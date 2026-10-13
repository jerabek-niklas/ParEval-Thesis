"""Non-productive preflight gate of the phase-2 run full_ext_phase2_001.

    python3 -B -m thesis.recovery_successor_005.preflight [--runtime] [--containers]
    python3 -m thesis.recovery_successor_005.preflight --container-check --tool llov|parcoach

Read-only: no lock, no authorization, no manifest, no provider request, no
measurement. The phase-2 run must be FRESH before and after. Checks:

  * phase-2 lineage: every protected byte and the membership of the six
    historical runs (pilot_002, full_ext_001, full_ext_recovery_001..004),
    the frozen historical definitions, the chain of custody against the
    inventories earlier definitions recorded;
  * target table: frozen == re-derived from the repository (77 targets,
    every candidate bound to its loop's request and its source hash);
  * proof (deep: Git blobs of the origin commit), readiness, binding chain,
    contract rebuild == frozen contract;
  * the missing-only plan equals the contracted work exactly, and no stage
    outside the phase-2 assignment has a gap;
  * the 1,980-cell base population, the 66/66 terminal repair loops, the
    complete pilot reference;
  * no package module can reach a provider (import scan);
  * no tool container and no writer lock of ANY successor run exist;
  * --runtime: a fresh runtime probe equals the readiness;
  * --containers: the binding chain validates inside the pinned LLOV
    (Python 3.8) and PARCOACH (Python 3.11) images, tool available.

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import ast
import json
import platform
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402

SCHEMA = "phase2_preflight.v1"
PACKAGE_DIR = "thesis/recovery_successor_005"
# provider code: the SDK packages, the generation / batch modules and the
# repair orchestrator (its wave runner reaches batch_api) - none may be
# imported by a phase-2 module
FORBIDDEN_IMPORTS = ("thesis.generation.generate", "thesis.generation.batch_api",
                     "thesis.repair.orchestrator", "thesis.repair.run_repair", "openai", "anthropic",
                     "google.genai", "google.generativeai", "dotenv")
FORBIDDEN_NAMES = ("require_provider_call", "call_with_retries", "submit_batch", "poll_batch",
                   "_submit_batch", "_poll_batch", "bootstrap_provider_run")
# the one sanctioned use: the driver's T0 bootstrap (run.py), followed by
# run_authorization.clear_context()
FORBIDDEN_NAME_ALLOWED = {("run.py", "bootstrap_provider_run")}
# the exact work the frozen design assigns to phase 2 (real repository)
EXPECTED_PLAN = OrderedDict([
    ("static.main", OrderedDict([("samples", 320), ("items", 1280), ("applicable.clang_tidy", 320),
                                 ("applicable.cppcheck", 320), ("applicable.gcc_analyzer", 320),
                                 ("applicable.infer", 166)])),
    ("static.parcoach", OrderedDict([("samples", 320), ("items", 320), ("applicable.parcoach", 134)])),
    ("static.llov", OrderedDict([("samples", 320), ("items", 320), ("applicable.llov", 154)])),
    ("correctness", OrderedDict([("samples", 1249), ("items", 1249)])),
    ("dynamic", OrderedDict([("samples", 1249), ("items", 1249)])),
    ("enhanced", OrderedDict([("samples", 4517), ("items", 90340), ("expected_samples", 4517),
                              ("expected_pairs", 90340)])),
])


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
    return json.loads(checked_path(root, relative).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def binding_chain(root, config, config_path, lineage=None):
    """Lineage -> targets -> proof -> readiness -> frozen contract provenance
    -> config pin (git-free; verifiable inside every tool container; never
    re-hashes the protected trees - the driver does that)."""
    from thesis.evaluation import condition_hashing as ch
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.recovery_successor_005 import contract as pc5
    from thesis.recovery_successor_005 import equivalence as pe
    from thesis.recovery_successor_005 import readiness as prd
    from thesis.recovery_successor_005 import targets as pt

    lineage = lineage or pl.load(root)
    table = pt.load_table(root, lineage.targets_sha256)
    proof = _json(root, pl.DEFINITIONS_REL + "/equivalence.json")
    pe.validate(proof, root, lineage, config)
    readiness = _json(root, pl.DEFINITIONS_REL + "/readiness.json")
    prd.validate(readiness, lineage, proof)
    frozen = prc.load_frozen(pc5.frozen_path(root))
    provenance = frozen.get("phase2_provenance") or {}
    if (frozen.get("run_id") != pl.SUCCESSOR or frozen.get("status") != prc.STATUS_READY
            or provenance.get("lineage_sha256") != lineage.sha256
            or provenance.get("targets_sha256") != table.sha256
            or provenance.get("equivalence_sha256") != proof["proof_sha256"]
            or provenance.get("readiness_lf_sha256")
            != ch.lf_normalized_sha256(checked_path(root, pl.DEFINITIONS_REL + "/readiness.json"))
            or provenance.get("config_lf_sha256") != ch.lf_normalized_sha256(Path(config_path))
            or provenance.get("provider_calls") != "NONE"):
        raise RecoveryRefused("frozen phase-2 contract is not bound to the current definitions")
    return OrderedDict([("contract_sha256", frozen["contract_sha256"]), ("lineage_sha256", lineage.sha256),
                        ("targets_sha256", table.sha256), ("proof_sha256", proof["proof_sha256"]),
                        ("readiness_sha256", readiness["readiness_sha256"])])


def container_check(root, config_path, tool):
    from thesis.config.load_config import load_config
    from thesis.evaluation import framework
    from thesis.evaluation.run_static_analysis import resolve_enabled_tools
    from thesis.evaluation.tools import register_default_tools

    pl.isolate_providers()
    config = load_config(config_path)
    pl.scrub_provider_environment(config)
    chain = binding_chain(root, config, config_path)
    register_default_tools(primary_compiler="g++", config=config)
    if tool not in resolve_enabled_tools(config, [tool], "static_analysis"):
        raise RecoveryRefused("tool %s is not enabled" % tool)
    instance = framework.get_tool(tool)
    # everything the productive container path imports before writing
    from thesis.evaluation import effective_invocation, manifest_fragments, run_authorization  # noqa: F401
    from thesis.evaluation import run_manifest, stage_runtime, static_provenance  # noqa: F401
    from thesis.evaluation import successor_supplement, successor_writer  # noqa: F401
    from thesis.recovery_successor_005 import external, ledger, targets  # noqa: F401

    state = stage_runtime.enforcement_state(config, pl.SUCCESSOR)
    if state.get("enforced"):
        raise RecoveryRefused("the phase-2 run is already contracted (T0 happened)")
    return OrderedDict([("status", "PASS"), ("python", platform.python_version()), ("tool", tool),
                        ("tool_available", instance.is_available()), ("binding", chain),
                        ("enforcement_before_t0", False)])


def provider_isolation(root):
    """No package module imports provider code or names a provider chokepoint."""
    offending = []
    for path in sorted((Path(root) / PACKAGE_DIR).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + ["%s.%s" % (node.module, a.name) for a in node.names]
            for name in names:
                if any(name == f or name.startswith(f + ".") for f in FORBIDDEN_IMPORTS):
                    offending.append("%s imports %s" % (path.name, name))
            if isinstance(node, (ast.Name, ast.Attribute)):
                identifier = node.id if isinstance(node, ast.Name) else node.attr
                if (identifier in FORBIDDEN_NAMES and path.name not in ("preflight.py", "test_authority.py")
                        and (path.name, identifier) not in FORBIDDEN_NAME_ALLOWED):
                    offending.append("%s references %s" % (path.name, identifier))
    if offending:
        raise RecoveryRefused("phase-2 code can reach a provider: %s" % offending[:5])
    return {"modules_scanned": len(list((Path(root) / PACKAGE_DIR).glob("*.py"))), "provider_paths": 0}


def plan_matches(root, config, table):
    from thesis.recovery_successor_005 import plan as pp

    result = pp.plan(root, config, table)
    if result["integrity_findings"]:
        raise RecoveryRefused("integrity findings: %s" % result["integrity_findings"][:5])
    totals = result["totals"]
    problems = []
    for stage, expected in EXPECTED_PLAN.items():
        actual = totals.get(stage) or {}
        for key, value in expected.items():
            if actual.get(key) != value:
                problems.append("%s.%s = %s, expected %s" % (stage, key, actual.get(key), value))
    if problems:
        raise RecoveryRefused("the plan differs from the contracted phase-2 work: %s" % problems)
    return totals


def population(root):
    from thesis.recovery_successor_005 import verify as pv

    result = pv.population(root)
    if result.get("status") != "PASS":
        raise RecoveryRefused("population check failed: %s" % result.get("detail"))
    return result["detail"]


def pilot_reference(root, config):
    """pilot_002 is complete for every model: base cells and every repair
    candidate carry static (applicable tools), correctness, dynamic and the
    exact enhanced (sample, spec) set - verified read-only."""
    from thesis.recovery_successor_005 import ledger as pg
    from thesis.recovery_successor_005 import verify as pv

    deep = {"llm_specs": pg.load_frozen_specs(root), "spec_cache": {}}
    samples = OrderedDict()
    failing = []
    rows = 0
    for model in pl.MODELS:
        report = pv.Report(model)
        counts = pv._block_counts()
        pv.verify_pilot(root, config, model, report, counts, deep)
        failing.extend("%s %s" % (model, check) for check in report.failing())
        samples[model] = counts["samples"]
        rows += counts["enhanced"]["rows"]
    if failing:
        raise RecoveryRefused("the pilot reference is incomplete: %s" % failing[:5])
    return OrderedDict([("samples", sum(samples.values())), ("enhanced_rows", rows),
                        ("samples_per_model", samples)])


def quiescence(root):
    from thesis.recovery_successor_005 import run as pr
    from thesis.evaluation import successor_writer as sw

    pr.require_no_tool_containers()
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
    from thesis.recovery_successor_005 import measure_static as ms

    settings = (config.get("stages") or {}).get("repair") or {}
    results = OrderedDict()
    for tool in pl.EXTERNAL_TOOLS:
        template = settings["external_tool_commands"][tool]
        image, interpreter = parse_docker_template(template)
        marker = " %s %s " % (image, interpreter)
        head = template[:template.index(marker)].format(host_repo=ms.host_repo_path(settings),
                                                        repo=str(REPO_ROOT))
        command = "%s %s %s -B -m thesis.recovery_successor_005.preflight --container-check --tool %s" % (
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
                                  % (tool, completed.returncode, completed.stdout[-1500:], completed.stderr[-1500:]))
        results[tool] = OrderedDict([("image", image), ("interpreter", interpreter),
                                     ("python", document["python"]), ("tool_available", document["tool_available"]),
                                     ("contract_sha256", document["binding"]["contract_sha256"])])
    return results


def preflight(root, config, config_path, runtime=False, containers=False):
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.recovery_successor_004 import census
    from thesis.recovery_successor_005 import contract as pc5
    from thesis.recovery_successor_005 import equivalence as pe
    from thesis.recovery_successor_005 import freeze as pf
    from thesis.recovery_successor_005 import targets as pt

    gate = Gate()

    def fresh():
        state = pf.phase2_state(root, config)
        if state:
            raise RecoveryRefused("phase-2 state exists: %s" % state[:5])
        return "FRESH"

    gate.run("phase-2 run FRESH before", fresh)
    lineage = gate.run("phase-2 lineage loads (self-hash)", pl.load, root)
    if lineage is None:
        return gate
    gate.run("protected bytes + membership of pilot_002, full_ext_001, full_ext_recovery_001..004 and "
             "the historical definitions unchanged", lineage.verify)
    gate.run("chain of custody: inventories equal protected_history, the 004 snapshot and the 002/003 "
             "sibling inventories", lambda: pl.custody(root, lineage.document["protected"]) and {
                 "full_ext_recovery_004_lineage_sha256":
                     lineage.document["custody"]["full_ext_recovery_004_lineage_sha256"]})

    def targets_reproduce():
        frozen = pt.load_table(root, lineage.targets_sha256)
        rebuilt = pt.build_table(root)
        if rebuilt["table_sha256"] != frozen.sha256:
            raise RecoveryRefused("the target table re-derived from the repository differs from the frozen one")
        return OrderedDict([("table_sha256", frozen.sha256), ("target_count", frozen.document["target_count"]),
                            ("sample_totals", frozen.document["sample_totals"])])

    gate.run("target table re-derives from the repository (77 targets, requests == candidates, source hashes)",
             targets_reproduce)
    proof = _json(root, pl.DEFINITIONS_REL + "/equivalence.json")
    gate.run("phase-2 proof (deep, origin commit blobs; measurement equivalence covered)",
             lambda: pe.validate(proof, root, lineage, config, deep=True) and {
                 "proof_sha256": proof["proof_sha256"],
                 "unchanged_source_pins": len(proof["unchanged_source_pins"]),
                 "routing_changes": list(proof["routing_changes"]),
                 "measurement_equivalence": list(proof["measurement_equivalence"]),
                 "test_evidence": [(e["label"], e.get("tests_run")) for e in proof["test_evidence"]]})
    gate.run("binding chain lineage -> targets -> proof -> readiness -> frozen contract -> config",
             binding_chain, root, config, config_path, lineage)

    def contract():
        frozen = prc.load_frozen(pc5.frozen_path(root))
        rebuilt = pc5.build(config_path, pl.SUCCESSOR, root=root, writer_check=False)
        if rebuilt["contract_sha256"] != frozen["contract_sha256"] or prc.contract_diff(frozen, rebuilt):
            raise RecoveryRefused("rebuilt phase-2 contract differs from the frozen definition")
        return {"contract_sha256": frozen["contract_sha256"], "status": frozen["status"],
                "model_ids": frozen["model_ids"]}

    gate.run("phase-2 contract rebuilds to the frozen definition", contract)
    table = pt.load_table(root, lineage.targets_sha256)
    gate.run("missing-only plan == contracted phase-2 work (correctness 1,249, dynamic 1,249, static "
             "1,920 rows / 1,414 applicable, enhanced 4,517 samples / 90,340 pairs), no other gap",
             plan_matches, root, config, table)

    def census_terminal():
        result = census.census(root, list(pl.MODELS))
        summary = census.summary(result)
        problems = []
        if summary["total_repair_loops_done"] != "66/66" or summary["base_cells"]["total"] != 1980:
            problems.append("66/66 terminal loops and 1,980 base cells expected: %s / %s"
                            % (summary["total_repair_loops_done"], summary["base_cells"]["total"]))
        if len(summary["repair_conditions"]) != 1:
            problems.append("more than one repair condition: %s" % summary["repair_conditions"])
        if problems:
            raise RecoveryRefused("; ".join(problems))
        return summary

    gate.run("experiment census: 66/66 repair loops terminal, 1,980 base cells, one repair condition",
             census_terminal)
    gate.run("1,980-cell composite population", population, root)
    gate.run("pilot reference complete (static, correctness, dynamic, exact enhanced pairs)",
             pilot_reference, root, config)
    gate.run("no phase-2 module can reach a provider", provider_isolation, root)

    def environment_clean():
        present = pl.provider_environment(config)
        if present:
            raise RecoveryRefused("provider variables present in the phase-2 process: %s" % present)
        import thesis.config.load_config as loader

        if loader.load_dotenv(override=False) is not False:
            raise RecoveryRefused("the .env import of the config loader is not disabled")
        return {"provider_variables": 0, "dotenv_import": "DISABLED"}

    gate.run("provider keys/endpoints absent from the phase-2 process (.env import disabled)",
             environment_clean)
    gate.run("no tool container and no writer lock of any successor run", quiescence, root)
    gate.run("git state", git_state, root)
    if runtime:
        from thesis.recovery_successor_005 import readiness as prd

        def runtime_matches():
            readiness = _json(root, pl.DEFINITIONS_REL + "/readiness.json")
            probe = prd.probe(config)
            problems = prd.check_runtime(lineage, [probe, probe])
            if problems or probe["sha256"] != readiness["runtime_condition_sha256"]:
                raise RecoveryRefused("runtime differs from the readiness: %s" % problems)
            return {"runtime_condition_sha256": probe["sha256"], "vm_mmap_rnd_bits": probe["vm_mmap_rnd_bits"]}

        gate.run("fresh runtime equals the readiness (images, tools, TSan)", runtime_matches)
    if containers:
        gate.run("binding chain inside the pinned tool images", run_containers, config, root)
    gate.run("phase-2 run FRESH after (nothing written)", fresh)
    return gate


def main(argv=None):
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=pl.CONFIG_REL)
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--containers", action="store_true")
    parser.add_argument("--container-check", action="store_true")
    parser.add_argument("--tool", choices=pl.EXTERNAL_TOOLS)
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
    pl.isolate_providers()
    config = load_config(config_path)
    pl.scrub_provider_environment(config)
    gate = preflight(root, config, config_path, args.runtime, args.containers)
    result = OrderedDict([
        ("schema_version", SCHEMA), ("status", gate.status), ("run_id", pl.SUCCESSOR),
        ("python", platform.python_version()),
        ("authorization_created", False), ("provider_calls_made", False),
        ("measurements_started", False), ("checks", gate.checks)])
    print(json.dumps(result, indent=2, default=str))
    return 0 if gate.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
