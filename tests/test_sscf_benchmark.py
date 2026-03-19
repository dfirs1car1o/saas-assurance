"""
Tests for skills.sscf_benchmark — SSCF domain compliance scorecard.

Covers:
- _domain_status thresholds (green/amber/red/not_assessed)
- _score_findings (pass/partial/fail/not_applicable weighting)
- run_benchmark core logic with a minimal inline sscf_index
- _to_markdown rendering (headers, score strings, N/A handling)
- _load_backlog validation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from skills.sscf_benchmark.sscf_benchmark import (
    _domain_status,
    _load_backlog,
    _load_sscf_index,
    _score_findings,
    _to_markdown,
    cli,
    run_benchmark,
)

# ---------------------------------------------------------------------------
# Minimal SSCF index for tests (no file I/O needed)
# ---------------------------------------------------------------------------

_MINI_INDEX: dict[str, dict[str, Any]] = {
    "SSCF-IAM-01": {
        "sscf_control_id": "SSCF-IAM-01",
        "domain": "Identity & Access Management",
        "title": "MFA Enforcement",
        "owner_team": "IAM",
    },
    "SSCF-IAM-02": {
        "sscf_control_id": "SSCF-IAM-02",
        "domain": "Identity & Access Management",
        "title": "Privileged Access",
        "owner_team": "IAM",
    },
    "SSCF-LOG-01": {
        "sscf_control_id": "SSCF-LOG-01",
        "domain": "Logging & Monitoring",
        "title": "Audit Logging",
        "owner_team": "SecOps",
    },
}

_MINI_BACKLOG: dict[str, Any] = {
    "assessment_id": "test-bench-001",
    "org": "test-org",
    "mapped_items": [
        {"sbs_control_id": "AUTH-001", "status": "fail", "severity": "critical", "sscf_control_ids": ["SSCF-IAM-01"]},
        {"sbs_control_id": "AUTH-002", "status": "pass", "severity": "moderate", "sscf_control_ids": ["SSCF-IAM-02"]},
        {"sbs_control_id": "LOG-001", "status": "partial", "severity": "high", "sscf_control_ids": ["SSCF-LOG-01"]},
    ],
}


# ---------------------------------------------------------------------------
# _domain_status
# ---------------------------------------------------------------------------


class TestDomainStatus:
    def test_none_score_returns_not_assessed(self) -> None:
        assert _domain_status(None, 0.80) == "not_assessed"

    def test_score_at_threshold_returns_green(self) -> None:
        assert _domain_status(0.80, 0.80) == "green"

    def test_score_above_threshold_returns_green(self) -> None:
        assert _domain_status(1.0, 0.80) == "green"

    def test_score_between_50_and_threshold_returns_amber(self) -> None:
        assert _domain_status(0.60, 0.80) == "amber"

    def test_score_at_50_returns_amber(self) -> None:
        assert _domain_status(0.50, 0.80) == "amber"

    def test_score_below_50_returns_red(self) -> None:
        assert _domain_status(0.40, 0.80) == "red"

    def test_score_zero_returns_red(self) -> None:
        assert _domain_status(0.0, 0.80) == "red"

    def test_custom_threshold(self) -> None:
        assert _domain_status(0.70, 0.65) == "green"
        assert _domain_status(0.60, 0.65) == "amber"


# ---------------------------------------------------------------------------
# _score_findings
# ---------------------------------------------------------------------------


class TestScoreFindings:
    def test_all_pass_returns_score_one(self) -> None:
        items = [{"status": "pass"}, {"status": "pass"}]
        p, par, f, na, score = _score_findings(items)
        assert p == 2
        assert score == pytest.approx(1.0)

    def test_all_fail_returns_score_zero(self) -> None:
        items = [{"status": "fail"}, {"status": "fail"}]
        _, _, f, _, score = _score_findings(items)
        assert f == 2
        assert score == pytest.approx(0.0)

    def test_partial_scores_half(self) -> None:
        items = [{"status": "partial"}]
        _, par, _, _, score = _score_findings(items)
        assert par == 1
        assert score == pytest.approx(0.5)

    def test_mixed_scoring(self) -> None:
        # 1 pass (1.0) + 1 fail (0.0) = 0.5 / 2 scoreable
        items = [{"status": "pass"}, {"status": "fail"}]
        _, _, _, _, score = _score_findings(items)
        assert score == pytest.approx(0.5)

    def test_not_applicable_excluded_from_score(self) -> None:
        items = [{"status": "pass"}, {"status": "not_applicable"}]
        p, _, _, na, score = _score_findings(items)
        assert p == 1
        assert na == 1
        assert score == pytest.approx(1.0)

    def test_all_not_applicable_returns_none_score(self) -> None:
        items = [{"status": "not_applicable"}, {"status": "not_applicable"}]
        _, _, _, na, score = _score_findings(items)
        assert na == 2
        assert score is None

    def test_empty_list_returns_none_score(self) -> None:
        _, _, _, _, score = _score_findings([])
        assert score is None

    def test_unknown_status_ignored_in_score(self) -> None:
        items = [{"status": "unknown"}, {"status": "pass"}]
        p, _, _, _, score = _score_findings(items)
        assert p == 1
        assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# run_benchmark
# ---------------------------------------------------------------------------


class TestRunBenchmark:
    def test_returns_required_top_level_keys(self) -> None:
        report = run_benchmark(_MINI_BACKLOG, _MINI_INDEX, threshold=0.80)
        for key in ("benchmark_id", "generated_at_utc", "overall_score", "overall_status", "domains", "summary"):
            assert key in report, f"missing key: {key}"

    def test_benchmark_id_contains_assessment_id(self) -> None:
        report = run_benchmark(_MINI_BACKLOG, _MINI_INDEX, threshold=0.80)
        assert "test-bench-001" in report["benchmark_id"]

    def test_domain_count_matches_index(self) -> None:
        report = run_benchmark(_MINI_BACKLOG, _MINI_INDEX, threshold=0.80)
        # 2 unique domains in _MINI_INDEX
        assert report["summary"]["total_domains"] == 2

    def test_iam_domain_has_fail_finding(self) -> None:
        report = run_benchmark(_MINI_BACKLOG, _MINI_INDEX, threshold=0.80)
        iam = next(d for d in report["domains"] if "Identity" in d["domain"])
        assert iam["fail"] >= 1

    def test_log_domain_has_partial_finding(self) -> None:
        report = run_benchmark(_MINI_BACKLOG, _MINI_INDEX, threshold=0.80)
        log = next(d for d in report["domains"] if "Logging" in d["domain"])
        assert log["partial"] >= 1

    def test_unmatched_items_counted(self) -> None:
        backlog = dict(_MINI_BACKLOG)
        backlog["mapped_items"] = [
            {"sbs_control_id": "X-999", "status": "fail", "sscf_control_ids": ["SSCF-UNKNOWN"]},
        ]
        report = run_benchmark(backlog, _MINI_INDEX, threshold=0.80)
        assert report["summary"]["unmatched_findings"] >= 1

    def test_empty_backlog_scores_none(self) -> None:
        backlog = {"assessment_id": "empty", "mapped_items": []}
        report = run_benchmark(backlog, _MINI_INDEX, threshold=0.80)
        assert report["overall_status"] == "not_assessed"

    def test_all_pass_is_green(self) -> None:
        backlog = {
            "assessment_id": "all-pass",
            "mapped_items": [
                {"sbs_control_id": "A", "status": "pass", "sscf_control_ids": ["SSCF-IAM-01"]},
                {"sbs_control_id": "B", "status": "pass", "sscf_control_ids": ["SSCF-LOG-01"]},
            ],
        }
        report = run_benchmark(backlog, _MINI_INDEX, threshold=0.80)
        assert report["overall_status"] == "green"
        assert report["overall_score"] == pytest.approx(1.0)

    def test_score_is_rounded(self) -> None:
        report = run_benchmark(_MINI_BACKLOG, _MINI_INDEX, threshold=0.80)
        # Score should have at most 4 decimal places
        score_str = str(report["overall_score"])
        decimals = len(score_str.split(".")[-1]) if "." in score_str else 0
        assert decimals <= 4


# ---------------------------------------------------------------------------
# _to_markdown
# ---------------------------------------------------------------------------


class TestToMarkdown:
    def _make_report(self) -> dict:
        return run_benchmark(_MINI_BACKLOG, _MINI_INDEX, threshold=0.80)

    def test_contains_sscf_heading(self) -> None:
        md = _to_markdown(self._make_report())
        assert "# SSCF Compliance Benchmark" in md

    def test_contains_domain_scorecard_section(self) -> None:
        md = _to_markdown(self._make_report())
        assert "## Domain Scorecard" in md

    def test_contains_domain_names(self) -> None:
        md = _to_markdown(self._make_report())
        assert "Identity & Access Management" in md
        assert "Logging & Monitoring" in md

    def test_na_score_renders_as_na_string(self) -> None:
        backlog = {"assessment_id": "x", "mapped_items": []}
        report = run_benchmark(backlog, _MINI_INDEX, threshold=0.80)
        md = _to_markdown(report)
        assert "N/A" in md

    def test_summary_section_present(self) -> None:
        md = _to_markdown(self._make_report())
        assert "## Summary" in md

    def test_domain_details_section_present(self) -> None:
        md = _to_markdown(self._make_report())
        assert "## Domain Details" in md


# ---------------------------------------------------------------------------
# _load_backlog
# ---------------------------------------------------------------------------


class TestLoadBacklog:
    def test_loads_valid_json_object(self, tmp_path: Path) -> None:
        f = tmp_path / "backlog.json"
        f.write_text(json.dumps({"assessment_id": "x", "mapped_items": []}))
        result = _load_backlog(f)
        assert result["assessment_id"] == "x"

    def test_raises_on_json_array(self, tmp_path: Path) -> None:
        f = tmp_path / "array.json"
        f.write_text("[1, 2, 3]")
        with pytest.raises(ValueError, match="Expected JSON object"):
            _load_backlog(f)


# ---------------------------------------------------------------------------
# _load_sscf_index
# ---------------------------------------------------------------------------


class TestLoadSscfIndex:
    def test_loads_valid_yaml(self, tmp_path: Path) -> None:
        yaml_content = """controls:
  - sscf_control_id: SSCF-TST-001
    domain: Test Domain
    title: Test Control
    owner_team: test-team
  - sscf_control_id: SSCF-TST-002
    domain: Test Domain
    title: Another Control
    owner_team: test-team
"""
        f = tmp_path / "index.yaml"
        f.write_text(yaml_content)
        index = _load_sscf_index(f)
        assert "SSCF-TST-001" in index
        assert "SSCF-TST-002" in index
        assert index["SSCF-TST-001"]["domain"] == "Test Domain"

    def test_skips_entries_with_no_id(self, tmp_path: Path) -> None:
        yaml_content = """controls:
  - sscf_control_id: SSCF-VALID-001
    domain: D
    title: Valid
  - domain: D
    title: Missing ID entry
"""
        f = tmp_path / "index.yaml"
        f.write_text(yaml_content)
        index = _load_sscf_index(f)
        assert len(index) == 1
        assert "SSCF-VALID-001" in index

    def test_empty_controls_list_returns_empty_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yaml"
        f.write_text("controls: []\n")
        index = _load_sscf_index(f)
        assert index == {}

    def test_real_config_index_loads(self) -> None:
        """Smoke test against the actual repo config file."""
        repo_root = Path(__file__).resolve().parents[1]
        index_path = repo_root / "config" / "sscf_control_index.yaml"
        if not index_path.exists():
            pytest.skip("sscf_control_index.yaml not present")
        index = _load_sscf_index(index_path)
        assert len(index) > 0
        # Every entry should have a domain field
        for ctrl in index.values():
            assert "domain" in ctrl


# ---------------------------------------------------------------------------
# CLI — benchmark command
# ---------------------------------------------------------------------------


class TestBenchmarkCli:
    def _make_backlog(self, tmp_path: Path) -> Path:
        backlog = {
            "assessment_id": "cli-test-001",
            "org": "test-org",
            "mapped_items": [
                {"sbs_control_id": "AUTH-001", "status": "fail", "severity": "critical",
                 "sscf_control_ids": ["SSCF-IAM-01"]},
                {"sbs_control_id": "LOG-001", "status": "pass", "severity": "high",
                 "sscf_control_ids": ["SSCF-LOG-01"]},
            ],
        }
        p = tmp_path / "backlog.json"
        p.write_text(json.dumps(backlog))
        return p

    def _make_index(self, tmp_path: Path) -> Path:
        yaml_content = """controls:
  - sscf_control_id: SSCF-IAM-01
    domain: Identity & Access Management
    title: MFA Enforcement
    owner_team: IAM
  - sscf_control_id: SSCF-LOG-01
    domain: Logging & Monitoring
    title: Audit Logging
    owner_team: SecOps
"""
        p = tmp_path / "sscf_index.yaml"
        p.write_text(yaml_content)
        return p

    def test_cli_outputs_json_to_stdout(self, tmp_path: Path) -> None:
        backlog = self._make_backlog(tmp_path)
        index = self._make_index(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["benchmark", "--backlog", str(backlog), "--sscf-index", str(index)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        # Progress lines go to stderr; extract the JSON object from combined output
        json_start = result.output.find("{")
        assert json_start >= 0, f"No JSON in output: {result.output[:200]}"
        data = json.loads(result.output[json_start:])
        assert "overall_score" in data
        assert "domains" in data

    def test_cli_writes_json_to_file(self, tmp_path: Path) -> None:
        backlog = self._make_backlog(tmp_path)
        index = self._make_index(tmp_path)
        out = tmp_path / "report.json"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["benchmark", "--backlog", str(backlog), "--sscf-index", str(index), "--out", str(out)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert "benchmark_id" in data

    def test_cli_writes_markdown_output(self, tmp_path: Path) -> None:
        backlog = self._make_backlog(tmp_path)
        index = self._make_index(tmp_path)
        out = tmp_path / "report.md"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["benchmark", "--backlog", str(backlog), "--sscf-index", str(index),
             "--format", "markdown", "--out", str(out)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        content = out.read_text()
        assert "# SSCF Compliance Benchmark" in content

    def test_cli_exits_nonzero_on_missing_backlog(self, tmp_path: Path) -> None:
        index = self._make_index(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["benchmark", "--backlog", str(tmp_path / "nonexistent.json"), "--sscf-index", str(index)],
        )
        assert result.exit_code != 0

    def test_cli_exits_nonzero_on_missing_index(self, tmp_path: Path) -> None:
        backlog = self._make_backlog(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["benchmark", "--backlog", str(backlog), "--sscf-index", str(tmp_path / "no_index.yaml")],
        )
        assert result.exit_code != 0
