// Package httpx provides JSON response helpers and the CRV error-code registry.
package httpx

// Carver error code registry — ports api/app/error_codes.py.
// Format: CRV-XYYY (1xxx infra, 2xxx auth, 3xxx AI, 4xxx matching, 5xxx admin,
// 6xxx scraper). Every API error response carries a "code" field.
const (
	// Infrastructure / General
	CRV1001 = "CRV-1001" // Database unreachable / connection failed
	CRV1002 = "CRV-1002" // Database query failed at runtime
	CRV1003 = "CRV-1003" // Request validation failed (bad input)
	CRV1004 = "CRV-1004" // Rate limit exceeded
	CRV1005 = "CRV-1005" // Resource not found
	CRV1006 = "CRV-1006" // Unexpected internal error (catch-all)
	CRV1007 = "CRV-1007" // Method not allowed / route not found
	CRV1008 = "CRV-1008" // Feature temporarily disabled

	// Authentication / Session
	CRV2001 = "CRV-2001" // Session secret key is the insecure default value
	CRV2002 = "CRV-2002" // Invalid credentials
	CRV2003 = "CRV-2003" // Session expired
	CRV2004 = "CRV-2004" // Authentication required (no session)
	CRV2005 = "CRV-2005" // Admin access required
	CRV2006 = "CRV-2006" // CSRF validation failed
	CRV2007 = "CRV-2007" // Google login not enabled / token invalid
	CRV2008 = "CRV-2008" // Google account not in allowlist
	CRV2009 = "CRV-2009" // Email already registered (signup)

	// External AI / OpenAI
	CRV3001 = "CRV-3001" // OpenAI API key is missing or not configured
	CRV3002 = "CRV-3002" // OpenAI request timed out
	CRV3003 = "CRV-3003" // OpenAI returned an HTTP error response
	CRV3004 = "CRV-3004" // OpenAI quota exceeded (HTTP 429)
	CRV3005 = "CRV-3005" // OpenAI unreachable (network / DNS error)
	CRV3006 = "CRV-3006" // OpenAI returned an empty or unparseable response

	// Matching Engine / Data Pipeline
	CRV4001 = "CRV-4001" // Matching engine returned an error
	CRV4002 = "CRV-4002" // Matching engine is not available in this deployment

	// Admin / Dashboard
	CRV5001 = "CRV-5001" // Admin stats query failed (database error)
	CRV5002 = "CRV-5002" // Unknown feature flag key supplied to PATCH /admin/flags
	CRV5003 = "CRV-5003" // AI error analysis failed (OpenAI or config issue)
	CRV5004 = "CRV-5004" // AI job review failed

	// Agent Monitoring
	CRV5005 = "CRV-5005" // Agent stats endpoint not configured (missing token)
	CRV5006 = "CRV-5006" // Agent stats query failed (database error)
	CRV5007 = "CRV-5007" // Agent SQL query rejected (forbidden statement)
	CRV5008 = "CRV-5008" // Agent SQL query failed (execution error)

	// APIFY Scraper / Job Ingestion
	CRV6001 = "CRV-6001" // APIFY API key is missing or not configured
	CRV6002 = "CRV-6002" // No APIFY actor IDs are configured
	CRV6003 = "CRV-6003" // APIFY actor run timed out
	CRV6004 = "CRV-6004" // APIFY actor run ended with a non-SUCCEEDED status
	CRV6005 = "CRV-6005" // APIFY network or HTTP error
	CRV6006 = "CRV-6006" // Job sync failed (database write error)
)

// Descriptions maps each CRV code to a short human-readable description.
var Descriptions = map[string]string{
	CRV1001: "Database unreachable",
	CRV1002: "Database query failed",
	CRV1003: "Invalid request data",
	CRV1004: "Rate limit exceeded",
	CRV1005: "Resource not found",
	CRV1006: "Internal server error",
	CRV1007: "Route not found",
	CRV1008: "Feature temporarily disabled",
	CRV2001: "Insecure default secret key in use",
	CRV2002: "Invalid credentials",
	CRV2003: "Session expired",
	CRV2004: "Authentication required",
	CRV2005: "Admin access required",
	CRV2006: "CSRF validation failed",
	CRV2007: "Google login unavailable",
	CRV2008: "Google account not allowed",
	CRV2009: "Email already registered",
	CRV3001: "OpenAI API key not configured",
	CRV3002: "OpenAI request timed out",
	CRV3003: "OpenAI returned an error",
	CRV3004: "OpenAI quota exceeded",
	CRV3005: "OpenAI network error",
	CRV3006: "OpenAI returned no usable response",
	CRV4001: "Matching engine error",
	CRV4002: "Matching engine unavailable",
	CRV5001: "Admin stats query failed",
	CRV5002: "Unknown feature flag key",
	CRV5003: "AI error analysis failed",
	CRV5004: "AI job review failed",
	CRV5005: "Agent stats endpoint not configured",
	CRV5006: "Agent stats query failed",
	CRV5007: "Agent SQL query rejected",
	CRV5008: "Agent SQL query failed",
	CRV6001: "APIFY API key not configured",
	CRV6002: "No APIFY actor IDs configured",
	CRV6003: "APIFY actor run timed out",
	CRV6004: "APIFY actor run failed",
	CRV6005: "APIFY network or HTTP error",
	CRV6006: "Job sync database error",
}

// StatusCodeToCRV maps an HTTP status code to a fallback CRV code, used when an
// error has no explicit code. Ports STATUS_CODE_TO_CRV.
var StatusCodeToCRV = map[int]string{
	400: CRV1003,
	401: CRV2004,
	403: CRV2005,
	404: CRV1005,
	405: CRV1007,
	409: CRV1005,
	413: CRV1003,
	422: CRV1003,
	429: CRV1004,
	500: CRV1006,
	502: CRV1006,
	503: CRV1008,
	504: CRV1006,
}
