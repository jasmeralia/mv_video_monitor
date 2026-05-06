# Use official Playwright Python image — includes all browser system dependencies
FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install only Chromium to keep image size manageable
RUN playwright install chromium --with-deps

COPY src/ ./src/

# Create data and config directories (mounted as volumes at runtime)
RUN mkdir -p /data/logs /config

# Drop to non-root user provided by the Playwright base image
USER pwuser

# Run as a module so relative imports work
CMD ["python", "-m", "src.main"]
