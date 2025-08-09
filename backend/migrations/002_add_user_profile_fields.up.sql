-- Add user profile fields for job matching (SQLite compatible)
-- Profile Information
ALTER TABLE users ADD COLUMN description TEXT;
ALTER TABLE users ADD COLUMN gender VARCHAR(50);
ALTER TABLE users ADD COLUMN country_of_origin VARCHAR(100);
ALTER TABLE users ADD COLUMN current_location VARCHAR(200);
ALTER TABLE users ADD COLUMN availability VARCHAR(100);

-- Documents and Files
ALTER TABLE users ADD COLUMN cv_file_path TEXT;
ALTER TABLE users ADD COLUMN picture_file_path TEXT;
ALTER TABLE users ADD COLUMN reference_letters_file_path TEXT;

-- Visa and Work Authorization
ALTER TABLE users ADD COLUMN visa_status VARCHAR(100);
ALTER TABLE users ADD COLUMN work_authorization VARCHAR(100);
ALTER TABLE users ADD COLUMN passport_country VARCHAR(100);

-- Subscription Information
ALTER TABLE users ADD COLUMN subscription_type VARCHAR(50) DEFAULT 'free';
ALTER TABLE users ADD COLUMN subscription_start_date TIMESTAMP;
ALTER TABLE users ADD COLUMN subscription_end_date TIMESTAMP;
ALTER TABLE users ADD COLUMN subscription_status VARCHAR(50) DEFAULT 'inactive';

-- Contact and Additional Info
ALTER TABLE users ADD COLUMN phone_number VARCHAR(20);
ALTER TABLE users ADD COLUMN linkedin_profile TEXT;
ALTER TABLE users ADD COLUMN years_of_experience INTEGER;
ALTER TABLE users ADD COLUMN preferred_job_types TEXT; -- JSON array as string
ALTER TABLE users ADD COLUMN preferred_locations TEXT; -- JSON array as string
ALTER TABLE users ADD COLUMN salary_expectation VARCHAR(100);
ALTER TABLE users ADD COLUMN languages_spoken TEXT; -- JSON array as string
ALTER TABLE users ADD COLUMN certifications TEXT; -- JSON array as string

-- Profile completion and verification
ALTER TABLE users ADD COLUMN profile_completed BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN profile_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN profile_completion_percentage INTEGER DEFAULT 0;

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_users_subscription_type ON users(subscription_type);
CREATE INDEX IF NOT EXISTS idx_users_subscription_status ON users(subscription_status);
CREATE INDEX IF NOT EXISTS idx_users_country_of_origin ON users(country_of_origin);
CREATE INDEX IF NOT EXISTS idx_users_current_location ON users(current_location);
CREATE INDEX IF NOT EXISTS idx_users_availability ON users(availability);
CREATE INDEX IF NOT EXISTS idx_users_visa_status ON users(visa_status);
CREATE INDEX IF NOT EXISTS idx_users_profile_completed ON users(profile_completed);
CREATE INDEX IF NOT EXISTS idx_users_years_experience ON users(years_of_experience); 