"""Tool-container entrypoint of the successor run (LLOV / PARCOACH).

Started by the successor loop inside the pinned tool image (pareval-llov
python3.8 / parcoach-demo python3), never by hand:

    python -B -m thesis.recovery_successor_004.external
        --config thesis/config/recovery_successor_004.yaml
        --profile recovery_successor_004 --run-id full_ext_recovery_004
        --target-run-id full_ext_recovery_004__<variant>__iter<N>
        --model-id M --variant V --iteration N
        --tool llov|parcoach        (writer token in $PAREVAL_SUCCESSOR_TOKEN)

Sequence (nothing is written before step 5):
 1. the writer token must match the held successor writer lock;
 2. the binding chain validates: persisted successor authorization ->
    frozen contract -> successor lineage (recovery_001 snapshot, protected
    siblings) -> successor proof (Python-3.8-stable AST) -> config pin;
 3. the target is the IN-FLIGHT successor iteration (1 or 2) of this
    static/combined loop: wave at that iteration in phase assembled or
    analyzed_waiting_external (the parent full_ext_001 and every other run
    are refused - parent measurements are never backfilled);
 4. the tool is available in this container (environment gate);
 5. the native order of run_static_analysis.main on the successor-owned
    target: toolchain record -> target run manifest -> static condition;
 6. stage_runtime.enforce_stage(full_ext_recovery_004, static.<tool>) stamps
    the runtime against the successor T0 evidence and registers the
    invocation (a refusal here leaves only the successor-owned records of
    step 5, exactly like the native runner);
 7. run_static_analysis.run_model (missing-only: a stored entry, including
    TIMEOUT/TOOL_ERROR, is present and never re-run).

Exit codes: 0 done; 2 environment gate (tool unavailable); 3 provenance merge
conflict; 4 refusal (token, binding chain, contract, target); 5 runtime /
effective-invocation drift. The driver treats 3, 4 and 5 as a contract /
provenance / runtime conflict and stops the WHOLE run (GLOBAL_CONFLICT_EXITS).

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import platform
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.recovery_successor_004 import handoff as sh  # noqa: E402
from thesis.recovery_successor_004 import lineage as sl  # noqa: E402
from thesis.evaluation import successor_writer as sw  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402

EXIT_REFUSED = 4
EXIT_ENVIRONMENT = 2
EXIT_MERGE_CONFLICT = 3
EXIT_RUNTIME_CONFLICT = 5
# exits that are a contract / provenance / runtime conflict: global stop of the run
GLOBAL_CONFLICT_EXITS = OrderedDict([
    (EXIT_MERGE_CONFLICT, "provenance merge conflict"),
    (EXIT_REFUSED, "token / binding chain / contract / target refusal"),
    (EXIT_RUNTIME_CONFLICT, "runtime or effective-invocation drift"),
])
TOKEN_ENV = sw.TOKEN_ENV


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target-run-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--tool", required=True, choices=sl.EXTERNAL_TOOLS)
    return parser.parse_args(argv)


class ContainerAuthority:
    """Read-only authority checks inside a tool container.

    Deliberately NOT a contract rebuild and NOT an authorization
    rehydration: those run in the driver on every step and every provider
    call. Inside the tool images they are unproven (conditions_view) or
    impossible (no python-dotenv -> provider endpoint identities resolve as
    UNSET, which is irrelevant to static analysis). Here the binding chain is
    verified: authorization fingerprint + run provenance integrity -> frozen
    contract -> successor lineage (recovery_001 snapshot, siblings) -> successor proof
    (git-free, Python-3.8-stable AST) -> config pin."""

    def __init__(self, config, config_path, root):
        self.config = config
        self.config_path = Path(config_path)
        self.root = Path(root)

    def validate(self):
        import json

        from thesis.evaluation import condition_hashing as ch
        from thesis.evaluation import manifest_fragments as mf
        from thesis.evaluation import pilot_run_contract as prc
        from thesis.evaluation import run_authorization as ra
        from thesis.evaluation import run_manifest
        from thesis.recovery_successor_004 import contract as sc
        from thesis.recovery_successor_004 import equivalence as se

        stored = ra.load_authorization(self.config, sl.SUCCESSOR)
        if (not stored or stored.get("decision") != ra.DECISION_ALLOWED
                or stored.get("run_id") != sl.SUCCESSOR
                or ra.authorization_fingerprint(stored) != stored.get("authorization_sha256")):
            raise RecoveryRefused("no valid successor authorization is persisted")
        intermediate = Path(self.config["outputs"]["intermediate_dir"])
        tampered = mf.verify_fragment_integrity(intermediate, sl.SUCCESSOR)
        if tampered:
            raise RecoveryRefused("successor run provenance was tampered with: %s" % tampered)
        manifest = run_manifest.load_manifest(self.config, sl.SUCCESSOR) or {}
        frozen = prc.load_frozen(sc.frozen_path(self.root))
        evidence = manifest.get("runtime_evidence") or {}
        if (manifest.get("contract_sha256") != stored["frozen_contract_sha256"]
                or frozen["contract_sha256"] != stored["frozen_contract_sha256"]
                or evidence.get("contract_sha256") != frozen["contract_sha256"]
                or evidence.get("fresh_runtime_condition_sha256")
                != stored.get("fresh_t0_runtime_condition_sha256")):
            raise RecoveryRefused("successor authorization/contract/T0 binding broken")
        provenance = frozen.get("successor_provenance") or {}
        lineage = sl.load(self.root)
        lineage.verify_quick()
        proof = json.loads((sc.definitions(self.root) / "equivalence.json").read_text(encoding="utf-8"))
        if (lineage.sha256 != provenance.get("lineage_sha256")
                or proof.get("proof_sha256") != provenance.get("equivalence_sha256")
                or ch.lf_normalized_sha256(self.config_path) != provenance.get("config_lf_sha256")):
            raise RecoveryRefused("successor lineage/proof/config differ from the frozen contract")
        se.validate(proof, self.root, lineage, self.config)
        return OrderedDict([("contract_sha256", frozen["contract_sha256"]),
                            ("authorization_sha256", stored["authorization_sha256"])])

    def enforce(self, tool, model):
        from thesis.evaluation import stage_runtime

        values = {
            "primary_compiler": {"value": "g++", "source": "DEFAULT"},
            "tools": {"value": [tool], "source": "CLI"},
            "replace_tool_entries": {"value": False, "source": "DEFAULT"},
            "rerun_gaps": {"value": False, "source": "DEFAULT"},
            "replace_legacy_record": {"value": False, "source": "DEFAULT"},
        }
        enforcement = stage_runtime.enforce_stage(
            self.config, sl.SUCCESSOR, "static.%s" % tool, effective_values=values,
            profile=sl.PROFILE, model_scope=[model], writer="static_analysis")
        if not enforcement.get("enforced"):
            raise RecoveryRefused("successor stage enforcement is NOT_APPLICABLE: %s"
                                  % enforcement.get("reason"))
        return enforcement


def wave_in_flight(root, config, model, variant, iteration):
    from thesis.repair import orchestrator

    paths = orchestrator.LoopPaths(config, sl.SUCCESSOR, model, variant)
    path = Path(root) / paths.wave_state_path
    if not path.exists():
        raise RecoveryRefused("no successor wave for an iteration-%d target" % iteration)
    import json
    wave = json.loads(path.read_text(encoding="utf-8"))
    if (wave.get("run_id") != sl.SUCCESSOR or wave.get("model_id") != model
            or wave.get("variant") != variant or wave.get("iteration") != iteration
            or wave.get("phase") not in ("assembled", "analyzed_waiting_external")):
        raise RecoveryRefused("target iteration %d is not in flight for %s/%s" % (iteration, model, variant))
    return wave.get("phase")


def template_sha256(config, tool):
    from thesis.evaluation.condition_hashing import utf8_sha256

    template = (((config.get("stages") or {}).get("repair") or {})
                .get("external_tool_commands") or {}).get(tool)
    return utf8_sha256(template) if template else None


def resolve_tool(config, tool):
    from thesis.evaluation import framework
    from thesis.evaluation.run_static_analysis import resolve_enabled_tools
    from thesis.evaluation.tools import register_default_tools

    register_default_tools(primary_compiler="g++", config=config)
    known = resolve_enabled_tools(config, [tool], "static_analysis")
    expected = resolve_enabled_tools(config, None, "static_analysis")
    if tool not in known:
        raise RecoveryRefused("tool %s is not enabled in the configuration" % tool)
    instance = framework.get_tool(tool)
    if not instance.is_available():
        raise EnvironmentError("ENVIRONMENT GATE FAILED: %s unavailable in this container" % tool)
    return instance, known, expected


def evaluation_context(config):
    from thesis.evaluation import framework

    return framework.EvaluationContext(repo_root=REPO_ROOT, drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
                                       primary_compiler="g++", config=config)


def run_native(root, config, profile, target, model, tool, known, expected, context, token,
               log=print, enforce=None):
    """run_static_analysis.main's write order, on a SUCCESSOR-owned target:
    toolchain record -> target manifest -> static condition -> stage
    enforcement (invocation + runtime stamp on the successor) -> run_model."""
    from pathlib import Path as _Path

    from thesis.evaluation import run_static_analysis as rsa
    from thesis.evaluation import static_provenance as provenance
    from thesis.evaluation.run_manifest import ensure_run_manifest, register_static_condition

    intermediate = _Path(config["outputs"]["intermediate_dir"])
    sw.require_token(root, sl.SUCCESSOR, token)
    rsa.record_toolchain_versions(intermediate, target)
    ensure_run_manifest(config, target, stage="static_analysis", profile=profile, primary_compiler="g++")
    condition = provenance.static_analysis_condition(config, "g++")
    register_static_condition(config, target, provenance.static_analysis_condition_sha256(condition),
                              condition)
    if enforce is not None:
        enforce()
    return rsa.run_model(context=context, intermediate_dir=intermediate, run_id=target,
                         model_id=model, tool_settings=known, tools_skipped=[],
                         expected_tools=expected,
                         invocation_label="successor_external --tools %s" % tool)


def run(args, root=None, authority=None, log=print):
    from thesis.config.load_config import load_config

    root = Path(root).resolve() if root is not None else REPO_ROOT
    if args.run_id != sl.SUCCESSOR or args.profile != sl.PROFILE:
        raise RecoveryRefused("this entrypoint serves the successor run only")
    # test_feedback never runs external tools natively (orchestrator.pending_external)
    if args.model_id not in sl.MODELS or args.variant not in ("static_feedback", "combined_feedback"):
        raise RecoveryRefused("loop outside the successor external-tool scope")
    if type(args.iteration) is not int or args.iteration not in sl.PROVIDER_ITERATIONS:
        raise RecoveryRefused("parent iteration-0 evidence is never backfilled")
    import os
    token = os.environ.get(TOKEN_ENV)
    sw.require_token(root, sl.SUCCESSOR, token)
    config_path = (root / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)
    config = load_config(config_path)
    authority = authority or ContainerAuthority(config, config_path, root)
    authority.validate()
    target = sh.iteration_run(sl.SUCCESSOR, args.variant, args.iteration, sl.MAX_ITERATIONS)
    if args.target_run_id != target:
        raise RecoveryRefused("target %s is not the successor-writable iteration target %s"
                              % (args.target_run_id, target))
    wave_in_flight(root, config, args.model_id, args.variant, args.iteration)
    _tool_instance, known, expected = resolve_tool(config, args.tool)
    context = evaluation_context(config)
    return run_native(root, config, args.profile, target, args.model_id, args.tool, known,
                      expected, context, token, log=log,
                      enforce=lambda: authority.enforce(args.tool, args.model_id))


def main(argv=None):
    from thesis.evaluation import effective_invocation, stage_runtime
    from thesis.evaluation import static_provenance as provenance

    args = parse_args(argv)
    try:
        run(args)
    except EnvironmentError as error:
        print(str(error))
        return EXIT_ENVIRONMENT
    except provenance.StaticMergeConflict as conflict:
        print("MERGE REFUSED (fail-closed): %s" % conflict)
        return EXIT_MERGE_CONFLICT
    except RecoveryRefused as refused:
        print("SUCCESSOR EXTERNAL REFUSED: %s" % refused)
        return EXIT_REFUSED
    except (stage_runtime.StageRuntimeDrift, effective_invocation.InvocationRefused) as drift:
        print("RUNTIME CONFLICT (fail-closed): %s" % drift)
        return EXIT_RUNTIME_CONFLICT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
