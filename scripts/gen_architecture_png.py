#!/usr/bin/env python3
"""
gen_architecture_png.py — Generate docs/architecture.png

Reference architecture for saas-posture.
JWT-only for Salesforce, OAuth 2.0 / REST / RaaS for Workday.  No SOAP anywhere.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "docs" / "architecture.png"

# ── Colour palette ────────────────────────────────────────────────────────────
C_BLUE_DARK = "#1565C0"  # section headers
C_BLUE_MID = "#1E88E5"  # agent boxes
C_BLUE_LIGHT = "#E3F2FD"  # section bg
C_TEAL = "#00897B"  # skill / CLI boxes
C_TEAL_LIGHT = "#E0F2F1"  # skills section bg
C_ORANGE = "#F57C00"  # SaaS platform
C_ORANGE_LIGHT = "#FFF3E0"  # platform section bg
C_GREEN_DARK = "#2E7D32"  # output / artifact
C_GREEN_LIGHT = "#E8F5E9"  # artifact section bg
C_PURPLE = "#6A1B9A"  # config / OSCAL
C_PURPLE_LIGHT = "#F3E5F5"  # config section bg
C_GREY = "#546E7A"  # secondary text
C_RED = "#C62828"  # critical / auth
C_WHITE = "#FFFFFF"
C_BG = "#FAFAFA"

FONT_MAIN = "DejaVu Sans"

fig, ax = plt.subplots(figsize=(18, 26), facecolor=C_BG)
ax.set_xlim(0, 18)
ax.set_ylim(0, 26)
ax.axis("off")
ax.set_facecolor(C_BG)


# ── Helpers ───────────────────────────────────────────────────────────────────


def box(x, y, w, h, fc, ec, lw=1.0, radius=0.18, zorder=2):
    p = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
        zorder=zorder,
    )
    ax.add_patch(p)
    return p


def label(x, y, text, size=8, color="black", bold=False, ha="center", va="center", wrap=False, zorder=5):
    weight = "bold" if bold else "normal"
    ax.text(
        x,
        y,
        text,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        zorder=zorder,
        fontfamily=FONT_MAIN,
        wrap=wrap,
        multialignment="center",
    )


def section(x, y, w, h, title, fc, ec, title_color, title_size=8.5):
    box(x, y, w, h, fc, ec, lw=1.2, radius=0.25, zorder=1)
    label(x + w / 2, y + h - 0.22, title, size=title_size, color=title_color, bold=True, zorder=3)


def arrow(x0, y0, x1, y1, color=C_GREY, lw=1.2, style="->", zorder=4):
    ax.annotate(
        "",
        xy=(x1, y1),
        xytext=(x0, y0),
        arrowprops={"arrowstyle": style, "color": color, "lw": lw, "connectionstyle": "arc3,rad=0.0"},
        zorder=zorder,
    )


def agent_box(x, y, w, h, name, subtitle="", fc=C_BLUE_LIGHT, ec=C_BLUE_MID):
    box(x, y, w, h, fc, ec, lw=1.0)
    label(x + w / 2, y + h / 2 + (0.1 if subtitle else 0), name, size=7.5, bold=True, color=C_BLUE_DARK)
    if subtitle:
        label(x + w / 2, y + h / 2 - 0.18, subtitle, size=6.2, color=C_GREY)


def skill_box(x, y, w, h, name, subtitle=""):
    box(x, y, w, h, C_TEAL_LIGHT, C_TEAL, lw=1.0)
    label(x + w / 2, y + h / 2 + (0.1 if subtitle else 0), name, size=7.5, bold=True, color=C_TEAL)
    if subtitle:
        label(x + w / 2, y + h / 2 - 0.18, subtitle, size=6.2, color=C_GREY)


def artifact_box(x, y, w, h, name, subtitle=""):
    box(x, y, w, h, C_GREEN_LIGHT, C_GREEN_DARK, lw=1.0)
    label(x + w / 2, y + h / 2 + (0.1 if subtitle else 0), name, size=7.5, bold=True, color=C_GREEN_DARK)
    if subtitle:
        label(x + w / 2, y + h / 2 - 0.18, subtitle, size=6.2, color=C_GREY)


def platform_box(x, y, w, h, name, lines):
    box(x, y, w, h, C_ORANGE_LIGHT, C_ORANGE, lw=1.2)
    label(x + w / 2, y + h - 0.22, name, size=8, bold=True, color=C_ORANGE)
    for i, line in enumerate(lines):
        label(x + w / 2, y + h - 0.48 - i * 0.28, line, size=6.8, color=C_GREY)


# ─────────────────────────────────────────────────────────────────────────────
# LAYOUT  (y=0 bottom, y=26 top)
# ─────────────────────────────────────────────────────────────────────────────

TOP = 25.7

# ── Title ─────────────────────────────────────────────────────────────────────
label(9, TOP - 0.05, "saas-posture — Reference Architecture", size=13, bold=True, color=C_BLUE_DARK)
label(9, TOP - 0.42, "Read-only · JWT Bearer (Salesforce) · OAuth 2.0 (Workday) · No SOAP", size=8, color=C_GREY)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — SaaS Platforms  (top right)
# ─────────────────────────────────────────────────────────────────────────────
SEC1_X, SEC1_Y, SEC1_W, SEC1_H = 11.4, 21.2, 6.3, 3.8
section(SEC1_X, SEC1_Y, SEC1_W, SEC1_H, "SaaS Platforms  (read-only)", C_ORANGE_LIGHT, C_ORANGE, C_ORANGE, 8.5)

# Workday box
platform_box(
    SEC1_X + 0.2,
    SEC1_Y + 0.3,
    2.8,
    3.0,
    "Workday Tenant",
    ["HCM / Finance", "OAuth 2.0 Client Credentials", "REST API v1", "RaaS (custom reports)", "Manual questionnaire"],
)

# Salesforce box
platform_box(
    SEC1_X + 3.3,
    SEC1_Y + 0.3,
    2.7,
    3.0,
    "Salesforce Org",
    ["Any edition", "JWT Bearer Flow", "Tooling API", "REST API", "Metadata API"],
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — OSCAL Config  (top left)
# ─────────────────────────────────────────────────────────────────────────────
SEC2_X, SEC2_Y, SEC2_W, SEC2_H = 0.3, 21.2, 10.7, 3.8
section(SEC2_X, SEC2_Y, SEC2_W, SEC2_H, "OSCAL Config  (config/)", C_PURPLE_LIGHT, C_PURPLE, C_PURPLE, 8.5)

config_items = [
    ("SSCF v1.0 Catalog\n36 controls · 6 domains", 1.5),
    ("SBS v1.0 Profile\n35 Salesforce controls", 3.8),
    ("WSCC v1.0 Profile\n30 Workday controls", 6.1),
    ("CCM v4.1 · AICM v1.0.3\nISO 27001 · AI Act", 8.4),
]
for text, cx in config_items:
    box(SEC2_X + cx - 1.0, SEC2_Y + 0.35, 2.1, 1.15, C_PURPLE_LIGHT, C_PURPLE, lw=0.8)
    label(SEC2_X + cx - 1.0 + 1.05, SEC2_Y + 0.35 + 0.57, text, size=6.8, color=C_PURPLE, bold=False)

# Component-definitions note
label(
    SEC2_X + 5.35,
    SEC2_Y + 1.75,
    "config/component-definitions/  ←  per-control evidence spec (API query + method)",
    size=6.5,
    color=C_GREY,
    ha="center",
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — Agent Layer
# ─────────────────────────────────────────────────────────────────────────────
SEC3_X, SEC3_Y, SEC3_W, SEC3_H = 0.3, 6.8, 11.0, 14.0
section(
    SEC3_X,
    SEC3_Y,
    SEC3_W,
    SEC3_H,
    "Agent Layer  (OpenAI API  ·  gpt-5.3-chat-latest)",
    C_BLUE_LIGHT,
    C_BLUE_DARK,
    C_BLUE_DARK,
    8.5,
)

# Orchestrator — centrepiece
ORC_X, ORC_Y, ORC_W, ORC_H = 0.65, 13.2, 3.0, 1.1
agent_box(ORC_X, ORC_Y, ORC_W, ORC_H, "Orchestrator", "plans + dispatches", fc="#BBDEFB", ec=C_BLUE_DARK)

# Sub-agents column
sub_agents = [
    ("Security Reviewer", "DevSecOps CI gate", 19.8),
    ("Collector", "sfdc + workday", 18.2),
    ("Assessor", "OSCAL gap analysis", 16.6),
    ("NIST Reviewer", "AI RMF gate", 15.0),
    ("Reporter", "MD + DOCX narrative", 13.4),
    ("SFDC Expert", "on-call specialist", 11.8),
    ("Workday Expert", "on-call specialist", 10.2),
]
for name, sub, y_pos in sub_agents:
    agent_box(4.6, y_pos - 0.55, 2.9, 0.95, name, sub)
    # dashed line from orchestrator to sub-agent
    ax.annotate(
        "",
        xy=(4.6, y_pos - 0.07),
        xytext=(ORC_X + ORC_W, ORC_Y + ORC_H / 2),
        arrowprops={
            "arrowstyle": "->,head_width=0.15,head_length=0.1",
            "color": C_BLUE_MID,
            "lw": 0.8,
            "linestyle": "dashed",
        },
        zorder=4,
    )

# Human actor
box(0.65, 19.3, 2.0, 0.8, "#E8EAF6", "#3949AB", lw=1.2)
label(1.65, 19.7, "Human / CI", size=7.5, bold=True, color="#283593")
label(1.65, 19.42, "agent-loop run", size=6.2, color=C_GREY)
arrow(1.65, 19.3, ORC_X + ORC_W / 2, ORC_Y + ORC_H, color="#283593", lw=1.2)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — Skills / CLIs
# ─────────────────────────────────────────────────────────────────────────────
SEC4_X, SEC4_Y, SEC4_W, SEC4_H = 11.6, 6.8, 6.1, 14.0
section(SEC4_X, SEC4_Y, SEC4_W, SEC4_H, "Skills  (Python CLIs  ·  read-only)", C_TEAL_LIGHT, C_TEAL, C_TEAL, 8.5)

skills = [
    ("workday-connect", "OAuth 2.0 · REST · RaaS · manual", 19.4),
    ("sfdc-connect", "JWT Bearer · REST · Tooling · Meta", 17.5),
    ("oscal-assess", "OSCAL gap analysis", 15.6),
    ("sscf-benchmark", "RED / AMBER / GREEN scoring", 13.7),
    ("nist-review", "AI RMF govern/map/measure/manage", 11.8),
    ("report-gen", "Markdown + DOCX packages", 9.9),
]
for name, sub, y_pos in skills:
    skill_box(SEC4_X + 0.3, y_pos - 0.45, 5.5, 0.82, name, sub)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — Generated Artifacts
# ─────────────────────────────────────────────────────────────────────────────
SEC5_X, SEC5_Y, SEC5_W, SEC5_H = 0.3, 1.8, 11.0, 4.7
section(
    SEC5_X,
    SEC5_Y,
    SEC5_W,
    SEC5_H,
    "Generated Artifacts  (docs/oscal-salesforce-poc/generated/)",
    C_GREEN_LIGHT,
    C_GREEN_DARK,
    C_GREEN_DARK,
    8.5,
)

artifacts = [
    ("sfdc_raw.json\nworkday_raw.json", "Phase 1 — Collect", 1.4),
    ("gap_analysis.json\nbacklog.json", "Phase 2-3 — Assess", 3.55),
    ("sscf_report.json", "Phase 4 — Score", 5.7),
    ("nist_review.json", "Phase 5 — Gate", 7.85),
    ("report_*.md/.docx\naicm_coverage.json", "Phase 5-6 — Report+AI", 10.0),
]
for text, phase, cx in artifacts:
    artifact_box(SEC5_X + cx - 1.1, SEC5_Y + 0.4, 2.0, 1.9, text, phase)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — Continuous Monitoring  (bottom right)
# ─────────────────────────────────────────────────────────────────────────────
SEC6_X, SEC6_Y, SEC6_W, SEC6_H = 11.6, 1.8, 6.1, 4.7
section(
    SEC6_X, SEC6_Y, SEC6_W, SEC6_H, "Continuous Monitoring  (optional)", C_GREEN_LIGHT, C_GREEN_DARK, C_GREEN_DARK, 8.5
)

box(SEC6_X + 0.3, SEC6_Y + 2.7, 5.5, 1.65, "#F1F8E9", C_GREEN_DARK, lw=0.9)
label(SEC6_X + 3.05, SEC6_Y + 3.72, "OpenSearch + Dashboards", size=8, bold=True, color=C_GREEN_DARK)
label(SEC6_X + 3.05, SEC6_Y + 3.38, "docker compose up -d  →  localhost:5601", size=6.8, color=C_GREY)
label(SEC6_X + 3.05, SEC6_Y + 3.06, "SSCF Overview · Salesforce · Workday dashboards", size=6.8, color=C_GREY)
label(SEC6_X + 3.05, SEC6_Y + 2.78, "40 pre-built panels · KQL platform isolation", size=6.8, color=C_GREY)

box(SEC6_X + 0.3, SEC6_Y + 0.4, 5.5, 2.0, "#F9FBE7", C_GREEN_DARK, lw=0.9)
label(SEC6_X + 3.05, SEC6_Y + 1.55, "export_to_opensearch.py", size=8, bold=True, color=C_GREEN_DARK)
label(SEC6_X + 3.05, SEC6_Y + 1.22, "--auto --org <alias> --date <YYYY-MM-DD>", size=6.8, color=C_GREY)
label(SEC6_X + 3.05, SEC6_Y + 0.90, "Indexes sscf-findings-* + sscf-runs-*", size=6.8, color=C_GREY)
label(SEC6_X + 3.05, SEC6_Y + 0.57, "Score trend · POA&M · Domain risk · Severity", size=6.8, color=C_GREY)

# ─────────────────────────────────────────────────────────────────────────────
# ARROWS between sections
# ─────────────────────────────────────────────────────────────────────────────

# Orchestrator ↔ skills (right)
for y_pos in [19.4 - 0.04, 17.5 - 0.04, 15.6 - 0.04, 13.7 - 0.04, 11.8 - 0.04, 9.9 - 0.04]:
    arrow(SEC3_X + SEC3_W, y_pos, SEC4_X, y_pos, color=C_TEAL, lw=1.0)

# Skills ↔ SaaS platforms
arrow(SEC4_X + 2.75, 19.4 - 0.04, SEC1_X + 1.6, SEC1_Y, color=C_ORANGE, lw=1.2)  # workday-connect → Workday
arrow(SEC4_X + 2.75, 17.5 - 0.04, SEC1_X + 4.65, SEC1_Y, color=C_ORANGE, lw=1.2)  # sfdc-connect → Salesforce

# Config → Assessor / Collector (left)
arrow(
    SEC2_X + 3.0,
    SEC2_Y,
    SEC3_X + 1.65,
    SEC3_Y + SEC3_H,
    color=C_PURPLE,
    lw=1.1,
    style="->,head_width=0.15,head_length=0.1",
)

# Artifacts → report-gen → Governance (right side of artifacts)
arrow(SEC5_X + SEC5_W, SEC5_Y + SEC5_H / 2, SEC6_X, SEC6_Y + SEC6_H / 2, color=C_GREEN_DARK, lw=1.2)

# Skills → artifacts (downward)
arrow(SEC4_X + SEC4_W / 2, SEC4_Y, SEC5_X + SEC5_W * 0.75, SEC5_Y + SEC5_H, color=C_TEAL, lw=1.2)

# ─────────────────────────────────────────────────────────────────────────────
# Framework chain banner at bottom
# ─────────────────────────────────────────────────────────────────────────────
chain_y = 0.95
ax.add_patch(
    FancyBboxPatch(
        (0.3, 0.35),
        17.4,
        0.85,
        boxstyle="round,pad=0,rounding_size=0.15",
        facecolor="#E8EAF6",
        edgecolor="#3949AB",
        lw=0.9,
        zorder=1,
    )
)
label(
    9,
    chain_y,
    "Framework chain:  Platform control  →  SSCF domain  →  CCM v4.1 / AICM v1.0.3"
    "  →  ISO 27001:2022 Annex A  →  SOX / HIPAA / SOC2 / NIST 800-53 / PCI DSS / GDPR / EU AI Act",
    size=6.8,
    color="#283593",
    bold=False,
)

# SAVE
plt.tight_layout(pad=0)
plt.savefig(OUT, dpi=160, bbox_inches="tight", facecolor=C_BG)
plt.close()
print(f"Written → {OUT}")
