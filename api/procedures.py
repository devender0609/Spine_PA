from __future__ import annotations

PROCEDURES = {
    "acdf": {
        "description": "Anterior Cervical Discectomy and Fusion (ACDF)",
        "region": "cervical",
        "category": "fusion",
        "cpt": ["22551", "22552", "22853", "22845"],
        "typical_indications": [
            "Cervical radiculopathy",
            "Cervical myelopathy",
            "Disc herniation",
            "Spondylosis with neurologic compression",
        ],
        "required_documents": [
            "Office note with neurologic exam",
            "Cervical MRI or CT report",
            "Failure of conservative care unless urgent neurologic deficit",
            "Specific ICD-10 diagnosis",
        ],
    },
    "cervical_disc_arthroplasty": {
        "description": "Cervical Disc Arthroplasty",
        "region": "cervical",
        "category": "arthroplasty",
        "cpt": ["22856", "22858"],
        "typical_indications": [
            "Single-level or selected two-level cervical radiculopathy",
            "Disc herniation",
            "Preserved segment motion",
        ],
        "required_documents": [
            "Office note with neurologic exam",
            "Cervical MRI report",
            "Conservative treatment history",
            "Implant level request",
        ],
    },
    "posterior_cervical_fusion": {
        "description": "Posterior Cervical Fusion",
        "region": "cervical",
        "category": "fusion",
        "cpt": ["22600", "22614", "22842"],
        "typical_indications": [
            "Instability",
            "Deformity",
            "Multilevel stenosis with instability",
        ],
        "required_documents": [
            "Operative plan with levels",
            "Imaging demonstrating instability or deformity",
            "Neurologic findings",
        ],
    },
    "cervical_laminectomy": {
        "description": "Cervical Laminectomy",
        "region": "cervical",
        "category": "decompression",
        "cpt": ["63045", "63048"],
        "typical_indications": [
            "Cervical stenosis",
            "Myelopathy",
            "Posterior decompression need",
        ],
        "required_documents": [
            "MRI or CT evidence of central stenosis",
            "Myelopathic symptoms/signs",
            "Neurologic exam",
        ],
    },
    "cervical_laminoplasty": {
        "description": "Cervical Laminoplasty",
        "region": "cervical",
        "category": "decompression",
        "cpt": ["63050", "63051"],
        "typical_indications": [
            "Multilevel cervical stenosis",
            "Cervical myelopathy",
            "Motion-preserving posterior decompression",
        ],
        "required_documents": [
            "Cervical MRI report",
            "Documented myelopathy",
            "Proposed operative levels",
        ],
    },
    "lumbar_microdiscectomy": {
        "description": "Lumbar Microdiscectomy",
        "region": "lumbar",
        "category": "decompression",
        "cpt": ["63030"],
        "typical_indications": [
            "Lumbar disc herniation",
            "Radiculopathy",
            "Failed conservative therapy",
        ],
        "required_documents": [
            "Lumbar MRI report",
            "Radicular symptoms correlating with imaging",
            "Conservative treatment history",
        ],
    },
    "lumbar_laminectomy": {
        "description": "Lumbar Laminectomy / Decompression",
        "region": "lumbar",
        "category": "decompression",
        "cpt": ["63047", "63048"],
        "typical_indications": [
            "Lumbar stenosis",
            "Neurogenic claudication",
            "Radiculopathy",
        ],
        "required_documents": [
            "Lumbar MRI or CT report",
            "Walking intolerance / claudication history",
            "Conservative treatment history",
        ],
    },
    "lumbar_tlif": {
        "description": "Transforaminal Lumbar Interbody Fusion (TLIF)",
        "region": "lumbar",
        "category": "fusion",
        "cpt": ["22630", "22632", "22853", "22840"],
        "typical_indications": [
            "Spondylolisthesis",
            "Instability",
            "Recurrent stenosis or foraminal collapse",
            "Degenerative disc disease with instability",
        ],
        "required_documents": [
            "Office note with pain and function history",
            "MRI report and, when relevant, flexion-extension X-rays",
            "Documented nonoperative care",
            "Functional limitation or disability measure",
        ],
    },
    "lumbar_plif": {
        "description": "Posterior Lumbar Interbody Fusion (PLIF)",
        "region": "lumbar",
        "category": "fusion",
        "cpt": ["22630", "22632", "22853", "22842"],
        "typical_indications": [
            "Instability",
            "Recurrent disc or stenosis",
            "Spondylolisthesis",
        ],
        "required_documents": [
            "MRI report",
            "Failed conservative care",
            "Structural pathology documentation",
        ],
    },
    "lumbar_alif": {
        "description": "Anterior Lumbar Interbody Fusion (ALIF)",
        "region": "lumbar",
        "category": "fusion",
        "cpt": ["22558", "22585", "22853"],
        "typical_indications": [
            "Degenerative disc disease",
            "Spondylolisthesis",
            "Segmental instability",
        ],
        "required_documents": [
            "Lumbar MRI report",
            "Conservative care history",
            "Rationale for anterior approach",
        ],
    },
    "lumbar_llif_xlif": {
        "description": "LLIF / XLIF",
        "region": "lumbar",
        "category": "fusion",
        "cpt": ["22558", "22585", "22853"],
        "typical_indications": [
            "Degenerative scoliosis",
            "Foraminal collapse",
            "Instability",
        ],
        "required_documents": [
            "MRI or CT report",
            "Coronal/sagittal deformity rationale when relevant",
            "Failed conservative care",
        ],
    },
    "posterior_lumbar_fusion": {
        "description": "Posterior Lumbar Fusion",
        "region": "lumbar",
        "category": "fusion",
        "cpt": ["22612", "22614", "22842"],
        "typical_indications": [
            "Instability",
            "Spondylolisthesis",
            "Pseudoarthrosis or revision setting",
        ],
        "required_documents": [
            "MRI and/or CT report",
            "Flexion-extension imaging if instability is claimed",
            "Failed conservative management",
        ],
    },
    "lumbar_foraminotomy": {
        "description": "Lumbar Foraminotomy",
        "region": "lumbar",
        "category": "decompression",
        "cpt": ["63047", "63048"],
        "typical_indications": [
            "Foraminal stenosis",
            "Radiculopathy",
        ],
        "required_documents": [
            "MRI or CT report",
            "Radicular pattern matching level",
        ],
    },
    "interspinous_spacer": {
        "description": "Interspinous Spacer",
        "region": "lumbar",
        "category": "implant",
        "cpt": ["22867", "22868", "22869"],
        "typical_indications": [
            "Lumbar spinal stenosis",
            "Neurogenic claudication",
            "Relief in flexion",
        ],
        "required_documents": [
            "Imaging-confirmed stenosis",
            "Walking intolerance and flexion-relief history",
            "Prior nonoperative management",
        ],
    },
    "sacroiliac_joint_fusion": {
        "description": "Sacroiliac Joint Fusion",
        "region": "pelvic",
        "category": "fusion",
        "cpt": ["27279"],
        "typical_indications": [
            "Confirmed SI joint pain",
            "Positive provocative tests",
            "Response to diagnostic SI injection",
        ],
        "required_documents": [
            "Exam documenting positive provocative maneuvers",
            "Imaging and exclusion of alternative causes",
            "Diagnostic injection response documentation",
            "Conservative care history",
        ],
    },
    "vertebroplasty": {
        "description": "Vertebroplasty",
        "region": "thoracolumbar",
        "category": "augmentation",
        "cpt": ["22510", "22511", "22512"],
        "typical_indications": [
            "Painful compression fracture",
            "Refractory pain",
        ],
        "required_documents": [
            "Fracture imaging",
            "Pain severity and functional decline",
            "Failure of bracing/analgesics when relevant",
        ],
    },
    "kyphoplasty": {
        "description": "Kyphoplasty",
        "region": "thoracolumbar",
        "category": "augmentation",
        "cpt": ["22513", "22514", "22515"],
        "typical_indications": [
            "Painful vertebral compression fracture",
            "Progressive collapse",
        ],
        "required_documents": [
            "Fracture imaging",
            "Pain/function documentation",
            "Osteoporosis or fracture context",
        ],
    },
    "adult_spinal_deformity_correction": {
        "description": "Adult Spinal Deformity Correction",
        "region": "spine",
        "category": "deformity",
        "cpt": ["22800", "22802", "22804"],
        "typical_indications": [
            "Sagittal or coronal deformity",
            "Fixed imbalance",
            "Functional disability",
        ],
        "required_documents": [
            "Standing full-length radiographs",
            "Spinopelvic alignment parameters",
            "Failed nonoperative management",
            "Disability assessment",
        ],
    },
    "long_segment_fusion": {
        "description": "Long Segment Fusion",
        "region": "spine",
        "category": "deformity",
        "cpt": ["22843", "22844"],
        "typical_indications": [
            "Multilevel deformity",
            "Instability",
            "Revision deformity",
        ],
        "required_documents": [
            "Standing scoliosis films",
            "Operative plan and levels",
            "Bone quality/risk assessment if available",
        ],
    },
    "pedicle_subtraction_osteotomy": {
        "description": "Pedicle Subtraction Osteotomy / Complex Osteotomy",
        "region": "spine",
        "category": "deformity",
        "cpt": ["22206", "22207", "22208"],
        "typical_indications": [
            "Fixed sagittal imbalance",
            "Rigid deformity",
        ],
        "required_documents": [
            "Standing full-length radiographs",
            "Documented fixed deformity",
            "Complex surgery rationale",
        ],
    },
    "spinal_cord_stimulator_trial": {
        "description": "Spinal Cord Stimulator Trial",
        "region": "pain",
        "category": "neuromodulation",
        "cpt": ["63650"],
        "typical_indications": [
            "Chronic neuropathic pain",
            "Failed back surgery syndrome",
            "CRPS or refractory radicular pain",
        ],
        "required_documents": [
            "Pain history",
            "Prior procedure/treatment history",
            "Psychological clearance when required",
        ],
    },
    "spinal_cord_stimulator_implant": {
        "description": "Spinal Cord Stimulator Implant",
        "region": "pain",
        "category": "neuromodulation",
        "cpt": ["63685", "63650"],
        "typical_indications": [
            "Successful SCS trial",
            "Chronic neuropathic pain",
        ],
        "required_documents": [
            "Trial success report",
            "Pain scores and functional response",
            "Psychological clearance when required",
        ],
    },
    "radiofrequency_ablation_facet": {
        "description": "Facet Radiofrequency Ablation",
        "region": "spine",
        "category": "pain",
        "cpt": ["64635", "64636", "64633", "64634"],
        "typical_indications": [
            "Facet-mediated axial pain",
            "Successful medial branch blocks",
        ],
        "required_documents": [
            "Diagnostic block response documentation",
            "Pain/function assessment",
            "Conservative treatment history",
        ],
    },
    "medial_branch_block": {
        "description": "Medial Branch Block",
        "region": "spine",
        "category": "pain",
        "cpt": ["64490", "64491", "64492", "64493", "64494", "64495"],
        "typical_indications": [
            "Facet-mediated pain suspicion",
            "Diagnostic evaluation",
        ],
        "required_documents": [
            "Pain diagram/exam",
            "Conservative treatment history",
        ],
    },
    "epidural_steroid_injection": {
        "description": "Epidural Steroid Injection",
        "region": "spine",
        "category": "pain",
        "cpt": ["62323", "64483", "64484"],
        "typical_indications": [
            "Radiculopathy",
            "Disc herniation",
            "Stenosis with nerve root irritation",
        ],
        "required_documents": [
            "Imaging report",
            "Radicular symptoms",
            "Conservative treatment history",
        ],
    },
    "mri_lumbar": {
        "description": "Lumbar MRI",
        "region": "lumbar",
        "category": "diagnostic",
        "cpt": ["72148"],
        "typical_indications": [
            "Radiculopathy",
            "Neurologic deficit",
            "Persistent low back pain with red flags",
        ],
        "required_documents": [
            "Office note",
            "Neuro/radicular symptom documentation",
            "Conservative treatment history when applicable",
        ],
    },
    "mri_cervical": {
        "description": "Cervical MRI",
        "region": "cervical",
        "category": "diagnostic",
        "cpt": ["72141"],
        "typical_indications": [
            "Radiculopathy",
            "Myelopathy",
            "Weakness or numbness",
        ],
        "required_documents": [
            "Office note",
            "Neurologic findings",
            "Conservative treatment history when applicable",
        ],
    },
    "physical_therapy": {
        "description": "Physical Therapy",
        "region": "rehab",
        "category": "therapy",
        "cpt": ["97110", "97112", "97530"],
        "typical_indications": [
            "Back pain",
            "Postoperative rehabilitation",
            "Functional limitation",
        ],
        "required_documents": [
            "Functional deficits",
            "Therapy goals",
            "Plan of care",
        ],
    },
}

PROCEDURE_ALIASES = {
    "mri": "mri_lumbar",
    "lumbar mri": "mri_lumbar",
    "cervical mri": "mri_cervical",
    "esi": "epidural_steroid_injection",
    "epidural steroid injection": "epidural_steroid_injection",
    "fusion": "lumbar_tlif",
    "lumbar fusion": "lumbar_tlif",
    "pt": "physical_therapy",
    "physical therapy": "physical_therapy",
}


def canonical_procedure_key(value: str) -> str:
    key = (value or "").strip().lower().replace(" ", "_")
    return PROCEDURE_ALIASES.get(key, key)


def get_procedure(value: str) -> dict:
    key = canonical_procedure_key(value)
    return PROCEDURES.get(key, {})
