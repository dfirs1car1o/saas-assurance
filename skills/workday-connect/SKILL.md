---
name: workday-connect
description: Authenticates to a Workday tenant via OAuth 2.0 and extracts HCM/Finance security configuration for WSCC assessment. Read-only. Never writes to the tenant.
cli: skills/workday-connect/workday-connect
model_hint: sonnet
---

# workday-connect

Connects to a Workday tenant and extracts security-relevant configuration data across IAM, logging, data security, governance, and configuration domains for OSCAL/WSCC/SSCF assessment.

## Usage

```bash
python -m skills.workday_connect.workday_connect --help
python -m skills.workday_connect.workday_connect collect \
  --org <tenant-alias> --env dev|test|prod \
  --out docs/oscal-salesforce-poc/generated/<org>/<date>/workday_raw.json
```

## Flags

```
--org        Tenant alias for output naming. Required.
--env        Environment label: dev|test|prod. Default: dev.
--out        Output JSON file path. Required.
--dry-run    Generate realistic stub output without contacting the tenant.
```

## Authentication

Set in `.env`:
```bash
WD_BASE_URL=https://<tenant>.workday.com
WD_TENANT=<tenant>
WD_CLIENT_ID=<client-id>
WD_CLIENT_SECRET=<client-secret>
WD_TOKEN_URL=https://<tenant>.workday.com/ccx/oauth2/<tenant>/token
```

OAuth 2.0 Client Credentials flow. Token is acquired once per session and cached in memory. Client secret is deleted from memory immediately after token acquisition (CWE-312 mitigation).

## Transport Matrix

| Transport | Controls | Auth |
|-----------|----------|------|
| SOAP (WWS) | WD-IAM-*, WD-CON-*, WD-CKM-* | Bearer header |
| RaaS (custom reports) | WD-LOG-*, WD-DSP-*, WD-GOV-* | Bearer header |
| REST API v1 | WD-IAM-007 (worker data) | Bearer header |
| Manual questionnaire | WD-CON-005, WD-TDR-*, WD-CKM-001/002 | n/a |

## Control Coverage

30 WSCC controls across 6 domains:

| Domain | Controls |
|--------|----------|
| IAM — Identity & Access Management | WD-IAM-001 through WD-IAM-008 |
| CON — Configuration Hardening | WD-CON-001 through WD-CON-005 |
| LOG — Logging & Monitoring | WD-LOG-001 through WD-LOG-004 |
| DSP — Data Security & Privacy | WD-DSP-001 through WD-DSP-005 |
| GOV — Governance & Compliance | WD-GOV-001 through WD-GOV-004 |
| CKM — Credential & Key Management | WD-CKM-001 through WD-CKM-004 |

## Output Shape

```json
{
  "org": "<alias>",
  "env": "dev|test|prod",
  "platform": "workday",
  "collected_at_utc": "<ISO timestamp>",
  "findings": [
    {
      "control_id": "WD-IAM-001",
      "status": "pass|fail|partial|not_applicable",
      "severity": "critical|high|moderate|low",
      "observed_value": "<what the tenant actually has>",
      "expected_value": "<what WSCC baseline requires>",
      "evidence_ref": "workday-connect://<org>/WD-IAM-001/<timestamp>",
      "data_source": "live_api|dry_run_stub|manual_questionnaire"
    }
  ]
}
```

## Error Handling

| Error | Action |
|-------|--------|
| `PERMISSION_DENIED` on critical control | Invoke `workday-expert` before marking `not_applicable` |
| OAuth token failure (401) | Stop immediately, report to orchestrator — do not retry with different credentials |
| API timeout | Record collected items; note incomplete scope in `evidence_ref` |
| RaaS report not configured | Log as `not_applicable` with note; do not fail entire collection |

## What This Skill Will Not Do

- Write, update, or delete any Workday record
- Store credentials to disk
- Access record-level employee data (only aggregate security configuration)
- Expose `WD_CLIENT_SECRET` in any log, output file, or error message
