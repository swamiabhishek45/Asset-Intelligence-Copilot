# Frontend context (session log)

Last updated: 2026-10-17 (sidebar layout fix)

## Stack

- **Next.js 16** (App Router) scaffolded with `npx @openuidev/cli@latest create . --no-interactive --backend-framework vercel-ai-sdk`
- **OpenUI** Agent Interface + Gateway (`THESYS_API_KEY`) for generative UI streaming
- **shadcn-style** primitives under `src/components/ui/` (neutral black/white tokens in `globals.css`)
- **FlytBase FastAPI backend** at `BACKEND_API_URL` for deterministic copilot answers

## Product goal

Operator-facing chat for the FlytBase Asset Intelligence challenge: well status, inspections, maintenance, SOP/RAG, benchmark-style questions (Q1–Q18). UI should read as **industrial documentation**, not marketing fluff—monochrome, tight typography, no glow/mascot chrome.

## Key files

| Path | Role |
|------|------|
| `src/components/cloud-chat.tsx` | OpenUI Agent Interface shell, starters, theme |
| `src/app/flytbase-openui.css` | OpenUI + Tailwind layout fixes (sidebar width, footer) |
| `src/app/api/chat/route.ts` | Vercel AI SDK → OpenUI Gateway + FlytBase system appendix |
| `src/lib/tools/query-asset-copilot.ts` | Server tool → `POST /api/query` |
| `src/lib/flytbase-prompt.ts` | Domain instructions for the model |
| `src/components/backend-status.tsx` | shadcn Card + health poll |
| `docs/BACKEND-INTEGRATION.md` | API contract |

## Branch

Work on **`frontend-dev`**; commit only under `frontend/`.

## User action required

1. Generate OpenUI Gateway key (never commit it):

   ```bash
   cd frontend && npm run generate:apiKey
   ```

   Paste into `frontend/.env` as `THESYS_API_KEY=…`

2. Run backend before testing asset questions (see BACKEND-INTEGRATION.md).

## Verification notes

- **Dev server:** `npm run dev` → http://localhost:3000 (Next.js 16 + OpenUI spec regen on predev).
- **UI load:** Title “FlytBase Asset Copilot”; monochrome shell with FlytBase sidebar brand and backend status card.
- **Chat smoke test:** `POST /api/chat` with a user message returned **HTTP 500**. Next.js server log:

  ```text
  ⨯ Error: Missing required env var: THESYS_API_KEY
      at requiredEnv (src/lib/env.ts:3:21)
      at module evaluation (src/app/api/chat/route.ts:24:27)
  POST /api/chat 500 in …ms
  ```

  Set `THESYS_API_KEY` via `npm run generate:apiKey` before sending chat messages.

- **Backend:** Not running in agent environment (`fastapi` not installed / use `python3 -m backend.main` after `pip install -r backend/requirements.txt`). Sidebar shows **offline** until `/api/health` succeeds.
