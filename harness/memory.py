"""
harness/memory.py — Mem0 + Qdrant session memory for cross-org, cross-session comparison.

Usage:
    client = build_client()
    context = load_memories(client, "prod-org-alias")
    # ... run assessment ...
    save_assessment(client, "prod-org-alias", "assess-20260301", 0.51, ["SBS-AUTH-001"])

Environment:
    QDRANT_IN_MEMORY=1  — use in-memory Qdrant (no Docker needed; for CI / tests)
    QDRANT_HOST         — override Qdrant host (default: localhost)
    QDRANT_PORT         — override Qdrant port (default: 6333)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    pass

COLLECTION = "saas-posture"
_MEMORY_LIMIT = 5  # max prior assessment summaries to surface per org


def build_client() -> Any:
    """Construct a Mem0 Memory client backed by Qdrant.

    Uses in-memory Qdrant when QDRANT_IN_MEMORY=1 (CI / local dev without Docker).
    Raises RuntimeError (caught by caller) when MEMORY_ENABLED=0 or deps missing.
    """
    if os.getenv("MEMORY_ENABLED", "0") != "1":
        raise RuntimeError("memory disabled (set MEMORY_ENABLED=1 and install sentence-transformers to enable)")

    try:
        from mem0 import Memory  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("mem0ai is not installed. Run: pip install mem0ai qdrant-client") from exc

    in_memory = os.getenv("QDRANT_IN_MEMORY", "0") == "1"

    if in_memory:
        vector_config: dict[str, Any] = {
            "provider": "qdrant",
            "config": {
                "collection_name": COLLECTION,
                "path": ":memory:",
            },
        }
    else:
        vector_config = {
            "provider": "qdrant",
            "config": {
                "collection_name": COLLECTION,
                "host": os.getenv("QDRANT_HOST", "localhost"),
                "port": int(os.getenv("QDRANT_PORT", "6333")),
            },
        }

    config: dict[str, Any] = {"vector_store": vector_config}

    # If no OpenAI key is available, tell Mem0 to use a lightweight local embedder
    # (sentence-transformers via huggingface) instead of the OpenAI default.
    # If that's also unavailable, build_client() will raise and the caller's
    # try/except will degrade memory gracefully.
    if not os.getenv("OPENAI_API_KEY"):
        config["embedder"] = {
            "provider": "huggingface",
            "config": {"model": "multi-qa-MiniLM-L6-cos-v1"},
        }

    return Memory.from_config(config)


def load_memories(client: Any, org_alias: str) -> str:
    """Return formatted string of recent assessment summaries for this org.

    Returns a human-readable string prepended to the orchestrator's first user
    message so it can compare the current run against historical baselines.
    """
    try:
        results = client.search(
            f"assessment results for {org_alias}",
            user_id=org_alias,
            limit=_MEMORY_LIMIT,
        )
        if not results:
            return f"No prior assessments found in memory for org '{org_alias}'."
        lines = []
        for r in results:
            # mem0 returns dicts with a 'memory' key containing the stored text
            text = r.get("memory") or r.get("text") or str(r)
            lines.append(f"  - {text}")
        return f"Prior assessment memory for org '{org_alias}':\n" + "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"[Memory unavailable for org '{org_alias}': {exc}]"


def save_assessment(
    client: Any,
    org_alias: str,
    assessment_id: str,
    score: float,
    critical_fails: list[str],
) -> None:
    """Persist key assessment metrics for future cross-session comparison.

    Stores a compact summary string so future runs can detect drift:
    'score was 34%, now 51%' or 'SBS-AUTH-001 was critical-fail, now partial'.
    """
    summary = (
        f"Assessment {assessment_id} for org '{org_alias}': "
        f"overall_score={score:.1%}, "
        f"critical_fails={len(critical_fails)}" + (f": {', '.join(critical_fails[:5])}" if critical_fails else "")
    )
    try:
        client.add(
            summary,
            user_id=org_alias,
            metadata={"assessment_id": assessment_id, "score": round(score, 4)},
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(f"WARNING: Could not save assessment to memory: {exc}", err=True)
