"""Tool-container entrypoint of the phase-2 successor (LLOV / PARCOACH) and
the ONE supplement writer of the phase-2 static backfill.

Started by the phase-2 driver (measure_static.run_external) inside the
pinned tool image (pareval-llov python3.8 / parcoach-demo python3.11), never
by hand:

    python -B -m thesis.recovery_successor_005.external
        --config thesis/config/recovery_successor_005.yaml
        --profile recovery_successor_005 --run-id full_ext_phase2_001
        --target-id <model>/<source_run> --tool llov|parcoach
        (writer token in $PAREVAL_SUCCESSOR_TOKEN, never on the command line)

Sequence (nothing is written before step 6):
 1. the writer token must match the held phase-2 writer lock;
 2. the cheap binding chain validates (ContainerAuthority): persisted
    authorization -> run provenance fragments -> frozen contract -> its
    phase-2 provenance block (lineage self-hash, target table, equivalence
    proof, config pin). The deep re-hash of every protected byte is NOT
    repeated here: the driver runs it before and after every container;
 3. the target comes from the FROZEN target table (hash bound by the
    contract) and must be a test_feedback target - phase 2 assigns the
    external static backfill to test_feedback candidates only;
 4. the tool is available in this container (environment gate);
 5. stage_runtime.enforce_stage(full_ext_phase2_001, static.<tool>) with
    exactly the values recovery_successor_003's ContainerAuthority registers;
 6. missing-only supplement rows (ledger.missing_static: an entry present in
    the merged record - history, 002/003 supplements, phase-2 ledger -
    whatever its state is never re-run), appended durably, writer token
    re-checked and candidate bytes re-hashed before every row.

supplement_target() also writes the main-container tools for
measure_static.run_main: one row builder, one schema
(successor_static_supplement.v1, field order of recovery_successor_003's
run_supplement) for all six tools.

Exit codes: 0 done; 1 target failure (a tool crashed); 2 environment gate;
3 provenance merge conflict; 4 refusal (token, binding chain, contract,
target, integrity); 5 runtime / effective-invocation drift. 3, 4 and 5 are
GLOBAL_CONFLICT_EXITS: the driver stops the whole run.

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import successor_writer as sw  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402
from thesis.recovery_successor_005 import ledger as pg  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.recovery_successor_005 import targets as pt  # noqa: E402

EXIT_TARGET_FAILURE = 1
EXIT_ENVIRONMENT = 2
EXIT_MERGE_CONFLICT = 3
EXIT_REFUSED = 4
EXIT_RUNTIME_CONFLICT = 5
# exits that are a contract / provenance / runtime conflict: global stop of the run
GLOBAL_CONFLICT_EXITS = OrderedDict([
    (EXIT_MERGE_CONFLICT, "provenance merge conflict"),
    (EXIT_REFUSED, "token / binding chain / contract / target refusal"),
    (EXIT_RUNTIME_CONFLICT, "runtime or effective-invocation drift"),
])
TOKEN_ENV = sw.TOKEN_ENV
TARGET_VARIANT = "test_feedback"
STATE_NOT_APPLICABLE = "NOT_APPLICABLE"  # framework.STATE_NOT_APPLICABLE (counted only, never decided here)
BINDING_FIELDS = ("contract_sha256", "authorization_sha256", "stage_runtime_sha256", "invocation_sha256")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target-id", required=True, help="<model>/<source_run> of the frozen table")
    parser.add_argument("--tool", required=True, choices=pl.EXTERNAL_TOOLS)
    return parser.parse_args(argv)


class ContainerAuthority:
    """Read-only authority checks inside a tool container (the cheap binding
    chain only).

    Deliberately NOT a contract rebuild, NOT an authorization rehydration and
    NOT the deep lineage verification: the driver runs those before and after
    every container. Inside the tool images they are unproven or impossible
    (no python-dotenv, minutes of hashing per container). What IS verified
    here: authorization fingerprint + run provenance integrity -> frozen
    contract (self-hash, == authorization, == manifest/T0 evidence) -> the
    contract's phase-2 provenance block, which binds the lineage self-hash,
    the target table, the equivalence proof and the config pin. Everything
    phase-2 specific is named in the class attributes below, so the contract
    builder's field names can be adjusted in ONE place."""

    CONTRACT_REL = pl.DEFINITIONS_REL + "/contract.json"
    EQUIVALENCE_REL = pl.DEFINITIONS_REL + "/equivalence.json"
    PROVENANCE_BLOCK = "phase2_provenance"
    LINEAGE_FIELD = "lineage_sha256"
    TARGETS_FIELD = "targets_sha256"
    EQUIVALENCE_FIELD = "equivalence_sha256"
    CONFIG_FIELD = "config_lf_sha256"

    def __init__(self, config, config_path, root):
        self.config = config
        self.config_path = Path(config_path)
        self.root = Path(root).resolve()

    def _frozen_contract(self):
        from thesis.evaluation import pilot_run_contract as prc

        try:
            return prc.load_frozen(checked_path(self.root, self.CONTRACT_REL))
        except prc.ContractDrift as drift:
            # a missing or corrupt frozen contract is a contract conflict (global stop)
            raise RecoveryRefused("phase-2 frozen contract: %s" % drift)

    def validate(self):
        import json

        from thesis.evaluation import condition_hashing as ch
        from thesis.evaluation import manifest_fragments as mf
        from thesis.evaluation import run_authorization as ra
        from thesis.evaluation import run_manifest

        stored = ra.load_authorization(self.config, pl.SUCCESSOR)
        if (not stored or stored.get("decision") != ra.DECISION_ALLOWED
                or stored.get("run_id") != pl.SUCCESSOR
                or ra.authorization_fingerprint(stored) != stored.get("authorization_sha256")):
            raise RecoveryRefused("no valid phase-2 authorization is persisted")
        intermediate = Path(self.config["outputs"]["intermediate_dir"])
        tampered = mf.verify_fragment_integrity(intermediate, pl.SUCCESSOR)
        if tampered:
            raise RecoveryRefused("phase-2 run provenance was tampered with: %s" % tampered)
        manifest = run_manifest.load_manifest(self.config, pl.SUCCESSOR) or {}
        frozen = self._frozen_contract()
        evidence = manifest.get("runtime_evidence") or {}
        if (frozen.get("run_id") != pl.SUCCESSOR
                or manifest.get("contract_sha256") != stored["frozen_contract_sha256"]
                or frozen["contract_sha256"] != stored["frozen_contract_sha256"]
                or evidence.get("contract_sha256") != frozen["contract_sha256"]
                or evidence.get("fresh_runtime_condition_sha256")
                != stored.get("fresh_t0_runtime_condition_sha256")):
            raise RecoveryRefused("phase-2 authorization/contract/T0 binding broken")
        provenance = frozen.get(self.PROVENANCE_BLOCK) or {}
        fields = (self.LINEAGE_FIELD, self.TARGETS_FIELD, self.EQUIVALENCE_FIELD, self.CONFIG_FIELD)
        if any(not provenance.get(field) for field in fields):
            raise RecoveryRefused("the frozen contract lacks the %s binding" % self.PROVENANCE_BLOCK)
        if self.config_path.resolve() != (self.root / pl.CONFIG_REL).resolve():
            raise RecoveryRefused("the phase-2 container is bound to %s" % pl.CONFIG_REL)
        # self-hash of the persisted lineage document only (the protected
        # bytes it inventories are re-hashed by the driver, not here)
        lineage = pl.load(self.root)
        proof = json.loads(checked_path(self.root, self.EQUIVALENCE_REL).read_text(encoding="utf-8"))
        if (lineage.sha256 != provenance[self.LINEAGE_FIELD]
                or lineage.targets_sha256 != provenance[self.TARGETS_FIELD]
                or proof.get("proof_sha256") != provenance[self.EQUIVALENCE_FIELD]
                or ch.lf_normalized_sha256(self.config_path) != provenance[self.CONFIG_FIELD]):
            raise RecoveryRefused("phase-2 lineage/targets/proof/config differ from the frozen contract")
        # the proof itself (git-free fast mode: origin pins, routing change,
        # phase-2 source pins, methodical config, test evidence) and the
        # readiness bound to it - the implementation this container runs
        from thesis.recovery_successor_005 import equivalence as pe
        from thesis.recovery_successor_005 import readiness as prd

        pe.validate(proof, self.root, lineage, self.config)
        readiness = json.loads(checked_path(self.root, pl.DEFINITIONS_REL + "/readiness.json")
                               .read_text(encoding="utf-8"))
        prd.validate(readiness, lineage, proof)
        return OrderedDict([("contract_sha256", frozen["contract_sha256"]),
                            ("authorization_sha256", stored["authorization_sha256"]),
                            ("targets_sha256", provenance[self.TARGETS_FIELD])])

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
            self.config, pl.SUCCESSOR, "static.%s" % tool, effective_values=values,
            profile=pl.PROFILE, model_scope=[model], writer="static_analysis")
        if not enforcement.get("enforced"):
            raise RecoveryRefused("phase-2 stage enforcement is NOT_APPLICABLE: %s"
                                  % enforcement.get("reason"))
        return enforcement


# -- shared supplement writer ----------------------------------------------------

def template_sha256(config, tool):
    from thesis.evaluation.condition_hashing import utf8_sha256

    template = (((config.get("stages") or {}).get("repair") or {})
                .get("external_tool_commands") or {}).get(tool)
    return utf8_sha256(template) if template else None


def runner_block(template=None):
    """The runner provenance of a row: this process's argv and interpreter;
    template_sha256 only for the container tools (None in the driver)."""
    return OrderedDict([("argv", list(sys.argv)), ("python", platform.python_version()),
                        ("template_sha256", template)])


def evaluation_context(config, root=None):
    from thesis.evaluation import framework

    root = Path(root).resolve() if root is not None else REPO_ROOT
    return framework.EvaluationContext(repo_root=root, drivers_cpp_dir=root / "drivers" / "cpp",
                                       primary_compiler="g++", config=config)


def resolve_tool(config, tool):
    """The registered tool exactly as run_static_analysis.main obtains it
    (register_default_tools with the config options); unavailable -> the
    environment gate (nothing written)."""
    from thesis.evaluation import framework
    from thesis.evaluation import tools as tools_module

    tools_module.register_default_tools(primary_compiler="g++", config=config)
    settings = pg.static_settings(config)
    if tool not in settings:
        raise RecoveryRefused("tool %s is not enabled in the configuration" % tool)
    instance = framework.get_tool(tool)
    if not instance.is_available():
        raise EnvironmentError("ENVIRONMENT GATE FAILED: %s unavailable in this container" % tool)
    return instance, settings[tool]


def checked_binding(binding):
    """The four phase-2 binding shas, all present (a NOT_APPLICABLE
    enforcement has none and must never produce a row)."""
    result = OrderedDict()
    for field in BINDING_FIELDS:
        value = (binding or {}).get(field)
        if not isinstance(value, str) or not value:
            raise pl.GlobalStop("phase-2 binding lacks %s" % field)
        result[field] = value
    return result


def ledger_paths(root, target, tools):
    return OrderedDict((tool, pt.ledger_path(root, target.model_id, target.source_run, "static.%s.jsonl" % tool))
                       for tool in tools)


def archive_ledgers(root, target, tools, log=print):
    """Archive torn ledger tails (crash during an append) before anything
    reads them; the caller holds the writer lock (token checked)."""
    for tool, path in ledger_paths(root, target, tools).items():
        archived = sw.archive_torn_tail(path)
        if archived:
            log("archived a torn tail (%d bytes) of %s static.%s.jsonl" % (archived, target.target_id, tool))


def archive_all_ledgers(root, config, target, log=print):
    """Archive the torn tails of EVERY enabled static tool's ledger of a
    target: the merged-view read (ledger.missing_static) reads all of them,
    so a torn tail of one tool would otherwise block every other stage. Safe
    for any lock holder (single writer)."""
    from thesis.recovery_successor_005 import ledger as _pg

    archive_ledgers(root, target, list(_pg.static_settings(config)), log)


def check_source_pin(record, sample_id, source_sha):
    """The native merge guard (static_provenance.check_merge, exactly as
    run_static_analysis.run_model applies it before adding a tool to an
    existing record): the historical record must be pinned to the candidate
    bytes being measured. A conflict is a provenance conflict (global)."""
    from thesis.evaluation import static_provenance as provenance

    try:
        provenance.check_merge(record, sample_id, source_sha)
    except provenance.StaticMergeConflict as conflict:
        raise pl.GlobalStop("static merge refused for %s: %s" % (sample_id, conflict))


def static_artifact(root, target):
    relative = pt.run_dir(target.source_run, target.model_id) + "/" + pt.STATIC_FILE
    data = checked_path(Path(root), relative).read_bytes()
    return OrderedDict([("path", relative), ("raw_sha256", hashlib.sha256(data).hexdigest())])


def source_sha256(root, target, sample):
    """Re-hash the candidate bytes against the frozen table (before the tool
    runs AND again before its row is written)."""
    facts = target.samples[sample.sample_id]
    path = checked_path(Path(root), facts["source_path"])
    if path.resolve() != Path(sample.source_path).resolve():
        raise pl.GlobalStop("assembly source path differs from the frozen table: " + sample.sample_id)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != facts["source_sha256"]:
        raise pl.GlobalStop("candidate source drifted from the frozen table: " + sample.sample_id)
    return digest


def supplement_row(target, sample, tool, source_sha, static_facts, entry, runner, binding):
    """One successor_static_supplement.v1 row (field order of
    recovery_successor_003/external.py::run_supplement)."""
    from thesis.evaluation import successor_supplement as ss
    from thesis.generation import common

    assembly = target.document["assembly"]
    return OrderedDict([
        ("schema_version", ss.SUPPLEMENT_SCHEMA),
        ("run_id", pl.SUCCESSOR),
        ("authority_run_id", pl.SUCCESSOR),
        ("candidate_source_run", target.source_run),
        ("model_id", target.model_id), ("variant", target.variant), ("iteration", target.iteration),
        ("sample_id", sample.sample_id), ("execution_model", sample.execution_model),
        ("tool", tool),
        ("candidate_source_sha256", source_sha),
        ("predecessor_static_artifact", OrderedDict([("path", static_facts["path"]),
                                                     ("raw_sha256", static_facts["raw_sha256"])])),
        ("predecessor_assembly_artifact", OrderedDict([("path", assembly["path"]),
                                                       ("raw_sha256", assembly["raw_sha256"])])),
        ("entry", entry),
        ("runner", runner),
        ("contract_sha256", binding["contract_sha256"]),
        ("authorization_sha256", binding["authorization_sha256"]),
        ("stage_runtime_sha256", binding["stage_runtime_sha256"]),
        ("invocation_sha256", binding["invocation_sha256"]),
        ("created_at_utc", common.utc_now_iso()),
    ])


def supplement_target(root, config, target, instruments, context, binding, runner, token,
                      log=print, stop=None):
    """Missing-only supplement rows of ONE test_feedback target for the tools
    in `instruments` (OrderedDict tool -> (tool object, ToolSettings)).

    The work list is ledger.missing_static (never re-measures a present
    entry, whatever its state); tools run per sample in config order; the
    entry is successor_supplement.measure_entry (the native run_model steps,
    NOT_APPLICABLE for out-of-scope samples). `stop()` is polled between
    samples: True ends the target cleanly after the current sample.
    Returns (Counter, stopped)."""
    from thesis.evaluation import successor_supplement as ss

    root = Path(root).resolve()
    if target.variant != TARGET_VARIANT:
        raise pl.GlobalStop("the phase-2 static backfill serves test_feedback targets only: %s"
                            % target.target_id)
    binding = checked_binding(binding)
    sw.require_token(root, pl.SUCCESSOR, token)
    paths = ledger_paths(root, target, instruments)
    archive_all_ledgers(root, config, target, log)
    samples = pt.assembled_samples(root, target)
    artifact = static_artifact(root, target)
    historical = pt.historical_records(root, target, pt.STATIC_FILE)
    missing = pg.missing_static(root, config, target)
    counts = Counter()
    present = len(samples) * len(instruments) - sum(
        len([t for t in tools if t in instruments]) for tools in missing.values())
    stopped = False
    for sample in samples:
        tools = [tool for tool in missing.get(sample.sample_id, ()) if tool in instruments]
        if not tools:
            continue
        states = []
        check_source_pin(historical.get(sample.sample_id), sample.sample_id,
                         source_sha256(root, target, sample))
        for tool in tools:
            instance, settings = instruments[tool]
            source_sha = source_sha256(root, target, sample)
            try:
                entry = ss.measure_entry(instance, settings, sample, context, source_sha)
            except RecoveryRefused:
                raise
            except Exception as error:  # noqa: BLE001 - a tool crash is confined to this target
                raise pl.TargetFailure("%s crashed on %s: %s: %s"
                                       % (tool, sample.sample_id, type(error).__name__, error))
            source_sha256(root, target, sample)  # the bytes are unchanged after the tool ran
            sw.require_token(root, pl.SUCCESSOR, token)  # still the lock holder (or its child)
            sw.durable_append_jsonl(paths[tool], supplement_row(target, sample, tool, source_sha, artifact,
                                                                entry, runner, binding))
            counts["rows"] += 1
            counts["rows." + tool] += 1
            if entry.get("analysis_state") == STATE_NOT_APPLICABLE:
                counts["not_applicable"] += 1
            states.append("%s=%s" % (tool, entry.get("analysis_state")))
        counts["samples"] += 1
        log("  %s: %s" % (sample.sample_id, " ".join(states)))
        if stop is not None and stop():
            stopped = True
            break
    if static_artifact(root, target)["raw_sha256"] != artifact["raw_sha256"]:
        raise pl.GlobalStop("historical static record changed during the backfill: " + artifact["path"])
    log("static %s [%s]: %d row(s) written for %d sample(s), %d (sample, tool) already present%s"
        % (target.target_id, ",".join(instruments), counts["rows"], counts["samples"], present,
           " - STOPPED on request" if stopped else ""))
    return counts, stopped


# -- container entrypoint ----------------------------------------------------------

def run(args, root=None, authority=None, log=print):
    """Container body; returns the number of rows written."""
    from thesis.config.load_config import load_config

    root = Path(root).resolve() if root is not None else REPO_ROOT
    if args.run_id != pl.SUCCESSOR or args.profile != pl.PROFILE:
        raise RecoveryRefused("this entrypoint serves the phase-2 run %s only" % pl.SUCCESSOR)
    if args.tool not in pl.EXTERNAL_TOOLS:
        raise RecoveryRefused("%s is not a container tool" % args.tool)
    model, _, source_run = str(args.target_id).partition("/")
    if model not in pl.MODELS or not source_run:
        raise RecoveryRefused("target %r is outside the phase-2 model scope" % args.target_id)
    token = os.environ.get(TOKEN_ENV)
    sw.require_token(root, pl.SUCCESSOR, token)
    config_path = (root / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)
    pl.isolate_providers()
    config = load_config(config_path)
    pl.scrub_provider_environment(config)
    authority = authority or ContainerAuthority(config, config_path, root)
    facts = authority.validate()
    if not facts.get("targets_sha256"):
        raise RecoveryRefused("the authority did not bind the target table")
    table = pt.load_table(root, facts["targets_sha256"])
    target = table.get(args.target_id)
    if target.variant != TARGET_VARIANT:
        raise RecoveryRefused("phase 2 runs container tools on test_feedback targets only: %s"
                              % target.target_id)
    instance, settings = resolve_tool(config, args.tool)
    context = evaluation_context(config, root)
    enforcement = authority.enforce(args.tool, target.model_id)
    binding = OrderedDict([("contract_sha256", facts.get("contract_sha256")),
                           ("authorization_sha256", facts.get("authorization_sha256")),
                           ("stage_runtime_sha256", enforcement.get("stage_runtime_sha256")),
                           ("invocation_sha256", enforcement.get("invocation_sha256"))])
    counts, _stopped = supplement_target(
        root, config, target, OrderedDict([(args.tool, (instance, settings))]), context, binding,
        runner_block(template_sha256(config, args.tool)), token, log=log)
    return counts["rows"]


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
        print("PHASE-2 EXTERNAL REFUSED: %s" % refused)
        return EXIT_REFUSED
    except (stage_runtime.StageRuntimeDrift, effective_invocation.InvocationRefused) as drift:
        print("RUNTIME CONFLICT (fail-closed): %s" % drift)
        return EXIT_RUNTIME_CONFLICT
    except pl.TargetFailure as failure:
        print("TARGET FAILURE: %s" % failure)
        return EXIT_TARGET_FAILURE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
