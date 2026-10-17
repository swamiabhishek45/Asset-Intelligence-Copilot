import unittest
from backend.db.postgres import get_db_connection, init_database
from backend.services.domain_tools import domain_engine
from backend.services.gatemem_policy import gatemem_service
from backend.services.copilot_agent import copilot_agent

class TestUnseenGeneralizationAndGateMem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database()

    def test_01_governed_view_rainwater_and_corrections(self):
        """Tests that v_effective_inspections SQL view directly incorporates corrections and overrides."""
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Rainwater false-positive exclusion (Q4)
            cur.execute("SELECT raw_spill_volume_bbl, effective_spill_detected FROM v_effective_inspections WHERE inspection_id = 'INS-0001-0070'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["effective_spill_detected"], 0, "INS-0001-0070 rainwater exclusion must reflect in SQL view")

            # Q12: Raw temperature correction on WELL-0164 (15 Oct reading is INS-0164-0205)
            cur.execute("SELECT raw_wellhead_temp_c, effective_wellhead_temp_c, effective_temp_delta_c FROM v_effective_inspections WHERE inspection_id = 'INS-0164-0205'")
            row_temp = cur.fetchone()
            self.assertIsNotNone(row_temp)
            self.assertEqual(row_temp["effective_wellhead_temp_c"], 41.0, "Q12 41.0°C override must reflect in SQL view")
            self.assertGreater(row_temp["effective_temp_delta_c"], 20.0)

            # Q13: Spill volume correction on WELL-0151
            cur.execute("SELECT raw_spill_volume_bbl, effective_spill_volume_bbl FROM v_effective_inspections WHERE inspection_id = 'INS-0151-0201'")
            row_spill = cur.fetchone()
            self.assertIsNotNone(row_spill)
            self.assertEqual(row_spill["effective_spill_volume_bbl"], 5.4, "Q13 5.4 bbl override must reflect in SQL view")

    def test_02_execute_safe_readonly_sql(self):
        """Tests security constraints on execute_safe_readonly_sql."""
        rows = domain_engine.execute_safe_readonly_sql("SELECT COUNT(*) AS total FROM v_effective_inspections")
        self.assertEqual(rows[0]["total"], 39567)

        # Mutating queries must be blocked
        with self.assertRaises(ValueError):
            domain_engine.execute_safe_readonly_sql("DROP TABLE wells")
        with self.assertRaises(ValueError):
            domain_engine.execute_safe_readonly_sql("DELETE FROM context_notes WHERE 1=1")
        with self.assertRaises(ValueError):
            domain_engine.execute_safe_readonly_sql("UPDATE wells SET recorded_status = 'active'")

    def test_03_unseen_contractor_analytics(self):
        """Tests unseen analytical routing for contractor expenditure and downtime."""
        res = copilot_agent.answer_query("Compare contractor repair costs and job counts across all wells", user_id="U-201")
        self.assertEqual(res["pipeline_telemetry"]["gatemem_action"], "unseen_analytics_computed")
        self.assertIn("Contractor", res["text"])
        self.assertGreater(len(res["visual_payload"]["rows"]), 0)
        self.assertGreater(len(res["citations"]), 0)

    def test_04_unseen_equipment_breakdown(self):
        """Tests unseen breakdown for equipment kinds (pump_jack, rod_string, etc.)."""
        res = copilot_agent.answer_query("Show equipment breakdown of failure jobs and costs for rod_string and separator", user_id="U-201")
        self.assertEqual(res["pipeline_telemetry"]["gatemem_action"], "unseen_analytics_computed")
        self.assertIn("Equipment", res["text"])
        self.assertGreater(len(res["visual_payload"]["rows"]), 0)

    def test_05_unseen_inspection_methods_drone_vs_manual(self):
        """Tests unseen comparative analytics for drone vs manual inspections."""
        res = copilot_agent.answer_query("Compare drone vs manual inspection counts and total spills found", user_id="U-201")
        self.assertEqual(res["pipeline_telemetry"]["gatemem_action"], "unseen_analytics_computed")
        self.assertIn("Drone", res["text"])
        self.assertIn("Manual", res["text"])
        self.assertGreater(len(res["visual_payload"]["rows"]), 0)

    def test_06_unseen_regulatory_agency_fines(self):
        """Tests unseen regulatory agency fine aggregation."""
        res = copilot_agent.answer_query("List total fines and open violation events grouped by regulatory agency", user_id="U-201")
        self.assertEqual(res["pipeline_telemetry"]["gatemem_action"], "unseen_analytics_computed")
        self.assertIn("Regulatory Agency", res["text"])
        self.assertGreater(len(res["visual_payload"]["rows"]), 0)

    def test_07_gatemem_active_forgetting(self):
        """
        Tests GateMem Active Forgetting (arXiv:2606.18829):
        1. Operator creates a runtime claim.
        2. Operator issues an active forgetting / retraction command.
        3. Record is tombstoned to 'deleted_forgotten' and redacted.
        4. In-chat probe returns 'no_memory' without leaking the forgotten claim.
        """
        # Step 1: Record runtime note
        fb = gatemem_service.apply_user_feedback(
            user_id="U-201",
            feedback_type="well_status_claim",
            asset_id="WELL-0099",
            text_reason="WELL-0099 test observation for active forgetting validation"
        )
        note_id = fb["recorded_note_id"]

        # Verify exists in context_notes
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT verification_status, text FROM context_notes WHERE note_id = %s", (note_id,))
            n = cur.fetchone()
            self.assertEqual(n["verification_status"], "confirmed")
            self.assertIn("test observation", n["text"])

        # Step 2: Issue in-chat active forgetting request
        res = copilot_agent.answer_query("Please forget note about WELL-0099", user_id="U-201")
        self.assertEqual(res["pipeline_telemetry"]["gatemem_action"], "no_memory")
        self.assertIn("GateMem Active Forgetting", res["text"])
        self.assertIn(note_id, res["visual_payload"]["deleted_note_ids"])

        # Step 3: Verify tombstoning in database
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT verification_status, text FROM context_notes WHERE note_id = %s", (note_id,))
            n_after = cur.fetchone()
            self.assertEqual(n_after["verification_status"], "deleted_forgotten")
            self.assertEqual(n_after["text"], "[REDACTED_BY_GATEMEM_ACTIVE_FORGETTING]")

        # Step 4: Verify evaluate_well_status does not leak the redacted note
        status = domain_engine.evaluate_well_status("WELL-0099")
        active_note_ids = [note["note_id"] for note in status["context_notes"]]
        self.assertNotIn(note_id, active_note_ids, "Forgotten note must never be returned in well status")

if __name__ == "__main__":
    unittest.main()
