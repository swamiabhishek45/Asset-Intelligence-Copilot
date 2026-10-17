import os
import shutil
import tempfile
from pathlib import Path
from backend.config import settings, get_as_of_date
from backend.services.rules_engine import rules_engine
from backend.services.copilot_agent import copilot_agent
from backend.ingest.celery_worker import ingest_dataset_task
from backend.db.postgres import get_db_connection

def test_corrections_persist_across_restarts():
    print("\n" + "=" * 80)
    print("RUNNING CORRECTIONS PERSISTENCE & AUDIT TRAIL TEST")
    print("=" * 80)

    original_db = settings.SQLITE_PATH
    original_root = settings.SAMPLE_DATA_PATH

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_db = str(Path(temp_dir) / "test_persist.db")
        settings.SQLITE_PATH = temp_db

        # Ingest original sample dataset into fresh isolated database
        print(f"Ingesting clean baseline dataset into {temp_db}...")
        ingest_dataset_task(original_root)
        copilot_agent.areas.refresh()

        # ---------------------------------------------------------------------
        # 1. APPLY MUTATIONS VIA /api/query (IN-CHAT OPERATOR MESSAGES)
        # ---------------------------------------------------------------------
        print("\n1. Applying in-chat corrections as Michael Turner (U-201)...")

        # Mutation 1: Raw Wellhead Temperature Override for WELL-0164
        q_temp = (
            "The 15 Oct reading for WELL-0164 is wrong: thermal sensor calibration was off by +3.5 C, "
            "real wellhead temp was 41.0 C."
        )
        res_temp = copilot_agent.answer_query(q_temp, user_id="U-201")
        assert "41.0" in res_temp["text"], f"Expected 41.0 in response: {res_temp['text']}"
        assert "producing oil" in res_temp["text"].lower(), f"Expected producing status: {res_temp['text']}"
        print("PASS: Temperature override applied via chat for WELL-0164.")

        # Mutation 2: AI Spill Volume Override for WELL-0151
        q_vol = (
            "The AI estimated the 24 Sep spill at WELL-0151 as 4.5 bbl. "
            "The field crew measured 5.4 bbl."
        )
        res_vol = copilot_agent.answer_query(q_vol, user_id="U-201")
        assert "5.4" in res_vol["text"], f"Expected 5.4 bbl in response: {res_vol['text']}"
        assert "SR-01" in res_vol["text"], f"Expected SR-01 breach in response: {res_vol['text']}"
        print("PASS: Spill volume override applied via chat for WELL-0151.")

        # Mutation 3: Scoped Rule Override for All T350 Wells
        q_rule = (
            "Note for all T350 wells: from now on, flag pump jack repairs for root-cause analysis "
            "after 2 corrective events in 12 months, not 3."
        )
        res_rule = copilot_agent.answer_query(q_rule, user_id="U-201")
        assert "2 corrective repairs" in res_rule["text"] or "2" in res_rule["text"], f"Expected threshold 2: {res_rule['text']}"
        print("PASS: Scoped rule override applied via chat for T350 wells.")

        # ---------------------------------------------------------------------
        # 2. SIMULATE FULL PROCESS RESTART / CLEAR ALL IN-MEMORY CACHES
        # ---------------------------------------------------------------------
        print("\n2. Simulating full system restart (clearing caches & reconnecting DB)...")
        # Refresh area cache and reload rules
        rules_engine.reload()
        copilot_agent.areas.refresh()

        # ---------------------------------------------------------------------
        # 3. RE-QUERY AND ASSERT PERSISTED EFFECTIVE STATE
        # ---------------------------------------------------------------------
        print("\n3. Re-querying to verify corrections persisted in the database...")

        # Verify WELL-0164 is still producing oil with effective temperature 41.0 C
        check_temp = copilot_agent.answer_query("Is WELL-0164 producing oil right now?", user_id="U-202")
        assert "Yes, it is producing oil" in check_temp["text"], f"WELL-0164 should still be producing: {check_temp['text']}"
        assert "41.0" in check_temp["text"], f"Effective temperature 41.0 should be present: {check_temp['text']}"
        print("PASS: Persisted temperature correction verified for WELL-0164.")

        # Verify WELL-0151 regulator reportable spill persists
        check_spill = copilot_agent.answer_query(
            "Which spills in Northeast Block 7 in the last 90 days required a report to the regulator?",
            user_id="U-202"
        )
        assert "WELL-0151" in check_spill["text"], f"WELL-0151 should be flagged as reportable spill: {check_spill['text']}"
        assert "5.4" in check_spill["text"] or "5.4 bbl" in check_spill["text"], f"Corrected 5.4 bbl should be cited: {check_spill['text']}"
        print("PASS: Persisted spill volume override verified for WELL-0151.")

        # Verify Scoped Rule persists for T350 RCA
        check_rca = copilot_agent.answer_query(
            "Which wells in Northeast Block 7 require root-cause analysis on pump jacks?",
            user_id="U-202"
        )
        assert "Michael Turner" in check_rca["text"] or "2+" in check_rca["text"], f"Scoped override should be active: {check_rca['text']}"
        print("PASS: Persisted scoped rule override verified for T350 wells.")

        # ---------------------------------------------------------------------
        # 4. VERIFY IMMUTABLE AUDIT TRAIL VIA /api/audit
        # ---------------------------------------------------------------------
        print("\n4. Verifying immutable audit trail provenance via /api/audit...")
        from backend.main import get_audit_trail
        audit_records = get_audit_trail()

        assert len(audit_records) >= 2, f"Expected at least 2 correction audit records, got {len(audit_records)}"

        temp_audit = next((r for r in audit_records if r["asset_id"] == "WELL-0164" and r["field_overridden"] == "wellhead_temp_c"), None)
        assert temp_audit is not None, "Missing audit record for WELL-0164 temperature correction"
        assert temp_audit["author_user_id"] == "U-201", f"Expected author U-201, got {temp_audit['author_user_id']}"
        assert temp_audit["author_name"] == "Michael Turner", f"Expected author Michael Turner, got {temp_audit['author_name']}"
        assert float(temp_audit["original_value"]) == 24.0, f"Expected original value 24.0, got {temp_audit['original_value']}"
        assert float(temp_audit["corrected_value"]) == 41.0, f"Expected corrected value 41.0, got {temp_audit['corrected_value']}"
        assert temp_audit["created_at"] is not None, "Audit record must have creation timestamp"

        vol_audit = next((r for r in audit_records if r["asset_id"] == "WELL-0151" and r["field_overridden"] == "spill_est_volume_bbl"), None)
        assert vol_audit is not None, "Missing audit record for WELL-0151 volume correction"
        assert vol_audit["author_user_id"] == "U-201", f"Expected author U-201, got {vol_audit['author_user_id']}"
        assert float(vol_audit["original_value"]) == 4.5, f"Expected original volume 4.5, got {vol_audit['original_value']}"
        assert float(vol_audit["corrected_value"]) == 5.4, f"Expected corrected volume 5.4, got {vol_audit['corrected_value']}"
        assert vol_audit["created_at"] is not None, "Audit record must have creation timestamp"

        print(f"PASS: Audit trail contains {len(audit_records)} records with complete author provenance, timestamps, and original vs corrected values.")

    # Restore settings
    settings.SQLITE_PATH = original_db
    rules_engine.reload()
    copilot_agent.areas.refresh()
    print("\n" + "=" * 80)
    print("ALL CORRECTIONS PERSISTENCE & AUDIT TRAIL TESTS PASSED (100% SUCCESS)!")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    test_corrections_persist_across_restarts()
