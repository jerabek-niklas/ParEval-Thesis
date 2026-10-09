"""Non-productive preflight gate of the successor run full_ext_recovery_002.

    python3 -B -m thesis.evaluation.successor_preflight [--runtime] [--containers]
    python3 -m thesis.evaluation.successor_preflight --container-check --tool llov|parcoach

Read-only: no lock, no authorization, no manifest, no provider request, no
analysis. The successor must be FRESH before and after. Checks:

  * predecessor lineage (deep: bytes, membership, bindings, every handoff
    fact and the retirement record re-derived), parent lineage binding;
  * successor proof (deep: Git blobs of the predecessor commit), readiness
    binding, contract rebuild == frozen contract;
  * the 1,980-cell base population and the protected pilot/full_ext history;
  * replay gate: every predecessor request ledger of both models rebuilds
    byte-identically through the successor read routing;
  * dry run: exactly the inherited LLOV gaps are pending, nothing else;
  * no successor tool container and no writer lock exist;
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

from thesis.evaluation import successor_lineage as sl  # noqa: E402
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
    from thesis.evaluation import successor_contract as sc
    from thesis.evaluation import successor_equivalence as se
    from thesis.evaluation import successor_readiness as sr

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
    from thesis.evaluation import successor_external as sx

    config = load_config(config_path)
    chain = binding_chain(root, config, config_path)
    instance, known, _expected = sx.resolve_tool(config, tool)
    # everything the productive container path imports and reads before T0
    from thesis.evaluation import effective_invocation, manifest_fragments, run_authorization  # noqa: F401
    from thesis.evaluation import run_manifest, stage_runtime, static_provenance  # noqa: F401

    state = stage_runtime.enforcement_state(config, sl.SUCCESSOR)
    waves = OrderedDict(("%s/%s" % (model, variant),
                         sx.wave_in_flight(root, config, model, variant, 1))
                        for model in sl.MODELS for variant in sl.CONTINUE_VARIANTS)
    return OrderedDict([("status", "PASS"), ("python", platform.python_version()), ("tool", tool),
                        ("tool_available", instance.is_available()), ("binding", chain),
                        ("enforcement_before_t0", bool(state.get("enforced"))),
                        ("iteration1_targets", waves)])


def replay_gate(config, config_path, lineage, parent):
    from thesis.repair import run_successor as rs
    from thesis.repair import successor_routing as sr

    profile = config["profiles"][sl.PROFILE]
    by_id = {m["id"]: m for m in config["models"]}
    rows = OrderedDict()
    total = 0
    for model in sl.MODELS:
        for variant in sl.VARIANTS:
            loop = sr.SuccessorRepairLoop(config, config_path, sl.PROFILE, profile, by_id[model],
                                          variant, "g++", lineage=lineage, parent_lineage=parent,
                                          authority=rs.NullAuthority(), replay=True)
            for iteration in lineage.handoff(model, variant)["iterations"]:
                result = loop.replay_requests(int(iteration))
                if result["mismatches"]:
                    raise RecoveryRefused("%s/%s iteration %s: %d request(s) do not rebuild"
                                          % (model, variant, iteration, len(result["mismatches"])))
                rows["%s/%s/iter%s" % (model, variant, iteration)] = result["requests"]
                total += result["requests"]
    return OrderedDict([("requests_rebuilt", total), ("mismatches", 0), ("ledgers", rows)])


def dry_run_gate(config, config_path, lineage, parent):
    from thesis.repair import run_successor as rs

    report = rs.dry_run(config, config_path, lineage, parent)
    for entry in report:
        model, variant = entry["loop"].split("/")
        facts = lineage.handoff(model, variant)["iteration_1"]
        expected = [["llov", facts["external_missing"]["llov"]]] if facts["external_missing"]["llov"] else []
        pending = [list(p) for p in entry.get("pending_external") or []]
        if (entry["phase"] != "analyzed_waiting_external" or entry["iteration"] != 1
                or entry.get("missing_internal_stages") or pending != expected):
            raise RecoveryRefused("unexpected continuation state for %s: %s" % (entry["loop"], entry))
    return report


def no_tool_containers():
    from thesis.repair import run_successor as rs

    return rs.require_no_tool_containers()


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
        command = "%s %s %s -B -m thesis.evaluation.successor_preflight --container-check --tool %s" % (
            head, image, interpreter, tool)
        completed = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=900,
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
    from thesis.evaluation import successor_contract as sc
    from thesis.evaluation import successor_equivalence as se
    from thesis.evaluation import successor_freeze as sf
    from thesis.evaluation import verify_successor_run as vs
    from thesis.repair import run_successor as rs

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
    gate.run("predecessor bytes, membership, bindings, handoff, retirement (deep)",
             lambda: lineage.verify(config, deep=True) and {
                 "files": len(lineage.snapshot.files),
                 "snapshot_sha256": lineage.document["predecessor_snapshot"]["snapshot_sha256"],
                 "lineage_sha256": lineage.sha256})
    proof = _json(root, sl.DEFINITIONS_REL + "/equivalence.json")
    gate.run("successor proof (deep, predecessor commit blobs)",
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
    gate.run("replay gate: predecessor requests rebuild through the successor routing",
             replay_gate, config, config_path, lineage, parent)
    gate.run("dry run: only the inherited LLOV gaps are pending", dry_run_gate, config, config_path,
             lineage, parent)
    gate.run("handoff summary", lambda: OrderedDict(
        (key, OrderedDict([("mode", facts["mode"]), ("phase", facts["wave_phase"]),
                           ("active", facts["active_samples"]),
                           ("llov_missing", (facts.get("iteration_1") or {}).get("external_missing",
                                                                                 {}).get("llov"))]))
        for key, facts in lineage.document["handoff"].items()))
    gate.run("no successor tool container exists", no_tool_containers)
    gate.run("git state", git_state, root)
    if runtime:
        from thesis.evaluation import successor_readiness as sr

        def runtime_matches():
            readiness = _json(root, sl.DEFINITIONS_REL + "/readiness.json")
            probe = sr.probe(config)
            problems, _keys, _endpoints = sr.check_runtime(config, lineage, [probe, probe])
            if problems or probe["sha256"] != readiness["runtime_condition_sha256"]:
                raise RecoveryRefused("runtime differs from the readiness: %s" % problems)
            return {"runtime_condition_sha256": probe["sha256"], "vm_mmap_rnd_bits": probe["vm_mmap_rnd_bits"],
                    "provider_endpoints_equal_predecessor": True}

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
