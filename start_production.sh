#!/usr/bin/env bash
# Production entrypoint for Cloud deployments (Render, Koyeb, Docker, VPS)
set -e

echo "=== Starting Chaos Tutor Cloud Services ==="

# 1. Start AI Tutor microservice on local port 5000 in the background
echo "Starting AI Tutor backend on port 5000..."
cd ai_tutor_backend
export AI_TUTOR_PORT=5000
export HOST=127.0.0.1
python app.py &
AI_PID=$!
cd ..

# Ensure AI tutor process terminates if main script exits
trap "kill -9 $AI_PID 2>/dev/null || true" EXIT

# 2. Wait briefly for AI Tutor service to initialise
sleep 2

# 3. Start Core Chaos Tutor Backend on the Cloud Platform assigned PORT (default 8090)
echo "Starting Core Backend on port ${PORT:-8090}..."
cd backend
export HOST=0.0.0.0
export PORT="${PORT:-8090}"
export CHAOS_TUTOR_ALLOW_DEGRADED_SANDBOX="${CHAOS_TUTOR_ALLOW_DEGRADED_SANDBOX:-true}"
exec python -m app.main
