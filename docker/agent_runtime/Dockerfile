FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONPATH=/app

# Install base system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  gcc \
  python3-dev \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user to run the agent code
RUN useradd -m -u 1000 agent_user

# Set up directories
RUN mkdir -p /app/agent \
  && mkdir -p /app/context \
  && chown -R agent_user:agent_user /app

# Copy runner script
COPY runner.py /app/
COPY context_module /app/context_module/

# Default command to run the agent
USER agent_user
ENTRYPOINT ["python", "/app/runner.py"]

# The agent_id and context_data will be passed as arguments
# Example: docker run agent_runtime agent_123 /path/to/context.json
