# Architecture Overview

## Design Philosophy

**CLIs not MCPs.** Every tool is a Python CLI callable from the shell. No hidden service state. No Docker-required infrastructure. The agent loop is an OpenAI `tool_use` ReAct loop.

---

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│         agent-loop  (gpt-5.3-chat-latest orchestrator)                      │
│         OpenAI tool_use ReAct loop · max 14 turns · 9 agents                │
└──┬──────────┬──────────┬──────────┬──────────┬──────────┬────────────────────┘
   │          │          │          │          │          │
   │ Phase 1  │ Phase 2  │ Phase 3  │ Phase 4  │Phase 5-6 │ Phase 5 (OSCAL docs)
   ▼          ▼          ▼          ▼          ▼          ▼
sfdc-      workday-   oscal-     oscal_    sscf-      nist-
connect    connect    assess     gap_map   benchmark  review
(SFDC)     (WD)       (assess)   (map)     (score)    (gate)
   │          │          │           │          │          │
sfdc_raw  workday_raw gap_analysis backlog  sscf_report nist_review
 .json      .json       .json       .json     .json       .json
   └──────────┴──────────┴───────────┴──────────┘
                              │
              ┌───────────────┼───────────────────────────────┐
              │               │                               │
    ┌─────────▼──────┐ ┌──────▼──────────┐ ┌────────────────▼──────┐
    │   report-gen    │ │  gen_poam +     │ │  gen_aicm_crosswalk   │
    │  app-owner MD   │ │  gen_assessment │ │  SSCF → AICM v1.0.3   │
    │  security MD    │ │  _results +     │ │  243 controls         │
    │  + DOCX         │ │  gen_ssp        │ │  18 domains           │
    └─────────────────┘ │  (OSCAL 1.1.2)  │ │  aicm_coverage.json   │
                        └─────────────────┘ └───────────────────────┘
```

---

## Agent Architecture

### 9 Agents

| Agent | Model | Role | Tools |
|---|---|---|---|
| `orchestrator` | gpt-5.3-chat-latest | Routes tasks, manages the ReAct loop, quality gates | All CLI tools |
| `collector` | gpt-5.3-chat-latest | Extracts Salesforce org config (REST/Metadata) and Workday config (OAuth 2.0/RaaS/REST) | sfdc-connect, workday-connect |
| `assessor` | gpt-5.3-chat-latest | Maps findings to OSCAL/SBS/SSCF controls | oscal-assess, oscal_gap_map |
| `reporter` | gpt-5.3-chat-latest | Generates DOCX/MD governance outputs | report-gen |
| `nist-reviewer` | gpt-5.3-chat-latest | Validates outputs against NIST AI RMF | None (text analysis) |
| `security-reviewer` | gpt-5.3-chat-latest | AppSec + DevSecOps review of CI/CD and skills | None (text analysis) |
| `sfdc-expert` | gpt-5.3-chat-latest | On-call Salesforce/Apex specialist | None (text + code) |
| `workday-expert` | gpt-5.3-chat-latest | On-call Workday HCM/Finance/RaaS specialist | None (text + code) |
| `container-expert` | gpt-5.3-chat-latest | Docker Compose, OpenSearch, JVM tuning specialist | None (text + config) |

### Model Assignment Rationale

- **gpt-5.3-chat-latest** for all agents: complex routing, API extraction, control mapping, regulatory QA, security review, and report generation
- **No tools for review/expert agents**: text-only analysis prevents accidental state modification
- **Override via env:** `LLM_MODEL_ORCHESTRATOR`, `LLM_MODEL_ANALYST`, `LLM_MODEL_REPORTER`

> **Azure OpenAI Government:** Supported as a drop-in for FedRAMP/IL5 environments via `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_VERSION`.

---

## 6 Skills (CLI Tools)

| Skill | Binary | Platform | Purpose |
|---|---|---|---|
| `sfdc-connect` | `skills/sfdc_connect/sfdc_connect.py` | Salesforce | Authenticates via JWT Bearer; collects SecuritySettings, Auth, Permissions, Network, Connected Apps |
| `workday-connect` | `skills/workday_connect/workday_connect.py` | Workday | Authenticates via OAuth 2.0; collects 30 WSCC controls via RaaS/REST/manual questionnaire |
| `oscal-assess` | `skills/oscal_assess/oscal_assess.py` | Both | Evaluates platform controls against OSCAL catalog; produces findings with status and severity |
| `sscf-benchmark` | `skills/sscf_benchmark/sscf_benchmark.py` | Both | Maps findings to SSCF domains; calculates domain scores and overall posture (RED/AMBER/GREEN) |
| `nist-review` | `skills/nist_review/nist_review.py` | Both | Validates assessment outputs against NIST AI RMF 1.0; issues pass/flag/block verdict |
| `report-gen` | `skills/report_gen/report_gen.py` | Both | Generates audience-specific outputs: app-owner Markdown, security Markdown + DOCX |
| `gen_aicm_crosswalk` | `scripts/gen_aicm_crosswalk.py` | Both | Maps SSCF findings to CSA AICM v1.0.3 (243 controls, 18 domains); produces `aicm_coverage.json` with per-domain posture and gap analysis |

---

## Data Flow

### Salesforce Pipeline

```
sfdc-connect collect (--platform salesforce)
    → sfdc_raw.json
        → oscal-assess assess
            → gap_analysis.json (35 SBS controls)
                → oscal_gap_map.py
                    → backlog.json (SSCF-mapped remediation items)
                        → sscf-benchmark benchmark
                            → sscf_report.json (RED/AMBER/GREEN per domain)
                                → nist-review assess
                                    → nist_review.json (pass/flag/block verdict)
                                        → report-gen generate (×2)
                                            → {org}_remediation_report.md   (app-owner)
                                            → {org}_security_assessment.md  (security)
                                            → {org}_security_assessment.docx
```

### Workday Pipeline

```
workday-connect collect (--platform workday)
    → workday_raw.json
        → oscal-assess assess (--platform workday)
            → gap_analysis.json (30 WSCC controls)
                → oscal_gap_map.py (SSCF-* direct path)
                    → backlog.json
                        → sscf-benchmark benchmark
                            → sscf_report.json
                                → nist-review assess (--platform workday)
                                    → nist_review.json
                                        → report-gen generate (×2)
```

### Drift Detection (Re-assessment)

```
scripts/drift_check.py --baseline <prior_backlog.json> --current <new_backlog.json>
    → drift_report.json  (regression / improvement / resolved / new_finding / unchanged)
    → drift_report.md    (tables with change icons)
```

All outputs land in `docs/oscal-salesforce-poc/generated/<org>/<date>/`.

---

## Report Structure

Reports are assembled from deterministic Python-rendered sections plus a focused LLM narrative:

```
[Gate banner]                  ← ⛔ block / 🚩 flag if NIST verdict requires it
Executive Scorecard            ← overall score + severity × status matrix        [HARNESS]
Domain Posture (ASCII chart)   ← bar chart of all SSCF domain scores             [HARNESS]
OSCAL Framework Provenance     ← catalog → profile → ISO 27001 → CCM chain      [HARNESS]
CCM v4.1 Regulatory Crosswalk  ← fail/partial → SOX/HIPAA/SOC2/PCI/GDPR        [HARNESS]
                                  (security audience only; ISO column = via CCM)
ISO 27001:2022 SoA             ← Statement of Applicability: all 93 Annex A      [HARNESS]
                                  controls with applicability, status, implementation,
                                  SSCF ref, owner, evidence (security audience only)
Immediate Actions (Top 10)     ← sorted critical/fail findings                   [HARNESS]
Executive Summary + Analysis   ← LLM narrative (2 sections only)                 [LLM]
Full Control Matrix            ← complete sorted findings table                   [HARNESS]
Plan of Action & Milestones    ← POAM-IDs, owners, due dates, status             [HARNESS]
Not Assessed Controls          ← out-of-scope appendix for auditors              [HARNESS]
NIST AI RMF Governance Review  ← function table + blockers + recs                [HARNESS]
```

---

## Optional: Visualization Layer (OpenSearch + Docker)

The pipeline runs fully as plain Python with no infrastructure. For teams who want continuous monitoring with trending dashboards:

```
docker compose up -d   # starts OpenSearch + OpenSearch Dashboards + dashboard-init
```

Three pre-built dashboards auto-import on startup:

| Dashboard | Purpose |
|---|---|
| SSCF Security Posture Overview | Combined cross-platform governance view |
| Salesforce Security Posture | Salesforce-only findings + SBS quarterly review |
| Workday Security Posture | Workday-only findings + WSCC compliance review |

Export assessment data to OpenSearch after each run:
```bash
python scripts/export_to_opensearch.py --auto --org <alias> --date $(date +%Y-%m-%d)
```

See [`docs/wiki/OpenSearch-Dashboards.md`](OpenSearch-Dashboards.md) and [`docs/wiki/Continuous-Monitoring.md`](Continuous-Monitoring.md) for full setup.

---

## Memory Architecture

Session memory uses **Mem0 + Qdrant**. By default:
- `QDRANT_IN_MEMORY=1` — in-process Qdrant (no Docker needed)
- Memory stores: org alias, prior assessment score, critical findings
- Each new assessment loads prior org context as prefix to the first user message
- This allows the orchestrator to detect regression ("score dropped from 48% to 34%")

For persistent cross-session memory, run a Qdrant container and set `QDRANT_HOST=localhost`.

---

## Control Mapping Architecture

```
Platform Config (Salesforce or Workday)
       ↓
  Platform OSCAL Catalog
    SBS:  config/salesforce/sbs_v1_profile.json   (35 controls, OSCAL 1.1.2)
    WSCC: config/workday/wscc_v1_profile.json      (30 controls, OSCAL 1.1.2)
       ↓
  Platform → SSCF mapping
    SBS:  config/salesforce/sbs_to_sscf_mapping.yaml
    WSCC: control IDs are SSCF-* directly (no intermediate mapping)
       ↓
  SSCF Catalog (config/sscf/sscf_v1_catalog.json — 36 controls, OSCAL 1.1.2)
       ↓
  SSCF → ISO 27001:2022 direct mapping (config/iso27001/sscf_to_iso27001_mapping.yaml)
       ↓  29 of 93 Annex A controls · SoA auto-generated in security report
  SSCF → CCM v4.1 bridge (config/sscf/sscf_to_ccm_mapping.yaml)
       ↓
  CCM v4.1 (config/ccm/ccm_v4.1_oscal_ref.yaml — 197 controls)
       ↓
  Regulatory crosswalk: SOX · HIPAA · SOC2 TSC · ISO 27001 (via CCM) · NIST 800-53 · PCI DSS · GDPR
       ↓
  Domain Scores (IAM, Data Security, Configuration Hardening, Logging, Governance, CKM)
```

---

## Key File Locations

| Location | Purpose |
|---|---|
| `mission.md` | Agent identity + authorized scope (loaded every session) |
| `AGENTS.md` | Canonical agent roster |
| `agents/orchestrator.md` | Orchestrator routing table, quality gates, finish() trigger |
| `config/sscf/sscf_v1_catalog.json` | SSCF OSCAL 1.1.2 catalog (36 controls, 6 domains) |
| `config/sscf/sscf_to_ccm_mapping.yaml` | SSCF→CCM v4.1 bridge |
| `config/salesforce/sbs_v1_profile.json` | SBS OSCAL 1.1.2 sub-profile (35 controls) |
| `config/workday/wscc_v1_profile.json` | WSCC OSCAL 1.1.2 sub-profile (30 controls) |
| `schemas/baseline_assessment_schema.json` | v2 platform-agnostic assessment schema |
| `skills/workday_connect/SKILL.md` | Workday connector reference (transport matrix, auth, output shape) |
| `scripts/drift_check.py` | Drift detection: compare two backlog.json snapshots |
| `scripts/export_to_opensearch.py` | Exports assessment data to OpenSearch for dashboards |
| `docs/oscal-salesforce-poc/generated/` | All assessment outputs |
| `docs/architecture.png` | Auto-generated reference architecture diagram |
