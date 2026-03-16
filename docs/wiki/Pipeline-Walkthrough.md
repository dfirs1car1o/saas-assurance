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

## Stage 1a: Collector Enrichment (Agent Sub-call)

**What it does:** After raw collection, the orchestrator invokes the **collector agent** directly via `collector_enrich` to review the raw output for evidence quality issues before assessment runs.

**Checks:**
- Missing API scopes or API limitations that reduced assessment completeness
- Controls recorded as `not_applicable` that a different scope would have resolved
- Data quality issues (missing timestamps, empty `evidence_ref` fields)

**Output:** JSON with `status`, `analysis`, and `flags` list. Each FLAG is a short slug the orchestrator acts on (e.g., `FLAG: missing_scope:event-monitoring`, `FLAG: stale_evidence:SBS-LOG-001`).

**When skipped:** Dry-run mode (synthetic collector output has no real gaps to review).

---

## Stage 2: OSCAL Assessment (`oscal-assess`)

**What it does:** Evaluates 35 SBS (Salesforce Baseline Security) controls against the collected config.

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

## Stage 2a: Assessor Enrichment (Agent Sub-call)

**What it does:** After `oscal-assess`, the orchestrator invokes the **assessor agent** directly via `assessor_analyze` to review the gap analysis findings for confidence issues.

**Checks:**
- Critical/high findings with `mapping_confidence: low` that need expert review
- Controls with `needs_expert_review: true` that lack `expert_notes`
- Whether >20% of findings are unmapped (threshold exceeded)

**Output:** JSON with `flags` list. Key flags:
- `FLAG: low_confidence_critical:<control_id>` — triggers sfdc_expert or workday_expert_enrich
- `FLAG: expert_review_pending:<control_id>` — expert notes missing
- `FLAG: unmapped_findings_threshold_exceeded` — assessment may be incomplete

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
    --controls docs/oscal-salesforce-poc/generated/sbs_controls.json \
    --gap-analysis gap_analysis.json \
    --mapping config/oscal-salesforce/control_mapping.yaml \
    --sscf-map config/oscal-salesforce/sbs_to_sscf_mapping.yaml \
    --out-md backlog_matrix.md \
    --out-json backlog.json
```

**Output:** `backlog.json` — remediation backlog with SSCF control references and priority ordering.

---

## Stage 2.5: OSCAL POA&M Generation (`gen_poam.py`)

**What it does:** Converts the remediation backlog into a valid OSCAL 1.1.2 Plan of Action and Milestones (POA&M) JSON artifact. Supports persistent cumulative mode — each run merges into the existing POA&M, appending new observations and auto-closing resolved findings.

**OSCAL artifacts produced:**

| Object | Count (dry-run) | Description |
|---|---|---|
| `observations` | 1 per finding per run | Automated evidence of each control assessment |
| `risks` | 1 per open finding | Risk record with severity, deadline, remediation plan |
| `poam-items` | 1 per fail/partial finding | Numbered POAM-NNNN items linked to observation + risk |

**Sensitivity tier mapping:**

| Open items | Tier | Maps from |
|---|---|---|
| ≥ 10 | `high` | SSCF RED |
| 5–9 | `moderate` | SSCF AMBER |
| < 5 | `low` | SSCF GREEN |

**Command — first run (seeds fresh POA&M):**
```bash
python3 scripts/gen_poam.py \
    --backlog docs/oscal-salesforce-poc/generated/<org>/<date>/backlog.json \
    --org <org-alias> \
    --platform salesforce \
    --out docs/oscal-salesforce-poc/generated/<org>/<date>/poam.json
```

**Command — subsequent runs (persistent cumulative update):**
```bash
python3 scripts/gen_poam.py \
    --backlog docs/oscal-salesforce-poc/generated/<org>/<new-date>/backlog.json \
    --org <org-alias> \
    --platform salesforce \
    --out docs/oscal-salesforce-poc/generated/<org>/<new-date>/poam.json \
    --existing docs/oscal-salesforce-poc/generated/<org>/<old-date>/poam.json
```

**Cumulative merge logic:**

| Finding change | POA&M action |
|---|---|
| New fail/partial | Adds observation + risk + poam-item (POAM-NNNN) |
| Existing finding, status unchanged | Appends new observation; risk status preserved |
| Existing finding, now resolved (pass) | Updates risk status → `closed`; lifecycle-state → `closed` |
| `not_applicable` | Skipped — out of scope |

**Output:** `poam.json` — OSCAL 1.1.2 `plan-of-action-and-milestones` with observations, risks, and numbered POAM items. Links to SSP via `import-ssp` (generated by `gen_ssp.py`).

---

## Stage 2.6: OSCAL Assessment Results (`gen_assessment_results.py`)

**What it does:** Wraps `gap_analysis.json` findings in the OSCAL 1.1.2 `assessment-results` model — producing machine-readable observations and findings linked to the resolved platform profile. Each gap analysis finding maps to one OSCAL observation + one OSCAL finding.

**OSCAL model elements produced:**

| Element | Source | Notes |
|---|---|---|
| `observations` | One per `gap_analysis.findings` entry | Evidence ref, collection method, observed value |
| `findings` | One per observation | Status (satisfied/not-satisfied), severity, risk-level |
| `reviewed-controls` | include-all | All controls from resolved profile |

**Command:**
```bash
python3 scripts/gen_assessment_results.py \
    --gap-analysis gap_analysis.json \
    --backlog backlog.json \
    --org my-org \
    --platform salesforce \
    --resolved-catalog config/salesforce/sbs_resolved_catalog.json \
    --out assessment_results.json
```

**Output:** `assessment_results.json` — OSCAL 1.1.2 `assessment-results` with `observations`, `findings`, and summary props (pass-count, fail-count, partial-count).

---

## Stage 2.7: OSCAL SSP (`gen_ssp.py`)

**What it does:** Generates a fully-populated OSCAL 1.1.2 System Security Plan (SSP) for the assessed org. The SSP is generated every run to stay in sync with the latest assessment state. Uses the commercial SaaS template — no FedRAMP red tape (no JAB/PMO, no FIPS 199, no physical media controls).

**Sensitivity tier mapping:**

| SSCF Score / Status | SSP Sensitivity Tier |
|---|---|
| Score < 40% or status RED | `high` |
| Score 40–80% or status AMBER | `moderate` |
| Score ≥ 80% and status GREEN | `low` |

**Command:**
```bash
python3 scripts/gen_ssp.py \
    --sscf-report sscf_report.json \
    --backlog backlog.json \
    --nist-review nist_review.json \
    --org my-org \
    --platform salesforce \
    --out ssp.json
```

**Key sections populated:**
- `system-characteristics` — sensitivity tier, scores, regulatory obligations (SOX/HIPAA/SOC2/ISO 27001/PCI DSS/GDPR)
- `system-implementation` — components (SaaS platform + IdP), user types, authorization boundary
- `control-implementation.implemented-requirements` — one entry per backlog item with `implementation-status`, severity, owner, evidence ref
- `import-profile` — links to platform-specific SBS or WSCC profile
- `back-matter` — links to resolved catalog and component definition

**Output:** `ssp.json` — OSCAL 1.1.2 SSP. Regenerated every assessment run.

---

## Stage 2.8: AICM Coverage Crosswalk (`gen_aicm_crosswalk.py`)

**What it does:** Maps SSCF backlog findings through the SSCF → AICM v1.0.3 bridge to produce a per-domain AI governance coverage report. Surfaces which of the 18 AICM domains receive coverage from your SaaS platform assessment and which are structural gaps requiring supplemental controls.

**When to run:** After gen_ssp.py (Stage 2.7), once backlog.json is available.

**Command:**
```bash
python3 scripts/gen_aicm_crosswalk.py \
    --backlog backlog.json \
    --org my-org \
    --platform salesforce \
    --out aicm_coverage.json
```

**Coverage verdicts:**
| Verdict | Meaning |
|---|---|
| `covered` | SSCF assessment provides direct evidence for this AICM domain |
| `partial` | SSCF partially addresses this domain; gaps remain |
| `not_covered` | No SSCF coverage — supplemental controls required (BCR, CEK, DCS, HRS, IVS, MDS, UEM) |

**Output:** `aicm_coverage.json` — per-domain coverage + posture verdict. MDS (Model Security) is the critical AI-specific gap domain not addressable via SaaS platform controls alone.

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

**Output:** `{org}_security_assessment.md` + `{org}_security_assessment.docx` — SSCF domain bar chart, CCM v4.1 regulatory crosswalk (SOX/HIPAA/SOC2/ISO 27001 via CCM/PCI DSS/GDPR), **ISO 27001:2022 Statement of Applicability** (all 93 Annex A controls — 29 assessed via API, 64 manual), full control matrix, NIST AI RMF governance review, executive summary, and risk analysis.

---

## Stage 7a: Security Reviewer Final Review (Agent Sub-call)

**What it does:** After security report generation, the orchestrator invokes the **security-reviewer agent** directly via `security_reviewer_review` for a final AppSec pass before `finish()`.

**Checks three areas:**
1. **Credential exposure** — org URLs, usernames, internal identifiers that should not appear in a deliverable → `FLAG: credential_exposure:<detail>`
2. **Status misrepresentation** — language that downplays or softens a fail/critical finding → `FLAG: status_misrepresentation:<control_id>`
3. **Scope violations** — any section implying permissions beyond read-only OSCAL/SSCF assessment scope → `FLAG: scope_violation:<section>`

**Output:** JSON with `flags` list + `### Security Posture Summary` block (1–3 sentences). `credential_exposure` and `scope_violation` flags delay `finish()` until human acknowledgement.

---

## Stage 1 (Workday): Workday Collection (`workday-connect`)

For Workday assessments, replace Stage 1 with:

```bash
workday-connect collect --org my-tenant --env dev --out workday_raw.json
# or dry-run (no live tenant needed):
python3 scripts/workday_dry_run_demo.py --org my-tenant --env dev
```

Collects 30 WSCC controls across IAM, CON, LOG, DSP, GOV, CKM domains via OAuth 2.0 / REST API v1 / RaaS (custom reports) / manual questionnaire. No SOAP.
All subsequent stages (oscal-assess → report-gen) run identically with `--platform workday`.

**Stage 1a (Workday):** The `workday_expert_enrich` dispatcher is the Workday parallel to sfdc_expert_enrich. It invokes the **workday-expert agent** on findings where `needs_expert_review: true` or `data_source: permission_denied`. For each eligible finding it:
- Identifies which Workday domain security policy grant is missing
- Specifies the exact RaaS report or REST endpoint that provides the evidence
- States whether an ISSG grant resolves it or tenant admin manual confirmation is required
- Writes `expert_notes` back to `gap_analysis.json`

---

## Stage 1.5: Drift Detection (`drift_check.py`)

**What it does:** Compares two backlog snapshots — baseline (previous run) vs. current (latest run) — and produces a structured change report.

**When to run it:**  Run between Phase 1–2 outputs of successive assessments, or weekly after the scheduled CI dry-run produces a new backlog.

**Change types detected:**

| Change type | Meaning |
|---|---|
| `regression` | Was pass/not_applicable → now fail/partial. Requires immediate action. |
| `new_finding` | Control not in baseline; failing now. |
| `improvement` | Was fail → now partial; or partial → now pass. |
| `resolved` | Was fail/partial → now pass. |
| `severity_change` | Status unchanged, but severity escalated or de-escalated. |
| `unchanged` | Status identical; reported only for still-failing controls. |

**Command:**
```bash
python scripts/drift_check.py \
    --baseline docs/oscal-salesforce-poc/generated/<org>/<old-date>/backlog.json \
    --current  docs/oscal-salesforce-poc/generated/<org>/<new-date>/backlog.json \
    --out      docs/oscal-salesforce-poc/generated/<org>/<new-date>/drift_report.json \
    --out-md   docs/oscal-salesforce-poc/generated/<org>/<new-date>/drift_report.md
```

**Outputs:**

- `drift_report.json` — structured diff with per-control change entries, summary buckets, score delta, and net direction (improving / regressing / stable)
- `drift_report.md` — human-readable report with tables for each change category

**Example drift report summary:**

```
Direction  : 📈 Improving
Pass rate  : 34.8% → 41.2% (+6.4%)
New findings       : 0
Resolved           : 3
Regressions        : 0
Improvements       : 2
Still failing      : 12
```

**Example workflow — weekly cadence:**
```bash
# Week 1: baseline run
agent-loop run --env dev --org cyber-coach-dev --approve-critical
# artifacts land in docs/.../cyber-coach-dev/2026-03-07/

# Week 2: new run
agent-loop run --env dev --org cyber-coach-dev --approve-critical
# artifacts land in docs/.../cyber-coach-dev/2026-03-14/

# Drift comparison
python scripts/drift_check.py \
    --baseline docs/oscal-salesforce-poc/generated/cyber-coach-dev/2026-03-07/backlog.json \
    --current  docs/oscal-salesforce-poc/generated/cyber-coach-dev/2026-03-14/backlog.json
# → drift_report.json + drift_report.md next to the current backlog
```

**Score delta interpretation:**

| Net direction | Score delta | Meaning |
|---|---|---|
| Improving | > +1% | Remediations are landing; controls moving from fail → pass |
| Stable | ±1% | No material change since last run |
| Regressing | < −1% | New failures detected; investigate immediately |

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
