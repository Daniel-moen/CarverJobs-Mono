package scraper

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/models"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/services"
	"github.com/google/uuid"
)

type YachtScraperService struct {
	jobService *services.JobService
	client     *http.Client
	apifyKey   string
}

type ApifyRunRequest struct {
	StartUrls    []map[string]string `json:"startUrls,omitempty"`
	Channels     []string            `json:"channels,omitempty"`
	MaxPosts     int                 `json:"maxPosts"`
	MaxPostDate  string              `json:"maxPostDate,omitempty"`
	MaxComments  int                 `json:"maxComments,omitempty"`
	PostsFrom    int                 `json:"postsFrom,omitempty"`
	PostsTo      int                 `json:"postsTo,omitempty"`
	Timeout      int                 `json:"timeout,omitempty"`
}

type ApifyRunResponse struct {
	Data struct {
		ID string `json:"id"`
	} `json:"data"`
}

type ApifyStatusResponse struct {
	Data struct {
		Status string `json:"status"`
	} `json:"data"`
}

type ScrapedPost struct {
	Text        string    `json:"text"`
	URL         string    `json:"url"`
	Timestamp   time.Time `json:"timestamp"`
	Source      string    `json:"source"`
	GroupName   string    `json:"groupName,omitempty"`
	ChannelName string    `json:"channelName,omitempty"`
}

// Top yacht job sources - compressed from original 100+ to most effective 20
var (
	facebookGroups = []string{
		"https://www.facebook.com/groups/239411889867327/",  // Yacht Crew Jobs
		"https://www.facebook.com/groups/338532096967628/",  // Yacht Crew Jobs International
		"https://www.facebook.com/groups/2258415597510901/", // Yacht Crew Jobs Worldwide
		"https://www.facebook.com/groups/1281653486137390/", // Yacht Crew Jobs Mediterranean
		"https://www.facebook.com/groups/crewhq/",           // Crew HQ
		"https://www.facebook.com/groups/252411372371043/",  // Yacht Crew Jobs Europe
		"https://www.facebook.com/groups/1506610199573250/", // Yacht Crew Jobs Caribbean
		"https://www.facebook.com/groups/147250563939706/",  // Seazone Yacht Crew & Jobs
		"https://www.facebook.com/groups/983255258859510/",  // Junior Yacht Crew
		"https://www.facebook.com/groups/396758057344877/",  // Yacht Stew Jobs
	}

	telegramChannels = []string{
		"cvcrewcom",            // CV-CREW Maritime Jobs (25k+ members)
		"yachtjobs",            // Yacht Jobs
		"superyachtjobs",       // Superyacht Jobs
		"megayachtjobs",        // Mega Yacht Jobs
		"motoryachtjobs",       // Motor Yacht Jobs
		"yachtcrewnetwork",     // Yacht Crew Network
		"superyachtcrew",       // Superyacht Crew Network
		"yachtingprofessionals", // Yachting Professionals
		"marinepedia",          // Marinepedia Jobs (5.7k+ members)
		"abroadjbs",            // Abroad Jobs (22k+ members)
	}
)

func NewYachtScraperService(jobService *services.JobService) *YachtScraperService {
	apifyKey := os.Getenv("APIFY_API_KEY")
	if apifyKey == "" {
		log.Println("Warning: APIFY_API_KEY not set, yacht scraper will be disabled")
	}

	return &YachtScraperService{
		jobService: jobService,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
		apifyKey: apifyKey,
	}
}

// ScrapeYachtJobs scrapes yacht jobs from Facebook and Telegram
func (s *YachtScraperService) ScrapeYachtJobs() error {
	if s.apifyKey == "" {
		log.Println("Skipping yacht scraping - no APIFY_API_KEY provided")
		return nil
	}

	log.Println("🚀 Starting Yacht Job Scraper System")
	log.Println("====================================================")

	// Scrape Facebook groups
	facebookPosts, err := s.scrapeFacebookGroups()
	if err != nil {
		log.Printf("❌ Facebook scraping failed: %v", err)
		facebookPosts = []ScrapedPost{}
	}

	// Scrape Telegram channels
	telegramPosts, err := s.scrapeTelegramChannels()
	if err != nil {
		log.Printf("❌ Telegram scraping failed: %v", err)
		telegramPosts = []ScrapedPost{}
	}

	allPosts := append(facebookPosts, telegramPosts...)
	log.Printf("📊 Total posts scraped: %d", len(allPosts))

	if len(allPosts) == 0 {
		log.Println("❌ No posts found to process")
		return nil
	}

	// Process posts and extract jobs (simplified without OpenAI)
	jobs := s.extractJobsFromPosts(allPosts)
	log.Printf("💼 Jobs extracted: %d", len(jobs))

	// Save jobs to database
	saved := 0
	for _, job := range jobs {
		if err := s.jobService.CreateJob(job); err != nil {
			log.Printf("Error saving job: %v", err)
		} else {
			saved++
		}
	}

	log.Printf("💾 Jobs saved: %d/%d", saved, len(jobs))
	log.Println("🎉 Yacht scraping completed")
	return nil
}

func (s *YachtScraperService) scrapeFacebookGroups() ([]ScrapedPost, error) {
	log.Println("🌐 Starting Facebook scraping...")

	runID, err := s.startFacebookActor()
	if err != nil {
		return nil, err
	}

	if err := s.waitForCompletion(runID, 10*time.Minute); err != nil {
		return nil, err
	}

	posts, err := s.getRunResults(runID)
	if err != nil {
		return nil, err
	}

	log.Printf("✅ Retrieved %d Facebook posts", len(posts))
	return posts, nil
}

func (s *YachtScraperService) scrapeTelegramChannels() ([]ScrapedPost, error) {
	log.Println("📱 Starting Telegram scraping...")

	runID, err := s.startTelegramActor()
	if err != nil {
		return nil, err
	}

	if err := s.waitForCompletion(runID, 15*time.Minute); err != nil {
		return nil, err
	}

	posts, err := s.getRunResults(runID)
	if err != nil {
		return nil, err
	}

	log.Printf("✅ Retrieved %d Telegram messages", len(posts))
	return posts, nil
}

func (s *YachtScraperService) startFacebookActor() (string, error) {
	url := "https://api.apify.com/v2/acts/apify~facebook-groups-scraper/runs"

	startUrls := make([]map[string]string, len(facebookGroups))
	for i, group := range facebookGroups {
		startUrls[i] = map[string]string{"url": group}
	}

	payload := ApifyRunRequest{
		StartUrls:   startUrls,
		MaxPosts:    20,
		MaxPostDate: time.Now().Format("2006-01-02"),
		MaxComments: 0,
	}

	return s.runApifyActor(url, payload)
}

func (s *YachtScraperService) startTelegramActor() (string, error) {
	url := "https://api.apify.com/v2/acts/cYGAiWbhiASIZSZb5/runs"

	payload := ApifyRunRequest{
		Channels:  telegramChannels,
		PostsFrom: 1,
		PostsTo:   20,
		MaxPosts:  20,
		Timeout:   900, // 15 minutes
	}

	return s.runApifyActor(url, payload)
}

func (s *YachtScraperService) runApifyActor(url string, payload ApifyRunRequest) (string, error) {
	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(payloadBytes))
	if err != nil {
		return "", err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+s.apifyKey)

	resp, err := s.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 201 {
		return "", fmt.Errorf("failed to start actor: HTTP %d", resp.StatusCode)
	}

	var response ApifyRunResponse
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return "", err
	}

	return response.Data.ID, nil
}

func (s *YachtScraperService) waitForCompletion(runID string, timeout time.Duration) error {
	start := time.Now()
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			status, err := s.getRunStatus(runID)
			if err != nil {
				return err
			}

			switch status {
			case "SUCCEEDED":
				return nil
			case "FAILED", "ABORTED", "TIMED-OUT":
				return fmt.Errorf("actor run %s: %s", runID, status)
			}

			if time.Since(start) > timeout {
				return fmt.Errorf("timeout waiting for actor completion")
			}
		}
	}
}

func (s *YachtScraperService) getRunStatus(runID string) (string, error) {
	url := fmt.Sprintf("https://api.apify.com/v2/actor-runs/%s", runID)

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return "", err
	}

	req.Header.Set("Authorization", "Bearer "+s.apifyKey)

	resp, err := s.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	var response ApifyStatusResponse
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return "", err
	}

	return response.Data.Status, nil
}

func (s *YachtScraperService) getRunResults(runID string) ([]ScrapedPost, error) {
	url := fmt.Sprintf("https://api.apify.com/v2/actor-runs/%s/dataset/items", runID)

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}

	req.Header.Set("Authorization", "Bearer "+s.apifyKey)

	resp, err := s.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var posts []ScrapedPost
	if err := json.NewDecoder(resp.Body).Decode(&posts); err != nil {
		return nil, err
	}

	return posts, nil
}

// extractJobsFromPosts - simplified job extraction without OpenAI
func (s *YachtScraperService) extractJobsFromPosts(posts []ScrapedPost) []*models.Job {
	var jobs []*models.Job

	for _, post := range posts {
		if s.isJobPost(post.Text) {
			job := s.convertPostToJob(post)
			if job != nil {
				jobs = append(jobs, job)
			}
		}
	}

	return jobs
}

// isJobPost - simplified job detection using keywords
func (s *YachtScraperService) isJobPost(text string) bool {
	text = strings.ToLower(text)

	// Job indicators
	jobKeywords := []string{
		"hiring", "job", "position", "crew", "vacancy", "looking for",
		"seeking", "needed", "required", "opportunity", "application",
		"captain", "engineer", "stewardess", "chef", "deckhand",
		"bosun", "officer", "stew", "cook", "mate",
	}

	// Yacht/marine indicators
	yachtKeywords := []string{
		"yacht", "superyacht", "motor yacht", "sailing yacht",
		"vessel", "boat", "ship", "charter", "private",
	}

	hasJobKeyword := false
	hasYachtKeyword := false

	for _, keyword := range jobKeywords {
		if strings.Contains(text, keyword) {
			hasJobKeyword = true
			break
		}
	}

	for _, keyword := range yachtKeywords {
		if strings.Contains(text, keyword) {
			hasYachtKeyword = true
			break
		}
	}

	return hasJobKeyword && hasYachtKeyword
}

// convertPostToJob - convert scraped post to job model
func (s *YachtScraperService) convertPostToJob(post ScrapedPost) *models.Job {
	title := s.extractJobTitle(post.Text)
	if title == "" {
		title = "Yacht Crew Position"
	}

	company := s.extractCompany(post.Text)
	if company == "" {
		company = "Private Yacht"
	}

	return &models.Job{
		ID:          uuid.New().String(),
		Title:       title,
		Company:     company,
		Location:    s.extractLocation(post.Text),
		Type:        s.extractJobType(post.Text),
		Vessel:      s.extractVesselType(post.Text),
		Duration:    s.extractDuration(post.Text),
		Salary:      s.extractSalary(post.Text),
		Description: s.cleanText(post.Text),
		SourceURL:   post.URL,
		Source:      "Yacht Scraper",
		PostedAt:    post.Timestamp,
		ScrapedAt:   time.Now(),
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
	}
}

// Helper functions for data extraction
func (s *YachtScraperService) extractJobTitle(text string) string {
	text = strings.ToLower(text)
	
	titles := map[string]string{
		"captain":     "Captain",
		"chief officer": "Chief Officer",
		"first officer": "First Officer",
		"second officer": "Second Officer",
		"bosun":       "Bosun",
		"deckhand":    "Deckhand",
		"able seaman": "Able Seaman",
		"chief engineer": "Chief Engineer",
		"first engineer": "First Engineer",
		"second engineer": "Second Engineer",
		"engineer":    "Engineer",
		"chief stewardess": "Chief Stewardess",
		"chief stew":  "Chief Stewardess",
		"stewardess":  "Stewardess",
		"stew":        "Stewardess",
		"chef":        "Chef",
		"cook":        "Cook",
		"purser":      "Purser",
	}

	for keyword, title := range titles {
		if strings.Contains(text, keyword) {
			return title
		}
	}
	return ""
}

func (s *YachtScraperService) extractCompany(text string) string {
	// Look for company indicators
	if strings.Contains(strings.ToLower(text), "m/y ") {
		return "Motor Yacht"
	}
	if strings.Contains(strings.ToLower(text), "s/y ") {
		return "Sailing Yacht"
	}
	return ""
}

func (s *YachtScraperService) extractLocation(text string) string {
	text = strings.ToLower(text)
	
	locations := []string{
		"mediterranean", "caribbean", "bahamas", "florida", "french riviera",
		"monaco", "antibes", "palma", "barcelona", "genoa", "miami",
		"fort lauderdale", "newport", "sardinia", "corsica", "ibiza",
		"worldwide", "global", "anywhere",
	}

	for _, location := range locations {
		if strings.Contains(text, location) {
			return strings.Title(location)
		}
	}
	return ""
}

func (s *YachtScraperService) extractJobType(text string) string {
	text = strings.ToLower(text)
	
	if strings.Contains(text, "captain") || strings.Contains(text, "officer") || 
	   strings.Contains(text, "bosun") || strings.Contains(text, "deckhand") {
		return "deck"
	}
	if strings.Contains(text, "engineer") || strings.Contains(text, "eto") {
		return "engine"
	}
	if strings.Contains(text, "stewardess") || strings.Contains(text, "stew") || 
	   strings.Contains(text, "chef") || strings.Contains(text, "cook") {
		return "interior"
	}
	return "crew"
}

func (s *YachtScraperService) extractVesselType(text string) string {
	text = strings.ToLower(text)
	
	if strings.Contains(text, "motor yacht") || strings.Contains(text, "m/y") {
		return "motor yacht"
	}
	if strings.Contains(text, "sailing yacht") || strings.Contains(text, "s/y") {
		return "sailing yacht"
	}
	if strings.Contains(text, "superyacht") {
		return "superyacht"
	}
	if strings.Contains(text, "catamaran") {
		return "catamaran"
	}
	return "yacht"
}

func (s *YachtScraperService) extractDuration(text string) string {
	text = strings.ToLower(text)
	
	durations := []string{
		"permanent", "rotational", "seasonal", "summer season",
		"winter season", "4/4", "6/6", "8/4", "2/2", "3/3",
		"6 months", "4 months", "8 months",
	}

	for _, duration := range durations {
		if strings.Contains(text, duration) {
			return duration
		}
	}
	return ""
}

func (s *YachtScraperService) extractSalary(text string) string {
	// Look for salary patterns
	if strings.Contains(text, "€") || strings.Contains(text, "$") || 
	   strings.Contains(text, "salary") || strings.Contains(text, "wage") {
		// Simple extraction - could be improved with regex
		lines := strings.Split(text, "\n")
		for _, line := range lines {
			line = strings.ToLower(line)
			if strings.Contains(line, "€") || strings.Contains(line, "$") ||
			   strings.Contains(line, "salary") || strings.Contains(line, "wage") {
				return strings.TrimSpace(line)
			}
		}
	}
	return ""
}

func (s *YachtScraperService) cleanText(text string) string {
	// Basic text cleaning
	text = strings.TrimSpace(text)
	if len(text) > 1000 {
		text = text[:1000] + "..."
	}
	return text
} 