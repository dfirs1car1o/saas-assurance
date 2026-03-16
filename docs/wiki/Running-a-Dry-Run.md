# Running a Dry Run

A dry run executes the **full 7-stage pipeline** — orchestrator, all tool calls, report generation — without connecting to a real Salesforce org or spending API credits on tool execution. It uses a pre-built synthetic "weak org" snapshot that exercises every pipeline stage.

---

## Prerequisites

- `OPENAI_API_KEY` set in `.env` (the LLM calls are real — only the Salesforce connection is mocked)
- `QDRANT_IN_MEMORY=1` set in `.env` (no Docker needed)
- Package installed: `pip install -e ".[dev]"`

---

## Run It

```bash
agent-loop run --dry-run --env dev --org test-org
```

### What Happens

```
agent-loop [DRY-RUN]: org=test-org env=dev
  [memory] No prior assessments found for test-org
  task: Run a full OSCAL/SSCF security assessment for Salesforce org 'test-org'...

  [tool] sfdc_connect_collect({"org":"test-org","scope":"all","dry_run":true})
  → writes: docs/oscal-salesforce-poc/generated/test-org/sfdc_raw.json

  [tool] oscal_assess_assess({"org":"test-org","collector_output":"...sfdc_raw.json"})
  → writes: docs/oscal-salesforce-poc/generated/test-org/gap_analysis.json

  [tool] oscal_gap_map({"org":"test-org","gap_analysis":"...gap_analysis.json"})
  → writes: docs/oscal-salesforce-poc/generated/test-org/backlog.json

  [tool] sscf_benchmark_benchmark({"org":"test-org","backlog":"...backlog.json"})
  → writes: docs/oscal-salesforce-poc/generated/test-org/sscf_report.json

  [tool] nist_review_assess({"org":"test-org","gap_analysis":"...","backlog":"...","dry_run":true})
  → writes: docs/oscal-salesforce-poc/generated/test-org/nist_review.json

  [tool] gen_aicm_crosswalk({"org":"test-org","backlog":"...backlog.json","platform":"salesforce"})
  → writes: docs/oscal-salesforce-poc/generated/test-org/aicm_coverage.json

  [tool] report_gen_generate({"org":"test-org","audience":"app-owner",...})
  → writes: docs/oscal-salesforce-poc/generated/test-org/test-org_remediation_report.md

  [tool] report_gen_generate({"org":"test-org","audience":"security","aicm_coverage":"...aicm_coverage.json",...})
  → writes: docs/oscal-salesforce-poc/generated/test-org/test-org_security_assessment.md
  → writes: docs/oscal-salesforce-poc/generated/test-org/test-org_security_assessment.docx

============================================================
Assessment complete (7 turn(s))
overall_score : 34.8%
critical_fails: 0
============================================================

Result written → docs/oscal-salesforce-poc/generated/test-org/loop_result.json
```

### Optional post-processing (run manually after pipeline)

The OSCAL machine-readable artifacts are **not** produced by the automated pipeline. Run these scripts separately after `agent-loop` completes if needed for GRC tooling or audit packages:

```bash
# OSCAL Plan of Action and Milestones
python scripts/gen_poam.py \
    --backlog docs/oscal-salesforce-poc/generated/test-org/backlog.json \
    --org test-org --platform salesforce \
    --out docs/oscal-salesforce-poc/generated/test-org/poam.json

# OSCAL Assessment Results
python scripts/gen_assessment_results.py \
    --gap-analysis docs/oscal-salesforce-poc/generated/test-org/gap_analysis.json \
    --backlog docs/oscal-salesforce-poc/generated/test-org/backlog.json \
    --org test-org --platform salesforce \
    --out docs/oscal-salesforce-poc/generated/test-org/assessment_results.json

# OSCAL System Security Plan
python scripts/gen_ssp.py \
    --sscf-report docs/oscal-salesforce-poc/generated/test-org/sscf_report.json \
    --backlog docs/oscal-salesforce-poc/generated/test-org/backlog.json \
    --nist-review docs/oscal-salesforce-poc/generated/test-org/nist_review.json \
    --org test-org --platform salesforce \
    --out docs/oscal-salesforce-poc/generated/test-org/ssp.json
```

---

## Expected Score

**~34.8% RED** — the synthetic weak-org stub is intentionally configured with missing MFA enforcement, no IP restrictions, and broad permission grants. This exercises the full RED alert path.

---

## What the Dry-Run Tests Without a Real Org

| What's real | What's simulated |
|---|---|
| OpenAI API calls (LLM reasoning) | Salesforce REST/Tooling API calls |
| All file I/O (reports written to disk) | SecuritySettings query |
| Memory read/write (Qdrant in-memory) | ConnectedApp query |
| All CLI tool execution | AuthProvider query |
| SSCF scoring logic | PermissionSet/Profile query |
| Report generation (DOCX + MD) | NetworkAccess query |

---

## Pre-loaded Dry-Run Data

The dry-run stub is defined in `skills/sfdc_connect/sfdc_connect.py` and produces:

| Control area | Dry-run state | Result |
|---|---|---|
| MFA enforcement | Not enabled | FAIL / critical |
| Session timeout | 120 min (too long) | FAIL |
| IP restrictions | None set | FAIL |
| OAuth token rotation | Disabled | FAIL |
| Admin profiles | Multiple broad grants | PARTIAL |
| Connected apps | Overly broad scopes | PARTIAL |
| SSO | Not configured | NOT_APPLICABLE |

---

## Workday Dry Run (No Credentials Needed)

```bash
python3 scripts/workday_dry_run_demo.py --org acme-workday --env dev
```

Runs the complete Workday pipeline (all 30 WSCC controls) using realistic stub data — no live Workday tenant required. Produces identical output structure to a live run:

```
Automated pipeline outputs:
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/workday_raw.json
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/gap_analysis.json
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/backlog.json
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/sscf_report.json
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/nist_review.json
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/aicm_coverage.json
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/acme-workday_remediation_report.md
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/acme-workday_security_assessment.md
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/acme-workday_security_assessment.docx

Optional post-processing (run manually after pipeline — see gen_poam.py, gen_assessment_results.py, gen_ssp.py):
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/poam.json
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/assessment_results.json
→ docs/oscal-salesforce-poc/generated/acme-workday/<date>/ssp.json
```

Or via agent-loop:
```bash
agent-loop run --platform workday --dry-run --env dev --org acme-workday
```

---

## Smoke Tests (No LLM Needed)

To test just the pipeline logic without any API calls:

```bash
pytest tests/ -v
```

This runs 191 tests across 12 suites — all pass without any environment variables or API keys:

| Test file | Tests | What it covers |
|---|---|---|
| `tests/test_pipeline_smoke.py` | 3 | Dry-run assess, gap map, benchmark |
| `tests/test_report_gen.py` | 3 | App-owner MD, security MD, DOCX generation |
| `tests/test_harness_dry_run.py` | 12 | Loop tool dispatch, audit log events, sequencing gate, finish() gate |
| `tests/test_sfdc_connect_jwt.py` | 6 | JWT auth resolution, env validation, key path handling |
| `tests/test_workday_connect.py` | 12 | OAuth flow, 30 controls, RaaS/REST, graceful degradation |
| `tests/test_drift_and_ccm.py` | 10 | Drift classification, CCM crosswalk rendering |
| `tests/test_security_gates.py` | 18 | Path traversal, org sanitization, dispatch boundary, input validation |
| `tests/test_safe_out_path.py` | 7 | Output path boundary enforcement |
| `tests/test_tools_dispatch.py` | 27 | All 10 dispatcher functions, _run helper, hermetic sfdc-expert enrichment |
| `tests/test_agent_dispatchers.py` | 39 | Agent sub-call dispatchers (collector_enrich, assessor_analyze, workday_expert_enrich, security_reviewer_review) |
| `tests/test_nist_review.py` | 21 | nist_review CLI dry-run, _build_review_context, _load_json, stub data |
| `tests/test_sscf_benchmark.py` | 33 | _domain_status thresholds, _score_findings, run_benchmark core, _to_markdown |

**Run with coverage:**
```bash
pytest tests/ -v --cov=skills --cov=scripts --cov=harness --cov-report=term-missing
```

---

## Running Against Multiple Orgs

```bash
# Run against prod org
agent-loop run --env prod --org mycompany-prod --approve-critical

# Run against dev sandbox
agent-loop run --env dev --org mycompany-dev

# Dry-run to compare reporting format
agent-loop run --dry-run --env dev --org test-comparison
```

Each org gets its own directory under `docs/oscal-salesforce-poc/generated/<org>/`. Session memory is scoped per org, so drift detection works across runs.

---

## Approving Critical Findings

On a live run, if `status=fail AND severity=critical` findings are found, the loop exits with code 2:

```
BLOCKED: 2 critical/fail finding(s) require human review:
  - SBS-AUTH-001
  - SBS-ACS-001

Re-run with --approve-critical to proceed past this gate.
```

After reviewing:
```bash
agent-loop run --env prod --org mycompany-prod --approve-critical
```
