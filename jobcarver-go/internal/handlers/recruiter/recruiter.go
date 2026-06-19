// Package recruiter ports api/app/routes/recruiter.py: agencies browse the
// discoverable crew pool (no contact details) and spend RECRUITER_UNLOCK_COST_TOKENS
// to unlock a candidate's email/phone, recorded in a ContactUnlock row. All token
// spend goes through credits.Spend; all DB logic is real.
package recruiter

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/config"
	"jobcarver/internal/credits"
	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

// Register mounts /recruiter (agency or admin session required).
func Register(r chi.Router) {
	r.Route("/recruiter", func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Use(agencyOrAdmin)
		r.Get("/candidates", listCandidates)
		r.Get("/unlocked", listUnlocked)
		r.Post("/candidates/{slug}/unlock", unlockCandidate)
	})
}

// agencyOrAdmin ports require_agency_or_admin_session.
func agencyOrAdmin(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sess := security.SessionFromContext(r.Context())
		if sess == nil || (sess.Role != "agency" && sess.Role != "admin") {
			httpx.WriteError(w, http.StatusForbidden,
				"Sign in as an agency to use this feature.", httpx.CRV2005)
			return
		}
		next.ServeHTTP(w, r)
	})
}

type candidate struct {
	ProfileSlug     string  `json:"profile_slug"`
	FirstName       *string `json:"first_name"`
	LastName        *string `json:"last_name"`
	Nationality     *string `json:"nationality"`
	CurrentLocation *string `json:"current_location"`
	DesiredRole     *string `json:"desired_role"`
	ContractType    *string `json:"contract_type"`
	YearsExperience *string `json:"years_experience"`
	AvailableFrom   *string `json:"available_from"`
	Certifications  *string `json:"certifications"`
	Languages       *string `json:"languages"`
	Bio             *string `json:"bio"`
	HasCV           bool    `json:"has_cv"`
	HasPhoto        bool    `json:"has_photo"`
	PhotoURL        *string `json:"photo_url"`
	Unlocked        bool    `json:"unlocked"`
	Email           *string `json:"email"`
	Phone           *string `json:"phone"`
}

type candidateList struct {
	Candidates []candidate `json:"candidates"`
	Total      int64       `json:"total"`
	UnlockCost int         `json:"unlock_cost"`
	Balance    int         `json:"balance"`
}

type unlockResponse struct {
	OK              bool    `json:"ok"`
	AlreadyUnlocked bool    `json:"already_unlocked"`
	Cost            int     `json:"cost"`
	Balance         int     `json:"balance"`
	Email           *string `json:"email"`
	Phone           *string `json:"phone"`
}

// docFlags ports _doc_flags: (has_cv, has_photo, photo_url).
func docFlags(userKey, slug string) (bool, bool, *string) {
	var docTypes []string
	db.DB.Model(&models.Document{}).Where("user_key = ?", userKey).Pluck("doc_type", &docTypes)
	set := map[string]bool{}
	for _, d := range docTypes {
		set[d] = true
	}
	var photoURL *string
	if set["photo"] {
		u := "/p/" + slug + "/photo"
		photoURL = &u
	}
	return set["cv"], set["photo"], photoURL
}

// resolveContact ports _resolve_contact: best-effort email + phone.
func resolveContact(profile models.CrewProfile) (*string, *string) {
	var user models.User
	hasUser := db.DB.Where("email = ?", profile.UserKey).First(&user).Error == nil
	isEmailKey := strings.Contains(profile.UserKey, "@")

	var email *string
	if hasUser {
		e := user.Email
		email = &e
	} else if isEmailKey {
		k := profile.UserKey
		email = &k
	}

	var phone *string
	if profile.Phone != nil && *profile.Phone != "" {
		phone = profile.Phone
	} else if hasUser && user.Phone != nil && *user.Phone != "" {
		phone = user.Phone
	}
	if phone == nil && !isEmailKey {
		k := profile.UserKey // WhatsApp crew keyed by phone
		phone = &k
	}
	return email, phone
}

func buildCandidate(profile models.CrewProfile, unlocked, withContact bool) candidate {
	hasCV, hasPhoto, photoURL := docFlags(profile.UserKey, profile.ProfileSlug)
	var email, phone *string
	if unlocked && withContact {
		email, phone = resolveContact(profile)
	}
	return candidate{
		ProfileSlug:     profile.ProfileSlug,
		FirstName:       profile.FirstName,
		LastName:        profile.LastName,
		Nationality:     profile.Nationality,
		CurrentLocation: profile.CurrentLocation,
		DesiredRole:     profile.DesiredRole,
		ContractType:    profile.ContractType,
		YearsExperience: profile.YearsExperience,
		AvailableFrom:   profile.AvailableFrom,
		Certifications:  profile.Certifications,
		Languages:       profile.Languages,
		Bio:             profile.Bio,
		HasCV:           hasCV,
		HasPhoto:        hasPhoto,
		PhotoURL:        photoURL,
		Unlocked:        unlocked,
		Email:           email,
		Phone:           phone,
	}
}

func listCandidates(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	agencyKey := sess.Sub

	limit := clampInt(queryInt(r, "limit", 50), 1, 100)
	offset := queryInt(r, "offset", 0)
	if offset < 0 {
		offset = 0
	}

	q := db.DB.Model(&models.CrewProfile{}).Where("discoverable = ?", true)
	if role := r.URL.Query().Get("role"); role != "" {
		q = q.Where("desired_role LIKE ?", "%"+role+"%")
	}
	if location := r.URL.Query().Get("location"); location != "" {
		q = q.Where("current_location LIKE ? OR preferred_locations LIKE ?", "%"+location+"%", "%"+location+"%")
	}
	if term := r.URL.Query().Get("q"); term != "" {
		like := "%" + term + "%"
		q = q.Where("first_name LIKE ? OR last_name LIKE ? OR bio LIKE ? OR certifications LIKE ?", like, like, like, like)
	}

	var total int64
	q.Count(&total)

	var profiles []models.CrewProfile
	q.Order("updated_at DESC").Offset(offset).Limit(limit).Find(&profiles)

	unlockedKeys := agencyUnlockedKeys(agencyKey)

	candidates := make([]candidate, 0, len(profiles))
	for _, p := range profiles {
		unlocked := unlockedKeys[p.UserKey]
		candidates = append(candidates, buildCandidate(p, unlocked, unlocked))
	}

	httpx.JSON(w, http.StatusOK, candidateList{
		Candidates: candidates,
		Total:      total,
		UnlockCost: config.S.RecruiterUnlockCostTokens,
		Balance:    credits.GetBalance(db.DB, agencyKey),
	})
}

func listUnlocked(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	agencyKey := sess.Sub

	var unlocks []models.ContactUnlock
	db.DB.Where("agency_user_key = ?", agencyKey).Order("created_at DESC").Find(&unlocks)

	candidates := make([]candidate, 0, len(unlocks))
	for _, u := range unlocks {
		var profile models.CrewProfile
		if db.DB.Where("user_key = ?", u.CrewUserKey).First(&profile).Error == nil {
			candidates = append(candidates, buildCandidate(profile, true, true))
		}
	}

	httpx.JSON(w, http.StatusOK, candidateList{
		Candidates: candidates,
		Total:      int64(len(candidates)),
		UnlockCost: config.S.RecruiterUnlockCostTokens,
		Balance:    credits.GetBalance(db.DB, agencyKey),
	})
}

func unlockCandidate(w http.ResponseWriter, r *http.Request) {
	slug := chi.URLParam(r, "slug")
	if len(slug) > 16 {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid slug.", httpx.CRV1003)
		return
	}
	sess := security.SessionFromContext(r.Context())
	agencyKey := sess.Sub

	var profile models.CrewProfile
	if err := db.DB.Where("profile_slug = ? AND discoverable = ?", slug, true).First(&profile).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "Candidate not found.", httpx.CRV1005)
		return
	}

	email, phone := resolveContact(profile)

	var existing models.ContactUnlock
	if db.DB.Where("agency_user_key = ? AND crew_user_key = ?", agencyKey, profile.UserKey).First(&existing).Error == nil {
		httpx.JSON(w, http.StatusOK, unlockResponse{
			OK: true, AlreadyUnlocked: true, Cost: 0,
			Balance: credits.GetBalance(db.DB, agencyKey), Email: email, Phone: phone,
		})
		return
	}

	cost := config.S.RecruiterUnlockCostTokens
	if err := credits.Spend(db.DB, agencyKey, cost); err != nil {
		httpx.WriteError(w, http.StatusPaymentRequired,
			"You need "+strconv.Itoa(cost)+" tokens to unlock this candidate. Top up to continue.", httpx.CRV1004)
		return
	}

	unlock := models.ContactUnlock{
		AgencyUserKey: agencyKey,
		CrewUserKey:   profile.UserKey,
		ProfileSlug:   slug,
		CostTokens:    cost,
	}
	if err := db.DB.Create(&unlock).Error; err != nil {
		// A concurrent request unlocked the same candidate first (unique index).
		// Refund the tokens just spent and return the contact for free.
		_ = credits.Grant(db.DB, agencyKey, cost)
		httpx.JSON(w, http.StatusOK, unlockResponse{
			OK: true, AlreadyUnlocked: true, Cost: 0,
			Balance: credits.GetBalance(db.DB, agencyKey), Email: email, Phone: phone,
		})
		return
	}

	httpx.JSON(w, http.StatusOK, unlockResponse{
		OK: true, AlreadyUnlocked: false, Cost: cost,
		Balance: credits.GetBalance(db.DB, agencyKey), Email: email, Phone: phone,
	})
}

func agencyUnlockedKeys(agencyKey string) map[string]bool {
	var keys []string
	db.DB.Model(&models.ContactUnlock{}).
		Where("agency_user_key = ?", agencyKey).Pluck("crew_user_key", &keys)
	out := make(map[string]bool, len(keys))
	for _, k := range keys {
		out[k] = true
	}
	return out
}

func queryInt(r *http.Request, key string, def int) int {
	raw := r.URL.Query().Get(key)
	if raw == "" {
		return def
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		return def
	}
	return v
}

func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
