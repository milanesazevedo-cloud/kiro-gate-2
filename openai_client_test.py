#!/usr/bin/env python3
"""
OpenAI-compatible client test for Kiro Gateway.
Run this locally to test the gateway after starting it.

Usage:
    python3 openai_client_test.py
"""

import os
import sys

# Configure OpenAI client to use Kiro Gateway
# The gateway is OpenAI-compatible, so we use the same interface

OPENAI_BASE_URL = "http://localhost:8000/v1"
OPENAI_API_KEY = "my-secure-password-change-this-2024"  # PROXY_API_KEY from .env

def test_with_openai_library():
    """Test using the official OpenAI library."""
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
        )

        print("=" * 60)
        print("OPENAI-COMPATIBLE CLIENT TEST")
        print("=" * 60)
        print(f"\nBase URL: {OPENAI_BASE_URL}")
        print(f"Model: claude-sonnet-4-20250506")

        # Test 1: List models
        print("\n[Test 1] Listing models...")
        try:
            models = client.models.list()
            print(f"  SUCCESS: Found {len(models.data)} models")
            for model in models.data[:5]:
                print(f"    - {model.id}")
        except Exception as e:
            print(f"  ERROR: {e}")

        # Test 2: Simple chat completion
        print("\n[Test 2] Testing chat completion...")
        try:
            response = client.chat.completions.create(
                model="claude-sonnet-4-20250506",
                messages=[
                    {"role": "user", "content": "Hello! This is a test. Respond with just 'OK'."}
                ],
                max_tokens=50,
            )
            print(f"  SUCCESS: {response.choices[0].message.content}")
        except Exception as e:
            print(f"  ERROR: {e}")

        print("\n" + "=" * 60)
        return True

    except ImportError:
        print("OpenAI library not installed. Install with: pip install openai")
        return False

def test_with_curl():
    """Test using curl (no Python dependencies)."""
    import subprocess

    print("\n" + "=" * 60)
    print("CURL TESTS (no Python required)")
    print("=" * 60)

    # Health check
    print("\n[curl 1] Health check...")
    result = subprocess.run(
        ["curl", "-s", "http://localhost:8000/health"],
        capture_output=True, text=True
    )
    print(f"  Response: {result.stdout.strip()}")

    # List models
    print("\n[curl 2] List models...")
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {OPENAI_API_KEY}",
         "http://localhost:8000/v1/models"],
        capture_output=True, text=True
    )
    print(f"  Response: {result.stdout.strip()[:200]}...")

    # Account status
    print("\n[curl 3] Account status (requires auth)...")
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {OPENAI_API_KEY}",
         "http://localhost:8000/v1/accounts/status"],
        capture_output=True, text=True
    )
    print(f"  Response: {result.stdout.strip()}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("KIRO GATEWAY - OPENAI COMPATIBILITY TEST")
    print("=" * 60)
    print("\nMake sure the gateway is running first:")
    print("  python3 main.py")
    print("\n")

    # Test with OpenAI library
    test_with_openai_library()

    # Test with curl
    test_with_curl()
