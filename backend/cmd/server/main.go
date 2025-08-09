package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/auth"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/database"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/handlers"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/scraper"
	"github.com/Daniel-moen/CarverJobs-Mono/backend/internal/services"
	"github.com/golang-migrate/migrate/v4"
	"github.com/golang-migrate/migrate/v4/database/postgres"
	"github.com/golang-migrate/migrate/v4/database/sqlite3"
	_ "github.com/golang-migrate/migrate/v4/source/file"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
	"go.uber.org/fx"
)

func main() {
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

// RunMigrations runs database migrations
func RunMigrations(lc fx.Lifecycle, db *database.DB, config database.Config) {
	lc.Append(fx.Hook{
		OnStart: func(ctx context.Context) error {
			var driver migrate.DatabaseDriver
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

			m, err := migrate.NewWithDatabaseInstance(
				"file://migrations",
				driverName,
				driver,
			)
			if err != nil {
				return fmt.Errorf("failed to create migration instance: %w", err)
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
) {
	lc.Append(fx.Hook{
		OnStart: func(ctx context.Context) error {
			// Health check
			e.GET("/health", func(c echo.Context) error {
				return c.JSON(http.StatusOK, map[string]string{
					"status": "healthy",
					"time":   time.Now().Format(time.RFC3339),
				})
			})

			// API routes
			api := e.Group("/api/v1")

			// Public routes
			api.POST("/auth/register", authHandler.RegisterUser)
			api.POST("/auth/login", authHandler.LoginUser)
			api.GET("/jobs", jobHandler.GetJobs)
			api.GET("/jobs/:id", jobHandler.GetJobByID)

			// Protected routes
			protected := api.Group("")
			protected.Use(auth.JWTMiddleware(jwtService))
			protected.GET("/auth/profile", authHandler.GetProfile)

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
	lc.Append(fx.Hook{
		OnStart: func(ctx context.Context) error {
			// Start scraper in background
			go func() {
				// Run immediately on startup
				if err := scraperService.ScrapeYachtJobs(); err != nil {
					fmt.Printf("Initial yacht scraping failed: %v\n", err)
				}

				// Then run every 6 hours
				ticker := time.NewTicker(6 * time.Hour)
				defer ticker.Stop()

				for {
					select {
					case <-ticker.C:
						if err := scraperService.ScrapeYachtJobs(); err != nil {
							fmt.Printf("Scheduled yacht scraping failed: %v\n", err)
						}
					case <-ctx.Done():
						return
					}
				}
			}()

			fmt.Println("Yacht job scraper started - running every 6 hours")
			return nil
		},
	})
} 