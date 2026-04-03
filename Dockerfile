FROM pytorch/pytorch:2.11.0-cuda13.0-cudnn9-runtime

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy manifests for dependency installation (Layer 1: Caching)
COPY pyproject.toml README.md ./

# Pre-install build backend (Hatch) to avoid build isolation network issues in VMs
RUN pip install --no-cache-dir --break-system-packages hatchling

# Install the project and its dependencies (no build isolation to avoid DNS errors)
RUN pip install --no-cache-dir --break-system-packages --no-build-isolation .[neo4j,sql,local]

# Copy the actual application source (Layer 2: Logic)
COPY stixdb/ stixdb/

# Create data directory
RUN mkdir -p /app/stixdb_data

# Expose the API port
EXPOSE 4020

# Default environment variables
ENV STIXDB_API_PORT=4020
ENV STIXDB_STORAGE_MODE=neo4j
ENV STIXDB_VECTOR_BACKEND=chroma
ENV STIXDB_DATA_DIR=/app/stixdb_data
ENV STIXDB_LOG_LEVEL=INFO

# Start the server
CMD ["uvicorn", "stixdb.api.server:app", "--host", "0.0.0.0", "--port", "4020"]
