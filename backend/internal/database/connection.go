package database

import (
	"context"
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

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
	// Railway provides multiple database URL formats
	// Priority order: DATABASE_PUBLIC_URL > DATABASE_URL > DATABASE_PRIVATE_URL
	databaseURL := os.Getenv("DATABASE_PUBLIC_URL")
	if databaseURL == "" {
		databaseURL = os.Getenv("DATABASE_URL")
	}
	if databaseURL == "" {
		databaseURL = os.Getenv("DATABASE_PRIVATE_URL")
	}
	
	driver := os.Getenv("DB_DRIVER")

	// Default to SQLite if no DATABASE_URL is provided
	if databaseURL == "" {
		fmt.Println("No database URL found, defaulting to SQLite")
		
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
		// Parse URL to validate and potentially fix format
		parsedURL, err := url.Parse(databaseURL)
		if err != nil {
			panic(fmt.Sprintf("Invalid database URL format: %v", err))
		}
		
		// Validate required components
		if parsedURL.Host == "" {
			panic("Database URL missing host")
		}
		if parsedURL.User == nil {
			panic("Database URL missing user credentials")
		}
		
		// Add SSL mode if not present (Railway requires SSL)
		query := parsedURL.Query()
		if query.Get("sslmode") == "" {
			// Railway typically requires SSL
			query.Set("sslmode", "require")
			parsedURL.RawQuery = query.Encode()
		}
		
		// Add connection timeout if not present
		if query.Get("connect_timeout") == "" {
			query.Set("connect_timeout", "10")
			parsedURL.RawQuery = query.Encode()
		}
		
		// Reconstruct URL with improvements
		reconstructedURL := parsedURL.String()
		
		// Log connection details (without password)
		safeURL := *parsedURL
		if safeURL.User != nil {
			safeURL.User = url.User(safeURL.User.Username())
		}
		fmt.Printf("Connecting to PostgreSQL: %s\n", safeURL.String())
		
		return Config{
			DatabaseURL: reconstructedURL,
			Driver:      "postgres",
		}
	}

	// Handle other database URLs
	if driver == "" {
		driver = "postgres"
	}

	return Config{
		DatabaseURL: databaseURL,
		Driver:      driver,
	}
}

func NewDB(config Config) (*DB, error) {
	fmt.Printf("Initializing database connection (driver: %s)\n", config.Driver)
	
	// Open database connection
	db, err := sql.Open(config.Driver, config.DatabaseURL)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Configure connection pool for better performance
	// These settings help with Railway's connection limits
	db.SetMaxOpenConns(25)              // Maximum number of open connections
	db.SetMaxIdleConns(5)                // Maximum number of idle connections
	db.SetConnMaxLifetime(5 * time.Minute) // Maximum lifetime of a connection
	db.SetConnMaxIdleTime(1 * time.Minute) // Maximum idle time before closing
	
	// Test connection with retries (helpful for cold starts)
	var pingErr error
	maxRetries := 5
	for i := 0; i < maxRetries; i++ {
		pingErr = db.Ping()
		if pingErr == nil {
			break
		}
		
		// Log retry attempts
		fmt.Printf("Database ping attempt %d/%d failed: %v\n", i+1, maxRetries, pingErr)
		
		// Exponential backoff
		if i < maxRetries-1 {
			sleepDuration := time.Duration(1<<uint(i)) * time.Second
			fmt.Printf("Retrying in %v...\n", sleepDuration)
			time.Sleep(sleepDuration)
		}
	}
	
	if pingErr != nil {
		db.Close()
		return nil, fmt.Errorf("failed to ping database after %d attempts: %w", maxRetries, pingErr)
	}

	// Enable foreign keys for SQLite
	if config.Driver == "sqlite3" {
		if _, err := db.Exec("PRAGMA foreign_keys = ON;"); err != nil {
			db.Close()
			return nil, fmt.Errorf("failed to enable foreign keys: %w", err)
		}
		// Optimize SQLite for better performance
		db.Exec("PRAGMA journal_mode = WAL;")
		db.Exec("PRAGMA synchronous = NORMAL;")
		db.Exec("PRAGMA cache_size = -64000;") // 64MB cache
		db.Exec("PRAGMA temp_store = MEMORY;")
	}

	fmt.Printf("✅ Successfully connected to %s database\n", config.Driver)
	
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

// HealthCheck performs a health check on the database
func (db *DB) HealthCheck() error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	
	return db.PingContext(ctx)
} 