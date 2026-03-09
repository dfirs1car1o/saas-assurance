#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GEN_DIR="$ROOT/docs/oscal-salesforce-poc/generated"

echo "== OSCAL Smoke Test =="
echo "Repo: $ROOT"

if ! python3 -c "import yaml" >/dev/null 2>&1; then
  echo "ERROR: PyYAML is required for OSCAL scripts." >&2
  echo "Install in a venv and retry:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  source .venv/bin/activate" >&2
  echo "  pip install PyYAML" >&2
  exit 1
fi

mkdir -p "$GEN_DIR"

echo "[1/2] Import SBS controls"
python3 "$ROOT/scripts/oscal_import_sbs.py" \
  --source-config config/oscal-salesforce/sbs_source.yaml \
  --out docs/oscal-salesforce-poc/generated/sbs_controls.json

echo "[2/2] Map sample gap analysis to SBS + CSA SSCF"
python3 "$ROOT/scripts/oscal_gap_map.py" \
  --controls docs/oscal-salesforce-poc/generated/sbs_controls.json \
  --gap-analysis docs/oscal-salesforce-poc/examples/gap-analysis-salesforce-collector-mock.json \
  --mapping config/oscal-salesforce/control_mapping.yaml \
  --sscf-map config/oscal-salesforce/sbs_to_sscf_mapping.yaml \
  --out-md docs/oscal-salesforce-poc/generated/salesforce_oscal_gap_matrix.md \
  --out-json docs/oscal-salesforce-poc/generated/salesforce_oscal_backlog.json

echo "== Smoke Test Outputs =="
ls -la "$GEN_DIR"

echo "== Backlog Summary =="
python3 - <<'PY'
import json
from pathlib import Path
path = Path("docs/oscal-salesforce-poc/generated/salesforce_oscal_backlog.json")
data = json.loads(path.read_text())
print("framework:", data.get("framework"))
print("catalog_version:", data.get("catalog_version"))
print("mapped_findings:", data.get("summary", {}).get("mapped_findings"))
print("unmapped_findings:", data.get("summary", {}).get("unmapped_findings"))
print("mapping_confidence_counts:", data.get("summary", {}).get("mapping_confidence_counts"))
PY

echo "Smoke test complete."
