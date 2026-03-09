"""Smoke tests for report-gen skill.

Exercises three output variants:
- app-owner audience Markdown (plain-language executive report)
- security audience Markdown with SSCF domain heatmap
- app-owner DOCX (validated as a real Office Open XML ZIP)

Uses the real salesforce_oscal_backlog_latest.json already in the repo.
All tests are skipped if that file is not present (matches pipeline smoke pattern).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
PYTHON = sys.executable

_BACKLOG = REPO / "docs" / "oscal-salesforce-poc" / "generated" / "salesforce_oscal_backlog_latest.json"
_SSCF_INDEX = REPO / "config" / "sscf_control_index.yaml"
_CONTROLS = REPO / "docs" / "oscal-salesforce-poc" / "generated" / "sbs_controls.json"
_MAPPING = REPO / "config" / "oscal-salesforce" / "control_mapping.yaml"
_SSCF_MAP = REPO / "config" / "oscal-salesforce" / "sbs_to_sscf_mapping.yaml"


def _run(*args: str, cwd: Path = REPO, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, cwd=cwd, check=check)


def _make_sscf_report(tmp_path: Path) -> Path:
    """Generate a fresh sscf_report.json via the pipeline for use in security audience tests."""
    gap = tmp_path / "gap.json"
    backlog = tmp_path / "backlog.json"
    matrix = tmp_path / "matrix.md"
    sscf = tmp_path / "sscf_report.json"

    _run(PYTHON, "-m", "skills.oscal_assess.oscal_assess", "assess", "--dry-run", "--env", "dev", "--out", str(gap))
    _run(
        PYTHON,
        "scripts/oscal_gap_map.py",
        "--controls",
        str(_CONTROLS),
        "--gap-analysis",
        str(gap),
        "--mapping",
        str(_MAPPING),
        "--sscf-map",
        str(_SSCF_MAP),
        "--out-md",
        str(matrix),
        "--out-json",
        str(backlog),
    )
    _run(
        PYTHON,
        "-m",
        "skills.sscf_benchmark.sscf_benchmark",
        "benchmark",
        "--backlog",
        str(backlog),
        "--sscf-index",
        str(_SSCF_INDEX),
        "--out",
        str(sscf),
    )
    return sscf


# ---------------------------------------------------------------------------
# Test 1 — app-owner Markdown
# ---------------------------------------------------------------------------


def test_app_owner_md(tmp_path: Path) -> None:
    if not _BACKLOG.exists():
        pytest.skip(f"backlog file not found: {_BACKLOG}")

    out = tmp_path / "report_app.md"
    result = _run(
        PYTHON,
        "-m",
        "skills.report_gen.report_gen",
        "generate",
        "--backlog",
        str(_BACKLOG),
        "--audience",
        "app-owner",
        "--out",
        str(out),
        "--mock-llm",
    )
    assert result.returncode == 0, f"report-gen failed:\n{result.stderr}"
    assert out.exists(), "Markdown report not written"

    content = out.read_text()
    assert "## Executive Scorecard" in content, "Missing Executive Scorecard section"
    assert "Assessed Controls" in content, "Missing Assessed Controls section"
    assert "## What Happens Next" in content, "Missing What Happens Next section"
    # Must contain at least one table row (pipe character)
    assert "|" in content, "No table found in output"


# ---------------------------------------------------------------------------
# Test 2 — security governance Markdown (with sscf_report)
# ---------------------------------------------------------------------------


def test_security_md(tmp_path: Path) -> None:
    if not _BACKLOG.exists():
        pytest.skip(f"backlog file not found: {_BACKLOG}")
    if not _CONTROLS.exists():
        pytest.skip(f"controls catalog not found: {_CONTROLS}")

    sscf_report = _make_sscf_report(tmp_path)
    out = tmp_path / "report_security.md"

    result = _run(
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
        "--sscf-benchmark",
        str(sscf_report),
        "--mock-llm",
    )
    assert result.returncode == 0, f"report-gen (security) failed:\n{result.stderr}"
    assert out.exists(), "Security Markdown report not written"

    content = out.read_text()
    assert "## Executive Scorecard" in content, "Missing Executive Scorecard section"
    assert "## Domain Posture" in content, "Missing Domain Posture section"
    # Full Control Matrix is now in the annex document
    annex = out.with_name(out.stem + "_annex.md")
    assert annex.exists(), "Annex Markdown not written"
    annex_content = annex.read_text()
    assert "## Full Control Matrix" in annex_content, "Missing Full Control Matrix in annex"
    assert "## Executive Summary" in content, "Missing Executive Summary section"
    assert "## Risk Analysis" in content, "Missing Risk Analysis section"
    # Domain chart must have real domain rows
    assert "Identity Access Management" in content or "Configuration Hardening" in content, "Expected SSCF domain data"


# ---------------------------------------------------------------------------
# Test 3 — app-owner DOCX created and non-empty
# ---------------------------------------------------------------------------


def test_docx_created(tmp_path: Path) -> None:
    if not _BACKLOG.exists():
        pytest.skip(f"backlog file not found: {_BACKLOG}")
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc not installed — DOCX conversion unavailable")

    # security audience triggers pandoc → DOCX conversion
    out = tmp_path / "report_security.md"
    result = _run(
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
    )
    assert result.returncode == 0, f"report-gen (docx) failed:\n{result.stderr}"
    docx_out = out.with_suffix(".docx")
    assert docx_out.exists(), "DOCX report not written"
    assert docx_out.stat().st_size > 0, "DOCX file is empty"
    # DOCX is a ZIP — verify magic bytes (PK header)
    header = docx_out.read_bytes()[:4]
    assert header == b"PK\x03\x04", f"Output is not a valid DOCX/ZIP: {header!r}"
