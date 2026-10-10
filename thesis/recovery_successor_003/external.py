"""Tool-container entrypoint of the successor run (LLOV / PARCOACH).

Started by the successor loop inside the pinned tool image (pareval-llov
python3.8 / parcoach-demo python3), never by hand:

    python -B -m thesis.recovery_successor_003.external
        --config thesis/config/recovery_successor_003.yaml
        --profile recovery_successor_003 --run-id full_ext_recovery_003
        --target-run-id <target> --model-id M --variant V --iteration N
        --tool llov|parcoach        (writer token in $PAREVAL_SUCCESSOR_TOKEN)

Sequence (nothing is written before step 5):
 1. the writer token must match the held successor writer lock;
 2. the successor contract rebuilds to the frozen one (Python-3.8-stable
    proof: successor_ast) and the persisted successor authorization
    validates (rehydration checks, explicit contract path);
 3. the target is the in-flight iteration of this loop:
      * predecessor full_ext_recovery_001__V__iter1  -> SUPPLEMENT mode
      * successor   full_ext_recovery_002__V__iter2  -> NATIVE mode
 4. the tool is available in this container (environment gate);
 5. stage_runtime.enforce_stage(full_ext_recovery_002, static.<tool>) stamps
    the runtime against the successor T0 evidence and registers the
    invocation - exactly the values run_static_analysis.main registers;
 6. SUPPLEMENT: missing-only rows (a stored predecessor or supplement entry,
    including TIMEOUT/TOOL_ERROR, is present and never re-run) appended
    durably to the successor supplement ledger; the predecessor
    static_analysis.jsonl is only read (snapshot-verified).
    NATIVE: the native write order of run_static_analysis.main on the
    successor-owned target, then run_static_analysis.run_model.

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

from thesis.recovery_successor_003 import handoff as sh  # noqa: E402
from thesis.recovery_successor_003 import lineage as sl  # noqa: E402
from thesis.evaluation import successor_supplement as ss  # noqa: E402
from thesis.evaluation import successor_writer as sw  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402

EXIT_REFUSED = 4
EXIT_ENVIRONMENT = 2
EXIT_MERGE_CONFLICT = 3
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
    contract -> successor lineage (predecessor snapshot) -> successor proof
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
        from thesis.recovery_successor_003 import contract as sc
        from thesis.recovery_successor_003 import equivalence as se

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
        if iteration != 1:
            raise RecoveryRefused("no successor wave for an iteration-%d target" % iteration)
        return "SEEDED_FROM_PREDECESSOR"
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


def run_supplement(root, lineage, config, model, variant, tool, authority_facts,
                   enforcement, tool_instance, settings, context, token, log=print):
    """Missing-only LLOV/PARCOACH entries for a PREDECESSOR iteration-1 target."""
    from thesis.generation import common

    run = sh.predecessor_iteration_run(variant, 1)
    view = lineage.view
    assembly_rel = sh.iteration_dir(run, model) + "/assembly.jsonl"
    static_rel = sh.iteration_dir(run, model) + "/static_analysis.jsonl"
    assembly_rows = list(view.unique_rows(assembly_rel, run, model).values())
    records = view.unique_rows(static_rel, run, model)
    samples = ss.assembled_samples(root, assembly_rows, run, model)
    expected = OrderedDict((s.sample_id, s.execution_model) for s in samples)
    relative = ss.supplement_relative(sl.SUCCESSOR, model, run, tool)
    path = checked_path(root, relative)
    archived = sw.archive_torn_tail(path)
    if archived:
        log("archived a torn supplement tail (%d bytes) of %s" % (archived, relative))
    present = ss.index_rows(sw.read_jsonl(path), successor_run=sl.SUCCESSOR,
                            predecessor_target=run, model=model, tool=tool, expected=expected)
    contributions = []
    for sample in samples:
        if tool in ((records.get(sample.sample_id) or {}).get("tools") or {}):
            raise RecoveryRefused("predecessor already carries %s for %s" % (tool, sample.sample_id))
    for sample_id, row in present.items():
        contributions.append((sample_id, dict(source_run=row["run_id"], source_artifact_sha256="supplement",
                                               record=dict(run_id=row["run_id"]))))
    missing = sh.missing_tool_keys(list(expected), contributions)
    written = 0
    for sample in samples:
        if sample.sample_id not in missing:
            continue
        source_rel = sh.iteration_dir(run, model) + "/sources/%s/generated-code.hpp" % sample.sample_id
        source_bytes = view.read_bytes(source_rel)
        import hashlib
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        record = records.get(sample.sample_id) or {}
        entry_sha = (sample.assembly_entry or {}).get("source_sha256")
        if record.get("sample_source_sha256") != source_sha or (entry_sha and entry_sha != source_sha):
            raise RecoveryRefused("predecessor source/record/assembly disagree for " + sample.sample_id)
        entry = ss.measure_entry(tool_instance, settings, sample, context, source_sha)
        view.read_bytes(source_rel)  # unchanged while the tool ran
        sw.require_token(root, sl.SUCCESSOR, token)  # still the lock holder's child
        sw.durable_append_jsonl(path, OrderedDict([
            ("schema_version", ss.SUPPLEMENT_SCHEMA),
            ("run_id", sl.SUCCESSOR),
            ("authority_run_id", sl.SUCCESSOR),
            ("candidate_source_run", run),
            ("model_id", model), ("variant", variant), ("iteration", 1),
            ("sample_id", sample.sample_id), ("execution_model", sample.execution_model),
            ("tool", tool),
            ("candidate_source_sha256", source_sha),
            ("predecessor_static_artifact", OrderedDict([("path", static_rel),
                                                         ("raw_sha256", view.sha256(static_rel))])),
            ("predecessor_assembly_artifact", OrderedDict([("path", assembly_rel),
                                                           ("raw_sha256", view.sha256(assembly_rel))])),
            ("entry", entry),
            ("runner", OrderedDict([("argv", list(sys.argv)), ("python", platform.python_version()),
                                    ("template_sha256", template_sha256(config, tool))])),
            ("contract_sha256", authority_facts["contract_sha256"]),
            ("authorization_sha256", authority_facts["authorization_sha256"]),
            ("stage_runtime_sha256", enforcement.get("stage_runtime_sha256")),
            ("invocation_sha256", enforcement.get("invocation_sha256")),
            ("created_at_utc", common.utc_now_iso()),
        ]))
        written += 1
        log("  %s %s: %s" % (tool, sample.sample_id, entry.get("analysis_state")))
    log("supplement %s/%s/%s: %d written, %d already present, %d expected"
        % (run, model, tool, written, len(present), len(expected)))
    return written


def run_native(root, config, profile, target, model, tool, known, expected, context, token,
               log=print):
    """run_static_analysis.main's write order, on a SUCCESSOR-owned target."""
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
    return rsa.run_model(context=context, intermediate_dir=intermediate, run_id=target,
                         model_id=model, tool_settings=known, tools_skipped=[],
                         expected_tools=expected,
                         invocation_label="successor_external --tools %s" % tool)


def run(args, root=None, authority=None, log=print):
    from thesis.config.load_config import load_config

    root = Path(root).resolve() if root is not None else REPO_ROOT
    if args.run_id != sl.SUCCESSOR or args.profile != sl.PROFILE:
        raise RecoveryRefused("this entrypoint serves the successor run only")
    if args.model_id not in sl.MODELS or args.variant not in sl.CONTINUE_VARIANTS:
        raise RecoveryRefused("loop outside the successor continuation scope")
    import os
    token = os.environ.get(TOKEN_ENV)
    sw.require_token(root, sl.SUCCESSOR, token)
    config_path = (root / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)
    config = load_config(config_path)
    authority = authority or ContainerAuthority(config, config_path, root)
    facts = authority.validate()
    lineage = sl.load(root)
    supplement_target = sh.predecessor_iteration_run(args.variant, 1)
    native_target = sh.iteration_run(sl.SUCCESSOR, args.variant, 2, sl.MAX_ITERATIONS)
    if args.iteration == 1 and args.target_run_id == supplement_target:
        mode = "SUPPLEMENT"
        if args.tool not in sl.SUPPLEMENT_TOOLS:
            raise RecoveryRefused("%s is no successor supplement of predecessor iteration 1" % args.tool)
    elif args.iteration == 2 and args.target_run_id == native_target:
        mode = "NATIVE"
    else:
        raise RecoveryRefused("target %s is not a successor-writable iteration target" % args.target_run_id)
    wave_in_flight(root, config, args.model_id, args.variant, args.iteration)
    tool_instance, known, expected = resolve_tool(config, args.tool)
    context = evaluation_context(config)
    enforcement = authority.enforce(args.tool, args.model_id)
    if mode == "SUPPLEMENT":
        return run_supplement(root, lineage, config, args.model_id, args.variant, args.tool, facts,
                              enforcement, tool_instance, known[args.tool], context, token, log=log)
    return run_native(root, config, args.profile, native_target, args.model_id, args.tool, known,
                      expected, context, token, log=log)


def main(argv=None):
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
