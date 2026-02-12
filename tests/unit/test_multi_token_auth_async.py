# -*- coding: utf-8 -*-
"""
Async method tests for MultiTokenAuthManager.

Tests cover:
- _mask_token
- is_token_fresh_for_streaming
- _refresh_single_token (success, HTTP error, generic error)
- _refresh_token_request (success, rotation on failure, all-fail)
- force_refresh
- start_background_refresh / stop_background_refresh
- Properties: profile_arn, region, api_host, q_host, fingerprint, auth_type
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from kiro.auth_multi import MultiTokenAuthManager, TokenInfo, AuthType


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def three_token_manager():
    return MultiTokenAuthManager(
        refresh_tokens=["token_a", "token_b", "token_c"],
        region="us-east-1",
    )


@pytest.fixture
def single_token_manager():
    return MultiTokenAuthManager(
        refresh_tokens=["only_token"],
        region="us-east-1",
    )


@pytest.fixture
def empty_token_manager():
    return MultiTokenAuthManager(refresh_tokens=[], region="us-east-1")


# ===========================================================================
# _mask_token
# ===========================================================================

class TestMaskToken:
    def test_masks_long_token(self, single_token_manager):
        result = single_token_manager._mask_token("abcdefgh_secret_part")
        assert result == "abcdefgh..."

    def test_returns_none_string_for_none(self, single_token_manager):
        assert single_token_manager._mask_token(None) == "None"

    def test_returns_none_string_for_empty(self, single_token_manager):
        assert single_token_manager._mask_token("") == "None"

    def test_short_token_uses_first_8_chars(self, single_token_manager):
        result = single_token_manager._mask_token("abc12345xyz")
        assert result == "abc12345..."


# ===========================================================================
# is_token_fresh_for_streaming
# ===========================================================================

class TestIsTokenFreshForStreaming:
    def test_returns_false_when_no_token(self, empty_token_manager):
        assert empty_token_manager.is_token_fresh_for_streaming() is False

    def test_returns_false_when_no_expires_at(self, single_token_manager):
        single_token_manager._tokens[0].expires_at = None
        assert single_token_manager.is_token_fresh_for_streaming() is False

    def test_returns_true_when_token_has_ample_time(self, single_token_manager):
        single_token_manager._tokens[0].expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=2)
        )
        assert single_token_manager.is_token_fresh_for_streaming(600) is True

    def test_returns_false_when_token_expires_too_soon(self, single_token_manager):
        single_token_manager._tokens[0].expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=100)
        )
        assert single_token_manager.is_token_fresh_for_streaming(600) is False

    def test_boundary_ample_time_above_minimum(self, single_token_manager):
        """Token valid for 1200 seconds passes a 600-second minimum check."""
        single_token_manager._tokens[0].expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=1200)
        )
        assert single_token_manager.is_token_fresh_for_streaming(600) is True


# ===========================================================================
# _refresh_single_token
# ===========================================================================

class TestRefreshSingleToken:
    @pytest.mark.asyncio
    async def test_returns_false_for_out_of_range_index(self, single_token_manager):
        result = await single_token_manager._refresh_single_token(99)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_negative_index(self, single_token_manager):
        result = await single_token_manager._refresh_single_token(-1)
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_refresh_updates_token(self, single_token_manager):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "accessToken": "new_access_token",
            "refreshToken": "new_refresh_token",
            "expiresIn": 3600,
            "profileArn": "arn:aws:codewhisperer:us-east-1:123:profile/test",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await single_token_manager._refresh_single_token(0)

        assert result is True
        token = single_token_manager._tokens[0]
        assert token.access_token == "new_access_token"
        assert token.refresh_token == "new_refresh_token"
        assert token.is_failed is False
        assert token.failure_count == 0

    @pytest.mark.asyncio
    async def test_successful_refresh_returns_false_without_access_token(self, single_token_manager):
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # No accessToken
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await single_token_manager._refresh_single_token(0)

        assert result is False

    @pytest.mark.asyncio
    async def test_http_error_marks_token_failed(self, single_token_manager):
        http_error = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=http_error)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await single_token_manager._refresh_single_token(0)

        assert result is False
        token = single_token_manager._tokens[0]
        assert token.is_failed is True
        assert token.failure_count == 1

    @pytest.mark.asyncio
    async def test_generic_error_marks_token_failed(self, single_token_manager):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=ConnectionError("timeout"))
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await single_token_manager._refresh_single_token(0)

        assert result is False
        token = single_token_manager._tokens[0]
        assert token.is_failed is True

    @pytest.mark.asyncio
    async def test_profile_arn_updated_on_refresh(self, single_token_manager):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "accessToken": "new_token",
            "expiresIn": 3600,
            "profileArn": "arn:new:profile",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            await single_token_manager._refresh_single_token(0)

        assert single_token_manager._tokens[0].profile_arn == "arn:new:profile"


# ===========================================================================
# _refresh_token_request
# ===========================================================================

class TestRefreshTokenRequest:
    @pytest.mark.asyncio
    async def test_raises_when_no_tokens(self, empty_token_manager):
        with pytest.raises(ValueError, match="No refresh tokens available"):
            await empty_token_manager._refresh_token_request()

    @pytest.mark.asyncio
    async def test_successful_refresh_sets_access_token(self, single_token_manager):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "accessToken": "fresh_token",
            "expiresIn": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            await single_token_manager._refresh_token_request()

        assert single_token_manager._tokens[0].access_token == "fresh_token"

    @pytest.mark.asyncio
    async def test_raises_when_no_access_token_in_response(self, single_token_manager):
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # No accessToken
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(Exception):
                await single_token_manager._refresh_token_request()

    @pytest.mark.asyncio
    async def test_401_rotates_to_next_token(self, three_token_manager):
        """On 401, should rotate and try next token."""
        call_count = 0

        def make_response(status_code=200, data=None):
            resp = MagicMock()
            if status_code == 401:
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "401", request=MagicMock(), response=MagicMock(status_code=401)
                )
            else:
                resp.raise_for_status = MagicMock()
                resp.json.return_value = data or {"accessToken": "ok_token", "expiresIn": 3600}
            return resp

        responses = [make_response(401), make_response(200)]

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            r = responses[min(call_count, len(responses) - 1)]
            call_count += 1
            return r

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            await three_token_manager._refresh_token_request()

        # Should have rotated (second token should now be active)
        assert three_token_manager._active_index != 0
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_all_tokens_401_raises_value_error(self, three_token_manager):
        """If all tokens fail 401, raises ValueError."""
        http_error = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock(status_code=401)
        )
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = http_error

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="All.*tokens failed"):
                await three_token_manager._refresh_token_request()

    @pytest.mark.asyncio
    async def test_non_auth_http_error_propagates(self, single_token_manager):
        """HTTP 500 (non-auth) should be re-raised, not swallowed."""
        http_error = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500)
        )
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = http_error

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.HTTPStatusError):
                await single_token_manager._refresh_token_request()

    @pytest.mark.asyncio
    async def test_profile_arn_updated_on_refresh(self, single_token_manager):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "accessToken": "tok",
            "expiresIn": 3600,
            "profileArn": "arn:updated",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            await single_token_manager._refresh_token_request()

        # Both token's profile_arn and manager's _profile_arn should be updated
        assert single_token_manager._tokens[0].profile_arn == "arn:updated"
        assert single_token_manager._profile_arn == "arn:updated"


# ===========================================================================
# force_refresh
# ===========================================================================

class TestForceRefresh:
    @pytest.mark.asyncio
    async def test_force_refresh_returns_access_token(self, single_token_manager):
        async def mock_refresh():
            single_token_manager._tokens[0].access_token = "forced_token"

        with patch.object(single_token_manager, "_refresh_token_request", side_effect=mock_refresh):
            result = await single_token_manager.force_refresh()

        assert result == "forced_token"

    @pytest.mark.asyncio
    async def test_force_refresh_raises_when_no_token_after_refresh(self, single_token_manager):
        async def mock_refresh():
            # Refresh succeeds but token is still None (edge case)
            pass

        with patch.object(single_token_manager, "_refresh_token_request", side_effect=mock_refresh):
            with pytest.raises(ValueError, match="Failed to obtain access token after refresh"):
                await single_token_manager.force_refresh()


# ===========================================================================
# get_access_token - missing branch
# ===========================================================================

class TestGetAccessTokenMissingBranch:
    @pytest.mark.asyncio
    async def test_raises_when_refresh_succeeds_but_token_still_none(self, single_token_manager):
        """Branch: refresh called but token still None."""
        async def noop_refresh():
            pass  # Does not set access_token

        with patch.object(single_token_manager, "_refresh_token_request", side_effect=noop_refresh):
            # Token has no access_token and no expiry -> triggers refresh
            with pytest.raises(ValueError, match="Failed to obtain access token"):
                await single_token_manager.get_access_token()


# ===========================================================================
# start_background_refresh / stop_background_refresh
# ===========================================================================

class TestBackgroundRefresh:
    @pytest.mark.asyncio
    async def test_start_background_refresh_creates_task(self, three_token_manager):
        # We don't want the background task to actually run
        async def never_ending():
            await asyncio.sleep(9999)

        with patch.object(three_token_manager, "_background_token_refresh", never_ending):
            three_token_manager.start_background_refresh()
            assert three_token_manager._background_task is not None
            assert not three_token_manager._background_task.done()
            # Cleanup
            three_token_manager._background_task.cancel()
            try:
                await three_token_manager._background_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_start_background_refresh_not_duplicated(self, three_token_manager):
        async def never_ending():
            await asyncio.sleep(9999)

        with patch.object(three_token_manager, "_background_token_refresh", never_ending):
            three_token_manager.start_background_refresh()
            task1 = three_token_manager._background_task
            three_token_manager.start_background_refresh()  # Second call should be a no-op
            assert three_token_manager._background_task is task1
            # Cleanup
            task1.cancel()
            try:
                await task1
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_stop_background_refresh_cancels_task(self, three_token_manager):
        async def never_ending():
            try:
                await asyncio.sleep(9999)
            except asyncio.CancelledError:
                raise

        with patch.object(three_token_manager, "_background_token_refresh", never_ending):
            three_token_manager.start_background_refresh()
            assert three_token_manager._background_task is not None

        await three_token_manager.stop_background_refresh()
        assert three_token_manager._background_task.done()

    @pytest.mark.asyncio
    async def test_stop_background_refresh_with_no_task(self, three_token_manager):
        """Calling stop when no task was started should not raise."""
        assert three_token_manager._background_task is None
        await three_token_manager.stop_background_refresh()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_sets_shutdown_flag(self, three_token_manager):
        await three_token_manager.stop_background_refresh()
        assert three_token_manager._shutdown is True


# ===========================================================================
# Properties
# ===========================================================================

class TestProperties:
    def test_profile_arn_property(self):
        arn = "arn:aws:codewhisperer:us-east-1:123:profile/test"
        manager = MultiTokenAuthManager(
            refresh_tokens=["tok"], profile_arn=arn, region="us-east-1"
        )
        assert manager.profile_arn == arn

    def test_region_property(self):
        manager = MultiTokenAuthManager(refresh_tokens=["tok"], region="eu-west-1")
        assert manager.region == "eu-west-1"

    def test_api_host_property(self):
        manager = MultiTokenAuthManager(refresh_tokens=["tok"], region="us-east-1")
        assert manager.api_host  # Non-empty
        assert "amazonaws.com" in manager.api_host or "q." in manager.api_host

    def test_q_host_property(self):
        manager = MultiTokenAuthManager(refresh_tokens=["tok"], region="us-east-1")
        assert manager.q_host

    def test_fingerprint_property(self):
        manager = MultiTokenAuthManager(refresh_tokens=["tok"], region="us-east-1")
        fp = manager.fingerprint
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_auth_type_is_kiro_desktop(self):
        manager = MultiTokenAuthManager(refresh_tokens=["tok"], region="us-east-1")
        assert manager.auth_type == AuthType.KIRO_DESKTOP

    def test_profile_arn_none_by_default(self):
        manager = MultiTokenAuthManager(refresh_tokens=["tok"], region="us-east-1")
        assert manager.profile_arn is None
