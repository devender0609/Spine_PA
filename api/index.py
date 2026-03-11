from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from datetime import date, datetime

import anthropic
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

ROOT_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT_DIR / "public"
DB_FILE = ROOT_DIR / "spinepa_cases.db"
CONFIG_FILE = ROOT_DIR / "config.json"

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
CORS(app)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (value or "")).strip("_").upper()


def title_from_suffix(suffix: str) -> str:
    parts = re.split(r"[_\-\s]+", suffix.strip())
    return " ".join(p.title() for p in parts if p)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            status TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def load_providers() -> list[dict]:
    providers: list[dict] = []
    for key, value in os.environ.items():
        if key.startswith("PROVIDER_NPI_") and value:
            suffix = key.replace("PROVIDER_NPI_", "", 1)
            providers.append({
                "key": slug(suffix),
                "name": title_from_suffix(suffix),
                "npi": str(value).strip(),
            })
    providers.sort(key=lambda x: x["name"].lower())
    return providers


def resolve_npi(provider_name: str, providers: list[dict]) -> str:
    direct = os.environ.get("PROVIDER_NPI")
    if direct:
        return direct.strip()
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


def load_config() -> dict:
    config: dict = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            config = {}

    env_map = {
        "ANTHROPIC_API_KEY": "api_key",
        "PRACTICE_NAME": "practice_name",
        "PROVIDER_NAME": "provider_name",
        "ANTHROPIC_MODEL": "anthropic_model",
    }
    for env_name, config_key in env_map.items():
        if os.environ.get(env_name):
            config[config_key] = os.environ[env_name].strip()

    providers = load_providers()
    config["providers"] = providers
    config["npi"] = resolve_npi(config.get("provider_name", ""), providers)
    return config


def infer_cpt(proc_type: str) -> str:
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
    return mapping.get((proc_type or "").strip().lower(), "")


def proc_label(proc_type: str) -> str:
    labels = {
        "mri": "Lumbar MRI",
        "esi": "Epidural Steroid Injection",
        "fusion": "Lumbar Spinal Fusion",
        "pt": "Physical Therapy Extension",
    }
    key = (proc_type or "").strip().lower()
    return labels.get(key, proc_type or "Requested Procedure")


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


def conservative_analysis(data: dict) -> dict:
    notes = (data.get("notes") or "").lower()
    proc_type = str(data.get("proc_type") or "")
    missing: list[dict] = []

    if not data.get("diagnosis"):
        missing.append({"element": "Diagnosis", "detail": "Diagnosis is missing."})
    if not proc_type:
        missing.append({"element": "Requested Procedure", "detail": "Requested procedure is missing."})
    if not data.get("duration"):
        missing.append({"element": "Duration of Symptoms", "detail": "Duration was not entered."})
    if not data.get("pain_score"):
        missing.append({"element": "Pain Score", "detail": "Pain score was not entered."})

    if proc_type == "mri" and not any(k in notes for k in ["physical therapy", "pt", "conservative", "nsaid", "radicul", "numb", "weakness"]):
        missing.append({
            "element": "Conservative Treatment / Neurologic Detail",
            "detail": "Clinical notes do not clearly document failed conservative care and neurologic or radicular features.",
        })

    score_total = 6
    score_value = max(score_total - len(missing), 0)
    percent = int(round((score_value / score_total) * 100)) if score_total else 0
    likelihood = "high" if percent >= 84 else "moderate" if percent >= 50 else "low"

    return {
        "summary": "Structured case review completed.",
        "medical_necessity": "Review the generated package and fill any documentation gaps before manual submission.",
        "approval_likelihood": likelihood,
        "missing_elements": missing,
        "criteria_score": {
            "score": score_value,
            "total": score_total,
            "percent": percent,
            "band": likelihood.upper(),
        },
    }


def try_ai_json(prompt: str, api_key: str, model_name: str) -> dict | None:
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
            text = text[start:end + 1]
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
    attachments = [
        "Prior authorization letter",
        "Clinical notes or visit summary",
        "Relevant imaging report",
        "Physical therapy / conservative treatment documentation if applicable",
    ]
    return {
        "status": status,
        "missing": missing,
        "attachments": attachments,
        "next_steps": [
            "Review the generated letter for accuracy.",
            "Export the Word letter or PDF package.",
            "Upload the documents manually in the payer portal.",
        ],
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
    clinical_summary = notes or f"The patient presents for evaluation related to {diagnosis_text or 'the requested service'} with persistent symptoms documented in the intake form."
    medical_necessity = (
        f"Based on the documented diagnosis, symptom duration ({duration or 'not specified'}), "
        f"and current pain severity ({pain_score or 'not specified'}/10), {proc_name} is requested "
        f"as medically necessary to guide or provide appropriate treatment."
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


def row_to_case(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
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
        "letter": row["letter"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@app.route("/")
def home():
    if (PUBLIC_DIR / "index.html").exists():
        return send_from_directory(PUBLIC_DIR, "index.html")
    return jsonify({"running": True})


@app.route("/<path:path>")
def static_files(path: str):
    target = PUBLIC_DIR / path
    if target.exists():
        return send_from_directory(PUBLIC_DIR, path)
    return jsonify({"error": "Not found"}), 404


@app.route("/status")
def status():
    init_db()
    config = load_config()
    return jsonify({
        "running": True,
        "has_api_key": bool(config.get("api_key")),
        "practice_name": config.get("practice_name", ""),
        "provider_name": config.get("provider_name", ""),
        "npi": config.get("npi", ""),
        "providers": config.get("providers", []),
    })


@app.route("/analyze", methods=["POST"])
def analyze():
    config = load_config()
    data = request.json or {}
    proc_type = data.get("proc_type", "")
    patient = data.get("patient", "")
    payer = data.get("payer", "")
    diagnosis = data.get("diagnosis", "")
    provider = data.get("provider", "")
    provider_npi = data.get("provider_npi", "")
    pain_score = data.get("pain_score", "")
    duration = data.get("duration", "")
    notes = data.get("notes", "")
    cpt_code = infer_cpt(proc_type)
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(diagnosis)

    analysis = conservative_analysis(data)
    api_key = config.get("api_key")
    if api_key:
        prompt = f"""
You are a medical prior authorization specialist.
Analyze the following request and return JSON with keys: summary, medical_necessity, approval_likelihood, missing_elements.
For missing_elements, return a list of objects with keys "element" and "detail".

PATIENT: {patient}
PAYER: {payer}
ORDERING PROVIDER: {provider}
NPI: {provider_npi}
PROCEDURE: {proc_type}
CPT: {cpt_code}
DIAGNOSIS: {diagnosis_text}
ICD-10: {icd_code}
PAIN SCORE: {pain_score}
DURATION: {duration}
CLINICAL NOTES:
{notes}
"""
        ai_json = try_ai_json(
            prompt,
            api_key,
            config.get("anthropic_model") or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        )
        if isinstance(ai_json, dict):
            analysis = {**analysis, **ai_json}
            if "criteria_score" not in analysis:
                analysis["criteria_score"] = conservative_analysis(data)["criteria_score"]

    portal_helper = build_portal_helper(data, analysis)
    return jsonify({
        "analysis": analysis,
        "portal_helper": portal_helper,
        "echo_input": {
            "patient": patient,
            "payer": payer,
            "diagnosis": diagnosis,
            "provider": provider,
            "provider_npi": provider_npi,
        },
    })


@app.route("/generate-letter", methods=["POST"])
def generate_letter():
    config = load_config()
    data = request.json or {}
    providers = config.get("providers", [])
    if not data.get("provider"):
        data["provider"] = config.get("provider_name", "Treating Physician")
    if not data.get("provider_npi"):
        data["provider_npi"] = resolve_npi(data.get("provider", ""), providers) or config.get("npi", "")
    letter, structured = build_structured_letter(data, config.get("practice_name", "Spine Clinic"))
    return jsonify({
        "letter": letter,
        "structured": structured,
        "echo_input": {
            "patient": data.get("patient", ""),
            "payer": data.get("payer", ""),
            "dob": data.get("dob", ""),
            "member_id": data.get("member_id", data.get("memberId", "")),
        },
        **structured,
    })


@app.route("/build-package", methods=["POST"])
def build_package():
    config = load_config()
    data = request.json or {}
    helper = data.get("portalHelper") or {}
    letter = data.get("letter") or build_structured_letter(data, config.get("practice_name", "Spine Clinic"))[0]
    submission_checklist = helper.get("attachments", []) or [
        "Prior authorization letter",
        "Clinical notes or visit summary",
        "Relevant imaging report",
    ]
    clinical_summary = {
        "patient": data.get("patient", ""),
        "dob": data.get("dob", ""),
        "member_id": data.get("memberId") or data.get("member_id", ""),
        "payer": data.get("payer", ""),
        "diagnosis": data.get("diagnosis", ""),
        "procedure": proc_label(data.get("procType") or data.get("proc_type") or ""),
        "provider": data.get("provider", ""),
    }
    return jsonify({
        "clinical_summary": clinical_summary,
        "portal_helper": helper,
        "letter": letter,
        "submission_checklist": submission_checklist,
        "export_meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "practice_name": config.get("practice_name", "Spine Clinic"),
        },
    })


@app.route("/cases", methods=["GET"])
def list_cases():
    init_db()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cases ORDER BY datetime(updated_at) DESC, id DESC").fetchall()
    conn.close()
    return jsonify({"cases": [row_to_case(r) for r in rows]})


@app.route("/cases/<int:case_id>", methods=["GET"])
def get_case(case_id: int):
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Case not found"}), 404
    return jsonify({"case": row_to_case(row)})


@app.route("/cases", methods=["POST"])
def create_case():
    init_db()
    data = request.json or {}
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO cases (
            patient, fname, lname, dob, member_id, payer, diagnosis, proc_type,
            provider, provider_npi, referring_provider, pain_score, duration,
            notes, criteria_results, portal_helper, letter, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get("patient", ""),
            data.get("fname", ""),
            data.get("lname", ""),
            data.get("dob", ""),
            data.get("memberId", ""),
            data.get("payer", ""),
            data.get("diagnosis", ""),
            data.get("procType", ""),
            data.get("provider", ""),
            data.get("providerNpi", ""),
            data.get("referringProvider", ""),
            data.get("painScore", ""),
            data.get("duration", ""),
            data.get("notes", ""),
            json.dumps(data.get("criteriaResults", [])),
            json.dumps(data.get("portalHelper", {})),
            data.get("letter", ""),
            data.get("status", "submitted"),
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
    init_db()
    data = request.json or {}
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    existing = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Case not found"}), 404

    conn.execute(
        """
        UPDATE cases SET
            patient = ?, fname = ?, lname = ?, dob = ?, member_id = ?, payer = ?,
            diagnosis = ?, proc_type = ?, provider = ?, provider_npi = ?, referring_provider = ?,
            pain_score = ?, duration = ?, notes = ?, criteria_results = ?, portal_helper = ?,
            letter = ?, status = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            data.get("patient", ""),
            data.get("fname", ""),
            data.get("lname", ""),
            data.get("dob", ""),
            data.get("memberId", ""),
            data.get("payer", ""),
            data.get("diagnosis", ""),
            data.get("procType", ""),
            data.get("provider", ""),
            data.get("providerNpi", ""),
            data.get("referringProvider", ""),
            data.get("painScore", ""),
            data.get("duration", ""),
            data.get("notes", ""),
            json.dumps(data.get("criteriaResults", [])),
            json.dumps(data.get("portalHelper", {})),
            data.get("letter", ""),
            data.get("status", existing["status"]),
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
    init_db()
    conn = get_conn()
    existing = conn.execute("SELECT id FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Case not found"}), 404
    conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)