import os
import json
import re
from pathlib import Path
from typing import Dict, Any, List

from backend.config import settings
from backend.db.postgres import get_db_connection, init_database
from backend.db.neo4j_graph import graph_service
from backend.ingest.parser import DatasetParser

try:
    from celery import Celery
    celery_app = Celery("aic_ingest", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
except ImportError:
    celery_app = None

def sync_anomalies_to_neo4j():
    """Populates graph nodes (Well, Area) and containment relationships."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT asset_id, well_type, area_id, recorded_status FROM wells")
        wells = [{"asset_id": r["asset_id"], "well_type": r["well_type"], "area_id": r["area_id"], "status": r["recorded_status"]} for r in cur.fetchall()]
        cur.execute("SELECT area_id, name FROM areas")
        areas = [{"area_id": r["area_id"], "name": r["name"]} for r in cur.fetchall()]
    
    graph_service.sync_nodes_and_edges(wells=wells, areas=areas)

def ingest_dataset_task(data_root: str = settings.SAMPLE_DATA_PATH) -> Dict[str, Any]:
    """Ingests dataset (fleet and assets) into database and graph."""
    init_database()
    parser = DatasetParser(data_root)
    root = Path(data_root)

    # 1. Parse manuals (T200.md, T350.md)
    manual_rules = parser.parse_well_type_manuals()

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

        users_path = root / "fleet" / "users.json"
        if users_path.exists():
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

        # 3. Load wells in assets/WELL-*
        assets_dir = root / "assets"
        well_count, ins_count, mnt_count = 0, 0, 0
        
        for well_dir in sorted(assets_dir.glob("WELL-*")):
            if not well_dir.is_dir():
                continue
            well_count += 1
            meta_path = well_dir / "metadata.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            cur.execute(
                """
                INSERT INTO wells (asset_id, name, well_type, area_id, team_id, in_charge_user_id, lat, lon, installed_on, recorded_status, equipment_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_id) DO UPDATE SET recorded_status = EXCLUDED.recorded_status
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
        conn.commit()

    # 4. Sync to graph
    sync_anomalies_to_neo4j()
    return {"status": "completed", "wells": well_count, "inspections": ins_count, "repairs": mnt_count}

if celery_app:
    ingest_dataset_task = celery_app.task(name="ingest_dataset_task")(ingest_dataset_task)

if __name__ == "__main__":
    result = ingest_dataset_task()
    print("Ingestion completed:", result)
