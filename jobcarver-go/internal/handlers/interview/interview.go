// Package interview ports api/app/routes/interview.py: the AI interview (/next)
// and onboarding (/onboard) conversational endpoints. Prompt construction,
// history windowing, JSON-extraction and the onboarding fallback logic are all
// ported faithfully; the model call runs through internal/ai (stubbed), so live
// responses are placeholders until OpenAI is wired. Both routes require a session
// and are gated by the interview/onboarding feature flags.
package interview

import (
	"encoding/json"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"jobcarver/internal/ai"
	"jobcarver/internal/config"
	"jobcarver/internal/flags"
	"jobcarver/internal/httpx"
	"jobcarver/internal/metrics"
	"jobcarver/internal/security"
)

var jsonObjectRE = regexp.MustCompile(`\{[\s\S]*\}`)

// requiredOnboardFields mirrors REQUIRED_ONBOARD_FIELDS.
var requiredOnboardFields = []string{
	"firstName", "lastName", "sex", "desiredRole", "yearsExperience",
	"nationality", "currentLocation", "preferredLocations",
	"contractType", "salaryMin", "salaryMax", "certifications", "languages",
}

// Register mounts /interview routes (session required).
func Register(r chi.Router) {
	r.Group(func(r chi.Router) {
		r.Use(security.RequireSession)
		r.Post("/interview/next", interviewNext)
		r.Post("/interview/onboard", interviewOnboard)
	})
}

type interviewMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type interviewRequest struct {
	UserMessage string             `json:"user_message"`
	History     []interviewMessage `json:"history"`
	Profile     map[string]string  `json:"profile"`
}

func interviewNext(w http.ResponseWriter, r *http.Request) {
	if !flags.IsEnabled("interview") {
		metrics.Increment("feature_blocked")
		httpx.WriteError(w, http.StatusServiceUnavailable, "AI interview is temporarily disabled.", httpx.CRV1008)
		return
	}
	if strings.TrimSpace(config.S.OpenAIAPIKey) == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable, "AI interview is not available.", httpx.CRV3001)
		return
	}
	var payload interviewRequest
	if err := httpx.Decode(r, &payload); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}

	systemText := buildInterviewSystem(payload)
	messages := buildMessages(systemText, payload.History, payload.UserMessage, 12, false)

	t0 := time.Now()
	text, err := ai.Chat(r.Context(), config.S.OpenAIModel, messages, ai.Options{MaxTokens: 450, Temperature: 0.4, JSONResponse: true})
	metrics.RecordAIResponseTime(int(time.Since(t0).Milliseconds()))
	if err != nil {
		httpx.WriteError(w, http.StatusBadGateway, "Something went wrong. Please try again.", httpx.CRV3003)
		return
	}

	parsed := extractJSON(text)
	message := strings.TrimSpace(getString(parsed, "message"))
	cleanUpdates := cleanUpdates(parsed)
	if message == "" {
		message = "Thanks for that! What else can you tell me about your preferences?"
	}

	metrics.Increment("interview_turns")
	httpx.JSON(w, http.StatusOK, map[string]any{"message": message, "updates": cleanUpdates})
}

func interviewOnboard(w http.ResponseWriter, r *http.Request) {
	if !flags.IsEnabled("onboarding") {
		metrics.Increment("feature_blocked")
		httpx.WriteError(w, http.StatusServiceUnavailable, "Onboarding is temporarily disabled.", httpx.CRV1008)
		return
	}
	if strings.TrimSpace(config.S.OpenAIAPIKey) == "" {
		httpx.WriteError(w, http.StatusServiceUnavailable, "AI interview is not available.", httpx.CRV3001)
		return
	}
	var payload interviewRequest
	if err := httpx.Decode(r, &payload); err != nil {
		httpx.WriteError(w, http.StatusUnprocessableEntity, "Invalid request body.", httpx.CRV1003)
		return
	}
	if len(payload.History) == 0 {
		metrics.Increment("onboard_started")
	}

	systemText := buildOnboardSystem(payload)
	messages := buildMessages(systemText, payload.History, payload.UserMessage, 20, true)

	t0 := time.Now()
	text, err := ai.Chat(r.Context(), config.S.OpenAIModel, messages, ai.Options{MaxTokens: 500, Temperature: 0.6, JSONResponse: true})
	metrics.RecordAIResponseTime(int(time.Since(t0).Milliseconds()))
	if err != nil {
		httpx.WriteError(w, http.StatusBadGateway, "Something went wrong. Please try again.", httpx.CRV3003)
		return
	}

	parsed := extractJSON(text)
	message := strings.TrimSpace(getString(parsed, "message"))
	done := getBool(parsed, "done")
	cleanUpdates := cleanUpdates(parsed)

	if message == "" {
		merged := map[string]string{}
		for k, v := range payload.Profile {
			merged[k] = v
		}
		for k, v := range cleanUpdates {
			merged[k] = v
		}
		missing := missingFields(merged)
		fallbackMap := map[string]string{
			"firstName":          "Could you tell me your full name?",
			"lastName":           "Could you tell me your last name?",
			"sex":                "How should we list your gender? (Male, Female, Other, or Prefer not to say)",
			"desiredRole":        "What role are you looking for on a yacht?",
			"yearsExperience":    "How many years of experience do you have?",
			"nationality":        "What's your nationality?",
			"currentLocation":    "Where are you currently based?",
			"preferredLocations": "Which regions would you prefer to work in?",
			"contractType":       "Are you looking for permanent, seasonal, rotational, or temporary work?",
			"salaryMin":          "What are your monthly salary expectations (EUR)?",
			"salaryMax":          "What would be your ideal maximum monthly salary (EUR)?",
			"certifications":     "Do you hold any certifications (STCW, ENG1, etc.)?",
			"languages":          "What languages do you speak?",
		}
		if len(missing) > 0 {
			q := fallbackMap[missing[0]]
			if q == "" {
				q = "Tell me a bit more about yourself."
			}
			message = "Got it, thanks! " + q
		} else {
			message = "Looks like we have everything — welcome aboard!"
			done = true
		}
	}

	if done {
		metrics.Increment("onboard_completed")
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"message": message, "updates": cleanUpdates, "done": done})
}

// ── prompt + parsing helpers (ported) ────────────────────────────────────────

func buildMessages(systemText string, history []interviewMessage, userMessage string, limit int, onboard bool) []ai.Message {
	messages := []ai.Message{{Role: "system", Content: systemText}}
	start := 0
	if len(history) > limit {
		start = len(history) - limit
	}
	for _, msg := range history[start:] {
		if msg.Role == "user" {
			messages = append(messages, ai.Message{Role: "user", Content: msg.Content})
		} else {
			var wrapped []byte
			if onboard {
				wrapped, _ = json.Marshal(map[string]any{"message": msg.Content, "done": false, "updates": map[string]string{}})
			} else {
				wrapped, _ = json.Marshal(map[string]any{"message": msg.Content, "updates": map[string]string{}})
			}
			messages = append(messages, ai.Message{Role: "assistant", Content: string(wrapped)})
		}
	}
	um := userMessage
	if um == "" {
		um = "Begin."
	}
	messages = append(messages, ai.Message{Role: "user", Content: um})
	return messages
}

func buildInterviewSystem(payload interviewRequest) string {
	profileText := marshalProfile(payload.Profile)
	return `You are CARVER Interview AI. Ask one concise, practical interview question at a time.
Your goal: learn candidate preferences for superyacht jobs and suggest profile updates.

Current profile:
` + profileText + `

Review the conversation history carefully. Do NOT repeat questions or topics already covered.

Return strict JSON only:
{"message": "your next question or brief acknowledgment + question", "updates": {"sex": "", "desiredRole": "", "preferredLocations": "", "contractType": "", "rotationPreference": "", "availableFrom": "", "salaryMin": "", "salaryMax": "", "languages": "", "certifications": "", "bio": ""}}

Rules:
- Only fill update fields if the user clearly provided that info.
- Keep values short and clean.
- Do not invent personal facts.
- For "sex", ONLY use one of: "male", "female", "other", "prefer_not_to_say". Map the user's answer to the closest value.
- If the user's gender/sex is not yet in their profile, ask about it early in the conversation.`
}

func buildOnboardSystem(payload interviewRequest) string {
	missing := missingFields(payload.Profile)
	allDone := len(missing) == 0
	profileText := marshalProfile(payload.Profile)
	missingText := "none — all fields collected!"
	if len(missing) > 0 {
		missingText = strings.Join(missing, ", ")
	}
	doneStr := "false"
	if allDone {
		doneStr = "true"
	}
	return `You are CARVER, a warm and professional onboarding assistant for a superyacht crew platform.
Your sole job: collect every required profile field through natural conversation.

Profile collected so far:
` + profileText + `

Still missing: ` + missingText + `

Review the conversation history carefully. Do NOT re-ask questions already answered.
Ask about fields in order: firstName+lastName, sex, desiredRole, yearsExperience, nationality, currentLocation, preferredLocations, contractType, salaryMin+salaryMax, certifications, languages.

Rules:
- ONLY set "done": true when the missing fields list is empty (all 13 fields collected).
- One question at a time — keep replies short, warm and conversational.
- Only populate update fields when the user has clearly provided that info.
- Do not invent or assume any facts.
- For salaryMin/salaryMax use numeric strings only.
- If the user wants to skip a field, set it to "unknown" so it counts as filled.

Return strict JSON only:
{"message": "your conversational reply + next question (or warm wrap-up if done)", "done": ` + doneStr + `, "updates": {"firstName": "", "lastName": "", "sex": "", "desiredRole": "", "yearsExperience": "", "nationality": "", "currentLocation": "", "preferredLocations": "", "contractType": "", "salaryMin": "", "salaryMax": "", "certifications": "", "languages": ""}}

For "sex", ONLY use one of: "male", "female", "other", "prefer_not_to_say".`
}

func missingFields(profile map[string]string) []string {
	var missing []string
	for _, f := range requiredOnboardFields {
		if strings.TrimSpace(profile[f]) == "" {
			missing = append(missing, f)
		}
	}
	return missing
}

func marshalProfile(p map[string]string) string {
	if p == nil {
		p = map[string]string{}
	}
	b, err := json.Marshal(p)
	if err != nil {
		return "{}"
	}
	return string(b)
}

// extractJSON ports _extract_json.
func extractJSON(text string) map[string]any {
	raw := strings.TrimSpace(text)
	if raw == "" {
		return map[string]any{}
	}
	raw = strings.TrimPrefix(raw, "```json")
	raw = strings.TrimPrefix(raw, "```JSON")
	raw = strings.TrimPrefix(raw, "```")
	raw = strings.TrimSuffix(strings.TrimSpace(raw), "```")
	raw = strings.TrimSpace(raw)
	var out map[string]any
	if json.Unmarshal([]byte(raw), &out) == nil {
		return out
	}
	if m := jsonObjectRE.FindString(raw); m != "" {
		if json.Unmarshal([]byte(m), &out) == nil {
			return out
		}
	}
	return map[string]any{}
}

func cleanUpdates(parsed map[string]any) map[string]string {
	out := map[string]string{}
	updates, ok := parsed["updates"].(map[string]any)
	if !ok {
		return out
	}
	for k, v := range updates {
		if v == nil {
			continue
		}
		s := strings.TrimSpace(anyToString(v))
		if s != "" {
			out[k] = s
		}
	}
	return out
}

func getString(m map[string]any, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func getBool(m map[string]any, key string) bool {
	b, _ := m[key].(bool)
	return b
}

func anyToString(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case bool:
		if t {
			return "true"
		}
		return "false"
	case float64:
		// Shortest exact decimal (no exponent, no spurious trailing zeros).
		// The old TrimRight(x, "0") stripped zeros that are part of the integer,
		// turning 5000 into "5" and 2020 into "202".
		return strconv.FormatFloat(t, 'f', -1, 64)
	default:
		return ""
	}
}
