#!/usr/bin/env python3
"""
gen_arch_a3_pipeline.py  —  Architecture (3/3): Data Pipeline

Two swim lanes (Salesforce on top, Workday on bottom) showing the 7-phase
assessment pipeline with artifact files at each phase. The control mapping
chain and post-processing scripts are shown at the bottom.

Output: docs/arch-a3-pipeline.png  (20 × 9 inch canvas)
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "docs" / "arch-a3-pipeline.png"

# ── Palette ───────────────────────────────────────────────────────────────────
C_BD, C_BM, C_BL = "#1565C0", "#1E88E5", "#E3F2FD"
C_T,  C_TL       = "#00897B", "#E0F2F1"
C_O,  C_OL       = "#F57C00", "#FFF3E0"
C_GD, C_GL       = "#2E7D32", "#E8F5E9"
C_P,  C_PL       = "#6A1B9A", "#F3E5F5"
C_A,  C_AL       = "#F57F17", "#FFF8E1"
C_GR             = "#546E7A"
C_BG             = "#FAFAFA"
FONT             = "DejaVu Sans"

fig, ax = plt.subplots(figsize=(20, 9), facecolor=C_BG)
ax.set_xlim(0, 20)
ax.set_ylim(0, 9)
ax.axis("off")


def box(x, y, w, h, fc, ec, lw=1.0, r=0.12, z=2):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={r}",
        facecolor=fc, edgecolor=ec, linewidth=lw, zorder=z,
    ))


def lbl(x, y, t, sz=8, c="black", bold=False, ha="center", va="center"):
    ax.text(x, y, t, fontsize=sz, color=c,
            fontweight="bold" if bold else "normal",
            ha=ha, va=va, fontfamily=FONT, multialignment="center", zorder=5)


def arr(x0, y0, x1, y1, c=C_GR, lw=1.2):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops={"arrowstyle": "->", "color": c, "lw": lw,
                            "connectionstyle": "arc3,rad=0.0"},
                zorder=4)


# ── Title ─────────────────────────────────────────────────────────────────────
lbl(10, 8.77, "saas-assurance — Reference Architecture (3/3): Data Pipeline",
    sz=12, bold=True, c=C_BD)
lbl(10, 8.47,
    "7-phase assessment pipeline  ·  Salesforce (45 SBS controls) and Workday (30 WSCC controls)"
    "  ·  All outputs to docs/oscal-salesforce-poc/generated/<org>/<date>/",
    sz=7.5, c=C_GR)

# ─────────────────────────────────────────────────────────────────────────────
# Phase definitions: (label, skill, artifact_file, phase_num)
# ─────────────────────────────────────────────────────────────────────────────
phases = [
    ("Phase 1\nCollect",    "sfdc-connect\nworkday-connect",   "sfdc_raw.json\nworkday_raw.json"),
    ("Phase 2\nAssess",     "oscal-assess",                    "gap_analysis.json\n45/30 controls"),
    ("Phase 3\nGap Map",    "oscal_gap_map.py",                "backlog.json\nremediation items"),
    ("Phase 4\nScore",      "sscf-benchmark",                  "sscf_report.json\nRED/AMBER/GREEN"),
    ("Phase 5\nNIST Gate",  "nist-review",                     "nist_review.json\npass/flag/block"),
    ("Phase 5b\nAICM",      "gen_aicm_crosswalk",              "aicm_coverage.json\n243 controls"),
    ("Phase 6\nReport",     "report-gen",                      "report_*.md\nreport_*.docx"),
]

# Phase box geometry
PH_W = 2.35   # phase box width
PH_H = 1.6    # phase box height
ART_H = 0.7   # artifact box height
GAP = 0.3     # gap between phase boxes
START_X = 0.5
PHASE_STEP = PH_W + GAP  # 2.65

# Phase x left edges
phase_x = [START_X + i * PHASE_STEP for i in range(7)]
phase_cx = [x + PH_W / 2 for x in phase_x]

# ─────────────────────────────────────────────────────────────────────────────
# SALESFORCE swim lane
# ─────────────────────────────────────────────────────────────────────────────
SFDC_LANE_Y = 4.55
SFDC_LANE_H = 3.7
box(0.25, SFDC_LANE_Y, 19.5, SFDC_LANE_H, C_OL, C_O, lw=1.2, r=0.2, z=1)
lbl(10, SFDC_LANE_Y + SFDC_LANE_H - 0.22,
    "Salesforce Pipeline  (45 SBS controls  ·  JWT Bearer  ·  REST + Tooling + Metadata API)",
    sz=8.5, bold=True, c=C_O)

SFDC_PHASE_Y  = SFDC_LANE_Y + 1.2   # phase box bottom
SFDC_ART_Y    = SFDC_LANE_Y + 0.35  # artifact box bottom

for i, (phase_lbl, skill, artifact) in enumerate(phases):
    px = phase_x[i]
    cx = phase_cx[i]
    # phase box (teal)
    box(px, SFDC_PHASE_Y, PH_W, PH_H, C_TL, C_T, lw=1.0)
    lbl(cx, SFDC_PHASE_Y + PH_H - 0.35, phase_lbl, sz=8.0, bold=True, c=C_T)
    lbl(cx, SFDC_PHASE_Y + 0.42, skill, sz=6.2, c=C_GR)
    # artifact box (green)
    box(px, SFDC_ART_Y, PH_W, ART_H, C_GL, C_GD, lw=0.8)
    lbl(cx, SFDC_ART_Y + ART_H / 2, artifact, sz=6.0, c=C_GD)
    # arrow to next
    if i < 6:
        arr(px + PH_W, SFDC_PHASE_Y + PH_H / 2,
            phase_x[i + 1], SFDC_PHASE_Y + PH_H / 2,
            c=C_T, lw=1.1)

# ─────────────────────────────────────────────────────────────────────────────
# WORKDAY swim lane
# ─────────────────────────────────────────────────────────────────────────────
WD_LANE_Y = 0.9
WD_LANE_H = 3.4
box(0.25, WD_LANE_Y, 19.5, WD_LANE_H, "#EDE7F6", "#7B1FA2", lw=1.2, r=0.2, z=1)
lbl(10, WD_LANE_Y + WD_LANE_H - 0.22,
    "Workday Pipeline  (30 WSCC controls  ·  OAuth 2.0 Client Credentials  ·  REST + RaaS + manual)",
    sz=8.5, bold=True, c="#6A1B9A")

WD_PHASE_Y = WD_LANE_Y + 1.2
WD_ART_Y   = WD_LANE_Y + 0.35

for i, (phase_lbl, skill, artifact) in enumerate(phases):
    px = phase_x[i]
    cx = phase_cx[i]
    # phase box (purple-teal)
    box(px, WD_PHASE_Y, PH_W, PH_H, "#E0F2F1", "#5C6BC0", lw=1.0)
    lbl(cx, WD_PHASE_Y + PH_H - 0.35, phase_lbl, sz=8.0, bold=True, c="#5C6BC0")
    lbl(cx, WD_PHASE_Y + 0.42, skill, sz=6.2, c=C_GR)
    # artifact box
    box(px, WD_ART_Y, PH_W, ART_H, C_GL, C_GD, lw=0.8)
    lbl(cx, WD_ART_Y + ART_H / 2, artifact, sz=6.0, c=C_GD)
    # arrow to next
    if i < 6:
        arr(px + PH_W, WD_PHASE_Y + PH_H / 2,
            phase_x[i + 1], WD_PHASE_Y + PH_H / 2,
            c="#5C6BC0", lw=1.1)

# vertical divider between swim lanes
ax.plot([0.25, 19.75], [SFDC_LANE_Y, SFDC_LANE_Y],
        color=C_GR, lw=0.8, linestyle="--", zorder=3)

# ─────────────────────────────────────────────────────────────────────────────
# Control mapping chain footer
# ─────────────────────────────────────────────────────────────────────────────
box(0.25, 0.08, 14.5, 0.68, "#E8EAF6", "#3949AB", lw=0.9, r=0.12)
lbl(7.5, 0.62, "Control Mapping Chain", sz=7, bold=True, c="#283593")
lbl(7.5, 0.3,
    "Platform control (SBS / WSCC)  →  SSCF domain  →  CCM v4.1"
    "  →  ISO 27001:2022 Annex A  →  SOX · HIPAA · SOC2 TSC · PCI DSS · GDPR · NIST 800-53",
    sz=6.2, c="#283593")

# Post-processing scripts
box(15.0, 0.08, 4.75, 0.68, C_PL, C_P, lw=0.9, r=0.12)
lbl(17.38, 0.62, "OSCAL Post-processing  (manual)", sz=7, bold=True, c=C_P)
lbl(17.38, 0.3,
    "gen_poam.py  ·  gen_ssp.py\nassessment_results.py  →  OSCAL 1.1.2",
    sz=6.2, c=C_P)

plt.tight_layout(pad=0)
plt.savefig(OUT, dpi=160, bbox_inches="tight", facecolor=C_BG)
plt.close()
print(f"Written → {OUT}")
