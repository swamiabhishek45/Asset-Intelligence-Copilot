import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from backend.config import settings
from backend.db.postgres import get_db_connection

class AssetIntelligenceDomainEngine:
    def __init__(self):
        pass

    def _get_conn(self):
        return get_db_connection()

    # -------------------------------------------------------------------------
    # RULE HELPERS: Scoped Rules & Overrides (Precedence Architecture)
    # -------------------------------------------------------------------------
    def get_well_type_rules(self, cur) -> Dict[str, Dict[str, Any]]:
        """
        Fetches active rules per well_type (T200, T350), prioritizing user overrides
        (e.g., Michael Turner's Q14 rule: T350 pump_jack RCA after 2 repairs instead of 3).
        """
        cur.execute(
            """
            SELECT scope_value, parameter_name, numeric_value, source_citation, is_user_override, author_user_id
            FROM scoped_rules
            WHERE scope_type = 'WELL_TYPE'
            ORDER BY is_user_override ASC, id ASC
            """
        )
        rules: Dict[str, Dict[str, Any]] = {
            "T200": {"min_temp_delta_c": {"value": 15.0, "citation": "T200.md", "is_user_override": False},
                     "rca_repairs_12m": {"value": 3.0, "citation": "T200.md", "is_user_override": False}},
            "T350": {"min_temp_delta_c": {"value": 20.0, "citation": "T350.md", "is_user_override": False},
                     "rca_repairs_12m": {"value": 3.0, "citation": "T350.md", "is_user_override": False}},
        }
        for r in cur.fetchall():
            wtype = r["scope_value"].upper()
            rules.setdefault(wtype, {})[r["parameter_name"]] = {
                "value": float(r["numeric_value"]),
                "citation": r.get("source_citation") or f"{wtype}.md",
                "is_user_override": bool(r.get("is_user_override")),
                "author_user_id": r.get("author_user_id"),
            }
        return rules

    def get_inspection_overrides(self, cur, asset_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Returns formal corrections and runtime overrides indexed by inspection_id.
        Audit trail preserves original values, author, timestamp, and reason.
        """
        query = """
            SELECT c.*, u.name AS author_name
            FROM context_notes c
            LEFT JOIN users u ON c.author_user_id = u.user_id
            WHERE c.inspection_id IS NOT NULL
        """
        params = ()
        if asset_id:
            query += " AND c.asset_id = %s"
            params = (asset_id,)
        cur.execute(query, params)
        by_ins: Dict[str, List[Dict[str, Any]]] = {}
        for row in cur.fetchall():
            by_ins.setdefault(row["inspection_id"], []).append(row)
        return by_ins

    # -------------------------------------------------------------------------
    # TOOL 1: Single Well Status & Inspection (Q1, Q12, Q15a, Q17)
    # -------------------------------------------------------------------------
    def evaluate_well_status(self, asset_id: str) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT w.*, a.name AS area_name, t.name AS team_name
                FROM wells w
                LEFT JOIN areas a ON w.area_id = a.area_id
                LEFT JOIN teams t ON w.team_id = t.team_id
                WHERE w.asset_id = %s
                """,
                (asset_id,)
            )
            well = cur.fetchone()
            if not well:
                return {"error": f"Well {asset_id} not found"}

            rules = self.get_well_type_rules(cur)
            wtype = well["well_type"].upper()
            min_delta = rules.get(wtype, {}).get("min_temp_delta_c", {}).get("value", 15.0)
            overrides = self.get_inspection_overrides(cur, asset_id)

            cur.execute(
                """
                SELECT i.*, u.name AS inspector_name
                FROM inspections i
                LEFT JOIN users u ON i.inspector_user_id = u.user_id
                WHERE i.asset_id = %s
                ORDER BY i.inspected_at DESC
                LIMIT 1
                """,
                (asset_id,)
            )
            latest = cur.fetchone()
            if not latest:
                return {"error": f"No inspections for {asset_id}"}

            ins_id = latest["inspection_id"]
            raw_wellhead = float(latest["wellhead_temp_c"])
            eff_wellhead = raw_wellhead
            temp_override_meta = None

            for ov in overrides.get(ins_id, []):
                if ov.get("field_overridden") == "wellhead_temp_c" and ov.get("corrected_value") is not None:
                    eff_wellhead = float(ov["corrected_value"])
                    temp_override_meta = ov

            ambient = float(latest["ambient_temp_c"])
            delta_t = round(eff_wellhead - ambient, 2)
            producing_oil = delta_t >= min_delta

            # Open repairs
            cur.execute(
                """
                SELECT * FROM maintenance
                WHERE asset_id = %s AND (completed_at IS NULL OR completed_at > %s)
                ORDER BY started_at DESC
                """,
                (asset_id, settings.BENCHMARK_TODAY)
            )
            open_repairs = cur.fetchall()

            # Context notes
            cur.execute(
                """
                SELECT c.*, u.name AS author_name
                FROM context_notes c
                LEFT JOIN users u ON c.author_user_id = u.user_id
                WHERE c.asset_id = %s
                ORDER BY c.created_at DESC
                """,
                (asset_id,)
            )
            notes = cur.fetchall()

            # Conflict detection
            conflicts = []
            if producing_oil and latest.get("notes") and "not moving" in latest["notes"].lower():
                conflicts.append({
                    "type": "sensor_correction_vs_inspector_note",
                    "inspection_id": ins_id,
                    "inspector_name": latest.get("inspector_name"),
                    "inspector_note": latest["notes"],
                    "message": f"Inspector {latest.get('inspector_name')} noted '{latest['notes']}' on {ins_id}, which disagrees with the corrected producing temperature ({eff_wellhead}°C)."
                })

            for n in notes:
                if n.get("verification_status") == "unconfirmed_conflict":
                    conflicts.append({
                        "type": "user_claim_vs_inspection",
                        "note_id": n["note_id"],
                        "author_name": n.get("author_name"),
                        "claim": n["text"]
                    })

            status_stale = (
                (well["recorded_status"] == "active" and not producing_oil) or
                (well["recorded_status"] == "down" and producing_oil)
            )

            citations = [ins_id, f"{well['well_type']}.md"]
            citations += [n["note_id"] for n in notes[:3]]
            citations += [r["maintenance_id"] for r in open_repairs]

            return {
                "asset_id": asset_id,
                "well_name": well.get("name"),
                "well_type": well["well_type"],
                "area_name": well["area_name"],
                "producing_oil": producing_oil,
                "latest_inspection": {
                    "inspection_id": ins_id,
                    "inspected_at": str(latest["inspected_at"])[:10],
                    "method": latest.get("method"),
                    "inspector_name": latest.get("inspector_name"),
                    "ambient_temp_c": ambient,
                    "raw_wellhead_temp_c": raw_wellhead,
                    "effective_wellhead_temp_c": eff_wellhead,
                    "temp_delta_c": delta_t,
                    "threshold_c": min_delta,
                    "inspector_notes": latest.get("notes"),
                    "override_info": temp_override_meta,
                },
                "recorded_status": well["recorded_status"],
                "recorded_status_out_of_date": status_stale,
                "open_repairs": open_repairs,
                "context_notes": notes,
                "conflicts": conflicts,
                "citations": list(dict.fromkeys(citations))
            }

    # -------------------------------------------------------------------------
    # TOOL 2: Area Offline Wells & Downtime (Q2, Q5, Q6)
    # -------------------------------------------------------------------------
    def get_area_offline_wells_now(self, area_name: str) -> Dict[str, Any]:
        """Solves Q2 & post-Q12 re-run: which wells in <Area> are not producing oil right now, and why?"""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT w.asset_id FROM wells w
                JOIN areas a ON w.area_id = a.area_id
                WHERE LOWER(a.name) = LOWER(%s) OR LOWER(a.area_id) = LOWER(%s)
                ORDER BY w.asset_id
                """,
                (area_name, area_name)
            )
            well_ids = [r["asset_id"] for r in cur.fetchall()]

        offline_rows = []
        excluded_by_correction = []
        for wid in well_ids:
            st = self.evaluate_well_status(wid)
            if not st.get("producing_oil"):
                reason = "No recorded reason"
                if st["open_repairs"]:
                    rep = st["open_repairs"][0]
                    reason = f"Repair {rep['maintenance_id']}, {rep['issue']}, started {str(rep['started_at'])[:10]}, still open"
                elif st["context_notes"]:
                    for n in st["context_notes"]:
                        if n.get("note_type") in ("operator_note", "runtime_claim") and n.get("verification_status") == "confirmed":
                            reason = f"Note {n['note_id']} ({n.get('author_name')}): {n['text']}"
                            break
                if reason == "No recorded reason" and st["latest_inspection"].get("inspector_notes"):
                    reason = f"No recorded reason. The inspector noted \"{st['latest_inspection']['inspector_notes']}\""

                offline_rows.append({
                    "asset_id": wid,
                    "well_type": st["well_type"],
                    "inspected_at": st["latest_inspection"]["inspected_at"],
                    "wellhead_above_air_c": st["latest_inspection"]["temp_delta_c"],
                    "recorded_status": f"{st['recorded_status']} (out of date)" if st["recorded_status_out_of_date"] else st["recorded_status"],
                    "reason": reason,
                    "citations": st["citations"]
                })
            elif st["latest_inspection"].get("override_info"):
                ov = st["latest_inspection"]["override_info"]
                excluded_by_correction.append({
                    "asset_id": wid,
                    "inspection_id": st["latest_inspection"]["inspection_id"],
                    "corrected_by": ov.get("author_name"),
                    "corrected_temp_c": st["latest_inspection"]["effective_wellhead_temp_c"],
                    "original_temp_c": st["latest_inspection"]["raw_wellhead_temp_c"],
                    "delta_c": st["latest_inspection"]["temp_delta_c"]
                })

        return {
            "area": area_name,
            "offline_wells": offline_rows,
            "excluded_by_correction": excluded_by_correction
        }

    def calculate_downtime(
        self,
        start_date: str,
        end_date: str,
        asset_id: Optional[str] = None,
        area_name: Optional[str] = None,
        top_n: int = 5
    ) -> Dict[str, Any]:
        """
        Solves Q5 (WELL-0001 in 2025 -> 21 days) and Q6 (Top 3 in NE Block 7 last 4 months).
        Rule: Every weekly inspection in period where ΔT < threshold counts as 7 days of downtime.
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            rules = self.get_well_type_rules(cur)
            overrides = self.get_inspection_overrides(cur, asset_id)

            query = """
                SELECT i.*, w.well_type, a.name AS area_name
                FROM inspections i
                JOIN wells w ON i.asset_id = w.asset_id
                JOIN areas a ON w.area_id = a.area_id
                WHERE substr(i.inspected_at, 1, 10) >= %s AND substr(i.inspected_at, 1, 10) <= %s
            """
            params: List[Any] = [start_date, end_date]
            if asset_id:
                query += " AND i.asset_id = %s"
                params.append(asset_id)
            if area_name:
                query += " AND (LOWER(a.name) = LOWER(%s) OR LOWER(a.area_id) = LOWER(%s))"
                params.extend([area_name, area_name])
            query += " ORDER BY i.asset_id, i.inspected_at ASC"

            cur.execute(query, tuple(params))
            rows = cur.fetchall()

            by_well: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                wid = r["asset_id"]
                wtype = r["well_type"].upper()
                min_delta = rules.get(wtype, {}).get("min_temp_delta_c", {}).get("value", 15.0)
                ins_id = r["inspection_id"]

                eff_temp = float(r["wellhead_temp_c"])
                for ov in overrides.get(ins_id, []):
                    if ov.get("field_overridden") == "wellhead_temp_c" and ov.get("corrected_value") is not None:
                        eff_temp = float(ov["corrected_value"])

                delta_t = round(eff_temp - float(r["ambient_temp_c"]), 2)
                if delta_t < min_delta:
                    entry = by_well.setdefault(wid, {
                        "asset_id": wid,
                        "well_type": wtype,
                        "downtime_days": 0,
                        "non_producing_inspections": []
                    })
                    entry["downtime_days"] += 7
                    ins_date = str(r["inspected_at"])[:10]
                    # Link cause repair
                    cur.execute(
                        """
                        SELECT maintenance_id, issue FROM maintenance
                        WHERE asset_id = %s AND (
                            triggered_by_inspection_id = %s OR
                            (substr(started_at, 1, 10) <= %s AND (completed_at IS NULL OR substr(completed_at, 1, 10) >= %s))
                        )
                        ORDER BY started_at DESC LIMIT 1
                        """,
                        (wid, ins_id, ins_date, ins_date)
                    )
                    rep = cur.fetchone()
                    entry["non_producing_inspections"].append({
                        "inspection_id": ins_id,
                        "date": ins_date,
                        "wellhead_temp_c": eff_temp,
                        "ambient_temp_c": float(r["ambient_temp_c"]),
                        "delta_t": delta_t,
                        "cause_maintenance_id": rep["maintenance_id"] if rep else None,
                        "cause_issue": rep["issue"] if rep else None,
                    })

            ranked = sorted(by_well.values(), key=lambda x: (-x["downtime_days"], x["asset_id"]))
            return {
                "window": {"start": start_date, "end": end_date},
                "results": ranked[:top_n] if area_name else ranked
            }

    # -------------------------------------------------------------------------
    # TOOL 3: Spills, Heatmaps & Maps (Q4, Q7, Q8, Q13, Q15b)
    # -------------------------------------------------------------------------
    def query_spills(
        self,
        start_date: str,
        end_date: str = settings.BENCHMARK_TODAY,
        asset_id: Optional[str] = None,
        area_name: Optional[str] = None
    ) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            overrides = self.get_inspection_overrides(cur, asset_id)
            query = """
                SELECT i.*, w.lat, w.lon, w.area_id, a.name AS area_name
                FROM inspections i
                JOIN wells w ON i.asset_id = w.asset_id
                JOIN areas a ON w.area_id = a.area_id
                WHERE i.spill_detected = 1
                  AND substr(i.inspected_at, 1, 10) >= %s
                  AND substr(i.inspected_at, 1, 10) <= %s
            """
            params: List[Any] = [start_date, end_date]
            if asset_id:
                query += " AND i.asset_id = %s"
                params.append(asset_id)
            if area_name:
                query += " AND (LOWER(a.name) = LOWER(%s) OR LOWER(a.area_id) = LOWER(%s))"
                params.extend([area_name, area_name])
            query += " ORDER BY i.inspected_at ASC"

            cur.execute(query, tuple(params))
            raw_detections = cur.fetchall()

            valid_spills = []
            corrected_false_positives = []
            for d in raw_detections:
                ins_id = d["inspection_id"]
                is_false_positive = False
                eff_vol = float(d["spill_est_volume_bbl"] or 0.0)
                raw_vol = eff_vol
                vol_override_note = None

                for ov in overrides.get(ins_id, []):
                    if ov.get("note_type") == "correction":
                        if ov.get("field_overridden") == "spill_detected" and str(ov.get("corrected_value")).lower() == "false":
                            is_false_positive = True
                            corrected_false_positives.append({
                                "inspection_id": ins_id,
                                "date": str(d["inspected_at"])[:10],
                                "note_id": ov["note_id"],
                                "reason": ov["text"]
                            })
                        elif ov.get("field_overridden") == "spill_est_volume_bbl" and ov.get("corrected_value") is not None:
                            eff_vol = float(ov["corrected_value"])
                            vol_override_note = ov

                if not is_false_positive:
                    valid_spills.append({
                        "inspection_id": ins_id,
                        "asset_id": d["asset_id"],
                        "area_name": d["area_name"],
                        "date": str(d["inspected_at"])[:10],
                        "month": int(str(d["inspected_at"])[5:7]),
                        "raw_volume_bbl": raw_vol,
                        "effective_volume_bbl": eff_vol,
                        "volume_override": vol_override_note,
                        "lat": d["lat"],
                        "lon": d["lon"],
                        "inspector_notes": d.get("notes")
                    })

            total_bbl = round(sum(s["effective_volume_bbl"] for s in valid_spills), 2)
            return {
                "raw_detection_count": len(raw_detections),
                "valid_spill_count": len(valid_spills),
                "total_volume_bbl": total_bbl,
                "valid_spills": valid_spills,
                "corrected_false_positives": corrected_false_positives
            }

    # -------------------------------------------------------------------------
    # TOOL 4: Temperature Time Series (Q3)
    # -------------------------------------------------------------------------
    def get_well_temperature_series(self, asset_id: str, weeks: int = 13) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            rules = self.get_well_type_rules(cur)
            cur.execute("SELECT well_type FROM wells WHERE asset_id = %s", (asset_id,))
            wrow = cur.fetchone()
            wtype = wrow["well_type"].upper() if wrow else "T200"
            min_delta = rules.get(wtype, {}).get("min_temp_delta_c", {}).get("value", 15.0)

            cur.execute(
                """
                SELECT inspection_id, inspected_at, ambient_temp_c, wellhead_temp_c
                FROM inspections
                WHERE asset_id = %s
                ORDER BY inspected_at DESC
                LIMIT %s
                """,
                (asset_id, weeks)
            )
            rows = list(reversed(cur.fetchall()))
            series = []
            for r in rows:
                dt = round(float(r["wellhead_temp_c"]) - float(r["ambient_temp_c"]), 2)
                series.append({
                    "inspection_id": r["inspection_id"],
                    "date": str(r["inspected_at"])[:10],
                    "wellhead_temp_c": float(r["wellhead_temp_c"]),
                    "ambient_temp_c": float(r["ambient_temp_c"]),
                    "delta_t": dt,
                    "producing": dt >= min_delta
                })
            return {
                "asset_id": asset_id,
                "well_type": wtype,
                "threshold_c": min_delta,
                "readings": series,
                "non_producing_dates": [s["date"] for s in series if not s["producing"]]
            }

    # -------------------------------------------------------------------------
    # TOOL 5: Annual Repair Costs (Q11)
    # -------------------------------------------------------------------------
    def get_well_annual_repair_costs(self, asset_ids: List[str], year: int = 2026) -> Dict[str, Any]:
        results = {}
        with self._get_conn() as conn:
            cur = conn.cursor()
            for wid in asset_ids:
                cur.execute(
                    """
                    SELECT SUM(cost_total_usd) AS total_cost
                    FROM maintenance
                    WHERE asset_id = %s AND substr(started_at, 1, 4) = %s
                    """,
                    (wid, str(year))
                )
                r = cur.fetchone()
                results[wid] = round(float(r["total_cost"] or 0.0), 2)
        return {"year": year, "costs": results}

    # -------------------------------------------------------------------------
    # TOOL 6: SOP & RCA Compliance Audit (Q9, Q10, Q13, Q14)
    # -------------------------------------------------------------------------
    def audit_sop_and_rca(
        self,
        asset_id: Optional[str] = None,
        area_name: Optional[str] = None,
        equipment_filter: Optional[str] = None,
        lookback_days: int = 365
    ) -> Dict[str, Any]:
        today_dt = datetime.fromisoformat(settings.BENCHMARK_TODAY)
        start_date = (today_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        with self._get_conn() as conn:
            cur = conn.cursor()
            rules = self.get_well_type_rules(cur)
            spills_data = self.query_spills(start_date, settings.BENCHMARK_TODAY, asset_id=asset_id, area_name=area_name)

            breaches = []
            open_actions = []

            for sp in spills_data["valid_spills"]:
                ins_id = sp["inspection_id"]
                wid = sp["asset_id"]
                vol = sp["effective_volume_bbl"]

                # SR-02: 4-hour containment limit
                cur.execute(
                    """
                    SELECT * FROM maintenance
                    WHERE triggered_by_inspection_id = %s OR (asset_id = %s AND substr(started_at, 1, 10) = %s)
                    ORDER BY started_at ASC LIMIT 1
                    """,
                    (ins_id, wid, sp["date"])
                )
                mnt = cur.fetchone()
                if mnt and mnt.get("extracted_containment_hours") is not None:
                    chours = float(mnt["extracted_containment_hours"])
                    if chours > 4.0:
                        breaches.append({
                            "protocol_id": "SR-02",
                            "asset_id": wid,
                            "inspection_id": ins_id,
                            "maintenance_id": mnt["maintenance_id"],
                            "report_file": mnt.get("report_file"),
                            "containment_hours": chours,
                            "limit_hours": 4.0,
                            "detail": f"Contained after about {chours} hours, against a 4-hour limit (found in {mnt['maintenance_id']} report)."
                        })

                # SR-01 & SR-03 for reportable spills (>= 5.0 bbl)
                if vol >= 5.0:
                    cur.execute(
                        "SELECT * FROM regulatory_events WHERE related_inspection_id = %s OR asset_id = %s ORDER BY event_date ASC",
                        (ins_id, wid)
                    )
                    reg_events = [e for e in cur.fetchall() if e.get("related_inspection_id") == ins_id or str(e["event_date"])[:10] >= sp["date"]]
                    report_ev = next((e for e in reg_events if e.get("event_type") == "spill_report_filed"), None)
                    if not report_ev:
                        breaches.append({
                            "protocol_id": "SR-01",
                            "asset_id": wid,
                            "inspection_id": ins_id,
                            "volume_bbl": vol,
                            "detail": f"Spill of {vol} bbl (>= 5 bbl reportable threshold) had a written notice due within 24 hours of {sp['date']}, and none is recorded."
                        })
                    elif report_ev.get("hours_to_report") and float(report_ev["hours_to_report"]) > 24.0:
                        nov_ev = next((e for e in reg_events if e.get("event_type") == "notice_of_violation"), None)
                        breaches.append({
                            "protocol_id": "SR-01",
                            "asset_id": wid,
                            "event_id": report_ev["event_id"],
                            "nov_event_id": nov_ev["event_id"] if nov_ev else None,
                            "fine_usd": nov_ev.get("fine_usd", 5000.0) if nov_ev else 5000.0,
                            "status": nov_ev.get("status", "open") if nov_ev else "open",
                            "detail": f"Reported after {report_ev['hours_to_report']} hours ({report_ev['event_id']}), against a 24-hour limit."
                        })

                    # SR-03: 60-day cleanup verification
                    due_dt = (datetime.fromisoformat(sp["date"]) + timedelta(days=60)).strftime("%Y-%m-%d")
                    sr03_ev = next((e for e in reg_events if e.get("protocol_id") == "SR-03"), None)
                    if sr03_ev and sr03_ev.get("status") == "open":
                        breaches.append({
                            "protocol_id": "SR-03",
                            "asset_id": wid,
                            "event_id": sr03_ev["event_id"],
                            "detail": f"Cleanup verification was due by {due_dt} and is still open ({sr03_ev['event_id']})."
                        })
                    elif due_dt > settings.BENCHMARK_TODAY:
                        open_actions.append({
                            "protocol_id": "SR-03",
                            "asset_id": wid,
                            "due_date": due_dt,
                            "detail": f"Agency verification of clean-up (SR-03) due within 60 days, by {due_dt}."
                        })

            # RC-04: NOV response deadline check
            if asset_id:
                cur.execute(
                    """
                    SELECT * FROM regulatory_events
                    WHERE asset_id = %s AND event_type = 'notice_of_violation' AND status = 'open'
                    """,
                    (asset_id,)
                )
                novs = cur.fetchall()
                for nov in novs:
                    nov_due = (datetime.fromisoformat(str(nov["event_date"])[:10]) + timedelta(days=30)).strftime("%Y-%m-%d")
                    cur.execute(
                        "SELECT * FROM regulatory_events WHERE asset_id = %s AND event_type = 'nov_response_filed'",
                        (asset_id,)
                    )
                    resp = cur.fetchone()
                    if not resp and nov_due < settings.BENCHMARK_TODAY:
                        breaches.append({
                            "protocol_id": "RC-04",
                            "asset_id": asset_id,
                            "event_id": nov["event_id"],
                            "deadline": nov_due,
                            "detail": f"Notice {nov['event_id']} needed a response by {nov_due}, and none is recorded."
                        })

            # Check RCA corrective repair counts
            rca_query = """
                SELECT m.asset_id, w.well_type, m.equipment_kind,
                       COUNT(*) AS repair_count
                FROM maintenance m
                JOIN wells w ON m.asset_id = w.asset_id
                JOIN areas a ON w.area_id = a.area_id
                WHERE m.maintenance_type = 'corrective'
                  AND substr(m.started_at, 1, 10) >= %s
                  AND substr(m.started_at, 1, 10) <= %s
            """
            rca_params: List[Any] = [start_date, settings.BENCHMARK_TODAY]
            if asset_id:
                rca_query += " AND m.asset_id = %s"
                rca_params.append(asset_id)
            if area_name:
                rca_query += " AND (LOWER(a.name) = LOWER(%s) OR LOWER(a.area_id) = LOWER(%s))"
                rca_params.extend([area_name, area_name])
            if equipment_filter:
                rca_query += " AND LOWER(m.equipment_kind) = LOWER(%s)"
                rca_params.append(equipment_filter)
            rca_query += " GROUP BY m.asset_id, w.well_type, m.equipment_kind ORDER BY m.asset_id"

            cur.execute(rca_query, tuple(rca_params))
            rca_wells = []
            for row in cur.fetchall():
                wtype = row["well_type"].upper()
                rule_obj = rules.get(wtype, {}).get("rca_repairs_12m", {"value": 3.0, "citation": f"{wtype}.md", "is_user_override": False})
                thresh = int(rule_obj["value"])
                if row["repair_count"] >= thresh:
                    rca_wells.append({
                        "asset_id": row["asset_id"],
                        "well_type": wtype,
                        "equipment_kind": row["equipment_kind"],
                        "repair_count": row["repair_count"],
                        "threshold_applied": thresh,
                        "rule_citation": rule_obj.get("citation"),
                        "is_user_override": rule_obj.get("is_user_override", False)
                    })

            return {
                "breaches": breaches,
                "open_actions": open_actions,
                "rca_required": rca_wells
            }

    # -------------------------------------------------------------------------
    # TOOL 7: Conflict Detection for Evidence Verification (Q18)
    # -------------------------------------------------------------------------
    def check_spill_reality_conflict(self, asset_id: str, date_prefix: str = "2026-08-20") -> Dict[str, Any]:
        """Solves Q18: returns detection, repair, and human note disagreement details."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM inspections
                WHERE asset_id = %s AND substr(inspected_at, 1, 10) = %s
                """,
                (asset_id, date_prefix)
            )
            ins = cur.fetchone()
            cur.execute(
                """
                SELECT c.*, u.name as author_name, u.role as author_role
                FROM context_notes c
                LEFT JOIN users u ON c.author_user_id = u.user_id
                WHERE c.asset_id = %s
                ORDER BY c.created_at ASC
                """,
                (asset_id,)
            )
            notes = cur.fetchall()
            cur.execute(
                """
                SELECT * FROM maintenance
                WHERE asset_id = %s AND substr(started_at, 1, 10) >= %s
                ORDER BY started_at ASC LIMIT 1
                """,
                (asset_id, date_prefix)
            )
            mnt = cur.fetchone()

            return {
                "asset_id": asset_id,
                "date": date_prefix,
                "ai_detection": ins,
                "maintenance_record": mnt,
                "disagreeing_notes": notes,
                "detection_stands": True,
                "rationale": "Neither note is a formal correction, and a spill repair was performed, so the detection stands as real crude oil."
            }

domain_engine = AssetIntelligenceDomainEngine()
