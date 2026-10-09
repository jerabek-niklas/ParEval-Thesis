"""Successor implementation proof against the PREDECESSOR run commit.

recovery_001 ran at the commit recorded in its own run manifest (8d88ebc,
git_dirty False) with 347 LF-normalised source pins. The successor proves:

1. baseline (deep mode): every predecessor pin reproduces from the Git blob
   of that commit, i.e. the predecessor results were produced by exactly the
   pinned code;
2. every predecessor-pinned file is byte-identical (LF-normalised) in the
   current checkout, EXCEPT the explicitly registered routing changes, whose
   non-routing AST (successor_ast.index_v1, Python 3.8 + 3.12 stable) is
   identical to the baseline blob and whose exact diff is recorded;
3. the successor's own sources (new modules, tests, config) are pinned;
4. the methodical configuration (models, generation_defaults, stages,
   prompts) equals the predecessor's frozen resolved configuration;
5. the bound synthetic test evidence passed under both pinned interpreters.

The predecessor proof (equivalence.json of recovery_001) is never rebuilt or
replaced; it is an input bound by raw sha256 through the successor lineage.

Python 3.8 compatible.
"""
from __future__ import annotations

import difflib
import json
import os
import stat
import threading
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation import successor_ast as sa
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path

SCHEMA = "successor_equivalence.v1"
METHODICAL_CONFIG_KEYS = ("models", "generation_defaults", "stages", "prompts")

# Pinned predecessor files whose CONTROL-PLANE routing the successor changes.
# Everything outside the named functions must keep its baseline AST.
ROUTING_CHANGES = OrderedDict([
    ("thesis/evaluation/pilot_run_contract.py", ("build_contract",)),
])

SUCCESSOR_SOURCES = (
    "thesis/config/recovery_successor.yaml",
    "thesis/evaluation/successor_ast.py",
    "thesis/evaluation/successor_ast_evidence.py",
    "thesis/evaluation/successor_contract.py",
    "thesis/evaluation/successor_equivalence.py",
    "thesis/evaluation/successor_external.py",
    "thesis/evaluation/successor_freeze.py",
    "thesis/evaluation/successor_handoff.py",
    "thesis/evaluation/successor_lineage.py",
    "thesis/evaluation/successor_preflight.py",
    "thesis/evaluation/successor_readiness.py",
    "thesis/evaluation/successor_supplement.py",
    "thesis/evaluation/successor_writer.py",
    "thesis/evaluation/test_successor_infrastructure.py",
    "thesis/evaluation/verify_successor_run.py",
    "thesis/repair/run_successor.py",
    "thesis/repair/successor_routing.py",
    "thesis/repair/test_successor_routing.py",
)


def _lf_text(data):
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def predecessor_proof(root, lineage):
    binding = lineage.document["predecessor"]["definitions"]["equivalence.json"]
    data = checked_path(root, binding["path"]).read_bytes()
    if ch.lf_normalized_sha256_bytes(data) != binding["lf_sha256"]:
        raise RecoveryRefused("predecessor proof drifted from the successor lineage")
    proof = json.loads(data.decode("utf-8"))
    if proof.get("status") != "PROVEN" or not proof.get("source_pins"):
        raise RecoveryRefused("predecessor proof is not a proven source pin set")
    return proof


def config_projection(config):
    missing = [key for key in METHODICAL_CONFIG_KEYS if key not in config]
    if missing:
        raise RecoveryRefused("configuration lacks methodical keys: " + ", ".join(missing))
    return OrderedDict((key, ch.canonical_sha256(config[key])) for key in METHODICAL_CONFIG_KEYS)


def predecessor_config_projection(lineage):
    view = lineage.view
    fragment = view.read_json(
        "thesis/results/intermediate/%s/run_manifest.fragments/global.json"
        % lineage.document["predecessor_run_id"])
    resolved = (fragment.get("content") or {}).get("resolved_config")
    if not isinstance(resolved, dict):
        raise RecoveryRefused("predecessor frozen resolved configuration is unavailable")
    return config_projection(resolved)


def routing_projection(root, commit, relative, functions, read_blob):
    before = _lf_text(read_blob(str(root), commit, relative))
    after = _lf_text(checked_path(root, relative).read_bytes())
    old_ast = sa.projection_sha256(before, functions)
    new_ast = sa.projection_sha256(after, functions)
    if old_ast != new_ast:
        raise RecoveryRefused("non-routing implementation changed: " + relative)
    diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        fromfile="%s/%s" % (commit, relative),
                                        tofile="successor/%s" % relative))
    return OrderedDict([
        ("routing_functions", sorted(functions)),
        ("old_lf_sha256", ch.utf8_sha256(before)),
        ("new_lf_sha256", ch.utf8_sha256(after)),
        ("non_routing_ast_sha256", new_ast),
        ("ast_algorithm", sa.VERSION),
        ("exact_diff", diff),
    ])


def source_state(root, predecessor_pins, commit, read_blob):
    unchanged = OrderedDict()
    changed = OrderedDict()
    for relative in sorted(predecessor_pins):
        current = ch.lf_normalized_sha256(checked_path(root, relative))
        if current is None:
            raise RecoveryRefused("predecessor-pinned source is missing: " + relative)
        if current == predecessor_pins[relative]:
            unchanged[relative] = current
            continue
        if relative not in ROUTING_CHANGES:
            raise RecoveryRefused("unregistered change of a predecessor-pinned source: " + relative)
        entry = routing_projection(root, commit, relative, ROUTING_CHANGES[relative], read_blob)
        if entry["old_lf_sha256"] != predecessor_pins[relative] or entry["new_lf_sha256"] != current:
            raise RecoveryRefused("routing change is not anchored at the predecessor pin: " + relative)
        changed[relative] = entry
    stale = sorted(set(ROUTING_CHANGES) - set(changed))
    if stale:
        raise RecoveryRefused("registered routing change without an actual change: " + ", ".join(stale))
    return unchanged, changed


def successor_pins(root):
    pins = OrderedDict()
    for relative in SUCCESSOR_SOURCES:
        value = ch.lf_normalized_sha256(checked_path(root, relative))
        if not value:
            raise RecoveryRefused("missing successor source: " + relative)
        pins[relative] = value
    return pins


def baseline_verification(root, predecessor_pins, commit, read_blob):
    """Deep: every predecessor pin reproduces from the predecessor commit."""
    for relative, pin in sorted(predecessor_pins.items()):
        if ch.utf8_sha256(_lf_text(read_blob(str(root), commit, relative))) != pin:
            raise RecoveryRefused("predecessor commit does not reproduce pin: " + relative)
    return OrderedDict([("commit", commit), ("verified_source_count", len(predecessor_pins)),
                        ("source_pins_sha256", ch.canonical_sha256(predecessor_pins))])


def _default_reader():
    from thesis.evaluation.recovery_historical_source import git_blob
    return git_blob


def build(root, lineage, config, test_evidence, read_blob=None):
    """Build the proof (never persists). test_evidence: list of bound runs."""
    root = Path(root).resolve()
    read_blob = read_blob or _default_reader()
    predecessor = lineage.document["predecessor"]
    commit = predecessor["git_commit"]
    if predecessor.get("git_dirty") is not False:
        raise RecoveryRefused("the predecessor did not run from a clean commit")
    old = predecessor_proof(root, lineage)
    pins = old["source_pins"]
    unchanged, changed = source_state(root, pins, commit, read_blob)
    projection = config_projection(config)
    if projection != predecessor_config_projection(lineage):
        raise RecoveryRefused("successor methodical configuration differs from the predecessor")
    if not test_evidence or any(t.get("status") != "PASS" for t in test_evidence):
        raise RecoveryRefused("successor test evidence missing or failing")
    proof = OrderedDict([
        ("schema_version", SCHEMA),
        ("status", "PROVEN"),
        ("predecessor_run_id", lineage.document["predecessor_run_id"]),
        ("successor_run_id", lineage.document["run_id"]),
        ("predecessor_commit", commit),
        ("predecessor_proof_sha256", old.get("proof_sha256")),
        ("baseline_verification", baseline_verification(root, pins, commit, read_blob)),
        ("unchanged_source_pins", unchanged),
        ("routing_changes", changed),
        ("successor_source_pins", successor_pins(root)),
        ("methodical_config_projection", projection),
        ("ast_algorithm", sa.VERSION),
        ("test_evidence", list(test_evidence)),
        ("scope", "SUCCESSOR_ONLY; predecessor proof/contract never rebuilt or replaced"),
    ])
    proof["proof_sha256"] = ch.canonical_sha256(OrderedDict(
        (k, v) for k, v in proof.items() if k != "proof_sha256"))
    return proof


def current_source_state(root, predecessor_pins, routing_changes):
    """Git-free check of the CURRENT side (every contract rebuild, every
    container): unchanged pins reproduce; each registered routing file has
    its recorded new LF sha and its recorded non-routing AST."""
    for relative in sorted(predecessor_pins):
        current = ch.lf_normalized_sha256(checked_path(root, relative))
        if current is None:
            raise RecoveryRefused("predecessor-pinned source is missing: " + relative)
        if relative in routing_changes:
            entry = routing_changes[relative]
            text = _lf_text(checked_path(root, relative).read_bytes())
            if (current != entry.get("new_lf_sha256")
                    or sa.projection_sha256(text, tuple(entry.get("routing_functions") or ()))
                    != entry.get("non_routing_ast_sha256")):
                raise RecoveryRefused("routing change drifted from the proof: " + relative)
        elif current != predecessor_pins[relative]:
            raise RecoveryRefused("unregistered change of a predecessor-pinned source: " + relative)
    if set(routing_changes) != set(ROUTING_CHANGES):
        raise RecoveryRefused("proof routing set differs from the registered routing changes")
    return True


# Fast re-validation (every contract rebuild: every step, every provider
# call) re-hashes the pinned sources whenever any of them changed size,
# mtime or link status since the last full hash in this process.
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
    """Fast (git-free) re-validation used by every contract rebuild and every
    tool container; deep additionally re-derives the routing entries and the
    baseline from the predecessor commit's Git blobs."""
    root = Path(root).resolve()
    body = OrderedDict((k, v) for k, v in proof.items() if k != "proof_sha256")
    if (proof.get("schema_version") != SCHEMA or proof.get("status") != "PROVEN"
            or ch.canonical_sha256(body) != proof.get("proof_sha256")
            or proof.get("successor_run_id") != lineage.document["run_id"]
            or proof.get("predecessor_commit") != lineage.document["predecessor"]["git_commit"]
            or proof.get("ast_algorithm") != sa.VERSION):
        raise RecoveryRefused("missing/unproven/tampered successor proof")
    old = predecessor_proof(root, lineage)
    if proof.get("predecessor_proof_sha256") != old.get("proof_sha256"):
        raise RecoveryRefused("successor proof is bound to another predecessor proof")
    pins = old["source_pins"]
    expected_unchanged = OrderedDict((k, v) for k, v in sorted(pins.items())
                                     if k not in (proof.get("routing_changes") or {}))
    if expected_unchanged != proof.get("unchanged_source_pins"):
        raise RecoveryRefused("successor proof does not cover the predecessor pin set")
    if (config_projection(config) != proof.get("methodical_config_projection")
            or proof.get("methodical_config_projection") != predecessor_config_projection(lineage)):
        raise RecoveryRefused("methodical configuration drifted")
    if not proof.get("test_evidence"):
        raise RecoveryRefused("successor proof carries no test evidence")
    files = (sorted(pins) + list(SUCCESSOR_SOURCES)
             + [test.get("evidence_path") for test in proof["test_evidence"]])
    key = (str(root), proof["proof_sha256"], lineage.sha256)
    stats = None if deep else _file_stats(root, files)
    if stats is None or _FAST_VERIFIED.get(key) != stats:
        current_source_state(root, pins, proof.get("routing_changes") or {})
        if successor_pins(root) != proof.get("successor_source_pins"):
            raise RecoveryRefused("successor source pins drifted")
        for test in proof["test_evidence"]:
            path = checked_path(root, test.get("evidence_path"))
            # LF-normalised: a version-controlled definition must survive autocrlf
            if (test.get("status") != "PASS" or not path.is_file()
                    or ch.lf_normalized_sha256(path) != test.get("evidence_lf_sha256")):
                raise RecoveryRefused("missing/mismatched successor test evidence")
        if stats is not None:
            with _FAST_LOCK:
                _FAST_VERIFIED[key] = stats
    if deep:
        read_blob = read_blob or _default_reader()
        unchanged, changed = source_state(root, pins, proof["predecessor_commit"], read_blob)
        if unchanged != proof.get("unchanged_source_pins") or changed != proof.get("routing_changes"):
            raise RecoveryRefused("successor source state differs from the proof (deep)")
        if baseline_verification(root, pins, proof["predecessor_commit"],
                                 read_blob) != proof.get("baseline_verification"):
            raise RecoveryRefused("baseline verification differs")
    return True
