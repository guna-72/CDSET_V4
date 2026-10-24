# Multi-stage Dockerfile for Chaos Tutor
# Stage 1: Build React Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/chaos
COPY chaos/package*.json ./
RUN npm install
COPY chaos/ ./
ARG VITE_API_URL=""
ARG VITE_AI_TUTOR_URL=""
RUN npm run build

# Stage 2: Production Python & Subprocess Environment
FROM python:3.11-slim
WORKDIR /app

# Install Node.js (for student Node project testing) and system tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    curl \
    git \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY backend/requirements.txt ./backend/
COPY ai_tutor_backend/requirements.txt ./ai_tutor_backend/
RUN pip install --no-cache-dir -r backend/requirements.txt -r ai_tutor_backend/requirements.txt

# Copy application source code
COPY backend ./backend
COPY ai_tutor_backend ./ai_tutor_backend
COPY start_production.sh ./
COPY --from=frontend-builder /app/chaos/dist ./chaos_dist

# Make start script executable
RUN chmod +x start_production.sh

# Cloud environments dynamically provide PORT (default to 8090)
ENV PORT=8090
ENV HOST=0.0.0.0
ENV CHAOS_TUTOR_ALLOW_DEGRADED_SANDBOX=true

EXPOSE 8090
EXPOSE 5000

CMD ["./start_production.sh"]
