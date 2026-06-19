// Package security ports api/app/security.py: bcrypt password hashing,
// HMAC-signed timed session tokens (an itsdangerous-equivalent), and the chi
// session middleware. Tokens are self-contained and verified by this service.
package security

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"golang.org/x/crypto/bcrypt"

	"jobcarver/internal/config"
	"jobcarver/internal/httpx"
)

// Session is the signed session payload (ports SessionPayload).
type Session struct {
	Sub      string `json:"sub"`
	Role     string `json:"role"`
	UserID   int    `json:"user_id,omitempty"`
	Provider string `json:"provider,omitempty"`
}

type ctxKey string

const sessionCtxKey ctxKey = "carver_session"

// salt mirrors the itsdangerous salt used in security.py so the signing domain
// is namespaced to sessions.
const salt = "carver-session"

var (
	// ErrInvalidToken is returned for malformed or wrongly-signed tokens.
	ErrInvalidToken = errors.New("invalid session token")
	// ErrExpiredToken is returned when a token is past its TTL.
	ErrExpiredToken = errors.New("session token expired")
)

func b64encode(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }
func b64decode(s string) ([]byte, error) {
	return base64.RawURLEncoding.DecodeString(s)
}

func sign(msg string) string {
	mac := hmac.New(sha256.New, []byte(config.S.SecretKey))
	mac.Write([]byte(salt))
	mac.Write([]byte("|"))
	mac.Write([]byte(msg))
	return b64encode(mac.Sum(nil))
}

// IssueSessionToken serialises s and returns an HMAC-SHA256 signed, timestamped
// token of the form  <payload>.<timestamp>.<signature>  (all base64url).
func IssueSessionToken(s Session) (string, error) {
	raw, err := json.Marshal(s)
	if err != nil {
		return "", err
	}
	payload := b64encode(raw)
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	msg := payload + "." + ts
	return msg + "." + sign(msg), nil
}

// ParseSessionToken verifies the signature and TTL, returning the payload.
func ParseSessionToken(token string) (*Session, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, ErrInvalidToken
	}
	payload, ts, sig := parts[0], parts[1], parts[2]
	msg := payload + "." + ts
	expected := sign(msg)
	if subtle.ConstantTimeCompare([]byte(sig), []byte(expected)) != 1 {
		return nil, ErrInvalidToken
	}
	issued, err := strconv.ParseInt(ts, 10, 64)
	if err != nil {
		return nil, ErrInvalidToken
	}
	if config.S.SessionTTLSeconds > 0 {
		age := time.Now().Unix() - issued
		if age < 0 || age > int64(config.S.SessionTTLSeconds) {
			return nil, ErrExpiredToken
		}
	}
	raw, err := b64decode(payload)
	if err != nil {
		return nil, ErrInvalidToken
	}
	var s Session
	if err := json.Unmarshal(raw, &s); err != nil {
		return nil, ErrInvalidToken
	}
	return &s, nil
}

// HashPassword bcrypt-hashes a plaintext password.
func HashPassword(pw string) (string, error) {
	h, err := bcrypt.GenerateFromPassword([]byte(pw), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(h), nil
}

// VerifyPassword compares a plaintext password against a bcrypt hash.
func VerifyPassword(pw, hash string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(pw)) == nil
}

// extractToken reads the session token from the session cookie or a
// "Authorization: Bearer" header (ports _extract_token).
func extractToken(r *http.Request) string {
	if c, err := r.Cookie(config.S.SessionCookieName); err == nil && c.Value != "" {
		return c.Value
	}
	auth := r.Header.Get("Authorization")
	if strings.HasPrefix(auth, "Bearer ") {
		return strings.TrimSpace(auth[7:])
	}
	return ""
}

// optionalSession returns the session for a request, honouring AutoLoginAsAdmin.
// Returns nil when no valid session is present (never an error).
func optionalSession(r *http.Request) *Session {
	if config.S.AutoLoginAsAdmin {
		return &Session{Sub: config.S.AdminUsername, Role: "admin"}
	}
	token := extractToken(r)
	if token == "" {
		return nil
	}
	s, err := ParseSessionToken(token)
	if err != nil {
		return nil
	}
	return s
}

// OptionalSession attaches a session to the context if one is present, and never
// blocks the request.
func OptionalSession(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if s := optionalSession(r); s != nil {
			r = r.WithContext(context.WithValue(r.Context(), sessionCtxKey, s))
		}
		next.ServeHTTP(w, r)
	})
}

// RequireSession enforces a valid session, returning 401 CRV-2004 otherwise.
func RequireSession(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s := optionalSession(r)
		if s == nil {
			httpx.WriteError(w, http.StatusUnauthorized, "Authentication required", httpx.CRV2004)
			return
		}
		r = r.WithContext(context.WithValue(r.Context(), sessionCtxKey, s))
		next.ServeHTTP(w, r)
	})
}

// RequireRole enforces a valid session whose role is in roles. It responds 401
// CRV-2004 when no session is present and 403 CRV-2005 when the role is not
// allowed. The session is attached to the request context for the handler.
func RequireRole(roles ...string) func(http.Handler) http.Handler {
	allowed := make(map[string]bool, len(roles))
	for _, r := range roles {
		allowed[r] = true
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			s := optionalSession(r)
			if s == nil {
				httpx.WriteError(w, http.StatusUnauthorized, "Authentication required", httpx.CRV2004)
				return
			}
			if !allowed[s.Role] {
				httpx.WriteError(w, http.StatusForbidden, "Insufficient permissions", httpx.CRV2005)
				return
			}
			r = r.WithContext(context.WithValue(r.Context(), sessionCtxKey, s))
			next.ServeHTTP(w, r)
		})
	}
}

// SessionFromContext returns the session stored on the context, or nil.
func SessionFromContext(ctx context.Context) *Session {
	if s, ok := ctx.Value(sessionCtxKey).(*Session); ok {
		return s
	}
	return nil
}
