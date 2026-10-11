"""Productive entrypoint of the successor run full_ext_recovery_004.

    python3 -B -m thesis.recovery_successor_004.run [--status | --dry-run]
            [--parallel-submissions N]
            [--resolve-ambiguous MODEL/VARIANT/SAMPLE@ITERATION --resolution-note TEXT]

Run from the repository root inside the pareval-thesis container with the
docker socket, PAREVAL_HOST_REPO and the provider .env (the launch topology
of recovery_001, 002 and 003). --status and --dry-run are read-only: no lock,
no authorization, no provider request, no measurement.

The productive invocation:
  1. refuses a dirty Git worktree (the implementation must be committed), a
     live tool container of ANY successor run and any other successor writer
     lock (cross-run quiescence);
  2. takes the single successor writer lock (no stale takeover);
  3. requires the successor contract to rebuild to the frozen definition and
     the provider endpoints to equal the origin (recovery_001) T0;
  4. bootstraps the run authorization (first start: full T0 sequence with a
     fresh runtime probe for the FULL five-model scope; afterwards:
     rehydration) - never a bypass;
  5. drives the 15 fresh loops under schedule api_first.v2 (see drive());
  6. verifies every model and persists each verification report.
Re-running continues the same state machines (resume after any crash).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.recovery_successor_004 import lineage as sl  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused  # noqa: E402
from thesis.repair import orchestrator  # noqa: E402
from thesis.recovery_successor_004 import routing as sr  # noqa: E402

READY_TO_SUBMIT = "ready_to_submit"
HELD = "held"
SUBMISSION_PHASES = ("requests_built", "submitted")
# phases AFTER the provider phase of an iteration (assembly, analyses,
# external tools and the decision of that iteration's answers)
POST_PROVIDER_PHASES = ("responses_merged", "assembled", "analyzed_waiting_external", "analyzed",
                        "decided")
# Driver schedule (recorded in the invocation record and the frozen contract).
SCHEDULE = "api_first.v2"
LANE_DOWN = "lane_down"


class NullAuthority:
    """Pre-T0 read-only gates (replay, preflight): no authority exists yet."""
    contract_sha256 = None
    authorization_sha256 = None

    def check(self):
        raise RecoveryRefused("read-only mode cannot step a loop")


class ReadOnlyAuthority(NullAuthority):
    """--status / --dry-run: the PERSISTED frozen contract and successor
    authorization (fingerprint-checked); installs no context and can never
    step a loop."""

    def __init__(self, config):
        from thesis.evaluation import pilot_run_contract as prc
        from thesis.evaluation import run_authorization as ra
        from thesis.recovery_successor_004 import contract as sc

        path = sc.frozen_path()
        self.contract_sha256 = prc.load_frozen(path)["contract_sha256"] if path.is_file() else None
        stored = ra.load_authorization(config, sl.SUCCESSOR)
        self.authorization_sha256 = (
            stored["authorization_sha256"]
            if stored and stored.get("frozen_contract_sha256") == self.contract_sha256
            and ra.authorization_fingerprint(stored) == stored.get("authorization_sha256") else None)


def load_lineages(root=REPO_ROOT):
    from thesis.evaluation import recovery_context

    lineage = sl.load(root)
    parent = recovery_context.load_lineage()
    if parent.document["lineage_sha256"] != lineage.document["predecessor"]["parent_lineage_sha256"]:
        raise RecoveryRefused("parent lineage differs from the successor binding")
    return lineage, parent


def key(loop):
    return "%s/%s" % (loop.model_id, loop.variant)


def lane_order(loops):
    """Lane rank = rank of the lane's highest-priority model (MODELS order)."""
    ranks = OrderedDict()
    for model in sl.MODELS:
        for loop in loops:
            if loop.model_id == model and loop.lane not in ranks:
                ranks[loop.lane] = len(ranks)
    return ranks


def priority_key(loop, ranks=None):
    """Strict model priority (sl.MODELS) by provider lane; inside a lane the
    variants of its models alternate (fair, no model starves)."""
    ranks = ranks if ranks is not None else {}
    return (ranks.get(loop.lane, 99), sl.VARIANTS.index(loop.variant), sl.MODELS.index(loop.model_id))


def prioritized(loops):
    ranks = lane_order(loops)
    return sorted(loops, key=lambda loop: priority_key(loop, ranks))


def build_loops(config, config_path, lineage, parent_lineage, authority, writer_token=None,
                models=None, adapter_factory=None, external_runner=None,
                loop_class=sr.SuccessorRepairLoop):
    profile = (config.get("profiles") or {}).get(sl.PROFILE)
    by_id = {m["id"]: m for m in config.get("models") or [] if m.get("enabled")}
    models = list(models or sl.MODELS)
    if len(set(models)) != len(models):
        raise RecoveryRefused("duplicate model ids in the successor scope: %s" % models)
    loops = []
    for model in models:
        if model not in sl.MODELS or model not in by_id:
            raise RecoveryRefused("model %s is outside the successor scope" % model)
        for variant in sl.VARIANTS:
            loops.append(loop_class(
                config, config_path, sl.PROFILE, profile, by_id[model], variant, "g++",
                adapter_factory, lineage=lineage, parent_lineage=parent_lineage,
                authority=authority, writer_token=writer_token, external_runner=external_runner))
    return prioritized(loops)


def is_global_failure(error):
    """A failure that concerns the whole run (never one loop only)."""
    from thesis.evaluation.run_authorization import PreRunInfrastructureFailure

    if isinstance(error, BaseException) and not isinstance(error, Exception):
        return True
    return isinstance(error, (sr.GlobalIntegrityError, PreRunInfrastructureFailure))


def advance(loop, wave):
    """Serial native steps of ONE loop until it reaches the provider phase of
    WAVE (READY_TO_SUBMIT), a phase that belongs to a later schedule phase
    (HELD), done, or a blocked outcome."""
    while True:
        if sr.STOP_EVENT.is_set():
            raise sr.StopRequested("stop requested; loop %s is not advanced further" % key(loop))
        state = loop.load_wave_state()
        phase, iteration = state["phase"], int(state["iteration"])
        if phase in SUBMISSION_PHASES:
            if iteration == wave:
                return READY_TO_SUBMIT
            if iteration > wave:
                return HELD
            raise RecoveryRefused("loop %s is still in the provider phase of iteration %d"
                                  % (key(loop), iteration))
        if phase in POST_PROVIDER_PHASES and iteration >= wave:
            return HELD
        outcome = loop.step()
        if outcome == orchestrator.OUTCOME_DONE or outcome in orchestrator.BLOCKED_OUTCOMES:
            return outcome


class SubmissionPool:
    """Provider rounds of READY loops of ONE wave on `parallel` worker threads.

    A free worker takes the highest-priority queued loop that is eligible
    (its not-before time passed, its provider lane is neither paused nor
    down). One step = the loop's whole provider round (requests inside a loop
    stay sequential). Outcome handling:
      advanced          left the provider phase (analysed later)
      blocked_api       recorded provider failures: re-queued ONCE per wave
                        after api_retry_delay (the native bounded policy;
                        every round stays counted)
      lane trouble      ProviderPaused, or blocked_api with a tripped lane:
                        the LANE pauses for api_retry_delay (its queued loops
                        wait, every other lane goes on) and then re-opens
                        HALF-OPEN: one probe request of a sample without a
                        counted round at this iteration (a loop whose next
                        sample already used a round declines the probe and
                        waits); a trip of the probe = lane DOWN for this
                        invocation (its loops stay resumable); every loop of
                        the lane declining = lane DOWN as well
      loop failure      SuccessorStop (e.g. AMBIGUOUS_SUBMISSION) or any other
                        Exception: that loop only, recorded
      global failure    GlobalIntegrityError, pre-run infrastructure failure,
                        BaseException: STOP_EVENT - no new intent anywhere
    """

    def __init__(self, wave, parallel, outcomes, outcomes_lock, log, api_retry_delay, clock, wait,
                 max_sleep, ranks, on_advanced=None, poll=0.2, down_lanes=None):
        self.wave = wave
        self.parallel = max(1, int(parallel))
        self.outcomes = outcomes
        self.outcomes_lock = outcomes_lock
        self.log = log
        self.api_retry_delay = float(api_retry_delay)
        self.clock = clock
        self.wait = wait
        self.max_sleep = max_sleep
        self.ranks = ranks
        self.on_advanced = on_advanced
        self.poll = poll
        self.cond = threading.Condition()
        self.queue = []
        self.sequence = 0
        self.not_before = {}
        self.lanes = {}
        self.inflight = 0
        self.inflight_by_lane = {}
        self.closed = False
        self.requeued = set()
        self.advanced = []
        self.global_error = None
        self.timer_waiting = False
        self.threads = []
        # lanes that went DOWN earlier in this invocation stay down
        self.down_lanes = down_lanes if down_lanes is not None else set()

    # -- queue ------------------------------------------------------------

    def _lane(self, lane):
        return self.lanes.setdefault(lane, {"paused_until": None, "pauses": 0,
                                            "down": lane in self.down_lanes, "declined": set()})

    def _declined(self, loop):
        """A loop that declined the probe of its half-open lane waits until the
        lane is closed again (a healthy answer) or goes down."""
        lane = self._lane(loop.lane)
        if not sr.LANES.half_open(loop.lane):
            lane["declined"].clear()
            return False
        return key(loop) in lane["declined"]

    def _lane_down(self, loop_or_lane, reason):
        name = getattr(loop_or_lane, "lane", loop_or_lane)
        lane = self._lane(name)
        lane["down"] = True
        self.down_lanes.add(name)
        self.log("SUCCESSOR_LANE %s DOWN in wave %d (%s); its loops stay resumable (nothing is "
                 "resubmitted in this invocation)" % (name, self.wave, reason))
        down = [entry for entry in self.queue if entry[2].lane == name]
        for entry in down:
            self.queue.remove(entry)
        blocked = [entry[2] for entry in down]
        if not isinstance(loop_or_lane, str):
            blocked.insert(0, loop_or_lane)
        for item in blocked:
            self._final(item, sr.ProviderPaused("%s: provider lane %s is down in wave %d"
                                                % (LANE_DOWN, name, self.wave)))

    def submit(self, loop):
        with self.cond:
            if self._lane(loop.lane)["down"]:
                self._final(loop, sr.ProviderPaused("%s: provider lane %s is down in wave %d"
                                                    % (LANE_DOWN, loop.lane, self.wave)))
                return
            self.sequence += 1
            self.queue.append((priority_key(loop, self.ranks), self.sequence, loop))
            self.queue.sort(key=lambda entry: entry[:2])
            self.cond.notify_all()

    def close(self):
        with self.cond:
            self.closed = True
            # no further loop can arrive: a half-open lane whose every queued
            # loop declined the probe cannot be probed in this wave
            for name in list(self.lanes):
                self._probe_exhausted(name)
            self.cond.notify_all()

    def _final(self, loop, outcome):
        with self.outcomes_lock:
            self.outcomes[key(loop)] = outcome

    def _eligible(self, now):
        for entry in self.queue:
            loop = entry[2]
            lane = self._lane(loop.lane)
            in_flight = self.inflight_by_lane.get(loop.lane, 0)
            if lane["down"]:
                continue  # finalised by _lane_down; never dispatched again
            if lane["paused_until"] is not None and (now < lane["paused_until"] or in_flight):
                continue  # paused, or a pre-pause request is still in flight: re-open only when quiet
            if sr.LANES.half_open(loop.lane) and in_flight:
                continue  # one half-open probe at a time; wait for its outcome
            if self.not_before.get(key(loop), 0.0) > now:
                continue
            if self._declined(loop):
                continue
            return entry
        return None

    def _next_wake(self):
        times = []
        for entry in self.queue:
            loop = entry[2]
            if self._declined(loop) or self.inflight_by_lane.get(loop.lane, 0):
                continue  # waits for a lane event, not for a time
            lane = self._lane(loop.lane)
            times.append(max(self.not_before.get(key(loop), 0.0), lane["paused_until"] or 0.0))
        return min(times) if times else None

    # -- workers ----------------------------------------------------------

    def start(self):
        for index in range(self.parallel):
            thread = threading.Thread(target=self._worker, name="submit-w%d-%d" % (self.wave, index))
            sr.WORKERS.append(thread)
            self.threads.append(thread)
            thread.start()
        return self

    def _worker(self):
        while True:
            with self.cond:
                loop = None
                while loop is None:
                    if sr.STOP_EVENT.is_set() or self.global_error is not None:
                        self.cond.notify_all()
                        return
                    now = self.clock()
                    entry = self._eligible(now)
                    if entry is not None:
                        self.queue.remove(entry)
                        loop = entry[2]
                        lane = self._lane(loop.lane)
                        if lane["paused_until"] is not None and now >= lane["paused_until"]:
                            lane["paused_until"] = None  # the pause is over: half-open probe
                            lane["successes_at_reopen"] = sr.LANES.successes(loop.lane)
                            sr.LANES.reopen(loop.lane)
                            self.log("SUCCESSOR_LANE %s re-opened (half-open probe) in wave %d"
                                     % (loop.lane, self.wave))
                        self.inflight += 1
                        self.inflight_by_lane[loop.lane] = self.inflight_by_lane.get(loop.lane, 0) + 1
                        break
                    if self.closed and not self.queue and self.inflight == 0:
                        self.cond.notify_all()
                        return
                    wake = self._next_wake()
                    if wake is not None and wake > now and not self.timer_waiting:
                        self.timer_waiting = True
                        self.cond.release()
                        try:
                            self.wait(min(wake - now, self.max_sleep))
                        finally:
                            self.cond.acquire()
                            self.timer_waiting = False
                            self.cond.notify_all()
                        continue
                    self.cond.wait(timeout=self.poll)
            try:
                outcome = loop.step()
            except BaseException as error:  # noqa: BLE001 - classified in _handle
                outcome = error
            with self.cond:
                self.inflight -= 1
                self.inflight_by_lane[loop.lane] -= 1
                self._handle(loop, outcome)
                self._probe_exhausted(loop.lane)
                self.cond.notify_all()

    def _probe_exhausted(self, name):
        """Half-open lane, nothing in flight, and every queued loop of the lane
        declined the probe: no loop can probe without spending a sample's last
        round - the lane goes down for this invocation."""
        lane = self._lane(name)
        if (lane["down"] or not self.closed or not sr.LANES.half_open(name)
                or self.inflight_by_lane.get(name, 0)):
            return
        queued = [entry[2] for entry in self.queue if entry[2].lane == name]
        if queued and all(key(loop) in lane["declined"] for loop in queued):
            self._lane_down(name, "every queued loop declined the half-open probe")

    def _requeue(self, loop, delay):
        self.not_before[key(loop)] = self.clock() + delay
        self.sequence += 1
        self.queue.append((priority_key(loop, self.ranks), self.sequence, loop))
        self.queue.sort(key=lambda entry: entry[:2])

    def _handle(self, loop, outcome):
        lane = self._lane(loop.lane)
        if isinstance(outcome, BaseException) and is_global_failure(outcome):
            sr.STOP_EVENT.set()
            self.global_error = outcome
            self._final(loop, outcome)
            self.log("SUCCESSOR_GLOBAL_STOP in wave %d by %s: %s: %s"
                     % (self.wave, key(loop), type(outcome).__name__, outcome))
            return
        if isinstance(outcome, sr.ProbeDeclined):
            if lane["down"]:
                self._final(loop, sr.ProviderPaused("%s: provider lane %s is down in wave %d"
                                                    % (LANE_DOWN, loop.lane, self.wave)))
                return
            lane["declined"].add(key(loop))
            self._requeue(loop, 0.0)
            return
        trouble = (isinstance(outcome, sr.ProviderPaused)
                   or (outcome == orchestrator.OUTCOME_BLOCKED_API and sr.LANES.tripped(loop.lane)))
        if trouble:
            now = self.clock()
            if lane["down"]:
                self._final(loop, sr.ProviderPaused("%s: provider lane %s is down in wave %d"
                                                    % (LANE_DOWN, loop.lane, self.wave)))
                return
            if lane["paused_until"] is not None:
                # paused, or the pause expired but the quiet re-open has not
                # happened yet (a pre-pause request returned late): this is no
                # probe outcome - wait for the real half-open probe
                self._requeue(loop, 0.0)
                return
            if lane["pauses"] >= 1 and sr.LANES.successes(loop.lane) <= lane.get("successes_at_reopen", 0):
                # no healthy answer since the re-open: the probe failed
                self._lane_down(loop, "the half-open probe failed")
                return
            lane["pauses"] += 1
            lane["paused_until"] = now + self.api_retry_delay
            self.log("SUCCESSOR_LANE %s PAUSED in wave %d for %.0f s (%s); other lanes continue"
                     % (loop.lane, self.wave, self.api_retry_delay, key(loop)))
            self._requeue(loop, 0.0)
            return
        if outcome == orchestrator.OUTCOME_BLOCKED_API:
            if lane["down"]:
                self._final(loop, sr.ProviderPaused("%s: provider lane %s is down in wave %d"
                                                    % (LANE_DOWN, loop.lane, self.wave)))
                return
            marker = (key(loop), self.wave)
            if marker not in self.requeued:
                self.requeued.add(marker)
                self.log("SUCCESSOR_PHASE SUBMIT@%d: re-queueing %s after recorded provider failures "
                         "(native bounded retry), in %.0f s" % (self.wave, key(loop), self.api_retry_delay))
                self._requeue(loop, self.api_retry_delay)
                return
            self._final(loop, outcome)
            return
        if outcome in (orchestrator.OUTCOME_ADVANCED, orchestrator.OUTCOME_DECIDED):
            self.advanced.append(loop)
            if self.on_advanced is not None:
                self.on_advanced(loop)
            return
        self._final(loop, outcome)

    def join(self):
        try:
            for thread in self.threads:
                thread.join()
        except BaseException:
            # stop at the next request boundary, wait for in-flight calls
            sr.STOP_EVENT.set()
            with self.cond:
                self.cond.notify_all()
            for thread in self.threads:
                thread.join()
            raise
        finally:
            for thread in self.threads:
                if not thread.is_alive() and thread in sr.WORKERS:
                    sr.WORKERS.remove(thread)
        if self.global_error is not None:
            raise self.global_error
        if sr.STOP_EVENT.is_set():
            raise sr.StopRequested("stop requested during the submission phase of wave %d" % self.wave)
        return self.advanced


def _serial(loops, wave, outcomes, outcomes_lock, log, sleep, external_retry_delay, label,
            on_ready=None):
    """Serial native steps of every loop (priority order) for one schedule
    phase. A blocked_external loop is retried once (missing-only) after
    external_retry_delay. Returns (ready, held)."""
    ready, held = [], []
    for loop in loops:
        if sr.STOP_EVENT.is_set():
            raise sr.StopRequested("stop requested; no further loop is advanced")
        retried = False
        while True:
            try:
                outcome = advance(loop, wave)
            except Exception as error:  # noqa: BLE001 - classified below
                if is_global_failure(error):
                    sr.STOP_EVENT.set()
                    raise
                with outcomes_lock:
                    outcomes[key(loop)] = error
                break
            except BaseException:
                # operator abort / interpreter exit: no loop may advance or submit
                sr.STOP_EVENT.set()
                raise
            if outcome == orchestrator.OUTCOME_BLOCKED_EXTERNAL and not retried:
                retried = True
                log("SUCCESSOR_PHASE %s: re-running the missing external tools of %s (missing-only) "
                    "in %.0f s" % (label, key(loop), external_retry_delay))
                sleep(external_retry_delay)
                continue
            if outcome == READY_TO_SUBMIT:
                ready.append(loop)
                if on_ready is not None:
                    on_ready(loop)
            elif outcome == HELD:
                held.append(loop)
            else:
                with outcomes_lock:
                    outcomes[key(loop)] = outcome
            break
    return ready, held


def drive(loops, parallel=1, log=print, api_retry_delay=600.0, sleep=None, external_retry_delay=60.0,
          clock=None, max_sleep=5.0):
    """Drive every loop to done/blocked under schedule api_first.v2.
    Returns {loop: outcome or exception}.

      PREPARE    serial: iteration-0 decision from the verified parent evidence
                 and the iteration-1 requests of every loop (no analysis runs:
                 the parent is complete and is never re-measured)
      SUBMIT@1   the provider round of EVERY loop at iteration 1 on `parallel`
                 workers, strict model priority, lane pauses; nothing is
                 analysed while iteration-1 requests are open
      ANALYZE@1  serial, model priority: assembly, internal analyses, native
      + SUBMIT@2 PARCOACH/LLOV containers and the decision of iteration 1 per
                 loop; a loop whose iteration-2 requests are built enters the
                 iteration-2 submission pool IMMEDIATELY (the analyses of the
                 other loops are needed for their own decisions and run
                 concurrently; no iteration-2 analysis starts before the last
                 iteration-2 request ended)
      ANALYZE@2  serial: assembly, analyses, decision of iteration 2 -> done
                 (max_iterations=2: no provider request follows iteration 2)
    Loops already past a phase (resume) are held until that phase comes."""
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    if len(set(key(loop) for loop in loops)) != len(loops):
        raise RecoveryRefused("two loops share the same model/variant")
    ordered = prioritized(loops)
    ranks = lane_order(ordered)
    for lane in ranks:
        sr.LANES.reset(lane)  # an invocation starts with every lane closed
    outcomes = OrderedDict()
    lock = threading.Lock()

    down_lanes = set()  # lanes DOWN for the rest of this invocation

    def pool(wave, on_advanced=None):
        return SubmissionPool(wave, parallel, outcomes, lock, log, api_retry_delay, clock, sleep,
                              max_sleep, ranks, on_advanced=on_advanced, down_lanes=down_lanes).start()

    log("SUCCESSOR_PHASE PREPARE: %s" % ", ".join(key(loop) for loop in ordered))
    ready, held = _serial(ordered, 1, outcomes, lock, log, sleep, external_retry_delay, "PREPARE")
    advanced = []
    if ready:
        log("SUCCESSOR_PHASE SUBMIT@1: %s" % ", ".join(key(loop) for loop in ready))
        first = pool(1)
        for loop in ready:
            first.submit(loop)
        first.close()
        try:
            advanced = first.join()
        except BaseException:
            _log_end(log, outcomes)
            raise
    live = prioritized(held + advanced)
    for lane in ranks:
        if lane not in down_lanes:
            sr.LANES.reset(lane)  # healthy lanes start the new wave closed-circuit
    for lane in sorted(down_lanes):
        log("SUCCESSOR_LANE %s stays DOWN in wave 2 (down in wave 1 of this invocation)" % lane)
    log("SUCCESSOR_PHASE ANALYZE@1+SUBMIT@2: %s" % ", ".join(key(loop) for loop in live))
    second = pool(2, on_advanced=lambda loop: None)

    def submit2(loop):
        log("SUCCESSOR_PHASE SUBMIT@2: %s" % key(loop))
        second.submit(loop)

    try:
        # resumed loops whose iteration-2 requests already exist go first
        resumed, pending = [], []
        for loop in live:
            state = loop.load_wave_state()
            if state["phase"] in SUBMISSION_PHASES and int(state["iteration"]) == 2:
                resumed.append(loop)
            else:
                pending.append(loop)
        for loop in resumed:
            submit2(loop)
        _ready2, held2 = _serial(pending, 2, outcomes, lock, log, sleep, external_retry_delay,
                                 "ANALYZE@1", on_ready=submit2)
    except BaseException as error:
        sr.STOP_EVENT.set()
        second.close()
        try:
            second.join()
        except BaseException:  # noqa: BLE001 - reported below
            pass
        _log_end(log, outcomes)
        if second.global_error is not None and isinstance(error, sr.StopRequested):
            raise second.global_error from error
        raise
    second.close()
    advanced2 = second.join()
    final = prioritized(held2 + advanced2)
    log("SUCCESSOR_PHASE ANALYZE@2: %s" % ", ".join(key(loop) for loop in final))
    _ready3, _held3 = _serial(final, sl.MAX_ITERATIONS + 1, outcomes, lock, log, sleep,
                              external_retry_delay, "ANALYZE@2")
    _log_end(log, outcomes)
    return OrderedDict((key(loop), outcomes[key(loop)]) for loop in loops if key(loop) in outcomes)


def _log_end(log, outcomes):
    log("SUCCESSOR_PHASE END: %s" % json.dumps(OrderedDict(
        (k, v if isinstance(v, str) else "%s: %s" % (type(v).__name__, v))
        for k, v in outcomes.items())))
    log("SUCCESSOR_LANES %s" % json.dumps(sr.LANES.snapshot(), sort_keys=True))


def require_clean_worktree(root=REPO_ROOT):
    status = subprocess.check_output(["git", "-c", "safe.directory=" + root.as_posix(), "-C",
                                      str(root), "status", "--porcelain"], text=True)
    if status.strip():
        raise RecoveryRefused("commit the reviewed implementation before starting/resuming the "
                              "successor (git status is not clean)")
    return subprocess.check_output(["git", "-c", "safe.directory=" + root.as_posix(), "-C",
                                    str(root), "rev-parse", "HEAD"], text=True).strip()


def require_no_tool_containers():
    """Refuse while ANY successor tool container (an orphan of a crashed
    driver of this or another successor run) still exists: it could still
    be writing successor evidence."""
    # a label filter without a value matches every successor run
    result = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}", "--filter",
                             "label=%s" % sr.CONTAINER_LABEL], capture_output=True, text=True)
    if result.returncode != 0:
        raise RecoveryRefused("docker is not reachable: %s" % result.stderr.strip())
    labelled = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if labelled:
        raise RecoveryRefused("successor tool containers still exist (%s); wait for them or remove "
                              "them explicitly before resuming" % labelled)
    return True


def require_no_other_writer(root=REPO_ROOT):
    """Cross-run quiescence: no other successor run holds a writer lock."""
    from thesis.evaluation import successor_writer as sw

    directory = Path(root) / sw.LOCK_DIR
    others = sorted(p.name for p in directory.glob("*.writer.lock")
                    if p.name != "%s.writer.lock" % sl.SUCCESSOR) if directory.is_dir() else []
    if others:
        raise RecoveryRefused("another successor writer lock exists (%s); successor runs never write "
                              "concurrently" % others)
    return True


def status_rows(config, config_path, lineage, parent):
    rows = []
    for loop in build_loops(config, config_path, lineage, parent, ReadOnlyAuthority(config)):
        wave = loop.load_wave_state()
        counts = OrderedDict()
        for row in loop.sample_states().values():
            counts[row.get("status")] = counts.get(row.get("status"), 0) + 1
        rows.append(OrderedDict([
            ("loop", key(loop)), ("lane", loop.lane), ("iteration", wave["iteration"]),
            ("phase", wave["phase"]), ("status_counts", counts),
            ("intents", OrderedDict(("iter%d" % i, len(loop.submission_intents(i)))
                                    for i in sl.PROVIDER_ITERATIONS))]))
    return rows


def dry_run(config, config_path, lineage, parent, authority=None):
    """Read-only: the fresh start of every loop (iteration-0 evidence
    coverage, iteration-0 decisions, iteration-1 requests - built twice,
    compared without their timestamps)."""
    from thesis.evaluation.condition_hashing import canonical_sha256

    report = []
    authority = authority or ReadOnlyAuthority(config)
    for loop in build_loops(config, config_path, lineage, parent, authority):
        wave = loop.load_wave_state()
        entry = OrderedDict([("loop", key(loop)), ("lane", loop.lane), ("phase", wave["phase"]),
                             ("iteration", wave["iteration"])])
        if wave["phase"] == "start":
            entry["iteration0_missing_internal"] = loop.missing_internal_stages(0)
            entry["iteration0_pending_external"] = loop.pending_external(0)
            decisions = loop.iteration0_decisions()
            counts = OrderedDict()
            for decision in decisions.values():
                counts[decision["status"]] = counts.get(decision["status"], 0) + 1
            entry["iteration0_decisions"] = counts
            active = [s for s, d in decisions.items() if d["status"] == orchestrator.STATUS_ACTIVE]

            def projection():
                return [OrderedDict((f, r[f]) for f in sr.REQUEST_FIELDS)
                        for r in loop.build_request_records(1, active)]

            first, second = projection(), projection()
            if first != second:
                raise RecoveryRefused("iteration-1 requests of %s do not build deterministically" % key(loop))
            entry["iteration1_requests"] = len(first)
            entry["iteration1_requests_sha256"] = canonical_sha256(first)
        report.append(entry)
    return report


def main(argv=None):
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=sl.CONFIG_REL)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    # 1 = one request in flight; >1 runs the provider rounds of different
    # loops concurrently (faster; request timing then not comparable to the
    # sequential recovery_001 waves)
    parser.add_argument("--parallel-submissions", type=int, default=1)
    parser.add_argument("--api-retry-delay-seconds", type=float, default=600.0)
    parser.add_argument("--external-retry-delay-seconds", type=float, default=60.0)
    parser.add_argument("--resolve-ambiguous", default=None,
                        help="MODEL/VARIANT/SAMPLE@ITERATION: count the open lost response as a round")
    parser.add_argument("--resolution-note", default=None)
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != REPO_ROOT:
        raise RecoveryRefused("run from the repository root (outputs are repo-relative)")
    config_path = str((REPO_ROOT / args.config).resolve())
    config = load_config(config_path)
    lineage, parent = load_lineages()
    lineage.verify()
    if args.status:
        print(json.dumps(status_rows(config, config_path, lineage, parent), indent=2))
        return 0
    if args.dry_run:
        print(json.dumps(dry_run(config, config_path, lineage, parent), indent=2))
        return 0

    from thesis.evaluation import successor_writer as sw

    head = require_clean_worktree()
    require_no_tool_containers()
    require_no_other_writer()
    lock = sw.WriterLock(REPO_ROOT, sl.SUCCESSOR, "run_successor")
    lock.acquire()
    # the writer proof every productive successor contract rebuild requires
    os.environ[sw.TOKEN_ENV] = lock.token
    try:
        return _productive(args, config, config_path, lineage, parent, lock, head)
    finally:
        sr.STOP_EVENT.set()
        alive = [t.name for t in sr.WORKERS if t.is_alive()]
        if alive:
            print("WRITER LOCK KEPT: submission workers still alive (%s); the lock stays on disk "
                  "until they have ended and an operator removed it" % ", ".join(alive))
        else:
            lock.release()
            os.environ.pop(sw.TOKEN_ENV, None)


def _productive(args, config, config_path, lineage, parent, lock, head):
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.evaluation import run_authorization as ra
    from thesis.recovery_successor_004 import contract as sc
    from thesis.recovery_successor_004 import readiness as srd
    from thesis.recovery_successor_004 import verify as vs

    probe_loops = build_loops(config, config_path, lineage, parent, NullAuthority())
    print("SUCCESSOR_INVOCATION", json.dumps(OrderedDict([
        ("head", head), ("schedule", SCHEDULE), ("parallel_submissions", args.parallel_submissions),
        ("api_retry_delay_seconds", args.api_retry_delay_seconds),
        ("lane_trip_failures", sr.LANE_TRIP_FAILURES),
        ("model_priority", list(sl.MODELS)),
        ("lanes", OrderedDict((key(loop), loop.lane) for loop in probe_loops))])))
    frozen = prc.load_frozen(sc.frozen_path())
    rebuilt = sc.build(config_path, sl.SUCCESSOR)
    if rebuilt["contract_sha256"] != frozen["contract_sha256"]:
        raise RecoveryRefused("successor contract drift before start")
    # the provider endpoints of the successor models must be the ones the
    # origin recovery_001 was authorized for (every invocation; hashes only)
    if srd.current_endpoints(config) != srd.predecessor_endpoints(lineage):
        raise RecoveryRefused("provider endpoint of a successor model differs from the origin "
                              "authorization")
    if ra.load_authorization(config, sl.SUCCESSOR) is None:
        # first start: the methodology replay (recovery_001's native decisions
        # and requests through the 004 routing) must reproduce the proof
        from thesis.recovery_successor_004 import equivalence as se

        proof = json.loads((sc.definitions(REPO_ROOT) / "equivalence.json").read_text(encoding="utf-8"))
        replay = se.methodology_replay(config, config_path, lineage, parent)
        if replay != proof.get("methodology_replay"):
            raise RecoveryRefused("first-start methodology replay differs from the frozen proof")
        print("SUCCESSOR_FIRST_START_METHODOLOGY_REPLAY PASS", replay["digest"])
        # first start: re-measure the readiness prerequisites (images, tool
        # identities, TSan/mmap, host path, keys, disk) twice before T0
        readiness = json.loads((sc.definitions(REPO_ROOT) / "readiness.json").read_text(encoding="utf-8"))
        probes = [srd.probe(config), srd.probe(config)]
        problems, _keys, _endpoints = srd.check_runtime(config, lineage, probes)
        if problems or any(p["sha256"] != readiness["runtime_condition_sha256"] for p in probes):
            raise RecoveryRefused("first-start runtime gate failed: %s" % "; ".join(problems))
        print("SUCCESSOR_FIRST_START_RUNTIME_GATE PASS", probes[0]["sha256"])
    # first start: the full T0 sequence for the FULL contracted model set
    # (a narrowed first start is refused); afterwards: rehydration
    bootstrap = ra.bootstrap_provider_run(config, config_path, sl.PROFILE, sl.SUCCESSOR,
                                          contract_path=sc.frozen_path(),
                                          stage="successor_bootstrap",
                                          requested_model_scope=list(sl.MODELS))
    print("SUCCESSOR_BOOTSTRAP", json.dumps(bootstrap, default=str), "head", head)
    if (bootstrap.get("mode") not in (ra.MODE_FIRST_START, ra.MODE_REHYDRATED, ra.MODE_PROCESS_CACHE)
            or not bootstrap.get("authorization_sha256")):
        raise RecoveryRefused("no successor authorization is installed (%s)" % bootstrap.get("mode"))
    authority = sr.SuccessorAuthority(config, config_path)
    authority.check()
    loops = build_loops(config, config_path, lineage, parent, authority, lock.token)
    if args.resolve_ambiguous:
        target, _, iteration = args.resolve_ambiguous.rpartition("@")
        model, variant, sample = target.split("/", 2)
        if not args.resolution_note or not iteration.isdigit():
            raise RecoveryRefused("--resolve-ambiguous MODEL/VARIANT/SAMPLE@ITERATION requires "
                                  "--resolution-note")
        chosen = [loop for loop in loops if loop.model_id == model and loop.variant == variant]
        if len(chosen) != 1:
            raise RecoveryRefused("unknown loop %s/%s" % (model, variant))
        intent = chosen[0].resolve_ambiguous(sample, args.resolution_note, int(iteration))
        print("RESOLVED_AMBIGUOUS_SUBMISSION", model, variant, sample, iteration, intent)
        return 0
    outcomes = drive(loops, args.parallel_submissions,
                     api_retry_delay=args.api_retry_delay_seconds,
                     external_retry_delay=args.external_retry_delay_seconds)
    failures = OrderedDict()
    for name, outcome in outcomes.items():
        if isinstance(outcome, BaseException):
            failures[name] = "%s: %s" % (type(outcome).__name__, outcome)
            traceback.print_exception(type(outcome), outcome, outcome.__traceback__)
    print("SUCCESSOR_LOOP_OUTCOMES", json.dumps(OrderedDict(
        (k, v if isinstance(v, str) else "%s: %s" % (type(v).__name__, v))
        for k, v in outcomes.items()), indent=2))
    results = OrderedDict()
    for model in sl.MODELS:
        results[model] = vs.verify_model(config, config_path, model, authority=authority)
        print("SUCCESSOR_MODEL_VERIFICATION", model, results[model]["status"])
        # persisted under the writer lock: the verdict is evidence, not only stdout
        vs.write_report(config, results[model])
    print(json.dumps(OrderedDict((m, vs.summary(r)) for m, r in results.items()), indent=2))
    done = all(r["status"] == "PASS" for r in results.values()) and not failures
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
