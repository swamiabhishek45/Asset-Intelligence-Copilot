from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from backend.config import settings
from backend.ingest.celery_worker import ingest_dataset_task
from backend.services.domain_tools import domain_engine
from backend.services.gatemem_policy import gatemem_service
from backend.services.copilot_agent import copilot_agent
from backend.db.postgres import get_db_connection

app = FastAPI(
    title="FlytBase Asset Intelligence Copilot Backend",
    version="1.0.0",
    description="Agentic backend architecture with GateMem memory governance and RCN+CNN+HTGNN scoring"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class IngestRequest(BaseModel):
    dataset_path: str = settings.SAMPLE_DATA_PATH
    async_mode: bool = False

class FeedbackRequest(BaseModel):
    user_id: str
    feedback_type: str  # 'raw_temp_override' | 'spill_volume_override' | 'well_type_rule' | 'well_status_claim'
    asset_id: Optional[str] = None
    well_type: Optional[str] = None
    inspection_date: Optional[str] = None
    new_value: Optional[float] = None
    claim_is_producing: Optional[bool] = None
    text_reason: str = ""

class QueryRequest(BaseModel):
    query: str
    user_id: str = "U-201"
    session_id: Optional[str] = "session-1"

@app.get("/api/health")
def health_check():
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM wells")
        w_cnt = cur.fetchone()["cnt"]
    return {
        "status": "healthy",
        "wells_loaded": w_cnt,
        "benchmark_today": settings.BENCHMARK_TODAY
    }

@app.get("/api/users")
def get_users():
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, name, role, team_id FROM users ORDER BY name")
        return cur.fetchall()

@app.post("/api/ingest")
def trigger_ingest(req: IngestRequest):
    """Hot-loads datasets at startup and for final 2-hour test drop."""
    if req.async_mode:
        from backend.ingest.celery_worker import celery_app
        if celery_app:
            task = ingest_dataset_task.delay(req.dataset_path)
            return {"status": "queued", "task_id": task.id}
    return ingest_dataset_task(req.dataset_path)

@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest):
    """Enforces GateMem memory policy and cascades updates."""
    return gatemem_service.apply_user_feedback(
        user_id=req.user_id,
        feedback_type=req.feedback_type,
        asset_id=req.asset_id,
        well_type=req.well_type,
        inspection_date=req.inspection_date,
        new_value=req.new_value,
        claim_is_producing=req.claim_is_producing,
        text_reason=req.text_reason
    )

@app.post("/api/query")
def process_chat_query(req: QueryRequest):
    """Answers operator plain-English queries with visual and citations."""
    return copilot_agent.answer_query(
        query=req.query,
        user_id=req.user_id,
        session_id=req.session_id
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
