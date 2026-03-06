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

ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"

app = Flask(
    __name__,
    static_folder=str(PUBLIC_DIR),
    static_url_path=""
)
CORS(app)

CONFIG_FILE = ROOT_DIR / "config.json"


def _slugify(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (value or "").strip()).strip("_").upper()


def _title_from_env_suffix(suffix: str) -> str:
    parts = re.split(r"[_\-\s]+", suffix.strip())
    return " ".join(p for p in parts if p)


def _load_provider_map_from_env() -> list[dict]:
    providers = []
    for key, value in os.environ.items():
        if key.startswith("PROVIDER_NPI_") and str(value).strip():
            suffix = key.replace("PROVIDER_NPI_", "", 1)
            display_name = _title_from_env_suffix(suffix)
            providers.append(
                {
                    "key": _slugify(suffix),
                    "name": display_name,
                    "npi": str(value).strip(),
                }
            )
    providers.sort(key=lambda x: x["name"].lower())
    return providers


def _resolve_provider_npi(provider_name: str, providers: list[dict]) -> str:
    if os.environ.get("PROVIDER_NPI"):
        return os.environ["PROVIDER_NPI"].strip()

    wanted = _slugify(provider_name)
    if not wanted:
        return ""

    for provider in providers:
        if provider["key"] == wanted:
            return provider["npi"]

    parts = provider_name.strip().split()
    if parts:
        last = _slugify(parts[-1])
        for provider in providers:
            if provider["key"] == last:
                return provider["npi"]

    return ""


def load_config():
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

    providers = _load_provider_map_from_env()
    config["providers"] = providers

    # single fallback provider NPI if explicitly present
    if os.environ.get("PROVIDER_NPI"):
        config["npi"] = os.environ["PROVIDER_NPI"].strip()
    else:
        default_provider = config.get("provider_name", "")
        config["npi"] = _resolve_provider_npi(default_provider, providers)

    return config


# ------------------------------------------------------------
# Static UI routes
# ------------------------------------------------------------

@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    target = PUBLIC_DIR / path
    if target.exists():
        return send_from_directory(PUBLIC_DIR, path)
    return jsonify({"error": "Not found"}), 404


# ------------------------------------------------------------
# Health / config
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
# Analyze notes
# ------------------------------------------------------------

@app.route("/analyze", methods=["POST"])
def analyze():
    config = load_config()
    api_key = config.get("api_key")
    if not api_key:
        return jsonify({"error": "Missing ANTHROPIC_API_KEY"}), 400

    data = request.json or {}

    notes = data.get("notes", "")
    proc_type = data.get("proc_type", "mri")

    prompt = f"""
You are a medical prior authorization specialist.

Analyze the following clinical notes and determine whether the request
meets payer criteria.

Procedure type: {proc_type}

CLINICAL NOTES:
{notes}

Return JSON only.
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        response = client.messages.create(
            model=model_name,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )

        result = response.content[0].text
        return jsonify({"analysis": result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------
# Generate authorization letter
# ------------------------------------------------------------

@app.route("/generate-letter", methods=["POST"])
def generate_letter():
    config = load_config()
    api_key = config.get("api_key")
    if not api_key:
        return jsonify({"error": "Missing ANTHROPIC_API_KEY"}), 400

    data = request.json or {}

    notes = data.get("notes", "")
    payer = data.get("payer", "")
    patient = data.get("patient", "")
    provider = (data.get("provider") or config.get("provider_name") or "Treating Physician").strip()

    providers = config.get("providers", [])
    provider_npi = (data.get("provider_npi") or _resolve_provider_npi(provider, providers) or config.get("npi", "")).strip()

    practice = config.get("practice_name", "Spine Clinic")
    today = date.today().strftime("%B %d, %Y")

    prompt = f"""
Write a professional prior authorization letter.

DATE: {today}
PATIENT: {patient}
PAYER: {payer}
PROVIDER: {provider}
PRACTICE: {practice}
NPI: {provider_npi}

CLINICAL NOTES:
{notes}

Write a persuasive prior authorization request letter.
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        response = client.messages.create(
            model=model_name,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        return jsonify(
            {
                "letter": response.content[0].text,
                "provider": provider,
                "provider_npi": provider_npi,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500