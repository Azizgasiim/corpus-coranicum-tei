#!/bin/bash
# Load Leeds Quranic Arabic Corpus into BigQuery
# Usage: ./load.sh [PROJECT_ID] [DATASET_NAME]
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - BigQuery API enabled
#
# Example:
#   ./load.sh my-project quran

set -euo pipefail

PROJECT="${1:-}"
DATASET="${2:-quran}"
DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$PROJECT" ]; then
    echo "Usage: $0 <project-id> [dataset-name]"
    echo "  project-id:   Your Google Cloud project ID"
    echo "  dataset-name:  BigQuery dataset name (default: quran)"
    exit 1
fi

echo "=== Loading Leeds Quranic Arabic Corpus into BigQuery ==="
echo "  Project: $PROJECT"
echo "  Dataset: $DATASET"
echo ""

# Create dataset if not exists
echo "1. Creating dataset ${DATASET}..."
bq --project_id="$PROJECT" mk --dataset --exists "${DATASET}" \
    --description "Quranic Arabic Corpus — morphological annotations"

# Load quran_text
echo "2. Loading quran_text (77,429 words)..."
bq --project_id="$PROJECT" load \
    --source_format=CSV \
    --skip_leading_rows=1 \
    --replace \
    --schema="${DIR}/quran_text.schema.json" \
    "${DATASET}.quran_text" \
    "${DIR}/quran_text.csv"

# Load leeds_morph
echo "3. Loading leeds_morph (130,030 morphemes)..."
bq --project_id="$PROJECT" load \
    --source_format=CSV \
    --skip_leading_rows=1 \
    --replace \
    --schema="${DIR}/leeds_morph.schema.json" \
    "${DATASET}.leeds_morph" \
    "${DIR}/leeds_morph.csv"

echo ""
echo "=== Done! ==="
echo ""
echo "Tables created:"
echo "  ${DATASET}.quran_text    — 77,429 rows (one per word)"
echo "  ${DATASET}.leeds_morph   — 130,030 rows (one per morpheme)"
echo ""
echo "Try: bq query --use_legacy_sql=false \\"
echo "  'SELECT * FROM ${DATASET}.quran_text WHERE surah=1 ORDER BY ayah, word_index'"
