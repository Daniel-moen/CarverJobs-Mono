// Package models holds the GORM structs ported from api/app/models.py.
// Column names and table names match the Python/SQLAlchemy schema exactly so the
// Go service reads and writes the same SQLite database.
package models

import "time"

// Job ports the `jobs` table.
type Job struct {
	ID                      int       `gorm:"column:id;primaryKey"`
	Title                   string    `gorm:"column:title;not null"`
	Role                    string    `gorm:"column:role;not null"`
	Yacht                   string    `gorm:"column:yacht;not null"`
	YachtType               *string   `gorm:"column:yacht_type"`
	YachtLengthM            *int      `gorm:"column:yacht_length_m"`
	VesselFlag              *string   `gorm:"column:vessel_flag"`
	VesselItinerary         *string   `gorm:"column:vessel_itinerary"`
	Department              *string   `gorm:"column:department"`
	RankLevel               *string   `gorm:"column:rank_level"`
	Location                string    `gorm:"column:location;not null"`
	StartDate               *string   `gorm:"column:start_date"`
	ContractType            *string   `gorm:"column:contract_type"`
	LeaveStructure          *string   `gorm:"column:leave_structure"`
	Rotation                *string   `gorm:"column:rotation"`
	Season                  *string   `gorm:"column:season"`
	SalaryCurrency          *string   `gorm:"column:salary_currency;default:EUR"`
	SalaryMin               *float64  `gorm:"column:salary_min"`
	SalaryMax               *float64  `gorm:"column:salary_max"`
	TipsBonus               *string   `gorm:"column:tips_bonus"`
	VisaSupport             bool      `gorm:"column:visa_support;not null;default:false"`
	Accommodation           *string   `gorm:"column:accommodation"`
	TravelReimbursement     bool      `gorm:"column:travel_reimbursement;not null;default:false"`
	ExperienceRequiredYears *int      `gorm:"column:experience_required_years"`
	MinimumLicense          *string   `gorm:"column:minimum_license"`
	CertificationsRequired  *string   `gorm:"column:certifications_required"`
	LanguagesRequired       *string   `gorm:"column:languages_required"`
	Description             *string   `gorm:"column:description"`
	Responsibilities        *string   `gorm:"column:responsibilities"`
	Requirements            *string   `gorm:"column:requirements"`
	Benefits                *string   `gorm:"column:benefits"`
	ContactEmail            *string   `gorm:"column:contact_email"`
	ApplicationURL          *string   `gorm:"column:application_url"`
	RecruiterName           *string   `gorm:"column:recruiter_name"`
	RecruiterAgency         *string   `gorm:"column:recruiter_agency"`
	UrgentHire              bool      `gorm:"column:urgent_hire;not null;default:false"`
	Status                  string    `gorm:"column:status;not null;default:open;index"`
	AutoApplyEnabled        bool      `gorm:"column:auto_apply_enabled;not null;default:false"`
	Source                  *string   `gorm:"column:source;default:manual;index"`
	PostedByUserID          *int      `gorm:"column:posted_by_user_id;index"`
	PostedByAgency          *string   `gorm:"column:posted_by_agency;index"`
	ContentHash             *string   `gorm:"column:content_hash;uniqueIndex"`
	JobFingerprint          *string   `gorm:"column:job_fingerprint;uniqueIndex"`
	CreatedAt               time.Time `gorm:"column:created_at;not null;index"`
	UpdatedAt               time.Time `gorm:"column:updated_at;not null"`
}

func (Job) TableName() string { return "jobs" }

// User ports the `users` table.
type User struct {
	ID              int       `gorm:"column:id;primaryKey"`
	Email           string    `gorm:"column:email;uniqueIndex;not null"`
	FullName        string    `gorm:"column:full_name;not null"`
	Role            string    `gorm:"column:role;not null;default:crew"`
	Phone           *string   `gorm:"column:phone"`
	Nationality     *string   `gorm:"column:nationality"`
	YearsExperience *int      `gorm:"column:years_experience"`
	CurrentLocation *string   `gorm:"column:current_location"`
	Gender          *string   `gorm:"column:gender"`
	PasswordHash    string    `gorm:"column:password_hash;not null"`
	IsActive        bool      `gorm:"column:is_active;not null;default:true"`
	IsSubscribed    bool      `gorm:"column:is_subscribed;not null;default:false"`
	EarlyBird       bool      `gorm:"column:early_bird;not null;default:false"`
	AgencyName      *string   `gorm:"column:agency_name;index"`
	CreatedAt       time.Time `gorm:"column:created_at;not null"`
	UpdatedAt       time.Time `gorm:"column:updated_at;not null"`
}

func (User) TableName() string { return "users" }

// Document ports the `documents` table.
type Document struct {
	ID           int       `gorm:"column:id;primaryKey"`
	UserKey      string    `gorm:"column:user_key;not null;index;uniqueIndex:uq_document_user_doctype,priority:1"`
	DocType      string    `gorm:"column:doc_type;not null;uniqueIndex:uq_document_user_doctype,priority:2"`
	OriginalName string    `gorm:"column:original_name;not null"`
	StoredName   string    `gorm:"column:stored_name;not null"`
	ScannedText  *string   `gorm:"column:scanned_text"`
	CreatedAt    time.Time `gorm:"column:created_at;not null"`
}

func (Document) TableName() string { return "documents" }

// CrewProfile ports the `crew_profiles` table.
type CrewProfile struct {
	ID                 int       `gorm:"column:id;primaryKey"`
	UserKey            string    `gorm:"column:user_key;uniqueIndex;not null"`
	ProfileSlug        string    `gorm:"column:profile_slug;uniqueIndex;not null"`
	FirstName          *string   `gorm:"column:first_name"`
	LastName           *string   `gorm:"column:last_name"`
	Sex                *string   `gorm:"column:sex"`
	Phone              *string   `gorm:"column:phone"`
	Nationality        *string   `gorm:"column:nationality"`
	CurrentLocation    *string   `gorm:"column:current_location"`
	DesiredRole        *string   `gorm:"column:desired_role"`
	ContractType       *string   `gorm:"column:contract_type"`
	PreferredLocations *string   `gorm:"column:preferred_locations"`
	RotationPreference *string   `gorm:"column:rotation_preference"`
	YearsExperience    *string   `gorm:"column:years_experience"`
	AvailableFrom      *string   `gorm:"column:available_from"`
	SalaryMin          *string   `gorm:"column:salary_min"`
	SalaryMax          *string   `gorm:"column:salary_max"`
	Certifications     *string   `gorm:"column:certifications"`
	Languages          *string   `gorm:"column:languages"`
	Bio                *string   `gorm:"column:bio"`
	Discoverable       bool      `gorm:"column:discoverable;not null;default:true"`
	CreatedAt          time.Time `gorm:"column:created_at;not null"`
	UpdatedAt          time.Time `gorm:"column:updated_at;not null"`
}

func (CrewProfile) TableName() string { return "crew_profiles" }

// JobHistoryEntry ports the `job_history` table.
type JobHistoryEntry struct {
	ID          int       `gorm:"column:id;primaryKey"`
	UserKey     string    `gorm:"column:user_key;not null;index"`
	YachtName   string    `gorm:"column:yacht_name;not null"`
	YachtType   *string   `gorm:"column:yacht_type"`
	Role        string    `gorm:"column:role;not null"`
	StartDate   *string   `gorm:"column:start_date"`
	EndDate     *string   `gorm:"column:end_date"`
	Description *string   `gorm:"column:description"`
	CreatedAt   time.Time `gorm:"column:created_at;not null"`
}

func (JobHistoryEntry) TableName() string { return "job_history" }

// WhatsAppSession ports the `whatsapp_sessions` table.
type WhatsAppSession struct {
	PhoneNumber    string    `gorm:"column:phone_number;primaryKey"`
	Mode           string    `gorm:"column:mode;not null;default:onboarding"`
	History        string    `gorm:"column:history;not null;default:'[]'"`
	PartialProfile string    `gorm:"column:partial_profile;not null;default:'{}'"`
	CreatedAt      time.Time `gorm:"column:created_at;not null"`
	UpdatedAt      time.Time `gorm:"column:updated_at;not null"`
}

func (WhatsAppSession) TableName() string { return "whatsapp_sessions" }

// WhatsAppMessage ports the `whatsapp_messages` table.
type WhatsAppMessage struct {
	ID                 int       `gorm:"column:id;primaryKey"`
	PhoneNumber        string    `gorm:"column:phone_number;not null;index"`
	Direction          string    `gorm:"column:direction;not null;index"`
	MessageType        string    `gorm:"column:message_type;not null;default:text"`
	Content            *string   `gorm:"column:content"`
	MetaMessageID      *string   `gorm:"column:meta_message_id;uniqueIndex"`
	GraphPhoneNumberID *string   `gorm:"column:graph_phone_number_id"`
	PayloadJSON        *string   `gorm:"column:payload_json"`
	CreatedAt          time.Time `gorm:"column:created_at;not null;index"`
}

func (WhatsAppMessage) TableName() string { return "whatsapp_messages" }

// WhatsAppMagicToken ports the `whatsapp_magic_tokens` table.
type WhatsAppMagicToken struct {
	Token       string    `gorm:"column:token;primaryKey"`
	PhoneNumber string    `gorm:"column:phone_number;not null;index"`
	ExpiresAt   time.Time `gorm:"column:expires_at;not null"`
	Used        bool      `gorm:"column:used;not null;default:false"`
	RedirectTo  *string   `gorm:"column:redirect_to"`
	CreatedAt   time.Time `gorm:"column:created_at;not null"`
}

func (WhatsAppMagicToken) TableName() string { return "whatsapp_magic_tokens" }

// AnalyticsEvent ports the `analytics_events` table.
type AnalyticsEvent struct {
	ID        int       `gorm:"column:id;primaryKey"`
	SessionID string    `gorm:"column:session_id;not null;index"`
	EventType string    `gorm:"column:event_type;not null;index"`
	Page      *string   `gorm:"column:page"`
	Label     *string   `gorm:"column:label"`
	Value     *string   `gorm:"column:value"`
	ErrorCode *string   `gorm:"column:error_code"`
	ClientTS  *string   `gorm:"column:client_ts"`
	CreatedAt time.Time `gorm:"column:created_at;not null;index"`
}

func (AnalyticsEvent) TableName() string { return "analytics_events" }

// ErrorLog ports the `error_logs` table.
type ErrorLog struct {
	ID         int       `gorm:"column:id;primaryKey"`
	CreatedAt  time.Time `gorm:"column:created_at;not null;index"`
	Level      string    `gorm:"column:level;not null;default:error"`
	StatusCode *int      `gorm:"column:status_code"`
	CrvCode    *string   `gorm:"column:crv_code"`
	Method     *string   `gorm:"column:method"`
	Path       *string   `gorm:"column:path"`
	Module     *string   `gorm:"column:module"`
	Message    string    `gorm:"column:message;not null"`
	Traceback  *string   `gorm:"column:traceback"`
	RequestID  *string   `gorm:"column:request_id"`
	ClientIP   *string   `gorm:"column:client_ip"`
	AIAnalysis *string   `gorm:"column:ai_analysis"`
}

func (ErrorLog) TableName() string { return "error_logs" }

// WaitlistSignup ports the `waitlist_signups` table.
type WaitlistSignup struct {
	ID        int       `gorm:"column:id;primaryKey"`
	Email     string    `gorm:"column:email;uniqueIndex;not null"`
	Source    string    `gorm:"column:source;not null;default:website"`
	CreatedAt time.Time `gorm:"column:created_at;not null;index"`
}

func (WaitlistSignup) TableName() string { return "waitlist_signups" }

// Subscription ports the `subscriptions` table.
type Subscription struct {
	ID              int       `gorm:"column:id;primaryKey"`
	UserKey         string    `gorm:"column:user_key;not null;index"`
	MPaymentID      string    `gorm:"column:m_payment_id;uniqueIndex;not null"`
	PaymentToken    *string   `gorm:"column:payment_token"`
	CheckoutID      *string   `gorm:"column:checkout_id"`
	Status          string    `gorm:"column:status;not null;default:pending"`
	Amount          string    `gorm:"column:amount;not null"`
	Frequency       int       `gorm:"column:frequency;not null;default:3"`
	NextBillingDate *string   `gorm:"column:next_billing_date"`
	CreatedAt       time.Time `gorm:"column:created_at;not null"`
	UpdatedAt       time.Time `gorm:"column:updated_at;not null"`
}

func (Subscription) TableName() string { return "subscriptions" }

// CreditAccount ports the `credit_accounts` table.
type CreditAccount struct {
	ID                  int        `gorm:"column:id;primaryKey"`
	UserKey             string     `gorm:"column:user_key;uniqueIndex;not null"`
	Balance             int        `gorm:"column:balance;not null;default:0"`
	LastResetAt         *time.Time `gorm:"column:last_reset_at"`
	JobPostTokensEarned int        `gorm:"column:job_post_tokens_earned;not null;default:0"`
	JobPostWindowStart  *time.Time `gorm:"column:job_post_window_start"`
	CreatedAt           time.Time  `gorm:"column:created_at;not null"`
	UpdatedAt           time.Time  `gorm:"column:updated_at;not null"`
}

func (CreditAccount) TableName() string { return "credit_accounts" }

// ContactUnlock ports the `contact_unlocks` table.
type ContactUnlock struct {
	ID            int       `gorm:"column:id;primaryKey"`
	AgencyUserKey string    `gorm:"column:agency_user_key;not null;index;uniqueIndex:uq_contact_unlock_agency_crew,priority:1"`
	CrewUserKey   string    `gorm:"column:crew_user_key;not null;index;uniqueIndex:uq_contact_unlock_agency_crew,priority:2"`
	ProfileSlug   string    `gorm:"column:profile_slug;not null;index"`
	CostTokens    int       `gorm:"column:cost_tokens;not null;default:0"`
	CreatedAt     time.Time `gorm:"column:created_at;not null"`
}

func (ContactUnlock) TableName() string { return "contact_unlocks" }

// FeedbackSubmission ports the `feedback_submissions` table.
type FeedbackSubmission struct {
	ID           int       `gorm:"column:id;primaryKey"`
	UserKey      string    `gorm:"column:user_key;not null;index;uniqueIndex:uq_feedback_user_campaign,priority:1"`
	Campaign     string    `gorm:"column:campaign;not null;default:feedback_2_tokens;index;uniqueIndex:uq_feedback_user_campaign,priority:2"`
	Source       string    `gorm:"column:source;not null;default:website_popup;index"`
	Rating       int       `gorm:"column:rating;not null"`
	Liked        *string   `gorm:"column:liked"`
	Improved     *string   `gorm:"column:improved"`
	Confusing    *string   `gorm:"column:confusing"`
	Recommend    *string   `gorm:"column:recommend"`
	AnythingElse *string   `gorm:"column:anything_else"`
	RewardAmount int       `gorm:"column:reward_amount;not null;default:2"`
	Rewarded     bool      `gorm:"column:rewarded;not null;default:true"`
	CreatedAt    time.Time `gorm:"column:created_at;not null;index"`
}

func (FeedbackSubmission) TableName() string { return "feedback_submissions" }

// FeedbackCampaignSetting ports the `feedback_campaign_settings` table.
type FeedbackCampaignSetting struct {
	Campaign           string    `gorm:"column:campaign;primaryKey"`
	Enabled            bool      `gorm:"column:enabled;not null;default:true"`
	TargetMode         string    `gorm:"column:target_mode;not null;default:all"`
	TargetUserKeysJSON string    `gorm:"column:target_user_keys_json;not null;default:'[]'"`
	UpdatedAt          time.Time `gorm:"column:updated_at;not null"`
}

func (FeedbackCampaignSetting) TableName() string { return "feedback_campaign_settings" }

// MatchSession ports the `match_sessions` table.
type MatchSession struct {
	ID               int        `gorm:"column:id;primaryKey"`
	UserKey          string     `gorm:"column:user_key;not null;index"`
	Status           string     `gorm:"column:status;not null;default:running"`
	TotalJobsScanned int        `gorm:"column:total_jobs_scanned;not null;default:0"`
	TotalMatched     int        `gorm:"column:total_matched;not null;default:0"`
	CreatedAt        time.Time  `gorm:"column:created_at;not null;index"`
	CompletedAt      *time.Time `gorm:"column:completed_at"`
}

func (MatchSession) TableName() string { return "match_sessions" }

// MatchSessionResult ports the `match_session_results` table.
type MatchSessionResult struct {
	ID            int     `gorm:"column:id;primaryKey"`
	SessionID     int     `gorm:"column:session_id;not null;index"`
	JobID         int     `gorm:"column:job_id;not null"`
	Matched       bool    `gorm:"column:matched;not null;default:false"`
	Compatibility float64 `gorm:"column:compatibility;not null;default:0"`
	Reason        *string `gorm:"column:reason"`
	Strengths     *string `gorm:"column:strengths"`
	Gaps          *string `gorm:"column:gaps"`
	FactorScores  *string `gorm:"column:factor_scores"`
}

func (MatchSessionResult) TableName() string { return "match_session_results" }

// Article ports the `articles` table.
type Article struct {
	ID           int       `gorm:"column:id;primaryKey"`
	Slug         string    `gorm:"column:slug;uniqueIndex;not null"`
	Title        string    `gorm:"column:title;not null"`
	Description  string    `gorm:"column:description;not null"`
	Date         string    `gorm:"column:date;not null"`
	ReadMinutes  int       `gorm:"column:read_minutes;not null;default:3"`
	KeywordsJSON string    `gorm:"column:keywords_json;not null;default:'[]'"`
	BodyJSON     string    `gorm:"column:body_json;not null;default:'[]'"`
	Published    bool      `gorm:"column:published;not null;default:true;index"`
	CreatedAt    time.Time `gorm:"column:created_at;not null"`
	UpdatedAt    time.Time `gorm:"column:updated_at;not null"`
}

func (Article) TableName() string { return "articles" }

// JobDraftEvent ports the `job_drafts` table.
type JobDraftEvent struct {
	ID        int       `gorm:"column:id;primaryKey"`
	JobID     int       `gorm:"column:job_id;not null;index;uniqueIndex:uq_job_drafts_job_user,priority:1"`
	UserKey   string    `gorm:"column:user_key;not null;index;uniqueIndex:uq_job_drafts_job_user,priority:2"`
	CreatedAt time.Time `gorm:"column:created_at;not null"`
	UpdatedAt time.Time `gorm:"column:updated_at;not null"`
}

func (JobDraftEvent) TableName() string { return "job_drafts" }

// AllModels returns one pointer per table for AutoMigrate.
func AllModels() []any {
	return []any{
		&Job{},
		&User{},
		&Document{},
		&CrewProfile{},
		&JobHistoryEntry{},
		&WhatsAppSession{},
		&WhatsAppMessage{},
		&WhatsAppMagicToken{},
		&AnalyticsEvent{},
		&ErrorLog{},
		&WaitlistSignup{},
		&Subscription{},
		&CreditAccount{},
		&ContactUnlock{},
		&FeedbackSubmission{},
		&FeedbackCampaignSetting{},
		&MatchSession{},
		&MatchSessionResult{},
		&Article{},
		&JobDraftEvent{},
	}
}
