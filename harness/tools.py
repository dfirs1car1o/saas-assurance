"""
harness/tools.py — OpenAI tool schema definitions + subprocess dispatchers.

Each tool schema follows the OpenAI tool format (input_schema = JSON Schema).
dispatch(name, input_dict) runs the corresponding CLI as a subprocess and returns
its result as a JSON string. All output files are written to:
    docs/oscal-salesforce-poc/generated/<org>/<date>/

Raises RuntimeError on non-zero subprocess exit (stderr included in message).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.agents import load_agent_prompt

_REPO = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Agent sub-call client (injected by loop.py at startup via set_openai_client)
# ---------------------------------------------------------------------------

_AGENT_CLIENT: Any = None

_FLAG_PREFIX = "FLAG:"

# ---------------------------------------------------------------------------
# Canonical sub-agent response schema (v2)
# {
#   "status":   "ok" | "error" | "block",
#   "agent":    "<agent-name>",
#   "analysis": "<findings text>",
#   "flags":    ["FLAG:category:detail", ...],
#   "summary":  "<1-3 sentence summary>",
#   "severity": "info" | "warning" | "critical"
# }
# ---------------------------------------------------------------------------

# Agents that MUST return valid JSON — non-JSON responses are fail-closed.
# delivery-reviewer → status=block; all other strict agents → status=error.
_STRICT_AGENTS: frozenset[str] = frozenset(
    {"delivery-reviewer", "collector", "assessor", "sfdc-expert", "workday-expert"}
)


def set_openai_client(client: Any) -> None:
    """Inject the already-instantiated OpenAI client from loop.py.

    Called once at the top of _run_loop() before the agentic loop starts.
    Avoids creating a second client with separate retry/rate-limit state.
    Must be called before any _dispatch_agent_call() is invoked.
    """
    global _AGENT_CLIENT  # noqa: PLW0603
    _AGENT_CLIENT = client


# ---------------------------------------------------------------------------
# Agent response validation helpers (module-level to keep _validate_agent_response
# below the S3776 cognitive-complexity limit of 15)
# ---------------------------------------------------------------------------

_REQUIRED_STRICT: frozenset[str] = frozenset({"status", "agent", "analysis", "flags", "summary", "severity"})
_VALID_STATUS: frozenset[str] = frozenset({"ok", "error", "block"})
_VALID_SEVERITY: frozenset[str] = frozenset({"info", "warning", "critical"})


def _agent_violation_response(agent_name: str, field: str) -> dict:
    """Return a fail-closed schema-violation response for a strict agent."""
    block_status = "block" if agent_name == "delivery-reviewer" else "error"
    return {
        "status": block_status,
        "agent": agent_name,
        "analysis": "Schema violation — required field missing or invalid",
        "flags": [f"FLAG:schema_violation:{field}"],
        "summary": "",
        "severity": "critical",
    }


def _check_strict_schema(parsed: dict) -> str | None:
    """Return a violation description if the strict-agent schema is violated, else None."""
    missing = _REQUIRED_STRICT - parsed.keys()
    if missing:
        return "missing_fields_" + ",".join(sorted(missing))
    if parsed.get("severity") not in _VALID_SEVERITY:
        return f"invalid_severity_{parsed.get('severity')}"
    if not isinstance(parsed.get("flags"), list):
        return "flags_not_a_list"
    if any(not isinstance(f, str) for f in parsed["flags"]):
        return "flags_element_not_string"
    if parsed.get("status", "ok") not in _VALID_STATUS:
        return f"invalid_status_{parsed.get('status', 'ok')}"
    if not isinstance(parsed.get("summary"), str):
        return "summary_not_a_string"
    if not isinstance(parsed.get("analysis"), str) or not parsed.get("analysis"):
        return "analysis_empty_or_not_string"
    # agent field must be a non-empty string (exact-name match not enforced — models
    # self-identify from their system-prompt role name which may differ from the
    # internal dispatch key; the authoritative name is always agent_name from the caller)
    if not isinstance(parsed.get("agent"), str) or not parsed.get("agent"):
        return "agent_not_a_string"
    return None


def _build_strict_result(parsed: dict, agent_name: str) -> dict:
    """Assemble a canonical result dict from a schema-valid strict-agent response."""
    return {
        "status": parsed["status"],
        "agent": agent_name,  # always use authoritative dispatch name
        "analysis": parsed.get("analysis", ""),
        "flags": parsed["flags"],
        "summary": parsed.get("summary", ""),
        "severity": parsed["severity"],
    }


def _build_nonstrict_result(parsed: dict, agent_name: str, raw: str) -> dict:
    """Assemble a canonical result dict from a non-strict agent JSON response."""
    raw_status = parsed.get("status", "ok")
    analysis = parsed.get("analysis", raw)
    flags = parsed.get("flags")
    if not isinstance(flags, list):
        flags = [
            line.split(_FLAG_PREFIX, 1)[1].strip()
            for line in str(analysis).splitlines()
            if line.strip().startswith(_FLAG_PREFIX)
        ]
    return {
        "status": raw_status if raw_status in _VALID_STATUS else "ok",
        "agent": parsed.get("agent", agent_name),
        "analysis": analysis,
        "flags": flags,
        "summary": parsed.get("summary", ""),
        "severity": parsed.get("severity", "info"),
    }


def _handle_non_json_response(raw: str, agent_name: str) -> dict:
    """Handle an agent response that is not valid JSON.

    Strict agents fail closed; non-strict agents fall back to FLAG: line scraping.
    """
    import sys  # noqa: PLC0415

    if agent_name in _STRICT_AGENTS:
        print(  # noqa: T201
            f"[agent] ERROR: {agent_name} returned non-JSON response — pipeline blocked (fail-closed).",
            file=sys.stderr,
        )
        block_status = "block" if agent_name == "delivery-reviewer" else "error"
        return {
            "status": block_status,
            "agent": agent_name,
            "analysis": "Non-JSON response from strict agent — pipeline blocked",
            "flags": ["FLAG:parse_failure:non_json_response"],
            "summary": "",
            "severity": "critical",
        }

    print(  # noqa: T201
        f"[agent] WARNING: {agent_name} returned non-JSON response — falling back to FLAG: scraping.",
        file=sys.stderr,
    )
    flags = [
        line.split(_FLAG_PREFIX, 1)[1].strip() for line in raw.splitlines() if line.strip().startswith(_FLAG_PREFIX)
    ]
    return {"status": "ok", "agent": agent_name, "analysis": raw, "flags": flags, "summary": "", "severity": "info"}


def _validate_agent_response(raw: str, agent_name: str) -> dict:
    """Parse and validate an agent response string into a well-formed canonical dict.

    Strict agents (_STRICT_AGENTS) must return all 6 schema fields as valid JSON;
    non-JSON or schema-incomplete responses fail closed. Non-strict agents fall back
    to FLAG: line scraping. Always returns a dict with all 6 canonical fields.
    """
    try:
        candidate = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _handle_non_json_response(raw, agent_name)

    if not isinstance(candidate, dict):
        return _handle_non_json_response(raw, agent_name)

    if agent_name in _STRICT_AGENTS:
        violation = _check_strict_schema(candidate)
        if violation:
            return _agent_violation_response(agent_name, violation)
        return _build_strict_result(candidate, agent_name)

    return _build_nonstrict_result(candidate, agent_name, raw)


def _dispatch_agent_call(agent_name: str, system_prompt: str, user_content: str) -> str:
    """Make a direct OpenAI chat.completions call using an agent's system prompt.

    NOT a subprocess call — uses the injected client directly (shell=False satisfied).
    The model is read from LLM_MODEL_ANALYST env var (default: gpt-5.3-chat-latest).

    Returns a JSON string:
        {"status": "ok", "agent": "<name>", "analysis": "<text>", "flags": [...]}

    "flags" contains short slug tokens the orchestrator can act on. If the agent returns
    valid JSON with the required fields it is used directly; otherwise FLAG: line scraping
    is applied as a fallback (see _validate_agent_response).

    On failure returns a structured error payload so the orchestrator can continue
    rather than aborting the pipeline.
    """
    if _AGENT_CLIENT is None:
        return json.dumps(
            {
                "status": "error",
                "agent": agent_name,
                "message": "OpenAI client not injected — call set_openai_client() before dispatch.",
            }
        )
    model = os.getenv("LLM_MODEL_ANALYST", "gpt-5.3-chat-latest")
    json_instruction = (
        "\n\nYou MUST respond with a valid JSON object containing ALL of the following fields: "
        '"status" ("ok"|"error"|"block"), '
        '"agent" ("<agent-name>"), '
        '"analysis" ("<detailed findings text>"), '
        '"flags" (["FLAG:category:detail", ...] or []), '
        '"summary" ("<1-3 sentence summary>"), '
        '"severity" ("info"|"warning"|"critical"). '
        "No text outside the JSON object."
    )
    try:
        response = _AGENT_CLIENT.chat.completions.create(
            model=model,
            max_completion_tokens=2048,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt + json_instruction},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content or ""
        result = _validate_agent_response(raw, agent_name)
        return json.dumps(result)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {
                "status": "error",
                "agent": agent_name,
                "message": str(exc),
                "analysis": "",
                "flags": [],
            }
        )


_PYTHON = sys.executable
_ORG_ALIAS_HELP = "Org alias for output dir naming"
_GAP_ANALYSIS_HELP = "Path to gap_analysis.json from oscal_assess_assess"
_GAP_ANALYSIS_REQUIRED = "gap_analysis path required"

# Allowed output roots — all generated artifacts must land under one of these.
_ARTIFACT_ROOT = (_REPO / "docs" / "oscal-salesforce-poc" / "generated").resolve()
_APEX_ROOT = (_REPO / "docs" / "oscal-salesforce-poc" / "apex-scripts").resolve()

# Org alias: alphanumeric, hyphens, underscores only — prevents path traversal
# via LLM-provided values injected into directory paths (e.g., "../../tmp").
_ORG_ALIAS_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _sanitize_org(org: str) -> str:
    """Validate and return a safe org alias.

    LLM-provided org values flow directly into filesystem paths via _out_dir().
    Restricting the character set closes the path traversal vector before
    _safe_out_path() even runs.

    Raises ValueError on invalid aliases so _handle_tool_error() can surface
    the rejection rather than silently using a malformed path.
    """
    if not _ORG_ALIAS_RE.match(org):
        raise ValueError(f"Invalid org alias: {org!r}. Must match [a-zA-Z0-9_-]{{1,64}}.")
    return org


def _safe_inp_path(raw: str | None) -> str | None:
    """Validate that an LLM-provided input file path stays within the artifact tree.

    Mirrors _safe_out_path() for *input* file arguments (gap_analysis, backlog,
    collector_output, baseline, current, etc.).  Returns None for None inputs
    (optional fields).  Raises ValueError for paths that escape the allowed roots
    so the dispatcher surfaces a clear error instead of passing a traversal path
    to a subprocess argument.
    """
    if raw is None:
        return None
    target = Path(raw).resolve()
    if not (target.is_relative_to(_ARTIFACT_ROOT) or target.is_relative_to(_APEX_ROOT)):
        raise ValueError(
            f"Input path '{target}' is outside the allowed artifact root "
            f"({_ARTIFACT_ROOT}). LLM-provided input paths must be under "
            "docs/oscal-salesforce-poc/generated/."
        )
    return str(target)


def _safe_out_path(raw: str | None, default: Path) -> str:
    """Resolve and validate an output path is within the approved artifact tree.

    Rejects paths that escape via ``..`` or absolute traversal. Falls back to
    *default* when *raw* is None.

    Raises ValueError for paths outside the allowed roots so the dispatcher can
    surface a clear error instead of silently writing elsewhere.
    """
    target = Path(raw).resolve() if raw else default.resolve()
    if not (target.is_relative_to(_ARTIFACT_ROOT) or target.is_relative_to(_APEX_ROOT)):
        raise ValueError(
            f"Output path '{target}' is outside the allowed artifact root "
            f"({_ARTIFACT_ROOT}). All outputs must be under docs/oscal-salesforce-poc/generated/."
        )
    return str(target)


# ---------------------------------------------------------------------------
# Tool schema definitions (OpenAI tool format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "finish",
        "description": (
            "Signal that the assessment pipeline is complete and no further tool calls are needed. "
            "Call this immediately after the final report_gen_generate (security audience) tool call succeeds. "
            "Do NOT call any other tools after calling finish()."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One-sentence summary of what was completed and which output files were written.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "workday_connect_collect",
        "description": (
            "Collect security-relevant configuration from a Workday tenant (read-only). "
            "Uses OAuth 2.0 and calls SOAP/RaaS/REST APIs against the WSCC catalog (30 controls). "
            "Returns path to collector output JSON."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": "Org alias for output dir naming (overrides WD_ORG_ALIAS)"},
                "env": {
                    "type": "string",
                    "enum": ["dev", "test", "prod"],
                    "description": "Environment label for evidence tagging",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Print collection plan without making Workday API calls",
                },
            },
            "required": [],
        },
    },
    {
        "name": "sfdc_connect_collect",
        "description": (
            "Collect security-relevant configuration from a Salesforce org (read-only). "
            "Use scope='all' for a full assessment. Returns path to collector output JSON."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": "Org alias or instance URL (overrides SF_INSTANCE_URL)"},
                "scope": {
                    "type": "string",
                    "enum": [
                        "all",
                        "auth",
                        "access",
                        "event-monitoring",
                        "transaction-security",
                        "integrations",
                        "oauth",
                        "secconf",
                    ],
                    "description": "Which configuration scope(s) to collect",
                },
                "env": {
                    "type": "string",
                    "enum": ["dev", "test", "prod"],
                    "description": "Environment label for evidence tagging",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Print what would be collected without calling Salesforce API",
                },
            },
            "required": ["scope"],
        },
    },
    {
        "name": "oscal_assess_assess",
        "description": (
            "Run deterministic OSCAL gap assessment against SBS (Salesforce) or WSCC (Workday) controls. "
            "Takes platform collector output and produces gap_analysis.json. "
            "Use dry_run=true to emit realistic weak-org stub findings without a live connection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "platform": {
                    "type": "string",
                    "enum": ["salesforce", "workday"],
                    "description": "Platform to assess — determines control catalog (SBS vs WSCC)",
                },
                "collector_output": {
                    "type": "string",
                    "description": "Path to collector output JSON (omit if dry_run=true)",
                },
                "env": {
                    "type": "string",
                    "enum": ["dev", "test", "prod"],
                    "description": "Environment label",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Emit realistic stub findings without a real org connection",
                },
                "assessment_owner": {
                    "type": "string",
                    "description": "Named individual responsible for the assessment (NIST GOVERN compliance)",
                },
                "out": {"type": "string", "description": "Override output file path"},
            },
            "required": [],
        },
    },
    {
        "name": "oscal_gap_map",
        "description": (
            "Map gap-analysis findings to SSCF controls and produce a prioritised remediation backlog. "
            "Reads gap_analysis.json, writes matrix.md and backlog.json."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "gap_analysis": {
                    "type": "string",
                    "description": "Path to gap_analysis.json produced by oscal_assess_assess",
                },
                "out_md": {"type": "string", "description": "Override output path for matrix markdown"},
                "out_json": {"type": "string", "description": "Override output path for backlog JSON"},
            },
            "required": ["gap_analysis"],
        },
    },
    {
        "name": "report_gen_generate",
        "description": (
            "Generate governance output (DOCX or Markdown) from assessment backlog. "
            "Use audience='app-owner' for a plain-language report; "
            "'security' for a technical security governance review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "backlog": {"type": "string", "description": "Path to backlog.json from oscal_gap_map"},
                "audience": {
                    "type": "string",
                    "enum": ["app-owner", "security"],
                    "description": "Report audience",
                },
                "out": {"type": "string", "description": "Output file path (.md or .docx)"},
                "sscf_benchmark": {
                    "type": "string",
                    "description": "Optional path to sscf_report.json for domain heatmap",
                },
                "nist_review": {
                    "type": "string",
                    "description": "Optional path to nist_review.json for NIST AI RMF section",
                },
                "org_alias": {"type": "string", "description": "Org alias for report header"},
                "title": {"type": "string", "description": "Custom report title (overrides auto-generated title)"},
                "platform": {
                    "type": "string",
                    "enum": ["salesforce", "workday"],
                    "description": "Platform being assessed — drives OSCAL provenance table",
                },
                "dry_run": {"type": "boolean", "description": "Print plan without writing files"},
                "mock_llm": {
                    "type": "boolean",
                    "description": "Use deterministic template output — no API call. Required for CI/offline testing.",
                },
                "drift_report": {
                    "type": "string",
                    "description": "Path to drift_report.json from backlog_diff — adds regression section to report",
                },
                "aicm_coverage": {
                    "type": "string",
                    "description": "Path to aicm_coverage.json from gen_aicm_crosswalk — adds AICM section to annex",
                },
            },
            "required": ["backlog", "audience", "out"],
        },
    },
    {
        "name": "nist_review_assess",
        "description": (
            "Run NIST AI RMF 1.0 review against the assessment outputs (gap_analysis + backlog). "
            "Validates Govern, Map, Measure, Manage functions and produces a structured verdict JSON. "
            "Use dry_run=true for offline testing. Pass the output path to report_gen_generate as nist_review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "platform": {
                    "type": "string",
                    "enum": ["salesforce", "workday"],
                    "description": "Platform being assessed (determines stub verdicts in dry-run)",
                },
                "gap_analysis": {
                    "type": "string",
                    "description": "Path to gap_analysis.json produced by oscal_assess_assess",
                },
                "backlog": {
                    "type": "string",
                    "description": "Path to backlog.json produced by oscal_gap_map",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Produce realistic stub verdict without calling the API",
                },
                "out": {"type": "string", "description": "Override output file path"},
            },
            "required": [],
        },
    },
    {
        "name": "sfdc_expert_enrich",
        "description": (
            "Invoke the SFDC Expert agent to enrich partial/blocked findings that require "
            "Apex or deep admin analysis. Reads gap_analysis.json, adds expert_notes to "
            "eligible findings, and stages read-only Apex script proposals to "
            "docs/oscal-salesforce-poc/apex-scripts/. "
            "Only processes controls where needs_expert_review=true. "
            "Apex scripts require human review before execution — never run autonomously."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "gap_analysis": {
                    "type": "string",
                    "description": _GAP_ANALYSIS_HELP,
                },
            },
            "required": ["gap_analysis"],
        },
    },
    {
        "name": "backlog_diff",
        "description": (
            "Compare two assessment backlogs for the same org and produce a structured drift report. "
            "Identifies regressions (status worsened), improvements (status improved), resolved findings, "
            "new findings, and severity escalations. Outputs drift_report.json and drift_report.md. "
            "Use this before report_gen_generate on a re-assessment to surface drift to stakeholders."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "baseline": {
                    "type": "string",
                    "description": "Absolute path to the baseline backlog.json (earlier run)",
                },
                "current": {
                    "type": "string",
                    "description": "Absolute path to the current backlog.json (latest run)",
                },
                "out": {
                    "type": "string",
                    "description": "Override output path for drift_report.json (default: next to current backlog)",
                },
                "out_md": {
                    "type": "string",
                    "description": "Override output path for drift_report.md",
                },
            },
            "required": ["baseline", "current"],
        },
    },
    {
        "name": "sscf_benchmark_benchmark",
        "description": (
            "Benchmark the remediation backlog against the SSCF control index to produce "
            "a domain-level compliance scorecard (overall_score, overall_status, per-domain breakdown)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "backlog": {
                    "type": "string",
                    "description": "Path to backlog.json produced by oscal_gap_map",
                },
                "out": {"type": "string", "description": "Override output path for SSCF report JSON"},
            },
            "required": ["backlog"],
        },
    },
    {
        "name": "gen_aicm_crosswalk",
        "description": (
            "Generate a CSA AI Controls Matrix (AICM v1.0.3) coverage crosswalk from the assessment backlog. "
            "Maps SSCF findings to all 18 AICM domains and 243 controls, producing aicm_coverage.json. "
            "Call after oscal_gap_map. Pass the output to report_gen_generate as aicm_coverage "
            "to include the AICM annex in the security report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "backlog": {
                    "type": "string",
                    "description": "Path to backlog.json from oscal_gap_map",
                },
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "platform": {
                    "type": "string",
                    "enum": ["salesforce", "workday"],
                    "description": "Platform being assessed — determines AICM mapping scope",
                },
                "out": {"type": "string", "description": "Override output path for aicm_coverage.json"},
            },
            "required": ["backlog"],
        },
    },
    {
        "name": "collector_enrich",
        "description": (
            "Invoke the collector agent to review raw collector output for evidence quality, "
            "missing API scopes, and data_source issues before assessment runs. "
            "Call after sfdc_connect_collect or workday_connect_collect on live runs. "
            "Skip on dry-run (synthetic output has no real gaps to review). "
            "Returns analyst commentary and FLAG tokens — act on 'FLAG: missing_scope:*' "
            "tokens by noting them in reasoning before proceeding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "platform": {
                    "type": "string",
                    "enum": ["salesforce", "workday"],
                    "description": "Platform being assessed",
                },
                "collector_output": {
                    "type": "string",
                    "description": "Path to sfdc_raw.json or workday_raw.json from the collect step",
                },
            },
            "required": ["collector_output"],
        },
    },
    {
        "name": "assessor_analyze",
        "description": (
            "Invoke the assessor agent to review gap_analysis.json for confidence issues, "
            "unmapped findings, and controls requiring expert review. "
            "Call after oscal_assess_assess. "
            "If result flags 'expert_review_pending:*', call sfdc_expert_enrich (Salesforce) "
            "or workday_expert_enrich (Workday) BEFORE proceeding to oscal_gap_map. "
            "If result flags 'unmapped_findings_threshold_exceeded', surface to human."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "platform": {
                    "type": "string",
                    "enum": ["salesforce", "workday"],
                    "description": "Platform being assessed",
                },
                "gap_analysis": {
                    "type": "string",
                    "description": _GAP_ANALYSIS_HELP,
                },
            },
            "required": ["gap_analysis"],
        },
    },
    {
        "name": "workday_expert_enrich",
        "description": (
            "Invoke the Workday Expert agent to enrich findings that need ISSG permission guidance "
            "or RaaS report proposals. Workday-parallel to sfdc_expert_enrich. "
            "Processes controls where needs_expert_review=true or data_source=permission_denied. "
            "Writes expert_notes back to gap_analysis.json. "
            "Call after oscal_assess_assess on Workday assessments when assessor_analyze "
            "flags expert_review_pending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "gap_analysis": {
                    "type": "string",
                    "description": _GAP_ANALYSIS_HELP,
                },
            },
            "required": ["gap_analysis"],
        },
    },
    {
        "name": "security_reviewer_review",
        "description": (
            "Invoke the Security Reviewer agent for a final AppSec pass on the security report "
            "before finish() is called. Checks for credential exposure, status misrepresentation, "
            "and scope violations. "
            "Call after both report_gen_generate calls complete. "
            "If result flags 'credential_exposure:*' or 'scope_violation:*', surface to human "
            "and do NOT call finish() until acknowledged. "
            "'status_misrepresentation:*' is a warning only — does not block finish()."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": _ORG_ALIAS_HELP},
                "report_path": {
                    "type": "string",
                    "description": "Path to the security-audience report markdown file",
                },
            },
            "required": ["report_path"],
        },
    },
]


def _to_openai_tools(schemas: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in schemas
    ]


ALL_TOOLS = _to_openai_tools(TOOL_SCHEMAS)


# ---------------------------------------------------------------------------
# Output directory helper
# ---------------------------------------------------------------------------


def _out_dir(org: str) -> Path:
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    out = _REPO / "docs" / "oscal-salesforce-poc" / "generated" / org / date
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def _run(args: list[str], timeout: int = 300) -> str:
    """Run subprocess, return stdout. Raise RuntimeError on non-zero exit or timeout."""
    result = subprocess.run(args, capture_output=True, text=True, cwd=_REPO, timeout=timeout)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"Tool '{args[0]}' failed (exit {result.returncode}):\n{result.stderr.strip()}")
    return result.stdout


# ---------------------------------------------------------------------------
# Per-tool dispatchers
# ---------------------------------------------------------------------------


def _dispatch_workday_connect(inp: dict[str, Any], out_dir: Path) -> str:
    out_path = _safe_out_path(inp.get("out"), out_dir / "workday_raw.json")
    args = [
        _PYTHON,
        "-m",
        "skills.workday_connect.workday_connect",
        "collect",
        "--org",
        inp.get("org", "unknown-org"),
        "--env",
        inp.get("env", "dev"),
        "--out",
        out_path,
    ]
    if inp.get("dry_run"):
        args.append("--dry-run")
        _run(args)
        return json.dumps(
            {
                "status": "ok",
                "dry_run": True,
                "output_file": out_path,
                "note": "dry-run: Workday tenant not contacted; pass dry_run=true to oscal_assess_assess",
            }
        )
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_path})


def _dispatch_sfdc_connect(inp: dict[str, Any], out_dir: Path) -> str:
    out_path = _safe_out_path(inp.get("out"), out_dir / "sfdc_raw.json")
    args = [
        _PYTHON,
        "-m",
        "skills.sfdc_connect.sfdc_connect",
        "collect",
        "--scope",
        inp.get("scope", "all"),
        "--env",
        inp.get("env", "dev"),
    ]
    if inp.get("org"):
        args += ["--org", inp["org"]]
    if inp.get("dry_run"):
        # dry-run prints a message but writes nothing — return synthetic result
        args.append("--dry-run")
        _run(args)
        return json.dumps(
            {
                "status": "ok",
                "dry_run": True,
                "output_file": out_path,
                "note": "dry-run: org config not collected; pass dry_run=true to oscal_assess_assess",
            }
        )
    args += ["--out", out_path]
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_path})


def _dispatch_oscal_assess(inp: dict[str, Any], out_dir: Path) -> str:
    out_path = _safe_out_path(inp.get("out"), out_dir / "gap_analysis.json")
    collector_output = _safe_inp_path(inp.get("collector_output"))
    args = [
        _PYTHON,
        "-m",
        "skills.oscal_assess.oscal_assess",
        "assess",
        "--env",
        inp.get("env", "dev"),
        "--platform",
        inp.get("platform", "salesforce"),
        "--out",
        out_path,
    ]
    if collector_output:
        args += ["--collector-output", collector_output]
    if inp.get("dry_run"):
        args.append("--dry-run")
    assessment_owner = inp.get("assessment_owner")
    if isinstance(assessment_owner, str) and assessment_owner.strip() and assessment_owner.strip().lower() != "unknown":
        args += ["--assessment-owner", assessment_owner.strip()]
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_path})


def _dispatch_gap_map(inp: dict[str, Any], out_dir: Path) -> str:
    out_md = _safe_out_path(inp.get("out_md"), out_dir / "matrix.md")
    out_json = _safe_out_path(inp.get("out_json"), out_dir / "backlog.json")
    gap_analysis = _safe_inp_path(inp["gap_analysis"])  # required field
    controls_path = _REPO / "docs/oscal-salesforce-poc/generated/sbs_controls.json"
    mapping_path = _REPO / "config/oscal-salesforce/control_mapping.yaml"
    sscf_map_path = _REPO / "config/oscal-salesforce/sbs_to_sscf_mapping.yaml"
    args = [
        _PYTHON,
        "scripts/oscal_gap_map.py",
        "--controls",
        str(controls_path),
        "--gap-analysis",
        gap_analysis,
        "--mapping",
        str(mapping_path),
        "--sscf-map",
        str(sscf_map_path),
        "--out-md",
        out_md,
        "--out-json",
        out_json,
    ]
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_json})


def _report_gen_optional_args(inp: dict[str, Any]) -> list[str]:
    """Build the optional CLI flags for report-gen from the tool input dict."""
    extras: list[str] = []
    sscf_benchmark = _safe_inp_path(inp.get("sscf_benchmark"))
    nist_review = _safe_inp_path(inp.get("nist_review"))
    drift_report = _safe_inp_path(inp.get("drift_report"))
    aicm_coverage = _safe_inp_path(inp.get("aicm_coverage"))
    if sscf_benchmark:
        extras += ["--sscf-benchmark", sscf_benchmark]
    if nist_review:
        extras += ["--nist-review", nist_review]
    if inp.get("org_alias"):
        extras += ["--org-alias", inp["org_alias"]]
    if inp.get("title"):
        extras += ["--title", inp["title"]]
    if inp.get("platform"):
        extras += ["--platform", inp["platform"]]
    if inp.get("dry_run"):
        extras.append("--dry-run")
    if inp.get("mock_llm"):
        extras.append("--mock-llm")
    if drift_report:
        extras += ["--drift-report", drift_report]
    if aicm_coverage:
        extras += ["--aicm-coverage", aicm_coverage]
    return extras


def _dispatch_report_gen(inp: dict[str, Any], out_dir: Path) -> str:
    raw_out = inp.get("out")
    if raw_out:
        p = Path(raw_out)
        if p.is_absolute():
            candidate = p
        else:
            # Resolve relative filenames against the backlog's directory so reports
            # always land next to the data they came from, even when `org` is not
            # explicitly passed to this tool (the LLM uses `org_alias` instead).
            backlog = inp.get("backlog", "")
            anchor = Path(backlog).parent if backlog else out_dir
            candidate = anchor / p.name
        out_path = _safe_out_path(str(candidate), out_dir / "report.md")
    else:
        out_path = _safe_out_path(None, out_dir / "report.md")
    backlog = _safe_inp_path(inp["backlog"])  # required field
    audience = inp.get("audience", "security")
    args = [
        _PYTHON,
        "-m",
        "skills.report_gen.report_gen",
        "generate",
        "--backlog",
        backlog,
        "--audience",
        audience,
        "--out",
        out_path,
        *_report_gen_optional_args(inp),
    ]
    _run(args, timeout=600)  # report_gen makes LLM calls — allow up to 10 min
    return json.dumps({"status": "ok", "output_file": out_path})


def _dispatch_nist_review(inp: dict[str, Any], out_dir: Path) -> str:
    out_path = _safe_out_path(inp.get("out"), out_dir / "nist_review.json")
    gap_analysis = _safe_inp_path(inp.get("gap_analysis"))
    backlog = _safe_inp_path(inp.get("backlog"))
    args = [
        _PYTHON,
        "-m",
        "skills.nist_review.nist_review",
        "assess",
        "--out",
        out_path,
    ]
    if inp.get("platform"):
        args += ["--platform", inp["platform"]]
    if gap_analysis:
        args += ["--gap-analysis", gap_analysis]
    if backlog:
        args += ["--backlog", backlog]
    if inp.get("dry_run"):
        args.append("--dry-run")
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_path})


def _write_apex_placeholder(apex_path: Path, cid: str, date_str: str) -> None:
    """Stage a read-only Apex script placeholder for human review."""
    if not apex_path.exists():
        apex_path.write_text(
            f"// -- READ-ONLY -- sfdc-expert proposal for {cid}\n"
            f"// Generated: {date_str} | Status: PENDING HUMAN REVIEW\n"
            f"// Do NOT execute without System Administrator review.\n"
            f"// Replace this placeholder with a specific SOQL/Apex query.\n"
            f"//\n"
            f"// Control: {cid}\n"
            f"// Purpose: Surface data unavailable via sfdc-connect REST/SOQL API\n"
        )


def _call_sfdc_expert_note(cid: str, finding: dict[str, Any]) -> str:
    """Call sfdc-expert agent for per-finding guidance. Returns '' if unavailable."""
    if _AGENT_CLIENT is None:
        return ""
    finding_summary = json.dumps(
        {
            "control_id": cid,
            "status": finding.get("status"),
            "severity": finding.get("severity"),
            "observed_value": finding.get("observed_value", ""),
            "evidence_ref": finding.get("evidence_ref", ""),
        }
    )
    user_content = (
        f"Provide expert Salesforce/Apex guidance for this finding requiring specialist review.\n"
        f"Control: {cid}\n"
        f"Finding: {finding_summary}\n\n"
        f"Specify: (1) exact SOQL or Tooling API query to gather evidence, "
        f"(2) Salesforce permission required to run it, "
        f"(3) whether the finding is likely a genuine gap or a collector API limitation."
    )
    try:
        result_str = _dispatch_agent_call("sfdc-expert", load_agent_prompt("sfdc-expert"), user_content)
        result = json.loads(result_str)
        if result.get("status") == "ok":
            return result.get("analysis", "")[:600]
    except Exception:  # noqa: BLE001
        pass  # agent call failure must not abort the enrichment loop
    return ""


def _dispatch_sfdc_expert(inp: dict[str, Any], out_dir: Path) -> str:  # noqa: ARG001
    """Enrich gap_analysis findings that need expert Apex/admin review.

    For each eligible finding: stages an Apex script placeholder AND calls the
    sfdc-expert agent for per-finding specialist notes written into expert_notes.
    """
    gap_path_str = inp.get("gap_analysis", "")
    if not gap_path_str:
        return json.dumps({"status": "error", "message": _GAP_ANALYSIS_REQUIRED})

    gap_path = Path(gap_path_str)
    if not gap_path.exists():
        return json.dumps({"status": "error", "message": f"gap_analysis not found: {gap_path}"})

    try:
        data = json.loads(gap_path.read_text())
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"status": "error", "message": f"Could not read gap_analysis: {exc}"})

    apex_dir = _REPO / "docs" / "oscal-salesforce-poc" / "apex-scripts"
    apex_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    enriched = 0

    for finding in data.get("findings", []):
        if not finding.get("needs_expert_review"):
            continue
        cid = finding["control_id"]
        apex_filename = f"{cid}_{date_str}.apex"
        _write_apex_placeholder(apex_dir / apex_filename, cid, date_str)
        agent_note = _call_sfdc_expert_note(cid, finding)
        apex_note = (
            f"Apex script staged at docs/oscal-salesforce-poc/apex-scripts/{apex_filename}. "
            f"Awaiting human review before execution."
        )
        finding["expert_notes"] = f"{apex_note}\n{agent_note}".strip() if agent_note else apex_note
        enriched += 1

    gap_path = gap_path.resolve()
    gap_path.write_text(json.dumps(data, indent=2))  # NOSONAR — intentional CLI output path
    return json.dumps(
        {
            "status": "ok",
            "enriched_findings": enriched,
            "output_file": str(gap_path),
            "apex_scripts_dir": str(apex_dir),
        }
    )


def _dispatch_backlog_diff(inp: dict[str, Any], out_dir: Path) -> str:
    """Run drift_check.py to compare two backlogs."""
    baseline = _safe_inp_path(inp.get("baseline"))
    current = _safe_inp_path(inp.get("current"))
    if not baseline or not current:
        return json.dumps({"status": "error", "message": "baseline and current paths are required"})
    args = [_PYTHON, "scripts/drift_check.py", "--baseline", baseline, "--current", current]
    if inp.get("out"):
        safe_out = _safe_out_path(inp["out"], out_dir / "drift_report.json")
        args += ["--out", safe_out]
    if inp.get("out_md"):
        safe_md = _safe_out_path(inp["out_md"], out_dir / "drift_report.md")
        args += ["--out-md", safe_md]
    return _run(args)


def _dispatch_aicm_crosswalk(inp: dict[str, Any], out_dir: Path) -> str:
    """Generate AICM v1.0.3 coverage crosswalk from the assessment backlog."""
    out_path = _safe_out_path(inp.get("out"), out_dir / "aicm_coverage.json")
    backlog = _safe_inp_path(inp["backlog"])  # required field
    args = [_PYTHON, "scripts/gen_aicm_crosswalk.py", "--backlog", backlog, "--out", out_path]
    if inp.get("org"):
        args += ["--org", inp["org"]]
    if inp.get("platform"):
        args += ["--platform", inp["platform"]]
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_path})


def _dispatch_collector_enrich(inp: dict[str, Any], out_dir: Path) -> str:  # noqa: ARG001
    """Invoke the collector agent to review raw collector output for evidence quality.

    Checks for missing API scopes, stale evidence refs, and data_source issues
    before assessment runs. Returns commentary + FLAG tokens the orchestrator acts on.
    Skip on dry-run (synthetic collector output has no real gaps to review).
    """
    collector_output = _safe_inp_path(inp.get("collector_output"))
    if not collector_output:
        return json.dumps({"status": "error", "agent": "collector", "message": "collector_output path required"})
    try:
        raw_text = Path(collector_output).read_text()
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"status": "error", "agent": "collector", "message": f"Could not read: {exc}"})

    platform = inp.get("platform", "salesforce")
    org = inp.get("org", "unknown-org")
    user_content = (
        f"Review the following raw collector output for {platform} org '{org}'.\n"
        "Identify: (1) missing API scopes or API limitations affecting assessment completeness, "
        "(2) controls recorded as not_applicable that a different scope would have resolved, "
        "(3) data quality issues (missing timestamps, empty evidence_ref).\n"
        "For each issue found, emit a line starting with 'FLAG: <slug>', e.g. "
        "'FLAG: missing_scope:event-monitoring' or 'FLAG: stale_evidence:SBS-LOG-001'.\n\n"
        f"Collector output (truncated to 4000 chars):\n{raw_text[:4000]}"
    )
    return _dispatch_agent_call("collector", load_agent_prompt("collector"), user_content)


def _dispatch_assessor_analyze(inp: dict[str, Any], out_dir: Path) -> str:  # noqa: ARG001
    """Invoke the assessor agent to review gap_analysis findings for confidence issues.

    Checks mapping_confidence on critical/high findings, controls still needing expert
    review, and whether unmapped findings exceed 20%. Returns FLAG tokens the orchestrator
    uses to decide whether sfdc_expert_enrich or workday_expert_enrich should run before
    proceeding to oscal_gap_map.
    """
    gap_analysis = _safe_inp_path(inp.get("gap_analysis"))
    if not gap_analysis:
        return json.dumps({"status": "error", "agent": "assessor", "message": _GAP_ANALYSIS_REQUIRED})
    try:
        data = json.loads(Path(gap_analysis).read_text())
        summary = [
            {
                "control_id": f.get("control_id"),
                "status": f.get("status"),
                "severity": f.get("severity"),
                "needs_expert_review": f.get("needs_expert_review", False),
                "data_source": f.get("data_source"),
                "mapping_confidence": f.get("mapping_confidence"),
            }
            for f in data.get("findings", [])
        ]
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"status": "error", "agent": "assessor", "message": f"Could not read gap_analysis: {exc}"})

    platform = inp.get("platform", "salesforce")
    user_content = (
        f"Review the following {platform} gap analysis findings summary.\n"
        "Identify: (1) critical/high findings with low mapping_confidence needing review, "
        "(2) controls with needs_expert_review=true that lack expert_notes, "
        "(3) whether >20% of findings are unmapped.\n"
        "For each concern emit 'FLAG: <slug>' on its own line. Examples:\n"
        "  FLAG: low_confidence_critical:SBS-AUTH-001\n"
        "  FLAG: expert_review_pending:SBS-ACS-005\n"
        "  FLAG: unmapped_findings_threshold_exceeded\n\n"
        f"Findings summary:\n{json.dumps(summary, indent=2)[:5000]}"
    )
    return _dispatch_agent_call("assessor", load_agent_prompt("assessor"), user_content)


def _parse_workday_expert_notes(analysis: str) -> dict[str, str]:
    """Parse workday-expert analysis text into a per-control-id notes dict.

    Expected format: "Control: <WD-ID>\\nGap: ...\\nFix: ...\\nAPI: ..."
    """
    per_finding_notes: dict[str, str] = {}
    current_cid: str | None = None
    current_lines: list[str] = []
    for line in analysis.splitlines():
        if line.startswith("Control:"):
            if current_cid and current_lines:
                per_finding_notes[current_cid] = "\n".join(current_lines).strip()
            current_cid = line.split(":", 1)[1].strip()
            current_lines = [line]
        elif current_cid:
            current_lines.append(line)
    if current_cid and current_lines:
        per_finding_notes[current_cid] = "\n".join(current_lines).strip()
    return per_finding_notes


def _apply_workday_expert_notes(
    eligible: list[dict[str, Any]],
    per_finding_notes: dict[str, str],
    analysis: str,
) -> None:
    """Write expert_notes into each eligible finding in-place."""
    for finding in eligible:
        if finding.get("expert_notes"):
            continue
        cid = finding.get("control_id", "")
        if cid in per_finding_notes:
            finding["expert_notes"] = f"[workday-expert] {per_finding_notes[cid]}\nAwaiting human review."
        else:
            finding["expert_notes"] = f"[workday-expert][generic] {analysis[:500]}\nAwaiting human review."


def _dispatch_workday_expert_enrich(inp: dict[str, Any], out_dir: Path) -> str:  # noqa: ARG001
    """Invoke the Workday Expert agent to enrich permission-denied findings.

    Workday-parallel to sfdc_expert_enrich. Produces ISSG permission guidance and
    RaaS report proposals for controls where needs_expert_review=true or
    data_source=permission_denied. Writes expert_notes back to gap_analysis.json.
    """
    gap_path_str = inp.get("gap_analysis", "")
    if not gap_path_str:
        return json.dumps({"status": "error", "message": _GAP_ANALYSIS_REQUIRED})
    gap_path = Path(gap_path_str)
    if not gap_path.exists():
        return json.dumps({"status": "error", "message": f"gap_analysis not found: {gap_path}"})
    try:
        data = json.loads(gap_path.read_text())
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"status": "error", "message": f"Could not read gap_analysis: {exc}"})

    eligible = [
        f
        for f in data.get("findings", [])
        if f.get("needs_expert_review") or f.get("data_source") == "permission_denied"
    ]
    if not eligible:
        return json.dumps(
            {
                "status": "ok",
                "agent": "workday-expert",
                "enriched_findings": 0,
                "output_file": str(gap_path),
                "note": "No findings required workday-expert review.",
            }
        )

    eligible_summary = json.dumps(
        [
            {
                "control_id": f.get("control_id"),
                "status": f.get("status"),
                "severity": f.get("severity"),
                "observed_value": f.get("observed_value", ""),
                "evidence_ref": f.get("evidence_ref", ""),
            }
            for f in eligible
        ],
        indent=2,
    )[:4000]
    user_content = (
        "The following Workday findings require expert review — either permission_denied "
        "or needs_expert_review=true.\n\n"
        "For each control: (1) identify which Workday domain security policy grant is missing, "
        "(2) specify the exact RaaS report or REST endpoint that provides the evidence, "
        "(3) state whether an ISSG grant resolves it or tenant admin manual confirmation is required.\n\n"
        "Format each as:\nControl: <WD-ID>\nGap: <what is missing>\n"
        "Fix: <ISSG domain permission or manual check>\nAPI: <RaaS report or REST endpoint>\n\n"
        f"Findings requiring expert review:\n{eligible_summary}"
    )
    result_str = _dispatch_agent_call("workday-expert", load_agent_prompt("workday-expert"), user_content)
    try:
        result = json.loads(result_str)
        if result.get("status") == "ok":
            analysis = result.get("analysis", "")
            per_finding_notes = _parse_workday_expert_notes(analysis)
            _apply_workday_expert_notes(eligible, per_finding_notes, analysis)
        gap_path = gap_path.resolve()
        gap_path.write_text(json.dumps(data, indent=2))  # NOSONAR — intentional artifact path
        result["enriched_findings"] = len(eligible)
        result["output_file"] = str(gap_path)
        return json.dumps(result)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"status": "error", "message": f"Failed to write enriched findings: {exc}"})


def _dispatch_security_reviewer_review(inp: dict[str, Any], out_dir: Path) -> str:  # noqa: ARG001
    """Invoke the security-reviewer agent for a final AppSec pass on the security report.

    Checks for credential exposure, status misrepresentation, and scope violations.
    Returns FLAG tokens — credential_exposure and scope_violation flags should delay
    finish() until the human acknowledges them. status_misrepresentation is a warning only.
    """
    report_path_str = inp.get("report_path", "")
    if not report_path_str:
        return json.dumps({"status": "error", "agent": "delivery-reviewer", "message": "report_path required"})
    report_path = _safe_inp_path(report_path_str)
    if not report_path:
        return json.dumps(
            {
                "status": "error",
                "agent": "delivery-reviewer",
                "message": f"report_path failed safety validation: {report_path_str}",
            }
        )
    try:
        report_text = Path(report_path).read_text()
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"status": "error", "agent": "delivery-reviewer", "message": f"Could not read report: {exc}"})

    user_content = (
        "Review the following security assessment report for delivery to a human stakeholder.\n"
        "Check three areas and respond in JSON with fields: status, agent, analysis, flags, summary.\n"
        "1. Credentials, org URLs, usernames, or internal identifiers that should not appear "
        "   in a deliverable — add 'FLAG: credential_exposure:<detail>' to the flags array.\n"
        "2. Language in any finding that downplays or softens a fail/critical status — "
        "   add 'FLAG: status_misrepresentation:<control_id>' to the flags array.\n"
        "3. Any section granting or implying permissions beyond the read-only OSCAL/SSCF "
        "   assessment scope in mission.md — add 'FLAG: scope_violation:<section>' to the flags array.\n\n"
        "Set 'summary' to 1-3 sentences on overall delivery readiness. "
        "Set 'status' to 'ok' if no blocking flags, 'block' if credential_exposure or scope_violation found.\n\n"
        f"Report content (truncated to 6000 chars):\n{report_text[:6000]}"
    )
    return _dispatch_agent_call("delivery-reviewer", load_agent_prompt("delivery-reviewer"), user_content)


def _dispatch_finish(inp: dict[str, Any], out_dir: Path) -> str:  # noqa: ARG001
    """Sentinel: orchestrator signals pipeline is complete. Loop will break immediately.

    Blocks completion if security_review_flags contains any credential_exposure:* or
    scope_violation:* flags — these require human acknowledgement before delivery.
    status_misrepresentation:* flags are warning-only and do not block.
    """
    review_flags: list[str] = inp.get("security_review_flags", [])
    blocking_flags = [
        f for f in review_flags if f.startswith("credential_exposure:") or f.startswith("scope_violation:")
    ]
    if blocking_flags:
        return json.dumps(
            {
                "status": "blocked",
                "reason": "Unresolved delivery-review flags require human acknowledgement",
                "flags": blocking_flags,
            }
        )
    return json.dumps({"status": "ok", "pipeline_complete": True, "summary": inp.get("summary", "")})


def _dispatch_sscf_benchmark(inp: dict[str, Any], out_dir: Path) -> str:
    out_path = _safe_out_path(inp.get("out"), out_dir / "sscf_report.json")
    sscf_index = _REPO / "config/sscf_control_index.yaml"
    args = [
        _PYTHON,
        "-m",
        "skills.sscf_benchmark.sscf_benchmark",
        "benchmark",
        "--backlog",
        inp["backlog"],
        "--sscf-index",
        str(sscf_index),
        "--out",
        out_path,
    ]
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_path})


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

_DISPATCHERS = {
    "finish": _dispatch_finish,
    "backlog_diff": _dispatch_backlog_diff,
    "workday_connect_collect": _dispatch_workday_connect,
    "sfdc_connect_collect": _dispatch_sfdc_connect,
    "collector_enrich": _dispatch_collector_enrich,
    "oscal_assess_assess": _dispatch_oscal_assess,
    "assessor_analyze": _dispatch_assessor_analyze,
    "oscal_gap_map": _dispatch_gap_map,
    "sfdc_expert_enrich": _dispatch_sfdc_expert,
    "workday_expert_enrich": _dispatch_workday_expert_enrich,
    "nist_review_assess": _dispatch_nist_review,
    "sscf_benchmark_benchmark": _dispatch_sscf_benchmark,
    "gen_aicm_crosswalk": _dispatch_aicm_crosswalk,
    "report_gen_generate": _dispatch_report_gen,
    "security_reviewer_review": _dispatch_security_reviewer_review,
}


def dispatch(name: str, input_dict: dict[str, Any]) -> str:
    """Dispatch a named tool call; return JSON result string."""
    handler = _DISPATCHERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name!r}. Available: {list(_DISPATCHERS)}")
    org = _sanitize_org(input_dict.get("org", "unknown-org"))
    out_dir = _out_dir(org)
    return handler(input_dict, out_dir)
