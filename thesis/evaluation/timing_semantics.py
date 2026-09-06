"""Timing contract - the single machine-readable source of truth for every
timing field the pipeline produces (pilot_002 pre-run wave, block D).

Nothing here changes a measurement; it states, per field, what the number
IS (unit, clock, start/end boundary, what it includes) and what it may be
used for (model speed ranking, cross-model / cross-execution-model
comparison, allowed aggregation). Reports and the validator
(check_timing_semantics.py) consume this table; the exported JSON
(timing_semantics.json) is content-addressed by `timing_contract_sha256`.

Measured facts behind the statements (timing audit on HEAD d56db25):
  * every historical timer is time.time() (wall clock); direct generation
    and repair responses switch to time.perf_counter (monotonic) in this
    wave and record status.timing_clock
  * correctness/static/dynamic stages run samples SEQUENTIALLY; only the
    enhanced stage uses a thread pool over samples (timer starts inside
    the worker, so queue wait never enters duration_seconds, but CPU
    contention between concurrent samples can)
  * the timed process for mpi is `mpirun -np N benchmark.out 1`, for omp
    `benchmark.out T` with OMP_NUM_THREADS=T, for serial `benchmark.out 1`
    -> launcher / runtime init / process startup are INSIDE run seconds
  * timeouts store the OBSERVED elapsed (limit + kill overhead) plus a
    flag, never the configured limit; the limit lives in the run manifest
    (stages.correctness_tests.run_timeout_seconds, stages.enhanced_tests.
    run_timeout_seconds) and in code defaults (build limit 120 s)
  * batch generation has no per-request latency: one submit stamp and one
    poll-side completion stamp per JOB
  * pilot_001 base generation is MIXED: 6 batch models, 5 direct models

Python 3.8 compatible.
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TIMING_CONTRACT_VERSION = "timing_semantics.v1"
TIMEOUT_EPSILON_SECONDS = 0.002     # observed elapsed may round 1 ms below the limit
WALL_CLOCK_ANOMALY_SLACK_SECONDS = 2.0  # elapsed > limit + slack on a non-timeout row

BUILD_TIMEOUT_DEFAULT_SECONDS = 120.0  # code default, not in config (framework/run_enhanced_tests)

# Per-model generation timing classes
DIRECT_LATENCY_AVAILABLE = "DIRECT_LATENCY_AVAILABLE"
BATCH_QUEUE_ONLY = "BATCH_QUEUE_ONLY"
MIXED_DIRECT_AND_BATCH = "MIXED_DIRECT_AND_BATCH"
TEST_RUNTIME_AVAILABLE = "TEST_RUNTIME_AVAILABLE"
TIMING_PROVENANCE_INSUFFICIENT = "TIMING_PROVENANCE_INSUFFICIENT"


def _field(path, producer, unit, meaning, clock, start, end, direct, batch,
           includes, suitable, aggregation, on_timeout, consumers, notes=None):
    return OrderedDict([
        ("field", path),
        ("producer", producer),
        ("unit", unit),
        ("meaning", meaning),
        ("clock_source", clock),
        ("start_boundary", start),
        ("end_boundary", end),
        ("available_in_direct_mode", direct),
        ("available_in_batch_mode", batch),
        ("includes", OrderedDict(sorted(includes.items()))),
        ("suitable_for", OrderedDict(sorted(suitable.items()))),
        ("allowed_aggregation", aggregation),
        ("on_timeout", on_timeout),
        ("consumers", consumers),
        ("notes", notes or []),
    ])


def _includes(**kw):
    base = OrderedDict([
        ("client_retries", False), ("sdk_internal_retries", False),
        ("inter_request_sleep", False), ("provider_queue_wait", False),
        ("local_queue_wait", False), ("build", False), ("process_startup", False),
        ("launcher_overhead", False), ("runtime_initialization", False),
        ("adapter_overhead", False), ("cpu_contention_from_parallel_samples", False),
    ])
    base.update(kw)
    return base


def _suitable(**kw):
    base = OrderedDict([
        ("model_speed_ranking", False),
        ("cross_model_within_execution_model", False),
        ("cross_execution_model", False),
        ("cross_pilot_absolute_comparison", False),
        ("cost_accounting", False),
    ])
    base.update(kw)
    return base


def timing_contract() -> "OrderedDict[str, Any]":
    fields: "List[OrderedDict[str, Any]]" = []

    fields.append(_field(
        "generation.status.duration_seconds (timing_mode=direct)",
        "thesis/generation/common.py:apply_direct_timing (generation main loop; "
        "repair: thesis/repair/orchestrator.py direct request loop)",
        "seconds", "end-to-end request latency of ONE model call as seen by the client",
        "time.perf_counter (monotonic) when status.timing_clock == 'perf_counter'; "
        "time.time (wall clock) for legacy records (pilot_001, timing_clock absent)",
        "immediately before adapter.generate()",
        "after the success/failure record fields are applied, before the record is written",
        True, False,
        _includes(client_retries=True, sdk_internal_retries=True, adapter_overhead=True,
                  inter_request_sleep=True, process_startup=False),
        _suitable(model_speed_ranking=True, cross_model_within_execution_model=True),
        ["median", "percentiles", "mean with n", "per model", "per benchmark"],
        "client timeout (generation_defaults.timeout_seconds) raises inside the retry "
        "loop; the final failure record still carries the observed elapsed",
        ["validate_generations", "build_overview generation effort/latency section"],
        ["the RETRY BACKOFF inside call_with_retries is inside the timer, and it uses "
         "generation_defaults.sleep_seconds_between_requests as its wait when that value "
         "is > 0 (otherwise an exponential backoff capped at 10 s); only the sleep AFTER "
         "the record is written is outside the timer. A retried request therefore carries "
         "its own backoff time",
         "upper bound = timeout x (retry_attempts+1) x (sdk max_retries+1) plus the "
         "in-timer backoffs",
         "model speed ranking only among DIRECT-mode models; a run that mixes direct "
         "and batch models has CROSS_MODEL_LATENCY_RANKING = NOT_AVAILABLE"]))

    fields.append(_field(
        "generation.status.duration_seconds (timing_mode=batch)",
        "thesis/generation/common.py:apply_batch_timing",
        "seconds", "ALWAYS null: batch APIs expose no per-request inference time",
        "n/a", "n/a", "n/a", False, True,
        _includes(), _suitable(),
        ["none"], "n/a",
        ["build_overview (must treat null as not available)"],
        ["a batch record with a non-null duration_seconds is a contract violation"]))

    fields.append(_field(
        "generation.status.batch_wall_clock_seconds "
        "(= batch_completed_at_utc - batch_submitted_at_utc)",
        "thesis/generation/common.py:apply_batch_timing (stamps: batch submit / "
        "completing poll)",
        "seconds", "JOB-level provider queue span shared by every request of the job",
        "two UTC wall-clock stamps (utc_now_iso) on the client side",
        "batch job submitted", "the poll that observed the job completed",
        False, True,
        _includes(provider_queue_wait=True, local_queue_wait=True),
        _suitable(),
        ["per job only; never per request; never as a latency distribution"],
        "n/a (jobs expire provider-side; expired requests are re-submitted as new jobs)",
        ["operational reporting only"],
        ["NOT model latency: dominated by provider queueing (pilot_001: 6108-23884 s per job)",
         "pilot_001 records predate this derived field; the two stamps exist"]))

    fields.append(_field(
        "generation.api_response.usage_normalized.{input_tokens,output_tokens,reasoning_tokens}",
        "thesis/generation/common.py:normalize_usage (provider usage object)",
        "tokens", "provider-reported usage; reasoning_tokens is the EFFORT measure "
        "(separate from any time field)",
        "n/a (provider counter)", "n/a", "n/a", True, True,
        _includes(), _suitable(cost_accounting=True, cross_model_within_execution_model=True),
        ["sum per model (cost)", "median per model (effort)"],
        "n/a",
        ["build_overview generation effort section", "cost accounting"],
        ["provider cost = tokens x configured price per model; generation and repair "
         "responses are counted once each (never both a base record and its repair "
         "history); missing usage stays null and is never estimated"]))

    fields.append(_field(
        "correctness.compile.duration_seconds",
        "thesis/evaluation/framework.py:run_command (compile step of run_correctness)",
        "seconds", "wall time of the compiler process for one sample",
        "time.time (wall clock)", "before Popen of the compiler", "after the process exits or is killed",
        True, True,
        _includes(process_startup=True),
        _suitable(),
        ["sum per stage (runtime cost)", "per model diagnostics"],
        "observed elapsed stored + compile.timed_out=true (limit 120 s code default)",
        ["build_overview runtime cost", "check_timing_semantics"],
        ["build time, kept strictly separate from run time"]))

    fields.append(_field(
        "correctness.runs[].duration_seconds",
        "thesis/evaluation/framework.py:run_command (run grid of run_correctness)",
        "seconds", "wall time of ONE timed benchmark process at one grid point "
        "(serial: 1; omp: OMP_NUM_THREADS in {1,2,4,8}; mpi: -np in {1,2,4,8})",
        "time.time (wall clock)", "before Popen of the benchmark (or mpirun)",
        "after the process exits or is killed", True, True,
        _includes(process_startup=True, launcher_overhead=True, runtime_initialization=True),
        _suitable(cross_model_within_execution_model=True),
        ["median per (model, benchmark, execution_model, grid point)", "never pooled across execution models"],
        "observed elapsed stored + runs[].timed_out=true. The limit is the manifest's "
        "stages.correctness_tests.run_timeout_seconds, BUT run_correctness.py accepts a "
        "--run-timeout override that is persisted nowhere; a run that used one must "
        "declare it (the validator takes it via --run-timeout-seconds), otherwise its "
        "legitimate timeout rows look inconsistent with the frozen limit",
        ["build_overview", "check_timing_semantics"],
        ["mpi: includes_launcher_overhead=true (mpirun -np N is the timed argv) and "
         "MPI_Init/teardown; omp: includes OpenMP runtime init and the omp driver's fixed "
         "timing iterations; serial: includes process startup",
         "RUN_SECONDS_CROSS_EXECUTION_MODEL_COMPARABLE = false",
         "cross-model comparison within one execution model requires: same host/container, "
         "same compiler, same grid point, same niter, sequential execution (correctness "
         "stage is sequential) and no wall-clock anomaly on the row"]))

    fields.append(_field(
        "enhanced_build_groups.compile_seconds",
        "thesis/evaluation/run_enhanced_tests.py (grouped build per (sample, spec group))",
        "seconds", "wall time of one grouped enhanced build",
        "time.time (wall clock)", "before the compiler Popen", "after exit/kill", True, True,
        _includes(process_startup=True, cpu_contention_from_parallel_samples=True),
        _suitable(),
        ["sum per stage"],
        "observed elapsed is stored, but a build that hit the 120 s limit is recorded as "
        "build_status='build_failed' - INDISTINGUISHABLE from a compile error, so an "
        "enhanced build timeout is NOT detectable from the record alone (pre-existing "
        "producer behaviour, stated here rather than assumed away)",
        ["build_overview enhanced_seconds", "check_timing_semantics"],
        ["pilot_001 carries ONE wall-clock artifact: claude_opus_5 compile_seconds "
         "70714.574 s (a host suspension mid-compile); the validator flags rows whose "
         "elapsed exceeds limit + 2 s without a timeout flag"]))

    fields.append(_field(
        "enhanced_tests.duration_seconds",
        "thesis/evaluation/run_enhanced_tests.py (per-spec run inside the worker thread)",
        "seconds", "wall time of ONE enhanced spec execution (run only, build separate)",
        "time.time (wall clock)", "inside the worker immediately before Popen",
        "after exit/kill", True, True,
        _includes(process_startup=True, launcher_overhead=True, runtime_initialization=True,
                  cpu_contention_from_parallel_samples=True),
        _suitable(),
        ["sum per stage (runtime cost)"],
        "observed elapsed + status='timeout' (exit_code null); limit = manifest "
        "stages.enhanced_tests.run_timeout_seconds",
        ["build_overview enhanced_seconds", "check_timing_semantics"],
        ["thread pool over SAMPLES (pilot: serial jobs=2): local queue wait is outside "
         "the timer, CPU contention is inside; therefore not a speed measure",
         "verdict-only specs legitimately carry no duration"]))

    fields.append(_field(
        "static_analysis.tools[<tool>].duration_seconds",
        "thesis/evaluation/tools.py (per tool; framework.run_command)",
        "seconds", "wall time of the analysis tool invocation(s) for one sample; the "
        "SCOPE differs per tool (see notes), so the includes map below is the union and "
        "must not be read per tool",
        "time.time (wall clock)", "before the tool process", "after exit/kill", True, True,
        _includes(process_startup=True, build=True),
        _suitable(),
        ["sum per tool (analysis cost)"],
        "observed elapsed + analysis_state=TIMEOUT (v3) / error string (legacy pilot_001)",
        ["build_overview runtime cost per tool"],
        ["STATIC_DURATION_IS_MODEL_SPEED = false: this is analysis cost, never a "
         "property of the model",
         "per-tool scope: parcoach records ONLY the parcoach step on success and ONLY "
         "the emit-llvm step on compile failure (includes.build is false there); "
         "cppcheck and clang_tidy perform no build of their own (includes.build false); "
         "compiler and gcc_analyzer ARE the build; infer builds under its capture. The "
         "includes map is therefore the union over the tools, not a per-tool statement",
         "per-tool timeouts (e.g. gcc_analyzer 300 s, parcoach 60 s) live in the "
         "manifest's stages.static_analysis.tools[<tool>] settings; the validator does "
         "not yet compare them, so a timeout row's elapsed is checked for finiteness "
         "and sign only",
         "not-applicable entries carry 0.0 with ran=false"]))

    fields.append(_field(
        "dynamic_analysis.tools[<tool>].duration_seconds",
        "thesis/evaluation/dynamic_tools.py (per tool; framework.run_command)",
        "seconds", "wall time of one dynamic tool's BUILD plus the SUM over its launch "
        "grid for one sample - a composite, not a single process",
        "time.time (wall clock)", "before the instrumented build",
        "after the last grid launch exits or is killed", True, True,
        _includes(process_startup=True, build=True, launcher_overhead=True,
                  runtime_initialization=True),
        _suitable(),
        ["sum per tool (analysis cost)"],
        "observed elapsed of the timed-out step + the tool's error/state; the per-tool "
        "limit lives in the manifest's stages.dynamic_analysis.tools[<tool>] settings",
        ["build_overview runtime cost per tool", "check_timing_semantics"],
        ["DYNAMIC_DURATION_IS_MODEL_SPEED = false; the number aggregates build and every "
         "launch-grid point, so it is not comparable with the single-process static field",
         "not-applicable entries carry 0.0 with ran=false"]))

    fields.append(_field(
        "assembly (no timing field)",
        "thesis/assembly/assemble_sources.py",
        "n/a", "assembly records carry created_at_utc only; assembly is not timed",
        "n/a", "n/a", "n/a", True, True, _includes(), _suitable(), ["none"], "n/a", [], []))

    contract = OrderedDict()
    contract["contract_version"] = TIMING_CONTRACT_VERSION
    contract["global_statements"] = OrderedDict([
        ("RUN_SECONDS_CROSS_EXECUTION_MODEL_COMPARABLE", False),
        ("CROSS_MODEL_LATENCY_RANKING",
         "AVAILABLE only among models whose generation ran in direct mode; "
         "NOT_AVAILABLE for a run that mixes direct and batch models"),
        ("BATCH_QUEUE_TIME_IS_MODEL_LATENCY", False),
        ("STATIC_DURATION_IS_MODEL_SPEED", False),
        ("DYNAMIC_DURATION_IS_MODEL_SPEED", False),
        ("STATIC_AND_DYNAMIC_TOOL_DURATIONS_ARE_COMPARABLE", False),
        ("TIMEOUT_STORES_OBSERVED_ELAPSED_NOT_LIMIT", True),
        ("CONFIGURED_LIMITS_SOURCE",
         "run manifest resolved_config: stages.correctness_tests.run_timeout_seconds and "
         "stages.enhanced_tests.run_timeout_seconds; the build limit comes from "
         "stages.correctness_tests.build_timeout_seconds when configured, else the 120 s "
         "code default. An effective --run-timeout CLI override is NOT persisted by the "
         "producer and must be declared to the validator"),
        ("PROVIDER_COST_RULE", "LLM usage tokens x configured price only; generation and "
                               "repair responses counted once each; missing usage stays null"),
        ("ABSOLUTE_CROSS_PILOT_RUNTIME_COMPARISON",
         "NOT_COMPARABLE unless host/container/compiler/grid/niter identities match the "
         "pinned runtime condition of both runs"),
        ("MPI_RUN_SECONDS_INCLUDE_LAUNCHER_OVERHEAD", True),
        ("OMP_RUN_SECONDS_INCLUDE_RUNTIME_INITIALIZATION", True),
        ("SERIAL_RUN_SECONDS_INCLUDE_PROCESS_STARTUP", True),
    ])
    contract["constants"] = OrderedDict([
        ("timeout_epsilon_seconds", TIMEOUT_EPSILON_SECONDS),
        ("wall_clock_anomaly_slack_seconds", WALL_CLOCK_ANOMALY_SLACK_SECONDS),
        ("build_timeout_default_seconds", BUILD_TIMEOUT_DEFAULT_SECONDS),
    ])
    contract["fields"] = fields
    contract["generation_timing_classes"] = OrderedDict([
        (DIRECT_LATENCY_AVAILABLE, "every generation record of the model is direct with a numeric duration"),
        (BATCH_QUEUE_ONLY, "every generation record of the model is batch (duration null, job stamps only)"),
        (MIXED_DIRECT_AND_BATCH, "the model's records mix both modes (latency distribution incomplete)"),
        (TIMING_PROVENANCE_INSUFFICIENT, "timing_mode missing/unknown or durations missing on direct records"),
        (TEST_RUNTIME_AVAILABLE, "correctness build and run timings present for the model"),
    ])
    return contract


def timing_contract_sha256(contract: "Optional[Dict[str, Any]]" = None) -> str:
    from thesis.evaluation.condition_hashing import canonical_sha256

    return canonical_sha256(contract or timing_contract())


def export(path) -> str:
    """Write timing_semantics.json (LF, content-addressed)."""
    from thesis.evaluation import atomic_io

    contract = timing_contract()
    payload = OrderedDict(list(contract.items()))
    payload["timing_contract_sha256"] = timing_contract_sha256(contract)
    atomic_io.atomic_write_json(path, payload)
    return payload["timing_contract_sha256"]


if __name__ == "__main__":
    import sys
    from pathlib import Path

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).with_name("timing_semantics.json")
    print("TIMING_CONTRACT_SHA256 =", export(target))
    print("written:", target)
