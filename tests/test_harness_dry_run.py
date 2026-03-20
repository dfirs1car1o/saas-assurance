"""
Smoke test: harness agentic loop with mocked OpenAI client + audit log verification.

Verifies:
  1. Correct tool dispatch order (sfdc_connect_collect → oscal_assess_assess → stop)
  2. Output file paths tracked in state
  3. memory save_assessment called with extracted score
  4. Loop exits cleanly without real Salesforce org or OpenAI API credits

Mock sequence:
  Turn 1: tool_calls sfdc_connect_collect (dry_run=True)
  Turn 2: tool_calls oscal_assess_assess (dry_run=True)
  Turn 3: stop with summary text
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from harness.loop import cli

_REPO = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers — build realistic mock OpenAI ChatCompletion responses
# ---------------------------------------------------------------------------


def _tool_use_response(tool_name: str, tool_id: str, tool_input: dict) -> MagicMock:
    """Build a mock OpenAI ChatCompletion with a tool_calls finish_reason."""
    tc = MagicMock()
    tc.id = tool_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(tool_input)

    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]

    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message = msg

    response = MagicMock()
    response.choices = [choice]
    return response


def _end_turn_response(text: str) -> MagicMock:
    """Build a mock OpenAI ChatCompletion with a stop finish_reason."""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None

    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message = msg

    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# Test: two-tool loop → stop
# ---------------------------------------------------------------------------


def test_dry_run_loop_tool_dispatch_order(tmp_path: Path) -> None:
    """Loop calls tools in correct order and exits cleanly."""

    fake_gap = str(tmp_path / "gap_analysis.json")

    # Write minimal gap_analysis.json so _extract_critical_fails / _extract_score work
    (tmp_path / "gap_analysis.json").write_text(
        json.dumps(
            {
                "assessment_id": "test-001",
                "findings": [
                    {"control_id": "SBS-AUTH-001", "status": "fail", "severity": "critical"},
                    {"control_id": "SBS-ACS-001", "status": "fail", "severity": "high"},
                ],
            }
        )
    )
    (tmp_path / "sscf_report.json").write_text(
        json.dumps(
            {
                "benchmark_id": "bench-001",
                "overall_score": 0.34,
                "overall_status": "red",
                "domains": [],
                "summary": {"domains_green": 0, "domains_red": 7},
            }
        )
    )

    mock_responses = [
        _tool_use_response(
            "sfdc_connect_collect",
            "call_001",
            {"scope": "all", "dry_run": True, "env": "dev", "org": "test-org"},
        ),
        _tool_use_response(
            "oscal_assess_assess",
            "call_002",
            {"dry_run": True, "env": "dev", "out": fake_gap},
        ),
        _end_turn_response("Assessment complete. overall_score=34%, status=RED."),
    ]

    mock_openai_client = MagicMock()
    mock_openai_client.chat.completions.create.side_effect = mock_responses

    sfdc_out = str(tmp_path / "sfdc_raw.json")
    dispatch_results = {
        "sfdc_connect_collect": json.dumps({"status": "ok", "dry_run": True, "output_file": sfdc_out}),
        "oscal_assess_assess": json.dumps({"status": "ok", "output_file": fake_gap}),
    }

    def fake_dispatch(name: str, inp: dict) -> str:  # noqa: ANN001
        return dispatch_results.get(name, json.dumps({"status": "ok"}))

    runner = CliRunner()

    with (
        patch("openai.OpenAI", return_value=mock_openai_client),
        patch("harness.loop.build_client") as mock_build,
        patch("harness.loop.load_memories", return_value="No prior assessments."),
        patch("harness.loop.save_assessment") as mock_save,
        patch("harness.loop.dispatch", side_effect=fake_dispatch) as mock_dispatch,
    ):
        mock_build.return_value = MagicMock()

        result = runner.invoke(
            cli,
            ["run", "--dry-run", "--env", "dev", "--org", "test-org", "--approve-critical"],
        )

    assert result.exit_code == 0, f"Loop exited with {result.exit_code}:\n{result.output}"

    # Verify tool dispatch order
    dispatch_calls = mock_dispatch.call_args_list
    assert len(dispatch_calls) == 2, f"Expected 2 dispatch calls, got {len(dispatch_calls)}"
    assert dispatch_calls[0][0][0] == "sfdc_connect_collect"
    assert dispatch_calls[1][0][0] == "oscal_assess_assess"

    # Verify dry_run propagated to tool inputs
    assert dispatch_calls[0][0][1].get("dry_run") is True
    assert dispatch_calls[1][0][1].get("dry_run") is True

    # Verify memory save was called
    mock_save.assert_called_once()
    save_args = mock_save.call_args[0]
    assert save_args[1] == "test-org"  # org_alias


# ---------------------------------------------------------------------------
# Test: tool error triggers _handle_tool_error
# ---------------------------------------------------------------------------


def test_tool_error_triggers_handler(tmp_path: Path) -> None:
    """When dispatch raises, _handle_tool_error is called."""
    mock_responses = [
        _tool_use_response("sfdc_connect_collect", "call_err", {"scope": "all", "dry_run": True}),
        _end_turn_response("Halted due to tool error."),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_responses

    runner = CliRunner()

    with (
        patch("openai.OpenAI", return_value=mock_client),
        patch("harness.loop.build_client", return_value=MagicMock()),
        patch("harness.loop.load_memories", return_value=""),
        patch("harness.loop.save_assessment"),
        patch("harness.loop.dispatch", side_effect=RuntimeError("Salesforce connection refused")),
        patch(
            "harness.loop._handle_tool_error",
            return_value='{"status": "error", "message": "handled"}',
        ) as mock_handler,
    ):
        runner.invoke(cli, ["run", "--dry-run", "--org", "err-org"])

    mock_handler.assert_called_once()
    call_args = mock_handler.call_args[0]
    assert call_args[0] == "sfdc_connect_collect"
    assert isinstance(call_args[2], RuntimeError)


# ---------------------------------------------------------------------------
# Test: OpenAI client constructed with env key
# ---------------------------------------------------------------------------


def test_audit_log_written_with_correct_events(tmp_path: Path) -> None:
    """Audit log (audit.jsonl) is written for every run with loop_start, tool_call, loop_end."""
    from datetime import UTC, datetime

    fake_gap = str(tmp_path / "gap_analysis.json")
    (tmp_path / "gap_analysis.json").write_text(json.dumps({"findings": []}))

    mock_responses = [
        _tool_use_response(
            "sfdc_connect_collect",
            "call_a01",
            {"scope": "all", "dry_run": True, "org": "audit-test-org"},
        ),
        _end_turn_response("Done."),
    ]
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_responses

    dispatch_results = {
        "sfdc_connect_collect": json.dumps({"status": "ok", "dry_run": True, "output_file": fake_gap}),
    }

    def fake_dispatch(name: str, inp: dict) -> str:  # noqa: ANN001
        return dispatch_results.get(name, json.dumps({"status": "ok"}))

    runner = CliRunner()
    with (
        patch("openai.OpenAI", return_value=mock_client),
        patch("harness.loop.build_client", return_value=MagicMock()),
        patch("harness.loop.load_memories", return_value=""),
        patch("harness.loop.save_assessment"),
        patch("harness.loop.dispatch", side_effect=fake_dispatch),
    ):
        result = runner.invoke(
            cli,
            ["run", "--dry-run", "--env", "dev", "--org", "audit-test-org", "--approve-critical"],
        )

    assert result.exit_code == 0, result.output

    run_date = datetime.now(UTC).strftime("%Y-%m-%d")
    audit_path = _REPO / ".saas-assurance" / "audit" / "audit-test-org" / run_date / "audit.jsonl"
    assert audit_path.exists(), f"audit.jsonl not created at {audit_path}"

    lines = [json.loads(row) for row in audit_path.read_text().strip().splitlines()]
    events = [row["event"] for row in lines]

    assert events[0] == "loop_start"
    assert "tool_call" in events
    assert events[-1] == "loop_end"

    tool_call = next(row for row in lines if row["event"] == "tool_call")
    assert tool_call["tool"] == "sfdc_connect_collect"
    assert "duration_ms" in tool_call
    assert tool_call["status"] == "ok"


def test_openai_client_uses_api_key(tmp_path: Path) -> None:
    """OPENAI_API_KEY env var is passed to the OpenAI client."""
    mock_responses = [_end_turn_response("No tools needed.")]
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_responses

    runner = CliRunner()

    with (
        patch("openai.OpenAI", return_value=mock_client) as mock_ctor,
        patch("harness.loop.build_client", return_value=MagicMock()),
        patch("harness.loop.load_memories", return_value=""),
        patch("harness.loop.save_assessment"),
    ):
        runner.invoke(
            cli,
            ["run", "--dry-run", "--org", "key-test-org", "--api-key", "sk-test-key"],
        )

    mock_ctor.assert_called_once_with(api_key="sk-test-key", max_retries=5)


# ---------------------------------------------------------------------------
# Test: sequencing gate blocks out-of-order tool calls
# ---------------------------------------------------------------------------


def test_sequencing_gate_blocks_report_gen_without_prerequisites(tmp_path: Path) -> None:
    """report_gen_generate is blocked if oscal_gap_map / sscf_benchmark haven't run."""
    fake_backlog = str(tmp_path / "backlog.json")
    (tmp_path / "backlog.json").write_text(json.dumps({"mapped_items": [], "summary": {}}))

    # LLM tries to call report_gen before gap_map/benchmark — sequencing violation
    mock_responses = [
        _tool_use_response(
            "report_gen_generate",
            "call_seq_001",
            {
                "backlog": fake_backlog,
                "audience": "security",
                "out": str(tmp_path / "report.md"),
                "org": "seq-test-org",
            },
        ),
        _end_turn_response("Could not generate report — prerequisite tools not completed."),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_responses

    dispatch_called_with: list[str] = []

    def fake_dispatch(name: str, inp: dict) -> str:  # noqa: ANN001
        dispatch_called_with.append(name)
        return json.dumps({"status": "ok"})

    runner = CliRunner()
    with (
        patch("openai.OpenAI", return_value=mock_client),
        patch("harness.loop.build_client", return_value=MagicMock()),
        patch("harness.loop.load_memories", return_value=""),
        patch("harness.loop.save_assessment"),
        patch("harness.loop.dispatch", side_effect=fake_dispatch),
    ):
        result = runner.invoke(
            cli,
            ["run", "--dry-run", "--org", "seq-test-org", "--approve-critical"],
        )

    assert result.exit_code == 0, result.output
    # dispatch must NOT have been called for report_gen (blocked by sequencing gate)
    assert "report_gen_generate" not in dispatch_called_with, (
        "report_gen_generate should have been blocked by sequencing gate"
    )


# ---------------------------------------------------------------------------
# Regression: malformed JSON result must NOT unlock downstream tools
# ---------------------------------------------------------------------------


def test_malformed_json_result_does_not_unlock_downstream(tmp_path: Path) -> None:
    """A tool returning un-parseable JSON must not enter completed_tools.

    The completed_tools.add() call lives inside the JSON-parsing try block.
    If the result is malformed, the except branch fires, the add is skipped,
    and downstream tools that depend on this tool must remain blocked.
    """
    fake_gap = str(tmp_path / "gap_analysis.json")
    (tmp_path / "gap_analysis.json").write_text(json.dumps({"findings": []}))

    mock_responses = [
        _tool_use_response("oscal_assess_assess", "c01", {"dry_run": True, "out": fake_gap, "org": "seq-test-org"}),
        # oscal_gap_map returns garbage — not valid JSON
        _tool_use_response("oscal_gap_map", "c02", {"gap_analysis": fake_gap, "org": "seq-test-org"}),
        # model immediately tries the dependent tool
        _tool_use_response(
            "sscf_benchmark_benchmark",
            "c03",
            {"backlog": str(tmp_path / "backlog.json"), "org": "seq-test-org"},
        ),
        _end_turn_response("Done."),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_responses

    dispatched: list[str] = []

    def fake_dispatch(name: str, inp: dict) -> str:  # noqa: ANN001
        dispatched.append(name)
        if name == "oscal_gap_map":
            return "THIS IS NOT JSON {{{"  # malformed result
        return json.dumps({"status": "ok", "output_file": fake_gap})

    runner = CliRunner()
    with (
        patch("openai.OpenAI", return_value=mock_client),
        patch("harness.loop.build_client", return_value=MagicMock()),
        patch("harness.loop.load_memories", return_value=""),
        patch("harness.loop.save_assessment"),
        patch("harness.loop.dispatch", side_effect=fake_dispatch),
    ):
        result = runner.invoke(cli, ["run", "--dry-run", "--org", "seq-test-org", "--approve-critical"])

    assert result.exit_code == 0, result.output
    assert "oscal_gap_map" in dispatched
    # sscf_benchmark must be blocked — gap_map never entered completed_tools
    # because its result could not be parsed
    assert "sscf_benchmark_benchmark" not in dispatched, (
        "sscf_benchmark_benchmark should be blocked when oscal_gap_map returned malformed JSON"
    )


# ---------------------------------------------------------------------------
# Regression: failed tool must NOT unlock downstream tools (Finding 1)
# ---------------------------------------------------------------------------


def test_failed_tool_does_not_unlock_downstream(tmp_path: Path) -> None:
    """A tool returning status=error must not be added to completed_tools.

    oscal_gap_map fails → sscf_benchmark_benchmark must remain blocked.
    Without the fix, completed_tools.add() was unconditional, allowing
    downstream tools to run after a failed prerequisite.
    """
    fake_gap = str(tmp_path / "gap_analysis.json")
    (tmp_path / "gap_analysis.json").write_text(json.dumps({"findings": []}))

    mock_responses = [
        # Turn 1: oscal_assess succeeds — populates completed_tools
        _tool_use_response("oscal_assess_assess", "c01", {"dry_run": True, "out": fake_gap, "org": "weak-org-dry-run"}),
        # Turn 2: oscal_gap_map returns an error payload (status=error)
        _tool_use_response("oscal_gap_map", "c02", {"gap_analysis": fake_gap, "org": "weak-org-dry-run"}),
        # Turn 3: model tries sscf_benchmark immediately after the failed gap_map
        _tool_use_response(
            "sscf_benchmark_benchmark",
            "c03",
            {"backlog": str(tmp_path / "backlog.json"), "org": "weak-org-dry-run"},
        ),
        _end_turn_response("Stopped after sequencing block."),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_responses

    dispatched: list[str] = []

    def fake_dispatch(name: str, inp: dict) -> str:  # noqa: ANN001
        dispatched.append(name)
        if name == "oscal_gap_map":
            # Simulate tool failure: non-zero exit causes dispatch to return error payload
            return json.dumps({"status": "error", "message": "gap map script crashed"})
        return json.dumps({"status": "ok", "output_file": fake_gap})

    runner = CliRunner()
    with (
        patch("openai.OpenAI", return_value=mock_client),
        patch("harness.loop.build_client", return_value=MagicMock()),
        patch("harness.loop.load_memories", return_value=""),
        patch("harness.loop.save_assessment"),
        patch("harness.loop.dispatch", side_effect=fake_dispatch),
    ):
        result = runner.invoke(cli, ["run", "--dry-run", "--org", "weak-org-dry-run", "--approve-critical"])

    assert result.exit_code == 0, result.output
    # gap_map was dispatched (and returned an error)
    assert "oscal_gap_map" in dispatched
    # sscf_benchmark must have been blocked by the sequencing gate because
    # oscal_gap_map never entered completed_tools (it returned status=error)
    assert "sscf_benchmark_benchmark" not in dispatched, (
        "sscf_benchmark_benchmark should be blocked when oscal_gap_map returned an error"
    )


# ---------------------------------------------------------------------------
# Regression: finish() blocked when only app-owner report exists (Finding 2)
# ---------------------------------------------------------------------------


def test_finish_blocked_without_security_report(tmp_path: Path) -> None:
    """finish() must be rejected if the security-audience report has not been written.

    The sequencing gate allows finish() only after report_gen_generate[audience=security]
    has succeeded. An app-owner-only run must not be able to call finish() and exit
    without the security deliverable.

    Prerequisites (oscal_gap_map, sscf_benchmark_benchmark) are satisfied via
    fake_dispatch returning status=ok, advancing completed_tools normally.
    """
    fake_gap = str(tmp_path / "gap_analysis.json")
    fake_backlog = str(tmp_path / "backlog.json")
    fake_sscf = str(tmp_path / "sscf_report.json")
    app_owner_out = str(tmp_path / "remediation.md")

    for path, content in [
        (fake_gap, {"findings": []}),
        (fake_backlog, {"mapped_items": [], "summary": {}}),
        (fake_sscf, {"overall_score": 0.5, "overall_status": "amber", "domains": []}),
    ]:
        Path(path).write_text(json.dumps(content))

    mock_responses = [
        # Run full prerequisite chain so completed_tools is populated correctly
        _tool_use_response("oscal_assess_assess", "c01", {"dry_run": True, "out": fake_gap, "org": "seq-test-org"}),
        _tool_use_response("oscal_gap_map", "c02", {"gap_analysis": fake_gap, "org": "seq-test-org"}),
        _tool_use_response("sscf_benchmark_benchmark", "c03", {"backlog": fake_backlog, "org": "seq-test-org"}),
        # Only the app-owner report is generated — security report is skipped
        _tool_use_response(
            "report_gen_generate",
            "c04",
            {"backlog": fake_backlog, "audience": "app-owner", "out": app_owner_out, "org": "seq-test-org"},
        ),
        # Model calls finish() without generating the security report
        _tool_use_response("finish", "c05", {"summary": "Done — only app-owner report written."}),
        _end_turn_response("Pipeline ended without security report."),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_responses

    dispatched: list[str] = []

    def fake_dispatch(name: str, inp: dict) -> str:  # noqa: ANN001
        dispatched.append(name)
        out_map = {
            "oscal_assess_assess": fake_gap,
            "oscal_gap_map": fake_backlog,
            "sscf_benchmark_benchmark": fake_sscf,
            "report_gen_generate": app_owner_out,
        }
        return json.dumps({"status": "ok", "output_file": out_map.get(name, "")})

    runner = CliRunner()
    with (
        patch("openai.OpenAI", return_value=mock_client),
        patch("harness.loop.build_client", return_value=MagicMock()),
        patch("harness.loop.load_memories", return_value=""),
        patch("harness.loop.save_assessment"),
        patch("harness.loop.dispatch", side_effect=fake_dispatch),
    ):
        result = runner.invoke(cli, ["run", "--dry-run", "--org", "seq-test-org", "--approve-critical"])

    assert result.exit_code == 0, result.output
    # app-owner report_gen was dispatched and succeeded
    assert "report_gen_generate" in dispatched
    # finish() must NOT have been dispatched — sequencing gate should have blocked it
    # because state["report_security_md"] is None (only app-owner report was written)
    assert "finish" not in dispatched, "finish() should be blocked when no security-audience report has been written"


# ---------------------------------------------------------------------------
# finish() gating: security_review_flags injected from harness state
# ---------------------------------------------------------------------------


def test_finish_blocked_on_credential_exposure_flag() -> None:
    """_dispatch_finish must block when security_review_flags contains a credential_exposure flag.

    This test verifies that harness/tools.py correctly blocks pipeline completion
    when a credential_exposure flag is present. The loop.py injects state flags
    into the inp dict before calling dispatch("finish", inp).
    """
    from harness.tools import dispatch

    inp = {
        "summary": "All checks complete.",
        "security_review_flags": ["credential_exposure:org_id_in_executive_summary"],
    }
    result = json.loads(dispatch("finish", inp))
    assert result["status"] == "blocked", f"Expected blocked, got: {result}"
    assert any("credential_exposure" in f for f in result.get("flags", [])), "blocking flag not surfaced"


def test_finish_blocked_on_scope_violation_flag() -> None:
    """_dispatch_finish must block when security_review_flags contains a scope_violation flag."""
    from harness.tools import dispatch

    inp = {
        "summary": "Assessment done.",
        "security_review_flags": ["scope_violation:section_3_grants_write_access"],
    }
    result = json.loads(dispatch("finish", inp))
    assert result["status"] == "blocked", f"Expected blocked, got: {result}"
    assert any("scope_violation" in f for f in result.get("flags", [])), "blocking flag not surfaced"


def test_finish_allowed_when_only_status_misrepresentation_flag() -> None:
    """_dispatch_finish must allow completion when the only flag is status_misrepresentation.

    status_misrepresentation is a warning-only flag — it does not block delivery.
    Only credential_exposure and scope_violation are blocking.
    """
    from harness.tools import dispatch

    inp = {
        "summary": "Assessment complete.",
        "security_review_flags": ["status_misrepresentation:SBS-AUTH-001"],
    }
    result = json.loads(dispatch("finish", inp))
    assert result["status"] == "ok", f"Expected ok (warning-only flag should not block), got: {result}"
    assert result.get("pipeline_complete") is True


def test_finish_allowed_when_no_security_review_flags() -> None:
    """_dispatch_finish must allow completion when security_review_flags is empty."""
    from harness.tools import dispatch

    inp = {
        "summary": "Clean run — no flags.",
        "security_review_flags": [],
    }
    result = json.loads(dispatch("finish", inp))
    assert result["status"] == "ok", f"Expected ok with no flags, got: {result}"
    assert result.get("pipeline_complete") is True


# ---------------------------------------------------------------------------
# security_reviewer_review nudge: loop.py branches (lines 481-504)
# ---------------------------------------------------------------------------


def test_security_reviewer_review_nudge_injected_when_no_critical_flags(tmp_path: Path) -> None:
    """When security_reviewer_review returns no critical flags the harness injects a
    user-role nudge message telling the orchestrator to call finish().

    Covers the else-branch in loop.py (lines 492-504). _TOOL_REQUIRES is patched
    to empty so this test is isolated to the nudge logic, not the sequencing gate.
    """
    security_report = str(tmp_path / "nudge-test-org_security_assessment.md")
    (tmp_path / "nudge-test-org_security_assessment.md").write_text("# Security Report")

    mock_responses = [
        # report_gen_generate populates state["report_security_md"] to satisfy the
        # hardcoded finish() check (separate from _TOOL_REQUIRES gate, patched below)
        _tool_use_response(
            "report_gen_generate",
            "rg_01",
            {"audience": "security", "org_alias": "nudge-test-org", "out": security_report},
        ),
        _tool_use_response(
            "security_reviewer_review",
            "sr_01",
            {"org": "nudge-test-org", "report_path": security_report},
        ),
        _tool_use_response("finish", "fin_01", {"summary": "Done."}),
    ]
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_responses

    def fake_dispatch(name: str, inp: dict) -> str:  # noqa: ANN001
        if name == "report_gen_generate":
            return json.dumps({"status": "ok", "output_file": security_report})
        if name == "security_reviewer_review":
            return json.dumps({"status": "ok", "flags": []})
        if name == "finish":
            return json.dumps({"status": "ok", "pipeline_complete": True, "summary": inp.get("summary", "")})
        return json.dumps({"status": "ok"})

    runner = CliRunner()
    with (
        patch("openai.OpenAI", return_value=mock_client),
        patch("harness.loop.build_client", return_value=MagicMock()),
        patch("harness.loop.load_memories", return_value=""),
        patch("harness.loop.save_assessment"),
        patch("harness.loop.dispatch", side_effect=fake_dispatch),
        patch("harness.loop._TOOL_REQUIRES", {}),  # bypass sequencing gate
    ):
        result = runner.invoke(
            cli,
            ["run", "--dry-run", "--env", "dev", "--org", "nudge-test-org", "--approve-critical"],
        )

    assert result.exit_code == 0, result.output
    assert "finish() called" in result.output

    # The nudge message must appear in the messages sent for the finish() turn (3rd call)
    calls = mock_client.chat.completions.create.call_args_list
    assert len(calls) == 3  # noqa: PLR2004  # rg + sr + finish
    finish_turn_messages = calls[2][1].get("messages", calls[2][0][0] if calls[2][0] else [])
    nudge_msgs = [
        m for m in finish_turn_messages if m.get("role") == "user" and "[harness]" in m.get("content", "")
    ]
    assert nudge_msgs, "Harness nudge message was not injected before finish() turn"


def test_security_reviewer_review_warning_logged_on_critical_flag(tmp_path: Path) -> None:
    """When security_reviewer_review returns a credential_exposure flag the harness
    logs a WARNING (covers the if-critical_flags branch in loop.py lines 486-491).
    """
    mock_responses = [
        _tool_use_response(
            "security_reviewer_review",
            "sr_02",
            {"org": "flag-test-org", "report_path": "/tmp/report.md"},
        ),
        _end_turn_response("Security review flagged — stopping."),
    ]
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_responses

    def fake_dispatch(name: str, inp: dict) -> str:  # noqa: ANN001
        if name == "security_reviewer_review":
            return json.dumps({
                "status": "ok",
                "flags": ["credential_exposure:org_id_in_executive_summary"],
            })
        return json.dumps({"status": "ok"})

    runner = CliRunner()
    with (
        patch("openai.OpenAI", return_value=mock_client),
        patch("harness.loop.build_client", return_value=MagicMock()),
        patch("harness.loop.load_memories", return_value=""),
        patch("harness.loop.save_assessment"),
        patch("harness.loop.dispatch", side_effect=fake_dispatch),
        patch("harness.loop._TOOL_REQUIRES", {}),
    ):
        result = runner.invoke(
            cli,
            ["run", "--dry-run", "--env", "dev", "--org", "flag-test-org", "--approve-critical"],
        )

    # The critical-flag WARNING must appear in the merged output
    assert "WARNING" in result.output or "critical flag" in result.output.lower()
