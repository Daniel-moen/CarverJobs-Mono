"""
Carver error code registry.

Format: CRV-XYYY
  1xxx = Infrastructure (database, server, general)
  2xxx = Authentication / session
  3xxx = External AI services (OpenAI)
  4xxx = Matching engine / data pipeline
  5xxx = Admin / dashboard
  6xxx = APIFY scraper / job ingestion

Every API error response MUST include a "code" field with a CRV code.
Global exception handlers in main.py guarantee this — no raw library
errors should ever reach the client.

See ERROR_CODES.md at the project root for the full human-readable guide.
"""

# ── Infrastructure / General ────────────────────────────────────────────────
CRV_1001 = "CRV-1001"  # Database unreachable / connection failed
CRV_1002 = "CRV-1002"  # Database query failed at runtime
CRV_1003 = "CRV-1003"  # Request validation failed (bad input)
CRV_1004 = "CRV-1004"  # Rate limit exceeded
CRV_1005 = "CRV-1005"  # Resource not found
CRV_1006 = "CRV-1006"  # Unexpected internal error (catch-all)
CRV_1007 = "CRV-1007"  # Method not allowed / route not found
CRV_1008 = "CRV-1008"  # Feature temporarily disabled

# ── Authentication / Session ─────────────────────────────────────────────────
CRV_2001 = "CRV-2001"  # Session secret key is the insecure default value
CRV_2002 = "CRV-2002"  # Invalid credentials
CRV_2003 = "CRV-2003"  # Session expired
CRV_2004 = "CRV-2004"  # Authentication required (no session)
CRV_2005 = "CRV-2005"  # Admin access required
CRV_2006 = "CRV-2006"  # CSRF validation failed
CRV_2007 = "CRV-2007"  # Google login not enabled / token invalid
CRV_2008 = "CRV-2008"  # Google account not in allowlist
CRV_2009 = "CRV-2009"  # Email already registered (signup)

# ── External AI / OpenAI ─────────────────────────────────────────────────────
CRV_3001 = "CRV-3001"  # OpenAI API key is missing or not configured
CRV_3002 = "CRV-3002"  # OpenAI request timed out
CRV_3003 = "CRV-3003"  # OpenAI returned an HTTP error response
CRV_3004 = "CRV-3004"  # OpenAI quota exceeded (HTTP 429)
CRV_3005 = "CRV-3005"  # OpenAI unreachable (network / DNS error)
CRV_3006 = "CRV-3006"  # OpenAI returned an empty or unparseable response

# ── Matching Engine / Data Pipeline ─────────────────────────────────────────
CRV_4001 = "CRV-4001"  # Matching engine returned an error
CRV_4002 = "CRV-4002"  # Matching engine is not available in this deployment

# ── Admin / Dashboard ────────────────────────────────────────────────────────
CRV_5001 = "CRV-5001"  # Admin stats query failed (database error)
CRV_5002 = "CRV-5002"  # Unknown feature flag key supplied to PATCH /admin/flags
CRV_5003 = "CRV-5003"  # AI error analysis failed (OpenAI or config issue)
CRV_5004 = "CRV-5004"  # AI job review failed

# ── APIFY Scraper / Job Ingestion ────────────────────────────────────────────
CRV_6001 = "CRV-6001"  # APIFY API key is missing or not configured
CRV_6002 = "CRV-6002"  # No APIFY actor IDs are configured
CRV_6003 = "CRV-6003"  # APIFY actor run timed out
CRV_6004 = "CRV-6004"  # APIFY actor run ended with a non-SUCCEEDED status
CRV_6005 = "CRV-6005"  # APIFY network or HTTP error
CRV_6006 = "CRV-6006"  # Job sync failed (database write error)

# ── Convenience lookup ───────────────────────────────────────────────────────
DESCRIPTIONS: dict[str, str] = {
    CRV_1001: "Database unreachable",
    CRV_1002: "Database query failed",
    CRV_1003: "Invalid request data",
    CRV_1004: "Rate limit exceeded",
    CRV_1005: "Resource not found",
    CRV_1006: "Internal server error",
    CRV_1007: "Route not found",
    CRV_1008: "Feature temporarily disabled",
    CRV_2001: "Insecure default secret key in use",
    CRV_2002: "Invalid credentials",
    CRV_2003: "Session expired",
    CRV_2004: "Authentication required",
    CRV_2005: "Admin access required",
    CRV_2006: "CSRF validation failed",
    CRV_2007: "Google login unavailable",
    CRV_2008: "Google account not allowed",
    CRV_2009: "Email already registered",
    CRV_3001: "OpenAI API key not configured",
    CRV_3002: "OpenAI request timed out",
    CRV_3003: "OpenAI returned an error",
    CRV_3004: "OpenAI quota exceeded",
    CRV_3005: "OpenAI network error",
    CRV_3006: "OpenAI returned no usable response",
    CRV_4001: "Matching engine error",
    CRV_4002: "Matching engine unavailable",
    CRV_5001: "Admin stats query failed",
    CRV_5002: "Unknown feature flag key",
    CRV_5003: "AI error analysis failed",
    CRV_5004: "AI job review failed",
    CRV_6001: "APIFY API key not configured",
    CRV_6002: "No APIFY actor IDs configured",
    CRV_6003: "APIFY actor run timed out",
    CRV_6004: "APIFY actor run failed",
    CRV_6005: "APIFY network or HTTP error",
    CRV_6006: "Job sync database error",
}


# ── Status-code fallback mapping ────────────────────────────────────────────
# Used by the global exception handler when an HTTPException has no explicit
# CRV code.  The handler looks up exc.status_code in this dict.
STATUS_CODE_TO_CRV: dict[int, str] = {
    400: CRV_1003,
    401: CRV_2004,
    403: CRV_2005,
    404: CRV_1005,
    405: CRV_1007,
    409: CRV_1005,
    413: CRV_1003,
    422: CRV_1003,
    429: CRV_1004,
    500: CRV_1006,
    502: CRV_1006,
    503: CRV_1008,
    504: CRV_1006,
}
