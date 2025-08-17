FROM node:18-alpine

# Install required packages including Go, tmux, and dev dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    sqlite-dev \
    postgresql-client \
    tmux \
    bash \
    go

# Set Go environment
ENV GOPATH=/go
ENV PATH=$GOPATH/bin:/usr/local/go/bin:$PATH
ENV GOPROXY=https://proxy.golang.org,direct

# Create app directory
WORKDIR /app

# Copy and install frontend dependencies first (better caching)
COPY frontend/package*.json ./frontend/
WORKDIR /app/frontend
RUN npm ci

# Copy and download backend dependencies
WORKDIR /app/backend
COPY backend/go.mod backend/go.sum ./
RUN go mod download

# Copy all source code
WORKDIR /app
COPY frontend/ ./frontend/
COPY backend/ ./backend/

# Create tmux configuration
COPY tmux.conf /etc/tmux.conf

# Create startup script
COPY start-services.sh /start-services.sh
RUN chmod +x /start-services.sh

# Expose both ports
EXPOSE 5173 8080

# Start tmux session with both services
CMD ["/start-services.sh"]
