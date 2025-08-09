# CarverJobs Mono

A modern job scraping platform focused on marine industry positions.

## Tech Stack

### Backend
- **Go** with Echo framework
- **SQLite** for fast, lightweight database
- **JWT** for secure authentication
- **tRPC** for type-safe API communication
- Modular architecture with dependency injection

### Frontend
- **Svelte** with TypeScript
- **Tailwind CSS** for styling
- **tRPC** client for type-safe API calls

### Infrastructure
- **Railway** for deployment
- **Docker** for containerization

## Project Structure

```
├── backend/           # Go backend service
│   ├── cmd/          # Application entry points
│   ├── internal/     # Internal packages
│   │   ├── auth/     # Authentication logic
│   │   ├── database/ # Database connection and migrations
│   │   ├── handlers/ # HTTP handlers (one per route)
│   │   ├── models/   # Data models
│   │   ├── services/ # Business logic
│   │   └── scraper/  # Job scraping service
│   ├── migrations/   # Database migrations
│   └── go.mod
├── frontend/         # Svelte frontend
│   ├── src/
│   │   ├── lib/      # Shared components and utilities
│   │   ├── routes/   # Page routes
│   │   └── app.html
│   ├── static/       # Static assets
│   └── package.json
├── shared/           # Shared types and schemas
└── docker-compose.yml
```

## Getting Started

### Prerequisites
- Go 1.21+
- Node.js 18+
- Railway CLI

### Development
1. Clone the repository
2. Start the backend: `cd backend && go run cmd/server/main.go`
3. Start the frontend: `cd frontend && npm run dev`

### Deployment
Deploy to Railway using the included configuration files. 