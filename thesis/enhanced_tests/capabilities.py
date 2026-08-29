"""Enhanced capability enforcement — the ONE productive source of truth.

Validation (`specs.py::validate_spec`), LLM spec generation
(`generate_test_specs.py`) and the deterministic mutation
(`specs.py::_mutants_of`) all ask THIS module. There is deliberately no second
capability table: `enhanced_capabilities.json` is the AUDIT document
(AUDIT_ONLY_NOT_ENFORCED) and `enhanced_policy.json` is the ENFORCED policy
derived from it by `derive_enhanced_policy.py`.

A pattern is in exactly one of three states for a benchmark:

    supported        offered, generated, mutated into, accepted
    unsupported      never offered/generated/accepted. Either the benchmark has
                     no reachable ENHANCED_FILL hook, so the label would only
                     fake diversity (`no_pattern_effect`), or the frozen oracle
                     would execute undefined behaviour on that input
                     (`unsafe_pattern_for_benchmark`), or the benchmark has no
                     single canonical fill site for explicit values.
    deferred_policy  technically producible, but whether it is a legitimate
                     input needs one of the OPEN E2-B policies
                     (EXTREME_PATTERN_SEMANTICS, tolerance policy). Treated
                     like unsupported for generation/validation, but reported
                     separately so it is never mistaken for a permanent answer.

Size constraints are per benchmark and technical (a documented UB otherwise).
They are NOT a global size-0 rule: SIZE_ZERO_SPEC_POLICY stays open and every
benchmark without an entry keeps accepting size 0.

Python 3.8 compatible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

POLICY_PATH = Path(__file__).resolve().parent / "enhanced_policy.json"

# rejection reasons (stable internal vocabulary; not part of any record schema)
REASON_UNSUPPORTED = "unsupported_pattern_for_benchmark"
REASON_NO_EFFECT = "no_pattern_effect"
REASON_UNSAFE = "unsafe_pattern_for_benchmark"
REASON_DEFERRED = "deferred_policy_pattern"
REASON_INVALID_SIZE = "invalid_size_for_benchmark"
REASON_VALUE_NOT_REPRESENTABLE = "value_not_representable_for_benchmark"

_POLICY_CACHE = None  # type: Optional[Dict[str, Any]]


def load_policy() -> Dict[str, Any]:
    global _POLICY_CACHE
    if _POLICY_CACHE is None:
        if POLICY_PATH.exists():
            with POLICY_PATH.open("r", encoding="utf-8") as handle:
                _POLICY_CACHE = json.load(handle)
        else:
            # No policy file: enforce nothing rather than silently rejecting
            # everything. A checkout without the derived artifact behaves like
            # the pre-E2-A pipeline.
            _POLICY_CACHE = {"benchmarks": {}}
    return _POLICY_CACHE


def benchmark_policy(benchmark: str) -> Optional[Dict[str, Any]]:
    return (load_policy().get("benchmarks") or {}).get(benchmark)


def has_policy(benchmark: str) -> bool:
    return benchmark_policy(benchmark) is not None


def supported_patterns(benchmark: str) -> Optional[List[str]]:
    """Patterns this benchmark actually supports, or None when the benchmark is
    unknown to the policy (then nothing is enforced)."""
    entry = benchmark_policy(benchmark)
    if entry is None:
        return None
    return list(entry.get("supported_patterns") or [])


def effective_patterns(benchmark: str, offered: List[str]) -> List[str]:
    """effective = globally offered INTERSECT benchmark-supported.

    Order follows `offered` so the caller's preference is preserved.
    """
    supported = supported_patterns(benchmark)
    if supported is None:
        return list(offered)
    allowed = set(supported)
    return [p for p in offered if p in allowed]


def deferred_patterns(benchmark: str) -> Dict[str, str]:
    entry = benchmark_policy(benchmark)
    if entry is None:
        return {}
    return dict(entry.get("deferred_policy_patterns") or {})


def pattern_status(benchmark: str, pattern: str) -> Tuple[str, str]:
    """('supported'|'unsupported'|'deferred_policy'|'unknown_benchmark', reason)."""
    entry = benchmark_policy(benchmark)
    if entry is None:
        return "unknown_benchmark", ""
    if pattern in (entry.get("supported_patterns") or []):
        return "supported", ""
    deferred = entry.get("deferred_policy_patterns") or {}
    if pattern in deferred:
        return "deferred_policy", deferred[pattern]
    unsupported = entry.get("unsupported_patterns") or {}
    if pattern in unsupported:
        return "unsupported", unsupported[pattern]
    return "unsupported", REASON_UNSUPPORTED


def pattern_rejection(benchmark: str, pattern: str) -> Optional[str]:
    """None when the pattern may be used, else a stable rejection reason."""
    status, why = pattern_status(benchmark, pattern)
    if status in ("supported", "unknown_benchmark"):
        return None
    if status == "deferred_policy":
        return "%s: %s is deferred for %s (%s) — the resolving policy is still open" % (
            REASON_DEFERRED, pattern, benchmark, why)
    if why == REASON_NO_EFFECT:
        return "%s: %s has no fill hook for %s, so the pattern cannot change the input" % (
            REASON_NO_EFFECT, pattern, benchmark)
    if why == REASON_UNSAFE:
        return "%s: %s would execute undefined behaviour in the frozen oracle of %s" % (
            REASON_UNSAFE, pattern, benchmark)
    return "%s: %s is not supported for %s (%s)" % (
        REASON_UNSUPPORTED, pattern, benchmark, why or "no reason recorded")


def _is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def size_rejection(benchmark: str, size: int) -> Optional[str]:
    """None when the size is technically safe for this benchmark, else a reason.

    Only benchmark-specific, technically unambiguous constraints are enforced.
    """
    entry = benchmark_policy(benchmark)
    if entry is None:
        return None
    constraint = entry.get("size_constraint")
    if not constraint:
        return None

    min_size = constraint.get("min_size")
    if min_size is not None and size < int(min_size):
        return "%s: size %s is below the safe minimum %s for %s (%s)" % (
            REASON_INVALID_SIZE, size, min_size, benchmark, constraint.get("reason", ""))

    predicate = constraint.get("size_predicate")
    if predicate == "power_of_two_or_below_two":
        if size > 1 and not _is_power_of_two(size):
            return "%s: size %s is neither <= 1 nor a power of two, which %s requires (%s)" % (
                REASON_INVALID_SIZE, size, benchmark, constraint.get("reason", ""))
    elif predicate:
        return "%s: unknown size predicate %r for %s" % (
            REASON_INVALID_SIZE, predicate, benchmark)

    return None


def explicit_values_rejection(benchmark: str, values) -> Optional[str]:
    """None when every explicit value is representable in the benchmark's fill
    container, else a reason.

    Values outside the container's element type would be converted out of range,
    which is undefined behaviour. E2-A REJECTS such a spec rather than clipping
    it: clipping would decide VALUE_RANGE_DOMAIN_POLICY, which stays open.
    """
    entry = benchmark_policy(benchmark)
    if entry is None:
        return None
    bounds = entry.get("explicit_values_bounds")
    if not bounds or not values:
        return None
    lo = float(bounds["min"])
    hi = float(bounds["max"])
    for value in values:
        number = float(value)
        if number < lo or number > hi:
            return ("%s: explicit value %r is outside the representable range "
                    "[%g, %g] of %s's fill container (%s)"
                    % (REASON_VALUE_NOT_REPRESENTABLE, value, lo, hi, benchmark,
                       bounds.get("reason", "")))
    return None


def spec_rejection(benchmark: str, size: int, pattern: str) -> Optional[str]:
    """Combined capability check used by validate_spec."""
    reason = size_rejection(benchmark, size)
    if reason is not None:
        return reason
    return pattern_rejection(benchmark, pattern)


def policy_summary() -> Dict[str, Any]:
    """Counts for reports and the consistency checker."""
    policy = load_policy().get("benchmarks") or {}
    supported = unsupported = deferred = 0
    reasons = {}  # type: Dict[str, int]
    constrained = []
    for name, entry in policy.items():
        supported += len(entry.get("supported_patterns") or [])
        for _p, why in (entry.get("unsupported_patterns") or {}).items():
            unsupported += 1
            reasons[why] = reasons.get(why, 0) + 1
        for _p, why in (entry.get("deferred_policy_patterns") or {}).items():
            deferred += 1
            reasons[why] = reasons.get(why, 0) + 1
        if entry.get("size_constraint"):
            constrained.append(name)
    return {
        "benchmarks": len(policy),
        "supported_pattern_cases": supported,
        "unsupported_pattern_cases": unsupported,
        "deferred_policy_pattern_cases": deferred,
        "reason_distribution": reasons,
        "size_constrained_benchmarks": sorted(constrained),
    }
