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
from thesis.evaluation import condition_hashing as ch  # noqa: E402
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


def sample_id(benchmark, index=0, execution_model="serial", model=MODEL):
    return "%s__%s__%s__%s__sample_%d" % (model, benchmark[0], benchmark[1],
                                          execution_model, index)


def fake_environment(name, tools, extra=None):
    """A pinned runtime domain exactly as the readiness probe reports one."""
    return OrderedDict([
        ("image_ref", "%s-image" % name),
        ("image_id", "sha256:%s" % (name * 8)[:64]),
        ("repo_digests", ["%s@sha256:%s" % (name, (name * 8)[:64])]),
        ("rootfs_layers_sha256", ("%s%s" % (name, "0" * 64))[:64]),
        ("tool_identities", OrderedDict(sorted(tools.items()))),
        ("evidence", OrderedDict(sorted((extra or {}).items()))),
        ("probe_error", None),
    ])


def fake_environments(**overrides):
    environments = OrderedDict([
        # the PRODUCTIVE main-probe shape (probe_runtime_identity.ROLE_TOOLS
        # ["main"] + main_evidence): tool identities for the five static
        # tools, MPI ONLY as evidence.mpi_version_line - never a tool
        # identity named "mpi" (pre-start fix 2026-09-16)
        ("main", fake_environment("main", {
            "compiler": "g++ 13.3.0",
            "gcc_analyzer": "gcc 13.3.0", "clang_tidy": "clang-tidy 18.1.3",
            "cppcheck": "cppcheck 2.13.0", "infer": "infer 1.1.0"},
            {"mpi_version_line": "mpirun (Open MPI) 4.1.6",
             "toolchain_versions_file": "/opt/toolchain-versions.txt",
             "toolchain_versions_sha256": "2026073100" + "0" * 54,
             "interpreter_identity": "Python 3.12.3"})),
        ("parcoach", fake_environment("parcoach", {"parcoach": "PARCOACH 2.4.0"},
                                      {"executable_sha256": "1bad6752" + "0" * 56,
                                       "llvm_backend": "LLVM 15.0.7"})),
        ("llov", fake_environment("llov", {"llov": "clang 7.1.0"},
                                  {"plugin_sha256": "19bbc86b" + "0" * 56,
                                   "clang_identity": "clang version 7.1.0"})),
    ])
    for domain, mutate in (overrides or {}).items():
        environments[domain] = mutate(environments[domain])
    return environments


def fake_prober(config):
    return fake_environments()


def write_readiness_artifact(config, path):
    """A fixture's own readiness proof: the runtime condition of the fake
    environments UNDER THIS CONFIG, computed by the PRODUCTIVE measurement
    path. Each fixture world needs its own, because the runtime condition
    covers the static/repair condition of its config."""
    from thesis.evaluation import run_authorization as ra

    fresh = ra.measure_fresh_runtime(config, prober=fake_prober)
    atomic_io.atomic_write_json(Path(path), {
        "schema_version": "static_repair_readiness.v2",
        "gate": "READY",
        "static_analysis_condition_sha256": fresh["static_analysis_condition_sha256"],
        "repair_condition_sha256": fresh["repair_condition_sha256"],
        "runtime_condition_sha256": fresh["sha256"],
        "runtime_condition": fresh["condition"],
        "runtime_fully_pinned": True,
    })
    return fresh


def generation_record(benchmark, prompt_text, raw_text, execution_model="serial",
                      run_id=RUN_ID):
    return {
        "schema_version": "generation.v3",
        "run_id": run_id,
        "created_at_utc": common.utc_now_iso(),
        "sample_id": sample_id(benchmark, execution_model=execution_model),
        "prompt": {"problem_type": benchmark[0], "name": benchmark[1],
                   "parallelism_model": execution_model, "language": "cpp",
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
                 models=(MODEL,), samples=(BENCHMARK, BENCHMARK2),
                 extra_models=(), stage_overrides=None,
                 execution_models=("serial",), skip_stamps=(),
                 execution_model="serial", repair_loops=True,
                 repair_sample_status=None, repair_iteration=1,
                 unsuccessful_generations=()):
        self.root = Path(root)
        self.run_id = run_id
        self.models = list(models)
        # models that exist in the CONFIG (and therefore in the contract's
        # model set) but carry no generations - a provider child process
        # started for one of them has real pending work
        self.extra_models = [dict(m) for m in extra_models]
        self.stage_overrides = dict(stage_overrides or {})
        self.execution_models = list(execution_models)
        self.skip_stamps = tuple(skip_stamps)
        # the execution model of the fixture SAMPLES (the population above is
        # what the contract admits; this is what the two prompts are)
        self.execution_model = execution_model
        # repair loops: written for every contracted (model, variant) through
        # the PRODUCTIVE orchestrator writers, all samples terminal
        self.repair_loops = repair_loops
        self.repair_sample_status = repair_sample_status
        self.repair_iteration = repair_iteration
        # (model, benchmark) pairs whose generation the provider never
        # delivered: the productive assembler then SKIPS them, and the repair
        # loop's own bootstrap marks them repair_unusable at iteration 0
        self.unsuccessful_generations = {tuple(pair) for pair in unsuccessful_generations}
        self.skip_repair_invocations = set()
        self.skip_static_invocations = set()
        self.samples = list(samples)
        self.config_path = self.root / "config.yaml"
        self.contract_path = self.root / "frozen_contract.json"
        self.prompts_path = self.root / "prompts.json"
        self.readiness_path = self.root / "readiness.json"
        # the fixture's OWN freeze (population / publication / cross-pilot
        # policy / methodology) through the productive config seams, so the
        # fixture contract is READY on the productive path - never a draft
        self.cross_pilot_path = self.root / "cross_pilot.json"
        self.freeze_dir = self.root / "freeze"
        self._write_prompts()
        self._write_config()
        from thesis.config.load_config import load_config

        self.config = load_config(self.config_path)
        self._write_readiness()
        self._write_freeze()
        self._freeze_contract(contract_run_id)
        # T0 BEFORE any record, exactly as in production: the first start
        # requires a FRESH run (NO_PILOT001_MEASUREMENT_REUSE) and every
        # generation record must postdate the start authorization
        self._bind_contract()
        self._write_generations()
        self._assemble()
        # records first: whether a repair loop registers its repair_evaluation
        # invocation at iteration 0 depends on the base records it finds
        self._write_stage_records()
        self.stamp_stages(skip=self.skip_stamps)
        if self.repair_loops:
            self.write_repair_loops()

    # ---- construction -------------------------------------------------
    def _write_prompts(self):
        atomic_io.atomic_write_json(self.prompts_path, [
            {"problem_type": BENCHMARK[0], "name": BENCHMARK[1], "language": "cpp",
             "parallelism_model": self.execution_model, "prompt": PROMPT_TEXT},
            {"problem_type": BENCHMARK2[0], "name": BENCHMARK2[1], "language": "cpp",
             "parallelism_model": self.execution_model, "prompt": PROMPT_TEXT2},
        ])

    def _write_readiness(self):
        write_readiness_artifact(self.config, self.readiness_path)

    def _write_config(self):
        config = {
            "outputs": {"raw_dir": (self.root / "raw").as_posix(),
                        "intermediate_dir": (self.root / "intermediate").as_posix(),
                        "root": (self.root / "results").as_posix(),
                        "readiness_artifact": self.readiness_path.as_posix(),
                        "cross_pilot_artifact": self.cross_pilot_path.as_posix(),
                        "freeze_artifacts": {
                            "population": (self.freeze_dir / "population.json").as_posix(),
                            "publication_policy": (self.freeze_dir / "publication_policy.json").as_posix(),
                            "methodology_freeze": (self.freeze_dir / "methodology_freeze.json").as_posix(),
                            "run_freeze_receipt": (self.freeze_dir / "run_freeze_receipt.json").as_posix(),
                            "result_acceptance": (self.freeze_dir / "result_acceptance.json").as_posix()}},
            "prompts": {"path": self.prompts_path.as_posix(), "prompt_field": "prompt",
                        "execution_models": list(self.execution_models),
                        "problem_types": None},
            "profiles": {"fixture": {"run_id": self.run_id, "selection": "prefix",
                                     "prompt_limit": 2, "num_samples_per_prompt": 1}},
            "models": [{"id": model, "enabled": True, "provider": "mock",
                        "model_name": model, "api_key_env": "PAREVAL_FIXTURE_API_KEY"}
                       for model in self.models] + list(self.extra_models),
            "generation_defaults": {"timeout_seconds": 300, "retry_attempts": 2,
                                    "system_prompt": "fixture system prompt",
                                    "max_output_tokens": 128, "api_mode": "direct"},
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
        for stage, override in self.stage_overrides.items():
            config["stages"][stage] = override
        self.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        (self.root / "specs.jsonl").write_text("", encoding="utf-8")

    def _write_generations(self):
        from thesis.evaluation import run_authorization as ra

        authorization = ra.load_authorization(self.config, self.run_id) or {}
        for model in self.models:
            path = Path(self.config["outputs"]["raw_dir"]) / self.run_id / model / "generations.jsonl"
            if path.exists():
                path.unlink()
            # the productive runner's per-model summary (generation_summary.v1)
            # binds the run authorization; the verifier requires it
            atomic_io.atomic_write_json(path.parent / "generation_summary.json", {
                "schema_version": "generation_summary.v1", "run_id": self.run_id,
                "model_id": model, "provider": "mock", "model_name": model,
                "api_mode": "direct",
                "run_authorization": {"mode": "FIRST_START",
                                      "authorization_sha256": authorization.get("authorization_sha256"),
                                      "contract_discovery": "explicit_contract_path",
                                      "fresh_runtime_probed": True},
                "counts": {"requested": len(self.samples), "success": len(self.samples),
                           "skipped_existing": 0}})
            for benchmark, prompt_text, raw in ((BENCHMARK, PROMPT_TEXT, RAW),
                                                (BENCHMARK2, PROMPT_TEXT2, RAW2)):
                if benchmark in self.samples:
                    record = generation_record(benchmark, prompt_text, raw, self.execution_model,
                                               run_id=self.run_id)
                    record["sample_id"] = sample_id(benchmark, execution_model=self.execution_model,
                                                    model=model)
                    # the productive record names its model identity (generation.v3)
                    record["model"] = {"id": model, "provider": "mock", "model_name": model}
                    if (model, benchmark) in self.unsuccessful_generations:
                        record["status"] = dict(record["status"], success=False,
                                                error_type="APITimeoutError")
                        record["output"] = dict(record["output"], raw_text="",
                                                cleaned_code=None)
                    common.append_jsonl(path, record)

    def _write_freeze(self, reuse_decided=True, publication_decided=True,
                      population_decided=True, base_run_configured=True):
        """The fixture's freeze artifacts: population (the fixture author's
        decision = its own selection), publication policy, a cross-pilot
        policy artifact binding both, and the methodology freeze."""
        from thesis.evaluation import pilot_freeze as pf

        paths = pf.freeze_paths(self.config)
        self.freeze_dir.mkdir(parents=True, exist_ok=True)
        population = pf.build_population(
            self.config, "fixture", pf.fixture_author_freeze(self.config, "fixture"), self.config_path)
        atomic_io.atomic_write_json(paths["population"], population)
        publication = pf.build_publication_policy(self.run_id)
        atomic_io.atomic_write_json(paths["publication_policy"], publication)
        gate = OrderedDict([
            ("schema", "fixture cross-pilot policy artifact"),
            ("state_commit", "fixture"),
            ("reuse_status", pf.REUSE_STATUS_DECIDED if reuse_decided else "UNDECIDED"),
            ("reuse_policy", OrderedDict([
                ("status", "DECIDED" if reuse_decided else "UNDECIDED"),
                ("policy", pf.REUSE_POLICY if reuse_decided else None),
                ("pilot_002_base_measurements", "FRESH"), ("generation_reuse", False),
                ("stage_result_reuse", False), ("repair_reuse", False),
                ("pilot_001_role", "READ_ONLY"), ("comparability_is_not_reuse", True)])),
            ("publication_policy", OrderedDict([
                ("status", "DECIDED" if publication_decided else "OPEN"),
                ("policy", pf.PUBLICATION_POLICY if publication_decided else None),
                ("publication_policy_sha256", publication["publication_policy_sha256"])])),
            ("expected_pilot_002_population", OrderedDict([
                ("selection", "prefix"), ("prompt_limit", 2), ("num_samples_per_prompt", 1),
                ("status", "DECIDED" if population_decided else "NOT_YET_DECIDED"),
                ("population_sha256", population["population_sha256"])])),
            ("expected_pilot_002_base_run", OrderedDict([
                ("run_id", self.run_id if base_run_configured else None),
                ("status", "CONFIGURED" if base_run_configured else "NOT_YET_CONFIGURED"),
                ("forbid_iteration_variants", True)])),
        ])
        gate["cross_pilot_fingerprint_sha256"] = ch.canonical_sha256(gate)
        atomic_io.atomic_write_json(self.cross_pilot_path, gate)
        if not publication_decided:
            paths["publication_policy"].unlink()
        methodology = pf.build_methodology_freeze(self.config, "fixture", "g++", population,
                                                  publication, self.config_path)
        atomic_io.atomic_write_json(paths["methodology_freeze"], methodology)
        self.freeze_paths = paths

    def _freeze_contract(self, contract_run_id):
        contract = pilot_run_contract.build_contract(
            self.config_path, "fixture", run_id_override=contract_run_id)
        if contract_run_id is None and contract["status"] != pilot_run_contract.STATUS_READY:
            raise RuntimeError("fixture contract NOT_READY: %s" % "; ".join(contract["blockers"]))
        # a contract for ANOTHER run id (deliberate mismatch fixtures) can only
        # be a draft: the freeze artifacts are bound to the fixture run id
        self.contract_sha = pilot_run_contract.freeze_contract(
            contract, self.contract_path, allow_draft=contract_run_id is not None)
        self.contract = pilot_run_contract.load_frozen(self.contract_path)

    def _assemble(self):
        run_manifest.ensure_run_manifest(self.config, self.run_id, stage="assembly",
                                         profile="fixture", primary_compiler="g++")
        for model in self.models:
            assemble_sources.assemble_model(self.config, {"run_id": self.run_id},
                                            {"id": model}, False, register_manifest=True)

    def _bind_contract(self, contract=None, sha=None, runtime=True):
        """T0: authorize the run through the PRODUCTIVE path (contract
        integrity, rebuild, fresh runtime probe, contract binding, evidence
        binding, atomic authorization, read-back) with an injected runtime
        prober, then stamp the expected measurement stages."""
        from thesis.evaluation import run_authorization as ra

        if runtime:
            ra.clear_context()
            # the PRODUCTIVE first start: a READY contract and a FRESH run are
            # required (the fixture authorizes before it writes any record);
            # only a deliberate foreign-run-id contract is a draft
            ra.authorize_start(self.config, self.config_path, "fixture", self.run_id,
                               self.contract_path, prober=fake_prober,
                               allow_draft_contract=self.contract.get("status") != "READY")
        else:
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

    # Every expected runtime stage, with the effective invocation the real
    # runner registers for it. Static analysis is deliberately modelled as
    # THREE separate invocations (main container, PARCOACH container, LLOV
    # container), each with its own fragment owner - exactly how a split
    # container run produces its findings.
    STAGE_INVOCATIONS = OrderedDict([
        ("correctness", ({"effective_run_timeout_seconds": {"value": 120,
                                                            "source": "CONFIG"},
                          "primary_compiler": {"value": "g++", "source": "DEFAULT"}},
                         "correctness_tests")),
        ("dynamic", ({"primary_compiler": {"value": "g++", "source": "DEFAULT"},
                      "tools": {"value": ["asan_ubsan"], "source": "CONFIG"},
                      "skip_unavailable_tools": {"value": False, "source": "DEFAULT"}},
                     "dynamic_analysis")),
        # specs: the productive runner marks the DEFAULT frozen artifact as
        # source DEFAULT (CLI only when --specs names another file - an
        # unpinned methodical override the plan NONE refuses)
        ("enhanced", ({"specs": {"value": "frozen", "source": "DEFAULT"},
                       "jobs": {"value": "serial=1", "source": "CONFIG"},
                       "effective_enhanced_run_timeout_seconds": {"value": None,
                                                                  "source": "DEFAULT"}},
                      "enhanced_tests")),
        ("static.main", ({"primary_compiler": {"value": "g++", "source": "DEFAULT"},
                          "tools": {"value": ["compiler"], "source": "CONFIG"},
                          "replace_tool_entries": {"value": False, "source": "DEFAULT"},
                          "rerun_gaps": {"value": False, "source": "DEFAULT"},
                          "replace_legacy_record": {"value": False, "source": "DEFAULT"}},
                         "static_analysis")),
        ("static.parcoach", ({"primary_compiler": {"value": "g++", "source": "DEFAULT"},
                              "tools": {"value": ["parcoach"], "source": "CLI"}},
                             "static_analysis")),
        ("static.llov", ({"primary_compiler": {"value": "g++", "source": "DEFAULT"},
                          "tools": {"value": ["llov"], "source": "CLI"}},
                         "static_analysis")),
        ("repair_evaluation", ({"primary_compiler": {"value": "g++", "source": "DEFAULT"},
                                "variant": {"value": "static_feedback", "source": "CLI"}},
                               "repair")),
    ])

    def stamp_stages(self, only=None, skip=()):
        """Every result-producing stage the contract expects stamps the
        runtime it runs under and pins its effective invocation."""
        from thesis.evaluation import stage_runtime

        stage_runtime.reset_cache()
        stamped = []
        for stage in stage_runtime.expected_stages(self.contract, self.config):
            if only is not None and stage not in only:
                continue
            if stage in skip:
                continue
            effective_values, writer = self.STAGE_INVOCATIONS[stage]
            if stage in ("static.parcoach", "static.llov"):
                # the container commands run once per model (--model-id), so
                # production registers one invocation per model
                for model in self.models + [m["id"] for m in self.extra_models]:
                    if (stage, model) in self.skip_static_invocations:
                        continue
                    stage_runtime.enforce_stage(
                        self.config, self.run_id, stage,
                        effective_values=dict(effective_values), profile="fixture",
                        model_scope=[model], prober=fake_prober, writer=writer)
                stamped.append(stage)
                continue
            if stage == "repair_evaluation":
                # the productive repair loop registers ONE invocation per
                # (model, variant) - and ONLY when it analyses an iteration
                # itself: every loop that reached iteration >= 1, or at
                # iteration 0 a loop whose base records / contract leave a
                # stage for it to run (repair_scope.iteration_zero_analysis)
                for model, variant in self.expected_repair_loops():
                    if (model, variant) in self.skip_repair_invocations:
                        continue
                    if not self.loop_registers_invocation(model, variant):
                        continue
                    self.register_repair_invocation(model, variant)
                stamped.append(stage)
                continue
            stage_runtime.enforce_stage(
                self.config, self.run_id, stage, effective_values=dict(effective_values),
                profile="fixture", prober=fake_prober, writer=writer)
            stamped.append(stage)
        return stamped

    def loop_registers_invocation(self, model, variant):
        """Does the productive loop analyse an iteration - and register its
        repair_evaluation invocation - in this world?"""
        from thesis.evaluation import repair_scope as rs
        from thesis.repair import orchestrator

        if self.repair_iteration >= 1:
            # an iteration >= 1 is analysed unless its samples ended in a
            # status the orchestrator writes BEFORE any analysis
            status = self.repair_sample_status or orchestrator.STATUS_CLEAN
            if status not in (orchestrator.STATUS_UNUSABLE, orchestrator.STATUS_API_EXHAUSTED):
                return True
        # iteration 0: the loop analyses whatever the base run did not cover
        return bool(rs.iteration_zero_analysis(self.contract, self.config, variant,
                                               self.run_id, model)["certain"])

    def register_repair_invocation(self, model, variant):
        """The repair_evaluation invocation exactly as the productive loop
        registers it for (model, variant)."""
        from thesis.evaluation import stage_runtime

        effective_values, writer = self.STAGE_INVOCATIONS["repair_evaluation"]
        values = dict(effective_values)
        values["variant"] = {"value": variant, "source": "CLI"}
        return stage_runtime.enforce_stage(
            self.config, self.run_id, "repair_evaluation", effective_values=values,
            profile="fixture", model_scope=[model], prober=fake_prober, writer=writer)

    def _write_stage_records(self):
        for model in self.models:
            model_dir = self.model_dir(model)
            for entry in self.assembled(model):
                sid = entry["sample_id"]
                common.append_jsonl(model_dir / "correctness.jsonl", {
                    "schema_version": "correctness.v2", "sample_id": sid, "model_id": model,
                    "run_id": self.run_id, "created_at_utc": common.utc_now_iso(),
                    "execution_model": entry.get("execution_model") or "serial", "verdict": "pass",
                    "compile": {"ok": True, "exit_code": 0, "timed_out": False,
                                "duration_seconds": 2.0},
                    "runs": [{"argv": ["b.out", "1"], "exit_code": 0, "timed_out": False,
                              "duration_seconds": 0.01, "verdict": "pass"}]})
                common.append_jsonl(model_dir / "static_analysis.jsonl", {
                    "schema_version": "static_analysis.v3", "sample_id": sid,
                    "model_id": model, "run_id": self.run_id, "created_at_utc": common.utc_now_iso(),
                    "execution_model": entry.get("execution_model") or "serial",
                    "tools": self.static_tools_for(entry)})
                for spec in self.expected_specs(entry):
                    common.append_jsonl(model_dir / "enhanced_tests.jsonl", {
                        "schema_version": "enhanced.v3", "sample_id": sid, "model_id": model,
                        "run_id": self.run_id, "created_at_utc": common.utc_now_iso(),
                        "execution_model": entry.get("execution_model") or "serial",
                        "benchmark": entry.get("benchmark"), "spec": spec,
                        "status": "pass", "exit_code": 0, "duration_seconds": 0.01})
            self.register_enhanced_fingerprint(model)
            self.write_dynamic_records(model)
            self.write_stage_histories(model)

    def write_dynamic_records(self, model):
        """Base dynamic records when the world's config enables the dynamic
        stage: the productive runner without tools writes exactly this shape
        (one record per assembled sample, no tool entries) plus one base entry
        in its invocation history."""
        from thesis.evaluation import writer_attribution as wa

        stage = (self.config.get("stages") or {}).get("dynamic_analysis") or {}
        if not stage.get("enabled"):
            return
        path = self.model_dir(model) / "dynamic_analysis.jsonl"
        if path.exists():
            path.unlink()
        for entry in self.assembled(model):
            common.append_jsonl(path, {"schema_version": "dynamic_analysis.v2",
                                       "sample_id": entry["sample_id"], "model_id": model,
                                       "run_id": self.run_id, "created_at_utc": common.utc_now_iso(),
                                       "execution_model": entry.get("execution_model") or "serial",
                                       "tools": {}, "has_blocking_findings": False,
                                       "low_confidence_count": 0})
        samples = len(self.assembled(model))
        atomic_io.atomic_write_json(self.model_dir(model) / "dynamic_analysis_summary.json", {
            "model_id": model, "samples": samples, "tools_run": [], "tools_skipped": [],
            "invocations": [wa.invocation_entry("run_dynamic_analysis --tools <config>", None,
                                                status=wa.STATUS_COMPLETED, tools_run=[],
                                                tools_skipped=[], samples=samples)]})

    def write_stage_histories(self, model):
        """The per-model invocation histories every productive runner writes
        (base-writer entries): static_analysis_summary.json - one entry per
        container invocation exactly as a split run produces them - and
        correctness_summary.json. A history that is absent although its stage
        is contracted and its records exist is a lost provenance artifact for
        the verifier, so a faithful base run carries them."""
        from thesis.evaluation import writer_attribution as wa
        from thesis.evaluation.tool_config import resolve_tool_settings

        settings = resolve_tool_settings(self.config, "static_analysis")
        enabled = [name for name, tool in settings.items() if tool.enabled]
        main_tools = [name for name in enabled if name not in ("parcoach", "llov")]
        invocations = []
        for tools in [main_tools] + [[name] for name in enabled if name in ("parcoach", "llov")]:
            if not tools:
                continue
            entry = wa.invocation_entry("run_static_analysis --tools %s" % " ".join(tools), None,
                                        created_at_utc=common.utc_now_iso(),
                                        tools_requested=list(tools), tools_run=list(tools),
                                        tools_skipped=[], entries_run={t: 2 for t in tools},
                                        replace_tool_entries=[], rerun_gaps=False,
                                        replace_legacy_record=False, primary_compiler="g++")
            invocations.append(entry)
        atomic_io.atomic_write_json(self.model_dir(model) / "static_analysis_summary.json", {
            "schema_version": "static_analysis_summary.v3", "model_id": model,
            "invocations": invocations})
        samples = len(self.assembled(model))
        atomic_io.atomic_write_json(self.model_dir(model) / "correctness_summary.json", {
            "schema_version": "correctness_summary.v1", "run_id": self.run_id,
            "model_id": model, "samples": samples, "verdicts": {"pass": samples},
            "invocations": [wa.invocation_entry(
                "run_correctness", None, status=wa.STATUS_COMPLETED,
                started_at_utc=common.utc_now_iso(), created_at_utc=common.utc_now_iso(),
                samples=samples, verdicts={"pass": samples})]})

    def tool_entry(self, state, error=None, tool="compiler"):
        return {"tool": tool, "ran": True, "exit_code": 0, "num_findings": 0,
                "num_blocking": 0, "num_low_confidence": 0, "duration_seconds": 0.5,
                "findings": [], "error": error, "analysis_state": state,
                "tool_state_schema": "tool_state.v1"}

    def static_tools_for(self, entry):
        """One COMPLETED entry per static tool the fixture config enables for
        the sample's execution model - exactly the coverage the verifier's
        check_static requires (compiler only in the default world)."""
        from thesis.evaluation.tool_config import resolve_tool_settings

        settings = resolve_tool_settings(self.config, "static_analysis")
        execution_model = entry.get("execution_model") or "serial"
        return {name: self.tool_entry("COMPLETED", tool=name)
                for name, tool in settings.items()
                if tool.enabled and execution_model in tool.execution_models}

    # ---- repair loops (productive orchestrator writers) ---------------
    def repair_loop(self, model, variant):
        """The productive loop object for (model, variant): its writers
        (append_sample_state / save_wave_state) produce the real state
        schema, so the verifier reads exactly what a run would leave."""
        from thesis.repair import orchestrator

        model_config = next(m for m in self.config["models"] if m["id"] == model)
        return orchestrator.RepairLoop(
            config=self.config, config_path=str(self.config_path), profile_name="fixture",
            profile=self.config["profiles"]["fixture"], model_config=model_config,
            variant=variant)

    def expected_repair_loops(self):
        plan = self.contract.get("repair_plan") or {}
        if not plan.get("enabled"):
            return []
        return [(model, variant) for model in self.contract.get("model_ids") or []
                for variant in plan.get("variants") or []]

    def write_repair_loops(self, status=None, iteration=None, only=None, skip=()):
        """Every contracted (model, variant) loop: one terminal state record
        per assembled sample (default stopped_clean) and a `done` wave state."""
        from thesis.repair import orchestrator

        status = status or self.repair_sample_status or orchestrator.STATUS_CLEAN
        iteration = self.repair_iteration if iteration is None else iteration
        written = []
        for model, variant in self.expected_repair_loops():
            if only is not None and (model, variant) not in only:
                continue
            if (model, variant) in skip:
                continue
            loop = self.repair_loop(model, variant)
            if loop.paths.state_path.exists():
                loop.paths.state_path.unlink()
            for entry in self.assembled(model):
                loop.append_sample_state(entry["sample_id"], iteration, status,
                                         "fixture: %s at iteration %d" % (status, iteration))
            loop.save_wave_state(iteration, "done")
            written.append((model, variant))
        return written

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
        fragment["content"]["fresh_runtime_condition_sha256"] = "9" * 64
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
        check("T0: an unchanged, READY frozen contract -> START_ALLOWED (rebuilt sha equal, "
              "no drift)",
              decision["decision"] == "START_ALLOWED"
              and decision["frozen_contract_sha256"] == decision["rebuilt_contract_sha256"]
              and decision["drift_fields"] == [] and decision["rebuilt_status"] == "READY")
        draft = pilot_run_contract.build_contract(world.config_path, "fixture",
                                                  run_id_override="pilot_002_other")
        draft_path = world.root / "draft_contract.json"
        pilot_run_contract.freeze_contract(draft, draft_path, allow_draft=True)
        refused = pilot_run_contract.t0_guard(world.config_path, "fixture", draft_path,
                                              run_id_override="pilot_002_other", bind=False)
        check("T0: an unchanged frozen contract is only START_ALLOWED when the contract "
              "itself is READY (a draft with open decisions is refused)",
              refused["decision"] == "START_REFUSED"
              and refused["frozen_contract_sha256"] == refused["rebuilt_contract_sha256"]
              and refused["rebuilt_status"] == "NOT_READY")
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

    print("== contract builder state (today: pilot_002 frozen) ==")
    contract = pilot_run_contract.build_contract(
        REPO_ROOT / "thesis" / "config" / "config.yaml", "pilot")
    check("builder returns READY for the frozen pilot_002 (no open decision)",
          contract["status"] == "READY" and contract["blockers"] == []
          and contract["run_id"] == "pilot_002"
          and len(contract["model_ids"]) == 11
          and contract["population"]["selection"] == "stratified"
          and contract["population"]["prompt_limit"] == 36
          and contract["population"]["expected_sample_count"] == 36
          and contract["population_freeze"]["total_model_prompt_cells"] == 396)
    historical = pilot_run_contract.build_contract(
        REPO_ROOT / "thesis" / "config" / "config.yaml", "pilot", run_id_override="pilot_001")
    check("builder returns NOT_READY for the historical run id (and refuses to freeze it)",
          historical["status"] == "NOT_READY"
          and any("historical pilot_001" in b for b in historical["blockers"])
          and _freeze_refused(historical))
    iteration = pilot_run_contract.build_contract(
        REPO_ROOT / "thesis" / "config" / "config.yaml", "pilot",
        run_id_override="pilot_002__static_feedback__iter1")
    check("builder returns NOT_READY for a repair-iteration run id",
          iteration["status"] == "NOT_READY"
          and any("repair-iteration" in b for b in iteration["blockers"]))
    check("contract sha is stable across rebuilds (no timestamp inside)",
          contract["contract_sha256"] == pilot_run_contract.build_contract(
              REPO_ROOT / "thesis" / "config" / "config.yaml", "pilot")["contract_sha256"])
    check("contract carries every contracted field",
          {"run_id", "profile", "model_ids", "population", "execution_models",
           "primary_compiler", "run_timeout_seconds", "conditions", "expected_stages",
           "post_run_verifier_version", "base_run", "population_freeze",
           "selected_prompt_hashes", "reuse_policy", "publication_policy",
           "methodology_freeze", "methodical_override_plan"} <= set(contract)
          and {"generation_condition_sha256", "assembly_condition_sha256",
               "evaluation_condition_sha256", "enhanced_frozen_specs_sha256",
               "enhanced_policy_sha256_lf_normalized", "static_analysis_condition_sha256",
               "repair_condition_sha256", "static_repair_runtime_condition_sha256",
               "semantic_decisions_sha256_lf_normalized", "cross_pilot_artifact_sha256",
               "e3_2_author_confirmation_sha256", "e3_2_decisions_sha256",
               "technical_provenance_cleanup_sha256", "timing_contract_sha256"}
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
