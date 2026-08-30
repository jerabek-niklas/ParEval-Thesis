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

E2-A.1 added three things:

  FAIL-CLOSED POLICY LOADING
      A missing, unreadable, non-ENFORCED, structurally broken or
      benchmark-incomplete policy is a FATAL configuration error
      (EnhancedPolicyError), never a silently empty policy that enforces
      nothing. A benchmark the policy does not know is likewise fatal, not
      "unrestricted".

  CANONICAL PATTERN-PARAMETER RELEVANCE
      `PATTERN_PARAM_RELEVANCE` states, once, which of value_range / k / values
      each pattern actually READS in drivers/cpp/enhanced-fill.hpp. Validation,
      generation and mutation all use this one table, so an inert parameter can
      no longer produce a second spec identity for an identical input
      (parameter-level fake diversity). Irrelevant parameters are REJECTED, not
      normalized away: normalizing would silently equate two stored specs and
      reinterpret historical spec_keys.

  TECHNICAL RANGE SAFETY
      A value_range is accepted only if both endpoints are finite, both are
      representable in EVERY fill container the pattern reaches, and the span
      the current fill arithmetic computes from them stays representable
      (integral: no signed overflow in hi-lo or span+1; floating: hi-lo stays
      finite). This is a REPRESENTABILITY guard, not VALUE_RANGE_DOMAIN_POLICY:
      it answers "can the harness hold this value and compute with it", never
      "is this value meaningful for the benchmark". Out-of-range specs are
      rejected, never clipped, saturated or wrapped.

E2-B froze the remaining methodological policies and added a second, strictly
separate question on top of E2-A.1's technical one:

  DECLARED FILL DOMAIN
      E2-A.1 asks "can the container hold this value and can the arithmetic
      compute with it" (`fill_type_capability`). E2-B asks "is this a
      legitimate input for THIS benchmark" (`fill_domain_capability`), answered
      from the domain each fill site declares at its call site - narrowed only
      where the frozen prompt states a narrower state space. A value_range and
      every explicit value must be a SUBSET of that domain. Where the sites of
      one benchmark declare DIFFERENT domains (sort/43: startTime / duration /
      value) a single global value_range has no unambiguous meaning and is
      refused outright rather than reconciled by an invented common domain.
      Both questions must be answered yes; neither replaces the other, and
      neither clips, saturates or wraps anything.

  DOMAIN-BOUNDED EXTREMES
      `extreme_values` and `spike_at` no longer use numeric_limits. The harness
      alternates between the EFFECTIVE endpoints and spikes at the effective
      `hi`. A consequence is that `extreme_values` became byte-identical to
      `alternating`, so the derivation marks it unsupported everywhere - two
      labels for one input is the fake-diversity defect, not a capability.

  DEGENERATE RANGES
      With `lo == hi` every range-reading pattern produces the same constant
      array, and the structural perturbations of duplicate_at /
      sorted_except_one / spike_at are provably no-ops. Only `all_same`, whose
      name describes that input honestly, may carry a degenerate range.

Python 3.8 compatible.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

POLICY_PATH = Path(__file__).resolve().parent / "enhanced_policy.json"

REQUIRED_POLICY_STATUS = "ENFORCED"


class EnhancedPolicyError(RuntimeError):
    """The enforced capability policy is missing, malformed or incomplete.

    Fail-closed by design: every productive path (validation, generation,
    mutation, the runner) must abort rather than fall back to enforcing
    nothing.
    """


# ---------------------------------------------------------------------------
# Canonical pattern-parameter relevance (E2-A.1)
#
# THE one definition of which fill parameters a pattern actually reads. Every
# entry names the code in drivers/cpp/enhanced-fill.hpp that reads (or ignores)
# the parameter, so this table is checkable against the harness rather than
# asserted.
# ---------------------------------------------------------------------------

PARAM_VALUE_RANGE = "value_range"
PARAM_K = "k"
PARAM_VALUES = "values"

FILL_PARAMS = (PARAM_VALUE_RANGE, PARAM_K, PARAM_VALUES)

# pattern -> {parameter: (used, evidence)}
PATTERN_PARAM_RELEVANCE = OrderedDict([
    ("random", OrderedDict([
        (PARAM_VALUE_RANGE, (True, "enhancedFillRandom -> fillRand(x, lo, hi)")),
        (PARAM_K, (False, "case 0 never reads param_k")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("all_zeros", OrderedDict([
        (PARAM_VALUE_RANGE, (False, "case 1 assigns DType(0); lo/hi are never read")),
        (PARAM_K, (False, "case 1 never reads param_k")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("all_same", OrderedDict([
        (PARAM_VALUE_RANGE, (True, "case 2 -> enhancedMidValue(lo, hi)")),
        (PARAM_K, (False, "case 2 never reads param_k")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("ascending", OrderedDict([
        (PARAM_VALUE_RANGE, (True, "case 3 -> enhancedRampValue(lo, hi, ...)")),
        (PARAM_K, (False, "case 3 never reads param_k")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("descending", OrderedDict([
        (PARAM_VALUE_RANGE, (True, "case 4 -> enhancedRampValue(lo, hi, ...)")),
        (PARAM_K, (False, "case 4 never reads param_k")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("alternating", OrderedDict([
        (PARAM_VALUE_RANGE, (True, "case 5 assigns lo / hi alternately")),
        (PARAM_K, (False, "case 5 never reads param_k")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("extreme_values", OrderedDict([
        (PARAM_VALUE_RANGE, (True, "case 6 -> enhancedExtremeValue<DType>(lo, hi, i): "
                                   "E2-B alternates the effective domain "
                                   "endpoints (before E2-B: numeric_limits, "
                                   "which read neither)")),
        (PARAM_K, (False, "case 6 never reads param_k")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("duplicate_at", OrderedDict([
        (PARAM_VALUE_RANGE, (True, "case 7 fills randomly in [lo, hi] first")),
        (PARAM_K, (True, "case 7 writes x[k] = x[(k+1) % n]")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("sorted_except_one", OrderedDict([
        (PARAM_VALUE_RANGE, (True, "case 8 builds the ascending ramp from lo/hi")),
        (PARAM_K, (True, "case 8 swaps x[k] with x[(k+1) % n]")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("spike_at", OrderedDict([
        (PARAM_VALUE_RANGE, (True, "case 9 fills randomly in [lo, hi] first")),
        (PARAM_K, (True, "case 9 writes the spike at x[k]")),
        (PARAM_VALUES, (False, "values are only read by pattern id 10")),
    ])),
    ("explicit_values", OrderedDict([
        (PARAM_VALUE_RANGE, (False, "case 10 fills cyclically from the value "
                                    "list; lo/hi are never read")),
        (PARAM_K, (False, "case 10 never reads param_k")),
        (PARAM_VALUES, (True, "case 10 reads ENHANCED_EXPLICIT_VALUES / the "
                              "runtime values file")),
    ])),
])

ALL_PATTERNS = tuple(PATTERN_PARAM_RELEVANCE.keys())

K_PATTERNS = tuple(
    p for p in ALL_PATTERNS if PATTERN_PARAM_RELEVANCE[p][PARAM_K][0])
RANGE_PATTERNS = tuple(
    p for p in ALL_PATTERNS if PATTERN_PARAM_RELEVANCE[p][PARAM_VALUE_RANGE][0])
VALUES_PATTERNS = tuple(
    p for p in ALL_PATTERNS if PATTERN_PARAM_RELEVANCE[p][PARAM_VALUES][0])

# the only pattern_params keys the harness implements
KNOWN_PATTERN_PARAM_KEYS = (PARAM_VALUE_RANGE, PARAM_K)


def pattern_uses(pattern: str, param: str) -> bool:
    entry = PATTERN_PARAM_RELEVANCE.get(pattern)
    if entry is None:
        raise EnhancedPolicyError("unknown pattern %r" % (pattern,))
    if param not in entry:
        raise EnhancedPolicyError("unknown fill parameter %r" % (param,))
    return entry[param][0]


def pattern_param_evidence(pattern: str, param: str) -> str:
    return PATTERN_PARAM_RELEVANCE[pattern][param][1]


# rejection reasons (stable internal vocabulary; not part of any record schema)
REASON_UNSUPPORTED = "unsupported_pattern_for_benchmark"
REASON_NO_EFFECT = "no_pattern_effect"
REASON_UNSAFE = "unsafe_pattern_for_benchmark"
REASON_DEFERRED = "deferred_policy_pattern"
REASON_INVALID_SIZE = "invalid_size_for_benchmark"
REASON_VALUE_NOT_REPRESENTABLE = "value_not_representable_for_benchmark"
# E2-A.1
REASON_IRRELEVANT_PARAM = "irrelevant_pattern_parameter"
REASON_INERT_PARAM = "inert_parameter_for_benchmark"
REASON_UNKNOWN_PARAM = "unknown_pattern_parameter"
REASON_NON_FINITE_RANGE = "non_finite_value_range"
REASON_NON_FINITE_VALUE = "non_finite_explicit_value"
REASON_RANGE_NOT_REPRESENTABLE = "range_not_representable_for_benchmark"
REASON_UNSAFE_SPAN = "unsafe_value_range_span"
# E2-B
REASON_RANGE_OUTSIDE_DOMAIN = "value_range_outside_declared_domain"
REASON_RANGE_UNSUPPORTED = "value_range_not_supported_for_benchmark"
REASON_VALUE_OUTSIDE_DOMAIN = "explicit_value_outside_declared_domain"
REASON_DEGENERATE_RANGE = "degenerate_range_not_canonical"

# the one pattern whose name honestly describes a constant array
CANONICAL_DEGENERATE_PATTERN = "all_same"

_POLICY_CACHE = None  # type: Optional[Dict[str, Any]]
_POLICY_BYTES = None  # type: Optional[bytes]


# ---------------------------------------------------------------------------
# Fail-closed policy loading
# ---------------------------------------------------------------------------

def _validate_policy_document(policy: Any, path: Path) -> None:
    """Structural gate. Anything unexpected is fatal — never repaired."""
    if not isinstance(policy, dict):
        raise EnhancedPolicyError(
            "%s: the enforced capability policy must be a JSON object" % path)

    status = policy.get("status")
    if status != REQUIRED_POLICY_STATUS:
        raise EnhancedPolicyError(
            "%s: policy status is %r, expected %r — an unenforced policy must "
            "never be used to enforce anything" % (path, status, REQUIRED_POLICY_STATUS))

    benchmarks = policy.get("benchmarks")
    if not isinstance(benchmarks, dict) or not benchmarks:
        raise EnhancedPolicyError(
            "%s: policy has no benchmarks section" % path)

    expected_patterns = set(ALL_PATTERNS)
    for name, entry in benchmarks.items():
        if not isinstance(entry, dict):
            raise EnhancedPolicyError("%s: %s: entry is not an object" % (path, name))

        supported = entry.get("supported_patterns")
        unsupported = entry.get("unsupported_patterns")
        deferred = entry.get("deferred_policy_patterns")
        if (not isinstance(supported, list) or not isinstance(unsupported, dict)
                or not isinstance(deferred, dict)):
            raise EnhancedPolicyError(
                "%s: %s: supported_patterns must be a list and "
                "unsupported_patterns / deferred_policy_patterns objects"
                % (path, name))

        sup, uns, dfr = set(supported), set(unsupported), set(deferred)
        unknown = (sup | uns | dfr) - expected_patterns
        if unknown:
            raise EnhancedPolicyError(
                "%s: %s: unknown pattern(s) %s" % (path, name, sorted(unknown)))
        if sup & uns or sup & dfr or uns & dfr:
            raise EnhancedPolicyError(
                "%s: %s: the pattern partition overlaps" % (path, name))
        if sup | uns | dfr != expected_patterns:
            raise EnhancedPolicyError(
                "%s: %s: the pattern partition does not cover all %d patterns "
                "(missing %s)" % (path, name, len(expected_patterns),
                                  sorted(expected_patterns - (sup | uns | dfr))))

        domain = entry.get("fill_domain_capability")
        if not isinstance(domain, dict):
            raise EnhancedPolicyError(
                "%s: %s: fill_domain_capability is missing" % (path, name))
        if domain.get("global_value_range_supported"):
            for field in ("domain_lo", "domain_hi"):
                value = domain.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise EnhancedPolicyError(
                        "%s: %s: fill_domain_capability.%s must be a number"
                        % (path, name, field))
            if float(domain["domain_lo"]) > float(domain["domain_hi"]):
                raise EnhancedPolicyError(
                    "%s: %s: declared domain is inverted" % (path, name))

        size_zero = entry.get("size_zero_policy")
        if not isinstance(size_zero, dict) or size_zero.get("policy") not in (
                "ALLOWED", "DISALLOWED", "NOT_APPLICABLE"):
            raise EnhancedPolicyError(
                "%s: %s: size_zero_policy is missing or not one of "
                "ALLOWED/DISALLOWED/NOT_APPLICABLE" % (path, name))

        capability = entry.get("fill_type_capability")
        if not isinstance(capability, dict):
            raise EnhancedPolicyError(
                "%s: %s: fill_type_capability is missing" % (path, name))
        if not isinstance(capability.get("element_types"), list):
            raise EnhancedPolicyError(
                "%s: %s: fill_type_capability.element_types is missing" % (path, name))
        if capability.get("has_fill_hook"):
            for field in ("value_min", "value_max", "max_finite_span"):
                value = capability.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise EnhancedPolicyError(
                        "%s: %s: fill_type_capability.%s must be a number"
                        % (path, name, field))
                if not math.isfinite(float(value)):
                    raise EnhancedPolicyError(
                        "%s: %s: fill_type_capability.%s is not finite"
                        % (path, name, field))

        constraint = entry.get("size_constraint")
        if constraint is not None:
            if not isinstance(constraint, dict):
                raise EnhancedPolicyError(
                    "%s: %s: size_constraint must be an object" % (path, name))
            min_size = constraint.get("min_size")
            if min_size is not None and (
                    not isinstance(min_size, int) or isinstance(min_size, bool)
                    or min_size < 0):
                raise EnhancedPolicyError(
                    "%s: %s: size_constraint.min_size must be a non-negative int"
                    % (path, name))
            predicate = constraint.get("size_predicate")
            if predicate is not None and predicate not in KNOWN_SIZE_PREDICATES:
                raise EnhancedPolicyError(
                    "%s: %s: unknown size_predicate %r (known: %s)"
                    % (path, name, predicate, ", ".join(KNOWN_SIZE_PREDICATES)))
            if min_size is None and predicate is None:
                raise EnhancedPolicyError(
                    "%s: %s: size_constraint carries neither min_size nor "
                    "size_predicate" % (path, name))


KNOWN_SIZE_PREDICATES = ("power_of_two_or_below_two",)


def load_policy() -> Dict[str, Any]:
    """The enforced policy. FAIL-CLOSED: raises EnhancedPolicyError when the
    artifact is missing, unreadable, not ENFORCED or structurally broken.

    Before E2-A.1 a missing file silently produced an empty policy, which
    disabled every capability check without a single diagnostic.
    """
    global _POLICY_CACHE, _POLICY_BYTES
    if _POLICY_CACHE is None:
        if not POLICY_PATH.is_file():
            raise EnhancedPolicyError(
                "the enforced capability policy %s does not exist. Derive it "
                "with `python thesis/enhanced_tests/derive_enhanced_policy.py`. "
                "Running without it is refused: it would silently disable "
                "pattern, size, parameter and range enforcement."
                % POLICY_PATH)
        raw = POLICY_PATH.read_bytes()
        try:
            policy = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise EnhancedPolicyError(
                "%s is not valid JSON: %s" % (POLICY_PATH, error))
        _validate_policy_document(policy, POLICY_PATH)
        _POLICY_CACHE = policy
        _POLICY_BYTES = raw
    return _POLICY_CACHE


def reset_policy_cache() -> None:
    """Drop the cached policy (tests that point POLICY_PATH elsewhere)."""
    global _POLICY_CACHE, _POLICY_BYTES
    _POLICY_CACHE = None
    _POLICY_BYTES = None


def policy_benchmarks() -> List[str]:
    return sorted((load_policy().get("benchmarks") or {}).keys())


def benchmark_policy(benchmark: str) -> Dict[str, Any]:
    """The benchmark's policy entry. FAIL-CLOSED: an unknown benchmark is a
    fatal configuration error, not an unrestricted benchmark."""
    entry = (load_policy().get("benchmarks") or {}).get(benchmark)
    if entry is None:
        raise EnhancedPolicyError(
            "benchmark %r is not covered by the enforced capability policy "
            "(%s). A benchmark the policy does not know is refused rather than "
            "treated as unrestricted; re-derive the policy from the audit "
            "catalog." % (benchmark, POLICY_PATH))
    return entry


def has_policy(benchmark: str) -> bool:
    return (load_policy().get("benchmarks") or {}).get(benchmark) is not None


def supported_patterns(benchmark: str) -> List[str]:
    return list(benchmark_policy(benchmark).get("supported_patterns") or [])


def effective_patterns(benchmark: str, offered: List[str]) -> List[str]:
    """effective = globally offered INTERSECT benchmark-supported.

    Order follows `offered` so the caller's preference is preserved.
    """
    allowed = set(supported_patterns(benchmark))
    return [p for p in offered if p in allowed]


def deferred_patterns(benchmark: str) -> Dict[str, str]:
    return dict(benchmark_policy(benchmark).get("deferred_policy_patterns") or {})


def has_fill_hook(benchmark: str) -> bool:
    capability = benchmark_policy(benchmark).get("fill_type_capability") or {}
    return bool(capability.get("has_fill_hook"))


def fill_type_capability(benchmark: str) -> Dict[str, Any]:
    return dict(benchmark_policy(benchmark).get("fill_type_capability") or {})


def fill_domain_capability(benchmark: str) -> Dict[str, Any]:
    """E2-B: the benchmark's DECLARED legitimate fill domain (semantic), as
    opposed to fill_type_capability (technical representability)."""
    return dict(benchmark_policy(benchmark).get("fill_domain_capability") or {})


def global_value_range_supported(benchmark: str) -> bool:
    return bool(fill_domain_capability(benchmark).get("global_value_range_supported"))


def declared_domain(benchmark: str):
    """(lo, hi) of the benchmark's global declared domain, or None when it has
    no fill hook or its sites declare different domains."""
    capability = fill_domain_capability(benchmark)
    if not capability.get("global_value_range_supported"):
        return None
    return float(capability["domain_lo"]), float(capability["domain_hi"])


def size_zero_policy(benchmark: str) -> Dict[str, Any]:
    return dict(benchmark_policy(benchmark).get("size_zero_policy") or {})


def adapter_policy(benchmark: str) -> Optional[Dict[str, Any]]:
    entry = benchmark_policy(benchmark).get("adapter_policy")
    return dict(entry) if entry else None


def pattern_status(benchmark: str, pattern: str) -> Tuple[str, str]:
    """('supported'|'unsupported'|'deferred_policy', reason)."""
    entry = benchmark_policy(benchmark)
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
    if status == "supported":
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
    constraint = benchmark_policy(benchmark).get("size_constraint")
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


# ---------------------------------------------------------------------------
# E2-A.1: parameter relevance
# ---------------------------------------------------------------------------

def parameter_rejection(
    benchmark: str,
    pattern: str,
    pattern_params: Optional[Dict[str, Any]],
    has_values: bool,
) -> Optional[str]:
    """None when every supplied fill parameter is actually read for this
    (benchmark, pattern), else a stable rejection reason.

    Two distinct defects are separated:

      unknown_pattern_parameter    a key the harness does not implement at all
                                   (it would be silently ignored)
      irrelevant_pattern_parameter the key exists but THIS pattern never reads
                                   it, so it can only create a second spec
                                   identity for an identical input
      inert_parameter_for_benchmark the benchmark has no reachable fill hook at
                                   all, so every fill parameter is inert

    Rejected, never normalized away: silently dropping the parameter would
    equate two DIFFERENT stored specs and reinterpret historical spec_keys.
    """
    params = pattern_params or {}

    unknown = [k for k in params if k not in KNOWN_PATTERN_PARAM_KEYS]
    if unknown:
        return ("%s: pattern_params key(s) %s are not implemented by the fill "
                "harness (known: %s); a silently ignored parameter would only "
                "create a second spec identity for an identical input"
                % (REASON_UNKNOWN_PARAM, sorted(unknown),
                   ", ".join(KNOWN_PATTERN_PARAM_KEYS)))

    supplied = []
    if params.get(PARAM_VALUE_RANGE) is not None:
        supplied.append(PARAM_VALUE_RANGE)
    if params.get(PARAM_K) is not None:
        supplied.append(PARAM_K)
    if has_values:
        supplied.append(PARAM_VALUES)

    if not supplied:
        return None

    if not has_fill_hook(benchmark):
        return ("%s: %s has no reachable ENHANCED_FILL hook, so %s cannot "
                "change the input; a spec carrying it would differ from the "
                "canonical one only in its key, not in what is executed"
                % (REASON_INERT_PARAM, benchmark, "/".join(supplied)))

    for param in supplied:
        if not pattern_uses(pattern, param):
            return ("%s: pattern %r never reads %s (%s), so it cannot change "
                    "the input; the spec is rejected instead of normalized so "
                    "no two stored specs are silently equated"
                    % (REASON_IRRELEVANT_PARAM, pattern, param,
                       pattern_param_evidence(pattern, param)))

    return None


# ---------------------------------------------------------------------------
# E2-A.1: technical value/range safety
# ---------------------------------------------------------------------------

def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def non_finite_range_reason(value_range: Any) -> Optional[str]:
    """THE finiteness rule for a value_range, stated once.

    validate_spec calls this before its lo <= hi ordering check so a NaN
    endpoint never falls out of a comparison with a misleading message, and
    value_range_rejection calls it as its own first step.
    """
    if value_range is None:
        return None
    if not _finite(value_range[0]) or not _finite(value_range[1]):
        return ("%s: value_range %r contains NaN or +/-Inf; a non-finite fill "
                "bound is rejected at validation time rather than turned into "
                "a deterministic non-finite input at run time"
                % (REASON_NON_FINITE_RANGE, list(value_range)))
    return None


def value_range_rejection(
    benchmark: str, pattern: str, value_range: Any
) -> Optional[str]:
    """None when this value_range is TECHNICALLY safe for the benchmark's fill
    containers, else a stable rejection reason.

    Three independent technical questions, in order:

      1. are both endpoints finite numbers?            non_finite_value_range
      2. is each endpoint representable in EVERY fill
         container the pattern reaches?                range_not_representable_*
      3. can the current fill arithmetic compute the
         span in those containers?                     unsafe_value_range_span

    (3) is deliberately a single conservative rule for every range-using
    pattern rather than a per-pattern sub-policy. `alternating` would
    technically survive a wider range than `ascending`, but a per-pattern
    exception buys nothing here (no existing spec needs it) and would be a new
    partial policy — the contrary of what this wave is for. Nothing about the
    benchmark's admissible DOMAIN is decided: the guard only asks whether the
    container can hold the value and the arithmetic can compute with it.
    """
    if value_range is None:
        return None

    reason = non_finite_range_reason(value_range)
    if reason is not None:
        return reason

    if not has_fill_hook(benchmark):
        # already reported as an inert parameter; nothing to check technically
        return None

    lo = float(value_range[0])
    hi = float(value_range[1])

    capability = fill_type_capability(benchmark)
    value_min = float(capability["value_min"])
    value_max = float(capability["value_max"])
    max_span = float(capability["max_finite_span"])
    types = ", ".join(capability.get("element_types") or [])

    for name, endpoint in (("lo", lo), ("hi", hi)):
        if endpoint < value_min or endpoint > value_max:
            return ("%s: value_range %s=%r is outside the representable range "
                    "[%g, %g] of %s's fill container element type(s) %s; the "
                    "spec is rejected, not clipped (clipping would decide "
                    "VALUE_RANGE_DOMAIN_POLICY, which is open)"
                    % (REASON_RANGE_NOT_REPRESENTABLE, name, endpoint,
                       value_min, value_max, benchmark, types))

    if not pattern_uses(pattern, PARAM_VALUE_RANGE):
        # inert for this pattern; parameter_rejection reports that separately
        return None

    span = hi - lo
    if not math.isfinite(span) or span > max_span:
        return ("%s: value_range [%r, %r] has span %r, which the fill "
                "arithmetic cannot compute in %s's element type(s) %s "
                "(largest safe span %g). Integral spans must leave hi-lo and "
                "span+1 representable; floating spans must stay finite."
                % (REASON_UNSAFE_SPAN, lo, hi, span, benchmark, types, max_span))

    return None


def value_range_domain_rejection(
    benchmark: str, pattern: str, value_range: Any
) -> Optional[str]:
    """E2-B: is this range a LEGITIMATE input for this benchmark?

    Strictly separate from value_range_rejection, which asks only whether the
    harness can represent and compute with it. A range is admissible iff the
    benchmark has one unambiguous declared domain and the range is a subset of
    it. Out-of-domain ranges are REJECTED, never clipped, saturated or wrapped.
    """
    if value_range is None:
        return None
    if not pattern_uses(pattern, PARAM_VALUE_RANGE):
        return None  # inert here; parameter_rejection reports that separately
    if not has_fill_hook(benchmark):
        return None  # inert here; parameter_rejection reports that separately

    capability = fill_domain_capability(benchmark)
    if not capability.get("global_value_range_supported"):
        roles = "; ".join(
            "%s [%g, %g]" % (d.get("semantic_role"), d.get("lo"), d.get("hi"))
            for d in capability.get("site_domains") or [])
        return ("%s: %s fills several inputs with DIFFERENT declared domains "
                "(%s), so one global value_range has no unambiguous meaning. "
                "E2-B refuses to invent a common domain; pattern and size "
                "variation stay available."
                % (REASON_RANGE_UNSUPPORTED, benchmark, roles))

    lo = float(value_range[0])
    hi = float(value_range[1])
    domain_lo = float(capability["domain_lo"])
    domain_hi = float(capability["domain_hi"])
    if lo < domain_lo or hi > domain_hi:
        return ("%s: value_range [%g, %g] is not a subset of %s's declared fill "
                "domain [%g, %g]; the spec is rejected, not clipped"
                % (REASON_RANGE_OUTSIDE_DOMAIN, lo, hi, benchmark,
                   domain_lo, domain_hi))

    if lo == hi and pattern != CANONICAL_DEGENERATE_PATTERN:
        return ("%s: a degenerate value_range [%g, %g] makes every "
                "range-reading pattern produce the SAME constant array, and the "
                "structural perturbation of %s is provably a no-op on it. Only "
                "%r may carry a degenerate range, so the label describes the "
                "input honestly."
                % (REASON_DEGENERATE_RANGE, lo, hi, pattern,
                   CANONICAL_DEGENERATE_PATTERN))
    return None


def explicit_values_domain_rejection(benchmark: str, values) -> Optional[str]:
    """E2-B: every explicit value must lie in the declared fill domain.

    An explicit value is a direct input, so it is exactly as domain-bound as a
    value_range endpoint. For a benchmark whose sites declare different domains
    the intersection would be an invented common domain, so the shape gate
    (`no_single_canonical_fill_site`) already keeps explicit_values out there.
    """
    if not values or not has_fill_hook(benchmark):
        return None
    capability = fill_domain_capability(benchmark)
    if not capability.get("global_value_range_supported"):
        return None
    domain_lo = float(capability["domain_lo"])
    domain_hi = float(capability["domain_hi"])
    for value in values:
        number = float(value)
        if number < domain_lo or number > domain_hi:
            return ("%s: explicit value %r is outside %s's declared fill domain "
                    "[%g, %g]; the spec is rejected, not clipped"
                    % (REASON_VALUE_OUTSIDE_DOMAIN, value, benchmark,
                       domain_lo, domain_hi))
    return None


def explicit_values_rejection(benchmark: str, values) -> Optional[str]:
    """None when every explicit value is finite and representable in the
    benchmark's fill container, else a reason.

    Values outside the container's element type would be converted out of
    range, which is undefined behaviour. Non-finite values would become a
    deterministic Inf/NaN input. E2-A/E2-A.1 REJECT such a spec rather than
    clipping it: clipping would decide VALUE_RANGE_DOMAIN_POLICY, which stays
    open, and a non-finite input has no place in a regular enhanced spec.
    """
    if not values:
        return None

    for value in values:
        if not _finite(value):
            return ("%s: explicit value %r is NaN or +/-Inf; non-finite values "
                    "are rejected for every element type (int, float and "
                    "double alike) instead of becoming a deterministic "
                    "non-finite input" % (REASON_NON_FINITE_VALUE, value))

    capability = fill_type_capability(benchmark)
    if not capability.get("has_fill_hook"):
        return None

    lo = float(capability["value_min"])
    hi = float(capability["value_max"])
    for value in values:
        number = float(value)
        if number < lo or number > hi:
            return ("%s: explicit value %r is outside the representable range "
                    "[%g, %g] of %s's fill container (%s)"
                    % (REASON_VALUE_NOT_REPRESENTABLE, value, lo, hi, benchmark,
                       ", ".join(capability.get("element_types") or [])))
    return None


def spec_rejection(benchmark: str, size: int, pattern: str) -> Optional[str]:
    """Combined benchmark/size/pattern check used by validate_spec and by the
    mutation path (which has no parameters yet at that point)."""
    reason = size_rejection(benchmark, size)
    if reason is not None:
        return reason
    return pattern_rejection(benchmark, pattern)


def full_spec_rejection(spec: Dict[str, Any]) -> Optional[str]:
    """Every capability rule this module owns, applied to a whole spec."""
    benchmark = spec.get("benchmark")
    pattern = spec.get("pattern")
    params = spec.get("pattern_params") or {}
    values = spec.get("values") or []

    reason = spec_rejection(benchmark, spec.get("size"), pattern)
    if reason is not None:
        return reason
    reason = parameter_rejection(benchmark, pattern, params, bool(values))
    if reason is not None:
        return reason
    reason = value_range_rejection(benchmark, pattern, params.get(PARAM_VALUE_RANGE))
    if reason is not None:
        return reason
    reason = value_range_domain_rejection(
        benchmark, pattern, params.get(PARAM_VALUE_RANGE))
    if reason is not None:
        return reason
    reason = explicit_values_rejection(benchmark, values)
    if reason is not None:
        return reason
    return explicit_values_domain_rejection(benchmark, values)


# ---------------------------------------------------------------------------
# Provenance and preflight
# ---------------------------------------------------------------------------

def policy_provenance() -> Dict[str, Any]:
    """What a productive enhanced run must record about the policy it enforced.

    The hash is over the policy FILE CONTENT (and the audit catalog's content),
    never over mtime, file name or the git commit.
    """
    policy = load_policy()
    from thesis.enhanced_tests import derive_enhanced_policy as derivation

    catalog_bytes = derivation.CATALOG.read_bytes() if derivation.CATALOG.is_file() else b""
    return OrderedDict([
        ("enhanced_policy_path", str(POLICY_PATH)),
        ("enhanced_policy_sha256", hashlib.sha256(_POLICY_BYTES or b"").hexdigest()),
        ("enhanced_policy_status", policy.get("status")),
        ("enhanced_policy_benchmark_count", len(policy.get("benchmarks") or {})),
        ("derived_from", (policy.get("_meta") or {}).get("derived_from")),
        ("derived_from_sha256", hashlib.sha256(catalog_bytes).hexdigest()),
        ("derivation_version", (policy.get("_meta") or {}).get("derivation_version")),
        ("derivation_module_version", derivation.DERIVATION_VERSION),
    ])


def policy_preflight(expected_benchmarks=None) -> Dict[str, Any]:
    """MANDATORY before any productive enhanced side effect.

    Raises EnhancedPolicyError when the policy is missing, malformed, not
    ENFORCED, incomplete for the benchmarks the run will touch, or no longer
    exactly what the current audit catalog derives. Returns the provenance
    record on success.

    Callers must invoke this BEFORE writing a manifest, truncating or deleting
    an output file, persisting a cache or calling a model API — a stale policy
    must never cost a partially written run.
    """
    load_policy()  # structural + status gate, fail-closed

    from thesis.enhanced_tests import derive_enhanced_policy as derivation

    matches, differing = derivation.policy_matches_derivation()
    if not matches:
        raise EnhancedPolicyError(
            "%s is STALE: it is not what the current audit catalog (%s) "
            "derives. Differing entries: %s. Re-derive with `python "
            "thesis/enhanced_tests/derive_enhanced_policy.py` and re-review "
            "before running anything."
            % (POLICY_PATH, derivation.CATALOG, ", ".join(differing[:8])
               + (" ..." if len(differing) > 8 else "")))

    if expected_benchmarks is not None:
        known = set(policy_benchmarks())
        missing = sorted(set(expected_benchmarks) - known)
        if missing:
            raise EnhancedPolicyError(
                "the enforced capability policy does not cover %d benchmark(s) "
                "this run needs: %s. A benchmark without a policy entry is "
                "refused, never treated as unrestricted."
                % (len(missing), ", ".join(missing[:8])
                   + (" ..." if len(missing) > 8 else "")))

    return policy_provenance()


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
        "benchmarks_with_fill_hook": sum(
            1 for e in policy.values()
            if (e.get("fill_type_capability") or {}).get("has_fill_hook")),
        "range_enabled_benchmarks": sorted(
            n for n, e in policy.items()
            if (e.get("fill_domain_capability") or {}).get(
                "global_value_range_supported")),
        "range_disabled_benchmarks": sorted(
            n for n, e in policy.items()
            if (e.get("fill_domain_capability") or {}).get("has_fill_hook")
            and not (e.get("fill_domain_capability") or {}).get(
                "global_value_range_supported")),
        "size_zero_allowed": sorted(
            n for n, e in policy.items()
            if (e.get("size_zero_policy") or {}).get("policy") == "ALLOWED"),
        "size_zero_disallowed": sorted(
            n for n, e in policy.items()
            if (e.get("size_zero_policy") or {}).get("policy") == "DISALLOWED"),
        "size_zero_not_applicable": sorted(
            n for n, e in policy.items()
            if (e.get("size_zero_policy") or {}).get("policy") == "NOT_APPLICABLE"),
        "adapter_disabled_benchmarks": sorted(
            n for n, e in policy.items() if e.get("adapter_policy")),
    }
