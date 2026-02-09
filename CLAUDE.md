# CLAUDE.md

**Project:** Kiro Gateway - OpenAI/Anthropic Compatible API Proxy for Kiro
**Language:** Python 3.10+ | **Framework:** FastAPI
**License:** AGPL-3.0

---

## Project Overview

Kiro Gateway is a transparent proxy server that provides OpenAI-compatible and Anthropic-compatible APIs for Kiro (Amazon Q Developer / AWS CodeWhisperer). It translates requests between different API formats while handling authentication, streaming, model resolution, and error handling.

**Primary Use Cases:**
- Use Claude models from Kiro with Claude Code, OpenCode, Cursor, Cline, Roo Code, and other OpenAI/Anthropic compatible tools
- Seamless model switching between Kiro and OpenAI/Anthropic APIs
- Extended thinking support via fake reasoning injection

---

## Architecture

### Directory Structure

```
kiro-gateway/
├── main.py                    # Application entry point
├── kiro/                      # Main package
│   ├── auth.py               # KiroAuthManager - token lifecycle management
│   ├── cache.py              # ModelInfoCache - model metadata caching
│   ├── config.py             # Configuration and constants (471 lines)
│   ├── model_resolver.py     # Dynamic model resolution system
│   ├── http_client.py        # HTTP client with retry logic
│   ├── routes_openai.py      # OpenAI API endpoints
│   ├── routes_anthropic.py   # Anthropic API endpoints
│   ├── converters_core.py    # Shared conversion logic
│   ├── converters_openai.py  # OpenAI format converters
│   ├── converters_anthropic.py # Anthropic format converters
│   ├── streaming_core.py     # Shared streaming logic
│   ├── streaming_openai.py   # OpenAI streaming
│   ├── streaming_anthropic.py # Anthropic streaming
│   ├── parsers.py            # AWS SSE stream parsers
│   ├── thinking_parser.py    # Thinking block parser (FSM)
│   ├── models_openai.py      # OpenAI Pydantic models
│   ├── models_anthropic.py   # Anthropic Pydantic models
│   ├── network_errors.py     # Network error classification
│   ├── exceptions.py         # Exception handlers
│   ├── debug_logger.py       # Debug logging system
│   ├── debug_middleware.py   # Debug middleware
│   ├── tokenizer.py          # Token counting (tiktoken)
│   ├── utils.py              # Helper utilities
│   ├── kiro_errors.py        # Kiro API error enhancement
│   ├── truncation_recovery.py # Truncation recovery system
│   └── truncation_state.py   # Truncation state cache
├── tests/                    # Test suite
│   ├── conftest.py           # Shared fixtures and network isolation
│   ├── unit/                 # Unit tests (30+ test files)
│   └── integration/          # Integration tests
└── docs/                     # Multi-language documentation
```

### Architecture Patterns

**Layered Modular Architecture:**
1. **Routes Layer** - FastAPI endpoints, authentication, request validation
2. **Converters Layer** - Format translation (OpenAI/Anthropic -> Kiro)
3. **Streaming Layer** - SSE stream processing (Kiro -> OpenAI/Anthropic)
4. **Core Services** - Auth, HTTP client, model resolution, caching
5. **Parsers** - AWS event stream parsing, thinking block extraction
6. **Models** - Pydantic models for validation

### Key Principles

- **Transparency First:** Preserves user's original intent
- **Minimal Intervention:** Surgical changes only when necessary
- **User Control:** All optional enhancements configurable
- **Systems Over Patches:** Build systems that handle entire classes of issues
- **Paranoid Testing:** Test edge cases, error scenarios, boundary conditions

---

## Configuration

### Environment Variables

**Required:**
- `PROXY_API_KEY` - Password to protect the proxy server

**Authentication (choose one):**
- `KIRO_CREDS_FILE` - Path to JSON credentials file from Kiro IDE
- `REFRESH_TOKEN` - Direct refresh token from Kiro IDE traffic
- `KIRO_CLI_DB_FILE` - Path to kiro-cli SQLite database

**Optional Settings:**
- `PROFILE_ARN` - AWS CodeWhisperer profile ARN
- `KIRO_REGION` - AWS region (default: us-east-1)
- `SERVER_HOST` - Server host (default: 0.0.0.0)
- `SERVER_PORT` - Server port (default: 8000)
- `VPN_PROXY_URL` - VPN/Proxy URL for restricted networks
- `FIRST_TOKEN_TIMEOUT` - Timeout for first token (default: 15s)
- `STREAMING_READ_TIMEOUT` - Read timeout for streaming (default: 300s)
- `FAKE_REASONING_ENABLED` - Enable fake reasoning (default: true)
- `FAKE_REASONING_MAX_TOKENS` - Max thinking length (default: 4000)
- `FAKE_REASONING_HANDLING` - How to handle thinking blocks
- `TRUNCATION_RECOVERY` - Enable truncation recovery (default: true)
- `LOG_LEVEL` - Log level (default: INFO)
- `DEBUG_MODE` - Debug mode: off/errors/all (default: off)

**Configuration Priority:** CLI args > Environment variables > Defaults

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Simple health check |
| `/health` | GET | Detailed health check |
| `/v1/models` | GET | List available models |
| `/v1/chat/completions` | POST | OpenAI Chat Completions API |
| `/v1/messages` | POST | Anthropic Messages API |

**Authentication Headers:**
```bash
# OpenAI format
Authorization: Bearer {PROXY_API_KEY}

# Anthropic format
x-api-key: {PROXY_API_KEY}
```

---

## Development Commands

### Setup

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

### Docker

```bash
# Build and run
docker build -t kiro-gateway .
docker run -d -p 8000:8000 --env-file .env kiro-gateway

# Using docker-compose (recommended)
docker-compose up -d
docker-compose logs -f
```

### Testing

```bash
# All tests
pytest -v

# Unit tests only
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v

# With coverage
pytest --cov=kiro --cov-report=html

# Watch mode (development)
pytest-watch -v
```

**Testing Philosophy:** Complete network isolation - all tests are mocked, no real network calls. The global fixture `block_all_network_calls` in `conftest.py` enforces this.

---

## Code Style

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Functions/Variables | snake_case | `authenticate_request()` |
| Classes | PascalCase | `KiroAuthManager` |
| Constants | UPPER_SNAKE_CASE | `TOKEN_REFRESH_THRESHOLD` |
| Private members | _leading_underscore | `_refresh_token()` |

### Required Standards

1. **Type Hints:** ALL functions must have type annotations
2. **Docstrings:** Google style with Args/Returns/Raises
3. **Logging:** Use loguru at key decision points
4. **Error Handling:** Catch specific exceptions, add context
5. **No Placeholders:** Every function must be complete and production-ready

### Log Levels

- `DEBUG`: Detailed diagnostic information
- `INFO`: General informational messages
- `WARNING`: Non-critical issues
- `ERROR`: Failures

### Error Handling Pattern

```python
try:
    result = await some_operation()
except SpecificException as e:
    logger.error(f"Operation failed: {e}")
    raise HTTPException(status_code=500, detail="User-friendly message")
```

**Rules:**
- Never use bare `except:` - catch specific exceptions
- Add context to all error messages
- User-friendly error messages for API-facing errors
- Detailed logging for internal errors

---

## Multi-Account Support

### Configuration

```bash
# Multi-account mode: comma-separated refresh tokens
REFRESH_TOKEN="token1,token2,token3,token4,token5"

# Alternative: numbered variables
REFRESH_TOKEN1="token1"
REFRESH_TOKEN2="token2"
REFRESH_TOKEN3="token3"

# Background refresh interval (seconds)
BACKGROUND_REFRESH_INTERVAL=1800
```

### Features

- **Round-robin rotation** between accounts
- **Exponential backoff** for failed tokens (5min → 30min → 2h)
- **Background refresh** keeps all tokens healthy
- **Health monitoring** via `/v1/accounts/status` endpoint

### Usage

```bash
# Check account status
curl http://localhost:8000/v1/accounts/status \
  -H "Authorization: Bearer my-secret"

# Response:
# {
#   "mode": "multi-account",
#   "total_tokens": 5,
#   "healthy_tokens": 5,
#   "accounts": [...]
# }
```

### Health Check

```bash
curl http://localhost:8000/health
```

---

## Dependencies

### Core Dependencies

| Package | Purpose |
|---------|---------|
| fastapi | Web framework |
| uvicorn[standard] | ASGI server |
| httpx | Async HTTP client |
| loguru | Logging |
| python-dotenv | Configuration |
| tiktoken | Token counting |

### Dev Dependencies

| Package | Purpose |
|---------|---------|
| pytest | Testing framework |
| pytest-asyncio | Async test support |
| pytest-cov | Coverage reporting |
| pytest-watch | Watch mode |

---

## Testing Requirements

### Coverage Target: 80%+

### Test Types Required

1. **Unit Tests** - Individual functions, utilities, modules
2. **Integration Tests** - API endpoints, auth flow, converters

### Test Organization

- Place unit tests in `tests/unit/`
- Place integration tests in `tests/integration/`
- Use `pytest.mark` for test categorization
- Naming: `test_*.py` files

### Test Fixtures

All tests use network isolation via `conftest.py`:
- `block_all_network_calls` - Prevents real network calls
- Use mocks for external services

---

## Security

### Authentication

**KiroAuthManager** handles token lifecycle:
- **Auth Types:**
  - `KIRO_DESKTOP` - Kiro IDE credentials (default)
  - `AWS_SSO_OIDC` - AWS SSO credentials from kiro-cli
- **Features:**
  - Auto-detects auth type based on credentials
  - Thread-safe token refresh with asyncio.Lock
  - Automatic refresh before expiration (TOKEN_REFRESH_THRESHOLD: 600s)

### Proxy API Key

- Simple Bearer token authentication on all endpoints
- Configured via `PROXY_API_KEY` environment variable
- NEVER log or expose this value

### Secret Management

```python
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ["PROXY_API_KEY"]  # Raises KeyError if missing
if not api_key:
    raise ValueError("PROXY_API_KEY not configured")
```

---

## Git Workflow

### Commit Message Format

```
<type>: <description>

<optional body>
```

**Types:** feat, fix, refactor, docs, test, chore, perf, ci

### Branch Naming

- Features: `feature/description`
- Bug fixes: `fix/description`
- Hotfixes: `hotfix/description`

### Pull Request Workflow

1. Create feature branch from main
2. Write tests first (TDD approach)
3. Implement changes
4. Ensure 80%+ coverage
5. Run all tests with `pytest -v`
6. Create PR with description

---

## External Services

### Kiro API Endpoints

- Token refresh: `https://prod.{region}.auth.desktop.kiro.dev/refreshToken`
- AWS SSO OIDC: `https://oidc.{region}.amazonaws.com/token`
- Main API: `https://q.{region}.amazonaws.com`
- ListAvailableModels: `https://q.{region}.amazonaws.com`

### Supported Features

- Extended Thinking (Fake Reasoning via tag injection)
- Vision Support
- Tool Calling
- Streaming (SSE)
- HTTP/SOCKS5 Proxy support
- VPN/Proxy for restricted networks

---

## Deployment Contínuo

O projeto já está configurado para rodar continuamente com **auto-restart**:

### Docker Compose (Recomendado)

```bash
# Iniciar com auto-restart
docker-compose up -d

# Verificar status
docker-compose ps

# Ver logs
docker-compose logs -f

# Reiniciar
docker-compose restart

# Parar
docker-compose down
```

### Auto-Restart Configurado

O `docker-compose.yml` já possui:
- `restart: unless-stopped` - Reinicia automaticamente se o container cair
- `healthcheck` - Monitora saúde do serviço
- `deploy.resources` - Limites de CPU e memória

### Para Servidor Linux (Systemd)

Crie `/etc/systemd/system/kiro-gateway.service`:

```ini
[Unit]
Description=Kiro Gateway Proxy
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/path/to/kiro-gateway
ExecStart=/usr/bin/docker-compose up -d
ExecStop=/usr/bin/docker-compose down

[Install]
WantedBy=multi-user.target
```

```bash
# Ativar e iniciar
sudo systemctl enable kiro-gateway
sudo systemctl start kiro-gateway

# Ver status
sudo systemctl status kiro-gateway

# Ver logs
journalctl -u kiro-gateway -f
```

### Verificação de Saúde

O endpoint `/health` pode ser usado para monitoramento:

```bash
# Health check
curl http://localhost:8000/health

# Resposta esperada:
# {"status":"healthy"}
```

---

## Docker

### Dockerfile (Single-Stage)

- Base: `python:3.10-slim`
- Non-root user: `kiro` for security
- Health check: `httpx.get('http://localhost:8000/health')`

### docker-compose.yml

- Service: `kiro-gateway`
- Port: `8000:8000`
- Resource limits: 2 CPU cores, 1GB memory
- Volume mounts for credentials and debug logs

---

## Additional Documentation

| File | Purpose |
|------|---------|
| `README.md` | User-facing documentation |
| `AGENTS.md` | AI agent guidelines |
| `CONTRIBUTING.md` | Contribution guidelines |
| `docs/en/ARCHITECTURE.md` | Architecture documentation |

---

## Key Files Reference

### Critical Core Modules

- `kiro/config.py` - All configuration and constants (471 lines)
- `kiro/auth.py` - Authentication and token management
- `kiro/model_resolver.py` - Model resolution logic
- `kiro/http_client.py` - HTTP client with retry logic

### API Routes

- `kiro/routes_openai.py` - OpenAI compatible endpoints
- `kiro/routes_anthropic.py` - Anthropic compatible endpoints

### Converters & Streaming

- `kiro/converters_core.py` - Shared conversion logic
- `kiro/streaming_core.py` - Shared streaming logic
- `kiro/streaming_openai.py` - OpenAI streaming
- `kiro/streaming_anthropic.py` - Anthropic streaming

---

## Common Tasks

### Adding a New API Endpoint

1. Add route in `routes_openai.py` or `routes_anthropic.py`
2. Create converter in `converters_*.py` if needed
3. Add streaming handler in `streaming_*.py` if needed
4. Write unit tests in `tests/unit/`
5. Update Pydantic models in `models_*.py`

### Modifying Configuration

1. Update `config.py` with new constant/variable
2. Add to `.env.example` with documentation
3. Update `main.py` CLI argument parsing if needed

### Adding Tests

1. Follow TDD: Write test first
2. Mock all external calls (enforced by `block_all_network_calls`)
3. Place in appropriate directory (`unit/` or `integration/`)
4. Run with `pytest -v` to verify

---

## Agent Guidelines

When working on this project, AI agents should:

1. **Understand Before Acting:** Read existing code patterns before modifying
2. **Preserve Architecture:** Follow the layered modular pattern
3. **Complete Features:** No placeholders - implement fully
4. **Test Thoroughly:** Write tests before implementation
5. **Document Changes:** Update relevant docs
6. **Network Isolation:** Never make real network calls in tests
7. **Type Safety:** Always use type hints
8. **Error Context:** Provide meaningful error messages
