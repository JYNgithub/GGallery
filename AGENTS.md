# AGENTS.md

## Project Overview
Self-hosted media gallery (photos/videos) with decoupled architecture:
- **Backend**: FastAPI (Python) - API, metadata, streaming
- **Frontend**: Reflex (Python) - web UI
- **Database**: PostgreSQL (external)
- **Object Storage**: Garage S3-compatible (external)
- **Networking**: SSH tunnel for remote DB/Garage access

## Do Not Read
- Never open/read: `.venv/`, `admin/`, `data/`, `etc/`, `.env`, `NOTES.md`, `TODO.md`.

## Critical Environment Notes
- `.env` contains ALL credentials (API keys, DB, Garage, SSH). NEVER commit or expose. It is git-ignored (see `.agentignore` above).
- Both `backend/main.py` and `frontend/frontend/frontend.py` call `load_dotenv("../.env")` — relative to CWD, so run them from their own directory (`backend/` or `frontend/`).
- Backend `main.py` opens DB/Garage connections and starts the SSH tunnel **at import time** (module-level side effects). The app won't start if PostgreSQL/Garage are unreachable.

## Running the Project
```bash
# Docker (production-like)
docker compose up --build

# Local dev (backend only) - requires external Postgres + Garage
cd backend && uvicorn main:app --reload

# Local dev (frontend only)
cd frontend && reflex run --backend-port 8001
```

## Architecture Gotchas
- **Two separate `requirements.txt` files** — root (used by backend Dockerfile + local backend) vs `frontend/requirements.txt`. They pin **different Reflex versions** (root has 0.9.2, frontend has 0.8.27). Install per-directory.
- **Media types** defined in `backend/configuration.py` and duplicated in `frontend/configuration.py` — keep in sync.
- **Frontend is a single file**: `frontend/frontend/frontend.py` (~1000 lines). The `State(rx.State)` class is the Reflex backend (state + logic); page functions (`login`, `gallery`) are the UI; `app = rx.App()` at the bottom registers pages via `app.add_page(...)`.
- **Auth layers**: API key via `header_key` (frontend↔backend requests) or `query_key` (browser `src` URLs, Reflex limitation), PIN (`PIN_NUMBER` env) for frontend login, signed URLs (15-min expiry, HMAC-SHA256) for video streaming via `/stream/{filename}?expires=&signature=`.
- **`etc/init_db.sql` is stale**: it shows only an `uploaded_at` column. The live schema used by `main.py` inserts `key, original_filename, file_type, size, device, uploaded_date, created_date, tag, is_img` into `${DB_SCHEMA}.${DB_TABLE}`. Trust `main.py`, not the DDL file.
- **Docker networking**: frontend calls the backend via `BACKEND_INTERNAL_URL` (container name) for API calls, but browser-facing URLs use `BACKEND_URL` (`BACKEND_HOST`/`BACKEND_PORT`). DB/Garage accessed via `host.docker.internal`; use `localhost` for local dev.

## Development Conventions
- **Backend naming**: Use technical terms (`write`, `read`, `list`, `filter`).
- **Frontend naming**: Match feature names (`load_gallery`, `delete_selected_files`).
- **Config files**: `configuration.py` = constants; `.env` = credentials only.

## Common Pitfalls
- **Port conflicts**: FastAPI uses 8000; Reflex backend needs 8001 in dev (via `--backend-port 8001`). In prod (`--env prod`) Reflex shares port 3000 — `frontend/rxconfig.py` `api_url` must be `http://localhost:3000` for docker / `http://localhost:8001` for dev.
- **SSH tunnel**: toggled via `USE_SSH` in `.env`; when enabled, DB/Garage connect to `127.0.0.1` through local tunnel ports.
- **Missing infra**: PostgreSQL and Garage must be running before the backend starts (import-time connections).

## Verification
- No test suite exists. Verify manually:
```bash
curl http://localhost:8000/                 # backend health
curl http://localhost:8000/db-health        # DB health
curl http://localhost:8000/garage-health    # Garage health
```
- `admin/` has helper scripts (`listall_bucket.py`, `clear_bucket.py`) for Garage bucket inspection.

## Security Reminders
- Never expose `API_KEY`, `SECRET_SIGNING_KEY`, or DB credentials.
- Use signed URLs for streaming (15-min expiry).
- Browser cannot use header keys (Reflex limitation), hence `query_key` in image/stream URLs.