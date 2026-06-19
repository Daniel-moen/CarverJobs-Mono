// Package logger configures stdlib log/slog as the structured logger.
// In production it emits JSON; in development it emits text. Ports the spirit of
// api/app/logger.py (structlog) onto the Go standard library.
package logger

import (
	"context"
	"log/slog"
	"os"

	"jobcarver/internal/config"
)

type ctxKey string

const requestIDKey ctxKey = "request_id"

// Setup installs a process-wide slog default handler chosen by APP_ENV.
func Setup() {
	var handler slog.Handler
	opts := &slog.HandlerOptions{Level: slog.LevelInfo}
	if config.S != nil && config.S.AppEnv == "production" {
		handler = slog.NewJSONHandler(os.Stdout, opts)
	} else {
		handler = slog.NewTextHandler(os.Stdout, opts)
	}
	slog.SetDefault(slog.New(handler))
}

// Get returns a named logger (slog.With("logger", name)).
func Get(name string) *slog.Logger {
	return slog.Default().With("logger", name)
}

// WithRequestID stores a request id on the context so handlers/middleware can
// include it in log lines (mirrors structlog bind_request_id).
func WithRequestID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, requestIDKey, id)
}

// RequestID returns the request id bound to the context, or "" if none.
func RequestID(ctx context.Context) string {
	if v, ok := ctx.Value(requestIDKey).(string); ok {
		return v
	}
	return ""
}
