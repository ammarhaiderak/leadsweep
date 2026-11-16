# Stage 1: Build Frontend SPA
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY project/package.json project/package-lock.json ./
RUN npm ci
COPY project/ ./
RUN npm run build

# Stage 2: Python 3.11 Slim Backend
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    LEADSWEEP_WEB_DIST=/app/project/dist

WORKDIR /app

# Install curl, ca-certificates, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gcc \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright chromium with OS dependencies
RUN playwright install --with-deps chromium

# Create non-root user and ensure directories exist with correct permissions
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data /app/secrets /ms-playwright && \
    chown -R appuser:appuser /app /ms-playwright

# Copy application source, config, scripts, and built frontend from Stage 1
COPY --chown=appuser:appuser leadsweep/ /app/leadsweep/
COPY --chown=appuser:appuser scripts/ /app/scripts/
COPY --chown=appuser:appuser config/ /app/config/
COPY --from=frontend-builder --chown=appuser:appuser /build/dist /app/project/dist
COPY --chown=appuser:appuser docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["studio"]
