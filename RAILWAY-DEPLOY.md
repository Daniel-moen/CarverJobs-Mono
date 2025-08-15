# Railway Deployment Guide

This guide explains how to deploy CarverJobs to Railway with the unified structure where the dashboard is served at `/` and the API at `/api`.

## 🚀 Deployment Structure

- **Dashboard (Frontend):** Served at root path `/`
- **API:** Served at `/api/*`
- **Health Check:** Available at `/health`
- **Single Port:** Everything runs on port 8080

## 📋 Prerequisites

1. Railway CLI installed: `npm install -g @railway/cli`
2. Railway account created
3. GitHub repository connected
4. PostgreSQL database service created on Railway

## 🔧 Configuration

The deployment uses `Dockerfile.railway` which:
1. Builds the frontend for production
2. Builds the backend Go binary
3. Serves frontend static files at root
4. Serves API endpoints at `/api`

## 🌍 Environment Variables

Set these in your Railway service:

```bash
DATABASE_URL=postgresql://postgres:password@host:port/database
PORT=8080
NODE_ENV=production
```

## 🚀 Deploy Steps

1. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Deploy unified structure"
   git push origin main
   ```

2. **Railway will automatically build and deploy using:**
   - `Dockerfile.railway`
   - Environment variables from Railway dashboard
   - PostgreSQL database connection

## 📊 Access Points

After deployment, your application will be available at:

- **Main App:** `https://your-app.railway.app/`
- **API:** `https://your-app.railway.app/api/jobs`
- **Health:** `https://your-app.railway.app/health`

## 🔍 Verification

Test your deployment:

```bash
# Check health
curl https://your-app.railway.app/health

# Check API
curl https://your-app.railway.app/api/jobs

# Check frontend (should return HTML)
curl https://your-app.railway.app/
```

## 🐛 Troubleshooting

1. **Frontend not loading:** Check that `npm run build` completed successfully
2. **API not working:** Verify DATABASE_URL is set correctly
3. **Database connection:** Check PostgreSQL service is running
4. **Build failures:** Review Railway build logs

## 📝 Notes

- The frontend is built during Docker build process
- All routes are handled by a single Go server
- SPA routing is supported with fallback to `index.html`
- API calls use relative URLs (`/api/...`) for better portability 