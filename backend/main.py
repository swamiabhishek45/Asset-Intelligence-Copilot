import time
import uuid
import logging
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Query as FastQuery, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import settings, get_as_of_date
from backend.ingest.celery_worker import ingest_dataset_task
from backend.services.domain_tools import domain_engine
from backend.services.gatemem_policy import gatemem_service
from backend.services.copilot_agent import copilot_agent
from backend.services.cache_service import cache_service
from backend.services.rules_engine import rules_engine
from backend.services.vector_store import vector_store
from backend.db.postgres import get_db_connection, check_postgres_availability
from backend.db.neo4j_graph import graph_service

logger = logging.getLogger(__name__)

APP_START_TIME = time.time()

app = FastAPI(
    title="FlytBase Asset Intelligence Copilot Backend",
    version="2.0.0",
    description="Deterministic SQL rules engine, Neo4j spatio-temporal graph, GateMem memory governance, and Next.js UI integration."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Request & Response Models
# -----------------------------------------------------------------------------
class IngestRequest(BaseModel):
    dataset_path: str = settings.SAMPLE_DATA_PATH
    async_mode: bool = False

class FeedbackRequest(BaseModel):
    user_id: str
    target_type: Optional[str] = None  # 'temperature'|'spill'|'status'|'general'
    target_id: Optional[str] = None
    scope: Optional[str] = None  # 'WELL'|'GLOBAL'|'SESSION'
    field: Optional[str] = None
    original_value: Optional[Any] = None
    new_value: Optional[Any] = None
    reason: Optional[str] = None

    # Legacy fields support
    feedback_type: Optional[str] = None
    asset_id: Optional[str] = None
    well_type: Optional[str] = None
    inspection_date: Optional[str] = None
    claim_is_producing: Optional[bool] = None
    text_reason: Optional[str] = None

class QueryRequest(BaseModel):
    user_id: Optional[str] = "U-201"
    conversation_id: Optional[str] = None
    question: Optional[str] = None
    # Legacy fields
    query: Optional[str] = None
    session_id: Optional[str] = None

# -----------------------------------------------------------------------------
# Core API Endpoints
# -----------------------------------------------------------------------------
@app.get("/api/health")
def health_check():
    """Reports system health, database, graph, cache, and vector store backend statuses."""
    pg_conn = check_postgres_availability(settings.POSTGRES_DSN)
    neo_status = graph_service.get_status()
    cache_backend = cache_service.get_backend_name()

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM wells")
        w_cnt = cur.fetchone()["cnt"]
        is_sqlite = getattr(conn, "is_sqlite", False)

    postgres_status = "connected" if (pg_conn and not is_sqlite) else "fallback_sqlite"
    neo4j_status = "connected" if neo_status.get("status") == "connected" else "fallback_memory"
    redis_status = "connected" if cache_backend == "redis" else "fallback_memory"
    vector_status = "pgvector" if postgres_status == "connected" else "sqlite_fallback"
    
    overall_status = "healthy" if (postgres_status == "connected" and neo4j_status == "connected") else "degraded"

    return {
        "status": overall_status,
        "postgres": postgres_status,
        "neo4j": neo4j_status,
        "redis": redis_status,
        "vector_backend": vector_status,
        "data_version": settings.DATA_VERSION,
        "uptime_seconds": round(time.time() - APP_START_TIME, 2),
        "wells_loaded": w_cnt,
        "as_of_date": get_as_of_date(),
        "benchmark_today": settings.BENCHMARK_TODAY
    }

@app.post("/api/query")
def process_chat_query(req: QueryRequest):
    """
    Answers operator plain-English queries with deterministic calculations,
    visualizations, citations, conflicts, and GateMem memory actions.
    Uses Redis / In-Memory query cache with 5-minute TTL.
    """
    t_start = time.time()
    effective_question = (req.question or req.query or "").strip()
    effective_user = (req.user_id or "U-201").strip()
    effective_conv = req.conversation_id or req.session_id or "session-1"

    if not effective_question:
        raise HTTPException(status_code=400, detail="Question or query field must not be empty.")

    # 1. Check Query Cache
    cached = cache_service.get_cached_query(effective_question, effective_user, settings.DATA_VERSION)
    if cached:
        cached["cached"] = True
        cached["latency_ms"] = round((time.time() - t_start) * 1000.0, 2)
        return cached

    # 2. Run query through Copilot Agent
    raw_res = copilot_agent.answer_query(
        query=effective_question,
        user_id=effective_user,
        session_id=effective_conv
    )

    # 3. Format citations as structured list
    raw_citations = raw_res.get("citations", [])
    structured_citations = []
    for c in raw_citations:
        if isinstance(c, dict):
            structured_citations.append(c)
        else:
            c_str = str(c)
            doc_name = c_str.split()[0] if c_str else "Manual"
            structured_citations.append({
                "doc": doc_name,
                "section": c_str,
                "snippet": c_str
            })

    # 4. Map Visual Types
    raw_visual_type = raw_res.get("visual_type", "none")
    visual_map = {
        "well_detail": "well_detail",
        "status_card": "well_detail",
        "comparison_table": "comparison_table",
        "incident_card": "incident_card",
        "timeseries": "timeseries",
        "table": "comparison_table",
        "text": "none",
        "none": "none"
    }
    canonical_visual_type = visual_map.get(raw_visual_type, "none")
    visual_payload = raw_res.get("visual_payload", {})

    # 5. Extract conflicts & memory actions from telemetry
    telemetry = raw_res.get("pipeline_telemetry", {})
    gatemem_action = telemetry.get("gatemem_action", "remember")
    memory_actions = [{
        "action": gatemem_action,
        "key": f"{effective_user}:{effective_conv}",
        "detail": f"GateMem action '{gatemem_action}' for user {effective_user}"
    }]

    conflicts = []
    if "conflicts" in telemetry and isinstance(telemetry["conflicts"], list):
        conflicts = telemetry["conflicts"]

    tools_used = telemetry.get("tools_executed", [telemetry.get("intent_route", "deterministic_sql")])

    latency_ms = round((time.time() - t_start) * 1000.0, 2)
    answer_text = raw_res.get("text", "")

    response_payload = {
        "answer_text": answer_text,
        "visual": {
            "type": canonical_visual_type,
            "payload": visual_payload
        },
        "citations": structured_citations,
        "conflicts": conflicts,
        "memory_actions": memory_actions,
        "tools_used": tools_used,
        "data_version": settings.DATA_VERSION,
        "latency_ms": latency_ms,
        # Backward compatibility aliases
        "text": answer_text,
        "visual_type": canonical_visual_type,
        "visual_payload": visual_payload,
        "pipeline_telemetry": telemetry,
        "cached": False
    }

    # 6. Save in Cache
    cache_service.set_cached_query(effective_question, effective_user, settings.DATA_VERSION, response_payload, ttl_seconds=300)

    return response_payload

@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest):
    """
    Applies runtime human feedback, records provenance in context_notes / scoped_rules,
    invalidates query cache, bumps data_version, and returns updated entity view.
    """
    effective_user = req.user_id
    effective_fb_type = req.feedback_type
    effective_asset = req.target_id or req.asset_id
    effective_val = req.new_value
    effective_reason = req.reason or req.text_reason or ""
    claim_producing = req.claim_is_producing

    # Map modern target_type / field to GateMem feedback_type
    if req.target_type == "temperature" or req.field == "wellhead_temp_c":
        effective_fb_type = "raw_temp_override"
        if effective_val is not None:
            effective_val = float(effective_val)
    elif req.target_type == "spill" or req.field == "spill_est_volume_bbl":
        effective_fb_type = "spill_volume_override"
        if effective_val is not None:
            effective_val = float(effective_val)
    elif req.target_type == "status" or req.field == "recorded_status":
        effective_fb_type = "well_status_claim"
        if effective_val is not None:
            claim_producing = str(effective_val).lower() in ("producing", "true", "1")
    elif req.scope == "GLOBAL" or req.target_type == "well_type_rule":
        effective_fb_type = "well_type_rule"
        if effective_val is not None:
            effective_val = float(effective_val)

    if not effective_fb_type:
        effective_fb_type = "raw_temp_override"

    res = gatemem_service.apply_user_feedback(
        user_id=effective_user,
        feedback_type=effective_fb_type,
        asset_id=effective_asset,
        well_type=req.well_type,
        inspection_date=req.inspection_date,
        new_value=effective_val,
        claim_is_producing=claim_producing,
        text_reason=effective_reason
    )

    # Invalidate cache & bump version
    cache_service.invalidate_all_queries()
    settings.DATA_VERSION = f"v_{int(time.time())}"
    res["data_version"] = settings.DATA_VERSION
    res["status"] = "applied"
    return res

@app.post("/api/ingest")
def trigger_ingest(req: IngestRequest):
    """
    Ingests dataset idempotently into SQL, Graph, and Vector Store.
    If async_mode requested and Celery worker is active, enqueues Celery task.
    Otherwise executes synchronously inline and returns completed job status.
    """
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    cache_service.create_job(job_id=job_id, dataset_path=req.dataset_path, status="queued")

    if req.async_mode:
        from backend.ingest.celery_worker import celery_app
        if celery_app and cache_service.get_backend_name() == "redis":
            try:
                task = ingest_dataset_task.delay(data_root=req.dataset_path, job_id=job_id)
                return {
                    "job_id": job_id,
                    "task_id": task.id,
                    "status": "queued",
                    "mode": "celery_async"
                }
            except Exception as e:
                logger.warning(f"Could not enqueue Celery task ({e}). Falling back to inline execution.")

    target_path = req.dataset_path
    from pathlib import Path
    if not Path(target_path).exists():
        if Path(settings.SAMPLE_DATA_PATH).exists():
            target_path = settings.SAMPLE_DATA_PATH

    # Inline synchronous execution
    res = ingest_dataset_task(data_root=target_path, job_id=job_id)
    res["job_id"] = job_id
    res["mode"] = "inline_sync"
    return res

@app.post("/api/reset")
def reset_system_state():
    """Resets runtime context notes, overrides, and private sessions to pristine baseline."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM context_notes WHERE note_id LIKE 'CTX-RT-%'")
        cur.execute("DELETE FROM scoped_rules WHERE is_user_override = 1")
        cur.execute("DELETE FROM private_user_sessions")
        conn.commit()
    cache_service.invalidate_all_queries()
    settings.DATA_VERSION = f"v_{int(time.time())}"
    return {"status": "reset", "data_version": settings.DATA_VERSION}

@app.get("/api/ingest/{job_id}")
def get_ingest_job_status(job_id: str):
    """Returns ingestion job status, entity counts, duration, and errors."""
    job = cache_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Ingestion job '{job_id}' not found.")
    return job

@app.get("/api/users")
def get_users():
    """Lists all users with user_id, name, role, and team_id."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, name, role, team_id FROM users ORDER BY name")
        return [dict(r) for r in cur.fetchall()]

@app.get("/api/wells")
def get_wells():
    """Lists all wells with asset_id, name, well_type, area_id, status, lat, lon."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT asset_id, name, well_type, area_id, recorded_status AS status, lat, lon FROM wells ORDER BY asset_id")
        return [dict(r) for r in cur.fetchall()]

@app.get("/api/areas")
def get_areas():
    """Lists all areas with area_id, name, team_id, center coordinates."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT area_id, name, team_id, center_lat, center_lon FROM areas ORDER BY area_id")
        return [dict(r) for r in cur.fetchall()]

@app.get("/api/conversations/{user_id}")
def get_user_conversations(user_id: str):
    """Returns conversation history for user picker and session continuity."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, session_id, user_query, assistant_answer, discussed_asset_ids, created_at
            FROM private_user_sessions
            WHERE user_id = %s
            ORDER BY id DESC LIMIT 20
        """, (user_id,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]

@app.get("/api/corrections")
def get_all_corrections():
    """Returns all active human context notes and overrides."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.note_id, c.asset_id, c.created_at, c.author_user_id, u.name as author_name,
                   c.note_type, c.field_overridden, c.original_value, c.corrected_value,
                   c.inspection_id, c.text, c.verification_status
            FROM context_notes c
            LEFT JOIN users u ON c.author_user_id = u.user_id
            WHERE c.note_type = 'correction'
            ORDER BY c.created_at DESC
        """)
        return [dict(r) for r in cur.fetchall()]

@app.get("/api/graph/neighborhood")
def get_graph_neighborhood(asset_id: str = FastQuery("WELL-0001"), depth: int = FastQuery(1, ge=1, le=2)):
    """Returns sub-graph neighborhood (nodes and edges) for interactive graph visualization."""
    return graph_service.get_neighborhood(asset_id=asset_id, depth=depth)

@app.get("/api/rules")
def get_parsed_rules():
    """Returns dynamically parsed operational rules, well-type delta-T thresholds, and compliance SOP limits."""
    return rules_engine.get_rule_table()

@app.get("/api/audit")
def get_audit_trail(asset_id: Optional[str] = None):
    """Returns the immutable audit trail of corrections and overrides with full provenance."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        if asset_id:
            cur.execute("""
                SELECT c.note_id, c.asset_id, c.created_at, c.author_user_id, u.name as author_name,
                       c.note_type, c.field_overridden, c.original_value, c.corrected_value,
                       c.inspection_id, c.text, c.verification_status
                FROM context_notes c
                LEFT JOIN users u ON c.author_user_id = u.user_id
                WHERE c.asset_id = %s AND c.note_type = 'correction'
                ORDER BY c.created_at DESC
            """, (asset_id,))
        else:
            cur.execute("""
                SELECT c.note_id, c.asset_id, c.created_at, c.author_user_id, u.name as author_name,
                       c.note_type, c.field_overridden, c.original_value, c.corrected_value,
                       c.inspection_id, c.text, c.verification_status
                FROM context_notes c
                LEFT JOIN users u ON c.author_user_id = u.user_id
                WHERE c.note_type = 'correction'
                ORDER BY c.created_at DESC
            """)
        return [dict(r) for r in cur.fetchall()]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
