// Package jobsubmit ports api/app/routes/job_submit.py — user-facing job
// submission (crew/agency/admin). The text and image flows depend on the AI
// import pipeline (out of scope here) and are stubbed; the guided /form flow has
// no AI and is ported fully, including dedupe and the free-token-on-post loop.
package jobsubmit

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/config"
	"jobcarver/internal/credits"
	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/metrics"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

// Register mounts /jobs/submit. text/image/form need a poster session
// (crew/agency/admin); /mine needs agency-or-admin.
func Register(r chi.Router) {
	r.Route("/jobs/submit", func(r chi.Router) {
		r.Use(security.RequireSession)
		r.With(requireRoles("crew", "agency", "admin")).Post("/text", submitText)
		r.With(requireRoles("crew", "agency", "admin")).Post("/image", submitImage)
		r.With(requireRoles("crew", "agency", "admin")).Post("/form", submitForm)
		r.With(requireRoles("agency", "admin")).Get("/mine", listMine)
	})
}

func requireRoles(roles ...string) func(http.Handler) http.Handler {
	allowed := map[string]bool{}
	for _, r := range roles {
		allowed[r] = true
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			sess := security.SessionFromContext(r.Context())
			if sess == nil || !allowed[sess.Role] {
				httpx.WriteError(w, http.StatusForbidden, "You do not have access to this feature.", httpx.CRV2005)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// posterMeta ports _poster_meta: resolve (userID, agencyName) for the session.
// Admins pass through with userID 0 so their actions stay out of agency listings.
func posterMeta(sess *security.Session) (int, *string) {
	var agencyName *string
	if sess.Role == "agency" && sess.UserID != 0 {
		var user models.User
		if err := db.DB.Select("agency_name").Where("id = ?", sess.UserID).First(&user).Error; err == nil {
			agencyName = user.AgencyName
		}
	}
	userID := 0
	if sess.Role == "crew" || sess.Role == "agency" {
		userID = sess.UserID
	}
	return userID, agencyName
}

func submitText(w http.ResponseWriter, _ *http.Request) {
	// TODO(go-port): ports the AI import pipeline (_run_import_pipeline →
	// ai_job_reviewer.review_post). AI is out of scope for the Go port.
	aiStub(w)
}

func submitImage(w http.ResponseWriter, _ *http.Request) {
	// TODO(go-port): ports the vision review pipeline (review_job_images). AI is
	// out of scope for the Go port.
	aiStub(w)
}

func aiStub(w http.ResponseWriter) {
	if config.S.OpenAIAPIKey == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable, "OPENAI_API_KEY is not configured.", httpx.CRV3001)
		return
	}
	httpx.WriteError(w, http.StatusNotImplemented,
		"AI job import is not implemented in the Go port yet.", httpx.CRV3001)
}

// formRequest ports schemas.AgencyJobFormRequest.
type formRequest struct {
	Title                   string   `json:"title"`
	Role                    string   `json:"role"`
	Yacht                   string   `json:"yacht"`
	Location                string   `json:"location"`
	YachtType               *string  `json:"yacht_type"`
	YachtLengthM            *int     `json:"yacht_length_m"`
	Department              *string  `json:"department"`
	RankLevel               *string  `json:"rank_level"`
	StartDate               *string  `json:"start_date"`
	ContractType            *string  `json:"contract_type"`
	Rotation                *string  `json:"rotation"`
	Season                  *string  `json:"season"`
	SalaryCurrency          *string  `json:"salary_currency"`
	SalaryMin               *float64 `json:"salary_min"`
	SalaryMax               *float64 `json:"salary_max"`
	VisaSupport             bool     `json:"visa_support"`
	Accommodation           *string  `json:"accommodation"`
	TravelReimbursement     bool     `json:"travel_reimbursement"`
	ExperienceRequiredYears *int     `json:"experience_required_years"`
	MinimumLicense          *string  `json:"minimum_license"`
	CertificationsRequired  *string  `json:"certifications_required"`
	LanguagesRequired       *string  `json:"languages_required"`
	Description             *string  `json:"description"`
	Responsibilities        *string  `json:"responsibilities"`
	Requirements            *string  `json:"requirements"`
	Benefits                *string  `json:"benefits"`
	ContactEmail            *string  `json:"contact_email"`
	ApplicationURL          *string  `json:"application_url"`
	UrgentHire              bool     `json:"urgent_hire"`
}

func submitForm(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())

	var body formRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if strings.TrimSpace(body.Title) == "" || strings.TrimSpace(body.Role) == "" ||
		strings.TrimSpace(body.Yacht) == "" || strings.TrimSpace(body.Location) == "" {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "title, role, yacht and location are required.", httpx.CRV1003)
		return
	}

	userID, agencyName := posterMeta(sess)
	isAgency := sess.Role == "agency"

	currency := body.SalaryCurrency
	if currency == nil {
		currency = strPtr("EUR")
	}
	source := "website_form"
	if isAgency {
		source = "agency_form"
	}

	job := models.Job{
		Title:                   body.Title,
		Role:                    body.Role,
		Yacht:                   body.Yacht,
		Location:                body.Location,
		YachtType:               body.YachtType,
		YachtLengthM:            body.YachtLengthM,
		Department:              body.Department,
		RankLevel:               body.RankLevel,
		StartDate:               body.StartDate,
		ContractType:            body.ContractType,
		Rotation:                body.Rotation,
		Season:                  body.Season,
		SalaryCurrency:          currency,
		SalaryMin:               body.SalaryMin,
		SalaryMax:               body.SalaryMax,
		VisaSupport:             body.VisaSupport,
		Accommodation:           body.Accommodation,
		TravelReimbursement:     body.TravelReimbursement,
		ExperienceRequiredYears: body.ExperienceRequiredYears,
		MinimumLicense:          body.MinimumLicense,
		CertificationsRequired:  body.CertificationsRequired,
		LanguagesRequired:       body.LanguagesRequired,
		Description:             body.Description,
		Responsibilities:        body.Responsibilities,
		Requirements:            body.Requirements,
		Benefits:                body.Benefits,
		ContactEmail:            body.ContactEmail,
		ApplicationURL:          body.ApplicationURL,
		UrgentHire:              body.UrgentHire,
		Status:                  "open",
		Source:                  &source,
		AutoApplyEnabled:        false,
	}
	if userID != 0 {
		job.PostedByUserID = &userID
	}
	if agencyName != nil && *agencyName != "" {
		job.PostedByAgency = agencyName
		if job.RecruiterAgency == nil {
			job.RecruiterAgency = agencyName
		}
	}

	// Dedupe fingerprints (mirror crew_submit_form).
	textForHash := strings.Join([]string{
		strings.ToLower(strings.TrimSpace(job.Title)),
		strings.ToLower(strings.TrimSpace(job.Role)),
		strings.ToLower(strings.TrimSpace(job.Yacht)),
		strings.ToLower(strings.TrimSpace(job.Location)),
		strings.ToLower(strings.TrimSpace(deref(job.Description))),
	}, "|")
	if strings.Trim(textForHash, "|") != "" {
		h := contentHash(textForHash)
		job.ContentHash = &h
	}
	if fp := jobFingerprint(job.Role, job.Location, deref(job.StartDate)); fp != "" {
		job.JobFingerprint = &fp
	}

	if job.ContentHash != nil {
		if id, ok := existingJobID("content_hash = ?", *job.ContentHash); ok {
			conflict(w, id)
			return
		}
	}
	if job.JobFingerprint != nil {
		if id, ok := existingJobID("job_fingerprint = ?", *job.JobFingerprint); ok {
			conflict(w, id)
			return
		}
	}

	if err := db.DB.Create(&job).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not save job.", httpx.CRV1002)
		return
	}

	newBal := 0
	if sess.Role == "crew" {
		_, newBal, _ = credits.AwardJobPostCredit(db.DB, sess.Sub)
	}
	metrics.Increment("manual_job_imports")

	out := shapeImportResponse(job)
	out["credits_balance"] = newBal
	httpx.JSON(w, http.StatusCreated, out)
}

func listMine(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userID := sess.UserID
	if userID == 0 {
		httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "jobs": []any{}})
		return
	}

	var rows []models.Job
	db.DB.Where("posted_by_user_id = ?", userID).Order("created_at desc").Limit(200).Find(&rows)

	jobIDs := make([]int, 0, len(rows))
	for _, j := range rows {
		jobIDs = append(jobIDs, j.ID)
	}

	matches := map[int]int{}
	drafts := map[int]int{}
	if len(jobIDs) > 0 {
		type countRow struct {
			JobID int
			Cnt   int
		}
		var matchRows []countRow
		db.DB.Table("match_session_results AS r").
			Select("r.job_id AS job_id, COUNT(DISTINCT s.user_key) AS cnt").
			Joins("JOIN match_sessions AS s ON s.id = r.session_id").
			Where("r.job_id IN ? AND r.matched = ?", jobIDs, true).
			Group("r.job_id").
			Scan(&matchRows)
		for _, m := range matchRows {
			matches[m.JobID] = m.Cnt
		}

		var draftRows []countRow
		db.DB.Table("job_drafts").
			Select("job_id, COUNT(DISTINCT user_key) AS cnt").
			Where("job_id IN ?", jobIDs).
			Group("job_id").
			Scan(&draftRows)
		for _, d := range draftRows {
			drafts[d.JobID] = d.Cnt
		}
	}

	jobs := make([]map[string]any, 0, len(rows))
	for _, j := range rows {
		var createdAt any
		if !j.CreatedAt.IsZero() {
			createdAt = j.CreatedAt.Format(time.RFC3339)
		}
		jobs = append(jobs, map[string]any{
			"id":          j.ID,
			"title":       j.Title,
			"role":        j.Role,
			"yacht":       j.Yacht,
			"location":    j.Location,
			"status":      j.Status,
			"source":      j.Source,
			"created_at":  createdAt,
			"match_count": matches[j.ID],
			"draft_count": drafts[j.ID],
		})
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "jobs": jobs})
}

func shapeImportResponse(j models.Job) map[string]any {
	return map[string]any{
		"ok":       true,
		"id":       j.ID,
		"title":    j.Title,
		"role":     j.Role,
		"location": j.Location,
		"source":   j.Source,
	}
}

func existingJobID(where string, arg any) (int, bool) {
	var job models.Job
	if err := db.DB.Select("id").Where(where, arg).First(&job).Error; err != nil {
		return 0, false
	}
	return job.ID, true
}

func conflict(w http.ResponseWriter, id int) {
	httpx.WriteError(w, http.StatusConflict,
		"This job is already on the board (id="+strconv.Itoa(id)+").", httpx.CRV1005)
}

// contentHash ports job_sync._content_hash: SHA-256 of whitespace-normalised text.
func contentHash(text string) string {
	normalised := strings.Join(strings.Fields(text), " ")
	sum := sha256.Sum256([]byte(normalised))
	return hex.EncodeToString(sum[:])
}

// jobFingerprint ports job_sync._job_fingerprint: SHA-256 of role|location|start.
// Returns "" when both role and location are empty.
func jobFingerprint(role, location, startDate string) string {
	r := strings.ToLower(strings.TrimSpace(role))
	l := strings.ToLower(strings.TrimSpace(location))
	d := strings.ToLower(strings.TrimSpace(startDate))
	if r == "" && l == "" {
		return ""
	}
	sum := sha256.Sum256([]byte(r + "|" + l + "|" + d))
	return hex.EncodeToString(sum[:])
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func strPtr(s string) *string { return &s }
