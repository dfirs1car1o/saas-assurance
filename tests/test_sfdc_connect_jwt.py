"""
Unit tests for JWT Bearer Auth in sfdc-connect.
No live Salesforce org required.
"""

from __future__ import annotations

import pytest


def test_resolve_auth_method_cli_flag(monkeypatch):
    """CLI flag 'jwt' is accepted."""
    from skills.sfdc_connect.sfdc_connect import AUTH_METHOD_JWT, _resolve_auth_method

    monkeypatch.delenv("SF_AUTH_METHOD", raising=False)
    assert _resolve_auth_method("jwt") == AUTH_METHOD_JWT


def test_resolve_auth_method_env_var(monkeypatch):
    """Env var used when no CLI flag."""
    from skills.sfdc_connect.sfdc_connect import AUTH_METHOD_JWT, _resolve_auth_method

    monkeypatch.setenv("SF_AUTH_METHOD", "jwt")
    assert _resolve_auth_method(None) == AUTH_METHOD_JWT


def test_resolve_auth_method_default_jwt(monkeypatch):
    """Default is jwt when neither CLI flag nor env var is set."""
    from skills.sfdc_connect.sfdc_connect import AUTH_METHOD_JWT, _resolve_auth_method

    monkeypatch.delenv("SF_AUTH_METHOD", raising=False)
    assert _resolve_auth_method(None) == AUTH_METHOD_JWT


def test_resolve_auth_method_rejects_soap(monkeypatch):
    """SOAP is no longer a valid auth method."""
    from skills.sfdc_connect.sfdc_connect import _resolve_auth_method

    monkeypatch.delenv("SF_AUTH_METHOD", raising=False)
    with pytest.raises(SystemExit):
        _resolve_auth_method("soap")


def test_check_env_jwt_missing_vars(monkeypatch):
    """_check_env exits 1 when required JWT env vars are absent."""
    from skills.sfdc_connect.sfdc_connect import _check_env

    monkeypatch.delenv("SF_USERNAME", raising=False)
    monkeypatch.delenv("SF_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("SF_PRIVATE_KEY_PATH", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        _check_env()
    assert exc_info.value.code == 1


def test_auth_dry_run_jwt(monkeypatch):
    """auth --dry-run fails when JWT-specific vars are absent."""
    from click.testing import CliRunner

    from skills.sfdc_connect.sfdc_connect import cli

    monkeypatch.setenv("SF_USERNAME", "test@example.com")
    monkeypatch.delenv("SF_AUTH_METHOD", raising=False)
    monkeypatch.delenv("SF_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("SF_PRIVATE_KEY_PATH", raising=False)

    runner = CliRunner()
    result = runner.invoke(cli, ["auth", "--dry-run"])
    assert result.exit_code != 0
