# FlytBase Asset Copilot — Frontend

Generative UI chat for field operators, built with **Next.js**, **OpenUI**, and **shadcn-style** components (black/white neutral theme).

## Prerequisites

- Node.js 20+
- Running [FastAPI backend](../backend/README.md) on port 8000
- `THESYS_API_KEY` for OpenUI Gateway ([getting started](https://www.openui.com/docs/getting-started))

## Setup

```bash
cd frontend
npm install
npm run generate:apiKey   # you run this — paste key into .env
cp .env.example .env      # if needed
npm run dev
```

App: http://localhost:3000

## Docs

- [Backend integration](docs/BACKEND-INTEGRATION.md)
- [Context / session notes](docs/CONTEXT.md)
- [Monorepo branching](../../docs/BRANCHING.md)

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Regenerate OpenUI spec + start Next dev server |
| `npm run generate` | Refresh `src/generated/spec.json` from component library |
| `npm run build` | Production build |
