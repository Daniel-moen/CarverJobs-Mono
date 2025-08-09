#!/bin/bash

echo "Starting database migration on Railway..."

# Navigate to the app directory
cd /app

# Run the migration
echo "Running migration command..."
./migrate

echo "Migration script completed!" 