"""
sscf-benchmark — SSCF domain-level compliance scorecard.

Takes oscal_gap_map.py backlog output and rolls up findings by SSCF domain,
scoring each domain and producing an overall compliance posture report.

Scoring: pass=1.0, partial=0.5, fail=0.0, not_applicable=excluded.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

STATUS_SCORE = {"pass": 1.0, "partial": 0.5, "fail": 0.0}


def _domain_status(score: float | None, threshold: float) -> str:
    if score is None:
        return "not_assessed"
    if score >= threshold:
        return "green"
    if score >= 0.50:
        return "amber"
    return "red"


def _score_findings(items: list[dict[str, Any]]) -> tuple[int, int, int, int, float]:
    """Return (pass, partial, fail, not_applicable, score)."""
    counts = {"pass": 0, "partial": 0, "fail": 0, "not_applicable": 0}
    for item in items:
        status = item.get("status", "")
        if status in counts:
            counts[status] += 1

    scoreable = counts["pass"] + counts["partial"] + counts["fail"]
    total = scoreable + counts["not_applicable"]
    if total == 0:
        # No findings mapped to this domain at all — not assessed via API
        score = None
    elif scoreable == 0:
        # All findings are not_applicable — exclude from numeric score
        score = None
    else:
        score = (counts["pass"] * 1.0 + counts["partial"] * 0.5) / scoreable

    return counts["pass"], counts["partial"], counts["fail"], counts["not_applicable"], score


# ---------------------------------------------------------------------------
# SSCF index loader
# ---------------------------------------------------------------------------


def _load_sscf_index(path: Path) -> dict[str, dict[str, Any]]:
    """Load sscf_control_index.yaml and return dict keyed by sscf_control_id."""
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required. Install with: pip install PyYAML") from exc

    data = yaml.safe_load(path.read_text())
    index = {}
    for ctrl in data.get("controls", []):
        cid = ctrl.get("sscf_control_id", "")
        if cid:
            index[cid] = ctrl
    return index


def _load_backlog(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in backlog file: {path}")
    return data


# ---------------------------------------------------------------------------
# Core benchmark logic
# ---------------------------------------------------------------------------


def run_benchmark(  # NOSONAR
    backlog: dict[str, Any],
    sscf_index: dict[str, dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    """Compute per-domain SSCF compliance scores from a gap-map backlog."""
    mapped_items: list[dict[str, Any]] = backlog.get("mapped_items", [])

    # Build domain → {sscf_control_id → [items]} mapping
    domain_controls: dict[str, dict[str, list[dict]]] = {}
    for ctrl in sscf_index.values():
        domain = ctrl["domain"]
        cid = ctrl["sscf_control_id"]
        domain_controls.setdefault(domain, {})[cid] = []

    # Distribute backlog items into their SSCF domains
    unmatched_items: list[dict] = []
    for item in mapped_items:
        placed = False
        for sscf_cid in item.get("sscf_control_ids", []):
            ctrl_meta = sscf_index.get(sscf_cid)
            if ctrl_meta:
                domain = ctrl_meta["domain"]
                domain_controls.setdefault(domain, {}).setdefault(sscf_cid, []).append(item)
                placed = True
        if not placed:
            unmatched_items.append(item)

    # Score each domain
    domain_results = []
    for domain, controls in sorted(domain_controls.items()):
        domain_items = [item for items in controls.values() for item in items]
        passes, partials, fails, nas, score = _score_findings(domain_items)

        control_detail = []
        for sscf_cid, items in sorted(controls.items()):
            ctrl_meta = sscf_index.get(sscf_cid, {})
            statuses = [i.get("status", "") for i in items]
            if "fail" in statuses:
                worst = "fail"
            elif "partial" in statuses:
                worst = "partial"
            elif "pass" in statuses:
                worst = "pass"
            else:
                worst = "not_applicable"
            control_detail.append(
                {
                    "sscf_control_id": sscf_cid,
                    "title": ctrl_meta.get("title", ""),
                    "owner_team": ctrl_meta.get("owner_team", ""),
                    "findings": [i.get("sbs_control_id", i.get("legacy_control_id", "")) for i in items],
                    "worst_status": worst if items else "not_applicable",
                }
            )

        domain_results.append(
            {
                "domain": domain,
                "sscf_controls": sorted(controls.keys()),
                "findings_count": len(domain_items),
                "pass": passes,
                "partial": partials,
                "fail": fails,
                "not_applicable": nas,
                "score": round(score, 4) if score is not None else None,
                "status": _domain_status(score, threshold),
                "controls": control_detail,
            }
        )

    # Overall score — only assessed domains (score is not None)
    all_items = [item for items in domain_controls.values() for ctrl_items in items.values() for item in ctrl_items]
    _, _, _, _, overall_score = _score_findings(all_items)

    summary_counts = {"green": 0, "amber": 0, "red": 0, "not_assessed": 0}
    for dr in domain_results:
        summary_counts[dr["status"]] += 1

    return {
        "benchmark_id": f"sscf-benchmark-{backlog.get('assessment_id', 'unknown')}",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_assessment_id": backlog.get("assessment_id", ""),
        "framework": "CSA_SSCF",
        "threshold": threshold,
        "overall_score": round(overall_score, 4) if overall_score is not None else None,
        "overall_status": _domain_status(overall_score, threshold),
        "domains": domain_results,
        "summary": {
            "total_domains": len(domain_results),
            "domains_green": summary_counts["green"],
            "domains_amber": summary_counts["amber"],
            "domains_red": summary_counts["red"],
            "domains_not_assessed": summary_counts["not_assessed"],
            "unmatched_findings": len(unmatched_items),
        },
    }


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def _to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# SSCF Compliance Benchmark",
        "",
        f"- Benchmark ID: `{report['benchmark_id']}`",
        f"- Generated UTC: `{report['generated_at_utc']}`",
        f"- Framework: `{report['framework']}`",
        f"- Threshold: `{int(report['threshold'] * 100)}%`",
        "- Overall Score: `"
        + ("N/A" if report["overall_score"] is None else f"{int(report['overall_score'] * 100)}%")
        + f"` — **{report['overall_status'].upper()}**",
        "",
        "## Domain Scorecard",
        "",
        "| Domain | Score | Status | Pass | Partial | Fail | N/A |",
        "|---|---|---|---|---|---|---|",
    ]
    status_emoji = {"green": "✅", "amber": "⚠️", "red": "❌", "not_assessed": "—"}
    for d in report["domains"]:
        emoji = status_emoji.get(d["status"], "")
        score_str = f"{int(d['score'] * 100)}%" if d["score"] is not None else "N/A"
        lines.append(
            f"| {d['domain']} | {score_str} | {emoji} {d['status'].upper()}"
            f" | {d['pass']} | {d['partial']} | {d['fail']} | {d['not_applicable']} |"
        )

    lines += [
        "",
        "## Summary",
        "",
        f"- Domains GREEN: `{report['summary']['domains_green']}`",
        f"- Domains AMBER: `{report['summary']['domains_amber']}`",
        f"- Domains RED: `{report['summary']['domains_red']}`",
        f"- Unmatched findings: `{report['summary']['unmatched_findings']}`",
        "",
        "## Domain Details",
    ]

    for d in report["domains"]:
        emoji = status_emoji.get(d["status"], "")
        score_str = f"{int(d['score'] * 100)}%" if d["score"] is not None else "N/A"
        lines += [
            "",
            f"### {d['domain']} — {score_str} {emoji}",
            "",
            "| SSCF Control | Title | Findings | Worst Status |",
            "|---|---|---|---|",
        ]
        for ctrl in d["controls"]:
            findings_str = ", ".join(f"`{f}`" for f in ctrl["findings"]) or "—"
            lines.append(f"| `{ctrl['sscf_control_id']}` | {ctrl['title']} | {findings_str} | {ctrl['worst_status']} |")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """sscf-benchmark — SSCF domain-level compliance scorecard."""


@cli.command()
@click.option(
    "--backlog",
    "backlog_path",
    required=True,
    help="Path to oscal_gap_map.py backlog JSON output.",
)
@click.option(
    "--sscf-index",
    "sscf_index_path",
    default="config/sscf_control_index.yaml",
    show_default=True,
    help="Path to SSCF control index YAML.",
)
@click.option("--out", default=None, help="Output path (default: stdout).")
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "markdown"]),
    show_default=True,
    help="Output format.",
)
@click.option(
    "--threshold",
    default=0.80,
    show_default=True,
    type=click.FloatRange(0.0, 1.0),
    help="Score threshold for GREEN status (0.0–1.0).",
)
def benchmark(
    backlog_path: str,
    sscf_index_path: str,
    out: str | None,
    output_format: str,
    threshold: float,
) -> None:
    """Score SSCF compliance from an oscal_gap_map backlog.

    Input: backlog.json produced by scripts/oscal_gap_map.py.
    Output: per-domain scorecard JSON or Markdown.
    """
    repo_root = Path(__file__).resolve().parents[2]

    backlog_resolved = (repo_root / backlog_path).resolve()
    if not backlog_resolved.exists():
        click.echo(f"ERROR: backlog file not found: {backlog_resolved}", err=True)
        sys.exit(1)

    index_resolved = (repo_root / sscf_index_path).resolve()
    if not index_resolved.exists():
        click.echo(f"ERROR: SSCF index not found: {index_resolved}", err=True)
        sys.exit(1)

    backlog = _load_backlog(backlog_resolved)
    sscf_index = _load_sscf_index(index_resolved)

    mapped_count = len(backlog.get("mapped_items", []))
    click.echo(f"  loaded {mapped_count} mapped findings from backlog", err=True)
    click.echo(f"  loaded {len(sscf_index)} SSCF controls from index", err=True)

    report = run_benchmark(backlog, sscf_index, threshold)

    click.echo(
        f"  overall score: {int(report['overall_score'] * 100)}% — {report['overall_status'].upper()}",
        err=True,
    )
    for d in report["domains"]:
        score_str = f"{int(d['score'] * 100)}%" if d["score"] is not None else "N/A"
        click.echo(
            f"    {d['domain']}: {score_str} [{d['status'].upper()}] ({d['pass']}P/{d['partial']}p/{d['fail']}F)",
            err=True,
        )

    if output_format == "markdown":
        output = _to_markdown(report)
    else:
        output = json.dumps(report, indent=2)

    if out:
        out_path = (repo_root / out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output)
        click.echo(f"  wrote report → {out_path}", err=True)
    else:
        click.echo(output)


if __name__ == "__main__":
    cli()
