"""SpinePA Agent — Flask app for Vercel."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import anthropic
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

ROOT_DIR = Path(__file__).resolve().parents[1]   # .../app
PUBLIC_DIR = ROOT_DIR / "public"
CONFIG_FILE = ROOT_DIR / "config.json"

app = Flask(__name__)
CORS(app)

CRITERIA = {
    "mri": [
        {"id": "c1", "label": "6+ weeks of conservative treatment documented", "required": True},
        {"id": "c2", "label": "Failure to improve with conservative management", "required": True},
        {"id": "c3", "label": "Specific radicular or neurological symptoms", "required": True},
        {"id": "c4", "label": "Red flag symptoms documented (or absence confirmed)", "required": False},
        {"id": "c5", "label": "VAS / pain score documented", "required": True},
        {"id": "c6", "label": "Physical exam findings documented", "required": True},
    ],
    "esi": [
        {"id": "e1", "label": "MRI or CT evidence of disc herniation or stenosis", "required": True},
        {"id": "e2", "label": "Radicular symptoms with dermatomal distribution", "required": True},
        {"id": "e3", "label": "Failed conservative treatment (PT + medications)", "required": True},
        {"id": "e4", "label": "VAS pain score >= 6 documented", "required": True},
        {"id": "e5", "label": "Duration of symptoms >= 4 weeks", "required": True},
        {"id": "e6", "label": "No active infection or bleeding disorder", "required": False},
    ],
    "fusion": [
        {"id": "f1", "label": "MRI/CT confirming structural pathology", "required": True},
        {"id": "f2", "label": "Failed conservative treatment >= 3-6 months", "required": True},
        {"id": "f3", "label": "Failed interventional treatment (injections)", "required": True},
        {"id": "f4", "label": "Functional disability documented (ODI, VAS, ADL limitation)", "required": True},
        {"id": "f5", "label": "Neurological deficit or progressive symptoms", "required": False},
        {"id": "f6", "label": "Grade II+ spondylolisthesis or instability on dynamic X-rays", "required": False},
    ],
    "pt": [
        {"id": "p1", "label": "Documented functional progress from prior PT course", "required": True},
        {"id": "p2", "label": "Specific measurable therapy goals remaining", "required": True},
        {"id": "p3", "label": "Not yet at maximum medical improvement (MMI)", "required": True},
        {"id": "p4", "label": "Frequency and duration of additional sessions requested", "required": True},
        {"id": "p5", "label": "Prior auth number / expiry for current auth period", "required": False},
    ],
}

PROC_LABELS = {
    "mri": "Lumbar Magnetic Resonance Imaging (MRI)",
    "esi": "Lumbar Epidural Steroid Injection",
    "fusion": "Lumbar Spinal Fusion Surgery",
    "pt": "Physical Therapy (Extended Course)",
}

CPT_CODES = {
    "mri": "CPT 72148",
    "esi": "CPT 62323 / CPT 64483",
    "fusion": "CPT 22612",
    "pt": "CPT 97110",
}


def _is_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))


def _slugify(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (s or "")).strip("_").upper()


def _provider_map_from_env() -> dict:
    out = {}
    for k, v in os.environ.items():
        if k.startswith("PROVIDER_NPI_") and (v or "").strip():
            suffix = k.replace("PROVIDER_NPI_", "", 1)
            out[_slugify(suffix)] = v.strip()
    return out


def _resolve_npi(provider_name: str) -> str:
    # direct single-provider variable
    direct = (os.environ.get("PROVIDER_NPI") or "").strip()
    if direct:
        return direct

    provider_map = _provider_map_from_env()
    if not provider_map:
        return ""

    wanted = _slugify(provider_name)

    # exact match
    if wanted and wanted in provider_map:
        return provider_map[wanted]

    # last-name match
    parts = provider_name.strip().split()
    if parts:
        last = _slugify(parts[-1])
        if last in provider_map:
            return provider_map[last]

    # if exactly one exists, use it
    if len(provider_map) == 1:
        return next(iter(provider_map.values()))

    return ""


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

    provider_name = config.get("provider_name", "")
    config["npi"] = _resolve_npi(provider_name)
    config["provider_keys"] = sorted(_provider_map_from_env().keys())

    return config


def save_config(data: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename: str):
    target = PUBLIC_DIR / filename
    if target.exists() and target.is_file():
        return send_from_directory(PUBLIC_DIR, filename)
    return jsonify({"error": "Not found"}), 404


@app.route("/status")
def status():
    config = load_config()
    has_key = bool((config.get("api_key") or "").strip())
    return jsonify(
        {
            "ai_mode": has_key,
            "practice_name": config.get("practice_name", ""),
            "provider_name": config.get("provider_name", ""),
            "npi": config.get("npi", ""),
            "provider_keys": config.get("provider_keys", []),
            "storage": "env" if _is_vercel() else ("file" if CONFIG_FILE.exists() else "none"),
        }
    )


@app.route("/settings", methods=["POST"])
def settings():
    if _is_vercel():
        return (
            jsonify(
                {
                    "error": "Settings are disabled on Vercel. Set ANTHROPIC_API_KEY, PRACTICE_NAME, PROVIDER_NAME, and PROVIDER_NPI or PROVIDER_NPI_* in Vercel Environment Variables."
                }
            ),
            400,
        )

    data = request.json or {}
    api_key = (data.get("api_key") or "").strip()
    practice_name = (data.get("practice_name") or "").strip()
    provider_name = (data.get("provider_name") or "").strip()
    npi = (data.get("npi") or "").strip()

    save_config(
        {
            "api_key": api_key,
            "practice_name": practice_name,
            "provider_name": provider_name,
            "npi": npi,
        }
    )

    return jsonify({"ok": True})


@app.route("/analyze", methods=["POST"])
def analyze():
    config = load_config()
    api_key = (config.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "No API key configured. Set ANTHROPIC_API_KEY in Vercel env vars (or config.json locally)."}), 400

    data = request.json or {}
    notes = data.get("notes", "")
    proc_type = data.get("proc_type", "mri")
    payer = data.get("payer", "the insurance payer")
    patient = data.get("patient", {})

    criteria = CRITERIA.get(proc_type, [])
    criteria_list_text = "\n".join(
        f"  - ID: {c['id']} | {'REQUIRED' if c['required'] else 'OPTIONAL'} | {c['label']}" for c in criteria
    )

    prompt = f"""You are an expert prior authorization specialist at a spine clinic. Carefully read the clinical notes below and determine whether each payer criterion is documented.

PROCEDURE REQUESTED: {PROC_LABELS.get(proc_type, proc_type)} ({CPT_CODES.get(proc_type, '')})
PAYER: {payer}
PATIENT: {patient.get('fname', '')} {patient.get('lname', '')}

CLINICAL NOTES:
\"\"\"
{notes}
\"\"\"

CRITERIA TO EVALUATE:
{criteria_list_text}

For each criterion, carefully read the notes and decide:
- "met"     → clearly documented in the notes
- "missing" → required criterion but NOT clearly documented
- "unmet"   → optional criterion not documented

Return ONLY valid JSON:
{{
  "criteria": [
    {{"id": "c1", "status": "met", "note": "One sentence explaining your reasoning"}}
  ],
  "approval_likelihood": "high",
  "summary": "Two sentence summary."
}}"""

    model = config.get("anthropic_model") or "claude-3-5-sonnet-20240620"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (response.content[0].text or "").strip()

        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) >= 2:
                raw = parts[1]
            if raw.lstrip().startswith("json"):
                raw = raw.lstrip()[4:]

        result = json.loads(raw)

        status_map = {item.get("id"): item for item in (result.get("criteria") or [])}
        merged = []
        for c in criteria:
            ai = status_map.get(c["id"], {}) or {}
            merged.append(
                {
                    "id": c["id"],
                    "label": c["label"],
                    "required": c["required"],
                    "status": ai.get("status", "unmet"),
                    "note": ai.get("note", ""),
                }
            )

        return jsonify(
            {
                "criteria": merged,
                "approval_likelihood": result.get("approval_likelihood", "moderate"),
                "summary": result.get("summary", ""),
            }
        )

    except json.JSONDecodeError as e:
        return jsonify({"error": f"AI returned unexpected format: {str(e)}"}), 500
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key. Please check ANTHROPIC_API_KEY."}), 401
    except Exception as e:
        return jsonify({"error": f"AI analysis failed: {str(e)}"}), 500


@app.route("/generate-letter", methods=["POST"])
def generate_letter():
    config = load_config()
    api_key = (config.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "No API key configured. Set ANTHROPIC_API_KEY in Vercel env vars (or config.json locally)."}), 400

    data = request.json or {}
    notes = data.get("notes", "")
    proc_type = data.get("proc_type", "")
    payer = data.get("payer", "")
    icd = data.get("icd", "")
    pain = data.get("pain", "")
    duration = data.get("duration", "")
    fname = data.get("fname", "")
    lname = data.get("lname", "")
    met_criteria = data.get("met_criteria", [])

    provider = (data.get("provider") or config.get("provider_name") or "Treating Physician").strip()
    provider_npi = (data.get("provider_npi") or _resolve_npi(provider) or config.get("npi") or "[NPI]").strip()
    practice = config.get("practice_name", "Spine Clinic")
    today = date.today().strftime("%B %d, %Y")

    prompt = f"""You are an expert medical prior authorization letter writer specializing in spine care. Write a complete, professional, and persuasive prior authorization letter.

DATE: {today}
PATIENT: {fname} {lname}
PAYER: {payer}
PROCEDURE: {PROC_LABELS.get(proc_type, proc_type)} ({CPT_CODES.get(proc_type, '')})
DIAGNOSIS (ICD-10): {icd}
VAS PAIN SCORE: {pain}/10
SYMPTOM DURATION: {duration}
REQUESTING PROVIDER: {provider}
PRACTICE: {practice}
NPI: {provider_npi}

CLINICAL NOTES:
\"\"\"
{notes}
\"\"\"

CRITERIA MET:
{chr(10).join('- ' + str(c) for c in met_criteria)}

Write the full letter only."""

    model = config.get("anthropic_model") or "claude-3-5-sonnet-20240620"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        return jsonify({"letter": response.content[0].text})
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key. Please check ANTHROPIC_API_KEY."}), 401
    except Exception as e:
        return jsonify({"error": f"Letter generation failed: {str(e)}"}), 500