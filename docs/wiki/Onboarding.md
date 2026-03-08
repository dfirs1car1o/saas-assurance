# Onboarding — Get Running in 10 Minutes

> **Full setup docs on the Wiki:** For platform-specific setup (macOS, Linux, Windows), see the [Wiki Home](Home).

## Step 1: Clone & Install

```bash
git clone git@github.com:dfirs1car1o/saas-posture.git
cd saas-posture

# Create and activate a venv
python3 -m venv .venv && source .venv/bin/activate

# Install the package + test dependencies
pip install -e .
pip install pytest pytest-mock PyYAML click
```

## Step 2: Configure .env

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```bash
# Required for agent loop (OpenAI)
OPENAI_API_KEY=sk-...

# Required for live Salesforce assessment
# Option A — JWT Bearer (preferred, no password needed)
SF_AUTH_METHOD=jwt
SF_USERNAME=your.name@company.com
SF_CONSUMER_KEY=3MVG9...
SF_PRIVATE_KEY_PATH=/path/to/salesforce_jwt_private.pem
SF_DOMAIN=login          # use "test" for sandbox

# Option B — SOAP (username/password)
# SF_AUTH_METHOD=soap
# SF_USERNAME=your.name@company.com
# SF_PASSWORD=YourSalesforcePassword
# SF_SECURITY_TOKEN=YourSecurityToken
# SF_DOMAIN=login

# Memory backend (default: in-process, no Docker needed)
QDRANT_IN_MEMORY=1
MEMORY_ENABLED=0
```

> **Dry-run mode:** If you don't have a Salesforce org, you can still run the full pipeline with `--dry-run`. Only `OPENAI_API_KEY` is needed.

## Step 3: Verify Your Environment

```bash
python3 scripts/validate_env.py
```

Expected: `ENVIRONMENT READY` or `ENVIRONMENT READY WITH WARNINGS` (credentials missing = expected if using dry-run).

## Step 4: Run the Tests

```bash
pytest tests/ -v
```

Expected: **12/12 pass** (fully offline — no API keys or Salesforce org needed).

## Step 5: Your First Run (Dry-Run)

```bash
agent-loop run --dry-run --env dev --org my-test-org
```

Expected output:
```
agent-loop [DRY-RUN]: org=my-test-org env=dev
  [tool] sfdc_connect_collect(...)
  [tool] oscal_assess_assess(...)
  [tool] oscal_gap_map(...)
  [tool] sscf_benchmark_benchmark(...)
  [tool] nist_review_assess(...)
  [tool] report_gen_generate(...)   ← app-owner
  [tool] report_gen_generate(...)   ← security
============================================================
Assessment complete (N turn(s))
overall_score : 34.8%
critical_fails: 0
============================================================
```

Reports land in: `docs/oscal-salesforce-poc/generated/my-test-org/<date>/`

## Step 6 (Optional): Live Assessment

```bash
agent-loop run --env prod --org mycompany-prod --approve-critical
```

This runs against your real Salesforce org. Requires Salesforce credentials set in `.env`.

---

## What You Get After a Run

| File | Contents |
|---|---|
| `generated/<org>/<date>/sfdc_raw.json` | Raw Salesforce org config snapshot |
| `generated/<org>/<date>/gap_analysis.json` | OSCAL/SBS control findings (pass/fail/partial) |
| `generated/<org>/<date>/backlog.json` | Remediation backlog mapped to SSCF controls |
| `generated/<org>/<date>/sscf_report.json` | SSCF domain scorecard (0–100% per domain) |
| `generated/<org>/<date>/nist_review.json` | NIST AI RMF governance verdict |
| `generated/<org>/<date>/{org}_remediation_report.md` | App owner remediation report (Markdown) |
| `generated/<org>/<date>/{org}_security_assessment.md` | Security governance report (Markdown) |
| `generated/<org>/<date>/{org}_security_assessment.docx` | Security governance report (Word) |
| `generated/<org>/<date>/loop_result.json` | Consolidated run metadata |

---

## Tool Reference (Quick)

```bash
sfdc-connect --help        # Salesforce org connector
oscal-assess --help        # SBS control assessor
sscf-benchmark --help      # SSCF domain scorer
nist-review --help         # NIST AI RMF validator
report-gen --help          # Governance report generator
agent-loop --help          # Full pipeline orchestrator
```

---

## Next Steps

- [Architecture Overview](Architecture-Overview) — understand the system design
- [Pipeline Walkthrough](Pipeline-Walkthrough) — step-by-step through each stage
- [Running a Dry Run](Running-a-Dry-Run) — full simulation without Salesforce
- [Configuration Reference](Configuration-Reference) — all environment variables
