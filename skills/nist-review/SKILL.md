---
name: nist-review
description: Validates multi-agent assessment outputs against NIST AI RMF 1.0 (Govern, Map, Measure, Manage) and produces a structured verdict JSON. Used as pipeline step 5 after sscf-benchmark.
cli: skills/nist-review/nist-review
model_hint: sonnet
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
--dry-run         Produce realistic stub verdict without calling the Anthropic API.
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

In live mode (`--dry-run` omitted), calls `gpt-5.3-chat-latest` with `agents/nist-reviewer.md` as the system prompt. Both input JSONs are truncated to 6 000 characters each to stay within the token budget. Requires `OPENAI_API_KEY` in the environment.

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
