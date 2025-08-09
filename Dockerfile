# Multi-stage build for both frontend and backend

# Stage 1: Build frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Build backend
FROM golang:1.21-alpine AS backend-builder
WORKDIR /app/backend
RUN apk add --no-cache gcc musl-dev sqlite-dev
COPY backend/go.mod backend/go.sum ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=1 GOOS=linux go build -a -installsuffix cgo -o main cmd/server/main.go

# Stage 3: Final image
FROM alpine:latest
RUN apk --no-cache add ca-certificates sqlite
WORKDIR /app

# Copy backend binary and migrations
COPY --from=backend-builder /app/backend/main .
COPY --from=backend-builder /app/backend/migrations ./migrations

# Copy frontend build
COPY --from=frontend-builder /app/frontend/build ./frontend/build

# Create data directory for SQLite
RUN mkdir -p /app/data

# Environment variables
ENV PORT=8080
ENV DATABASE_PATH=/app/data/carverjobs.db

EXPOSE 8080

CMD ["./main"] 