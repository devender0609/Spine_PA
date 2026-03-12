from __future__ import annotations

COMMON_RULES = {
    "diagnostic_mri": [
        "Specific neurologic, radicular, or red-flag indication documented",
        "Specific ICD-10 code and symptom duration documented",
        "Conservative treatment history unless urgent neurologic concern",
        "Exam findings or rationale for imaging escalation",
    ],
    "decompression": [
        "Symptoms correlate with imaging findings",
        "Objective neurologic or radicular findings documented",
        "Reasonable nonoperative care attempted unless urgent deficit",
        "Procedure level(s) clearly identified",
    ],
    "fusion": [
        "Structural pathology or instability documented",
        "Failure of nonoperative treatment duration documented",
        "Functional limitation and/or pain severity documented",
        "Imaging supports the operative target level(s)",
        "Specific ICD-10 and CPT coding documented",
    ],
    "si_joint_fusion": [
        "SI pain source supported by exam",
        "Alternative pain generators reasonably excluded",
        "Diagnostic SI injection response documented",
        "Conservative care history documented",
    ],
    "neuromodulation": [
        "Chronic pain diagnosis and prior treatment history documented",
        "Pain distribution/function documented",
        "Psychological clearance when required by plan",
        "For permanent implant, successful trial documented",
    ],
    "deformity": [
        "Standing radiographs and deformity parameters documented",
        "Functional disability documented",
        "Nonoperative care history documented",
        "Levels and surgical rationale clearly specified",
    ],
    "pain": [
        "Pain generator documented",
        "Imaging or diagnostic block evidence documented when required",
        "Conservative care history documented",
        "Prior response to injections/blocks documented when relevant",
    ],
}

PAYER_RULES = {
    "united_healthcare": {
        "default": [
            "Use member-specific prior authorization lookup first",
            "Upload complete clinical records at initial submission",
            "Supportive imaging and conservative treatment history should be attached when applicable",
        ],
        "lumbar_microdiscectomy": [
            "MRI showing disc herniation or compressive lesion",
            "Radiculopathy correlating with imaging",
            "At least about 6 weeks of conservative therapy unless progressive deficit",
            "Failure of PT, medication, or other nonoperative care",
        ],
        "lumbar_tlif": [
            "Instability, spondylolisthesis, recurrent stenosis, or comparable structural pathology documented",
            "Extended failed conservative therapy documented",
            "Functional impairment documented",
            "Imaging including instability studies when relevant",
        ],
    },
    "aetna": {
        "default": [
            "Submit through Availity and attach imaging plus office notes",
            "Clearly document prior treatment failure and diagnosis specificity",
        ],
        "lumbar_tlif": [
            "Spondylolisthesis, instability, recurrent stenosis, or equivalent pathology documented",
            "Failed conservative treatment generally documented over a meaningful period",
            "Imaging supports the requested operative level(s)",
            "Functional limitation/disability documented",
        ],
        "acdf": [
            "Cervical radiculopathy or myelopathy documented",
            "MRI/CT correlates with symptoms",
            "Conservative treatment history documented unless deficit warrants earlier surgery",
        ],
    },
    "cigna": {
        "default": [
            "Confirm whether the request is handled directly by Cigna or by a delegated review pathway",
            "Provide imaging, office note, medication history, and PT history when relevant",
        ],
        "epidural_steroid_injection": [
            "Imaging or clinical evidence of radicular pain source",
            "Failure of medication and/or PT where appropriate",
            "Pain distribution and severity documented",
        ],
        "spinal_cord_stimulator_trial": [
            "Chronic neuropathic pain history documented",
            "Conservative and interventional treatment failure documented",
            "Psychological clearance and goals documented when required",
        ],
    },
    "anthem_bcbs": {
        "default": [
            "Verify the local BCBS plan's policy in Availity or plan-specific tools",
            "Attach imaging, office note, and functional scores when relevant",
        ],
        "lumbar_tlif": [
            "Structural pathology/instability documented",
            "Failed conservative therapy documented",
            "ODI or comparable functional disability measure helpful when available",
            "Imaging supports requested level(s)",
        ],
        "sacroiliac_joint_fusion": [
            "Positive SI provocative testing documented",
            "Diagnostic injection response documented",
            "Conservative treatment history documented",
        ],
    },
    "humana": {
        "default": [
            "Use Humana's search tool to confirm medical prior authorization requirements",
            "Attach all relevant records at first submission",
        ],
        "lumbar_laminectomy": [
            "Imaging-confirmed stenosis/compression",
            "Symptoms correlate with imaging",
            "Conservative care documented unless urgent deficit",
        ],
    },
    "medicare": {
        "default": [
            "Confirm whether the exact service and setting are subject to prior authorization or pre-claim review",
            "Submit the same documentation needed to support payment to the applicable MAC workflow when required",
        ],
        "vertebroplasty": [
            "Fracture documentation and medical necessity clearly documented",
            "Imaging and symptom severity included",
        ],
    },
}
