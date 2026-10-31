# syntax=docker/dockerfile:1
FROM python:3.12.7-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    PORT=8000

# Install curl for HEALTHCHECK and ffmpeg if needed for voice processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root application user and data directory
RUN useradd -m -u 10001 -s /bin/bash appuser && \
    mkdir -p /data /app && \
    chown -R appuser:appuser /data /app

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT:-8000}/health || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
