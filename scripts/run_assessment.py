#!/usr/bin/env python3
"""
run_assessment.py — interactive assessment runner.

Prompts for platform, mode, org, and visualization preference,
then runs the full pipeline and optionally exports to OpenSearch.

Usage:
    python scripts/run_assessment.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# ── ANSI colours ──────────────────────────────────────────────────────────────
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"


def _print_header() -> None:
    print(f"""
{_BOLD}{_CYAN}╔══════════════════════════════════════════════════════╗
║        saas-assurance — Assessment Runner        ║
╚══════════════════════════════════════════════════════╝{_RESET}
""")


def _ask(prompt: str, choices: list[str] | None = None, default: str | None = None) -> str:
    """Prompt until a valid answer is given."""
    suffix = ""
    if choices:
        suffix = f"  [{'/'.join(choices)}]"
    if default:
        suffix += f"  (default: {default})"

    while True:
        raw = input(f"{_BOLD}{prompt}{_RESET}{suffix}: ").strip()
        if not raw and default:
            return default
        if choices:
            if raw.lower() in [c.lower() for c in choices]:
                return raw.lower()
            print(f"  {_YELLOW}Please enter one of: {', '.join(choices)}{_RESET}")
        elif raw:
            return raw
        else:
            print(f"  {_YELLOW}A value is required.{_RESET}")


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    default_str = "y" if default else "n"
    answer = _ask(prompt, choices=["y", "n"], default=default_str)
    return answer == "y"


def _run(cmd: list[str], env: dict | None = None, check: bool = True) -> int:
    merged = {**os.environ, **(env or {})}
    print(f"\n{_DIM}  $ {' '.join(cmd)}{_RESET}\n")
    result = subprocess.run(cmd, cwd=_REPO, env=merged)  # noqa: S603
    if check and result.returncode != 0:
        print(f"\n{_RED}Command failed (exit {result.returncode}){_RESET}")
        sys.exit(result.returncode)
    return result.returncode


def _python() -> str:
    """Return the Python executable to use."""
    venv = _REPO / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def _check_docker() -> bool:
    return shutil.which("docker") is not None


def _docker_compose_up() -> None:
    print(f"\n{_GREEN}Starting OpenSearch + Dashboards...{_RESET}")
    _run(["docker", "compose", "up", "-d", "opensearch", "dashboards", "dashboard-init"])
    print(f"\n{_GREEN}Stack started. Dashboard will be available at http://localhost:5601{_RESET}")
    print(f"{_DIM}  (may take ~60s for dashboards to become ready){_RESET}")


def _find_generated(org: str, date: str) -> Path | None:
    base = _REPO / "docs" / "oscal-salesforce-poc" / "generated" / org / date
    return base if base.exists() else None


def _print_outputs(org: str, date: str, use_viz: bool) -> None:
    base = _REPO / "docs" / "oscal-salesforce-poc" / "generated" / org / date
    if not base.exists():
        return

    print(f"\n{_BOLD}{_GREEN}Assessment complete — outputs:{_RESET}")
    for f in sorted(base.iterdir()):
        print(f"  {_DIM}{f}{_RESET}")

    if use_viz:
        print(f"\n{_BOLD}Dashboard:{_RESET} {_CYAN}http://localhost:5601{_RESET}")
        print(f"{_DIM}  Use Discover → sscf-findings-* or sscf-runs-* to explore results.{_RESET}")


def main() -> int:  # NOSONAR
    try:
        return _main()
    except Exception as exc:  # noqa: BLE001
        print(f"\n{_RED}Unexpected error: {exc}{_RESET}")
        return 1


def _main() -> int:  # NOSONAR — S3516/S3776: interactive CLI; success always returns 0
    _print_header()

    # ── Platform ──────────────────────────────────────────────────────────────
    print(f"{_BOLD}What platform are you assessing?{_RESET}")
    print(f"  {_CYAN}salesforce{_RESET}  — Salesforce org (SOQL/Tooling/Metadata API)")
    print(f"  {_CYAN}workday{_RESET}     — Workday HCM/Finance (SOAP/RaaS/REST)\n")
    platform = _ask("Platform", choices=["salesforce", "workday"])

    # ── Mode: live or dry-run ─────────────────────────────────────────────────
    print(f"\n{_BOLD}Run mode?{_RESET}")
    print(f"  {_CYAN}dry-run{_RESET}  — No credentials needed. Uses realistic stub data.")
    print(f"  {_CYAN}live{_RESET}     — Connects to a real platform instance.\n")
    mode = _ask("Mode", choices=["dry-run", "live"], default="dry-run")

    # ── Org alias ─────────────────────────────────────────────────────────────
    default_org = os.getenv("SFDC_ORG_ALIAS") if platform == "salesforce" else os.getenv("WD_TENANT", "")
    default_org = default_org or ("acme-workday" if platform == "workday" else "")
    print()
    org = _ask("Org alias (used for output folder naming)", default=default_org or None)

    # ── Environment ───────────────────────────────────────────────────────────
    env = _ask("\nEnvironment", choices=["dev", "test", "prod"], default="dev")

    # ── Visualization ─────────────────────────────────────────────────────────
    print(f"\n{_BOLD}Export results to OpenSearch for visualization?{_RESET}")
    print(f"  {_DIM}Requires Docker. Starts OpenSearch + OpenSearch Dashboards at localhost:5601.{_RESET}")
    print(f"  {_DIM}Skip if you use Splunk, Elastic, Grafana, or another tool.{_RESET}\n")

    docker_available = _check_docker()
    if not docker_available:
        print(f"  {_YELLOW}Docker not found — visualization option unavailable.{_RESET}\n")

    use_viz = docker_available and _ask_yes_no("Enable visualization (Docker + OpenSearch)?", default=False)

    # ── Confirm ───────────────────────────────────────────────────────────────
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    print(f"""
{_BOLD}Ready to run:{_RESET}
  Platform  : {_CYAN}{platform}{_RESET}
  Mode      : {_CYAN}{mode}{_RESET}
  Org       : {_CYAN}{org}{_RESET}
  Env       : {_CYAN}{env}{_RESET}
  Date      : {_CYAN}{today}{_RESET}
  Visualize : {_CYAN}{"yes (OpenSearch Dashboards)" if use_viz else "no"}{_RESET}
""")
    if not _ask_yes_no("Proceed?", default=True):
        print("Aborted.")
        return 0

    # ── Start Docker stack if visualization requested ─────────────────────────
    if use_viz:
        _docker_compose_up()

    py = _python()

    # ── Run assessment ────────────────────────────────────────────────────────
    if mode == "dry-run":
        if platform == "workday":
            print(f"\n{_GREEN}Running Workday dry-run...{_RESET}")
            _run([py, "scripts/workday_dry_run_demo.py", "--org", org, "--env", env])
        else:
            print(f"\n{_GREEN}Running Salesforce dry-run (mock-llm)...{_RESET}")
            # Generate stub gap analysis first, then report in mock mode
            gap_out = _REPO / "docs" / "oscal-salesforce-poc" / "generated" / org / today
            gap_out.mkdir(parents=True, exist_ok=True)
            _run(
                [
                    py,
                    "-m",
                    "skills.oscal_assess.oscal_assess",
                    "assess",
                    "--dry-run",
                    "--platform",
                    "salesforce",
                    "--env",
                    env,
                    "--out",
                    str(gap_out / "gap_analysis.json"),
                ]
            )
            _run(
                [
                    py,
                    "scripts/oscal_gap_map.py",
                    "--controls",
                    "docs/oscal-salesforce-poc/generated/sbs_controls.json",
                    "--gap-analysis",
                    str(gap_out / "gap_analysis.json"),
                    "--mapping",
                    "config/oscal-salesforce/control_mapping.yaml",
                    "--out-md",
                    str(gap_out / "gap_matrix.md"),
                    "--out-json",
                    str(gap_out / "backlog.json"),
                ],
                check=False,
            )
            _run(
                [
                    py,
                    "-m",
                    "skills.report_gen.report_gen",
                    "generate",
                    "--backlog",
                    str(gap_out / "backlog.json"),
                    "--audience",
                    "security",
                    "--org-alias",
                    org,
                    "--mock-llm",
                    "--out",
                    str(gap_out / f"{org}_security_assessment.md"),
                ],
                check=False,
            )
    else:
        # Live run via agent-loop
        print(f"\n{_GREEN}Running live assessment via agent-loop...{_RESET}")
        cmd = [
            py,
            "-m",
            "harness.loop",
            "run",
            "--platform",
            platform,
            "--env",
            env,
            "--org",
            org,
            "--approve-critical",
        ]
        _run(cmd)

    # ── Export to OpenSearch ──────────────────────────────────────────────────
    if use_viz:
        print(f"\n{_GREEN}Exporting results to OpenSearch...{_RESET}")
        rc = _run(
            [py, "scripts/export_to_opensearch.py", "--auto", "--org", org, "--date", today],
            env={"OPENSEARCH_URL": "http://localhost:9200"},
            check=False,
        )
        if rc != 0:
            print(f"  {_YELLOW}Export failed — data may not be in OpenSearch yet.{_RESET}")
            rerun = f"python scripts/export_to_opensearch.py --auto --org {org} --date {today}"
            print(f"  {_DIM}Re-run manually: {rerun}{_RESET}")

    # ── Summary ───────────────────────────────────────────────────────────────
    _print_outputs(org, today, use_viz)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
