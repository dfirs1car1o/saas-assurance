#!/usr/bin/env python3
"""
gen_arch_a1_overview.py  —  Architecture (1/3): System Overview

All six sections at a glance. Agent layer is summarised — see arch-a2-agents
for the full agent detail. Skills use a 2-column grid for breathing room.

Output: docs/arch-a1-overview.png  (18 × 10 inch canvas)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "docs" / "arch-a1-overview.png"

# ── Palette ───────────────────────────────────────────────────────────────────
C_BD, C_BM, C_BL = "#1565C0", "#1E88E5", "#E3F2FD"
C_T, C_TL = "#00897B", "#E0F2F1"
C_O, C_OL = "#F57C00", "#FFF3E0"
C_GD, C_GL = "#2E7D32", "#E8F5E9"
C_P, C_PL = "#6A1B9A", "#F3E5F5"
C_A, C_AL = "#F57F17", "#FFF8E1"
C_GR = "#546E7A"
C_BG = "#FAFAFA"
FONT = "DejaVu Sans"

fig, ax = plt.subplots(figsize=(18, 10), facecolor=C_BG)
ax.set_xlim(0, 18)
ax.set_ylim(0, 10)
ax.axis("off")


def box(x, y, w, h, fc, ec, lw=1.0, r=0.15, z=2):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={r}",
            facecolor=fc,
            edgecolor=ec,
            linewidth=lw,
            zorder=z,
        )
    )


def lbl(x, y, t, sz=8, c="black", bold=False, ha="center", va="center"):
    ax.text(
        x,
        y,
        t,
        fontsize=sz,
        color=c,
        fontweight="bold" if bold else "normal",
        ha=ha,
        va=va,
        fontfamily=FONT,
        multialignment="center",
        zorder=5,
    )


def sec(x, y, w, h, title, fc, ec, tc, tsz=8.5):
    box(x, y, w, h, fc, ec, lw=1.2, r=0.2, z=1)
    lbl(x + w / 2, y + h - 0.2, title, sz=tsz, c=tc, bold=True)


def arr(x0, y0, x1, y1, c=C_GR, lw=1.2):
    ax.annotate(
        "",
        xy=(x1, y1),
        xytext=(x0, y0),
        arrowprops={"arrowstyle": "->", "color": c, "lw": lw, "connectionstyle": "arc3,rad=0.0"},
        zorder=4,
    )


# ── Title ─────────────────────────────────────────────────────────────────────
lbl(9, 9.77, "saas-assurance — Reference Architecture (1/3): System Overview", sz=12, bold=True, c=C_BD)
lbl(
    9,
    9.48,
    "Read-only  ·  JWT Bearer (SFDC)  ·  OAuth 2.0 (Workday)  ·  OWASP Agentic App Top 10  ·  10 agents  ·  7 skills",
    sz=7.5,
    c=C_GR,
)

# ── OSCAL Config (top-left) ───────────────────────────────────────────────────
sec(0.3, 5.85, 8.5, 3.25, "OSCAL Config  (config/)", C_PL, C_P, C_P)
for text, cx in [
    ("SSCF v1.0 Catalog\n36 controls · 6 domains", 1.45),
    ("SBS v1.0 Profile\n45 Salesforce controls", 3.6),
    ("WSCC v1.0 Profile\n30 Workday controls", 5.75),
    ("CCM v4.1 · AICM v1.0.3\nISO 27001 · EU AI Act", 7.9),
]:
    box(cx - 1.05, 6.1, 2.1, 1.35, C_PL, C_P, lw=0.8)
    lbl(cx, 6.78, text, sz=6.8, c=C_P)
lbl(4.55, 7.65, "config/component-definitions/  ←  per-control evidence spec (API query + method)", sz=6.5, c=C_GR)

# ── SaaS Platforms (top-right) ────────────────────────────────────────────────
sec(9.1, 5.85, 8.6, 3.25, "SaaS Platforms  (read-only)", C_OL, C_O, C_O)
box(9.3, 6.1, 3.85, 2.75, C_OL, C_O, lw=1.0)
lbl(11.25, 8.55, "Workday Tenant", sz=8.5, bold=True, c=C_O)
for i, t in enumerate(
    ["HCM / Finance", "OAuth 2.0 Client Credentials", "REST API v1 · RaaS (custom reports)", "Manual questionnaire"]
):
    lbl(11.25, 8.2 - i * 0.33, t, sz=6.8, c=C_GR)
box(13.4, 6.1, 4.0, 2.75, C_OL, C_O, lw=1.0)
lbl(15.4, 8.55, "Salesforce Org", sz=8.5, bold=True, c=C_O)
for i, t in enumerate(["Any edition", "JWT Bearer Flow", "REST + Tooling + Metadata API", "SecuritySettings SOQL"]):
    lbl(15.4, 8.2 - i * 0.33, t, sz=6.8, c=C_GR)

# ── Agent Layer (center-left, summary) ───────────────────────────────────────
sec(0.3, 1.1, 8.5, 4.55, "Agent Layer  (OpenAI API  ·  gpt-5.3-chat-latest)", C_BL, C_BD, C_BD)

# Left summary box — agent roster
box(0.5, 2.35, 3.9, 2.95, "#BBDEFB", C_BM, lw=0.9)
lbl(2.45, 5.05, "10 Agents  ·  18-turn ReAct loop", sz=7.5, bold=True, c=C_BD)
for i, line in enumerate(
    [
        "Orchestrator  — plans + dispatches",
        "Collector  — sfdc + workday",
        "Assessor  — OSCAL gap analysis",
        "Reporter  — MD + DOCX narrative",
        "NIST Reviewer  — AI RMF gate",
    ]
):
    lbl(2.45, 4.72 - i * 0.5, line, sz=6.8, c=C_BD)

# Right summary box — more agents + loop stats
box(4.65, 2.35, 3.9, 2.95, "#BBDEFB", C_BM, lw=0.9)
lbl(6.6, 5.05, "OWASP Hardened  ·  Fail-Closed", sz=7.5, bold=True, c=C_BD)
for i, line in enumerate(
    [
        "Delivery Reviewer  — delivery QA",
        "Security Reviewer  — AppSec CI",
        "SFDC Expert  — on-call specialist",
        "Workday Expert  — on-call specialist",
        "Container Expert  — Docker / infra",
    ]
):
    lbl(6.6, 4.72 - i * 0.5, line, sz=6.8, c=C_BD)

# OWASP harness strip
box(0.5, 1.28, 8.0, 0.85, C_AL, C_A, lw=0.9)
lbl(4.5, 1.87, "Security Harness  (harness/loop.py · tools.py)", sz=7, bold=True, c=C_A)
lbl(
    4.5,
    1.52,
    "_TOOL_REQUIRES gate  ·  memory guard  ·  _sanitize_org / _safe_inp_path  ·  audit.jsonl  ·  OWASP A1–A9",
    sz=6.2,
    c=C_GR,
)
lbl(4.5, 2.31, "→ See Architecture (2/3) for full agent detail", sz=6.5, c=C_BM)

# ── Skills (center-right, 2-column grid) ──────────────────────────────────────
sec(9.1, 1.1, 8.6, 4.55, "Skills  (Python CLIs  ·  read-only)", C_TL, C_T, C_T)
skills = [
    ("workday-connect", "OAuth 2.0 · REST · RaaS · manual"),
    ("sfdc-connect", "JWT Bearer · REST · Tooling · Meta"),
    ("oscal-assess", "OSCAL gap analysis (SFDC + WD)"),
    ("sscf-benchmark", "RED / AMBER / GREEN scoring"),
    ("nist-review", "AI RMF · pass / flag / block"),
    ("report-gen", "Markdown + DOCX packages"),
    ("gen_aicm_crosswalk", "SSCF → AICM v1.0.3 · 243 controls"),
]
for i, (name, sub) in enumerate(skills):
    col = i % 2
    row = i // 2
    sx = 9.35 + col * 4.2
    sy = 4.82 - row * 0.97
    box(sx, sy - 0.39, 3.9, 0.82, C_TL, C_T, lw=0.8)
    lbl(sx + 1.95, sy + 0.02, name, sz=7.5, bold=True, c=C_T)
    lbl(sx + 1.95, sy - 0.24, sub, sz=6.1, c=C_GR)

# ── Footer: Artifacts + Monitoring ────────────────────────────────────────────
box(0.3, 0.1, 11.5, 0.8, C_GL, C_GD, lw=0.9)
lbl(6.05, 0.72, "Generated Artifacts  (docs/oscal-salesforce-poc/generated/<org>/<date>/)", sz=7.0, bold=True, c=C_GD)
lbl(
    6.05,
    0.38,
    "sfdc_raw.json  →  gap_analysis.json  →  sscf_report.json  →  nist_review.json"
    "  →  aicm_coverage.json  →  report_*.md/.docx  +  audit.jsonl",
    sz=6.0,
    c=C_GR,
)

box(12.1, 0.1, 5.6, 0.8, C_GL, C_GD, lw=0.9)
lbl(14.9, 0.72, "Continuous Monitoring  (optional)", sz=7.0, bold=True, c=C_GD)
lbl(
    14.9,
    0.38,
    "docker compose up -d  →  OpenSearch · 3 dashboards · 40 panels  →  export_to_opensearch.py",
    sz=6.0,
    c=C_GR,
)

# ── Cross-section arrows ───────────────────────────────────────────────────────
arr(4.55, 5.85, 4.55, 5.65, c=C_P)  # OSCAL Config ↓ Agent Layer
arr(8.8, 3.35, 9.1, 3.35, c=C_T)  # Agent Layer → Skills
arr(13.4, 5.65, 13.4, 5.85, c=C_O)  # Skills ↑ SaaS Platforms
arr(4.55, 1.1, 4.55, 0.9, c=C_GD)  # Agent Layer ↓ Artifacts
arr(13.4, 1.1, 13.4, 0.9, c=C_GD)  # Skills ↓ Monitoring

plt.tight_layout(pad=0)
plt.savefig(OUT, dpi=160, bbox_inches="tight", facecolor=C_BG)
plt.close()
print(f"Written → {OUT}")
