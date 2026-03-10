from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB = "cases.db"


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    c = db()
    c.execute("""
    CREATE TABLE IF NOT EXISTS cases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient TEXT,
        dob TEXT,
        payer TEXT,
        memberId TEXT,
        diagnosis TEXT,
        procedure TEXT,
        provider TEXT,
        providerNpi TEXT,
        notes TEXT,
        letter TEXT,
        status TEXT,
        createdAt TEXT
    )
    """)
    c.commit()
    c.close()


@app.route("/status")
def status():
    return jsonify({"running": True})


@app.route("/generate-letter", methods=["POST"])
def generate():
    d = request.json

    patient = d.get("patient", "")
    dob = d.get("dob", "")
    payer = d.get("payer", "")
    member = d.get("memberId", "")
    diagnosis = d.get("diagnosis", "")
    procedure = d.get("procType", "")
    provider = d.get("provider", "")
    npi = d.get("providerNpi", "")
    notes = d.get("notes", "")

    today = datetime.now().strftime("%B %d, %Y")

    letter = f"""
PRIOR AUTHORIZATION REQUEST LETTER

DATE: {today}

TO: {payer}

PATIENT: {patient}
DOB: {dob}
MEMBER ID: {member}

PROCEDURE: {procedure}
DIAGNOSIS: {diagnosis}

ORDERING PROVIDER: {provider}
NPI: {npi}

CLINICAL SUMMARY:
{notes if notes else "Patient presents with symptoms requiring further evaluation."}

MEDICAL NECESSITY:
The requested procedure is medically necessary to evaluate and manage the patient's condition.

Sincerely,
{provider}
"""

    return jsonify({"letter": letter})


@app.route("/cases", methods=["GET"])
def get_cases():
    c = db()
    rows = c.execute("SELECT * FROM cases ORDER BY id DESC").fetchall()
    c.close()
    return jsonify({"cases": [dict(r) for r in rows]})


@app.route("/cases", methods=["POST"])
def create_case():
    d = request.json

    conn = db()

    conn.execute("""
        INSERT INTO cases(
            patient,dob,payer,memberId,diagnosis,procedure,
            provider,providerNpi,notes,letter,status,createdAt
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        d.get("patient"),
        d.get("dob"),
        d.get("payer"),
        d.get("memberId"),
        d.get("diagnosis"),
        d.get("procType"),
        d.get("provider"),
        d.get("providerNpi"),
        d.get("notes"),
        d.get("letter"),
        "saved",
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()

    return jsonify({"success": True})


@app.route("/cases/<int:id>", methods=["PUT"])
def update_case(id):
    d = request.json

    conn = db()

    conn.execute("""
    UPDATE cases
    SET patient=?,dob=?,payer=?,memberId=?,diagnosis=?,procedure=?,
        provider=?,providerNpi=?,notes=?,letter=?
    WHERE id=?
    """, (
        d.get("patient"),
        d.get("dob"),
        d.get("payer"),
        d.get("memberId"),
        d.get("diagnosis"),
        d.get("procType"),
        d.get("provider"),
        d.get("providerNpi"),
        d.get("notes"),
        d.get("letter"),
        id
    ))

    conn.commit()
    conn.close()

    return jsonify({"success": True})


@app.route("/cases/<int:id>", methods=["DELETE"])
def delete_case(id):

    conn = db()
    conn.execute("DELETE FROM cases WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return jsonify({"deleted": True})


if __name__ == "__main__":
    init_db()
    app.run(port=5000)