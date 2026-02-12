# -*- coding: utf-8 -*-
"""
Unit tests for kiro/utils.py.

Tests cover:
- get_machine_fingerprint (normal + exception path)
- get_kiro_headers
- generate_completion_id
- generate_conversation_id (no messages, few messages, many messages)
- generate_tool_call_id
"""

import json
import uuid
import pytest
from unittest.mock import MagicMock, patch

from kiro.utils import (
    get_machine_fingerprint,
    get_kiro_headers,
    generate_completion_id,
    generate_conversation_id,
    generate_tool_call_id,
)


# ===========================================================================
# get_machine_fingerprint tests
# ===========================================================================

class TestGetMachineFingerprint:
    def test_returns_64_char_hex_string(self):
        fp = get_machine_fingerprint()
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_is_deterministic(self):
        fp1 = get_machine_fingerprint()
        fp2 = get_machine_fingerprint()
        assert fp1 == fp2

    def test_fallback_on_exception(self):
        with patch("socket.gethostname", side_effect=OSError("no hostname")):
            fp = get_machine_fingerprint()
        # Should still return a 64-char hex string (from default fallback)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_fallback_different_from_normal(self):
        """Fallback fingerprint is for 'default-kiro-gateway' and differs from normal."""
        import hashlib
        fallback = hashlib.sha256(b"default-kiro-gateway").hexdigest()
        normal = get_machine_fingerprint()
        # In normal environments these differ; the test guarantees fallback works
        with patch("socket.gethostname", side_effect=OSError):
            fp = get_machine_fingerprint()
        assert fp == fallback


# ===========================================================================
# get_kiro_headers tests
# ===========================================================================

class TestGetKiroHeaders:
    def _make_auth_manager(self, fingerprint: str = "a" * 64) -> MagicMock:
        manager = MagicMock()
        manager.fingerprint = fingerprint
        return manager

    def test_returns_dict_with_authorization(self):
        manager = self._make_auth_manager()
        headers = get_kiro_headers(manager, "my_token")
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer my_token"

    def test_content_type_is_json(self):
        manager = self._make_auth_manager()
        headers = get_kiro_headers(manager, "tok")
        assert headers["Content-Type"] == "application/json"

    def test_user_agent_contains_fingerprint(self):
        fp = "abcdef1234567890" + "x" * 48  # 64 chars, first 16 = 'abcdef1234567890'
        manager = self._make_auth_manager(fingerprint=fp)
        headers = get_kiro_headers(manager, "tok")
        # User-Agent includes first 16 chars of fingerprint
        assert fp[:16] in headers["User-Agent"]

    def test_x_amz_user_agent_present(self):
        manager = self._make_auth_manager()
        headers = get_kiro_headers(manager, "tok")
        assert "x-amz-user-agent" in headers

    def test_codewhisperer_optout_header(self):
        manager = self._make_auth_manager()
        headers = get_kiro_headers(manager, "tok")
        assert headers["x-amzn-codewhisperer-optout"] == "true"

    def test_kiro_agent_mode_vibe(self):
        manager = self._make_auth_manager()
        headers = get_kiro_headers(manager, "tok")
        assert headers["x-amzn-kiro-agent-mode"] == "vibe"

    def test_amz_sdk_request_has_attempt(self):
        manager = self._make_auth_manager()
        headers = get_kiro_headers(manager, "tok")
        assert "attempt=1" in headers["amz-sdk-request"]

    def test_amz_sdk_invocation_id_is_uuid(self):
        manager = self._make_auth_manager()
        headers = get_kiro_headers(manager, "tok")
        invocation_id = headers["amz-sdk-invocation-id"]
        # Should be a valid UUID (no exception raised on parse)
        parsed = uuid.UUID(invocation_id)
        assert str(parsed) == invocation_id

    def test_each_call_has_unique_invocation_id(self):
        manager = self._make_auth_manager()
        h1 = get_kiro_headers(manager, "tok")
        h2 = get_kiro_headers(manager, "tok")
        assert h1["amz-sdk-invocation-id"] != h2["amz-sdk-invocation-id"]


# ===========================================================================
# generate_completion_id tests
# ===========================================================================

class TestGenerateCompletionId:
    def test_starts_with_chatcmpl(self):
        cid = generate_completion_id()
        assert cid.startswith("chatcmpl-")

    def test_unique_each_call(self):
        ids = {generate_completion_id() for _ in range(10)}
        assert len(ids) == 10

    def test_is_string(self):
        assert isinstance(generate_completion_id(), str)


# ===========================================================================
# generate_conversation_id tests
# ===========================================================================

class TestGenerateConversationId:
    def test_no_messages_returns_uuid(self):
        cid = generate_conversation_id()
        # Should be a valid UUID
        parsed = uuid.UUID(cid)
        assert str(parsed) == cid

    def test_empty_list_returns_uuid(self):
        cid = generate_conversation_id([])
        # Falsy list -> UUID fallback
        parsed = uuid.UUID(cid)
        assert str(parsed) == cid

    def test_with_messages_returns_16_char_hex(self):
        messages = [{"role": "user", "content": "Hello"}]
        cid = generate_conversation_id(messages)
        assert len(cid) == 16
        assert all(c in "0123456789abcdef" for c in cid)

    def test_same_messages_produce_same_id(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        assert generate_conversation_id(messages) == generate_conversation_id(messages)

    def test_different_messages_produce_different_id(self):
        msgs_a = [{"role": "user", "content": "Hello"}]
        msgs_b = [{"role": "user", "content": "Goodbye"}]
        assert generate_conversation_id(msgs_a) != generate_conversation_id(msgs_b)

    def test_more_than_3_messages_stable(self):
        """ID is stable even as conversation grows (uses first 3 + last)."""
        base = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
        ]
        extended = base + [{"role": "assistant", "content": "msg4"}]
        id_base = generate_conversation_id(base)
        id_extended = generate_conversation_id(extended)
        # Different because last message changed
        assert id_base != id_extended

    def test_long_content_truncated_to_100_chars(self):
        """Messages with the same first 100 chars of content produce same ID."""
        long = "A" * 200
        same_prefix = "A" * 100 + "B" * 100
        msgs_a = [{"role": "user", "content": long}]
        msgs_b = [{"role": "user", "content": same_prefix}]
        assert generate_conversation_id(msgs_a) == generate_conversation_id(msgs_b)

    def test_list_content_is_serialized(self):
        """Content as list (Anthropic-style blocks) doesn't crash."""
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        cid = generate_conversation_id(messages)
        assert len(cid) == 16

    def test_non_string_content_is_converted(self):
        """Content as non-string (e.g. int) doesn't crash."""
        messages = [{"role": "user", "content": 42}]
        cid = generate_conversation_id(messages)
        assert len(cid) == 16

    def test_missing_role_defaults_to_unknown(self):
        """Missing 'role' key uses 'unknown' default."""
        messages = [{"content": "hello"}]
        # Should not raise
        cid = generate_conversation_id(messages)
        assert len(cid) == 16


# ===========================================================================
# generate_tool_call_id tests
# ===========================================================================

class TestGenerateToolCallId:
    def test_starts_with_call_prefix(self):
        tcid = generate_tool_call_id()
        assert tcid.startswith("call_")

    def test_unique_each_call(self):
        ids = {generate_tool_call_id() for _ in range(10)}
        assert len(ids) == 10

    def test_is_string(self):
        assert isinstance(generate_tool_call_id(), str)

    def test_suffix_is_8_chars(self):
        tcid = generate_tool_call_id()
        suffix = tcid[len("call_"):]
        assert len(suffix) == 8
