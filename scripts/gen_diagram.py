#!/usr/bin/env python3
"""
gen_diagram.py — Generate reference architecture diagram for saas-assurance.

Outputs: docs/architecture.png  (via graphviz / diagrams library)

Shows the multi-agent OpenAI layer orchestrating Python CLI skills across the
full 7-phase assessment pipeline for both Salesforce and Workday platforms,
with the security controls harness (OWASP Agentic App Top 10 hardening).

    [Salesforce] sfdc-connect → oscal-assess → gap_map → sscf-benchmark
                 → nist-review → gen_aicm_crosswalk → report-gen
    [Workday]    workday-connect → oscal-assess → gap_map → sscf-benchmark
                 → nist-review → gen_aicm_crosswalk → report-gen

Security harness: _TOOL_REQUIRES sequencing gate · memory guard ·
                  audit.jsonl · input path validation · shell=False

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
from diagrams.generic.network import Firewall
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
    "label": "saas-assurance — Reference Architecture\nRead-only · OWASP Agentic App hardened · 7-phase",
    "labelloc": "t",
    "labelfontsize": "13",
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
            with Cluster("Salesforce Org"):
                sfdc = Firewall("JWT Bearer Flow\nConnected App")
                sfdc_apis = Firewall("Tooling API\nREST API · Metadata API")
            with Cluster("Workday Tenant  (HCM / Finance)"):
                workday = Server("OAuth 2.0\nClient Credentials")
                wd_apis = Firewall("RaaS (custom reports)\nREST API · Manual questionnaire")

        # ── OSCAL Config Layer ────────────────────────────────────────────────
        with Cluster("OSCAL Config  (config/)"):
            catalog = Storage("SSCF v1.0 Catalog\n36 controls · 6 domains")
            sfdc_profile = Storage("SBS Profile\n35 controls")
            wd_profile = Storage("WSCC Profile\n30 controls")
            aicm_config = Storage("AICM v1.0.3\n243 controls · 18 domains")

        # ── Security Harness ─────────────────────────────────────────────────
        with Cluster("Security Harness  (harness/loop.py · harness/tools.py)"):
            seq_gate = Server("_TOOL_REQUIRES\nSequencing Gate\n(OWASP A2)")
            mem_guard = Server("Memory Guard\nInjection Patterns\n(OWASP A1/A3)")
            audit_log = Storage("audit.jsonl\nper run\n(OWASP A9)")
            path_val = Server("Input Path Validation\n_sanitize_org\n_safe_inp_path (OWASP A5)")

        # ── Agent Layer ──────────────────────────────────────────────────────
        with Cluster("Agent Layer  (OpenAI API · gpt-5.3-chat-latest)"):
            orchestrator = Server("Orchestrator\n14-turn ReAct loop")
            with Cluster("Sub-Agents"):
                collector = Server("Collector")
                assessor = Server("Assessor")
                nist_reviewer = Server("NIST Reviewer\nAI RMF gate")
                reporter = Server("Reporter")
                security_reviewer = Server("Security Reviewer\nDevSecOps CI")
                sfdc_expert = Server("SFDC Expert\non-call")
                wd_expert = Server("Workday Expert\non-call")

        # ── Skill CLIs ───────────────────────────────────────────────────────
        with Cluster("Skill CLIs  (Python · shell=False · read-only)"):
            sfdc_connect = Python("sfdc-connect")
            wd_connect = Python("workday-connect")
            oscal_assess = Python("oscal-assess")
            gap_map = Python("oscal_gap_map.py")
            sscf_bench = Python("sscf-benchmark")
            nist_skill = Python("nist-review")
            aicm_skill = Python("gen_aicm_crosswalk.py")
            report_gen = Python("report-gen")

        # ── Generated Artifacts ──────────────────────────────────────────────
        with Cluster("Generated Artifacts  (docs/oscal-salesforce-poc/generated/)"):
            raw_sfdc = Storage("sfdc_raw.json")
            raw_wd = Storage("workday_raw.json")
            gap_json = Storage("gap_analysis.json")
            backlog_json = Storage("backlog.json")
            sscf_json = Storage("sscf_report.json")
            nist_json = Storage("nist_review.json")
            aicm_json = Storage("aicm_coverage.json")
            oscal_artifacts = MultipleDocuments("poam.json · ssp.json\nassessment_results.json")

        # ── Governance Deliverables ───────────────────────────────────────────
        with Cluster("Governance Deliverables"):
            app_owner = Document("App Owner\nReport (.md)")
            sec_review = MultipleDocuments("Security Governance\n(.md + .docx)\n+ AICM annex")

        # ── OSCAL config chain ────────────────────────────────────────────────
        catalog >> Edge(style="dotted", color="navy") >> sfdc_profile
        catalog >> Edge(style="dotted", color="navy") >> wd_profile
        aicm_config >> Edge(style="dotted", color="purple") >> aicm_skill

        # ── Data pipeline (solid arrows) ─────────────────────────────────────
        sfdc >> sfdc_apis
        sfdc_apis >> Edge(color="darkgreen") >> sfdc_connect >> raw_sfdc
        workday >> wd_apis
        wd_apis >> Edge(color="darkgreen") >> wd_connect >> raw_wd
        raw_sfdc >> oscal_assess
        raw_wd >> oscal_assess
        oscal_assess >> gap_json >> gap_map >> backlog_json
        backlog_json >> sscf_bench >> sscf_json
        sscf_json >> nist_skill >> nist_json
        backlog_json >> aicm_skill >> aicm_json
        nist_json >> report_gen
        backlog_json >> report_gen
        aicm_json >> report_gen
        backlog_json >> oscal_artifacts
        report_gen >> app_owner
        report_gen >> sec_review

        # ── Security harness gates ────────────────────────────────────────────
        sec_edge = Edge(style="dashed", color="orange")
        seq_gate >> sec_edge >> orchestrator
        mem_guard >> sec_edge >> orchestrator
        audit_log >> sec_edge >> orchestrator
        path_val >> sec_edge >> orchestrator

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
        assessor >> gray >> aicm_skill

    print(f"diagram written → {_OUT}.png")


if __name__ == "__main__":
    main()
