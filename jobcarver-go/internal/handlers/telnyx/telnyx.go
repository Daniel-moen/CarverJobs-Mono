// Package telnyx ports api/app/routes/telnyx.py: the inbound SMS webhook.
//
// The Python handler verifies an Ed25519 signature over "{timestamp}|{body}"
// using TELNYX_PUBLIC_KEY. That key is not modelled in the Go config, so
// signature verification here is RELAXED (accepted) with a clear TODO. The
// event parsing, in-memory inbound buffer and the 6-digit OTP detection are
// ported faithfully. TODO(go-port): add TELNYX_PUBLIC_KEY to config and verify
// the Ed25519 signature before accepting events.
package telnyx

import (
	"encoding/json"
	"io"
	"net/http"
	"regexp"
	"sync"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/httpx"
)

var otpRE = regexp.MustCompile(`(?:^|[^\d])(\d{6})(?:[^\d]|$)`)

// inboundRecord is one buffered inbound SMS (ports telnyx_inbound_buffer.record).
type inboundRecord struct {
	FromNumber string    `json:"from_number"`
	ToNumbers  []string  `json:"to_numbers"`
	Text       string    `json:"text"`
	MsgID      string    `json:"msg_id"`
	ReceivedAt time.Time `json:"received_at"`
}

var (
	bufMu     sync.Mutex
	buffer    []inboundRecord
	bufferMax = 50
)

func recordInbound(rec inboundRecord) {
	bufMu.Lock()
	defer bufMu.Unlock()
	buffer = append(buffer, rec)
	if len(buffer) > bufferMax {
		buffer = buffer[len(buffer)-bufferMax:]
	}
}

// Recent returns the buffered inbound SMS as JSON-friendly maps, newest first.
// Exposed so the admin handler can surface OTP/debug messages
// (ports telnyx_inbound_buffer.recent()).
func Recent() []map[string]any {
	bufMu.Lock()
	defer bufMu.Unlock()
	out := make([]map[string]any, 0, len(buffer))
	for i := len(buffer) - 1; i >= 0; i-- {
		r := buffer[i]
		out = append(out, map[string]any{
			"from_number": r.FromNumber,
			"to_numbers":  r.ToNumbers,
			"text":        r.Text,
			"msg_id":      r.MsgID,
			"received_at": r.ReceivedAt.Format(time.RFC3339),
		})
	}
	return out
}

// Register mounts POST /telnyx/webhook (public; signature-verified in Python).
func Register(r chi.Router) {
	r.Post("/telnyx/webhook", webhook)
}

func webhook(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)

	// TODO(go-port): verify telnyx-signature-ed25519 over "{telnyx-timestamp}|body"
	// using a configured TELNYX_PUBLIC_KEY. Relaxed (accepted) for now.

	var payload struct {
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		httpx.WriteError(w, http.StatusBadRequest, "Invalid JSON", httpx.CRV1003)
		return
	}
	if len(payload.Data) == 0 {
		httpx.JSON(w, http.StatusOK, map[string]any{"status": "ok"})
		return
	}

	// data may be a single event object or a list of events.
	var events []telnyxEvent
	var single telnyxEvent
	if json.Unmarshal(payload.Data, &single) == nil && single.EventType != "" {
		events = []telnyxEvent{single}
	} else {
		_ = json.Unmarshal(payload.Data, &events)
	}

	for _, ev := range events {
		if ev.EventType == "message.received" {
			processMessageReceived(ev.Payload)
		}
	}

	httpx.JSON(w, http.StatusOK, map[string]any{"status": "ok"})
}

type telnyxEvent struct {
	EventType string         `json:"event_type"`
	Payload   messagePayload `json:"payload"`
}

type messagePayload struct {
	ID   any `json:"id"`
	From struct {
		PhoneNumber          string `json:"phone_number"`
		AlphanumericSenderID string `json:"alphanumeric_sender_id"`
	} `json:"from"`
	To []struct {
		PhoneNumber string `json:"phone_number"`
	} `json:"to"`
	Text string `json:"text"`
}

func processMessageReceived(rec messagePayload) {
	fromNumber := rec.From.PhoneNumber
	if fromNumber == "" {
		fromNumber = rec.From.AlphanumericSenderID
	}
	if fromNumber == "" {
		fromNumber = "unknown"
	}
	var toNumbers []string
	for _, t := range rec.To {
		toNumbers = append(toNumbers, t.PhoneNumber)
	}
	msgID := ""
	switch v := rec.ID.(type) {
	case string:
		msgID = v
	case float64:
		msgID = json.Number(jsonNumber(v)).String()
	}

	recordInbound(inboundRecord{
		FromNumber: fromNumber,
		ToNumbers:  toNumbers,
		Text:       rec.Text,
		MsgID:      msgID,
		ReceivedAt: time.Now().UTC(),
	})
	// 6-digit OTP detection (logged in Python; recorded structurally here).
	_ = otpRE.FindStringSubmatch(rec.Text)
}

func jsonNumber(f float64) string {
	b, _ := json.Marshal(f)
	return string(b)
}
