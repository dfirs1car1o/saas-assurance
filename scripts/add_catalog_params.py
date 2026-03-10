"""add_catalog_params.py — One-shot script to add OSCAL ODPs to the SSCF catalog.

Adds organizational defined parameters (ODPs) to all 36 controls in
config/sscf/sscf_v1_catalog.json, following NIST/FedRAMP parameterization patterns.

Each control gets:
  - A `params` array (added before `props`, per OSCAL 1.1.2 schema order)
  - Updated statement prose using {{ insert: param, <param-id> }} references

Run once, then commit the updated catalog:
    python3 scripts/add_catalog_params.py
    git diff config/sscf/sscf_v1_catalog.json
"""

from __future__ import annotations

import json
from pathlib import Path

CATALOG_PATH = Path("config/sscf/sscf_v1_catalog.json")

# ── Shared ODP value constants (SonarCloud S1192 — avoid duplicated literals) ─
_SLA_24H = "24 hours"
_SLA_1H = "1 hour"
_SLA_30D = "30 days"
_SLA_90D = "90 days"
_SLA_12M = "12 months"

# ── ODP definitions per control ───────────────────────────────────────────────
# Format: control_id → {"params": [...], "statement": "<updated prose>"}
# params: list of {"id", "label", "usage", "values"}

PARAMS: dict[str, dict] = {
    "sscf-con-001": {
        "params": [
            {
                "id": "sscf-con-001_prm_1",
                "label": "assessment-frequency",
                "usage": (
                    "Frequency at which the security baseline is assessed against a published "
                    "benchmark (e.g., quarterly, monthly, semi-annually)"
                ),
                "values": ["quarterly"],
            }
        ],
        "statement": (
            "Apply and continuously assess approved secure configuration baselines "
            "for each SaaS platform against a published benchmark, at minimum "
            "{{ insert: param, sscf-con-001_prm_1 }}."
        ),
    },
    "sscf-con-002": {
        "params": [
            {
                "id": "sscf-con-002_prm_1",
                "label": "critical-drift-remediation-sla",
                "usage": "Maximum time allowed to remediate a critical baseline drift deviation",
                "values": [_SLA_24H],
            },
            {
                "id": "sscf-con-002_prm_2",
                "label": "high-drift-remediation-sla",
                "usage": "Maximum time allowed to remediate a high-severity baseline drift deviation",
                "values": ["7 days"],
            },
            {
                "id": "sscf-con-002_prm_3",
                "label": "moderate-drift-remediation-sla",
                "usage": "Maximum time allowed to remediate a moderate-severity baseline drift deviation",
                "values": [_SLA_30D],
            },
        ],
        "statement": (
            "Detect unauthorized configuration drift from the approved security baseline "
            "and enforce a remediation workflow with defined SLAs: "
            "Critical — {{ insert: param, sscf-con-002_prm_1 }}; "
            "High — {{ insert: param, sscf-con-002_prm_2 }}; "
            "Moderate — {{ insert: param, sscf-con-002_prm_3 }}."
        ),
    },
    "sscf-con-003": {
        "params": [
            {
                "id": "sscf-con-003_prm_1",
                "label": "integration-password-max-age",
                "usage": "Maximum age for integration system passwords before mandatory rotation",
                "values": [_SLA_90D],
            },
            {
                "id": "sscf-con-003_prm_2",
                "label": "api-key-max-age",
                "usage": "Maximum age for API keys before mandatory rotation",
                "values": ["180 days"],
            },
            {
                "id": "sscf-con-003_prm_3",
                "label": "oauth-refresh-token-max-lifetime",
                "usage": "Maximum lifetime for OAuth refresh tokens",
                "values": ["1 year"],
            },
        ],
        "statement": (
            "Govern the full lifecycle of API credentials, OAuth tokens, integration system "
            "passwords, and service account secrets used to access SaaS platforms, with "
            "maximum credential ages of: integration passwords {{ insert: param, sscf-con-003_prm_1 }}, "
            "API keys {{ insert: param, sscf-con-003_prm_2 }}, "
            "OAuth refresh tokens {{ insert: param, sscf-con-003_prm_3 }}."
        ),
    },
    "sscf-con-004": {
        "params": [
            {
                "id": "sscf-con-004_prm_1",
                "label": "hardening-review-frequency",
                "usage": "Frequency at which platform hardening settings are reviewed and updated",
                "values": ["after each major platform update, and at minimum annually"],
            }
        ],
        "statement": (
            "Verify that vendor-published hardening guidance and security settings are applied "
            "to each SaaS platform, including disabling insecure defaults and enabling "
            "platform-native security features, reviewed {{ insert: param, sscf-con-004_prm_1 }}."
        ),
    },
    "sscf-con-005": {
        "params": [
            {
                "id": "sscf-con-005_prm_1",
                "label": "oauth-app-review-frequency",
                "usage": "Frequency of reviews for OAuth-connected applications",
                "values": ["quarterly"],
            },
            {
                "id": "sscf-con-005_prm_2",
                "label": "unused-integration-revocation-period",
                "usage": "Inactivity period after which an unused integration must be revoked",
                "values": [_SLA_90D],
            },
        ],
        "statement": (
            "Inventory and assess the security posture of all third-party integrations and "
            "OAuth-connected applications accessing the SaaS platform, with "
            "{{ insert: param, sscf-con-005_prm_1 }} reviews and revocation of integrations "
            "unused for {{ insert: param, sscf-con-005_prm_2 }}."
        ),
    },
    "sscf-con-006": {
        "params": [
            {
                "id": "sscf-con-006_prm_1",
                "label": "critical-patch-sla",
                "usage": "Maximum time to apply a critical security patch after vendor release",
                "values": [_SLA_30D],
            },
            {
                "id": "sscf-con-006_prm_2",
                "label": "high-severity-patch-sla",
                "usage": "Maximum time to apply a high-severity security patch after vendor release",
                "values": [_SLA_90D],
            },
            {
                "id": "sscf-con-006_prm_3",
                "label": "eol-feature-disable-period",
                "usage": "Maximum time to disable end-of-life or deprecated features after vendor EOL notice",
                "values": ["60 days"],
            },
        ],
        "statement": (
            "Track and assure the application of security-relevant vendor patches within: "
            "{{ insert: param, sscf-con-006_prm_1 }} for critical patches, "
            "{{ insert: param, sscf-con-006_prm_2 }} for high-severity patches, and "
            "{{ insert: param, sscf-con-006_prm_3 }} for end-of-life feature disablement."
        ),
    },
    "sscf-dsp-001": {
        "params": [
            {
                "id": "sscf-dsp-001_prm_1",
                "label": "sensitive-data-access-review-frequency",
                "usage": "Frequency of access reviews for roles with sensitive data permissions",
                "values": ["quarterly"],
            }
        ],
        "statement": (
            "Restrict and continuously monitor access to sensitive business and personal data "
            "fields within SaaS platforms, aligned to data classification policy, with access "
            "reviews at minimum {{ insert: param, sscf-dsp-001_prm_1 }}."
        ),
    },
    "sscf-dsp-002": {
        "params": [
            {
                "id": "sscf-dsp-002_prm_1",
                "label": "external-sharing-max-duration",
                "usage": "Maximum duration for external sharing links before mandatory expiry",
                "values": [_SLA_30D],
            }
        ],
        "statement": (
            "Prevent unauthorized bulk data exports, report downloads, and API-based "
            "exfiltration from SaaS platforms, with external sharing links limited to "
            "{{ insert: param, sscf-dsp-002_prm_1 }} duration and requiring authentication."
        ),
    },
    "sscf-dsp-003": {
        "params": [
            {
                "id": "sscf-dsp-003_prm_1",
                "label": "classification-inventory-review-frequency",
                "usage": "Frequency at which the data classification inventory is reviewed and updated",
                "values": ["annually"],
            }
        ],
        "statement": (
            "Maintain a current data inventory and classification map for all data stored "
            "or processed within each SaaS platform, aligned to the organization's data "
            "classification policy, reviewed at minimum {{ insert: param, sscf-dsp-003_prm_1 }}."
        ),
    },
    "sscf-dsp-004": {
        "params": [
            {
                "id": "sscf-dsp-004_prm_1",
                "label": "transfer-mechanism-review-frequency",
                "usage": "Frequency of review for cross-border transfer mechanisms and vendor DPAs",
                "values": ["annually"],
            }
        ],
        "statement": (
            "Ensure that cross-border data transfers comply with applicable data sovereignty "
            "requirements, and that SaaS platform data residency settings align with "
            "organizational policy and regulatory obligations, with transfer mechanisms and "
            "vendor DPAs reviewed {{ insert: param, sscf-dsp-004_prm_1 }}."
        ),
    },
    "sscf-dsp-005": {
        "params": [
            {
                "id": "sscf-dsp-005_prm_1",
                "label": "minimum-retention-period",
                "usage": (
                    "Minimum data retention period before secure deletion is permitted "
                    "(may be extended by regulation-specific schedules)"
                ),
                "values": [_SLA_12M],
            }
        ],
        "statement": (
            "Apply and enforce data retention schedules with a minimum retention period of "
            "{{ insert: param, sscf-dsp-005_prm_1 }} and secure deletion procedures for data "
            "stored in SaaS platforms, ensuring data is not retained beyond its authorized lifecycle."
        ),
    },
    "sscf-dsp-006": {
        "params": [
            {
                "id": "sscf-dsp-006_prm_1",
                "label": "gdpr-dsar-response-sla",
                "usage": "Maximum response time for GDPR data subject access requests",
                "values": [_SLA_30D],
            },
            {
                "id": "sscf-dsp-006_prm_2",
                "label": "ccpa-dsar-response-sla",
                "usage": "Maximum response time for CCPA deletion and opt-out requests",
                "values": ["45 days"],
            },
        ],
        "statement": (
            "Ensure SaaS platform data handling supports organizational obligations to fulfill "
            "data subject rights requests within regulatory timeframes: "
            "GDPR {{ insert: param, sscf-dsp-006_prm_1 }}, "
            "CCPA {{ insert: param, sscf-dsp-006_prm_2 }}."
        ),
    },
    "sscf-iam-001": {
        "params": [
            {
                "id": "sscf-iam-001_prm_1",
                "label": "mfa-exception-review-frequency",
                "usage": "Frequency of mandatory review for documented MFA exemptions",
                "values": ["annually"],
            }
        ],
        "statement": (
            "Require multi-factor authentication (MFA) for all privileged accounts and all "
            "workforce accounts accessing SaaS platforms, with MFA exemptions subject to "
            "time-bound risk acceptance reviewed {{ insert: param, sscf-iam-001_prm_1 }}."
        ),
    },
    "sscf-iam-002": {
        "params": [
            {
                "id": "sscf-iam-002_prm_1",
                "label": "privileged-access-recertification-frequency",
                "usage": "Minimum frequency for privileged role recertification campaigns",
                "values": ["annually"],
            },
            {
                "id": "sscf-iam-002_prm_2",
                "label": "orphaned-privileged-account-disable-period",
                "usage": "Maximum time before an orphaned privileged account must be disabled after role owner departure",  # noqa: E501
                "values": [_SLA_30D],
            },
        ],
        "statement": (
            "Enforce formal approval, least-privilege assignment, and periodic recertification "
            "at minimum {{ insert: param, sscf-iam-002_prm_1 }} for all privileged roles in "
            "SaaS platforms, with orphaned privileged accounts disabled within "
            "{{ insert: param, sscf-iam-002_prm_2 }} of role owner departure."
        ),
    },
    "sscf-iam-003": {
        "params": [
            {
                "id": "sscf-iam-003_prm_1",
                "label": "break-glass-account-review-frequency",
                "usage": "Frequency of inventory review and credential rotation for break-glass accounts",
                "values": ["quarterly"],
            }
        ],
        "statement": (
            "Enforce enterprise IdP federation and harden SSO policy posture. Local "
            "authentication bypass paths must be disabled or restricted to break-glass "
            "accounts only, with break-glass accounts inventoried and reviewed "
            "{{ insert: param, sscf-iam-003_prm_1 }}."
        ),
    },
    "sscf-iam-004": {
        "params": [
            {
                "id": "sscf-iam-004_prm_1",
                "label": "offboarding-access-revocation-sla",
                "usage": "Maximum time to revoke all SaaS access after employee termination",
                "values": [_SLA_24H],
            },
            {
                "id": "sscf-iam-004_prm_2",
                "label": "role-change-access-revocation-sla",
                "usage": "Maximum time to revoke access not required in new role after a role change",
                "values": ["7 days"],
            },
            {
                "id": "sscf-iam-004_prm_3",
                "label": "stale-account-inactivity-period",
                "usage": "Inactivity period after which an account is flagged as stale for review or removal",
                "values": [_SLA_90D],
            },
        ],
        "statement": (
            "Ensure timely and complete revocation of SaaS platform access upon employee "
            "termination within {{ insert: param, sscf-iam-004_prm_1 }}, role change within "
            "{{ insert: param, sscf-iam-004_prm_2 }}, and regular access recertification "
            "identifying accounts inactive beyond {{ insert: param, sscf-iam-004_prm_3 }} "
            "for review and removal."
        ),
    },
    "sscf-iam-005": {
        "params": [
            {
                "id": "sscf-iam-005_prm_1",
                "label": "ownerless-service-account-disable-period",
                "usage": "Maximum time before a service account without an active owner must be disabled",
                "values": [_SLA_30D],
            },
            {
                "id": "sscf-iam-005_prm_2",
                "label": "service-account-review-frequency",
                "usage": "Minimum frequency for full service account inventory reviews",
                "values": ["annually"],
            },
        ],
        "statement": (
            "Maintain a complete inventory of all non-human identities (service accounts, "
            "integration users, automation identities) accessing SaaS platforms, with "
            "documented owners and scoped permissions, ownerless accounts disabled within "
            "{{ insert: param, sscf-iam-005_prm_1 }}, and {{ insert: param, sscf-iam-005_prm_2 }} "
            "full inventory reviews."
        ),
    },
    "sscf-iam-006": {
        "params": [
            {
                "id": "sscf-iam-006_prm_1",
                "label": "standard-user-session-timeout",
                "usage": "Maximum idle session timeout for standard (non-privileged) users",
                "values": ["8 hours"],
            },
            {
                "id": "sscf-iam-006_prm_2",
                "label": "privileged-user-session-timeout",
                "usage": "Maximum idle session timeout for privileged users",
                "values": ["30 minutes"],
            },
        ],
        "statement": (
            "Configure SaaS platform session controls to enforce idle timeout of "
            "{{ insert: param, sscf-iam-006_prm_1 }} for standard users and "
            "{{ insert: param, sscf-iam-006_prm_2 }} for privileged users, "
            "limit concurrent sessions, and restrict session tokens to authorized devices or networks."
        ),
    },
    "sscf-iam-007": {
        "params": [
            {
                "id": "sscf-iam-007_prm_1",
                "label": "jit-standard-max-duration",
                "usage": "Maximum JIT session duration for standard operational tasks",
                "values": ["4 hours"],
            },
            {
                "id": "sscf-iam-007_prm_2",
                "label": "jit-absolute-max-duration",
                "usage": "Absolute maximum JIT session duration under any circumstances",
                "values": [_SLA_24H],
            },
        ],
        "statement": (
            "Govern temporary privilege elevation through a formal request-approve-expire "
            "workflow, with maximum session duration of {{ insert: param, sscf-iam-007_prm_1 }} "
            "for most tasks and {{ insert: param, sscf-iam-007_prm_2 }} absolute maximum, "
            "avoiding standing privileged access for operational tasks."
        ),
    },
    "sscf-iam-008": {
        "params": [
            {
                "id": "sscf-iam-008_prm_1",
                "label": "external-access-max-duration",
                "usage": "Maximum duration for external party access before mandatory renewal",
                "values": [_SLA_12M],
            },
            {
                "id": "sscf-iam-008_prm_2",
                "label": "external-access-review-frequency",
                "usage": "Frequency of recertification for external user access",
                "values": ["quarterly"],
            },
        ],
        "statement": (
            "Govern access granted to external parties (contractors, partners, auditors) "
            "including scoped permissions, time-bound access limited to "
            "{{ insert: param, sscf-iam-008_prm_1 }}, MFA requirements, and "
            "{{ insert: param, sscf-iam-008_prm_2 }} recertification."
        ),
    },
    "sscf-ipy-001": {
        "params": [
            {
                "id": "sscf-ipy-001_prm_1",
                "label": "export-capability-test-frequency",
                "usage": "Frequency at which data export capabilities are tested as part of business continuity planning",  # noqa: E501
                "values": ["annually"],
            }
        ],
        "statement": (
            "Verify that SaaS platforms support data export in open, machine-readable formats "
            "sufficient to enable migration, regulatory fulfillment, and business continuity, "
            "with export capabilities tested {{ insert: param, sscf-ipy-001_prm_1 }}."
        ),
    },
    "sscf-ipy-002": {
        "params": [
            {
                "id": "sscf-ipy-002_prm_1",
                "label": "deprecated-api-disable-period",
                "usage": "Maximum time to disable deprecated or legacy API versions after successor release",
                "values": [_SLA_90D],
            }
        ],
        "statement": (
            "Govern all API access to SaaS platforms to ensure that APIs enforce "
            "authentication, authorization, rate limiting, and input validation, with "
            "deprecated or legacy API versions disabled within "
            "{{ insert: param, sscf-ipy-002_prm_1 }} of successor release."
        ),
    },
    "sscf-ipy-003": {
        "params": [
            {
                "id": "sscf-ipy-003_prm_1",
                "label": "high-risk-integration-assessment-frequency",
                "usage": "Frequency of vendor security assessments (SOC 2, ISO 27001, or equivalent) for high-risk integrations",  # noqa: E501
                "values": ["annually"],
            }
        ],
        "statement": (
            "Maintain an inventory of all integrations connecting to SaaS platforms and assess "
            "the security risk of data flows between connected systems, with "
            "{{ insert: param, sscf-ipy-003_prm_1 }} vendor security assessments for "
            "high-risk integrations."
        ),
    },
    "sscf-ipy-004": {
        "params": [
            {
                "id": "sscf-ipy-004_prm_1",
                "label": "exit-plan-review-frequency",
                "usage": "Minimum frequency for reviewing the SaaS platform exit plan",
                "values": ["annually"],
            }
        ],
        "statement": (
            "Document a SaaS platform exit plan that includes data retrieval procedures, "
            "migration timelines, and dependency mapping, reviewed "
            "{{ insert: param, sscf-ipy-004_prm_1 }} or upon significant platform contract renewal."
        ),
    },
    "sscf-ipy-005": {
        "params": [
            {
                "id": "sscf-ipy-005_prm_1",
                "label": "sub-processor-verification-frequency",
                "usage": "Frequency of verification of vendor sub-processor locations against approved jurisdictions",
                "values": ["annually"],
            }
        ],
        "statement": (
            "Ensure that SaaS platform configurations enforce data residency requirements "
            "and that data synchronized across cloud environments complies with applicable "
            "sovereignty regulations, with sub-processor locations verified "
            "{{ insert: param, sscf-ipy-005_prm_1 }}."
        ),
    },
    "sscf-log-001": {
        "params": [
            {
                "id": "sscf-log-001_prm_1",
                "label": "log-forwarding-sla",
                "usage": "Maximum delay between log generation and forwarding to centralized SIEM",
                "values": [_SLA_24H],
            },
            {
                "id": "sscf-log-001_prm_2",
                "label": "minimum-accessible-log-retention",
                "usage": "Minimum period of logs that must be immediately accessible for investigation",
                "values": [_SLA_90D],
            },
        ],
        "statement": (
            "Enable all required audit and security logs in SaaS platforms sufficient to "
            "support detection, forensics, and compliance reporting, forwarded to a centralized "
            "SIEM within {{ insert: param, sscf-log-001_prm_1 }} of generation with at minimum "
            "{{ insert: param, sscf-log-001_prm_2 }} of logs accessible for investigation."
        ),
    },
    "sscf-log-002": {
        "params": [
            {
                "id": "sscf-log-002_prm_1",
                "label": "admin-log-review-frequency",
                "usage": "Minimum frequency for reviewing administrative and configuration change audit logs",
                "values": ["monthly"],
            }
        ],
        "statement": (
            "Capture and monitor all administrative actions and security configuration changes "
            "within SaaS platforms, with log review at minimum "
            "{{ insert: param, sscf-log-002_prm_1 }} and alerts configured for high-risk admin actions."
        ),
    },
    "sscf-log-003": {
        "params": [
            {
                "id": "sscf-log-003_prm_1",
                "label": "log-retention-hot",
                "usage": "Minimum hot (immediately queryable) log retention period",
                "values": [_SLA_12M],
            },
            {
                "id": "sscf-log-003_prm_2",
                "label": "log-retention-cold",
                "usage": "Minimum cold (archival) log retention period",
                "values": ["36 months"],
            },
            {
                "id": "sscf-log-003_prm_3",
                "label": "cold-storage-restoration-test-frequency",
                "usage": "Frequency of testing restoration from cold log storage",
                "values": ["annually"],
            },
        ],
        "statement": (
            "Retain audit logs per organizational policy with a minimum of "
            "{{ insert: param, sscf-log-003_prm_1 }} hot retention and "
            "{{ insert: param, sscf-log-003_prm_2 }} cold retention, preserving log integrity "
            "to support investigations, with cold storage restoration tested "
            "{{ insert: param, sscf-log-003_prm_3 }}."
        ),
    },
    "sscf-log-004": {
        "params": [
            {
                "id": "sscf-log-004_prm_1",
                "label": "alert-routing-sla",
                "usage": "Maximum time for high-risk event alerts to reach the Security Operations queue after detection",  # noqa: E501
                "values": ["5 minutes"],
            },
            {
                "id": "sscf-log-004_prm_2",
                "label": "alert-suppression-review-frequency",
                "usage": "Frequency of review for alert suppression rules",
                "values": ["quarterly"],
            },
        ],
        "statement": (
            "Configure real-time monitoring rules and alerts for high-risk events in SaaS "
            "platforms, routed to the Security Operations team within "
            "{{ insert: param, sscf-log-004_prm_1 }} of event detection, with alert suppression "
            "rules reviewed {{ insert: param, sscf-log-004_prm_2 }}."
        ),
    },
    "sscf-log-005": {
        "params": [
            {
                "id": "sscf-log-005_prm_1",
                "label": "integration-health-alert-sla",
                "usage": "Maximum time for integration health monitoring to alert on log source outages",
                "values": [_SLA_1H],
            }
        ],
        "statement": (
            "Integrate SaaS platform logs into the centralized SIEM to enable cross-platform "
            "correlation, incident investigation, and compliance reporting, with integration "
            "health monitoring alerting on log source outages within "
            "{{ insert: param, sscf-log-005_prm_1 }}."
        ),
    },
    "sscf-log-006": {
        "params": [
            {
                "id": "sscf-log-006_prm_1",
                "label": "ueba-rule-review-frequency",
                "usage": "Frequency of review and tuning for behavioral analytics and UEBA rules",
                "values": ["semi-annually"],
            },
            {
                "id": "sscf-log-006_prm_2",
                "label": "data-access-anomaly-threshold",
                "usage": "Threshold for data access volume above baseline that triggers an anomaly alert",
                "values": ["10x above baseline"],
            },
        ],
        "statement": (
            "Apply behavioral analytics or UEBA capabilities to detect anomalous user activity "
            "patterns within SaaS platforms, with data access anomaly threshold at "
            "{{ insert: param, sscf-log-006_prm_2 }} and UEBA rules reviewed and tuned "
            "{{ insert: param, sscf-log-006_prm_1 }}."
        ),
    },
    "sscf-sef-001": {
        "params": [
            {
                "id": "sscf-sef-001_prm_1",
                "label": "threat-policy-review-frequency",
                "usage": "Frequency of review for automated threat policy rules",
                "values": ["quarterly"],
            }
        ],
        "statement": (
            "Detect and automatically block or quarantine high-risk behaviors within SaaS "
            "platforms through policy-driven controls, with threat policies reviewed "
            "{{ insert: param, sscf-sef-001_prm_1 }} and automated blocks generating SIEM alerts."
        ),
    },
    "sscf-sef-002": {
        "params": [
            {
                "id": "sscf-sef-002_prm_1",
                "label": "critical-alert-acknowledge-sla",
                "usage": "Maximum time to acknowledge a critical security alert",
                "values": ["15 minutes"],
            },
            {
                "id": "sscf-sef-002_prm_2",
                "label": "critical-alert-triage-sla",
                "usage": "Maximum time to complete triage of a critical security alert",
                "values": [_SLA_1H],
            },
            {
                "id": "sscf-sef-002_prm_3",
                "label": "high-alert-acknowledge-sla",
                "usage": "Maximum time to acknowledge a high-severity security alert",
                "values": [_SLA_1H],
            },
            {
                "id": "sscf-sef-002_prm_4",
                "label": "high-alert-triage-sla",
                "usage": "Maximum time to complete triage of a high-severity security alert",
                "values": ["4 hours"],
            },
        ],
        "statement": (
            "Ensure all high-risk SaaS security alerts are triaged within SLA and escalated "
            "to the appropriate incident response team: Critical alerts acknowledged within "
            "{{ insert: param, sscf-sef-002_prm_1 }} and triaged within "
            "{{ insert: param, sscf-sef-002_prm_2 }}; High alerts acknowledged within "
            "{{ insert: param, sscf-sef-002_prm_3 }} and triaged within "
            "{{ insert: param, sscf-sef-002_prm_4 }}."
        ),
    },
    "sscf-sef-003": {
        "params": [
            {
                "id": "sscf-sef-003_prm_1",
                "label": "tabletop-exercise-frequency",
                "usage": "Minimum frequency for incident response tabletop exercises or simulations",
                "values": ["annually"],
            }
        ],
        "statement": (
            "Maintain a documented incident response plan covering SaaS platform security "
            "events and conduct tabletop exercises or simulations at minimum "
            "{{ insert: param, sscf-sef-003_prm_1 }}."
        ),
    },
    "sscf-sef-004": {
        "params": [
            {
                "id": "sscf-sef-004_prm_1",
                "label": "forensic-preservation-test-frequency",
                "usage": "Frequency of testing forensic evidence preservation and chain-of-custody procedures",
                "values": ["annually"],
            }
        ],
        "statement": (
            "Ensure that SaaS platform audit logs and forensic artifacts can be preserved "
            "in a legally defensible manner to support incident investigations and e-discovery "
            "requests, with preservation procedures tested "
            "{{ insert: param, sscf-sef-004_prm_1 }}."
        ),
    },
    "sscf-sef-005": {
        "params": [
            {
                "id": "sscf-sef-005_prm_1",
                "label": "exception-max-duration",
                "usage": "Maximum duration for a security control exception before mandatory renewal or remediation",
                "values": [_SLA_12M],
            }
        ],
        "statement": (
            "Enforce time-bound, formally approved exceptions to security baseline controls, "
            "with maximum exception duration of {{ insert: param, sscf-sef-005_prm_1 }}, "
            "documented compensating controls, and tracking in the risk register."
        ),
    },
}


def _update_statement_parts(parts: list[dict], new_statement: str) -> list[dict]:
    """Replace statement prose with parameterized version; leave other parts unchanged."""
    return [{**p, "prose": new_statement} if p.get("name") == "statement" and new_statement else p for p in parts]


def _add_params_to_control(control: dict) -> dict:
    """Add params to a single control dict. Returns modified control."""
    control_id = control.get("id", "")
    if control_id not in PARAMS:
        return control  # no params defined for this control

    spec = PARAMS[control_id]
    params = spec.get("params", [])
    new_statement = spec.get("statement", "")

    # Build updated control: params before props (OSCAL 1.1.2 schema order)
    updated: dict = {"id": control["id"], "title": control["title"]}
    if params:
        updated["params"] = params
    for key in control:
        if key in ("id", "title"):
            continue
        if key == "parts":
            updated["parts"] = _update_statement_parts(control["parts"], new_statement)
        else:
            updated[key] = control[key]

    return updated


def main() -> None:
    if not CATALOG_PATH.exists():
        print(f"ERROR: catalog not found at {CATALOG_PATH}")
        print("Run from the repo root: python3 scripts/add_catalog_params.py")
        raise SystemExit(1)

    catalog = json.loads(CATALOG_PATH.read_text())

    updated_count = 0
    for group in catalog["catalog"]["groups"]:
        updated_controls = []
        for control in group.get("controls", []):
            updated = _add_params_to_control(control)
            if updated is not control:
                updated_count += 1
            updated_controls.append(updated)
        group["controls"] = updated_controls

    # Bump last-modified
    catalog["catalog"]["metadata"]["last-modified"] = "2026-03-10T00:00:00Z"
    catalog["catalog"]["metadata"]["remarks"] = (
        catalog["catalog"]["metadata"].get("remarks", "")
        + " Parameterized 2026-03-10: all 36 controls carry ODP params following NIST/FedRAMP "
        "patterns. Platform profiles (SBS/WSCC) set-parameters override defaults."
    )

    CATALOG_PATH.resolve().write_text(json.dumps(catalog, indent=2))
    print(f"Updated {updated_count} controls with ODP params in {CATALOG_PATH}")
    print("Next steps:")
    print("  1. Review: git diff config/sscf/sscf_v1_catalog.json")
    print("  2. Update SBS profile set-parameters: config/salesforce/sbs_v1_profile.json")
    print("  3. Update WSCC profile set-parameters: config/workday/wscc_v1_profile.json")


if __name__ == "__main__":
    main()
