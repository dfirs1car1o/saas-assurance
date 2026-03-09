"""
drift_check.py — Compare two assessment backlogs and produce a structured drift report.

Usage:
    python scripts/drift_check.py \\
        --baseline docs/oscal-salesforce-poc/generated/<org>/<old-date>/backlog.json \\
        --current  docs/oscal-salesforce-poc/generated/<org>/<new-date>/backlog.json \\
        --out      docs/oscal-salesforce-poc/generated/<org>/<new-date>/drift_report.json \\
        --out-md   docs/oscal-salesforce-poc/generated/<org>/<new-date>/drift_report.md

Change types produced:
    new_finding     — control not present in baseline, failing/partial now
    resolved        — was fail/partial, now pass
    regression      — was pass/not_applicable, now fail/partial
    improvement     — was fail, now partial; or was partial, now pass
    severity_change — status unchanged but severity escalated or de-escalated
    unchanged       — status identical (fail/partial or pass; not reported separately)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAILING = {"fail", "partial"}
_PASSING = {"pass", "not_applicable"}

_SEV_ORDER = {"critical": 0, "high": 1, "moderate": 2, "low": 3, "": 99}


def _pass_rate(items: list[dict]) -> float:
    """Fraction of assessed (non-N/A) controls that pass."""
    assessed = [i for i in items if i.get("status") != "not_applicable"]
    if not assessed:
        return 0.0
    passing = sum(1 for i in assessed if i.get("status") == "pass")
    return passing / len(assessed)


def _classify_change(  # NOSONAR
    baseline: dict | None,
    current: dict | None,
) -> tuple[str, str]:
    """Return (change_type, note)."""
    b_status = (baseline or {}).get("status", "")
    c_status = (current or {}).get("status", "")
    b_sev = (baseline or {}).get("severity", "")
    c_sev = (current or {}).get("severity", "")

    if baseline is None:
        # brand-new control in current run
        if c_status in _FAILING:
            return "new_finding", "Control not present in baseline; failing now."
        return "new_finding", "Control not present in baseline; passing now."

    if current is None:
        return "removed", "Control present in baseline but missing from current run."

    if b_status in _FAILING and c_status == "pass":
        return "resolved", f"Status improved: {b_status} → {c_status}."

    if b_status in _PASSING and c_status in _FAILING:
        return "regression", f"Status worsened: {b_status} → {c_status}."

    if b_status == "fail" and c_status == "partial":
        return "improvement", "Partially remediated: fail → partial."

    if b_status == "partial" and c_status == "pass":
        return "improvement", "Fully remediated: partial → pass."

    if b_status == c_status and b_sev != c_sev and b_sev and c_sev:
        direction = "escalated" if _SEV_ORDER.get(c_sev, 99) < _SEV_ORDER.get(b_sev, 99) else "de-escalated"
        return "severity_change", f"Severity {direction}: {b_sev} → {c_sev}."

    return "unchanged", f"Status unchanged: {c_status}."


def _due_date_delta(baseline: dict | None, current: dict | None) -> int | None:
    """Days between baseline and current due_date. Positive = deadline extended."""
    b_date = (baseline or {}).get("due_date")
    c_date = (current or {}).get("due_date")
    if not b_date or not c_date:
        return None
    try:
        b = datetime.strptime(b_date, "%Y-%m-%d")
        c = datetime.strptime(c_date, "%Y-%m-%d")
        return (c - b).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Core diff logic
# ---------------------------------------------------------------------------


def diff_backlogs(baseline_data: dict, current_data: dict) -> dict[str, Any]:
    b_items: dict[str, dict] = {
        i["sbs_control_id"]: i for i in baseline_data.get("mapped_items", []) if "sbs_control_id" in i
    }
    c_items: dict[str, dict] = {
        i["sbs_control_id"]: i for i in current_data.get("mapped_items", []) if "sbs_control_id" in i
    }

    all_ids = sorted(set(b_items) | set(c_items))
    changes: list[dict] = []

    for cid in all_ids:
        b = b_items.get(cid)
        c = c_items.get(cid)
        change_type, note = _classify_change(b, c)

        changes.append(
            {
                "control_id": cid,
                "title": (c or b or {}).get("sbs_title", ""),
                "change_type": change_type,
                "baseline_status": (b or {}).get("status"),
                "current_status": (c or {}).get("status"),
                "baseline_severity": (b or {}).get("severity"),
                "current_severity": (c or {}).get("severity"),
                "due_date_delta_days": _due_date_delta(b, c),
                "owner": (c or b or {}).get("owner"),
                "note": note,
            }
        )

    # Summary buckets
    new_findings = [ch for ch in changes if ch["change_type"] == "new_finding" and ch["current_status"] in _FAILING]
    resolved = [ch for ch in changes if ch["change_type"] == "resolved"]
    regressions = [ch for ch in changes if ch["change_type"] == "regression"]
    improvements = [ch for ch in changes if ch["change_type"] == "improvement"]
    severity_changes = [ch for ch in changes if ch["change_type"] == "severity_change"]
    unchanged_failing = [ch for ch in changes if ch["change_type"] == "unchanged" and ch["current_status"] in _FAILING]

    b_score = _pass_rate(baseline_data.get("mapped_items", []))
    c_score = _pass_rate(current_data.get("mapped_items", []))
    score_delta = c_score - b_score

    if score_delta > 0.01:
        net_direction = "improving"
    elif score_delta < -0.01:
        net_direction = "regressing"
    else:
        net_direction = "stable"

    # Org / platform from current run (fall back to baseline)
    org = current_data.get("org") or baseline_data.get("org") or "unknown"
    platform = current_data.get("platform") or baseline_data.get("platform") or "unknown"

    b_id = baseline_data.get("assessment_id", "unknown")
    c_id = current_data.get("assessment_id", "unknown")

    return {
        "drift_id": f"{org}-drift-{datetime.now(UTC).strftime('%Y-%m-%d')}",
        "baseline_assessment_id": b_id,
        "current_assessment_id": c_id,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "org": org,
        "platform": platform,
        "summary": {
            "baseline_pass_rate": round(b_score, 4),
            "current_pass_rate": round(c_score, 4),
            "score_delta": round(score_delta, 4),
            "net_direction": net_direction,
            "new_findings": len(new_findings),
            "resolved_findings": len(resolved),
            "regressions": len(regressions),
            "improvements": len(improvements),
            "severity_changes": len(severity_changes),
            "unchanged_failing": len(unchanged_failing),
        },
        "changes": changes,
        "new_findings": new_findings,
        "resolved_findings": resolved,
        "regressions": regressions,
        "improvements": improvements,
        "severity_changes": severity_changes,
        "unchanged_failing": unchanged_failing,
    }


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def _render_md(drift: dict) -> str:  # NOSONAR
    s = drift["summary"]
    direction_icon = {"improving": "📈", "regressing": "📉", "stable": "➡️"}.get(s["net_direction"], "")
    delta_str = f"{s['score_delta']:+.1%}"
    b_pct = f"{s['baseline_pass_rate']:.1%}"
    c_pct = f"{s['current_pass_rate']:.1%}"

    lines = [
        f"# Drift Report — {drift['org']}",
        "",
        f"**Baseline:** `{drift['baseline_assessment_id']}`  "
        f"**Current:** `{drift['current_assessment_id']}`  "
        f"**Generated:** {drift['generated_at_utc'][:10]}",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Direction | {direction_icon} **{s['net_direction'].capitalize()}** |",
        f"| Pass rate | {b_pct} → {c_pct} ({delta_str}) |",
        f"| New failing findings | {s['new_findings']} |",
        f"| Resolved | {s['resolved_findings']} |",
        f"| Regressions | {s['regressions']} |",
        f"| Improvements | {s['improvements']} |",
        f"| Severity escalations/de-escalations | {s['severity_changes']} |",
        f"| Still failing (unchanged) | {s['unchanged_failing']} |",
        "",
    ]

    def _table(items: list[dict], heading: str, icon: str) -> list[str]:
        if not items:
            return []
        out = [
            f"## {icon} {heading}",
            "",
            "| Control | Title | Status | Severity | Note |",
            "|---------|-------|--------|----------|------|",
        ]
        for ch in items:
            b_sta = ch.get("baseline_status") or "—"
            c_sta = ch.get("current_status") or "—"
            b_sev = ch.get("baseline_severity") or "—"
            c_sev = ch.get("current_severity") or "—"
            sta = f"{b_sta} → {c_sta}" if b_sta != c_sta else c_sta
            sev = f"{b_sev} → {c_sev}" if b_sev != c_sev else c_sev
            out.append(f"| {ch['control_id']} | {ch['title']} | {sta} | {sev} | {ch['note']} |")
        out.append("")
        return out

    lines += _table(drift["regressions"], "Regressions (Action Required)", "🚨")
    lines += _table(drift["new_findings"], "New Failing Findings", "🆕")
    lines += _table(drift["improvements"], "Improvements", "📈")
    lines += _table(drift["resolved_findings"], "Resolved", "✅")
    lines += _table(drift["severity_changes"], "Severity Changes", "⚠️")

    if drift["unchanged_failing"]:
        lines += [
            "## ⏳ Still Failing (Unchanged)",
            "",
            "| Control | Title | Status | Severity | Owner |",
            "|---------|-------|--------|----------|-------|",
        ]
        for ch in drift["unchanged_failing"]:
            lines.append(
                f"| {ch['control_id']} | {ch['title']} "
                f"| {ch['current_status']} | {ch['current_severity']} | {ch.get('owner') or '—'} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command()
@click.option("--baseline", required=True, type=click.Path(exists=True), help="Path to baseline backlog.json")
@click.option("--current", required=True, type=click.Path(exists=True), help="Path to current backlog.json")
@click.option("--out", default=None, type=click.Path(), help="Output drift_report.json path")
@click.option("--out-md", default=None, type=click.Path(), help="Output drift_report.md path")
def main(baseline: str, current: str, out: str | None, out_md: str | None) -> None:
    """Produce a structured diff between two assessment backlogs."""
    b_path = Path(baseline)
    c_path = Path(current)

    baseline_data = json.loads(b_path.read_text())
    current_data = json.loads(c_path.read_text())

    drift = diff_backlogs(baseline_data, current_data)

    # Default output paths next to the current backlog
    base_dir = c_path.parent
    out_json = Path(out) if out else base_dir / "drift_report.json"
    out_markdown = Path(out_md) if out_md else base_dir / "drift_report.md"

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json = out_json.resolve()  # NOSONAR — intentional CLI output path
    out_json.write_text(json.dumps(drift, indent=2))
    click.echo(f"drift-check: wrote {out_json}", err=True)

    out_markdown.parent.mkdir(parents=True, exist_ok=True)
    out_markdown = out_markdown.resolve()  # NOSONAR — intentional CLI output path
    out_markdown.write_text(_render_md(drift))
    click.echo(f"drift-check: wrote {out_markdown}", err=True)

    s = drift["summary"]
    click.echo(
        json.dumps(
            {
                "status": "ok",
                "drift_id": drift["drift_id"],
                "net_direction": s["net_direction"],
                "score_delta": s["score_delta"],
                "regressions": s["regressions"],
                "resolved": s["resolved_findings"],
                "output_json": str(out_json),
                "output_md": str(out_markdown),
            }
        )
    )


if __name__ == "__main__":
    main()
