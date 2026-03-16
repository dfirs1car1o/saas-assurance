"""
report-gen — LLM-driven governance output skill.

Main document (security audience):
  [Gate banner]                 — ⛔/🚩 if NIST verdict is block/flag
  Executive Scorecard           — overall score + severity × status matrix   [HARNESS]
  Domain Posture                — ASCII bar chart of SSCF domain scores      [HARNESS]
  Immediate Actions             — top-10 critical/fail findings              [HARNESS]
  Executive Summary + Analysis  — LLM narrative                              [LLM]
  Not Assessed Controls         — out-of-scope appendix for auditors         [HARNESS]
  NIST AI RMF Review            — governance gate, function table, recs      [HARNESS]

Annex document (security audience only — <org>_annex.md/.docx):
  Full Control Matrix           — sorted findings table (all controls)       [HARNESS]
  Plan of Action & Milestones   — open items: POAM-IDs, owners, due dates   [HARNESS]
  OSCAL Framework Provenance    — catalog → profile → component → CCM chain  [HARNESS]
  CCM v4.1 Regulatory Crosswalk — per-CCM-control regulatory citations       [HARNESS]
  ISO 27001:2022 SoA            — 93-control Statement of Applicability      [HARNESS]

Usage:
    report-gen generate --backlog <path> --audience app-owner|security --out <path>
    report-gen generate --backlog <path> --audience security --sscf-benchmark <path> \\
        --nist-review <path> --out <path>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from dotenv import load_dotenv

_REPO = Path(__file__).resolve().parents[2]
_DOCX_SUFFIX = ".docx"
load_dotenv(_REPO / ".env")

# ---------------------------------------------------------------------------
# Severity / status sort order
# ---------------------------------------------------------------------------

_SEV_ORDER = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
_STA_ORDER = {"fail": 0, "partial": 1, "pass": 2, "not_applicable": 3}
_SEV_ICON = {"critical": "🔴", "high": "🟠", "moderate": "🟡", "low": "🔵"}
_STA_ICON = {"fail": "❌", "partial": "⚠️", "pass": "✅", "not_applicable": "—"}

# ---------------------------------------------------------------------------
# System prompts — LLM writes narrative only; all tables injected by harness
# ---------------------------------------------------------------------------

_SYSTEM_PROMPTS: dict[str, str] = {
    "app-owner": (
        "You are a security consultant writing a plain-English remediation report for an application owner. "
        "No jargon. Write two sections only:\n"
        "1. ## Executive Summary — 2-3 paragraphs: what was assessed, what the score means in business terms, "
        "and the single most important thing they must do first.\n"
        "2. ## What Happens Next — clear, numbered list of owner actions with deadlines.\n"
        "Do NOT write any tables, charts, or control IDs — those are rendered separately. "
        "Do NOT include a NIST AI RMF section."
    ),
    "security": (
        "You are a security governance analyst writing for a Security Team security review board. "
        "Write two sections only:\n"
        "1. ## Executive Summary — 2-3 paragraphs: assessment scope, overall posture, "
        "the key risk drivers behind the score, and governance implications.\n"
        "2. ## Risk Analysis — business and regulatory impact of each RED domain, "
        "critical control failures, and remediation priority rationale.\n"
        "Reference control IDs and SSCF domains by name where relevant. Be precise and technical. "
        "Do NOT write any findings tables, domain score tables, or charts — those are pre-rendered. "
        "Do NOT include a NIST AI RMF section — it is appended as the final section."
    ),
}

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


def _sorted_findings(items: list[dict]) -> list[dict]:
    """Sort findings: fail before partial before pass, critical before high before moderate."""
    return sorted(
        items,
        key=lambda x: (
            _STA_ORDER.get(x.get("status", ""), 9),
            _SEV_ORDER.get(x.get("severity", ""), 9),
        ),
    )


def _build_user_message(
    backlog: dict[str, Any],
    sscf: dict[str, Any] | None,
    nist: dict[str, Any] | None,
    audience: str,
    org: str,
    title: str,
) -> str:
    """Minimal context for the LLM — enough for narrative, no duplication of pre-rendered tables."""
    all_items = backlog.get("mapped_items", [])
    assessed = [i for i in all_items if i.get("status") not in ("not_applicable",)]

    lines = [
        f"Assessment Title: {title}",
        f"Org: {org}",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Assessment ID: {backlog.get('assessment_id', 'unknown')}",
        f"Total controls assessed: {len(assessed)} of {len(all_items)}",
    ]

    if sscf:
        score = sscf.get("overall_score")
        status = sscf.get("overall_status", "unknown")
        if score is not None:
            lines.append(f"Overall Score: {score:.1%} ({status.upper()})")

        # Domain summary for narrative context
        domains = sscf.get("domains", [])
        red = [d["domain"] for d in domains if d.get("status") == "red"]
        amber = [d["domain"] for d in domains if d.get("status") == "amber"]
        if red:
            lines.append(f"RED domains: {', '.join(red)}")
        if amber:
            lines.append(f"AMBER domains: {', '.join(amber)}")

    # Critical and high fails for narrative context
    priority = [i for i in assessed if i.get("status") == "fail" and i.get("severity") in ("critical", "high")]
    if priority:
        lines.append(f"\nCritical/High failures ({len(priority)}):")
        for i in priority:
            lines.append(
                f"  - {i.get('sbs_control_id', '?')} [{i.get('severity', '?').upper()}]: "
                f"{i.get('sbs_title', i.get('remediation', ''))[:80]}"
            )

    if nist:
        review = nist.get("nist_ai_rmf_review", nist)
        overall = review.get("overall", "unknown")
        lines.append(
            f"\nNIST AI RMF context: overall={overall} "
            f"(govern={review.get('govern', {}).get('status', '?')}, "
            f"manage={review.get('manage', {}).get('status', '?')})"
        )

    lines.append(
        "\nAll findings tables, domain charts, and the NIST section are pre-rendered "
        "and will be injected into the document — do not write them."
    )
    lines.append(f"\nWrite the {audience} narrative sections described in your instructions.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Python-rendered report sections
# ---------------------------------------------------------------------------


_OSCAL_CHAIN: dict[str, list[dict[str, str]]] = {
    "salesforce": [
        {
            "layer": "Catalog",
            "document": "CSA SSCF v1.0",
            "version": "1.0",
            "scope": "36 controls · 6 domains (CON, DSP, IAM, IPY, LOG, SEF)",
            "file": "`config/sscf/sscf_v1_catalog.json`",
        },
        {
            "layer": "Profile",
            "document": "Security Baseline for Salesforce (SBS) v1.0",
            "version": "1.0",
            "scope": "35 controls (SSCF subset)",
            "file": "`config/salesforce/sbs_v1_profile.json`",
        },
        {
            "layer": "Component Definition",
            "document": "Salesforce Component",
            "version": "1.0",
            "scope": "18 automated requirements (SOQL / Tooling / Metadata / Manual)",
            "file": "`config/component-definitions/salesforce_component.json`",
        },
        {
            "layer": "Control Framework",
            "document": "CSA CCM v4.1",
            "version": "4.1",
            "scope": "207 controls · cross-reference only (IDs embedded as props in catalog)",
            "file": "`config/ccm/ccm_v4.1_oscal_ref.yaml`",
        },
        {
            "layer": "Regulatory Standard",
            "document": "ISO/IEC 27001:2022 Annex A",
            "version": "2022",
            "scope": "29 of 93 Annex A controls directly mapped via SSCF layer · SoA auto-generated",
            "file": "`config/iso27001/sscf_to_iso27001_mapping.yaml`",
        },
        {
            "layer": "Regulatory Crosswalk",
            "document": "SOX · HIPAA · SOC 2 TSC · ISO 27001 (via CCM) · NIST 800-53 · PCI DSS · GDPR",
            "version": "—",
            "scope": "Via CCM v4.1 domain mappings",
            "file": "Embedded in CCM reference",
        },
        {
            "layer": "POA&M",
            "document": "Plan of Action & Milestones",
            "version": "—",
            "scope": "Generated from fail/partial findings — remediation backlog with due dates and owners",
            "file": "`docs/oscal-salesforce-poc/generated/<org>/<date>/backlog.json`",
        },
    ],
    "workday": [
        {
            "layer": "Catalog",
            "document": "CSA SSCF v1.0",
            "version": "1.0",
            "scope": "36 controls · 6 domains (CON, DSP, IAM, IPY, LOG, SEF)",
            "file": "`config/sscf/sscf_v1_catalog.json`",
        },
        {
            "layer": "Profile",
            "document": "Workday Security Control Catalog (WSCC) v1.0",
            "version": "1.0",
            "scope": "30 controls (SSCF subset)",
            "file": "`config/workday/wscc_v1_profile.json`",
        },
        {
            "layer": "Component Definition",
            "document": "Workday Component",
            "version": "1.0",
            "scope": "16 automated requirements (SOAP / RaaS / REST / Manual)",
            "file": "`config/component-definitions/workday_component.json`",
        },
        {
            "layer": "Control Framework",
            "document": "CSA CCM v4.1",
            "version": "4.1",
            "scope": "207 controls · cross-reference only (IDs embedded as props in catalog)",
            "file": "`config/ccm/ccm_v4.1_oscal_ref.yaml`",
        },
        {
            "layer": "Regulatory Standard",
            "document": "ISO/IEC 27001:2022 Annex A",
            "version": "2022",
            "scope": "29 of 93 Annex A controls directly mapped via SSCF layer · SoA auto-generated",
            "file": "`config/iso27001/sscf_to_iso27001_mapping.yaml`",
        },
        {
            "layer": "Regulatory Crosswalk",
            "document": "SOX · HIPAA · SOC 2 TSC · ISO 27001 (via CCM) · NIST 800-53 · PCI DSS · GDPR",
            "version": "—",
            "scope": "Via CCM v4.1 domain mappings",
            "file": "Embedded in CCM reference",
        },
        {
            "layer": "POA&M",
            "document": "Plan of Action & Milestones",
            "version": "—",
            "scope": "Generated from fail/partial findings — remediation backlog with due dates and owners",
            "file": "`docs/oscal-salesforce-poc/generated/<org>/<date>/backlog.json`",
        },
    ],
}


def _detect_platform(backlog: dict) -> str:
    """Infer platform from control ID prefix in mapped_items."""
    for item in backlog.get("mapped_items", []):
        cid = item.get("sbs_control_id", "")
        if cid.startswith("WSCC-") or cid.startswith("WD-"):
            return "workday"
    return "salesforce"


def _render_oscal_provenance(backlog: dict, platform: str | None = None) -> str:
    """Render OSCAL framework chain table (Catalog → Profile → Component Def → CCM → Regulatory)."""
    resolved = platform or _detect_platform(backlog)
    chain = _OSCAL_CHAIN.get(resolved, _OSCAL_CHAIN["salesforce"])
    framework = backlog.get("framework", "CSA_SSCF").replace("_", " ")

    lines = [
        "## OSCAL Framework Provenance",
        "",
        f"This assessment is governed by the **{framework}** framework. "
        "The table below shows the full OSCAL control chain from catalog to regulatory crosswalk.",
        "",
        "| Layer | Document | Version | Scope | Config File |",
        "|-------|----------|---------|-------|-------------|",
    ]
    for row in chain:
        lines.append(f"| {row['layer']} | {row['document']} | {row['version']} | {row['scope']} | {row['file']} |")
    lines.append("")
    return "\n".join(lines)


def _render_executive_scorecard(backlog: dict, sscf: dict | None, org: str, title: str) -> str:
    """Overall score badge + severity × status matrix."""
    items = backlog.get("mapped_items", [])
    assessed = [i for i in items if i.get("status") != "not_applicable"]

    # Severity × status counts
    sevs = ["critical", "high", "moderate", "low"]
    stas = ["fail", "partial", "pass"]
    matrix: dict[str, dict[str, int]] = {s: dict.fromkeys(stas, 0) for s in sevs}
    for item in assessed:
        sev = item.get("severity", "")
        sta = item.get("status", "")
        if sev in matrix and sta in matrix[sev]:
            matrix[sev][sta] += 1

    overall_score = sscf.get("overall_score") if sscf else None
    overall_status = (sscf.get("overall_status") or "unknown").upper() if sscf else "UNKNOWN"
    status_icon = {"RED": "🔴", "AMBER": "🟡", "GREEN": "🟢"}.get(overall_status, "⚪")
    score_str = f"{overall_score:.1%}" if overall_score is not None else "N/A"

    na_count = len(items) - len(assessed)
    lines = [
        f"# {title}",
        "",
        f"**Org:** {org} &nbsp;|&nbsp; "
        f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d')} &nbsp;|&nbsp; "
        f"**Assessment ID:** {backlog.get('assessment_id', 'unknown')}",
        "",
        "---",
        "",
        "## Executive Scorecard",
        "",
        f"### {status_icon} Overall Posture: {score_str} — {overall_status}",
        "",
        "| Severity | ❌ Fail | ⚠️ Partial | ✅ Pass |",
        "|----------|---------|-----------|--------|",
    ]
    for sev in sevs:
        row = matrix[sev]
        if any(row.values()):
            icon = _SEV_ICON.get(sev, "")
            lines.append(
                f"| {icon} **{sev.capitalize()}** "
                f"| {row['fail'] or '—'} "
                f"| {row['partial'] or '—'} "
                f"| {row['pass'] or '—'} |"
            )
    lines += [
        "",
        f"*{len(assessed)} controls assessed · {na_count} not assessable via API · {len(items)} total in catalog*",
        "",
    ]
    return "\n".join(lines)


def _render_domain_chart(sscf: dict) -> str:
    """ASCII bar chart of SSCF domain scores."""
    domains = sscf.get("domains", [])
    if not domains:
        return ""

    bar_width = 20
    status_icon = {"green": "✅", "amber": "⚠️", "red": "❌", "not_assessed": "—"}

    lines = [
        "## Domain Posture",
        "",
        "```",
    ]

    max_name = max(len(d["domain"].replace("_", " ").title()) for d in domains)

    for d in domains:
        name = d["domain"].replace("_", " ").title()
        score = d.get("score")
        status = d.get("status", "not_assessed")
        icon = status_icon.get(status, "—")

        if score is not None:
            filled = round(score * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            pct = f"{score:.0%}"
            status_label = status.upper()
        else:
            bar = "─" * bar_width
            pct = "N/A"
            status_label = "NOT ASSESSED"

        lines.append(f"  {name:<{max_name}}  {bar}  {pct:>4}  {icon} {status_label}")

    lines += ["```", ""]
    return "\n".join(lines)


def _render_iso27001_soa(backlog: dict, catalog_path: Path | None = None) -> str:  # NOSONAR
    """Render ISO/IEC 27001:2022 Annex A Statement of Applicability (SoA).

    Shows all 93 Annex A controls with applicability decisions, assessment status,
    and implementation verdict — the core document an ISO 27001 auditor needs.

    Controls touched by assessment findings derive their status from those findings.
    Remaining controls default to not_assessed_by_api using the catalog's defaults.
    """
    import yaml  # local import

    # ── Build lookup: ISO control ID → list of backlog items referencing it ──
    iso_to_items: dict[str, list[dict]] = {}
    for item in backlog.get("mapped_items", []):
        for ctrl in item.get("iso27001_controls", []):
            iso_id = ctrl.get("id", "")
            if iso_id:
                iso_to_items.setdefault(iso_id, []).append(
                    {
                        "status": item.get("status", ""),
                        "severity": item.get("severity", ""),
                        "sscf_id": (item.get("sscf_control_ids") or [item.get("sbs_control_id", "")])[0],
                        "sbs_title": item.get("sbs_title", ""),
                        "evidence_ref": item.get("evidence_ref", ""),
                        "owner": item.get("owner", ""),
                        "applicability": ctrl.get("applicability", "applicable"),
                    }
                )

    if not iso_to_items and not catalog_path:
        return ""  # no ISO data and no catalog — skip section silently

    # ── Derive per-ISO-control verdict from mapped findings ───────────────────
    _STA_PRIORITY = {"fail": 0, "partial": 1, "pass": 2}
    _IMPL_LABEL = {"fail": "Planned — Remediation Required", "partial": "Partially Implemented", "pass": "Implemented"}
    _STA_ICON2 = {"fail": "❌", "partial": "⚠️", "pass": "✅", "not_assessed": "—"}

    def _worst_status(items: list[dict]) -> str:
        statuses = [i["status"] for i in items if i["status"] in _STA_PRIORITY]
        if not statuses:
            return "not_assessed"
        return min(statuses, key=lambda s: _STA_PRIORITY[s])

    # ── Load catalog for complete 93-control listing ──────────────────────────
    catalog_controls: list[dict] = []
    if catalog_path and catalog_path.exists():
        try:
            raw = yaml.safe_load(catalog_path.read_text())
            catalog_controls = raw.get("controls", [])
        except Exception:
            pass

    # If no catalog, build synthetic entries from touched controls only
    if not catalog_controls:
        seen_ids: set[str] = set()
        for iso_id, items in iso_to_items.items():
            if iso_id not in seen_ids:
                seen_ids.add(iso_id)
                ctrl = items[0]  # take first for theme/applicability
                catalog_controls.append(
                    {
                        "id": iso_id,
                        "title": "—",
                        "theme": "—",
                        "default_applicability": ctrl.get("applicability", "applicable"),
                        "default_reason": "",
                    }
                )

    # ── Build SoA rows ────────────────────────────────────────────────────────
    rows_assessed: list[dict] = []
    rows_not_assessed: list[dict] = []

    for ctrl in catalog_controls:
        iso_id = ctrl.get("id", "")
        title = ctrl.get("title", "—")
        theme = ctrl.get("theme", "—")
        default_appl = ctrl.get("default_applicability", "not_assessed_by_api")
        default_reason = ctrl.get("default_reason", "")

        if iso_id in iso_to_items:
            items = iso_to_items[iso_id]
            status = _worst_status(items)
            appl = items[0].get("applicability", "applicable")
            sscf_refs = ", ".join(sorted({i["sscf_id"] for i in items if i["sscf_id"]}))
            owner = items[0].get("owner", "Security Team")
            evidence = items[0].get("evidence_ref", "—") or "—"
            impl_label = _IMPL_LABEL.get(status, "Not Assessed")
            status_icon = _STA_ICON2.get(status, "—")
            rows_assessed.append(
                {
                    "id": iso_id,
                    "title": title,
                    "theme": theme,
                    "applicability": appl,
                    "status": status,
                    "status_icon": status_icon,
                    "implementation": impl_label,
                    "owner": owner,
                    "evidence": evidence[:60] + "…" if len(evidence) > 60 else evidence,
                    "sscf": sscf_refs,
                }
            )
        else:
            rows_not_assessed.append(
                {
                    "id": iso_id,
                    "title": title,
                    "theme": theme,
                    "applicability": default_appl,
                    "reason": default_reason,
                }
            )

    # Sort assessed rows: fail first, then by clause number
    def _clause_key(row: dict) -> tuple:
        parts = row["id"].split(".")
        return tuple(int(p) for p in parts if p.isdigit())

    rows_assessed.sort(key=lambda r: (_STA_PRIORITY.get(r["status"], 9), _clause_key(r)))
    rows_not_assessed.sort(key=_clause_key)

    # ── Counts for summary ────────────────────────────────────────────────────
    fail_count = sum(1 for r in rows_assessed if r["status"] == "fail")
    partial_count = sum(1 for r in rows_assessed if r["status"] == "partial")
    pass_count = sum(1 for r in rows_assessed if r["status"] == "pass")
    not_assessed_count = len(rows_not_assessed)

    # ── Assessment scope statement ────────────────────────────────────────────
    scope_note = (
        "> **Assessment Scope:** This SoA covers ISO/IEC 27001:2022 Annex A controls "
        "assessable via SaaS platform APIs (Salesforce and/or Workday). "
        "Organizational process controls (5.x), HR/people controls (6.x), physical controls (7.x), "
        "and technological controls outside the API collection scope (8.x) are declared "
        "`not_assessed_by_api` — they require manual review, vendor attestation, or process interviews. "
        "Do not interpret `not_assessed_by_api` as `not applicable` without a formal risk acceptance decision."
    )

    lines = [
        "## ISO/IEC 27001:2022 Statement of Applicability (SoA)",
        "",
        scope_note,
        "",
        f"**Assessed (API-collected):** {len(rows_assessed)} controls "
        f"({pass_count} ✅ pass · {partial_count} ⚠️ partial · {fail_count} ❌ fail)  ",
        f"**Not assessed by API:** {not_assessed_count} controls — manual review required  ",
        f"**Total Annex A controls:** {len(catalog_controls) or len(rows_assessed) + not_assessed_count}",
        "",
    ]

    if rows_assessed:
        lines += [
            "### Assessed Controls",
            "",
            "| Annex A | Title | Theme | Applicability | Status | Implementation | SSCF Ref | Owner | Evidence |",
            "|---------|-------|-------|---------------|--------|----------------|----------|-------|----------|",
        ]
        for r in rows_assessed:
            appl_label = "Applicable" if r["applicability"] == "applicable" else "Applicable — Manual"
            lines.append(
                f"| **{r['id']}** | {r['title']} | {r['theme']} | {appl_label} "
                f"| {r['status_icon']} {r['status'].capitalize()} "
                f"| {r['implementation']} | {r['sscf']} | {r['owner']} | {r['evidence']} |"
            )
        lines.append("")

    if rows_not_assessed:
        lines += [
            "### Not Assessed via API",
            "",
            "> Controls below are within scope but require manual review, vendor attestation, "
            "or process interviews. Evidence must be collected separately before an ISO 27001 "
            "audit can claim these controls as implemented.",
            "",
            "| Annex A | Title | Theme | Applicability | Reason |",
            "|---------|-------|-------|---------------|--------|",
        ]
        for r in rows_not_assessed:
            reason = r["reason"][:90] + "…" if len(r["reason"]) > 90 else r["reason"]
            lines.append(f"| **{r['id']}** | {r['title']} | {r['theme']} | Not Assessed by API | {reason} |")
        lines.append("")

    lines.append(
        "*Direct mapping via SSCF v1.0 control layer — "
        "`config/iso27001/sscf_to_iso27001_mapping.yaml`. "
        "ISO 27001:2022 Annex A published 2022-10-25 (ISO/IEC 27001:2022).*"
    )
    lines.append("")
    return "\n".join(lines)


def _render_ccm_crosswalk(backlog: dict) -> str:  # NOSONAR
    """Render CCM v4.1 regulatory crosswalk for controls with fail/partial findings.

    Loads config/sscf/sscf_to_ccm_mapping.yaml, intersects with SSCF control IDs
    referenced by failing findings, and renders a table per CCM control showing
    which regulatory frameworks apply (SOX, HIPAA, SOC2, ISO 27001, PCI DSS, GDPR).
    ISO 27001 references here are via the CCM bridge — see the ISO 27001:2022 SoA
    section above for direct Annex A control mappings.
    """
    import yaml  # local import — not all environments have pyyaml at module load

    mapping_path = _REPO / "config" / "sscf" / "sscf_to_ccm_mapping.yaml"
    if not mapping_path.exists():
        return ""

    try:
        raw = yaml.safe_load(mapping_path.read_text())
    except Exception:
        return ""

    # Build lookup: sscf_control_id → list of CCM control dicts
    sscf_to_ccm: dict[str, list[dict]] = {}
    for entry in raw.get("mappings", []):
        sscf_id = entry.get("sscf_control_id", "")
        for ccm in entry.get("ccm_controls", []):
            sscf_to_ccm.setdefault(sscf_id, []).append(ccm)

    # Collect SSCF control IDs referenced by fail/partial findings
    failing_sscf: set[str] = set()
    for item in backlog.get("mapped_items", []):
        if item.get("status") not in ("fail", "partial"):
            continue
        for mapping in item.get("sscf_mappings", []):
            sid = mapping.get("sscf_control_id", "")
            if sid:
                failing_sscf.add(sid)

    if not failing_sscf:
        return ""

    # Collect unique CCM controls (deduplicated by CCM ID) touched by failing findings
    seen_ccm: dict[str, dict] = {}
    ccm_to_sscf: dict[str, list[str]] = {}
    for sscf_id in sorted(failing_sscf):
        for ccm in sscf_to_ccm.get(sscf_id, []):
            cid = ccm["id"]
            seen_ccm[cid] = ccm
            ccm_to_sscf.setdefault(cid, []).append(sscf_id)

    if not seen_ccm:
        return ""

    def _reg_cell(highlights: list[str], prefix: str, strip: str) -> str:
        """Extract citations for a given framework prefix."""
        hits = [h[len(strip) :] for h in highlights if h.startswith(prefix)]
        return " · ".join(hits) if hits else "—"

    rows = []
    for cid in sorted(seen_ccm, key=lambda x: (seen_ccm[x]["domain"], x)):
        ccm = seen_ccm[cid]
        hl = ccm.get("regulatory_highlights", [])
        sscf_refs = ", ".join(sorted(set(ccm_to_sscf.get(cid, []))))
        rows.append(
            {
                "id": cid,
                "domain": ccm.get("domain", ""),
                "title": ccm.get("title", ""),
                "sscf": sscf_refs,
                "sox": _reg_cell(hl, "SOX_", "SOX_"),
                "hipaa": _reg_cell(hl, "HIPAA_", "HIPAA_"),
                "soc2": _reg_cell(hl, "SOC2_", "SOC2_"),
                "iso": _reg_cell(hl, "ISO27001_", "ISO27001_"),
                "pci": _reg_cell(hl, "PCI_DSS_", "PCI_DSS_"),
                "gdpr": _reg_cell(hl, "GDPR_", "GDPR_"),
            }
        )

    lines = [
        "## CCM v4.1 Regulatory Crosswalk",
        "",
        "Controls below are CCM v4.1 entries mapped from failing or partial findings in this assessment. "
        "Each column shows the regulatory reference that applies via the CCM crosswalk "
        "(SOX ITGC, HIPAA §164, SOC 2 TSC, ISO 27001:2022, PCI DSS v4, GDPR).",
        "",
        "| CCM ID | Domain | Title | SSCF Controls | SOX | HIPAA | SOC2 | ISO 27001 (via CCM) | PCI DSS | GDPR |",
        "|--------|--------|-------|---------------|-----|-------|------|---------------------|---------|------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['domain']} | {r['title']} | {r['sscf']} "
            f"| {r['sox']} | {r['hipaa']} | {r['soc2']} | {r['iso']} | {r['pci']} | {r['gdpr']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_aicm_coverage(aicm: dict[str, Any]) -> str:
    """Render AICM v1.0.3 AI Governance Coverage section for the security annex.

    Reads aicm_coverage.json produced by gen_aicm_crosswalk.py and renders
    a domain-level summary table plus gap domain list — showing which AI
    Controls Matrix domains have SSCF evidence and which require supplemental
    questionnaire or third-party audit.

    Only included in the annex (security audience).
    """
    summary = aicm.get("summary", {})
    domain_coverage = aicm.get("domain_coverage", {})
    gap_note = aicm.get("gap_note", "")
    aicm_version = aicm.get("aicm_version", "v1.0.3")

    _VERDICT_ICON = {
        "covered": "✅",
        "partial": "⚠️",
        "not_assessed": "—",
        "not_covered": "—",
    }
    _POSTURE_ICON = {"pass": "🟢", "partial": "🟡", "fail": "🔴", "not_assessed": "—"}

    lines = [
        f"## CSA AICM {aicm_version} AI Governance Coverage",
        "",
        "Maps SSCF assessment evidence to the CSA AI Controls Matrix (AICM) — "
        "an AI-specific governance framework covering 243 controls across 18 domains "
        "including Model Security (MDS) not present in CCM v4.1.",
        "",
        f"**Total AICM domains:** {summary.get('total_aicm_domains', 18)}  ",
        f"**Total AICM controls:** {summary.get('total_aicm_controls', 243)}  ",
        f"**Covered:** {summary.get('covered_domains', 0)} domains  "
        f"**Partial:** {summary.get('partial_domains', 0)} domains  "
        f"**Gap:** {summary.get('gap_domains', 0)} domains",
        "",
        "| Domain | SSCF Coverage | Posture | Controls | Failing Controls |",
        "|---|---|---|---|---|",
    ]

    for abbrev, data in sorted(domain_coverage.items()):
        cov = data.get("coverage_verdict", "not_assessed")
        pos = data.get("posture_verdict", "not_assessed")
        total = data.get("total_aicm_controls", 0)
        failing = data.get("failing_controls", [])
        cov_icon = _VERDICT_ICON.get(cov, "—")
        pos_icon = _POSTURE_ICON.get(pos, "—")
        if failing:
            fail_str = ", ".join(failing[:3]) + ("…" if len(failing) > 3 else "")
        else:
            fail_str = "—"
        lines.append(f"| **{abbrev}** | {cov_icon} {cov} | {pos_icon} {pos} | {total} | {fail_str} |")

    if gap_note:
        lines += ["", f"> **Gap Note:** {gap_note}"]

    gap_domain_details: list[dict] = aicm.get("gap_domain_details", [])
    if gap_domain_details:
        lines += [
            "",
            "### Gap Domain Details",
            "",
            "The following AICM domains have no SSCF evidence. Each requires supplemental "
            "review outside the API-based assessment scope.",
            "",
        ]
        for d in gap_domain_details:
            abbrev = d.get("abbrev", "")
            full_name = d.get("full_name", abbrev)
            control_range = d.get("control_range", "")
            reason = d.get("reason", "")
            guidance = d.get("supplemental_guidance", "")
            range_str = f" ({control_range})" if control_range else ""
            lines += [
                f"#### {abbrev} — {full_name}{range_str}",
                "",
            ]
            if reason:
                lines += [f"**Scope gap:** {reason}", ""]
            if guidance:
                lines += [f"**Supplemental guidance:** {guidance}", ""]

    return "\n".join(lines)


def _render_drift_section(drift: dict[str, Any]) -> str:
    """Changes Since Last Assessment — rendered from drift_report.json."""
    summary = drift.get("summary", {})
    direction = summary.get("net_direction", "stable").lower()
    delta = summary.get("pass_rate_delta", 0.0)
    baseline_date = drift.get("baseline_date", "prior run")
    current_date = drift.get("current_date", "this run")

    _DIR_ICON = {"improving": "📈", "regressing": "📉", "stable": "➡️"}
    dir_icon = _DIR_ICON.get(direction, "➡️")

    delta_str = f"+{delta:.1%}" if delta >= 0 else f"{delta:.1%}"

    lines = [
        "## Changes Since Last Assessment",
        "",
        f"**Comparison:** {baseline_date} → {current_date}  ",
        f"**Net direction:** {dir_icon} {direction.upper()}  ",
        f"**Pass rate delta:** {delta_str}",
        "",
        "| Category | Count |",
        "|---|---|",
        f"| 🔴 Regressions (new failures) | {summary.get('regression', 0)} |",
        f"| 🟡 Improvements (partial fix) | {summary.get('improvement', 0)} |",
        f"| 🟢 Resolved (fully remediated) | {summary.get('resolved', 0)} |",
        f"| 🆕 New findings | {summary.get('new_finding', 0)} |",
        f"| ⚠️ Severity escalations | {summary.get('severity_change', 0)} |",
        "",
    ]

    changes = drift.get("changes", [])
    regressions = [c for c in changes if c.get("change_type") == "regression"]
    resolved = [c for c in changes if c.get("change_type") == "resolved"]

    if regressions:
        lines += [
            "### 🔴 Regressions — Immediate Attention Required",
            "",
            "| Control | Severity | Change | Note |",
            "|---|---|---|---|",
        ]
        for r in regressions:
            cid = r.get("control_id", "?")
            sev = r.get("current_severity", r.get("baseline_severity", "?"))
            change = f"{r.get('baseline_status', '?')} → {r.get('current_status', '?')}"
            note = r.get("note", "—")
            lines.append(f"| `{cid}` | {sev} | {change} | {note} |")
        lines.append("")

    if resolved:
        lines += [
            "### 🟢 Resolved — Remediation Confirmed",
            "",
            "| Control | Prior Status | Note |",
            "|---|---|---|",
        ]
        for r in resolved:
            cid = r.get("control_id", "?")
            prior = r.get("baseline_status", "?")
            note = r.get("note", "—")
            lines.append(f"| `{cid}` | {prior} | {note} |")
        lines.append("")

    return "\n".join(lines)


def _render_priority_findings(backlog: dict, _n: int = 10) -> str:
    """All assessed controls sorted by severity (critical → high → moderate → low), then by status."""
    items = backlog.get("mapped_items", [])
    assessed = [i for i in items if i.get("status") != "not_applicable"]

    # Sort by severity first, then status within each severity band
    sorted_items = sorted(
        assessed,
        key=lambda x: (
            _SEV_ORDER.get(x.get("severity", ""), 9),
            _STA_ORDER.get(x.get("status", ""), 9),
        ),
    )

    if not sorted_items:
        return ""

    lines = [
        f"## Assessed Controls — {len(sorted_items)} Controls by Severity",
        "",
        "| # | Control | Description | Severity | Status | Required Action | Due Date |",
        "|---|---------|-------------|----------|--------|----------------|----------|",
    ]
    for idx, item in enumerate(sorted_items, 1):
        cid = item.get("sbs_control_id", "?")
        desc = item.get("sbs_title", "—")
        sev = item.get("severity", "?")
        sta = item.get("status", "?")
        sev_icon = _SEV_ICON.get(sev, "")
        sta_icon = _STA_ICON.get(sta, "")
        due = item.get("due_date") or "—"
        sev_str = f"{sev_icon} {sev.capitalize()}"
        sta_str = f"{sta_icon} {sta.capitalize()}"

        if sta == "pass":
            action = "No action required"
            due = "—"
        elif item.get("needs_expert_review"):
            raw = item.get("remediation") or "Manual review required"
            raw = raw[:55] + "…" if len(raw) > 55 else raw
            action = f"⚠️ Expert review pending — {raw}"
        else:
            raw = item.get("remediation") or item.get("sbs_title") or "See control catalog"
            action = raw[:70] + "…" if len(raw) > 70 else raw

        lines.append(f"| {idx} | `{cid}` | {desc} | {sev_str} | {sta_str} | {action} | {due} |")

    lines.append("")
    return "\n".join(lines)


def _render_poam(backlog: dict) -> str:
    """Formal Plan of Action & Milestones table — open (fail) and in-progress (partial) findings only."""
    items = backlog.get("mapped_items", [])
    open_items = _sorted_findings([i for i in items if i.get("status") in ("fail", "partial")])

    if not open_items:
        return "## Plan of Action & Milestones (POA&M)\n\n*No open items — all assessed controls passed.*\n"

    assessment_id = backlog.get("assessment_id", "unknown")
    generated = backlog.get("generated_at_utc", datetime.now(UTC).isoformat())[:10]

    lines = [
        "## Plan of Action & Milestones (POA&M)",
        "",
        f"**Assessment ID:** `{assessment_id}` &nbsp;|&nbsp; "
        f"**Generated:** {generated} &nbsp;|&nbsp; "
        f"**Open items:** {len(open_items)}",
        "",
        "| POA&M ID | Control | Description | Risk | Owner | Due Date | Milestones | Status |",
        "|----------|---------|-------------|------|-------|----------|------------|--------|",
    ]
    for idx, item in enumerate(open_items, 1):
        poam_id = f"POAM-{idx:03d}"
        cid = item.get("sbs_control_id", "?")
        desc = item.get("sbs_title", "—")
        sev = item.get("severity", "?")
        sta = item.get("status", "?")
        owner = item.get("owner", "—")
        due = item.get("due_date") or "—"
        milestone = item.get("remediation") or "Remediate per control guidance"
        milestone = milestone[:80] + "…" if len(milestone) > 80 else milestone
        sev_icon = _SEV_ICON.get(sev, "")
        open_status = "Open" if sta == "fail" else "In Progress"
        lines.append(
            f"| `{poam_id}` | `{cid}` | {desc} | {sev_icon} {sev.capitalize()} "
            f"| {owner} | {due} | {milestone} | {open_status} |"
        )

    lines.append("")
    return "\n".join(lines)


def _render_not_assessed(backlog: dict) -> str:
    """Appendix: controls not assessable via API — auditor disclosure."""
    items = backlog.get("mapped_items", [])
    na_items = [i for i in items if i.get("status") == "not_applicable"]
    unmapped = backlog.get("unmapped_items", [])

    if not na_items and not unmapped:
        return ""

    lines = [
        "## Appendix: Controls Not Assessed via API",
        "",
        "The following controls could not be automatically assessed through platform APIs. "
        "Manual review, vendor attestation, or process interviews are required.",
        "",
        "| Control | Description | Reason |",
        "|---------|-------------|--------|",
    ]
    for item in na_items:
        cid = item.get("sbs_control_id", "?")
        desc = item.get("sbs_title", "—")
        notes = item.get("mapping_notes", "Outside automated collector scope")
        lines.append(f"| `{cid}` | {desc} | {notes} |")
    for item in unmapped:
        cid = item.get("legacy_control_id", "?")
        lines.append(f"| `{cid}` | — | No catalog mapping — manual review required |")

    lines.append("")
    return "\n".join(lines)


def _render_full_matrix(backlog: dict) -> str:
    """Complete sorted findings table — critical/fail first."""
    items = backlog.get("mapped_items", [])
    sorted_items = _sorted_findings(items)

    lines = [
        "## Full Control Matrix",
        "",
        "| Control | Description | Severity | Status | Confidence | Due Date | Owner |",
        "|---------|-------------|----------|--------|------------|----------|-------|",
    ]
    for item in sorted_items:
        cid = item.get("sbs_control_id", "?")
        desc = item.get("sbs_title", "—")
        sev = item.get("severity", "?")
        sta = item.get("status", "?")
        sev_icon = _SEV_ICON.get(sev, "")
        sta_icon = _STA_ICON.get(sta, "")
        conf = item.get("mapping_confidence", "—")
        due = item.get("due_date") or "—"
        owner = item.get("owner", "—")
        sev_str = f"{sev_icon} {sev.capitalize()}"
        sta_str = f"{sta_icon} {sta.capitalize()}"
        lines.append(f"| `{cid}` | {desc} | {sev_str} | {sta_str} | {conf} | {due} | {owner} |")

    lines.append("")
    return "\n".join(lines)


def _render_evidence_methodology(backlog: dict) -> str:  # NOSONAR
    """Evidence methodology table — shows the API query or data source used to assess each control."""
    items = backlog.get("mapped_items", [])
    if not items:
        return ""

    org = backlog.get("org", "unknown-org")
    platform = backlog.get("platform", "salesforce")
    generated = backlog.get("generated_at_utc", "")[:10]

    _platform_labels = {
        "salesforce": "Salesforce (REST · Tooling · Metadata API)",
        "workday": "Workday (RaaS · REST · manual questionnaire)",
    }
    platform_label = _platform_labels.get(platform, platform)

    lines = [
        "# Assessment Evidence Methodology",
        "",
        f"**Org:** {org} &nbsp;|&nbsp; **Platform:** {platform_label} &nbsp;|&nbsp; **Generated:** {generated}",
        "",
        "> This document describes **how each control was assessed** — the specific API, query, or "
        "endpoint used to collect evidence. Use this to verify assessment coverage, audit the "
        "collection methodology, or reproduce results manually.",
        "",
        "---",
        "",
        "## Control Assessment Methods",
        "",
        "| Control | Description | Status | Evidence Source | Collection Method / Query |",
        "|---------|-------------|--------|-----------------|---------------------------|",
    ]

    for item in _sorted_findings(items):
        cid = item.get("sbs_control_id", "?")
        desc = item.get("sbs_title", "—")
        sta = item.get("status", "?")
        sta_icon = _STA_ICON.get(sta, "")
        sta_str = f"{sta_icon} {sta.capitalize()}"

        evidence_ref = item.get("evidence_ref") or "—"
        # Truncate long evidence refs for readability
        if len(evidence_ref) > 80:
            evidence_ref = evidence_ref[:77] + "…"

        method = item.get("mapping_notes") or item.get("data_source") or "—"
        if len(method) > 100:
            method = method[:97] + "…"

        lines.append(f"| `{cid}` | {desc} | {sta_str} | {evidence_ref} | {method} |")

    lines.append("")

    # Not assessed controls — why they couldn't be collected
    na_items = [i for i in items if i.get("status") == "not_applicable"]
    if na_items:
        lines += [
            "## Controls Not Assessable via API",
            "",
            "The following controls require manual review, vendor attestation, or configuration "
            "data not exposed through platform APIs.",
            "",
            "| Control | Description | Reason |",
            "|---------|-------------|--------|",
        ]
        for item in na_items:
            cid = item.get("sbs_control_id", "?")
            desc = item.get("sbs_title", "—")
            reason = item.get("mapping_notes") or "Outside automated collector scope"
            if len(reason) > 100:
                reason = reason[:97] + "…"
            lines.append(f"| `{cid}` | {desc} | {reason} |")
        lines.append("")

    unmapped = backlog.get("unmapped_items", [])
    if unmapped:
        lines += [
            "## Unmapped Controls",
            "",
            "| Control | Reason |",
            "|---------|--------|",
        ]
        for item in unmapped:
            cid = item.get("legacy_control_id", "?")
            lines.append(f"| `{cid}` | No catalog mapping — requires manual review |")
        lines.append("")

    lines.append(
        "*Evidence collected by the platform connector skill. "
        "For full query source code see `skills/sfdc_connect/sfdc_connect.py` "
        "or `skills/workday_connect/workday_connect.py`.*"
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# NIST section renderer
# ---------------------------------------------------------------------------

_NIST_STATUS_ICON = {"pass": "✅", "partial": "⚠️", "fail": "❌"}
_NIST_OVERALL_ICON = {"block": "⛔", "flag": "🚩", "pass": "✅"}
_NIST_GATE_BANNERS = {
    "block": (
        "> ⛔ **GOVERNANCE GATE: BLOCKED**  \n"
        "> This assessment has been flagged by the NIST AI RMF reviewer. "
        "Do not distribute this report until blocking issues are resolved. "
        "See the NIST AI RMF Governance Review section at the end of this document.\n"
    ),
    "flag": (
        "> 🚩 **GOVERNANCE FLAG: REVIEW REQUIRED**  \n"
        "> The NIST AI RMF reviewer has raised issues requiring attention before this report "
        "is submitted for Security Team review. See the NIST AI RMF Governance Review section at the end.\n"
    ),
}
_NIST_APPOWNER_NOTE = {
    "block": (
        "> ⛔ **Note:** This security assessment has been blocked by an internal governance review. "
        "Your remediation plan is valid, but the overall report cannot be submitted to the security team "
        "until governance issues are resolved. Your security architect will follow up.\n"
    ),
    "flag": (
        "> 🚩 **Note:** This security assessment has been flagged for governance review. "
        "Your action plan below is accurate — please proceed with remediation. "
        "Your security architect may follow up with additional questions.\n"
    ),
}


def _render_nist_section(nist: dict[str, Any]) -> str:
    review = nist.get("nist_ai_rmf_review", nist)
    overall = review.get("overall", "unknown").lower()
    overall_icon = _NIST_OVERALL_ICON.get(overall, "ℹ️")
    reviewed_at = review.get("reviewed_at_utc", "unknown")
    reviewer = review.get("reviewer", "nist-reviewer")

    lines = [
        "---",
        "",
        "## NIST AI RMF Governance Review",
        "",
        f"### {overall_icon} Overall Verdict: {overall.upper()}",
        "",
        "| Function | Status | Notes |",
        "|---|---|---|",
    ]
    for fn in ["govern", "map", "measure", "manage"]:
        data = review.get(fn, {})
        status = data.get("status", "unknown")
        icon = _NIST_STATUS_ICON.get(status, "—")
        notes = data.get("notes", "—")
        lines.append(f"| **{fn.upper()}** | {icon} {status.upper()} | {notes} |")

    blocking = review.get("blocking_issues", [])
    if blocking:
        lines += ["", "### Blocking Issues", ""]
        for i, issue in enumerate(blocking, 1):
            lines.append(f"{i}. {issue}")

    recs = review.get("recommendations", [])
    if recs:
        lines += ["", "### Recommendations", ""]
        for i, rec in enumerate(recs, 1):
            lines.append(f"{i}. {rec}")

    lines += [
        "",
        f"*Reviewed: {reviewed_at} — Reviewer: {reviewer}*",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mock templates (for --mock-llm / CI)
# ---------------------------------------------------------------------------

_MOCK_TEMPLATES: dict[str, str] = {
    "app-owner": (
        "## Executive Summary\n\nMock report for testing.\n\n"
        "## What Happens Next\n\nRemediate items above within SLA windows.\n"
    ),
    "security": (
        "## Executive Summary\n\nMock security report for testing.\n\n"
        "## Risk Analysis\n\nCritical failures in identity and logging domains require immediate attention.\n"
    ),
}


def _call_llm(system_prompt: str, user_msg: str, model: str, mock: bool = False) -> str:
    if mock:
        audience = "security" if "Security Team" in system_prompt else "app-owner"
        return _MOCK_TEMPLATES[audience]

    try:
        import openai
    except ImportError:
        click.echo("ERROR: openai package not installed. Run: pip install openai", err=True)
        sys.exit(1)

    api_key = os.getenv("OPENAI_API_KEY")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not api_key and not (azure_key and azure_endpoint):
        click.echo("ERROR: set OPENAI_API_KEY or both AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT.", err=True)
        sys.exit(1)

    if azure_key and azure_endpoint:
        client = openai.AzureOpenAI(
            api_key=azure_key,
            azure_endpoint=azure_endpoint,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
    else:
        client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=4096,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    )
    return response.choices[0].message.content.strip()


def _apply_table_borders(docx_path: Path) -> None:
    """Post-process DOCX: apply full single-line borders to every table cell."""
    try:
        from copy import deepcopy

        from docx import Document
        from docx.oxml.ns import qn
        from lxml import etree
    except ImportError:
        return  # python-docx not installed; skip silently

    _BORDER_XML = (
        '<w:tcBorders xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        "</w:tcBorders>"
    )
    border_proto = etree.fromstring(_BORDER_XML)

    doc = Document(docx_path)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                tcp = cell._tc.get_or_add_tcPr()  # noqa: SLF001
                existing = tcp.find(qn("w:tcBorders"))
                if existing is not None:
                    tcp.remove(existing)
                tcp.append(deepcopy(border_proto))
    doc.save(docx_path)


def _run_pandoc(md_path: Path, docx_path: Path) -> None:
    template = Path(__file__).parent / "report_template.docx"
    cmd = ["pandoc", str(md_path), "-o", str(docx_path)]
    if template.exists():
        cmd += ["--reference-doc", str(template)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
    except FileNotFoundError:
        click.echo("WARNING: pandoc not found — DOCX not generated. Install pandoc to enable.", err=True)
        return
    except subprocess.CalledProcessError as exc:
        click.echo(f"WARNING: pandoc failed: {exc.stderr.decode()}", err=True)
        return
    _apply_table_borders(docx_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """report-gen — LLM-driven governance report generator."""


@cli.command()
@click.option("--backlog", required=True, help="Path to backlog.json from oscal_gap_map.")
@click.option(
    "--audience",
    required=True,
    type=click.Choice(["app-owner", "security"]),
    help="Report audience.",
)
@click.option("--out", required=True, help="Output file path (.md).")
@click.option("--sscf-benchmark", "sscf_benchmark", default=None, help="Path to sscf_report.json.")
@click.option("--nist-review", "nist_review", default=None, help="Path to nist_review.json.")
@click.option("--org-alias", "org_alias", default=None, help="Org alias for report header.")
@click.option("--title", default=None, help="Custom report title.")
@click.option(
    "--platform",
    type=click.Choice(["salesforce", "workday"]),
    default=None,
    help="Platform being assessed — drives OSCAL provenance table (auto-detected if omitted).",
)
@click.option("--dry-run", is_flag=True, help="Print plan without writing files.")
@click.option("--mock-llm", is_flag=True, help="Use deterministic template output (no API call). For testing.")
@click.option("--drift-report", "drift_report", default=None, help="Path to drift_report.json from drift_check.py.")
@click.option(
    "--iso27001-catalog",
    "iso27001_catalog",
    default=None,
    help="Path to iso27001_2022_annex_a_catalog.yaml for full 93-control SoA. Auto-detected if omitted.",
)
@click.option(
    "--aicm-coverage",
    "aicm_coverage",
    default=None,
    help="Path to aicm_coverage.json from gen_aicm_crosswalk.py. Adds AICM AI governance section to annex.",
)
def generate(  # NOSONAR
    backlog: str,
    audience: str,
    out: str,
    sscf_benchmark: str | None,
    nist_review: str | None,
    org_alias: str | None,
    title: str | None,
    platform: str | None,
    dry_run: bool,
    mock_llm: bool,
    drift_report: str | None,
    iso27001_catalog: str | None,
    aicm_coverage: str | None,
) -> None:
    """Generate an executive governance report (Markdown + DOCX for security audience).

    Produces three documents for security audience:
      <out>                         — main report: scorecard + analysis + priority findings
      <out stem>_annex              — full control matrix + POAM + framework crosswalk tables
      <out stem>_evidence_methodology — API queries and collection methods per control
    """
    out_path = Path(out)
    if not out_path.suffix:
        out_path = out_path.with_suffix(".md")

    org = org_alias or "unknown-org"
    model = os.getenv("LLM_MODEL_REPORTER", "gpt-5.3-chat-latest")

    if dry_run:
        click.echo(f"report-gen [DRY-RUN]: would write {out_path}", err=True)
        if audience == "security":
            click.echo(f"report-gen [DRY-RUN]: would also write {out_path.with_suffix('.docx')}", err=True)
        return

    backlog_data = _load_json(backlog)
    platform = platform or backlog_data.get("platform", "salesforce")
    _platform_titles = {
        "salesforce": f"Salesforce Security Governance Assessment — {org}",
        "workday": f"Workday Security Governance Assessment — {org}",
    }
    report_title = title or _platform_titles.get(platform, f"SaaS Security Governance Assessment — {org}")
    sscf_data = _load_json(sscf_benchmark) if sscf_benchmark else None
    nist_data = _load_json(nist_review) if nist_review else None
    drift_data = _load_json(drift_report) if drift_report else None
    aicm_data = _load_json(aicm_coverage) if aicm_coverage else None

    # Resolve ISO 27001 catalog path — explicit arg → repo default → None (partial SoA)
    _default_catalog = _REPO / "config" / "iso27001" / "iso27001_2022_annex_a_catalog.yaml"
    _catalog_default_resolved: Path | None = _default_catalog if _default_catalog.exists() else None
    iso_catalog_path: Path | None = Path(iso27001_catalog) if iso27001_catalog else _catalog_default_resolved

    # ── NIST gate banner ─────────────────────────────────────────────────────
    banner = ""
    nist_section = ""
    if nist_data:
        review = nist_data.get("nist_ai_rmf_review", nist_data)
        overall = review.get("overall", "").lower()
        if audience == "security":
            banner = _NIST_GATE_BANNERS.get(overall, "")
            nist_section = _render_nist_section(nist_data)
            click.echo(f"report-gen: NIST verdict={overall.upper()}", err=True)
        elif audience == "app-owner":
            banner = _NIST_APPOWNER_NOTE.get(overall, "")

    # ── Companion document reference note (security only) ────────────────────
    stem = out_path.stem
    companion_note = ""
    if audience == "security":
        companion_note = (
            "> **Companion Documents**  \n"
            f"> This report is one of three documents produced by this assessment.  \n"
            f"> - **`{stem}_annex.docx`** — Full Control Matrix, Plan of Action & Milestones (POA&M), "
            "OSCAL Framework Provenance, CCM v4.1 Regulatory Crosswalk, ISO 27001:2022 SoA  \n"
            f"> - **`{stem}_evidence_methodology.docx`** — Per-control table showing the exact API query, "
            "endpoint, or collection method used to assess each control — use for auditing coverage "
            "and reproducing results  \n"
            "> All three files are in the same folder as this document.\n"
        )

    # ── Python-rendered structural sections ──────────────────────────────────
    scorecard = _render_executive_scorecard(backlog_data, sscf_data, org, report_title)
    domain_chart = _render_domain_chart(sscf_data) if sscf_data else ""
    drift_section = _render_drift_section(drift_data) if drift_data else ""
    priority = _render_priority_findings(backlog_data)
    not_assessed = _render_not_assessed(backlog_data) if audience == "security" else ""

    # ── Annex sections (security only) ───────────────────────────────────────
    full_matrix = _render_full_matrix(backlog_data) if audience == "security" else ""
    poam = _render_poam(backlog_data) if audience == "security" else ""
    provenance = _render_oscal_provenance(backlog_data, platform) if audience == "security" else ""
    ccm_crosswalk = _render_ccm_crosswalk(backlog_data) if audience == "security" else ""
    iso_soa = _render_iso27001_soa(backlog_data, iso_catalog_path) if audience == "security" else ""

    # ── LLM narrative ────────────────────────────────────────────────────────
    system_prompt = _SYSTEM_PROMPTS[audience]
    user_msg = _build_user_message(backlog_data, sscf_data, nist_data, audience, org, report_title)
    llm_narrative = _call_llm(system_prompt, user_msg, model, mock=mock_llm)

    # ── Main document: scorecard + domain + priority findings + narrative ─────
    main_parts = [
        p
        for p in [
            banner,
            companion_note,
            drift_section,
            scorecard,
            domain_chart,
            priority,
            llm_narrative,
            not_assessed,
            nist_section,
        ]
        if p
    ]
    markdown = "\n\n".join(main_parts)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path = out_path.resolve()
    out_path.write_text(markdown)  # NOSONAR — intentional CLI output path, not a web input
    click.echo(f"report-gen: wrote {out_path}", err=True)

    if audience == "security":
        docx_path = out_path.with_suffix(_DOCX_SUFFIX)
        _run_pandoc(out_path, docx_path)
        if docx_path.exists():
            click.echo(f"report-gen: wrote {docx_path}", err=True)

        # ── Annex document: full control matrix + POAM + framework tables ────
        annex_header = (
            f"# {report_title} — Annex\n\n"
            f"**Org:** {org} &nbsp;|&nbsp; "
            f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d')} &nbsp;|&nbsp; "
            f"**Assessment ID:** {backlog_data.get('assessment_id', 'unknown')}\n\n"
            "> This annex contains the full control matrix, plan of action & milestones, "
            "and framework crosswalk tables. Share the main assessment document for executive "
            "review; share this annex for governance tracking and audit evidence.\n"
        )
        aicm_section = _render_aicm_coverage(aicm_data) if aicm_data else ""
        annex_parts = [
            p for p in [annex_header, full_matrix, poam, provenance, ccm_crosswalk, iso_soa, aicm_section] if p
        ]
        annex_md = "\n\n".join(annex_parts)

        annex_md_path = out_path.with_name(out_path.stem + "_annex.md")
        annex_md_path = annex_md_path.resolve()
        annex_md_path.write_text(annex_md)  # NOSONAR — intentional CLI output path
        click.echo(f"report-gen: wrote {annex_md_path}", err=True)

        annex_docx_path = annex_md_path.with_suffix(_DOCX_SUFFIX)
        _run_pandoc(annex_md_path, annex_docx_path)
        if annex_docx_path.exists():
            click.echo(f"report-gen: wrote {annex_docx_path}", err=True)

        # ── Evidence methodology document ─────────────────────────────────────
        methodology = _render_evidence_methodology(backlog_data)
        if methodology:
            method_md_path = out_path.with_name(out_path.stem + "_evidence_methodology.md")
            method_md_path = method_md_path.resolve()
            method_md_path.write_text(methodology)  # NOSONAR — intentional CLI output path
            click.echo(f"report-gen: wrote {method_md_path}", err=True)

            method_docx_path = method_md_path.with_suffix(_DOCX_SUFFIX)
            _run_pandoc(method_md_path, method_docx_path)
            if method_docx_path.exists():
                click.echo(f"report-gen: wrote {method_docx_path}", err=True)


if __name__ == "__main__":
    cli()
