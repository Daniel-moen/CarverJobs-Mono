// Package jobs ports api/app/routes/jobs.py — listing/reading jobs (any session)
// and admin-only create/update/delete. Listing replicates crud.list_jobs,
// including its capped query and de-duplication pass.
package jobs

import (
	"net/http"
	"regexp"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

const (
	defaultJobLimit = 500
	maxJobLimit     = 1000
)

// Statuses that mean a job is no longer a live listing — excluded by default.
var inactiveJobStatuses = []string{"expired", "closed", "filled", "archived"}

var validJobStatuses = map[string]bool{
	"open": true, "closed": true, "priority": true, "filled": true, "draft": true,
}

var emailRE = regexp.MustCompile(`^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$`)

// Register mounts /jobs. Listing/reading need any session; writes need admin.
func Register(r chi.Router) {
	r.Route("/jobs", func(r chi.Router) {
		r.Group(func(r chi.Router) {
			r.Use(security.RequireSession)
			r.Get("/", list)
			r.Get("/{jobID}", get)
		})
		r.Group(func(r chi.Router) {
			r.Use(security.RequireSession)
			r.Use(adminOnly)
			r.Post("/", create)
			r.Patch("/{jobID}", update)
			r.Delete("/{jobID}", remove)
		})
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

func list(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())

	limit := defaultJobLimit
	if raw := r.URL.Query().Get("limit"); raw != "" {
		v, err := strconv.Atoi(raw)
		if err != nil || v < 1 || v > maxJobLimit {
			httpx.WriteError(w, http.StatusUnprocessableEntity, "limit must be between 1 and 1000.", httpx.CRV1003)
			return
		}
		limit = v
	}
	includeInactive := r.URL.Query().Get("include_inactive") == "true"
	allowInactive := includeInactive && sess.Role == "admin"

	q := db.DB.Model(&models.Job{})
	if !allowInactive {
		q = q.Where("status NOT IN ?", inactiveJobStatuses)
	}
	var rows []models.Job
	q.Order("created_at desc").Limit(limit).Find(&rows)

	deduped := dedupeJobs(rows)
	out := make([]jobRead, 0, len(deduped))
	for _, j := range deduped {
		out = append(out, toJobRead(j))
	}
	httpx.JSON(w, http.StatusOK, out)
}

// dedupeJobs ports the de-duplication pass in crud.list_jobs.
func dedupeJobs(rows []models.Job) []models.Job {
	type key struct{ kind, val string }
	seen := map[key]bool{}
	out := make([]models.Job, 0, len(rows))
	for _, j := range rows {
		var k *key
		switch {
		case j.ContentHash != nil && *j.ContentHash != "":
			k = &key{"content_hash", *j.ContentHash}
		case j.JobFingerprint != nil && *j.JobFingerprint != "":
			k = &key{"job_fingerprint", *j.JobFingerprint}
		case j.ApplicationURL != nil && strings.TrimSpace(*j.ApplicationURL) != "":
			k = &key{"application_url", strings.ToLower(strings.TrimSpace(*j.ApplicationURL))}
		default:
			fallback := strings.Join([]string{
				strings.ToLower(strings.TrimSpace(j.Title)),
				strings.ToLower(strings.TrimSpace(j.Role)),
				strings.ToLower(strings.TrimSpace(j.Yacht)),
				strings.ToLower(strings.TrimSpace(j.Location)),
				strings.ToLower(strings.TrimSpace(deref(j.StartDate))),
			}, "|")
			if strings.Trim(fallback, "|") != "" {
				k = &key{"fallback", fallback}
			}
		}
		if k != nil {
			if seen[*k] {
				continue
			}
			seen[*k] = true
		}
		out = append(out, j)
	}
	return out
}

func get(w http.ResponseWriter, r *http.Request) {
	job, ok := loadJob(w, r)
	if !ok {
		return
	}
	httpx.JSON(w, http.StatusOK, toJobRead(job))
}

func create(w http.ResponseWriter, r *http.Request) {
	var body jobWrite
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if strings.TrimSpace(deref(body.Title)) == "" || strings.TrimSpace(deref(body.Role)) == "" ||
		strings.TrimSpace(deref(body.Yacht)) == "" || strings.TrimSpace(deref(body.Location)) == "" {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "title, role, yacht and location are required.", httpx.CRV1003)
		return
	}

	job := models.Job{
		// Defaults mirroring JobBase.
		SalaryCurrency: strPtr("EUR"),
		Status:         "open",
		Source:         strPtr("manual"),
	}
	if !applyWrite(&job, body, w) {
		return
	}
	if err := db.DB.Create(&job).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not create job.", httpx.CRV1002)
		return
	}
	httpx.JSON(w, http.StatusCreated, toJobRead(job))
}

func update(w http.ResponseWriter, r *http.Request) {
	job, ok := loadJob(w, r)
	if !ok {
		return
	}
	var body jobWrite
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if !applyWrite(&job, body, w) {
		return
	}
	db.DB.Save(&job)
	httpx.JSON(w, http.StatusOK, toJobRead(job))
}

func remove(w http.ResponseWriter, r *http.Request) {
	job, ok := loadJob(w, r)
	if !ok {
		return
	}
	db.DB.Delete(&job)
	httpx.JSON(w, http.StatusNoContent, nil)
}

func loadJob(w http.ResponseWriter, r *http.Request) (models.Job, bool) {
	id, err := strconv.Atoi(chi.URLParam(r, "jobID"))
	if err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid job id.", httpx.CRV1003)
		return models.Job{}, false
	}
	var job models.Job
	if err := db.DB.Where("id = ?", id).First(&job).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "Job not found", httpx.CRV1005)
		return models.Job{}, false
	}
	return job, true
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func strPtr(s string) *string { return &s }
