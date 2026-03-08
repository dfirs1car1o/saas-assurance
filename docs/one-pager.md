# saas-posture — One-Pager

**Automated SaaS Security Assessment · OSCAL · CSA SSCF · NIST AI RMF**

---

## The Problem

Enterprise SaaS platforms — Salesforce, Workday, and others — accumulate security configuration drift over time. Password policies loosen. OAuth scopes expand. Audit logging gets disabled. Manual security reviews happen once a year, if at all. By the time a finding reaches a governance report, it is already months stale.

Security teams need continuous, evidence-backed posture data that maps to the frameworks auditors actually use — SOX, HIPAA, SOC 2, ISO 27001, PCI DSS — without requiring expensive consultants or custom one-off scripts for every platform.

---

## What saas-posture Does

saas-posture is an open-source, multi-agent AI system that automates the full security assessment lifecycle for SaaS platforms. It connects read-only to live orgs, maps every finding to industry control frameworks, validates its own AI outputs against NIST AI RMF 1.0, and generates governance-grade evidence packages — all without touching a single record.

**Six phases. Fully automated.**

| Phase | What Happens |
|---|---|
| **1 · Collect** | Read-only API queries extract security configuration from Salesforce and Workday |
| **2 · Assess** | Findings are mapped to OSCAL catalogs (SBS v1.0 / WSCC v0.2.0) and CSA SSCF domains |
| **3 · Score** | SSCF benchmark produces RED / AMBER / GREEN domain scores with CCM v4.1 regulatory crosswalk |
| **4 · Gate** | NIST AI RMF 1.0 reviewer validates AI outputs — issues clear / flag / block verdicts before delivery |
| **5 · Report** | Audience-specific reports: remediation-focused (app owners) and full technical + regulatory (security governance) |
| **6 · Monitor** | Findings indexed into OpenSearch; three pre-built dashboards surface trends over time |

---

## Platform Coverage

| Platform | Controls | Framework | Auth |
|---|---|---|---|
| **Salesforce** | 45 SBS controls across 10 domains | SBS v1.0 (OSCAL 1.1.2) | JWT Bearer or SOAP |
| **Workday** | 30 WSCC controls across 6 domains | WSCC v0.2.0 (OSCAL 1.1.2) | OAuth 2.0 Client Credentials |

**Regulatory crosswalk built in:** SOX · HIPAA · SOC 2 · ISO 27001 · NIST 800-53 · PCI DSS · GDPR

---

## What You Get

**For application owners:**
- Plain-language remediation report: what is failing, who owns it, when it is due
- Critical and high findings table with auto-populated due dates (critical = 7 days, high = 30 days)
- POA&M (Plan of Action & Milestones) with POAM-IDs ready for your GRC tool

**For security governance:**
- Full OSCAL provenance chain (Catalog → Profile → Component Definition → CCM → Regulatory crosswalk → POA&M)
- NIST AI RMF governance review embedded in every report
- SSCF domain heatmap — visual posture by domain
- Not Assessed Controls appendix — auditor-ready evidence of assessment completeness
- DOCX output compatible with standard governance workflows

**For continuous monitoring:**
- OpenSearch dashboards: combined posture, per-platform drill-down, trend over time
- Scheduled runs exportable to JSON and indexed automatically
- Configurable drift alerts

---

## Architecture

```
Collector Agent          reads SaaS APIs (read-only)
    ↓
Assessor Agent           maps to OSCAL / SSCF / CCM
    ↓
NIST Reviewer Agent      validates AI output integrity (block / flag / clear)
    ↓
Reporter Agent           generates Markdown + DOCX governance packages
    ↓
OpenSearch Stack         indexes findings, serves pre-built dashboards
```

Seven agents. Six skill CLIs. One orchestrator managing a 14-turn ReAct loop. No human in the loop required for standard runs — humans re-enter only on block verdicts or critical findings requiring acknowledgment.

---

## Security Posture

- **Read-only by design** — no write operations against any SaaS platform
- **No credentials in artifacts** — evidence files contain org aliases, not tokens
- **AI output validated** — every report passes through NIST AI RMF gate; dry-run and live collections explicitly distinguished
- **CI/CD security** — gitleaks, pip-audit, bandit, CodeQL, dependency-review on every PR
- **Open source** — Apache 2.0; self-hosted; no data leaves your infrastructure

---

## Get Started

```bash
git clone https://github.com/dfirs1car1o/saas-posture
cd saas-posture && pip install -e .
cp .env.example .env   # add credentials
agent-loop run --env dev --org <your-org> --approve-critical
```

Full documentation: **github.com/dfirs1car1o/saas-posture/wiki**

---

*saas-posture is open source (Apache 2.0). Built with Claude Code, OpenAI GPT-5.3, and the OpenSearch stack.*
