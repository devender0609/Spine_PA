"""SpinePA Agent — Flask app for Vercel.

- Serves the UI from ./public/index.html
- Provides backend routes: /status, /settings (local only), /analyze, /generate-letter

Security note:
- On Vercel (serverless), /settings is disabled. Configure via env vars instead.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import anthropic
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS


ROOT_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT_DIR / "public"
CONFIG_FILE = ROOT_DIR / "config.json"  # local-only (gitignored)

app = Flask(__name__)
CORS(app)


# ─────────────────────────────────────────────────────────────
# Payer criteria (used by the AI as a reference)
# ─────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load config from local config.json (if present), overridden by env vars."""
    config: dict = {}

    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            # If config is malformed, ignore (avoid crashing the server)
            config = {}

    # Environment variables override file (cloud deployment mode)
    if os.environ.get("ANTHROPIC_API_KEY"):
        config["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("PRACTICE_NAME"):
        config["practice_name"] = os.environ["PRACTICE_NAME"]
    if os.environ.get("PROVIDER_NAME"):
        config["provider_name"] = os.environ["PROVIDER_NAME"]
    if os.environ.get("PROVIDER_NPI"):
        config["npi"] = os.environ["PROVIDER_NPI"]
    if os.environ.get("ANTHROPIC_MODEL"):
        config["anthropic_model"] = os.environ["ANTHROPIC_MODEL"]

    return config


def save_config(data: dict) -> None:
    """Local-only config persistence."""
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_vercel() -> bool:
    # Vercel sets VERCEL=1 in production and preview deployments
    return bool(os.environ.get("VERCEL"))


# ─────────────────────────────────────────────────────────────
# Static UI
# ─────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename: str):
    # Allow other static files if you add them later
    target = PUBLIC_DIR / filename
    if target.exists() and target.is_file():
        return send_from_directory(PUBLIC_DIR, filename)
    return jsonify({"error": "Not found"}), 404


# ─────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────

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
            "storage": "env" if _is_vercel() else ("file" if CONFIG_FILE.exists() else "none"),
        }
    )


@app.route("/settings", methods=["POST"])
def settings():
    if _is_vercel():
        return (
            jsonify(
                {
                    "error": "Settings are disabled on Vercel. Set ANTHROPIC_API_KEY, PRACTICE_NAME, PROVIDER_NAME, and PROVIDER_NPI in Vercel Environment Variables."
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
- "missing" → required criterion but NOT clearly documented (needs to be added by the provider)
- "unmet"   → optional criterion not documented (acceptable)

Return ONLY a valid JSON object in this exact format (no other text, no markdown):
{{
  "criteria": [
    {{"id": "c1", "status": "met", "note": "One sentence explaining your reasoning"}},
    ...
  ],
  "approval_likelihood": "high" | "moderate" | "low",
  "summary": "Two sentence summary of the case strength and any key gaps."
}}"""

    model = config.get("anthropic_model") or "claude-sonnet-4-5-20250929"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (response.content[0].text or "").strip()

        # Strip markdown code blocks if present
        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) >= 2:
                raw = parts[1]
            if raw.lstrip().startswith("json"):
                raw = raw.lstrip()[4:]

        result = json.loads(raw)

        # Merge AI statuses back into full criteria objects
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

    provider = data.get("provider", config.get("provider_name", "Treating Physician"))
    practice = config.get("practice_name", "Spine Clinic")
    npi = config.get("npi", "[NPI]")

    fname = data.get("fname", "")
    lname = data.get("lname", "")
    met_criteria = data.get("met_criteria", [])

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
NPI: {npi}

CLINICAL NOTES:
\"\"\"
{notes}
\"\"\"

CRITERIA MET (include these explicitly):
{chr(10).join('- ' + str(c) for c in met_criteria)}

Write a compelling, medically accurate prior authorization letter that:
1. Uses today's date and standard business letter format
2. Opens with "Dear Prior Authorization Reviewer,"
3. Clearly states what is being requested in the first paragraph
4. Provides a concise but complete clinical summary drawn from the notes
5. Explicitly addresses each met criterion with specific evidence from the notes
6. Uses professional medical terminology appropriate for a spine specialist
7. Is persuasive but factually accurate — do not invent clinical details
8. Ends with a professional closing, offers peer-to-peer review, and lists attachments

Write the full letter now. Do not include any preamble or explanation — just the letter itself."""

    model = config.get("anthropic_model") or "claude-sonnet-4-5-20250929"

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
