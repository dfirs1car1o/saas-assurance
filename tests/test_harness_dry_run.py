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
    audit_path = (
        _REPO / "docs" / "oscal-salesforce-poc" / "generated" / "audit-test-org" / run_date / "audit.jsonl"
    )
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
