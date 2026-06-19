package security

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"net/http"
	"strconv"
	"strings"
	"time"

	"jobcarver/internal/config"
)

// CSRF protection ports api/app/csrf.py: a signed, timestamped token is issued
// on every response via the X-CSRF-Token header and must be echoed back on
// mutating requests. An off-origin attacker cannot read the header (CORS), so it
// cannot forge the token.

// CSRFHeaderName is the request/response header carrying the CSRF token.
const CSRFHeaderName = "X-CSRF-Token"

var csrfSafeMethods = map[string]bool{
	http.MethodGet:     true,
	http.MethodHead:    true,
	http.MethodOptions: true,
}

var csrfExemptPaths = map[string]bool{
	"/health":          true,
	"/admin/analytics": true,
	"/auth/login":      true,
	"/auth/google":     true,
	"/auth/waitlist":   true,
}

// External callers (Meta, Yoco, Telnyx) never send a CSRF token — exempt by prefix.
var csrfExemptPrefixes = []string{"/webhooks/", "/subscription/webhook", "/telnyx/webhook", "/agent/"}

func csrfSign(timestamp string) string {
	mac := hmac.New(sha256.New, []byte(config.S.SecretKey))
	mac.Write([]byte(timestamp))
	return hex.EncodeToString(mac.Sum(nil))[:32]
}

// GenerateCSRFToken returns a fresh "<ts>.<sig>" token.
func GenerateCSRFToken() string {
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	return ts + "." + csrfSign(ts)
}

func verifyCSRFToken(token string) bool {
	ts, sig, ok := strings.Cut(token, ".")
	if !ok {
		return false
	}
	if subtle.ConstantTimeCompare([]byte(sig), []byte(csrfSign(ts))) != 1 {
		return false
	}
	issued, err := strconv.ParseInt(ts, 10, 64)
	if err != nil {
		return false
	}
	age := time.Now().Unix() - issued
	return age >= 0 && age <= int64(config.S.SessionTTLSeconds)
}

// CheckCSRF returns true when the request passes CSRF validation (or is exempt).
func CheckCSRF(r *http.Request) bool {
	if csrfSafeMethods[r.Method] {
		return true
	}
	path := r.URL.Path
	if csrfExemptPaths[path] {
		return true
	}
	for _, p := range csrfExemptPrefixes {
		if strings.HasPrefix(path, p) {
			return true
		}
	}
	token := r.Header.Get(CSRFHeaderName)
	if token == "" {
		return false
	}
	return verifyCSRFToken(token)
}
