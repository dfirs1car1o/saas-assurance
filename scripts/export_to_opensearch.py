#!/usr/bin/env python3
"""
export_to_opensearch.py — index assessment artifacts into OpenSearch.

Reads backlog.json + sscf_report.json + nist_review.json from a completed
assessment run and writes two document types:

  sscf-runs-<YYYY-MM>     — one doc per assessment run (scores, NIST verdict, domain summary)
  sscf-findings-<YYYY-MM> — one doc per finding per run (control-level time-series)

Usage:
    python scripts/export_to_opensearch.py --backlog <path> --sscf <path> [--nist <path>]
    python scripts/export_to_opensearch.py --auto --org acme-workday --date 2026-03-06

Environment:
    OPENSEARCH_URL  — default http://localhost:9200
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_GENERATED = _REPO / "docs" / "oscal-salesforce-poc" / "generated"

_DEFAULT_URL = "http://localhost:9200"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text())


def _opensearch_client(url: str):
    try:
        from opensearchpy import OpenSearch
    except ImportError:
        print("ERROR: opensearch-py not installed. Run: pip install opensearch-py", file=sys.stderr)
        sys.exit(1)
    return OpenSearch([url], http_compress=True, use_ssl=False, verify_certs=False)


def _index_suffix(ts: str) -> str:
    """Return YYYY-MM index suffix from ISO timestamp."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m")
    except Exception:
        return datetime.now(UTC).strftime("%Y-%m")


def _build_run_doc(
    backlog: dict[str, Any],
    sscf: dict[str, Any] | None,
    nist: dict[str, Any] | None,
) -> dict[str, Any]:
    """One document per assessment run — goes into sscf-runs-* index."""
    items = backlog.get("mapped_items", [])
    counts = {
        "pass": sum(1 for i in items if i.get("status") == "pass"),
        "fail": sum(1 for i in items if i.get("status") == "fail"),
        "partial": sum(1 for i in items if i.get("status") == "partial"),
        "not_applicable": sum(1 for i in items if i.get("status") == "not_applicable"),
    }

    domains = []
    if sscf:
        for d in sscf.get("domains", []):
            domains.append(
                {
                    "domain": d.get("domain", ""),
                    "score": d.get("score"),
                    "status": d.get("status", "not_assessed"),
                }
            )

    nist_verdict = "unknown"
    if nist:
        review = nist.get("nist_ai_rmf_review", nist)
        nist_verdict = review.get("overall", "unknown")

    # Prefer explicit fields; fall back to control-ID prefix heuristic
    assessment_id = backlog.get("assessment_id", "unknown")
    org = backlog.get("org") or backlog.get("assessment_owner", "").split("-")[0] or "unknown"
    items = backlog.get("mapped_items", [])
    platform = backlog.get("platform") or (
        "workday" if any(i.get("sbs_control_id", "").startswith("WD-") for i in items) else "salesforce"
    )

    return {
        "assessment_id": assessment_id,
        "org": org,
        "platform": platform,
        "generated_at_utc": backlog.get("generated_at_utc", datetime.now(UTC).isoformat()),
        "assessment_owner": backlog.get("assessment_owner", ""),
        "overall_score": sscf.get("overall_score") if sscf else None,
        "overall_status": sscf.get("overall_status", "unknown") if sscf else "unknown",
        "nist_verdict": nist_verdict,
        "counts": counts,
        "domains": domains,
        "catalog_version": backlog.get("catalog_version"),
        "mapped_findings": backlog.get("summary", {}).get("mapped_findings", len(items)),
        "unmapped_findings": backlog.get("summary", {}).get("unmapped_findings", 0),
    }


def _build_finding_docs(backlog: dict[str, Any]) -> list[dict[str, Any]]:
    """One document per finding — goes into sscf-findings-* index."""
    ts = backlog.get("generated_at_utc", datetime.now(UTC).isoformat())
    assessment_id = backlog.get("assessment_id", "unknown")

    # Use explicit platform field from backlog; fall back to control-ID prefix heuristic
    items = backlog.get("mapped_items", [])
    platform = backlog.get("platform") or (
        "workday" if any(i.get("sbs_control_id", "").startswith("WD-") for i in items) else "salesforce"
    )

    # Use explicit org field; fall back to assessment_id second segment
    org = backlog.get("org") or (assessment_id.split("-")[1] if len(assessment_id.split("-")) > 1 else "unknown")

    docs = []
    for item in items:
        status = item.get("status", "")
        if status == "pass":
            poam_status = "Closed"
        elif status == "fail":
            poam_status = "Open"
        else:
            poam_status = "In Progress"
        if status == "not_applicable":
            poam_status = "N/A"

        docs.append(
            {
                "assessment_id": assessment_id,
                "org": org,
                "platform": platform,
                "generated_at_utc": ts,
                "control_id": item.get("sbs_control_id", item.get("legacy_control_id", "?")),
                "sbs_title": item.get("sbs_title", ""),
                "domain": (item.get("sscf_mappings") or [{}])[0].get("sscf_domain", ""),
                "severity": item.get("severity", ""),
                "status": status,
                "owner": item.get("owner", ""),
                "due_date": item.get("due_date") or None,
                "poam_status": poam_status,
                "mapping_confidence": item.get("mapping_confidence", ""),
                "remediation": item.get("remediation", ""),
            }
        )
    return docs


def export(
    backlog_path: Path,
    sscf_path: Path | None,
    nist_path: Path | None,
    opensearch_url: str,
    org_override: str | None = None,
) -> None:
    backlog = _load_json(backlog_path)
    if org_override:
        backlog.setdefault("org", org_override)
    sscf = _load_json(sscf_path) if sscf_path else None
    nist = _load_json(nist_path) if nist_path else None

    client = _opensearch_client(opensearch_url)

    # ── Run summary doc ───────────────────────────────────────────────────────
    run_doc = _build_run_doc(backlog, sscf, nist)
    ts = run_doc["generated_at_utc"]
    suffix = _index_suffix(ts)
    runs_index = f"sscf-runs-{suffix}"
    findings_index = f"sscf-findings-{suffix}"

    resp = client.index(index=runs_index, body=run_doc, id=run_doc["assessment_id"])
    print(f"[opensearch] run doc → {runs_index} ({resp['result']})")

    # ── Per-finding docs (bulk) ───────────────────────────────────────────────
    finding_docs = _build_finding_docs(backlog)
    if finding_docs:
        bulk_body = []
        for i, doc in enumerate(finding_docs):
            doc_id = f"{run_doc['assessment_id']}-{i:04d}"
            bulk_body.append({"index": {"_index": findings_index, "_id": doc_id}})
            bulk_body.append(doc)
        resp = client.bulk(body=bulk_body)
        errors = [item for item in resp["items"] if "error" in item.get("index", {})]
        print(f"[opensearch] {len(finding_docs)} findings → {findings_index} ({len(errors)} errors)")
        if errors:
            for e in errors[:3]:
                print(f"  error: {e['index']['error']}", file=sys.stderr)


def _resolve_auto(org: str, date: str) -> tuple[Path, Path | None, Path | None]:
    """Auto-discover artifact paths for an org + date."""
    base = _GENERATED / org / date
    if not base.exists():
        print(f"ERROR: generated dir not found: {base}", file=sys.stderr)
        sys.exit(1)

    # Find backlog (may be named workday_backlog.json or backlog.json)
    for name in ["workday_backlog.json", "backlog.json", f"{org}_backlog.json"]:
        if (base / name).exists():
            backlog = base / name
            break
    else:
        print(f"ERROR: no backlog.json found in {base}", file=sys.stderr)
        sys.exit(1)

    sscf = next((base / n for n in ["workday_sscf_report.json", "sscf_report.json"] if (base / n).exists()), None)
    nist = next((base / n for n in ["workday_nist_review.json", "nist_review.json"] if (base / n).exists()), None)
    return backlog, sscf, nist


def main() -> int:
    parser = argparse.ArgumentParser(description="Export assessment artifacts to OpenSearch.")
    parser.add_argument("--backlog", help="Path to backlog.json")
    parser.add_argument("--sscf", help="Path to sscf_report.json (optional)")
    parser.add_argument("--nist", help="Path to nist_review.json (optional)")
    parser.add_argument("--auto", action="store_true", help="Auto-discover artifacts for --org + --date")
    parser.add_argument("--org", help="Org alias (used with --auto)")
    parser.add_argument("--date", default=None, help="Date dir YYYY-MM-DD (used with --auto, default: today)")
    parser.add_argument(
        "--opensearch-url",
        default=None,
        help="OpenSearch URL (default: OPENSEARCH_URL env or http://localhost:9200)",
    )
    args = parser.parse_args()

    import os

    url = args.opensearch_url or os.getenv("OPENSEARCH_URL", _DEFAULT_URL)

    if args.auto:
        if not args.org:
            print("ERROR: --auto requires --org", file=sys.stderr)
            return 1
        date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
        backlog, sscf, nist = _resolve_auto(args.org, date)
    else:
        if not args.backlog:
            print("ERROR: --backlog is required (or use --auto --org)", file=sys.stderr)
            return 1
        backlog = (_REPO / args.backlog).resolve()
        sscf = (_REPO / args.sscf).resolve() if args.sscf else None
        nist = (_REPO / args.nist).resolve() if args.nist else None

    export(backlog, sscf, nist, url, org_override=args.org)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
