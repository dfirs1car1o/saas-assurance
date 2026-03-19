---
name: nist-review
description: Validates multi-agent assessment outputs against NIST AI RMF 1.0 (Govern, Map, Measure, Manage) and produces a structured verdict JSON. Used as pipeline step 5 after sscf-benchmark.
cli: skills/nist-review/nist-review
model_hint: gpt-5.3-chat-latest
---

# nist-review

Takes assessed OSCAL outputs (`gap_analysis.json` and `backlog.json`) and evaluates them against the four NIST AI RMF 1.0 governance functions. Produces a structured verdict JSON used by `report-gen` for the NIST AI RMF compliance note.

## Usage

```bash
nist-review assess \
  --gap-analysis <path/to/gap_analysis.json> \
  --backlog      <path/to/backlog.json> \
  --out          <path/to/nist_review.json> \
  [--dry-run]
```

## Flags

```
--gap-analysis    Path to gap_analysis.json from oscal-assess. Required (live mode).
--backlog         Path to backlog.json from oscal_gap_map. Required (live mode).
--out             Output path for nist_review.json. Required.
--dry-run         Produce realistic stub verdict without calling the OpenAI API.
```

## NIST AI RMF Functions

| Function | What it evaluates |
|---|---|
| GOVERN | Policies, accountability structures, and AI governance processes in place |
| MAP | Risk identification and categorization alignment with assessment findings |
| MEASURE | Measurement methods and metrics used for AI risk quantification |
| MANAGE | Risk response, prioritization, and remediation planning completeness |

## Output Format

```json
{
  "nist_ai_rmf_review": {
    "assessment_id": "sfdc-assess-my-org-dev",
    "reviewed_at_utc": "2026-03-03T15:00:00Z",
    "govern":  { "status": "pass|partial|fail", "notes": "..." },
    "map":     { "status": "pass|partial|fail", "notes": "..." },
    "measure": { "status": "pass|partial|fail", "notes": "..." },
    "manage":  { "status": "pass|partial|fail", "notes": "..." },
    "overall": "clear|flag|block",
    "blocking_issues": [],
    "recommendations": ["..."]
  }
}
```

### Overall verdict values

| Verdict | Meaning |
|---|---|
| `clear` | All four functions pass — no NIST AI RMF concerns |
| `flag` | One or more functions partial — review recommended before sign-off |
| `block` | One or more functions fail or blocking issues present — escalation required |

## Live Mode

In live mode (`--dry-run` omitted), calls `gpt-5.3-chat-latest` with `agents/nist-reviewer.md` as the system prompt. Input artifacts are summarised by `_build_review_context` (token-efficient structured summary — critical/high findings always included in full). Requires `OPENAI_API_KEY` in the environment.

## MEASURE Flag — Low Confidence Denominator

`mapping_confidence="low"` is assigned exclusively to `not_applicable` findings (controls outside the API collector scope — code review, CI/CD audit, manual governance, browser extension inventory, etc.). These are structural scope limits of the tool, not assessment quality defects.

The NIST MEASURE >`30% low confidence` FLAG threshold applies to **assessable findings only** (`pass + fail + partial`). The context sent to the LLM includes derived fields:

| Field | Meaning |
|---|---|
| `low_confidence_assessable_count` | Count of low-confidence items among pass/fail/partial only |
| `low_confidence_assessable_pct` | `low_confidence_assessable_count / assessable_count × 100` |
| `assessable_count` | Total items minus `not_applicable` items |
| `not_applicable_count` | Items outside collector scope (always `low` confidence) |
| `measure_note` | Plain-text explanation of the denominator for the LLM |

For a healthy live Salesforce run where all low-confidence items are scope exclusions, `low_confidence_assessable_pct` will be 0%, and the MEASURE threshold will not be exceeded from confidence alone.

## needs_expert_review Tracking

The context also includes:
- `gap_summary.needs_expert_review_ids` — list of control IDs with `needs_expert_review=true` from `gap_analysis.json`
- `backlog_summary.needs_expert_review_items` — list of `{control_id, expert_review_status}` from `backlog.json`
- `backlog_summary.needs_expert_review_count` — count of pending expert reviews

`expert_review_status` is set by the sfdc-expert / workday-expert enrichment step. If `null`, expert review has not yet been performed — this triggers the FLAG condition in `nist-reviewer.md`.

## Dry-Run Mode

Produces a realistic weak-org stub verdict without calling the OpenAI API:

- GOVERN: pass
- MAP: partial
- MEASURE: pass
- MANAGE: partial
- overall: flag

This exercises the full report pipeline (including the NIST section in `report-gen`) without API spend on the review step.

## Pipeline Position

```
sfdc-connect → oscal-assess → oscal_gap_map → sscf-benchmark → nist-review → report-gen (×2)
                                    ↓                                ↑
                             gap_analysis.json ───────────────────→─┘
                             backlog.json ────────────────────────→─┘
```

`nist-review` is registered in `pyproject.toml` as:
```
nist-review = "skills.nist_review.nist_review:cli"
```
