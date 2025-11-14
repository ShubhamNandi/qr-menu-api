#!/bin/bash

# QR Menu API Startup Script
# Starts the FastAPI server with uvicorn

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Get IP address
get_ip() {
    ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}' | head -1)
    if [ -n "$ip" ] && [ "$ip" != "127.0.0.1" ]; then
        echo "$ip"
        return 0
    fi
    return 1
}

# Get current IP
CURRENT_IP=$(get_ip)

if [ -n "$CURRENT_IP" ]; then
    echo "Starting QR Menu API on IP: $CURRENT_IP:8000"
else
    echo "Starting QR Menu API on 0.0.0.0:8000"
fi

# Start uvicorn server
exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload


