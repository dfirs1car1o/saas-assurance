"""gen_assessment_results.py — Generate an OSCAL Assessment Results document.

Wraps gap_analysis.json findings in the OSCAL 1.1.2 assessment-results model,
producing machine-readable observations and findings linked to the resolved profile.

Usage:
    python3 scripts/gen_assessment_results.py \
        --gap-analysis docs/.../gap_analysis.json \
        --backlog      docs/.../backlog.json \
        --org          my-org \
        --platform     salesforce \
        --out          docs/.../assessment_results.json \
        [--resolved-catalog config/salesforce/sbs_resolved_catalog.json]

Output: OSCAL 1.1.2 assessment-results JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _safe_write_path(p: Path) -> Path:
    """Resolve *p* and assert it stays within the repo tree."""
    resolved = p.resolve()
    if not resolved.is_relative_to(_REPO):
        raise ValueError(f"Output path '{resolved}' escapes the repository root.")
    return resolved


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _severity_to_risk_level(severity: str) -> str:
    return {
        "critical": "very-high",
        "high": "high",
        "moderate": "moderate",
        "low": "low",
        "informational": "low",
    }.get(severity.lower(), "moderate")


def _map_status(status: str) -> str:
    return {
        "pass": "satisfied",
        "fail": "not-satisfied",
        "partial": "not-satisfied",
        "not_applicable": "not-applicable",
    }.get(status.lower(), "not-satisfied")


def _build_observation(finding: dict, org: str, platform: str, assessment_id: str) -> dict:
    control_id = finding.get("control_id", "")
    status = finding.get("status", "fail")
    return {
        "uuid": _uuid(),
        "title": f"Control assessment: {control_id}",
        "description": (
            f"Automated assessment of control {control_id} for {platform} org {org}. "
            f"Status: {status.upper()}. "
            f"Evidence: {finding.get('evidence_ref', 'N/A')}."
        ),
        "methods": ["AUTOMATED"],
        "types": ["finding"],
        "subjects": [
            {
                "subject-uuid": _uuid(),
                "type": "component",
                "title": f"{platform.capitalize()} — {org}",
                "props": [
                    {"name": "platform", "value": platform},
                    {"name": "org", "value": org},
                ],
            }
        ],
        "relevant-evidence": [
            {
                "description": finding.get("evidence_ref", ""),
                "props": [
                    {"name": "assessment-id", "value": assessment_id},
                    {"name": "collection-method", "value": "automated-api"},
                    {"name": "observed-value", "value": str(finding.get("observed_value", ""))},
                ],
            }
        ],
        "collected": _now_iso(),
    }


def _build_finding(finding: dict, obs_uuid: str, control_id: str) -> dict:
    status = finding.get("status", "fail")
    severity = finding.get("severity", "moderate")
    return {
        "uuid": _uuid(),
        "title": f"Finding: {control_id}",
        "description": (
            f"Control {control_id} assessment result: {status.upper()}. "
            f"Severity: {severity}. "
            f"Remediation: {finding.get('remediation', '')}"
        ),
        "target": {
            "type": "statement-id",
            "target-id": f"{control_id.lower()}_smt",
            "title": control_id,
            "status": {
                "state": _map_status(status),
                "reason": status,
            },
        },
        "implementation-statement-uuid": _uuid(),
        "related-observations": [{"observation-uuid": obs_uuid}],
        "props": [
            {"name": "control-id", "value": control_id},
            {"name": "assessment-status", "value": status},
            {"name": "severity", "value": severity},
            {"name": "risk-level", "value": _severity_to_risk_level(severity)},
        ],
        "remarks": finding.get("remediation", ""),
    }


def build_assessment_results(
    gap_analysis: dict,
    backlog: dict,
    org: str,
    platform: str,
    resolved_catalog_path: str | None = None,
) -> dict:
    assessment_id = gap_analysis.get("assessment_id") or backlog.get("assessment_id", "unknown")
    generated_at = gap_analysis.get("generated_at_utc", _now_iso())

    observations: list[dict] = []
    findings: list[dict] = []

    # Process gap analysis findings
    for finding in gap_analysis.get("findings", []):
        control_id = finding.get("control_id", "")
        obs = _build_observation(finding, org, platform, assessment_id)
        finding_obj = _build_finding(finding, obs["uuid"], control_id)
        observations.append(obs)
        findings.append(finding_obj)

    # Summary stats
    status_counts: dict[str, int] = {}
    for f in gap_analysis.get("findings", []):
        s = f.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    # Resolved catalog reference
    catalog_href = resolved_catalog_path or f"config/{platform}/sbs_resolved_catalog.json"

    return {
        "assessment-results": {
            "uuid": _uuid(),
            "metadata": {
                "title": f"SSCF Assessment Results — {platform.capitalize()} — {org}",
                "last-modified": _now_iso(),
                "version": "1.0.0",
                "oscal-version": "1.1.2",
                "props": [
                    {"name": "assessment-id", "value": assessment_id},
                    {"name": "platform", "value": platform},
                    {"name": "org", "value": org},
                    {"name": "generated-at", "value": generated_at},
                    {"name": "findings-total", "value": str(len(findings))},
                    {"name": "pass-count", "value": str(status_counts.get("pass", 0))},
                    {"name": "fail-count", "value": str(status_counts.get("fail", 0))},
                    {"name": "partial-count", "value": str(status_counts.get("partial", 0))},
                    {"name": "not-applicable-count", "value": str(status_counts.get("not_applicable", 0))},
                ],
                "remarks": (
                    f"OSCAL Assessment Results for {platform} org {org}. "
                    f"Assessment ID: {assessment_id}. "
                    f"Findings: {len(findings)} total, "
                    f"{status_counts.get('fail', 0)} fail, "
                    f"{status_counts.get('partial', 0)} partial, "
                    f"{status_counts.get('pass', 0)} pass."
                ),
            },
            "import-ap": {
                "href": f"assessment_plan-{platform}-{org}.json",
                "remarks": "Assessment plan not yet generated. See Pipeline-Walkthrough.md.",
            },
            "local-definitions": {
                "activities": [
                    {
                        "uuid": _uuid(),
                        "title": "SSCF Automated Collection and Assessment",
                        "description": (
                            "Automated collection of platform configuration via REST/Tooling API "
                            "followed by rule-based OSCAL gap assessment against the SSCF baseline."
                        ),
                        "props": [
                            {"name": "method", "value": "automated-api"},
                            {"name": "platform", "value": platform},
                        ],
                        "steps": [
                            {
                                "uuid": _uuid(),
                                "title": "Platform Configuration Collection",
                                "description": f"Collect security configuration from {platform} via API.",
                            },
                            {
                                "uuid": _uuid(),
                                "title": "OSCAL Gap Assessment",
                                "description": "Evaluate collected config against SSCF control rules.",
                            },
                        ],
                    }
                ]
            },
            "results": [
                {
                    "uuid": _uuid(),
                    "title": f"Assessment Run — {assessment_id}",
                    "description": (f"Results for SSCF assessment run {assessment_id} against {platform} org {org}."),
                    "start": generated_at,
                    "end": _now_iso(),
                    "props": [
                        {"name": "assessment-id", "value": assessment_id},
                        {"name": "catalog-ref", "value": catalog_href},
                    ],
                    "reviewed-controls": {
                        "control-selections": [
                            {
                                "description": (f"All controls selected from resolved {platform.upper()} profile."),
                                "include-all": {},
                            }
                        ]
                    },
                    "observations": observations,
                    "findings": findings,
                    "remarks": f"Generated by scripts/gen_assessment_results.py from {assessment_id}.",
                }
            ],
        }
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate OSCAL Assessment Results from SSCF gap analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--gap-analysis", required=True, help="Path to gap_analysis.json")
    p.add_argument("--backlog", required=False, default=None, help="Path to backlog.json (optional metadata)")
    p.add_argument("--org", required=True, help="Org alias")
    p.add_argument(
        "--platform",
        default="salesforce",
        choices=["salesforce", "workday"],
        help="Platform (default: salesforce)",
    )
    p.add_argument("--out", required=True, help="Output path for OSCAL assessment-results JSON")
    p.add_argument(
        "--resolved-catalog",
        default=None,
        help="Path to resolved catalog JSON (optional reference link)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    ga_path = Path(args.gap_analysis)
    if not ga_path.exists():
        print(f"ERROR: gap-analysis not found: {ga_path}", file=sys.stderr)
        sys.exit(1)

    gap_analysis = json.loads(ga_path.read_text())

    backlog: dict = {}
    if args.backlog:
        bp = Path(args.backlog)
        if bp.exists():
            backlog = json.loads(bp.read_text())

    results = build_assessment_results(
        gap_analysis=gap_analysis,
        backlog=backlog,
        org=args.org,
        platform=args.platform,
        resolved_catalog_path=args.resolved_catalog,
    )

    out_path = _safe_write_path(Path(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))

    root = results["assessment-results"]
    result = root["results"][0]
    print(f"Assessment results written to {out_path}")
    print(f"  Observations: {len(result['observations'])}")
    print(f"  Findings    : {len(result['findings'])}")
    props = {p["name"]: p["value"] for p in root["metadata"]["props"]}
    print(f"  Pass        : {props.get('pass-count', 0)}")
    print(f"  Fail        : {props.get('fail-count', 0)}")
    print(f"  Partial     : {props.get('partial-count', 0)}")


if __name__ == "__main__":
    main()
