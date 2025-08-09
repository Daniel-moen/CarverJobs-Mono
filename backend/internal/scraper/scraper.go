package scraper

import (
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/models"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/services"
	"github.com/PuerkitoBio/goquery"
	"github.com/google/uuid"
)

type ScraperService struct {
	jobService *services.JobService
	client     *http.Client
}

type ScrapedJob struct {
	Title        string
	Company      string
	Location     string
	Type         string
	Vessel       string
	Duration     string
	Salary       string
	Description  string
	Requirements string
	URL          string
	PostedAt     time.Time
}

func NewScraperService(jobService *services.JobService) *ScraperService {
	return &ScraperService{
		jobService: jobService,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// ScrapeJobs orchestrates scraping from multiple sources
func (s *ScraperService) ScrapeJobs() error {
	log.Println("Starting job scraping...")

	// Example marine job sites (you can replace with actual sites)
	sources := []struct {
		name string
		url  string
	}{
		{"Maritime Jobs", "https://example-maritime-jobs.com"},
		{"Seaman Jobs", "https://example-seaman-jobs.com"},
		{"Offshore Jobs", "https://example-offshore-jobs.com"},
	}

	for _, source := range sources {
		log.Printf("Scraping from %s...", source.name)
		
		jobs, err := s.scrapeSource(source.name, source.url)
		if err != nil {
			log.Printf("Error scraping %s: %v", source.name, err)
			continue
		}

		for _, job := range jobs {
			if err := s.saveJob(job, source.name); err != nil {
				log.Printf("Error saving job: %v", err)
			}
		}

		log.Printf("Scraped %d jobs from %s", len(jobs), source.name)
		
		// Be respectful - add delay between requests
		time.Sleep(2 * time.Second)
	}

	log.Println("Job scraping completed")
	return nil
}

// scrapeSource scrapes jobs from a specific source
func (s *ScraperService) scrapeSource(sourceName, url string) ([]ScrapedJob, error) {
	resp, err := s.client.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch %s: %w", url, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("bad status code %d for %s", resp.StatusCode, url)
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to parse HTML: %w", err)
	}

	var jobs []ScrapedJob

	// Generic scraping logic - customize based on actual site structure
	doc.Find(".job-listing, .job-item, .job-card").Each(func(i int, sel *goquery.Selection) {
		job := ScrapedJob{
			Title:        strings.TrimSpace(sel.Find(".job-title, h2, h3").First().Text()),
			Company:      strings.TrimSpace(sel.Find(".company, .employer").First().Text()),
			Location:     strings.TrimSpace(sel.Find(".location, .job-location").First().Text()),
			Description:  strings.TrimSpace(sel.Find(".description, .job-description").First().Text()),
			PostedAt:     time.Now(), // Default to now if can't parse
		}

		// Extract job URL
		if link, exists := sel.Find("a").First().Attr("href"); exists {
			if strings.HasPrefix(link, "/") {
				job.URL = url + link
			} else {
				job.URL = link
			}
		}

		// Extract marine-specific details
		job.Type = s.extractJobType(job.Title, job.Description)
		job.Vessel = s.extractVesselType(job.Title, job.Description)
		job.Duration = s.extractDuration(job.Description)
		job.Salary = s.extractSalary(job.Description)

		// Only add if we have minimum required data
		if job.Title != "" && job.Company != "" {
			jobs = append(jobs, job)
		}
	})

	return jobs, nil
}

// saveJob converts scraped job to model and saves to database
func (s *ScraperService) saveJob(scrapedJob ScrapedJob, source string) error {
	job := &models.Job{
		ID:           uuid.New().String(),
		Title:        scrapedJob.Title,
		Company:      scrapedJob.Company,
		Location:     scrapedJob.Location,
		Type:         scrapedJob.Type,
		Vessel:       scrapedJob.Vessel,
		Duration:     scrapedJob.Duration,
		Salary:       scrapedJob.Salary,
		Description:  scrapedJob.Description,
		Requirements: scrapedJob.Requirements,
		SourceURL:    scrapedJob.URL,
		Source:       source,
		PostedAt:     scrapedJob.PostedAt,
		ScrapedAt:    time.Now(),
		CreatedAt:    time.Now(),
		UpdatedAt:    time.Now(),
	}

	return s.jobService.CreateJob(job)
}

// Helper functions to extract marine-specific information
func (s *ScraperService) extractJobType(title, description string) string {
	text := strings.ToLower(title + " " + description)
	
	types := map[string]string{
		"deck":      "deck",
		"officer":   "deck",
		"captain":   "deck",
		"mate":      "deck",
		"engineer":  "engine",
		"engine":    "engine",
		"motorman":  "engine",
		"cook":      "catering",
		"chef":      "catering",
		"steward":   "catering",
		"catering":  "catering",
		"fitter":    "engine",
		"welder":    "technical",
		"ab":        "deck",
		"oiler":     "engine",
	}

	for keyword, jobType := range types {
		if strings.Contains(text, keyword) {
			return jobType
		}
	}
	return "general"
}

func (s *ScraperService) extractVesselType(title, description string) string {
	text := strings.ToLower(title + " " + description)
	
	vessels := []string{
		"tanker", "container", "bulk", "cargo", "cruise", "ferry",
		"offshore", "supply", "tug", "barge", "yacht", "fishing",
	}

	for _, vessel := range vessels {
		if strings.Contains(text, vessel) {
			return vessel
		}
	}
	return ""
}

func (s *ScraperService) extractDuration(description string) string {
	text := strings.ToLower(description)
	
	durations := []string{
		"4 months", "6 months", "8 months", "permanent", "rotation",
		"4/4", "6/6", "8/4", "2/2", "3/3",
	}

	for _, duration := range durations {
		if strings.Contains(text, duration) {
			return duration
		}
	}
	return ""
}

func (s *ScraperService) extractSalary(description string) string {
	text := description
	
	// Look for common salary patterns
	salaryPatterns := []string{
		"USD", "$", "EUR", "€", "GBP", "£", "/month", "/day",
		"salary", "wage", "pay",
	}

	for _, pattern := range salaryPatterns {
		if strings.Contains(strings.ToLower(text), strings.ToLower(pattern)) {
			// Extract the sentence containing salary information
			sentences := strings.Split(text, ".")
			for _, sentence := range sentences {
				if strings.Contains(strings.ToLower(sentence), strings.ToLower(pattern)) {
					return strings.TrimSpace(sentence)
				}
			}
		}
	}
	return ""
} 