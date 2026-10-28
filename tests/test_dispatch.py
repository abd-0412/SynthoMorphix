"""
SynthoMorphix: Cloud AI Dispatch Test Suite
Verifies POST /api/v1/dispatch-ai, instruction scrubbing, API key safety,
error handling mappings, offline mock fallback, and egress previews.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict
import pytest
import httpx
from fastapi.testclient import TestClient

# Ensure root in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app, RAM_VAULT_REGISTRY, SESSION_METADATA_STORE


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure in-memory stores are pristine for each test."""
    RAM_VAULT_REGISTRY.clear()
    SESSION_METADATA_STORE.clear()
    yield
    RAM_VAULT_REGISTRY.clear()
    SESSION_METADATA_STORE.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_dispatch_no_key_mock_offline_labeled(client, monkeypatch):
    """(Req 17) Cover: no key -> MOCK_OFFLINE and labeled."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # First scrub code to populate session
    code = "def calculate_pay(rate, hours):\n    gross = rate * hours\n    return gross\n"
    scrub_resp = client.post("/api/v1/scrub", json={"source_code": code, "mask_level": "L1"})
    assert scrub_resp.status_code == 200
    session_id = scrub_resp.json()["session_id"]

    # Dispatch with no API key
    disp_resp = client.post(
        "/api/v1/dispatch-ai",
        json={
            "instruction": "Fix bugs and improve code",
            "session_id": session_id,
            "api_key": None,
        },
    )
    assert disp_resp.status_code == 200
    data = disp_resp.json()
    assert data["status"] == "SUCCESS"
    assert data["inference_mode"] == "MOCK_OFFLINE"
    assert data["model"] is None
    assert "[MOCK_OFFLINE]" in data["raw_llm_response"]
    assert "def calculate_pay(rate, hours):" in data["reconstructed_code"]
    assert data["exact_match"] is True
    assert data["tokens_restored"] >= 3
    assert data["dropped_tokens"] == []


def test_dispatch_with_key_mocked_200_fences(client, monkeypatch):
    """(Req 17) Cover: key + mocked 200 response with fences -> REAL_CLOUD_LLM, tokens restored."""
    code = "def process_data(user_id, count):\n    total = count * 2\n    return total\n"
    scrub_resp = client.post("/api/v1/scrub", json={"source_code": code, "mask_level": "L1"})
    session_id = scrub_resp.json()["session_id"]
    scrubbed_code = scrub_resp.json()["scrubbed_code"]

    fake_llm_body = f"Here is the improved solution:\n```python\n# Refactored\n{scrubbed_code}\n```\nLooks good!"

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, headers=None, json=None):
            assert "Authorization" in headers
            assert headers["Authorization"] == "Bearer gsk_secret_12345"
            return httpx.Response(
                status_code=200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": fake_llm_body}}
                    ]
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    disp_resp = client.post(
        "/api/v1/dispatch-ai",
        json={
            "instruction": "Optimize calculations",
            "session_id": session_id,
            "api_key": "gsk_secret_12345",
        },
    )
    assert disp_resp.status_code == 200
    data = disp_resp.json()
    assert data["status"] == "SUCCESS"
    assert data["inference_mode"] == "REAL_CLOUD_LLM"
    assert data["model"] == "llama-3.1-8b-instant"
    assert data["exact_match"] is True
    assert data["tokens_restored"] >= 3
    assert "def process_data(user_id, count):" in data["reconstructed_code"]
    assert data["dropped_tokens"] == []


def test_dispatch_response_with_hallucinated_token(client, monkeypatch):
    """(Req 17) Cover: response with hallucinated fn_99 -> exact_match false and unmapped list."""
    code = "def compute_tax(subtotal):\n    return subtotal * 0.1\n"
    scrub_resp = client.post("/api/v1/scrub", json={"source_code": code, "mask_level": "L1"})
    session_id = scrub_resp.json()["session_id"]

    vault = RAM_VAULT_REGISTRY[session_id]
    synth_fn = [k for k, v in vault.items() if v == "compute_tax"][0]
    synth_arg = [k for k, v in vault.items() if v == "subtotal"][0]

    hallucinated_llm = f"```python\ndef {synth_fn}({synth_arg}):\n    return fn_99({synth_arg})\n```"

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, headers=None, json=None):
            return httpx.Response(
                status_code=200,
                json={"choices": [{"message": {"role": "assistant", "content": hallucinated_llm}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    disp_resp = client.post(
        "/api/v1/dispatch-ai",
        json={
            "instruction": "Refactor logic",
            "session_id": session_id,
            "api_key": "gsk_test_key",
        },
    )
    assert disp_resp.status_code == 200
    data = disp_resp.json()
    assert data["exact_match"] is False
    assert "fn_99" in data["unmapped_tokens"]
    assert "def compute_tax(subtotal):" in data["reconstructed_code"]


def test_dispatch_gating_blocked_expired_no_payload(client):
    """(Req 17) Cover: blocked/expired/no-payload session -> 409."""
    # 1. Non-existent session
    resp1 = client.post(
        "/api/v1/dispatch-ai",
        json={"instruction": "test", "session_id": "non_existent_uuid"},
    )
    assert resp1.status_code == 409
    assert "expired" in resp1.json()["detail"].lower() or "stored payload" in resp1.json()["detail"].lower()

    # 2. Blocked dynamic risk session
    dyn_code = "eval('import os; os.system(\"ls\")')\n"
    scrub_resp = client.post("/api/v1/scrub", json={"source_code": dyn_code, "mask_level": "L1"})
    assert scrub_resp.status_code == 200
    assert scrub_resp.json()["status"] == "BLOCKED_DYNAMIC_RISK"
    dyn_session_id = scrub_resp.json()["session_id"]

    resp2 = client.post(
        "/api/v1/dispatch-ai",
        json={"instruction": "test", "session_id": dyn_session_id},
    )
    assert resp2.status_code == 409
    assert "blocked" in resp2.json()["detail"].lower()


def test_instruction_scrubbing_replaces_original_identifiers(client, monkeypatch):
    """(Req 17) Cover: instruction containing an original identifier is replaced with its token in what is sent."""
    code = "def execute_disbursement(company_id, bonus_rate):\n    return company_id + bonus_rate\n"
    scrub_resp = client.post("/api/v1/scrub", json={"source_code": code, "mask_level": "L1"})
    session_id = scrub_resp.json()["session_id"]
    vault = RAM_VAULT_REGISTRY[session_id]

    sent_user_message = ""

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, headers=None, json=None):
            nonlocal sent_user_message
            sent_user_message = json["messages"][1]["content"]
            return httpx.Response(
                status_code=200,
                json={"choices": [{"message": {"role": "assistant", "content": "```python\n# ok\n```"}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    # Instruction explicitly uses original project names: execute_disbursement, company_id, bonus_rate
    raw_instruction = "Please review execute_disbursement for employee bonus_rate and company_id"
    disp_resp = client.post(
        "/api/v1/dispatch-ai",
        json={
            "instruction": raw_instruction,
            "session_id": session_id,
            "api_key": "gsk_test_key",
        },
    )
    assert disp_resp.status_code == 200
    data = disp_resp.json()
    scrubbed_inst = data["instruction_sent"]

    # Verify original names are replaced in instruction_sent and in sent_user_message
    assert "execute_disbursement" not in scrubbed_inst
    assert "company_id" not in scrubbed_inst
    assert "bonus_rate" not in scrubbed_inst
    assert "execute_disbursement" not in sent_user_message
    assert "company_id" not in sent_user_message
    assert "bonus_rate" not in sent_user_message


def test_api_key_safety_logs_responses_exceptions(client, monkeypatch, caplog):
    """(Req 8 & 17) Cover: API key absent from logs, responses, and error bodies (also when call raises)."""
    caplog.set_level(logging.DEBUG)
    test_key = "gsk_SUPER_SECRET_LEAK_TARGET_99999"

    code = "def my_func(x): return x * 2\n"
    scrub_resp = client.post("/api/v1/scrub", json={"source_code": code, "mask_level": "L1"})
    session_id = scrub_resp.json()["session_id"]

    # Case A: Mock error that embeds the key in its exception message
    class LeakyExceptionAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, headers=None, json=None):
            raise httpx.RequestError(f"Connection error to {url} with key {test_key}")

    monkeypatch.setattr(httpx, "AsyncClient", LeakyExceptionAsyncClient)

    disp_resp = client.post(
        "/api/v1/dispatch-ai",
        json={
            "instruction": "Review code",
            "session_id": session_id,
            "api_key": test_key,
        },
    )
    assert disp_resp.status_code == 200
    data = disp_resp.json()
    assert data["status"] == "NETWORK_ERROR"

    # Verify key is never in response body or egress_preview
    resp_text = disp_resp.text
    assert test_key not in resp_text
    assert test_key not in json.dumps(data["egress_preview"])
    assert "[REDACTED_API_KEY]" in data["error"]

    # Verify key is not in logs
    assert test_key not in caplog.text


def test_error_status_mappings(client, monkeypatch):
    """(Req 7 & 17) Cover: 401, 429, timeout, malformed JSON map to clean statuses."""
    code = "def sample(a): return a\n"
    scrub_resp = client.post("/api/v1/scrub", json={"source_code": code, "mask_level": "L1"})
    session_id = scrub_resp.json()["session_id"]

    # 1. HTTP 401 -> AUTH_ERROR
    class Mock401Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, headers=None, json=None):
            return httpx.Response(status_code=401, text="Unauthorized", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", Mock401Client)
    res_401 = client.post("/api/v1/dispatch-ai", json={"instruction": "hi", "session_id": session_id, "api_key": "k"}).json()
    assert res_401["status"] == "AUTH_ERROR"

    # 2. HTTP 429 -> RATE_LIMITED
    class Mock429Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, headers=None, json=None):
            return httpx.Response(status_code=429, text="Too Many Requests", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", Mock429Client)
    res_429 = client.post("/api/v1/dispatch-ai", json={"instruction": "hi", "session_id": session_id, "api_key": "k"}).json()
    assert res_429["status"] == "RATE_LIMITED"

    # 3. Timeout -> TIMEOUT
    class MockTimeoutClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, headers=None, json=None):
            raise httpx.TimeoutException("Connection timed out")

    monkeypatch.setattr(httpx, "AsyncClient", MockTimeoutClient)
    res_timeout = client.post("/api/v1/dispatch-ai", json={"instruction": "hi", "session_id": session_id, "api_key": "k"}).json()
    assert res_timeout["status"] == "TIMEOUT"

    # 4. Malformed JSON -> BAD_LLM_RESPONSE
    class MockMalformedClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, headers=None, json=None):
            return httpx.Response(status_code=200, text="Not valid json", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", MockMalformedClient)
    res_malformed = client.post("/api/v1/dispatch-ai", json={"instruction": "hi", "session_id": session_id, "api_key": "k"}).json()
    assert res_malformed["status"] == "BAD_LLM_RESPONSE"


def test_egress_preview_equals_actual_body_sent(client, monkeypatch):
    """(Req 3 & 17) Cover: egress_preview equals the body actually sent."""
    code = "def process(item): return item + 1\n"
    scrub_resp = client.post("/api/v1/scrub", json={"source_code": code, "mask_level": "L1"})
    session_id = scrub_resp.json()["session_id"]

    captured_payload = {}

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, headers=None, json=None):
            nonlocal captured_payload
            captured_payload = json
            return httpx.Response(
                status_code=200,
                json={"choices": [{"message": {"role": "assistant", "content": "```python\n# ok\n```"}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    disp_resp = client.post(
        "/api/v1/dispatch-ai",
        json={"instruction": "Check item", "session_id": session_id, "api_key": "gsk_key"},
    )
    assert disp_resp.status_code == 200
    data = disp_resp.json()

    # The messages in egress_preview must match captured_payload["messages"] exactly
    assert data["egress_preview"]["messages"] == captured_payload["messages"]


def test_health_endpoint_fields(client):
    """(Req 9) Cover: /health has version, active_sessions, has_groq_key, groq_model."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "UP"
    assert "version" in data
    assert "active_sessions" in data
    assert "has_groq_key" in data
    assert isinstance(data["has_groq_key"], bool)
    assert "groq_model" in data
    assert data["groq_model"] == "llama-3.1-8b-instant"
