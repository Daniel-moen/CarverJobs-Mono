# Website (Svelte + Tailwind)
Modern, minimal, and modular frontend starter for CARVER v3.
## Goals
- Clean visual baseline (modern, understated UI)
- Easy to extend with new sections/components
- Responsive across phone/tablet/desktop
- Minimal external dependencies
## Stack
- Svelte 5
- Vite
- Tailwind CSS (via `@tailwindcss/vite`)
## Commands
- `npm run dev` — local development
- `npm run build` — production build
- `npm run preview` — preview production build
- Docker build: `docker build -t carver-v3-website .`
- Docker run: `docker run --rm -p 8080:8080 carver-v3-website`
## Auth/session integration
- UI now enforces login before dashboard access
- API session cookie is HTTP-only and sent using `credentials: include`
- Set `VITE_API_BASE_URL` if API is not at `http://localhost:3001`
- Google sign-in button appears automatically when API `/auth/providers` returns Google as enabled
## Folder layout
- `src/components/layout/` — persistent shell components
- `src/components/sections/` — page sections/feature blocks
- `src/config/` — site-level configuration/content objects
- `src/App.svelte` — high-level page composition
- `src/app.css` — global styles + Tailwind import
## Extension guidelines
- Add new UI blocks to `src/components/sections/`
- Keep shared data/config in `src/config/`
- Keep `App.svelte` thin: compose, don’t overload logic
- Prefer Svelte and Tailwind primitives before adding dependencies
## Security notes
- Production container runs as non-root user
- Nginx serves static build with basic security headers
- Container listens on port `8080` (non-privileged)
