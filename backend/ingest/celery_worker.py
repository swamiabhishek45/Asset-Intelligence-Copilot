import os
import json
import re
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.config import settings
from backend.db.postgres import get_db_connection, init_database
from backend.db.neo4j_graph import graph_service
from backend.services.cache_service import cache_service
from backend.services.vector_store import vector_store
from backend.ingest.parser import DatasetParser

logger = logging.getLogger(__name__)

try:
    from celery import Celery
    celery_app = Celery("aic_ingest", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
except ImportError:
    celery_app = None

def sync_all_entities_to_graph() -> Dict[str, Any]:
    """
    Reads all relational entities from SQL and synchronizes them to Neo4j (or In-Memory graph)
    using batch UNWIND queries (batch size = 1000).
    Runs a post-ingest consistency verification.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # 1. Areas
        cur.execute("SELECT area_id, name, team_id FROM areas")
        areas = [{"area_id": r["area_id"], "name": r["name"], "team_id": r.get("team_id")} for r in cur.fetchall()]

        # 2. Users
        cur.execute("SELECT user_id, name, role, team_id FROM users")
        users = [{"user_id": r["user_id"], "name": r["name"], "role": r.get("role"), "team_id": r.get("team_id")} for r in cur.fetchall()]

        # 3. Wells
        cur.execute("SELECT asset_id, well_type, area_id, recorded_status, lat, lon FROM wells")
        wells = [{
            "asset_id": r["asset_id"],
            "well_type": r["well_type"],
            "area_id": r["area_id"],
            "status": r["recorded_status"],
            "lat": r.get("lat"),
            "lon": r.get("lon")
        } for r in cur.fetchall()]

        # 4. Inspections
        cur.execute("""
            SELECT inspection_id, asset_id, inspected_at, method, spill_detected,
                   (wellhead_temp_c - ambient_temp_c) AS temp_delta_c
            FROM inspections
        """)
        inspections = [{
            "inspection_id": r["inspection_id"],
            "asset_id": r["asset_id"],
            "inspected_at": r["inspected_at"],
            "method": r.get("method"),
            "spill_detected": bool(r.get("spill_detected")),
            "temp_delta_c": r.get("temp_delta_c")
        } for r in cur.fetchall()]

        # 5. Maintenance
        cur.execute("""
            SELECT maintenance_id, asset_id, started_at, equipment_kind,
                   cost_total_usd, issue, report_file
            FROM maintenance
        """)
        maintenance = [{
            "maintenance_id": r["maintenance_id"],
            "asset_id": r["asset_id"],
            "started_at": r["started_at"],
            "equipment_kind": r.get("equipment_kind"),
            "cost_total_usd": r.get("cost_total_usd"),
            "issue": r.get("issue"),
            "report_file": r.get("report_file")
        } for r in cur.fetchall()]

        # 6. Regulatory Events
        cur.execute("""
            SELECT event_id, asset_id, event_date, protocol_id, agency, fine_usd
            FROM regulatory_events
        """)
        regulatory_events = [{
            "event_id": r["event_id"],
            "asset_id": r["asset_id"],
            "event_date": r["event_date"],
            "protocol_id": r.get("protocol_id"),
            "agency": r.get("agency"),
            "fine_usd": r.get("fine_usd")
        } for r in cur.fetchall()]

        # 7. Context Notes
        cur.execute("""
            SELECT note_id, asset_id, created_at, note_type, text, inspection_id
            FROM context_notes
        """)
        context_notes = [{
            "note_id": r["note_id"],
            "asset_id": r["asset_id"],
            "created_at": r["created_at"],
            "note_type": r.get("note_type"),
            "text": r.get("text"),
            "inspection_id": r.get("inspection_id")
        } for r in cur.fetchall()]

    # Push to Graph (Neo4j or In-Memory fallback)
    graph_service.sync_all_entities(
        wells=wells,
        areas=areas,
        users=users,
        inspections=inspections,
        maintenance=maintenance,
        regulatory_events=regulatory_events,
        context_notes=context_notes,
        batch_size=1000
    )

    # Post-Ingest Consistency Check
    sql_counts = {
        "wells": len(wells),
        "areas": len(areas),
        "users": len(users),
        "inspections": len(inspections),
        "maintenance": len(maintenance),
        "regulatory_events": len(regulatory_events),
        "context_notes": len(context_notes)
    }
    consistency = graph_service.verify_consistency(sql_counts)
    return consistency

def ingest_dataset_task(data_root: str = settings.SAMPLE_DATA_PATH, job_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Ingests dataset (fleet and assets) idempotently into database, graph, and vector store.
    Updates cache_service job progress and invalidates caches upon completion.
    """
    start_time = time.time()
    errors: List[str] = []

    if job_id:
        cache_service.update_job(job_id, status="processing")

    init_database()
    parser = DatasetParser(data_root)
    root = Path(data_root)

    # 1. Parse manuals (T200.md, T350.md)
    try:
        manual_rules = parser.parse_well_type_manuals()
    except Exception as e:
        logger.error(f"Failed to parse manuals: {e}")
        manual_rules = {}

    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Seed default scoped rules from manuals
        for wtype, rdict in manual_rules.items():
            for param, val in rdict.items():
                cur.execute(
                    """
                    SELECT id FROM scoped_rules WHERE scope_type = 'WELL_TYPE' AND scope_value = %s AND parameter_name = %s
                    """,
                    (wtype, param)
                )
                if not cur.fetchone():
                    cur.execute(
                        """
                        INSERT INTO scoped_rules (scope_type, scope_value, parameter_name, numeric_value, source_citation, is_user_override)
                        VALUES ('WELL_TYPE', %s, %s, %s, %s, FALSE)
                        """,
                        (wtype, param, val, f"{wtype}.md")
                    )

        # 2. Ingest fleet/areas.json and fleet/users.json
        areas_path = root / "fleet" / "areas.json"
        if areas_path.exists():
            try:
                areas_data = json.loads(areas_path.read_text(encoding="utf-8"))
                for t in areas_data.get("teams", []):
                    cur.execute(
                        """
                        INSERT INTO teams (team_id, name, lead_user_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (team_id) DO UPDATE SET name = EXCLUDED.name, lead_user_id = EXCLUDED.lead_user_id
                        """,
                        (t["team_id"], t["name"], t.get("lead_user_id"))
                    )
                for a in areas_data.get("areas", []):
                    cur.execute(
                        """
                        INSERT INTO areas (area_id, name, team_id, center_lat, center_lon)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (area_id) DO UPDATE SET name = EXCLUDED.name, team_id = EXCLUDED.team_id
                        """,
                        (a["area_id"], a["name"], a.get("team_id"), a["center"]["lat"], a["center"]["lon"])
                    )
            except Exception as e:
                msg = f"Failed to ingest areas.json: {e}"
                logger.error(msg)
                errors.append(msg)

        users_path = root / "fleet" / "users.json"
        if users_path.exists():
            try:
                users_data = json.loads(users_path.read_text(encoding="utf-8"))
                user_list = users_data if isinstance(users_data, list) else users_data.get("users", [])
                for u in user_list:
                    cur.execute(
                        """
                        INSERT INTO users (user_id, name, role, team_id)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id) DO UPDATE SET name = EXCLUDED.name, role = EXCLUDED.role, team_id = EXCLUDED.team_id
                        """,
                        (u["user_id"], u["name"], u["role"], u.get("team_id"))
                    )
            except Exception as e:
                msg = f"Failed to ingest users.json: {e}"
                logger.error(msg)
                errors.append(msg)

        # 3. Load wells in assets/WELL-*
        assets_dir = root / "assets"
        well_count, ins_count, mnt_count, reg_count, ctx_count = 0, 0, 0, 0, 0
        
        if assets_dir.exists():
            for well_dir in sorted(assets_dir.glob("WELL-*")):
                if not well_dir.is_dir():
                    continue
                well_count += 1
                meta_path = well_dir / "metadata.json"
                if not meta_path.exists():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    cur.execute(
                        """
                        INSERT INTO wells (asset_id, name, well_type, area_id, team_id, in_charge_user_id, lat, lon, installed_on, recorded_status, equipment_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (asset_id) DO UPDATE SET
                            recorded_status = EXCLUDED.recorded_status,
                            name = COALESCE(EXCLUDED.name, wells.name),
                            well_type = EXCLUDED.well_type,
                            area_id = COALESCE(EXCLUDED.area_id, wells.area_id),
                            team_id = COALESCE(EXCLUDED.team_id, wells.team_id),
                            in_charge_user_id = COALESCE(EXCLUDED.in_charge_user_id, wells.in_charge_user_id),
                            lat = EXCLUDED.lat,
                            lon = EXCLUDED.lon,
                            installed_on = COALESCE(EXCLUDED.installed_on, wells.installed_on)
                        """,
                        (
                            meta["asset_id"], meta.get("name"), meta["well_type"],
                            meta.get("area_id"), meta.get("team_id"), meta.get("in_charge_user_id"),
                            meta["location"]["lat"], meta["location"]["lon"],
                            meta.get("installed_on"), meta.get("recorded_status"),
                            json.dumps(meta.get("equipment", []))
                        )
                    )

                    # Inspections
                    for ins in parser.iter_jsonl(well_dir / "inspections.jsonl"):
                        ins_count += 1
                        cur.execute(
                            """
                            INSERT INTO inspections (
                                inspection_id, asset_id, inspected_at, inspector_user_id, method,
                                ambient_temp_c, wellhead_temp_c, spill_detected, spill_area_pct,
                                spill_est_volume_bbl, evidence_images, notes
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (inspection_id) DO NOTHING
                            """,
                            (
                                ins["inspection_id"], ins["asset_id"], ins["inspected_at"],
                                ins.get("inspector_user_id"), ins.get("method"),
                                ins["ambient_temp_c"], ins["wellhead_temp_c"],
                                ins["spill_detected"], ins.get("spill_area_pct"),
                                ins.get("spill_est_volume_bbl"),
                                json.dumps(ins.get("evidence_images", [])), ins.get("notes")
                            )
                        )

                    # Maintenance
                    for mnt in parser.iter_jsonl(well_dir / "maintenance.jsonl"):
                        mnt_count += 1
                        rep_info = parser.parse_maintenance_report_md(well_dir, mnt.get("report_file"))
                        cost = mnt.get("cost_usd", {})
                        cur.execute(
                            """
                            INSERT INTO maintenance (
                                maintenance_id, asset_id, started_at, completed_at, maintenance_type,
                                equipment_kind, issue, action_taken, technician_user_id, contractor,
                                downtime_hours, cost_labor_usd, cost_parts_usd, cost_total_usd,
                                triggered_by_inspection_id, report_file, report_markdown,
                                extracted_containment_hours, extracted_spill_class, extracted_action_required
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (maintenance_id) DO NOTHING
                            """,
                            (
                                mnt["maintenance_id"], mnt["asset_id"], mnt["started_at"],
                                mnt.get("completed_at"), mnt.get("maintenance_type"),
                                mnt.get("equipment_kind"), mnt.get("issue"), mnt.get("action_taken"),
                                mnt.get("technician_user_id"), mnt.get("contractor"),
                                mnt.get("downtime_hours"),
                                cost.get("labor", 0.0), cost.get("parts", 0.0), cost.get("total", 0.0),
                                mnt.get("triggered_by_inspection_id"), mnt.get("report_file"),
                                rep_info["report_markdown"], rep_info["extracted_containment_hours"],
                                rep_info["extracted_spill_class"], rep_info["extracted_action_required"]
                            )
                        )

                    # Regulatory Events
                    for reg in parser.iter_jsonl(well_dir / "regulatory-events.jsonl"):
                        reg_count += 1
                        cur.execute(
                            """
                            INSERT INTO regulatory_events (
                                event_id, asset_id, event_date, agency, event_type,
                                protocol_id, related_inspection_id, hours_to_report,
                                detail, fine_usd, status
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (event_id) DO NOTHING
                            """,
                            (
                                reg["event_id"], reg["asset_id"], reg["date"], reg.get("agency"),
                                reg.get("event_type"), reg.get("protocol_id"),
                                reg.get("related_inspection_id"), reg.get("hours_to_report"),
                                reg.get("detail"), reg.get("fine_usd", 0.0), reg.get("status")
                            )
                        )

                    # Context Notes
                    for ctx in parser.iter_jsonl(well_dir / "context.jsonl"):
                        ctx_count += 1
                        field_overridden, corrected_val = None, None
                        if ctx.get("note_type") == "correction" and ctx.get("inspection_id"):
                            if re.search(r"rainwater|puddle|not\s+oil|not\s+a\s+crude\s+spill|not\s+a\s+spill|water|shadow|false", ctx.get("text", ""), re.I):
                                field_overridden = "spill_detected"
                                corrected_val = "false"
                        cur.execute(
                            """
                            INSERT INTO context_notes (
                                note_id, asset_id, created_at, author_user_id, note_type,
                                inspection_id, text, valid_from, valid_to,
                                field_overridden, corrected_value, verification_status
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'confirmed')
                            ON CONFLICT (note_id) DO NOTHING
                            """,
                            (
                                ctx["note_id"], ctx["asset_id"], ctx["created_at"],
                                ctx.get("author_user_id"), ctx.get("note_type"),
                                ctx.get("inspection_id"), ctx["text"],
                                ctx.get("valid_from"), ctx.get("valid_to"),
                                field_overridden, corrected_val
                            )
                        )
                except Exception as e:
                    msg = f"Failed processing {well_dir.name}: {e}"
                    logger.error(msg)
                    errors.append(msg)

        conn.commit()

    # 4. Sync to Graph with UNWIND in batches of 1000 & verify consistency
    consistency = sync_all_entities_to_graph()
    if not consistency.get("consistent", True):
        for mm in consistency.get("mismatches", []):
            errors.append(mm)

    # 5. Index Document Embeddings (pgvector / fallback)
    indexed_doc_count = 0
    try:
        indexed_doc_count = vector_store.index_documents(data_root)
    except Exception as e:
        msg = f"Vector indexing failed: {e}"
        logger.error(msg)
        errors.append(msg)

    # 6. Invalidate caches and bump data version
    settings.DATA_VERSION = f"v_{int(time.time())}"
    cache_service.invalidate_all_queries()

    duration = round(time.time() - start_time, 2)
    final_status = "completed" if len(errors) == 0 else ("completed_with_warnings" if not any("Critical" in err for err in errors) else "failed")
    
    counts = {
        "wells": well_count,
        "inspections": ins_count,
        "maintenance": mnt_count,
        "regulatory_events": reg_count,
        "context_notes": ctx_count,
        "docs_indexed": indexed_doc_count
    }

    if job_id:
        cache_service.update_job(
            job_id,
            status=final_status,
            counts=counts,
            duration_seconds=duration,
            errors=errors
        )

    logger.info(f"Ingestion {final_status} in {duration}s. Counts: {counts}")
    return {
        "status": final_status,
        "job_id": job_id,
        "data_version": settings.DATA_VERSION,
        "counts": counts,
        "consistency": consistency,
        "duration_seconds": duration,
        "errors": errors
    }

if celery_app:
    ingest_dataset_task = celery_app.task(name="ingest_dataset_task")(ingest_dataset_task)

if __name__ == "__main__":
    result = ingest_dataset_task()
    print("Ingestion completed:", result)
