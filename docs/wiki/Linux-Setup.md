# Linux Setup — Ubuntu / Debian / RHEL

This guide covers setup on Ubuntu 22.04+, Debian 12+, and RHEL/CentOS 8+ (including WSL2 on Windows).

---

## What You Need

| Tool | Required | Notes |
|---|---|---|
| Python 3.11+ | ✅ | Usually available via system package manager |
| Git | ✅ | Usually pre-installed |
| pandoc | ✅ for DOCX | `apt install pandoc` / `dnf install pandoc` |
| Docker | ❌ Not needed | `QDRANT_IN_MEMORY=1` replaces it |

---

## Step 1 — Install System Dependencies

**Ubuntu / Debian / WSL2:**
```bash
sudo apt update && sudo apt install -y \
    python3.11 python3.11-venv python3.11-dev \
    python3-pip git pandoc curl
```

**RHEL / CentOS 8+ / Fedora:**
```bash
sudo dnf install -y python3.11 python3.11-devel git pandoc curl
```

Verify:
```bash
python3.11 --version   # Python 3.11.x (or 3.12/3.13)
git --version
pandoc --version
```

> **Python version note:** The repo requires Python 3.11+. If your distro ships an older version, install from [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa) (Ubuntu) or compile from source.

---

## Step 2 — Clone the Repo

```bash
git clone git@github.com:dfirs1car1o/saas-posture.git saas-assurance
cd saas-assurance
```

Or use HTTPS:
```bash
git clone https://github.com/dfirs1car1o/saas-posture.git saas-assurance
cd saas-assurance
```

---

## Step 3 — Create and Activate a Virtual Environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Verify you're in the venv:
```bash
which python3   # should show /path/to/saas-assurance/.venv/bin/python3
```

To auto-activate when entering the directory, add to `~/.bashrc` or `~/.zshrc`:
```bash
function cd() { builtin cd "$@" && [[ -f .venv/bin/activate ]] && source .venv/bin/activate; }
```

---

## Step 4 — Install Dependencies

```bash
pip install -e ".[dev]"
```

Verify:
```bash
agent-loop --help
sfdc-connect --help
nist-review --help
report-gen --help
```

---

## Step 5 — Configure `.env`

```bash
cp .env.example .env
nano .env   # or: vim .env / code .env
```

Fill in your values:

```bash
# ── OpenAI (required for agent-loop) ─────────────────────────
OPENAI_API_KEY=sk-...

# ── Salesforce auth — JWT (preferred) ────────────────────────
SF_AUTH_METHOD=jwt
SF_USERNAME=your.name@yourcompany.com
SF_CONSUMER_KEY=3MVG9...
SF_PRIVATE_KEY_PATH=/home/yourname/salesforce_jwt_private.pem
SF_DOMAIN=login          # "login" for production, "test" for sandbox

# ── Session memory (no Docker needed) ─────────────────────────
QDRANT_IN_MEMORY=1
MEMORY_ENABLED=0
```

> **JWT key permissions:** `chmod 600 ~/salesforce_jwt_private.pem`

---

## Step 6 — Validate Your Environment

```bash
python3 scripts/validate_env.py
```

Expected:
```
  PASS  [python] Python 3.11.x
  PASS  [.env] .env file exists
  PASS  [OPENAI_API_KEY] OpenAI API key — set (sk-****)
  PASS  [qdrant] QDRANT_IN_MEMORY=1 — in-process Qdrant

  ENVIRONMENT READY.
```

---

## Step 7 — Run the Tests

```bash
pytest tests/ -v
```

Expected: **all tests pass** (no API keys or Salesforce org needed).

---

## Step 8 — Your First Dry Run

```bash
agent-loop run --dry-run --env dev --org test-org
```

You'll see a live progress log, then a results banner:

```
============================================================
Assessment complete (7 turn(s))
overall_score : 34.8%  🔴 RED
critical_fails: 0
============================================================

────────────────────────────────────────────────────────────
📁  RESULTS
────────────────────────────────────────────────────────────
  Gap analysis  →  /home/yourname/saas-assurance/docs/oscal-salesforce-poc/generated/test-org/gap_analysis.json
  Backlog       →  /home/yourname/saas-assurance/docs/oscal-salesforce-poc/generated/test-org/backlog.json
  SSCF report   →  /home/yourname/saas-assurance/docs/oscal-salesforce-poc/generated/test-org/sscf_report.json
  App owner MD  →  .../test-org_remediation_report.md
  Security MD   →  .../test-org_security_assessment.md
  Security DOCX →  .../test-org_security_assessment.docx
────────────────────────────────────────────────────────────
```

---

## Step 9 — Live Assessment

```bash
agent-loop run --env dev --org your-org-name --approve-critical
```

---

## WSL2 (Windows Subsystem for Linux) Notes

WSL2 runs the full Linux pipeline natively. A few extras:

**Access generated files from Windows Explorer:**
```bash
# Open the output directory in Windows Explorer
explorer.exe "$(wslpath -w docs/oscal-salesforce-poc/generated/)"
```

**Open DOCX in Word from WSL2:**
```bash
# PowerShell-style open from WSL:
cmd.exe /c start "$(wslpath -w docs/.../your-org_security_assessment.docx)"
```

**Forward ports if running Qdrant in Docker:**
```bash
# In WSL2, localhost:6333 maps to the WSL2 IP automatically
docker run -d -p 6333:6333 qdrant/qdrant
# Then set QDRANT_IN_MEMORY=0 QDRANT_HOST=localhost in .env
```

---

## CI/Server (Headless) Mode

For headless environments (CI, remote servers), skip the venv auto-activate step and use explicit paths:

```bash
# Example CI install
python3.11 -m venv /opt/saas-assurance/.venv
/opt/saas-assurance/.venv/bin/pip install -e ".[dev]"
/opt/saas-assurance/.venv/bin/agent-loop run --org my-org --env prod --approve-critical
```

For CI environments where you don't want LLM API calls, use mock mode:
```bash
/opt/saas-assurance/.venv/bin/pytest tests/ -v   # fully offline
```

---

## Troubleshooting on Linux

### `python3.11: command not found`

**Ubuntu (deadsnakes PPA):**
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update && sudo apt install -y python3.11 python3.11-venv
```

**Compile from source (RHEL/other):**
```bash
wget https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz
tar xf Python-3.11.9.tgz && cd Python-3.11.9
./configure --enable-optimizations && make -j$(nproc) && sudo make altinstall
```

### `agent-loop: command not found`

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

Or use directly without activation:
```bash
.venv/bin/agent-loop run --dry-run --env dev --org test-org
```

### `pandoc: command not found`

```bash
# Ubuntu/Debian
sudo apt install pandoc

# RHEL/Fedora
sudo dnf install pandoc

# Or download binary directly (for older distros)
wget https://github.com/jgm/pandoc/releases/latest/download/pandoc-3.x-linux-amd64.tar.gz
```

### Permission denied on private key

```bash
chmod 600 /path/to/salesforce_jwt_private.pem
ls -la /path/to/salesforce_jwt_private.pem  # should show -rw-------
```

### `ModuleNotFoundError: No module named 'skills'`

```bash
pip install -e ".[dev]"   # editable install with dev deps required
```

### Qdrant / memory errors

```bash
echo "QDRANT_IN_MEMORY=1" >> .env
echo "MEMORY_ENABLED=0" >> .env
```
