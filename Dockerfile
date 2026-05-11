FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (ffmpeg, yt-dlp, etc.)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directories
RUN mkdir -p outputs .work

# Expose port 8787
EXPOSE 8787

# Set environment variables
ENV PORT=8787
ENV PYTHONUNBUFFERED=1

# Start the application
CMD ["python", "src/web_app.py"]
