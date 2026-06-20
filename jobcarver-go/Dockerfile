# ── Build stage ──────────────────────────────────────────────────────────────
FROM golang:1.25 AS builder

WORKDIR /src

# Cache deps first.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

# Pure-Go build (CGO disabled — glebarez/sqlite needs no C toolchain).
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/server ./cmd/server

# ── Runtime stage ────────────────────────────────────────────────────────────
FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata su-exec && adduser -D -u 10001 carver
WORKDIR /app

COPY --from=builder /out/server /app/server
COPY entrypoint.sh /app/entrypoint.sh

# SQLite lives here; mount a volume at /app/data to persist across deploys.
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/data && chown -R carver:carver /app

# The entrypoint runs as root only to fix the mounted volume's ownership, then
# drops to the unprivileged `carver` user (see entrypoint.sh).
ENV PORT=3000
EXPOSE 3000

ENTRYPOINT ["/app/entrypoint.sh"]
