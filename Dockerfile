# PostgreSQL-ready Dockerfile
FROM golang:1.23-alpine AS builder

WORKDIR /app/backend

# Install basic build dependencies (PostgreSQL driver doesn't need sqlite-dev)
RUN apk add --no-cache gcc musl-dev

# Copy go mod files
COPY backend/go.mod backend/go.sum ./
RUN go mod download

# Copy backend source
COPY backend/ ./

# Build the application and migration tool
RUN CGO_ENABLED=1 GOOS=linux go build -a -installsuffix cgo -o main cmd/server/main.go
RUN CGO_ENABLED=1 GOOS=linux go build -a -installsuffix cgo -o migrate cmd/migrate/main.go

# Final stage
FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /app

# Copy binaries and migrations
COPY --from=builder /app/backend/main .
COPY --from=builder /app/backend/migrate .
COPY --from=builder /app/backend/migrations ./migrations
COPY migrate.sh .

# Create data directory (for SQLite fallback)
RUN mkdir -p /app/data

# Environment variables
ENV PORT=8080

EXPOSE 8080

CMD ["./main"] 