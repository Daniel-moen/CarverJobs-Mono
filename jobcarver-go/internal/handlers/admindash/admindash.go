// Package admindash ports api/app/routes/admin_dashboard.py: the standalone
// admin dashboard. GET /admin/dashboard/metrics returns the frozen signup /
// revenue / token / message / engagement JSON contract (admin-gated); the
// /admin/dashboard[.css|.js] routes serve the panel's static files un-gated so
// the login form can render before a session cookie exists.
//
// Static files live under api/app/static/admin in the Python tree; this port
// serves them from a configurable directory (ADMIN_STATIC_DIR env or
// ./static/admin) and 404s cleanly if absent. TODO(go-port): bundle/ship the
// dashboard static assets with the Go binary.
package admindash

import (
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

const paidStatus = "completed"

func staticDir() string {
	if d := os.Getenv("ADMIN_STATIC_DIR"); d != "" {
		return d
	}
	return filepath.Join("static", "admin")
}

// Register mounts the admin-gated metrics route + the public static routes.
func Register(r chi.Router) {
	r.With(security.RequireRole("admin")).Get("/admin/dashboard/metrics", getDashboardMetrics)

	r.Get("/admin/dashboard", serveFile("index.html", "text/html"))
	r.Get("/admin/dashboard.css", serveFile("dashboard.css", "text/css"))
	r.Get("/admin/dashboard.js", serveFile("dashboard.js", "application/javascript"))
}

func serveFile(name, contentType string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		path := filepath.Join(staticDir(), name)
		if info, err := os.Stat(path); err != nil || info.IsDir() {
			httpx.WriteError(w, http.StatusNotFound, "Dashboard asset not found.", httpx.CRV1005)
			return
		}
		w.Header().Set("Content-Type", contentType)
		http.ServeFile(w, r, path)
	}
}

func getDashboardMetrics(w http.ResponseWriter, r *http.Request) {
	now := time.Now().UTC()
	days := 30
	if raw := r.URL.Query().Get("days"); raw != "" {
		if v, err := strconv.Atoi(raw); err == nil && v >= 1 && v <= 365 {
			days = v
		}
	}

	// ── Signups ──────────────────────────────────────────────────────────────
	usersTotal := count(&models.User{}, "")
	usersWebsite := count(&models.User{}, "email LIKE '%@%'")
	waUsers := count(&models.WhatsAppSession{}, "")
	byRole := map[string]int64{"crew": 0, "agency": 0, "admin": 0}
	for k, v := range groupCount(&models.User{}, "role") {
		byRole[k] = v
	}
	activeUsers := count(&models.User{}, "is_active = 1")
	subscribedUsers := count(&models.User{}, "is_subscribed = 1")

	var recentUsers []models.User
	db.DB.Order("created_at DESC, id DESC").Limit(25).Find(&recentUsers)
	recentSignups := make([]map[string]any, 0, len(recentUsers))
	for _, u := range recentUsers {
		recentSignups = append(recentSignups, map[string]any{
			"id": u.ID, "name": u.FullName, "identifier": u.Email,
			"role": u.Role, "source": "website", "created_at": iso(u.CreatedAt),
		})
	}

	// Signup timeseries: zero-fill last `days` UTC days.
	startDate := now.AddDate(0, 0, -(days - 1)).Truncate(24 * time.Hour)
	windowStart := time.Date(startDate.Year(), startDate.Month(), startDate.Day(), 0, 0, 0, 0, time.UTC)
	buckets := map[string]map[string]int64{}
	order := make([]string, 0, days)
	for i := 0; i < days; i++ {
		d := windowStart.AddDate(0, 0, i).Format("2006-01-02")
		buckets[d] = map[string]int64{"website": 0, "whatsapp": 0}
		order = append(order, d)
	}
	addToBuckets(buckets, &models.User{}, windowStart, "website")
	addToBuckets(buckets, &models.WhatsAppSession{}, windowStart, "whatsapp")
	timeseries := make([]map[string]any, 0, len(order))
	sort.Strings(order)
	for _, d := range order {
		timeseries = append(timeseries, map[string]any{
			"date": d, "website": buckets[d]["website"], "whatsapp": buckets[d]["whatsapp"],
		})
	}

	// ── Revenue ──────────────────────────────────────────────────────────────
	transactionsTotal := count(&models.Subscription{}, "")
	byStatus := groupCount(&models.Subscription{}, "status")

	var paidRows []models.Subscription
	db.DB.Where("status = ?", paidStatus).Find(&paidRows)
	totalPaid := 0.0
	payingKeys := map[string]bool{}
	for _, s := range paidRows {
		if v, err := strconv.ParseFloat(s.Amount, 64); err == nil {
			totalPaid += v
		}
		payingKeys[s.UserKey] = true
	}

	var recentPaymentRows []models.Subscription
	db.DB.Order("created_at DESC, id DESC").Limit(15).Find(&recentPaymentRows)
	recentPayments := make([]map[string]any, 0, len(recentPaymentRows))
	for _, s := range recentPaymentRows {
		recentPayments = append(recentPayments, map[string]any{
			"user_key": s.UserKey, "amount": s.Amount, "status": s.Status, "created_at": iso(s.CreatedAt),
		})
	}

	// ── Tokens ───────────────────────────────────────────────────────────────
	var balanceOutstanding int64
	db.DB.Model(&models.CreditAccount{}).Select("COALESCE(SUM(balance),0)").Scan(&balanceOutstanding)
	accounts := count(&models.CreditAccount{}, "")
	var spentOnUnlocks int64
	db.DB.Model(&models.ContactUnlock{}).Select("COALESCE(SUM(cost_tokens),0)").Scan(&spentOnUnlocks)
	unlocksCount := count(&models.ContactUnlock{}, "")

	// ── Messages ─────────────────────────────────────────────────────────────
	waTotalMsg := count(&models.WhatsAppMessage{}, "")
	inbound := count(&models.WhatsAppMessage{}, "direction = 'inbound'")
	outbound := count(&models.WhatsAppMessage{}, "direction = 'outbound'")
	activeSessions := count(&models.WhatsAppSession{}, "")
	sessionsByMode := map[string]int64{"onboarding": 0, "chat": 0}
	for k, v := range groupCount(&models.WhatsAppSession{}, "mode") {
		sessionsByMode[k] = v
	}

	// ── Engagement ───────────────────────────────────────────────────────────
	jobsTotal := count(&models.Job{}, "")
	matchSessions := count(&models.MatchSession{}, "")
	feedbackSubmissions := count(&models.FeedbackSubmission{}, "")
	documents := count(&models.Document{}, "")

	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok":           true,
		"generated_at": now.Format(time.RFC3339),
		"window_days":  days,
		"signups": map[string]any{
			"total": usersTotal, "website": usersWebsite, "whatsapp": waUsers,
			"by_role": byRole, "active_users": activeUsers, "subscribed_users": subscribedUsers,
			"recent": recentSignups, "timeseries": timeseries,
		},
		"revenue": map[string]any{
			"currency": "ZAR", "total_paid": round2(totalPaid),
			"paying_customers": len(payingKeys), "transactions_total": transactionsTotal,
			"transactions_paid": len(paidRows), "by_status": byStatus, "recent_payments": recentPayments,
		},
		"tokens": map[string]any{
			"balance_outstanding": balanceOutstanding, "accounts": accounts,
			"spent_on_unlocks": spentOnUnlocks, "unlocks_count": unlocksCount,
		},
		"messages": map[string]any{
			"whatsapp_total": waTotalMsg, "inbound": inbound, "outbound": outbound,
			"active_sessions": activeSessions, "sessions_by_mode": sessionsByMode,
		},
		"engagement": map[string]any{
			"jobs_total": jobsTotal, "match_sessions": matchSessions,
			"feedback_submissions": feedbackSubmissions, "documents": documents,
		},
	})
}

// addToBuckets buckets a model's created_at rows into the day buckets.
func addToBuckets(buckets map[string]map[string]int64, model any, windowStart time.Time, key string) {
	var times []time.Time
	db.DB.Model(model).Where("created_at >= ?", windowStart).Pluck("created_at", &times)
	for _, t := range times {
		d := t.UTC().Format("2006-01-02")
		if b, ok := buckets[d]; ok {
			b[key]++
		}
	}
}

func count(model any, where string) int64 {
	q := db.DB.Model(model)
	if where != "" {
		q = q.Where(where)
	}
	var n int64
	q.Count(&n)
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

func iso(t time.Time) any {
	if t.IsZero() {
		return nil
	}
	return t.Format(time.RFC3339)
}

func round2(f float64) float64 {
	return float64(int64(f*100+0.5)) / 100
}
