// Package health ports api/app/routes/health.py — public liveness probes plus a
// session-gated services-status endpoint.
package health

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/httpx"
	"jobcarver/internal/security"
)

// Register mounts the health routes onto r.
func Register(r chi.Router) {
	r.Get("/", root)
	r.Get("/health", health)
	r.With(security.RequireSession).Get("/status/services", servicesStatus)
}

func root(w http.ResponseWriter, _ *http.Request) {
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "service": "api"})
}

func health(w http.ResponseWriter, _ *http.Request) {
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "service": "api"})
}

func servicesStatus(w http.ResponseWriter, _ *http.Request) {
	// TODO(go-port): wire to Worker 3's health checker once available. The Python
	// version returns cached background-probe results; until that exists we return
	// the documented empty/unknown fallback.
	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok":               true,
		"last_run":         nil,
		"next_run_seconds": 300,
		"services":         []any{},
	})
}
