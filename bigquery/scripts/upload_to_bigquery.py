#!/usr/bin/env python3
"""
Upload Leeds Quranic Arabic Corpus directly to BigQuery from this server.

Usage:
    python3 upload_to_bigquery.py --project=PROJECT_ID --key=service_account.json
    python3 upload_to_bigquery.py --project=PROJECT_ID --key=service_account.json --dataset=quran
"""

import argparse
import json
import os
import sys

from google.cloud import bigquery
from google.oauth2 import service_account


def load_table(client, dataset_id, table_name, csv_path, schema_path):
    """Load a CSV file into BigQuery table."""
    table_id = f"{client.project}.{dataset_id}.{table_name}"

    with open(schema_path, 'r') as f:
        schema_json = json.load(f)

    schema = [
        bigquery.SchemaField(
            name=field['name'],
            field_type=field['type'],
            mode=field.get('mode', 'NULLABLE'),
        )
        for field in schema_json
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    with open(csv_path, 'rb') as f:
        job = client.load_table_from_file(f, table_id, job_config=job_config)

    job.result()  # wait
    table = client.get_table(table_id)
    print(f"  ✓ {table_name}: {table.num_rows} rows loaded")
    return table.num_rows


def main():
    parser = argparse.ArgumentParser(description='Upload Quran corpus to BigQuery')
    parser.add_argument('--project', required=True, help='Google Cloud project ID')
    parser.add_argument('--key', required=True, help='Service account JSON key file')
    parser.add_argument('--dataset', default='quran', help='BigQuery dataset name (default: quran)')
    args = parser.parse_args()

    # Paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    leeds_dir = os.path.join(os.path.dirname(script_dir), 'leeds')

    # Validate files exist
    files = {
        'quran_text': {
            'csv': os.path.join(leeds_dir, 'quran_text.csv'),
            'schema': os.path.join(leeds_dir, 'quran_text.schema.json'),
        },
        'leeds_morph': {
            'csv': os.path.join(leeds_dir, 'leeds_morph.csv'),
            'schema': os.path.join(leeds_dir, 'leeds_morph.schema.json'),
        },
    }

    for name, paths in files.items():
        for kind, path in paths.items():
            if not os.path.exists(path):
                print(f"ERROR: {path} not found", file=sys.stderr)
                sys.exit(1)

    # Authenticate
    credentials = service_account.Credentials.from_service_account_file(
        args.key,
        scopes=['https://www.googleapis.com/auth/bigquery'],
    )
    client = bigquery.Client(project=args.project, credentials=credentials)
    print(f"Connected to project: {args.project}")

    # Create dataset
    dataset_ref = bigquery.Dataset(f"{args.project}.{args.dataset}")
    dataset_ref.location = "US"
    try:
        client.create_dataset(dataset_ref)
        print(f"Created dataset: {args.dataset}")
    except Exception as e:
        if 'Already Exists' in str(e):
            print(f"Dataset exists: {args.dataset}")
        else:
            raise

    # Load tables
    print("\nLoading tables...")
    total = 0
    for table_name, paths in files.items():
        total += load_table(client, args.dataset, table_name, paths['csv'], paths['schema'])

    print(f"\nDone! {total} total rows loaded into {args.dataset}.*")
    print(f"\nTest query:")
    print(f"  SELECT * FROM `{args.project}.{args.dataset}.quran_text` WHERE surah = 1 ORDER BY ayah, word_index")


if __name__ == '__main__':
    main()
