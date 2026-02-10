#!/usr/bin/env python3
"""
Test script for Kiro Gateway token validation.
Run locally with: python3 test_token.py
"""

import os
import sys

# Test token format validation
REFRESH_TOKEN = "aoaAAAAAGoBMgoZ35zLGTGQVRP-zbCWs7nQGrND2350j3XZYzMOVZS513VoNkOsy-V5F85WpoGoMdM84rhEGZ25W4Bkc0:MGYCMQCQHeSroOXm2cpoR9CrZmTtYbt9rBrUxIfu6eVOV/Ja5SlNnZubBPjK26qR45noEZECMQC4feAMXEjwSXlW2PY4nReGna9jkfvZM37AqYeyB96Hdt3N+eTg8ZpNKqfQLX0finI"

ACCESS_TOKEN = "aoaAAAAAGmKmRowdoRJCVpgnfVo8P2qeS16aBpp5VS4u-yB-hW1Z32KwdWLw3T5IOA1soMfzEf33d_PU3Dx9eauLsBkc0:MGUCMHWE7Qu6VVoe60e6FiQuuNqwMN9jIIREBlKCSXtfTG7ZFxbwQd4csmt5z8aQb8A1GwIxAJVZBQdzNcma3+XXo1EEXL4NRP+01QNKQjVLAu4pS0DB0QH9t8qpP/vOFS0Jq+B1GA"

KIRO_VISITOR_ID = "1770687212106-469idblwt7y"

def validate_token_format(token: str, name: str) -> bool:
    """Validate basic token format."""
    print(f"\n=== Validating {name} ===")
    print(f"Length: {len(token)} characters")

    # Check for Amazon Q Developer format (contains colons)
    parts = token.split(':')
    if len(parts) == 2:
        print(f"Format: Amazon Q Developer (userId:encryptedToken)")
        print(f"User ID part: {parts[0][:20]}...")
        print(f"Encrypted token part: {parts[1][:20]}...")
        return True
    else:
        print(f"WARNING: Unexpected format (expected 2 parts, got {len(parts)})")
        return False

def main():
    print("=" * 60)
    print("KIRO GATEWAY TOKEN VALIDATION TEST")
    print("=" * 60)

    # Validate tokens
    refresh_valid = validate_token_format(REFRESH_TOKEN, "Refresh Token")
    access_valid = validate_token_format(ACCESS_TOKEN, "Access Token")

    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    print(f"Refresh Token:  {'VALID' if refresh_valid else 'INVALID'}")
    print(f"Access Token:   {'VALID' if access_valid else 'INVALID'}")
    print(f"Visitor ID:     {KIRO_VISITOR_ID}")

    if refresh_valid and access_valid:
        print("\n[SUCCESS] All tokens are in valid format!")
        print("\nTo test with Docker:")
        print("  1. Configure .env with these tokens")
        print("  2. Run: docker-compose up -d")
        print("  3. Test: curl http://localhost:8000/health")
        return 0
    else:
        print("\n[ERROR] Token validation failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
