# Shadow traffic — validate the Go port against real requests

A way to **duplicate production traffic, replay it through the Go server, and log
every divergence** before `jobcarver-go` replaces the Python API. It has two
halves:

1. **Capture** (Python side) — an off-by-default middleware records real requests
   to a JSONL corpus: `api/app/shadow_capture.py`.
2. **Replay + diff** (Go side) — a tool re-sends that corpus at a Go server and
   structurally diffs each response against what Python returned, classifying
   every issue: `jobcarver-go/cmd/shadowreplay`.

Capture and replay are **decoupled on purpose**: capture a corpus once, then
replay it as many times as you like as you harden the Go port (a free regression
suite). The replay never touches production.

```
  prod request ──▶ Python API ──▶ real response to user
                       │
                       └─(capture middleware, async)─▶ shadow_capture.jsonl
                                                            │
                                  offline, off-prod ────────┘
                                                            ▼
                              shadowreplay ──▶ Go server ──▶ diff vs Python ──▶ report
```

---

## 1. Capture a corpus (production / staging)

Enable on the Python API (e.g. Railway env vars). **Off by default — zero
overhead until switched on.**

```bash
SHADOW_CAPTURE_ENABLED=true
SHADOW_CAPTURE_FILE=data/shadow_capture.jsonl   # lives on the API's data volume
SHADOW_CAPTURE_SAMPLE_RATE=1.0                  # lower for high traffic, e.g. 0.2
SHADOW_CAPTURE_MAX_BODY_BYTES=65536
SHADOW_CAPTURE_RESPONSE_BODY=false              # status+content-type is enough for structural diff
SHADOW_CAPTURE_EXCLUDE_PREFIXES=/health,/metrics,/admin/dashboard/static
```

Each captured line records: method, path, query, a safe subset of headers, the
(redacted) request body, the **principal Python authenticated** (`sub`/`role`/
`user_id`), and Python's response status + content-type.

Let it run long enough to cover the routes you care about, then pull the file:

```bash
# Railway example
railway run cat data/shadow_capture.jsonl > shadow_capture.jsonl
```

> **Security:** the corpus contains request bodies. Sensitive JSON fields
> (`password`, `token`, `otp`, …) are redacted and `Cookie`/`Authorization`
> headers are dropped, but treat the file as sensitive and delete it when done.

## 2. Replay against the Go server

Point a Go server at a **snapshot of the production DB** and give it the **same
`SECRET_KEY`** as production (so the principals in the corpus exist and the minted
sessions validate):

```bash
cd jobcarver-go
cp /path/to/prod-snapshot.db data/carver.db
SECRET_KEY=<prod secret> APP_ENV=development go run ./cmd/server   # :3000
```

Then replay the corpus and diff:

```bash
go run ./cmd/shadowreplay \
  -corpus ../shadow_capture.jsonl \
  -target http://localhost:3000 \
  -report data/shadow_report.jsonl
```

The tool reads `SECRET_KEY` / `SESSION_COOKIE_NAME` / `SESSION_TTL_SECONDS` from
the Go config (`.env` + env), mints a **native Go session + fresh CSRF token**
for each captured principal (Python's `itsdangerous` cookies aren't Go-compatible,
so replaying raw cookies would falsely fail every authed request), and sends
`X-Shadow-Replay: 1` on every request.

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `-corpus` | `data/shadow_capture.jsonl` | capture file to replay |
| `-target` | `http://localhost:3000` | Go server base URL |
| `-report` | `data/shadow_report.jsonl` | per-request JSONL output |
| `-concurrency` | `4` | parallel replay workers |
| `-timeout` | `30s` | per-request timeout |
| `-limit` | `0` | cap records replayed (0 = all) |
| `-mint-auth` | `true` | mint Go session+CSRF for the captured principal |
| `-fail-on` | `critical` | exit non-zero at/above `none\|warn\|critical` (CI gate) |

## 3. Read the report

Each request is bucketed (first match wins, highest severity first):

| Bucket | Severity | Meaning — action |
|--------|----------|------------------|
| `transport_error` | critical | Go unreachable / timed out. |
| `go_5xx` | critical | Go threw 5xx where Python didn't — a crash/bug to fix. |
| `routing_gap` | critical | Go 404/405 on a route Python handled — route not implemented/registered. |
| `auth_divergence` | warn | 401/403 on exactly one side — session/CSRF/role gap (or a redacted login body). |
| `status_class_mismatch` | warn | e.g. Python 200 vs Go 400 — behavioural difference. |
| `content_type_mismatch` | warn | 2xx on both but json-vs-html differs. |
| `bad_json` | warn | Go says JSON but the body won't parse. |
| `not_implemented` | info | Go returned 501 — a known, intentional stub (see `TODO.md`). |
| `ok` | ok | same status class (and valid JSON where claimed). |

The console prints per-bucket counts + sample endpoints; `-report` holds the full
per-request detail for triage. Work the **critical** buckets first.

### Expected noise while the port is incomplete

Per `TODO.md`, AI / Yoco / scrapers / Google-login are still stubbed, so expect
`not_implemented` (501) and some `status_class_mismatch` on those routes — those
aren't regressions. `routing_gap` and `go_5xx` are the real signal.

## CI / pre-deploy gate

```bash
go run ./cmd/shadowreplay -corpus shadow_capture.jsonl -target http://localhost:3000 -fail-on critical
# exit 1 if any transport_error / go_5xx / routing_gap remains
```
