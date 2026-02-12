# Kiro Gateway - Multi-Account Setup

OpenAI/Anthropic compatible API proxy for Kiro (Amazon Q Developer) with multi-account support.

## 🚀 Features

- **Multi-Account Support**: Round-robin rotation across 5+ Kiro accounts
- **Dual Authentication**: Works with both OpenAI (`Authorization: Bearer`) and Anthropic (`x-api-key`) style authentication
- **Load Balancing**: Automatic distribution of requests across all configured accounts
- **Failover Protection**: Automatic rotation to healthy accounts when one fails
- **Model Compatibility**: Access to Claude Sonnet, Haiku, and other models via Kiro API

## 🛠 Configuration

The gateway is configured with 5 Kiro accounts:
- 3 Google-authenticated accounts
- 2 GitHub-authenticated accounts

### Environment Variables

```bash
# Required - API key for proxy authentication
PROXY_API_KEY="sk-kiro-proxy-4f2e8d9c1a3b5e7f9d2c6a8b4e1f7a3c"

# Multi-account configuration (5 accounts)
REFRESH_TOKEN1="account1_refresh_token"
REFRESH_TOKEN2="account2_refresh_token"
REFRESH_TOKEN3="account3_refresh_token"
REFRESH_TOKEN4="account4_refresh_token"
REFRESH_TOKEN5="account5_refresh_token"

# Background refresh interval (seconds)
BACKGROUND_REFRESH_INTERVAL=600
```

## 🎯 API Endpoints

### Authentication
- **OpenAI-style**: `Authorization: Bearer {PROXY_API_KEY}`
- **Anthropic-style**: `x-api-key: {PROXY_API_KEY}`

### Endpoints
- `GET /` - Basic health check
- `GET /health` - Detailed health check
- `GET /v1/models` - List available models
- `POST /v1/chat/completions` - OpenAI Chat Completions API
- `POST /v1/messages` - Anthropic Messages API

## ▶️ Running the Gateway

```bash
# Install dependencies
pip install -r requirements.txt

# Run the gateway
python main.py

# Run on custom port
python main.py --port 9000
```

## 🔄 Multi-Account Benefits

- **Increased Capacity**: 5x request limits across accounts
- **Better Reliability**: Automatic failover between accounts
- **Load Distribution**: Balanced usage across all accounts
- **Automatic Refresh**: Background token refresh keeps accounts active

## 📊 Supported Models

- `auto-kiro` - Automatic model selection
- `claude-3.7-sonnet` - Claude Sonnet 3.7
- `claude-haiku-4.5` - Claude Haiku 4.5 (fast)
- `claude-sonnet-4` - Claude Sonnet 4
- `claude-sonnet-4.5` - Claude Sonnet 4.5 (most capable)
- `deepseek-3.2` - DeepSeek model
- `minimax-m2.1` - Minimax model
- `qwen3-coder-next` - Qwen3 Coder model

## 🔧 Deployment

This repository is automatically deployed to Scalingo. Push changes to trigger automatic deployment.
