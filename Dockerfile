# saas-posture — agent container
# Python 3.11-slim + pandoc for DOCX generation
# Non-root user; all credentials via env vars only

FROM python:3.11-slim AS base

# System deps: pandoc (DOCX), curl (healthchecks), ca-certs
RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r agent && useradd -r -g agent -m -d /home/agent agent

WORKDIR /app

# Install Python deps before copying source (layer cache)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || true

# Copy source
COPY --chown=agent:agent . .

# Re-install in editable mode with full source present
RUN pip install --no-cache-dir -e .

# Generated outputs land here — mount as volume so reports survive container lifecycle
RUN mkdir -p docs/oscal-salesforce-poc/generated && \
    chown -R agent:agent docs/oscal-salesforce-poc/generated

USER agent

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["agent-loop"]
CMD ["--help"]
