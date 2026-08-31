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

# E2-A: benchmark capability enforcement. Validation, LLM generation and the
# mutation path all go through this ONE module (thesis/enhanced_tests/
# capabilities.py -> enhanced_policy.json); there is no second table.
from thesis.enhanced_tests import capabilities

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

# E2-A.1: the pattern-parameter relevance table in capabilities.py is the ONE
# canonical statement of which fill parameters a pattern reads. K_PATTERNS is
# derived from it instead of being a second list that could drift.
K_PATTERNS = capabilities.K_PATTERNS

if set(PATTERNS) != set(capabilities.PATTERN_PARAM_RELEVANCE):
    raise RuntimeError(
        "the implemented pattern library (specs.PATTERNS) and the canonical "
        "pattern-parameter relevance table (capabilities.PATTERN_PARAM_RELEVANCE) "
        "disagree: %s vs %s"
        % (sorted(PATTERNS), sorted(capabilities.PATTERN_PARAM_RELEVANCE)))

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
    # which execution models the runner covers; ["serial"] = the historical
    # behavior. The GATES stay serial regardless (pilot decision, see
    # run_enhanced_tests.py docstring + docs/enhanced-tests-parallel.md).
    "execution_models": ["serial"],
    # ONE fixed launch point for parallel samples — deliberately not a
    # grid (grids are the correctness stage's axis)
    "enhanced_launch": {"omp_threads": 4, "mpi_ranks": 4},
    # runner worker-pool width PER EXECUTION MODEL (samples run in
    # parallel, specs within a sample stay sequential). The built-in
    # default 1/1/1 IS the historical serial behavior; anything higher is
    # an explicit resource decision (omp/mpi samples already occupy
    # omp_threads/mpi_ranks cores each — see docs/parallel-execution.md).
    "jobs": {"serial": 1, "omp": 1, "mpi": 1},
}

ENHANCED_EXECUTION_MODELS = ("serial", "omp", "mpi")


def stage_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """stages.enhanced_tests merged over defaults (defaults == historical
    behavior). `max_cases_per_benchmark` is honored as the legacy alias of
    `target_cases_per_benchmark`."""
    raw = (config.get("stages") or {}).get("enhanced_tests") or {}

    merged = dict(DEFAULT_SETTINGS)

    for key in DEFAULT_SETTINGS:
        if raw.get(key) is not None:
            merged[key] = raw[key]

    # enhanced_launch merges PER SUBKEY: a config that sets only
    # omp_threads must not silently lose the mpi_ranks default
    if isinstance(raw.get("enhanced_launch"), dict):
        merged["enhanced_launch"] = dict(DEFAULT_SETTINGS["enhanced_launch"])
        merged["enhanced_launch"].update(raw["enhanced_launch"])

    # jobs merges PER SUBKEY for the same reason (a config setting only
    # serial keeps omp/mpi at the serial-behavior default 1)
    if isinstance(raw.get("jobs"), dict):
        merged["jobs"] = dict(DEFAULT_SETTINGS["jobs"])
        merged["jobs"].update(raw["jobs"])

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

    models = settings["execution_models"]
    if not isinstance(models, list) or not models:
        raise ValueError(
            "stages.enhanced_tests.execution_models must be a non-empty "
            "list (got %r)" % (models,)
        )
    unknown_models = [m for m in models if m not in ENHANCED_EXECUTION_MODELS]
    if unknown_models:
        raise ValueError(
            "stages.enhanced_tests.execution_models: unknown model(s) %s "
            "(known: %s)" % (unknown_models, ", ".join(ENHANCED_EXECUTION_MODELS))
        )

    launch = settings["enhanced_launch"]
    if not isinstance(launch, dict):
        raise ValueError(
            "stages.enhanced_tests.enhanced_launch must be a mapping "
            "(got %r)" % (launch,)
        )
    for key in launch:
        if key not in ("omp_threads", "mpi_ranks"):
            raise ValueError(
                "stages.enhanced_tests.enhanced_launch: unknown key '%s' "
                "(known: omp_threads, mpi_ranks)" % key
            )
    for key in ("omp_threads", "mpi_ranks"):
        value = launch.get(key, DEFAULT_SETTINGS["enhanced_launch"][key])
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(
                "stages.enhanced_tests.enhanced_launch.%s must be a "
                "positive integer (got %r)" % (key, value)
            )

    jobs = settings["jobs"]
    if not isinstance(jobs, dict):
        raise ValueError(
            "stages.enhanced_tests.jobs must be a mapping of EXECUTION "
            "models (serial/omp/mpi) to worker counts (got %r)" % (jobs,)
        )
    for key, value in jobs.items():
        if key not in ENHANCED_EXECUTION_MODELS:
            raise ValueError(
                "stages.enhanced_tests.jobs: unknown key '%s' — keys are "
                "EXECUTION models (%s), not LLM model ids"
                % (key, ", ".join(ENHANCED_EXECUTION_MODELS))
            )
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(
                "stages.enhanced_tests.jobs.%s must be a positive integer "
                "(got %r)" % (key, value)
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
        ):
            return False, "value_range must be [lo, hi] numbers, got %r" % (
                value_range,
            )
        # E2-A.1: NaN/+-Inf are rejected EXPLICITLY and before the ordering
        # comparison. Relying on `lo <= hi` caught NaN only by accident (every
        # comparison with NaN is false) and accepted +/-Inf outright.
        non_finite = capabilities.non_finite_range_reason(value_range)
        if non_finite is not None:
            return False, non_finite
        if not value_range[0] <= value_range[1]:
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

    # E2-A capability enforcement (single source: capabilities.py). Rejects a
    # pattern the benchmark cannot actually vary (fake diversity), a pattern
    # whose frozen oracle would execute undefined behaviour on it, a pattern
    # whose admissibility depends on an OPEN policy, and a size that is
    # technically unsafe for this specific benchmark. Benchmarks the policy does
    # not know are not restricted.
    capability_reason = capabilities.spec_rejection(benchmark, size, pattern)
    if capability_reason is not None:
        return False, capability_reason

    # E2-A.1 parameter-level fake diversity: a parameter the pattern (or the
    # benchmark, when it has no fill hook at all) never reads cannot change the
    # input, so it must not be able to create a second spec identity. Rejected
    # rather than normalized away - normalizing would silently equate two
    # DIFFERENT stored specs and reinterpret their historical spec_keys.
    parameter_reason = capabilities.parameter_rejection(
        benchmark, pattern, params, bool(spec.get("values")))
    if parameter_reason is not None:
        return False, parameter_reason

    # E2-A.1 technical range safety: representable endpoints AND a span the
    # current fill arithmetic can compute. Purely technical - no statement
    # about which values are meaningful for the benchmark.
    range_reason = capabilities.value_range_rejection(benchmark, pattern, value_range)
    if range_reason is not None:
        return False, range_reason

    # E2-B domain safety: technical representability is not enough - the range
    # must also be a subset of the benchmark's DECLARED legitimate fill domain,
    # and a benchmark whose fill sites declare different domains supports no
    # global value_range at all.
    domain_reason = capabilities.value_range_domain_rejection(
        benchmark, pattern, value_range)
    if domain_reason is not None:
        return False, domain_reason

    values = spec.get("values") or []
    value_reason = capabilities.explicit_values_rejection(benchmark, values)
    if value_reason is not None:
        return False, value_reason

    value_domain_reason = capabilities.explicit_values_domain_rejection(
        benchmark, values)
    if value_domain_reason is not None:
        return False, value_domain_reason

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


def spec_runtime_env(spec: dict, values_file: "Optional[str]" = None) -> "Dict[str, str]":
    """Environment variables realizing this spec for a runtime-fill binary
    (compiled with -DENHANCED_RUNTIME_FILL), the runtime twin of
    spec_defines(): the pattern travels as the SAME integer id, lo/hi as
    %.17g-formatted doubles (round-trip exact and locale-free — Python
    formats without locale, the header parses with std::from_chars).
    explicit_values data travels via a values FILE (one number per line,
    row-major) whose path the caller must supply; requesting the env for an
    explicit_values spec without one is a programming error, not a runtime
    fallback."""
    env = {"ENHANCED_FILL_PATTERN": str(PATTERNS[spec["pattern"]])}

    params = spec.get("pattern_params") or {}

    value_range = params.get("value_range")
    if value_range:
        env["ENHANCED_FILL_RANGE_LO"] = "%.17g" % float(value_range[0])
        env["ENHANCED_FILL_RANGE_HI"] = "%.17g" % float(value_range[1])

    if spec["pattern"] in K_PATTERNS:
        env["ENHANCED_FILL_K"] = "%d" % int(params["k"])

    if spec["pattern"] == "explicit_values":
        if values_file is None:
            raise ValueError(
                "explicit_values spec needs a values_file path "
                "(write explicit_values_file_text() first)"
            )
        env["ENHANCED_FILL_VALUES_FILE"] = str(values_file)

    return env


def explicit_values_file_text(spec: dict) -> Optional[str]:
    """Text of the runtime values file for an explicit_values spec (None
    for other patterns). One number per line, row-major, %.17g (round-trip
    exact, locale-free). Mirrors explicit_values_header(): an EMPTY values
    list writes a single 0.0 line (count 1), so the degenerate size-0 case
    keeps identical semantics in both modes — the value is never read at
    size 0, and the header's no-empty-file abort rule stays intact."""
    if spec.get("pattern") != "explicit_values":
        return None

    values = [float(v) for v in spec.get("values") or []]
    if not values:
        values = [0.0]

    return "".join("%.17g\n" % v for v in values)


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

    # E2-A: drop base sizes that are technically unsafe for THIS benchmark
    # (e.g. size 0 where the frozen oracle reads out of bounds). This is a
    # per-benchmark constraint, not a global size-0 policy.
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
        if capabilities.size_rejection(benchmark, int(size)) is None
    ]


def _mutants_of(spec: dict, max_size: int) -> "List[dict]":
    """Deterministic spec-level neighborhood of one seed spec.

    explicit_values specs are never mutated (surgical cases; a size
    mutation would break the len(values) == size contract)."""
    if spec.get("pattern") == "explicit_values":
        return []

    # E2-A.1: a seed that already carries an irrelevant, unknown or inert fill
    # parameter is itself invalid; mutating it would turn one historical
    # fake-diversity spec into a family of new ones. The seed is NOT silently
    # normalized (that would equate two different stored specs) - it simply
    # produces no offspring.
    if capabilities.parameter_rejection(
        spec["benchmark"], spec["pattern"],
        spec.get("pattern_params") or {}, bool(spec.get("values")),
    ) is not None:
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
    if value_range and capabilities.pattern_uses(spec["pattern"], "value_range"):
        lo, hi = float(value_range[0]), float(value_range[1])
        span = hi - lo
        for bounds in ([lo + span, hi + span], [lo + span / 4, hi - span / 4]):
            # E2-A.1: a shifted/narrowed range must itself be technically safe.
            # Without this the mutator could push a valid range past the fill
            # container's representable bounds or its safe span.
            if capabilities.value_range_rejection(
                spec["benchmark"], spec["pattern"], bounds
            ) is not None:
                continue
            # E2-B: and inside the declared benchmark domain. A mutant that
            # would leave the domain is NOT generated - it is never clamped
            # back, which would silently rewrite the mutation.
            if capabilities.value_range_domain_rejection(
                spec["benchmark"], spec["pattern"], bounds
            ) is not None:
                continue
            mutant = clone()
            mutant["pattern_params"]["value_range"] = bounds
            mutants.append(mutant)

    # E2-A: a pattern swap may only target a pattern the benchmark actually
    # supports. Without this the mutator manufactured specs that differ only in
    # an inert or unsafe pattern label (random -> extreme_values on a benchmark
    # with no fill hook), which validate_spec would then reject anyway.
    swap = PATTERN_SWAPS.get(spec["pattern"])
    if swap and capabilities.pattern_rejection(spec["benchmark"], swap) is None:
        swapped = clone(pattern=swap)
        # E2-A.1: the swap inherits the seed's parameters, which the TARGET
        # pattern may not read (random -> extreme_values carries a value_range
        # extreme_values ignores). Such a mutant would be pure parameter-level
        # fake diversity, so it is dropped instead of emitted.
        if capabilities.parameter_rejection(
            swapped["benchmark"], swap, swapped.get("pattern_params") or {},
            bool(swapped.get("values")),
        ) is None:
            mutants.append(swapped)

    return mutants


MUTATION_FRONTIER_CANONICALIZATION_VERSION = "e3.1"


def canonical_seed_identities(
    seeds: "List[dict]",
    known_benchmarks: "set",
    max_size: int = 4096,
    explicit_values_max_size: int = 64,
) -> "List[dict]":
    """The seed list reduced to one object per spec_key: the first VALID one.

    E3.1: this is what both the emitted seeds and the mutation frontier are
    built from, so neither row multiplicity nor unrunnable rows can influence
    what a benchmark ends up testing. Order of first valid appearance is
    preserved, so the deterministic mutation order is unchanged for a seed list
    that was already unique and valid.
    """
    seen = set()
    canonical: "List[dict]" = []
    for spec in seeds:
        try:
            key = spec_key(spec)
        except (KeyError, TypeError):
            continue                      # not even shaped like a spec
        if key in seen:
            continue                      # a second serialization of the same spec
        ok, _reason = validate_spec(
            spec, known_benchmarks, max_size=max_size,
            explicit_values_max_size=explicit_values_max_size)
        if not ok:
            continue                      # cannot run, so it must not breed either
        seen.add(key)
        canonical.append(spec)
    return canonical


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

    E3.1 CANONICAL SEED FRONTIER. The seed list is canonicalized BEFORE it is
    used, to the first VALID occurrence per spec_key. Previously the mutation
    frontier was seeded from the raw rows, so two things that must not matter
    did:

      * ROW MULTIPLICITY - a spec_key serialized twice (the pre-E3 cache had 12
        such rows) entered the frontier twice and mutated twice. Measured on the
        pre-E3 snapshot: 7 benchmarks, 21 raw-only and 21 canonical-only derived
        keys, plus fft/08 with the same keys in a different order.
      * INVALID SEEDS - a seed the frozen policy rejects was never emitted
        itself, but still produced mutants. Measured on the same snapshot: 46
        benchmarks, 152 raw-only and 138 canonical-only derived keys.

    Both are the same fake-diversity defect E2-A/E2-A.1 froze out one layer up:
    what a benchmark tests must follow from its SEED IDENTITIES, not from how
    many times a row was written or from rows that cannot run. Identity is
    spec_key; validity is decided per OBJECT, so a duplicate whose first
    serialization is invalid cannot mask a later valid one.

    SCOPE. Canonicalization applies to the SEED ROWS (`llm_specs`, i.e. what was
    deserialized from the spec artifact) - which is exactly where row
    multiplicity and unrunnable rows can occur. It is deliberately NOT applied
    to the union with the static base: `static_base_specs` is generated here,
    deterministically, and a static/LLM spec_key collision is a different
    phenomenon (two generators proposing one identity), not a serialization
    artefact. It produces no fake diversity either, because emission already
    dedupes on spec_key - it only lengthens the pre-shuffle mutation list.
    Collapsing it WOULD change which mutants survive the target cap, i.e. it
    would silently re-shuffle the suite E3 just froze (measured on the frozen
    artifact: 12 benchmarks, 38 colliding identities, 10 benchmarks with a
    changed key set). That is out of scope here and recorded as a separate
    finding.
    """
    settings = stage_settings(config or {})
    target = int(settings["target_cases_per_benchmark"])
    max_size = int(settings["max_spec_size"])
    known = {benchmark}

    static = static_base_specs(benchmark, settings["static_base_sizes"])
    # Canonicalize the SEED ROWS read from the spec artifact. The static base is
    # generated deterministically here, not deserialized, so it carries no row
    # multiplicity; it is deliberately NOT collapsed against the LLM seeds (see
    # the note above).
    seeds = static + canonical_seed_identities(
        llm_specs, known,
        max_size=max_size,
        explicit_values_max_size=int(settings["explicit_values_max_size"]),
    )

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
