package database

import (
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"strings"

	_ "github.com/lib/pq"
	_ "github.com/mattn/go-sqlite3"
)

type Config struct {
	DatabaseURL string
	Driver      string
}

type DB struct {
	*sql.DB
	driver string
}

func NewConfig() Config {
	// Check if DATABASE_PUBLIC_URL is set (Railway's public database URL)
	databaseURL := os.Getenv("DATABASE_PUBLIC_URL")
	if databaseURL == "" {
		// Fallback to DATABASE_URL for backwards compatibility
		databaseURL = os.Getenv("DATABASE_URL")
	}
	driver := os.Getenv("DB_DRIVER")

	// Default to SQLite if no DATABASE_URL is provided
	if databaseURL == "" {
		// Ensure data directory exists for SQLite
		if err := os.MkdirAll("data", 0755); err != nil {
			panic(fmt.Sprintf("Failed to create data directory: %v", err))
		}
		
		databasePath := os.Getenv("DATABASE_PATH")
		if databasePath == "" {
			databasePath = "data/carverjobs.db"
		}
		
		return Config{
			DatabaseURL: databasePath,
			Driver:      "sqlite3",
		}
	}

	// Parse and validate PostgreSQL URL
	if strings.HasPrefix(databaseURL, "postgres://") || strings.HasPrefix(databaseURL, "postgresql://") {
		// Parse and reconstruct URL to ensure it's in the correct format
		parsedURL, err := url.Parse(databaseURL)
		if err != nil {
			panic(fmt.Sprintf("Invalid database URL format: %v", err))
		}
		
		// Ensure we have all required components
		if parsedURL.Host == "" {
			panic("Database URL missing host")
		}
		if parsedURL.User == nil {
			panic("Database URL missing user credentials")
		}
		
		// Reconstruct URL to ensure proper format for pq driver
		reconstructedURL := fmt.Sprintf("postgres://%s@%s%s?%s",
			parsedURL.User.String(),
			parsedURL.Host,
			parsedURL.Path,
			parsedURL.RawQuery,
		)
		
		return Config{
			DatabaseURL: reconstructedURL,
			Driver:      "postgres",
		}
	}

	// Use PostgreSQL as default for non-postgres URLs
	if driver == "" {
		driver = "postgres"
	}

	return Config{
		DatabaseURL: databaseURL,
		Driver:      driver,
	}
}

func NewDB(config Config) (*DB, error) {
	// Add debug logging for connection issues
	fmt.Printf("Attempting to connect to database with driver: %s\n", config.Driver)
	if config.Driver == "postgres" {
		// Don't log the full URL for security, just the host part
		if parsedURL, err := url.Parse(config.DatabaseURL); err == nil {
			fmt.Printf("Connecting to PostgreSQL host: %s\n", parsedURL.Host)
		}
	}
	
	db, err := sql.Open(config.Driver, config.DatabaseURL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to database: %w", err)
	}

	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	// Enable foreign keys for SQLite
	if config.Driver == "sqlite3" {
		if _, err := db.Exec("PRAGMA foreign_keys = ON;"); err != nil {
			return nil, fmt.Errorf("failed to enable foreign keys: %w", err)
		}
	}

	fmt.Printf("Successfully connected to %s database\n", config.Driver)
	return &DB{
		DB:     db,
		driver: config.Driver,
	}, nil
}

// GetDriver returns the database driver type
func (db *DB) GetDriver() string {
	return db.driver
}

// Close closes the database connection
func (db *DB) Close() error {
	return db.DB.Close()
} 