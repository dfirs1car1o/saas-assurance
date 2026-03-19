"""
harness/loop.py — Agentic orchestration loop for OSCAL/SSCF assessments.

Entry point:  agent-loop run [OPTIONS]

The orchestrator (gpt-5.3-chat-latest by default, override via LLM_MODEL_ORCHESTRATOR) is called in a tool_calls loop:
  1. Load agent config (mission.md + orchestrator.md as system prompt)
  2. Prepend prior org assessment memory to the first user message
  3. Drive the OpenAI chat completions API until finish_reason == "stop"
  4. Dispatch each tool call via harness.tools.dispatch()
  5. Gate on critical/fail findings before writing final output
  6. Persist assessment metrics to Qdrant via Mem0
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from dotenv import load_dotenv

from harness.agents import ORCHESTRATOR
from harness.memory import build_client, load_memories, save_assessment
from harness.tools import ALL_TOOLS, dispatch, set_openai_client

_REPO = Path(os.environ.get("REPO_ROOT", str(Path(__file__).resolve().parents[1])))


# ---------------------------------------------------------------------------
# Structured audit log
# ---------------------------------------------------------------------------


def _append_audit(path: Path, record: dict[str, Any]) -> None:
    """Append one JSONL record to the run audit log. Best-effort — never aborts the loop.

    Produces a machine-readable forensic trail of every tool invocation:
        {"event": "tool_call", "ts": "...", "turn": 2, "tool": "oscal_assess_assess",
         "args": {...}, "status": "ok", "duration_ms": 142}

    OWASP ASI-09 (Logging & Monitoring) requires an audit trail for every
    autonomous agent action. This satisfies that requirement without coupling
    the audit path to the harness state machine.
    """
    try:
        with path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001
        pass  # audit failure must never abort the assessment run


def _make_openai_client(api_key: str | None = None, max_retries: int = 5):
    """Return an AzureOpenAI or OpenAI client based on environment variables.

    Azure is selected when both AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT
    are present. All other callers fall back to the standard OpenAI client.
    """
    import openai  # lazy import — keeps startup fast when openai is not installed

    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if azure_key and azure_endpoint:
        return openai.AzureOpenAI(
            api_key=azure_key,
            azure_endpoint=azure_endpoint,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            max_retries=max_retries,
        )
    return openai.OpenAI(
        api_key=api_key or os.getenv("OPENAI_API_KEY"),
        max_retries=max_retries,
    )


# Load .env at import time so OPENAI_API_KEY and SF_* vars are in os.environ
# before Click reads envvar= options or os.getenv() is called anywhere.
load_dotenv(_REPO / ".env")
_MAX_TURNS = 14  # hard stop: 7 pipeline steps + LLM-only turns; extra headroom for finish() call

# Tool sequencing dependency map (OWASP A2 — Excessive Agency mitigation).
# Before dispatching a tool, verify all required predecessors have completed.
# This prevents the LLM from calling report_gen before assess/gap_map, which would
# produce misleading governance output from missing or stale data.
# dry_run=True waives collector prerequisites (sfdc/workday_connect_collect) so
# offline test loops can run straight to assess without a live org connection.
_TOOL_REQUIRES: dict[str, frozenset] = {
    "oscal_gap_map": frozenset({"oscal_assess_assess"}),
    "sscf_benchmark_benchmark": frozenset({"oscal_gap_map"}),
    "nist_review_assess": frozenset({"oscal_assess_assess"}),
    "gen_aicm_crosswalk": frozenset({"oscal_gap_map"}),
    "report_gen_generate": frozenset({"oscal_gap_map", "sscf_benchmark_benchmark"}),
    "finish": frozenset({"report_gen_generate"}),
    # Agent sub-call tools — require assess to have produced gap_analysis.json.
    # collector_enrich and security_reviewer_review are optional/conditional and
    # are not gated here; the orchestrator task prompt governs when to call them.
    "assessor_analyze": frozenset({"oscal_assess_assess"}),
    "workday_expert_enrich": frozenset({"oscal_assess_assess"}),
}

# ---------------------------------------------------------------------------
# Expert-review escalation helper
# ---------------------------------------------------------------------------


def _log_expert_escalations(gap_analysis_path: str, dry_run: bool) -> list[str]:
    """Scan gap_analysis for controls needing sfdc-expert review. Log in dry-run."""
    try:
        data = json.loads(Path(gap_analysis_path).read_text())
        eligible = [f["control_id"] for f in data.get("findings", []) if f.get("needs_expert_review")]
    except Exception:  # noqa: BLE001
        return []

    if not eligible:
        return eligible

    if dry_run:
        click.echo(
            f"  [sfdc-expert] DRY-RUN: {len(eligible)} control(s) would trigger sfdc-expert:\n"
            + "\n".join(f"    - {c}" for c in eligible),
            err=True,
        )
    else:
        click.echo(
            f"  [sfdc-expert] {len(eligible)} control(s) flagged for expert review: " + ", ".join(eligible),
            err=True,
        )
    return eligible


# ---------------------------------------------------------------------------
# Critical/fail gate helpers
# ---------------------------------------------------------------------------


def _extract_critical_fails(gap_analysis_path: str | None) -> list[str]:
    """Return control IDs that are both status=fail and severity=critical."""
    if not gap_analysis_path:
        return []
    path = Path(gap_analysis_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [
            f["control_id"]
            for f in data.get("findings", [])
            if f.get("status") == "fail" and f.get("severity") == "critical"
        ]
    except Exception:  # noqa: BLE001
        return []


def _extract_score(sscf_report_path: str | None) -> float:
    """Extract overall_score from sscf_report.json, default 0.0 on failure."""
    if not sscf_report_path:
        return 0.0
    path = Path(sscf_report_path)
    if not path.exists():
        return 0.0
    try:
        data = json.loads(path.read_text())
        return float(data.get("overall_score", 0.0))
    except Exception:  # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------------------
# Tool error handler — your contribution here
# ---------------------------------------------------------------------------


def _handle_tool_error(
    tool_name: str,
    tool_input: dict[str, Any],
    error: Exception,
) -> str:
    """Decide how to respond when a CLI tool dispatch fails.

    This function is called whenever dispatch() raises a RuntimeError.
    It returns a string that is fed back to the orchestrator as the tool_result
    content — the LLM will see this and decide how to proceed.

    Your task: implement the error handling strategy that best fits the
    security assessment context. Consider these trade-offs:

    Option A — Halt + surface (safest):
        raise the error immediately so the human sees it.
        Risk: one transient failure aborts the entire assessment.
        Best for: production runs, critical-path tools.

    Option B — Return structured error (recommended for resilience):
        return a JSON error payload; let the orchestrator decide next step.
        The LLM can narrow scope, skip optional stages, or ask the human.
        Best for: multi-stage pipelines where some stages are optional.

    Option C — Retry with narrowed scope (advanced):
        modify tool_input (e.g., scope="auth" instead of "all") and retry once.
        Useful when "all" scope times out but partial scope succeeds.
        Risk: hiding a real failure in a retry loop.

    IMPORTANT (security constraint): never silently swallow errors on
    sfdc_connect_collect or oscal_assess_assess — a hidden collector failure
    could cause a false-pass assessment (no findings because no data collected).

    TODO: implement your chosen strategy below (5–10 lines).
    Signature: (tool_name: str, tool_input: dict, error: Exception) -> str
    The return value is a JSON string fed to the orchestrator as the tool result.
    """
    # Critical pipeline stages: halt immediately.
    # A hidden collector or assessor failure produces zero findings → false-pass assessment.
    _CRITICAL_TOOLS = {
        "sfdc_connect_collect",
        "workday_connect_collect",
        "oscal_assess_assess",
        "sfdc_expert_enrich",
        "workday_expert_enrich",
    }
    if tool_name in _CRITICAL_TOOLS:
        raise RuntimeError(f"Critical tool '{tool_name}' failed — aborting to prevent false-pass assessment.\n{error}")
    # Downstream stages (gap_map, benchmark): return structured error payload.
    # The orchestrator can report partial results rather than aborting the whole run.
    return json.dumps({"status": "error", "tool": tool_name, "input": tool_input, "message": str(error)})


# ---------------------------------------------------------------------------
# Message loop
# ---------------------------------------------------------------------------


def _run_loop(  # NOSONAR
    task: str,
    env: str,
    org: str,
    platform: str,
    dry_run: bool,
    approve_critical: bool,
    api_key: str | None,
) -> dict[str, Any]:
    """Core agentic loop. Returns result dict with score, status, output paths."""
    client = _make_openai_client(api_key=api_key or os.getenv("OPENAI_API_KEY"), max_retries=5)
    # Inject client into tools.py so agent sub-call dispatchers can use it.
    # Must happen before the first tool call — not lazily on first dispatch.
    set_openai_client(client)

    # --- Audit log: one JSONL file per run, co-located with other outputs ---
    run_date = datetime.now(UTC).strftime("%Y-%m-%d")
    audit_dir = _REPO / ".saas-assurance" / "audit" / org / run_date
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "audit.jsonl"
    _append_audit(
        audit_path,
        {
            "event": "loop_start",
            "ts": datetime.now(UTC).isoformat(),
            "org": org,
            "env": env,
            "platform": platform,
            "dry_run": dry_run,
        },
    )

    # --- Memory: load prior assessments for this org ---
    mem_client = None
    memory_context = ""
    try:
        mem_client = build_client()
        memory_context = load_memories(mem_client, org)
        click.echo(f"  [memory] {memory_context.splitlines()[0]}", err=True)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"  [memory] unavailable: {exc}", err=True)

    # --- Memory guard: strip indirect prompt injection patterns before injecting
    # Mem0 memories into the system prompt. If Qdrant memories were poisoned via
    # a prior adversarial assessment run, this prevents the stored content from
    # overriding the orchestrator's instructions. Low-overhead; defense-in-depth. ---
    _INJECTION_PATTERNS = [
        "ignore previous instructions",
        "ignore all previous",
        "disregard previous",
        "system:",
        "you are now",
        "act as",
        "new instructions:",
        "override:",
    ]
    if memory_context:
        lowered = memory_context.lower()
        if any(pat in lowered for pat in _INJECTION_PATTERNS):
            click.echo("  [memory] WARNING: possible injection pattern in stored memories — skipping.", err=True)
            memory_context = ""

    # --- Build initial messages (system prompt + user task) ---
    user_content = task
    if memory_context:
        user_content = f"{memory_context}\n\n---\n\n{task}"

    messages: list[Any] = [
        {"role": "system", "content": ORCHESTRATOR.system_prompt},
        {"role": "user", "content": user_content},
    ]

    # Track key output file paths as the pipeline progresses
    state: dict[str, Any] = {
        "gap_analysis": None,
        "backlog": None,
        "sscf_report": None,
        "nist_review": None,
        "aicm_coverage": None,
        "report_app_owner": None,
        "report_security_md": None,
        "report_security_docx": None,
        "collector_enrichment": None,  # analysis text from collector_enrich agent
        "security_review_flags": [],  # FLAG tokens from security_reviewer_review
        "turns": 0,
    }

    # Tracks which pipeline tools have completed; used by the sequencing gate.
    completed_tools: set[str] = set()

    # --- Agentic loop ---
    for turn in range(_MAX_TURNS):
        state["turns"] = turn + 1

        response = client.chat.completions.create(
            model=ORCHESTRATOR.model,
            max_completion_tokens=int(os.getenv("LLM_MAX_TOKENS_ORCHESTRATOR", "8192")),
            tools=ALL_TOOLS,
            messages=messages,
        )

        choice = response.choices[0]

        if choice.finish_reason == "stop":
            state["summary"] = choice.message.content or ""
            break

        if choice.finish_reason == "length":
            click.echo("WARNING: Response truncated (max_completion_tokens reached).", err=True)
            state["summary"] = "[truncated]"
            break

        if choice.finish_reason != "tool_calls":
            click.echo(f"WARNING: Unexpected finish_reason: {choice.finish_reason}", err=True)
            state["summary"] = f"[stop: {choice.finish_reason}]"
            break

        # --- Append assistant turn preserving tool_calls metadata ---
        messages.append(
            {
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in choice.message.tool_calls
                ],
            }
        )

        # --- Process each tool call; one tool message per call ---
        pipeline_done = False
        for tc in choice.message.tool_calls:
            name = tc.function.name
            inp = json.loads(tc.function.arguments)

            click.echo(f"  [tool] {name}({json.dumps(inp, separators=(',', ':'))})", err=True)

            # --- Inject harness-managed state into finish() call (OWASP A2 hardening) ---
            # The LLM cannot reliably pass security_review_flags back to finish() because
            # it has no structured access to harness state. Inject from state here so
            # _dispatch_finish always sees the flags recorded by security_reviewer_review,
            # regardless of what the LLM included in its tool arguments.
            if name == "finish":
                inp["security_review_flags"] = state.get("security_review_flags", [])

            # --- Tool sequencing gate (OWASP A2 — Excessive Agency) ---
            # Waive collector prerequisites when dry_run is active — offline test runs
            # skip straight to assess without a live Salesforce/Workday connection.
            _required = _TOOL_REQUIRES.get(name, frozenset())
            if inp.get("dry_run", dry_run):
                _required = _required - {"sfdc_connect_collect", "workday_connect_collect"}
            _missing = _required - completed_tools
            # finish() additionally requires the security-audience report to exist.
            # Requiring only "some report_gen_generate" would allow finish() after an
            # app-owner-only report, producing a run with no security deliverable.
            if name == "finish" and not state.get("report_security_md"):
                _missing = _missing | {"report_gen_generate[audience=security]"}
            if _missing:
                _seq_msg = (
                    f"Sequencing violation: '{name}' requires {sorted(_missing)} to complete first. "
                    "Call the required tools before calling this one."
                )
                click.echo(f"  [sequence] BLOCKED: {_seq_msg}", err=True)
                _append_audit(
                    audit_path,
                    {
                        "event": "tool_call",
                        "ts": datetime.now(UTC).isoformat(),
                        "turn": turn + 1,
                        "tool": name,
                        "args": inp,
                        "status": "sequencing_violation",
                        "duration_ms": 0,
                    },
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"status": "error", "message": _seq_msg}),
                    }
                )
                continue

            _t0 = time.perf_counter()
            _call_status = "ok"
            try:
                result_str = dispatch(name, inp)
            except Exception as exc:  # noqa: BLE001
                _call_status = "error"
                result_str = _handle_tool_error(name, inp, exc)
            finally:
                _append_audit(
                    audit_path,
                    {
                        "event": "tool_call",
                        "ts": datetime.now(UTC).isoformat(),
                        "turn": turn + 1,
                        "tool": name,
                        "args": inp,
                        "status": _call_status,
                        "duration_ms": round((time.perf_counter() - _t0) * 1000),
                    },
                )

            # Track output files and mark tool as completed (on success only).
            # Unconditionally adding here would allow a failed oscal_gap_map or
            # sscf_benchmark to unlock downstream tools, producing misleading output.
            try:
                result_data = json.loads(result_str)
                if result_data.get("pipeline_complete"):
                    state["summary"] = result_data.get("summary", "Pipeline complete.")
                    pipeline_done = True
                # Gate advancement: only mark complete when the tool itself succeeded.
                if _call_status == "ok" and result_data.get("status") == "ok":
                    completed_tools.add(name)
                out_file = result_data.get("output_file")
                if out_file:
                    if name == "oscal_assess_assess":
                        state["gap_analysis"] = out_file
                        _log_expert_escalations(out_file, dry_run)
                    elif name == "oscal_gap_map":
                        state["backlog"] = out_file
                    elif name == "sscf_benchmark_benchmark":
                        state["sscf_report"] = out_file
                    elif name == "nist_review_assess":
                        state["nist_review"] = out_file
                    elif name == "gen_aicm_crosswalk":
                        state["aicm_coverage"] = out_file
                    elif name == "report_gen_generate":
                        audience = inp.get("audience", "")
                        if audience == "app-owner":
                            state["report_app_owner"] = out_file
                        elif audience == "security":
                            state["report_security_md"] = out_file
                            docx = str(Path(out_file).with_suffix(".docx"))
                            if Path(docx).exists():
                                state["report_security_docx"] = docx
                # Track agent sub-call outputs (no output_file — track analysis/flags instead).
                if name == "collector_enrich":
                    state["collector_enrichment"] = result_data.get("analysis")
                elif name == "security_reviewer_review":
                    state["security_review_flags"] = result_data.get("flags", [])
                    critical_flags = [
                        f for f in result_data.get("flags", []) if "credential_exposure" in f or "scope_violation" in f
                    ]
                    if critical_flags:
                        click.echo(
                            f"  [security-reviewer] WARNING: {len(critical_flags)} critical flag(s):\n"
                            + "\n".join(f"    - {f}" for f in critical_flags),
                            err=True,
                        )
            except (json.JSONDecodeError, AttributeError):
                pass

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

        if pipeline_done:
            click.echo("  [loop] finish() called — pipeline complete.", err=True)
            break

    else:
        click.echo(f"WARNING: Reached max turns ({_MAX_TURNS}). Loop hard-stopped.", err=True)
        state["summary"] = f"[max_turns={_MAX_TURNS} exceeded]"

    # --- Critical/fail gate ---
    critical_fails = _extract_critical_fails(state.get("gap_analysis"))
    score = _extract_score(state.get("sscf_report"))

    if critical_fails and not dry_run and not approve_critical:
        click.echo(
            f"\nBLOCKED: {len(critical_fails)} critical/fail finding(s) require human review:\n"
            + "\n".join(f"  - {c}" for c in critical_fails)
            + "\n\nRe-run with --approve-critical to proceed past this gate.",
            err=True,
        )
        sys.exit(2)

    # --- Persist to memory ---
    if mem_client is not None:
        assessment_id = f"{platform}-assess-{org}-{env}-loop"
        save_assessment(mem_client, org, assessment_id, score, critical_fails)

    _append_audit(
        audit_path,
        {
            "event": "loop_end",
            "ts": datetime.now(UTC).isoformat(),
            "turns": state["turns"],
            "overall_score": score,
            "critical_fails": critical_fails,
        },
    )

    state["score"] = score
    state["critical_fails"] = critical_fails
    state["audit_log"] = str(audit_path)
    return state


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """agent-loop — agentic OSCAL/SSCF assessment orchestrator."""


@cli.command()
@click.option(
    "--env",
    default="dev",
    envvar="SFDC_ENV",
    type=click.Choice(["dev", "test", "prod"]),
    show_default=True,
    help="Target environment label (default: SFDC_ENV env var, then 'dev').",
)
@click.option(
    "--org",
    default="unknown-org",
    envvar="SFDC_ORG_ALIAS",
    show_default=True,
    help="Org alias for output directory naming and memory scoping (default: SFDC_ORG_ALIAS env var).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Use dry-run mode for all CLIs (no real Salesforce connection, no real API spend on tools).",
)
@click.option(
    "--approve-critical",
    is_flag=True,
    help="Bypass the critical/fail gate and write output even if critical findings exist.",
)
@click.option("--task", default=None, help="Override the default assessment task prompt sent to the orchestrator.")
@click.option(
    "--platform",
    default="salesforce",
    type=click.Choice(["salesforce", "workday"]),
    show_default=True,
    envvar="ASSESSMENT_PLATFORM",
    help="Platform to assess (salesforce or workday).",
)
@click.option(
    "--api-key",
    default=None,
    envvar="OPENAI_API_KEY",
    help="OpenAI API key (defaults to OPENAI_API_KEY env var).",
)
def run(  # NOSONAR
    env: str,
    org: str,
    dry_run: bool,
    approve_critical: bool,
    task: str | None,
    platform: str,
    api_key: str | None,
) -> None:
    """Run the agentic assessment loop against a Salesforce or Workday org.

    Orchestrates the full assessment pipeline via gpt tool_calls, with Mem0+Qdrant session memory.

    Examples:
        agent-loop run --dry-run --env dev --org demo-org
        agent-loop run --platform workday --dry-run --env dev --org acme-workday
    """
    dry_tag = " [DRY-RUN]" if dry_run else ""
    click.echo(f"\nagent-loop{dry_tag}: platform={platform} org={org} env={env}")

    platform_label = "Salesforce" if platform == "salesforce" else "Workday"
    default_title = f"{platform_label} Security Governance Assessment"
    governance_title = os.getenv("REPORT_GOVERNANCE_TITLE", default_title)
    org_display = os.getenv("REPORT_ORG_DISPLAY_NAME", org)

    if task is None:
        dry_note = f" Use dry_run=true for all tool calls (no real {platform_label} connection)." if dry_run else ""
        dry_gate_note = (
            (
                " This is a dry run — proceed through all pipeline stages including report generation "
                "without waiting for human review of findings."
            )
            if dry_run
            else ""
        )
        if platform == "workday":
            task = (
                f"Run a full OSCAL/SSCF security assessment for Workday tenant '{org}' "
                f"in environment '{env}'.{dry_note}{dry_gate_note}\n\n"
                f"IMPORTANT: Pass org='{org}' to every tool call so all outputs land in the same directory.\n\n"
                "Pipeline:\n"
                f"1. Call workday_connect_collect (org='{org}') to gather Workday tenant configuration.\n"
                f"1b. (Live only) Call collector_enrich (org='{org}', platform='workday', "
                f"collector_output=<output from step 1>) to review evidence quality. "
                f"Skip on dry-run. Act on any FLAG: tokens before proceeding.\n"
                f"2. Call oscal_assess_assess (org='{org}', platform='workday') to produce gap_analysis.json "
                f"using the WSCC control catalog (30 SSCF controls).\n"
                f"2b. Call assessor_analyze (org='{org}', platform='workday', "
                f"gap_analysis=<output from step 2>) to review finding confidence. "
                f"If it flags 'expert_review_pending:*', call workday_expert_enrich before step 3.\n"
                f"3. Call oscal_gap_map (org='{org}') with the gap_analysis output to produce backlog.json.\n"
                f"4. Call sscf_benchmark_benchmark (org='{org}') with the backlog to produce the SSCF scorecard.\n"
                f"5. Call nist_review_assess (org='{org}', platform='workday') with gap_analysis from step 2 "
                f"and backlog from step 3 to produce nist_review.json.\n"
                f"5b. Call gen_aicm_crosswalk (org='{org}', backlog from step 3, platform='workday') "
                f"to produce aicm_coverage.json.\n"
                f"6. Call report_gen_generate twice:\n"
                f"   a. audience='app-owner', out='{org}_remediation_report.md', platform='workday', "
                f"sscf_benchmark from step 4.\n"
                f"   b. audience='security', out='{org}_security_assessment.md', platform='workday', "
                f"sscf_benchmark from step 4, nist_review from step 5, aicm_coverage from step 5b, "
                f"title='{governance_title} - {org_display}'. "
                f"The security call automatically also writes .docx to the same directory.\n"
                f"6c. Call security_reviewer_review (org='{org}', "
                f"report_path=<security .md from step 6b>) for a final AppSec check. "
                f"If it flags 'credential_exposure:*' or 'scope_violation:*', surface to human "
                f"before calling finish().\n\n"
                "After step 6c completes (with no blocking flags), call finish() with a one-sentence summary. "
                "The finish() tool signals the harness to stop the loop. "
                "Do NOT call any further tools after finish()."
            )
        else:
            task = (
                f"Run a full OSCAL/SSCF security assessment for Salesforce org '{org}' "
                f"in environment '{env}'.{dry_note}{dry_gate_note}\n\n"
                f"IMPORTANT: Pass org='{org}' to every tool call so all outputs land in the same directory.\n\n"
                "Pipeline:\n"
                f"1. Call sfdc_connect_collect (org='{org}', scope='all') to gather org configuration.\n"
                f"1b. (Live only) Call collector_enrich (org='{org}', platform='salesforce', "
                f"collector_output=<output from step 1>) to review evidence quality. "
                f"Skip on dry-run. Log any FLAG: tokens but always continue to step 2.\n"
                f"2. Call oscal_assess_assess (org='{org}') to produce gap_analysis.json.\n"
                f"2b. Call assessor_analyze (org='{org}', platform='salesforce', "
                f"gap_analysis=<output from step 2>) to review finding confidence. "
                f"If it flags 'expert_review_pending:*', call sfdc_expert_enrich before step 3. "
                f"Assessor flags are informational — always continue to step 3 even if confidence is partial "
                f"or unmapped findings exceed a threshold; low-confidence findings are marked accordingly.\n"
                f"3. Call oscal_gap_map (org='{org}') with the gap_analysis output to produce backlog.json.\n"
                f"4. Call sscf_benchmark_benchmark (org='{org}') with the backlog to produce the SSCF scorecard.\n"
                f"5. Call nist_review_assess (org='{org}', platform='salesforce') with gap_analysis from step 2 "
                f"and backlog from step 3 to produce nist_review.json.\n"
                f"5b. Call gen_aicm_crosswalk (org='{org}', backlog from step 3, platform='salesforce') "
                f"to produce aicm_coverage.json.\n"
                f"6. Call report_gen_generate twice:\n"
                f"   a. audience='app-owner', out='{org}_remediation_report.md', platform='salesforce', "
                f"sscf_benchmark from step 4.\n"
                f"   b. audience='security', out='{org}_security_assessment.md', platform='salesforce', "
                f"sscf_benchmark from step 4, nist_review from step 5, aicm_coverage from step 5b, "
                f"title='{governance_title} - {org_display}'. "
                f"The security call automatically also writes .docx to the same directory.\n"
                f"6c. Call security_reviewer_review (org='{org}', "
                f"report_path=<security .md from step 6b>) for a final AppSec check. "
                f"If it flags 'credential_exposure:*' or 'scope_violation:*', surface to human "
                f"before calling finish().\n\n"
                "After step 6c completes (with no blocking flags), call finish() with a one-sentence summary. "
                "The finish() tool signals the harness to stop the loop. "
                "Do NOT call any further tools after finish()."
            )

    click.echo(f"  task: {task[:120]}{'...' if len(task) > 120 else ''}", err=True)

    state = _run_loop(
        task=task,
        env=env,
        org=org,
        platform=platform,
        dry_run=dry_run,
        approve_critical=approve_critical,
        api_key=api_key,
    )

    # --- Final output ---
    score = state.get("score", 0.0)
    critical_fails = state.get("critical_fails", [])
    score_pct = f"{score:.1%}"
    if score >= 0.80:
        status_label = "GREEN"
    elif score >= 0.50:
        status_label = "AMBER"
    else:
        status_label = "RED"
    status_icon = {"GREEN": "✅", "AMBER": "⚠️", "RED": "🔴"}.get(status_label, "")

    click.echo("\n" + "=" * 60)
    click.echo(f"Assessment complete ({state['turns']} turn(s))")
    click.echo(f"overall_score : {score_pct}  {status_icon} {status_label}")
    click.echo(f"critical_fails: {len(critical_fails)}")
    if critical_fails:
        for c in critical_fails:
            click.echo(f"  - {c}")
    click.echo("=" * 60)

    summary = state.get("summary", "")
    if summary:
        click.echo(f"\nOrchestrator summary:\n{summary}")

    # Write consolidated result JSON to dated run directory (prevents cross-run overwrite)
    run_date = datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir = _REPO / "docs" / "oscal-salesforce-poc" / "generated" / org / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "loop_result.json"
    result_path.write_text(
        json.dumps(
            {
                "org": org,
                "env": env,
                "dry_run": dry_run,
                "turns": state["turns"],
                "overall_score": score,
                "overall_status": status_label.lower(),
                "critical_fails": critical_fails,
                "gap_analysis": state.get("gap_analysis"),
                "backlog": state.get("backlog"),
                "sscf_report": state.get("sscf_report"),
                "nist_review": state.get("nist_review"),
                "aicm_coverage": state.get("aicm_coverage"),
                "report_app_owner": state.get("report_app_owner"),
                "report_security_md": state.get("report_security_md"),
                "report_security_docx": state.get("report_security_docx"),
                "collector_enrichment": state.get("collector_enrichment"),
                "security_review_flags": state.get("security_review_flags", []),
                "audit_log": state.get("audit_log"),
                "summary": state.get("summary", ""),
            },
            indent=2,
        )
    )

    # --- Results location banner ---
    click.echo("\n" + "─" * 60)
    click.echo("📁  RESULTS")
    click.echo("─" * 60)
    _file_labels = [
        ("gap_analysis", "Gap analysis  "),
        ("backlog", "Backlog       "),
        ("sscf_report", "SSCF report   "),
        ("nist_review", "NIST review   "),
        ("aicm_coverage", "AICM coverage "),
        ("report_app_owner", "App owner MD  "),
        ("report_security_md", "Security MD   "),
        ("report_security_docx", "Security DOCX "),
        ("audit_log", "Audit log     "),
    ]
    for key, label in _file_labels:
        path = state.get(key)
        if path:
            click.echo(f"  {label}→  {path}")
    click.echo(f"  Loop result   →  {result_path}")
    click.echo("─" * 60)


if __name__ == "__main__":
    cli()
