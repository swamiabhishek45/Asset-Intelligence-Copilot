import sys
import argparse
from pathlib import Path
from backend.config import settings
from backend.services.rules_engine import rules_engine
from backend.ingest.celery_worker import ingest_dataset_task
from backend.db.postgres import get_db_connection
from backend.db.neo4j_graph import graph_service
from backend.services.vector_store import vector_store

def main():
    parser = argparse.ArgumentParser(description="Ingest Asset Intelligence dataset into database, graph, and rules engine.")
    parser.add_argument("path", nargs="?", default=settings.SAMPLE_DATA_PATH, help="Path to the dataset directory")
    args = parser.parse_args()

    dataset_path = str(Path(args.path).resolve())
    print("=" * 80)
    print("FLYTEBASE ASSET INTELLIGENCE DATASET INGESTION CLI")
    print(f"Target Dataset Path: {dataset_path}")
    print("=" * 80)

    # 1. Update rules engine root and print parsed rules table
    rules_engine.set_data_root(dataset_path)
    rules_engine.print_rule_table()

    # 2. Ingest dataset
    print(f"\nStarting ingestion from: {dataset_path} ...")
    res = ingest_dataset_task(dataset_path)

    # 3. Print verification stats
    with get_db_connection() as conn:
        cur = conn.cursor()
        counts = {}
        for table in ["areas", "teams", "users", "wells", "inspections", "maintenance", "regulatory_events", "context_notes"]:
            cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
            counts[table] = cur.fetchone()["c"]

    # Graph stats
    graph_status = graph_service.get_status()
    graph_nodes = graph_service.get_label_counts()
    graph_edges = graph_service.get_relationship_counts()
    doc_chunks = vector_store.count_chunks()

    print("\n" + "=" * 80)
    print("INGESTION VERIFICATION REPORT")
    print("=" * 80)
    print("SQL Table Rows:")
    for tbl, cnt in counts.items():
        print(f"  - {tbl:<20}: {cnt}")
    
    print(f"\nGraph Engine: {graph_status.get('active_backend')} ({graph_status.get('status')})")
    print(f"  Total Nodes: {sum(graph_nodes.values())}")
    for lbl, cnt in sorted(graph_nodes.items()):
        print(f"    * {lbl:<18}: {cnt}")
    print(f"  Total Edges: {sum(graph_edges.values())}")
    for rel, cnt in sorted(graph_edges.items()):
        print(f"    * {rel:<18}: {cnt}")

    print(f"\nVector Store Embeddings:")
    print(f"  - Indexed Document Chunks: {doc_chunks}")

    consistency = res.get("consistency", {})
    is_consistent = consistency.get("consistent", False)
    print(f"\nConsistency Check: {'PASSED [OK]' if is_consistent else 'FAILED [MISMATCH]'}")
    if not is_consistent:
        for mm in consistency.get("mismatches", []):
            print(f"  ! {mm}")
    print(f"Duration: {res.get('duration_seconds')} seconds")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
