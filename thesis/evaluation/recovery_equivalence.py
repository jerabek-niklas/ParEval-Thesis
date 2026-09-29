"""Recovery proof definitions; never upgrades a legacy certificate.

Transport equivalence and routing equivalence are distinct obligations. An
external reviewed test-evidence document must bind its exact source set. A
definition is not a successful proof and cannot authorize a run.
"""
from __future__ import annotations

import ast
import difflib
import json

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path

DOMAINS = (
    "prompts_text", "models_reasoning_parameters", "generation_semantics",
    "assembly_cleaning", "static_tool_semantics", "correctness_launch_semantics",
    "dynamic_semantics", "repair_feedback", "repair_stop_rules", "variants",
    "max_iterations", "enhanced_specs_policy", "compiler_tool_identities",
)
OBLIGATIONS = ("PARSER_TRANSPORT_COMPATIBILITY", "RECOVERY_READ_WRITE_ROUTING")


def portable_ast(node):
    """Canonical AST content, independent of ast.dump's versioned defaults.

Absent optional fields and empty lists represent the same AST content on
Python 3.8/3.12/3.14. Source bytes are separately pinned in full.
"""
    if isinstance(node, ast.AST):
        return {"node": type(node).__name__, "fields": {
            name: portable_ast(value) for name, value in ast.iter_fields(node)
            if value is not None and value != []}}
    if isinstance(node, list):
        return [portable_ast(value) for value in node]
    return node

# Functions whose control-plane routing changes are explicitly reviewed.
# All other AST nodes in these files must remain identical to the parent.
ROUTING_FUNCTIONS = {
    "thesis/evaluation/check_static_repair_readiness.py": {"docker_image_identity"},
    "thesis/evaluation/run_authorization.py": {"discover_frozen_contract"},
    "thesis/evaluation/pilot_run_contract.py": {"build_contract"},
    "thesis/repair/run_repair.py": {"build_loops"},
    "thesis/repair/run_backfill.py": {"load_assembly", "discover_runs", "plan_run", "backfill_model", "_enforce"},
    "thesis/repair/backfill_authority.py": {"validate_target"},
    "thesis/evaluation/repair_scope.py": {"productive_missing_internal_stages"},
    "thesis/evaluation/verify_pilot_run.py": {"check_enhanced_source_drift"},
    "thesis/evaluation/run_enhanced_tests.py": set(),
}


def required_sources(root, added):
    certificate = json.loads((root / "thesis/evaluation/full_extension_equivalence.json").read_text(encoding="utf-8"))
    return tuple(sorted(set(certificate["source_pins"]) | set(added)))


def unchanged_projection(root):
    """Recompute evidence, not self-reported unchanged-domain labels."""
    from thesis.evaluation.recovery_historical_source import git_blob
    from thesis.evaluation.recovery_source_projection import pre_recovery_enhanced_source
    from thesis.evaluation.verify_parent_base_evidence import read_json, BASE
    from thesis.config.load_config import load_config
    manifest = read_json(root / BASE / "run_manifest.json")
    commit = manifest["git_commit"]
    certificate = json.loads(git_blob(root, commit, "thesis/evaluation/full_extension_equivalence.json"))
    unchanged = {}
    for relative, old_sha in certificate["source_pins"].items():
        path = checked_path(root, relative)
        actual = ch.lf_normalized_sha256(path)
        if actual == old_sha:
            unchanged[relative] = old_sha
            continue
        if relative == "thesis/evaluation/test_backfill_equivalence.py":
            # Regression source itself is pinned separately, not claimed to
            # be a measurement implementation.
            continue
        if relative not in ROUTING_FUNCTIONS:
            raise RecoveryRefused("unregistered source change: " + relative)
        before = git_blob(root, commit, relative).decode("utf-8")
        after = path.read_text(encoding="utf-8")
        if relative.endswith("run_enhanced_tests.py"):
            after = pre_recovery_enhanced_source(after)
        excluded = ROUTING_FUNCTIONS[relative]
        def projection(text):
            tree = ast.parse(text)
            class RoutingFunctions(ast.NodeTransformer):
                def visit_FunctionDef(self, node):
                    return None if node.name in excluded else self.generic_visit(node)
            tree = RoutingFunctions().visit(tree)
            return json.dumps(portable_ast(tree), sort_keys=True, separators=(",", ":"))
        old, new = projection(before), projection(after)
        if old != new:
            raise RecoveryRefused("non-routing implementation changed: " + relative)
        unchanged[relative + "#non_routing_ast"] = ch.utf8_sha256(old)
    config = load_config(root / "thesis/config/recovery.yaml")
    for key in ("models", "generation_defaults", "prompts", "stages"):
        if config.get(key) != manifest["resolved_config"].get(key):
            raise RecoveryRefused("methodical configuration changed: " + key)
        unchanged["config:" + key] = ch.canonical_sha256(config[key])
    return unchanged


def build(root, added_sources, test_evidence):
    from thesis.evaluation.recovery_historical_source import git_blob
    from thesis.evaluation.verify_parent_base_evidence import read_json, BASE
    sources = required_sources(root, added_sources)
    projection = unchanged_projection(root)
    invariant_sha = ch.canonical_sha256(projection)
    pins = source_pins(root, sources)
    commit = read_json(root / BASE / "run_manifest.json")["git_commit"]
    diffs = {}
    old_pins = {}
    for relative in sorted(set(added_sources) | set(ROUTING_FUNCTIONS)):
        try:
            before = git_blob(root, commit, relative).decode("utf-8").replace("\r\n", "\n")
        except RecoveryRefused:
            before = ""
        after = checked_path(root, relative).read_text(encoding="utf-8")
        old_pins[relative] = ch.utf8_sha256(before)
        if before != after:
            diffs[relative] = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                         fromfile=commit + "/" + relative, tofile="recovery/" + relative))
    parser = "thesis/evaluation/check_static_repair_readiness.py"
    obligations = {}
    for name, paths in ((OBLIGATIONS[0], [parser]),
                        (OBLIGATIONS[1], [p for p in diffs if p != parser])):
        obligations[name] = dict(exact_diff={p: diffs[p] for p in paths},
                                old_source_sha256=ch.canonical_sha256({p: old_pins[p] for p in paths}),
                                new_source_sha256=ch.canonical_sha256({p: pins[p] for p in paths}),
                                tests=test_evidence)
    proof = dict(schema_version="recovery_equivalence.v1", status="PROVEN", parent_commit=commit,
                 source_pins=pins, unchanged_projection=projection,
                 unchanged_domains={name:dict(old=invariant_sha,new=invariant_sha) for name in DOMAINS},
                 obligations=obligations,
                 scope="NEW_RECOVERY_ONLY; no historical contract or hash replacement")
    proof["proof_sha256"] = ch.canonical_sha256(proof)
    return proof


def source_pins(root, paths):
    if not paths or len(paths) != len(set(paths)):
        raise RecoveryRefused("empty/duplicate recovery source set")
    result = {}
    for relative in sorted(paths):
        value = ch.lf_normalized_sha256(checked_path(root, relative))
        if not value:
            raise RecoveryRefused("missing proof source: " + relative)
        result[relative] = value
    return result


def validate(proof, expected_sha, root, required_sources):
    body = {k: v for k, v in proof.items() if k != "proof_sha256"}
    if (proof.get("schema_version") != "recovery_equivalence.v1"
            or proof.get("status") != "PROVEN"
            or proof.get("proof_sha256") != expected_sha
            or ch.canonical_sha256(body) != expected_sha):
        raise RecoveryRefused("missing/unproven/tampered recovery proof")
    if proof.get("source_pins") != source_pins(root, globals()["required_sources"](root, required_sources)):
        raise RecoveryRefused("recovery proof source set/content drift")
    projection = unchanged_projection(root)
    if projection != proof.get("unchanged_projection"):
        raise RecoveryRefused("unchanged methodology projection differs")
    invariants = proof.get("unchanged_domains", {})
    if set(invariants) != set(DOMAINS):
        raise RecoveryRefused("incomplete recovery methodical invariants")
    for name, value in invariants.items():
        if value.get("old") != ch.canonical_sha256(projection) or value.get("old") != value.get("new"):
            raise RecoveryRefused("methodical domain changed: " + name)
    obligations = proof.get("obligations", {})
    if set(obligations) != set(OBLIGATIONS):
        raise RecoveryRefused("parser and routing need separate proofs")
    for name, obligation in obligations.items():
        if not obligation.get("exact_diff") or not obligation.get("old_source_sha256") or not obligation.get("new_source_sha256"):
            raise RecoveryRefused("unbound change classification: " + name)
        tests = obligation.get("tests", [])
        if not tests:
            raise RecoveryRefused("missing regression evidence: " + name)
        for test in tests:
            path = checked_path(root, test.get("evidence_path"))
            if (test.get("status") != "PASS" or not test.get("evidence_sha256")
                    or not path.is_file() or ch.raw_sha256(path) != test["evidence_sha256"]):
                raise RecoveryRefused("missing/mismatched test evidence")
    return True
