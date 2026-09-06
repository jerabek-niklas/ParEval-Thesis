"""Post-run verification fixtures A-Q + T0 contract guard tests
(pilot_002 pre-run wave, GATE 3).

A synthetic mini-run is built with the REAL production code (assembly,
run manifest fragments, contract builder) and then mutated one property at
a time. The verifier must PASS the exact run, FAIL every drift, and report
UNRESOLVED - never a false PASS - where the evidence is absent.

Run:  python thesis/evaluation/test_post_run_verification.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from thesis.assembly import assemble_sources  # noqa: E402
from thesis.assembly import assembly_provenance as ap  # noqa: E402
from thesis.enhanced_tests import execution_provenance as ep  # noqa: E402
from thesis.enhanced_tests.specs import build_benchmark_specs  # noqa: E402
from thesis.evaluation import atomic_io, pilot_run_contract, run_manifest, verify_pilot_run  # noqa: E402
from thesis.generation import common  # noqa: E402

FAILURES = []

MODEL = "m1"
RUN_ID = "pilot_002_fixture"
BENCHMARK = ("transform", "55_transform_relu")
BENCHMARK2 = ("reduce", "25_reduce_xor")
PROMPT_TEXT = ("#include <vector>\n/* fixture prompt */\n"
               "void relu(std::vector<double> &x) {")
PROMPT_TEXT2 = ("#include <vector>\n/* fixture prompt 2 */\n"
                "int xorOf(std::vector<int> const& x) {")
RAW = "```cpp\nvoid relu(std::vector<double> &x) {\n  for (auto &v : x) v = v > 0 ? v : 0;\n}\n```"
RAW2 = "```cpp\nint xorOf(std::vector<int> const& x) {\n  int r = 0;\n  for (int v : x) r ^= v;\n  return r;\n}\n```"


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def sample_id(benchmark, index=0):
    return "%s__%s__%s__serial__sample_%d" % (MODEL, benchmark[0], benchmark[1], index)


def generation_record(benchmark, prompt_text, raw_text):
    return {
        "sample_id": sample_id(benchmark),
        "prompt": {"problem_type": benchmark[0], "name": benchmark[1],
                   "parallelism_model": "serial", "language": "cpp",
                   "prompt_text": prompt_text},
        "output": {"raw_text": raw_text, "cleaned_code": raw_text},
        "status": {"success": True, "truncated": False, "error_type": None,
                   "duration_seconds": 1.5, "timing_mode": "direct",
                   "timing_clock": "perf_counter"},
        "api_response": {"usage_normalized": {"input_tokens": 10, "output_tokens": 20,
                                              "reasoning_tokens": 0}},
        "generation_parameters": {"sample_index": 0},
    }


class World:
    """A complete, contract-conform mini run on disk."""

    def __init__(self, root: Path, run_id: str = RUN_ID,
                 contract_run_id: "str | None" = None,
                 models=(MODEL,), samples=(BENCHMARK, BENCHMARK2)):
        self.root = Path(root)
        self.run_id = run_id
        self.models = list(models)
        self.samples = list(samples)
        self.config_path = self.root / "config.yaml"
        self.contract_path = self.root / "frozen_contract.json"
        self.prompts_path = self.root / "prompts.json"
        self._write_prompts()
        self._write_config()
        from thesis.config.load_config import load_config

        self.config = load_config(self.config_path)
        self._write_generations()
        self._freeze_contract(contract_run_id)
        self._assemble()
        self._bind_contract()
        self._write_stage_records()

    # ---- construction -------------------------------------------------
    def _write_prompts(self):
        atomic_io.atomic_write_json(self.prompts_path, [
            {"problem_type": BENCHMARK[0], "name": BENCHMARK[1], "language": "cpp",
             "parallelism_model": "serial", "prompt": PROMPT_TEXT},
            {"problem_type": BENCHMARK2[0], "name": BENCHMARK2[1], "language": "cpp",
             "parallelism_model": "serial", "prompt": PROMPT_TEXT2},
        ])

    def _write_config(self):
        config = {
            "outputs": {"raw_dir": (self.root / "raw").as_posix(),
                        "intermediate_dir": (self.root / "intermediate").as_posix(),
                        "root": (self.root / "results").as_posix()},
            "prompts": {"path": self.prompts_path.as_posix(), "prompt_field": "prompt",
                        "execution_models": ["serial"], "problem_types": None},
            "profiles": {"fixture": {"run_id": self.run_id, "selection": "prefix",
                                     "prompt_limit": 2, "num_samples_per_prompt": 1}},
            "models": [{"id": model, "enabled": True} for model in self.models],
            "generation_defaults": {"timeout_seconds": 300, "retry_attempts": 2},
            "stages": {
                "assembly": {"enabled": True, "auto_close_single_brace": True,
                             "output_file_name": "assembly.jsonl"},
                "correctness_tests": {"enabled": True, "niter": 1,
                                      "run_timeout_seconds": 120,
                                      "output_file_name": "correctness.jsonl"},
                "static_analysis": {"enabled": True, "tools": {
                    "compiler": {"enabled": True},
                    "clang_tidy": {"enabled": False}, "gcc_analyzer": {"enabled": False},
                    "cppcheck": {"enabled": False}, "infer": {"enabled": False},
                    "parcoach": {"enabled": False}, "llov": {"enabled": False}}},
                "dynamic_analysis": {"enabled": False, "tools": {}},
                # the REAL frozen spec file, so the manifest's spec pin and the
                # contract's enhanced_frozen_specs_sha256 describe the same set
                "enhanced_tests": {"enabled": True, "execution_models": ["serial"],
                                   "target_cases_per_benchmark": 2,
                                   "static_base_sizes": [0, 1],
                                   "specs_file": (REPO_ROOT / "thesis" / "enhanced_tests"
                                                  / "frozen" / "e3_final_specs.jsonl").as_posix()},
                "repair": {"enabled": True, "max_iterations": 2,
                           "variants": ["static_feedback"]},
            },
        }
        self.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        (self.root / "specs.jsonl").write_text("", encoding="utf-8")

    def _write_generations(self):
        for model in self.models:
            path = Path(self.config["outputs"]["raw_dir"]) / self.run_id / model / "generations.jsonl"
            if path.exists():
                path.unlink()
            for benchmark, prompt_text, raw in ((BENCHMARK, PROMPT_TEXT, RAW),
                                                (BENCHMARK2, PROMPT_TEXT2, RAW2)):
                if benchmark in self.samples:
                    common.append_jsonl(path, generation_record(benchmark, prompt_text, raw))

    def _freeze_contract(self, contract_run_id):
        contract = pilot_run_contract.build_contract(
            self.config_path, "fixture", run_id_override=contract_run_id)
        # the population decision is open repo-wide, so the fixture freezes a
        # DRAFT: what is under test is the VERIFIER, not the open decision
        self.contract_sha = pilot_run_contract.freeze_contract(
            contract, self.contract_path, allow_draft=True)
        self.contract = pilot_run_contract.load_frozen(self.contract_path)

    def _assemble(self):
        run_manifest.ensure_run_manifest(self.config, self.run_id, stage="assembly",
                                         profile="fixture", primary_compiler="g++")
        for model in self.models:
            assemble_sources.assemble_model(self.config, {"run_id": self.run_id},
                                            {"id": model}, False, register_manifest=True)

    def _bind_contract(self, contract=None, sha=None, runtime=True):
        run_manifest.register_contract(self.config, self.run_id,
                                       sha or self.contract_sha, contract or self.contract)
        # the analysis stages register their conditions during a real run
        conditions = self.contract.get("conditions") or {}
        run_manifest.register_static_condition(
            self.config, self.run_id, conditions["static_analysis_condition_sha256"],
            {"fixture": "static"})
        run_manifest.register_repair_condition(
            self.config, self.run_id, conditions["repair_condition_sha256"],
            {"fixture": "repair"})
        if runtime:
            conditions = self.contract.get("conditions") or {}
            run_manifest.register_runtime_evidence(self.config, self.run_id, OrderedDict([
                ("evidence_version", "t0_runtime_evidence.v1"),
                ("contract_sha256", self.contract_sha),
                ("static_repair_runtime_condition_sha256",
                 conditions.get("static_repair_runtime_condition_sha256")),
                ("main_image_identity_live", {"image_id": "sha256:fixture"}),
            ]))

    def _write_stage_records(self):
        for model in self.models:
            model_dir = self.model_dir(model)
            for entry in self.assembled(model):
                sid = entry["sample_id"]
                common.append_jsonl(model_dir / "correctness.jsonl", {
                    "schema_version": "correctness.v2", "sample_id": sid, "model_id": model,
                    "run_id": self.run_id, "execution_model": "serial", "verdict": "pass",
                    "compile": {"ok": True, "exit_code": 0, "timed_out": False,
                                "duration_seconds": 2.0},
                    "runs": [{"argv": ["b.out", "1"], "exit_code": 0, "timed_out": False,
                              "duration_seconds": 0.01, "verdict": "pass"}]})
                common.append_jsonl(model_dir / "static_analysis.jsonl", {
                    "schema_version": "static_analysis.v3", "sample_id": sid,
                    "model_id": model, "run_id": self.run_id, "execution_model": "serial",
                    "tools": {"compiler": self.tool_entry("COMPLETED")}})
                for spec in self.expected_specs(entry):
                    common.append_jsonl(model_dir / "enhanced_tests.jsonl", {
                        "schema_version": "enhanced.v3", "sample_id": sid, "model_id": model,
                        "run_id": self.run_id, "execution_model": "serial",
                        "benchmark": entry.get("benchmark"), "spec": spec,
                        "status": "pass", "exit_code": 0, "duration_seconds": 0.01})
            self.register_enhanced_fingerprint(model)

    def tool_entry(self, state, error=None):
        return {"tool": "compiler", "ran": True, "exit_code": 0, "num_findings": 0,
                "num_blocking": 0, "num_low_confidence": 0, "duration_seconds": 0.5,
                "findings": [], "error": error, "analysis_state": state,
                "tool_state_schema": "tool_state.v1"}

    def expected_specs(self, entry):
        return build_benchmark_specs(entry.get("benchmark"), [], self.config)

    def register_enhanced_fingerprint(self, model):
        global_fingerprint = {"enhanced_execution_fingerprint_sha256": "f" * 64,
                              "components": {"fixture": True}}
        # the global fingerprint is registered as the run's enhanced execution
        # condition, the per-model one includes the candidate source hashes
        from thesis.evaluation import manifest_fragments as mf

        mf.register_fragment(Path(self.config["outputs"]["intermediate_dir"]), self.run_id,
                             "enhanced_execution", None, global_fingerprint,
                             fingerprint=global_fingerprint["enhanced_execution_fingerprint_sha256"],
                             writer="fixture")
        candidate = ep.candidate_source_fingerprint(
            Path(self.config["outputs"]["intermediate_dir"]), self.run_id, model, REPO_ROOT)
        sha = ep.model_fingerprint_sha(
            ep.model_execution_fingerprint(global_fingerprint, candidate))
        run_manifest.register_model_execution(self.config, self.run_id, model, sha)
        mf.write_snapshot(Path(self.config["outputs"]["intermediate_dir"]), self.run_id)

    # ---- accessors ----------------------------------------------------
    def model_dir(self, model=MODEL, run_id=None):
        return Path(self.config["outputs"]["intermediate_dir"]) / (run_id or self.run_id) / model

    def raw_dir(self, model=MODEL, run_id=None):
        return Path(self.config["outputs"]["raw_dir"]) / (run_id or self.run_id) / model

    def entries(self, model=MODEL, run_id=None):
        return ap.load_assembly_entries(self.model_dir(model, run_id) / "assembly.jsonl")

    def assembled(self, model=MODEL):
        return [e for e in self.entries(model) if e.get("assembled")]

    def source(self, sid, model=MODEL):
        return self.model_dir(model) / "sources" / sid / "generated-code.hpp"

    def rewrite_jsonl(self, path, records):
        atomic_io.atomic_write_jsonl(path, records)

    def verify(self, run_id=None, contract=True, skip_enhanced=False):
        return verify_pilot_run.verify(self.config, run_id or self.run_id,
                                       self.contract_path if contract else None,
                                       skip_enhanced=skip_enhanced)


def status_of(report, prefix):
    for entry in report["checks"]:
        if entry["check"] == prefix or entry["check"].startswith(prefix + ":"):
            return entry["status"]
    return None


def fixture(label, mutate, expected_status, expected_check=None, expected_check_status="FAIL",
            run_id=None, skip_enhanced=False):
    """Build a pristine world, apply one mutation, verify."""
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        target_run = mutate(world) if mutate else None
        report = world.verify(run_id=target_run or run_id, skip_enhanced=skip_enhanced)
        ok = report["status"] == expected_status
        detail = ""
        if expected_check:
            actual = status_of(report, expected_check)
            ok = ok and actual == expected_check_status
            detail = " (%s -> %s)" % (expected_check, actual)
        if not ok:
            detail += " | overall %s, failing checks: %s" % (
                report["status"],
                [(c["check"], c["status"], c["detail"][:70]) for c in report["checks"]
                 if c["status"] != "PASS"][:6])
        check("%s -> %s%s" % (label, expected_status, detail), ok)
        return report


def main():
    print("== A: the exact run verifies ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        report = world.verify()
        check("A: exact run -> PASS", report["status"] == "PASS")
        if report["status"] != "PASS":
            for entry in report["checks"]:
                if entry["status"] != "PASS":
                    print("     %s %s: %s" % (entry["status"], entry["check"], entry["detail"]))
        check("A: every contracted area is checked",
              {"contract_present", "run_id_matches_contract", "base_run_is_not_a_repair_iteration",
               "contract_sha_bound_to_run", "model_set_exact", "primary_compiler",
               "run_timeout_seconds", "execution_models", "runtime_evidence_bound_at_t0",
               "repair_iterations_separate_from_base"}
              <= {c["check"] for c in report["checks"]}
              and all(any(c["check"].startswith(p + ":") for c in report["checks"])
                      for p in ("population_count", "population_selection", "prompt_fingerprints",
                                "assembly_integrity", "assembly_set_registered",
                                "assembly_condition", "correctness_coverage", "static_coverage",
                                "enhanced_coverage", "enhanced_source_drift")))
        check("A: verification report is written as post_run_verification.v1",
              report["schema_version"] == "post_run_verification.v1"
              and report["verifier_version"] == "verify_pilot_run.v1"
              and report["contract_sha256"] == world.contract_sha)

    print("== B-Q: every drift is caught ==")

    def wrong_run_id(world):
        # the frozen contract names another run
        contract = pilot_run_contract.build_contract(world.config_path, "fixture",
                                                     run_id_override="pilot_002_other")
        world.contract_sha = pilot_run_contract.freeze_contract(
            contract, world.contract_path, allow_draft=True)
        return None

    fixture("B: wrong run_id", wrong_run_id, "FAIL", "run_id_matches_contract")

    def missing_model(world):
        shutil.rmtree(world.raw_dir(MODEL))

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), models=(MODEL, "m2"))
        shutil.rmtree(world.raw_dir("m2"))
        report = world.verify()
        check("C: missing model -> FAIL", report["status"] == "FAIL"
              and status_of(report, "model_set_exact") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        extra = world.raw_dir("m_unexpected")
        common.append_jsonl(extra / "generations.jsonl",
                            generation_record(BENCHMARK, PROMPT_TEXT, RAW))
        report = world.verify()
        check("D: unexpected extra model -> FAIL", report["status"] == "FAIL"
              and status_of(report, "model_set_exact") == "FAIL")

    def wrong_sample_count(world):
        path = world.raw_dir() / "generations.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        world.rewrite_jsonl(path, records[:1])

    fixture("E: sample count below the contract", wrong_sample_count, "FAIL", "population_count")

    def prompt_drift(world):
        path = world.raw_dir() / "generations.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        records[0]["prompt"]["prompt_text"] = PROMPT_TEXT + "\n// edited after the freeze\n"
        world.rewrite_jsonl(path, records)

    fixture("F: prompt text drifted from the contract", prompt_drift, "FAIL", "prompt_fingerprints")

    def tamper_source(world):
        source = world.source(world.assembled()[0]["sample_id"])
        source.write_bytes(source.read_bytes() + b"// tampered after the run\n")

    fixture("G: assembled source bytes drifted from the record", tamper_source, "FAIL",
            "assembly_integrity")

    def assembly_set_drift(world):
        entries = world.entries()
        entries[0]["source_sha256"] = "0" * 64
        world.rewrite_jsonl(world.model_dir() / "assembly.jsonl", entries)

    fixture("G2: per-model assembly set fingerprint drift", assembly_set_drift, "FAIL",
            "assembly_set_registered")

    def orphan_source(world):
        orphan = world.model_dir() / "sources" / "ghost__serial__sample_0" / "generated-code.hpp"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"int ghost;\n")

    fixture("H: orphan source without a record", orphan_source, "FAIL", "assembly_integrity")

    def fabricated_assembly_record(world):
        # an assembly record (and source) for a sample that has no generation
        # record at all: candidate code from nowhere
        entries = world.entries()
        ghost = dict([e for e in entries if e.get("assembled")][0])
        ghost["sample_id"] = "m1__reduce__25_reduce_xor__serial__sample_9"
        ghost["logical_source_path"] = ap.logical_source_path(MODEL, ghost["sample_id"])
        source = world.source(ghost["sample_id"])
        source.parent.mkdir(parents=True, exist_ok=True)
        data = b"int fabricated;\n"
        source.write_bytes(data)
        ghost["source_sha256"] = ap.ch.raw_sha256_bytes(data)
        ghost["byte_size"] = len(data)
        entries.append(ghost)
        world.rewrite_jsonl(world.model_dir() / "assembly.jsonl", entries)

    fixture("H2: assembly record without a generation record", fabricated_assembly_record,
            "FAIL", "assembly_integrity")

    def missing_correctness(world):
        path = world.model_dir() / "correctness.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        world.rewrite_jsonl(path, records[:1])

    fixture("I: a sample without a correctness record", missing_correctness, "FAIL",
            "correctness_coverage")

    def static_gap(world):
        path = world.model_dir() / "static_analysis.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        records[0]["tools"]["compiler"] = world.tool_entry("NOT_ANALYZED", error="timeout")
        world.rewrite_jsonl(path, records)

    report = fixture("J: terminal static gap state is a coverage limitation, not a failure",
                     static_gap, "PASS", "static_coverage", "PASS")
    for entry in report["checks"]:
        if entry["check"].startswith("static_coverage:"):
            check("J: the coverage limitation is REPORTED",
                  entry["evidence"]["coverage_limitations"].get("compiler") == 1)

    def missing_static_entry(world):
        path = world.model_dir() / "static_analysis.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        records[0]["tools"] = {}
        world.rewrite_jsonl(path, records)

    fixture("K: a required static tool entry is missing entirely", missing_static_entry, "FAIL",
            "static_coverage")

    def missing_spec(world):
        path = world.model_dir() / "enhanced_tests.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        world.rewrite_jsonl(path, records[:-1])

    fixture("L: an expected (sample, spec_key) pair is missing", missing_spec, "FAIL",
            "enhanced_coverage")

    def enhanced_source_drift(world):
        # the source changed AFTER the enhanced run; the assembly record is
        # updated with it, so only the enhanced fingerprint can still detect it
        entries = world.entries()
        target = [e for e in entries if e.get("assembled")][0]
        source = world.source(target["sample_id"])
        source.write_bytes(source.read_bytes() + b"// changed after the enhanced run\n")
        data = source.read_bytes()
        target["source_sha256"] = ap.ch.raw_sha256_bytes(data)
        target["byte_size"] = len(data)
        world.rewrite_jsonl(world.model_dir() / "assembly.jsonl", entries)

    fixture("M: candidate source drift after the enhanced run", enhanced_source_drift, "FAIL",
            "enhanced_source_drift")

    def runtime_drift(world):
        from thesis.evaluation import manifest_fragments as mf

        path = mf.fragment_path(Path(world.config["outputs"]["intermediate_dir"]),
                                world.run_id, "runtime", "evidence")
        fragment = json.loads(path.read_text(encoding="utf-8"))
        fragment["content"]["static_repair_runtime_condition_sha256"] = "9" * 64
        atomic_io.atomic_write_json(path, fragment)
        mf.write_snapshot(Path(world.config["outputs"]["intermediate_dir"]), world.run_id)

    fixture("N: runtime evidence differs from the contract", runtime_drift, "FAIL",
            "runtime_evidence_bound_at_t0")

    def no_runtime_evidence(world):
        from thesis.evaluation import manifest_fragments as mf

        mf.fragment_path(Path(world.config["outputs"]["intermediate_dir"]),
                         world.run_id, "runtime", "evidence").unlink()
        mf.write_snapshot(Path(world.config["outputs"]["intermediate_dir"]), world.run_id)

    fixture("O: no runtime evidence bound at T0 -> UNRESOLVED, never a PASS",
            no_runtime_evidence, "UNRESOLVED", "runtime_evidence_bound_at_t0", "UNRESOLVED")

    def iteration_as_base(world):
        iteration = "%s__static_feedback__iter1" % world.run_id
        target = world.model_dir(MODEL, iteration) / "assembly.jsonl"
        entry = dict(world.assembled()[0])
        entry["run_id"] = world.run_id  # an iteration artifact claiming the base run
        common.append_jsonl(target, entry)

    fixture("P: a repair-iteration artifact claiming the base run", iteration_as_base, "FAIL",
            "repair_iterations_separate_from_base")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        report = world.verify(run_id="%s__static_feedback__iter1" % RUN_ID)
        check("P2: an iteration run id as base run -> FAIL",
              report["status"] == "FAIL"
              and status_of(report, "base_run_is_not_a_repair_iteration") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        from thesis.evaluation import manifest_fragments as mf

        path = mf.fragment_path(Path(world.config["outputs"]["intermediate_dir"]),
                                world.run_id, "contract")
        fragment = json.loads(path.read_text(encoding="utf-8"))
        fragment["fingerprint_sha256"] = "a" * 64
        fragment["content"]["contract_sha256"] = "a" * 64
        atomic_io.atomic_write_json(path, fragment)
        mf.write_snapshot(Path(world.config["outputs"]["intermediate_dir"]), world.run_id)
        report = world.verify()
        check("Q: contract sha bound to the run drifted -> FAIL",
              report["status"] == "FAIL"
              and status_of(report, "contract_sha_bound_to_run") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        report = world.verify(contract=False)
        check("R: no contract at all -> UNRESOLVED, never a PASS",
              report["status"] == "UNRESOLVED")

    def condition_drift(world):
        from thesis.evaluation import manifest_fragments as mf

        inter = Path(world.config["outputs"]["intermediate_dir"])
        path = mf.fragment_path(inter, world.run_id, "static", "condition")
        fragment = json.loads(path.read_text(encoding="utf-8"))
        fragment["fingerprint_sha256"] = "5" * 64
        atomic_io.atomic_write_json(path, fragment)
        mf.write_snapshot(inter, world.run_id)

    fixture("S: the run registered a different static-analysis condition", condition_drift,
            "FAIL", "contracted_conditions_registered")

    def unregistered_conditions(world):
        from thesis.evaluation import manifest_fragments as mf

        inter = Path(world.config["outputs"]["intermediate_dir"])
        for owner in ("condition",):
            mf.fragment_path(inter, world.run_id, "static", owner).unlink()
            mf.fragment_path(inter, world.run_id, "repair", owner).unlink()
        mf.write_snapshot(inter, world.run_id)

    fixture("S2: the run registered no analysis conditions at all -> UNRESOLVED",
            unregistered_conditions, "UNRESOLVED", "contracted_conditions_registered",
            "UNRESOLVED")

    def wrong_profile(world):
        text = world.config_path.read_text(encoding="utf-8")
        world.config_path.write_text(text.replace("fixture:", "fixture2:")
                                     .replace("profiles:\n  fixture2:", "profiles:\n  fixture2:"),
                                     encoding="utf-8")
        # rebuild the contract under the renamed profile, keep the run as it is
        from thesis.config.load_config import load_config

        contract = pilot_run_contract.build_contract(world.config_path, "fixture2")
        world.contract_sha = pilot_run_contract.freeze_contract(
            contract, world.contract_path, allow_draft=True)
        world.config = load_config(world.config_path)

    fixture("T: the frozen contract belongs to another profile", wrong_profile, "FAIL",
            "profile_matches_contract")

    def successful_generation_not_assembled(world):
        entries = [e for e in world.entries() if not e.get("assembled")
                   or e["sample_id"] != sample_id(BENCHMARK)]
        world.rewrite_jsonl(world.model_dir() / "assembly.jsonl", entries)
        source = world.source(sample_id(BENCHMARK))
        if source.exists():
            source.unlink()

    fixture("U: a successful generation without an assembled source",
            successful_generation_not_assembled, "FAIL",
            "assembly_covers_successful_generations")

    def unkeyable_enhanced_record(world):
        common.append_jsonl(world.model_dir() / "enhanced_tests.jsonl", {
            "schema_version": "enhanced.v3", "sample_id": world.assembled()[0]["sample_id"],
            "model_id": MODEL, "run_id": world.run_id, "execution_model": "serial",
            "spec": {"benchmark": "transform/55_transform_relu"},  # no size/pattern
            "status": "pass", "exit_code": 0, "duration_seconds": 0.01})

    fixture("V: an enhanced record whose spec cannot be keyed is never invisible",
            unkeyable_enhanced_record, "FAIL", "enhanced_coverage")

    print("== T0 contract guard ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        decision = pilot_run_contract.t0_guard(world.config_path, "fixture",
                                               world.contract_path, bind=False)
        check("T0: an unchanged frozen contract is only START_ALLOWED when the contract "
              "itself is READY (this draft is not)",
              decision["decision"] == "START_REFUSED"
              and decision["frozen_contract_sha256"] == decision["rebuilt_contract_sha256"]
              and decision["rebuilt_status"] == "NOT_READY")
        # a config edited after the freeze must be refused on the sha, not only
        # on the open decisions
        text = world.config_path.read_text(encoding="utf-8")
        world.config_path.write_text(text.replace("run_timeout_seconds: 120",
                                                  "run_timeout_seconds: 90"), encoding="utf-8")
        drifted = pilot_run_contract.t0_guard(world.config_path, "fixture",
                                              world.contract_path, bind=False)
        check("T0: a config change after the freeze -> START_REFUSED with the drift named",
              drifted["decision"] == "START_REFUSED"
              and drifted["frozen_contract_sha256"] != drifted["rebuilt_contract_sha256"]
              and any("run_timeout_seconds" in field for field in drifted["drift_fields"]))
        check("T0: a corrupt frozen contract is refused",
              _corrupt_refused(world.contract_path))

    print("== contract builder state (today) ==")
    contract = pilot_run_contract.build_contract(
        REPO_ROOT / "thesis" / "config" / "config.yaml", "pilot")
    check("builder returns NOT_READY while the population decision is open",
          contract["status"] == "NOT_READY"
          and any("population" in b for b in contract["blockers"]))
    check("builder refuses to freeze a NOT_READY contract", _freeze_refused(contract))
    check("contract sha is stable across rebuilds (no timestamp inside)",
          contract["contract_sha256"] == pilot_run_contract.build_contract(
              REPO_ROOT / "thesis" / "config" / "config.yaml", "pilot")["contract_sha256"])
    check("contract carries every contracted field",
          {"run_id", "profile", "model_ids", "population", "execution_models",
           "primary_compiler", "run_timeout_seconds", "conditions", "expected_stages",
           "post_run_verifier_version"} <= set(contract)
          and {"generation_condition_sha256", "assembly_condition_sha256",
               "evaluation_condition_sha256", "enhanced_frozen_specs_sha256",
               "enhanced_policy_sha256_lf_normalized", "static_analysis_condition_sha256",
               "repair_condition_sha256", "static_repair_runtime_condition_sha256",
               "semantic_decisions_sha256_lf_normalized", "cross_pilot_artifact_sha256"}
          <= set(contract["conditions"]))
    check("contract contains no secrets",
          not any(k in json.dumps(contract).lower() for k in ("api_key", "sk-", "token=")))

    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for item in FAILURES:
            print("  -", item)
        sys.exit(1)
    print("All post-run verification fixtures passed.")


def _corrupt_refused(path: Path) -> bool:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["model_ids"] = ["tampered"]
    atomic_io.atomic_write_json(path, payload)
    try:
        pilot_run_contract.load_frozen(path)
        return False
    except pilot_run_contract.ContractDrift:
        return True


def _freeze_refused(contract) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            pilot_run_contract.freeze_contract(contract, Path(tmp) / "c.json")
            return False
        except pilot_run_contract.ContractNotReady:
            return True


if __name__ == "__main__":
    main()
