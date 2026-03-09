from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import date

app = Flask(__name__)
CORS(app)


def evaluate_criteria(data):
    met = 0
    total = 4
    details = []

    if data.get("duration"):
        met += 1
        details.append({"description": "Symptoms duration documented", "met": True})
    else:
        details.append({"description": "Symptoms duration missing", "met": False})

    if data.get("pain_score"):
        met += 1
        details.append({"description": "Pain severity documented", "met": True})
    else:
        details.append({"description": "Pain severity missing", "met": False})

    if data.get("diagnosis"):
        met += 1
        details.append({"description": "Diagnosis documented", "met": True})
    else:
        details.append({"description": "Diagnosis missing", "met": False})

    if data.get("proc_type"):
        met += 1
        details.append({"description": "Procedure specified", "met": True})
    else:
        details.append({"description": "Procedure missing", "met": False})

    return met, total, details


@app.route("/analyze", methods=["POST"])
def analyze():

    data = request.json

    met, total, details = evaluate_criteria(data)

    probability = "Moderate"
    if met >= 3:
        probability = "High"
    elif met <= 1:
        probability = "Low"

    portal_helper = {
        "status": "Ready" if met >= 3 else "Needs Documentation",
        "missing": [d["description"] for d in details if not d["met"]],
        "attachments": [
            "Clinical notes",
            "Prior imaging report",
            "Physical therapy documentation"
        ]
    }

    return jsonify({
        "mode": "AI",
        "criteria_met": met,
        "criteria_total": total,
        "criteria_details": details,
        "approval_probability": probability,
        "portal_helper": portal_helper
    })


@app.route("/generate-letter", methods=["POST"])
def generate_letter():

    data = request.json

    today = date.today().strftime("%B %d, %Y")

    letter = f"""
# PRIOR AUTHORIZATION REQUEST LETTER

DATE: {today}

TO: {data.get("insurance")}

FROM: {data.get("provider")} | NPI: {data.get("provider_npi")}
Ascension Texas Spine and Scoliosis

RE: Prior Authorization Request – {data.get("proc_type")}

PATIENT INFORMATION

Patient Name: {data.get("patient_name")}
DOB: {data.get("dob")}
Member ID: {data.get("member_id")}

CLINICAL SUMMARY

Patient presents with pain score {data.get("pain_score")} with symptom duration of {data.get("duration")}.

Diagnosis: {data.get("diagnosis")}

MEDICAL NECESSITY

Patient has persistent symptoms despite conservative management.

Requested Procedure: {data.get("proc_type")}

Ordering Provider: {data.get("provider")}
NPI: {data.get("provider_npi")}

Respectfully,

{data.get("provider")}
"""

    return jsonify({
        "letter": letter
    })


@app.route("/build-package", methods=["POST"])
def build_package():

    data = request.json

    package = {
        "clinical_summary": {
            "patient": data.get("patient_name"),
            "dob": data.get("dob"),
            "diagnosis": data.get("diagnosis"),
            "procedure": data.get("proc_type"),
            "pain_score": data.get("pain_score"),
            "duration": data.get("duration")
        },
        "submission_checklist": [
            "Prior auth letter",
            "Clinical documentation",
            "Imaging report",
            "Insurance member ID"
        ],
        "case_payload": data
    }

    return jsonify(package)


if __name__ == "__main__":
    app.run()