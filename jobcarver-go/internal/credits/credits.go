// Package credits ports api/app/services/credits.py: the token-economy account
// logic (balances, monthly free grants, job-post earn cap, spending).
//
// Function names mirror the Python service so handlers read the same:
//
//	GetBalance -> get_credit_balance, AddCredits -> add_credits,
//	SpendCredits -> spend_credits, AwardJobPostCredit -> award_job_post_credit,
//	IsSubscribed -> is_subscribed.
package credits

import (
	"errors"
	"time"

	"gorm.io/gorm"

	"jobcarver/internal/config"
	"jobcarver/internal/models"
)

// ErrInsufficientCredits is returned by Spend when the balance is too low.
var ErrInsufficientCredits = errors.New("insufficient credits")

// IsSubscribed reports whether the user has an active paid subscription
// (ports is_subscribed).
func IsSubscribed(db *gorm.DB, userKey string) bool {
	var count int64
	db.Model(&models.Subscription{}).
		Where("user_key = ? AND status = ?", userKey, "active").
		Count(&count)
	return count > 0
}

// getOrCreateAccount ports _get_or_create_account: returns the user's account,
// creating it (initial balance = FreeMonthlyTokens if subscribed else
// FreeSignupTokens) if absent, and applying the monthly reset on existing ones.
// TODO(go-port): the Python retry-on-locked-DB loop is dropped — gorm + WAL
// busy_timeout handles contention.
func getOrCreateAccount(db *gorm.DB, userKey string) (*models.CreditAccount, error) {
	var account models.CreditAccount
	err := db.Where("user_key = ?", userKey).First(&account).Error
	if err == nil {
		maybeResetMonthly(db, &account)
		return &account, nil
	}
	if !errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, err
	}

	initial := config.S.FreeSignupTokens
	if IsSubscribed(db, userKey) {
		initial = config.S.FreeMonthlyTokens
	}
	now := time.Now().UTC()
	account = models.CreditAccount{
		UserKey:     userKey,
		Balance:     initial,
		LastResetAt: &now,
	}
	if err := db.Create(&account).Error; err != nil {
		return nil, err
	}
	return &account, nil
}

// maybeResetMonthly ports _maybe_reset_monthly: grant the monthly token
// allowance if 30+ days since last reset. Only subscribers receive the top-up.
func maybeResetMonthly(db *gorm.DB, account *models.CreditAccount) {
	now := time.Now().UTC()
	subscribed := IsSubscribed(db, account.UserKey)

	if account.LastResetAt == nil {
		if subscribed && account.Balance < config.S.FreeMonthlyTokens {
			account.Balance = config.S.FreeMonthlyTokens
		}
		account.LastResetAt = &now
		db.Save(account)
		return
	}
	if now.Sub(account.LastResetAt.UTC()) >= 30*24*time.Hour {
		if subscribed && account.Balance < config.S.FreeMonthlyTokens {
			account.Balance = config.S.FreeMonthlyTokens
		}
		account.LastResetAt = &now
		db.Save(account)
	}
}

// GetBalance returns the user's current token balance, creating the account if
// needed (ports get_credit_balance). Returns 0 on error.
func GetBalance(db *gorm.DB, userKey string) int {
	account, err := getOrCreateAccount(db, userKey)
	if err != nil {
		return 0
	}
	return account.Balance
}

// AddCredits adds amount tokens and returns the new balance (ports add_credits).
func AddCredits(db *gorm.DB, userKey string, amount int) (int, error) {
	if amount < 0 {
		return 0, errors.New("amount must be non-negative")
	}
	account, err := getOrCreateAccount(db, userKey)
	if err != nil {
		return 0, err
	}
	account.Balance += amount
	if err := db.Save(account).Error; err != nil {
		return 0, err
	}
	return account.Balance, nil
}

// SpendCredits deducts amount tokens. ok is false (and balance is the unchanged
// current balance) when the user has insufficient credits (ports spend_credits,
// where the Python returns None on insufficient funds).
func SpendCredits(db *gorm.DB, userKey string, amount int) (balance int, ok bool) {
	if amount < 0 {
		return 0, false
	}
	account, err := getOrCreateAccount(db, userKey)
	if err != nil {
		return 0, false
	}
	if account.Balance < amount {
		return account.Balance, false
	}
	account.Balance -= amount
	if err := db.Save(account).Error; err != nil {
		return account.Balance, false
	}
	return account.Balance, true
}

// AwardJobPostCredit grants +1 free token for posting a job, capped per 30-day
// window (FreeJobPostTokensPerMonth, shared web + WhatsApp). Ports
// award_job_post_credit. Returns (granted, balance, remaining).
func AwardJobPostCredit(db *gorm.DB, userKey string) (granted bool, balance int, remaining int) {
	cap := config.S.FreeJobPostTokensPerMonth
	account, err := getOrCreateAccount(db, userKey)
	if err != nil {
		return false, 0, 0
	}
	now := time.Now().UTC()
	if account.JobPostWindowStart == nil || now.Sub(account.JobPostWindowStart.UTC()) >= 30*24*time.Hour {
		account.JobPostTokensEarned = 0
		account.JobPostWindowStart = &now
	}
	if account.JobPostTokensEarned >= cap {
		db.Save(account)
		return false, account.Balance, 0
	}
	account.Balance++
	account.JobPostTokensEarned++
	db.Save(account)
	rem := cap - account.JobPostTokensEarned
	if rem < 0 {
		rem = 0
	}
	return true, account.Balance, rem
}

// ── Backward-compatible aliases ─────────────────────────────────────────────
// Kept so any handler written against the earlier draft contract still compiles.

// EnsureAccount creates the user's credit account if it does not yet exist.
func EnsureAccount(db *gorm.DB, userKey string) error {
	_, err := getOrCreateAccount(db, userKey)
	return err
}

// Grant is an alias for AddCredits that discards the new balance.
func Grant(db *gorm.DB, userKey string, amount int) error {
	_, err := AddCredits(db, userKey, amount)
	return err
}

// Spend is an alias for SpendCredits returning ErrInsufficientCredits when funds
// are too low.
func Spend(db *gorm.DB, userKey string, amount int) error {
	if _, ok := SpendCredits(db, userKey, amount); !ok {
		return ErrInsufficientCredits
	}
	return nil
}

// ApplyFreeMonthlyGrantIfDue applies the 30-day monthly reset for a user.
func ApplyFreeMonthlyGrantIfDue(db *gorm.DB, userKey string) {
	_, _ = getOrCreateAccount(db, userKey)
}
