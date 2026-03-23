FROM python:3.12-slim AS runtime
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright
RUN playwright install chromium --with-deps

COPY app ./app
COPY ["Matching Engine", "Matching Engine"]
COPY entrypoint.sh ./entrypoint.sh

RUN chmod +x entrypoint.sh && mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
ENV PORT=3000
EXPOSE 3000
ENTRYPOINT ["./entrypoint.sh"]
