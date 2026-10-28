# SynthoMorphix: Client-Side Python Code De-Identification Gateway

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Academic%20Research-green.svg)]()
[![FastAPI](https://img.shields.io/badge/Gateway-FastAPI%20Loopback-009688.svg)](http://127.0.0.1:8000)

> **Base Paper**: Zhou Yang et al., *IEEE Transactions on Software Engineering (TSE)*, 2024.  
> **Phase I Implementation**: ~30-40% Core Working Prototype with Empirical Benchmarking.

SynthoMorphix is a client-side privacy gateway for developers utilizing cloud-hosted coding assistants (e.g., ChatGPT, Claude, GitHub Copilot). It uses modern **Tree-sitter AST transformation** to de-identify proprietary Python source code prior to external transmission, storing original symbol mappings in volatile, in-memory RAM vaults. Responses returned from the model are deterministically stitched back using a lexical suture operator.

---

## Architecture Overview

```
                      +------------------------------------------+
                      |         Local Development Machine        |
                      |                                          |
                      |  [Proprietary Python Source Code]        |
                      |                    |                     |
                      |                    v                     |
                      |        +-----------------------+         |
                      |        |  Pass 1: AST Discovery |         |
                      |        |  (Imports, Dynamic)   |         |
                      |        +-----------+-----------+         |
                      |                    |                     |
                      |                    v                     |
                      |        +-----------------------+         |
                      |        |  Pass 2: AST Scrubber |         |
                      |        |  (LEGB Scopes, Roles) |         |
                      |        +-----+-----------+-----+         |
                      |              |           |               |
                      |   Scrubbed   |           | Reverse Vault |
                      |   Payload    |           | (RAM-only)    |
                      |      v       |           v               |
                      |      |       |      +---------+          |
                      |      |       |      | RAM     |          |
                      |      |       |      | Vault   |          |
                      |      |       |      | Registry|          |
                      |      |       |      +----+----+          |
                      +------+-------+-----------+---------------+
                             |                   |
               Public WAN    |                   | Local Loopback
               (Untrusted)   |                   |
                             v                   v
                    +----------------+  +-------------------+
                    | Cloud LLM API  |  | Suture Operator   |
                    | (ChatGPT, etc) |  | R(O, V) -> Code   |
                    +--------+-------+  +---------+---------+
                             |                    ^
                             | Patched Response   |
                             +--------------------+
                                (With Code Fences)
```

---

## Implementation Status Table

| Module / Component | Phase I Status | Phase II Status | Notes |
| :--- | :---: | :---: | :--- |
| **AST Parser Binding** | **[Implemented]** | — | `tree-sitter>=0.22.0` modern Python binding |
| **Static Import & Symbol Discovery** | **[Implemented]** | — | Preserves `import os, sys`, `math.sqrt as s` |
| **LEGB Lexical Scope Scrubber** | **[Implemented]** | — | Supports `fn_XX`, `var_XX`, `cls_XX`, `arg_XX` |
| **L2 Comments & String Literals** | **[Implemented]** | — | De-identifies literals while preserving f-string slots |
| **Dynamic Reflection Safety Gate** | **[Implemented]** | — | Flags & blocks `eval`, `exec`, `getattr` |
| **Deterministic Suture Reconstructor** | **[Implemented]** | — | Handles code fences, diffs, and collision prevention |
| **Volatile RAM Vault Registry** | **[Implemented]** | — | Zero disk writes; purge endpoint `/api/v1/session/clear` |
| **FastAPI Loopback Gateway** | **[Implemented]** | — | Local daemon running on `127.0.0.1:8000` |
| **Single-Page Executive Dashboard** | **[Implemented]** | — | Clean light theme with zero emojis and Feather SVGs |
| **Automated Benchmark Harness** | **[Implemented]** | — | Evaluates 12 benchmark samples under L1/L2 |
| **Transparent LLM Reverse Proxy** | — | **[Specified for Phase II]** | Direct proxy for OpenAI/Anthropic SDKs |
| **HumanEval+ Utility Evaluation** | — | **[Specified for Phase II]** | Measures Pass@1 on scrubbed prompts |
| **MIA Membership Inference Attacks** | — | **[Specified for Phase II]** | Perplexity-based MIA evaluation |
| **Multi-Language Grammar Catalog** | — | **[Specified for Phase II]** | TypeScript, Java, C++, Go Tree-sitter parsers |

---

## Directory Layout

```
synthomorphix-project/
├── synthomorphix/              # Core Gateway Library Package
│   ├── __init__.py             # Public API exports
│   ├── engine.py               # Tree-sitter AST Scrubber & Static Discovery
│   ├── reconstructor.py        # Suture Operator R(O, V) & Discrepancy Auditor
│   └── main.py                 # FastAPI Loopback Daemon & Session Registry
├── tests/                      # Automated Verification Test Suite
│   ├── test_scrub.py           # Pytest suite for AST de-identification
│   ├── test_reconstruct.py     # Pytest suite for suture reconstruction
│   └── test_semantics.py       # Pytest suite for semantic execution equivalence
├── samples/                    # 12 Realistic Benchmark Python Programs
│   ├── 01_payroll.py           # Classes, methods, kwargs, calculations
│   ├── 02_inventory.py         # Default arguments and attribute lookups
│   ├── 03_auth.py              # Global salt constants and hashing
│   ├── 04_data_cleaning.py     # Regex sanitization and list comprehensions
│   ├── 05_nested_closure.py    # Inner function closures
│   ├── 06_shadowing.py         # Cross-scope variable shadowing
│   ├── 07_decorators.py        # Python decorators (@functools.wraps)
│   ├── 08_kwargs.py            # Keyword argument calls and defaults
│   ├── 09_lambdas.py           # Lambda sorting and anonymous functions
│   ├── 10_comprehensions.py    # Dict and set comprehensions
│   ├── 11_global_nonlocal.py   # Global and nonlocal scope bindings
│   └── 12_dynamic_risk.py      # Reflection constructs (getattr, eval)
├── eval/                       # Benchmark & Metrics Infrastructure
│   ├── metrics.py              # LLR (with category breakdown), compile_ok, structural_match, latency
│   ├── run_benchmark.py        # Benchmark execution runner
│   ├── results.csv             # Empirical measurement dataset
│   └── results.md              # Tabular markdown benchmark report
├── docs/                       # Research Documentation
│   ├── KNOWN_LIMITATIONS.md    # Limitations & empirical edge cases
│   └── PHASE2_PLAN.md          # Reverse proxy, HumanEval+, MIA privacy evaluation
├── index.html                  # Executive 3-Column Security Dashboard
├── test_suite.py               # Standalone verification runner
├── requirements.txt            # Minimal runtime dependencies
├── .gitignore                  # Git ignore rules
└── README.md                   # Project documentation
```

---

## Installation & Setup

```bash
# Clone the repository
git clone https://github.com/your-org/synthomorphix.git
cd synthomorphix

# Install dependencies
pip install -r requirements.txt
```

---

## How to Run

### 1. Run the Verification Tests
```bash
pytest -v
```

### 2. Run the Empirical Benchmark Suite
```bash
python eval/run_benchmark.py
```

### 3. Launch the Local Loopback Gateway & Dashboard
```bash
python synthomorphix/main.py
```
Open **`http://127.0.0.1:8000/`** in any web browser to interact with the 3-column security dashboard.

---

## Dynamic Reflection Security Policy

* **Default Mode (`dynamic_policy="block"`)**: Fail-closed. If dynamic reflection constructs (`getattr`, `eval`, `exec`) are detected in the AST, the engine halts de-identification, returning `status: "BLOCKED_DYNAMIC_RISK"` with an empty payload `""` (the original source code is withheld), and disables Step 2 in the dashboard.
* **Unsafe Pass-Through (`dynamic_policy="pass"`)**:
  > [!WARNING]
  > **UNSAFE OPERATIONAL MODE**: Running with `dynamic_policy="pass"` bypasses the security block and passes code with dynamic reflection constructs to downstream models. Because runtime string lookups cannot be statically validated, this mode is explicitly flagged as **UNSAFE** and documented in `docs/KNOWN_LIMITATIONS.md`.

---

## Empirical Benchmark Summary (Measured Sample Counts)

Evaluated across all 12 benchmark samples under L1 and L2 masking levels (24 benchmark evaluations total), plus a ~1000-line synthetic benchmark:

* **Dynamic Risk Fail-Closed Blocks**: **2/24 evaluations** (`12_dynamic_risk.py` blocked under default policy with payload withheld)
* **Bytecode Compilation Validity**: **22/22 active evaluations** compile to valid Python bytecode without syntax regressions
* **Runtime Semantic Execution Equivalence (sums to 24/24)**:
  - **PASS**: **11/24 runs** (all 11 active L1 samples produce execution output identical to original)
  - **NOT_APPLICABLE**: **11/24 runs** (all 11 active L2 samples; string literals masked prior to suture)
  - **BLOCKED**: **2/24 runs** (sample 12 blocked under fail-closed dynamic policy)
  - **FAIL**: **0/24 runs** (zero regressions across all benchmark samples)
* **Lossless Suture Round-Trip Determinism**: **22/22 active evaluations** restored identically via $R(O, V)$
* **AST Structural Isomorphism Rate**: **21/22 active evaluations** retain identical Tree-sitter node type hierarchies (1 documented xfail on raw regex string split in sample 04 under L2)
* **Mean LLR (Code Identifiers Leaked)**: **0.0332** across active evaluations
* **Mean Identifier Coverage (Hidden Identifiers)**: **0.9594** across active evaluations (satisfies mathematical identity: `Identifier Coverage + LLR == 1.0000` across all active samples)
* **Mean Renamed Name Coverage (Vault)**: **1.0000** (ratio of declared renamable identifiers substituted in the ephemeral reverse vault)
* **Mean Small-Sample Latency**: **0.62 ms** per file (Sub-millisecond overhead)
* **Large File Benchmark (~1086 Lines Synthetic Code)**:
  - Synthetic tokens isolated: **835**
  - Scrub latency: **46.43 ms** | Reconstruct latency: **26.66 ms** | Total latency: **73.09 ms**
  - Bytecode compilation: **Pass** | Lossless round-trip suture: **Pass**
  - LLR: **0.0241** | Ident Coverage (Hidden): **0.9725** | Renamed Name Coverage (Vault): **1.0000**

*(See `eval/results.md` and `docs/KNOWN_LIMITATIONS.md` for individual sample measurements and limitation breakdowns).*
