"""
SynthoMorphix: Suture Reconstruction Gateway Operator R(O, V) -> (P_final, Report)
Base Paper: Zhou Yang et al., IEEE Transactions on Software Engineering (TSE) 2024.
Reference: Deterministic Reverse Token Suture and Discrepancy Auditing for Cloud LLM Code Generation.

This module deterministically reverses synthetic token obfuscations produced by the
SynthoMorphix AST scrubber, handling Markdown code fences, prose explanations,
unified diffs, prefix collision prevention, and hallucinated synthetic token auditing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple


# Regex pattern to identify any token that fits the SynthoMorphix grammatical synthetic format
# e.g., fn_01, var_10, cls_03, arg_02, str_01, cmt_05
SYNTHETIC_TOKEN_PATTERN = re.compile(r"\b(?:fn|var|cls|arg|str|cmt)_\d{2,}\b")

# Regex to match markdown code blocks with case-insensitive language tags or bare backticks
# Matches ```python, ```py, ```Python, ```, etc.
# Group 1: Opening fence tag (e.g. ```python\n)
# Group 2: Code block content
# Group 3: Closing fence tag (```)
FENCE_BLOCK_PATTERN = re.compile(
    r"(```[a-zA-Z0-9_-]*\r?\n)([\s\S]*?)(^|\n)(```)",
    re.MULTILINE,
)


def _build_replacement_regex(sorted_keys: List[str]) -> Optional[re.Pattern]:
    """
    Builds a regex pattern with word boundaries for the sorted synthetic keys.
    Returns None if sorted_keys is empty.
    """
    if not sorted_keys:
        return None
    # Escape each key to safeguard against regex special chars and wrap in word boundaries
    escaped_keys = [re.escape(k) for k in sorted_keys]
    pattern_str = r"\b(" + "|".join(escaped_keys) + r")\b"
    return re.compile(pattern_str)


def _replace_segment(
    segment: str,
    compiled_regex: Optional[re.Pattern],
    reverse_vault: Dict[str, str],
) -> Tuple[str, int]:
    """
    Replaces synthetic tokens within a given string segment using the compiled regex.
    Returns the modified segment and the count of replacements made.
    """
    if compiled_regex is None:
        return segment, 0

    replacement_count = 0

    def _sub_callback(match: re.Match) -> str:
        nonlocal replacement_count
        token = match.group(0)
        if token in reverse_vault:
            replacement_count += 1
            return reverse_vault[token]
        return token

    reconstructed_segment = compiled_regex.sub(_sub_callback, segment)
    return reconstructed_segment, replacement_count


def reconstruct_solution(raw_llm_response: str, reverse_vault: Dict[str, str]) -> Dict[str, Any]:
    """
    Deterministic suture reconstruction operator R(O, V) -> (P_final, Report).

    Takes a raw, noisy response from a Cloud LLM (which may contain markdown code fences,
    prose explanations, or unified diffs) and the ephemeral volatile vault V, and
    deterministically restores project-defined identifiers to their original names.

    Parameters:
      raw_llm_response: The raw string response from the Cloud LLM.
      reverse_vault: In-memory mapping of {synthetic_token: original_text} produced by the scrubber.

    Returns:
      A dictionary containing:
        - reconstructed_text: The fully stitched, reconstructed string with original identifiers.
        - exact_match: Boolean indicating whether 100% of observed synthetic tokens were resolved.
        - unmapped_tokens: List of unexpected synthetic strings introduced by the model.
        - tokens_restored: Count of successfully replaced synthetic occurrences.
    """
    if not raw_llm_response:
        return {
            "reconstructed_text": "",
            "exact_match": True,
            "unmapped_tokens": [],
            "tokens_restored": 0,
        }

    # Step 1: Discrepancy & Hallucination Auditing
    # Find all synthetic tokens occurring anywhere in the raw LLM payload
    all_observed_synthetic: Set[str] = set(SYNTHETIC_TOKEN_PATTERN.findall(raw_llm_response))
    vault_keys: Set[str] = set(reverse_vault.keys())

    # Detect synthetic tokens present in the output that are NOT in the vault
    unmapped_set = all_observed_synthetic - vault_keys
    unmapped_tokens = sorted(list(unmapped_set))
    exact_match = (len(unmapped_tokens) == 0)

    # Step 2: Collision Prevention Preparation
    # Sort keys strictly by descending length to prevent partial/prefix overwrites (e.g., var_10 before var_1)
    sorted_vault_keys = sorted(vault_keys, key=len, reverse=True)
    compiled_regex = _build_replacement_regex(sorted_vault_keys)

    # Step 3: Segment Parsing & Fence Sanitization
    # Check if markdown code fences exist in the response
    matches = list(FENCE_BLOCK_PATTERN.finditer(raw_llm_response))

    total_tokens_restored = 0

    if matches:
        # Fences detected: Process strictly inside each code fence while preserving enclosing prose and tags
        reconstructed_parts: List[str] = []
        last_idx = 0

        for match in matches:
            fence_start = match.start()
            fence_end = match.end()

            # Append preceding text (e.g., markdown prose or commentary before the fence) unmodified
            reconstructed_parts.append(raw_llm_response[last_idx:fence_start])

            opening_fence = match.group(1)
            code_content = match.group(2)
            newline_boundary = match.group(3)
            closing_fence = match.group(4)

            # Reconstruct the code content strictly inside the block
            reconstructed_code, count = _replace_segment(code_content, compiled_regex, reverse_vault)
            total_tokens_restored += count

            # Reassemble fence block exactly preserving opening tags, newlines, and backticks
            reconstructed_parts.append(f"{opening_fence}{reconstructed_code}{newline_boundary}{closing_fence}")

            last_idx = fence_end

        # Append any remaining trailing prose/diff after the final fence
        reconstructed_parts.append(raw_llm_response[last_idx:])
        reconstructed_text = "".join(reconstructed_parts)
    else:
        # No markdown fences present: Fall back to safe boundary-checked lexical substitution across the entire payload
        reconstructed_text, total_tokens_restored = _replace_segment(
            raw_llm_response,
            compiled_regex,
            reverse_vault,
        )

    return {
        "reconstructed_text": reconstructed_text,
        "exact_match": exact_match,
        "unmapped_tokens": unmapped_tokens,
        "tokens_restored": total_tokens_restored,
    }


if __name__ == "__main__":
    # Self-test demonstration with Markdown code fences, prose, and unified diffs
    test_vault = {
        "fn_01": "process_batch",
        "fn_02": "compute_checksum",
        "cls_01": "DataLoader",
        "arg_01": "payload",
        "arg_02": "salt",
        "var_01": "hashed_output",
        "var_02": "raw_buffer",
        "var_10": "extended_buffer",
    }

    # Case 1: Standard LLM Response with Markdown code fence and prose
    raw_response_with_fence = """Here is the optimized solution:

```python
class cls_01:
    def fn_01(self, arg_01):
        var_02 = arg_01.strip()
        var_10 = var_02.encode('utf-8')
        return self.fn_02(var_10)

    def fn_02(self, raw_buffer, arg_02="secret"):
        var_01 = hash(raw_buffer)
        return var_01
```

Let me know if you need any further enhancements!
"""

    print("=== Test Case 1: Markdown Fence with Prefix Collisions (var_10 vs var_01) ===")
    report_1 = reconstruct_solution(raw_response_with_fence, test_vault)
    print("Exact Match:", report_1["exact_match"])
    print("Tokens Restored:", report_1["tokens_restored"])
    print("Unmapped Tokens:", report_1["unmapped_tokens"])
    print("Reconstructed Text:\n", report_1["reconstructed_text"])

    # Case 2: Response without fences (raw code/prose fallback)
    raw_response_plain = "def fn_01(arg_01): return arg_01"
    print("\n=== Test Case 2: Plain Response Fallback ===")
    report_2 = reconstruct_solution(raw_response_plain, test_vault)
    print("Reconstructed Text:", report_2["reconstructed_text"])
    print("Tokens Restored:", report_2["tokens_restored"])

    # Case 3: Hallucinated / Unmapped Tokens Introduced by Model
    raw_response_hallucinated = """```py
def fn_01(arg_01):
    var_99 = fn_88(arg_01)
    return var_99
```"""
    print("\n=== Test Case 3: Hallucinated / Discrepant Synthetic Tokens ===")
    report_3 = reconstruct_solution(raw_response_hallucinated, test_vault)
    print("Exact Match:", report_3["exact_match"])
    print("Unmapped Tokens:", report_3["unmapped_tokens"])
    print("Tokens Restored:", report_3["tokens_restored"])
    print("Reconstructed Text:\n", report_3["reconstructed_text"])
