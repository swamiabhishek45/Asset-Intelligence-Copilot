import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from backend.config import settings
from backend.db.postgres import get_db_connection
from backend.services.domain_tools import AssetIntelligenceDomainEngine, domain_engine

class GateMemPolicyService:
    """
    Implements GateMem (arXiv:2606.18829) two-level memory governance:
    1. Private user memory strictly scoped to authenticated user_id (Q11 vs Q16).
    2. Shared well knowledge & corrections with provenance and conflict checks (Q12-Q18).
    """
    def __init__(self, engine: AssetIntelligenceDomainEngine = domain_engine):
        self.engine = engine

    def get_private_session_wells(self, user_id: str) -> Dict[str, Any]:
        """
        Solves Q11 (Michael Turner recalls [WELL-0121, WELL-0138, WELL-0107])
        and Q16 (Jessica Reed gets GateMem action='no_memory' - zero cross-user leakage).
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT session_id, user_query, discussed_asset_ids, created_at
                FROM private_user_sessions
                WHERE user_id = %s
                ORDER BY id DESC LIMIT 1
                """,
                (user_id,)
            )
            row = cur.fetchone()
            if not row or not row.get("discussed_asset_ids"):
                return {
                    "gatemem_action": "no_memory",
                    "message": f"No earlier conversation discussing specific wells was found for user {user_id}.",
                    "wells": []
                }
            
            w_ids = json.loads(row["discussed_asset_ids"]) if isinstance(row["discussed_asset_ids"], str) else row["discussed_asset_ids"]
            return {
                "gatemem_action": "answer",
                "wells": w_ids,
                "prior_query": row["user_query"]
            }

    def record_private_turn(self, user_id: str, session_id: str, query: str, answer: str, asset_ids: List[str]):
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO private_user_sessions (user_id, session_id, user_query, assistant_answer, discussed_asset_ids)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, session_id, query, answer, json.dumps(asset_ids))
            )
            conn.commit()

    def apply_user_feedback(
        self,
        user_id: str,
        feedback_type: str,
        asset_id: Optional[str] = None,
        well_type: Optional[str] = None,
        inspection_date: Optional[str] = None,
        new_value: Optional[float] = None,
        claim_is_producing: Optional[bool] = None,
        text_reason: str = ""
    ) -> Dict[str, Any]:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name, role FROM users WHERE user_id = %s", (user_id,))
            user = cur.fetchone() or {"name": user_id, "role": "operator"}
            note_id = f"CTX-RT-{uuid.uuid4().hex[:6].upper()}"

            # CASE 1: Q12 - Raw Wellhead Temperature Correction
            if feedback_type == "raw_temp_override" and asset_id and new_value is not None:
                cur.execute(
                    """
                    SELECT * FROM inspections
                    WHERE asset_id = %s AND (%s IS NULL OR substr(inspected_at, 1, 10) = %s)
                    ORDER BY inspected_at DESC LIMIT 1
                    """,
                    (asset_id, inspection_date, inspection_date)
                )
                ins = cur.fetchone()
                orig_val = str(ins["wellhead_temp_c"])
                cur.execute(
                    """
                    INSERT INTO context_notes (
                        note_id, asset_id, created_at, author_user_id, note_type,
                        inspection_id, text, field_overridden, original_value, corrected_value, verification_status
                    ) VALUES (%s, %s, CURRENT_TIMESTAMP, %s, 'correction', %s, %s, 'wellhead_temp_c', %s, %s, 'confirmed')
                    """,
                    (note_id, asset_id, user_id, ins["inspection_id"], text_reason, orig_val, str(new_value))
                )
                conn.commit()
                updated_status = self.engine.evaluate_well_status(asset_id)
                return {
                    "recorded_note_id": note_id,
                    "inspection_id": ins["inspection_id"],
                    "original_value_c": float(orig_val),
                    "corrected_value_c": new_value,
                    "author": user["name"],
                    "updated_well_status": updated_status,
                    "confirmation_needed": len(updated_status["conflicts"]) > 0
                }

            # CASE 2: Q13 - AI Spill Volume Correction -> Cascading SOP Re-Audit
            if feedback_type == "spill_volume_override" and asset_id and new_value is not None:
                cur.execute(
                    """
                    SELECT * FROM inspections
                    WHERE asset_id = %s AND spill_detected = 1 AND (%s IS NULL OR substr(inspected_at, 1, 10) = %s)
                    ORDER BY inspected_at DESC LIMIT 1
                    """,
                    (asset_id, inspection_date, inspection_date)
                )
                ins = cur.fetchone()
                orig_val = str(ins["spill_est_volume_bbl"])
                cur.execute(
                    """
                    INSERT INTO context_notes (
                        note_id, asset_id, created_at, author_user_id, note_type,
                        inspection_id, text, field_overridden, original_value, corrected_value, verification_status
                    ) VALUES (%s, %s, CURRENT_TIMESTAMP, %s, 'correction', %s, %s, 'spill_est_volume_bbl', %s, %s, 'confirmed')
                    """,
                    (note_id, asset_id, user_id, ins["inspection_id"], text_reason, orig_val, str(new_value))
                )
                conn.commit()
                cascaded_audit = self.engine.audit_sop_and_rca(asset_id=asset_id, lookback_days=90)
                return {
                    "recorded_note_id": note_id,
                    "inspection_id": ins["inspection_id"],
                    "original_ai_volume_bbl": float(orig_val),
                    "corrected_volume_bbl": new_value,
                    "author": user["name"],
                    "cascaded_sop_audit": cascaded_audit
                }

            # CASE 3: Q14 - Scoped Rule Override for a Whole Well Type
            if feedback_type == "well_type_rule" and well_type and new_value is not None:
                cur.execute(
                    """
                    INSERT INTO scoped_rules (
                        scope_type, scope_value, parameter_name, numeric_value,
                        source_citation, is_user_override, author_user_id
                    ) VALUES ('WELL_TYPE', %s, 'rca_repairs_12m', %s, %s, 1, %s)
                    """,
                    (well_type.upper(), new_value, f"Rule by {user['name']} ({user_id})", user_id)
                )
                conn.commit()
                return {
                    "scope": f"All {well_type.upper()} wells",
                    "parameter": "rca_repairs_12m",
                    "new_threshold": int(new_value),
                    "author": user["name"]
                }

            # CASE 4: Q16 & Q17 - Shared Operational Note or Status Claim
            if feedback_type == "well_status_claim" and asset_id:
                current_st = self.engine.evaluate_well_status(asset_id)
                v_status = "confirmed"
                conflict_msg = None
                if claim_is_producing is not None and claim_is_producing != current_st["producing_oil"]:
                    v_status = "unconfirmed_conflict"
                    conflict_msg = (
                        f"Latest inspection {current_st['latest_inspection']['inspection_id']} on "
                        f"{current_st['latest_inspection']['inspected_at']} shows wellhead only "
                        f"{current_st['latest_inspection']['temp_delta_c']}°C above air "
                        f"(producing={current_st['producing_oil']}), which contradicts {user['name']}'s claim."
                    )
                cur.execute(
                    """
                    INSERT INTO context_notes (
                        note_id, asset_id, created_at, author_user_id, note_type,
                        text, verification_status
                    ) VALUES (%s, %s, CURRENT_TIMESTAMP, %s, 'runtime_claim', %s, %s)
                    """,
                    (note_id, asset_id, user_id, text_reason, v_status)
                )
                conn.commit()
                return {
                    "recorded_note_id": note_id,
                    "asset_id": asset_id,
                    "author": user["name"],
                    "verification_status": v_status,
                    "conflict_detected": conflict_msg,
                    "latest_inspection": current_st["latest_inspection"],
                    "existing_notes": current_st["context_notes"]
                }

    def retract_or_forget_note(self, user_id: str, asset_id: str, target_keyword: str = "") -> Dict[str, Any]:
        """
        Implements GateMem (arXiv:2606.18829) Active Forgetting (F):
        Tombstones runtime notes/claims on explicit deletion request so subsequent probes
        return action='no_memory' without leaking or confirming the deleted content.
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT note_id, text FROM context_notes
                WHERE asset_id = %s
                  AND note_type IN ('runtime_claim', 'operator_note', 'correction')
                  AND COALESCE(verification_status, 'confirmed') != 'deleted_forgotten'
                ORDER BY created_at DESC
                """,
                (asset_id,)
            )
            rows = cur.fetchall()
            deleted_ids = []
            for r in rows:
                if not target_keyword or target_keyword.lower() in (r.get("text") or "").lower():
                    cur.execute(
                        """
                        UPDATE context_notes
                        SET verification_status = 'deleted_forgotten',
                            text = '[REDACTED_BY_GATEMEM_ACTIVE_FORGETTING]'
                        WHERE note_id = %s
                        """,
                        (r["note_id"],)
                    )
                    deleted_ids.append(r["note_id"])
            conn.commit()
            return {
                "gatemem_action": "no_memory",
                "asset_id": asset_id,
                "deleted_note_ids": deleted_ids,
                "status": "forgotten" if deleted_ids else "nothing_matched"
            }

gatemem_service = GateMemPolicyService(domain_engine)

