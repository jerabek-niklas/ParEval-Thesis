#!/usr/bin/env python3
"""Staleness check for the cross-pilot comparability gate.

Recomputes ALL state fingerprints stored in
thesis/evaluation/cross_pilot_comparability.json under the SAME canonical
rules used at gate-creation time and compares them. Four groups:

  BENCHMARK_LOCAL_STATE   per candidate-subset benchmark: cpu.cc,
                          baseline.hpp, the three prompt strings, and the
                          benchmark-local enhanced-spec projection
  SHARED_STATE            shared measurement/comparator/transport/enhanced
                          dependency files (raw-byte hashes, each with an
                          explicit granularity: semantic | coarse)
  GENERATION_CONDITION    canonical projection of the response-relevant
                          model-generation condition (system prompt +
                          generation params + model identities, no secrets,
                          no prices) - the SAME field definition Wave 3 used
                          for its generation-condition comparison
  EVALUATION_CONDITION    canonical projection of the verdict-relevant
                          correctness evaluation condition (launch grids,
                          compilers/flags, NDEBUG state, DRIVER_PROBLEM_SIZE,
                          niter, MAX_VALIDATION_ATTEMPTS, build/run timeouts)
  ASSEMBLY_STATE          candidate-source construction semantics: raw-byte
                          hashes of cleaning.py (semantic) and
                          assemble_sources.py (coarse) plus the canonical
                          assembly condition (auto_close_single_brace)
  EFFECTIVE_INVOCATION_POLICY (repo-side only) the frozen EXPECTED values of
                          the verdict-relevant CLI overrides
                          (--primary-compiler, --run-timeout) are still
                          reproducible from the productive defaults/config.
                          This NEVER validates an actual future invocation:
                          EFFECTIVE_INVOCATION_RUNTIME_CHECK = REQUIRED via
                          thesis/evaluation/pilot_preflight.py.
  ENVIRONMENT_CONDITION   (repo-side only) the stored expected environment
                          values are still derivable from the frozen
                          pilot_001 toolchain provenance and the Dockerfile
                          pinning classification still holds.
                          ENVIRONMENT_RUNTIME_CHECK = REQUIRED via the pilot
                          preflight (actual compiler/MPI/container identity).

Benchmark-local hash rules (unchanged since gate creation):
  cpu_cc_sha256        SHA-256 over the RAW BYTES of
                       drivers/cpp/benchmarks/<problem_type>/<name>/cpu.cc
  baseline_hpp_sha256  SHA-256 over the RAW BYTES of
                       drivers/cpp/benchmarks/<problem_type>/<name>/baseline.hpp
  prompt_sha256.<pm>   SHA-256 over the UTF-8 encoding of the full `prompt`
                       string of the entry in
                       thesis/prompts/generation-prompts-thesis.json matched by
                       the stable identity (problem_type, name,
                       parallelism_model). Array positions are never join keys.
  enhanced_spec_keys_sha256
                       Benchmark-local projection of the frozen E3 spec
                       artifact thesis/enhanced_tests/frozen/e3_final_specs.jsonl
                       (version controlled; the gitignored generator cache
                       thesis/results/cache/enhanced/specs.jsonl remains a
                       fallback and was byte-identical when this source was
                       switched, so no stored hash changed): take every
                       raw line whose parsed JSON object has
                       obj["benchmark"] == "<problem_type>/<name>", strip one
                       trailing "\\n" / "\\r\\n" from the line, sort the lines
                       lexicographically as Unicode strings, join with "\\n",
                       SHA-256 over the UTF-8 encoding of the joined string.

Shared-state rule: SHA-256 over the RAW BYTES of each file listed in the
gate's shared_state.files - no normalization, no reformatting, no git blob
SHA. Granularity semantics:
  semantic  the file consists essentially of shared verdict-/comparison-/
            transport-/input-semantic logic; a byte diff is highly likely
            methodically relevant ("shared semantic dependency changed").
  coarse    the file contains real verdict/measurement semantics but also
            substantial unrelated code; a byte diff still triggers STALE,
            but only means "coarse shared dependency changed; inspect
            whether the diff affects verdict semantics" - it is NOT proof
            of a semantic change.

Condition canonicalization (both conditions): build the structured
projection described in generation_condition_projection() /
evaluation_condition_projection(), serialize with
json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
(dict keys sorted; LIST ORDER PRESERVED - flag and grid order is kept as
produced by the productive configuration), SHA-256 over UTF-8. The
generation projection reuses byte-for-byte the Wave-3 comparison definition
(yaml.safe_load of thesis/config/config.yaml; generation_defaults block
plus all model fields except price_per_mtok_in/price_per_mtok_out, models
keyed by stable model id; api_key_env is an environment-variable NAME, no
secret material; run_id/paths/prices/profiles excluded).

Semantics of the result (frozen in the gate artifact's validity block):
  all stored fingerprints reproducible and equal -> CROSS_PILOT_GATE_STALE = false, exit 0
  at least one reproducible fingerprint differs  -> CROSS_PILOT_GATE_STALE = true,  exit 1
                                                    (comparability_re_evaluation_required;
                                                    a hash diff does NOT by itself yield a
                                                    new classification, subset or cell count)
  a stored non-null state no longer addressable  -> CROSS_PILOT_GATE_STALE = UNRESOLVED, exit 2
A stored null hash (state documented as unavailable at creation time) is
skipped, never treated as a mismatch.

Requires PyYAML (run with the repo venv or the analysis container); a
missing dependency is reported as UNRESOLVED, never silently ignored.

Read-only: this script never writes anything.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPO_ROOT / "thesis" / "evaluation" / "cross_pilot_comparability.json"
PROMPTS_PATH = REPO_ROOT / "thesis" / "prompts" / "generation-prompts-thesis.json"
# Cross-pilot reevaluation: the benchmark-local enhanced-spec projection is read
# from the VERSION-CONTROLLED frozen E3 artifact, not from the gitignored
# generator cache (.gitignore:23 ignores thesis/results/cache/). The two were
# verified byte-identical at reevaluation time (both sha256
# 49b0229c508f063008078bd58cb61bfebc82c2b2b75c680b42cdd262bd440292, 471 specs),
# so NO stored hash changes; only the source becomes reproducible in a fresh
# clone. The legacy cache path stays as a documented fallback so an older
# checkout without the frozen artifact still resolves instead of going
# UNRESOLVED.
SPECS_PATH = (REPO_ROOT / "thesis" / "enhanced_tests" / "frozen"
              / "e3_final_specs.jsonl")
SPECS_PATH_LEGACY_CACHE = (REPO_ROOT / "thesis" / "results" / "cache"
                           / "enhanced" / "specs.jsonl")
BENCH_ROOT = REPO_ROOT / "drivers" / "cpp" / "benchmarks"
CONFIG_PATH = REPO_ROOT / "thesis" / "config" / "config.yaml"
UTILITIES_HPP = REPO_ROOT / "drivers" / "cpp" / "utilities.hpp"
TOOLS_PY = REPO_ROOT / "thesis" / "evaluation" / "tools.py"
RUN_CORRECTNESS_PY = REPO_ROOT / "thesis" / "evaluation" / "run_correctness.py"
TOOLCHAIN_PROVENANCE = (REPO_ROOT / "thesis" / "results" / "intermediate" /
                        "pilot_001" / "toolchain-versions.txt")
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"

PM_CANON = ("serial", "omp", "mpi")


class ConditionUnresolved(Exception):
    """A source needed to recompute a condition is no longer addressable."""


# ---------------------------------------------------------------------------
# canonical serialization (shared by both conditions)
# ---------------------------------------------------------------------------

def canon_sha256(obj):
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_yaml_config(config_path=None):
    """Load the productive config (default) or, for the pilot preflight's
    content-addressed check, an explicitly given config file. The projection
    field definitions below are identical either way - there is exactly ONE
    definition of each condition."""
    try:
        import yaml
    except ImportError:
        raise ConditionUnresolved(
            "PyYAML not importable - run with the repo venv "
            "(.venv\\Scripts\\python.exe) or the analysis container")
    path = Path(config_path) if config_path is not None else CONFIG_PATH
    if not path.is_file():
        raise ConditionUnresolved("config file missing: %s" % path)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extract(pattern, path, cast, what):
    """Regex-extract a single productive constant from a source file."""
    if not path.is_file():
        raise ConditionUnresolved("%s: source file missing: %s" % (what, path))
    m = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if not m:
        raise ConditionUnresolved("%s: pattern %r not found in %s" % (what, pattern, path))
    return cast(m.group(1))


# ---------------------------------------------------------------------------
# generation condition (Wave-3 field definition, unchanged)
# ---------------------------------------------------------------------------

def generation_condition_projection(config_path=None):
    cfg = _load_yaml_config(config_path)
    gd = cfg.get("generation_defaults")
    models = cfg.get("models")
    if gd is None or models is None:
        raise ConditionUnresolved("config.yaml lacks generation_defaults/models")
    model_view = {}
    for x in models:
        model_view[x["id"]] = {k: x.get(k) for k in sorted(x.keys())
                               if k not in ("price_per_mtok_in", "price_per_mtok_out")}
    return {"generation_defaults": gd, "models": model_view}


# ---------------------------------------------------------------------------
# evaluation condition (correctness stage, verdict-relevant parameters only)
# ---------------------------------------------------------------------------

def evaluation_condition_projection(config_path=None):
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from thesis.evaluation.build_config import (
            BASE_CXX_STANDARD, BASE_OPTIMIZATION, get_build_config,
            get_launch_config,
        )
    except Exception as exc:  # pragma: no cover - import failure = unresolved
        raise ConditionUnresolved("cannot import thesis.evaluation.build_config: %s" % exc)

    driver_problem_size = _extract(
        r'^DRIVER_PROBLEM_SIZE_DEFINE\s*=\s*"DRIVER_PROBLEM_SIZE=(.+)"\s*$',
        TOOLS_PY, str, "DRIVER_PROBLEM_SIZE")
    default_niter = _extract(r"^DEFAULT_NITER\s*=\s*(\d+)\s*$",
                             RUN_CORRECTNESS_PY, int, "DEFAULT_NITER")
    default_build_timeout = _extract(r"^DEFAULT_BUILD_TIMEOUT\s*=\s*([0-9.]+)\s*$",
                                     RUN_CORRECTNESS_PY, float, "DEFAULT_BUILD_TIMEOUT")
    default_run_timeout = _extract(r"^DEFAULT_RUN_TIMEOUT\s*=\s*([0-9.]+)\s*$",
                                   RUN_CORRECTNESS_PY, float, "DEFAULT_RUN_TIMEOUT")
    primary_compiler = _extract(
        r'"--primary-compiler",\s*default="([^"]+)"', RUN_CORRECTNESS_PY, str,
        "primary compiler default")
    max_validation_attempts = _extract(
        r"^#define MAX_VALIDATION_ATTEMPTS\s+(\d+)\s*$", UTILITIES_HPP, int,
        "MAX_VALIDATION_ATTEMPTS")

    cfg = _load_yaml_config(config_path)
    stage = (cfg.get("stages") or {}).get("correctness_tests") or {}
    launch_overrides = stage.get("launch_overrides")

    per_model = {}
    ndebug_defined = False
    for pm in PM_CANON:
        bc = get_build_config(pm, primary_compiler=primary_compiler)
        # exactly the verdict-relevant flag set base_command() assembles,
        # in its original order (include dirs are paths - operational;
        # MISMATCH_REPORT_MAX is a diagnostic display cap - verdict-invariant;
        # both deliberately excluded)
        flags = ["-std=%s" % BASE_CXX_STANDARD, BASE_OPTIMIZATION]
        flags += list(bc.cxxflags)
        flags += ["-D%s" % bc.macro, "-DDRIVER_PROBLEM_SIZE=%s" % driver_problem_size]
        if any(f.startswith("-DNDEBUG") for f in flags):
            ndebug_defined = True
        lc = get_launch_config(pm, overrides=launch_overrides)
        per_model[pm] = {
            "compiler": bc.compiler,
            "cxxflags": flags,
            "macro": bc.macro,
            "model_driver_file": bc.model_driver_file,
            "launch_params": lc.params,
            "launcher": ("direct; argv[1]=niter" if pm == "serial" else
                         "direct; argv[1]=num_threads; OMP_NUM_THREADS set; driver NITER fixed at 5" if pm == "omp" else
                         "mpirun -np <num_procs>; trailing argv=niter"),
        }

    return {
        "stage": "correctness_tests",
        "primary_compiler": primary_compiler,
        "per_execution_model": per_model,
        "ndebug_defined": ndebug_defined,
        "driver_problem_size": driver_problem_size,
        "niter": int(stage.get("niter", default_niter)),
        "max_validation_attempts": max_validation_attempts,
        "build_timeout_seconds": float(stage.get("build_timeout_seconds", default_build_timeout)),
        "run_timeout_seconds": float(stage.get("run_timeout_seconds", default_run_timeout)),
        "launch_overrides": launch_overrides,
    }


# ---------------------------------------------------------------------------
# assembly condition (candidate-source construction semantics)
# ---------------------------------------------------------------------------

def assembly_condition_projection():
    """The only config option that changes generated-code.hpp bytes is
    stages.assembly.auto_close_single_brace (read with default True by
    assemble_sources.py; cleaning.clean_for_assembly is a pure function of
    (prompt_text, raw_text) and reads no config). Other stages.assembly keys
    are either unconsumed by the assembler or location-/reporting-only and
    are deliberately excluded."""
    cfg = _load_yaml_config()
    stage = (cfg.get("stages") or {}).get("assembly") or {}
    return {
        "stage": "assembly",
        "auto_close_single_brace": bool(stage.get("auto_close_single_brace", True)),
    }


# ---------------------------------------------------------------------------
# effective invocation (repo-side reconstruction of the EXPECTED values)
# ---------------------------------------------------------------------------

def expected_invocation_values():
    """Re-derive the frozen expected values of the verdict-relevant CLI
    overrides from the current productive state. This validates only that
    the EXPECTED values are still reproducible - it does NOT validate any
    future actual invocation (that is the runtime preflight's job)."""
    primary_compiler = _extract(
        r'"--primary-compiler",\s*default="([^"]+)"', RUN_CORRECTNESS_PY, str,
        "primary compiler default")
    default_run_timeout = _extract(r"^DEFAULT_RUN_TIMEOUT\s*=\s*([0-9.]+)\s*$",
                                   RUN_CORRECTNESS_PY, float, "DEFAULT_RUN_TIMEOUT")
    cfg = _load_yaml_config()
    stage = (cfg.get("stages") or {}).get("correctness_tests") or {}
    return {
        "primary_compiler": primary_compiler,
        "run_timeout_seconds": float(stage.get("run_timeout_seconds", default_run_timeout)),
    }


# ---------------------------------------------------------------------------
# environment condition (repo-side validation of recorded provenance)
# ---------------------------------------------------------------------------

def environment_provenance_check(expected):
    """Repo-side check that the stored expected environment values are still
    derivable from the frozen pilot_001 toolchain provenance and that the
    Dockerfile pinning classification still holds. Returns a list of
    (label, status, detail) with status in {ok, STALE, UNRESOLVED}. The
    ACTUAL runtime environment can NOT be validated here - that requires the
    runtime preflight."""
    results = []
    if not TOOLCHAIN_PROVENANCE.is_file():
        results.append(("toolchain provenance file", "UNRESOLVED",
                        "%s missing" % TOOLCHAIN_PROVENANCE))
    else:
        text = TOOLCHAIN_PROVENANCE.read_text(encoding="utf-8", errors="replace")
        for label, needle in (
                ("primary_compiler_version", expected.get("primary_compiler_version")),
                ("mpi_version_line", expected.get("mpi_version_line"))):
            if not needle:
                results.append((label, "UNRESOLVED", "no expected value stored"))
            elif needle in text:
                results.append((label, "ok", ""))
            else:
                results.append((label, "STALE",
                                "expected %r not found in frozen toolchain provenance" % needle))
    container = expected.get("container") or {}
    if not DOCKERFILE.is_file():
        results.append(("dockerfile", "UNRESOLVED", "%s missing" % DOCKERFILE))
    else:
        dtext = DOCKERFILE.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^FROM\s+(\S+)", dtext, re.MULTILINE)
        base = m.group(1) if m else None
        if base != container.get("base_image"):
            results.append(("container base image", "STALE",
                            "Dockerfile FROM %r != stored %r" % (base, container.get("base_image"))))
        else:
            results.append(("container base image", "ok", ""))
        digest_pinned = bool(m and "@sha256:" in m.group(1))
        stored_pinning = container.get("pinning")
        current_pinning = "DIGEST_PINNED" if digest_pinned else "TAG_ONLY"
        if stored_pinning != current_pinning:
            results.append(("container pinning classification", "STALE",
                            "stored %r != current %r" % (stored_pinning, current_pinning)))
        else:
            results.append(("container pinning classification", "ok",
                            "[%s]" % current_pinning))
    return results


# ---------------------------------------------------------------------------
# benchmark-local state (unchanged rules)
# ---------------------------------------------------------------------------

def sha256_file_bytes(path: Path):
    """Raw-byte hash; None if the file does not exist."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_prompt_hashes():
    """(problem_type, name, parallelism_model) -> sha256(utf-8 prompt)."""
    entries = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    out = {}
    for e in entries:
        key = (e["problem_type"], e["name"], e["parallelism_model"])
        out[key] = hashlib.sha256(e["prompt"].encode("utf-8")).hexdigest()
    return out


def enhanced_spec_hash(benchmark: str):
    """Canonical benchmark-local spec projection hash; None if the specs file
    is absent. An empty projection (no lines for the benchmark) hashes the
    empty string - a stable, meaningful state of its own."""
    path = SPECS_PATH if SPECS_PATH.is_file() else SPECS_PATH_LEGACY_CACHE
    if not path.is_file():
        return None
    lines = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.rstrip("\r\n")
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except ValueError:
                continue
            if obj.get("benchmark") == benchmark:
                lines.append(stripped)
    lines.sort()
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def recompute_state(benchmark: str):
    """Recompute all benchmark-local fingerprints for one
    '<problem_type>/<name>' id."""
    pt, name = benchmark.split("/", 1)
    bench_dir = BENCH_ROOT / pt / name
    prompt_hashes = load_prompt_hashes()
    prompts = {}
    for pm in PM_CANON:
        prompts[pm] = prompt_hashes.get((pt, name, pm))
    return {
        "benchmark": benchmark,
        "cpu_cc_sha256": sha256_file_bytes(bench_dir / "cpu.cc"),
        "baseline_hpp_sha256": sha256_file_bytes(bench_dir / "baseline.hpp"),
        "prompt_sha256": prompts,
        "enhanced_spec_keys_sha256": enhanced_spec_hash(benchmark),
    }


# ---------------------------------------------------------------------------
# comparison driver
# ---------------------------------------------------------------------------

def self_fingerprint_line(artifact):
    """Cross-pilot reevaluation: the artifact carries its OWN content
    fingerprint, so a hand-edit that skips recomputation is detected instead of
    passing silently. Rule (also stored in the artifact): canon_sha256 over the
    parsed file content with the two fingerprint fields removed."""
    stored = artifact.get("cross_pilot_fingerprint_sha256")
    if stored is None:
        return "ARTIFACT_SELF_FINGERPRINT\n  absent (pre-reevaluation artifact)"
    body = {k: v for k, v in artifact.items()
            if k not in ("cross_pilot_fingerprint_sha256",
                         "cross_pilot_fingerprint_rule")}
    current = canon_sha256(body)
    if current == stored:
        return "ARTIFACT_SELF_FINGERPRINT\n  %s: ok" % current
    return ("ARTIFACT_SELF_FINGERPRINT\n  MISMATCH (stored %s... != current "
            "%s...)" % (stored[:12], current[:12]))


def main() -> int:
    if not GATE_PATH.is_file():
        print("ERROR: gate artifact missing: %s" % GATE_PATH)
        return 2

    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))
    stored_states = gate.get("candidate_subset_state", [])
    if not stored_states:
        print("ERROR: gate artifact has no candidate_subset_state")
        return 2

    stale = False
    unresolved = False

    print("BENCHMARK_LOCAL_STATE")
    for stored in stored_states:
        bench = stored["benchmark"]
        current = recompute_state(bench)
        for field in ("cpu_cc_sha256", "baseline_hpp_sha256",
                      "enhanced_spec_keys_sha256"):
            old, new = stored.get(field), current[field]
            if old is None:
                print("  %s %s: stored null (unavailable at creation) - skipped"
                      % (bench, field))
                continue
            if new is None:
                print("  %s %s: UNRESOLVED (source no longer addressable)"
                      % (bench, field))
                unresolved = True
            elif old != new:
                print("  %s %s: STALE (stored %s... != current %s...)"
                      % (bench, field, old[:12], new[:12]))
                stale = True
            else:
                print("  %s %s: ok" % (bench, field))
        for pm in PM_CANON:
            old = (stored.get("prompt_sha256") or {}).get(pm)
            new = current["prompt_sha256"][pm]
            label = "%s prompt_sha256.%s" % (bench, pm)
            if old is None:
                print("  %s: stored null - skipped" % label)
            elif new is None:
                print("  %s: UNRESOLVED (identity no longer present)" % label)
                unresolved = True
            elif old != new:
                print("  %s: STALE" % label)
                stale = True
            else:
                print("  %s: ok" % label)

    shared = gate.get("shared_state") or {}

    print("SHARED_STATE")
    files = shared.get("files") or {}
    if not files:
        print("  UNRESOLVED (gate stores no shared_state.files)")
        unresolved = True
    for rel, entry in files.items():
        old = entry.get("sha256")
        gran = entry.get("granularity", "coarse")
        new = sha256_file_bytes(REPO_ROOT / rel)
        if old is None:
            print("  %s: stored null - skipped [granularity=%s]" % (rel, gran))
            continue
        if new is None:
            print("  %s: UNRESOLVED (file no longer addressable) [granularity=%s]"
                  % (rel, gran))
            unresolved = True
        elif old != new:
            if gran == "semantic":
                print("  %s: STALE [granularity=semantic] shared semantic "
                      "dependency changed" % rel)
            else:
                print("  %s: STALE [granularity=coarse] coarse shared "
                      "dependency changed; inspect whether the diff affects "
                      "verdict semantics (a coarse diff is NOT proof of a "
                      "semantic change)" % rel)
            stale = True
        else:
            print("  %s: ok [granularity=%s]" % (rel, gran))

    print("GENERATION_CONDITION")
    gc = shared.get("generation_condition") or {}
    old = gc.get("sha256")
    if old is None:
        print("  UNRESOLVED (gate stores no generation_condition.sha256)")
        unresolved = True
    else:
        try:
            new = canon_sha256(generation_condition_projection())
            if old != new:
                print("  STALE (stored %s... != current %s...)" % (old[:12], new[:12]))
                stale = True
            else:
                print("  ok")
        except ConditionUnresolved as exc:
            print("  UNRESOLVED (%s)" % exc)
            unresolved = True

    print("EVALUATION_CONDITION")
    ec = shared.get("evaluation_condition") or {}
    old = ec.get("sha256")
    if old is None:
        print("  UNRESOLVED (gate stores no evaluation_condition.sha256)")
        unresolved = True
    else:
        try:
            new = canon_sha256(evaluation_condition_projection())
            if old != new:
                print("  STALE (stored %s... != current %s...)" % (old[:12], new[:12]))
                stale = True
            else:
                print("  ok")
        except ConditionUnresolved as exc:
            print("  UNRESOLVED (%s)" % exc)
            unresolved = True

    print("ASSEMBLY_STATE")
    asm = gate.get("assembly_state") or {}
    afiles = asm.get("files") or {}
    if not afiles:
        print("  UNRESOLVED (gate stores no assembly_state.files)")
        unresolved = True
    for rel, entry in afiles.items():
        old = entry.get("sha256")
        gran = entry.get("granularity", "coarse")
        new = sha256_file_bytes(REPO_ROOT / rel)
        if old is None:
            print("  %s: stored null - skipped [granularity=%s]" % (rel, gran))
            continue
        if new is None:
            print("  %s: UNRESOLVED (file no longer addressable) [granularity=%s]"
                  % (rel, gran))
            unresolved = True
        elif old != new:
            if gran == "semantic":
                print("  %s: STALE [granularity=semantic] assembly transformation "
                      "semantics dependency changed" % rel)
            else:
                print("  %s: STALE [granularity=coarse] coarse assembly dependency "
                      "changed; inspect whether the diff affects the candidate-source "
                      "construction (a coarse diff is NOT proof of a semantic change)"
                      % rel)
            stale = True
        else:
            print("  %s: ok [granularity=%s]" % (rel, gran))
    acond = asm.get("condition") or {}
    old = acond.get("sha256")
    if old is None:
        print("  assembly_condition: UNRESOLVED (no sha256 stored)")
        unresolved = True
    else:
        try:
            new = canon_sha256(assembly_condition_projection())
            if old != new:
                print("  assembly_condition: STALE (stored %s... != current %s...)"
                      % (old[:12], new[:12]))
                stale = True
            else:
                print("  assembly_condition: ok")
        except ConditionUnresolved as exc:
            print("  assembly_condition: UNRESOLVED (%s)" % exc)
            unresolved = True

    print("EFFECTIVE_INVOCATION_POLICY")
    pol = gate.get("effective_invocation_policy") or {}
    overrides = pol.get("verdict_relevant_cli_overrides") or {}
    if not overrides:
        print("  UNRESOLVED (gate stores no verdict_relevant_cli_overrides)")
        unresolved = True
    else:
        try:
            current = expected_invocation_values()
            for key in ("primary_compiler", "run_timeout_seconds"):
                stored_exp = (overrides.get(key) or {}).get("expected")
                if stored_exp is None:
                    print("  %s: UNRESOLVED (no expected value stored)" % key)
                    unresolved = True
                elif stored_exp != current[key]:
                    print("  %s: STALE (stored expected %r no longer matches the "
                          "productive default/config value %r)"
                          % (key, stored_exp, current[key]))
                    stale = True
                else:
                    print("  %s: ok (expected %r reproducible from repo state)"
                          % (key, stored_exp))
        except ConditionUnresolved as exc:
            print("  UNRESOLVED (%s)" % exc)
            unresolved = True
    print("  EFFECTIVE_INVOCATION_RUNTIME_CHECK = REQUIRED (this repo-side check"
          " validates only the frozen EXPECTED values; a future actual CLI"
          " invocation is NOT validated here - run"
          " thesis/evaluation/pilot_preflight.py before pilot_002)")

    print("ENVIRONMENT_CONDITION")
    env = gate.get("environment_condition") or {}
    expected_env = env.get("expected") or {}
    if not expected_env:
        print("  UNRESOLVED (gate stores no environment_condition.expected)")
        unresolved = True
    else:
        for label, status, detail in environment_provenance_check(expected_env):
            print("  %s: %s%s" % (label, status, (" " + detail if detail else "")))
            if status == "STALE":
                stale = True
            elif status == "UNRESOLVED":
                unresolved = True
    print("  ENVIRONMENT_RUNTIME_CHECK = REQUIRED (repo-side provenance only;"
          " the actual runtime environment - compiler/MPI versions, container"
          " image digest/ID - must be captured and compared by the pilot"
          " preflight before pilot_002)")

    print(self_fingerprint_line(gate))

    if stale:
        print("\nCROSS_PILOT_REPO_STATE_STALE = true")
        print("CROSS_PILOT_GATE_STALE = true")
        print("-> comparability_re_evaluation_required (a hash diff does not"
              " by itself produce a new comparability classification, a new"
              " candidate subset, or new cell counts)")
        return 1
    if unresolved:
        print("\nCROSS_PILOT_REPO_STATE_STALE = UNRESOLVED")
        print("CROSS_PILOT_GATE_STALE = UNRESOLVED")
        return 2
    if "MISMATCH" in self_fingerprint_line(gate):
        print("\nCROSS_PILOT_REPO_STATE_STALE = UNRESOLVED")
        print("CROSS_PILOT_GATE_STALE = UNRESOLVED (the artifact's own"
              " fingerprint does not reproduce - it was edited without"
              " recomputation)")
        return 2
    print("\nCROSS_PILOT_REPO_STATE_STALE = false")
    print("CROSS_PILOT_GATE_STALE = false (repo-state check; the RUNTIME"
          " condition match - effective invocation and actual environment -"
          " is determined separately by thesis/evaluation/pilot_preflight.py"
          " and is REQUIRED before pilot_002)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
