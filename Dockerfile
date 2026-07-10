FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies (including Tesseract for OCR)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-ita \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY api/ ./api/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config.yaml .
COPY workflows/ ./workflows/
COPY dashboard/dist/ ./dashboard/dist/

# Create required runtime directories and set permissions
RUN mkdir -p /tmp/argos_logs /app/data

# Security: Create a non-root user with configurable UID to match the host user.
# This ensures write access to host-mounted volumes (e.g. ./data:/app/data).
# Override at build time: --build-arg USER_ID=$(id -u) --build-arg GROUP_ID=$(id -g)
ARG USER_ID=1000
ARG GROUP_ID=1000
RUN groupadd -r -g ${GROUP_ID} argos && useradd -r -u ${USER_ID} -g argos -d /app -s /sbin/nologin argos \
    && chown -R argos:argos /app /tmp/argos_logs

USER argos

# Expose FastAPI server port
EXPOSE 8000

# Launch uvicorn ASGI server
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
