#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return data


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required. Install with: pip install PyYAML") from exc
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML object at {path}")
    return data


def _findings(gap: dict[str, Any]) -> list[dict[str, Any]]:
    findings = gap.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("gap-analysis JSON must include findings[]")
    return [f for f in findings if isinstance(f, dict)]


def _confidence_from_status(status: str) -> str:
    """Map finding status to mapping_confidence (Issue #13 — NIST MEASURE-PARTIAL).

    high   — pass/fail: deterministic API evidence confirmed or refuted the control.
    medium — partial: evidence is incomplete or structural; definitive call not possible.
    low    — not_applicable: control is outside collector scope; no API evidence available.
    """
    if status in ("pass", "fail"):
        return "high"
    if status == "partial":
        return "medium"
    return "low"  # not_applicable or unknown


def _status_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"pass": 0, "fail": 0, "partial": 0, "not_applicable": 0}
    for item in items:
        status = str(item.get("status", "")).strip()
        if status in summary:
            summary[status] += 1
    return summary


def _to_markdown(
    assessment_id: str,
    control_count: int,
    mapped_items: list[dict[str, Any]],
    unmapped_items: list[dict[str, Any]],
    invalid_mapping_entries: list[str],
) -> str:
    summary = _status_summary(mapped_items)
    lines = [
        "# Salesforce OSCAL Gap Matrix (POC)",
        "",
        f"- Assessment ID: `{assessment_id}`",
        f"- Generated UTC: `{datetime.now(UTC).isoformat()}`",
        f"- SBS controls in catalog: `{control_count}`",
        f"- Mapped findings: `{len(mapped_items)}`",
        f"- Unmapped findings: `{len(unmapped_items)}`",
        "",
        "## Status Summary (Mapped Findings)",
        f"- pass: `{summary['pass']}`",
        f"- fail: `{summary['fail']}`",
        f"- partial: `{summary['partial']}`",
        f"- not_applicable: `{summary['not_applicable']}`",
        "",
        "## Control Mapping Table",
        "| Legacy Control ID | SBS Control ID | SBS Title | Mapping Confidence"
        " | SSCF Controls | Status | Severity | Owner | Due Date |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for item in mapped_items:
        sscf_controls = ", ".join(item.get("sscf_control_ids", []))
        lines.append(
            "| {legacy} | {sbs} | {title} | {confidence} | {sscf} | {status} | {severity} | {owner} | {due} |".format(
                legacy=item.get("legacy_control_id", ""),
                sbs=item.get("sbs_control_id", ""),
                title=item.get("sbs_title", "").replace("|", "/"),
                confidence=item.get("mapping_confidence", "unrated"),
                sscf=sscf_controls,
                status=item.get("status", ""),
                severity=item.get("severity", ""),
                owner=item.get("owner", ""),
                due=item.get("due_date", ""),
            )
        )

    lines += ["", "## Unmapped Findings"]
    if not unmapped_items:
        lines.append("- None")
    else:
        for item in unmapped_items:
            cid = item.get("legacy_control_id", "")
            lines.append(f"- `{cid}` ({item.get('status', '')}, {item.get('severity', '')})")

    lines += ["", "## Invalid Mapping Entries"]
    if not invalid_mapping_entries:
        lines.append("- None")
    else:
        for entry in invalid_mapping_entries:
            lines.append(f"- {entry}")

    lines.append("")
    return "\n".join(lines)


def _load_iso27001_map(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Load sscf_to_iso27001_mapping.yaml → dict keyed by sscf_control_id."""
    raw = _load_yaml(path)
    result: dict[str, list[dict[str, Any]]] = {}
    for entry in raw.get("mappings", []):
        if isinstance(entry, dict) and entry.get("sscf_control_id"):
            result[entry["sscf_control_id"]] = entry.get("iso27001_controls", [])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Map gap-analysis findings to SBS controls.")
    parser.add_argument("--controls", required=True, help="Path to normalized SBS controls JSON.")
    parser.add_argument("--gap-analysis", required=True, help="Path to gap-analysis JSON.")
    parser.add_argument("--mapping", required=True, help="Path to control mapping YAML.")
    parser.add_argument(
        "--sscf-map",
        default="config/oscal-salesforce/sbs_to_sscf_mapping.yaml",
        help="Path to SBS-to-SSCF mapping YAML.",
    )
    parser.add_argument(
        "--iso27001-map",
        default="config/iso27001/sscf_to_iso27001_mapping.yaml",
        help="Path to SSCF-to-ISO-27001:2022 mapping YAML (optional — skipped if absent).",
    )
    parser.add_argument("--out-md", required=True, help="Output markdown matrix path.")
    parser.add_argument("--out-json", required=True, help="Output JSON backlog path.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    controls_path = (repo_root / args.controls).resolve()
    gap_path = (repo_root / args.gap_analysis).resolve()
    mapping_path = (repo_root / args.mapping).resolve()
    sscf_map_path = (repo_root / args.sscf_map).resolve()
    iso27001_map_path = (repo_root / args.iso27001_map).resolve()
    out_md = (repo_root / args.out_md).resolve()
    out_json = (repo_root / args.out_json).resolve()

    controls_payload = _load_json(controls_path)
    controls = controls_payload.get("controls", [])
    controls_by_id = {c.get("control_id"): c for c in controls if isinstance(c, dict)}

    gap = _load_json(gap_path)
    findings = _findings(gap)
    assessment_id = str(gap.get("assessment_id", "unknown-assessment"))
    assessment_owner = str(gap.get("assessment_owner", ""))

    mapping_cfg = _load_yaml(mapping_path)
    mappings = mapping_cfg.get("mappings", [])
    map_by_legacy: dict[str, dict[str, Any]] = {}
    for row in mappings:
        if isinstance(row, dict):
            legacy = str(row.get("legacy_control_id", "")).strip()
            if legacy:
                map_by_legacy[legacy] = row

    sscf_map_cfg = _load_yaml(sscf_map_path)
    sscf_defaults_by_category = sscf_map_cfg.get("defaults_by_category", {})
    sscf_overrides = sscf_map_cfg.get("control_overrides", {})

    mapped_items: list[dict[str, Any]] = []
    unmapped_items: list[dict[str, Any]] = []
    invalid_mapping_entries: list[str] = []

    # Load SSCF index once for SSCF-* direct mappings (Workday / WSCC path)
    sscf_index: dict[str, dict[str, Any]] = {}
    sscf_index_path = repo_root / "config" / "sscf_control_index.yaml"
    if sscf_index_path.exists():
        sscf_raw = _load_yaml(sscf_index_path)
        sscf_index = {c["sscf_control_id"]: c for c in sscf_raw.get("controls", []) if isinstance(c, dict)}

    for finding in findings:
        legacy_control_id = str(finding.get("control_id", "")).strip()

        # ── SSCF-* direct path (Workday / WSCC) ─────────────────────────────
        if legacy_control_id.startswith("SSCF-"):
            ctrl = sscf_index.get(legacy_control_id, {})
            domain = ctrl.get("domain", "unknown")
            mapped_items.append(
                {
                    "legacy_control_id": legacy_control_id,
                    "sbs_control_id": legacy_control_id,
                    "sbs_title": ctrl.get("title", legacy_control_id),
                    "status": finding.get("status", ""),
                    "severity": finding.get("severity", ctrl.get("severity", "moderate")),
                    "owner": finding.get("owner", ctrl.get("owner_team", "").replace("_", " ").title()),
                    "due_date": finding.get("due_date", ""),
                    "remediation": finding.get("remediation", ""),
                    "evidence_ref": finding.get("evidence_ref", ""),
                    "mapping_notes": "Direct SSCF mapping (WSCC control ID emitted by workday assessor).",
                    "mapping_confidence": _confidence_from_status(finding.get("status", "")),
                    "sscf_mappings": [
                        {
                            "sscf_domain": domain,
                            "sscf_control_id": legacy_control_id,
                            "mapping_strength": "direct",
                            "rationale": "WSCC control is a direct SSCF subset — no translation required.",
                        }
                    ],
                    "sscf_control_ids": [legacy_control_id],
                }
            )
            continue

        if legacy_control_id.startswith("SBS-"):
            sbs_control_id = legacy_control_id
            sbs = controls_by_id.get(sbs_control_id)
            if not sbs:
                invalid_mapping_entries.append(
                    f"{legacy_control_id} -> {sbs_control_id} (SBS control not found in imported catalog)"
                )
                continue

            item: dict[str, Any] = {
                "legacy_control_id": legacy_control_id,
                "sbs_control_id": sbs_control_id,
                "sbs_title": sbs.get("title", ""),
                "status": finding.get("status", ""),
                "severity": finding.get("severity", ""),
                "owner": finding.get("owner", ""),
                "due_date": finding.get("due_date", ""),
                "remediation": finding.get("remediation", ""),
                "evidence_ref": finding.get("evidence_ref", ""),
                "observed_value": finding.get("observed_value", ""),
                "mapping_notes": "Direct collector mapping (SBS control ID emitted by collector).",
                "mapping_confidence": _confidence_from_status(finding.get("status", "")),
                "sscf_mappings": sscf_overrides.get(sbs_control_id)
                or sscf_defaults_by_category.get(sbs.get("category", ""))
                or [],
            }
            if finding.get("needs_expert_review"):
                item["needs_expert_review"] = True
            mapped_items.append(item)
            continue

        map_row = map_by_legacy.get(legacy_control_id)
        if not map_row:
            unmapped_items.append(
                {
                    "legacy_control_id": legacy_control_id,
                    "status": finding.get("status", ""),
                    "severity": finding.get("severity", ""),
                }
            )
            continue

        sbs_control_id = str(map_row.get("sbs_control_id", "")).strip()
        sbs = controls_by_id.get(sbs_control_id)
        if not sbs:
            invalid_mapping_entries.append(f"{legacy_control_id} -> {sbs_control_id} (not found in imported catalog)")
            continue

        mapped_items.append(
            {
                "legacy_control_id": legacy_control_id,
                "sbs_control_id": sbs_control_id,
                "sbs_title": sbs.get("title", ""),
                "status": finding.get("status", ""),
                "severity": finding.get("severity", ""),
                "owner": finding.get("owner", ""),
                "due_date": finding.get("due_date", ""),
                "remediation": finding.get("remediation", ""),
                "evidence_ref": finding.get("evidence_ref", ""),
                "mapping_notes": map_row.get("notes", ""),
                "mapping_confidence": map_row.get("mapping_confidence", "unrated"),
                "sscf_mappings": sscf_overrides.get(sbs_control_id)
                or sscf_defaults_by_category.get(sbs.get("category", ""))
                or [],
            }
        )

    for item in mapped_items:
        sscf_mappings = item.get("sscf_mappings", [])
        item["sscf_control_ids"] = [
            mapping.get("sscf_control_id")
            for mapping in sscf_mappings
            if isinstance(mapping, dict) and mapping.get("sscf_control_id")
        ]

    # ── ISO 27001:2022 Annex A enrichment ────────────────────────────────────
    iso_map: dict[str, list[dict[str, Any]]] = {}
    if iso27001_map_path.exists():
        iso_map = _load_iso27001_map(iso27001_map_path)

    for item in mapped_items:
        iso_controls: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for sscf_id in item.get("sscf_control_ids", []):
            for ctrl in iso_map.get(sscf_id, []):
                iso_id = ctrl.get("id", "")
                if iso_id and iso_id not in seen_ids:
                    seen_ids.add(iso_id)
                    iso_controls.append(
                        {
                            "id": iso_id,
                            "title": ctrl.get("title", ""),
                            "theme": ctrl.get("theme", ""),
                            "mapping_strength": ctrl.get("mapping_strength", "informative"),
                            "applicability": ctrl.get("applicability", "applicable"),
                        }
                    )
        item["iso27001_controls"] = iso_controls
        item["iso27001_control_ids"] = [c["id"] for c in iso_controls]

    iso27001_touched: set[str] = set()
    for item in mapped_items:
        iso27001_touched.update(item.get("iso27001_control_ids", []))

    backlog_payload = {
        "assessment_id": assessment_id,
        "assessment_owner": assessment_owner,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "catalog_version": controls_payload.get("catalog", {}).get("version"),
        "framework": "CSA_SSCF",
        "summary": {
            "catalog_controls": len(controls_by_id),
            "findings_total": len(findings),
            "mapped_findings": len(mapped_items),
            "unmapped_findings": len(unmapped_items),
            "invalid_mapping_entries": len(invalid_mapping_entries),
            "status_counts": _status_summary(mapped_items),
            "mapping_confidence_counts": {
                confidence: sum(1 for item in mapped_items if item.get("mapping_confidence") == confidence)
                for confidence in sorted({item.get("mapping_confidence", "unrated") for item in mapped_items})
            },
            "iso27001_summary": {
                "framework": "ISO/IEC 27001:2022",
                "annex_a_total_controls": 93,
                "unique_annex_a_controls_touched": len(iso27001_touched),
                "mapping_loaded": iso27001_map_path.exists(),
            },
        },
        "mapped_items": mapped_items,
        "unmapped_items": unmapped_items,
        "invalid_mapping_entries": invalid_mapping_entries,
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(backlog_payload, indent=2))
    out_md.write_text(
        _to_markdown(
            assessment_id=assessment_id,
            control_count=len(controls_by_id),
            mapped_items=mapped_items,
            unmapped_items=unmapped_items,
            invalid_mapping_entries=invalid_mapping_entries,
        )
    )

    print(f"Mapped findings written to {out_json}")
    print(f"Gap matrix written to {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
