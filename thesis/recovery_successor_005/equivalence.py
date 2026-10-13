"""Phase-2 implementation proof against the methodology ORIGIN commit.

recovery_001 ran at the commit recorded in its own run manifest (8d88ebc,
git_dirty False) with 347 LF-normalised source pins; 002, 003 and 004 ran
on exactly those pins plus one registered routing change. Phase 2 proves:

1. baseline (deep mode): every origin pin reproduces from the Git blob of
   that commit;
2. every origin-pinned file is byte-identical (LF-normalised) in the current
   checkout, EXCEPT the registered routing change of
   pilot_run_contract.build_contract (non-routing AST identical, exact diff
   recorded) - the measurement implementations (static, correctness,
   dynamic, enhanced runners, tools, specs, policy) are therefore exactly the
   ones every historical result was produced by;
3. the phase-2 sources (new package, tests, config) and the reused successor
   helpers are pinned;
4. the methodical configuration (models, generation_defaults, stages,
   prompts) equals the origin's frozen resolved configuration;
5. the bound synthetic test evidence passed, and it contains the
   MEASUREMENT-EQUIVALENCE tests: each phase-2 measurement path produces
   exactly the entry/record of the native runner (static: run_model,
   correctness: run_model's run_sample calls, dynamic: run_model,
   enhanced: process_sample/precompute_gates as main() uses them).

Phase 2 replays no repair decision (it makes none): it only measures.

Python 3.8 compatible.
"""
from __future__ import annotations

import json
import os
import stat
import threading
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation import successor_ast as sa
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path
from thesis.recovery_successor_005 import lineage as pl

SCHEMA = "phase2_equivalence.v1"
METHODICAL_CONFIG_KEYS = ("models", "generation_defaults", "stages", "prompts")
ORIGIN_PROOF_REL = "thesis/evaluation/recovery/full_ext_recovery_001/equivalence.json"
ORIGIN_GLOBAL_FRAGMENT_REL = "thesis/results/intermediate/full_ext_recovery_001/run_manifest.fragments/global.json"

ROUTING_CHANGES = OrderedDict([
    ("thesis/evaluation/pilot_run_contract.py", ("build_contract",)),
])

PHASE2_SOURCES = (
    "thesis/config/recovery_successor_005.yaml",
    "thesis/recovery_successor_005/__init__.py",
    "thesis/recovery_successor_005/composite.py",
    "thesis/recovery_successor_005/contract.py",
    "thesis/recovery_successor_005/equivalence.py",
    "thesis/recovery_successor_005/external.py",
    "thesis/recovery_successor_005/freeze.py",
    "thesis/recovery_successor_005/ledger.py",
    "thesis/recovery_successor_005/lineage.py",
    "thesis/recovery_successor_005/measure_enhanced.py",
    "thesis/recovery_successor_005/measure_runtime.py",
    "thesis/recovery_successor_005/measure_static.py",
    "thesis/recovery_successor_005/plan.py",
    "thesis/recovery_successor_005/preflight.py",
    "thesis/recovery_successor_005/readiness.py",
    "thesis/recovery_successor_005/run.py",
    "thesis/recovery_successor_005/targets.py",
    "thesis/recovery_successor_005/verify.py",
    "thesis/recovery_successor_005/test_authority.py",
    "thesis/recovery_successor_005/test_measure_enhanced.py",
    "thesis/recovery_successor_005/test_measure_runtime.py",
    "thesis/recovery_successor_005/test_measure_static.py",
    "thesis/recovery_successor_005/test_verify.py",
    # reused unchanged: generic successor helpers and the 004 census
    "thesis/evaluation/successor_ast.py",
    "thesis/evaluation/successor_ast_evidence.py",
    "thesis/evaluation/successor_supplement.py",
    "thesis/evaluation/successor_writer.py",
    "thesis/recovery_successor_004/census.py",
)

# test ids (unittest ids, prefix match) that MUST be in the passing evidence:
# the measurement-equivalence obligations of claim 5
EQUIVALENCE_TESTS = OrderedDict([
    ("static", "thesis.recovery_successor_005.test_measure_static"),
    ("correctness", "thesis.recovery_successor_005.test_measure_runtime"),
    ("dynamic", "thesis.recovery_successor_005.test_measure_runtime"),
    ("enhanced", "thesis.recovery_successor_005.test_measure_enhanced"),
])


def _lf_text(data):
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def origin_proof(root, lineage):
    binding = lineage.document["definitions"].get(ORIGIN_PROOF_REL)
    if not binding:
        raise RecoveryRefused("the origin proof is not bound by the phase-2 lineage")
    data = checked_path(Path(root), ORIGIN_PROOF_REL).read_bytes()
    if ch.lf_normalized_sha256_bytes(data) != binding["lf_sha256"]:
        raise RecoveryRefused("origin proof drifted from the phase-2 lineage")
    proof = json.loads(data.decode("utf-8"))
    if proof.get("status") != "PROVEN" or not proof.get("source_pins"):
        raise RecoveryRefused("origin proof is not a proven source pin set")
    return proof


def config_projection(config):
    missing = [key for key in METHODICAL_CONFIG_KEYS if key not in config]
    if missing:
        raise RecoveryRefused("configuration lacks methodical keys: " + ", ".join(missing))
    return OrderedDict((key, ch.canonical_sha256(config[key])) for key in METHODICAL_CONFIG_KEYS)


def origin_config_projection(lineage):
    fragment = json.loads(lineage.protected_bytes(ORIGIN_GLOBAL_FRAGMENT_REL).decode("utf-8"))
    resolved = (fragment.get("content") or {}).get("resolved_config")
    if not isinstance(resolved, dict):
        raise RecoveryRefused("origin frozen resolved configuration is unavailable")
    return config_projection(resolved)


def routing_projection(root, commit, relative, functions, read_blob):
    import difflib

    before = _lf_text(read_blob(str(root), commit, relative))
    after = _lf_text(checked_path(root, relative).read_bytes())
    old_ast = sa.projection_sha256(before, functions)
    new_ast = sa.projection_sha256(after, functions)
    if old_ast != new_ast:
        raise RecoveryRefused("non-routing implementation changed: " + relative)
    diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        fromfile="%s/%s" % (commit, relative),
                                        tofile="phase2/%s" % relative))
    return OrderedDict([
        ("routing_functions", sorted(functions)),
        ("old_lf_sha256", ch.utf8_sha256(before)),
        ("new_lf_sha256", ch.utf8_sha256(after)),
        ("non_routing_ast_sha256", new_ast),
        ("ast_algorithm", sa.VERSION),
        ("exact_diff", diff),
    ])


def source_state(root, origin_pins, commit, read_blob):
    unchanged = OrderedDict()
    changed = OrderedDict()
    for relative in sorted(origin_pins):
        current = ch.lf_normalized_sha256(checked_path(root, relative))
        if current is None:
            raise RecoveryRefused("origin-pinned source is missing: " + relative)
        if current == origin_pins[relative]:
            unchanged[relative] = current
            continue
        if relative not in ROUTING_CHANGES:
            raise RecoveryRefused("unregistered change of an origin-pinned source: " + relative)
        entry = routing_projection(root, commit, relative, ROUTING_CHANGES[relative], read_blob)
        if entry["old_lf_sha256"] != origin_pins[relative] or entry["new_lf_sha256"] != current:
            raise RecoveryRefused("routing change is not anchored at the origin pin: " + relative)
        changed[relative] = entry
    stale = sorted(set(ROUTING_CHANGES) - set(changed))
    if stale:
        raise RecoveryRefused("registered routing change without an actual change: " + ", ".join(stale))
    return unchanged, changed


def phase2_pins(root):
    pins = OrderedDict()
    for relative in PHASE2_SOURCES:
        value = ch.lf_normalized_sha256(checked_path(root, relative))
        if not value:
            raise RecoveryRefused("missing phase-2 source: " + relative)
        pins[relative] = value
    return pins


def baseline_verification(root, origin_pins, commit, read_blob):
    for relative, pin in sorted(origin_pins.items()):
        if ch.utf8_sha256(_lf_text(read_blob(str(root), commit, relative))) != pin:
            raise RecoveryRefused("origin commit does not reproduce pin: " + relative)
    return OrderedDict([("commit", commit), ("verified_source_count", len(origin_pins)),
                        ("source_pins_sha256", ch.canonical_sha256(origin_pins))])


def measurement_equivalence(test_evidence):
    """The equivalence obligations, each covered by passing tests of the
    bound py312 evidence (the measurement modules run in the main image)."""
    py312 = [e for e in test_evidence if e.get("label") == "py312" and e.get("kind") == "unittest"]
    if not py312 or py312[0].get("status") != "PASS":
        raise RecoveryRefused("the measurement-equivalence evidence (py312 unittest) is missing or failing")
    passed = set(py312[0].get("passed_test_modules") or [])
    result = OrderedDict()
    for obligation, module in EQUIVALENCE_TESTS.items():
        if module not in passed:
            raise RecoveryRefused("measurement equivalence %s is not covered by passing tests (%s)"
                                  % (obligation, module))
        result[obligation] = OrderedDict([("module", module), ("status", "PASS"),
                                          ("evidence", py312[0]["evidence_path"])])
    return result


def _default_reader():
    from thesis.evaluation.recovery_historical_source import git_blob
    return git_blob


def build(root, lineage, config, test_evidence, read_blob=None):
    root = Path(root).resolve()
    read_blob = read_blob or _default_reader()
    origin = lineage.origin
    commit = origin["git_commit"]
    if origin.get("git_dirty") is not False:
        raise RecoveryRefused("the origin did not run from a clean commit")
    old = origin_proof(root, lineage)
    pins = old["source_pins"]
    unchanged, changed = source_state(root, pins, commit, read_blob)
    projection = config_projection(config)
    if projection != origin_config_projection(lineage):
        raise RecoveryRefused("phase-2 methodical configuration differs from the origin")
    if not test_evidence or any(t.get("status") != "PASS" for t in test_evidence):
        raise RecoveryRefused("phase-2 test evidence missing or failing")
    proof = OrderedDict([
        ("schema_version", SCHEMA),
        ("status", "PROVEN"),
        ("origin_run_id", pl.ORIGIN),
        ("phase2_run_id", pl.SUCCESSOR),
        ("origin_commit", commit),
        ("origin_proof_sha256", old.get("proof_sha256")),
        ("baseline_verification", baseline_verification(root, pins, commit, read_blob)),
        ("unchanged_source_pins", unchanged),
        ("routing_changes", changed),
        ("phase2_source_pins", phase2_pins(root)),
        ("methodical_config_projection", projection),
        ("ast_algorithm", sa.VERSION),
        ("test_evidence", list(test_evidence)),
        ("measurement_equivalence", measurement_equivalence(test_evidence)),
        ("provider_calls", "NONE"),
        ("scope", "PHASE2_ONLY; origin proof/contract never rebuilt or replaced"),
    ])
    proof["proof_sha256"] = ch.canonical_sha256(OrderedDict(
        (k, v) for k, v in proof.items() if k != "proof_sha256"))
    return proof


def current_source_state(root, origin_pins, routing_changes):
    for relative in sorted(origin_pins):
        current = ch.lf_normalized_sha256(checked_path(root, relative))
        if current is None:
            raise RecoveryRefused("origin-pinned source is missing: " + relative)
        if relative in routing_changes:
            entry = routing_changes[relative]
            text = _lf_text(checked_path(root, relative).read_bytes())
            if (current != entry.get("new_lf_sha256")
                    or sa.projection_sha256(text, tuple(entry.get("routing_functions") or ()))
                    != entry.get("non_routing_ast_sha256")):
                raise RecoveryRefused("routing change drifted from the proof: " + relative)
        elif current != origin_pins[relative]:
            raise RecoveryRefused("unregistered change of an origin-pinned source: " + relative)
    if set(routing_changes) != set(ROUTING_CHANGES):
        raise RecoveryRefused("proof routing set differs from the registered routing changes")
    return True


_FAST_LOCK = threading.Lock()
_FAST_VERIFIED = {}


def _file_stats(root, relatives):
    result = []
    for relative in relatives:
        if not isinstance(relative, str) or not relative:
            raise RecoveryRefused("invalid pinned path")
        try:
            info = os.lstat(os.path.join(str(root), relative))
        except OSError:
            raise RecoveryRefused("pinned file is missing: " + relative)
        if stat.S_ISLNK(info.st_mode):
            raise RecoveryRefused("pinned file is a link: " + relative)
        result.append((relative, info.st_size, info.st_mtime_ns))
    return tuple(result)


def validate(proof, root, lineage, config, read_blob=None, deep=False):
    """Fast (git-free, stat-guarded) re-validation used by every contract
    rebuild and every tool container; deep re-derives the routing entries
    and the baseline from the origin commit's Git blobs."""
    root = Path(root).resolve()
    body = OrderedDict((k, v) for k, v in proof.items() if k != "proof_sha256")
    if (proof.get("schema_version") != SCHEMA or proof.get("status") != "PROVEN"
            or ch.canonical_sha256(body) != proof.get("proof_sha256")
            or proof.get("phase2_run_id") != pl.SUCCESSOR
            or proof.get("origin_commit") != lineage.origin["git_commit"]
            or proof.get("ast_algorithm") != sa.VERSION
            or proof.get("provider_calls") != "NONE"):
        raise RecoveryRefused("missing/unproven/tampered phase-2 proof")
    old = origin_proof(root, lineage)
    if proof.get("origin_proof_sha256") != old.get("proof_sha256"):
        raise RecoveryRefused("phase-2 proof is bound to another origin proof")
    pins = old["source_pins"]
    expected_unchanged = OrderedDict((k, v) for k, v in sorted(pins.items())
                                     if k not in (proof.get("routing_changes") or {}))
    if expected_unchanged != proof.get("unchanged_source_pins"):
        raise RecoveryRefused("phase-2 proof does not cover the origin pin set")
    if (config_projection(config) != proof.get("methodical_config_projection")
            or proof.get("methodical_config_projection") != origin_config_projection(lineage)):
        raise RecoveryRefused("methodical configuration drifted")
    if not proof.get("test_evidence"):
        raise RecoveryRefused("phase-2 proof carries no test evidence")
    if measurement_equivalence(proof["test_evidence"]) != proof.get("measurement_equivalence"):
        raise RecoveryRefused("phase-2 proof carries no passing measurement equivalence")
    files = (sorted(pins) + list(PHASE2_SOURCES)
             + [test.get("evidence_path") for test in proof["test_evidence"]])
    key = (str(root), proof["proof_sha256"], lineage.sha256)
    stats = None if deep else _file_stats(root, files)
    if stats is None or _FAST_VERIFIED.get(key) != stats:
        current_source_state(root, pins, proof.get("routing_changes") or {})
        if phase2_pins(root) != proof.get("phase2_source_pins"):
            raise RecoveryRefused("phase-2 source pins drifted")
        for test in proof["test_evidence"]:
            path = checked_path(root, test.get("evidence_path"))
            if (test.get("status") != "PASS" or not path.is_file()
                    or ch.lf_normalized_sha256(path) != test.get("evidence_lf_sha256")):
                raise RecoveryRefused("missing/mismatched phase-2 test evidence")
        if stats is not None:
            with _FAST_LOCK:
                _FAST_VERIFIED[key] = stats
    if deep:
        read_blob = read_blob or _default_reader()
        unchanged, changed = source_state(root, pins, proof["origin_commit"], read_blob)
        if unchanged != proof.get("unchanged_source_pins") or changed != proof.get("routing_changes"):
            raise RecoveryRefused("phase-2 source state differs from the proof (deep)")
        if baseline_verification(root, pins, proof["origin_commit"], read_blob) != proof.get(
                "baseline_verification"):
            raise RecoveryRefused("baseline verification differs")
    return True
