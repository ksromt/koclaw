# Koclaw Agent - Python build
# Usage: docker build -t koclaw-agent ./agent

FROM python:3.12-slim-bookworm

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Run as non-root user
RUN useradd -m -s /bin/bash koclaw
USER koclaw
WORKDIR /home/koclaw/agent

# Copy project files
COPY --chown=koclaw:koclaw pyproject.toml ./
COPY --chown=koclaw:koclaw koclaw_agent/ koclaw_agent/

# Install dependencies
RUN uv pip install --system -e .

EXPOSE 18790

CMD ["python", "-m", "koclaw_agent"]
