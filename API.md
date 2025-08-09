# CarverJobs API Documentation

## Authentication

All protected endpoints require a Bearer token in the Authorization header:
```
Authorization: Bearer <your-jwt-token>
```

## Endpoints

### Health Check
- **GET** `/health`
- Returns application status

### Authentication

#### Register User
- **POST** `/api/v1/auth/register`
- Body:
```json
{
  "email": "user@example.com",
  "password": "securepassword",
  "first_name": "John",
  "last_name": "Doe"
}
```
- Response: `201 Created` with user data

#### Login
- **POST** `/api/v1/auth/login`
- Body:
```json
{
  "email": "user@example.com",
  "password": "securepassword"
}
```
- Response: `200 OK` with JWT token and user data

#### Get Profile (Protected)
- **GET** `/api/v1/auth/profile`
- Requires: Bearer token
- Response: User profile data

### Jobs

#### Get Jobs (Public)
- **GET** `/api/v1/jobs`
- Query parameters:
  - `type`: Filter by job type (deck, engine, catering, etc.)
  - `location`: Filter by location
  - `company`: Filter by company name
  - `limit`: Number of results (default: 20, max: 100)
  - `offset`: Pagination offset

- Response:
```json
{
  "jobs": [...],
  "total": 150,
  "page": 1,
  "limit": 20
}
```

#### Get Job by ID (Public)
- **GET** `/api/v1/jobs/:id`
- Response: Single job object

#### Create Job (Admin Only)
- **POST** `/api/v1/admin/jobs`
- Requires: Bearer token with admin role
- Body: Job object

## Data Models

### User
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "role": "user",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### Job
```json
{
  "id": "uuid",
  "title": "Chief Engineer",
  "company": "Maritime Corp",
  "location": "Worldwide",
  "type": "engine",
  "vessel": "tanker",
  "duration": "4 months",
  "salary": "$8000/month",
  "description": "Job description...",
  "requirements": "Requirements...",
  "source_url": "https://example.com/job/123",
  "source": "Maritime Jobs",
  "posted_at": "2024-01-01T00:00:00Z",
  "scraped_at": "2024-01-01T00:00:00Z",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

## Error Responses

All errors return JSON with error message:
```json
{
  "message": "Error description"
}
```

Common HTTP status codes:
- `400`: Bad Request (validation errors)
- `401`: Unauthorized (missing/invalid token)
- `403`: Forbidden (insufficient permissions)
- `404`: Not Found
- `409`: Conflict (duplicate email, etc.)
- `500`: Internal Server Error 