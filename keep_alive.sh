#!/usr/bin/env bash
# Pratham AI - Unbreakable Phone Daemon & Watchdog
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# 1. Acquire Android Wake Lock so phone CPU never sleeps when screen turns off
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
    echo "⚡ Termux wake lock acquired. Android will not sleep."
fi

# 2. Prevent SIGHUP from closing when terminal closes
trap "" HUP

echo "=========================================================="
echo "  🛡️ Pratham AI Phone Daemon Active (Auto-Restart Enabled)"
echo "=========================================================="
echo "URL: https://balance-onlooker-party.ngrok-free.dev"
echo "Running in background... You can lock phone or minimize."
echo "=========================================================="

while true; do
    # Check & restart backend
    if ! curl -s --max-time 3 http://127.0.0.1:5000/api/projects >/dev/null 2>&1; then
        echo "[Watchdog] Backend down. Starting..."
        python3 api/app.py > /tmp/pratham_server.log 2>&1 &
        sleep 2
    fi

    # Check & restart ngrok
    if ! curl -s --max-time 3 http://127.0.0.1:4040/api/tunnels >/dev/null 2>&1; then
        echo "[Watchdog] Ngrok tunnel down. Starting..."
        "$DIR/ngrok" http --url=balance-onlooker-party.ngrok-free.dev 5000 > /tmp/pratham_ngrok.log 2>&1 &
        sleep 2
    fi

    sleep 5
done
