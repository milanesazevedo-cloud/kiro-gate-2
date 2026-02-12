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
Credential loading and saving mixin for KiroAuthManager.

Extracted from auth.py to keep file sizes manageable.
Contains all SQLite and JSON file credential I/O methods.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from kiro.config import get_kiro_refresh_url, get_kiro_api_host, get_kiro_q_host


# Supported SQLite token keys (searched in priority order)
SQLITE_TOKEN_KEYS = [
    "kirocli:social:token",      # Social login (Google, GitHub, Microsoft, etc.)
    "kirocli:odic:token",        # AWS SSO OIDC (kiro-cli corporate)
    "codewhisperer:odic:token",  # Legacy AWS SSO OIDC
]

# Device registration keys (for AWS SSO OIDC only)
SQLITE_REGISTRATION_KEYS = [
    "kirocli:odic:device-registration",
    "codewhisperer:odic:device-registration",
]


class KiroCredentialsMixin:
    """
    Mixin providing credential loading and saving for KiroAuthManager.

    Expects the following attributes to be set on the host class before
    any mixin method is called (all set in KiroAuthManager.__init__):

        _refresh_token, _access_token, _expires_at, _profile_arn,
        _region, _refresh_url, _api_host, _q_host,
        _client_id, _client_secret, _scopes, _sso_region,
        _client_id_hash, _sqlite_token_key, _creds_file, _sqlite_db
    """

    def _load_credentials_from_sqlite(self, db_path: str) -> None:
        """
        Loads credentials from kiro-cli SQLite database.

        The database contains an auth_kv table with key-value pairs.
        Supports multiple authentication types:

        Token keys (searched in priority order):
        - 'kirocli:social:token': Social login (Google, GitHub, etc.)
        - 'kirocli:odic:token': AWS SSO OIDC (kiro-cli corporate)
        - 'codewhisperer:odic:token': Legacy AWS SSO OIDC

        Device registration keys (for AWS SSO OIDC only):
        - 'kirocli:odic:device-registration': Client ID and secret
        - 'codewhisperer:odic:device-registration': Legacy format

        Args:
            db_path: Path to SQLite database file
        """
        try:
            path = Path(db_path).expanduser()
            if not path.exists():
                logger.warning(f"SQLite database not found: {db_path}")
                return

            conn = sqlite3.connect(str(path))
            cursor = conn.cursor()

            # Try all possible token keys in priority order
            token_row = None
            for key in SQLITE_TOKEN_KEYS:
                cursor.execute("SELECT value FROM auth_kv WHERE key = ?", (key,))
                token_row = cursor.fetchone()
                if token_row:
                    self._sqlite_token_key = key
                    logger.debug(f"Loaded credentials from SQLite key: {key}")
                    break

            if token_row:
                token_data = json.loads(token_row[0])
                if token_data:
                    if 'access_token' in token_data:
                        self._access_token = token_data['access_token']
                    if 'refresh_token' in token_data:
                        self._refresh_token = token_data['refresh_token']
                    if 'profile_arn' in token_data:
                        self._profile_arn = token_data['profile_arn']
                    if 'region' in token_data:
                        # Store SSO region for OIDC token refresh only.
                        # The CodeWhisperer API is only available in us-east-1,
                        # so api_host / q_host are NOT updated here.
                        self._sso_region = token_data['region']
                        logger.debug(
                            f"SSO region from SQLite: {self._sso_region} "
                            f"(API stays at {self._region})"
                        )
                    if 'scopes' in token_data:
                        self._scopes = token_data['scopes']
                    if 'expires_at' in token_data:
                        try:
                            expires_str = token_data['expires_at']
                            if expires_str.endswith('Z'):
                                self._expires_at = datetime.fromisoformat(
                                    expires_str.replace('Z', '+00:00')
                                )
                            else:
                                self._expires_at = datetime.fromisoformat(expires_str)
                        except Exception as e:
                            logger.warning(f"Failed to parse expires_at from SQLite: {e}")

            # Load device registration (client_id, client_secret)
            registration_row = None
            for key in SQLITE_REGISTRATION_KEYS:
                cursor.execute("SELECT value FROM auth_kv WHERE key = ?", (key,))
                registration_row = cursor.fetchone()
                if registration_row:
                    logger.debug(f"Loaded device registration from SQLite key: {key}")
                    break

            if registration_row:
                registration_data = json.loads(registration_row[0])
                if registration_data:
                    if 'client_id' in registration_data:
                        self._client_id = registration_data['client_id']
                    if 'client_secret' in registration_data:
                        self._client_secret = registration_data['client_secret']
                    if 'region' in registration_data and not self._sso_region:
                        self._sso_region = registration_data['region']
                        logger.debug(
                            f"SSO region from device-registration: {self._sso_region}"
                        )

            conn.close()
            logger.info(f"Credentials loaded from SQLite database: {db_path}")

        except sqlite3.Error as e:
            logger.error(f"SQLite error loading credentials: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in SQLite data: {e}")
        except Exception as e:
            logger.error(f"Error loading credentials from SQLite: {e}")

    def _load_credentials_from_file(self, file_path: str) -> None:
        """
        Loads credentials from a JSON file.

        Supported JSON fields (Kiro Desktop):
        - refreshToken, accessToken, profileArn, region, expiresAt

        Additional fields for AWS SSO OIDC (kiro-cli):
        - clientId, clientSecret

        For Enterprise Kiro IDE:
        - clientIdHash: triggers loading from ~/.aws/sso/cache/{hash}.json

        Args:
            file_path: Path to JSON file
        """
        try:
            path = Path(file_path).expanduser()
            if not path.exists():
                logger.warning(f"Credentials file not found: {file_path}")
                return

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if 'refreshToken' in data:
                self._refresh_token = data['refreshToken']
            if 'accessToken' in data:
                self._access_token = data['accessToken']
            if 'profileArn' in data:
                self._profile_arn = data['profileArn']
            if 'region' in data:
                self._region = data['region']
                self._refresh_url = get_kiro_refresh_url(self._region)
                self._api_host = get_kiro_api_host(self._region)
                self._q_host = get_kiro_q_host(self._region)
                logger.info(
                    f"Region updated from credentials file: region={self._region}, "
                    f"api_host={self._api_host}, q_host={self._q_host}"
                )

            if 'clientIdHash' in data:
                self._client_id_hash = data['clientIdHash']
                self._load_enterprise_device_registration(self._client_id_hash)

            if 'clientId' in data:
                self._client_id = data['clientId']
            if 'clientSecret' in data:
                self._client_secret = data['clientSecret']

            if 'expiresAt' in data:
                try:
                    expires_str = data['expiresAt']
                    if expires_str.endswith('Z'):
                        self._expires_at = datetime.fromisoformat(
                            expires_str.replace('Z', '+00:00')
                        )
                    else:
                        self._expires_at = datetime.fromisoformat(expires_str)
                except Exception as e:
                    logger.warning(f"Failed to parse expiresAt: {e}")

            logger.info(f"Credentials loaded from {file_path}")

        except Exception as e:
            logger.error(f"Error loading credentials from file: {e}")

    def _load_enterprise_device_registration(self, client_id_hash: str) -> None:
        """
        Loads clientId and clientSecret from Enterprise Kiro IDE device registration.

        Device registration is stored at:
        ~/.aws/sso/cache/{clientIdHash}.json

        Args:
            client_id_hash: Client ID hash used to locate the registration file
        """
        try:
            device_reg_path = (
                Path.home() / ".aws" / "sso" / "cache" / f"{client_id_hash}.json"
            )
            if not device_reg_path.exists():
                logger.warning(
                    f"Enterprise device registration file not found: {device_reg_path}"
                )
                return

            with open(device_reg_path, 'r', encoding='utf-8') as f:
                device_data = json.load(f)

            if 'clientId' in device_data:
                self._client_id = device_data['clientId']
            if 'clientSecret' in device_data:
                self._client_secret = device_data['clientSecret']

            logger.info(f"Enterprise device registration loaded from {device_reg_path}")

        except Exception as e:
            logger.error(f"Error loading enterprise device registration: {e}")

    def _save_credentials_to_file(self) -> None:
        """Saves updated credentials to the JSON file, preserving other fields."""
        if not self._creds_file:
            return

        try:
            path = Path(self._creds_file).expanduser()
            existing_data: dict = {}
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)

            existing_data['accessToken'] = self._access_token
            existing_data['refreshToken'] = self._refresh_token
            if self._expires_at:
                existing_data['expiresAt'] = self._expires_at.isoformat()
            if self._profile_arn:
                existing_data['profileArn'] = self._profile_arn

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Credentials saved to {self._creds_file}")

        except Exception as e:
            logger.error(f"Error saving credentials: {e}")

    def _save_credentials_to_sqlite(self) -> None:
        """
        Saves updated credentials back to SQLite database.

        Persists tokens refreshed by the gateway so they are available
        after restart or for other processes reading the same database.

        Strategy: save to the key we loaded from (_sqlite_token_key).
        Falls back to trying all supported keys if that fails.
        """
        if not self._sqlite_db:
            return

        try:
            path = Path(self._sqlite_db).expanduser()
            if not path.exists():
                logger.warning(
                    f"SQLite database not found for writing: {self._sqlite_db}"
                )
                return

            conn = sqlite3.connect(str(path), timeout=5.0)
            cursor = conn.cursor()

            token_data: dict = {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "expires_at": self._expires_at.isoformat() if self._expires_at else None,
                "region": self._sso_region or self._region,
            }
            if self._scopes:
                token_data["scopes"] = self._scopes

            token_json = json.dumps(token_data)

            if self._sqlite_token_key:
                cursor.execute(
                    "UPDATE auth_kv SET value = ? WHERE key = ?",
                    (token_json, self._sqlite_token_key),
                )
                if cursor.rowcount > 0:
                    conn.commit()
                    conn.close()
                    logger.debug(
                        f"Credentials saved to SQLite key: {self._sqlite_token_key}"
                    )
                    return
                else:
                    logger.warning(
                        f"Failed to update SQLite key: {self._sqlite_token_key}, "
                        "trying fallback"
                    )

            for key in SQLITE_TOKEN_KEYS:
                cursor.execute(
                    "UPDATE auth_kv SET value = ? WHERE key = ?",
                    (token_json, key),
                )
                if cursor.rowcount > 0:
                    conn.commit()
                    conn.close()
                    logger.debug(f"Credentials saved to SQLite key: {key} (fallback)")
                    return

            conn.close()
            logger.warning(
                "Failed to save credentials to SQLite: no matching keys found"
            )

        except sqlite3.Error as e:
            logger.error(f"SQLite error saving credentials: {e}")
        except Exception as e:
            logger.error(f"Error saving credentials to SQLite: {e}")
