# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main` (latest) | ✅ Active |
| `< v0.3.0` | ❌ End-of-life |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues privately via one of the following:

- **GitHub private vulnerability reporting** (preferred): Use the [Security → Report a vulnerability](../../security/advisories/new) button on the GitHub repo.
- **Email**: Contact the maintainer directly at the email shown in the repository's GitHub profile.

### What to include

Please provide as much of the following as possible to help triage the report quickly:

1. **Description** — what the vulnerability is and its potential impact
2. **Affected component** — which file, skill, agent, or API endpoint
3. **Steps to reproduce** — minimal reproduction steps or a PoC (proof-of-concept)
4. **Suggested severity** — Critical / High / Moderate / Low
5. **Environment** — Python version, OS, Docker version if applicable

### Response timeline

| Milestone | Target |
|-----------|--------|
| Initial acknowledgement | 3 business days |
| Severity triage | 7 business days |
| Fix / mitigation | Dependent on severity (critical: ASAP, high: 30 days, moderate/low: 90 days) |
| Public disclosure | After fix is released and downstream users have had reasonable time to update |

## Security Architecture

This project is an **autonomous multi-agent AI system** connecting read-only to SaaS orgs. Key design decisions:

- **Read-only enforcement** — all SaaS connectors use read-only OAuth scopes or JWT Bearer flow; no write operations without explicit human approval (`--approve-critical`).
- **No credential logging** — credentials, tokens, org IDs, and private keys are never written to stdout, audit logs, or generated outputs.
- **Path validation** — all LLM-supplied file paths are validated through `_safe_inp_path()` before use; org aliases are validated against `^[a-zA-Z0-9_-]{1,64}$`.
- **Subprocess safety** — all CLI tools are invoked via `subprocess.run(..., shell=False)` to prevent shell injection.
- **Audit trail** — every tool call is appended to `.saas-assurance/audit/<org>/<date>/audit.jsonl` (gitignored, local only).
- **Threat model** — see [`docs/security/threat-model.md`](docs/security/threat-model.md) for the full OWASP Agentic Applications Top 10 threat model.

## Scope

| In scope | Out of scope |
|----------|--------------|
| Prompt injection / agent hijacking | Physical security |
| Credential exposure in outputs | Vendor (Salesforce / Workday) vulnerabilities |
| Path traversal via LLM-supplied paths | Third-party MCP server internals |
| Dependency vulnerabilities (CVEs) | Issues with your local `.env` configuration |
| Docker / container escape | Social engineering |

## Dependency Security

Dependencies are scanned automatically on every push and weekly via:

- **`pip-audit`** — PyPI CVE scanning
- **`grype`** — container SBOM vulnerability scanning
- **`Dependabot`** — automated dependency update PRs
- **`CodeQL`** — static analysis for common vulnerability classes

See [`.github/workflows/security-checks.yml`](.github/workflows/security-checks.yml) for the full CI security pipeline.
