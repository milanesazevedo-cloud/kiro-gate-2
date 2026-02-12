# Kiro Gateway - Multi-Account Setup

OpenAI/Anthropic compatible API proxy for Kiro (Amazon Q Developer) with multi-account support.

## 🚀 Features

- **Multi-Account Support**: Round-robin rotation across multiple Kiro accounts
- **Dual Authentication**: Works with both OpenAI (`Authorization: Bearer`) and Anthropic (`x-api-key`) style authentication
- **Load Balancing**: Automatic distribution of requests across all configured accounts
- **Failover Protection**: Automatic rotation to healthy accounts when one fails
- **Model Compatibility**: Access to Claude Sonnet, Haiku, and other models via Kiro API

## 🛠 Configuration

The gateway is configured with multiple Kiro accounts for load balancing and redundancy.

### Environment Variables

```bash
# Required - API key for proxy authentication
PROXY_API_KEY="your-secret-api-key-here"

# Multi-account configuration
REFRESH_TOKEN1="first_account_refresh_token"
REFRESH_TOKEN2="second_account_refresh_token"
REFRESH_TOKEN3="third_account_refresh_token"
# Add more tokens as needed

# Background refresh interval (seconds)
BACKGROUND_REFRESH_INTERVAL=600
```

## 🎯 API Endpoints

### Authentication
- **OpenAI-style**: `Authorization: Bearer YOUR_API_KEY`
- **Anthropic-style**: `x-api-key: YOUR_API_KEY`

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

- **Increased Capacity**: Multiple accounts increase total request limits
- **Better Reliability**: Automatic failover between accounts
- **Load Distribution**: Balanced usage across all accounts
- **Automatic Refresh**: Background token refresh keeps accounts active

## 📊 Supported Models

The gateway provides access to various models through the Kiro API including Claude models and other providers.

## 🔧 Deployment

This repository is automatically deployed to Scalingo. Push changes to trigger automatic deployment.
