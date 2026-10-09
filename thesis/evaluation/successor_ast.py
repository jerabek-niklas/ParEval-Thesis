"""Successor-only AST representation, never a replacement for a v1 proof.

Only the demonstrated CPython 3.8 Index wrapper is removed. Unsupported
ExtSlice nodes fail closed. This does not claim arbitrary-version equivalence.
"""
from __future__ import annotations

import ast
import json

from thesis.evaluation.condition_hashing import utf8_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused

VERSION = "successor_ast.index_v1"


def normalize(node):
    if isinstance(node, ast.AST):
        name = type(node).__name__
        if name == "Index":
            if tuple(node._fields) != ("value",):
                raise RecoveryRefused("unrecognized Index representation")
            return normalize(node.value)
        if name == "ExtSlice":
            raise RecoveryRefused("ExtSlice compatibility is not proven")
        return {"node": name, "fields": {
            key: normalize(value) for key, value in ast.iter_fields(node)
            if value is not None and value != []}}
    if isinstance(node, list):
        return [normalize(value) for value in node]
    return node


def projection(text, excluded=()):
    """Same registered routing exclusions as v1; no extra exclusions."""
    class RemoveRouting(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            return None if node.name in excluded else self.generic_visit(node)

    tree = RemoveRouting().visit(ast.parse(text))
    return json.dumps(normalize(tree), sort_keys=True, separators=(",", ":"))


def projection_sha256(text, excluded=()):
    return utf8_sha256(projection(text, excluded))
