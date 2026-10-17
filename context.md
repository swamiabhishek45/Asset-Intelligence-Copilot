# FlytBase Asset Intelligence Copilot: Domain & Gateway Context

**Evaluation Reference Date:** 16 October 2026  
**Operating Environment:** Upstream Oil & Gas Field Asset Intelligence  
**Geographic Coverage:** 4 Operating Areas (Southwest Block 23, Southwest Block 24, Northeast Block 7, Northeast Block 8)  
**Fleet Inventory:** 200 Wells (`WELL-0001` through `WELL-0200`) across T200 and T350 classes  
**User Interface Framework:** OpenUI Generative UI with Next.js 16 + OpenUI AI Gateway  

---

## 1. Domain Physics & Operational Rules

### 1.1 Wellhead Thermal Production Test
Oil flow generates frictional and geothermal heat at the wellhead relative to ambient temperature:
$$\Delta T = T_{\text{wellhead}} - T_{\text{ambient}}$$

- **Model T200 Wells:**
  - Standard Operating Manual: `fleet/well-types/T200.md`
  - Normal Operating Threshold: $\Delta T \ge 15.0\,^\circ\text{C} \implies \text{Producing Oil}$
  - Below Threshold: $\Delta T < 15.0\,^\circ\text{C} \implies \text{Not Producing (Shut-in / Cold)}$
- **Model T350 Wells:**
  - Standard Operating Manual: `fleet/well-types/T350.md`
  - Normal Operating Threshold: $\Delta T \ge 20.0\,^\circ\text{C} \implies \text{Producing Oil}$
  - Below Threshold: $\Delta T < 20.0\,^\circ\text{C} \implies \text{Not Producing (Shut-in / Cold)}$

### 1.2 Truth Hierarchy: Sensor Observation vs. Static Record
- Database attribute `wells.recorded_status` (e.g. `'active'`, `'shut_in'`) is frequently stale due to manual administrative delay.
- The latest inspection reading (thermal $\Delta T$ and visual flow verification) **supersedes** `recorded_status`.
- If latest inspection indicates non-producing ($\Delta T < \text{threshold}$) but `recorded_status == 'active'`, the copilot reports:
  `Not producing oil right now; recorded status 'active' is out of date.`

### 1.3 Downtime Accounting
- Weekly drone and ground inspections occur at 7-day intervals.
- When a well is inspected and identified as non-producing, that inspection represents a full **7-day downtime window** unless verified otherwise by an operational startup log.
- Annual or date-range downtime is calculated by summing non-producing inspection weeks ($7 \times N_{\text{offline}}$ days) and cross-referencing repair downtime recorded in `maintenance.jsonl`.

### 1.4 Environmental Spills & False-Positive Elimination
- **Spill Detection:** Drones and ground cameras detect surface liquid accumulations.
- **Rainwater Suppression (Q4):** Rainwater accumulation, shadows, and water pooling occasionally trigger false spill detections (e.g. inspection `INS-0001-0070` on 2024-04-03). Validated context notes (`note_type = 'correction'`, text indicating rainwater/puddle) suppress false positives (`effective_spill_detected = 0`).
- **Spill Volume Accounting:** Total spill volume sums only verified crude oil events in barrels (bbl).
- **Reportable Threshold (SR-01):** Spills $\ge 5.0\,\text{bbl}$ require mandatory formal notification to environmental regulators within 24 hours.

---

## 2. Standard Operating Procedures (SOPs) & Regulatory Governance

| Protocol ID | Protocol Title | Critical Compliance Criteria |
| :--- | :--- | :--- |
| **SR-01** | Spill Notification Requirement | Mandatory notification within 24 hours for spills $\ge 5.0\,\text{bbl}$. |
| **SR-02** | Containment Duration Limits | Time from spill discovery to containment must not exceed **6.0 hours**. Any containment taking $> 6.0\,\text{h}$ constitutes a regulatory violation. |
| **SR-03** | 60-Day Corrective Action Follow-up | Following a reportable spill, corrective repair verification must occur within **60 days**. Open actions without verified repair are flagged. |
| **RC-04** | Root Cause Analysis (RCA) Trigger | Any equipment kind (e.g. `flowline`, `rod_string`) experiencing **$\ge 3$ repair events** within a 12-month rolling window triggers a mandatory formal RCA investigation. |
| **WS-03** | Hydrogen Sulfide ($H_2S$) Safety Protocol | Area containment and respiratory gear required when atmospheric concentration exceeds **10 ppm**. |

---

## 3. OpenUI AI Gateway & Generative UI Context

The frontend leverages the OpenUI AI Gateway (`https://api.thesys.dev/v1/embed`) to provide streaming conversational UI generation for oil field operators:

```text
[Operator Browser]
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ OpenUI Agentic Interface (React 19 + Tailwind v4)      │
│ - Model Switcher (Gemini 3.6 Flash, 3.1 Pro, Claude)   │
│ - Chat Stream Adapter (vercelAIAdapter)                │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Next.js API Chat Route (/api/chat)                     │
│ - Authenticated to OpenUI AI Gateway via THESYS_API_KEY│
│ - OpenAI Client: https://api.thesys.dev/v1/embed       │
│ - Tool Registration: query_asset_copilot               │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ FastAPI Asset Intelligence Backend (/api/query)        │
│ - Deterministic GateMem Governance + SQL Views         │
│ - SE-HTGNN Neural Telemetry Scorer                     │
│ - Generates OpenUI Visual Schema Payloads              │
└────────────────────────────────────────────────────────┘
```

### 3.1 Visual Schemas Returned to OpenUI
When operators query the copilot, responses contain structured visual payloads rendered dynamically:
- **`status_card`:** Single-well diagnostics (producing state, temperature delta, threshold, inspector name, and out-of-date warnings).
- **`table`:** Multi-asset matrices (e.g. offline wells across Northeast Block 8, contractor repair cost summaries).
- **`line_chart`:** Multi-week time series (e.g. 13-week thermal readings with operating threshold guide lines).
- **`bar_chart`:** Comparative downtime and financial rankings (e.g. top downtime assets in Northeast Block 7).
- **`map`:** Geo-coordinate scatter pins for spills, containment breaches, and offline wells.
- **`heatmap`:** Area $\times$ Month spill frequency matrices.

---

## 4. GateMem Memory Governance (arXiv:2606.18829)

The copilot implements the GateMem memory architecture to prevent hallucinations, cross-user privacy leaks, and ungrounded overrides:

- **Two-Tier Isolation:** Private sessions are strictly accessible only by the creating user (`user_id`). Shared knowledge (temperature overrides, validated spill measurements) propagates fleet-wide.
- **Zero Cross-User Leakage:** A query from Operator B attempting to access Operator A's private discussions halts with `gatemem_action = "no_memory"`.
- **Active Forgetting:** Commands such as *"Forget note for WELL-0099"* mark the record `deleted_forgotten`, redacting the text and preventing retrieval.
- **Conflict Handling:** When human claims conflict with physical telemetry, the copilot surfaces an `Inspector Disagreement` alert rather than silently overwriting sensor truth.

---

## 5. Benchmark Evaluation Scenarios (Q1–Q18) Summary

| Scenario | Objective | Ground Truth / Target Resolution |
| :--- | :--- | :--- |
| **Q1** | WELL-0001 Current Status | Not producing ($\Delta T=3.2^\circ\text{C}$ vs $15.0^\circ\text{C}$ threshold), inspected 2026-10-15 by Ryan Brooks, recorded status `active` is out of date. |
| **Q2** | Northeast Block 8 Offline Wells | 4 offline wells: `WELL-0164`, `WELL-0170`, `WELL-0172`, `WELL-0175`. |
| **Q3** | WELL-0001 13-Week Trend | 13 readings; non-producing on 2026-10-08 ($\Delta T=3.5^\circ\text{C}$) and 2026-10-15 ($\Delta T=3.2^\circ\text{C}$). |
| **Q4** | WELL-0001 Spill History | 6 valid spills totaling 15.1 bbl; `INS-0001-0070` excluded as rainwater. |
| **Q5** | WELL-0001 2025 Downtime | 21 days downtime (3 non-producing weeks: `MNT-0001-021`, `MNT-0001-023`). |
| **Q6** | NE Block 7 Top Downtime | Top 3 wells: `WELL-0121` (49d), `WELL-0138` (42d), `WELL-0107` (42d). |
| **Q7** | NE Block 8 90-Day Spills | 4 spill pins: `WELL-0186`, `WELL-0165`, `WELL-0175`, `WELL-0151`. |
| **Q8** | 2026 Fleet Spill Heatmap | Month $\times$ Area matrix; Southwest Block 24 highest (43 spills). |
| **Q9** | WELL-0001 SOP Audit | 4 breaches (SR-01, SR-02 7.0h, open SR-03, open RC-04 Flowline RCA, $5,000 fine). |
| **Q10** | SW Block 24 Containment Breaches | `WELL-0082` (7.1h) and `WELL-0100` (8.1h) exceeded 6.0h limit. |
| **Q11** | Private Session Recall | Recalls Michael Turner's private session: `WELL-0121` (\$25,794), `WELL-0138` (\$46,942), `WELL-0107` (\$5,176). |
| **Q12** | Raw Temp Correction | Overrides 2026-10-15 reading for `WELL-0164` to $41.0^\circ\text{C}$; excludes it from Q2 offline list. |
| **Q13** | Spill Volume Correction | Corrects `WELL-0151` spill from 4.5 to 5.4 bbl; cascades SR-01 notice breach and SR-03 follow-up. |
| **Q14** | Scoped Rule Override | Lowers T350 RCA threshold from 3 to 2 repairs (adds `WELL-0120`); preserves T200 threshold at 3. |
| **Q15** | Cross-User Propagation | Jessica Reed sees `WELL-0164` producing; Laura Diaz sees `WELL-0151` reportable. |
| **Q16** | Cross-User Isolation | Jessica Reed blocked from Michael Turner's private session (`no_memory`). |
| **Q17** | Data Conflict Detection | Unconfirmed user claims flagged with `Inspector Disagreement` alert. |
| **Q18** | AI Disagreement Resolution | Ryan Brooks vs. Chris Dalton; sensor evidence stands with full audit trail. |
