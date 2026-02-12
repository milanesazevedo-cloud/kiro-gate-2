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
