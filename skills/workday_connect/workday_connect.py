"""
workday_connect — Workday HCM/Finance tenant security baseline collector.

Read-only. Never modifies tenant configuration.
Auth: OAuth 2.0 Client Credentials (machine-to-machine). No WS-Security BasicAuth.
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
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"

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
# SOAP response cache (one call per unique operation)
# ---------------------------------------------------------------------------

_soap_cache: dict[str, tuple[int, str]] = {}


def _soap_cache_key(service: str, operation: str) -> str:
    return f"{service}:{operation}"


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
                    "soap_service": props.get("soap-service", "Security_Configuration"),
                    "soap_operation": props.get("soap-operation"),
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
# SOAP transport
# ---------------------------------------------------------------------------

_SOAP_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope
    xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:wd="urn:com.workday/bsvc">
  <SOAP-ENV:Body>
    <wd:{operation}_Request wd:version="{api_version}">
    </wd:{operation}_Request>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""


def _soap_url(base_url: str, tenant: str, service: str, api_version: str) -> str:
    return f"{base_url}/ccx/service/{tenant}/{service}/{api_version}"


def call_soap(
    base_url: str,
    tenant: str,
    service: str,
    operation: str,
    token: str,
    api_version: str,
    *,
    use_cache: bool = True,
) -> tuple[int, str]:
    """POST a minimal SOAP envelope; return (status_code, response_text).

    Results are cached per (service, operation) to avoid duplicate API calls
    when multiple controls share the same SOAP operation.
    """
    import requests

    cache_key = _soap_cache_key(service, operation)
    if use_cache and cache_key in _soap_cache:
        return _soap_cache[cache_key]

    url = _soap_url(base_url, tenant, service, api_version)
    body = _SOAP_TEMPLATE.format(operation=operation, api_version=api_version)
    headers = {
        "Content-Type": "text/xml; charset=UTF-8",
        "Authorization": f"Bearer {token}",
        "SOAPAction": f"urn:com.workday/bsvc/{operation}",
    }
    resp = requests.post(url, data=body.encode(), headers=headers, timeout=30)
    result = (resp.status_code, resp.text)
    if use_cache:
        _soap_cache[cache_key] = result
    return result


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
# XML helpers
# ---------------------------------------------------------------------------


def _xml_text(xml_str: str, *element_names: str) -> str | None:
    """Return text of the first matching element (any of element_names) in WD namespace."""
    try:
        from lxml import etree  # type: ignore[import-untyped]

        root = etree.fromstring(xml_str.encode())
        for name in element_names:
            el = root.find(f".//{{{WD_NS}}}{name}")
            if el is not None and el.text:
                return el.text.strip()
        return None
    except Exception:
        return None


def _xml_all_texts(xml_str: str, element_name: str) -> list[str]:
    """Return all text values for elements matching element_name in WD namespace."""
    try:
        from lxml import etree  # type: ignore[import-untyped]

        root = etree.fromstring(xml_str.encode())
        return [el.text.strip() for el in root.findall(f".//{{{WD_NS}}}{element_name}") if el.text]
    except Exception:
        return []


def _bool_val(raw: str | None) -> bool | None:
    """Coerce Workday boolean text (true/false/1/0) to Python bool."""
    if raw is None:
        return None
    return raw.strip().lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Per-control assessment logic
# ---------------------------------------------------------------------------


def _assess_password_rules(ctrl_id: str, xml_str: str) -> dict[str, Any]:  # NOSONAR
    """Assess WD-CON-001, WD-CON-002, WD-CON-004 from Get_Password_Rules response."""
    t = _THRESHOLDS
    result: dict[str, Any] = {"observed": {}, "status": "partial", "notes": ""}

    if ctrl_id == "WD-CON-001":
        val = _xml_text(xml_str, "Minimum_Password_Length")
        result["observed"] = {"Minimum_Password_Length": val}
        result["expected"] = f">= {t['min_password_length']}"
        if val is not None:
            result["status"] = "pass" if int(val) >= t["min_password_length"] else "fail"
            result["observed_value"] = f"Minimum_Password_Length={val}"
        else:
            result["notes"] = "Field not returned by API"

    elif ctrl_id == "WD-CON-002":
        expiry = _xml_text(xml_str, "Password_Expiration_Days")
        history = _xml_text(xml_str, "Password_History_Count")
        result["observed"] = {"Password_Expiration_Days": expiry, "Password_History_Count": history}
        result["expected"] = f"expiry <= {t['max_password_expiry_days']} AND history >= {t['min_password_history']}"
        if expiry is not None and history is not None:
            ok = int(expiry) <= t["max_password_expiry_days"] and int(history) >= t["min_password_history"]
            result["status"] = "pass" if ok else "fail"
            result["observed_value"] = f"Password_Expiration_Days={expiry}, Password_History_Count={history}"
        else:
            result["notes"] = "One or more fields not returned by API"

    elif ctrl_id == "WD-CON-004":
        threshold = _xml_text(xml_str, "Lockout_Threshold")
        duration = _xml_text(xml_str, "Lockout_Duration_Minutes")
        result["observed"] = {"Lockout_Threshold": threshold, "Lockout_Duration_Minutes": duration}
        result["expected"] = (
            f"threshold <= {t['max_lockout_threshold']} AND duration >= {t['min_lockout_duration_minutes']}"
        )
        if threshold is not None and duration is not None:
            ok = int(threshold) <= t["max_lockout_threshold"] and int(duration) >= t["min_lockout_duration_minutes"]
            result["status"] = "pass" if ok else "fail"
            result["observed_value"] = f"Lockout_Threshold={threshold}, Lockout_Duration_Minutes={duration}"
        else:
            result["notes"] = "One or more fields not returned by API"

    return result


def _assess_soap_result(ctrl_id: str, xml_str: str) -> dict[str, Any]:  # NOSONAR
    """Route SOAP XML response to the appropriate assessment function."""
    # Password rules: CON-001, CON-002, CON-004 all share Get_Password_Rules
    if ctrl_id in ("WD-CON-001", "WD-CON-002", "WD-CON-004"):
        return _assess_password_rules(ctrl_id, xml_str)

    # Session timeout
    if ctrl_id == "WD-CON-003":
        val = _xml_text(xml_str, "Session_Timeout_Minutes", "SessionTimeout")
        result: dict[str, Any] = {
            "observed": {"Session_Timeout_Minutes": val},
            "expected": f"<= {_THRESHOLDS['max_session_timeout_minutes']}",
        }
        if val is not None:
            result["status"] = "pass" if int(val) <= _THRESHOLDS["max_session_timeout_minutes"] else "fail"
            result["observed_value"] = f"Session_Timeout_Minutes={val}"
        else:
            result["status"] = "partial"
            result["notes"] = "Field not returned by API"
        return result

    # IP restriction
    if ctrl_id == "WD-CON-005":
        ranges = _xml_all_texts(xml_str, "IP_Range")
        has_restriction = len(ranges) > 0
        return {
            "observed": {"IP_Range_count": len(ranges)},
            "expected": "At least one IP range configured",
            "status": "pass" if has_restriction else "fail",
            "observed_value": f"IP ranges configured: {len(ranges)}",
        }

    # Auth policy coverage
    if ctrl_id == "WD-CON-006":
        policies = _xml_all_texts(xml_str, "Authentication_Policy_Name")
        return {
            "observed": {"policy_count": len(policies)},
            "expected": "At least one authentication policy covering all users",
            "status": "pass" if len(policies) >= 1 else "fail",
            "observed_value": f"Authentication policies found: {len(policies)}",
        }

    # ISU Disallow_UI_Sessions
    if ctrl_id == "WD-IAM-002":
        vals = _xml_all_texts(xml_str, "Disallow_UI_Sessions")
        all_disabled = all(_bool_val(v) for v in vals) if vals else None
        iam002_status = "pass" if all_disabled else ("fail" if all_disabled is False else "partial")
        return {
            "observed": {"Disallow_UI_Sessions_values": vals},
            "expected": "Disallow_UI_Sessions=true for all ISUs",
            "status": iam002_status,
            "observed_value": f"Disallow_UI_Sessions values: {vals}",
        }

    # MFA required on all auth policies
    if ctrl_id == "WD-IAM-003":
        mfa_vals = _xml_all_texts(xml_str, "Multi_Factor_Authentication_Required")
        all_mfa = all(_bool_val(v) for v in mfa_vals) if mfa_vals else None
        iam003_status = "pass" if all_mfa else ("fail" if all_mfa is False else "partial")
        return {
            "observed": {"MFA_Required_values": mfa_vals},
            "expected": "Multi_Factor_Authentication_Required=true on all policies",
            "status": iam003_status,
            "observed_value": f"MFA required on {sum(1 for v in mfa_vals if _bool_val(v))}/{len(mfa_vals)} policies",
        }

    # SSO + signed assertions
    if ctrl_id == "WD-IAM-004":
        sso_active = _bool_val(_xml_text(xml_str, "SSO_Enabled", "SAML_Enabled"))
        signed = _bool_val(_xml_text(xml_str, "Require_Signed_Assertions"))
        ok = sso_active and signed
        return {
            "observed": {"SSO_Enabled": sso_active, "Require_Signed_Assertions": signed},
            "expected": "SSO enabled with signed assertions required",
            "status": "pass" if ok else "fail",
            "observed_value": f"SSO_Enabled={sso_active}, Require_Signed_Assertions={signed}",
        }

    # API client scope check
    if ctrl_id == "WD-IAM-008":
        broad_scopes = _xml_all_texts(xml_str, "All_Workday_Data")
        flagged = any(_bool_val(v) for v in broad_scopes)
        return {
            "observed": {"broad_scope_clients": len(broad_scopes)},
            "expected": "No API clients with All_Workday_Data scope",
            "status": "fail" if flagged else "pass",
            "observed_value": f"API clients with broad scope: {len(broad_scopes)}",
        }

    # Audit log retention
    if ctrl_id == "WD-LOG-005":
        val = _xml_text(xml_str, "Audit_Log_Retention_Days")
        if val is not None:
            ok = int(val) >= _THRESHOLDS["min_audit_retention_days"]
            return {
                "observed": {"Audit_Log_Retention_Days": val},
                "expected": f">= {_THRESHOLDS['min_audit_retention_days']}",
                "status": "pass" if ok else "fail",
                "observed_value": f"Audit_Log_Retention_Days={val}",
            }
        return {"status": "partial", "observed": {}, "notes": "Audit_Log_Retention_Days not returned"}

    # TLS required for API
    if ctrl_id == "WD-CKM-001":
        val = _bool_val(_xml_text(xml_str, "Require_TLS_For_API", "TLS_Required"))
        return {
            "observed": {"Require_TLS_For_API": val},
            "expected": "Require_TLS_For_API=true",
            "status": "pass" if val else "fail",
            "observed_value": f"Require_TLS_For_API={val}",
        }

    # ISU credential age
    if ctrl_id == "WD-CKM-003":
        rotation_dates = _xml_all_texts(xml_str, "Password_Last_Changed_Date")
        return {
            "observed": {"ISU_credential_rotation_dates": rotation_dates},
            "expected": f"Credential rotated within {_THRESHOLDS['max_isu_password_age_days']} days",
            "status": "partial" if rotation_dates else "not_applicable",
            "observed_value": f"ISU credentials last rotated: {rotation_dates or 'unknown'}",
            "notes": "Age comparison requires runtime date calculation; review dates manually",
        }

    # Pending security policies
    if ctrl_id == "WD-GOV-001":
        pending = _xml_all_texts(xml_str, "Pending_Security_Policy")
        return {
            "observed": {"pending_count": len(pending)},
            "expected": "No pending security policies",
            "status": "pass" if len(pending) == 0 else "fail",
            "observed_value": f"Pending security policies: {len(pending)}",
        }

    # Failed login alert
    if ctrl_id == "WD-TDR-001":
        threshold = _xml_text(xml_str, "Failed_Login_Alert_Threshold")
        routing = _xml_text(xml_str, "Alert_Routing_Enabled", "Alert_Email")
        return {
            "observed": {"Failed_Login_Alert_Threshold": threshold, "alert_routing": routing},
            "expected": "Alert threshold configured with routing",
            "status": "pass" if threshold and routing else "partial",
            "observed_value": f"Failed_Login_Alert_Threshold={threshold}, routing={routing}",
        }

    # Business process approval steps
    if ctrl_id == "WD-TDR-002":
        single_approver = _xml_all_texts(xml_str, "Single_Approver_Chain")
        return {
            "observed": {"single_approver_chains": len(single_approver)},
            "expected": "No single-approver business process chains for sensitive actions",
            "status": "pass" if len(single_approver) == 0 else "fail",
            "observed_value": f"Single-approver chains: {len(single_approver)}",
        }

    # User activity logging
    if ctrl_id == "WD-LOG-001":
        val = _bool_val(_xml_text(xml_str, "User_Activity_Logging_Enabled"))
        return {
            "observed": {"User_Activity_Logging_Enabled": val},
            "expected": "User_Activity_Logging_Enabled=true",
            "status": "pass" if val else "fail",
            "observed_value": f"User_Activity_Logging_Enabled={val}",
        }

    # Log accessibility checks (WD-LOG-002, WD-LOG-004): partial with data
    if ctrl_id in ("WD-LOG-002", "WD-LOG-004"):
        count = len(_xml_all_texts(xml_str, "Audit_Log_Entry") + _xml_all_texts(xml_str, "Sign_On_Event"))
        return {
            "observed": {"log_entries_accessible": count},
            "expected": "Audit logs accessible and non-empty",
            "status": "pass" if count > 0 else "partial",
            "observed_value": f"Log entries accessible: {count}",
        }

    # Security group sensitive domain access (WD-DSP-001, WD-DSP-004)
    if ctrl_id in ("WD-DSP-001", "WD-DSP-004"):
        members = _xml_all_texts(xml_str, "Security_Group_Member")
        return {
            "observed": {"sensitive_domain_members": len(members)},
            "expected": "Sensitive domain access limited to documented groups",
            "status": "partial",
            "observed_value": f"Security group members in sensitive domains: {len(members)}",
            "notes": "Human review required to verify all members are authorized",
        }

    # Data export permissions
    if ctrl_id == "WD-DSP-002":
        val = _bool_val(_xml_text(xml_str, "Allow_Data_Export"))
        return {
            "observed": {"Allow_Data_Export": val},
            "expected": "Allow_Data_Export restricted",
            "status": "fail" if val else "pass",
            "observed_value": f"Allow_Data_Export={val}",
        }

    # API client data access (WD-DSP-003)
    if ctrl_id == "WD-DSP-003":
        broad = _xml_all_texts(xml_str, "All_Workday_Data")
        return {
            "observed": {"broad_access_clients": len(broad)},
            "expected": "No integrations with All_Workday_Data scope",
            "status": "fail" if broad else "pass",
            "observed_value": f"Integrations with broad data scope: {len(broad)}",
        }

    # Fallback: return partial with raw XML excerpt
    return {
        "status": "partial",
        "observed": {},
        "observed_value": xml_str[:200] if xml_str else "no response",
        "notes": f"No specific assessment rule for {ctrl_id}; manual review required",
    }


# ---------------------------------------------------------------------------
# Per-method collectors
# ---------------------------------------------------------------------------


def collect_soap(
    ctrl: dict[str, Any],
    base_url: str,
    tenant: str,
    token: str,
    api_version: str,
) -> dict[str, Any]:
    """Collect via SOAP WWS. Returns partial finding dict."""
    service = ctrl["soap_service"]
    operation = ctrl["soap_operation"]
    status_code, xml_str = call_soap(base_url, tenant, service, operation, token, api_version)

    if status_code == 403:
        return {
            "status": "partial",
            "observed_value": None,
            "evidence_source": f"{operation} — SOAP (permission denied)",
            "platform_data": {
                "collection_method": "soap",
                "http_status": status_code,
                "soap_error": "PERMISSION_DENIED: domain not granted to ISSG",
            },
        }

    if status_code != 200:
        return {
            "status": "partial",
            "observed_value": None,
            "evidence_source": f"{operation} — SOAP HTTP {status_code}",
            "platform_data": {"collection_method": "soap", "http_status": status_code},
        }

    assessed = _assess_soap_result(ctrl["id"], xml_str)
    return {
        "status": assessed.get("status", "partial"),
        "observed_value": assessed.get("observed_value"),
        "expected_value": assessed.get("expected"),
        "notes": assessed.get("notes"),
        "evidence_source": f"workday-connect://soap/{service}/{operation}",
        "platform_data": {
            "collection_method": "soap",
            "soap_service": service,
            "soap_operation": operation,
            "http_status": status_code,
            "raw_fields": assessed.get("observed", {}),
        },
    }


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
    _soap_cache.clear()  # fresh cache per run

    controls = load_catalog()
    domain_map = load_sscf_domain_map()

    findings: list[dict[str, Any]] = []
    for ctrl in controls:
        method = ctrl["collection_method"]

        if method in ("soap", "soap+oauth"):
            raw = collect_soap(ctrl, base_url, tenant, token, api_version)
        elif method == "raas":
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
        "assessment_id": f"wd-assess-{datetime.now(UTC).strftime('%Y%m%d')}-001",
        "platform": "workday",
        "oscal_catalog_ref": "config/workday/workday_catalog.json",
        "assessment_time_utc": now_utc,
        "environment": env,
        "assessor": f"workday-connect v{_VERSION}",
        "assessment_owner": assessment_owner,
        "data_source": f"workday-connect SOAP WWS {api_version} + RaaS",
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
        op = ctrl.get("soap_operation") or ctrl.get("raas_report") or ctrl.get("rest_endpoint") or "(manual)"
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
