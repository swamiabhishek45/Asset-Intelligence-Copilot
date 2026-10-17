# Branch workflow (avoid merge conflicts)

This repo is a **monorepo**: backend and frontend live in separate top-level folders. Use three long-lived branches.

| Branch | Purpose | Edit only |
|--------|---------|-----------|
| `main` | Integration (default) | Merge via PR; no direct feature work |
| `backend` | Backend features | `backend/**` |
| `frontend` | Frontend features | `frontend/**` |

## Daily workflow

### Backend developer

```bash
git checkout backend
git pull origin backend
# … change only under backend/ …
git add backend/
git commit -m "feat(backend): …"
git push origin backend
# Open PR: backend → main
```

### Frontend developer

```bash
git checkout frontend
git pull origin frontend
# … change only under frontend/ …
git add frontend/
git commit -m "feat(frontend): …"
git push origin frontend
# Open PR: frontend → main
```

### After `main` moves (sync your branch)

```bash
git checkout frontend   # or backend
git fetch origin
git merge origin/main
git push origin HEAD
```

## Shared files (coordinate)

Avoid editing these on topic branches unless you agree first:

- `docker-compose.yml`
- `.gitignore`
- Root `README.md` (details live in `backend/README.md` and `frontend/README.md`)

## Dataset

The local clone of `flytbase-ahc-swe-asset-intelligence-dataset/` is gitignored. Do not commit sample data.
