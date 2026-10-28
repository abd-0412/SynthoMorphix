"""
SynthoMorphix: Suture Reconstructor Pytest Suite
Base Paper: Zhou Yang et al., IEEE Transactions on Software Engineering 2024.

Tests with Mock LLM Responses:
1. Markdown code fences + prose explanations
2. LLM response preserving synthetic tokens
3. LLM response that drops a token
4. LLM response that invents an unknown token (e.g., fn_99) -> must appear in unmapped_tokens without crashing
5. Plain code response with no markdown fences
6. Long token collision prevention (var_10 before var_01)
"""

from __future__ import annotations

import os
import sys
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from synthomorphix.reconstructor import reconstruct_solution


@pytest.fixture
def mock_vault():
    return {
        "fn_01": "calculate_tax",
        "fn_02": "apply_discount",
        "cls_01": "OrderManager",
        "arg_01": "subtotal",
        "arg_02": "rate",
        "var_01": "final_amount",
        "var_10": "extended_buffer",
        "str_01": "standard",
    }


def test_mock_llm_markdown_fences_with_prose(mock_vault):
    """Verifies that markdown code blocks with prose are sanitized strictly inside fences."""
    raw_llm = """Here is your refactored Python function:

```python
class cls_01:
    def fn_01(self, arg_01, arg_02=0.05):
        var_01 = arg_01 * (1 + arg_02)
        return var_01
```

Hope this helps with your calculation! Let me know if you need anything else.
"""
    res = reconstruct_solution(raw_llm, mock_vault)
    
    assert res["exact_match"] is True
    assert res["tokens_restored"] >= 5
    assert "class OrderManager:" in res["reconstructed_text"]
    assert "def calculate_tax(self, subtotal, rate=0.05):" in res["reconstructed_text"]
    assert "final_amount = subtotal * (1 + rate)" in res["reconstructed_text"]
    assert "Here is your refactored Python function:" in res["reconstructed_text"]


def test_mock_llm_without_fences(mock_vault):
    """Verifies fallback lexical substitution when no markdown fences exist."""
    raw_llm = "def fn_01(arg_01): return arg_01"
    res = reconstruct_solution(raw_llm, mock_vault)
    
    assert res["exact_match"] is True
    assert res["reconstructed_text"] == "def calculate_tax(subtotal): return subtotal"
    assert res["tokens_restored"] == 3


def test_mock_llm_drops_token(mock_vault):
    """Verifies suture stability when the LLM drops or rewrites one of the tokens."""
    # LLM dropped 'var_01' and inlined the calculation
    raw_llm = "```python\ndef fn_01(arg_01, arg_02):\n    return arg_01 * (1 + arg_02)\n```"
    res = reconstruct_solution(raw_llm, mock_vault)
    
    assert res["exact_match"] is True
    assert "calculate_tax(subtotal, rate)" in res["reconstructed_text"]
    assert res["tokens_restored"] == 5


def test_mock_llm_invents_unknown_token(mock_vault):
    """
    Verifies that unknown/hallucinated synthetic tokens (e.g., fn_99, var_88)
    are captured in unmapped_tokens without crashing and exact_match is False.
    """
    raw_llm = """```python
def fn_01(arg_01):
    var_99 = fn_88(arg_01)
    return var_99
```"""
    res = reconstruct_solution(raw_llm, mock_vault)
    
    assert res["exact_match"] is False
    assert "fn_88" in res["unmapped_tokens"]
    assert "var_99" in res["unmapped_tokens"]
    # fn_01 and arg_01 should still be restored cleanly
    assert "calculate_tax(subtotal)" in res["reconstructed_text"]


def test_mock_llm_prefix_collision_prevention(mock_vault):
    """Verifies that longer synthetic tokens (var_10) are not partially overwritten by var_01."""
    raw_llm = "var_10 = var_01 + 100"
    res = reconstruct_solution(raw_llm, mock_vault)
    
    assert res["exact_match"] is True
    assert res["reconstructed_text"] == "extended_buffer = final_amount + 100"
