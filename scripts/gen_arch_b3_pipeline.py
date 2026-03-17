#!/usr/bin/env python3
"""
gen_arch_b3_pipeline.py  —  Architecture (3/3): Data Pipeline (diagrams lib)

Clean left-to-right pipeline: both Salesforce and Workday flows, skill CLIs,
artifact files at each phase, and governance deliverables. Complements
arch-a3-pipeline.png (matplotlib swim-lane version).

Output: docs/arch-b3-pipeline.png
"""

from __future__ import annotations

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.generic.storage import Storage
from diagrams.onprem.compute import Server
from diagrams.programming.flowchart import Document, MultipleDocuments
from diagrams.programming.language import Python

_OUT = str(Path(__file__).resolve().parents[1] / "docs" / "arch-b3-pipeline")

_GRAPH = {
    "fontsize": "12",
    "bgcolor": "#FAFAFA",
    "pad": "0.8",
    "splines": "ortho",
    "nodesep": "0.55",
    "ranksep": "1.0",
    "label": (
        "saas-assurance — Reference Architecture (3/3): Data Pipeline\n"
        "7-phase assessment  ·  Salesforce (45 SBS controls) + Workday (30 WSCC controls)"
        "  ·  All outputs to docs/oscal-salesforce-poc/generated/<org>/<date>/"
    ),
    "labelloc": "t",
    "labelfontsize": "13",
}
_NODE = {"fontsize": "11"}


def main() -> None:
    with Diagram(
        "saas-assurance Data Pipeline",
        filename=_OUT,
        show=False,
        graph_attr=_GRAPH,
        node_attr=_NODE,
        direction="LR",
    ):
        # ── SaaS inputs ───────────────────────────────────────────────────────
        with Cluster("SaaS Platforms  (read-only)"):
            with Cluster("Salesforce Org"):
                sfdc = Server("JWT Bearer Flow\nREST + Tooling + Metadata")
            with Cluster("Workday Tenant  (HCM / Finance)"):
                workday = Server("OAuth 2.0 Client Creds\nREST API · RaaS · Manual")

        # ── Phase 1: Collect ──────────────────────────────────────────────────
        with Cluster("Phase 1 — Collect"):
            sfdc_conn = Python("sfdc-connect")
            wd_conn = Python("workday-connect")
            raw_sfdc = Storage("sfdc_raw.json")
            raw_wd = Storage("workday_raw.json")

        # ── Phase 2: Assess ───────────────────────────────────────────────────
        with Cluster("Phase 2 — Assess"):
            osc_assess = Python("oscal-assess\n(SBS + WSCC catalog)")
            gap_json = Storage("gap_analysis.json\n45 / 30 controls")

        # ── Phase 3: Gap Map ──────────────────────────────────────────────────
        with Cluster("Phase 3 — Gap Map"):
            gap_map = Python("oscal_gap_map.py")
            backlog = Storage("backlog.json\nremediation items")

        # ── Phase 4: Score ────────────────────────────────────────────────────
        with Cluster("Phase 4 — Score"):
            sscf_bench = Python("sscf-benchmark")
            sscf_json = Storage("sscf_report.json\nRED / AMBER / GREEN")

        # ── Phase 5: NIST Gate ────────────────────────────────────────────────
        with Cluster("Phase 5 — NIST AI RMF Gate"):
            nist_skill = Python("nist-review")
            nist_json = Storage("nist_review.json\npass / flag / block")

        # ── Phase 5b: AICM ────────────────────────────────────────────────────
        with Cluster("Phase 5b — AICM Crosswalk"):
            aicm_skill = Python("gen_aicm_crosswalk\nSSCF → AICM v1.0.3")
            aicm_json = Storage("aicm_coverage.json\n243 controls · 18 domains")

        # ── Phase 6: Report ───────────────────────────────────────────────────
        with Cluster("Phase 6 — Report Generation"):
            rep_gen = Python("report-gen")
            app_report = Document("report_*_remediation.md\nApp Owner audience")
            sec_report = MultipleDocuments("report_*_security.md + .docx\nSecurity Team + AICM annex")

        # ── Post-processing (manual / optional) ───────────────────────────────
        with Cluster("Post-processing  (manual · OSCAL 1.1.2)"):
            oscal_out = MultipleDocuments("poam.json\nssp.json\nassessment_results.json")

        # ── Audit ─────────────────────────────────────────────────────────────
        with Cluster("Audit Trail"):
            audit = Storage("audit.jsonl\ntool · args · status · duration_ms")

        # ── Pipeline connections ───────────────────────────────────────────────
        green = Edge(color="darkgreen", lw="1.5")
        teal = Edge(color="teal")
        dotted = Edge(style="dotted", color="gray")

        sfdc >> green >> sfdc_conn >> raw_sfdc
        workday >> green >> wd_conn >> raw_wd

        raw_sfdc >> osc_assess
        raw_wd >> osc_assess
        osc_assess >> gap_json >> gap_map >> backlog

        backlog >> sscf_bench >> sscf_json
        sscf_json >> nist_skill >> nist_json
        backlog >> aicm_skill >> aicm_json

        nist_json >> teal >> rep_gen
        backlog >> teal >> rep_gen
        aicm_json >> teal >> rep_gen
        rep_gen >> app_report
        rep_gen >> sec_report

        backlog >> dotted >> oscal_out

        # Audit receives every tool call (shown as dotted)
        for node in [sfdc_conn, wd_conn, osc_assess, gap_map, sscf_bench, nist_skill, aicm_skill, rep_gen]:
            node >> Edge(style="dotted", color="orange") >> audit

    print(f"diagram written → {_OUT}.png")


if __name__ == "__main__":
    main()
