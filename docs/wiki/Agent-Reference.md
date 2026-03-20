# Agent Reference

All 10 agents in the system. Each has a definition file in `agents/` with YAML frontmatter and a full role description.

---

## Orchestrator

| Field | Value |
|---|---|
| **File** | `agents/orchestrator.md` |
| **Model** | `gpt-5.3-chat-latest` |
| **Tools** | All 7 CLI skills + agent sub-call dispatchers |
| **Invoked by** | Human / CI (entry point for all requests) |

**Role:** Routes all tasks. Manages the 18-turn ReAct loop. Enforces quality gates. Assembles final output. Calls `finish()` after the last pipeline step to exit the loop cleanly.

**Does NOT:**
- Call `sfdc-connect` and interpret raw results itself (delegates to collector)
- Write report content (delegates to reporter)
- Assume defaults — always confirms org/env/platform/audience before starting

**Quality gates it enforces:**
1. Any `critical/fail` finding → blocks output on live runs (bypass: `--approve-critical`)
2. nist-reviewer `block` verdict → prepends ⛔ banner and blocks distribution
3. Output schema violation → blocks output
4. Missing `assessment_time_utc` or `assessment_id` → blocks output
5. `security_reviewer_review` returns `credential_exposure` or `scope_violation` flag → blocks `finish()` until acknowledged

**Routing table (tool call sequences):**

| Request | Tool Call Sequence |
|---|---|
| **Full Salesforce assessment (live)** | `sfdc_connect_collect` → `collector_enrich` → [`backlog_diff` if prior run] → `oscal_assess_assess` → `assessor_analyze` → [`sfdc_expert_enrich` if expert_review_pending] → `oscal_gap_map` → `sscf_benchmark_benchmark` → `nist_review_assess(platform=salesforce)` → `gen_aicm_crosswalk` → `report_gen_generate(app-owner)` → `report_gen_generate(security)` → `security_reviewer_review` → `finish()` |
| **Full Workday assessment (live)** | `workday_connect_collect` → `collector_enrich` → [`backlog_diff` if prior run] → `oscal_assess_assess` → `assessor_analyze` → [`workday_expert_enrich` if expert_review_pending] → `oscal_gap_map` → `sscf_benchmark_benchmark` → `nist_review_assess(platform=workday)` → `gen_aicm_crosswalk` → `report_gen_generate(app-owner)` → `report_gen_generate(security)` → `security_reviewer_review` → `finish()` |
| **Salesforce dry-run** | `oscal_assess_assess(--dry-run --platform salesforce)` → `assessor_analyze` → `oscal_gap_map` → `sscf_benchmark_benchmark` → `nist_review_assess(--dry-run)` → `gen_aicm_crosswalk` → `report_gen_generate(--mock-llm, security)` → `finish()` |
| **Workday dry-run** | `workday_connect_collect(--dry-run)` → `oscal_assess_assess(--dry-run --platform workday)` → `assessor_analyze` → `oscal_gap_map` → `sscf_benchmark_benchmark` → `nist_review_assess(--dry-run)` → `gen_aicm_crosswalk` → `report_gen_generate(--mock-llm, security)` → `finish()` |
| **Drift check only** | `backlog_diff(baseline=<prior_backlog>, current=<new_backlog>)` → `finish()` |
| **Gap map from existing JSON** | `oscal_gap_map` → `sscf_benchmark_benchmark` → `report_gen_generate` |
| **Report refresh** | `report_gen_generate(app-owner)` + `report_gen_generate(security)` |
| **NIST AI RMF validation** | nist-reviewer (text analysis — no tool call) |
| **CI/CD or skill security review** | security-reviewer (text analysis — no tool call) |
| **Salesforce API / Apex question** | sfdc-expert (text analysis) |
| **Workday RaaS / REST question** | workday-expert (text analysis) |
| **Docker / OpenSearch issue** | container-expert (text analysis + proposed config) |
| **Control or CVE research** | assessor context — no tool calls |

---

## Collector

| Field | Value |
|---|---|
| **File** | `agents/collector.md` |
| **Model** | `gpt-5.3-chat-latest` |
| **Tools** | `sfdc-connect` (Salesforce), `workday-connect` (Workday) |
| **Invoked by** | Orchestrator via `collector_enrich` dispatcher |
| **Schema** | STRICT — 6-field canonical schema enforced; fail-closed |

**Role:** Platform-aware collector for both Salesforce and Workday. Extracts SaaS org configuration via platform-native APIs and packages it for the assessor. Produces structured findings conforming to `schemas/baseline_assessment_schema.json`.

- **Salesforce:** JWT Bearer auth via REST/Tooling/Metadata API
- **Workday:** OAuth 2.0 Client Credentials via RaaS/REST + manual questionnaire fallback

**Critical constraint:** Never logs credentials. Never queries record-level data (Contacts, Accounts, Opportunities, Workers). Read-only on all platforms.

---

## Assessor

| Field | Value |
|---|---|
| **File** | `agents/assessor.md` |
| **Model** | `gpt-5.3-chat-latest` |
| **Tools** | `oscal-assess`, `oscal_gap_map` |
| **Invoked by** | Orchestrator via `assessor_analyze` dispatcher |
| **Schema** | STRICT — 6-field canonical schema enforced; fail-closed |

**Role:** Platform-aware assessor for both Salesforce and Workday. Maps collected platform config to OSCAL controls, runs the rule engine, and produces findings with status and severity.

- **Salesforce:** 45 SBS controls (OSCAL 1.1.2 sub-profile)
- **Workday:** 30 WSCC controls (OSCAL 1.1.2 sub-profile)

**Control assignment:** Conservative — only marks `pass` when definitively met. Ambiguous → `partial`. Controls that cannot be evaluated without write access → `not_applicable`.

---

## Reporter

| Field | Value |
|---|---|
| **File** | `agents/reporter.md` |
| **Model** | `gpt-5.3-chat-latest` |
| **Tools** | `report-gen` |
| **Invoked by** | Orchestrator (after `gen_aicm_crosswalk` completes) |

**Role:** Generates governance outputs. Two runs per assessment — once for `app-owner` (Markdown), once for `security` (Markdown + DOCX). Platform-aware for both Salesforce (SBS) and Workday (WSCC).

**Security report sections (in order):**

| Section | Source |
|---|---|
| Gate banner (⛔ / 🚩) | NIST verdict |
| Executive Scorecard | Harness — overall score + severity × status matrix |
| Domain Posture chart | Harness — ASCII bar chart per SSCF domain |
| OSCAL Framework Provenance | Harness — catalog → profile → ISO 27001 → CCM chain |
| CCM v4.1 Regulatory Crosswalk | Harness — fail/partial → SOX/HIPAA/SOC2/PCI DSS/GDPR |
| ISO 27001:2022 SoA | Harness — all 93 Annex A controls with status + evidence |
| Immediate Actions (Top 10) | Harness — sorted critical/fail findings |
| Executive Summary + Risk Analysis | LLM narrative (2 sections only) |
| Full Control Matrix | Harness — complete sorted findings table |
| Plan of Action & Milestones | Harness — POAM-IDs, owners, due dates, status |
| Not Assessed Controls | Harness — out-of-scope appendix for auditors |
| NIST AI RMF Governance Review | Harness — function table + blockers + recs |
| AICM Coverage Annex | Harness — CSA AICM v1.0.3, 243 controls, 18 domains |

---

## NIST Reviewer

| Field | Value |
|---|---|
| **File** | `agents/nist-reviewer.md` |
| **Model** | `gpt-5.3-chat-latest` |
| **Tools** | None (text analysis only) |
| **Invoked by** | Orchestrator via `nist_review_assess` skill |

**Role:** Validates all outputs against the NIST AI RMF 1.0 (Govern, Map, Measure, Manage). Platform-aware — issues Salesforce (SBS) or Workday (WSCC) specific verdicts. Final governance gate before any output reaches human stakeholders.

**Checks:**
- Transparency documentation and accountability trail (`assessment_id`, `assessment_time_utc`, `assessor`, `assessment_owner`)
- Low-confidence mapping percentage (assessable findings only — excludes `not_applicable`)
- Bias and fairness considerations in AI-generated findings
- Risk categorisation alignment with NIST AI RMF functions

**Verdicts:** `pass` → `flag` (review required) → `block` (do not distribute). A `block` prepends ⛔ to both reports; `flag` prepends 🚩.

**Why no tools?** Review is analytical. Tool access would risk accidental state modification.

---

## Delivery Reviewer

| Field | Value |
|---|---|
| **File** | `agents/delivery-reviewer.md` |
| **Model** | `gpt-5.3-chat-latest` |
| **Tools** | None (text analysis only) |
| **Invoked by** | Orchestrator via `security_reviewer_review` tool dispatcher |
| **Schema** | STRICT — block-status enforced; fail-closed |

**Role:** Final delivery-quality pass on the security report immediately before `finish()`. Checks for:

- **Credential exposure** — org URLs, usernames, internal identifiers in a deliverable → `FLAG: credential_exposure:<detail>`
- **Status misrepresentation** — language that softens a fail/critical finding → `FLAG: status_misrepresentation:<control_id>`
- **Scope violations** — any section implying write permissions beyond read-only OSCAL/SSCF scope → `FLAG: scope_violation:<section>`

`credential_exposure` and `scope_violation` flags block `finish()` until human acknowledgement. `status_misrepresentation` is a warning only and does not block delivery.

When the review returns no critical flags, the harness injects a nudge message directing the orchestrator to call `finish()` immediately.

> **Not to be confused with `security-reviewer`**, which reviews repo/CI/AppSec posture (workflow files, skill CLIs, PRs) and is invoked on-demand outside the pipeline.

---

## Security Reviewer

| Field | Value |
|---|---|
| **File** | `agents/security-reviewer.md` |
| **Model** | `gpt-5.3-chat-latest` (via `LLM_MODEL_ANALYST`) |
| **Tools** | None (text analysis only) |
| **Invoked by** | On-demand — CI/CD, workflow, or skill changes (not a pipeline dispatch) |

**Role:** Expert AppSec + DevSecOps reviewer. Reviews:
- `.github/workflows/` — expression injection, permissions, unpinned actions
- `skills/**/*.py` — subprocess safety, SOQL injection, HTTP timeouts, path traversal
- `harness/**/*.py` — control flow leaks, tool input validation, credential logging
- `agents/**/*.md` — scope creep, bypass instructions, prompt injection
- `pyproject.toml` — version ranges, license conflicts, deprecated packages

**Severity levels:** CRITICAL, HIGH, MEDIUM, LOW. CRITICAL/HIGH block merge.

**Anti-patterns always flagged:**
1. `subprocess.run(..., shell=True)` with any non-static argument
2. `eval()` or `exec()`
3. `pickle.loads()` on untrusted input
4. `yaml.load()` without `Loader=yaml.SafeLoader`
5. `os.system()` with variable content
6. Credentials in any committed file
7. `allow_redirects=True` on user-supplied URLs
8. `verify=False` on TLS connections

---

## SFDC Expert

| Field | Value |
|---|---|
| **File** | `agents/sfdc-expert.md` |
| **Model** | `gpt-5.3-chat-latest` |
| **Tools** | None (text analysis + code generation only) |
| **Invoked by** | Orchestrator via `sfdc_expert_enrich` when findings have `needs_expert_review=true` |
| **Schema** | STRICT — 6-field canonical schema enforced; fail-closed |

**Role:** On-call Salesforce specialist. Handles complex questions the assessor cannot resolve through CLI tools — Apex code review, Flow/Process Builder security issues, SOQL injection patterns, Connected App scope analysis. See `apex-scripts/README.md` for Apex security patterns.

**Outputs:** Plain-text analysis and Apex code snippets (never executed — for human review only).

---

## Workday Expert

| Field | Value |
|---|---|
| **File** | `agents/workday-expert.md` |
| **Model** | `gpt-5.3-chat-latest` |
| **Tools** | None (text analysis + code generation only) |
| **Invoked by** | Orchestrator via `workday_expert_enrich` when Workday API calls fail or controls need clarification |
| **Schema** | STRICT — 6-field canonical schema enforced; fail-closed |

**Role:** On-call Workday HCM/Finance specialist. Handles complex Workday questions — RaaS report configuration, security group membership APIs, ISSG policies, OAuth 2.0 troubleshooting, and manual questionnaire guidance for controls inaccessible via API.

**Outputs:** Plain-text analysis and Workday RaaS/REST guidance (never executed — for human review only).

---

## Container Expert

| Field | Value |
|---|---|
| **File** | `agents/container-expert.md` |
| **Model** | `gpt-5.3-chat-latest` |
| **Tools** | None (text analysis + config generation only) |
| **Invoked by** | Orchestrator for Docker Compose, OpenSearch, or dashboard issues |

**Role:** Specialist for the optional containerised monitoring stack. Handles Docker Compose configuration, OpenSearch 2.x cluster tuning, JVM heap sizing, NDJSON dashboard imports, `vm.max_map_count` issues on Linux, and production TLS setup (`docker-compose.prod.yml`).

**Outputs:** Docker Compose YAML, OpenSearch configuration, troubleshooting guidance.

---

## Adding a New Agent

1. Create `agents/<name>.md` with YAML frontmatter:
   ```yaml
   ---
   name: my-agent
   description: What it does and when to use it
   model: gpt-5.3-chat-latest
   tools: []
   ---
   ```
2. Add `AgentConfig` to `harness/agents.py`
3. Add row to `AGENTS.md`
4. Add routing entry to `agents/orchestrator.md`
5. If the agent produces findings, add it to `STRICT_AGENTS` in `harness/tools.py` for 6-field schema enforcement
6. Run `security-reviewer` on the new agent file before merging
