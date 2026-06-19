// Package config ports api/app/settings.py: loads a .env file (if present) then
// reads environment variables with the same defaults as the Python service.
package config

import (
	"bufio"
	"os"
	"strconv"
	"strings"
)

// TokenPackage is one purchasable token pack (ports a TOKEN_PACKAGES entry).
type TokenPackage struct {
	Tokens    int    `json:"tokens"`
	Price     string `json:"price"`
	Label     string `json:"label"`
	Badge     string `json:"badge,omitempty"`
	Highlight bool   `json:"highlight,omitempty"`
}

// Settings is the fully-resolved application configuration.
type Settings struct {
	AppEnv              string
	AutoLoginAsAdmin    bool
	SecretKey           string
	SessionCookieName   string
	SessionTTLSeconds   int
	SessionSecureCookie bool

	AdminUsername string
	AdminPassword string

	GoogleOAuthClientID        string
	GoogleAllowedEmails        []string
	GoogleAllowedDomain        string
	GoogleRequireVerifiedEmail bool

	OpenAIAPIKey    string
	OpenAIModel     string
	EmailAIModel    string
	WhatsAppAIModel string

	CORSOrigins    []string
	AllowedHosts   []string
	UploadDir      string
	UploadMaxBytes int64

	// Monetization
	TokenPrice                 string
	TokenPackages              []TokenPackage
	FirstPurchaseBonusTokens   int
	FreeMonthlyTokens          int
	FreeSignupTokens           int
	FreeJobPostTokensPerMonth  int
	RecruiterUnlockCostTokens  int
	FeedbackMinAccountAgeHours int

	// Integrations (keys may be empty -> feature disabled)
	APIFYAPIKey            string
	MetaVerifyToken        string
	WhatsAppAccessToken    string
	WhatsAppPhoneNumberID  string
	FrontendBaseURL        string
	WAMagicTokenTTLSeconds int
	WAMatchRecentDays      int

	JobExpireAfterDays        int
	JobDeleteAfterDays        int
	JobRetentionIntervalHours int

	AgentAPIToken     string
	YocoPublicKey     string
	YocoSecretKey     string
	YocoWebhookSecret string
	TelnyxAPIKey      string

	Port string // default "3000", from PORT env
}

// S holds the loaded settings, populated by Load().
var S *Settings

// getenv returns the env var or a default when unset/empty-after-default-rules.
// Mirrors os.getenv(name, default) in settings.py.
func getenv(name, def string) string {
	if v, ok := os.LookupEnv(name); ok {
		return v
	}
	return def
}

func getenvStrip(name, def string) string {
	return strings.TrimSpace(getenv(name, def))
}

func getenvInt(name string, def int) int {
	raw := getenv(name, strconv.Itoa(def))
	v, err := strconv.Atoi(strings.TrimSpace(raw))
	if err != nil {
		return def
	}
	return v
}

func getenvInt64(name string, def int64) int64 {
	raw := getenv(name, strconv.FormatInt(def, 10))
	v, err := strconv.ParseInt(strings.TrimSpace(raw), 10, 64)
	if err != nil {
		return def
	}
	return v
}

func getenvBool(name string, def bool) bool {
	d := "false"
	if def {
		d = "true"
	}
	return strings.EqualFold(strings.TrimSpace(getenv(name, d)), "true")
}

// csvEnv ports _csv_env: split on commas, trim, drop empties.
func csvEnv(name, def string) []string {
	raw := getenv(name, def)
	var out []string
	for _, item := range strings.Split(raw, ",") {
		item = strings.TrimSpace(item)
		if item != "" {
			out = append(out, item)
		}
	}
	return out
}

// loadDotenv ports settings.py _load_dotenv: key=value lines, skip blanks and
// comments, only set vars not already present in the environment.
func loadDotenv(path string) {
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		key, value, _ := strings.Cut(line, "=")
		key = strings.TrimSpace(key)
		value = strings.TrimSpace(value)
		if key == "" {
			continue
		}
		if _, ok := os.LookupEnv(key); !ok {
			_ = os.Setenv(key, value)
		}
	}
}

// defaultCORSOrigins ports _default_cors_origins: explicit defaults plus an
// optional FRONTEND_BASE_URL, de-duplicated, order preserved.
func defaultCORSOrigins() string {
	defaults := []string{
		"http://localhost:5173",
		"http://127.0.0.1:5173",
		"http://localhost:8080",
		"https://jobcarver.co",
		"https://www.jobcarver.co",
	}
	if fb := strings.TrimSpace(os.Getenv("FRONTEND_BASE_URL")); fb != "" {
		defaults = append(defaults, fb)
	}
	seen := map[string]bool{}
	var out []string
	for _, d := range defaults {
		if !seen[d] {
			seen[d] = true
			out = append(out, d)
		}
	}
	return strings.Join(out, ",")
}

// Load reads jobcarver-go/.env (if present) then resolves all settings from the
// environment with the same defaults as settings.py, sets S, and returns it.
func Load() *Settings {
	loadDotenv(".env")

	appEnv := getenv("APP_ENV", "development")

	secureDefault := false
	if appEnv == "production" {
		secureDefault = true
	}

	allowedEmails := csvEnv("GOOGLE_ALLOWED_EMAILS", "")
	for i, e := range allowedEmails {
		allowedEmails[i] = strings.ToLower(e)
	}

	waPhoneRaw := getenvStrip("WHATSAPP_PHONE_NUMBER_ID", "")
	waPhone := ""
	for _, p := range strings.Split(waPhoneRaw, ",") {
		if p = strings.TrimSpace(p); p != "" {
			waPhone = p
			break
		}
	}

	s := &Settings{
		AppEnv:              appEnv,
		AutoLoginAsAdmin:    getenvBool("AUTO_LOGIN_AS_ADMIN", false),
		SecretKey:           getenv("SECRET_KEY", "change-me-in-production"),
		SessionCookieName:   getenv("SESSION_COOKIE_NAME", "carver_session"),
		SessionTTLSeconds:   getenvInt("SESSION_TTL_SECONDS", 3600),
		SessionSecureCookie: getenvBool("SESSION_SECURE_COOKIE", secureDefault),

		AdminUsername: getenv("ADMIN_USERNAME", "admin"),
		AdminPassword: getenv("ADMIN_PASSWORD", "change-this-password"),

		GoogleOAuthClientID:        getenvStrip("GOOGLE_OAUTH_CLIENT_ID", ""),
		GoogleAllowedEmails:        allowedEmails,
		GoogleAllowedDomain:        strings.ToLower(getenvStrip("GOOGLE_ALLOWED_DOMAIN", "")),
		GoogleRequireVerifiedEmail: getenvBool("GOOGLE_REQUIRE_VERIFIED_EMAIL", true),

		OpenAIAPIKey:    getenvStrip("OPENAI_API_KEY", ""),
		OpenAIModel:     getenvStrip("OPENAI_MODEL", "gpt-4o-mini"),
		EmailAIModel:    getenvStrip("EMAIL_AI_MODEL", "gpt-4o"),
		WhatsAppAIModel: getenvStrip("WHATSAPP_AI_MODEL", "gpt-5-mini"),

		CORSOrigins:    csvEnv("CORS_ORIGINS", defaultCORSOrigins()),
		AllowedHosts:   csvEnv("ALLOWED_HOSTS", "*"),
		UploadDir:      getenv("UPLOAD_DIR", "data/uploads"),
		UploadMaxBytes: getenvInt64("UPLOAD_MAX_BYTES", 10*1024*1024),

		TokenPrice: getenvStrip("TOKEN_PRICE", "11.00"),
		TokenPackages: []TokenPackage{
			{Tokens: 5, Price: "65.00", Label: "Starter"},
			{Tokens: 20, Price: "220.00", Label: "Standard", Badge: "Most Popular"},
			{Tokens: 50, Price: "600.00", Label: "Plus"},
			{Tokens: 75, Price: "675.00", Label: "Premium", Badge: "Best Value", Highlight: true},
		},
		FirstPurchaseBonusTokens:   getenvInt("FIRST_PURCHASE_BONUS_TOKENS", 5),
		FreeMonthlyTokens:          getenvInt("FREE_MONTHLY_TOKENS", 25),
		FreeSignupTokens:           getenvInt("FREE_SIGNUP_TOKENS", 2),
		FreeJobPostTokensPerMonth:  getenvInt("FREE_JOB_POST_TOKENS_PER_MONTH", 5),
		RecruiterUnlockCostTokens:  getenvInt("RECRUITER_UNLOCK_COST_TOKENS", 5),
		FeedbackMinAccountAgeHours: getenvInt("FEEDBACK_MIN_ACCOUNT_AGE_HOURS", 24),

		APIFYAPIKey:            getenvStrip("APIFY_API_KEY", ""),
		MetaVerifyToken:        getenvStrip("META_VERIFY_TOKEN", "carver-whatsapp-verify"),
		WhatsAppAccessToken:    getenvStrip("WHATSAPP_ACCESS_TOKEN", ""),
		WhatsAppPhoneNumberID:  waPhone,
		FrontendBaseURL:        getenvStrip("FRONTEND_BASE_URL", "http://localhost:5173"),
		WAMagicTokenTTLSeconds: getenvInt("WA_MAGIC_TOKEN_TTL_SECONDS", 1800),
		WAMatchRecentDays:      getenvInt("WA_MATCH_RECENT_DAYS", 7),

		JobExpireAfterDays:        getenvInt("JOB_EXPIRE_AFTER_DAYS", 30),
		JobDeleteAfterDays:        getenvInt("JOB_DELETE_AFTER_DAYS", 90),
		JobRetentionIntervalHours: getenvInt("JOB_RETENTION_INTERVAL_HOURS", 24),

		AgentAPIToken:     getenvStrip("AGENT_API_TOKEN", ""),
		YocoPublicKey:     getenvStrip("YOCO_PUBLIC_KEY", ""),
		YocoSecretKey:     getenvStrip("YOCO_SECRET_KEY", ""),
		YocoWebhookSecret: getenvStrip("YOCO_WEBHOOK_SECRET", ""),
		TelnyxAPIKey:      getenvStrip("TELNYX_API_KEY", ""),

		Port: getenv("PORT", "3000"),
	}

	S = s
	return s
}
