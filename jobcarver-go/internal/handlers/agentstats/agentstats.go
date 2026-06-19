// Package agentstats ports api/app/routes/agent_stats.py: platform-wide
// aggregate statistics (GET /agent/stats) and a guarded read/write SQL endpoint
// (POST /agent/sql). Both authenticate via the static AGENT_API_TOKEN bearer
// (not the session system). All queries run against the real database.
package agentstats

import (
	"crypto/subtle"
	"database/sql"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/config"
	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/metrics"
	"jobcarver/internal/models"
)

const (
	maxQueryLength = 4096
	maxRows        = 1000
)

var (
	forbiddenPattern = regexp.MustCompile(`(?i)\b(DROP|ALTER|CREATE|TRUNCATE|ATTACH|DETACH|LOAD_EXTENSION|REINDEX|VACUUM)\b`)
	allowedLeading   = regexp.MustCompile(`(?i)^\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE|PRAGMA|EXPLAIN|WITH)\b`)
	rowReturningLead = regexp.MustCompile(`(?i)^\s*(SELECT|PRAGMA|EXPLAIN|WITH)\b`)
)

// Register mounts /agent/stats and /agent/sql (agent-token gated).
func Register(r chi.Router) {
	r.With(requireAgentToken).Get("/agent/stats", getAgentStats)
	r.With(requireAgentToken).Post("/agent/sql", runAgentSQL)
}

func requireAgentToken(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if config.S.AgentAPIToken == "" {
			httpx.WriteError(w, http.StatusServiceUnavailable, "Agent stats endpoint is not configured.", httpx.CRV5005)
			return
		}
		token := ""
		if auth := r.Header.Get("Authorization"); strings.HasPrefix(auth, "Bearer ") {
			token = strings.TrimSpace(auth[7:])
		}
		if token == "" || subtle.ConstantTimeCompare([]byte(token), []byte(config.S.AgentAPIToken)) != 1 {
			httpx.WriteError(w, http.StatusUnauthorized, "Invalid or missing agent token.", httpx.CRV2004)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func getAgentStats(w http.ResponseWriter, r *http.Request) {
	now := time.Now().UTC()
	cutoff24h := now.Add(-24 * time.Hour)
	cutoff7d := now.Add(-7 * 24 * time.Hour)
	uptime := int(now.Sub(metrics.ServerStartedAt()).Seconds())

	usersTotal := count(&models.User{}, "")
	usersActive := count(&models.User{}, "is_active = 1")
	usersSubscribed := count(&models.User{}, "is_subscribed = 1")
	usersByRole := groupCount(&models.User{}, "role")

	waTotal := count(&models.WhatsAppSession{}, "")
	waByMode := groupCount(&models.WhatsAppSession{}, "mode")
	waTokensTotal := count(&models.WhatsAppMagicToken{}, "")
	waTokensUsed := count(&models.WhatsAppMagicToken{}, "used = 1")

	jobsTotal := count(&models.Job{}, "")
	jobsByStatus := groupCount(&models.Job{}, "status")
	jobsBySource := groupCount(&models.Job{}, "source")
	jobsLast24h := countWhere(&models.Job{}, "created_at >= ?", cutoff24h)
	jobsLast7d := countWhere(&models.Job{}, "created_at >= ?", cutoff7d)

	matchSessionsTotal := count(&models.MatchSession{}, "")
	var matchTotalMatched int64
	db.DB.Model(&models.MatchSession{}).Select("COALESCE(SUM(total_matched),0)").Scan(&matchTotalMatched)
	var avgCompat sql.NullFloat64
	db.DB.Model(&models.MatchSessionResult{}).Where("matched = 1").Select("AVG(compatibility)").Scan(&avgCompat)

	waitlistTotal := count(&models.WaitlistSignup{}, "")
	profilesTotal := count(&models.CrewProfile{}, "")
	documentsTotal := count(&models.Document{}, "")
	errorsLast24h := countWhere(&models.ErrorLog{}, "created_at >= ?", cutoff24h)
	subsByStatus := groupCount(&models.Subscription{}, "status")

	var creditsTotalBalance int64
	db.DB.Model(&models.CreditAccount{}).Select("COALESCE(SUM(balance),0)").Scan(&creditsTotalBalance)

	tokensPurchasedTotal := count(&models.Subscription{}, "status = 'completed'")
	tokensRevenue := sumAmountCompleted()
	var tokensUniqueBuyers int64
	db.DB.Model(&models.Subscription{}).Where("status = 'completed'").
		Distinct("user_key").Count(&tokensUniqueBuyers)

	events := metrics.Snapshot()

	var avgCompatOut any
	if avgCompat.Valid {
		avgCompatOut = round2(avgCompat.Float64)
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok":                true,
		"generated_at":      now.Format(time.RFC3339),
		"uptime_seconds":    uptime,
		"server_started_at": metrics.ServerStartedAt().Format(time.RFC3339),
		"users": map[string]any{
			"website_total":              usersTotal,
			"active":                     usersActive,
			"subscribed":                 usersSubscribed,
			"by_role":                    usersByRole,
			"whatsapp_total":             waTotal,
			"whatsapp_by_mode":           waByMode,
			"whatsapp_magic_tokens":      waTokensTotal,
			"whatsapp_magic_tokens_used": waTokensUsed,
		},
		"jobs": map[string]any{
			"total":          jobsTotal,
			"by_status":      jobsByStatus,
			"by_source":      jobsBySource,
			"added_last_24h": jobsLast24h,
			"added_last_7d":  jobsLast7d,
		},
		"matching": map[string]any{
			"sessions_total":    matchSessionsTotal,
			"total_matched":     matchTotalMatched,
			"avg_compatibility": avgCompatOut,
		},
		"good_to_know": map[string]any{
			"waitlist_signups":        waitlistTotal,
			"crew_profiles":           profilesTotal,
			"documents_uploaded":      documentsTotal,
			"subscriptions_by_status": subsByStatus,
			"credits_total_balance":   creditsTotalBalance,
			"token_purchases":         tokensPurchasedTotal,
			"token_revenue_zar":       tokensRevenue,
			"token_unique_buyers":     tokensUniqueBuyers,
			"errors_last_24h":         errorsLast24h,
		},
		"api": map[string]any{
			"requests_total":     events["requests_total"],
			"whatsapp_messages":  events["whatsapp_messages"],
			"crew_matches":       events["crew_matches"],
			"avg_response_ms":    events["avg_response_ms"],
			"avg_ai_response_ms": events["avg_ai_response_ms"],
		},
	})
}

func runAgentSQL(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Query string `json:"query"`
		Limit int    `json:"limit"`
	}
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid request body.", httpx.CRV1003)
		return
	}
	limit := body.Limit
	if limit <= 0 || limit > maxRows {
		limit = maxRows
	}

	if msg, code, ok := validateSQL(body.Query); !ok {
		httpx.WriteError(w, code, msg, httpx.CRV5007)
		return
	}
	effective := strings.TrimRight(strings.TrimSpace(body.Query), ";")

	sqlDB, err := db.DB.DB()
	if err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not open database connection.", httpx.CRV5008)
		return
	}

	if rowReturningLead.MatchString(effective) {
		rows, err := sqlDB.Query(effective)
		if err != nil {
			httpx.WriteError(w, http.StatusBadRequest, "Query error: "+err.Error(), httpx.CRV5008)
			return
		}
		defer rows.Close()
		columns, _ := rows.Columns()
		out := make([][]any, 0, limit)
		truncated := false
		for rows.Next() {
			if len(out) >= limit {
				truncated = true
				break
			}
			vals := make([]any, len(columns))
			ptrs := make([]any, len(columns))
			for i := range vals {
				ptrs[i] = &vals[i]
			}
			if err := rows.Scan(ptrs...); err != nil {
				httpx.WriteError(w, http.StatusBadRequest, "Query error: "+err.Error(), httpx.CRV5008)
				return
			}
			for i, v := range vals {
				if b, ok := v.([]byte); ok {
					vals[i] = string(b)
				}
			}
			out = append(out, vals)
		}
		httpx.JSON(w, http.StatusOK, map[string]any{
			"ok": true, "columns": columns, "rows": out,
			"row_count": len(out), "truncated": truncated,
		})
		return
	}

	res, err := sqlDB.Exec(effective)
	if err != nil {
		httpx.WriteError(w, http.StatusBadRequest, "Query error: "+err.Error(), httpx.CRV5008)
		return
	}
	affected, _ := res.RowsAffected()
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "rows_affected": affected})
}

func validateSQL(query string) (string, int, bool) {
	if len(query) > maxQueryLength {
		return "Query too long (max " + strconv.Itoa(maxQueryLength) + " chars).", http.StatusBadRequest, false
	}
	stripped := strings.TrimSpace(strings.TrimRight(strings.TrimSpace(query), ";"))
	if stripped == "" {
		return "Empty query.", http.StatusBadRequest, false
	}
	if !allowedLeading.MatchString(stripped) {
		return "Only SELECT, INSERT, UPDATE, DELETE, REPLACE, PRAGMA, EXPLAIN, and WITH queries are allowed.", http.StatusForbidden, false
	}
	if forbiddenPattern.MatchString(stripped) {
		return "Query contains a forbidden keyword (DROP, ALTER, CREATE, TRUNCATE are not allowed).", http.StatusForbidden, false
	}
	return "", 0, true
}

// ── aggregation helpers ──────────────────────────────────────────────────────

func count(model any, where string) int64 {
	q := db.DB.Model(model)
	if where != "" {
		q = q.Where(where)
	}
	var n int64
	q.Count(&n)
	return n
}

func countWhere(model any, where string, args ...any) int64 {
	var n int64
	db.DB.Model(model).Where(where, args...).Count(&n)
	return n
}

func groupCount(model any, column string) map[string]int64 {
	type row struct {
		K string
		C int64
	}
	var rows []row
	db.DB.Model(model).Select(column + " as k, COUNT(*) as c").Group(column).Scan(&rows)
	out := map[string]int64{}
	for _, r := range rows {
		key := r.K
		if key == "" {
			key = "unknown"
		}
		out[key] = r.C
	}
	return out
}

func sumAmountCompleted() float64 {
	var total float64
	db.DB.Model(&models.Subscription{}).
		Where("status = 'completed'").
		Select("COALESCE(SUM(CAST(amount AS REAL)),0)").Scan(&total)
	return total
}

func round2(f float64) float64 {
	return float64(int64(f*100+0.5)) / 100
}
