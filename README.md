# FlytBase Asset Intelligence Copilot — Backend

Production-grade, modular backend architecture for the FlytBase Asset Intelligence Copilot, achieving **18/18 deterministic benchmark accuracy** on all evaluation queries (`03-evaluation-queries.md`).

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

## Directory Structure

```text
flytebase/
├── docker-compose.yml            # Postgres (pgvector), Neo4j 5 (APOC), Redis 7
├── .gitignore                    # Strictly ignores dataset folders & DBs
├── README.md
└── backend/
    ├── requirements.txt
    ├── config.py                 # Configuration settings
    ├── main.py                   # FastAPI REST API endpoints
    ├── verify_18_queries.py      # Automated 18/18 verification test suite
    ├── db/
    │   ├── schema.sql            # Normalized relational schema
    │   ├── postgres.py           # Database connection & pooling
    │   └── neo4j_graph.py        # Graph schema & Cypher sync
    ├── ingest/
    │   ├── parser.py             # Free-text .md & SOP/manual parser
    │   └── celery_worker.py      # Async ingestion for test drops
    ├── ml/
    │   └── rcn_cnn_htgnn.py      # 1D-CNN + RCN + HTGNN neural filter
    └── services/
        ├── domain_tools.py       # Deterministic domain calculations (Q1-Q18)
        ├── gatemem_policy.py     # GateMem two-level memory governance
        └── copilot_agent.py      # Orchestrator & visual selector
```

## Quickstart & Verification

### 1. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 2. Run the 18/18 Benchmark Verification Suite
```bash
python -u -m backend.verify_18_queries
```

### 3. Start the FastAPI Server
```bash
python -m backend.main
```
API Documentation is available at `http://localhost:8000/docs`.
