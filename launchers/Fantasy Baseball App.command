#!/bin/bash
# start_server.command
# Double-click to start the Fantasy Baseball server and open it in Chrome.

PROJECT_DIR="$HOME/Projects/fantasy_baseball_br"

cd "$PROJECT_DIR"

echo "================================================"
echo " Fantasy Baseball Server"
echo "================================================"
echo " Project: $PROJECT_DIR"
echo " URL:     http://localhost:8000"
echo ""
echo " Press Ctrl+C to stop the server."
echo "================================================"
echo ""

# Open Chrome after a short delay
(sleep 2 && open -a "Google Chrome" "http://localhost:8000") &

# Start the server (blocks until Ctrl+C)
uv run uvicorn app.main:app --reload --port 8000
