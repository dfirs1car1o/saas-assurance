# Security Model

The security model for this system is defined in `mission.md` and enforced at multiple layers. A full formal threat model is maintained at `docs/security/threat-model.md`.

---

## OWASP Top 10 for Agentic Applications 2026

This pipeline is hardened against all 10 OWASP Agentic Application risks. Status as of March 2026:

| Risk | Status | Control |
|---|---|---|
| A1 — Prompt Injection | ✅ Mitigated | Memory guard strips injection patterns before Qdrant memories reach the orchestrator prompt |
| A2 — Excessive Agency | ✅ Mitigated | `_TOOL_REQUIRES` sequencing gate in `harness/loop.py`; `_MAX_TURNS=14`; `finish()` tool breaks loop; `dispatch()` allowlist |
| A3 — Memory Poisoning | ✅ Mitigated | `_INJECTION_PATTERNS` guard; Qdrant `QDRANT_API_KEY` auth for non-local deployments |
| A4 — Supply Chain | ✅ Mitigated | `pip-audit`, `grype`, `gitleaks`, pinned GitHub Actions at full SHA, `https://` enforced on XML sources |
| A5 — Unexpected Code Execution | ✅ Mitigated | `_sanitize_org()` + `_safe_inp_path()` + `_safe_out_path()`; `shell=False` on all subprocess calls; Bandit + Semgrep in CI |
| A6 — Credential Disclosure | ✅ Mitigated | Credentials via env vars only; `gitleaks` on full git history; artifacts in `.gitignore`d directory |
| A7 — Insecure Tool Design | ✅ Mitigated | `_DISPATCHERS` allowlist; `ValueError` on unknown tool names; all paths validated |
| A8 — Overreliance | ⚠️ Partial | Critical/fail gate (`sys.exit(2)`); NIST AI RMF block verdict; human must interpret report |
| A9 — Logging Gaps | ✅ Mitigated | Structured JSONL audit log (`audit.jsonl`) per run: `loop_start`, `tool_call` (name, args, status, duration_ms, turn), `loop_end` |
| A10 — Unsafe Integrations | ✅ Mitigated | Read-only by design; SOQL SELECT only; JWT Bearer (SFDC) / OAuth 2.0 (Workday); no DML |

---

## Core Rules (Non-Negotiable)

| Rule | Enforcement |
|---|---|
| Read-only against SaaS platforms | Coded in sfdc-connect / workday-connect; no write methods exist |
| No credentials in code or logs | bandit, gitleaks, CodeQL in CI; CodeRabbit review |
| Evidence stays in `docs/oscal-salesforce-poc/generated/` | `_safe_inp_path()` + `_safe_out_path()` validate all LLM-provided paths |
| Org aliases restricted to `[a-zA-Z0-9_-]{1,64}` | `_sanitize_org()` in `harness/tools.py` — called before every dispatch |
| Tool sequencing enforced in code | `_TOOL_REQUIRES` map in `harness/loop.py` checked before every dispatch |
| All findings need `assessment_id` + `generated_at_utc` | Schema validation in orchestrator |
| Critical/fail gate on live runs | `harness/loop.py` — `sys.exit(2)` if critical fails without `--approve-critical` |
| NIST AI RMF validation before output | nist-reviewer agent, final step before report-gen |
| Every tool call logged | `_append_audit()` writes to `audit.jsonl` in try/finally — never aborts the loop |

---

## Quality Gates (Layered)

### Gate 1: Tool Sequencing Gate (`harness/loop.py`)
- **When:** Every tool call in every mode
- **Logic:** `_TOOL_REQUIRES` dependency map checked against `completed_tools` set before dispatch
- **On violation:** Structured error JSON returned to orchestrator; tool dispatch skipped; event logged to `audit.jsonl` with `status: sequencing_violation`
- **dry_run waiver:** Collector prerequisites (sfdc/workday_connect_collect) are waived when `dry_run=True`

### Gate 2: Critical/fail gate (`harness/loop.py`)
- **When:** Live runs only (not dry-run)
- **Bypass:** `--approve-critical` flag
- **Blocks:** Loop exit if `status=fail AND severity=critical`

### Gate 3: Orchestrator prompt gate (`agents/orchestrator.md`)
- **When:** All modes including dry-run
- **Bypass:** Task prompt includes dry-run bypass note
- **Blocks:** Output delivery if nist-reviewer gap, schema violation, or security-reviewer CRITICAL/HIGH

### Gate 4: CI/CD gates (`.github/workflows/`)
- **When:** Every PR and push to main
- **Bypass:** Admin merge only
- **Blocks:** Merge if bandit HIGH, CVE, GPL dep, gitleaks hit, zizmor HIGH, actionlint error, pytest failure, Semgrep ERROR

---

## Input Validation (LLM → Subprocess Boundary)

All LLM-provided arguments are validated before reaching any subprocess call:

| Validator | Where | What it rejects |
|---|---|---|
| `_sanitize_org(org)` | `harness/tools.py` → called in `dispatch()` | Any org alias not matching `[a-zA-Z0-9_-]{1,64}` — blocks path traversal via `../../etc` |
| `_safe_inp_path(raw)` | `harness/tools.py` → all dispatchers | Input file paths outside `docs/oscal-salesforce-poc/generated/` — blocks `/etc/shadow`, `/tmp/`, `../` escapes |
| `_safe_out_path(raw, default)` | `harness/tools.py` → all dispatchers | Output paths outside artifact root — falls back to default on `None` |
| `shell=False` | All `subprocess.run()` calls | Shell interpretation of arguments — no shell injection possible |

---

## Memory Guard (Prompt Injection via Qdrant)

Before Mem0-loaded assessment memories are injected into the orchestrator's user message:

```python
_INJECTION_PATTERNS = [
    "ignore previous instructions", "ignore all previous",
    "disregard previous", "system:", "you are now",
    "act as", "new instructions:", "override:",
]
if memory_context:
    if any(pat in memory_context.lower() for pat in _INJECTION_PATTERNS):
        click.echo("WARNING: possible injection pattern in stored memories — skipping.", err=True)
        memory_context = ""
```

If a prior adversarial assessment run poisoned the Qdrant store, this gate prevents the stored content from overriding orchestrator instructions.

---

## Structured Audit Log

Every run writes `docs/oscal-salesforce-poc/generated/<org>/<date>/audit.jsonl`:

```jsonl
{"event": "loop_start", "ts": "...", "org": "my-org", "env": "dev", "platform": "salesforce", "dry_run": false}
{"event": "tool_call", "ts": "...", "turn": 1, "tool": "sfdc_connect_collect", "args": {...}, "status": "ok", "duration_ms": 2341}
{"event": "tool_call", "ts": "...", "turn": 2, "tool": "oscal_assess_assess", "args": {...}, "status": "ok", "duration_ms": 891}
{"event": "loop_end", "ts": "...", "turns": 7, "overall_score": 0.44, "critical_fails": ["SBS-AUTH-001"]}
```

`status` values: `ok`, `error`, `sequencing_violation`. The audit path is surfaced in `loop_result.json` and the CLI banner.

---

## Sensitive Data Handling

| Data type | Where it lives | What to never do |
|---|---|---|
| Salesforce credentials | `.env` (gitignored) | Put in code, commit, log |
| OPENAI_API_KEY | `.env` (gitignored) | Put in code, commit, log to stdout |
| WD_CLIENT_SECRET | `.env` (gitignored) | Put in code, commit, log |
| QDRANT_API_KEY | `.env` (gitignored) | Put in code, commit, log |
| Salesforce config data | `docs/oscal-salesforce-poc/generated/<org>/` | Write to `/tmp`, commit, put in /tmp |
| Assessment findings | `docs/oscal-salesforce-poc/generated/<org>/` | Write to external systems without approval |

The `gitleaks` CI job scans full commit history on every PR. If a credential is ever committed, rotate it immediately.

---

## Escalation Paths

| Finding | Who is notified | Blocks what |
|---|---|---|
| Sequencing violation | Orchestrator (structured error JSON) | That tool call's dispatch |
| `critical/fail` Salesforce/Workday control | Human (via loop exit + message) | Live assessment output |
| NIST AI RMF `block` verdict | Human (via orchestrator gate) | All assessment output |
| security-reviewer CRITICAL | Human (via orchestrator gate) | CI merge |
| security-reviewer HIGH | Human (via orchestrator gate) | CI merge |
| gitleaks credential detection | CI failure → PR author | Merge to main |
| bandit HIGH finding | CI failure → PR author | Merge to main |
| Semgrep ERROR finding | CI failure → PR author | Merge to main |
| CVE in dependency | CI failure → PR author | Merge to main |

---

## What the Security Reviewer Checks

The `security-reviewer` agent reviews workflow files, Python CLIs, and agent definitions:

**Workflow files:**
- Expression injection (`${{ github.event.*.body }}` in `run:` blocks)
- Overly broad permissions
- Third-party actions not pinned to SHA
- `pull_request_target` + fork checkout (critical injection vector)
- Secret interpolation in `run:` steps

**Python CLI tools and harness:**
- `subprocess.run(..., shell=True)` with any non-static input (HIGH)
- HTTP calls without `timeout=` (MEDIUM)
- Path traversal from CLI args (now enforced by `_safe_inp_path` / `_sanitize_org`)
- SOQL injection (user input in queries)
- Credential logging in exception handlers
- `sys.exit()` outside CLI entrypoints
- Unvalidated tool_use input passed to subprocess

**Always-flag anti-patterns:**
`shell=True` with variable input / `eval()` / `exec()` / `pickle.loads()` on untrusted input / `yaml.load()` without SafeLoader / `os.system()` with variables / credentials in committed files / `verify=False` on TLS

---

## Audit Trail

Every assessment produces:

| Field | Purpose |
|---|---|
| `audit.jsonl` | Structured JSONL audit log: every tool call with tool name, args, status, duration_ms, turn number |
| `assessment_id` | Unique ID for this run (format: `sfdc-assess-<org>-<env>-loop`) |
| `generated_at_utc` | ISO 8601 timestamp of when findings were generated |
| `evidence_ref` | URI pointing to the collector snapshot |
| `loop_result.json` | Full metadata: org, env, dry_run, turns, score, critical_fails, all output paths including audit_log |

The `schemas/baseline_assessment_schema.json` enforces required fields on all output.

---

## Security Test Coverage

Full offline test suite (no API keys needed):

| Test class | What it covers |
|---|---|
| `TestSafeInpPath` | None passthrough, valid artifact paths, `/etc/shadow` traversal, `/tmp/` traversal, relative `../` escapes |
| `TestSanitizeOrg` | Valid aliases, `../../etc`, null bytes, spaces, shell injection (`; rm -rf`), >64-char aliases |
| `TestDispatchOrgValidation` | End-to-end traversal rejected at dispatch boundary, valid org dispatches correctly |
| `test_audit_log_written_with_correct_events` | JSONL audit trail: `loop_start → tool_call → loop_end`, `duration_ms` present, tool name correct |
| `test_sequencing_gate_blocks_report_gen_without_prerequisites` | `report_gen_generate` dispatch blocked when `oscal_gap_map` + `sscf_benchmark_benchmark` have not completed |

Full threat model: [`docs/security/threat-model.md`](../security/threat-model.md)
