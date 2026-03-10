"""gen_aicm_crosswalk.py — Generate AICM v1.0.3 coverage report from SSCF assessment.

Maps SSCF backlog findings through sscf_to_aicm_mapping.yaml to produce a per-domain
AICM coverage verdict with live posture data from the current assessment run.

Usage:
    python3 scripts/gen_aicm_crosswalk.py \\
        --backlog  docs/.../backlog.json \\
        --mapping  config/aicm/sscf_to_aicm_mapping.yaml \\
        --catalog  config/aicm/aicm_v1_catalog.json \\
        --out      docs/.../aicm_coverage.json \\
        [--org my-org] [--platform salesforce]

Output: aicm_coverage.json — per-domain coverage verdicts + per-control posture
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml  # PyYAML — already a project dependency

# ── constants ─────────────────────────────────────────────────────────────────

_DEFAULT_MAPPING = Path("config/aicm/sscf_to_aicm_mapping.yaml")
_DEFAULT_CATALOG = Path("config/aicm/aicm_v1_catalog.json")

_SEVERITY_RANK = {"critical": 4, "high": 3, "moderate": 2, "low": 1}
_STATUS_PASS = {"pass", "not_applicable"}

# Coverage roll-up: if any mapped SSCF finding is fail/partial the domain is degraded
_VERDICT_FAIL = "fail"
_VERDICT_PARTIAL = "partial"
_VERDICT_PASS = "pass"
_VERDICT_NOT_ASSESSED = "not_assessed"


# ── helpers ───────────────────────────────────────────────────────────────────


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _index_backlog(backlog: dict) -> dict[str, dict]:
    """Return {control_id: finding} mapping from backlog.json."""
    findings: dict[str, dict] = {}
    for f in backlog.get("findings", []):
        cid = f.get("control_id", "")
        if cid:
            findings[cid] = f
    return findings


def _index_catalog_domains(catalog: dict) -> dict[str, list[str]]:
    """Return {domain_abbrev: [control_id, ...]} from aicm catalog."""
    domain_controls: dict[str, list[str]] = {}
    for ctrl in catalog.get("aicm-catalog", {}).get("controls", []):
        abbrev = ctrl.get("domain_abbrev", "")
        if abbrev:
            domain_controls.setdefault(abbrev, []).append(ctrl.get("id", ""))
    return domain_controls


def _worst_status(statuses: list[str]) -> str:
    """Return the worst status from a list (fail > partial > pass)."""
    if "fail" in statuses:
        return _VERDICT_FAIL
    if "partial" in statuses:
        return _VERDICT_PARTIAL
    return _VERDICT_PASS


def _compute_domain_verdict(
    domain_abbrev: str,
    mapping_verdict: str,
    sscf_controls: list[dict],
    findings_index: dict[str, dict],
) -> dict:
    """Compute live posture for one AICM domain based on mapped SSCF controls."""
    if mapping_verdict == "not_covered":
        return {
            "coverage_verdict": "not_covered",
            "posture_verdict": _VERDICT_NOT_ASSESSED,
            "mapped_sscf_controls": [],
            "failing_controls": [],
            "max_severity": None,
            "note": "No SSCF controls map to this AICM domain — supplemental controls required.",
        }

    mapped_ids: list[str] = []
    statuses: list[str] = []
    failing: list[dict] = []
    max_sev = 0

    for ctrl_entry in sscf_controls:
        sscf_id: str = ctrl_entry.get("sscf_id", "")
        mapped_ids.append(sscf_id)
        finding = findings_index.get(sscf_id)
        if not finding:
            statuses.append("pass")  # not in backlog → passed
            continue
        status = finding.get("status", "pass").lower()
        statuses.append(status)
        if status not in _STATUS_PASS:
            sev = finding.get("severity", "low").lower()
            max_sev = max(max_sev, _SEVERITY_RANK.get(sev, 0))
            failing.append({
                "control_id": sscf_id,
                "status": status,
                "severity": sev,
                "description": finding.get("description", ""),
            })

    posture = _worst_status(statuses) if statuses else _VERDICT_NOT_ASSESSED
    sev_labels = {4: "critical", 3: "high", 2: "moderate", 1: "low", 0: None}

    return {
        "coverage_verdict": mapping_verdict,
        "posture_verdict": posture,
        "mapped_sscf_controls": mapped_ids,
        "failing_controls": failing,
        "max_severity": sev_labels[max_sev],
        "note": None,
    }


# ── core ──────────────────────────────────────────────────────────────────────


def build_aicm_coverage(
    backlog: dict,
    mapping: dict,
    catalog: dict,
    org: str,
    platform: str,
) -> dict:
    """Build the full AICM coverage report."""
    findings_index = _index_backlog(backlog)
    catalog_domains = _index_catalog_domains(catalog)

    controls_map = mapping.get("controls", {})
    uncovered_domains: list[str] = [
        d["abbrev"] for d in mapping.get("uncovered_aicm_domains", [])
    ]

    # Build per-AICM-domain coverage: aggregate all SSCF controls that touch each domain
    # {aicm_abbrev: {mapping_verdict, [sscf_ctrl_entries]}}
    domain_sscf: dict[str, dict] = {}

    for sscf_id, ctrl_data in controls_map.items():
        for aicm_domain_entry in ctrl_data.get("aicm_domains", []):
            abbrev: str = aicm_domain_entry.get("abbrev", "")
            if not abbrev:
                continue
            if abbrev not in domain_sscf:
                domain_sscf[abbrev] = {
                    "mapping_verdict": aicm_domain_entry.get("coverage_verdict", "partial"),
                    "sscf_controls": [],
                }
            # Use the weakest coverage_verdict if multiple SSCF controls hit same domain
            existing = domain_sscf[abbrev]["mapping_verdict"]
            new_v = aicm_domain_entry.get("coverage_verdict", "partial")
            if existing == "covered" and new_v != "covered":
                domain_sscf[abbrev]["mapping_verdict"] = new_v
            domain_sscf[abbrev]["sscf_controls"].append({
                "sscf_id": sscf_id,
                "control_ids": aicm_domain_entry.get("control_ids", []),
                "mapping_strength": aicm_domain_entry.get("mapping_strength", "partial"),
            })

    # Add uncovered domains (not referenced by any SSCF control)
    for abbrev in uncovered_domains:
        if abbrev not in domain_sscf:
            domain_sscf[abbrev] = {"mapping_verdict": "not_covered", "sscf_controls": []}

    # Compute per-domain results
    domain_results: dict[str, dict] = {}
    for abbrev, data in sorted(domain_sscf.items()):
        result = _compute_domain_verdict(
            abbrev,
            data["mapping_verdict"],
            data["sscf_controls"],
            findings_index,
        )
        result["total_aicm_controls"] = len(catalog_domains.get(abbrev, []))
        domain_results[abbrev] = result

    # Summary counts
    covered_count = sum(1 for d in domain_results.values() if d["coverage_verdict"] == "covered")
    partial_count = sum(1 for d in domain_results.values() if d["coverage_verdict"] == "partial")
    gap_count = sum(1 for d in domain_results.values() if d["coverage_verdict"] == "not_covered")
    failing_domains = [a for a, d in domain_results.items() if d["posture_verdict"] == _VERDICT_FAIL]
    partial_domains = [a for a, d in domain_results.items() if d["posture_verdict"] == _VERDICT_PARTIAL]

    aicm_meta = catalog.get("aicm-catalog", {})

    return {
        "schema_version": "1.0",
        "report_type": "aicm_coverage",
        "generated": _now_iso(),
        "org": org,
        "platform": platform,
        "aicm_version": aicm_meta.get("version", "1.0.3"),
        "sscf_version": mapping.get("sscf_version", "1.0"),
        "source": "https://cloudsecurityalliance.org/artifacts/ai-controls-matrix",
        "summary": {
            "total_aicm_domains": len(aicm_meta.get("domains", [])),
            "total_aicm_controls": aicm_meta.get("total_controls", 243),
            "covered_domains": covered_count,
            "partial_domains": partial_count,
            "gap_domains": gap_count,
            "failing_domains": failing_domains,
            "partial_posture_domains": partial_domains,
        },
        "gap_note": (
            "Uncovered domains (not_covered) represent areas where SSCF assessments "
            "provide no evidence. These require supplemental controls reviewed via "
            "questionnaire or third-party audit (DCS, IVS, UEM, BCR, CEK, HRS, MDS)."
        ),
        "domain_coverage": domain_results,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate AICM v1.0.3 coverage report from SSCF backlog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--backlog", required=True, help="Path to backlog.json")
    p.add_argument(
        "--mapping",
        default=str(_DEFAULT_MAPPING),
        help=f"Path to sscf_to_aicm_mapping.yaml (default: {_DEFAULT_MAPPING})",
    )
    p.add_argument(
        "--catalog",
        default=str(_DEFAULT_CATALOG),
        help=f"Path to aicm_v1_catalog.json (default: {_DEFAULT_CATALOG})",
    )
    p.add_argument("--org", default="unknown-org", help="Org alias")
    p.add_argument("--platform", default="salesforce", choices=["salesforce", "workday"])
    p.add_argument("--out", required=True, help="Output path for aicm_coverage.json")
    p.add_argument("--dry-run", action="store_true", help="Print summary only; do not write output")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    backlog_path = Path(args.backlog)
    mapping_path = Path(args.mapping)
    catalog_path = Path(args.catalog)
    out_path = Path(args.out).resolve()

    for label, path in [("backlog", backlog_path), ("mapping", mapping_path), ("catalog", catalog_path)]:
        if not path.exists():
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            return 1

    backlog = _load_json(backlog_path)
    mapping = _load_yaml(mapping_path)
    catalog = _load_json(catalog_path)

    coverage = build_aicm_coverage(backlog, mapping, catalog, args.org, args.platform)

    summary = coverage["summary"]
    print(f"AICM coverage: {summary['covered_domains']} covered / "
          f"{summary['partial_domains']} partial / "
          f"{summary['gap_domains']} gap domains")
    if summary["failing_domains"]:
        print(f"Failing domains: {', '.join(summary['failing_domains'])}")
    if summary["gap_domains"]:
        print(f"Gap domains (no SSCF coverage): DCS, IVS, UEM, BCR, CEK, HRS, MDS")

    if args.dry_run:
        print("Dry run — no file written.")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    print(f"Written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
