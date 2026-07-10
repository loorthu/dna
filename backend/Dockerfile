FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Optional internal PyPI mirror for corporate / air-gapped builds where the
# build host can't reach public PyPI. Defaults to public PyPI (normal builds
# unchanged). Pass: --build-arg PIP_INDEX_URL=... --build-arg PIP_TRUSTED_HOST=...
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=

# Install Python dependencies
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" \
        ${PIP_TRUSTED_HOST:+--trusted-host $PIP_TRUSTED_HOST} \
        -r requirements.txt

# Copy application code
COPY src/ ./src/

# Add src to Python path so 'dna' package is importable
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
