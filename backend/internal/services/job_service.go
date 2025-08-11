package services

import (
	"database/sql"
	"fmt"
	"strings"

	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/database"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/models"
)

type JobService struct {
	db     *database.DB
	driver string
}

func NewJobService(db *database.DB) *JobService {
	// Get driver from the database instance
	driver := "sqlite3" // default fallback
	if db != nil {
		driver = db.GetDriver()
	}
	return &JobService{
		db:     db,
		driver: driver,
	}
}

// getPlaceholder returns the appropriate placeholder for the database driver
func (s *JobService) getPlaceholder(index int) string {
	if s.driver == "postgres" {
		return fmt.Sprintf("$%d", index)
	}
	return "?"
}

// buildWhereClause builds the WHERE clause with appropriate placeholders
func (s *JobService) buildWhereClause(filter models.JobFilter) (string, []interface{}) {
	whereClause := []string{}
	args := []interface{}{}
	argIndex := 1

	if filter.Type != "" {
		if s.driver == "postgres" {
			whereClause = append(whereClause, fmt.Sprintf("type ILIKE %s", s.getPlaceholder(argIndex)))
		} else {
			whereClause = append(whereClause, fmt.Sprintf("type LIKE %s", s.getPlaceholder(argIndex)))
		}
		args = append(args, "%"+filter.Type+"%")
		argIndex++
	}
	if filter.Location != "" {
		if s.driver == "postgres" {
			whereClause = append(whereClause, fmt.Sprintf("location ILIKE %s", s.getPlaceholder(argIndex)))
		} else {
			whereClause = append(whereClause, fmt.Sprintf("location LIKE %s", s.getPlaceholder(argIndex)))
		}
		args = append(args, "%"+filter.Location+"%")
		argIndex++
	}
	if filter.Company != "" {
		if s.driver == "postgres" {
			whereClause = append(whereClause, fmt.Sprintf("company ILIKE %s", s.getPlaceholder(argIndex)))
		} else {
			whereClause = append(whereClause, fmt.Sprintf("company LIKE %s", s.getPlaceholder(argIndex)))
		}
		args = append(args, "%"+filter.Company+"%")
		argIndex++
	}

	where := ""
	if len(whereClause) > 0 {
		where = "WHERE " + strings.Join(whereClause, " AND ")
	}

	return where, args
}

func (s *JobService) GetJobs(filter models.JobFilter) (*models.JobResponse, error) {
	// Set default pagination
	if filter.Limit <= 0 || filter.Limit > 100 {
		filter.Limit = 20
	}
	if filter.Offset < 0 {
		filter.Offset = 0
	}

	// Build WHERE clause
	where, args := s.buildWhereClause(filter)
	
	// Get total count
	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM jobs %s", where)
	var total int
	err := s.db.QueryRow(countQuery, args...).Scan(&total)
	if err != nil {
		return nil, fmt.Errorf("failed to get job count: %w", err)
	}

	// Build main query with proper placeholders
	limitPlaceholder := s.getPlaceholder(len(args) + 1)
	offsetPlaceholder := s.getPlaceholder(len(args) + 2)
	
	query := fmt.Sprintf(`
		SELECT id, title, company, location, type, vessel, duration, salary, 
		       description, requirements, source_url, source, posted_at, 
		       scraped_at, created_at, updated_at
		FROM jobs %s
		ORDER BY posted_at DESC, created_at DESC
		LIMIT %s OFFSET %s
	`, where, limitPlaceholder, offsetPlaceholder)

	args = append(args, filter.Limit, filter.Offset)
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to query jobs: %w", err)
	}
	defer rows.Close()

	var jobs []models.Job
	for rows.Next() {
		var job models.Job
		var title, company, location, jobType, vessel, duration, salary, description, requirements, sourceURL, source sql.NullString
		var postedAt, scrapedAt, createdAt, updatedAt sql.NullTime
		
		err := rows.Scan(
			&job.ID, &title, &company, &location, &jobType,
			&vessel, &duration, &salary, &description,
			&requirements, &sourceURL, &source, &postedAt,
			&scrapedAt, &createdAt, &updatedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan job: %w", err)
		}
		
		// Handle NULL values for all string fields
		if title.Valid {
			job.Title = title.String
		}
		if company.Valid {
			job.Company = company.String
		}
		if location.Valid {
			job.Location = location.String
		}
		if jobType.Valid {
			job.Type = jobType.String
		}
		if vessel.Valid {
			job.Vessel = vessel.String
		}
		if duration.Valid {
			job.Duration = duration.String
		}
		if salary.Valid {
			job.Salary = salary.String
		}
		if description.Valid {
			job.Description = description.String
		}
		if requirements.Valid {
			job.Requirements = requirements.String
		}
		if sourceURL.Valid {
			job.SourceURL = sourceURL.String
		}
		if source.Valid {
			job.Source = source.String
		}
		
		// Handle NULL values for time fields
		if postedAt.Valid {
			job.PostedAt = postedAt.Time
		}
		if scrapedAt.Valid {
			job.ScrapedAt = scrapedAt.Time
		}
		if createdAt.Valid {
			job.CreatedAt = createdAt.Time
		}
		if updatedAt.Valid {
			job.UpdatedAt = updatedAt.Time
		}
		
		jobs = append(jobs, job)
	}

	if err = rows.Err(); err != nil {
		return nil, fmt.Errorf("row iteration error: %w", err)
	}

	page := (filter.Offset / filter.Limit) + 1
	return &models.JobResponse{
		Jobs:  jobs,
		Total: total,
		Page:  page,
		Limit: filter.Limit,
	}, nil
}

func (s *JobService) CreateJob(job *models.Job) error {
	var query string
	var args []interface{}
	
	if s.driver == "postgres" {
		query = `
			INSERT INTO jobs (
				id, title, company, location, type, vessel, duration, salary,
				description, requirements, source_url, source, posted_at,
				scraped_at, created_at, updated_at
			) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
		`
	} else {
		query = `
			INSERT INTO jobs (
				id, title, company, location, type, vessel, duration, salary,
				description, requirements, source_url, source, posted_at,
				scraped_at, created_at, updated_at
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`
	}
	
	args = []interface{}{
		job.ID, job.Title, job.Company, job.Location, job.Type,
		job.Vessel, job.Duration, job.Salary, job.Description,
		job.Requirements, job.SourceURL, job.Source, job.PostedAt,
		job.ScrapedAt, job.CreatedAt, job.UpdatedAt,
	}
	
	_, err := s.db.Exec(query, args...)
	if err != nil {
		return fmt.Errorf("failed to create job: %w", err)
	}
	return nil
}

func (s *JobService) GetJobByID(jobID string) (*models.Job, error) {
	job := &models.Job{}
	var query string
	
	if s.driver == "postgres" {
		query = `
			SELECT id, title, company, location, type, vessel, duration, salary,
			       description, requirements, source_url, source, posted_at,
			       scraped_at, created_at, updated_at
			FROM jobs WHERE id = $1
		`
	} else {
		query = `
			SELECT id, title, company, location, type, vessel, duration, salary,
			       description, requirements, source_url, source, posted_at,
			       scraped_at, created_at, updated_at
			FROM jobs WHERE id = ?
		`
	}
	
	var vessel, duration, salary, description, requirements, sourceURL, source sql.NullString
	var postedAt, scrapedAt, createdAt, updatedAt sql.NullTime
	
	err := s.db.QueryRow(query, jobID).Scan(
		&job.ID, &job.Title, &job.Company, &job.Location, &job.Type,
		&vessel, &duration, &salary, &description,
		&requirements, &sourceURL, &source, &postedAt,
		&scrapedAt, &createdAt, &updatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("failed to get job: %w", err)
	}
	
	// Handle NULL values
	if vessel.Valid {
		job.Vessel = vessel.String
	}
	if duration.Valid {
		job.Duration = duration.String
	}
	if salary.Valid {
		job.Salary = salary.String
	}
	if description.Valid {
		job.Description = description.String
	}
	if requirements.Valid {
		job.Requirements = requirements.String
	}
	if sourceURL.Valid {
		job.SourceURL = sourceURL.String
	}
	if source.Valid {
		job.Source = source.String
	}
	
	// Handle NULL values for time fields
	if postedAt.Valid {
		job.PostedAt = postedAt.Time
	}
	if scrapedAt.Valid {
		job.ScrapedAt = scrapedAt.Time
	}
	if createdAt.Valid {
		job.CreatedAt = createdAt.Time
	}
	if updatedAt.Valid {
		job.UpdatedAt = updatedAt.Time
	}
	
	return job, nil
} 