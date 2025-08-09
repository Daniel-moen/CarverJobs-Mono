package main

import (
	"fmt"
	"log"

	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/database"
	"github.com/golang-migrate/migrate/v4"
	migrateDatabase "github.com/golang-migrate/migrate/v4/database"
	"github.com/golang-migrate/migrate/v4/database/postgres"
	"github.com/golang-migrate/migrate/v4/database/sqlite3"
	_ "github.com/golang-migrate/migrate/v4/source/file"
)

func main() {
	fmt.Println("Starting database migration...")
	
	// Get database configuration
	config := database.NewConfig()
	
	// Connect to database
	db, err := database.NewDB(config)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer db.Close()

	fmt.Printf("Connected to database using %s driver\n", config.Driver)

	var driver migrateDatabase.Driver
	var driverName string

	// Create appropriate driver based on database type
	if config.Driver == "postgres" {
		driver, err = postgres.WithInstance(db.DB, &postgres.Config{})
		driverName = "postgres"
	} else {
		driver, err = sqlite3.WithInstance(db.DB, &sqlite3.Config{})
		driverName = "sqlite3"
	}

	if err != nil {
		log.Fatalf("Failed to create migration driver: %v", err)
	}

	m, err := migrate.NewWithDatabaseInstance(
		"file://migrations",
		driverName,
		driver,
	)
	if err != nil {
		log.Fatalf("Failed to create migration instance: %v", err)
	}

	// Get current version
	version, dirty, err := m.Version()
	if err != nil && err != migrate.ErrNilVersion {
		log.Fatalf("Failed to get current migration version: %v", err)
	}

	fmt.Printf("Current migration version: %d (dirty: %t)\n", version, dirty)

	// Run migrations
	if err := m.Up(); err != nil && err != migrate.ErrNoChange {
		log.Fatalf("Failed to run migrations: %v", err)
	}

	// Get new version
	newVersion, dirty, err := m.Version()
	if err != nil && err != migrate.ErrNilVersion {
		log.Fatalf("Failed to get new migration version: %v", err)
	}

	fmt.Printf("Migration completed successfully! New version: %d (dirty: %t)\n", newVersion, dirty)
	
	// Test the new columns by checking table structure
	fmt.Println("Verifying new columns...")
	if config.Driver == "postgres" {
		testPostgresColumns(db)
	} else {
		testSQLiteColumns(db)
	}
}

func testPostgresColumns(db *database.DB) {
	query := `
		SELECT column_name 
		FROM information_schema.columns 
		WHERE table_name = 'users' 
		AND column_name IN ('description', 'gender', 'country_of_origin', 'subscription_type', 'cv_file_path')
		ORDER BY column_name
	`
	
	rows, err := db.Query(query)
	if err != nil {
		log.Printf("Failed to verify columns: %v", err)
		return
	}
	defer rows.Close()

	fmt.Println("Found new columns:")
	for rows.Next() {
		var columnName string
		if err := rows.Scan(&columnName); err != nil {
			log.Printf("Failed to scan column name: %v", err)
			continue
		}
		fmt.Printf("  - %s\n", columnName)
	}
}

func testSQLiteColumns(db *database.DB) {
	query := "PRAGMA table_info(users)"
	
	rows, err := db.Query(query)
	if err != nil {
		log.Printf("Failed to verify columns: %v", err)
		return
	}
	defer rows.Close()

	fmt.Println("User table columns:")
	for rows.Next() {
		var cid int
		var name, dataType string
		var notNull, pk int
		var defaultValue interface{}
		
		if err := rows.Scan(&cid, &name, &dataType, &notNull, &defaultValue, &pk); err != nil {
			log.Printf("Failed to scan column info: %v", err)
			continue
		}
		fmt.Printf("  - %s (%s)\n", name, dataType)
	}
} 