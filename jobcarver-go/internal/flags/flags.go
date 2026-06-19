// Package flags ports api/app/flags.py: in-memory feature kill-switches that
// reset to all-on each restart. Toggle via the admin flags route. Mutex-guarded.
package flags

import "sync"

var (
	mu sync.RWMutex

	// Keys must stay stable — frontend and routes reference them by name.
	state = map[string]bool{
		"interview":         true, // AI interview (/interview/next)
		"onboarding":        true, // AI onboarding (/interview/onboard)
		"matching":          true, // Job matching engine (/matching/*)
		"user_registration": true, // Creating new user accounts (POST /users)
		"scraper":           true, // Apify Facebook scraper — costs money per run
		"scraper_web":       true, // Web scrapers (Dockwalk, Yotspot) — free
		"whatsapp":          true, // WhatsApp bot (/webhooks/whatsapp)
	}
)

// Labels are human-readable names for the dashboard toggle UI (ports LABELS).
var Labels = map[string]string{
	"interview":         "AI Interview",
	"onboarding":        "AI Onboarding",
	"matching":          "Job Matching Engine",
	"user_registration": "User Registration",
	"scraper":           "Apify Scraper (paid — Facebook groups)",
	"scraper_web":       "Web Scrapers (free — Dockwalk + Yotspot)",
	"whatsapp":          "WhatsApp Bot",
}

// GetAll returns a copy of the current flag state.
func GetAll() map[string]bool {
	mu.RLock()
	defer mu.RUnlock()
	out := make(map[string]bool, len(state))
	for k, v := range state {
		out[k] = v
	}
	return out
}

// IsEnabled reports whether a flag is on. Unknown keys default to true (matches
// the Python implementation).
func IsEnabled(key string) bool {
	mu.RLock()
	defer mu.RUnlock()
	v, ok := state[key]
	if !ok {
		return true
	}
	return v
}

// SetFlag updates a flag, returning false if the key does not exist.
func SetFlag(key string, value bool) bool {
	mu.Lock()
	defer mu.Unlock()
	if _, ok := state[key]; !ok {
		return false
	}
	state[key] = value
	return true
}
