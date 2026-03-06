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

app = Flask(
    __name__,
    static_folder=str(PUBLIC_DIR),
    static_url_path=""
)

CORS(app)

CONFIG_FILE = ROOT_DIR / "config.json"


# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------

def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (value or "")).strip("_").upper()


def title_from_suffix(suffix: str) -> str:
    parts = re.split(r"[_\-\s]+", suffix.strip())
    return " ".join(p.title() for p in parts if p)


def load_providers() -> list[dict]:
    providers = []

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

    # fallback to last token, e.g. "Dr Truumees" -> "TRUUMEES"
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


def normalize_diagnosis_and_icd(diagnosis: str) -> tuple[str, str]:
    """
    Accepts values like:
      'M54.5 — Low Back Pain'
      'M54.5 - Low Back Pain'
      'Low Back Pain'
    Returns:
      (diagnosis_text, icd_code)
    """
    raw = (diagnosis or "").strip()
    if not raw:
        return "", ""

    match = re.match(r"^\s*([A-Z][0-9A-Z][0-9A-Z](?:\.[0-9A-Z]+)?)\s*[-—:]\s*(.+?)\s*$", raw)
    if match:
        icd = match.group(1).strip()
        diag_text = match.group(2).strip()
        return diag_text, icd

    # if it just looks like an ICD code
    if re.match(r"^[A-Z][0-9A-Z][0-9A-Z](?:\.[0-9A-Z]+)?$", raw):
        return "", raw

    return raw, ""


def load_config() -> dict:
    config = {}

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


# ------------------------------------------------------------
# Static UI
# ------------------------------------------------------------

@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path: str):
    target = PUBLIC_DIR / path

    if target.exists():
        return send_from_directory(PUBLIC_DIR, path)

    return jsonify({"error": "Not found"}), 404


# ------------------------------------------------------------
# Status endpoint
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# AI Analysis
# ------------------------------------------------------------

@app.route("/analyze", methods=["POST"])
def analyze():
    config = load_config()
    api_key = config.get("api_key")

    if not api_key:
        return jsonify({"error": "Missing ANTHROPIC_API_KEY"}), 400

    data = request.json or {}

    notes = data.get("notes", "")
    proc_type = data.get("proc_type", "")
    patient = data.get("patient", "")
    payer = data.get("payer", "")
    diagnosis = data.get("diagnosis", "")
    provider = data.get("provider", "")
    provider_npi = data.get("provider_npi", "")
    pain_score = data.get("pain_score", "")
    duration = data.get("duration", "")

    cpt_code = infer_cpt(proc_type)
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(diagnosis)

    prompt = f"""
You are a medical prior authorization specialist.

Analyze the following request and determine whether it likely meets payer criteria.

PATIENT
Name: {patient}
Payer: {payer}

PROVIDER
Ordering Provider: {provider}
Provider NPI: {provider_npi}

REQUESTED SERVICE
Procedure: {proc_type}
CPT Code: {cpt_code}
Diagnosis: {diagnosis_text}
ICD-10: {icd_code}
Pain Score: {pain_score}
Duration of Symptoms: {duration}

CLINICAL NOTES
{notes}

Return a structured response in JSON with:
- summary
- medical_necessity
- approval_likelihood
- missing_elements
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        model_name = config.get("anthropic_model") or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        response = client.messages.create(
            model=model_name,
            max_tokens=1400,
            messages=[{"role": "user", "content": prompt}],
        )

        result = response.content[0].text
        return jsonify({"analysis": result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------
# Generate Authorization Letter
# ------------------------------------------------------------

@app.route("/generate-letter", methods=["POST"])
def generate_letter():
    config = load_config()
    api_key = config.get("api_key")

    if not api_key:
        return jsonify({"error": "Missing ANTHROPIC_API_KEY"}), 400

    providers = config.get("providers", [])
    data = request.json or {}

    # structured fields from frontend
    notes = data.get("notes", "")
    payer = data.get("payer", "")
    patient = data.get("patient", "")
    dob = data.get("dob", "")
    member_id = data.get("member_id", "")
    diagnosis_raw = data.get("diagnosis", "")
    proc_type = data.get("proc_type", "")
    pain_score = data.get("pain_score", "")
    duration = data.get("duration", "")
    referring_provider = data.get("referring_provider", "")

    provider = (data.get("provider") or config.get("provider_name") or "Treating Physician").strip()
    provider_npi = (data.get("provider_npi") or resolve_npi(provider, providers) or config.get("npi", "")).strip()

    cpt_code = infer_cpt(proc_type)
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(diagnosis_raw)

    practice_name = config.get("practice_name", "Spine Clinic")
    today = date.today().strftime("%B %d, %Y")

    prompt = f"""
Write a professional prior authorization request letter.

Use a formal insurance authorization letter format.

DATE: {today}

PATIENT INFORMATION
Patient Name: {patient}
Date of Birth: {dob}
Insurance / Payer: {payer}
Member ID: {member_id}

PROVIDER INFORMATION
Ordering Provider: {provider}
Provider NPI: {provider_npi}
Referring Provider: {referring_provider}
Practice Name: {practice_name}

REQUESTED SERVICE
Procedure Requested: {proc_type}
CPT Code: {cpt_code}
Diagnosis: {diagnosis_text}
ICD-10 Code: {icd_code}
Pain Score: {pain_score}
Duration of Symptoms: {duration}

CLINICAL NOTES
{notes}

Write the letter with these sections:
1. Patient Information
2. Clinical Summary
3. Medical Necessity
4. Requested Procedure and Coding
5. Closing Request / Conclusion

Important instructions:
- Do not invent missing patient facts.
- Use the structured fields provided above exactly when available.
- Use the clinical notes to support medical necessity.
- Make the letter persuasive, clean, and professional.
- Include provider name and NPI in the letter body.
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        model_name = config.get("anthropic_model") or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        response = client.messages.create(
            model=model_name,
            max_tokens=2200,
            messages=[{"role": "user", "content": prompt}],
        )

        return jsonify(
            {
                "letter": response.content[0].text,
                "provider": provider,
                "provider_npi": provider_npi,
                "cpt_code": cpt_code,
                "icd_10": icd_code,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500