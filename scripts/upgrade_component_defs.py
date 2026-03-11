"""upgrade_component_defs.py — Add control-origination and set-parameters to component defs.

Upgrades both Salesforce and Workday OSCAL component definitions to add:
  - `control-origination` prop to every implemented-requirement
    (customer-configured, customer-provided, or shared)
  - `responsibility` prop to every implemented-requirement
  - `set-parameters` referencing the key ODPs from the profile

Run once from the repo root:
    python3 scripts/upgrade_component_defs.py
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _safe_write_path(p: Path) -> Path:
    """Resolve *p* and assert it stays within the repo tree."""
    resolved = p.resolve()
    if not resolved.is_relative_to(_REPO):
        raise ValueError(f"Output path '{resolved}' escapes the repository root.")
    return resolved


# ── Origination map: control-id → origination type ───────────────────────────
# FedRAMP origination types:
#   customer-configured  — org configures settings in the SaaS platform
#   customer-provided    — org provides/manages the capability (e.g. own IdP)
#   inherited            — SaaS vendor implements; org inherits the control
#   shared               — both org and vendor share responsibility

SFDC_ORIGINATION: dict[str, str] = {
    # IAM — mostly customer-configured (org sets Salesforce IAM policies)
    "sscf-iam-001": "customer-configured",  # MFA enforcement in Salesforce
    "sscf-iam-002": "customer-configured",  # privileged access review
    "sscf-iam-003": "customer-provided",  # org provides the IdP (Okta/Azure AD)
    "sscf-iam-004": "customer-configured",  # user lifecycle via SCIM/manual
    "sscf-iam-005": "customer-configured",  # service account governance
    "sscf-iam-006": "customer-configured",  # session timeout settings
    "sscf-iam-007": "customer-configured",  # JIT access workflow
    "sscf-iam-008": "customer-configured",  # external access controls
    # CON — org hardening of Salesforce settings
    "sscf-con-001": "customer-configured",  # baseline enforcement
    "sscf-con-002": "customer-configured",  # drift detection
    "sscf-con-003": "customer-configured",  # credential lifecycle
    "sscf-con-004": "customer-configured",  # platform hardening
    "sscf-con-005": "customer-configured",  # third-party integrations
    "sscf-con-006": "shared",  # patching: vendor releases, org enables
    # DSP — org configures Salesforce data controls
    "sscf-dsp-001": "customer-configured",  # sensitive data access
    "sscf-dsp-002": "customer-configured",  # export controls
    "sscf-dsp-003": "customer-configured",  # data classification
    "sscf-dsp-004": "customer-configured",  # cross-border data transfer
    "sscf-dsp-005": "customer-configured",  # retention schedules
    "sscf-dsp-006": "customer-configured",  # privacy rights
    # IPY
    "sscf-ipy-001": "shared",  # export: vendor provides API, org tests
    "sscf-ipy-002": "shared",  # API security: vendor controls + org governs
    "sscf-ipy-003": "customer-configured",  # integration inventory
    "sscf-ipy-004": "customer-provided",  # exit planning is org's responsibility
    "sscf-ipy-005": "customer-configured",  # data residency config
    # LOG
    "sscf-log-001": "customer-configured",  # log enablement (Event Monitoring)
    "sscf-log-002": "customer-configured",  # admin audit logging
    "sscf-log-003": "customer-configured",  # audit retention
    "sscf-log-004": "customer-configured",  # real-time monitoring
    "sscf-log-005": "customer-configured",  # SIEM integration
    "sscf-log-006": "customer-configured",  # UEBA
    # SEF
    "sscf-sef-001": "customer-configured",  # threat policies
    "sscf-sef-002": "customer-provided",  # SOC triage is org-operated
    "sscf-sef-003": "customer-provided",  # IR plan is org-owned
    "sscf-sef-004": "customer-provided",  # forensics readiness
    "sscf-sef-005": "customer-configured",  # exception governance
}

WD_ORIGINATION: dict[str, str] = {
    "sscf-iam-001": "customer-configured",
    "sscf-iam-002": "customer-configured",
    "sscf-iam-003": "customer-provided",
    "sscf-iam-004": "customer-configured",
    "sscf-iam-005": "customer-configured",
    "sscf-iam-006": "customer-configured",
    "sscf-iam-007": "customer-configured",
    "sscf-iam-008": "customer-configured",
    "sscf-con-001": "customer-configured",
    "sscf-con-002": "customer-configured",
    "sscf-con-003": "customer-configured",
    "sscf-con-004": "customer-configured",
    "sscf-con-005": "customer-configured",
    "sscf-dsp-001": "customer-configured",
    "sscf-dsp-002": "customer-configured",
    "sscf-dsp-003": "customer-configured",
    "sscf-dsp-004": "customer-configured",
    "sscf-dsp-005": "customer-configured",
    "sscf-ipy-001": "shared",
    "sscf-ipy-002": "shared",
    "sscf-ipy-003": "customer-configured",
    "sscf-log-001": "customer-configured",
    "sscf-log-002": "customer-configured",
    "sscf-log-003": "customer-configured",
    "sscf-log-004": "customer-configured",
    "sscf-log-005": "customer-configured",
    "sscf-sef-001": "customer-configured",
    "sscf-sef-002": "customer-provided",
    "sscf-sef-003": "customer-provided",
    "sscf-sef-005": "customer-configured",
}

# Key ODP set-parameters to add per control in each component definition
# These represent the concrete values the organization configures in the platform
SFDC_SET_PARAMS: dict[str, list[dict]] = {
    "sscf-iam-001": [
        {"param-id": "sscf-iam-001_prm_1", "values": ["annually"]},
    ],
    "sscf-iam-002": [
        {"param-id": "sscf-iam-002_prm_1", "values": ["annually"]},
        {"param-id": "sscf-iam-002_prm_2", "values": ["30 days"]},
    ],
    "sscf-iam-003": [
        {"param-id": "sscf-iam-003_prm_1", "values": ["quarterly"]},
    ],
    "sscf-iam-004": [
        {"param-id": "sscf-iam-004_prm_1", "values": ["24 hours"]},
        {"param-id": "sscf-iam-004_prm_2", "values": ["7 days"]},
        {"param-id": "sscf-iam-004_prm_3", "values": ["90 days"]},
    ],
    "sscf-iam-006": [
        {"param-id": "sscf-iam-006_prm_1", "values": ["8 hours"]},
        {"param-id": "sscf-iam-006_prm_2", "values": ["30 minutes"]},
    ],
    "sscf-con-002": [
        {"param-id": "sscf-con-002_prm_1", "values": ["24 hours"]},
        {"param-id": "sscf-con-002_prm_2", "values": ["7 days"]},
        {"param-id": "sscf-con-002_prm_3", "values": ["30 days"]},
    ],
    "sscf-con-003": [
        {"param-id": "sscf-con-003_prm_1", "values": ["90 days"]},
        {"param-id": "sscf-con-003_prm_2", "values": ["180 days"]},
        {"param-id": "sscf-con-003_prm_3", "values": ["1 year"]},
    ],
    "sscf-log-003": [
        {"param-id": "sscf-log-003_prm_1", "values": ["12 months"]},
        {"param-id": "sscf-log-003_prm_2", "values": ["36 months"]},
    ],
    "sscf-log-004": [
        {"param-id": "sscf-log-004_prm_1", "values": ["5 minutes"]},
    ],
    "sscf-sef-002": [
        {"param-id": "sscf-sef-002_prm_1", "values": ["15 minutes"]},
        {"param-id": "sscf-sef-002_prm_2", "values": ["1 hour"]},
    ],
    "sscf-sef-005": [
        {"param-id": "sscf-sef-005_prm_1", "values": ["12 months"]},
    ],
}

# Workday uses same key params; reuse SFDC mapping for shared controls
WD_SET_PARAMS = {k: v for k, v in SFDC_SET_PARAMS.items() if k in WD_ORIGINATION}


def _upgrade_impl_requirements(
    impl_reqs: list[dict],
    origination_map: dict[str, str],
    set_params_map: dict[str, list[dict]],
) -> list[dict]:
    """Add control-origination, responsibility, and set-parameters to each impl-req."""
    upgraded = []
    for req in impl_reqs:
        control_id = req.get("control-id", "")
        origination = origination_map.get(control_id, "customer-configured")

        # Add control-origination and responsibility to props (avoid duplicates)
        existing_props = req.get("props", [])
        existing_prop_names = {p["name"] for p in existing_props}

        new_props = list(existing_props)
        if "control-origination" not in existing_prop_names:
            new_props.append({"name": "control-origination", "value": origination})
        if "responsibility" not in existing_prop_names:
            new_props.append({"name": "responsibility", "value": origination})

        updated_req = {**req, "props": new_props}

        # Add set-parameters if defined for this control
        sp = set_params_map.get(control_id, [])
        if sp:
            updated_req["set-parameters"] = sp

        upgraded.append(updated_req)
    return upgraded


def upgrade_component_def(
    path: Path,
    origination_map: dict[str, str],
    set_params_map: dict[str, list[dict]],
) -> None:
    if not path.exists():
        print(f"WARN: {path} not found — skipping")
        return

    comp_def = json.loads(path.read_text())
    root = comp_def.get("component-definition", {})

    for component in root.get("components", []):
        for ctrl_impl in component.get("control-implementations", []):
            impl_reqs = ctrl_impl.get("implemented-requirements", [])
            ctrl_impl["implemented-requirements"] = _upgrade_impl_requirements(
                impl_reqs, origination_map, set_params_map
            )

    # Bump version and last-modified
    meta = root.get("metadata", {})
    meta["last-modified"] = "2026-03-10T00:00:00Z"
    old_remarks = meta.get("remarks", "")
    if "control-origination" not in old_remarks:
        meta["remarks"] = (
            old_remarks.rstrip(".") + ". "
            "Upgraded 2026-03-10: control-origination, responsibility props, and "
            "set-parameters added to all implemented-requirements."
        )
    root["metadata"] = meta

    _safe_write_path(path).write_text(json.dumps(comp_def, indent=2))
    impl_count = sum(
        len(ctrl.get("implemented-requirements", []))
        for comp in root.get("components", [])
        for ctrl in comp.get("control-implementations", [])
    )
    print(f"Upgraded {impl_count} implemented-requirements in {path}")


def main() -> None:
    upgrade_component_def(
        Path("config/component-definitions/salesforce_component.json"),
        SFDC_ORIGINATION,
        SFDC_SET_PARAMS,
    )
    upgrade_component_def(
        Path("config/component-definitions/workday_component.json"),
        WD_ORIGINATION,
        WD_SET_PARAMS,
    )
    print("Done. Review with: git diff config/component-definitions/")


if __name__ == "__main__":
    main()
