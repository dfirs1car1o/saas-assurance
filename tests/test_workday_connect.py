"""
tests/test_workday_connect.py — Unit tests for workday_connect.

Uses `responses` library to intercept HTTP calls — no live Workday tenant required.
All tests run in CI with no network access.
"""

from __future__ import annotations

import re

import pytest
import responses as resp_lib

from skills.workday_connect.workday_connect import (
    clear_token_cache,
    collect_manual,
    collect_raas,
    collect_rest,
    get_oauth_token,
    load_catalog,
    print_dry_run_plan,
    run_collect,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TOKEN_URL = "https://acme.workday.com/ccx/oauth2/acme/token"
BASE_URL = "https://acme.workday.com"
TENANT = "acme"
API_VERSION = "v40.0"
FAKE_TOKEN = "fake-access-token-abc123"


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear OAuth token cache before each test."""
    clear_token_cache()
    yield


def _token_stub():
    resp_lib.add(
        resp_lib.POST,
        TOKEN_URL,
        json={"access_token": FAKE_TOKEN, "expires_in": 3600},
        status=200,
    )


def _make_ctrl(ctrl_id: str, method: str = "manual") -> dict:
    return {
        "id": ctrl_id,
        "title": f"Test control {ctrl_id}",
        "group_id": "con",
        "severity": "high",
        "collection_method": method,
        "raas_report": "Test_Report",
        "rest_endpoint": "/staffing/v6/workers",
        "sscf_control": "SSCF-IAM-001",
    }


# ---------------------------------------------------------------------------
# OAuth token tests
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_get_oauth_token_success():
    _token_stub()
    token = get_oauth_token("client-id", "client-secret", TOKEN_URL)
    assert token == FAKE_TOKEN
    assert len(resp_lib.calls) == 1


@resp_lib.activate
def test_get_oauth_token_cached():
    """Second call should use cache — only one HTTP request fired."""
    _token_stub()
    t1 = get_oauth_token("client-id", "client-secret", TOKEN_URL)
    t2 = get_oauth_token("client-id", "client-secret", TOKEN_URL)
    assert t1 == t2 == FAKE_TOKEN
    assert len(resp_lib.calls) == 1  # cached — no second request


@resp_lib.activate
def test_get_oauth_token_failure():
    resp_lib.add(resp_lib.POST, TOKEN_URL, status=401, json={"error": "unauthorized"})
    with pytest.raises(RuntimeError, match="OAuth token acquisition failed"):
        get_oauth_token("bad-id", "bad-secret", TOKEN_URL)


# ---------------------------------------------------------------------------
# Catalog tests
# ---------------------------------------------------------------------------


def test_load_catalog_returns_30_controls():
    controls = load_catalog()
    assert len(controls) == 30, f"Expected 30 controls, got {len(controls)}"


def test_load_catalog_all_have_required_fields():
    controls = load_catalog()
    for ctrl in controls:
        assert "id" in ctrl
        assert "collection_method" in ctrl
        assert ctrl["collection_method"] in ("raas", "rest", "manual"), (
            f"{ctrl['id']} has unexpected method: {ctrl['collection_method']}"
        )


def test_load_catalog_no_soap_controls():
    """SOAP has been removed — no control should use soap or soap+oauth."""
    controls = load_catalog()
    soap_controls = [c for c in controls if "soap" in c["collection_method"]]
    assert soap_controls == [], f"Found unexpected soap controls: {[c['id'] for c in soap_controls]}"


# ---------------------------------------------------------------------------
# collect_raas tests
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_collect_raas_not_configured():
    raas_url = f"{BASE_URL}/ccx/service/customreport2/{TENANT}/Test_Report?format=json"
    resp_lib.add(resp_lib.GET, raas_url, status=404)
    ctrl = _make_ctrl("WD-IAM-001", method="raas")
    result = collect_raas(ctrl, BASE_URL, TENANT, FAKE_TOKEN)
    assert result["status"] == "not_applicable"
    assert result["platform_data"]["raas_available"] is False


@resp_lib.activate
def test_collect_raas_success():
    raas_url = f"{BASE_URL}/ccx/service/customreport2/{TENANT}/Test_Report?format=json"
    resp_lib.add(resp_lib.GET, raas_url, status=200, json={"Report_Entry": [{"id": "grp1"}, {"id": "grp2"}]})
    ctrl = _make_ctrl("WD-IAM-001", method="raas")
    result = collect_raas(ctrl, BASE_URL, TENANT, FAKE_TOKEN)
    assert result["status"] == "partial"
    assert result["platform_data"]["record_count"] == 2


# ---------------------------------------------------------------------------
# collect_rest tests
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_collect_rest_workers():
    rest_url = f"{BASE_URL}/ccx/api/staffing/v6/workers"
    resp_lib.add(resp_lib.GET, rest_url, status=200, json={"data": [{"id": "w1"}, {"id": "w2"}]})
    ctrl = _make_ctrl("WD-IAM-007", method="rest")
    ctrl["rest_endpoint"] = "/staffing/v6/workers"
    result = collect_rest(ctrl, BASE_URL, FAKE_TOKEN)
    assert result["status"] == "partial"
    assert result["platform_data"]["worker_count"] == 2


# ---------------------------------------------------------------------------
# collect_manual test
# ---------------------------------------------------------------------------


def test_collect_manual_not_applicable():
    ctrl = _make_ctrl("WD-CKM-002", method="manual")
    ctrl["title"] = "BYOK Key Management"
    result = collect_manual(ctrl)
    assert result["status"] == "not_applicable"
    assert "BYOK" in result["platform_data"]["collection_method_note"]


# ---------------------------------------------------------------------------
# dry-run test
# ---------------------------------------------------------------------------


def test_dry_run_prints_plan(capsys):
    print_dry_run_plan("acme_dpt1", "acme-dry-run")
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out
    assert "acme_dpt1" in captured.out
    assert "WD-IAM-001" in captured.out
    assert "WD-CKM-002" in captured.out


# ---------------------------------------------------------------------------
# Full run_collect integration test (mocked HTTP)
# ---------------------------------------------------------------------------


@resp_lib.activate
def test_run_collect_writes_output(tmp_path):
    # Stub REST endpoint
    rest_url = f"{BASE_URL}/ccx/api/staffing/v6/workers"
    resp_lib.add(resp_lib.GET, rest_url, status=200, json={"data": []})

    # Stub all RaaS endpoints as 404 (not pre-configured)
    resp_lib.add(resp_lib.GET, re.compile(r".*/customreport2/.*"), status=404)

    out_path = tmp_path / "workday_raw.json"
    output = run_collect(BASE_URL, TENANT, FAKE_TOKEN, API_VERSION, "test-org", "dev", "Test Owner", out_path)

    assert out_path.exists()
    assert output["schema_version"] == "2.0"
    assert output["platform"] == "workday"
    assert len(output["findings"]) == 30
    # Manual controls are not_applicable
    ckm2 = next(f for f in output["findings"] if f["control_id"] == "WD-CKM-002")
    assert ckm2["status"] == "not_applicable"
    # Previously-soap controls are now manual/not_applicable
    con001 = next(f for f in output["findings"] if f["control_id"] == "WD-CON-001")
    assert con001["status"] == "not_applicable"
