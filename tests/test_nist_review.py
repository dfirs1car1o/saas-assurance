"""
Tests for skills.nist_review — NIST AI RMF review skill.

Covers:
- _load_json helper (happy path and error cases)
- _build_review_context summarizer
- assess CLI dry-run (salesforce + workday platforms)
- assess CLI error paths (missing args, missing file)
- parse-error fallback verdict path (live mode stub)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from skills.nist_review.nist_review import (
    _DRY_RUN_VERDICTS,
    _build_review_context,
    _load_json,
    cli,
)

# ---------------------------------------------------------------------------
# _load_json
# ---------------------------------------------------------------------------


class TestLoadJson:
    def test_returns_dict_for_valid_file(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        result = _load_json(f)
        assert result == {"key": "value"}

    def test_exits_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            _load_json(tmp_path / "nonexistent.json")

    def test_exits_on_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{not valid json}")
        with pytest.raises(SystemExit):
            _load_json(f)


# ---------------------------------------------------------------------------
# _build_review_context
# ---------------------------------------------------------------------------


class TestBuildReviewContext:
    def _gap_data(self) -> dict:
        return {
            "assessment_id": "test-001",
            "findings": [
                {"status": "fail", "severity": "critical", "control_id": "AUTH-001"},
                {"status": "fail", "severity": "high", "control_id": "AUTH-002"},
                {"status": "pass", "severity": "low", "control_id": "LOG-001"},
                {"status": "not_applicable", "severity": "low", "control_id": "SOAP-001"},
            ],
        }

    def _backlog_data(self) -> dict:
        return {
            "org": "test-org",
            "platform": "salesforce",
            "overall_score": 0.45,
            "mapped_items": [
                {"severity": "critical", "status": "fail", "sbs_control_id": "AUTH-001"},
                {"severity": "high", "status": "partial", "sbs_control_id": "AUTH-002"},
            ],
            "iso27001_summary": {"covered": 12},
        }

    def test_returns_string_with_assessment_id(self) -> None:
        ctx = _build_review_context("test-001", self._gap_data(), self._backlog_data())
        assert "test-001" in ctx

    def test_includes_all_critical_findings(self) -> None:
        ctx = _build_review_context("test-001", self._gap_data(), self._backlog_data())
        assert "AUTH-001" in ctx

    def test_produces_valid_inner_json(self) -> None:
        ctx = _build_review_context("test-001", self._gap_data(), self._backlog_data())
        # Extract JSON from <assessment_context> block
        start = ctx.index("<assessment_context>") + len("<assessment_context>")
        end = ctx.index("</assessment_context>")
        inner = json.loads(ctx[start:end].strip())
        assert "gap_summary" in inner
        assert "backlog_summary" in inner

    def test_status_counts_are_correct(self) -> None:
        ctx = _build_review_context("test-001", self._gap_data(), self._backlog_data())
        start = ctx.index("<assessment_context>") + len("<assessment_context>")
        end = ctx.index("</assessment_context>")
        inner = json.loads(ctx[start:end].strip())
        counts = inner["gap_summary"]["status_counts"]
        assert counts["fail"] == 2
        assert counts["pass"] == 1
        assert counts["not_applicable"] == 1

    def test_empty_findings_handled(self) -> None:
        gap_data = {"assessment_id": "empty-001", "findings": []}
        backlog_data = {"org": "x", "mapped_items": []}
        ctx = _build_review_context("empty-001", gap_data, backlog_data)
        assert "empty-001" in ctx

    def test_missing_backlog_fields_handled(self) -> None:
        gap_data = {"assessment_id": "min-001", "findings": []}
        backlog_data = {}
        ctx = _build_review_context("min-001", gap_data, backlog_data)
        inner_start = ctx.index("<assessment_context>") + len("<assessment_context>")
        inner_end = ctx.index("</assessment_context>")
        inner = json.loads(ctx[inner_start:inner_end].strip())
        assert inner["backlog_summary"]["org"] is None


# ---------------------------------------------------------------------------
# assess CLI — dry-run
# ---------------------------------------------------------------------------


class TestAssessDryRun:
    def test_dry_run_salesforce_writes_verdict(self, tmp_path: Path) -> None:
        out_path = tmp_path / "nist_review.json"
        runner = CliRunner()
        result = runner.invoke(cli, ["assess", "--dry-run", "--platform", "salesforce", "--out", str(out_path)])
        assert result.exit_code == 0, result.output
        verdict = json.loads(out_path.read_text())
        assert "nist_ai_rmf_review" in verdict
        assert verdict["nist_ai_rmf_review"]["overall"] == "flag"

    def test_dry_run_workday_writes_verdict(self, tmp_path: Path) -> None:
        out_path = tmp_path / "nist_review_wd.json"
        runner = CliRunner()
        result = runner.invoke(cli, ["assess", "--dry-run", "--platform", "workday", "--out", str(out_path)])
        assert result.exit_code == 0
        verdict = json.loads(out_path.read_text())
        assert verdict["nist_ai_rmf_review"]["reviewer"] == "nist-reviewer"

    def test_dry_run_fills_reviewed_at_utc(self, tmp_path: Path) -> None:
        out_path = tmp_path / "v.json"
        runner = CliRunner()
        runner.invoke(cli, ["assess", "--dry-run", "--out", str(out_path)])
        verdict = json.loads(out_path.read_text())
        assert verdict["nist_ai_rmf_review"]["reviewed_at_utc"] != ""

    def test_dry_run_uses_assessment_id_from_gap_file(self, tmp_path: Path) -> None:
        gap_path = tmp_path / "gap.json"
        gap_path.write_text(json.dumps({"assessment_id": "my-custom-id", "findings": []}))
        out_path = tmp_path / "v.json"
        runner = CliRunner()
        runner.invoke(cli, ["assess", "--dry-run", "--gap-analysis", str(gap_path), "--out", str(out_path)])
        verdict = json.loads(out_path.read_text())
        assert verdict["nist_ai_rmf_review"]["assessment_id"] == "my-custom-id"

    def test_dry_run_creates_parent_dirs(self, tmp_path: Path) -> None:
        out_path = tmp_path / "nested" / "dir" / "verdict.json"
        runner = CliRunner()
        result = runner.invoke(cli, ["assess", "--dry-run", "--out", str(out_path)])
        assert result.exit_code == 0
        assert out_path.exists()

    def test_dry_run_salesforce_governs_pass(self, tmp_path: Path) -> None:
        out_path = tmp_path / "v.json"
        runner = CliRunner()
        runner.invoke(cli, ["assess", "--dry-run", "--platform", "salesforce", "--out", str(out_path)])
        verdict = json.loads(out_path.read_text())
        assert verdict["nist_ai_rmf_review"]["govern"]["status"] == "pass"

    def test_dry_run_stubs_are_independent_copies(self, tmp_path: Path) -> None:
        """Each dry-run invocation should get its own timestamp, not share state."""
        out1 = tmp_path / "v1.json"
        out2 = tmp_path / "v2.json"
        runner = CliRunner()
        runner.invoke(cli, ["assess", "--dry-run", "--out", str(out1)])
        runner.invoke(cli, ["assess", "--dry-run", "--out", str(out2)])
        v1 = json.loads(out1.read_text())
        v2 = json.loads(out2.read_text())
        # Both should have a timestamp, both verdicts are valid
        assert v1["nist_ai_rmf_review"]["reviewed_at_utc"] != ""
        assert v2["nist_ai_rmf_review"]["reviewed_at_utc"] != ""


# ---------------------------------------------------------------------------
# assess CLI — live mode error paths
# ---------------------------------------------------------------------------


class TestAssessLiveModeErrors:
    def test_missing_gap_analysis_and_backlog_exits(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["assess", "--out", str(tmp_path / "out.json")])
        assert result.exit_code != 0

    def test_missing_api_key_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        gap = tmp_path / "gap.json"
        backlog = tmp_path / "backlog.json"
        gap.write_text(json.dumps({"assessment_id": "x", "findings": []}))
        backlog.write_text(json.dumps({"org": "x", "mapped_items": []}))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["assess", "--gap-analysis", str(gap), "--backlog", str(backlog), "--out", str(tmp_path / "out.json")],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Dry-run stub data integrity
# ---------------------------------------------------------------------------


class TestDryRunStubs:
    def test_salesforce_stub_has_required_keys(self) -> None:
        review = _DRY_RUN_VERDICTS["salesforce"]["nist_ai_rmf_review"]
        for key in ("govern", "map", "measure", "manage", "overall", "blocking_issues"):
            assert key in review, f"missing key: {key}"

    def test_workday_stub_has_required_keys(self) -> None:
        review = _DRY_RUN_VERDICTS["workday"]["nist_ai_rmf_review"]
        for key in ("govern", "map", "measure", "manage", "overall", "recommendations"):
            assert key in review, f"missing key: {key}"

    def test_both_platforms_have_blocking_issues_list(self) -> None:
        for platform in ("salesforce", "workday"):
            assert isinstance(_DRY_RUN_VERDICTS[platform]["nist_ai_rmf_review"]["blocking_issues"], list)


# ---------------------------------------------------------------------------
# Live mode — structured JSON parse and regex salvage fallback (FIX 3)
# ---------------------------------------------------------------------------


class TestAssessLiveModeStructuredParse:
    """Tests for live-mode structured JSON output and regex salvage fallback."""

    def _gap_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "gap.json"
        f.write_text(json.dumps({"assessment_id": "test-live-001", "findings": []}))
        return f

    def _backlog_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "backlog.json"
        f.write_text(json.dumps({"org": "test", "mapped_items": []}))
        return f

    def _valid_verdict_json(self, assessment_id: str = "test-live-001") -> str:
        return json.dumps(
            {
                "nist_ai_rmf_review": {
                    "assessment_id": assessment_id,
                    "reviewed_at_utc": "2026-01-01T00:00:00+00:00",
                    "reviewer": "nist-reviewer",
                    "govern": {"status": "pass", "notes": "Accountability defined."},
                    "map": {"status": "pass", "notes": "Scope bounded."},
                    "measure": {"status": "pass", "notes": "Confidence tracked."},
                    "manage": {"status": "partial", "notes": "Due dates missing."},
                    "overall": "flag",
                    "blocking_issues": [],
                    "recommendations": ["Add due dates to critical findings."],
                }
            }
        )

    def test_nist_review_structured_parse_produces_correct_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful structured JSON parse from nist_review live mode produces correct verdict."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        gap = self._gap_file(tmp_path)
        backlog = self._backlog_file(tmp_path)
        out = tmp_path / "nist_review.json"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = self._valid_verdict_json()

        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai_cls.return_value = mock_client

            runner = __import__("click.testing", fromlist=["CliRunner"]).CliRunner()
            result = runner.invoke(
                cli,
                ["assess", "--gap-analysis", str(gap), "--backlog", str(backlog), "--out", str(out)],
            )

        assert result.exit_code == 0, result.output
        verdict = json.loads(out.read_text())
        assert "nist_ai_rmf_review" in verdict
        review = verdict["nist_ai_rmf_review"]
        assert review["overall"] == "flag"
        assert review["govern"]["status"] == "pass"
        assert isinstance(review["blocking_issues"], list)

    def test_nist_review_malformed_response_triggers_fail_closed_not_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Malformed nist_review response triggers fail-closed verdict, not an exception."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        gap = self._gap_file(tmp_path)
        backlog = self._backlog_file(tmp_path)
        out = tmp_path / "nist_review_fallback.json"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        # Pure prose — not valid JSON
        mock_response.choices[0].message.content = (
            "The assessment looks okay. verdict: flag. All functions were reviewed."
        )

        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai_cls.return_value = mock_client

            runner = __import__("click.testing", fromlist=["CliRunner"]).CliRunner()
            result = runner.invoke(
                cli,
                ["assess", "--gap-analysis", str(gap), "--backlog", str(backlog), "--out", str(out)],
            )

        # Must not raise — fail-closed verdict is written
        assert result.exit_code == 0, result.output
        verdict = json.loads(out.read_text())
        assert "nist_ai_rmf_review" in verdict
        assert verdict["nist_ai_rmf_review"]["overall"] == "block"
        assert verdict["nist_ai_rmf_review"]["parser_mode"] == "fail_closed"

    def test_malformed_response_is_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JSON parse failure returns fail-closed verdict wrapped in nist_ai_rmf_review."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        gap = self._gap_file(tmp_path)
        backlog = self._backlog_file(tmp_path)
        out = tmp_path / "nist_fail_closed.json"

        # Pure prose wrapping that cannot be parsed as JSON
        prose_wrapping = "Here is my verdict: flag. All functions were reviewed. The org is okay."

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = prose_wrapping

        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai_cls.return_value = mock_client

            runner = __import__("click.testing", fromlist=["CliRunner"]).CliRunner()
            result = runner.invoke(
                cli,
                ["assess", "--gap-analysis", str(gap), "--backlog", str(backlog), "--out", str(out)],
            )

        assert result.exit_code == 0, result.output
        verdict = json.loads(out.read_text())
        assert "nist_ai_rmf_review" in verdict
        review = verdict["nist_ai_rmf_review"]
        assert review["overall"] == "block"
        assert review["parser_mode"] == "fail_closed"
        assert "Structured parse failure" in review["blocking_issues"][0]
        assert review["govern"]["status"] == "BLOCK"

    def test_valid_structured_response_has_no_degraded_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Valid structured JSON parse does NOT add parser_mode or REVIEW REQUIRED."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        gap = self._gap_file(tmp_path)
        backlog = self._backlog_file(tmp_path)
        out = tmp_path / "nist_valid.json"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = self._valid_verdict_json()

        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai_cls.return_value = mock_client

            runner = __import__("click.testing", fromlist=["CliRunner"]).CliRunner()
            result = runner.invoke(
                cli,
                ["assess", "--gap-analysis", str(gap), "--backlog", str(backlog), "--out", str(out)],
            )

        assert result.exit_code == 0, result.output
        verdict = json.loads(out.read_text())
        review = verdict["nist_ai_rmf_review"]
        assert "parser_mode" not in review
        assert not any("REVIEW REQUIRED" in rec for rec in review.get("recommendations", []))

    def test_nist_review_response_format_requested_in_api_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Live mode passes response_format=json_object to the OpenAI API call."""
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        gap = self._gap_file(tmp_path)
        backlog = self._backlog_file(tmp_path)
        out = tmp_path / "nist_review_rf.json"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = self._valid_verdict_json()

        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai_cls.return_value = mock_client

            runner = __import__("click.testing", fromlist=["CliRunner"]).CliRunner()
            runner.invoke(
                cli,
                ["assess", "--gap-analysis", str(gap), "--backlog", str(backlog), "--out", str(out)],
            )

        call_kwargs = mock_client.chat.completions.create.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert kwargs.get("response_format") == {"type": "json_object"}
