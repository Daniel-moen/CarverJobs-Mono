FROM python:3.12-slim AS runtime
WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium + system dependencies (needs root).
# Browsers are stored under /app/.playwright so the api user can access them.
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright
RUN playwright install chromium --with-deps

COPY app ./app
COPY ["Matching Engine", "Matching Engine"]
COPY tests ./tests
COPY entrypoint.sh ./entrypoint.sh

RUN chmod +x entrypoint.sh && mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
ENV PORT=3000
# Run tests at build time — fails the build fast if anything is broken,
# and keeps container startup clean (uvicorn launches immediately).
RUN APP_ENV=development APIFY_API_KEY="" OPENAI_API_KEY="" \
    python -m pytest tests/ -v --tb=short
EXPOSE 3000
ENTRYPOINT ["./entrypoint.sh"]
