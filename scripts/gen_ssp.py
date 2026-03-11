"""gen_ssp.py — Generate a commercial SaaS OSCAL System Security Plan per org.

Reads the SSP template + assessment results and produces a fully populated
OSCAL 1.1.2 SSP for the assessed org. Generates a new SSP every run (keeps
it in sync with the latest assessment state).

Design decisions (from 2026-03-10 session):
  - SSP generated every run — stays in sync with assessment results
  - Sensitivity tier: RED=high, AMBER=moderate, GREEN=low
  - No FedRAMP red tape: no JAB/PMO, no FIPS 199 government data categories,
    no physical media controls — commercial SaaS focus only

Usage:
    python3 scripts/gen_ssp.py \
        --sscf-report docs/.../sscf_report.json \
        --backlog     docs/.../backlog.json \
        --nist-review docs/.../nist_review.json \
        --org         my-org \
        --platform    salesforce \
        --out         docs/.../ssp.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path("config/ssp/commercial_saas_ssp_template.json")

PLATFORM_VENDORS: dict[str, str] = {
    "salesforce": "Salesforce, Inc.",
    "workday": "Workday, Inc.",
}

PLATFORM_PROFILE_HREFS: dict[str, str] = {
    "salesforce": "../../config/salesforce/sbs_v1_profile.json",
    "workday": "../../config/workday/wscc_v1_profile.json",
}

PLATFORM_RESOLVED_CAT: dict[str, str] = {
    "salesforce": "../../config/salesforce/sbs_resolved_catalog.json",
    "workday": "../../config/workday/wscc_resolved_catalog.json",
}

PLATFORM_COMPONENT_DEFS: dict[str, str] = {
    "salesforce": "../../config/component-definitions/salesforce_component.json",
    "workday": "../../config/component-definitions/workday_component.json",
}


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _score_to_sensitivity(score: float, status: str) -> str:
    """Map SSCF score/status to SSP sensitivity tier."""
    s = status.upper()
    if s == "RED" or score < 0.40:
        return "high"
    if s == "AMBER" or score < 0.80:
        return "moderate"
    return "low"


def _fill_placeholders(obj: object, replacements: dict[str, str]) -> Any:
    """Recursively replace placeholder strings in nested JSON structure."""
    if isinstance(obj, str):
        for placeholder, value in replacements.items():
            obj = obj.replace(placeholder, value)
        return obj
    if isinstance(obj, dict):
        return {k: _fill_placeholders(v, replacements) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill_placeholders(item, replacements) for item in obj]
    return obj


def _build_implemented_requirements(backlog: dict, platform: str) -> list[dict]:
    """Build control-implementation implemented-requirements from backlog findings."""
    reqs = []
    for item in backlog.get("mapped_items", []):
        control_id = item.get("sbs_control_id") or item.get("legacy_control_id") or item.get("control_id", "")
        # Map SBS/WD control IDs back to SSCF control IDs via sscf_mappings
        sscf_id = control_id
        sscf_mappings = item.get("sscf_mappings", [])
        if sscf_mappings:
            sscf_id = sscf_mappings[0].get("sscf_control_id", control_id).lower().replace("sscf-", "sscf-")

        status = item.get("status", "fail")
        impl_status = {
            "pass": "implemented",
            "fail": "not-implemented",
            "partial": "partially-implemented",
            "not_applicable": "not-applicable",
        }.get(status, "not-implemented")

        reqs.append(
            {
                "uuid": _uuid(),
                "control-id": sscf_id,
                "description": (
                    f"Implementation of {control_id} for {platform} deployment. "
                    f"Status: {status.upper()}. "
                    f"Remediation: {item.get('remediation', '')}"
                ),
                "props": [
                    {"name": "platform-control-id", "value": control_id},
                    {"name": "implementation-status", "value": impl_status},
                    {"name": "severity", "value": item.get("severity", "moderate")},
                    {"name": "owner", "value": item.get("owner", "Security Team")},
                ],
                "statements": [
                    {
                        "statement-id": f"{sscf_id}_smt",
                        "uuid": _uuid(),
                        "description": item.get("remediation", ""),
                        "by-components": [
                            {
                                "component-uuid": "COMPONENT_UUID_PLACEHOLDER",
                                "uuid": _uuid(),
                                "description": (
                                    f"Assessment evidence: {item.get('evidence_ref', 'N/A')}. "
                                    f"Current status: {status.upper()}."
                                ),
                                "implementation-status": {
                                    "state": impl_status,
                                },
                            }
                        ],
                    }
                ],
            }
        )
    return reqs


def build_ssp(
    sscf_report: dict,
    backlog: dict,
    nist_review: dict,
    org: str,
    platform: str,
) -> dict:
    assessment_id = backlog.get("assessment_id", "unknown")
    overall_score = sscf_report.get("overall_score", 0.0)
    overall_status = sscf_report.get("overall_status", "red")
    sensitivity = _score_to_sensitivity(overall_score, overall_status)
    nist_verdict = nist_review.get("overall_verdict", "flag")

    # Load and deep-copy template
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"SSP template not found: {TEMPLATE_PATH}")
    template = copy.deepcopy(json.loads(TEMPLATE_PATH.read_text()))

    # Remove template instructions meta-key
    template.pop("_template_instructions", None)

    # Build placeholder replacements
    replacements = {
        "SSP_UUID_PLACEHOLDER": _uuid(),
        "ORG_ALIAS_PLACEHOLDER": org,
        "PLATFORM_PLACEHOLDER": platform.capitalize(),
        "LAST_MODIFIED_PLACEHOLDER": _now_iso(),
        "SENSITIVITY_TIER_PLACEHOLDER": sensitivity,
        "OVERALL_SCORE_PLACEHOLDER": f"{overall_score:.1%}",
        "OVERALL_STATUS_PLACEHOLDER": overall_status.upper(),
        "ASSESSMENT_ID_PLACEHOLDER": assessment_id,
        "NIST_VERDICT_PLACEHOLDER": nist_verdict,
        "SYSTEM_ID_PLACEHOLDER": f"{platform}-{org}",
        "OWNER_UUID_PLACEHOLDER": _uuid(),
        "COMPONENT_UUID_PLACEHOLDER": _uuid(),
        "IDP_UUID_PLACEHOLDER": _uuid(),
        "USER_UUID_1_PLACEHOLDER": _uuid(),
        "USER_UUID_2_PLACEHOLDER": _uuid(),
        "USER_UUID_3_PLACEHOLDER": _uuid(),
        "INFO_UUID_PLACEHOLDER": _uuid(),
        "VENDOR_PLACEHOLDER": PLATFORM_VENDORS.get(platform, platform),
        "PROFILE_HREF_PLACEHOLDER": PLATFORM_PROFILE_HREFS.get(platform, ""),
        "COMPONENT_DEF_HREF_PLACEHOLDER": PLATFORM_COMPONENT_DEFS.get(platform, ""),
        "RESOLVED_CAT_HREF_PLACEHOLDER": PLATFORM_RESOLVED_CAT.get(platform, ""),
        "RESOLVED_CAT_UUID_PLACEHOLDER": _uuid(),
        "COMPONENT_DEF_RESOURCE_UUID_PLACEHOLDER": _uuid(),
    }

    filled = _fill_placeholders(template, replacements)

    # Replace the implemented-requirements placeholder with actual data
    impl_reqs = _build_implemented_requirements(backlog, platform)
    ssp_root = filled["system-security-plan"]
    ssp_root["control-implementation"]["implemented-requirements"] = impl_reqs

    return filled


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a commercial SaaS OSCAL SSP from assessment outputs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--sscf-report", required=True, help="Path to sscf_report.json")
    p.add_argument("--backlog", required=True, help="Path to backlog.json")
    p.add_argument("--nist-review", required=True, help="Path to nist_review.json")
    p.add_argument("--org", required=True, help="Org alias")
    p.add_argument(
        "--platform",
        default="salesforce",
        choices=["salesforce", "workday"],
        help="Platform (default: salesforce)",
    )
    p.add_argument("--out", required=True, help="Output path for OSCAL SSP JSON")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    for label, path_str in [
        ("sscf-report", args.sscf_report),
        ("backlog", args.backlog),
        ("nist-review", args.nist_review),
    ]:
        if not Path(path_str).exists():
            print(f"ERROR: {label} not found: {path_str}", file=sys.stderr)
            sys.exit(1)

    sscf_report = json.loads(Path(args.sscf_report).read_text())
    backlog = json.loads(Path(args.backlog).read_text())
    nist_review = json.loads(Path(args.nist_review).read_text())

    ssp = build_ssp(
        sscf_report=sscf_report,
        backlog=backlog,
        nist_review=nist_review,
        org=args.org,
        platform=args.platform,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ssp, indent=2))

    root = ssp["system-security-plan"]
    props = {p["name"]: p["value"] for p in root["system-characteristics"].get("props", [])}
    impl_count = len(root["control-implementation"]["implemented-requirements"])

    print(f"SSP written to {out_path}")
    print(f"  Org               : {args.org}")
    print(f"  Platform          : {args.platform}")
    print(f"  Sensitivity tier  : {props.get('sensitivity-tier', '?')}")
    print(f"  Overall score     : {props.get('overall-score', '?')} ({props.get('overall-status', '?')})")
    print(f"  NIST AI RMF       : {props.get('nist-ai-rmf-verdict', '?')}")
    print(f"  Implemented reqs  : {impl_count}")


if __name__ == "__main__":
    main()
