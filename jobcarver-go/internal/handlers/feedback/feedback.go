// Package feedback ports api/app/routes/feedback.py plus the relevant pieces of
// app/services/feedback_settings.py (campaign settings + eligibility) so the
// handler stays self-contained.
package feedback

import (
	"encoding/json"
	"net/http"
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

const (
	feedbackCampaign     = "feedback_2_tokens"
	feedbackRewardTokens = 0 // reward currently disabled; submissions still recorded
)

var validTargetModes = map[string]bool{"all": true, "website": true, "whatsapp": true, "specific": true, "off": true}

// Register mounts /feedback (all routes require a session).
func Register(r chi.Router) {
	r.Route("/feedback", func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Get("/status", status)
		r.Post("/submit", submit)
	})
}

func status(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub

	source := r.URL.Query().Get("source")
	safeSource := "website_popup"
	if source == "whatsapp_message" {
		safeSource = "whatsapp_message"
	}

	setting := getFeedbackSetting()
	eligible := feedbackIsEligible(setting, userKey, safeSource)

	var cnt int64
	db.DB.Model(&models.FeedbackSubmission{}).
		Where("user_key = ? AND campaign = ?", userKey, feedbackCampaign).Count(&cnt)

	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok":            true,
		"submitted":     cnt > 0,
		"eligible":      eligible,
		"force_prompt":  eligible && setting.TargetMode == "specific",
		"target_mode":   setting.TargetMode,
		"reward_amount": feedbackRewardTokens,
	})
}

type submitRequest struct {
	Source       string  `json:"source"`
	Rating       int     `json:"rating"`
	Liked        *string `json:"liked"`
	Improved     *string `json:"improved"`
	Confusing    *string `json:"confusing"`
	Recommend    *string `json:"recommend"`
	AnythingElse *string `json:"anything_else"`
}

func submit(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub
	if userKey == "" {
		httpx.WriteError(w, http.StatusUnauthorized, "Authentication required.", httpx.CRV2004)
		return
	}

	var body submitRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if body.Source == "" {
		body.Source = "website_popup"
	}
	if body.Source != "website_popup" && body.Source != "whatsapp_message" {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid source.", httpx.CRV1003)
		return
	}
	if body.Rating < 1 || body.Rating > 5 {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "rating must be between 1 and 5.", httpx.CRV1003)
		return
	}
	if body.Recommend != nil {
		switch *body.Recommend {
		case "yes", "no", "maybe":
		default:
			httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid recommend value.", httpx.CRV1003)
			return
		}
	}
	stripOptional(&body.Liked)
	stripOptional(&body.Improved)
	stripOptional(&body.Confusing)
	stripOptional(&body.AnythingElse)

	setting := getFeedbackSetting()
	if !feedbackIsEligible(setting, userKey, body.Source) {
		httpx.WriteError(w, http.StatusForbidden,
			"Feedback reward is not available for this account right now.", httpx.CRV2005)
		return
	}

	var existing int64
	db.DB.Model(&models.FeedbackSubmission{}).
		Where("user_key = ? AND campaign = ?", userKey, feedbackCampaign).Count(&existing)
	if existing > 0 {
		httpx.JSON(w, http.StatusCreated, map[string]any{
			"ok":              true,
			"submitted":       true,
			"reward_granted":  false,
			"reward_amount":   feedbackRewardTokens,
			"credits_balance": credits.GetBalance(db.DB, userKey),
		})
		return
	}

	submission := models.FeedbackSubmission{
		UserKey:      userKey,
		Campaign:     feedbackCampaign,
		Source:       body.Source,
		Rating:       body.Rating,
		Liked:        body.Liked,
		Improved:     body.Improved,
		Confusing:    body.Confusing,
		Recommend:    body.Recommend,
		AnythingElse: body.AnythingElse,
		RewardAmount: feedbackRewardTokens,
		Rewarded:     feedbackRewardTokens > 0,
	}
	if err := db.DB.Create(&submission).Error; err != nil {
		// Likely the (user_key, campaign) unique constraint — treat as already submitted.
		httpx.JSON(w, http.StatusCreated, map[string]any{
			"ok":              true,
			"submitted":       true,
			"reward_granted":  false,
			"reward_amount":   feedbackRewardTokens,
			"credits_balance": credits.GetBalance(db.DB, userKey),
		})
		return
	}

	if feedbackRewardTokens > 0 {
		_ = credits.Grant(db.DB, userKey, feedbackRewardTokens)
	}
	balance := credits.GetBalance(db.DB, userKey)
	metrics.Increment("feedback_submissions")
	httpx.JSON(w, http.StatusCreated, map[string]any{
		"ok":              true,
		"submitted":       true,
		"reward_granted":  feedbackRewardTokens > 0,
		"reward_amount":   feedbackRewardTokens,
		"credits_balance": balance,
	})
}

func stripOptional(p **string) {
	if *p == nil {
		return
	}
	s := strings.TrimSpace(**p)
	if s == "" {
		*p = nil
		return
	}
	*p = &s
}

// getFeedbackSetting mirrors feedback_settings.get_feedback_setting: load (or
// lazily create) the single campaign row, normalising an invalid target_mode.
func getFeedbackSetting() models.FeedbackCampaignSetting {
	var setting models.FeedbackCampaignSetting
	err := db.DB.Where("campaign = ?", feedbackCampaign).First(&setting).Error
	if err == nil {
		if !validTargetModes[setting.TargetMode] {
			setting.TargetMode = "all"
			db.DB.Save(&setting)
		}
		return setting
	}
	setting = models.FeedbackCampaignSetting{
		Campaign:           feedbackCampaign,
		Enabled:            true,
		TargetMode:         "all",
		TargetUserKeysJSON: "[]",
	}
	db.DB.Create(&setting)
	return setting
}

func feedbackIsEligible(setting models.FeedbackCampaignSetting, userKey, source string) bool {
	mode := setting.TargetMode
	if !validTargetModes[mode] {
		mode = "all"
	}
	if !setting.Enabled || mode == "off" {
		return false
	}

	var modeEligible bool
	switch mode {
	case "all":
		modeEligible = true
	case "website":
		modeEligible = source == "website_popup"
	case "whatsapp":
		modeEligible = source == "whatsapp_message"
	case "specific":
		targets := parseTargets(setting.TargetUserKeysJSON)
		modeEligible = targets[normaliseUserKey(userKey)]
	}
	if !modeEligible {
		return false
	}
	if source == "website_popup" && !userOldEnoughForWebsiteFeedback(userKey) {
		return false
	}
	return true
}

func userOldEnoughForWebsiteFeedback(userKey string) bool {
	minAgeHours := config.S.FeedbackMinAccountAgeHours
	if minAgeHours <= 0 {
		return true
	}
	key := normaliseUserKey(userKey)
	if key == "" {
		return false
	}
	var user models.User
	if err := db.DB.Select("created_at").Where("email = ?", key).First(&user).Error; err != nil {
		// No website user row (admin/phone identities) — keep compatible.
		return true
	}
	age := time.Since(user.CreatedAt)
	return age >= time.Duration(minAgeHours)*time.Hour
}

func parseTargets(raw string) map[string]bool {
	out := map[string]bool{}
	var items []string
	if json.Unmarshal([]byte(raw), &items) != nil {
		return out
	}
	for _, it := range items {
		if k := normaliseUserKey(it); k != "" {
			out[k] = true
		}
	}
	return out
}

func normaliseUserKey(k string) string {
	return strings.ToLower(strings.TrimSpace(k))
}
