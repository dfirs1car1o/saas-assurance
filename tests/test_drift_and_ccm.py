"""Tests for drift detection (scripts/drift_check.py) and CCM crosswalk (report_gen)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
PYTHON = sys.executable

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BASELINE_ITEMS = [
    {
        "sbs_control_id": "SBS-AUTH-001",
        "sbs_title": "SSO/MFA",
        "status": "fail",
        "severity": "critical",
        "owner": "SecTeam",
        "due_date": "2026-03-15",
        "sscf_mappings": [],
        "sscf_control_ids": [],
    },
    # fail in baseline → partial in current = improvement (fail→partial)
    {
        "sbs_control_id": "SBS-AUTH-002",
        "sbs_title": "Password Policy",
        "status": "fail",
        "severity": "high",
        "owner": "SecTeam",
        "due_date": "2026-04-07",
        "sscf_mappings": [],
        "sscf_control_ids": [],
    },
    {
        "sbs_control_id": "SBS-LOG-001",
        "sbs_title": "Audit Logging",
        "status": "pass",
        "severity": "high",
        "owner": "SecTeam",
        "due_date": None,
        "sscf_mappings": [],
        "sscf_control_ids": [],
    },
]

_CURRENT_ITEMS = [
    # SBS-AUTH-001: still failing (unchanged_failing)
    {
        "sbs_control_id": "SBS-AUTH-001",
        "sbs_title": "SSO/MFA",
        "status": "fail",
        "severity": "critical",
        "owner": "SecTeam",
        "due_date": "2026-03-15",
        "sscf_mappings": [],
        "sscf_control_ids": [],
    },
    # SBS-AUTH-002: improved (fail → partial)
    {
        "sbs_control_id": "SBS-AUTH-002",
        "sbs_title": "Password Policy",
        "status": "partial",
        "severity": "high",
        "owner": "SecTeam",
        "due_date": "2026-04-07",
        "sscf_mappings": [],
        "sscf_control_ids": [],
    },
    # SBS-LOG-001: regression (pass → fail)
    {
        "sbs_control_id": "SBS-LOG-001",
        "sbs_title": "Audit Logging",
        "status": "fail",
        "severity": "high",
        "owner": "SecTeam",
        "due_date": "2026-04-07",
        "sscf_mappings": [],
        "sscf_control_ids": [],
    },
    # SBS-ACS-001: new finding
    {
        "sbs_control_id": "SBS-ACS-001",
        "sbs_title": "Permission Sets",
        "status": "fail",
        "severity": "high",
        "owner": "SecTeam",
        "due_date": "2026-04-07",
        "sscf_mappings": [],
        "sscf_control_ids": [],
    },
]


def _make_backlog(items: list, tmp_path: Path, name: str) -> Path:
    data = {
        "assessment_id": f"sf-test-{name}",
        "org": "test-org",
        "platform": "salesforce",
        "assessment_owner": "Test Team",
        "generated_at_utc": "2026-03-08T00:00:00+00:00",
        "catalog_version": "0.4.0",
        "framework": "CSA_SSCF",
        "summary": {
            "mapped_findings": len(items),
            "unmapped_findings": 0,
            "status_counts": {},
            "mapping_confidence_counts": {},
        },
        "mapped_items": items,
        "unmapped_items": [],
        "invalid_mapping_entries": [],
    }
    p = tmp_path / f"{name}_backlog.json"
    p.write_text(json.dumps(data))
    return p


# ===========================================================================
# Drift detection tests
# ===========================================================================


class TestDriftLogic:
    """Unit tests for the diff_backlogs function."""

    def test_regression_detected(self, tmp_path: Path) -> None:
        from scripts.drift_check import diff_backlogs

        b = {"mapped_items": _BASELINE_ITEMS, "assessment_id": "base", "org": "x"}
        c = {"mapped_items": _CURRENT_ITEMS, "assessment_id": "curr", "org": "x"}
        drift = diff_backlogs(b, c)

        regressions = drift["regressions"]
        assert len(regressions) == 1
        assert regressions[0]["control_id"] == "SBS-LOG-001"
        assert regressions[0]["change_type"] == "regression"

    def test_improvement_detected(self, tmp_path: Path) -> None:
        from scripts.drift_check import diff_backlogs

        b = {"mapped_items": _BASELINE_ITEMS, "assessment_id": "base", "org": "x"}
        c = {"mapped_items": _CURRENT_ITEMS, "assessment_id": "curr", "org": "x"}
        drift = diff_backlogs(b, c)

        improvements = drift["improvements"]
        assert len(improvements) == 1
        assert improvements[0]["control_id"] == "SBS-AUTH-002"

    def test_new_finding_detected(self, tmp_path: Path) -> None:
        from scripts.drift_check import diff_backlogs

        b = {"mapped_items": _BASELINE_ITEMS, "assessment_id": "base", "org": "x"}
        c = {"mapped_items": _CURRENT_ITEMS, "assessment_id": "curr", "org": "x"}
        drift = diff_backlogs(b, c)

        assert any(ch["control_id"] == "SBS-ACS-001" for ch in drift["new_findings"])

    def test_score_delta(self, tmp_path: Path) -> None:
        from scripts.drift_check import diff_backlogs

        b = {"mapped_items": _BASELINE_ITEMS, "assessment_id": "base", "org": "x"}
        c = {"mapped_items": _CURRENT_ITEMS, "assessment_id": "curr", "org": "x"}
        drift = diff_backlogs(b, c)

        # Baseline: 1 pass / 3 total → 33.3%; Current: 1 pass / 4 total → 25%
        assert drift["summary"]["net_direction"] == "regressing"
        assert drift["summary"]["score_delta"] < 0

    def test_summary_counts(self, tmp_path: Path) -> None:
        from scripts.drift_check import diff_backlogs

        b = {"mapped_items": _BASELINE_ITEMS, "assessment_id": "base", "org": "x"}
        c = {"mapped_items": _CURRENT_ITEMS, "assessment_id": "curr", "org": "x"}
        drift = diff_backlogs(b, c)
        s = drift["summary"]

        assert s["regressions"] == 1
        assert s["improvements"] == 1
        assert s["new_findings"] == 1
        assert s["resolved_findings"] == 0


class TestDriftCLI:
    """Integration test — invoke drift_check.py as subprocess."""

    def test_cli_produces_json_and_md(self, tmp_path: Path) -> None:
        baseline = _make_backlog(_BASELINE_ITEMS, tmp_path, "baseline")
        current = _make_backlog(_CURRENT_ITEMS, tmp_path, "current")
        out_json = tmp_path / "drift.json"
        out_md = tmp_path / "drift.md"

        result = subprocess.run(
            [
                PYTHON,
                "scripts/drift_check.py",
                "--baseline",
                str(baseline),
                "--current",
                str(current),
                "--out",
                str(out_json),
                "--out-md",
                str(out_md),
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert result.returncode == 0, f"drift_check failed:\n{result.stderr}"
        assert out_json.exists(), "drift_report.json not written"
        assert out_md.exists(), "drift_report.md not written"

        data = json.loads(out_json.read_text())
        assert "drift_id" in data
        assert "summary" in data
        assert data["summary"]["regressions"] == 1

        md = out_md.read_text()
        assert "## Summary" in md
        assert "Regressions" in md
        assert "SBS-LOG-001" in md


# ===========================================================================
# CCM crosswalk tests
# ===========================================================================


class TestCCMCrosswalk:
    """Unit tests for _render_ccm_crosswalk in report_gen."""

    def _make_backlog_with_sscf(self, sscf_id: str) -> dict:
        return {
            "mapped_items": [
                {
                    "sbs_control_id": "SBS-AUTH-001",
                    "status": "fail",
                    "severity": "critical",
                    "sscf_mappings": [{"sscf_control_id": sscf_id, "sscf_domain": "identity_access_management"}],
                    "sscf_control_ids": [sscf_id],
                }
            ]
        }

    def test_ccm_section_renders_for_failing_finding(self) -> None:
        from skills.report_gen.report_gen import _render_ccm_crosswalk

        backlog = self._make_backlog_with_sscf("SSCF-IAM-001")
        result = _render_ccm_crosswalk(backlog)

        assert "## CCM v4.1 Regulatory Crosswalk" in result
        assert "IAM-02" in result  # CCM control for SSCF-IAM-001

    def test_ccm_section_empty_for_passing_findings(self) -> None:
        from skills.report_gen.report_gen import _render_ccm_crosswalk

        backlog = {
            "mapped_items": [
                {
                    "sbs_control_id": "SBS-AUTH-001",
                    "status": "pass",
                    "severity": "critical",
                    "sscf_mappings": [{"sscf_control_id": "SSCF-IAM-001"}],
                    "sscf_control_ids": ["SSCF-IAM-001"],
                }
            ]
        }
        result = _render_ccm_crosswalk(backlog)
        assert result == ""

    def test_regulatory_highlights_appear_in_table(self) -> None:
        from skills.report_gen.report_gen import _render_ccm_crosswalk

        backlog = self._make_backlog_with_sscf("SSCF-IAM-001")
        result = _render_ccm_crosswalk(backlog)

        # SSCF-IAM-001 → IAM-02 → [SOC2_CC6.1, HIPAA_164.312d, ISO27001_A.9.4.2]
        assert "CC6.1" in result
        assert "164.312d" in result

    def test_ccm_section_in_security_report(self, tmp_path: Path) -> None:
        """Integration: security report should contain CCM section when failing findings exist."""
        _BACKLOG = REPO / "docs" / "oscal-salesforce-poc" / "generated" / "salesforce_oscal_backlog_latest.json"
        if not _BACKLOG.exists():
            pytest.skip("backlog file not found")

        out = tmp_path / "report_security.md"
        result = subprocess.run(
            [
                PYTHON,
                "-m",
                "skills.report_gen.report_gen",
                "generate",
                "--backlog",
                str(_BACKLOG),
                "--audience",
                "security",
                "--out",
                str(out),
                "--mock-llm",
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert result.returncode == 0, f"report-gen failed:\n{result.stderr}"
        # CCM crosswalk is now in the annex document, not the main report
        annex = out.with_name(out.stem + "_annex.md")
        assert annex.exists(), "Annex document not written"
        content = annex.read_text()
        assert "## CCM v4.1 Regulatory Crosswalk" in content
