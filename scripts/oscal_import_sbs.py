#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET  # safer XML parsing (prevents XXE/entity expansion)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required. Install with: pip install PyYAML") from exc
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML config format: {path}")
    return data


def _read_xml_bytes(source_cfg: dict[str, Any], base_dir: Path) -> bytes:
    local_xml = source_cfg.get("local_xml_path")
    if isinstance(local_xml, str) and local_xml.strip():
        local_path = (base_dir / local_xml).resolve()
        return local_path.read_bytes()

    xml_url = source_cfg.get("xml_url")
    if not isinstance(xml_url, str) or not xml_url.strip():
        raise ValueError("Missing required xml_url in source config.")

    # Restrict to HTTPS only — prevents file:// and custom scheme abuse (B310)
    if not xml_url.startswith("https://"):
        raise ValueError(f"xml_url must use https:// scheme, got: {xml_url!r}")

    with urllib.request.urlopen(xml_url, timeout=60) as response:  # noqa: S310
        return response.read()


def _text(parent: ET.Element, name: str, ns: dict[str, str]) -> str:
    value = parent.findtext(f"s:{name}", default="", namespaces=ns)
    return value.strip()


def _parse_controls(xml_bytes: bytes) -> dict[str, Any]:  # NOSONAR
    root = ET.fromstring(xml_bytes)
    ns = {"s": "https://securitybenchmark.dev/sbs/v1"}

    metadata = root.find("s:metadata", ns)
    version = _text(metadata, "version", ns) if metadata is not None else ""
    title = _text(metadata, "title", ns) if metadata is not None else ""
    total_controls = _text(metadata, "total_controls", ns) if metadata is not None else ""

    controls: list[dict[str, Any]] = []
    for category in root.findall("s:controls/s:category", ns):
        category_name = _text(category, "name", ns)
        category_description = _text(category, "description", ns)

        for control in category.findall("s:control", ns):
            control_id = control.attrib.get("id", "").strip()
            remediation_scope_node = control.find("s:remediation_scope", ns)
            task_node = control.find("s:task", ns)
            controls.append(
                {
                    "control_id": control_id,
                    "category": category_name,
                    "category_description": category_description,
                    "title": _text(control, "title", ns),
                    "statement": _text(control, "statement", ns),
                    "description": _text(control, "description", ns),
                    "risk": _text(control, "risk", ns),
                    "risk_level": _text(control, "risk_level", ns),
                    "audit_procedure": _text(control, "audit_procedure", ns),
                    "remediation": _text(control, "remediation", ns),
                    "default_value": _text(control, "default_value", ns),
                    "remediation_scope": {
                        "scope": _text(remediation_scope_node, "scope", ns)
                        if remediation_scope_node is not None
                        else "",
                        "entity_type": _text(remediation_scope_node, "entity_type", ns)
                        if remediation_scope_node is not None
                        else "",
                    },
                    "task": {"title_template": _text(task_node, "title_template", ns) if task_node is not None else ""},
                }
            )

    return {
        "metadata": {
            "title": title,
            "version": version,
            "total_controls": int(total_controls) if total_controls.isdigit() else len(controls),
        },
        "controls": controls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import SBS XML and normalize controls to JSON.")
    parser.add_argument(
        "--source-config",
        default="config/oscal-salesforce/sbs_source.yaml",
        help="Path to SBS source configuration YAML.",
    )
    parser.add_argument(
        "--out",
        default="docs/oscal-salesforce-poc/generated/sbs_controls.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    source_cfg_path = (repo_root / args.source_config).resolve()
    out_path = (repo_root / args.out).resolve()

    source_cfg = _load_yaml(source_cfg_path)
    xml_bytes = _read_xml_bytes(source_cfg, repo_root)
    parsed = _parse_controls(xml_bytes)

    payload = {
        "source": {
            "benchmark_name": source_cfg.get("benchmark_name"),
            "benchmark_short_name": source_cfg.get("benchmark_short_name"),
            "release_tag": source_cfg.get("release_tag"),
            "xml_url": source_cfg.get("xml_url"),
        },
        "catalog": parsed["metadata"],
        "controls": parsed["controls"],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {len(parsed['controls'])} controls to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
