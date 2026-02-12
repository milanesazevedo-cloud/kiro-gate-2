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
Shared rate limiter instance.

Centralises the slowapi Limiter so that main.py and route modules
all reference the same object without circular imports.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from kiro.config import RATE_LIMIT_RPM

# Shared limiter instance.  Disabled when RATE_LIMIT_RPM == 0.
limiter: Limiter = Limiter(
    key_func=get_remote_address,
    enabled=RATE_LIMIT_RPM > 0,
)

# Pre-built limit string used by all inference route decorators.
INFERENCE_RATE_LIMIT: str = f"{RATE_LIMIT_RPM}/minute"
