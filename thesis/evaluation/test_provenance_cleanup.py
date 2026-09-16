#!/usr/bin/env python3
"""Technical provenance cleanup - fixtures for the two closed gaps.

  1. STATIC_SPLIT_INVOCATION_COVERAGE_GAP (PARCOACH / LLOV): per-model
     invocation MEMBERSHIP vs COVERAGE derived from the frozen contract
     (stage_runtime.expected_split_static_invocations /
     split_static_invocation_matrix, reported by verify_pilot_run).
  2. ITERATION_ZERO_COVERAGE_RESIDUAL (correctness / dynamic writer
     attribution): positive writer provenance written by the productive
     runners when the repair loop runs an internal stage at iteration 0
     (writer_attribution.py, repair_scope.iteration_zero_analysis).

Every fixture is a real mini run through the productive contract builder,
manifest fragments, stage runners and orchestrator writers (World from
test_post_run_verification.py). No provider calls, no containers.

    python thesis/evaluation/test_provenance_cleanup.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import manifest_fragments as mf  # noqa: E402
from thesis.evaluation import repair_scope as rs  # noqa: E402
from thesis.evaluation import stage_runtime as sr  # noqa: E402
from thesis.evaluation import writer_attribution as wa  # noqa: E402
from thesis.evaluation.test_post_run_verification import (  # noqa: E402
    World, fake_prober, status_of)
from thesis.evaluation.test_repair_scope import (  # noqa: E402
    ALL_VARIANTS, SIX_LOOPS, _remove_repair_invocation, loop_status, scope_check)
from thesis.generation import common  # noqa: E402

FAILURES = []
CHECKS = 0


def check(label, condition):
    global CHECKS
    CHECKS += 1
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

SPLIT_TOOLS = {"static_analysis": {"enabled": True, "tools": {
    "compiler": {"enabled": True}, "clang_tidy": {"enabled": False},
    "gcc_analyzer": {"enabled": False}, "cppcheck": {"enabled": False},
    "infer": {"enabled": False},
    "parcoach": {"enabled": True, "execution_models": ["mpi"]},
    "llov": {"enabled": True, "execution_models": ["omp"]}}}}

TOOL_OF = {"parcoach": "mpi", "llov": "omp"}


def split_world(tmp, tool, models=("m1", "m2"), **kwargs):
    return World(Path(tmp), models=models, execution_model=TOOL_OF[tool],
                 execution_models=("serial", "omp", "mpi"), stage_overrides=SPLIT_TOOLS, **kwargs)


def intermediate(world):
    return Path(world.config["outputs"]["intermediate_dir"])


def remove_split_invocation(world, tool, model):
    stage = "static.%s" % tool
    removed = 0
    for path in mf.fragments_dir(intermediate(world), world.run_id).glob(
            "invocation.%s@%s*.json" % (stage, model)):
        path.unlink()
        removed += 1
    mf.write_snapshot(intermediate(world), world.run_id)
    assert removed == 1, removed


def register_raw_invocation(world, invocation, owner, refingerprint=True):
    """Register an invocation fragment WITHOUT the contract check of
    enforce_stage (the attack path: a fragment that should never exist)."""
    from thesis.evaluation import effective_invocation as ei

    if refingerprint:
        invocation["invocation_sha256"] = ei.invocation_fingerprint(invocation)
    mf.register_fragment(intermediate(world), world.run_id, "invocation", owner, invocation,
                         fingerprint=invocation["invocation_sha256"], writer="fixture")
    mf.write_snapshot(intermediate(world), world.run_id)


def split_invocation(world, tool, model_scope, **overrides):
    from thesis.evaluation import effective_invocation as ei

    values = {"primary_compiler": {"value": "g++", "source": "DEFAULT"},
              "tools": {"value": [tool], "source": "CLI"}}
    values.update(overrides)
    return ei.build_invocation(world.run_id, "static.%s" % tool, "fixture", values,
                               model_scope=model_scope, contract=world.contract)


def write_static_summary(world, model, tools_run, **condition):
    """One static summary invocation entry exactly as run_static_analysis
    writes it (condition fields included)."""
    summary = world.model_dir(model) / "static_analysis_summary.json"
    entry = {"label": "run_static_analysis --tools %s" % " ".join(tools_run),
             "writer": "base", "repair_writer": None, "tools_requested": list(tools_run),
             "tools_run": list(tools_run), "tools_skipped": [],
             "entries_run": {t: 2 for t in tools_run}, "replace_tool_entries": [],
             "rerun_gaps": False, "replace_legacy_record": False, "primary_compiler": "g++"}
    entry.update(condition)
    document = {"schema_version": "static_analysis_summary.v3", "model_id": model,
                "invocations": [entry]}
    summary.write_text(json.dumps(document), encoding="utf-8")


def drop_split_history(world, model, tool):
    """A container that never ran left no history entry."""
    summary_path = world.model_dir(model) / "static_analysis_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["invocations"] = [i for i in summary["invocations"]
                              if tool not in (i.get("tools_run") or [])]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")


def split_report(world):
    report = world.verify(skip_enhanced=True)
    return report, report["split_static_invocation_coverage"]


def scope_status(report, tool, model):
    return status_of(report, "split_static_invocation:static.%s/%s" % (tool, model))


# ---------------------------------------------------------------------------
# 1. split-container invocation coverage
# ---------------------------------------------------------------------------

def test_split_expected_set_contract_derived():
    print("== split coverage: expected scopes derive from the FROZEN contract only ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = split_world(tmp, "parcoach", models=("m1", "m2", "m3"))
        expected = sr.expected_split_static_invocations(world.contract)
        check("status PASS with one scope per contracted model and split tool",
              expected["status"] == "PASS" and expected["model_ids"] == ["m1", "m2", "m3"]
              and [(s["tool"], s["model_id"]) for s in expected["scopes"]]
              == [("parcoach", "m1"), ("parcoach", "m2"), ("parcoach", "m3"),
                  ("llov", "m1"), ("llov", "m2"), ("llov", "m3")])
        check("every scope carries stage, tool, model, applicable execution models and the "
              "contract binding",
              all(s["stage"] == "static.%s" % s["tool"] and s["contract_binding"]["contract_sha256"]
                  == world.contract["contract_sha256"] and s["applicable_execution_models"]
                  == [TOOL_OF[s["tool"]]] for s in expected["scopes"]))
        check("no model count is hard-coded: 3 contracted models -> 3 scopes per tool",
              expected["per_tool"]["parcoach"]["scope_count"] == 3
              and expected["per_tool"]["llov"]["scope_count"] == 3)
    check("no contract -> UNRESOLVED (never an empty PASS)",
          sr.expected_split_static_invocations(None)["status"] == "UNRESOLVED")
    check("contract without a frozen toolset -> UNRESOLVED",
          sr.expected_split_static_invocations({"expected_stages": ["static_analysis"],
                                                "model_ids": ["m1"]})["status"] == "UNRESOLVED")
    check("contract without static analysis -> NOT_APPLICABLE",
          sr.expected_split_static_invocations({"expected_stages": ["correctness_tests"],
                                                "model_ids": ["m1"]})["status"] == "NOT_APPLICABLE")
    with tempfile.TemporaryDirectory() as tmp:
        # F: population without mpi/omp: neither split tool applies -> no scope
        world = World(Path(tmp), models=("m1",), execution_models=("serial",),
                      stage_overrides=SPLIT_TOOLS)
        expected = sr.expected_split_static_invocations(world.contract)
        check("F: a split tool whose scope misses the contracted population is NOT expected "
              "(no scope, reason recorded)",
              expected["status"] == "NOT_APPLICABLE" and expected["scopes"] == []
              and {n["tool"] for n in expected["not_expected"]} == {"parcoach", "llov"})
        report, split = split_report(world)
        check("F: ... and the run verifies PASS without any split invocation",
              report["status"] == "PASS" and split["coverage"] == "NOT_APPLICABLE"
              and status_of(report, "split_static_invocation_expected_set") == "PASS")


def test_split_coverage_matrix():
    for tool in ("parcoach", "llov"):
        print("== split coverage: %s ==" % tool)
        other = "llov" if tool == "parcoach" else "parcoach"
        with tempfile.TemporaryDirectory() as tmp:
            # A / C: every expected scope present
            world = split_world(tmp, tool)
            report, split = split_report(world)
            check("A/C %s: all expected per-model invocations present -> coverage PASS, "
                  "membership PASS, run PASS" % tool,
                  report["status"] == "PASS" and split["coverage"] == "PASS"
                  and split["membership"] == "PASS" and split["expected_scope_count"] == 4
                  and split["covered_scope_count"] == 4 and split["missing_scopes"] == [])
            check("A/C %s: per-tool counts are separate" % tool,
                  split["per_tool"][tool]["covered_scope_count"] == 2
                  and split["per_tool"][other]["covered_scope_count"] == 2)
        with tempfile.TemporaryDirectory() as tmp:
            # B / D / K: one model's invocation deleted, records complete, runtime
            # stamp still present
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            report, split = split_report(world)
            check("B/D %s: one expected model invocation deleted while the tool records are "
                  "complete -> NON-PASS (coverage UNRESOLVED, scope named)" % tool,
                  report["status"] == "UNRESOLVED" and split["coverage"] == "UNRESOLVED"
                  and split["covered_scope_count"] == 3
                  and [(m["tool"], m["model_id"], m["records_present"]) for m in split["missing_scopes"]]
                  == [(tool, "m2", True)])
            check("B/D %s: static record coverage of m2 is PASS - records do not substitute "
                  "for the invocation" % tool,
                  status_of(report, "static_coverage:m2") == "PASS"
                  and scope_status(report, tool, "m2") == "UNRESOLVED"
                  and split["record_coverage_substitutes_split_invocation"] is False)
            check("K %s: the stage runtime stamp is present and PASS, yet coverage is not - "
                  "a runtime stamp does not substitute" % tool,
                  status_of(report, "stage_runtime:static.%s.%s" % (tool, tool)) == "PASS"
                  and split["runtime_stamp_substitutes_split_invocation"] is False)
            check("E %s: the surviving fragment (m1) covers ONE model only, not the stage" % tool,
                  scope_status(report, tool, "m1") == "PASS"
                  and status_of(report, "effective_invocation:static.%s" % tool) == "PASS"
                  and split["membership"] == "PASS")
        with tempfile.TemporaryDirectory() as tmp:
            # G: invocation for a NOT_APPLICABLE scope (serial-only population)
            world = World(Path(tmp), models=("m1",), execution_models=("serial",),
                          stage_overrides=SPLIT_TOOLS)
            register_raw_invocation(world, split_invocation(world, tool, ["m1"]),
                                    "static.%s@m1@tools-%s" % (tool, tool))
            report, split = split_report(world)
            check("G %s: an invocation for a scope the contract does not apply -> membership "
                  "FAIL" % tool,
                  split["membership"] == "FAIL" and report["status"] == "FAIL"
                  and len(split["unexpected_scopes"]) == 1)
        with tempfile.TemporaryDirectory() as tmp:
            # H: wrong model id
            world = split_world(tmp, tool)
            register_raw_invocation(world, split_invocation(world, tool, ["ghost"]),
                                    "static.%s@ghost@tools-%s" % (tool, tool))
            report, split = split_report(world)
            check("H %s: a fragment for a model outside the contract -> membership FAIL, run "
                  "FAIL (the expected scopes themselves stay covered)" % tool,
                  split["membership"] == "FAIL" and report["status"] == "FAIL"
                  and split["coverage"] == "PASS"
                  and any(u.get("model_id") == "ghost" for u in split["unexpected_scopes"]))
        with tempfile.TemporaryDirectory() as tmp:
            # I: contract contradiction (a pinned value differs) and a fingerprint
            # that does not reproduce
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            bad = split_invocation(world, tool, ["m2"],
                                   primary_compiler={"value": "clang++", "source": "CLI"})
            register_raw_invocation(world, bad, "static.%s@m2@tools-%s" % (tool, tool))
            report, split = split_report(world)
            check("I %s: an invocation contradicting a contract-pinned value -> FAIL" % tool,
                  split["membership"] == "FAIL" and scope_status(report, tool, "m2") != "PASS"
                  and report["status"] == "FAIL")
        with tempfile.TemporaryDirectory() as tmp:
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            tampered = split_invocation(world, tool, ["m2"])
            tampered["invocation_sha256"] = "0" * 64
            register_raw_invocation(world, tampered, "static.%s@m2@tools-%s" % (tool, tool),
                                    refingerprint=False)
            report, split = split_report(world)
            check("I2 %s: a fragment whose fingerprint does not reproduce -> FAIL" % tool,
                  split["membership"] == "FAIL" and report["status"] == "FAIL"
                  and any("fingerprint" in " ".join(u["problems"])
                          for u in report["split_static_invocations"]["unkeyable_fragments"]))
        with tempfile.TemporaryDirectory() as tmp:
            # J: wrong stage / tool identity
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            wrong = split_invocation(world, tool, ["m2"], tools={"value": [other], "source": "CLI"})
            register_raw_invocation(world, wrong, "static.%s@m2@tools-%s" % (tool, other))
            report, split = split_report(world)
            check("J %s: a %s fragment that claims the tool of the other stage -> FAIL" % (tool, tool),
                  split["membership"] == "FAIL" and report["status"] == "FAIL"
                  and scope_status(report, tool, "m2") != "PASS")
        with tempfile.TemporaryDirectory() as tmp:
            # foreign run id inside the fragment
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            foreign = split_invocation(world, tool, ["m2"])
            foreign["run_id"] = "another_run"
            register_raw_invocation(world, foreign, "static.%s@m2@tools-%s" % (tool, tool))
            report, split = split_report(world)
            check("foreign run_id %s: a fragment of another run never covers this run's scope"
                  % tool, split["membership"] == "FAIL" and report["status"] == "FAIL")
        with tempfile.TemporaryDirectory() as tmp:
            # L: legitimate consistent duplicates - a per-model fragment AND a
            # whole-run fragment (model_scope null) with per-model summary
            # evidence for every model under the same condition
            world = split_world(tmp, tool)
            for model in ("m1", "m2"):
                write_static_summary(world, model, ["compiler", tool])
            register_raw_invocation(world, split_invocation(world, tool, None),
                                    "static.%s@tools-%s" % (tool, tool))
            report, split = split_report(world)
            check("L %s: consistent duplicates (per-model + whole-run fragment) -> PASS, "
                  "reported as consistent duplicates" % tool,
                  report["status"] == "PASS" and split["coverage"] == "PASS"
                  and split["membership"] == "PASS"
                  and len(report["split_static_invocations"]["consistent_duplicate_scopes"]) == 2)
        with tempfile.TemporaryDirectory() as tmp:
            # L2: a whole-run fragment alone does not blanket-cover a model whose own
            # summary never ran the tool
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            write_static_summary(world, "m1", ["compiler", tool])
            drop_split_history(world, "m2", tool)
            register_raw_invocation(world, split_invocation(world, tool, None),
                                    "static.%s@tools-%s" % (tool, tool))
            report, split = split_report(world)
            check("L2 %s: a whole-run fragment covers a model only with that model's own "
                  "summary evidence -> m2 stays UNRESOLVED" % tool,
                  scope_status(report, tool, "m1") == "PASS"
                  and scope_status(report, tool, "m2") == "UNRESOLVED"
                  and report["status"] == "UNRESOLVED")
        with tempfile.TemporaryDirectory() as tmp:
            # L3 (review T1-A): a whole-run fragment must not borrow a history
            # entry recorded under ANOTHER condition - the lost per-model
            # fragment of a --replace-tool-entries rerun is a contradiction
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            write_static_summary(world, "m1", ["compiler", tool])
            write_static_summary(world, "m2", ["compiler", tool], replace_tool_entries=[tool])
            register_raw_invocation(world, split_invocation(world, tool, None),
                                    "static.%s@tools-%s" % (tool, tool))
            report, split = split_report(world)
            row = next(r for r in report["split_static_invocations"]["rows"]
                       if r["model_id"] == "m2" and r["tool"] == tool)
            check("L3 %s: m2's history records an execution under a condition no fragment "
                  "carries -> never borrowed by the whole-run fragment: UNRESOLVED (records "
                  "present, invocation missing), noted, never PASS" % tool,
                  scope_status(report, tool, "m2") == "UNRESOLVED" and report["status"] != "PASS"
                  and row["fragments"] == [] and "no fragment carrying that condition" in row["detail"])
        with tempfile.TemporaryDirectory() as tmp:
            # L4: the same rerun WITH its per-model fragment is consistent
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            write_static_summary(world, "m2", ["compiler", tool], replace_tool_entries=[tool])
            register_raw_invocation(world, split_invocation(
                world, tool, ["m2"], replace_tool_entries={"value": True, "source": "CLI"}),
                "static.%s@m2@tools-%s" % (tool, tool))
            report, split = split_report(world)
            # pilot_002 freeze: the fixture contract plans NO methodical CLI
            # overrides, so a --replace-tool-entries rerun fragment is an
            # UNPINNED methodical override: refused by the contract check
            # (effective_invocation FAIL, override plan FAIL); its scope is
            # never PASS on that fragment
            check("L4 %s: a per-model --replace-tool-entries rerun fragment is refused under a "
                  "plan of NONE (effective_invocation FAIL + override plan FAIL), the scope is "
                  "not PASS" % tool,
                  status_of(report, "effective_invocation:static.%s" % tool) == "FAIL"
                  and status_of(report, "methodical_override_plan") == "FAIL"
                  and scope_status(report, tool, "m2") != "PASS" and report["status"] == "FAIL")
        with tempfile.TemporaryDirectory() as tmp:
            # M: contradictory duplicates - both models were executed twice (their
            # histories carry an entry under each condition), once per per-model
            # fragment (default) and once under a whole-run --rerun-gaps fragment
            world = split_world(tmp, tool)
            for model in ("m1", "m2"):
                summary_path = world.model_dir(model) / "static_analysis_summary.json"
                write_static_summary(world, model, ["compiler", tool])
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["invocations"].append(dict(summary["invocations"][0], rerun_gaps=True))
                summary_path.write_text(json.dumps(summary), encoding="utf-8")
            register_raw_invocation(world, split_invocation(
                world, tool, None, rerun_gaps={"value": True, "source": "CLI"}),
                "static.%s@tools-%s" % (tool, tool))
            report, split = split_report(world)
            check("M %s: fragments covering one scope under different conditions -> FAIL" % tool,
                  split["membership"] == "FAIL" and split["coverage"] == "FAIL"
                  and report["status"] == "FAIL"
                  and len(split["contradicting_scopes"]) == 2)
        with tempfile.TemporaryDirectory() as tmp:
            # M2: a per-model fragment covers the scope, but the history records a
            # SECOND execution under a condition no fragment carries -> FAIL
            world = split_world(tmp, tool)
            summary_path = world.model_dir("m1") / "static_analysis_summary.json"
            write_static_summary(world, "m1", ["compiler", tool])
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["invocations"].append(dict(summary["invocations"][0], rerun_gaps=True))
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report, split = split_report(world)
            check("M2 %s: a covered scope whose history records an unregistered second "
                  "execution -> contradiction FAIL" % tool,
                  scope_status(report, tool, "m1") == "FAIL" and report["status"] == "FAIL"
                  and len(split["contradicting_scopes"]) == 1)
        with tempfile.TemporaryDirectory() as tmp:
            # deliberate narrowing evidence: the frozen resolved_config enables a
            # strict subset of the contracted models -> the missing scope is FAIL
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            frag_dir = mf.fragments_dir(intermediate(world), world.run_id)
            manifest_fragment = next(p for p in frag_dir.glob("*.json")
                                     if json.loads(p.read_text(encoding="utf-8")).get("kind") == "global")
            document = json.loads(manifest_fragment.read_text(encoding="utf-8"))
            for model in document["content"]["resolved_config"]["models"]:
                if model["id"] == "m2":
                    model["enabled"] = False
            manifest_fragment.write_text(json.dumps(document), encoding="utf-8")
            mf.write_snapshot(intermediate(world), world.run_id)
            report, split = split_report(world)
            check("narrowing %s: the frozen resolved_config enables a strict subset of the "
                  "contracted models -> the missing scope is FAIL, not UNRESOLVED" % tool,
                  split["coverage"] == "FAIL" and scope_status(report, tool, "m2") == "FAIL"
                  and report["split_static_invocations"]["narrowing"]["narrowed"])
        with tempfile.TemporaryDirectory() as tmp:
            # a recorded config drift on the model list is NOT probative
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            mf.register_fragment(intermediate(world), world.run_id, "drift", "fixture",
                                 {"detected_at_utc": common.utc_now_iso(), "stage": "static_analysis",
                                  "changed_keys": ["models"]}, fingerprint="fixture",
                                 writer="fixture", history=False)
            mf.write_snapshot(intermediate(world), world.run_id)
            report, split = split_report(world)
            check("drift %s: a config drift on the model list carries no model set -> the "
                  "missing scope stays UNRESOLVED and the drift is only noted" % tool,
                  scope_status(report, tool, "m2") == "UNRESOLVED"
                  and not report["split_static_invocations"]["narrowing"]["narrowed"]
                  and report["split_static_invocations"]["narrowing"]["model_list_drift_records"] == 1)
        with tempfile.TemporaryDirectory() as tmp:
            # records missing AND invocation missing: static coverage decides,
            # the split check does not excuse it
            world = split_world(tmp, tool)
            remove_split_invocation(world, tool, "m2")
            drop_split_history(world, "m2", tool)
            path = world.model_dir("m2") / "static_analysis.jsonl"
            records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
                       if l.strip()]
            for record in records:
                record["tools"].pop(tool, None)
            world.rewrite_jsonl(path, records)
            report, split = split_report(world)
            check("records missing %s: static coverage FAILs and the split scope is not "
                  "excused (UNRESOLVED, records_present false)" % tool,
                  status_of(report, "static_coverage:m2") == "FAIL"
                  and scope_status(report, tool, "m2") == "UNRESOLVED"
                  and split["missing_scopes"][0]["records_present"] is False
                  and report["status"] == "FAIL")
    print("== split coverage: report fields ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = split_world(tmp, "parcoach")
        report, split = split_report(world)
        check("the final report carries the machine-readable coverage block",
              all(k in split for k in ("expected_scope_count", "observed_scope_count",
                                       "covered_scope_count", "missing_scopes", "unexpected_scopes",
                                       "contradicting_scopes", "per_tool"))
              and split["policy"] == sr.SPLIT_INVOCATION_COVERAGE_POLICY)
        check("RUNTIME_STAMP_SUBSTITUTES_SPLIT_INVOCATION = false, "
              "RECORD_COVERAGE_SUBSTITUTES_SPLIT_INVOCATION = false",
              sr.RUNTIME_STAMP_SUBSTITUTES_SPLIT_INVOCATION is False
              and sr.RECORD_COVERAGE_SUBSTITUTES_SPLIT_INVOCATION is False)


# ---------------------------------------------------------------------------
# 2. iteration-0 writer attribution (correctness / dynamic)
# ---------------------------------------------------------------------------

NO_DYNAMIC_TOOLS = {"enabled": True, "tools": {
    "asan_ubsan": {"enabled": False}, "tsan": {"enabled": False},
    "memcheck": {"enabled": False}, "must": {"enabled": False},
    "helgrind": {"enabled": False}, "drd": {"enabled": False}}}
ITER0 = dict(SIX_LOOPS, dynamic_analysis=NO_DYNAMIC_TOOLS)


def iter0_world(tmp, stamp_repair=False, **kwargs):
    """Two models, three variants, correctness + dynamic (no dynamic tools:
    the productive dynamic runner still runs and writes its records) - every
    loop terminal at iteration 0. The repair_evaluation invocations are NOT
    pre-registered by the fixture (stamp_repair=False): the productive
    orchestrator registers its own when a loop runs an internal stage, and a
    loop that runs none legitimately has none."""
    world = World(Path(tmp), models=("m1", "m2"), stage_overrides=ITER0, repair_iteration=0,
                  skip_stamps=() if stamp_repair else ("repair_evaluation",), **kwargs)
    return world


class Stubbed:
    """Run the PRODUCTIVE orchestrator._run_analysis_stages with the
    correctness sample runner and the compiler probe stubbed (no compiler on
    the host) and the runtime prober of the fixture world."""

    def __init__(self, world):
        self.world = world

    def __enter__(self):
        from thesis.evaluation import framework, run_correctness

        self.saved = (framework.binary_available, run_correctness.run_sample,
                      sr.enforce_stage)
        framework.binary_available = lambda name: True

        def run_sample(sample, context, launch_overrides, niter, build_timeout, run_timeout):
            return {"schema_version": "correctness.v2", "sample_id": sample.sample_id,
                    "model_id": sample.model_id, "run_id": sample.run_id,
                    "created_at_utc": common.utc_now_iso(),
                    "execution_model": sample.execution_model, "verdict": "pass",
                    "compile": {"ok": True, "exit_code": 0, "timed_out": False,
                                "duration_seconds": 0.1},
                    "runs": [{"argv": ["b.out", "1"], "exit_code": 0, "timed_out": False,
                              "duration_seconds": 0.01, "verdict": "pass"}]}
        run_correctness.run_sample = run_sample
        original_enforce = self.saved[2]

        def enforce(config, run_id, stage, **kwargs):
            kwargs.setdefault("prober", fake_prober)
            return original_enforce(config, run_id, stage, **kwargs)
        sr.enforce_stage = enforce
        # the orchestrator imports enforce_stage through the module attribute
        return self

    def __exit__(self, *exc):
        from thesis.evaluation import framework, run_correctness

        framework.binary_available, run_correctness.run_sample, sr.enforce_stage = self.saved
        return False


def run_internal(world, model, variant, stages, iteration=0):
    """The productive loop runs `stages` internally for `iteration`."""
    loop = world.repair_loop(model, variant)
    with Stubbed(world):
        loop._run_analysis_stages(iteration, stages)
    return loop


def summary_entries(world, model, stage):
    path = world.model_dir(model) / wa.SUMMARY_FILE_NAMES[stage]
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("invocations") or []


def repair_entries(world, model, stage):
    """The repair-written entries of a history (the fixture world writes one
    base entry per history, exactly as the productive base runners do)."""
    entries = summary_entries(world, model, stage)
    return None if entries is None else [e for e in entries if e.get("writer") == "repair"]


def row_of(report, model, variant):
    return next(r for r in report["repair_matrix"]["rows"]
                if (r["model_id"], r["variant"]) == (model, variant))


def test_writer_attribution_module():
    print("== writer attribution: structured block + strict parser ==")
    attribution = wa.repair_attribution("run_x", "m1", "combined_feedback", 0, "correctness",
                                        enforcement={"enforced": True, "contract_sha256": "c" * 64,
                                                     "authorization_sha256": "a" * 64,
                                                     "invocation_sha256": "i" * 64,
                                                     "stage_runtime_sha256": "r" * 64})
    check("attribution binds base run, model, variant, iteration, stage and the enforcement context",
          attribution["base_run_id"] == "run_x" and attribution["model_id"] == "m1"
          and attribution["variant"] == "combined_feedback" and attribution["iteration"] == 0
          and attribution["internal_stage"] == "correctness"
          and attribution["label"] == "repair m1/combined_feedback iteration 0 (internal correctness)"
          and attribution["contract_sha256"] == "c" * 64 and attribution["pre_run_enforced"])
    check("the static label convention is byte-identical to the pre-run enforcement wave",
          wa.repair_label("m", "v", 3, "static") == rs.REPAIR_STATIC_INVOCATION_LABEL % ("m", "v", 3))
    entry = wa.invocation_entry(attribution["label"], attribution, samples=2)
    parsed, problem = wa.parse_entry(entry)
    check("a runner entry with the block parses (structured source)",
          problem is None and parsed["source"] == "structured" and parsed["iteration"] == 0)
    parsed, problem = wa.parse_entry({"label": "repair m1/static_feedback iteration 1 (internal static)"})
    check("a label-only static entry parses strictly (label source)",
          problem is None and parsed["source"] == "label" and parsed["variant"] == "static_feedback")
    parsed, problem = wa.parse_entry({"label": "run_correctness", "writer": "base", "repair_writer": None})
    check("a base runner entry is no attribution and no problem", parsed is None and problem is None)
    for label, entry_, expect in (
        ("malformed: block without fields", {"repair_writer": {"writer": "repair"}}, "lacks"),
        ("malformed: iteration not an integer",
         {"repair_writer": dict(attribution, iteration="0")}, "iteration"),
        ("malformed: label contradicts the block",
         {"label": "repair m2/combined_feedback iteration 0 (internal correctness)",
          "repair_writer": attribution}, "contradicts"),
        ("malformed: unknown stage",
         {"repair_writer": dict(attribution, internal_stage="enhanced",
                                label="repair m1/combined_feedback iteration 0 (internal enhanced)")},
         "unknown"),
        ("malformed: not an object", [1, 2], "not an object"),
    ):
        parsed, problem = wa.parse_entry(entry_)
        check("%s -> problem (%s)" % (label, expect), parsed is None and problem and expect in problem)
    good = wa.invocation_entry(attribution["label"], attribution)
    other_variant = wa.invocation_entry(None, wa.repair_attribution("run_x", "m1", "static_feedback", 0, "correctness"))
    wrong_model = wa.invocation_entry(None, wa.repair_attribution("run_x", "m2", "combined_feedback", 0, "correctness"))
    wrong_run = wa.invocation_entry(None, wa.repair_attribution("run_y", "m1", "combined_feedback", 0, "correctness"))
    over_max = wa.invocation_entry(None, wa.repair_attribution("run_x", "m1", "combined_feedback", 3, "correctness"))
    wrong_variant = wa.invocation_entry(None, wa.repair_attribution("run_x", "m1", "ghost_feedback", 0, "correctness"))
    wrong_stage = wa.invocation_entry(None, wa.repair_attribution("run_x", "m1", "combined_feedback", 0, "dynamic"))
    contradicting = wa.invocation_entry(None, wa.repair_attribution(
        "run_x", "m1", "combined_feedback", 0, "correctness",
        enforcement={"contract_sha256": "d" * 64}))
    kw = dict(internal_stage="correctness", base_run_id="run_x", model_id="m1",
              contracted_variants=ALL_VARIANTS, variant="combined_feedback", max_iterations=2)
    found = wa.repair_iterations([good, good, other_variant], **kw)
    check("O: identical resume entries are one consistent observation; another loop's entry is "
          "neither evidence nor a problem",
          found["iterations"] == [0] and found["duplicates"] == 1 and found["problems"] == [])
    for label, entry_ in (("J: wrong model", wrong_model), ("wrong base run", wrong_run),
                          ("L: iteration beyond max_iterations", over_max),
                          ("K: uncontracted variant", wrong_variant),
                          ("stage recorded under another stage's history", wrong_stage)):
        found = wa.repair_iterations([good, entry_], **kw)
        check("%s -> problem, iterations of the loop unaffected" % label,
              len(found["problems"]) == 1 and found["iterations"] == [0])
    found = wa.repair_iterations([good, contradicting], **kw)
    check("P: two attributions of one label binding different provenance -> problem",
          len(found["problems"]) == 1 and "different provenance" in found["problems"][0]["problem"])
    check("a history that is not a list -> problem",
          [p["problem"] for p in wa.repair_iterations({"x": 1}, **kw)["problems"]]
          == ["invocations is not a list"])
    over_other = wa.invocation_entry(None, wa.repair_attribution("run_x", "m1", "static_feedback", 3, "correctness"))
    found = wa.repair_iterations([good, over_other], **kw)
    check("a problem of ANOTHER loop's entry is attributed to that loop's variant",
          len(found["problems"]) == 1 and found["problems"][0]["variant"] == "static_feedback")
    iter1 = wa.invocation_entry(None, wa.repair_attribution("run_x", "m1", "combined_feedback", 1, "correctness"))
    found = wa.repair_iterations([good, iter1], history_iteration=0, **kw)
    check("an iteration >= 1 entry inside the base run's history (iteration 0) -> problem",
          len(found["problems"]) == 1 and "history of iteration 0" in found["problems"][0]["problem"])
    foreign = wa.invocation_entry(None, wa.repair_attribution("run_x", "m1", "combined_feedback", 0, "correctness",
                                                            enforcement={"contract_sha256": "f" * 64}))
    found = wa.repair_iterations([foreign], contract_sha256="c" * 64, **kw)
    check("an attribution bound to a foreign contract sha -> problem",
          len(found["problems"]) == 1 and "bound to contract" in found["problems"][0]["problem"])
    parsed, problem = wa.parse_entry({"label": "run_correctness", "writer": "repair", "repair_writer": None})
    check("writer=repair without any attribution -> problem", parsed is None and "claims writer=repair" in problem)
    parsed, problem = wa.parse_entry({"label": "repair m1/combined_feedback iteration 0 (internal correctness)",
                                      "writer": "base", "repair_writer": None})
    check("a repair label with writer=base -> problem", parsed is None and "entry.writer" in problem)
    parsed, problem = wa.parse_entry({"label": "repair m1/combined_feedback iteration 0 (internal correctness)"})
    check("a label-only correctness entry (never a productive format) -> problem",
          parsed is None and "without the structured attribution block" in problem)
    parsed, problem = wa.parse_entry({"label": "x", "writer": "unknown"})
    check("an unknown writer value -> problem", parsed is None and "unknown" in problem)


def test_base_runners_write_no_repair_label():
    print("== H/I: the base runners label their invocations as base, never repair ==")
    with tempfile.TemporaryDirectory() as tmp:
        from thesis.evaluation import framework, run_correctness, run_dynamic_analysis

        world = iter0_world(tmp)
        context = framework.EvaluationContext(repo_root=REPO_ROOT, drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
                                              primary_compiler="g++", config=world.config)
        with Stubbed(world):
            run_correctness.run_model(context=context, intermediate_dir=intermediate(world),
                                      run_id=world.run_id, model_id="m1",
                                      output_file_name="correctness.jsonl", launch_overrides=None,
                                      niter=1, build_timeout=10.0, run_timeout=10.0,
                                      invocation_label="run_correctness")
            run_dynamic_analysis.run_model(context=context, intermediate_dir=intermediate(world),
                                           run_id=world.run_id, model_id="m1", tool_settings={},
                                           output_file_name="dynamic_analysis.jsonl",
                                           invocation_label="run_dynamic_analysis --tools <config>")
        for stage in ("correctness", "dynamic"):
            entries = summary_entries(world, "m1", stage)
            check("H/I: the base %s runner writes writer=base and no repair_writer block" % stage,
                  entries is not None and len(entries) == 2 and entries[-1]["writer"] == "base"
                  and entries[-1]["repair_writer"] is None and entries[-1]["status"] == "completed"
                  and wa.parse_entry(entries[-1]) == (None, None)
                  and repair_entries(world, "m1", stage) == [])
        report = world.verify()
        check("... and a base run with such histories verifies PASS (no repair attribution)",
              report["status"] == "PASS"
              and all(r["repair_labelled_correctness_iterations"] == []
                      and r["repair_labelled_dynamic_iterations"] == []
                      for r in report["repair_matrix"]["rows"]))


def test_iteration_zero_attribution_end_to_end():
    print("== iteration-0 writer attribution through the productive orchestrator ==")
    with tempfile.TemporaryDirectory() as tmp:
        # B / C: only correctness missing at iteration 0; the loop fills it;
        # afterwards the records are complete
        world = iter0_world(tmp)
        (world.model_dir("m1") / "correctness.jsonl").unlink()
        loop = world.repair_loop("m1", "combined_feedback")
        check("B: before the internal run, correctness is the only missing stage",
              loop.missing_internal_stages(0) == ["correctness"])
        run_internal(world, "m1", "combined_feedback", ["correctness"])
        check("B: after the internal run the records are complete (missing_internal_stages(0) == [])",
              loop.missing_internal_stages(0) == [])
        entries = repair_entries(world, "m1", "correctness")
        check("24: the productive correctness runner persisted the repair attribution "
              "(model, variant, iteration, stage, contract binding)",
              entries is not None and len(entries) == 1 and entries[0]["writer"] == "repair"
              and entries[0]["status"] == "completed"
              and entries[0]["repair_writer"]["model_id"] == "m1"
              and entries[0]["repair_writer"]["variant"] == "combined_feedback"
              and entries[0]["repair_writer"]["iteration"] == 0
              and entries[0]["repair_writer"]["internal_stage"] == "correctness"
              and entries[0]["repair_writer"]["base_run_id"] == world.run_id
              and entries[0]["repair_writer"]["contract_sha256"] == world.contract["contract_sha256"]
              and entries[0]["label"] == "repair m1/combined_feedback iteration 0 (internal correctness)")
        report = world.verify()
        row = row_of(report, "m1", "combined_feedback")
        check("B: with the repair_evaluation invocation present the loop verifies PASS and the "
              "attribution is read",
              report["status"] == "PASS" and row["status"] == "PASS"
              and row["repair_labelled_correctness_iterations"] == [0]
              and row["invocation_required"] and row["invocation_status"] == "PASS")
        _remove_repair_invocation(world, "m1", "combined_feedback")
        report = world.verify()
        row = row_of(report, "m1", "combined_feedback")
        check("C (core regression): correctness-only iteration-0 repair, records complete, "
              "repair_evaluation invocation deleted -> NON-PASS",
              report["status"] != "PASS" and row["status"] == "UNRESOLVED"
              and row["invocation_status"] == "UNRESOLVED" and row["invocation_required"]
              and row["iteration_zero_analysis"]["records_missing_stages"] == []
              and row["repair_labelled_correctness_iterations"] == [0]
              and scope_check(report) == "UNRESOLVED")
        check("30: the attribution survives complete records - the reason names the correctness "
              "history, not a missing record",
              "correctness_summary.json" in row["iteration_zero_analysis"]["reason"]
              and "do not cover" not in row["iteration_zero_analysis"]["reason"])
        check("... other loops of the same model are not implicated",
              all(r["repair_labelled_correctness_iterations"] == []
                  for r in report["repair_matrix"]["rows"]
                  if (r["model_id"], r["variant"]) != ("m1", "combined_feedback")))
    with tempfile.TemporaryDirectory() as tmp:
        # D / E: only dynamic missing at iteration 0
        world = iter0_world(tmp)
        (world.model_dir("m2") / "dynamic_analysis.jsonl").unlink()
        loop = world.repair_loop("m2", "combined_feedback")
        check("D: before the internal run, dynamic is the only missing stage",
              loop.missing_internal_stages(0) == ["dynamic"])
        run_internal(world, "m2", "combined_feedback", ["dynamic"])
        entries = repair_entries(world, "m2", "dynamic")
        check("25: the productive dynamic runner persisted the repair attribution",
              loop.missing_internal_stages(0) == [] and entries is not None and len(entries) == 1
              and entries[0]["writer"] == "repair"
              and entries[0]["repair_writer"]["internal_stage"] == "dynamic"
              and entries[0]["repair_writer"]["iteration"] == 0
              and entries[0]["label"] == "repair m2/combined_feedback iteration 0 (internal dynamic)")
        report = world.verify()
        check("D: PASS with the invocation present", report["status"] == "PASS"
              and row_of(report, "m2", "combined_feedback")["repair_labelled_dynamic_iterations"] == [0])
        _remove_repair_invocation(world, "m2", "combined_feedback")
        report = world.verify()
        row = row_of(report, "m2", "combined_feedback")
        check("E: dynamic-only iteration-0 repair + deleted invocation -> NON-PASS",
              report["status"] != "PASS" and row["status"] == "UNRESOLVED"
              and row["invocation_required"] and row["repair_labelled_dynamic_iterations"] == [0])
    with tempfile.TemporaryDirectory() as tmp:
        # F: correctness + dynamic missing, static complete
        world = iter0_world(tmp)
        (world.model_dir("m1") / "correctness.jsonl").unlink()
        (world.model_dir("m1") / "dynamic_analysis.jsonl").unlink()
        loop = world.repair_loop("m1", "combined_feedback")
        check("F: correctness and dynamic missing, static complete",
              loop.missing_internal_stages(0) == ["correctness", "dynamic"])
        run_internal(world, "m1", "combined_feedback", ["correctness", "dynamic"])
        _remove_repair_invocation(world, "m1", "combined_feedback")
        report = world.verify()
        row = row_of(report, "m1", "combined_feedback")
        check("F: both stages attributed -> invocation required, NON-PASS without it",
              row["repair_labelled_correctness_iterations"] == [0]
              and row["repair_labelled_dynamic_iterations"] == [0]
              and row["repair_labelled_static_iterations"] == []
              and row["invocation_required"] and report["status"] != "PASS")
    with tempfile.TemporaryDirectory() as tmp:
        # G: everything complete, loop stops at iteration 0, no internal run
        world = iter0_world(tmp)
        report = world.verify()
        check("G: no internal analysis, no writer label, no invocation -> PASS / NOT_APPLICABLE "
              "(no blanket 'every loop needs an invocation')",
              report["status"] == "PASS" and scope_check(report) == "PASS"
              and all(r["invocation_status"] == "NOT_APPLICABLE" and not r["invocation_required"]
                      for r in report["repair_matrix"]["rows"])
              and status_of(report, "effective_invocation:repair_evaluation") == "NOT_APPLICABLE")
    with tempfile.TemporaryDirectory() as tmp:
        # A: static-only regression (existing behaviour must not regress) - the
        # productive static runner is not runnable on the host, so the label
        # is written in the history exactly as run_static_analysis appends it
        world = iter0_world(tmp)
        summary = world.model_dir("m1") / "static_analysis_summary.json"
        summary.write_text(json.dumps({
            "schema_version": "static_analysis_summary.v3", "model_id": "m1",
            "invocations": [wa.invocation_entry(
                rs.REPAIR_STATIC_INVOCATION_LABEL % ("m1", "static_feedback", 0),
                wa.repair_attribution(world.run_id, "m1", "static_feedback", 0, "static"))]}),
            encoding="utf-8")
        report = world.verify()
        row = row_of(report, "m1", "static_feedback")
        check("A: static-only iteration-0 attribution (structured) still keeps the invocation "
              "required -> NON-PASS",
              row["repair_labelled_static_iterations"] == [0] and row["invocation_required"]
              and row["invocation_status"] == "UNRESOLVED" and report["status"] != "PASS")


def test_attribution_fail_closed():
    print("== writer attribution: malformed / wrong identity / unreadable / resume ==")

    def write_history(world, model, stage, entries):
        path = world.model_dir(model) / wa.SUMMARY_FILE_NAMES[stage]
        base = [e for e in (summary_entries(world, model, stage) or []) if e.get("writer") == "base"]
        path.write_text(json.dumps({"schema_version": "fixture", "model_id": model,
                                    "run_id": world.run_id, "invocations": base + entries}),
                        encoding="utf-8")

    def loop_verdict(world, model, variant):
        report = world.verify()
        row = row_of(report, model, variant)
        return report["status"], row["status"], row["writer_attribution_problem"]

    with tempfile.TemporaryDirectory() as tmp:
        world = iter0_world(tmp, stamp_repair=True)
        # the loop under test carries its repair_evaluation invocation (it
        # analysed correctness at iteration 0 in this scenario)
        world.register_repair_invocation("m1", "combined_feedback")
        good = wa.invocation_entry(None, wa.repair_attribution(world.run_id, "m1", "combined_feedback", 0, "correctness"))
        write_history(world, "m1", "correctness", [good, good, good])
        overall, status, problem = loop_verdict(world, "m1", "combined_feedback")
        check("O: three identical resume entries -> no false FAIL (PASS with the invocation)",
              overall == "PASS" and status == "PASS" and problem is None)
        write_history(world, "m1", "correctness", [wa.invocation_entry(
            None, wa.repair_attribution(world.run_id, "m2", "combined_feedback", 0, "correctness"))])
        overall, status, problem = loop_verdict(world, "m1", "combined_feedback")
        check("J: a correctness attribution naming another model inside m1's history -> FAIL",
              overall == "FAIL" and status == "FAIL" and "names model" in problem)
        write_history(world, "m1", "dynamic", [wa.invocation_entry(
            None, wa.repair_attribution(world.run_id, "m1", "ghost_feedback", 0, "dynamic"))])
        write_history(world, "m1", "correctness", [])
        overall, status, problem = loop_verdict(world, "m1", "combined_feedback")
        check("K: a dynamic attribution with an uncontracted variant -> FAIL",
              overall == "FAIL" and status == "FAIL" and "variant" in problem)
        write_history(world, "m1", "dynamic", [wa.invocation_entry(
            None, wa.repair_attribution(world.run_id, "m1", "combined_feedback", 5, "dynamic"))])
        overall, status, problem = loop_verdict(world, "m1", "combined_feedback")
        check("L: an attribution with iteration > max_iterations -> FAIL",
              overall == "FAIL" and status == "FAIL" and "max_iterations" in problem)
        write_history(world, "m1", "dynamic", [{"label": "repair m1/combined_feedback iteration 0 (internal dynamic)",
                                                "repair_writer": {"writer": "repair"}}])
        overall, status, problem = loop_verdict(world, "m1", "combined_feedback")
        check("M: a malformed attribution block -> FAIL (fail-closed)",
              overall == "FAIL" and status == "FAIL" and "lacks" in problem)
        write_history(world, "m1", "dynamic", [])
        (world.model_dir("m1") / "correctness_summary.json").write_text("{not json", encoding="utf-8")
        overall, status, problem = loop_verdict(world, "m1", "combined_feedback")
        check("N: an unreadable attribution history -> NON-PASS (UNRESOLVED), never 'no attribution'",
              overall == "UNRESOLVED" and status == "UNRESOLVED" and "correctness_summary.json" in problem)
        (world.model_dir("m1") / "correctness_summary.json").unlink()
        write_history(world, "m1", "correctness", [
            wa.invocation_entry(None, wa.repair_attribution(
                world.run_id, "m1", "combined_feedback", 0, "correctness",
                enforcement={"contract_sha256": world.contract["contract_sha256"],
                             "authorization_sha256": "a" * 64})),
            wa.invocation_entry(None, wa.repair_attribution(
                world.run_id, "m1", "combined_feedback", 0, "correctness",
                enforcement={"contract_sha256": world.contract["contract_sha256"],
                             "authorization_sha256": "b" * 64}))])
        overall, status, problem = loop_verdict(world, "m1", "combined_feedback")
        check("P: contradicting attributions for one iteration -> FAIL",
              overall == "FAIL" and status == "FAIL"
              and ("different provenance" in problem or "bound to" in problem))
        # T2-F2: a contracted stage whose records exist but whose history is
        # ABSENT is a lost provenance artifact -> UNRESOLVED, never PASS
        (world.model_dir("m1") / "correctness_summary.json").unlink()
        overall, status, problem = loop_verdict(world, "m1", "combined_feedback")
        check("absent correctness history although the stage is contracted and its records exist "
              "-> UNRESOLVED (lost provenance artifact), never PASS",
              overall == "UNRESOLVED" and status == "UNRESOLVED" and "absent" in problem)
        # a problem in the correctness history of m1 concerns m1's loops only
        report = world.verify()
        check("... and a problem in m1's history never touches m2's loops",
              all(r["status"] == "PASS" for r in report["repair_matrix"]["rows"]
                  if r["model_id"] == "m2"))


def test_resume_idempotency():
    print("== resume: a repeated internal run keeps the attribution and adds one entry ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = iter0_world(tmp)
        (world.model_dir("m1") / "correctness.jsonl").unlink()
        run_internal(world, "m1", "combined_feedback", ["correctness"])
        run_internal(world, "m1", "combined_feedback", ["correctness"])
        entries = repair_entries(world, "m1", "correctness")
        report = world.verify()
        row = row_of(report, "m1", "combined_feedback")
        check("41/42: two identical internal runs -> two identical entries, one iteration, no FAIL",
              len(entries) == 2 and entries[0]["repair_writer"] == entries[1]["repair_writer"]
              and row["repair_labelled_correctness_iterations"] == [0]
              and row["iteration_zero_analysis"]["writer_attribution_duplicates"] == 1
              and report["status"] == "PASS")
        check("resume never loses the attribution: the invocation stays required",
              row["invocation_required"] and row["invocation_status"] == "PASS")


def test_malformed_artifacts_never_crash():
    print("== malformed artifacts: a verdict, never a traceback (review T4-01..04, T2-F1) ==")
    corruptions = [
        ("static summary is a JSON list", "static_analysis_summary.json", "[1, 2]"),
        ("static summary is a JSON string", "static_analysis_summary.json", '"x"'),
        ("static summary is JSON null", "static_analysis_summary.json", "null"),
        ("static summary invocations is not a list", "static_analysis_summary.json",
         json.dumps({"model_id": "m1", "invocations": 5})),
        ("static summary tools_run is not a list", "static_analysis_summary.json",
         json.dumps({"model_id": "m1", "invocations": [{"tools_run": 5}]})),
        ("static records with tools that is not an object", "static_analysis.jsonl",
         json.dumps({"sample_id": "s", "tools": 5}) + chr(10)),
        ("correctness history is JSON null", "correctness_summary.json", "null"),
        ("correctness history is a list", "correctness_summary.json", "[]"),
        ("correctness history invocations is a string", "correctness_summary.json",
         json.dumps({"invocations": "abc"})),
    ]
    for label, name, content in corruptions:
        with tempfile.TemporaryDirectory() as tmp:
            world = split_world(tmp, "parcoach")
            (world.model_dir("m1") / name).write_text(content, encoding="utf-8")
            try:
                report, split = split_report(world)
                outcome = report["status"]
            except Exception as exc:  # noqa: BLE001
                outcome = "CRASH(%s: %s)" % (type(exc).__name__, exc)
            check("%s -> a verdict (%s), never a crash" % (label, outcome),
                  outcome in ("FAIL", "UNRESOLVED"))
    # fragments of a wrong shape
    shapes = [
        ("stage is a list", lambda inv: inv.__setitem__("stage", ["static.parcoach"])),
        ("effective_values is a string", lambda inv: inv.__setitem__("effective_values", "x")),
        ("model_scope carries an int", lambda inv: inv.__setitem__("model_scope", [1])),
        ("tools value is a string", lambda inv: inv["effective_values"].__setitem__(
            "tools", {"value": "parcoach", "source": "CLI"})),
        ("owner does not match the body", None),
    ]
    for label, mutate in shapes:
        with tempfile.TemporaryDirectory() as tmp:
            world = split_world(tmp, "parcoach")
            remove_split_invocation(world, "parcoach", "m2")
            inv = split_invocation(world, "parcoach", ["m2"])
            owner = "static.parcoach@m2@tools-parcoach"
            if mutate is None:
                owner = "static.parcoach@m1@tools-parcoach"  # body names m2
                # m1 already has that owner: register under a distinct wrong owner
                owner = "correctness@zzz"
            else:
                mutate(inv)
            try:
                register_raw_invocation(world, inv, owner, refingerprint=False)
                report, split = split_report(world)
                outcome = report["status"]
                unkeyable = report["split_static_invocations"]["unkeyable_fragments"]
            except Exception as exc:  # noqa: BLE001
                outcome, unkeyable = "CRASH(%s: %s)" % (type(exc).__name__, exc), []
            check("fragment %s -> membership FAIL with an unkeyable fragment (%s), never a crash"
                  % (label, outcome),
                  outcome == "FAIL" and len(unkeyable) >= 1)


def test_repair_evaluation_stamp_without_attribution():
    print("== a repair_evaluation runtime stamp with no attributed loop refuses the NOT_APPLICABLE downgrade ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = iter0_world(tmp)
        (world.model_dir("m1") / "correctness.jsonl").unlink()
        run_internal(world, "m1", "combined_feedback", ["correctness"])
        # the attack: lose the fragment AND replace the history by a base-only one
        _remove_repair_invocation(world, "m1", "combined_feedback")
        path = world.model_dir("m1") / "correctness_summary.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["invocations"] = [e for e in document["invocations"] if e.get("writer") == "base"]
        path.write_text(json.dumps(document), encoding="utf-8")
        report = world.verify()
        check("the runtime stamp of repair_evaluation survived (registered only by the loop's own analysis)",
              status_of(report, "stage_runtime:repair_evaluation.main") == "PASS"
              and report["repair_matrix"]["repair_evaluation_stamp_present"])
        check("no loop is attributed, yet the effective_invocation check is NOT downgraded to "
              "NOT_APPLICABLE -> the run stays UNRESOLVED",
              status_of(report, "effective_invocation:repair_evaluation") == "UNRESOLVED"
              and report["status"] == "UNRESOLVED")
    with tempfile.TemporaryDirectory() as tmp:
        # counter-direction: no stamp at all and nothing analysed -> NOT_APPLICABLE
        world = iter0_world(tmp)
        report = world.verify()
        check("without a stamp and without any internal analysis the downgrade still applies",
              status_of(report, "effective_invocation:repair_evaluation") == "NOT_APPLICABLE"
              and not report["repair_matrix"]["repair_evaluation_stamp_present"]
              and report["status"] == "PASS")


def test_round2_regressions():
    print("== round-2 review regressions (R2-SPLIT-01..04, R2-W1..W6, R2-RS-2/3) ==")
    from thesis.evaluation import framework, run_static_analysis
    tool = "parcoach"
    with tempfile.TemporaryDirectory() as tmp:
        # R2-SPLIT-01: an absent / emptied static history next to records is a
        # lost artifact - the scope is at most UNRESOLVED; a hidden rerun can
        # not be laundered by deleting the history afterwards
        world = split_world(tmp, tool)
        summary_path = world.model_dir("m2") / "static_analysis_summary.json"
        write_static_summary(world, "m2", ["compiler", tool])
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["invocations"].append(dict(summary["invocations"][0], rerun_gaps=True))
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        report, split = split_report(world)
        check("R2-SPLIT-01: an unregistered second execution in m2's history -> FAIL",
              scope_status(report, tool, "m2") == "FAIL")
        summary_path.unlink()
        report, split = split_report(world)
        check("R2-SPLIT-01: ... deleting that history does not launder it - an absent history "
              "next to records -> UNRESOLVED, never PASS",
              scope_status(report, tool, "m2") == "UNRESOLVED" and report["status"] != "PASS")
        summary_path.write_text(json.dumps({"model_id": "m2", "invocations": []}), encoding="utf-8")
        report, split = split_report(world)
        check("R2-SPLIT-01: ... an emptied history next to records -> UNRESOLVED",
              scope_status(report, tool, "m2") == "UNRESOLVED" and report["status"] != "PASS")
    with tempfile.TemporaryDirectory() as tmp:
        # R2-SPLIT-02 / R2-W1: a fragment whose content is not an object and a
        # repair_evaluation fragment of a wrong shape -> verdicts, never a crash
        world = split_world(tmp, tool)
        mf.register_fragment(intermediate(world), world.run_id, "invocation",
                             "static.parcoach@m9@tools-parcoach", [1, 2], fingerprint="a" * 64,
                             writer="fixture", history=False)
        mf.register_fragment(intermediate(world), world.run_id, "invocation",
                             "repair_evaluation@m1@variant-zzz",
                             {"schema_version": "effective_stage_invocation.v1",
                              "stage": "repair_evaluation", "run_id": world.run_id,
                              "model_scope": [1], "effective_values": "x",
                              "invocation_sha256": "b" * 64},
                             fingerprint="b" * 64, writer="fixture", history=False)
        mf.write_snapshot(intermediate(world), world.run_id)
        try:
            report, split = split_report(world)
            outcome = report["status"]
        except Exception as exc:  # noqa: BLE001
            outcome = "CRASH(%s: %s)" % (type(exc).__name__, exc)
        check("R2-SPLIT-02/W1: a non-object split fragment and a malformed repair_evaluation "
              "fragment -> FAIL verdict (%s), never a crash" % outcome, outcome == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        # R2-SPLIT-03: narrowing evidence FAILs only the models the frozen
        # config disabled; a merely missing enabled model stays UNRESOLVED
        world = split_world(tmp, tool, models=("m1", "m2", "m3"))
        remove_split_invocation(world, tool, "m2")
        remove_split_invocation(world, tool, "m3")
        frag_dir = mf.fragments_dir(intermediate(world), world.run_id)
        manifest_fragment = next(q for q in frag_dir.glob("*.json")
                                 if json.loads(q.read_text(encoding="utf-8")).get("kind") == "global")
        document = json.loads(manifest_fragment.read_text(encoding="utf-8"))
        for model in document["content"]["resolved_config"]["models"]:
            if model["id"] == "m3":
                model["enabled"] = False
        manifest_fragment.write_text(json.dumps(document), encoding="utf-8")
        mf.write_snapshot(intermediate(world), world.run_id)
        report, split = split_report(world)
        check("R2-SPLIT-03: the disabled model's missing scope is FAIL, the enabled model's "
              "missing scope stays UNRESOLVED (%s / %s)"
              % (scope_status(report, tool, "m3"), scope_status(report, tool, "m2")),
              scope_status(report, tool, "m3") == "FAIL"
              and scope_status(report, tool, "m2") == "UNRESOLVED")
    with tempfile.TemporaryDirectory() as tmp:
        # R2-W3: a present history without any entry next to records, and a
        # history naming another model -> UNRESOLVED (never PASS)
        world = iter0_world(tmp)
        path = world.model_dir("m1") / "correctness_summary.json"
        path.write_text(json.dumps({"schema_version": "correctness_summary.v1",
                                    "run_id": world.run_id, "model_id": "m1",
                                    "invocations": []}), encoding="utf-8")
        report = world.verify()
        row = row_of(report, "m1", "combined_feedback")
        check("R2-W3: an entry-less correctness history next to records -> UNRESOLVED",
              row["status"] == "UNRESOLVED" and report["status"] != "PASS"
              and "carries no invocation entry" in row["writer_attribution_problem"])
        path.write_text(json.dumps({"schema_version": "correctness_summary.v1",
                                    "run_id": world.run_id, "model_id": "m2",
                                    "invocations": [wa.invocation_entry("run_correctness", None)]}),
                        encoding="utf-8")
        report = world.verify()
        row = row_of(report, "m1", "combined_feedback")
        check("R2-W3: a history naming another model inside m1's directory -> UNRESOLVED",
              row["status"] == "UNRESOLVED" and report["status"] != "PASS"
              and "names model_id" in row["writer_attribution_problem"])
    with tempfile.TemporaryDirectory() as tmp:
        # R2-W4(2): a repair_evaluation invocation nothing explains -> UNRESOLVED
        world = iter0_world(tmp)
        world.register_repair_invocation("m1", "combined_feedback")
        report = world.verify()
        row = row_of(report, "m1", "combined_feedback")
        check("R2-W4: a repair_evaluation invocation with no analysed iteration, no wave evidence "
              "and no writer attribution -> UNRESOLVED (its writer provenance is lost)",
              row["invocation_status"] == "UNRESOLVED" and row["status"] == "UNRESOLVED"
              and "no analysis explains it" in row["detail"] and report["status"] == "UNRESOLVED")
        # R2-W5: the frozen contract declares the provenance policies
        policies = world.contract.get("provenance_policies") or {}
        check("R2-W5: the frozen contract declares the writer-attribution and split-coverage policies",
              policies.get("writer_attribution") == wa.REPAIR_WRITER_ATTRIBUTION_VERSION
              and policies.get("split_invocation_coverage") == sr.SPLIT_INVOCATION_COVERAGE_POLICY
              and policies.get("iteration_zero_writer_attribution")
              == rs.ITERATION_ZERO_WRITER_ATTRIBUTION_POLICY)
    with tempfile.TemporaryDirectory() as tmp:
        # R2-W2 / R2-RS-3: a failing close never wipes the dynamic history
        world = iter0_world(tmp)
        (world.model_dir("m2") / "dynamic_analysis.jsonl").unlink()
        saved = wa.close_invocation

        def failing_close(*args, **kwargs):
            raise OSError("fixture: atomic replace failed")
        wa.close_invocation = failing_close
        try:
            run_internal(world, "m2", "combined_feedback", ["dynamic"])
        finally:
            wa.close_invocation = saved
        entries = summary_entries(world, "m2", "dynamic")
        check("R2-W2/RS-3: dynamic close failure - the base entry, the INVOKED repair entry and a "
              "COMPLETED repair entry carrying its identity all survive",
              entries is not None and [e.get("writer") for e in entries] == ["base", "repair", "repair"]
              and entries[1]["status"] == wa.STATUS_INVOKED
              and entries[-1]["status"] == wa.STATUS_COMPLETED
              and entries[-1].get("opened_entry_lost") is True
              and entries[-1]["repair_writer"]["internal_stage"] == "dynamic"
              and entries[-1]["repair_writer"]["variant"] == "combined_feedback")
        report = world.verify()
        row = row_of(report, "m2", "combined_feedback")
        check("R2-W2/RS-3: ... and the verifier still attributes iteration 0 to the repair loop",
              row["repair_labelled_dynamic_iterations"] == [0] and row["invocation_required"])
    with tempfile.TemporaryDirectory() as tmp:
        # R2-RS-2: a hostile deeply nested sidecar (RecursionError inside the
        # JSON parser) never aborts the correctness stage
        world = iter0_world(tmp)
        (world.model_dir("m1") / "correctness_summary.json").write_text("[" * 100000, encoding="utf-8")
        (world.model_dir("m1") / "correctness.jsonl").unlink()
        try:
            run_internal(world, "m1", "combined_feedback", ["correctness"])
            outcome = "ran"
        except Exception as exc:  # noqa: BLE001
            outcome = "CRASH(%s)" % type(exc).__name__
        check("R2-RS-2: a deeply nested sidecar does not abort the correctness stage (%s), the "
              "records are produced" % outcome,
              outcome == "ran" and (world.model_dir("m1") / "correctness.jsonl").is_file())
        document = json.loads((world.model_dir("m1") / "correctness_summary.json").read_text(encoding="utf-8"))
        check("R2-RS-2: ... the history was rebuilt with the unreadable bytes kept and the repair entry",
              document.get("unreadable_previous", "").startswith("[[[")
              and [e["writer"] for e in document["invocations"]] == ["repair"]
              and document["invocations"][0]["status"] == wa.STATUS_COMPLETED)
        report = world.verify()
        row = row_of(report, "m1", "combined_feedback")
        check("R2-RS-2: ... and the verifier reports the unreadable earlier history (UNRESOLVED, "
              "never PASS)", row["status"] == "UNRESOLVED" and report["status"] != "PASS"
              and "unreadable_previous" in row["writer_attribution_problem"])
    with tempfile.TemporaryDirectory() as tmp:
        # R2-W6: the productive static runner keeps an unreadable predecessor
        # under unreadable_previous and never aborts on it (empty tool set on
        # the host: records without tool entries, the history append is real)
        world = iter0_world(tmp)
        summary_path = world.model_dir("m1") / "static_analysis_summary.json"
        summary_path.write_text("{not json", encoding="utf-8")
        (world.model_dir("m1") / "static_analysis.jsonl").unlink()
        context = framework.EvaluationContext(repo_root=REPO_ROOT,
                                              drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
                                              primary_compiler="g++", config=world.config)
        run_static_analysis.run_model(context=context, intermediate_dir=intermediate(world),
                                      run_id=world.run_id, model_id="m1", tool_settings={},
                                      expected_tools={}, invocation_label="fixture static",
                                      writer_attribution=wa.repair_attribution(
                                          world.run_id, "m1", "combined_feedback", 0, "static"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        check("R2-W6: the static runner keeps an unreadable predecessor under unreadable_previous "
              "and appends the attributed entry",
              summary.get("unreadable_previous", "").startswith("{not json")
              and [i["label"] for i in summary["invocations"]] == ["fixture static"]
              and summary["invocations"][0]["writer"] == "repair"
              and summary["invocations"][0]["repair_writer"]["internal_stage"] == "static")


def test_policies_and_preflight():
    print("== policies exposed to the preflight ==")
    check("ITERATION_ZERO_COVERAGE_RESIDUAL = CLOSED_BY_WRITER_ATTRIBUTION",
          rs.ITERATION_ZERO_COVERAGE_RESIDUAL == "CLOSED_BY_WRITER_ATTRIBUTION")
    check("split coverage policy exported", sr.SPLIT_INVOCATION_COVERAGE_POLICY
          == "split_static_invocation_coverage.v1")
    from thesis.evaluation import pilot_preflight, pilot_run_contract
    from thesis.config.load_config import load_config

    config = load_config(REPO_ROOT / "thesis" / "config" / "config.yaml")
    contract = pilot_run_contract.build_contract(REPO_ROOT / "thesis" / "config" / "config.yaml",
                                                 "pilot")
    lines = pilot_preflight.technical_provenance_lines(contract, config)
    text = "\n".join(lines)
    check("preflight reports STATIC_SPLIT_INVOCATION_COVERAGE_READY = true",
          "STATIC_SPLIT_INVOCATION_COVERAGE_READY = true" in text)
    check("preflight reports ITERATION_ZERO_WRITER_ATTRIBUTION_READY = true",
          "ITERATION_ZERO_WRITER_ATTRIBUTION_READY = true" in text)
    check("preflight reports TECHNICAL_PROVENANCE_CLEANUP_READY = true",
          "TECHNICAL_PROVENANCE_CLEANUP_READY = true" in text)
    expected = sr.expected_split_static_invocations(contract)
    n_models = len(contract["model_ids"])
    check("the productive contract view expects one PARCOACH and one LLOV scope per enabled "
          "model (%d), derived - not hard-coded" % n_models,
          expected["per_tool"]["parcoach"]["scope_count"] == n_models
          and expected["per_tool"]["llov"]["scope_count"] == n_models
          and expected["per_tool"]["parcoach"]["applicable_execution_models"] == ["mpi"]
          and expected["per_tool"]["llov"]["applicable_execution_models"] == ["omp"])


def test_interrupted_internal_run_stays_attributed():
    print("== an interrupted repair-internal run leaves partial records attributed to repair ==")
    from thesis.evaluation import run_correctness

    with tempfile.TemporaryDirectory() as tmp:
        world = iter0_world(tmp)
        (world.model_dir("m1") / "correctness.jsonl").unlink()
        loop = world.repair_loop("m1", "combined_feedback")
        calls = {"n": 0}

        def failing_run_sample(sample, context, launch_overrides, niter, build_timeout, run_timeout):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("fixture: runner interrupted after the first sample")
            return {"schema_version": "correctness.v2", "sample_id": sample.sample_id,
                    "model_id": sample.model_id, "run_id": sample.run_id,
                    "created_at_utc": common.utc_now_iso(),
                    "execution_model": sample.execution_model, "verdict": "pass",
                    "compile": {"ok": True, "exit_code": 0, "timed_out": False, "duration_seconds": 0.1},
                    "runs": []}
        with Stubbed(world):
            run_correctness.run_sample = failing_run_sample
            try:
                loop._run_analysis_stages(0, ["correctness"])
                interrupted = False
            except RuntimeError:
                interrupted = True
        entries = repair_entries(world, "m1", "correctness")
        records = (world.model_dir("m1") / "correctness.jsonl").read_text(encoding="utf-8").strip().splitlines()
        check("the runner was interrupted after one record",
              interrupted and len(records) == 1)
        check("the history carries an INVOKED (never completed) repair entry for the partial records",
              entries is not None and len(entries) == 1 and entries[0]["status"] == wa.STATUS_INVOKED
              and entries[0]["writer"] == "repair"
              and entries[0]["repair_writer"]["internal_stage"] == "correctness")
        report = world.verify()
        row = row_of(report, "m1", "combined_feedback")
        check("the verifier attributes the partial stage to repair (invocation required) while "
              "record coverage - not the attribution - decides completion (correctness_coverage FAIL)",
              row["repair_labelled_correctness_iterations"] == [0] and row["invocation_required"]
              and status_of(report, "correctness_coverage:m1") == "FAIL" and report["status"] == "FAIL")
        # a completed run afterwards (resume) closes its own entry and keeps the interrupted one
        (world.model_dir("m1") / "correctness.jsonl").unlink()
        run_internal(world, "m1", "combined_feedback", ["correctness"])
        entries = repair_entries(world, "m1", "correctness")
        check("the resumed run adds a COMPLETED entry and keeps the interrupted one",
              [e["status"] for e in entries] == [wa.STATUS_INVOKED, wa.STATUS_COMPLETED]
              and entries[1]["samples"] == 2)
        report = world.verify()
        check("... and the loop verifies PASS with its invocation present",
              report["status"] == "PASS" and row_of(report, "m1", "combined_feedback")["status"] == "PASS")


def main() -> int:
    for test in (test_split_expected_set_contract_derived, test_split_coverage_matrix,
                 test_writer_attribution_module, test_base_runners_write_no_repair_label,
                 test_iteration_zero_attribution_end_to_end, test_attribution_fail_closed,
                 test_resume_idempotency, test_interrupted_internal_run_stays_attributed,
                 test_malformed_artifacts_never_crash, test_repair_evaluation_stamp_without_attribution,
                 test_round2_regressions, test_policies_and_preflight):
        test()
    if FAILURES:
        print("\n%d of %d checks FAILED:" % (len(FAILURES), CHECKS))
        for failure in FAILURES:
            print("  - " + failure)
        return 1
    print("\nAll %d technical-provenance-cleanup checks passed." % CHECKS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
