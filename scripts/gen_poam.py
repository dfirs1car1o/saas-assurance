"""gen_poam.py — Generate (or update) an OSCAL POA&M from assessment backlog.

Usage:
    python3 scripts/gen_poam.py \
        --backlog  docs/.../backlog.json \
        --gap-analysis docs/.../gap_analysis.json \
        --org my-org \
        --platform salesforce \
        --out docs/.../poam.json \
        [--existing docs/.../poam.json]   # persistent cumulative mode

Persistent cumulative mode:
    If --existing is supplied (or if --out already exists), the script merges:
      - NEW findings:    adds observation + risk + poam-item (status=open)
      - CHANGED findings: updates risk status, appends a new remediation timeline entry
      - RESOLVED findings: sets risk status=closed, poam-item reflects completion
      - PASSED findings:  skipped (only fail/partial create poam-items)
      - NOT_APPLICABLE:   skipped

OSCAL version: 1.1.2
Output schema: https://pages.nist.gov/OSCAL/reference/1.1.2/plan-of-action-and-milestones/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# ── helpers ───────────────────────────────────────────────────────────────────


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
    """Map SSCF severity labels to OSCAL risk-level values."""
    return {
        "critical": "very-high",
        "high": "high",
        "moderate": "moderate",
        "low": "low",
        "informational": "low",
    }.get(severity.lower(), "moderate")


def _status_to_risk_status(status: str) -> str:
    return {
        "fail": "open",
        "partial": "open",
        "pass": "closed",
        "not_applicable": "closed",
    }.get(status.lower(), "open")


def _control_key(item: dict) -> str:
    """Stable key for matching findings across runs."""
    return item.get("sbs_control_id") or item.get("legacy_control_id") or item.get("control_id", "")


def _poam_id(n: int) -> str:
    return f"POAM-{n:04d}"


# ── OSCAL builders ────────────────────────────────────────────────────────────


def _build_observation(item: dict, org: str, platform: str, assessment_id: str) -> dict:
    control_id = _control_key(item)
    return {
        "uuid": _uuid(),
        "title": f"Assessment observation: {control_id}",
        "description": (
            f"Automated assessment finding for control {control_id} — "
            f"{item.get('sbs_title', '')}. "
            f"Status: {item.get('status', '').upper()}. "
            f"Evidence reference: {item.get('evidence_ref', 'N/A')}."
        ),
        "methods": ["AUTOMATED"],
        "types": ["finding"],
        "subjects": [
            {
                "subject-uuid": _uuid(),
                "type": "component",
                "title": f"{platform.capitalize()} Platform — {org}",
                "props": [
                    {"name": "platform", "value": platform},
                    {"name": "org", "value": org},
                ],
            }
        ],
        "relevant-evidence": [
            {
                "description": item.get("evidence_ref", ""),
                "props": [
                    {"name": "method", "value": "automated-api"},
                    {"name": "assessment-id", "value": assessment_id},
                ],
            }
        ],
        "collected": _now_iso(),
        "remarks": f"Collected by sscf-assessment pipeline run {assessment_id}.",
    }


def _build_risk(item: dict, obs_uuid: str) -> dict:
    control_id = _control_key(item)
    severity = item.get("severity", "moderate")
    status = item.get("status", "fail")
    due_date = item.get("due_date", "")
    remediation_text = item.get("remediation", "Remediation steps not specified.")

    # Build deadline from due_date string (YYYY-MM-DD → ISO8601 with time)
    deadline = f"{due_date}T23:59:59Z" if due_date else _now_iso()

    risk = {
        "uuid": _uuid(),
        "title": f"Risk: {control_id} — {item.get('sbs_title', '')}",
        "description": (
            f"Control {control_id} is in status '{status}'. "
            f"Severity: {severity}. "
            f"This risk represents a gap against the SSCF baseline."
        ),
        "statement": (
            f"The organization has not fully implemented {control_id}. "
            f"Current status: {status}. "
            f"Recommended action: {remediation_text}"
        ),
        "props": [
            {"name": "risk-level", "value": _severity_to_risk_level(severity)},
            {"name": "sscf-severity", "value": severity},
            {"name": "control-id", "value": control_id},
        ],
        "status": _status_to_risk_status(status),
        "origins": [
            {
                "actors": [
                    {
                        "type": "tool",
                        "actor-uuid": _uuid(),
                        "title": "sscf-assessment-pipeline",
                    }
                ]
            }
        ],
        "deadline": deadline,
        "remediations": [
            {
                "uuid": _uuid(),
                "lifecycle": "recommendation",
                "title": f"Remediation plan for {control_id}",
                "description": remediation_text,
                "tasks": [
                    {
                        "uuid": _uuid(),
                        "type": "milestone",
                        "title": "Complete remediation",
                        "description": f"Implement remediation for {control_id}.",
                        "timing": {
                            "within-date-range": {
                                "start": _now_iso(),
                                "end": deadline,
                            }
                        },
                    }
                ],
            }
        ],
        "related-observations": [{"observation-uuid": obs_uuid}],
    }

    # Add SSCF domain cross-reference
    sscf_mappings = item.get("sscf_mappings", [])
    if sscf_mappings:
        risk["props"].append(
            {
                "name": "sscf-domain",
                "value": sscf_mappings[0].get("sscf_control_id", ""),
            }
        )

    return risk


def _build_poam_item(
    item: dict,
    obs_uuid: str,
    risk_uuid: str,
    poam_number: int,
    platform: str,
    org: str,
) -> dict:
    control_id = _control_key(item)
    severity = item.get("severity", "moderate")
    status = item.get("status", "fail")
    owner = item.get("owner", "Security Team")
    due_date = item.get("due_date", "")

    # Map assessment status → POAM lifecycle state
    lifecycle_state = {
        "fail": "open",
        "partial": "open",
    }.get(status.lower(), "open")

    props = [
        {"name": "control-id", "value": control_id},
        {"name": "sscf-severity", "value": severity},
        {"name": "platform", "value": platform},
        {"name": "org", "value": org},
        {"name": "poam-id", "value": _poam_id(poam_number)},
        {"name": "owner", "value": owner},
        {"name": "assessment-status", "value": status},
        {"name": "lifecycle-state", "value": lifecycle_state},
    ]
    if due_date:
        props.append({"name": "due-date", "value": due_date})

    iso27001_controls = item.get("iso27001_controls", [])
    if iso27001_controls:
        # iso27001_controls is a list of dicts with "id" keys
        ids = [c["id"] if isinstance(c, dict) else str(c) for c in iso27001_controls]
        props.append({"name": "iso27001-controls", "value": ", ".join(ids)})

    return {
        "uuid": _uuid(),
        "title": f"{_poam_id(poam_number)}: {control_id} — {item.get('sbs_title', '')}",
        "description": (
            f"POA&M item for control {control_id}. "
            f"Platform: {platform.capitalize()} ({org}). "
            f"Assessment status: {status}. Severity: {severity}. "
            f"Owner: {owner}."
        ),
        "props": props,
        "origins": [
            {
                "actors": [
                    {
                        "type": "tool",
                        "actor-uuid": _uuid(),
                        "title": "sscf-assessment-pipeline",
                    }
                ]
            }
        ],
        "related-observations": [{"observation-uuid": obs_uuid}],
        "related-risks": [{"risk-uuid": risk_uuid}],
    }


# ── merge helpers ─────────────────────────────────────────────────────────────


def _extract_existing_index(existing: dict) -> dict[str, dict]:
    """Build a lookup {control_id: poam_item_index} from an existing POA&M."""
    index: dict[str, dict] = {}
    poam_root = existing.get("plan-of-action-and-milestones", {})
    for item in poam_root.get("poam-items", []):
        for prop in item.get("props", []):
            if prop.get("name") == "control-id":
                index[prop["value"]] = item
                break
    return index


def _find_obs_uuid(existing: dict, control_id: str) -> str | None:
    poam_root = existing.get("plan-of-action-and-milestones", {})
    for item in poam_root.get("poam-items", []):
        cid = next(
            (p["value"] for p in item.get("props", []) if p["name"] == "control-id"),
            None,
        )
        if cid == control_id:
            obs_links = item.get("related-observations", [])
            if obs_links:
                return obs_links[0].get("observation-uuid")
    return None


def _find_risk_uuid(existing: dict, control_id: str) -> str | None:
    poam_root = existing.get("plan-of-action-and-milestones", {})
    for item in poam_root.get("poam-items", []):
        cid = next(
            (p["value"] for p in item.get("props", []) if p["name"] == "control-id"),
            None,
        )
        if cid == control_id:
            risk_links = item.get("related-risks", [])
            if risk_links:
                return risk_links[0].get("risk-uuid")
    return None


def _update_risk_status(risks: list[dict], risk_uuid: str, new_status: str) -> None:
    for risk in risks:
        if risk.get("uuid") == risk_uuid:
            risk["status"] = new_status
            return


def _update_poam_item_props(item: dict, new_status: str) -> None:
    for prop in item.get("props", []):
        if prop["name"] == "assessment-status":
            prop["value"] = new_status
        if prop["name"] == "lifecycle-state":
            prop["value"] = "closed" if new_status in ("pass", "not_applicable") else "open"


# ── main build ────────────────────────────────────────────────────────────────


def _init_poam_state(
    existing: dict | None,
) -> tuple[list[dict], list[dict], list[dict], dict, int, dict]:
    """Return (observations, risks, poam_items, existing_index, next_number, poam_root)."""
    if not existing:
        return [], [], [], {}, 1, {}
    poam_root = existing.get("plan-of-action-and-milestones", {})
    observations: list[dict] = poam_root.get("observations", [])
    risks: list[dict] = poam_root.get("risks", [])
    poam_items: list[dict] = poam_root.get("poam-items", [])
    existing_index = _extract_existing_index(existing)
    existing_numbers: list[int] = []
    for pi in poam_items:
        for prop in pi.get("props", []):
            if prop.get("name") == "poam-id":
                m = re.match(r"POAM-(\d+)", prop["value"])
                if m:
                    existing_numbers.append(int(m.group(1)))
    return observations, risks, poam_items, existing_index, max(existing_numbers, default=0) + 1, poam_root


def _apply_finding_to_existing(
    finding: dict,
    existing: dict,
    existing_index: dict,
    observations: list[dict],
    risks: list[dict],
    org: str,
    platform: str,
    assessment_id: str,
) -> None:
    """Update an existing poam-item, risk, and observations list in-place."""
    control_id = _control_key(finding)
    status = finding.get("status", "fail")
    obs_uuid = _find_obs_uuid(existing, control_id)
    risk_uuid = _find_risk_uuid(existing, control_id)

    new_obs = _build_observation(finding, org, platform, assessment_id)
    if obs_uuid:
        new_obs["uuid"] = _uuid()
    observations.append(new_obs)

    if risk_uuid:
        _update_risk_status(risks, risk_uuid, _status_to_risk_status(status))

    existing_pi = existing_index[control_id]
    _update_poam_item_props(existing_pi, status)
    existing_pi.setdefault("related-observations", []).append({"observation-uuid": new_obs["uuid"]})


def _apply_finding_as_new(
    finding: dict,
    observations: list[dict],
    risks: list[dict],
    poam_items: list[dict],
    next_poam_number: int,
    org: str,
    platform: str,
    assessment_id: str,
) -> int:
    """Create a new observation+risk+poam-item. Returns updated next_poam_number."""
    if finding.get("status", "fail") == "pass":
        return next_poam_number
    obs = _build_observation(finding, org, platform, assessment_id)
    risk = _build_risk(finding, obs["uuid"])
    poam_item = _build_poam_item(finding, obs["uuid"], risk["uuid"], next_poam_number, platform, org)
    observations.append(obs)
    risks.append(risk)
    poam_items.append(poam_item)
    return next_poam_number + 1


def _compute_sensitivity(backlog: dict) -> tuple[str, int, int, int]:
    """Return (sensitivity, open_count, fail_count, partial_count)."""
    status_counts = backlog.get("summary", {}).get("status_counts", {})
    fail_count = status_counts.get("fail", 0)
    partial_count = status_counts.get("partial", 0)
    open_count = fail_count + partial_count
    if open_count >= 10:
        sensitivity = "high"
    elif open_count >= 5:
        sensitivity = "moderate"
    else:
        sensitivity = "low"
    return sensitivity, open_count, fail_count, partial_count


def _bump_version(existing: dict | None, poam_root: dict) -> str:
    """Return version string, bumping patch number when updating existing POA&M."""
    version_str = poam_root.get("metadata", {}).get("version", "1.0.0") if existing else "1.0.0"
    parts = version_str.split(".")
    if len(parts) == 3 and existing:
        try:
            parts[2] = str(int(parts[2]) + 1)
        except ValueError:
            pass
    return ".".join(parts)


def build_poam(
    backlog: dict,
    org: str,
    platform: str,
    existing: dict | None = None,
) -> dict:
    assessment_id = backlog.get("assessment_id", "unknown")
    now = _now_iso()

    observations, risks, poam_items, existing_index, next_poam_number, poam_root = _init_poam_state(existing)

    for finding in backlog.get("mapped_items", []):
        if finding.get("status") == "not_applicable":
            continue
        control_id = _control_key(finding)
        if control_id in existing_index:
            _apply_finding_to_existing(
                finding,
                existing or {},
                existing_index,
                observations,
                risks,
                org,
                platform,
                assessment_id,
            )
        else:
            next_poam_number = _apply_finding_as_new(
                finding,
                observations,
                risks,
                poam_items,
                next_poam_number,
                org,
                platform,
                assessment_id,
            )

    sensitivity, open_count, fail_count, partial_count = _compute_sensitivity(backlog)
    version_str = _bump_version(existing, poam_root)

    return {
        "plan-of-action-and-milestones": {
            "uuid": poam_root.get("uuid", _uuid()) if existing else _uuid(),
            "metadata": {
                "title": f"SSCF POA&M — {platform.capitalize()} — {org}",
                "last-modified": now,
                "version": version_str,
                "oscal-version": "1.1.2",
                "props": [
                    {"name": "assessment-id", "value": assessment_id},
                    {"name": "platform", "value": platform},
                    {"name": "org", "value": org},
                    {"name": "sensitivity-tier", "value": sensitivity},
                    {"name": "open-items", "value": str(open_count)},
                ],
                "remarks": (
                    f"Cumulative POA&M updated from assessment run {assessment_id}. "
                    f"Open items: {open_count} (fail: {fail_count}, partial: {partial_count}). "
                    f"Sensitivity tier: {sensitivity} (RED≥10=high, AMBER≥5=moderate, GREEN<5=low)."
                ),
            },
            "import-ssp": {
                "href": f"ssp-{platform}-{org}.json",
                "remarks": "SSP generated by gen_ssp.py. If not yet generated, create with: python3 scripts/gen_ssp.py",
            },
            "system-id": {
                "identifier-type": "https://ietf.org/rfc/rfc4122",
                "id": f"{platform}-{org}",
            },
            "local-definitions": {
                "remarks": (
                    "Components and inventory defined in the companion SSP and component definitions. "
                    "See config/component-definitions/ for platform-specific component UUIDs."
                )
            },
            "observations": observations,
            "risks": risks,
            "poam-items": poam_items,
        }
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate or update an OSCAL POA&M from SSCF assessment backlog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--backlog", required=True, help="Path to backlog.json from oscal_gap_map.py")
    p.add_argument(
        "--gap-analysis",
        required=False,
        default=None,
        help="Path to gap_analysis.json (optional; adds observation detail)",
    )
    p.add_argument("--org", required=True, help="Org alias (e.g. cyber-coach-dev)")
    p.add_argument(
        "--platform",
        default="salesforce",
        choices=["salesforce", "workday"],
        help="Platform (default: salesforce)",
    )
    p.add_argument("--out", required=True, help="Output path for OSCAL POA&M JSON")
    p.add_argument(
        "--existing",
        default=None,
        help="Path to existing POA&M JSON for persistent cumulative update (defaults to --out if it exists)",  # noqa: E501
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    backlog_path = Path(args.backlog)
    if not backlog_path.exists():
        print(f"ERROR: backlog not found: {backlog_path}", file=sys.stderr)
        sys.exit(1)

    backlog = json.loads(backlog_path.read_text())

    # Resolve existing POA&M for cumulative mode
    existing: dict | None = None
    existing_source = args.existing or args.out
    existing_path = Path(existing_source)
    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text())
            print(f"INFO: Loaded existing POA&M from {existing_path} (cumulative update mode)", file=sys.stderr)
        except json.JSONDecodeError as exc:
            print(f"WARN: Could not parse existing POA&M ({exc}) — starting fresh", file=sys.stderr)

    poam = build_poam(
        backlog=backlog,
        org=args.org,
        platform=args.platform,
        existing=existing,
    )

    out_path = _safe_write_path(Path(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(poam, indent=2))

    root = poam["plan-of-action-and-milestones"]
    open_items = len(
        [
            pi
            for pi in root.get("poam-items", [])
            if any(
                prop.get("name") == "lifecycle-state" and prop.get("value") == "open" for prop in pi.get("props", [])
            )
        ]
    )
    total_items = len(root.get("poam-items", []))
    sensitivity = next(
        (p["value"] for p in root["metadata"].get("props", []) if p["name"] == "sensitivity-tier"),
        "unknown",
    )

    print(f"POA&M written to {out_path}")
    print(f"  Total items : {total_items}")
    print(f"  Open items  : {open_items}")
    print(f"  Observations: {len(root.get('observations', []))}")
    print(f"  Risks       : {len(root.get('risks', []))}")
    print(f"  Sensitivity : {sensitivity.upper()}")


if __name__ == "__main__":
    main()
