#!/usr/bin/env python3
"""
gen_arch_b1_overview.py  —  Architecture (1/3): System Overview (diagrams lib)

Clean graphviz-laid-out overview: SaaS Platforms → Skills → Agent Layer → Outputs.
Complements arch-a1-overview.png (matplotlib) with auto-layout and iconography.

Output: docs/arch-b1-overview.png
"""
from __future__ import annotations

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.generic.storage import Storage
from diagrams.onprem.client import Users
from diagrams.onprem.compute import Server
from diagrams.programming.flowchart import MultipleDocuments
from diagrams.programming.language import Python

_OUT = str(Path(__file__).resolve().parents[1] / "docs" / "arch-b1-overview")

_GRAPH = {
    "fontsize": "13",
    "bgcolor": "#FAFAFA",
    "pad": "0.8",
    "splines": "ortho",
    "nodesep": "0.7",
    "ranksep": "1.1",
    "label": (
        "saas-assurance — Reference Architecture (1/3): System Overview\n"
        "Read-only  ·  JWT Bearer (SFDC)  ·  OAuth 2.0 (Workday)  ·  OWASP Agentic App Top 10"
    ),
    "labelloc": "t",
    "labelfontsize": "14",
}
_NODE = {"fontsize": "11"}


def main() -> None:
    with Diagram(
        "saas-assurance System Overview",
        filename=_OUT,
        show=False,
        graph_attr=_GRAPH,
        node_attr=_NODE,
        direction="LR",
    ):
        human = Users("Human / CI\nagent-loop run")

        # ── OSCAL Config ──────────────────────────────────────────────────────
        with Cluster("OSCAL Config  (config/)"):
            sscf_cat  = Storage("SSCF v1.0\n36 controls · 6 domains")
            sbs_prof  = Storage("SBS Profile\n45 Salesforce controls")
            wscc_prof = Storage("WSCC Profile\n30 Workday controls")
            ccm_aicm  = Storage("CCM v4.1 · AICM v1.0.3\nISO 27001 · EU AI Act")

        # ── SaaS Platforms ────────────────────────────────────────────────────
        with Cluster("SaaS Platforms  (read-only)"):
            with Cluster("Salesforce Org"):
                sfdc = Server("JWT Bearer Flow\nREST + Tooling + Metadata API")
            with Cluster("Workday Tenant"):
                workday = Server("OAuth 2.0 Client Credentials\nREST API · RaaS · Manual")

        # ── Skills ────────────────────────────────────────────────────────────
        with Cluster("Skills  (Python CLIs · shell=False · read-only)"):
            sk_sfdc  = Python("sfdc-connect")
            sk_wd    = Python("workday-connect")
            sk_osc   = Python("oscal-assess")
            sk_bench = Python("sscf-benchmark")
            sk_nist  = Python("nist-review")
            sk_rep   = Python("report-gen")
            sk_aicm  = Python("gen_aicm_crosswalk")

        # ── Agent Layer ───────────────────────────────────────────────────────
        with Cluster("Agent Layer  (gpt-5.3-chat-latest · 10 agents · 14-turn ReAct)"):
            orchestrator = Server("Orchestrator\nplans + dispatches")
            with Cluster("Assessment Agents"):
                collector = Server("Collector")
                assessor  = Server("Assessor")
                reporter  = Server("Reporter")
                nist_rev  = Server("NIST Reviewer\nAI RMF gate")
            with Cluster("Review Agents"):
                del_rev  = Server("Delivery Reviewer\n(STRICT)")
                sec_rev  = Server("Security Reviewer\nAppSec CI")
            with Cluster("Expert Agents  (on-call)"):
                sfdc_exp = Server("SFDC Expert")
                wd_exp   = Server("Workday Expert")
                ctr_exp  = Server("Container Expert")

        # ── Generated Outputs ─────────────────────────────────────────────────
        with Cluster("Generated Outputs  (docs/oscal-salesforce-poc/generated/)"):
            artifacts = Storage(
                "gap_analysis.json · backlog.json\n"
                "sscf_report.json · nist_review.json\n"
                "aicm_coverage.json · audit.jsonl"
            )
            reports = MultipleDocuments(
                "report_*.md (app-owner + security)\n"
                "report_*.docx  +  AICM annex"
            )

        # ── Connections ───────────────────────────────────────────────────────
        dotted_cfg  = Edge(style="dotted", color="purple")
        solid_green = Edge(color="darkgreen", lw="1.5")
        dashed_blue = Edge(style="dashed", color="steelblue")
        gray        = Edge(style="dashed", color="gray")

        # Config → assessment agents via assessor
        sscf_cat  >> dotted_cfg >> assessor
        sbs_prof  >> dotted_cfg >> assessor
        wscc_prof >> dotted_cfg >> assessor
        ccm_aicm  >> dotted_cfg >> sk_aicm

        # Human → Orchestrator
        human >> orchestrator

        # Orchestrator → agents
        orchestrator >> dashed_blue >> collector
        orchestrator >> dashed_blue >> assessor
        orchestrator >> dashed_blue >> reporter
        orchestrator >> dashed_blue >> nist_rev
        orchestrator >> dashed_blue >> del_rev
        orchestrator >> dashed_blue >> sec_rev
        orchestrator >> dashed_blue >> sfdc_exp
        orchestrator >> dashed_blue >> wd_exp
        orchestrator >> dashed_blue >> ctr_exp

        # Agents → skills
        collector >> gray >> sk_sfdc
        collector >> gray >> sk_wd
        assessor  >> gray >> sk_osc
        assessor  >> gray >> sk_bench
        assessor  >> gray >> sk_aicm
        nist_rev  >> gray >> sk_nist
        reporter  >> gray >> sk_rep

        # Skills → platforms (read)
        sk_sfdc >> solid_green >> sfdc
        sk_wd   >> solid_green >> workday

        # Skills → artifacts
        sk_sfdc  >> artifacts
        sk_wd    >> artifacts
        sk_osc   >> artifacts
        sk_bench >> artifacts
        sk_nist  >> artifacts
        sk_aicm  >> artifacts
        sk_rep   >> reports

    print(f"diagram written → {_OUT}.png")


if __name__ == "__main__":
    main()
