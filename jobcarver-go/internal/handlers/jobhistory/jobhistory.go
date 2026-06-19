// Package jobhistory ports api/app/routes/job_history.py — CRUD over a crew
// member's yacht work history, scoped to the logged-in user.
package jobhistory

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

const maxEntriesPerUser = 20

// Register mounts /job-history (all routes require a session).
func Register(r chi.Router) {
	r.Route("/job-history", func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Get("/", list)
		r.Post("/", create)
		r.Patch("/{entryID}", update)
		r.Delete("/{entryID}", remove)
	})
}

type historyRead struct {
	ID          int       `json:"id"`
	YachtName   string    `json:"yacht_name"`
	YachtType   *string   `json:"yacht_type"`
	Role        string    `json:"role"`
	StartDate   *string   `json:"start_date"`
	EndDate     *string   `json:"end_date"`
	Description *string   `json:"description"`
	CreatedAt   time.Time `json:"created_at"`
}

func toRead(e models.JobHistoryEntry) historyRead {
	return historyRead{
		ID:          e.ID,
		YachtName:   e.YachtName,
		YachtType:   e.YachtType,
		Role:        e.Role,
		StartDate:   e.StartDate,
		EndDate:     e.EndDate,
		Description: e.Description,
		CreatedAt:   e.CreatedAt,
	}
}

type createRequest struct {
	YachtName   string  `json:"yacht_name"`
	YachtType   *string `json:"yacht_type"`
	Role        string  `json:"role"`
	StartDate   *string `json:"start_date"`
	EndDate     *string `json:"end_date"`
	Description *string `json:"description"`
}

type updateRequest struct {
	YachtName   *string `json:"yacht_name"`
	YachtType   *string `json:"yacht_type"`
	Role        *string `json:"role"`
	StartDate   *string `json:"start_date"`
	EndDate     *string `json:"end_date"`
	Description *string `json:"description"`
}

func list(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub

	var entries []models.JobHistoryEntry
	db.DB.Where("user_key = ?", userKey).Order("id desc").Find(&entries)

	out := make([]historyRead, 0, len(entries))
	for _, e := range entries {
		out = append(out, toRead(e))
	}
	httpx.JSON(w, http.StatusOK, out)
}

func create(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub

	var body createRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if strings.TrimSpace(body.YachtName) == "" || strings.TrimSpace(body.Role) == "" {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "yacht_name and role are required.", httpx.CRV1003)
		return
	}

	var count int64
	db.DB.Model(&models.JobHistoryEntry{}).Where("user_key = ?", userKey).Count(&count)
	if count >= maxEntriesPerUser {
		httpx.WriteError(w, http.StatusBadRequest,
			"Maximum "+strconv.Itoa(maxEntriesPerUser)+" job history entries allowed.", httpx.CRV1003)
		return
	}

	entry := models.JobHistoryEntry{
		UserKey:     userKey,
		YachtName:   body.YachtName,
		YachtType:   body.YachtType,
		Role:        body.Role,
		StartDate:   body.StartDate,
		EndDate:     body.EndDate,
		Description: body.Description,
	}
	if err := db.DB.Create(&entry).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not save entry.", httpx.CRV1002)
		return
	}
	httpx.JSON(w, http.StatusCreated, toRead(entry))
}

func update(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub

	entryID, err := strconv.Atoi(chi.URLParam(r, "entryID"))
	if err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid entry id.", httpx.CRV1003)
		return
	}

	var body updateRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}

	var entry models.JobHistoryEntry
	if err := db.DB.Where("id = ? AND user_key = ?", entryID, userKey).First(&entry).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "Entry not found.", httpx.CRV1005)
		return
	}

	// model_dump(exclude_unset=True): only apply fields present in the payload.
	if body.YachtName != nil {
		entry.YachtName = *body.YachtName
	}
	if body.YachtType != nil {
		entry.YachtType = body.YachtType
	}
	if body.Role != nil {
		entry.Role = *body.Role
	}
	if body.StartDate != nil {
		entry.StartDate = body.StartDate
	}
	if body.EndDate != nil {
		entry.EndDate = body.EndDate
	}
	if body.Description != nil {
		entry.Description = body.Description
	}
	db.DB.Save(&entry)
	httpx.JSON(w, http.StatusOK, toRead(entry))
}

func remove(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub

	entryID, err := strconv.Atoi(chi.URLParam(r, "entryID"))
	if err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid entry id.", httpx.CRV1003)
		return
	}

	var entry models.JobHistoryEntry
	if err := db.DB.Where("id = ? AND user_key = ?", entryID, userKey).First(&entry).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "Entry not found.", httpx.CRV1005)
		return
	}
	db.DB.Delete(&entry)
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true})
}
