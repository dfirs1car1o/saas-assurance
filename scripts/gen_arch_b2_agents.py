#!/usr/bin/env python3
"""
gen_arch_b2_agents.py  —  Architecture (2/3): Agent Architecture (diagrams lib)

Focuses on the agent layer: orchestrator routing, sub-agent roles, STRICT_AGENTS,
and the full OWASP security harness. Complements arch-a2-agents.png.

Output: docs/arch-b2-agents.png
"""

from __future__ import annotations

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.generic.network import Firewall
from diagrams.generic.storage import Storage
from diagrams.onprem.client import Users
from diagrams.onprem.compute import Server
from diagrams.onprem.database import Cassandra

_OUT = str(Path(__file__).resolve().parents[1] / "docs" / "arch-b2-agents")

_GRAPH = {
    "fontsize": "12",
    "bgcolor": "#FAFAFA",
    "pad": "0.8",
    "splines": "ortho",
    "nodesep": "0.6",
    "ranksep": "1.0",
    "label": (
        "saas-assurance — Reference Architecture (2/3): Agent Architecture\n"
        "10 agents  ·  gpt-5.3-chat-latest  ·  14-turn ReAct  ·  STRICT_AGENTS fail-closed  "
        "·  OWASP Agentic App Top 10"
    ),
    "labelloc": "t",
    "labelfontsize": "13",
}
_NODE = {"fontsize": "11"}


def main() -> None:
    with Diagram(
        "saas-assurance Agent Architecture",
        filename=_OUT,
        show=False,
        graph_attr=_GRAPH,
        node_attr=_NODE,
        direction="TB",
    ):
        human = Users("Human / CI\nagent-loop run")

        # ── Security Harness ──────────────────────────────────────────────────
        with Cluster("Security Harness  (harness/loop.py · harness/tools.py)"):
            seq_gate = Firewall("_TOOL_REQUIRES\nSequencing Gate  (A2)")
            mem_guard = Firewall("Memory Guard\nInjection Strip  (A1/A3)")
            path_val = Firewall("_sanitize_org\n_safe_inp_path  (A5)")
            audit_log = Storage("audit.jsonl\nper run  (A9)")
            allowlist = Firewall("Tool Allowlist\ndispatch()  (A7)")

        # ── Memory Layer ──────────────────────────────────────────────────────
        with Cluster("Session Memory  (Mem0 + Qdrant)"):
            qdrant = Cassandra("org alias · prior score\ncritical findings\nQDRANT_IN_MEMORY=1")

        # ── Agent Layer ───────────────────────────────────────────────────────
        with Cluster("Agent Layer  (OpenAI API · gpt-5.3-chat-latest)"):
            orchestrator = Server("Orchestrator\n14-turn ReAct · finish() trigger\nall CLI tools")

            # Pipeline agents (dispatched in sequence)
            with Cluster("Pipeline Agents  (dispatched by sequencing gate)"):
                collector = Server("Collector  [STRICT]\nsfdc-connect · workday-connect")
                assessor = Server("Assessor  [STRICT]\noscal-assess · gap_map · sscf-benchmark")
                nist_rev = Server("NIST Reviewer\nnist-review · pass/flag/block")
                reporter = Server("Reporter\nreport-gen · MD + DOCX + AICM")

            # Gate agents (quality control, fail-closed)
            with Cluster("Gate Agents  (fail-closed schema validation)"):
                del_rev = Server("Delivery Reviewer  [STRICT]\ncredential exposure · status check")

            # On-demand agents (not pipeline dispatched)
            with Cluster("On-Demand Agents"):
                sec_rev = Server("Security Reviewer\nAppSec + DevSecOps CI")
                sfdc_exp = Server("SFDC Expert  [STRICT]\nApex + SOQL specialist")
                wd_exp = Server("Workday Expert  [STRICT]\nRaaS + REST specialist")
                ctr_exp = Server("Container Expert\nDocker + OpenSearch")

        # ── Connections ───────────────────────────────────────────────────────
        dashed = Edge(style="dashed", color="steelblue")
        orange = Edge(style="dashed", color="orange")

        human >> orchestrator

        # Harness gates around orchestrator
        seq_gate >> orange >> orchestrator
        mem_guard >> orange >> orchestrator
        path_val >> orange >> orchestrator
        audit_log >> orange >> orchestrator
        allowlist >> orange >> orchestrator

        # Memory
        qdrant >> Edge(style="dotted", color="purple") >> orchestrator

        # Orchestrator → pipeline agents
        orchestrator >> dashed >> collector
        orchestrator >> dashed >> assessor
        orchestrator >> dashed >> nist_rev
        orchestrator >> dashed >> reporter
        orchestrator >> dashed >> del_rev

        # Orchestrator → on-demand
        orchestrator >> Edge(style="dashed", color="gray") >> sec_rev
        orchestrator >> Edge(style="dashed", color="gray") >> sfdc_exp
        orchestrator >> Edge(style="dashed", color="gray") >> wd_exp
        orchestrator >> Edge(style="dashed", color="gray") >> ctr_exp

    print(f"diagram written → {_OUT}.png")


if __name__ == "__main__":
    main()
