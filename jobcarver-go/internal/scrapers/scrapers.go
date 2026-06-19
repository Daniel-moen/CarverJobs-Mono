// Package scrapers is a thin STUB for the various job scrapers in
// api/app/services/*_scraper.py (apify, dockwalk, faststream, vikingcrew,
// workonayacht, superyachttimes, crewfinders, scrape_do).
//
// Real scraping requires outbound HTTP, API keys (APIFY etc.) and headless
// browsers, none of which run here. Every Run* function returns empty results
// with a clear TODO so the scraper scheduler loop and the scraper admin
// endpoints have something real to call.
//
// TODO(go-port): implement real scrapers (port apify_scraper.py et al. to
// net/http; aggregate dataset items; map into ScrapedJob).
package scrapers

import (
	"context"

	"jobcarver/internal/config"
)

// ScrapedJob is a single normalised job item returned by a scraper. The field
// set mirrors the columns the Python scrapers populate on models.Job; kept loose
// (a map of extras) so the stub stays forward-compatible.
type ScrapedJob struct {
	Title       string            `json:"title"`
	Role        string            `json:"role"`
	Yacht       string            `json:"yacht"`
	Location    string            `json:"location"`
	Description string            `json:"description"`
	Source      string            `json:"source"`
	ContentHash string            `json:"content_hash"`
	Extra       map[string]string `json:"extra,omitempty"`
}

// Result reports what a single scraper run produced.
type Result struct {
	Source string       `json:"source"`
	Jobs   []ScrapedJob `json:"jobs"`
	Err    error        `json:"-"`
}

// sources is the list of scraper identifiers the scheduler iterates over,
// mirroring the modules under api/app/services/.
var sources = []string{
	"apify", "dockwalk", "faststream", "vikingcrew",
	"workonayacht", "superyachttimes", "crewfinders", "scrape_do",
}

// Sources returns the configured scraper source identifiers.
func Sources() []string { return sources }

// RunOne runs a single named scraper. STUB: always returns zero jobs.
//
// TODO(go-port): dispatch to a real scraper implementation per source.
func RunOne(_ context.Context, source string) Result {
	return Result{Source: source, Jobs: nil}
}

// RunAll runs every configured scraper and aggregates the (empty) results.
// Mirrors ApifyScraper.run_all / the scheduler's full sweep.
//
// TODO(go-port): run real scrapers; respect config.S.APIFYAPIKey etc.
func RunAll(ctx context.Context) []Result {
	out := make([]Result, 0, len(sources))
	for _, s := range sources {
		// A real implementation would skip sources whose key is unset, e.g.
		// apify when config.S.APIFYAPIKey == "".
		_ = config.S
		out = append(out, RunOne(ctx, s))
	}
	return out
}
