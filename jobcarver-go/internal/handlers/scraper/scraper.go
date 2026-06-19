// Package scraper ports api/app/routes/scraper.py: the admin-only scraper
// management endpoints (status, trigger, trigger-web, import, import-image).
//
// The scrape work itself runs through internal/scrapers, which is STUBBED, so
// trigger/trigger-web kick off a no-op cycle and status reports the in-process
// state. The /import + /import-image endpoints depend on the AI job-reviewer and
// job-sync pipelines (api/app/services/ai_job_reviewer.py + job_sync.py) which
// are out of scope for this port, so they validate inputs then return a clear
// TODO error. All routes require an admin session and the scraper flags gate the
// trigger endpoints.
package scraper

import (
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/config"
	"jobcarver/internal/flags"
	"jobcarver/internal/httpx"
	"jobcarver/internal/metrics"
	"jobcarver/internal/scrapers"
	"jobcarver/internal/security"
)

// state mirrors scheduler.get_scraper_state (running flag + last run summary).
var (
	stateMu    sync.Mutex
	running    bool
	lastRunAt  *time.Time
	lastResult string
)

func getState() map[string]any {
	stateMu.Lock()
	defer stateMu.Unlock()
	var last any
	if lastRunAt != nil {
		last = lastRunAt.UTC().Format(time.RFC3339)
	}
	return map[string]any{
		"running":     running,
		"last_run_at": last,
		"last_result": lastResult,
	}
}

// Register mounts /scraper (admin session required).
func Register(r chi.Router) {
	r.Group(func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Use(adminOnly)
		r.Get("/scraper/status", status)
		r.Post("/scraper/trigger", trigger)
		r.Post("/scraper/trigger-web", triggerWeb)
		r.Post("/scraper/import", importJob)
		r.Post("/scraper/import-image", importJobImage)
	})
}

func adminOnly(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sess := security.SessionFromContext(r.Context())
		if sess == nil || sess.Role != "admin" {
			httpx.WriteError(w, http.StatusForbidden, "Admin access required", httpx.CRV2005)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func status(w http.ResponseWriter, r *http.Request) {
	// The Go config only carries APIFY_API_KEY (actor IDs / start URLs are not
	// modelled), so actor/url counts are reported as 0. TODO(go-port): add
	// APIFY_ACTOR_IDS / APIFY_START_URLS to config when real scraping is wired.
	webScrapers := []map[string]any{
		{"name": "Dockwalk", "enabled": false, "needs_proxy": true},
		{"name": "Yotspot", "enabled": false, "needs_proxy": true},
		{"name": "Faststream", "enabled": false, "needs_proxy": false},
		{"name": "CrewFinders", "enabled": false, "needs_proxy": false},
		{"name": "Viking Crew", "enabled": false, "needs_proxy": true},
	}
	resp := map[string]any{
		"ok":                   true,
		"configured":           config.S.APIFYAPIKey != "",
		"actor_count":          0,
		"url_count":            0,
		"web_scrapers":         webScrapers,
		"scrape_do_configured": false,
	}
	for k, v := range getState() {
		resp[k] = v
	}
	httpx.JSON(w, http.StatusOK, resp)
}

func trigger(w http.ResponseWriter, r *http.Request) {
	if !flags.IsEnabled("scraper") {
		metrics.Increment("feature_blocked")
		httpx.WriteError(w, http.StatusServiceUnavailable, "Scraper is temporarily disabled.", httpx.CRV1008)
		return
	}
	stateMu.Lock()
	isRunning := running
	stateMu.Unlock()
	if isRunning {
		httpx.WriteError(w, http.StatusConflict, "A scrape cycle is already running.", httpx.CRV1006)
		return
	}
	if config.S.APIFYAPIKey == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable, "APIFY API key is not configured.", httpx.CRV6001)
		return
	}
	go runScrapeOnce()
	metrics.Increment("scraper_triggers")
	httpx.JSON(w, http.StatusAccepted, map[string]any{"ok": true, "message": "Scrape cycle triggered."})
}

func triggerWeb(w http.ResponseWriter, r *http.Request) {
	if !flags.IsEnabled("scraper_web") {
		metrics.Increment("feature_blocked")
		httpx.WriteError(w, http.StatusServiceUnavailable, "Web scrapers are temporarily disabled.", httpx.CRV1008)
		return
	}
	stateMu.Lock()
	isRunning := running
	stateMu.Unlock()
	if isRunning {
		httpx.WriteError(w, http.StatusConflict, "A scrape cycle is already running.", httpx.CRV1006)
		return
	}
	go runScrapeOnce()
	metrics.Increment("scraper_triggers")
	httpx.JSON(w, http.StatusAccepted, map[string]any{"ok": true, "message": "Web scrape started."})
}

// runScrapeOnce runs the (stubbed) scrapers and records the result in state.
// TODO(go-port): persist scraped jobs once internal/scrapers is real.
func runScrapeOnce() {
	stateMu.Lock()
	running = true
	stateMu.Unlock()

	results := scrapers.RunAll(nil)
	total := 0
	for _, res := range results {
		total += len(res.Jobs)
	}

	now := time.Now().UTC()
	stateMu.Lock()
	running = false
	lastRunAt = &now
	lastResult = "stubbed — 0 jobs ingested"
	_ = total
	stateMu.Unlock()
}

func importJob(w http.ResponseWriter, r *http.Request) {
	if config.S.OpenAIAPIKey == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable, "OPENAI_API_KEY is not configured.", httpx.CRV3001)
		return
	}
	var body struct {
		Text string `json:"text"`
		URL  string `json:"url"`
	}
	if err := httpx.Decode(r, &body); err != nil || len(strings.TrimSpace(body.Text)) < 10 {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	// TODO(go-port): port the AI job-reviewer (review_post) + job_sync dedup
	// pipeline to save a Job from the post text. Not yet implemented in the Go
	// port; the reviewer/job-sync services are outside this worker's scope.
	httpx.WriteError(w, http.StatusNotImplemented,
		"Manual job import via AI review is not yet implemented in the Go port.", httpx.CRV1006)
}

func importJobImage(w http.ResponseWriter, r *http.Request) {
	if config.S.OpenAIAPIKey == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable, "OPENAI_API_KEY is not configured.", httpx.CRV3001)
		return
	}
	// TODO(go-port): port review_job_image (AI vision) + _save_job_from_ai_fields.
	httpx.WriteError(w, http.StatusNotImplemented,
		"Screenshot import via AI vision is not yet implemented in the Go port.", httpx.CRV1006)
}
