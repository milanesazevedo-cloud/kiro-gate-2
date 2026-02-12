# Kiro Gateway

**Language:** Python 3.10+ | **Framework:** FastAPI
**License:** AGPL-3.0

## Overview

OpenAI/Anthropic compatible API proxy for Kiro (Amazon Q Developer).

Kiro Gateway provides a transparent proxy that translates requests between different API formats while handling authentication, streaming, model resolution, and error handling. It supports multi-account rotation for increased capacity and reliability.

## 🚀 Features

- **Multi-Account Support**: Round-robin rotation across multiple Kiro accounts
- **API Compatibility**: Works with both OpenAI and Anthropic client libraries
- **Load Balancing**: Automatic distribution of requests across accounts
- **Failover Protection**: Automatic rotation to healthy accounts when one fails
- **Model Access**: Access to Claude Sonnet, Haiku, and other models via Kiro API

## Multi-Account Support

Configure multiple Kiro accounts for load balancing and increased capacity:

```bash
# Numbered configuration (recommended)
REFRESH_TOKEN1="first_account_token"
REFRESH_TOKEN2="second_account_token"
REFRESH_TOKEN3="third_account_token"
# Add more as needed
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Run locally
python main.py                    # Default (0.0.0.0:8000)
python main.py --port 9000        # Custom port
```

## 🔧 Authentication

The gateway supports both authentication methods:
- **OpenAI-style**: `Authorization: Bearer YOUR_API_KEY`
- **Anthropic-style**: `x-api-key: YOUR_API_KEY`

## 🎯 API Endpoints

- `GET /` - Basic health check
- `GET /health` - Detailed health check
- `GET /v1/models` - List available models
- `POST /v1/chat/completions` - OpenAI Chat Completions API
- `POST /v1/messages` - Anthropic Messages API

## 🚀 Deployment

This repository includes configuration for automatic deployment to Scalingo:

1. **Procfile**: Defines the web process
2. **runtime.txt**: Specifies Python version
3. **scalingo.json**: Scalingo configuration

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for detailed deployment instructions.

## 📚 Documentation

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Complete deployment instructions
- [README_KIRO_GATEWAY.md](README_KIRO_GATEWAY.md) - Detailed project documentation
- [AGENTS.md](AGENTS.md) - Guide for AI agents working in Kiro Gateway
- [CLAUDE.md](CLAUDE.md) - Project overview and coding guidelines

## 🔄 Multi-Account Benefits

- **Increased Capacity**: Multiple accounts increase total request limits
- **Better Reliability**: Automatic failover between accounts
- **Load Distribution**: Balanced usage across all accounts
- **Automatic Refresh**: Background token refresh keeps accounts active
