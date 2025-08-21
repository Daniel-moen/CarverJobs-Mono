package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/auth"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/database"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/handlers"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/scraper"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/services"
	"github.com/golang-migrate/migrate/v4"
	migrateDatabase "github.com/golang-migrate/migrate/v4/database"
	"github.com/golang-migrate/migrate/v4/database/postgres"
	"github.com/golang-migrate/migrate/v4/database/sqlite3"
	_ "github.com/golang-migrate/migrate/v4/source/file"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
	"go.uber.org/fx"
)

// getFrontendBuildPath returns the correct path to frontend build directory
// It handles different working directories for local development and Railway deployment
func getFrontendBuildPath() (string, error) {
	// First, try to get the current working directory
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}

	// Check if frontend build directory exists relative to current directory (local development)
	frontendBuildPath := filepath.Join(cwd, "..", "frontend", "build")
	if _, err := os.Stat(frontendBuildPath); err == nil {
		return frontendBuildPath, nil
	}

	// Check if frontend build directory exists in frontend subdirectory (Railway case)
	railwayBuildPath := filepath.Join(cwd, "frontend", "build")
	if _, err := os.Stat(railwayBuildPath); err == nil {
		return railwayBuildPath, nil
	}

	// Check if frontend build directory exists in parent/frontend directory
	parentFrontendPath := filepath.Join(filepath.Dir(cwd), "frontend", "build")
	if _, err := os.Stat(parentFrontendPath); err == nil {
		return parentFrontendPath, nil
	}

	return "", fmt.Errorf("frontend build directory not found in any expected location")
}

// getMigrationsPath returns the correct path to migrations directory
// It handles different working directories for local development and Railway deployment
func getMigrationsPath() (string, error) {
	// First, try to get the current working directory
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}

	// Check if migrations directory exists in current directory
	migrationsPath := filepath.Join(cwd, "migrations")
	if _, err := os.Stat(migrationsPath); err == nil {
		return fmt.Sprintf("file://%s", migrationsPath), nil
	}

	// Check if migrations directory exists in backend subdirectory (Railway case)
	backendMigrationsPath := filepath.Join(cwd, "backend", "migrations")
	if _, err := os.Stat(backendMigrationsPath); err == nil {
		return fmt.Sprintf("file://%s", backendMigrationsPath), nil
	}

	// Check if migrations directory exists in parent/backend directory
	parentBackendPath := filepath.Join(filepath.Dir(cwd), "backend", "migrations")
	if _, err := os.Stat(parentBackendPath); err == nil {
		return fmt.Sprintf("file://%s", parentBackendPath), nil
	}

	return "", fmt.Errorf("migrations directory not found in any expected location")
}

func main() {
	// Parse command line flags
	migrateOnly := flag.Bool("migrate-only", false, "Run migrations and exit")
	flag.Parse()

	if *migrateOnly {
		runMigrationOnly()
		return
	}

	fx.New(
		// Provide dependencies
		fx.Provide(
			database.NewConfig,
			database.NewDB,
			auth.NewJWTService,
			services.NewUserService,
			services.NewJobService,
			handlers.NewAuthHandler,
			handlers.NewJobHandler,
			scraper.NewYachtScraperService,
			NewEcho,
		),
		// Register lifecycle hooks
		fx.Invoke(RunMigrations),
		fx.Invoke(SetupRoutes),
		fx.Invoke(StartScraper),
	).Run()
}

func runMigrationOnly() {
	fmt.Println("Running migrations only...")
	
	config := database.NewConfig()
	db, err := database.NewDB(config)
	if err != nil {
		fmt.Printf("Failed to connect to database: %v\n", err)
		os.Exit(1)
	}
	defer db.Close()

	var driver migrateDatabase.Driver
	var driverName string

	if config.Driver == "postgres" {
		driver, err = postgres.WithInstance(db.DB, &postgres.Config{})
		driverName = "postgres"
	} else {
		driver, err = sqlite3.WithInstance(db.DB, &sqlite3.Config{})
		driverName = "sqlite3"
	}

	if err != nil {
		fmt.Printf("Failed to create migration driver: %v\n", err)
		os.Exit(1)
	}

	migrationsPath, err := getMigrationsPath()
	if err != nil {
		fmt.Printf("Failed to find migrations directory: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Using migrations path: %s\n", migrationsPath)

	m, err := migrate.NewWithDatabaseInstance(
		migrationsPath,
		driverName,
		driver,
	)
	if err != nil {
		fmt.Printf("Failed to create migration instance: %v\n", err)
		os.Exit(1)
	}

	if err := m.Up(); err != nil && err != migrate.ErrNoChange {
		fmt.Printf("Failed to run migrations: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Migrations completed successfully using %s\n", driverName)
}

// NewEcho creates a new Echo instance with middleware
func NewEcho() *echo.Echo {
	e := echo.New()

	// Middleware
	e.Use(middleware.Logger())
	e.Use(middleware.Recover())
	e.Use(middleware.CORS())

	// Remove trailing slash
	e.Pre(middleware.RemoveTrailingSlash())

	return e
}

// waitForDB pings the DB until it's reachable or timeout elapses
func waitForDB(db *database.DB, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	var lastErr error
	for time.Now().Before(deadline) {
		if err := db.Ping(); err == nil {
			return nil
		} else {
			lastErr = err
		}
		time.Sleep(1 * time.Second)
	}
	return fmt.Errorf("database not ready after %s: %w", timeout, lastErr)
}

// RunMigrations runs database migrations with retries for DB readiness
func RunMigrations(lc fx.Lifecycle, db *database.DB, config database.Config) {
	lc.Append(fx.Hook{
		OnStart: func(ctx context.Context) error {
			// Ensure DB is ready (helpful on cold starts)
			if err := waitForDB(db, 60*time.Second); err != nil {
				return err
			}

			var driver migrateDatabase.Driver
			var err error
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
				return fmt.Errorf("failed to create migration driver: %w", err)
			}

			migrationsPath, err := getMigrationsPath()
			if err != nil {
				return fmt.Errorf("failed to find migrations directory: %w", err)
			}

			fmt.Printf("Using migrations path: %s\n", migrationsPath)

			// Create migration instance with retry (handles transient errors)
			var m *migrate.Migrate
			for i := 0; i < 5; i++ {
				m, err = migrate.NewWithDatabaseInstance(
					migrationsPath,
					driverName,
					driver,
				)
				if err == nil {
					break
				}
				time.Sleep(time.Duration(1+i) * time.Second)
			}
			if err != nil {
				return fmt.Errorf("failed to create migration instance after retries: %w", err)
			}

			if err := m.Up(); err != nil && err != migrate.ErrNoChange {
				return fmt.Errorf("failed to run migrations: %w", err)
			}

			fmt.Printf("Database migrations completed successfully using %s\n", driverName)
			return nil
		},
	})
}

// SetupRoutes configures all API routes
func SetupRoutes(
	lc fx.Lifecycle,
	e *echo.Echo,
	authHandler *handlers.AuthHandler,
	jobHandler *handlers.JobHandler,
	jwtService *auth.JWTService,
	db *database.DB,
) {
	lc.Append(fx.Hook{
		OnStart: func(ctx context.Context) error {
			// Health check with database connectivity
			e.GET("/health", func(c echo.Context) error {
				status := map[string]interface{}{
					"status": "healthy",
					"time":   time.Now().Format(time.RFC3339),
				}
				
				// Check database connectivity
				if err := db.Ping(); err != nil {
					status["status"] = "unhealthy"
					status["database"] = "disconnected"
					status["database_error"] = err.Error()
					return c.JSON(http.StatusServiceUnavailable, status)
				}
				
				status["database"] = "connected"
				return c.JSON(http.StatusOK, status)
			})

			// API routes
			api := e.Group("/api")

			// Public routes
			api.POST("/auth/register", authHandler.RegisterUser)
			api.POST("/auth/login", authHandler.LoginUser)
			api.GET("/jobs", jobHandler.GetJobs)
			api.GET("/jobs/:id", jobHandler.GetJobByID)

			// Protected routes
			protected := api.Group("")
			protected.Use(auth.JWTMiddleware(jwtService))
			protected.GET("/auth/profile", authHandler.GetProfile)
			protected.PUT("/auth/profile", authHandler.UpdateProfile)

			// Admin routes
			admin := api.Group("/admin")
			admin.Use(auth.JWTMiddleware(jwtService))
			admin.Use(auth.RequireRole("admin"))
			admin.POST("/jobs", jobHandler.CreateJob)


			// Start server
			port := os.Getenv("PORT")
			if port == "" {
				port = "8080"
			}

			go func() {
				if err := e.Start(":" + port); err != nil && err != http.ErrServerClosed {
					e.Logger.Fatal("Failed to start server: ", err)
				}
			}()

			fmt.Printf("Server started on port %s\n", port)
			return nil
		},
		OnStop: func(ctx context.Context) error {
			return e.Shutdown(ctx)
		},
	})
}

// StartScraper starts the yacht job scraping service
func StartScraper(lc fx.Lifecycle, scraperService *scraper.YachtScraperService) {
	scraperEnabled, _ := strconv.ParseBool(os.Getenv("SCRAPER_ENABLED"))
	if !scraperEnabled {
		log.Println("Scraper is disabled by environment variable.")
		return
	}

	lc.Append(fx.Hook{
		OnStart: func(ctx context.Context) error {
			go scraperService.ScrapeYachtJobs()
			return nil
		},
	})
} 