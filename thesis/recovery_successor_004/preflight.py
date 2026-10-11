"""Non-productive preflight gate of the successor run full_ext_recovery_004.

    python3 -B -m thesis.recovery_successor_004.preflight [--runtime] [--containers]
    python3 -m thesis.recovery_successor_004.preflight --container-check --tool llov|parcoach

Read-only: no lock, no authorization, no manifest, no provider request, no
analysis. The successor must be FRESH before and after. Checks:

  * successor lineage (deep: recovery_001 bytes, membership, bindings, the
    retirement record, the protected sibling successors 002/003, every
    origin fact incl. the absence proof re-derived), parent lineage binding;
  * successor proof (deep: Git blobs of the recovery_001 commit), readiness
    binding, contract rebuild == frozen contract;
  * the 1,980-cell base population and the protected pilot/full_ext history;
  * methodology replay gate: for every loop recovery_001 ran natively, the
    iteration-0 decisions and the iteration-1 requests derived through the
    004 routing equal recovery_001's bytes (the fresh path IS the native one);
  * dry run: all 15 loops start fresh, the parent evidence covers every
    iteration-0 decision (no internal stage, no external tool pending), and
    the iteration-1 requests build deterministically;
  * no tool container and no writer lock of ANY successor run exist;
  * the experiment-wide repair-loop census (read-only);
  * --runtime: a fresh runtime probe equals the readiness (main container);
  * --containers: the binding chain validates inside the pinned LLOV
    (Python 3.8) and PARCOACH (Python 3.11) images, tool available.

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.recovery_successor_004 import lineage as sl  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402

SCHEMA = "successor_preflight.v1"


class Gate:
    def __init__(self):
        self.checks = []

    def run(self, name, function, *args, **kwargs):
        try:
            detail = function(*args, **kwargs)
            self.checks.append(OrderedDict([("check", name), ("status", "PASS"), ("detail", detail)]))
            return detail
        except Exception as error:  # noqa: BLE001 - every failure is reported
            self.checks.append(OrderedDict([("check", name), ("status", "FAIL"),
                                            ("detail", "%s: %s" % (type(error).__name__, error))]))
            return None

    @property
    def status(self):
        return "PASS" if self.checks and all(c["status"] == "PASS" for c in self.checks) else "REFUSE"


def _json(root, relative):
    return json.loads(checked_path(root, relative).read_text(encoding="utf-8"),
                      object_pairs_hook=OrderedDict)


def binding_chain(root, config, config_path):
    """Lineage -> proof -> readiness -> frozen contract provenance -> config
    pin (git-free; the part every tool container can verify)."""
    from thesis.evaluation import condition_hashing as ch
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.recovery_successor_004 import contract as sc
    from thesis.recovery_successor_004 import equivalence as se
    from thesis.recovery_successor_004 import readiness as sr

    lineage = sl.load(root)
    lineage.verify_quick()
    proof = _json(root, sl.DEFINITIONS_REL + "/equivalence.json")
    se.validate(proof, root, lineage, config)
    readiness = _json(root, sl.DEFINITIONS_REL + "/readiness.json")
    sr.validate(readiness, lineage, proof)
    frozen = prc.load_frozen(sc.frozen_path(root))
    provenance = frozen.get("successor_provenance") or {}
    if (frozen.get("run_id") != sl.SUCCESSOR or frozen.get("status") != prc.STATUS_READY
            or provenance.get("lineage_sha256") != lineage.sha256
            or provenance.get("equivalence_sha256") != proof["proof_sha256"]
            or provenance.get("readiness_lf_sha256")
            != ch.lf_normalized_sha256(checked_path(root, sl.DEFINITIONS_REL + "/readiness.json"))
            or provenance.get("config_lf_sha256") != ch.lf_normalized_sha256(Path(config_path))):
        raise RecoveryRefused("frozen successor contract is not bound to the current definitions")
    return OrderedDict([("contract_sha256", frozen["contract_sha256"]),
                        ("lineage_sha256", lineage.sha256), ("proof_sha256", proof["proof_sha256"]),
                        ("readiness_sha256", readiness["readiness_sha256"])])


def container_check(root, config_path, tool):
    from thesis.config.load_config import load_config
    from thesis.recovery_successor_004 import external as sx

    config = load_config(config_path)
    chain = binding_chain(root, config, config_path)
    instance, known, _expected = sx.resolve_tool(config, tool)
    # everything the productive container path imports and reads before T0
    from thesis.evaluation import effective_invocation, manifest_fragments, run_authorization  # noqa: F401
    from thesis.evaluation import run_manifest, stage_runtime, static_provenance  # noqa: F401

    state = stage_runtime.enforcement_state(config, sl.SUCCESSOR)
    waves = OrderedDict()
    for model in sl.MODELS:
        for variant in ("static_feedback", "combined_feedback"):
            try:
                sx.wave_in_flight(root, config, model, variant, 1)
                waves["%s/%s" % (model, variant)] = "IN_FLIGHT"
            except RecoveryRefused:
                waves["%s/%s" % (model, variant)] = "FRESH_NO_WAVE"
    if any(value != "FRESH_NO_WAVE" for value in waves.values()):
        raise RecoveryRefused("a successor wave exists before T0: %s" % dict(waves))
    return OrderedDict([("status", "PASS"), ("python", platform.python_version()), ("tool", tool),
                        ("tool_available", instance.is_available()), ("binding", chain),
                        ("enforcement_before_t0", bool(state.get("enforced"))),
                        ("iteration_targets", "FRESH_NO_WAVE")])


def origin_models(lineage):
    """Models recovery_001 ran natively (repair directories in its snapshot)."""
    models = set()
    prefix = "thesis/results/intermediate/%s/" % sl.PREDECESSOR
    for relative in lineage.snapshot.files:
        if relative.startswith(prefix) and "/repair/" in relative and relative.endswith("/state.jsonl"):
            models.add(relative[len(prefix):].split("/")[0])
    return sorted(models)


def replay_gate(config, config_path, lineage, parent):
    """Methodology equivalence: recovery_001's native iteration-0 decisions,
    iteration-1 requests and iteration-1/2 decisions re-derive through the 004
    fresh routing (the productive compute_decisions path). Refuses on any
    mismatch; returns counts and a digest of everything compared."""
    from thesis.evaluation.condition_hashing import canonical_sha256
    from thesis.recovery_successor_004 import routing as sr
    from thesis.recovery_successor_004 import run as rs

    profile = config["profiles"][sl.PROFILE]
    by_id = {m["id"]: m for m in config["models"]}
    rows = OrderedDict()
    digests = OrderedDict()
    totals = OrderedDict([("decisions", 0), ("requests", 0), ("later", 0), ("later_prior_lc", 0)])
    models = origin_models(lineage)
    if not models or set(models) & set(sl.MODELS):
        raise RecoveryRefused("unexpected recovery_001 model set: %s" % models)
    for model in models:
        for variant in sl.VARIANTS:
            loop = sr.SuccessorRepairLoop(config, config_path, sl.PROFILE, profile, by_id[model],
                                          variant, "g++", lineage=lineage, parent_lineage=parent,
                                          authority=rs.NullAuthority(), replay=True)
            result = loop.replay_origin(lineage.view)
            if (result["decision_mismatches"] or result["request_mismatches"] or not result["unusable_match"]
                    or result["later_decision_mismatches"]):
                raise RecoveryRefused("%s/%s does not reproduce recovery_001: %s"
                                      % (model, variant, json.dumps(result)[:400]))
            name = "%s/%s" % (model, variant)
            rows[name] = [result["decisions"], result["requests"], result["later_decisions"]]
            digests[name] = result["digest"]
            totals["decisions"] += result["decisions"]
            totals["requests"] += result["requests"]
            totals["later"] += result["later_decisions"]
            totals["later_prior_lc"] += result["later_decisions_with_prior_low_confidence"]
    return OrderedDict([("origin_models", models), ("decisions_reproduced", totals["decisions"]),
                        ("iteration1_requests_rebuilt", totals["requests"]),
                        ("iteration_1_2_decisions_reproduced", totals["later"]),
                        ("iteration_1_2_decisions_with_prior_low_confidence", totals["later_prior_lc"]),
                        ("coverage", "iteration-0 decisions and iteration-1 requests of every recovery_001 "
                                     "loop; iteration-1/2 decisions only where recovery_001 decided them "
                                     "natively (its test_feedback loops); the static/combined iteration>=1 "
                                     "path is covered by the unchanged native source pins"),
                        ("mismatches", 0),
                        ("loops", rows), ("digest", canonical_sha256(digests))])


def dry_run_gate(config, config_path, lineage, parent):
    from thesis.recovery_successor_004 import run as rs

    report = rs.dry_run(config, config_path, lineage, parent)
    totals = OrderedDict()
    for entry in report:
        model, variant = entry["loop"].split("/")
        facts = lineage.origin(model, variant)
        active = (entry.get("iteration0_decisions") or {}).get("active", 0)
        if (entry["phase"] != "start" or entry["iteration"] != 0
                or entry.get("iteration0_missing_internal") or entry.get("iteration0_pending_external")
                or entry.get("iteration1_requests") != active
                or sum((entry.get("iteration0_decisions") or {}).values()) != facts["parent_assembled"]):
            raise RecoveryRefused("unexpected fresh state for %s: %s" % (entry["loop"], entry))
        totals[variant] = totals.get(variant, 0) + active
    totals["total"] = sum(totals.values())
    return OrderedDict([("iteration1_requests_by_variant", totals),
                        ("loops", OrderedDict((e["loop"], [e["lane"], e["iteration0_decisions"],
                                                           e["iteration1_requests"]]) for e in report))])


def quiescence(root):
    from thesis.recovery_successor_004 import run as rs
    from thesis.evaluation import successor_writer as sw

    rs.require_no_tool_containers()
    directory = Path(root) / sw.LOCK_DIR
    locks = sorted(p.name for p in directory.glob("*.writer.lock")) if directory.is_dir() else []
    if locks:
        raise RecoveryRefused("successor writer locks exist: %s" % locks)
    return {"successor_tool_containers": 0, "successor_writer_locks": 0}


def git_state(root):
    git = ["git", "-c", "safe.directory=" + Path(root).as_posix(), "-C", str(root)]
    head = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(git + ["status", "--porcelain"], text=True)
    return OrderedDict([("head", head), ("clean", not status.strip()),
                        ("uncommitted_paths", len([l for l in status.splitlines() if l.strip()]))])


def run_containers(config, root):
    """--container-check inside the pinned tool images (production mounts)."""
    import os

    from thesis.evaluation.check_static_repair_readiness import parse_docker_template
    from thesis.repair import orchestrator

    settings = orchestrator.repair_settings(config)
    results = OrderedDict()
    for tool in sl.EXTERNAL_TOOLS:
        template = settings["external_tool_commands"][tool]
        image, interpreter = parse_docker_template(template)
        marker = " %s %s " % (image, interpreter)
        head = template[:template.index(marker)].format(host_repo=orchestrator.host_repo_path(settings),
                                                        repo=str(orchestrator.REPO_ROOT))
        command = "%s %s %s -B -m thesis.recovery_successor_004.preflight --container-check --tool %s" % (
            head, image, interpreter, tool)
        completed = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=1800,
                                   env=dict(os.environ))
        lines = [l for l in completed.stdout.splitlines() if l.strip()]
        try:
            document = json.loads("\n".join(lines[lines.index("{"):])) if "{" in lines else None
        except ValueError:
            document = None
        if completed.returncode != 0 or not document or document.get("status") != "PASS":
            raise RecoveryRefused("%s container check failed (exit %s): %s %s"
                                  % (tool, completed.returncode, completed.stdout[-1500:],
                                     completed.stderr[-1500:]))
        results[tool] = OrderedDict([("image", image), ("interpreter", interpreter),
                                     ("python", document["python"]),
                                     ("tool_available", document["tool_available"]),
                                     ("contract_sha256", document["binding"]["contract_sha256"])])
    return results


def preflight(root, config, config_path, runtime=False, containers=False):
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.recovery_successor_004 import census
    from thesis.recovery_successor_004 import contract as sc
    from thesis.recovery_successor_004 import equivalence as se
    from thesis.recovery_successor_004 import freeze as sf
    from thesis.recovery_successor_004 import verify as vs
    from thesis.recovery_successor_004 import run as rs

    gate = Gate()

    def fresh():
        state = sf.successor_state(root, config)
        if state:
            raise RecoveryRefused("successor state exists: %s" % state[:5])
        return "FRESH"

    gate.run("successor FRESH before", fresh)
    lineage = gate.run("successor lineage loads", sl.load, root)
    parents = gate.run("parent lineage bound to the successor lineage", rs.load_lineages, root)
    if lineage is None or parents is None:
        return gate
    lineage, parent = parents
    gate.run("recovery_001 bytes, bindings, retirement, siblings 002/003, origin facts (deep)",
             lambda: lineage.verify(config, deep=True) and {
                 "recovery_001_files": len(lineage.snapshot.files),
                 "snapshot_sha256": lineage.document["predecessor_snapshot"]["snapshot_sha256"],
                 "siblings": lineage.verify_siblings(),
                 "lineage_sha256": lineage.sha256})
    proof = _json(root, sl.DEFINITIONS_REL + "/equivalence.json")
    gate.run("successor proof (deep, recovery_001 commit blobs)",
             lambda: se.validate(proof, root, lineage, config, deep=True) and {
                 "proof_sha256": proof["proof_sha256"],
                 "unchanged_source_pins": len(proof["unchanged_source_pins"]),
                 "routing_changes": list(proof["routing_changes"]),
                 "test_evidence": [(e["label"], e.get("tests_run")) for e in proof["test_evidence"]]})
    gate.run("binding chain lineage -> proof -> readiness -> frozen contract -> config",
             binding_chain, root, config, config_path)

    def contract():
        frozen = prc.load_frozen(sc.frozen_path(root))
        rebuilt = sc.build(config_path, sl.SUCCESSOR, root=root, writer_check=False)
        if rebuilt["contract_sha256"] != frozen["contract_sha256"] or prc.contract_diff(frozen, rebuilt):
            raise RecoveryRefused("rebuilt successor contract differs from the frozen definition")
        return {"contract_sha256": frozen["contract_sha256"], "status": frozen["status"],
                "model_ids": frozen["model_ids"]}

    gate.run("successor contract rebuilds to the frozen definition", contract)
    report = vs.Report("preflight")
    vs.population(lineage, report)
    vs.immutability(config, lineage, report, deep=True)
    for check in report.checks:
        gate.checks.append(OrderedDict([("check", check["check"]), ("status", check["status"]),
                                        ("detail", check["detail"])]))
    gate.run("methodology replay: recovery_001 iteration-0 decisions and iteration-1 requests rebuild "
             "through the 004 fresh routing", replay_gate, config, config_path, lineage, parent)
    gate.run("dry run: 15 fresh loops, parent evidence complete, iteration-1 requests deterministic",
             dry_run_gate, config, config_path, lineage, parent)
    gate.run("origin summary", lambda: OrderedDict(
        (loop, OrderedDict([("mode", facts["mode"]), ("parent_cells", facts["parent_cells"]),
                            ("parent_assembled", facts["parent_assembled"]),
                            ("parent_external_missing", facts["parent_external_missing"])]))
        for loop, facts in lineage.document["origin"].items()))
    gate.run("no tool container and no writer lock of any successor run", quiescence, root)
    def census_before_t0():
        result = census.census(root)
        summary = census.summary(result)
        mine = set("%s/%s" % (m, v) for m in sl.MODELS for v in sl.VARIANTS)
        problems = []
        if len(result["loops"]) != 66 or summary["base_cells"]["total"] != 1980:
            problems.append("66 loops / 1,980 base cells expected")
        for loop in result["loops"]:
            name = "%s/%s" % (loop["model"], loop["variant"])
            expected = "NOT_STARTED" if loop["block"] == "full_ext" and name in mine else "TERMINAL"
            if loop["state"] != expected:
                problems.append("%s/%s is %s, expected %s" % (loop["block"], name, loop["state"], expected))
        if len(summary["repair_conditions"]) != 1:
            problems.append("more than one repair condition: %s" % summary["repair_conditions"])
        if problems:
            raise RecoveryRefused("experiment census before T0: %s" % "; ".join(problems[:10]))
        return summary

    gate.run("experiment census: 51/66 terminal, exactly the 15 loops of 004 not started, 1,980 cells",
             census_before_t0)
    gate.run("git state", git_state, root)
    if runtime:
        from thesis.recovery_successor_004 import readiness as sr

        def runtime_matches():
            readiness = _json(root, sl.DEFINITIONS_REL + "/readiness.json")
            probe = sr.probe(config)
            problems, _keys, _endpoints = sr.check_runtime(config, lineage, [probe, probe])
            if problems or probe["sha256"] != readiness["runtime_condition_sha256"]:
                raise RecoveryRefused("runtime differs from the readiness: %s" % problems)
            return {"runtime_condition_sha256": probe["sha256"], "vm_mmap_rnd_bits": probe["vm_mmap_rnd_bits"],
                    "provider_endpoints_equal_origin": True}

        gate.run("fresh runtime equals the readiness (images, tools, TSan, endpoints, keys)",
                 runtime_matches)
    if containers:
        gate.run("binding chain inside the pinned tool images", run_containers, config, root)
    gate.run("successor FRESH after (nothing written)", fresh)
    return gate


def main(argv=None):
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=sl.CONFIG_REL)
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--containers", action="store_true")
    parser.add_argument("--container-check", action="store_true")
    parser.add_argument("--tool", choices=sl.EXTERNAL_TOOLS)
    args = parser.parse_args(argv)
    root = REPO_ROOT
    config_path = (root / args.config).resolve()
    if args.container_check:
        try:
            result = container_check(root, config_path, args.tool)
        except Exception as error:  # noqa: BLE001
            result = OrderedDict([("status", "REFUSE"), ("python", platform.python_version()),
                                  ("error", "%s: %s" % (type(error).__name__, error))])
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 1
    config = load_config(config_path)
    gate = preflight(root, config, config_path, args.runtime, args.containers)
    result = OrderedDict([
        ("schema_version", SCHEMA), ("status", gate.status), ("run_id", sl.SUCCESSOR),
        ("python", platform.python_version()),
        ("authorization_created", False), ("provider_calls_made", False),
        ("measurements_started", False), ("checks", gate.checks)])
    print(json.dumps(result, indent=2, default=str))
    return 0 if gate.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
