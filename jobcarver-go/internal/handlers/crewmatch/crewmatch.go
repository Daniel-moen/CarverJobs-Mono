// Package crewmatch ports api/app/routes/crew_match.py: the crew-facing matching
// flow (run a match session with live SSE progress, list/inspect past sessions)
// plus AI application-email drafting.
//
// The match scoring and email drafting both run through internal/ai (stubbed),
// but the token spend, MatchSession/MatchSessionResult persistence and
// JobDraftEvent recording are all real. The Python /find endpoint streams
// progress over Server-Sent Events while a background task runs; this port runs
// the match synchronously and streams the same SSE event shapes (initial
// progress, per-batch progress via the engine callback, then a final complete
// event). TODO(go-port): wire internal/ai to real OpenAI so matches/drafts are real.
package crewmatch

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/ai"
	"jobcarver/internal/config"
	"jobcarver/internal/credits"
	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	matchengine "jobcarver/internal/matching"
	"jobcarver/internal/metrics"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

const matchRunTimeoutSeconds = 600

// Register mounts the crew matching routes under the shared /matching prefix.
// Uses r.Group (not r.Route) because the /matching prefix is shared with the
// admin matching handler.
func Register(r chi.Router) {
	r.Group(func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Post("/matching/find", find)
		r.Get("/matching/sessions", listSessions)
		r.Get("/matching/sessions/{sessionID}", getSession)
		r.Post("/matching/draft-email", draftEmail)
	})
}

// ── DTOs (port of the crew-match schemas) ────────────────────────────────────

type crewMatchJob struct {
	ID                      int      `json:"id"`
	Title                   string   `json:"title"`
	Role                    string   `json:"role"`
	Yacht                   string   `json:"yacht"`
	Location                string   `json:"location"`
	ContractType            *string  `json:"contract_type"`
	SalaryMin               *float64 `json:"salary_min"`
	SalaryMax               *float64 `json:"salary_max"`
	SalaryCurrency          *string  `json:"salary_currency"`
	ContactEmail            *string  `json:"contact_email"`
	Description             *string  `json:"description"`
	YachtType               *string  `json:"yacht_type"`
	YachtLengthM            *int     `json:"yacht_length_m"`
	StartDate               *string  `json:"start_date"`
	Season                  *string  `json:"season"`
	Rotation                *string  `json:"rotation"`
	ExperienceRequiredYears *int     `json:"experience_required_years"`
	CertificationsRequired  *string  `json:"certifications_required"`
	LanguagesRequired       *string  `json:"languages_required"`
	Requirements            *string  `json:"requirements"`
	Responsibilities        *string  `json:"responsibilities"`
	Benefits                *string  `json:"benefits"`
	RecruiterName           *string  `json:"recruiter_name"`
	RecruiterAgency         *string  `json:"recruiter_agency"`
	ApplicationURL          *string  `json:"application_url"`
	UrgentHire              bool     `json:"urgent_hire"`
	Source                  *string  `json:"source"`
}

type matchSessionResultItem struct {
	Job           crewMatchJob       `json:"job"`
	Matched       bool               `json:"matched"`
	Compatibility float64            `json:"compatibility"`
	Reason        string             `json:"reason"`
	Strengths     []string           `json:"strengths"`
	Gaps          []string           `json:"gaps"`
	FactorScores  map[string]float64 `json:"factor_scores"`
}

type crewMatchV2Response struct {
	SessionID        int                      `json:"session_id"`
	Matched          bool                     `json:"matched"`
	TotalJobsScanned int                      `json:"total_jobs_scanned"`
	TotalMatched     int                      `json:"total_matched"`
	CreditsRemaining int                      `json:"credits_remaining"`
	Matches          []matchSessionResultItem `json:"matches"`
}

type matchSessionSummary struct {
	ID               int        `json:"id"`
	Status           string     `json:"status"`
	TotalJobsScanned int        `json:"total_jobs_scanned"`
	TotalMatched     int        `json:"total_matched"`
	CreatedAt        time.Time  `json:"created_at"`
	CompletedAt      *time.Time `json:"completed_at"`
}

// ── /matching/find (SSE) ─────────────────────────────────────────────────────

func find(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub

	if strings.TrimSpace(config.S.OpenAIAPIKey) == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable,
			"Matching not configured (missing API key).", httpx.CRV3001)
		return
	}

	var profile models.CrewProfile
	if db.DB.Where("user_key = ?", userKey).First(&profile).Error != nil {
		httpx.WriteError(w, http.StatusBadRequest, "Save your profile first before matching.", httpx.CRV1003)
		return
	}

	var jobs []models.Job
	db.DB.Where("status IN ?", []string{"open", "priority"}).Order("created_at DESC").Find(&jobs)

	flusher, ok := w.(http.Flusher)
	if !ok {
		httpx.WriteError(w, http.StatusInternalServerError, "Streaming unsupported.", httpx.CRV1006)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")

	if len(jobs) == 0 {
		writeSSE(w, flusher, "complete", mustJSON(map[string]any{
			"session_id":         0,
			"matched":            false,
			"total_jobs_scanned": 0,
			"total_matched":      0,
			"credits_remaining":  credits.GetBalance(db.DB, userKey),
			"matches":            []any{},
		}))
		return
	}

	if err := credits.Spend(db.DB, userKey, 1); err != nil {
		// SSE already not started for this branch; send a normal error.
		httpx.WriteError(w, http.StatusPaymentRequired,
			"You're out of tokens. Top up to keep matching, or submit a job to earn a free token.", httpx.CRV1004)
		return
	}
	creditsRemaining := credits.GetBalance(db.DB, userKey)

	deleteUserMatchSessions(userKey)

	matchSession := models.MatchSession{UserKey: userKey, Status: "running", TotalJobsScanned: len(jobs)}
	db.DB.Create(&matchSession)
	sessionID := matchSession.ID

	var history []models.JobHistoryEntry
	db.DB.Where("user_key = ?", userKey).Order("start_date DESC").Limit(10).Find(&history)
	docSummary := getDocumentSummary(userKey)
	candidate := profileToCandidate(profile, history, docSummary)

	summaries := make([]matchengine.JobSummary, 0, len(jobs))
	jobsByID := make(map[int]models.Job, len(jobs))
	for _, j := range jobs {
		summaries = append(summaries, jobToSummary(j))
		jobsByID[j.ID] = j
	}
	totalJobs := len(jobs)
	totalBatches := (totalJobs + matchengine.BatchSize - 1) / matchengine.BatchSize

	// Initial progress event.
	writeSSE(w, flusher, "progress", mustJSON(map[string]any{
		"session_id": sessionID, "jobs_scanned": 0, "total_jobs": totalJobs,
		"matches_so_far": 0, "batch": 0, "total_batches": totalBatches,
	}))

	onProgress := func(jobsScanned, total, matchesSoFar, batchNum, totalB int) {
		writeSSE(w, flusher, "progress", mustJSON(map[string]any{
			"session_id": sessionID, "jobs_scanned": jobsScanned, "total_jobs": total,
			"matches_so_far": matchesSoFar, "batch": batchNum, "total_batches": totalB,
		}))
	}

	t0 := time.Now()
	results := matchengine.MatchCandidateToJobs(r.Context(), config.S.OpenAIModel, candidate, summaries, 0, onProgress)
	metrics.RecordAIResponseTime(int(time.Since(t0).Milliseconds()))

	var matched []matchengine.MatchResult
	for _, res := range results {
		if res.Matched {
			matched = append(matched, res)
		}
	}

	// Persist results + finalise session.
	if err := persistResults(sessionID, matched); err != nil {
		db.DB.Model(&models.MatchSession{}).Where("id = ?", sessionID).Update("status", "failed")
		_ = credits.Grant(db.DB, userKey, 1)
		writeSSE(w, flusher, "error", mustJSON(map[string]any{
			"detail": "Matching finished but results could not be saved. Please try again.",
		}))
		return
	}
	now := time.Now().UTC()
	db.DB.Model(&models.MatchSession{}).Where("id = ?", sessionID).
		Updates(map[string]any{"status": "completed", "total_matched": len(matched), "completed_at": now})

	metrics.Increment("crew_matches")

	items := make([]matchSessionResultItem, 0, len(matched))
	for _, res := range matched {
		job, ok := jobsByID[res.JobID]
		if !ok {
			continue
		}
		items = append(items, matchSessionResultItem{
			Job:           jobToSchema(job),
			Matched:       res.Matched,
			Compatibility: res.Compatibility,
			Reason:        res.Reason,
			Strengths:     orEmpty(res.Strengths),
			Gaps:          orEmpty(res.Gaps),
			FactorScores:  orEmptyMap(res.FactorScores),
		})
	}

	final := crewMatchV2Response{
		SessionID:        sessionID,
		Matched:          len(items) > 0,
		TotalJobsScanned: totalJobs,
		TotalMatched:     len(matched),
		CreditsRemaining: creditsRemaining,
		Matches:          items,
	}
	writeSSE(w, flusher, "complete", mustJSON(final))
}

func persistResults(sessionID int, matched []matchengine.MatchResult) error {
	for _, r := range matched {
		strengths, _ := json.Marshal(orEmpty(r.Strengths))
		gaps, _ := json.Marshal(orEmpty(r.Gaps))
		fs, _ := json.Marshal(orEmptyMap(r.FactorScores))
		reason := r.Reason
		ss := string(strengths)
		gs := string(gaps)
		fss := string(fs)
		row := models.MatchSessionResult{
			SessionID:     sessionID,
			JobID:         r.JobID,
			Matched:       r.Matched,
			Compatibility: r.Compatibility,
			Reason:        &reason,
			Strengths:     &ss,
			Gaps:          &gs,
			FactorScores:  &fss,
		}
		if err := db.DB.Create(&row).Error; err != nil {
			return err
		}
	}
	return nil
}

// ── /matching/sessions ───────────────────────────────────────────────────────

func listSessions(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub
	expireStaleRunningSessions(userKey)

	var sessions []models.MatchSession
	db.DB.Where("user_key = ?", userKey).Order("id DESC").Limit(50).Find(&sessions)

	out := make([]matchSessionSummary, 0, len(sessions))
	for _, s := range sessions {
		out = append(out, matchSessionSummary{
			ID: s.ID, Status: s.Status, TotalJobsScanned: s.TotalJobsScanned,
			TotalMatched: s.TotalMatched, CreatedAt: s.CreatedAt, CompletedAt: s.CompletedAt,
		})
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"sessions": out})
}

func getSession(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub
	sessionID, err := strconv.Atoi(chi.URLParam(r, "sessionID"))
	if err != nil {
		httpx.WriteError(w, http.StatusNotFound, "Session not found.", httpx.CRV1005)
		return
	}

	var ms models.MatchSession
	if db.DB.Where("id = ? AND user_key = ?", sessionID, userKey).First(&ms).Error != nil {
		httpx.WriteError(w, http.StatusNotFound, "Session not found.", httpx.CRV1005)
		return
	}
	if ms.Status == "running" {
		cutoff := time.Now().UTC().Add(-matchRunTimeoutSeconds * time.Second)
		if ms.CreatedAt.UTC().Before(cutoff) || ms.CreatedAt.UTC().Equal(cutoff) {
			ms.Status = "failed"
			db.DB.Model(&models.MatchSession{}).Where("id = ?", ms.ID).Update("status", "failed")
			_ = credits.Grant(db.DB, userKey, 1)
		}
	}

	var stored []models.MatchSessionResult
	db.DB.Where("session_id = ?", sessionID).Find(&stored)

	jobIDs := make([]int, 0, len(stored))
	for _, s := range stored {
		jobIDs = append(jobIDs, s.JobID)
	}
	jobsMap := map[int]models.Job{}
	if len(jobIDs) > 0 {
		var jobs []models.Job
		db.DB.Where("id IN ?", jobIDs).Find(&jobs)
		for _, j := range jobs {
			jobsMap[j.ID] = j
		}
	}

	items := make([]matchSessionResultItem, 0, len(stored))
	for _, s := range stored {
		job, ok := jobsMap[s.JobID]
		if !ok {
			continue
		}
		items = append(items, matchSessionResultItem{
			Job:           jobToSchema(job),
			Matched:       s.Matched,
			Compatibility: s.Compatibility,
			Reason:        derefStr(s.Reason),
			Strengths:     decodeStrList(s.Strengths),
			Gaps:          decodeStrList(s.Gaps),
			FactorScores:  decodeFloatMap(s.FactorScores),
		})
	}
	sort.SliceStable(items, func(i, j int) bool { return items[i].Compatibility > items[j].Compatibility })

	httpx.JSON(w, http.StatusOK, map[string]any{
		"id":                 ms.ID,
		"status":             ms.Status,
		"total_jobs_scanned": ms.TotalJobsScanned,
		"total_matched":      ms.TotalMatched,
		"created_at":         ms.CreatedAt,
		"completed_at":       ms.CompletedAt,
		"results":            items,
	})
}

// ── /matching/draft-email ────────────────────────────────────────────────────

type draftEmailRequest struct {
	JobID        int     `json:"job_id"`
	Prompt       *string `json:"prompt"`
	PreviousBody *string `json:"previous_body"`
}

func draftEmail(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub

	if strings.TrimSpace(config.S.OpenAIAPIKey) == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable, "AI drafting not configured.", httpx.CRV3001)
		return
	}
	var body draftEmailRequest
	if err := httpx.Decode(r, &body); err != nil || body.JobID < 1 {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}

	var profile models.CrewProfile
	if db.DB.Where("user_key = ?", userKey).First(&profile).Error != nil {
		httpx.WriteError(w, http.StatusBadRequest, "Save your profile first.", httpx.CRV1003)
		return
	}
	var job models.Job
	if db.DB.Where("id = ?", body.JobID).First(&job).Error != nil {
		httpx.WriteError(w, http.StatusNotFound, "Job not found.", httpx.CRV1005)
		return
	}

	profileURL := ""
	if profile.ProfileSlug != "" {
		profileURL = config.S.FrontendBaseURL + "/crew/" + profile.ProfileSlug
	}
	firstName := "the applicant"
	if profile.FirstName != nil && *profile.FirstName != "" {
		firstName = *profile.FirstName
	}

	var history []models.JobHistoryEntry
	db.DB.Where("user_key = ?", userKey).Order("start_date DESC").Limit(5).Find(&history)
	docSummary := getDocumentSummary(userKey)
	profileText := profileSummary(profile, history, docSummary)

	systemPrompt := buildDraftSystemPrompt(firstName, profileText, job, profileURL)
	messages := []ai.Message{{Role: "system", Content: systemPrompt}}
	switch {
	case body.Prompt != nil && body.PreviousBody != nil:
		prev, _ := json.Marshal(map[string]string{"subject": "", "body": *body.PreviousBody})
		messages = append(messages,
			ai.Message{Role: "assistant", Content: string(prev)},
			ai.Message{Role: "user", Content: "Revise the email with this instruction (keep the same strict rules — don't invent facts): " + *body.Prompt})
	case body.Prompt != nil:
		messages = append(messages, ai.Message{Role: "user", Content: "Write the email. Extra instruction: " + *body.Prompt})
	default:
		messages = append(messages, ai.Message{Role: "user", Content: "Write the email."})
	}

	t0 := time.Now()
	text, err := ai.Chat(r.Context(), config.S.EmailAIModel, messages, ai.Options{
		MaxTokens: 400, Temperature: 0.7, JSONResponse: true,
	})
	metrics.RecordAIResponseTime(int(time.Since(t0).Milliseconds()))
	if err != nil || strings.TrimSpace(text) == "" {
		httpx.WriteError(w, http.StatusBadGateway, "Could not draft email. Try again.", httpx.CRV3006)
		return
	}

	subject, draftBody := parseDraft(text)
	if draftBody == "" {
		httpx.WriteError(w, http.StatusBadGateway, "AI returned an empty draft.", httpx.CRV3006)
		return
	}

	// Record engagement signal (unique on job_id+user_key); never block on it.
	var existing int64
	db.DB.Model(&models.JobDraftEvent{}).
		Where("job_id = ? AND user_key = ?", job.ID, userKey).Count(&existing)
	if existing == 0 {
		db.DB.Create(&models.JobDraftEvent{JobID: job.ID, UserKey: userKey})
	}

	to := ""
	if job.ContactEmail != nil {
		to = *job.ContactEmail
	}
	if subject == "" {
		subject = fmt.Sprintf("Application: %s - %s", job.Role, job.Yacht)
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"to": to, "subject": subject, "body": draftBody})
}

// ── helpers ──────────────────────────────────────────────────────────────────

func deleteUserMatchSessions(userKey string) {
	var ids []int
	db.DB.Model(&models.MatchSession{}).Where("user_key = ?", userKey).Pluck("id", &ids)
	if len(ids) == 0 {
		return
	}
	db.DB.Where("session_id IN ?", ids).Delete(&models.MatchSessionResult{})
	db.DB.Where("id IN ?", ids).Delete(&models.MatchSession{})
}

func expireStaleRunningSessions(userKey string) {
	cutoff := time.Now().UTC().Add(-matchRunTimeoutSeconds * time.Second)
	var stale []models.MatchSession
	db.DB.Where("user_key = ? AND status = ?", userKey, "running").Find(&stale)
	for _, s := range stale {
		if s.CreatedAt.UTC().After(cutoff) {
			continue
		}
		db.DB.Model(&models.MatchSession{}).Where("id = ?", s.ID).Update("status", "failed")
		_ = credits.Grant(db.DB, userKey, 1)
	}
}

func getDocumentSummary(userKey string) string {
	var docs []models.Document
	db.DB.Where("user_key = ? AND scanned_text IS NOT NULL", userKey).Find(&docs)
	var parts []string
	for _, d := range docs {
		if d.ScannedText != nil && *d.ScannedText != "" {
			parts = append(parts, "["+strings.ToUpper(d.DocType)+"] "+*d.ScannedText)
		}
	}
	return strings.Join(parts, "\n\n")
}

func profileToCandidate(p models.CrewProfile, history []models.JobHistoryEntry, docSummary string) matchengine.CandidateProfile {
	var certs, langs []string
	if p.Certifications != nil {
		for _, c := range strings.Split(strings.ReplaceAll(*p.Certifications, "\n", ","), ",") {
			if c = strings.TrimSpace(c); c != "" {
				certs = append(certs, c)
			}
		}
	}
	if p.Languages != nil {
		for _, l := range strings.Split(*p.Languages, ",") {
			if l = strings.TrimSpace(l); l != "" {
				langs = append(langs, l)
			}
		}
	}
	hist := make([]map[string]string, 0, len(history))
	for _, e := range history {
		hist = append(hist, map[string]string{
			"role": e.Role, "yacht": e.YachtName, "yacht_type": derefStr(e.YachtType),
			"start_date": derefStr(e.StartDate), "end_date": derefStr(e.EndDate),
			"description": clip(derefStr(e.Description), 200),
		})
	}
	return matchengine.CandidateProfile{
		UserKey:            p.UserKey,
		FirstName:          derefStr(p.FirstName),
		LastName:           derefStr(p.LastName),
		Sex:                derefStr(p.Sex),
		DesiredRole:        derefStr(p.DesiredRole),
		Location:           derefStr(p.CurrentLocation),
		PreferredLocations: derefStr(p.PreferredLocations),
		Nationality:        derefStr(p.Nationality),
		YearsExperience:    derefStr(p.YearsExperience),
		SalaryMin:          derefStr(p.SalaryMin),
		SalaryMax:          derefStr(p.SalaryMax),
		ContractType:       derefStr(p.ContractType),
		RotationPreference: derefStr(p.RotationPreference),
		AvailableFrom:      derefStr(p.AvailableFrom),
		Certifications:     certs,
		Languages:          langs,
		Bio:                derefStr(p.Bio),
		JobHistory:         hist,
		DocumentSummary:    docSummary,
	}
}

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
		JobID: j.ID, Title: j.Title, Role: j.Role, Department: derefStr(j.Department),
		Location: j.Location, YachtType: derefStr(j.YachtType), YachtLengthM: j.YachtLengthM,
		StartDate: derefStr(j.StartDate), ContractType: derefStr(j.ContractType),
		Rotation: derefStr(j.Rotation), Season: derefStr(j.Season),
		SalaryMin: j.SalaryMin, SalaryMax: j.SalaryMax, SalaryCurrency: currency,
		ExperienceRequiredYears: j.ExperienceRequiredYears,
		CertificationsRequired:  derefStr(j.CertificationsRequired),
		LanguagesRequired:       derefStr(j.LanguagesRequired),
		Description:             derefStr(j.Description), Status: status,
	}
}

func jobToSchema(j models.Job) crewMatchJob {
	return crewMatchJob{
		ID: j.ID, Title: j.Title, Role: j.Role, Yacht: j.Yacht, Location: j.Location,
		ContractType: j.ContractType, SalaryMin: j.SalaryMin, SalaryMax: j.SalaryMax,
		SalaryCurrency: j.SalaryCurrency, ContactEmail: j.ContactEmail, Description: j.Description,
		YachtType: j.YachtType, YachtLengthM: j.YachtLengthM, StartDate: j.StartDate,
		Season: j.Season, Rotation: j.Rotation, ExperienceRequiredYears: j.ExperienceRequiredYears,
		CertificationsRequired: j.CertificationsRequired, LanguagesRequired: j.LanguagesRequired,
		Requirements: j.Requirements, Responsibilities: j.Responsibilities, Benefits: j.Benefits,
		RecruiterName: j.RecruiterName, RecruiterAgency: j.RecruiterAgency,
		ApplicationURL: j.ApplicationURL, UrgentHire: j.UrgentHire, Source: j.Source,
	}
}

func profileSummary(p models.CrewProfile, history []models.JobHistoryEntry, docSummary string) string {
	var parts []string
	name := strings.TrimSpace(strings.Join(nonEmpty(derefStr(p.FirstName), derefStr(p.LastName)), " "))
	if name != "" {
		parts = append(parts, "Name: "+name)
	}
	if v := derefStr(p.DesiredRole); v != "" {
		parts = append(parts, "Desired role: "+v)
	}
	if v := derefStr(p.YearsExperience); v != "" {
		parts = append(parts, "Experience: "+v+" years")
	}
	if v := derefStr(p.Certifications); v != "" {
		parts = append(parts, "Certifications: "+v)
	}
	if v := derefStr(p.Languages); v != "" {
		parts = append(parts, "Languages: "+v)
	}
	if v := derefStr(p.Bio); v != "" {
		parts = append(parts, "Bio: "+clip(v, 300))
	}
	if len(history) > 0 {
		var lines []string
		for i, e := range history {
			if i >= 5 {
				break
			}
			line := "  - " + e.Role + " on " + e.YachtName
			if e.YachtType != nil && *e.YachtType != "" {
				line += " (" + *e.YachtType + ")"
			}
			if derefStr(e.StartDate) != "" || derefStr(e.EndDate) != "" {
				start := orQ(derefStr(e.StartDate))
				end := derefStr(e.EndDate)
				if end == "" {
					end = "present"
				}
				line += " | " + start + " – " + end
			}
			lines = append(lines, line)
		}
		parts = append(parts, "Work history:\n"+strings.Join(lines, "\n"))
	}
	if docSummary != "" {
		parts = append(parts, "Document insights:\n"+clip(docSummary, 500))
	}
	if len(parts) == 0 {
		return "No profile details available."
	}
	return strings.Join(parts, "\n")
}

func buildDraftSystemPrompt(firstName, profileText string, job models.Job, profileURL string) string {
	var b strings.Builder
	b.WriteString("You ghost-write job application emails for yacht crew. The email must sound like a real person wrote it — professional but natural. Not a cover letter, not a text message.\n\n")
	b.WriteString("STRUCTURE (4-5 sentences total): open naturally mentioning the role and yacht; mention the most relevant recent experience; include the profile link naturally; short professional sign-off, then: " + firstName + "\n\n")
	b.WriteString("Avoid AI tells (templated openers, \"align well with your needs\", \"I am confident that\", \"passionate about\", listing multiple certs, mentioning salary/location/nationality).\n\n")
	b.WriteString("Crew profile:\n" + profileText + "\n\n")
	b.WriteString("Job:\nRole: " + job.Role + "\nYacht: " + job.Yacht + "\n")
	if job.Description != nil && *job.Description != "" {
		b.WriteString("Description: " + clip(*job.Description, 400) + "\n")
	}
	if job.Requirements != nil && *job.Requirements != "" {
		b.WriteString("Requirements: " + clip(*job.Requirements, 300) + "\n")
	}
	if profileURL != "" {
		b.WriteString("Profile link: " + profileURL + "\n")
	} else {
		b.WriteString("No profile link available.\n")
	}
	b.WriteString("\nRespond with JSON only:\n{\"subject\": \"...\", \"body\": \"...\"}")
	return b.String()
}

func parseDraft(text string) (subject, body string) {
	start := strings.Index(text, "{")
	end := strings.LastIndex(text, "}")
	candidate := text
	if start >= 0 && end >= start {
		candidate = text[start : end+1]
	}
	var parsed struct {
		Subject string `json:"subject"`
		Body    string `json:"body"`
	}
	if json.Unmarshal([]byte(candidate), &parsed) == nil {
		return strings.TrimSpace(parsed.Subject), strings.TrimSpace(parsed.Body)
	}
	// Fallback: keep service usable even if the model returns plain text.
	return "", strings.TrimSpace(text)
}

// ── SSE + small helpers ──────────────────────────────────────────────────────

func writeSSE(w http.ResponseWriter, f http.Flusher, event, data string) {
	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, data)
	f.Flush()
}

func mustJSON(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return "{}"
	}
	return string(b)
}

func decodeStrList(s *string) []string {
	if s == nil || *s == "" {
		return []string{}
	}
	var out []string
	if json.Unmarshal([]byte(*s), &out) != nil {
		return []string{}
	}
	return out
}

func decodeFloatMap(s *string) map[string]float64 {
	if s == nil || *s == "" {
		return map[string]float64{}
	}
	out := map[string]float64{}
	if json.Unmarshal([]byte(*s), &out) != nil {
		return map[string]float64{}
	}
	return out
}

func derefStr(p *string) string {
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

func orEmpty(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

func orEmptyMap(m map[string]float64) map[string]float64 {
	if m == nil {
		return map[string]float64{}
	}
	return m
}

func nonEmpty(vals ...string) []string {
	var out []string
	for _, v := range vals {
		if v != "" {
			out = append(out, v)
		}
	}
	return out
}

func orQ(s string) string {
	if s == "" {
		return "?"
	}
	return s
}
