# Contributing — SaaS Security Multi-Agent System

This guide covers everything a new contributor needs to get the repo running locally, understand the architecture, and start contributing safely.

---

## Prerequisites

### Bare Minimum (run the full pipeline)

```text
Python 3.11+  +  git  +  pip install -e .  +  .env with API keys
```

That's it. No Docker, no Node.js, no container runtime required.

| Tool | Version | Install |
|---|---|---|
| Python | ≥ 3.11 | [python.org](https://python.org) or `brew install python@3.11` |
| Git | any recent | pre-installed on macOS/Linux |

### Full Dev Setup (optional extras)

| Tool | Why | Install |
|---|---|---|
| `uv` | Faster installs (optional — plain `pip` works) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| GitHub CLI (`gh`) | PR/issue management from terminal | `brew install gh` |
| Claude Code | Recommended for interactive dev with this repo | `npm install -g @anthropic-ai/claude-code` |

### Not Required

| Item | Reality |
|---|---|
| **Docker Desktop** | Not needed. Session memory runs in-process via `QDRANT_IN_MEMORY=1` (the default). Only needed if you want persistent cross-session memory with a real Qdrant container. |
| **Node.js** | Not needed. Hook files are shell scripts — no JS runtime required. |
| **Claude Desktop** | NOT needed for this repo. Claude Desktop is a chat UI — it does not run `agent-loop`, CLI skills, or any harness code. |
| **Graphviz** | CI-only (used by `diagram.yml` to regenerate the architecture diagram). Not needed locally. |

---

## Claude Code vs Claude Desktop

### Claude Code (CLI) — recommended for this repo

- **What it is:** An AI-powered CLI tool that runs in your terminal
- **Install:** `npm install -g @anthropic-ai/claude-code` (or `brew install claude-code`)
- **Used for:** interactive development, running `agent-loop`, reviewing code, session memory
- **Requirement:** `OPENAI_API_KEY` in `.env` — that's it

### Claude Desktop — NOT needed for this repo

- **What it is:** A desktop chat interface to Claude models
- **It does NOT** run `agent-loop`, harness code, or CLI skills
- No dependency here

**Neither Claude Code nor Claude Desktop is required to run the pipeline. Only `OPENAI_API_KEY` is needed. The pipeline runs as a plain Python CLI.**

---

## Initial Setup

```bash
# 1. Clone
git clone git@github.com:dfirs1car1o/saas-posture.git
cd saas-posture

# 2. Install Python dependencies (includes all dev/test deps)
pip install -e ".[dev]"

# 3. Copy and fill .env
cp .env.example .env
# Edit .env — add SF_USERNAME, SF_CONSUMER_KEY, SF_PRIVATE_KEY_PATH, OPENAI_API_KEY
# (or AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT if using Azure OpenAI)

# 4. Verify everything works
python3 -m pytest tests/ -v
agent-loop run --help
sfdc-connect --help
oscal-assess --help
sscf-benchmark --help
```

> **Session memory** uses `QDRANT_IN_MEMORY=1` by default (set in `.env.example`).
> No Docker container needed. To use a persistent Qdrant container instead, set
> `QDRANT_IN_MEMORY=0` and `QDRANT_HOST=localhost` in `.env`, then run:
> `docker run -d -p 6333:6333 qdrant/qdrant`

---

## Environment Variables

Copy `.env.example` to `.env` and populate:

```bash
# OpenAI API (required for agent-loop)
OPENAI_API_KEY=sk-...

# Salesforce org credentials (required for live assessment — skip for dry-run)
SF_USERNAME=your@email.com
SF_AUTH_METHOD=jwt
SF_CONSUMER_KEY=your-connected-app-consumer-key
SF_PRIVATE_KEY_PATH=/path/to/salesforce_jwt_private.pem
SF_DOMAIN=login                    # or 'test' for sandbox
SF_INSTANCE_URL=https://yourorg.salesforce.com  # optional override

# Org alias used in output file paths
SFDC_ORG_ALIAS=my-org-alias

# Qdrant session memory (default: in-memory, no Docker needed)
QDRANT_IN_MEMORY=1
# QDRANT_HOST=localhost   # only if running a Qdrant container
# QDRANT_PORT=6333        # only if running a Qdrant container
```

> **Never commit `.env`** — it is in `.gitignore`. Never put credentials in any Python file or commit message.

---

## Project Structure

```
saas-posture/
├── mission.md                  ← Agent identity + authorized scope. Read this first.
├── AGENTS.md                   ← Master agent roster and routing logic
├── CLAUDE.md                   ← Claude Code session instructions
│
├── agents/                     ← Per-agent role definitions (markdown + YAML frontmatter)
│   ├── orchestrator.md         ← gpt-5.3-chat-latest: loop control, routing
│   ├── collector.md            ← gpt-5.3-chat-latest: Salesforce API extraction
│   ├── assessor.md             ← gpt-5.3-chat-latest: OSCAL/SBS control mapping
│   ├── reporter.md             ← gpt-5.3-chat-latest: governance output generation
│   ├── nist-reviewer.md        ← gpt-5.3-chat-latest: NIST AI RMF validation
│   └── security-reviewer.md   ← gpt-5.3-chat-latest: CI/CD and AppSec review (Phase 6)
│
├── harness/                    ← Agentic orchestration loop (Phase 3)
│   ├── agents.py               ← AgentConfig dataclass + agent registry
│   ├── tools.py                ← Anthropic tool schemas + subprocess dispatchers
│   ├── memory.py               ← Mem0+Qdrant session memory
│   └── loop.py                 ← agent-loop CLI entry point
│
├── skills/                     ← CLI tools (each installable as a command)
│   ├── sfdc_connect/           ← sfdc-connect: Salesforce org collector
│   ├── oscal_assess/           ← oscal-assess: SBS control assessor
│   ├── sscf_benchmark/         ← sscf-benchmark: SSCF domain scorer
│   └── report-gen/             ← report-gen: DOCX/MD governance output (Phase 4)
│
├── scripts/                    ← Python helper scripts
│   ├── oscal_gap_map.py        ← Maps findings → SSCF controls → backlog
│   ├── oscal_import_sbs.py     ← Imports SBS XML catalog to JSON
│   ├── intake_questionnaire.py ← Intake form CLI
│   └── validate_env.py         ← Pre-flight environment check
│
├── config/
│   ├── oscal-salesforce/       ← Control mappings: SBS → SSCF
│   └── sscf_control_index.yaml ← Canonical SSCF control reference
│
├── contexts/                   ← System prompt context modes (assess/review/research)
├── prompts/                    ← Prompting patterns and examples
├── schemas/                    ← JSON schemas for output validation
├── docs/                       ← Architecture docs, deliverables, generated evidence
├── tests/                      ← pytest smoke tests
└── .github/workflows/          ← CI: ruff, bandit, pip-audit, gitleaks, pytest, CodeQL,
                                    actions-security (zizmor+actionlint), sbom, license-check
```

---

## Pipeline

The full assessment pipeline (all stages are CLI tools):

```
sfdc-connect collect --scope all --out sfdc_raw.json
        ↓
oscal-assess assess --collector-output sfdc_raw.json --out gap_analysis.json
        ↓
python scripts/oscal_gap_map.py --gap-analysis gap_analysis.json --out-json backlog.json
        ↓
sscf-benchmark benchmark --backlog backlog.json --out sscf_report.json
```

**Orchestrated via `agent-loop`** (Phase 3): `gpt-5.3-chat-latest` calls these tools automatically via `tool_use`.

**Dry-run** (no live Salesforce org needed):
```bash
agent-loop run --dry-run --env dev --org my-test-org
```

---

## Running the Full Pipeline (Dry-Run)

No Salesforce org or OpenAI API key needed for the pipeline smoke tests:

```bash
pytest tests/test_pipeline_smoke.py -v
```

For the agentic loop dry-run (needs `OPENAI_API_KEY`):
```bash
# QDRANT_IN_MEMORY=1 is the default — no Docker container needed
agent-loop run --dry-run --env dev --org test-org
```

Expected output: `overall_score ~34%, status: RED` (weak-org stub data).

---

## CI Stack

All checks run on every PR:

| Check | Tool | What fails it |
|---|---|---|
| Lint | `ruff check + format` | Any E/F/I/UP violations, line > 120 chars |
| SAST | `bandit -lll -ii` | HIGH severity findings |
| Dependency CVEs | `pip-audit` | Known CVEs in installed packages |
| License check | `pip-licenses` | GPL/AGPL/LGPL transitive dependencies |
| Secret scan | `gitleaks` | Credentials, tokens, API keys in code |
| Tests | `pytest tests/ -v` | Any test failure |
| Pre-flight | `validate_env.py --ci` | Missing required layout/packages |
| Static analysis | CodeQL | Python security patterns |
| Workflow security | `zizmor` + `actionlint` | Expression injection, bad permissions, syntax errors in workflows |
| SBOM | `cyclonedx-bom` | Generated on push to main — supply chain transparency |
| AI code review | CodeRabbit Pro | PR-level review comments |

**All checks must be green before merging to `main`.**

---

## Security Rules (Non-Negotiable)

1. **Read-only against Salesforce.** No writes to any org under any circumstances.
2. **No credentials in code.** All secrets via `.env` or environment variables only.
3. **Evidence stays in `docs/oscal-salesforce-poc/generated/`** — never `/tmp` or outside the repo.
4. **All findings reference an `assessment_id` and `generated_at_utc` timestamp.**
5. **Critical/fail gate:** `agent-loop` will block output if `status=fail AND severity=critical` unless `--approve-critical` is passed.

---

## Branch / PR Workflow

```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Make changes, run tests
pytest tests/ -v
ruff check skills/ scripts/ harness/

# Commit (conventional commits required)
git commit -m "feat(skill): description

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# Push and open PR
git push -u origin feature/your-feature-name
gh pr create
```

**1 PR review required** before merge. Branch protection is enforced on `main`.

---

## Phase Roadmap

| Phase | Status | Deliverable |
|---|---|---|
| 1 | ✅ Done | `sfdc-connect` CLI + full CI stack |
| 2 | ✅ Done | `oscal-assess` + `sscf-benchmark` CLIs |
| 3 | ✅ Done | `agent-loop` harness + Mem0 session memory |
| 4 | ✅ Done | `report-gen` DOCX/MD governance output pipeline |
| 5 | ✅ Done | Auto-regenerating architecture diagram + PR template |
| 6 | ✅ Done | CI hardening, security-reviewer agent, minimal local reqs |

---

## Getting Help

- Read `mission.md` — agent identity and authorized scope
- Read `AGENTS.md` — full agent roster and routing logic
- Run `<command> --help` on any CLI tool
- Open an issue on GitHub for bugs or questions
