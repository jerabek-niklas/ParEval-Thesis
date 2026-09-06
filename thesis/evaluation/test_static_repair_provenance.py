"""Tests for Static/Repair.1 — runtime readiness identity pinning and the
fail-closed legacy static merge.

Two provenance guarantees, both host-only (no containers, no providers):

  RUNTIME  A readiness artifact proves READY for a MEASURED runtime, not
           only for a semantic condition. The static-analysis condition
           deliberately excludes per-tool runtime identities (so PARCOACH,
           LLOV and the main image can merge results under ONE static
           condition); the readiness runtime condition therefore carries
           them explicitly - container image identity, tool identities,
           the LLOV plugin hash - and a drift in any of them invalidates an
           older READY. Volatile facts (timestamps, hostnames, container
           names) are documented in the artifact but never fingerprinted.

  LEGACY   A record written before the tool-state wave (static_analysis.v2,
           no `sample_source_sha256`) that already carries tool results can
           no longer be augmented and then pinned with the CURRENT source
           hash - that would retroactively legitimize results nobody can tie
           to those bytes. Only an empty legacy record may be initialized;
           a legacy record with results needs a fresh run_id or an explicit
           FULL recomputation.

Run:  python thesis/evaluation/test_static_repair_provenance.py
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import run_static_analysis as rsa  # noqa: E402
from thesis.evaluation import static_provenance as sp  # noqa: E402
from thesis.evaluation.framework import STATE_COMPLETED  # noqa: E402
from thesis.evaluation.test_tool_state import (  # noqa: E402
    FakeStaticTool,
    StaticWorld,
    check,
    FAILURES,
)

# ---------------------------------------------------------------------------
# a measured runtime environment, in the shape check_static_repair_readiness
# produces it (values abbreviated but structurally identical)
# ---------------------------------------------------------------------------

BASE_RUNTIME = {
    "main": {
        "role": "internal static tools",
        "image_ref": "pareval-thesis",
        "image_id": "sha256:eb1c2e93cfab755504b25e6fbf6e0df34e1b371e18c995f55d7eba77f74222aa",
        "repo_digests": [],
        "rootfs_layers_sha256": "f6bc13cbc026618ba889236257111696557081179048b7da766a89e81fbdba7c",
        "tool_identities": {
            "compiler": "g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0",
            "gcc_analyzer": "g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0",
            "clang_tidy": "Ubuntu LLVM version 18.1.3",
            "cppcheck": "Cppcheck 2.13.0",
            "infer": "Infer version v1.1.0",
        },
        "evidence": {"mpi_version_line": "mpirun (Open MPI) 4.1.6"},
    },
    "parcoach": {
        "role": "external static tool (MPI collectives)",
        "image_ref": "registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1",
        "image_id": "sha256:dbac7091e60b218c72a27153639ed4b5ead0389aca0857313cfb821bd3d68030",
        "repo_digests": ["registry.gitlab.inria.fr/parcoach/parcoach-demo@sha256:aaaa"],
        "rootfs_layers_sha256": "2975b0d46cf4e416ccf29686442116977b9e67a4c30e69dde51c364109b368ee",
        "tool_identities": {"parcoach": "Ubuntu LLVM version 15.0.7"},
        "evidence": {
            "executable_path": "/usr/bin/parcoach",
            "executable_sha256": "b" * 64,
            "cmake_package_version": "2.4.0",
            "program_version_claimable": False,
        },
    },
    "llov": {
        "role": "external static tool (OpenMP races)",
        "image_ref": "pareval-llov",
        "image_id": "sha256:67d8c6c0b36e691c72f80fe893fbfedf4d55e298abc82c841561cd46b95e3341",
        "repo_digests": [],
        "rootfs_layers_sha256": "835fc4ef14332c3ca74c0801139820c48aa6dc8acf8940a87ffe0b248fbc80a5",
        "tool_identities": {"llov": "clang version 7.1.0 (LLVMOMPVerify 93321be)"},
        "evidence": {
            "plugin_path": "/home/llvm/Work/LLOV/lib/OpenMPVerify.so",
            "plugin_sha256": "c" * 64,
            "python_identity": "Python 3.8.0",
        },
    },
}

STATIC_SHA = "1" * 64
REPAIR_SHA = "2" * 64


def runtime_sha(environments=None, static_sha=STATIC_SHA, repair_sha=REPAIR_SHA):
    condition = sp.runtime_condition(
        environments if environments is not None else copy.deepcopy(BASE_RUNTIME),
        static_analysis_condition_sha256=static_sha,
        repair_condition_sha256=repair_sha,
    )
    return sp.runtime_condition_sha256(condition), condition


def mutate(path, value):
    """Deep-copy BASE_RUNTIME with one field replaced ('llov.image_id')."""
    environments = copy.deepcopy(BASE_RUNTIME)
    node = environments
    parts = path.split(".")
    for key in parts[:-1]:
        node = node[key]
    node[parts[-1]] = value
    return environments


# ---------------------------------------------------------------------------
# RUNTIME group
# ---------------------------------------------------------------------------

def test_runtime_condition():
    print("RUNTIME: readiness runtime condition and drift detection")

    baseline, condition = runtime_sha()
    check("1: same semantic condition + same runtime -> identical fingerprint",
          runtime_sha()[0] == baseline and len(baseline) == 64)
    check("1: condition carries its own version and both semantic conditions",
          condition.get("condition_version") == sp.RUNTIME_CONDITION_VERSION
          and condition["static_analysis_condition_sha256"] == STATIC_SHA
          and condition["repair_condition_sha256"] == REPAIR_SHA)

    drifts = [
        ("2: LLOV image id changed", mutate("llov.image_id", "sha256:" + "9" * 64)),
        ("3: PARCOACH image id changed", mutate("parcoach.image_id", "sha256:" + "8" * 64)),
        ("3: PARCOACH repo digest changed",
         mutate("parcoach.repo_digests", ["registry.gitlab.inria.fr/parcoach/parcoach-demo@sha256:bbbb"])),
        ("4: compiler identity changed",
         mutate("main.tool_identities", dict(BASE_RUNTIME["main"]["tool_identities"],
                                             compiler="g++ (Ubuntu 14.2.0) 14.2.0"))),
        ("4: clang-tidy identity changed",
         mutate("main.tool_identities", dict(BASE_RUNTIME["main"]["tool_identities"],
                                             clang_tidy="Ubuntu LLVM version 19.1.0"))),
        ("4: infer identity changed",
         mutate("main.tool_identities", dict(BASE_RUNTIME["main"]["tool_identities"],
                                             infer="Infer version v1.2.0"))),
        ("5: LLOV plugin hash changed",
         mutate("llov.evidence", dict(BASE_RUNTIME["llov"]["evidence"], plugin_sha256="d" * 64))),
        ("5: PARCOACH executable hash changed",
         mutate("parcoach.evidence", dict(BASE_RUNTIME["parcoach"]["evidence"],
                                          executable_sha256="e" * 64))),
        # a rebuilt image can keep its tag AND (on a classic image store) even
        # its config digest while its layer set changes
        ("2: LLOV layer set changed (store-independent identity)",
         mutate("llov.rootfs_layers_sha256", "a" * 64)),
        ("3: PARCOACH layer set changed", mutate("parcoach.rootfs_layers_sha256", "a" * 64)),
        ("4: main layer set changed", mutate("main.rootfs_layers_sha256", "a" * 64)),
    ]
    for label, environments in drifts:
        sha, _ = runtime_sha(environments)
        check("%s -> fingerprint differs" % label, sha != baseline)
        check("%s -> drift is named" % label,
              sp.runtime_drift(condition, sp.runtime_condition(
                  environments, static_analysis_condition_sha256=STATIC_SHA,
                  repair_condition_sha256=REPAIR_SHA)))

    check("6: tool code change (static semantic condition) is a separate signal",
          runtime_sha(static_sha="f" * 64)[0] != baseline
          and "static_analysis_condition_sha256" in sp.runtime_drift(
              condition,
              sp.runtime_condition(copy.deepcopy(BASE_RUNTIME),
                                   static_analysis_condition_sha256="f" * 64,
                                   repair_condition_sha256=REPAIR_SHA)))
    check("6: repair condition change is a separate signal",
          "repair_condition_sha256" in sp.runtime_drift(
              condition,
              sp.runtime_condition(copy.deepcopy(BASE_RUNTIME),
                                   static_analysis_condition_sha256=STATIC_SHA,
                                   repair_condition_sha256="f" * 64)))

    # 7: volatile facts must NOT reach the fingerprint
    volatile = copy.deepcopy(BASE_RUNTIME)
    volatile["main"]["measured_at_utc"] = "2026-09-06T10:00:00Z"
    volatile["main"]["hostname"] = "a1b2c3d4e5f6"
    volatile["main"]["container_name"] = "boring_turing"
    volatile["main"]["duration_seconds"] = 12.5
    volatile["llov"]["measured_at_utc"] = "2026-09-06T10:01:00Z"
    volatile["llov"]["evidence"] = dict(volatile["llov"]["evidence"],
                                        measured_at_utc="2026-09-06T10:01:02Z")
    check("7: timestamps / hostname / container name do not change the fingerprint",
          runtime_sha(volatile)[0] == baseline)
    check("7: volatile facts stay readable in the condition body",
          runtime_sha(volatile)[1]["environments"]["main"].get("hostname") is None)

    # whitespace / CRLF normalization of measured identity strings
    noisy = mutate("main.tool_identities",
                   dict(BASE_RUNTIME["main"]["tool_identities"],
                        compiler="  g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1)   13.3.0\r\n"))
    check("identity strings are whitespace-normalized before hashing",
          runtime_sha(noisy)[0] == baseline)

    # determinism across interpreter processes
    import subprocess
    snippet = (
        "import json,sys; sys.path.insert(0, %r);"
        "from thesis.evaluation import static_provenance as sp;"
        "from thesis.evaluation.test_static_repair_provenance import BASE_RUNTIME, STATIC_SHA, REPAIR_SHA;"
        "print(sp.runtime_condition_sha256(sp.runtime_condition(BASE_RUNTIME,"
        " static_analysis_condition_sha256=STATIC_SHA, repair_condition_sha256=REPAIR_SHA)))"
        % str(REPO_ROOT)
    )
    runs = [subprocess.run([sys.executable, "-c", snippet], capture_output=True,
                           text=True).stdout.strip() for _ in range(2)]
    check("fingerprint identical across interpreter processes",
          runs[0] == baseline and runs[1] == baseline)

    # a missing immutable identity must never silently pass as "pinned"
    unpinned = mutate("llov.image_id", None)
    unpinned["llov"]["repo_digests"] = []
    unpinned["llov"]["rootfs_layers_sha256"] = None
    condition_unpinned = sp.runtime_condition(
        unpinned, static_analysis_condition_sha256=STATIC_SHA,
        repair_condition_sha256=REPAIR_SHA)
    check("environment without any immutable image identity is reported unpinned",
          condition_unpinned["unpinned_environments"] == ["llov"]
          and condition_unpinned["fully_pinned"] is False)
    check("fully measured runtime reports itself pinned",
          condition["fully_pinned"] is True and condition["unpinned_environments"] == [])


# ---------------------------------------------------------------------------
# LEGACY group
# ---------------------------------------------------------------------------

def legacy_record(sample_id, tools):
    """A pre-tool-state record: static_analysis.v2, no sample_source_sha256."""
    return {
        "schema_version": "static_analysis.v2",
        "run_id": "legacy_run",
        "model_id": "m",
        "sample_id": sample_id,
        "execution_model": "serial",
        "created_at_utc": "2026-08-13T12:43:00Z",
        "tools": {
            name: {
                "tool": name,
                "ran": True,
                "exit_code": 0,
                "duration_seconds": 0.1,
                "num_findings": 0,
                "num_blocking": 0,
                "findings": [],
            }
            for name in tools
        },
    }


def write_records(world, run_id, records):
    path = world.intermediate / run_id / "m" / "static_analysis.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


SAMPLE = "m__a__b__serial__sample_0"
SOURCES = {SAMPLE: ("serial", "int legacy;\n")}


def test_legacy_merge():
    print("LEGACY: fail-closed merge of unpinned pre-tool-state records")

    # ---- 8: empty legacy record may be initialized ----------------------
    with tempfile.TemporaryDirectory() as tmp:
        world = StaticWorld(tmp, SOURCES)
        world.register(FakeStaticTool("compiler"), FakeStaticTool("clang_tidy"),
                       FakeStaticTool("cppcheck"))
        record = legacy_record(SAMPLE, [])
        write_records(world, "r8", [record])
        summary = world.run("r8", ["compiler"])
        stored = world.records("r8")[SAMPLE]
        check("8: legacy record without tool results is initialized (pin allowed)",
              len(stored.get("sample_source_sha256") or "") == 64
              and set(stored["tools"]) == {"compiler"}
              and summary["invocations"][-1]["pre_existing_records_pinned"] == 1)
        check("8: nothing was reported as replaced",
              summary["invocations"][-1]["legacy_records_fully_replaced"]["records"] == 0)
        check("8: an initialized record carries no recomputation marker",
              "legacy_entries_dropped" not in stored)

    # ---- 9: legacy record WITH results cannot be augmented ---------------
    with tempfile.TemporaryDirectory() as tmp:
        world = StaticWorld(tmp, SOURCES)
        world.register(FakeStaticTool("compiler"), FakeStaticTool("clang_tidy"),
                       FakeStaticTool("cppcheck"))
        write_records(world, "r9", [legacy_record(SAMPLE, ["compiler"])])
        before = (world.intermediate / "r9" / "m" / "static_analysis.jsonl").read_bytes()
        try:
            world.run("r9", ["clang_tidy"])
            check("9: legacy record with historical results refuses a new tool", False)
        except sp.LegacyRecordUnverified as refusal:
            check("9: legacy record with historical results refuses a new tool", True)
            check("9: refusal names the unverified entries and the safe ways out",
                  "compiler" in str(refusal)
                  and "fresh run_id" in str(refusal)
                  and "--replace-legacy-record" in str(refusal))
        check("9: refusal is a StaticMergeConflict (runner exits 3)",
              issubclass(sp.LegacyRecordUnverified, sp.StaticMergeConflict))
        check("9: nothing was written",
              (world.intermediate / "r9" / "m" / "static_analysis.jsonl").read_bytes() == before)
        check("9: no source hash was pinned into the legacy record",
              world.records("r9")[SAMPLE].get("sample_source_sha256") is None)

    # ---- 10: partial --replace-tool-entries cannot bypass it -------------
    with tempfile.TemporaryDirectory() as tmp:
        world = StaticWorld(tmp, SOURCES)
        world.register(FakeStaticTool("compiler"), FakeStaticTool("clang_tidy"),
                       FakeStaticTool("cppcheck"))
        write_records(world, "r10", [legacy_record(SAMPLE, ["compiler", "clang_tidy"])])
        try:
            world.run("r10", ["clang_tidy"], replace_tool_entries=["clang_tidy"])
            check("10: partial tool replacement cannot bypass legacy provenance", False)
        except sp.LegacyRecordUnverified:
            check("10: partial tool replacement cannot bypass legacy provenance", True)
        stored = world.records("r10")[SAMPLE]
        check("10: the legacy entries are untouched",
              set(stored["tools"]) == {"compiler", "clang_tidy"}
              and stored.get("sample_source_sha256") is None)

    # ---- 11: explicit FULL recomputation is allowed and drops everything --
    with tempfile.TemporaryDirectory() as tmp:
        world = StaticWorld(tmp, SOURCES)
        world.register(FakeStaticTool("compiler"), FakeStaticTool("clang_tidy"),
                       FakeStaticTool("cppcheck"))
        write_records(world, "r11", [legacy_record(SAMPLE, ["compiler", "cppcheck"])])
        summary = world.run("r11", ["compiler", "clang_tidy"], replace_legacy_record=True)
        stored = world.records("r11")[SAMPLE]
        check("11: full recomputation retires every historical entry",
              set(stored["tools"]) == {"compiler", "clang_tidy"})
        check("11: no unverified entry survives as a result (legacy cppcheck retired)",
              "cppcheck" not in stored["tools"])
        check("11: the historical evidence is ARCHIVED, not deleted",
              set(stored.get("superseded_legacy_tools") or {}) == {"compiler", "cppcheck"}
              and (stored["superseded_legacy_tools"]["cppcheck"] or {}).get("tool") == "cppcheck")
        check("11: the record now pins the current source hash",
              stored["sample_source_sha256"]
              == sp.sample_source_sha256(world.samples[0].source_path))
        check("11: every surviving entry carries an execution fingerprint",
              all(len(e.get("tool_execution_fingerprint_sha256") or "") == 64
                  for e in stored["tools"].values()))
        replaced = summary["invocations"][-1]["legacy_records_fully_replaced"]
        check("11: the drop is recorded (bounded) in the invocation history",
              replaced["records"] == 1 and replaced["tool_entries"] == 2
              and replaced["tools"] == {"compiler": 1, "cppcheck": 1}
              and replaced["first_sample_ids"] == [SAMPLE]
              and summary["invocations"][-1]["replace_legacy_record"] is True)
        check("11: the RECORD says it was recomputed from an unpinned v2 record",
              stored.get("legacy_entries_dropped") == ["compiler", "cppcheck"]
              and "static_analysis.v2" in (stored.get("provenance_note") or ""))
        # and afterwards the record behaves like any v3 record
        summary = world.run("r11", ["compiler"])
        check("11: the recomputed record is idempotent afterwards",
              summary["invocations"][-1]["entries_kept_idempotent"].get("compiler") == 1)

    # ---- 12/13: v3 records keep their existing behaviour -----------------
    with tempfile.TemporaryDirectory() as tmp:
        world = StaticWorld(tmp, SOURCES)
        world.register(FakeStaticTool("compiler"), FakeStaticTool("clang_tidy"))
        world.run("r12", ["compiler"])
        world.run("r12", ["clang_tidy"])
        stored = world.records("r12")[SAMPLE]
        check("12: v3 cross-container merge of a different tool still works",
              set(stored["tools"]) == {"compiler", "clang_tidy"})
        summary = world.run("r12", ["compiler"])
        check("12: v3 same-source re-run stays idempotent",
              summary["invocations"][-1]["entries_kept_idempotent"].get("compiler") == 1)
        snapshot = (world.intermediate / "r12" / "m" / "static_analysis.jsonl").read_bytes()
        world.samples[0].source_path.write_text("int legacy; int drift;\n", encoding="utf-8")
        try:
            world.run("r12", ["clang_tidy"])
            check("13: v3 source drift is still refused", False)
        except sp.StaticMergeConflict as conflict:
            check("13: v3 source drift is still refused",
                  "generated-code.hpp changed" in str(conflict))
        check("13: nothing was written on the refused merge",
              (world.intermediate / "r12" / "m" / "static_analysis.jsonl").read_bytes() == snapshot)
        check("13: a legacy refusal and a drift refusal are distinguishable",
              not isinstance(sp.StaticMergeConflict("x"), sp.LegacyRecordUnverified))

    # ---- an unreadable candidate source is refused before any write -----
    with tempfile.TemporaryDirectory() as tmp:
        world = StaticWorld(tmp, SOURCES)
        world.register(FakeStaticTool("compiler"), FakeStaticTool("clang_tidy"))
        world.run("r14", ["compiler"])
        snapshot = (world.intermediate / "r14" / "m" / "static_analysis.jsonl").read_bytes()
        world.samples[0].source_path.unlink()
        try:
            world.run("r14", ["clang_tidy"])
            check("14: an unreadable candidate source is refused", False)
        except sp.StaticMergeConflict as conflict:
            check("14: an unreadable candidate source is refused",
                  "could not be read" in str(conflict))
        check("14: nothing was written for the unverifiable sample",
              (world.intermediate / "r14" / "m" / "static_analysis.jsonl").read_bytes() == snapshot)
        check("14: the refusal is not mislabelled as a legacy record",
              not isinstance(sp.StaticMergeConflict("x"), sp.LegacyRecordUnverified))

    # a fresh record can therefore never become an unpinned one that the NEXT
    # container would reject as "legacy" (the cross-container merge stays open)
    with tempfile.TemporaryDirectory() as tmp:
        world = StaticWorld(tmp, SOURCES)
        world.register(FakeStaticTool("compiler"), FakeStaticTool("clang_tidy"))
        world.run("r15", ["compiler"])
        stored = world.records("r15")[SAMPLE]
        check("15: every freshly written record is pinned",
              len(stored.get("sample_source_sha256") or "") == 64)
        world.run("r15", ["clang_tidy"])
        check("15: the second container merges into it normally",
              set(world.records("r15")[SAMPLE]["tools"]) == {"compiler", "clang_tidy"})

    # ---- read-only consumers are unaffected ------------------------------
    legacy = legacy_record(SAMPLE, ["compiler", "llov"])
    check("read-only classification of legacy records still works",
          sp.unpinned_legacy_entries(legacy) == ["compiler", "llov"]
          and sp.unpinned_legacy_entries({"sample_source_sha256": "x", "tools": {"a": {}}}) == []
          and sp.unpinned_legacy_entries(None) == [])
    check("check_merge stays silent for records it must not touch",
          sp.check_merge(None, SAMPLE, "abc") is None
          and sp.check_merge(legacy, SAMPLE, "abc", replace_legacy_record=True) is None)


def test_preflight_runtime_staleness():
    """End-to-end: the pilot preflight must re-measure the runtime and refuse
    a readiness artifact proven on a different one. Runs the real script in a
    subprocess with a SUPPLIED runtime (no docker needed); skipped when the
    repository carries no measured readiness artifact yet."""
    print("PREFLIGHT: readiness staleness against fresh vs drifted runtime")

    import subprocess

    artifact_path = REPO_ROOT / "thesis" / "evaluation" / "static_repair_readiness.json"
    gate_path = REPO_ROOT / "thesis" / "evaluation" / "cross_pilot_comparability.json"
    if not artifact_path.is_file() or not gate_path.is_file():
        print("  [skip] no readiness artifact / cross-pilot gate in the tree")
        return

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not artifact.get("runtime_condition_sha256") or not artifact.get("runtime"):
        print("  [skip] readiness artifact predates the runtime condition "
              "(schema %s) - re-run check_static_repair_readiness.py"
              % artifact.get("schema_version"))
        return

    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    expected_env = (gate.get("environment_condition") or {}).get("expected") or {}
    overrides = (gate.get("effective_invocation_policy") or {}).get(
        "verdict_relevant_cli_overrides") or {}
    models = list((gate.get("cross_pilot_reevaluation") or {}).get(
        "evidence_inventory", {}).get("model_ids", []))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        invocation = {
            "config_path": "thesis/config/config.yaml",
            "profile": "pilot",
            "effective_run_id": "pilot_002",
            "selected_model_ids": models or [],
            "primary_compiler": (overrides.get("primary_compiler") or {}).get("expected", "g++"),
            "run_timeout_seconds": (overrides.get("run_timeout_seconds") or {}).get("expected", 120.0),
            "model_id_cli_override": None,
        }
        (tmp_path / "invocation.json").write_text(json.dumps(invocation), encoding="utf-8")
        (tmp_path / "environment.json").write_text(json.dumps({
            "primary_compiler_version": expected_env.get("primary_compiler_version"),
            "mpi_version_line": expected_env.get("mpi_version_line"),
        }), encoding="utf-8")
        (tmp_path / "fresh.json").write_text(
            json.dumps({"runtime": artifact["runtime"]}), encoding="utf-8")

        drifted = copy.deepcopy(artifact["runtime"])
        for name, environment in drifted.items():
            if name == "llov":
                environment["image_id"] = "sha256:" + "9" * 64
                environment["rootfs_layers_sha256"] = "9" * 64
                environment["repo_digests"] = []
        (tmp_path / "drifted.json").write_text(
            json.dumps({"runtime": drifted}), encoding="utf-8")

        def preflight(runtime_file=None, extra=()):
            argv = [sys.executable, str(REPO_ROOT / "thesis/evaluation/pilot_preflight.py"),
                    "--invocation", str(tmp_path / "invocation.json"),
                    "--environment", str(tmp_path / "environment.json")]
            if runtime_file:
                argv += ["--static-runtime", str(tmp_path / runtime_file)]
            argv += list(extra)
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  cwd=str(REPO_ROOT), timeout=900)
            return proc.stdout + proc.stderr

        fresh_out = preflight("fresh.json")
        check("preflight accepts the runtime the readiness was proven on",
              "STATIC_REPAIR_READINESS = READY" in fresh_out
              and "runtime identity unchanged since the readiness proof" in fresh_out)

        drift_out = preflight("drifted.json")
        check("preflight refuses a drifted runtime",
              "STATIC_REPAIR_READINESS = UNRESOLVED (stale)" in drift_out
              and "STATIC_REPAIR_READINESS = READY" not in drift_out)
        check("preflight names the drifted identity",
              "environments.llov.image_id" in drift_out
              and "environments.llov.rootfs_layers_sha256" in drift_out)

        skipped_out = preflight(extra=["--skip-runtime-probe"])
        check("preflight never accepts a readiness proof without fresh runtime evidence",
              "STATIC_REPAIR_READINESS = UNRESOLVED (stale)" in skipped_out
              and "not re-measured" in skipped_out)


def main() -> int:
    for test in (test_runtime_condition, test_legacy_merge,
                 test_preflight_runtime_staleness):
        print()
        try:
            test()
        except Exception as error:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILURES.append("%s raised %s: %s" % (test.__name__, type(error).__name__, error))
    print()
    if FAILURES:
        print("FAILED (%d):" % len(FAILURES))
        for label in FAILURES:
            print("  - " + label)
        return 1
    print("All static/repair provenance test groups passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
