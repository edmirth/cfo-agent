# The platform as one image, for Render (render.yaml) or any host that runs
# containers. The frontend is built in a first stage and only its output is
# kept; the backend serves it.
#
# What is never inside: .env (the settings come from the host) and state/
# (the company's database and files live on a disk mounted at /app/state).
# .dockerignore keeps both out even if this file changes.

FROM node:24.11.1-slim AS frontend
WORKDIR /build
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend-react/ ./
RUN npm run build


FROM python:3.13.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ backend/
COPY scripts/ scripts/
# The CFO's instructions (config.AGENT_DEFINITION) and the starter rulebook a
# new company's company.md is made from.
COPY .claude/agents/ .claude/agents/
COPY company.md ./
COPY --from=frontend /build/dist frontend-react/dist

# The mount point for the disk. Without a disk the server still starts, on a
# folder that is lost on every deploy, which is fine for a look and nothing else.
RUN mkdir -p state

# One worker: the scheduler, the single-flight caches and the server lock all
# assume one process per company. No --reload. Render says which port in $PORT.
# Proxy headers are trusted because Render's proxy is the only way in.
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
