#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=========================================================="
echo "  ⚡ Starting Pratham AI Permanent Live Server & Tunnel  "
echo "=========================================================="

# Check if backend is running on port 5000
if ! curl -s http://127.0.0.1:5000/api/projects >/dev/null 2>&1; then
    echo "[1/2] Starting Python backend on port 5000..."
    python3 api/app.py > /tmp/pratham_server.log 2>&1 &
    sleep 2
fi
echo "✓ Backend active on http://127.0.0.1:5000"

# Check if ngrok is running
if ! curl -s http://127.0.0.1:4040/api/tunnels >/dev/null 2>&1; then
    echo "[2/2] Starting permanent ngrok tunnel..."
    "$DIR/ngrok" http 5000 --url=https://balance-onlooker-party.ngrok-free.dev > /tmp/pratham_ngrok.log 2>&1 &
    sleep 2
fi
echo "✓ Live Permanent URL: https://balance-onlooker-party.ngrok-free.dev"
echo "✓ Vercel App:         https://prathamai.vercel.app"
echo "=========================================================="
echo "Pratham AI is online with full terminal & ReportLab power!"
