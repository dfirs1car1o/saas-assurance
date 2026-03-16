# saas-assurance Wiki

Welcome to the **SaaS Security Multi-Agent System** wiki. AI-orchestrated, tool-sequenced assessment pipeline for Salesforce and Workday OSCAL/SSCF security assessments with NIST AI RMF governance gate and OWASP Agentic App security hardening. The pipeline runs automated from collection through report generation; delivery can be held by quality gates and human acknowledgment. OSCAL artifacts (POA&M, SSP, Assessment Results) are post-processing scripts, not orchestrated pipeline steps.

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

`gpt-5.3-chat-latest` orchestrates 7 CLI tools and 10 specialist agents over a 14-turn ReAct loop with enforced tool sequencing. Every tool call is logged to a structured JSONL audit trail.

---

## Pipeline at a Glance

7 CLI skills, 10 specialist agents, 14-turn ReAct orchestration loop.

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
git clone git@github.com:dfirs1car1o/saas-posture.git saas-assurance
cd saas-assurance
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in OPENAI_API_KEY + Salesforce credentials
pytest tests/ -v       # full offline suite — no API keys needed
agent-loop run --dry-run --env dev --org test-org
```

---

## Capabilities

| Area | What's included |
|---|---|
| **Platforms** | Salesforce (JWT Bearer, 35 SBS controls) · Workday (OAuth 2.0, 30 WSCC controls) |
| **Agents** | 10 specialists — orchestrator, collector, assessor, reporter, nist-reviewer, delivery-reviewer, sfdc-expert, workday-expert, container-expert, security-reviewer |
| **CLI Skills** | 7 tools: `sfdc-connect`, `workday-connect`, `oscal-assess`, `sscf-benchmark`, `nist-review`, `report-gen`, `gen-aicm-crosswalk` |
| **OSCAL** | OSCAL 1.1.2 catalogs (SSCF · SBS · WSCC) · resolved profiles · ODP parameterization · post-processing scripts for POA&M, SSP, Assessment Results |
| **Control Frameworks** | SSCF → CCM v4.1 → SOX / HIPAA / SOC2 / ISO 27001 / NIST 800-53 / PCI DSS / GDPR · AICM v1.0.3 (243 controls, EU AI Act / ISO 42001 / NIST AI 600-1 / BSI AI C4) |
| **Reports** | Executive Markdown + DOCX · app-owner remediation backlog · governance annex (POA&M, OSCAL provenance, CCM crosswalk, ISO 27001 SoA) · evidence methodology |
| **Gates** | NIST AI RMF gate (block / flag / pass) · critical-finding block · delivery-reviewer QA (credential exposure, scope violations) · tool sequencing (`_TOOL_REQUIRES`) |
| **Security hardening** | OWASP Agentic App Top 10 threat model · path validation · org sanitization · memory guard · structured JSONL audit log · Semgrep + Bandit + zizmor CI gates |
| **Observability** | OpenSearch + 3 pre-built dashboards (combined, Salesforce, Workday) · drift detection across runs |
| **CI** | ruff · bandit · pip-audit · gitleaks · CodeQL · grype SBOM · zizmor · SonarCloud · full offline pytest suite |
