"""
oscal-assess — deterministic SBS control assessor for Salesforce orgs.

Takes sfdc-connect collector output and applies structural rules to produce
a gap-analysis JSON consumed by scripts/oscal_gap_map.py.

Read-only. Never connects to Salesforce directly.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import click
import yaml

# ---------------------------------------------------------------------------
# Finding model
# ---------------------------------------------------------------------------

VALID_STATUSES = {"pass", "fail", "partial", "not_applicable"}
VALID_SEVERITIES = {"critical", "high", "moderate", "low"}
_VALID_DATA_SOURCES = {"live_api", "dry_run_stub", "manual_questionnaire"}


@dataclass
class Finding:
    control_id: str
    status: str
    severity: str
    observed_value: str
    remediation: str = ""
    owner: str = "SaaS Security Team"
    due_date: str = ""
    needs_expert_review: bool = False

    def to_dict(self, _org: str, env: str, date_str: str) -> dict[str, Any]:
        d: dict[str, Any] = {
            "control_id": self.control_id,
            "status": self.status,
            "severity": self.severity,
            "owner": self.owner,
            "due_date": self.due_date,
            "observed_value": self.observed_value,
            "remediation": self.remediation,
            "evidence_ref": f"collector://salesforce/{env}/{self.control_id}/snapshot-{date_str}",
        }
        if self.needs_expert_review:
            d["needs_expert_review"] = True
        return d


# ---------------------------------------------------------------------------
# Due-date SLA table (Issue #10 — NIST MANAGE-BLOCK)
# ---------------------------------------------------------------------------

_DUE_DATE_DAYS: dict[str, int] = {
    "critical": 7,
    "high": 30,
    "moderate": 90,
    "low": 180,
}


def _auto_due_date(severity: str, status: str, assessed_dt: datetime) -> str:
    """Return ISO due date for actionable findings; empty string for pass/not_applicable."""
    if status not in ("fail", "partial"):
        return ""
    days = _DUE_DATE_DAYS.get(severity, 90)
    return (assessed_dt + timedelta(days=days)).strftime("%Y-%m-%d")


def _normalize_assessment_owner(owner: str | None) -> str:
    """Return a valid accountable owner name for assessment metadata."""
    if not owner:
        return "SaaS Security Architect"
    normalized = owner.strip()
    if not normalized or normalized.lower() == "unknown":
        return "SaaS Security Architect"
    return normalized


def _normalize_data_source(dry_run: bool, source: str | None = None) -> str:
    """Return a NIST-review-compliant data_source enum."""
    if dry_run:
        return "dry_run_stub"
    normalized = (source or "").strip().lower()
    if normalized in _VALID_DATA_SOURCES:
        return normalized
    return "live_api"


def _na(control_id: str, severity: str, reason: str = "Scope not collected by sfdc-connect") -> Finding:
    """Return a not_applicable finding — scope data unavailable."""
    return Finding(
        control_id=control_id,
        status="not_applicable",
        severity=severity,
        observed_value=reason,
    )


def _scope(raw: dict[str, Any], scope_name: str) -> dict[str, Any] | None:
    """Extract a named scope's data from sfdc-connect raw output.

    sfdc-connect --scope all produces raw = {scope_name: {...}, ...}.
    sfdc-connect --scope auth produces raw = {auth data directly}.
    We handle both shapes.
    """
    if scope_name in raw:
        return raw[scope_name]
    # Single-scope output: raw IS the scope data
    return raw if raw else None


def _total(obj: Any) -> int:
    """Safely extract totalSize from a SOQL result dict."""
    if isinstance(obj, dict):
        return int(obj.get("totalSize", 0))
    return 0


def _records(obj: Any) -> list[dict]:
    """Safely extract records list from a SOQL result dict."""
    if isinstance(obj, dict):
        return [r for r in obj.get("records", []) if isinstance(r, dict)]
    return []


# ---------------------------------------------------------------------------
# Assessment rules — Authentication
# ---------------------------------------------------------------------------


def _rule_auth_001(raw: dict[str, Any]) -> Finding:
    """SBS-AUTH-001: Enable Organization-Wide SSO Enforcement Setting."""
    auth = _scope(raw, "auth")
    if not auth:
        return _na("SBS-AUTH-001", "critical")

    sso = auth.get("sso_providers", {})
    providers = _records(sso)
    enabled = [p for p in providers if p.get("IsEnabled")]

    if not providers:
        return Finding(
            "SBS-AUTH-001",
            "fail",
            "critical",
            "No SAML SSO providers configured — org-wide SSO not enforced.",
            "Configure and enable at least one SAML SSO provider in Setup > Single Sign-On Settings.",
        )
    if not enabled:
        return Finding(
            "SBS-AUTH-001",
            "partial",
            "critical",
            f"{len(providers)} SSO provider(s) configured but none enabled.",
            "Enable the configured SSO provider and enforce org-wide SSO.",
        )
    return Finding(
        "SBS-AUTH-001",
        "pass",
        "critical",
        f"{len(enabled)} enabled SSO provider(s) found.",
    )


def _rule_auth_002(raw: dict[str, Any]) -> Finding:
    """SBS-AUTH-002: Govern users permitted to bypass SSO."""
    auth = _scope(raw, "auth")
    if not auth:
        return _na("SBS-AUTH-002", "moderate")

    sso = auth.get("sso_providers", {})
    providers = _records(sso)
    ip_ranges = _total(auth.get("login_ip_ranges", {}))

    if not providers:
        return Finding(
            "SBS-AUTH-002",
            "partial",
            "moderate",
            "SSO not configured — SSO bypass governance cannot be assessed.",
            "Configure SSO before evaluating bypass governance.",
        )
    if ip_ranges == 0:
        return Finding(
            "SBS-AUTH-002",
            "partial",
            "moderate",
            f"SSO configured ({len(providers)} provider(s)) but no Login IP Ranges restrict bypass.",
            "Define Login IP Ranges on profiles that are exempt from SSO to limit bypass exposure.",
        )
    return Finding(
        "SBS-AUTH-002",
        "pass",
        "moderate",
        f"SSO configured with {ip_ranges} Login IP Range restriction(s) governing bypass.",
    )


def _rule_auth_003(raw: dict[str, Any]) -> Finding:
    """SBS-AUTH-003: Prohibit broad/unrestricted profile Login IP ranges."""
    auth = _scope(raw, "auth")
    if not auth:
        return _na("SBS-AUTH-003", "moderate")

    ip_ranges = _total(auth.get("login_ip_ranges", {}))
    if ip_ranges == 0:
        return Finding(
            "SBS-AUTH-003",
            "fail",
            "moderate",
            "No Login IP Ranges configured — all IPs permitted for all profiles.",
            "Configure Login IP Ranges on privileged profiles to restrict access by network location.",
        )
    if ip_ranges < 3:
        return Finding(
            "SBS-AUTH-003",
            "partial",
            "moderate",
            f"Only {ip_ranges} Login IP Range(s) — coverage may be incomplete.",
            "Review whether all privileged profiles have Login IP Ranges applied.",
        )
    return Finding(
        "SBS-AUTH-003",
        "pass",
        "moderate",
        f"{ip_ranges} Login IP Range(s) configured.",
    )


def _rule_auth_004(raw: dict[str, Any]) -> Finding:
    """SBS-AUTH-004: Enforce strong MFA for external users."""
    auth = _scope(raw, "auth")
    if not auth:
        return _na("SBS-AUTH-004", "moderate")

    mfa = auth.get("mfa_org_settings", {})
    if isinstance(mfa, dict) and "error" in mfa:
        return Finding(
            "SBS-AUTH-004",
            "partial",
            "moderate",
            "MFA org settings could not be retrieved via Tooling API — manual review required.",
            "Verify MFA enforcement for external users in Setup > Identity Verification.",
        )

    records = _records(mfa)
    if records:
        rec = records[0]
        mfa_ui = rec.get("MultiFactorAuthenticationForUserUI", False)
        if mfa_ui:
            return Finding(
                "SBS-AUTH-004",
                "pass",
                "moderate",
                "MFA enforced for user UI (MultiFactorAuthenticationForUserUI=true).",
            )
    return Finding(
        "SBS-AUTH-004",
        "partial",
        "moderate",
        "MFA org-level enforcement not confirmed — Tooling API returned no usable MFA fields.",
        "Confirm MFA enforcement in Setup > Identity Verification or via Transaction Security policies.",
    )


# ---------------------------------------------------------------------------
# Assessment rules — Access Controls
# ---------------------------------------------------------------------------


def _rule_acs_001(raw: dict[str, Any]) -> Finding:
    """SBS-ACS-001: Enforce a documented permission set model."""
    access = _scope(raw, "access")
    if not access:
        return _na("SBS-ACS-001", "high")

    admin_profiles = _total(access.get("admin_profiles", {}))
    if admin_profiles > 5:
        return Finding(
            "SBS-ACS-001",
            "fail",
            "high",
            f"{admin_profiles} profiles with ModifyAllData or ManageUsers — excessive admin surface.",
            "Reduce admin profiles; document and justify each. Target ≤2 for ModifyAllData.",
        )
    if admin_profiles > 2:
        return Finding(
            "SBS-ACS-001",
            "partial",
            "high",
            f"{admin_profiles} elevated profiles — review and justify each.",
            "Document justification for all profiles with elevated permissions.",
        )
    return Finding(
        "SBS-ACS-001",
        "pass",
        "high",
        f"{admin_profiles} admin profile(s) — within acceptable threshold.",
    )


def _rule_acs_002(raw: dict[str, Any]) -> Finding:
    """SBS-ACS-002: Documented justification for API-Enabled authorizations."""
    access = _scope(raw, "access")
    if not access:
        return _na("SBS-ACS-002", "high")

    perm_sets = _total(access.get("elevated_permission_sets", {}))
    if perm_sets > 10:
        return Finding(
            "SBS-ACS-002",
            "fail",
            "high",
            f"{perm_sets} permission sets with elevated privileges — undocumented API access likely.",
            "Audit and document justification for all permission sets with ModifyAllData or ManageUsers.",
        )
    if perm_sets > 4:
        return Finding(
            "SBS-ACS-002",
            "partial",
            "high",
            f"{perm_sets} elevated permission sets — verify all are documented and justified.",
            "Ensure each elevated permission set has a documented business justification.",
        )
    return Finding(
        "SBS-ACS-002",
        "pass",
        "high",
        f"{perm_sets} elevated permission set(s) — within acceptable threshold.",
    )


def _rule_acs_003(raw: dict[str, Any]) -> Finding:
    """SBS-ACS-003: Justification for Approve Uninstalled Connected Apps."""
    access = _scope(raw, "access")
    if not access:
        return _na("SBS-ACS-003", "critical")

    apps = _records(access.get("connected_apps", {}))
    if not apps:
        return Finding(
            "SBS-ACS-003",
            "pass",
            "critical",
            "No connected apps found.",
        )

    unrestricted = [a for a in apps if not a.get("OptionsAllowAdminApprovedUsersOnly")]
    if len(unrestricted) == len(apps):
        return Finding(
            "SBS-ACS-003",
            "fail",
            "critical",
            f"All {len(apps)} connected app(s) allow non-admin-approved users.",
            "Restrict all connected apps to admin-approved users only via OAuth policy.",
        )
    if unrestricted:
        return Finding(
            "SBS-ACS-003",
            "partial",
            "critical",
            f"{len(unrestricted)}/{len(apps)} connected app(s) not restricted to admin-approved users.",
            "Apply admin-approved-users-only policy to all connected apps.",
        )
    return Finding(
        "SBS-ACS-003",
        "pass",
        "critical",
        f"All {len(apps)} connected app(s) restricted to admin-approved users.",
    )


def _rule_acs_004(raw: dict[str, Any]) -> Finding:
    """SBS-ACS-004: Justification for super admin-equivalent users."""
    access = _scope(raw, "access")
    if not access:
        return _na("SBS-ACS-004", "high")

    profiles = _records(access.get("admin_profiles", {}))
    super_admin = [p for p in profiles if p.get("PermissionsModifyAllData") and p.get("PermissionsManageUsers")]
    count = len(super_admin)
    if count > 2:
        return Finding(
            "SBS-ACS-004",
            "fail",
            "high",
            f"{count} profiles have both ModifyAllData and ManageUsers — super admin equivalent.",
            "Reduce to ≤2 super-admin-equivalent profiles with documented justification.",
        )
    if count > 0:
        return Finding(
            "SBS-ACS-004",
            "partial",
            "high",
            f"{count} super admin–equivalent profile(s) — verify documented justification exists.",
            "Document the business justification for each super-admin-equivalent profile.",
        )
    return Finding(
        "SBS-ACS-004",
        "pass",
        "high",
        "No profiles found with both ModifyAllData and ManageUsers.",
    )


def _rule_acs_structural(control_id: str, severity: str) -> Callable[[dict], Finding]:
    """Generate a structural partial rule for ACS controls requiring deeper audit."""

    def _rule(raw: dict[str, Any]) -> Finding:
        access = _scope(raw, "access")
        if not access:
            return _na(control_id, severity)
        return Finding(
            control_id,
            "partial",
            severity,
            "Access scope collected — full assessment requires detailed profile/permission set audit.",
            f"Run a detailed permission audit for {control_id} using Setup > Permission Set Analyzer.",
            needs_expert_review=True,
        )

    return _rule


# ---------------------------------------------------------------------------
# Assessment rules — Integrations
# ---------------------------------------------------------------------------


def _rule_int_002(raw: dict[str, Any]) -> Finding:
    """SBS-INT-002: Inventory and justification of Remote Site Settings."""
    integrations = _scope(raw, "integrations")
    if not integrations:
        return _na("SBS-INT-002", "moderate")

    sites = _records(integrations.get("remote_site_settings", {}))
    insecure = [s for s in sites if s.get("DisableProtocolSecurity") and s.get("IsActive")]
    inactive_insecure = [s for s in sites if s.get("DisableProtocolSecurity") and not s.get("IsActive")]

    if insecure:
        return Finding(
            "SBS-INT-002",
            "fail",
            "moderate",
            f"{len(insecure)} active remote site(s) have protocol security disabled.",
            "Enable protocol security on all active Remote Site Settings or remove unused entries.",
        )
    if inactive_insecure:
        return Finding(
            "SBS-INT-002",
            "partial",
            "moderate",
            f"{len(inactive_insecure)} inactive remote site(s) have protocol security disabled.",
            "Remove or remediate inactive remote sites with insecure protocol settings.",
        )
    total = len(sites)
    return Finding(
        "SBS-INT-002",
        "pass",
        "moderate",
        f"{total} remote site setting(s) — none with protocol security disabled.",
    )


def _rule_int_003(raw: dict[str, Any]) -> Finding:
    """SBS-INT-003: Inventory and justification of Named Credentials."""
    integrations = _scope(raw, "integrations")
    if not integrations:
        return _na("SBS-INT-003", "moderate")

    creds = _records(integrations.get("named_credentials", {}))
    if not creds:
        return Finding(
            "SBS-INT-003",
            "partial",
            "moderate",
            "No Named Credentials found — integrations may be using hardcoded credentials.",
            "Migrate integration credentials to Named Credentials to centralize and govern access.",
        )
    return Finding(
        "SBS-INT-003",
        "pass",
        "moderate",
        f"{len(creds)} Named Credential(s) found — managed integration credentials in use.",
    )


def _rule_int_004(raw: dict[str, Any]) -> Finding:
    """SBS-INT-004: Retain API Total Usage Event Logs for 30 days."""
    em = _scope(raw, "event-monitoring")
    if not em:
        return _na("SBS-INT-004", "high")

    log_types = _records(em.get("event_log_types", {}))
    unique_types = {r.get("EventType") for r in log_types if r.get("EventType")}

    if not unique_types:
        return Finding(
            "SBS-INT-004",
            "fail",
            "high",
            "No Event Log File types found in last 7 days — API event monitoring not active.",
            "Enable Event Monitoring in Setup > Event Manager and ensure API event types are captured.",
        )
    api_types = {t for t in unique_types if "API" in t.upper() or "REST" in t.upper()}
    if not api_types:
        return Finding(
            "SBS-INT-004",
            "partial",
            "high",
            f"{len(unique_types)} event type(s) found but no API-specific event types detected.",
            "Enable API event types (ApiEvent, RestApi) in Event Manager for full API telemetry.",
        )
    return Finding(
        "SBS-INT-004",
        "pass",
        "high",
        f"{len(api_types)} API event type(s) active: {', '.join(sorted(api_types))}.",
    )


# ---------------------------------------------------------------------------
# Assessment rules — OAuth Security
# ---------------------------------------------------------------------------


def _rule_oauth_001(raw: dict[str, Any]) -> Finding:
    """SBS-OAUTH-001: Require formal installation approval for Connected Apps."""
    oauth = _scope(raw, "oauth")
    if not oauth:
        return _na("SBS-OAUTH-001", "critical")

    policies = _records(oauth.get("connected_app_oauth_policies", {}))
    if not policies:
        return Finding("SBS-OAUTH-001", "pass", "critical", "No OAuth-enabled connected apps found.")

    open_access = [p for p in policies if p.get("PermittedUsersPolicyEnum", "") in ("AllUsers", "")]
    if len(open_access) == len(policies):
        return Finding(
            "SBS-OAUTH-001",
            "fail",
            "critical",
            f"All {len(policies)} connected app(s) allow all users — no formal installation control.",
            "Restrict all connected apps to admin-approved users or specific profiles/permission sets.",
        )
    if open_access:
        return Finding(
            "SBS-OAUTH-001",
            "partial",
            "critical",
            f"{len(open_access)}/{len(policies)} connected app(s) permit all users.",
            "Apply admin-approved-only policy to all connected apps.",
        )
    return Finding(
        "SBS-OAUTH-001",
        "pass",
        "critical",
        f"All {len(policies)} connected app(s) have controlled access policies.",
    )


def _rule_oauth_002(raw: dict[str, Any]) -> Finding:
    """SBS-OAUTH-002: Require profile/permission set access for Connected Apps."""
    oauth = _scope(raw, "oauth")
    if not oauth:
        return _na("SBS-OAUTH-002", "critical")

    policies = _records(oauth.get("connected_app_oauth_policies", {}))
    if not policies:
        return Finding("SBS-OAUTH-002", "pass", "critical", "No OAuth-enabled connected apps found.")

    unrestricted = [p for p in policies if not p.get("OptionsAllowAdminApprovedUsersOnly")]
    if len(unrestricted) == len(policies):
        return Finding(
            "SBS-OAUTH-002",
            "fail",
            "critical",
            f"All {len(policies)} connected app(s) not restricted to admin-approved users.",
            "Enable 'Admin approved users are pre-authorized' on all connected apps.",
        )
    if unrestricted:
        return Finding(
            "SBS-OAUTH-002",
            "partial",
            "critical",
            f"{len(unrestricted)}/{len(policies)} connected app(s) lack admin-approved restriction.",
            "Apply admin-approved-users policy to all remaining connected apps.",
        )
    return Finding(
        "SBS-OAUTH-002",
        "pass",
        "critical",
        f"All {len(policies)} connected app(s) restricted to admin-approved users.",
    )


def _rule_oauth_structural(control_id: str, severity: str) -> Callable[[dict], Finding]:
    """Generate a structural partial rule for OAuth controls requiring manual review."""

    def _rule(raw: dict[str, Any]) -> Finding:
        oauth = _scope(raw, "oauth")
        if not oauth:
            return _na(control_id, severity)
        return Finding(
            control_id,
            "partial",
            severity,
            "OAuth scope collected — full assessment requires manual classification and documentation.",
            f"Complete manual assessment for {control_id} per the SBS runbook.",
            needs_expert_review=True,
        )

    return _rule


# ---------------------------------------------------------------------------
# Assessment rules — Data Security
# ---------------------------------------------------------------------------


def _rule_data_004(raw: dict[str, Any]) -> Finding:
    """SBS-DATA-004: Require field history tracking for sensitive fields."""
    em = _scope(raw, "event-monitoring")
    if not em:
        return _na("SBS-DATA-004", "high")

    tracked = _total(em.get("field_history_retention", {}))
    if tracked == 0:
        return Finding(
            "SBS-DATA-004",
            "fail",
            "high",
            "No fields with history tracking enabled found.",
            "Enable Field History Tracking on sensitive fields in object field settings.",
        )
    if tracked < 10:
        return Finding(
            "SBS-DATA-004",
            "partial",
            "high",
            f"Only {tracked} tracked field(s) — coverage may be insufficient for sensitive data.",
            "Review all objects containing PII/regulated data and enable Field History Tracking.",
        )
    return Finding(
        "SBS-DATA-004",
        "pass",
        "high",
        f"{tracked} field(s) with history tracking enabled.",
    )


def _rule_data_structural(control_id: str, severity: str) -> Callable[[dict], Finding]:
    """Structural partial for data controls requiring field-level inventory."""

    def _rule(_raw: dict[str, Any]) -> Finding:
        return Finding(
            control_id,
            "partial",
            severity,
            "Data security controls require field-level inventory — not available via sfdc-connect.",
            f"Complete {control_id} assessment via Setup > Data Classification or a custom SOQL audit.",
            needs_expert_review=True,
        )

    return _rule


# ---------------------------------------------------------------------------
# Assessment rules — Security Configuration
# ---------------------------------------------------------------------------


def _rule_secconf_001(raw: dict[str, Any]) -> Finding:
    """SBS-SECCONF-001: Establish a Salesforce Health Check Baseline."""
    secconf = _scope(raw, "secconf")
    if not secconf:
        return _na("SBS-SECCONF-001", "high")

    hc = secconf.get("health_check", {})
    if isinstance(hc, dict) and "note" in hc:
        return Finding(
            "SBS-SECCONF-001",
            "partial",
            "high",
            "Health Check not available via SOQL — check manually in Setup > Security Health Check.",
            "Review Security Health Check in the Salesforce UI and establish a documented baseline.",
        )
    records = _records(hc)
    if not records:
        return Finding(
            "SBS-SECCONF-001",
            "partial",
            "high",
            "Health Check score could not be retrieved via API.",
            "Verify Health Check is accessible and document the baseline score.",
        )
    score = records[0].get("Score", 0)
    if score < 50:
        return Finding(
            "SBS-SECCONF-001",
            "fail",
            "high",
            f"Health Check score: {score}/100 — critically below baseline.",
            "Address all Health Check findings in Setup > Security Health Check immediately.",
        )
    if score < 80:
        return Finding(
            "SBS-SECCONF-001",
            "partial",
            "high",
            f"Health Check score: {score}/100 — below recommended 80% threshold.",
            "Remediate Health Check findings to reach ≥80% score.",
        )
    return Finding(
        "SBS-SECCONF-001",
        "pass",
        "high",
        f"Health Check score: {score}/100.",
    )


def _rule_secconf_002(raw: dict[str, Any]) -> Finding:
    """SBS-SECCONF-002: Review and remediate Health Check deviations."""
    # Re-uses health check data; status driven by score thresholds
    secconf = _scope(raw, "secconf")
    if not secconf:
        return _na("SBS-SECCONF-002", "high")

    hc = secconf.get("health_check", {})
    records = _records(hc)
    if not records:
        return Finding(
            "SBS-SECCONF-002",
            "partial",
            "high",
            "Health Check deviations cannot be enumerated via API — manual review required.",
            "Review and remediate each Health Check deviation in Setup > Security Health Check.",
        )
    score = records[0].get("Score", 0)
    if score < 50:
        return Finding(
            "SBS-SECCONF-002",
            "fail",
            "high",
            f"Health Check score {score}/100 indicates unaddressed critical deviations.",
            "Resolve all failing Health Check items — prioritise Critical and High risk items.",
        )
    if score < 80:
        return Finding(
            "SBS-SECCONF-002",
            "partial",
            "high",
            f"Health Check score {score}/100 — some deviations remain unaddressed.",
            "Continue remediating Health Check findings until score reaches ≥80%.",
        )
    return Finding(
        "SBS-SECCONF-002",
        "pass",
        "high",
        f"Health Check score {score}/100 — deviations within acceptable range.",
    )


# ---------------------------------------------------------------------------
# Assessment rules — Transaction Security / Deployments
# ---------------------------------------------------------------------------


def _rule_dep_003(raw: dict[str, Any]) -> Finding:
    """SBS-DEP-003: Monitor and alert on unauthorised high-risk metadata changes."""
    ts = _scope(raw, "transaction-security")
    if not ts:
        return _na("SBS-DEP-003", "high")

    policies = _records(ts.get("policies", {}))
    if not policies:
        return Finding(
            "SBS-DEP-003",
            "fail",
            "high",
            "No Transaction Security Policies found — no automated threat response configured.",
            "Create Transaction Security Policies in Setup > Transaction Security to monitor high-risk events.",
        )
    enabled = [p for p in policies if p.get("IsEnabled")]
    if not enabled:
        return Finding(
            "SBS-DEP-003",
            "partial",
            "high",
            f"{len(policies)} Transaction Security Polic(ies) found but none enabled.",
            "Enable relevant Transaction Security Policies to enforce automated threat response.",
        )
    return Finding(
        "SBS-DEP-003",
        "pass",
        "high",
        f"{len(enabled)}/{len(policies)} Transaction Security Polic(ies) active.",
    )


def _rule_not_collectable(control_id: str, severity: str, reason: str) -> Callable[[dict], Finding]:
    """Generate a not_applicable rule for controls outside sfdc-connect scope."""

    def _rule(_raw: dict[str, Any]) -> Finding:
        return _na(control_id, severity, reason)

    return _rule


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

_CODE_NA = "Requires source code review — not assessable via Salesforce API"
_PORTAL_NA = "Requires Apex/LWC code audit — not assessable via Salesforce API"
_DEP_NA = "Requires CI/CD and source repository audit — not assessable via Salesforce API"
_FILE_NA = "Requires manual content link review — not assessable via Salesforce API"
_FDNS_NA = "Foundational governance control — requires manual programme review"

RULES: dict[str, Callable[[dict[str, Any]], Finding]] = {
    # Authentication
    "SBS-AUTH-001": _rule_auth_001,
    "SBS-AUTH-002": _rule_auth_002,
    "SBS-AUTH-003": _rule_auth_003,
    "SBS-AUTH-004": _rule_auth_004,
    # Access Controls
    "SBS-ACS-001": _rule_acs_001,
    "SBS-ACS-002": _rule_acs_002,
    "SBS-ACS-003": _rule_acs_003,
    "SBS-ACS-004": _rule_acs_004,
    "SBS-ACS-005": _rule_acs_structural("SBS-ACS-005", "high"),
    "SBS-ACS-006": _rule_acs_structural("SBS-ACS-006", "critical"),
    "SBS-ACS-007": _rule_acs_structural("SBS-ACS-007", "high"),
    "SBS-ACS-008": _rule_acs_structural("SBS-ACS-008", "high"),
    "SBS-ACS-009": _rule_acs_structural("SBS-ACS-009", "moderate"),
    "SBS-ACS-010": _rule_acs_structural("SBS-ACS-010", "moderate"),
    "SBS-ACS-011": _rule_acs_structural("SBS-ACS-011", "high"),
    "SBS-ACS-012": _rule_acs_structural("SBS-ACS-012", "moderate"),
    # Integrations
    "SBS-INT-001": _rule_not_collectable(
        "SBS-INT-001", "moderate", "Browser extension inventory requires manual review"
    ),
    "SBS-INT-002": _rule_int_002,
    "SBS-INT-003": _rule_int_003,
    "SBS-INT-004": _rule_int_004,
    # OAuth Security
    "SBS-OAUTH-001": _rule_oauth_001,
    "SBS-OAUTH-002": _rule_oauth_002,
    "SBS-OAUTH-003": _rule_oauth_structural("SBS-OAUTH-003", "high"),
    "SBS-OAUTH-004": _rule_oauth_structural("SBS-OAUTH-004", "moderate"),
    # Data Security
    "SBS-DATA-001": _rule_data_structural("SBS-DATA-001", "high"),
    "SBS-DATA-002": _rule_data_structural("SBS-DATA-002", "moderate"),
    "SBS-DATA-003": _rule_data_structural("SBS-DATA-003", "high"),
    "SBS-DATA-004": _rule_data_004,
    # Security Configuration
    "SBS-SECCONF-001": _rule_secconf_001,
    "SBS-SECCONF-002": _rule_secconf_002,
    # Deployments
    "SBS-DEP-001": _rule_not_collectable("SBS-DEP-001", "high", _DEP_NA),
    "SBS-DEP-002": _rule_not_collectable("SBS-DEP-002", "high", _DEP_NA),
    "SBS-DEP-003": _rule_dep_003,
    "SBS-DEP-005": _rule_not_collectable("SBS-DEP-005", "critical", _DEP_NA),
    "SBS-DEP-006": _rule_not_collectable("SBS-DEP-006", "high", _DEP_NA),
    # Code Security
    "SBS-CODE-001": _rule_not_collectable("SBS-CODE-001", "moderate", _CODE_NA),
    "SBS-CODE-002": _rule_not_collectable("SBS-CODE-002", "moderate", _CODE_NA),
    "SBS-CODE-003": _rule_not_collectable("SBS-CODE-003", "high", _CODE_NA),
    "SBS-CODE-004": _rule_not_collectable("SBS-CODE-004", "critical", _CODE_NA),
    # Customer Portals
    "SBS-CPORTAL-001": _rule_not_collectable("SBS-CPORTAL-001", "critical", _PORTAL_NA),
    "SBS-CPORTAL-002": _rule_not_collectable("SBS-CPORTAL-002", "critical", _PORTAL_NA),
    # File Security
    "SBS-FILE-001": _rule_not_collectable("SBS-FILE-001", "moderate", _FILE_NA),
    "SBS-FILE-002": _rule_not_collectable("SBS-FILE-002", "moderate", _FILE_NA),
    "SBS-FILE-003": _rule_not_collectable("SBS-FILE-003", "moderate", _FILE_NA),
    # Foundations
    "SBS-FDNS-001": _rule_not_collectable("SBS-FDNS-001", "moderate", _FDNS_NA),
}


# ---------------------------------------------------------------------------
# Dry-run stub data (realistic weak org — ~40% pass, 30% partial, 30% fail)
# ---------------------------------------------------------------------------

_DRY_RUN_OVERRIDES: dict[str, tuple[str, str, str]] = {
    # (status, observed_value, remediation)
    "SBS-AUTH-001": ("fail", "No SSO providers configured [dry-run]", "Configure org-wide SSO."),
    "SBS-AUTH-002": ("partial", "SSO not configured — bypass governance N/A [dry-run]", ""),
    "SBS-AUTH-003": ("fail", "No Login IP Ranges found [dry-run]", "Add Login IP Ranges to privileged profiles."),
    "SBS-AUTH-004": (
        "partial",
        "MFA org settings unconfirmed [dry-run]",
        "Verify MFA in Setup > Identity Verification.",
    ),
    "SBS-ACS-001": ("fail", "8 admin profiles with ModifyAllData [dry-run]", "Reduce to ≤2 admin profiles."),
    "SBS-ACS-002": ("partial", "6 elevated permission sets [dry-run]", "Document justification for all elevated sets."),
    "SBS-ACS-003": ("fail", "All 4 connected apps allow all users [dry-run]", "Apply admin-approved policy."),
    "SBS-ACS-004": ("partial", "2 super admin-equivalent profiles [dry-run]", "Document justification."),
    "SBS-ACS-005": ("partial", "Requires profile audit [dry-run]", "Run detailed profile review."),
    "SBS-ACS-006": ("partial", "Requires permission set audit [dry-run]", "Audit Use Any API Client grants."),
    "SBS-ACS-007": ("partial", "Non-human identity inventory required [dry-run]", "Build NHI inventory."),
    "SBS-ACS-008": ("partial", "NHI privilege scope requires audit [dry-run]", "Restrict NHI permissions."),
    "SBS-ACS-009": ("partial", "Compensating controls require manual review [dry-run]", ""),
    "SBS-ACS-010": ("fail", "No access review process evidence found [dry-run]", "Implement quarterly access reviews."),
    "SBS-ACS-011": (
        "partial",
        "Change governance process requires verification [dry-run]",
        "Implement change approval workflow for access changes.",
    ),
    "SBS-ACS-012": ("partial", "Login hour restrictions require profile audit [dry-run]", ""),
    "SBS-INT-002": (
        "fail",
        "3 active remote sites have protocol security disabled [dry-run]",
        "Enable protocol security.",
    ),
    "SBS-INT-003": ("pass", "12 Named Credentials found [dry-run]", ""),
    "SBS-INT-004": ("partial", "5 event types found but no API-specific types [dry-run]", "Enable ApiEvent type."),
    "SBS-OAUTH-001": ("fail", "3 connected apps allow all users [dry-run]", "Restrict to admin-approved."),
    "SBS-OAUTH-002": ("partial", "2/5 apps lack admin-approved restriction [dry-run]", "Apply policy to all apps."),
    "SBS-OAUTH-003": ("partial", "Criticality classification not documented [dry-run]", "Classify all connected apps."),
    "SBS-OAUTH-004": (
        "partial",
        "Vendor due diligence documentation missing [dry-run]",
        "Complete vendor assessments.",
    ),
    "SBS-DATA-001": ("partial", "Field scan required [dry-run]", "Run data classification scan."),
    "SBS-DATA-002": ("partial", "Field inventory requires SOQL audit [dry-run]", ""),
    "SBS-DATA-003": ("partial", "Backup process not verifiable via API [dry-run]", "Verify backup schedule."),
    "SBS-DATA-004": ("fail", "0 fields with history tracking enabled [dry-run]", "Enable field history tracking."),
    "SBS-SECCONF-001": ("partial", "Health Check score: 64/100 [dry-run]", "Remediate to reach ≥80%."),
    "SBS-SECCONF-002": ("partial", "Score 64/100 — deviations remain [dry-run]", "Address all failing items."),
    "SBS-DEP-003": ("fail", "No Transaction Security Policies found [dry-run]", "Create TSPs for high-risk events."),
    "SBS-CODE-003": (
        "partial",
        "Apex logging requires code audit [dry-run]",
        "Implement Platform Event or custom Apex logging framework.",
    ),
    "SBS-CODE-004": ("fail", "Sensitive data in logs cannot be ruled out [dry-run]", "Audit all Apex log statements."),
}

# Controls not overridden above keep their not_applicable status from the rule.
# A few we want to show as passing in the dry-run:
_DRY_RUN_PASS = {"SBS-INT-003"}

# Controls that require sfdc-expert Apex/admin analysis — too deep for REST/SOQL alone.
_EXPERT_ELIGIBLE: frozenset[str] = frozenset(
    {
        "SBS-ACS-005",
        "SBS-ACS-006",
        "SBS-ACS-007",
        "SBS-ACS-008",
        "SBS-ACS-009",
        "SBS-ACS-010",
        "SBS-ACS-011",
        "SBS-ACS-012",
        "SBS-OAUTH-003",
        "SBS-OAUTH-004",
        "SBS-DATA-001",
        "SBS-DATA-002",
        "SBS-DATA-003",
    }
)


# ---------------------------------------------------------------------------
# Workday (WSCC / SSCF) dry-run stubs
# ---------------------------------------------------------------------------

_WD_DRY_RUN_OVERRIDES: dict[str, tuple[str, str, str]] = {
    # (status, observed_value, remediation)
    "SSCF-CON-001": (
        "partial",
        "Workday security baseline partially applied [dry-run]",
        "Complete baseline enforcement per ISSG hardening guide.",
    ),
    "SSCF-CON-002": (
        "partial",
        "No automated drift detection configured [dry-run]",
        "Implement scheduled SOAP audit comparison against approved baseline.",
    ),
    "SSCF-CON-003": (
        "fail",
        "Service account tokens lack rotation policy [dry-run]",
        "Enforce 90-day ISU credential rotation via Workday security policy.",
    ),
    "SSCF-CON-004": (
        "partial",
        "ISU hardening partially complete — 4 ISUs lack domain restrictions [dry-run]",
        "Apply domain restrictions and constrained ISSG permissions to all ISUs.",
    ),
    "SSCF-CON-005": (
        "partial",
        "17 integrations found; 8 lack documented security review [dry-run]",
        "Complete vendor security review for all active integrations.",
    ),
    "SSCF-DSP-001": (
        "fail",
        "HR sensitive data accessible to 34 non-HR security groups [dry-run]",
        "Restrict domain data access policies to HR-only security groups.",
    ),
    "SSCF-DSP-002": (
        "fail",
        "RaaS reports allow unrestricted data export without approval [dry-run]",
        "Apply report sharing restrictions; require approval for sensitive RaaS exports.",
    ),
    "SSCF-DSP-003": (
        "partial",
        "Data classification schema defined; field mapping 60% complete [dry-run]",
        "Complete classification mapping for remaining worker and payroll data objects.",
    ),
    "SSCF-DSP-004": (
        "partial",
        "GDPR data residency configuration incomplete for EU tenant [dry-run]",
        "Configure data residency controls and validate cross-border transfer agreements.",
    ),
    "SSCF-DSP-005": (
        "partial",
        "Retention schedules defined; purge automation not configured [dry-run]",
        "Implement automated data purge for expired retention periods.",
    ),
    "SSCF-IAM-001": (
        "fail",
        "SSO configured but MFA bypass allowed for 6 service accounts [dry-run]",
        "Enforce MFA for all accounts including ISUs via Workday authentication policy.",
    ),
    "SSCF-IAM-002": (
        "fail",
        "22 ISU accounts provisioned without formal approval workflow [dry-run]",
        "Implement request-approve workflow for all ISU provisioning in ServiceNow.",
    ),
    "SSCF-IAM-003": (
        "partial",
        "SSO enforced for workforce; 3 integration users bypass federation [dry-run]",
        "Migrate remaining integration users to OAuth 2.0 with IdP federation.",
    ),
    "SSCF-IAM-004": (
        "partial",
        "Automated deprovisioning configured; 14 stale accounts detected [dry-run]",
        "Remediate stale accounts; validate termination trigger from HRIS.",
    ),
    "SSCF-IAM-005": (
        "fail",
        "ISU inventory incomplete; 9 ISUs have no documented owner [dry-run]",
        "Complete ISU inventory; assign named business owner to each ISU.",
    ),
    "SSCF-IAM-006": (
        "partial",
        "Session timeout set to 8 hours — policy requires ≤4 hours [dry-run]",
        "Update Workday session timeout policy to 4-hour maximum.",
    ),
    "SSCF-IAM-007": (
        "partial",
        "No JIT workflow configured for temporary privileged role elevation [dry-run]",
        "Implement time-bound role assignment via PAM tool integration.",
    ),
    "SSCF-IAM-008": (
        "partial",
        "Contractor access active; no quarterly recertification cycle enforced [dry-run]",
        "Enable quarterly access review campaign for all external user accounts.",
    ),
    "SSCF-IPY-001": ("pass", "PRISM reports and RaaS exports confirm open data portability [dry-run]", ""),
    "SSCF-IPY-002": (
        "partial",
        "REST API enabled; no rate limiting or throttle policy configured [dry-run]",
        "Configure Workday REST API rate limiting and input validation policies.",
    ),
    "SSCF-IPY-003": (
        "partial",
        "Integration inventory 70% complete; 5 undocumented integrations found [dry-run]",
        "Complete integration registry and assign risk classification to each connector.",
    ),
    "SSCF-LOG-001": (
        "fail",
        "Workday audit logs not forwarded to SIEM [dry-run]",
        "Configure Workday audit log streaming to SIEM via syslog or API forwarder.",
    ),
    "SSCF-LOG-002": (
        "partial",
        "Admin activity logged; configuration change events not captured [dry-run]",
        "Enable configuration change audit trail in Workday tenant settings.",
    ),
    "SSCF-LOG-003": (
        "partial",
        "90-day log retention in Workday; policy requires 365 days [dry-run]",
        "Export logs to long-term storage to meet 365-day retention requirement.",
    ),
    "SSCF-LOG-004": (
        "fail",
        "No real-time alerting configured for high-risk Workday events [dry-run]",
        "Define and deploy Workday notification rules for privileged access and bulk exports.",
    ),
    "SSCF-LOG-005": (
        "fail",
        "Workday not integrated with SIEM for cross-platform correlation [dry-run]",
        "Integrate Workday audit logs with SIEM using REST API or syslog connector.",
    ),
    "SSCF-SEF-001": (
        "partial",
        "No Workday-specific threat detection policies defined [dry-run]",
        "Define automated security policies for bulk data export and off-hours access events.",
    ),
    "SSCF-SEF-002": (
        "partial",
        "Alerting SLA not documented for Workday security events [dry-run]",
        "Document triage SLA for Workday-sourced alerts in SOC runbook.",
    ),
    "SSCF-SEF-003": (
        "partial",
        "IR plan exists but lacks Workday-specific runbooks [dry-run]",
        "Add Workday incident scenarios to IR plan and conduct annual tabletop.",
    ),
    "SSCF-SEF-005": (
        "partial",
        "Exception process not documented for Workday control deviations [dry-run]",
        "Define exception governance procedure and register active Workday exceptions.",
    ),
}

# WSCC profile control IDs (30 controls — SSCF subset)
_WSCC_CONTROL_IDS: list[str] = [
    "SSCF-CON-001",
    "SSCF-CON-002",
    "SSCF-CON-003",
    "SSCF-CON-004",
    "SSCF-CON-005",
    "SSCF-DSP-001",
    "SSCF-DSP-002",
    "SSCF-DSP-003",
    "SSCF-DSP-004",
    "SSCF-DSP-005",
    "SSCF-IAM-001",
    "SSCF-IAM-002",
    "SSCF-IAM-003",
    "SSCF-IAM-004",
    "SSCF-IAM-005",
    "SSCF-IAM-006",
    "SSCF-IAM-007",
    "SSCF-IAM-008",
    "SSCF-IPY-001",
    "SSCF-IPY-002",
    "SSCF-IPY-003",
    "SSCF-LOG-001",
    "SSCF-LOG-002",
    "SSCF-LOG-003",
    "SSCF-LOG-004",
    "SSCF-LOG-005",
    "SSCF-SEF-001",
    "SSCF-SEF-002",
    "SSCF-SEF-003",
    "SSCF-SEF-005",
]


def _load_sscf_index(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Load sscf_control_index.yaml; return dict keyed by sscf_control_id."""
    index_path = repo_root / "config" / "sscf_control_index.yaml"
    with index_path.open() as fh:
        data = yaml.safe_load(fh)
    return {c["sscf_control_id"]: c for c in data.get("controls", [])}


def run_workday_assessment(_org: str, env: str, sscf_index: dict[str, Any]) -> list[dict[str, Any]]:
    """Produce Workday (WSCC) dry-run findings using SSCF control IDs."""
    assessed_dt = datetime.now(UTC)
    date_str = assessed_dt.strftime("%Y-%m-%d")
    findings = []

    for cid in _WSCC_CONTROL_IDS:
        ctrl = sscf_index.get(cid, {})
        severity = ctrl.get("severity", "moderate").lower()
        override = _WD_DRY_RUN_OVERRIDES.get(cid)
        if override:
            status, observed, remediation = override
        else:
            status, observed, remediation = "not_applicable", "Not collected in dry-run", ""

        d = {
            "control_id": cid,
            "status": status,
            "severity": severity,
            "owner": ctrl.get("owner_team", "security_engineering").replace("_", " ").title(),
            "observed_value": observed,
            "remediation": remediation,
            "evidence_ref": f"collector://workday/{env}/{cid}/snapshot-{date_str}",
            "due_date": _auto_due_date(severity, status, assessed_dt),
        }
        findings.append(d)

    return findings


# ---------------------------------------------------------------------------
# Core assessment logic
# ---------------------------------------------------------------------------


def _load_controls(controls_path: Path) -> list[dict[str, Any]]:
    """Load SBS controls catalog and return the controls list."""
    data = json.loads(controls_path.read_text())
    return data.get("controls", [])


def run_assessment(
    raw: dict[str, Any] | None,
    controls: list[dict[str, Any]],
    dry_run: bool,
    org: str,
    env: str,
) -> list[dict[str, Any]]:
    """Apply rules to all known controls and return serialised findings."""
    assessed_dt = datetime.now(UTC)
    date_str = assessed_dt.strftime("%Y-%m-%d")
    findings = []

    for control in controls:
        cid = control.get("control_id", "")
        severity = (control.get("risk_level") or "moderate").lower()

        rule = RULES.get(cid)
        if rule is None:
            finding = _na(cid, severity, "No assessment rule defined")
        elif dry_run:
            override = _DRY_RUN_OVERRIDES.get(cid)
            if override:
                status, observed, remediation = override
                finding = Finding(
                    control_id=cid,
                    status=status,
                    severity=severity,
                    observed_value=observed,
                    remediation=remediation,
                    needs_expert_review=cid in _EXPERT_ELIGIBLE,
                )
            else:
                # Fall through to the real rule with empty raw (will produce not_applicable)
                finding = rule({})
        else:
            finding = rule(raw or {})

        d = finding.to_dict(org, env, date_str)
        # Auto-populate due_date for all actionable findings (Issue #10 — NIST MANAGE-BLOCK)
        if not d.get("due_date"):
            d["due_date"] = _auto_due_date(d["severity"], d["status"], assessed_dt)
        findings.append(d)

    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """oscal-assess — deterministic SBS control assessor for Salesforce orgs."""


@cli.command()
@click.option(
    "--collector-output",
    default=None,
    help="Path to sfdc-connect JSON output (required unless --dry-run).",
)
@click.option(
    "--controls",
    "controls_path",
    default="docs/oscal-salesforce-poc/generated/sbs_controls.json",
    show_default=True,
    help="Path to imported SBS controls catalog JSON.",
)
@click.option("--out", default=None, help="Output path for gap-analysis JSON (default: stdout).")
@click.option(
    "--env",
    default="dev",
    type=click.Choice(["dev", "test", "prod"]),
    show_default=True,
    help="Environment label.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Emit realistic stub findings (weak-org scenario) without connecting to the platform.",
)
@click.option(
    "--platform",
    type=click.Choice(["salesforce", "workday"]),
    default="salesforce",
    show_default=True,
    help="Platform to assess — determines control catalog and rule set.",
)
@click.option(
    "--assessment-owner",
    "assessment_owner",
    default="SaaS Security Architect",
    help="Named individual responsible for this assessment (e.g. 'Jane Smith'). "
    "Required for NIST GOVERN compliance. Defaults to 'SaaS Security Architect'.",
)
def assess(  # NOSONAR
    collector_output: str | None,
    controls_path: str,
    out: str | None,
    env: str,
    dry_run: bool,
    platform: str,
    assessment_owner: str | None,
) -> None:
    """Assess org configuration against SBS (Salesforce) or WSCC (Workday) controls.

    Input: platform collector output JSON (--scope all / workday-connect output).
    Output: gap-analysis JSON for scripts/oscal_gap_map.py.
    """
    repo_root = Path(__file__).resolve().parents[2]
    org_label = "dry-run"

    # ── Workday path ─────────────────────────────────────────────────────────
    if platform == "workday":
        click.echo(f"  platform=workday {'[DRY RUN]' if dry_run else ''}", err=True)
        if not dry_run and not collector_output:
            click.echo("ERROR: --collector-output is required unless --dry-run is set.", err=True)
            sys.exit(1)
        if not dry_run and collector_output:
            collector_path = (repo_root / collector_output).resolve()
            collector_data = json.loads(collector_path.read_text())
            org_label = collector_data.get("org", "unknown")
        sscf_index = _load_sscf_index(repo_root)
        findings = run_workday_assessment(org_label, env, sscf_index)
        platform_prefix = "wd"
    else:
        # ── Salesforce path ───────────────────────────────────────────────────
        resolved_controls = (repo_root / controls_path).resolve()
        if not resolved_controls.exists():
            click.echo(f"ERROR: controls file not found: {resolved_controls}", err=True)
            sys.exit(1)

        raw: dict[str, Any] | None = None

        if dry_run:
            click.echo("DRY RUN — emitting weak-org stub findings.", err=True)
        else:
            if not collector_output:
                click.echo("ERROR: --collector-output is required unless --dry-run is set.", err=True)
                sys.exit(1)
            collector_path = (repo_root / collector_output).resolve()
            if not collector_path.exists():
                click.echo(f"ERROR: collector output not found: {collector_path}", err=True)
                sys.exit(1)
            collector_data = json.loads(collector_path.read_text())
            raw = collector_data.get("raw", collector_data)
            org_label = collector_data.get("org", "unknown")
            click.echo(f"  assessing org: {org_label} env: {env}", err=True)

        controls = _load_controls(resolved_controls)
        click.echo(f"  loaded {len(controls)} SBS controls from catalog", err=True)
        findings = run_assessment(raw, controls, dry_run, org_label, env)
        platform_prefix = "sfdc"

    status_counts: dict[str, int] = {}
    for f in findings:
        status_counts[f["status"]] = status_counts.get(f["status"], 0) + 1
    click.echo(f"  assessed {len(findings)} controls: {status_counts}", err=True)

    assessment_id = (
        f"{platform_prefix}-assess-dry-run-{env}-{datetime.now(UTC).strftime('%Y%m%d')}"
        if dry_run
        else f"{platform_prefix}-assess-{org_label.split('.')[0]}-{env}-{datetime.now(UTC).strftime('%Y%m%d')}"
    )

    payload = {
        "assessment_id": assessment_id,
        "assessed_at_utc": datetime.now(UTC).isoformat(),
        "org": org_label,
        "platform": platform,
        "env": env,
        # Issue #12 — NIST GOVERN-PARTIAL: named individual accountable for the assessment
        "assessment_owner": _normalize_assessment_owner(assessment_owner),
        # Issue #11 — NIST MAP-BLOCK: declare collection mode with compliant enum values
        "data_source": _normalize_data_source(dry_run),
        "ai_generated_findings_notice": (
            "Findings are AI-generated assessments derived from sfdc-connect API data. "
            "Human verification is required before delivery to governance stakeholders."
        ),
        "findings": findings,
    }

    output = json.dumps(payload, indent=2)
    if out:
        out_path = (repo_root / out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output)
        click.echo(f"  wrote {len(findings)} findings → {out_path}", err=True)
    else:
        click.echo(output)


if __name__ == "__main__":
    cli()
