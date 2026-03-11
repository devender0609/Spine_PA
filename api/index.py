from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

try:
    import anthropic
except Exception:  # pragma: no cover
    anthropic = None

from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"
# On Vercel the project filesystem is read-only. Use /tmp when available.
DB_FILE = Path(os.environ.get("SPINEPA_DB_FILE", "/tmp/spinepa_cases.db"))
CONFIG_FILE = ROOT_DIR / "config.json"

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
CORS(app)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (value or "")).strip("_").upper()


def title_from_suffix(suffix: str) -> str:
    parts = re.split(r"[_\-\s]+", suffix.strip())
    return " ".join(p.title() for p in parts if p)


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def get_conn() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_uid TEXT,
            patient TEXT,
            fname TEXT,
            lname TEXT,
            dob TEXT,
            member_id TEXT,
            payer TEXT,
            diagnosis TEXT,
            proc_type TEXT,
            provider TEXT,
            provider_npi TEXT,
            referring_provider TEXT,
            pain_score TEXT,
            duration TEXT,
            notes TEXT,
            criteria_results TEXT,
            portal_helper TEXT,
            letter TEXT,
            package_json TEXT,
            status TEXT,
            storage_source TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    columns = {row[1] for row in conn.execute("PRAGMA table_info(cases)").fetchall()}
    migrations = {
        "case_uid": "ALTER TABLE cases ADD COLUMN case_uid TEXT",
        "package_json": "ALTER TABLE cases ADD COLUMN package_json TEXT",
        "storage_source": "ALTER TABLE cases ADD COLUMN storage_source TEXT",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)

    conn.commit()
    conn.close()


init_db()


def load_config() -> dict:
    config: dict = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            config = {}

    if os.environ.get("ANTHROPIC_API_KEY"):
        config["api_key"] = os.environ["ANTHROPIC_API_KEY"].strip()
    if os.environ.get("PRACTICE_NAME"):
        config["practice_name"] = os.environ["PRACTICE_NAME"].strip()
    if os.environ.get("PROVIDER_NAME"):
        config["provider_name"] = os.environ["PROVIDER_NAME"].strip()
    if os.environ.get("ANTHROPIC_MODEL"):
        config["anthropic_model"] = os.environ["ANTHROPIC_MODEL"].strip()

    config["providers"] = load_providers()
    config["npi"] = resolve_npi(config.get("provider_name", ""), config["providers"])
    return config


def load_providers() -> list[dict]:
    providers: list[dict] = []
    for key, value in os.environ.items():
        if key.startswith("PROVIDER_NPI_") and value:
            suffix = key.replace("PROVIDER_NPI_", "", 1)
            providers.append(
                {
                    "key": slug(suffix),
                    "name": title_from_suffix(suffix),
                    "npi": str(value).strip(),
                }
            )
    providers.sort(key=lambda x: x["name"].lower())
    return providers


def resolve_npi(provider_name: str, providers: list[dict]) -> str:
    if os.environ.get("PROVIDER_NPI"):
        return os.environ["PROVIDER_NPI"].strip()

    wanted = slug(provider_name)
    for provider in providers:
        if provider["key"] == wanted:
            return provider["npi"]

    parts = (provider_name or "").strip().split()
    if parts:
        last = slug(parts[-1])
        for provider in providers:
            if provider["key"] == last:
                return provider["npi"]
    return ""


def infer_cpt(proc_type: str) -> str:
    proc = (proc_type or "").strip().lower()
    mapping = {
        "mri": "72148",
        "lumbar mri": "72148",
        "cervical mri": "72141",
        "thoracic mri": "72146",
        "esi": "62323 / 64483",
        "epidural steroid injection": "62323 / 64483",
        "fusion": "22612",
        "lumbar fusion": "22612",
        "pt": "97110",
        "physical therapy": "97110",
    }
    return mapping.get(proc, "")


def proc_label(proc_type: str) -> str:
    proc = (proc_type or "").strip().lower()
    labels = {
        "mri": "Lumbar MRI",
        "esi": "Epidural Steroid Injection",
        "fusion": "Lumbar Spinal Fusion",
        "pt": "Physical Therapy Extension",
    }
    return labels.get(proc, proc_type or "Requested Procedure")


def normalize_diagnosis_and_icd(diagnosis: str) -> tuple[str, str]:
    raw = (diagnosis or "").strip()
    if not raw:
        return "", ""
    match = re.match(r"^\s*([A-Z][0-9A-Z][0-9A-Z](?:\.[0-9A-Z]+)?)\s*[-—:]\s*(.+?)\s*$", raw)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    if re.match(r"^[A-Z][0-9A-Z][0-9A-Z](?:\.[0-9A-Z]+)?$", raw):
        return "", raw
    return raw, ""


def has_specific_icd(icd_code: str) -> bool:
    if not icd_code:
        return False
    if "." not in icd_code:
        return False
    tail = icd_code.split(".", 1)[1]
    return bool(tail and not re.fullmatch(r"X+", tail, re.I))


def duration_is_short(duration: str) -> bool:
    value = (duration or "").lower()
    return "less than 4 weeks" in value or value.startswith("4–6") or value.startswith("4-6")


def conservative_analysis(data: dict) -> dict:
    notes = (data.get("notes") or "").lower()
    pain_score = str(data.get("pain_score") or data.get("painScore") or "").strip()
    duration = str(data.get("duration") or "").strip()
    diagnosis = str(data.get("diagnosis") or "").strip()
    proc_type = str(data.get("proc_type") or data.get("procType") or "").strip().lower()
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(diagnosis)

    missing: list[dict] = []
    strengths: list[str] = []

    if diagnosis:
        strengths.append("Diagnosis entered")
    else:
        missing.append({"element": "Diagnosis", "detail": "Diagnosis is missing."})

    if proc_type:
        strengths.append("Procedure selected")
    else:
        missing.append({"element": "Requested Procedure", "detail": "Requested procedure is missing."})

    if duration:
        strengths.append(f"Symptom duration documented ({duration})")
    else:
        missing.append({"element": "Duration of Symptoms", "detail": "Duration was not entered."})

    if pain_score:
        strengths.append(f"Pain score documented ({pain_score}/10)")
    else:
        missing.append({"element": "Pain Score", "detail": "Pain score was not entered."})

    if not icd_code:
        missing.append({"element": "ICD-10 Code", "detail": "No ICD-10 diagnosis code was detected."})
    elif not has_specific_icd(icd_code):
        missing.append({"element": "ICD-10 Code Specificity", "detail": f"{icd_code} may be too broad or incomplete for some payers; use the most specific supported code."})
    else:
        strengths.append(f"Specific ICD-10 code documented ({icd_code})")

    neuro_terms = ["radicular", "radiating", "radiculopathy", "numb", "weak", "sciatica", "paresthesia", "motor deficit"]
    conservative_terms = ["physical therapy", "pt", "home exercise", "nsaid", "medication", "chiropractic", "conservative", "activity modification"]
    imaging_terms = ["mri", "ct", "stenosis", "herniation", "disc bulge", "foraminal", "compression"]

    has_neuro = any(term in notes for term in neuro_terms)
    has_conservative = any(term in notes for term in conservative_terms)
    has_imaging = any(term in notes for term in imaging_terms)

    if notes:
        strengths.append("Clinical note or structured summary provided")

    if proc_type == "mri":
        if not has_conservative and not duration:
            missing.append({"element": "Conservative Treatment", "detail": "Clinical notes do not clearly document prior conservative management."})
        if not has_neuro:
            missing.append({"element": "Neurologic / Radicular Features", "detail": "Clinical notes do not clearly document neurologic, radicular, numbness, weakness, or sciatica symptoms."})
    elif proc_type == "esi":
        if not has_imaging:
            missing.append({"element": "Imaging Support", "detail": "Clinical notes do not clearly mention imaging evidence such as stenosis, herniation, or nerve compression."})
        if not has_neuro:
            missing.append({"element": "Radicular Symptoms", "detail": "Clinical notes do not clearly document radicular symptoms."})
    elif proc_type == "fusion":
        if not has_conservative and duration_is_short(duration):
            missing.append({"element": "Failed Conservative Treatment", "detail": "Fusion requests usually require documented nonoperative treatment and adequate symptom duration."})
        if pain_score and pain_score.isdigit() and int(pain_score) < 6:
            missing.append({"element": "Functional Severity", "detail": "Pain severity appears relatively low for a fusion request; make sure disability and failed treatment are documented."})
    elif proc_type == "pt":
        if not notes:
            missing.append({"element": "Therapy Progress / Goals", "detail": "PT extension requests are stronger when current progress and remaining goals are documented."})

    likelihood = "high" if len(missing) == 0 else "moderate" if len(missing) <= 2 else "low"

    return {
        "summary": "Structured payer readiness review completed.",
        "medical_necessity": (
            f"Review supports {proc_label(proc_type)} based on the entered diagnosis, symptom duration, pain severity, and available clinical details. "
            "Resolve any missing documentation before manual submission."
        ),
        "approval_likelihood": likelihood,
        "strengths": strengths,
        "missing_elements": missing,
    }


def try_ai_json(prompt: str, api_key: str, model_name: str) -> dict | None:
    if anthropic is None:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            max_tokens=1400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        if fenced:
            text = fenced.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
        return json.loads(text)
    except Exception:
        return None


def build_portal_helper(data: dict, analysis: dict) -> dict:
    raw_missing = analysis.get("missing_elements") if isinstance(analysis, dict) else []
    missing = []
    for item in raw_missing or []:
        if isinstance(item, dict):
            missing.append(item)
        else:
            missing.append({"element": str(item), "detail": ""})

    status = "Ready for manual submission" if not missing else "Needs review before manual submission"
    proc_name = proc_label(data.get("proc_type") or data.get("procType") or "")

    return {
        "status": status,
        "missing": missing,
        "attachments": [
            "Prior authorization letter",
            "Clinical notes or visit summary",
            "Relevant imaging report",
            "Physical therapy / conservative treatment documentation if applicable",
        ],
        "next_steps": [
            "Review all patient, payer, diagnosis, and provider fields for accuracy.",
            "Resolve any missing required items flagged below.",
            f"Export the {proc_name} package and upload it manually in the payer portal.",
        ],
    }


def normalize_case_payload(data: dict, config: dict | None = None) -> dict:
    config = config or load_config()
    providers = config.get("providers", [])

    fname = (data.get("fname") or "").strip()
    lname = (data.get("lname") or "").strip()
    patient = (data.get("patient") or f"{fname} {lname}").strip()
    provider = (data.get("provider") or config.get("provider_name") or "Treating Physician").strip()
    provider_npi = (data.get("provider_npi") or data.get("providerNpi") or "").strip()
    if not provider_npi:
        provider_npi = resolve_npi(provider, providers) or config.get("npi", "")

    member_id = (data.get("member_id") or data.get("memberId") or "").strip()
    proc_type = (data.get("proc_type") or data.get("procType") or "").strip().lower()

    return {
        "case_uid": (data.get("case_uid") or data.get("caseUid") or "").strip(),
        "patient": patient,
        "fname": fname,
        "lname": lname,
        "dob": (data.get("dob") or "").strip(),
        "member_id": member_id,
        "payer": (data.get("payer") or "").strip(),
        "diagnosis": (data.get("diagnosis") or "").strip(),
        "proc_type": proc_type,
        "provider": provider,
        "provider_npi": provider_npi,
        "referring_provider": (data.get("referring_provider") or data.get("referringProvider") or "").strip(),
        "pain_score": str(data.get("pain_score") or data.get("painScore") or "").strip(),
        "duration": str(data.get("duration") or "").strip(),
        "notes": (data.get("notes") or "").strip(),
        "criteria_results": data.get("criteria_results") or data.get("criteriaResults") or [],
        "portal_helper": data.get("portal_helper") or data.get("portalHelper") or {},
        "letter": (data.get("letter") or "").strip(),
        "package_json": data.get("package_json") or data.get("packageJson") or {},
        "status": (data.get("status") or "submitted").strip() or "submitted",
        "storage_source": (data.get("storage_source") or data.get("storageSource") or "backend").strip() or "backend",
    }


def build_structured_letter(data: dict, practice_name: str) -> tuple[str, dict]:
    patient = (data.get("patient") or "").strip()
    dob = (data.get("dob") or "").strip()
    member_id = (data.get("member_id") or data.get("memberId") or "").strip()
    payer = (data.get("payer") or "").strip()

    diagnosis_raw = data.get("diagnosis") or ""
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(diagnosis_raw)

    proc_type = (data.get("proc_type") or data.get("procType") or "").strip()
    pain_score = (data.get("pain_score") or data.get("painScore") or "").strip()
    duration = (data.get("duration") or "").strip()
    notes = (data.get("notes") or "").strip()
    referring_provider = (data.get("referring_provider") or data.get("referringProvider") or "").strip()
    provider = (data.get("provider") or "Treating Physician").strip()
    provider_npi = (data.get("provider_npi") or data.get("providerNpi") or "").strip()

    cpt_code = infer_cpt(proc_type)
    proc_name = proc_label(proc_type)
    today = date.today().strftime("%B %d, %Y")

    clinical_summary = (
        notes
        if notes
        else f"The patient presents for evaluation related to {diagnosis_text or diagnosis_raw or 'the requested service'} with persistent symptoms documented in the intake form."
    )

    medical_necessity = (
        f"Based on the documented diagnosis, symptom duration ({duration or 'not specified'}), and current pain severity ({pain_score or 'not specified'}/10), "
        f"{proc_name} is requested as medically necessary to guide or provide appropriate treatment."
    )

    letter = f"""# PRIOR AUTHORIZATION REQUEST LETTER

DATE: {today}

TO: {payer or 'Insurance Prior Authorization Department'}

FROM: {provider} | NPI: {provider_npi or '[NPI Not Provided]'}
{practice_name}

RE: Prior Authorization Request – {proc_name} (CPT {cpt_code or 'N/A'})

## 1. PATIENT INFORMATION

Patient Name: {patient or '[Patient Name Not Provided]'}
Date of Birth: {dob or '[DOB Not Provided]'}
Insurance / Payer: {payer or '[Payer Not Provided]'}
Member ID: {member_id or '[Member ID Not Provided]'}

## 2. CLINICAL SUMMARY

{clinical_summary}

## 3. MEDICAL NECESSITY

{medical_necessity}

## 4. REQUESTED PROCEDURE AND CODING

Procedure Requested: {proc_name}
CPT Code: {cpt_code or 'N/A'}
Diagnosis: {diagnosis_text or diagnosis_raw or '[Diagnosis Not Provided]'}
ICD-10 Code: {icd_code or '[ICD-10 Not Provided]'}
Pain Score: {pain_score or '[Not Provided]'}
Duration of Symptoms: {duration or '[Not Provided]'}
Ordering Provider: {provider}
Provider NPI: {provider_npi or '[NPI Not Provided]'}
Referring Provider: {referring_provider or '[Not Provided]'}
Practice Name: {practice_name}

## 5. CLOSING REQUEST / CONCLUSION

Please review this request for prior authorization. Supporting clinical documentation is available for manual portal submission. If additional information is needed, please contact our office.

Respectfully,

{provider}
Ordering Provider | NPI: {provider_npi or '[NPI Not Provided]'}
{practice_name}
"""

    structured = {
        "patient": patient,
        "dob": dob,
        "member_id": member_id,
        "payer": payer,
        "procedure": proc_name,
        "cpt_code": cpt_code,
        "diagnosis": diagnosis_text or diagnosis_raw,
        "icd_10": icd_code,
        "provider": provider,
        "provider_npi": provider_npi,
        "referring_provider": referring_provider,
    }
    return letter, structured


def build_package_payload(data: dict, config: dict) -> dict:
    normalized = normalize_case_payload(data, config)
    letter, structured = build_structured_letter(normalized, config.get("practice_name", "Spine Clinic"))

    analysis = conservative_analysis(normalized)
    helper = normalized.get("portal_helper") or build_portal_helper(normalized, analysis)
    criteria_results = normalized.get("criteria_results") or []

    package = {
        "generated_at": now_iso(),
        "practice_name": config.get("practice_name", "Spine Clinic"),
        "patient": {
            "name": normalized["patient"],
            "dob": normalized["dob"],
            "member_id": normalized["member_id"],
            "payer": normalized["payer"],
        },
        "request": {
            "procedure": structured["procedure"],
            "cpt_code": structured["cpt_code"],
            "diagnosis": structured["diagnosis"],
            "icd_10": structured["icd_10"],
            "pain_score": normalized["pain_score"],
            "duration": normalized["duration"],
        },
        "providers": {
            "ordering_provider": normalized["provider"],
            "provider_npi": normalized["provider_npi"],
            "referring_provider": normalized["referring_provider"],
        },
        "clinical_notes": normalized["notes"],
        "criteria_results": criteria_results,
        "analysis": analysis,
        "portal_helper": helper,
        "letter": normalized["letter"] or letter,
        "submission_checklist": helper.get("attachments", []),
    }
    return package


def row_to_case(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "caseUid": row["case_uid"] or f"CASE-{row['id']}",
        "patient": row["patient"],
        "fname": row["fname"],
        "lname": row["lname"],
        "dob": row["dob"],
        "memberId": row["member_id"],
        "payer": row["payer"],
        "diagnosis": row["diagnosis"],
        "procType": row["proc_type"],
        "provider": row["provider"],
        "providerNpi": row["provider_npi"],
        "referringProvider": row["referring_provider"],
        "painScore": row["pain_score"],
        "duration": row["duration"],
        "notes": row["notes"],
        "criteriaResults": json.loads(row["criteria_results"] or "[]"),
        "portalHelper": json.loads(row["portal_helper"] or "{}"),
        "packageJson": json.loads(row["package_json"] or "{}"),
        "letter": row["letter"],
        "status": row["status"],
        "storageSource": row["storage_source"] or "backend",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


# ─────────────────────────────────────────────────────────────
# Static routes
# ─────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path: str):
    target = PUBLIC_DIR / path
    if target.exists():
        return send_from_directory(PUBLIC_DIR, path)
    return jsonify({"error": "Not found"}), 404


# ─────────────────────────────────────────────────────────────
# Status / settings / analysis / letter / packages
# ─────────────────────────────────────────────────────────────

@app.route("/status")
def status():
    config = load_config()
    return jsonify(
        {
            "running": True,
            "has_api_key": bool(config.get("api_key")),
            "practice_name": config.get("practice_name", ""),
            "provider_name": config.get("provider_name", ""),
            "npi": config.get("npi", ""),
            "providers": config.get("providers", []),
            "storage_mode": "ephemeral_backend_sqlite",
            "db_file": str(DB_FILE),
        }
    )


@app.route("/settings")
def settings():
    config = load_config()
    return jsonify(
        {
            "practice_name": config.get("practice_name", "Spine Clinic"),
            "provider_name": config.get("provider_name", "Treating Physician"),
            "has_api_key": bool(config.get("api_key")),
            "providers": config.get("providers", []),
        }
    )


@app.route("/analyze", methods=["POST"])
def analyze():
    config = load_config()
    normalized = normalize_case_payload(request.json or {}, config)

    cpt_code = infer_cpt(normalized["proc_type"])
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(normalized["diagnosis"])

    analysis = conservative_analysis(normalized)
    api_key = config.get("api_key")

    if api_key:
        prompt = f"""
You are a medical prior authorization specialist.
Analyze the following request and return JSON with keys: summary, medical_necessity, approval_likelihood, strengths, missing_elements.
For missing_elements, return a list of objects with keys "element" and "detail".
Do not change patient demographic values.

PATIENT: {normalized['patient']}
PAYER: {normalized['payer']}
ORDERING PROVIDER: {normalized['provider']}
NPI: {normalized['provider_npi']}
PROCEDURE: {normalized['proc_type']}
CPT: {cpt_code}
DIAGNOSIS: {diagnosis_text}
ICD-10: {icd_code}
PAIN SCORE: {normalized['pain_score']}
DURATION: {normalized['duration']}
CLINICAL NOTES:
{normalized['notes']}
"""
        ai_json = try_ai_json(
            prompt,
            api_key,
            config.get("anthropic_model") or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        )
        if isinstance(ai_json, dict):
            analysis = {**analysis, **ai_json}

    portal_helper = build_portal_helper(normalized, analysis)

    return jsonify(
        {
            "analysis": analysis,
            "portal_helper": portal_helper,
            "echo_input": {
                "patient": normalized["patient"],
                "payer": normalized["payer"],
                "diagnosis": normalized["diagnosis"],
                "provider": normalized["provider"],
                "provider_npi": normalized["provider_npi"],
            },
        }
    )


@app.route("/generate-letter", methods=["POST"])
def generate_letter():
    config = load_config()
    normalized = normalize_case_payload(request.json or {}, config)
    letter, structured = build_structured_letter(normalized, config.get("practice_name", "Spine Clinic"))

    return jsonify(
        {
            "letter": letter,
            "structured": structured,
            "echo_input": {
                "patient": normalized["patient"],
                "payer": normalized["payer"],
                "dob": normalized["dob"],
                "member_id": normalized["member_id"],
            },
            **structured,
        }
    )


@app.route("/build-package", methods=["POST"])
def build_package():
    config = load_config()
    package = build_package_payload(request.json or {}, config)
    return jsonify(package)


@app.route("/export-package", methods=["POST"])
def export_package():
    config = load_config()
    package = build_package_payload(request.json or {}, config)

    export_dir = Path("/tmp/spinepa_exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    case_stub = slug(package["patient"].get("name", "case") or "case")[:40] or "CASE"
    outfile = export_dir / f"{case_stub}_PA_PACKAGE.json"
    outfile.write_text(json.dumps(package, indent=2), encoding="utf-8")
    return send_file(outfile, as_attachment=True, download_name=outfile.name, mimetype="application/json")


# ─────────────────────────────────────────────────────────────
# Repository routes
# ─────────────────────────────────────────────────────────────

@app.route("/cases", methods=["GET"])
def list_cases():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cases ORDER BY datetime(updated_at) DESC, id DESC").fetchall()
    conn.close()
    return jsonify({"cases": [row_to_case(r) for r in rows]})


@app.route("/cases/<int:case_id>", methods=["GET"])
def get_case(case_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Case not found"}), 404
    return jsonify({"case": row_to_case(row)})


@app.route("/cases", methods=["POST"])
def create_case():
    config = load_config()
    payload = normalize_case_payload(request.json or {}, config)
    package = build_package_payload(payload, config)
    now = now_iso()

    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO cases (
            case_uid, patient, fname, lname, dob, member_id, payer, diagnosis, proc_type,
            provider, provider_npi, referring_provider, pain_score, duration,
            notes, criteria_results, portal_helper, letter, package_json, status, storage_source,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["case_uid"] or f"CASE-{slug(payload['patient']) or 'PATIENT'}-{int(datetime.utcnow().timestamp())}",
            payload["patient"],
            payload["fname"],
            payload["lname"],
            payload["dob"],
            payload["member_id"],
            payload["payer"],
            payload["diagnosis"],
            payload["proc_type"],
            payload["provider"],
            payload["provider_npi"],
            payload["referring_provider"],
            payload["pain_score"],
            payload["duration"],
            payload["notes"],
            json.dumps(payload["criteria_results"]),
            json.dumps(payload["portal_helper"]),
            payload["letter"] or package["letter"],
            json.dumps(package),
            payload["status"],
            payload["storage_source"],
            now,
            now,
        ),
    )
    conn.commit()
    case_id = cur.lastrowid
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()

    return jsonify({"case": row_to_case(row)}), 201


@app.route("/cases/<int:case_id>", methods=["PUT"])
def update_case(case_id: int):
    config = load_config()
    payload = normalize_case_payload(request.json or {}, config)
    package = build_package_payload(payload, config)
    now = now_iso()

    conn = get_conn()
    existing = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Case not found"}), 404

    conn.execute(
        """
        UPDATE cases SET
            case_uid = ?, patient = ?, fname = ?, lname = ?, dob = ?, member_id = ?, payer = ?,
            diagnosis = ?, proc_type = ?, provider = ?, provider_npi = ?, referring_provider = ?,
            pain_score = ?, duration = ?, notes = ?, criteria_results = ?, portal_helper = ?,
            letter = ?, package_json = ?, status = ?, storage_source = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            payload["case_uid"] or existing["case_uid"] or f"CASE-{case_id}",
            payload["patient"],
            payload["fname"],
            payload["lname"],
            payload["dob"],
            payload["member_id"],
            payload["payer"],
            payload["diagnosis"],
            payload["proc_type"],
            payload["provider"],
            payload["provider_npi"],
            payload["referring_provider"],
            payload["pain_score"],
            payload["duration"],
            payload["notes"],
            json.dumps(payload["criteria_results"]),
            json.dumps(payload["portal_helper"]),
            payload["letter"] or package["letter"],
            json.dumps(package),
            payload["status"] or existing["status"] or "submitted",
            payload["storage_source"] or existing["storage_source"] or "backend",
            now,
            case_id,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()

    return jsonify({"case": row_to_case(row)})


@app.route("/cases/<int:case_id>", methods=["DELETE"])
def delete_case(case_id: int):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Case not found"}), 404

    conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
