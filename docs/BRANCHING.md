# Branch workflow (avoid merge conflicts)

This repo is a **monorepo**: backend and frontend live in separate top-level folders. Use **long-lived topic branches** so you rarely edit the same files.

| Branch | Owner | Edit only |
|--------|--------|-----------|
| `main` | Integration | Merge via PR; no direct feature work |
| `backend-dev` | Backend | `backend/**` |
| `frontend-dev` | Frontend | `frontend/**` |

## Daily workflow

### Backend developer

```bash
git checkout backend-dev
git pull origin backend-dev
# … change only under backend/ …
git add backend/
git commit -m "feat(backend): …"
git push origin backend-dev
# Open PR: backend-dev → main
```

### Frontend developer

```bash
git checkout frontend-dev
git pull origin frontend-dev
# … change only under frontend/ …
git add frontend/
git commit -m "feat(frontend): …"
git push origin frontend-dev
# Open PR: frontend-dev → main
```

### After `main` moves (sync your branch)

```bash
git checkout frontend-dev   # or backend-dev
git fetch origin
git merge origin/main
git push origin HEAD
```

## Shared files (coordinate)

These paths affect both sides. **Avoid editing them on topic branches** unless you agree first:

- `docker-compose.yml` — backend-owned today; add frontend services in a follow-up PR from whoever needs them
- `.gitignore` — add sections by area (`# Frontend`, `# Backend`)
- Root `README.md` — short overview only; details live in `backend/README.md` and `frontend/README.md`

## Dataset

The local clone of `flytbase-ahc-swe-asset-intelligence-dataset/` is gitignored. Do not commit sample data.
