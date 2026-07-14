"""Input-spec format for the enhanced-tests stage: test cases are DATA.

A spec describes one validation input configuration:

    {
      "benchmark": "dense_la/00_dense_la_lu_decomp",
      "size": 7,
      "pattern": "ascending",
      "pattern_params": {"value_range": [-1.0, 1.0]},   # optional
      "source": "static" | "llm" | "mutation",
      "rationale": "why this input is interesting"
    }

The pattern names map to the ids in drivers/cpp/enhanced-fill.hpp; a spec
whose pattern is not in the library is invalid by definition (the LLM must
not invent patterns). Specs translate to compile defines via spec_defines().

Static base set: sizes 0, 1, 2 and a small odd size (7) with the default
random fill — every parameterizable benchmark gets these, LLM-free.

Mutation: deterministic (seeded) spec-level neighborhood — size +/-1, size*2,
value_range shifted/narrowed, pattern swapped to a related one — capped per
benchmark (config: stages.enhanced_tests.max_cases_per_benchmark).
"""

from __future__ import annotations

import random
from typing import Any

# name -> id, keep in sync with drivers/cpp/enhanced-fill.hpp
PATTERNS = {
    "random": 0,
    "all_zeros": 1,
    "all_same": 2,
    "ascending": 3,
    "descending": 4,
    "alternating": 5,
    "extreme_values": 6,
}

STATIC_BASE_SIZES = (0, 1, 2, 7)

DEFAULT_MAX_CASES_PER_BENCHMARK = 20
DEFAULT_MAX_SPEC_SIZE = 4096

MUTATION_SEED = 20260709  # fixed: mutations must be reproducible

# related-pattern swaps used by the mutator (order-preserving pairs)
PATTERN_SWAPS = {
    "ascending": "descending",
    "descending": "ascending",
    "all_zeros": "all_same",
    "all_same": "alternating",
    "random": "extreme_values",
    "alternating": "extreme_values",
    "extreme_values": "alternating",
}


def validate_spec(
    spec: Any,
    known_benchmarks: "set[str]",
    max_size: int = DEFAULT_MAX_SPEC_SIZE,
) -> "tuple[bool, str]":
    """Schema check. Returns (ok, reason-if-not)."""
    if not isinstance(spec, dict):
        return False, "not an object"

    benchmark = spec.get("benchmark")
    if benchmark not in known_benchmarks:
        return False, f"unknown benchmark: {benchmark!r}"

    size = spec.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return False, f"size must be a non-negative int, got {size!r}"
    if size > max_size:
        return False, f"size {size} exceeds max_spec_size {max_size}"

    pattern = spec.get("pattern")
    if pattern not in PATTERNS:
        return False, f"unknown pattern: {pattern!r} (allowed: {', '.join(PATTERNS)})"

    params = spec.get("pattern_params") or {}
    if not isinstance(params, dict):
        return False, "pattern_params must be an object"

    value_range = params.get("value_range")
    if value_range is not None:
        if (
            not isinstance(value_range, (list, tuple))
            or len(value_range) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value_range)
            or not value_range[0] <= value_range[1]
        ):
            return False, f"value_range must be [lo, hi] numbers with lo <= hi, got {value_range!r}"

    if spec.get("source") not in ("static", "llm", "mutation"):
        return False, f"invalid source: {spec.get('source')!r}"

    return True, ""


def spec_key(spec: dict) -> tuple:
    """Identity for dedupe and baseline-gate caching."""
    value_range = (spec.get("pattern_params") or {}).get("value_range")
    bounds = tuple(float(v) for v in value_range) if value_range else None
    return (spec["benchmark"], spec["size"], spec["pattern"], bounds)


def spec_defines(spec: dict) -> "list[str]":
    """Compile defines (without -D prefix) realizing this spec."""
    defines = [
        f"ENHANCED_TEST_SIZE={spec['size']}",
        f"ENHANCED_FILL_PATTERN={PATTERNS[spec['pattern']]}",
    ]

    value_range = (spec.get("pattern_params") or {}).get("value_range")
    if value_range:
        defines.append(f"ENHANCED_FILL_LO=({float(value_range[0])})")
        defines.append(f"ENHANCED_FILL_HI=({float(value_range[1])})")

    return defines


def static_base_specs(benchmark: str) -> "list[dict]":
    """The LLM-free foundation every parameterizable benchmark gets."""
    return [
        {
            "benchmark": benchmark,
            "size": size,
            "pattern": "random",
            "pattern_params": {},
            "source": "static",
            "rationale": f"static base set: size {size} with default random fill",
        }
        for size in STATIC_BASE_SIZES
    ]


def _mutants_of(spec: dict) -> "list[dict]":
    """Deterministic spec-level neighborhood of one seed spec."""
    mutants = []

    def clone(**overrides) -> dict:
        mutant = {
            **spec,
            "pattern_params": dict(spec.get("pattern_params") or {}),
            "source": "mutation",
            "rationale": f"mutation of: {spec.get('rationale', '')[:80]}",
        }
        mutant.update(overrides)
        return mutant

    size = spec["size"]
    for new_size in (size - 1, size + 1, size * 2):
        if new_size >= 0 and new_size != size:
            mutants.append(clone(size=new_size))

    value_range = (spec.get("pattern_params") or {}).get("value_range")
    if value_range:
        lo, hi = float(value_range[0]), float(value_range[1])
        span = hi - lo
        shifted = clone()
        shifted["pattern_params"]["value_range"] = [lo + span, hi + span]
        narrowed = clone()
        narrowed["pattern_params"]["value_range"] = [lo + span / 4, hi - span / 4]
        mutants += [shifted, narrowed]

    swap = PATTERN_SWAPS.get(spec["pattern"])
    if swap:
        mutants.append(clone(pattern=swap))

    return mutants


def build_benchmark_specs(
    benchmark: str,
    llm_specs: "list[dict]",
    max_cases: int = DEFAULT_MAX_CASES_PER_BENCHMARK,
) -> "list[dict]":
    """Full deterministic spec set for one benchmark: static base + LLM seeds
    + one mutation round over the seeds, deduped, capped at max_cases.

    Priority under the cap: static base first (the foundation), then LLM
    seeds (curated edge cases), then mutations in seeded-shuffled order.
    """
    static = static_base_specs(benchmark)
    seeds = static + llm_specs

    mutations = []
    for seed_spec in seeds:
        mutations.extend(_mutants_of(seed_spec))

    rng = random.Random(f"{MUTATION_SEED}:{benchmark}")
    rng.shuffle(mutations)

    result: "list[dict]" = []
    seen = set()

    for spec in static + llm_specs + mutations:
        key = spec_key(spec)
        if key in seen:
            continue
        seen.add(key)
        result.append(spec)
        if len(result) >= max_cases:
            break

    return result
