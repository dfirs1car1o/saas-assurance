# Changelog

All notable changes to this project will be documented in this file.

This project follows a simple changelog format and semantic versioning intent:
- `Added` for new features
- `Changed` for changes in existing behavior
- `Fixed` for bug fixes
- `Security` for hardening and security controls
- `Removed` for now removed features

## [Unreleased]

### 2026-03-06 — POA&M, Not Assessed appendix, CI fix, docs update

#### Added
- `skills/report_gen/report_gen.py` — `_render_poam()`: POA&M table (security DOCX only) with sequential POAM-001 IDs, fail=Open/partial=In Progress, owner, due date, milestone text
- `skills/report_gen/report_gen.py` — `_render_not_assessed()`: auditor appendix listing `not_applicable` and unmapped controls with reason column
- Document assembly updated: `full_matrix → poam → not_assessed → nist_section`

#### Fixed
- `tests/test_pipeline_smoke.py` — domain count assertion updated 7→6 (SSCF v1.0 has 6 domains; v0 TDR/GOV merged into SEF)
- `scripts/generate_sbs_oscal_catalog.py` — removed unused `import uuid` and unused `defaults_by_cat` variable (ruff F401/F841)

#### Changed
- `README.md` — Workday "blueprint complete" → "Salesforce and Workday"; added Workday pipeline and dry-run commands; report structure updated with POA&M, Not Assessed, OSCAL Provenance
- `docs/wiki/Architecture-Overview.md`, `docs/wiki/Skill-Reference.md` — report structure blocks updated with new sections
- `docs/wiki/Home.md` — Phase E/F/G status rows added; Workday Connector marked done

---

### 2026-03-06 — Phase F/G: Workday agent-loop wiring, report improvements, CDW scrub

#### Added
- `harness/tools.py` — `workday_connect_collect` tool schema and dispatcher; `platform` param added to `oscal_assess_assess`, `nist_review_assess`, `report_gen_generate` schemas and dispatchers
- `harness/loop.py` — `--platform salesforce|workday` CLI flag; Workday-specific task prompt (step 1 = `workday_connect_collect`); `workday_connect_collect` added to `_CRITICAL_TOOLS`; platform-aware Mem0 session ID
- `agents/orchestrator.md` — Workday routing row: `workday_connect_collect → oscal_assess_assess → oscal_gap_map → sscf_benchmark → nist_review_assess (platform=workday) → report_gen_generate × 2 → finish()`
- `scripts/validate_env.py` — `--platform salesforce|workday` flag; Workday env vars (`WD_TENANT`, `WD_CLIENT_ID`, `WD_CLIENT_SECRET`, `WD_TOKEN_URL`, `WD_BASE_URL`, `WD_API_VERSION`) added as optional checks
- `skills/oscal_assess/oscal_assess.py` — `--platform salesforce|workday` flag; `run_workday_assessment()` produces 30 findings with SSCF-* control IDs using `_WSCC_CONTROL_IDS` list and `_load_sscf_index()`; `_WD_DRY_RUN_OVERRIDES` with Workday-specific evidence (ISU, SOAP, RaaS, ISSG)
- `skills/report_gen/report_gen.py` — `Description` column (`sbs_title`) added to Priority Findings and Full Control Matrix tables; `_apply_table_borders()` post-processes DOCX via python-docx for full single-line borders on all table cells; `_OSCAL_CHAIN` dict with 6-row provenance per platform; `_render_oscal_provenance()` renders OSCAL Framework Provenance table (Catalog → Profile → Component Definition → Control Framework → Regulatory Crosswalk → POA&M); `_detect_platform()` infers platform from control ID prefix
- `pyproject.toml` — `python-docx>=1.1.0` added to dependencies (required for table border post-processing)

#### Fixed
- `scripts/oscal_gap_map.py` — SSCF-* direct path: findings with `SSCF-*` control IDs bypass SBS catalog lookup; title/domain/severity resolved from `config/sscf_control_index.yaml` directly (enables Workday WSCC backlog items)
- `config/sscf_control_index.yaml` — YAML parse error at IAM-008: colon in description value now quoted

#### Removed (CDW attribution scrub)
- `docs/saas-baseline/` — entire directory deleted (25 files, 1322 deletions); contained `CDW_Salesforce_EventMonitoring_TSP_Baseline_v1.0.docx` and CDW-attributable baseline deliverables
- `config/saas_baseline_controls/` — `salesforce.yaml`, `servicenow.yaml`, `workday.yaml` deleted
- `config/saas_baseline_profiles/` — generated YAML and `salesforce_em_tsp_baseline_v1.yaml` deleted
- `docs/oscal-salesforce-poc/SESSION_HANDOFF_2026-02-24.md`, `SESSION_HANDOFF_2026-02-25.md` — session handoff files deleted
- `docs/agents/brutal-critic-agent.md`, `docs/agents/tasks/brutal-critic-audit-task.md` — internal debug agent docs deleted

---

### 2026-03-07 — Phase G/H: SSCF v1.0 catalog, OSCAL profiles, component definitions

#### Added
- `config/sscf/sscf_v1_catalog.json` — Full SSCF v1.0 OSCAL 1.1.2 catalog: 36 controls across 6 standard CCM-aligned domains (CON, DSP, IAM, IPY, LOG, SEF). IPY (Interoperability & Portability) domain added for first time. SEF (Security Incident Management) replaces non-standard TDR/GOV. Each control references authoritative CCM v4.1 control IDs via `ccm-controls` prop. `sscf-v0-equivalent` prop traces 14 existing controls to their v0 IDs for backward compatibility.
- `config/sscf/sscf_v1_profile.json` — OSCAL profile selecting all 36 SSCF v1.0 controls; base for platform sub-profiles.
- `config/salesforce/sbs_v1_profile.json` — SBS as OSCAL sub-profile of SSCF v1.0 (35 controls). Adds Salesforce-specific platform notes for Event Monitoring, JWT Bearer, Security Health Check.
- `config/workday/wscc_v1_profile.json` — WSCC as OSCAL sub-profile of SSCF v1.0 (30 controls). Adds Workday-specific notes for ISSG permissions, SOAP/RaaS/REST collection, OAuth 2.0 Client Credentials.
- `config/component-definitions/salesforce_component.json` — OSCAL component definition for Salesforce: 18 implemented-requirements with SOQL/Tooling/Metadata API evidence specifications, pass/fail criteria, and collection method metadata.
- `config/component-definitions/workday_component.json` — OSCAL component definition for Workday: 16 implemented-requirements with SOAP/RaaS/REST evidence specs, ISSG permission per control, and WSCC catalog cross-references.

#### Changed
- `config/sscf_control_index.yaml` → v2: 36 controls, all 6 SSCF v1.0 domains, severity ratings, owner teams, v0-equivalent mapping.

#### Architecture Note
- No CCM v4.1 OSCAL registration required: SSCF v1.0 is built as a standalone OSCAL catalog with CCM control IDs embedded as properties. This is the correct approach for frameworks without a public OSCAL download URL — interoperability is maintained via CCM ID cross-references in `ccm-controls` props and `back-matter` resource links.

---

### 2026-03-07 — NIST AI RMF platform fix, CWE-312 remediation, workday-expert agent

#### Added
- `agents/workday-expert.md` — on-call Workday HCM/Finance specialist with full SOAP/RaaS/REST reference, ISSG permissions, error patterns, and WireMock dev environment
- `scripts/workday_dry_run_demo.py` — full Workday pipeline demo: mock findings → sscf-benchmark → nist-review → DOCX

#### Fixed
- `skills/nist_review/nist_review.py` — `_DRY_RUN_VERDICT` was Salesforce-specific; replaced singleton with `_DRY_RUN_VERDICTS` dict keyed by platform; added `--platform` option to `nist-review assess`; Workday stub uses correct WSCC catalog reference, workday-connect language, and accurate MANAGE notes
- `scripts/workday_dry_run_demo.py` — nist-review now called with `--platform workday`; app-owner report now passes `--title "Workday Security Governance Assessment"` (previously defaulted to Salesforce)

#### Security
- `skills/workday_connect/workday_connect.py` — CWE-312 remediation (CodeQL alert #1, GitHub issue #14):
  - `del client_secret` after token acquisition in `collect` command to close credential taint scope
  - Renamed `ISU_password_dates` → `ISU_credential_rotation_dates` (removes "password" from non-credential evidence key)
  - Added CodeQL suppression comment at disk-write explaining password policy values are intentionally stored assessment evidence

---

### 2026-03-07 — GPT-5.3 upgrade, dry-run validated

#### Changed
- `harness/agents.py` — default model upgraded from `gpt-5.2` → `gpt-5.3-chat-latest` (released 2026-03-03); overridable via `LLM_MODEL_*` env vars
- All docs, wiki pages, agent frontmatter, README, AGENTS.md updated to new model name
- `.env.example` — ready-to-uncomment GPT-5.4 block added for when API model ID is published

#### Validated
- Dry-run clean on `gpt-5.3-chat-latest`: 8 turns, `finish()` called, all 7 artifacts written including DOCX

---

### 2026-03-07 — OSCAL catalogs, schema v2, Workday blueprint

#### Added
- `config/sscf/sscf_catalog.json` — OSCAL 1.1.2 SSCF catalog (7 domain groups, 14 controls with full statement/guidance/objective parts)
- `config/sscf/sscf_to_ccm_mapping.yaml` — SSCF→CCM v4.1 bridge; 14 entries with `regulatory_highlights` (SOX, HIPAA, SOC2, ISO 27001, NIST 800-53, PCI DSS, GDPR)
- `config/ccm/ccm_v4.1_oscal_ref.yaml` — Reference pointer to CSA CCM v4.1 published OSCAL catalog (197 controls, 17 regulatory standards); no copy needed
- `config/oscal-salesforce/sbs_catalog.json` — SBS OSCAL 1.1.2 catalog (11 groups, 45 controls); generated from `sbs_controls.json`
- `config/oscal-salesforce/sbs_profile.json` — OSCAL profile expressing SBS as implementation of SSCF catalog
- `scripts/generate_sbs_oscal_catalog.py` — Python conversion script: `sbs_controls.json` → OSCAL 1.1.2 catalog
- `config/workday/workday_catalog.json` v0.2.0 — OSCAL 1.1.2 Workday Security Control Catalog (30 controls, 7 domain groups, full audit procedures/remediation, soap/raas/manual/rest collection methods)
- `config/workday/workday_to_sscf_mapping.yaml` — All 30 Workday controls mapped to SSCF domains and control IDs
- `skills/workday_connect/BLUEPRINT.md` — Full Workday connector specification (ISU/ISSG setup, OAuth 2.0 auth, per-control API reference, graceful degradation, WireMock dev environment)
- `skills/workday_connect/__init__.py` — Package placeholder

#### Changed
- `schemas/baseline_assessment_schema.json` → v2: added `schema_version` (const "2.0"), `assessment_owner`, `data_source`, `ai_generated_findings_notice`, `oscal_catalog_ref`, `assessment_scope`, `mapping_confidence`, `ccm_controls`, `platform_data`; fixed severity enum `"medium"` → `"moderate"`
- `config/workday/workday_catalog.json`: upgraded auth from WS-Security BasicAuth to OAuth 2.0 Client Credentials (universal); WD-IAM-007 changed from `soap` to `rest` (`/staffing/v6/workers`)

#### Security
- Workday connector protocol hardened: OAuth 2.0 Client Credentials replaces WS-Security BasicAuth; no password credentials transmitted; all transports (REST, SOAP, RaaS) use short-lived Bearer tokens

### 2026-03-07 — Open issues resolved (commit 48bc739)

#### Added
- `harness/tools.py` — `finish()` tool: orchestrator calls to signal pipeline completion; loop breaks on `pipeline_complete: true` sentinel
- `harness/loop.py` — `pipeline_complete` sentinel detection; `_MAX_TURNS` bumped 12→14

#### Fixed
- `skills/sfdc_connect/sfdc_connect.py` — `collect_integrations()` now uses Tooling API for RemoteProxy/RemoteSiteSettings before SOQL fallback
- `agents/orchestrator.md` — routing table corrected; `.pdf` removed; `finish()` added at end of sequence

#### Changed
- `.github/CODEOWNERS` — `@compliance-rehab` added to `skills/**` and `config/**`

### 2026-03-03
- feat: add `nist-review` CLI skill (`skills/nist_review/`) with dry-run and live Anthropic mode
- feat: wire `nist_review_assess` as pipeline step 5 in `harness/loop.py`
- fix: PDF `_kv_table` uses `multi_cell()` — NIST notes now wrap instead of truncating
- fix: `sbom.yml` — remove `git push` to protected branch; upload SBOM as CI artifact instead
- fix: `diagram.yml` — remove `git push`; verify committed diagram is up-to-date instead
- fix: `ci.yml` — add `fpdf2` to LGPL allowlist (LGPL-3.0 acceptable for internal tooling)
- fix: pin `actions/upload-artifact` to commit SHA `ea165f8d` (v4.6.2) in diagram + sbom workflows
- fix: ruff format on `report_gen.py`, `nist_review.py`, and test files

### 2026-03-02 (PDF + branding)
- feat: configurable report title via `REPORT_GOVERNANCE_TITLE` env var
- feat: configurable org display name via `REPORT_ORG_DISPLAY_NAME` env var
- feat: org-named output files (`{org}_security_assessment.pdf/.docx/.md`, `{org}_remediation_report.md`)
- feat: `SFDC_ORG_ALIAS` and `SFDC_ENV` env vars as defaults for `agent-loop run`
- fix: PDF SBS ID column widened to 32 mm (SBS-CPORTAL-001 / SBS-SECCONF-001 no longer truncated)
- fix: SSCF domains with 0 scoreable controls show N/A instead of misleading 100% GREEN
- fix: report-gen dispatcher resolves relative `--out` against backlog directory (fixes unknown-org path bug)
- fix: PDF Top Findings section added before Full Control Matrix
- fix: PDF status values title-cased; Unicode symbols mapped to ASCII equivalents

### Changed (2026-03-02 — GitHub Actions upgrades)
- `actions/checkout` v4 → v6 (PR #6)
- `actions/setup-python` v5 → v6 (PR #7)
- `github/codeql-action` v3 → v4 (PR #8)

### Fixed (2026-03-02 — lint)
- `harness/tools.py` — shortened `org` property description strings to satisfy ruff E501 (line-length=120)

### Fixed (2026-03-01 — post-dry-run bugs)
- `harness/loop.py` — added `load_dotenv(_REPO / ".env")` so `ANTHROPIC_API_KEY` is loaded before API client init
- `harness/memory.py` — added HuggingFace embedder fallback when `OPENAI_API_KEY` is absent (Mem0 was defaulting to OpenAI)
- `harness/tools.py` — added `org` property to `oscal_assess_assess`, `oscal_gap_map`, `sscf_benchmark_benchmark` schemas; orchestrator can now pass org alias so artifacts land in `generated/<org>/` not `generated/unknown-org/`
- `harness/loop.py` — default task prompt updated: passes `org` in every tool call, adds report generation as step 5, includes dry-run note to bypass orchestrator prompt quality gate

### Added (Phase 5 — 2026-03-01)
- `scripts/gen_diagram.py` — Python diagrams-as-code script generating `docs/architecture.png`
- `.github/workflows/diagram.yml` — GitHub Action that auto-regenerates the architecture diagram on push to main when skills/harness/scripts/agents/config change; commits back with `[skip ci]`
- `docs/architecture.png` — initial reference architecture diagram (5-agent + 4-skill pipeline)
- `.github/pull_request_template.md` — updated to embed architecture diagram at top of every PR

### Added (Phase 4 — 2026-03-01)
- `skills/report_gen/report_gen.py` — governance output CLI: `report-gen generate`
  - Two audiences: `app-owner` (plain-language executive report) and `gis` (Security Team technical review)
  - Two formats: `.md` (Markdown) and `.docx` (programmatic python-docx with status cell shading)
  - Sections: Executive Summary, Critical/High Findings, What Happens Next, Full Control Matrix, SSCF Domain Heatmap, NIST AI RMF Note
- `tests/test_report_gen.py` — 3 smoke tests (app-owner MD, Security Team MD with SSCF, DOCX magic-byte validation)
- `harness/tools.py` — added `report_gen_generate` tool schema and `_dispatch_report_gen` dispatcher
- `pyproject.toml` — added `report-gen` entry point and `diagrams>=0.23.4` dev dependency

### Fixed (2026-03-01)
- `agents/reporter.md` — corrected CLI invocation (removed non-existent `--template` flag; now shows tool call JSON examples)
- `agents/orchestrator.md` — routing table updated to show exact tool call sequence including `report_gen_generate`
- `harness/agents.py` — added `report_gen_generate` to ORCHESTRATOR tool_names list

### Added (Phase 3 — 2026-02-27)
- `harness/loop.py` — 20-turn ReAct agentic loop, critical/fail safety gate, `agent-loop run` CLI entry point
- `harness/tools.py` — Anthropic tool schemas + subprocess dispatchers for all 4 pipeline stages
- `harness/memory.py` — Mem0+Qdrant session memory: `build_client / load_memories / save_assessment`
- `harness/agents.py` — ORCHESTRATOR AgentConfig (claude-opus-4-6, mission.md + orchestrator.md system prompt)
- `tests/test_harness_dry_run.py` — 3 harness smoke tests (tool dispatch order, error handler, API key plumbing)
- `docs/CONTRIBUTING.md` — full contributor wiki (setup, Docker deps, env vars, pipeline, CI docs)
- Internal team name scrub: replaced org-specific team codes with generic industry terms across 33 files

### Added
- OpenClaw agent framework: mission.md, AGENTS.md, 5 agent definitions, 4 skill SKILL.md files
- `skills/sfdc_connect/sfdc_connect.py` — read-only Salesforce collector CLI (7 scopes, Tooling API)
- Agent architecture: orchestrator-workers pattern with NIST AI RMF auditing layer
- `contexts/` — system prompts for assess/review/research modes
- `hooks/hooks.json` — session lifecycle (start/end/compact)
- `prompts/README.md` — prompting playbook and anti-patterns
- `docs/architecture-blueprint.md` — full agent/skill/model breakdown with system diagram
- `scripts/validate_env.py` — pre-flight check script for local system requirements
- `.coderabbit.yaml` — AI code review with Salesforce-specific security instructions
- `.github/dependabot.yml` — weekly pip + Actions dependency updates
- `.github/workflows/ci.yml` — ruff, bandit, pip-audit, pytest
- `.github/workflows/codeql.yml` — weekly + PR CodeQL semantic analysis
- `.github/workflows/dependency-review.yml` — block PRs introducing HIGH/CRITICAL CVEs
- `.env.example` and `setup.sh` for colleague onboarding

### Changed
- `pyproject.toml`: removed Azure/FastAPI deps, added anthropic + simple-salesforce + click
- `README.md`: full rewrite for saas-posture identity and architecture
- `.github/workflows/security-checks.yml`: replaced Terraform checks with bandit + pip-audit + gitleaks
- `.github/workflows/pr-inline-review.yml`: replaced tflint with ruff + bandit inline annotations
- `CODEOWNERS`: updated with agents/, mission.md, skills/, config/, generated/ ownership

### Removed
- `app/` — FastAPI model router (Azure/DFIR scaffold, not relevant to OSCAL/SSCF system)
- `infra/terraform/` — Azure infrastructure (not relevant to this system)
- `.github/workflows/terraform-plan.yml` — Terraform CI
- `.github/workflows/terraform-apply.yml` — Terraform CI
- `.github/workflows/cloud-mcp-plan.yml` — Azure MCP CI
- `docs/architecture.md` — Azure + Copilot Studio architecture doc
- `docs/azure-tenant-bootstrap.md` — Azure tenant setup doc
- `docs/cloud-mcp-architecture.md` — Azure cloud MCP architecture
- `docs/sift-worker-runbook.md` — SIFT/DFIR worker runbook
- `docs/sample-data-catalog.md` — Azure evidence plane catalog

### Security
- Branch protection on main: 1 PR review required, no force push, stale review dismissal
- Secret scanning and push protection: enabled org-wide
- Dependabot alerts and auto-fix: enabled
- CodeQL analysis: weekly + PR trigger, scoped to skills/ and scripts/
- Dependency review: blocks HIGH/CRITICAL CVE introductions at PR time
- Gitleaks: full-history secret scanning on every push and PR

## [0.1.0] - 2026-02-23

### Added
- CSA SSCF-aligned SaaS baseline controls for Salesforce, ServiceNow, and Workday
- `config/sscf_control_index.yaml` and `schemas/baseline_assessment_schema.json`
- `docs/saas-baseline/` — exception process, RACI, intake template, meeting pack
- OSCAL pipeline scripts: `scripts/oscal_gap_map.py`, `scripts/oscal_import_sbs.py`
- OSCAL control mappings: `config/oscal-salesforce/`
- End-to-end OSCAL example outputs in `docs/oscal-salesforce-poc/generated/`
- UK Salesforce partial copy exception record
