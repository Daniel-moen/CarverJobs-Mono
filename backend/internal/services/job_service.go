package services

import (
	"fmt"
	"strings"

	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/database"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/models"
)

type JobService struct {
	db *database.DB
}

func NewJobService(db *database.DB) *JobService {
	return &JobService{db: db}
}

func (s *JobService) GetJobs(filter models.JobFilter) (*models.JobResponse, error) {
	// Build dynamic query
	whereClause := []string{}
	args := []interface{}{}

	if filter.Type != "" {
		whereClause = append(whereClause, "type LIKE ?")
		args = append(args, "%"+filter.Type+"%")
	}
	if filter.Location != "" {
		whereClause = append(whereClause, "location LIKE ?")
		args = append(args, "%"+filter.Location+"%")
	}
	if filter.Company != "" {
		whereClause = append(whereClause, "company LIKE ?")
		args = append(args, "%"+filter.Company+"%")
	}

	where := ""
	if len(whereClause) > 0 {
		where = "WHERE " + strings.Join(whereClause, " AND ")
	}

	// Set default pagination
	if filter.Limit <= 0 || filter.Limit > 100 {
		filter.Limit = 20
	}
	if filter.Offset < 0 {
		filter.Offset = 0
	}

	// Get total count
	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM jobs %s", where)
	var total int
	err := s.db.QueryRow(countQuery, args...).Scan(&total)
	if err != nil {
		return nil, fmt.Errorf("failed to get job count: %w", err)
	}

	// Get jobs
	query := fmt.Sprintf(`
		SELECT id, title, company, location, type, vessel, duration, salary, 
		       description, requirements, source_url, source, posted_at, 
		       scraped_at, created_at, updated_at
		FROM jobs %s
		ORDER BY posted_at DESC, created_at DESC
		LIMIT ? OFFSET ?
	`, where)

	args = append(args, filter.Limit, filter.Offset)
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to query jobs: %w", err)
	}
	defer rows.Close()

	var jobs []models.Job
	for rows.Next() {
		var job models.Job
		err := rows.Scan(
			&job.ID, &job.Title, &job.Company, &job.Location, &job.Type,
			&job.Vessel, &job.Duration, &job.Salary, &job.Description,
			&job.Requirements, &job.SourceURL, &job.Source, &job.PostedAt,
			&job.ScrapedAt, &job.CreatedAt, &job.UpdatedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan job: %w", err)
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
	query := `
		INSERT INTO jobs (
			id, title, company, location, type, vessel, duration, salary,
			description, requirements, source_url, source, posted_at,
			scraped_at, created_at, updated_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`
	_, err := s.db.Exec(
		query, job.ID, job.Title, job.Company, job.Location, job.Type,
		job.Vessel, job.Duration, job.Salary, job.Description,
		job.Requirements, job.SourceURL, job.Source, job.PostedAt,
		job.ScrapedAt, job.CreatedAt, job.UpdatedAt,
	)
	if err != nil {
		return fmt.Errorf("failed to create job: %w", err)
	}
	return nil
}

func (s *JobService) GetJobByID(jobID string) (*models.Job, error) {
	job := &models.Job{}
	query := `
		SELECT id, title, company, location, type, vessel, duration, salary,
		       description, requirements, source_url, source, posted_at,
		       scraped_at, created_at, updated_at
		FROM jobs WHERE id = ?
	`
	err := s.db.QueryRow(query, jobID).Scan(
		&job.ID, &job.Title, &job.Company, &job.Location, &job.Type,
		&job.Vessel, &job.Duration, &job.Salary, &job.Description,
		&job.Requirements, &job.SourceURL, &job.Source, &job.PostedAt,
		&job.ScrapedAt, &job.CreatedAt, &job.UpdatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("failed to get job: %w", err)
	}
	return job, nil
} 