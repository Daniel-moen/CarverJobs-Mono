// Package matching ports api/app/routes/matching.py: the admin-gated /matching
// endpoint that scores every open/priority job against a user and spends one
// token. The actual scoring runs through internal/matching (which routes the
// model call through the internal/ai stub).
package matching

import (
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/config"
	"jobcarver/internal/credits"
	"jobcarver/internal/db"
	"jobcarver/internal/flags"
	"jobcarver/internal/httpx"
	matchengine "jobcarver/internal/matching"
	"jobcarver/internal/metrics"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

// Register mounts POST /matching/run (admin session required, mirroring the
// require_admin_session dependency on the Python router).
//
// NOTE: the /matching prefix is shared with the crewmatch handler, so this uses
// r.Group + a full path rather than r.Route("/matching") to avoid a chi mount
// collision.
func Register(r chi.Router) {
	r.Group(func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Use(adminOnly)
		r.Post("/matching/run", run)
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

type runRequest struct {
	UserID         int      `json:"user_id"`
	JobLimit       int      `json:"job_limit"`
	JobStatuses    []string `json:"job_statuses"`
	TimeoutSeconds int      `json:"timeout_seconds"`
}

type matchResultItem struct {
	JobID         string             `json:"job_id"`
	Matched       bool               `json:"matched"`
	Compatibility float64            `json:"compatibility"`
	Reason        string             `json:"reason"`
	Strengths     []string           `json:"strengths"`
	Gaps          []string           `json:"gaps"`
	FactorScores  map[string]float64 `json:"factor_scores"`
}

type runResponse struct {
	RequestID        string            `json:"request_id"`
	CreditsRemaining int               `json:"credits_remaining"`
	Matches          []matchResultItem `json:"matches"`
}

func run(w http.ResponseWriter, r *http.Request) {
	if !flags.IsEnabled("matching") {
		metrics.Increment("feature_blocked")
		httpx.WriteError(w, http.StatusServiceUnavailable,
			"Job matching is temporarily disabled.", httpx.CRV1008)
		return
	}

	if strings.TrimSpace(config.S.OpenAIAPIKey) == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable,
			"Matching not configured (missing API key).", httpx.CRV3001)
		return
	}

	var body runRequest
	if err := httpx.Decode(r, &body); err != nil || body.UserID < 1 {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	statuses := body.JobStatuses
	if len(statuses) == 0 {
		statuses = []string{"open", "priority"}
	}

	var user models.User
	if err := db.DB.Where("id = ? AND is_active = ?", body.UserID, true).First(&user).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "User not found", httpx.CRV1005)
		return
	}

	var jobs []models.Job
	if err := db.DB.Where("status IN ?", statuses).Order("created_at DESC").Find(&jobs).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Query failed", httpx.CRV1002)
		return
	}
	if len(jobs) == 0 {
		httpx.WriteError(w, http.StatusNotFound, "No jobs found", httpx.CRV1005)
		return
	}

	// Spend one token up front; refund on engine error.
	if err := credits.Spend(db.DB, user.Email, 1); err != nil {
		httpx.WriteError(w, http.StatusPaymentRequired,
			"User does not have enough credits to run matching.", httpx.CRV1004)
		return
	}
	creditsRemaining := credits.GetBalance(db.DB, user.Email)

	userKey := fmt.Sprintf("%d", user.ID)

	var profile models.CrewProfile
	hasProfile := db.DB.Where("user_key = ?", userKey).First(&profile).Error == nil

	var history []models.JobHistoryEntry
	if hasProfile {
		db.DB.Where("user_key = ?", userKey).Order("start_date DESC").Limit(10).Find(&history)
	}

	var docs []models.Document
	db.DB.Where("user_key = ? AND scanned_text IS NOT NULL", userKey).Find(&docs)
	var docParts []string
	for _, d := range docs {
		if d.ScannedText != nil && *d.ScannedText != "" {
			docParts = append(docParts, "["+strings.ToUpper(d.DocType)+"] "+*d.ScannedText)
		}
	}
	docSummary := strings.Join(docParts, "\n\n")

	candidate := userToCandidate(user, hasProfile, profile, history, docSummary)
	summaries := make([]matchengine.JobSummary, 0, len(jobs))
	for _, j := range jobs {
		summaries = append(summaries, jobToSummary(j))
	}

	t0 := time.Now()
	results := matchengine.MatchCandidateToJobs(r.Context(), config.S.OpenAIModel, candidate, summaries, 0, nil)
	metrics.RecordAIResponseTime(int(time.Since(t0).Milliseconds()))

	metrics.Increment("matching_completed")

	items := make([]matchResultItem, 0, len(results))
	for _, res := range results {
		strengths := res.Strengths
		if strengths == nil {
			strengths = []string{}
		}
		gaps := res.Gaps
		if gaps == nil {
			gaps = []string{}
		}
		fs := res.FactorScores
		if fs == nil {
			fs = map[string]float64{}
		}
		items = append(items, matchResultItem{
			JobID:         fmt.Sprintf("%d", res.JobID),
			Matched:       res.Matched,
			Compatibility: res.Compatibility,
			Reason:        res.Reason,
			Strengths:     strengths,
			Gaps:          gaps,
			FactorScores:  fs,
		})
	}

	httpx.JSON(w, http.StatusOK, runResponse{
		RequestID:        fmt.Sprintf("match-%d-%d", body.UserID, time.Now().Unix()),
		CreditsRemaining: creditsRemaining,
		Matches:          items,
	})
}

// userToCandidate ports _user_to_candidate.
func userToCandidate(user models.User, hasProfile bool, profile models.CrewProfile, history []models.JobHistoryEntry, docSummary string) matchengine.CandidateProfile {
	var certs, langs []string
	var bio string
	if hasProfile {
		if profile.Certifications != nil {
			for _, c := range strings.Split(strings.ReplaceAll(*profile.Certifications, "\n", ","), ",") {
				if c = strings.TrimSpace(c); c != "" {
					certs = append(certs, c)
				}
			}
		}
		if profile.Languages != nil {
			for _, l := range strings.Split(*profile.Languages, ",") {
				if l = strings.TrimSpace(l); l != "" {
					langs = append(langs, l)
				}
			}
		}
		bio = deref(profile.Bio)
	}

	hist := make([]map[string]string, 0, len(history))
	for _, e := range history {
		hist = append(hist, map[string]string{
			"role":        e.Role,
			"yacht":       e.YachtName,
			"yacht_type":  deref(e.YachtType),
			"start_date":  deref(e.StartDate),
			"end_date":    deref(e.EndDate),
			"description": clip(deref(e.Description), 200),
		})
	}

	firstName, lastName := splitName(user.FullName)
	desiredRole := user.Role
	location := deref(user.CurrentLocation)
	nationality := deref(user.Nationality)
	yearsExp := ""
	if user.YearsExperience != nil {
		yearsExp = fmt.Sprintf("%d", *user.YearsExperience)
	}

	if hasProfile {
		if v := deref(profile.FirstName); v != "" {
			firstName = v
		}
		if v := deref(profile.LastName); v != "" {
			lastName = v
		}
		if v := deref(profile.DesiredRole); v != "" {
			desiredRole = v
		}
		if v := deref(profile.CurrentLocation); v != "" {
			location = v
		}
		if v := deref(profile.Nationality); v != "" {
			nationality = v
		}
		if v := deref(profile.YearsExperience); v != "" {
			yearsExp = v
		}
	}

	c := matchengine.CandidateProfile{
		UserKey:         fmt.Sprintf("%d", user.ID),
		FirstName:       firstName,
		LastName:        lastName,
		DesiredRole:     desiredRole,
		Location:        location,
		Nationality:     nationality,
		YearsExperience: yearsExp,
		Certifications:  certs,
		Languages:       langs,
		Bio:             bio,
		JobHistory:      hist,
		DocumentSummary: docSummary,
	}
	if hasProfile {
		c.Sex = deref(profile.Sex)
		c.PreferredLocations = deref(profile.PreferredLocations)
		c.SalaryMin = deref(profile.SalaryMin)
		c.SalaryMax = deref(profile.SalaryMax)
		c.ContractType = deref(profile.ContractType)
		c.RotationPreference = deref(profile.RotationPreference)
		c.AvailableFrom = deref(profile.AvailableFrom)
	}
	return c
}

// jobToSummary ports _job_to_summary.
func jobToSummary(j models.Job) matchengine.JobSummary {
	currency := "EUR"
	if j.SalaryCurrency != nil && *j.SalaryCurrency != "" {
		currency = *j.SalaryCurrency
	}
	status := j.Status
	if status == "" {
		status = "open"
	}
	return matchengine.JobSummary{
		JobID:                   j.ID,
		Title:                   j.Title,
		Role:                    j.Role,
		Department:              deref(j.Department),
		Location:                j.Location,
		YachtType:               deref(j.YachtType),
		YachtLengthM:            j.YachtLengthM,
		StartDate:               deref(j.StartDate),
		ContractType:            deref(j.ContractType),
		Rotation:                deref(j.Rotation),
		Season:                  deref(j.Season),
		SalaryMin:               j.SalaryMin,
		SalaryMax:               j.SalaryMax,
		SalaryCurrency:          currency,
		ExperienceRequiredYears: j.ExperienceRequiredYears,
		CertificationsRequired:  deref(j.CertificationsRequired),
		LanguagesRequired:       deref(j.LanguagesRequired),
		Description:             deref(j.Description),
		Status:                  status,
	}
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func clip(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func splitName(full string) (string, string) {
	full = strings.TrimSpace(full)
	if full == "" {
		return "", ""
	}
	parts := strings.Fields(full)
	if len(parts) == 1 {
		return parts[0], ""
	}
	return parts[0], strings.Join(parts[1:], " ")
}
