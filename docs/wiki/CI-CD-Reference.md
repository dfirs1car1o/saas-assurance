# CI/CD Reference

Every CI check that runs on pull requests and pushes to `main`, what each one validates, and how to fix failures.

All actions are pinned to full commit SHAs for supply chain security.

---

## CI Jobs

### `ci.yml` — Core Quality Gates

| Job | Tool | Trigger | Fails if |
|---|---|---|---|
| `ruff` | `ruff check + format` | All PRs + push to main | Any E/F/I/UP violation or line > 120 chars |
| `bandit` | `bandit -r -lll -ii` | All PRs + push to main | HIGH severity findings in skills/, scripts/, harness/ |
| `pip-audit` | `pip-audit --desc on` | All PRs + push to main | Any installed package has a known CVE |
| `validate-env` | `validate_env.py --ci` | All PRs + push to main | Missing required repo files or Python packages |
| `license-check` | `pip-licenses` | All PRs + push to main | GPL/AGPL/LGPL dependency detected (not in allowlist) |
| `pytest` | `pytest tests/ -v --cov=... --cov-fail-under=60` | All PRs + push to main | Any test fails or coverage drops below 60% (33 tests total) |
| `docker-smoke` | `docker compose up/down` | All PRs + push to main | OpenSearch or Dashboards fail to reach healthy state |

**Fix `ruff` failures:**
```bash
ruff check skills/ scripts/ harness/ --fix
ruff format skills/ scripts/ harness/
```

**Fix `bandit` failures:**
- B102 (subprocess shell=True): use list form instead of string
- B301/B302 (pickle): don't use pickle on untrusted input
- B506 (yaml.load): use `yaml.safe_load()` instead

**Fix `validate-env` failures:**
```bash
pip install -e .
python3 scripts/validate_env.py --fix
```

**Fix `license-check` failures:**
- If a new GPL/LGPL dep appeared: find the transitive dep and replace it
- If LGPL is acceptable: add to `lgpl_allowlist` in `ci.yml` with review comment

**Current LGPL allowlist:** None — PDF generation was removed; all reports use pandoc (MIT) for DOCX conversion.

---

### `security-checks.yml` — Security Scanning

| Job | Tool | Trigger | Fails if |
|---|---|---|---|
| `Bandit SAST` | `bandit -r -lll -ii` | All PRs + push to main | HIGH severity in skills/, scripts/ |
| `pip-audit` | `pip-audit --desc on` | All PRs + push to main | CVE in any installed package |
| `Secret scan` | `gitleaks detect` | All PRs + push to main | Credential, token, or API key in any commit |

**Fix `gitleaks` failures:**
- Never commit real credentials — use `.env` or CI secrets only
- If a credential was committed: rotate it immediately, then use `git filter-repo` to purge from history (contact repo admin)
- `.env` is in `.gitignore` — never remove it from there

---

### `actions-security.yml` — Workflow Security

| Job | Tool | Trigger | Fails if |
|---|---|---|---|
| `zizmor` | `zizmor .github/workflows/` | All PRs + push to main | HIGH severity: expression injection, overly broad permissions, unpinned 3rd-party actions |
| `actionlint` | `actionlint` | All PRs + push to main | Workflow syntax errors, invalid event types, bad `${{ }}` expressions |

**Fix `zizmor` failures:**

*Expression injection* — if your workflow has:
```yaml
run: echo "${{ github.event.pull_request.title }}"  # DANGEROUS
```
Fix by assigning to env var first:
```yaml
env:
  PR_TITLE: ${{ github.event.pull_request.title }}
run: echo "$PR_TITLE"  # safe — shell variable, not GitHub expression
```

*Unpinned action* — replace `uses: some/action@v2` with the full SHA:
```yaml
uses: some/action@abc123def456...  # v2 — add comment for readability
```

*Overly broad permissions* — scope to minimum needed:
```yaml
permissions:
  contents: read        # only if reading files
  pull-requests: write  # only if posting PR comments
```

**Fix `actionlint` failures:**
- Most failures are syntax issues — read the error line/column carefully
- SC2016 in `run:` blocks: add `# shellcheck disable=SC2016` if Go template syntax is intentional

---

### `codeql.yml` — Static Analysis

| Job | Tool | Trigger | Fails if |
|---|---|---|---|
| `CodeQL Python Analysis` | GitHub CodeQL | All PRs + push to main + weekly | SQL injection, path traversal, command injection patterns |

Scans `skills/` and `scripts/` only (agents/, docs/, config/ are excluded).

**Fix CodeQL failures:** CodeQL findings appear in the Security tab. Most common for this repo:
- `CommandInjection` — subprocess call with string interpolation
- `PathTraversal` — file path from user input without validation

---

### `sbom.yml` — Software Bill of Materials + Vulnerability Scan

| Job | Tool | Trigger | What it does |
|---|---|---|---|
| `Generate CycloneDX SBOM` | `cyclonedx-py` | Push to main only | Generates `docs/sbom.cdx.json` and uploads SBOM as 90-day CI artifact |
| `Grype vulnerability scan` | `grype --fail-on high` | Push to main only | Scans SBOM for CVEs; fails on HIGH or CRITICAL findings |

The SBOM is uploaded as a CI artifact (90-day retention). Grype scan results are uploaded alongside it. No auto-commit to main.

**Fix grype failures:**
- Run `grype sbom:docs/sbom.cdx.json` locally to see the full CVE list
- Update the affected dependency in `pyproject.toml`, then re-run `pip install -e .`
- If the CVE has no fix yet, open a GitHub issue to track it and consider a temporary allowlist in CI

---

### `dependency-review.yml` — PR Dependency Scanning

| Job | Tool | Trigger | Fails if |
|---|---|---|---|
| `Dependency Review` | `actions/dependency-review-action` | PRs touching `pyproject.toml` | New HIGH/CRITICAL CVE in added packages |

Only fires when `pyproject.toml` changes. Uses GitHub's advisory database.

---

### `diagram.yml` — Architecture Diagram

| Job | Trigger | What it does |
|---|---|---|
| `Verify architecture diagram` | Push to main touching skills/, harness/, agents/ | Runs `scripts/gen_diagram.py` and verifies committed `docs/architecture.png` is up-to-date (fails if stale) |

Uses Graphviz (CI-only — not required locally). No auto-commit to main — if the diagram is stale, update `docs/architecture.png` locally and commit it.

---

### `pr-inline-review.yml` — PR Annotations

| Job | Tool | What it does |
|---|---|---|
| `Ruff (inline PR annotations)` | `ruff --output-format=github` | Posts ruff violations as inline PR comments |
| `Bandit SAST (inline PR annotations)` | `bandit -ll -ii -f json` | Posts MEDIUM+ bandit findings as inline warnings |

These are **informational only** — they don't block merging. They appear as annotations on changed lines.

---

## CodeRabbit Pro

This repo uses **CodeRabbit Pro** for AI-powered code review on every PR. CodeRabbit posts:
- Summary of changes
- Potential bugs and security issues
- Code quality suggestions

CodeRabbit runs automatically — no setup required for contributors. Reviews appear as PR comments from the `coderabbitai` bot.

---

## All-Green Checklist Before Merging

```
□ ruff — clean
□ bandit — no HIGH findings
□ pip-audit — no CVEs
□ validate-env — all non-credential checks pass
□ license-check — no unapproved copyleft
□ pytest — 33/33 pass + coverage ≥ 60%
□ docker-smoke — OpenSearch + Dashboards healthy
□ Bandit SAST — no HIGH findings
□ Secret scan (gitleaks) — no credentials found
□ zizmor — no HIGH workflow findings
□ actionlint — no syntax errors
□ CodeQL — no injection/traversal patterns
□ SBOM + grype — no HIGH/CRITICAL CVEs in dependencies
□ Dependency Review — no new HIGH/CRITICAL CVEs (if pyproject.toml changed)
□ CodeRabbit Pro — review addressed
□ 1 PR review — required by branch protection
```
