package models

import (
	"time"

	"golang.org/x/crypto/bcrypt"
)

type User struct {
	ID        string    `json:"id" db:"id"`
	Email     string    `json:"email" db:"email"`
	Password  string    `json:"-" db:"password_hash"` // Never expose password in JSON
	FirstName string    `json:"first_name" db:"first_name"`
	LastName  string    `json:"last_name" db:"last_name"`
	Role      string    `json:"role" db:"role"`
	CreatedAt time.Time `json:"created_at" db:"created_at"`
	UpdatedAt time.Time `json:"updated_at" db:"updated_at"`
	
	// Profile Information
	Description       *string `json:"description,omitempty" db:"description"`
	Gender           *string `json:"gender,omitempty" db:"gender"`
	CountryOfOrigin  *string `json:"country_of_origin,omitempty" db:"country_of_origin"`
	CurrentLocation  *string `json:"current_location,omitempty" db:"current_location"`
	Availability     *string `json:"availability,omitempty" db:"availability"`
	
	// Documents and Files
	CVFilePath              *string `json:"cv_file_path,omitempty" db:"cv_file_path"`
	PictureFilePath         *string `json:"picture_file_path,omitempty" db:"picture_file_path"`
	ReferenceLettersFilePath *string `json:"reference_letters_file_path,omitempty" db:"reference_letters_file_path"`
	
	// Visa and Work Authorization
	VisaStatus        *string `json:"visa_status,omitempty" db:"visa_status"`
	WorkAuthorization *string `json:"work_authorization,omitempty" db:"work_authorization"`
	PassportCountry   *string `json:"passport_country,omitempty" db:"passport_country"`
	
	// Subscription Information
	SubscriptionType      *string    `json:"subscription_type,omitempty" db:"subscription_type"`
	SubscriptionStartDate *time.Time `json:"subscription_start_date,omitempty" db:"subscription_start_date"`
	SubscriptionEndDate   *time.Time `json:"subscription_end_date,omitempty" db:"subscription_end_date"`
	SubscriptionStatus    *string    `json:"subscription_status,omitempty" db:"subscription_status"`
	
	// Contact and Additional Info
	PhoneNumber         *string `json:"phone_number,omitempty" db:"phone_number"`
	LinkedinProfile     *string `json:"linkedin_profile,omitempty" db:"linkedin_profile"`
	YearsOfExperience   *int    `json:"years_of_experience,omitempty" db:"years_of_experience"`
	PreferredJobTypes   *string `json:"preferred_job_types,omitempty" db:"preferred_job_types"`     // JSON array as string
	PreferredLocations  *string `json:"preferred_locations,omitempty" db:"preferred_locations"`   // JSON array as string
	SalaryExpectation   *string `json:"salary_expectation,omitempty" db:"salary_expectation"`
	LanguagesSpoken     *string `json:"languages_spoken,omitempty" db:"languages_spoken"`         // JSON array as string
	Certifications      *string `json:"certifications,omitempty" db:"certifications"`             // JSON array as string
	
	// Profile completion and verification
	ProfileCompleted            *bool `json:"profile_completed,omitempty" db:"profile_completed"`
	ProfileVerified             *bool `json:"profile_verified,omitempty" db:"profile_verified"`
	ProfileCompletionPercentage *int  `json:"profile_completion_percentage,omitempty" db:"profile_completion_percentage"`
}

type CreateUserRequest struct {
	Email     string `json:"email" validate:"required,email"`
	Password  string `json:"password" validate:"required,min=8"`
	FirstName string `json:"first_name" validate:"required"`
	LastName  string `json:"last_name" validate:"required"`
	// Optional profile fields during registration
	PhoneNumber     *string `json:"phone_number,omitempty"`
	CountryOfOrigin *string `json:"country_of_origin,omitempty"`
	CurrentLocation *string `json:"current_location,omitempty"`
}

type UpdateUserProfileRequest struct {
	// Profile Information
	Description       *string `json:"description,omitempty"`
	Gender           *string `json:"gender,omitempty"`
	CountryOfOrigin  *string `json:"country_of_origin,omitempty"`
	CurrentLocation  *string `json:"current_location,omitempty"`
	Availability     *string `json:"availability,omitempty"`
	
	// Visa and Work Authorization
	VisaStatus        *string `json:"visa_status,omitempty"`
	WorkAuthorization *string `json:"work_authorization,omitempty"`
	PassportCountry   *string `json:"passport_country,omitempty"`
	
	// Contact and Additional Info
	PhoneNumber         *string `json:"phone_number,omitempty"`
	LinkedinProfile     *string `json:"linkedin_profile,omitempty"`
	YearsOfExperience   *int    `json:"years_of_experience,omitempty"`
	PreferredJobTypes   *string `json:"preferred_job_types,omitempty"`
	PreferredLocations  *string `json:"preferred_locations,omitempty"`
	SalaryExpectation   *string `json:"salary_expectation,omitempty"`
	LanguagesSpoken     *string `json:"languages_spoken,omitempty"`
	Certifications      *string `json:"certifications,omitempty"`
}

type LoginRequest struct {
	Email    string `json:"email" validate:"required,email"`
	Password string `json:"password" validate:"required"`
}

type LoginResponse struct {
	Token string `json:"token"`
	User  User   `json:"user"`
}

// HashPassword hashes the user's password using bcrypt
func (u *User) HashPassword(password string) error {
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	u.Password = string(hashedPassword)
	return nil
}

// CheckPassword verifies the password against the hash
func (u *User) CheckPassword(password string) bool {
	err := bcrypt.CompareHashAndPassword([]byte(u.Password), []byte(password))
	return err == nil
} 