// Package auth ports api/app/routes/auth.py — provider discovery, waitlist,
// crew/agency signup, login (admin constant-time + crew email/password), logout
// and session introspection. Google ID-token login is stubbed (see login_google).
package auth

import (
	"crypto/subtle"
	"net/http"
	"regexp"
	"strings"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/config"
	"jobcarver/internal/credits"
	"jobcarver/internal/db"
	"jobcarver/internal/flags"
	"jobcarver/internal/httpx"
	"jobcarver/internal/metrics"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

var emailRE = regexp.MustCompile(`^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$`)

// Register mounts the /auth routes.
func Register(r chi.Router) {
	r.Route("/auth", func(r chi.Router) {
		r.Get("/providers", providers)
		r.Post("/waitlist", waitlist)
		r.Post("/signup", signup)
		r.Post("/signup-agency", signupAgency)
		r.Post("/login", login)
		r.Post("/google", loginGoogle)
		r.Post("/logout", logout)
		r.With(security.OptionalSession).Get("/session", getSession)
	})
}

// sameSite mirrors auth.py: SameSite=None requires Secure=true; otherwise Lax.
func sameSite() http.SameSite {
	if config.S.SessionSecureCookie {
		return http.SameSiteNoneMode
	}
	return http.SameSiteLaxMode
}

func setSessionCookie(w http.ResponseWriter, token string) {
	http.SetCookie(w, &http.Cookie{
		Name:     config.S.SessionCookieName,
		Value:    token,
		Path:     "/",
		HttpOnly: true,
		Secure:   config.S.SessionSecureCookie,
		SameSite: sameSite(),
		MaxAge:   config.S.SessionTTLSeconds,
	})
}

func clearSessionCookie(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     config.S.SessionCookieName,
		Value:    "",
		Path:     "/",
		HttpOnly: true,
		Secure:   config.S.SessionSecureCookie,
		SameSite: sameSite(),
		MaxAge:   -1,
	})
}

func googleAuthEnabled() bool { return config.S.GoogleOAuthClientID != "" }

func providers(w http.ResponseWriter, _ *http.Request) {
	enabled := googleAuthEnabled()
	var clientID any
	if enabled {
		clientID = config.S.GoogleOAuthClientID
	}
	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok": true,
		"google": map[string]any{
			"enabled":   enabled,
			"client_id": clientID,
		},
	})
}

type waitlistRequest struct {
	Email string `json:"email"`
}

func waitlist(w http.ResponseWriter, r *http.Request) {
	var body waitlistRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	email := strings.ToLower(strings.TrimSpace(body.Email))
	if email == "" || len(email) < 5 || !emailRE.MatchString(email) {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Email is required.", httpx.CRV1003)
		return
	}
	// Neutral response on duplicate so membership isn't leaked.
	if err := db.DB.Create(&models.WaitlistSignup{Email: email, Source: "website"}).Error; err != nil {
		httpx.JSON(w, http.StatusCreated, map[string]any{"ok": true})
		return
	}
	httpx.JSON(w, http.StatusCreated, map[string]any{"ok": true})
}

type signupRequest struct {
	Email    string `json:"email"`
	FullName string `json:"full_name"`
	Password string `json:"password"`
}

func signup(w http.ResponseWriter, r *http.Request) {
	if !flags.IsEnabled("user_registration") {
		metrics.Increment("feature_blocked")
		httpx.WriteError(w, http.StatusServiceUnavailable, "Registration is temporarily disabled.", httpx.CRV1008)
		return
	}
	var body signupRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	email := strings.ToLower(strings.TrimSpace(body.Email))
	fullName := strings.TrimSpace(body.FullName)
	if !emailRE.MatchString(email) || fullName == "" || len(body.Password) < 8 {
		httpx.WriteError(w, http.StatusUnprocessableEntity,
			"A valid email, full name and password (8+ chars) are required.", httpx.CRV1003)
		return
	}
	if emailExists(email) {
		httpx.WriteError(w, http.StatusConflict, "An account with this email already exists.", httpx.CRV2009)
		return
	}

	hash, err := security.HashPassword(body.Password)
	if err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not create account.", httpx.CRV1006)
		return
	}
	user := models.User{
		Email:        email,
		FullName:     fullName,
		Role:         "crew",
		PasswordHash: hash,
		IsActive:     true,
		EarlyBird:    isEarlyBird(),
	}
	if err := db.DB.Create(&user).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not create account.", httpx.CRV1002)
		return
	}

	token, err := security.IssueSessionToken(security.Session{Sub: email, Role: "crew", UserID: user.ID})
	if err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not issue session.", httpx.CRV1006)
		return
	}
	setSessionCookie(w, token)
	metrics.Increment("signups_success")
	httpx.JSON(w, http.StatusCreated, map[string]any{
		"ok":   true,
		"user": map[string]any{"id": user.ID, "email": email, "role": "crew"},
	})
}

type agencySignupRequest struct {
	Email      string `json:"email"`
	FullName   string `json:"full_name"`
	AgencyName string `json:"agency_name"`
	Password   string `json:"password"`
}

func signupAgency(w http.ResponseWriter, r *http.Request) {
	if !flags.IsEnabled("user_registration") {
		metrics.Increment("feature_blocked")
		httpx.WriteError(w, http.StatusServiceUnavailable, "Registration is temporarily disabled.", httpx.CRV1008)
		return
	}
	var body agencySignupRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	email := strings.ToLower(strings.TrimSpace(body.Email))
	fullName := strings.TrimSpace(body.FullName)
	agencyName := strings.TrimSpace(body.AgencyName)
	if !emailRE.MatchString(email) || fullName == "" || agencyName == "" || len(body.Password) < 8 {
		httpx.WriteError(w, http.StatusUnprocessableEntity,
			"A valid email, full name, agency name and password (8+ chars) are required.", httpx.CRV1003)
		return
	}
	if emailExists(email) {
		httpx.WriteError(w, http.StatusConflict, "An account with this email already exists.", httpx.CRV2009)
		return
	}

	hash, err := security.HashPassword(body.Password)
	if err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not create account.", httpx.CRV1006)
		return
	}
	user := models.User{
		Email:        email,
		FullName:     fullName,
		Role:         "agency",
		AgencyName:   &agencyName,
		PasswordHash: hash,
		IsActive:     true,
		EarlyBird:    isEarlyBird(),
	}
	if err := db.DB.Create(&user).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not create account.", httpx.CRV1002)
		return
	}

	token, err := security.IssueSessionToken(security.Session{Sub: email, Role: "agency", UserID: user.ID})
	if err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not issue session.", httpx.CRV1006)
		return
	}
	setSessionCookie(w, token)
	metrics.Increment("signups_success")
	httpx.JSON(w, http.StatusCreated, map[string]any{
		"ok":   true,
		"user": map[string]any{"id": user.ID, "email": email, "role": "agency", "agency_name": agencyName},
	})
}

type loginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

func login(w http.ResponseWriter, r *http.Request) {
	var body loginRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	username := strings.TrimSpace(body.Username)

	// ── Admin login (constant-time comparison) ──
	usernameOK := subtle.ConstantTimeCompare([]byte(username), []byte(config.S.AdminUsername)) == 1
	passwordOK := subtle.ConstantTimeCompare([]byte(body.Password), []byte(config.S.AdminPassword)) == 1
	if usernameOK && passwordOK {
		token, err := security.IssueSessionToken(security.Session{Sub: username, Role: "admin"})
		if err != nil {
			httpx.WriteError(w, http.StatusInternalServerError, "Could not issue session.", httpx.CRV1006)
			return
		}
		setSessionCookie(w, token)
		metrics.Increment("logins_success")
		httpx.JSON(w, http.StatusOK, map[string]any{
			"ok":   true,
			"user": map[string]any{"username": username, "role": "admin"},
		})
		return
	}

	// ── Crew/agency user login by email/password ──
	email := strings.ToLower(username)
	var user models.User
	if err := db.DB.Where("email = ?", email).First(&user).Error; err == nil &&
		user.PasswordHash != "" && security.VerifyPassword(body.Password, user.PasswordHash) {
		token, err := security.IssueSessionToken(security.Session{Sub: user.Email, Role: user.Role, UserID: user.ID})
		if err != nil {
			httpx.WriteError(w, http.StatusInternalServerError, "Could not issue session.", httpx.CRV1006)
			return
		}
		setSessionCookie(w, token)
		metrics.Increment("logins_success")
		httpx.JSON(w, http.StatusOK, map[string]any{
			"ok":   true,
			"user": map[string]any{"email": user.Email, "role": user.Role},
		})
		return
	}

	metrics.Increment("logins_failed")
	httpx.WriteError(w, http.StatusUnauthorized, "Invalid credentials", httpx.CRV2002)
}

type googleLoginRequest struct {
	IDToken string `json:"id_token"`
}

func loginGoogle(w http.ResponseWriter, r *http.Request) {
	// TODO(go-port): real Google ID-token verification (google.oauth2.id_token in
	// the Python version) is out of scope for this port. When disabled we mirror
	// the Python 503; otherwise we return 501 until a Go verifier is wired in.
	if !googleAuthEnabled() {
		httpx.WriteError(w, http.StatusServiceUnavailable, "Google login is not enabled", httpx.CRV2007)
		return
	}
	httpx.WriteError(w, http.StatusNotImplemented,
		"Google login is not implemented in the Go port yet.", httpx.CRV2007)
}

func logout(w http.ResponseWriter, _ *http.Request) {
	clearSessionCookie(w)
	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true})
}

func getSession(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	if sess == nil {
		httpx.JSON(w, http.StatusOK, map[string]any{"ok": true, "authenticated": false})
		return
	}
	userKey := sess.Sub

	isSubscribed := sess.Role == "admin"
	if !isSubscribed && userKey != "" {
		isSubscribed = credits.IsSubscribed(db.DB, userKey)
	}

	balance := 0
	if userKey != "" {
		balance = credits.GetBalance(db.DB, userKey)
	}

	earlyBird := false
	var agencyName any
	if userKey != "" {
		var user models.User
		if err := db.DB.Select("early_bird", "agency_name").Where("email = ?", userKey).First(&user).Error; err == nil {
			earlyBird = user.EarlyBird
			if sess.Role == "agency" && user.AgencyName != nil {
				agencyName = *user.AgencyName
			}
		}
	}

	session := map[string]any{
		"sub":             sess.Sub,
		"role":            sess.Role,
		"is_subscribed":   isSubscribed,
		"early_bird":      earlyBird,
		"credits_balance": balance,
		"agency_name":     agencyName,
	}
	if sess.UserID != 0 {
		session["user_id"] = sess.UserID
	}
	if sess.Provider != "" {
		session["provider"] = sess.Provider
	}
	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok":            true,
		"authenticated": true,
		"session":       session,
	})
}

func emailExists(email string) bool {
	var user models.User
	return db.DB.Where("email = ?", email).First(&user).Error == nil
}

// isEarlyBird ports crud._is_early_bird: true while there are fewer than 100 users.
func isEarlyBird() bool {
	const earlyBirdLimit = 100
	var count int64
	db.DB.Model(&models.User{}).Count(&count)
	return count < earlyBirdLimit
}
