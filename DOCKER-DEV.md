# Docker Development Setup

This document explains how to run CarverJobs in development mode using Docker containers.

## 🚀 Quick Start

### Option 1: Single Container (Recommended)
```bash
./run-dev.sh
```

This will:
- Build a development container with both frontend and backend
- Serve dashboard at root path (/)
- Serve API at /api
- Connect to remote PostgreSQL database

### Option 2: Docker Compose (Separate Services)
```bash
docker-compose -f docker-compose.dev.yml up --build
```

This runs frontend and backend as separate containers.

## 🔗 Access URLs

- **Dashboard (UI):** http://localhost:8080/
- **API:** http://localhost:8080/api
- **Health Check:** http://localhost:8080/health
- **Jobs API:** http://localhost:8080/api/jobs

## 📁 Available Docker Files

- `Dockerfile.dev` - Single container with both services
- `Dockerfile.frontend.dev` - Frontend only
- `Dockerfile.backend.dev` - Backend only
- `docker-compose.dev.yml` - Multi-container setup

## 🔧 Configuration

The containers are configured to:
- Use remote PostgreSQL database at `turntable.proxy.rlwy.net:45661`
- Enable hot reloading for development
- Expose both frontend (5173) and backend (8080) ports

## 🛑 Stopping

To stop the containers:
```bash
# For single container
docker stop carverjobs-dev

# For docker-compose
docker-compose -f docker-compose.dev.yml down
```

## 🐛 Troubleshooting

If you encounter issues:
1. Make sure Docker is running
2. Check if ports 5173 and 8080 are available
3. Verify database connection in logs
4. Rebuild containers if needed: `docker build --no-cache -f Dockerfile.dev -t carverjobs-dev .` 