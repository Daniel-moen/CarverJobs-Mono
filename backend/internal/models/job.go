package models

import "time"

type Job struct {
	ID          string    `json:"id" db:"id"`
	Title       string    `json:"title" db:"title"`
	Company     string    `json:"company" db:"company"`
	Location    string    `json:"location" db:"location"`
	Type        string    `json:"type" db:"type"` // e.g., "deck", "engine", "catering"
	Vessel      string    `json:"vessel" db:"vessel"`
	Duration    string    `json:"duration" db:"duration"`
	Salary      string    `json:"salary" db:"salary"`
	Description string    `json:"description" db:"description"`
	Requirements string   `json:"requirements" db:"requirements"`
	SourceURL   string    `json:"source_url" db:"source_url"`
	Source      string    `json:"source" db:"source"` // Which site it was scraped from
	PostedAt    time.Time `json:"posted_at" db:"posted_at"`
	ScrapedAt   time.Time `json:"scraped_at" db:"scraped_at"`
	CreatedAt   time.Time `json:"created_at" db:"created_at"`
	UpdatedAt   time.Time `json:"updated_at" db:"updated_at"`
}

type JobFilter struct {
	Type     string `query:"type"`
	Location string `query:"location"`
	Company  string `query:"company"`
	Limit    int    `query:"limit"`
	Offset   int    `query:"offset"`
}

type JobResponse struct {
	Jobs  []Job `json:"jobs"`
	Total int   `json:"total"`
	Page  int   `json:"page"`
	Limit int   `json:"limit"`
} 