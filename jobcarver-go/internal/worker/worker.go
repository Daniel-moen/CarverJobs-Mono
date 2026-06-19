// Package worker runs the background loops that mirror api/app/scheduler.py and
// api/app/services/job_retention.py.
//
// Start launches two goroutines:
//   - retentionLoop: applies the two-tier job retention policy (soft-expire then
//     hard-delete) on a fixed interval (config.JobRetentionIntervalHours).
//   - scraperLoop:   periodically invokes the (stubbed) scrapers to ingest new
//     jobs (every scrapeIntervalSeconds).
//
// Both loops stop promptly on ctx.Done(). The scraper side is a STUB — the
// internal/scrapers package returns no jobs yet — so scraperLoop just logs a
// no-op cycle. TODO(go-port): persist scraped jobs once internal/scrapers is real.
package worker

import (
	"context"
	"time"

	"jobcarver/internal/config"
	"jobcarver/internal/logger"
	"jobcarver/internal/models"
	"jobcarver/internal/scrapers"

	"jobcarver/internal/db"
)

var log = logger.Get("carver.worker")

// scrapeIntervalSeconds mirrors scheduler.SCRAPE_INTERVAL_SECONDS (12 hours).
const scrapeIntervalSeconds = 12 * 60 * 60

// Statuses that appear on active client-facing surfaces — only these are
// eligible for soft-expiry. SHARED CONTRACT with job_retention.py.
var activeStatuses = []string{"open", "priority"}

const expiredStatus = "expired"

// Start launches the background loops and returns immediately. They run until
// ctx is cancelled. Consumed by cmd/server/main.go.
func Start(ctx context.Context) {
	go retentionLoop(ctx)
	go scraperLoop(ctx)
}

// retentionLoop ports job_retention.retention_loop: a short initial delay, then
// purge on every interval. Crash-proof: a failed run is logged, the loop lives.
func retentionLoop(ctx context.Context) {
	interval := time.Duration(config.S.JobRetentionIntervalHours) * time.Hour
	if interval <= 0 {
		interval = 24 * time.Hour
	}

	// Small initial delay so it doesn't contend with DB init / first scrape.
	select {
	case <-ctx.Done():
		return
	case <-time.After(60 * time.Second):
	}

	for {
		if counts, err := purgeStaleJobs(); err != nil {
			log.Error("job retention run failed", "error", err)
		} else {
			log.Info("job retention complete", "expired", counts.expired, "deleted", counts.deleted)
		}
		log.Info("next job retention run scheduled", "hours", config.S.JobRetentionIntervalHours)
		select {
		case <-ctx.Done():
			return
		case <-time.After(interval):
		}
	}
}

type purgeCounts struct {
	expired int64
	deleted int64
}

// purgeStaleJobs ports job_retention.purge_stale_jobs: bulk soft-expire then
// hard-delete, age measured from Job.created_at.
func purgeStaleJobs() (purgeCounts, error) {
	now := time.Now().UTC()
	expireCutoff := now.Add(-time.Duration(config.S.JobExpireAfterDays) * 24 * time.Hour)
	deleteCutoff := now.Add(-time.Duration(config.S.JobDeleteAfterDays) * 24 * time.Hour)

	// 1. Soft-expire active jobs older than the expiry cutoff.
	exp := db.DB.Model(&models.Job{}).
		Where("status IN ? AND created_at < ?", activeStatuses, expireCutoff).
		Update("status", expiredStatus)
	if exp.Error != nil {
		return purgeCounts{}, exp.Error
	}

	// 2. Hard-delete anything older than the delete cutoff (any status).
	del := db.DB.Where("created_at < ?", deleteCutoff).Delete(&models.Job{})
	if del.Error != nil {
		return purgeCounts{expired: exp.RowsAffected}, del.Error
	}

	return purgeCounts{expired: exp.RowsAffected, deleted: del.RowsAffected}, nil
}

// scraperLoop ports scheduler.scraper_loop: run a (stubbed) full scrape cycle on
// a fixed interval. Stops on ctx.Done().
func scraperLoop(ctx context.Context) {
	// Initial short delay; the Python version optionally scrapes on startup,
	// which we skip (scrapers are stubbed).
	select {
	case <-ctx.Done():
		return
	case <-time.After(90 * time.Second):
	}

	for {
		results := scrapers.RunAll(ctx)
		total := 0
		for _, res := range results {
			total += len(res.Jobs)
		}
		// TODO(go-port): persist scraped jobs into models.Job (dedup on
		// content_hash / job_fingerprint) once internal/scrapers is real.
		log.Info("scraper cycle complete (stubbed)", "sources", len(results), "jobs", total)
		log.Info("next scrape cycle scheduled", "hours", scrapeIntervalSeconds/3600)
		select {
		case <-ctx.Done():
			return
		case <-time.After(scrapeIntervalSeconds * time.Second):
		}
	}
}
