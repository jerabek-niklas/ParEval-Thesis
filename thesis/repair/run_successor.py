"""Productive entrypoint of the successor run full_ext_recovery_002.

    python3 -B -m thesis.repair.run_successor [--status | --dry-run]
            [--model-id M ...] [--parallel-submissions N]

Run from the repository root inside the pareval-thesis container with the
docker socket, PAREVAL_HOST_REPO and the provider .env (the same launch
topology as recovery_001). --status and --dry-run are read-only: no lock,
no authorization, no provider request, no measurement.

The productive invocation:
  1. refuses a dirty Git worktree (the implementation must be committed);
  2. takes the single successor writer lock (no stale takeover);
  3. requires the successor contract to rebuild to the frozen definition;
  4. bootstraps the run authorization (first start: full T0 sequence with a
     fresh runtime probe; afterwards: rehydration) - never a bypass;
  5. drives the four continuation loops; provider submissions of different
     loops run in parallel threads (requests inside a loop stay sequential,
     analysis/assembly/external tools stay serial);
  6. verifies every model whose three variants are terminal.
Re-running continues the same state machines (resume after any crash).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import traceback
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import successor_lineage as sl  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused  # noqa: E402
from thesis.repair import orchestrator  # noqa: E402
from thesis.repair import successor_routing as sr  # noqa: E402

READY_TO_SUBMIT = "ready_to_submit"
SUBMISSION_PHASES = ("requests_built", "submitted")


class NullAuthority:
    """Pre-T0 read-only gates (replay, preflight): no authority exists yet."""
    contract_sha256 = None
    authorization_sha256 = None

    def check(self):
        raise RecoveryRefused("read-only mode cannot step a loop")


class ReadOnlyAuthority(NullAuthority):
    """--status / --dry-run: the PERSISTED frozen contract and successor
    authorization (fingerprint-checked) so successor-owned evidence can be
    read and bound; installs no context and can never step a loop."""

    def __init__(self, config):
        from thesis.evaluation import pilot_run_contract as prc
        from thesis.evaluation import run_authorization as ra
        from thesis.evaluation import successor_contract as sc

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
        for variant in sl.CONTINUE_VARIANTS:
            loops.append(loop_class(
                config, config_path, sl.PROFILE, profile, by_id[model], variant, "g++",
                adapter_factory, lineage=lineage, parent_lineage=parent_lineage,
                authority=authority, writer_token=writer_token, external_runner=external_runner))
    return loops


def key(loop):
    return "%s/%s" % (loop.model_id, loop.variant)


def advance_until_submission(loop):
    """Serial steps until done, blocked or ready for the provider phase."""
    while True:
        phase = loop.load_wave_state()["phase"]
        if phase in SUBMISSION_PHASES:
            return READY_TO_SUBMIT
        outcome = loop.step()
        if outcome == orchestrator.OUTCOME_DONE or outcome in orchestrator.BLOCKED_OUTCOMES:
            return outcome


def _submit_one(loop, results, lock):
    try:
        outcome = loop.step()
    except BaseException as error:  # noqa: BLE001 - reported per loop, re-raised later
        outcome = error
    with lock:
        results[key(loop)] = outcome


def drive(loops, parallel=1, log=print, api_retry_delay=600.0, sleep=None,
          external_retry_delay=60.0):
    """Drive every loop to done/blocked. Returns {loop: outcome or exception}.

    Re-queued ONCE per invocation (what an operator re-run would do):
      * blocked_api (RECORDED provider failures) after `api_retry_delay`
        seconds - the unchanged native bounded policy (request_retry_rounds),
        never a resubmission of an ambiguous request (verify_submission_ledger
        refuses those);
      * blocked_external (a tool container failed or wrote nothing) after
        `external_retry_delay` seconds - missing-only: a stored entry,
        including TIMEOUT/TOOL_ERROR, is never re-run."""
    import time

    sleep = sleep or time.sleep
    if len(set(key(loop) for loop in loops)) != len(loops):
        raise RecoveryRefused("two loops share the same model/variant")
    outcomes = OrderedDict()
    active = list(loops)
    requeued = set()
    delays = ((orchestrator.OUTCOME_BLOCKED_API, api_retry_delay,
               "recorded provider failures (native bounded retry)"),
              (orchestrator.OUTCOME_BLOCKED_EXTERNAL, external_retry_delay,
               "an incomplete external tool round (missing-only)"))
    while True:
        if not active:
            for blocked, delay, reason in delays:
                retry = [loop for loop in loops if outcomes.get(key(loop)) == blocked
                         and (blocked, key(loop)) not in requeued]
                if not retry:
                    continue
                log("re-queueing %s after %s, in %.0f s"
                    % (", ".join(key(loop) for loop in retry), reason, delay))
                sleep(delay)
                for loop in retry:
                    requeued.add((blocked, key(loop)))
                    outcomes.pop(key(loop))
                    active.append(loop)
                break
            if not active:
                break
        ready = []
        for loop in list(active):
            if sr.STOP_EVENT.is_set():
                raise sr.StopRequested("stop requested; no further loop is advanced")
            try:
                outcome = advance_until_submission(loop)
            except Exception as error:  # noqa: BLE001 - per-loop failure, reported later
                outcomes[key(loop)] = error
                active.remove(loop)
                continue
            except BaseException:
                # operator abort / interpreter exit: no loop may advance or submit
                sr.STOP_EVENT.set()
                raise
            if outcome == READY_TO_SUBMIT:
                ready.append(loop)
            else:
                outcomes[key(loop)] = outcome
                active.remove(loop)
        if not ready:
            continue
        results = {}
        lock = threading.Lock()
        width = max(1, int(parallel))
        for start in range(0, len(ready), width):
            if sr.STOP_EVENT.is_set():
                raise sr.StopRequested("stop requested; no further submission batch is started")
            batch = ready[start:start + width]
            threads = [threading.Thread(target=_submit_one, args=(loop, results, lock),
                                        name="submit-" + key(loop)) for loop in batch]
            for thread in threads:
                sr.WORKERS.append(thread)
                thread.start()
            try:
                for thread in threads:
                    thread.join()
            except BaseException:
                # stop at the next request boundary, wait for in-flight calls
                sr.STOP_EVENT.set()
                for thread in threads:
                    thread.join()
                raise
            finally:
                for thread in threads:
                    if not thread.is_alive() and thread in sr.WORKERS:
                        sr.WORKERS.remove(thread)
        for loop in ready:
            outcome = results.get(key(loop))
            if isinstance(outcome, BaseException) or outcome in orchestrator.BLOCKED_OUTCOMES \
                    or outcome == orchestrator.OUTCOME_DONE:
                outcomes[key(loop)] = outcome
                active.remove(loop)
    return outcomes


def require_clean_worktree(root=REPO_ROOT):
    status = subprocess.check_output(["git", "-c", "safe.directory=" + root.as_posix(), "-C",
                                      str(root), "status", "--porcelain"], text=True)
    if status.strip():
        raise RecoveryRefused("commit the reviewed implementation before starting/resuming the "
                              "successor (git status is not clean)")
    return subprocess.check_output(["git", "-c", "safe.directory=" + root.as_posix(), "-C",
                                    str(root), "rev-parse", "HEAD"], text=True).strip()


def require_no_tool_containers():
    """Refuse while any successor tool container (an orphan of a crashed
    driver) still exists: it could still be writing successor evidence."""
    result = subprocess.run(["docker", "ps", "-a", "-q", "--filter",
                             "label=%s=%s" % (sr.CONTAINER_LABEL, sl.SUCCESSOR)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RecoveryRefused("docker is not reachable: %s" % result.stderr.strip())
    if result.stdout.strip():
        raise RecoveryRefused("successor tool containers still exist (%s); wait for them or "
                              "remove them explicitly before resuming" % result.stdout.split())
    return True


def status_rows(config, config_path, lineage, parent):
    rows = []
    for loop in build_loops(config, config_path, lineage, parent, ReadOnlyAuthority(config)):
        wave = loop.load_wave_state()
        states = loop.sample_states()
        counts = OrderedDict()
        for row in states.values():
            counts[row.get("status")] = counts.get(row.get("status"), 0) + 1
        rows.append(OrderedDict([("loop", key(loop)), ("iteration", wave["iteration"]),
                                 ("phase", wave["phase"]),
                                 ("seeded_from_predecessor", bool(wave.get("seeded_from_predecessor"))),
                                 ("status_counts", counts)]))
    for model in sl.MODELS:
        for variant in sl.ADOPT_DONE_VARIANTS:
            facts = lineage.handoff(model, variant)
            rows.append(OrderedDict([("loop", "%s/%s" % (model, variant)),
                                     ("iteration", facts["wave_iteration"]),
                                     ("phase", facts["wave_phase"]),
                                     ("adopted_from_predecessor", True)]))
    return rows


def dry_run(config, config_path, lineage, parent, authority=None):
    """Read-only: verifies the handoff and shows the pending external work."""
    report = []
    authority = authority or ReadOnlyAuthority(config)
    for loop in build_loops(config, config_path, lineage, parent, authority):
        wave = loop.load_wave_state()
        entry = OrderedDict([("loop", key(loop)), ("phase", wave["phase"]),
                             ("iteration", wave["iteration"])])
        if wave["phase"] == "analyzed_waiting_external":
            entry["missing_internal_stages"] = loop.missing_internal_stages(int(wave["iteration"]))
            entry["pending_external"] = loop.pending_external(int(wave["iteration"]))
        report.append(entry)
    return report


def main(argv=None):
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=sl.CONFIG_REL)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model-id", action="append", default=None)
    # 1 = native (one request in flight, as recovery_001); >1 runs the provider
    # phase of different loops concurrently (faster; request timing then not
    # comparable to the sequential predecessor waves)
    parser.add_argument("--parallel-submissions", type=int, default=1)
    parser.add_argument("--api-retry-delay-seconds", type=float, default=600.0)
    parser.add_argument("--external-retry-delay-seconds", type=float, default=60.0)
    parser.add_argument("--resolve-ambiguous", default=None,
                        help="MODEL/VARIANT/SAMPLE: count the open lost response as a round")
    parser.add_argument("--resolution-note", default=None)
    args = parser.parse_args(argv)
    if args.model_id is not None and len(set(args.model_id)) != len(args.model_id):
        raise RecoveryRefused("duplicate --model-id: %s" % args.model_id)
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
    from thesis.evaluation import successor_contract as sc
    from thesis.evaluation import verify_successor_run as vs

    print("SUCCESSOR_INVOCATION", json.dumps(OrderedDict([
        ("head", head), ("parallel_submissions", args.parallel_submissions),
        ("api_retry_delay_seconds", args.api_retry_delay_seconds),
        ("models", args.model_id or list(sl.MODELS))])))
    from thesis.evaluation import successor_readiness as srd

    frozen = prc.load_frozen(sc.frozen_path())
    rebuilt = sc.build(config_path, sl.SUCCESSOR)
    if rebuilt["contract_sha256"] != frozen["contract_sha256"]:
        raise RecoveryRefused("successor contract drift before start")
    # the provider endpoints of the successor models must be the ones the
    # predecessor was authorized for (every invocation; hashes only)
    if srd.current_endpoints(config) != srd.predecessor_endpoints(lineage):
        raise RecoveryRefused("provider endpoint of a successor model differs from the "
                              "predecessor authorization")
    if ra.load_authorization(config, sl.SUCCESSOR) is None:
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
                                          requested_model_scope=list(args.model_id or sl.MODELS))
    print("SUCCESSOR_BOOTSTRAP", json.dumps(bootstrap, default=str), "head", head)
    if (bootstrap.get("mode") not in (ra.MODE_FIRST_START, ra.MODE_REHYDRATED, ra.MODE_PROCESS_CACHE)
            or not bootstrap.get("authorization_sha256")):
        raise RecoveryRefused("no successor authorization is installed (%s)" % bootstrap.get("mode"))
    authority = sr.SuccessorAuthority(config, config_path)
    authority.check()
    loops = build_loops(config, config_path, lineage, parent, authority, lock.token,
                        models=args.model_id)
    if args.resolve_ambiguous:
        model, variant, sample = args.resolve_ambiguous.split("/", 2)
        if not args.resolution_note:
            raise RecoveryRefused("--resolve-ambiguous requires --resolution-note")
        target = [loop for loop in loops if loop.model_id == model and loop.variant == variant]
        if len(target) != 1:
            raise RecoveryRefused("unknown loop %s/%s" % (model, variant))
        intent = target[0].resolve_ambiguous(sample, args.resolution_note)
        print("RESOLVED_AMBIGUOUS_SUBMISSION", model, variant, sample, intent)
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
    for model in (args.model_id or sl.MODELS):
        results[model] = vs.verify_model(config, config_path, model, authority=authority)
        print("SUCCESSOR_MODEL_VERIFICATION", model, results[model]["status"])
    print(json.dumps(OrderedDict((m, vs.summary(r)) for m, r in results.items()), indent=2))
    done = all(r["status"] == "PASS" for r in results.values()) and not failures
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
