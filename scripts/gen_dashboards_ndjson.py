#!/usr/bin/env python3
"""
gen_dashboards_ndjson.py — Generate config/opensearch/dashboards.ndjson

Produces platform-filtered OpenSearch saved objects for:
  - Salesforce Security Posture   (platform:salesforce — all charts filtered)
  - Workday Security Posture      (platform:workday — all charts filtered)
  - SSCF Security Posture Overview (combined, split by platform)

New in this version:
  - Every platform-specific viz carries a KQL platform filter
  - Pass / Fail / Critical count metric tiles per dashboard
  - Owner accountability horizontal bar
  - Domain × Status stacked bar (fail/partial only)
  - Severity × Status stacked bar
  - Platform score trend line (combined dashboard)
  - Donut status pie (replaces flat pie)
  - All searches pre-filtered by platform

Usage:
    python3 scripts/gen_dashboards_ndjson.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_OUT = Path(__file__).resolve().parents[1] / "config" / "opensearch" / "dashboards.ndjson"

# ── Duplicate-string constants (S1192) ────────────────────────────────────────
_FINDINGS_INDEX = "sscf-findings-*"
_RUNS_INDEX = "sscf-runs-*"
_FAIL_PARTIAL_QUERY = "status : fail OR status : partial"
_OPEN_ITEMS_LABEL = "Open Items"
_SFDC_FILTER = "platform : salesforce"
_SBS_TITLE_KW = "sbs_title.keyword"
_SFDC_FAIL_PARTIAL = "platform : salesforce AND (status : fail OR status : partial)"
_WD_FILTER = "platform : workday"
_WD_FAIL_PARTIAL = "platform : workday AND (status : fail OR status : partial)"
_KIBANA_INDEX_KEY = "kibanaSavedObjectMeta.searchSourceJSON.index"


def _j(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _src(query: str = "", _index_id: str = _FINDINGS_INDEX) -> str:
    return _j(
        {
            "query": {"language": "kuery", "query": query},
            "filter": [],
            "indexRefName": _KIBANA_INDEX_KEY,
        }
    )


def _viz(
    id_: str, title: str, vis_state: dict, query: str = "", index_id: str = _FINDINGS_INDEX, desc: str = ""
) -> dict:
    vis_state["title"] = title
    return {
        "type": "visualization",
        "id": id_,
        "attributes": {
            "title": title,
            "visState": _j(vis_state),
            "uiStateJSON": "{}",
            "description": desc,
            "version": 1,
            "kibanaSavedObjectMeta": {"searchSourceJSON": _src(query, index_id)},
        },
        "references": [{"name": _KIBANA_INDEX_KEY, "type": "index-pattern", "id": index_id}],
    }


# ── Primitive viz builders ────────────────────────────────────────────────────


def index_pattern(id_: str, title: str, time_field: str) -> dict:
    return {
        "type": "index-pattern",
        "id": id_,
        "attributes": {"title": title, "timeFieldName": time_field},
        "references": [],
    }


def score_tile(id_: str, title: str, subtext: str, platform: str) -> dict:
    """RED/AMBER/GREEN score tile sourced from sscf-runs-*."""
    return _viz(
        id_,
        title,
        {
            "type": "metric",
            "params": {
                "addTooltip": True,
                "addLegend": False,
                "type": "metric",
                "metric": {
                    "percentageMode": False,
                    "useRanges": True,
                    "colorSchema": "Green to Red",
                    "metricColorMode": "Background",
                    "colorsRange": [{"from": 0, "to": 0.5}, {"from": 0.5, "to": 0.75}, {"from": 0.75, "to": 1.0}],
                    "labels": {"show": True},
                    "invertColors": True,
                    "style": {
                        "bgFill": "#000",
                        "bgColor": True,
                        "labelColor": False,
                        "subText": subtext,
                        "fontSize": 48,
                    },
                },
            },
            "aggs": [
                {"id": "1", "enabled": True, "type": "avg", "schema": "metric", "params": {"field": "overall_score"}}
            ],
        },
        query=f"platform : {platform}",
        index_id=_RUNS_INDEX,
        desc=f"Latest average overall score for {platform}",
    )


def count_tile(id_: str, title: str, subtext: str, query: str) -> dict:
    """Plain count metric tile."""
    return _viz(
        id_,
        title,
        {
            "type": "metric",
            "params": {
                "addTooltip": True,
                "addLegend": False,
                "type": "metric",
                "metric": {
                    "percentageMode": False,
                    "useRanges": False,
                    "colorSchema": "Green to Red",
                    "metricColorMode": "None",
                    "colorsRange": [{"from": 0, "to": 10000}],
                    "labels": {"show": True},
                    "invertColors": False,
                    "style": {
                        "bgFill": "#000",
                        "bgColor": False,
                        "labelColor": False,
                        "subText": subtext,
                        "fontSize": 48,
                    },
                },
            },
            "aggs": [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}}],
        },
        query=query,
    )


def donut_pie(
    id_: str, title: str, field: str, query: str = "", index_id: str = _FINDINGS_INDEX, desc: str = ""
) -> dict:
    return _viz(
        id_,
        title,
        {
            "type": "pie",
            "params": {
                "type": "pie",
                "addTooltip": True,
                "addLegend": True,
                "legendPosition": "right",
                "isDonut": True,
                "labels": {"show": True, "values": True, "last_level": True, "truncate": 100},
            },
            "aggs": [
                {"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
                {
                    "id": "2",
                    "enabled": True,
                    "type": "terms",
                    "schema": "segment",
                    "params": {
                        "field": field,
                        "size": 10,
                        "order": "desc",
                        "orderBy": "1",
                        "otherBucket": False,
                        "missingBucket": False,
                    },
                },
            ],
        },
        query=query,
        index_id=index_id,
        desc=desc,
    )


def hbar(
    id_: str,
    title: str,
    term_field: str,
    query: str = "",
    split_field: str | None = None,
    index_id: str = _FINDINGS_INDEX,
    desc: str = "",
) -> dict:
    """Horizontal bar (terms on Y-axis) — good for long control names."""
    aggs: list[dict] = [
        {"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
        {
            "id": "2",
            "enabled": True,
            "type": "terms",
            "schema": "segment",
            "params": {
                "field": term_field,
                "size": 10,
                "order": "desc",
                "orderBy": "1",
                "otherBucket": False,
                "missingBucket": False,
                "customLabel": "Control",
            },
        },
    ]
    if split_field:
        aggs.append(
            {
                "id": "3",
                "enabled": True,
                "type": "terms",
                "schema": "group",
                "params": {
                    "field": split_field,
                    "size": 5,
                    "order": "desc",
                    "orderBy": "1",
                    "otherBucket": False,
                    "missingBucket": False,
                    "customLabel": split_field.split(".")[0].title(),
                },
            }
        )
    return _viz(
        id_,
        title,
        {
            "type": "histogram",
            "params": {
                "type": "histogram",
                "grid": {"categoryLines": False},
                "categoryAxes": [
                    {
                        "id": "CategoryAxis-1",
                        "type": "category",
                        "position": "left",
                        "show": True,
                        "style": {},
                        "scale": {"type": "linear"},
                        "labels": {"show": True, "filter": False, "truncate": 250},
                        "title": {},
                    }
                ],
                "valueAxes": [
                    {
                        "id": "ValueAxis-1",
                        "name": "BottomAxis-1",
                        "type": "value",
                        "position": "bottom",
                        "show": True,
                        "style": {},
                        "scale": {"type": "linear", "mode": "normal"},
                        "labels": {"show": True, "rotate": 0, "filter": False, "truncate": 100},
                        "title": {"text": "Count"},
                    }
                ],
                "seriesParams": [
                    {
                        "show": True,
                        "type": "histogram",
                        "mode": "stacked",
                        "data": {"label": "Count", "id": "1"},
                        "valueAxis": "ValueAxis-1",
                        "drawLinesBetweenPoints": True,
                        "lineWidth": 2,
                        "showCircles": True,
                    }
                ],
                "addTooltip": True,
                "addLegend": True,
                "legendPosition": "right",
                "times": [],
                "addTimeMarker": False,
            },
            "aggs": aggs,
        },
        query=query,
        index_id=index_id,
        desc=desc,
    )


def vbar(
    id_: str,
    title: str,
    term_field: str,
    query: str = "",
    split_field: str | None = None,
    index_id: str = _FINDINGS_INDEX,
    desc: str = "",
) -> dict:
    """Vertical bar — good for domain/severity breakdowns."""
    aggs: list[dict] = [
        {"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
        {
            "id": "2",
            "enabled": True,
            "type": "terms",
            "schema": "segment",
            "params": {
                "field": term_field,
                "size": 10,
                "order": "desc",
                "orderBy": "1",
                "otherBucket": False,
                "missingBucket": False,
            },
        },
    ]
    if split_field:
        aggs.append(
            {
                "id": "3",
                "enabled": True,
                "type": "terms",
                "schema": "group",
                "params": {
                    "field": split_field,
                    "size": 5,
                    "order": "desc",
                    "orderBy": "1",
                    "otherBucket": False,
                    "missingBucket": False,
                },
            }
        )
    return _viz(
        id_,
        title,
        {
            "type": "histogram",
            "params": {
                "type": "histogram",
                "grid": {"categoryLines": False},
                "categoryAxes": [
                    {
                        "id": "CategoryAxis-1",
                        "type": "category",
                        "position": "bottom",
                        "show": True,
                        "style": {},
                        "scale": {"type": "linear"},
                        "labels": {"show": True, "filter": True, "truncate": 100},
                        "title": {},
                    }
                ],
                "valueAxes": [
                    {
                        "id": "ValueAxis-1",
                        "name": "LeftAxis-1",
                        "type": "value",
                        "position": "left",
                        "show": True,
                        "style": {},
                        "scale": {"type": "linear", "mode": "normal"},
                        "labels": {"show": True, "rotate": 0, "filter": False, "truncate": 100},
                        "title": {"text": "Count"},
                    }
                ],
                "seriesParams": [
                    {
                        "show": True,
                        "type": "histogram",
                        "mode": "stacked",
                        "data": {"label": "Count", "id": "1"},
                        "valueAxis": "ValueAxis-1",
                        "drawLinesBetweenPoints": True,
                        "lineWidth": 2,
                        "showCircles": True,
                    }
                ],
                "addTooltip": True,
                "addLegend": True,
                "legendPosition": "right",
                "times": [],
                "addTimeMarker": False,
            },
            "aggs": aggs,
        },
        query=query,
        index_id=index_id,
        desc=desc,
    )


def line_trend(
    id_: str, title: str, query: str = "", index_id: str = _RUNS_INDEX, split_field: str | None = None
) -> dict:
    """Score trend line chart."""
    aggs: list[dict] = [
        {"id": "1", "enabled": True, "type": "avg", "schema": "metric", "params": {"field": "overall_score"}},
        {
            "id": "2",
            "enabled": True,
            "type": "date_histogram",
            "schema": "segment",
            "params": {
                "field": "generated_at_utc",
                "useNormalizedEsInterval": True,
                "interval": "auto",
                "drop_partials": False,
                "min_doc_count": 1,
                "extended_bounds": {},
            },
        },
    ]
    if split_field:
        aggs.append(
            {
                "id": "3",
                "enabled": True,
                "type": "terms",
                "schema": "group",
                "params": {
                    "field": split_field,
                    "size": 5,
                    "order": "desc",
                    "orderBy": "1",
                    "otherBucket": False,
                    "missingBucket": False,
                    "customLabel": "Platform",
                },
            }
        )
    return _viz(
        id_,
        title,
        {
            "type": "line",
            "params": {
                "type": "line",
                "grid": {"categoryLines": False},
                "categoryAxes": [
                    {
                        "id": "CategoryAxis-1",
                        "type": "category",
                        "position": "bottom",
                        "show": True,
                        "style": {},
                        "scale": {"type": "linear"},
                        "labels": {"show": True, "filter": True, "truncate": 100},
                        "title": {},
                    }
                ],
                "valueAxes": [
                    {
                        "id": "ValueAxis-1",
                        "name": "LeftAxis-1",
                        "type": "value",
                        "position": "left",
                        "show": True,
                        "style": {},
                        "scale": {"type": "linear", "mode": "normal"},
                        "labels": {"show": True, "rotate": 0, "filter": False, "truncate": 100},
                        "title": {"text": "Score (0–1)"},
                    }
                ],
                "seriesParams": [
                    {
                        "show": True,
                        "type": "line",
                        "mode": "normal",
                        "data": {"label": "Avg Score", "id": "1"},
                        "valueAxis": "ValueAxis-1",
                        "drawLinesBetweenPoints": True,
                        "lineWidth": 2,
                        "showCircles": True,
                        "interpolate": "linear",
                    }
                ],
                "addTooltip": True,
                "addLegend": True,
                "legendPosition": "right",
                "times": [],
                "addTimeMarker": False,
            },
            "aggs": aggs,
        },
        query=query,
        index_id=index_id,
    )


def agg_table(
    id_: str,
    title: str,
    buckets: list[tuple[str, str, int]],
    query: str = "",
    index_id: str = _FINDINGS_INDEX,
    desc: str = "",
) -> dict:
    aggs: list[dict] = [
        {"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
    ]
    for i, (field, label, size) in enumerate(buckets, start=2):
        aggs.append(
            {
                "id": str(i),
                "enabled": True,
                "type": "terms",
                "schema": "bucket",
                "params": {
                    "field": field,
                    "size": size,
                    "order": "desc",
                    "orderBy": "1",
                    "otherBucket": False,
                    "missingBucket": False,
                    "customLabel": label,
                },
            }
        )
    return _viz(
        id_,
        title,
        {
            "type": "table",
            "params": {
                "perPage": 10,
                "showPartialRows": False,
                "showMetricsAtAllLevels": False,
                "sort": {"columnIndex": None, "direction": None},
                "showTotal": False,
                "totalFunc": "sum",
                "percentageCol": "",
            },
            "aggs": aggs,
        },
        query=query,
        index_id=index_id,
        desc=desc,
    )


def saved_search(
    id_: str, title: str, columns: list[str], query: str = "", index_id: str = _FINDINGS_INDEX, desc: str = ""
) -> dict:
    return {
        "type": "search",
        "id": id_,
        "attributes": {
            "title": title,
            "description": desc,
            "hits": 0,
            "columns": columns,
            "sort": [["severity", "desc"]],
            "version": 1,
            "kibanaSavedObjectMeta": {"searchSourceJSON": _src(query, index_id)},
        },
        "references": [
            {"name": "kibanaSavedObjectMeta.searchSourceJSON.index", "type": "index-pattern", "id": index_id}
        ],
    }


# ── Panel / Dashboard helpers ─────────────────────────────────────────────────


def panel(idx: int, x: int, y: int, w: int, h: int, obj_id: str, obj_type: str = "visualization") -> dict:
    return {
        "panelIndex": str(idx),
        "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(idx)},
        "id": obj_id,
        "type": obj_type,
        "version": "2.19.0",
    }


def ref(name: str, obj_type: str, obj_id: str) -> dict:
    return {"name": name, "type": obj_type, "id": obj_id}


def dashboard_obj(id_: str, title: str, desc: str, panels: list[dict], refs: list[dict]) -> dict:
    return {
        "type": "dashboard",
        "id": id_,
        "attributes": {
            "title": title,
            "hits": 0,
            "description": desc,
            "panelsJSON": _j(panels),
            "optionsJSON": _j({"useMargins": True, "hidePanelTitles": False}),
            "version": 1,
            "timeRestore": True,
            "timeTo": "now",
            "timeFrom": "now-1y",
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": _j({"query": {"language": "kuery", "query": ""}, "filter": []}),
            },
        },
        "references": refs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# OBJECT DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

DETAIL_COLS = [
    "control_id",
    "sbs_title",
    "domain",
    "severity",
    "status",
    "poam_status",
    "owner",
    "due_date",
    "remediation",
]

ALL_COLS = ["org", "platform"] + DETAIL_COLS

OBJECTS: list[dict] = [
    # ── Index patterns ────────────────────────────────────────────────────────
    index_pattern(_RUNS_INDEX, _RUNS_INDEX, "generated_at_utc"),
    index_pattern(_FINDINGS_INDEX, _FINDINGS_INDEX, "generated_at_utc"),
    # ── Shared: score tiles (already platform-filtered at query level) ─────────
    score_tile("viz-sfdc-score", "Salesforce Score", "Salesforce", "salesforce"),
    score_tile("viz-wd-score", "Workday Score", "Workday", "workday"),
    # ── Shared: combined overview only ────────────────────────────────────────
    donut_pie("viz-platform-pie", "Findings by Platform", "platform", desc="Finding count split by platform"),
    line_trend("viz-combined-score-trend", "Score Trend — Both Platforms", split_field="platform"),
    vbar(
        "viz-combined-domain-bar",
        "All Platforms — Findings by Domain",
        "domain",
        query=_FAIL_PARTIAL_QUERY,
        split_field="platform",
        desc="Fail/partial findings per domain, split by platform",
    ),
    vbar(
        "viz-combined-severity-bar",
        "All Platforms — Findings by Severity",
        "severity",
        split_field="platform",
        desc="Severity distribution split by platform",
    ),
    count_tile("viz-combined-open-poam", "Open POA&M (All Platforms)", _OPEN_ITEMS_LABEL, query="poam_status : Open"),
    # ── Salesforce-specific ───────────────────────────────────────────────────
    count_tile("viz-sfdc-pass-count", "Controls Passing", "Passing", query="platform : salesforce AND status : pass"),
    count_tile("viz-sfdc-fail-count", "Controls Failing", "Failing", query="platform : salesforce AND status : fail"),
    count_tile(
        "viz-sfdc-critical-count",
        "Critical Failures",
        "Critical",
        query="platform : salesforce AND status : fail AND severity : critical",
    ),
    count_tile(
        "viz-sfdc-open-poam",
        "Open POA&M Items",
        _OPEN_ITEMS_LABEL,
        query="platform : salesforce AND poam_status : Open",
    ),
    donut_pie(
        "viz-sfdc-status-pie",
        "Salesforce — Control Status",
        "status",
        query=_SFDC_FILTER,
        desc="Pass / Fail / Partial / Not Applicable distribution",
    ),
    hbar(
        "viz-sfdc-top-failing-bar",
        "Salesforce — Top Failing Controls",
        _SBS_TITLE_KW,
        query=_SFDC_FAIL_PARTIAL,
        split_field="severity",
        desc="Top 10 fail/partial Salesforce controls by full title, colored by severity",
    ),
    vbar(
        "viz-sfdc-domain-bar",
        "Salesforce — Risk by Domain",
        "domain",
        query=_SFDC_FAIL_PARTIAL,
        split_field="status",
        desc="Fail/partial findings per SSCF domain, stacked by status",
    ),
    vbar(
        "viz-sfdc-severity-bar",
        "Salesforce — Findings by Severity",
        "severity",
        query=_SFDC_FILTER,
        split_field="status",
        desc="Severity distribution stacked by control status",
    ),
    hbar(
        "viz-sfdc-owner-bar",
        "Salesforce — Open Items by Owner",
        "owner",
        query=_SFDC_FAIL_PARTIAL,
        desc="Which owner/team carries the most open remediation items",
    ),
    line_trend("viz-sfdc-score-trend", "Salesforce — Score Over Time", query=_SFDC_FILTER),
    agg_table(
        "viz-sfdc-critical-table",
        "Salesforce — Critical & High Failures",
        buckets=[
            ("severity", "Severity", 5),
            ("control_id", "Control ID", 10),
            (_SBS_TITLE_KW, "Description", 1),
            ("domain", "Domain", 1),
        ],
        query=_SFDC_FAIL_PARTIAL + " AND (severity : critical OR severity : high)",
    ),
    agg_table(
        "viz-sfdc-poam-table",
        "Salesforce — POA&M Open Items",
        buckets=[("control_id", "Control", 50), ("severity", "Severity", 5), ("poam_status", "Status", 5)],
        query='platform : salesforce AND (poam_status : Open OR poam_status : "In Progress")',
    ),
    # ── Workday-specific ──────────────────────────────────────────────────────
    count_tile("viz-wd-pass-count", "Controls Passing", "Passing", query="platform : workday AND status : pass"),
    count_tile("viz-wd-fail-count", "Controls Failing", "Failing", query="platform : workday AND status : fail"),
    count_tile(
        "viz-wd-critical-count",
        "Critical Failures",
        "Critical",
        query="platform : workday AND status : fail AND severity : critical",
    ),
    count_tile(
        "viz-wd-open-poam",
        "Open POA&M Items",
        _OPEN_ITEMS_LABEL,
        query="platform : workday AND poam_status : Open",
    ),
    donut_pie(
        "viz-wd-status-pie",
        "Workday — Control Status",
        "status",
        query=_WD_FILTER,
        desc="Pass / Fail / Partial / Not Applicable distribution",
    ),
    hbar(
        "viz-wd-top-failing-bar",
        "Workday — Top Failing Controls",
        _SBS_TITLE_KW,
        query=_WD_FAIL_PARTIAL,
        split_field="severity",
        desc="Top 10 fail/partial Workday controls by full title, colored by severity",
    ),
    vbar(
        "viz-wd-domain-bar",
        "Workday — Risk by Domain",
        "domain",
        query=_WD_FAIL_PARTIAL,
        split_field="status",
        desc="Fail/partial findings per SSCF domain, stacked by status",
    ),
    vbar(
        "viz-wd-severity-bar",
        "Workday — Findings by Severity",
        "severity",
        query=_WD_FILTER,
        split_field="status",
        desc="Severity distribution stacked by control status",
    ),
    hbar(
        "viz-wd-owner-bar",
        "Workday — Open Items by Owner",
        "owner",
        query=_WD_FAIL_PARTIAL,
        desc="Which owner/team carries the most open Workday remediation items",
    ),
    line_trend("viz-wd-score-trend", "Workday — Score Over Time", query=_WD_FILTER),
    agg_table(
        "viz-wd-critical-table",
        "Workday — Critical & High Failures",
        buckets=[
            ("severity", "Severity", 5),
            ("control_id", "Control ID", 10),
            (_SBS_TITLE_KW, "Description", 1),
            ("domain", "Domain", 1),
        ],
        query=_WD_FAIL_PARTIAL + " AND (severity : critical OR severity : high)",
    ),
    agg_table(
        "viz-wd-poam-table",
        "Workday — POA&M Open Items",
        buckets=[("control_id", "Control", 50), ("severity", "Severity", 5), ("poam_status", "Status", 5)],
        query='platform : workday AND (poam_status : Open OR poam_status : "In Progress")',
    ),
    # ── Saved searches ────────────────────────────────────────────────────────
    saved_search(
        "search-sfdc-failing",
        "Salesforce — Failing Controls (Document View)",
        DETAIL_COLS,
        query=_SFDC_FAIL_PARTIAL,
        desc="Row-level Salesforce fail/partial findings",
    ),
    saved_search(
        "search-wd-failing",
        "Workday — Failing Controls (Document View)",
        DETAIL_COLS,
        query=_WD_FAIL_PARTIAL,
        desc="Row-level Workday fail/partial findings",
    ),
    saved_search(
        "search-all-failing",
        "All Platforms — Failing Controls (Document View)",
        ALL_COLS,
        query=_FAIL_PARTIAL_QUERY,
        desc="All fail/partial findings across every platform",
    ),
    # ── Partials detail searches (with remediation description) ───────────────
    saved_search(
        "search-sfdc-partials",
        "Salesforce — Partial Controls (Expert Review Required)",
        ["control_id", "sbs_title", "domain", "severity", "remediation", "owner", "due_date"],
        query="platform : salesforce AND status : partial",
        desc="Partial Salesforce controls — shows the reason/description for why each control "
        "is partial and what expert review or additional steps are required",
    ),
    saved_search(
        "search-wd-partials",
        "Workday — Partial Controls (Expert Review Required)",
        ["control_id", "sbs_title", "domain", "severity", "remediation", "owner", "due_date"],
        query="platform : workday AND status : partial",
        desc="Partial Workday controls — shows the reason/description for why each control "
        "is partial and what expert review or additional steps are required",
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD LAYOUTS
# ─────────────────────────────────────────────────────────────────────────────
#  Grid is 48 columns wide. Heights are in grid units (~30 px each).
#  Layout pattern per platform dashboard:
#    Row 0 (h=10): Big score tile | Pass | Fail | Critical | Open POA&M
#    Row 1 (h=22): Top failing bar (wide) | Status donut
#    Row 2 (h=18): Domain bar (stacked) | Severity bar (stacked)
#    Row 3 (h=15): Owner bar | Score trend
#    Row 4 (h=18): Critical table | POA&M table
#    Row 5 (h=22): Document search (full width)
# ─────────────────────────────────────────────────────────────────────────────


def _platform_dashboard(  # NOSONAR
    plat: str,  # NOSONAR — kept for caller readability; not used in body
    score_id: str,
    pass_id: str,
    fail_id: str,
    top_failing_id: str,
    status_pie_id: str,
    domain_id: str,
    sev_id: str,
    owner_id: str,
    trend_id: str,
    crit_table_id: str,
    poam_table_id: str,
    search_id: str,
    partials_search_id: str,
    dash_id: str,
    dash_title: str,
    dash_desc: str,
    full_width_top_failing: bool = False,
) -> dict:
    if full_width_top_failing:
        # SFDC layout — Top Failing gets its own full-width row for readability
        # Row 0 (y=0,  h=10): Score | Pass | Fail
        # Row 1 (y=10, h=28): Top Failing — FULL WIDTH
        # Row 2 (y=38, h=18): Status donut | Domain bar
        # Row 3 (y=56, h=18): Severity bar | Owner bar
        # Row 4 (y=74, h=15): Score trend — FULL WIDTH
        # Row 5 (y=89, h=20): Critical & High table — FULL WIDTH
        # Row 6 (y=109, h=20): POA&M table — FULL WIDTH
        # Row 7 (y=129, h=25): Failing controls search — FULL WIDTH
        # Row 8 (y=154, h=25): Partial controls search — FULL WIDTH
        panels = [
            panel(1, 0, 0, 16, 10, score_id),
            panel(2, 16, 0, 16, 10, pass_id),
            panel(3, 32, 0, 16, 10, fail_id),
            panel(4, 0, 10, 48, 28, top_failing_id),
            panel(5, 0, 38, 16, 18, status_pie_id),
            panel(6, 16, 38, 32, 18, domain_id),
            panel(7, 0, 56, 28, 18, sev_id),
            panel(8, 28, 56, 20, 18, owner_id),
            panel(9, 0, 74, 48, 15, trend_id),
            panel(10, 0, 89, 48, 20, crit_table_id),
            panel(11, 0, 109, 48, 20, poam_table_id),
            panel(12, 0, 129, 48, 25, search_id, obj_type="search"),
            panel(13, 0, 154, 48, 25, partials_search_id, obj_type="search"),
        ]
    else:
        # Standard layout — Top Failing shares row with status donut
        # Row 0 (y=0,  h=10): Score | Pass | Fail
        # Row 1 (y=10, h=22): Top Failing (wide) | Status donut
        # Row 2 (y=32, h=18): Domain bar | Severity bar
        # Row 3 (y=50, h=15): Owner bar | Score trend
        # Row 4 (y=65, h=20): Critical & High table — FULL WIDTH
        # Row 5 (y=85, h=20): POA&M table — FULL WIDTH
        # Row 6 (y=105, h=25): Failing controls search — FULL WIDTH
        # Row 7 (y=130, h=25): Partial controls search — FULL WIDTH
        panels = [
            panel(1, 0, 0, 16, 10, score_id),
            panel(2, 16, 0, 16, 10, pass_id),
            panel(3, 32, 0, 16, 10, fail_id),
            panel(4, 0, 10, 32, 22, top_failing_id),
            panel(5, 32, 10, 16, 22, status_pie_id),
            panel(6, 0, 32, 28, 18, domain_id),
            panel(7, 28, 32, 20, 18, sev_id),
            panel(8, 0, 50, 24, 15, owner_id),
            panel(9, 24, 50, 24, 15, trend_id),
            panel(10, 0, 65, 48, 20, crit_table_id),
            panel(11, 0, 85, 48, 20, poam_table_id),
            panel(12, 0, 105, 48, 25, search_id, obj_type="search"),
            panel(13, 0, 130, 48, 25, partials_search_id, obj_type="search"),
        ]
    refs = [
        ref("panel_1", "visualization", score_id),
        ref("panel_2", "visualization", pass_id),
        ref("panel_3", "visualization", fail_id),
        ref("panel_4", "visualization", top_failing_id),
        ref("panel_5", "visualization", status_pie_id),
        ref("panel_6", "visualization", domain_id),
        ref("panel_7", "visualization", sev_id),
        ref("panel_8", "visualization", owner_id),
        ref("panel_9", "visualization", trend_id),
        ref("panel_10", "visualization", crit_table_id),
        ref("panel_11", "visualization", poam_table_id),
        ref("panel_12", "search", search_id),
        ref("panel_13", "search", partials_search_id),
    ]
    return dashboard_obj(dash_id, dash_title, dash_desc, panels, refs)


sfdc_dash = _platform_dashboard(
    plat="salesforce",
    score_id="viz-sfdc-score",
    pass_id="viz-sfdc-pass-count",
    fail_id="viz-sfdc-fail-count",
    top_failing_id="viz-sfdc-top-failing-bar",
    status_pie_id="viz-sfdc-status-pie",
    domain_id="viz-sfdc-domain-bar",
    sev_id="viz-sfdc-severity-bar",
    owner_id="viz-sfdc-owner-bar",
    trend_id="viz-sfdc-score-trend",
    crit_table_id="viz-sfdc-critical-table",
    poam_table_id="viz-sfdc-poam-table",
    search_id="search-sfdc-failing",
    partials_search_id="search-sfdc-partials",
    dash_id="sfdc-dashboard",
    dash_title="Salesforce Security Posture",
    dash_desc="Salesforce OSCAL/SBS assessment — platform-filtered score, domain risk, "
    "top failing controls, severity breakdown, owner accountability, and POA&M.",
    full_width_top_failing=True,
)

wd_dash = _platform_dashboard(
    plat="workday",
    score_id="viz-wd-score",
    pass_id="viz-wd-pass-count",
    fail_id="viz-wd-fail-count",
    top_failing_id="viz-wd-top-failing-bar",
    status_pie_id="viz-wd-status-pie",
    domain_id="viz-wd-domain-bar",
    sev_id="viz-wd-severity-bar",
    owner_id="viz-wd-owner-bar",
    trend_id="viz-wd-score-trend",
    crit_table_id="viz-wd-critical-table",
    poam_table_id="viz-wd-poam-table",
    search_id="search-wd-failing",
    partials_search_id="search-wd-partials",
    dash_id="workday-dashboard",
    dash_title="Workday Security Posture",
    dash_desc="Workday HCM/Finance OSCAL/WSCC assessment — platform-filtered score, domain risk, "
    "top failing controls, severity breakdown, owner accountability, and POA&M.",
)

# Combined overview
main_panels = [
    # Row 0: score tiles + platform pie
    panel(1, 0, 0, 16, 10, "viz-sfdc-score"),
    panel(2, 16, 0, 16, 10, "viz-wd-score"),
    panel(3, 32, 0, 16, 10, "viz-platform-pie"),
    # Row 1: top failing (all) + combined severity
    panel(4, 0, 10, 32, 22, "viz-combined-top-failing-bar"),
    panel(5, 32, 10, 16, 22, "viz-combined-severity-bar"),
    # Row 2: domain bar + score trend
    panel(6, 0, 32, 28, 18, "viz-combined-domain-bar"),
    panel(7, 28, 32, 20, 18, "viz-combined-score-trend"),
    # Row 3: open POA&M tile
    panel(8, 0, 50, 8, 12, "viz-combined-open-poam"),
    # Row 4: full-width document search
    panel(9, 0, 62, 48, 22, "search-all-failing", obj_type="search"),
]
main_refs = [
    ref("panel_1", "visualization", "viz-sfdc-score"),
    ref("panel_2", "visualization", "viz-wd-score"),
    ref("panel_3", "visualization", "viz-platform-pie"),
    ref("panel_4", "visualization", "viz-combined-top-failing-bar"),
    ref("panel_5", "visualization", "viz-combined-severity-bar"),
    ref("panel_6", "visualization", "viz-combined-domain-bar"),
    ref("panel_7", "visualization", "viz-combined-score-trend"),
    ref("panel_8", "visualization", "viz-combined-open-poam"),
    ref("panel_9", "search", "search-all-failing"),
]

# Add the combined top-failing bar (referenced by the overview dashboard)
OBJECTS.append(
    hbar(
        "viz-combined-top-failing-bar",
        "All Platforms — Top Failing Controls",
        _SBS_TITLE_KW,
        query=_FAIL_PARTIAL_QUERY,
        split_field="platform",
        desc="Top 10 fail/partial controls across all platforms, colored by platform",
    ),
)

main_dash = dashboard_obj(
    "sscf-main-dashboard",
    "SSCF Security Posture Overview",
    "Combined cross-platform view — Salesforce & Workday scores, domain risk, "
    "top failing controls, severity trends, and score history.",
    main_panels,
    main_refs,
)

OBJECTS += [sfdc_dash, wd_dash, main_dash]

# WRITE
_OUT.parent.mkdir(parents=True, exist_ok=True)
lines = [json.dumps(obj, separators=(",", ":")) for obj in OBJECTS]
_OUT.write_text("\n".join(lines) + "\n")
print(f"Written {len(lines)} saved objects → {_OUT}")
