from __future__ import annotations

PAYER_PORTALS = {
    "united_healthcare": {
        "label": "UnitedHealthcare",
        "portal_name": "UnitedHealthcare Provider Portal",
        "portal_url": "https://www.uhcprovider.com/en/prior-auth-advance-notification.html",
        "support_url": "https://www.uhcprovider.com/en/access.html",
        "how_to_submit": [
            "Verify whether prior authorization is required in the Prior Authorization and Notification tool.",
            "Submit the request online through the UnitedHealthcare Provider Portal.",
            "Upload clinical records, imaging reports, and any requested supporting documentation.",
            "Track status and upload updates in the same portal.",
        ],
        "documents_required": [
            "Office note with diagnosis and symptom history",
            "Neurologic exam",
            "Imaging report",
            "Conservative treatment documentation",
            "Procedure/CPT and ICD-10 details",
        ],
        "notes": "Use member-specific lookup first because requirements can vary by plan and site of service.",
    },
    "aetna": {
        "label": "Aetna",
        "portal_name": "Availity Provider Portal for Aetna",
        "portal_url": "https://www.aetna.com/health-care-professionals/availity.html",
        "support_url": "https://www.aetna.com/health-care-professionals.html",
        "how_to_submit": [
            "Log in to Availity and open the authorization/referral workflow for Aetna.",
            "Submit the request and attach office notes, imaging, and conservative care records.",
            "Use payer-specific forms from Aetna when the service requires a form in addition to the portal request.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Therapy/medication history",
            "Procedure details and levels",
        ],
        "notes": "Availity is Aetna's main provider portal for authorizations and referrals.",
    },
    "cigna": {
        "label": "Cigna Healthcare",
        "portal_name": "CignaforHCP / Cigna precertification",
        "portal_url": "https://www.cigna.com/health-care-providers/coverage-and-claims/precertification",
        "support_url": "https://cignaforhcp.cigna.com/",
        "how_to_submit": [
            "Confirm whether the requested service requires precertification.",
            "Use the Cigna provider portal or designated utilization management workflow for the service line.",
            "Attach clinical documentation supporting medical necessity and prior treatment failure.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Medication and PT history",
            "Procedure/CPT details",
        ],
        "notes": "Some Cigna services are delegated to ancillary utilization partners; verify the correct pathway in the portal.",
    },
    "anthem_bcbs": {
        "label": "Anthem / BCBS",
        "portal_name": "Availity Essentials / Anthem authorizations",
        "portal_url": "https://www.anthem.com/provider/individual-commercial/prior-authorization",
        "support_url": "https://www.anthem.com/provider/individual-commercial/availity",
        "how_to_submit": [
            "Log in to Availity Essentials and open the authorizations/referrals workflow for the member's plan.",
            "Upload clinical records and imaging within the authorization request.",
            "Use the payer-specific lookup tool in Availity when available.",
        ],
        "documents_required": [
            "Office note",
            "Imaging",
            "Conservative treatment documentation",
            "Functional assessment / ODI when relevant",
        ],
        "notes": "BCBS requirements vary by local plan; always confirm the member's specific Blue plan before submission.",
    },
    "humana": {
        "label": "Humana",
        "portal_name": "Humana Provider / Availity",
        "portal_url": "https://provider.humana.com/coverage-claims/prior-authorizations",
        "support_url": "https://provider.humana.com/coverage-claims/prior-authorizations/prior-authorizations-search-tool",
        "how_to_submit": [
            "Use Humana's prior authorization search tool to verify requirements and pathway.",
            "Submit most medical prior authorizations through Availity when directed by Humana.",
            "Attach all supporting records at the time of submission whenever possible.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging",
            "Conservative treatment records",
            "Procedure and diagnosis details",
        ],
        "notes": "Humana routes many requests through Availity, but some services use partner-specific workflows.",
    },
    "medicare": {
        "label": "Medicare",
        "portal_name": "CMS / MAC workflow",
        "portal_url": "https://www.cms.gov/data-research/monitoring-programs/medicare-fee-service-compliance-programs/prior-authorization-and-pre-claim-review-initiatives",
        "support_url": "https://www.cms.gov/priorities/burden-reduction/overview/interoperability/frequently-asked-questions/prior-authorization-api",
        "how_to_submit": [
            "Confirm that the requested service is one of the Medicare services subject to prior authorization or pre-claim review.",
            "Submit the request with supporting documentation to the appropriate Medicare Administrative Contractor (MAC) when applicable.",
            "Retain the same clinical documentation required to support payment and submit it earlier in the process.",
        ],
        "documents_required": [
            "Ordering note with medical necessity",
            "Imaging / test reports when applicable",
            "Procedure and diagnosis coding",
            "Any documentation specified by the MAC workflow",
        ],
        "notes": "Traditional Medicare does not require prior authorization for all spine procedures; requirements are service- and setting-specific.",
    },
    "generic": {
        "label": "Other / Unknown Payer",
        "portal_name": "Use payer provider portal",
        "portal_url": "",
        "support_url": "",
        "how_to_submit": [
            "Check the member-specific provider portal or utilization management contact.",
            "Verify whether prior authorization is required before scheduling.",
            "Upload the full packet at first submission to reduce avoidable delays.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Conservative treatment history",
            "Procedure/CPT and ICD-10 details",
        ],
        "notes": "When the payer is not mapped, confirm the exact submission workflow manually.",
    },
}

PAYER_ALIASES = {
    "uhc": "united_healthcare",
    "united healthcare": "united_healthcare",
    "unitedhealthcare": "united_healthcare",
    "united_healthcare": "united_healthcare",
    "aetna": "aetna",
    "cigna": "cigna",
    "bcbs": "anthem_bcbs",
    "blue cross": "anthem_bcbs",
    "blue cross blue shield": "anthem_bcbs",
    "anthem": "anthem_bcbs",
    "anthem bcbs": "anthem_bcbs",
    "humana": "humana",
    "medicare": "medicare",
}


def canonical_payer_key(value: str) -> str:
    key = (value or "").strip().lower().replace("-", " ")
    key = " ".join(key.split())
    return PAYER_ALIASES.get(key, "generic")


def get_payer_portal(value: str) -> dict:
    return PAYER_PORTALS.get(canonical_payer_key(value), PAYER_PORTALS["generic"])
