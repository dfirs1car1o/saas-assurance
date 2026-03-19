"""Tests for skills/oscal_assess/oscal_assess.py.

Covers pure helper functions, all assessment rule branches, run_assessment /
run_workday_assessment, and the CLI (dry-run and error paths).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from click.testing import CliRunner

from skills.oscal_assess.oscal_assess import (
    RULES,
    Finding,
    _auto_due_date,
    _na,
    _normalize_assessment_owner,
    _normalize_data_source,
    _records,
    _rule_acs_001,
    _rule_acs_002,
    _rule_acs_003,
    _rule_acs_004,
    _rule_auth_001,
    _rule_auth_002,
    _rule_auth_003,
    _rule_auth_004,
    _rule_data_004,
    _rule_dep_003,
    _rule_int_002,
    _rule_int_003,
    _rule_int_004,
    _rule_oauth_001,
    _rule_oauth_002,
    _rule_secconf_001,
    _rule_secconf_002,
    _scope,
    _total,
    cli,
    run_assessment,
    run_workday_assessment,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)

_MINIMAL_CONTROLS = [
    {"control_id": "SBS-AUTH-001", "risk_level": "Critical"},
    {"control_id": "SBS-ACS-001", "risk_level": "High"},
    {"control_id": "SBS-INT-002", "risk_level": "Moderate"},
]

_MINIMAL_SSCF_INDEX: dict = {}


def _controls_json(controls: list[dict]) -> str:
    return json.dumps({"controls": controls})


def _soql(records: list[dict], total: int | None = None) -> dict:
    return {"records": records, "totalSize": total if total is not None else len(records)}


# ---------------------------------------------------------------------------
# _auto_due_date
# ---------------------------------------------------------------------------


class TestAutoDueDate:
    def test_pass_returns_empty(self) -> None:
        assert _auto_due_date("critical", "pass", _NOW) == ""

    def test_not_applicable_returns_empty(self) -> None:
        assert _auto_due_date("high", "not_applicable", _NOW) == ""

    def test_fail_critical_returns_7_days(self) -> None:
        result = _auto_due_date("critical", "fail", _NOW)
        assert result != ""
        from datetime import timedelta

        expected = (_NOW + timedelta(days=7)).strftime("%Y-%m-%d")
        assert result == expected

    def test_fail_high_returns_30_days(self) -> None:
        result = _auto_due_date("high", "fail", _NOW)
        from datetime import timedelta

        expected = (_NOW + timedelta(days=30)).strftime("%Y-%m-%d")
        assert result == expected

    def test_partial_moderate_returns_90_days(self) -> None:
        result = _auto_due_date("moderate", "partial", _NOW)
        from datetime import timedelta

        expected = (_NOW + timedelta(days=90)).strftime("%Y-%m-%d")
        assert result == expected

    def test_fail_low_returns_180_days(self) -> None:
        result = _auto_due_date("low", "fail", _NOW)
        from datetime import timedelta

        expected = (_NOW + timedelta(days=180)).strftime("%Y-%m-%d")
        assert result == expected

    def test_unknown_severity_defaults_to_90(self) -> None:
        result = _auto_due_date("unknown_sev", "fail", _NOW)
        from datetime import timedelta

        expected = (_NOW + timedelta(days=90)).strftime("%Y-%m-%d")
        assert result == expected


# ---------------------------------------------------------------------------
# _normalize_assessment_owner
# ---------------------------------------------------------------------------


class TestNormalizeAssessmentOwner:
    def test_none_returns_default(self) -> None:
        assert _normalize_assessment_owner(None) == "SaaS Security Architect"

    def test_empty_returns_default(self) -> None:
        assert _normalize_assessment_owner("") == "SaaS Security Architect"

    def test_whitespace_returns_default(self) -> None:
        assert _normalize_assessment_owner("   ") == "SaaS Security Architect"

    def test_unknown_returns_default(self) -> None:
        assert _normalize_assessment_owner("unknown") == "SaaS Security Architect"

    def test_real_name_passes_through(self) -> None:
        assert _normalize_assessment_owner("Jane Smith") == "Jane Smith"

    def test_strips_whitespace(self) -> None:
        assert _normalize_assessment_owner("  Alice  ") == "Alice"


# ---------------------------------------------------------------------------
# _normalize_data_source
# ---------------------------------------------------------------------------


class TestNormalizeDataSource:
    def test_dry_run_always_returns_stub(self) -> None:
        assert _normalize_data_source(True) == "dry_run_stub"

    def test_dry_run_ignores_source(self) -> None:
        assert _normalize_data_source(True, "live_api") == "dry_run_stub"

    def test_live_api_passes_through(self) -> None:
        assert _normalize_data_source(False, "live_api") == "live_api"

    def test_manual_questionnaire_passes_through(self) -> None:
        assert _normalize_data_source(False, "manual_questionnaire") == "manual_questionnaire"

    def test_unknown_source_defaults_to_live_api(self) -> None:
        assert _normalize_data_source(False, "live-collection") == "live_api"

    def test_none_source_defaults_to_live_api(self) -> None:
        assert _normalize_data_source(False, None) == "live_api"

    def test_empty_source_defaults_to_live_api(self) -> None:
        assert _normalize_data_source(False, "") == "live_api"


# ---------------------------------------------------------------------------
# _na, _scope, _total, _records
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_na_basic(self) -> None:
        f = _na("SBS-X-001", "critical")
        assert f.control_id == "SBS-X-001"
        assert f.status == "not_applicable"
        assert f.severity == "critical"

    def test_na_custom_reason(self) -> None:
        f = _na("SBS-X-001", "high", "test reason")
        assert f.observed_value == "test reason"

    def test_scope_named(self) -> None:
        raw = {"auth": {"key": "value"}}
        assert _scope(raw, "auth") == {"key": "value"}

    def test_scope_unnamed_fallback(self) -> None:
        raw = {"key": "value"}
        assert _scope(raw, "auth") == {"key": "value"}

    def test_scope_empty_raw(self) -> None:
        assert _scope({}, "auth") is None

    def test_total_from_dict(self) -> None:
        assert _total({"totalSize": 5, "records": []}) == 5

    def test_total_missing_key(self) -> None:
        assert _total({"records": []}) == 0

    def test_total_non_dict(self) -> None:
        assert _total("not a dict") == 0

    def test_records_from_dict(self) -> None:
        recs = [{"id": 1}, {"id": 2}]
        assert _records({"records": recs, "totalSize": 2}) == recs

    def test_records_filters_non_dicts(self) -> None:
        assert _records({"records": [{"id": 1}, "bad", None]}) == [{"id": 1}]

    def test_records_non_dict(self) -> None:
        assert _records("not a dict") == []


# ---------------------------------------------------------------------------
# Finding.to_dict
# ---------------------------------------------------------------------------


class TestFindingToDict:
    def test_basic_serialization(self) -> None:
        f = Finding("SBS-AUTH-001", "fail", "critical", "No SSO")
        d = f.to_dict("my-org", "dev", "2026-01-01")
        assert d["control_id"] == "SBS-AUTH-001"
        assert d["status"] == "fail"
        assert d["severity"] == "critical"
        assert "evidence_ref" in d

    def test_needs_expert_review_included_when_true(self) -> None:
        f = Finding("SBS-ACS-005", "partial", "high", "needs review", needs_expert_review=True)
        d = f.to_dict("org", "dev", "2026-01-01")
        assert d["needs_expert_review"] is True

    def test_needs_expert_review_absent_when_false(self) -> None:
        f = Finding("SBS-AUTH-001", "pass", "critical", "ok")
        d = f.to_dict("org", "dev", "2026-01-01")
        assert "needs_expert_review" not in d


# ---------------------------------------------------------------------------
# Auth rules
# ---------------------------------------------------------------------------


class TestRuleAuth001:
    def test_no_scope(self) -> None:
        f = _rule_auth_001({})
        assert f.status == "not_applicable"

    def test_no_providers(self) -> None:
        raw = {"auth": {"sso_providers": _soql([])}}
        f = _rule_auth_001(raw)
        assert f.status == "fail"

    def test_providers_none_enabled(self) -> None:
        raw = {"auth": {"sso_providers": _soql([{"IsEnabled": False}])}}
        f = _rule_auth_001(raw)
        assert f.status == "partial"

    def test_providers_enabled(self) -> None:
        raw = {"auth": {"sso_providers": _soql([{"IsEnabled": True}])}}
        f = _rule_auth_001(raw)
        assert f.status == "pass"


class TestRuleAuth002:
    def test_no_scope(self) -> None:
        assert _rule_auth_002({}).status == "not_applicable"

    def test_no_sso(self) -> None:
        raw = {"auth": {"sso_providers": _soql([]), "login_ip_ranges": _soql([], 0)}}
        assert _rule_auth_002(raw).status == "partial"

    def test_sso_no_ip_ranges(self) -> None:
        raw = {"auth": {"sso_providers": _soql([{"IsEnabled": True}]), "login_ip_ranges": _soql([], 0)}}
        assert _rule_auth_002(raw).status == "partial"

    def test_sso_with_ip_ranges(self) -> None:
        raw = {"auth": {"sso_providers": _soql([{"IsEnabled": True}]), "login_ip_ranges": _soql([], 2)}}
        assert _rule_auth_002(raw).status == "pass"


class TestRuleAuth003:
    def test_no_scope(self) -> None:
        assert _rule_auth_003({}).status == "not_applicable"

    def test_no_ranges(self) -> None:
        raw = {"auth": {"login_ip_ranges": _soql([], 0)}}
        assert _rule_auth_003(raw).status == "fail"

    def test_few_ranges(self) -> None:
        raw = {"auth": {"login_ip_ranges": _soql([], 2)}}
        assert _rule_auth_003(raw).status == "partial"

    def test_sufficient_ranges(self) -> None:
        raw = {"auth": {"login_ip_ranges": _soql([], 5)}}
        assert _rule_auth_003(raw).status == "pass"


class TestRuleAuth004:
    def test_no_scope(self) -> None:
        assert _rule_auth_004({}).status == "not_applicable"

    def test_api_error(self) -> None:
        raw = {"auth": {"mfa_org_settings": {"error": "Access denied"}}}
        assert _rule_auth_004(raw).status == "partial"

    def test_mfa_enabled(self) -> None:
        raw = {
            "auth": {
                "mfa_org_settings": _soql(
                    [{"MultiFactorAuthenticationForUserUI": True}]
                )
            }
        }
        assert _rule_auth_004(raw).status == "pass"

    def test_mfa_not_enabled(self) -> None:
        raw = {
            "auth": {
                "mfa_org_settings": _soql(
                    [{"MultiFactorAuthenticationForUserUI": False}]
                )
            }
        }
        assert _rule_auth_004(raw).status == "partial"

    def test_no_records(self) -> None:
        raw = {"auth": {"mfa_org_settings": _soql([])}}
        assert _rule_auth_004(raw).status == "partial"


# ---------------------------------------------------------------------------
# Access control rules
# ---------------------------------------------------------------------------


class TestRuleAcs001:
    def test_no_scope(self) -> None:
        assert _rule_acs_001({}).status == "not_applicable"

    def test_too_many_admin_profiles(self) -> None:
        raw = {"access": {"admin_profiles": _soql([], 6)}}
        assert _rule_acs_001(raw).status == "fail"

    def test_moderate_admin_profiles(self) -> None:
        raw = {"access": {"admin_profiles": _soql([], 3)}}
        assert _rule_acs_001(raw).status == "partial"

    def test_acceptable_admin_profiles(self) -> None:
        raw = {"access": {"admin_profiles": _soql([], 2)}}
        assert _rule_acs_001(raw).status == "pass"


class TestRuleAcs002:
    def test_no_scope(self) -> None:
        assert _rule_acs_002({}).status == "not_applicable"

    def test_too_many_perm_sets(self) -> None:
        raw = {"access": {"elevated_permission_sets": _soql([], 11)}}
        assert _rule_acs_002(raw).status == "fail"

    def test_moderate_perm_sets(self) -> None:
        raw = {"access": {"elevated_permission_sets": _soql([], 5)}}
        assert _rule_acs_002(raw).status == "partial"

    def test_acceptable_perm_sets(self) -> None:
        raw = {"access": {"elevated_permission_sets": _soql([], 3)}}
        assert _rule_acs_002(raw).status == "pass"


class TestRuleAcs003:
    def test_no_scope(self) -> None:
        assert _rule_acs_003({}).status == "not_applicable"

    def test_no_apps(self) -> None:
        raw = {"access": {"connected_apps": _soql([])}}
        assert _rule_acs_003(raw).status == "pass"

    def test_all_unrestricted(self) -> None:
        raw = {
            "access": {
                "connected_apps": _soql(
                    [{"OptionsAllowAdminApprovedUsersOnly": False}]
                )
            }
        }
        assert _rule_acs_003(raw).status == "fail"

    def test_some_unrestricted(self) -> None:
        raw = {
            "access": {
                "connected_apps": _soql(
                    [
                        {"OptionsAllowAdminApprovedUsersOnly": True},
                        {"OptionsAllowAdminApprovedUsersOnly": False},
                    ]
                )
            }
        }
        assert _rule_acs_003(raw).status == "partial"

    def test_all_restricted(self) -> None:
        raw = {
            "access": {
                "connected_apps": _soql(
                    [{"OptionsAllowAdminApprovedUsersOnly": True}]
                )
            }
        }
        assert _rule_acs_003(raw).status == "pass"


class TestRuleAcs004:
    def test_no_scope(self) -> None:
        assert _rule_acs_004({}).status == "not_applicable"

    def test_many_super_admins(self) -> None:
        raw = {
            "access": {
                "admin_profiles": _soql(
                    [
                        {"PermissionsModifyAllData": True, "PermissionsManageUsers": True},
                        {"PermissionsModifyAllData": True, "PermissionsManageUsers": True},
                        {"PermissionsModifyAllData": True, "PermissionsManageUsers": True},
                    ]
                )
            }
        }
        assert _rule_acs_004(raw).status == "fail"

    def test_one_super_admin(self) -> None:
        raw = {
            "access": {
                "admin_profiles": _soql(
                    [{"PermissionsModifyAllData": True, "PermissionsManageUsers": True}]
                )
            }
        }
        assert _rule_acs_004(raw).status == "partial"

    def test_no_super_admins(self) -> None:
        raw = {
            "access": {
                "admin_profiles": _soql(
                    [{"PermissionsModifyAllData": False, "PermissionsManageUsers": True}]
                )
            }
        }
        assert _rule_acs_004(raw).status == "pass"


# ---------------------------------------------------------------------------
# Integration rules
# ---------------------------------------------------------------------------


class TestRuleInt002:
    def test_no_scope(self) -> None:
        assert _rule_int_002({}).status == "not_applicable"

    def test_active_insecure_sites(self) -> None:
        raw = {
            "integrations": {
                "remote_site_settings": _soql(
                    [{"DisableProtocolSecurity": True, "IsActive": True}]
                )
            }
        }
        assert _rule_int_002(raw).status == "fail"

    def test_inactive_insecure_sites(self) -> None:
        raw = {
            "integrations": {
                "remote_site_settings": _soql(
                    [{"DisableProtocolSecurity": True, "IsActive": False}]
                )
            }
        }
        assert _rule_int_002(raw).status == "partial"

    def test_all_secure(self) -> None:
        raw = {
            "integrations": {
                "remote_site_settings": _soql(
                    [{"DisableProtocolSecurity": False, "IsActive": True}]
                )
            }
        }
        assert _rule_int_002(raw).status == "pass"


class TestRuleInt003:
    def test_no_scope(self) -> None:
        assert _rule_int_003({}).status == "not_applicable"

    def test_no_named_credentials(self) -> None:
        raw = {"integrations": {"named_credentials": _soql([])}}
        assert _rule_int_003(raw).status == "partial"

    def test_has_named_credentials(self) -> None:
        raw = {"integrations": {"named_credentials": _soql([{"Id": "cred1"}])}}
        assert _rule_int_003(raw).status == "pass"


class TestRuleInt004:
    def test_no_scope(self) -> None:
        assert _rule_int_004({}).status == "not_applicable"

    def test_no_log_types(self) -> None:
        raw = {"event-monitoring": {"event_log_types": _soql([])}}
        assert _rule_int_004(raw).status == "fail"

    def test_log_types_no_api(self) -> None:
        raw = {
            "event-monitoring": {
                "event_log_types": _soql([{"EventType": "Login"}, {"EventType": "Report"}])
            }
        }
        assert _rule_int_004(raw).status == "partial"

    def test_api_log_types_present(self) -> None:
        raw = {
            "event-monitoring": {
                "event_log_types": _soql([{"EventType": "ApiEvent"}, {"EventType": "RestApi"}])
            }
        }
        assert _rule_int_004(raw).status == "pass"


# ---------------------------------------------------------------------------
# OAuth rules
# ---------------------------------------------------------------------------


class TestRuleOauth001:
    def test_no_scope(self) -> None:
        assert _rule_oauth_001({}).status == "not_applicable"

    def test_no_policies(self) -> None:
        raw = {"oauth": {"connected_app_oauth_policies": _soql([])}}
        assert _rule_oauth_001(raw).status == "pass"

    def test_all_open_access(self) -> None:
        raw = {
            "oauth": {
                "connected_app_oauth_policies": _soql(
                    [{"PermittedUsersPolicyEnum": "AllUsers"}]
                )
            }
        }
        assert _rule_oauth_001(raw).status == "fail"

    def test_some_open_access(self) -> None:
        raw = {
            "oauth": {
                "connected_app_oauth_policies": _soql(
                    [
                        {"PermittedUsersPolicyEnum": "AllUsers"},
                        {"PermittedUsersPolicyEnum": "AdminApprovedUsers"},
                    ]
                )
            }
        }
        assert _rule_oauth_001(raw).status == "partial"

    def test_all_controlled(self) -> None:
        raw = {
            "oauth": {
                "connected_app_oauth_policies": _soql(
                    [{"PermittedUsersPolicyEnum": "AdminApprovedUsers"}]
                )
            }
        }
        assert _rule_oauth_001(raw).status == "pass"


class TestRuleOauth002:
    def test_no_scope(self) -> None:
        assert _rule_oauth_002({}).status == "not_applicable"

    def test_no_policies(self) -> None:
        raw = {"oauth": {"connected_app_oauth_policies": _soql([])}}
        assert _rule_oauth_002(raw).status == "pass"

    def test_all_unrestricted(self) -> None:
        raw = {
            "oauth": {
                "connected_app_oauth_policies": _soql(
                    [{"OptionsAllowAdminApprovedUsersOnly": False}]
                )
            }
        }
        assert _rule_oauth_002(raw).status == "fail"

    def test_some_unrestricted(self) -> None:
        raw = {
            "oauth": {
                "connected_app_oauth_policies": _soql(
                    [
                        {"OptionsAllowAdminApprovedUsersOnly": True},
                        {"OptionsAllowAdminApprovedUsersOnly": False},
                    ]
                )
            }
        }
        assert _rule_oauth_002(raw).status == "partial"

    def test_all_restricted(self) -> None:
        raw = {
            "oauth": {
                "connected_app_oauth_policies": _soql(
                    [{"OptionsAllowAdminApprovedUsersOnly": True}]
                )
            }
        }
        assert _rule_oauth_002(raw).status == "pass"


# ---------------------------------------------------------------------------
# Data rule
# ---------------------------------------------------------------------------


class TestRuleData004:
    def test_no_scope(self) -> None:
        assert _rule_data_004({}).status == "not_applicable"

    def test_no_tracked_fields(self) -> None:
        raw = {"event-monitoring": {"field_history_retention": _soql([], 0)}}
        assert _rule_data_004(raw).status == "fail"

    def test_few_tracked_fields(self) -> None:
        raw = {"event-monitoring": {"field_history_retention": _soql([], 5)}}
        assert _rule_data_004(raw).status == "partial"

    def test_sufficient_tracked_fields(self) -> None:
        raw = {"event-monitoring": {"field_history_retention": _soql([], 15)}}
        assert _rule_data_004(raw).status == "pass"


# ---------------------------------------------------------------------------
# Security config rules
# ---------------------------------------------------------------------------


class TestRuleSecconf001:
    def test_no_scope(self) -> None:
        assert _rule_secconf_001({}).status == "not_applicable"

    def test_health_check_note(self) -> None:
        raw = {"secconf": {"health_check": {"note": "unavailable"}}}
        assert _rule_secconf_001(raw).status == "partial"

    def test_no_records(self) -> None:
        raw = {"secconf": {"health_check": _soql([])}}
        assert _rule_secconf_001(raw).status == "partial"

    def test_score_critical(self) -> None:
        raw = {"secconf": {"health_check": _soql([{"Score": 40}])}}
        assert _rule_secconf_001(raw).status == "fail"

    def test_score_below_threshold(self) -> None:
        raw = {"secconf": {"health_check": _soql([{"Score": 70}])}}
        assert _rule_secconf_001(raw).status == "partial"

    def test_score_passing(self) -> None:
        raw = {"secconf": {"health_check": _soql([{"Score": 85}])}}
        assert _rule_secconf_001(raw).status == "pass"


class TestRuleSecconf002:
    def test_no_scope(self) -> None:
        assert _rule_secconf_002({}).status == "not_applicable"

    def test_no_records(self) -> None:
        raw = {"secconf": {"health_check": _soql([])}}
        assert _rule_secconf_002(raw).status == "partial"

    def test_score_critical(self) -> None:
        raw = {"secconf": {"health_check": _soql([{"Score": 30}])}}
        assert _rule_secconf_002(raw).status == "fail"

    def test_score_below_threshold(self) -> None:
        raw = {"secconf": {"health_check": _soql([{"Score": 65}])}}
        assert _rule_secconf_002(raw).status == "partial"

    def test_score_passing(self) -> None:
        raw = {"secconf": {"health_check": _soql([{"Score": 90}])}}
        assert _rule_secconf_002(raw).status == "pass"


# ---------------------------------------------------------------------------
# Deployment rule
# ---------------------------------------------------------------------------


class TestRuleDep003:
    def test_no_scope(self) -> None:
        assert _rule_dep_003({}).status == "not_applicable"

    def test_no_policies(self) -> None:
        raw = {"transaction-security": {"policies": _soql([])}}
        assert _rule_dep_003(raw).status == "fail"

    def test_policies_none_enabled(self) -> None:
        raw = {"transaction-security": {"policies": _soql([{"IsEnabled": False}])}}
        assert _rule_dep_003(raw).status == "partial"

    def test_policies_enabled(self) -> None:
        raw = {"transaction-security": {"policies": _soql([{"IsEnabled": True}])}}
        assert _rule_dep_003(raw).status == "pass"


# ---------------------------------------------------------------------------
# RULES registry completeness
# ---------------------------------------------------------------------------


class TestRulesRegistry:
    def test_all_rule_callables(self) -> None:
        for cid, rule in RULES.items():
            assert callable(rule), f"{cid} rule is not callable"

    def test_not_collectable_rules_return_na(self) -> None:
        na_controls = ["SBS-INT-001", "SBS-DEP-001", "SBS-DEP-002", "SBS-CODE-001"]
        for cid in na_controls:
            if cid in RULES:
                result = RULES[cid]({})
                assert result.status == "not_applicable", f"{cid} should be not_applicable"

    def test_structural_acs_rules_return_partial_with_scope(self) -> None:
        raw = {"access": {"admin_profiles": _soql([])}}
        for cid in ["SBS-ACS-005", "SBS-ACS-006", "SBS-ACS-007", "SBS-ACS-008"]:
            result = RULES[cid](raw)
            assert result.status == "partial"
            assert result.needs_expert_review is True

    def test_structural_oauth_rules_return_partial_with_scope(self) -> None:
        raw = {"oauth": {"connected_app_oauth_policies": _soql([])}}
        for cid in ["SBS-OAUTH-003", "SBS-OAUTH-004"]:
            result = RULES[cid](raw)
            assert result.status == "partial"
            assert result.needs_expert_review is True

    def test_data_structural_rules_always_partial(self) -> None:
        for cid in ["SBS-DATA-001", "SBS-DATA-002", "SBS-DATA-003"]:
            result = RULES[cid]({})
            assert result.status == "partial"
            assert result.needs_expert_review is True


# ---------------------------------------------------------------------------
# run_assessment
# ---------------------------------------------------------------------------


class TestRunAssessment:
    def test_dry_run_returns_findings_for_all_controls(self) -> None:
        findings = run_assessment(None, _MINIMAL_CONTROLS, dry_run=True, org="test", env="dev")
        assert len(findings) == len(_MINIMAL_CONTROLS)

    def test_dry_run_findings_have_required_fields(self) -> None:
        findings = run_assessment(None, _MINIMAL_CONTROLS, dry_run=True, org="test", env="dev")
        for f in findings:
            assert "control_id" in f
            assert "status" in f
            assert "severity" in f
            assert "evidence_ref" in f

    def test_live_run_with_empty_raw(self) -> None:
        findings = run_assessment({}, _MINIMAL_CONTROLS, dry_run=False, org="test", env="dev")
        assert len(findings) == len(_MINIMAL_CONTROLS)

    def test_unknown_control_gets_na(self) -> None:
        controls = [{"control_id": "SBS-UNKNOWN-999", "risk_level": "high"}]
        findings = run_assessment({}, controls, dry_run=False, org="test", env="dev")
        assert findings[0]["status"] == "not_applicable"

    def test_due_date_auto_populated_for_fail(self) -> None:
        controls = [{"control_id": "SBS-AUTH-001", "risk_level": "critical"}]
        # dry-run SBS-AUTH-001 → fail
        findings = run_assessment(None, controls, dry_run=True, org="test", env="dev")
        assert findings[0]["due_date"] != ""

    def test_dry_run_expert_controls_flagged(self) -> None:
        controls = [{"control_id": "SBS-ACS-005", "risk_level": "high"}]
        findings = run_assessment(None, controls, dry_run=True, org="test", env="dev")
        assert findings[0].get("needs_expert_review") is True

    def test_live_run_passes_raw_to_rules(self) -> None:
        raw = {
            "auth": {
                "sso_providers": _soql([{"IsEnabled": True}]),
                "login_ip_ranges": _soql([], 0),
                "mfa_org_settings": _soql([]),
            }
        }
        controls = [{"control_id": "SBS-AUTH-001", "risk_level": "critical"}]
        findings = run_assessment(raw, controls, dry_run=False, org="test", env="dev")
        assert findings[0]["status"] == "pass"


# ---------------------------------------------------------------------------
# run_workday_assessment
# ---------------------------------------------------------------------------


class TestRunWorkdayAssessment:
    def _load_real_sscf_index(self) -> dict:
        repo_root = Path(__file__).resolve().parents[1]
        index_path = repo_root / "config" / "sscf_control_index.yaml"
        with index_path.open() as fh:
            data = yaml.safe_load(fh)
        return {c["sscf_control_id"]: c for c in data.get("controls", [])}

    def test_returns_list_of_findings(self) -> None:
        sscf_index = self._load_real_sscf_index()
        findings = run_workday_assessment("acme-workday", "dev", sscf_index)
        assert isinstance(findings, list)
        assert len(findings) > 0

    def test_findings_have_required_fields(self) -> None:
        sscf_index = self._load_real_sscf_index()
        findings = run_workday_assessment("acme-workday", "dev", sscf_index)
        for f in findings:
            assert "control_id" in f
            assert "status" in f
            assert "severity" in f
            assert "evidence_ref" in f

    def test_fail_findings_have_due_date(self) -> None:
        sscf_index = self._load_real_sscf_index()
        findings = run_workday_assessment("acme-workday", "dev", sscf_index)
        fails = [f for f in findings if f["status"] == "fail"]
        assert all(f["due_date"] != "" for f in fails)

    def test_empty_sscf_index_produces_findings(self) -> None:
        findings = run_workday_assessment("acme-workday", "dev", {})
        valid_statuses = {"pass", "fail", "partial", "not_applicable"}
        assert all(f["status"] in valid_statuses for f in findings)


# ---------------------------------------------------------------------------
# CLI — assess command
# ---------------------------------------------------------------------------


class TestCliAssess:
    def _controls_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "sbs_controls.json"
        path.write_text(_controls_json(_MINIMAL_CONTROLS))
        return path

    def _extract_json(self, output: str) -> dict:
        """Extract the trailing JSON object from mixed stderr+stdout CliRunner output."""
        # stderr is mixed in; the JSON block starts at the first '\n{\n' (newline then brace)
        idx = output.find("\n{\n")
        assert idx != -1, f"No JSON block found in output: {output!r}"
        return json.loads(output[idx + 1 :])

    def test_dry_run_salesforce_stdout(self, tmp_path: Path) -> None:
        controls = self._controls_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "assess",
                "--dry-run",
                "--controls",
                str(controls),
                "--platform",
                "salesforce",
            ],
        )
        assert result.exit_code == 0
        payload = self._extract_json(result.output)
        assert payload["schema_version"] == "2.0"
        assert payload["platform"] == "salesforce"
        assert payload["data_source"] == "dry_run_stub"
        assert isinstance(payload["findings"], list)

    def test_dry_run_writes_to_file(self, tmp_path: Path) -> None:
        controls = self._controls_file(tmp_path)
        out_file = tmp_path / "gap.json"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "assess",
                "--dry-run",
                "--controls",
                str(controls),
                "--platform",
                "salesforce",
                "--out",
                str(out_file),
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        payload = json.loads(out_file.read_text())
        assert payload["schema_version"] == "2.0"

    def test_dry_run_workday(self, tmp_path: Path) -> None:
        controls = self._controls_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "assess",
                "--dry-run",
                "--controls",
                str(controls),
                "--platform",
                "workday",
            ],
        )
        assert result.exit_code == 0
        payload = self._extract_json(result.output)
        assert payload["platform"] == "workday"
        assert payload["data_source"] == "dry_run_stub"

    def test_missing_collector_output_errors(self, tmp_path: Path) -> None:
        controls = self._controls_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "assess",
                "--controls",
                str(controls),
                "--platform",
                "salesforce",
            ],
        )
        assert result.exit_code != 0 or "ERROR" in result.output

    def test_assessment_owner_normalised(self, tmp_path: Path) -> None:
        controls = self._controls_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "assess",
                "--dry-run",
                "--controls",
                str(controls),
                "--platform",
                "salesforce",
                "--assessment-owner",
                "unknown",
            ],
        )
        assert result.exit_code == 0
        payload = self._extract_json(result.output)
        assert payload["assessment_owner"] == "SaaS Security Architect"

    def test_live_missing_collector_workday_errors(self, tmp_path: Path) -> None:
        controls = self._controls_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "assess",
                "--controls",
                str(controls),
                "--platform",
                "workday",
            ],
        )
        assert result.exit_code != 0 or "ERROR" in result.output

    def test_missing_controls_file_errors(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "assess",
                "--dry-run",
                "--controls",
                str(tmp_path / "does_not_exist.json"),
                "--platform",
                "salesforce",
            ],
        )
        assert result.exit_code != 0 or "ERROR" in result.output
