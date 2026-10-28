"""
SynthoMorphix: Local Loopback Gateway Daemon
Base Paper: Zhou Yang et al., IEEE Transactions on Software Engineering (TSE) 2024.
Reference: Local-Loopback Security Architecture & Ephemeral Vault Management.

This module implements the production FastAPI loopback gateway daemon that mediates
between local development environments / clients and external cloud LLMs.
It enforces zero-disk leakage (NFR-02) via volatile RAM-only session storage,
strict CORS whitelisting, dynamic reflection safety gating, and session purging (FR-04).
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from synthomorphix import engine, reconstructor
except ImportError:
    import engine  # type: ignore
    import reconstructor  # type: ignore

logger = logging.getLogger("synthomorphix.gateway")

# Dedicated in-memory registry residing strictly in volatile local memory (RAM).
# Zero disk or external DB writes to satisfy Non-Functional Requirement NFR-02 (Zero Local Leakage).
RAM_VAULT_REGISTRY: Dict[str, Dict[str, str]] = {}

# Session payload and status store for dispatch gating (RAM-only)
SESSION_METADATA_STORE: Dict[str, Dict[str, Any]] = {}

app = FastAPI(
    title="SynthoMorphix Local Gateway Daemon",
    description="Compiler gateway for AST-based de-identification and deterministic suture reconstruction.",
    version="3.2.0",
)

# Security Hardening: Implement CORSMiddleware with a strict origin whitelist
# allowing ONLY local browser and loopback callers.
# Wildcard '*' origins are strictly disallowed to eliminate cross-origin hijacking risks.
ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "null",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ==========================================
# Pydantic Request & Response Schemas
# ==========================================


class DesensitizeRequest(BaseModel):
    source_code: str = Field(..., description="Raw Python source code to be scrubbed")
    mask_level: str = Field(default="L1", description="Masking level: 'L0', 'L1', or 'L2'")
    session_id: Optional[str] = Field(default=None, description="Optional existing session UUID")


class DesensitizeResponse(BaseModel):
    session_id: str
    status: str
    scrubbed_code: str
    error: Optional[str] = None
    tokens_isolated: int
    dynamic_risk: bool
    policy_status: Optional[str] = None


class SutureRequest(BaseModel):
    llm_output: str = Field(..., description="Raw output received from the Cloud LLM")
    session_id: str = Field(..., description="UUID session identifier mapped to the ephemeral vault")


class SutureResponse(BaseModel):
    status: str
    reconstructed_code: str
    exact_match: bool
    unmapped_tokens: List[str]
    tokens_restored: int
    error: Optional[str] = None


class DispatchAiRequest(BaseModel):
    instruction: str = Field(..., description="User instruction to guide LLM improvement")
    session_id: str = Field(..., description="UUID session identifier")
    api_key: Optional[str] = Field(default=None, description="Optional Groq API key")


class DispatchAiResponse(BaseModel):
    status: str
    inference_mode: str  # "REAL_CLOUD_LLM" | "MOCK_OFFLINE"
    model: Optional[str] = None
    raw_llm_response: str
    reconstructed_code: str
    exact_match: bool
    tokens_restored: int
    unmapped_tokens: List[str]
    dropped_tokens: List[str]
    instruction_sent: str
    egress_preview: Dict[str, Any]
    payload_bytes: int
    latency_ms: float
    error: Optional[str] = None


class SessionClearRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, description="Session UUID to purge from RAM")


class SessionClearResponse(BaseModel):
    status: str
    session_id: str
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    active_sessions: int
    has_groq_key: bool
    groq_model: str


from fastapi.responses import FileResponse

# ==========================================
# Helpers for Instruction Scrubbing & Egress
# ==========================================

SYSTEM_PROMPT = (
    "You are an expert code reviewer. Improve or fix bugs in the provided Python code. "
    "Return ONLY valid Python code inside ```python fences. "
    "Keep every synthetic identifier exactly as written (fn_XX, var_XX, arg_XX, cls_XX, str_XX)."
)


def scrub_instruction_text(instruction: str, reverse_vault: Dict[str, str]) -> str:
    """
    Replaces whole-word occurrences of the vault's ORIGINAL identifiers inside instruction
    with their corresponding synthetic tokens.
    """
    if not instruction or not reverse_vault:
        return instruction

    # Invert reverse_vault: original_ident -> synthetic_token
    # Sort original identifiers by descending length to prevent prefix collisions
    orig_to_synth: Dict[str, str] = {orig: synth for synth, orig in reverse_vault.items()}
    sorted_origs = sorted(orig_to_synth.keys(), key=len, reverse=True)
    if not sorted_origs:
        return instruction

    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted_origs) + r")\b")

    def _replace(match: re.Match) -> str:
        word = match.group(0)
        return orig_to_synth.get(word, word)

    return pattern.sub(_replace, instruction)


def redact_key(text: str, key: Optional[str]) -> str:
    """Redacts any occurrence of key from exception/error messages."""
    if not key or not text:
        return text
    return text.replace(key, "[REDACTED_API_KEY]")


def extract_code_from_llm(raw_text: str) -> str:
    """
    Extracts code from the first ```python fence, or falls back to whole text.
    """
    fence_pattern = re.compile(r"```(?:python|py)?\r?\n([\s\S]*?)```", re.IGNORECASE)
    match = fence_pattern.search(raw_text)
    if match:
        return match.group(1).strip()
    return raw_text.strip()


def generate_mock_llm_response(scrubbed_code: str) -> str:
    """
    Produces deterministic offline mock response preserving synthetic tokens
    with a clean non-breaking top comment.
    """
    return f"```python\n# [MOCK_OFFLINE] Logic verified by SynthoMorphix loopback gateway\n{scrubbed_code}\n```"

# ==========================================
# API Routes
# ==========================================


@app.get("/", response_class=FileResponse, tags=["Dashboard"])
async def get_dashboard() -> FileResponse:
    """
    Serves the SynthoMorphix executive security dashboard directly on loopback root.
    """
    return FileResponse("index.html")


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def get_health() -> HealthResponse:
    """
    Returns loopback gateway health status, daemon version, active RAM session count,
    configured Groq model, and whether a Groq API key is configured.
    """
    model_name = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    has_key = bool(os.getenv("GROQ_API_KEY"))
    return HealthResponse(
        status="UP",
        version="3.2.0",
        active_sessions=len(RAM_VAULT_REGISTRY),
        has_groq_key=has_key,
        groq_model=model_name,
    )


@app.post("/api/v1/scrub", response_model=DesensitizeResponse, tags=["De-identification"])
async def scrub_source_code(req: DesensitizeRequest) -> DesensitizeResponse:
    """
    Endpoint 1: De-identifies source code using modern Tree-sitter AST transformation.
    Caches the ephemeral reverse vault in volatile memory (RAM_VAULT_REGISTRY).
    """
    session_id = req.session_id if req.session_id else str(uuid.uuid4())

    try:
        scrub_result = engine.analyze_and_scrub(
            source_code=req.source_code,
            mask_level=req.mask_level,
            dynamic_policy="block",
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve),
        )
    except Exception as exc:
        SESSION_METADATA_STORE[session_id] = {
            "status": "ERROR",
            "scrubbed_code": "",
            "tokens_isolated": 0,
        }
        return DesensitizeResponse(
            session_id=session_id,
            status="ERROR",
            scrubbed_code=req.source_code,
            error=str(exc),
            tokens_isolated=0,
            dynamic_risk=False,
        )

    status_str = scrub_result.get("status", "SUCCESS")
    has_dyn = scrub_result.get("dynamic_risk", False)
    policy_st = "blocked" if status_str == "BLOCKED_DYNAMIC_RISK" else ("pass-through" if has_dyn else "none")
    out_code = "" if status_str == "BLOCKED_DYNAMIC_RISK" else scrub_result.get("scrubbed_code", req.source_code)

    # Store ephemeral reverse vault in RAM registry if successful
    if status_str == "SUCCESS":
        RAM_VAULT_REGISTRY[session_id] = scrub_result.get("reverse_vault", {})

    # Store session metadata for dispatch gating
    SESSION_METADATA_STORE[session_id] = {
        "status": status_str,
        "scrubbed_code": out_code,
        "tokens_isolated": scrub_result.get("tokens_isolated", 0),
    }

    return DesensitizeResponse(
        session_id=session_id,
        status=status_str,
        scrubbed_code=out_code,
        error=None,
        tokens_isolated=scrub_result.get("tokens_isolated", 0),
        dynamic_risk=has_dyn,
        policy_status=policy_st,
    )


@app.post("/api/v1/suture", response_model=SutureResponse, tags=["Reconstruction"])
async def suture_llm_response(req: SutureRequest) -> SutureResponse:
    """
    Endpoint 2: Restores de-identified tokens in Cloud LLM response using the in-memory vault.
    Handles Markdown code fences, prose preservation, and collision prevention.
    """
    if req.session_id not in RAM_VAULT_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{req.session_id}' not found in volatile memory. It may have expired or been purged.",
        )

    vault = RAM_VAULT_REGISTRY[req.session_id]

    try:
        rec_report = reconstructor.reconstruct_solution(
            raw_llm_response=req.llm_output,
            reverse_vault=vault,
        )
    except Exception as exc:
        return SutureResponse(
            status="ERROR",
            reconstructed_code=req.llm_output,
            exact_match=False,
            unmapped_tokens=[],
            tokens_restored=0,
            error=str(exc),
        )

    return SutureResponse(
        status="SUCCESS",
        reconstructed_code=rec_report["reconstructed_text"],
        exact_match=rec_report["exact_match"],
        unmapped_tokens=rec_report["unmapped_tokens"],
        tokens_restored=rec_report["tokens_restored"],
        error=None,
    )


@app.post("/api/v1/dispatch-ai", response_model=DispatchAiResponse, tags=["Cloud AI Dispatch"])
async def dispatch_ai(req: DispatchAiRequest) -> DispatchAiResponse:
    """
    Endpoint 4: Dispatches scrubbed code and scrubbed user instruction to Cloud LLM (Groq)
    or offline mock LLM. Suture reconstructs the response using the session vault.
    """
    # 1. Validate instruction length
    if len(req.instruction) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instruction exceeds maximum length of 1000 characters.",
        )

    session_id = req.session_id

    # 2. Gating checks on session
    if session_id not in SESSION_METADATA_STORE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session '{session_id}' has no stored payload or has expired.",
        )

    meta = SESSION_METADATA_STORE[session_id]
    if meta.get("status") == "BLOCKED_DYNAMIC_RISK":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session was blocked due to dynamic reflection risk (BLOCKED_DYNAMIC_RISK). Cannot dispatch.",
        )

    if session_id not in RAM_VAULT_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session '{session_id}' has no stored payload or has expired.",
        )

    scrubbed_code = meta.get("scrubbed_code", "")
    if not scrubbed_code or meta.get("status") != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session does not have a valid scrubbed payload.",
        )

    vault = RAM_VAULT_REGISTRY[session_id]

    # 3. Instruction scrubbing (replace original identifiers with synthetic tokens)
    scrubbed_instruction = scrub_instruction_text(req.instruction, vault)

    # 4. Construct user message and egress record
    user_message = f"{scrubbed_instruction}\n\n{scrubbed_code}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    egress_preview = {
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "messages": messages,
    }
    payload_bytes = len(user_message.encode("utf-8")) + len(SYSTEM_PROMPT.encode("utf-8"))

    # 5. Resolve API Key & determine inference mode
    # Key must NEVER be logged, stored on disk, put in session, or echoed in responses
    api_key = req.api_key or os.getenv("GROQ_API_KEY")
    groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    # Helper to calculate dropped tokens
    # Dropped tokens: synthetic tokens present in the scrubbed input that do NOT appear anywhere in the LLM response
    input_synthetic_tokens = set(re.findall(r"\b(?:fn|var|cls|arg|str|cmt)_\d{2,}\b", scrubbed_code))

    def _calc_dropped(raw_llm: str) -> List[str]:
        output_synthetic_tokens = set(re.findall(r"\b(?:fn|var|cls|arg|str|cmt)_\d{2,}\b", raw_llm))
        return sorted(list(input_synthetic_tokens - output_synthetic_tokens))

    # Offline Mock Flow
    if not api_key:
        start_t = time.perf_counter()
        raw_llm_response = generate_mock_llm_response(scrubbed_code)
        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)

        code_to_suture = extract_code_from_llm(raw_llm_response)
        suture_res = reconstructor.reconstruct_solution(code_to_suture, vault)

        return DispatchAiResponse(
            status="SUCCESS",
            inference_mode="MOCK_OFFLINE",
            model=None,
            raw_llm_response=raw_llm_response,
            reconstructed_code=suture_res["reconstructed_text"],
            exact_match=suture_res["exact_match"],
            tokens_restored=suture_res["tokens_restored"],
            unmapped_tokens=suture_res["unmapped_tokens"],
            dropped_tokens=_calc_dropped(raw_llm_response),
            instruction_sent=scrubbed_instruction,
            egress_preview=egress_preview,
            payload_bytes=payload_bytes,
            latency_ms=latency_ms,
            error=None,
        )

    # Real Cloud LLM Flow via Groq OpenAI-compatible endpoint
    start_t = time.perf_counter()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    groq_payload = {
        "model": groq_model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 2048,
    }

    debug_mode = os.getenv("DEBUG_MODE") in ("1", "true", "True")
    if debug_mode:
        print(f"DISPATCH_AI: instruction_sent length = {len(scrubbed_instruction)}")
        print(f"DISPATCH_AI: request headers Authorization header set = {'Bearer' in headers.get('Authorization', '')}")
        print(f"DISPATCH_AI: request body model = {groq_model}")
        print("DISPATCH_AI: timeout = 30.0")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=groq_payload,
            )
            latency_ms = round((time.perf_counter() - start_t) * 1000, 2)

            if debug_mode:
                print(f"DISPATCH_AI: HTTP {resp.status_code} from Groq")

            if resp.status_code in (401, 403):
                return DispatchAiResponse(
                    status="AUTH_ERROR",
                    inference_mode="REAL_CLOUD_LLM",
                    model=groq_model,
                    raw_llm_response="",
                    reconstructed_code="",
                    exact_match=False,
                    tokens_restored=0,
                    unmapped_tokens=[],
                    dropped_tokens=[],
                    instruction_sent=scrubbed_instruction,
                    egress_preview=egress_preview,
                    payload_bytes=payload_bytes,
                    latency_ms=latency_ms,
                    error=f"Groq authentication failed (HTTP {resp.status_code}). Check your API key.",
                )

            if resp.status_code == 429:
                return DispatchAiResponse(
                    status="RATE_LIMITED",
                    inference_mode="REAL_CLOUD_LLM",
                    model=groq_model,
                    raw_llm_response="",
                    reconstructed_code="",
                    exact_match=False,
                    tokens_restored=0,
                    unmapped_tokens=[],
                    dropped_tokens=[],
                    instruction_sent=scrubbed_instruction,
                    egress_preview=egress_preview,
                    payload_bytes=payload_bytes,
                    latency_ms=latency_ms,
                    error="Groq API rate limit reached (HTTP 429). Please retry later.",
                )

            if resp.status_code != 200:
                err_text = redact_key(resp.text, api_key)
                return DispatchAiResponse(
                    status="BAD_LLM_RESPONSE",
                    inference_mode="REAL_CLOUD_LLM",
                    model=groq_model,
                    raw_llm_response="",
                    reconstructed_code="",
                    exact_match=False,
                    tokens_restored=0,
                    unmapped_tokens=[],
                    dropped_tokens=[],
                    instruction_sent=scrubbed_instruction,
                    egress_preview=egress_preview,
                    payload_bytes=payload_bytes,
                    latency_ms=latency_ms,
                    error=f"Groq API returned HTTP {resp.status_code}: {err_text[:200]}",
                )

            try:
                resp_json = resp.json()
                raw_llm_response = resp_json["choices"][0]["message"]["content"]
            except Exception as parse_err:
                return DispatchAiResponse(
                    status="BAD_LLM_RESPONSE",
                    inference_mode="REAL_CLOUD_LLM",
                    model=groq_model,
                    raw_llm_response=resp.text[:500],
                    reconstructed_code="",
                    exact_match=False,
                    tokens_restored=0,
                    unmapped_tokens=[],
                    dropped_tokens=[],
                    instruction_sent=scrubbed_instruction,
                    egress_preview=egress_preview,
                    payload_bytes=payload_bytes,
                    latency_ms=latency_ms,
                    error=f"Failed to parse Groq response JSON: {str(parse_err)}",
                )

    except httpx.TimeoutException:
        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        return DispatchAiResponse(
            status="TIMEOUT",
            inference_mode="REAL_CLOUD_LLM",
            model=groq_model,
            raw_llm_response="",
            reconstructed_code="",
            exact_match=False,
            tokens_restored=0,
            unmapped_tokens=[],
            dropped_tokens=[],
            instruction_sent=scrubbed_instruction,
            egress_preview=egress_preview,
            payload_bytes=payload_bytes,
            latency_ms=latency_ms,
            error="Cloud AI call timed out after 30 seconds.",
        )
    except httpx.RequestError as req_err:
        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        safe_msg = redact_key(str(req_err), api_key)
        return DispatchAiResponse(
            status="NETWORK_ERROR",
            inference_mode="REAL_CLOUD_LLM",
            model=groq_model,
            raw_llm_response="",
            reconstructed_code="",
            exact_match=False,
            tokens_restored=0,
            unmapped_tokens=[],
            dropped_tokens=[],
            instruction_sent=scrubbed_instruction,
            egress_preview=egress_preview,
            payload_bytes=payload_bytes,
            latency_ms=latency_ms,
            error=f"Network communication failure: {safe_msg}",
        )
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        safe_msg = redact_key(str(exc), api_key)
        return DispatchAiResponse(
            status="BAD_LLM_RESPONSE",
            inference_mode="REAL_CLOUD_LLM",
            model=groq_model,
            raw_llm_response="",
            reconstructed_code="",
            exact_match=False,
            tokens_restored=0,
            unmapped_tokens=[],
            dropped_tokens=[],
            instruction_sent=scrubbed_instruction,
            egress_preview=egress_preview,
            payload_bytes=payload_bytes,
            latency_ms=latency_ms,
            error=f"Unexpected error during dispatch: {safe_msg}",
        )

    # Successful call: Parse code from first fence (fallback: whole text) and suture
    code_to_suture = extract_code_from_llm(raw_llm_response)
    suture_res = reconstructor.reconstruct_solution(code_to_suture, vault)

    return DispatchAiResponse(
        status="SUCCESS",
        inference_mode="REAL_CLOUD_LLM",
        model=groq_model,
        raw_llm_response=raw_llm_response,
        reconstructed_code=suture_res["reconstructed_text"],
        exact_match=suture_res["exact_match"],
        tokens_restored=suture_res["tokens_restored"],
        unmapped_tokens=suture_res["unmapped_tokens"],
        dropped_tokens=_calc_dropped(raw_llm_response),
        instruction_sent=scrubbed_instruction,
        egress_preview=egress_preview,
        payload_bytes=payload_bytes,
        latency_ms=latency_ms,
        error=None,
    )


@app.post("/api/v1/session/clear", response_model=SessionClearResponse, tags=["Memory Management"])
async def clear_session_vault(
    req: Optional[SessionClearRequest] = None,
    session_id: Optional[str] = None,
) -> SessionClearResponse:
    """
    Endpoint 3: Purges the specified session vault from volatile RAM memory (FR-04).
    Accepts session_id via JSON body or query parameter.
    """
    target_session_id = session_id
    if req and req.session_id:
        target_session_id = req.session_id

    if not target_session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'session_id' parameter in request body or query string.",
        )

    if target_session_id in RAM_VAULT_REGISTRY:
        del RAM_VAULT_REGISTRY[target_session_id]
        if target_session_id in SESSION_METADATA_STORE:
            del SESSION_METADATA_STORE[target_session_id]
        message = f"Session '{target_session_id}' successfully purged from volatile memory."
    else:
        if target_session_id in SESSION_METADATA_STORE:
            del SESSION_METADATA_STORE[target_session_id]
        message = f"Session '{target_session_id}' was not found in active RAM registry."

    return SessionClearResponse(
        status="PURGED",
        session_id=target_session_id,
        message=message,
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
