"""Build and freeze the phase-2 definitions (before the first start ONLY).

    python -B -m thesis.recovery_successor_005.freeze targets --write      (main container)
    python -B -m thesis.recovery_successor_005.freeze lineage --write      (main container)
    python -B -m thesis.recovery_successor_005.freeze tests --label py38|py311|py312 --write
    python -B -m thesis.recovery_successor_005.freeze ast --label py38|py312 --write
    python -B -m thesis.recovery_successor_005.freeze equivalence --write  (git blobs)
    python -B -m thesis.recovery_successor_005.readiness --write           (docker socket)
    python -B -m thesis.recovery_successor_005.freeze contract --write

Every step refuses once the phase-2 run carries any state (FRESH gate) and
writes only into thesis/evaluation/recovery/full_ext_phase2_001. Nothing
here authorizes, measures or calls a provider; every historical artifact is
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
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402

TEST_SCHEMA = "phase2_test_evidence.v1"
ALL_TEST_MODULES = ("thesis.recovery_successor_005.test_authority",
                    "thesis.recovery_successor_005.test_measure_static",
                    "thesis.recovery_successor_005.test_measure_runtime",
                    "thesis.recovery_successor_005.test_measure_enhanced",
                    "thesis.recovery_successor_005.test_verify")
# the tool images import only the container side (lineage/targets/ledger/
# contract/equivalence/external): their interpreters run that subset
CONTAINER_TEST_MODULES = ("thesis.recovery_successor_005.test_authority",
                          "thesis.recovery_successor_005.test_measure_static")
TEST_MODULES = OrderedDict([("py312", ALL_TEST_MODULES), ("py38", CONTAINER_TEST_MODULES),
                            ("py311", CONTAINER_TEST_MODULES)])
REQUIRED_LABELS = ("py312", "py38", "py311")
LABEL_PYTHON = {"py38": "3.8", "py311": "3.11", "py312": "3.12"}
AST_EVIDENCE = ("ast_python38.json", "ast_python312.json")


def label_matches(label, python_version):
    return ".".join(str(python_version).split(".")[:2]) == LABEL_PYTHON.get(label)


def definitions(root=REPO_ROOT):
    return Path(root) / pl.DEFINITIONS_REL


def phase2_state(root, config):
    """Every path that would make the phase-2 run non-FRESH (empty = FRESH)."""
    from thesis.evaluation import run_freshness
    from thesis.evaluation import successor_writer as sw

    found = []
    freshness = run_freshness.inspect_run_freshness(config, pl.SUCCESSOR)
    if freshness["status"] != run_freshness.FRESH:
        found.extend(freshness["result_bearing_paths"] + freshness["problems"])
    for area in ("raw", "intermediate"):
        base = Path(root) / "thesis/results" / area
        if base.is_dir():
            for run in base.iterdir():
                if run.name == pl.SUCCESSOR or run.name.startswith(pl.SUCCESSOR + "__"):
                    found.extend(p.relative_to(root).as_posix() for p in run.rglob("*") if p.is_file())
    lock = sw.lock_path(root, pl.SUCCESSOR)
    if lock.exists():
        found.append(lock.relative_to(root).as_posix())
    return sorted(set(found))


def require_fresh(root, config):
    state = phase2_state(root, config)
    if state:
        raise RecoveryRefused("the phase-2 run already carries state; its definitions are frozen: %s"
                              % ", ".join(state[:5]))


def write_json(path, document):
    from thesis.evaluation import atomic_io

    atomic_io.atomic_write_json(Path(path), document)


# -- steps -------------------------------------------------------------------

def step_targets(root):
    from thesis.recovery_successor_005 import targets as pt

    document = pt.build_table(root)
    again = pt.build_table(root)
    if again["table_sha256"] != document["table_sha256"]:
        raise RecoveryRefused("the target table does not build deterministically")
    pt.TargetTable(root, json.loads(json.dumps(document), object_pairs_hook=OrderedDict),
                   document["table_sha256"])
    return definitions(root) / "targets.json", document


def step_lineage(root):
    from thesis.recovery_successor_005 import targets as pt

    table = pt.load_table(root)
    document = pl.build(root, table.sha256, table.document["census_digest"])
    loaded = pl.PhaseLineage(root, json.loads(json.dumps(document), object_pairs_hook=OrderedDict),
                             document["lineage_sha256"])
    loaded.verify()
    return definitions(root) / "lineage.json", document


def _module_of(test_id):
    parts = test_id.split(".")
    return ".".join(parts[:3]) if len(parts) >= 3 else test_id


def step_tests(root, label):
    from thesis.recovery_successor_005 import equivalence as pe

    if not label_matches(label, platform.python_version()):
        raise RecoveryRefused("label %s does not name this interpreter (%s)" % (label, platform.python_version()))
    modules = list(TEST_MODULES[label])
    pins_before = pe.phase2_pins(root)
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    test_ids = []

    def collect(item):
        if isinstance(item, unittest.TestSuite):
            for child in item:
                collect(child)
        else:
            test_ids.append(item.id())

    collect(suite)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    pins_after = pe.phase2_pins(root)
    if pins_after != pins_before:
        raise RecoveryRefused("phase-2 sources changed while the tests ran")
    bad = set(test.id() for test, _ in result.failures + result.errors)
    per_module = OrderedDict()
    for test_id in test_ids:
        bucket = per_module.setdefault(_module_of(test_id), [0, 0])
        bucket[0] += 1
        if test_id not in bad:
            bucket[1] += 1
    passed_modules = [m for m in modules if m in per_module and per_module[m][0] == per_module[m][1]
                      and per_module[m][0] > 0]
    passed = result.wasSuccessful() and result.testsRun > 0 and passed_modules == modules
    output = stream.getvalue()
    document = OrderedDict([
        ("schema_version", TEST_SCHEMA),
        ("label", label),
        ("status", "PASS" if passed else "FAIL"),
        ("python", platform.python_version()),
        ("executable", sys.executable),
        ("modules", modules),
        ("tests_run", result.testsRun),
        ("failures", len(result.failures)),
        ("errors", len(result.errors)),
        ("skipped", [str(test) for test, _reason in result.skipped]),
        ("tests_per_module", OrderedDict((m, c[0]) for m, c in per_module.items())),
        ("passed_test_modules", passed_modules),
        ("phase2_source_pins", pins_after),
        ("routing_change_lf_sha256", OrderedDict(
            (relative, ch.lf_normalized_sha256(checked_path(root, relative)))
            for relative in pe.ROUTING_CHANGES)),
        ("runner_output_sha256", ch.utf8_sha256(output)),
        ("runner_output_tail", output[-4000:]),
        ("scope", "SYNTHETIC_ONLY: stub tools, temporary worlds; no productive authorization, "
                  "measurement or provider request"),
    ])
    document["evidence_sha256"] = ch.canonical_sha256(OrderedDict(
        (k, v) for k, v in document.items() if k != "evidence_sha256"))
    return definitions(root) / ("test_evidence_%s.json" % label), document


def step_ast(root, label):
    from thesis.evaluation import successor_ast_evidence

    if not label_matches(label, platform.python_version()):
        raise RecoveryRefused("label %s does not name this interpreter (%s)" % (label, platform.python_version()))
    document = successor_ast_evidence.verify(root)
    name = "ast_python38.json" if label == "py38" else "ast_python312.json"
    return definitions(root) / name, document


def evidence_entries(root):
    from thesis.recovery_successor_005 import equivalence as pe

    pins = pe.phase2_pins(root)
    entries = []
    for label in REQUIRED_LABELS:
        relative = "%s/test_evidence_%s.json" % (pl.DEFINITIONS_REL, label)
        path = checked_path(root, relative)
        if not path.is_file():
            raise RecoveryRefused("missing required test evidence " + relative)
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
        body = OrderedDict((k, v) for k, v in document.items() if k != "evidence_sha256")
        routing = dict((relative_, ch.lf_normalized_sha256(checked_path(root, relative_)))
                       for relative_ in pe.ROUTING_CHANGES)
        if (document.get("schema_version") != TEST_SCHEMA or document.get("status") != "PASS"
                or not label_matches(label, document.get("python"))
                or document.get("modules") != list(TEST_MODULES[label])
                or ch.canonical_sha256(body) != document.get("evidence_sha256")
                or document.get("phase2_source_pins") != pins
                or dict(document.get("routing_change_lf_sha256") or {}) != routing):
            raise RecoveryRefused("test evidence %s is failing, tampered or ran against other "
                                  "sources / routing bytes" % label)
        entries.append(OrderedDict([
            ("label", label), ("kind", "unittest"), ("status", "PASS"),
            ("python", document["python"]), ("tests_run", document["tests_run"]),
            ("passed_test_modules", list(document["passed_test_modules"])),
            ("evidence_path", relative), ("evidence_lf_sha256", ch.lf_normalized_sha256(path)),
            ("evidence_sha256", document["evidence_sha256"])]))
    for name in AST_EVIDENCE:
        relative = "%s/%s" % (pl.DEFINITIONS_REL, name)
        path = checked_path(root, relative)
        document = json.loads(path.read_text(encoding="utf-8"))
        body = {k: v for k, v in document.items() if k != "evidence_sha256"}
        current = {p: ch.raw_sha256(checked_path(root, p)) for p in document.get("source_pins") or {}}
        expected_label = "py38" if name == "ast_python38.json" else "py312"
        if (document.get("status") != "PASS" or ch.canonical_sha256(body) != document.get("evidence_sha256")
                or not label_matches(expected_label, document.get("python"))
                or current != document.get("source_pins")):
            raise RecoveryRefused("AST evidence %s is failing, tampered or stale" % name)
        entries.append(OrderedDict([
            ("label", name.replace(".json", "")), ("kind", "ast_projection"), ("status", "PASS"),
            ("python", document["python"]), ("evidence_path", relative),
            ("evidence_lf_sha256", ch.lf_normalized_sha256(path)),
            ("evidence_sha256", document["evidence_sha256"])]))
    return entries


def step_equivalence(root, config):
    from thesis.recovery_successor_005 import equivalence as pe

    lineage = pl.load(root)
    lineage.verify()
    proof = pe.build(root, lineage, config, evidence_entries(root))
    pe.validate(proof, root, lineage, config, deep=True)
    return definitions(root) / "equivalence.json", proof


def step_contract(root, config_path):
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.recovery_successor_005 import contract as pc5

    contract = pc5.build(config_path, pl.SUCCESSOR, root=root, writer_check=False)
    again = pc5.build(config_path, pl.SUCCESSOR, root=root, writer_check=False)
    if contract["contract_sha256"] != again["contract_sha256"]:
        raise RecoveryRefused("the phase-2 contract does not rebuild deterministically")
    if contract.get("status") != prc.STATUS_READY:
        raise RecoveryRefused("the phase-2 contract is not READY")
    return pc5.frozen_path(root), contract


def main(argv=None):
    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("targets", "lineage", "tests", "ast", "equivalence", "contract"))
    parser.add_argument("--config", default=pl.CONFIG_REL)
    parser.add_argument("--label", choices=REQUIRED_LABELS)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = REPO_ROOT
    config_path = (root / args.config).resolve()
    pl.isolate_providers()
    config = load_config(config_path)
    pl.scrub_provider_environment(config)
    require_fresh(root, config)
    if args.step == "targets":
        path, document = step_targets(root)
        summary = OrderedDict([("table_sha256", document["table_sha256"]),
                               ("target_count", document["target_count"]),
                               ("sample_totals", document["sample_totals"]),
                               ("census", document["census_summary"]["total_repair_loops_done"])])
    elif args.step == "lineage":
        path, document = step_lineage(root)
        summary = OrderedDict([("lineage_sha256", document["lineage_sha256"]),
                               ("protected_files", OrderedDict(
                                   (p, inv["file_count"]) for p, inv in document["protected"].items())),
                               ("definitions", len(document["definitions"])),
                               ("targets_sha256", document["targets_sha256"])])
    elif args.step == "tests":
        if not args.label:
            raise RecoveryRefused("--label is required for the tests step")
        path, document = step_tests(root, args.label)
        summary = OrderedDict((k, document[k]) for k in ("label", "status", "python", "tests_run",
                                                         "failures", "errors", "skipped",
                                                         "passed_test_modules"))
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
                               ("measurement_equivalence", list(document["measurement_equivalence"])),
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
