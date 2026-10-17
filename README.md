# FlytBase Asset Intelligence Copilot

Monorepo for the FlytBase Asset Intelligence Copilot challenge.

| Area | Folder | Branch |
|------|--------|--------|
| API, ML, ingestion | [`backend/`](backend/README.md) | `backend-dev` |
| Web UI | [`frontend/`](frontend/README.md) | `frontend-dev` |
| Integration | entire repo | `main` |

## Quick links

- [Backend setup & architecture](backend/README.md)
- [Frontend setup](frontend/README.md)
- [Branch workflow (avoid conflicts)](docs/BRANCHING.md)

## Infrastructure

```bash
docker compose up -d
```

Postgres, Neo4j, and Redis are defined in `docker-compose.yml` for the backend stack.
