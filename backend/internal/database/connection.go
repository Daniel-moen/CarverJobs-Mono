package database

import (
	"database/sql"
	"fmt"
	"os"

	_ "github.com/lib/pq"
	_ "github.com/mattn/go-sqlite3"
)

type Config struct {
	DatabaseURL string
	Driver      string
}

type DB struct {
	*sql.DB
}

func NewConfig() Config {
	// Check if DATABASE_URL is set (PostgreSQL)
	databaseURL := os.Getenv("DATABASE_URL")
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

	// Use PostgreSQL
	if driver == "" {
		driver = "postgres"
	}

	return Config{
		DatabaseURL: databaseURL,
		Driver:      driver,
	}
}

func NewDB(config Config) (*DB, error) {
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

	return &DB{db}, nil
}

// Close closes the database connection
func (db *DB) Close() error {
	return db.DB.Close()
} 