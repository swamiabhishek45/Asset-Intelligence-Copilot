import os
import sys
import json
import time
import argparse
import logging
import urllib.request
from typing import List, Dict, Any, Optional
from pathlib import Path

from backend.config import settings
from backend.db.postgres import get_db_connection

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

try:
    from neo4j import GraphDatabase
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False

# =============================================================================
# 1. EMBEDDING GENERATOR (OPENAI text-embedding-3-small)
# =============================================================================

class EmbeddingService:
    """Computes vector embeddings for entities using OpenAI API."""
    def __init__(self, api_key: str = settings.OPENAI_API_KEY, model: str = settings.EMBEDDING_MODEL):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model

    def get_embeddings(self, texts: List[str], batch_size: int = 50) -> List[List[float]]:
        if not self.api_key:
            logger.warning("No OPENAI_API_KEY provided. Returning zero-vectors.")
            return [[0.0] * 1536 for _ in texts]

        results = []
        for i in range(0, len(texts), batch_size):
            batch = [t[:4000].replace("\n", " ") for t in texts[i:i + batch_size]]
            url = "https://api.openai.com/v1/embeddings"
            req_data = json.dumps({"input": batch, "model": self.model}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    results.extend([item["embedding"] for item in data["data"]])
            except Exception as e:
                logger.error(f"Error fetching embeddings from OpenAI: {e}")
                results.extend([[0.0] * 1536 for _ in batch])
        return results

    def get_single_embedding(self, text: str) -> List[float]:
        res = self.get_embeddings([text])
        return res[0] if res else [0.0] * 1536


# =============================================================================
# 2. NEO4J INGESTION & GRAPH POPULATION PIPELINE
# =============================================================================

class Neo4jDatasetIngestor:
    """
    Connects to Neo4j (Local or AuraDB), initializes constraints, generates
    vector embeddings for domain knowledge, and batches entity/relation ingestion.
    """
    def __init__(
        self,
        uri: str = settings.NEO4J_URI,
        user: str = settings.NEO4J_USER,
        password: str = settings.NEO4J_PASSWORD
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.embedder = EmbeddingService()
        self.driver = None

    def connect(self) -> bool:
        if not HAS_NEO4J:
            logger.error("neo4j python package not installed.")
            return False

        if not self.password:
            logger.warning("Neo4j password not configured in .env. Skipping remote connection.")
            return False

        try:
            logger.info(f"Connecting to Neo4j at {self.uri} as {self.user}...")
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self.driver.verify_connectivity()
            logger.info("Neo4j connectivity verified successfully!")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j at {self.uri}: {e}")
            self.driver = None
            return False

    def close(self):
        if self.driver:
            self.driver.close()

    def create_constraints_and_indexes(self):
        """Initializes unique constraints and indexes for high-speed lookups."""
        if not self.driver:
            return

        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (w:Well) REQUIRE w.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Area) REQUIRE a.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Inspection) REQUIRE i.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Maintenance) REQUIRE m.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:RegulatoryEvent) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:ContextNote) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:SOP) REQUIRE s.id IS UNIQUE",
            "CREATE INDEX IF NOT EXISTS FOR (w:Well) ON (w.area_id)",
            "CREATE INDEX IF NOT EXISTS FOR (i:Inspection) ON (i.asset_id)",
            "CREATE INDEX IF NOT EXISTS FOR (m:Maintenance) ON (m.asset_id)",
        ]
        with self.driver.session() as session:
            for q in queries:
                try:
                    session.run(q)
                except Exception as e:
                    logger.warning(f"Error creating constraint/index: {e}")

    def ingest_full_dataset(self, embed_text: bool = True):
        """Extracts dataset entities and ingests into Neo4j with embeddings."""
        if not self.driver:
            logger.warning("No active Neo4j driver connection. Aborting ingestion.")
            return False

        self.create_constraints_and_indexes()

        with get_db_connection() as conn:
            cur = conn.cursor()

            # -----------------------------------------------------------------
            # 1. Ingest Areas & Wells
            # -----------------------------------------------------------------
            logger.info("Ingesting Areas and Wells...")
            cur.execute("SELECT area_id, name FROM areas")
            areas = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT w.asset_id, w.well_type, w.area_id, a.name AS area_name,
                       w.lat, w.lon, w.recorded_status
                FROM wells w
                JOIN areas a ON w.area_id = a.area_id
                """
            )
            wells = [dict(r) for r in cur.fetchall()]

            # Generate embeddings for wells
            well_texts = [
                f"Well {w['asset_id']}: Type {w['well_type']} located in {w['area_name']} ({w['area_id']}), recorded status {w['recorded_status']}."
                for w in wells
            ]
            well_embeddings = self.embedder.get_embeddings(well_texts) if embed_text else [[0.0]*1536]*len(wells)

            for w, emb in zip(wells, well_embeddings):
                w["embedding"] = emb

            with self.driver.session() as session:
                session.run(
                    """
                    UNWIND $areas AS a
                    MERGE (area:Area {id: a.area_id})
                    SET area.name = a.name
                    """,
                    areas=areas
                )
                session.run(
                    """
                    UNWIND $wells AS w
                    MERGE (well:Well {id: w.asset_id})
                    SET well.well_type = w.well_type,
                        well.area_id = w.area_id,
                        well.area_name = w.area_name,
                        well.lat = w.lat,
                        well.lon = w.lon,
                        well.recorded_status = w.recorded_status,
                        well.embedding = w.embedding
                    WITH well, w
                    MATCH (area:Area {id: w.area_id})
                    MERGE (area)-[:CONTAINS]->(well)
                    """,
                    wells=wells
                )
            logger.info(f"Ingested {len(areas)} areas and {len(wells)} wells with CONTAINS edges.")

            # -----------------------------------------------------------------
            # 2. Ingest SOPs & Well Manuals (Domain Rules)
            # -----------------------------------------------------------------
            logger.info("Ingesting SOPs and Operating Manuals...")
            sops = [
                {
                    "id": "SOP-T200",
                    "title": "T200 Operations Manual",
                    "text": "T200 wells require wellhead temperature >= 15.0 °C above ambient to be producing oil. RCA required after 3 corrective repairs in 12 months."
                },
                {
                    "id": "SOP-T350",
                    "title": "T350 Operations Manual",
                    "text": "T350 wells require wellhead temperature >= 20.0 °C above ambient to be producing oil. RCA required after 3 corrective repairs in 12 months."
                },
                {
                    "id": "SOP-SR-01",
                    "title": "Spill Response Protocol SR-01",
                    "text": "Written notice to regulator required within 24 hours of discovering an oil spill >= 5.0 bbl."
                },
                {
                    "id": "SOP-SR-02",
                    "title": "Spill Response Protocol SR-02",
                    "text": "All spills must be contained within 4.0 hours of initial notification or emergency dispatch."
                },
                {
                    "id": "SOP-SR-03",
                    "title": "Spill Response Protocol SR-03",
                    "text": "Environmental agency verification of clean-up due within 60 days of discovery for reportable spills."
                },
                {
                    "id": "SOP-RC-04",
                    "title": "Regulatory Compliance Protocol RC-04",
                    "text": "Formal written response to Notice of Violation due within 30 days of issuance."
                }
            ]
            sop_embeddings = self.embedder.get_embeddings([s["text"] for s in sops]) if embed_text else [[0.0]*1536]*len(sops)
            for s, emb in zip(sops, sop_embeddings):
                s["embedding"] = emb

            with self.driver.session() as session:
                session.run(
                    """
                    UNWIND $sops AS s
                    MERGE (sop:SOP {id: s.id})
                    SET sop.title = s.title,
                        sop.text = s.text,
                        sop.embedding = s.embedding
                    """,
                    sops=sops
                )
                session.run(
                    """
                    MATCH (w:Well)
                    WHERE w.well_type = 'T200'
                    MATCH (s:SOP {id: 'SOP-T200'})
                    MERGE (w)-[:GOVERNED_BY]->(s)
                    """
                )
                session.run(
                    """
                    MATCH (w:Well)
                    WHERE w.well_type = 'T350'
                    MATCH (s:SOP {id: 'SOP-T350'})
                    MERGE (w)-[:GOVERNED_BY]->(s)
                    """
                )
            logger.info("Ingested SOPs with GOVERNED_BY edges.")

            # -----------------------------------------------------------------
            # 3. Ingest Inspections (from v_effective_inspections)
            # -----------------------------------------------------------------
            logger.info("Ingesting Inspections from governed v_effective_inspections...")
            cur.execute(
                """
                SELECT inspection_id, asset_id, inspected_at, method,
                       ambient_temp_c, effective_wellhead_temp_c, effective_temp_delta_c,
                       min_temp_delta_c, effective_spill_detected, effective_spill_volume_bbl,
                       inspector_notes
                FROM v_effective_inspections
                ORDER BY inspected_at DESC
                LIMIT 5000
                """
            )
            inspections = [dict(r) for r in cur.fetchall()]

            with self.driver.session() as session:
                session.run(
                    """
                    UNWIND $inspections AS i
                    MERGE (ins:Inspection {id: i.inspection_id})
                    SET ins.asset_id = i.asset_id,
                        ins.inspected_at = i.inspected_at,
                        ins.method = i.method,
                        ins.ambient_temp_c = i.ambient_temp_c,
                        ins.wellhead_temp_c = i.effective_wellhead_temp_c,
                        ins.temp_delta_c = i.effective_temp_delta_c,
                        ins.spill_detected = i.effective_spill_detected,
                        ins.spill_volume_bbl = i.effective_spill_volume_bbl,
                        ins.notes = i.inspector_notes
                    WITH ins, i
                    MATCH (w:Well {id: i.asset_id})
                    MERGE (w)-[:HAS_INSPECTION]->(ins)
                    """,
                    inspections=inspections
                )
            logger.info(f"Ingested {len(inspections)} inspections with HAS_INSPECTION edges.")

            # -----------------------------------------------------------------
            # 4. Ingest Maintenance & Corrective Reports
            # -----------------------------------------------------------------
            logger.info("Ingesting Maintenance and Repair Reports...")
            cur.execute(
                """
                SELECT maintenance_id, asset_id, started_at, completed_at,
                       maintenance_type, equipment_kind, issue, action_taken,
                       downtime_hours, cost_total_usd, triggered_by_inspection_id,
                       report_file, extracted_containment_hours
                FROM maintenance
                """
            )
            maintenance = [dict(r) for r in cur.fetchall()]

            # Embed repair issues and action summaries
            mnt_texts = [
                f"Repair {m['maintenance_id']} on {m['asset_id']} ({m['equipment_kind']}): {m['issue']}. Action: {m['action_taken']}."
                for m in maintenance
            ]
            mnt_embeddings = self.embedder.get_embeddings(mnt_texts[:200]) if embed_text else []
            # pad remaining with dummy
            mnt_embeddings += [[0.0]*1536] * (len(maintenance) - len(mnt_embeddings))

            for m, emb in zip(maintenance, mnt_embeddings):
                m["embedding"] = emb

            with self.driver.session() as session:
                session.run(
                    """
                    UNWIND $maintenance AS m
                    MERGE (mnt:Maintenance {id: m.maintenance_id})
                    SET mnt.asset_id = m.asset_id,
                        mnt.started_at = m.started_at,
                        mnt.maintenance_type = m.maintenance_type,
                        mnt.equipment_kind = m.equipment_kind,
                        mnt.issue = m.issue,
                        mnt.action_taken = m.action_taken,
                        mnt.downtime_hours = m.downtime_hours,
                        mnt.cost_total_usd = m.cost_total_usd,
                        mnt.containment_hours = m.extracted_containment_hours,
                        mnt.report_file = m.report_file,
                        mnt.embedding = m.embedding
                    WITH mnt, m
                    MATCH (w:Well {id: m.asset_id})
                    MERGE (w)-[:HAS_MAINTENANCE]->(mnt)
                    """,
                    maintenance=maintenance
                )
                session.run(
                    """
                    UNWIND $maintenance AS m
                    WITH m WHERE m.triggered_by_inspection_id IS NOT NULL
                    MATCH (ins:Inspection {id: m.triggered_by_inspection_id})
                    MATCH (mnt:Maintenance {id: m.maintenance_id})
                    MERGE (ins)-[:TRIGGERED]->(mnt)
                    """,
                    maintenance=maintenance
                )
            logger.info(f"Ingested {len(maintenance)} maintenance records with TRIGGERED edges.")

            # -----------------------------------------------------------------
            # 5. Ingest Context Notes (Human Truth & Active Forgetting)
            # -----------------------------------------------------------------
            logger.info("Ingesting Context Notes...")
            cur.execute(
                """
                SELECT note_id, asset_id, created_at, note_type, inspection_id,
                       text, field_overridden, original_value, corrected_value, verification_status
                FROM context_notes
                WHERE COALESCE(verification_status, 'confirmed') != 'deleted_forgotten'
                """
            )
            notes = [dict(r) for r in cur.fetchall()]
            note_embeddings = self.embedder.get_embeddings([n["text"] for n in notes]) if embed_text else [[0.0]*1536]*len(notes)
            for n, emb in zip(notes, note_embeddings):
                n["embedding"] = emb

            with self.driver.session() as session:
                session.run(
                    """
                    UNWIND $notes AS n
                    MERGE (c:ContextNote {id: n.note_id})
                    SET c.asset_id = n.asset_id,
                        c.created_at = n.created_at,
                        c.note_type = n.note_type,
                        c.text = n.text,
                        c.field_overridden = n.field_overridden,
                        c.corrected_value = n.corrected_value,
                        c.verification_status = n.verification_status,
                        c.embedding = n.embedding
                    WITH c, n
                    MATCH (w:Well {id: n.asset_id})
                    MERGE (w)-[:HAS_NOTE]->(c)
                    """,
                    notes=notes
                )
                session.run(
                    """
                    UNWIND $notes AS n
                    WITH n WHERE n.inspection_id IS NOT NULL
                    MATCH (c:ContextNote {id: n.note_id})
                    MATCH (ins:Inspection {id: n.inspection_id})
                    MERGE (c)-[:CORRECTS]->(ins)
                    """,
                    notes=notes
                )
            logger.info(f"Ingested {len(notes)} context notes with CORRECTS edges.")

            # -----------------------------------------------------------------
            # 6. Ingest Regulatory Events
            # -----------------------------------------------------------------
            logger.info("Ingesting Regulatory Events...")
            cur.execute(
                """
                SELECT event_id, asset_id, event_date, agency, event_type,
                       protocol_id, related_inspection_id, hours_to_report, detail,
                       fine_usd, status
                FROM regulatory_events
                """
            )
            regs = [dict(r) for r in cur.fetchall()]

            with self.driver.session() as session:
                session.run(
                    """
                    UNWIND $regs AS r
                    MERGE (reg:RegulatoryEvent {id: r.event_id})
                    SET reg.asset_id = r.asset_id,
                        reg.event_date = r.event_date,
                        reg.agency = r.agency,
                        reg.event_type = r.event_type,
                        reg.protocol_id = r.protocol_id,
                        reg.detail = r.detail,
                        reg.fine_usd = r.fine_usd,
                        reg.status = r.status
                    WITH reg, r
                    MATCH (w:Well {id: r.asset_id})
                    MERGE (w)-[:HAS_REGULATORY_EVENT]->(reg)
                    """,
                    regs=regs
                )
            logger.info(f"Ingested {len(regs)} regulatory events.")

        logger.info("=" * 60)
        logger.info("NEO4J GRAPH INGESTION AND EMBEDDING COMPLETE!")
        logger.info("=" * 60)
        return True

def run_ingestion():
    parser = argparse.ArgumentParser(description="Ingest Asset Intelligence dataset into Neo4j with embeddings")
    parser.add_argument("--uri", default=settings.NEO4J_URI, help="Neo4j connection URI")
    parser.add_argument("--user", default=settings.NEO4J_USER, help="Neo4j username")
    parser.add_argument("--password", default=settings.NEO4J_PASSWORD, help="Neo4j password")
    parser.add_argument("--skip-embeddings", action="store_true", help="Skip OpenAI embedding calls")
    args = parser.parse_args()

    ingestor = Neo4jDatasetIngestor(uri=args.uri, user=args.user, password=args.password)
    connected = ingestor.connect()
    if not connected:
        print("\n" + "=" * 70)
        print("NEO4J CONNECTION STATUS: Not connected")
        print(f"Target URI: {args.uri}")
        print(f"Target User: {args.user}")
        print("\nTo connect and ingest into Neo4j AuraDB:")
        print("1. Update .env with your Neo4j Aura password:")
        print("   NEO4J_PASSWORD=your_actual_aura_password")
        print("2. Run the ingestion command:")
        print(f"   python -m backend.ingest.neo4j_embed_ingest --uri {args.uri} --user {args.user} --password <your_password>")
        print("=" * 70 + "\n")
        return

    ingestor.ingest_full_dataset(embed_text=not args.skip_embeddings)
    ingestor.close()

if __name__ == "__main__":
    run_ingestion()
