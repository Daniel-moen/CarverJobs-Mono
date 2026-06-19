// Package whatsapp ports the core of api/app/routes/whatsapp.py (~2000 lines):
// the Meta Cloud API webhook (GET verification handshake + POST inbound message
// ingestion), inbound message/session persistence, and the WhatsApp magic-link
// auth flow.
//
// SCOPE (per the port plan): the webhook verification, inbound
// WhatsAppMessage/WhatsAppSession persistence, message deduplication, and
// magic-token issue/consume are ported faithfully and are REAL. The full
// onboarding AI conversation state machine, the rich command/menu handling, the
// job-submission + document flows, and all OUTBOUND Meta Graph API sends are
// STUBBED: inbound text produces a placeholder reply through the internal/ai
// stub, recorded as an outbound WhatsAppMessage, while the actual Graph send is
// a no-op logging TODO.
//
// TODO(go-port): port the onboarding/chat state machine (_run_onboarding /
// _run_chat), the command router, media/job-submission flows, and wire real
// outbound Graph API sends (_send_whatsapp / _send_whatsapp_buttons). Also add
// META_APP_SECRET to config and verify X-Hub-Signature-256 (currently relaxed).
package whatsapp

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/go-chi/chi/v5"
	"gorm.io/gorm"

	"jobcarver/internal/ai"
	"jobcarver/internal/config"
	"jobcarver/internal/db"
	"jobcarver/internal/flags"
	"jobcarver/internal/httpx"
	"jobcarver/internal/logger"
	"jobcarver/internal/metrics"
	"jobcarver/internal/models"
	"jobcarver/internal/security"
)

var log = logger.Get("carver.whatsapp")

const (
	seenMsgMax       = 500
	staleMsgSeconds  = 300
	magicTokenMaxLen = 64
)

var allowedRedirects = map[string]bool{
	"/profile": true, "/jobs": true, "/status": true, "/": true,
	"/subscription": true, "/?feedback=1": true,
}

var allowedRedirectPrefixes = []string{"/matches/"}

// In-memory message-ID dedup (ports _SEEN_MSG_IDS / _SEEN_MSG_IDS_ORDER).
var (
	seenMu    sync.Mutex
	seenIDs   = map[string]bool{}
	seenOrder []string
)

// Register mounts the WhatsApp webhook + magic-auth routes.
func Register(r chi.Router) {
	r.Get("/webhooks/whatsapp", verify)
	r.Post("/webhooks/whatsapp", webhook)
	r.Get("/wa/auth/{token}", magicAuth)
}

// ── webhook verification ─────────────────────────────────────────────────────

func verify(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	if q.Get("hub.verify_token") == config.S.MetaVerifyToken {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(q.Get("hub.challenge")))
		return
	}
	httpx.WriteError(w, http.StatusForbidden, "Verification failed", httpx.CRV2004)
}

func waConfigured() bool {
	return config.S.WhatsAppPhoneNumberID != "" && config.S.WhatsAppAccessToken != ""
}

// ── inbound webhook ──────────────────────────────────────────────────────────

func webhook(w http.ResponseWriter, r *http.Request) {
	if !flags.IsEnabled("whatsapp") {
		metrics.Increment("feature_blocked")
		httpx.JSON(w, http.StatusOK, map[string]any{"ok": false})
		return
	}
	if !waConfigured() {
		httpx.WriteError(w, http.StatusServiceUnavailable, "WhatsApp not configured", httpx.CRV1008)
		return
	}

	body, _ := io.ReadAll(r.Body)
	// TODO(go-port): verify X-Hub-Signature-256 with META_APP_SECRET. Relaxed.

	var data struct {
		Entry []struct {
			Changes []struct {
				Value struct {
					Metadata struct {
						PhoneNumberID      string `json:"phone_number_id"`
						DisplayPhoneNumber string `json:"display_phone_number"`
					} `json:"metadata"`
					Messages []metaMessage `json:"messages"`
				} `json:"value"`
			} `json:"changes"`
		} `json:"entry"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid JSON", httpx.CRV1003)
		return
	}

	if len(data.Entry) == 0 || len(data.Entry[0].Changes) == 0 {
		httpx.JSON(w, http.StatusOK, map[string]any{"ok": true})
		return
	}
	value := data.Entry[0].Changes[0].Value
	graphPhoneID := strings.TrimSpace(value.Metadata.PhoneNumberID)
	if graphPhoneID == "" {
		graphPhoneID = config.S.WhatsAppPhoneNumberID
	}

	for _, msg := range value.Messages {
		phone := msg.From
		if phone == "" {
			continue
		}
		if msg.ID != "" && isDuplicateOrStale(msg.ID, msg.Timestamp) {
			continue
		}

		switch msg.Type {
		case "text":
			text := strings.TrimSpace(msg.Text.Body)
			if text == "" {
				recordUnsupported(phone, "text", graphPhoneID, msg.ID, "empty_text")
				continue
			}
			processMessage(phone, text, graphPhoneID, msg.ID, "text")
		case "interactive":
			bid := ""
			switch msg.Interactive.Type {
			case "button_reply":
				bid = msg.Interactive.ButtonReply.ID
			case "list_reply":
				bid = msg.Interactive.ListReply.ID
			default:
				recordUnsupported(phone, "interactive", graphPhoneID, msg.ID, "unsupported_interactive:"+msg.Interactive.Type)
				continue
			}
			// TODO(go-port): map button ids to commands (_INTERACTIVE_CMD_MAP).
			cmd := bid
			if cmd == "" {
				cmd = "help"
			}
			processMessage(phone, cmd, graphPhoneID, msg.ID, "interactive")
		case "image", "document", "audio", "video":
			// TODO(go-port): media/job-submission + document upload flows.
			mediaID := msg.Image.ID
			recordInbound(phone, "inbound", msg.Type, "["+msg.Type+"] "+mediaID, msg.ID, graphPhoneID, nil)
		default:
			recordUnsupported(phone, orStr(msg.Type, "unknown"), graphPhoneID, msg.ID, "unsupported_message_type")
		}
	}

	httpx.JSON(w, http.StatusOK, map[string]any{"ok": true})
}

type metaMessage struct {
	Type      string `json:"type"`
	From      string `json:"from"`
	ID        string `json:"id"`
	Timestamp string `json:"timestamp"`
	Text      struct {
		Body string `json:"body"`
	} `json:"text"`
	Image struct {
		ID string `json:"id"`
	} `json:"image"`
	Interactive struct {
		Type        string `json:"type"`
		ButtonReply struct {
			ID string `json:"id"`
		} `json:"button_reply"`
		ListReply struct {
			ID string `json:"id"`
		} `json:"list_reply"`
	} `json:"interactive"`
}

// processMessage records the inbound message, ensures a session, generates a
// (stubbed) reply via the AI stub, and records it as an outbound message.
// Outbound Graph send is a no-op (TODO).
func processMessage(phone, text, graphPhoneID, metaMsgID, msgType string) {
	recordInbound(phone, "inbound", msgType, text, metaMsgID, graphPhoneID, nil)
	session := getOrCreateSession(phone)

	// TODO(go-port): real onboarding/chat state machine + command routing.
	var reply string
	if config.S.OpenAIAPIKey == "" {
		reply = "Thanks! Our assistant is being set up — please try again soon."
	} else {
		model := config.S.WhatsAppAIModel
		out, err := ai.Chat(context.Background(), model, []ai.Message{
			{Role: "system", Content: "You are CARVER, a WhatsApp assistant for superyacht crew."},
			{Role: "user", Content: text},
		}, ai.Options{MaxTokens: 300})
		if err != nil || strings.TrimSpace(out) == "" {
			reply = "Thanks for your message — we'll be in touch shortly."
		} else {
			reply = out
		}
	}
	_ = session

	sendWhatsApp(phone, reply, graphPhoneID)
	metrics.Increment("whatsapp_messages")
}

// sendWhatsApp is a STUB: it records the outbound message but does not call the
// Meta Graph API. TODO(go-port): real POST to {phone_id}/messages.
func sendWhatsApp(to, text, graphPhoneID string) {
	log.Info("whatsapp outbound (stubbed; not sent)", "to_prefix", prefix(to), "chars", len(text))
	recordInbound(to, "outbound", "text", text, "", graphPhoneID, map[string]any{"stubbed": true})
}

// ── persistence helpers ──────────────────────────────────────────────────────

func recordInbound(phone, direction, msgType, content, metaMsgID, graphPhoneID string, payload map[string]any) {
	row := models.WhatsAppMessage{
		PhoneNumber: phone,
		Direction:   direction,
		MessageType: msgType,
	}
	if content != "" {
		row.Content = &content
	}
	if metaMsgID != "" {
		row.MetaMessageID = &metaMsgID
	}
	if graphPhoneID != "" {
		row.GraphPhoneNumberID = &graphPhoneID
	}
	if payload != nil {
		if b, err := json.Marshal(payload); err == nil {
			s := string(b)
			row.PayloadJSON = &s
		}
	}
	if err := db.DB.Create(&row).Error; err != nil {
		log.Warn("whatsapp message audit failed", "phone_prefix", prefix(phone), "err", err)
	}
}

func recordUnsupported(phone, msgType, graphPhoneID, metaMsgID, reason string) {
	recordInbound(phone, "inbound", orStr(msgType, "unknown"), "", metaMsgID, graphPhoneID, map[string]any{"reason": reason})
}

func getOrCreateSession(phone string) models.WhatsAppSession {
	var s models.WhatsAppSession
	err := db.DB.Where("phone_number = ?", phone).First(&s).Error
	if err == nil {
		return s
	}
	if err == gorm.ErrRecordNotFound {
		s = models.WhatsAppSession{PhoneNumber: phone, Mode: "onboarding", History: "[]", PartialProfile: "{}"}
		db.DB.Create(&s)
	}
	return s
}

// ── dedup ────────────────────────────────────────────────────────────────────

func parseMetaTimestamp(ts string) (int64, bool) {
	ts = strings.TrimSpace(ts)
	if ts == "" {
		return 0, false
	}
	raw, err := strconv.ParseInt(ts, 10, 64)
	if err != nil || raw <= 0 {
		return 0, false
	}
	now := time.Now().Unix()
	if raw >= 946684800 && raw <= now+86400 {
		return raw, true
	}
	if raw >= 946684800000 && raw <= (now+86400)*1000 {
		return raw / 1000, true
	}
	return 0, false
}

func isDuplicateOrStale(msgID, ts string) bool {
	if msgTS, ok := parseMetaTimestamp(ts); ok {
		if time.Now().Unix()-msgTS > staleMsgSeconds {
			return true
		}
	}
	seenMu.Lock()
	defer seenMu.Unlock()
	if seenIDs[msgID] {
		return true
	}
	seenIDs[msgID] = true
	seenOrder = append(seenOrder, msgID)
	if len(seenOrder) > seenMsgMax {
		oldest := seenOrder[0]
		seenOrder = seenOrder[1:]
		delete(seenIDs, oldest)
	}
	return false
}

// ── magic links ──────────────────────────────────────────────────────────────

func isSafeRedirect(path string) bool {
	if path == "" {
		return false
	}
	if allowedRedirects[path] {
		return true
	}
	for _, p := range allowedRedirectPrefixes {
		if strings.HasPrefix(path, p) {
			return true
		}
	}
	return false
}

// MakeMagicLink creates a WhatsAppMagicToken and returns the full magic-link URL
// (ports _make_magic_link). Exposed for the media/document flows once ported.
func MakeMagicLink(phone string, redirectTo string) string {
	safe := ""
	if isSafeRedirect(redirectTo) {
		safe = redirectTo
	}
	token := tokenURLSafe(16)
	expires := time.Now().UTC().Add(time.Duration(config.S.WAMagicTokenTTLSeconds) * time.Second)
	row := models.WhatsAppMagicToken{Token: token, PhoneNumber: phone, ExpiresAt: expires}
	if safe != "" {
		row.RedirectTo = &safe
	}
	db.DB.Create(&row)

	url := config.S.FrontendBaseURL + "/wa/" + token
	if safe != "" && safe != "/profile" {
		url += "?r=" + safe
	}
	return url
}

func magicAuth(w http.ResponseWriter, r *http.Request) {
	token := chi.URLParam(r, "token")
	if len(token) > magicTokenMaxLen {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid token", httpx.CRV1003)
		return
	}
	var record models.WhatsAppMagicToken
	if db.DB.Where("token = ?", token).First(&record).Error != nil {
		httpx.WriteError(w, http.StatusNotFound, "Link not found.", httpx.CRV1005)
		return
	}
	if time.Now().UTC().After(record.ExpiresAt.UTC()) {
		httpx.WriteError(w, http.StatusGone,
			"This link has expired. Send any message on WhatsApp to get a new one.", httpx.CRV2003)
		return
	}

	sessionToken, err := security.IssueSessionToken(security.Session{
		Sub: record.PhoneNumber, Role: "crew", Provider: "whatsapp",
	})
	if err != nil {
		httpx.WriteError(w, http.StatusInternalServerError, "Could not issue session.", httpx.CRV1006)
		return
	}

	sameSite := http.SameSiteLaxMode
	if config.S.SessionSecureCookie {
		sameSite = http.SameSiteNoneMode
	}
	http.SetCookie(w, &http.Cookie{
		Name:     config.S.SessionCookieName,
		Value:    sessionToken,
		HttpOnly: true,
		Secure:   config.S.SessionSecureCookie,
		SameSite: sameSite,
		MaxAge:   config.S.SessionTTLSeconds,
		Path:     "/",
	})

	redirect := ""
	if record.RedirectTo != nil && isSafeRedirect(*record.RedirectTo) {
		redirect = *record.RedirectTo
	}
	if redirect == "" {
		qp := r.URL.Query().Get("r")
		if isSafeRedirect(qp) {
			redirect = qp
		} else {
			redirect = "/profile"
		}
	}
	metrics.Increment("whatsapp_magic_logins")
	httpx.JSON(w, http.StatusOK, map[string]any{
		"ok": true, "redirect": redirect, "session_token": sessionToken,
	})
}

// ── small helpers ────────────────────────────────────────────────────────────

func tokenURLSafe(nbytes int) string {
	b := make([]byte, nbytes)
	if _, err := rand.Read(b); err != nil {
		return strconv.FormatInt(time.Now().UnixNano(), 36)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func prefix(s string) string {
	if len(s) <= 6 {
		return s
	}
	return s[:6] + "****"
}

func orStr(s, def string) string {
	if s == "" {
		return def
	}
	return s
}
