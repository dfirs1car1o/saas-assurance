#!/usr/bin/env python3
"""
scripts/workday_dry_run_demo.py

Generates a realistic Workday dry-run assessment and runs it through the full
downstream pipeline (sscf-benchmark → nist-review → report-gen) to produce
a DOCX governance report without a live Workday tenant.

Usage:
    python3 scripts/workday_dry_run_demo.py [--org ORG] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SECURITY_TEAM = "Security Team"

# ---------------------------------------------------------------------------
# Mock findings — realistic Workday org with common security gaps
# ---------------------------------------------------------------------------

_DUE_DAYS = {"critical": 7, "high": 30, "moderate": 90, "low": 180}


def _due(severity: str) -> str:
    days = _DUE_DAYS.get(severity, 90)
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%d")


MOCK_FINDINGS = [
    # IAM
    {
        "control_id": "WD-IAM-001",
        "title": "Security Group Overprivilege Assessment",
        "status": "partial",
        "severity": "critical",
        "sscf_domain": "identity_access_management",
        "sscf_control_id": "SSCF-IAM-002",
        "observed_value": "RaaS report returned 47 security group entries",
        "expected_value": "No groups with undocumented sensitive domain access",
        "notes": "Human review required — 4 ISSGs flagged with Compensation domain access",
        "remediation": "Review Security_Group_Domain_Access_Audit report; remove undocumented domain grants",
    },
    {
        "control_id": "WD-IAM-002",
        "title": "Integration System User (ISU) Least Privilege",
        "status": "fail",
        "severity": "critical",
        "sscf_domain": "identity_access_management",
        "sscf_control_id": "SSCF-IAM-001",
        "observed_value": "Disallow_UI_Sessions=false on 2 ISUs",
        "expected_value": "Disallow_UI_Sessions=true for all ISUs",
        "notes": "2 integration accounts allow UI login — violates ISU hardening requirement",
        "remediation": "Enable Disallow UI Sessions on all Integration System Users",
    },
    {
        "control_id": "WD-IAM-003",
        "title": "Multi-Factor Authentication Policy Enforcement",
        "status": "fail",
        "severity": "critical",
        "sscf_domain": "identity_access_management",
        "sscf_control_id": "SSCF-IAM-001",
        "observed_value": "MFA required on 1/3 authentication policies",
        "expected_value": "Multi_Factor_Authentication_Required=true on all policies",
        "notes": "2 authentication policies covering contractor and partner accounts lack MFA",
        "remediation": "Enable MFA on all Workday authentication policies",
    },
    {
        "control_id": "WD-IAM-004",
        "title": "Single Sign-On (SSO) Configuration",
        "status": "pass",
        "severity": "high",
        "sscf_domain": "identity_access_management",
        "sscf_control_id": "SSCF-IAM-001",
        "observed_value": "SSO_Enabled=true, Require_Signed_Assertions=true",
        "expected_value": "SSO enabled with signed assertions required",
        "notes": None,
        "remediation": None,
    },
    {
        "control_id": "WD-IAM-005",
        "title": "Privileged Role Assignment Review",
        "status": "partial",
        "severity": "high",
        "sscf_domain": "identity_access_management",
        "sscf_control_id": "SSCF-IAM-002",
        "observed_value": "RaaS report returned 12 privileged role assignments",
        "expected_value": "All privileged assignments recertified within 90 days",
        "notes": "Last recertification date unavailable in report; manual review needed",
        "remediation": "Configure recertification workflow; review Privileged_Role_Assignments_Audit report",
    },
    {
        "control_id": "WD-IAM-006",
        "title": "Segregation of Duties in Business Processes",
        "status": "partial",
        "severity": "high",
        "sscf_domain": "identity_access_management",
        "sscf_control_id": "SSCF-IAM-002",
        "observed_value": "RaaS report returned 23 business process security policies",
        "expected_value": "No initiator/approver overlap in sensitive business processes",
        "notes": "SOD check requires human review of initiator vs approver group membership",
        "remediation": "Review Business_Process_Security_Policy_Audit for SOD conflicts",
    },
    {
        "control_id": "WD-IAM-007",
        "title": "Inactive Account Detection",
        "status": "partial",
        "severity": "moderate",
        "sscf_domain": "identity_access_management",
        "sscf_control_id": "SSCF-IAM-001",
        "observed_value": "Active workers accessible: 1842",
        "expected_value": "No accounts with lastLogin > 90 days",
        "notes": "lastLogin date comparison requires manual review of full worker list",
        "remediation": "Configure Workday offboarding workflow; review inactive accounts quarterly",
    },
    {
        "control_id": "WD-IAM-008",
        "title": "API Client Scope Governance",
        "status": "pass",
        "severity": "high",
        "sscf_domain": "identity_access_management",
        "sscf_control_id": "SSCF-IAM-001",
        "observed_value": "API clients with broad scope: 0",
        "expected_value": "No API clients with All_Workday_Data scope",
        "notes": None,
        "remediation": None,
    },
    # Configuration Hardening
    {
        "control_id": "WD-CON-001",
        "title": "Password Complexity Requirements",
        "status": "fail",
        "severity": "high",
        "sscf_domain": "configuration_hardening",
        "sscf_control_id": "SSCF-CON-001",
        "observed_value": "Minimum_Password_Length=8",
        "expected_value": ">= 12",
        "notes": "Password minimum length below recommended 12 characters",
        "remediation": "Increase Minimum_Password_Length to 12 in Workday password policy",
    },
    {
        "control_id": "WD-CON-002",
        "title": "Password Rotation and History Policy",
        "status": "fail",
        "severity": "moderate",
        "sscf_domain": "configuration_hardening",
        "sscf_control_id": "SSCF-CON-001",
        "observed_value": "Password_Expiration_Days=180, Password_History_Count=5",
        "expected_value": "expiry <= 90 AND history >= 12",
        "notes": "Password expiry too long; history count below minimum",
        "remediation": "Set Password_Expiration_Days=90 and Password_History_Count=24",
    },
    {
        "control_id": "WD-CON-003",
        "title": "Session Timeout Configuration",
        "status": "fail",
        "severity": "moderate",
        "sscf_domain": "configuration_hardening",
        "sscf_control_id": "SSCF-CON-001",
        "observed_value": "Session_Timeout_Minutes=480",
        "expected_value": "<= 30",
        "notes": "8-hour session timeout significantly exceeds recommended 30 minutes",
        "remediation": "Reduce Session_Timeout_Minutes to 30 for standard accounts",
    },
    {
        "control_id": "WD-CON-004",
        "title": "Account Lockout Policy",
        "status": "pass",
        "severity": "high",
        "sscf_domain": "configuration_hardening",
        "sscf_control_id": "SSCF-CON-001",
        "observed_value": "Lockout_Threshold=3, Lockout_Duration_Minutes=30",
        "expected_value": "threshold <= 5 AND duration >= 15",
        "notes": None,
        "remediation": None,
    },
    {
        "control_id": "WD-CON-005",
        "title": "Network Access Restriction (IP Allowlisting)",
        "status": "not_applicable",
        "severity": "moderate",
        "sscf_domain": "configuration_hardening",
        "sscf_control_id": "SSCF-CON-001",
        "observed_value": None,
        "expected_value": "At least one IP range configured",
        "notes": "IP range restriction requires manual tenant admin confirmation",
        "remediation": "Configure IP allowlist in Workday Security → IP Range Settings",
    },
    {
        "control_id": "WD-CON-006",
        "title": "Authentication Policy Coverage",
        "status": "pass",
        "severity": "moderate",
        "sscf_domain": "configuration_hardening",
        "sscf_control_id": "SSCF-CON-001",
        "observed_value": "Authentication policies found: 3",
        "expected_value": "At least one authentication policy covering all users",
        "notes": None,
        "remediation": None,
    },
    # Logging and Monitoring
    {
        "control_id": "WD-LOG-001",
        "title": "User Activity Logging",
        "status": "not_applicable",
        "severity": "high",
        "sscf_domain": "logging_monitoring",
        "sscf_control_id": "SSCF-LOG-001",
        "observed_value": None,
        "expected_value": "User_Activity_Logging_Enabled=true",
        "notes": "Requires manual admin confirmation via tenant setup",
        "remediation": "Confirm User Activity Logging is enabled in Workday Tenant Setup → Security",
    },
    {
        "control_id": "WD-LOG-002",
        "title": "Sign-On Event Audit Availability",
        "status": "partial",
        "severity": "moderate",
        "sscf_domain": "logging_monitoring",
        "sscf_control_id": "SSCF-LOG-001",
        "observed_value": "RaaS report returned 1247 sign-on events (last 30 days)",
        "expected_value": "Sign-on audit logs accessible and non-empty",
        "notes": "Log entries accessible; alert routing configuration not verified",
        "remediation": None,
    },
    {
        "control_id": "WD-LOG-003",
        "title": "Failed Authentication Monitoring",
        "status": "not_applicable",
        "severity": "high",
        "sscf_domain": "logging_monitoring",
        "sscf_control_id": "SSCF-LOG-001",
        "observed_value": None,
        "expected_value": "Failed sign-on events tracked and alerting configured",
        "notes": "RaaS report RPT_Failed_Signon_Events not pre-configured",
        "remediation": "Create RPT_Failed_Signon_Events custom report and publish as RaaS endpoint",
    },
    {
        "control_id": "WD-LOG-004",
        "title": "Administrative Action Audit Trail",
        "status": "partial",
        "severity": "high",
        "sscf_domain": "logging_monitoring",
        "sscf_control_id": "SSCF-LOG-001",
        "observed_value": "RaaS report returned 89 audit log entries",
        "expected_value": "Admin action logs accessible and non-empty",
        "notes": "Audit log accessible; retention period not confirmed",
        "remediation": None,
    },
    {
        "control_id": "WD-LOG-005",
        "title": "Audit Log Retention Policy",
        "status": "not_applicable",
        "severity": "moderate",
        "sscf_domain": "logging_monitoring",
        "sscf_control_id": "SSCF-LOG-001",
        "observed_value": None,
        "expected_value": ">= 365 days",
        "notes": "Audit retention configuration requires manual admin verification",
        "remediation": "Verify audit log retention is set to >= 365 days in Workday Tenant Setup",
    },
    # Cryptography and Key Management
    {
        "control_id": "WD-CKM-001",
        "title": "TLS Enforcement for API Communications",
        "status": "not_applicable",
        "severity": "high",
        "sscf_domain": "cryptography_key_management",
        "sscf_control_id": "SSCF-CKM-001",
        "observed_value": None,
        "expected_value": "Require_TLS_For_API=true",
        "notes": "TLS configuration not accessible via current ISU permissions",
        "remediation": "Grant ISU access to Tenant Setup – Security domain to verify TLS enforcement",
    },
    {
        "control_id": "WD-CKM-002",
        "title": "Customer-Managed Encryption Keys (BYOK)",
        "status": "not_applicable",
        "severity": "moderate",
        "sscf_domain": "cryptography_key_management",
        "sscf_control_id": "SSCF-CKM-001",
        "observed_value": None,
        "expected_value": "BYOK configured for sensitive data at rest",
        "notes": "BYOK configuration requires manual tenant administrator confirmation",
        "remediation": "Confirm BYOK status with Workday tenant admin; document in evidence record",
    },
    {
        "control_id": "WD-CKM-003",
        "title": "Integration Credential Rotation",
        "status": "partial",
        "severity": "moderate",
        "sscf_domain": "cryptography_key_management",
        "sscf_control_id": "SSCF-CKM-001",
        "observed_value": "ISU passwords last changed: ['2025-09-12', '2025-11-03']",
        "expected_value": "Password changed within 90 days",
        "notes": "svc_security_assessor password may exceed 90-day rotation policy; verify dates",
        "remediation": "Rotate ISU passwords and enforce 90-day rotation policy",
    },
    # Data Security and Privacy
    {
        "control_id": "WD-DSP-001",
        "title": "Sensitive Domain Access Control",
        "status": "partial",
        "severity": "critical",
        "sscf_domain": "data_security_privacy",
        "sscf_control_id": "SSCF-DSP-001",
        "observed_value": "Security group members in sensitive domains: 14",
        "expected_value": "Sensitive domain access limited to documented groups",
        "notes": "14 members in sensitive domains (Compensation, SSN, Benefits) — human review required",
        "remediation": "Review and document justification for all sensitive domain group memberships",
    },
    {
        "control_id": "WD-DSP-002",
        "title": "Data Export Permission Controls",
        "status": "fail",
        "severity": "high",
        "sscf_domain": "data_security_privacy",
        "sscf_control_id": "SSCF-DSP-001",
        "observed_value": "Allow_Data_Export=true",
        "expected_value": "Allow_Data_Export restricted",
        "notes": "Bulk data export enabled without documented restriction",
        "remediation": "Restrict data export permissions; require explicit approval workflow for exports",
    },
    {
        "control_id": "WD-DSP-003",
        "title": "Integration Data Access Scope",
        "status": "pass",
        "severity": "high",
        "sscf_domain": "data_security_privacy",
        "sscf_control_id": "SSCF-DSP-001",
        "observed_value": "Integrations with broad data scope: 0",
        "expected_value": "No integrations with All_Workday_Data scope",
        "notes": None,
        "remediation": None,
    },
    {
        "control_id": "WD-DSP-004",
        "title": "PII Domain Access Restriction",
        "status": "partial",
        "severity": "high",
        "sscf_domain": "data_security_privacy",
        "sscf_control_id": "SSCF-DSP-001",
        "observed_value": "Security group members in PII domains: 9",
        "expected_value": "PII domain access limited to documented roles",
        "notes": "PII domain access inventory complete; authorization documentation review required",
        "remediation": "Document and recertify all PII domain access annually",
    },
    # Threat Detection and Response
    {
        "control_id": "WD-TDR-001",
        "title": "Failed Login Alert Configuration",
        "status": "not_applicable",
        "severity": "moderate",
        "sscf_domain": "threat_detection_response",
        "sscf_control_id": "SSCF-TDR-001",
        "observed_value": None,
        "expected_value": "Alert threshold configured with routing",
        "notes": "Alert threshold configuration requires manual admin verification",
        "remediation": "Configure failed login alert threshold and routing in Workday Security Settings",
    },
    {
        "control_id": "WD-TDR-002",
        "title": "Business Process Approval Controls",
        "status": "not_applicable",
        "severity": "moderate",
        "sscf_domain": "threat_detection_response",
        "sscf_control_id": "SSCF-TDR-001",
        "observed_value": None,
        "expected_value": "No single-approver business process chains",
        "notes": "Business process approval chain audit requires manual review",
        "remediation": "Review sensitive business processes for single-approver gaps; add secondary approver",
    },
    # Governance and Compliance
    {
        "control_id": "WD-GOV-001",
        "title": "Security Policy Activation Status",
        "status": "not_applicable",
        "severity": "high",
        "sscf_domain": "governance_risk_compliance",
        "sscf_control_id": "SSCF-GOV-001",
        "observed_value": None,
        "expected_value": "No pending security policies",
        "notes": "Security policy pending status requires manual admin verification",
        "remediation": "Activate all pending security policy changes in Workday",
    },
    {
        "control_id": "WD-GOV-002",
        "title": "Security Configuration Change Audit",
        "status": "partial",
        "severity": "high",
        "sscf_domain": "governance_risk_compliance",
        "sscf_control_id": "SSCF-GOV-001",
        "observed_value": "RaaS report returned 31 security config changes (last 90 days)",
        "expected_value": "All changes documented with approver",
        "notes": "3 changes lack recorded approver — requires human review",
        "remediation": "Investigate unapproved security config changes; enforce approval workflow",
    },
]


# ---------------------------------------------------------------------------
# Build workday_raw.json (schema v2)
# ---------------------------------------------------------------------------


def build_workday_raw(org: str, env: str) -> dict:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    findings = []
    for f in MOCK_FINDINGS:
        findings.append(
            {
                "control_id": f["control_id"],
                "title": f["title"],
                "status": f["status"],
                "severity": f["severity"],
                "evidence_source": f"workday-connect://dry-run/{f['control_id']}",
                "observed_value": f.get("observed_value"),
                "expected_value": f.get("expected_value"),
                "notes": f.get("notes"),
                "sscf_mappings": [
                    {
                        "sscf_domain": f["sscf_domain"],
                        "sscf_control_id": f["sscf_control_id"],
                        "mapping_strength": "direct",
                    }
                ],
                "platform_data": {"collection_method": "dry-run", "dry_run": True},
            }
        )
    return {
        "schema_version": "2.0",
        "assessment_id": f"wd-dry-run-{datetime.now(UTC).strftime('%Y%m%d')}-001",
        "platform": "workday",
        "oscal_catalog_ref": "config/workday/workday_catalog.json",
        "assessment_time_utc": now,
        "environment": env,
        "assessor": "workday-connect v0.1.0 (dry-run)",
        "assessment_owner": _SECURITY_TEAM,
        "data_source": "dry_run_stub",  # schema enum: live_api | dry_run_stub | manual_questionnaire
        "ai_generated_findings_notice": (
            "Findings are simulated dry-run demo data. "
            "Not based on a live Workday tenant. For demonstration purposes only."
        ),
        "assessment_scope": {
            "controls_in_scope": len(findings),
            "controls_excluded": 0,
        },
        "org": org,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Convert workday_raw.json → backlog.json format for sscf-benchmark
# ---------------------------------------------------------------------------


def to_backlog(raw: dict) -> dict:
    now = datetime.now(UTC).isoformat()
    items = []
    for f in raw["findings"]:
        sscf_ids = [m["sscf_control_id"] for m in f.get("sscf_mappings", [])]
        severity = f.get("severity", "moderate")
        status = f.get("status", "partial")
        due = _due(severity) if status == "fail" else ""
        if status in ("pass", "fail"):
            mapping_confidence = "high"
        elif status == "partial":
            mapping_confidence = "medium"
        else:
            mapping_confidence = "low"
        item = {
            "legacy_control_id": f["control_id"],
            "sbs_control_id": f["control_id"],
            "sbs_title": f.get("title", f["control_id"]),
            "status": status,
            "severity": severity,
            "owner": _SECURITY_TEAM,
            "due_date": due,
            "remediation": (
                MOCK_FINDINGS[
                    next((i for i, m in enumerate(MOCK_FINDINGS) if m["control_id"] == f["control_id"]), 0)
                ].get("remediation")
                or ""
            ),
            "evidence_ref": f.get("evidence_source", ""),
            "mapping_notes": "Direct Workday catalog mapping.",
            "mapping_confidence": mapping_confidence,
            "sscf_mappings": f.get("sscf_mappings", []),
            "sscf_control_ids": sscf_ids,
        }
        items.append(item)

    summary_counts: dict[str, int] = {"pass": 0, "fail": 0, "partial": 0, "not_applicable": 0}
    for item in items:
        summary_counts[item["status"]] = summary_counts.get(item["status"], 0) + 1

    return {
        "assessment_id": raw["assessment_id"],
        "assessment_owner": raw.get("assessment_owner", _SECURITY_TEAM),
        "generated_at_utc": now,
        "catalog_version": "wscc-0.2.0",
        "framework": "CSA_SSCF",
        "platform": "workday",
        "summary": summary_counts,
        "mapped_items": items,
        "unmapped_items": [],
        "invalid_mapping_entries": [],
    }


# ---------------------------------------------------------------------------
# Run subprocess pipeline step
# ---------------------------------------------------------------------------


def _run(cmd: list[str], label: str) -> None:
    print(f"  [{label}] {' '.join(cmd[:4])}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [{label}] STDERR: {result.stderr[:400]}", file=sys.stderr)
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Workday dry-run demo — generates DOCX report")
    parser.add_argument("--org", default="acme-workday-dryrun")
    parser.add_argument("--env", default="prod")
    args = parser.parse_args()

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir = _REPO / "docs" / "oscal-salesforce-poc" / "generated" / args.org / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = out_dir / "workday_raw.json"
    backlog_path = out_dir / "workday_backlog.json"
    sscf_path = out_dir / "workday_sscf_report.json"
    nist_path = out_dir / "workday_nist_review.json"
    aicm_path = out_dir / "aicm_coverage.json"
    security_md = out_dir / f"{args.org}_security_assessment.md"
    app_owner_md = out_dir / f"{args.org}_remediation_report.md"

    python = sys.executable

    # Step 1: Generate mock workday_raw.json
    raw = build_workday_raw(args.org, args.env)
    raw_path.write_text(json.dumps(raw, indent=2))
    print(f"  [workday-raw] written: {raw_path}")

    # Step 2: Convert to backlog.json
    backlog = to_backlog(raw)
    backlog_path.write_text(json.dumps(backlog, indent=2))
    print(f"  [backlog]     written: {backlog_path}")

    # Step 3: sscf-benchmark
    _run(
        [
            python,
            "-m",
            "skills.sscf_benchmark.sscf_benchmark",
            "benchmark",
            "--backlog",
            str(backlog_path),
            "--out",
            str(sscf_path),
        ],
        "sscf-benchmark",
    )
    print(f"  [sscf]        written: {sscf_path}")

    # Step 4: nist-review (--dry-run to avoid real API spend on demo)
    _run(
        [
            python,
            "-m",
            "skills.nist_review.nist_review",
            "assess",
            "--gap-analysis",
            str(raw_path),
            "--backlog",
            str(backlog_path),
            "--out",
            str(nist_path),
            "--dry-run",
            "--platform",
            "workday",
        ],
        "nist-review",
    )
    print(f"  [nist]        written: {nist_path}")

    # Step 4.5: gen_aicm_crosswalk
    _run(
        [
            python,
            "scripts/gen_aicm_crosswalk.py",
            "--backlog",
            str(backlog_path),
            "--org",
            args.org,
            "--platform",
            "workday",
            "--out",
            str(aicm_path),
        ],
        "aicm-crosswalk",
    )
    print(f"  [aicm]        written: {aicm_path}")

    # Step 5a: report-gen app-owner
    _run(
        [
            python,
            "-m",
            "skills.report_gen.report_gen",
            "generate",
            "--org-alias",
            args.org,
            "--backlog",
            str(backlog_path),
            "--sscf-benchmark",
            str(sscf_path),
            "--audience",
            "app-owner",
            "--title",
            f"Workday Security Governance Assessment — {args.org}",
            "--out",
            str(app_owner_md),
        ],
        "report-gen(app-owner)",
    )
    print(f"  [app-owner]   written: {app_owner_md}")

    # Step 5b: report-gen security (also writes .docx via pandoc)
    _run(
        [
            python,
            "-m",
            "skills.report_gen.report_gen",
            "generate",
            "--org-alias",
            args.org,
            "--backlog",
            str(backlog_path),
            "--sscf-benchmark",
            str(sscf_path),
            "--nist-review",
            str(nist_path),
            "--aicm-coverage",
            str(aicm_path),
            "--audience",
            "security",
            "--title",
            f"Workday Security Governance Assessment — {args.org}",
            "--out",
            str(security_md),
        ],
        "report-gen(security)",
    )
    print(f"  [security-md] written: {security_md}")

    docx_path = security_md.with_suffix(".docx")
    if docx_path.exists():
        print(f"  [security-docx] written: {docx_path}")
    else:
        print("  [security-docx] not generated (pandoc not found — markdown available above)")

    # Summary
    counts = backlog["summary"]
    total = sum(counts.values())
    fail_pct = counts["fail"] / total if total > 0 else 0
    print(f"\n{'=' * 60}")
    print(f"Workday Dry-Run Complete — org={args.org}")
    print(
        f"Controls: {total}  pass={counts['pass']}  fail={counts['fail']}"
        f"  partial={counts['partial']}  n/a={counts['not_applicable']}"
    )
    print(f"Fail rate: {fail_pct:.0%}")
    print(f"{'=' * 60}")
    if docx_path.exists():
        print(f"\nDOCX: {docx_path}")
    print(f"MD:   {security_md}")


if __name__ == "__main__":
    main()
