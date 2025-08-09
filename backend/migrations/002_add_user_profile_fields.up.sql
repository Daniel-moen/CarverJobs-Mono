-- Add user profile fields for job matching (PostgreSQL compatible)
-- Profile Information
ALTER TABLE users ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS gender VARCHAR(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS country_of_origin VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS current_location VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS availability VARCHAR(100);

-- Documents and Files
ALTER TABLE users ADD COLUMN IF NOT EXISTS cv_file_path TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_file_path TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reference_letters_file_path TEXT;

-- Visa and Work Authorization
ALTER TABLE users ADD COLUMN IF NOT EXISTS visa_status VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS work_authorization VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS passport_country VARCHAR(100);

-- Subscription Information
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_type VARCHAR(50) DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_start_date TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_end_date TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50) DEFAULT 'inactive';

-- Contact and Additional Info
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS linkedin_profile TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS years_of_experience INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_job_types TEXT; -- JSON array as string
ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_locations TEXT; -- JSON array as string
ALTER TABLE users ADD COLUMN IF NOT EXISTS salary_expectation VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS languages_spoken TEXT; -- JSON array as string
ALTER TABLE users ADD COLUMN IF NOT EXISTS certifications TEXT; -- JSON array as string

-- Profile completion and verification
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_completed BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_completion_percentage INTEGER DEFAULT 0;

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_users_subscription_type ON users(subscription_type);
CREATE INDEX IF NOT EXISTS idx_users_subscription_status ON users(subscription_status);
CREATE INDEX IF NOT EXISTS idx_users_country_of_origin ON users(country_of_origin);
CREATE INDEX IF NOT EXISTS idx_users_current_location ON users(current_location);
CREATE INDEX IF NOT EXISTS idx_users_availability ON users(availability);
CREATE INDEX IF NOT EXISTS idx_users_visa_status ON users(visa_status);
CREATE INDEX IF NOT EXISTS idx_users_profile_completed ON users(profile_completed);
CREATE INDEX IF NOT EXISTS idx_users_years_experience ON users(years_of_experience); 