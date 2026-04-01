# API Service
Modular FastAPI service for CARVER v3 using a local SQLite3 database.
## Endpoints
- `GET /health`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/session`
- `GET /jobs`
- `POST /jobs`
- `GET /jobs/{job_id}`
- `PATCH /jobs/{job_id}`
- `DELETE /jobs/{job_id}`
## Architecture
- `app/main.py`: FastAPI entrypoint only
- `app/routes/`: independent route modules
- `app/models.py`: SQLAlchemy models
- `app/schemas.py`: request/response schemas
- `app/crud.py`: database operations
- SQLite file: `api/data/carver.db`
## Security baseline
- HTTP-only signed session cookies
- All `/jobs` routes require authenticated admin session
- CORS allowlist + TrustedHost middleware
- Secure headers middleware (frame deny, no-sniff, no-store, etc.)
## Important environment variables
- `SECRET_KEY` (set a strong value in production)
- `ADMIN_USERNAME` / `ADMIN_PASSWORD`
- `AUTO_LOGIN_AS_ADMIN=false` (recommended; should stay `false` outside temporary local testing)
- `SESSION_SECURE_COOKIE=true` in HTTPS production
- `CORS_ORIGINS` and `ALLOWED_HOSTS`
- `GOOGLE_OAUTH_CLIENT_ID` (Google Web OAuth client ID)
- `GOOGLE_REQUIRE_VERIFIED_EMAIL=true` (recommended)
- `GOOGLE_ALLOWED_EMAILS` (optional comma-separated allowlist)
- `GOOGLE_ALLOWED_DOMAIN` (optional domain allowlist, e.g. `company.com`)
## Run locally
- `python -m venv .venv && source .venv/bin/activate`
- `pip install -r requirements.txt`
- `uvicorn app.main:app --reload --port 3000`
## Docker
- Build: `docker build -t carver-v3-api .`
- Run: `docker run --rm -p 3000:3000 carver-v3-api`
