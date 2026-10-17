import os
import csv
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from backend.config import settings, get_as_of_date
from backend.services.rules_engine import rules_engine
from backend.services.copilot_agent import copilot_agent
from backend.ingest.celery_worker import ingest_dataset_task
from backend.db.postgres import get_db_connection, init_database

def generate_and_test_synthetic_dataset():
    print("\n" + "=" * 80)
    print("RUNNING DYNAMIC SYNTHETIC DATASET GENERATION & GENERALIZATION TEST")
    print("=" * 80)

    original_root = settings.SAMPLE_DATA_PATH
    original_db = settings.SQLITE_PATH

    with tempfile.TemporaryDirectory() as temp_dir:
        synth_root = Path(temp_dir) / "synthetic-dataset"
        synth_root.mkdir(parents=True)
        temp_db_path = str(Path(temp_dir) / "synth_asset_intelligence.db")

        # Route SQLite to temp database for 100% clean isolation
        settings.SQLITE_PATH = temp_db_path

        # ---------------------------------------------------------------------
        # 1. GENERATE FLEET METADATA (5TH AREA: Northwest Block 1 / NW-01)
        # ---------------------------------------------------------------------
        fleet_dir = synth_root / "fleet"
        fleet_dir.mkdir(parents=True)

        well_ids = [f"WELL-{i:04d}" for i in range(201, 221)]  # WELL-0201 to WELL-0220

        areas_data = {
            "areas": [
                {
                    "area_id": "NW-01",
                    "name": "Northwest Block 1",
                    "team_id": "TEAM-NW",
                    "center": {"lat": 32.500, "lon": -102.800},
                    "asset_ids": well_ids
                }
            ],
            "teams": [
                {
                    "team_id": "TEAM-NW",
                    "name": "Northwest Operations",
                    "lead_user_id": "U-501"
                }
            ]
        }
        (fleet_dir / "areas.json").write_text(json.dumps(areas_data, indent=2), encoding="utf-8")

        users_data = {
            "users": [
                {"user_id": "U-501", "name": "Morgan Vance", "role": "production_supervisor", "team_id": "TEAM-NW"},
                {"user_id": "U-502", "name": "Alex Mercer", "role": "field_inspector", "team_id": "TEAM-NW"},
                {"user_id": "U-503", "name": "Jordan Hayes", "role": "maintenance_technician", "team_id": "TEAM-NW"}
            ]
        }
        (fleet_dir / "users.json").write_text(json.dumps(users_data, indent=2), encoding="utf-8")

        # Copy well-types and SOPs from original
        well_types_dir = fleet_dir / "well-types"
        shutil.copytree(Path(original_root) / "fleet" / "well-types", well_types_dir)
        sops_dir = fleet_dir / "sops"
        shutil.copytree(Path(original_root) / "fleet" / "sops", sops_dir)

        # ---------------------------------------------------------------------
        # 2. GENERATE SYNTHETIC ASSET DATA (WELL-0201 to WELL-0220)
        # ---------------------------------------------------------------------
        assets_dir = synth_root / "assets"
        assets_dir.mkdir()

        # Target ground truth values to assert:
        # Ground Truth 1: WELL-0201 (T350) -> Producing oil (wellhead 45°C - air 20°C = 25°C >= 20°C)
        # Ground Truth 2: WELL-0202 (T200) -> Offline (wellhead 25°C - air 22°C = 3°C < 15°C)
        # Ground Truth 3: WELL-0202 downtime in 2026 -> 4 non-producing inspections * 7 = 28 days
        # Ground Truth 4: WELL-0203 -> 1 spill of 7.5 bbl on 2026-08-15 (SR-01 reportable notice breach)
        # Ground Truth 5: WELL-0204 -> 1 spill of 2.2 bbl on 2026-09-10 (Pin at 32.510, -102.810)

        for wid in well_ids:
            wdir = assets_dir / wid
            wdir.mkdir()

            w_num = int(wid.split("-")[1])
            w_type = "T350" if w_num % 2 == 1 else "T200"

            # metadata.json
            well_meta = {
                "asset_id": wid,
                "name": f"Northwest Deep {w_num}",
                "well_type": w_type,
                "area_id": "NW-01",
                "team_id": "TEAM-NW",
                "location": {"lat": 32.500 + (w_num - 200) * 0.005, "lon": -102.800 + (w_num - 200) * 0.005},
                "recorded_status": "active",
                "installed_on": "2023-01-15",
                "equipment": [{"kind": "pump_jack", "model": "Lufkin 320"}]
            }
            (wdir / "metadata.json").write_text(json.dumps(well_meta, indent=2), encoding="utf-8")

            # inspections.jsonl
            insp_records = []
            if wid == "WELL-0201":
                # Producing T350
                insp_records.append({
                    "inspection_id": f"INS-{w_num}-01", "asset_id": wid,
                    "inspected_at": "2026-10-15T09:00:00Z", "inspector_user_id": "U-502",
                    "method": "drone", "ambient_temp_c": 20.0, "wellhead_temp_c": 45.0,
                    "spill_detected": 0, "spill_area_pct": 0.0, "spill_est_volume_bbl": 0.0,
                    "notes": "Operating nominally"
                })
            elif wid == "WELL-0202":
                # Non-producing T200 on 4 consecutive weekly inspections
                for k, dt_str in enumerate(["2026-09-24", "2026-10-01", "2026-10-08", "2026-10-15"], 1):
                    insp_records.append({
                        "inspection_id": f"INS-{w_num}-0{k}", "asset_id": wid,
                        "inspected_at": f"{dt_str}T09:00:00Z", "inspector_user_id": "U-502",
                        "method": "drone" if k < 4 else "manual", "ambient_temp_c": 22.0, "wellhead_temp_c": 25.0,
                        "spill_detected": 0, "spill_area_pct": 0.0, "spill_est_volume_bbl": 0.0,
                        "notes": "Cold wellhead" if k < 4 else "Stuffing box repair pending"
                    })
            elif wid == "WELL-0203":
                # Producing with a 7.5 bbl spill on 2026-08-15
                insp_records.append({
                    "inspection_id": f"INS-{w_num}-01", "asset_id": wid,
                    "inspected_at": "2026-08-15T09:00:00Z", "inspector_user_id": "U-502",
                    "method": "drone", "ambient_temp_c": 20.0, "wellhead_temp_c": 42.0,
                    "spill_detected": 1, "spill_area_pct": 8.0, "spill_est_volume_bbl": 7.5,
                    "notes": "Crude release on pad"
                })
                insp_records.append({
                    "inspection_id": f"INS-{w_num}-02", "asset_id": wid,
                    "inspected_at": "2026-10-15T09:00:00Z", "inspector_user_id": "U-502",
                    "method": "drone", "ambient_temp_c": 20.0, "wellhead_temp_c": 42.0,
                    "spill_detected": 0, "spill_area_pct": 0.0, "spill_est_volume_bbl": 0.0,
                    "notes": "Cleaned"
                })
            elif wid == "WELL-0204":
                # Spill on 2026-09-10
                insp_records.append({
                    "inspection_id": f"INS-{w_num}-01", "asset_id": wid,
                    "inspected_at": "2026-09-10T09:00:00Z", "inspector_user_id": "U-502",
                    "method": "drone", "ambient_temp_c": 20.0, "wellhead_temp_c": 38.0,
                    "spill_detected": 1, "spill_area_pct": 3.0, "spill_est_volume_bbl": 2.2,
                    "notes": "Flowline seep"
                })
                insp_records.append({
                    "inspection_id": f"INS-{w_num}-02", "asset_id": wid,
                    "inspected_at": "2026-10-15T09:00:00Z", "inspector_user_id": "U-502",
                    "method": "drone", "ambient_temp_c": 20.0, "wellhead_temp_c": 38.0,
                    "spill_detected": 0, "spill_area_pct": 0.0, "spill_est_volume_bbl": 0.0,
                    "notes": "Repaired"
                })
            else:
                # Routine producing
                insp_records.append({
                    "inspection_id": f"INS-{w_num}-01", "asset_id": wid,
                    "inspected_at": "2026-10-15T09:00:00Z", "inspector_user_id": "U-502",
                    "method": "drone", "ambient_temp_c": 20.0, "wellhead_temp_c": 40.0,
                    "spill_detected": 0, "spill_area_pct": 0.0, "spill_est_volume_bbl": 0.0,
                    "notes": "Routine check"
                })

            with open(wdir / "inspections.jsonl", "w", encoding="utf-8") as f:
                for rec in insp_records:
                    f.write(json.dumps(rec) + "\n")

            # maintenance.jsonl
            mnt_records = []
            if wid == "WELL-0202":
                mnt_records.append({
                    "maintenance_id": f"MNT-{w_num}-01", "asset_id": wid,
                    "started_at": "2026-09-24T12:00:00Z", "completed_at": None,
                    "maintenance_type": "corrective", "equipment_kind": "downhole_pump",
                    "contractor": "Apex Well Services", "issue": "Pump seizure",
                    "action_taken": "Awaiting workover rig", "technician_user_id": "U-503",
                    "downtime_hours": 504.0, "cost_usd": {"labor": 4500.0, "parts": 8000.0, "total": 12500.0},
                    "triggered_by_inspection_id": f"INS-{w_num}-01", "report_file": None
                })
            with open(wdir / "maintenance.jsonl", "w", encoding="utf-8") as f:
                for rec in mnt_records:
                    f.write(json.dumps(rec) + "\n")

            # regulatory_events.jsonl
            with open(wdir / "regulatory_events.jsonl", "w", encoding="utf-8") as f:
                pass

            # context_notes.jsonl
            with open(wdir / "context_notes.jsonl", "w", encoding="utf-8") as f:
                pass

        # ---------------------------------------------------------------------
        # 3. HOT-LOAD INGESTION INTO THE RUNNING SYSTEM
        # ---------------------------------------------------------------------
        print(f"Hot-loading synthetic dataset from: {synth_root}")
        ingest_res = ingest_dataset_task(str(synth_root))
        print("Ingestion completed successfully.")

        # Re-initialize area resolver
        copilot_agent.areas.refresh()

        # ---------------------------------------------------------------------
        # 4. ASSERT GROUND TRUTHS ACROSS NATURAL-LANGUAGE PIPELINE
        # ---------------------------------------------------------------------
        print("\nVerifying Natural-Language Pipeline against Synthetic Ground Truths:")

        # Test 1: Single Well Status (WELL-0201 - T350 Producing)
        ans1 = copilot_agent.answer_query("Is WELL-0201 producing oil right now?", user_id="U-501")
        assert ans1["visual_type"] == "status_card", f"Expected status_card, got {ans1['visual_type']}"
        assert "Yes, it is producing oil" in ans1["text"], f"Ground truth mismatch for WELL-0201: {ans1['text']}"
        assert "25.0" in ans1["text"], f"Expected delta-T 25.0 in text: {ans1['text']}"
        print("PASS [Synth-1]: WELL-0201 correctly verified producing (delta-T=25.0C >= 20.0C).")

        # Test 2: Single Well Status (WELL-0202 - T200 Offline)
        ans2 = copilot_agent.answer_query("Check status of WELL-0202", user_id="U-501")
        assert "No, it is not producing oil" in ans2["text"], f"Ground truth mismatch for WELL-0202: {ans2['text']}"
        assert "3.0" in ans2["text"], f"Expected delta-T 3.0 in text: {ans2['text']}"
        print("PASS [Synth-2]: WELL-0202 correctly verified offline (delta-T=3.0C < 15.0C).")

        # Test 3: Offline Wells in 5th Area (Northwest Block 1 / NW-01)
        ans3 = copilot_agent.answer_query("Which wells in Northwest Block 1 are offline right now?", user_id="U-501")
        assert ans3["visual_type"] == "table"
        assert "WELL-0202" in ans3["text"], f"WELL-0202 should be offline: {ans3['text']}"
        assert "WELL-0201" not in ans3["text"], f"WELL-0201 is producing and should NOT be offline: {ans3['text']}"
        print("PASS [Synth-3]: Northwest Block 1 offline query correctly identified WELL-0202.")

        # Test 4: Abbreviation resolution for 5th Area ("NW-01" / "NW 1")
        ans4 = copilot_agent.answer_query("Show me offline wells in NW-01", user_id="U-501")
        assert "WELL-0202" in ans4["text"], f"Abbreviation NW-01 failed: {ans4['text']}"
        print("PASS [Synth-4]: Abbreviation NW-01 correctly resolved to Northwest Block 1.")

        # Test 5: Downtime calculation for WELL-0202 (4 weeks * 7 = 28 days)
        ans5 = copilot_agent.answer_query("How much downtime did WELL-0202 have in 2026?", user_id="U-501")
        assert "28 days down" in ans5["text"] or "28 days" in ans5["text"], f"Expected 28 days downtime, got: {ans5['text']}"
        print("PASS [Synth-5]: WELL-0202 downtime computed exactly as 28 days (4 non-producing inspections).")

        # Test 6: Spills for WELL-0203 (1 spill, 7.5 bbl)
        ans6 = copilot_agent.answer_query("How many spills occurred at WELL-0203?", user_id="U-501")
        assert "1 spills" in ans6["text"] or "1 spill" in ans6["text"], f"Expected 1 spill: {ans6['text']}"
        assert "7.5" in ans6["text"], f"Expected 7.5 bbl: {ans6['text']}"
        print("PASS [Synth-6]: WELL-0203 spill count (1 spill, 7.5 bbl) matches synthetic ground truth.")

        # Test 7: Map of spills in Northwest Block 1
        ans7 = copilot_agent.answer_query("Show me a map of spills in Northwest Block 1", user_id="U-501")
        assert ans7["visual_type"] == "map"
        pins = ans7["visual_payload"]["pins"]
        assert len(pins) == 2, f"Expected 2 spill pins (WELL-0203 & WELL-0204), got {len(pins)}"
        print(f"PASS [Synth-7]: Map returned exactly {len(pins)} pins in Northwest Block 1.")

        # Test 8: SOP Compliance Audit for WELL-0203 (SR-01 reportable threshold breached)
        ans8 = copilot_agent.answer_query("What rules has WELL-0203 broken in the last 12 months?", user_id="U-501")
        assert "SR-01" in ans8["text"], f"Expected SR-01 breach for 7.5 bbl spill: {ans8['text']}"
        print("PASS [Synth-8]: WELL-0203 SR-01 breach (7.5 bbl >= 5.0 bbl reportable threshold) correctly flagged.")

    # Restore original database and rules
    settings.SQLITE_PATH = original_db
    rules_engine.set_data_root(original_root)
    copilot_agent.areas.refresh()
    print("\n" + "=" * 80)
    print("ALL 8 SYNTHETIC DATASET GENERALIZATION TESTS PASSED PERFECTLY (100% SUCCESS)!")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    generate_and_test_synthetic_dataset()
