package services

import (
	"database/sql"
	"fmt"
	"strings"
	"time"

	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/auth"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/database"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/models"
	"github.com/google/uuid"
)

type UserService struct {
	db         *database.DB
	jwtService *auth.JWTService
}

func NewUserService(db *database.DB, jwtService *auth.JWTService) *UserService {
	return &UserService{
		db:         db,
		jwtService: jwtService,
	}
}

func (s *UserService) CreateUser(req models.CreateUserRequest) (*models.User, error) {
	// Check if user already exists
	var exists bool
	err := s.db.QueryRow("SELECT EXISTS(SELECT 1 FROM users WHERE email = $1)", req.Email).Scan(&exists)
	if err != nil {
		return nil, fmt.Errorf("failed to check user existence: %w", err)
	}
	if exists {
		return nil, fmt.Errorf("user with email %s already exists", req.Email)
	}

	// Create new user
	user := &models.User{
		ID:        uuid.New().String(),
		Email:     req.Email,
		FirstName: req.FirstName,
		LastName:  req.LastName,
		Role:      "user",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
		// Set optional profile fields from request if provided
		PhoneNumber:     req.PhoneNumber,
		CountryOfOrigin: req.CountryOfOrigin,
		CurrentLocation: req.CurrentLocation,
	}

	// Hash password
	if err := user.HashPassword(req.Password); err != nil {
		return nil, fmt.Errorf("failed to hash password: %w", err)
	}

	// Insert user into database with new fields
	query := `
		INSERT INTO users (id, email, password_hash, first_name, last_name, role, created_at, updated_at, phone_number, country_of_origin, current_location)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
	`
	_, err = s.db.Exec(query, user.ID, user.Email, user.Password, user.FirstName, user.LastName, user.Role, user.CreatedAt, user.UpdatedAt, user.PhoneNumber, user.CountryOfOrigin, user.CurrentLocation)
	if err != nil {
		return nil, fmt.Errorf("failed to create user: %w", err)
	}

	return user, nil
}

func (s *UserService) UpdateUserProfile(userID string, req models.UpdateUserProfileRequest) error {
	// Build dynamic query based on provided fields
	setParts := []string{}
	args := []interface{}{}
	argIndex := 1

	if req.Description != nil {
		setParts = append(setParts, fmt.Sprintf("description = $%d", argIndex))
		args = append(args, *req.Description)
		argIndex++
	}
	if req.Gender != nil {
		setParts = append(setParts, fmt.Sprintf("gender = $%d", argIndex))
		args = append(args, *req.Gender)
		argIndex++
	}
	if req.CountryOfOrigin != nil {
		setParts = append(setParts, fmt.Sprintf("country_of_origin = $%d", argIndex))
		args = append(args, *req.CountryOfOrigin)
		argIndex++
	}
	if req.CurrentLocation != nil {
		setParts = append(setParts, fmt.Sprintf("current_location = $%d", argIndex))
		args = append(args, *req.CurrentLocation)
		argIndex++
	}
	if req.Availability != nil {
		setParts = append(setParts, fmt.Sprintf("availability = $%d", argIndex))
		args = append(args, *req.Availability)
		argIndex++
	}
	if req.VisaStatus != nil {
		setParts = append(setParts, fmt.Sprintf("visa_status = $%d", argIndex))
		args = append(args, *req.VisaStatus)
		argIndex++
	}
	if req.WorkAuthorization != nil {
		setParts = append(setParts, fmt.Sprintf("work_authorization = $%d", argIndex))
		args = append(args, *req.WorkAuthorization)
		argIndex++
	}
	if req.PassportCountry != nil {
		setParts = append(setParts, fmt.Sprintf("passport_country = $%d", argIndex))
		args = append(args, *req.PassportCountry)
		argIndex++
	}
	if req.PhoneNumber != nil {
		setParts = append(setParts, fmt.Sprintf("phone_number = $%d", argIndex))
		args = append(args, *req.PhoneNumber)
		argIndex++
	}
	if req.LinkedinProfile != nil {
		setParts = append(setParts, fmt.Sprintf("linkedin_profile = $%d", argIndex))
		args = append(args, *req.LinkedinProfile)
		argIndex++
	}
	if req.YearsOfExperience != nil {
		setParts = append(setParts, fmt.Sprintf("years_of_experience = $%d", argIndex))
		args = append(args, *req.YearsOfExperience)
		argIndex++
	}
	if req.PreferredJobTypes != nil {
		setParts = append(setParts, fmt.Sprintf("preferred_job_types = $%d", argIndex))
		args = append(args, *req.PreferredJobTypes)
		argIndex++
	}
	if req.PreferredLocations != nil {
		setParts = append(setParts, fmt.Sprintf("preferred_locations = $%d", argIndex))
		args = append(args, *req.PreferredLocations)
		argIndex++
	}
	if req.SalaryExpectation != nil {
		setParts = append(setParts, fmt.Sprintf("salary_expectation = $%d", argIndex))
		args = append(args, *req.SalaryExpectation)
		argIndex++
	}
	if req.LanguagesSpoken != nil {
		setParts = append(setParts, fmt.Sprintf("languages_spoken = $%d", argIndex))
		args = append(args, *req.LanguagesSpoken)
		argIndex++
	}
	if req.Certifications != nil {
		setParts = append(setParts, fmt.Sprintf("certifications = $%d", argIndex))
		args = append(args, *req.Certifications)
		argIndex++
	}

	if len(setParts) == 0 {
		return fmt.Errorf("no fields to update")
	}

	// Always update the updated_at timestamp
	setParts = append(setParts, fmt.Sprintf("updated_at = $%d", argIndex))
	args = append(args, time.Now())
	argIndex++

	// Add the user ID for the WHERE clause
	args = append(args, userID)

	query := fmt.Sprintf("UPDATE users SET %s WHERE id = $%d", strings.Join(setParts, ", "), argIndex)

	_, err := s.db.Exec(query, args...)
	if err != nil {
		return fmt.Errorf("failed to update user profile: %w", err)
	}

	return nil
}

func (s *UserService) LoginUser(req models.LoginRequest) (*models.LoginResponse, error) {
	// Get user by email
	user := &models.User{}
	query := `
		SELECT id, email, password_hash, first_name, last_name, role, created_at, updated_at,
		       phone_number, country_of_origin, current_location
		FROM users WHERE email = $1
	`
	err := s.db.QueryRow(query, req.Email).Scan(
		&user.ID, &user.Email, &user.Password, &user.FirstName,
		&user.LastName, &user.Role, &user.CreatedAt, &user.UpdatedAt,
		&user.PhoneNumber, &user.CountryOfOrigin, &user.CurrentLocation,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("invalid credentials")
		}
		return nil, fmt.Errorf("failed to get user: %w", err)
	}

	// Check password
	if !user.CheckPassword(req.Password) {
		return nil, fmt.Errorf("invalid credentials")
	}

	// Generate JWT token
	token, err := s.jwtService.GenerateToken(user.ID, user.Email, user.Role)
	if err != nil {
		return nil, fmt.Errorf("failed to generate token: %w", err)
	}

	return &models.LoginResponse{
		Token: token,
		User:  *user,
	}, nil
}

func (s *UserService) GetUserByID(userID string) (*models.User, error) {
	user := &models.User{}
	query := `
		SELECT id, email, password_hash, first_name, last_name, role, created_at, updated_at,
		       phone_number, country_of_origin, current_location,
		       description, gender, availability, cv_file_path, picture_file_path, reference_letters_file_path,
		       visa_status, work_authorization, passport_country, subscription_type, subscription_start_date,
		       subscription_end_date, subscription_status, linkedin_profile, years_of_experience,
		       preferred_job_types, preferred_locations, salary_expectation, languages_spoken, certifications,
		       profile_completed, profile_verified, profile_completion_percentage
		FROM users WHERE id = $1
	`
	err := s.db.QueryRow(query, userID).Scan(
		&user.ID, &user.Email, &user.Password, &user.FirstName,
		&user.LastName, &user.Role, &user.CreatedAt, &user.UpdatedAt,
		&user.PhoneNumber, &user.CountryOfOrigin, &user.CurrentLocation,
		&user.Description, &user.Gender, &user.Availability, &user.CVFilePath, &user.PictureFilePath, &user.ReferenceLettersFilePath,
		&user.VisaStatus, &user.WorkAuthorization, &user.PassportCountry, &user.SubscriptionType, &user.SubscriptionStartDate,
		&user.SubscriptionEndDate, &user.SubscriptionStatus, &user.LinkedinProfile, &user.YearsOfExperience,
		&user.PreferredJobTypes, &user.PreferredLocations, &user.SalaryExpectation, &user.LanguagesSpoken, &user.Certifications,
		&user.ProfileCompleted, &user.ProfileVerified, &user.ProfileCompletionPercentage,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("user not found")
		}
		return nil, fmt.Errorf("failed to get user: %w", err)
	}

	return user, nil
} 