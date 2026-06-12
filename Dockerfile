# Dockerfile
# Multi-stage build: Python backend + Node.js frontend

# ── Stage 1: Build React frontend ──
FROM node:20-slim AS frontend-build
WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm ci --production=false
COPY ui/ ./
RUN npm run build

# ── Stage 2: Python backend ──
FROM python:3.12-slim AS backend
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY main.py .
COPY agents/ agents/
COPY rag/ rag/
COPY api/ api/
COPY data/ data/

# Copy built frontend
COPY --from=frontend-build /app/ui/dist /app/static

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
