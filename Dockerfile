FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY api/ ./api/
COPY src/ ./src/
COPY main.py .

# Create required runtime directories
RUN mkdir -p /tmp/argos_logs

# Expose FastAPI server port
EXPOSE 8000

# Launch uvicorn ASGI server
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
