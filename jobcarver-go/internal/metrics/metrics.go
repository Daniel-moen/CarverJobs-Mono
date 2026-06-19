// Package metrics ports api/app/metrics.py: in-memory counters, a Welford
// rolling mean of response times, and a 60-point rolling history snapshot.
// All access is mutex-guarded. Counters reset on restart by design.
package metrics

import (
	"math"
	"strings"
	"sync"
	"time"
)

var (
	mu              sync.Mutex
	serverStartedAt = time.Now().UTC()

	counters = map[string]int{
		"requests_total":        0,
		"errors_4xx":            0,
		"errors_5xx":            0,
		"rate_limit_hits":       0,
		"csrf_rejections":       0,
		"feature_blocked":       0,
		"logins_success":        0,
		"logins_failed":         0,
		"onboard_started":       0,
		"onboard_completed":     0,
		"interview_turns":       0,
		"matching_queued":       0,
		"matching_completed":    0,
		"doc_uploads":           0,
		"doc_downloads":         0,
		"doc_deletes":           0,
		"scraper_triggers":      0,
		"whatsapp_messages":     0,
		"whatsapp_apply_drafts": 0,
		"whatsapp_magic_logins": 0,
		"crew_matches":          0,
	}

	respCount  int
	respMeanMS float64

	aiRespCount  int
	aiRespMeanMS float64

	errorsByModule = map[string]int{}

	historyMax         = 60
	history            []map[string]any
	prevSnapshot       = map[string]int{}
	prevErrorsByModule = map[string]int{}
)

// Increment adds 1 to a counter (creating it if unknown).
func Increment(key string) { IncrementBy(key, 1) }

// IncrementBy adds amount to a counter.
func IncrementBy(key string, amount int) {
	mu.Lock()
	defer mu.Unlock()
	counters[key] += amount
}

// RecordResponseTime updates the rolling mean for non-AI endpoints (Welford).
func RecordResponseTime(ms int) {
	mu.Lock()
	defer mu.Unlock()
	respCount++
	respMeanMS += (float64(ms) - respMeanMS) / float64(respCount)
}

// RecordAIResponseTime updates the rolling mean for AI call latency (Welford).
func RecordAIResponseTime(ms int) {
	mu.Lock()
	defer mu.Unlock()
	aiRespCount++
	aiRespMeanMS += (float64(ms) - aiRespMeanMS) / float64(aiRespCount)
}

// RecordErrorByModule tracks an error against a route module; statusClass is
// "4xx" or "5xx".
func RecordErrorByModule(module, statusClass string) {
	mu.Lock()
	defer mu.Unlock()
	errorsByModule[module+":"+statusClass]++
}

func round1(f float64) float64 { return math.Round(f*10) / 10 }

// Snapshot returns a copy of the counters plus average response times.
func Snapshot() map[string]any {
	mu.Lock()
	defer mu.Unlock()
	out := make(map[string]any, len(counters)+2)
	for k, v := range counters {
		out[k] = v
	}
	out["avg_response_ms"] = round1(respMeanMS)
	out["avg_ai_response_ms"] = round1(aiRespMeanMS)
	return out
}

// ErrorsByModuleSnapshot returns {module: {4xx: n, 5xx: n}}.
func ErrorsByModuleSnapshot() map[string]map[string]int {
	mu.Lock()
	defer mu.Unlock()
	result := map[string]map[string]int{}
	for key, count := range errorsByModule {
		idx := strings.LastIndex(key, ":")
		if idx < 0 {
			continue
		}
		module, statusClass := key[:idx], key[idx+1:]
		if result[module] == nil {
			result[module] = map[string]int{"4xx": 0, "5xx": 0}
		}
		result[module][statusClass] = count
	}
	return result
}

// RecordSnapshot appends a time-series point with per-minute deltas.
func RecordSnapshot() {
	mu.Lock()
	defer mu.Unlock()

	delta := func(key string) int {
		d := counters[key] - prevSnapshot[key]
		if d < 0 {
			return 0
		}
		return d
	}

	moduleErrors := map[string]map[string]int{}
	for key, count := range errorsByModule {
		d := count - prevErrorsByModule[key]
		if d <= 0 {
			continue
		}
		idx := strings.LastIndex(key, ":")
		if idx < 0 {
			continue
		}
		module, statusClass := key[:idx], key[idx+1:]
		if moduleErrors[module] == nil {
			moduleErrors[module] = map[string]int{"4xx": 0, "5xx": 0}
		}
		moduleErrors[module][statusClass] = d
	}

	point := map[string]any{
		"ts":                 time.Now().UTC().Format(time.RFC3339),
		"requests":           delta("requests_total"),
		"errors_4xx":         delta("errors_4xx"),
		"errors_5xx":         delta("errors_5xx"),
		"rate_limit_hits":    delta("rate_limit_hits"),
		"csrf_rejections":    delta("csrf_rejections"),
		"logins_success":     delta("logins_success"),
		"logins_failed":      delta("logins_failed"),
		"onboard_started":    delta("onboard_started"),
		"onboard_completed":  delta("onboard_completed"),
		"avg_response_ms":    round1(respMeanMS),
		"avg_ai_response_ms": round1(aiRespMeanMS),
		"errors_by_module":   moduleErrors,
	}
	history = append(history, point)
	if len(history) > historyMax {
		history = history[len(history)-historyMax:]
	}

	prevSnapshot = map[string]int{}
	for k, v := range counters {
		prevSnapshot[k] = v
	}
	prevErrorsByModule = map[string]int{}
	for k, v := range errorsByModule {
		prevErrorsByModule[k] = v
	}
}

// History returns a copy of the rolling time-series.
func History() []map[string]any {
	mu.Lock()
	defer mu.Unlock()
	out := make([]map[string]any, len(history))
	copy(out, history)
	return out
}

// ServerStartedAt returns the process start time (UTC).
func ServerStartedAt() time.Time { return serverStartedAt }
