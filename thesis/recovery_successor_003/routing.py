"""Successor repair loop: continue recovery_001 loops by verified reference.

Read/write separation (the core invariant):

    iteration 0  parent full_ext_001 artifacts, read through the recovery_001
                 parent lineage (raw sha256 per read)            READ ONLY
    iteration 1  predecessor recovery_001 iteration artifacts, read through
                 the successor lineage snapshot (raw sha256 per read), merged
                 with successor-owned supplements (LLOV)        READ ONLY
    iteration 2  successor-native full_ext_recovery_002__<variant>__iter2
                                                                 READ/WRITE
    ledgers      predecessor state/request_rounds are read as the head of
                 the event ledger; every new row/increment is written to the
                 successor repair directory only

The native state machine (orchestrator.RepairLoop) is reused unchanged; this
subclass only routes reads, refuses every write that would touch iterations
0/1, records submission intents durably before each provider call, and
re-verifies authority and predecessor bytes on every step.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import atomic_io
from thesis.recovery_successor_003 import handoff as sh
from thesis.recovery_successor_003 import lineage as sl
from thesis.evaluation import successor_supplement as ss
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.condition_hashing import canonical_sha256, utf8_sha256
from thesis.evaluation.recovery_lineage import PARENT, RecoveryRefused, checked_path
from thesis.repair import orchestrator

SUBMISSION_SCHEMA = "successor_submission_intent.v1"
TARGET_ITERATION = 2


class SuccessorStop(RecoveryRefused):
    """A condition the successor refuses to resolve automatically (STOP)."""


class StopRequested(SuccessorStop):
    """The driver asked every worker to stop at the next request boundary."""


# Process-wide stop flag: checked before EVERY new submission intent, so a
# shutdown never leaves a worker sending after the writer lock is released.
STOP_EVENT = threading.Event()
WORKERS = []  # live submission threads (the lock is released only when empty)
TOKEN_ENV = sw.TOKEN_ENV
CONTAINER_LABEL = "pareval.successor_run"


def _parse_jsonl_bytes(data, label):
    rows = []
    text = data.decode("utf-8")
    if text and not text.endswith("\n"):
        raise RecoveryRefused("torn last line in " + label)
    for line in text.split("\n"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


class SuccessorLoopPaths(orchestrator.LoopPaths):
    def __init__(self, config, model, variant, lineage, parent_lineage, replay=False):
        super().__init__(config, sl.SUCCESSOR, model, variant)
        root = lineage.root
        for key, folder in (("raw_dir", "raw"), ("intermediate_dir", "intermediate")):
            if (root / str(config["outputs"][key])).resolve() != (root / "thesis/results" / folder).resolve():
                raise RecoveryRefused("successor outputs must use the bound repository layout")
        if model not in lineage.document["model_ids"] or (
                variant not in (sl.VARIANTS if replay else sl.CONTINUE_VARIANTS)):
            raise RecoveryRefused("loop outside the successor continuation scope")
        if model not in parent_lineage.document.get("model_ids", []):
            raise RecoveryRefused("model outside the parent population")
        self.lineage = lineage
        self.parent = parent_lineage
        self.root = root

    # -- identities -------------------------------------------------------

    def iter_run_id(self, iteration):
        if iteration == 0:
            return self.base_run_id
        if iteration == 1:
            # READ identity of the predecessor candidates; every writer that
            # could use it is refused by SuccessorRepairLoop
            return sh.predecessor_iteration_run(self.variant, 1)
        return sh.iteration_run(sl.SUCCESSOR, self.variant, iteration, sl.MAX_ITERATIONS)

    # -- read-routed paths ------------------------------------------------

    def parent_relative(self, name, raw=False):
        return "thesis/results/%s/%s/%s/%s" % ("raw" if raw else "intermediate", PARENT,
                                               self.model_id, name)

    def predecessor_relative(self, name, raw=False):
        run = sh.predecessor_iteration_run(self.variant, 1)
        return "%s/%s" % (sh.iteration_dir(run, self.model_id, "raw" if raw else "intermediate"), name)

    def _repo(self, relative):
        return checked_path(self.root, relative)

    def iter_generations_path(self, iteration):
        if iteration == 0:
            return self._repo(self.parent_relative("generations.jsonl", raw=True))
        if iteration == 1:
            return self._repo(self.predecessor_relative("generations.jsonl", raw=True))
        return super().iter_generations_path(iteration)

    def assembly_path(self, iteration):
        if iteration == 0:
            return self._repo(self.parent_relative("assembly.jsonl"))
        if iteration == 1:
            return self._repo(self.predecessor_relative("assembly.jsonl"))
        return super().assembly_path(iteration)

    def stage_path(self, iteration, stage_name):
        name = orchestrator.stage_output_file(self.config, stage_name)
        if iteration == 0:
            return self._repo(self.parent_relative(name))
        if iteration == 1:
            return self._repo(self.predecessor_relative(name))
        return super().stage_path(iteration, stage_name)

    def source_path(self, iteration, sample_id):
        name = "sources/%s/generated-code.hpp" % sample_id
        if iteration == 0:
            # verified NOW (raw sha256 against the parent lineage), read by
            # the caller immediately afterwards
            return self.parent.read_path(self.parent_relative(name))
        if iteration == 1:
            relative = self.predecessor_relative(name)
            self.lineage.view.read_bytes(relative)
            return self._repo(relative)
        return super().source_path(iteration, sample_id)

    # -- predecessor ledgers (read only) ----------------------------------

    def predecessor_repair(self, name):
        return "%s/%s" % (sh.repair_dir(self.model_id, self.variant), name)

    @property
    def submissions_path(self):
        return self.repair_dir / ("iter%d" % TARGET_ITERATION) / "submissions.jsonl"


class SuccessorRepairLoop(orchestrator.RepairLoop):
    """orchestrator.RepairLoop continued from a predecessor handoff."""

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
        self.handoff = lineage.handoff(self.model_id, variant)
        if self.handoff.get("mode") != "CONTINUE" and not self.replay:
            raise RecoveryRefused("only CONTINUE loops are driven by the successor")
        self._ledger_lock = threading.RLock()

    def _writable(self):
        if self.replay:
            raise RecoveryRefused("a replay loop is read-only")

    def replay_requests(self, iteration):
        """Read-only equivalence gate: rebuild the PREDECESSOR request ledger of
        this loop through the successor read routing (parent iteration 0 via
        the parent lineage, predecessor iteration 1 via the snapshot) and
        compare every request byte-for-byte."""
        relative = "%s/iter%d/requests.jsonl" % (sh.repair_dir(self.model_id, self.variant), iteration)
        predecessor = self.lineage.view.jsonl(relative)
        rebuilt = {r["sample_id"]: r for r in self.build_request_records(
            iteration, [r["sample_id"] for r in predecessor])}
        mismatches = [r["sample_id"] for r in predecessor
                      if rebuilt[r["sample_id"]]["request"] != r["request"]
                      or rebuilt[r["sample_id"]]["request_chars"] != r["request_chars"]
                      or rebuilt[r["sample_id"]]["built_from_iteration"] != r["built_from_iteration"]]
        return OrderedDict([("ledger", relative), ("requests", len(predecessor)),
                            ("mismatches", mismatches)])

    # -- per step: authority + predecessor immutability -------------------

    def step(self):
        # predecessor immutability around every step: a full re-hash whenever
        # any predecessor file's size/mtime or the membership changed (every
        # individual predecessor READ additionally re-hashes the bytes read)
        self._writable()
        self.authority.check()
        self.lineage.verify_quick()
        outcome = super().step()
        self.lineage.verify_quick()
        return outcome

    # -- wave state -------------------------------------------------------

    def load_wave_state(self):
        if self.paths.wave_state_path.exists():
            state = super().load_wave_state()
            if (state.get("run_id") != sl.SUCCESSOR or state.get("model_id") != self.model_id
                    or state.get("variant") != self.variant
                    or int(state.get("iteration", -1)) < 1
                    or state.get("predecessor_run_id") != sl.PREDECESSOR
                    or state.get("lineage_sha256") != self.lineage.sha256):
                raise RecoveryRefused("foreign, regressed or not successor-written wave state")
            return state
        wave = self.lineage.view.read_json(self.paths.predecessor_repair("wave_state.json"))
        current = self.repair_condition_sha256()
        if (wave.get("run_id") != sl.PREDECESSOR or wave.get("model_id") != self.model_id
                or wave.get("variant") != self.variant
                or wave.get("iteration") != self.handoff["wave_iteration"]
                or wave.get("phase") != self.handoff["wave_phase"]
                or wave.get("repair_condition_sha256") != self.handoff["repair_condition_sha256"]
                or current is None or current != wave.get("repair_condition_sha256")):
            raise RecoveryRefused("predecessor wave state cannot be continued under this repair "
                                  "condition")
        return {"iteration": wave["iteration"], "phase": wave["phase"], "batch": None,
                "seeded_from_predecessor": True}

    def save_wave_state(self, iteration, phase, batch=None):
        self._writable()
        if phase not in orchestrator.PHASES:
            raise ValueError("unknown phase '%s'" % phase)
        if iteration < 1:
            raise RecoveryRefused("the successor never writes an iteration-0 wave state")
        state = OrderedDict([
            ("schema_version", orchestrator.WAVE_SCHEMA_VERSION),
            ("run_id", self.paths.base_run_id), ("model_id", self.model_id),
            ("variant", self.variant), ("iteration", iteration), ("phase", phase),
            ("batch", batch), ("repair_condition_sha256", self.repair_condition_sha256()),
            ("predecessor_run_id", sl.PREDECESSOR),
            ("lineage_sha256", self.lineage.sha256),
            ("updated_at_utc", orchestrator.common.utc_now_iso()),
        ])
        atomic_io.atomic_write_json(self.paths.wave_state_path, state)

    # -- sample state: predecessor head + successor tail ------------------

    def predecessor_states(self):
        rows = self.lineage.view.event_ledger(self.model_id, self.variant)
        return sh.latest_by_sample(rows)

    def successor_state_rows(self):
        rows = sw.read_jsonl(self.paths.state_path)
        for row in rows:
            if (row.get("run_id") != sl.SUCCESSOR or row.get("model_id") != self.model_id
                    or row.get("variant") != self.variant
                    or type(row.get("iteration")) is not int or row["iteration"] < 1):
                raise RecoveryRefused("foreign row in the successor state ledger")
        return rows

    def sample_states(self):
        states = OrderedDict(self.predecessor_states())
        for row in self.successor_state_rows():
            states[row["sample_id"]] = row
        return states

    def append_sample_state(self, sample_id, iteration, *args, **kwargs):
        self._writable()
        if iteration < 1:
            raise RecoveryRefused("the successor never decides iteration 0")
        if sw.tail_is_torn(self.paths.state_path):
            raise SuccessorStop("torn successor state ledger %s" % self.paths.state_path)
        result = super().append_sample_state(sample_id, iteration, *args, **kwargs)
        sw.fsync_file(self.paths.state_path)
        return result

    def _build_requests(self, target_iteration):
        if target_iteration != TARGET_ITERATION:
            raise RecoveryRefused("the successor builds iteration-2 requests only")
        # a torn request row was never submitted (submission starts only after
        # 'requests_built' is persisted), so its partial bytes are archived
        sw.archive_torn_tail(self.paths.requests_path(target_iteration))
        result = super()._build_requests(target_iteration)
        sw.fsync_file(self.paths.requests_path(target_iteration))
        return result

    # -- submission intents: the authoritative round count -----------------

    def submission_ledger(self):
        rows = sw.read_jsonl(self.paths.submissions_path)
        for row in rows:
            if (row.get("schema_version") != SUBMISSION_SCHEMA or row.get("run_id") != sl.SUCCESSOR
                    or row.get("model_id") != self.model_id or row.get("variant") != self.variant
                    or row.get("kind") not in ("intent", "refused_before_send", "resolution")):
                raise RecoveryRefused("foreign submission ledger row")
        return rows

    def submission_intents(self):
        return [row for row in self.submission_ledger() if row["kind"] == "intent"]

    def counted_rounds(self):
        """sample -> intents that were not refused before sending (rounds)."""
        ledger = self.submission_ledger()
        refused = set(r["intent_id"] for r in ledger if r["kind"] == "refused_before_send")
        rounds = {}
        for row in ledger:
            if row["kind"] == "intent" and row["intent_id"] not in refused:
                rounds[row["sample_id"]] = rounds.get(row["sample_id"], 0) + 1
        return rounds

    def load_retry_ledger(self):
        merged = {}
        relative = self.paths.predecessor_repair("request_rounds.json")
        if self.lineage.view.has(relative):
            merged = json.loads(self.lineage.view.read_text(relative))
        for sample, rounds in self.counted_rounds().items():
            target = merged.setdefault(sample, {})
            if str(TARGET_ITERATION) in target:
                raise RecoveryRefused("successor rounds overlap predecessor rounds")
            target[str(TARGET_ITERATION)] = rounds
        return merged

    def build_response_record(self, base_record, request, generation_parameters):
        record = super().build_response_record(base_record, request, generation_parameters)
        # identity of the outcome row this submission will produce (native
        # order: build_response_record -> count_request_round -> generate)
        self._pending_outcome = (request["sample_id"], record.get("created_at_utc"))
        return record

    def provider_guard(self, kind, label=None):
        from thesis.evaluation import run_authorization as ra

        return ra.require_provider_call(kind, label=label)

    def count_request_round(self, sample_ids, iteration):
        from thesis.evaluation import run_authorization as ra

        self._writable()
        if iteration != TARGET_ITERATION or self.api_mode() != "direct" or len(sample_ids) != 1:
            raise RecoveryRefused("the successor submits single direct iteration-2 requests only")
        if STOP_EVENT.is_set():
            raise StopRequested("stop requested before a new submission")
        sample_id = sample_ids[0]
        # the outcome of the previous round is on stable storage before the
        # next intent can be written
        sw.fsync_file(self.paths.iter_generations_path(iteration))
        pending = getattr(self, "_pending_outcome", None)
        if not pending or pending[0] != sample_id:
            raise RecoveryRefused("submission without a prepared response identity")
        request = {r["sample_id"]: r for r in self.load_requests(iteration)}.get(sample_id)
        if request is None:
            raise RecoveryRefused("submission without a persisted request: %s" % sample_id)
        # the authorization guard runs BEFORE the intent is written, so a
        # refusal never leaves an orphan intent (it runs again at the
        # chokepoint inside call_with_retries)
        self.provider_guard(ra.CALL_KIND_DIRECT, label="successor %s/%s %s" % (
            self.model_id, self.variant, sample_id))
        with self._ledger_lock:
            rounds = self.counted_rounds().get(sample_id, 0) + 1
            intent = OrderedDict([
                ("schema_version", SUBMISSION_SCHEMA), ("kind", "intent"),
                ("intent_id", uuid.uuid4().hex), ("run_id", sl.SUCCESSOR),
                ("model_id", self.model_id), ("variant", self.variant),
                ("sample_id", sample_id), ("iteration", iteration), ("round", rounds),
                ("request_sha256", utf8_sha256(request["request"])),
                ("response_created_at_utc", pending[1]),
                ("created_at_utc", orchestrator.common.utc_now_iso()),
            ])
            sw.durable_append_jsonl(self.paths.submissions_path, intent)
            self._open_intent = intent
            mirror = OrderedDict((s, {str(iteration): n}) for s, n in sorted(self.counted_rounds().items()))
            atomic_io.atomic_write_json(self.paths.retry_ledger_path, mirror)

    def _record_refusal(self, error):
        """A pre-run infrastructure refusal raised before the request was sent
        (call_with_retries raises that class only before fn())."""
        intent = getattr(self, "_open_intent", None)
        self._open_intent = None
        if not intent:
            return
        identity = (intent["sample_id"], intent["response_created_at_utc"])
        if identity in self.recorded_outcomes(TARGET_ITERATION):
            return
        sw.durable_append_jsonl(self.paths.submissions_path, OrderedDict([
            ("schema_version", SUBMISSION_SCHEMA), ("kind", "refused_before_send"),
            ("intent_id", intent["intent_id"]), ("run_id", sl.SUCCESSOR),
            ("model_id", self.model_id), ("variant", self.variant),
            ("sample_id", intent["sample_id"]), ("error_class", type(error).__name__),
            ("created_at_utc", orchestrator.common.utc_now_iso()),
        ]))

    def recorded_outcomes(self, iteration):
        """Identities (sample_id, created_at_utc) of persisted provider outcomes."""
        identities = set()
        path = self.paths.iter_generations_path(iteration)
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
        """Every counted intent has its recorded outcome, or an explicit
        operator resolution; an intent without either means a provider
        request may have been answered without being persisted.

        Such a sample may continue only when its counted rounds already reach
        the native bound (the native exhaust rule then ends it without another
        request); otherwise the loop STOPS."""
        ledger = self.submission_ledger()
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
        rounds = self.counted_rounds()
        blocking = [row for row in ambiguous if rounds.get(row["sample_id"], 0) < limit]
        for row in ambiguous:
            self.log("AMBIGUOUS submission %s (intent %s): no persisted outcome%s"
                     % (row["sample_id"], row["intent_id"],
                        "" if row in blocking else " - native bound reached, no further request"))
        if blocking:
            raise SuccessorStop(
                "AMBIGUOUS_SUBMISSION: %d request(s) of %s/%s were submitted without a persisted "
                "outcome (%s). The provider may have answered; nothing is resubmitted "
                "automatically. Resolve explicitly with thesis.recovery_successor_003.run --resolve-ambiguous."
                % (len(blocking), self.model_id, self.variant,
                   ", ".join(r["sample_id"] for r in blocking[:5])))
        return True

    def resolve_ambiguous(self, sample_id, note):
        """Operator decision (under the writer lock): the lost response of the
        open intent counts as a consumed round. Nothing is deleted."""
        ledger = self.submission_ledger()
        refused = set(r["intent_id"] for r in ledger if r["kind"] == "refused_before_send")
        resolved = set(r["intent_id"] for r in ledger if r["kind"] == "resolution")
        outcomes = self.recorded_outcomes(TARGET_ITERATION)
        open_intents = [r for r in ledger if r["kind"] == "intent" and r["sample_id"] == sample_id
                        and r["intent_id"] not in refused and r["intent_id"] not in resolved
                        and (r["sample_id"], r["response_created_at_utc"]) not in outcomes]
        if len(open_intents) != 1:
            raise RecoveryRefused("no single open ambiguous intent for %s" % sample_id)
        sw.durable_append_jsonl(self.paths.submissions_path, OrderedDict([
            ("schema_version", SUBMISSION_SCHEMA), ("kind", "resolution"),
            ("intent_id", open_intents[0]["intent_id"]), ("run_id", sl.SUCCESSOR),
            ("model_id", self.model_id), ("variant", self.variant), ("sample_id", sample_id),
            ("resolution", "lost_response_counted_as_round"), ("note", note),
            ("possible_duplicate_billing", True),
            ("created_at_utc", orchestrator.common.utc_now_iso()),
        ]))
        return open_intents[0]["intent_id"]

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

    # -- verified artifact readers ----------------------------------------

    def _parent_bytes(self, relative):
        ref = self.parent_lineage.refs.get(relative)
        if ref is None or ref.stage == "historical_only":
            raise RecoveryRefused("unregistered parent artifact: " + relative)
        data = checked_path(self.paths.root, relative).read_bytes()
        import hashlib
        if len(data) != ref.size or hashlib.sha256(data).hexdigest() != ref.raw_sha256:
            raise RecoveryRefused("parent artifact drift: " + relative)
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
        if iteration == 1:
            return self.lineage.view.unique_rows(self.paths.predecessor_relative("assembly.jsonl"),
                                                 self.paths.iter_run_id(1), self.model_id)
        return super().load_assembly_entries(iteration)

    def load_stage_records(self, iteration, stage_name):
        name = orchestrator.stage_output_file(self.config, stage_name)
        if iteration == 0:
            relative = self.paths.parent_relative(name)
            if relative not in self.parent_lineage.refs:
                return {}
            return self._keyed(_parse_jsonl_bytes(self._parent_bytes(relative), relative))
        if iteration == 1:
            relative = self.paths.predecessor_relative(name)
            if stage_name == "static_analysis":
                return self.iteration1_static()
            if not self.lineage.view.has(relative):
                # native: a missing stage file reads as {} (build_request_records
                # loads every stage for every variant); a stage this variant's
                # decisions depend on must exist
                needed = ((stage_name == "correctness_tests" and self.needs_tests())
                          or (stage_name == "dynamic_analysis" and self.needs_dynamic()))
                if needed:
                    raise RecoveryRefused("predecessor iteration 1 lacks %s" % stage_name)
                return {}
            return self.lineage.view.unique_rows(relative, self.paths.iter_run_id(1), self.model_id)
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

    # -- iteration-1 static: predecessor record + successor supplement ----

    def supplement_rows(self, tool):
        relative = ss.supplement_relative(sl.SUCCESSOR, self.model_id,
                                          self.paths.iter_run_id(1), tool)
        return sw.read_jsonl(checked_path(self.paths.root, relative))

    def iteration1_static(self):
        from thesis.evaluation.tool_config import resolve_tool_settings

        run = self.paths.iter_run_id(1)
        static_rel = self.paths.predecessor_relative("static_analysis.jsonl")
        records = self.lineage.view.unique_rows(static_rel, run, self.model_id)
        assembly = self.load_assembly_entries(1)
        expected = OrderedDict((s, orchestrator.execution_model_of(s))
                               for s, e in assembly.items() if e.get("assembled"))
        settings = resolve_tool_settings(self.config, "static_analysis")
        supplements = OrderedDict()
        for tool in self.settings["external_tools"]:
            rows = self.supplement_rows(tool)
            if not rows:
                continue
            indexed = ss.index_rows(rows, successor_run=sl.SUCCESSOR, predecessor_target=run,
                                    model=self.model_id, tool=tool, expected=expected)
            entries = OrderedDict()
            for sample, row in indexed.items():
                record = records.get(sample) or {}
                source_sha = record.get("sample_source_sha256")
                if (not source_sha or row.get("candidate_source_sha256") != source_sha
                        or row.get("variant") != self.variant or row.get("iteration") != 1
                        or (row.get("predecessor_static_artifact") or {}).get("raw_sha256")
                        != self.lineage.view.sha256(static_rel)):
                    raise RecoveryRefused("supplement row is not bound to the predecessor record")
                if self.authority.contract_sha256 is None or self.authority.authorization_sha256 is None:
                    raise RecoveryRefused("supplement rows exist but no persisted successor "
                                          "authorization is available to bind them")
                if (row.get("contract_sha256") != self.authority.contract_sha256
                        or row.get("authorization_sha256") != self.authority.authorization_sha256):
                    raise RecoveryRefused("supplement row was written under another authority")
                ss.validate_entry(row["entry"], tool, expected[sample], settings[tool], source_sha)
                entries[sample] = row["entry"]
            supplements[tool] = entries
        return ss.merge_static_records(records, supplements)

    # -- guards: iterations 0/1 are never re-measured or re-requested -----

    def _run_analysis_stages(self, iteration, stages):
        if iteration < TARGET_ITERATION:
            raise RecoveryRefused("iteration %d evidence is inherited; never re-measured" % iteration)
        return super()._run_analysis_stages(iteration, stages)

    def _submit(self, target_iteration):
        if target_iteration != TARGET_ITERATION:
            raise RecoveryRefused("predecessor requests are never resubmitted")
        if self.api_mode() != "direct":
            raise RecoveryRefused("the successor intent ledger covers direct submission only")
        self.verify_submission_ledger(target_iteration)
        try:
            return super()._submit(target_iteration)
        except orchestrator.common._pre_run_infrastructure_failure() as error:
            # raised by the chokepoint BEFORE fn(): the open intent was not sent
            self._record_refusal(error)
            raise

    def _require_successor_raw(self, path):
        expected = self.paths.raw_root / self.paths.iter_run_id(TARGET_ITERATION) / self.model_id
        if Path(path).name != "generations.jsonl" or Path(path).parent.resolve() != expected.resolve():
            raise RecoveryRefused("refusing to load/rewrite a non-successor response file")

    def _finish_responses(self, target_iteration):
        if target_iteration != TARGET_ITERATION:
            raise RecoveryRefused("predecessor responses are inherited")
        # every counted intent's outcome must be durable (or explicitly
        # resolved) BEFORE the wave may leave the submission phase; a lost
        # outcome then STOPs as AMBIGUOUS while a resolution can still lead to
        # a native retry
        sw.fsync_file(self.paths.iter_generations_path(target_iteration))
        self.verify_submission_ledger(target_iteration)
        return super()._finish_responses(target_iteration)

    def _submit_batch(self, target_iteration):
        if target_iteration != TARGET_ITERATION:
            raise RecoveryRefused("predecessor requests are never resubmitted")
        return super()._submit_batch(target_iteration)

    def _poll_batch(self, target_iteration):
        if target_iteration != TARGET_ITERATION:
            raise RecoveryRefused("predecessor batches are inherited")
        return super()._poll_batch(target_iteration)

    def _assemble(self, target_iteration):
        if target_iteration != TARGET_ITERATION:
            raise RecoveryRefused("predecessor assemblies are inherited")
        return super()._assemble(target_iteration)

    def mark_unusable(self, sample_id, iteration, reason):
        if iteration < 1:
            raise RecoveryRefused("the successor never re-classifies iteration 0")
        return super().mark_unusable(sample_id, iteration, reason)

    # -- external tools ----------------------------------------------------

    def pending_external(self, iteration):
        """Native pending tools, plus (iteration 1) a supplement tool whose
        ledger exists but does not cover EVERY assembled sample: the native
        run_model writes all entries of a tool, NOT_APPLICABLE stubs included,
        in one pass, so an interrupted supplement is never complete although
        its applicable samples may all be present. A tool without applicable
        samples and without rows is never waited for (native rule)."""
        pending = super().pending_external(iteration)
        if iteration != 1 or self.variant == "test_feedback":
            return pending
        listed = dict(pending)
        merged = self.load_stage_records(1, "static_analysis")
        assembled = self.iteration_samples(1)
        result = []
        for name in self.settings["external_tools"]:
            if name in listed:
                result.append((name, listed[name]))
                continue
            if name not in sl.SUPPLEMENT_TOOLS or not self.supplement_rows(name):
                continue
            missing = [s for s in assembled if name not in ((merged.get(s) or {}).get("tools") or {})]
            if missing:
                result.append((name, len(missing)))
        return result

    def external_target(self, iteration):
        if iteration == 1:
            return self.paths.iter_run_id(1)
        if iteration == TARGET_ITERATION:
            return self.paths.iter_run_id(TARGET_ITERATION)
        raise RecoveryRefused("no external analysis for iteration %d" % iteration)

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
        return ("%s%s %s %s -B -m thesis.recovery_successor_003.external --config %s --profile %s "
                "--run-id %s --target-run-id %s --model-id %s --variant %s --iteration %d "
                "--tool %s"
                % (head, flags, image, interpreter, sl.CONFIG_REL, sl.PROFILE, sl.SUCCESSOR,
                   target, self.model_id, self.variant, iteration, tool))

    def run_external_docker(self, pending, iteration):
        self.external_target(iteration)
        if iteration == 1:
            unexpected = [tool for tool, _count in pending if tool not in sl.SUPPLEMENT_TOOLS]
            if unexpected:
                raise RecoveryRefused("predecessor iteration 1 misses %s; only %s are successor "
                                      "supplements" % (", ".join(unexpected), "/".join(sl.SUPPLEMENT_TOOLS)))
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
            if result.returncode != 0:
                self.log("external %s FAILED (exit %d) - wave stays waiting" % (tool, result.returncode))
                failed.append(tool)
        return failed

    def write_pending_external(self, pending, iteration):
        lines = ["# Successor loop %s/%s waiting for external tools (iteration %d, target %s)"
                 % (self.model_id, self.variant, iteration, self.external_target(iteration)),
                 "# Re-run python3 -B -m thesis.recovery_successor_003.run; it starts the containers itself."]
        for tool, count in pending:
            lines.append("# %s: %d sample(s) missing" % (tool, count))
        self.paths.pending_external_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_io.atomic_write_text(self.paths.pending_external_path, "\n".join(lines) + "\n")
        self.log("waiting for external tools: %s" % ", ".join("%s(%d)" % p for p in pending))


class SuccessorAuthority:
    """Per-step authority: the successor contract rebuilds to the frozen one
    and the persisted authorization validates (rehydration checks)."""

    def __init__(self, config, config_path, root=None):
        from thesis.recovery_successor_003 import contract as sc

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
        from thesis.recovery_successor_003 import contract as sc

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
