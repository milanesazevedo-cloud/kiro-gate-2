# -*- coding: utf-8 -*-
"""
Unit tests for MultiTokenAuthManager.

Tests cover:
- Initialization
- Token rotation logic
- Exponential backoff
- _rotate_to_next_token return values
- get_token_status
- All-tokens-failed scenario
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from kiro.auth_multi import MultiTokenAuthManager, TokenInfo


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def three_token_manager():
    """MultiTokenAuthManager with 3 healthy tokens."""
    return MultiTokenAuthManager(
        refresh_tokens=["token_a", "token_b", "token_c"],
        region="us-east-1",
    )


@pytest.fixture
def single_token_manager():
    """MultiTokenAuthManager with a single token."""
    return MultiTokenAuthManager(
        refresh_tokens=["only_token"],
        region="us-east-1",
    )


@pytest.fixture
def empty_token_manager():
    """MultiTokenAuthManager with no tokens."""
    return MultiTokenAuthManager(refresh_tokens=[], region="us-east-1")


# ===========================================================================
# Initialization tests
# ===========================================================================

class TestMultiTokenAuthManagerInit:
    def test_initializes_with_multiple_tokens(self, three_token_manager):
        assert len(three_token_manager._tokens) == 3
        assert three_token_manager._active_index == 0

    def test_initializes_empty_pool(self, empty_token_manager):
        assert len(empty_token_manager._tokens) == 0
        assert empty_token_manager._active_index == -1

    def test_filters_empty_strings(self):
        manager = MultiTokenAuthManager(
            refresh_tokens=["valid", "", "  ", "also_valid"],
            region="us-east-1",
        )
        # empty and whitespace-only tokens should be skipped (empty string is falsy)
        # "  " is truthy so it will be included; only "" is filtered
        assert any(t.refresh_token == "valid" for t in manager._tokens)
        assert any(t.refresh_token == "also_valid" for t in manager._tokens)
        assert not any(t.refresh_token == "" for t in manager._tokens)

    def test_tokens_start_as_not_failed(self, three_token_manager):
        for token in three_token_manager._tokens:
            assert token.is_failed is False
            assert token.failure_count == 0

    def test_profile_arn_stored(self):
        arn = "arn:aws:codewhisperer:us-east-1:123:profile/test"
        manager = MultiTokenAuthManager(
            refresh_tokens=["tok"],
            profile_arn=arn,
            region="us-east-1",
        )
        assert manager.profile_arn == arn

    def test_region_stored(self):
        manager = MultiTokenAuthManager(refresh_tokens=["tok"], region="eu-west-1")
        assert manager.region == "eu-west-1"


# ===========================================================================
# _rotate_to_next_token tests
# ===========================================================================

class TestRotateToNextToken:
    def test_returns_false_when_no_tokens(self, empty_token_manager):
        result = empty_token_manager._rotate_to_next_token()
        assert result is False

    def test_returns_true_on_successful_rotation(self, three_token_manager):
        result = three_token_manager._rotate_to_next_token()
        assert result is True
        assert three_token_manager._active_index == 1

    def test_rotates_cyclically(self, three_token_manager):
        three_token_manager._rotate_to_next_token()  # 0 -> 1
        three_token_manager._rotate_to_next_token()  # 1 -> 2
        three_token_manager._rotate_to_next_token()  # 2 -> 0
        assert three_token_manager._active_index == 0

    def test_skips_tokens_in_backoff(self, three_token_manager):
        # Mark token 1 (index 1) as recently failed
        three_token_manager._tokens[1].is_failed = True
        three_token_manager._tokens[1].failure_count = 1
        three_token_manager._tokens[1].last_failure = datetime.now(timezone.utc)

        result = three_token_manager._rotate_to_next_token()
        # Should skip index 1, go to index 2
        assert result is True
        assert three_token_manager._active_index == 2

    def test_returns_false_when_all_tokens_in_backoff(self, three_token_manager):
        now = datetime.now(timezone.utc)
        for token in three_token_manager._tokens:
            token.is_failed = True
            token.failure_count = 1
            token.last_failure = now

        result = three_token_manager._rotate_to_next_token()
        # All in backoff -> resets failures and returns False
        assert result is False

    def test_resets_failures_when_all_in_backoff(self, three_token_manager):
        now = datetime.now(timezone.utc)
        for token in three_token_manager._tokens:
            token.is_failed = True
            token.failure_count = 1
            token.last_failure = now

        three_token_manager._rotate_to_next_token()

        # Failures should be reset
        for token in three_token_manager._tokens:
            assert token.is_failed is False

    def test_respects_backoff_window_expired(self, three_token_manager):
        # Token 1 failed more than 5 minutes ago (backoff window for failure_count=1)
        three_token_manager._tokens[1].is_failed = True
        three_token_manager._tokens[1].failure_count = 1
        three_token_manager._tokens[1].last_failure = (
            datetime.now(timezone.utc) - timedelta(minutes=6)
        )

        result = three_token_manager._rotate_to_next_token()
        assert result is True
        assert three_token_manager._active_index == 1


# ===========================================================================
# Token status tests
# ===========================================================================

class TestGetTokenStatus:
    def test_returns_status_for_all_tokens(self, three_token_manager):
        status = three_token_manager.get_token_status()
        assert len(status) == 3

    def test_active_token_marked_correctly(self, three_token_manager):
        status = three_token_manager.get_token_status()
        assert status[0]["active"] is True
        assert status[1]["active"] is False
        assert status[2]["active"] is False

    def test_failed_token_reflected_in_status(self, three_token_manager):
        three_token_manager._tokens[1].is_failed = True
        three_token_manager._tokens[1].failure_count = 2
        status = three_token_manager.get_token_status()
        assert status[1]["is_failed"] is True
        assert status[1]["failure_count"] == 2

    def test_empty_manager_returns_empty_list(self, empty_token_manager):
        assert empty_token_manager.get_token_status() == []


# ===========================================================================
# is_token_expiring_soon tests
# ===========================================================================

class TestIsTokenExpiringSoon:
    def test_returns_true_when_no_token(self, empty_token_manager):
        assert empty_token_manager.is_token_expiring_soon() is True

    def test_returns_false_when_token_has_long_validity(self, single_token_manager):
        single_token_manager._tokens[0].expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        )
        assert single_token_manager.is_token_expiring_soon() is False

    def test_returns_true_when_token_expired(self, single_token_manager):
        single_token_manager._tokens[0].expires_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        assert single_token_manager.is_token_expiring_soon() is True


# ===========================================================================
# get_access_token tests (async)
# ===========================================================================

class TestGetAccessToken:
    @pytest.mark.asyncio
    async def test_returns_existing_valid_token(self, single_token_manager):
        single_token_manager._tokens[0].access_token = "valid_access_token"
        single_token_manager._tokens[0].expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        )

        with patch.object(
            single_token_manager, "_refresh_token_request", new_callable=AsyncMock
        ) as mock_refresh:
            result = await single_token_manager.get_access_token()
            mock_refresh.assert_not_called()
            assert result == "valid_access_token"

    @pytest.mark.asyncio
    async def test_refreshes_when_no_access_token(self, single_token_manager):
        async def set_token():
            single_token_manager._tokens[0].access_token = "refreshed_token"

        with patch.object(
            single_token_manager,
            "_refresh_token_request",
            side_effect=set_token,
        ):
            single_token_manager._tokens[0].expires_at = (
                datetime.now(timezone.utc) + timedelta(hours=1)
            )
            result = await single_token_manager.get_access_token()
            assert result == "refreshed_token"

    @pytest.mark.asyncio
    async def test_raises_when_no_tokens(self, empty_token_manager):
        with pytest.raises(ValueError, match="No refresh tokens available"):
            await empty_token_manager.get_access_token()


# ===========================================================================
# refresh_all_tokens tests (async)
# ===========================================================================

class TestRefreshAllTokens:
    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_tokens(self, empty_token_manager):
        result = await empty_token_manager.refresh_all_tokens()
        assert result == {}

    @pytest.mark.asyncio
    async def test_refreshes_all_tokens_concurrently(self, three_token_manager):
        async def mock_refresh(index: int) -> bool:
            return True

        with patch.object(
            three_token_manager,
            "_refresh_single_token",
            side_effect=mock_refresh,
        ):
            results = await three_token_manager.refresh_all_tokens()
            assert len(results) == 3
            assert all(v == "healthy" for v in results.values())

    @pytest.mark.asyncio
    async def test_marks_failed_tokens_correctly(self, three_token_manager):
        async def mock_refresh(index: int) -> bool:
            return index != 1  # token_2 fails

        with patch.object(
            three_token_manager,
            "_refresh_single_token",
            side_effect=mock_refresh,
        ):
            results = await three_token_manager.refresh_all_tokens()
            assert results["token_1"] == "healthy"
            assert results["token_2"] == "failed"
            assert results["token_3"] == "healthy"
