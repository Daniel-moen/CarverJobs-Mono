// Package matching is the Go port of api/app/services/matching_engine.py.
//
// The Python engine is LLM-driven: it batches every open/priority job, asks
// OpenAI to score each batch, then merges, dedupes and gender-filters the
// results. This port keeps all the deterministic structure faithful (batching,
// gender normalisation + requirement detection, prompt building, JSON parsing,
// dedup, gender filtering, sorting) and routes the model call through the
// internal/ai stub. With the stub, the AI returns an empty matched_jobs list, so
// MatchCandidateToJobs yields zero scored jobs until a real model is wired —
// TODO(go-port): wire internal/ai to real OpenAI so scoring produces results.
package matching

import (
	"context"
	"encoding/json"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"

	"jobcarver/internal/ai"
)

const (
	BatchSize      = 8
	MatchThreshold = 30
	MaxWorkers     = 4

	matchMaxTokensPerJob = 400
	matchMinMaxTokens    = 4096
	matchRequestTimeout  = 90 // seconds
)

var (
	fenceRE          = regexp.MustCompile("(?s)```(?:json)?\\s*\\n?(.*?)\\n?\\s*```")
	femaleReqPattern = []*regexp.Regexp{
		regexp.MustCompile(`\bfemale(?:\s+candidates?)?(?:\s+only)?\b`),
		regexp.MustCompile(`\bfemales?\s+only\b`),
		regexp.MustCompile(`\blady(?:\s+only)?\b`),
		regexp.MustCompile(`\bstewardess(?:es)?\b`),
	}
	maleReqPattern = []*regexp.Regexp{
		regexp.MustCompile(`\bmale(?:\s+candidates?)?(?:\s+only)?\b`),
		regexp.MustCompile(`\bmales?\s+only\b`),
		regexp.MustCompile(`\bgentleman(?:\s+only)?\b`),
		regexp.MustCompile(`\bsteward\b`),
	}
)

// CandidateProfile ports the matching_engine CandidateProfile dataclass.
type CandidateProfile struct {
	UserKey            string
	FirstName          string
	LastName           string
	Sex                string
	DesiredRole        string
	Location           string
	PreferredLocations string
	Nationality        string
	YearsExperience    string
	SalaryMin          string
	SalaryMax          string
	ContractType       string
	RotationPreference string
	AvailableFrom      string
	Certifications     []string
	Languages          []string
	Bio                string
	JobHistory         []map[string]string
	DocumentSummary    string
}

// JobSummary ports the matching_engine JobSummary dataclass.
type JobSummary struct {
	JobID                   int      `json:"job_id"`
	Title                   string   `json:"title"`
	Role                    string   `json:"role"`
	Department              string   `json:"department"`
	Location                string   `json:"location"`
	YachtType               string   `json:"yacht_type"`
	YachtLengthM            *int     `json:"yacht_length_m"`
	StartDate               string   `json:"start_date"`
	ContractType            string   `json:"contract_type"`
	Rotation                string   `json:"rotation"`
	Season                  string   `json:"season"`
	SalaryMin               *float64 `json:"salary_min"`
	SalaryMax               *float64 `json:"salary_max"`
	SalaryCurrency          string   `json:"salary_currency"`
	ExperienceRequiredYears *int     `json:"experience_required_years"`
	CertificationsRequired  string   `json:"certifications_required"`
	LanguagesRequired       string   `json:"languages_required"`
	Description             string   `json:"description"`
	Status                  string   `json:"status"`
}

// MatchResult ports the matching_engine MatchResult dataclass.
type MatchResult struct {
	JobID         int                `json:"job_id"`
	Matched       bool               `json:"matched"`
	Compatibility float64            `json:"compatibility"`
	Reason        string             `json:"reason"`
	Strengths     []string           `json:"strengths"`
	Gaps          []string           `json:"gaps"`
	FactorScores  map[string]float64 `json:"factor_scores"`
}

// ProgressCallback mirrors ProgressCallback in the Python module.
// (jobsScanned, totalJobs, matchesSoFar, batchNum, totalBatches)
type ProgressCallback func(jobsScanned, totalJobs, matchesSoFar, batchNum, totalBatches int)

func normaliseGender(value string) string {
	v := strings.ToLower(strings.TrimSpace(value))
	switch v {
	case "f", "female", "woman", "lady":
		return "female"
	case "m", "male", "man", "gentleman":
		return "male"
	}
	return ""
}

func jobGenderRequirement(job JobSummary) string {
	parts := []string{job.Title, job.Role, job.Description, job.CertificationsRequired, job.LanguagesRequired}
	var nonEmpty []string
	for _, p := range parts {
		if p != "" {
			nonEmpty = append(nonEmpty, p)
		}
	}
	text := strings.ToLower(strings.Join(nonEmpty, " "))
	if text == "" {
		return ""
	}
	femaleReq := anyMatch(femaleReqPattern, text)
	maleReq := anyMatch(maleReqPattern, text)
	if femaleReq && !maleReq {
		return "female"
	}
	if maleReq && !femaleReq {
		return "male"
	}
	return ""
}

func anyMatch(patterns []*regexp.Regexp, text string) bool {
	for _, p := range patterns {
		if p.MatchString(text) {
			return true
		}
	}
	return false
}

func matchMaxTokens(jobCount int) int {
	if v := jobCount * matchMaxTokensPerJob; v > matchMinMaxTokens {
		return v
	}
	return matchMinMaxTokens
}

// buildPrompt ports _build_prompt: produces the full instruction + JSON payload
// string sent as the single user message.
func buildPrompt(candidate CandidateProfile, jobs []JobSummary) string {
	jobIDs := make([]int, len(jobs))
	for i, j := range jobs {
		jobIDs[i] = j.JobID
	}

	candidateDict := map[string]any{
		"name":                strings.TrimSpace(candidate.FirstName + " " + candidate.LastName),
		"sex":                 candidate.Sex,
		"desired_role":        candidate.DesiredRole,
		"current_location":    candidate.Location,
		"preferred_locations": candidate.PreferredLocations,
		"nationality":         candidate.Nationality,
		"years_experience":    candidate.YearsExperience,
		"salary_min":          candidate.SalaryMin,
		"salary_max":          candidate.SalaryMax,
		"contract_type":       candidate.ContractType,
		"rotation_preference": candidate.RotationPreference,
		"available_from":      candidate.AvailableFrom,
		"certifications":      candidate.Certifications,
		"languages":           candidate.Languages,
		"bio":                 clip(candidate.Bio, 500),
		"job_history":         clipHistory(candidate.JobHistory, 8),
		"document_summary":    clip(candidate.DocumentSummary, 800),
	}

	jobsList := make([]map[string]any, 0, len(jobs))
	for _, j := range jobs {
		entry := map[string]any{
			"job_id":                    j.JobID,
			"title":                     j.Title,
			"role":                      j.Role,
			"department":                j.Department,
			"location":                  j.Location,
			"yacht_type":                j.YachtType,
			"yacht_length_m":            j.YachtLengthM,
			"start_date":                j.StartDate,
			"contract_type":             j.ContractType,
			"rotation":                  j.Rotation,
			"season":                    j.Season,
			"salary_min":                j.SalaryMin,
			"salary_max":                j.SalaryMax,
			"salary_currency":           j.SalaryCurrency,
			"experience_required_years": j.ExperienceRequiredYears,
			"certifications_required":   j.CertificationsRequired,
			"languages_required":        j.LanguagesRequired,
			"description":               clip(j.Description, 400),
		}
		if j.Status == "priority" {
			entry["status"] = "priority"
		}
		jobsList = append(jobsList, entry)
	}

	jobIDsJSON, _ := json.Marshal(jobIDs)
	payload := map[string]any{
		"rules": map[string]any{
			"priority_order":    []string{"role", "experience", "certifications", "location", "pay", "contract_length", "languages"},
			"matched_threshold": MatchThreshold,
			"instructions": []string{
				"ROLE DEPARTMENT is the primary filter. The job must be in the same department or a closely related one.",
				"Departments: Deck, Interior/Stew, Engine, Galley, Bridge, Medical, Pursers.",
				"Cross-department mismatches (e.g. desired=Deckhand, job=Stewardess) must get compatibility <= 15.",
				"Same-department roles at different seniority levels ARE valid matches — score them 35-70 depending on experience gap. E.g. a Deckhand with 3+ years should match Bosun roles at 45-55.",
				"Adjacent roles within the same department should score highly: Bosun↔Deckhand, Chief Stew↔Stewardess, 2nd Engineer↔Chief Engineer, Sous Chef↔Head Chef.",
				"Dual roles like Deck/Stew should match BOTH Deck and Interior departments.",
				"Set matched=true if compatibility >= " + itoa(MatchThreshold) + ". Be GENEROUS — if the candidate could reasonably apply and have a shot, mark it matched.",
				"Use the candidate's bio, job_history, and document_summary as the PRIMARY evidence of capability. Recent job history (last 2 roles) should carry the most weight — if they did the role before, score 70+.",
				"If the candidate held the exact same role on a previous vessel, that is a STRONG match (80+) regardless of other factors.",
				"Do NOT over-penalise for missing certifications unless the job explicitly requires them for safety-critical roles (Captain, Engineer, Officer). Partial cert matches (e.g. has STCW but not ENG1) should only reduce by 5-10 points.",
				"Location flexibility: yachting is a global industry — location mismatches should only reduce by 3-5 points, not disqualify.",
				"Pay mismatches: only reduce if the job pay is drastically (>50%) below the candidate's minimum.",
				"If the candidate has relevant experience for the role, that should outweigh minor gaps in listed requirements.",
				"AIM to find at least 5+ matches if the candidate has any relevant experience. Be helpful, not punitive.",
				"Jobs with status=priority should receive a +10 compatibility boost (they are urgent hires looking for crew now).",
				"Gender requirements are strict. If a job explicitly specifies male/female-only (or uses gendered role labels like stewardess/steward), opposite-gender candidates must be matched=false with compatibility <= 5.",
				"Output ONLY raw JSON. No markdown fences, no extra text.",
				"You MUST return exactly one entry for every job_id: " + string(jobIDsJSON) + ". Copy each job_id verbatim.",
				"Each entry: job_id (integer, verbatim), matched (boolean), compatibility (integer 0-100), reason (1-2 sentences), strengths (list), gaps (list), factor_scores (object).",
				"factor_scores keys: role, location, pay, contract, skills, certifications, experience — all integers 0-100.",
			},
		},
		"candidate": candidateDict,
		"jobs":      jobsList,
		"response_schema": map[string]any{
			"matched_jobs": []map[string]any{{
				"job_id":        "integer (verbatim from input)",
				"matched":       "boolean",
				"compatibility": "integer 0-100",
				"reason":        "string",
				"strengths":     []string{"string"},
				"gaps":          []string{"string"},
				"factor_scores": map[string]string{
					"role": "0-100", "location": "0-100", "pay": "0-100",
					"contract": "0-100", "skills": "0-100",
					"certifications": "0-100", "experience": "0-100",
				},
			}},
		},
	}

	payloadJSON, _ := json.Marshal(payload)
	return "You are a superyacht crew job matching engine. " +
		"Your goal is to help candidates find every job they could realistically apply for. " +
		"Be thorough and generous — if there is a reasonable fit, surface it.\n" +
		"CRITICAL: Output ONLY raw JSON matching the schema. No markdown code fences.\n" +
		string(payloadJSON)
}

// extractJSON ports _extract_json.
func extractJSON(text string) string {
	if text == "" {
		return "{}"
	}
	text = strings.TrimSpace(text)
	if m := fenceRE.FindStringSubmatch(text); m != nil {
		text = strings.TrimSpace(m[1])
	}
	if start := strings.Index(text, "{"); start > 0 {
		text = text[start:]
	}
	return text
}

// rawMatch is the loosely-typed shape of one matched_jobs entry, mirroring the
// defensive parsing in _parse_batch.
type rawMatch struct {
	JobID         json.Number        `json:"job_id"`
	Compatibility json.Number        `json:"compatibility"`
	Reason        any                `json:"reason"`
	Strengths     []any              `json:"strengths"`
	Gaps          []any              `json:"gaps"`
	FactorScores  map[string]float64 `json:"factor_scores"`
}

func parseBatch(responseText string, validJobIDs map[int]bool) []MatchResult {
	cleaned := extractJSON(responseText)
	var payload struct {
		MatchedJobs []rawMatch `json:"matched_jobs"`
	}
	if err := json.Unmarshal([]byte(cleaned), &payload); err != nil {
		return nil
	}
	var results []MatchResult
	for _, item := range payload.MatchedJobs {
		jobID, err := item.JobID.Int64()
		if err != nil || !validJobIDs[int(jobID)] {
			continue
		}
		comp, _ := item.Compatibility.Float64()
		comp = clamp(comp, 0, 100)
		fs := map[string]float64{}
		for k, v := range item.FactorScores {
			fs[k] = clamp(v, 0, 100)
		}
		results = append(results, MatchResult{
			JobID:         int(jobID),
			Matched:       comp >= MatchThreshold,
			Compatibility: comp,
			Reason:        toStr(item.Reason),
			Strengths:     toStrSlice(item.Strengths),
			Gaps:          toStrSlice(item.Gaps),
			FactorScores:  fs,
		})
	}
	return results
}

func callAI(ctx context.Context, model, prompt string, jobCount int) (string, error) {
	return ai.Chat(ctx, model, []ai.Message{{Role: "user", Content: prompt}}, ai.Options{
		MaxTokens:      matchMaxTokens(jobCount),
		Temperature:    0.3,
		JSONResponse:   true,
		TimeoutSeconds: matchRequestTimeout,
	})
}

// MatchCandidateToJobs ports match_candidate_to_jobs: batches jobs, scores each
// batch via the AI stub (concurrently when >1 batch), merges + dedupes + gender
// filters, and returns results sorted by compatibility descending.
func MatchCandidateToJobs(ctx context.Context, model string, candidate CandidateProfile, jobs []JobSummary, batchSize int, onProgress ProgressCallback) []MatchResult {
	if len(jobs) == 0 {
		return nil
	}
	if batchSize <= 0 {
		batchSize = BatchSize
	}
	totalJobs := len(jobs)
	var batches [][]JobSummary
	for i := 0; i < totalJobs; i += batchSize {
		end := i + batchSize
		if end > totalJobs {
			end = totalJobs
		}
		batches = append(batches, jobs[i:end])
	}
	totalBatches := len(batches)

	validIDs := make(map[int]bool, totalJobs)
	for _, j := range jobs {
		validIDs[j.JobID] = true
	}

	processBatch := func(batch []JobSummary) []MatchResult {
		prompt := buildPrompt(candidate, batch)
		resp, err := callAI(ctx, model, prompt, len(batch))
		if err != nil {
			return nil
		}
		return parseBatch(resp, validIDs)
	}

	var allResults []MatchResult
	jobsScanned := 0

	if totalBatches <= 1 {
		for idx, batch := range batches {
			res := processBatch(batch)
			allResults = append(allResults, res...)
			jobsScanned += len(batch)
			if onProgress != nil {
				onProgress(jobsScanned, totalJobs, countMatched(allResults), idx+1, totalBatches)
			}
		}
	} else {
		resultsMap := make([][]MatchResult, totalBatches)
		sem := make(chan struct{}, min(totalBatches, MaxWorkers))
		var wg sync.WaitGroup
		for i := range batches {
			wg.Add(1)
			go func(idx int) {
				defer wg.Done()
				sem <- struct{}{}
				defer func() { <-sem }()
				resultsMap[idx] = processBatch(batches[idx])
			}(i)
		}
		wg.Wait()
		for idx := 0; idx < totalBatches; idx++ {
			allResults = append(allResults, resultsMap[idx]...)
			jobsScanned += len(batches[idx])
			if onProgress != nil {
				onProgress(jobsScanned, totalJobs, countMatched(allResults), idx+1, totalBatches)
			}
		}
	}

	// Dedup: keep the highest compatibility per job_id.
	deduped := map[int]MatchResult{}
	for _, r := range allResults {
		if ex, ok := deduped[r.JobID]; !ok || r.Compatibility > ex.Compatibility {
			deduped[r.JobID] = r
		}
	}

	// Gender filter.
	candidateGender := normaliseGender(candidate.Sex)
	jobsByID := map[int]JobSummary{}
	for _, j := range jobs {
		jobsByID[j.JobID] = j
	}
	if candidateGender != "" {
		for id, result := range deduped {
			job, ok := jobsByID[id]
			if !ok {
				continue
			}
			required := jobGenderRequirement(job)
			if required != "" && required != candidateGender {
				result.Matched = false
				result.Compatibility = mathMin(result.Compatibility, 5.0)
				result.Reason = "Filtered out: job specifies " + required + " candidates."
				result.Strengths = nil
				result.Gaps = []string{"Gender requirement mismatch (" + required + " only)."}
				result.FactorScores = map[string]float64{}
				deduped[id] = result
			}
		}
	}

	results := make([]MatchResult, 0, len(deduped))
	for _, r := range deduped {
		results = append(results, r)
	}
	sort.SliceStable(results, func(i, j int) bool {
		return results[i].Compatibility > results[j].Compatibility
	})
	return results
}

// ── small helpers ────────────────────────────────────────────────────────────

func countMatched(rs []MatchResult) int {
	n := 0
	for _, r := range rs {
		if r.Matched {
			n++
		}
	}
	return n
}

func clip(s string, n int) string {
	if s == "" {
		return ""
	}
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func clipHistory(h []map[string]string, n int) []map[string]string {
	if len(h) <= n {
		return h
	}
	return h[:n]
}

func clamp(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func mathMin(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func itoa(i int) string {
	return strconv.Itoa(i)
}

func toStr(v any) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func toStrSlice(vs []any) []string {
	if len(vs) == 0 {
		return nil
	}
	out := make([]string, 0, len(vs))
	for _, v := range vs {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}
