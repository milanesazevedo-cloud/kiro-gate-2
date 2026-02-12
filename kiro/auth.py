# -*- coding: utf-8 -*-

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
Authentication manager for Kiro API.

Manages token lifecycle:
- Automatic token refresh on expiration
- Thread-safe refresh using asyncio.Lock
- Support for both Kiro Desktop Auth and AWS SSO OIDC (kiro-cli)

Credential loading/saving extracted to auth_credentials.py.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
import asyncio
import httpx
from loguru import logger

from kiro.config import (
    TOKEN_REFRESH_THRESHOLD,
    BACKGROUND_REFRESH_INTERVAL,
    get_kiro_api_host,
    get_kiro_q_host,
    get_aws_sso_oidc_url,
)
from kiro.utils import get_machine_fingerprint
from kiro.auth_credentials import KiroCredentialsMixin
from kiro.auth_multi import AuthType, MultiTokenAuthManager  # noqa: F401


class KiroAuthManager(KiroCredentialsMixin):
    """
    Manages token lifecycle for accessing Kiro API.

    Supports:
    - Automatic token refresh on expiration
    - Expiration time validation (expiresAt)
    - Saving updated tokens to file
    - Both Kiro Desktop Auth and AWS SSO OIDC (kiro-cli) authentication

    Attributes:
        profile_arn: AWS CodeWhisperer profile ARN
        region: AWS region
        api_host: API host for current region
        q_host: Q API host for current region
        fingerprint: Unique machine fingerprint
        auth_type: Type of authentication (KIRO_DESKTOP or AWS_SSO_OIDC)

    Example:
        >>> # Kiro Desktop Auth (default)
        >>> auth_manager = KiroAuthManager(
        ...     refresh_token="your_refresh_token",
        ...     region="us-east-1"
        ... )
        >>> token = await auth_manager.get_access_token()

        >>> # AWS SSO OIDC (kiro-cli) - auto-detected from credentials file
        >>> auth_manager = KiroAuthManager(
        ...     creds_file="~/.aws/sso/cache/your-cache.json"
        ... )
        >>> token = await auth_manager.get_access_token()
    """

    def __init__(
        self,
        refresh_token: Optional[str] = None,
        profile_arn: Optional[str] = None,
        region: str = "us-east-1",
        creds_file: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        sqlite_db: Optional[str] = None,
    ):
        """
        Initializes authentication manager.

        Args:
            refresh_token: Refresh token for obtaining access token
            profile_arn: AWS CodeWhisperer profile ARN
            region: AWS region (default: us-east-1)
            creds_file: Path to JSON file with credentials (optional)
            client_id: OAuth client ID (for AWS SSO OIDC, optional)
            client_secret: OAuth client secret (for AWS SSO OIDC, optional)
            sqlite_db: Path to kiro-cli SQLite database (optional)
        """
        self._refresh_token = refresh_token
        self._profile_arn = profile_arn
        self._region = region
        self._creds_file = creds_file
        self._sqlite_db = sqlite_db

        # AWS SSO OIDC specific fields
        self._client_id: Optional[str] = client_id
        self._client_secret: Optional[str] = client_secret
        self._scopes: Optional[list] = None  # OAuth scopes for AWS SSO OIDC
        self._sso_region: Optional[str] = None  # SSO region for OIDC token refresh (may differ from API region)

        # Enterprise Kiro IDE specific fields
        self._client_id_hash: Optional[str] = None  # clientIdHash from Enterprise Kiro IDE

        # Track which SQLite key we loaded credentials from (for saving back to correct location)
        self._sqlite_token_key: Optional[str] = None

        self._access_token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self._background_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Auth type will be determined after loading credentials
        self._auth_type: AuthType = AuthType.KIRO_DESKTOP

        # Dynamic URLs based on region
        from kiro.config import get_kiro_refresh_url
        self._refresh_url = get_kiro_refresh_url(region)
        self._api_host = get_kiro_api_host(region)
        self._q_host = get_kiro_q_host(region)

        # Log initialized endpoints for diagnostics (helps with DNS issues like #58)
        logger.info(
            f"Auth manager initialized: region={region}, "
            f"api_host={self._api_host}, q_host={self._q_host}"
        )

        # Fingerprint for User-Agent
        self._fingerprint = get_machine_fingerprint()

        # Load credentials from SQLite if specified (takes priority over JSON)
        if sqlite_db:
            self._load_credentials_from_sqlite(sqlite_db)
        # Load credentials from JSON file if specified
        elif creds_file:
            self._load_credentials_from_file(creds_file)

        # Determine auth type based on available credentials
        self._detect_auth_type()

    def _detect_auth_type(self) -> None:
        """
        Detects authentication type based on available credentials.

        AWS SSO OIDC credentials contain clientId and clientSecret.
        Kiro Desktop credentials do not contain these fields.
        """
        if self._client_id and self._client_secret:
            self._auth_type = AuthType.AWS_SSO_OIDC
            logger.info("Detected auth type: AWS SSO OIDC (kiro-cli)")
        else:
            self._auth_type = AuthType.KIRO_DESKTOP
            logger.info("Detected auth type: Kiro Desktop")

    def is_token_expiring_soon(self) -> bool:
        """
        Checks if token is expiring soon.

        Returns:
            True if token expires within TOKEN_REFRESH_THRESHOLD seconds
            or if expiration time information is not available
        """
        if not self._expires_at:
            return True  # If no expiration info available, assume refresh is needed

        now = datetime.now(timezone.utc)
        threshold = now.timestamp() + TOKEN_REFRESH_THRESHOLD

        return self._expires_at.timestamp() <= threshold

    def is_token_expired(self) -> bool:
        """
        Checks if token is actually expired (not just expiring soon).

        This is used for graceful degradation when refresh fails but
        access token might still be valid for a short time.

        Returns:
            True if token has already expired or if expiration time
            information is not available
        """
        if not self._expires_at:
            return True  # If no expiration info available, assume expired

        now = datetime.now(timezone.utc)
        return now >= self._expires_at

    def is_token_fresh_for_streaming(self, min_validity_seconds: float = 600) -> bool:
        """
        Checks if token is fresh enough for a long streaming request.

        This ensures token won't expire during a streaming request that
        might take longer than normal token validity.

        Args:
            min_validity_seconds: Minimum time token should be valid for
                (default: 600 seconds = 10 minutes)

        Returns:
            True if token is valid for at least min_validity_seconds
        """
        if not self._expires_at:
            return False  # No expiration info, not fresh

        now = datetime.now(timezone.utc)
        time_until_expiry = (self._expires_at - now).total_seconds()

        return time_until_expiry >= min_validity_seconds

    async def _refresh_token_request(self) -> None:
        """
        Performs a token refresh request.

        Routes to appropriate refresh method based on auth type:
        - KIRO_DESKTOP: Uses Kiro Desktop Auth endpoint
        - AWS_SSO_OIDC: Uses AWS SSO OIDC endpoint

        Raises:
            ValueError: If refresh token is not set or response doesn't contain accessToken
            httpx.HTTPError: On HTTP request error
        """
        if self._auth_type == AuthType.AWS_SSO_OIDC:
            await self._refresh_token_aws_sso_oidc()
        else:
            await self._refresh_token_kiro_desktop()

    async def _refresh_token_kiro_desktop(self) -> None:
        """
        Refreshes token using Kiro Desktop Auth endpoint.

        Endpoint: https://prod.{region}.auth.desktop.kiro.dev/refreshToken
        Method: POST
        Content-Type: application/json
        Body: {"refreshToken": "..."}

        Raises:
            ValueError: If refresh token is not set or response doesn't contain accessToken
            httpx.HTTPError: On HTTP request error
        """
        if not self._refresh_token:
            raise ValueError("Refresh token is not set")

        logger.info("Refreshing Kiro token via Kiro Desktop Auth...")

        payload = {'refreshToken': self._refresh_token}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"KiroIDE-0.7.45-{self._fingerprint}",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self._refresh_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        new_access_token = data.get("accessToken")
        new_refresh_token = data.get("refreshToken")
        expires_in = data.get("expiresIn", 3600)
        new_profile_arn = data.get("profileArn")

        if not new_access_token:
            raise ValueError(f"Response does not contain accessToken: {data}")

        # Update data
        self._access_token = new_access_token
        if new_refresh_token:
            self._refresh_token = new_refresh_token
        if new_profile_arn:
            self._profile_arn = new_profile_arn

        # Calculate expiration time with buffer (minus 60 seconds for safety)
        # Kiro tokens typically expire in 3600 seconds (1 hour)
        self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

        logger.info(f"Token refreshed via Kiro Desktop Auth, expires: {self._expires_at.isoformat()}")

        # Save to file or SQLite depending on configuration
        if self._sqlite_db:
            self._save_credentials_to_sqlite()
        else:
            self._save_credentials_to_file()

    async def _refresh_token_aws_sso_oidc(self) -> None:
        """
        Refreshes token using AWS SSO OIDC endpoint.

        Used by kiro-cli which authenticates via AWS IAM Identity Center.

        Strategy: Try with current in-memory token first. If it fails with 400
        (invalid_request - token was invalidated by kiro-cli re-login), reload
        credentials from SQLite and retry once.

        This approach handles both scenarios:
        1. Container successfully refreshed token (uses in-memory token)
        2. kiro-cli re-login invalidated token (reloads from SQLite on failure)

        Endpoint: https://oidc.{region}.amazonaws.com/token
        Method: POST
        Content-Type: application/x-www-form-urlencoded
        Body: grant_type=refresh_token&client_id=...&client_secret=...&refresh_token=...

        Raises:
            ValueError: If required credentials are not set
            httpx.HTTPError: On HTTP request error
        """
        try:
            await self._do_aws_sso_oidc_refresh()
        except httpx.HTTPStatusError as e:
            # 400 = invalid_request, likely stale token after kiro-cli re-login
            if e.response.status_code == 400 and self._sqlite_db:
                logger.warning(
                    "Token refresh failed with 400, reloading credentials "
                    "from SQLite and retrying..."
                )
                self._load_credentials_from_sqlite(self._sqlite_db)
                await self._do_aws_sso_oidc_refresh()
            else:
                raise

    async def _do_aws_sso_oidc_refresh(self) -> None:
        """
        Performs actual AWS SSO OIDC token refresh.

        This is the internal implementation called by _refresh_token_aws_sso_oidc().
        It performs a single refresh attempt with current in-memory credentials.

        Uses AWS SSO OIDC CreateToken API format:
        - Content-Type: application/json (not form-urlencoded)
        - Parameter names: camelCase (clientId, not client_id)
        - Payload: JSON object

        Raises:
            ValueError: If required credentials are not set
            httpx.HTTPError: On HTTP error (including 400 for invalid token)
        """
        if not self._refresh_token:
            raise ValueError("Refresh token is not set")
        if not self._client_id:
            raise ValueError("Client ID is not set (required for AWS SSO OIDC)")
        if not self._client_secret:
            raise ValueError("Client secret is not set (required for AWS SSO OIDC)")

        logger.info("Refreshing Kiro token via AWS SSO OIDC...")

        # AWS SSO OIDC CreateToken API uses JSON with camelCase parameters
        # Use SSO region for OIDC endpoint (may differ from API region)
        sso_region = self._sso_region or self._region
        url = get_aws_sso_oidc_url(sso_region)

        # IMPORTANT: AWS SSO OIDC CreateToken API requires:
        # 1. JSON payload (not form-urlencoded)
        # 2. camelCase parameter names (clientId, not client_id)
        payload = {
            "grantType": "refresh_token",
            "clientId": self._client_id,
            "clientSecret": self._client_secret,
            "refreshToken": self._refresh_token,
        }

        headers = {
            "Content-Type": "application/json",
        }

        # Log request details (without secrets) for debugging
        logger.debug(
            f"AWS SSO OIDC refresh request: url={url}, sso_region={sso_region}, "
            f"api_region={self._region}, client_id={self._client_id[:8]}..."
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)

            # Log response details for debugging (especially on errors)
            if response.status_code != 200:
                error_body = response.text
                logger.error(
                    f"AWS SSO OIDC refresh failed: status={response.status_code}, "
                    f"body={error_body}"
                )
                # Try to parse AWS error for more details
                try:
                    error_json = response.json()
                    error_code = error_json.get("error", "unknown")
                    error_desc = error_json.get("error_description", "no description")
                    logger.error(
                        f"AWS SSO OIDC error details: error={error_code}, "
                        f"description={error_desc}"
                    )
                except Exception:
                    pass  # Body wasn't JSON, already logged as text
                response.raise_for_status()

            result = response.json()

        # AWS SSO OIDC CreateToken API returns camelCase fields
        new_access_token = result.get("accessToken")
        new_refresh_token = result.get("refreshToken")
        expires_in = result.get("expiresIn", 3600)

        if not new_access_token:
            raise ValueError(f"AWS SSO OIDC response does not contain accessToken: {result}")

        # Update data
        self._access_token = new_access_token
        if new_refresh_token:
            self._refresh_token = new_refresh_token

        # Calculate expiration time with buffer (minus 60 seconds)
        self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

        logger.info(f"Token refreshed via AWS SSO OIDC, expires: {self._expires_at.isoformat()}")

        # Save to file or SQLite depending on configuration
        if self._sqlite_db:
            self._save_credentials_to_sqlite()
        else:
            self._save_credentials_to_file()

    async def get_access_token(self) -> str:
        """
        Returns a valid access_token, refreshing it if necessary.

        Thread-safe method using asyncio.Lock.
        Automatically refreshes token if it has expired or is about to expire.

        For SQLite mode (kiro-cli): implements graceful degradation when refresh fails.
        If kiro-cli has been running and refreshing tokens in memory (without persisting
        to SQLite), refresh_token in SQLite becomes stale. In this case, we fall back
        to using access_token directly until it actually expires.

        Returns:
            Valid access token

        Raises:
            ValueError: If unable to obtain access token
        """
        async with self._lock:
            # Token is valid and not expiring soon - just return it
            if self._access_token and not self.is_token_expiring_soon():
                return self._access_token

            # SQLite mode: reload credentials first, kiro-cli might have updated them
            if self._sqlite_db and self.is_token_expiring_soon():
                logger.debug("SQLite mode: reloading credentials before refresh attempt")
                self._load_credentials_from_sqlite(self._sqlite_db)
                # Check if reloaded token is now valid
                if self._access_token and not self.is_token_expiring_soon():
                    logger.debug("SQLite reload provided fresh token, no refresh needed")
                    return self._access_token

            # Try to refresh token
            try:
                await self._refresh_token_request()
            except httpx.HTTPStatusError as e:
                # Graceful degradation for SQLite mode when refresh fails twice
                # This happens when kiro-cli refreshed tokens in memory without persisting
                if e.response.status_code == 400 and self._sqlite_db:
                    logger.warning(
                        "Token refresh failed with 400 after SQLite reload. "
                        "This may happen if kiro-cli refreshed tokens in memory without persisting."
                    )
                    # Check if access_token is still usable
                    if self._access_token and not self.is_token_expired():
                        logger.warning(
                            "Using existing access_token until it expires. "
                            "Run 'kiro-cli login' when convenient to refresh credentials."
                        )
                        return self._access_token
                    else:
                        raise ValueError(
                            "Token expired and refresh failed. "
                            "Please run 'kiro-cli login' to refresh your credentials."
                        )
                # Non-SQLite mode or non-400 error - propagate exception
                raise
            except Exception:
                # For any other exception, propagate it
                raise

            if not self._access_token:
                raise ValueError("Failed to obtain access token")

            return self._access_token

    async def force_refresh(self) -> str:
        """
        Forces a token refresh.

        Used when receiving a 403 error from the API.

        Returns:
            New access token
        """
        async with self._lock:
            await self._refresh_token_request()
            return self._access_token

    async def _background_token_refresh(self) -> None:
        """
        Background task that proactively refreshes token before expiry.

        Prevents the scenario where the server is idle, the token expires,
        and the next request hangs waiting for a slow/failed refresh.

        FIXED: Moved expiration check INSIDE the lock to prevent race conditions.
        """
        logger.info("Background token refresh task started (single-token mode)")

        while True:
            try:
                await asyncio.sleep(BACKGROUND_REFRESH_INTERVAL)

                if self._shutdown:
                    break

                # FIXED: Check expiration INSIDE the lock to avoid race condition
                # Previously we checked outside the lock, which could cause
                # token to expire before we acquired the lock
                async with self._lock:
                    if self._shutdown:
                        break

                    # Check if token needs refresh
                    if self.is_token_expiring_soon():
                        logger.info("Background refresh: token expiring soon, refreshing...")
                        try:
                            await self._refresh_token_request()
                            logger.info("Background refresh: token refreshed successfully")
                        except Exception as refresh_error:
                            logger.error(f"Background refresh failed: {refresh_error}")
                            # Don't log full traceback for expected network errors
                    else:
                        logger.debug("Background refresh: token still valid, skipping")

            except asyncio.CancelledError:
                logger.info("Background token refresh task cancelled")
                break
            except Exception as e:
                logger.error(f"Background refresh error: {e}")
                # Brief sleep before retry to avoid spinning on persistent errors
                await asyncio.sleep(30)

            if self._shutdown:
                break

        logger.info("Background token refresh task stopped")

    def start_background_refresh(self) -> None:
        """Start background token refresh task."""
        if not hasattr(self, '_background_task') or self._background_task is None or self._background_task.done():
            self._shutdown = False
            self._background_task = asyncio.create_task(self._background_token_refresh())
            logger.info("Background token refresh enabled (single-token mode)")

    async def stop_background_refresh(self) -> None:
        """Stop background token refresh task."""
        self._shutdown = True
        if hasattr(self, '_background_task') and self._background_task and not self._background_task.done():
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        logger.info("Background token refresh disabled")

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
        """API host for current region."""
        return self._api_host

    @property
    def q_host(self) -> str:
        """Q API host for current region."""
        return self._q_host

    @property
    def fingerprint(self) -> str:
        """Unique machine fingerprint."""
        return self._fingerprint

    @property
    def auth_type(self) -> AuthType:
        """Authentication type (KIRO_DESKTOP or AWS_SSO_OIDC)."""
        return self._auth_type
