# Deployment Guide

## Railway Deployment

### Prerequisites
1. Railway CLI installed: `npm install -g @railway/cli`
2. Railway account created
3. GitHub repository connected

### Setup Steps

1. **Login to Railway**
   ```bash
   railway login
   ```

2. **Initialize Railway project**
   ```bash
   railway init
   ```

3. **Set Environment Variables**
   ```bash
   railway variables set JWT_SECRET=your-secure-jwt-secret-here
   railway variables set DATABASE_PATH=/app/data/carverjobs.db
   railway variables set PORT=8080
   ```

4. **Deploy**
   ```bash
   railway up
   ```

### Environment Variables Needed

- `JWT_SECRET`: A secure random string for JWT token signing
- `DATABASE_PATH`: Path to SQLite database file (default: `/app/data/carverjobs.db`)
- `PORT`: Application port (Railway sets this automatically)

### Database

The application uses SQLite and will automatically:
- Create the database file on first run
- Run migrations to set up tables
- Start the scraper service

### Monitoring

- Health check endpoint: `/health`
- Application logs available in Railway dashboard
- Database stored in persistent volume at `/app/data`

### Scaling

- Application supports horizontal scaling
- SQLite is suitable for moderate loads
- Consider PostgreSQL for high-traffic scenarios

### Security Features

- JWT tokens with secure secret generation
- Password hashing with bcrypt
- CORS protection
- Input validation
- SQL injection prevention 