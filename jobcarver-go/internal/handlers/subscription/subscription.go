// Package subscription ports api/app/routes/subscription.py: token-pack listing,
// Yoco checkout creation and the Yoco payment webhook.
//
// The outbound Yoco checkout HTTP POST is STUBBED — there is no network access
// and no live Yoco key here — so create_checkout returns a deterministic fake
// checkout id + redirect URL while keeping all Subscription/CreditAccount DB
// logic real. The webhook signature verification (local HMAC-SHA256) is ported
// faithfully and crediting goes through credits.Grant with the first-purchase
// bonus. TODO(go-port): replace the stubbed checkout create with a real POST to
// https://payments.yoco.com/api/checkouts.
package subscription

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"jobcarver/internal/config"
	"jobcarver/internal/credits"
	"jobcarver/internal/db"
	"jobcarver/internal/httpx"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

// Register mounts /subscription. /checkout and /status need a session; /webhook
// is public (verified by signature).
func Register(r chi.Router) {
	r.Route("/subscription", func(r chi.Router) {
		r.Group(func(r chi.Router) {
			r.Use(security.RequireSession)
			r.Post("/checkout", createCheckout)
			r.Get("/status", subscriptionStatus)
		})
		r.Post("/webhook", yocoWebhook)
	})
}

func amountStrToCents(s string) int {
	f, _ := strconv.ParseFloat(strings.TrimSpace(s), 64)
	return int(math.Round(f * 100))
}

func yocoConfigured() bool { return config.S.YocoSecretKey != "" }

func findPackage(tokens int) *config.TokenPackage {
	for i := range config.S.TokenPackages {
		if config.S.TokenPackages[i].Tokens == tokens {
			return &config.S.TokenPackages[i]
		}
	}
	return nil
}

func packageForAmount(cents int) *config.TokenPackage {
	for i := range config.S.TokenPackages {
		if amountStrToCents(config.S.TokenPackages[i].Price) == cents {
			return &config.S.TokenPackages[i]
		}
	}
	return nil
}

// isFirstPurchase ports _is_first_purchase.
func isFirstPurchase(userKey, excludePaymentID string) bool {
	q := db.DB.Model(&models.Subscription{}).
		Where("user_key = ? AND status = ?", userKey, "completed")
	if excludePaymentID != "" {
		q = q.Where("m_payment_id != ?", excludePaymentID)
	}
	var count int64
	q.Count(&count)
	return count == 0
}

type checkoutRequest struct {
	Tokens int `json:"tokens"`
}

func createCheckout(w http.ResponseWriter, r *http.Request) {
	if !yocoConfigured() {
		httpx.WriteError(w, http.StatusServiceUnavailable,
			"Payment provider is not configured yet.", httpx.CRV1008)
		return
	}
	var body checkoutRequest
	if err := httpx.Decode(r, &body); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	pkg := findPackage(body.Tokens)
	if pkg == nil {
		var valid []int
		for _, p := range config.S.TokenPackages {
			valid = append(valid, p.Tokens)
		}
		httpx.WriteError(w, http.StatusBadRequest,
			fmt.Sprintf("Invalid package. Choose one of: %v", valid), httpx.CRV1003)
		return
	}

	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub
	paymentID := strings.ReplaceAll(uuid.NewString(), "-", "")
	cents := amountStrToCents(pkg.Price)
	amountStr := fmt.Sprintf("%.2f", float64(cents)/100)

	// Clear any stale pending row for this user.
	db.DB.Where("user_key = ? AND status = ?", userKey, "pending").Delete(&models.Subscription{})

	sub := models.Subscription{
		UserKey:    userKey,
		MPaymentID: paymentID,
		Status:     "pending",
		Amount:     amountStr,
		Frequency:  0,
	}
	if err := db.DB.Create(&sub).Error; err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not start checkout.", httpx.CRV1002)
		return
	}

	// TODO(go-port): POST to YOCO_CHECKOUTS_URL with Bearer YocoSecretKey +
	// Idempotency-Key, parse redirectUrl + id. Stubbed below with a deterministic
	// fake checkout id + redirect URL so the DB flow stays exercisable.
	frontendBase := strings.TrimRight(config.S.FrontendBaseURL, "/")
	checkoutID := "stub_checkout_" + paymentID
	redirectURL := fmt.Sprintf("%s/subscription?status=success&stub=1&ref=%s", frontendBase, paymentID)

	sub.CheckoutID = &checkoutID
	db.DB.Save(&sub)

	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok":           true,
		"redirect_url": redirectURL,
	})
}

// verifyYocoWebhookSignature ports _verify_yoco_webhook_signature.
func verifyYocoWebhookSignature(rawBody []byte, webhookID, webhookTimestamp, signatureHeader, secret string) bool {
	if webhookID == "" || webhookTimestamp == "" || signatureHeader == "" {
		return false
	}
	ts, err := strconv.ParseInt(webhookTimestamp, 10, 64)
	if err != nil {
		return false
	}
	if abs64(time.Now().Unix()-ts) > 180 {
		return false
	}
	if !strings.HasPrefix(secret, "whsec_") {
		return false
	}
	secretBytes, err := base64.StdEncoding.DecodeString(strings.SplitN(secret, "_", 2)[1])
	if err != nil {
		return false
	}
	signedContent := webhookID + "." + webhookTimestamp + "." + string(rawBody)
	mac := hmac.New(sha256.New, secretBytes)
	mac.Write([]byte(signedContent))
	expected := base64.StdEncoding.EncodeToString(mac.Sum(nil))
	for _, part := range strings.Fields(signatureHeader) {
		idx := strings.Index(part, ",")
		if idx < 0 {
			continue
		}
		sig := strings.TrimSpace(part[idx+1:])
		if subtle.ConstantTimeCompare([]byte(sig), []byte(expected)) == 1 {
			return true
		}
	}
	return false
}

func abs64(v int64) int64 {
	if v < 0 {
		return -v
	}
	return v
}

func yocoWebhook(w http.ResponseWriter, r *http.Request) {
	raw, _ := io.ReadAll(r.Body)
	whID := r.Header.Get("webhook-id")
	whTS := r.Header.Get("webhook-timestamp")
	whSig := r.Header.Get("webhook-signature")

	if config.S.YocoWebhookSecret == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable, "Webhook not configured", httpx.CRV1008)
		return
	}
	if !verifyYocoWebhookSignature(raw, whID, whTS, whSig, config.S.YocoWebhookSecret) {
		httpx.WriteError(w, http.StatusForbidden, "Invalid signature", httpx.CRV2006)
		return
	}

	var event struct {
		Type    string `json:"type"`
		Payload struct {
			ID       any            `json:"id"`
			Amount   *int           `json:"amount"`
			Metadata map[string]any `json:"metadata"`
		} `json:"payload"`
	}
	if err := json.Unmarshal(raw, &event); err != nil {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid JSON", httpx.CRV1003)
		return
	}

	meta := event.Payload.Metadata
	mPaymentID := metaString(meta, "m_payment_id")
	if mPaymentID == "" {
		httpx.WriteError(w, http.StatusBadRequest, "Missing reference", httpx.CRV1003)
		return
	}

	var sub models.Subscription
	if err := db.DB.Where("m_payment_id = ?", mPaymentID).First(&sub).Error; err != nil {
		httpx.WriteError(w, http.StatusNotFound, "Subscription not found", httpx.CRV1005)
		return
	}

	switch event.Type {
	case "payment.succeeded":
		if sub.Status == "completed" {
			// At-least-once delivery: tokens already credited on first delivery.
			httpx.JSON(w, http.StatusOK, map[string]any{"ok": true})
			return
		}
		if event.Payload.Amount != nil {
			expected := amountStrToCents(sub.Amount)
			if *event.Payload.Amount != expected {
				httpx.WriteError(w, http.StatusBadRequest, "Amount mismatch", httpx.CRV1003)
				return
			}
		}

		firstPurchase := isFirstPurchase(sub.UserKey, sub.MPaymentID)

		sub.Status = "completed"
		if id := anyToString(event.Payload.ID); id != "" {
			sub.PaymentToken = &id
		}
		db.DB.Save(&sub)

		tokens := metaInt(meta, "tokens")
		if tokens > 0 {
			_ = credits.Grant(db.DB, sub.UserKey, tokens)
		} else if pkg := packageForAmount(amountStrToCents(sub.Amount)); pkg != nil {
			_ = credits.Grant(db.DB, sub.UserKey, pkg.Tokens)
		}

		bonus := config.S.FirstPurchaseBonusTokens
		if firstPurchase && bonus > 0 {
			_ = credits.Grant(db.DB, sub.UserKey, bonus)
		}
	case "payment.failed":
		sub.Status = "failed"
		db.DB.Save(&sub)
	default:
		// ignored event type
	}

	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true})
}

func subscriptionStatus(w http.ResponseWriter, r *http.Request) {
	sess := security.SessionFromContext(r.Context())
	userKey := sess.Sub
	balance := credits.GetBalance(db.DB, userKey)

	packages := make([]map[string]any, 0, len(config.S.TokenPackages))
	for _, p := range config.S.TokenPackages {
		label := p.Label
		if label == "" {
			label = fmt.Sprintf("%d Token Pack", p.Tokens)
		}
		price, _ := strconv.ParseFloat(p.Price, 64)
		perToken := "0.00"
		if p.Tokens > 0 {
			perToken = fmt.Sprintf("%.2f", price/float64(p.Tokens))
		}
		var badge any
		if p.Badge != "" {
			badge = p.Badge
		}
		packages = append(packages, map[string]any{
			"tokens":          p.Tokens,
			"price":           p.Price,
			"label":           label,
			"badge":           badge,
			"highlight":       p.Highlight,
			"price_per_token": perToken,
		})
	}

	bonus := config.S.FirstPurchaseBonusTokens
	firstBonus := 0
	if bonus > 0 && isFirstPurchase(userKey, "") {
		firstBonus = bonus
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok":                   true,
		"balance":              balance,
		"token_price":          config.S.TokenPrice,
		"packages":             packages,
		"first_purchase_bonus": firstBonus,
	})
}

// ── metadata helpers (Yoco metadata values arrive as strings or numbers) ──

func metaString(m map[string]any, key string) string {
	if m == nil {
		return ""
	}
	return anyToString(m[key])
}

func metaInt(m map[string]any, key string) int {
	if m == nil {
		return 0
	}
	switch v := m[key].(type) {
	case float64:
		return int(v)
	case string:
		n, _ := strconv.Atoi(strings.TrimSpace(v))
		return n
	}
	return 0
}

func anyToString(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case float64:
		if t == math.Trunc(t) {
			return strconv.FormatInt(int64(t), 10)
		}
		return strconv.FormatFloat(t, 'f', -1, 64)
	case nil:
		return ""
	default:
		return fmt.Sprintf("%v", t)
	}
}
