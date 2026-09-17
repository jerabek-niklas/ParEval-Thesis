"""pilot_002 population + final methodology / run freeze (2026-09-13).

Deterministic, content-addressed freeze artifacts of the pilot_002 base run
and the verifiers the contract builder, the preflight and the post-run
verifier apply to them:

    pilot_002_population.json          pilot_002_population.v1
    pilot_002_publication_policy.json  pilot_002_publication_policy.v1
    pilot_002_methodology_freeze.json  pilot_002_methodology_freeze.v1
    pilot_002_run_freeze_receipt.json  pilot_002_run_freeze_receipt.v1

Acyclic hash order (no artifact hashes something that hashes it back):

    population  ->  publication policy  ->  cross_pilot_comparability.json
    (binds population + publication shas, reuse decision, base run; refers to
    the methodology freeze by PATH only)  ->  methodology freeze (binds the
    population sha, the publication sha, the cross-pilot fingerprint and every
    condition sha)  ->  run contract (binds the methodology sha, the population
    sha, the publication sha, the cross-pilot sha)  ->  run freeze receipt
    (records the contract sha - it is never hashed back into an input).

The population is an EXPLICIT AUTHOR DECISION (PILOT_002_AUTHOR_FREEZE): the
builder reproduces it with the productive selection logic
(thesis.generation.common.select_prompts) and refuses with
BLOCKED_POPULATION_SELECTION_DRIFT when the current config does not
reproduce exactly that population. That it coincides with the historical
pilot_001 population is a consequence of the same "one benchmark per problem
type" pilot methodology - pilot_001 is never the source of authority
(historical_population_used_as_source = false).

Python 3.8 compatible (imported inside the analysis containers).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import condition_hashing as ch  # noqa: E402

# ---------------------------------------------------------------------------
# schema / policy literals
# ---------------------------------------------------------------------------

POPULATION_SCHEMA = "pilot_002_population.v1"
PUBLICATION_POLICY_SCHEMA = "pilot_002_publication_policy.v1"
METHODOLOGY_FREEZE_SCHEMA = "pilot_002_methodology_freeze.v1"
RUN_FREEZE_RECEIPT_SCHEMA = "pilot_002_run_freeze_receipt.v1"
# written by a LATER author wave after verify_pilot_run = PASS; this module
# only defines the shape the publication gate expects
RESULT_ACCEPTANCE_SCHEMA = "pilot_002_result_acceptance.v1"

PILOT_002_RUN_ID = "pilot_002"
PILOT_002_PROFILE = "pilot"
HISTORICAL_PILOT_RUN_ID = "pilot_001"

REUSE_POLICY = "NO_PILOT001_MEASUREMENT_REUSE"
REUSE_STATUS_DECIDED = "DECIDED_NO_REUSE"
PUBLICATION_POLICY = "POST_RUN_ACCEPTED_RESULTS_ONLY"
GLOBAL_OVERRIDE_POLICY = "METHODICAL_OVERRIDES_ALLOWED_ONLY_IF_DECLARED_AND_PINNED"
PLANNED_METHODICAL_OVERRIDES = "NONE"
POPULATION_SOURCE = "EXPLICIT_AUTHOR_FREEZE"

STATUS_DECIDED = "DECIDED"
STATUS_CONFIGURED = "CONFIGURED"
FRESH = "FRESH"
STALE = "STALE"
MISSING = "MISSING"
MALFORMED = "MALFORMED"

SHA_RULE = ("condition_hashing.canonical_sha256 (json.dumps sort_keys=True, "
            "separators=(',',':'), ensure_ascii=True, default=str; SHA-256 over UTF-8) of the "
            "document with the fields `volatile` and the self-hash field removed")

# CLI selectors that address WHERE / WHICH SCOPE a contracted invocation runs
# without changing what is measured. They are bound in the invocation
# provenance (owner = stage@model@tools-..., variant of the repair loop) and
# are the only CLI-sourced effective values a plan of NONE admits.
OPERATIONAL_SCOPE_FIELDS = ("tools", "variant")
ALLOWED_OPERATIONAL_SELECTORS = OrderedDict([
    ("--run-id", "addresses the contracted base run (authorize_start and the post-run "
                 "verifier refuse any other run id)"),
    ("--profile", "selects the frozen profile (pilot); its values are contract-pinned"),
    ("--model-id", "per-model scope of a contract-derived split-container static run or a "
                   "per-model resume; bound as model_scope of the invocation fragment and "
                   "refused for a model outside the contract; a FIRST START that narrows the "
                   "contracted model set is refused (generate.py)"),
    ("--tools", "contract-derived PARCOACH / LLOV container invocations (static.parcoach / "
                "static.llov); bound as the invocation owner, covered per model by the "
                "split-invocation matrix"),
    ("--poll", "collects an already authorized batch job; never authorizes, never submits"),
    ("--max-wave", "bounds how many repair waves ONE invocation advances; the loop's persisted state "
                   "machine continues on the next invocation and the post-run repair-scope check "
                   "verifies the final state (every contracted loop terminal), so the bound changes "
                   "no methodical value"),
    ("PAREVAL_HOST_REPO / stages.repair.host_repo_path",
     "operational bind-mount path of the analysis containers; part of no condition hash "
     "and of no invocation fragment"),
])

# ---------------------------------------------------------------------------
# the explicit author decision (wave contract 2026-09-13)
# ---------------------------------------------------------------------------

PILOT_002_BENCHMARKS = (
    "dense_la/00_dense_la_lu_decomp",
    "fft/05_fft_inverse_fft",
    "geometry/10_geometry_convex_hull",
    "graph/15_graph_edge_count",
    "histogram/20_histogram_pixel_histogram",
    "reduce/25_reduce_xor",
    "scan/30_scan_prefix_sum",
    "search/35_search_search_for_last_struct_by_key",
    "sort/40_sort_sort_an_array_of_complex_numbers_by_magnitude",
    "sparse_la/45_sparse_la_sparse_solve",
    "stencil/50_stencil_xor_kernel",
    "transform/55_transform_relu",
)
PILOT_002_MODEL_IDS = (
    "claude_fable_5", "claude_opus_5", "deepseek_v4_flash", "deepseek_v4_pro",
    "gemini_31_pro", "gemini_36_flash", "openai_gpt55", "openai_gpt56_sol",
    "qwen36_35b_a3b", "qwen37_max", "qwen3_coder_api",
)
PILOT_002_EXECUTION_MODELS = ("serial", "omp", "mpi")


def pilot_002_author_freeze() -> "OrderedDict[str, Any]":
    return OrderedDict([
        ("source", POPULATION_SOURCE),
        ("decided_on", "2026-09-13"),
        ("decided_by", "author (wave contract: PILOT_002 POPULATION + FINAL METHODOLOGY/RUN FREEZE)"),
        ("run_id", PILOT_002_RUN_ID),
        ("profile", PILOT_002_PROFILE),
        ("selection", "stratified"),
        ("benchmark_count", len(PILOT_002_BENCHMARKS)),
        ("prompt_count", len(PILOT_002_BENCHMARKS) * len(PILOT_002_EXECUTION_MODELS)),
        ("samples_per_prompt", 1),
        ("execution_models", list(PILOT_002_EXECUTION_MODELS)),
        ("model_count", len(PILOT_002_MODEL_IDS)),
        ("benchmarks", list(PILOT_002_BENCHMARKS)),
        ("model_ids", sorted(PILOT_002_MODEL_IDS)),
        ("rationale", "exactly ONE benchmark from each of the 12 problem classes, each with all "
                      "three execution models (one-benchmark-per-problem-type pilot "
                      "methodology). The population is decided HERE; that it equals the "
                      "historical 12-benchmark pilot is a consequence of the same methodology, "
                      "not its justification."),
        ("historical_population_used_as_source", False),
    ])


def fixture_author_freeze(config: Dict[str, Any], profile_name: str,
                          decided_by: str = "fixture author") -> "OrderedDict[str, Any]":
    """FIXTURES ONLY: an author-freeze block derived from the fixture's own
    current selection (the test author decides its population). The
    productive pilot_002 freeze is the literal PILOT_002_AUTHOR_FREEZE above,
    never derived from a selection - a fixture block is refused for the
    productive run id."""
    body = population_body(config, profile_name, None)
    if body["run_id"] == PILOT_002_RUN_ID:
        raise PopulationSelectionDrift(
            "%s: the productive run %s takes its population from the author literal "
            "(pilot_002_author_freeze), never from a selection-derived fixture block"
            % (PopulationSelectionDrift.code, PILOT_002_RUN_ID))
    return OrderedDict([
        ("source", POPULATION_SOURCE),
        ("decided_on", "fixture"),
        ("decided_by", decided_by),
        ("run_id", body["run_id"]),
        ("profile", profile_name),
        ("selection", body["selection"]),
        ("benchmark_count", body["benchmark_count"]),
        ("prompt_count", body["prompt_count"]),
        ("samples_per_prompt", body["samples_per_prompt"]),
        ("execution_models", sorted({m for models in body["execution_models_by_benchmark"].values()
                                     for m in models})),
        ("model_count", body["model_count"]),
        ("benchmarks", list(body["benchmark_ids"])),
        ("model_ids", list(body["model_ids"])),
        ("rationale", "fixture population, decided by the test"),
        ("historical_population_used_as_source", False),
    ])


# ---------------------------------------------------------------------------
# paths (config seam `outputs.freeze_artifacts` for fixtures)
# ---------------------------------------------------------------------------

DEFAULT_PATHS = OrderedDict([
    ("population", REPO_ROOT / "thesis" / "evaluation" / "pilot_002_population.json"),
    ("publication_policy", REPO_ROOT / "thesis" / "evaluation" / "pilot_002_publication_policy.json"),
    ("methodology_freeze", REPO_ROOT / "thesis" / "evaluation" / "pilot_002_methodology_freeze.json"),
    ("run_freeze_receipt", REPO_ROOT / "thesis" / "evaluation" / "pilot_002_run_freeze_receipt.json"),
    ("result_acceptance", REPO_ROOT / "thesis" / "evaluation" / "pilot_002_result_acceptance.json"),
])
CROSS_PILOT_PATH = REPO_ROOT / "thesis" / "evaluation" / "cross_pilot_comparability.json"
SEMANTIC_DECISIONS_PATH = REPO_ROOT / "thesis" / "evaluation" / "semantic_decisions_pilot002.json"
PROMPT_ORACLE_INTERLOCK_PATH = REPO_ROOT / "thesis" / "evaluation" / "prompt_oracle_interlock.json"
E3_2_CONFIRMATION_PATH = REPO_ROOT / "thesis" / "evaluation" / "e3_2_author_confirmation.json"
E3_2_DECISIONS_PATH = REPO_ROOT / "thesis" / "evaluation" / "e3_2_decisions.json"
TECHNICAL_PROVENANCE_PATH = REPO_ROOT / "thesis" / "evaluation" / "technical_provenance_cleanup.json"
READINESS_PATH = REPO_ROOT / "thesis" / "evaluation" / "static_repair_readiness.json"
FROZEN_SPECS_PATH = REPO_ROOT / "thesis" / "enhanced_tests" / "frozen" / "e3_final_specs.jsonl"
ENHANCED_POLICY_PATH = REPO_ROOT / "thesis" / "enhanced_tests" / "enhanced_policy.json"


def freeze_paths(config: "Optional[Dict[str, Any]]") -> "OrderedDict[str, Path]":
    """The freeze artifact locations. Production reads the repository files;
    a fixture pins its own through config `outputs.freeze_artifacts`
    (the same seam pattern as `outputs.readiness_artifact`)."""
    seam = (((config or {}).get("outputs") or {}).get("freeze_artifacts") or {})
    paths = OrderedDict()
    for key, default in DEFAULT_PATHS.items():
        value = seam.get(key)
        paths[key] = Path(value) if value else default
    return paths


def cross_pilot_path(config: "Optional[Dict[str, Any]]") -> Path:
    """The cross-pilot gate artifact; fixtures pin their own through
    `outputs.cross_pilot_artifact`."""
    seam = (((config or {}).get("outputs") or {}).get("cross_pilot_artifact"))
    return Path(seam) if seam else CROSS_PILOT_PATH


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class PopulationSelectionDrift(RuntimeError):
    """The current productive selection does not reproduce the author-frozen
    population (BLOCKED_POPULATION_SELECTION_DRIFT)."""

    code = "BLOCKED_POPULATION_SELECTION_DRIFT"


def _load_json(path: Path) -> "Optional[Any]":
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    except (OSError, ValueError):
        return None


def _utc_now() -> str:
    from thesis.generation.common import utc_now_iso

    return utc_now_iso()


def document_sha256(document: Dict[str, Any], self_field: str) -> str:
    body = OrderedDict((k, v) for k, v in document.items() if k not in ("volatile", self_field))
    return ch.canonical_sha256(body)


def recompute_self_hash(document: Any, self_field: str,
                        exclude: "Tuple[str, ...]" = ("volatile",)) -> "Optional[str]":
    """The self-hash a pinned artifact SHOULD carry, recomputed from its
    content: canonical JSON (sort_keys, compact separators, default=str) of
    the document minus `exclude` and the self field, SHA-256 over UTF-8.
    The repository artifacts use either ensure_ascii variant; the stored
    value reproduces under exactly one of them, so both are tried and the
    reproducing one is returned - None when neither reproduces (edited
    without recomputation) or when the document is not an object."""
    if not isinstance(document, dict):
        return None
    stored = document.get(self_field)
    body = OrderedDict((k, v) for k, v in document.items() if k not in exclude and k != self_field)
    for ensure_ascii in (True, False):
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=ensure_ascii, default=str)
                                .encode("utf-8")).hexdigest()
        if digest == stored:
            return digest
    return None


def cross_pilot_fingerprint(document: Any) -> "OrderedDict[str, Any]":
    """The cross-pilot artifact's self-fingerprint, recomputed under its own
    rule (check_cross_pilot_gate.self_fingerprint_line: canon_sha256 of the
    parsed content minus cross_pilot_fingerprint_sha256 /
    cross_pilot_fingerprint_rule; ensure_ascii=False)."""
    if not isinstance(document, dict):
        return OrderedDict([("stored", None), ("recomputed", None), ("reproduces", False)])
    body = OrderedDict((k, v) for k, v in document.items()
                       if k not in ("cross_pilot_fingerprint_sha256", "cross_pilot_fingerprint_rule"))
    recomputed = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False).encode("utf-8")).hexdigest()
    stored = document.get("cross_pilot_fingerprint_sha256")
    return OrderedDict([("stored", stored), ("recomputed", recomputed),
                        ("reproduces", stored == recomputed)])


def pinned_artifact(path: Path, self_field: str) -> "OrderedDict[str, Any]":
    """Load a pinned artifact and recompute its self-hash: the pin a
    contract binds is the RECOMPUTED value (None when the stored one does
    not reproduce, which the builder turns into a blocker)."""
    document = _load_json(path)
    stored = document.get(self_field) if isinstance(document, dict) else None
    recomputed = recompute_self_hash(document, self_field) if document is not None else None
    return OrderedDict([("document", document if isinstance(document, dict) else None),
                        ("stored", stored), ("recomputed", recomputed),
                        ("reproduces", recomputed is not None and recomputed == stored),
                        ("present", document is not None)])


def _write(path: Path, document: Dict[str, Any]) -> None:
    atomic_io.atomic_write_json(Path(path), document)


def prompt_key(entry: Dict[str, Any]) -> str:
    return "%s|%s|%s" % (entry.get("problem_type"), entry.get("name"),
                         entry.get("parallelism_model"))


def benchmark_id(entry: Dict[str, Any]) -> str:
    return "%s/%s" % (entry.get("problem_type"), entry.get("name"))


def _prompts_path(config: Dict[str, Any]) -> Path:
    prompts_cfg = config.get("prompts") or {}
    path = Path(prompts_cfg.get("path") or "thesis/prompts/generation-prompts-thesis.json")
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def enabled_model_ids(config: Dict[str, Any]) -> "List[str]":
    return sorted(str(m.get("id")) for m in (config.get("models") or []) if m.get("enabled", False))


def _model_view(model: Dict[str, Any]) -> "OrderedDict[str, Any]":
    """One model entry minus price keys (the generation-condition projection
    rule) - no secret VALUES are stored anywhere in the config (only env var
    names)."""
    skip = ("price_per_mtok_in", "price_per_mtok_out")
    return OrderedDict((k, model[k]) for k in sorted(model) if k not in skip)


# ---------------------------------------------------------------------------
# population
# ---------------------------------------------------------------------------

def population_body(config: Dict[str, Any], profile_name: str,
                    author_freeze: "Optional[Dict[str, Any]]",
                    config_path: "Optional[Path]" = None) -> "OrderedDict[str, Any]":
    """The hashed body of the population artifact, derived with the PRODUCTIVE
    selection (common.select_prompts). Raises PopulationSelectionDrift when
    `author_freeze` is given and the current selection does not reproduce
    it exactly (benchmarks, prompt count, execution models per benchmark,
    samples per prompt, model set)."""
    from thesis.generation import common

    profile = common.get_profile(config, profile_name)
    prompts_cfg = config.get("prompts") or {}
    prompts_path = _prompts_path(config)
    prompts = _load_json(prompts_path)
    if not isinstance(prompts, list):
        raise PopulationSelectionDrift("prompt file missing or not a list: %s" % prompts_path)
    execution_models = list(prompts_cfg.get("execution_models") or [])
    problem_types = prompts_cfg.get("problem_types")
    prompt_limit = profile.get("prompt_limit")
    selection = profile.get("selection", "prefix")
    samples_per_prompt = int(profile.get("num_samples_per_prompt") or 0)
    prompt_field = prompts_cfg.get("prompt_field", "prompt")

    selected, notes = common.select_prompts(prompts, execution_models, problem_types,
                                            prompt_limit, selection)
    selected_sorted = sorted(selected, key=prompt_key)
    keys = [prompt_key(e) for e in selected_sorted]
    hashes = OrderedDict((prompt_key(e), ch.utf8_sha256(e.get(prompt_field) or ""))
                         for e in selected_sorted)
    benchmarks = sorted({benchmark_id(e) for e in selected_sorted})
    by_type = OrderedDict()
    exec_by_benchmark = OrderedDict()
    for entry in selected_sorted:
        by_type.setdefault(str(entry.get("problem_type")), [])
        if benchmark_id(entry) not in by_type[str(entry.get("problem_type"))]:
            by_type[str(entry.get("problem_type"))].append(benchmark_id(entry))
        exec_by_benchmark.setdefault(benchmark_id(entry), [])
        exec_by_benchmark[benchmark_id(entry)].append(str(entry.get("parallelism_model")))
    for bench in exec_by_benchmark:
        exec_by_benchmark[bench] = sorted(exec_by_benchmark[bench],
                                          key=lambda m: (execution_models.index(m)
                                                         if m in execution_models else 99, m))
    model_ids = enabled_model_ids(config)
    body = OrderedDict([
        ("schema_version", POPULATION_SCHEMA),
        ("run_id", profile.get("run_id")),
        ("profile", profile_name),
        ("population_source", POPULATION_SOURCE if author_freeze else "FIXTURE"),
        ("author_freeze", OrderedDict(author_freeze) if author_freeze else None),
        ("selection", selection),
        ("selection_algorithm", OrderedDict([
            ("function", "thesis.generation.common.select_prompts"),
            ("version_constant", None),
            ("description", "deterministic round-robin over sorted problem types, whole "
                            "benchmarks (all execution models per benchmark), no randomness; "
                            "bound here by its OUTPUT (exact keys and hashes)"),
            ("notes", [str(n) for n in (notes or [])]),
        ])),
        ("prompt_limit", prompt_limit),
        ("samples_per_prompt", samples_per_prompt),
        ("execution_models", execution_models),
        ("problem_types_filter", problem_types),
        ("benchmark_ids", benchmarks),
        ("problem_type_mapping", by_type),
        ("execution_models_by_benchmark", exec_by_benchmark),
        ("prompt_keys", keys),
        ("prompt_hashes", hashes),
        ("prompt_key_set_sha256", ch.canonical_sha256(keys)),
        ("prompt_set_sha256", ch.canonical_sha256(hashes)),
        ("model_ids", model_ids),
        ("benchmark_count", len(benchmarks)),
        ("prompt_count", len(keys)),
        ("model_count", len(model_ids)),
        ("total_model_prompt_cells", len(keys) * samples_per_prompt * len(model_ids)),
        ("source", OrderedDict([
            # the config FILE identity (path, LF-normalized sha) is recorded
            # under `volatile`: the population is bound by its content, the
            # methodical config content by the generation condition below
            ("generation_condition_sha256", _generation_condition_sha()),
            ("prompt_artifact_path", ch.repo_relative(prompts_path)),
            # LF-normalized: the committed content, not the machine's EOL
            # convention (git autocrlf checks the LF blob out as CRLF)
            ("prompt_artifact_sha256_lf_normalized", ch.lf_normalized_sha256(prompts_path)),
            ("prompt_field", prompt_field),
        ])),
        ("historical_population_used_as_source", False),
        ("sha_rule", SHA_RULE),
    ])
    if author_freeze:
        problems = _author_freeze_problems(body, author_freeze)
        if problems:
            raise PopulationSelectionDrift(
                "%s: the current productive selection does not reproduce the author-frozen "
                "population: %s" % (PopulationSelectionDrift.code, "; ".join(problems)))
    return body


def _author_freeze_problems(body: Dict[str, Any], author_freeze: Dict[str, Any]) -> "List[str]":
    problems = []
    expected_benchmarks = list(author_freeze.get("benchmarks") or [])
    if body["benchmark_ids"] != sorted(expected_benchmarks):
        missing = sorted(set(expected_benchmarks) - set(body["benchmark_ids"]))
        extra = sorted(set(body["benchmark_ids"]) - set(expected_benchmarks))
        problems.append("benchmarks differ (missing %s; unexpected %s)" % (missing, extra))
    if body["benchmark_count"] != author_freeze.get("benchmark_count"):
        problems.append("benchmark_count %s != %s" % (body["benchmark_count"],
                                                      author_freeze.get("benchmark_count")))
    if body["prompt_count"] != author_freeze.get("prompt_count"):
        problems.append("prompt_count %s != %s" % (body["prompt_count"],
                                                   author_freeze.get("prompt_count")))
    if body["samples_per_prompt"] != author_freeze.get("samples_per_prompt"):
        problems.append("samples_per_prompt %s != %s" % (body["samples_per_prompt"],
                                                         author_freeze.get("samples_per_prompt")))
    if body["selection"] != author_freeze.get("selection"):
        problems.append("selection %r != %r" % (body["selection"], author_freeze.get("selection")))
    expected_exec = list(author_freeze.get("execution_models") or [])
    observed_exec = sorted({m for models in body["execution_models_by_benchmark"].values()
                            for m in models})
    if observed_exec != sorted(expected_exec):
        problems.append("execution models present in the selection %s != authorized %s"
                        % (observed_exec, sorted(expected_exec)))
    for bench, models in body["execution_models_by_benchmark"].items():
        if sorted(models) != sorted(expected_exec):
            problems.append("%s misses execution models: %s" % (bench, models))
    types = body["problem_type_mapping"]
    for problem_type, benches in types.items():
        if len(benches) != 1:
            problems.append("problem type %s has %d benchmarks" % (problem_type, len(benches)))
    if len(types) != author_freeze.get("benchmark_count"):
        problems.append("%d problem types covered, expected %s" % (len(types),
                                                                   author_freeze.get("benchmark_count")))
    expected_models = sorted(author_freeze.get("model_ids") or [])
    if body["model_ids"] != expected_models:
        missing = sorted(set(expected_models) - set(body["model_ids"]))
        extra = sorted(set(body["model_ids"]) - set(expected_models))
        problems.append("enabled model set differs (missing %s; extra %s) - no substitution, "
                        "no degradation" % (missing, extra))
    if body["model_count"] != author_freeze.get("model_count"):
        problems.append("model_count %s != %s" % (body["model_count"], author_freeze.get("model_count")))
    if author_freeze.get("run_id") and body["run_id"] != author_freeze.get("run_id"):
        problems.append("profile run_id %r != %r" % (body["run_id"], author_freeze.get("run_id")))
    return problems


def pilot001_population_note(body: Dict[str, Any], config: "Optional[Dict[str, Any]]" = None
                             ) -> "OrderedDict[str, Any]":
    """READ-ONLY comparison with the historical pilot_001 population as
    recorded in the cross-pilot artifact - an observation, never a source."""
    cross = _load_json(cross_pilot_path(config))
    cross = cross if isinstance(cross, dict) else {}
    hist = cross.get("pilot_001_population") if isinstance(cross.get("pilot_001_population"), dict) else {}
    equal = None
    detail = "pilot_001 population not recorded in the cross-pilot artifact"
    if hist:
        hist_benchmarks = hist.get("benchmarks")
        hist_models = hist.get("models")
        hist_exec = hist.get("execution_models")
        hist_cells = hist.get("iteration0_cells")
        comparable = OrderedDict([
            ("benchmark_count", (hist_benchmarks if isinstance(hist_benchmarks, int)
                                 else len(hist_benchmarks or [])) == body["benchmark_count"]),
            ("model_count", (hist_models if isinstance(hist_models, int)
                             else len(hist_models or [])) == body["model_count"]),
            ("execution_models", ((sorted(hist_exec) == sorted(body["execution_models"]))
                                  if isinstance(hist_exec, list) else
                                  (hist_exec == len(body["execution_models"]))
                                  if isinstance(hist_exec, int) else None)),
            ("cells", hist_cells == body["total_model_prompt_cells"]),
            ("samples_per_cell", hist.get("samples_per_cell") == body["samples_per_prompt"]),
        ])
        equal = all(v for v in comparable.values() if v is not None)
        detail = "counts compared against cross_pilot_comparability.json pilot_001_population: %s" % (
            json.dumps(comparable))
    return OrderedDict([
        ("pilot001_population_equal", equal),
        ("equality_note", "%s. Equality is an OBSERVATION: the pilot_002 population was decided "
                          "explicitly by the author (population_source = %s); the historical "
                          "pilot_001 population was neither read as a source nor does its "
                          "equality grant any permission (reuse policy: %s)."
                          % (detail, POPULATION_SOURCE, REUSE_POLICY)),
        ("pilot001_population_used_as_authority", False),
    ])


def _generation_condition_sha() -> "Optional[str]":
    try:
        from thesis.evaluation.check_cross_pilot_gate import (canon_sha256,
                                                              generation_condition_projection)

        return canon_sha256(generation_condition_projection())
    except Exception:  # noqa: BLE001 - reported as None, the contract blocks on it
        return None


def build_population(config: Dict[str, Any], profile_name: str,
                     author_freeze: "Optional[Dict[str, Any]]",
                     config_path: "Optional[Path]" = None) -> "OrderedDict[str, Any]":
    body = population_body(config, profile_name, author_freeze, config_path)
    document = OrderedDict(body)
    document["population_sha256"] = document_sha256(document, "population_sha256")
    document["volatile"] = OrderedDict([
        ("generated_at_utc", _utc_now()),
        # the READ-ONLY comparison with the historical population is evidence
        # of the freeze moment, never part of the population identity (the
        # cross-pilot artifact binds this artifact's sha, not the reverse)
        ("pilot_001_comparison", pilot001_population_note(body, config)),
        ("config_path_at_freeze", ch.repo_relative(config_path) if config_path else None),
        ("config_sha256_lf_normalized_at_freeze",
         ch.lf_normalized_sha256(config_path) if config_path else None),
        ("prompt_artifact_raw_sha256_at_freeze", ch.raw_sha256(_prompts_path(config))),
    ])
    return document


def verify_population(document: "Optional[Dict[str, Any]]", config: Dict[str, Any],
                      profile_name: str, config_path: "Optional[Path]" = None
                      ) -> "OrderedDict[str, Any]":
    """FRESH when the artifact is internally consistent AND the current
    productive selection reproduces it exactly (keys, hashes, counts, model
    set); STALE/MALFORMED/MISSING otherwise - never a silent PASS."""
    problems: "List[str]" = []
    if document is None:
        return OrderedDict([("status", MISSING), ("problems", ["population artifact missing"])])
    if not isinstance(document, dict) or document.get("schema_version") != POPULATION_SCHEMA:
        return OrderedDict([("status", MALFORMED),
                            ("problems", ["not a %s document" % POPULATION_SCHEMA])])
    stored = document.get("population_sha256")
    if stored != document_sha256(document, "population_sha256"):
        problems.append("population_sha256 does not reproduce (edited without recomputation)")
    from thesis.evaluation.run_manifest import config_key_diff

    author = document.get("author_freeze")
    author = OrderedDict(author) if isinstance(author, dict) else None
    productive = document.get("run_id") == PILOT_002_RUN_ID
    if productive:
        # the AUTHOR LITERAL is the verification authority of the productive
        # run: the artifact's block must equal it and the current selection
        # must reproduce it (a self-consistent chain for another population
        # can never verify)
        literal = pilot_002_author_freeze()
        if json.loads(json.dumps(author)) != json.loads(json.dumps(literal)):
            problems.append("author_freeze block differs from the wave decision "
                            "(pilot_002_author_freeze)")
        author = literal
    try:
        # the rebuild uses the author block the artifact claims; every
        # deviation of the artifact from that rebuild is a problem
        current = population_body(config, profile_name, None, config_path)
    except PopulationSelectionDrift as exc:
        return OrderedDict([("status", STALE), ("problems", problems + [str(exc)])])
    if document.get("run_id") != current.get("run_id"):
        return OrderedDict([("status", STALE), ("problems", problems + [
            "population artifact is frozen for run %r, not %r" % (document.get("run_id"),
                                                                   current.get("run_id"))])])
    if author is not None:
        problems.extend(_author_freeze_problems(current, author))
    stored_body = OrderedDict((k, v) for k, v in document.items()
                              if k not in ("volatile", "population_sha256", "author_freeze",
                                           "population_source"))
    rebuilt_body = OrderedDict((k, v) for k, v in current.items()
                               if k not in ("author_freeze", "population_source"))
    drift = config_key_diff(json.loads(json.dumps(stored_body, default=str)),
                            json.loads(json.dumps(rebuilt_body, default=str)))
    for field in drift:
        problems.append("%s: frozen value differs from the current productive selection" % field)
    # the config file sha is recorded as evidence of the freeze moment, not
    # compared: the population identity is bound by its CONTENT (keys, hashes,
    # counts, model set); a comment / ordering edit of config.yaml does not
    # change it, a methodical edit shows up in the fields above
    if document.get("population_source") == POPULATION_SOURCE:
        if not author:
            problems.append("population_source claims %s but no author_freeze block is present"
                            % POPULATION_SOURCE)
        elif author.get("source") != POPULATION_SOURCE or \
                author.get("historical_population_used_as_source") is not False:
            problems.append("author_freeze block does not declare an explicit author freeze")
    elif productive:
        problems.append("population_source %r is not %s" % (document.get("population_source"),
                                                             POPULATION_SOURCE))
    if document.get("historical_population_used_as_source") is not False:
        problems.append("historical_population_used_as_source must be false")
    comparison = (document.get("volatile") or {}).get("pilot_001_comparison") \
        if isinstance(document.get("volatile"), dict) else None
    if not isinstance(comparison, dict) or comparison.get("pilot001_population_used_as_authority") is not False:
        problems.append("volatile.pilot_001_comparison must record pilot001_population_used_as_authority = false")
    return OrderedDict([("status", FRESH if not problems else STALE), ("problems", problems)])


# ---------------------------------------------------------------------------
# publication policy
# ---------------------------------------------------------------------------

def mandatory_disclosure_sources() -> "List[OrderedDict[str, Any]]":
    """Machine-readable disclosure requirements a publication of pilot_002
    results must carry. Each entry names the artifact and the field the
    requirement lives in; publication_decision() verifies that every source
    is present and readable."""
    e3 = ch.repo_relative(E3_2_CONFIRMATION_PATH)
    return [
        OrderedDict([("id", "semantic_disclosure_dense_la_00"),
                     ("artifact", ch.repo_relative(SEMANTIC_DECISIONS_PATH)),
                     ("field", "decisions[benchmark=dense_la/00_dense_la_lu_decomp].reporting_requirement"),
                     ("requirement", "per-benchmark disclosure BL-01 alongside every dense_la/00 result "
                                     "(false-FAIL possibility; aggregates marked as disclosure-bearing)")]),
        OrderedDict([("id", "prompt_oracle_interlock"),
                     ("artifact", ch.repo_relative(PROMPT_ORACLE_INTERLOCK_PATH)),
                     ("field", "interlocks[] (enforcement = disclosure_required)"),
                     ("requirement", "open grader conventions disclosed next to the affected results")]),
        OrderedDict([("id", "semantic_decisions_all_disclosure_states"),
                     ("artifact", ch.repo_relative(SEMANTIC_DECISIONS_PATH)),
                     ("field", "decisions[].status / decisions[].reporting_requirement"),
                     ("requirement", "every ACCEPTED_DISCLOSURE_REQUIRED_FOR_PILOT_002 decision is disclosed; "
                                     "unresolved_count must be 0")]),
        OrderedDict([("id", "e3_2_D1_infer_omp_scope_difference"), ("artifact", e3),
                     ("field", "disclosures.D1_infer_omp_coverage_scope"),
                     ("requirement", "Infer OpenMP scope difference between pilot_001 and pilot_002")]),
        OrderedDict([("id", "e3_2_D2_clang_tidy_pilot_001_location_limitation"), ("artifact", e3),
                     ("field", "disclosures.D2_clang_tidy_pilot_001_crlf_location_bug"),
                     ("requirement", "clang-tidy pilot_001 finding-location limitation")]),
        OrderedDict([("id", "e3_2_D3_gcc_analyzer_confidence_demotion_difference"), ("artifact", e3),
                     ("field", "disclosures.D3_gcc_analyzer_t1_t5_confidence_demotion"),
                     ("requirement", "gcc_analyzer confidence-demotion difference between pilots")]),
        OrderedDict([("id", "e3_2_D4_malloc_leak_demotion_scope"), ("artifact", e3),
                     ("field", "disclosures.D4_malloc_leak_demotion_scope"),
                     ("requirement", "malloc-leak demotion scope")]),
        OrderedDict([("id", "e3_2_D5_search_35_validation_attempt_exception"), ("artifact", e3),
                     ("field", "disclosures.D5_search_35_five_validation_attempts"),
                     ("requirement", "search/35 validation-attempt exception (numTries = 5, suite default 2)")]),
        OrderedDict([("id", "e3_2_D6_geometry_sentinel_size_zero_untested"), ("artifact", e3),
                     ("field", "disclosures.D6_geometry_sentinel_convention_size_zero_untested"),
                     ("requirement", "geometry sentinel convention, size-zero inputs untested")]),
        OrderedDict([("id", "e3_2_all_disclosures"), ("artifact", e3),
                     ("field", "disclosures.* (every key)"),
                     ("requirement", "every E3.2 author-confirmation disclosure is carried; author "
                                     "choices A/B/A/A/C/B/B/A are not reinterpreted")]),
        OrderedDict([("id", "cross_pilot_current_scope"),
                     ("artifact", ch.repo_relative(CROSS_PILOT_PATH)),
                     ("field", "candidate_subset / transport_effect / change_classes / "
                               "cross_pilot_reevaluation (CURRENT artifact only)"),
                     ("requirement", "every cross-pilot statement against pilot_001 uses only the "
                                     "CURRENT cross_pilot_comparability.json scope and counts")]),
    ]


def publication_policy_body(run_id: str = PILOT_002_RUN_ID) -> "OrderedDict[str, Any]":
    return OrderedDict([
        ("schema_version", PUBLICATION_POLICY_SCHEMA),
        ("run_id", run_id),
        ("status", STATUS_DECIDED),
        ("decided_on", "2026-09-13"),
        ("policy", PUBLICATION_POLICY),
        ("pilot_results_may_be_used_after_acceptance", True),
        ("pilot_results_must_be_labelled_as_pilot", True),
        ("pilot_label", "pilot_002 / Pilotexperiment (12 benchmarks x 3 execution models x 11 models, "
                        "1 sample per prompt)"),
        ("may_be_presented_as_full_60_benchmark_study", False),
        ("post_run_verification_required", True),
        ("post_run_verification_tool", "thesis/evaluation/verify_pilot_run.py (status PASS required)"),
        ("result_acceptance_required", True),
        ("result_acceptance_artifact", OrderedDict([
            ("path", ch.repo_relative(DEFAULT_PATHS["result_acceptance"])),
            ("schema_version", RESULT_ACCEPTANCE_SCHEMA),
            ("required_fields", ["status (ACCEPTED | REJECTED | PENDING)", "run_id",
                                 "post_run_verification_status", "post_run_verification_sha256",
                                 "frozen_contract_sha256", "decided_by", "decided_on"]),
            ("note", "written by a separate author wave AFTER verify_pilot_run = PASS; absent "
                     "or PENDING means publication_allowed = false"),
        ])),
        ("publication_allowed_before_result_acceptance", False),
        ("cross_pilot_claims_must_follow_current_artifact", True),
        ("cross_pilot_claims_source", ch.repo_relative(CROSS_PILOT_PATH)),
        ("no_numbers_from_prompt_memory_or_old_reports", True),
        ("mandatory_disclosure_sources", mandatory_disclosure_sources()),
        ("no_accepted_publication_without_required_disclosures", True),
        ("historical_records_may_not_be_mutated", True),
        ("historical_baseline", HISTORICAL_PILOT_RUN_ID),
        ("gate_function", "thesis.evaluation.pilot_freeze.publication_decision"),
        ("sha_rule", SHA_RULE),
    ])


def build_publication_policy(run_id: str = PILOT_002_RUN_ID) -> "OrderedDict[str, Any]":
    document = publication_policy_body(run_id)
    document["publication_policy_sha256"] = document_sha256(document, "publication_policy_sha256")
    document["volatile"] = OrderedDict([("generated_at_utc", _utc_now())])
    return document


def verify_publication_policy(document: "Optional[Dict[str, Any]]") -> "OrderedDict[str, Any]":
    problems: "List[str]" = []
    if document is None:
        return OrderedDict([("status", MISSING), ("problems", ["publication policy artifact missing"])])
    if not isinstance(document, dict) or document.get("schema_version") != PUBLICATION_POLICY_SCHEMA:
        return OrderedDict([("status", MALFORMED),
                            ("problems", ["not a %s document" % PUBLICATION_POLICY_SCHEMA])])
    if document.get("publication_policy_sha256") != document_sha256(document, "publication_policy_sha256"):
        problems.append("publication_policy_sha256 does not reproduce")
    from thesis.evaluation.run_manifest import config_key_diff

    stored_body = OrderedDict((k, v) for k, v in document.items()
                              if k not in ("volatile", "publication_policy_sha256"))
    rebuilt = publication_policy_body(str(document.get("run_id")))
    drift = config_key_diff(json.loads(json.dumps(stored_body, default=str)),
                            json.loads(json.dumps(rebuilt, default=str)))
    if drift:
        problems.append("publication policy differs from the code-canonical policy: %s" % ", ".join(drift))
    if not isinstance(document.get("run_id"), str) or not document.get("run_id"):
        problems.append("publication policy names no run id")
    if document.get("status") != STATUS_DECIDED:
        problems.append("status %r is not DECIDED" % document.get("status"))
    if document.get("policy") != PUBLICATION_POLICY:
        problems.append("policy %r is not %s" % (document.get("policy"), PUBLICATION_POLICY))
    for flag, expected in (("post_run_verification_required", True),
                           ("result_acceptance_required", True),
                           ("publication_allowed_before_result_acceptance", False),
                           ("pilot_results_must_be_labelled_as_pilot", True),
                           ("may_be_presented_as_full_60_benchmark_study", False),
                           ("cross_pilot_claims_must_follow_current_artifact", True),
                           ("historical_records_may_not_be_mutated", True),
                           ("no_accepted_publication_without_required_disclosures", True)):
        if document.get(flag) is not expected:
            problems.append("%s must be %s" % (flag, expected))
    if not document.get("mandatory_disclosure_sources"):
        problems.append("mandatory_disclosure_sources is empty")
    return OrderedDict([("status", FRESH if not problems else STALE), ("problems", problems)])


def _present(value: Any) -> bool:
    """A disclosure VALUE must carry content: None, '', {} and [] are absent."""
    if value is None or value is False:
        return False
    if isinstance(value, (str, dict, list)) and not value:
        return False
    return True


def _lookup_field(document: Any, field: str) -> bool:
    """Presence check of a dotted field path with the forms used above:
    `a.b.c`, `a[key=value].b` (the entry must CARRY key), `a[].b` (EVERY
    element must carry b), `a.*` (a non-empty object whose every value is
    present). Fail-closed: an empty path, a malformed selector or an absent
    / empty value is `False`."""
    field = field.replace(" ", "")
    if not field:
        return False
    nodes = [document]
    for part in field.split("."):
        if part.endswith("(everykey)"):
            part = part[:-len("(everykey)")]
        if not part:
            return False
        if part == "*":
            return all(isinstance(n, dict) and bool(n) and all(_present(v) for v in n.values())
                       for n in nodes)
        selector = None
        if "[" in part:
            if not part.endswith("]"):
                return False
            part, selector = part[:part.index("[")], part[part.index("[") + 1:-1]
        next_nodes = []
        for node in nodes:
            if not isinstance(node, dict) or part not in node:
                return False
            value = node[part]
            if selector is None:
                next_nodes.append(value)
                continue
            if not isinstance(value, list) or not value:
                return False
            if selector == "":
                next_nodes.extend(value)
                continue
            key, sep, wanted = selector.partition("=")
            if not sep:
                return False
            matches = [e for e in value if isinstance(e, dict) and key in e and str(e.get(key)) == wanted]
            if not matches:
                return False
            next_nodes.extend(matches)
        nodes = next_nodes
    return bool(nodes) and all(_present(n) for n in nodes)


def _source_requirement_problems(source_id: str, document: Any) -> "List[str]":
    """The machine-readable parts of a mandatory disclosure requirement that
    the artifact itself can prove (beyond the field being present)."""
    problems: "List[str]" = []
    if not isinstance(document, dict):
        return ["artifact is not a JSON object"]
    if source_id in ("semantic_disclosure_dense_la_00", "semantic_decisions_all_disclosure_states"):
        if document.get("unresolved_count") != 0:
            problems.append("semantic decisions unresolved_count is %r, must be 0"
                            % document.get("unresolved_count"))
        decisions = document.get("decisions")
        if not isinstance(decisions, list) or not decisions:
            problems.append("semantic decisions[] missing")
        else:
            for decision in decisions:
                if not isinstance(decision, dict) or not decision.get("status"):
                    problems.append("a semantic decision without a status")
                    break
            dense = [d for d in decisions if isinstance(d, dict)
                     and d.get("benchmark") == "dense_la/00_dense_la_lu_decomp"]
            if not dense:
                problems.append("dense_la/00 decision missing")
            elif dense[0].get("status") != "ACCEPTED_DISCLOSURE_REQUIRED_FOR_PILOT_002":
                problems.append("dense_la/00 decision status is %r, not "
                                "ACCEPTED_DISCLOSURE_REQUIRED_FOR_PILOT_002" % dense[0].get("status"))
            elif not _present(dense[0].get("reporting_requirement")):
                problems.append("dense_la/00 reporting_requirement is empty")
    if source_id == "prompt_oracle_interlock":
        meta = document.get("_meta") if isinstance(document.get("_meta"), dict) else {}
        if meta.get("enforcement") != "disclosure_required":
            problems.append("interlock registry enforcement is %r, not disclosure_required"
                            % meta.get("enforcement"))
        if not all(isinstance(e, dict) and e for e in (document.get("interlocks") or [])):
            problems.append("interlock entries must be non-empty objects")
    if source_id.startswith("e3_2_"):
        disclosures = document.get("disclosures")
        if not isinstance(disclosures, dict) or not disclosures:
            problems.append("E3.2 disclosures missing")
        elif not all(isinstance(v, dict) and v for v in disclosures.values()):
            problems.append("an E3.2 disclosure is empty")
        if document.get("E3_2_DECISION") != "ACCEPTED":
            problems.append("E3_2_DECISION is %r, not ACCEPTED" % document.get("E3_2_DECISION"))
    if source_id == "cross_pilot_current_scope":
        for key in ("candidate_subset", "transport_effect", "change_classes", "cross_pilot_reevaluation",
                    "classification", "statistical_caveats"):
            if not _present(document.get(key)):
                problems.append("cross-pilot artifact lacks %s" % key)
        if not cross_pilot_fingerprint(document)["reproduces"]:
            problems.append("cross-pilot artifact fingerprint does not reproduce (edited without "
                            "recomputation)")
    return problems


def disclosure_sources_state(policy: Dict[str, Any], repo_root: "Optional[Path]" = None
                             ) -> "List[OrderedDict[str, Any]]":
    """Every declared source: readable, EVERY listed field present with
    content, and the requirement's machine-readable parts satisfied."""
    root = Path(repo_root) if repo_root else REPO_ROOT
    states = []
    sources = policy.get("mandatory_disclosure_sources") if isinstance(policy, dict) else None
    if not isinstance(sources, list):
        return [OrderedDict([("id", "mandatory_disclosure_sources"), ("artifact", None), ("field", None),
                             ("artifact_readable", False), ("field_present", False),
                             ("problems", ["mandatory_disclosure_sources is not a list"])])]
    for source in sources:
        if not isinstance(source, dict) or not source.get("artifact") or not source.get("field"):
            states.append(OrderedDict([("id", (source or {}).get("id") if isinstance(source, dict) else None),
                                       ("artifact", None), ("field", None), ("artifact_readable", False),
                                       ("field_present", False),
                                       ("problems", ["malformed disclosure source (artifact / field missing)"])]))
            continue
        artifact = root / str(source.get("artifact"))
        document = _load_json(artifact)
        field = str(source.get("field") or "")
        fields = [f.strip() for f in field.split(" (")[0].split(" / ") if f.strip()]
        present = document is not None and bool(fields) and all(_lookup_field(document, f) for f in fields)
        problems = _source_requirement_problems(str(source.get("id")), document) if document is not None else []
        states.append(OrderedDict([
            ("id", source.get("id")), ("artifact", source.get("artifact")),
            ("field", field), ("artifact_readable", document is not None),
            ("field_present", bool(present)), ("problems", problems),
        ]))
    return states


def post_run_report_digest(report: Any) -> "Optional[str]":
    """THE digest a result acceptance names: canonical sha of the post-run
    verification report minus its own `publication` block (the block is
    derived from the gate and would otherwise hash itself)."""
    if not isinstance(report, dict):
        return None
    body = OrderedDict((k, v) for k, v in report.items() if k != "publication")
    return ch.canonical_sha256(body)


ACCEPTANCE_REQUIRED_FIELDS = ("status", "run_id", "post_run_verification_status",
                              "post_run_verification_sha256", "frozen_contract_sha256",
                              "decided_by", "decided_on")


def publication_decision(policy: "Optional[Dict[str, Any]]",
                         post_run_report: "Optional[Dict[str, Any]]",
                         acceptance: "Optional[Dict[str, Any]]",
                         repo_root: "Optional[Path]" = None,
                         contract: "Optional[Dict[str, Any]]" = None) -> "OrderedDict[str, Any]":
    """THE publication gate (POST_RUN_ACCEPTED_RESULTS_ONLY). Fail-closed:
    publication_allowed is true only with a DECIDED, code-canonical policy,
    a post-run verification report with status PASS and no FAIL/UNRESOLVED
    counts, a result acceptance ACCEPTED that carries every required field,
    names THAT report (post_run_report_digest), THIS run and THIS contract,
    and every mandatory disclosure source present, contentful and (with a
    contract) unchanged since the freeze. Never raises."""
    reasons: "List[str]" = []
    if policy is not None and not isinstance(policy, dict):
        policy = None
        reasons.append("publication policy artifact malformed (not an object)")
    policy_state = verify_publication_policy(policy)
    if policy_state["status"] != FRESH:
        reasons.append("publication policy %s: %s" % (policy_state["status"],
                                                      "; ".join(policy_state["problems"])))
    policy_run_id = (policy or {}).get("run_id")
    if contract is not None and policy is not None and \
            ((contract.get("publication_policy") or {}).get("sha256")
             not in (None, policy.get("publication_policy_sha256"))):
        reasons.append("the contract binds publication policy %s..., the repository holds %s..."
                       % (str((contract.get("publication_policy") or {}).get("sha256"))[:12],
                          str(policy.get("publication_policy_sha256"))[:12]))
    report = post_run_report if isinstance(post_run_report, dict) else None
    verification_status = report.get("status") if report else None
    if post_run_report is None:
        reasons.append("post-run verification not performed (no verify_pilot_run report)")
    elif report is None:
        reasons.append("post-run verification report malformed (not an object)")
    elif verification_status != "PASS":
        reasons.append("post-run verification status is %s, not PASS" % verification_status)
    else:
        counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
        if any((counts.get(k) or 0) > 0 for k in ("FAIL", "UNRESOLVED")):
            reasons.append("post-run verification report carries FAIL/UNRESOLVED counts although "
                           "its status says PASS (inconsistent report)")
        if policy_run_id is not None and report.get("run_id") != policy_run_id:
            reasons.append("the report verifies run %r, the policy governs %r"
                           % (report.get("run_id"), policy_run_id))
        if contract is not None and report.get("contract_sha256") not in (None,) and \
                report.get("contract_sha256") != contract.get("contract_sha256"):
            reasons.append("the report was verified against contract %s..., not the bound %s..."
                           % (str(report.get("contract_sha256"))[:12],
                              str(contract.get("contract_sha256"))[:12]))
    digest = post_run_report_digest(report)
    acceptance_status = acceptance.get("status") if isinstance(acceptance, dict) else None
    if acceptance is None:
        reasons.append("result acceptance pending (no %s artifact)" % RESULT_ACCEPTANCE_SCHEMA)
    elif not isinstance(acceptance, dict):
        reasons.append("result acceptance artifact malformed (not an object)")
    elif acceptance.get("schema_version") != RESULT_ACCEPTANCE_SCHEMA:
        reasons.append("result acceptance artifact is not a %s document" % RESULT_ACCEPTANCE_SCHEMA)
    else:
        missing = [f for f in ACCEPTANCE_REQUIRED_FIELDS if not _present(acceptance.get(f))]
        if missing:
            reasons.append("result acceptance lacks required field(s): %s" % ", ".join(missing))
        if acceptance_status != "ACCEPTED":
            reasons.append("result acceptance status is %s, not ACCEPTED" % acceptance_status)
        if acceptance.get("post_run_verification_status") != "PASS":
            reasons.append("result acceptance records verification status %r, not PASS"
                           % acceptance.get("post_run_verification_status"))
        if digest is None or acceptance.get("post_run_verification_sha256") != digest:
            reasons.append("result acceptance names another post-run verification report "
                           "(%s... vs this report %s...)"
                           % (str(acceptance.get("post_run_verification_sha256"))[:12], str(digest)[:12]))
        if report is not None and acceptance.get("run_id") != report.get("run_id"):
            reasons.append("result acceptance names run %r, the report verifies %r"
                           % (acceptance.get("run_id"), report.get("run_id")))
        if policy_run_id is not None and acceptance.get("run_id") != policy_run_id:
            reasons.append("result acceptance names run %r, the policy governs %r"
                           % (acceptance.get("run_id"), policy_run_id))
        bound = (contract or {}).get("contract_sha256") if contract is not None else \
            ((report or {}).get("contract_sha256") if report else None)
        if bound is not None and acceptance.get("frozen_contract_sha256") != bound:
            reasons.append("result acceptance names contract %s..., the run's contract is %s..."
                           % (str(acceptance.get("frozen_contract_sha256"))[:12], str(bound)[:12]))
    disclosures = disclosure_sources_state(policy, repo_root) if policy else []
    missing_sources = [str(d["id"]) for d in disclosures
                       if not (d["artifact_readable"] and d["field_present"]) or d.get("problems")]
    if policy and not disclosures:
        missing_sources.append("no mandatory disclosure sources declared")
    if missing_sources:
        reasons.append("mandatory disclosure sources missing/unreadable/unsatisfied: %s"
                       % ", ".join(missing_sources))
    if contract is not None and policy is not None:
        reasons.extend(_disclosure_pin_problems(contract, repo_root))
    return OrderedDict([
        ("policy", (policy or {}).get("policy")),
        ("publication_allowed", not reasons),
        ("post_run_verification_status", verification_status),
        ("post_run_verification_sha256", digest),
        ("result_acceptance_status", acceptance_status),
        ("mandatory_disclosures", disclosures),
        ("reasons", reasons),
        ("label_required", (policy or {}).get("pilot_label")),
    ])


def _disclosure_pin_problems(contract: Dict[str, Any], repo_root: "Optional[Path]" = None) -> "List[str]":
    """The live disclosure sources must be the ones the contract froze: the
    cross-pilot fingerprint, the semantic decisions sha and the E3.2
    confirmation sha are compared with the contract's pins."""
    root = Path(repo_root) if repo_root else REPO_ROOT
    conditions = contract.get("conditions") or {}
    problems = []
    # the cross-pilot artifact the contract froze (a fixture pins its own
    # through the config seam; the contract records its path)
    cross_path = Path(conditions.get("cross_pilot_artifact_path") or ch.repo_relative(CROSS_PILOT_PATH))
    if not cross_path.is_absolute():
        cross_path = root / cross_path
    cross = _load_json(cross_path)
    fingerprint = cross_pilot_fingerprint(cross)
    if conditions.get("cross_pilot_artifact_sha256") and \
            fingerprint["recomputed"] != conditions.get("cross_pilot_artifact_sha256"):
        problems.append("cross_pilot_comparability.json changed since the freeze (contract pins %s..., "
                        "live content %s...) - cross-pilot claims must use the frozen CURRENT scope"
                        % (str(conditions.get("cross_pilot_artifact_sha256"))[:12],
                           str(fingerprint["recomputed"])[:12]))
    semantic = ch.lf_normalized_sha256(root / ch.repo_relative(SEMANTIC_DECISIONS_PATH))
    if conditions.get("semantic_decisions_sha256_lf_normalized") and \
            semantic != conditions.get("semantic_decisions_sha256_lf_normalized"):
        problems.append("semantic_decisions_pilot002.json changed since the freeze")
    confirmation = pinned_artifact(root / ch.repo_relative(E3_2_CONFIRMATION_PATH), "confirmation_sha256")
    if conditions.get("e3_2_author_confirmation_sha256") and \
            confirmation["recomputed"] != conditions.get("e3_2_author_confirmation_sha256"):
        problems.append("e3_2_author_confirmation.json changed since the freeze")
    return problems


# ---------------------------------------------------------------------------
# methodology freeze
# ---------------------------------------------------------------------------

def _generation_plan(config: Dict[str, Any]) -> "OrderedDict[str, Any]":
    """Effective provider submission path per enabled model, derived with the
    PRODUCTIVE resolver (common.resolve_api_mode) - configuration/capability
    only, no network."""
    from thesis.generation import common
    from thesis.repair import orchestrator

    gd = config.get("generation_defaults") or {}
    repair = orchestrator.repair_settings(config)
    plan = OrderedDict()
    counts = OrderedDict([("batch_jobs", 0), ("batch_requests", 0), ("direct_requests", 0)])
    for model in sorted((config.get("models") or []), key=lambda m: str(m.get("id"))):
        if not model.get("enabled", False):
            continue
        provider = str(model.get("provider"))
        mode, note = common.resolve_api_mode(gd, provider)
        requested = (gd.get("api_mode_overrides") or {}).get(provider, gd.get("api_mode", "direct"))
        path = ("batch" if mode == "batch" else
                ("direct_fallback" if requested == "batch" else "direct"))
        repair_mode = (repair.get("api_mode_overrides") or {}).get(provider, repair.get("api_mode"))
        repair_forced = provider in (repair.get("api_mode_overrides") or {})
        if repair_mode == "batch" and provider not in orchestrator.BATCH_PROVIDERS and not repair_forced:
            repair_effective, repair_note = "direct", ("provider has no verified batch API - "
                                                       "repair falls back to direct")
        else:
            repair_effective, repair_note = repair_mode, None
        reasoning = OrderedDict((k, model.get(k)) for k in sorted(model)
                                if k in ("reasoning_effort", "thinking", "effort", "thinking_level",
                                         "extra_body", "reasoning"))
        _refuse_secret_like(reasoning, "models[%s]" % model.get("id"))
        plan[str(model["id"])] = OrderedDict([
            ("provider", provider),
            ("model_name", model.get("model_name")),
            ("reasoning_configuration", reasoning),
            ("configured_generation_api_mode", requested),
            ("effective_generation_submission_path", path),
            ("effective_generation_api_mode", mode),
            ("fallback_reason", note),
            ("repair_api_mode_configured", repair_mode),
            ("repair_api_mode_effective", repair_effective),
            ("repair_fallback_reason", repair_note),
            ("model_config_sha256", ch.canonical_sha256(_model_view(model))),
        ])
        if mode == "batch":
            counts["batch_jobs"] += 1
    return OrderedDict([("per_model", plan), ("summary", counts)])


SECRET_LIKE_KEY = ("key", "secret", "token", "password", "credential")


def _refuse_secret_like(value: Any, where: str) -> None:
    """A freeze artifact is git-tracked: no key that looks like a credential
    may be frozen verbatim (env var NAMES such as api_key_env are fine, they
    are the config's own convention and carry no value)."""
    if isinstance(value, dict):
        for key, inner in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_LIKE_KEY) and not lowered.endswith("_env"):
                raise ValueError("refusing to freeze a secret-like field %s.%s verbatim" % (where, key))
            _refuse_secret_like(inner, "%s.%s" % (where, key))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            _refuse_secret_like(inner, "%s[%d]" % (where, index))


def _system_prompt_sha(gd: Dict[str, Any]) -> "Optional[str]":
    prompt = gd.get("system_prompt")
    return ch.utf8_sha256(prompt) if isinstance(prompt, str) else None


def _enforcement_provenance_view() -> "OrderedDict[str, Any]":
    """The two pre-start enforcement conditions (stage_runtime_enforcement.v1,
    dynamic_analysis_implementation.v1) as projections: repo-relative file
    entries with LF-normalized hashes plus the policy tables. Reported, never
    invented: a computation failure is recorded as an error entry (the
    contract builder turns the missing pin into a blocker)."""
    try:
        from thesis.evaluation import enforcement_provenance as ep

        return OrderedDict([
            ("stage_runtime_enforcement", ep.stage_runtime_enforcement_condition()),
            ("dynamic_analysis_implementation", ep.dynamic_analysis_implementation_condition()),
        ])
    except Exception as exc:  # noqa: BLE001
        return OrderedDict([("error", "%s: %s" % (type(exc).__name__, exc))])


def methodology_freeze_body(config: Dict[str, Any], profile_name: str, primary_compiler: str,
                            population: Dict[str, Any], publication: Dict[str, Any],
                            config_path: "Optional[Path]" = None) -> "OrderedDict[str, Any]":
    """Every methodical decision the final environment gate must NOT reopen,
    content-addressed. Reads only the CURRENT productive resolvers and the
    pinned artifacts; contains no timestamps and never the contract sha."""
    from thesis.enhanced_tests import specs as enhanced_specs
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.evaluation import run_enhanced_tests
    from thesis.evaluation.check_cross_pilot_gate import evaluation_condition_projection
    from thesis.evaluation.tool_config import resolve_tool_settings
    from thesis.generation import common
    from thesis.repair import orchestrator

    profile = common.get_profile(config, profile_name)
    stages = config.get("stages") or {}
    conditions = prc.conditions_view(config, primary_compiler)
    cross = _load_json(cross_pilot_path(config))
    cross = cross if isinstance(cross, dict) else {}
    reuse_view = reuse_policy_view(config)
    e3_confirmation = _load_json(E3_2_CONFIRMATION_PATH) or {}
    e3_decisions = _load_json(E3_2_DECISIONS_PATH) or {}
    tpc = _load_json(TECHNICAL_PROVENANCE_PATH) or {}
    semantic = _load_json(SEMANTIC_DECISIONS_PATH) or {}
    gd = config.get("generation_defaults") or {}
    repair = orchestrator.repair_settings(config)
    repair_cfg = stages.get("repair") or {}
    enhanced_cfg = stages.get("enhanced_tests") or {}
    try:
        enhanced_settings = enhanced_specs.stage_settings(config)
        effective_jobs = run_enhanced_tests.resolve_jobs(enhanced_settings, None)
    except Exception as exc:  # noqa: BLE001 - reported, never invented
        enhanced_settings, effective_jobs = {"error": "%s: %s" % (type(exc).__name__, exc)}, None
    try:
        evaluation_projection = evaluation_condition_projection()
    except Exception as exc:  # noqa: BLE001
        evaluation_projection = {"error": "%s: %s" % (type(exc).__name__, exc)}
    try:
        dynamic_tools = resolve_tool_settings(config, "dynamic_analysis")
        dynamic_view = OrderedDict(
            (name, OrderedDict([("enabled", bool(t.enabled)),
                                ("execution_models", list(t.execution_models)),
                                ("options", OrderedDict(sorted((getattr(t, "options", None) or {}).items())))]))
            for name, t in sorted(dynamic_tools.items()))
    except Exception as exc:  # noqa: BLE001
        dynamic_view = OrderedDict([("error", "%s: %s" % (type(exc).__name__, exc))])
    correctness_cfg = stages.get("correctness_tests") or {}
    search_35 = (((cross.get("shared_state") or {}).get("evaluation_condition") or {})
                 .get("benchmark_local_exceptions") or {}).get(
        "search/35_search_search_for_last_struct_by_key")
    projection = evaluation_projection if isinstance(evaluation_projection, dict) else {}
    generation_plan = _generation_plan(config)
    n_prompts = int(population.get("prompt_count") or 0)
    n_models = int(population.get("model_count") or 0)
    samples = int(population.get("samples_per_prompt") or 0)
    cells = n_prompts * samples * n_models
    batch_models = [m for m, p in generation_plan["per_model"].items()
                    if p["effective_generation_api_mode"] == "batch"]
    direct_models = [m for m, p in generation_plan["per_model"].items()
                     if p["effective_generation_api_mode"] != "batch"]
    loops = n_models * len(repair["variants"])

    body = OrderedDict([
        ("schema_version", METHODOLOGY_FREEZE_SCHEMA),
        ("identity", OrderedDict([
            ("run_id", profile.get("run_id")),
            ("profile", profile_name),
            ("historical_baseline_run_id", HISTORICAL_PILOT_RUN_ID),
            # the config file's path and sha are volatile evidence (see
            # build_methodology_freeze): the methodology is bound by the
            # resolved values and condition shas below, so a comment / ordering
            # edit or another location of the same content does not invalidate
            # the freeze
        ])),
        ("population", OrderedDict([
            ("artifact_path", ch.repo_relative(freeze_paths(config)["population"])),
            ("schema_version", population.get("schema_version")),
            ("population_sha256", population.get("population_sha256")),
            ("population_source", population.get("population_source")),
            ("status", STATUS_DECIDED),
            ("benchmark_count", population.get("benchmark_count")),
            ("benchmark_ids", list(population.get("benchmark_ids") or [])),
            ("prompt_count", n_prompts),
            ("prompt_keys", list(population.get("prompt_keys") or [])),
            ("prompt_key_set_sha256", population.get("prompt_key_set_sha256")),
            ("prompt_set_sha256", population.get("prompt_set_sha256")),
            ("model_count", n_models),
            ("model_ids", list(population.get("model_ids") or [])),
            ("execution_models", list(population.get("execution_models") or [])),
            ("samples_per_prompt", samples),
            ("total_base_cells", cells),
            ("pilot001_population_used_as_authority", False),
        ])),
        ("reuse", OrderedDict([
            # mirrors the cross-pilot reuse decision (reuse_policy_view): a
            # contradiction between the two bound documents is STALE
            ("status", reuse_view.get("status")),
            ("policy", reuse_view.get("policy")),
            ("decided", reuse_view.get("decided")),
            ("pilot_002_base_measurements", reuse_view.get("pilot_002_base_measurements")),
            ("generation_reuse", reuse_view.get("generation_reuse")),
            ("assembly_reuse", False),
            ("stage_result_reuse", reuse_view.get("stage_result_reuse")),
            ("enhanced_result_reuse", False),
            ("repair_reuse", reuse_view.get("repair_reuse")),
            ("pilot_001_role", "READ_ONLY (historical comparison baseline, cross-pilot analysis, "
                               "documented re-derivations)"),
            ("frozen_enhanced_specs_are_methodology_not_measurement", True),
            ("comparability_is_not_reuse", True),
            ("enforcement", ["run_authorization.authorize_start refuses a FIRST START of a run "
                             "that already carries result-bearing files (RUN_ID_NOT_FRESH)",
                             "verify_pilot_run record_run_identity / generation_authorization_binding "
                             "/ reuse_policy_honoured checks",
                             "pilot_preflight PILOT_002_RUN_ID_FRESH"]),
        ])),
        ("publication", OrderedDict([
            ("artifact_path", ch.repo_relative(freeze_paths(config)["publication_policy"])),
            ("schema_version", publication.get("schema_version")),
            ("publication_policy_sha256", publication.get("publication_policy_sha256")),
            ("status", publication.get("status")),
            ("policy", publication.get("policy")),
        ])),
        ("override_policy", OrderedDict([
            ("global", GLOBAL_OVERRIDE_POLICY),
            ("pilot_002_planned_methodical_cli_overrides", PLANNED_METHODICAL_OVERRIDES),
            ("planned_methodical_cli_overrides", []),
            ("allowed_operational_selectors", ALLOWED_OPERATIONAL_SELECTORS),
            ("operational_scope_fields_in_invocations", list(OPERATIONAL_SCOPE_FIELDS)),
            ("rule", "every methodical value comes from the frozen config + the frozen run "
                     "contract; a CLI-sourced methodical value is admitted only if the contract "
                     "pins exactly that value; a CLI-sourced methodical value the contract does "
                     "not pin is refused before the first record; a needed methodical override "
                     "invalidates this freeze (re-decide + re-freeze), it never starts"),
        ])),
        ("generation", OrderedDict([
            ("settings", OrderedDict([
                ("max_output_tokens", gd.get("max_output_tokens")),
                ("temperature", gd.get("temperature")),
                ("top_p", gd.get("top_p")),
                ("timeout_seconds", gd.get("timeout_seconds")),
                ("retry_attempts", gd.get("retry_attempts")),
                ("sleep_seconds_between_requests", gd.get("sleep_seconds_between_requests")),
                ("api_mode", gd.get("api_mode")),
                ("api_mode_overrides", OrderedDict(sorted((gd.get("api_mode_overrides") or {}).items()))),
                ("system_prompt_sha256", _system_prompt_sha(gd)),
                ("batch_providers", list(common.BATCH_PROVIDERS)),
                ("batch_fallback_policy", "generation_defaults.api_mode batch; a provider outside "
                                          "BATCH_PROVIDERS falls back to direct (existing productive "
                                          "policy, common.resolve_api_mode); no new batch/direct policy"),
            ])),
            ("effective_provider_plan", generation_plan["per_model"]),
            ("request_plan", OrderedDict([
                ("selected_prompt_count", n_prompts),
                ("samples_per_model", n_prompts * samples),
                ("total_model_prompt_cells", cells),
                ("batch_models", batch_models),
                ("batch_jobs", len(batch_models)),
                ("batch_requests", len(batch_models) * n_prompts * samples),
                ("direct_models", direct_models),
                ("direct_requests", len(direct_models) * n_prompts * samples),
            ])),
            ("generation_condition_sha256", conditions.get("generation_condition_sha256")),
            ("generation_cleaning_condition_sha256", conditions.get("generation_cleaning_condition_sha256")),
            ("known_provenance_caveats", [
                "Gemini batch submissions (batch_api._gemini_submit) send temperature = "
                "generation_defaults.temperature while the Gemini direct adapter deliberately "
                "sends no temperature and the persisted generation_parameters.temperature is "
                "null in both modes; frozen AS IS (no adapter change in this wave), disclosed here",
            ]),
        ])),
        ("assembly", OrderedDict([
            ("assembly_condition_version", conditions.get("assembly_condition_version")),
            ("assembly_condition_sha256", conditions.get("assembly_condition_sha256")),
            ("auto_close_single_brace", (stages.get("assembly") or {}).get("auto_close_single_brace")),
        ])),
        ("correctness", OrderedDict([
            ("primary_compiler", primary_compiler),
            # effective values (config over the runner defaults), taken from the
            # productive evaluation-condition projection
            ("niter", projection.get("niter", correctness_cfg.get("niter"))),
            ("build_timeout_seconds", projection.get("build_timeout_seconds",
                                                     correctness_cfg.get("build_timeout_seconds"))),
            ("run_timeout_seconds", projection.get("run_timeout_seconds",
                                                   correctness_cfg.get("run_timeout_seconds"))),
            ("launch_defaults", OrderedDict((pm, (v or {}).get("launch_params"))
                                            for pm, v in sorted((projection.get("per_execution_model")
                                                                 or {}).items()))),
            ("launch_overrides", projection.get("launch_overrides", correctness_cfg.get("launch_overrides"))),
            ("config_values", OrderedDict([("niter", correctness_cfg.get("niter")),
                                           ("run_timeout_seconds", correctness_cfg.get("run_timeout_seconds")),
                                           ("build_timeout_seconds", correctness_cfg.get("build_timeout_seconds")),
                                           ("launch_overrides", correctness_cfg.get("launch_overrides"))])),
            ("evaluation_condition_sha256", conditions.get("evaluation_condition_sha256")),
            ("evaluation_condition_projection", evaluation_projection),
            ("validation", OrderedDict([
                ("max_validation_attempts_default", projection.get("max_validation_attempts")),
                ("benchmark_local_exception_search_35", search_35),
                ("e3_2_disclosure", "D5_search_35_five_validation_attempts"),
            ])),
        ])),
        ("static", OrderedDict([
            ("toolset", prc.static_toolset_view(config)),
            ("static_analysis_condition_sha256", conditions.get("static_analysis_condition_sha256")),
            ("static_repair_runtime_condition_sha256", conditions.get("static_repair_runtime_condition_sha256")),
            ("readiness_gate", conditions.get("static_repair_readiness_gate")),
            ("e3_2_decision", e3_decisions.get("E3_2_DECISION")),
            ("e3_2_decisions_sha256", e3_decisions.get("decisions_sha256")),
            ("e3_2_author_choices", e3_confirmation.get("choices_short")),
        ])),
        ("dynamic", OrderedDict([
            ("enabled", bool((stages.get("dynamic_analysis") or {}).get("enabled", False))),
            ("toolset", dynamic_view),
        ])),
        ("enhanced", OrderedDict([
            ("enabled", bool(enhanced_cfg.get("enabled", False))),
            ("frozen_specs_path", conditions.get("enhanced_frozen_specs_path")),
            ("frozen_specs_sha256", conditions.get("enhanced_frozen_specs_sha256")),
            ("enhanced_policy_sha256_lf_normalized", conditions.get("enhanced_policy_sha256_lf_normalized")),
            ("enhanced_policy_status", conditions.get("enhanced_policy_status")),
            ("execution_models", list(enhanced_cfg.get("execution_models") or [])),
            ("enhanced_launch", OrderedDict(sorted((enhanced_cfg.get("enhanced_launch") or {}).items()))),
            ("run_timeout_seconds", enhanced_cfg.get("run_timeout_seconds")),
            ("build_timeout_seconds_constant", getattr(run_enhanced_tests, "BUILD_TIMEOUT", None)),
            ("effective_jobs_from_config", effective_jobs),
            ("jobs_cli_override_planned", False),
            ("target_cases_per_benchmark", enhanced_settings.get("target_cases_per_benchmark")
             if isinstance(enhanced_settings, dict) else None),
            ("static_base_sizes", enhanced_settings.get("static_base_sizes")
             if isinstance(enhanced_settings, dict) else None),
            ("max_spec_size", enhanced_settings.get("max_spec_size")
             if isinstance(enhanced_settings, dict) else None),
        ])),
        ("repair", OrderedDict([
            ("enabled", bool(repair_cfg.get("enabled", False))),
            ("variants", list(repair["variants"])),
            ("max_iterations", repair["max_iterations"]),
            ("api_mode", repair["api_mode"]),
            ("api_mode_overrides", OrderedDict(sorted((repair.get("api_mode_overrides") or {}).items()))),
            ("external_tools_mode", repair["external_tools_mode"]),
            ("external_tools", list(repair["external_tools"])),
            ("history_mode", repair_cfg.get("history_mode")),
            ("low_confidence_stop_mode", repair["low_confidence_stop_mode"]),
            ("request_retry_rounds", repair["request_retry_rounds"]),
            ("feedback", repair_cfg.get("feedback")),
            ("strategies", repair_cfg.get("strategies")),
            ("expected_logical_loops", loops),
            ("request_upper_bound", OrderedDict([
                ("value", loops * repair["max_iterations"] * n_prompts * samples),
                ("rule", "loops x max_iterations x samples per model; stop/terminal semantics "
                         "make the actual number smaller, never larger"),
            ])),
            ("repair_condition_sha256", conditions.get("repair_condition_sha256")),
        ])),
        ("conditions", OrderedDict([
            ("generation", conditions.get("generation_condition_sha256")),
            ("generation_cleaning", conditions.get("generation_cleaning_condition_sha256")),
            ("assembly", conditions.get("assembly_condition_sha256")),
            ("evaluation", conditions.get("evaluation_condition_sha256")),
            ("enhanced_specs", conditions.get("enhanced_frozen_specs_sha256")),
            ("enhanced_policy_lf_normalized", conditions.get("enhanced_policy_sha256_lf_normalized")),
            ("semantic_decisions_lf_normalized", conditions.get("semantic_decisions_sha256_lf_normalized")),
            ("semantic_decisions_counts", conditions.get("semantic_decisions_counts")),
            ("e3_2_author_confirmation", e3_confirmation.get("confirmation_sha256")),
            ("e3_2_decisions", e3_decisions.get("decisions_sha256")),
            ("static_analysis", conditions.get("static_analysis_condition_sha256")),
            ("repair", conditions.get("repair_condition_sha256")),
            ("runtime", conditions.get("static_repair_runtime_condition_sha256")),
            ("timing", conditions.get("timing_contract_sha256")),
            ("cross_pilot", conditions.get("cross_pilot_artifact_sha256")),
            ("cross_pilot_state_commit", conditions.get("cross_pilot_state_commit")),
            ("technical_provenance_cleanup", tpc.get("artifact_sha256")),
            # pre-start fix wave (2026-09-16): the two enforcement pins
            ("stage_runtime_enforcement", conditions.get("stage_runtime_enforcement_condition_sha256")),
            ("dynamic_analysis_implementation",
             conditions.get("dynamic_analysis_implementation_condition_sha256")),
        ])),
        ("provenance_policies", prc.provenance_policies_view()),
        # the projections behind the two enforcement pins (file hashes +
        # policy), so the freeze documents WHAT is pinned, not only the sha
        ("enforcement_provenance", _enforcement_provenance_view()),
        ("open_environment_gates", [
            "Docker first-inspect / Docker Desktop observation",
            "TSan/ASLR",
            "live runtime remeasurement",
            "provider/model availability",
            "T0 fresh authorization",
        ]),
        ("open_environment_gates_note", "environment checks only - NOT method decisions; every "
                                        "method decision needed before the final environment gate "
                                        "is closed and content-addressed in this document"),
        ("sha_rule", SHA_RULE),
    ])
    return body


def build_methodology_freeze(config: Dict[str, Any], profile_name: str, primary_compiler: str,
                             population: Dict[str, Any], publication: Dict[str, Any],
                             config_path: "Optional[Path]" = None) -> "OrderedDict[str, Any]":
    document = methodology_freeze_body(config, profile_name, primary_compiler, population,
                                       publication, config_path)
    document["methodology_freeze_sha256"] = document_sha256(document, "methodology_freeze_sha256")
    document["volatile"] = OrderedDict([
        ("generated_at_utc", _utc_now()),
        ("config_path_at_freeze", ch.repo_relative(config_path) if config_path else None),
        ("config_sha256_lf_normalized_at_freeze",
         ch.lf_normalized_sha256(config_path) if config_path else None),
    ])
    return document


def verify_methodology_freeze(document: "Optional[Dict[str, Any]]", config: Dict[str, Any],
                              profile_name: str, primary_compiler: str,
                              population: "Optional[Dict[str, Any]]",
                              publication: "Optional[Dict[str, Any]]",
                              config_path: "Optional[Path]" = None) -> "OrderedDict[str, Any]":
    """FRESH when the stored sha reproduces AND a rebuild from the current
    state yields the identical body; STALE with the drifted dot-paths
    otherwise (a config / artifact edit after the freeze invalidates it)."""
    from thesis.evaluation.run_manifest import config_key_diff

    if document is None:
        return OrderedDict([("status", MISSING), ("problems", ["methodology freeze artifact missing"]),
                            ("drift_fields", [])])
    if not isinstance(document, dict) or document.get("schema_version") != METHODOLOGY_FREEZE_SCHEMA:
        return OrderedDict([("status", MALFORMED),
                            ("problems", ["not a %s document" % METHODOLOGY_FREEZE_SCHEMA]),
                            ("drift_fields", [])])
    problems: "List[str]" = []
    if document.get("methodology_freeze_sha256") != document_sha256(document, "methodology_freeze_sha256"):
        problems.append("methodology_freeze_sha256 does not reproduce (edited without recomputation)")
    if population is None or publication is None:
        return OrderedDict([("status", STALE),
                            ("problems", problems + ["population / publication artifacts needed for the "
                                                     "rebuild are missing"]),
                            ("drift_fields", [])])
    try:
        current = methodology_freeze_body(config, profile_name, primary_compiler, population,
                                          publication, config_path)
    except Exception as exc:  # noqa: BLE001 - never a silent FRESH
        return OrderedDict([("status", STALE),
                            ("problems", problems + ["rebuild failed: %s: %s" % (type(exc).__name__, exc)]),
                            ("drift_fields", [])])
    stored_body = OrderedDict((k, v) for k, v in document.items()
                              if k not in ("volatile", "methodology_freeze_sha256"))
    drift = config_key_diff(json.loads(json.dumps(stored_body, default=str)),
                            json.loads(json.dumps(current, default=str)))
    if drift:
        problems.append("methodology freeze is stale: %s" % ", ".join(drift))
    if document.get("methodology_freeze_sha256") != ch.canonical_sha256(current):
        if not drift:
            problems.append("methodology freeze sha differs from the current rebuild")
    return OrderedDict([("status", FRESH if not problems else STALE), ("problems", problems),
                        ("drift_fields", drift)])


# ---------------------------------------------------------------------------
# the consolidated freeze state (contract builder + preflight)
# ---------------------------------------------------------------------------

def freeze_state_unresolved(config: "Optional[Dict[str, Any]]", error: str) -> "OrderedDict[str, Any]":
    """The freeze state when it cannot be computed: every part MALFORMED,
    nothing decided - the contract builder turns it into blockers."""
    paths = freeze_paths(config)
    empty = OrderedDict([("path", None), ("schema_version", None), ("sha256", None),
                         ("status", MALFORMED), ("problems", [error])])
    population = OrderedDict(empty)
    population.update(OrderedDict([("path", ch.repo_relative(paths["population"])),
                                   ("population_source", None), ("benchmark_count", None),
                                   ("prompt_count", None), ("model_count", None),
                                   ("samples_per_prompt", None), ("total_model_prompt_cells", None),
                                   ("execution_models", None), ("benchmark_ids", None),
                                   ("prompt_key_set_sha256", None), ("prompt_set_sha256", None),
                                   ("prompt_hashes", None), ("model_ids", None)]))
    publication = OrderedDict(empty)
    publication.update(OrderedDict([("path", ch.repo_relative(paths["publication_policy"])),
                                    ("decided", False), ("policy", None)]))
    methodology = OrderedDict(empty)
    methodology.update(OrderedDict([("path", ch.repo_relative(paths["methodology_freeze"])),
                                    ("drift_fields", [])]))
    return OrderedDict([
        ("population", population), ("publication", publication), ("methodology", methodology),
        ("reuse", OrderedDict([("reuse_status", None), ("status", None), ("policy", None),
                               ("decided", False)])),
        ("override_plan", OrderedDict([("global_policy", GLOBAL_OVERRIDE_POLICY),
                                       ("planned_methodical_cli_overrides", None),
                                       ("planned", "UNDECLARED"),
                                       ("allowed_operational_selectors", list(ALLOWED_OPERATIONAL_SELECTORS.keys())),
                                       ("operational_scope_fields", list(OPERATIONAL_SCOPE_FIELDS))])),
    ])


def seam_problems(config: "Optional[Dict[str, Any]]", run_id: "Optional[str]") -> "List[str]":
    """The fixture seams (outputs.freeze_artifacts / cross_pilot_artifact /
    readiness_artifact) are refused for the productive run id."""
    if run_id != PILOT_002_RUN_ID:
        return []
    outputs = ((config or {}).get("outputs") or {})
    problems = []
    for key in ("freeze_artifacts", "cross_pilot_artifact", "readiness_artifact"):
        if outputs.get(key):
            problems.append("fixture seam outputs.%s is set in the configuration of the productive "
                            "run %s - the productive freeze is the repository default only"
                            % (key, PILOT_002_RUN_ID))
    return problems


def reuse_policy_view(config: "Optional[Dict[str, Any]]") -> "OrderedDict[str, Any]":
    cross = _load_json(cross_pilot_path(config))
    cross = cross if isinstance(cross, dict) else {}
    policy = cross.get("reuse_policy") if isinstance(cross.get("reuse_policy"), dict) else {}
    status = cross.get("reuse_status")
    decided = (status == REUSE_STATUS_DECIDED and policy.get("policy") == REUSE_POLICY
               and policy.get("status") == STATUS_DECIDED
               and policy.get("pilot_002_base_measurements") == "FRESH"
               and all(policy.get(flag) is False for flag in
                       ("generation_reuse", "stage_result_reuse", "repair_reuse"))
               and policy.get("comparability_is_not_reuse") is True)
    return OrderedDict([
        ("reuse_status", status),
        ("status", policy.get("status")),
        ("policy", policy.get("policy")),
        ("decided", bool(decided)),
        ("pilot_002_base_measurements", policy.get("pilot_002_base_measurements")),
        ("generation_reuse", policy.get("generation_reuse")),
        ("stage_result_reuse", policy.get("stage_result_reuse")),
        ("repair_reuse", policy.get("repair_reuse")),
        ("pilot_001_role", policy.get("pilot_001_role")),
        ("comparability_is_not_reuse", policy.get("comparability_is_not_reuse")),
    ])


def freeze_state(config: Dict[str, Any], profile_name: str, primary_compiler: str,
                 config_path: "Optional[Path]" = None,
                 run_id: "Optional[str]" = None) -> "OrderedDict[str, Any]":
    """What the contract builder and the preflight bind / report: the three
    freeze artifacts with their integrity + staleness verdicts, the reuse
    decision of the cross-pilot artifact and the override plan. An artifact
    frozen for ANOTHER run id is stale for this run (a fixture run never
    inherits the repository's pilot_002 freeze by accident)."""
    from thesis.generation import common

    paths = freeze_paths(config)
    if run_id is None:
        run_id = common.get_profile(config, profile_name).get("run_id")
    population = _load_json(paths["population"])
    publication = _load_json(paths["publication_policy"])
    methodology = _load_json(paths["methodology_freeze"])
    pop_state = verify_population(population, config, profile_name, config_path)
    pub_state = verify_publication_policy(publication)
    meth_state = verify_methodology_freeze(methodology, config, profile_name, primary_compiler,
                                           population, publication, config_path)
    if isinstance(population, dict) and population.get("run_id") != run_id:
        pop_state = OrderedDict([("status", STALE), ("problems", list(pop_state["problems"]) + [
            "population artifact is frozen for run %r, not %r" % (population.get("run_id"), run_id)])])
    if isinstance(methodology, dict) and (methodology.get("identity") or {}).get("run_id") != run_id:
        meth_state = OrderedDict([("status", STALE), ("problems", list(meth_state["problems"]) + [
            "methodology freeze is frozen for run %r, not %r"
            % ((methodology.get("identity") or {}).get("run_id"), run_id)]),
            ("drift_fields", list(meth_state.get("drift_fields") or []))])
        methodology_for_plan = None
    else:
        methodology_for_plan = methodology
    cross = _load_json(cross_pilot_path(config))
    cross = cross if isinstance(cross, dict) else {}
    exp_pop = cross.get("expected_pilot_002_population") if isinstance(cross.get("expected_pilot_002_population"), dict) else {}
    exp_pub = cross.get("publication_policy") if isinstance(cross.get("publication_policy"), dict) else {}
    pop_sha = (population or {}).get("population_sha256")
    pub_sha = (publication or {}).get("publication_policy_sha256")
    meth = methodology or {}
    problems = OrderedDict([("population", list(pop_state["problems"])),
                            ("publication", list(pub_state["problems"])),
                            ("methodology", list(meth_state["problems"]))])
    if exp_pop.get("status") == STATUS_DECIDED and exp_pop.get("population_sha256") not in (None, pop_sha):
        problems["population"].append(
            "cross-pilot expected_pilot_002_population binds population sha %s... but the artifact is %s..."
            % (str(exp_pop.get("population_sha256"))[:12], str(pop_sha)[:12]))
    if exp_pub.get("status") == STATUS_DECIDED and exp_pub.get("publication_policy_sha256") not in (None, pub_sha):
        problems["publication"].append(
            "cross-pilot publication_policy binds sha %s... but the artifact is %s..."
            % (str(exp_pub.get("publication_policy_sha256"))[:12], str(pub_sha)[:12]))
    if methodology and (meth.get("population") or {}).get("population_sha256") != pop_sha:
        problems["methodology"].append("methodology freeze binds another population sha")
    if methodology and (meth.get("publication") or {}).get("publication_policy_sha256") != pub_sha:
        problems["methodology"].append("methodology freeze binds another publication policy sha")
    if isinstance(publication, dict) and publication.get("run_id") != run_id:
        problems["publication"].append("publication policy is frozen for run %r, not %r"
                                       % (publication.get("run_id"), run_id))
    # the productive run never takes its freeze from a fixture seam: every
    # artifact must be the repository default (CTR-02)
    seams = seam_problems(config, run_id)
    for problem in seams:
        problems["methodology"].append(problem)
    override = (meth.get("override_policy") or {}) if methodology_for_plan else {}
    planned = override.get("planned_methodical_cli_overrides")
    return OrderedDict([
        ("population", OrderedDict([
            ("path", ch.repo_relative(paths["population"])),
            ("schema_version", (population or {}).get("schema_version")),
            ("sha256", pop_sha),
            ("status", pop_state["status"] if not problems["population"] else
             (pop_state["status"] if pop_state["status"] in (MISSING, MALFORMED) else STALE)),
            ("problems", problems["population"]),
            ("population_source", (population or {}).get("population_source")),
            ("benchmark_count", (population or {}).get("benchmark_count")),
            ("prompt_count", (population or {}).get("prompt_count")),
            ("model_count", (population or {}).get("model_count")),
            ("samples_per_prompt", (population or {}).get("samples_per_prompt")),
            ("total_model_prompt_cells", (population or {}).get("total_model_prompt_cells")),
            ("execution_models", (population or {}).get("execution_models")),
            ("benchmark_ids", (population or {}).get("benchmark_ids")),
            ("prompt_key_set_sha256", (population or {}).get("prompt_key_set_sha256")),
            ("prompt_set_sha256", (population or {}).get("prompt_set_sha256")),
            ("prompt_hashes", (population or {}).get("prompt_hashes")),
            ("model_ids", (population or {}).get("model_ids")),
        ])),
        ("publication", OrderedDict([
            ("path", ch.repo_relative(paths["publication_policy"])),
            ("schema_version", (publication or {}).get("schema_version")),
            ("sha256", pub_sha),
            ("status", pub_state["status"] if not problems["publication"] else
             (pub_state["status"] if pub_state["status"] in (MISSING, MALFORMED) else STALE)),
            ("decided", pub_state["status"] == FRESH and not problems["publication"]),
            ("policy", (publication or {}).get("policy")),
            ("problems", problems["publication"]),
        ])),
        ("methodology", OrderedDict([
            ("path", ch.repo_relative(paths["methodology_freeze"])),
            ("schema_version", meth.get("schema_version")),
            ("sha256", meth.get("methodology_freeze_sha256")),
            ("status", meth_state["status"] if not problems["methodology"] else
             (meth_state["status"] if meth_state["status"] in (MISSING, MALFORMED) else STALE)),
            ("problems", problems["methodology"]),
            ("drift_fields", meth_state.get("drift_fields") or []),
        ])),
        ("reuse", reuse_policy_view(config)),
        ("override_plan", OrderedDict([
            ("global_policy", override.get("global") or GLOBAL_OVERRIDE_POLICY),
            ("planned_methodical_cli_overrides", planned if isinstance(planned, list) else None),
            ("planned", ("NONE" if isinstance(planned, list) and not planned else
                         ("UNDECLARED" if planned is None else "NON_EMPTY"))),
            ("allowed_operational_selectors", list(ALLOWED_OPERATIONAL_SELECTORS.keys())),
            ("operational_scope_fields", list(OPERATIONAL_SCOPE_FIELDS)),
        ])),
    ])


# ---------------------------------------------------------------------------
# run freeze receipt
# ---------------------------------------------------------------------------

def build_run_freeze_receipt(config: Dict[str, Any], contract: Dict[str, Any],
                             contract_path: Path, source_head: "Optional[str]",
                             rebuilt_sha256: "Optional[str]", drift_fields: "List[str]",
                             freshness: Dict[str, Any]) -> "OrderedDict[str, Any]":
    from thesis.evaluation import run_authorization as ra

    run_id = contract.get("run_id")
    authorization = ra.load_authorization(config, run_id)
    document = OrderedDict([
        ("schema_version", RUN_FREEZE_RECEIPT_SCHEMA),
        ("run_id", run_id),
        ("profile", contract.get("profile")),
        ("methodology_freeze_sha256", (contract.get("methodology_freeze") or {}).get("sha256")),
        ("population_sha256", (contract.get("population_freeze") or {}).get("sha256")),
        ("publication_policy_sha256", (contract.get("publication_policy") or {}).get("sha256")),
        ("reuse_policy", (contract.get("reuse_policy") or {}).get("policy")),
        ("frozen_contract_path", ch.repo_relative(contract_path)),
        ("frozen_contract_path_note", "the canonical per-run location run_authorization discovers "
                                      "(git-ignored results tree); the contract is reproducible: a "
                                      "rebuild from the repository state yields the same sha"),
        ("frozen_contract_sha256", contract.get("contract_sha256")),
        ("contract_schema", contract.get("schema_version")),
        ("contract_status", contract.get("status")),
        ("rebuilt_contract_sha256", rebuilt_sha256),
        ("frozen_vs_rebuilt_drift_fields", list(drift_fields)),
        ("source_head_before_freeze", source_head),
        ("run_freshness", freshness.get("status")),
        ("start_authorized", authorization is not None),
        ("t0_bound", False),
        ("provider_calls", 0),
        ("result_records_written", 0),
        ("sha_rule", SHA_RULE),
    ])
    document["receipt_sha256"] = document_sha256(document, "receipt_sha256")
    document["volatile"] = OrderedDict([("generated_at_utc", _utc_now())])
    return document


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def common_run_id(config: Dict[str, Any], profile_name: str) -> "Optional[str]":
    from thesis.generation import common

    return common.get_profile(config, profile_name).get("run_id")


def main() -> int:
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["population", "publication", "methodology", "receipt", "verify"])
    parser.add_argument("--config", default="thesis/config/config.yaml")
    parser.add_argument("--profile", default=PILOT_002_PROFILE)
    parser.add_argument("--primary-compiler", default="g++")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    paths = freeze_paths(config)
    if args.command == "population":
        document = build_population(config, args.profile, pilot_002_author_freeze(), config_path)
        _write(paths["population"], document)
        print("POPULATION_SHA256 = %s -> %s" % (document["population_sha256"], paths["population"]))
        return 0
    if args.command == "publication":
        document = build_publication_policy()
        _write(paths["publication_policy"], document)
        print("PUBLICATION_POLICY_SHA256 = %s -> %s" % (document["publication_policy_sha256"],
                                                       paths["publication_policy"]))
        return 0
    if args.command == "methodology":
        population = _load_json(paths["population"])
        publication = _load_json(paths["publication_policy"])
        if population is None or publication is None:
            print("population / publication artifacts missing - build them first")
            return 2
        document = build_methodology_freeze(config, args.profile, args.primary_compiler,
                                            population, publication, config_path)
        _write(paths["methodology_freeze"], document)
        print("METHODOLOGY_FREEZE_SHA256 = %s -> %s" % (document["methodology_freeze_sha256"],
                                                       paths["methodology_freeze"]))
        return 0
    if args.command == "receipt":
        # the receipt of an ALREADY frozen contract at the canonical location:
        # reload, rebuild live (no bind, no probe), write the receipt
        from thesis.evaluation import pilot_run_contract as prc
        from thesis.evaluation import run_authorization as ra
        from thesis.evaluation import run_freshness

        run_id = common_run_id(config, args.profile)
        canonical = ra.canonical_contract_path(config, run_id)
        frozen = prc.load_frozen(canonical)
        decision = prc.t0_guard(config_path, args.profile, canonical, bind=False, probe_docker=False)
        freshness = run_freshness.inspect_run_freshness(config, run_id)
        head = None
        try:
            import subprocess

            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                                           text=True).strip()
        except Exception:  # noqa: BLE001
            head = None
        receipt = build_run_freeze_receipt(config, frozen, canonical, head,
                                           decision["rebuilt_contract_sha256"], decision["drift_fields"],
                                           freshness)
        _write(paths["run_freeze_receipt"], receipt)
        print("RECEIPT_SHA256 = %s -> %s" % (receipt["receipt_sha256"], paths["run_freeze_receipt"]))
        print("T0_GUARD_NO_BIND = %s drift %s" % (decision["decision"], decision["drift_fields"]))
        return 0 if decision["decision"] == prc.START_ALLOWED else 2
    state = freeze_state(config, args.profile, args.primary_compiler, config_path)
    print(json.dumps(state, indent=1))
    ok = all(state[k]["status"] == FRESH for k in ("population", "publication", "methodology")) \
        and state["reuse"]["decided"] and state["override_plan"]["planned"] == "NONE"
    print("FREEZE_STATE = %s" % ("FRESH" if ok else "NOT_READY"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
