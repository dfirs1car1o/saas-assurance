"""
Security gate tests for harness.tools input validation.

Covers the LLM-input trust boundary:
  _safe_inp_path() — rejects traversal on input file paths
  _sanitize_org()  — rejects malformed org aliases that could escape into paths
  dispatch()       — end-to-end rejection before any subprocess is spawned
"""

from __future__ import annotations

import pytest

from harness.tools import _ARTIFACT_ROOT, _safe_inp_path, _sanitize_org, dispatch

# ---------------------------------------------------------------------------
# _safe_inp_path
# ---------------------------------------------------------------------------


class TestSafeInpPath:
    def test_none_returns_none(self) -> None:
        assert _safe_inp_path(None) is None

    def test_valid_artifact_path_accepted(self) -> None:
        valid = str(_ARTIFACT_ROOT / "my-org" / "2026-03-12" / "gap_analysis.json")
        assert _safe_inp_path(valid) == valid

    def test_path_traversal_rejected(self) -> None:
        traversal = str(_ARTIFACT_ROOT / "my-org" / ".." / ".." / ".." / "etc" / "passwd")
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            _safe_inp_path(traversal)

    def test_absolute_path_outside_repo_rejected(self) -> None:
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            _safe_inp_path("/etc/shadow")

    def test_tmp_path_rejected(self) -> None:
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            _safe_inp_path("/tmp/evil_backlog.json")

    def test_relative_escape_rejected(self) -> None:
        import os

        escape = os.path.join(str(_ARTIFACT_ROOT), "..", "..", "..", "harness", "tools.py")
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            _safe_inp_path(escape)


# ---------------------------------------------------------------------------
# _sanitize_org
# ---------------------------------------------------------------------------


class TestSanitizeOrg:
    def test_valid_simple(self) -> None:
        assert _sanitize_org("my-org") == "my-org"

    def test_valid_with_underscores(self) -> None:
        assert _sanitize_org("cyber_coach_dev") == "cyber_coach_dev"

    def test_valid_alphanumeric(self) -> None:
        assert _sanitize_org("org123") == "org123"

    def test_path_traversal_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid org alias"):
            _sanitize_org("../../tmp/evil")

    def test_slash_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid org alias"):
            _sanitize_org("org/subdir")

    def test_null_byte_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid org alias"):
            _sanitize_org("org\x00evil")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid org alias"):
            _sanitize_org("")

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid org alias"):
            _sanitize_org("a" * 65)

    def test_spaces_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid org alias"):
            _sanitize_org("my org")

    def test_shell_injection_attempt_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid org alias"):
            _sanitize_org("org; rm -rf /")


# ---------------------------------------------------------------------------
# dispatch() — end-to-end rejection at the entry point
# ---------------------------------------------------------------------------


class TestDispatchOrgValidation:
    def test_traversal_org_rejected_before_subprocess(self) -> None:
        """A malicious org alias from the LLM must be caught at dispatch(),
        before any subprocess or directory creation occurs."""
        with pytest.raises(ValueError, match="Invalid org alias"):
            dispatch("finish", {"org": "../../evil", "summary": "test"})

    def test_valid_org_dispatches_finish(self) -> None:
        """finish() tool should succeed with a valid org alias."""
        result = dispatch("finish", {"org": "test-org", "summary": "done"})
        import json

        data = json.loads(result)
        assert data["pipeline_complete"] is True
