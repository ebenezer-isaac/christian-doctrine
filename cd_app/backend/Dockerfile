# Backend image: FastAPI + the Claude Agent SDK, which shells out to the
# Claude Code CLI, so Node + the CLI are installed alongside Python.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

COPY . /app/backend

RUN useradd -m -u 10001 app \
    && mkdir -p /work /home/app/.claude \
    && chown -R app:app /app /work /home/app
USER app
ENV HOME=/home/app

EXPOSE 8080
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
