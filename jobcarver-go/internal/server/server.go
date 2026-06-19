// Package server wires the chi router: middleware (request-id, structured
// logging, startup gate, CSRF, security headers, CORS) and mounts every handler
// package's Register function. Ports the middleware + router wiring in
// api/app/main.py.
package server

import (
	"net/http"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"jobcarver/internal/config"
	"jobcarver/internal/logger"
	"jobcarver/internal/metrics"
	"jobcarver/internal/security"

	// Worker 2 handler packages
	"jobcarver/internal/handlers/auth"
	"jobcarver/internal/handlers/documents"
	"jobcarver/internal/handlers/feedback"
	"jobcarver/internal/handlers/health"
	"jobcarver/internal/handlers/jobhistory"
	"jobcarver/internal/handlers/jobs"
	"jobcarver/internal/handlers/jobsubmit"
	"jobcarver/internal/handlers/profile"
	"jobcarver/internal/handlers/users"

	// Worker 3 handler packages
	"jobcarver/internal/handlers/admin"
	"jobcarver/internal/handlers/admindash"
	"jobcarver/internal/handlers/agentstats"
	"jobcarver/internal/handlers/articles"
	"jobcarver/internal/handlers/crewmatch"
	"jobcarver/internal/handlers/interview"
	"jobcarver/internal/handlers/matching"
	"jobcarver/internal/handlers/recruiter"
	"jobcarver/internal/handlers/scraper"
	"jobcarver/internal/handlers/subscription"
	"jobcarver/internal/handlers/telnyx"
	"jobcarver/internal/handlers/whatsapp"
)

var log = logger.Get("carver.server")

// ready gates non-liveness routes until the database is initialised. main.go
// calls SetReady(true) once init completes.
var ready atomic.Bool

// SetReady flips the startup-ready gate.
func SetReady(v bool) { ready.Store(v) }

// New builds the fully-wired HTTP handler.
func New() http.Handler {
	r := chi.NewRouter()

	r.Use(requestIDMiddleware)
	r.Use(requestLogger)
	r.Use(corsMiddleware)
	r.Use(securityHeaders)
	r.Use(startupReadyGate)
	r.Use(csrfMiddleware)

	// Worker 2 packages
	health.Register(r)
	auth.Register(r)
	jobs.Register(r)
	jobsubmit.Register(r)
	users.Register(r)
	profile.Register(r)
	jobhistory.Register(r)
	documents.Register(r)
	feedback.Register(r)

	// Worker 3 packages
	matching.Register(r)
	interview.Register(r)
	crewmatch.Register(r)
	recruiter.Register(r)
	subscription.Register(r)
	scraper.Register(r)
	telnyx.Register(r)
	whatsapp.Register(r)
	admin.Register(r)
	admindash.Register(r)
	agentstats.Register(r)
	articles.Register(r)

	log.Info("router built", "env", config.S.AppEnv, "auto_login", config.S.AutoLoginAsAdmin)
	return r
}

// statusRecorder captures the response status code for logging/metrics.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusRecorder) Write(b []byte) (int, error) {
	if s.status == 0 {
		s.status = http.StatusOK
	}
	return s.ResponseWriter.Write(b)
}

// requestIDMiddleware assigns/propagates an X-Request-ID and binds it to the
// request context for logging (ports request_id_middleware).
func requestIDMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reqID := r.Header.Get("X-Request-ID")
		if reqID == "" {
			reqID = uuid.NewString()[:12]
		}
		w.Header().Set("X-Request-ID", reqID)
		ctx := logger.WithRequestID(r.Context(), reqID)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

var modulePrefixes = []string{
	"/auth", "/jobs", "/users", "/admin", "/matching",
	"/interview", "/documents", "/scraper", "/subscription", "/feedback",
	"/health", "/status", "/profile", "/job-history", "/p", "/recruiter",
}

func routeModule(path string) string {
	for _, prefix := range modulePrefixes {
		if strings.HasPrefix(path, prefix) {
			return strings.SplitN(strings.TrimPrefix(prefix, "/"), "/", 2)[0]
		}
	}
	return "other"
}

// requestLogger logs request start/end and feeds metrics (ports request_logger).
func requestLogger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		module := routeModule(r.URL.Path)
		rec := &statusRecorder{ResponseWriter: w}

		next.ServeHTTP(rec, r)

		if rec.status == 0 {
			rec.status = http.StatusOK
		}
		elapsed := int(time.Since(start).Milliseconds())
		level := slogInfo
		if rec.status >= 400 {
			level = slogWarn
		}
		level("request_end", "method", r.Method, "path", r.URL.Path,
			"status", rec.status, "elapsed_ms", elapsed, "module", module)

		metrics.Increment("requests_total")
		if !strings.HasPrefix(r.URL.Path, "/interview/") {
			metrics.RecordResponseTime(elapsed)
		}
		switch {
		case rec.status == 429:
			metrics.Increment("rate_limit_hits")
		case rec.status >= 400 && rec.status < 500:
			metrics.Increment("errors_4xx")
			metrics.RecordErrorByModule(module, "4xx")
		case rec.status >= 500:
			metrics.Increment("errors_5xx")
			metrics.RecordErrorByModule(module, "5xx")
		}
	})
}

// small wrappers so requestLogger can pick log level by status.
func slogInfo(msg string, args ...any) { log.Info(msg, args...) }
func slogWarn(msg string, args ...any) { log.Warn(msg, args...) }

// startupReadyGate returns 503 until the DB is ready, except for liveness paths
// and preflight (ports startup_ready_gate).
func startupReadyGate(next http.Handler) http.Handler {
	exempt := map[string]bool{"/health": true, "/": true}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodOptions || exempt[r.URL.Path] || ready.Load() {
			next.ServeHTTP(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = w.Write([]byte(`{"ok":false,"detail":"Service starting up, try again shortly."}`))
	})
}

// csrfMiddleware verifies the CSRF token on mutating requests and issues a fresh
// token on every response (ports csrf_middleware).
func csrfMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !security.CheckCSRF(r) {
			metrics.Increment("csrf_rejections")
			w.Header().Set(security.CSRFHeaderName, security.GenerateCSRFToken())
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`{"detail":"CSRF validation failed","code":"CRV-2006"}`))
			return
		}
		w.Header().Set(security.CSRFHeaderName, security.GenerateCSRFToken())
		next.ServeHTTP(w, r)
	})
}

// securityHeaders sets static security response headers (ports security_headers).
func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("X-Content-Type-Options", "nosniff")
		h.Set("X-Frame-Options", "DENY")
		h.Set("Referrer-Policy", "strict-origin-when-cross-origin")
		h.Set("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
		h.Set("Cache-Control", "no-store")
		h.Set("Content-Security-Policy",
			"default-src 'self'; script-src 'self' https://accounts.google.com; frame-src 'none'; object-src 'none'")
		if config.S.AppEnv == "production" && r.Header.Get("X-Forwarded-Proto") == "https" {
			h.Set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
		}
		next.ServeHTTP(w, r)
	})
}

// corsMiddleware mirrors the FastAPI CORSMiddleware config (allow credentials,
// expose X-CSRF-Token, echo allowed origins).
func corsMiddleware(next http.Handler) http.Handler {
	allowAll := len(config.S.CORSOrigins) == 1 && config.S.CORSOrigins[0] == "*"
	allowed := map[string]bool{}
	for _, o := range config.S.CORSOrigins {
		allowed[o] = true
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" && (allowAll || allowed[origin]) {
			h := w.Header()
			h.Set("Access-Control-Allow-Origin", origin)
			h.Set("Vary", "Origin")
			h.Set("Access-Control-Allow-Credentials", "true")
			h.Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
			reqHeaders := r.Header.Get("Access-Control-Request-Headers")
			if reqHeaders == "" {
				reqHeaders = "*"
			}
			h.Set("Access-Control-Allow-Headers", reqHeaders)
			h.Set("Access-Control-Expose-Headers", security.CSRFHeaderName)
			h.Set("Access-Control-Max-Age", strconv.Itoa(600))
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}
