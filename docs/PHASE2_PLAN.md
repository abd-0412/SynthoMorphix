# SynthoMorphix Phase II Research & Implementation Plan

This roadmap outlines the planned research, architecture, and empirical evaluation for Phase II of the SynthoMorphix project (Base Paper: Zhou Yang et al., IEEE Transactions on Software Engineering 2024).

---

## 1. Automated Reverse Proxy Gateway
* **Objective**: Transparent interceptor proxy for OpenAI, Anthropic, and open-source model API calls (`/v1/chat/completions`).
* **Design**: Intercept outgoing requests from IDE extensions (VS Code, Cursor) and terminal coding agents. Automatically apply AST de-identification in-flight, cache the volatile reverse vault in RAM, forward the scrubbed prompt to the cloud provider, and deterministically suture incoming responses before returning them to the editor.

---

## 2. Code Generation Utility Evaluation
* **Objective**: Measure the functional impact of de-identification on LLM code synthesis accuracy.
* **Benchmark Suites**:
  - **HumanEval+** (164 coding tasks with expanded test oracles)
  - **MBPP+** (Mostly Basic Python Problems with sanitization)
* **Methodology**:
  1. Evaluate Pass@1 on original benchmark prompts vs. Pass@1 on scrubbed (L1 and L2) prompts.
  2. Compute Utility Retention Ratio:
     $$\text{Utility Retention} = \frac{\text{Pass@1}_{\text{scrubbed}}}{\text{Pass@1}_{\text{original}}}$$
  3. Validate whether structural graph-isomorphism preserves code model reasoning capability.

---

## 3. Privacy Evaluation via Membership Inference Attacks (MIA)
* **Theoretical Foundation**: Inspired by Yang et al., IEEE TSE 2024 (Membership Inference on Code Models).
* **Experimental Protocol**:
  1. Select a proprietary code corpus $\mathcal{D}_{\text{private}}$ split into training $\mathcal{D}_{\text{train}}$ and holdout $\mathcal{D}_{\text{test}}$.
  2. Fine-tune a small open-weight code model (e.g., StarCoder-1B or Qwen2.5-Coder-1.5B) on $\mathcal{D}_{\text{train}}$ in plaintext.
  3. Fine-tune an identical instance on $\mathcal{D}_{\text{train}}^{\text{scrubbed}}$ (processed through SynthoMorphix).
  4. Run a loss/perplexity-based Membership Inference Attack (MIA) to determine whether a code snippet was part of the training set.
  5. Compare privacy protection metrics:
     - True Positive Rate (TPR) at low False Positive Rate (FPR $\le 1\%$)
     - Area Under ROC Curve (AUC-ROC)
  6. Hypothesized Outcome: Scrubbed models should demonstrate near-random guessing ($AUC \approx 0.50$), confirming that proprietary tokens cannot be extracted by memorization attacks.

---

## 4. Adversarial Identifier Recovery Evaluation
* **Objective**: Evaluate whether frontier models (e.g., GPT-4o, Claude 3.5 Sonnet) can infer original variable and function names from context alone.
* **Methodology**:
  - Prompt adversarial models with scrubbed code payloads and instruct them to predict original identifier names.
  - Compute Top-1 and Top-5 semantic recovery accuracy.

---

## 5. Multi-Language AST Grammar Expansion
* **Objective**: Expand the Tree-sitter grammar catalog beyond Python to include JavaScript/TypeScript, Java, C++, and Go.
* **Architecture**: Leverage the existing language-agnostic suture reconstructor $R(O, V)$ with pluggable grammar visitor modules.

---

## 6. Academic Publication Milestone Plan
* Target Venue: IEEE Transactions on Software Engineering (TSE) / ACM TOSEM / ASE 2025 Tool Demonstration.
* Status: All features described in this document are **[Specified for Phase II - Planned]**.
