"""SpinePA Agent — Flask backend for Vercel serverless deployment."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import anthropic
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# api/index.py lives inside  <root>/api/
# public/index.html lives at <root>/public/
ROOT_DIR   = Path(__file__).resolve().parent.parent   # <root>
PUBLIC_DIR = ROOT_DIR / "public"

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Payer criteria
# ---------------------------------------------------------------------------
CRITERIA = {
    "mri": [
        {"id": "c1", "label": "6+ weeks of conservative treatment documented",        "required": True},
        {"id": "c2", "label": "Failure to improve with conservative management",       "required": True},
        {"id": "c3", "label": "Specific radicular or neurological symptoms",           "required": True},
        {"id": "c4", "label": "Red flag symptoms documented (or absence confirmed)",   "required": False},
        {"id": "c5", "label": "VAS / pain score documented",                           "required": True},
        {"id": "c6", "label": "Physical exam findings documented",                     "required": True},
    ],
    "esi": [
        {"id": "e1", "label": "MRI or CT evidence of disc herniation or stenosis",     "required": True},
        {"id": "e2", "label": "Radicular symptoms with dermatomal distribution",       "required": True},
        {"id": "e3", "label": "Failed conservative treatment (PT + medications)",      "required": True},
        {"id": "e4", "label": "VAS pain score >= 6 documented",                        "required": True},
        {"id": "e5", "label": "Duration of symptoms >= 4 weeks",                       "required": True},
        {"id": "e6", "label": "No active infection or bleeding disorder",              "required": False},
    ],
    "fusion": [
        {"id": "f1", "label": "MRI/CT confirming structural pathology",                "required": True},
        {"id": "f2", "label": "Failed conservative treatment >= 3-6 months",          "required": True},
        {"id": "f3", "label": "Failed interventional treatment (injections)",          "required": True},
        {"id": "f4", "label": "Functional disability documented (ODI, VAS, ADL)",     "required": True},
        {"id": "f5", "label": "Neurological deficit or progressive symptoms",          "required": False},
        {"id": "f6", "label": "Grade II+ spondylolisthesis or instability on X-rays", "required": False},
    ],
    "pt": [
        {"id": "p1", "label": "Documented functional progress from prior PT course",  "required": True},
        {"id": "p2", "label": "Specific measurable therapy goals remaining",           "required": True},
        {"id": "p3", "label": "Not yet at maximum medical improvement (MMI)",          "required": True},
        {"id": "p4", "label": "Frequency and duration of additional sessions requested","required": True},
        {"id": "p5", "label": "Prior auth number / expiry for current auth period",   "required": False},
    ],
}

PROC_LABELS = {
    "mri":    "Lumbar Magnetic Resonance Imaging (MRI)",
    "esi":    "Lumbar Epidural Steroid Injection",
    "fusion": "Lumbar Spinal Fusion Surgery",
    "pt":     "Physical Therapy (Extended Course)",
}

CPT_CODES = {
    "mri":    "CPT 72148",
    "esi":    "CPT 62323 / CPT 64483",
    "fusion": "CPT 22612",
    "pt":     "CPT 97110",
}

# ---------------------------------------------------------------------------
# Config — reads from environment variables (Vercel) or local config.json
# ---------------------------------------------------------------------------
CONFIG_FILE = ROOT_DIR / "config.json"   # only used in local dev


def load_config() -> dict:
    """Merge local config.json (if present) with environment variables.
    Environment variables always win so Vercel env vars take precedence."""
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
    if os.environ.get("PROVIDER_NPI"):
        config["npi"] = os.environ["PROVIDER_NPI"].strip()
    if os.environ.get("ANTHROPIC_MODEL"):
        config["anthropic_model"] = os.environ["ANTHROPIC_MODEL"].strip()

    return config


def _is_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))


# ---------------------------------------------------------------------------
# Static routes — serve the UI
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return send_from_directory(str(PUBLIC_DIR), "index.html")


@app.route("/<path:filename>")
def static_files(filename: str):
    target = PUBLIC_DIR / filename
    if target.is_file():
        return send_from_directory(str(PUBLIC_DIR), filename)
    return jsonify({"error": "Not found"}), 404


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/status")
def status():
    config = load_config()
    has_key = bool((config.get("api_key") or "").strip())
    return jsonify({
        "running":       True,
        "has_api_key":   has_key,          # used by the frontend JS
        "ai_mode":       has_key,          # alias
        "practice_name": config.get("practice_name", "Spine Clinic"),
        "provider_name": config.get("provider_name", ""),
        "npi":           config.get("npi", ""),
        "mode":          "AI" if has_key else "demo",
    })


@app.route("/settings", methods=["POST"])
def settings():
    """Disabled on Vercel — configure via env vars instead."""
    if _is_vercel():
        return jsonify({
            "error": (
                "Settings endpoint is disabled on Vercel. "
                "Set ANTHROPIC_API_KEY, PRACTICE_NAME, PROVIDER_NAME, and PROVIDER_NPI "
                "in Vercel → Project → Settings → Environment Variables."
            )
        }), 400

    data = request.json or {}
    config = load_config()
    for field in ("api_key", "practice_name", "provider_name", "npi"):
        val = (data.get(field) or "").strip()
        if val:
            config[field] = val
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return jsonify({"success": True, "message": "Settings saved successfully."})


@app.route("/analyze", methods=["POST"])
def analyze():
    config = load_config()
    api_key = (config.get("api_key") or "").strip()
    if not api_key:
        return jsonify({
            "error": "No API key configured. Add ANTHROPIC_API_KEY in Vercel Environment Variables."
        }), 400

    data      = request.json or {}
    notes     = data.get("notes", "")
    proc_type = data.get("proc_type", "mri")
    payer     = data.get("payer", "the insurance payer")
    patient   = data.get("patient", {})

    criteria = CRITERIA.get(proc_type, [])
    criteria_text = "\n".join(
        f"  - ID: {c['id']} | {'REQUIRED' if c['required'] else 'OPTIONAL'} | {c['label']}"
        for c in criteria
    )

    prompt = f"""You are an expert prior authorization specialist at a spine clinic.
Carefully read the clinical notes and determine whether each payer criterion is documented.

PROCEDURE: {PROC_LABELS.get(proc_type, proc_type)} ({CPT_CODES.get(proc_type, '')})
PAYER: {payer}
PATIENT: {patient.get('fname', '')} {patient.get('lname', '')}

CLINICAL NOTES:
\"\"\"
{notes}
\"\"\"

CRITERIA TO EVALUATE:
{criteria_text}

For each criterion decide:
- "met"     → clearly documented in the notes
- "missing" → required but NOT clearly documented (provider must add this)
- "unmet"   → optional criterion, not documented (acceptable)

Return ONLY valid JSON — no markdown, no extra text:
{{
  "criteria": [
    {{"id": "c1", "status": "met", "note": "One sentence explaining reasoning"}}
  ],
  "approval_likelihood": "high",
  "summary": "Two sentence summary of case strength and key gaps."
}}"""

    model = config.get("anthropic_model") or "claude-3-5-sonnet-20240620"

    try:
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model, max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (response.content[0].text or "").strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw   = parts[1] if len(parts) >= 2 else raw
            if raw.lstrip().startswith("json"):
                raw = raw.lstrip()[4:]

        result     = json.loads(raw)
        status_map = {item.get("id"): item for item in (result.get("criteria") or [])}
        merged     = []
        for c in criteria:
            ai = status_map.get(c["id"]) or {}
            merged.append({
                "id":       c["id"],
                "label":    c["label"],
                "required": c["required"],
                "status":   ai.get("status", "unmet"),
                "note":     ai.get("note", ""),
            })

        return jsonify({
            "criteria":            merged,
            "approval_likelihood": result.get("approval_likelihood", "moderate"),
            "summary":             result.get("summary", ""),
        })

    except json.JSONDecodeError as e:
        return jsonify({"error": f"AI returned unexpected format: {e}"}), 500
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key. Check ANTHROPIC_API_KEY."}), 401
    except Exception as e:
        return jsonify({"error": f"AI analysis failed: {e}"}), 500


@app.route("/generate-letter", methods=["POST"])
def generate_letter():
    config  = load_config()
    api_key = (config.get("api_key") or "").strip()
    if not api_key:
        return jsonify({
            "error": "No API key configured. Add ANTHROPIC_API_KEY in Vercel Environment Variables."
        }), 400

    data         = request.json or {}
    notes        = data.get("notes", "")
    proc_type    = data.get("proc_type", "")
    payer        = data.get("payer", "")
    icd          = data.get("icd", "")
    pain         = data.get("pain", "")
    duration     = data.get("duration", "")
    fname        = data.get("fname", "")
    lname        = data.get("lname", "")
    met_criteria = data.get("met_criteria", [])
    provider     = (data.get("provider") or config.get("provider_name") or "Treating Physician").strip()
    practice     = config.get("practice_name", "Spine Clinic")
    npi          = config.get("npi", "[NPI]")
    today        = date.today().strftime("%B %d, %Y")

    prompt = f"""You are an expert medical prior authorization letter writer specializing in spine care.
Write a complete, professional, and persuasive prior authorization letter.

DATE: {today}
PATIENT: {fname} {lname}
PAYER: {payer}
PROCEDURE: {PROC_LABELS.get(proc_type, proc_type)} ({CPT_CODES.get(proc_type, '')})
DIAGNOSIS (ICD-10): {icd}
VAS PAIN SCORE: {pain}/10
SYMPTOM DURATION: {duration}
REQUESTING PROVIDER: {provider}
PRACTICE: {practice}
NPI: {npi}

CLINICAL NOTES:
\"\"\"
{notes}
\"\"\"

CRITERIA MET (cite each explicitly with evidence from notes):
{chr(10).join('- ' + str(c) for c in met_criteria)}

Instructions:
1. Standard business letter format with today's date
2. Open with "Dear Prior Authorization Reviewer,"
3. First paragraph: clearly state what is being requested
4. Clinical summary drawn strictly from the notes (do not invent details)
5. Address each met criterion with specific evidence
6. Professional medical terminology for a spine specialist
7. Close with peer-to-peer review offer and list of attachments

Write the full letter only — no preamble or explanation."""

    model = config.get("anthropic_model") or "claude-3-5-sonnet-20240620"

    try:
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model, max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        return jsonify({"letter": response.content[0].text})
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key. Check ANTHROPIC_API_KEY."}), 401
    except Exception as e:
        return jsonify({"error": f"Letter generation failed: {e}"}), 500
