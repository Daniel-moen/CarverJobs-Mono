# jobcarver-go

Go port of the jobcarver API (originally Python/FastAPI in `../api/app/`). Same
SQLite schema, same routes, same error-code contract — no Python, no Playwright.

## Run

```bash
cd jobcarver-go
go run ./cmd/server          # serves on :3000 (override with PORT)
```

The server creates `data/carver.db` (WAL mode) on first run, auto-migrates the
schema, and — outside production — seeds a `test@carver.local` / `test1234` crew
account.

## Build

```bash
go build ./...               # full build (all handler packages)
go build ./cmd/server        # just the binary
```

## Docker

```bash
docker build -t jobcarver-go .
docker run -p 3000:3000 -v $PWD/data:/app/data jobcarver-go
```

Multi-stage build → small Alpine runtime, `CGO_ENABLED=0` (pure-Go SQLite via
`github.com/glebarez/sqlite`). Mount a volume at `/app/data` to persist the DB.

## Configuration

Settings load from `jobcarver-go/.env` (gitignored) first, then environment
variables — same keys and defaults as `api/app/settings.py`. Key ones:

| Var | Default | Purpose |
|-----|---------|---------|
| `PORT` | `3000` | HTTP listen port |
| `APP_ENV` | `development` | `production` enables JSON logs, secure cookies, secret validation |
| `SECRET_KEY` | `change-me-in-production` | HMAC key for sessions + CSRF |
| `SESSION_COOKIE_NAME` | `carver_session` | session cookie name |
| `SESSION_TTL_SECONDS` | `3600` | session/CSRF token lifetime |
| `AUTO_LOGIN_AS_ADMIN` | `false` | dev-only: every request is admin |
| `CARVER_SQLITE_PATH` | _(unset)_ | absolute DB path override (else `data/carver.db`) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `change-this-password` | admin login |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, … | — | AI features (disabled when key empty) |
| `CORS_ORIGINS` | localhost + jobcarver.co | comma-separated allowed origins |
| `FREE_SIGNUP_TOKENS` / `FREE_MONTHLY_TOKENS` / `RECRUITER_UNLOCK_COST_TOKENS` | `2` / `25` / `5` | token economy |
| `YOCO_*`, `APIFY_API_KEY`, `WHATSAPP_*`, `META_VERIFY_TOKEN`, `TELNYX_API_KEY` | — | integrations |

See `internal/config/config.go` for the complete list.

## Architecture

```
cmd/server/main.go          entrypoint: load config → db init → background loops → serve
internal/
  config/    settings loader (.env + env vars, settings.py defaults)
  logger/    log/slog setup (JSON in prod, text in dev) + request-id context
  models/    GORM structs — exact column/table names from models.py
  db/        SQLite open (WAL), AutoMigrate, default-user seed
  security/  bcrypt + HMAC session tokens + CSRF + chi session middleware
  httpx/     JSON/error helpers + full CRV error-code registry
  metrics/   in-memory counters + rolling history (metrics.py)
  credits/   token-economy account logic (services/credits.py)
  flags/     in-memory feature kill-switches (flags.py)
  server/    chi router: middleware stack + mounts every handler's Register()
  handlers/  one package per route group (auth, jobs, admin, whatsapp, …)
  ai/ matching/ scrapers/ worker/   AI + matching + scraping + background loops
```

### Middleware stack (outer → inner)
request-id → request logger (metrics) → CORS → security headers → startup-ready
gate → CSRF. Then each `handlers/<name>.Register(r)` mounts its routes.

### Foundation contract
Handler packages depend on the `internal/{config,models,db,security,httpx,metrics,credits,flags}`
packages. Each handler package exposes `func Register(r chi.Router)`.
