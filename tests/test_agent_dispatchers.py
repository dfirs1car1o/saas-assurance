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

from harness.tools import _ARTIFACT_ROOT, _dispatch_agent_call, dispatch, set_openai_client

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
        injected_client.chat.completions.create.return_value.choices[
            0
        ].message.content = "Some analysis.\nFLAG: missing_scope:event-monitoring\nFLAG: stale_evidence:SBS-LOG-001"
        result = json.loads(_dispatch_agent_call("collector", "sys", "user"))
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
        assert mock_call.call_args[0][0] == "security-reviewer"

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
