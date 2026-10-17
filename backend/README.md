# Backend — FlytBase Asset Intelligence Copilot

Production-grade backend for the FlytBase Asset Intelligence Copilot.

**Work on this code from the `backend-dev` branch.** Only change files under `backend/` (and coordinate before editing shared root files).

## System Architecture

```text
                                 [ User Query ]
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │    GateMem Policy Engine      │
                       │    (arXiv:2606.18829)         │
                       │  - Private session isolation  │
                       │  - Conflict & integrity check │
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │   Deterministic Domain Tools  │
                       │  - Precedence rule evaluation │
                       │  - Weekly downtime counting   │
                       │  - SOP & RCA audit automation │
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │    RCN + CNN + HTGNN Model    │
                       │  - 1D-CNN thermal anomaly scan│
                       │  - Relational Conv Net (RCN)  │
                       │  - Heterogeneous Temporal GNN │
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │        Multi-DB Storage       │
                       │  - PostgreSQL (pgvector)      │
                       │  - Neo4j Temporal Graph       │
                       │  - Redis / Celery Task Queue  │
                       │  - SQLite (WAL) Fast Engine   │
                       └───────────────────────────────┘
```

## Layout

```text
backend/
├── requirements.txt
├── config.py
├── main.py                   # FastAPI REST API
├── verify_18_queries.py      # Benchmark verification
├── test_chat_e2e.py          # E2E chat pipeline tests
├── db/
├── ingest/
├── ml/
└── services/
```

## Quickstart

```bash
pip install -r backend/requirements.txt
python -u -m backend.verify_18_queries
python -m backend.main
```

API docs: `http://localhost:8000/docs`
