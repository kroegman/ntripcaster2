# syntax=docker/dockerfile:1

# Use a slim Python base image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NTRIP_OVERWRITE_DB=false

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

# Basic healthcheck to ensure the admin UI is responding
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys,contextlib;\nurl='http://127.0.0.1:8000/';\nimport urllib.error;\ntry:\n  with contextlib.closing(urllib.request.urlopen(url, timeout=3)) as r: sys.exit(0 if getattr(r,'status',200) < 400 else 1)\nexcept Exception:\n  sys.exit(1)"

# By default the SQLite DB will be created at /app/ntripcaster.db.
# You can mount a bind volume for persistence: -v $(pwd)/ntripcaster.db:/app/ntripcaster.db

# Run the FastAPI app with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
