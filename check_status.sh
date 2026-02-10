#!/bin/bash
# Check Kiro Gateway status from outside the container
# Usage: ./check_status.sh

KIRO_URL="http://localhost:8000"
API_KEY="meu-api-do-sucesso"

echo "=========================================="
echo "  Kiro Gateway - Status Checker"
echo "=========================================="
echo ""

# Check if container is running
echo "[1] Container Status"
if docker ps | grep -q kiro-gateway; then
    echo "  Container: RUNNING"
    docker ps --filter "name=kiro-gateway" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep kiro-gateway
else
    echo "  Container: NOT RUNNING"
    exit 1
fi

echo ""
echo "[2] Health Check"
curl -s "${KIRO_URL}/health" | python3 -m json.tool 2>/dev/null || curl -s "${KIRO_URL}/health"

echo ""
echo "[3] Accounts Status"
curl -s -H "Authorization: Bearer ${API_KEY}" "${KIRO_URL}/v1/accounts/status" | python3 -m json.tool 2>/dev/null || \
    curl -s -H "Authorization: Bearer ${API_KEY}" "${KIRO_URL}/v1/accounts/status"

echo ""
echo "[4] Container Logs (last 10 lines)"
docker logs --tail 10 kiro-gateway 2>/dev/null

echo ""
echo "[5] Quick Test Chat Completion"
curl -s -X POST "${KIRO_URL}/v1/chat/completions" \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "claude-sonnet-4-20250506",
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 10
    }' | head -c 200

echo ""
