from __future__ import annotations

import json
import os
import re
from pathlib import Path
from datetime import date

import anthropic
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
CORS(app)

CONFIG_FILE = ROOT_DIR / "config.json"


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (value or "")).strip("_").upper()


def title_from_suffix(suffix: str) -> str:
    parts = re.split(r"[_\-\s]+", suffix.strip())
    return " ".join(p.title() for p in parts if p)


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

    providers = load_providers()
    config["providers"] = providers
    default_provider = config.get("provider_name", "")
    config["npi"] = resolve_npi(default_provider, providers)
    return config


def conservative_analysis(data: dict) -> dict:
    notes = (data.get("notes") or "").lower()
    pain_score = str(data.get("pain_score") or "")
    duration = str(data.get("duration") or "")
    diagnosis = str(data.get("diagnosis") or "")
    proc_type = str(data.get("proc_type") or "")

    missing = []
    if not diagnosis:
        missing.append("Diagnosis")
    if not proc_type:
        missing.append("Requested procedure")
    if not duration:
        missing.append("Duration of symptoms")
    if not pain_score:
        missing.append("Pain score")

    if proc_type == "mri" and not any(
        k in notes for k in ["physical therapy", "pt", "conservative", "nsaid", "neurolog", "radicul", "numb", "weakness"]
    ):
        missing.append("Conservative treatment and neurologic/radicular detail")

    likelihood = "high" if len(missing) == 0 else "moderate" if len(missing) <= 2 else "low"
    return {
        "summary": "Structured case review completed.",
        "medical_necessity": "Review the generated package and fill any documentation gaps before manual submission.",
        "approval_likelihood": likelihood,
        "missing_elements": missing,
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
    missing = analysis.get("missing_elements") if isinstance(analysis, dict) else []
    missing = [m if isinstance(m, str) else json.dumps(m) for m in (missing or [])]
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
    referring_provider = (data.get("referring_provider") or "").strip()
    provider = (data.get("provider") or "Treating Physician").strip()
    provider_npi = (data.get("provider_npi") or "").strip()

    cpt_code = infer_cpt(proc_type)
    proc_name = proc_label(proc_type)
    today = date.today().strftime("%B %d, %Y")

    clinical_summary = (
        notes
        if notes
        else f"The patient presents for evaluation related to {diagnosis_text or 'the requested service'} with persistent symptoms documented in the intake form."
    )

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


@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path: str):
    target = PUBLIC_DIR / path
    if target.exists():
        return send_from_directory(PUBLIC_DIR, path)
    return jsonify({"error": "Not found"}), 404


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
        }
    )


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

    portal_helper = build_portal_helper(data, analysis)
    return jsonify(
        {
            "analysis": analysis,
            "portal_helper": portal_helper,
            "echo_input": {
                "patient": patient,
                "payer": payer,
                "diagnosis": diagnosis,
                "provider": provider,
                "provider_npi": provider_npi,
            },
        }
    )


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

    return jsonify(
        {
            "letter": letter,
            "structured": structured,
            "echo_input": {
                "patient": data.get("patient", ""),
                "payer": data.get("payer", ""),
                "dob": data.get("dob", ""),
                "member_id": data.get("member_id", data.get("memberId", "")),
            },
            **structured,
        }
    )


@app.route("/build-package", methods=["POST"])
def build_package():
    config = load_config()
    data = request.json or {}

    helper = data.get("portalHelper") or {}
    letter = data.get("letter") or build_structured_letter(data, config.get("practice_name", "Spine Clinic"))[0]

    clinical_summary = {
        "patient": data.get("patient", ""),
        "dob": data.get("dob", ""),
        "member_id": data.get("memberId") or data.get("member_id", ""),
        "payer": data.get("payer", ""),
        "diagnosis": data.get("diagnosis", ""),
        "procedure": proc_label(data.get("procType") or data.get("proc_type") or ""),
        "provider": data.get("provider", ""),
    }

    return jsonify(
        {
            "clinical_summary": clinical_summary,
            "portal_helper": helper,
            "letter": letter,
            "submission_checklist": helper.get("attachments", []),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)