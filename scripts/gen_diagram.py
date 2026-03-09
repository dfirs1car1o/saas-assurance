#!/usr/bin/env python3
"""
gen_diagram.py — Generate reference architecture diagram for saas-posture.

Outputs: docs/architecture.png

Shows the multi-agent OpenAI layer orchestrating Python CLI skills across the
full assessment pipeline for both Salesforce and Workday platforms:

    [Salesforce] sfdc-connect → oscal-assess → oscal_gap_map → sscf-benchmark → report-gen
    [Workday]  workday-connect → oscal-assess → oscal_gap_map → sscf-benchmark → report-gen

Security Reviewer is a parallel DevSecOps audit agent — invoked by the
orchestrator on CI/CD and skill changes, not part of the main assessment flow.

SFDC Expert and Workday Expert are on-call specialists — invoked when findings
have needs_expert_review=true.

Run manually or automatically via GitHub Actions on every push to main.

Usage:
    python3 scripts/gen_diagram.py

Requires:
    pip install diagrams
    brew install graphviz   # macOS
    apt-get install graphviz  # Linux
"""

from __future__ import annotations

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.azure.identity import ActiveDirectory
from diagrams.generic.storage import Storage
from diagrams.onprem.compute import Server
from diagrams.programming.flowchart import Document, MultipleDocuments
from diagrams.programming.language import Python

_OUT = Path(__file__).resolve().parents[1] / "docs" / "architecture"

_GRAPH = {
    "fontsize": "12",
    "bgcolor": "white",
    "pad": "0.8",
    "splines": "ortho",
    "nodesep": "0.6",
    "ranksep": "0.9",
}

_NODE = {"fontsize": "11"}


def main() -> None:
    with Diagram(
        "SaaS Security Agents — Reference Architecture",
        filename=str(_OUT),
        show=False,
        graph_attr=_GRAPH,
        node_attr=_NODE,
        direction="LR",
    ):
        # ── Inputs ───────────────────────────────────────────────────────────
        with Cluster("SaaS Platforms  (read-only)"):
            sfdc = ActiveDirectory("Salesforce Org\n(Entra ID SSO)")
            workday = Server("Workday Tenant\n(HCM / Finance)")

        # ── OSCAL Config Layer ────────────────────────────────────────────────
        with Cluster("OSCAL Config  (config/)"):
            catalog = Storage("SSCF v1.0 Catalog\n36 controls")
            sfdc_profile = Storage("SBS Profile\n35 controls")
            wd_profile = Storage("WSCC Profile\n30 controls")
            sfdc_comp = Storage("Salesforce\nComponent Def")
            wd_comp = Storage("Workday\nComponent Def")

        # ── Agent Layer ──────────────────────────────────────────────────────
        with Cluster("Agent Layer  (OpenAI API)"):
            orchestrator = Server("Orchestrator\ngpt-5.3-chat-latest")
            with Cluster("Sub-Agents"):
                collector = Server("Collector\ngpt-5.3-chat-latest")
                assessor = Server("Assessor\ngpt-5.3-chat-latest")
                nist_reviewer = Server("NIST Reviewer\ngpt-5.3-chat-latest")
                reporter = Server("Reporter\ngpt-5.3-chat-latest")
                security_reviewer = Server("Security Reviewer\ngpt-5.3-chat-latest")
                sfdc_expert = Server("SFDC Expert\ngpt-5.3-chat-latest")
                wd_expert = Server("Workday Expert\ngpt-5.3-chat-latest")

        # ── Skill CLIs ───────────────────────────────────────────────────────
        with Cluster("Skill CLIs  (Python)"):
            sfdc_connect = Python("sfdc-connect")
            wd_connect = Python("workday-connect")
            oscal_assess = Python("oscal-assess")
            gap_map = Python("oscal_gap_map.py")
            sscf_bench = Python("sscf-benchmark")
            nist_skill = Python("nist-review")
            report_gen = Python("report-gen")

        # ── Generated Artifacts ──────────────────────────────────────────────
        with Cluster("Generated Artifacts"):
            raw_sfdc = Storage("sfdc_raw.json")
            raw_wd = Storage("workday_raw.json")
            gap_json = Storage("gap_analysis.json")
            backlog_json = Storage("backlog.json")
            sscf_json = Storage("sscf_report.json")
            nist_json = Storage("nist_review.json")

        # ── Governance Deliverables ───────────────────────────────────────────
        with Cluster("Governance Deliverables"):
            app_owner = Document("App Owner\nReport (.md)")
            sec_review = MultipleDocuments("Security Team\nGovernance Review\n(.md + .docx)")

        # ── OSCAL config feeds component definitions ──────────────────────────
        catalog >> Edge(style="dotted", color="navy") >> sfdc_profile
        catalog >> Edge(style="dotted", color="navy") >> wd_profile
        sfdc_profile >> Edge(style="dotted", color="navy") >> sfdc_comp
        wd_profile >> Edge(style="dotted", color="navy") >> wd_comp

        # ── Data pipeline (solid arrows) ─────────────────────────────────────
        sfdc >> sfdc_connect >> raw_sfdc
        workday >> wd_connect >> raw_wd
        raw_sfdc >> oscal_assess
        raw_wd >> oscal_assess
        sfdc_comp >> Edge(style="dotted", color="orange") >> sfdc_connect
        wd_comp >> Edge(style="dotted", color="orange") >> wd_connect
        oscal_assess >> gap_json >> gap_map >> backlog_json
        backlog_json >> sscf_bench >> sscf_json
        sscf_json >> nist_skill >> nist_json
        nist_json >> report_gen
        backlog_json >> report_gen
        report_gen >> app_owner
        report_gen >> sec_review

        # ── Agent orchestration (dashed blue arrows) ──────────────────────────
        dashed = Edge(style="dashed", color="steelblue")
        orchestrator >> dashed >> collector
        orchestrator >> dashed >> assessor
        orchestrator >> dashed >> nist_reviewer
        orchestrator >> dashed >> reporter
        orchestrator >> dashed >> security_reviewer
        orchestrator >> dashed >> sfdc_expert
        orchestrator >> dashed >> wd_expert

        gray = Edge(style="dashed", color="gray")
        collector >> gray >> sfdc_connect
        collector >> gray >> wd_connect
        assessor >> gray >> oscal_assess
        assessor >> gray >> gap_map
        assessor >> gray >> sscf_bench
        nist_reviewer >> gray >> nist_skill
        reporter >> gray >> report_gen

    print(f"diagram written → {_OUT}.png")


if __name__ == "__main__":
    main()
