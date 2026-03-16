# Threat Model — saas-assurance Agentic Pipeline

**Framework:** OWASP Top 10 for Agentic Applications 2026 + OWASP LLM Top 10 2025
**Last reviewed:** 2026-03-12
**Reviewer:** Security Team
**Scope:** The `saas-assurance` agentic assessment pipeline — orchestrator loop, CLI tool dispatchers, Salesforce/Workday collectors, report generation, and CI/CD gates.

---

## System Context

`saas-assurance` is a **read-only security assessment tool**, not a consumer web application. It runs as a CLI on operator machines or in GitHub Actions. The attack surface is therefore different from the JWT/brute-force/WebSocket threats that affect web apps — the relevant threats are:

1. **LLM-output → system execution boundary** (tool arguments from the LLM reaching subprocess calls)
2. **Memory poisoning** (Qdrant-stored assessment history injected into the orchestrator prompt)
3. **Supply chain** (dependencies, GitHub Actions, external XML sources)
4. **CI/CD pipeline integrity** (workflow injection, secrets leakage)
5. **Excessive agency** (LLM calling more tools than intended, bypassing human gates)

---

## Threat Map — OWASP Top 10 for Agentic Applications 2026

### A1 — Prompt Injection

| Attribute | Detail |
|---|---|
| **Threat** | Adversarial content in Salesforce org config (e.g., a field value containing `"ignore previous instructions"`) or in Qdrant-stored memories causes the orchestrator to deviate from its pipeline |
| **Likelihood** | Low — org config is read-only structured JSON; field values don't flow into the system prompt |
| **Impact** | Medium — could cause skipped pipeline stages or unexpected tool calls |
| **Controls** | Memory guard in `harness/loop.py`: strips `ignore previous instructions`, `system:`, `act as`, `override:` patterns before Mem0 content is prepended to user message |
| **Residual risk** | Low — indirect injection via collector output is blocked by structured JSON parsing; org config values are not interpolated into prompts |
| **Status** | ✅ Mitigated |

---

### A2 — Excessive Agency

| Attribute | Detail |
|---|---|
| **Threat** | LLM calls tools out of sequence, calls non-pipeline tools, or exceeds its authorized scope |
| **Likelihood** | Medium — GPT models occasionally hallucinate extra tool calls |
| **Impact** | High — an out-of-order `report_gen_generate` without assessment data produces misleading governance output |
| **Controls** | `_MAX_TURNS = 14` hard stop; `finish()` tool breaks loop cleanly after step 6b; `dispatch()` rejects unknown tool names with `ValueError`; `--approve-critical` flag required for critical gate bypass |
| **Residual risk** | Medium — no enforced tool sequencing (e.g., can't enforce `oscal_assess` before `report_gen` at the harness level without state machine) |
| **Status** | ⚠️ Partially mitigated — sequencing enforced by task prompt, not by code |

---

### A3 — Memory Poisoning

| Attribute | Detail |
|---|---|
| **Threat** | Qdrant stores assessment summaries from prior runs. If a prior run processed adversarial org data, the stored memory could contain injected instructions that reappear in future runs |
| **Likelihood** | Very low — org data is collected via SOQL (structured) and never directly stored in Mem0 |
| **Impact** | Medium — injected instructions in memory could redirect orchestrator behavior |
| **Controls** | Memory guard (`_INJECTION_PATTERNS`) in `harness/loop.py`; Qdrant runs in Docker on localhost only; no external write access |
| **Residual risk** | Low |
| **Status** | ✅ Mitigated |

---

### A4 — Supply Chain Compromise

| Attribute | Detail |
|---|---|
| **Threat** | Compromised Python dependency (pip), GitHub Action, or SBS XML source introduces malicious code |
| **Likelihood** | Low-Medium — third-party dependencies are the primary attack surface for most Python projects |
| **Impact** | Critical — malicious dependency could exfiltrate Salesforce credentials or JWT private keys |
| **Controls** | `pip-audit` (dependency CVEs, hard fail); `grype` SBOM scan; `gitleaks` (secrets in git history); pinned GitHub Actions at full SHA; `dependency-review.yml`; `oscal_import_sbs.py` enforces `https://` on XML URL |
| **Residual risk** | Low |
| **Status** | ✅ Mitigated |

---

### A5 — Unexpected Code Execution (Insecure Output Handling)

| Attribute | Detail |
|---|---|
| **Threat** | LLM-provided tool arguments (org alias, file paths) reach `subprocess.run()` with attacker-controlled values |
| **Likelihood** | Low — requires LLM to produce malicious argument values |
| **Impact** | High — path traversal could read arbitrary files; shell injection could execute arbitrary commands |
| **Controls** | `_sanitize_org()`: rejects any org alias not matching `[a-zA-Z0-9_-]{1,64}`; `_safe_inp_path()`: validates all LLM-provided input file paths within `_ARTIFACT_ROOT`; `_safe_out_path()`: validates all output paths; `subprocess.run(args, shell=False)` — no shell interpretation; Bandit `-lll -ii` (S603/S607 would flag `shell=True`); Semgrep `p/python` + `p/owasp-top-ten` |
| **Residual risk** | Low |
| **Status** | ✅ Mitigated |

---

### A6 — Sensitive Information Disclosure

| Attribute | Detail |
|---|---|
| **Threat** | Salesforce JWT private key, OpenAI API key, or org credentials leaked to stdout, logs, or generated artifacts |
| **Likelihood** | Low — credentials come from env vars and `.env` file, not from tool arguments |
| **Impact** | Critical — org compromise or API key theft |
| **Controls** | `SECURITY.md`: all creds via env vars only; `validate_env.py` skips credential checks in CI; `gitleaks` scans full git history; `--redact` flag on gitleaks output; generated artifacts confined to `docs/oscal-salesforce-poc/generated/` (in `.gitignore` boundary); JWT private key outside repo (`~/salesforce_jwt_private.pem`, chmod 600) |
| **Residual risk** | Low |
| **Status** | ✅ Mitigated |

---

### A7 — Insecure Plugin / Tool Design

| Attribute | Detail |
|---|---|
| **Threat** | Tool dispatch executes CLI subprocesses with LLM-controlled arguments without validation |
| **Likelihood** | Low — mitigated by input validators |
| **Impact** | High |
| **Controls** | All tools dispatch via explicit allowlist (`_DISPATCHERS` dict); unknown tool name raises `ValueError`; all path arguments validated; `shell=False` on all subprocess calls |
| **Residual risk** | Low |
| **Status** | ✅ Mitigated |

---

### A8 — Overreliance / Insufficient Human Oversight

| Attribute | Detail |
|---|---|
| **Threat** | Security Team accepts AI-generated assessment reports without independent verification, especially on critical findings |
| **Likelihood** | Medium — agentic outputs look authoritative |
| **Impact** | High — false-pass assessment leads to unmitigated controls in production |
| **Controls** | Critical/fail gate: `sys.exit(2)` if `critical_fails` found without `--approve-critical`; NIST AI RMF gate: `block`/`flag` verdicts surfaced in report banner; CodeRabbit Pro inline PR review on all changes; structured audit log per run |
| **Residual risk** | Medium — human still must interpret report; gate requires `--approve-critical` bypass to be intentional |
| **Status** | ⚠️ Partially mitigated — human review required by process, not enforced by system |

---

### A9 — Logging & Monitoring Gaps

| Attribute | Detail |
|---|---|
| **Threat** | No forensic record of what the agent did, making incident investigation impossible |
| **Likelihood** | N/A (was a gap; now addressed) |
| **Impact** | High — without audit trail, cannot determine if agent was manipulated |
| **Controls** | Structured JSONL audit log (`audit.jsonl`) written per run: `loop_start`, `tool_call` (tool name, args, status, duration_ms, turn), `loop_end` (score, critical_fails). Path surfaced in `loop_result.json` and CLI banner. |
| **Status** | ✅ Mitigated |

---

### A10 — Unsafe External Integrations

| Attribute | Detail |
|---|---|
| **Threat** | Salesforce/Workday API connections expose the org to data exfiltration or privilege escalation |
| **Likelihood** | Low — read-only scope enforced by design |
| **Impact** | High — unintended writes to production Salesforce org |
| **Controls** | Read-only by design (SOQL SELECT only; no DML); JWT Bearer auth (no password/SOAP); `mission.md`: "No writes without explicit human approval"; Salesforce connected app scoped to read-only permissions; Workday OAuth 2.0 Client Credentials with read-only RaaS/REST scopes |
| **Residual risk** | Low |
| **Status** | ✅ Mitigated |

---

## Summary Table

| Risk | Likelihood | Impact | Status |
|---|---|---|---|
| A1 Prompt Injection | Low | Medium | ✅ Mitigated |
| A2 Excessive Agency | Medium | High | ⚠️ Partial |
| A3 Memory Poisoning | Very Low | Medium | ✅ Mitigated |
| A4 Supply Chain | Low-Med | Critical | ✅ Mitigated |
| A5 Code Execution (LLM args) | Low | High | ✅ Mitigated |
| A6 Credential Disclosure | Low | Critical | ✅ Mitigated |
| A7 Insecure Tool Design | Low | High | ✅ Mitigated |
| A8 Overreliance | Medium | High | ⚠️ Partial |
| A9 Logging Gaps | — | High | ✅ Mitigated |
| A10 Unsafe Integrations | Low | High | ✅ Mitigated |

---

## Open / Residual Risks

| # | Risk | Status | Mitigation Roadmap |
|---|---|---|---|
| R1 | **Tool sequencing not enforced in code** — LLM could call `report_gen` before `oscal_assess` | ✅ Resolved | `_TOOL_REQUIRES` dependency map in `harness/loop.py`; sequencing gate fires before every dispatch; violations return structured error JSON to orchestrator; `dry_run` waives collector prerequisites |
| R2 | **Human review is process-dependent** — `--approve-critical` can be scripted away | ⚠️ Open | Add required named approver field to the critical gate; require human-signed artifact |
| R3 | **Qdrant has no authentication in local dev** — any local process can read/write memories | ✅ Resolved | `QDRANT_API_KEY` env var wired into networked Qdrant config in `harness/memory.py`; documented in `.env.example` |

---

## References

- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- [OWASP LLM Top 10 2025](https://genai.owasp.org/llmrisk/)
- [DryRun Security Agentic Coding Security Report (March 2026)](https://finance.yahoo.com/news/dryrun-security-research-anthropic-claude-120000947.html)
- [NIST AI RMF 1.0](https://airc.nist.gov/RMF/about)
- [CSA AICM v1.0.3](https://cloudsecurityalliance.org/research/topics/ai-controls-matrix)
