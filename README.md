# CARVER v3
Project workspace with multiple components.
## Structure
- `website/`: Svelte + Tailwind frontend (modular starter)
- `api/`: FastAPI service (Python)
- `docker-compose.yml`: orchestrates per-service containers
## Getting started
### Website only
1. Open `website/`
2. Install dependencies: `npm install`
3. Start dev server: `npm run dev`
### API only
1. Open `api/`
2. Install dependencies: `npm install`
3. Start server: `npm start`
### Docker (both services)
1. From project root, run: `docker compose up --build`
2. Website: `http://localhost:8080`
3. API health: `http://localhost:3001/health`

## Google login setup
1. Copy `.env.example` to `.env` and set strong values for `SECRET_KEY` and `ADMIN_PASSWORD`.
2. In Google Cloud Console, create a Web OAuth client and set:
   - Authorized JavaScript origins: `http://localhost:8080`
3. Set at least one allowlist control:
   - `GOOGLE_ALLOWED_EMAILS` (comma-separated), or
   - `GOOGLE_ALLOWED_DOMAIN` (e.g. `company.com`)
4. Set `GOOGLE_OAUTH_CLIENT_ID` in `.env`.
5. Restart: `docker compose up -d --build`.
## Standards in this repo
- Separate Dockerfile per service
- Non-root runtime users
- Read-only containers where feasible via Compose
- Minimal external dependencies by default
