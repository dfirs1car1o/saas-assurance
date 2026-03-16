#!/usr/bin/env bash
# setup.sh — Onboarding script for saas-assurance
# Run once after cloning. Requires Python 3.11+ and uv.
set -euo pipefail

echo "==> saas-assurance setup"

# 1. Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
required="3.11"
if ! python3 -c "import sys; assert sys.version_info >= (3,11)" 2>/dev/null; then
  echo "ERROR: Python 3.11+ required (found $python_version). Install via pyenv or homebrew."
  exit 1
fi
echo "    Python $python_version OK"

# 2. Install uv if missing
if ! command -v uv &>/dev/null; then
  echo "==> Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.cargo/bin:$PATH"
fi
echo "    uv $(uv --version) OK"

# 3. Create venv and install deps
echo "==> Installing Python dependencies..."
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]" 2>/dev/null || uv pip install -e .

# 4. Copy .env.example if .env doesn't exist
if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Created .env from .env.example"
  echo "    ACTION REQUIRED: fill in SF_USERNAME, SF_CONSUMER_KEY, SF_PRIVATE_KEY_PATH in .env"
else
  echo "    .env already exists — skipping"
fi

# 5. Ensure QDRANT_IN_MEMORY is set in .env (no Docker container needed by default)
if ! grep -q "^QDRANT_IN_MEMORY=" .env; then
  echo "" >> .env
  echo "# Qdrant in-memory mode (no Docker needed for local dev)" >> .env
  echo "QDRANT_IN_MEMORY=1" >> .env
  echo "==> Added QDRANT_IN_MEMORY=1 to .env (use Docker container only if you need persistent cross-session memory)"
fi

# 5. Verify CLI is callable
echo "==> Verifying sfdc-connect CLI..."
python3 -m skills.sfdc_connect.sfdc_connect --help > /dev/null 2>&1 && echo "    sfdc-connect OK" || echo "    WARNING: sfdc-connect --help failed (expected until deps installed)"

echo ""
echo "Setup complete. Next steps:"
echo "  1. Edit .env with your Salesforce credentials"
echo "  2. Run: source .venv/bin/activate"
echo "  3. Test: python3 -m skills.sfdc_connect.sfdc_connect auth --dry-run"
echo ""
echo "Optional:"
echo "  Docker Desktop — NOT required. Session memory works in-process via QDRANT_IN_MEMORY=1."
echo "  Node.js        — NOT required. Hooks are shell scripts only."
echo "  Claude Code    — Recommended for interactive dev (npm install -g @anthropic-ai/claude-code). (requires Node.js)"
echo "  uv             — Faster installs. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
