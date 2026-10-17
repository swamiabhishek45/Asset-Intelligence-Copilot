# FlytBase Asset Intelligence Copilot — Project Report

*Version 2.0.0 · Evaluation reference date: 16 October 2026 · Repository: flytebase (monorepo)*

---

## Page 1 — System Architecture

### 1.1 Executive Summary

The FlytBase Asset Intelligence Copilot is an operator-facing agent for upstream oil and gas field operations. It answers natural-language questions about **200 wells** across four operating areas using a hybrid architecture: **deterministic SQL and SOP rules** produce every operational number; **GateMem** governs memory and privacy; **graph-augmented retrieval** and an **RCN + 1D-CNN + HTGNN** telemetry ranker supply context; and **OpenUI** (via the AI Gateway) renders streaming generative UI. The large language model orchestrates dialogue and layout—it does **not** invent downtime days, spill volumes, or compliance outcomes.

**Current status:** Dataset ingested (39,567 inspections, 5,665 maintenance records); OpenUI Gateway connected; **44/44** automated verification checks passing.

### 1.2 System Architecture Overview

The system is a three-tier agentic stack: **browser client**, **Next.js + OpenUI Gateway**, and **FastAPI backend** with multi-database persistence.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    OPERATOR (Web Browser — localhost:3000)                   │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ HTTPS
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PRESENTATION TIER — Next.js 16 + OpenUI Agent Interface                     │
│  • React 19, Tailwind v4, industrial documentation-style UI                  │
│  • Model switcher (Gateway-backed models)                                    │
│  • Streaming OpenUI Lang → component renderer (cards, tables, charts, maps)  │
│  • Server routes: /api/chat, /api/backend/health, users, feedback           │
└───────────────┬─────────────────────────────┬───────────────────────────────┘
                │ THESYS_API_KEY (server only)  │ BACKEND_URL
                ▼                               ▼
┌───────────────────────────────┐   ┌─────────────────────────────────────────┐
│ OpenUI AI Gateway             │   │ APPLICATION TIER — FastAPI (:8000)         │
│ api.thesys.dev/v1/embed       │   │ POST /api/query · POST /api/ingest         │
│ Streaming, autofix, tool calls│   │ GET /api/health · POST /api/feedback       │
└───────────────────────────────┘   └───────────────────┬─────────────────────┘
                                                          │
              ┌───────────────────────────────────────────┼───────────────────────┐
              │              QUERY PROCESSING PIPELINE    │                       │
              ▼                     ▼                     ▼                       ▼
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐
   │ GateMem Policy   │  │ Rules Engine     │  │ Domain Tools     │  │ Copilot Agent   │
   │ Private sessions │→ │ SOPs from fleet/ │→ │ Q1–Q18 resolvers │→ │ RAG + citations │
   │ Shared overrides │  │ markdown at boot │  │ Downtime, spills │  │ Visual schemas  │
   │ Active forgetting│  │ T200/T350 ΔT     │  │ SOP/RCA audit    │  │ for OpenUI      │
   └──────────────────┘  └──────────────────┘  └────────┬─────────┘  └─────────────────┘
                                                          │
              ┌───────────────────────────────────────────┼───────────────────────┐
              ▼                     ▼                     ▼                       ▼
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐
   │ RCN+CNN+HTGNN    │  │ PostgreSQL       │  │ Neo4j 5          │  │ Redis + Celery  │
   │ Evidence ranker  │  │ pgvector, WAL    │  │ Temporal graph   │  │ Cache, async      │
   │ ~4 ms inference  │  │ v_effective_*    │  │ Well–event edges │  │ ingest jobs       │
   └──────────────────┘  └──────────────────┘  └──────────────────┘  └─────────────────┘
```

**Resilience:** Each tier falls back gracefully—PostgreSQL → SQLite, Neo4j → in-memory NetworkX, Redis → in-process TTL cache—so local development and demos stay operational without every container running.

### 1.3 End-to-End Request Flow

1. Operator submits a question in the chat UI (optionally as a specific user ID for GateMem tests).
2. Next.js `/api/chat` streams to the OpenUI Gateway with a system prompt derived from the component library (`spec.json`) and registers the tool **`query_asset_copilot`**.
3. The model invokes the tool; the frontend proxies **`POST /api/query`** to FastAPI with `query`, `user_id`, and `session_id`.
4. **GateMem** resolves memory scope (private session vs fleet-wide shared knowledge, forget commands, cross-user blocks).
5. **Rules engine** loads thresholds and regulatory limits from `fleet/well-types/*.md` and `fleet/sops/*.md` (not hardcoded constants).
6. **Domain tools** run deterministic SQL against **`v_effective_inspections`** and related tables; graph lookups augment multi-hop explanations.
7. **Telemetry ranker** prunes routine sensor packets (~89% noise) while retaining spills, downtime, repairs, and human notes.
8. **Copilot agent** assembles markdown answer, citations, `visual_type`, and `visual_payload`.
9. Gateway streams OpenUI Lang; the browser renders status cards, tables, line/bar charts, maps, or heatmaps.

### 1.4 Core Design Principles

| Principle | Rationale | Implementation |
|-----------|-----------|----------------|
| Numbers from data | Prevent LLM hallucination on metrics | SQL views, domain tools, rules engine |
| Inspection > static record | Admin `recorded_status` lags reality | Latest ΔT vs T200/T350 threshold |
| Governed corrections | Audit trail for operator overrides | `context_notes` → `v_effective_inspections` |
| Memory governance | Privacy + fleet propagation | GateMem (arXiv:2606.18829) |
| Separation of concerns | Safe evolution of UI vs logic | REST contract; no Python in frontend |

---

## Page 2 — Domain, Components & Data

### 2.1 Problem Domain

**Environment:** Upstream oil and gas field asset intelligence.

**Coverage:** Southwest Block 23, Southwest Block 24, Northeast Block 7, Northeast Block 8.

**Fleet:** Wells `WELL-0001`–`WELL-0200`; well classes **T200** (ΔT ≥ 15.0 °C ⇒ producing) and **T350** (ΔT ≥ 20.0 °C ⇒ producing).

**Key domain rules:**

- **Truth hierarchy:** Latest thermal inspection supersedes `wells.recorded_status`; stale “active” flags trigger explicit out-of-date warnings.
- **Downtime:** Non-producing inspection weeks count as 7-day downtime windows; annual totals sum weeks and maintenance-linked repair downtime.
- **Spills:** Rainwater false positives suppressed via validated context notes; volumes in bbl; **SR-01** reportable threshold ≥ 5.0 bbl within 24 hours.
- **Compliance:** **SR-02** containment ≤ 4.0 h; **SR-03** 60-day follow-up; **RC-04** RCA after ≥ 3 repairs in 12 months (thresholds parsed from SOP markdown).

### 2.2 Technology Stack

| Layer | Technologies |
|-------|----------------|
| Frontend | Next.js 16, React 19, Tailwind v4, OpenUI (`@openuidev/*`), Vercel AI SDK |
| Gateway | OpenUI AI Gateway (`https://api.thesys.dev/v1/embed`) |
| Backend | Python 3, FastAPI, Uvicorn, Pydantic |
| Data | PostgreSQL 16 + pgvector, Neo4j 5 + APOC, Redis 7, Celery |
| ML / ranking | RCN + 1D-CNN + HTGNN evidence prefilter (rule-based + graph-weighted) |
| Ops | Docker Compose, Makefile, pytest verification suites |

### 2.3 Backend Module Map

| Module | Path | Responsibility |
|--------|------|----------------|
| API surface | `backend/main.py` | Health, ingest, query, feedback, users |
| GateMem | `backend/services/gatemem_policy.py` | Sessions, propagation, forgetting, isolation |
| Rules | `backend/services/rules_engine.py` | Document-driven SOP and well-type thresholds |
| Domain | `backend/services/domain_tools.py` | Benchmark resolvers, downtime, spills, audits |
| Agent | `backend/services/copilot_agent.py` | Routing, RAG, visual schema selection |
| RAG | `backend/services/rag_engine.py` | Retrieval over embeddings and reports |
| Ranker | `backend/ml/rcn_cnn_htgnn.py` | Telemetry packet scoring and pruning |
| Ingest | `backend/ingest/` | Parser, Neo4j embed ingest, Celery tasks |
| Schema | `backend/db/schema.sql` | Tables, indexes, governed views |

### 2.4 Data Model & Governed View

**PostgreSQL** holds wells, inspections, maintenance, regulatory events, context notes, and document embeddings.

**`v_effective_inspections`** unifies ~39,567 inspection rows with:

- Effective temperatures after operator corrections
- Rainwater spill suppression (`effective_spill_detected = 0`)
- Spill volume corrections with provenance
- Exclusion of GateMem-tombstoned notes (`deleted_forgotten`)

**Neo4j** models heterogeneous relations: `CONTAINS`, `HAS_INSPECTION`, `TRIGGERED`, `CORRECTS`, `GOVERNED_BY`, `NEARBY_WELL`, supporting graph-augmented explanations.

**Ingest source:** `flytbase-ahc-swe-asset-intelligence-dataset/sample-data` (200 wells, inspections, maintenance JSONL, fleet markdown).

---

## Page 3 — GateMem, ML, Frontend & API

### 3.1 GateMem Memory Governance

GateMem implements two-tier memory:

- **Private session store:** Per `user_id`; working notes and session-specific calculations (e.g. Q11 contractor spend recall for Michael Turner).
- **Shared domain store:** Fleet-wide temperature overrides, spill corrections, scoped rule changes (e.g. T350 RCA threshold).

**Behaviors verified in benchmark suite:**

- **Cross-user isolation (Q16):** Unauthorized recall returns `gatemem_action = "no_memory"` and the message *"I have no earlier conversation with you about that."*
- **Active forgetting:** Forget commands tombstone records and redact text from retrieval.
- **Conflict detection (Q17–Q18):** Unconfirmed claims surface inspector disagreement rather than silently overwriting sensor truth.
- **Scoped propagation (Q14–Q15):** Rule changes apply to intended well type or asset without polluting unrelated classes.

### 3.2 Evidence Prefilter & Graph Ranker

The module in `backend/ml/rcn_cnn_htgnn.py` is an **evidence prefilter and relation-weighted ranker**, not a black-box numeric calculator. Final answers always come from deterministic SQL.

**Performance (measured):**

- Neural forward pass: **~3.8 ms**
- ~**89.4%** routine telemetry pruned per well (2-year lookback)
- **100%** retention of critical events (spills, downtime, repairs, notes)
- End-to-end `/api/query`: **25–45 ms** typical

**Safety invariant:** Records with spill, non-producing, repair, note, or “latest inspection” flags bypass pruning; non-existent well IDs are dropped before ranking.

### 3.3 Frontend & OpenUI Integration

- **Chat route:** `frontend/src/app/api/chat/route.ts` — Gateway client, tool wiring, thread persistence.
- **Tool:** `query_asset_copilot` forwards operator text to FastAPI and returns structured results to the model.
- **Visual types:** `status_card`, `table`, `line_chart`, `bar_chart`, `map`, `heatmap`, `text`.
- **Specialized views:** `FlytMapView`, `FlytHeatmapView` for geo and matrix queries.
- **User picker:** Switch test personas (e.g. U-201 vs U-202) for GateMem scenarios.
- **Security:** `THESYS_API_KEY` and backend URLs remain server-side only.

### 3.4 REST API Summary

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/health` | DB/graph/cache status, wells loaded, `as_of_date` |
| POST | `/api/ingest` | Load dataset (sync or Celery `async_mode`) |
| POST | `/api/query` | Primary copilot query |
| POST | `/api/feedback` | Operator corrections and scoped rules |

Frontend proxies: `/api/backend/health`, `/api/backend/users`, `/api/backend/feedback`.

---

## Page 4 — Deployment, Verification & Conclusion

### 4.1 Deployment

**Full stack (recommended):**

```bash
docker compose up -d
```

Services: Postgres (5432), Neo4j (7474/7687), Redis (6379), backend (8000), Celery worker, frontend (3000).

**Key environment variables:** `POSTGRES_DSN`, `NEO4J_URI`, `REDIS_URL`, `SAMPLE_DATA_PATH`, `AS_OF_DATE`, `THESYS_API_KEY` (frontend server), optional `OPENAI_API_KEY` / `GEMINI_API_KEY`.

### 4.2 Verification & Test Results

| Suite | Scope | Result |
|-------|-------|--------|
| `backend/verify_18_queries.py` | Benchmark Q1–Q18 | 18/18 PASS |
| `backend/test_chat_e2e.py` | Chat API + payloads | 19/19 PASS |
| `backend/test_unseen_generalization.py` | Unseen wells, GateMem | 7/7 PASS |
| `backend/run_final_showdown.py` | Full pipeline | 44/44 PASS |
| `tests/test_rephrasings.py` | Query paraphrases | 47/47 PASS |
| `tests/test_sop_variation.py` | Markdown-driven SOP changes | PASS |

Screenshots for representative queries captured under `docs/screens/` (Q1, Q2, Q3, Q6, Q7, Q8, Q9).

### 4.3 Generalization to Unseen Evaluation

Three invariants support held-out wells (`WELL-0201+`), new areas (e.g. `NW-01`), and shifted dates without code changes:

1. **Document-driven rules** from `fleet/` markdown at startup.
2. **Dynamic area and asset resolution** from `fleet/areas.json` and `WELL-\d+` matching.
3. **Single governed numeric source:** `v_effective_inspections` for all inspection-derived metrics.

### 4.4 Conclusion

The FlytBase Asset Intelligence Copilot delivers a production-shaped architecture that combines generative UI with strict deterministic grounding. Operators receive conversational answers backed by SQL, auditable corrections, privacy-preserving memory, and rich visuals—while the system remains testable, ingestible, and generalizable to unseen fleet data.

### 4.5 References (Repository)

- `architecture.md` — Extended diagrams and performance tables
- `docs/SYSTEM_DOCUMENTATION.md` — Two-page technical summary
- `frontend/docs/BACKEND-INTEGRATION.md` — Proxy and env wiring
- `context.md` — Domain physics and Q1–Q18 summary
- `backend/README.md` — Backend quickstart

---

*End of project report*
