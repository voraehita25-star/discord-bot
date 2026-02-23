FROM python:3.14-slim

# Install system dependencies for discord.py voice and ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libffi-dev \
    libnacl-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash botuser

# Copy requirements first for better caching
COPY --chown=botuser:botuser requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=botuser:botuser . .

# Create necessary directories
RUN mkdir -p data temp logs && chown -R botuser:botuser data temp logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER botuser

# Run the bot
CMD ["python", "bot.py"]
