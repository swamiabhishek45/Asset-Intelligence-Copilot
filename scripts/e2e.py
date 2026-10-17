#!/usr/bin/env python3
"""
End-to-End Automated HTTP Verification Suite (scripts/e2e.py)
Tests full stack HTTP API: health, typed endpoints, Q1-Q18 queries,
caching, feedback, GateMem memory governance, and ingestion pipeline.
Runnable inside and outside Docker.
"""
import sys
import os
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to sys.path so direct resets can run
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_URL = os.environ.get("AIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

def reset_db_runtime_state():
    """Resets runtime overrides and private sessions to pristine baseline."""
    try:
        http_post("/api/reset", {})
        print("[Setup] Pristine benchmark state restored via /api/reset.")
        return
    except Exception:
        pass

    try:
        from backend.db.postgres import get_db_connection
        from backend.services.cache_service import cache_service
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM context_notes WHERE note_id LIKE 'CTX-RT-%'")
            cur.execute("DELETE FROM scoped_rules WHERE is_user_override = 1")
            cur.execute("DELETE FROM private_user_sessions")
            conn.commit()
        cache_service.invalidate_all_queries()
        print("[Setup] Pristine benchmark state restored via direct DB.")
    except Exception as e:
        print(f"[Notice] Direct DB reset skipped ({e}), testing against live HTTP state.")

def http_get(path: str, timeout: int = 20) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))

def http_post(path: str, payload: Dict[str, Any], timeout: int = 35) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))

def run_suite():
    print("=" * 80)
    print(f"FLYTEBASE ASSET INTELLIGENCE COPILOT - END-TO-END HTTP SUITE")
    print(f"Target API Base: {BASE_URL}")
    print("=" * 80)

    reset_db_runtime_state()

    passed = 0
    total = 0

    def assert_test(name: str, condition: bool, detail: str = ""):
        nonlocal passed, total
        total += 1
        if condition:
            print(f"PASS [{total:02d}]: {name}")
            passed += 1
        else:
            print(f"FAIL [{total:02d}]: {name} - {detail[:200]}")

    # -------------------------------------------------------------------------
    # 1. Health & Backend Routing
    # -------------------------------------------------------------------------
    try:
        health = http_get("/api/health")
        assert_test(
            "System Health Check",
            health.get("status") in ("healthy", "degraded") and "postgres" in health and "neo4j" in health,
            f"Health: {health}"
        )
        print(f"       -> Database: {health.get('postgres')}, Graph: {health.get('neo4j')}, Cache: {health.get('redis')}, Vector: {health.get('vector_backend')}")
    except Exception as e:
        assert_test("System Health Check", False, str(e))

    # -------------------------------------------------------------------------
    # 2. Reference Metadata Endpoints
    # -------------------------------------------------------------------------
    try:
        users = http_get("/api/users")
        assert_test("GET /api/users", len(users) >= 18 and any(u["name"] == "Michael Turner" for u in users))
    except Exception as e:
        assert_test("GET /api/users", False, str(e))

    try:
        wells = http_get("/api/wells")
        assert_test("GET /api/wells", len(wells) >= 200 and any(w["asset_id"] == "WELL-0001" for w in wells))
    except Exception as e:
        assert_test("GET /api/wells", False, str(e))

    try:
        areas = http_get("/api/areas")
        assert_test("GET /api/areas", len(areas) >= 5)
    except Exception as e:
        assert_test("GET /api/areas", False, str(e))

    try:
        rules = http_get("/api/rules")
        wt = rules.get("well_types", {})
        sops = rules.get("sops", {})
        cond_rules = (
            "T200" in wt and wt["T200"].get("min_temp_delta_c") == 15.0 and
            "T350" in wt and wt["T350"].get("min_temp_delta_c") == 20.0 and
            "SR-02" in sops and sops["SR-02"].get("containment_limit_hours") == 4.0
        )
        assert_test("GET /api/rules (Dynamic SOP Parsing)", cond_rules, f"Rules: {rules}")
    except Exception as e:
        assert_test("GET /api/rules", False, str(e))

    try:
        neigh = http_get("/api/graph/neighborhood?asset_id=WELL-0001&depth=1")
        assert_test(
            "GET /api/graph/neighborhood",
            neigh.get("root_id") == "WELL-0001" and len(neigh.get("nodes", [])) > 0
        )
    except Exception as e:
        assert_test("GET /api/graph/neighborhood", False, str(e))

    # -------------------------------------------------------------------------
    # 3. Benchmark Queries Q1 - Q10 (/api/query)
    # -------------------------------------------------------------------------
    # Q1: Single Well Status Card
    try:
        q1 = http_post("/api/query", {
            "question": "Is WELL-0001 producing oil right now? When was it last inspected, and by whom? Show me its status card.",
            "user_id": "U-201"
        })
        text1 = q1.get("answer_text", "").lower()
        cond_q1 = (
            "not producing oil" in text1 and
            "3.2" in q1.get("answer_text", "") and
            "ryan brooks" in text1 and
            "ins-0001-0203" in text1 and
            q1.get("visual", {}).get("type") in ("well_detail", "status_card")
        )
        assert_test("Chat-Q1: Single Well Status Card", cond_q1, q1.get("answer_text", ""))
    except Exception as e:
        assert_test("Chat-Q1: Single Well Status Card", False, str(e))

    # Q2: Offline Wells in Area
    try:
        q2 = http_post("/api/query", {
            "question": "Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table.",
            "user_id": "U-201"
        })
        text2 = q2.get("answer_text", "")
        cond_q2 = "WELL-0164" in text2 and "WELL-0170" in text2 and "WELL-0172" in text2 and "WELL-0175" in text2
        assert_test("Chat-Q2: Table of Offline Wells", cond_q2, text2)
    except Exception as e:
        assert_test("Chat-Q2: Table of Offline Wells", False, str(e))

    # Q3: Line Chart
    try:
        q3 = http_post("/api/query", {
            "question": "Show a line chart of WELL-0001's wellhead temperature against air temperature for the last 13 weeks, and mark when it was not producing oil.",
            "user_id": "U-201"
        })
        text3 = q3.get("answer_text", "")
        cond_q3 = "2026-10-08" in text3 and "2026-10-15" in text3
        assert_test("Chat-Q3: Line Chart (13 Weeks Temperature)", cond_q3, text3)
    except Exception as e:
        assert_test("Chat-Q3: Line Chart (13 Weeks Temperature)", False, str(e))

    # Q4: Spills History
    try:
        q4 = http_post("/api/query", {
            "question": "How many oil spills has WELL-0001 had in the last 4 years, and how much oil in total? List them in a table.",
            "user_id": "U-201"
        })
        text4 = q4.get("answer_text", "")
        cond_q4 = "6 spills" in text4 and "15.1 barrels" in text4 and "INS-0001-0070" in text4
        assert_test("Chat-Q4: Spill History & Rainwater Exclusion", cond_q4, text4)
    except Exception as e:
        assert_test("Chat-Q4: Spill History & Rainwater Exclusion", False, str(e))

    # Q5: 2025 Downtime
    try:
        q5 = http_post("/api/query", {
            "question": "How many days was WELL-0001 down in 2025?",
            "user_id": "U-201"
        })
        text5 = q5.get("answer_text", "")
        cond_q5 = "21 days down in 2025" in text5 and "MNT-0001-021" in text5
        assert_test("Chat-Q5: 2025 Downtime Calculation", cond_q5, text5)
    except Exception as e:
        assert_test("Chat-Q5: 2025 Downtime Calculation", False, str(e))

    # Q6: Bar Chart of Top Downtime & Day 1 Session Recording
    try:
        q6 = http_post("/api/query", {
            "question": "Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months? Show a bar chart.",
            "user_id": "U-201",
            "conversation_id": "session-mt-day1"
        })
        text6 = q6.get("answer_text", "")
        cond_q6 = "WELL-0121" in text6 and "49 days" in text6 and "WELL-0138" in text6 and "WELL-0107" in text6
        assert_test("Chat-Q6: Bar Chart & Session Recording", cond_q6, text6)
    except Exception as e:
        assert_test("Chat-Q6: Bar Chart & Session Recording", False, str(e))

    # Q7: Map of 90-day Spills
    try:
        q7 = http_post("/api/query", {
            "question": "Show on a map every well in Northeast Block 8 with a real spill in the last 90 days.",
            "user_id": "U-201"
        })
        text7 = q7.get("answer_text", "")
        cond_q7 = "WELL-0151" in text7 and "WELL-0165" in text7 and "WELL-0175" in text7 and "WELL-0186" in text7
        assert_test("Chat-Q7: Map of 90-day Real Spills", cond_q7, text7)
    except Exception as e:
        assert_test("Chat-Q7: Map of 90-day Real Spills", False, str(e))

    # Q8: Heatmap by Area and Month
    try:
        q8 = http_post("/api/query", {
            "question": "Show a heatmap of 2026 spills by geographic area and month.",
            "user_id": "U-201"
        })
        text8 = q8.get("answer_text", "")
        cond_q8 = "Southwest Block 24" in text8 and "Total = 43" in text8
        assert_test("Chat-Q8: Heatmap of Spills by Area and Month", cond_q8, text8)
    except Exception as e:
        assert_test("Chat-Q8: Heatmap of Spills by Area and Month", False, str(e))

    # Q9: SOP & Regulatory Compliance
    try:
        q9 = http_post("/api/query", {
            "question": "Which rules has WELL-0001 broken in the last 12 months, and what is still open?",
            "user_id": "U-201"
        })
        text9 = q9.get("answer_text", "")
        cond_q9 = "SR-01" in text9 and "SR-02" in text9 and "SR-03" in text9 and "RC-04" in text9 and "5,000" in text9
        assert_test("Chat-Q9: SOP & Regulatory Compliance Audit", cond_q9, text9)
    except Exception as e:
        assert_test("Chat-Q9: SOP & Regulatory Compliance Audit", False, str(e))

    # Q10: Containment limit breaches
    try:
        q10 = http_post("/api/query", {
            "question": "In Southwest Block 24, which spills in the last 90 days were not contained within the SOP time limit?",
            "user_id": "U-201"
        })
        text10 = q10.get("answer_text", "")
        cond_q10 = "WELL-0082" in text10 and "7.1 hours" in text10 and "WELL-0100" in text10 and "8.1 hours" in text10
        assert_test("Chat-Q10: Containment Time Limit Breaches", cond_q10, text10)
    except Exception as e:
        assert_test("Chat-Q10: Containment Time Limit Breaches", False, str(e))

    # -------------------------------------------------------------------------
    # 4. GateMem Session Memory Recall (Q11)
    # -------------------------------------------------------------------------
    try:
        q11 = http_post("/api/query", {
            "question": "For the three wells we discussed yesterday, what have repairs cost this year?",
            "user_id": "U-201",
            "conversation_id": "session-mt-day2"
        })
        text11 = q11.get("answer_text", "")
        cond_q11 = "25,794" in text11 and "46,942" in text11 and "5,176" in text11
        assert_test("Chat-Q11: In-Chat Session Memory Recall", cond_q11, text11)
    except Exception as e:
        assert_test("Chat-Q11: In-Chat Session Memory Recall", False, str(e))

    # -------------------------------------------------------------------------
    # 5. In-Chat Corrections & Governance (Q12 - Q14)
    # -------------------------------------------------------------------------
    try:
        q12_fb = http_post("/api/query", {
            "question": "The 15 Oct reading for WELL-0164 is wrong. The handheld thermal gun used in that inspection was faulty; the field crew re-measured the wellhead at 41.0 °C.",
            "user_id": "U-201"
        })
        q12_re = http_post("/api/query", {
            "question": "Which wells in Northeast Block 8 are not producing oil right now, and why?",
            "user_id": "U-201"
        })
        cond_q12 = (
            "41.0 °C" in q12_fb.get("answer_text", "") and
            "producing oil" in q12_fb.get("answer_text", "") and
            "WELL-0164" not in [w[0] for w in q12_re.get("visual", {}).get("payload", {}).get("rows", [])]
        )
        assert_test("Chat-Q12: In-Chat Raw Temp Override & Cascade", cond_q12, q12_fb.get("answer_text", ""))
    except Exception as e:
        assert_test("Chat-Q12: In-Chat Raw Temp Override & Cascade", False, str(e))

    try:
        q13 = http_post("/api/query", {
            "question": "The AI estimated the 24 Sep spill at WELL-0151 as 4.5 bbl. The field crew measured 5.4 bbl.",
            "user_id": "U-201"
        })
        text13 = q13.get("answer_text", "")
        cond_q13 = "5.4 bbl" in text13 and "SR-01" in text13 and "SR-02" in text13 and "6.4 hours" in text13 and "23 Nov 2026" in text13
        assert_test("Chat-Q13: In-Chat Spill Override & SOP Cascade", cond_q13, text13)
    except Exception as e:
        assert_test("Chat-Q13: In-Chat Spill Override & SOP Cascade", False, str(e))

    try:
        q14_fb = http_post("/api/query", {
            "question": "Note for all T350 wells: our team now wants a pump jack root-cause analysis after 2 repairs, not 3.",
            "user_id": "U-201"
        })
        q14_re = http_post("/api/query", {
            "question": "Which wells in Northeast Block 7 need a root-cause analysis on their pump jack?",
            "user_id": "U-201"
        })
        text14 = q14_re.get("answer_text", "")
        cond_q14 = (
            "2 corrective repairs" in q14_fb.get("answer_text", "") and
            "WELL-0120" in text14 and
            "WELL-0108" in text14 and
            "WELL-0121" in text14 and
            "WELL-0138" in text14 and
            "WELL-0102" not in text14
        )
        assert_test("Chat-Q14: In-Chat Scoped Rule Override", cond_q14, text14)
    except Exception as e:
        assert_test("Chat-Q14: In-Chat Scoped Rule Override", False, str(e))

    # -------------------------------------------------------------------------
    # 6. Cross-User Visibility & Memory Isolation (Q15 - Q16)
    # -------------------------------------------------------------------------
    try:
        q15a = http_post("/api/query", {
            "question": "Is WELL-0164 producing oil right now?",
            "user_id": "U-203"  # Jessica Reed
        })
        q15b = http_post("/api/query", {
            "question": "Which spills in Northeast Block 8 in the last 90 days needed a report to the regulator?",
            "user_id": "U-401"  # Laura Simmons
        })
        cond_q15 = (
            "producing oil" in q15a.get("answer_text", "").lower() and
            "41.0" in q15a.get("answer_text", "") and
            "WELL-0151" in q15b.get("answer_text", "")
        )
        assert_test("Chat-Q15: Cross-User Shared Visibility", cond_q15, f"15a: {q15a.get('answer_text')}")
    except Exception as e:
        assert_test("Chat-Q15: Cross-User Shared Visibility", False, str(e))

    try:
        q16a = http_post("/api/query", {
            "question": "FYI for everyone: WELL-0007 will be shut in from 17 Oct for a 10-day planned workover.",
            "user_id": "U-102"
        })
        q16b = http_post("/api/query", {
            "question": "Is any downtime planned for WELL-0007?",
            "user_id": "U-201"
        })
        q16c = http_post("/api/query", {
            "question": "For the three wells we discussed yesterday, what have repairs cost this year?",
            "user_id": "U-203"  # Jessica Reed
        })
        text16b = q16b.get("answer_text", "")
        text16c = q16c.get("answer_text", "").lower()
        cond_q16 = (
            "10-day planned workover" in text16b and
            "no record of an earlier conversation" in text16c
        )
        assert_test("Chat-Q16: Shared Knowledge vs Zero Private Leakage", cond_q16, f"16c: {text16c}")
    except Exception as e:
        assert_test("Chat-Q16: Shared Knowledge vs Zero Private Leakage", False, str(e))

    # -------------------------------------------------------------------------
    # 7. Data Conflict Claims & Analysis (Q17 - Q18)
    # -------------------------------------------------------------------------
    try:
        q17a = http_post("/api/query", {
            "question": "WELL-0175 is running fine.",
            "user_id": "U-202"
        })
        q17b = http_post("/api/query", {
            "question": "WELL-0001 is back online since 14 Oct.",
            "user_id": "U-102"
        })
        text17a = q17a.get("answer_text", "")
        text17b = q17b.get("answer_text", "")
        cond_q17 = (
            "Disagreement with recorded sensor data" in text17a and
            "0.4" in text17a and
            "Disagreement with recorded sensor data" in text17b and
            "20 Oct" in text17b
        )
        assert_test("Chat-Q17: Data Conflict Claims", cond_q17, text17a)
    except Exception as e:
        assert_test("Chat-Q17: Data Conflict Claims", False, str(e))

    try:
        q18 = http_post("/api/query", {
            "question": "Was the 20 Aug spill at WELL-0101 real oil?",
            "user_id": "U-201"
        })
        text18 = q18.get("answer_text", "")
        cond_q18 = (
            "real crude oil" in text18 and
            "Ryan Brooks" in text18 and
            "Chris Dalton" in text18 and
            "MNT-0101-029" in text18
        )
        assert_test("Chat-Q18: AI Analysis Disagreement (Ryan Brooks vs Chris Dalton)", cond_q18, text18)
    except Exception as e:
        assert_test("Chat-Q18: AI Analysis Disagreement (Ryan Brooks vs Chris Dalton)", False, str(e))

    # -------------------------------------------------------------------------
    # 8. Unseen SOP Protocol RAG Verification
    # -------------------------------------------------------------------------
    try:
        q_rag = http_post("/api/query", {
            "question": "What is the company safety requirement for Protocol WS-03 regarding personal H2S monitors?",
            "user_id": "U-201"
        })
        text_rag = q_rag.get("answer_text", "")
        cond_rag = "WS-03" in text_rag and "10 ppm" in text_rag and q_rag.get("visual", {}).get("type") in ("table", "comparison_table")
        assert_test("Unseen RAG: Exact Protocol Retrieval (WS-03, 10 ppm H2S)", cond_rag, text_rag)
    except Exception as e:
        assert_test("Unseen RAG: Exact Protocol Retrieval (WS-03, 10 ppm H2S)", False, str(e))

    # -------------------------------------------------------------------------
    # 9. Dedicated Feedback API Endpoints (/api/feedback)
    # -------------------------------------------------------------------------
    try:
        fb_api = http_post("/api/feedback", {
            "user_id": "U-101",
            "target_type": "temperature",
            "target_id": "WELL-0001",
            "field": "wellhead_temp_c",
            "new_value": 38.5,
            "reason": "Calibration reading"
        })
        assert_test("Dedicated POST /api/feedback", fb_api.get("status") == "applied" and "data_version" in fb_api)
    except Exception as e:
        assert_test("Dedicated POST /api/feedback", False, str(e))

    # -------------------------------------------------------------------------
    # 10. Query Caching TTL & Cache Hit Check
    # -------------------------------------------------------------------------
    try:
        q_c1 = http_post("/api/query", {
            "question": "Is WELL-0002 producing oil right now?",
            "user_id": "U-201",
            "conversation_id": "cache-suite-session"
        })
        q_c2 = http_post("/api/query", {
            "question": "Is WELL-0002 producing oil right now?",
            "user_id": "U-201",
            "conversation_id": "cache-suite-session"
        })
        assert_test("Query Cache: 5-min TTL Hit", q_c2.get("cached") is True)
    except Exception as e:
        assert_test("Query Cache: 5-min TTL Hit", False, str(e))

    # -------------------------------------------------------------------------
    # 11. Audit & Corrections Endpoints
    # -------------------------------------------------------------------------
    try:
        corrections = http_get("/api/corrections")
        assert_test("GET /api/corrections", len(corrections) > 0)
    except Exception as e:
        assert_test("GET /api/corrections", False, str(e))

    try:
        audit = http_get("/api/audit")
        assert_test("GET /api/audit", len(audit) > 0)
    except Exception as e:
        assert_test("GET /api/audit", False, str(e))

    # -------------------------------------------------------------------------
    # 12. Ingest Job Execution & Tracking
    # -------------------------------------------------------------------------
    try:
        ingest_res = http_post("/api/ingest", {"dataset_path": "sample-data"})
        job_id = ingest_res.get("job_id")
        assert_test("POST /api/ingest", job_id is not None and ingest_res.get("status") in ("completed", "queued"))
        
        if job_id:
            job_status = http_get(f"/api/ingest/{job_id}")
            assert_test(
                "GET /api/ingest/{job_id}",
                job_status.get("job_id") == job_id and "counts" in job_status,
                f"Job: {job_status}"
            )
    except Exception as e:
        assert_test("POST /api/ingest", False, str(e))
        assert_test("GET /api/ingest/{job_id}", False, str(e))

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print(f"E2E SUITE RESULTS: {passed}/{total} TESTS PASSED ({round(passed/total*100, 1)}%)")
    print("=" * 80)

    if passed == total:
        print("[SUCCESS] ALL END-TO-END ACCEPTANCE GATES ARE VERIFIED AND GREEN!\n")
        return 0
    else:
        print(f"[WARNING] {total - passed} tests failed.\n")
        return 1

if __name__ == "__main__":
    sys.exit(run_suite())
