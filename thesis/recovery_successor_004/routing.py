"""Successor repair loop: FRESH native loops of the five unstarted models.

Read/write separation (the core invariant):

    iteration 0  parent full_ext_001 evidence (generations, assembly, static
                 incl. PARCOACH/LLOV, correctness, dynamic, sources), read
                 through the recovery_001 parent lineage (size + raw sha256
                 on every read)                  READ ONLY, NEVER RE-MEASURED
    decisions    iteration-0 decisions and the wave state are native
                 successor-owned loop state (exactly what recovery_001 wrote
                 natively for its models)               SUCCESSOR WRITES
    iterations   full_ext_recovery_004__<variant>__iter1 / __iter2 requests,
    1 and 2      answers, assemblies, analyses           SUCCESSOR WRITES
    ledgers      one durable submission-intent ledger PER provider
                 iteration (iter1/submissions.jsonl, iter2/submissions.jsonl);
                 the native round count (request_rounds.json) is DERIVED from
                 them and only mirrored

The native state machine (orchestrator.RepairLoop) is reused unchanged; this
subclass routes iteration-0 reads, refuses every write that would touch
parent evidence, records a submission intent durably before each provider
call, re-verifies authority and every protected byte on every step, and
pauses a provider lane (before any intent) after consecutive transport
failures so an outage never burns the native retry budget of every sample.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import atomic_io
from thesis.recovery_successor_004 import handoff as sh
from thesis.recovery_successor_004 import lineage as sl
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.condition_hashing import canonical_sha256, utf8_sha256
from thesis.evaluation.recovery_lineage import PARENT, RecoveryRefused, checked_path
from thesis.repair import orchestrator

SUBMISSION_SCHEMA = "successor_submission_intent.v2"
STATE_FIELDS = ("status", "stop_reason", "counts", "test_verdict", "low_confidence_keys",
                "analysis_gaps")
REQUEST_FIELDS = ("sample_id", "variant", "iteration", "built_from_iteration", "strategy", "request",
                  "request_chars")
# consecutive transport failures in one provider lane before the lane pauses
# (checked BEFORE an intent is written: a paused lane consumes no round)
LANE_TRIP_FAILURES = 3


class SuccessorStop(RecoveryRefused):
    """A condition of ONE loop the successor refuses to resolve automatically."""


class StopRequested(SuccessorStop):
    """The driver asked every worker to stop at the next request boundary."""


class ProviderPaused(SuccessorStop):
    """The loop's provider lane failed repeatedly; no further intent is written
    in this lane until the driver re-opens it."""


class ProbeDeclined(ProviderPaused):
    """A half-open lane is probed with a sample that has no counted round at
    this iteration only: a probe never spends a sample's last native round."""


class GlobalIntegrityError(RecoveryRefused):
    """Contract / authorization / lineage / protected-byte failure: affects the
    whole run, never one loop only (the driver stops every loop)."""


# Process-wide stop flag: checked before EVERY new submission intent, so a
# shutdown never leaves a worker sending after the writer lock is released.
STOP_EVENT = threading.Event()
WORKERS = []  # live submission threads (the lock is released only when empty)
TOKEN_ENV = sw.TOKEN_ENV
CONTAINER_LABEL = "pareval.successor_run"


def lane_of(model_config):
    """Provider lane = provider + endpoint CONFIGURATION (the env-var name of
    the base URL, never its value). The three Alibaba Model Studio models
    share one lane; SDK-fixed endpoints are one lane per provider."""
    endpoint = model_config.get("base_url_env") or ("base_url" if model_config.get("base_url")
                                                    else "sdk_fixed")
    return "%s|%s" % (model_config.get("provider"), endpoint)


class LaneMonitor:
    """Consecutive transport failures per provider lane (process-wide).

    closed     LANE_TRIP_FAILURES consecutive failures trip the lane;
    half-open  after a pause the driver re-opens the lane for a probe: ONE
               failure trips it again (an outage costs as few rounds as
               possible); any healthy answer closes it."""

    def __init__(self):
        self._lock = threading.Lock()
        self._failures = {}
        self._threshold = {}
        self._successes = {}

    def failure(self, lane):
        with self._lock:
            self._failures[lane] = self._failures.get(lane, 0) + 1

    def success(self, lane):
        with self._lock:
            self._failures[lane] = 0
            self._threshold[lane] = LANE_TRIP_FAILURES
            self._successes[lane] = self._successes.get(lane, 0) + 1

    def successes(self, lane):
        with self._lock:
            return self._successes.get(lane, 0)

    def reset(self, lane):
        with self._lock:
            self._failures[lane] = 0
            self._threshold[lane] = LANE_TRIP_FAILURES

    def reopen(self, lane):
        with self._lock:
            self._failures[lane] = 0
            self._threshold[lane] = 1

    def tripped(self, lane):
        with self._lock:
            return self._failures.get(lane, 0) >= self._threshold.get(lane, LANE_TRIP_FAILURES)

    def half_open(self, lane):
        with self._lock:
            return self._threshold.get(lane, LANE_TRIP_FAILURES) == 1

    def snapshot(self):
        with self._lock:
            return OrderedDict((lane, {"consecutive_failures": n,
                                       "threshold": self._threshold.get(lane, LANE_TRIP_FAILURES)})
                               for lane, n in sorted(self._failures.items()))


LANES = LaneMonitor()


class LaneAdapter:
    """The real provider adapter, unchanged; only the OUTCOME of each
    generate() call is reported to the lane monitor (a model answer, a model
    refusal or a deterministic terminal error = the provider is healthy; any
    other exception = one transport failure)."""

    def __init__(self, inner, lane):
        self._inner = inner
        self._lane = lane

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def generate(self, *args, **kwargs):
        common = orchestrator.common
        try:
            result = self._inner.generate(*args, **kwargs)
        except common._pre_run_infrastructure_failure():
            raise
        except Exception as error:  # noqa: BLE001 - classified, re-raised unchanged
            if isinstance(error, common.ModelRefusal) or type(error).__name__ in common.TERMINAL_ERROR_TYPES:
                LANES.success(self._lane)
            else:
                LANES.failure(self._lane)
            raise
        LANES.success(self._lane)
        return result


def _parse_jsonl_bytes(data, label):
    rows = []
    text = data.decode("utf-8")
    if text and not text.endswith("\n"):
        raise RecoveryRefused("torn last line in " + label)
    for line in text.split("\n"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def fsync_directory(path):
    """Make a created/renamed directory entry durable (POSIX; a no-op where
    directories cannot be opened)."""
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _check_provider_iteration(iteration):
    if type(iteration) is not int or iteration not in sl.PROVIDER_ITERATIONS:
        raise RecoveryRefused("iteration %r is no successor provider iteration" % (iteration,))
    return iteration


class SuccessorLoopPaths(orchestrator.LoopPaths):
    def __init__(self, config, model, variant, lineage, parent_lineage, replay=False):
        super().__init__(config, sl.SUCCESSOR, model, variant)
        root = lineage.root
        for key, folder in (("raw_dir", "raw"), ("intermediate_dir", "intermediate")):
            if (root / str(config["outputs"][key])).resolve() != (root / "thesis/results" / folder).resolve():
                raise RecoveryRefused("successor outputs must use the bound repository layout")
        if variant not in sl.VARIANTS:
            raise RecoveryRefused("unregistered variant")
        if not replay and model not in lineage.document["model_ids"]:
            raise RecoveryRefused("loop outside the successor scope")
        if model not in parent_lineage.document.get("model_ids", []):
            raise RecoveryRefused("model outside the parent population")
        self.lineage = lineage
        self.parent = parent_lineage
        self.root = root

    # -- identities -------------------------------------------------------

    def iter_run_id(self, iteration):
        if iteration == 0:
            return self.base_run_id
        return sh.iteration_run(sl.SUCCESSOR, self.variant, iteration, sl.MAX_ITERATIONS)

    # -- iteration-0 reads routed to the parent ---------------------------

    def parent_relative(self, name, raw=False):
        return "thesis/results/%s/%s/%s/%s" % ("raw" if raw else "intermediate", PARENT,
                                               self.model_id, name)

    def _repo(self, relative):
        return checked_path(self.root, relative)

    def iter_generations_path(self, iteration):
        if iteration == 0:
            return self._repo(self.parent_relative("generations.jsonl", raw=True))
        return super().iter_generations_path(iteration)

    def assembly_path(self, iteration):
        if iteration == 0:
            return self._repo(self.parent_relative("assembly.jsonl"))
        return super().assembly_path(iteration)

    def stage_path(self, iteration, stage_name):
        if iteration == 0:
            if stage_name not in sl.PARENT_STAGES:
                raise RecoveryRefused("unregistered parent stage")
            return self._repo(self.parent_relative(orchestrator.stage_output_file(self.config, stage_name)))
        return super().stage_path(iteration, stage_name)

    def source_path(self, iteration, sample_id):
        if iteration == 0:
            # verified NOW (raw sha256 against the parent lineage), read by
            # the caller immediately afterwards; a parent drift stops the RUN
            try:
                return self.parent.read_path(self.parent_relative("sources/%s/generated-code.hpp" % sample_id))
            except GlobalIntegrityError:
                raise
            except Exception as error:  # noqa: BLE001 - every parent failure is global
                raise GlobalIntegrityError("GLOBAL_INTEGRITY: parent source of %s: %s: %s"
                                           % (sample_id, type(error).__name__, error))
        return super().source_path(iteration, sample_id)

    def submissions_path(self, iteration):
        return self.repair_dir / ("iter%d" % _check_provider_iteration(iteration)) / "submissions.jsonl"


class SuccessorRepairLoop(orchestrator.RepairLoop):
    """orchestrator.RepairLoop started FRESH from the parent base."""

    def __init__(self, config, config_path, profile_name, profile, model_config, variant,
                 primary_compiler="g++", adapter_factory=None, *, lineage, parent_lineage,
                 authority, writer_token=None, external_runner=None, replay=False):
        super().__init__(config, config_path, profile_name, profile, model_config, variant,
                         primary_compiler, adapter_factory)
        if self.paths.base_run_id != sl.SUCCESSOR or profile_name != sl.PROFILE:
            raise RecoveryRefused("successor loop requires the successor profile")
        self.replay = bool(replay)
        self.paths = SuccessorLoopPaths(config, self.model_id, variant, lineage, parent_lineage,
                                        replay=self.replay)
        self.lineage = lineage
        self.parent_lineage = parent_lineage
        self.authority = authority
        self.writer_token = writer_token
        self.external_runner = external_runner
        self.origin = None if self.replay else lineage.origin(self.model_id, variant)
        self.lane = lane_of(model_config)
        self._ledger_lock = threading.RLock()
        factory = self._adapter_factory
        lane = self.lane
        self._adapter_factory = lambda provider: LaneAdapter(factory(provider), lane)

    def _writable(self):
        if self.replay:
            raise RecoveryRefused("a replay loop is read-only")

    def _origin_repair_condition(self):
        return self.lineage.document["predecessor"]["repair_condition_sha256"]

    # -- per step: authority + protected bytes ----------------------------

    def global_checks(self):
        """Contract/authorization and every protected byte (recovery_001,
        sibling successors; stat-guarded). Any failure is GLOBAL."""
        try:
            self.authority.check()
            self.lineage.verify_quick()
            self.lineage.verify_origin_absence()
        except GlobalIntegrityError:
            raise
        except Exception as error:  # noqa: BLE001 - every failure here is global
            raise GlobalIntegrityError("GLOBAL_INTEGRITY: %s: %s" % (type(error).__name__, error))

    def step(self):
        self._writable()
        self.global_checks()
        outcome = super().step()
        self.global_checks()
        return outcome

    # -- wave state -------------------------------------------------------

    def _require_untouched(self):
        """No wave state: the loop must not own ANY artifact yet (the wave
        state is the first thing a native loop writes)."""
        found = []
        if self.paths.repair_dir.exists():
            # a temp file left by a crash inside the very first (atomic) wave
            # save is not an artifact: the rename never happened
            found.extend(p for p in self.paths.repair_dir.rglob("*") if p.is_file()
                         and not (p.name.startswith("wave_state.json") and atomic_io.TEMP_MARKER in p.name))
        for iteration in sl.PROVIDER_ITERATIONS:
            run = self.paths.iter_run_id(iteration)
            for base in (self.paths.raw_root, self.paths.intermediate_root):
                directory = base / run / self.model_id
                if directory.exists():
                    found.extend(p for p in directory.rglob("*") if p.is_file())
        if found:
            raise RecoveryRefused("loop %s/%s owns artifacts but has no wave state (%s); refusing a "
                                  "second fresh start" % (self.model_id, self.variant,
                                                          ", ".join(str(p) for p in found[:3])))

    def load_wave_state(self):
        if self.paths.wave_state_path.exists():
            state = super().load_wave_state()  # native repair-condition check
            if (state.get("run_id") != sl.SUCCESSOR or state.get("model_id") != self.model_id
                    or state.get("variant") != self.variant
                    or type(state.get("iteration")) is not int
                    or not 0 <= state["iteration"] <= sl.MAX_ITERATIONS
                    or state.get("origin") != "FRESH" or state.get("parent_run_id") != sl.PARENT
                    or state.get("parent_lineage_sha256")
                    != self.lineage.document["predecessor"]["parent_lineage_sha256"]
                    or state.get("lineage_sha256") != self.lineage.sha256
                    or state.get("repair_condition_sha256") != self._origin_repair_condition()
                    or state.get("batch") is not None):
                raise RecoveryRefused("foreign, regressed or not successor-written wave state")
            return state
        self._require_untouched()
        current = self.repair_condition_sha256()
        if current is None or current != self._origin_repair_condition():
            raise RecoveryRefused("the repair condition differs from the origin recovery_001 T0; a fresh "
                                  "loop must start under the original repair method")
        return {"iteration": 0, "phase": "start", "batch": None}

    def save_wave_state(self, iteration, phase, batch=None):
        self._writable()
        if phase not in orchestrator.PHASES:
            raise ValueError("unknown phase '%s'" % phase)
        if type(iteration) is not int or not 0 <= iteration <= sl.MAX_ITERATIONS:
            raise RecoveryRefused("wave iteration %r outside the native budget" % (iteration,))
        if batch is not None:
            raise RecoveryRefused("the successor submits direct requests only")
        state = OrderedDict([
            ("schema_version", orchestrator.WAVE_SCHEMA_VERSION),
            ("run_id", self.paths.base_run_id), ("model_id", self.model_id),
            ("variant", self.variant), ("iteration", iteration), ("phase", phase),
            ("batch", None), ("repair_condition_sha256", self.repair_condition_sha256()),
            ("origin", "FRESH"), ("parent_run_id", sl.PARENT),
            ("parent_lineage_sha256", self.lineage.document["predecessor"]["parent_lineage_sha256"]),
            ("lineage_sha256", self.lineage.sha256),
            ("updated_at_utc", orchestrator.common.utc_now_iso()),
        ])
        atomic_io.atomic_write_json(self.paths.wave_state_path, state)
        fsync_directory(self.paths.wave_state_path.parent)

    # -- sample state: the successor ledger only ---------------------------

    def successor_state_rows(self):
        rows = sw.read_jsonl(self.paths.state_path)
        for row in rows:
            if (row.get("run_id") != sl.SUCCESSOR or row.get("model_id") != self.model_id
                    or row.get("variant") != self.variant or not row.get("sample_id")
                    or type(row.get("iteration")) is not int
                    or not 0 <= row["iteration"] <= sl.MAX_ITERATIONS):
                raise RecoveryRefused("foreign row in the successor state ledger")
        return rows

    def sample_states(self):
        return sh.latest_by_sample(self.successor_state_rows())

    def append_sample_state(self, sample_id, iteration, *args, **kwargs):
        self._writable()
        if type(iteration) is not int or not 0 <= iteration <= sl.MAX_ITERATIONS:
            raise RecoveryRefused("state iteration %r outside the native budget" % (iteration,))
        if sw.tail_is_torn(self.paths.state_path):
            raise SuccessorStop("torn successor state ledger %s" % self.paths.state_path)
        result = super().append_sample_state(sample_id, iteration, *args, **kwargs)
        sw.fsync_file(self.paths.state_path)
        return result

    def mark_unusable(self, sample_id, iteration, reason):
        self._writable()
        return super().mark_unusable(sample_id, iteration, reason)

    def _build_requests(self, target_iteration):
        self._writable()
        _check_provider_iteration(target_iteration)
        if target_iteration > 1:
            # no open (ambiguous) intent of the previous wave may remain
            self.verify_submission_ledger(target_iteration - 1)
        # a torn request row was never submitted (submission starts only after
        # 'requests_built' is persisted), so its partial bytes are archived
        sw.archive_torn_tail(self.paths.requests_path(target_iteration))
        result = super()._build_requests(target_iteration)
        sw.fsync_file(self.paths.requests_path(target_iteration))
        return result

    # -- submission intents: the authoritative round count -----------------

    def submission_ledger(self, iteration):
        rows = sw.read_jsonl(self.paths.submissions_path(iteration))
        for row in rows:
            if (row.get("schema_version") != SUBMISSION_SCHEMA or row.get("run_id") != sl.SUCCESSOR
                    or row.get("model_id") != self.model_id or row.get("variant") != self.variant
                    or row.get("iteration") != iteration
                    or row.get("kind") not in ("intent", "refused_before_send", "resolution")):
                raise RecoveryRefused("foreign submission ledger row")
        return rows

    def submission_intents(self, iteration):
        return [row for row in self.submission_ledger(iteration) if row["kind"] == "intent"]

    def counted_rounds(self, iteration):
        """sample -> intents of THIS iteration not refused before sending."""
        ledger = self.submission_ledger(iteration)
        refused = set(r["intent_id"] for r in ledger if r["kind"] == "refused_before_send")
        rounds = OrderedDict()
        for row in ledger:
            if row["kind"] == "intent" and row["intent_id"] not in refused:
                rounds[row["sample_id"]] = rounds.get(row["sample_id"], 0) + 1
        return rounds

    def load_retry_ledger(self):
        """Native shape {sample: {"<iteration>": rounds}}, DERIVED from the
        durable intent ledgers (request_rounds.json is only a mirror)."""
        merged = OrderedDict()
        for iteration in sl.PROVIDER_ITERATIONS:
            for sample, rounds in self.counted_rounds(iteration).items():
                merged.setdefault(sample, OrderedDict())[str(iteration)] = rounds
        return merged

    def build_response_record(self, base_record, request, generation_parameters):
        record = super().build_response_record(base_record, request, generation_parameters)
        # identity of the outcome row this submission will produce (native
        # order: build_response_record -> count_request_round -> generate)
        self._pending_outcome = (request["sample_id"], record.get("created_at_utc"),
                                 int(request["iteration"]))
        return record

    def provider_guard(self, kind, label=None):
        from thesis.evaluation import run_authorization as ra

        return ra.require_provider_call(kind, label=label)

    def count_request_round(self, sample_ids, iteration):
        from thesis.evaluation import run_authorization as ra

        self._writable()
        _check_provider_iteration(iteration)
        if self.api_mode() != "direct" or len(sample_ids) != 1:
            raise RecoveryRefused("the successor submits single direct requests only")
        if STOP_EVENT.is_set():
            raise StopRequested("stop requested before a new submission")
        if LANES.tripped(self.lane):
            raise ProviderPaused("PROVIDER_PAUSED: lane %s had %d consecutive transport failures; no "
                                 "further request is sent in this lane until the driver re-opens it"
                                 % (self.lane, LANE_TRIP_FAILURES))
        wave = self.load_wave_state()
        if wave["phase"] != "requests_built" or int(wave["iteration"]) != iteration:
            raise RecoveryRefused("no submission outside the requests_built phase of iteration %d"
                                  % iteration)
        sample_id = sample_ids[0]
        if LANES.half_open(self.lane) and self.counted_rounds(iteration).get(sample_id, 0) >= 1:
            raise ProbeDeclined("PROBE_DECLINED: lane %s is half-open and %s@%d already used a round"
                                % (self.lane, sample_id, iteration))
        # the outcome of the previous round is on stable storage before the
        # next intent can be written
        sw.fsync_file(self.paths.iter_generations_path(iteration))
        pending = getattr(self, "_pending_outcome", None)
        if not pending or pending[0] != sample_id or pending[2] != iteration:
            raise RecoveryRefused("submission without a prepared response identity")
        request = {r["sample_id"]: r for r in self.load_requests(iteration)}.get(sample_id)
        if request is None:
            raise RecoveryRefused("submission without a persisted request: %s" % sample_id)
        # the authorization guard runs BEFORE the intent is written, so a
        # refusal never leaves an orphan intent (it runs again at the
        # chokepoint inside call_with_retries)
        self.provider_guard(ra.CALL_KIND_DIRECT, label="successor %s/%s %s@%d" % (
            self.model_id, self.variant, sample_id, iteration))
        with self._ledger_lock:
            rounds = self.counted_rounds(iteration).get(sample_id, 0) + 1
            intent = OrderedDict([
                ("schema_version", SUBMISSION_SCHEMA), ("kind", "intent"),
                ("intent_id", uuid.uuid4().hex), ("run_id", sl.SUCCESSOR),
                ("model_id", self.model_id), ("variant", self.variant),
                ("sample_id", sample_id), ("iteration", iteration), ("round", rounds),
                ("request_sha256", utf8_sha256(request["request"])),
                ("response_created_at_utc", pending[1]),
                ("created_at_utc", orchestrator.common.utc_now_iso()),
            ])
            ledger = self.paths.submissions_path(iteration)
            created = not ledger.exists()
            sw.durable_append_jsonl(ledger, intent)
            if created:
                fsync_directory(ledger.parent)
                fsync_directory(ledger.parent.parent)
            self._open_intent = intent
            atomic_io.atomic_write_json(self.paths.retry_ledger_path, self.load_retry_ledger())

    def _record_refusal(self, error):
        """A pre-run infrastructure refusal raised before the request was sent
        (call_with_retries raises that class only before fn())."""
        intent = getattr(self, "_open_intent", None)
        self._open_intent = None
        if not intent:
            return
        iteration = intent["iteration"]
        identity = (intent["sample_id"], intent["response_created_at_utc"])
        if identity in self.recorded_outcomes(iteration):
            return
        sw.durable_append_jsonl(self.paths.submissions_path(iteration), OrderedDict([
            ("schema_version", SUBMISSION_SCHEMA), ("kind", "refused_before_send"),
            ("intent_id", intent["intent_id"]), ("run_id", sl.SUCCESSOR),
            ("model_id", self.model_id), ("variant", self.variant),
            ("sample_id", intent["sample_id"]), ("iteration", iteration),
            ("error_class", type(error).__name__),
            ("created_at_utc", orchestrator.common.utc_now_iso()),
        ]))

    def _archive_torn_outcomes(self, iteration):
        """A crash inside a native outcome append can leave a partial last line
        in generations.jsonl / failed_responses.jsonl. On the write paths its
        bytes are archived (<name>.torn, fsynced): the intent of that outcome
        then is an open AMBIGUOUS submission - fail-closed below the native
        bound and resolvable with --resolve-ambiguous. Never on read paths."""
        self._writable()
        generations = self.paths.iter_generations_path(_check_provider_iteration(iteration))
        for path in (generations, generations.with_name("failed_responses.jsonl")):
            archived = sw.archive_torn_tail(path)
            if archived:
                self.log("archived a torn outcome tail (%d bytes) of %s; its intent is now an open "
                         "AMBIGUOUS submission" % (archived, path))
        return True

    def recorded_outcomes(self, iteration):
        """Identities (sample_id, created_at_utc) of persisted provider outcomes."""
        identities = set()
        path = self.paths.iter_generations_path(_check_provider_iteration(iteration))
        if path.exists():
            for row in _parse_jsonl_bytes(path.read_bytes(), str(path)):
                identities.add((row.get("sample_id"), row.get("created_at_utc")))
        failed = path.with_name("failed_responses.jsonl")
        if failed.exists():
            for envelope in _parse_jsonl_bytes(failed.read_bytes(), str(failed)):
                for record in envelope.get("records") or []:
                    if isinstance(record, dict):
                        identities.add((record.get("sample_id"), record.get("created_at_utc")))
        return identities

    def verify_submission_ledger(self, iteration):
        """Every counted intent of ITERATION has its recorded outcome, or an
        explicit operator resolution; an intent without either means a
        provider request may have been answered without being persisted.

        Such a sample may continue only when its counted rounds of this
        iteration already reach the native bound (the native exhaust rule then
        ends it without another request); otherwise the loop STOPS."""
        ledger = self.submission_ledger(iteration)
        refused = set(r["intent_id"] for r in ledger if r["kind"] == "refused_before_send")
        resolved = set(r["intent_id"] for r in ledger if r["kind"] == "resolution")
        requests = {r["sample_id"]: r for r in self.load_requests(iteration)}
        outcomes = self.recorded_outcomes(iteration)
        expected = set()
        ambiguous = []
        for row in ledger:
            if row["kind"] != "intent":
                continue
            request = requests.get(row["sample_id"])
            if request is None or utf8_sha256(request["request"]) != row["request_sha256"]:
                raise RecoveryRefused("submission intent does not match the persisted request")
            identity = (row["sample_id"], row["response_created_at_utc"])
            if row["intent_id"] in refused:
                if identity in outcomes:
                    raise RecoveryRefused("a refused-before-send intent has a provider outcome")
                continue
            expected.add(identity)
            if identity not in outcomes and row["intent_id"] not in resolved:
                ambiguous.append(row)
        unexplained = sorted(i for i in outcomes if i not in expected)
        if unexplained:
            raise RecoveryRefused("provider outcomes without a submission intent: %s"
                                  % ", ".join(str(i[0]) for i in unexplained[:5]))
        limit = self.settings["request_retry_rounds"]
        rounds = self.counted_rounds(iteration)
        blocking = [row for row in ambiguous if rounds.get(row["sample_id"], 0) < limit]
        for row in ambiguous:
            self.log("AMBIGUOUS submission %s@%d (intent %s): no persisted outcome%s"
                     % (row["sample_id"], iteration, row["intent_id"],
                        "" if row in blocking else " - native bound reached, no further request"))
        if blocking:
            raise SuccessorStop(
                "AMBIGUOUS_SUBMISSION: %d request(s) of %s/%s at iteration %d were submitted without a "
                "persisted outcome (%s). The provider may have answered; nothing is resubmitted "
                "automatically. Resolve explicitly with thesis.recovery_successor_004.run "
                "--resolve-ambiguous MODEL/VARIANT/SAMPLE@ITERATION."
                % (len(blocking), self.model_id, self.variant, iteration,
                   ", ".join(r["sample_id"] for r in blocking[:5])))
        # ambiguous intents at the native bound: no further request is allowed
        # (the native exhaust rule ends the sample), but their outcome is
        # UNKNOWN - the provider may have answered and billed them. Returned
        # (truthy list or an empty list) so verifiers report them explicitly.
        return [OrderedDict([("sample_id", row["sample_id"]), ("intent_id", row["intent_id"]),
                             ("iteration", iteration),
                             ("outcome", "UNKNOWN_DRIVER_INTERRUPTED_IN_LAST_ALLOWED_ROUND")])
                for row in ambiguous]

    def resolve_ambiguous(self, sample_id, note, iteration):
        """Operator decision (under the writer lock): the lost response of the
        open intent counts as a consumed round. Nothing is deleted."""
        self._writable()
        _check_provider_iteration(iteration)
        wave = self.load_wave_state()
        if wave["phase"] != "requests_built" or int(wave["iteration"]) != iteration:
            raise RecoveryRefused("the loop is not in the requests_built phase of iteration %d" % iteration)
        self._archive_torn_outcomes(iteration)
        ledger = self.submission_ledger(iteration)
        refused = set(r["intent_id"] for r in ledger if r["kind"] == "refused_before_send")
        resolved = set(r["intent_id"] for r in ledger if r["kind"] == "resolution")
        outcomes = self.recorded_outcomes(iteration)
        open_intents = [r for r in ledger if r["kind"] == "intent" and r["sample_id"] == sample_id
                        and r["intent_id"] not in refused and r["intent_id"] not in resolved
                        and (r["sample_id"], r["response_created_at_utc"]) not in outcomes]
        if len(open_intents) != 1:
            raise RecoveryRefused("no single open ambiguous intent for %s@%d" % (sample_id, iteration))
        sw.durable_append_jsonl(self.paths.submissions_path(iteration), OrderedDict([
            ("schema_version", SUBMISSION_SCHEMA), ("kind", "resolution"),
            ("intent_id", open_intents[0]["intent_id"]), ("run_id", sl.SUCCESSOR),
            ("model_id", self.model_id), ("variant", self.variant), ("sample_id", sample_id),
            ("iteration", iteration),
            ("resolution", "lost_response_counted_as_round"), ("note", note),
            ("possible_duplicate_billing", True),
            ("created_at_utc", orchestrator.common.utc_now_iso()),
        ]))
        return open_intents[0]["intent_id"]

    def _require_successor_raw(self, path):
        allowed = [(self.paths.raw_root / self.paths.iter_run_id(i) / self.model_id).resolve()
                   for i in sl.PROVIDER_ITERATIONS]
        if Path(path).name != "generations.jsonl" or Path(path).parent.resolve() not in allowed:
            raise RecoveryRefused("refusing to load/rewrite a non-successor response file")

    def _load_terminal_responses(self, path):
        """Native keep/drop semantics on the SUCCESSOR file only, crash-safe:
        a torn or undecodable line refuses (bytes preserved), dropped records
        are archived durably, the rewrite is atomic."""
        self._require_successor_raw(path)
        path = Path(path)
        if not path.exists():
            return {}
        rows = _parse_jsonl_bytes(path.read_bytes(), str(path))
        terminal = OrderedDict()
        kept = []
        dropped = []
        for record in rows:
            status = record.get("status") or {}
            success = status.get("success") is True
            refusal = status.get("error_type") in orchestrator.common.TERMINAL_ERROR_TYPES
            if record.get("sample_id") and (success or refusal):
                if record["sample_id"] in terminal:
                    raise RecoveryRefused("duplicate terminal response for %s" % record["sample_id"])
                terminal[record["sample_id"]] = record
                kept.append(record)
            else:
                dropped.append(record)
        if dropped:
            sw.durable_append_jsonl(path.with_name("failed_responses.jsonl"), OrderedDict([
                ("dropped_at_utc", orchestrator.common.utc_now_iso()), ("records", dropped)]))
            atomic_io.atomic_write_bytes(path, "".join(
                json.dumps(r, ensure_ascii=False) + "\n" for r in kept).encode("utf-8"))
            self.log("dropped %d failed response record(s) for retry (archived)" % len(dropped))
        return terminal

    # -- verified parent readers (iteration 0) -------------------------------

    def _parent_bytes(self, relative):
        """Verified parent bytes. A drifted, missing or unregistered parent
        artifact is a lineage failure of the WHOLE run (GlobalIntegrityError)."""
        ref = self.parent_lineage.refs.get(relative)
        if ref is None or ref.stage == "historical_only":
            raise GlobalIntegrityError("GLOBAL_INTEGRITY: unregistered parent artifact: " + relative)
        try:
            data = checked_path(self.paths.root, relative).read_bytes()
        except Exception as error:  # noqa: BLE001 - every parent failure is global
            raise GlobalIntegrityError("GLOBAL_INTEGRITY: parent artifact unreadable: %s (%s: %s)"
                                       % (relative, type(error).__name__, error))
        if len(data) != ref.size or hashlib.sha256(data).hexdigest() != ref.raw_sha256:
            raise GlobalIntegrityError("GLOBAL_INTEGRITY: parent artifact drift: " + relative)
        return data

    def _keyed(self, rows):
        keyed = OrderedDict()
        for row in rows:
            if row["sample_id"] in keyed:
                raise RecoveryRefused("duplicate sample in a verified artifact")
            keyed[row["sample_id"]] = row
        return keyed

    def load_assembly_entries(self, iteration):
        if iteration == 0:
            relative = self.paths.parent_relative("assembly.jsonl")
            return self._keyed(_parse_jsonl_bytes(self._parent_bytes(relative), relative))
        return super().load_assembly_entries(iteration)

    def load_stage_records(self, iteration, stage_name):
        if iteration == 0:
            name = orchestrator.stage_output_file(self.config, stage_name)
            relative = self.paths.parent_relative(name)
            if relative not in self.parent_lineage.refs:
                # native: a missing stage file reads as {}; a stage the
                # iteration-0 DECISION of this variant depends on must exist
                needed = (stage_name == "static_analysis"
                          or (stage_name == "correctness_tests" and self.needs_tests())
                          or (stage_name == "dynamic_analysis" and self.needs_dynamic()))
                if needed:
                    raise RecoveryRefused("parent evidence lacks %s for %s" % (stage_name, self.model_id))
                return {}
            return self._keyed(_parse_jsonl_bytes(self._parent_bytes(relative), relative))
        return super().load_stage_records(iteration, stage_name)

    def load_base_prompts(self):
        prompts = {}
        for sample, record in self.load_base_generation_records().items():
            prompt = record.get("prompt") or {}
            if prompt.get("prompt_text"):
                prompts[sample] = prompt["prompt_text"]
        return prompts

    def load_base_generation_records(self):
        relative = self.paths.parent_relative("generations.jsonl", raw=True)
        return self._keyed(_parse_jsonl_bytes(self._parent_bytes(relative), relative))

    # -- guards: parent evidence is never re-measured or re-written ----------

    def _run_analysis_stages(self, iteration, stages):
        self._writable()
        if iteration == 0:
            raise RecoveryRefused("parent iteration-0 evidence is never re-measured")
        _check_provider_iteration(iteration)
        return super()._run_analysis_stages(iteration, stages)

    def _submit(self, target_iteration):
        self._writable()
        _check_provider_iteration(target_iteration)
        if self.api_mode() != "direct":
            raise RecoveryRefused("the successor intent ledger covers direct submission only")
        self._archive_torn_outcomes(target_iteration)
        self.verify_submission_ledger(target_iteration)
        try:
            return super()._submit(target_iteration)
        except orchestrator.common._pre_run_infrastructure_failure() as error:
            # raised by the chokepoint BEFORE fn(): the open intent was not sent
            self._record_refusal(error)
            raise

    def _finish_responses(self, target_iteration):
        self._writable()
        _check_provider_iteration(target_iteration)
        # every counted intent's outcome must be durable (or explicitly
        # resolved) BEFORE the wave may leave the submission phase
        self._archive_torn_outcomes(target_iteration)
        sw.fsync_file(self.paths.iter_generations_path(target_iteration))
        self.verify_submission_ledger(target_iteration)
        return super()._finish_responses(target_iteration)

    def _submit_batch(self, target_iteration):
        raise RecoveryRefused("the successor submits direct requests only")

    def _poll_batch(self, target_iteration):
        raise RecoveryRefused("the successor submits direct requests only")

    def _assemble(self, target_iteration):
        self._writable()
        _check_provider_iteration(target_iteration)
        return super()._assemble(target_iteration)

    # -- external tools (native at iterations 1 and 2) -----------------------

    def external_target(self, iteration):
        if iteration == 0:
            raise RecoveryRefused("parent external evidence is never backfilled")
        return self.paths.iter_run_id(_check_provider_iteration(iteration))

    def container_name(self, tool, iteration):
        return "pareval-%s-%s-%s-it%d-%s" % (sl.SUCCESSOR, self.model_id, self.variant,
                                             iteration, tool)

    def external_command(self, tool, iteration):
        """Docker command for the successor tool runner. Same image and
        interpreter as the configured template (the measurement container is
        unchanged); a unique --name refuses a concurrent duplicate; the label
        lets the driver refuse to start while an orphan is alive; the writer
        token travels in the environment, never on the command line."""
        from thesis.evaluation.check_static_repair_readiness import parse_docker_template

        target = self.external_target(iteration)
        template = self.settings["external_tool_commands"].get(tool)
        if not template:
            raise ValueError("stages.repair.external_tool_commands has no template for '%s'" % tool)
        image, interpreter = parse_docker_template(template)
        marker = " %s %s " % (image, interpreter)
        if not image or marker not in template or not template.startswith("docker run "):
            raise RecoveryRefused("external template is not a docker image/interpreter command")
        head = template[:template.index(marker)].format(
            host_repo=orchestrator.host_repo_path(self.settings), repo=str(orchestrator.REPO_ROOT))
        flags = " --name %s --label %s=%s -e %s" % (self.container_name(tool, iteration),
                                                    CONTAINER_LABEL, sl.SUCCESSOR, TOKEN_ENV)
        return ("%s%s %s %s -B -m thesis.recovery_successor_004.external --config %s --profile %s "
                "--run-id %s --target-run-id %s --model-id %s --variant %s --iteration %d "
                "--tool %s"
                % (head, flags, image, interpreter, sl.CONFIG_REL, sl.PROFILE, sl.SUCCESSOR,
                   target, self.model_id, self.variant, iteration, tool))

    def run_external_docker(self, pending, iteration):
        """Run the pending tools in their pinned containers. A non-zero exit
        leaves the wave waiting (this loop only), EXCEPT a contract /
        provenance / runtime conflict of the tool container (external
        GLOBAL_CONFLICT_EXITS): that stops the whole run, nothing further is
        started."""
        from thesis.recovery_successor_004 import external as sx

        self._writable()
        self.external_target(iteration)
        if self.external_runner is not None:
            return self.external_runner(self, pending, iteration)
        if not self.writer_token:
            raise RecoveryRefused("external tools need the successor writer token")
        failed = []
        for tool, count in pending:
            if not self.settings["external_tool_commands"].get(tool):
                raise ValueError("no external command template for '%s'" % tool)
            command = self.external_command(tool, iteration)
            self.log("external %s (%d sample(s)): %s" % (tool, count, command))
            environment = dict(os.environ)
            environment[TOKEN_ENV] = self.writer_token
            try:
                result = subprocess.run(command, shell=True, env=environment)
            except BaseException:
                # never leave a writing container behind the driver
                subprocess.run(["docker", "kill", self.container_name(tool, iteration)],
                               capture_output=True)
                raise
            if result.returncode in sx.GLOBAL_CONFLICT_EXITS:
                raise GlobalIntegrityError(
                    "external %s of %s/%s (iteration %d) exited %d: %s - global stop"
                    % (tool, self.model_id, self.variant, iteration, result.returncode,
                       sx.GLOBAL_CONFLICT_EXITS[result.returncode]))
            if result.returncode != 0:
                self.log("external %s FAILED (exit %d) - wave stays waiting" % (tool, result.returncode))
                failed.append(tool)
        return failed

    def write_pending_external(self, pending, iteration):
        lines = ["# Successor loop %s/%s waiting for external tools (iteration %d, target %s)"
                 % (self.model_id, self.variant, iteration, self.external_target(iteration)),
                 "# Re-run python3 -B -m thesis.recovery_successor_004.run; it starts the containers itself."]
        for tool, count in pending:
            lines.append("# %s: %d sample(s) missing" % (tool, count))
        self.paths.pending_external_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_io.atomic_write_text(self.paths.pending_external_path, "\n".join(lines) + "\n")
        self.log("waiting for external tools: %s" % ", ".join("%s(%d)" % p for p in pending))

    # -- read-only methodology replay (recovery_001 models) ------------------

    def iteration0_decisions(self):
        """Pure: the iteration-0 decision of every assembled parent sample
        through the PRODUCTIVE native path (compute_decisions(0) with the
        verified parent routing) on a loop that has not decided yet."""
        if self.successor_state_rows():
            raise RecoveryRefused("iteration-0 decisions are derived for an undecided loop only")
        decisions = OrderedDict()
        for sample, _prior, decision in self.compute_decisions(0):
            decisions[sample] = OrderedDict([
                ("status", decision.status), ("stop_reason", decision.stop_reason),
                ("counts", decision.counts), ("test_verdict", decision.test_verdict),
                ("low_confidence_keys", decision.low_confidence_keys),
                ("analysis_gaps", decision.analysis_gaps)])
        return decisions

    def replay_later_decisions(self, view):
        """Read-only: re-derive recovery_001's NATIVE decisions at iterations
        1 and 2 (evaluate_stop on its iteration stage records, previous row as
        prior - the grace_once low-confidence rule included) and compare."""
        rows = view.event_ledger(self.model_id, self.variant)
        by_iteration = OrderedDict()
        for row in rows:
            by_iteration.setdefault(row["iteration"], OrderedDict())[row["sample_id"]] = row
        compared, mismatches = 0, []
        self._replayed_with_prior_low_confidence = 0
        for iteration in sl.PROVIDER_ITERATIONS:
            decided = OrderedDict((s, r) for s, r in (by_iteration.get(iteration) or {}).items()
                                  if r.get("status") not in (orchestrator.STATUS_UNUSABLE,
                                                             orchestrator.STATUS_API_EXHAUSTED))
            if not decided:
                continue
            run = sh.predecessor_iteration_run(self.variant, iteration)
            base = sh.iteration_dir(run, self.model_id)

            def records(name):
                relative = "%s/%s" % (base, name)
                return view.unique_rows(relative, run, self.model_id) if view.has(relative) else {}

            static = records(orchestrator.stage_output_file(self.config, "static_analysis"))
            correctness = records(orchestrator.stage_output_file(self.config, "correctness_tests")) \
                if self.needs_tests() else {}
            dynamic = records(orchestrator.stage_output_file(self.config, "dynamic_analysis")) \
                if self.needs_dynamic() else {}
            prior_rows = by_iteration.get(iteration - 1) or {}
            for sample, row in decided.items():
                prior = prior_rows.get(sample)
                if prior and prior.get("low_confidence_keys"):
                    self._replayed_with_prior_low_confidence += 1
                decision = orchestrator.evaluate_stop(
                    config=self.config, variant=self.variant, iteration=iteration,
                    max_iterations=self.settings["max_iterations"],
                    static_record=static.get(sample), dynamic_record=dynamic.get(sample),
                    correctness_record=correctness.get(sample),
                    previous_low_confidence_keys=(prior.get("low_confidence_keys") if prior else None))
                expected = OrderedDict([("status", decision.status), ("stop_reason", decision.stop_reason),
                                        ("counts", decision.counts), ("test_verdict", decision.test_verdict),
                                        ("low_confidence_keys", decision.low_confidence_keys),
                                        ("analysis_gaps", decision.analysis_gaps)])
                compared += 1
                if json.loads(json.dumps(expected)) != json.loads(json.dumps(OrderedDict(
                        (f, row.get(f)) for f in STATE_FIELDS))):
                    mismatches.append("%s@%d" % (sample, iteration))
        return compared, mismatches

    def replay_origin(self, view):
        """Read-only methodology gate on a recovery_001 loop (a model outside
        004): the iteration-0 decisions and the iteration-1 requests derived
        through THIS routing equal recovery_001's natively written bytes."""
        if not self.replay:
            raise RecoveryRefused("the methodology replay runs on replay loops only")
        rows = view.event_ledger(self.model_id, self.variant)
        recorded = OrderedDict()
        for row in rows:
            if row["iteration"] == 0 and row.get("status") != orchestrator.STATUS_UNUSABLE:
                recorded[row["sample_id"]] = row
        derived = self.iteration0_decisions()
        decision_mismatches = [s for s in sorted(set(derived) | set(recorded))
                               if s not in derived or s not in recorded or json.loads(json.dumps(
                                   derived[s])) != json.loads(json.dumps(OrderedDict(
                                       (f, recorded[s].get(f)) for f in STATE_FIELDS)))]
        unassembled = sorted(s for s, e in self.load_assembly_entries(0).items() if not e.get("assembled"))
        unusable0 = sorted(r["sample_id"] for r in rows if r["iteration"] == 0
                           and r.get("status") == orchestrator.STATUS_UNUSABLE)
        active = sorted(s for s, d in derived.items() if d["status"] == orchestrator.STATUS_ACTIVE)
        relative = "%s/iter1/requests.jsonl" % sh.repair_dir(self.model_id, self.variant)
        recorded_requests = view.jsonl(relative) if view.has(relative) else []
        request_mismatches = []
        if sorted(r["sample_id"] for r in recorded_requests) != active:
            request_mismatches.append("request set != derived active set")
        rebuilt = {r["sample_id"]: r for r in self.build_request_records(
            1, [r["sample_id"] for r in recorded_requests])}
        for request in recorded_requests:
            mine = rebuilt[request["sample_id"]]
            if any(mine.get(field) != request.get(field) for field in REQUEST_FIELDS):
                request_mismatches.append(request["sample_id"])
        later, later_mismatches = self.replay_later_decisions(view)
        digest = canonical_sha256(OrderedDict([
            ("decisions", derived), ("requests", OrderedDict(
                (r["sample_id"], OrderedDict((f, r.get(f)) for f in REQUEST_FIELDS)) for r in recorded_requests))]))
        return OrderedDict([
            ("decisions", len(derived)), ("decision_mismatches", decision_mismatches),
            ("unassembled", len(unassembled)), ("unusable_match", unassembled == unusable0),
            ("active", len(active)), ("requests", len(recorded_requests)),
            ("request_mismatches", request_mismatches),
            ("later_decisions", later), ("later_decision_mismatches", later_mismatches),
            ("later_decisions_with_prior_low_confidence", self._replayed_with_prior_low_confidence),
            ("digest", digest)])


class SuccessorAuthority:
    """Per-step authority: the successor contract rebuilds to the frozen one
    and the persisted authorization validates (rehydration checks)."""

    def __init__(self, config, config_path, root=None):
        from thesis.recovery_successor_004 import contract as sc

        self.config = config
        self.config_path = str(config_path)
        self.root = Path(root).resolve() if root is not None else sc.ROOT
        self.contract_path = sc.frozen_path(self.root)
        self._lock = threading.RLock()
        self.contract_sha256 = None
        self.authorization_sha256 = None

    def check(self):
        from thesis.evaluation import pilot_run_contract as prc
        from thesis.evaluation import run_authorization as ra
        from thesis.recovery_successor_004 import contract as sc

        with self._lock:
            frozen = prc.load_frozen(self.contract_path)
            rebuilt = sc.build(self.config_path, sl.SUCCESSOR, root=self.root)
            if rebuilt["contract_sha256"] != frozen["contract_sha256"]:
                raise RecoveryRefused("successor contract drift: frozen %s... vs rebuilt %s..."
                                      % (frozen["contract_sha256"][:12], rebuilt["contract_sha256"][:12]))
            validated = ra.load_and_validate_run_authorization(
                self.config, sl.SUCCESSOR, config_path=self.config_path, profile=sl.PROFILE,
                contract_path=self.contract_path)
            self.contract_sha256 = frozen["contract_sha256"]
            self.authorization_sha256 = validated["authorization"]["authorization_sha256"]
            return validated
