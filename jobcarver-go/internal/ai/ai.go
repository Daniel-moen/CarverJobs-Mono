// Package ai is the Go port of api/app/services/ai_client.py — the single
// wrapper every module uses to talk to OpenAI.
//
// In this port the actual OpenAI HTTP call is STUBBED: there is no network
// access at build time and no key in CI, so Chat returns a deterministic
// placeholder string (or AIKeyMissingError when no key is configured). The
// interface mirrors call_openai so a real HTTP implementation can be dropped in
// later without touching callers.
//
// TODO(go-port): wire real OpenAI HTTP call (urllib equivalent: net/http POST to
// https://api.openai.com/v1/chat/completions with retry-on-429, timeout, and the
// gpt-5 max_completion_tokens handling from ai_client.call_openai).
package ai

import (
	"context"
	"fmt"
	"strings"

	"jobcarver/internal/config"
)

// CRV error codes — mirror ai_client.py's crv_code values.
const (
	CRVKeyMissing  = "CRV-3001"
	CRVTimeout     = "CRV-3002"
	CRVHTTP        = "CRV-3003"
	CRVRateLimit   = "CRV-3004"
	CRVNetwork     = "CRV-3005"
	CRVBadResponse = "CRV-3006"
)

// Message is one chat message ({"role": ..., "content": ...}).
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// Error is the Go analogue of AIClientError: a message plus a CRV code. The
// typed-subclass distinctions from Python are folded into Code.
type Error struct {
	Message string
	Code    string
}

func (e *Error) Error() string { return e.Message }

// ErrKeyMissing is returned (wrapped) when no OPENAI_API_KEY is configured.
func keyMissing() error {
	return &Error{Message: "OPENAI_API_KEY is not set — cannot call OpenAI.", Code: CRVKeyMissing}
}

// Options mirror the optional params of call_openai. Zero values fall back to
// the same defaults as the Python signature.
type Options struct {
	MaxTokens      int     // default 1200
	Temperature    float64 // default 0.1
	JSONResponse   bool    // response_format={"type":"json_object"}
	TimeoutSeconds float64 // default 45
}

// Client is the swappable interface mirroring ai_client.call_openai. Keeping it
// an interface lets the real OpenAI implementation replace the stub later.
type Client interface {
	Chat(ctx context.Context, model string, messages []Message, opts Options) (string, error)
}

// stubClient is the build-time implementation: it never hits the network.
type stubClient struct{}

// Chat returns a deterministic placeholder (or an error if no key is set), so
// downstream DB/flow logic can run without a real model.
func (stubClient) Chat(_ context.Context, model string, messages []Message, opts Options) (string, error) {
	if config.S == nil || strings.TrimSpace(config.S.OpenAIAPIKey) == "" {
		return "", keyMissing()
	}
	// TODO(go-port): replace this with a real POST to OpenAI. For now return a
	// deterministic placeholder. If a JSON response was requested, return valid
	// (empty-shaped) JSON so json.Unmarshal in callers does not blow up.
	if opts.JSONResponse {
		return `{"matched_jobs": []}`, nil
	}
	last := ""
	if len(messages) > 0 {
		last = messages[len(messages)-1].Content
	}
	return fmt.Sprintf("[ai-stub:%s] %s", model, truncate(last, 80)), nil
}

func truncate(s string, n int) string {
	s = strings.TrimSpace(s)
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// Default is the process-wide client. Swap it for a real implementation when
// wiring OpenAI for real.
var Default Client = stubClient{}

// Chat is a package-level convenience wrapping Default.Chat, mirroring how the
// Python code calls the module-level call_openai function directly.
func Chat(ctx context.Context, model string, messages []Message, opts Options) (string, error) {
	if opts.MaxTokens == 0 {
		opts.MaxTokens = 1200
	}
	if opts.Temperature == 0 {
		opts.Temperature = 0.1
	}
	if opts.TimeoutSeconds == 0 {
		opts.TimeoutSeconds = 45
	}
	return Default.Chat(ctx, model, messages, opts)
}
