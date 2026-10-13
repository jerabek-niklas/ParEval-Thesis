"""Held-out enhanced tests of phase 2 (full_ext_phase2_001) for every
target, through the UNCHANGED native building blocks of
thesis/evaluation/run_enhanced_tests.py.

Native (taken 1:1 from run_enhanced_tests.main):
  * the setup: capability-policy preflight first, stage settings, run
    timeout, jobs = config only (resolve_jobs WITHOUT a CLI override - the
    jobs map is part of fingerprint component G), the frozen spec artifact
    as specs path (the SAME str as main's --specs default, so component A
    is identical), the global execution fingerprint, the toolchain gate,
    MISMATCH_REPORT_MAX, the LLM specs and the serial signatures;
  * ONE gate_cache / wrapper_cache for the whole invocation, all targets and
    models (main shares them across models in one process; never persisted);
  * the sample filter (execution-model scope, parameterizable cpu.cc), the
    serial gate precomputation before any pool, one ThreadPoolExecutor per
    execution model with the config jobs, process_sample per sample, the
    cancel-on-exception handling, appends by the MAIN thread only;
  * the per-target summary shape.

Phase-2 differences (and why):
  * identity: one target = (model, source_run). Records keep run_id =
    source_run as native and gain the flat candidate provenance
    (targets.provenance) + phase2_binding; group rows the provenance only.
    Every row goes durably (fsync) into the phase-2 tree only
    (targets.ledger_path) under the writer token, after the candidate source
    bytes were re-checked.
  * missing-only work from ledger.missing_enhanced: a present row counts
    whatever its status (gated, build_failed, timeout ...) and is never
    re-measured.
  * main's run manifest / register_model_execution would write into the
    historical run tree; they are replaced by the phase-2 contract (the
    authority) and a per-target REGISTRATION sidecar written atomically
    BEFORE the first record. A resume under another model execution
    condition (execution_provenance.model_resume_allowed) is a GlobalStop,
    never a mixed ledger. It also closes main's resume dead end (main's only
    fingerprint evidence is the summary, written after the model completes).
  * precompute_gates runs per worklist entry: identical cache contents and
    order (its loop carries no state across entries besides the shared
    caches), but stop() is honoured between samples in the serial gate
    phase too.

Main container only (python 3.12).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from thesis.enhanced_tests import capabilities
from thesis.enhanced_tests import execution_provenance as execprov
from thesis.enhanced_tests.specs import spec_key, stage_settings
from thesis.evaluation import run_enhanced_tests as ret
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.generation import common
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt

STAGE = "enhanced"
REGISTRATION_SCHEMA = "phase2_enhanced_registration.v1"
PRIMARY_COMPILER = "g++"
PARAMETERIZABLE_MARKER = "ENHANCED_TEST_SIZE_DEFAULT"
REPORTED_STATUSES = ("pass", "fail", "crash", "timeout", "runtime_error", "build_failed",
                     "baseline_incompatible", "numerically_unstable")
BINDING_FIELDS = ("contract_sha256", "authorization_sha256", "stage_runtime_sha256", "invocation_sha256")
# a registration is the condition of exactly one target
IDENTITY_FIELDS = ("schema_version", "run_id", "target_id", "model_id", "candidate_source_run",
                   "variant", "iteration")


def _never():
    return False


def _refused(target, error):
    """A refusal of a core helper (token, table, source hash, ledger) stops
    the whole run."""
    return pl.GlobalStop("enhanced %s refused: %s" % (target.target_id if target else "-", error))


# -- invocation setup (main()'s order) ------------------------------------------

def native_setup(config, log=print):
    """main()'s invocation setup without a CLI. The policy preflight comes
    first; a stale policy or a missing toolchain is an EnvironmentError
    before anything is written."""
    try:
        policy = capabilities.policy_preflight()
    except capabilities.EnhancedPolicyError as error:
        raise EnvironmentError("ENHANCED CAPABILITY POLICY PREFLIGHT FAILED - aborting before any "
                               "record, registration or build artifact is written.\n%s" % error)
    log("Enhanced capability policy: %s | %d benchmarks | sha256 %s"
        % (policy["enhanced_policy_status"], policy["enhanced_policy_benchmark_count"],
           str(policy["enhanced_policy_sha256"])[:16]))
    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    settings = stage_settings(config)
    # the phase-2 ledger names are the native default names (summary and
    # build groups derived exactly as main derives them)
    output_name = stage.get("output_file_name", "enhanced_tests.jsonl")
    if (output_name != pt.ENHANCED_FILE
            or ret.derived_file_names(output_name) != (pt.ENHANCED_GROUPS_FILE, pt.ENHANCED_SUMMARY_FILE)):
        raise pl.GlobalStop("enhanced output names differ from the native names: %r" % output_name)
    target_cases = int(settings["target_cases_per_benchmark"])
    run_timeout = float(stage.get("run_timeout_seconds", ret.DEFAULT_RUN_TIMEOUT))
    execution_models = list(settings["execution_models"])
    launch_settings = dict(settings["enhanced_launch"])
    jobs = ret.resolve_jobs(settings, None)
    specs_path = str(ret.DEFAULT_SPECS_PATH)
    execution_provenance = execprov.enhanced_execution_fingerprint(
        specs_path, settings, runtime={"run_timeout_seconds": run_timeout, "effective_jobs": jobs},
        primary_compiler=PRIMARY_COMPILER)
    log("Enhanced execution fingerprint: %s"
        % execution_provenance["enhanced_execution_fingerprint_sha256"][:16])
    missing = ret.missing_toolchain(execution_models, primary_compiler=PRIMARY_COMPILER)
    if missing:
        raise EnvironmentError("ENVIRONMENT GATE FAILED - aborting before any record is written. Missing "
                               "toolchain for execution models %s: %s"
                               % ("/".join(execution_models), ", ".join(missing)))
    mismatch_k = int(((config.get("stages") or {}).get("repair") or {})
                     .get("feedback", {}).get("mismatch_report_max_indices", 3))
    effective_config = dict(settings)
    effective_config.update({"jobs": jobs, "run_timeout_seconds": run_timeout, "specs_file": specs_path})
    return OrderedDict([
        ("policy_provenance", policy), ("settings", settings), ("target_cases", target_cases),
        ("run_timeout", run_timeout), ("execution_models", execution_models),
        ("launch_settings", launch_settings), ("jobs", jobs), ("specs_path", specs_path),
        ("execution_provenance", execution_provenance), ("mismatch_k", mismatch_k),
        ("effective_config", effective_config),
        ("llm_specs", ret.load_llm_specs(Path(specs_path))),
        ("signatures", ret.load_serial_signatures()),
    ])


# -- atomic sidecars ----------------------------------------------------------------

def _write_json_atomic(root, target, name, document):
    """Temp file + fsync + os.replace inside the phase-2 tree (same JSON
    format as common.write_json)."""
    path = pt.ledger_path(root, target.model_id, target.source_run, name)
    temporary = pt.ledger_path(root, target.model_id, target.source_run, name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(temporary), "wb") as handle:
        handle.write(json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(temporary), str(path))
    try:
        descriptor = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return path
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
    return path


def _check_candidate(target, candidate):
    """The native candidate fingerprint covers exactly the table's samples
    with the table's source hashes."""
    rows = candidate.get("samples") or []
    if (candidate.get("missing_source_count") or candidate.get("sample_count") != len(target.samples)
            or sorted(row["sample_id"] for row in rows) != sorted(target.samples)):
        raise RecoveryRefused("candidate fingerprint does not cover the frozen target")
    for row in rows:
        facts = target.samples[row["sample_id"]]
        if (row["source_sha256"] != facts["source_sha256"] or row["execution_model"] != facts["execution_model"]
                or row["benchmark"] != facts["benchmark"]):
            raise RecoveryRefused("candidate fingerprint disagrees with the table: " + row["sample_id"])


class _Prepared:
    """Per-target state: paths, worklist and the present (sample, key) set."""

    def __init__(self, paths, model_execution, worklist, written, counts, samples_seen, resumed_rows):
        self.paths = paths
        self.model_execution = model_execution
        self.worklist = worklist
        self.written = written
        self.counts = counts
        self.samples_seen = samples_seen
        self.resumed_rows = resumed_rows


class _Invocation:
    def __init__(self, root, config, setup, authority, log, stop):
        self.root = root
        self.config = config
        self.setup = setup
        self.authority = authority
        self.log = log
        self.stop = stop
        # ONE gate/wrapper cache for the whole invocation (as main: shared
        # across models, never persisted); spec_cache = main's specs_by_benchmark
        self.gate_cache = {}
        self.wrapper_cache = {}
        self.spec_cache = {}
        self.enforced = set()
        self.totals = Counter()

    # -- writing ---------------------------------------------------------------

    def _require_token(self):
        try:
            sw.require_token(self.root, pl.SUCCESSOR, self.authority.token)
        except pl.GlobalStop:
            raise
        except RecoveryRefused as error:
            raise _refused(None, error) from error

    def _append_row(self, path, row):
        self._require_token()
        try:
            sw.durable_append_jsonl(path, row)
        except pl.GlobalStop:
            raise
        except RecoveryRefused as error:
            raise _refused(None, error) from error

    # -- registration ------------------------------------------------------------

    def _registration(self, target, model_execution, binding):
        return OrderedDict([
            ("schema_version", REGISTRATION_SCHEMA),
            ("run_id", pl.SUCCESSOR),
            ("target_id", target.target_id),
            ("model_id", target.model_id),
            ("candidate_source_run", target.source_run),
            ("variant", target.variant),
            ("iteration", target.iteration),
            ("specs_file", self.setup["specs_path"]),
            ("effective_config", self.setup["effective_config"]),
            ("enhanced_policy_provenance", dict(self.setup["policy_provenance"])),
            ("enhanced_execution_provenance", dict(self.setup["execution_provenance"])),
            ("enhanced_model_execution_provenance", dict(model_execution)),
            ("registered_binding", binding),
            ("registered_at_utc", common.utc_now_iso()),
        ])

    def _register(self, target, paths, model_execution, binding):
        """Present: the recorded model execution condition must allow the
        resume (fail-closed). Absent: no row may exist yet; the sidecar is
        written atomically before the first record."""
        path = paths[pt.ENHANCED_REGISTRATION_FILE]
        current = self._registration(target, model_execution, binding)
        if path.is_file():
            try:
                recorded = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                recorded = None
            if not isinstance(recorded, dict):
                raise pl.GlobalStop("unreadable enhanced registration of " + target.target_id)
            foreign = [f for f in IDENTITY_FIELDS if recorded.get(f) != current[f]]
            if foreign:
                raise pl.GlobalStop("enhanced registration of %s carries a foreign %s"
                                    % (target.target_id, ", ".join(foreign)))
            allowed, why = execprov.model_resume_allowed(
                recorded.get("enhanced_model_execution_provenance"), model_execution)
            if not allowed:
                raise pl.GlobalStop(
                    "enhanced RESUME REFUSED for %s: registered model execution fingerprint %s, current %s "
                    "(%s). spec_key does not encode the execution condition; results are never mixed."
                    % (target.target_id, execprov.model_fingerprint_sha(
                        recorded.get("enhanced_model_execution_provenance")),
                       model_execution["model_execution_fingerprint_sha256"], why))
            return False
        for name in (pt.ENHANCED_FILE, pt.ENHANCED_GROUPS_FILE):
            if paths[name].is_file() and paths[name].stat().st_size:
                raise pl.GlobalStop("enhanced rows of %s exist without a registration (%s)"
                                    % (target.target_id, name))
        self._require_token()
        _write_json_atomic(self.root, target, pt.ENHANCED_REGISTRATION_FILE, current)
        self.log("[%s] enhanced registration written (model execution fingerprint %s)"
                 % (target.target_id, model_execution["model_execution_fingerprint_sha256"][:16]))
        return True

    # -- per target ----------------------------------------------------------------

    def _prepare(self, target, binding):
        model = target.model_id
        self._require_token()
        samples = pt.assembled_samples(self.root, target)
        candidate = execprov.candidate_source_fingerprint(
            self.root / pt.INTERMEDIATE_REL, target.source_run, model, repo_root=self.root)
        _check_candidate(target, candidate)
        model_execution = execprov.model_execution_fingerprint(self.setup["execution_provenance"], candidate)
        paths = OrderedDict((name, pt.ledger_path(self.root, model, target.source_run, name))
                            for name in (pt.ENHANCED_FILE, pt.ENHANCED_GROUPS_FILE,
                                         pt.ENHANCED_REGISTRATION_FILE, pt.ENHANCED_SUMMARY_FILE))
        self._register(target, paths, model_execution, binding)
        for name in (pt.ENHANCED_FILE, pt.ENHANCED_GROUPS_FILE):
            archived = sw.archive_torn_tail(paths[name])
            if archived:
                self.log("[%s] archived a torn tail of %d byte(s) from %s" % (target.target_id, archived, name))
        llm_specs = self.setup["llm_specs"]
        expected = pg.expected_enhanced(self.root, self.config, target, llm_specs, self.spec_cache)
        missing = pg.missing_enhanced(self.root, self.config, target, llm_specs, self.spec_cache)
        written = set()
        for sample_id, specs in expected.items():
            pending = set(pg.key_text(spec_key(spec)) for spec in missing.get(sample_id, ()))
            written.update((sample_id, key) for key in specs if key not in pending)
        counts = Counter()
        samples_seen = 0
        seen = []
        worklist = []
        execution_models = self.setup["execution_models"]
        for sample in samples:
            if sample.execution_model not in execution_models:
                continue
            benchmark = "%s/%s" % (sample.problem_type, sample.name)
            cpu_cc = sample.benchmark_dir / "cpu.cc"
            if not cpu_cc.exists() or PARAMETERIZABLE_MARKER not in cpu_cc.read_text(encoding="utf-8"):
                counts["benchmark_not_parameterizable"] += 1
                continue
            samples_seen += 1
            seen.append(sample.sample_id)
            if sample.sample_id not in expected or benchmark != target.samples[sample.sample_id]["benchmark"]:
                raise pl.GlobalStop("enhanced scope of %s disagrees with ledger.expected_enhanced: %s"
                                    % (target.target_id, sample.sample_id))
            specs = self.spec_cache[benchmark]
            if len(specs) < self.setup["target_cases"]:
                self.log("  [%s] under_target: %d/%d specs (mutation space exhausted)"
                         % (benchmark, len(specs), self.setup["target_cases"]))
            pending = missing.get(sample.sample_id)
            if pending:
                worklist.append((sample, benchmark, pending))
        if seen != list(expected):
            raise pl.GlobalStop("enhanced scope of %s disagrees with ledger.expected_enhanced"
                                % target.target_id)
        return _Prepared(paths, model_execution, worklist, written, counts, samples_seen, len(written))

    def target(self, target):
        """True when the target is complete, False when stop() interrupted it."""
        model = target.model_id
        self.authority.check()
        if model not in self.enforced:
            facts = self.authority.enforce(STAGE, model) or {}
            binding = self.authority.binding(STAGE, model)
            if any(not binding.get(k) or facts.get(k) != binding.get(k) for k in BINDING_FIELDS):
                raise pl.GlobalStop("phase-2 binding of %s/%s disagrees with its enforcement" % (STAGE, model))
            self.enforced.add(model)
        binding = self.authority.binding(STAGE, model)
        try:
            prepared = self._prepare(target, binding)
        except pl.GlobalStop:
            raise
        except RecoveryRefused as error:
            raise _refused(target, error) from error
        summary_path = prepared.paths[pt.ENHANCED_SUMMARY_FILE]
        pairs = sum(len(entry[2]) for entry in prepared.worklist)
        self.log("[%s] enhanced: %d sample(s) in scope, %d present (sample, spec) row(s), %d pending pair(s) "
                 "in %d sample(s)" % (target.target_id, prepared.samples_seen, prepared.resumed_rows, pairs,
                                      len(prepared.worklist)))
        self.totals["benchmark_not_parameterizable"] += prepared.counts["benchmark_not_parameterizable"]
        if not prepared.worklist and summary_path.is_file():
            self.totals["targets_complete"] += 1
            return True
        for entry in prepared.worklist:
            if self.stop():
                return False
            self.totals["gates_computed"] += ret.precompute_gates(
                [entry], self.gate_cache, self.wrapper_cache, self.setup["signatures"], self.setup["mismatch_k"])
        if not self._pools(target, prepared, binding):
            return False
        counts = prepared.counts
        for status in REPORTED_STATUSES:
            if counts.get(status):
                self.log("    %s: %d" % (status, counts[status]))
        self._summary(target, prepared, binding)
        self.totals["targets_complete"] += 1
        return True

    def _pools(self, target, prepared, binding):
        setup = self.setup
        for execution_model in setup["execution_models"]:
            entries = [entry for entry in prepared.worklist if entry[0].execution_model == execution_model]
            if not entries:
                continue
            if self.stop():
                return False
            workers = int(setup["jobs"].get(execution_model, 1))
            if execution_model == "omp":
                ranks = int(setup["launch_settings"]["omp_threads"])
            elif execution_model == "mpi":
                ranks = int(setup["launch_settings"]["mpi_ranks"])
            else:
                ranks = 1
            cores = (len(os.sched_getaffinity(0)) or 1) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
            effective = min(workers, len(entries))
            if effective * ranks > cores:
                self.log("[%s] INFO: %s jobs=%d x %d threads/ranks = %d > %d cores - overcommit can turn into "
                         "timeouts in the results" % (target.target_id, execution_model, effective, ranks,
                                                       effective * ranks, cores))
            started = time.time()
            stopped = False
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = OrderedDict()
                for sample, benchmark, pending in entries:
                    future = pool.submit(ret.process_sample, sample, benchmark, pending, self.gate_cache,
                                         target.source_run, target.model_id, setup["mismatch_k"],
                                         setup["run_timeout"], setup["launch_settings"])
                    futures[future] = (sample, pending)
                # ONLY this thread appends; a worker exception or an interrupt
                # cancels the queue (the with-block then waits only for the <=
                # jobs running workers, whose results are redone on resume)
                try:
                    for future in as_completed(futures):
                        sample, pending = futures[future]
                        try:
                            records, group_rows = future.result()
                        except Exception as error:
                            # native main dies here (harness transport defect,
                            # build/launch environment): never a model result
                            raise pl.GlobalStop("enhanced %s: worker failed on %s: %s: %s"
                                                % (target.target_id, sample.sample_id,
                                                   type(error).__name__, error)) from error
                        self._append(target, prepared, binding, sample, pending, records, group_rows)
                        if self.stop():
                            cancelled = sum(1 for other in futures if other.cancel())
                            self.log("[%s] stop requested: %d queued sample(s) cancelled; running samples are "
                                     "discarded and redone on resume" % (target.target_id, cancelled))
                            stopped = True
                            break
                except BaseException:
                    for other in futures:
                        other.cancel()
                    raise
            self.log("[%s] %s: %d sample(s) in %.1fs wall (jobs=%d)"
                     % (target.target_id, execution_model, len(entries), time.time() - started, workers))
            if stopped:
                return False
        return True

    def _append(self, target, prepared, binding, sample, pending, records, group_rows):
        """Validate one sample's native result, re-check its source bytes,
        then append its group rows and records durably."""
        sample_id = sample.sample_id
        try:
            keys = [pg.key_text(spec_key(record["spec"])) for record in records]
        except (KeyError, TypeError, ValueError):
            raise pl.GlobalStop("malformed enhanced record for " + sample_id)
        if sorted(keys) != sorted(pg.key_text(spec_key(spec)) for spec in pending):
            raise pl.GlobalStop("enhanced records of %s do not cover exactly its pending specs" % sample_id)
        if any(record.get("sample_id") != sample_id or record.get("run_id") != target.source_run
               or record.get("model_id") != target.model_id or not record.get("status") for record in records):
            raise pl.GlobalStop("foreign enhanced record for " + sample_id)
        if any(row.get("sample_id") != sample_id for row in group_rows):
            raise pl.GlobalStop("foreign enhanced build-group row for " + sample_id)
        if any((sample_id, key) in prepared.written for key in keys):
            raise pl.GlobalStop("duplicate enhanced (sample, spec) for " + sample_id)
        source_sha = hashlib.sha256(sample.source_path.read_bytes()).hexdigest()
        if source_sha != target.samples[sample_id]["source_sha256"]:
            raise pl.GlobalStop("candidate source changed during the enhanced measurement: " + sample_id)
        provenance = pt.provenance(target, sample_id)
        for row in group_rows:
            row.update(provenance)
            self._append_row(prepared.paths[pt.ENHANCED_GROUPS_FILE], row)
            self.totals["group_rows"] += 1
        for record, key in zip(records, keys):
            record.update(provenance)
            record["phase2_binding"] = binding
            self._append_row(prepared.paths[pt.ENHANCED_FILE], record)
            prepared.written.add((sample_id, key))
            prepared.counts[record["status"]] += 1
            self.totals[record["status"]] += 1
            self.totals["rows"] += 1
        self.totals["samples"] += 1

    def _summary(self, target, prepared, binding):
        setup = self.setup
        summary = OrderedDict([
            ("schema_version", ret.ENHANCED_SCHEMA_VERSION + ".summary"),
            ("run_id", target.source_run),
            ("model_id", target.model_id),
            ("created_at_utc", common.utc_now_iso()),
            ("counts", dict(prepared.counts)),
            ("samples_seen", prepared.samples_seen),
            ("resumed_rows", prepared.resumed_rows),
            ("timing_semantics", ret.TIMING_SEMANTICS),
            ("build_groups_file", pt.ENHANCED_GROUPS_FILE),
            ("legacy_mixed_rows", 0),
            ("effective_config", setup["effective_config"]),
            ("enhanced_policy_provenance", dict(setup["policy_provenance"])),
            ("enhanced_execution_provenance", dict(setup["execution_provenance"])),
            ("enhanced_model_execution_provenance", dict(prepared.model_execution)),
        ])
        # the target-level part of targets.provenance (the per-sample source
        # facts live on every record)
        summary["writer_run_id"] = pl.SUCCESSOR
        summary["authority_run_id"] = pl.SUCCESSOR
        summary["candidate_source_run"] = target.source_run
        summary["variant"] = target.variant
        summary["iteration"] = target.iteration
        summary["target_id"] = target.target_id
        summary["registration_file"] = pt.ENHANCED_REGISTRATION_FILE
        summary["phase2_binding"] = binding
        self._require_token()
        _write_json_atomic(self.root, target, pt.ENHANCED_SUMMARY_FILE, summary)


def run_enhanced(root, config, table, authority, targets, log=print, stop=None):
    """Enhanced tests for the given targets (in the given order), missing-only.
    Returns a Counter (record statuses, rows, group_rows, samples,
    gates_computed, targets_complete, benchmark_not_parameterizable, and
    stopped=1 when stop() ended the invocation early).

    Raises EnvironmentError (policy / toolchain gate, before anything is
    written) or lineage.GlobalStop (integrity, provenance, token, condition
    conflict, and a worker exception - where native main dies; the rows
    already appended stay, the rest is redone missing-only on resume)."""
    root = Path(root).resolve()
    stop = stop or _never
    targets = list(targets)
    setup = native_setup(config, log)
    for target in targets:
        try:
            frozen = table.get(target.target_id)
        except pl.GlobalStop:
            raise
        except RecoveryRefused as error:
            raise _refused(target, error) from error
        if frozen.document != target.document:
            raise pl.GlobalStop("target %s differs from the frozen table" % target.target_id)
    local_specs = pg.frozen_specs_path(root)
    if (local_specs.is_file() and local_specs.resolve() != Path(setup["specs_path"]).resolve()
            and local_specs.read_bytes() != Path(setup["specs_path"]).read_bytes()):
        raise pl.GlobalStop("the repository's frozen enhanced specs differ from the runner's specs file")
    run = _Invocation(root, config, setup, authority, log, stop)
    log("Enhanced tests | %d target(s) | execution models: %s | jobs: %s"
        % (len(targets), "/".join(setup["execution_models"]),
           ",".join("%s=%d" % (m, setup["jobs"][m]) for m in setup["execution_models"])))
    for target in targets:
        if stop() or not run.target(target):
            run.totals["stopped"] = 1
            log("enhanced: stop requested - ending cleanly after %d complete target(s)"
                % run.totals["targets_complete"])
            break
    return run.totals


def expected_totals(root, config, table, llm_specs=None):
    """(samples, pairs) the enhanced stage must hold for the whole table
    (ledger.expected_enhanced over the runner's frozen specs)."""
    llm_specs = llm_specs if llm_specs is not None else ret.load_llm_specs(Path(str(ret.DEFAULT_SPECS_PATH)))
    cache = {}
    samples = pairs = 0
    for target in table.targets:
        expected = pg.expected_enhanced(root, config, target, llm_specs, cache)
        samples += len(expected)
        pairs += sum(len(specs) for specs in expected.values())
    return samples, pairs
