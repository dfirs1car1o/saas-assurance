# Architecture Blueprint — saas-assurance

> Read this before running anything. It explains every agent, every skill, every model, and how they connect.

---

## 1. System Purpose

`saas-assurance` is a read-only security assessment pipeline. It connects to Salesforce orgs, extracts configuration data, maps findings against OSCAL/SBS/SSCF control frameworks, and produces governance-grade evidence packages for Security Team review cycles.

**What it does not do:**
- Write to any Salesforce org
- Store credentials outside the session
- Make security decisions autonomously (humans review all findings)
- Access record-level data (Contacts, Accounts, Opportunities)

---

## 2. Multi-Agent Architecture

### Pattern: Orchestrator → Workers (Sequential Pipeline)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HUMAN INPUT                                  │
│  "Assess the auth config of org: myorg.salesforce.com"              │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR — gpt-5.3-chat-latest                                     │
│  File: agents/orchestrator.md                                       │
│                                                                      │
│  • Reads mission.md and AGENTS.md at session start                  │
│  • Determines which agents to invoke and in what order              │
│  • Quality-gates each agent's output before passing to next         │
│  • Escalates CRITICAL findings to human before Reporter runs        │
│  • Assembles final output package                                   │
└──────┬────────────────────────────────────────────────────────────┘
       │ routes to
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  COLLECTOR — gpt-5.3-chat-latest                                      │
│  File: agents/collector.md                                          │
│  Skill: skills/sfdc_connect/sfdc_connect.py                        │
│                                                                      │
│  • Calls sfdc-connect CLI with requested scope                      │
│  • Reads: auth, access, event-monitoring, transaction-security,     │
│           integrations, oauth, secconf (or all)                     │
│  • Uses Tooling API for SecuritySettings (session/MFA config)       │
│  • Emits: raw JSON evidence file with org/scope/timestamp           │
│  • NEVER reads record-level data                                    │
└──────┬────────────────────────────────────────────────────────────┘
       │ evidence JSON
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ASSESSOR — gpt-5.3-chat-latest                                       │
│  File: agents/assessor.md                                           │
│  Skills: skills/oscal-assess/, skills/sscf-benchmark/              │
│                                                                      │
│  • Maps each finding to an SBS control ID (e.g. SBS-AUTH-001)      │
│  • Determines status: pass | fail | partial | not_applicable        │
│  • Maps SBS control → SSCF control (CCM domain)                    │
│  • Adds severity, evidence source, observed/expected values         │
│  • Emits: structured findings JSON per schemas/baseline_assessment_ │
│           schema.json                                               │
└──────┬────────────────────────────────────────────────────────────┘
       │ findings JSON
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  NIST REVIEWER — gpt-5.3-chat-latest          ← AI AUDITING LAYER    │
│  File: agents/nist-reviewer.md                                      │
│                                                                      │
│  Validates outputs against NIST AI RMF 1.0 before delivery:        │
│  • GOVERN: Are scope limits respected? No org write attempts?       │
│  • MAP: Is each finding traceable to a real evidence source?        │
│  • MEASURE: Are confidence levels calibrated (not overconfident)?   │
│  • MANAGE: Are CRITICAL findings escalated before report runs?      │
│  • Bias check: Same standards applied across all orgs?              │
│                                                                      │
│  BLOCKS output if any AI RMF gap is unacknowledged                 │
└──────┬────────────────────────────────────────────────────────────┘
       │ validated findings
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  REPORTER — gpt-5.3-chat-latest                                        │
│  File: agents/reporter.md                                           │
│  Skill: skills/report-gen/                                          │
│                                                                      │
│  • Formats validated findings for human audiences                   │
│  • Outputs: JSON (backlog), Markdown (gap matrix), DOCX (app owner) │
│  • All output to: docs/oscal-salesforce-poc/generated/              │
│  • Adds: assessment_id, generated_at_utc, org reference             │
└──────┬────────────────────────────────────────────────────────────┘
       │ deliverables
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR QA GATE                                               │
│                                                                      │
│  (parallel, on CI/CD or skill changes)                              │
│                                                                      │
│  SECURITY REVIEWER — gpt-5.3-chat-latest      ← DEVSECOPS LAYER      │
│  File: agents/security-reviewer.md                                  │
│                                                                      │
│  • Reviews GitHub Actions workflows for supply-chain risk           │
│  • Reviews skill CLIs for injection, secrets, and unsafe patterns   │
│  • Checks SAST output (bandit), pip-audit, gitleaks findings        │
│  • CRITICAL or HIGH findings block merge via CODEOWNERS gate        │
│                                                                      │
│  • Checks output schema conformance                                 │
│  • Verifies no credentials in output                                │
│  • Confirms evidence paths are within repo                          │
└──────┬────────────────────────────────────────────────────────────┘
       │
       ▼
                        HUMAN REVIEW
```

### Why this pattern?

- **Orchestrator-workers** (not a swarm): Predictable, auditable, easy to debug. Each agent has a defined input and output. No emergent behavior.
- **Sequential**: The assessor cannot run until the collector finishes. The reporter cannot run until the NIST reviewer approves. Dependencies are explicit.
- **NIST Reviewer as blocking gate**: AI auditing is not a post-hoc review — it's a hard gate in the pipeline. This is the "MANAGE" function of NIST AI RMF.
- **Single model tier**: All agents use `gpt-5.3-chat-latest`. This simplifies reasoning audits — there is no cheaper-model shortcut that could produce lower-quality findings.

---

## 3. Agent Reference

| Agent | File | Model | Context Window | Primary Role |
|---|---|---|---|---|
| orchestrator | `agents/orchestrator.md` | gpt-5.3-chat-latest | 200K | Routing, QA, escalation |
| collector | `agents/collector.md` | gpt-5.3-chat-latest | 200K | Salesforce + Workday API extraction |
| assessor | `agents/assessor.md` | gpt-5.3-chat-latest | 200K | OSCAL/SBS/WSCC/SSCF mapping |
| nist-reviewer | `agents/nist-reviewer.md` | gpt-5.3-chat-latest | 200K | AI RMF validation |
| reporter | `agents/reporter.md` | gpt-5.3-chat-latest | 200K | Output formatting |
| security-reviewer | `agents/security-reviewer.md` | gpt-5.3-chat-latest | 200K | AppSec + DevSecOps CI/CD audit |
| sfdc-expert | `agents/sfdc-expert.md` | gpt-5.3-chat-latest | 200K | Apex + deep admin specialist (on-demand) |
| workday-expert | `agents/workday-expert.md` | gpt-5.3-chat-latest | 200K | Workday API + WSCC specialist (on-demand) |
| container-expert | `agents/container-expert.md` | gpt-5.3-chat-latest | 200K | Docker + OpenSearch stack specialist (on-demand) |

**sfdc-expert** is invoked on-demand (not sequential) — only when `oscal_assess_assess`
emits findings with `needs_expert_review=true`. It proposes read-only Apex scripts staged
in `docs/oscal-salesforce-poc/apex-scripts/` for human review before any execution.

**workday-expert** and **container-expert** are similarly on-demand text-analysis agents (no tool calls).

---

## 4. Skill (CLI) Reference

| Skill | Module | Commands | Auth | Description |
|---|---|---|---|---|
| sfdc-connect | `skills/sfdc_connect/sfdc_connect.py` | `collect`, `auth`, `org-info` | SF JWT env vars | Salesforce REST + Tooling API collector |
| workday-connect | `skills/workday_connect/workday_connect.py` | `collect` | WD OAuth 2.0 env vars | Workday REST + SOAP + RaaS collector (30 WSCC controls) |
| oscal-assess | `skills/oscal_assess/oscal_assess.py` | `assess` | none | OSCAL gap mapping vs SBS/WSCC catalog; `--dry-run --platform` flags |
| sscf-benchmark | `skills/sscf_benchmark/sscf_benchmark.py` | `benchmark` | none | CSA SSCF domain scoring; RED/AMBER/GREEN verdict |
| nist-review | `skills/nist_review/nist_review.py` | `assess` | none | NIST AI RMF 7-step gate; clear/flag/block verdict |
| report-gen | `skills/report_gen/report_gen.py` | `generate` | OpenAI API | DOCX/MD governance output; `--audience app-owner|security` |
| agent-loop | `harness/loop.py` | `run` | OpenAI + platform creds | 14-turn ReAct orchestration loop; `--platform salesforce|workday` |

### sfdc-connect scopes

| Scope | Salesforce API | What It Collects |
|---|---|---|
| `auth` | Tooling API + SOQL | Session settings, MFA, SSO providers, login IP ranges |
| `access` | SOQL | Admin profiles, elevated permission sets, connected apps |
| `event-monitoring` | SOQL | Event log types, field history tracking |
| `transaction-security` | SOQL | Automated threat response policies |
| `integrations` | SOQL | Named credentials, remote site settings |
| `oauth` | SOQL | Connected app OAuth policies |
| `secconf` | SOQL | Security Health Check score |
| `all` | All of the above | Full configuration sweep |

---

## 5. Control Framework Reference

| Framework | Config File | Purpose |
|---|---|---|
| SSCF v1.0 catalog | `config/sscf/sscf_v1_catalog.json` | 36 parameterized controls — base catalog with ODPs |
| SBS profile | `config/salesforce/sbs_v1_profile.json` | Salesforce: selects 35 SSCF controls, sets ODP values |
| SBS resolved catalog | `config/salesforce/sbs_resolved_catalog.json` | Pre-resolved: 35 controls, params substituted |
| WSCC profile | `config/workday/wscc_v1_profile.json` | Workday: selects 30 SSCF controls, sets ODP values |
| WSCC resolved catalog | `config/workday/wscc_resolved_catalog.json` | Pre-resolved: 30 controls, params substituted |
| SBS → SSCF | `config/oscal-salesforce/sbs_to_sscf_mapping.yaml` | SBS control → SSCF domain + control ID |
| SSCF → CCM | `config/sscf/sscf_to_ccm_mapping.yaml` | SSCF control → CCM v4.1 controls + regulatory highlights |
| AICM v1.0.3 catalog | `config/aicm/aicm_v1_catalog.json` | 243 controls, 18 domains (EU AI Act / ISO 42001 / NIST AI 600-1) |
| SSCF → AICM | `config/aicm/sscf_to_aicm_mapping.yaml` | 36-control SSCF → AICM crosswalk |
| SSP template | `config/ssp/commercial_saas_ssp_template.json` | OSCAL 1.1.2 SSP — commercial SaaS variant |
| NIST AI RMF | (applied in-context by nist-reviewer agent) | AI system governance (Govern/Map/Measure/Manage) |

---

## 6. Output Schema

All findings must conform to `schemas/baseline_assessment_schema.json`.

```json
{
  "assessment_id": "SFDC-2026-001",
  "org": "myorg.salesforce.com",
  "env": "dev | test | prod",
  "generated_at_utc": "2026-02-27T10:00:00Z",
  "scope": "auth",
  "findings": [
    {
      "control_id": "SBS-AUTH-001",
      "sscf_control": "IAM-02",
      "status": "fail | pass | partial | not_applicable",
      "severity": "critical | high | medium | low",
      "evidence_source": "sfdc-connect://auth/session_settings",
      "observed_value": "SessionTimeout = 120 minutes",
      "expected_value": "SessionTimeout <= 30 minutes",
      "notes": "Optional context from assessor"
    }
  ]
}
```

---

## 7. Context Modes

Load the appropriate system prompt before starting a session:

| Mode | File | When to Use |
|---|---|---|
| assess | `contexts/assess.md` | Running a live or historical assessment |
| review | `contexts/review.md` | QA'ing agent outputs, reviewing findings |
| research | `contexts/research.md` | Investigating CVEs, control definitions |

---

## 8. Session Protocol

```
Session Start:
  1. Read mission.md               ← agent identity + scope
  2. Read AGENTS.md                ← agent roster + routing
  3. Check NEXT_SESSION.md         ← current objectives
  4. Run hooks/session-start.js    ← load org context
  5. Confirm scope with human      ← before calling sfdc-connect

Session End:
  1. Run hooks/session-end.js      ← persist findings
  2. Update NEXT_SESSION.md        ← state for next session
  3. Commit generated artifacts    ← to docs/.../generated/
  4. Verify no credentials in git  ← final safety check
```

---

## 9. Prerequisite Summary

See `scripts/validate_env.py --help` for the automated preflight check.

### Hard requirements (pipeline will not run without these)

| Requirement | Version | Check |
|---|---|---|
| Python | >= 3.11 | `python3 --version` |
| uv | latest | `uv --version` |
| OpenAI API key | — | `OPENAI_API_KEY` in `.env` |
| SF credentials | — | `SF_USERNAME`, `SF_CONSUMER_KEY`, `SF_PRIVATE_KEY_PATH` in `.env` (JWT auth) |
| simple-salesforce | >= 1.12.6 | `pip show simple-salesforce` |
| openai | >= 1.0.0 | `pip show openai` |
| click | >= 8.1.0 | `pip show click` |

### Soft requirements (needed for full CI, not for local assessment)

| Requirement | Purpose |
|---|---|
| ruff | Linting |
| bandit | SAST |
| pip-audit | Dependency CVE scanning |
| pytest | Unit tests (Phase 3) |
| gh CLI | GitHub operations |

---

## 10. Known Limitations

| Limitation | Impact | Workaround |
|---|---|---|
| SecuritySettings requires Tooling API | Some orgs restrict Tooling API access | Output includes error + `note` field; assessor flags as manual check |
| OrganizationSettings MFA fields require API v57+ | Older orgs may not return MFA data | Flagged in output; use UI Security Health Check instead |
| SOAP login blocked in some orgs | New orgs (Spring '24+) disable password-based login by default | Set `SF_AUTH_METHOD=jwt`; see §10a |
| No record-level access by design | Cannot assess data-layer controls | Intentional; assessor uses metadata API for field-level security |

---

### §10a — JWT Bearer Flow Prerequisites

For orgs that block password-based (SOAP) login (Spring '24+ default):

| Step | Action |
|---|---|
| 1. Generate RSA keypair | `openssl genrsa -out ~/salesforce_jwt_private.pem 2048` |
| 2. Generate cert | `openssl req -new -x509 -key ~/salesforce_jwt_private.pem -out ~/salesforce_cert.crt -days 365` |
| 3. Create Connected App | Setup → App Manager → New; enable OAuth (scopes: api, refresh_token); check "Use digital signatures" → upload cert |
| 4. Set permitted users | Edit Policies → Permitted Users = "Admin approved users are pre-authorized" |
| 5. Authorize profile | Manage Connected App → Profiles → add your user's profile |

**Environment variables** (add to `.env`):
```dotenv
SF_AUTH_METHOD=jwt
SF_CONSUMER_KEY=<Consumer Key from Connected App>
SF_PRIVATE_KEY_PATH=/path/to/salesforce_jwt_private.pem
```

**Test:**
```bash
sfdc-connect auth --dry-run --auth-method jwt   # validate vars only
sfdc-connect auth --auth-method jwt             # live connection test
```
