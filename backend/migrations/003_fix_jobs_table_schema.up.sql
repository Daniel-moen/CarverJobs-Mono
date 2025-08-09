-- Fix jobs table schema to match Go models
-- This migration aligns the database schema with the models.Job struct

-- First, let's rename columns to match Go struct db tags
ALTER TABLE jobs RENAME COLUMN job_type TO type;
ALTER TABLE jobs RENAME COLUMN vessel_type TO vessel;

-- Add missing columns that the scraper and models expect
ALTER TABLE jobs ADD COLUMN source_url TEXT;
ALTER TABLE jobs ADD COLUMN source TEXT;
ALTER TABLE jobs ADD COLUMN posted_at TIMESTAMP;
ALTER TABLE jobs ADD COLUMN scraped_at TIMESTAMP;

-- Create indexes for better query performance on new columns
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at DESC); 