FROM python:3.12-slim

# Install system dependencies for discord.py voice and ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libffi-dev \
    libnacl-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data temp logs

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash botuser && \
    chown -R botuser:botuser /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER botuser

# Run the bot
CMD ["python", "bot.py"]
