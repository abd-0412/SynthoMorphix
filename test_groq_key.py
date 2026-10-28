"""
Diagnostic script for Groq API integration in SynthoMorphix.
Checks .env presence, key validity, model configuration, and performs a direct test call.
"""

import asyncio
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
    has_dotenv = True
except ImportError:
    has_dotenv = False

import httpx

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


def check_env_file() -> bool:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    print("=" * 60)
    print("STEP 1: .env VERIFICATION")
    print("=" * 60)
    if not os.path.exists(env_path):
        print(".env check: FAIL (.env file does not exist in root folder)")
        return False

    key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "").strip()

    if not key:
        print(".env check: FAIL (GROQ_API_KEY is missing or empty)")
        return False

    if not model:
        print(".env check: FAIL (GROQ_MODEL is missing or empty)")
        return False

    print(f".env check: PASS (GROQ_API_KEY found, GROQ_MODEL='{model}')")
    return True


async def run_groq_direct_call():
    print("\n" + "=" * 60)
    print("STEP 2: GROQ KEY & DIRECT DISPATCH TEST")
    print("=" * 60)

    key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip()

    print(f"python-dotenv available : {has_dotenv}")
    print(f"Configured GROQ_MODEL   : {model}")
    print(f"Key present             : {bool(key)}")
    print(f"Key length              : {len(key)}")
    print(f"Key prefix (first 10)   : {key[:10]}...")

    if not key:
        print("ERROR: No GROQ_API_KEY found. Exiting.")
        return

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "say hello"}],
        "max_tokens": 10,
        "temperature": 0,
    }

    print(f"\nSending test POST request to {GROQ_ENDPOINT}...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(GROQ_ENDPOINT, headers=headers, json=payload)

        print(f"HTTP Status Code        : {resp.status_code}")
        print(f"Raw Response Body       : {resp.text}")

        if resp.status_code == 200:
            print("\nDIAGNOSIS: Groq API key is valid. The issue is in main.py request construction.")
            try:
                res_json = resp.json()
                reply = res_json["choices"][0]["message"]["content"]
                print(f"Groq Response Text      : {reply.strip()}")
            except Exception:
                pass
        elif resp.status_code == 401:
            print("\nDIAGNOSIS: Key rejected by Groq. Check:")
            print("  1) Key expiry or deletion in Groq console (console.groq.com/keys)")
            print("  2) No extra spaces or quotes in .env")
            print("  3) Model name in console")
        elif resp.status_code == 404:
            print(f"\nDIAGNOSIS: Model '{model}' not found or endpoint incorrect.")
        elif resp.status_code == 429:
            print("\nDIAGNOSIS: Rate limit reached or quota exceeded on Groq account.")
        else:
            print(f"\nDIAGNOSIS: Groq returned unexpected status {resp.status_code}.")

    except Exception as exc:
        print(f"Connection / Request Error: {exc}")


if __name__ == "__main__":
    check_env_file()
    asyncio.run(run_groq_direct_call())
