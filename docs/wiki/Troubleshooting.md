# Troubleshooting

Common errors and their fixes.

---

## `agent-loop: command not found`

```bash
pip install -e .
```
Then verify: `which agent-loop`

---

## `OPENAI_API_KEY not set` or `AuthenticationError`

1. Check `.env` has `OPENAI_API_KEY=sk-...`
2. Verify `load_dotenv` is being called: `harness/loop.py` calls `load_dotenv(_REPO / ".env")` at import time
3. Check the key starts with `sk-` — OpenAI API keys use this prefix
4. Check the key hasn't expired or been revoked at [platform.openai.com](https://platform.openai.com) → API Keys

---

## `Salesforce login failed` / `SalesforceAuthenticationFailed`

**For JWT auth (current supported method):**
1. Check `SF_AUTH_METHOD=jwt`, `SF_CONSUMER_KEY`, and `SF_PRIVATE_KEY_PATH` are all set
2. Verify the private key file exists and is readable: `ls -la $SF_PRIVATE_KEY_PATH`
3. Verify the Connected App in Salesforce has "Use digital signatures" enabled and your certificate uploaded
4. Developer Edition orgs: use `SF_DOMAIN=login` (not `test`)
5. Try authenticating manually: `sfdc-connect auth --dry-run`

---

## Session memory / Qdrant errors

```
[memory] unavailable: Connection refused
```

**Fix:** Add `QDRANT_IN_MEMORY=1` to `.env`. This uses an in-process Qdrant store — no Docker container needed.

```bash
echo "QDRANT_IN_MEMORY=1" >> .env
```

If you want persistent cross-session memory instead:
```bash
docker run -d -p 6333:6333 qdrant/qdrant
# Then in .env:
QDRANT_IN_MEMORY=0
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

---

## `ModuleNotFoundError: No module named 'skills'`

```bash
pip install -e .
```
The `skills` package requires editable install (`-e`) to be importable.

---

## Output files land in `generated/unknown-org/`

Cause: the `org` parameter wasn't passed to every tool call.

Fix: Use `agent-loop run --org <name>` — the task prompt now includes:
```
IMPORTANT: Pass org='<org>' to every tool call so all outputs land in the same directory.
```

If you're calling CLIs directly, add `--org my-org` to each command.

---

## `Reached max turns (12)` warning

The pipeline ran 12 turns without completing. Most common cause: the orchestrator made extra diagnostic tool calls after finishing the pipeline.

Fixes:
- Re-run — the LLM usually completes within budget on retry
- Check that the task prompt ends with "After step 6b, STOP calling tools immediately" (see `harness/loop.py`)
- If consistently hitting the limit, check `_MAX_TURNS` in `harness/loop.py` and bump to 14

---

## pytest failures

```
ImportError: cannot import name 'cli' from 'harness.loop'
```

Fix:
```bash
pip install -e . && pip install pytest pytest-mock PyYAML click
```

Note: `[tool.uv]` dev-dependencies in `pyproject.toml` are not installed by plain `pip install`. You must install test dependencies explicitly.

---

## CI: `validate_env` fails on credential checks

This is expected in CI — the environment check job intentionally skips credential checks:
```python
cred_skip = {"SF_USERNAME", "SF_CONSUMER_KEY", "SF_PRIVATE_KEY_PATH", "OPENAI_API_KEY", ...}
```

If non-credential checks fail (e.g., `repo-layout`, `sfdc-connect-module`), run:
```bash
pip install -e .
python3 scripts/validate_env.py --fix
```

---

## CI: `zizmor` flags an unpinned action I just added

Replace the tag reference with a full commit SHA:
```bash
# Find the SHA for a specific tag
gh api repos/<owner>/<repo>/commits/<tag> --jq '.sha'
```

Then update your workflow:
```yaml
uses: owner/action@<full-sha>  # vX.Y.Z
```

---

## CI: `actionlint` fails with SC2016

If you have Go template syntax (`{{$var}}`) in a `run:` block and shellcheck flags it:
```yaml
- name: My step
  run: |
    # shellcheck disable=SC2016
    actionlint -format '{{range $err := .}}...{{end}}'
```

---

## CI: `pip-licenses` flags a new LGPL dependency

1. Check if it's a transitive dep: `pip show <package>`
2. If it's a direct dep you added: either replace it with a non-copyleft alternative, or add to the `lgpl_allowlist` in `ci.yml` with a review comment explaining why it's acceptable

---

## Getting Help

- Run `<command> --help` on any CLI tool
- Read `mission.md` — agent identity and scope constraints
- Read `AGENTS.md` — full routing logic
- Open a GitHub issue for bugs
