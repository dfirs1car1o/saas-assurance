# macOS Setup — Apple Silicon & Intel

This guide covers setup on macOS 13+ (Ventura and later), both Apple Silicon (M1/M2/M3/M4) and Intel.

---

## What You Need

| Tool | Required | Install method |
|---|---|---|
| Python 3.11+ | ✅ | Homebrew (recommended) or python.org |
| Git | ✅ | Already on macOS via Xcode CLT |
| pandoc | ✅ for DOCX | `brew install pandoc` |
| Homebrew | Recommended | [brew.sh](https://brew.sh) |
| Docker | ❌ Not needed | `QDRANT_IN_MEMORY=1` replaces it |

---

## Step 1 — Install Homebrew (if not already installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**Apple Silicon only:** After install, add Homebrew to your shell profile:
```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc
source ~/.zshrc
```

Verify:
```bash
brew --version
```

---

## Step 2 — Install Python 3.11+ and pandoc

```bash
brew install python@3.13 pandoc
```

Verify:
```bash
python3 --version   # Python 3.13.x
pandoc --version    # pandoc 3.x
```

> **Note:** Homebrew installs Python as `python3` (not `python`). All commands in this repo use `python3`.

---

## Step 3 — Clone the Repo

```bash
git clone git@github.com:dfirs1car1o/saas-posture.git saas-assurance
cd saas-assurance
```

Or use HTTPS if you haven't set up SSH keys:
```bash
git clone https://github.com/dfirs1car1o/saas-posture.git saas-assurance
cd saas-assurance
```

---

## Step 4 — Create and Activate a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Add to your shell profile to auto-activate when entering the directory (optional):
```bash
# In ~/.zshrc — add this function:
function cd() { builtin cd "$@" && [[ -f .venv/bin/activate ]] && source .venv/bin/activate; }
```

---

## Step 5 — Install Dependencies

```bash
pip install -e ".[dev]"
```

Verify all CLIs are installed:
```bash
agent-loop --help
sfdc-connect --help
oscal-assess --help
nist-review --help
report-gen --help
```

---

## Step 6 — Configure `.env`

```bash
cp .env.example .env
open -e .env   # opens in TextEdit; or use your editor of choice
```

Fill in your values:

```bash
# ── OpenAI (required for agent-loop) ─────────────────────────
OPENAI_API_KEY=sk-...

# ── Salesforce auth — JWT (preferred) ────────────────────────
SF_AUTH_METHOD=jwt
SF_USERNAME=your.name@yourcompany.com
SF_CONSUMER_KEY=3MVG9...
SF_PRIVATE_KEY_PATH=/Users/yourname/salesforce_jwt_private.pem
SF_DOMAIN=login          # "login" for production, "test" for sandbox

# ── Session memory (no Docker needed) ─────────────────────────
QDRANT_IN_MEMORY=1
MEMORY_ENABLED=0
```

> **JWT key setup:** Generate a key pair, upload the certificate to your Salesforce Connected App, and store the private key outside the repo (e.g., `~/salesforce_jwt_private.pem`). Set permissions: `chmod 600 ~/salesforce_jwt_private.pem`.

---

## Step 7 — Validate Your Environment

```bash
python3 scripts/validate_env.py
```

Expected:
```
  PASS  [python] Python 3.13.x
  PASS  [.env] .env file exists
  PASS  [OPENAI_API_KEY] OpenAI API key — set (sk-****)
  PASS  [qdrant] QDRANT_IN_MEMORY=1 — in-process Qdrant

  ENVIRONMENT READY.
```

---

## Step 8 — Run the Tests

```bash
pytest tests/ -v
```

Expected: **all tests pass** (no API keys or Salesforce org needed).

---

## Step 9 — Your First Dry Run

```bash
agent-loop run --dry-run --env dev --org test-org
```

You'll see a live progress log, then a results banner like:

```
============================================================
Assessment complete (7 turn(s))
overall_score : 34.8%  🔴 RED
critical_fails: 0
============================================================

────────────────────────────────────────────────────────────
📁  RESULTS
────────────────────────────────────────────────────────────
  Gap analysis  →  .../generated/test-org/<date>/gap_analysis.json
  Backlog       →  .../generated/test-org/<date>/backlog.json
  SSCF report   →  .../generated/test-org/<date>/sscf_report.json
  NIST review   →  .../generated/test-org/<date>/nist_review.json
  AICM coverage →  .../generated/test-org/<date>/aicm_coverage.json
  App owner MD  →  .../generated/test-org/<date>/test-org_remediation_report.md
  Security MD   →  .../generated/test-org/<date>/test-org_security_assessment.md
  Security DOCX →  .../generated/test-org/<date>/test-org_security_assessment.docx
────────────────────────────────────────────────────────────
```

---

## Step 10 — Live Assessment

```bash
agent-loop run --env dev --org your-org-name --approve-critical
```

Open the DOCX in Word or Preview:
```bash
open docs/oscal-salesforce-poc/generated/your-org-name/*/your-org-name_security_assessment.docx
```

---

## Recommended Editor Setup (VS Code)

```bash
brew install --cask visual-studio-code
code .
```

Install extensions:
- **Python** (Microsoft)
- **Pylance** (Microsoft)
- **Markdown Preview Enhanced** (Yiyi Wang)
- **GitLens** (GitKraken)

---

## Troubleshooting on macOS

### `python3: command not found`
```bash
brew install python@3.13
```

### `agent-loop: command not found`
Activate your venv first:
```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

### `pandoc: command not found`
```bash
brew install pandoc
```
DOCX reports will not be generated without pandoc.

### `SSL: CERTIFICATE_VERIFY_FAILED` on macOS
Run the Python certificate installer:
```bash
open /Applications/Python\ 3.13/Install\ Certificates.command
```

### JWT private key errors
```bash
chmod 600 ~/salesforce_jwt_private.pem
# Verify it loads correctly:
python3 -c "from cryptography.hazmat.primitives.serialization import load_pem_private_key; load_pem_private_key(open('$SF_PRIVATE_KEY_PATH','rb').read(), None); print('key OK')"
```
