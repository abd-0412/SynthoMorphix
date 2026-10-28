# Known Limitations: SynthoMorphix Phase I
Base Paper: Zhou Yang et al., IEEE Transactions on Software Engineering (TSE) 2024.

This document records genuine limitations identified during empirical testing and compiler verification of the SynthoMorphix Phase I prototype.
Academic rigor requires transparently reporting edge cases and measured constraints rather than making unsubstantiated claims.

---

### 1. Instance Attribute Handling (`self.attr` / `obj.attr`) & Measured Leakage
* **Observed Limitation**: 
  In Phase I, object property access (`self.attr`, `var.values()`) preserves non-method attributes and external calls untouched to prevent breaking third-party library APIs (e.g., `os.path.exists`, `dict.get`, `dict.values`).
* **Empirical Measurement**:
  Under L1/L2 lexical leakage evaluation (`eval/metrics.py`), attribute leakage accounts for:
  - `samples/01_payroll.py`: `self.company_id` and `self.base_multiplier` are retained as attributes (`attribute` leak count: 2).
  - `samples/02_inventory.py`: `self.warehouse_code` is retained as an attribute (`attribute` leak count: 1).
  - `samples/10_comprehensions.py`: dictionary method `.values()` collides with parameter name `values` (`attribute` leak count: 1).
* **Resolved Call-Site Method Kwargs**:
  When a method call `obj.method(kw=...)` targets a method name defined exactly once across the project and does not collide with common library methods (e.g. `pipeline.calculate_disbursement(employee, bonus_rate=0.12)` in `01_payroll.py`), the callee is safely resolved and its keyword argument is renamed to `arg_04`, enabling clean runtime execution without requiring full interprocedural type inference.
* **Remaining Limitation (Collisions & Duplicates)**:
  If a project method name is declared more than once in the project (e.g. `ClassA.execute` and `ClassB.execute`) or matches a standard library method (`get`, `update`, `format`, `items`, `values`, `keys`, `append`, `join`, `split`, `read`, `write`, `send`, `post`), the call site kwarg is safely left untouched and emits an `ambiguous_kwarg` warning.
* **Heuristic Risk: Project Method Name Equal to an Unlisted Library Method**:
  In Phase I, method call resolution relies on a project method uniqueness check combined with `COMMON_LIBRARY_METHODS`. If an external library or third-party framework defines an object with a method name that is *not* in `COMMON_LIBRARY_METHODS` (for example, `client.query(limit=50)` or `df.compute(threads=4)`), and a project class happens to declare a method with that same name (`def query(self, limit): ...`), calls of the form `library_obj.query(limit=50)` will heuristically match the project method name. As a result, the kwarg `limit` would be renamed to `arg_XX` at the library call site, potentially inducing a `TypeError: unexpected keyword argument` upon execution against the third-party library.
* **Phase II Mitigation Plan**:
  1. Implement interprocedural receiver type inference (tracking variable assignments like `pipeline = PayrollPipeline(...)` or `client = BigQueryClient(...)` to resolve receivers to explicit classes).
  2. Implement dedicated class-instance symbol tables separating instance attributes (`self.field`) from local variables.
  3. Expand the static library registry to cover standard scientific and web framework method APIs.

---

### 2. Dynamic Reflection Pass-Through vs. Fail-Closed Blocking
* **Observed Behavior**:
  Dynamic reflection constructs (`getattr`, `setattr`, `hasattr`, `eval`, `exec`, `globals`, `locals`) access variables and method names via runtime strings or arbitrary string expressions rather than static syntax tokens.
* **Fail-Closed Default (`dynamic_policy="block"`)**:
  By default, any detected dynamic reflection construct causes the engine to return `status: "BLOCKED_DYNAMIC_RISK"` with an **empty payload** (`scrubbed_code: ""`), isolating 0 tokens and storing no vault entries. The dashboard displays `"Blocked: dynamic code detected"` and disables Step 2.
* **Unsafe Pass-Through Mode (`dynamic_policy="pass"`)**:
  > [!WARNING]
  > **UNSAFE OPERATIONAL MODE**: Running with `dynamic_policy="pass"` bypasses the security block and allows code containing reflection to be transmitted to downstream models. Because strings evaluated at runtime cannot be guaranteed to be synchronized with renamed AST identifiers, this mode is explicitly classified as **UNSAFE** and should only be used in controlled environments with full awareness of potential runtime deserialization or attribute failures.

---

### 3. Lexical Scope Boundary at L1 (Strings & Comments)
* **Observed Behavior**:
  At protection level `L1`, the scrubber intentionally targets identifiers only (`fn_XX`, `var_XX`, `cls_XX`, `arg_XX`). String literals and inline developer comments remain unchanged.
* **Security Consequence**:
  Proprietary project names or secrets embedded in strings (`db_pass = "admin123"`) or comments (`# Project Titan`) are visible to third-party endpoints under `L1`.
* **Mitigation**:
  Protection level `L2` de-identifies inline comments into `# cmt_XX` and string literals into `"str_XX"` with lossless round-trip restoration.

---

### 4. Tree-sitter Tokenization on Raw Regex String Replacements (L2 xfail)
* **Observed Behavior** (`tests/test_scrub.py::test_l2_raw_string_structural_xfail`):
  In sample `04_data_cleaning.py`, raw regex strings such as `r"[^\d]"` are replaced with synthetic tokens (`r"str_05"`).
* **Compiler Detail**:
  Tree-sitter's Python grammar treats the inner characters of raw strings with special internal token boundaries. Replacing the inner regex pattern with an identifier-like string token alters the internal subtree node count, although top-level AST execution and Python bytecode compilation remain valid and lossless upon suture.

---

### 5. Non-Deterministic Cloud LLM Rewrites & Token Drop
* **Observed Behavior**:
  Cloud LLMs may:
  1. Omit intermediate variables and inline calculations.
  2. Hallucinate new synthetic tokens not present in the ephemeral vault (e.g., `fn_99`).
* **Handling**:
  SynthoMorphix records all unmapped tokens in the `unmapped_tokens` divergence report (FR-08) and sets `exact_match = False`. Preserved tokens are restored, but omitted tokens cannot be reconstructed.

### 6. Single-File Scope
* **Observed Behavior**:
  Phase I processes Python files individually. Cross-module symbol resolution across multiple packages or external repositories is scheduled for Phase II.

---

### 7. L2 Pre-Suture Semantic Execution Constraint
* **Observed Behavior**:
  At protection level `L2`, all string literals are replaced with synthetic tokens (`"str_01"`, `"str_02"`, etc.) in order to conceal hardcoded sensitive values before transmission to the cloud.
* **Semantic Impact Prior to Suture**:
  Strings functioning as dictionary lookup keys (e.g. `state_holder["seed"]` receiving distinct tokens `"str_01"`, `"str_02"` across different functions) or runtime constants (e.g. `.encode("utf-8")` becoming `.encode("str_04")`) cannot be executed *in their scrubbed form* prior to suture reconstruction without triggering a `KeyError` or `LookupError: unknown encoding`.
* **Designed Boundary**:
  De-identified code at L2 is an intermediate artifact intended for LLM completion; the sutured code restores all strings losslessly. In Phase II, string de-identification will implement string-interning (identical string constants map to identical synthetic tokens) and preserve standard runtime encoding literals (`"utf-8"`, `"ascii"`).