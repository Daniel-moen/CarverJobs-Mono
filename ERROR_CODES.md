# CARVER Error Codes

Every API error response includes a `"code"` field with a CRV code. Global
exception handlers guarantee that no raw library or framework errors ever
reach the client.

Error codes appear in two places:

1. **API error responses** — the JSON body always includes `"detail"` and `"code"`.
2. **Health status** — `/status/services` service objects include a `"code"` field when `connected` is `false`.

## Format

```
CRV-XYYY
```

| Prefix | Category |
|--------|----------|
| `CRV-1xxx` | Infrastructure / general (database, validation, rate limiting) |
| `CRV-2xxx` | Authentication / session |
| `CRV-3xxx` | External AI services (OpenAI) |
| `CRV-4xxx` | Matching engine / data pipeline |
| `CRV-5xxx` | Admin / dashboard |
| `CRV-6xxx` | APIFY scraper / job ingestion |

---

## Code Reference

### Infrastructure / General — CRV-1xxx

| Code | Meaning | What to check |
|------|---------|---------------|
| `CRV-1001` | Database unreachable / connection failed | Check that the SQLite file path is correct and the API process has read/write permissions. In Docker, verify the volume mount. |
| `CRV-1002` | Database query failed at runtime | Inspect API logs for the underlying SQLAlchemy error. May indicate a schema migration is needed. |
| `CRV-1003` | Request validation failed (bad input) | The request body or query parameters did not pass validation. Check the endpoint docs for the expected format. |
| `CRV-1004` | Rate limit exceeded | You are sending too many requests. Wait a moment and try again. |
| `CRV-1005` | Resource not found | The requested item does not exist. Check the ID or path. |
| `CRV-1006` | Unexpected internal error | Something went wrong on the server. Inspect API logs for the root cause. |
| `CRV-1007` | Route not found / method not allowed | The URL path or HTTP method is not valid. Check the API docs. |
| `CRV-1008` | Feature temporarily disabled | A feature flag has disabled this endpoint. Check the admin dashboard. |

---

### Authentication / Session — CRV-2xxx

| Code | Meaning | What to check |
|------|---------|---------------|
| `CRV-2001` | Session secret key is the insecure default value | Set `SECRET_KEY` in your `.env` to a long, random string before deploying to production. Generate one with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CRV-2002` | Invalid credentials | The username or password was incorrect. |
| `CRV-2003` | Session expired | Your session has timed out. Please log in again. |
| `CRV-2004` | Authentication required | No session cookie was found. You must log in first. |
| `CRV-2005` | Admin access required | Your session does not have admin privileges. |
| `CRV-2006` | CSRF validation failed | The CSRF token is missing or does not match. Reload the page and try again. |
| `CRV-2007` | Google login unavailable / token invalid | Google OAuth is not configured or the token could not be verified. Check `GOOGLE_OAUTH_CLIENT_ID` in your `.env`. |
| `CRV-2008` | Google account not allowed | The Google email is unverified, or it does not match `GOOGLE_ALLOWED_EMAILS` / `GOOGLE_ALLOWED_DOMAIN` when those restrictions are configured. |

---

### External AI / OpenAI — CRV-3xxx

| Code | Meaning | What to check |
|------|---------|---------------|
| `CRV-3001` | OpenAI API key not configured | Set `OPENAI_API_KEY` in your `.env`. |
| `CRV-3002` | OpenAI request timed out | The OpenAI API did not respond within 25 seconds. Check your network connectivity. |
| `CRV-3003` | OpenAI returned an HTTP error | Check API logs for the HTTP status code. May indicate an invalid key or model name. Verify `OPENAI_MODEL` in `.env`. |
| `CRV-3004` | OpenAI quota exceeded | Your OpenAI API quota has been exhausted. Check billing or wait for the quota to reset. |
| `CRV-3005` | OpenAI network error | The API server could not reach `api.openai.com`. Check DNS and outbound firewall rules. |
| `CRV-3006` | OpenAI returned no usable response | OpenAI responded but with no candidates or an unparseable body. Check API logs for the raw response. |

---

### Matching Engine / Data Pipeline — CRV-4xxx

| Code | Meaning | What to check |
|------|---------|---------------|
| `CRV-4001` | Matching engine returned an error | Inspect API logs for the full error from the matching engine worker. |
| `CRV-4002` | Matching engine unavailable | The matching engine module is not present or failed to import. Check that the `api/Matching Engine/` directory is included in the deployment. |

---

### Admin / Dashboard — CRV-5xxx

| Code | Meaning | What to check |
|------|---------|---------------|
| `CRV-5001` | Admin stats DB query failed | Inspect API logs for the underlying SQLAlchemy error. The database may be locked or corrupted. |
| `CRV-5002` | Unknown feature flag key | A flag key was sent to `PATCH /admin/flags` that does not exist. Check the key name against `GET /admin/flags`. |

---

### APIFY Scraper / Job Ingestion — CRV-6xxx

| Code | Meaning | What to check |
|------|---------|---------------|
| `CRV-6001` | APIFY API key not configured | Set `APIFY_API_KEY` in your `.env`. |
| `CRV-6002` | No APIFY actor IDs configured | Set `APIFY_ACTOR_IDS` in your `.env` as a comma-separated list of APIFY actor IDs for the Facebook group scrapers. |
| `CRV-6003` | APIFY actor run timed out | The actor did not complete within the configured timeout. Check the actor run in the APIFY console. |
| `CRV-6004` | APIFY actor run failed | The actor finished with a FAILED or ABORTED status. Inspect the run logs in the APIFY console. |
| `CRV-6005` | APIFY network or HTTP error | The API server could not reach `api.apify.com`. Check DNS, outbound firewall rules, and that the API key is valid. |
| `CRV-6006` | Job sync database error | The scraped data could not be written to the database. Inspect API logs for the SQLAlchemy error. |

---

## Example API error response

```json
{
  "detail": "Invalid request data.",
  "code": "CRV-1003"
}
```

## Example health status entry

```json
{
  "connected": false,
  "detail": "Service unavailable",
  "code": "CRV-1001",
  "checked_at": "2026-03-02T10:00:00+00:00"
}
```
