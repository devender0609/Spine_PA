import os
import json
from pathlib import Path
from datetime import date

from flask import Flask, jsonify, request, send_from_directory

import anthropic

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"
CONFIG_FILE = BASE_DIR / "config.json"

# -------------------------------------------------------------------
# Labels / codes (keep yours as-is if you already have them elsewhere)
# -------------------------------------------------------------------
PROC_LABELS = {
    "mri": "Lumbar MRI",
    "esi": "Epidural Steroid Injection",
    "fusion": "Lumbar Spinal Fusion",
    "pt": "Physical Therapy Extension",
}
CPT_CODES = {
    "mri": "72148",
    "esi": "62323/64483",
    "fusion": "22612",
    "pt": "97110",
}

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _is_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))

def _load_config_file() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_config_file(data: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def _providers_from_env() -> list[dict]:
    """
    Priority:
    1) PROVIDERS_JSON = '[{"id":"truumees","label":"Dr. Truumees","npi":"..."}]'
    2) Scan PROVIDER_NPI_* env vars
    """
    # 1) explicit JSON
    providers_json = os.environ.get("PROVIDERS_JSON", "").strip()
    if providers_json:
        try:
            arr = json.loads(providers_json)
            cleaned = []
            for i, p in enumerate(arr):
                if not isinstance(p, dict):
                    continue
                pid = (p.get("id") or f"provider_{i}").strip()
                label = (p.get("label") or p.get("name") or pid).strip()
                npi = (p.get("npi") or "").strip()
                if label and npi:
                    cleaned.append({"id": pid, "label": label, "npi": npi})
            if cleaned:
                return cleaned
        except Exception:
            pass

    # 2) scan PROVIDER_NPI_*
    scanned = []
    for k, v in os.environ.items():
        if not k.startswith("PROVIDER_NPI_"):
            continue
        suffix = k.replace("PROVIDER_NPI_", "", 1).strip()
        npi = (v or "").strip()
        if not suffix or not npi:
            continue

        # Optional: if you also define PROVIDER_NAME_<suffix>, we use it
        name_key = f"PROVIDER_NAME_{suffix}"
        label = (os.environ.get(name_key) or suffix).strip()

        pid = suffix.lower().replace(" ", "_")
        scanned.append({"id": pid, "label": label, "npi": npi})

    # stable ordering for UI
    scanned.sort(key=lambda x: x["label"].lower())
    return scanned

def load_config() -> dict:
    """
    Returns one config object for both local + Vercel.
    On Vercel: env vars override.
    """
    config = _load_config_file()

    # Core single fields (still supported)
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

    # Multi-provider support
    providers = _providers_from_env()
    if providers:
        config["providers"] = providers
        # Default provider if not specified
        if not config.get("default_provider_id"):
            config["default_provider_id"] = providers[0]["id"]

    return config

def _resolve_provider(config: dict, requested_provider: str | None, requested_npi: str | None) -> tuple[str, str]:
    """
    Returns (provider_label, provider_npi)
    Priority:
    - If request explicitly includes provider_npi, use it
    - Else if request includes provider label and we can match it in providers list, use that NPI
    - Else fallback to config single provider_name/npi
    - Else fallback to default provider in providers list
    """
    providers = config.get("providers") or []

    # If caller sent NPI explicitly, trust it
    if (requested_npi or "").strip():
        return (requested_provider or config.get("provider_name") or "Treating Physician", requested_npi.strip())

    # Try matching by label
    rp = (requested_provider or "").strip()
    if rp and providers:
        for p in providers:
            if p["label"].strip().lower() == rp.lower():
                return (p["label"], p["npi"])

    # Try default provider id
    default_id = (config.get("default_provider_id") or "").strip()
    if default_id and providers:
        for p in providers:
            if p["id"] == default_id:
                return (p["label"], p["npi"])

    # Fallback to single fields
    return (
        config.get("provider_name", "Treating Physician"),
        config.get("npi", "[NPI]"),
    )

# -------------------------------------------------------------------
# Static UI
# -------------------------------------------------------------------
@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")

@app.route("/<path:filename>")
def static_files(filename: str):
    target = PUBLIC_DIR / filename
    if target.exists() and target.is_file():
        return send_from_directory(PUBLIC_DIR, filename)
    return jsonify({"error": "Not found"}), 404

# -------------------------------------------------------------------
# API
# -------------------------------------------------------------------
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
            "providers": config.get("providers", []),
            "default_provider_id": config.get("default_provider_id", ""),
            "storage": "env" if _is_vercel() else ("file" if CONFIG_FILE.exists() else "none"),
        }
    )

@app.route("/settings", methods=["POST"])
def settings():
    # Keep disabled on Vercel (you set env vars there)
    if _is_vercel():
        return (
            jsonify(
                {
                    "error": "Settings are disabled on Vercel. Set env vars in Vercel: ANTHROPIC_API_KEY, PRACTICE_NAME, and either PROVIDERS_JSON or PROVIDER_NPI_*."
                }
            ),
            400,
        )

    data = request.json or {}
    config = load_config()

    # Only update what is provided
    if (data.get("api_key") or "").strip():
        config["api_key"] = data["api_key"].strip()
    if "practice_name" in data:
        config["practice_name"] = (data.get("practice_name") or "").strip()

    # Optional: allow local multi providers too
    if "providers" in data and isinstance(data["providers"], list):
        config["providers"] = data["providers"]
    if "default_provider_id" in data:
        config["default_provider_id"] = (data.get("default_provider_id") or "").strip()

    # Keep single fields for backward compatibility
    if "provider_name" in data:
        config["provider_name"] = (data.get("provider_name") or "").strip()
    if "npi" in data:
        config["npi"] = (data.get("npi") or "").strip()

    _save_config_file(config)
    return jsonify({"ok": True})

@app.route("/generate-letter", methods=["POST"])
def generate_letter():
    config = load_config()
    api_key = (config.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "No API key configured. Set ANTHROPIC_API_KEY in Vercel env vars."}), 400

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

    requested_provider = data.get("provider")
    requested_npi = data.get("provider_npi")
    provider_label, provider_npi = _resolve_provider(config, requested_provider, requested_npi)

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
REQUESTING PROVIDER: {provider_label}
PRACTICE: {practice}
NPI: {provider_npi}

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
        return jsonify({"error": "Invalid API key. Check ANTHROPIC_API_KEY."}), 401
    except Exception as e:
        return jsonify({"error": f"Letter generation failed: {str(e)}"}), 500