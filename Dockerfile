# syntax=docker/dockerfile:1

# Use a slim Python base image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set workdir
WORKDIR /app

# System deps (optional but useful for timezones and certificates)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker layer cache
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app ./app
COPY templates ./templates
COPY static ./static
COPY README.md ./

# Expose admin UI and NTRIP caster ports
EXPOSE 8000
EXPOSE 2101

# By default the SQLite DB will be created at /app/ntripcaster.db.
# You can mount a bind volume for persistence: -v $(pwd)/ntripcaster.db:/app/ntripcaster.db

# Run the FastAPI app with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
