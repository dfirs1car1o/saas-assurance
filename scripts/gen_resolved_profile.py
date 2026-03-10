"""gen_resolved_profile.py — Generate a resolved OSCAL profile catalog.

Reads the SSCF base catalog + a platform profile (SBS or WSCC) and produces
a standalone "resolved catalog" with:
  - Only the controls selected by the profile
  - All param {{ insert: param, ... }} references substituted with set-parameter values
  - Platform-specific alters (added parts) merged in
  - Metadata documenting the resolution chain

This is the OSCAL "resolved profile catalog" concept — FedRAMP publishes these as
their High/Moderate/Low baseline artifacts so that tools don't need to traverse
a catalog→profile chain at runtime.

Usage:
    # Salesforce SBS resolved catalog
    python3 scripts/gen_resolved_profile.py \
        --catalog  config/sscf/sscf_v1_catalog.json \
        --profile  config/salesforce/sbs_v1_profile.json \
        --out      config/salesforce/sbs_resolved_catalog.json

    # Workday WSCC resolved catalog
    python3 scripts/gen_resolved_profile.py \
        --catalog  config/sscf/sscf_v1_catalog.json \
        --profile  config/workday/wscc_v1_profile.json \
        --out      config/workday/wscc_resolved_catalog.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

_PARAM_RE = re.compile(r"\{\{\s*insert:\s*param,\s*([\w-]+)\s*\}\}")


def _uuid() -> str:
    return str(uuid.uuid4())


def _substitute_params(text: str, param_map: dict[str, str]) -> str:
    """Replace {{ insert: param, param-id }} with resolved values."""

    def _replace(m: re.Match) -> str:
        param_id = m.group(1)
        return param_map.get(param_id, f"[UNRESOLVED: {param_id}]")

    return _PARAM_RE.sub(_replace, text)


def _resolve_parts(parts: list[dict], param_map: dict[str, str]) -> list[dict]:
    """Recursively substitute params in all part prose."""
    resolved = []
    for part in parts:
        p = dict(part)
        if "prose" in p:
            p["prose"] = _substitute_params(p["prose"], param_map)
        if "parts" in p:
            p["parts"] = _resolve_parts(p["parts"], param_map)
        resolved.append(p)
    return resolved


def _build_param_map(
    catalog_controls: dict[str, dict],
    profile_set_params: list[dict],
) -> dict[str, str]:
    """
    Build param-id → resolved value map.
    Profile set-parameters override catalog param defaults.
    """
    param_map: dict[str, str] = {}

    # Seed from catalog defaults
    for control in catalog_controls.values():
        for param in control.get("params", []):
            pid = param.get("id", "")
            values = param.get("values", [])
            if pid and values:
                param_map[pid] = ", ".join(values)

    # Override with profile set-parameters
    for sp in profile_set_params:
        pid = sp.get("param-id", "")
        values = sp.get("values", [])
        if pid and values:
            param_map[pid] = ", ".join(values)

    return param_map


def _profile_root(profile: dict) -> dict:
    """Return the profile object regardless of whether it's wrapped in {'profile': ...}."""
    return profile.get("profile", profile)


def _get_profile_selected_ids(profile: dict) -> set[str]:
    """Extract the set of control IDs selected by the profile imports."""
    selected: set[str] = set()
    root = _profile_root(profile)
    for imp in root.get("imports", []):
        include = imp.get("include-controls", [])
        for block in include:
            for cid in block.get("with-ids", []):
                selected.add(cid)
    return selected


def _get_profile_alters(profile: dict) -> dict[str, list[dict]]:
    """Build {control-id: [alter-add-parts]} from profile alters."""
    alters: dict[str, list[dict]] = {}
    root = _profile_root(profile)
    for alter in root.get("modify", {}).get("alters", []):
        control_id = alter.get("control-id", "")
        adds = alter.get("adds", [])
        if control_id and adds:
            alters.setdefault(control_id, []).extend(adds)
    return alters


def _flatten_catalog_controls(catalog: dict) -> dict[str, dict]:
    """Return {control-id: control-dict} for all controls in the catalog."""
    result: dict[str, dict] = {}
    for group in catalog.get("catalog", {}).get("groups", []):
        for control in group.get("controls", []):
            result[control["id"]] = {**control, "_group_id": group["id"], "_group_title": group["title"]}
    return result


def _params_to_props(params: list[dict], param_map: dict[str, str]) -> list[dict]:
    """Convert catalog params to resolved-param props (traceability record)."""
    props = []
    for p in params:
        pid = p.get("id", "")
        resolved_val = param_map.get(pid, ", ".join(p.get("values", [])))
        props.append(
            {
                "name": f"resolved-param:{pid}",
                "value": resolved_val,
                "remarks": p.get("usage", ""),
            }
        )
    return props


def _merge_alter_adds(resolved: dict, alter_adds: list[dict]) -> None:
    """Merge platform alter add-parts into resolved control parts in-place."""
    for add in alter_adds:
        add_parts = add.get("parts", [])
        if not add_parts:
            continue
        existing = resolved.get("parts", [])
        if add.get("position", "ending") == "starting":
            resolved["parts"] = add_parts + existing
        else:
            resolved["parts"] = existing + add_parts


def _resolve_control(
    control: dict,
    param_map: dict[str, str],
    alter_adds: list[dict] | None = None,
) -> dict:
    """
    Produce a resolved control:
    - params removed (values substituted into prose)
    - statement prose has params resolved
    - alter add-parts merged into parts list
    """
    resolved: dict = {}

    for key, val in control.items():
        if key in ("_group_id", "_group_title"):
            continue
        if key == "params":
            resolved.setdefault("props", [])
            resolved["props"].extend(_params_to_props(val, param_map))
        elif key == "props":
            resolved.setdefault("props", [])
            resolved["props"].extend(val)
        elif key == "parts":
            resolved["parts"] = _resolve_parts(val, param_map)
        else:
            resolved[key] = val

    if alter_adds:
        _merge_alter_adds(resolved, alter_adds)

    return resolved


def resolve_profile(
    catalog: dict,
    profile: dict,
) -> dict:
    """Produce the resolved catalog dict."""
    catalog_controls = _flatten_catalog_controls(catalog)
    selected_ids = _get_profile_selected_ids(profile)
    set_params = _profile_root(profile).get("modify", {}).get("set-parameters", [])
    param_map = _build_param_map(catalog_controls, set_params)
    alters = _get_profile_alters(profile)

    # Group controls by domain, preserving catalog group order
    groups_order = [g["id"] for g in catalog.get("catalog", {}).get("groups", [])]
    group_info = {
        g["id"]: {"title": g["title"], "props": g.get("props", [])}
        for g in catalog.get("catalog", {}).get("groups", [])
    }

    resolved_groups: dict[str, list[dict]] = {gid: [] for gid in groups_order}

    for cid, control in catalog_controls.items():
        if cid not in selected_ids:
            continue
        group_id = control.get("_group_id", "unknown")
        resolved = _resolve_control(
            control,
            param_map,
            alter_adds=alters.get(cid),
        )
        resolved_groups.setdefault(group_id, []).append(resolved)

    # Build resolved groups list (only non-empty)
    groups = []
    for gid in groups_order:
        controls = resolved_groups.get(gid, [])
        if not controls:
            continue
        gi = group_info.get(gid, {})
        groups.append(
            {
                "id": gid,
                "class": "domain",
                "title": gi.get("title", gid),
                "props": gi.get("props", []),
                "controls": controls,
            }
        )

    # Build metadata
    profile_meta = _profile_root(profile).get("metadata", {})
    catalog_meta = catalog.get("catalog", {}).get("metadata", {})

    return {
        "catalog": {
            "uuid": _uuid(),
            "metadata": {
                "title": f"{profile_meta.get('title', 'Resolved Profile')} — Resolved Catalog",
                "last-modified": profile_meta.get("last-modified", ""),
                "version": profile_meta.get("version", "1.0.0"),
                "oscal-version": "1.1.2",
                "remarks": (
                    f"Resolved profile catalog. Base: {catalog_meta.get('title', '')}. "
                    f"Profile: {profile_meta.get('title', '')}. "
                    f"Selected controls: {len(selected_ids)}. "
                    f"All param {{ insert: param, ... }} references have been substituted "
                    "with profile set-parameter values. Platform-specific alters merged. "
                    "Generated by scripts/gen_resolved_profile.py."
                ),
                "props": [
                    {"name": "resolution-origin-catalog", "value": "config/sscf/sscf_v1_catalog.json"},
                    {"name": "resolution-origin-profile", "value": profile_meta.get("title", "")},
                    {"name": "selected-control-count", "value": str(len(selected_ids))},
                    {"name": "param-resolution-count", "value": str(len(param_map))},
                ],
                "roles": catalog_meta.get("roles", []),
                "parties": catalog_meta.get("parties", []),
                "responsible-parties": catalog_meta.get("responsible-parties", []),
            },
            "groups": groups,
            "back-matter": catalog.get("catalog", {}).get("back-matter", {}),
        }
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Resolve an OSCAL profile against the SSCF catalog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--catalog", required=True, help="Path to SSCF base catalog JSON")
    p.add_argument("--profile", required=True, help="Path to platform profile JSON (SBS or WSCC)")
    p.add_argument("--out", required=True, help="Output path for resolved catalog JSON")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    catalog_path = Path(args.catalog)
    profile_path = Path(args.profile)
    out_path = Path(args.out)

    if not catalog_path.exists():
        print(f"ERROR: catalog not found: {catalog_path}", file=sys.stderr)
        sys.exit(1)
    if not profile_path.exists():
        print(f"ERROR: profile not found: {profile_path}", file=sys.stderr)
        sys.exit(1)

    catalog = json.loads(catalog_path.read_text())
    profile = json.loads(profile_path.read_text())

    resolved = resolve_profile(catalog, profile)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(resolved, indent=2))

    total_controls = sum(len(g["controls"]) for g in resolved["catalog"]["groups"])
    total_params = int(
        next(p["value"] for p in resolved["catalog"]["metadata"]["props"] if p["name"] == "param-resolution-count")
    )
    print(f"Resolved catalog written to {out_path}")
    print(f"  Groups    : {len(resolved['catalog']['groups'])}")
    print(f"  Controls  : {total_controls}")
    print(f"  Params resolved: {total_params}")


if __name__ == "__main__":
    main()
