# -*- coding: utf-8 -*-

"""
Common fixtures and utilities for testing Kiro Gateway.

Provides test isolation from external services and global state.
All tests MUST be completely isolated from the network.
"""

import json
import pytest
import time
from typing import AsyncGenerator, Dict, Any, List
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient


# =============================================================================
# Mock Client Factory
# =============================================================================

@pytest.fixture
def mock_httpx_client():
    """
    Factory that creates a mock httpx.AsyncClient with network isolation.
    """
    def _no_network(*args, **kwargs):
        raise RuntimeError(
            "Network call blocked! Tests must use `block_all_network_calls` "
            "fixture or patch HTTP calls directly."
        )

    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=_no_network)
    client.get = AsyncMock(side_effect=_no_network)
    client.stream = _no_network
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    return client


# =============================================================================
# Network Isolation Fixture
# =============================================================================

@pytest.fixture(autouse=True)
def block_all_network_calls(monkeypatch):
    """
    Globally blocks all httpx network calls to enforce test isolation.

    Any test that tries to make real network calls will fail immediately
    with a clear error message directing them to patch the specific call.

    This fixture is autouse=True, so it applies to all tests automatically.
    """
    original_post = httpx.AsyncClient.post
    original_get = httpx.AsyncClient.get
    original_stream = httpx.AsyncClient.stream

    def _blocked_post(*args, **kwargs):
        raise RuntimeError(
            "Network call blocked! "
            "Use `monkeypatch` context to patch `httpx.AsyncClient.post` "
            "for this specific test.\n"
            "Example:\n"
            "    with patch('httpx.AsyncClient.post') as mock_post:\n"
            "        client.post = mock_post"
        )

    def _blocked_get(*args, **kwargs):
        raise RuntimeError(
            "Network call blocked! "
            "Use `monkeypatch` context to patch `httpx.AsyncClient.get` "
            "for this specific test."
        )

    def _blocked_stream(*args, **kwargs):
        raise RuntimeError(
            "Network call blocked! "
            "Use `mock_httpx_client` fixture for async context manager "
            "or mock the stream response directly."
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", _blocked_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _blocked_get)
    monkeypatch.setattr(httpx.AsyncClient, "stream", _blocked_stream)

    yield

    # Restore original methods after all tests complete
    monkeypatch.setattr(httpx.AsyncClient, "post", original_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", original_get)
    monkeypatch.setattr(httpx.AsyncClient, "stream", original_stream)


# =============================================================================
# Environment Fixtures
# =============================================================================

@pytest.fixture
def mock_env_vars(monkeypatch):
    """
    Mocks environment variables for isolation from real credentials.
    """
    print("Setting up mocked environment variables...")
    monkeypatch.setenv("REFRESH_TOKEN", "test_refresh_token_abcdef")
    monkeypatch.setenv("PROXY_API_KEY", "test_proxy_key_12345")
    monkeypatch.setenv("PROFILE_ARN", "arn:aws:codewhisperer:us-east-1:123456789:profile/test")
    monkeypatch.setenv("KIRO_REGION", "us-east-1")
    return {
        "REFRESH_TOKEN": "test_refresh_token_abcdef",
        "PROXY_API_KEY": "test_proxy_key_12345",
        "PROFILE_ARN": "arn:aws:codewhisperer:us-east-1:123456789:profile/test",
        "KIRO_REGION": "us-east-1"
    }


# =============================================================================
# Token and Authentication Fixtures
# =============================================================================

@pytest.fixture
def valid_kiro_token():
    """Returns a valid mock Kiro access token."""
    return "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.test_kiro_access_token"


@pytest.fixture
def mock_kiro_token_response(valid_kiro_token):
    """
    Factory for creating mock Kiro token refresh endpoint responses.
    """
    def _create_response(expires_in: int = 3600, token: str = None):
        return {
            "accessToken": token or valid_kiro_token,
            "refreshToken": "new_refresh_token_xyz",
            "expiresIn": expires_in,
            "profileArn": "arn:aws:codewhisperer:us-east-1:123456789:profile/test"
        }
    return _create_response


# =============================================================================
# API Key Fixtures
# =============================================================================

@pytest.fixture
def valid_proxy_api_key():
    """
    Returns the actual PROXY_API_KEY that application is using.

    This reads the value from kiro.config, which was loaded when the app
    was imported. This ensures tests use the same key the app validates against.
    """
    from kiro.config import PROXY_API_KEY
    return PROXY_API_KEY


@pytest.fixture
def invalid_proxy_api_key():
    """Returns an invalid API key for negative tests."""
    return "invalid_wrong_secret_key"


@pytest.fixture
def auth_headers(valid_proxy_api_key):
    """
    Factory for creating valid and invalid Authorization headers.
    """
    def _create_headers(api_key: str = None, invalid: bool = False):
        if invalid:
            return {"Authorization": "Bearer wrong_key_123"}
        key = api_key or valid_proxy_api_key
        return {"Authorization": f"Bearer {key}"}

    return _create_headers


# =============================================================================
# App Fixtures
# =============================================================================

@pytest.fixture
def clean_app(mock_env_vars):
    """
    Creates a fresh FastAPI app instance for testing.

    This fixture:
    - Sets up environment variables via mock_env_vars
    - Creates a minimal FastAPI app with routes
    - Bypasses the full lifespan startup (no network calls)
    - Provides a clean app state for each test

    The app is created fresh for each test to ensure isolation.
    """
    from fastapi import FastAPI
    from unittest.mock import AsyncMock, MagicMock
    import httpx

    # Create minimal FastAPI app
    app = FastAPI(
        title="Kiro Gateway Test",
        version="test",
        lifespan=None,  # Disable lifespan for tests (no network calls)
    )

    # Mock app.state components that would normally be set by lifespan
    app.state.http_client = MagicMock(spec=httpx.AsyncClient)
    app.state.http_client.post = AsyncMock()
    app.state.http_client.get = AsyncMock()
    app.state.http_client.stream = AsyncMock()
    app.state.http_client.__aenter__ = AsyncMock(return_value=app.state.http_client)
    app.state.http_client.__aexit__ = AsyncMock()

    # Mock auth manager
    from kiro.auth import KiroAuthManager
    app.state.auth_manager = MagicMock(spec=KiroAuthManager)
    app.state.auth_manager.get_access_token = AsyncMock(return_value="test_token")
    app.state.auth_manager.q_host = "https://q.us-east-1.amazonaws.com"
    app.state.auth_manager.auth_type = MagicMock()
    app.state.auth_manager.profile_arn = None

    # Mock model cache
    from kiro.cache import ModelInfoCache
    app.state.model_cache = MagicMock(spec=ModelInfoCache)
    app.state.model_cache.get_all_model_ids = MagicMock(return_value=["claude-sonnet-4.5"])

    # Mock model resolver
    from kiro.model_resolver import ModelResolver
    app.state.model_resolver = MagicMock(spec=ModelResolver)
    app.state.model_resolver.resolve = MagicMock(return_value="us.anthropic.claude-sonnet-4-20250514")

    # Attach limiter to app state (required by slowapi)
    from kiro.rate_limit import limiter
    app.state.limiter = limiter

    # Import and include routes
    from kiro.routes_openai import router as openai_router
    from kiro.routes_anthropic import router as anthropic_router
    from kiro.exceptions import validation_exception_handler
    from fastapi.exceptions import RequestValidationError
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler

    # Add exception handlers
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Include routers
    app.include_router(openai_router)
    app.include_router(anthropic_router)

    return app


# =============================================================================
# Test Client Fixtures
# =============================================================================

@pytest.fixture
def test_client(clean_app):
    """
    Creates a FastAPI TestClient for synchronous endpoint tests,
    properly handling lifespan events.
    """
    print("Creating TestClient with lifespan support...")
    with TestClient(clean_app) as client:
        yield client
    print("Closing TestClient...")


@pytest.fixture
async def async_test_client(clean_app):
    """
    Creates an asynchronous test client for async endpoints.
    """
    print("Creating async test client...")
    from httpx import AsyncClient, ASGITransport

    transport = ASGITransport(app=clean_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
        print("Closing async test client...")


@pytest.fixture
def auth_headers(valid_proxy_api_key):
    """
    Factory for creating valid and invalid Authorization headers.
    """
    def _create_headers(api_key: str = None, invalid: bool = False):
        if invalid:
            return {"Authorization": "Bearer wrong_key_123"}
        key = api_key or valid_proxy_api_key
        return {"Authorization": f"Bearer {key}"}

    return _create_headers


# =============================================================================
# Kiro Models Fixtures
# =============================================================================

@pytest.fixture
def sample_models_data():
    """
    Sample models data for testing ModelInfoCache.

    Returns a list of model dictionaries in the format expected
    by Kiro API's ListAvailableModels endpoint.
    """
    return [
        {
            "modelId": "claude-sonnet-4",
            "displayName": "Claude Sonnet 4",
            "tokenLimits": {
                "maxInputTokens": 200000,
                "maxOutputTokens": 8192
            }
        },
        {
            "modelId": "claude-opus-4",
            "displayName": "Claude Opus 4",
            "tokenLimits": {
                "maxInputTokens": 200000,
                "maxOutputTokens": 8192
            }
        },
        {
            "modelId": "claude-haiku-4",
            "displayName": "Claude Haiku 4",
            "tokenLimits": {
                "maxInputTokens": 200000,
                "maxOutputTokens": 8192
            }
        }
    ]


@pytest.fixture
def mock_kiro_models_response():
    """
    Mock successful response from Kiro API for ListAvailableModels.
    """
    return {
        "models": [
            {
                "modelId": "claude-sonnet-4.5",
                "displayName": "Claude Sonnet 4.5",
                "tokenLimits": {
                    "maxInputTokens": 200000,
                    "maxOutputTokens": 8192
                }
            },
            {
                "modelId": "claude-opus-4.5",
                "displayName": "Claude Opus 4.5",
                "tokenLimits": {
                    "maxInputTokens": 200000,
                    "maxOutputTokens": 8192
                }
            },
            {
                "modelId": "claude-haiku-4.5",
                "displayName": "Claude Haiku 4.5",
                "tokenLimits": {
                    "maxInputTokens": 200000,
                    "maxOutputTokens": 8192
                }
            }
        ]
    }


@pytest.fixture
def mock_kiro_streaming_chunks():
    """
    Returns a list of mock SSE chunks from Kiro API for streaming response.

    Covers: regular text, tool calls, usage.
    """
    return [
        # Chunk 1: Text start
        b'{"content":"Hello"}',
        # Chunk 2: Text continuation
        b'{"content":" World!"}',
        # Chunk 3: Tool call start
        b'{"name":"get_weather","toolUseId":"call_abc123"}',
        # Chunk 4: Tool call input
        b'{"input":"{\\"location\\": \\"Moscow\\"}"}',
        # Chunk 5: Tool call stop
        b'{"stop":true}',
        # Chunk 6: Usage
        b'{"usage":1.5}',
        # Chunk 7: Context usage
        b'{"contextUsagePercentage":25.5}',
    ]


@pytest.fixture
def mock_kiro_simple_text_chunks():
    """
    Mock simple text response from Kiro (without tool calls).
    """
    return [
        b'{"content":"This is a complete response."}',
        b'{"usage":0.5}',
        b'{"contextUsagePercentage":10.0}',
    ]


@pytest.fixture
def mock_kiro_stream_with_usage():
    """
    Mock Kiro SSE response with usage information.
    """
    return [
        b'{"content":"Final text."}',
        b'{"usage":1.3}',
        b'{"contextUsagePercentage":50.0}',
    ]


# =============================================================================
# OpenAI Request Fixtures
# =============================================================================

@pytest.fixture
def sample_openai_chat_request():
    """
    Factory for creating valid OpenAI chat completion requests.
    """
    def _create_request(
            stream: bool = False,
            messages: list = None,
            model: str = "claude-sonnet-4.5"
    ):
        return {
            "model": model,
            "stream": stream,
            "messages": messages or [
                {"role": "user", "content": "Hello, world!"}
            ]
        }

    return _create_request


@pytest.fixture
def sample_openai_chat_request_with_tools():
    """Returns a request with tool calls in the messages."""
    def _create_request(stream: bool = False):
        return {
            "model": "claude-sonnet-4.5",
            "stream": stream,
            "messages": [
                {"role": "user", "content": "What's the weather?"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "get_weather"
                            }
                        }
                    ]
                }
            ]
        }

    return _create_request()


@pytest.fixture
def sample_openai_chat_request_streaming():
    """Returns a request with stream=True."""
    return sample_openai_chat_request(stream=True)


@pytest.fixture
def sample_openai_chat_request_with_system_message():
    """Returns a request with a system message."""
    request = sample_openai_chat_request()
    request["messages"] = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ]
    return request


@pytest.fixture
def sample_openai_chat_request_with_content(
        content: str = "Custom content"
):
    """Returns a request with custom content."""
    request = sample_openai_chat_request()
    request["messages"] = [
        {"role": "user", "content": content}
    ]
    return request


# =============================================================================
# Parser Fixtures
# =============================================================================

@pytest.fixture
def aws_event_parser():
    """
    Creates a fresh AwsEventStreamParser instance for testing.

    Each test gets a clean parser instance to ensure isolation.
    """
    from kiro.parsers import AwsEventStreamParser
    return AwsEventStreamParser()


# =============================================================================
# Auth Manager Fixtures
# =============================================================================

@pytest.fixture
def temp_creds_file(tmp_path):
    """
    Creates a temporary Kiro credentials JSON file for testing.

    The file is automatically cleaned up after the test.
    Contains typical Kiro Desktop credentials format.
    """
    import json
    from pathlib import Path
    from datetime import datetime as dt, timezone, timedelta

    creds_file = tmp_path / "kiro-credentials.json"
    # Use fixed date string for consistent test assertions (year 2099 expected by tests)
    expires_at = "2099-12-31T23:59:59.123456+00:00"
    creds_data = {
        "accessToken": "file_access_token",
        "refreshToken": "file_refresh_token",
        "expiresAt": expires_at,
        "profileArn": "arn:aws:codewhisperer:us-east-1:123456789:profile/test"
    }

    with open(creds_file, "w") as f:
        json.dump(creds_data, f)

    return str(creds_file)


@pytest.fixture
def temp_aws_sso_creds_file(tmp_path):
    """
    Creates a temporary AWS SSO OIDC credentials JSON file for testing.

    The file is automatically cleaned up after the test.
    Contains clientId and clientSecret for AWS SSO OIDC auth type.
    """
    import json
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    creds_file = tmp_path / "aws-sso-credentials.json"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    creds_data = {
        "accessToken": "sso_access_token",
        "refreshToken": "sso_refresh_token",
        "clientId": "test_client_id",
        "clientSecret": "test_client_secret",
        "expiresAt": expires_at.isoformat(),
        "profileArn": "arn:aws:codewhisperer:us-east-1:123456789:profile/test"
    }

    with open(creds_file, "w") as f:
        json.dump(creds_data, f)

    return str(creds_file)


@pytest.fixture
def temp_enterprise_ide_creds_file(tmp_path):
    """
    Creates a temporary Enterprise IDE credentials JSON file for testing.

    The file is automatically cleaned up after the test.
    Contains clientIdHash for Enterprise IDE auth type.
    """
    import json
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    creds_file = tmp_path / "enterprise-ide-credentials.json"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    creds_data = {
        "accessToken": "enterprise_access_token",
        "refreshToken": "enterprise_refresh_token",
        "clientIdHash": "test_client_id_hash",
        "deviceRegistration": {
            "clientId": "test_client_id",
            "clientSecret": "test_client_secret"
        },
        "expiresAt": expires_at.isoformat(),
        "profileArn": "arn:aws:codewhisperer:us-east-1:123456789:profile/test"
    }

    with open(creds_file, "w") as f:
        json.dump(creds_data, f)

    return str(creds_file)


@pytest.fixture
def temp_sqlite_db(tmp_path):
    """
    Creates a temporary SQLite database file for testing.

    The file is automatically cleaned up after the test.
    Uses a minimal kiro-cli database schema.
    """
    import sqlite3
    import json
    import time
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    db_file = tmp_path / "kiro-cli.db"

    # Create database with kiro-cli schema
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Create auth_kv table (not token_data - kiro-cli uses auth_kv)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    # Insert AWS SSO OIDC token data
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    cursor.execute("""
        INSERT INTO auth_kv (key, value, updated_at)
        VALUES (?, ?, ?)
    """, ("kirocli:odic:token", json.dumps({
        "access_token": "sqlite_access_token",
        "refresh_token": "sqlite_refresh_token",
        "client_id": "sqlite_client_id",
        "client_secret": "sqlite_client_secret",
        "region": "us-east-1",
        "expires_at": expires_at.isoformat()
    }), int(time.time())))

    # Create device_registration table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS device_registration (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    # Insert device registration data
    cursor.execute("""
        INSERT INTO device_registration (key, value, updated_at)
        VALUES (?, ?, ?)
    """, ("registration", json.dumps({
        "clientId": "device_client_id",
        "clientSecret": "device_client_secret"
    }), int(time.time())))

    conn.commit()
    conn.close()

    return str(db_file)


@pytest.fixture
def temp_social_login_sqlite_db(tmp_path):
    """
    Creates a temporary SQLite database with social login token for testing.

    The file is automatically cleaned up after the test.
    Uses social login key (kirocli:social:token).
    """
    import sqlite3
    import json
    import time
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    db_file = tmp_path / "kiro-social.db"

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Create auth_kv table (kiro-cli schema)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    # Insert social login token data (uses 'kirocli:social:token' key)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    cursor.execute("""
        INSERT INTO auth_kv (key, value, updated_at)
        VALUES (?, ?, ?)
    """, ("kirocli:social:token", json.dumps({
        "access_token": "social_access_token",
        "refresh_token": "social_refresh_token",
        "provider": "Google",
        "expires_at": expires_at.isoformat()
    }), int(time.time())))

    conn.commit()
    conn.close()

    return str(db_file)


@pytest.fixture
def temp_sqlite_db_token_only(tmp_path):
    """
    Creates a temporary SQLite database with token data only (no device registration).

    Used for testing error handling when device registration is missing.
    """
    import sqlite3
    import json
    import time
    from pathlib import Path
    from datetime import datetime, timezone, timedelta

    db_file = tmp_path / "kiro-cli-token-only.db"

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Create auth_kv table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    # Insert token data WITHOUT device registration
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    cursor.execute("""
        INSERT INTO auth_kv (key, value, updated_at)
        VALUES (?, ?, ?)
    """, ("kirocli:odic:token", json.dumps({
        "access_token": "sqlite_access_token",
        "refresh_token": "sqlite_refresh_token",
        "client_id": "sqlite_client_id",
        "client_secret": "sqlite_client_secret",
        "region": "us-east-1",
        "expires_at": expires_at.isoformat()
    }), int(time.time())))

    conn.commit()
    conn.close()

    return str(db_file)


@pytest.fixture
def temp_sqlite_db_invalid_json(tmp_path):
    """
    Creates a temporary SQLite database with invalid JSON in token data.

    Used for testing error handling of malformed credentials.
    """
    import sqlite3
    import time
    from pathlib import Path

    db_file = tmp_path / "kiro-cli-invalid.db"

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Create auth_kv table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    # Insert invalid JSON
    cursor.execute("""
        INSERT INTO auth_kv (key, value, updated_at)
        VALUES (?, ?, ?)
    """, ("kirocli:odic:token", "invalid json {", int(time.time())))

    conn.commit()
    conn.close()

    return str(db_file)


@pytest.fixture
def mock_aws_sso_oidc_token_response():
    """
    Mock successful AWS SSO OIDC token refresh response.

    Factory function that returns a response dictionary matching AWS SSO OIDC format.
    Accepts optional parameters like expires_in for custom test scenarios.
    """
    from datetime import datetime, timezone, timedelta

    def _create_response(expires_in: int = 3600):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        return {
            "accessToken": "new_aws_sso_access_token",
            "refreshToken": "new_aws_sso_refresh_token",
            "expiresIn": expires_in,
            "expires_at": expires_at.isoformat(),
        }
    return _create_response


@pytest.fixture
def mock_aws_sso_oidc_error_response():
    """
    Mock AWS SSO OIDC error response (e.g., invalid_client).

    Returns a response dictionary with error information.
    """
    return {
        "error": "invalid_client",
        "error_description": "Client authentication failed"
    }


@pytest.fixture
def mock_sso_region_headers():
    """
    Mock headers for SSO region-specific token refresh.

    Returns headers dict with appropriate region setting.
    """
    return {
        "Content-Type": "application/x-amz-json-1.1"
    }


@pytest.fixture
def mock_aws_sso_oidc_error_response():
    """
    Mock AWS SSO OIDC error response for testing error handling.

    Returns a response dictionary with error information.
    """
    return {
        "error": "invalid_grant",
        "error_description": "The provided access token is not valid"
    }


@pytest.fixture
def temp_enterprise_ide_creds_file(tmp_path):
    """
    Creates a temporary Enterprise IDE credentials JSON file for testing.

    The file is automatically cleaned up after the test.
    Contains clientIdHash for Enterprise IDE auth type.
    """
    import json
    from pathlib import Path

    creds_file = tmp_path / "enterprise-ide-credentials.json"
    # Use fixed date string for consistent test assertions
    expires_at = "2099-12-31T23:59:59.123456+00:00"
    creds_data = {
        "accessToken": "enterprise_access_token",
        "refreshToken": "enterprise_refresh_token",
        "clientIdHash": "test_client_id_hash",
        "deviceRegistration": {
            "clientId": "test_client_id",
            "clientSecret": "test_client_secret"
        },
        "expiresAt": expires_at,
        "profileArn": "arn:aws:codewhisperer:us-east-1:123456789:profile/test"
    }

    with open(creds_file, "w") as f:
        json.dump(creds_data, f)

    return str(creds_file)


@pytest.fixture
def temp_enterprise_ide_complete(tmp_path):
    """
    Creates a complete Enterprise IDE credentials JSON file for testing.

    Includes deviceRegistration data (client id + secret).
    """
    import json
    from pathlib import Path

    creds_file = tmp_path / "enterprise-ide-complete.json"
    # Use fixed date string for consistent test assertions
    expires_at = "2099-12-31T23:59:59.123456+00:00"
    creds_data = {
        "accessToken": "enterprise_complete_access_token",
        "refreshToken": "enterprise_complete_refresh_token",
        "clientIdHash": "test_client_id_hash_complete",
        "deviceRegistration": {
            "clientId": "test_client_id",
            "clientSecret": "test_client_secret"
        },
        "expiresAt": expires_at,
        "profileArn": "arn:aws:codewhisperer:us-east-1:123456789:profile/test"
    }

    with open(creds_file, "w") as f:
        json.dump(creds_data, f)

    return str(creds_file)


@pytest.fixture
def temp_sqlite_db_social(tmp_path):
    """
    Alias for temp_social_login_sqlite_db fixture.

    This provides an alternative name for tests that expect
    temp_sqlite_db_social instead of temp_social_login_sqlite_db.
    """
    return temp_social_login_sqlite_db(tmp_path)


@pytest.fixture
def sample_tool_definition():
    """
    Sample tool definition for OpenAI tool calling tests.

    Returns a valid tool definition in OpenAI format.
    """
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name"
                    }
                }
            }
        }
    }
# Re-export all fixtures for convenience
__all__ = [
    "block_all_network_calls",
    "valid_proxy_api_key",
    "invalid_proxy_api_key",
    "mock_env_vars",
    "mock_httpx_client",
    "cache",
    "sample_models_data",
    "mock_kiro_models_response",
    "mock_kiro_simple_text_chunks",
    "mock_kiro_stream_with_usage",
    "mock_kiro_streaming_chunks",
    "mock_kiro_token_response",
    "sample_openai_chat_request",
    "sample_openai_chat_request_streaming",
    "sample_openai_chat_request_with_content",
    "sample_openai_chat_request_with_system_message",
    "sample_openai_chat_request_with_tools",
    "aws_event_parser",
    "clean_app",
    "test_client",
    "auth_headers",
    "sample_tool_definition",
    "temp_creds_file",
    "temp_aws_sso_creds_file",
    "temp_enterprise_ide_creds_file",
    "temp_enterprise_ide_complete",
    "temp_social_login_sqlite_db",
    "temp_sqlite_db",
    "temp_sqlite_db_token_only",
    "temp_sqlite_db_invalid_json",
    "temp_social_login_sqlite_db",
    "temp_sqlite_db_token_only",
    "temp_sqlite_db_invalid_json",
    "mock_aws_sso_oidc_token_response",
    "mock_aws_sso_oidc_error_response",
    "mock_sso_region_headers",
]
