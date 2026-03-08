# AGENTS.md — Master Agent Reference

This file is the canonical reference for all agents in this system. Each agent has a definition file in agents/. Read that file for full context, tools, and prompting patterns.

## Agent Roster

| Agent | File | Model | Primary Role |
|---|---|---|---|
| orchestrator | agents/orchestrator.md | gpt-5.3-chat-latest | Routes tasks, manages 14-turn ReAct loop, calls finish() to exit |
| collector | agents/collector.md | gpt-5.3-chat-latest | Extracts SaaS org config via API and CLI |
| assessor | agents/assessor.md | gpt-5.3-chat-latest | Maps findings to OSCAL/SBS/SSCF controls |
| reporter | agents/reporter.md | gpt-5.3-chat-latest | Generates DOCX/MD governance outputs |
| nist-reviewer | agents/nist-reviewer.md | gpt-5.3-chat-latest | Validates all outputs against NIST AI RMF 1.0 |
| security-reviewer | agents/security-reviewer.md | gpt-5.3-chat-latest | AppSec + DevSecOps review of CI/CD, workflows, and skill CLIs |
| sfdc-expert | agents/sfdc-expert.md | gpt-5.3-chat-latest | Apex + deep Salesforce admin specialist (on-call) |
| workday-expert | agents/workday-expert.md | gpt-5.3-chat-latest | Workday HCM/Finance API specialist (on-call) — SOAP/RaaS/REST, WSCC catalog, ISSG permissions |
| container-expert | agents/container-expert.md | gpt-5.3-chat-latest | Docker Compose, OpenSearch 2.x, NDJSON dashboards, JVM tuning, stack troubleshooting |
| repo-reviewer | agents/repo-reviewer.md | gpt-5.3-chat-latest | Periodic audit: personal data, stale docs, strategic alignment |

> Models are set by env vars: `LLM_MODEL_ORCHESTRATOR`, `LLM_MODEL_ANALYST`, `LLM_MODEL_REPORTER` (default: `gpt-5.3-chat-latest`). Azure OpenAI Government supported via `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT`.

## Skill Roster

| Skill | Directory | What It Does |
|---|---|---|
| sfdc-connect | skills/sfdc_connect/ | Authenticates and queries a Salesforce org via REST/Tooling API (JWT or SOAP) |
| oscal-assess | skills/oscal_assess/ | Evaluates 45 SBS controls against collected org config |
| sscf-benchmark | skills/sscf_benchmark/ | Scores findings by CSA SSCF domain (RED/AMBER/GREEN) |
| nist-review | skills/nist_review/ | NIST AI RMF 1.0 gate (govern/map/measure/manage); issues block/flag/pass |
| report-gen | skills/report_gen/ | Generates audience-specific Markdown + DOCX governance reports |
| workday-connect | skills/workday_connect/ | Workday HCM/Finance collector — OAuth 2.0, 30 WSCC controls, SOAP/RaaS/REST/manual, fully implemented |

## Context Modes

| Mode | File | When To Load |
|---|---|---|
| assess | contexts/assess.md | Running a live or historical assessment |
| review | contexts/review.md | Reviewing agent outputs, performing QA |
| research | contexts/research.md | Investigating a CVE, framework, or control definition |

## Model Assignment Rationale

All agents use `gpt-5.3-chat-latest` by default. Override per-role via env vars:
- `LLM_MODEL_ORCHESTRATOR` — routing decisions and multi-step assembly (use highest-capability model)
- `LLM_MODEL_ANALYST` — collector, assessor, nist-reviewer, sfdc-expert, workday-expert (mid-complexity structured tasks)
- `LLM_MODEL_REPORTER` — reporter, container-expert (templated output; lower complexity)

Security Reviewer runs as a Claude Code subagent (text-only, no tool calls).
Azure OpenAI Government (FedRAMP/IL5): set `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_VERSION`.

## Agent Loop Model

```
human message
  -> orchestrator receives
  -> orchestrator identifies task type
  -> orchestrator routes to specialist agents in sequence
  -> each agent calls skills (CLIs), parses output, returns structured result
  -> orchestrator assembles findings into output schema
  -> reporter formats for audience
  -> nist-reviewer validates
  -> orchestrator returns to human
```

## Proactive Heartbeat (Future)

The orchestrator can be scheduled to run proactively:
- Weekly: run sscf-benchmark against last known backlog, flag new drift.
- On CVE feed update: research.md context + nist-reviewer to assess impact.
- On org config change (webhook): collector + assessor triggered automatically.

## Escalation Rules

- Any finding with severity=critical and status=fail must surface to human before reporter finalizes.
- Any NIST AI RMF gap identified by nist-reviewer blocks output until human acknowledges.
- Any CRITICAL or HIGH finding from security-reviewer on a workflow or skill change blocks merge.
- If orchestrator cannot determine org target, it asks human before calling sfdc-connect.
- If any Salesforce finding has `needs_expert_review=true`, invoke sfdc-expert before Assessor passes findings to gap mapping.
- If any Workday finding has `needs_expert_review=true` or `PERMISSION_DENIED` on a critical control, invoke workday-expert before marking `not_applicable`.
- If Docker/OpenSearch stack issues arise (OOM, yellow cluster, dashboard import failure), invoke container-expert.
