"""Productive recovery entrypoint. Never invoked by implementation tests.

Re-running continues the same state machines; pending provider batches cause
an ordinary return. No generation stage or parent backfill can be scheduled.
"""
from __future__ import annotations
import argparse
import subprocess
from pathlib import Path
from types import SimpleNamespace


def main():
    from thesis.repair import run_repair, run_backfill
    from thesis.evaluation import recovery_context as rc, recovery_contract
    from thesis.repair.backfill_authority import backfill_lock
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="thesis/config/recovery.yaml")
    args = parser.parse_args()
    config_path = str(Path(args.config).resolve())
    contract = recovery_contract.build(config_path, rc.RECOVERY)
    from thesis.config.load_config import load_config
    from thesis.evaluation import run_authorization
    config = load_config(config_path, validate_keys=True)
    if subprocess.check_output(["git", "-c", "safe.directory=" + rc.ROOT.as_posix(),
                                "-C", str(rc.ROOT), "status", "--porcelain"], text=True).strip():
        raise ValueError("commit the reviewed implementation before starting/resuming recovery")
    if run_authorization.load_authorization(config, rc.RECOVERY) is None:
        from thesis.evaluation import recovery_preflight
        recovery_preflight.verify(config, config_path, recovery_preflight.runtime_probe(config))
    options = SimpleNamespace(config=config_path, profile="recovery", model_id=None,
                              variant=None, primary_compiler="g++", max_wave=None,
                              status=False, dry_run=False, poll=False)
    loops = run_repair.build_loops(options)
    if len(loops) != 33:
        raise ValueError("recovery requires all 33 loops")
    # This is the FIRST productive authorization of a fresh recovery. It
    # is intentionally not reachable from any read-only preflight helper.
    run_repair.bootstrap_run_authorization(options, loops)
    for loop in loops:
        loop.run()
    config = loops[0].config
    run_backfill.check_toolchain(
        current_path=run_backfill.TOOLCHAIN_VERSIONS_FILE,
        stored_path=Path(config["outputs"]["intermediate_dir"]) / rc.RECOVERY / "toolchain-versions.txt",
        strict=True)
    for model in contract["model_ids"]:
        if not all(loop.load_wave_state()["phase"] == "done" for loop in loops if loop.model_id == model):
            print(model + ": repair pending; enhanced remains held out")
            continue
        rc.require_terminal(config, model)
        executor = run_backfill.StageExecutor(config, config_path, "recovery", "g++")
        with backfill_lock(config, rc.RECOVERY, model):
            run_backfill.backfill_model(config, config_path, "recovery", rc.RECOVERY,
                                        model, executor, None, False)
    if all(loop.load_wave_state()["phase"] == "done" for loop in loops):
        from thesis.evaluation.verify_recovery_run import verify
        result = verify(config, config_path)
        print("RECOVERY_POST_RUN_VERIFICATION", result["status"], result["counts"])
        return 0 if result["status"] == "PASS" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
