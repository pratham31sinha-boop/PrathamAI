# Use lightweight official Python runtime
FROM python:3.11-slim

# Install system dependencies for Pillow, ReportLab, and PDF tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Expose Koyeb standard port
EXPOSE 8000

# Start Pratham AI server
CMD ["python3", "api/app.py"]
