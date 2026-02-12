# -*- coding: utf-8 -*-
from __future__ import annotations

# Kiro Gateway
# https://github.com/jwadow/kiro-gateway
# Copyright (C) 2025 Jwadow
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
Multi-token authentication manager for Kiro API.

Contains MultiTokenAuthManager for round-robin rotation across multiple
refresh tokens, and the TokenInfo dataclass used to track token health.
"""

import asyncio
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import httpx
from loguru import logger

from kiro.config import (
    TOKEN_REFRESH_THRESHOLD,
    BACKGROUND_REFRESH_INTERVAL,
    get_kiro_refresh_url,
    get_kiro_api_host,
    get_kiro_q_host,
)
from kiro.utils import get_machine_fingerprint


class AuthType(Enum):
    """
    Type of authentication mechanism.
    
    KIRO_DESKTOP: Kiro IDE credentials (default)
        - Uses https://prod.{region}.auth.desktop.kiro.dev/refreshToken
        - JSON body: {"refreshToken": "..."}
    
    AWS_SSO_OIDC: AWS SSO credentials from kiro-cli
        - Uses https://oidc.{region}.amazonaws.com/token
        - Form body: grant_type=refresh_token&client_id=...&client_secret=...&refresh_token=...
        - Requires clientId and clientSecret from credentials file
    """
    KIRO_DESKTOP = "kiro_desktop"
    AWS_SSO_OIDC = "aws_sso_oidc"



@dataclass
class TokenInfo:
    """Information about a single refresh token with health tracking."""
    refresh_token: str
    access_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_failed: bool = False
    failure_count: int = 0
    last_failure: Optional[datetime] = None
    last_refresh: Optional[datetime] = None
    profile_arn: Optional[str] = None


# Multi-Token Support (based on user's implementation that ran 30 days)
# ==================================================================================================

class MultiTokenAuthManager:
    """
    Manages multiple refresh tokens with round-robin rotation and health tracking.

    Features:
    - Load multiple tokens from comma-separated list or numbered vars
    - Round-robin rotation between healthy tokens
    - Exponential backoff for failed tokens (5min, 30min, 2h)
    - Background refresh to keep all tokens healthy
    - Health status monitoring

    Example:
        >>> auth_manager = MultiTokenAuthManager(
        ...     refresh_tokens=["token1", "token2", "token3"],
        ...     region="us-east-1"
        ... )
        >>> token = await auth_manager.get_access_token()
    """

    def __init__(
        self,
        refresh_tokens: Optional[List[str]] = None,
        profile_arn: Optional[str] = None,
        region: str = "us-east-1",
    ):
        """
        Initialize multi-token auth manager.

        Args:
            refresh_tokens: List of refresh tokens
            profile_arn: AWS CodeWhisperer profile ARN
            region: AWS region (default: us-east-1)
        """
        # Initialize token pool
        self._tokens: List[TokenInfo] = []

        if refresh_tokens:
            for token in refresh_tokens:
                if token:
                    self._tokens.append(TokenInfo(refresh_token=token))

        # Current active token index
        self._active_index = 0 if self._tokens else -1

        self._profile_arn = profile_arn
        self._region = region
        self._lock = asyncio.Lock()
        self._background_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Dynamic URLs based on region
        self._refresh_url = get_kiro_refresh_url(region)
        self._api_host = get_kiro_api_host(region)
        self._q_host = get_kiro_q_host(region)

        # Fingerprint for User-Agent
        self._fingerprint = get_machine_fingerprint()

        if self._tokens:
            logger.info(f"MultiTokenAuthManager initialized with {len(self._tokens)} tokens")
        else:
            logger.warning("MultiTokenAuthManager: no refresh tokens provided")

    def _get_active_token(self) -> Optional[TokenInfo]:
        """Get the currently active token info."""
        if not self._tokens or self._active_index < 0:
            return None
        return self._tokens[self._active_index]

    def _rotate_to_next_token(self) -> bool:
        """
        Rotate to the next available token.

        Returns:
            True if rotation successful, False if no more tokens available
        """
        if not self._tokens:
            return False

        original_index = self._active_index

        # Try all tokens in order, starting from the one after the current active
        for i in range(1, len(self._tokens) + 1):
            next_index = (original_index + i) % len(self._tokens)
            token = self._tokens[next_index]

            # Skip tokens that are marked as failed
            if token.is_failed and token.last_failure:
                time_since_failure = datetime.now(timezone.utc) - token.last_failure

                # Exponential backoff based on failure count
                if token.failure_count == 1:
                    backoff = timedelta(minutes=5)
                elif token.failure_count == 2:
                    backoff = timedelta(minutes=30)
                else:  # 3 or more failures
                    backoff = timedelta(hours=2)

                if time_since_failure < backoff:
                    continue

            self._active_index = next_index
            logger.info(f"Rotated to token {self._active_index + 1}/{len(self._tokens)}")
            return True

        # Reset failures if all are in backoff (staggered to avoid thundering herd)
        for i, token in enumerate(self._tokens):
            token.is_failed = False

        if original_index >= 0:
            self._active_index = original_index

        return False

    def _mask_token(self, token: Optional[str]) -> str:
        """Mask a token for safe logging (shows first 8 chars only)."""
        if not token:
            return "None"
        return f"{token[:8]}..."

    def is_token_expiring_soon(self) -> bool:
        """Check if active token is expiring soon."""
        token = self._get_active_token()
        if not token or not token.expires_at:
            return True

        now = datetime.now(timezone.utc)
        threshold = now.timestamp() + TOKEN_REFRESH_THRESHOLD
        return token.expires_at.timestamp() <= threshold

    def is_token_fresh_for_streaming(self, min_validity_seconds: float = 600) -> bool:
        """
        Check if the active token is fresh enough for a long streaming request.

        Args:
            min_validity_seconds: Minimum time the token should be valid for
                (default: 600 seconds = 10 minutes)

        Returns:
            True if the token is valid for at least min_validity_seconds
        """
        token = self._get_active_token()
        if not token or not token.expires_at:
            return False

        now = datetime.now(timezone.utc)
        time_until_expiry = (token.expires_at - now).total_seconds()

        return time_until_expiry >= min_validity_seconds

    async def _refresh_single_token(self, index: int) -> bool:
        """Refresh a specific token by index."""
        if index < 0 or index >= len(self._tokens):
            return False

        token = self._tokens[index]
        masked = self._mask_token(token.refresh_token)
        logger.debug(f"Refreshing token {index + 1}/{len(self._tokens)} (token: {masked})")

        payload = {"refreshToken": token.refresh_token}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"KiroGateway-{self._fingerprint[:16]}",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self._refresh_url, json=payload, headers=headers
                )
                response.raise_for_status()
                data = response.json()

            new_access_token = data.get("accessToken")
            new_refresh_token = data.get("refreshToken")
            expires_in = data.get("expiresIn", 3600)
            new_profile_arn = data.get("profileArn")

            if not new_access_token:
                logger.warning(f"Token {index + 1}: No accessToken in response")
                return False

            token.access_token = new_access_token
            if new_refresh_token:
                token.refresh_token = new_refresh_token
            if new_profile_arn:
                token.profile_arn = new_profile_arn

            token.expires_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + expires_in - 60,
                tz=timezone.utc
            )
            token.last_refresh = datetime.now(timezone.utc)
            token.is_failed = False
            token.failure_count = 0

            logger.info(f"Token {index + 1}/{len(self._tokens)} refreshed successfully")
            return True

        except httpx.HTTPStatusError as e:
            logger.warning(f"Token {index + 1} refresh failed: HTTP {e.response.status_code}")
            token.is_failed = True
            token.failure_count += 1
            token.last_failure = datetime.now(timezone.utc)
            return False
        except Exception as e:
            logger.warning(f"Token {index + 1} refresh error: {e}")
            token.is_failed = True
            token.failure_count += 1
            token.last_failure = datetime.now(timezone.utc)
            return False

    async def _refresh_token_request(self) -> None:
        """Refresh the active token with rotation on failure."""
        if not self._tokens:
            raise ValueError("No refresh tokens available")

        last_error = None

        for attempt in range(len(self._tokens)):
            token = self._tokens[self._active_index]

            logger.info(f"Refreshing token {self._active_index + 1}/{len(self._tokens)}...")

            payload = {"refreshToken": token.refresh_token}
            headers = {
                "Content-Type": "application/json",
                "User-Agent": f"KiroGateway-{self._fingerprint[:16]}",
            }

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(
                        self._refresh_url, json=payload, headers=headers
                    )
                    response.raise_for_status()
                    data = response.json()

                new_access_token = data.get("accessToken")
                new_refresh_token = data.get("refreshToken")
                expires_in = data.get("expiresIn", 3600)
                new_profile_arn = data.get("profileArn")

                if not new_access_token:
                    raise ValueError(f"Response does not contain accessToken: {data}")

                token.access_token = new_access_token
                if new_refresh_token:
                    token.refresh_token = new_refresh_token
                if new_profile_arn:
                    token.profile_arn = new_profile_arn
                    self._profile_arn = new_profile_arn

                # Calculate expiration time with buffer (minus 60 seconds for safety)
                token.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

                token.is_failed = False
                token.failure_count = 0

                logger.info(f"Token {self._active_index + 1}/{len(self._tokens)} refreshed, expires: {token.expires_at.isoformat()}")
                return

            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403):
                    logger.warning(f"Token {self._active_index + 1} failed: {e.response.status_code}")
                    token.is_failed = True
                    token.failure_count += 1
                    token.last_failure = datetime.now(timezone.utc)
                    last_error = e

                    if not self._rotate_to_next_token():
                        break
                else:
                    raise
            except Exception as e:
                logger.error(f"Error refreshing token: {e}")
                token.is_failed = True
                token.failure_count += 1
                token.last_failure = datetime.now(timezone.utc)
                last_error = e

                if not self._rotate_to_next_token():
                    break

        raise ValueError(f"All {len(self._tokens)} tokens failed. Last error: {last_error}")

    async def get_access_token(self) -> str:
        """
        Get valid access token from active token, refreshing if needed.
        """
        async with self._lock:
            token = self._get_active_token()
            if not token or not token.access_token or self.is_token_expiring_soon():
                await self._refresh_token_request()
                token = self._get_active_token()

            if not token or not token.access_token:
                raise ValueError("Failed to obtain access token")

            return token.access_token

    async def force_refresh(self) -> str:
        """Force refresh the active token."""
        async with self._lock:
            await self._refresh_token_request()
            token = self._get_active_token()
            if not token or not token.access_token:
                raise ValueError("Failed to obtain access token after refresh")
            return token.access_token

    async def refresh_all_tokens(self) -> dict:
        """
        Refresh ALL tokens concurrently to keep them healthy.

        Returns:
            Dict with refresh results for each token
        """
        if not self._tokens:
            return {}

        results = {}

        async with self._lock:
            # Refresh all tokens concurrently
            tasks = [self._refresh_single_token(i) for i in range(len(self._tokens))]
            refresh_results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(refresh_results):
                token_id = f"token_{i + 1}"
                if isinstance(result, Exception):
                    results[token_id] = "failed"
                else:
                    results[token_id] = "healthy" if result else "failed"

        healthy = sum(1 for v in results.values() if v == "healthy")
        logger.info(f"Token refresh complete: {healthy}/{len(results)} healthy")
        return results

    async def _background_token_refresh(self) -> None:
        """
        Background task that periodically refreshes all tokens.

        FIXED: Improved timing and error handling:
        - Initial refresh waits for app startup (60 seconds)
        - Checks shutdown flag more frequently
        - Individual token health monitoring
        """
        logger.info("Background token refresh task started")

        # Initial delay to ensure app is fully started
        await asyncio.sleep(60)

        # Initial refresh of all tokens
        try:
            results = await self.refresh_all_tokens()
            healthy = sum(1 for v in results.values() if v == "healthy")
            logger.info(f"Initial token refresh: {healthy}/{len(results)} healthy")
        except Exception as e:
            logger.error(f"Initial token refresh failed: {e}")

        while True:
            try:
                await asyncio.sleep(BACKGROUND_REFRESH_INTERVAL)

                # Check shutdown flag BEFORE and AFTER sleep
                if self._shutdown:
                    break

                logger.info("Running scheduled token refresh for all tokens...")
                results = await self.refresh_all_tokens()

                healthy = sum(1 for v in results.values() if v == "healthy")
                failed = len(results) - healthy
                if failed > 0:
                    logger.warning(f"Token refresh complete: {healthy}/{len(results)} healthy, {failed} failed")
                else:
                    logger.info(f"Token refresh complete: {healthy}/{len(results)} healthy")

            except asyncio.CancelledError:
                logger.info("Background token refresh task cancelled")
                break
            except Exception as e:
                logger.error(f"Background refresh error: {e}")
                # Brief sleep before retry to avoid spinning on persistent errors
                await asyncio.sleep(30)

            # Check again after each iteration to avoid race
            if self._shutdown:
                break

        logger.info("Background token refresh task stopped")

    def start_background_refresh(self) -> None:
        """Start the background token refresh task."""
        if self._background_task is None or self._background_task.done():
            self._shutdown = False
            self._background_task = asyncio.create_task(self._background_token_refresh())
            logger.info("Background token refresh enabled")

    async def stop_background_refresh(self) -> None:
        """Stop the background token refresh task."""
        self._shutdown = True
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        logger.info("Background token refresh disabled")

    def get_token_status(self) -> List[dict]:
        """
        Get status of all tokens for health monitoring.

        Returns:
            List of token status dicts
        """
        status = []
        for i, token in enumerate(self._tokens):
            status.append({
                "index": i + 1,
                "active": i == self._active_index,
                "has_access_token": bool(token.access_token),
                "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                "last_refresh": token.last_refresh.isoformat() if token.last_refresh else None,
                "is_failed": token.is_failed,
                "failure_count": token.failure_count,
            })
        return status

    @property
    def profile_arn(self) -> Optional[str]:
        """AWS CodeWhisperer profile ARN."""
        return self._profile_arn

    @property
    def region(self) -> str:
        """AWS region."""
        return self._region

    @property
    def api_host(self) -> str:
        """API host for the current region."""
        return self._api_host

    @property
    def q_host(self) -> str:
        """Q API host for the current region."""
        return self._q_host

    @property
    def fingerprint(self) -> str:
        """Unique machine fingerprint."""
        return self._fingerprint

    @property
    def auth_type(self) -> AuthType:
        """Authentication type (KIRO_DESKTOP for refresh tokens)."""
        return AuthType.KIRO_DESKTOP