#!/bin/bash
# Kiro Gateway - Startup Script
# Usage: ./run.sh [port]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PORT=${1:-8000}
API_KEY="meu-api-do-sucesso"

echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN}  Kiro Gateway - OpenAI Compatible${NC}"
echo -e "${GREEN}====================================${NC}"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found${NC}"
    echo "Install Python 3.10+ first"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}Installing dependencies...${NC}"
    ./.venv/bin/pip install -q -r requirements.txt
fi

# Activate virtual environment
source .venv/bin/activate

# Check if .env exists
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}Creating .env from .env.example...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}WARNING: Edit .env with your tokens before running!${NC}"
    fi
fi

# Set API key if not configured
if grep -q "my-secure-password-change-this-2024" .env 2>/dev/null; then
    echo -e "${YELLOW}WARNING: Using default API key. Edit .env to change it!${NC}"
fi

echo ""
echo -e "${GREEN}Starting Kiro Gateway on port ${PORT}...${NC}"
echo ""
echo "Endpoints available:"
echo "  - Health:      http://localhost:${PORT}/health"
echo "  - Models:      http://localhost:${PORT}/v1/models"
echo "  - Chat:        http://localhost:${PORT}/v1/chat/completions"
echo "  - Accounts:    http://localhost:${PORT}/v1/accounts/status"
echo ""
echo "OpenAI-compatible base URL:"
echo "  http://localhost:${PORT}/v1"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run the gateway
exec python3 main.py --port $PORT
