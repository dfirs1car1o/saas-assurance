#!/usr/bin/env python3
"""
validate_env.py — Pre-flight system requirements check for saas-posture.

Run this before any assessment or agent workflow. Exits 0 only if all HARD
requirements pass. Prints a clear PASS / WARN / FAIL per check.

Usage:
    python3 scripts/validate_env.py            # interactive, color output
    python3 scripts/validate_env.py --ci       # no color, strict exit code
    python3 scripts/validate_env.py --fix      # attempt to auto-install missing Python deps
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

USE_COLOR = sys.stdout.isatty()


def _color(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def ok(msg: str) -> str:
    return _color("32;1", "  PASS") + f"  {msg}"


def warn(msg: str) -> str:
    return _color("33;1", "  WARN") + f"  {msg}"


def fail(msg: str) -> str:
    return _color("31;1", "  FAIL") + f"  {msg}"


def header(msg: str) -> str:
    return _color("34;1", f"\n{msg}")


# ---------------------------------------------------------------------------
# Check result
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    status: str  # "pass" | "warn" | "fail"
    message: str
    hard: bool = True  # hard=True means failure blocks the pipeline


@dataclass
class CheckSuite:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)
        if result.status == "pass":
            print(ok(f"[{result.name}] {result.message}"))
        elif result.status == "warn":
            print(warn(f"[{result.name}] {result.message}"))
        else:
            print(fail(f"[{result.name}] {result.message}"))

    @property
    def hard_failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "fail" and r.hard]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "warn"]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_python_version(suite: CheckSuite) -> None:
    v = sys.version_info
    if v >= (3, 11):
        suite.add(CheckResult("python", "pass", f"Python {v.major}.{v.minor}.{v.micro}"))
    else:
        suite.add(
            CheckResult(
                "python",
                "fail",
                f"Python {v.major}.{v.minor} found — 3.11+ required. Install via pyenv or homebrew.",
            )
        )


def check_uv(suite: CheckSuite) -> None:
    path = shutil.which("uv")
    if path:
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
        suite.add(CheckResult("uv", "pass", result.stdout.strip()))
    else:
        suite.add(
            CheckResult(
                "uv",
                "warn",
                "uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh",
                hard=False,
            )
        )


def check_git(suite: CheckSuite) -> None:
    path = shutil.which("git")
    if path:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True)
        suite.add(CheckResult("git", "pass", result.stdout.strip()))
    else:
        suite.add(CheckResult("git", "fail", "git not found. Install from https://git-scm.com"))


def check_gh_cli(suite: CheckSuite) -> None:
    path = shutil.which("gh")
    if path:
        result = subprocess.run(["gh", "--version"], capture_output=True, text=True)
        suite.add(CheckResult("gh-cli", "pass", result.stdout.splitlines()[0].strip(), hard=False))
    else:
        suite.add(
            CheckResult(
                "gh-cli",
                "warn",
                "gh CLI not found (optional). Install: https://cli.github.com",
                hard=False,
            )
        )


def check_env_file(suite: CheckSuite) -> None:
    env_path = Path(".env")
    example_path = Path(".env.example")
    if not env_path.exists():
        if example_path.exists():
            suite.add(
                CheckResult(
                    ".env",
                    "fail",
                    ".env not found. Copy .env.example to .env and fill in values.",
                )
            )
        else:
            suite.add(CheckResult(".env", "fail", "Neither .env nor .env.example found."))
        return
    suite.add(CheckResult(".env", "pass", ".env file exists"))


def check_env_vars(suite: CheckSuite) -> None:  # NOSONAR
    # Load .env manually for the check
    env_path = Path(".env")
    env_values: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_values[k.strip()] = v.strip()

    # Merge with process environment
    for k, v in os.environ.items():
        env_values.setdefault(k, v)

    checks = [
        ("SF_USERNAME", "Salesforce username", True),
        ("SF_PASSWORD", "Salesforce password", True),
        ("SF_SECURITY_TOKEN", "Salesforce security token", True),
        ("OPENAI_API_KEY", "OpenAI API key", True),
        ("SF_DOMAIN", "Salesforce domain (optional)", False),
        ("SF_INSTANCE_URL", "Salesforce instance URL (optional)", False),
        ("SF_AUTH_METHOD", "Auth method: soap (default) or jwt (optional)", False),
        ("SF_CONSUMER_KEY", "JWT: Connected App Consumer Key (optional)", False),
        ("SF_PRIVATE_KEY_PATH", "JWT: RSA private key path (optional)", False),
        ("LLM_MODEL_ORCHESTRATOR", "LLM orchestrator model override (optional)", False),
        ("LLM_MODEL_ANALYST", "LLM analyst model override (optional)", False),
        ("LLM_MODEL_REPORTER", "LLM reporter model override (optional)", False),
        # Workday (optional — only required for --platform workday)
        ("WD_TENANT", "Workday tenant ID (required for workday platform)", False),
        ("WD_CLIENT_ID", "Workday OAuth 2.0 client ID (required for workday platform)", False),
        ("WD_CLIENT_SECRET", "Workday OAuth 2.0 client secret (required for workday platform)", False),
        ("WD_TOKEN_URL", "Workday OAuth 2.0 token URL (required for workday platform)", False),
        ("WD_BASE_URL", "Workday REST/SOAP base URL (required for workday platform)", False),
        ("WD_API_VERSION", "Workday API version (optional, default v42.0)", False),
    ]

    for key, description, hard in checks:
        val = env_values.get(key, "")
        if val and not val.startswith("your") and not val.startswith("sk-..."):
            masked = val[:4] + "****" if len(val) > 4 else "****"
            suite.add(CheckResult(key, "pass", f"{description} — set ({masked})", hard=hard))
        elif hard:
            suite.add(
                CheckResult(
                    key,
                    "fail",
                    f"{description} — not set. Add to .env.",
                    hard=True,
                )
            )
        else:
            suite.add(CheckResult(key, "warn", f"{description} — not set (optional)", hard=False))


def check_python_package(
    suite: CheckSuite, package: str, import_name: str | None, min_version: str | None, hard: bool = True
) -> None:
    imp = import_name or package.replace("-", "_")
    spec = importlib.util.find_spec(imp)
    if spec is None:
        suite.add(
            CheckResult(
                package,
                "fail" if hard else "warn",
                f"Not installed. Run: pip install {package}",
                hard=hard,
            )
        )
        return

    # Try to get version
    try:
        from importlib.metadata import version as _pkg_version

        installed_version = _pkg_version(package)
    except Exception:
        installed_version = "unknown"

    if min_version and installed_version != "unknown":
        try:
            installed_parts = tuple(int(x) for x in installed_version.split(".")[:3])
            required_parts = tuple(int(x) for x in min_version.split(".")[:3])
            if installed_parts < required_parts:
                suite.add(
                    CheckResult(
                        package,
                        "warn",
                        f"v{installed_version} installed, v{min_version}+ recommended",
                        hard=False,
                    )
                )
                return
        except Exception:
            pass

    suite.add(CheckResult(package, "pass", f"v{installed_version}", hard=hard))


def check_python_packages(suite: CheckSuite) -> None:
    hard_packages = [
        ("openai", "openai", "1.0.0", True),
        ("simple-salesforce", "simple_salesforce", "1.12.6", True),
        ("click", "click", "8.1.0", True),
        ("pydantic", "pydantic", "2.8.0", True),
        ("PyYAML", "yaml", "6.0.2", True),
        ("python-dotenv", "dotenv", "1.0.0", True),
    ]
    soft_packages = [
        ("ruff", "ruff", None, False),
        ("bandit", "bandit", None, False),
        ("pip-audit", "pip_audit", None, False),
        ("pytest", "pytest", None, False),
    ]
    for pkg, imp, min_v, hard in hard_packages + soft_packages:
        check_python_package(suite, pkg, imp, min_v, hard=hard)


def check_repo_layout(suite: CheckSuite) -> None:
    required = [
        Path("mission.md"),
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("skills/sfdc_connect/sfdc_connect.py"),
        Path("config/sscf_control_index.yaml"),
        Path("config/oscal-salesforce/sbs_source.yaml"),
        Path("schemas/baseline_assessment_schema.json"),
        Path(".env.example"),
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        suite.add(
            CheckResult(
                "repo-layout",
                "fail",
                f"Missing required files: {', '.join(missing)}",
            )
        )
    else:
        suite.add(CheckResult("repo-layout", "pass", "All required repo files present"))


def check_sfdc_connect_importable(suite: CheckSuite) -> None:
    # Try running via subprocess first (works regardless of install state)
    result = subprocess.run(
        [sys.executable, "-m", "skills.sfdc_connect.sfdc_connect", "--help"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )
    if result.returncode == 0:
        suite.add(CheckResult("sfdc-connect-module", "pass", "sfdc-connect --help OK"))
    else:
        suite.add(
            CheckResult(
                "sfdc-connect-module",
                "fail",
                "skills.sfdc_connect not importable. Run: ./setup.sh or: pip install -e .",
            )
        )


def check_qdrant_config(suite: CheckSuite) -> None:
    """Warn if neither QDRANT_IN_MEMORY nor QDRANT_HOST is configured.

    QDRANT_IN_MEMORY=1 is the default for local dev and CI — no container needed.
    QDRANT_HOST should only be set when running a persistent Qdrant container.
    """
    in_memory = os.getenv("QDRANT_IN_MEMORY", "").strip().strip('"').strip("'").lower()
    qdrant_host = os.getenv("QDRANT_HOST", "")

    if in_memory in {"1", "true", "yes", "on"}:
        suite.add(
            CheckResult(
                "qdrant",
                "pass",
                "QDRANT_IN_MEMORY=1 — in-process Qdrant, no Docker container needed",
                hard=False,
            )
        )
    elif qdrant_host:
        suite.add(
            CheckResult(
                "qdrant",
                "pass",
                f"QDRANT_HOST={qdrant_host} — using external Qdrant container",
                hard=False,
            )
        )
    else:
        suite.add(
            CheckResult(
                "qdrant",
                "warn",
                (
                    "Neither QDRANT_IN_MEMORY=1 nor QDRANT_HOST is set. "
                    "Session memory will fail at runtime. "
                    "Add QDRANT_IN_MEMORY=1 to .env (recommended) or start a Qdrant container."
                ),
                hard=False,
            )
        )


def check_docs_generated_dir(suite: CheckSuite) -> None:
    path = Path("docs/oscal-salesforce-poc/generated")
    if path.exists():
        count = len(list(path.glob("*")))
        suite.add(
            CheckResult(
                "generated-dir",
                "pass",
                f"docs/.../generated/ exists ({count} files)",
                hard=False,
            )
        )
    else:
        suite.add(
            CheckResult(
                "generated-dir",
                "warn",
                "docs/oscal-salesforce-poc/generated/ does not exist — will be created on first run",
                hard=False,
            )
        )


def check_openai_api_key_format(suite: CheckSuite) -> None:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        # Already caught in check_env_vars
        return
    if key.startswith("sk-"):
        suite.add(CheckResult("openai-key-format", "pass", "API key format looks correct"))
    else:
        suite.add(
            CheckResult(
                "openai-key-format",
                "warn",
                "OPENAI_API_KEY doesn't start with 'sk-' — double-check it's a valid key",
                hard=False,
            )
        )


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------


def attempt_fix(suite: CheckSuite) -> None:
    failures = [
        r
        for r in suite.results
        if r.status == "fail"
        and r.name
        not in (
            "python",
            "git",
            ".env",
            "SF_USERNAME",
            "SF_PASSWORD",
            "SF_SECURITY_TOKEN",
            "OPENAI_API_KEY",
            "repo-layout",
            "SF_AUTH_METHOD",
            "SF_CONSUMER_KEY",
            "SF_PRIVATE_KEY_PATH",
        )
    ]
    if not failures:
        print("\nNothing auto-fixable found.")
        return

    print(f"\nAttempting to fix {len(failures)} issue(s)...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        cwd=Path.cwd(),
    )
    if result.returncode == 0:
        print(_color("32;1", "  Auto-fix complete.") + " Re-run validate_env.py to confirm.")
    else:
        print(_color("31;1", "  Auto-fix failed.") + " Check error output above.")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(suite: CheckSuite, _ci_mode: bool) -> int:
    total = len(suite.results)
    passed = sum(1 for r in suite.results if r.status == "pass")
    warned = len(suite.warnings)
    failed = len(suite.hard_failures)

    print(header("─" * 60))
    print(f"  Results: {passed}/{total} passed | {warned} warnings | {failed} hard failures")

    if failed:
        print(_color("31;1", "\n  ENVIRONMENT NOT READY.") + " Fix the FAIL items above before running assessments.\n")
        return 1
    elif warned:
        print(_color("33;1", "\n  ENVIRONMENT READY WITH WARNINGS.") + " Soft requirements missing — see WARN items.\n")
        return 0
    else:
        print(_color("32;1", "\n  ENVIRONMENT READY.") + " All hard requirements met.\n")
        return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-flight check for saas-posture local environment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/validate_env.py           # standard check
  python3 scripts/validate_env.py --ci      # non-interactive, for use in CI
  python3 scripts/validate_env.py --fix     # attempt to install missing Python deps
  python3 scripts/validate_env.py --json    # output results as JSON
""",
    )
    parser.add_argument("--ci", action="store_true", help="Non-interactive mode (no color, strict exit)")
    parser.add_argument("--fix", action="store_true", help="Attempt to auto-install missing Python packages")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--platform",
        choices=["salesforce", "workday"],
        default=None,
        help="Show platform-specific env var guidance (salesforce or workday)",
    )
    args = parser.parse_args()

    global USE_COLOR
    if args.ci:
        USE_COLOR = False

    # Change to repo root if we're in scripts/
    repo_root = Path(__file__).parent.parent
    os.chdir(repo_root)

    # Load .env before running checks
    env_path = repo_root / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    suite = CheckSuite()

    # When --json is set, route human-readable output to stderr so stdout is
    # clean JSON that callers (e.g. CI scripts) can parse with json.load().
    _real_stdout = None
    if args.json:
        _real_stdout, sys.stdout = sys.stdout, sys.stderr

    print(header("saas-posture — Environment Pre-flight Check"))
    print(f"  Repo root: {repo_root}")
    print(f"  Python:    {sys.executable}")

    print(header("System Tools"))
    check_python_version(suite)
    check_uv(suite)
    check_git(suite)
    check_gh_cli(suite)

    print(header("Repository Layout"))
    check_repo_layout(suite)

    print(header("Environment Variables (.env)"))
    check_env_file(suite)
    check_env_vars(suite)
    check_openai_api_key_format(suite)

    print(header("Python Packages"))
    check_python_packages(suite)
    check_sfdc_connect_importable(suite)

    print(header("Runtime Paths"))
    check_docs_generated_dir(suite)
    check_qdrant_config(suite)

    if args.fix:
        attempt_fix(suite)

    if args.json and _real_stdout is not None:
        rc = 1 if suite.hard_failures else 0
        sys.stdout = _real_stdout
        print(
            json.dumps(
                [{"name": r.name, "status": r.status, "message": r.message, "hard": r.hard} for r in suite.results],
                indent=2,
            )
        )
        return rc

    return print_summary(suite, args.ci)


if __name__ == "__main__":
    sys.exit(main())
