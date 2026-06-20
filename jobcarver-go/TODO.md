# jobcarver-go — Remaining Work

What's left to turn the Go port into a true drop-in replacement for the Python API
(`api/app`). The HTTP surface (87/89 routes), all 20 models, auth/sessions/CSRF, the token
economy, matching persistence, and CRUD are **done and verified**. What remains is wiring the
external integrations that are currently stubbed.

> **Out of scope for now (intentionally skipped):** Telnyx SMS, WhatsApp bot.
> Those handlers exist and persist data but their outbound/verify paths stay stubbed for now.

> **Validate before cutover:** [`SHADOW.md`](SHADOW.md) describes how to capture real
> production traffic and replay it through the Go server (`cmd/shadowreplay`), logging
> every routing gap / 5xx / divergence. Use it to verify each item below as it lands.

Legend: 🔴 blocks production · 🟠 important · 🟡 nice-to-have

---

## 🔴 1. AI client — real OpenAI HTTP
**Files:** `internal/ai/ai.go` (lines 10, 77)
The entire AI product surface depends on this one package. Today `ai.Chat` returns a
deterministic placeholder (or a key-missing error). Implement a real `net/http` POST to the
OpenAI Chat Completions API using `config.S.OpenAIAPIKey` / `OpenAIModel` (and
`EmailAIModel` where the Python uses it).

Once this is real, the following light up automatically (they already call the `ai` package):
- `internal/matching/engine.go:10` — match scoring / reasons
- `internal/handlers/crewmatch/crewmatch.go:11` — match results + AI email drafting
- `internal/handlers/interview/interview.go` — AI interview + onboarding
- `internal/handlers/documents/documents.go:133` — async CV/document scan (`scanned_text`)
- `internal/handlers/admin/admin.go:281` — AI job-review batch (jobs/review)

**Done when:** a real API call returns model output; the above endpoints produce real results
end-to-end. Port reference: `api/app/services/ai_client.py`.

---

## 🔴 2. Payments — real Yoco checkout creation
**Files:** `internal/handlers/subscription/subscription.go` (lines 9, 135)
`POST /subscription/checkout` currently returns a **fake** redirect URL, so users can't
actually pay. The webhook side (HMAC verify + `credits.Grant` + first-purchase bonus) is
already real. Implement the real `POST` to `YOCO_CHECKOUTS_URL` with
`Authorization: Bearer <YocoSecretKey>` and return the real redirect URL + checkout id.

**Done when:** a checkout returns a live Yoco redirect and a completed payment credits tokens
via the existing webhook. Port reference: `api/app/routes/subscription.py` (`/checkout`).

---

## 🔴 3. Job ingestion — real scrapers
**Files:** `internal/scrapers/scrapers.go` (10, 53, 61), `internal/worker/worker.go` (12, 121),
`internal/handlers/scraper/scraper.go` (77, 141, 175, 187)
All scrapers return empty, so no jobs are ingested. Needed:
1. Implement real source scrapers (Apify Facebook groups + the web boards) — port
   `api/app/services/apify_scraper.py`, `dockwalk_scraper.py`, `workonayacht_scraper.py`,
   `crewfinders_scraper.py`, `vikingcrew_scraper.py`, `faststream_scraper.py`,
   `superyachttimes_scraper.py`, `scrape_do_scraper.py`. (Apify/Playwright-based ones may need
   an HTTP-API or headless approach in Go.)
2. Persist scraped jobs into `models.Job` with content-hash / fingerprint dedup
   (`worker.go:121`, `scraper.go:141`).
3. `scraper.go:175,187` — port the AI job-reviewer (`review_post`) + `job_sync` dedup and the
   vision review (`review_job_image`) for `POST /scraper/import` and `/import-image`
   (currently 501). Depends on #1 (ai).

**Done when:** the background worker ingests + dedups real jobs and `/scraper/import*` work.
Port references: `api/app/services/*_scraper.py`, `job_sync.py`, `ai_job_reviewer.py`,
`scheduler.py`, `job_retention.py`.

---

## 🟠 4. Google login
**File:** `internal/handlers/auth/auth.go` (294, 301) — `POST /auth/google` returns 501.
Implement real Google ID-token verification (equivalent of `google.oauth2.id_token`):
verify signature against Google certs, check `aud == GoogleOAuthClientID`, enforce
`GoogleRequireVerifiedEmail` + allowlist/domain, then create/find the user and issue a session.
Port reference: `api/app/routes/auth.py` (`login_google`).

---

## 🟠 5. jobsubmit AI import pipelines
**File:** `internal/handlers/jobsubmit/jobsubmit.go` (73, 79, 89) — `/jobs/submit/text` and
`/jobs/submit/image` return 501. Port `_run_import_pipeline` (text) and `review_job_images`
(vision). Depends on #1 (ai). The non-AI `/jobs/submit/form` path is already complete.

---

## 🟠 6. Admin analytics depth
**File:** `internal/handlers/admin/admin.go` (328, 338)
Pragmatic aggregation over `AnalyticsEvent` is in place. Port the full
`get_user_flows` + `get_page_transitions` from `api/app/analytics.py` for the richer
funnel/flow views.

---

## 🟡 7. Config fields to add
**Files:** `internal/config/config.go` (consumers flagged across handlers)
Add and parse these env vars (present in `settings.py`, not yet in the Go `Settings`):
- `APIFY_ACTOR_IDS`, `APIFY_START_URLS`, `APIFY_MAX_ITEMS`, `APIFY_SCRAPE_ON_STARTUP` (for #3)
- `SCRAPE_DO_TOKEN`, `SCRAPE_DO_URLS`, `SCRAPE_DO_RENDER` (for #3)
- per-web-scraper `*_ENABLED` flags (DOCKWALK/WORKONAYACHT/CREWFINDERS/VIKINGCREW/FASTSTREAM/SUPERYACHTTIMES)
- `MIXPANEL_*` (for #6 / article SSR analytics — `articles.go:7`)
- `WHATSAPP_PHONE_NUMBER_IDS` (plural list) — only if WhatsApp is picked back up later
- (`META_APP_SECRET`, `TELNYX_PUBLIC_KEY` — skip; WhatsApp/Telnyx are out of scope for now)

---

## 🟡 8. Misc parity
- **Rate limiting** — port slowapi per-route limits as chi middleware (signup/login etc.).
  Currently not enforced.
- **Admin dashboard static assets** — `internal/handlers/admindash/admindash.go:9` serves from
  `ADMIN_STATIC_DIR | ./static/admin` and 404s if absent; bundle/ship the built dashboard.
- **Health checker** — `internal/handlers/health/health.go:30`: `/status/services` returns a
  fallback; wire it to a real periodic service health checker (port `health_checker.py`).
- **credits DB retry** — `internal/credits/credits.go:37`: the Python retry-on-locked-DB loop
  was dropped (gorm + WAL handles most contention); re-add if lock errors surface under load.

---

## Priority order (suggested)
1. **AI client (#1)** — unlocks the most surface in one change.
2. **Yoco checkout (#2)** — restores the revenue path.
3. **Scrapers (#3)** — restores job ingestion (the content pipeline).
4. Google login (#4), jobsubmit pipelines (#5).
5. Analytics depth (#6), config (#7), misc parity (#8).
