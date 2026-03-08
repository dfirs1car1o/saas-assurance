# OSCAL POC for Salesforce

## Objective
Stand up an OSCAL-aligned Salesforce baseline pipeline under the SaaS Risk Program using existing gap-analysis outputs first, then connect to a sandbox for automated evidence checks, and finally promote to production orgs.

## Scope
- In scope:
  - Version-pinned upstream benchmark ingestion (SBS).
  - Mapping current gap-analysis data to benchmark control IDs.
  - Generating technical + operational baseline views for governance.
  - Sandbox automation hooks for phase 2.
- Out of scope:
  - Production org write actions.
  - Real-time remediation execution.

## Phase Plan
1. Phase 1 (Now): Build POC from current gap-analysis data.
2. Phase 2: Connect sandbox/dev org for check automation and evidence collection.
3. Phase 3: Promote to production orgs after tuning and approval.

## Directory Layout
- `config/oscal-salesforce/sbs_source.yaml`: version-pinned SBS source configuration.
- `config/oscal-salesforce/control_mapping.yaml`: map internal/gap IDs to SBS control IDs.
- `config/oscal-salesforce/sbs_to_sscf_mapping.yaml`: map SBS controls/categories to CSA SSCF controls.
- `scripts/oscal_import_sbs.py`: import SBS XML and normalize controls.
- `scripts/oscal_gap_map.py`: apply mappings and generate backlog + scorecard artifacts.

## Inputs
- Existing gap-analysis export (JSON), expected shape:
  - `assessment_id`
  - `assessment_time_utc`
  - `findings[]` with at least:
    - `control_id` (internal legacy ID)
    - `status` (`pass|fail|partial|not_applicable`)
    - `severity` (`critical|high|medium|low`)
    - optional `owner`, `remediation`, `due_date`, `evidence_ref`
- Sample input for dry runs:
  - `docs/oscal-salesforce-poc/examples/gap-analysis-sample.json`
  - `docs/oscal-salesforce-poc/examples/gap-analysis-salesforce-collector-mock.json` (collector-style full control set)

## Outputs
- `docs/oscal-salesforce-poc/generated/sbs_controls.json`
- `docs/oscal-salesforce-poc/generated/salesforce_oscal_gap_matrix.md`
- `docs/oscal-salesforce-poc/generated/salesforce_oscal_backlog.json`

## Runbook (Phase 1)
```bash
cd /path/to/saas-posture

python3 scripts/oscal_import_sbs.py \
  --source-config config/oscal-salesforce/sbs_source.yaml \
  --out docs/oscal-salesforce-poc/generated/sbs_controls.json

python3 scripts/oscal_gap_map.py \
  --controls docs/oscal-salesforce-poc/generated/sbs_controls.json \
  --gap-analysis <PATH_TO_GAP_ANALYSIS_JSON> \
  --mapping config/oscal-salesforce/control_mapping.yaml \
  --sscf-map config/oscal-salesforce/sbs_to_sscf_mapping.yaml \
  --out-md docs/oscal-salesforce-poc/generated/salesforce_oscal_gap_matrix.md \
  --out-json docs/oscal-salesforce-poc/generated/salesforce_oscal_backlog.json
```

Resulting artifacts include `sscf_mappings` and flattened `sscf_control_ids` per mapped item.
Resulting mapped items also include `mapping_confidence` with aggregate `mapping_confidence_counts`.

## One-Command Smoke Test
```bash
cd /path/to/saas-posture
./scripts/oscal_smoke_test.sh
```

## Sandbox Hook (Phase 2)
Implement read-only collectors that emit the existing baseline schema and include SBS IDs:
- `collector.salesforce.auth`
- `collector.salesforce.access`
- `collector.salesforce.integrations`
- `collector.salesforce.deployment`

Each collector result should include:
- `sbs_control_id`
- `status`
- `evidence_ref`
- `observed_value`
- `expected_value`

## Promotion Gate (Phase 3)
Promote from sandbox to production only when:
- False positive rate is accepted by BSS + Security Team.
- Critical/High control checks have stable deterministic logic.
- Exception workflow and SLA reporting are integrated into monthly SaaS Risk Program governance.
