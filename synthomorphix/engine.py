"""
SynthoMorphix: Academic-Grade Compiler Gateway & AST Scrubber
Base Paper: Zhou Yang et al., IEEE Transactions on Software Engineering (TSE) 2024.
Reference: De-identification and lexical obfuscation for privacy-preserving code analysis.

This module provides modern tree-sitter based static discovery and lexical de-identification
for Python source code, supporting multi-level de-identification, grammatical role assignment,
active LEGB lexical scoping, dynamic reflection risk mitigation, and reverse mapping vaults.
"""

from __future__ import annotations

import builtins
import keyword
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser


# Initialize Tree-sitter modern language binding (tree-sitter>=0.22.0)
PY_LANGUAGE = Language(tspython.language())


# Set of dynamic reflection functions / constructs to monitor
DYNAMIC_CONSTRUCTS: Set[str] = {
    "getattr",
    "setattr",
    "hasattr",
    "eval",
    "exec",
    "globals",
    "locals",
}

# Standard built-in names from the Python runtime
BUILTIN_NAMES: Set[str] = set(dir(builtins))

# Python reserved keywords
PYTHON_KEYWORDS: Set[str] = set(keyword.kwlist)

# Explicitly preserved conventional & runtime identifier names
PRESERVED_IDENTIFIERS: Set[str] = {
    "self",
    "cls",
}

# Common standard library and builtin method names that must never be assumed
# to be unique project methods when called on an arbitrary receiver
COMMON_LIBRARY_METHODS: Set[str] = {
    "get",
    "update",
    "format",
    "items",
    "values",
    "keys",
    "append",
    "join",
    "split",
    "read",
    "write",
    "send",
    "post",
}


@dataclass
class SymbolCatalog:
    """Stores statically collected symbols and imports across the module AST."""

    imported_base_names: Set[str] = field(default_factory=set)
    declared_function_names: Set[str] = field(default_factory=set)
    declared_class_names: Set[str] = field(default_factory=set)
    has_dynamic_constructs: bool = False
    dynamic_constructs_found: Set[str] = field(default_factory=set)
    # Callee name -> {original_param_name: synthetic_token}
    callee_param_map: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # Callee names with conflicting signatures
    conflicting_callee_names: Set[str] = field(default_factory=set)
    # Number of times each function/method name is declared across the project
    function_definition_counts: Dict[str, int] = field(default_factory=dict)
    # Ambiguous kwarg call warnings recorded during scrubbing
    ambiguous_kwarg_warnings: List[str] = field(default_factory=list)


@dataclass
class ScopeFrame:
    """Represents an active lexical frame in the scope stack."""

    name: str
    kind: str  # 'global', 'function', or 'class'
    declared_symbols: Dict[str, str] = field(default_factory=dict)  # original_ident -> synthetic_token


class TokenGenerator:
    """Generates sequentially indexed grammatical role-based synthetic tokens."""

    def __init__(self) -> None:
        self.counters: Dict[str, int] = {
            "fn": 0,
            "cls": 0,
            "arg": 0,
            "var": 0,
            "cmt": 0,
            "str": 0,
        }

    def next_token(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}_{self.counters[prefix]:02d}"


def is_dunder(name: str) -> bool:
    """Returns True if the identifier is a dunder name (__xxx__)."""
    return len(name) >= 4 and name.startswith("__") and name.endswith("__")


def collect_project_symbols_and_imports(root_node: Node, source_bytes: bytes) -> SymbolCatalog:
    """
    Pass 1: Static Discovery
    Recursively traverses the AST to identify:
    1. Imported base names (e.g., 'import os, sys', 'from math import sqrt as s', 'import x.y.z' -> 'x')
    2. Declared function and class definitions (to identify method calls like self.method())
    3. Dynamic reflection constructs (getattr, setattr, eval, exec, etc.)
    """
    catalog = SymbolCatalog()

    def get_node_text(node: Node) -> str:
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def visit(node: Node) -> None:
        node_type = node.type

        # 1. Imports
        if node_type == "import_statement":
            # e.g., import os, sys / import x.y.z / import numpy as np
            for child in node.children:
                if child.type == "dotted_name":
                    # First identifier in dotted name is the base imported module name in namespace
                    first_ident = child.child_by_field_name("name") or (child.children[0] if child.children else None)
                    if first_ident:
                        catalog.imported_base_names.add(get_node_text(first_ident))
                    else:
                        # Fallback: first token split by dot
                        catalog.imported_base_names.add(get_node_text(child).split(".")[0])
                elif child.type == "aliased_import":
                    # import foo as bar -> 'bar' is bound in namespace
                    alias_child = child.child_by_field_name("alias")
                    if alias_child:
                        catalog.imported_base_names.add(get_node_text(alias_child))
                    else:
                        name_child = child.child_by_field_name("name")
                        if name_child:
                            catalog.imported_base_names.add(get_node_text(name_child).split(".")[0])

        elif node_type == "import_from_statement":
            # e.g., from math import sqrt as s, pi
            module_name_node = node.child_by_field_name("module_name")
            if module_name_node:
                catalog.imported_base_names.add(get_node_text(module_name_node).split(".")[0])

            # Process individual imported names and aliases
            for child in node.children:
                if child.type == "aliased_import":
                    alias_child = child.child_by_field_name("alias")
                    name_child = child.child_by_field_name("name")
                    if alias_child:
                        catalog.imported_base_names.add(get_node_text(alias_child))
                    if name_child:
                        catalog.imported_base_names.add(get_node_text(name_child))
                elif child.type == "dotted_name":
                    if child != module_name_node:
                        catalog.imported_base_names.add(get_node_text(child))

        # 2. Function & Class Declarations
        elif node_type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                fn_name = get_node_text(name_node)
                catalog.declared_function_names.add(fn_name)
                catalog.function_definition_counts[fn_name] = catalog.function_definition_counts.get(fn_name, 0) + 1
                # Extract declared parameter names for this function
                params_node = node.child_by_field_name("parameters")
                param_set: Set[str] = set()
                if params_node:
                    for p in params_node.children:
                        if p.type in {"identifier"}:
                            param_set.add(get_node_text(p))
                        elif p.type in {"default_parameter", "typed_parameter", "typed_default_parameter"}:
                            p_name = p.child_by_field_name("name")
                            if p_name:
                                param_set.add(get_node_text(p_name))
                if fn_name in catalog.callee_param_map and catalog.callee_param_map[fn_name].keys() != param_set:
                    catalog.conflicting_callee_names.add(fn_name)
                elif fn_name not in catalog.callee_param_map:
                    # Initialize with empty dict; synthetic tokens will be mapped in Pass 2
                    catalog.callee_param_map[fn_name] = {p: "" for p in param_set}

        elif node_type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                cls_name = get_node_text(name_node)
                catalog.declared_class_names.add(cls_name)
                # Look for __init__ in class body to map constructor parameters
                body_node = node.child_by_field_name("body")
                init_params: Set[str] = set()
                if body_node:
                    for child_item in body_node.children:
                        if child_item.type == "function_definition":
                            init_name = child_item.child_by_field_name("name")
                            if init_name and get_node_text(init_name) == "__init__":
                                p_node = child_item.child_by_field_name("parameters")
                                if p_node:
                                    for p in p_node.children:
                                        if p.type == "identifier":
                                            init_params.add(get_node_text(p))
                                        elif p.type in {"default_parameter", "typed_parameter", "typed_default_parameter"}:
                                            pn = p.child_by_field_name("name")
                                            if pn:
                                                init_params.add(get_node_text(pn))
                # Remove self/cls from constructor param set
                init_params.discard("self")
                init_params.discard("cls")
                if cls_name in catalog.callee_param_map and catalog.callee_param_map[cls_name].keys() != init_params:
                    catalog.conflicting_callee_names.add(cls_name)
                elif cls_name not in catalog.callee_param_map:
                    catalog.callee_param_map[cls_name] = {p: "" for p in init_params}

        # 3. Dynamic Reflection Constructs
        elif node_type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                func_text = get_node_text(func_node)
                if func_text in DYNAMIC_CONSTRUCTS:
                    catalog.has_dynamic_constructs = True
                    catalog.dynamic_constructs_found.add(func_text)

        elif node_type == "identifier":
            ident_text = get_node_text(node)
            if ident_text in DYNAMIC_CONSTRUCTS:
                # In Python, passing getattr or eval as higher-order arguments is also a dynamic construct
                catalog.has_dynamic_constructs = True
                catalog.dynamic_constructs_found.add(ident_text)

        for child in node.children:
            visit(child)

    visit(root_node)
    return catalog


def _determine_identifier_role(
    node: Node,
    ident_text: str,
    catalog: SymbolCatalog,
    source_bytes: bytes,
) -> Optional[str]:
    """
    Determines the grammatical role ('fn', 'cls', 'arg', 'var') for an identifier,
    or None if the identifier should not be scrubbed (e.g., non-method attributes,
    unrecognized external properties, imports, builtins, keywords, dunders).
    """
    parent = node.parent
    if parent is None:
        return "var"

    # Function definition name
    if parent.type == "function_definition" and parent.child_by_field_name("name") == node:
        return "fn"

    # Class definition name
    if parent.type == "class_definition" and parent.child_by_field_name("name") == node:
        return "cls"

    # Function parameters
    if parent.type in {"parameters", "lambda_parameters"}:
        return "arg"
    if parent.type in {
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
        "positional_separator",
        "keyword_separator",
        "list_splat_pattern",
        "dictionary_splat_pattern",
    }:
        # Check if node is the parameter identifier or the default value
        name_node = parent.child_by_field_name("name")
        if name_node == node or (name_node is None and parent.children and parent.children[0] == node):
            return "arg"

    # Attribute access: obj.attr
    if parent.type == "attribute":
        attr_node = parent.child_by_field_name("attribute")
        object_node = parent.child_by_field_name("object")

        if attr_node == node:
            # If parent attribute is part of a call: obj.attr()
            grandparent = parent.parent
            if grandparent and grandparent.type == "call" and grandparent.child_by_field_name("function") == parent:
                # If the attribute matches a known declared function/method name, scrub as 'fn'
                if ident_text in catalog.declared_function_names:
                    return "fn"
            # Non-method attribute or undeclared external attribute/method: skip to preserve library API
            return None
        elif object_node == node:
            # The base object (e.g., `self` in `self.method()`, or `my_var` in `my_var.val`)
            return "var"

    # Keyword argument call: func(arg_name=val) or obj.method(arg_name=val)
    if parent.type == "keyword_argument":
        name_node = parent.child_by_field_name("name")
        if name_node == node:
            # Determine callee by walking up to the enclosing 'call' node
            # Node hierarchy: identifier -> keyword_argument -> argument_list -> call
            arg_list = parent.parent
            call_node = arg_list.parent if arg_list and arg_list.type == "argument_list" else None
            
            if call_node and call_node.type == "call":
                func_child = call_node.child_by_field_name("function")
                callee_name = None
                is_ambiguous = False

                if func_child:
                    if func_child.type == "identifier":
                        callee_name = source_bytes[func_child.start_byte:func_child.end_byte].decode("utf-8", errors="replace")
                    elif func_child.type == "attribute":
                        # e.g., self.method(kw=...) or obj.method(kw=...)
                        attr_child = func_child.child_by_field_name("attribute")
                        obj_child = func_child.child_by_field_name("object")
                        obj_text = source_bytes[obj_child.start_byte:obj_child.end_byte].decode("utf-8", errors="replace") if obj_child else ""
                        attr_text = source_bytes[attr_child.start_byte:attr_child.end_byte].decode("utf-8", errors="replace") if attr_child else ""
                        
                        if obj_text in {"self", "cls"}:
                            callee_name = attr_text
                        else:
                            # External or instance receiver: e.g. obj.method(kw=...)
                            callee_name = attr_text
                            if attr_text in COMMON_LIBRARY_METHODS:
                                # Collides with common standard library / builtin method -> ambiguous, leave untouched
                                is_ambiguous = True
                            elif catalog.function_definition_counts.get(attr_text, 0) == 1:
                                # Defined exactly once across project and not a common library method
                                # Safely resolve to that unique project method
                                is_ambiguous = False
                            elif catalog.function_definition_counts.get(attr_text, 0) > 1:
                                # Defined more than once across project -> ambiguous receiver
                                is_ambiguous = True
                            else:
                                # Not defined in project -> external library method
                                is_ambiguous = True

                # Check if callee is a project-defined function, method, or class
                if callee_name and (callee_name in catalog.declared_function_names or callee_name in catalog.declared_class_names):
                    # Check for conflicting signatures across project
                    if callee_name in catalog.conflicting_callee_names:
                        catalog.ambiguous_kwarg_warnings.append(
                            f"Conflicting definition for callee '{callee_name}'; kwarg '{ident_text}' left untouched."
                        )
                        return None

                    if is_ambiguous:
                        catalog.ambiguous_kwarg_warnings.append(
                            f"Ambiguous receiver for call to '{callee_name}'; kwarg '{ident_text}' left untouched."
                        )
                        return None

                    # If this kwarg is one of that callee's declared parameters, return 'kwarg_call'
                    callee_params = catalog.callee_param_map.get(callee_name, {})
                    if ident_text in callee_params:
                        return "kwarg_call"

            # External library call (e.g., re.sub(..., count=1)) or unrecognized kwarg -> leave untouched
            return None

    return "var"


def analyze_and_scrub(
    source_code: str,
    mask_level: str = "L1",
    dynamic_policy: str = "block",
) -> Dict[str, Any]:
    """
    Pass 2: Lexical Scoping & AST Scrubber
    Masking levels:
      - 'L0': Pass-through (no masking).
      - 'L1': Identifiers only (functions, classes, variables, arguments).
      - 'L2': L1 + comments and string literals (preserving f-string interpolations).

    Parameters:
      source_code: Python source code string.
      mask_level: 'L0', 'L1', or 'L2'.
      dynamic_policy: 'block' or 'warn'/'ignore'. If 'block' and dynamic constructs exist,
                      aborts and returns status: 'BLOCKED_DYNAMIC_RISK'.

    Returns:
      Dictionary with:
        - status: "SUCCESS" or "BLOCKED_DYNAMIC_RISK"
        - scrubbed_code: De-identified Python source code
        - reverse_vault: Mapping of {synthetic_token: original_text}
        - tokens_isolated: Count of protected tokens
        - dynamic_risk: Boolean flag
    """
    if mask_level not in {"L0", "L1", "L2"}:
        raise ValueError(f"Unsupported mask_level '{mask_level}'. Must be 'L0', 'L1', or 'L2'.")

    source_bytes = source_code.encode("utf-8")
    parser = Parser(PY_LANGUAGE)
    tree = parser.parse(source_bytes)
    root_node = tree.root_node

    # Pass 1: Static Discovery
    catalog = collect_project_symbols_and_imports(root_node, source_bytes)

    if catalog.has_dynamic_constructs and dynamic_policy == "block":
        return {
            "status": "BLOCKED_DYNAMIC_RISK",
            "scrubbed_code": "",
            "reverse_vault": {},
            "tokens_isolated": 0,
            "dynamic_risk": True,
            "ambiguous_kwarg_warnings": [],
        }

    if mask_level == "L0":
        return {
            "status": "SUCCESS",
            "scrubbed_code": source_code,
            "reverse_vault": {},
            "tokens_isolated": 0,
            "dynamic_risk": catalog.has_dynamic_constructs,
            "ambiguous_kwarg_warnings": [],
        }

    # Pass 2: Active Lexical Scope Stack and Scrubber
    token_gen = TokenGenerator()
    reverse_vault: Dict[str, str] = {}
    replacements: List[Tuple[int, int, str]] = []  # (start_byte, end_byte, replacement_text)

    # Scope stack maintains frames: [ScopeFrame(name='global', kind='global')]
    scope_stack: List[ScopeFrame] = [ScopeFrame(name="global", kind="global")]
    scope_counter = 0

    def get_node_text(node: Node) -> str:
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def lookup_symbol_in_scope_stack(ident: str) -> Optional[str]:
        """LEGB search up the active scope stack."""
        for frame in reversed(scope_stack):
            if ident in frame.declared_symbols:
                return frame.declared_symbols[ident]
        return None

    def register_symbol_in_current_scope(ident: str, role_prefix: str) -> str:
        """Assigns a new synthetic token for the identifier in the current scope frame."""
        synth_token = token_gen.next_token(role_prefix)
        scope_stack[-1].declared_symbols[ident] = synth_token
        reverse_vault[synth_token] = ident
        return synth_token

    def is_protected_name(name: str) -> bool:
        """Determines if the token must be preserved as-is."""
        return (
            name in catalog.imported_base_names
            or name in BUILTIN_NAMES
            or name in PYTHON_KEYWORDS
            or name in PRESERVED_IDENTIFIERS
            or is_dunder(name)
        )

    def process_node(node: Node) -> None:
        nonlocal scope_counter
        node_type = node.type

        # Scope management: Function or Class definition entered
        pushed_scope = False
        if node_type in {"function_definition", "class_definition"}:
            name_node = node.child_by_field_name("name")
            scope_name = get_node_text(name_node) if name_node else f"anon_{scope_counter}"
            scope_counter += 1
            frame_kind = "function" if node_type == "function_definition" else "class"
            scope_stack.append(ScopeFrame(name=scope_name, kind=frame_kind))
            pushed_scope = True

        # Handle comments for L2
        if mask_level == "L2" and node_type == "comment":
            cmt_token = token_gen.next_token("cmt")
            original_cmt = get_node_text(node)
            # original_cmt starts with '#'
            reverse_vault[cmt_token] = original_cmt.lstrip("#").lstrip(" ")
            replacements.append((node.start_byte, node.end_byte, f"# {cmt_token}"))
            return

        # Handle strings for L2 (differentiating normal strings vs f-strings)
        if mask_level == "L2" and node_type == "string":
            # Check if this string is part of an f-string (interpolated string)
            # In tree-sitter-python, an f-string is typed 'string' containing 'interpolation' children
            has_interpolation = any(child.type == "interpolation" for child in node.children)
            if not has_interpolation:
                # Normal string literal -> replace whole string while preserving quote format and prefixes
                original_str = get_node_text(node)
                str_token = token_gen.next_token("str")
                
                # Identify any leading string prefix: r, u, b, br, rb, etc.
                import re
                prefix_match = re.match(r"^([rRuUbB]{1,2})", original_str)
                prefix = prefix_match.group(1) if prefix_match else ""
                rest = original_str[len(prefix):]
                
                # Identify quote delimiter ('"", ''', ", ')
                if rest.startswith('"""') and rest.endswith('"""') and len(rest) >= 6:
                    delimiter = '"""'
                    inner_str = rest[3:-3]
                elif rest.startswith("'''") and rest.endswith("'''") and len(rest) >= 6:
                    delimiter = "'''"
                    inner_str = rest[3:-3]
                elif rest.startswith('"') and rest.endswith('"') and len(rest) >= 2:
                    delimiter = '"'
                    inner_str = rest[1:-1]
                elif rest.startswith("'") and rest.endswith("'") and len(rest) >= 2:
                    delimiter = "'"
                    inner_str = rest[1:-1]
                else:
                    delimiter = '"'
                    inner_str = rest

                reverse_vault[str_token] = inner_str
                replacements.append((node.start_byte, node.end_byte, f'{prefix}{delimiter}{str_token}{delimiter}'))
                return
            else:
                # F-string: Scrub only the string_content parts, preserving interpolation expressions!
                for child in node.children:
                    if child.type == "string_content":
                        str_content_text = get_node_text(child)
                        if str_content_text:
                            str_token = token_gen.next_token("str")
                            reverse_vault[str_token] = str_content_text
                            replacements.append((child.start_byte, child.end_byte, str_token))
                    else:
                        process_node(child)
                if pushed_scope:
                    scope_stack.pop()
                return

        # Handle Identifiers
        if node_type == "identifier":
            ident_text = get_node_text(node)
            if not is_protected_name(ident_text):
                role = _determine_identifier_role(node, ident_text, catalog, source_bytes)
                if role is not None:
                    # Check if this identifier is a call-site keyword argument for a project callee
                    if role == "kwarg_call":
                        # Look up enclosing call's callee to find the matching synthetic token
                        arg_list = node.parent.parent if node.parent else None
                        call_node = arg_list.parent if arg_list and arg_list.type == "argument_list" else None
                        func_child = call_node.child_by_field_name("function") if call_node else None
                        callee_name = None
                        if func_child:
                            if func_child.type == "identifier":
                                callee_name = get_node_text(func_child)
                            elif func_child.type == "attribute":
                                attr_child = func_child.child_by_field_name("attribute")
                                if attr_child:
                                    callee_name = get_node_text(attr_child)
                        
                        mapped_kw_token = catalog.callee_param_map.get(callee_name, {}).get(ident_text)
                        if mapped_kw_token:
                            replacements.append((node.start_byte, node.end_byte, mapped_kw_token))
                        return

                    # Check if already declared in accessible lexical scope
                    existing_token = lookup_symbol_in_scope_stack(ident_text)

                    parent = node.parent
                    is_definition = False
                    if parent:
                        if parent.type == "function_definition" and parent.child_by_field_name("name") == node:
                            is_definition = True
                        elif parent.type == "class_definition" and parent.child_by_field_name("name") == node:
                            is_definition = True
                        elif parent.type in {"parameters", "lambda_parameters"}:
                            is_definition = True
                        elif parent.type in {
                            "typed_parameter",
                            "default_parameter",
                            "typed_default_parameter",
                        }:
                            name_child = parent.child_by_field_name("name")
                            if name_child == node or (name_child is None and parent.children and parent.children[0] == node):
                                is_definition = True

                    if is_definition:
                        # In class or function definition, the name is declared in the enclosing scope frame
                        target_frame_idx = -2 if pushed_scope and len(scope_stack) > 1 else -1
                        synth_token = token_gen.next_token(role)
                        scope_stack[target_frame_idx].declared_symbols[ident_text] = synth_token
                        if role in {"fn", "cls"}:
                            scope_stack[0].declared_symbols[ident_text] = synth_token
                        elif role == "arg":
                            # Register this parameter token in callee_param_map for the current enclosing scope
                            current_func_scope = scope_stack[-1].name
                            if current_func_scope in catalog.callee_param_map:
                                catalog.callee_param_map[current_func_scope][ident_text] = synth_token
                            # If this function is __init__, also register under the class name!
                            if current_func_scope == "__init__" and len(scope_stack) >= 2 and scope_stack[-2].kind == "class":
                                enclosing_cls_name = scope_stack[-2].name
                                if enclosing_cls_name in catalog.callee_param_map:
                                    catalog.callee_param_map[enclosing_cls_name][ident_text] = synth_token

                        reverse_vault[synth_token] = ident_text
                        replacements.append((node.start_byte, node.end_byte, synth_token))
                    elif existing_token is not None:
                        # LEGB matched an existing variable/param/func/class in current or parent scope
                        replacements.append((node.start_byte, node.end_byte, existing_token))
                    else:
                        # If calling or referencing a declared method on self/instance
                        if role == "fn" and ident_text in catalog.declared_function_names:
                            synth_token = lookup_symbol_in_scope_stack(ident_text)
                            if not synth_token:
                                synth_token = token_gen.next_token("fn")
                                scope_stack[0].declared_symbols[ident_text] = synth_token
                                reverse_vault[synth_token] = ident_text
                            replacements.append((node.start_byte, node.end_byte, synth_token))
                        elif role == "cls" and ident_text in catalog.declared_class_names:
                            synth_token = lookup_symbol_in_scope_stack(ident_text)
                            if not synth_token:
                                synth_token = token_gen.next_token("cls")
                                scope_stack[0].declared_symbols[ident_text] = synth_token
                                reverse_vault[synth_token] = ident_text
                            replacements.append((node.start_byte, node.end_byte, synth_token))
                        elif ident_text in catalog.declared_class_names:
                            synth_token = lookup_symbol_in_scope_stack(ident_text)
                            if not synth_token:
                                synth_token = token_gen.next_token("cls")
                                scope_stack[0].declared_symbols[ident_text] = synth_token
                                reverse_vault[synth_token] = ident_text
                            replacements.append((node.start_byte, node.end_byte, synth_token))
                        else:
                            # Fresh local/global variable assignment or first-time read
                            synth_token = register_symbol_in_current_scope(ident_text, role)
                            replacements.append((node.start_byte, node.end_byte, synth_token))

        # Recurse children
        for child in node.children:
            process_node(child)

        # Scope exit
        if pushed_scope:
            scope_stack.pop()

    # Traverse AST and accumulate replacements
    process_node(root_node)

    # Apply replacements in reverse byte order to preserve character offsets exactly
    sorted_replacements = sorted(replacements, key=lambda x: x[0], reverse=True)

    scrubbed_bytes = bytearray(source_bytes)
    for start_byte, end_byte, rep_text in sorted_replacements:
        rep_bytes = rep_text.encode("utf-8")
        scrubbed_bytes[start_byte:end_byte] = rep_bytes

    scrubbed_code = scrubbed_bytes.decode("utf-8", errors="replace")

    return {
        "status": "SUCCESS",
        "scrubbed_code": scrubbed_code,
        "reverse_vault": reverse_vault,
        "tokens_isolated": len(reverse_vault),
        "dynamic_risk": catalog.has_dynamic_constructs,
        "ambiguous_kwarg_warnings": catalog.ambiguous_kwarg_warnings,
    }


def restore_code(scrubbed_code: str, reverse_vault: Dict[str, str]) -> str:
    """
    Utility function to restore de-identified code using the reverse vault mappings.
    Sorts synthetic tokens by descending length to prevent partial prefix replacements.
    """
    import re

    if not reverse_vault:
        return scrubbed_code

    # Build regex matching word-bounded synthetic tokens
    sorted_tokens = sorted(reverse_vault.keys(), key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(token) for token in sorted_tokens) + r")\b")

    def replace_match(match: re.Match) -> str:
        token = match.group(0)
        return reverse_vault.get(token, token)

    return pattern.sub(replace_match, scrubbed_code)


if __name__ == "__main__":
    sample_code = '''
import os, sys
from math import sqrt as s

class DataProcessor:
    def __init__(self, raw_data):
        self.raw_data = raw_data
        self.count = len(raw_data)

    def process(self, multiplier=2):
        # Calculate intermediate metric
        delta = s(self.count) * multiplier
        return f"Processed {delta} items"

def compute():
    processor = DataProcessor([1, 4, 9])
    return processor.process()
'''

    print("--- Original Code ---")
    print(sample_code)

    print("\n--- Testing L1 Masking ---")
    res_l1 = analyze_and_scrub(sample_code, mask_level="L1")
    print("Status:", res_l1["status"])
    print("Tokens Isolated:", res_l1["tokens_isolated"])
    print(res_l1["scrubbed_code"])

    print("\n--- Testing L2 Masking (with f-strings & comments) ---")
    res_l2 = analyze_and_scrub(sample_code, mask_level="L2")
    print("Status:", res_l2["status"])
    print(res_l2["scrubbed_code"])

    print("\n--- Testing Dynamic Construct Risk Block ---")
    dynamic_code = """
def run_dynamic(code_str):
    eval(code_str)
"""
    res_dyn = analyze_and_scrub(dynamic_code, mask_level="L1", dynamic_policy="block")
    print("Status:", res_dyn["status"])
    print("Dynamic Risk Flag:", res_dyn["dynamic_risk"])
