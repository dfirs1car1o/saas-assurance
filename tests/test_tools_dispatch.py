"""
Tests for harness.tools dispatcher functions.

Covers the per-tool dispatch paths with _run patched to avoid subprocess calls.
Verifies return shapes, path validation, and the unknown-tool guard.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.tools import _ARTIFACT_ROOT, _run, dispatch

# Stable test org — artifacts land under the gitignored generated/ tree.
_TEST_ORG = "ci-dry-run-sfdc"
_TEST_DATE = "2026-01-01"
_BASE = _ARTIFACT_ROOT / _TEST_ORG / _TEST_DATE


@pytest.fixture(autouse=True)
def ensure_base_dir() -> None:
    _BASE.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# _run helper
# ---------------------------------------------------------------------------


class TestRunHelper:
    def test_raises_on_nonzero_exit(self) -> None:
        with patch("harness.tools.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=1, stderr="boom", stdout="")
            with pytest.raises(RuntimeError, match="failed"):
                _run(["some", "cmd"])

    def test_returns_stdout_on_success(self) -> None:
        with patch("harness.tools.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout='{"status":"ok"}', stderr="")
            assert _run(["some", "cmd"]) == '{"status":"ok"}'


# ---------------------------------------------------------------------------
# Unknown tool guard
# ---------------------------------------------------------------------------


class TestDispatchUnknownTool:
    def test_unknown_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown tool"):
            dispatch("nonexistent_tool", {"org": _TEST_ORG})


# ---------------------------------------------------------------------------
# workday_connect_collect
# ---------------------------------------------------------------------------


class TestDispatchWorkdayConnect:
    def test_dry_run_returns_ok(self) -> None:
        with patch("harness.tools._run", return_value=""):
            result = dispatch("workday_connect_collect", {"org": _TEST_ORG, "dry_run": True, "env": "dev"})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["dry_run"] is True

    def test_live_mode_returns_ok(self) -> None:
        with patch("harness.tools._run", return_value=""):
            result = dispatch("workday_connect_collect", {"org": _TEST_ORG, "env": "dev"})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "output_file" in data


# ---------------------------------------------------------------------------
# sfdc_connect_collect
# ---------------------------------------------------------------------------


class TestDispatchSfdcConnect:
    def test_dry_run_skips_api(self) -> None:
        with patch("harness.tools._run", return_value=""):
            result = dispatch("sfdc_connect_collect", {"org": _TEST_ORG, "scope": "all", "dry_run": True})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["dry_run"] is True

    def test_live_scope_all(self) -> None:
        with patch("harness.tools._run", return_value=""):
            result = dispatch("sfdc_connect_collect", {"org": _TEST_ORG, "scope": "auth"})
        data = json.loads(result)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# oscal_assess_assess
# ---------------------------------------------------------------------------


class TestDispatchOscalAssess:
    def test_salesforce_dry_run(self) -> None:
        with patch("harness.tools._run", return_value=""):
            result = dispatch("oscal_assess_assess", {"org": _TEST_ORG, "dry_run": True, "platform": "salesforce"})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["output_file"].endswith("gap_analysis.json")

    def test_workday_platform(self) -> None:
        with patch("harness.tools._run", return_value=""):
            result = dispatch("oscal_assess_assess", {"org": _TEST_ORG, "dry_run": True, "platform": "workday"})
        data = json.loads(result)
        assert data["status"] == "ok"

    def test_with_assessment_owner(self) -> None:
        with patch("harness.tools._run", return_value=""):
            result = dispatch(
                "oscal_assess_assess",
                {"org": _TEST_ORG, "dry_run": True, "assessment_owner": "alice@example.com"},
            )
        assert json.loads(result)["status"] == "ok"

    def test_unknown_assessment_owner_not_forwarded(self) -> None:
        with patch("harness.tools._run", return_value="") as run_mock:
            result = dispatch(
                "oscal_assess_assess",
                {"org": _TEST_ORG, "dry_run": True, "assessment_owner": "unknown"},
            )
        assert json.loads(result)["status"] == "ok"
        forwarded_args = run_mock.call_args.args[0]
        assert "--assessment-owner" not in forwarded_args


# ---------------------------------------------------------------------------
# oscal_gap_map
# ---------------------------------------------------------------------------


class TestDispatchGapMap:
    def test_gap_map_returns_backlog_path(self) -> None:
        gap_path = str(_BASE / "gap_analysis.json")
        (_BASE / "gap_analysis.json").write_text(json.dumps({"findings": []}))
        with patch("harness.tools._run", return_value=""):
            result = dispatch("oscal_gap_map", {"org": _TEST_ORG, "gap_analysis": gap_path})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "backlog.json" in data["output_file"]

    def test_gap_map_rejects_traversal_input(self) -> None:
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            dispatch("oscal_gap_map", {"org": _TEST_ORG, "gap_analysis": "/etc/passwd"})


# ---------------------------------------------------------------------------
# sscf_benchmark_benchmark
# ---------------------------------------------------------------------------


class TestDispatchSscfBenchmark:
    def test_benchmark_returns_sscf_report(self) -> None:
        backlog_path = str(_BASE / "backlog.json")
        (_BASE / "backlog.json").write_text(json.dumps({"mapped_items": []}))
        with patch("harness.tools._run", return_value=""):
            result = dispatch("sscf_benchmark_benchmark", {"org": _TEST_ORG, "backlog": backlog_path})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "sscf_report.json" in data["output_file"]


# ---------------------------------------------------------------------------
# nist_review_assess
# ---------------------------------------------------------------------------


class TestDispatchNistReview:
    def test_dry_run_returns_ok(self) -> None:
        with patch("harness.tools._run", return_value=""):
            result = dispatch("nist_review_assess", {"org": _TEST_ORG, "dry_run": True})
        assert json.loads(result)["status"] == "ok"

    def test_with_gap_analysis_and_backlog(self) -> None:
        gap_path = str(_BASE / "gap_analysis.json")
        backlog_path = str(_BASE / "backlog.json")
        (_BASE / "gap_analysis.json").write_text(json.dumps({"findings": []}))
        (_BASE / "backlog.json").write_text(json.dumps({"mapped_items": []}))
        with patch("harness.tools._run", return_value=""):
            result = dispatch(
                "nist_review_assess",
                {"org": _TEST_ORG, "gap_analysis": gap_path, "backlog": backlog_path, "platform": "salesforce"},
            )
        assert json.loads(result)["status"] == "ok"


# ---------------------------------------------------------------------------
# report_gen_generate
# ---------------------------------------------------------------------------


class TestDispatchReportGen:
    def test_security_audience(self) -> None:
        backlog_path = str(_BASE / "backlog.json")
        out_path = str(_BASE / "security_report.md")
        (_BASE / "backlog.json").write_text(json.dumps({"mapped_items": []}))
        with patch("harness.tools._run", return_value=""):
            result = dispatch(
                "report_gen_generate",
                {"org": _TEST_ORG, "backlog": backlog_path, "audience": "security", "out": out_path},
            )
        assert json.loads(result)["status"] == "ok"

    def test_app_owner_with_optional_flags(self) -> None:
        backlog_path = str(_BASE / "backlog.json")
        sscf_path = str(_BASE / "sscf_report.json")
        nist_path = str(_BASE / "nist_review.json")
        out_path = str(_BASE / "remediation.md")
        for p, content in [
            (backlog_path, {"mapped_items": []}),
            (sscf_path, {"overall_score": 0.5}),
            (nist_path, {"nist_ai_rmf_review": {"overall": "partial"}}),
        ]:
            Path(p).write_text(json.dumps(content))
        with patch("harness.tools._run", return_value=""):
            result = dispatch(
                "report_gen_generate",
                {
                    "org": _TEST_ORG,
                    "backlog": backlog_path,
                    "audience": "app-owner",
                    "out": out_path,
                    "sscf_benchmark": sscf_path,
                    "nist_review": nist_path,
                    "mock_llm": True,
                    "platform": "salesforce",
                    "title": "Test Report",
                },
            )
        assert json.loads(result)["status"] == "ok"

    def test_rejects_out_path_traversal(self) -> None:
        backlog_path = str(_BASE / "backlog.json")
        (_BASE / "backlog.json").write_text(json.dumps({"mapped_items": []}))
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            dispatch(
                "report_gen_generate",
                {"org": _TEST_ORG, "backlog": backlog_path, "audience": "security", "out": "/tmp/evil.md"},
            )


# ---------------------------------------------------------------------------
# gen_aicm_crosswalk
# ---------------------------------------------------------------------------


class TestDispatchAicmCrosswalk:
    def test_aicm_returns_ok(self) -> None:
        backlog_path = str(_BASE / "backlog.json")
        (_BASE / "backlog.json").write_text(json.dumps({"mapped_items": []}))
        with patch("harness.tools._run", return_value=""):
            result = dispatch("gen_aicm_crosswalk", {"org": _TEST_ORG, "backlog": backlog_path})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "aicm_coverage.json" in data["output_file"]

    def test_aicm_with_platform(self) -> None:
        backlog_path = str(_BASE / "backlog.json")
        (_BASE / "backlog.json").write_text(json.dumps({"mapped_items": []}))
        with patch("harness.tools._run", return_value=""):
            result = dispatch("gen_aicm_crosswalk", {"org": _TEST_ORG, "backlog": backlog_path, "platform": "workday"})
        assert json.loads(result)["status"] == "ok"


# ---------------------------------------------------------------------------
# backlog_diff
# ---------------------------------------------------------------------------


class TestDispatchBacklogDiff:
    def test_returns_stdout_on_success(self) -> None:
        baseline = str(_BASE / "baseline.json")
        current = str(_BASE / "backlog.json")
        (_BASE / "baseline.json").write_text(json.dumps({"mapped_items": []}))
        (_BASE / "backlog.json").write_text(json.dumps({"mapped_items": []}))
        expected = json.dumps({"status": "ok", "regressions": []})
        with patch("harness.tools._run", return_value=expected):
            result = dispatch("backlog_diff", {"org": _TEST_ORG, "baseline": baseline, "current": current})
        assert json.loads(result)["status"] == "ok"

    def test_missing_inputs_returns_error(self) -> None:
        result = dispatch("backlog_diff", {"org": _TEST_ORG})
        assert json.loads(result)["status"] == "error"

    def test_rejects_traversal_baseline(self) -> None:
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            dispatch("backlog_diff", {"org": _TEST_ORG, "baseline": "/etc/passwd", "current": "/etc/passwd"})


# ---------------------------------------------------------------------------
# sfdc_expert_enrich
# ---------------------------------------------------------------------------


class TestDispatchSfdcExpert:
    def test_missing_gap_analysis_path(self) -> None:
        result = dispatch("sfdc_expert_enrich", {"org": _TEST_ORG, "gap_analysis": ""})
        assert json.loads(result)["status"] == "error"

    def test_nonexistent_file_returns_error(self) -> None:
        result = dispatch("sfdc_expert_enrich", {"org": _TEST_ORG, "gap_analysis": "/nonexistent/path.json"})
        assert json.loads(result)["status"] == "error"

    def test_enriches_eligible_findings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Redirect _REPO so apex scripts land in tmp_path, not in the live repo tree.
        # Without this, the dispatcher writes apex files into
        # docs/oscal-salesforce-poc/apex-scripts/ and leaves untracked repo artifacts.
        import harness.tools as tools_mod

        monkeypatch.setattr(tools_mod, "_REPO", tmp_path)
        gap_data = {
            "findings": [
                {"control_id": "SBS-AUTH-001", "status": "fail", "needs_expert_review": True},
                {"control_id": "SBS-ACS-001", "status": "pass", "needs_expert_review": False},
            ]
        }
        gap_path = tmp_path / "gap_analysis.json"
        gap_path.write_text(json.dumps(gap_data))
        result = dispatch("sfdc_expert_enrich", {"org": _TEST_ORG, "gap_analysis": str(gap_path)})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["enriched_findings"] == 1

    def test_no_eligible_findings_enriches_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import harness.tools as tools_mod

        monkeypatch.setattr(tools_mod, "_REPO", tmp_path)
        gap_data = {"findings": [{"control_id": "SBS-ACS-001", "status": "pass", "needs_expert_review": False}]}
        gap_path = tmp_path / "gap_analysis.json"
        gap_path.write_text(json.dumps(gap_data))
        result = dispatch("sfdc_expert_enrich", {"org": _TEST_ORG, "gap_analysis": str(gap_path)})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["enriched_findings"] == 0
