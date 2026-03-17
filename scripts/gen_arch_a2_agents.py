#!/usr/bin/env python3
"""
gen_arch_a2_agents.py  —  Architecture (2/3): Agent Architecture

Deep-dive into the agent layer: Orchestrator, all 9 sub-agents in a 3×3 grid,
STRICT_AGENTS annotation, model/env override strip, memory layer, and the
full OWASP Agentic App security harness.

Output: docs/arch-a2-agents.png  (16 × 14 inch canvas)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "docs" / "arch-a2-agents.png"

# ── Palette ───────────────────────────────────────────────────────────────────
C_BD, C_BM, C_BL = "#1565C0", "#1E88E5", "#E3F2FD"
C_T, C_TL = "#00897B", "#E0F2F1"
C_GD, C_GL = "#2E7D32", "#E8F5E9"
C_P, C_PL = "#6A1B9A", "#F3E5F5"
C_A, C_AL = "#F57F17", "#FFF8E1"
C_GR = "#546E7A"
C_RD = "#C62828"
C_BG = "#FAFAFA"
FONT = "DejaVu Sans"

fig, ax = plt.subplots(figsize=(16, 14), facecolor=C_BG)
ax.set_xlim(0, 16)
ax.set_ylim(0, 14)
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


def sec(x, y, w, h, title, fc, ec, tc, tsz=9):
    box(x, y, w, h, fc, ec, lw=1.3, r=0.22, z=1)
    lbl(x + w / 2, y + h - 0.22, title, sz=tsz, c=tc, bold=True)


def arr(x0, y0, x1, y1, c=C_GR, lw=1.2, style="->", dash=False):
    ls = "dashed" if dash else "solid"
    ax.annotate(
        "",
        xy=(x1, y1),
        xytext=(x0, y0),
        arrowprops={"arrowstyle": style, "color": c, "lw": lw, "linestyle": ls, "connectionstyle": "arc3,rad=0.0"},
        zorder=4,
    )


# ── Title ─────────────────────────────────────────────────────────────────────
lbl(8, 13.77, "saas-assurance — Reference Architecture (2/3): Agent Architecture", sz=12, bold=True, c=C_BD)
lbl(
    8,
    13.47,
    "10 agents  ·  OpenAI gpt-5.3-chat-latest  ·  14-turn ReAct loop"
    "  ·  STRICT_AGENTS fail-closed  ·  OWASP Agentic App Top 10",
    sz=7.5,
    c=C_GR,
)

# ── Outer agent layer section ─────────────────────────────────────────────────
sec(0.3, 0.3, 15.4, 13.0, "Agent Layer  (harness/loop.py  ·  OpenAI tool_use ReAct)", C_BL, C_BD, C_BD)

# ── Human / CI ────────────────────────────────────────────────────────────────
box(6.25, 11.95, 3.5, 0.8, "#E8EAF6", "#3949AB", lw=1.2)
lbl(8.0, 12.38, "Human / CI", sz=8.5, bold=True, c="#283593")
lbl(8.0, 12.1, "agent-loop run --env dev --org <alias>", sz=6.5, c=C_GR)

# ── Orchestrator ──────────────────────────────────────────────────────────────
box(5.25, 10.45, 5.5, 1.2, "#BBDEFB", C_BD, lw=1.5, r=0.2)
lbl(8.0, 11.28, "Orchestrator", sz=10, bold=True, c=C_BD)
lbl(8.0, 10.97, "plans + dispatches  ·  quality gates  ·  finish() trigger", sz=7, c=C_GR)
lbl(8.0, 10.68, "gpt-5.3-chat-latest  ·  all CLI tools  ·  _MAX_TURNS=14", sz=6.5, c=C_GR)
arr(8.0, 11.95, 8.0, 11.65, c="#3949AB", lw=1.3)  # Human → Orchestrator

# ── Agent grid (3 × 3) ────────────────────────────────────────────────────────
# Columns: x positions for box left edge
COL_X = [0.6, 5.6, 10.6]  # each box width = 4.5
COL_CX = [2.85, 7.85, 12.85]  # column centres
# Rows: y positions for box bottom
ROW_Y = [7.8, 6.1, 4.4]  # each box height = 1.5
ROW_CY = [8.55, 6.85, 5.15]  # row centres

agents = [
    # (name, subtitle, is_strict)
    ("Security Reviewer", "AppSec + DevSecOps CI gate\non-demand · not pipeline dispatch", False),
    ("Delivery Reviewer", "final report delivery QA\ncredential exposure · status misrepresentation", True),
    ("Collector", "Salesforce + Workday collection\nsfdc-connect · workday-connect", True),
    ("Assessor", "OSCAL control mapping\noscal-assess · oscal_gap_map · sscf-benchmark", True),
    ("NIST Reviewer", "AI RMF 1.0 gate\npass / flag / block verdict", False),
    ("Reporter", "governance report generation\nreport-gen (MD + DOCX + AICM annex)", False),
    ("SFDC Expert", "on-call Salesforce specialist\nApex + SOQL + Connected Apps", True),
    ("Workday Expert", "on-call Workday HCM specialist\nRaaS + REST + manual config", True),
    ("Container Expert", "Docker Compose + OpenSearch\nJVM tuning · infra checks", False),
]

ORC_BOT = 10.45  # bottom of orchestrator box

for idx, (name, sub, is_strict) in enumerate(agents):
    col = idx % 3
    row = idx // 3
    bx, by = COL_X[col], ROW_Y[row]
    cx, cy = COL_CX[col], ROW_CY[row]

    fc = "#FDECEA" if is_strict else C_BL
    ec = C_RD if is_strict else C_BM
    box(bx, by, 4.5, 1.5, fc, ec, lw=1.0 if not is_strict else 1.2)
    lbl(cx, cy + 0.32, name, sz=8, bold=True, c=C_RD if is_strict else C_BD)
    lbl(cx, cy - 0.08, sub, sz=6.2, c=C_GR)
    if is_strict:
        box(cx + 1.3, by + 1.2, 0.95, 0.22, "#FFCDD2", C_RD, lw=0.7, r=0.05)
        lbl(cx + 1.78, by + 1.31, "STRICT", sz=5.5, bold=True, c=C_RD)

    # dashed arrow from orchestrator bottom to agent top
    ax.annotate(
        "",
        xy=(cx, by + 1.5),
        xytext=(8.0, ORC_BOT),
        arrowprops={
            "arrowstyle": "->,head_width=0.15,head_length=0.1",
            "color": C_BM,
            "lw": 0.7,
            "linestyle": "dashed",
            "connectionstyle": "arc3,rad=0.0",
        },
        zorder=3,
    )

# STRICT note
box(0.55, 3.95, 6.2, 0.3, "#FFEBEE", C_RD, lw=0.7, r=0.08)
lbl(
    3.65,
    4.1,
    "STRICT_AGENTS (fail-closed, full 6-field schema): "
    "delivery-reviewer · collector · assessor · sfdc-expert · workday-expert",
    sz=6.2,
    bold=False,
    c=C_RD,
)

# ── Model / env-override strip ────────────────────────────────────────────────
box(0.55, 3.1, 14.6, 0.65, "#E3F2FD", C_BM, lw=0.9)
lbl(7.85, 3.62, "Model Assignment  ·  All agents: gpt-5.3-chat-latest", sz=7.5, bold=True, c=C_BD)
lbl(
    7.85,
    3.3,
    "Override via env: LLM_MODEL_ORCHESTRATOR  ·  LLM_MODEL_ANALYST  ·  LLM_MODEL_REPORTER"
    "     Azure OpenAI Government: AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT (FedRAMP / IL5)",
    sz=6.3,
    c=C_GR,
)

# ── Memory / Qdrant strip ─────────────────────────────────────────────────────
box(0.55, 2.15, 14.6, 0.75, "#F3E5F5", C_P, lw=0.9)
lbl(7.85, 2.67, "Session Memory  (Mem0 + Qdrant)", sz=7.5, bold=True, c=C_P)
lbl(
    7.85,
    2.35,
    "Stores: org alias · prior assessment score · critical findings"
    "     Memory guard strips _INJECTION_PATTERNS before prompt inject  (OWASP A1 / A3)"
    "     QDRANT_IN_MEMORY=1 (default) · set QDRANT_HOST for persistent cross-session memory",
    sz=6.1,
    c=C_GR,
)

# ── OWASP Security Harness ────────────────────────────────────────────────────
box(0.55, 0.55, 14.6, 1.38, C_AL, C_A, lw=1.1, r=0.18)
lbl(7.85, 1.68, "Security Controls Harness  (harness/loop.py · harness/tools.py)", sz=8, bold=True, c=C_A)
# Six OWASP mitigations as sub-boxes
owasp = [
    ("A1 · A3", "Prompt Inject\nMemory Guard", "#FFF8E1"),
    ("A2", "_TOOL_REQUIRES\nSequencing Gate", "#FFF8E1"),
    ("A5", "_sanitize_org\n_safe_inp_path", "#FFF8E1"),
    ("A5", "subprocess\nshell=False", "#FFF8E1"),
    ("A7", "Tool allowlist\ndispatch()", "#FFF8E1"),
    ("A9", "audit.jsonl\nper run", "#FFF8E1"),
]
for i, (onum, desc, ofc) in enumerate(owasp):
    bx2 = 0.7 + i * 2.44
    box(bx2, 0.65, 2.25, 0.9, ofc, C_A, lw=0.75, r=0.1)
    lbl(bx2 + 1.125, 1.22, onum, sz=7, bold=True, c=C_A)
    lbl(bx2 + 1.125, 0.92, desc, sz=6.2, c=C_GR)

plt.tight_layout(pad=0)
plt.savefig(OUT, dpi=160, bbox_inches="tight", facecolor=C_BG)
plt.close()
print(f"Written → {OUT}")
