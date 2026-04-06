#!/bin/bash
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║        ClassVault – Starting Up          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is required. Please install it."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting server at http://localhost:8080"
echo "Press Ctrl+C to stop."
echo ""
python3 server.py
