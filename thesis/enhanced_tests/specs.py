"""Input-spec format for the enhanced-tests stage: test cases are DATA.

A spec describes one validation input configuration:

    {
      "benchmark": "dense_la/00_dense_la_lu_decomp",
      "size": 7,
      "pattern": "ascending",
      "pattern_params": {"value_range": [-1.0, 1.0], "k": 3},  # optional
      "values": [1.0, 2.0, ...],          # explicit_values pattern only
      "source": "static" | "llm" | "mutation",
      "spec_model": "<config spec_model>",   # llm specs, set by the script
      "parent_source": "static" | "llm",     # mutation specs only
      "rationale": "why this input is interesting"
    }

Pattern names map to the ids in drivers/cpp/enhanced-fill.hpp; a spec whose
pattern is not implemented (or, for LLM specs, not offered via config) is
invalid by definition. Specs translate to compile defines via
spec_defines(); the explicit_values pattern additionally emits a generated
header (explicit_values_header()).

All tunables come from config stages.enhanced_tests (static_base_sizes,
llm_specs_min/max, target_cases_per_benchmark, max_spec_size,
offered_patterns, explicit_values_max_size, ...); the module defaults
below equal the historical behavior.

Python 3.8 compatible.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Input shapes (derive_shapes.py -> benchmark_shapes.json)
#
# `size` is the benchmark's size PARAMETER, not necessarily its element
# count: an n x n matrix benchmark needs n*n input values. explicit_values
# is the one pattern that has to know the difference, since it ships the
# values themselves.
# ---------------------------------------------------------------------------

SHAPES_PATH = Path(__file__).resolve().parent / "benchmark_shapes.json"

_SHAPES_CACHE = None  # type: Optional[Dict[str, dict]]

# used when the shapes file is absent (e.g. a checkout without the derived
# artifact): behave like the historical 1-D assumption rather than crash
_DEFAULT_SHAPE = {
    "fill_sites": 1,
    "elements_per_site": ["n"],
    "total_elements": "n",
    "explicit_values_supported": True,
    "notes": "no benchmark_shapes.json — assuming 1-D (n elements)",
}


def load_shapes() -> "Dict[str, dict]":
    global _SHAPES_CACHE

    if _SHAPES_CACHE is None:
        if SHAPES_PATH.exists():
            with SHAPES_PATH.open("r", encoding="utf-8") as handle:
                _SHAPES_CACHE = json.load(handle)
        else:
            _SHAPES_CACHE = {}

    return _SHAPES_CACHE


def benchmark_shape(benchmark: str) -> dict:
    return load_shapes().get(benchmark, _DEFAULT_SHAPE)


def expected_value_count(benchmark: str, size: int) -> int:
    """How many explicit values this benchmark needs at `size`.

    Only defined for the single-fill-site benchmarks (validate_spec rejects
    explicit_values elsewhere); "n" -> size, "n2" -> size*size.
    """
    shape = benchmark_shape(benchmark)
    total = 0

    for form in shape.get("elements_per_site") or []:
        if form == "n":
            total += size
        elif form == "n2":
            total += size * size
        elif form.startswith("const:"):
            total += int(form.split(":", 1)[1])

    return total

# name -> id, keep in sync with drivers/cpp/enhanced-fill.hpp
PATTERNS = {
    "random": 0,
    "all_zeros": 1,
    "all_same": 2,
    "ascending": 3,
    "descending": 4,
    "alternating": 5,
    "extreme_values": 6,
    "duplicate_at": 7,
    "sorted_except_one": 8,
    "spike_at": 9,
    "explicit_values": 10,
}

# patterns taking a position parameter k (pattern_params["k"])
K_PATTERNS = ("duplicate_at", "sorted_except_one", "spike_at")

MUTATION_SEED = 20260709  # fixed: mutations must be reproducible

MAX_MUTATION_ROUNDS = 4

# related-pattern swaps used by the mutator (non-parameterized patterns
# only: a swap into a k-pattern would have to invent a k, and
# explicit_values specs are surgical cases that are never mutated)
PATTERN_SWAPS = {
    "ascending": "descending",
    "descending": "ascending",
    "all_zeros": "all_same",
    "all_same": "alternating",
    "random": "extreme_values",
    "alternating": "extreme_values",
    "extreme_values": "alternating",
}

DEFAULT_SETTINGS = {
    "static_base_sizes": [0, 1, 2, 7],
    "llm_specs_min": 5,
    "llm_specs_max": 8,
    "target_cases_per_benchmark": 20,
    "max_spec_size": 4096,
    "offered_patterns": list(PATTERNS.keys()),
    "explicit_values_max_size": 64,
    "baseline_prompt_max_chars": 12000,
}


def stage_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """stages.enhanced_tests merged over defaults (defaults == historical
    behavior). `max_cases_per_benchmark` is honored as the legacy alias of
    `target_cases_per_benchmark`."""
    raw = (config.get("stages") or {}).get("enhanced_tests") or {}

    merged = dict(DEFAULT_SETTINGS)

    for key in DEFAULT_SETTINGS:
        if raw.get(key) is not None:
            merged[key] = raw[key]

    if raw.get("target_cases_per_benchmark") is None and raw.get(
        "max_cases_per_benchmark"
    ) is not None:
        merged["target_cases_per_benchmark"] = raw["max_cases_per_benchmark"]

    return merged


def validate_enhanced_settings(config: Dict[str, Any]) -> None:
    """Hard config errors (called from load_config): unknown pattern names,
    min > max, target smaller than the static base set."""
    settings = stage_settings(config)

    unknown = [p for p in settings["offered_patterns"] if p not in PATTERNS]
    if unknown:
        raise ValueError(
            "stages.enhanced_tests.offered_patterns: unknown pattern(s) %s "
            "(implemented: %s) — config selects FROM the implemented "
            "library, it cannot invent patterns" % (unknown, ", ".join(PATTERNS))
        )

    if int(settings["llm_specs_min"]) > int(settings["llm_specs_max"]):
        raise ValueError(
            "stages.enhanced_tests: llm_specs_min (%s) > llm_specs_max (%s)"
            % (settings["llm_specs_min"], settings["llm_specs_max"])
        )

    if int(settings["target_cases_per_benchmark"]) < len(settings["static_base_sizes"]):
        raise ValueError(
            "stages.enhanced_tests: target_cases_per_benchmark (%s) is "
            "smaller than the static base set (%d sizes)"
            % (settings["target_cases_per_benchmark"], len(settings["static_base_sizes"]))
        )


def validate_spec(
    spec: Any,
    known_benchmarks: "set",
    max_size: int = 4096,
    allowed_patterns: Optional[List[str]] = None,
    explicit_values_max_size: int = 64,
) -> "Tuple[bool, str]":
    """Schema check. Returns (ok, reason-if-not).

    allowed_patterns restricts beyond the implemented library (used for
    LLM specs, which may only use the offered subset).
    """
    if not isinstance(spec, dict):
        return False, "not an object"

    benchmark = spec.get("benchmark")
    if benchmark not in known_benchmarks:
        return False, "unknown benchmark: %r" % (benchmark,)

    size = spec.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return False, "size must be a non-negative int, got %r" % (size,)
    if size > max_size:
        return False, "size %s exceeds max_spec_size %s" % (size, max_size)

    pattern = spec.get("pattern")
    if pattern not in PATTERNS:
        return False, "unknown pattern: %r (implemented: %s)" % (pattern, ", ".join(PATTERNS))
    if allowed_patterns is not None and pattern not in allowed_patterns:
        return False, "pattern %r is not offered (offered: %s)" % (
            pattern,
            ", ".join(allowed_patterns),
        )

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
            return False, "value_range must be [lo, hi] numbers with lo <= hi, got %r" % (
                value_range,
            )

    if pattern in K_PATTERNS:
        if size < 2:
            return False, "%s requires size >= 2 (got %s)" % (pattern, size)
        k = params.get("k")
        if not isinstance(k, int) or isinstance(k, bool) or not (0 <= k <= size - 1):
            return False, "%s: k must be an int in [0, size-1], got %r" % (pattern, k)

    if pattern == "explicit_values":
        values = spec.get("values")

        # The number of values a benchmark needs is its INPUT SHAPE, not its
        # `size`: an n x n matrix benchmark needs n*n values (row-major).
        # Shapes are derived from each validate() body and checked in
        # benchmark_shapes.json (thesis/enhanced_tests/derive_shapes.py).
        shape = benchmark_shape(benchmark)

        if not shape.get("explicit_values_supported"):
            return False, "explicit_values: not supported for %s (%s)" % (
                benchmark,
                shape.get("notes") or "no single canonical fill site",
            )

        expected = expected_value_count(benchmark, size)

        # Cap on the ELEMENT COUNT, not on `size` — otherwise a 64x64 matrix
        # would sneak 4096 hand-written values past a size-64 limit. The
        # config value keeps its meaning for 1-D benchmarks (size == count);
        # for matrices it now binds where it actually matters.
        if expected > explicit_values_max_size:
            return False, (
                "explicit_values: %s values needed for size %s (%s) exceeds "
                "explicit_values_max_size %s"
                % (expected, size, shape.get("total_elements"), explicit_values_max_size)
            )

        if (
            not isinstance(values, (list, tuple))
            or len(values) != expected
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
        ):
            return False, (
                "explicit_values: values must be %s numbers (%s for size %s), got %s"
                % (
                    expected,
                    shape.get("total_elements"),
                    size,
                    len(values) if isinstance(values, (list, tuple)) else type(values).__name__,
                )
            )

    if spec.get("source") not in ("static", "llm", "mutation"):
        return False, "invalid source: %r" % (spec.get("source"),)

    return True, ""


def spec_key(spec: dict) -> tuple:
    """Identity for dedupe, resume and baseline-gate caching.

    Components for k/values are appended ONLY when present so that keys of
    the pre-existing patterns stay identical to earlier runs (gate caches
    and resume files remain valid)."""
    params = spec.get("pattern_params") or {}
    value_range = params.get("value_range")
    bounds = tuple(float(v) for v in value_range) if value_range else None

    key = (spec["benchmark"], spec["size"], spec["pattern"], bounds)

    if params.get("k") is not None:
        key = key + (int(params["k"]),)

    if spec.get("values"):
        key = key + (tuple(float(v) for v in spec["values"]),)

    return key


def spec_defines(spec: dict) -> "List[str]":
    """Compile defines (without -D prefix) realizing this spec. The
    explicit_values data travels via the generated header instead
    (explicit_values_header()), not as a define."""
    defines = [
        "ENHANCED_TEST_SIZE=%d" % spec["size"],
        "ENHANCED_FILL_PATTERN=%d" % PATTERNS[spec["pattern"]],
    ]

    params = spec.get("pattern_params") or {}

    value_range = params.get("value_range")
    if value_range:
        defines.append("ENHANCED_FILL_LO=(%s)" % float(value_range[0]))
        defines.append("ENHANCED_FILL_HI=(%s)" % float(value_range[1]))

    if spec["pattern"] in K_PATTERNS:
        defines.append("ENHANCED_FILL_PARAM_K=%d" % int(params["k"]))

    return defines


def explicit_values_header(spec: dict) -> Optional[str]:
    """Text of the generated enhanced-explicit-values.hpp for an
    explicit_values spec (None for other patterns). The runner writes it
    into an -I'd build dir; enhanced-fill.hpp includes it when pattern 10
    is selected. Containers longer than the list fill cyclically
    (row-major repetition for size x size matrices)."""
    if spec.get("pattern") != "explicit_values":
        return None

    values = [float(v) for v in spec.get("values") or []]
    body = ", ".join(repr(v) for v in values) if values else "0.0"
    count = max(len(values), 1)

    return (
        "#pragma once\n"
        "// generated per-spec by the enhanced-tests runner\n"
        "static const double ENHANCED_EXPLICIT_VALUES[] = {%s};\n"
        "static const size_t ENHANCED_EXPLICIT_COUNT = %d;\n" % (body, count)
    )


def static_base_specs(benchmark: str, sizes: Optional[List[int]] = None) -> "List[dict]":
    """The LLM-free foundation every parameterizable benchmark gets."""
    base_sizes = sizes if sizes is not None else DEFAULT_SETTINGS["static_base_sizes"]

    return [
        {
            "benchmark": benchmark,
            "size": int(size),
            "pattern": "random",
            "pattern_params": {},
            "source": "static",
            "rationale": "static base set: size %s with default random fill" % size,
        }
        for size in base_sizes
    ]


def _mutants_of(spec: dict, max_size: int) -> "List[dict]":
    """Deterministic spec-level neighborhood of one seed spec.

    explicit_values specs are never mutated (surgical cases; a size
    mutation would break the len(values) == size contract)."""
    if spec.get("pattern") == "explicit_values":
        return []

    mutants = []
    parent_source = spec.get("parent_source") or spec.get("source")

    def clone(**overrides) -> dict:
        mutant = {
            **spec,
            "pattern_params": dict(spec.get("pattern_params") or {}),
            "source": "mutation",
            "parent_source": parent_source,
            "rationale": "mutation of: %s" % (spec.get("rationale", "")[:80],),
        }
        mutant.pop("spec_model", None)
        mutant.update(overrides)
        return mutant

    size = spec["size"]
    for new_size in (size - 1, size + 1, size * 2):
        if 0 <= new_size <= max_size and new_size != size:
            mutant = clone(size=new_size)
            # keep k valid under the new size (k-patterns need k <= size-1)
            k = (mutant["pattern_params"] or {}).get("k")
            if k is not None and new_size >= 2:
                mutant["pattern_params"]["k"] = min(int(k), new_size - 1)
            mutants.append(mutant)

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
    llm_specs: "List[dict]",
    config: Optional[Dict[str, Any]] = None,
) -> "List[dict]":
    """Full deterministic spec set for one benchmark: static base + LLM
    seeds + mutation rounds, deduped, targeting
    target_cases_per_benchmark.

    Fill-up guarantee: if one mutation round does not reach the target,
    further rounds mutate the previous round's mutants (second-order
    mutation), each round with its own deterministic shuffle seed. Stops
    after MAX_MUTATION_ROUNDS or when a round yields no new unique specs
    (space exhausted, e.g. tiny sizes) — then returns fewer than target
    (caller logs under_target).

    Priority under the cap: static base first, then LLM seeds, then
    mutations in seeded-shuffled round order. Invalid mutants (e.g. k out
    of range after a size mutation) are dropped via validate_spec.
    """
    settings = stage_settings(config or {})
    target = int(settings["target_cases_per_benchmark"])
    max_size = int(settings["max_spec_size"])
    known = {benchmark}

    static = static_base_specs(benchmark, settings["static_base_sizes"])
    seeds = static + llm_specs

    result: "List[dict]" = []
    seen = set()

    def try_add(spec: dict) -> bool:
        key = spec_key(spec)
        if key in seen:
            return False
        ok, _ = validate_spec(
            spec, known, max_size=max_size,
            explicit_values_max_size=int(settings["explicit_values_max_size"]),
        )
        if not ok:
            return False
        seen.add(key)
        result.append(spec)
        return True

    for spec in seeds:
        if len(result) >= target:
            return result[:target]
        try_add(spec)

    frontier = list(seeds)

    for round_index in range(MAX_MUTATION_ROUNDS):
        if len(result) >= target:
            break

        mutations: "List[dict]" = []
        for seed_spec in frontier:
            mutations.extend(_mutants_of(seed_spec, max_size))

        rng = random.Random("%s:%s:round%d" % (MUTATION_SEED, benchmark, round_index))
        rng.shuffle(mutations)

        added_this_round: "List[dict]" = []
        for spec in mutations:
            if len(result) >= target:
                break
            if try_add(spec):
                added_this_round.append(spec)

        if not added_this_round:
            break  # space exhausted

        frontier = added_this_round

    return result
