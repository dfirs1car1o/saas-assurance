#!/usr/bin/env bash
set -euo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

echo "== Session Bootstrap =="
echo "Repo: $REPO"
echo

echo "[1/6] Git status"
git -C "$REPO" status -sb || true
echo

echo "[2/6] Recent commits"
git -C "$REPO" log --oneline -n 5 || true
echo

echo "[3/6] Remote"
git -C "$REPO" remote -v || true
echo

echo "[4/6] DNS test"
ping -c 1 github.com >/dev/null 2>&1 && echo "github.com DNS: OK" || echo "github.com DNS: FAIL"
echo

echo "[5/6] SSH test (github.com-443 alias)"
ssh -T git@github.com-443 </dev/null 2>&1 | sed -n '1,3p' || true
echo

echo "[6/6] Pending push check"
AHEAD_LINE="$(git -C "$REPO" status -sb | head -n 1 || true)"
echo "$AHEAD_LINE"
echo

echo "== Suggested next commands =="
echo "git -C $REPO push"
echo "# Session notes are in Obsidian vault — saas-assurance/Next Session.md"
