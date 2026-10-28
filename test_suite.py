"""
SynthoMorphix: Formal Compiler Test & Verification Harness
Base Paper: Zhou Yang et al., IEEE Transactions on Software Engineering (TSE) 2024.
Reference: Formal Verification of AST Suture Operators, Bytecode Validity, and Round-Trip Determinism.

This standalone harness tests:
1. Standard Library & Class Method Resolution (os.path.exists preserved)
2. LEGB Lexical Scope & Cross-Scope Variable Shadowing (distinct tokens across non-nested scopes)
3. L2 Privacy Scrubbing (Comments and String Literals desensitized and sutured losslessly)
4. Bytecode Compilation via py_compile (0% syntax regressions)
5. Round-trip Lossless Identity Verification
"""

from __future__ import annotations

import os
import py_compile
import sys
import tempfile
from typing import Dict, Tuple

try:
    from synthomorphix import engine, reconstructor
except ImportError:
    import engine  # type: ignore
    import reconstructor  # type: ignore


# ==============================================================================
# Test Payloads
# ==============================================================================

PAYLOAD_CASE_1 = """import os
import sys

class TransactionHandler:
    def __init__(self, storage_dir):
        self.storage_dir = storage_dir
        self.is_ready = True

    def process_transaction(self, tx_id, amount=100.0):
        target_path = os.path.join(self.storage_dir, f"tx_{tx_id}.dat")
        if os.path.exists(target_path):
            return self.archive_transaction(target_path)
        return amount * 1.05

    def archive_transaction(self, path):
        return f"Archived at {path}"

def run_pipeline():
    handler = TransactionHandler("/var/data")
    return handler.process_transaction(42, amount=250.0)
"""

PAYLOAD_CASE_2 = """CONFIG_LIMIT = 5000

def compute_tier_a():
    temp_val = 10
    total = temp_val * 2
    if total < CONFIG_LIMIT:
        return total
    return CONFIG_LIMIT

def compute_tier_b():
    temp_val = 20
    total = temp_val * 3
    if total < CONFIG_LIMIT:
        return total
    return CONFIG_LIMIT
"""

PAYLOAD_CASE_3 = """# Sensitive Database Connection
db_host = "postgres://admin:super_secret_pw@db.internal:5432/corp"
api_token = "sk_live_99482710492817491"

def authenticate_session(user_id):
    # Verify cryptographic signature
    session_uri = f"{db_host}?user={user_id}&key={api_token}"
    return session_uri
"""


def verify_bytecode_compilation(code_str: str) -> Tuple[bool, str]:
    """
    Writes code to a temporary .py file and compiles it with py_compile.doraise=True.
    Returns (True, "PASSED") or (False, error_message).
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".py", text=True)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(code_str)

        py_compile.compile(tmp_path, doraise=True)
        return True, "PASSED"
    except py_compile.PyCompileError as pce:
        return False, str(pce)
    except Exception as exc:
        return False, str(exc)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def run_harness() -> bool:
    print("=" * 72)
    print("   SYNTHOMORPHIX: COMPILER VERIFICATION & ROUND-TRIP TEST HARNESS")
    print("   Base Paper: Zhou Yang et al., IEEE TSE 2024")
    print("=" * 72)

    passed_count = 0
    total_cases = 3

    # --------------------------------------------------------------------------
    # Case 1: Standard Library & Class Method Resolution
    # --------------------------------------------------------------------------
    print("\n[+] RUNNING TEST CASE 1: Standard Library & Class Method Resolution")
    print("    Masking Level: L1 | Dynamic Policy: block")
    
    scrub_1 = engine.analyze_and_scrub(PAYLOAD_CASE_1, mask_level="L1", dynamic_policy="block")
    scrubbed_1 = scrub_1["scrubbed_code"]
    vault_1 = scrub_1["reverse_vault"]
    isolated_1 = scrub_1["tokens_isolated"]

    # Bytecode compilation verification
    bytecode_ok_1, bytecode_msg_1 = verify_bytecode_compilation(scrubbed_1)

    # Invariant checks: os.path.exists and import os must remain preserved
    lib_preserved_1 = (
        "import os" in scrubbed_1
        and "os.path.exists" in scrubbed_1
        and "os.path.join" in scrubbed_1
        and "self.storage_dir" in scrubbed_1
    )

    # Lossless Suture verification
    suture_1 = reconstructor.reconstruct_solution(scrubbed_1, vault_1)
    restored_1 = suture_1["reconstructed_text"]
    exact_suture_1 = (restored_1.strip() == PAYLOAD_CASE_1.strip())

    c1_passed = bytecode_ok_1 and lib_preserved_1 and exact_suture_1 and suture_1["exact_match"]

    print(f"    * Isolated Symbols Count        : {isolated_1}")
    print(f"    * Bytecode Syntax Compilation   : {'PASSED' if bytecode_ok_1 else 'FAILED (' + bytecode_msg_1 + ')'}")
    print(f"    * Library `os.path.exists` Check : {'PASSED (Preserved)' if lib_preserved_1 else 'FAILED'}")
    print(f"    * Round-Trip Identity Suture    : {'PASSED (Lossless)' if exact_suture_1 else 'FAILED'}")
    print(f"    * Test Case 1 Verdict           : {'[PASS]' if c1_passed else '[FAIL]'}")
    if c1_passed:
        passed_count += 1

    # --------------------------------------------------------------------------
    # Case 2: LEGB Lexical Scope & Cross-Scope Variable Shadowing
    # --------------------------------------------------------------------------
    print("\n[+] RUNNING TEST CASE 2: LEGB Lexical Scope & Variable Shadowing")
    print("    Masking Level: L1 | Dynamic Policy: block")

    scrub_2 = engine.analyze_and_scrub(PAYLOAD_CASE_2, mask_level="L1", dynamic_policy="block")
    scrubbed_2 = scrub_2["scrubbed_code"]
    vault_2 = scrub_2["reverse_vault"]
    isolated_2 = scrub_2["tokens_isolated"]

    bytecode_ok_2, bytecode_msg_2 = verify_bytecode_compilation(scrubbed_2)

    # Invariant check: In fn1 and fn2, temp_val must have received DIFFERENT synthetic tokens
    # e.g., var_02 in compute_tier_a and var_04 in compute_tier_b
    tokens_for_temp_val = [k for k, v in vault_2.items() if v == "temp_val"]
    distinct_scopes_2 = len(tokens_for_temp_val) >= 2

    # Global CONFIG_LIMIT must have been resolved and shared in both functions
    tokens_for_config = [k for k, v in vault_2.items() if v == "CONFIG_LIMIT"]
    global_resolved_2 = len(tokens_for_config) == 1

    suture_2 = reconstructor.reconstruct_solution(scrubbed_2, vault_2)
    restored_2 = suture_2["reconstructed_text"]
    exact_suture_2 = (restored_2.strip() == PAYLOAD_CASE_2.strip())

    c2_passed = bytecode_ok_2 and distinct_scopes_2 and global_resolved_2 and exact_suture_2

    print(f"    * Isolated Symbols Count        : {isolated_2}")
    print(f"    * Bytecode Syntax Compilation   : {'PASSED' if bytecode_ok_2 else 'FAILED (' + bytecode_msg_2 + ')'}")
    print(f"    * Cross-Scope Shadow Isolation  : {'PASSED (Distinct Tokens: ' + str(tokens_for_temp_val) + ')' if distinct_scopes_2 else 'FAILED'}")
    print(f"    * LEGB Global Scope Resolution  : {'PASSED (Single Global Token: ' + str(tokens_for_config) + ')' if global_resolved_2 else 'FAILED'}")
    print(f"    * Round-Trip Identity Suture    : {'PASSED (Lossless)' if exact_suture_2 else 'FAILED'}")
    print(f"    * Test Case 2 Verdict           : {'[PASS]' if c2_passed else '[FAIL]'}")
    if c2_passed:
        passed_count += 1

    # --------------------------------------------------------------------------
    # Case 3: L2 Privacy Scrubbing & Comment/Literal Masking
    # --------------------------------------------------------------------------
    print("\n[+] RUNNING TEST CASE 3: L2 Privacy Scrubbing (Comments & Literals)")
    print("    Masking Level: L2 | Dynamic Policy: block")

    scrub_3 = engine.analyze_and_scrub(PAYLOAD_CASE_3, mask_level="L2", dynamic_policy="block")
    scrubbed_3 = scrub_3["scrubbed_code"]
    vault_3 = scrub_3["reverse_vault"]
    isolated_3 = scrub_3["tokens_isolated"]

    bytecode_ok_3, bytecode_msg_3 = verify_bytecode_compilation(scrubbed_3)

    # Invariant check: Sensitivities must NOT appear anywhere in the scrubbed text
    privacy_masked_3 = (
        "postgres://admin" not in scrubbed_3
        and "sk_live_" not in scrubbed_3
        and "Sensitive Database Connection" not in scrubbed_3
        and "# cmt_" in scrubbed_3
        and '"str_' in scrubbed_3
    )

    suture_3 = reconstructor.reconstruct_solution(scrubbed_3, vault_3)
    restored_3 = suture_3["reconstructed_text"]
    exact_suture_3 = (restored_3.strip() == PAYLOAD_CASE_3.strip())

    c3_passed = bytecode_ok_3 and privacy_masked_3 and exact_suture_3 and suture_3["exact_match"]

    print(f"    * Isolated Symbols Count        : {isolated_3}")
    print(f"    * Bytecode Syntax Compilation   : {'PASSED' if bytecode_ok_3 else 'FAILED (' + bytecode_msg_3 + ')'}")
    print(f"    * L2 Sensitive Literal Masking  : {'PASSED (Zero Leakage)' if privacy_masked_3 else 'FAILED'}")
    print(f"    * Round-Trip Identity Suture    : {'PASSED (Lossless)' if exact_suture_3 else 'FAILED'}")
    print(f"    * Test Case 3 Verdict           : {'[PASS]' if c3_passed else '[FAIL]'}")
    if c3_passed:
        passed_count += 1

    # --------------------------------------------------------------------------
    # Final Executive Summary
    # --------------------------------------------------------------------------
    print("\n" + "=" * 72)
    if passed_count == total_cases:
        print(f"HARNESS RESULT: {passed_count}/{total_cases} TEST CASES PASSED (100% REGRESSION-FREE)")
    else:
        print(f"HARNESS RESULT: {passed_count}/{total_cases} TEST CASES PASSED (FAILURES DETECTED)")
    print("=" * 72 + "\n")

    return passed_count == total_cases


if __name__ == "__main__":
    success = run_harness()
    sys.exit(0 if success else 1)
