from __future__ import annotations

import re
from typing import Any

from procedures import canonical_procedure_key, get_procedure
from submission_portals import canonical_payer_key, get_payer_portal
from payer_rules import COMMON_RULES, PAYER_RULES


def normalize_diagnosis_and_icd(diagnosis: str) -> tuple[str, str]:
    raw = (diagnosis or "").strip()
    if not raw:
        return "", ""
    match = re.match(r"^\s*([A-Z][0-9A-Z][0-9A-Z](?:\.[0-9A-Z]+)?)\s*[-—:]\s*(.+?)\s*$", raw)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    if re.match(r"^[A-Z][0-9A-Z][0-9A-Z](?:\.[0-9A-Z]+)?$", raw):
        return "", raw
    return raw, ""


def has_specific_icd(icd_code: str) -> bool:
    if not icd_code or "." not in icd_code:
        return False
    tail = icd_code.split(".", 1)[1]
    return bool(tail and not re.fullmatch(r"X+", tail, re.I))


def _has_any(text: str, *terms: str) -> bool:
    return any(t in text for t in terms)


def _weeks_value(duration: str) -> int | None:
    match = re.search(r"(\d+)", duration or "")
    return int(match.group(1)) if match else None


def infer_rule_family(proc_key: str, proc: dict[str, Any]) -> str:
    category = proc.get("category", "")
    if category == "diagnostic":
        return "diagnostic_mri"
    if category == "decompression":
        return "decompression"
    if category == "fusion":
        if proc_key == "sacroiliac_joint_fusion":
            return "si_joint_fusion"
        return "fusion"
    if category == "neuromodulation":
        return "neuromodulation"
    if category == "deformity":
        return "deformity"
    if category in {"pain", "therapy"}:
        return "pain"
    return "decompression"


def evaluate_case(data: dict[str, Any]) -> dict[str, Any]:
    notes = (data.get("notes") or "").lower()
    proc_key = canonical_procedure_key(data.get("proc_type") or data.get("procType") or "")
    proc = get_procedure(proc_key)
    payer_key = canonical_payer_key(data.get("payer") or "")
    portal = get_payer_portal(data.get("payer") or "")
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(data.get("diagnosis") or "")
    duration = str(data.get("duration") or "")
    pain_score = str(data.get("pain_score") or data.get("painScore") or "")
    pain_num = int(pain_score) if pain_score.isdigit() else None
    weeks = _weeks_value(duration)

    has_imaging = _has_any(notes, "mri", "ct", "x-ray", "xray", "radiograph", "stenosis", "herniation", "compression", "foraminal")
    has_neuro = _has_any(notes, "radicul", "numb", "weak", "myelopath", "sciatica", "claudication", "paresthesia", "deficit")
    has_conservative = _has_any(notes, "physical therapy", "pt", "home exercise", "nsaid", "medication", "chiropractic", "injection", "conservative")
    has_function = _has_any(notes, "functional", "adl", "disability", "odI", "odi", "walk", "standing", "sleep", "work")
    has_instability = _has_any(notes, "instability", "spondylolisthesis", "listhesis", "dynamic")
    has_deformity = _has_any(notes, "scoliosis", "sagittal", "coronal", "imbalance", "kyphosis")
    has_si_exam = _has_any(notes, "fabER", "gaenslen", "compression test", "distraction test", "thigh thrust", "si joint")
    has_psych = _has_any(notes, "psychological clearance", "psych eval", "psychological evaluation")
    has_trial_success = _has_any(notes, "trial success", "50% pain relief", "greater than 50% relief", "successful trial")

    strengths: list[str] = []
    missing: list[dict[str, str]] = []
    criteria_results: list[dict[str, Any]] = []

    def add(label: str, met: bool, required: bool = True, detail: str = ""):
        criteria_results.append({
            "id": f"c{len(criteria_results)+1}",
            "label": label,
            "required": required,
            "status": "met" if met else ("missing" if required else "unmet"),
            "detail": detail,
        })
        if met:
            strengths.append(label)
        elif required:
            missing.append({"element": label, "detail": detail or "Not clearly documented in the current inputs."})

    add("Specific ICD-10 diagnosis documented", has_specific_icd(icd_code), True, "Use the most specific supported ICD-10 code.")
    add("Procedure selected", bool(proc_key), True, "Select the requested procedure.")
    add("Office / clinical note provided", bool(notes.strip()), True, "Add a concise structured clinical summary or visit note.")
    add("Symptom duration documented", bool(duration.strip()), True, "Enter duration such as 8 weeks, 3 months, or 1 year.")

    family = infer_rule_family(proc_key, proc)
    if family == "diagnostic_mri":
        add("Neurologic, radicular, or red-flag indication documented", has_neuro or pain_num and pain_num >= 6, True)
        add("Conservative treatment history documented when applicable", has_conservative or (weeks is not None and weeks >= 6), True)
    elif family == "decompression":
        add("Imaging supports the requested level or pathology", has_imaging, True, "Reference the MRI/CT findings relevant to the requested level.")
        add("Symptoms correlate with imaging", has_neuro, True, "Document radicular, myelopathic, or claudication findings that match the level.")
        add("Conservative treatment attempted unless urgent deficit", has_conservative or (weeks is not None and weeks >= 6), True)
    elif family == "fusion":
        add("Structural pathology or instability documented", has_instability or has_imaging or has_deformity, True, "For fusion requests, document spondylolisthesis, instability, deformity, recurrent stenosis, or similar structural pathology.")
        add("Extended nonoperative care documented", has_conservative or (weeks is not None and weeks >= 6), True, "Document PT, medication, injections, home exercise, or other nonoperative care.")
        add("Functional limitation or disability documented", has_function or (pain_num is not None and pain_num >= 6), True, "Include ODI or a clear description of walking, standing, work, ADL, or sleep limitation.")
        add("Imaging supports operative level(s)", has_imaging, True, "Attach MRI, CT, or flexion-extension imaging as appropriate.")
    elif family == "si_joint_fusion":
        add("Positive SI joint exam findings documented", has_si_exam, True)
        add("Diagnostic SI injection response documented", _has_any(notes, "diagnostic injection", "relief after injection", "si injection"), True)
        add("Conservative care history documented", has_conservative or (weeks is not None and weeks >= 6), True)
    elif family == "neuromodulation":
        add("Chronic pain history documented", bool(notes.strip()), True)
        add("Prior treatment failure documented", has_conservative, True)
        if proc_key == "spinal_cord_stimulator_implant":
            add("Successful trial documented", has_trial_success, True)
        add("Psychological clearance documented when required", has_psych, False)
    elif family == "deformity":
        add("Deformity parameters or standing radiographs documented", has_deformity or has_imaging, True)
        add("Functional disability documented", has_function or (pain_num is not None and pain_num >= 6), True)
        add("Nonoperative care documented", has_conservative or (weeks is not None and weeks >= 6), True)
    else:
        add("Pain generator documented", bool(notes.strip()), True)
        add("Conservative care documented", has_conservative or (weeks is not None and weeks >= 6), True)

    payer_specific = PAYER_RULES.get(payer_key, {}).get(proc_key) or PAYER_RULES.get(payer_key, {}).get("default") or []
    common_rules = COMMON_RULES.get(family, [])

    total_required = len([c for c in criteria_results if c["required"]]) or 1
    met_required = len([c for c in criteria_results if c["required"] and c["status"] == "met"])
    approval_score = round((met_required / total_required) * 100)
    if approval_score >= 85:
        likelihood = "high"
    elif approval_score >= 60:
        likelihood = "moderate"
    else:
        likelihood = "low"

    recommended_docs = list(dict.fromkeys((proc.get("required_documents") or []) + portal.get("documents_required", [])))
    denial_risks = [m["element"] for m in missing[:5]]

    summary = f"{proc.get('description', proc_key or 'Requested procedure')} reviewed against structured spine PA rules for {portal.get('label', 'the selected payer')}."
    medical_necessity = (
        f"Request reviewed for {proc.get('description', proc_key or 'the requested procedure')}. "
        f"Approval readiness is {likelihood} ({approval_score}%). "
        f"Strengthen the packet by resolving flagged gaps and attaching the recommended supporting records."
    )

    return {
        "summary": summary,
        "medical_necessity": medical_necessity,
        "approval_likelihood": likelihood,
        "approval_score": approval_score,
        "strengths": strengths,
        "missing_elements": missing,
        "criteria_results": criteria_results,
        "procedure": proc,
        "procedure_key": proc_key,
        "payer_key": payer_key,
        "common_rules": common_rules,
        "payer_rules": payer_specific,
        "recommended_documents": recommended_docs,
        "portal": portal,
        "denial_risk": {
            "level": "high" if len(missing) >= 4 else "moderate" if len(missing) >= 2 else "low",
            "top_reasons": denial_risks,
        },
        "structured": {
            "diagnosis_text": diagnosis_text,
            "icd_code": icd_code,
            "pain_score": pain_num,
            "duration_weeks_hint": weeks,
        },
    }
