#!/bin/bash

echo "🚀 Starting CarverJobs Development Container"
echo "============================================="
echo "Frontend will be available at: http://localhost:5173"
echo "Backend API will be available at: http://localhost:8080"
echo "============================================="

# Build and run the development container
docker build -f Dockerfile.dev -t carverjobs-dev .
docker run -it --rm -p 5173:5173 -p 8080:8080 --name carverjobs-dev carverjobs-dev 