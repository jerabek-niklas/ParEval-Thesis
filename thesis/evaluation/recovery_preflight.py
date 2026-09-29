"""Read-only recovery gate. Never imports the productive start entrypoint."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from thesis.evaluation import recovery_context as rc
from thesis.evaluation.recovery_lineage import RecoveryRefused, RECOVERY


def runtime_probe(config):
    from thesis.evaluation.run_authorization import measure_fresh_runtime
    from thesis.evaluation.dynamic_tools import TsanTool
    from thesis.evaluation import stage_runtime as sr
    from thesis.evaluation.probe_runtime_identity import ROLE_TOOLS
    result = measure_fresh_runtime(config)
    for domain, environment in result["environments"].items():
        if environment.get("inspect_error"):
            result["problems"].append(domain + ": " + str(environment["inspect_error"]))
        if not environment.get("image_id") or not environment.get("rootfs_layers_sha256"):
            result["problems"].append(domain + ": incomplete immutable image identity")
        for identity in ROLE_TOOLS.get(domain, ()):
            if not environment.get("tool_identities", {}).get(identity):
                result["problems"].append(domain + ": missing " + identity)
        for evidence in sr.REQUIRED_EVIDENCE.get(domain, ()):
            if not environment.get("evidence", {}).get(evidence):
                result["problems"].append(domain + ": missing " + evidence)
    bits = Path("/proc/sys/vm/mmap_rnd_bits")
    result["vm_mmap_rnd_bits"] = bits.read_text().strip() if bits.is_file() else None
    result["tsan_error"] = TsanTool().preflight()
    result["tsan_preflight_pass"] = result["tsan_error"] is None and result["vm_mmap_rnd_bits"] == "28"
    result["api_keys"] = {m["api_key_env"]: "SET" if os.environ.get(m["api_key_env"]) else "MISSING"
                          for m in config["models"] if m.get("enabled") and m.get("api_key_env")}
    result["free_disk_gb"] = round(shutil.disk_usage(rc.ROOT).free / 1024**3, 2)
    result["host_repo_path"] = os.environ.get("PAREVAL_HOST_REPO")
    result["host_repo_path_valid"] = result["host_repo_path"] == "C:/Users/jerab/Desktop/ParEval-thesis" and not result["problems"]
    return result


def verify(config, config_path, runtime, allow_uncommitted=False):
    from thesis.evaluation import recovery_contract, pilot_run_contract, run_freshness
    from thesis.evaluation.verify_parent_base_evidence import read_json
    from thesis.evaluation import composite_study_v2
    git = ["git", "-c", "safe.directory=" + rc.ROOT.as_posix(), "-C", str(rc.ROOT)]
    head = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(git + ["status", "--porcelain"], text=True)
    if status and not allow_uncommitted:
        raise RecoveryRefused("commit the reviewed implementation before productive start")
    contract = recovery_contract.build(config_path, RECOVERY)
    frozen = pilot_run_contract.load_frozen(rc.DEFINITIONS / "contract.json")
    if contract != frozen:
        raise RecoveryRefused("rebuilt recovery contract differs from frozen definition")
    if run_freshness.inspect_run_freshness(config, RECOVERY)["status"] != "FRESH":
        raise RecoveryRefused("recovery already has productive state")
    for area in ("raw_dir", "intermediate_dir"):
        for path in Path(config["outputs"][area]).glob(RECOVERY + "*"):
            if path.is_dir() and any(p.is_file() for p in path.rglob("*")):
                raise RecoveryRefused("productive recovery artifact exists before first T0")
    readiness = read_json(rc.DEFINITIONS / "readiness.json")
    if (runtime["problems"] or runtime["sha256"] != readiness["runtime_condition_sha256"]
            or not runtime["tsan_preflight_pass"] or not runtime["host_repo_path_valid"]
            or any(v != "SET" for v in runtime["api_keys"].values())
            or runtime["free_disk_gb"] < readiness["minimum_free_disk_gb"]):
        raise RecoveryRefused("runtime/API/disk recovery prerequisites fail")
    study = read_json(rc.DEFINITIONS / "composite_v2.json")
    composite_study_v2.verify(rc.ROOT, study, config, config_path)
    return dict(status="PASS", scope="UNCOMMITTED_IMPLEMENTATION_GATE" if status else "POST_COMMIT_START_GATE",
                head=head, worktree_clean=not bool(status), authorization_created=False,
                provider_calls_made=False, measurements_started=False,
                contract_sha256=contract["contract_sha256"], runtime_sha256=runtime["sha256"])


def main():
    from thesis.config.load_config import load_config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="thesis/config/recovery.yaml")
    parser.add_argument("--runtime-only", action="store_true")
    parser.add_argument("--allow-uncommitted", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    runtime = runtime_probe(config)
    if args.runtime_only:
        print(json.dumps(runtime, indent=2))
        return 0 if not runtime["problems"] and runtime["tsan_preflight_pass"] else 1
    try:
        result = verify(config, args.config, runtime, args.allow_uncommitted)
    except Exception as error:
        result = dict(status="REFUSE", error=str(error), runtime=runtime)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
