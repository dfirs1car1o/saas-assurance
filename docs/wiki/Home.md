# saas-posture Wiki

Welcome to the **SaaS Security Multi-Agent System** wiki. AI-orchestrated assessment pipeline for Salesforce and Workday OSCAL/SSCF security assessments with NIST AI RMF governance gate and OWASP Agentic App security hardening. The 6-phase agent pipeline is fully automated; OSCAL artifact generation (POA&M, SSP, Assessment Results) runs as optional post-processing scripts.

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
| [Agent Reference](Agent-Reference) | All 10 agents — roles, models, triggers |
| [Skill Reference](Skill-Reference) | All 7 CLI tools — usage, inputs, outputs |
| [Pipeline Walkthrough](Pipeline-Walkthrough) | Step-by-step: from org → report |
| [CI-CD Reference](CI-CD-Reference) | Every CI job, what it checks, how to fix failures |
| [Security Model](Security-Model) | Rules, gates, escalation paths, OWASP Agentic App Top 10 controls |
| [Configuration Reference](Configuration-Reference) | All env vars, config files, YAML schemas |
| [Running a Dry Run](Running-a-Dry-Run) | Full pipeline without a live Salesforce org |
| [OpenSearch Dashboards](OpenSearch-Dashboards) | 3 pre-built dashboards — when to use each, how to load data, navigation guide |
| [Troubleshooting](Troubleshooting) | Common errors and fixes |

---

## What This Repo Does

This system connects to SaaS platforms, runs OSCAL and CSA SSCF security assessments, and generates governance outputs for:
- **Application owners** — remediation backlog with priority actions and due dates (Markdown)
- **Security governance review** — full DOCX + Markdown report with Executive Scorecard, Domain Posture chart, NIST AI RMF review, and sorted control matrix

Platform controls chain through **platform OSCAL catalog → SSCF → CCM v4.1 → regulatory crosswalk** (SOX, HIPAA, SOC2, ISO 27001, NIST 800-53, PCI DSS, GDPR) automatically. For organizations using AI-enabled SaaS (Salesforce Einstein, Workday AI), an **AICM v1.0.3 crosswalk** (EU AI Act / ISO 42001 / NIST AI 600-1 / BSI AI C4) is generated as a companion output.

The pipeline is fully agentic: `gpt-5.3-chat-latest` orchestrates 7 CLI tools and 10 specialist agents over a 14-turn ReAct loop with enforced tool sequencing. No human input needed once triggered. Every tool call is logged to a structured JSONL audit trail.

---

## Pipeline at a Glance

6 automated phases, 7 CLI skills, 10 specialist agents, 14-turn ReAct orchestration loop.

### Automated Pipeline (agent-loop)

| Phase | Tool | Output | Notes |
|---|---|---|---|
| **1 · Collect** | `sfdc-connect` / `workday-connect` | `sfdc_raw.json` / `workday_raw.json` | Read-only; JWT Bearer (SFDC) or OAuth 2.0 (Workday) |
| **2 · Assess** | `oscal-assess` + `oscal_gap_map.py` | `gap_analysis.json` + `backlog.json` | 35 SBS controls (SFDC) / 30 WSCC controls (Workday) |
| **3 · Score** | `sscf-benchmark` | `sscf_report.json` | RED / AMBER / GREEN per SSCF domain |
| **4 · NIST Gate** | `nist-review` | `nist_review.json` | clear / flag / block verdict; block stops delivery |
| **5 · AICM Crosswalk** | `gen_aicm_crosswalk.py` | `aicm_coverage.json` | 243 controls, 18 domains; EU AI Act / ISO 42001 / NIST AI 600-1 |
| **6 · Report** | `report-gen` | `.md` + `.docx` | App-owner + security-governance audience split |

**Sequencing is enforced in code** — the harness `_TOOL_REQUIRES` map blocks out-of-order tool calls before dispatch. Every invocation is logged to `audit.jsonl`.

### Post-processing (run manually after pipeline)

These scripts are **not** orchestrated tool calls. Run them after `agent-loop` completes if OSCAL machine-readable artifacts are needed for GRC tooling or audit packages.

| Script | Output | Description |
|---|---|---|
| `python scripts/gen_poam.py` | `poam.json` | OSCAL 1.1.2 persistent Plan of Action and Milestones |
| `python scripts/gen_assessment_results.py` | `assessment_results.json` | OSCAL 1.1.2 Assessment Results |
| `python scripts/gen_ssp.py` | `ssp.json` | OSCAL 1.1.2 per-org System Security Plan |

---

## Bare Minimum to Run

```text
Python 3.11+  +  git  +  pip install -e ".[dev]"  +  .env with API keys
```

No Docker. No Node.js. No cloud accounts beyond OpenAI + Salesforce.

---

## Quick Start (Any Platform)

```bash
git clone git@github.com:dfirs1car1o/saas-posture.git
cd saas-posture
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in OPENAI_API_KEY + Salesforce credentials
pytest tests/ -v       # 191/191 should pass (offline, no API keys needed)
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
| All agents | ✅ Done | Unified model: all 10 agents use `gpt-5.3-chat-latest` |
| Executive reports | ✅ Done | Python-rendered scorecard, domain chart, sorted matrix |
| finish() tool | ✅ Done | Orchestrator exits cleanly; _MAX_TURNS→14 |
| OSCAL Catalogs | ✅ Done | SSCF catalog, SBS catalog, Workday catalog — all OSCAL 1.1.2 |
| Schema v2 | ✅ Done | `baseline_assessment_schema.json` v2 — platform-agnostic, CCM chains |
| SSCF→CCM bridge | ✅ Done | 14 SSCF controls mapped to CCM v4.1; automatic regulatory crosswalk |
| Workday Blueprint | ✅ Done | 30-control WSCC catalog, SSCF mapping, connector blueprint |
| Workday Connector | ✅ Done | `skills/workday_connect/workday_connect.py` — OAuth 2.0, 30 controls, 21 tests |
| Workday Agent-Loop | ✅ Done | `--platform workday` flag, workday_connect_collect tool, Workday task prompt |
| Report: POA&M + Not Assessed | ✅ Done | POA&M (POAM-IDs, owners, milestones) + auditor appendix in security DOCX |
| Report: OSCAL Provenance | ✅ Done | Catalog → Profile → Component Def → CCM chain table in every report |
| Report: Table borders + Description | ✅ Done | Full single-line borders on all DOCX tables; Description column added |
| **OpenSearch** | **✅ Done** | Docker stack + OpenSearch + 3 pre-built dashboards (combined, Salesforce, Workday) |
| **OSCAL P0** | **✅ Done** | ODP parameterization — all 36 SSCF controls carry `params`; SBS (59) + WSCC (50) `set-parameters` |
| **OSCAL P1** | **✅ Done** | `gen_resolved_profile.py` — resolved catalogs for SBS (35 controls) and WSCC (30 controls); component def upgrades with `control-origination` + `responsibility` |
| **OSCAL P2** | **✅ Done** | `gen_assessment_results.py` (OSCAL AR), `gen_ssp.py` (per-org SSP), commercial SSP template; all wired into CI |
| **AICM** | **✅ Done** | CSA AI Controls Matrix v1.0.3 crosswalk — 243 controls, 18 domains; `config/aicm/` + `gen_aicm_crosswalk.py`; maps to EU AI Act / ISO 42001 / NIST AI 600-1 / BSI AI C4 |
| **AICM Loop Wiring** | **✅ Done** | `gen_aicm_crosswalk` registered as dispatchable tool in agent loop; Step 5b in both Salesforce + Workday task prompts; `schedule.yml` Phase 6 passes `--aicm-coverage` |
| **Tool Sequencing Gate** | **✅ Done** | `_TOOL_REQUIRES` dependency map in `harness/loop.py` — enforces pipeline order in code; sequencing violations return structured error JSON (OWASP A2 Excessive Agency) |
| **Qdrant API Key Auth** | **✅ Done** | `QDRANT_API_KEY` env var wired into networked Qdrant config; documented in `.env.example` (OWASP A3 Memory Poisoning) |
| **OWASP Agentic App Hardening** | **✅ Done** | Full OWASP Top 10 for Agentic Applications 2026 threat model; input path validation, org sanitization, memory guard, structured audit log, Semgrep CI gates; 94 tests |
