import os
import shutil
import tempfile
from pathlib import Path
from backend.config import settings
from backend.services.rules_engine import rules_engine
from backend.services.domain_tools import domain_engine

def test_sop_dynamic_variation():
    original_root = settings.SAMPLE_DATA_PATH
    print(f"Original data root: {original_root}")

    # Baseline check: with 4.0h limit, SW-24 has 2 breaches (WELL-0082 @ 7.1h, WELL-0100 @ 8.1h)
    rules_engine.set_data_root(original_root)
    assert rules_engine.sop_rules["SR-02"]["containment_limit_hours"] == 4.0, "Baseline SR-02 must be 4.0 hours"
    
    baseline_res = domain_engine.audit_sop_and_rca(area_name="Southwest Block 24", lookback_days=90)
    baseline_sr02 = [b for b in baseline_res["breaches"] if b["protocol_id"] == "SR-02"]
    assert len(baseline_sr02) == 2, f"Expected 2 baseline SR-02 breaches, got {len(baseline_sr02)}"
    print(f"PASS: Baseline verified with 2 breaches at 4.0h limit: {[b['asset_id'] for b in baseline_sr02]}")

    # Create temporary isolated directory with a copy of the fleet data
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        shutil.copytree(original_root, temp_path / "sample-data", dirs_exist_ok=True)
        data_copy = str(temp_path / "sample-data")
        sop_file = temp_path / "sample-data" / "fleet" / "sops" / "spill-response-sop.md"
        assert sop_file.exists(), f"Temp SOP file missing at {sop_file}"

        # 1. Edit spill-response-sop.md: Increase limit to 8.5 hours
        original_text = sop_file.read_text(encoding="utf-8")
        # Replace 4 hours / 4-hour containment limit with 8.5 hours
        modified_text = original_text.replace(
            "contained within **4 hours** of discovery",
            "contained within **8.5 hours** of discovery"
        ).replace(
            "4-hour containment limit (SR-02)",
            "8.5-hour containment limit (SR-02)"
        )
        sop_file.write_text(modified_text, encoding="utf-8")

        # Point rules engine to temp copy
        rules_engine.set_data_root(data_copy)
        assert rules_engine.sop_rules["SR-02"]["containment_limit_hours"] == 8.5, "SR-02 limit must update to 8.5 hours"

        # Re-run compliance check with zero code changes
        res_8_5 = domain_engine.audit_sop_and_rca(area_name="Southwest Block 24", lookback_days=90)
        sr02_8_5 = [b for b in res_8_5["breaches"] if b["protocol_id"] == "SR-02"]
        assert len(sr02_8_5) == 0, f"Expected 0 breaches at 8.5h limit (7.1h & 8.1h < 8.5h), got {len(sr02_8_5)}"
        print("PASS: Editing SOP to 8.5h resulted in 0 breaches (zero code edits).")

        # 2. Edit spill-response-sop.md: Set limit to 7.5 hours
        modified_text_2 = original_text.replace(
            "contained within **4 hours** of discovery",
            "contained within **7.5 hours** of discovery"
        ).replace(
            "4-hour containment limit (SR-02)",
            "7.5-hour containment limit (SR-02)"
        )
        sop_file.write_text(modified_text_2, encoding="utf-8")

        rules_engine.set_data_root(data_copy)
        assert rules_engine.sop_rules["SR-02"]["containment_limit_hours"] == 7.5, "SR-02 limit must update to 7.5 hours"

        # Re-run compliance check: WELL-0082 (7.1h) is compliant, WELL-0100 (8.1h) breaches
        res_7_5 = domain_engine.audit_sop_and_rca(area_name="Southwest Block 24", lookback_days=90)
        sr02_7_5 = [b for b in res_7_5["breaches"] if b["protocol_id"] == "SR-02"]
        assert len(sr02_7_5) == 1, f"Expected 1 breach at 7.5h limit, got {len(sr02_7_5)}"
        assert sr02_7_5[0]["asset_id"] == "WELL-0100", f"Expected WELL-0100, got {sr02_7_5[0]['asset_id']}"
        print("PASS: Editing SOP to 7.5h correctly flagged only WELL-0100 (zero code edits).")

    # Restore original rules root
    rules_engine.set_data_root(original_root)
    print("ALL SOP DYNAMIC VARIATION CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_sop_dynamic_variation()
