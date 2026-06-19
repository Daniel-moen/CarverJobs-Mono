// Package users ports api/app/routes/users.py — admin-only CRUD over user
// accounts. The whole router requires an admin session.
package users

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/db"
	"jobcarver/internal/flags"
	"jobcarver/internal/httpx"
	"jobcarver/internal/metrics"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

var validRoles = map[string]bool{"crew": true, "admin": true, "agency": true}

// Register mounts /users behind RequireSession + admin role check.
func Register(r chi.Router) {
	r.Route("/users", func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Use(adminOnly)
		r.Get("/", list)
		r.Post("/", create)
		r.Get("/{userID}", get)
		r.Patch("/{userID}", update)
		r.Delete("/{userID}", remove)
	})
}

// adminOnly mirrors security.require_admin_session as a middleware.
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

type userRead struct {
	ID              int       `json:"id"`
	Email           string    `json:"email"`
	FullName        string    `json:"full_name"`
	Role            string    `json:"role"`
	Phone           *string   `json:"phone"`
	Nationality     *string   `json:"nationality"`
	YearsExperience *int      `json:"years_experience"`
	CurrentLocation *string   `json:"current_location"`
	Gender          *string   `json:"gender"`
	IsActive        bool      `json:"is_active"`
	IsSubscribed    bool      `json:"is_subscribed"`
	CreatedAt       time.Time `json:"created_at"`
	UpdatedAt       time.Time `json:"updated_at"`
}

func toRead(u models.User) userRead {
	return userRead{
		ID:              u.ID,
		Email:           u.Email,
		FullName:        u.FullName,
		Role:            u.Role,
		Phone:           u.Phone,
		Nationality:     u.Nationality,
		YearsExperience: u.YearsExperience,
		CurrentLocation: u.CurrentLocation,
		Gender:          u.Gender,
		IsActive:        u.IsActive,
		IsSubscribed:    u.IsSubscribed,
		CreatedAt:       u.CreatedAt,
		UpdatedAt:       u.UpdatedAt,
	}
}

func list(w http.ResponseWriter, _ *http.Request) {
	var users []models.User
	db.DB.Order("created_at desc").Find(&users)
	out := make([]userRead, 0, len(users))
	for _, u := range users {
		out = append(out, toRead(u))
	}
	httpx.JSON(w, http.StatusOK, out)
}

type createRequest struct {
	Email           string  `json:"email"`
	FullName        string  `json:"full_name"`
	Role            string  `json:"role"`
	Phone           *string `json:"phone"`
	Nationality     *string `json:"nationality"`
	YearsExperience *int    `json:"years_experience"`
	CurrentLocation *string `json:"current_location"`
	Gender          *string `json:"gender"`
	IsActive        *bool   `json:"is_active"`
	IsSubscribed    *bool   `json:"is_subscribed"`
	Password        string  `json:"password"`
}

func create(w http.ResponseWriter, r *http.Request) {
	if !flags.IsEnabled("user_registration") {
		metrics.Increment("feature_blocked")
		httpx.WriteError(w, http.StatusServiceUnavailable,
			"User registration is temporarily disabled.", httpx.CRV1008)
		return
	}
	var body createRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	body.Email = strings.ToLower(strings.TrimSpace(body.Email))
	body.FullName = strings.TrimSpace(body.FullName)
	if body.Role == "" {
		body.Role = "crew"
	}
	if !validRoles[body.Role] {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid role.", httpx.CRV1003)
		return
	}
	if body.Email == "" || body.FullName == "" || len(body.Password) < 8 {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "email, full_name and a password (8+ chars) are required.", httpx.CRV1003)
		return
	}

	var existing models.User
	if err := db.DB.Where("email = ?", body.Email).First(&existing).Error; err == nil {
		httpx.WriteError(w, http.StatusConflict, "Email already exists", httpx.CRV1005)
		return
	}

	hash, err := security.HashPassword(body.Password)
	if err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not create user.", httpx.CRV1006)
		return
	}

	user := models.User{
		Email:           body.Email,
		FullName:        body.FullName,
		Role:            body.Role,
		Phone:           body.Phone,
		Nationality:     body.Nationality,
		YearsExperience: body.YearsExperience,
		CurrentLocation: body.CurrentLocation,
		Gender:          body.Gender,
		IsActive:        boolOr(body.IsActive, true),
		PasswordHash:    hash,
		EarlyBird:       isEarlyBird(),
	}
	if err := db.DB.Create(&user).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not create user.", httpx.CRV1002)
		return
	}
	httpx.JSON(w, http.StatusCreated, toRead(user))
}

func get(w http.ResponseWriter, r *http.Request) {
	user, ok := loadUser(w, r)
	if !ok {
		return
	}
	httpx.JSON(w, http.StatusOK, toRead(user))
}

type updateRequest struct {
	FullName        *string `json:"full_name"`
	Role            *string `json:"role"`
	Phone           *string `json:"phone"`
	Nationality     *string `json:"nationality"`
	YearsExperience *int    `json:"years_experience"`
	CurrentLocation *string `json:"current_location"`
	Gender          *string `json:"gender"`
	Password        *string `json:"password"`
	IsActive        *bool   `json:"is_active"`
	IsSubscribed    *bool   `json:"is_subscribed"`
}

func update(w http.ResponseWriter, r *http.Request) {
	user, ok := loadUser(w, r)
	if !ok {
		return
	}
	var body updateRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if body.Role != nil && !validRoles[*body.Role] {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid role.", httpx.CRV1003)
		return
	}
	if body.Password != nil {
		hash, err := security.HashPassword(*body.Password)
		if err != nil {
			httpx.WriteError(w, http.StatusInternalServerError, "Could not update user.", httpx.CRV1006)
			return
		}
		user.PasswordHash = hash
	}
	if body.FullName != nil {
		user.FullName = *body.FullName
	}
	if body.Role != nil {
		user.Role = *body.Role
	}
	if body.Phone != nil {
		user.Phone = body.Phone
	}
	if body.Nationality != nil {
		user.Nationality = body.Nationality
	}
	if body.YearsExperience != nil {
		user.YearsExperience = body.YearsExperience
	}
	if body.CurrentLocation != nil {
		user.CurrentLocation = body.CurrentLocation
	}
	if body.Gender != nil {
		user.Gender = body.Gender
	}
	if body.IsActive != nil {
		user.IsActive = *body.IsActive
	}
	if body.IsSubscribed != nil {
		user.IsSubscribed = *body.IsSubscribed
	}
	db.DB.Save(&user)
	httpx.JSON(w, http.StatusOK, toRead(user))
}

func remove(w http.ResponseWriter, r *http.Request) {
	user, ok := loadUser(w, r)
	if !ok {
		return
	}
	db.DB.Delete(&user)
	httpx.JSON(w, http.StatusNoContent, nil)
}

func loadUser(w http.ResponseWriter, r *http.Request) (models.User, bool) {
	id, err := strconv.Atoi(chi.URLParam(r, "userID"))
	if err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid user id.", httpx.CRV1003)
		return models.User{}, false
	}
	var user models.User
	if err := db.DB.Where("id = ?", id).First(&user).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "User not found", httpx.CRV1005)
		return models.User{}, false
	}
	return user, true
}

// isEarlyBird ports crud._is_early_bird: the new account is an "early bird" while
// there are still fewer than EARLY_BIRD_LIMIT (100) users.
func isEarlyBird() bool {
	const earlyBirdLimit = 100
	var count int64
	db.DB.Model(&models.User{}).Count(&count)
	return count < earlyBirdLimit
}

func boolOr(p *bool, def bool) bool {
	if p == nil {
		return def
	}
	return *p
}
