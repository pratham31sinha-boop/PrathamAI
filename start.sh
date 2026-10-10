#!/usr/bin/env bash
# Pratham AI - Render / Cloud Production Entrypoint
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$DIR:$DIR/api:${PYTHONPATH:-}"

PORT="${PORT:-5000}"
echo "=========================================================="
echo "  🚀 Starting Pratham AI Server on port $PORT"
echo "  Environment: Python $(python3 --version 2>&1 | awk '{print $2}')"
echo "=========================================================="

exec gunicorn --bind 0.0.0.0:"$PORT" \
     --workers 1 \
     --threads 8 \
     --timeout 180 \
     --worker-class gthread \
     --access-logfile - \
     --error-logfile - \
     "api.app:app"
