"""
harness/tools.py — Anthropic tool schema definitions + subprocess dispatchers.

Each tool schema follows the Anthropic tool format (input_schema = JSON Schema).
dispatch(name, input_dict) runs the corresponding CLI as a subprocess and returns
its result as a JSON string. All output files are written to:
    docs/oscal-salesforce-poc/generated/<org>/<date>/

Raises RuntimeError on non-zero subprocess exit (stderr included in message).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_PYTHON = sys.executable
_ORG_ALIAS_HELP = "Org alias for output dir naming"

# Allowed output roots — all generated artifacts must land under one of these.
_ARTIFACT_ROOT = (_REPO / "docs" / "oscal-salesforce-poc" / "generated").resolve()
_APEX_ROOT = (_REPO / "docs" / "oscal-salesforce-poc" / "apex-scripts").resolve()


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
# Tool schema definitions (Anthropic format)
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
                    "description": "Path to gap_analysis.json from oscal_assess_assess",
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


def _run(args: list[str]) -> str:
    """Run subprocess, return stdout. Raise RuntimeError on non-zero exit."""
    result = subprocess.run(args, capture_output=True, text=True, cwd=_REPO)  # noqa: S603
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
    if inp.get("collector_output"):
        args += ["--collector-output", inp["collector_output"]]
    if inp.get("dry_run"):
        args.append("--dry-run")
    if inp.get("assessment_owner"):
        args += ["--assessment-owner", inp["assessment_owner"]]
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_path})


def _dispatch_gap_map(inp: dict[str, Any], out_dir: Path) -> str:
    out_md = _safe_out_path(inp.get("out_md"), out_dir / "matrix.md")
    out_json = _safe_out_path(inp.get("out_json"), out_dir / "backlog.json")
    controls_path = _REPO / "docs/oscal-salesforce-poc/generated/sbs_controls.json"
    mapping_path = _REPO / "config/oscal-salesforce/control_mapping.yaml"
    sscf_map_path = _REPO / "config/oscal-salesforce/sbs_to_sscf_mapping.yaml"
    args = [
        _PYTHON,
        "scripts/oscal_gap_map.py",
        "--controls",
        str(controls_path),
        "--gap-analysis",
        inp["gap_analysis"],
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
    audience = inp.get("audience", "security")
    args = [
        _PYTHON,
        "-m",
        "skills.report_gen.report_gen",
        "generate",
        "--backlog",
        inp["backlog"],
        "--audience",
        audience,
        "--out",
        out_path,
    ]
    if inp.get("sscf_benchmark"):
        args += ["--sscf-benchmark", inp["sscf_benchmark"]]
    if inp.get("nist_review"):
        args += ["--nist-review", inp["nist_review"]]
    if inp.get("org_alias"):
        args += ["--org-alias", inp["org_alias"]]
    if inp.get("title"):
        args += ["--title", inp["title"]]
    if inp.get("platform"):
        args += ["--platform", inp["platform"]]
    if inp.get("dry_run"):
        args.append("--dry-run")
    if inp.get("mock_llm"):
        args.append("--mock-llm")
    if inp.get("drift_report"):
        args += ["--drift-report", inp["drift_report"]]
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_path})


def _dispatch_nist_review(inp: dict[str, Any], out_dir: Path) -> str:
    out_path = _safe_out_path(inp.get("out"), out_dir / "nist_review.json")
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
    if inp.get("gap_analysis"):
        args += ["--gap-analysis", inp["gap_analysis"]]
    if inp.get("backlog"):
        args += ["--backlog", inp["backlog"]]
    if inp.get("dry_run"):
        args.append("--dry-run")
    _run(args)
    return json.dumps({"status": "ok", "output_file": out_path})


def _dispatch_sfdc_expert(inp: dict[str, Any], out_dir: Path) -> str:  # noqa: ARG001
    """Enrich gap_analysis findings that need expert Apex/admin review (Phase 1 stub)."""
    gap_path_str = inp.get("gap_analysis", "")
    if not gap_path_str:
        return json.dumps({"status": "error", "message": "gap_analysis path required"})

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
        apex_path = apex_dir / apex_filename
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
        finding["expert_notes"] = (
            f"Apex script staged at docs/oscal-salesforce-poc/apex-scripts/{apex_filename}. "
            f"Awaiting human review before execution."
        )
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
    baseline = inp.get("baseline")
    current = inp.get("current")
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


def _dispatch_finish(inp: dict[str, Any], out_dir: Path) -> str:  # noqa: ARG001
    """Sentinel: orchestrator signals pipeline is complete. Loop will break immediately."""
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
    "oscal_assess_assess": _dispatch_oscal_assess,
    "oscal_gap_map": _dispatch_gap_map,
    "sfdc_expert_enrich": _dispatch_sfdc_expert,
    "nist_review_assess": _dispatch_nist_review,
    "sscf_benchmark_benchmark": _dispatch_sscf_benchmark,
    "report_gen_generate": _dispatch_report_gen,
}


def dispatch(name: str, input_dict: dict[str, Any]) -> str:
    """Dispatch a named tool call; return JSON result string."""
    handler = _DISPATCHERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name!r}. Available: {list(_DISPATCHERS)}")
    org = input_dict.get("org", "unknown-org")
    out_dir = _out_dir(org)
    return handler(input_dict, out_dir)
