FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies (including Tesseract for OCR)
RUN apt-get update && apt-get install -y \
    build-essential \
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
COPY main.py .

# Create required runtime directories and set permissions
RUN mkdir -p /tmp/argos_logs

# Security: Create a non-root user and assign ownership
RUN groupadd -r argos && useradd -r -g argos -d /app -s /sbin/nologin argos \
    && chown -R argos:argos /app /tmp/argos_logs

USER argos

# Expose FastAPI server port
EXPOSE 8000

# Launch uvicorn ASGI server
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
