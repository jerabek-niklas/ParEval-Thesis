"""Productive entrypoint of the phase-2 run full_ext_phase2_001.

    python3 -B -u -m thesis.recovery_successor_005.run [--status | --dry-run]
            [--stages STAGE,...] [--models MODEL,...]

Run from the repository root inside the pareval-thesis container with the
docker socket and PAREVAL_HOST_REPO. Phase 2 makes no provider request: no
package module imports provider code or names a provider chokepoint (import
scan of the preflight); no API key is needed. --status and --dry-run are
read-only: no lock, no authorization, no measurement.

The productive invocation:
  1. refuses a dirty Git worktree, a live tool container of ANY successor run
     and any other successor writer lock (cross-run quiescence);
  2. takes the single phase-2 writer lock (no stale takeover);
  3. requires the phase-2 contract to rebuild to the frozen definition and
     re-hashes every protected byte of the six historical runs;
  4. first start: re-measures the runtime twice against the readiness, then
     the full T0 authorization for all eleven models; afterwards rehydration;
  5. measures, one stage at a time and missing-only, in the contracted order
     static.main -> static.parcoach -> static.llov -> correctness -> dynamic
     -> enhanced (base cells first, then the repair candidates);
  6. verifies every model and persists each verification report.
Re-running the same command resumes (missing-only; nothing is re-measured).

GRACEFUL STOP: SIGTERM (`docker stop -t 7200 <container>`; it reaches only
the driver, never a measurement child) lets the sample in flight finish,
appends nothing half-written and releases the writer lock. Ctrl-C (SIGINT)
is NOT a graceful stop: as in the native runners it aborts immediately
(KeyboardInterrupt) and the interrupted measurement is never written. A hard
kill can leave at most a torn ledger tail (archived on resume) and the
writer lock (removed by the operator after confirming no phase-2 process is
alive).

Provider isolation: every phase-2 entrypoint disables the native config
loader's .env import and removes every configured provider key / endpoint
variable from its environment before the first configuration load
(lineage.isolate_providers), so no key reaches the driver, a measured
program or a tool container, and the T0 evidence never depends on a .env.

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.recovery_lineage import RecoveryRefused  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402

CONTAINER_LABEL = "pareval.successor_run"
TARGET_RETRY_DELAY_SECONDS = 60.0
STOP_EVENT = threading.Event()


def log(message):
    print(message, flush=True)


def stop_requested():
    return STOP_EVENT.is_set()


def install_signal_handlers():
    """SIGTERM only. SIGINT keeps Python's default (KeyboardInterrupt): a
    terminal Ctrl-C also hits the measurement children of the foreground
    process group, so their interrupted results must never be persisted -
    exactly the native behaviour."""
    def handler(signum, _frame):
        if not STOP_EVENT.is_set():
            log("PHASE2_STOP_REQUESTED signal %d: finishing the sample in flight, then stopping" % signum)
        STOP_EVENT.set()

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handler)


# -- effective invocations (exactly the native runners' values; plan NONE) -------

def effective_values(config, stage):
    stages = config.get("stages") or {}
    if stage == "correctness":
        from thesis.evaluation import run_correctness as rc

        own = stages.get("correctness_tests") or {}
        return {
            "effective_run_timeout_seconds": {
                "value": float(own.get("run_timeout_seconds", rc.DEFAULT_RUN_TIMEOUT)),
                "source": "CONFIG" if own.get("run_timeout_seconds") is not None else "DEFAULT"},
            "primary_compiler": {"value": "g++", "source": "DEFAULT"},
        }
    if stage == "dynamic":
        return {
            "primary_compiler": {"value": "g++", "source": "DEFAULT"},
            "tools": {"value": dynamic_tool_scope(config), "source": "CONFIG"},
            "skip_unavailable_tools": {"value": False, "source": "DEFAULT"},
        }
    if stage == "static.main":
        return {
            "primary_compiler": {"value": "g++", "source": "DEFAULT"},
            "tools": {"value": main_static_scope(config), "source": "CLI"},
            "replace_tool_entries": {"value": False, "source": "DEFAULT"},
            "rerun_gaps": {"value": False, "source": "DEFAULT"},
            "replace_legacy_record": {"value": False, "source": "DEFAULT"},
        }
    if stage == "enhanced":
        from thesis.enhanced_tests.specs import stage_settings
        from thesis.evaluation import run_enhanced_tests as ret

        own = stages.get("enhanced_tests") or {}
        settings = stage_settings(config)
        jobs = ret.resolve_jobs(settings, None)
        models = list(settings["execution_models"])
        return {
            "specs": {"value": str(ret.DEFAULT_SPECS_PATH), "source": "DEFAULT"},
            "jobs": {"value": ",".join("%s=%d" % (m, jobs[m]) for m in models), "source": "CONFIG"},
            "effective_enhanced_run_timeout_seconds": {
                "value": float(own.get("run_timeout_seconds", ret.DEFAULT_RUN_TIMEOUT)),
                "source": "CONFIG" if own.get("run_timeout_seconds") is not None else "DEFAULT"},
        }
    raise RecoveryRefused("stage %s is enforced inside its tool container" % stage)


def main_static_scope(config):
    from thesis.recovery_successor_005 import ledger as pg

    return sorted(name for name in pg.static_settings(config) if name not in pl.EXTERNAL_TOOLS)


def dynamic_tool_scope(config):
    from thesis.evaluation import framework
    from thesis.evaluation import run_dynamic_analysis as rda
    from thesis.evaluation.dynamic_tools import register_dynamic_tools

    register_dynamic_tools()
    known = []
    for name in rda.resolve_enabled_tools(config, None):
        try:
            framework.get_tool(name)
            known.append(name)
        except KeyError:
            continue
    return sorted(known)


# -- authority ---------------------------------------------------------------------

class Phase2Authority:
    """The measurement modules' view of the authorization: integrity check
    (contract rebuild == frozen, authorization valid, protected bytes
    stat-guarded) before each target; one stage enforcement per (stage,
    model) per invocation; the binding every record carries."""

    def __init__(self, config, config_path, token, root=REPO_ROOT):
        self.config = config
        self.config_path = str(config_path)
        self.token = token
        self.root = Path(root)
        self._enforced = {}
        self._lock = threading.Lock()

    def check(self):
        from thesis.evaluation import pilot_run_contract as prc
        from thesis.evaluation import run_authorization as ra
        from thesis.evaluation import successor_writer as sw
        from thesis.recovery_successor_005 import contract as pc5

        try:
            sw.require_token(self.root, pl.SUCCESSOR, self.token)
            frozen = prc.load_frozen(pc5.frozen_path(self.root))
            rebuilt = prc.build_contract(self.config_path, pl.PROFILE, pl.SUCCESSOR)
            if rebuilt["contract_sha256"] != frozen["contract_sha256"]:
                raise RecoveryRefused("phase-2 contract drifted from the frozen definition")
            ra.load_and_validate_run_authorization(self.config, pl.SUCCESSOR, config_path=self.config_path,
                                                   profile=pl.PROFILE,
                                                   contract_path=pc5.frozen_path(self.root))
            pl.load(self.root).verify_quick()
        except pl.GlobalStop:
            raise
        except Exception as error:  # noqa: BLE001 - every integrity failure is global
            raise pl.GlobalStop("phase-2 authority check failed: %s: %s" % (type(error).__name__, error))
        return True

    def enforce(self, stage, model):
        from thesis.evaluation import stage_runtime

        key = (stage, model)
        with self._lock:
            if key in self._enforced:
                return self._enforced[key]
        try:
            result = stage_runtime.enforce_stage(
                self.config, pl.SUCCESSOR, stage, effective_values=effective_values(self.config, stage),
                profile=pl.PROFILE, model_scope=[model], writer="phase2_" + stage.replace(".", "_"))
        except Exception as error:  # noqa: BLE001 - a refused/drifted stage stops the run
            raise pl.GlobalStop("stage enforcement %s/%s refused: %s: %s"
                                % (stage, model, type(error).__name__, error))
        if not result.get("enforced"):
            raise pl.GlobalStop("stage enforcement %s/%s is NOT_APPLICABLE: %s"
                                % (stage, model, result.get("reason")))
        with self._lock:
            self._enforced[key] = result
        return result

    def binding(self, stage, model):
        result = self.enforce(stage, model)
        return OrderedDict((k, result.get(k)) for k in ("contract_sha256", "authorization_sha256",
                                                        "stage_runtime_sha256", "invocation_sha256"))


class ReadOnlyAuthority:
    def check(self):
        return True

    def enforce(self, stage, model):
        raise RecoveryRefused("read-only")

    def binding(self, stage, model):
        raise RecoveryRefused("read-only")


# -- quiescence --------------------------------------------------------------------

def require_clean_worktree(root=REPO_ROOT):
    status = subprocess.check_output(["git", "-c", "safe.directory=" + root.as_posix(), "-C",
                                      str(root), "status", "--porcelain"], text=True)
    if status.strip():
        raise RecoveryRefused("commit the reviewed implementation before starting/resuming phase 2 "
                              "(git status is not clean)")
    return subprocess.check_output(["git", "-c", "safe.directory=" + root.as_posix(), "-C",
                                    str(root), "rev-parse", "HEAD"], text=True).strip()


def require_no_tool_containers():
    result = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}", "--filter",
                             "label=%s" % CONTAINER_LABEL], capture_output=True, text=True)
    if result.returncode != 0:
        raise RecoveryRefused("docker is not reachable: %s" % result.stderr.strip())
    labelled = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if labelled:
        raise RecoveryRefused("successor tool containers still exist (%s); remove them explicitly "
                              "after confirming they ended" % labelled)
    return True


def require_no_other_writer(root=REPO_ROOT):
    from thesis.evaluation import successor_writer as sw

    directory = Path(root) / sw.LOCK_DIR
    others = sorted(p.name for p in directory.glob("*.writer.lock")
                    if p.name != "%s.writer.lock" % pl.SUCCESSOR) if directory.is_dir() else []
    if others:
        raise RecoveryRefused("another successor writer lock exists (%s)" % others)
    return True


# -- stage scheduling --------------------------------------------------------------

def stage_targets(table, stage, models=None):
    """Targets of a stage in measurement order (enhanced: every base target
    first, then the candidates; model order = lineage.MODELS)."""
    from thesis.recovery_successor_005 import contract as pc5

    chosen = []
    for target in table.targets:
        if models and target.model_id not in models:
            continue
        kind = "base" if target.is_base else target.variant
        if stage in pc5.STAGE_ASSIGNMENT[kind]:
            chosen.append(target)
    if stage == "enhanced":
        chosen = [t for t in chosen if t.is_base] + [t for t in chosen if not t.is_base]
    return chosen


def _isolated(stage, target, open_items, function):
    """Run one (stage, target); a failure confined to it (TargetFailure or an
    unexpected exception of a native measurement) is logged and recorded as
    open, the other targets continue. Integrity and environment stops, and
    every BaseException (KeyboardInterrupt), propagate."""
    try:
        return function()
    except (pl.GlobalStop, EnvironmentError):
        raise
    except RecoveryRefused as refused:
        raise pl.GlobalStop("%s %s: %s" % (stage, target.target_id, refused))
    except Exception as failure:  # noqa: BLE001 - confined to this target, reported
        log("PHASE2_TARGET_FAILURE %s %s: %s: %s" % (stage, target.target_id, type(failure).__name__, failure))
        traceback.print_exc()
        open_items.append("%s %s" % (stage, target.target_id))
        return Counter()


def run_stage(stage, root, config, table, authority, targets, open_items):
    from thesis.evaluation import successor_writer as sw
    from thesis.recovery_successor_005 import external as ex
    from thesis.recovery_successor_005 import ledger as pg
    from thesis.recovery_successor_005 import measure_enhanced as me
    from thesis.recovery_successor_005 import measure_runtime as mr
    from thesis.recovery_successor_005 import measure_static as ms

    if stage == "enhanced":
        # one call: the gate cache is shared across every target and model
        return me.run_enhanced(root, config, table, authority, targets, log=log, stop=stop_requested)
    counts = Counter()
    if stage in ("static.main", "correctness", "dynamic"):
        for target in targets:
            if stop_requested():
                break
            if stage == "static.main":
                def call(target=target):
                    return ms.run_main(root, config, table, authority, [target], log=log, stop=stop_requested,
                                       open_items=open_items)
            elif stage == "correctness":
                def call(target=target):
                    return mr.run_correctness(root, config, table, authority, [target], log=log,
                                              stop=stop_requested)
            else:
                def call(target=target):
                    return mr.run_dynamic(root, config, table, authority, [target], log=log, stop=stop_requested)
            counts.update(_isolated(stage, target, open_items, call) or Counter())
        return counts
    tool = stage.split(".", 1)[1]
    for target in targets:
        if stop_requested():
            break
        try:
            # a torn tail of ANY static ledger of the target is archived by the
            # lock holder before the merged view is read
            sw.require_token(root, pl.SUCCESSOR, authority.token)
            ex.archive_all_ledgers(root, config, target, log)
            pending = [sid for sid, tools in pg.missing_static(root, config, target).items() if tool in tools]
        except (pl.GlobalStop, EnvironmentError):
            raise
        except RecoveryRefused as refused:
            raise pl.GlobalStop("%s %s planning: %s" % (stage, target.target_id, refused))
        if not pending:
            continue
        authority.check()
        for attempt in (1, 2):
            if attempt == 2:
                time.sleep(TARGET_RETRY_DELAY_SECONDS)
                if stop_requested():
                    open_items.append("%s %s" % (stage, target.target_id))
                    break
            try:
                counts[tool] += ms.run_external(root, config, authority, target, tool, log=log)
                break
            except pl.TargetFailure as failure:
                log("PHASE2_TARGET_FAILURE %s %s attempt %d: %s" % (stage, target.target_id, attempt, failure))
                if attempt == 2 or stop_requested():
                    open_items.append("%s %s" % (stage, target.target_id))
                    break
        authority.check()
    return counts


def stage_history(root, row):
    """Run-level stage invocation history (invoked / completed / stopped /
    failed per stage and invocation): rows of an interrupted invocation stay
    attributable by their created_at_utc within the window."""
    from thesis.evaluation import successor_writer as sw

    path = pl.require_writable(root, "%s/phase2_stage_invocations.jsonl" % pl.RESULTS_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    sw.archive_torn_tail(path)
    sw.durable_append_jsonl(path, row)


# -- read-only modes ---------------------------------------------------------------

def load_definitions(root=REPO_ROOT):
    from thesis.recovery_successor_005 import targets as pt

    lineage = pl.load(root)
    table = pt.load_table(root, lineage.targets_sha256)
    return lineage, table


def read_only_plan(config, table, models=None):
    from thesis.recovery_successor_005 import plan as pp

    return pp.summary(pp.plan(REPO_ROOT, config, table, models=models, strict=False))


def main(argv=None):
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=pl.CONFIG_REL)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stages", default=None,
                        help="comma-separated subset of the contracted measurement order")
    parser.add_argument("--models", default=None, help="comma-separated subset of the eleven models")
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != REPO_ROOT:
        raise RecoveryRefused("run from the repository root (outputs are repo-relative)")
    from thesis.recovery_successor_005 import contract as pc5

    stages = list(pc5.MEASUREMENT_ORDER)
    if args.stages:
        requested = [s.strip() for s in args.stages.split(",") if s.strip()]
        unknown = [s for s in requested if s not in stages]
        if unknown:
            raise RecoveryRefused("unknown stage(s): %s" % unknown)
        stages = [s for s in stages if s in requested]
    models = None
    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        unknown = [m for m in models if m not in pl.MODELS]
        if unknown:
            raise RecoveryRefused("unknown model(s): %s" % unknown)
    config_path = str((REPO_ROOT / args.config).resolve())
    pl.isolate_providers()
    config = load_config(config_path)
    pl.scrub_provider_environment(config)
    lineage, table = load_definitions()
    if args.status or args.dry_run:
        lineage.verify_quick()
        out = read_only_plan(config, table, models)
        if args.status:
            out = OrderedDict([("totals", out["totals"]), ("integrity_findings", out["integrity_findings"])])
        print(json.dumps(out, indent=2))
        return 0

    from thesis.evaluation import successor_writer as sw

    head = require_clean_worktree()
    require_no_tool_containers()
    require_no_other_writer()
    install_signal_handlers()
    lock = sw.WriterLock(REPO_ROOT, pl.SUCCESSOR, "phase2_run")
    lock.acquire()
    os.environ[sw.TOKEN_ENV] = lock.token
    try:
        return _productive(args, config, config_path, lineage, table, lock, head, stages, models)
    finally:
        STOP_EVENT.set()
        lock.release()
        os.environ.pop(sw.TOKEN_ENV, None)


def _productive(args, config, config_path, lineage, table, lock, head, stages, models):
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.evaluation import run_authorization as ra
    from thesis.recovery_successor_005 import contract as pc5
    from thesis.recovery_successor_005 import readiness as prd
    from thesis.recovery_successor_005 import verify as pv

    log("PHASE2_INVOCATION " + json.dumps(OrderedDict([
        ("head", head), ("run_id", pl.SUCCESSOR), ("stages", stages), ("models", models or "ALL"),
        ("targets", table.document["target_count"]), ("sample_totals", table.document["sample_totals"])])))
    frozen = prc.load_frozen(pc5.frozen_path())
    rebuilt = pc5.build(config_path, pl.SUCCESSOR)
    if rebuilt["contract_sha256"] != frozen["contract_sha256"]:
        raise RecoveryRefused("phase-2 contract drift before start")
    started = time.time()
    counts = lineage.verify()
    log("PHASE2_PROTECTED_BYTES_VERIFIED %s (%.0f s)" % (json.dumps(counts), time.time() - started))
    if ra.load_authorization(config, pl.SUCCESSOR) is None:
        readiness = json.loads((pc5.definitions(REPO_ROOT) / "readiness.json").read_text(encoding="utf-8"))
        probes = [prd.probe(config), prd.probe(config)]
        problems = prd.check_runtime(lineage, probes)
        if problems or any(p["sha256"] != readiness["runtime_condition_sha256"] for p in probes):
            raise RecoveryRefused("first-start runtime gate failed: %s" % "; ".join(problems))
        log("PHASE2_FIRST_START_RUNTIME_GATE PASS %s" % probes[0]["sha256"])
    bootstrap = ra.bootstrap_provider_run(config, config_path, pl.PROFILE, pl.SUCCESSOR,
                                          contract_path=pc5.frozen_path(), stage="phase2_bootstrap",
                                          requested_model_scope=list(pl.MODELS))
    log("PHASE2_BOOTSTRAP %s head %s" % (json.dumps(bootstrap, default=str), head))
    if (bootstrap.get("mode") not in (ra.MODE_FIRST_START, ra.MODE_REHYDRATED, ra.MODE_PROCESS_CACHE)
            or not bootstrap.get("authorization_sha256")):
        raise RecoveryRefused("no phase-2 authorization is installed (%s)" % bootstrap.get("mode"))
    # the measurement path reads only the PERSISTED authorization (stage
    # enforcement, per-target checks): the in-process provider chokepoint
    # context is removed, so any provider call in this process is refused
    ra.clear_context()
    authority = Phase2Authority(config, config_path, lock.token)
    authority.check()
    open_items = []
    outcome = "COMPLETE"
    invocation_id = "%s-%d" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid())

    def history(stage, status, started, counts=None, error=None):
        stage_history(REPO_ROOT, OrderedDict([
            ("schema_version", "phase2_stage_invocation.v1"), ("run_id", pl.SUCCESSOR),
            ("invocation_id", invocation_id), ("head", head), ("stage", stage), ("status", status),
            ("started_at_utc", started), ("logged_at_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            ("models", models or "ALL"), ("counts", dict(counts or {})), ("error", error),
            ("open_items", list(open_items))]))

    stage = None
    stage_started = None
    try:
        for stage in stages:
            if stop_requested():
                outcome = "STOPPED"
                break
            targets = stage_targets(table, stage, models)
            log("PHASE2_STAGE %s START targets=%d" % (stage, len(targets)))
            stage_started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            history(stage, "invoked", stage_started)
            clock = time.time()
            counts = run_stage(stage, REPO_ROOT, config, table, authority, targets, open_items)
            status = "stopped" if stop_requested() else "completed"
            history(stage, status, stage_started, counts)
            log("PHASE2_STAGE %s END %s %s (%.0f s)" % (stage, status.upper(), json.dumps(dict(counts or {})),
                                                        time.time() - clock))
        if stop_requested() and outcome == "COMPLETE":
            outcome = "STOPPED"
    except pl.GlobalStop as stop:
        STOP_EVENT.set()
        log("PHASE2_GLOBAL_STOP %s" % stop)
        traceback.print_exc()
        if stage_started:
            history(stage, "failed", stage_started, error="GlobalStop: %s" % stop)
        return 2
    except EnvironmentError as error:
        STOP_EVENT.set()
        log("PHASE2_ENVIRONMENT_STOP %s" % error)
        if stage_started:
            history(stage, "failed", stage_started, error="EnvironmentError: %s" % error)
        return 2
    if outcome == "STOPPED":
        log("PHASE2_STOPPED gracefully; resume with the same command")
        return 3
    results = pv.verify_all(REPO_ROOT, config, table, pl.load(REPO_ROOT), models=models, write=True)
    log("PHASE2_VERIFICATION " + json.dumps(results, default=str))
    complete = isinstance(results, dict) and all(
        (r or {}).get("model_complete") for r in (results.get("models") or {}).values())
    log("PHASE2_SUMMARY " + json.dumps(OrderedDict([("open_items", open_items),
                                                    ("models_complete", complete)])))
    return 0 if complete and not open_items else 1


if __name__ == "__main__":
    raise SystemExit(main())
