FROM python:3.11-slim

# Install system dependencies for OpenCV and InsightFace build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency requirements
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app/ ./app/
COPY setup_models.py .

# Pre-download face recognition AI models into image
RUN python setup_models.py || true

# Expose standard web port
EXPOSE 7860

# Launch FastAPI web application with dynamic port support (Render $PORT or default 7860)
CMD ["sh", "-c", "uvicorn app.web.server:app --host 0.0.0.0 --port ${PORT:-7860}"]
