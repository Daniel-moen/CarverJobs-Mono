package handlers

import (
	"database/sql"
	"log"
	"net/http"
	"strconv"

	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/models"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/services"
	"github.com/labstack/echo/v4"
)

type JobHandler struct {
	jobService *services.JobService
}

func NewJobHandler(jobService *services.JobService) *JobHandler {
	return &JobHandler{
		jobService: jobService,
	}
}

// GetJobs handles job listing with filtering and pagination
func (h *JobHandler) GetJobs(c echo.Context) error {
	log.Printf("GetJobs endpoint called with query params: %v", c.QueryParams())
	
	var filter models.JobFilter

	// Parse query parameters
	filter.Type = c.QueryParam("type")
	filter.Location = c.QueryParam("location")
	filter.Company = c.QueryParam("company")

	// Parse pagination
	if limitStr := c.QueryParam("limit"); limitStr != "" {
		if limit, err := strconv.Atoi(limitStr); err == nil {
			filter.Limit = limit
		} else {
			log.Printf("Invalid limit parameter: %s", limitStr)
		}
	}

	if offsetStr := c.QueryParam("offset"); offsetStr != "" {
		if offset, err := strconv.Atoi(offsetStr); err == nil {
			filter.Offset = offset
		} else {
			log.Printf("Invalid offset parameter: %s", offsetStr)
		}
	}

	log.Printf("Parsed filter: %+v", filter)

	response, err := h.jobService.GetJobs(filter)
	if err != nil {
		log.Printf("Error getting jobs: %v", err)
		// Check if it's a database connection error
		if err.Error() == "sql: database is closed" {
			return echo.NewHTTPError(http.StatusServiceUnavailable, "Database connection is not available")
		}
		return echo.NewHTTPError(http.StatusInternalServerError, map[string]interface{}{
			"message": "Failed to retrieve jobs",
			"error":   err.Error(),
		})
	}

	log.Printf("Returning %d jobs", len(response.Jobs))
	return c.JSON(http.StatusOK, response)
}

// GetJobByID handles getting a specific job by ID
func (h *JobHandler) GetJobByID(c echo.Context) error {
	jobID := c.Param("id")
	if jobID == "" {
		return echo.NewHTTPError(http.StatusBadRequest, "job ID is required")
	}

	log.Printf("GetJobByID called for ID: %s", jobID)

	job, err := h.jobService.GetJobByID(jobID)
	if err != nil {
		log.Printf("Error getting job by ID %s: %v", jobID, err)
		if err == sql.ErrNoRows {
			return echo.NewHTTPError(http.StatusNotFound, "job not found")
		}
		return echo.NewHTTPError(http.StatusInternalServerError, map[string]interface{}{
			"message": "Failed to retrieve job",
			"error":   err.Error(),
		})
	}

	return c.JSON(http.StatusOK, job)
}

// CreateJob handles job creation (typically used by scrapers)
func (h *JobHandler) CreateJob(c echo.Context) error {
	log.Printf("CreateJob endpoint called")
	
	var job models.Job
	if err := c.Bind(&job); err != nil {
		log.Printf("Error binding job data: %v", err)
		return echo.NewHTTPError(http.StatusBadRequest, "invalid request body")
	}

	// Basic validation
	if job.Title == "" || job.Company == "" || job.Source == "" {
		return echo.NewHTTPError(http.StatusBadRequest, "title, company, and source are required")
	}

	log.Printf("Creating job: %s at %s", job.Title, job.Company)

	if err := h.jobService.CreateJob(&job); err != nil {
		log.Printf("Error creating job: %v", err)
		return echo.NewHTTPError(http.StatusInternalServerError, map[string]interface{}{
			"message": "Failed to create job",
			"error":   err.Error(),
		})
	}

	log.Printf("Successfully created job with ID: %s", job.ID)
	return c.JSON(http.StatusCreated, map[string]interface{}{
		"message": "job created successfully",
		"job":     job,
	})
} 