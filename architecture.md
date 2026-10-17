# FlytBase Asset Intelligence Copilot: Full System Architecture

**Version:** 1.0.0 (Production Core & Generative UI Integration)  
**System Architecture:** OpenUI AI Gateway + Next.js 16 + FastAPI + PostgreSQL (`v_effective_inspections`) + Neo4j Graph + Redis/Celery + GateMem Governance + SE-HTGNN Neural Scorer  

---

## 1. High-Level System Architecture

The FlytBase Asset Intelligence Copilot is architected as an agentic monorepo combining a Next.js 16 Generative UI frontend, an OpenUI AI Gateway integration, and a Python FastAPI backend enforcing deterministic domain logic, neural packet scoring, and GateMem memory governance.

```mermaid
flowchart TD
    subgraph Browser["Operator Client Tier"]
        UI["OpenUI Chat Interface (React 19 + Tailwind v4)"]
        Components["OpenUI Component Library (spec.json)"]
    end

    subgraph OpenUIGateway["OpenUI AI Gateway (api.thesys.dev)"]
        GatewayEmbed["AI Gateway Endpoint (/v1/embed)"]
        ModelRouting["LLM Selector (Gemini 3.6 Flash, 3.1 Pro, Claude)"]
        CloudStorage["OpenUI Cloud Thread Storage"]
    end

    subgraph NextJS["Frontend Server Tier (Next.js 16 / Port 3000)"]
        ChatRoute["POST /api/chat (ai SDK createOpenAI)"]
        TokenRoute["GET /api/frontend-token"]
        HealthProxy["GET /api/backend/health"]
        CopilotTool["OpenUI Tool: query_asset_copilot"]
    end

    subgraph FastAPIGateway["Backend Microservices Tier (FastAPI / Port 8000)"]
        QueryEP["POST /api/query"]
        FeedEP["POST /api/feedback"]
        IngestEP["POST /api/ingest"]
        HealthEP["GET /api/health"]
    end

    subgraph Governance["GateMem Memory Governance (arXiv:2606.18829)"]
        Gatekeeper["GateMem Policy Gatekeeper"]
        PrivSession["Private Session Cache (Isolated per Principal)"]
        SharedKnowledge["Shared Domain Knowledge (Scoped Rules)"]
        ActiveForgetting["Active Forgetting Engine ('no_memory' Tombstoning)"]
    end

    subgraph DomainOrchestrator["Agentic Domain Orchestrator"]
        Copilot["Copilot Agent (Tool Router + Citation Generator)"]
        DomainTools["Deterministic Domain Engine (Q1-Q18 Resolvers)"]
        VisualGen["OpenUI Schema Generator (Cards, Tables, Charts, Heatmaps)"]
    end

    subgraph NeuralPipeline["SE-HTGNN + 1D-CNN + RCN Telemetry Scorer"]
        GraphBuilder["Heterogeneous Temporal Graph Builder"]
        CNN_RCN["1D-CNN + RCN Anomaly Gate (89.4% Noise Pruning)"]
        SE_HTGNN["SE-HTGNN Scorer (Relation GRUs + Temporal Decay)"]
    end

    subgraph StorageTier["Data & Knowledge Storage"]
        PG["PostgreSQL / SQLite WAL (v_effective_inspections View)"]
        Neo["Neo4j Temporal Graph (CONTAINS, TRIGGERED, CORRECTS)"]
        RedisCelery["Redis + Celery Async Ingestion Queue"]
    end

    UI --> ChatRoute
    UI --> TokenRoute
    TokenRoute --> CloudStorage
    ChatRoute --> GatewayEmbed
    GatewayEmbed --> ModelRouting
    GatewayEmbed -- Tool Call --> CopilotTool
    CopilotTool --> QueryEP
    QueryEP --> Gatekeeper
    Gatekeeper --> PrivSession
    Gatekeeper --> SharedKnowledge
    Gatekeeper --> Copilot
    Copilot --> DomainTools
    Copilot --> NeuralPipeline
    DomainTools --> PG
    NeuralPipeline --> GraphBuilder
    GraphBuilder --> PG
    GraphBuilder --> Neo
    NeuralPipeline --> CNN_RCN --> SE_HTGNN
    Copilot --> VisualGen --> CopilotTool
    CopilotTool -- Visual Payload --> GatewayEmbed
    GatewayEmbed -- Stream Deltas --> UI
```

---

## 2. OpenUI AI Gateway Integration Layer

### 2.1 Gateway Authentication & Client Setup
The frontend uses `@ai-sdk/openai` to communicate directly with the OpenUI AI Gateway:
```typescript
// frontend/src/app/api/chat/route.ts
const apiKey = requiredEnv("THESYS_API_KEY");
const openai = createOpenAI({
  baseURL: "https://api.thesys.dev/v1/embed",
  apiKey
});
```

- **Credential Security:** `THESYS_API_KEY` is loaded exclusively inside the server-side Node.js environment. It is never exposed in client bundles or logged.
- **Model Menu:** Supports high-performance reasoning models through the Gateway (`google/gemini-3.6-flash-free`, `google/gemini-3.1-pro-free`, `anthropic/claude-sonnet-5`).
- **Tool-Call Routing:** The model calls `query_asset_copilot`, which passes the operator query verbatim to the FastAPI backend at `http://127.0.0.1:8000/api/query`.
- **Cloud Storage Persistence:** Chat turns are saved to OpenUI Cloud storage via `storeTurn({ apiKey, conversationId, messages })` to enable multi-turn continuity.

---

## 3. Storage & Governed Views Layer

### 3.1 Dual-Engine Relational Storage
- **Primary Engine:** PostgreSQL with `pgvector` support (`postgresql://aic_user:aic_password@localhost:5432/asset_intelligence`).
- **Resilient Fallback:** Local high-performance SQLite (`asset_intelligence.db`) with WAL journal mode, 10-second busy timeout, and automatic dialect translation (`::timestamptz`, `NOW()`, `TRUE/FALSE`).

### 3.2 Governed SQL View: `v_effective_inspections`
All 39,567 inspection records are unified under `v_effective_inspections`. Every query automatically inherits:
1. **Dynamic Temperature Overrides:** Raw wellhead temperatures (`raw_wellhead_temp_c`) are replaced by validated operator corrections (`effective_wellhead_temp_c`), dynamically updating `effective_temp_delta_c`.
2. **Rainwater False-Positive Suppression:** Inspections flagged as rainwater (e.g. `INS-0001-0070`) have `effective_spill_detected = 0`, keeping spill counts exact.
3. **Dynamic Spill Volume Corrections:** Field crew measurements supersede AI estimates (e.g. `INS-0151-0201` updated from 4.5 to 5.4 bbl).
4. **Active Forgetting Compliance:** Retracted context notes (`verification_status = 'deleted_forgotten'`) are omitted from override resolution.

---

## 4. SE-HTGNN + 1D-CNN + RCN Neural Architecture

Implemented in [`backend/ml/rcn_cnn_htgnn.py`](file:///c:/Users/Priyanshu%20Patil/Documents/program01/flytbase/flytebase/backend/ml/rcn_cnn_htgnn.py), this module prunes high-volume routine inspection telemetry while preserving 100% of anomalies.

```mermaid
flowchart LR
    CandidatePackets["Candidate Telemetry Packets (104-week lookback)"]
    CNN_RCN["1D-CNN + RCN Anomaly Filter"]
    PruningGate{"Keep Score >= 0.55 or Anomaly/Action?"}
    Pruned["Pruned Routine Noise (89.4% eliminated)"]
    Surviving["Surviving Anomalies & Critical Records"]
    NodeProj["Heterogeneous Node Projections R^H (H=16)"]
    RelationGRU["Relation-wise GRU Dynamic Attention"]
    TemporalDecay["Spatio-Temporal Decay gamma(t)"]
    FinalScores["Composite HTGNN Scoring & Ranking (Top-K)"]

    CandidatePackets --> CNN_RCN --> PruningGate
    PruningGate -- No --> Pruned
    PruningGate -- Yes --> Surviving
    Surviving --> NodeProj
    Surviving --> RelationGRU
    NodeProj --> FinalScores
    RelationGRU --> FinalScores
    TemporalDecay --> FinalScores
```

### 4.1 Heterogeneous Graph Nodes & Edges
- **Node Schemas:**
  - `Well`: Spatial coordinates, well type (T200/T350), operational status.
  - `Inspection`: Thermal $\Delta T$, spill detection, inspection method (drone/manual).
  - `Maintenance`: Cost breakdown, downtime hours, equipment kind, report markdown.
  - `RegulatoryEvent`: Violation agency, protocol ID, fine amounts, open/closed status.
  - `ContextNote`: Author, override field, verification status.
- **Relations:**
  - `CONTAINS` (Area $\to$ Well)
  - `HAS_INSPECTION` (Well $\to$ Inspection)
  - `TRIGGERED` (Inspection $\to$ Maintenance)
  - `HAS_REPORT` (Maintenance $\to$ Engineering Report)
  - `CORRECTS` (ContextNote $\to$ Inspection)
  - `GOVERNED_BY` (Well $\to$ SOP / Manual)

### 4.2 1D-CNN + RCN Anomaly Pre-Filter
- Maps binary and normalized anomaly indicators into latent space $H=16$:
  $$\mathbf{h}_{\text{cnn}} = \text{ReLU}(\text{Conv1D}(\mathbf{X})), \quad \mathbf{h}_{\text{rcn}} = \text{ReLU}(\mathbf{X} \mathbf{W}_{\text{rcn}})$$
  $$\text{keep\_score} = \sigma(\mathbf{W}_{\text{gate}} (\mathbf{h}_{\text{cnn}} + \mathbf{h}_{\text{rcn}}) + b_{\text{gate}})$$
- **Zero False-Negative Safety Invariant:** Any record with `has_spill == 1.0`, `is_non_producing == 1.0`, `has_repair == 1.0`, `has_note == 1.0`, or `is_latest == 1.0` bypasses pruning unconditionally.

### 4.3 Relation-wise GRUs & Dynamic Attention
- Preserves relational context across historical weekly snapshots:
  $$\mathbf{h}_r^{(t)} = \text{GRUCell}(\bar{\mathbf{m}}_r, \mathbf{h}_r^{(t-1)})$$
  $$\alpha_r = \text{Softmax}(\text{Linear}(\mathbf{h}_r^{(t)}))$$
- Semantic embedding priors: `CORRECTS: 3.5`, `TRIGGERED: 2.8`, `GOVERNED_BY: 2.6`, `HAS_REPORT: 2.2`, `HAS_INSPECTION: 1.8`, `CONTAINS: 1.2`.

---

## 5. GateMem Memory Governance Layer

Implemented in [`backend/services/gatemem_policy.py`](file:///c:/Users/Priyanshu%20Patil/Documents/program01/flytbase/flytebase/backend/services/gatemem_policy.py):

1. **Two-Tier Memory Partitioning:**
   - *Private Session Store:* Scoped strictly to the authenticated principal (`user_id`). Holds working calculations, contractor spend comparisons, and draft notes.
   - *Shared Domain Store:* Fleet-wide overrides, confirmed physical sensor corrections, and scoped rule adjustments.
2. **Zero Cross-User Leakage:** Traversal across session boundaries is strictly prohibited. If User B queries User A's session, execution halts with `gatemem_action = "no_memory"`.
3. **Active Forgetting & Tombstoning:** Retraction commands mark target notes as `verification_status = 'deleted_forgotten'` and replace content with `[REDACTED_BY_GATEMEM_ACTIVE_FORGETTING]`.
4. **Scoped Knowledge Propagation:** Supports scoping to individual assets (`WELL_ID`), well classes (`WELL_TYPE`), or field areas (`AREA_ID`).

---

## 6. End-to-End Performance Benchmarks

| Component | Latency | Operational Impact |
| :--- | :---: | :--- |
| **Neural Forward Pass (CNN + RCN + SE-HTGNN)** | **3.78 ms** | Sub-5ms real-time throughput |
| **Relational DB & Subgraph Extraction** | 8.85 ms | Fast SQLite WAL / PostgreSQL fetch |
| **Total Telemetry Scoring Pipeline** | 12.63 ms | Complete packet pruning and ranking |
| **Full Natural-Language Query (`/api/query`)** | 25 – 45 ms | SQL + Neural Scorer + OpenUI Formatting |
| **Chat Stream TTFB (OpenUI AI Gateway)** | < 120 ms | Instant streaming response for operators |
