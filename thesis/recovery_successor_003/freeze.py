"""Build and freeze the successor definitions (before the first start ONLY).

    python -B -m thesis.recovery_successor_003.freeze lineage --write   (main container)
    python -B -m thesis.recovery_successor_003.freeze tests --label py38|py311|py312 --write
                                               (each pinned interpreter)
    python -B -m thesis.recovery_successor_003.freeze ast --label py38|py312 --write
    python -B -m thesis.recovery_successor_003.freeze equivalence --write   (git blobs)
    python -B -m thesis.recovery_successor_003.readiness --write  (docker socket, .env)
    python -B -m thesis.recovery_successor_003.freeze contract --write

Every step refuses once the successor run carries any state (FRESH gate:
nothing of full_ext_recovery_002 may exist before its T0) and writes only
into thesis/evaluation/recovery/full_ext_recovery_002. Nothing here
authorizes, measures or calls a provider; the predecessor definitions are
only read.

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import io
import json
import platform
import sys
import unittest
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import condition_hashing as ch  # noqa: E402
from thesis.recovery_successor_003 import lineage as sl  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402

TEST_SCHEMA = "successor_test_evidence.v1"
TEST_MODULES = ("thesis.recovery_successor_003.test_handoff",
                "thesis.recovery_successor_003.test_routing")
# pinned interpreters: LLOV image (supplements), PARCOACH image (native
# iteration-2 runs), main image (driver, loops, verification)
REQUIRED_LABELS = ("py38", "py312")
OPTIONAL_LABELS = ("py311",)
AST_EVIDENCE = ("ast_python38.json", "ast_python312.json")


def definitions(root=REPO_ROOT):
    return Path(root) / sl.DEFINITIONS_REL


def successor_state(root, config):
    """Every path that would make the successor non-FRESH (empty = FRESH)."""
    from thesis.evaluation import run_freshness
    from thesis.evaluation import successor_writer as sw

    found = []
    freshness = run_freshness.inspect_run_freshness(config, sl.SUCCESSOR)
    if freshness["status"] != run_freshness.FRESH:
        found.extend(freshness["result_bearing_paths"] + freshness["problems"])
    for area in ("raw", "intermediate"):
        base = Path(root) / "thesis/results" / area
        if base.is_dir():
            for run in base.iterdir():
                if run.name == sl.SUCCESSOR or run.name.startswith(sl.SUCCESSOR + "__"):
                    found.extend(p.relative_to(root).as_posix() for p in run.rglob("*") if p.is_file())
    lock = sw.lock_path(root, sl.SUCCESSOR)
    if lock.exists():
        found.append(lock.relative_to(root).as_posix())
    return sorted(set(found))


def require_fresh(root, config):
    state = successor_state(root, config)
    if state:
        raise RecoveryRefused("the successor already carries state; its definitions are frozen: %s"
                              % ", ".join(state[:5]))


def write_json(path, document):
    from thesis.evaluation import atomic_io

    atomic_io.atomic_write_json(Path(path), document)


# -- steps -------------------------------------------------------------------

def step_lineage(root, config):
    document = sl.build(root, config)
    loaded = sl.SuccessorLineage(root, json.loads(json.dumps(document), object_pairs_hook=OrderedDict),
                                 document["lineage_sha256"])
    loaded.verify(config, deep=True)
    return definitions(root) / "lineage.json", document


def step_tests(root, label):
    from thesis.recovery_successor_003 import equivalence as se

    pins_before = se.successor_pins(root)
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames(list(TEST_MODULES))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    pins_after = se.successor_pins(root)
    if pins_after != pins_before:
        raise RecoveryRefused("successor sources changed while the tests ran")
    passed = result.wasSuccessful() and result.testsRun > 0
    output = stream.getvalue()
    document = OrderedDict([
        ("schema_version", TEST_SCHEMA),
        ("label", label),
        ("status", "PASS" if passed else "FAIL"),
        ("python", platform.python_version()),
        ("executable", sys.executable),
        ("modules", list(TEST_MODULES)),
        ("tests_run", result.testsRun),
        ("failures", len(result.failures)),
        ("errors", len(result.errors)),
        ("skipped", [str(test) for test, _reason in result.skipped]),
        ("successor_source_pins", pins_after),
        ("routing_change_lf_sha256", OrderedDict(
            (relative, ch.lf_normalized_sha256(checked_path(root, relative)))
            for relative in se.ROUTING_CHANGES)),
        ("runner_output_sha256", ch.utf8_sha256(output)),
        ("runner_output_tail", output[-4000:]),
        ("scope", "SYNTHETIC_ONLY: mock provider, mock tools, temporary worlds; no productive "
                  "authorization, analysis or provider request"),
    ])
    document["evidence_sha256"] = ch.canonical_sha256(OrderedDict(
        (k, v) for k, v in document.items() if k != "evidence_sha256"))
    return definitions(root) / ("test_evidence_%s.json" % label), document


def step_ast(root, label):
    """AST-only compatibility evidence of successor_ast.index_v1 under one
    pinned interpreter (successor_ast_evidence, reused unchanged)."""
    from thesis.evaluation import successor_ast_evidence

    document = successor_ast_evidence.verify(root)
    name = "ast_python38.json" if label == "py38" else "ast_python312.json"
    return definitions(root) / name, document


def evidence_entries(root):
    """Proof entries of every present test / AST evidence; required labels must exist."""
    from thesis.recovery_successor_003 import equivalence as se

    pins = se.successor_pins(root)
    entries = []
    for label in REQUIRED_LABELS + OPTIONAL_LABELS:
        relative = "%s/test_evidence_%s.json" % (sl.DEFINITIONS_REL, label)
        path = checked_path(root, relative)
        if not path.is_file():
            if label in REQUIRED_LABELS:
                raise RecoveryRefused("missing required test evidence " + relative)
            continue
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
        body = OrderedDict((k, v) for k, v in document.items() if k != "evidence_sha256")
        routing = dict((relative, ch.lf_normalized_sha256(checked_path(root, relative)))
                       for relative in se.ROUTING_CHANGES)
        if (document.get("schema_version") != TEST_SCHEMA or document.get("status") != "PASS"
                or ch.canonical_sha256(body) != document.get("evidence_sha256")
                or document.get("successor_source_pins") != pins
                or dict(document.get("routing_change_lf_sha256") or {}) != routing):
            raise RecoveryRefused("test evidence %s is failing, tampered or ran against other "
                                  "sources / routing bytes" % label)
        entries.append(OrderedDict([
            ("label", label), ("kind", "unittest"), ("status", "PASS"),
            ("python", document["python"]), ("tests_run", document["tests_run"]),
            ("evidence_path", relative), ("evidence_lf_sha256", ch.lf_normalized_sha256(path)),
            ("evidence_sha256", document["evidence_sha256"])]))
    from thesis.evaluation import successor_ast_evidence  # noqa: F401 - pinned audit module

    for name in AST_EVIDENCE:
        relative = "%s/%s" % (sl.DEFINITIONS_REL, name)
        path = checked_path(root, relative)
        document = json.loads(path.read_text(encoding="utf-8"))
        body = {k: v for k, v in document.items() if k != "evidence_sha256"}
        current = {p: ch.raw_sha256(checked_path(root, p)) for p in document.get("source_pins") or {}}
        if (document.get("status") != "PASS" or ch.canonical_sha256(body) != document.get("evidence_sha256")
                or current != document.get("source_pins")):
            raise RecoveryRefused("AST evidence %s is failing, tampered or stale" % name)
        entries.append(OrderedDict([
            ("label", name.replace(".json", "")), ("kind", "ast_projection"), ("status", "PASS"),
            ("python", document["python"]), ("evidence_path", relative),
            ("evidence_lf_sha256", ch.lf_normalized_sha256(path)),
            ("evidence_sha256", document["evidence_sha256"])]))
    return entries


def step_equivalence(root, config):
    from thesis.recovery_successor_003 import equivalence as se

    lineage = sl.load(root)
    lineage.verify(config)
    proof = se.build(root, lineage, config, evidence_entries(root))
    se.validate(proof, root, lineage, config, deep=True)
    return definitions(root) / "equivalence.json", proof


def step_contract(root, config_path):
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.recovery_successor_003 import contract as sc

    contract = sc.build(config_path, sl.SUCCESSOR, root=root, writer_check=False)
    again = sc.build(config_path, sl.SUCCESSOR, root=root, writer_check=False)
    if contract["contract_sha256"] != again["contract_sha256"]:
        raise RecoveryRefused("the successor contract does not rebuild deterministically")
    if contract.get("status") != prc.STATUS_READY:
        raise RecoveryRefused("the successor contract is not READY")
    return sc.frozen_path(root), contract


def main(argv=None):
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("lineage", "tests", "ast", "equivalence", "contract"))
    parser.add_argument("--config", default=sl.CONFIG_REL)
    parser.add_argument("--label", choices=REQUIRED_LABELS + OPTIONAL_LABELS)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = REPO_ROOT
    config_path = (root / args.config).resolve()
    config = load_config(config_path)
    require_fresh(root, config)
    if args.step == "lineage":
        path, document = step_lineage(root, config)
        summary = OrderedDict([("lineage_sha256", document["lineage_sha256"]),
                               ("snapshot_files", len(document["predecessor_snapshot"]["files"])),
                               ("snapshot_sha256", document["predecessor_snapshot"]["snapshot_sha256"])])
    elif args.step == "tests":
        if not args.label:
            raise RecoveryRefused("--label is required for the tests step")
        path, document = step_tests(root, args.label)
        summary = OrderedDict((k, document[k]) for k in ("label", "status", "python", "tests_run",
                                                         "failures", "errors", "skipped"))
    elif args.step == "ast":
        if args.label not in ("py38", "py312"):
            raise RecoveryRefused("--label py38|py312 is required for the ast step")
        path, document = step_ast(root, args.label)
        summary = OrderedDict((k, document[k]) for k in ("status", "python", "evidence_sha256"))
    elif args.step == "equivalence":
        path, document = step_equivalence(root, config)
        summary = OrderedDict([("proof_sha256", document["proof_sha256"]),
                               ("unchanged_source_pins", len(document["unchanged_source_pins"])),
                               ("routing_changes", list(document["routing_changes"])),
                               ("test_evidence", [e["label"] for e in document["test_evidence"]])])
    else:
        path, document = step_contract(root, config_path)
        summary = OrderedDict([("contract_sha256", document["contract_sha256"]),
                               ("status", document["status"]), ("model_ids", document["model_ids"])])
    require_fresh(root, config)
    if args.write:
        if args.step == "contract":
            from thesis.evaluation import pilot_run_contract as prc

            sha = prc.freeze_contract(document, path)
            if prc.load_frozen(path)["contract_sha256"] != sha:
                raise RecoveryRefused("frozen contract read-back mismatch")
        else:
            write_json(path, document)
        summary["written"] = Path(path).relative_to(root).as_posix()
    print(json.dumps(summary, indent=2))
    return 0 if args.step != "tests" or document["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
