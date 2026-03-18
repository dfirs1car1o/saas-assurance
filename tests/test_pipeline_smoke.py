"""Smoke test: end-to-end dry-run pipeline without a live Salesforce org.

oscal-assess --dry-run → oscal_gap_map.py → sscf-benchmark

All three steps must produce valid JSON with expected top-level keys.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
PYTHON = sys.executable


def _run(*args: str, cwd: Path = REPO, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, cwd=cwd, check=check)


# ---------------------------------------------------------------------------
# Step 1 — oscal-assess dry-run
# ---------------------------------------------------------------------------


def test_oscal_assess_dry_run_produces_valid_json(tmp_path: Path) -> None:
    gap_json = tmp_path / "gap_analysis.json"
    result = _run(
        PYTHON,
        "-m",
        "skills.oscal_assess.oscal_assess",
        "assess",
        "--dry-run",
        "--env",
        "dev",
        "--out",
        str(gap_json),
    )
    assert result.returncode == 0, f"oscal-assess failed:\n{result.stderr}"
    assert gap_json.exists(), "gap_analysis.json not written"

    data = json.loads(gap_json.read_text())
    assert "assessment_id" in data
    assert "findings" in data
    # Issue #11: data_source and AI notice must be present
    assert data.get("data_source") == "dry_run_stub", (
        f"Expected data_source=dry_run_stub, got {data.get('data_source')}"
    )
    assert "ai_generated_findings_notice" in data
    # Issue #12: assessment_owner field must be present
    assert "assessment_owner" in data

    findings = data["findings"]
    assert len(findings) == 45, f"Expected 45 findings, got {len(findings)}"

    statuses = {f["status"] for f in findings}
    assert statuses <= {"pass", "fail", "partial", "not_applicable"}

    # Dry-run weak-org: expect at least some fails and partials
    fail_count = sum(1 for f in findings if f["status"] == "fail")
    partial_count = sum(1 for f in findings if f["status"] == "partial")
    assert fail_count >= 3, f"Expected ≥3 fails in dry-run, got {fail_count}"
    assert partial_count >= 5, f"Expected ≥5 partials in dry-run, got {partial_count}"

    # Issue #10: all fail/partial findings must have a non-empty due_date
    actionable = [f for f in findings if f["status"] in ("fail", "partial")]
    missing_due_date = [f["control_id"] for f in actionable if not f.get("due_date")]
    assert not missing_due_date, f"Findings missing due_date: {missing_due_date}"

    # Pass and not_applicable findings must NOT have a due_date
    non_actionable = [f for f in findings if f["status"] in ("pass", "not_applicable")]
    unexpected_due_date = [f["control_id"] for f in non_actionable if f.get("due_date")]
    assert not unexpected_due_date, f"Non-actionable findings have due_date: {unexpected_due_date}"


# ---------------------------------------------------------------------------
# Step 2 — oscal_gap_map.py
# ---------------------------------------------------------------------------


def test_gap_map_produces_backlog(tmp_path: Path) -> None:
    gap_json = tmp_path / "gap_analysis.json"
    backlog_json = tmp_path / "backlog.json"
    matrix_md = tmp_path / "matrix.md"

    # First generate gap analysis
    _run(
        PYTHON,
        "-m",
        "skills.oscal_assess.oscal_assess",
        "assess",
        "--dry-run",
        "--env",
        "dev",
        "--out",
        str(gap_json),
    )

    controls_path = REPO / "docs/oscal-salesforce-poc/generated/sbs_controls.json"
    mapping_path = REPO / "config/oscal-salesforce/control_mapping.yaml"
    sscf_map_path = REPO / "config/oscal-salesforce/sbs_to_sscf_mapping.yaml"

    if not controls_path.exists():
        pytest.skip(f"SBS controls catalog not found: {controls_path}")

    result = _run(
        PYTHON,
        "scripts/oscal_gap_map.py",
        "--controls",
        str(controls_path),
        "--gap-analysis",
        str(gap_json),
        "--mapping",
        str(mapping_path),
        "--sscf-map",
        str(sscf_map_path),
        "--out-md",
        str(matrix_md),
        "--out-json",
        str(backlog_json),
    )
    assert result.returncode == 0, f"oscal_gap_map.py failed:\n{result.stderr}"
    assert backlog_json.exists(), "backlog.json not written"

    data = json.loads(backlog_json.read_text())
    assert "assessment_id" in data
    assert "mapped_items" in data
    assert len(data["mapped_items"]) > 0

    # Issue #12: assessment_owner must flow through from gap_analysis to backlog
    assert "assessment_owner" in data

    # Issue #13: mapping_confidence must vary (not all "high")
    confidences = {item.get("mapping_confidence") for item in data["mapped_items"]}
    assert len(confidences) > 1, f"Expected mapping_confidence variance, got uniform: {confidences}"


# ---------------------------------------------------------------------------
# Step 3 — sscf-benchmark
# ---------------------------------------------------------------------------


def test_sscf_benchmark_produces_scorecard(tmp_path: Path) -> None:
    gap_json = tmp_path / "gap_analysis.json"
    backlog_json = tmp_path / "backlog.json"
    matrix_md = tmp_path / "matrix.md"
    sscf_json = tmp_path / "sscf_report.json"

    controls_path = REPO / "docs/oscal-salesforce-poc/generated/sbs_controls.json"
    mapping_path = REPO / "config/oscal-salesforce/control_mapping.yaml"
    sscf_map_path = REPO / "config/oscal-salesforce/sbs_to_sscf_mapping.yaml"
    sscf_index_path = REPO / "config/sscf_control_index.yaml"

    if not controls_path.exists():
        pytest.skip(f"SBS controls catalog not found: {controls_path}")

    _run(
        PYTHON,
        "-m",
        "skills.oscal_assess.oscal_assess",
        "assess",
        "--dry-run",
        "--env",
        "dev",
        "--out",
        str(gap_json),
    )
    _run(
        PYTHON,
        "scripts/oscal_gap_map.py",
        "--controls",
        str(controls_path),
        "--gap-analysis",
        str(gap_json),
        "--mapping",
        str(mapping_path),
        "--sscf-map",
        str(sscf_map_path),
        "--out-md",
        str(matrix_md),
        "--out-json",
        str(backlog_json),
    )

    result = _run(
        PYTHON,
        "-m",
        "skills.sscf_benchmark.sscf_benchmark",
        "benchmark",
        "--backlog",
        str(backlog_json),
        "--sscf-index",
        str(sscf_index_path),
        "--out",
        str(sscf_json),
    )
    assert result.returncode == 0, f"sscf-benchmark failed:\n{result.stderr}"
    assert sscf_json.exists(), "sscf_report.json not written"

    data = json.loads(sscf_json.read_text())
    assert "benchmark_id" in data
    assert "overall_score" in data
    assert "overall_status" in data
    assert "domains" in data
    assert data["overall_status"] in {"green", "amber", "red"}
    # SSCF v1.0 has 6 domains: CON/DSP/IAM/IPY/LOG/SEF (TDR/GOV merged into SEF in v1.0)
    assert len(data["domains"]) == 6, f"Expected 6 SSCF domains, got {len(data['domains'])}"

    # Dry-run weak org should score below threshold (0.80)
    assert data["overall_score"] < 0.80, f"Expected weak-org score < 0.80, got {data['overall_score']}"

    summary = data["summary"]
    assert "domains_green" in summary
    assert "domains_red" in summary
