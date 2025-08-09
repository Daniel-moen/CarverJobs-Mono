package handlers

import (
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
	var filter models.JobFilter

	// Parse query parameters
	filter.Type = c.QueryParam("type")
	filter.Location = c.QueryParam("location")
	filter.Company = c.QueryParam("company")

	// Parse pagination
	if limitStr := c.QueryParam("limit"); limitStr != "" {
		if limit, err := strconv.Atoi(limitStr); err == nil {
			filter.Limit = limit
		}
	}

	if offsetStr := c.QueryParam("offset"); offsetStr != "" {
		if offset, err := strconv.Atoi(offsetStr); err == nil {
			filter.Offset = offset
		}
	}

	response, err := h.jobService.GetJobs(filter)
	if err != nil {
		return echo.NewHTTPError(http.StatusInternalServerError, "failed to get jobs")
	}

	return c.JSON(http.StatusOK, response)
}

// GetJobByID handles getting a specific job by ID
func (h *JobHandler) GetJobByID(c echo.Context) error {
	jobID := c.Param("id")
	if jobID == "" {
		return echo.NewHTTPError(http.StatusBadRequest, "job ID is required")
	}

	job, err := h.jobService.GetJobByID(jobID)
	if err != nil {
		return echo.NewHTTPError(http.StatusNotFound, "job not found")
	}

	return c.JSON(http.StatusOK, job)
}

// CreateJob handles job creation (typically used by scrapers)
func (h *JobHandler) CreateJob(c echo.Context) error {
	var job models.Job
	if err := c.Bind(&job); err != nil {
		return echo.NewHTTPError(http.StatusBadRequest, "invalid request body")
	}

	// Basic validation
	if job.Title == "" || job.Company == "" || job.Source == "" {
		return echo.NewHTTPError(http.StatusBadRequest, "title, company, and source are required")
	}

	if err := h.jobService.CreateJob(&job); err != nil {
		return echo.NewHTTPError(http.StatusInternalServerError, "failed to create job")
	}

	return c.JSON(http.StatusCreated, map[string]interface{}{
		"message": "job created successfully",
		"job":     job,
	})
} 