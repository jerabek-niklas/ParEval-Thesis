"""Manifest concurrency tests (pilot_002 pre-run wave, GATE 2).

Empirical, with REAL processes on a REAL directory:

  1. legacy shared-manifest read-modify-write under concurrency -> counts
     lost updates (the measurement behind MANIFEST_SHARED_WRITE_CAPABILITY)
  2. per-writer fragments under the same load -> zero lost registrations
  3. same model X then Y -> HARD FAIL; concurrent X/Y -> exactly one wins,
     the other is refused, the stored fragment is never a mix
  4. crash safety: killed writers leave no half-written JSON; temp
     leftovers are ignored
  5. deterministic merge; missing expected / unexpected fragments reported
  6. idempotent duplicate registration; legacy run untouched

Run (temp dir):            python thesis/evaluation/test_manifest_fragments.py
Run on a real mount:       python thesis/evaluation/test_manifest_fragments.py --target-dir <dir>
                           (a scratch run id is created under <dir> and removed afterwards)
Writes a JSON report with --report <path>.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import manifest_fragments as mf  # noqa: E402
from thesis.evaluation import run_manifest  # noqa: E402

FAILURES = []
REPORT = OrderedDict()


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# worker modes (run in child processes)
# ---------------------------------------------------------------------------

def worker_legacy_rmw(path: Path, worker: int, n: int) -> None:
    """The legacy pattern: read the shared JSON, add one key, atomic replace.
    Exactly what register_model_execution / _register_condition did."""
    for i in range(n):
        key = "w%d_k%d" % (worker, i)
        for _ in range(50):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                break
            except (json.JSONDecodeError, OSError, FileNotFoundError):
                time.sleep(0.001)
        else:
            data = {}
        data.setdefault("keys", {})[key] = worker
        atomic_io.atomic_write_json(path, data)


def worker_fragments(intermediate: Path, run_id: str, worker: int, n: int) -> None:
    for i in range(n):
        owner = "w%d_k%d" % (worker, i)
        mf.register_fragment(intermediate, run_id, "enhanced", owner,
                             {"model_id": owner, "value": worker}, writer="worker%d" % worker)


def worker_conflict(intermediate: Path, run_id: str, fingerprint: str) -> None:
    try:
        mf.register_fragment(intermediate, run_id, "assembly", "model_x",
                             {"assembly_set_sha256": fingerprint}, fingerprint=fingerprint)
        print("REGISTERED %s" % fingerprint)
    except mf.FragmentConflict:
        print("REFUSED %s" % fingerprint)


def worker_killable(intermediate: Path, run_id: str, worker: int) -> None:
    payload = {"blob": "x" * 200000}
    i = 0
    while True:
        mf.register_fragment(intermediate, run_id, "enhanced", "w%d_k%d" % (worker, i),
                             dict(payload, i=i), writer="killable", history=False)
        i += 1


def spawn(args):
    return subprocess.Popen([sys.executable, __file__, "--worker"] + [str(a) for a in args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            cwd=str(REPO_ROOT))


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_legacy_lost_updates(target: Path, workers: int, per_worker: int) -> int:
    print("== 1. legacy shared-manifest read-modify-write under concurrency ==")
    path = target / "legacy_shared.json"
    atomic_io.atomic_write_json(path, {"keys": {}})
    started = time.perf_counter()
    procs = [spawn(["legacy", path, w, per_worker]) for w in range(workers)]
    for p in procs:
        p.communicate()
    elapsed = time.perf_counter() - started
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = workers * per_worker
    lost = expected - len(data["keys"])
    print("  legacy RMW: %d writers x %d keys -> %d stored, %d LOST (%.2fs)"
          % (workers, per_worker, len(data["keys"]), lost, elapsed))
    REPORT["legacy_shared_rmw"] = OrderedDict([
        ("writers", workers), ("per_worker", per_worker), ("expected", expected),
        ("stored", len(data["keys"])), ("lost_updates", lost), ("elapsed_seconds", round(elapsed, 3))])
    check("legacy shared RMW measured (lost updates counted, not assumed)", True)
    return lost


def test_fragments_no_loss(target: Path, workers: int, per_worker: int) -> None:
    print("== 2. per-writer fragments under the same load ==")
    run_id = "probe_fragments"
    started = time.perf_counter()
    procs = [spawn(["fragments", target, run_id, w, per_worker]) for w in range(workers)]
    outs = [p.communicate() for p in procs]
    elapsed = time.perf_counter() - started
    errors = [e for _, e in outs if e.strip()]
    merged = mf.merge_fragments(target, run_id)
    stored = len(merged.get("model_execution_fingerprints") or {})
    expected = workers * per_worker
    print("  fragments: %d writers x %d registrations -> %d stored, %d lost (%.2fs)"
          % (workers, per_worker, stored, expected - stored, elapsed))
    REPORT["fragments_concurrent"] = OrderedDict([
        ("writers", workers), ("per_worker", per_worker), ("expected", expected),
        ("stored", stored), ("lost_updates", expected - stored),
        ("worker_errors", len(errors)), ("elapsed_seconds", round(elapsed, 3))])
    check("no lost registration with fragments", stored == expected and not errors)
    for e in errors[:2]:
        print("   worker stderr:", e[-300:])
    snapshot = mf.write_snapshot(target, run_id)
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    check("snapshot run_manifest.json is the complete merged view",
          len(data.get("model_execution_fingerprints") or {}) == expected)
    check("merge is deterministic", mf.merge_is_deterministic(target, run_id))
    check("every fragment file parses as JSON",
          all(isinstance(f, dict) for _, f in mf.load_fragments(target, run_id)))


def test_same_key_conflict(target: Path) -> None:
    print("== 3. same key X then Y -> HARD FAIL; concurrent X/Y -> exactly one wins ==")
    run_id = "probe_conflict"
    x, y = "a" * 64, "b" * 64
    mf.register_fragment(target, run_id, "assembly", "model_x", {"assembly_set_sha256": x}, fingerprint=x)
    mf.register_fragment(target, run_id, "assembly", "model_x", {"assembly_set_sha256": x}, fingerprint=x)
    check("identical re-registration is idempotent", True)
    try:
        mf.register_fragment(target, run_id, "assembly", "model_x", {"assembly_set_sha256": y}, fingerprint=y)
        check("same key, different fingerprint -> FragmentConflict", False)
    except mf.FragmentConflict:
        check("same key, different fingerprint -> FragmentConflict", True)
    stored = json.loads(mf.fragment_path(target, run_id, "assembly", "model_x").read_text(encoding="utf-8"))
    check("the first registration stays (never last-writer-wins)", stored["fingerprint_sha256"] == x)

    run_id = "probe_conflict_concurrent"
    wins = OrderedDict([("registered", 0), ("refused", 0)])
    for _round in range(5):
        shutil.rmtree(target / run_id, ignore_errors=True)
        procs = [spawn(["conflict", target, run_id, x]), spawn(["conflict", target, run_id, y])]
        outs = [p.communicate()[0] for p in procs]
        text = "".join(outs)
        wins["registered"] += text.count("REGISTERED")
        wins["refused"] += text.count("REFUSED")
        stored = json.loads(mf.fragment_path(target, run_id, "assembly", "model_x").read_text(encoding="utf-8"))
        if stored["fingerprint_sha256"] not in (x, y):
            check("stored fragment is one of the two, never a mix", False)
        if stored["fingerprint_sha256"] != stored["content"]["assembly_set_sha256"]:
            check("stored fragment content matches its fingerprint", False)
    REPORT["concurrent_conflict_rounds"] = wins
    check("concurrent X/Y: exactly one registered and one refused per round (5 rounds)",
          wins["registered"] == 5 and wins["refused"] == 5)


def test_crash_safety(target: Path) -> None:
    print("== 4. crash safety ==")
    run_id = "probe_crash"
    procs = [spawn(["killable", target, run_id, w]) for w in range(3)]
    time.sleep(1.5)
    for p in procs:
        p.kill()
    for p in procs:
        p.communicate()
    fragments = mf.load_fragments(target, run_id)
    directory = mf.fragments_dir(target, run_id)
    all_files = [p for p in directory.iterdir() if p.is_file()]
    temps = [p for p in all_files if ".tmp-" in p.name]
    locks = [p for p in directory.iterdir() if p.is_dir() and p.name.endswith(".lock")]
    print("  stale lock dirs left by killed writers: %d (taken over after %.0fs)"
          % (len(locks), mf.LOCK_STALE_SECONDS))
    REPORT["crash_kill_stale_locks"] = len(locks)
    parsed = 0
    for p in all_files:
        if ".tmp-" in p.name:
            continue
        json.loads(p.read_text(encoding="utf-8"))
        parsed += 1
    print("  killed 3 writers after 1.5s: %d complete fragments, %d temp leftovers" % (len(fragments), len(temps)))
    REPORT["crash_kill"] = OrderedDict([("complete_fragments", len(fragments)), ("temp_leftovers", len(temps))])
    check("every surviving fragment is complete JSON (no half-written file)", parsed == len(fragments))
    # a garbage temp file (a writer died mid-write) is ignored by the reader
    (directory / "enhanced.garbage.json.tmp-999").write_bytes(b'{"half": ')
    check("temp leftovers are ignored by the reader",
          len(mf.load_fragments(target, run_id)) == len(fragments))
    removed = atomic_io.remove_stale_temp_files(directory)
    check("temp leftovers can be cleaned", removed >= 1)


def test_temp_name_uniqueness(target: Path) -> None:
    """Two writers in SEPARATE CONTAINERS on one mounted tree are both PID 1.
    A temp name keyed on the PID alone would make them collide on the same
    target, and one would replace a file the other had already renamed away."""
    print("== 0. temp-file naming across writers with identical PIDs ==")
    import threading

    directory = target / "_temp_probe"
    directory.mkdir(parents=True, exist_ok=True)
    real_getpid = os.getpid
    names = set()
    errors = []
    lock = threading.Lock()

    real_tmp_path = atomic_io._tmp_path
    writes = {"n": 0}

    def recording_tmp_path(target):
        tmp = real_tmp_path(target)
        with lock:
            names.add(tmp.name)
            writes["n"] += 1
        return tmp

    atomic_io._tmp_path = recording_tmp_path

    def writer(index):
        try:
            for i in range(40):
                atomic_io.atomic_write_json(directory / "run_manifest.json",
                                            {"writer": index, "i": i})
        except Exception as exc:  # noqa: BLE001
            errors.append("%s: %s" % (type(exc).__name__, exc))

    atomic_io.os.getpid = lambda: 1  # every container's python is PID 1
    try:
        threads = [threading.Thread(target=writer, args=(w,)) for w in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        atomic_io.os.getpid = real_getpid
        atomic_io._tmp_path = real_tmp_path
    leftovers = [p for p in directory.iterdir() if atomic_io.TEMP_MARKER in p.name]
    payload = json.loads((directory / "run_manifest.json").read_text(encoding="utf-8"))
    print("  8 writers x 40 writes with PID pinned to 1: %d write(s), %d distinct temp "
          "names, %d error(s)" % (writes["n"], len(names), len(errors)))
    REPORT["temp_name_uniqueness"] = OrderedDict([
        ("writes", writes["n"]), ("distinct_temp_names", len(names)), ("errors", len(errors))])
    check("writers with the SAME pid never share a temp name",
          len(names) == writes["n"] == 8 * 40)
    check("no writer fails when they collide on one target", not errors)
    for e in errors[:2]:
        print("   error:", e)
    check("the surviving target is one complete document",
          set(payload) == {"writer", "i"} and not leftovers)
    shutil.rmtree(directory, ignore_errors=True)


def test_merge_semantics(target: Path) -> None:
    print("== 5/6. merge semantics, expected/unexpected, legacy ==")
    run_id = "probe_merge"
    cfg = {"outputs": {"intermediate_dir": target.as_posix(), "raw_dir": (target / "raw").as_posix()},
           "stages": {"x": 1}}
    run_manifest.ensure_run_manifest(cfg, run_id, stage="generation", profile="p")
    check("a new run is fragment-based", run_manifest.manifest_architecture(cfg, run_id) == "PER_WRITER_FRAGMENTS")
    run_manifest.register_assembly_set(cfg, run_id, "m1", 3, "c" * 64, "d" * 64, {"assembled": 3})
    run_manifest.register_model_execution(cfg, run_id, "m1", "e" * 64)
    run_manifest.register_static_condition(cfg, run_id, "f" * 64, {"tools": ["x"]})
    run_manifest.register_repair_condition(cfg, run_id, "9" * 64, {"policy": "p"})
    run_manifest.register_runtime_evidence(cfg, run_id, {"main_runtime_sha256": "1" * 64})
    run_manifest.register_contract(cfg, run_id, "2" * 64, {"run_id": run_id})
    merged = run_manifest.load_manifest(cfg, run_id)
    check("merged view keeps the legacy manifest shape",
          merged["run_id"] == run_id and merged["resolved_config"]["stages"] == {"x": 1}
          and merged["created_by_stage"] == "generation"
          and merged["model_execution_fingerprints"] == {"m1": "e" * 64}
          and merged["static_analysis_condition_sha256"] == "f" * 64
          and merged["repair_condition_sha256"] == "9" * 64
          and merged["assembly_model_sets"]["m1"]["assembly_set_sha256"] == "c" * 64
          and merged["assembly_condition_sha256"] == "d" * 64
          and merged["contract_sha256"] == "2" * 64
          and merged["runtime_evidence"]["main_runtime_sha256"] == "1" * 64)
    expected = [mf.fragment_name("global"), mf.fragment_name("assembly", "m1"),
                mf.fragment_name("assembly", "m2")]
    view = mf.merge_fragments(target, run_id, expected=expected)
    check("missing expected fragment -> incomplete, named",
          view["complete"] is False and view["missing_expected_fragments"] == [mf.fragment_name("assembly", "m2")])
    atomic_io.atomic_write_json(mf.fragments_dir(target, run_id) / "mystery.thing.json",
                                {"run_id": run_id, "kind": "mystery", "fingerprint_sha256": "0"})
    view = mf.merge_fragments(target, run_id)
    check("unexpected fragment reported, not absorbed", view["unexpected_fragments"] == ["mystery.thing.json"])
    try:
        run_manifest.register_assembly_set(cfg, run_id, "m1", 3, "x" * 64, "d" * 64)
        check("same model, different assembly set -> AssemblySetMismatch", False)
    except run_manifest.AssemblySetMismatch:
        check("same model, different assembly set -> AssemblySetMismatch", True)
    try:
        run_manifest.register_model_execution(cfg, run_id, "m1", "y" * 64)
        check("same model, different execution fingerprint -> mismatch", False)
    except run_manifest.EnhancedExecutionConditionMismatch:
        check("same model, different execution fingerprint -> mismatch", True)
    run_manifest.register_model_execution(cfg, run_id, "m2", "e" * 64)
    check("a second model registers additively",
          set(run_manifest.load_manifest(cfg, run_id)["model_execution_fingerprints"]) == {"m1", "m2"})
    # drift recorded once per distinct deviation, without RMW
    cfg2 = {"outputs": cfg["outputs"], "stages": {"x": 2}}
    run_manifest.ensure_run_manifest(cfg2, run_id, stage="static_analysis", profile="p")
    run_manifest.ensure_run_manifest(cfg2, run_id, stage="enhanced_tests", profile="p")
    drift = run_manifest.load_manifest(cfg, run_id)["config_drift"]
    check("config drift recorded once for one deviation, frozen snapshot untouched",
          len(drift) == 1 and drift[0]["changed_keys"] == ["stages.x"]
          and run_manifest.load_manifest(cfg, run_id)["resolved_config"]["stages"] == {"x": 1})
    history = list((mf.fragments_dir(target, run_id) / mf.HISTORY_DIR_NAME).iterdir())
    check("registration history exists and is outside every condition",
          len(history) >= 6 and "history" not in json.dumps(view["fragment_set_sha256"]))
    # legacy run: shared manifest without fragments is left alone
    legacy_run = "probe_legacy"
    legacy_path = run_manifest.manifest_path(cfg, legacy_run)
    atomic_io.atomic_write_json(legacy_path, {"run_id": legacy_run, "resolved_config": {}, "config_drift": []})
    before = legacy_path.read_bytes()
    run_manifest.register_assembly_set(cfg, legacy_run, "m1", 1, "c" * 64, "d" * 64)
    check("legacy shared-manifest run: classified LEGACY, not migrated, assembly registration is a no-op",
          run_manifest.manifest_architecture(cfg, legacy_run) == "LEGACY_SHARED_MANIFEST"
          and legacy_path.read_bytes() == before
          and not mf.fragments_dir(target, legacy_run).exists())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--target-dir", default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--per-worker", type=int, default=25)
    parser.add_argument("--report", default=None)
    parser.add_argument("rest", nargs="*")
    args = parser.parse_args()

    if args.worker:
        mode = args.rest[0]
        if mode == "legacy":
            worker_legacy_rmw(Path(args.rest[1]), int(args.rest[2]), int(args.rest[3]))
        elif mode == "fragments":
            worker_fragments(Path(args.rest[1]), args.rest[2], int(args.rest[3]), int(args.rest[4]))
        elif mode == "conflict":
            worker_conflict(Path(args.rest[1]), args.rest[2], args.rest[3])
        elif mode == "killable":
            worker_killable(Path(args.rest[1]), args.rest[2], int(args.rest[3]))
        return

    if args.target_dir:
        base = Path(args.target_dir)
        base.mkdir(parents=True, exist_ok=True)
        target = base / ("_manifest_concurrency_probe_%d" % os.getpid())
        target.mkdir()
        cleanup = True
    else:
        tmp = tempfile.mkdtemp()
        target = Path(tmp)
        cleanup = True

    REPORT["environment"] = OrderedDict([
        ("target_dir", str(target)), ("platform", sys.platform),
        ("python_version", platform.python_version()),
        ("workers", args.workers), ("per_worker", args.per_worker),
    ])
    try:
        test_temp_name_uniqueness(target)
        lost = test_legacy_lost_updates(target, args.workers, args.per_worker)
        test_fragments_no_loss(target, args.workers, args.per_worker)
        test_same_key_conflict(target)
        test_crash_safety(target)
        test_merge_semantics(target)
    finally:
        if cleanup:
            shutil.rmtree(target, ignore_errors=True)

    capability = "SAFE_SHARED_ATOMIC" if lost == 0 else "UNSAFE_OR_UNPROVEN"
    REPORT["legacy_shared_write_capability_measured"] = capability
    REPORT["selected_architecture"] = "PER_WRITER_FRAGMENTS"
    REPORT["failures"] = list(FAILURES)
    print()
    print("LEGACY_SHARED_MANIFEST_LOST_UPDATES = %d" % lost)
    print("MANIFEST_SHARED_WRITE_CAPABILITY (legacy RMW on this mount) = %s" % capability)
    print("SELECTED_MANIFEST_ARCHITECTURE = PER_WRITER_FRAGMENTS")
    if args.report:
        atomic_io.atomic_write_json(Path(args.report), REPORT)
        print("report:", args.report)
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("All manifest fragment test groups passed.")


if __name__ == "__main__":
    main()
