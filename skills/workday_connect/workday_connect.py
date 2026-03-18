"""
workday_connect — Workday HCM/Finance tenant security baseline collector.

Read-only. Never modifies tenant configuration.
Auth: OAuth 2.0 Client Credentials (machine-to-machine) exclusively. No SOAP/WS-Security.
Catalog-driven: reads config/workday/workday_catalog.json for control enumeration.

Usage:
    workday-connect collect [--org ALIAS] [--env ENV] [--dry-run]
    workday-connect auth [--dry-run]
    workday-connect org-info
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import yaml
from dotenv import load_dotenv

load_dotenv()

_REPO = Path(__file__).resolve().parents[2]
_CATALOG_PATH = _REPO / "config" / "workday" / "workday_catalog.json"
_SSCF_MAP_PATH = _REPO / "config" / "workday" / "workday_to_sscf_mapping.yaml"
_SCHEMA_PATH = _REPO / "schemas" / "baseline_assessment_schema.json"
_VERSION = "0.1.0"

WD_NS = "urn:com.workday/bsvc"

# Assessment thresholds (from BLUEPRINT.md)
_THRESHOLDS = {
    "min_password_length": 12,
    "max_password_expiry_days": 90,
    "min_password_history": 12,
    "max_session_timeout_minutes": 30,
    "max_lockout_threshold": 5,
    "min_lockout_duration_minutes": 15,
    "min_audit_retention_days": 365,
    "max_isu_password_age_days": 90,
}

# ---------------------------------------------------------------------------
# OAuth 2.0 token cache
# ---------------------------------------------------------------------------

_token_cache: dict[str, Any] = {}


def get_oauth_token(client_id: str, client_secret: str, token_url: str) -> str:
    """Acquire or return cached OAuth 2.0 Client Credentials token.

    Never logs client_secret or the returned token.
    Token is refreshed 60 s before expiry.
    """
    import requests

    now = time.time()
    if _token_cache.get("expires_at", 0) > now + 60:
        return str(_token_cache["access_token"])

    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"OAuth token acquisition failed: {exc}") from exc

    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 3600))
    return str(_token_cache["access_token"])


def clear_token_cache() -> None:
    """Clear cached token — used in tests."""
    _token_cache.clear()


# ---------------------------------------------------------------------------
# Catalog loading
# ---------------------------------------------------------------------------


def _props_dict(props: list[dict[str, Any]]) -> dict[str, str]:
    """Flatten OSCAL props array → {name: value}."""
    return {p["name"]: p["value"] for p in props}


def load_catalog() -> list[dict[str, Any]]:
    """Load workday_catalog.json; return flat list of control metadata dicts."""
    raw = json.loads(_CATALOG_PATH.read_text())
    controls: list[dict[str, Any]] = []
    for group in raw["catalog"]["groups"]:
        for ctrl in group["controls"]:
            props = _props_dict(ctrl.get("props", []))
            controls.append(
                {
                    "id": props.get("label", ctrl["id"].upper()),
                    "title": ctrl["title"],
                    "group_id": group["id"],
                    "severity": props.get("severity", "moderate"),
                    "collection_method": props.get("collection-method", "manual"),
                    "raas_report": props.get("raas-report"),
                    "rest_endpoint": (props.get("rest-endpoint") or "").removeprefix("GET ").removeprefix("POST "),
                    "sscf_control": props.get("sscf-control"),
                }
            )
    return controls


# ---------------------------------------------------------------------------
# SSCF mapping helpers
# ---------------------------------------------------------------------------


def load_sscf_domain_map() -> dict[str, list[dict[str, Any]]]:
    """Return {domain_id: [sscf_mapping, ...]} from workday_to_sscf_mapping.yaml."""
    data = yaml.safe_load(_SSCF_MAP_PATH.read_text())
    return data.get("defaults_by_domain", {})


def _sscf_for_control(ctrl: dict[str, Any], domain_map: dict[str, Any]) -> list[dict[str, Any]]:
    """Return SSCF mappings for a control using group domain as fallback."""
    # Direct sscf-control prop takes priority
    if ctrl.get("sscf_control"):
        return [{"sscf_control_id": ctrl["sscf_control"], "sscf_domain": ctrl["group_id"]}]
    # Fall back to domain defaults
    return domain_map.get(ctrl["group_id"], [])


# ---------------------------------------------------------------------------
# RaaS transport
# ---------------------------------------------------------------------------


def call_raas(base_url: str, tenant: str, report_name: str, token: str) -> tuple[int, dict[str, Any] | None]:
    """GET a RaaS JSON endpoint; return (status_code, json_or_none)."""
    import requests

    url = f"{base_url}/ccx/service/customreport2/{tenant}/{report_name}?format=json"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if resp.status_code == 200:
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, None
    return resp.status_code, None


# ---------------------------------------------------------------------------
# REST transport
# ---------------------------------------------------------------------------


def call_rest(base_url: str, endpoint: str, token: str) -> tuple[int, dict[str, Any] | None]:
    """GET a Workday REST API endpoint; return (status_code, json_or_none)."""
    import requests

    url = f"{base_url}/ccx/api{endpoint}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if resp.status_code == 200:
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, None
    return resp.status_code, None


# ---------------------------------------------------------------------------
# Per-method collectors
# ---------------------------------------------------------------------------


def collect_raas(
    ctrl: dict[str, Any],
    base_url: str,
    tenant: str,
    token: str,
) -> dict[str, Any]:
    """Collect via RaaS. Returns partial finding dict."""
    report = ctrl["raas_report"]
    status_code, data = call_raas(base_url, tenant, report, token)

    if status_code == 404:
        return {
            "status": "not_applicable",
            "observed_value": None,
            "evidence_source": f"RaaS GET {report}",
            "platform_data": {
                "collection_method": "raas",
                "raas_available": False,
                "collection_method_note": (
                    f"RaaS report '{report}' not pre-configured. "
                    "Control requires manual review or report pre-configuration."
                ),
            },
        }

    if status_code != 200 or data is None:
        return {
            "status": "partial",
            "observed_value": None,
            "evidence_source": f"RaaS GET {report} — HTTP {status_code}",
            "platform_data": {"collection_method": "raas", "http_status": status_code},
        }

    record_count = len(data.get("Report_Entry", data.get("data", [])))
    return {
        "status": "partial",
        "observed_value": f"RaaS report returned {record_count} entries",
        "evidence_source": f"workday-connect://raas/{report}",
        "notes": "RaaS data collected; human review required for pass/fail determination",
        "platform_data": {
            "collection_method": "raas",
            "raas_available": True,
            "record_count": record_count,
            "report_name": report,
        },
    }


def collect_rest(
    ctrl: dict[str, Any],
    base_url: str,
    token: str,
) -> dict[str, Any]:
    """Collect via Workday REST API."""
    endpoint = ctrl["rest_endpoint"]
    status_code, data = call_rest(base_url, endpoint, token)

    if status_code != 200 or data is None:
        return {
            "status": "partial",
            "observed_value": None,
            "evidence_source": f"REST GET {endpoint} — HTTP {status_code}",
            "platform_data": {"collection_method": "rest", "http_status": status_code},
        }

    # WD-IAM-007: inactive worker accounts (lastLogin > 90 days)
    if ctrl["id"] == "WD-IAM-007":
        workers = data.get("data", [])
        total = len(workers)
        return {
            "status": "partial",
            "observed_value": f"Active workers accessible: {total}",
            "evidence_source": f"workday-connect://rest{endpoint}",
            "notes": "Inactive account filter requires lastLogin date comparison; human review of full list",
            "platform_data": {
                "collection_method": "rest",
                "worker_count": total,
                "endpoint": endpoint,
            },
        }

    # Generic REST fallback
    return {
        "status": "partial",
        "observed_value": json.dumps(data)[:200],
        "evidence_source": f"workday-connect://rest{endpoint}",
        "platform_data": {"collection_method": "rest", "http_status": status_code},
    }


def collect_manual(ctrl: dict[str, Any]) -> dict[str, Any]:
    """Manual controls always return not_applicable with an explanatory note."""
    notes_by_id: dict[str, str] = {
        "WD-CKM-002": (
            "BYOK (Bring Your Own Key) configuration requires confirmation from the "
            "Workday tenant administrator via manual questionnaire."
        ),
    }
    return {
        "status": "not_applicable",
        "observed_value": None,
        "evidence_source": "manual questionnaire required",
        "platform_data": {
            "collection_method": "manual",
            "collection_method_note": notes_by_id.get(
                ctrl["id"],
                f"Control {ctrl['id']} requires manual verification.",
            ),
        },
    }


# ---------------------------------------------------------------------------
# Main collection loop
# ---------------------------------------------------------------------------


def run_collect(
    base_url: str,
    tenant: str,
    token: str,
    api_version: str,
    org_alias: str,
    env: str,
    assessment_owner: str,
    out_path: Path,
) -> dict[str, Any]:
    """Run all controls from catalog; write schema v2 output to out_path."""
    controls = load_catalog()
    domain_map = load_sscf_domain_map()

    findings: list[dict[str, Any]] = []
    for ctrl in controls:
        method = ctrl["collection_method"]

        if method == "raas":
            raw = collect_raas(ctrl, base_url, tenant, token)
        elif method == "rest":
            raw = collect_rest(ctrl, base_url, token)
        else:
            raw = collect_manual(ctrl)

        sscf = _sscf_for_control(ctrl, domain_map)
        finding: dict[str, Any] = {
            "control_id": ctrl["id"],
            "title": ctrl["title"],
            "status": raw.get("status", "partial"),
            "severity": ctrl["severity"],
            "evidence_source": raw.get("evidence_source", "workday-connect"),
            "observed_value": raw.get("observed_value"),
            "expected_value": raw.get("expected_value"),
            "notes": raw.get("notes"),
            "sscf_mappings": sscf,
            "platform_data": raw.get("platform_data", {}),
        }
        findings.append(finding)

    now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    output: dict[str, Any] = {
        "schema_version": "2.0",
        "assessment_id": f"wd-assess-{org_alias}-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
        "platform": "workday",
        "oscal_catalog_ref": "config/workday/workday_catalog.json",
        "assessment_time_utc": now_utc,
        "environment": env,
        "assessor": f"workday-connect v{_VERSION}",
        "assessment_owner": assessment_owner,
        "data_source": "live_api",  # schema enum: live_api | dry_run_stub | manual_questionnaire
        "collector_detail": f"workday-connect OAuth 2.0 REST + RaaS {api_version}",
        "ai_generated_findings_notice": (
            "Findings produced by automated collector workday-connect. "
            "Requires human review before use in audit evidence."
        ),
        "assessment_scope": {
            "controls_in_scope": len(controls),
            "controls_excluded": sum(1 for f in findings if f["status"] == "not_applicable"),
        },
        "org": org_alias,
        "findings": findings,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # lgtm[py/clear-text-storage-sensitive-data] — output contains password POLICY values
    # (e.g. Minimum_Password_Length) collected as security assessment evidence, not credentials.
    # Bearer token and client_secret are never included in this dict.
    out_path.write_text(json.dumps(output, indent=2))
    return output


# ---------------------------------------------------------------------------
# Dry-run display
# ---------------------------------------------------------------------------


def print_dry_run_plan(tenant: str, org_alias: str) -> None:
    controls = load_catalog()
    method_counts: dict[str, int] = {}
    click.echo("\nDRY-RUN: Workday Connect Collection Plan")
    click.echo(f"Tenant:   {tenant}")
    click.echo(f"Org:      {org_alias}")
    click.echo(f"Controls: {len(controls)}")
    click.echo("")
    for ctrl in controls:
        m = ctrl["collection_method"]
        method_counts[m] = method_counts.get(m, 0) + 1
        op = ctrl.get("raas_report") or ctrl.get("rest_endpoint") or "(manual)"
        if m == "raas":
            flag = "*"
        elif m == "manual":
            flag = "-"
        else:
            flag = " "
        click.echo(f"  {ctrl['id']:<14} {m:<12} {op:<40} {flag}")
    click.echo(f"\nMethod summary: {method_counts}")
    click.echo(f"\nWould write: docs/oscal-salesforce-poc/generated/{org_alias}/workday_raw.json")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """workday-connect — Workday HCM/Finance security baseline collector."""


@cli.command()
@click.option("--org", default="unknown-org", envvar="WD_ORG_ALIAS", show_default=True)
@click.option("--env", default="dev", type=click.Choice(["dev", "test", "prod"]), show_default=True)
@click.option("--dry-run", is_flag=True, help="Print collection plan without making API calls.")
@click.option("--out", default=None, help="Override output file path.")
def collect(org: str, env: str, dry_run: bool, out: str | None) -> None:
    """Collect Workday security configuration and emit a baseline assessment JSON."""
    tenant = os.getenv("WD_TENANT", "")
    client_id = os.getenv("WD_CLIENT_ID", "")
    client_secret = os.getenv("WD_CLIENT_SECRET", "")
    token_url = os.getenv("WD_TOKEN_URL") or f"https://{tenant}.workday.com/ccx/oauth2/{tenant}/token"
    base_url = os.getenv("WD_BASE_URL") or f"https://{tenant}.workday.com"
    api_version = os.getenv("WD_API_VERSION", "v40.0")
    assessment_owner = os.getenv("WD_ASSESSMENT_OWNER", "Security Team")

    if dry_run:
        print_dry_run_plan(tenant or "not-set", org)
        return

    env_checks = [("WD_TENANT", tenant), ("WD_CLIENT_ID", client_id), ("WD_CLIENT_SECRET", client_secret)]
    missing = [v for v, k in env_checks if not k]
    if missing:
        click.echo(f"ERROR: Missing required env vars: {missing}", err=True)
        sys.exit(1)

    click.echo(f"  [workday-connect] org={org} env={env} tenant={tenant}", err=True)

    token = get_oauth_token(client_id, client_secret, token_url)
    del client_secret  # clear credential from scope — token is short-lived and not stored in output
    click.echo("  [workday-connect] authenticated via OAuth 2.0", err=True)

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    if out:
        out_path = Path(out)
    else:
        out_path = _REPO / "docs" / "oscal-salesforce-poc" / "generated" / org / date_str / "workday_raw.json"

    output = run_collect(base_url, tenant, token, api_version, org, env, assessment_owner, out_path)
    total = len(output["findings"])
    passed = sum(1 for f in output["findings"] if f["status"] == "pass")
    failed = sum(1 for f in output["findings"] if f["status"] == "fail")
    click.echo(f"  [workday-connect] {total} controls — pass={passed} fail={failed}", err=True)
    click.echo(json.dumps({"status": "ok", "output_file": str(out_path), "controls": total}))


@cli.command()
@click.option("--dry-run", is_flag=True, help="Validate env vars only, no API call.")
def auth(dry_run: bool) -> None:
    """Test OAuth 2.0 connection to Workday tenant."""
    tenant = os.getenv("WD_TENANT", "")
    client_id = os.getenv("WD_CLIENT_ID", "")
    client_secret = os.getenv("WD_CLIENT_SECRET", "")
    token_url = os.getenv("WD_TOKEN_URL") or f"https://{tenant}.workday.com/ccx/oauth2/{tenant}/token"

    required = {"WD_TENANT": tenant, "WD_CLIENT_ID": client_id, "WD_CLIENT_SECRET": client_secret}
    missing = [k for k, v in required.items() if not v]
    if missing:
        click.echo(f"ERROR: Missing env vars: {missing}", err=True)
        sys.exit(1)

    if dry_run:
        click.echo(f"DRY-RUN: WD_TENANT={tenant}, WD_CLIENT_ID={client_id[:8]}..., token_url={token_url}")
        return

    try:
        get_oauth_token(client_id, client_secret, token_url)
        click.echo(f"OK: authenticated to tenant={tenant}")
    except RuntimeError as exc:
        click.echo(f"FAIL: {exc}", err=True)
        sys.exit(1)


@cli.command("org-info")
def org_info() -> None:
    """Print tenant configuration from environment."""
    tenant = os.getenv("WD_TENANT", "(not set)")
    base_url = os.getenv("WD_BASE_URL") or f"https://{tenant}.workday.com"
    api_version = os.getenv("WD_API_VERSION", "v40.0")
    has_secret = bool(os.getenv("WD_CLIENT_SECRET"))
    click.echo(
        json.dumps(
            {
                "tenant": tenant,
                "base_url": base_url,
                "api_version": api_version,
                "client_id_set": bool(os.getenv("WD_CLIENT_ID")),
                "client_secret_set": has_secret,
                "token_url_set": bool(os.getenv("WD_TOKEN_URL")),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    cli()
