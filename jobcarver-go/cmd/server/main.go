// Command server is the jobcarver API entrypoint: it loads config, initialises
// the database, starts background loops, and serves HTTP with graceful shutdown.
package main

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"jobcarver/internal/config"
	"jobcarver/internal/db"
	"jobcarver/internal/logger"
	"jobcarver/internal/metrics"
	"jobcarver/internal/server"
	"jobcarver/internal/worker"
)

func main() {
	config.Load()
	logger.Setup()
	log := logger.Get("carver.main")

	if err := db.Init(); err != nil {
		log.Error("database init failed", "error", err)
		os.Exit(1)
	}
	if err := db.AutoMigrate(); err != nil {
		log.Error("auto-migrate failed", "error", err)
		os.Exit(1)
	}
	if err := db.EnsureDefaultUser(); err != nil {
		log.Error("default user seed failed", "error", err)
		// non-fatal — continue
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Background loops.
	go metricsLoop(ctx)
	worker.Start(ctx) // Worker 3: retention + scraper loops

	handler := server.New()
	server.SetReady(true)

	srv := &http.Server{
		Addr:              ":" + config.S.Port,
		Handler:           handler,
		ReadHeaderTimeout: 15 * time.Second,
	}

	go func() {
		log.Info("listening", "addr", srv.Addr, "env", config.S.AppEnv)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("server error", "error", err)
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	log.Info("shutdown signal received")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Error("graceful shutdown failed", "error", err)
	}
	log.Info("server stopped")
}

// metricsLoop records a metrics snapshot every 60 seconds (ports metrics_loop).
func metricsLoop(ctx context.Context) {
	ticker := time.NewTicker(60 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			metrics.RecordSnapshot()
		}
	}
}
