import pytest
from backend.services.copilot_agent import copilot_agent
from backend.db.postgres import get_db_connection

REPHRASING_SCENARIOS = [
    # -------------------------------------------------------------------------
    # Q1: Single Well Status Card (WELL-0001)
    # -------------------------------------------------------------------------
    ("Is WELL-0001 producing oil right now?", {"wid": "WELL-0001", "producing": False, "delta_t": 3.2, "visual": "status_card"}),
    ("Check production status for WELL-0001", {"wid": "WELL-0001", "producing": False, "delta_t": 3.2, "visual": "status_card"}),
    ("WELL-0001 status card please", {"wid": "WELL-0001", "producing": False, "delta_t": 3.2, "visual": "status_card"}),
    ("How is WELL-0001 doing right now?", {"wid": "WELL-0001", "producing": False, "delta_t": 3.2, "visual": "status_card"}),
    ("What's the status of well WELL-0001?", {"wid": "WELL-0001", "producing": False, "delta_t": 3.2, "visual": "status_card"}),

    # -------------------------------------------------------------------------
    # Q2: Offline Wells in Area (Northeast Block 8 / NE-8 / NE-08)
    # -------------------------------------------------------------------------
    ("Which wells in Northeast Block 8 are not producing oil right now?", {"wells": ["WELL-0164", "WELL-0170", "WELL-0172", "WELL-0175"], "visual": "table"}),
    ("Show me offline wells in NE-8", {"wells": ["WELL-0164", "WELL-0170", "WELL-0172", "WELL-0175"], "visual": "table"}),
    ("List non-producing wells in NE Block 8 right now", {"wells": ["WELL-0164", "WELL-0170", "WELL-0172", "WELL-0175"], "visual": "table"}),
    ("Which wells are shut in or stopped in NE-08?", {"wells": ["WELL-0164", "WELL-0170", "WELL-0172", "WELL-0175"], "visual": "table"}),
    ("Northeast Block 8 offline wells table", {"wells": ["WELL-0164", "WELL-0170", "WELL-0172", "WELL-0175"], "visual": "table"}),

    # -------------------------------------------------------------------------
    # Q3: Temperature Series / Line Chart (WELL-0001)
    # -------------------------------------------------------------------------
    ("Show temperature series for WELL-0001 over last 13 weeks", {"wid": "WELL-0001", "visual": "line_chart", "non_prod": ["2026-10-08", "2026-10-15"]}),
    ("WELL-0001 thermal history line chart", {"wid": "WELL-0001", "visual": "line_chart", "non_prod": ["2026-10-08", "2026-10-15"]}),
    ("Plot weekly temperature readings for WELL-0001 for the past 13 weeks", {"wid": "WELL-0001", "visual": "line_chart", "non_prod": ["2026-10-08", "2026-10-15"]}),
    ("Give me the last 13 weeks temperature readings for WELL-0001", {"wid": "WELL-0001", "visual": "line_chart", "non_prod": ["2026-10-08", "2026-10-15"]}),

    # -------------------------------------------------------------------------
    # Q4: Spill History for Well (WELL-0001)
    # -------------------------------------------------------------------------
    ("How many spills occurred at WELL-0001 over the last 4 years?", {"wid": "WELL-0001", "spills": 6, "volume": 15.1, "rainwater_noted": True}),
    ("WELL-0001 spill history and total volume in past 4 years", {"wid": "WELL-0001", "spills": 6, "volume": 15.1, "rainwater_noted": True}),
    ("Total barrels spilled at WELL-0001 over the last 4 years?", {"wid": "WELL-0001", "spills": 6, "volume": 15.1, "rainwater_noted": True}),
    ("List all verified crude oil spills for WELL-0001", {"wid": "WELL-0001", "spills": 6, "volume": 15.1, "rainwater_noted": True}),

    # -------------------------------------------------------------------------
    # Q5: Downtime for Well (WELL-0001 in 2025)
    # -------------------------------------------------------------------------
    ("How much downtime did WELL-0001 have in 2025?", {"wid": "WELL-0001", "days": 21, "inspections": 3}),
    ("Calculate 2025 downtime days for WELL-0001", {"wid": "WELL-0001", "days": 21, "inspections": 3}),
    ("WELL-0001 days down during 2025", {"wid": "WELL-0001", "days": 21, "inspections": 3}),
    ("Downtime days for WELL-0001 in 2025", {"wid": "WELL-0001", "days": 21, "inspections": 3}),

    # -------------------------------------------------------------------------
    # Q6: Top Downtime in Area (Northeast Block 7 / NE-7)
    # -------------------------------------------------------------------------
    ("Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months?", {"top_well": "WELL-0121", "days": 49, "visual": "bar_chart"}),
    ("Top 3 downtime wells in NE-7 over past 4 months", {"top_well": "WELL-0121", "days": 49, "visual": "bar_chart"}),
    ("Rank wells with most downtime in NE Block 7 last 4 months", {"top_well": "WELL-0121", "days": 49, "visual": "bar_chart"}),
    ("Bar chart of top downtime wells in NE-07 for the last 4 months", {"top_well": "WELL-0121", "days": 49, "visual": "bar_chart"}),

    # -------------------------------------------------------------------------
    # Q7: Map of Spills (Northeast Block 8 / NE-8)
    # -------------------------------------------------------------------------
    ("Show me a map of spills in Northeast Block 8 in the last 90 days", {"visual": "map", "pin_count": 4, "area": "Northeast Block 8"}),
    ("Pin map of verified spills in NE-8 last 90 days", {"visual": "map", "pin_count": 4, "area": "Northeast Block 8"}),
    ("Where were spills detected in NE Block 8 in past 90 days? Show pins", {"visual": "map", "pin_count": 4, "area": "Northeast Block 8"}),
    ("Map view of NE-08 spill locations over last 90 days", {"visual": "map", "pin_count": 4, "area": "Northeast Block 8"}),

    # -------------------------------------------------------------------------
    # Q8: Heatmap of Spills by Area and Month
    # -------------------------------------------------------------------------
    ("Show a heatmap of spills across areas and months in 2026", {"visual": "heatmap", "contains": ["Southwest Block 24", "43"]}),
    ("2026 monthly spill count heatmap by area", {"visual": "heatmap", "contains": ["Southwest Block 24", "43"]}),
    ("Area by month crude oil spill matrix heatmap", {"visual": "heatmap", "contains": ["Northeast Block 7", "37"]}),

    # -------------------------------------------------------------------------
    # Q9: Rules & SOP Compliance Audit (WELL-0001)
    # -------------------------------------------------------------------------
    ("What rules or SOPs has WELL-0001 broken in the last 12 months?", {"breaches": ["SR-01", "SR-02", "SR-03", "RC-04"], "rca": "flowline"}),
    ("WELL-0001 compliance audit and open violations", {"breaches": ["SR-01", "SR-02", "SR-03", "RC-04"], "rca": "flowline"}),
    ("Audit SOP compliance and open regulatory actions for WELL-0001", {"breaches": ["SR-01", "SR-02", "SR-03", "RC-04"], "rca": "flowline"}),

    # -------------------------------------------------------------------------
    # Q10: Containment Duration Breaches (Southwest Block 24 / SW-24)
    # -------------------------------------------------------------------------
    ("Which spills in Southwest Block 24 exceeded the 4-hour containment limit?", {"wells": ["WELL-0082", "WELL-0100"], "protocol": "SR-02"}),
    ("List spills in SW-24 not contained within SOP limit in past 90 days", {"wells": ["WELL-0082", "WELL-0100"], "protocol": "SR-02"}),
    ("SW Block 24 spills taking more than 4 hours to contain", {"wells": ["WELL-0082", "WELL-0100"], "protocol": "SR-02"}),

    # -------------------------------------------------------------------------
    # Clarifying Questions (Unplannable Ambiguous Queries)
    # -------------------------------------------------------------------------
    ("What is the downtime?", {"clarification": True, "missing": "asset_id_or_area"}),
    ("Calculate downtime", {"clarification": True, "missing": "asset_id_or_area"}),
    ("Is it producing?", {"clarification": True, "missing": "asset_id"}),
    ("Show me the temperature curve", {"clarification": True, "missing": "asset_id"}),

    # -------------------------------------------------------------------------
    # Unseen Dimension Analytics (Contractor, Equipment, Methods, Fines)
    # -------------------------------------------------------------------------
    ("Which contractor cost the most in repairs?", {"category": "contractor_analytics", "visual": "table"}),
    ("Break down failure costs by equipment kind", {"category": "equipment_analytics", "visual": "table"}),
    ("Compare drone vs manual inspection methods", {"category": "inspection_method_analytics", "visual": "bar_chart"}),
    ("What are the total fines across regulatory agencies?", {"category": "regulatory_agency_analytics", "visual": "table"}),
]

def test_all_rephrasings():
    print(f"\n================================================================================")
    print(f"RUNNING {len(REPHRASING_SCENARIOS)} REPHRASING & OPERATIONAL VARIANT BENCHMARKS")
    print(f"================================================================================")

    # Clean scoped rule user overrides before test
    with get_db_connection() as conn:
        conn.cursor().execute("DELETE FROM scoped_rules WHERE is_user_override = 1")
        conn.commit()

    passed = 0
    for idx, (query_text, expected) in enumerate(REPHRASING_SCENARIOS, 1):
        res = copilot_agent.answer_query(query_text, user_id="U-201", session_id=f"test-rep-{idx}")
        assert res is not None, f"Query '{query_text}' returned None"
        text = res.get("text", "")
        visual = res.get("visual_type", "")
        citations = res.get("citations", [])

        # 1. Single well status
        if "delta_t" in expected:
            assert "producing" in text.lower(), f"Failed producing check: {text}"
            assert f"{expected['delta_t']}" in text, f"Missing delta_t: {text}"
            assert visual == expected["visual"]

        # 2. Offline wells list
        if "wells" in expected and "not producing" in query_text.lower() or "offline" in query_text.lower() or "stopped" in query_text.lower():
            for w in expected["wells"]:
                assert w in text, f"Missing expected well {w} in response: {text}"
            assert visual == expected["visual"]

        # 3. Line chart / temperature curve
        if "non_prod" in expected:
            for np_date in expected["non_prod"]:
                assert np_date in text, f"Missing non-producing date {np_date} in: {text}"
            assert visual == expected["visual"]

        # 4. Spills count
        if "spills" in expected:
            assert f"{expected['spills']} spills" in text, f"Wrong spill count in: {text}"
            assert f"{expected['volume']}" in text, f"Wrong total volume in: {text}"

        # 5. Downtime days
        if "days" in expected and "top_well" not in expected:
            assert f"{expected['days']} days down" in text or f"{expected['days']} days" in text, f"Wrong downtime days in: {text}"

        # 6. Bar chart / top downtime
        if "top_well" in expected:
            assert expected["top_well"] in text, f"Missing top well {expected['top_well']} in: {text}"
            assert f"{expected['days']} days" in text, f"Missing top days {expected['days']} in: {text}"
            assert visual == expected["visual"]

        # 7. Map visual
        if "pin_count" in expected:
            assert visual == "map"
            assert len(res["visual_payload"]["pins"]) == expected["pin_count"]

        # 8. Heatmap visual
        if expected.get("visual") == "heatmap":
            assert visual == "heatmap"
            for c in expected.get("contains", []):
                assert c in text, f"Heatmap missing expected text '{c}': {text}"

        # 9. Compliance breaches
        if "breaches" in expected:
            for b in expected["breaches"]:
                assert b in text, f"Missing breach {b} in: {text}"
            assert expected["rca"] in text.lower(), f"Missing RCA equipment {expected['rca']}: {text}"

        # 10. Containment limits
        if "protocol" in expected:
            for w in expected["wells"]:
                assert w in text, f"Missing containment breach well {w} in: {text}"

        # 11. Clarifying questions
        if expected.get("clarification"):
            assert "?" in text, f"Clarification must ask a question: {text}"
            assert res["visual_payload"].get("missing_parameter") == expected["missing"]

        # 12. Unseen dimension analytics
        if "category" in expected:
            assert res["pipeline_telemetry"].get("gatemem_action") == "unseen_analytics_computed"
            assert visual == expected["visual"]

        # Invariant: citations must be present on all factual answers
        if not expected.get("clarification"):
            assert len(citations) > 0, f"Query '{query_text}' had empty citations!"

        passed += 1
        print(f"PASS [{idx:02d}/{len(REPHRASING_SCENARIOS):02d}]: '{query_text}' -> {visual}")

    print(f"\n================================================================================")
    print(f"ALL {passed}/{len(REPHRASING_SCENARIOS)} REPHRASINGS PASSED PERFECTLY (100% SUCCESS)!")
    print(f"================================================================================\n")

if __name__ == "__main__":
    test_all_rephrasings()
