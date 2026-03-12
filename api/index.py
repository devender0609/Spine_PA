from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

API_DIR = Path(__file__).resolve().parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

try:
    import anthropic
except Exception:  # pragma: no cover
    anthropic = None

from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

from criteria_engine import evaluate_case, has_specific_icd, normalize_diagnosis_and_icd
from procedures import PROCEDURES, canonical_procedure_key, get_procedure
from submission_portals import PAYER_PORTALS as BASE_PAYER_PORTALS, get_payer_portal as base_get_payer_portal

ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"
DB_FILE = Path(os.environ.get("SPINEPA_DB_FILE", "/tmp/spinepa_cases.db"))
CONFIG_FILE = ROOT_DIR / "config.json"

os.makedirs("/tmp", exist_ok=True)

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
CORS(app)


EXTRA_PAYER_PORTALS = {
    "anthem": {
        "display_name": "Anthem / Elevance",
        "portal_name": "Availity / Anthem Provider",
        "portal_url": "https://www.anthem.com/provider",
        "fax": "Varies by plan and state",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Neurologic exam",
            "Conservative treatment records",
        ],
        "how_to_submit": [
            "Verify member plan and prior authorization policy.",
            "Submit through Anthem provider workflow or linked clearinghouse.",
            "Upload clinical notes, imaging, and prior conservative treatment documentation.",
        ],
        "notes": "Requirements may vary by state plan and vendor.",
    },
    "bcbs": {
        "display_name": "Blue Cross Blue Shield",
        "portal_name": "Availity / BCBS Provider Workflow",
        "portal_url": "https://www.availity.com",
        "fax": "Varies by state plan",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Neurologic exam",
            "Prior treatment documentation",
        ],
        "how_to_submit": [
            "Confirm the exact BCBS state plan.",
            "Use plan-specific PA workflow, often through Availity.",
            "Include full clinical packet on the first submission.",
        ],
        "notes": "BCBS requirements are highly plan specific.",
    },
    "uhc": {
        "display_name": "UnitedHealthcare",
        "portal_name": "UHC Provider Portal",
        "portal_url": "https://www.uhcprovider.com",
        "fax": "Plan specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Neurologic exam",
            "Conservative treatment history",
        ],
        "how_to_submit": [
            "Review current UHC authorization requirements.",
            "Submit through the UHC provider portal.",
            "Attach documentation showing diagnosis, symptoms, imaging, and failed nonoperative care.",
        ],
        "notes": "Rules can vary by member plan and delegated vendor.",
    },
    "aetna": {
        "display_name": "Aetna",
        "portal_name": "Availity / Aetna Provider",
        "portal_url": "https://www.aetna.com/health-care-professionals.html",
        "fax": "Plan specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "PT or medication history",
            "Neurologic findings",
        ],
        "how_to_submit": [
            "Review Aetna procedure policy first.",
            "Submit through the Aetna provider workflow.",
            "Upload supporting records and any failed conservative treatment documentation.",
        ],
        "notes": "Some requests are managed through delegated utilization vendors.",
    },
    "cigna": {
        "display_name": "Cigna",
        "portal_name": "Cigna for Health Care Professionals",
        "portal_url": "https://cignaforhcp.cigna.com",
        "fax": "Plan specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Prior conservative treatment documentation",
            "Procedure request details",
        ],
        "how_to_submit": [
            "Confirm if pre-certification is required for the member plan.",
            "Submit through the Cigna provider portal.",
            "Attach clinical note, imaging, diagnosis, and prior nonoperative care details.",
        ],
        "notes": "Plan and service site can change requirements.",
    },
    "humana": {
        "display_name": "Humana",
        "portal_name": "Availity / Humana Provider",
        "portal_url": "https://www.humana.com/provider",
        "fax": "Plan specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Neurologic findings",
            "Failed conservative treatment records",
        ],
        "how_to_submit": [
            "Check prior authorization list for the member plan.",
            "Submit through Humana provider workflow.",
            "Attach all supporting records up front.",
        ],
        "notes": "Medicare Advantage plans may use separate workflows.",
    },
    "medicare": {
        "display_name": "Medicare",
        "portal_name": "Medicare / MAC Guidance",
        "portal_url": "https://www.cms.gov",
        "fax": "Contractor specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Objective exam findings",
            "Procedure details",
        ],
        "how_to_submit": [
            "Check local MAC coverage policy and any prior authorization requirement.",
            "Follow contractor-specific workflow if authorization is required.",
            "Keep full supporting packet available for medical review.",
        ],
        "notes": "Requirements vary by contractor and service type.",
    },
    "tricare": {
        "display_name": "TRICARE",
        "portal_name": "TRICARE Provider Portal",
        "portal_url": "https://www.tricare.mil",
        "fax": "Region specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Referral if required",
            "Conservative treatment history",
        ],
        "how_to_submit": [
            "Confirm region-specific authorization policy.",
            "Submit via regional contractor workflow.",
            "Attach referral and full supporting clinical records.",
        ],
        "notes": "Requirements vary by TRICARE region and service.",
    },
    "kaiser": {
        "display_name": "Kaiser Permanente",
        "portal_name": "Kaiser Referrals / Authorizations",
        "portal_url": "https://healthy.kaiserpermanente.org",
        "fax": "Region specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Referral / internal authorization details",
            "Prior treatment history",
        ],
        "how_to_submit": [
            "Follow regional Kaiser referral and authorization workflow.",
            "Confirm any internal specialist approval requirement.",
            "Upload all clinical records and imaging.",
        ],
        "notes": "Workflows differ significantly by Kaiser region.",
    },
    "molina": {
        "display_name": "Molina Healthcare",
        "portal_name": "Molina Provider Portal",
        "portal_url": "https://provider.molinahealthcare.com",
        "fax": "Plan specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Neurologic exam",
            "Conservative care documentation",
        ],
        "how_to_submit": [
            "Verify service and plan prior authorization requirement.",
            "Submit through Molina provider portal.",
            "Attach full supporting clinical packet.",
        ],
        "notes": "Medicaid rules can be state specific.",
    },
    "centene": {
        "display_name": "Centene / Ambetter",
        "portal_name": "Centene Provider Resources",
        "portal_url": "https://www.centene.com/providers.html",
        "fax": "Plan specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Prior treatment history",
            "Procedure details",
        ],
        "how_to_submit": [
            "Confirm the exact Centene-affiliated plan.",
            "Use the plan-specific provider portal or utilization vendor.",
            "Upload records showing diagnosis, imaging, symptoms, and failed nonoperative care.",
        ],
        "notes": "Use the exact health plan, not just the parent brand.",
    },
    "oscar": {
        "display_name": "Oscar Health",
        "portal_name": "Oscar Provider Portal",
        "portal_url": "https://www.hioscar.com/providers",
        "fax": "Plan specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Treatment history",
            "Procedure details",
        ],
        "how_to_submit": [
            "Review current authorization rules for the member plan.",
            "Submit through Oscar provider workflow.",
            "Attach diagnosis, imaging, and prior treatment documentation.",
        ],
        "notes": "Coverage requirements may differ by market.",
    },
    "ambetter": {
        "display_name": "Ambetter",
        "portal_name": "Ambetter Provider Resources",
        "portal_url": "https://www.ambetterhealth.com/providers.html",
        "fax": "Plan specific",
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Prior conservative treatment history",
            "Procedure request details",
        ],
        "how_to_submit": [
            "Verify the state-specific Ambetter plan.",
            "Submit using the plan portal or delegated vendor.",
            "Attach all supporting clinical documents.",
        ],
        "notes": "State plan differences are common.",
    },
}


DIAGNOSIS_LIBRARY = {
    "lumbar": [
        {"label": "Lumbar radiculopathy", "code": "M54.16"},
        {"label": "Lumbar disc herniation", "code": "M51.26"},
        {"label": "Lumbar spinal stenosis", "code": "M48.061"},
        {"label": "Degenerative disc disease, lumbar", "code": "M51.36"},
        {"label": "Spondylolisthesis, lumbar region", "code": "M43.16"},
        {"label": "Low back pain", "code": "M54.50"},
    ],
    "cervical": [
        {"label": "Cervical radiculopathy", "code": "M54.12"},
        {"label": "Cervical myelopathy", "code": "M47.12"},
        {"label": "Cervical disc disorder with radiculopathy", "code": "M50.10"},
        {"label": "Cervical spinal stenosis", "code": "M48.02"},
        {"label": "Cervical spondylosis", "code": "M47.812"},
        {"label": "Cervicalgia", "code": "M54.2"},
    ],
    "thoracic": [
        {"label": "Thoracic radiculopathy", "code": "M54.14"},
        {"label": "Thoracic disc disorder", "code": "M51.24"},
        {"label": "Thoracic spondylosis with myelopathy", "code": "M47.14"},
        {"label": "Thoracic spinal stenosis", "code": "M48.04"},
        {"label": "Thoracic pain", "code": "M54.6"},
    ],
    "deformity": [
        {"label": "Scoliosis, unspecified", "code": "M41.9"},
        {"label": "Other secondary scoliosis", "code": "M41.50"},
        {"label": "Kyphosis, thoracic region", "code": "M40.204"},
        {"label": "Postural kyphosis", "code": "M40.00"},
        {"label": "Spinal deformity / imbalance", "code": "M43.8X9"},
    ],
    "fracture": [
        {"label": "Compression fracture of vertebra", "code": "M48.50XA"},
        {"label": "Collapsed vertebra, not elsewhere classified", "code": "M48.50XA"},
        {"label": "Age-related osteoporosis with current pathological fracture", "code": "M80.08XA"},
    ],
    "pelvis": [
        {"label": "Sacroiliitis", "code": "M46.1"},
        {"label": "Sacrococcygeal disorders, not elsewhere classified", "code": "M53.3"},
        {"label": "SI joint dysfunction", "code": "M53.3"},
    ],
    "pain": [
        {"label": "Chronic pain syndrome", "code": "G89.4"},
        {"label": "Postlaminectomy syndrome", "code": "M96.1"},
        {"label": "Other chronic postprocedural pain", "code": "G89.28"},
        {"label": "Neuralgia and neuritis, unspecified", "code": "M79.2"},
    ],
    "generic": [
        {"label": "Other intervertebral disc degeneration", "code": "M51.30"},
        {"label": "Back pain, unspecified", "code": "M54.9"},
    ],
}


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (value or "")).strip("_").upper()


def title_from_suffix(suffix: str) -> str:
    parts = re.split(r"[_\-\s]+", suffix.strip())
    return " ".join(p.title() for p in parts if p)


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def payer_key_from_name(payer_name: str) -> str:
    value = (payer_name or "").strip().lower()
    if not value:
        return "generic"
    mapping = {
        "unitedhealthcare": "uhc",
        "united healthcare": "uhc",
        "uhc": "uhc",
        "aetna": "aetna",
        "cigna": "cigna",
        "humana": "humana",
        "medicare": "medicare",
        "tricare": "tricare",
        "kaiser": "kaiser",
        "kaiser permanente": "kaiser",
        "molina": "molina",
        "molina healthcare": "molina",
        "centene": "centene",
        "ambetter": "ambetter",
        "anthem": "anthem",
        "bcbs": "bcbs",
        "blue cross blue shield": "bcbs",
        "oscar": "oscar",
        "oscar health": "oscar",
    }
    return mapping.get(value, re.sub(r"[^a-z0-9]+", "_", value).strip("_") or "generic")


def all_payer_portals() -> dict:
    merged = {}
    for key, value in BASE_PAYER_PORTALS.items():
        merged[key] = value
    for key, value in EXTRA_PAYER_PORTALS.items():
        merged[key] = value
    return merged


def get_payer_portal(payer_name: str) -> dict:
    key = payer_key_from_name(payer_name)
    merged = all_payer_portals()
    if key in merged:
        return merged[key]
    try:
        portal = base_get_payer_portal(payer_name)
        if portal:
            return portal
    except Exception:
        pass
    return merged.get("generic", {"display_name": payer_name or "Generic Payer"})


def procedure_diagnosis_options(proc_type: str) -> list[dict]:
    procedure = get_procedure(proc_type)
    region = (procedure.get("region") or "").lower()
    category = (procedure.get("category") or "").lower()

    if category == "deformity":
        return DIAGNOSIS_LIBRARY["deformity"]
    if category == "fracture":
        return DIAGNOSIS_LIBRARY["fracture"]
    if region in DIAGNOSIS_LIBRARY:
        return DIAGNOSIS_LIBRARY[region]
    if region == "thoracolumbar":
        return DIAGNOSIS_LIBRARY["thoracic"] + DIAGNOSIS_LIBRARY["lumbar"]
    return DIAGNOSIS_LIBRARY["generic"]


def get_conn() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_uid TEXT,
            patient TEXT,
            fname TEXT,
            lname TEXT,
            dob TEXT,
            member_id TEXT,
            payer TEXT,
            diagnosis TEXT,
            proc_type TEXT,
            provider TEXT,
            provider_npi TEXT,
            referring_provider TEXT,
            pain_score TEXT,
            duration TEXT,
            notes TEXT,
            criteria_results TEXT,
            portal_helper TEXT,
            letter TEXT,
            package_json TEXT,
            status TEXT,
            storage_source TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def load_providers() -> list[dict]:
    providers: list[dict] = []
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

    parts = (provider_name or "").strip().split()
    if parts:
        last = slug(parts[-1])
        for provider in providers:
            if provider["key"] == last:
                return provider["npi"]

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

    config["providers"] = load_providers()
    config["npi"] = resolve_npi(config.get("provider_name", ""), config["providers"])
    return config


def infer_cpt(proc_type: str) -> str:
    procedure = get_procedure(proc_type)
    codes = procedure.get("cpt") or []
    return ", ".join(codes) if codes else ""


def proc_label(proc_type: str) -> str:
    procedure = get_procedure(proc_type)
    return procedure.get("description") or proc_type or "Requested Procedure"


def conservative_analysis(data: dict) -> dict:
    analysis = evaluate_case(data)
    analysis["portal"] = get_payer_portal(data.get("payer") or "")
    return analysis


def try_ai_json(prompt: str, api_key: str, model_name: str) -> dict | None:
    if anthropic is None:
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            max_tokens=1400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        if fenced:
            text = fenced.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
        return json.loads(text)
    except Exception:
        return None


def build_portal_helper(data: dict, analysis: dict) -> dict:
    raw_missing = analysis.get("missing_elements") if isinstance(analysis, dict) else []
    missing = []
    for item in raw_missing or []:
        if isinstance(item, dict):
            missing.append(item)
        else:
            missing.append({"element": str(item), "detail": ""})

    portal = analysis.get("portal") or get_payer_portal(data.get("payer") or "")
    recommended_documents = analysis.get("recommended_documents") or portal.get("documents_required", [])
    proc_name = proc_label(data.get("proc_type") or data.get("procType") or "")
    status = "Ready for manual submission" if not missing else "Needs review before manual submission"

    return {
        "status": status,
        "missing": missing,
        "attachments": recommended_documents,
        "next_steps": [
            "Verify demographics, procedure, CPT, ICD-10, and requested level(s).",
            "Attach the full clinical packet on first submission whenever possible.",
            f"Use the payer workflow below to submit the {proc_name} request and track status.",
        ],
        "portal": portal,
        "payer_rules": analysis.get("payer_rules") or [],
        "common_rules": analysis.get("common_rules") or [],
        "denial_risk": analysis.get("denial_risk") or {},
    }


def normalize_case_payload(data: dict, config: dict | None = None) -> dict:
    config = config or load_config()
    providers = config.get("providers", [])

    fname = (data.get("fname") or "").strip()
    lname = (data.get("lname") or "").strip()
    patient = (data.get("patient") or f"{fname} {lname}").strip()
    provider = (data.get("provider") or config.get("provider_name") or "Treating Physician").strip()
    provider_npi = (data.get("provider_npi") or data.get("providerNpi") or "").strip()
    if not provider_npi:
        provider_npi = resolve_npi(provider, providers) or config.get("npi", "")

    member_id = (data.get("member_id") or data.get("memberId") or "").strip()
    proc_type = canonical_procedure_key((data.get("proc_type") or data.get("procType") or "").strip())

    return {
        "case_uid": (data.get("case_uid") or data.get("caseUid") or "").strip(),
        "patient": patient,
        "fname": fname,
        "lname": lname,
        "dob": (data.get("dob") or "").strip(),
        "member_id": member_id,
        "payer": (data.get("payer") or "").strip(),
        "diagnosis": (data.get("diagnosis") or "").strip(),
        "proc_type": proc_type,
        "provider": provider,
        "provider_npi": provider_npi,
        "referring_provider": (data.get("referring_provider") or data.get("referringProvider") or "").strip(),
        "pain_score": str(data.get("pain_score") or data.get("painScore") or "").strip(),
        "duration": str(data.get("duration") or "").strip(),
        "notes": (data.get("notes") or "").strip(),
        "clinical_note": (data.get("clinical_note") or data.get("clinicalNote") or data.get("notes") or "").strip(),
        "conservative_treatment": (data.get("conservative_treatment") or data.get("conservativeTreatment") or "").strip(),
        "imaging_summary": (data.get("imaging_summary") or data.get("imagingSummary") or "").strip(),
        "criteria_results": data.get("criteria_results") or data.get("criteriaResults") or [],
        "portal_helper": data.get("portal_helper") or data.get("portalHelper") or {},
        "letter": (data.get("letter") or "").strip(),
        "package_json": data.get("package_json") or data.get("packageJson") or {},
        "status": (data.get("status") or "submitted").strip() or "submitted",
        "storage_source": (data.get("storage_source") or data.get("storageSource") or "backend").strip() or "backend",
    }


def build_structured_letter(data: dict, practice_name: str) -> tuple[str, dict]:
    patient = (data.get("patient") or "").strip()
    dob = (data.get("dob") or "").strip()
    member_id = (data.get("member_id") or data.get("memberId") or "").strip()
    payer = (data.get("payer") or "").strip()
    diagnosis_raw = data.get("diagnosis") or ""
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(diagnosis_raw)
    proc_type = (data.get("proc_type") or data.get("procType") or "").strip()
    pain_score = (data.get("pain_score") or data.get("painScore") or "").strip()
    duration = (data.get("duration") or "").strip()
    notes = (data.get("notes") or "").strip()
    conservative_treatment = (data.get("conservative_treatment") or "").strip()
    imaging_summary = (data.get("imaging_summary") or "").strip()
    referring_provider = (data.get("referring_provider") or data.get("referringProvider") or "").strip()
    provider = (data.get("provider") or "Treating Physician").strip()
    provider_npi = (data.get("provider_npi") or data.get("providerNpi") or "").strip()

    procedure = get_procedure(proc_type)
    cpt_code = infer_cpt(proc_type)
    proc_name = proc_label(proc_type)
    analysis = conservative_analysis(data)
    portal = analysis.get("portal") or get_payer_portal(payer)
    today = date.today().strftime("%B %d, %Y")

    clinical_summary_parts = []
    if notes:
        clinical_summary_parts.append(notes)
    if conservative_treatment:
        clinical_summary_parts.append(f"Conservative treatment history: {conservative_treatment}")
    if imaging_summary:
        clinical_summary_parts.append(f"Imaging summary: {imaging_summary}")

    clinical_summary = "\n\n".join(clinical_summary_parts) if clinical_summary_parts else (
        f"The patient presents for evaluation related to "
        f"{diagnosis_text or diagnosis_raw or 'the requested service'} with persistent symptoms "
        f"documented in the intake form."
    )

    payer_points = analysis.get("payer_rules") or ["See attached clinical records and imaging."]
    document_points = analysis.get("recommended_documents") or procedure.get("required_documents") or [
        "Clinical note",
        "Imaging report",
    ]

    medical_necessity = (
        f"{proc_name} is requested for the diagnosis of "
        f"{diagnosis_text or diagnosis_raw or '[Diagnosis Not Provided]'}. "
        f"Current documentation reflects symptom duration of {duration or 'not specified'} "
        f"and pain severity of {pain_score or 'not specified'}/10. "
        f"Structured payer-readiness review estimates an approval support score of "
        f"{analysis.get('approval_score', 'N/A')}% with "
        f"{analysis.get('approval_likelihood', 'moderate')} likelihood if the missing items below are addressed."
    )

    letter = f"""# PRIOR AUTHORIZATION REQUEST LETTER

DATE: {today}

TO: {payer or 'Insurance Prior Authorization Department'}

FROM: {provider} | NPI: {provider_npi or '[NPI Not Provided]'}
{practice_name}

RE: Prior Authorization Request – {proc_name} (CPT {cpt_code or 'N/A'})

## 1. PATIENT INFORMATION

Patient Name: {patient or '[Patient Name Not Provided]'}
Date of Birth: {dob or '[DOB Not Provided]'}
Insurance / Payer: {payer or '[Payer Not Provided]'}
Member ID: {member_id or '[Member ID Not Provided]'}

## 2. CLINICAL SUMMARY

{clinical_summary}

## 3. MEDICAL NECESSITY

{medical_necessity}

## 4. REQUESTED PROCEDURE AND CODING

Procedure Requested: {proc_name}
CPT Code(s): {cpt_code or 'N/A'}
Diagnosis: {diagnosis_text or diagnosis_raw or '[Diagnosis Not Provided]'}
ICD-10 Code: {icd_code or '[ICD-10 Not Provided]'}
Pain Score: {pain_score or '[Not Provided]'}
Duration of Symptoms: {duration or '[Not Provided]'}
Ordering Provider: {provider}
Provider NPI: {provider_npi or '[NPI Not Provided]'}
Referring Provider: {referring_provider or '[Not Provided]'}
Practice Name: {practice_name}

## 5. PAYER-SPECIFIC SUPPORTING POINTS

{"".join(f"- {item}\n" for item in payer_points)}

## 6. ATTACHED / EXPECTED SUPPORTING DOCUMENTS

{"".join(f"- {item}\n" for item in document_points)}

## 7. SUBMISSION PATHWAY

Payer Pathway: {portal.get('portal_name', '')}
Portal Link: {portal.get('portal_url', '') or '[See payer portal]'}

## 8. CLOSING REQUEST / CONCLUSION

Please review this request for prior authorization. This packet includes patient-specific demographics, diagnosis coding, requested CPT coding, and supporting clinical documentation aligned to the payer workflow. If additional information is needed, please contact our office.

Respectfully,

{provider}
Ordering Provider | NPI: {provider_npi or '[NPI Not Provided]'}
{practice_name}
"""

    structured = {
        "patient": patient,
        "dob": dob,
        "member_id": member_id,
        "payer": payer,
        "procedure": proc_name,
        "procedure_key": canonical_procedure_key(proc_type),
        "cpt_code": cpt_code,
        "diagnosis": diagnosis_text or diagnosis_raw,
        "icd_10": icd_code,
        "provider": provider,
        "provider_npi": provider_npi,
        "referring_provider": referring_provider,
    }
    return letter, structured


def build_package_payload(data: dict, config: dict) -> dict:
    normalized = normalize_case_payload(data, config)
    analysis = conservative_analysis(normalized)
    helper = normalized.get("portal_helper") or build_portal_helper(normalized, analysis)
    letter, structured = build_structured_letter(normalized, config.get("practice_name", "Spine Clinic"))
    criteria_results = normalized.get("criteria_results") or analysis.get("criteria_results") or []

    return {
        "generated_at": now_iso(),
        "practice_name": config.get("practice_name", "Spine Clinic"),
        "patient": {
            "name": normalized["patient"],
            "dob": normalized["dob"],
            "member_id": normalized["member_id"],
            "payer": normalized["payer"],
        },
        "request": {
            "procedure": structured["procedure"],
            "procedure_key": structured["procedure_key"],
            "cpt_code": structured["cpt_code"],
            "diagnosis": structured["diagnosis"],
            "icd_10": structured["icd_10"],
            "pain_score": normalized["pain_score"],
            "duration": normalized["duration"],
        },
        "providers": {
            "ordering_provider": normalized["provider"],
            "provider_npi": normalized["provider_npi"],
            "referring_provider": normalized["referring_provider"],
        },
        "clinical_notes": normalized["notes"],
        "conservative_treatment": normalized.get("conservative_treatment", ""),
        "imaging_summary": normalized.get("imaging_summary", ""),
        "criteria_results": criteria_results,
        "analysis": analysis,
        "portal_helper": helper,
        "procedure_details": get_procedure(normalized["proc_type"]),
        "letter": normalized["letter"] or letter,
        "submission_checklist": helper.get("attachments", []),
        "submission_steps": (helper.get("portal") or {}).get("how_to_submit", []),
        "portal": helper.get("portal") or {},
        "denial_risk": analysis.get("denial_risk") or {},
    }


def row_to_case(row: sqlite3.Row) -> dict:
    package_json = json.loads(row["package_json"] or "{}")

    return {
        "id": row["id"],
        "caseUid": row["case_uid"] or f"CASE-{row['id']}",
        "patient": row["patient"],
        "fname": row["fname"],
        "lname": row["lname"],
        "dob": row["dob"],
        "memberId": row["member_id"],
        "payer": row["payer"],
        "diagnosis": row["diagnosis"],
        "procType": row["proc_type"],
        "provider": row["provider"],
        "providerNpi": row["provider_npi"],
        "referringProvider": row["referring_provider"],
        "painScore": row["pain_score"],
        "duration": row["duration"],
        "notes": row["notes"],
        "conservativeTreatment": package_json.get("conservative_treatment", ""),
        "imagingSummary": package_json.get("imaging_summary", ""),
        "criteriaResults": json.loads(row["criteria_results"] or "[]"),
        "portalHelper": json.loads(row["portal_helper"] or "{}"),
        "packageJson": package_json,
        "letter": row["letter"],
        "status": row["status"],
        "storageSource": row["storage_source"] or "backend",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/favicon.ico")
def favicon():
    target = PUBLIC_DIR / "favicon.ico"
    if target.exists():
        return send_from_directory(PUBLIC_DIR, "favicon.ico")
    return ("", 204)


@app.route("/<path:path>")
def static_files(path: str):
    target = PUBLIC_DIR / path
    if target.exists():
        return send_from_directory(PUBLIC_DIR, path)
    return jsonify({"error": "Not found"}), 404


@app.route("/status")
def status():
    config = load_config()
    merged_payers = all_payer_portals()
    return jsonify(
        {
            "running": True,
            "has_api_key": bool(config.get("api_key")),
            "practice_name": config.get("practice_name", ""),
            "provider_name": config.get("provider_name", ""),
            "npi": config.get("npi", ""),
            "providers": config.get("providers", []),
            "storage_mode": "ephemeral_backend_sqlite",
            "db_file": str(DB_FILE),
            "procedures": [
                {
                    "key": k,
                    **v,
                    "diagnosis_options": procedure_diagnosis_options(k),
                }
                for k, v in PROCEDURES.items()
            ],
            "payers": [{"key": k, **v} for k, v in merged_payers.items() if k != "generic"],
            "diagnosis_library": DIAGNOSIS_LIBRARY,
        }
    )


@app.route("/settings")
def settings():
    config = load_config()
    merged_payers = all_payer_portals()
    return jsonify(
        {
            "practice_name": config.get("practice_name", "Spine Clinic"),
            "provider_name": config.get("provider_name", "Treating Physician"),
            "has_api_key": bool(config.get("api_key")),
            "providers": config.get("providers", []),
            "procedures": [
                {
                    "key": k,
                    **v,
                    "diagnosis_options": procedure_diagnosis_options(k),
                }
                for k, v in PROCEDURES.items()
            ],
            "payers": [{"key": k, **v} for k, v in merged_payers.items() if k != "generic"],
            "diagnosis_library": DIAGNOSIS_LIBRARY,
        }
    )


@app.route("/knowledge-base")
def knowledge_base():
    merged_payers = all_payer_portals()
    return jsonify(
        {
            "procedures": [
                {
                    "key": k,
                    **v,
                    "diagnosis_options": procedure_diagnosis_options(k),
                }
                for k, v in PROCEDURES.items()
            ],
            "payers": [{"key": k, **v} for k, v in merged_payers.items()],
            "diagnosis_library": DIAGNOSIS_LIBRARY,
        }
    )


@app.route("/analyze", methods=["POST"])
def analyze():
    config = load_config()
    normalized = normalize_case_payload(request.json or {}, config)
    analysis = conservative_analysis(normalized)

    api_key = config.get("api_key")
    if api_key:
        prompt = f"""
You are a medical prior authorization specialist.
Analyze the following request and return JSON with keys: summary, medical_necessity, approval_likelihood, approval_score, strengths, missing_elements.
For missing_elements, return a list of objects with keys "element" and "detail".
Do not change patient demographic values.

PATIENT: {normalized['patient']}
PAYER: {normalized['payer']}
ORDERING PROVIDER: {normalized['provider']}
NPI: {normalized['provider_npi']}
PROCEDURE: {normalized['proc_type']}
DIAGNOSIS: {normalized['diagnosis']}
PAIN SCORE: {normalized['pain_score']}
DURATION: {normalized['duration']}
CLINICAL SUMMARY:
{normalized['notes']}

CONSERVATIVE TREATMENT:
{normalized.get('conservative_treatment', '')}

IMAGING SUMMARY:
{normalized.get('imaging_summary', '')}
"""
        ai_json = try_ai_json(
            prompt,
            api_key,
            config.get("anthropic_model") or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        )
        if isinstance(ai_json, dict):
            analysis = {**analysis, **ai_json}
            analysis["portal"] = get_payer_portal(normalized.get("payer") or "")

    portal_helper = build_portal_helper(normalized, analysis)
    return jsonify(
        {
            "analysis": analysis,
            "portal_helper": portal_helper,
            "criteria_results": analysis.get("criteria_results", []),
            "echo_input": {
                "patient": normalized["patient"],
                "payer": normalized["payer"],
                "diagnosis": normalized["diagnosis"],
                "provider": normalized["provider"],
                "provider_npi": normalized["provider_npi"],
            },
        }
    )


@app.route("/generate-letter", methods=["POST"])
def generate_letter():
    config = load_config()
    normalized = normalize_case_payload(request.json or {}, config)
    letter, structured = build_structured_letter(normalized, config.get("practice_name", "Spine Clinic"))
    return jsonify(
        {
            "letter": letter,
            "structured": structured,
            "echo_input": {
                "patient": normalized["patient"],
                "payer": normalized["payer"],
                "dob": normalized["dob"],
                "member_id": normalized["member_id"],
            },
            **structured,
        }
    )


@app.route("/build-package", methods=["POST"])
def build_package():
    config = load_config()
    return jsonify(build_package_payload(request.json or {}, config))


@app.route("/export-package", methods=["POST"])
def export_package():
    config = load_config()
    package = build_package_payload(request.json or {}, config)
    export_dir = Path("/tmp/spinepa_exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    case_stub = slug(package["patient"].get("name", "case") or "case")[:40] or "CASE"
    outfile = export_dir / f"{case_stub}_PA_PACKAGE.json"
    outfile.write_text(json.dumps(package, indent=2), encoding="utf-8")
    return send_file(outfile, as_attachment=True, download_name=outfile.name, mimetype="application/json")


@app.route("/cases", methods=["GET"])
def list_cases():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cases ORDER BY datetime(updated_at) DESC, id DESC").fetchall()
    conn.close()
    return jsonify({"cases": [row_to_case(r) for r in rows]})


@app.route("/cases/<int:case_id>", methods=["GET"])
def get_case(case_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Case not found"}), 404
    return jsonify({"case": row_to_case(row)})


@app.route("/submit", methods=["POST"])
@app.route("/cases", methods=["POST"])
def create_case():
    config = load_config()
    payload = normalize_case_payload(request.json or {}, config)
    analysis = conservative_analysis(payload)
    payload["criteria_results"] = payload["criteria_results"] or analysis.get("criteria_results") or []
    payload["portal_helper"] = payload["portal_helper"] or build_portal_helper(payload, analysis)
    package = build_package_payload(payload, config)
    now = now_iso()

    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO cases (
            case_uid, patient, fname, lname, dob, member_id, payer, diagnosis, proc_type,
            provider, provider_npi, referring_provider, pain_score, duration,
            notes, criteria_results, portal_helper, letter, package_json, status, storage_source,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["case_uid"] or f"CASE-{slug(payload['patient']) or 'PATIENT'}-{int(datetime.utcnow().timestamp())}",
            payload["patient"],
            payload["fname"],
            payload["lname"],
            payload["dob"],
            payload["member_id"],
            payload["payer"],
            payload["diagnosis"],
            payload["proc_type"],
            payload["provider"],
            payload["provider_npi"],
            payload["referring_provider"],
            payload["pain_score"],
            payload["duration"],
            payload["notes"],
            json.dumps(payload["criteria_results"]),
            json.dumps(payload["portal_helper"]),
            payload["letter"] or package["letter"],
            json.dumps(package),
            payload["status"],
            payload["storage_source"],
            now,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return jsonify({"ok": True, "case": row_to_case(row)})


@app.route("/cases/<int:case_id>", methods=["PUT"])
def update_case(case_id: int):
    config = load_config()
    payload = normalize_case_payload(request.json or {}, config)
    analysis = conservative_analysis(payload)
    payload["criteria_results"] = payload["criteria_results"] or analysis.get("criteria_results") or []
    payload["portal_helper"] = payload["portal_helper"] or build_portal_helper(payload, analysis)
    package = build_package_payload(payload, config)
    now = now_iso()

    conn = get_conn()
    existing = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Case not found"}), 404

    conn.execute(
        """
        UPDATE cases
        SET case_uid = ?, patient = ?, fname = ?, lname = ?, dob = ?, member_id = ?, payer = ?, diagnosis = ?,
            proc_type = ?, provider = ?, provider_npi = ?, referring_provider = ?,
            pain_score = ?, duration = ?, notes = ?, criteria_results = ?, portal_helper = ?,
            letter = ?, package_json = ?, status = ?, storage_source = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            payload["case_uid"] or existing["case_uid"],
            payload["patient"],
            payload["fname"],
            payload["lname"],
            payload["dob"],
            payload["member_id"],
            payload["payer"],
            payload["diagnosis"],
            payload["proc_type"],
            payload["provider"],
            payload["provider_npi"],
            payload["referring_provider"],
            payload["pain_score"],
            payload["duration"],
            payload["notes"],
            json.dumps(payload["criteria_results"]),
            json.dumps(payload["portal_helper"]),
            payload["letter"] or package["letter"],
            json.dumps(package),
            payload["status"],
            payload["storage_source"],
            now,
            case_id,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    return jsonify({"ok": True, "case": row_to_case(row)})


@app.route("/cases/<int:case_id>", methods=["DELETE"])
def delete_case(case_id: int):
    conn = get_conn()
    row = conn.execute("SELECT id FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Case not found"}), 404
    conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deleted": case_id})


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050)