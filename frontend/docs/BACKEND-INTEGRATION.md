# Backend integration

The frontend does **not** embed Python logic. It proxies operator questions to the FastAPI copilot.

## Endpoints

| Frontend route | Backend route | Purpose |
|----------------|---------------|---------|
| `GET /api/backend/health` | `GET /api/health` | Sidebar status (wells loaded, benchmark date) |
| OpenUI tool `query_asset_copilot` | `POST /api/query` | GateMem + domain tools + RAG answers |
| Mic (OpenAI Realtime) | `POST /api/realtime/session`, `POST /api/realtime/tool` | Voice WebRTC session + same `/api/query` tool |

## Request shape (`POST /api/query`)

```json
{
  "query": "Is WELL-0164 producing oil?",
  "user_id": "U-201",
  "session_id": "frontend-session"
}
```

## Response shape

```json
{
  "text": "Markdown answer for operators",
  "visual_type": "status_card | table | text | …",
  "visual_payload": {},
  "citations": ["…"],
  "pipeline_telemetry": {}
}
```

The OpenUI agent calls `query_asset_copilot`, then renders `text` and structured metrics using the OpenUI component library.

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_API_URL` | `http://127.0.0.1:8000` | FastAPI base URL (server-side only) |
| `THESYS_API_KEY` | — | OpenUI Gateway key for generative UI (server-side only) |
| `OPENAI_API_KEY` | — | OpenAI Realtime voice (server-side only; mic disabled if unset) |
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-2.1` | Realtime model id for voice sessions |
| `OPENAI_REALTIME_VOICE` | `marin` | TTS voice for Realtime output |

## Voice (OpenAI Realtime)

The chat composer includes a **mic toggle**. When enabled, the browser opens a WebRTC session using a short-lived token from `POST /api/realtime/session`. Asset questions invoke `POST /api/realtime/tool`, which calls the same FastAPI `POST /api/query` as text chat. Spoken answers are played in the browser; transcripts and OpenUI visuals are **appended to the active thread**.

Requires `OPENAI_API_KEY` in `frontend/.env` (never expose to the client bundle).

## Local stack

```bash
# Terminal 1 — from repo root (use a venv on Debian/Ubuntu PEP 668 systems)
docker compose up -d
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python -m backend.main

# Terminal 2 — frontend
cd frontend
npm run dev
```

Open `http://localhost:3000`.
