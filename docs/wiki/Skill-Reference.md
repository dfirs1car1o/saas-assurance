# Skill Reference

All CLI skills. Each is a Python CLI installed by `pip install -e ".[dev]"` and callable from the shell or from the agent orchestrator via `tool_use`.

---

## sfdc-connect

**Binary:** `sfdc-connect`
**File:** `skills/sfdc_connect/sfdc_connect.py`
**Purpose:** Authenticates to a Salesforce org and collects security-relevant configuration.

### Commands

```bash
sfdc-connect collect --scope all --org my-org [--dry-run] [--out PATH]
sfdc-connect auth --dry-run   # test auth only, no collection
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--scope` | `all` | What to collect: `all`, `auth`, `permissions`, `network`, `oauth` |
| `--org` | `unknown-org` | Org alias for output path naming |
| `--dry-run` | off | Use synthetic weak-org data, no real Salesforce connection |
| `--out` | auto | Output path (`docs/.../generated/<org>/sfdc_raw.json`) |

### What It Collects

| API | Data | Purpose |
|---|---|---|
| Tooling API `SecuritySettings` | Session timeout, MFA, IP restrictions, cert auth | AUTH controls |
| REST `AuthProvider` | SSO/OAuth providers | OAUTH controls |
| REST `PermissionSet` | Named permissions, dangerous grants | ACS controls |
| REST `Profile` | Admin-equivalent profiles | ACS controls |
| REST `NetworkAccess` | Trusted IP ranges | ACS controls |
| REST `ConnectedApp` | OAuth clients, scopes, token policy | OAUTH controls |

### Auth Methods

**JWT Bearer (preferred — no password stored):**
```bash
SF_AUTH_METHOD=jwt
SF_USERNAME=user@org.com
SF_CONSUMER_KEY=3MVG9...
SF_PRIVATE_KEY_PATH=/path/to/private.pem
SF_DOMAIN=login
```

---

## oscal-assess

**Binary:** `oscal-assess`
**File:** `skills/oscal_assess/oscal_assess.py`
**Purpose:** Evaluates 45 SBS controls against the collected org configuration.

### Commands

```bash
oscal-assess assess --collector-output sfdc_raw.json --assessment-owner "Jane Smith" [--out PATH]
```

### Rule Engine

| Rule type | Count | Logic |
|---|---|---|
| Explicit deterministic | 11 | Direct config check → pass/fail (AUTH-001, ACS-001–004, INT, OAUTH-001–002, DATA-004, SECCONF, DEP-003) |
| Structural partial | 8 | Config present but ambiguous → partial (ACS-005–012, OAUTH-003–004, DATA-001–003) |
| Not applicable | 26 | Outside sfdc-connect scope (CODE, CPORTAL, FILE, DEP, FDNS) |

**Conservative rule:** Only `pass` when definitive. When ambiguous → `partial`.

### Output

`gap_analysis.json`:
```json
{
  "assessment_id": "sfdc-assess-my-org-dev",
  "assessed_at_utc": "2026-03-02T15:00:00Z",
  "assessment_owner": "SaaS Security Architect",
  "data_source": "live_api",
  "findings": [
    {
      "control_id": "SBS-AUTH-001",
      "status": "fail",
      "severity": "critical",
      "owner": "security-team",
      "due_date": "2026-03-09",
      "evidence_ref": "collector://salesforce/dev/SBS-AUTH-001/snapshot-2026-03-02"
    }
  ]
}
```

---

## sscf-benchmark

**Binary:** `sscf-benchmark`
**File:** `skills/sscf_benchmark/sscf_benchmark.py`
**Purpose:** Maps SBS findings to SSCF domains and calculates domain maturity scores.

### Commands

```bash
sscf-benchmark benchmark --backlog backlog.json --org my-org [--out PATH] [--threshold 0.80]
```

### Scoring

```
domain_score = (pass_count + 0.5 * partial_count) / total_assessed_controls
overall_score = weighted_average(domain_scores, excluding not_assessed domains)

Status (default threshold=0.80):
  domain_score >= threshold → GREEN
  0.50 <= domain_score < threshold → AMBER
  domain_score < 0.50 → RED
  no findings mapped → NOT ASSESSED (excluded from overall score)
```

### Output

`sscf_report.json`:
```json
{
  "overall_score": 0.348,
  "overall_status": "red",
  "domains": [
    {
      "domain": "identity_access_management",
      "score": 0.34,
      "status": "red",
      "pass": 2, "partial": 3, "fail": 6, "not_applicable": 0
    },
    {
      "domain": "governance_risk_compliance",
      "score": null,
      "status": "not_assessed"
    }
  ]
}
```

---

## report-gen

**Binary:** `report-gen`
**File:** `skills/report_gen/report_gen.py`
**Purpose:** Generates audience-specific governance reports from assessment data.

### Commands

```bash
# App owner report (Markdown)
report-gen generate \
    --backlog backlog.json \
    --sscf-benchmark sscf_report.json \
    --nist-review nist_review.json \
    --audience app-owner \
    --org-alias my-org \
    --out report-app-owner.md

# Security governance report (Markdown + DOCX)
report-gen generate \
    --backlog backlog.json \
    --sscf-benchmark sscf_report.json \
    --nist-review nist_review.json \
    --audience security \
    --org-alias my-org \
    --out report-security.md

# Offline / CI mode (no OpenAI API call)
report-gen generate --backlog backlog.json --audience security --out report.md --mock-llm

# Override ISO 27001:2022 catalog path (optional — auto-detected by default)
report-gen generate --backlog backlog.json --audience security --out report.md \
    --iso27001-catalog config/iso27001/iso27001_2022_annex_a_catalog.yaml
```

### Audiences

| Audience | Formats | Contents |
|---|---|---|
| `app-owner` | Markdown | Executive Scorecard, Immediate Actions, plain-language narrative, Full Control Matrix |
| `security` | Markdown + DOCX | All of the above + OSCAL Provenance + Domain Posture + CCM Crosswalk + ISO 27001:2022 SoA + POA&M + Not Assessed appendix + NIST AI RMF Governance Review |

### Report Structure

```
[Gate banner]                  ← ⛔ block / 🚩 flag if NIST verdict requires it
Executive Scorecard            ← overall score + severity × status matrix        [HARNESS]
Domain Posture (ASCII chart)   ← bar chart of SSCF domain scores                 [HARNESS]
OSCAL Framework Provenance     ← catalog → profile → ISO 27001:2022 → CCM chain  [HARNESS]
CCM v4.1 Regulatory Crosswalk  ← fail/partial → SOX/HIPAA/SOC2/PCI/GDPR         [HARNESS]
                                  (security audience only; ISO column = via CCM)
ISO 27001:2022 SoA             ← Statement of Applicability: all 93 Annex A      [HARNESS]
                                  controls with applicability, status, SSCF ref,
                                  owner, evidence (security audience only)
Immediate Actions (Top 10)     ← sorted critical/fail findings                   [HARNESS]
Executive Summary + Analysis   ← LLM narrative only                               [LLM]
Full Control Matrix            ← complete sorted findings table                   [HARNESS]
Plan of Action & Milestones    ← POAM-IDs, owners, due dates, status             [HARNESS]
Not Assessed Controls          ← out-of-scope appendix for auditors              [HARNESS]
NIST AI RMF Governance Review  ← function table + blockers + recs                [HARNESS]
```

### DOCX Generation

Uses `pandoc` (MIT) to convert Markdown → DOCX. A reference template (`skills/report_gen/report_template.docx`) is used if present for styling. Requires `pandoc` on your PATH:

```bash
brew install pandoc    # macOS
apt install pandoc     # Linux
```

---

## oscal_gap_map.py (Script, Not CLI)

**File:** `scripts/oscal_gap_map.py`
**Not installed as a CLI binary** — run directly with `python3`.

```bash
python3 scripts/oscal_gap_map.py \
    --gap-analysis gap_analysis.json \
    --org my-org \
    --out-json backlog.json

# Override ISO 27001:2022 mapping (optional — auto-detected by default)
python3 scripts/oscal_gap_map.py \
    --gap-analysis gap_analysis.json \
    --org my-org \
    --out-json backlog.json \
    --iso27001-map config/iso27001/sscf_to_iso27001_mapping.yaml
```

Maps `gap_analysis.json` findings to SSCF controls using `config/oscal-salesforce/sbs_to_sscf_mapping.yaml`. Produces `backlog.json` with remediation items, SSCF control references, `mapping_confidence` (high/medium/low), and ISO 27001:2022 Annex A control enrichment.

Controls starting with `SBS-` are looked up directly — no `control_mapping.yaml` needed. Controls starting with `SSCF-` are mapped directly (Workday/WSCC path — no intermediate translation).

**ISO 27001:2022 enrichment:** Each mapped item gains `iso27001_controls[]` (id, title, theme, mapping_strength, applicability) and `iso27001_control_ids[]` derived from the SSCF→ISO 27001 mapping at `config/iso27001/sscf_to_iso27001_mapping.yaml`. The backlog summary includes an `iso27001_summary` block with counts of unique Annex A controls touched. Skipped if the mapping file is absent.

---

## nist-review

**Binary:** `nist-review`
**Source:** `skills/nist_review/nist_review.py`
**Purpose:** Validates multi-agent assessment outputs against NIST AI RMF 1.0 (Govern, Map, Measure, Manage) and produces a structured verdict JSON.

### Command

```bash
nist-review assess \
  --gap-analysis <path/to/gap_analysis.json> \
  --backlog      <path/to/backlog.json> \
  --out          <path/to/nist_review.json> \
  [--dry-run]
```

### Options

| Option | Required | Description |
|---|---|---|
| `--gap-analysis` | Yes (live) | Path to `gap_analysis.json` from `oscal-assess` |
| `--backlog` | Yes (live) | Path to `backlog.json` from `oscal_gap_map` |
| `--out` | Yes | Output path for `nist_review.json` |
| `--dry-run` | No | Produce realistic stub verdict without calling the API |

### Output format

```json
{
  "nist_ai_rmf_review": {
    "assessment_id": "sfdc-assess-...",
    "reviewed_at_utc": "2026-03-03T...",
    "govern":  { "status": "pass|partial|fail", "notes": "..." },
    "map":     { "status": "pass|partial|fail", "notes": "..." },
    "measure": { "status": "pass|partial|fail", "notes": "..." },
    "manage":  { "status": "pass|partial|fail", "notes": "..." },
    "overall": "pass|flag|block",
    "blocking_issues": [],
    "recommendations": ["..."]
  }
}
```

### Live mode

In live mode, calls `gpt-5.3-chat-latest` with `agents/nist-reviewer.md` as system prompt. A deterministic `_build_review_context()` summarizer is used instead of raw JSON truncation — all critical/high findings are always included in full regardless of payload size. Requires `OPENAI_API_KEY`.

### Dry-run mode

Emits a realistic weak-org stub verdict: GOVERN=pass, MAP=partial, MEASURE=pass, MANAGE=partial, overall=flag. Does not call the OpenAI API.

---

## workday-connect

**Binary:** `workday-connect`
**File:** `skills/workday_connect/workday_connect.py`
**Spec:** `skills/workday_connect/SKILL.md`
**Purpose:** Authenticates to a Workday HCM/Finance tenant and collects security-relevant configuration across 30 WSCC controls (OAuth 2.0, RaaS/REST/manual, 12 automated tests).

### Auth

OAuth 2.0 Client Credentials — no password credentials. All calls (REST, RaaS) use short-lived Bearer tokens. No SOAP.

```bash
WD_TENANT=acme_dpt1
WD_CLIENT_ID=...
WD_CLIENT_SECRET=...   # never logged
WD_TOKEN_URL=https://acme_dpt1.workday.com/ccx/oauth2/acme_dpt1/token
```

### Collection methods

| Method | Transport | Count |
|---|---|---|
| `rest` | GET JSON with Bearer | 1 control (WD-IAM-007: `/staffing/v6/workers`) |
| `raas` | GET JSON with Bearer | 10 controls (pre-configured custom reports) |
| `manual` | N/A — questionnaire required | 19 controls |

### Graceful degradation

- RaaS report not pre-configured → `not_applicable + raas_available: false`
- REST permission denied → `partial`
- Manual controls → always `not_applicable`

### Dev without a live tenant

Use WireMock:
```bash
docker run -d --name workday-mock -p 8080:8080 \
  -v ./tests/workday_mocks:/home/wiremock/mappings wiremock/wiremock:latest
# Set WD_BASE_URL=http://localhost:8080 in .env
```

Stub files: `tests/workday_mocks/` — one JSON file per REST endpoint and RaaS report.

### Output

`docs/oscal-salesforce-poc/generated/workday_raw.json` — `baseline_assessment_schema.json` v2 compliant, `"platform": "workday"`.

---

## drift_check.py (Script)

**File:** `scripts/drift_check.py`
**Not installed as a CLI binary** — run directly with `python3`.

```bash
python3 scripts/drift_check.py \
    --baseline docs/.../generated/<org>/<date1>/backlog.json \
    --current  docs/.../generated/<org>/<date2>/backlog.json \
    --out      drift_report.json \
    --out-md   drift_report.md
```

Compares two `backlog.json` snapshots and classifies every control change:

| Change type | Meaning |
|---|---|
| `regression` | Was pass/not_applicable → now fail/partial |
| `improvement` | Was fail → now partial (partially remediated) |
| `resolved` | Was fail/partial → now pass (fully remediated) |
| `new_finding` | Not present in baseline; appears in current |
| `unchanged` | Same status in both snapshots |
| `severity_change` | Status unchanged but severity changed |

**Outputs:**
- `drift_report.json` — structured report with `pass_rate_delta`, `net_direction` (improving/regressing/stable), per-control change list
- `drift_report.md` — Markdown tables with change icons (🔴 regression, 🟢 resolved, 🟡 improvement)

The orchestrator can call this via the `backlog_diff` tool (defined in `harness/tools.py`).

---

## generate_sbs_oscal_catalog.py (Script)

**File:** `scripts/generate_sbs_oscal_catalog.py`
**Purpose:** Converts `docs/oscal-salesforce-poc/generated/sbs_controls.json` → OSCAL 1.1.2 `config/oscal-salesforce/sbs_catalog.json`.

```bash
python3 scripts/generate_sbs_oscal_catalog.py [--dry-run]
```

Maps custom JSON fields to OSCAL parts: `statement`, `guidance`, `objective` (audit procedure), `implementation-guidance` (remediation), `default-value`. Groups controls by category. Adds `sscf-control` prop and SSCF catalog link from `sbs_to_sscf_mapping.yaml`.

---

## Agent Enrichment Calls

These are **not CLI skills** — they are OpenAI sub-calls made directly by the orchestrator using `_dispatch_agent_call()` in `harness/tools.py`. They inject agent intelligence into the pipeline between CLI stages. Each returns a JSON payload with `status`, `analysis`, and `flags`.

### collector_enrich

**Dispatcher:** `_dispatch_collector_enrich` (harness/tools.py)
**Agent invoked:** `collector`
**Input:** `collector_output` (path to `sfdc_raw.json` or `workday_raw.json`)

Reviews raw collector output for evidence quality before assessment runs. Flags missing API scopes, stale evidence references, and data quality issues (missing timestamps, empty `evidence_ref`). Skipped on dry-run.

**FLAG tokens:** `missing_scope:<scope>`, `stale_evidence:<control_id>`

---

### assessor_analyze

**Dispatcher:** `_dispatch_assessor_analyze` (harness/tools.py)
**Agent invoked:** `assessor`
**Input:** `gap_analysis` (path to `gap_analysis.json`)

Reviews gap analysis findings for confidence issues after `oscal-assess`. Identifies low-confidence critical findings, controls with `needs_expert_review: true` that lack notes, and whether the unmapped findings rate exceeds 20%.

**FLAG tokens:** `low_confidence_critical:<control_id>`, `expert_review_pending:<control_id>`, `unmapped_findings_threshold_exceeded`

---

### workday_expert_enrich

**Dispatcher:** `_dispatch_workday_expert_enrich` (harness/tools.py)
**Agent invoked:** `workday-expert`
**Input:** `gap_analysis` (path to `gap_analysis.json`)

Enriches Workday findings where `needs_expert_review: true` or `data_source: permission_denied`. For each finding, identifies the missing Workday domain security policy grant, the exact RaaS report or REST endpoint for evidence, and whether an ISSG grant resolves it. Writes `expert_notes` back to `gap_analysis.json`. Returns `enriched_findings` count.

---

### security_reviewer_review

**Dispatcher:** `_dispatch_security_reviewer_review` (harness/tools.py)
**Agent invoked:** `delivery-reviewer`
**Input:** `report_path` (path to the generated security assessment Markdown)

Final delivery-quality pass on the security report before it is sent to a stakeholder. Checks for credential exposure, status misrepresentation, and scope violations. `credential_exposure` and `scope_violation` flags delay `finish()` until human acknowledgement.

> **Agent distinction:**
> - `delivery-reviewer` — reviews **report output** for delivery QA (credential exposure, softened findings, scope violations). Invoked here via `security_reviewer_review`.
> - `security-reviewer` — reviews **repo/CI/AppSec posture** (workflow files, skill CLIs, PRs). Invoked on-demand for DevSecOps review; not a pipeline dispatch.

**FLAG tokens:** `credential_exposure:<detail>`, `status_misrepresentation:<control_id>`, `scope_violation:<section>`
