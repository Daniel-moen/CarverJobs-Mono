# Build stage
FROM golang:1.23-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache gcc musl-dev git

# Copy go mod files first for better caching
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY . .

# Build the binary
RUN CGO_ENABLED=1 GOOS=linux go build -v -a -installsuffix cgo -o /main ./cmd/server

# Production stage
FROM alpine:latest

# Install runtime dependencies
RUN apk --no-cache add ca-certificates tzdata wget

WORKDIR /app

# Copy the binary from builder
COPY --from=builder /main ./server
COPY --from=builder /app/migrations ./migrations

# Create data directory for SQLite
RUN mkdir -p data

# Expose port
EXPOSE 8081

# Run the binary
CMD ["./server"] 