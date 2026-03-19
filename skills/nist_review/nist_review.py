"""
nist_review — NIST AI RMF 1.0 review skill.

Validates the multi-agent assessment outputs against NIST AI RMF 1.0
(Govern, Map, Measure, Manage) and produces a structured verdict JSON.

Usage:
    nist-review assess --gap-analysis <path> --backlog <path> --out <path>
    nist-review assess --dry-run --gap-analysis <path> --out <path>
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
load_dotenv(_REPO / ".env")

# ---------------------------------------------------------------------------
# Dry-run stub verdict (realistic weak-org scenario)
# ---------------------------------------------------------------------------

_DRY_RUN_VERDICTS: dict[str, dict[str, Any]] = {
    "salesforce": {
        "nist_ai_rmf_review": {
            "assessment_id": "sfdc-assess-dry-run",
            "reviewed_at_utc": "",  # filled at runtime
            "reviewer": "nist-reviewer",
            "govern": {
                "status": "pass",
                "notes": (
                    "Human accountability defined in mission.md. "
                    "Assessment scope bounded to sfdc-connect collector output only. "
                    "Override and escalation path documented via --approve-critical flag."
                ),
            },
            "map": {
                "status": "partial",
                "notes": (
                    "Dry-run mode clearly noted; no live Salesforce API call made. "
                    "AI-generated findings distinguished from human-verified via dry_run flag in assessment_id. "
                    "SBS catalog version (0.4.0) documented. "
                    "Stub scenario limitations explicitly disclosed in assessment metadata."
                ),
            },
            "measure": {
                "status": "pass",
                "notes": (
                    "Mapping confidence tracked via status/severity per finding. "
                    "Unmapped controls explicitly listed as not_applicable (13 findings). "
                    "SSCF heatmap complete across all 7 domains. "
                    "2 domains (Governance Risk Compliance, Threat Detection Response) "
                    "have no assessed controls in current SBS catalog -- noted as N/A."
                ),
            },
            "manage": {
                "status": "partial",
                "notes": (
                    "Critical findings (4) flagged for human review gate. "
                    "Remediation actions provided for all critical/high findings. "
                    "Owner and due_date fields absent in dry-run stub scenario -- "
                    "required before live assessment delivery to governance committee."
                ),
            },
            "overall": "flag",
            "blocking_issues": [],
            "recommendations": [
                "Add owner and due_date to all critical/fail backlog items before live delivery.",
                "Replace dry-run stub with live sfdc-connect collection before governance committee review.",
            ],
        }
    },
    "workday": {
        "nist_ai_rmf_review": {
            "assessment_id": "wd-assess-dry-run",
            "reviewed_at_utc": "",  # filled at runtime
            "reviewer": "nist-reviewer",
            "govern": {
                "status": "pass",
                "notes": (
                    "Human accountability defined in mission.md. "
                    "Assessment scope bounded to workday-connect collector output only. "
                    "Override and escalation path documented via --approve-critical flag."
                ),
            },
            "map": {
                "status": "partial",
                "notes": (
                    "Dry-run mode clearly noted; no live Workday API call made. "
                    "AI-generated findings distinguished from human-verified via dry_run flag in assessment_id. "
                    "Workday Security Control Catalog (WSCC) v0.2.0 documented. "
                    "Stub scenario limitations explicitly disclosed in assessment metadata. "
                    "9 manual controls (TDR, CKM-002, CON-005, LOG-001/003/005, GOV-001) "
                    "not assessable via API -- require Workday admin confirmation."
                ),
            },
            "measure": {
                "status": "pass",
                "notes": (
                    "Mapping confidence tracked via status/severity per finding. "
                    "Unmapped controls explicitly listed as not_applicable (9 findings). "
                    "SSCF heatmap complete across assessed domains. "
                    "Threat Detection Response domain is manual-only -- noted as N/A. "
                    "Due dates populated for all critical/high/moderate fail findings."
                ),
            },
            "manage": {
                "status": "partial",
                "notes": (
                    "4 critical findings (2 fail, 2 partial) flagged for human review gate. "
                    "Due dates assigned to all fail findings per severity SLA. "
                    "Partial findings require RaaS report access before definitive pass/fail -- "
                    "provision workday-connect ISSG with required domain permissions before live run."
                ),
            },
            "overall": "flag",
            "blocking_issues": [],
            "recommendations": [
                "Provision workday-connect ISSG with domain permissions for RaaS reports before live run.",
                "Replace dry-run stub with live workday-connect collection before governance committee review.",
                "Assign named assessment owner (individual) rather than team label for governance traceability.",
            ],
        }
    },
}

# Keep backward-compat alias (used by existing callers that don't pass --platform)
_DRY_RUN_VERDICT = _DRY_RUN_VERDICTS["salesforce"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        click.echo(f"ERROR: file not found: {p}", err=True)
        sys.exit(1)
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        click.echo(f"ERROR: invalid JSON in {p}: {exc}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Context builder — deterministic summarizer (replaces [:6000] truncation)
# ---------------------------------------------------------------------------


def _build_review_context(assessment_id: str, gap_data: dict[str, Any], backlog_data: dict[str, Any]) -> str:
    """Build a structured review context that always includes all critical/high findings.

    Produces a token-efficient summary instead of raw JSON truncation, ensuring
    the NIST gate never silently drops critical findings.

    MEASURE note: mapping_confidence="low" is assigned exclusively to not_applicable findings
    (controls outside the API collector scope — code review, CI/CD, manual governance, etc.).
    The NIST MEASURE flag threshold (>30% low confidence) must be evaluated against
    *assessable* findings only (pass + fail + partial), NOT against the full catalog count
    which includes structurally out-of-scope controls.  The derived fields
    ``low_confidence_assessable_count`` and ``low_confidence_assessable_pct`` reflect
    this correct denominator and are what should be used for the >30% threshold check.
    """
    # --- gap_analysis summary ---
    findings = gap_data.get("findings", [])
    total = len(findings)
    by_status: dict[str, list[dict]] = {}
    for f in findings:
        by_status.setdefault(f.get("status", "unknown"), []).append(f)

    status_counts = {s: len(v) for s, v in by_status.items()}

    # Always include every critical + high finding in full
    priority_findings = [
        f for f in findings if f.get("severity") in ("critical", "high") and f.get("status") in ("fail", "partial")
    ]

    # Collect needs_expert_review control IDs from gap_analysis for explicit MEASURE tracking
    needs_expert_review_ids = [f.get("control_id") for f in findings if f.get("needs_expert_review")]

    gap_summary = {
        "assessment_id": assessment_id,
        "total_findings": total,
        "status_counts": status_counts,
        "priority_findings_full": priority_findings,
        "needs_expert_review_ids": needs_expert_review_ids,
        "needs_expert_review_count": len(needs_expert_review_ids),
    }

    # --- backlog summary ---
    items = backlog_data.get("mapped_items", [])
    priority_items = [
        i for i in items if i.get("severity") in ("critical", "high") and i.get("status") in ("fail", "partial")
    ]
    bl_summary = backlog_data.get("summary", {})
    conf_counts = bl_summary.get("mapping_confidence_counts", {})

    # Compute low_confidence among ASSESSABLE findings only (exclude not_applicable).
    # not_applicable findings are structurally low-confidence (outside API scope) and must
    # not be counted against the >30% threshold, which targets assessment quality of
    # findings that WERE evaluated.
    assessable_items = [i for i in items if i.get("status") != "not_applicable"]
    low_conf_assessable = [i for i in assessable_items if i.get("mapping_confidence") == "low"]
    assessable_count = len(assessable_items)
    low_conf_assessable_count = len(low_conf_assessable)
    low_conf_assessable_pct = round(low_conf_assessable_count / assessable_count * 100, 1) if assessable_count else 0.0

    # Collect needs_expert_review items and their expert_review_status from backlog
    needs_review_items = [i for i in items if i.get("needs_expert_review")]
    needs_review_with_status = [
        {
            "control_id": i.get("sbs_control_id", i.get("legacy_control_id")),
            "expert_review_status": i.get("expert_review_status"),
        }
        for i in needs_review_items
    ]

    backlog_summary = {
        # governance metadata — required by NIST GOVERN / MAP / MEASURE functions
        "assessment_owner": backlog_data.get("assessment_owner"),
        "data_source": backlog_data.get("data_source"),
        "ai_generated_findings_notice": backlog_data.get("ai_generated_findings_notice"),
        "org": backlog_data.get("org"),
        "platform": backlog_data.get("platform"),
        # findings metadata
        "overall_score": backlog_data.get("overall_score"),
        "total_items": len(items),
        "not_applicable_count": len(items) - assessable_count,
        "assessable_count": assessable_count,
        "unmapped_findings": bl_summary.get("unmapped_findings", 0),
        # Raw confidence counts across ALL items (including not_applicable).
        "mapping_confidence_counts": conf_counts,
        # Derived: low confidence among assessable findings ONLY — use this for >30% threshold.
        # not_applicable findings are always low-confidence (outside API collector scope)
        # and are NOT assessment-quality defects.
        "low_confidence_assessable_count": low_conf_assessable_count,
        "low_confidence_assessable_pct": low_conf_assessable_pct,
        "measure_note": (
            "mapping_confidence='low' applies exclusively to not_applicable findings "
            "(controls outside the API collector scope). The >30% low-confidence FLAG "
            "threshold applies to assessable findings (pass+fail+partial) only. "
            f"Assessable findings: {assessable_count}. "
            f"Low-confidence assessable findings: {low_conf_assessable_count} "
            f"({low_conf_assessable_pct}%)."
        ),
        # needs_expert_review tracking
        "needs_expert_review_count": len(needs_review_items),
        "needs_expert_review_items": needs_review_with_status,
        "priority_items_full": priority_items,
        "iso27001_summary": backlog_data.get("iso27001_summary"),
    }

    context = json.dumps({"gap_summary": gap_summary, "backlog_summary": backlog_summary}, indent=2)

    return (
        f"Review these assessment outputs for assessment_id={assessment_id}.\n\n"
        f"<assessment_context>\n{context}\n</assessment_context>\n\n"
        "Return ONLY the JSON verdict. No text outside the JSON object."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """nist-review — NIST AI RMF 1.0 compliance review skill."""


@cli.command()
@click.option("--gap-analysis", "gap_analysis", default=None, help="Path to gap_analysis.json.")
@click.option("--backlog", default=None, help="Path to backlog.json.")
@click.option("--out", required=True, help="Output path for nist_review.json.")
@click.option("--dry-run", is_flag=True, help="Produce realistic stub verdict without calling the API.")
@click.option(
    "--platform",
    default="salesforce",
    type=click.Choice(["salesforce", "workday"]),
    help="Platform being assessed — selects the correct dry-run stub language.",
)
def assess(gap_analysis: str | None, backlog: str | None, out: str, dry_run: bool, platform: str) -> None:  # NOSONAR
    """Run NIST AI RMF review against assessment outputs."""
    out_path = Path(out)

    if dry_run:
        import copy

        stub = _DRY_RUN_VERDICTS.get(platform, _DRY_RUN_VERDICT)
        verdict = copy.deepcopy(stub)
        verdict["nist_ai_rmf_review"]["reviewed_at_utc"] = datetime.now(UTC).isoformat()
        if gap_analysis:
            try:
                data = _load_json(gap_analysis)
                default_id = f"{platform}-assess-dry-run"
                verdict["nist_ai_rmf_review"]["assessment_id"] = data.get("assessment_id", default_id)
            except SystemExit as exc:
                click.echo(f"WARNING: Could not load gap_analysis for assessment_id: {exc}", err=True)
                raise
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(verdict, indent=2))
        click.echo(f"nist-review [DRY-RUN]: wrote stub verdict -> {out_path}", err=True)
        return

    # Live mode: call OpenAI API with nist-reviewer system prompt
    if not gap_analysis or not backlog:
        click.echo("ERROR: --gap-analysis and --backlog are required for live mode.", err=True)
        sys.exit(1)

    try:
        import openai
    except ImportError:
        click.echo("ERROR: openai package not installed.", err=True)
        sys.exit(1)

    api_key = os.getenv("OPENAI_API_KEY")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not api_key and not (azure_key and azure_endpoint):
        click.echo("ERROR: set OPENAI_API_KEY or both AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT.", err=True)
        sys.exit(1)

    gap_data = _load_json(gap_analysis)
    backlog_data = _load_json(backlog)
    assessment_id = gap_data.get("assessment_id", "unknown")

    reviewer_md = _REPO / "agents" / "nist-reviewer.md"
    _json_schema_instruction = (
        "\n\nYou MUST respond with a valid JSON object. "
        "Required schema: "
        '{"nist_ai_rmf_review": {'
        '"assessment_id": "<id>", '
        '"reviewed_at_utc": "<iso8601>", '
        '"reviewer": "nist-reviewer", '
        '"govern": {"status": "pass|partial|fail", "notes": "<text>"}, '
        '"map": {"status": "pass|partial|fail", "notes": "<text>"}, '
        '"measure": {"status": "pass|partial|fail", "notes": "<text>"}, '
        '"manage": {"status": "pass|partial|fail", "notes": "<text>"}, '
        '"overall": "pass|flag|block", '
        '"blocking_issues": [...], '
        '"recommendations": [...]'
        "}}. No text outside the JSON object."
    )
    system_prompt = (
        (reviewer_md.read_text() + _json_schema_instruction)
        if reviewer_md.exists()
        else (
            "You are a NIST AI RMF 1.0 reviewer. "
            "Validate the assessment outputs against Govern, Map, Measure, Manage functions. "
            "Return ONLY a JSON verdict in the format specified." + _json_schema_instruction
        )
    )

    user_msg = _build_review_context(assessment_id, gap_data, backlog_data)

    if azure_key and azure_endpoint:
        client = openai.AzureOpenAI(
            api_key=azure_key,
            azure_endpoint=azure_endpoint,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
    else:
        client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("LLM_MODEL_ANALYST", "gpt-5.3-chat-latest"),
        max_completion_tokens=2048,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    )
    raw = response.choices[0].message.content.strip()

    # Primary parse: response_format=json_object guarantees valid JSON from the API.
    # Strip markdown code fences defensively in case the model wraps anyway.
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])

    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("nist_review: structured parse failed — returning explicit review-required verdict")
        _fail_note = "Structured parse failure — verdict is unverified."
        verdict = {
            "nist_ai_rmf_review": {
                "assessment_id": assessment_id,
                "reviewed_at_utc": datetime.now(UTC).isoformat(),
                "reviewer": "nist-reviewer",
                "govern": {"status": "BLOCK", "notes": _fail_note},
                "map": {"status": "BLOCK", "notes": _fail_note},
                "measure": {"status": "BLOCK", "notes": _fail_note},
                "manage": {"status": "BLOCK", "notes": _fail_note},
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
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path = out_path.resolve()
        out_path.write_text(json.dumps(verdict, indent=2))  # NOSONAR — intentional CLI output path
        click.echo(f"nist-review: wrote fail-closed verdict -> {out_path}", err=True)
        return

    if "nist_ai_rmf_review" in verdict:
        verdict["nist_ai_rmf_review"].setdefault("reviewed_at_utc", datetime.now(UTC).isoformat())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path = out_path.resolve()
    out_path.write_text(json.dumps(verdict, indent=2))  # NOSONAR — intentional CLI output path
    click.echo(f"nist-review: wrote verdict -> {out_path}", err=True)


if __name__ == "__main__":
    cli()
