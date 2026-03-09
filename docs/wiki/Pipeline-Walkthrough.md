# Pipeline Walkthrough

This page walks through every stage of the assessment pipeline end-to-end, including what each tool does, what it produces, and how the orchestrator connects them.

---

## Stage 0: Pre-flight

Before the pipeline runs, validate your environment:

```bash
python3 scripts/validate_env.py
```

This checks:
- Python ≥ 3.11
- Required Python packages installed
- `.env` file exists with required keys
- Repo layout is correct (mission.md, AGENTS.md, schemas/, etc.)
- Qdrant backend configured (QDRANT_IN_MEMORY=1 or QDRANT_HOST set)

---

## Stage 1: Salesforce Collection (`sfdc-connect`)

**What it does:** Connects to the Salesforce org and snapshots security-relevant configuration.

**Config collected:**
| Salesforce API | What it captures |
|---|---|
| `SecuritySettings` (Tooling API) | Session timeout, IP allowlisting, MFA enforcement, certificate-based auth |
| `AuthProvider` (REST API) | OAuth providers, SSO configurations |
| `PermissionSet` + `Profile` | Admin-equivalent profiles, dangerous permission grants |
| `NetworkAccess` | Trusted IP ranges |
| `ConnectedApp` | OAuth clients, refresh token policy, scopes |

**Command:**
```bash
sfdc-connect collect --scope all --org my-org --out sfdc_raw.json
```

**Output:** `sfdc_raw.json` — structured JSON with all collected config.

**Dry-run mode:**
```bash
sfdc-connect collect --scope all --org my-org --dry-run --out sfdc_raw.json
```
Produces a synthetic weak-org snapshot (no real Salesforce connection needed).

---

## Stage 2: OSCAL Assessment (`oscal-assess`)

**What it does:** Evaluates 45 SBS (Salesforce Baseline Security) controls against the collected config.

**How rules work:**

| Rule type | Count | Logic |
|---|---|---|
| Explicit deterministic | 11 | Direct config check → pass/fail |
| Structural partial | 8 | Config present but incomplete → partial |
| Not applicable | 26 | Outside sfdc-connect scope (CODE, FILE, etc.) |

**Status values:**
- `pass` — control requirement met definitively
- `fail` — control requirement not met
- `partial` — control partially implemented
- `not_applicable` — control outside the assessment scope

**Command:**
```bash
oscal-assess assess --collector-output sfdc_raw.json --org my-org --out gap_analysis.json
```

**Output:** `gap_analysis.json` — findings array with `control_id`, `status`, `severity`, `owner`, `evidence_ref`, `due_date`.

---

## Stage 3: Gap Mapping (`oscal_gap_map.py`)

**What it does:** Maps SBS findings to SSCF control domains; produces a prioritized remediation backlog.

**Mapping path:**
```
SBS control (SBS-AUTH-001)
    → sbs_to_sscf_mapping.yaml
        → SSCF domain (IAM-001, DATA-003, etc.)
            → backlog item with priority score
```

**Command:**
```bash
python3 scripts/oscal_gap_map.py \
    --gap-analysis gap_analysis.json \
    --org my-org \
    --out-json backlog.json
```

**Output:** `backlog.json` — remediation backlog with SSCF control references and priority ordering.

---

## Stage 4: SSCF Benchmark (`sscf-benchmark`)

**What it does:** Calculates maturity scores per SSCF domain and an overall posture rating.

**Scoring:**
- Per-domain score: `(pass + 0.5*partial) / total_controls_in_domain`
- Overall score: weighted average across all assessed domains
- Status thresholds: RED < 40%, AMBER 40–80%, GREEN ≥ 80% (configurable via `--threshold`)
- Domains with no mapped findings show as `N/A / NOT ASSESSED` (not counted against the score)

**Command:**
```bash
sscf-benchmark benchmark \
    --backlog backlog.json \
    --org my-org \
    --out sscf_report.json
```

**Output:** `sscf_report.json` — domain scores, overall score, overall status, per-domain control detail.

---

## Stage 5: NIST AI RMF Review (`nist-review`)

**What it does:** Validates the assessment outputs against NIST AI RMF 1.0, covering all four governance functions.

**NIST AI RMF functions evaluated:**

| Function | What it checks |
|---|---|
| GOVERN | Policies, accountability structures, and AI governance processes |
| MAP | Risk identification and categorization alignment |
| MEASURE | Measurement methods and metrics for AI risk |
| MANAGE | Risk response, prioritization, and remediation planning |

**Command:**
```bash
nist-review assess \
    --gap-analysis gap_analysis.json \
    --backlog backlog.json \
    --out nist_review.json
```

**Output:** `nist_review.json` — structured verdict with per-function status (pass/partial/fail), overall verdict (pass/flag/block), blocking issues list, and recommendations.

**Dry-run mode:**
```bash
nist-review assess \
    --gap-analysis gap_analysis.json \
    --backlog backlog.json \
    --out nist_review.json \
    --dry-run
```
Produces a realistic stub verdict (GOVERN=pass, MAP=partial, MEASURE=pass, MANAGE=partial, overall=flag) without calling the OpenAI API.

---

## Stage 6: Report Generation — App Owner (`report-gen`)

**What it does:** Generates a plain-language remediation report for the application owner.

**Command:**
```bash
report-gen generate \
    --backlog backlog.json \
    --sscf-benchmark sscf_report.json \
    --nist-review nist_review.json \
    --audience app-owner \
    --org-alias my-org \
    --out my-org_remediation_report.md
```

**Output:** `{org}_remediation_report.md` with Executive Scorecard, Immediate Actions, plain-language narrative, and Full Control Matrix.

---

## Stage 7: Report Generation — Security Governance (`report-gen`)

**What it does:** Generates a full technical governance report for security team review.

**Command:**
```bash
report-gen generate \
    --backlog backlog.json \
    --sscf-benchmark sscf_report.json \
    --nist-review nist_review.json \
    --audience security \
    --org-alias my-org \
    --out my-org_security_assessment.md   # also writes .docx
```

**Output:** `{org}_security_assessment.md` + `{org}_security_assessment.docx` — SSCF domain bar chart, CCM v4.1 regulatory crosswalk (SOX/HIPAA/SOC2/ISO 27001/PCI DSS/GDPR), full control matrix, NIST AI RMF governance review, executive summary, and risk analysis.

---

## Stage 1 (Workday): Workday Collection (`workday-connect`)

For Workday assessments, replace Stage 1 with:

```bash
workday-connect collect --org my-tenant --env dev --out workday_raw.json
# or dry-run (no live tenant needed):
python3 scripts/workday_dry_run_demo.py --org my-tenant --env dev
```

Collects 30 WSCC controls across IAM, CON, LOG, DSP, GOV, CKM domains via SOAP/RaaS/REST.
All subsequent stages (oscal-assess → report-gen) run identically with `--platform workday`.

---

## Orchestrated Pipeline (agent-loop)

All 7 stages above run automatically via `agent-loop`. The `gpt-5.3-chat-latest` orchestrator decides the sequence, passes outputs between tools, and enforces quality gates.

```bash
# Full live run — Salesforce
agent-loop run --env prod --org mycompany --approve-critical

# Full live run — Workday
agent-loop run --platform workday --env prod --org my-tenant --approve-critical

# Dry-run — Salesforce
agent-loop run --dry-run --env dev --org test-org

# Dry-run — Workday (no credentials needed)
agent-loop run --platform workday --dry-run --env dev --org acme-workday
```

**Turn budget:** 14 turns max. Typical full pipeline: 7–9 turns.

**Quality gates the orchestrator enforces:**
1. `critical/fail` findings require `--approve-critical` to proceed on live runs
2. nist-reviewer must not return a blocking gap
3. Output schema (`schemas/baseline_assessment_schema.json`) must be satisfied
4. `assessment_id` and `generated_at_utc` must be present in all findings
5. security-reviewer CRITICAL/HIGH on CI changes blocks merge

---

## Interpreting the Score

| Score | Status | Meaning |
|---|---|---|
| ≥ 80% | GREEN | Most controls met; minor gaps |
| 40–79% | AMBER | Significant gaps; remediation plan required |
| < 40% | RED | Critical posture deficiencies; immediate action required |

A dry-run with the synthetic weak-org stub produces ~34.8% RED — this is intentional to test the full alert path.
