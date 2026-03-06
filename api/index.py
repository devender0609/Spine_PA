"""SpinePA Agent — Flask backend for Vercel serverless deployment."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import anthropic
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"

# IMPORTANT: static_folder points to public directory
app = Flask(
    __name__,
    static_folder=str(PUBLIC_DIR),
    static_url_path=""
)

CORS(app)

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
CONFIG_FILE = ROOT_DIR / "config.json"


def load_config():
    config = {}

    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
        except Exception:
            config = {}

    if os.environ.get("ANTHROPIC_API_KEY"):
        config["api_key"] = os.environ["ANTHROPIC_API_KEY"]

    if os.environ.get("PRACTICE_NAME"):
        config["practice_name"] = os.environ["PRACTICE_NAME"]

    if os.environ.get("PROVIDER_NAME"):
        config["provider_name"] = os.environ["PROVIDER_NAME"]

    if os.environ.get("PROVIDER_NPI"):
        config["npi"] = os.environ["PROVIDER_NPI"]

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
# Health check
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

CLINICAL NOTES:
{notes}

Return JSON only.
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
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

    provider = config.get("provider_name", "Treating Physician")
    practice = config.get("practice_name", "Spine Clinic")
    npi = config.get("npi", "")

    today = date.today().strftime("%B %d, %Y")

    prompt = f"""
Write a professional prior authorization letter.

DATE: {today}
PATIENT: {patient}
PAYER: {payer}
PROVIDER: {provider}
PRACTICE: {practice}
NPI: {npi}

CLINICAL NOTES:
{notes}

Write a persuasive prior authorization request letter.
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        return jsonify({"letter": response.content[0].text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
