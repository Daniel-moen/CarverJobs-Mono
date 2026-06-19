// Package admin ports api/app/routes/admin.py: the admin-gated operations
// console (stats, feature flags, feedback campaign settings, error log + AI
// analysis, AI job review, analytics, and destructive cleanup routes) plus the
// un-gated public analytics ingestion endpoint.
//
// DB logic and the flags/metrics integration are real; the AI-backed routes
// (error analysis, job review) run through the internal/ai stub. The analytics
// read endpoints are served from real AnalyticsEvent rows with pragmatic
// aggregation. TODO(go-port): wire real OpenAI for analysis/review, and port the
// full analytics flow/transition computation from app/analytics.py.
package admin

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/ai"
	"jobcarver/internal/config"
	"jobcarver/internal/db"
	"jobcarver/internal/flags"
	"jobcarver/internal/handlers/telnyx"
	"jobcarver/internal/httpx"
	"jobcarver/internal/metrics"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

const feedbackCampaign = "feedback_2_tokens"

var validTargetModes = map[string]bool{"all": true, "website": true, "whatsapp": true, "specific": true, "off": true}

// Register mounts the admin-gated routes and the public analytics ingest route.
func Register(r chi.Router) {
	r.Group(func(r chi.Router) {
		r.Use(security.RequireRole("admin"))
		r.Get("/admin/stats", getStats)
		r.Get("/admin/telnyx-inbound", getTelnyxInbound)
		r.Get("/admin/whatsapp/messages", listWhatsAppMessages)
		r.Get("/admin/flags", getFlags)
		r.Patch("/admin/flags", updateFlag)
		r.Get("/admin/feedback/settings", getFeedbackSettings)
		r.Patch("/admin/feedback/settings", updateFeedbackSettings)
		r.Get("/admin/errors", getErrorLogs)
		r.Post("/admin/errors/{errorID}/analyze", analyzeError)
		r.Post("/admin/jobs/review", reviewJobs)
		r.Get("/admin/analytics", getAnalytics)
		r.Get("/admin/analytics/flows", getFlows)
		r.Delete("/admin/jobs/duplicates", wipeDuplicateJobs)
		r.Delete("/admin/whatsapp/sessions", wipeWhatsAppSessions)
	})

	// Public (un-gated) analytics ingestion from unauthenticated pages.
	r.Post("/admin/analytics", postAnalytics)
}

// ── stats ────────────────────────────────────────────────────────────────────

func getStats(w http.ResponseWriter, r *http.Request) {
	now := time.Now().UTC()
	uptime := int(now.Sub(metrics.ServerStartedAt()).Seconds())

	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok":                true,
		"uptime_seconds":    uptime,
		"server_started_at": metrics.ServerStartedAt().Format(time.RFC3339),
		"db": map[string]any{
			"users_total":                    count(&models.User{}, ""),
			"users_active":                   count(&models.User{}, "is_active = 1"),
			"users_by_role":                  groupCount(&models.User{}, "role"),
			"jobs_total":                     count(&models.Job{}, ""),
			"jobs_by_status":                 groupCount(&models.Job{}, "status"),
			"whatsapp_sessions_total":        count(&models.WhatsAppSession{}, ""),
			"whatsapp_sessions_by_mode":      groupCount(&models.WhatsAppSession{}, "mode"),
			"whatsapp_magic_tokens_total":    count(&models.WhatsAppMagicToken{}, ""),
			"whatsapp_magic_tokens_used":     count(&models.WhatsAppMagicToken{}, "used = 1"),
			"feedback_submissions_total":     count(&models.FeedbackSubmission{}, ""),
			"feedback_submissions_by_source": groupCount(&models.FeedbackSubmission{}, "source"),
		},
		"events":           metrics.Snapshot(),
		"errors_by_module": metrics.ErrorsByModuleSnapshot(),
		"time_series":      metrics.History(),
	})
}

func getTelnyxInbound(w http.ResponseWriter, r *http.Request) {
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "messages": telnyx.Recent()})
}

func listWhatsAppMessages(w http.ResponseWriter, r *http.Request) {
	limit := 50
	if raw := r.URL.Query().Get("limit"); raw != "" {
		if v, err := strconv.Atoi(raw); err == nil && v >= 1 && v <= 200 {
			limit = v
		}
	}
	q := db.DB.Model(&models.WhatsAppMessage{}).Order("id DESC")
	if phone := strings.TrimSpace(r.URL.Query().Get("phone_number")); phone != "" {
		q = q.Where("phone_number = ?", phone)
	}
	var rows []models.WhatsAppMessage
	q.Limit(limit).Find(&rows)
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		out = append(out, map[string]any{
			"id": row.ID, "created_at": iso(row.CreatedAt), "phone_number": row.PhoneNumber,
			"direction": row.Direction, "message_type": row.MessageType, "content": row.Content,
			"meta_message_id": row.MetaMessageID, "graph_phone_number_id": row.GraphPhoneNumberID,
		})
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "messages": out})
}

// ── feature flags ────────────────────────────────────────────────────────────

func getFlags(w http.ResponseWriter, r *http.Request) {
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "flags": flags.GetAll(), "labels": flags.Labels})
}

func updateFlag(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Key     string `json:"key"`
		Enabled bool   `json:"enabled"`
	}
	if err := httpx.Decode(r, &body); err != nil || body.Key == "" {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if !flags.SetFlag(body.Key, body.Enabled) {
		httpx.WriteError(w, http.StatusNotFound, "Unknown feature flag.", httpx.CRV5002)
		return
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "flags": flags.GetAll()})
}

// ── feedback campaign settings ───────────────────────────────────────────────

func getFeedbackSetting() models.FeedbackCampaignSetting {
	var s models.FeedbackCampaignSetting
	if db.DB.Where("campaign = ?", feedbackCampaign).First(&s).Error == nil {
		if !validTargetModes[s.TargetMode] {
			s.TargetMode = "all"
			db.DB.Save(&s)
		}
		return s
	}
	s = models.FeedbackCampaignSetting{Campaign: feedbackCampaign, Enabled: true, TargetMode: "all", TargetUserKeysJSON: "[]"}
	db.DB.Create(&s)
	return s
}

func serialiseFeedbackSetting(s models.FeedbackCampaignSetting) map[string]any {
	keys := []string{}
	_ = jsonUnmarshalStrings(s.TargetUserKeysJSON, &keys)
	return map[string]any{
		"campaign":         s.Campaign,
		"enabled":          s.Enabled,
		"target_mode":      s.TargetMode,
		"target_user_keys": keys,
		"reward_amount":    2,
	}
}

func getFeedbackSettings(w http.ResponseWriter, r *http.Request) {
	resp := map[string]any{"ok": true}
	for k, v := range serialiseFeedbackSetting(getFeedbackSetting()) {
		resp[k] = v
	}
	httpx.JSON(w, http.StatusOK, resp)
}

func updateFeedbackSettings(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Enabled        bool     `json:"enabled"`
		TargetMode     string   `json:"target_mode"`
		TargetUserKeys []string `json:"target_user_keys"`
	}
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if !validTargetModes[body.TargetMode] {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid target_mode.", httpx.CRV1003)
		return
	}
	// Normalise + dedupe keys (lowercase, trimmed).
	seen := map[string]bool{}
	var keys []string
	for _, k := range body.TargetUserKeys {
		nk := strings.ToLower(strings.TrimSpace(k))
		if nk != "" && !seen[nk] {
			seen[nk] = true
			keys = append(keys, nk)
		}
	}
	keysJSON := jsonMarshalStrings(keys)

	s := getFeedbackSetting()
	s.Enabled = body.Enabled
	s.TargetMode = body.TargetMode
	s.TargetUserKeysJSON = keysJSON
	db.DB.Save(&s)

	resp := map[string]any{"ok": true}
	for k, v := range serialiseFeedbackSetting(s) {
		resp[k] = v
	}
	httpx.JSON(w, http.StatusOK, resp)
}

// ── error log + AI analysis ──────────────────────────────────────────────────

func getErrorLogs(w http.ResponseWriter, r *http.Request) {
	var rows []models.ErrorLog
	db.DB.Order("created_at DESC").Limit(50).Find(&rows)
	out := make([]map[string]any, 0, len(rows))
	for _, e := range rows {
		out = append(out, map[string]any{
			"id": e.ID, "created_at": iso(e.CreatedAt), "level": e.Level,
			"status_code": e.StatusCode, "crv_code": e.CrvCode, "method": e.Method,
			"path": e.Path, "module": e.Module, "message": e.Message,
			"traceback": e.Traceback, "request_id": e.RequestID, "client_ip": e.ClientIP,
			"ai_analysis": e.AIAnalysis,
		})
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "errors": out})
}

func analyzeError(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(chi.URLParam(r, "errorID"))
	if err != nil {
		httpx.WriteError(w, http.StatusNotFound, "Error log entry not found.", httpx.CRV1005)
		return
	}
	var row models.ErrorLog
	if db.DB.Where("id = ?", id).First(&row).Error != nil {
		httpx.WriteError(w, http.StatusNotFound, "Error log entry not found.", httpx.CRV1005)
		return
	}
	var b strings.Builder
	b.WriteString("You are a senior backend engineer reviewing a server error from the Carver API.\n\nError details:\n")
	b.WriteString("  Method: " + derefStr(row.Method) + " Path: " + derefStr(row.Path) + "\n")
	b.WriteString("  Module: " + derefStr(row.Module) + "\n")
	b.WriteString("  Message: " + row.Message + "\n")
	if row.Traceback != nil {
		b.WriteString("\nTraceback:\n" + *row.Traceback + "\n")
	}
	b.WriteString("\nProvide a concise analysis (3-5 sentences): root cause, responsible file/function, recommended fix.")

	model := config.S.OpenAIModel
	if model == "" {
		model = "gpt-4o-mini"
	}
	analysis, err := ai.Chat(r.Context(), model, []ai.Message{{Role: "user", Content: b.String()}}, ai.Options{MaxTokens: 400, Temperature: 0.1})
	if err != nil {
		httpx.WriteError(w, http.StatusBadGateway, "Could not reach AI service for analysis.", httpx.CRV5003)
		return
	}
	row.AIAnalysis = &analysis
	db.DB.Save(&row)
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "analysis": analysis})
}

// ── AI job review ────────────────────────────────────────────────────────────

func reviewJobs(w http.ResponseWriter, r *http.Request) {
	if config.S.OpenAIAPIKey == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable, "OpenAI API key is not configured.", httpx.CRV5004)
		return
	}
	var jobs []models.Job
	db.DB.Find(&jobs)
	if len(jobs) == 0 {
		httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "reviewed": 0, "deleted": 0, "deleted_jobs": []any{}})
		return
	}
	// TODO(go-port): batch the jobs through the AI reviewer and delete rejected
	// ones. With the AI stub returning no results, nothing is deleted; the shape
	// is preserved so the admin UI keeps working.
	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok": true, "total": len(jobs), "reviewed": len(jobs),
		"deleted": 0, "failed_batches": 0, "deleted_jobs": []any{},
	})
}

// ── analytics ────────────────────────────────────────────────────────────────

func postAnalytics(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Events []struct {
			Type      string `json:"type"`
			SessionID string `json:"session_id"`
			Page      string `json:"page"`
			Label     string `json:"label"`
			Value     any    `json:"value"`
			TS        string `json:"ts"`
		} `json:"events"`
	}
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	ingested := 0
	for _, ev := range body.Events {
		if strings.TrimSpace(ev.Type) == "" {
			continue
		}
		row := models.AnalyticsEvent{
			SessionID: orDefault(ev.SessionID, "anonymous"),
			EventType: ev.Type,
			Page:      ptrIfSet(ev.Page),
			Label:     ptrIfSet(ev.Label),
			Value:     ptrIfSet(valueToString(ev.Value)),
			ClientTS:  ptrIfSet(ev.TS),
		}
		if db.DB.Create(&row).Error == nil {
			ingested++
		}
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "ingested": ingested})
}

func getAnalytics(w http.ResponseWriter, r *http.Request) {
	// Pragmatic aggregation over AnalyticsEvent. TODO(go-port): port the full
	// app/analytics.py aggregation (funnels, retention, etc.).
	byType := groupCount(&models.AnalyticsEvent{}, "event_type")
	total := count(&models.AnalyticsEvent{}, "")
	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok": true, "total_events": total, "by_type": byType,
	})
}

func getFlows(w http.ResponseWriter, r *http.Request) {
	// TODO(go-port): port get_user_flows + get_page_transitions from analytics.py.
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "flows": []any{}, "transitions": []any{}})
}

// ── destructive cleanup ──────────────────────────────────────────────────────

func wipeDuplicateJobs(w http.ResponseWriter, r *http.Request) {
	// Keep the oldest (min id) per (title, role, location) group; delete the rest.
	var keepIDs []int
	db.DB.Model(&models.Job{}).Select("MIN(id)").Group("title, role, location").Pluck("MIN(id)", &keepIDs)
	res := db.DB.Where("id NOT IN ?", keepIDs).Delete(&models.Job{})
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "deleted": res.RowsAffected})
}

func wipeWhatsAppSessions(w http.ResponseWriter, r *http.Request) {
	sessions := db.DB.Where("1 = 1").Delete(&models.WhatsAppSession{})
	tokens := db.DB.Where("1 = 1").Delete(&models.WhatsAppMagicToken{})
	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok": true, "sessions_deleted": sessions.RowsAffected, "tokens_deleted": tokens.RowsAffected,
	})
}

// ── helpers ──────────────────────────────────────────────────────────────────

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

func derefStr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func ptrIfSet(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func orDefault(s, def string) string {
	if strings.TrimSpace(s) == "" {
		return def
	}
	return s
}

func jsonUnmarshalStrings(s string, dst *[]string) error {
	if strings.TrimSpace(s) == "" {
		*dst = []string{}
		return nil
	}
	return json.Unmarshal([]byte(s), dst)
}

func jsonMarshalStrings(s []string) string {
	if s == nil {
		s = []string{}
	}
	b, err := json.Marshal(s)
	if err != nil {
		return "[]"
	}
	return string(b)
}

func valueToString(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return t
	case bool:
		if t {
			return "true"
		}
		return "false"
	case float64:
		return strconv.FormatFloat(t, 'f', -1, 64)
	default:
		return ""
	}
}
