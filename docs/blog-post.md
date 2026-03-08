# I Built a Multi-Agent AI System to Automate SaaS Security Assessments — Here's What I Learned

*How OSCAL, CSA SSCF, and NIST AI RMF turn a sprawling compliance problem into a repeatable pipeline*

---

Security assessments for enterprise SaaS platforms are expensive, slow, and almost always out of date by the time they reach a stakeholder. I wanted to change that. Over the past few months I built **saas-posture** — an open-source, multi-agent AI system that automates the full security assessment lifecycle for Salesforce and Workday, from live API collection through governance-ready reports.

This post covers what I built, why the architecture decisions are the way they are, and what I learned about combining AI agents with formal security frameworks.

---

## The Problem With SaaS Security Reviews Today

Most SaaS security assessments follow a familiar pattern: a consultant connects to your org, runs a checklist, writes a Word doc, and hands it to your security team six weeks later. The findings are already stale. The mappings to SOX or ISO 27001 are done by hand and may be inconsistent across engagements. The remediation tracking lives in a spreadsheet nobody updates.

The core failure is that SaaS platforms have machine-readable APIs for almost everything that matters — authentication policies, permission sets, audit log configuration, OAuth scopes, data sharing rules — but almost nobody queries them programmatically and maps the results to a control framework in a repeatable way.

The NIST OSCAL standard (Open Security Controls Assessment Language) was designed to fix exactly this. It defines a machine-readable format for security catalogs, profiles, component definitions, and assessment results. The CSA Cloud Security Alliance publishes its SaaS Security Framework (SSCF) in OSCAL format. The pieces are there. The tooling to assemble them into a working assessment pipeline mostly is not.

That gap is what I built into.

---

## The Architecture: Six Phases, Seven Agents, One Orchestrator

saas-posture is built around a ReAct (Reason + Act) agent loop with an orchestrator managing up to 14 turns. Each turn, the orchestrator decides which specialist agent to invoke, calls the appropriate CLI skill, parses the output, and advances the pipeline state.

```
Phase 1 — Collect      sfdc-connect / workday-connect    →  structured findings JSON
Phase 2 — Assess       oscal-assess + oscal_gap_map       →  gap_analysis.json + backlog.json
Phase 3 — Score        sscf-benchmark                     →  RED/AMBER/GREEN domain scores
Phase 4 — Gate         nist-reviewer (NIST AI RMF 1.0)    →  clear / flag / block verdict
Phase 5 — Report       report-gen                         →  Markdown + DOCX for two audiences
Phase 6 — Monitor      export_to_opensearch + dashboards  →  trending posture data
```

Seven agents handle specialist tasks: orchestrator, collector, assessor, NIST reviewer, reporter, sfdc-expert (deep Salesforce/Apex calls), and workday-expert (Workday HCM/Finance specialist). A security-reviewer agent runs on every CI/CD pipeline change. A container-expert agent handles the OpenSearch stack.

### Why CLIs Instead of MCPs?

Every tool in the system is a Python CLI called with subprocess — not an MCP server. This was a deliberate choice. CLIs are:

- **Auditable** — every invocation with its full arguments shows up in logs
- **Composable** — you can pipe and filter them from the shell without understanding the agent loop
- **Testable** — standard pytest coverage, no mocked MCP infrastructure needed
- **Debuggable** — when something fails, you run the CLI directly with the same arguments

The agent loop calls `python -m skills.sfdc_connect.sfdc_connect collect --org acme --dry-run` the same way you would from your terminal. There is no hidden state.

---

## The Control Framework Chain

One of the design choices I'm most satisfied with is the full framework provenance chain. Every finding traces through:

```
Platform control (SBS-AUTH-001 / WD-IAM-003)
    → SSCF domain (Identity & Access Management)
        → CCM v4.1 control (IAM-04)
            → Regulatory crosswalk (SOX §404, HIPAA §164.312, SOC2 CC6.1, ISO 27001 A.9.1, NIST 800-53 AC-2, PCI DSS 7.1, GDPR Art.25)
```

This matters for two reasons. First, it means a security team can answer "which findings affect our SOX compliance?" with a query, not a manual review. Second, it means the OSCAL artifact chain is complete — Catalog → Profile → Component Definition → Assessment Results → POA&M — which is what auditors using OSCAL-aware GRC tools need.

The OSCAL Provenance table in every security report makes this chain explicit and human-readable:

| Layer | Artifact |
|---|---|
| Catalog | CSA SSCF v1.0 (OSCAL 1.1.2) |
| Profile | SBS v1.0 (Salesforce) or WSCC v0.2.0 (Workday) |
| Component Def | Platform-specific evidence specifications |
| Framework Bridge | CCM v4.1 (36 controls) |
| Regulatory Crosswalk | SOX / HIPAA / SOC2 / ISO 27001 / NIST 800-53 / PCI DSS / GDPR |
| POA&M | Open findings with owners, due dates, POAM-IDs |

---

## The NIST AI RMF Gate — Validating the AI Itself

This is the part that surprised people most when I described it: there is a governance gate that validates the AI system's own outputs before they can be delivered.

The NIST AI Risk Management Framework 1.0 defines four functions: **Govern**, **Map**, **Measure**, and **Manage**. I implemented each as a check on the assessment output:

- **Govern** — Is there a named `assessment_owner`? Is the scope documented?
- **Map** — Is `data_source` declared? (`live_api`, `dry_run_stub`, or `manual_questionnaire`) Are AI-generated findings distinguished from human-verified ones?
- **Measure** — Is `mapping_confidence` reported for every finding? Are unmapped findings counted, not silently dropped?
- **Manage** — Does every critical finding have an `owner` and `due_date`? Is the exception process referenced?

The gate issues one of three verdicts:
- **clear** — output may be delivered
- **flag** — output may be delivered with caveats surfaced to the recipient (e.g., dry-run stub data used)
- **block** — output must not be distributed until blocking issues are resolved

The orchestrator cannot auto-override a block verdict. A human must acknowledge each blocking issue before the pipeline continues. This is what makes the system governance-grade rather than just a demo.

In practice, the most common block condition on early runs was missing `assessment_owner` in the backlog root — a field I added after the first live run against our Salesforce developer org returned a `block` verdict on NIST Govern.

---

## What I Learned About Salesforce's API Surface

Thirty percent of the interesting security configuration in Salesforce is harder to read than it should be:

**SecuritySettings** — you cannot query individual fields via SOQL. You have to use `SELECT Metadata FROM SecuritySettings LIMIT 1` and parse the Metadata blob. The documentation does not make this obvious and the error message when you try individual fields is unhelpful.

**RemoteProxy** (remote site settings) — not accessible via SOQL v59. Requires the Tooling API with a different endpoint and authentication flow. The skill now tries Tooling API automatically before falling back gracefully.

**OrganizationSettings MFA fields** — inaccessible on Developer Edition orgs entirely. Recorded as `not_applicable` with a note in the evidence reference so auditors know the gap exists and why.

**MFA enforcement policy** — the relevant fields live in `UserManagement` settings and `SecuritySettings.Metadata`, not in any simple org-wide boolean. Checking this correctly requires parsing nested XML embedded in a JSON blob returned by the Metadata API.

All of these edge cases are now handled gracefully in `sfdc-connect`, with the exact failure mode recorded in the finding's `evidence_ref` field so assessors can decide whether to invoke the sfdc-expert agent for deeper investigation.

---

## The OpenSearch Dashboard Layer

Phase 6 was the most visually satisfying. Every assessment run exports its findings to OpenSearch via `opensearch-py` bulk indexing. Three pre-built dashboards — one combined view, one Salesforce-only, one Workday-only — load automatically on first `docker compose up`.

The hardest part was the NDJSON dashboard format. OpenSearch's saved objects API requires `visState` to be a double-JSON-encoded string — JSON encoded as a string and then embedded inside another JSON object. Getting this wrong (and there are dozens of ways to get it wrong) produces silent failures where the dashboard imports without error but renders blank panels.

The working approach: generate all dashboard objects programmatically via Python's `json.dumps`, never hand-edit visState strings, and always test with `curl -X POST "http://localhost:5601/api/saved_objects/_import?overwrite=true" -H "osd-xsrf: true"` after any change.

Another non-obvious issue: OpenSearch clusters in single-node mode will stay `yellow` health unless you explicitly set `number_of_replicas: 0` in your index template. The yellow state does not prevent indexing or querying, but it will cause your healthcheck to fail if you are polling for `"state":"green"` — which you should be, not Kibana's `"level":"available"` pattern that appears in most blog posts.

---

## What's Next

The two capabilities I'm most interested in adding:

**Live Workday run** — the full Workday collection pipeline is built and tested in dry-run mode. Running it live requires a tenant with the right integration system user permissions. The SOAP/RaaS/REST transport matrix handles all 30 WSCC controls; I just need a real tenant to test against.

**Drift detection** — right now each run is a snapshot. The data model supports comparing runs (same org, different dates), but the assessor does not yet produce a structured diff. This would make the "has anything gotten worse since last month?" question answerable in two seconds.

**GitHub Actions scheduled runs** — the container stack supports cron-triggered assessments, but the GitHub Actions workflow for scheduling dry-runs and pushing results to OpenSearch is not wired up yet.

---

## Try It

saas-posture is open source under Apache 2.0.

```bash
git clone https://github.com/dfirs1car1o/saas-posture
cd saas-posture && pip install -e .
cp .env.example .env
python3 -m skills.sfdc_connect.sfdc_connect collect \
  --org my-org --scope all --dry-run \
  --out docs/oscal-salesforce-poc/generated/my-org/2026-03-08/sfdc_raw.json
```

The wiki has full platform setup guides for Salesforce, Workday, macOS, Linux, and Windows/WSL2: **github.com/dfirs1car1o/saas-posture/wiki**

Feedback welcome — especially from anyone running Workday HCM with a sandbox tenant they would let me test against.

---

*Built with Claude Code (orchestration), OpenAI GPT-5.3 (analysis and reporting), and the OpenSearch stack. All source code is in the repo. No vendor lock-in.*
