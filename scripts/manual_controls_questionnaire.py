#!/usr/bin/env python3
"""
manual_controls_questionnaire.py — Manual intake for controls that cannot be
assessed via the Salesforce REST/SOQL API.

Covers the 15 not_applicable controls produced by oscal-assess:
  Code Security  : SBS-CODE-001/002/003/004
  Customer Portal: SBS-CPORTAL-001/002
  Deployments    : SBS-DEP-001/002/005/006
  File Security  : SBS-FILE-001/002/003
  Foundations    : SBS-FDNS-001
  Integrations   : SBS-INT-001

Usage:
    # Interactive
    python3 scripts/manual_controls_questionnaire.py --org cyber-coach-dev --env dev

    # Non-interactive (pre-filled answers JSON)
    python3 scripts/manual_controls_questionnaire.py --org cyber-coach-dev --answers answers.json

    # Merge results back into gap_analysis.json produced by oscal-assess
    python3 scripts/manual_controls_questionnaire.py --org cyber-coach-dev \\
        --merge docs/oscal-salesforce-poc/generated/cyber-coach-dev/2026-03-03/gap_analysis.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Due-date SLA (mirrors oscal_assess logic)
# ---------------------------------------------------------------------------

_DUE_DATE_DAYS: dict[str, int] = {
    "critical": 7,
    "high": 30,
    "moderate": 90,
    "low": 180,
}


def _due_date(severity: str, status: str, assessed_dt: datetime) -> str:
    if status not in ("fail", "partial"):
        return ""
    days = _DUE_DATE_DAYS.get(severity.lower(), 90)
    return (assessed_dt + timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Status options
# ---------------------------------------------------------------------------

# Maps a short answer token → gap_analysis status
_STATUS_MAP = {
    "yes": "pass",
    "partial": "partial",
    "no": "fail",
    "na": "not_applicable",
}

_STATUS_LABELS = {
    "yes": "Yes — fully implemented",
    "partial": "Partial — in progress or incomplete",
    "no": "No — not implemented",
    "na": "Not applicable — does not apply to this org",
}


# ---------------------------------------------------------------------------
# Control question definitions
# ---------------------------------------------------------------------------


@dataclass
class ControlQuestion:
    control_id: str
    severity: str
    title: str
    description: str  # one-line context for the respondent
    status_question: str  # the yes/partial/no question
    status_options: list[str]  # subset of yes/partial/no/na
    tool_question: str  # "which tool or process?"
    evidence_question: str  # "evidence reference (URL / ticket / path):"
    remediations: dict[str, str]  # status → remediation text
    observed_templates: dict[str, str]  # status → observed_value template ("{tool}" substituted)
    na_allowed_reason: str = ""  # shown when na is in options


CONTROLS: list[ControlQuestion] = [
    # ── Code Security ───────────────────────────────────────────────────────
    ControlQuestion(
        control_id="SBS-CODE-001",
        severity="moderate",
        title="Mandatory Peer Review for Salesforce Code Changes",
        description="Source control must require ≥1 peer reviewer for all Apex/LWC/metadata PRs before merge.",
        status_question="Is peer review enforced for all Apex, LWC, and metadata changes via branch protection?",
        status_options=["yes", "partial", "no"],
        tool_question="Which platform enforces this? (e.g. GitHub branch protection, Bitbucket, Azure DevOps):",
        evidence_question="Evidence reference (URL to branch protection settings, screenshot path, or ticket):",
        remediations={
            "partial": (
                "Enable mandatory PR reviews on all branches that deploy to production. "
                "Require ≥1 reviewer dismissal when code is pushed post-approval."
            ),
            "fail": (
                "Configure branch protection rules to require ≥1 peer reviewer for all Apex, LWC, "
                "and metadata changes. Block direct pushes to main/master."
            ),
        },
        observed_templates={
            "pass": "Peer review enforced via {tool}.",
            "partial": "Peer review partially enforced via {tool} — coverage gaps remain.",
            "fail": "No peer review enforcement found for Salesforce code changes.",
        },
    ),
    ControlQuestion(
        control_id="SBS-CODE-002",
        severity="moderate",
        title="Pre-Merge Static Code Analysis for Apex and LWC",
        description="SAST must run on every PR and block merge on HIGH/CRITICAL findings.",
        status_question="Does SAST run on every PR and block merges on high/critical security findings?",
        status_options=["yes", "partial", "no"],
        tool_question=("Which tool? (e.g. Salesforce Code Analyzer, PMD, CodeClimate, SonarQube, other):"),
        evidence_question="Evidence reference (CI config path, tool dashboard URL, or ticket):",
        remediations={
            "partial": (
                "Ensure SAST runs on every PR and is configured to block merge on HIGH/CRITICAL findings. "
                "Review ruleset coverage for Apex-specific security rules (CRUD/FLS, SOQL injection)."
            ),
            "fail": (
                "Implement SAST in the CI/CD pipeline using Salesforce Code Analyzer or equivalent. "
                "Configure to run on every PR and block merge on HIGH/CRITICAL findings."
            ),
        },
        observed_templates={
            "pass": "SAST enforced pre-merge via {tool} — blocks on HIGH/CRITICAL findings.",
            "partial": "SAST present via {tool} but does not fully block on HIGH/CRITICAL findings.",
            "fail": "No pre-merge SAST configured for Apex/LWC changes.",
        },
    ),
    ControlQuestion(
        control_id="SBS-CODE-003",
        severity="high",
        title="Implement Persistent Apex Application Logging",
        description="A durable Apex logging framework must capture application events beyond debug log limits.",
        status_question=(
            "Is a persistent Apex logging framework deployed that stores events in durable Salesforce objects "
            "or an external SIEM?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question=("Which framework? (e.g. custom Platform Events, Nebula Logger, Splunk forwarder, other):"),
        evidence_question="Evidence reference (AppExchange listing, repo path, or runbook link):",
        remediations={
            "partial": (
                "Extend the existing logging framework to cover all critical Apex paths and ensure "
                "log records persist beyond the 24-hour debug log retention window."
            ),
            "fail": (
                "Deploy a persistent Apex logging framework (e.g. Nebula Logger or custom Platform Events) "
                "that writes to durable custom objects or an external SIEM, surviving beyond debug log limits."
            ),
        },
        observed_templates={
            "pass": "Persistent Apex logging deployed via {tool}.",
            "partial": "Apex logging partially implemented via {tool} — coverage or persistence gaps remain.",
            "fail": "No persistent Apex logging framework deployed.",
        },
    ),
    ControlQuestion(
        control_id="SBS-CODE-004",
        severity="critical",
        title="Prevent Sensitive Data in Application Logs",
        description="Apex logs and debug logs must not capture PII, credentials, or regulated data fields.",
        status_question=(
            "Is there an enforced policy or automated scan preventing PII/credentials from appearing "
            "in Apex application logs or debug logs?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question=(
            "How is this enforced? (e.g. code review checklist, SAST rule, regex scan in CI, field allowlist):"
        ),
        evidence_question="Evidence reference (policy doc link, SAST config path, or ticket):",
        remediations={
            "partial": (
                "Extend the data-in-logs policy to cover all Apex logging paths. "
                "Add a SAST rule or regex CI scan that fails on hardcoded field names known to contain PII."
            ),
            "fail": (
                "Implement and enforce a policy prohibiting PII/credentials in Apex logs. "
                "Add a SAST check or code review gate that scans for sensitive field names in log statements."
            ),
        },
        observed_templates={
            "pass": "Sensitive-data-in-logs policy enforced via {tool}.",
            "partial": "Partial policy in place via {tool} — not all Apex paths covered.",
            "fail": "No policy or automated check preventing sensitive data from appearing in Apex logs.",
        },
    ),
    # ── Customer Portal ─────────────────────────────────────────────────────
    ControlQuestion(
        control_id="SBS-CPORTAL-001",
        severity="critical",
        title="Prevent Parameter-Based Record Access in Portal Apex",
        description=(
            "Portal-exposed Apex methods must not accept user-supplied record IDs to prevent IDOR. "
            "Mark not-applicable if this org has no Experience Cloud / Customer Portal."
        ),
        status_question=(
            "Are portal-exposed Apex methods reviewed and hardened against IDOR (no user-supplied record IDs accepted)?"
        ),
        status_options=["yes", "partial", "no", "na"],
        na_allowed_reason="This org has no Experience Cloud / Customer Portal deployed.",
        tool_question=(
            "How is this enforced? (e.g. WITH SECURITY_ENFORCED, stripInaccessible, code review gate, SAST rule):"
        ),
        evidence_question="Evidence reference (code review record, SAST config, or architecture doc):",
        remediations={
            "partial": (
                "Audit all portal-exposed @AuraEnabled and @RemoteAction methods for user-supplied ID parameters. "
                "Apply stripInaccessible(AccessType.READABLE, ...) and remove any user-controlled SOQL filters."
            ),
            "fail": (
                "Conduct a full audit of portal Apex methods. Prohibit user-supplied record identifiers. "
                "Use stripInaccessible and WITH SECURITY_ENFORCED to enforce record-level visibility."
            ),
        },
        observed_templates={
            "pass": "Portal Apex methods audited and hardened against IDOR via {tool}.",
            "partial": "Partial IDOR hardening via {tool} — not all portal Apex methods reviewed.",
            "fail": "No IDOR hardening confirmed for portal-exposed Apex methods.",
            "not_applicable": "No Experience Cloud / Customer Portal deployed in this org.",
        },
    ),
    ControlQuestion(
        control_id="SBS-CPORTAL-002",
        severity="critical",
        title="Restrict Guest User Record Access",
        description=(
            "Guest user profiles must have no access to business objects. "
            "Mark not-applicable if no Experience Cloud / Customer Portal is deployed."
        ),
        status_question=(
            "Is the guest user profile restricted to no business-related objects "
            "(no CRUD on standard/custom objects beyond authentication flow)?"
        ),
        status_options=["yes", "partial", "no", "na"],
        na_allowed_reason="This org has no Experience Cloud / Customer Portal deployed.",
        tool_question="When was the guest user profile last audited? (date or sprint reference):",
        evidence_question="Evidence reference (profile audit export path, ticket, or screenshot):",
        remediations={
            "partial": (
                "Review the guest user profile and remove all object permissions not required for the "
                "authentication flow. Apply org-wide sharing defaults to restrict guest access by default."
            ),
            "fail": (
                "Restrict the guest user profile immediately. Remove all CRUD permissions on business objects. "
                "Set org-wide sharing defaults for all sensitive objects to Private."
            ),
        },
        observed_templates={
            "pass": "Guest user profile audited and restricted as of {tool}.",
            "partial": "Guest user profile partially restricted — some business object access remains ({tool}).",
            "fail": "Guest user profile has unrestricted access to business objects — not remediated.",
            "not_applicable": "No Experience Cloud / Customer Portal deployed in this org.",
        },
    ),
    # ── Deployments ─────────────────────────────────────────────────────────
    ControlQuestion(
        control_id="SBS-DEP-001",
        severity="high",
        title="Require a Designated Deployment Identity for Metadata Changes",
        description="A dedicated integration user (not a human admin) must perform all CI/CD deployments.",
        status_question=(
            "Is a dedicated non-human deployment identity used exclusively for all CI/CD "
            "and metadata deployments to production?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question="What is the deployment identity? (username / service account name):",
        evidence_question="Evidence reference (CI config file path, deployment user profile link, or ticket):",
        remediations={
            "partial": (
                "Ensure the deployment identity is non-human and used for all deployments. "
                "Remove production deployment rights from all human admin accounts."
            ),
            "fail": (
                "Create a dedicated deployment integration user. Configure CI/CD to authenticate exclusively "
                "as this user. Remove deployment rights from all human admin accounts."
            ),
        },
        observed_templates={
            "pass": "Dedicated deployment identity '{tool}' in use for all CI/CD deployments.",
            "partial": "Deployment identity '{tool}' used for some deployments — not exclusively enforced.",
            "fail": "No dedicated deployment identity — human admins perform deployments directly.",
        },
    ),
    ControlQuestion(
        control_id="SBS-DEP-002",
        severity="high",
        title="High-Risk Metadata Types Prohibited from Direct Production Editing",
        description=(
            "Apex, Triggers, Profiles, Permission Sets, and Remote Site Settings must not be "
            "edited directly in production — all changes must go through the CI/CD pipeline."
        ),
        status_question=(
            "Is there a documented and enforced list of metadata types prohibited from direct "
            "production editing, with all changes routed through the CI/CD pipeline?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question=(
            "How is this enforced? (e.g. org lockdown via profiles, DevOps Center policy, documented process, other):"
        ),
        evidence_question="Evidence reference (policy doc link, DevOps Center config, or change management ticket):",
        remediations={
            "partial": (
                "Formalise the list of prohibited metadata types and ensure enforcement via profile restrictions "
                "or DevOps tooling. Include at minimum: Apex Classes, Triggers, LWC, Profiles, Permission Sets."
            ),
            "fail": (
                "Document and enforce a prohibited-in-production metadata list. "
                "Restrict all human admin profiles from editing high-risk metadata types in production. "
                "Route all changes through an approved CI/CD pipeline."
            ),
        },
        observed_templates={
            "pass": "High-risk metadata prohibited from direct prod editing via {tool}.",
            "partial": "Partial enforcement via {tool} — not all high-risk metadata types covered.",
            "fail": "No policy restricting direct production editing of high-risk metadata types.",
        },
    ),
    ControlQuestion(
        control_id="SBS-DEP-005",
        severity="critical",
        title="Implement Secret Scanning for Salesforce Source Repositories",
        description="CI/CD pipelines must scan for secrets (tokens, credentials) before merge and block on detection.",
        status_question=(
            "Is automated secret scanning enabled on the Salesforce source repository, "
            "blocking PRs when secrets are detected?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question=("Which tool? (e.g. GitHub secret scanning + push protection, gitleaks, truffleHog, other):"),
        evidence_question="Evidence reference (repo settings URL, CI config path, or scan report link):",
        remediations={
            "partial": (
                "Enable push protection on the secret scanning tool to block commits containing secrets, "
                "not just alert after the fact. Ensure all Salesforce token patterns are in the ruleset."
            ),
            "fail": (
                "Enable secret scanning with push protection on all Salesforce source repositories. "
                "Add Salesforce token patterns (access_token, refresh_token, client_secret) to the ruleset. "
                "Rotate any secrets found in git history immediately."
            ),
        },
        observed_templates={
            "pass": "Secret scanning with blocking enforcement active via {tool}.",
            "partial": "Secret scanning present via {tool} but push protection or ruleset incomplete.",
            "fail": "No secret scanning configured for the Salesforce source repository.",
        },
    ),
    ControlQuestion(
        control_id="SBS-DEP-006",
        severity="high",
        title="Salesforce CLI Connected App Token Expiration Policies",
        description=(
            "The Salesforce CLI Connected App must have refresh token and access token expiration "
            "configured — default settings ship with indefinite tokens."
        ),
        status_question=(
            "Is the Salesforce CLI Connected App configured with a finite refresh token expiry and access token expiry?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question=(
            "What are the configured expiry settings? (e.g. refresh token = 24h, access token = 2h; or 'org default'):"
        ),
        evidence_question="Evidence reference (Connected App config screenshot, Setup link, or ticket):",
        remediations={
            "partial": (
                "Configure both refresh token and access token expiry on the Salesforce CLI Connected App. "
                "Refresh tokens should expire after ≤24 hours of inactivity for developer workstations."
            ),
            "fail": (
                "Update the Salesforce CLI Connected App OAuth policies to set a finite refresh token expiry "
                "and access token expiry. The default indefinite token setting is a credential-theft risk."
            ),
        },
        observed_templates={
            "pass": "CLI Connected App token expiry configured: {tool}.",
            "partial": "Token expiry partially configured: {tool} — one or both token types still indefinite.",
            "fail": "CLI Connected App has no token expiry configured — indefinite refresh tokens in use.",
        },
    ),
    # ── File Security ────────────────────────────────────────────────────────
    ControlQuestion(
        control_id="SBS-FILE-001",
        severity="moderate",
        title="Require Expiry Dates on Public Content Links",
        description=(
            "All ContentDistribution (public link) records must have an expiry date "
            "set appropriate to the content classification."
        ),
        status_question=("Are expiry dates enforced on all public content links (ContentDistribution records)?"),
        status_options=["yes", "partial", "no"],
        tool_question=(
            "How is this enforced? (e.g. process builder/flow default, admin policy, quarterly audit, other):"
        ),
        evidence_question="Evidence reference (flow config path, policy doc, audit report, or ticket):",
        remediations={
            "partial": (
                "Implement a Flow or Process Builder that requires expiry date on ContentDistribution creation. "
                "Audit existing links and set or shorten expiry dates on all active links."
            ),
            "fail": (
                "Create a Flow that enforces expiry date input on all new ContentDistribution records. "
                "Run a SOQL audit of existing links and set expiry dates on all active records. "
                "Establish a quarterly review cadence."
            ),
        },
        observed_templates={
            "pass": "Expiry dates enforced on public content links via {tool}.",
            "partial": "Expiry dates partially enforced via {tool} — existing or some links have no expiry.",
            "fail": "No expiry date enforcement on public content links.",
        },
    ),
    ControlQuestion(
        control_id="SBS-FILE-002",
        severity="moderate",
        title="Require Passwords on Public Content Links for Sensitive Content",
        description=(
            "Public links sharing sensitive or confidential content must require a password "
            "to protect against link interception."
        ),
        status_question=(
            "Are passwords required on public content links that share sensitive or confidential content?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question=(
            "How is this enforced? (e.g. Flow validation, admin policy, content classification tag, other):"
        ),
        evidence_question="Evidence reference (flow config, policy doc, or ticket):",
        remediations={
            "partial": (
                "Extend password enforcement to all links sharing content classified as sensitive or confidential. "
                "Implement a content classification step that triggers password enforcement."
            ),
            "fail": (
                "Implement a Flow requiring passwords on ContentDistribution records for sensitive content. "
                "Define and document a content classification policy linking sensitivity level to link controls."
            ),
        },
        observed_templates={
            "pass": "Passwords enforced on sensitive public content links via {tool}.",
            "partial": "Password enforcement partially implemented via {tool} — gaps in coverage remain.",
            "fail": "No password enforcement on public content links for sensitive content.",
        },
    ),
    ControlQuestion(
        control_id="SBS-FILE-003",
        severity="moderate",
        title="Periodic Review and Cleanup of Public Content Links",
        description=(
            "A defined cadence (e.g. quarterly) must exist to scan ContentDistribution records "
            "and remove stale or forgotten public links."
        ),
        status_question=(
            "Is there a defined and documented cadence for reviewing and cleaning up "
            "all public content links (ContentDistribution records)?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question=(
            "What is the cadence and who owns it? (e.g. quarterly — Security team, monthly — IT admin, other):"
        ),
        evidence_question="Evidence reference (runbook link, calendar entry, last audit ticket, or report):",
        remediations={
            "partial": (
                "Formalise the review cadence by documenting it in the security runbook with a named owner. "
                "Automate the SOQL query to surface active links older than the threshold."
            ),
            "fail": (
                "Establish a quarterly review of all ContentDistribution records. "
                "Assign a named owner. Automate the scan using a scheduled Flow or SOQL report. "
                "Document the process in the security runbook."
            ),
        },
        observed_templates={
            "pass": "Periodic content link review established: {tool}.",
            "partial": "Review cadence partially in place: {tool} — not fully documented or automated.",
            "fail": "No periodic review or cleanup process for public content links.",
        },
    ),
    # ── Foundations ──────────────────────────────────────────────────────────
    ControlQuestion(
        control_id="SBS-FDNS-001",
        severity="moderate",
        title="Centralized Security System of Record",
        description=(
            "All Salesforce security-relevant configurations, exceptions, approvals, and control "
            "deviations must be recorded in a durable, accessible system of record."
        ),
        status_question=(
            "Is a centralised, durable system of record maintained that documents all Salesforce "
            "security configurations, exceptions, and control approvals?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question=(
            "Where is this system of record? (e.g. Confluence space, SharePoint site, Jira project, Git repo, other):"
        ),
        evidence_question="Evidence reference (URL to the system of record or path to the doc):",
        remediations={
            "partial": (
                "Expand the system of record to include all control deviations, exception approvals, "
                "and pending remediation items. Ensure it is accessible to all relevant stakeholders."
            ),
            "fail": (
                "Establish a centralised security system of record (e.g. Confluence, SharePoint, or Git). "
                "Migrate all security exception approvals, configuration decisions, and control deviations "
                "into this system immediately."
            ),
        },
        observed_templates={
            "pass": "Centralised security system of record maintained at {tool}.",
            "partial": "System of record partially in place at {tool} — not all controls/exceptions captured.",
            "fail": "No centralised system of record for Salesforce security configurations.",
        },
    ),
    # ── Integrations ─────────────────────────────────────────────────────────
    ControlQuestion(
        control_id="SBS-INT-001",
        severity="moderate",
        title="Enforce Governance of Browser Extensions Accessing Salesforce",
        description=(
            "A centrally managed allowlist or blocklist must govern which browser extensions "
            "can access Salesforce on managed devices."
        ),
        status_question=(
            "Is a centrally managed browser extension governance mechanism deployed "
            "(allowlist or blocklist) that covers all Salesforce users on managed devices?"
        ),
        status_options=["yes", "partial", "no"],
        tool_question=(
            "Which mechanism? (e.g. Chrome Browser Cloud Management, Intune/MDM policy, macOS config profile, other):"
        ),
        evidence_question="Evidence reference (MDM policy ID, admin console URL, or config doc):",
        remediations={
            "partial": (
                "Extend the browser extension governance policy to cover all managed devices used "
                "to access Salesforce. Define an explicit allowlist or blocklist for production org access."
            ),
            "fail": (
                "Deploy centrally managed browser extension governance via Chrome Browser Cloud Management, "
                "MDM, or equivalent. Define an allowlist of permitted extensions for Salesforce access. "
                "Block extensions with excessive data access permissions."
            ),
        },
        observed_templates={
            "pass": "Browser extension governance enforced via {tool} across all managed devices.",
            "partial": "Browser extension governance partially deployed via {tool} — coverage gaps remain.",
            "fail": "No centralised browser extension governance deployed for Salesforce users.",
        },
    ),
]

# ---------------------------------------------------------------------------
# Evidence reference formatter
# ---------------------------------------------------------------------------


def _evidence_ref(org: str, env: str, control_id: str, user_ref: str, date_str: str) -> str:
    if user_ref and user_ref.lower() not in ("none", "n/a", ""):
        return f"manual://{org}/{env}/{control_id}/{user_ref.replace(' ', '-')}/snapshot-{date_str}"
    return f"manual://{org}/{env}/{control_id}/no-evidence/snapshot-{date_str}"


# ---------------------------------------------------------------------------
# Interactive prompting
# ---------------------------------------------------------------------------


def _ask_status(q: ControlQuestion) -> str:
    """Prompt user for status; return one of yes/partial/no/na."""
    opts = q.status_options
    label_line = "  |  ".join(f"[{o}] {_STATUS_LABELS[o]}" for o in opts)
    while True:
        print(f"\n  {label_line}")
        raw = input(f"  Your answer ({'/'.join(opts)}): ").strip().lower()
        if raw in opts:
            return raw
        print(f"  Invalid. Please enter one of: {', '.join(opts)}")


def _ask_text(prompt: str, default: str = "") -> str:
    val = input(f"  {prompt} ").strip()
    return val if val else default


def _run_interactive(controls: list[ControlQuestion], org: str, env: str) -> list[dict]:
    assessed_dt = datetime.now(UTC)
    date_str = assessed_dt.strftime("%Y-%m-%d")
    findings = []

    groups = {
        "Code Security": [c for c in controls if c.control_id.startswith("SBS-CODE")],
        "Customer Portal": [c for c in controls if c.control_id.startswith("SBS-CPORTAL")],
        "Deployments": [c for c in controls if c.control_id.startswith("SBS-DEP")],
        "File Security": [c for c in controls if c.control_id.startswith("SBS-FILE")],
        "Foundations": [c for c in controls if c.control_id.startswith("SBS-FDNS")],
        "Integrations": [c for c in controls if c.control_id.startswith("SBS-INT")],
    }

    print(f"\n{'=' * 70}")
    print("  Manual Controls Assessment — sfdc-connect cannot assess these via API")
    print(f"  Org: {org}  |  Env: {env}  |  Date: {date_str}")
    print(f"{'=' * 70}\n")

    for group_name, group_controls in groups.items():
        if not group_controls:
            continue
        print(f"\n{'─' * 70}")
        print(f"  {group_name.upper()}")
        print(f"{'─' * 70}")

        for q in group_controls:
            print(f"\n  [{q.control_id}]  {q.title}  ({q.severity.upper()})")
            print(f"  {q.description}")
            if q.na_allowed_reason and "na" in q.status_options:
                print(f"  Note: {q.na_allowed_reason}")

            status_token = _ask_status(q)
            status = _STATUS_MAP[status_token]

            tool = _ask_text(q.tool_question, default="not specified")
            evidence_user = _ask_text(q.evidence_question, default="")

            observed = q.observed_templates.get(status, q.observed_templates.get(status_token, "")).format(tool=tool)
            remediation = q.remediations.get(status, "")
            evidence_ref = _evidence_ref(org, env, q.control_id, evidence_user, date_str)
            due = _due_date(q.severity, status, assessed_dt)

            findings.append(
                {
                    "control_id": q.control_id,
                    "status": status,
                    "severity": q.severity,
                    "owner": "SaaS Security Team",
                    "due_date": due,
                    "observed_value": observed,
                    "remediation": remediation,
                    "evidence_ref": evidence_ref,
                    "data_source": "manual-intake",
                }
            )
            print(f"  → Recorded: {status.upper()}")

    return findings


# ---------------------------------------------------------------------------
# Non-interactive (answers file) mode
# ---------------------------------------------------------------------------


def _run_from_answers(controls: list[ControlQuestion], org: str, env: str, answers: dict) -> list[dict]:
    """Process pre-filled answers. answers dict: {control_id: {status, tool, evidence}}."""
    assessed_dt = datetime.now(UTC)
    date_str = assessed_dt.strftime("%Y-%m-%d")
    findings = []

    for q in controls:
        ans = answers.get(q.control_id, {})
        status_token = ans.get("status", "no")
        if status_token not in q.status_options:
            print(f"WARNING: invalid status '{status_token}' for {q.control_id}, defaulting to 'no'", file=sys.stderr)
            status_token = "no"
        status = _STATUS_MAP[status_token]
        tool = ans.get("tool", "not specified")
        evidence_user = ans.get("evidence", "")

        observed = q.observed_templates.get(status, "").format(tool=tool)
        remediation = q.remediations.get(status, "")
        evidence_ref = _evidence_ref(org, env, q.control_id, evidence_user, date_str)
        due = _due_date(q.severity, status, assessed_dt)

        findings.append(
            {
                "control_id": q.control_id,
                "status": status,
                "severity": q.severity,
                "owner": "SaaS Security Team",
                "due_date": due,
                "observed_value": observed,
                "remediation": remediation,
                "evidence_ref": evidence_ref,
                "data_source": "manual-intake",
            }
        )

    return findings


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _to_markdown(findings: list[dict], org: str, env: str, assessed_at: str) -> str:
    lines = [
        "# Manual Controls Assessment",
        "",
        f"- **Org:** {org}",
        f"- **Env:** {env}",
        f"- **Assessed at:** {assessed_at}",
        "- **Data source:** manual-intake",
        "",
        "These controls cannot be assessed via the Salesforce REST/SOQL API. "
        "Answers were provided by the security or DevOps team.",
        "",
    ]

    groups = {
        "Code Security": ["SBS-CODE-001", "SBS-CODE-002", "SBS-CODE-003", "SBS-CODE-004"],
        "Customer Portal": ["SBS-CPORTAL-001", "SBS-CPORTAL-002"],
        "Deployments": ["SBS-DEP-001", "SBS-DEP-002", "SBS-DEP-005", "SBS-DEP-006"],
        "File Security": ["SBS-FILE-001", "SBS-FILE-002", "SBS-FILE-003"],
        "Foundations": ["SBS-FDNS-001"],
        "Integrations": ["SBS-INT-001"],
    }

    status_icons = {"pass": "✅", "fail": "❌", "partial": "⚠️", "not_applicable": "—"}

    for group_name, ids in groups.items():
        group_findings = [f for f in findings if f["control_id"] in ids]
        if not group_findings:
            continue
        lines += [f"## {group_name}", ""]
        for f in group_findings:
            icon = status_icons.get(f["status"], "?")
            lines += [
                f"### {icon} {f['control_id']} — {f['status'].upper()}",
                f"- **Severity:** {f['severity']}",
                f"- **Observed:** {f['observed_value']}",
            ]
            if f.get("due_date"):
                lines.append(f"- **Due:** {f['due_date']}")
            if f.get("remediation"):
                lines.append(f"- **Remediation:** {f['remediation']}")
            lines.append(f"- **Evidence:** `{f['evidence_ref']}`")
            lines.append("")

    # Summary table
    from collections import Counter

    counts = Counter(f["status"] for f in findings)
    lines += [
        "## Summary",
        "",
        "| Status | Count |",
        "|---|---|",
        f"| pass | {counts.get('pass', 0)} |",
        f"| partial | {counts.get('partial', 0)} |",
        f"| fail | {counts.get('fail', 0)} |",
        f"| not_applicable | {counts.get('not_applicable', 0)} |",
        f"| **Total** | **{len(findings)}** |",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Merge into existing gap_analysis.json
# ---------------------------------------------------------------------------


def _merge(gap_path: Path, new_findings: list[dict]) -> None:
    data = json.loads(gap_path.read_text())
    existing = {f["control_id"]: f for f in data.get("findings", [])}
    updated = 0

    for nf in new_findings:
        cid = nf["control_id"]
        if cid in existing:
            existing[cid].update(nf)
            updated += 1
        else:
            existing[cid] = nf

    data["findings"] = list(existing.values())
    # Update data_source to reflect combined collection
    data["data_source"] = "live-collection+manual-intake"
    gap_path = gap_path.resolve()
    gap_path.write_text(json.dumps(data, indent=2))  # NOSONAR — intentional CLI output path
    print(f"  Merged {updated} manual findings into {gap_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manual intake questionnaire for API-unassessable SBS controls.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--org", default="unknown-org", help="Org alias (used for evidence refs and output path).")
    parser.add_argument("--env", default="dev", choices=["dev", "test", "prod"], help="Environment label.")
    parser.add_argument(
        "--answers",
        metavar="FILE",
        help="JSON file with pre-filled answers {control_id: {status, tool, evidence}}. Omit for interactive mode.",
    )
    parser.add_argument(
        "--merge",
        metavar="GAP_ANALYSIS",
        help="Path to gap_analysis.json produced by oscal-assess. "
        "Manual findings will be merged in, updating not_applicable entries.",
    )
    parser.add_argument("--out", metavar="DIR", help="Output directory (default: same dir as --merge or cwd).")
    args = parser.parse_args()

    # Determine output directory
    if args.out:
        out_dir = Path(args.out)
    elif args.merge:
        out_dir = Path(args.merge).parent
    else:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        out_dir = _REPO / "docs" / "oscal-salesforce-poc" / "generated" / args.org / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    # Run assessment
    if args.answers:
        answers_path = Path(args.answers)
        if not answers_path.exists():
            print(f"ERROR: answers file not found: {answers_path}", file=sys.stderr)
            return 1
        answers = json.loads(answers_path.read_text())
        findings = _run_from_answers(CONTROLS, args.org, args.env, answers)
    else:
        findings = _run_interactive(CONTROLS, args.org, args.env)

    # Write outputs
    assessed_at = datetime.now(UTC).isoformat()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    payload = {
        "assessment_id": f"sfdc-manual-{args.org}-{args.env}-{datetime.now(UTC).strftime('%Y%m%d')}",
        "assessed_at_utc": assessed_at,
        "org": args.org,
        "env": args.env,
        "data_source": "manual-intake",
        "ai_generated_findings_notice": (
            "Findings in this file are based on human-provided answers to structured questions. "
            "Evidence references must be verified by the assessment owner before delivery."
        ),
        "findings": findings,
    }

    json_path = out_dir / f"manual_assessment-{timestamp}.json"
    md_path = out_dir / f"manual_assessment-{timestamp}.md"

    json_path.write_text(json.dumps(payload, indent=2))
    md_path.write_text(_to_markdown(findings, args.org, args.env, assessed_at))
    print("\nWrote manual assessment:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")

    # Merge into gap_analysis if requested
    if args.merge:
        gap_path = Path(args.merge)
        if not gap_path.exists():
            print(f"ERROR: gap_analysis not found: {gap_path}", file=sys.stderr)
            return 1
        _merge(gap_path, findings)
        print(f"  Updated: {gap_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
