-- Revert jobs table schema changes

-- Revert column renames
ALTER TABLE jobs RENAME COLUMN type TO job_type;
ALTER TABLE jobs RENAME COLUMN vessel TO vessel_type;

-- Remove added columns
ALTER TABLE jobs DROP COLUMN source_url;
ALTER TABLE jobs DROP COLUMN source;
ALTER TABLE jobs DROP COLUMN posted_at;
ALTER TABLE jobs DROP COLUMN scraped_at;

-- Drop indexes
DROP INDEX IF EXISTS idx_jobs_source;
DROP INDEX IF EXISTS idx_jobs_posted_at;
DROP INDEX IF EXISTS idx_jobs_scraped_at; 