# QR Wapsi

AI teammate that clears the RBI re-KYC backlog for paused small merchants — triage, collect, schedule, verify, reactivate.
Paytm Build for India AI Hackathon (Delhi), Track 3 · Team Hawks (Mayank Bhatt, Bhumika Bhatt, Tanuja Kanswal).

> Prototype · synthetic data · integrations simulated. See [CLAUDE.md](CLAUDE.md) for the full spec.

## Requirements
- Python 3.11+
- Node 20+ and npm
- Git Bash / WSL / macOS / Linux shell for `run.sh`

## Setup and run
```bash
cp .env.example .env     # optional; run.sh does this if missing. Add GEMINI_API_KEY / SARVAM_API_KEY for live mode.
./run.sh
```
`run.sh` creates `backend/venv`, installs backend and frontend dependencies, then starts:
- Frontend (Vite): http://localhost:5173
- Backend (FastAPI): http://localhost:8000 — health check at `/api/health`

Vite proxies `/api` to the backend. Press Ctrl+C to stop both.

## Manual run
```bash
cd backend && python -m venv venv && . venv/bin/activate   # Windows Git Bash: venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000

cd frontend && npm install && npm run dev
```

## Configuration (`.env`)
| Variable | Meaning |
|---|---|
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL` | LLM access |
| `SARVAM_API_KEY` | Hindi text-to-speech |
| `DEMO_MODE` | `live`, `record` or `replay` (offline, served from `backend/demo_cache/`) |
| `TOOL_TRANSPORT` | `mcp` (default) or `direct` |

## Pages
`/` Dashboard · `/merchant/:id` Merchant journey · `/shop/:id` Shopkeeper phone simulator · `/field` Field app · `/review` Review queue · `/demo` Demo control

## Status
Skeleton only: config, DB models, health endpoint, empty routers, placeholder pages. Agent, rules engine and demo flow come next.
