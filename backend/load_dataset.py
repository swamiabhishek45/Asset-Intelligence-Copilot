import sys
import argparse
from pathlib import Path
from backend.config import settings
from backend.services.rules_engine import rules_engine
from backend.ingest.celery_worker import ingest_dataset_task
from backend.db.postgres import get_db_connection

def main():
    parser = argparse.ArgumentParser(description="Ingest Asset Intelligence dataset into database, graph, and rules engine.")
    parser.add_argument("path", nargs="?", default=settings.SAMPLE_DATA_PATH, help="Path to the dataset directory")
    args = parser.parse_args()

    dataset_path = str(Path(args.path).resolve())
    print("=" * 80)
    print(f"FLYTEBASE ASSET INTELLIGENCE DATASET INGESTION CLI")
    print(f"Target Dataset Path: {dataset_path}")
    print("=" * 80)

    # 1. Update rules engine root and print parsed rules table
    rules_engine.set_data_root(dataset_path)
    rules_engine.print_rule_table()

    # 2. Ingest dataset
    print(f"Starting ingestion from: {dataset_path} ...")
    res = ingest_dataset_task(dataset_path)

    # 3. Print verification stats
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM wells")
        w_cnt = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM inspections")
        i_cnt = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM maintenance")
        m_cnt = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM areas")
        a_cnt = cur.fetchone()["c"]

    print("\n" + "=" * 80)
    print("INGESTION SUCCESSFUL!")
    print(f"- Areas Loaded: {a_cnt}")
    print(f"- Wells Loaded: {w_cnt}")
    print(f"- Inspections Loaded: {i_cnt}")
    print(f"- Maintenance Jobs Loaded: {m_cnt}")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
