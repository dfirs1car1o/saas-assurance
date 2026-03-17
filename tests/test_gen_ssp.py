"""Tests for scripts/gen_ssp.py — NIST verdict parsing and fail-closed handling."""

from __future__ import annotations

from scripts.gen_ssp import build_ssp


def _minimal_sscf() -> dict:
    return {"overall_score": 0.75, "overall_status": "amber"}


def _minimal_backlog() -> dict:
    return {
        "assessment_id": "test-ssp-001",
        "org": "test-org",
        "platform": "salesforce",
        "mapped_items": [],
    }


class TestGenSspNistVerdict:
    def test_reads_nist_verdict_from_nist_ai_rmf_review(self) -> None:
        """SSP build_ssp reads overall from nist_ai_rmf_review wrapper correctly."""
        nist_review = {
            "nist_ai_rmf_review": {
                "assessment_id": "test-ssp-001",
                "reviewed_at_utc": "2026-01-01T00:00:00+00:00",
                "reviewer": "nist-reviewer",
                "govern": {"status": "pass", "notes": "ok"},
                "map": {"status": "pass", "notes": "ok"},
                "measure": {"status": "pass", "notes": "ok"},
                "manage": {"status": "pass", "notes": "ok"},
                "overall": "pass",
                "blocking_issues": [],
                "recommendations": [],
            }
        }
        ssp = build_ssp(
            sscf_report=_minimal_sscf(),
            backlog=_minimal_backlog(),
            nist_review=nist_review,
            org="test-org",
            platform="salesforce",
        )
        root = ssp["system-security-plan"]
        props = {p["name"]: p["value"] for p in root["system-characteristics"].get("props", [])}
        assert props.get("nist-ai-rmf-verdict") == "pass"

    def test_handles_fail_closed_verdict_without_exception(self) -> None:
        """SSP build_ssp handles fail-closed nist_ai_rmf_review shape without error."""
        nist_review = {
            "nist_ai_rmf_review": {
                "assessment_id": "test-ssp-002",
                "reviewed_at_utc": "2026-01-01T00:00:00+00:00",
                "reviewer": "nist-reviewer",
                "govern": {"status": "BLOCK", "notes": "Structured parse failure — verdict is unverified."},
                "map": {"status": "BLOCK", "notes": "Structured parse failure — verdict is unverified."},
                "measure": {"status": "BLOCK", "notes": "Structured parse failure — verdict is unverified."},
                "manage": {"status": "BLOCK", "notes": "Structured parse failure — verdict is unverified."},
                "overall": "block",
                "blocking_issues": [
                    "Structured parse failure — nist_review output must be treated as unverified. Do not distribute."
                ],
                "recommendations": [
                    "REVIEW REQUIRED: nist_review failed to parse structured output. "
                    "Rerun assessment and inspect raw model output."
                ],
                "parser_mode": "fail_closed",
            }
        }
        # Must not raise
        ssp = build_ssp(
            sscf_report=_minimal_sscf(),
            backlog=_minimal_backlog(),
            nist_review=nist_review,
            org="test-org",
            platform="salesforce",
        )
        root = ssp["system-security-plan"]
        props = {p["name"]: p["value"] for p in root["system-characteristics"].get("props", [])}
        assert props.get("nist-ai-rmf-verdict") == "block"

    def test_falls_back_to_flag_when_nist_review_is_empty(self) -> None:
        """SSP build_ssp defaults to 'flag' when nist_review has no recognisable fields."""
        nist_review: dict = {}
        ssp = build_ssp(
            sscf_report=_minimal_sscf(),
            backlog=_minimal_backlog(),
            nist_review=nist_review,
            org="test-org",
            platform="salesforce",
        )
        root = ssp["system-security-plan"]
        props = {p["name"]: p["value"] for p in root["system-characteristics"].get("props", [])}
        assert props.get("nist-ai-rmf-verdict") == "flag"

    def test_stale_overall_verdict_field_still_accepted(self) -> None:
        """SSP build_ssp accepts legacy overall_verdict fallback for backward compat."""
        nist_review = {"overall_verdict": "pass"}
        ssp = build_ssp(
            sscf_report=_minimal_sscf(),
            backlog=_minimal_backlog(),
            nist_review=nist_review,
            org="test-org",
            platform="salesforce",
        )
        root = ssp["system-security-plan"]
        props = {p["name"]: p["value"] for p in root["system-characteristics"].get("props", [])}
        assert props.get("nist-ai-rmf-verdict") == "pass"
