"""Tests for the four agent-dispatcher functions that call _dispatch_agent_call().

Covers: _dispatch_collector_enrich, _dispatch_assessor_analyze,
        _dispatch_workday_expert_enrich, _dispatch_security_reviewer_review,
and the underlying _dispatch_agent_call() helper itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.tools import _ARTIFACT_ROOT, _dispatch_agent_call, _validate_agent_response, dispatch, set_openai_client

_TEST_ORG = "ci-dry-run-sfdc"
_TEST_DATE = "2026-01-01"
_BASE = _ARTIFACT_ROOT / _TEST_ORG / _TEST_DATE

_OK_RESPONSE = json.dumps({"status": "ok", "agent": "test-agent", "analysis": "all clear", "flags": []})


@pytest.fixture(autouse=True)
def ensure_base_dir() -> None:
    _BASE.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def injected_client() -> MagicMock:
    """Inject a mock OpenAI client and restore None after the test."""
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = "all clear"
    mock_client.chat.completions.create.return_value.choices = [MagicMock(message=mock_msg)]
    set_openai_client(mock_client)
    yield mock_client
    set_openai_client(None)


# ---------------------------------------------------------------------------
# _dispatch_agent_call — core helper
# ---------------------------------------------------------------------------


class TestDispatchAgentCall:
    def test_no_client_returns_error(self) -> None:
        set_openai_client(None)
        result = json.loads(_dispatch_agent_call("test", "sys", "user"))
        assert result["status"] == "error"
        assert "not injected" in result["message"]

    def test_successful_call_returns_ok(self, injected_client: MagicMock) -> None:
        result = json.loads(_dispatch_agent_call("test-agent", "sys prompt", "user content"))
        assert result["status"] == "ok"
        assert result["agent"] == "test-agent"
        assert "analysis" in result
        assert isinstance(result["flags"], list)

    def test_flags_extracted_from_response(self, injected_client: MagicMock) -> None:
        # Use a non-strict agent so FLAG: scraping fallback is exercised (strict agents fail-closed).
        injected_client.chat.completions.create.return_value.choices[
            0
        ].message.content = "Some analysis.\nFLAG: missing_scope:event-monitoring\nFLAG: stale_evidence:SBS-LOG-001"
        result = json.loads(_dispatch_agent_call("reporter", "sys", "user"))
        assert result["flags"] == ["missing_scope:event-monitoring", "stale_evidence:SBS-LOG-001"]

    def test_exception_returns_structured_error(self, injected_client: MagicMock) -> None:
        injected_client.chat.completions.create.side_effect = RuntimeError("API down")
        result = json.loads(_dispatch_agent_call("test", "sys", "user"))
        assert result["status"] == "error"
        assert "API down" in result["message"]
        assert result["flags"] == []

    def test_uses_llm_model_analyst_env_var(self, injected_client: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_MODEL_ANALYST", "custom-model-xyz")
        _dispatch_agent_call("test", "sys", "user")
        call_kwargs = injected_client.chat.completions.create.call_args
        model_used = call_kwargs.kwargs.get("model") or call_kwargs[1].get("model")
        assert model_used == "custom-model-xyz"


# ---------------------------------------------------------------------------
# collector_enrich
# ---------------------------------------------------------------------------


class TestDispatchCollectorEnrich:
    def test_missing_collector_output_returns_error(self) -> None:
        result = json.loads(dispatch("collector_enrich", {"org": _TEST_ORG}))
        assert result["status"] == "error"
        assert "collector_output" in result["message"]

    def test_traversal_path_raises(self) -> None:
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            dispatch("collector_enrich", {"org": _TEST_ORG, "collector_output": "/etc/passwd"})

    def test_file_not_found_returns_error(self) -> None:
        valid_path = str(_BASE / "nonexistent_collector.json")
        result = json.loads(dispatch("collector_enrich", {"org": _TEST_ORG, "collector_output": valid_path}))
        assert result["status"] == "error"
        assert "Could not read" in result["message"]

    def test_valid_file_calls_agent_and_returns_ok(self) -> None:
        coll_path = _BASE / "sfdc_raw.json"
        coll_path.write_text(json.dumps({"status": "ok", "controls": []}))
        with patch("harness.tools._dispatch_agent_call", return_value=_OK_RESPONSE) as mock_call:
            result = json.loads(dispatch("collector_enrich", {"org": _TEST_ORG, "collector_output": str(coll_path)}))
        assert result["status"] == "ok"
        mock_call.assert_called_once()
        assert mock_call.call_args[0][0] == "collector"

    def test_workday_platform_appears_in_user_content(self) -> None:
        coll_path = _BASE / "sfdc_raw.json"
        coll_path.write_text(json.dumps({"platform": "workday"}))
        with patch("harness.tools._dispatch_agent_call", return_value=_OK_RESPONSE) as mock_call:
            dispatch(
                "collector_enrich",
                {"org": _TEST_ORG, "collector_output": str(coll_path), "platform": "workday"},
            )
        _, _, user_content = mock_call.call_args[0]
        assert "workday" in user_content

    def test_returns_flags_from_agent_response(self) -> None:
        coll_path = _BASE / "sfdc_raw.json"
        coll_path.write_text("{}")
        flag_response = json.dumps(
            {"status": "ok", "agent": "collector", "analysis": "", "flags": ["missing_scope:event-monitoring"]}
        )
        with patch("harness.tools._dispatch_agent_call", return_value=flag_response):
            result = json.loads(dispatch("collector_enrich", {"org": _TEST_ORG, "collector_output": str(coll_path)}))
        assert result["flags"] == ["missing_scope:event-monitoring"]


# ---------------------------------------------------------------------------
# assessor_analyze
# ---------------------------------------------------------------------------


class TestDispatchAssessorAnalyze:
    def test_missing_gap_analysis_returns_error(self) -> None:
        result = json.loads(dispatch("assessor_analyze", {"org": _TEST_ORG}))
        assert result["status"] == "error"

    def test_traversal_path_raises(self) -> None:
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            dispatch("assessor_analyze", {"org": _TEST_ORG, "gap_analysis": "/etc/shadow"})

    def test_invalid_json_returns_error(self) -> None:
        gap_path = _BASE / "gap_analysis_bad.json"
        gap_path.write_text("NOT JSON")
        result = json.loads(dispatch("assessor_analyze", {"org": _TEST_ORG, "gap_analysis": str(gap_path)}))
        assert result["status"] == "error"
        assert "gap_analysis" in result["message"]

    def test_valid_findings_calls_agent(self) -> None:
        gap_data = {
            "findings": [
                {
                    "control_id": "SBS-AUTH-001",
                    "status": "fail",
                    "severity": "critical",
                    "needs_expert_review": True,
                    "data_source": "soql",
                    "mapping_confidence": "low",
                }
            ]
        }
        gap_path = _BASE / "gap_analysis.json"
        gap_path.write_text(json.dumps(gap_data))
        with patch("harness.tools._dispatch_agent_call", return_value=_OK_RESPONSE) as mock_call:
            result = json.loads(dispatch("assessor_analyze", {"org": _TEST_ORG, "gap_analysis": str(gap_path)}))
        assert result["status"] == "ok"
        mock_call.assert_called_once()
        _, _, user_content = mock_call.call_args[0]
        assert "SBS-AUTH-001" in user_content

    def test_workday_platform_label_in_content(self) -> None:
        gap_path = _BASE / "gap_analysis.json"
        gap_path.write_text(json.dumps({"findings": []}))
        with patch("harness.tools._dispatch_agent_call", return_value=_OK_RESPONSE) as mock_call:
            dispatch("assessor_analyze", {"org": _TEST_ORG, "gap_analysis": str(gap_path), "platform": "workday"})
        _, _, user_content = mock_call.call_args[0]
        assert "workday" in user_content

    def test_empty_findings_list_still_calls_agent(self) -> None:
        gap_path = _BASE / "gap_analysis.json"
        gap_path.write_text(json.dumps({"findings": []}))
        with patch("harness.tools._dispatch_agent_call", return_value=_OK_RESPONSE) as mock_call:
            result = json.loads(dispatch("assessor_analyze", {"org": _TEST_ORG, "gap_analysis": str(gap_path)}))
        assert result["status"] == "ok"
        mock_call.assert_called_once()


# ---------------------------------------------------------------------------
# workday_expert_enrich
# ---------------------------------------------------------------------------


class TestDispatchWorkdayExpertEnrich:
    def test_missing_gap_analysis_returns_error(self) -> None:
        result = json.loads(dispatch("workday_expert_enrich", {"org": _TEST_ORG, "gap_analysis": ""}))
        assert result["status"] == "error"

    def test_nonexistent_file_returns_error(self) -> None:
        result = json.loads(
            dispatch("workday_expert_enrich", {"org": _TEST_ORG, "gap_analysis": "/nonexistent/wd_gap.json"})
        )
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_no_eligible_findings_skips_agent(self, tmp_path: Path) -> None:
        gap_data = {
            "findings": [
                {"control_id": "WD-IAM-001", "status": "pass", "needs_expert_review": False, "data_source": "rest"}
            ]
        }
        gap_path = tmp_path / "gap_analysis.json"
        gap_path.write_text(json.dumps(gap_data))
        with patch("harness.tools._dispatch_agent_call") as mock_call:
            result = json.loads(dispatch("workday_expert_enrich", {"org": _TEST_ORG, "gap_analysis": str(gap_path)}))
        mock_call.assert_not_called()
        assert result["status"] == "ok"
        assert result["enriched_findings"] == 0

    def test_needs_expert_review_findings_are_eligible(self, tmp_path: Path) -> None:
        gap_data = {
            "findings": [
                {"control_id": "WD-IAM-001", "status": "fail", "needs_expert_review": True, "data_source": "rest"},
                {"control_id": "WD-IAM-002", "status": "pass", "needs_expert_review": False, "data_source": "rest"},
            ]
        }
        gap_path = tmp_path / "gap_analysis.json"
        gap_path.write_text(json.dumps(gap_data))
        agent_response = json.dumps(
            {"status": "ok", "agent": "workday-expert", "analysis": "Expert guidance here.", "flags": []}
        )
        with patch("harness.tools._dispatch_agent_call", return_value=agent_response):
            result = json.loads(dispatch("workday_expert_enrich", {"org": _TEST_ORG, "gap_analysis": str(gap_path)}))
        assert result["status"] == "ok"
        assert result["enriched_findings"] == 1
        updated = json.loads(gap_path.read_text())
        assert updated["findings"][0]["expert_notes"].startswith("[workday-expert]")

    def test_permission_denied_data_source_is_eligible(self, tmp_path: Path) -> None:
        gap_data = {
            "findings": [
                {
                    "control_id": "WD-ACS-003",
                    "status": "fail",
                    "needs_expert_review": False,
                    "data_source": "permission_denied",
                }
            ]
        }
        gap_path = tmp_path / "gap_analysis.json"
        gap_path.write_text(json.dumps(gap_data))
        agent_response = json.dumps(
            {"status": "ok", "agent": "workday-expert", "analysis": "Fix: ISSG grant.", "flags": []}
        )
        with patch("harness.tools._dispatch_agent_call", return_value=agent_response):
            result = json.loads(dispatch("workday_expert_enrich", {"org": _TEST_ORG, "gap_analysis": str(gap_path)}))
        assert result["enriched_findings"] == 1

    def test_expert_notes_not_overwritten_if_already_set(self, tmp_path: Path) -> None:
        existing_note = "Manual review completed."
        gap_data = {
            "findings": [
                {
                    "control_id": "WD-IAM-001",
                    "needs_expert_review": True,
                    "data_source": "rest",
                    "expert_notes": existing_note,
                }
            ]
        }
        gap_path = tmp_path / "gap_analysis.json"
        gap_path.write_text(json.dumps(gap_data))
        agent_response = json.dumps(
            {"status": "ok", "agent": "workday-expert", "analysis": "New guidance.", "flags": []}
        )
        with patch("harness.tools._dispatch_agent_call", return_value=agent_response):
            dispatch("workday_expert_enrich", {"org": _TEST_ORG, "gap_analysis": str(gap_path)})
        updated = json.loads(gap_path.read_text())
        assert updated["findings"][0]["expert_notes"] == existing_note

    def test_invalid_json_in_file_returns_error(self, tmp_path: Path) -> None:
        gap_path = tmp_path / "gap_analysis.json"
        gap_path.write_text("INVALID JSON")
        result = json.loads(dispatch("workday_expert_enrich", {"org": _TEST_ORG, "gap_analysis": str(gap_path)}))
        assert result["status"] == "error"
        assert "Could not read" in result["message"]


# ---------------------------------------------------------------------------
# security_reviewer_review
# ---------------------------------------------------------------------------


class TestDispatchSecurityReviewerReview:
    def test_missing_report_path_returns_error(self) -> None:
        result = json.loads(dispatch("security_reviewer_review", {"org": _TEST_ORG}))
        assert result["status"] == "error"
        assert "report_path" in result["message"]

    def test_traversal_path_raises(self) -> None:
        with pytest.raises(ValueError, match="outside the allowed artifact root"):
            dispatch("security_reviewer_review", {"org": _TEST_ORG, "report_path": "/etc/passwd"})

    def test_file_not_found_returns_error(self) -> None:
        valid_path = str(_BASE / "nonexistent_report.md")
        result = json.loads(dispatch("security_reviewer_review", {"org": _TEST_ORG, "report_path": valid_path}))
        assert result["status"] == "error"
        assert "Could not read" in result["message"]

    def test_valid_report_calls_security_reviewer_agent(self) -> None:
        report_path = _BASE / "security_report.md"
        report_path.write_text("# Security Report\n\nAll controls assessed.")
        with patch("harness.tools._dispatch_agent_call", return_value=_OK_RESPONSE) as mock_call:
            result = json.loads(
                dispatch("security_reviewer_review", {"org": _TEST_ORG, "report_path": str(report_path)})
            )
        assert result["status"] == "ok"
        mock_call.assert_called_once()
        assert mock_call.call_args[0][0] == "delivery-reviewer"

    def test_report_content_truncated_to_6000_chars(self) -> None:
        report_path = _BASE / "security_report.md"
        report_path.write_text("X" * 10000)
        captured: list[str] = []

        def capture(*args: object) -> str:
            captured.append(str(args[2]))
            return _OK_RESPONSE

        with patch("harness.tools._dispatch_agent_call", side_effect=capture):
            dispatch("security_reviewer_review", {"org": _TEST_ORG, "report_path": str(report_path)})
        assert "X" * 6000 in captured[0]
        assert "X" * 6001 not in captured[0]

    def test_flags_returned_from_agent_response(self) -> None:
        report_path = _BASE / "security_report.md"
        report_path.write_text("# Report")
        flag_response = json.dumps(
            {
                "status": "ok",
                "agent": "security-reviewer",
                "analysis": "FLAG: credential_exposure:org-id-12345",
                "flags": ["credential_exposure:org-id-12345"],
            }
        )
        with patch("harness.tools._dispatch_agent_call", return_value=flag_response):
            result = json.loads(
                dispatch("security_reviewer_review", {"org": _TEST_ORG, "report_path": str(report_path)})
            )
        assert result["flags"] == ["credential_exposure:org-id-12345"]


# ---------------------------------------------------------------------------
# PATCH 4 — _validate_agent_response structured output tests
# ---------------------------------------------------------------------------


class TestValidateAgentResponse:
    def test_structured_json_response_used_directly(self) -> None:
        """Valid JSON with all 6 required fields is used directly without FLAG: scraping."""
        payload = json.dumps(
            {
                "status": "ok",
                "agent": "delivery-reviewer",
                "analysis": "No issues found.",
                "flags": ["scope_violation:section-x"],
                "summary": "Report is clean.",
                "severity": "critical",
            }
        )
        result = _validate_agent_response(payload, "delivery-reviewer")
        assert result["status"] == "ok"
        assert result["flags"] == ["scope_violation:section-x"]
        assert result["analysis"] == "No issues found."

    def test_malformed_json_non_strict_falls_back_to_flag_scraping(self) -> None:
        """Non-JSON free-text response falls back to FLAG: scraping for non-strict agents."""
        raw = "Some analysis text.\nFLAG: missing_scope:event-monitoring\nEnd of review."
        result = _validate_agent_response(raw, "reporter")  # non-strict agent
        assert result["status"] == "ok"
        assert result["flags"] == ["missing_scope:event-monitoring"]
        assert result["analysis"] == raw

    def test_strict_agent_non_json_returns_error_not_ok(self) -> None:
        """Non-JSON response from collector (strict agent) returns error, not ok."""
        raw = "Some analysis text.\nFLAG: missing_scope:event-monitoring\nEnd of review."
        result = _validate_agent_response(raw, "collector")
        assert result["status"] == "error"
        assert result["severity"] == "critical"
        assert any("parse_failure" in f for f in result["flags"])

    def test_missing_fields_filled_with_defaults_non_strict(self) -> None:
        """Partial JSON (missing flags/status) gets defaults filled in for non-strict agents."""
        partial = json.dumps({"agent": "reporter", "analysis": "FLAG: low_confidence_critical:SBS-AUTH-001"})
        result = _validate_agent_response(partial, "reporter")
        assert "status" in result
        assert "flags" in result
        # flags should be extracted from analysis text since they were missing in JSON
        assert "low_confidence_critical:SBS-AUTH-001" in result["flags"]

    def test_missing_required_fields_strict_agent_returns_error(self) -> None:
        """JSON missing 'analysis' field on strict agent (assessor) returns error."""
        partial = json.dumps({"status": "ok", "agent": "assessor"})
        result = _validate_agent_response(partial, "assessor")
        assert result["status"] == "error"
        assert result["severity"] == "critical"

    # --- Fail-closed regression tests (FIX 1+2) ---

    def test_delivery_reviewer_nonjson_returns_block(self) -> None:
        """Non-JSON response from delivery-reviewer must return status=block, not ok."""
        raw = "The report looks fine, no issues detected, all controls are green."
        result = _validate_agent_response(raw, "delivery-reviewer")
        assert result["status"] == "block"
        assert any("parse_failure" in f for f in result["flags"])
        assert result["severity"] == "critical"

    def test_strict_agent_nonjson_returns_error_with_critical_severity(self) -> None:
        """Non-JSON response from a strict agent (collector) returns status=error with critical severity."""
        raw = "I collected the Salesforce configuration but could not format as JSON."
        result = _validate_agent_response(raw, "collector")
        assert result["status"] == "error"
        assert result["severity"] == "critical"
        assert any("parse_failure" in f for f in result["flags"])

    def test_valid_block_status_parses_cleanly(self) -> None:
        """Valid JSON with status=block parses without error — block is a valid status value."""
        payload = json.dumps(
            {
                "status": "block",
                "agent": "delivery-reviewer",
                "analysis": "Credential exposure detected in executive summary section.",
                "flags": ["FLAG:credential_exposure:org-id-in-title"],
                "summary": "Report blocked due to credential exposure.",
                "severity": "critical",
            }
        )
        result = _validate_agent_response(payload, "delivery-reviewer")
        assert result["status"] == "block"
        assert result["severity"] == "critical"

    def test_strict_agent_missing_analysis_field_returns_error(self) -> None:
        """JSON with only status+agent (missing analysis) on strict agent returns error."""
        payload = json.dumps({"status": "ok", "agent": "assessor"})
        result = _validate_agent_response(payload, "assessor")
        assert result["status"] == "error"
        assert result["severity"] == "critical"

    def test_assessor_non_json_returns_error_not_ok(self) -> None:
        """Non-JSON response from assessor (strict agent) returns error status."""
        result = _validate_agent_response("prose analysis without json", "assessor")
        assert result["status"] == "error"
        assert result["severity"] == "critical"

    def test_sfdc_expert_nonjson_returns_error(self) -> None:
        """Non-JSON response from sfdc-expert (strict agent) returns status=error."""
        result = _validate_agent_response("Here are the Apex script suggestions...", "sfdc-expert")
        assert result["status"] == "error"
        assert result["severity"] == "critical"

    def test_workday_expert_nonjson_returns_error(self) -> None:
        """Non-JSON response from workday-expert (strict agent) returns status=error."""
        result = _validate_agent_response("Workday configuration review complete.", "workday-expert")
        assert result["status"] == "error"
        assert result["severity"] == "critical"

    # --- FIX 1: full strict-agent 6-field schema enforcement ---

    def test_delivery_reviewer_missing_flags_returns_block(self) -> None:
        """JSON response for delivery-reviewer missing 'flags' field → status=block."""
        payload = json.dumps(
            {
                "status": "ok",
                "agent": "delivery-reviewer",
                "analysis": "No issues.",
                "summary": "Clean report.",
                "severity": "info",
                # 'flags' intentionally omitted
            }
        )
        result = _validate_agent_response(payload, "delivery-reviewer")
        assert result["status"] == "block"
        assert any("flags" in f for f in result["flags"])
        assert result["severity"] == "critical"

    def test_delivery_reviewer_missing_summary_returns_block(self) -> None:
        """JSON response for delivery-reviewer missing 'summary' field → status=block."""
        payload = json.dumps(
            {
                "status": "ok",
                "agent": "delivery-reviewer",
                "analysis": "No issues.",
                "flags": [],
                "severity": "info",
                # 'summary' intentionally omitted
            }
        )
        result = _validate_agent_response(payload, "delivery-reviewer")
        assert result["status"] == "block"
        assert any("summary" in f for f in result["flags"])
        assert result["severity"] == "critical"

    def test_strict_agent_missing_severity_returns_error(self) -> None:
        """JSON response for collector (strict) missing 'severity' → status=error."""
        payload = json.dumps(
            {
                "status": "ok",
                "agent": "collector",
                "analysis": "Collection complete.",
                "flags": [],
                "summary": "All controls collected.",
                # 'severity' intentionally omitted
            }
        )
        result = _validate_agent_response(payload, "collector")
        assert result["status"] == "error"
        assert result["severity"] == "critical"

    def test_strict_agent_invalid_severity_returns_error(self) -> None:
        """JSON response with severity='high' (not in info|warning|critical) → status=error."""
        payload = json.dumps(
            {
                "status": "ok",
                "agent": "collector",
                "analysis": "Collection complete.",
                "flags": [],
                "summary": "All controls collected.",
                "severity": "high",  # invalid — must be info|warning|critical
            }
        )
        result = _validate_agent_response(payload, "collector")
        assert result["status"] == "error"
        assert any("severity" in f for f in result["flags"])
        assert result["severity"] == "critical"

    def test_strict_agent_non_list_flags_returns_error(self) -> None:
        """JSON response with flags='none' (string, not list) → status=error."""
        payload = json.dumps(
            {
                "status": "ok",
                "agent": "assessor",
                "analysis": "Assessment complete.",
                "flags": "none",  # invalid — must be a list
                "summary": "All controls assessed.",
                "severity": "info",
            }
        )
        result = _validate_agent_response(payload, "assessor")
        assert result["status"] == "error"
        assert any("flags" in f for f in result["flags"])
        assert result["severity"] == "critical"


# ---------------------------------------------------------------------------
# PATCH 1 — finish() blocked on security_review_flags
# ---------------------------------------------------------------------------


class TestFinishBlockedOnSecurityReviewFlags:
    """Tests for the finish() sequencing gate against security_review_flags."""

    def _make_state_with_flags(self, flags: list[str]) -> None:
        """Helper: inject flags into harness.tools module state via loop.py path.

        The _dispatch_finish function in tools.py reads flags from the input dict
        (passed by loop.py which extracts them from state). We test the dispatch
        path directly by passing flags in the tool input.
        """

    def test_finish_blocked_on_credential_exposure_flag(self) -> None:
        """finish() returns status=blocked when credential_exposure flag is present."""
        result = json.loads(
            dispatch(
                "finish",
                {
                    "org": _TEST_ORG,
                    "summary": "Assessment complete.",
                    "security_review_flags": ["credential_exposure:org-id-123"],
                },
            )
        )
        assert result["status"] == "blocked"
        assert "credential_exposure:org-id-123" in result["flags"]

    def test_finish_blocked_on_scope_violation_flag(self) -> None:
        """finish() returns status=blocked when scope_violation flag is present."""
        result = json.loads(
            dispatch(
                "finish",
                {
                    "org": _TEST_ORG,
                    "summary": "Assessment complete.",
                    "security_review_flags": ["scope_violation:executive-summary"],
                },
            )
        )
        assert result["status"] == "blocked"
        assert "scope_violation:executive-summary" in result["flags"]

    def test_finish_allowed_when_only_status_misrepresentation_flag(self) -> None:
        """status_misrepresentation flags are warning-only — must not block finish()."""
        result = json.loads(
            dispatch(
                "finish",
                {
                    "org": _TEST_ORG,
                    "summary": "Assessment complete.",
                    "security_review_flags": ["status_misrepresentation:SBS-AUTH-001"],
                },
            )
        )
        assert result["status"] == "ok"
        assert result["pipeline_complete"] is True

    def test_finish_allowed_when_no_security_review_flags(self) -> None:
        """Normal path: no flags means finish() proceeds."""
        result = json.loads(
            dispatch(
                "finish",
                {
                    "org": _TEST_ORG,
                    "summary": "Assessment complete.",
                    "security_review_flags": [],
                },
            )
        )
        assert result["status"] == "ok"
        assert result["pipeline_complete"] is True


# ---------------------------------------------------------------------------
# PATCH 6 — expert agent per-finding enrichment
# ---------------------------------------------------------------------------


class TestWorkdayExpertDifferentiatedNotes:
    def test_workday_expert_produces_differentiated_notes_per_finding(self) -> None:
        """Two eligible findings should each get expert_notes written."""
        gap = {
            "findings": [
                {
                    "control_id": "WD-IAM-001",
                    "status": "fail",
                    "severity": "critical",
                    "needs_expert_review": True,
                    "observed_value": "no data",
                    "evidence_ref": "",
                },
                {
                    "control_id": "WD-LOG-002",
                    "status": "partial",
                    "severity": "high",
                    "needs_expert_review": True,
                    "observed_value": "partial logs",
                    "evidence_ref": "",
                },
            ]
        }
        gap_path = _BASE / "gap_analysis_wd_expert.json"
        gap_path.write_text(json.dumps(gap))

        # Return a response that includes per-finding sections
        per_finding_response = json.dumps(
            {
                "status": "ok",
                "agent": "workday-expert",
                "analysis": (
                    "Control: WD-IAM-001\nGap: Missing IAM grant\nFix: ISSG domain\nAPI: /raas/iam\n\n"
                    "Control: WD-LOG-002\nGap: Partial log coverage\nFix: Enable audit log RaaS\nAPI: /raas/logs"
                ),
                "flags": [],
            }
        )
        with patch("harness.tools._dispatch_agent_call", return_value=per_finding_response):
            result = json.loads(dispatch("workday_expert_enrich", {"org": _TEST_ORG, "gap_analysis": str(gap_path)}))
        assert result["status"] == "ok"
        assert result["enriched_findings"] == 2
        updated = json.loads(gap_path.read_text())
        for finding in updated["findings"]:
            assert "expert_notes" in finding, f"expert_notes missing on {finding['control_id']}"


class TestSfdcExpertWritesExpertNotes:
    def test_sfdc_expert_writes_expert_notes_to_findings(self) -> None:
        """sfdc_expert_enrich must write expert_notes to each eligible finding."""
        gap = {
            "findings": [
                {
                    "control_id": "SBS-AUTH-001",
                    "status": "fail",
                    "severity": "critical",
                    "needs_expert_review": True,
                },
                {
                    "control_id": "SBS-ACS-005",
                    "status": "partial",
                    "severity": "high",
                    "needs_expert_review": True,
                },
                {
                    "control_id": "SBS-LOG-001",
                    "status": "pass",
                    "severity": "medium",
                    "needs_expert_review": False,
                },
            ]
        }
        gap_path = _BASE / "gap_analysis_sfdc_expert.json"
        gap_path.write_text(json.dumps(gap))

        result = json.loads(dispatch("sfdc_expert_enrich", {"org": _TEST_ORG, "gap_analysis": str(gap_path)}))
        assert result["status"] == "ok"
        assert result["enriched_findings"] == 2
        updated = json.loads(gap_path.read_text())
        enriched = [f for f in updated["findings"] if f.get("needs_expert_review")]
        for finding in enriched:
            assert "expert_notes" in finding, f"expert_notes missing on {finding['control_id']}"
        # Non-eligible finding should NOT have expert_notes
        pass_finding = next(f for f in updated["findings"] if f["control_id"] == "SBS-LOG-001")
        assert "expert_notes" not in pass_finding
