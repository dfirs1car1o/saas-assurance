"""
harness/agents.py — Agent configuration registry.

Each AgentConfig loads its system prompt from mission.md (identity + scope rules)
followed by the agent-specific role file from agents/<name>.md.
Mission always loads first — it takes precedence over role definitions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

DEFAULT_MODEL = "gpt-5.3-chat-latest"


def _load(agent_name: str) -> str:
    """Concatenate mission.md + agents/<name>.md into a single system prompt."""
    mission = (_REPO / "mission.md").read_text()
    agent_file = _REPO / "agents" / f"{agent_name}.md"
    agent_text = agent_file.read_text() if agent_file.exists() else ""
    return f"{mission}\n\n---\n\n{agent_text}".strip()


@dataclass
class AgentConfig:
    name: str
    model: str
    system_prompt: str
    tool_names: list[str] = field(default_factory=list)


_MODEL_ORCHESTRATOR = os.getenv("LLM_MODEL_ORCHESTRATOR", DEFAULT_MODEL)
_MODEL_ANALYST = os.getenv("LLM_MODEL_ANALYST", DEFAULT_MODEL)
_MODEL_REPORTER = os.getenv("LLM_MODEL_REPORTER", DEFAULT_MODEL)

# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------

ORCHESTRATOR = AgentConfig(
    name="orchestrator",
    model=_MODEL_ORCHESTRATOR,
    system_prompt=_load("orchestrator"),
    tool_names=[
        "sfdc_connect_collect",
        "oscal_assess_assess",
        "oscal_gap_map",
        "sscf_benchmark_benchmark",
        "report_gen_generate",
    ],
)

REPORTER = AgentConfig(
    name="reporter",
    model=_MODEL_REPORTER,
    system_prompt=_load("reporter"),
    tool_names=[],
)

# Security reviewer: AppSec + DevSecOps expert. Text analysis only — no tool calls.
# Invoked by the orchestrator when CI/CD, workflow, or skill changes are reviewed.
SECURITY_REVIEWER = AgentConfig(
    name="security-reviewer",
    model=_MODEL_ANALYST,
    system_prompt=_load("security-reviewer"),
    tool_names=[],
)
