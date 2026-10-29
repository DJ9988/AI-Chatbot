# Multi-stage / Production Dockerfile for Indian Unicorns Chatbot API
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install lightweight runtime dependencies (curl for container healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python package dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code and pre-processed dataset
COPY config/ config/
COPY tools/ tools/
COPY agent/ agent/
COPY security/ security/
COPY observability/ observability/
COPY data/processed/ data/processed/
COPY api.py .
COPY cli.py .

# Create logs directory for persistent audit trails
RUN mkdir -p logs

EXPOSE 8000

# Container healthcheck testing /health endpoint
HEALTHCHECK --interval=20s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start FastAPI production server
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

