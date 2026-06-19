// Package profile ports api/app/routes/profile.py — the authenticated crew
// profile editor (/profile/*) plus the public profile view (/p/{slug} and the
// profile photo). Register mounts both routers.
package profile

import (
	"crypto/rand"
	"encoding/base64"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/config"
	"jobcarver/internal/credits"
	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

var validSexValues = map[string]bool{"male": true, "female": true, "other": true, "prefer_not_to_say": true}

// Register mounts the authenticated /profile routes and the public /p routes.
func Register(r chi.Router) {
	r.Route("/profile", func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Post("/save", saveProfile)
		r.Get("/me", getMyProfile)
	})
	r.Get("/p/{slug}", getPublicProfile)
	r.Get("/p/{slug}/photo", getPublicPhoto)
}

func generateSlug() string {
	b := make([]byte, 6)
	_, _ = rand.Read(b)
	return base64.RawURLEncoding.EncodeToString(b)
}

func saveProfile(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub

	var body profileSave
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if body.Sex != nil {
		s := strings.ToLower(strings.TrimSpace(*body.Sex))
		if s != "" && !validSexValues[s] {
			httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid sex value.", httpx.CRV1003)
			return
		}
		if s == "" {
			body.Sex = nil
		} else {
			body.Sex = &s
		}
	}

	var existing models.CrewProfile
	err := db.DB.Where("user_key = ?", userKey).First(&existing).Error
	if err == nil {
		applyProfile(&existing, body)
		db.DB.Save(&existing)
		httpx.JSON(w, http.StatusOK, toProfileRead(existing))
		return
	}

	slug := generateSlug()
	for {
		var clash models.CrewProfile
		if db.DB.Where("profile_slug = ?", slug).First(&clash).Error != nil {
			break
		}
		slug = generateSlug()
	}

	profile := models.CrewProfile{UserKey: userKey, ProfileSlug: slug}
	applyProfile(&profile, body)
	if err := db.DB.Create(&profile).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not save profile.", httpx.CRV1002)
		return
	}
	httpx.JSON(w, http.StatusOK, toProfileRead(profile))
}

func getMyProfile(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub
	balance := credits.GetBalance(db.DB, userKey)

	var profile models.CrewProfile
	if err := db.DB.Where("user_key = ?", userKey).First(&profile).Error; err != nil {
		httpx.JSON(w, http.StatusOK, map[string]any{"profile": nil, "credits_balance": balance})
		return
	}
	httpx.JSON(w, http.StatusOK, map[string]any{
		"profile":         toProfileRead(profile),
		"credits_balance": balance,
	})
}

func getPublicProfile(w http.ResponseWriter, r *http.Request) {
	slug := chi.URLParam(r, "slug")
	if len(slug) > 16 {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid slug.", httpx.CRV1003)
		return
	}
	var profile models.CrewProfile
	if err := db.DB.Where("profile_slug = ?", slug).First(&profile).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "Profile not found.", httpx.CRV1005)
		return
	}

	var docs []models.Document
	db.DB.Where("user_key = ?", profile.UserKey).Find(&docs)
	docTypes := map[string]bool{}
	for _, d := range docs {
		docTypes[d.DocType] = true
	}
	var photoURL *string
	if docTypes["photo"] {
		u := "/p/" + slug + "/photo"
		photoURL = &u
	}

	var entries []models.JobHistoryEntry
	db.DB.Where("user_key = ?", profile.UserKey).Order("id desc").Find(&entries)
	history := make([]jobHistoryRead, 0, len(entries))
	for _, e := range entries {
		history = append(history, toJobHistoryRead(e))
	}

	httpx.JSON(w, http.StatusOK, publicProfileResponse{
		FirstName:          profile.FirstName,
		LastName:           profile.LastName,
		Nationality:        profile.Nationality,
		CurrentLocation:    profile.CurrentLocation,
		DesiredRole:        profile.DesiredRole,
		ContractType:       profile.ContractType,
		PreferredLocations: profile.PreferredLocations,
		RotationPreference: profile.RotationPreference,
		YearsExperience:    profile.YearsExperience,
		AvailableFrom:      profile.AvailableFrom,
		Certifications:     profile.Certifications,
		Languages:          profile.Languages,
		Bio:                profile.Bio,
		HasCV:              docTypes["cv"],
		HasReferences:      docTypes["references"],
		HasPhoto:           docTypes["photo"],
		PhotoURL:           photoURL,
		JobHistory:         history,
	})
}

func getPublicPhoto(w http.ResponseWriter, r *http.Request) {
	slug := chi.URLParam(r, "slug")
	if len(slug) > 16 {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid slug.", httpx.CRV1003)
		return
	}
	var profile models.CrewProfile
	if err := db.DB.Where("profile_slug = ?", slug).First(&profile).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "Profile not found.", httpx.CRV1005)
		return
	}
	var doc models.Document
	if err := db.DB.Where("user_key = ? AND doc_type = ?", profile.UserKey, "photo").First(&doc).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "No photo uploaded.", httpx.CRV1005)
		return
	}

	uploadDir, _ := filepath.Abs(config.S.UploadDir)
	filePath, _ := filepath.Abs(filepath.Join(uploadDir, doc.StoredName))
	if !strings.HasPrefix(filePath, uploadDir) {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid file path.", httpx.CRV1003)
		return
	}
	if _, err := os.Stat(filePath); err != nil {
		httpx.WriteError(w, http.StatusNotFound, "File missing on server.", httpx.CRV1005)
		return
	}

	mediaType := "image/jpeg"
	if strings.EqualFold(filepath.Ext(filePath), ".png") {
		mediaType = "image/png"
	}
	w.Header().Set("Content-Type", mediaType)
	http.ServeFile(w, r, filePath)
}

// profileSave ports schemas.CrewProfileSave — all fields optional.
type profileSave struct {
	FirstName          *string `json:"first_name"`
	LastName           *string `json:"last_name"`
	Sex                *string `json:"sex"`
	Phone              *string `json:"phone"`
	Nationality        *string `json:"nationality"`
	CurrentLocation    *string `json:"current_location"`
	DesiredRole        *string `json:"desired_role"`
	ContractType       *string `json:"contract_type"`
	PreferredLocations *string `json:"preferred_locations"`
	RotationPreference *string `json:"rotation_preference"`
	YearsExperience    *string `json:"years_experience"`
	AvailableFrom      *string `json:"available_from"`
	SalaryMin          *string `json:"salary_min"`
	SalaryMax          *string `json:"salary_max"`
	Certifications     *string `json:"certifications"`
	Languages          *string `json:"languages"`
	Bio                *string `json:"bio"`
}

func applyProfile(p *models.CrewProfile, b profileSave) {
	if b.FirstName != nil {
		p.FirstName = b.FirstName
	}
	if b.LastName != nil {
		p.LastName = b.LastName
	}
	if b.Sex != nil {
		p.Sex = b.Sex
	}
	if b.Phone != nil {
		p.Phone = b.Phone
	}
	if b.Nationality != nil {
		p.Nationality = b.Nationality
	}
	if b.CurrentLocation != nil {
		p.CurrentLocation = b.CurrentLocation
	}
	if b.DesiredRole != nil {
		p.DesiredRole = b.DesiredRole
	}
	if b.ContractType != nil {
		p.ContractType = b.ContractType
	}
	if b.PreferredLocations != nil {
		p.PreferredLocations = b.PreferredLocations
	}
	if b.RotationPreference != nil {
		p.RotationPreference = b.RotationPreference
	}
	if b.YearsExperience != nil {
		p.YearsExperience = b.YearsExperience
	}
	if b.AvailableFrom != nil {
		p.AvailableFrom = b.AvailableFrom
	}
	if b.SalaryMin != nil {
		p.SalaryMin = b.SalaryMin
	}
	if b.SalaryMax != nil {
		p.SalaryMax = b.SalaryMax
	}
	if b.Certifications != nil {
		p.Certifications = b.Certifications
	}
	if b.Languages != nil {
		p.Languages = b.Languages
	}
	if b.Bio != nil {
		p.Bio = b.Bio
	}
}

// profileRead ports schemas.CrewProfileRead.
type profileRead struct {
	FirstName          *string   `json:"first_name"`
	LastName           *string   `json:"last_name"`
	Sex                *string   `json:"sex"`
	Phone              *string   `json:"phone"`
	Nationality        *string   `json:"nationality"`
	CurrentLocation    *string   `json:"current_location"`
	DesiredRole        *string   `json:"desired_role"`
	ContractType       *string   `json:"contract_type"`
	PreferredLocations *string   `json:"preferred_locations"`
	RotationPreference *string   `json:"rotation_preference"`
	YearsExperience    *string   `json:"years_experience"`
	AvailableFrom      *string   `json:"available_from"`
	SalaryMin          *string   `json:"salary_min"`
	SalaryMax          *string   `json:"salary_max"`
	Certifications     *string   `json:"certifications"`
	Languages          *string   `json:"languages"`
	Bio                *string   `json:"bio"`
	ProfileSlug        string    `json:"profile_slug"`
	CreatedAt          time.Time `json:"created_at"`
	UpdatedAt          time.Time `json:"updated_at"`
}

func toProfileRead(p models.CrewProfile) profileRead {
	return profileRead{
		FirstName:          p.FirstName,
		LastName:           p.LastName,
		Sex:                p.Sex,
		Phone:              p.Phone,
		Nationality:        p.Nationality,
		CurrentLocation:    p.CurrentLocation,
		DesiredRole:        p.DesiredRole,
		ContractType:       p.ContractType,
		PreferredLocations: p.PreferredLocations,
		RotationPreference: p.RotationPreference,
		YearsExperience:    p.YearsExperience,
		AvailableFrom:      p.AvailableFrom,
		SalaryMin:          p.SalaryMin,
		SalaryMax:          p.SalaryMax,
		Certifications:     p.Certifications,
		Languages:          p.Languages,
		Bio:                p.Bio,
		ProfileSlug:        p.ProfileSlug,
		CreatedAt:          p.CreatedAt,
		UpdatedAt:          p.UpdatedAt,
	}
}

type publicProfileResponse struct {
	FirstName          *string          `json:"first_name"`
	LastName           *string          `json:"last_name"`
	Nationality        *string          `json:"nationality"`
	CurrentLocation    *string          `json:"current_location"`
	DesiredRole        *string          `json:"desired_role"`
	ContractType       *string          `json:"contract_type"`
	PreferredLocations *string          `json:"preferred_locations"`
	RotationPreference *string          `json:"rotation_preference"`
	YearsExperience    *string          `json:"years_experience"`
	AvailableFrom      *string          `json:"available_from"`
	Certifications     *string          `json:"certifications"`
	Languages          *string          `json:"languages"`
	Bio                *string          `json:"bio"`
	HasCV              bool             `json:"has_cv"`
	HasReferences      bool             `json:"has_references"`
	HasPhoto           bool             `json:"has_photo"`
	PhotoURL           *string          `json:"photo_url"`
	JobHistory         []jobHistoryRead `json:"job_history"`
}

// jobHistoryRead mirrors schemas.JobHistoryRead (embedded in public profiles).
type jobHistoryRead struct {
	ID          int       `json:"id"`
	YachtName   string    `json:"yacht_name"`
	YachtType   *string   `json:"yacht_type"`
	Role        string    `json:"role"`
	StartDate   *string   `json:"start_date"`
	EndDate     *string   `json:"end_date"`
	Description *string   `json:"description"`
	CreatedAt   time.Time `json:"created_at"`
}

func toJobHistoryRead(e models.JobHistoryEntry) jobHistoryRead {
	return jobHistoryRead{
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
