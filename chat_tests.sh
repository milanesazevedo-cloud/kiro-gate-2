#!/bin/bash
# Kiro Gateway - Chat Tests
# Usage: ./chat_tests.sh

KIRO_URL="http://localhost:8000"
API_KEY="meu-api-do-sucesso"

echo "=========================================="
echo "  Kiro Gateway - Chat Tests"
echo "=========================================="
echo ""

# Test 1: Simple chat
echo "[Test 1] Simple Chat"
echo "--------------------"
curl -s -X POST "${KIRO_URL}/v1/chat/completions" \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "claude-sonnet-4-20250506",
        "messages": [{"role": "user", "content": "Hello! Say just OK."}],
        "max_tokens": 20
    }' | python3 -m json.tool 2>/dev/null | head -20

echo ""

# Test 2: Streaming chat
echo "[Test 2] Streaming Chat"
echo "-----------------------"
echo "Response (streaming):"
curl -s -X POST "${KIRO_URL}/v1/chat/completions" \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "claude-sonnet-4-20250506",
        "messages": [{"role": "user", "content": "Count from 1 to 5, one number per line."}],
        "max_tokens": 50,
        "stream": true
    }' | head -c 500

echo ""
echo ""

# Test 3: System message
echo "[Test 3] System Message"
echo "------------------------"
curl -s -X POST "${KIRO_URL}/v1/chat/completions" \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "claude-sonnet-4-20250506",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Answer briefly."},
            {"role": "user", "content": "What is 2+2?"}
        ],
        "max_tokens": 20
    }' | python3 -m json.tool 2>/dev/null | head -15

echo ""

# Test 4: Multiple messages (conversation)
echo "[Test 4] Conversation History"
echo "------------------------------"
curl -s -X POST "${KIRO_URL}/v1/chat/completions" \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "claude-sonnet-4-20250506",
        "messages": [
            {"role": "user", "content": "My name is Claude"},
            {"role": "assistant", "content": "Nice to meet you, Claude!"},
            {"role": "user", "content": "What is my name?"}
        ],
        "max_tokens": 20
    }' | python3 -m json.tool 2>/dev/null | head -15

echo ""
echo "=========================================="
echo "  Tests Complete"
echo "=========================================="
