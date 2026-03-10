FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install the few packages we need directly
RUN apt-get update && apt-get install -y --no-install-recommends \
    libheif-dev \
    libde265-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Using --no-cache-dir keeps the image size minimal
RUN pip install --no-cache-dir \
    python-telegram-bot \
    python-telegram-bot[job-queue] \
    pillow \
    pillow-heif \
    asyncio \
    python-dotenv

# Copy the project files
COPY . .

# Create necessary directories to avoid permission issues with volumes
RUN mkdir -p downloads && chmod 777 downloads
RUN mkdir -p database && chmod 777 database

# Run the bot
CMD ["python", "bot.py"]