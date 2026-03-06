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


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


def load_providers():

    providers = []

    for key, value in os.environ.items():

        if key.startswith("PROVIDER_NPI_") and value:

            suffix = key.replace("PROVIDER_NPI_", "")

            name = suffix.replace("_", " ").title()

            providers.append({
                "key": slug(suffix),
                "name": name,
                "npi": value
            })

    providers.sort(key=lambda x: x["name"])

    return providers


def resolve_npi(provider_name, providers):

    key = slug(provider_name)

    for p in providers:
        if p["key"] == key:
            return p["npi"]

    return ""


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

    providers = load_providers()

    config["providers"] = providers

    return config


@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):

    target = PUBLIC_DIR / path

    if target.exists():
        return send_from_directory(PUBLIC_DIR, path)

    return jsonify({"error": "Not found"}), 404


@app.route("/status")
def status():

    config = load_config()

    return jsonify({
        "running": True,
        "practice_name": config.get("practice_name", ""),
        "provider_name": config.get("provider_name", ""),
        "providers": config.get("providers", [])
    })


@app.route("/analyze", methods=["POST"])
def analyze():

    config = load_config()

    api_key = config.get("api_key")

    if not api_key:
        return jsonify({"error": "Missing ANTHROPIC_API_KEY"}), 400

    data = request.json or {}

    notes = data.get("notes", "")

    prompt = f"""
You are a medical prior authorization specialist.

Analyze these clinical notes and determine if the request meets payer criteria.

Clinical Notes:
{notes}

Return JSON only.
"""

    try:

        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text

        return jsonify({"analysis": result})

    except Exception as e:

        return jsonify({"error": str(e)}), 500


@app.route("/generate-letter", methods=["POST"])
def generate_letter():

    config = load_config()

    api_key = config.get("api_key")

    if not api_key:
        return jsonify({"error": "Missing ANTHROPIC_API_KEY"}), 400

    providers = config.get("providers", [])

    data = request.json or {}

    notes = data.get("notes", "")
    payer = data.get("payer", "")
    patient = data.get("patient", "")
    provider = data.get("provider", "")

    provider_npi = data.get("provider_npi") or resolve_npi(provider, providers)

    today = date.today().strftime("%B %d, %Y")

    prompt = f"""
Write a professional prior authorization request letter.

DATE: {today}
PATIENT: {patient}
PAYER: {payer}
PROVIDER: {provider}
NPI: {provider_npi}

Clinical Notes:
{notes}
"""

    try:

        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        return jsonify({
            "letter": response.content[0].text
        })

    except Exception as e:

        return jsonify({"error": str(e)}), 500