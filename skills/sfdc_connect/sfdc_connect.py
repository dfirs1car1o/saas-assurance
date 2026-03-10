"""
sfdc-connect — Salesforce org configuration collector for OSCAL/SBS/SSCF assessment.

Read-only. Never writes to any Salesforce org. Credentials sourced from environment only.
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
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Auth constants
# ---------------------------------------------------------------------------

AUTH_METHOD_JWT = "jwt"
VALID_AUTH_METHODS = (AUTH_METHOD_JWT,)

REQUIRED_ENV_JWT = ("SF_USERNAME", "SF_CONSUMER_KEY", "SF_PRIVATE_KEY_PATH")

JWT_EXPIRY_SECONDS = 300  # Salesforce max: 5 min
JWT_REQUEST_TIMEOUT = 30  # seconds

_TOOLING_QUERY = "tooling/query"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _check_env() -> None:
    """Verify all required JWT env vars are present and private key file exists."""
    missing = [k for k in REQUIRED_ENV_JWT if not os.getenv(k)]
    if missing:
        click.echo(
            f"ERROR: Missing required env vars for JWT auth: {', '.join(missing)}\n"
            "See .env.example for the JWT Bearer Flow section.",
            err=True,
        )
        sys.exit(1)
    key_path = os.environ.get("SF_PRIVATE_KEY_PATH", "")
    if not Path(key_path).is_file():
        click.echo(
            f"ERROR: SF_PRIVATE_KEY_PATH does not exist or is not a file: {key_path}",
            err=True,
        )
        sys.exit(1)


def _resolve_auth_method(cli_flag: str | None) -> str:
    """Return the effective auth method: CLI flag > SF_AUTH_METHOD env > 'jwt'."""
    method = cli_flag or os.getenv("SF_AUTH_METHOD") or AUTH_METHOD_JWT
    if method not in VALID_AUTH_METHODS:
        click.echo(
            f"ERROR: Unknown auth method '{method}'. Only 'jwt' is supported.",
            err=True,
        )
        sys.exit(1)
    return method


def _connect_jwt() -> Any:
    """Return an authenticated Salesforce client using JWT Bearer Flow (read-only use only)."""
    try:
        import jwt as pyjwt
    except ImportError:
        click.echo("ERROR: PyJWT[crypto] not installed. Run: pip install 'PyJWT[crypto]>=2.8.0'", err=True)
        sys.exit(1)
    try:
        import requests
        from simple_salesforce import Salesforce
    except ImportError:
        click.echo("ERROR: simple-salesforce not installed. Run: uv pip install simple-salesforce", err=True)
        sys.exit(1)

    _check_env()

    key_path = os.environ["SF_PRIVATE_KEY_PATH"]
    try:
        private_key = Path(key_path).read_bytes()
    except FileNotFoundError:
        click.echo(f"ERROR: SF_PRIVATE_KEY_PATH not found: {key_path}", err=True)
        sys.exit(1)
    except OSError as exc:
        click.echo(f"ERROR: Could not read private key: {exc}", err=True)
        sys.exit(1)

    domain = os.environ.get("SF_DOMAIN", "login")
    # Hardcoded token endpoints — one branch per domain, no dynamic URL construction
    if domain == "test":
        token_url = "https://test.salesforce.com/services/oauth2/token"
        audience = "https://test.salesforce.com"
    else:
        token_url = "https://login.salesforce.com/services/oauth2/token"
        audience = "https://login.salesforce.com"

    claims = {
        "iss": os.environ["SF_CONSUMER_KEY"],
        "sub": os.environ["SF_USERNAME"],
        "aud": audience,
        "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
    }

    try:
        token = pyjwt.encode(claims, private_key, algorithm="RS256")
    except Exception as exc:
        click.echo(f"ERROR: JWT signing failed: {exc}", err=True)
        sys.exit(1)

    try:
        resp = requests.post(
            token_url,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": token},
            timeout=JWT_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.Timeout:
        click.echo("ERROR: JWT token request timed out", err=True)
        sys.exit(1)
    except requests.exceptions.HTTPError as exc:
        try:
            err_body = exc.response.json()
            click.echo(
                f"ERROR: JWT token request failed ({exc.response.status_code}): "
                f"{err_body.get('error_description', err_body)}",
                err=True,
            )
        except Exception:
            click.echo(f"ERROR: JWT token request failed: {exc}", err=True)
        sys.exit(1)
    except requests.exceptions.RequestException as exc:
        click.echo(f"ERROR: JWT network error: {exc}", err=True)
        sys.exit(1)

    access_token = result.get("access_token")
    instance_url = result.get("instance_url")
    if not access_token or not instance_url:
        click.echo(f"ERROR: JWT response missing access_token or instance_url: {result}", err=True)
        sys.exit(1)

    return Salesforce(instance_url=instance_url, session_id=access_token)


def _connect(auth_method: str | None = None) -> Any:
    """Return an authenticated Salesforce client using JWT Bearer Flow (read-only use only)."""
    _resolve_auth_method(auth_method)  # validates any explicit override
    return _connect_jwt()


def _result_envelope(org: str, env: str, scope: str, data: Any) -> dict:
    return {
        "org": org,
        "env": env,
        "collected_at_utc": datetime.now(UTC).isoformat(),
        "scope": scope,
        "raw": data,
    }


def _write_output(result: dict, out: str | None) -> None:
    payload = json.dumps(result, indent=2, default=str)
    if out:
        with open(out, "w") as f:
            f.write(payload)
        click.echo(f"Wrote {len(result.get('raw', {}))} items → {out}")
    else:
        click.echo(payload)


# ---------------------------------------------------------------------------
# Scope collectors
# ---------------------------------------------------------------------------


def collect_auth(sf: Any) -> dict:
    """Auth: SSO, MFA, login IP ranges, session settings."""
    data: dict[str, Any] = {}

    # Session settings via Tooling API — use Metadata blob (field names vary by API version)
    try:
        tooling_result = sf.restful(
            _TOOLING_QUERY,
            params={"q": "SELECT Metadata FROM SecuritySettings LIMIT 1"},
        )
        data["session_settings"] = tooling_result
    except Exception as exc:
        data["session_settings"] = {"error": str(exc), "note": "Requires Tooling API access"}

    # MFA enforcement via Tooling API (Identity Verification setting)
    try:
        mfa_result = sf.restful(
            _TOOLING_QUERY,
            params={
                "q": "SELECT MultiFactorAuthenticationForUserUI, MultiFactorAuthenticationForUserUIBlock"
                " FROM OrganizationSettings LIMIT 1"
            },
        )
        data["mfa_org_settings"] = mfa_result
    except Exception as exc:
        data["mfa_org_settings"] = {"error": str(exc), "note": "OrganizationSettings MFA fields require API v57+"}

    # Identity providers (SSO config)
    try:
        data["sso_providers"] = sf.query_all("SELECT Id, Name, SamlVersion, IsEnabled FROM SamlSsoConfig")
    except Exception:
        data["sso_providers"] = {"totalSize": 0, "records": []}

    # Login IP ranges (trusted IPs)
    try:
        data["login_ip_ranges"] = sf.query_all("SELECT Id, ProfileId, StartAddress, EndAddress FROM LoginIpRange")
    except Exception:
        data["login_ip_ranges"] = {"totalSize": 0, "records": []}

    # MFA: check if MFA is enforced via connected app or org setting
    try:
        data["mfa_policies"] = sf.query_all(
            "SELECT Id, DeveloperName, IsEnabled FROM TransactionSecurityPolicy WHERE ActionConfig LIKE '%TwoFactor%'"
        )
    except Exception:
        data["mfa_policies"] = {"totalSize": 0, "records": []}

    return data


def collect_access(sf: Any) -> dict:
    """Access: profiles with system admin, permission sets, connected apps."""
    data: dict[str, Any] = {}

    # Profiles with system admin or modify all data
    data["admin_profiles"] = sf.query_all(
        "SELECT Id, Name, PermissionsModifyAllData, PermissionsManageUsers, "
        "PermissionsViewAllData FROM Profile WHERE PermissionsModifyAllData = true "
        "OR PermissionsManageUsers = true ORDER BY Name"
    )

    # Permission sets with elevated permissions
    data["elevated_permission_sets"] = sf.query_all(
        "SELECT Id, Name, Label, PermissionsModifyAllData, PermissionsViewAllData, "
        "PermissionsManageUsers FROM PermissionSet WHERE PermissionsModifyAllData = true "
        "OR PermissionsManageUsers = true ORDER BY Name"
    )

    # Connected apps (OAuth clients)
    data["connected_apps"] = sf.query_all(
        "SELECT Id, Name, OptionsAllowAdminApprovedUsersOnly, OptionsRefreshTokenValidityMetric "
        "FROM ConnectedApplication ORDER BY Name"
    )

    return data


def collect_event_monitoring(sf: Any) -> dict:
    """Event Monitoring: storage, enabled event types."""
    data: dict[str, Any] = {}

    # Event log file types available (indicates what monitoring is enabled)
    data["event_log_types"] = sf.query_all(
        "SELECT EventType, LogDate, LogFileLength FROM EventLogFile "
        "WHERE LogDate = LAST_N_DAYS:7 ORDER BY LogDate DESC LIMIT 200"
    )

    # Check field audit trail / field history (metadata count as proxy)
    try:
        data["field_history_retention"] = sf.query_all(
            "SELECT Id, EntityDefinition.QualifiedApiName FROM FieldDefinition "
            "WHERE IsAiPredictionField = false AND IsHistoryTracked = true LIMIT 100"
        )
    except Exception:
        data["field_history_retention"] = {"totalSize": 0, "records": []}

    return data


def collect_transaction_security(sf: Any) -> dict:
    """Transaction Security Policies (automated threat response rules)."""
    return {
        "policies": sf.query_all(
            "SELECT Id, DeveloperName, EventName, ExecutionUserId, BlockMessage "
            "FROM TransactionSecurityPolicy ORDER BY EventName"
        )
    }


def collect_integrations(sf: Any) -> dict:
    """Named credentials and remote site settings (outbound integration points)."""
    data: dict[str, Any] = {}

    data["named_credentials"] = sf.query_all(
        "SELECT Id, DeveloperName, Endpoint FROM NamedCredential ORDER BY DeveloperName"
    )

    try:
        # RemoteProxy is a Tooling API metadata object — not queryable via standard SOQL
        _rss_query = (
            "SELECT Id, SiteName, EndpointUrl, IsActive, DisableProtocolSecurity FROM RemoteProxy ORDER BY SiteName"
        )
        tooling_result = sf.restful(_TOOLING_QUERY, params={"q": _rss_query})
        data["remote_site_settings"] = tooling_result
    except Exception as exc:
        data["remote_site_settings"] = {
            "totalSize": 0,
            "records": [],
            "note": f"RemoteSiteSettings not queryable via Tooling API ({exc}) — check Setup > Remote Site Settings",
        }

    return data


def collect_oauth(sf: Any) -> dict:
    """OAuth policies on connected apps."""
    return {
        "connected_app_oauth_policies": sf.query_all(
            "SELECT Id, Name, OptionsAllowAdminApprovedUsersOnly, OptionsRefreshTokenValidityMetric "
            "FROM ConnectedApplication ORDER BY Name"
        )
    }


def collect_secconf(sf: Any) -> dict:
    """Security health check baseline score."""
    try:
        data = sf.query_all("SELECT Score, LastModifiedDate FROM SecurityHealthCheck LIMIT 1")
    except Exception:
        data = {"note": "SecurityHealthCheck not available via SOQL — check Setup > Security Health Check in UI"}
    return {"health_check": data}


SCOPE_COLLECTORS = {
    "auth": collect_auth,
    "access": collect_access,
    "event-monitoring": collect_event_monitoring,
    "transaction-security": collect_transaction_security,
    "integrations": collect_integrations,
    "oauth": collect_oauth,
    "secconf": collect_secconf,
}

VALID_SCOPES = list(SCOPE_COLLECTORS.keys()) + ["all"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """sfdc-connect — read-only Salesforce org config collector for security assessment."""


@cli.command()
@click.option("--org", default=None, help="Org alias or instance URL (overrides SF_INSTANCE_URL in .env)")
@click.option("--scope", required=True, type=click.Choice(VALID_SCOPES, case_sensitive=False), help="What to collect")
@click.option("--out", default=None, help="Output JSON file path (default: stdout)")
@click.option("--env", default="dev", type=click.Choice(["dev", "test", "prod"]), help="Environment label")
@click.option("--timeout", default=60, help="API timeout in seconds")
@click.option("--dry-run", is_flag=True, help="Print what would be collected without calling API")
@click.option(
    "--auth-method",
    default=None,
    type=click.Choice(list(VALID_AUTH_METHODS)),
    help="Auth method override (default: SF_AUTH_METHOD env var or 'jwt')",
)
def collect(
    org: str | None, scope: str, out: str | None, env: str, timeout: int, dry_run: bool, auth_method: str | None
) -> None:
    """Collect security-relevant configuration from a Salesforce org."""
    org_label = org or os.getenv("SFDC_ORG_ALIAS", os.getenv("SF_INSTANCE_URL", "unknown"))
    effective_method = _resolve_auth_method(auth_method)

    if dry_run:
        scopes_to_run = list(SCOPE_COLLECTORS.keys()) if scope == "all" else [scope]
        click.echo(f"DRY RUN — would collect: {scopes_to_run} from org: {org_label}")
        click.echo(f"Output: {out or 'stdout'}")
        return

    sf = _connect(effective_method)
    if org:
        # Override instance URL if explicit org URL provided
        sf.sf_instance = org.replace("https://", "").rstrip("/")

    scopes_to_run = list(SCOPE_COLLECTORS.keys()) if scope == "all" else [scope]
    combined: dict[str, Any] = {}

    for s in scopes_to_run:
        click.echo(f"  collecting: {s}", err=True)
        try:
            combined[s] = SCOPE_COLLECTORS[s](sf)
        except Exception as exc:
            combined[s] = {"error": str(exc)}
            click.echo(f"  WARNING: {s} failed — {exc}", err=True)

    result = _result_envelope(org_label, env, scope, combined)
    _write_output(result, out)


@cli.command()
@click.option("--dry-run", is_flag=True, help="Skip actual connection, just validate env vars are set")
@click.option(
    "--auth-method",
    default=None,
    type=click.Choice(list(VALID_AUTH_METHODS)),
    help="Auth method override (only 'jwt' is supported)",
)
def auth(dry_run: bool, auth_method: str | None) -> None:
    """Test authentication to the Salesforce org (JWT Bearer Flow)."""
    _resolve_auth_method(auth_method)

    if dry_run:
        missing = [k for k in REQUIRED_ENV_JWT if not os.getenv(k)]
        if missing:
            click.echo(f"FAIL — missing env vars: {', '.join(missing)}", err=True)
            sys.exit(1)
        click.echo("OK — all required JWT env vars set (dry-run, no connection made)")
        return

    sf = _connect()
    org_info = sf.query_all("SELECT Id, Name, OrganizationType FROM Organization LIMIT 1")
    if org_info["totalSize"] == 1:
        rec = org_info["records"][0]
        click.echo(f"OK — connected to: {rec['Name']} ({rec['OrganizationType']}) id={rec['Id']}")
    else:
        click.echo("WARN — connected but could not retrieve org info")


@cli.command("org-info")
@click.option("--out", default=None, help="Output JSON file path (default: stdout)")
def org_info(out: str | None) -> None:
    """Retrieve basic org metadata (name, edition, features, limits)."""
    sf = _connect()

    data: dict[str, Any] = {}
    data["organization"] = sf.query_all(
        "SELECT Id, Name, OrganizationType, InstanceName, IsSandbox, "
        "LanguageLocaleKey, TimeZoneSidKey, UsedLicenses FROM Organization LIMIT 1"
    )
    data["limits"] = sf.limits()

    result = _result_envelope(
        org=os.getenv("SF_INSTANCE_URL", "unknown"),
        env="dev",
        scope="org-info",
        data=data,
    )
    _write_output(result, out)


if __name__ == "__main__":
    cli()
