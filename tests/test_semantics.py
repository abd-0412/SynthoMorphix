"""
SynthoMorphix: Semantic Execution Equivalence Test Suite
Base Paper: Zhou Yang et al., IEEE Transactions on Software Engineering (TSE) 2024.

Verifies Directive 3:
For each non-blocked sample in samples/, executes the original and scrubbed code
in isolated sandboxed namespaces with dedicated driver calls, and asserts that the
execution results are strictly equal (original == scrubbed).

Any semantic divergence will cause a test failure (no xfail unless documented in KNOWN_LIMITATIONS.md).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, Dict, Tuple

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from synthomorphix.engine import analyze_and_scrub

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SAMPLES_DIR = os.path.join(PROJECT_ROOT, "samples")


def execute_driver_pair(
    sample_file: str,
    driver_orig: Callable[[Dict[str, Any]], Any],
    driver_scrub: Callable[[Dict[str, Any], Dict[str, str]], Any],
    mask_level: str = "L1",
    dynamic_policy: str = "block",
) -> Tuple[Any, Any]:
    """
    Executes original vs scrubbed code in isolated namespaces using custom driver functions.
    Returns (result_orig, result_scrub).
    """
    sample_path = os.path.join(SAMPLES_DIR, sample_file)
    with open(sample_path, "r", encoding="utf-8") as f:
        code = f.read()

    res = analyze_and_scrub(code, mask_level=mask_level, dynamic_policy=dynamic_policy)
    assert res["status"] == "SUCCESS", f"Expected SUCCESS but got {res['status']}"

    vault = res["reverse_vault"]
    ns_orig: Dict[str, Any] = {}
    ns_scrub: Dict[str, Any] = {}

    exec(code, ns_orig)
    exec(res["scrubbed_code"], ns_scrub)

    result_orig = driver_orig(ns_orig)
    result_scrub = driver_scrub(ns_scrub, vault)

    return result_orig, result_scrub


def test_semantics_01_payroll():
    """
    Sample 01: Payroll pipeline with method call `pipeline.calculate_disbursement(..., bonus_rate=0.12)`.
    Resolves uniquely defined project method `calculate_disbursement` and renames kwarg to match parameter.
    """
    def orig(ns):
        return ns["process_batch"]()

    def scrub(ns, vault):
        fn_scrub = [k for k, v in vault.items() if v == "process_batch"][0]
        return ns[fn_scrub]()

    res_orig, res_scrub = execute_driver_pair("01_payroll.py", orig, scrub)
    assert res_orig == res_scrub


def test_semantics_02_inventory():
    """Sample 02: InventoryTracker class instantiation and stock management."""
    def orig(ns):
        tracker = ns["InventoryTracker"]("WH_EAST")
        tracker.update_stock("ITEM_A", 15)
        return tracker.check_availability("ITEM_A", 10)

    def scrub(ns, vault):
        cls_token = [k for k, v in vault.items() if v == "InventoryTracker"][0]
        tracker = ns[cls_token]("WH_EAST")
        fn_update = [k for k, v in vault.items() if v == "update_stock"][0]
        getattr(tracker, fn_update)("ITEM_A", 15)
        fn_avail = [k for k, v in vault.items() if v == "check_availability"][0]
        return getattr(tracker, fn_avail)("ITEM_A", 10)

    res_orig, res_scrub = execute_driver_pair("02_inventory.py", orig, scrub)
    assert res_orig == res_scrub
    assert res_orig is True


def test_semantics_03_auth():
    """Sample 03: Hash credentials and token verification."""
    def orig(ns):
        return ns["verify_token"]("alice", "dummy_token_hash")

    def scrub(ns, vault):
        fn_token = [k for k, v in vault.items() if v == "verify_token"][0]
        return ns[fn_token]("alice", "dummy_token_hash")

    res_orig, res_scrub = execute_driver_pair("03_auth.py", orig, scrub)
    assert res_orig == res_scrub
    assert res_orig is False


def test_semantics_04_data_cleaning():
    """Sample 04: Regex-based phone and text sanitization."""
    test_data = [{"name": "  alice smith  ", "email": "ALICE@EXAMPLE.COM", "phone": "123-456-7890"}]

    def orig(ns):
        return ns["clean_dataset"](test_data)

    def scrub(ns, vault):
        fn_token = [k for k, v in vault.items() if v == "clean_dataset"][0]
        return ns[fn_token](test_data)

    res_orig, res_scrub = execute_driver_pair("04_data_cleaning.py", orig, scrub)
    assert res_orig == res_scrub
    assert res_orig == [{"name": "Alice Smith", "email": "alice@example.com", "phone": "1234567890"}]


def test_semantics_05_nested_closure():
    """Sample 05: Higher-order nested closure execution."""
    def orig(ns):
        return ns["run_calculation"](5)

    def scrub(ns, vault):
        fn_token = [k for k, v in vault.items() if v == "run_calculation"][0]
        return ns[fn_token](5)

    res_orig, res_scrub = execute_driver_pair("05_nested_closure.py", orig, scrub)
    assert res_orig == res_scrub
    assert res_orig == 45.0


def test_semantics_06_shadowing():
    """Sample 06: Independent tiered calculation across scopes."""
    def orig(ns):
        return ns["compute_tier_a"](), ns["compute_tier_b"]()

    def scrub(ns, vault):
        fn_a = [k for k, v in vault.items() if v == "compute_tier_a"][0]
        fn_b = [k for k, v in vault.items() if v == "compute_tier_b"][0]
        return ns[fn_a](), ns[fn_b]()

    res_orig, res_scrub = execute_driver_pair("06_shadowing.py", orig, scrub)
    assert res_orig == res_scrub
    assert res_orig == (20, 60)


def test_semantics_07_decorators():
    """Sample 07: Function wrapper decorator with kwargs passing."""
    def orig(ns):
        return ns["execute_trade"]("AAPL", 50)

    def scrub(ns, vault):
        fn_token = [k for k, v in vault.items() if v == "execute_trade"][0]
        return ns[fn_token]("AAPL", 50)

    res_orig, res_scrub = execute_driver_pair("07_decorators.py", orig, scrub)
    assert res_orig == res_scrub
    assert res_orig == 49.9


def test_semantics_08_kwargs():
    """Sample 08: Function call with project-defined keyword arguments."""
    def orig(ns):
        return ns["process_employee"]()

    def scrub(ns, vault):
        fn_token = [k for k, v in vault.items() if v == "process_employee"][0]
        return ns[fn_token]()

    res_orig, res_scrub = execute_driver_pair("08_kwargs.py", orig, scrub)
    assert res_orig == res_scrub
    assert res_orig == 25375.0


def test_semantics_09_lambdas():
    """Sample 09: Higher-order functions with lambda expressions."""
    records = [{"id": 1, "priority": 2, "amount": 100}, {"id": 2, "priority": 5, "amount": 200}]

    def orig(ns):
        return ns["sort_transactions"](records), ns["apply_discount"]([100, 200], 0.15)

    def scrub(ns, vault):
        fn_sort = [k for k, v in vault.items() if v == "sort_transactions"][0]
        fn_disc = [k for k, v in vault.items() if v == "apply_discount"][0]
        return ns[fn_sort](records), ns[fn_disc]([100, 200], 0.15)

    res_orig, res_scrub = execute_driver_pair("09_lambdas.py", orig, scrub)
    assert res_orig == res_scrub


def test_semantics_10_comprehensions():
    """Sample 10: Dictionary, list, and set comprehensions."""
    def orig(ns):
        return ns["generate_lookup"](["cat", "elephant", "dog"], [10, 20, 30])

    def scrub(ns, vault):
        fn_token = [k for k, v in vault.items() if v == "generate_lookup"][0]
        return ns[fn_token](["cat", "elephant", "dog"], [10, 20, 30])

    res_orig, res_scrub = execute_driver_pair("10_comprehensions.py", orig, scrub)
    assert res_orig == res_scrub


def test_semantics_11_global_nonlocal():
    """Sample 11: Closure state mutating nonlocal and global counters."""
    def orig(ns):
        inc = ns["manage_state"](100)
        return inc(), inc()

    def scrub(ns, vault):
        fn_token = [k for k, v in vault.items() if v == "manage_state"][0]
        inc = ns[fn_token](100)
        return inc(), inc()

    res_orig, res_scrub = execute_driver_pair("11_global_nonlocal.py", orig, scrub)
    assert res_orig == res_scrub
    assert res_orig == (105, 110)


def test_semantics_12_dynamic_risk_blocked_under_default_policy():
    """Sample 12: Under default policy ('block'), dynamic code is safely blocked."""
    sample_path = os.path.join(SAMPLES_DIR, "12_dynamic_risk.py")
    with open(sample_path, "r", encoding="utf-8") as f:
        code = f.read()

    res = analyze_and_scrub(code, mask_level="L1", dynamic_policy="block")
    assert res["status"] == "BLOCKED_DYNAMIC_RISK"
    assert res["scrubbed_code"] == ""
    assert res["dynamic_risk"] is True


def test_semantics_12_dynamic_risk_pass_mode_unsafe():
    """
    Sample 12: Under dynamic_policy='pass' (UNSAFE mode), executes with matching output.
    Documented as unsafe in docs/KNOWN_LIMITATIONS.md.
    """
    class SampleObj:
        api_key = "SECRET_12345"

    def orig(ns):
        res1 = ns["inspect_object_dynamically"](SampleObj(), "api_key")
        res2 = ns["evaluate_custom_formula"]("x + y", {"x": 10, "y": 20})
        return res1, res2

    def scrub(ns, vault):
        fn_inspect = [k for k, v in vault.items() if v == "inspect_object_dynamically"][0]
        fn_eval = [k for k, v in vault.items() if v == "evaluate_custom_formula"][0]
        res1 = ns[fn_inspect](SampleObj(), "api_key")
        res2 = ns[fn_eval]("x + y", {"x": 10, "y": 20})
        return res1, res2

    res_orig, res_scrub = execute_driver_pair("12_dynamic_risk.py", orig, scrub, dynamic_policy="pass")
    assert res_orig == res_scrub
    assert res_orig == ("SECRET_12345", 30)
