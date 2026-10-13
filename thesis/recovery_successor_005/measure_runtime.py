"""Phase-2 correctness and dynamic backfill of the static_feedback candidates
(full_ext_phase2_001, stages `correctness` and `dynamic`).

The static_feedback repair loops fed back only compiler/static findings, so
their 1,249 candidates were never tested at runtime. Phase 2 adds the two
missing runtime measurements as per-target, per-sample ledgers in the phase-2
tree. The native stage runners cannot be used as they are: run_correctness
UNLINKS its output and re-runs every sample, run_dynamic_analysis rewrites
its whole file per sample, and both write into the candidate's own
(protected) run directory - neither is missing-only nor crash-safe.

What stays native (the record CONTENT is exactly what the native runner
produces for that sample):
  correctness  run_correctness.run_sample, called with main()'s stage values
               (launch_overrides, niter, build/run timeout from the config;
               phase 2 has no CLI override, plan NONE) after main()'s
               toolchain gate, context with primary compiler g++.
  dynamic      main()'s tool resolution (register_dynamic_tools,
               resolve_enabled_tools, registry filter, apply_preflight_gate)
               and a 1:1 re-statement of the per-sample body of
               run_dynamic_analysis.run_model for a sample WITHOUT an
               existing record (phase 2 only fills whole missing records),
               calling the native helpers through the native module, so the
               key order and every value are the native ones.
Each ledger row = the native record (run_id = the candidate's source run)
+ the flat candidate provenance (targets.provenance) + `phase2_binding`.

Missing-only via ledger.missing_records: a historical record or a phase-2
row counts as present whatever its verdict/state (build_failed, timeout,
TOOL_ERROR ... are measurements). Crash safety: the torn tail is archived at
target start, one fsynced line per sample, the writer token is checked
before every write, and the candidate source is re-hashed right before its
row is written (a drift discards the measurement and stops the run).
Every target with missing records also gets an `invoked` line in the
per-model phase2_invocations.jsonl BEFORE its first record and a `completed`
/ `stopped` line after its last one (an append-only history cannot close an
entry in place), so a partial ledger of an interrupted invocation stays
attributed to the invocation that wrote it (an `invoked` line without a
close line). A complete target writes nothing.

Error classes: lineage.GlobalStop for every integrity / provenance / token /
binding conflict (refusals of the core modules are re-raised as GlobalStop),
EnvironmentError for a failed environment gate (always before any file is
touched). Any other exception of a native measurement propagates unchanged,
exactly as it would abort the native stage; the next invocation resumes
missing-only.

Main container only (python3.12); Python 3.8 syntax nonetheless.
"""
from __future__ import annotations

import hashlib
import uuid
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.evaluation import successor_writer as sw
from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import plan as pp
from thesis.recovery_successor_005 import targets as pt

CORRECTNESS = "correctness"
DYNAMIC = "dynamic"
STAGE_FILES = OrderedDict([(CORRECTNESS, pt.CORRECTNESS_FILE), (DYNAMIC, pt.DYNAMIC_FILE)])
# the native config stage of each phase-2 stage and its output_file_name default
CONFIG_STAGES = OrderedDict([(CORRECTNESS, ("correctness_tests", "correctness.jsonl")),
                             (DYNAMIC, ("dynamic_analysis", "dynamic_analysis.jsonl"))])
PRIMARY_COMPILER = "g++"  # the native default; phase 2 never overrides it
BINDING_FIELDS = ("contract_sha256", "authorization_sha256", "stage_runtime_sha256", "invocation_sha256")
INVOCATION_SCHEMA = "phase2_invocation.v1"
INVOCATIONS_FILE = "phase2_invocations.jsonl"
WRITER = "thesis.recovery_successor_005.measure_runtime"


def _now():
    from thesis.generation import common

    return common.utc_now_iso()


def _stop_requested(stop):
    return stop is not None and bool(stop())


# -- native settings and environment gates ---------------------------------------

def evaluation_context(root, config):
    """The EvaluationContext of both native main()s (primary compiler g++)."""
    from thesis.evaluation import framework

    root = Path(root).resolve()
    return framework.EvaluationContext(repo_root=root, drivers_cpp_dir=root / "drivers" / "cpp",
                                       primary_compiler=PRIMARY_COMPILER, config=config)


def correctness_settings(config):
    """run_correctness.main()'s stage values (the CLI run timeout does not
    exist in phase 2)."""
    from thesis.evaluation import run_correctness as rc

    stage = (config.get("stages") or {}).get("correctness_tests") or {}
    return OrderedDict([
        ("launch_overrides", stage.get("launch_overrides")),
        ("niter", int(stage.get("niter", rc.DEFAULT_NITER))),
        ("build_timeout", float(stage.get("build_timeout_seconds", rc.DEFAULT_BUILD_TIMEOUT))),
        ("run_timeout", float(stage.get("run_timeout_seconds", rc.DEFAULT_RUN_TIMEOUT))),
    ])


def correctness_gate(config):
    """run_correctness.main()'s toolchain gate over the configured sample
    universe: a missing compiler/mpirun would otherwise produce a full set
    of build_failed records that reads like model failures."""
    from thesis.evaluation import run_correctness as rc

    scoped_models = list((config.get("prompts") or {}).get("execution_models")
                         or ("serial", "omp", "mpi"))
    missing = rc.missing_toolchain(scoped_models, PRIMARY_COMPILER)
    if missing:
        raise EnvironmentError(
            "ENVIRONMENT GATE FAILED - aborting before any record is written. Missing toolchain "
            "for execution models %s: %s. The correctness stage runs inside the pareval-thesis "
            "container." % ("/".join(scoped_models), ", ".join(missing)))
    return scoped_models


def dynamic_tools(config, log=print):
    """run_dynamic_analysis.main()'s tool resolution and preflight gate
    (BEFORE any record): (usable settings in config order, tool instances)."""
    from thesis.evaluation import run_dynamic_analysis as rda

    rda.register_dynamic_tools()
    known = {}
    for name, settings in rda.resolve_enabled_tools(config, None).items():
        try:
            rda.framework.get_tool(name)
            known[name] = settings
        except KeyError:
            log("Tool '%s' configured but not implemented yet, skipping." % name)
    try:
        known, _skipped = rda.apply_preflight_gate(known, False)
    except rda.EnvironmentPreflightError as failure:
        raise EnvironmentError(str(failure)) from failure
    if not known:
        raise EnvironmentError("No usable dynamic tools after the environment gate - nothing to run.")
    return known, [rda.framework.get_tool(name) for name in known]


def _require_output_name(config, stage):
    """Presence is read from the native file names; a config that renamed
    the stage output would make the historical records invisible."""
    config_stage, default = CONFIG_STAGES[stage]
    name = ((config.get("stages") or {}).get(config_stage) or {}).get("output_file_name", default)
    if name != STAGE_FILES[stage]:
        raise pl.GlobalStop("config %s.output_file_name %r differs from the phase-2 ledger %s"
                            % (config_stage, name, STAGE_FILES[stage]))


# -- the native per-sample bodies ---------------------------------------------------

def dynamic_record(sample, context, run_id, model_id, tools, tool_settings, counts=None):
    """The per-sample body of run_dynamic_analysis.run_model, re-stated 1:1
    for a sample without an existing record (records.get(...) is None).
    `counts` receives the native per-tool summary counters."""
    from thesis.evaluation import run_dynamic_analysis as rda

    counts = counts if counts is not None else Counter()
    record = {
        "schema_version": rda.DYNAMIC_ANALYSIS_SCHEMA_VERSION,
        "run_id": run_id,
        "model_id": model_id,
        "sample_id": sample.sample_id,
        "execution_model": sample.execution_model,
        "tools": {},
    }
    record["created_at_utc"] = rda.common.utc_now_iso()
    record["schema_version"] = rda.DYNAMIC_ANALYSIS_SCHEMA_VERSION

    for tool in tools:
        settings = tool_settings[tool.name]
        if not settings.applies_to(sample.execution_model):
            record["tools"][tool.name] = rda.framework.ToolResult(
                tool=tool.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=(
                    f"not applicable: '{sample.execution_model}' outside "
                    "configured execution_models"
                ),
            ).to_dict()
            continue

        result = tool.run(sample, context)
        num_low_confidence = rda.mark_low_confidence(result.findings, settings)
        entry = result.to_dict()
        entry["num_low_confidence"] = num_low_confidence
        record["tools"][tool.name] = entry

        counts["findings." + tool.name] += len(result.findings)
        counts["blocking." + tool.name] += len(result.blocking_findings)
        if result.ran and result.error:
            counts["tool_errors." + tool.name] += 1

    record["has_blocking_findings"] = rda.record_has_blocking(record)
    record["low_confidence_count"] = rda.record_low_confidence_count(record)
    if record["has_blocking_findings"]:
        counts["samples_with_blocking"] += 1
    return record


def phase2_record(target, sample, record, binding):
    """native record + flat candidate provenance + phase2_binding. A native
    field is never overwritten; the identity must be the candidate's."""
    provenance = pt.provenance(target, sample.sample_id)
    clash = [key for key in list(provenance) + ["phase2_binding"] if key in record]
    if clash:
        raise pl.GlobalStop("native record of %s already carries %s" % (sample.sample_id, clash))
    if (record.get("run_id") != target.source_run or record.get("model_id") != target.model_id
            or record.get("sample_id") != sample.sample_id):
        raise pl.GlobalStop("native record identity differs from the candidate " + sample.sample_id)
    record.update(provenance)
    record["phase2_binding"] = OrderedDict(binding)
    return record


def source_unchanged(target, sample):
    """The candidate bytes still hash to the frozen table (checked right
    before the row is written: a drift during the measurement discards it)."""
    expected = target.samples[sample.sample_id]["source_sha256"]
    try:
        actual = hashlib.sha256(Path(sample.source_path).read_bytes()).hexdigest()
    except OSError as exc:
        raise pl.GlobalStop("candidate source unreadable after measuring %s: %s" % (sample.sample_id, exc))
    if actual != expected:
        raise pl.GlobalStop("candidate source drifted while it was measured: " + sample.sample_id)
    return True


# -- invocation history -------------------------------------------------------------

def invocations_path(root, model):
    if not model or "/" in model or "\\" in model or model.startswith("."):
        raise RecoveryRefused("invalid model id for the phase-2 invocation history")
    return pl.require_writable(root, "%s/%s/%s" % (pl.RESULTS_REL, model, INVOCATIONS_FILE))


def _invocation_row(target, stage, invocation_id, status, started, completed, counts, binding):
    return OrderedDict([
        ("schema_version", INVOCATION_SCHEMA),
        ("run_id", pl.SUCCESSOR),
        ("model_id", target.model_id),
        ("stage", stage),
        ("target_id", target.target_id),
        ("candidate_source_run", target.source_run),
        ("ledger", STAGE_FILES[stage]),
        ("invocation_id", invocation_id),
        ("status", status),
        ("writer", WRITER),
        ("started_at_utc", started),
        ("completed_at_utc", completed),
        ("counts", counts),
        ("phase2_binding", OrderedDict(binding)),
    ])


def _append(root, authority, path, row):
    sw.require_token(root, pl.SUCCESSOR, authority.token)
    sw.durable_append_jsonl(path, row)


# -- driver ---------------------------------------------------------------------------

def _select(table, targets, stage, counts, log):
    """The given targets (default: the whole table), each verified to be the
    frozen table's own target BEFORE anything runs; targets the design does
    not assign this stage to are skipped."""
    chosen = table.targets if targets is None else list(targets)
    selected = []
    for target in chosen:
        try:
            frozen = table.get(target.target_id)
        except RecoveryRefused as exc:
            raise pl.GlobalStop("foreign phase-2 target: %s" % exc) from exc
        if frozen.document != target.document or target.source_run in pl.EXCLUDED_HISTORICAL_RUNS:
            raise pl.GlobalStop("target %s differs from the frozen table" % target.target_id)
        if stage not in pp.assigned_stages(target):
            counts["skipped_unassigned"] += 1
            continue
        selected.append(target)
    log("%s: %d target(s) selected, %d not assigned to the stage"
        % (stage, len(selected), counts["skipped_unassigned"]))
    return selected


def _enforce(authority, stage, model):
    """authority.enforce once per (stage, model) and invocation, before the
    first record; the record binding must be the enforced one."""
    facts = authority.enforce(stage, model) or {}
    binding = authority.binding(stage, model)
    for key in BINDING_FIELDS:
        if not binding.get(key) or facts.get(key) != binding.get(key):
            raise pl.GlobalStop("phase-2 binding of %s/%s disagrees with its enforcement (%s)"
                                % (stage, model, key))


def _run_target(root, authority, target, stage, measure, invocation_id, log, stop, counts):
    """Missing-only records of one target; True if stop() ended it early."""
    file_name = STAGE_FILES[stage]
    model = target.model_id
    path = pt.ledger_path(root, model, target.source_run, file_name)
    sw.require_token(root, pl.SUCCESSOR, authority.token)
    archived = sw.archive_torn_tail(path)
    if archived:
        log("archived a torn tail (%d bytes) of %s" % (archived, path))
    missing = pg.missing_records(root, target, file_name)
    present = len(target.samples) - len(missing)
    counts["targets"] += 1
    counts["present"] += present
    if not missing:
        counts["targets_complete"] += 1
        log("%s %s: complete (%d present)" % (stage, target.target_id, present))
        return False
    pending = set(missing)
    samples = [sample for sample in pt.assembled_samples(root, target) if sample.sample_id in pending]
    if [sample.sample_id for sample in samples] != missing:
        raise pl.GlobalStop("assembled samples do not cover the missing %s records of %s"
                            % (stage, target.target_id))
    binding = authority.binding(stage, model)
    history = invocations_path(root, model)
    sw.require_token(root, pl.SUCCESSOR, authority.token)
    archived = sw.archive_torn_tail(history)
    if archived:
        log("archived a torn tail (%d bytes) of %s" % (archived, history))
    started = _now()
    opened = OrderedDict([("missing", len(missing)), ("present", present)])
    _append(root, authority, history,
            _invocation_row(target, stage, invocation_id, "invoked", started, None, opened, binding))
    log("%s %s: %d missing, %d present" % (stage, target.target_id, len(missing), present))
    local = Counter()
    stopped = False
    for sample in samples:
        if local["written"] and _stop_requested(stop):
            stopped = True
            break
        record = measure(target, sample, local)
        source_unchanged(target, sample)
        record = phase2_record(target, sample, record, binding)
        _append(root, authority, path, record)
        local["written"] += 1
    closed = OrderedDict(opened)
    closed.update(sorted(local.items()))
    closed["written"] = local["written"]
    _append(root, authority, history,
            _invocation_row(target, stage, invocation_id, "stopped" if stopped else "completed",
                            started, _now(), closed, binding))
    counts.update(local)
    log("%s %s: %d written%s" % (stage, target.target_id, local["written"],
                                 " (stopped on request)" if stopped else ""))
    return stopped


def _run_stage(root, table, authority, targets, stage, measure, log, stop):
    root = Path(root).resolve()
    counts = Counter()
    selected = _select(table, targets, stage, counts, log)
    invocation_id = uuid.uuid4().hex
    enforced = set()
    for target in selected:
        if _stop_requested(stop):
            counts["stopped"] = 1
            log("%s: stop requested before %s" % (stage, target.target_id))
            break
        try:
            authority.check()
            if target.model_id not in enforced:
                _enforce(authority, stage, target.model_id)
                enforced.add(target.model_id)
            stopped = _run_target(root, authority, target, stage, measure, invocation_id, log, stop, counts)
        except pl.GlobalStop:
            raise
        except RecoveryRefused as exc:
            raise pl.GlobalStop("%s %s refused: %s" % (stage, target.target_id, exc)) from exc
        if stopped:
            counts["stopped"] = 1
            break
    log("%s: %s" % (stage, ", ".join("%s=%d" % item for item in sorted(counts.items()))))
    return counts


def run_correctness(root, config, table, authority, targets=None, log=print, stop=None):
    """Missing correctness records of the static_feedback targets (default:
    every target of the table the stage is assigned to) -> Counter."""
    from thesis.evaluation import run_correctness as rc

    _require_output_name(config, CORRECTNESS)
    settings = correctness_settings(config)
    correctness_gate(config)
    context = evaluation_context(root, config)
    log("phase-2 correctness | niter=%d | build timeout %ss | run timeout %ss | launch overrides %r"
        % (settings["niter"], settings["build_timeout"], settings["run_timeout"],
           settings["launch_overrides"]))

    def measure(target, sample, counts):
        try:
            record = rc.run_sample(sample, context, settings["launch_overrides"], settings["niter"],
                                   settings["build_timeout"], settings["run_timeout"])
        except rc.HarnessTransportError as exc:
            raise pl.GlobalStop("harness transport defect on %s: %s" % (sample.sample_id, exc)) from exc
        counts["verdict.%s" % record.get("verdict")] += 1
        log("  correctness %s: %s" % (sample.sample_id, record.get("verdict")))
        return record

    return _run_stage(root, table, authority, targets, CORRECTNESS, measure, log, stop)


def run_dynamic(root, config, table, authority, targets=None, log=print, stop=None):
    """Missing dynamic-analysis records of the static_feedback targets
    (default: every target of the table the stage is assigned to) -> Counter."""
    _require_output_name(config, DYNAMIC)
    tool_settings, tools = dynamic_tools(config, log)
    context = evaluation_context(root, config)
    log("phase-2 dynamic | tools: " + ", ".join(
        "%s[%s]" % (name, "/".join(s.execution_models)) for name, s in tool_settings.items()))

    def measure(target, sample, counts):
        record = dynamic_record(sample, context, target.source_run, target.model_id, tools,
                                tool_settings, counts)
        log("  dynamic %s: blocking=%s low_confidence=%d"
            % (sample.sample_id, record["has_blocking_findings"], record["low_confidence_count"]))
        return record

    return _run_stage(root, table, authority, targets, DYNAMIC, measure, log, stop)
