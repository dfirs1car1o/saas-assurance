# Changelog

All notable changes to this project will be documented in this file.

This project follows a simple changelog format and semantic versioning intent:
- `Added` for new features
- `Changed` for changes in existing behavior
- `Fixed` for bug fixes
- `Security` for hardening and security controls
- `Removed` for now removed features

## [Unreleased]

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
  - Two audiences: `app-owner` (plain-language executive report) and `gis` (CorpIS technical review)
  - Two formats: `.md` (Markdown) and `.docx` (programmatic python-docx with status cell shading)
  - Sections: Executive Summary, Critical/High Findings, What Happens Next, Full Control Matrix, SSCF Domain Heatmap, NIST AI RMF Note
- `tests/test_report_gen.py` — 3 smoke tests (app-owner MD, CorpIS MD with SSCF, DOCX magic-byte validation)
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
- Corporate data scrub: CDW → Acme Corp, BSS → SaaS Security Team, GIS → CorpIS across 33 files

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
- `README.md`: full rewrite for saas-sec-agents identity and architecture
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
