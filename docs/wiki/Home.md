# saas-posture Wiki

Welcome to the **SaaS Security Multi-Agent System** wiki. Fully automated AI pipeline for Salesforce OSCAL/SSCF security assessments.

---

## Quick Links

| Page | What it covers |
|---|---|
| [Onboarding](Onboarding) | Get running in 10 minutes (any platform) |
| [macOS Setup](macOS-Setup) | Apple Silicon + Intel — step by step |
| [Linux Setup](Linux-Setup) | Ubuntu, Debian, RHEL, WSL2 — step by step |
| [Windows Setup](Windows-Setup) | Corporate Windows machine with VS Code — step by step |
| [Architecture Overview](Architecture-Overview) | How the system is designed |
| [OSCAL Guide](OSCAL-Guide) | What OSCAL is and how we use it — catalogs, profiles, component definitions, diagrams |
| [Agent Reference](Agent-Reference) | All 7 agents — roles, models, triggers |
| [Skill Reference](Skill-Reference) | All 5 CLI tools — usage, inputs, outputs |
| [Pipeline Walkthrough](Pipeline-Walkthrough) | Step-by-step: from org → report |
| [CI-CD Reference](CI-CD-Reference) | Every CI job, what it checks, how to fix failures |
| [Security Model](Security-Model) | Rules, gates, escalation paths |
| [Configuration Reference](Configuration-Reference) | All env vars, config files, YAML schemas |
| [Running a Dry Run](Running-a-Dry-Run) | Full pipeline without a live Salesforce org |
| [OpenSearch Dashboards](OpenSearch-Dashboards) | 3 pre-built dashboards — when to use each, how to load data, navigation guide |
| [Troubleshooting](Troubleshooting) | Common errors and fixes |

---

## What This Repo Does

This system connects to SaaS platforms, runs OSCAL and CSA SSCF security assessments, and generates governance outputs for:
- **Application owners** — remediation backlog with priority actions and due dates (Markdown)
- **Security governance review** — full DOCX + Markdown report with Executive Scorecard, Domain Posture chart, NIST AI RMF review, and sorted control matrix

Platform controls chain through **platform OSCAL catalog → SSCF → CCM v4.1 → regulatory crosswalk** (SOX, HIPAA, SOC2, ISO 27001, NIST 800-53, PCI DSS, GDPR) automatically.

The pipeline is fully agentic: `gpt-5.3-chat-latest` orchestrates 5 CLI tools and 7 specialist agents over a 14-turn ReAct loop. No human input needed once triggered.

---

## Bare Minimum to Run

```text
Python 3.11+  +  git  +  pip install -e .  +  .env with API keys
```

No Docker. No Node.js. No cloud accounts beyond OpenAI + Salesforce.

---

## Quick Start (Any Platform)

```bash
git clone git@github.com:dfirs1car1o/saas-posture.git
cd saas-posture
python3 -m venv .venv && source .venv/bin/activate
pip install -e . && pip install pytest
cp .env.example .env   # fill in OPENAI_API_KEY + Salesforce credentials
pytest tests/ -v       # 37/37 should pass (offline, no API keys needed)
agent-loop run --dry-run --env dev --org test-org
```

---

## Current Status

| Phase | Status | Deliverable |
|---|---|---|
| 1 | ✅ Done | `sfdc-connect` CLI + full CI stack |
| 2 | ✅ Done | `oscal-assess` + `sscf-benchmark` CLIs |
| 3 | ✅ Done | `agent-loop` harness + Mem0 session memory |
| 4 | ✅ Done | `report-gen` DOCX/MD governance output |
| 5 | ✅ Done | Auto-regenerating architecture diagram |
| 6 | ✅ Done | CI hardening, security-reviewer agent |
| NIST review | ✅ Done | nist-review skill, 7-step pipeline, gate logic |
| JWT Auth | ✅ Done | JWT Bearer flow, live verified |
| sfdc-expert | ✅ Done | On-call Apex/SFDC specialist agent |
| SDK Migration | ✅ Done | Anthropic → OpenAI (gpt-5.3-chat-latest / gpt-4o-mini) |
| Executive reports | ✅ Done | Python-rendered scorecard, domain chart, sorted matrix |
| finish() tool | ✅ Done | Orchestrator exits cleanly; _MAX_TURNS→14 |
| OSCAL Catalogs | ✅ Done | SSCF catalog, SBS catalog, Workday catalog — all OSCAL 1.1.2 |
| Schema v2 | ✅ Done | `baseline_assessment_schema.json` v2 — platform-agnostic, CCM chains |
| SSCF→CCM bridge | ✅ Done | 14 SSCF controls mapped to CCM v4.1; automatic regulatory crosswalk |
| Workday Blueprint | ✅ Done | 30-control WSCC catalog, SSCF mapping, connector blueprint (Phase C) |
| Workday Connector | ✅ Done | `skills/workday_connect/workday_connect.py` — OAuth 2.0, 30 controls, 21 tests (Phase E) |
| Workday Agent-Loop | ✅ Done | `--platform workday` flag, workday_connect_collect tool, Workday task prompt (Phase F) |
| Report: POA&M + Not Assessed | ✅ Done | POA&M (POAM-IDs, owners, milestones) + auditor appendix in security DOCX (Phase G) |
| Report: OSCAL Provenance | ✅ Done | Catalog → Profile → Component Def → CCM chain table in every report |
| Report: Table borders + Description | ✅ Done | Full single-line borders on all DOCX tables; Description column added |
| **Phase H** | **✅ Done** | Docker stack + OpenSearch + 3 pre-built dashboards (combined, Salesforce, Workday) |
| **OSCAL P0** | **✅ Done** | ODP parameterization — all 36 SSCF controls carry `params`; SBS (59) + WSCC (50) `set-parameters` |
| **OSCAL P1** | **✅ Done** | `gen_resolved_profile.py` — resolved catalogs for SBS (35 controls) and WSCC (30 controls); component def upgrades with `control-origination` + `responsibility` |
| **OSCAL P2** | **✅ Done** | `gen_assessment_results.py` (OSCAL AR), `gen_ssp.py` (per-org SSP), commercial SSP template; all wired into CI |
| **AICM** | **✅ Done** | CSA AI Controls Matrix v1.0.3 crosswalk — 243 controls, 18 domains; `config/aicm/` + `gen_aicm_crosswalk.py`; maps to EU AI Act / ISO 42001 / NIST AI 600-1 / BSI AI C4 |
