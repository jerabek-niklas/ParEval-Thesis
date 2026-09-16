"""pilot_002 POPULATION + FINAL METHODOLOGY/RUN FREEZE - fixtures.

Run:  python thesis/evaluation/test_pilot002_freeze.py

Groups (every one against the PRODUCTIVE modules; no provider call, no
docker, no T0 bind of the real run):

  population   A exact 36 keys -> PASS; B one prompt missing / C one extra /
               D wrong benchmark / E missing execution model / F 2 samples /
               G prefix instead of stratified / H prompt text changed /
               I problem type duplicated -> NON-PASS; J equality with
               pilot_001 grants nothing (explicit author freeze only)
  model set    missing / extra / substituted / reasoning drift / ordering
  reuse        A UNDECIDED -> NOT_READY; B policy missing -> NOT_READY;
               C NO_REUSE + fresh -> READY; D imported historical records ->
               refused at start / NON-PASS post-run; E read-only comparison
  publication  A OPEN / B missing -> NOT_READY; C decided -> READY; D-G the
               publication gate (no verification / FAIL / pending / ACCEPTED)
  overrides    A none -> PASS; B niter / D launch (config) -> START_REFUSED;
               C CLI timeout / --jobs -> refused before the first record;
               E narrowed model set at first start -> refused; F/G/H/I
               operational selectors allowed
  contract     every open decision -> NOT_READY; the real pilot_002 contract
               READY, frozen (when present) reproducible, drift-free
  preflight    the freeze lines; PILOT_START_ALLOWED never true
"""
from __future__ import annotations

import copy
import functools
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "thesis" / "evaluation") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "thesis" / "evaluation"))

import yaml  # noqa: E402

from thesis.config.load_config import load_config  # noqa: E402
from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import condition_hashing as ch  # noqa: E402
from thesis.evaluation import effective_invocation as ei  # noqa: E402
from thesis.evaluation import pilot_freeze as pf  # noqa: E402
from thesis.evaluation import pilot_preflight  # noqa: E402
from thesis.evaluation import pilot_run_contract as prc  # noqa: E402
from thesis.evaluation import run_authorization as ra  # noqa: E402
from thesis.evaluation import run_freshness  # noqa: E402
from thesis.evaluation import stage_runtime  # noqa: E402
from thesis.evaluation.test_post_run_verification import (  # noqa: E402
    MODEL, World, fake_prober, status_of)
from thesis.generation import common  # noqa: E402

CONFIG_PATH = REPO_ROOT / "thesis" / "config" / "config.yaml"
FAILURES = []
CHECKS = 0


def check(label, condition):
    global CHECKS
    CHECKS += 1
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def load_generate_module():
    spec = importlib.util.spec_from_file_location(
        "thesis_generate_cli", REPO_ROOT / "thesis" / "generation" / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# temp copies of the REAL config / prompt file
# ---------------------------------------------------------------------------

def repo_config_copy(tmp, mutate=None, prompts_mutate=None):
    """A copy of the productive config (optionally mutated) under tmp;
    relative paths keep resolving against the repository root."""
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    if prompts_mutate is not None:
        prompts = json.loads((REPO_ROOT / config["prompts"]["path"]).read_text(encoding="utf-8"))
        prompts = prompts_mutate(prompts)
        prompts_path = Path(tmp) / "prompts.json"
        prompts_path.write_text(json.dumps(prompts), encoding="utf-8")
        config["prompts"]["path"] = prompts_path.as_posix()
    if mutate is not None:
        mutate(config)
    path = Path(tmp) / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def contract_for(config_path, run_id=None):
    return prc.build_contract(Path(config_path), "pilot", run_id_override=run_id)


def blockers_mention(contract, *needles):
    return [b for b in contract["blockers"] if any(n in b for n in needles)]


# ---------------------------------------------------------------------------
# 1. population
# ---------------------------------------------------------------------------

def test_population():
    print("== population: the explicit author freeze vs the productive selection ==")
    config = load_config(CONFIG_PATH)
    artifact = pf._load_json(pf.DEFAULT_PATHS["population"])
    state = pf.verify_population(artifact, config, "pilot", CONFIG_PATH)
    check("A: the frozen population reproduces from the CURRENT productive selection (FRESH)",
          state["status"] == pf.FRESH and state["problems"] == [])
    check("A: 12 benchmarks, 36 prompt keys, 11 models, serial/omp/mpi, 1 sample, 396 cells",
          artifact["benchmark_count"] == 12 and artifact["prompt_count"] == 36
          and artifact["model_count"] == 11 and artifact["samples_per_prompt"] == 1
          and artifact["execution_models"] == ["serial", "omp", "mpi"]
          and artifact["total_model_prompt_cells"] == 396
          and len(artifact["prompt_keys"]) == 36 and len(artifact["prompt_hashes"]) == 36
          and artifact["benchmark_ids"] == list(pf.PILOT_002_BENCHMARKS)
          and artifact["model_ids"] == sorted(pf.PILOT_002_MODEL_IDS))
    check("A: every problem type exactly once, every benchmark with all three execution models",
          all(len(v) == 1 for v in artifact["problem_type_mapping"].values())
          and len(artifact["problem_type_mapping"]) == 12
          and all(sorted(v) == ["mpi", "omp", "serial"]
                  for v in artifact["execution_models_by_benchmark"].values()))
    check("A: population_sha256 reproduces and the artifact is author-frozen (not historical)",
          artifact["population_sha256"] == pf.document_sha256(artifact, "population_sha256")
          and artifact["population_source"] == pf.POPULATION_SOURCE
          and artifact["historical_population_used_as_source"] is False
          and artifact["author_freeze"]["source"] == pf.POPULATION_SOURCE
          and artifact["run_id"] == "pilot_002")
    rebuilt = pf.build_population(config, "pilot", pf.pilot_002_author_freeze(), CONFIG_PATH)
    check("A: a rebuild yields the identical population sha (deterministic, no timestamp inside)",
          rebuilt["population_sha256"] == artifact["population_sha256"])
    contract = contract_for(CONFIG_PATH)
    check("A: the real contract is READY and binds the population sha + the 36 selected hashes",
          contract["status"] == "READY"
          and contract["population_freeze"]["sha256"] == artifact["population_sha256"]
          and list(contract["selected_prompt_hashes"].keys()) == artifact["prompt_keys"]
          and contract["selected_prompt_hashes"] == artifact["prompt_hashes"])

    selected_key = artifact["prompt_keys"][0]
    problem_type, name, pm = selected_key.split("|")
    with tempfile.TemporaryDirectory() as tmp:
        # B: one selected prompt missing from the prompt file
        def drop_one(prompts):
            return [e for e in prompts if not (e["problem_type"] == problem_type and e["name"] == name
                                               and e["parallelism_model"] == pm)]
        path = repo_config_copy(tmp, prompts_mutate=drop_one)
        cfg = load_config(path)
        state = pf.verify_population(artifact, cfg, "pilot", path)
        contract = contract_for(path)
        drift = None
        try:
            pf.build_population(cfg, "pilot", pf.pilot_002_author_freeze(), path)
        except pf.PopulationSelectionDrift as exc:
            drift = str(exc)
        check("B: one prompt missing -> population STALE, contract NOT_READY, author freeze "
              "BLOCKED_POPULATION_SELECTION_DRIFT",
              state["status"] == pf.STALE and contract["status"] == "NOT_READY"
              and blockers_mention(contract, "population freeze", "selected prompt")
              and drift is not None and "BLOCKED_POPULATION_SELECTION_DRIFT" in drift)
    with tempfile.TemporaryDirectory() as tmp:
        # C: one prompt extra inside the frozen artifact (a key the selection does not select)
        mutated = copy.deepcopy(artifact)
        mutated["prompt_keys"].append("zzz|99_extra|serial")
        mutated["prompt_hashes"]["zzz|99_extra|serial"] = "0" * 64
        mutated["prompt_count"] = 37
        mutated["population_sha256"] = pf.document_sha256(mutated, "population_sha256")
        state = pf.verify_population(mutated, config, "pilot", CONFIG_PATH)
        check("C: one prompt extra in the frozen population -> STALE (prompt_keys / counts differ)",
              state["status"] == pf.STALE and any("prompt_keys" in p for p in state["problems"]))
        # D: same count, wrong benchmark
        mutated = copy.deepcopy(artifact)
        wrong = [k.replace("55_transform_relu", "56_transform_negate_odds") for k in mutated["prompt_keys"]]
        mutated["prompt_keys"] = sorted(wrong)
        mutated["prompt_hashes"] = OrderedDict((k.replace("55_transform_relu", "56_transform_negate_odds"), v)
                                               for k, v in mutated["prompt_hashes"].items())
        mutated["benchmark_ids"] = sorted(b.replace("55_transform_relu", "56_transform_negate_odds")
                                          for b in mutated["benchmark_ids"])
        mutated["population_sha256"] = pf.document_sha256(mutated, "population_sha256")
        state = pf.verify_population(mutated, config, "pilot", CONFIG_PATH)
        check("D: same counts but a wrong benchmark -> STALE",
              state["status"] == pf.STALE and any("benchmark_ids" in p for p in state["problems"]))
        # I: a problem type duplicated, another missing (author freeze side)
        author = copy.deepcopy(pf.pilot_002_author_freeze())
        author["benchmarks"] = [b for b in author["benchmarks"] if not b.startswith("fft/")] + \
            ["transform/56_transform_negate_odds"]
        drift = None
        try:
            pf.build_population(config, "pilot", author, CONFIG_PATH)
        except pf.PopulationSelectionDrift as exc:
            drift = str(exc)
        check("I: an authorized list with a duplicated problem type and a missing one is never "
              "reproduced by the selection -> BLOCKED_POPULATION_SELECTION_DRIFT",
              drift is not None and "benchmarks differ" in drift)
        mutated = copy.deepcopy(artifact)
        mutated["problem_type_mapping"] = OrderedDict(mutated["problem_type_mapping"])
        mutated["problem_type_mapping"].pop("fft")
        mutated["problem_type_mapping"]["transform"] = ["transform/55_transform_relu",
                                                        "transform/56_transform_negate_odds"]
        mutated["population_sha256"] = pf.document_sha256(mutated, "population_sha256")
        state = pf.verify_population(mutated, config, "pilot", CONFIG_PATH)
        check("I: a frozen artifact whose problem-type mapping duplicates a type -> STALE",
              state["status"] == pf.STALE and any("problem_type_mapping" in p for p in state["problems"]))
    with tempfile.TemporaryDirectory() as tmp:
        # E: same benchmarks but an execution model missing
        path = repo_config_copy(tmp, mutate=lambda c: c["prompts"].__setitem__(
            "execution_models", ["serial", "omp"]))
        cfg = load_config(path)
        state = pf.verify_population(artifact, cfg, "pilot", path)
        contract = contract_for(path)
        drift = None
        try:
            pf.build_population(cfg, "pilot", pf.pilot_002_author_freeze(), path)
        except pf.PopulationSelectionDrift as exc:
            drift = str(exc)
        check("E: an execution model missing -> STALE + NOT_READY + selection drift",
              state["status"] == pf.STALE and contract["status"] == "NOT_READY"
              and drift is not None and "execution models" in drift)
    with tempfile.TemporaryDirectory() as tmp:
        # F: 2 samples per prompt
        path = repo_config_copy(tmp, mutate=lambda c: c["profiles"]["pilot"].__setitem__(
            "num_samples_per_prompt", 2))
        cfg = load_config(path)
        state = pf.verify_population(artifact, cfg, "pilot", path)
        contract = contract_for(path)
        drift = None
        try:
            pf.build_population(cfg, "pilot", pf.pilot_002_author_freeze(), path)
        except pf.PopulationSelectionDrift as exc:
            drift = str(exc)
        check("F: 2 samples per prompt -> STALE + NOT_READY + selection drift (792 cells != 396)",
              state["status"] == pf.STALE and contract["status"] == "NOT_READY"
              and drift is not None and "samples_per_prompt 2 != 1" in drift)
    with tempfile.TemporaryDirectory() as tmp:
        # G: prefix selection instead of stratified
        path = repo_config_copy(tmp, mutate=lambda c: c["profiles"]["pilot"].__setitem__(
            "selection", "prefix"))
        cfg = load_config(path)
        state = pf.verify_population(artifact, cfg, "pilot", path)
        contract = contract_for(path)
        drift = None
        try:
            pf.build_population(cfg, "pilot", pf.pilot_002_author_freeze(), path)
        except pf.PopulationSelectionDrift as exc:
            drift = str(exc)
        check("G: a 36-prompt PREFIX instead of the stratified selection -> STALE + NOT_READY + drift",
              state["status"] == pf.STALE and contract["status"] == "NOT_READY"
              and drift is not None and "selection 'prefix'" in drift)
    with tempfile.TemporaryDirectory() as tmp:
        # H: prompt text changed, same key
        def edit_text(prompts):
            for e in prompts:
                if e["problem_type"] == problem_type and e["name"] == name and e["parallelism_model"] == pm:
                    e["prompt"] = e["prompt"] + "\n// edited after the freeze"
            return prompts
        path = repo_config_copy(tmp, prompts_mutate=edit_text)
        cfg = load_config(path)
        state = pf.verify_population(artifact, cfg, "pilot", path)
        contract = contract_for(path)
        check("H: a prompt text changed with the same key -> STALE (prompt_hashes) + NOT_READY",
              state["status"] == pf.STALE and any("prompt_hashes" in p for p in state["problems"])
              and contract["status"] == "NOT_READY"
              and blockers_mention(contract, "prompt_hashes", "prompt text changed"))
    # J: equality with pilot_001 grants nothing
    check("J: the artifact records the pilot_001 equality as an OBSERVATION only "
          "(historical population never the source, never an authority)",
          artifact["volatile"]["pilot_001_comparison"]["pilot001_population_equal"] is True
          and artifact["volatile"]["pilot_001_comparison"]["pilot001_population_used_as_authority"] is False
          and artifact["historical_population_used_as_source"] is False)
    with tempfile.TemporaryDirectory() as tmp:
        mutated = copy.deepcopy(artifact)
        mutated["population_source"] = "PILOT_001_HISTORICAL"
        mutated["author_freeze"] = None
        mutated["population_sha256"] = pf.document_sha256(mutated, "population_sha256")
        seam = Path(tmp) / "population.json"
        atomic_io.atomic_write_json(seam, mutated)
        path = repo_config_copy(tmp, mutate=lambda c: c["outputs"].__setitem__(
            "freeze_artifacts", {"population": seam.as_posix()}))
        contract = contract_for(path)
        check("J: a population that merely inherits pilot_001 (no explicit author freeze) is NOT "
              "accepted by the contract",
              contract["status"] == "NOT_READY"
              and (blockers_mention(contract, "population source")
                   or blockers_mention(contract, "population freeze")))


# ---------------------------------------------------------------------------
# 2. model set
# ---------------------------------------------------------------------------

def test_model_set():
    print("== model set: exactly the 11 authorized models, no substitution ==")
    config = load_config(CONFIG_PATH)
    enabled = pf.enabled_model_ids(config)
    check("the enabled config models are exactly the 11 authorized ids",
          enabled == sorted(pf.PILOT_002_MODEL_IDS) and len(enabled) == 11
          and all(m.get("enabled") for m in config["models"] if m["id"] in pf.PILOT_002_MODEL_IDS))

    def disable(model_id):
        def mutate(c):
            for m in c["models"]:
                if m["id"] == model_id:
                    m["enabled"] = False
        return mutate

    def enable(model_id):
        def mutate(c):
            for m in c["models"]:
                if m["id"] == model_id:
                    m["enabled"] = True
        return mutate

    with tempfile.TemporaryDirectory() as tmp:
        path = repo_config_copy(tmp, mutate=disable("qwen37_max"))
        contract = contract_for(path)
        check("a disabled expected model -> NOT_READY (model set mismatch; no automatic "
              "degradation to 10 models)",
              contract["status"] == "NOT_READY" and len(contract["model_ids"]) == 10
              and blockers_mention(contract, "model set mismatch", "population freeze"))
    with tempfile.TemporaryDirectory() as tmp:
        path = repo_config_copy(tmp, mutate=enable("claude_opus_48"))
        contract = contract_for(path)
        check("an extra enabled model -> NOT_READY (model set mismatch)",
              contract["status"] == "NOT_READY" and len(contract["model_ids"]) == 12
              and blockers_mention(contract, "model set mismatch", "population freeze"))

    def substitute(c):
        for m in c["models"]:
            if m["id"] == "gemini_36_flash":
                m["model_name"] = "gemini-3.6-flash-lite"

    with tempfile.TemporaryDirectory() as tmp:
        path = repo_config_copy(tmp, mutate=substitute)
        contract = contract_for(path)
        methodology = pf._load_json(pf.DEFAULT_PATHS["methodology_freeze"])
        state = pf.verify_methodology_freeze(methodology, load_config(path), "pilot", "g++",
                                             pf._load_json(pf.DEFAULT_PATHS["population"]),
                                             pf._load_json(pf.DEFAULT_PATHS["publication_policy"]), path)
        check("same id, another model_name -> methodology freeze STALE (drift names the model plan) "
              "-> NOT_READY",
              contract["status"] == "NOT_READY" and state["status"] == pf.STALE
              and any("gemini_36_flash" in f for f in state["drift_fields"]))

    def reasoning_drift(c):
        for m in c["models"]:
            if m["id"] == "gemini_31_pro":
                m["thinking_level"] = "high"

    with tempfile.TemporaryDirectory() as tmp:
        path = repo_config_copy(tmp, mutate=reasoning_drift)
        contract = contract_for(path)
        check("reasoning configuration drift -> methodology STALE -> NOT_READY",
              contract["status"] == "NOT_READY" and blockers_mention(contract, "methodology freeze STALE"))

    def reorder(c):
        c["models"] = list(reversed(c["models"]))

    with tempfile.TemporaryDirectory() as tmp:
        path = repo_config_copy(tmp, mutate=reorder)
        cfg = load_config(path)
        artifact = pf._load_json(pf.DEFAULT_PATHS["population"])
        state = pf.verify_population(artifact, cfg, "pilot", path)
        rebuilt = pf.build_population(cfg, "pilot", pf.pilot_002_author_freeze(), path)
        contract = contract_for(path)
        check("model ORDER only -> canonicalized: population FRESH, identical population sha, "
              "identical contract model set, contract READY (semantics unchanged)",
              state["status"] == pf.FRESH
              and rebuilt["population_sha256"] == artifact["population_sha256"]
              and contract["model_ids"] == sorted(pf.PILOT_002_MODEL_IDS)
              and contract["status"] == "READY")


# ---------------------------------------------------------------------------
# 3. reuse
# ---------------------------------------------------------------------------

def historical_static_record(sample_id, model):
    """The historical pilot_001 static shape (static_analysis.v2, no
    sample_source_sha256, run_id pilot_001)."""
    return {"schema_version": "static_analysis.v2", "run_id": "pilot_001", "model_id": model,
            "sample_id": sample_id, "execution_model": "serial",
            "tools": {"compiler": {"status": "ok", "findings": []}}}


def test_reuse():
    print("== reuse: NO_PILOT001_MEASUREMENT_REUSE is enforceable ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        contract = world.contract
        check("C: NO_REUSE decided + fresh run -> the fixture contract is READY on the productive "
              "path (no draft) and binds the reuse policy",
              contract["status"] == "READY"
              and contract["reuse_policy"]["policy"] == pf.REUSE_POLICY
              and contract["reuse_policy"]["decided"] is True
              and ra.load_authorization(world.config, world.run_id) is not None)
        report = world.verify()
        check("C: the post-run verifier: reuse_policy_honoured PASS, every record claims the run, "
              "generations postdate the start authorization",
              report["status"] == "PASS" and status_of(report, "reuse_policy_honoured") == "PASS"
              and status_of(report, "record_run_identity") == "PASS"
              and status_of(report, "generation_authorization_binding") == "PASS"
              and report["reuse_policy"]["policy"] == pf.REUSE_POLICY)
        # A: reuse UNDECIDED -> NOT_READY
        world._write_freeze(reuse_decided=False)
        contract = prc.build_contract(world.config_path, "fixture")
        check("A: reuse_status UNDECIDED -> contract NOT_READY",
              contract["status"] == "NOT_READY"
              and blockers_mention(contract, "reuse policy not decided"))
        # B: reuse policy missing
        gate = json.loads(world.cross_pilot_path.read_text(encoding="utf-8"))
        gate.pop("reuse_policy")
        gate["reuse_status"] = pf.REUSE_STATUS_DECIDED
        atomic_io.atomic_write_json(world.cross_pilot_path, gate)
        contract = prc.build_contract(world.config_path, "fixture")
        check("B: reuse policy object missing (status alone) -> NOT_READY",
              contract["status"] == "NOT_READY"
              and blockers_mention(contract, "reuse policy not decided"))
        world._write_freeze()
        check("C: restored -> READY again",
              prc.build_contract(world.config_path, "fixture")["status"] == "READY")

    with tempfile.TemporaryDirectory() as tmp:
        # D: historical records imported AFTER the start -> post-run NON-PASS
        world = World(Path(tmp))
        static_path = world.model_dir(MODEL) / "static_analysis.jsonl"
        records = [json.loads(l) for l in static_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        world.rewrite_jsonl(static_path, [historical_static_record(r["sample_id"], MODEL) for r in records])
        report = world.verify()
        check("D1: pilot_001-shaped static records (static_analysis.v2, run_id pilot_001) under "
              "pilot_002 -> record_run_identity FAIL, reuse_policy_honoured FAIL, run FAIL",
              report["status"] == "FAIL" and status_of(report, "record_run_identity") == "FAIL"
              and status_of(report, "reuse_policy_honoured") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        gen_path = world.raw_dir(MODEL) / "generations.jsonl"
        records = [json.loads(l) for l in gen_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in records:
            r["run_id"] = "pilot_001"
        world.rewrite_jsonl(gen_path, records)
        report = world.verify()
        check("D2: generation records claiming pilot_001 -> record_run_identity FAIL",
              report["status"] == "FAIL" and status_of(report, "record_run_identity") == "FAIL"
              and "generations.jsonl" in next(c["detail"] for c in report["checks"]
                                              if c["check"] == "record_run_identity:%s" % MODEL))
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        gen_path = world.raw_dir(MODEL) / "generations.jsonl"
        records = [json.loads(l) for l in gen_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in records:
            r["created_at_utc"] = "2020-01-01T00:00:00.000000Z"  # a copied old generation, run_id rewritten
        world.rewrite_jsonl(gen_path, records)
        report = world.verify()
        check("D3: generations that PREDATE the start authorization (copied, run_id rewritten) -> "
              "generation_authorization_binding FAIL",
              report["status"] == "FAIL"
              and status_of(report, "generation_authorization_binding") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        summary = {"schema_version": "generation_summary.v1", "run_id": world.run_id, "model_id": MODEL,
                   "run_authorization": {"authorization_sha256": "f" * 64}, "counts": {"skipped_existing": 0}}
        atomic_io.atomic_write_json(world.raw_dir(MODEL) / "generation_summary.json", summary)
        report = world.verify()
        check("D4: a generation summary bound to ANOTHER authorization -> FAIL",
              status_of(report, "generation_authorization_binding") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        asm_path = world.model_dir(MODEL) / "assembly.jsonl"
        entries = [json.loads(l) for l in asm_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for e in entries:
            e["schema_version"] = "assembly.v1"
            e["source_path"] = "thesis/results/intermediate/pilot_001/%s/sources/%s/generated-code.hpp" % (
                MODEL, e["sample_id"])
        world.rewrite_jsonl(asm_path, entries)
        report = world.verify()
        check("D5: assembly.v1 entries pointing at pilot_001 sources -> record_run_identity FAIL",
              status_of(report, "record_run_identity") == "FAIL" and report["status"] == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        # D6: historical records present BEFORE the first start -> refused at start
        world = World(Path(tmp))
        run_id = "pilot_002_second"
        contract = prc.build_contract(world.config_path, "fixture", run_id_override=run_id)
        contract_path = ra.canonical_contract_path(world.config, run_id)
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        prc.freeze_contract(contract, contract_path, allow_draft=True)
        fresh = run_freshness.inspect_run_freshness(world.config, run_id)
        check("D6: a run directory holding only the frozen contract is FRESH",
              fresh["status"] == run_freshness.FRESH and fresh["result_bearing_paths"] == [])
        imported = Path(world.config["outputs"]["raw_dir"]) / run_id / MODEL / "generations.jsonl"
        imported.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(world.raw_dir(MODEL) / "generations.jsonl", imported)
        fresh = run_freshness.inspect_run_freshness(world.config, run_id)
        refused = None
        ra.clear_context()
        try:
            ra.authorize_start(world.config, world.config_path, "fixture", run_id, contract_path,
                               prober=fake_prober, allow_draft_contract=True)
        except ra.StartRefused as exc:
            refused = str(exc)
        check("D6: copied generations before the first start -> NOT_FRESH; authorize_start refuses "
              "(RUN_ID_NOT_FRESH), no authorization is written",
              fresh["status"] == run_freshness.NOT_FRESH
              and refused is not None and "RUN_ID_NOT_FRESH" in refused
              and ra.load_authorization(world.config, run_id) is None)
        imported.unlink()
        iteration = Path(world.config["outputs"]["intermediate_dir"]) / (run_id + "__static_feedback__iter1")
        iteration.mkdir(parents=True)
        fresh = run_freshness.inspect_run_freshness(world.config, run_id)
        check("D7: an existing repair-iteration directory of the base run -> NOT_FRESH",
              fresh["status"] == run_freshness.NOT_FRESH
              and any("repair-iteration" in p for p in fresh["result_bearing_paths"]))
        shutil.rmtree(iteration)
        stage_file = Path(world.config["outputs"]["intermediate_dir"]) / run_id / MODEL / "correctness.jsonl"
        stage_file.parent.mkdir(parents=True, exist_ok=True)
        stage_file.write_text("{}\n", encoding="utf-8")
        refused = None
        try:
            ra.authorize_start(world.config, world.config_path, "fixture", run_id, contract_path,
                               prober=fake_prober, allow_draft_contract=True)
        except ra.StartRefused as exc:
            refused = str(exc)
        check("D8: a copied correctness record before the first start -> refused (RUN_ID_NOT_FRESH)",
              refused is not None and "RUN_ID_NOT_FRESH" in refused)
        shutil.rmtree(stage_file.parent)
        # the PRODUCTIVE first-start sequence: generate.py freezes the run
        # manifest in the parent (global fragment + snapshot + toolchain
        # record) BEFORE the provider child authorizes - that pre-start state
        # is legitimate and must not read as "already started" (review R1)
        from thesis.evaluation import run_manifest
        run_manifest.ensure_run_manifest(world.config, run_id, stage="generation", profile="fixture",
                                         prompt_selection={"selection": "prefix"})
        fresh = run_freshness.inspect_run_freshness(world.config, run_id)
        check("D9a: the run manifest frozen by generate.py's parent (global fragment, snapshot, "
              "toolchain record, global history) is pre-start state -> still FRESH",
              fresh["status"] == run_freshness.FRESH and fresh["result_bearing_paths"] == [])
        ra.clear_context()
        authorization = ra.authorize_start(world.config, world.config_path, "fixture", run_id,
                                           contract_path, prober=fake_prober, allow_draft_contract=True)
        check("D9: the same run, fresh again -> the productive first start proceeds",
              authorization is not None and ra.load_authorization(world.config, run_id) is not None)
        fresh = run_freshness.inspect_run_freshness(world.config, run_id)
        check("D9b: after the authorization the run is no longer fresh (contract / evidence / "
              "authorization fragments)",
              fresh["status"] == run_freshness.NOT_FRESH
              and any("authorization" in p for p in fresh["result_bearing_paths"]))
        ra.clear_context()

    # E: cross-pilot read-only comparison is allowed and changes nothing
    gate_path = pf.CROSS_PILOT_PATH
    before = ch.raw_sha256(gate_path)
    config = load_config(CONFIG_PATH)
    body = pf.population_body(config, "pilot", None, CONFIG_PATH)
    note = pf.pilot001_population_note(body, config)
    check("E: the cross-pilot artifact is read for the comparison only - its bytes are unchanged",
          ch.raw_sha256(gate_path) == before and note["pilot001_population_equal"] is True
          and note["pilot001_population_used_as_authority"] is False)
    gate = pf._load_json(gate_path)
    check("E: the repository gate binds the decisions: reuse DECIDED_NO_REUSE, population DECIDED "
          "with the artifact sha, base run pilot_002 CONFIGURED, publication DECIDED",
          gate["reuse_status"] == pf.REUSE_STATUS_DECIDED
          and gate["reuse_policy"]["policy"] == pf.REUSE_POLICY
          and gate["expected_pilot_002_population"]["status"] == "DECIDED"
          and gate["expected_pilot_002_population"]["population_sha256"]
          == pf._load_json(pf.DEFAULT_PATHS["population"])["population_sha256"]
          and gate["expected_pilot_002_base_run"] == OrderedDict(
              [(k, v) for k, v in gate["expected_pilot_002_base_run"].items()])
          and gate["expected_pilot_002_base_run"]["run_id"] == "pilot_002"
          and gate["expected_pilot_002_base_run"]["status"] == "CONFIGURED"
          and gate["expected_pilot_002_base_run"]["forbid_iteration_variants"] is True
          and gate["publication_policy"]["status"] == "DECIDED"
          and gate["publication_policy"]["policy"] == pf.PUBLICATION_POLICY)
    check("E: frozen enhanced specs are a methodology artifact, not measurement reuse "
          "(the freeze binds their sha; the reuse policy says so explicitly)",
          gate["reuse_policy"]["frozen_enhanced_specs_are_methodology_not_measurement"] is True
          and pf._load_json(pf.DEFAULT_PATHS["methodology_freeze"])["enhanced"]["frozen_specs_sha256"]
          == ch.raw_sha256(pf.FROZEN_SPECS_PATH))


# ---------------------------------------------------------------------------
# 4. publication
# ---------------------------------------------------------------------------

def test_publication():
    print("== publication: POST_RUN_ACCEPTED_RESULTS_ONLY ==")
    policy = pf._load_json(pf.DEFAULT_PATHS["publication_policy"])
    state = pf.verify_publication_policy(policy)
    check("the repository policy is DECIDED, POST_RUN_ACCEPTED_RESULTS_ONLY, sha reproduces",
          state["status"] == pf.FRESH and policy["policy"] == pf.PUBLICATION_POLICY
          and policy["publication_allowed_before_result_acceptance"] is False
          and policy["may_be_presented_as_full_60_benchmark_study"] is False
          and policy["pilot_results_must_be_labelled_as_pilot"] is True
          and policy["historical_records_may_not_be_mutated"] is True
          and len(policy["mandatory_disclosure_sources"]) >= 8)
    ids = {s["id"] for s in policy["mandatory_disclosure_sources"]}
    check("mandatory disclosure sources name the required ones machine-readably",
          {"semantic_disclosure_dense_la_00", "e3_2_D2_clang_tidy_pilot_001_location_limitation",
           "e3_2_D3_gcc_analyzer_confidence_demotion_difference", "e3_2_D1_infer_omp_scope_difference",
           "e3_2_D5_search_35_validation_attempt_exception", "e3_2_all_disclosures",
           "cross_pilot_current_scope"} <= ids)
    states = pf.disclosure_sources_state(policy)
    check("every mandatory disclosure source is present and readable in the repository",
          states and all(s["artifact_readable"] and s["field_present"] for s in states))
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        fixture_policy = json.loads(world.freeze_paths["publication_policy"].read_text(encoding="utf-8"))
        check("C: publication DECIDED -> the fixture contract is READY and binds the policy sha",
              world.contract["status"] == "READY"
              and world.contract["publication_policy"]["policy"] == pf.PUBLICATION_POLICY
              and world.contract["publication_policy"]["sha256"] == fixture_policy["publication_policy_sha256"]
              and fixture_policy["run_id"] == world.run_id)
        world._write_freeze(publication_decided=False)
        contract = prc.build_contract(world.config_path, "fixture")
        check("A/B: publication OPEN (no DECIDED policy artifact) -> NOT_READY",
              contract["status"] == "NOT_READY" and blockers_mention(contract, "publication policy not decided"))
        world._write_freeze()
        world.freeze_paths["publication_policy"].unlink()
        contract = prc.build_contract(world.config_path, "fixture")
        check("B: policy artifact missing -> NOT_READY",
              contract["status"] == "NOT_READY" and blockers_mention(contract, "publication policy not decided"))
        world._write_freeze()
        report = world.verify()
        check("D: post-run verification of a PASS run without result acceptance -> "
              "publication_allowed = false in the verifier report",
              report["status"] == "PASS" and report["publication"]["publication_allowed"] is False
              and any("result acceptance pending" in r for r in report["publication"]["reasons"]))
    passing = OrderedDict([("schema_version", "post_run_verification.v1"), ("run_id", "pilot_002"),
                           ("contract_sha256", "c" * 64), ("status", "PASS"),
                           ("counts", {"PASS": 10, "FAIL": 0, "UNRESOLVED": 0})])
    failing = OrderedDict(passing, status="FAIL", counts={"PASS": 9, "FAIL": 1, "UNRESOLVED": 0})
    accepted = OrderedDict([("schema_version", pf.RESULT_ACCEPTANCE_SCHEMA), ("status", "ACCEPTED"),
                            ("run_id", "pilot_002"), ("post_run_verification_status", "PASS"),
                            ("post_run_verification_sha256", pf.post_run_report_digest(passing)),
                            ("frozen_contract_sha256", "c" * 64),
                            ("decided_by", "author"), ("decided_on", "2026-10-01")])
    pending = OrderedDict(accepted, status="PENDING")
    check("D: verification not performed -> publication_allowed false",
          pf.publication_decision(policy, None, None)["publication_allowed"] is False)
    check("E: verification FAIL -> false",
          pf.publication_decision(policy, failing, accepted)["publication_allowed"] is False)
    check("F: verification PASS but acceptance pending -> false",
          pf.publication_decision(policy, passing, pending)["publication_allowed"] is False
          and pf.publication_decision(policy, passing, None)["publication_allowed"] is False)
    decision = pf.publication_decision(policy, passing, accepted)
    check("G: PASS + ACCEPTED (naming that report) + every mandatory disclosure present -> true, "
          "with the pilot label required",
          decision["publication_allowed"] is True and decision["reasons"] == []
          and "pilot_002" in (decision["label_required"] or ""))
    other = OrderedDict(accepted, post_run_verification_sha256="a" * 64)
    check("G: an acceptance naming ANOTHER verification report -> false",
          pf.publication_decision(policy, passing, other)["publication_allowed"] is False)
    for field in pf.ACCEPTANCE_REQUIRED_FIELDS:
        stripped = OrderedDict(accepted)
        stripped.pop(field)
        check("G: an acceptance without %s -> false" % field,
              pf.publication_decision(policy, passing, stripped)["publication_allowed"] is False)
    check("G: an acceptance recording verification status FAIL / another contract / another run -> false",
          pf.publication_decision(policy, passing, OrderedDict(accepted, post_run_verification_status="FAIL"))["publication_allowed"] is False
          and pf.publication_decision(policy, passing, OrderedDict(accepted, frozen_contract_sha256="d" * 64))["publication_allowed"] is False
          and pf.publication_decision(policy, passing, OrderedDict(accepted, run_id="pilot_001"))["publication_allowed"] is False)
    check("G: a PASS report carrying FAIL counts (inconsistent) -> false",
          pf.publication_decision(policy, OrderedDict(passing, counts={"PASS": 9, "FAIL": 1, "UNRESOLVED": 0}),
                                  accepted)["publication_allowed"] is False)
    check("G: malformed acceptance / policy / report never raise -> false",
          pf.publication_decision(policy, passing, [])["publication_allowed"] is False
          and pf.publication_decision([], passing, accepted)["publication_allowed"] is False
          and pf.publication_decision(policy, "PASS", accepted)["publication_allowed"] is False)
    check("G: a disclosure source whose content is emptied -> false",
          not pf._lookup_field({"disclosures": {"D1": {}}}, "disclosures.*")
          and not pf._lookup_field({"decisions": [{"status": "x"}, {}]}, "decisions[].status")
          and pf._lookup_field({"decisions": [{"benchmark": "b", "reporting_requirement": {"x": 1}}]},
                               "decisions[benchmark=b].reporting_requirement")
          and not pf._lookup_field({"decisions": [{"reporting_requirement": {"x": 1}}]},
                                   "decisions[benchmark=b].reporting_requirement"))
    with tempfile.TemporaryDirectory() as tmp:
        decision = pf.publication_decision(policy, passing, accepted, repo_root=Path(tmp))
        check("G: a mandatory disclosure source missing -> false (no accepted publication without "
              "the required disclosures)",
              decision["publication_allowed"] is False
              and any("disclosure" in r for r in decision["reasons"]))


# ---------------------------------------------------------------------------
# 5. methodical overrides
# ---------------------------------------------------------------------------

def test_overrides():
    print("== methodical overrides: planned NONE, operational selectors allowed ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        report = world.verify()
        check("A: no overrides -> PASS (methodical_override_plan PASS over every registered invocation)",
              report["status"] == "PASS" and status_of(report, "methodical_override_plan") == "PASS"
              and world.contract["methodical_override_plan"]["planned"] == "NONE"
              and world.contract["methodical_override_plan"]["global_policy"] == pf.GLOBAL_OVERRIDE_POLICY)
        # C: a CLI timeout (differs from the contract pin) is refused before the first record
        refused = None
        try:
            stage_runtime.enforce_stage(
                world.config, world.run_id, "correctness",
                effective_values={"effective_run_timeout_seconds": {"value": 60, "source": "CLI"},
                                  "primary_compiler": {"value": "g++", "source": "DEFAULT"}},
                profile="fixture", prober=fake_prober, writer="correctness_tests")
        except ei.InvocationRefused as exc:
            refused = str(exc)
        check("C: CLI --run-timeout 60 vs contract 120 -> refused before the first record",
              refused is not None and "contract pins" in refused)
        # D (CLI): --jobs is an UNPINNED methodical override under plan NONE
        refused = None
        try:
            stage_runtime.enforce_stage(
                world.config, world.run_id, "enhanced",
                effective_values={"specs": {"value": "frozen", "source": "DEFAULT"},
                                  "jobs": {"value": "serial=4", "source": "CLI"},
                                  "effective_enhanced_run_timeout_seconds": {"value": None,
                                                                             "source": "DEFAULT"}},
                profile="fixture", prober=fake_prober, writer="enhanced_tests")
        except ei.InvocationRefused as exc:
            refused = str(exc)
        check("D: CLI --jobs (no contract pin) -> refused as an unpinned methodical override",
              refused is not None and "unpinned methodical override" in refused)
        for field in ("replace_tool_entries", "rerun_gaps", "replace_legacy_record", "skip_unavailable_tools"):
            invocation = {"effective_values": {field: {"value": True, "source": "CLI"}}}
            check("the plan refuses CLI-sourced %s" % field,
                  bool(ei.override_plan_problems(invocation, world.contract)))
        # F / G: contract-derived split-container selectors are operational
        for stage, values in (("static.parcoach", {"tools": {"value": ["parcoach"], "source": "CLI"}}),
                              ("static.llov", {"tools": {"value": ["llov"], "source": "CLI"}}),
                              ("static.main", {"tools": {"value": ["compiler"], "source": "CLI"}}),
                              ("repair_evaluation", {"variant": {"value": "static_feedback", "source": "CLI"}}),
                              ("correctness", {"effective_run_timeout_seconds": {"value": 120, "source": "CLI"},
                                               "primary_compiler": {"value": "g++", "source": "DEFAULT"}})):
            invocation = {"stage": stage, "effective_values": values}
            check("F/G: %s from the CLI is admitted for %s under plan NONE (operational scope "
                  "selector or pinned value)" % (", ".join(values), stage),
                  ei.override_plan_problems(invocation, world.contract) == [])
        # a NARROWED / foreign --tools is a methodical override, not a selector
        for stage, values in (("static.parcoach", {"tools": {"value": ["parcoach", "llov"], "source": "CLI"}}),
                              ("static.main", {"tools": {"value": ["clang_tidy"], "source": "CLI"}}),
                              ("dynamic", {"tools": {"value": ["asan_ubsan"], "source": "CLI"}})):
            invocation = {"stage": stage, "effective_values": values}
            check("a narrowed / foreign --tools for %s is refused under plan NONE" % stage,
                  bool(ei.override_plan_problems(invocation, world.contract)))
        # B: a config niter edit after the freeze -> methodology STALE -> START_REFUSED
        config = yaml.safe_load(world.config_path.read_text(encoding="utf-8"))
        config["stages"]["correctness_tests"]["niter"] = 3
        world.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        decision = prc.t0_guard(world.config_path, "fixture", world.contract_path, bind=False,
                                probe_docker=False)
        check("B: niter changed in the config after the freeze -> START_REFUSED (methodology "
              "freeze STALE, the drifted field named)",
              decision["decision"] == "START_REFUSED"
              and any("methodology freeze STALE" in b and "niter" in b
                      for b in decision["rebuilt_blockers"])
              and "methodology_freeze.status" in decision["drift_fields"])
        config["stages"]["correctness_tests"]["niter"] = 1
        config["stages"]["enhanced_tests"]["enhanced_launch"] = {"omp_threads": 8, "mpi_ranks": 4}
        world.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        decision = prc.t0_guard(world.config_path, "fixture", world.contract_path, bind=False,
                                probe_docker=False)
        check("D: the enhanced launch grid changed in the config -> START_REFUSED (methodology STALE)",
              decision["decision"] == "START_REFUSED"
              and any("methodology freeze STALE" in b for b in decision["rebuilt_blockers"]))
        config["stages"]["enhanced_tests"].pop("enhanced_launch")
        world.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        decision = prc.t0_guard(world.config_path, "fixture", world.contract_path, bind=False,
                                probe_docker=False)
        check("the restored config -> START_ALLOWED again (frozen == rebuilt, no drift)",
              decision["decision"] == "START_ALLOWED" and decision["drift_fields"] == [])

    # E / H: a narrowed FIRST START is refused by generate.py; --poll / dry-run / resume are not
    generate = load_generate_module()
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), models=("m1", "m2"))
        run_id = "pilot_002_narrow"
        contract = prc.build_contract(world.config_path, "fixture", run_id_override=run_id)
        contract_path = ra.canonical_contract_path(world.config, run_id)
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        prc.freeze_contract(contract, contract_path, allow_draft=True)
        config = dict(world.config)
        config["profiles"] = {"fixture": dict(world.config["profiles"]["fixture"], run_id=run_id)}

        def args(**kw):
            base = {"profile": "fixture", "model_id": None, "provider": None, "poll": False,
                    "dry_run": False}
            base.update(kw)
            return type("Args", (), base)()
        narrowed = generate.contracted_model_set_narrowed(config, args(model_id="m1"),
                                                          [{"id": "m1"}])
        check("E: --model-id narrows the contracted model set at the FIRST START -> refused "
              "(CONTRACTED_MODEL_SET_NARROWED, exit 3 class)",
              narrowed is not None and "CONTRACTED_MODEL_SET_NARROWED" in narrowed and "m2" in narrowed)
        check("E: the full population -> not refused",
              generate.contracted_model_set_narrowed(config, args(), [{"id": "m1"}, {"id": "m2"}]) is None)
        check("H: --poll of an already submitted batch is operational -> not refused",
              generate.contracted_model_set_narrowed(config, args(model_id="m1", poll=True),
                                                     [{"id": "m1"}]) is None)
        check("--dry-run previews are never refused",
              generate.contracted_model_set_narrowed(config, args(model_id="m1", dry_run=True),
                                                     [{"id": "m1"}]) is None)
        authorized = dict(config)
        authorized["profiles"] = {"fixture": dict(world.config["profiles"]["fixture"])}
        check("a per-model re-run AFTER the authorization is an operational resume -> not refused",
              generate.contracted_model_set_narrowed(authorized, args(model_id="m1"), [{"id": "m1"}]) is None)
        check("a run without a frozen contract (uncontracted smoke run) is not the freeze's business",
              generate.contracted_model_set_narrowed(
                  dict(config, profiles={"fixture": dict(config["profiles"]["fixture"], run_id="smoke_x")}),
                  args(model_id="m1"), [{"id": "m1"}]) is None)
    # I: the operational host-repo path is part of no condition and no contract
    contract_a = contract_for(CONFIG_PATH)
    previous = os.environ.get("PAREVAL_HOST_REPO")
    os.environ["PAREVAL_HOST_REPO"] = "/some/other/mount"
    try:
        contract_b = contract_for(CONFIG_PATH)
    finally:
        if previous is None:
            os.environ.pop("PAREVAL_HOST_REPO", None)
        else:
            os.environ["PAREVAL_HOST_REPO"] = previous
    check("I: PAREVAL_HOST_REPO changes nothing methodical (identical contract sha, not in the "
          "contract or the methodology freeze)",
          contract_a["contract_sha256"] == contract_b["contract_sha256"]
          and "/some/other/mount" not in json.dumps(contract_b)
          and "host_repo" not in json.dumps(pf._load_json(pf.DEFAULT_PATHS["methodology_freeze"])["conditions"]))
    check("H: --poll and --dry-run are classified NON_METHODICAL by the CLI inventory",
          all(sel in pf.ALLOWED_OPERATIONAL_SELECTORS for sel in ("--poll", "--model-id", "--tools", "--run-id")))


# ---------------------------------------------------------------------------
# 6. contract
# ---------------------------------------------------------------------------

def test_contract():
    print("== contract: fail-closed builder, the real pilot_002 contract ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        base = prc.build_contract(world.config_path, "fixture")
        check("fixture baseline READY (schema v3, every decision bound)",
              base["status"] == "READY" and base["schema_version"] == "pilot_run_contract.v3"
              and base["methodology_freeze"]["status"] == pf.FRESH
              and base["population_freeze"]["status"] == pf.FRESH
              and base["publication_policy"]["decided"] is True)
        world._write_freeze(population_decided=False)
        c = prc.build_contract(world.config_path, "fixture")
        check("population policy not DECIDED -> NOT_READY",
              c["status"] == "NOT_READY" and blockers_mention(c, "pilot_002 population: NOT_YET_DECIDED"))
        world._write_freeze(base_run_configured=False)
        c = prc.build_contract(world.config_path, "fixture")
        check("base run not CONFIGURED -> NOT_READY",
              c["status"] == "NOT_READY" and blockers_mention(c, "base run id: NOT_YET_CONFIGURED"))
        world._write_freeze()
        world.freeze_paths["methodology_freeze"].unlink()
        c = prc.build_contract(world.config_path, "fixture")
        check("methodology freeze missing -> NOT_READY (and the override plan UNDECLARED)",
              c["status"] == "NOT_READY" and blockers_mention(c, "methodology freeze MISSING")
              and blockers_mention(c, "override plan is UNDECLARED"))
        world._write_freeze()
        methodology = json.loads(world.freeze_paths["methodology_freeze"].read_text(encoding="utf-8"))
        methodology["repair"]["max_iterations"] = 5
        methodology["methodology_freeze_sha256"] = pf.document_sha256(methodology, "methodology_freeze_sha256")
        atomic_io.atomic_write_json(world.freeze_paths["methodology_freeze"], methodology)
        c = prc.build_contract(world.config_path, "fixture")
        check("methodology freeze STALE (a value differs from the current state) -> NOT_READY",
              c["status"] == "NOT_READY" and blockers_mention(c, "methodology freeze STALE"))
        methodology["override_policy"]["planned_methodical_cli_overrides"] = [{"stage": "correctness",
                                                                               "run_timeout": 60}]
        methodology["repair"]["max_iterations"] = 2
        methodology["methodology_freeze_sha256"] = pf.document_sha256(methodology, "methodology_freeze_sha256")
        atomic_io.atomic_write_json(world.freeze_paths["methodology_freeze"], methodology)
        c = prc.build_contract(world.config_path, "fixture")
        check("a non-empty methodical override plan -> NOT_READY",
              c["status"] == "NOT_READY" and blockers_mention(c, "override plan is NON_EMPTY"))
        world._write_freeze()
        gate = json.loads(world.cross_pilot_path.read_text(encoding="utf-8"))
        gate["expected_pilot_002_population"]["population_sha256"] = "1" * 64
        atomic_io.atomic_write_json(world.cross_pilot_path, gate)
        c = prc.build_contract(world.config_path, "fixture")
        check("population sha mismatch between the policy and the artifact -> NOT_READY",
              c["status"] == "NOT_READY" and blockers_mention(c, "population sha", "population freeze"))
        world._write_freeze()
        gate = json.loads(world.cross_pilot_path.read_text(encoding="utf-8"))
        gate["publication_policy"]["publication_policy_sha256"] = "2" * 64
        atomic_io.atomic_write_json(world.cross_pilot_path, gate)
        c = prc.build_contract(world.config_path, "fixture")
        check("publication sha mismatch -> NOT_READY",
              c["status"] == "NOT_READY" and blockers_mention(c, "publication"))
        world._write_freeze()
        c = prc.build_contract(world.config_path, "fixture", run_id_override="pilot_002_other")
        check("run_id != the configured base run -> NOT_READY",
              c["status"] == "NOT_READY" and blockers_mention(c, "differs from the configured expected base run"))
        c = prc.build_contract(world.config_path, "fixture", run_id_override="pilot_001")
        check("the historical run id -> NOT_READY", blockers_mention(c, "historical pilot_001"))
        c = prc.build_contract(world.config_path, "fixture",
                               run_id_override=world.run_id + "__combined_feedback__iter2")
        check("an iteration-like run id -> NOT_READY", blockers_mention(c, "repair-iteration"))
        readiness = json.loads(world.readiness_path.read_text(encoding="utf-8"))
        readiness["gate"] = "NOT_READY"
        atomic_io.atomic_write_json(world.readiness_path, readiness)
        c = prc.build_contract(world.config_path, "fixture")
        check("readiness artifact NOT_READY -> NOT_READY",
              c["status"] == "NOT_READY" and blockers_mention(c, "readiness gate"))
        readiness["gate"] = "READY"
        atomic_io.atomic_write_json(world.readiness_path, readiness)
        check("restored -> READY", prc.build_contract(world.config_path, "fixture")["status"] == "READY")
        # the freeze artifacts of ANOTHER run never make this run READY
        other = Path(tmp) / "other"
        other_world = World(other, run_id="pilot_002_other_world")
        for key in ("population", "methodology_freeze"):
            shutil.copy(other_world.freeze_paths[key], world.freeze_paths[key])
        c = prc.build_contract(world.config_path, "fixture")
        check("freeze artifacts of another run id -> NOT_READY (never inherited)",
              c["status"] == "NOT_READY" and blockers_mention(c, "frozen for run"))
        world._write_freeze()
    # the real pilot_002 contract
    contract = contract_for(CONFIG_PATH)
    check("REAL: pilot_002 contract READY, run_id pilot_002, 11 models, 36 x 1 samples, 396 cells",
          contract["status"] == "READY" and contract["blockers"] == []
          and contract["run_id"] == "pilot_002" and len(contract["model_ids"]) == 11
          and contract["population"]["expected_sample_count"] == 36
          and contract["population_freeze"]["total_model_prompt_cells"] == 396
          and contract["base_run"]["expected_base_run_id"] == "pilot_002"
          and contract["base_run"]["forbid_iteration_variants"] is True)
    check("REAL: the contract binds the methodology, population, publication and cross-pilot shas "
          "consistently with the artifacts",
          contract["methodology_freeze"]["sha256"]
          == pf._load_json(pf.DEFAULT_PATHS["methodology_freeze"])["methodology_freeze_sha256"]
          and contract["population_freeze"]["sha256"]
          == pf._load_json(pf.DEFAULT_PATHS["population"])["population_sha256"]
          and contract["publication_policy"]["sha256"]
          == pf._load_json(pf.DEFAULT_PATHS["publication_policy"])["publication_policy_sha256"]
          and contract["conditions"]["cross_pilot_artifact_sha256"]
          == pf._load_json(pf.CROSS_PILOT_PATH)["cross_pilot_fingerprint_sha256"]
          and contract["conditions"]["technical_provenance_cleanup_status"] == "COMPLETE"
          and contract["conditions"]["e3_2_decision"] == "ACCEPTED")
    check("REAL: no hash cycle - the methodology freeze does not carry the contract sha, the "
          "receipt does",
          contract["contract_sha256"] not in json.dumps(pf._load_json(pf.DEFAULT_PATHS["methodology_freeze"]))
          and contract["contract_sha256"] not in json.dumps(pf._load_json(pf.CROSS_PILOT_PATH)))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "c.json"
        sha = prc.freeze_contract(contract, path)
        frozen = prc.load_frozen(path)
        rebuilt = contract_for(CONFIG_PATH)
        check("REAL: freeze -> reload -> own sha reproduces -> rebuild identical, drift_fields []",
              sha == frozen["contract_sha256"] == rebuilt["contract_sha256"]
              and prc.contract_diff(frozen, rebuilt) == [])
    canonical = ra.canonical_contract_path(load_config(CONFIG_PATH), "pilot_002")
    if canonical.is_file():
        frozen = prc.load_frozen(canonical)
        check("REAL: the canonical frozen contract equals the live rebuild (READY, no drift)",
              frozen["status"] == "READY" and frozen["contract_sha256"] == contract["contract_sha256"]
              and prc.contract_diff(frozen, contract) == [])
        check("REAL: no start authorization, no T0 bind, no manifest for pilot_002",
              ra.load_authorization(load_config(CONFIG_PATH), "pilot_002") is None
              and run_freshness.inspect_run_freshness(load_config(CONFIG_PATH), "pilot_002")["status"]
              == run_freshness.FRESH)
        receipt = pf._load_json(pf.DEFAULT_PATHS["run_freeze_receipt"])
        check("REAL: the run freeze receipt names this contract and says start_authorized false, "
              "t0_bound false, provider_calls 0, result_records_written 0",
              receipt is not None and receipt["frozen_contract_sha256"] == frozen["contract_sha256"]
              and receipt["start_authorized"] is False and receipt["t0_bound"] is False
              and receipt["provider_calls"] == 0 and receipt["result_records_written"] == 0
              and receipt["receipt_sha256"] == pf.document_sha256(receipt, "receipt_sha256"))
    else:
        print("  [note] canonical pilot_002 contract not frozen yet - the REAL frozen-contract checks "
              "run once it exists")


# ---------------------------------------------------------------------------
# 7. preflight lines
# ---------------------------------------------------------------------------

def test_preflight_lines():
    print("== preflight: the freeze lines ==")
    config = load_config(CONFIG_PATH)
    contract = contract_for(CONFIG_PATH)
    lines = pilot_preflight.pilot_002_freeze_lines(contract, config)
    text = "\n".join(lines)
    flags = dict(pilot_preflight.FREEZE_FLAGS)
    check("population / reuse / publication / methodology READY lines",
          "PILOT_002_POPULATION_FREEZE_READY = true" in text
          and "PILOT_002_REUSE_POLICY_DECIDED = true" in text
          and "PILOT_002_PUBLICATION_POLICY_DECIDED = true" in text
          and "PILOT_002_METHODOLOGY_FREEZE_READY = true" in text
          and "PLANNED_METHODICAL_OVERRIDES = NONE" in text
          and "PILOT001_POPULATION_USED_AS_AUTHORITY = false" in text)
    check("PILOT_START_ALLOWED is always false in the preflight",
          "PILOT_START_ALLOWED = false" in text)
    canonical = ra.canonical_contract_path(config, "pilot_002")
    if canonical.is_file():
        check("frozen contract READY + run fresh -> SAFE_TO_PROCEED_TO_FINAL_ENVIRONMENT_GATE = true",
              "PILOT_002_FROZEN_CONTRACT_READY = true" in text and "PILOT_002_RUN_ID_FRESH = true" in text
              and "SAFE_TO_PROCEED_TO_FINAL_ENVIRONMENT_GATE = true" in text and flags.get("safe") is True)
    else:
        check("no frozen contract yet -> SAFE_TO_PROCEED_TO_FINAL_ENVIRONMENT_GATE = false",
              "PILOT_002_FROZEN_CONTRACT_READY = false" in text
              and "SAFE_TO_PROCEED_TO_FINAL_ENVIRONMENT_GATE = false" in text)
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        lines = pilot_preflight.pilot_002_freeze_lines(world.contract, world.config)
        text = "\n".join(lines)
        check("a fixture run that already started is reported non-fresh / authorized (never safe)",
              "PILOT_002_RUN_ID_FRESH = false" in text and "PILOT_002_AUTHORIZED = true" in text
              and "SAFE_TO_PROCEED_TO_FINAL_ENVIRONMENT_GATE = false" in text)


# ---------------------------------------------------------------------------
# 8. adversarial review round 1 - regressions
# ---------------------------------------------------------------------------

def _rebind_cross_pilot(world, **updates):
    gate = json.loads(world.cross_pilot_path.read_text(encoding="utf-8"))
    for key, value in updates.items():
        gate[key] = value
    gate.pop("cross_pilot_fingerprint_sha256", None)
    gate["cross_pilot_fingerprint_sha256"] = ch.canonical_sha256(gate)
    atomic_io.atomic_write_json(world.cross_pilot_path, gate)


def test_review_round1():
    print("== adversarial review round 1: regressions ==")
    config = load_config(CONFIG_PATH)
    artifact = pf._load_json(pf.DEFAULT_PATHS["population"])
    # POP-1 / MS-2 / CTR-04: the author literal is the verification authority
    forged = copy.deepcopy(artifact)
    forged["author_freeze"]["decided_by"] = "copied from pilot_001"
    forged["population_sha256"] = pf.document_sha256(forged, "population_sha256")
    state = pf.verify_population(forged, config, "pilot", CONFIG_PATH)
    check("POP-1: a pilot_002 artifact whose author_freeze block differs from the wave literal -> STALE",
          state["status"] == pf.STALE and any("author_freeze block differs" in x for x in state["problems"]))
    refused = None
    try:
        pf.fixture_author_freeze(config, "pilot")
    except pf.PopulationSelectionDrift as exc:
        refused = str(exc)
    check("POP-1: fixture_author_freeze refuses the productive run id",
          refused is not None and "BLOCKED_POPULATION_SELECTION_DRIFT" in refused)
    forged = copy.deepcopy(artifact)
    forged["prompt_set_sha256"] = "f" * 64
    forged["population_sha256"] = pf.document_sha256(forged, "population_sha256")
    state = pf.verify_population(forged, config, "pilot", CONFIG_PATH)
    check("CTR-04: every hashed population field is rebuilt and diffed (prompt_set_sha256 tampered -> STALE)",
          state["status"] == pf.STALE and any("prompt_set_sha256" in x for x in state["problems"]))
    # POP-2 / MS-1 / CTR-01: pins are recomputed from content
    with tempfile.TemporaryDirectory() as tmp:
        gate = pf._load_json(pf.CROSS_PILOT_PATH)
        gate["reuse_policy"]["generation_reuse"] = True  # edited WITHOUT recomputation
        seam = Path(tmp) / "cross_pilot.json"
        atomic_io.atomic_write_json(seam, gate)
        path = repo_config_copy(tmp, mutate=lambda c: c["outputs"].__setitem__("cross_pilot_artifact", seam.as_posix()))
        contract = contract_for(path)
        check("POP-2/MS-1/CTR-01: a cross-pilot artifact edited without fingerprint recomputation -> pin "
              "None, NOT_READY ('edited without recomputation'; fixture seam refused for pilot_002 too)",
              contract["status"] == "NOT_READY"
              and contract["conditions"]["cross_pilot_artifact_sha256"] is None
              and blockers_mention(contract, "edited without recomputation")
              and blockers_mention(contract, "fixture seam"))
    for path_const, field, blocker in ((pf.E3_2_DECISIONS_PATH, "decisions_sha256", "e3_2_decisions_sha256"),
                                       (pf.TECHNICAL_PROVENANCE_PATH, "artifact_sha256",
                                        "technical_provenance_cleanup_sha256"),
                                       (pf.E3_2_CONFIRMATION_PATH, "confirmation_sha256",
                                        "e3_2_author_confirmation_sha256")):
        document = pf._load_json(path_const)
        pinned = pf.pinned_artifact(path_const, field)
        tampered = copy.deepcopy(document)
        tampered["tampered_after_freeze"] = True
        check("CTR-01: %s pin reproduces from content; a tampered copy does not" % blocker,
              pinned["reproduces"] and pinned["recomputed"] == document[field]
              and pf.recompute_self_hash(tampered, field) is None)
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        _rebind_cross_pilot(world, reuse_policy=dict(
            json.loads(world.cross_pilot_path.read_text(encoding="utf-8"))["reuse_policy"],
            generation_reuse=True, pilot_002_base_measurements="COPIED_FROM_PILOT_001"))
        contract = prc.build_contract(world.config_path, "fixture")
        check("CTR-07: a reuse policy whose flags allow reuse is NOT decided -> NOT_READY",
              contract["status"] == "NOT_READY" and blockers_mention(contract, "reuse policy not decided"))
        world._write_freeze()
        policy = json.loads(world.freeze_paths["publication_policy"].read_text(encoding="utf-8"))
        policy["mandatory_disclosure_sources"] = policy["mandatory_disclosure_sources"][:1]
        policy["publication_policy_sha256"] = pf.document_sha256(policy, "publication_policy_sha256")
        atomic_io.atomic_write_json(world.freeze_paths["publication_policy"], policy)
        _rebind_cross_pilot(world, publication_policy=dict(
            json.loads(world.cross_pilot_path.read_text(encoding="utf-8"))["publication_policy"],
            publication_policy_sha256=policy["publication_policy_sha256"]))
        contract = prc.build_contract(world.config_path, "fixture")
        check("CTR-03: a self-consistent publication policy that differs from the code-canonical one "
              "(gutted disclosure list) -> NOT_READY",
              contract["status"] == "NOT_READY"
              and blockers_mention(contract, "code-canonical policy"))
        world._write_freeze()
        # PUB-9: the ACCEPTED path through verify_pilot_run
        report = world.verify()
        check("baseline PASS, publication not allowed (acceptance pending)",
              report["status"] == "PASS" and report["publication"]["publication_allowed"] is False)
        digest = pf.post_run_report_digest(report)
        acceptance = OrderedDict([("schema_version", pf.RESULT_ACCEPTANCE_SCHEMA), ("status", "ACCEPTED"),
                                  ("run_id", world.run_id), ("post_run_verification_status", "PASS"),
                                  ("post_run_verification_sha256", digest),
                                  ("frozen_contract_sha256", world.contract_sha),
                                  ("decided_by", "fixture author"), ("decided_on", "2026-10-01")])
        atomic_io.atomic_write_json(world.freeze_paths["result_acceptance"], acceptance)
        report2 = world.verify()
        check("PUB-9: an acceptance naming THIS report's digest (report minus the publication block) and "
              "the bound contract -> publication_allowed true through verify_pilot_run",
              report2["publication"]["publication_allowed"] is True
              and report2["publication"]["post_run_verification_sha256"] == digest
              and pf.post_run_report_digest(report2) == digest)
        acceptance["frozen_contract_sha256"] = "0" * 64
        atomic_io.atomic_write_json(world.freeze_paths["result_acceptance"], acceptance)
        report3 = world.verify()
        check("PUB-3: an acceptance naming another contract -> false",
              report3["publication"]["publication_allowed"] is False)
        atomic_io.atomic_write_json(world.freeze_paths["result_acceptance"], [])
        report4 = world.verify()
        check("PUB-6: a malformed acceptance artifact never crashes the verifier -> false",
              report4["publication"]["publication_allowed"] is False
              and any("malformed" in r for r in report4["publication"]["reasons"]))
        world.freeze_paths["result_acceptance"].unlink()
        # R2: a backdated authorization (volatile field edited) is detected
        from thesis.evaluation import manifest_fragments as mf
        inter = Path(world.config["outputs"]["intermediate_dir"])
        auth_path = mf.fragment_path(inter, world.run_id, "authorization", "start")
        fragment = json.loads(auth_path.read_text(encoding="utf-8"))
        fragment["content"]["authorized_at_utc"] = "2020-01-01T00:00:00.000000Z"
        atomic_io.atomic_write_json(auth_path, fragment)
        mf.write_snapshot(inter, world.run_id)
        report5 = world.verify()
        check("R2: a backdated authorized_at_utc (a volatile field, edited in place) -> "
              "run_provenance_integrity FAIL (content hash)",
              status_of(report5, "run_provenance_integrity") == "FAIL" and report5["status"] == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        gen_path = world.raw_dir(MODEL) / "generations.jsonl"
        records = [json.loads(l) for l in gen_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in records:
            r.pop("created_at_utc", None)
        world.rewrite_jsonl(gen_path, records)
        report = world.verify()
        check("R3: generation records without a parseable created_at_utc -> FAIL (never 'postdates')",
              status_of(report, "generation_authorization_binding") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        (world.raw_dir(MODEL) / "generation_summary.json").unlink()
        report = world.verify()
        check("R6: a model with generation records but no generation_summary.json -> UNRESOLVED, never PASS",
              status_of(report, "generation_authorization_binding") == "UNRESOLVED"
              and report["status"] != "PASS")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        gen_path = world.raw_dir(MODEL) / "generations.jsonl"
        records = [json.loads(l) for l in gen_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in records:
            r["model"] = {"id": MODEL, "provider": "mock", "model_name": "another-model"}
        world.rewrite_jsonl(gen_path, records)
        report = world.verify()
        check("MS-8: generation records naming another model identity than the contracted one -> FAIL",
              status_of(report, "record_run_identity") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        cor_path = world.model_dir(MODEL) / "correctness.jsonl"
        records = [json.loads(l) for l in cor_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in records:
            r["created_at_utc"] = "2020-01-01T00:00:00.000000Z"
        world.rewrite_jsonl(cor_path, records)
        report = world.verify()
        check("R5: stage records predating the start authorization -> record_run_identity FAIL",
              status_of(report, "record_run_identity") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        static_path = world.model_dir(MODEL) / "static_analysis.jsonl"
        records = [json.loads(l) for l in static_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in records:
            r["sample_source_sha256"] = "0" * 64
        world.rewrite_jsonl(static_path, records)
        report = world.verify()
        check("R5: static records that analysed other bytes than the assembled source -> FAIL",
              status_of(report, "record_run_identity") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        # R4: historical repair-iteration records under the base run's namespace
        world = World(Path(tmp))
        iteration = world.run_id + "__static_feedback__iter1"
        src = world.raw_dir(MODEL) / "generations.jsonl"
        dst = Path(world.config["outputs"]["raw_dir"]) / iteration / MODEL / "generations.jsonl"
        dst.parent.mkdir(parents=True, exist_ok=True)
        records = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in records:
            r["run_id"] = "pilot_001__static_feedback__iter1"
        world.rewrite_jsonl(dst, records)
        report = world.verify()
        check("R4: copied historical repair-iteration records (foreign run id) -> "
              "repair_iteration_record_identity FAIL, reuse_policy_honoured FAIL",
              status_of(report, "repair_iteration_record_identity") == "FAIL"
              and status_of(report, "reuse_policy_honoured") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        # OVR-3: a stage runner on a repair-iteration run of a contracted base
        world = World(Path(tmp))
        iteration = world.run_id + "__static_feedback__iter1"
        from thesis.evaluation import run_manifest
        refused = None
        try:
            stage_runtime.enforce_stage(
                world.config, iteration, "correctness",
                effective_values={"effective_run_timeout_seconds": {"value": 5, "source": "CLI"},
                                  "primary_compiler": {"value": "clang++", "source": "CLI"}},
                profile="fixture", prober=fake_prober, writer="correctness_tests")
        except stage_runtime.StageRuntimeDrift as exc:
            refused = str(exc)
        check("OVR-3: a stage runner invoked directly on a repair-iteration run of a contracted base -> "
              "refused (REPAIR_ITERATION_RUN_NOT_INVOCABLE)",
              refused is not None and "REPAIR_ITERATION_RUN_NOT_INVOCABLE" in refused)
        # OVR-1: a methodical config edit AFTER T0 is refused before the first record
        edited = copy.deepcopy(world.config)
        edited["stages"]["correctness_tests"]["niter"] = 7
        refused = None
        try:
            stage_runtime.enforce_stage(
                edited, world.run_id, "correctness",
                effective_values={"effective_run_timeout_seconds": {"value": 120, "source": "CONFIG"},
                                  "primary_compiler": {"value": "g++", "source": "DEFAULT"}},
                profile="fixture", prober=fake_prober, writer="correctness_tests")
        except stage_runtime.StageRuntimeDrift as exc:
            refused = str(exc)
        check("OVR-1: niter edited in the config after T0 -> refused before the first record "
              "(METHODICAL_CONFIG_DRIFT)",
              refused is not None and "METHODICAL_CONFIG_DRIFT" in refused and "niter" in refused)
        # OVR-1 post-run: a recorded methodical drift fails the verifier
        run_manifest.ensure_run_manifest(edited, world.run_id, stage="correctness_tests", profile="fixture")
        report = world.verify()
        check("OVR-1: a methodical config drift recorded in the manifest -> methodical_config_drift FAIL",
              status_of(report, "methodical_config_drift") == "FAIL" and report["status"] == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        # OVR-2: dynamic coverage + narrowed dynamic --tools
        dyn = {"enabled": True, "tools": {"asan_ubsan": {"enabled": True, "execution_models": ["serial"]},
                                          "tsan": {"enabled": False}, "memcheck": {"enabled": True,
                                                                                   "execution_models": ["serial"]},
                                          "must": {"enabled": False}, "helgrind": {"enabled": False},
                                          "drd": {"enabled": False}},
               "output_file_name": "dynamic_analysis.jsonl"}
        world = World(Path(tmp), stage_overrides={"dynamic_analysis": dyn})
        report = world.verify()
        check("OVR-2: the contract pins the dynamic toolset; missing dynamic tool entries -> "
              "dynamic_coverage FAIL",
              set(world.contract["dynamic_toolset"]) >= {"asan_ubsan", "memcheck"}
              and status_of(report, "dynamic_coverage") == "FAIL")
        invocation = {"stage": "dynamic", "effective_values": {"tools": {"value": ["asan_ubsan"], "source": "CLI"}}}
        check("OVR-2: a narrowed dynamic --tools is refused under plan NONE",
              bool(ei.override_plan_problems(invocation, world.contract)))
        invocation = {"stage": "dynamic", "effective_values": {"tools": {"value": ["asan_ubsan", "memcheck"],
                                                                         "source": "CLI"}}}
        check("OVR-2: the full contracted dynamic tool set from the CLI is admitted",
              ei.override_plan_problems(invocation, world.contract) == [])
    with tempfile.TemporaryDirectory() as tmp:
        # OVR-4 / R7: a provider child's first start is refused, the orchestrator's full start proceeds
        world = World(Path(tmp), models=("m1", "m2"))
        run_id = "pilot_002_scope"
        contract = prc.build_contract(world.config_path, "fixture", run_id_override=run_id)
        contract_path = ra.canonical_contract_path(world.config, run_id)
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        prc.freeze_contract(contract, contract_path, allow_draft=True)
        refused = None
        ra.clear_context()
        try:
            ra.authorize_start(world.config, world.config_path, "fixture", run_id, contract_path,
                               prober=fake_prober, allow_draft_contract=True, requested_model_scope=["m1"])
        except ra.StartRefused as exc:
            refused = str(exc)
        check("R7: a single provider child as the FIRST START -> refused (CONTRACTED_MODEL_SET_NARROWED), "
              "no authorization written",
              refused is not None and "CONTRACTED_MODEL_SET_NARROWED" in refused
              and ra.load_authorization(world.config, run_id) is None)
        ra.clear_context()
        authorization = ra.authorize_start(world.config, world.config_path, "fixture", run_id, contract_path,
                                           prober=fake_prober, allow_draft_contract=True,
                                           requested_model_scope=["m2", "m1"])
        check("R7: the orchestrator's full-population first start proceeds; the T0 evidence records the "
              "provider endpoint identities",
              authorization is not None
              and isinstance((run_manifest_evidence(world.config, run_id) or {}).get("provider_endpoint_identities"), dict))
        ra.clear_context()
    with tempfile.TemporaryDirectory() as tmp:
        # OVR-5: the FIRST enhanced invocation after a T0-created manifest pins the fingerprint
        from thesis.evaluation import run_manifest
        world = World(Path(tmp), repair_loops=False)
        run_id = "pilot_002_enh"
        run_manifest.ensure_run_manifest(world.config, run_id, stage="t0_authorization", profile="fixture")
        try:
            run_manifest.ensure_run_manifest(
                world.config, run_id, stage="enhanced_tests", profile="fixture",
                enhanced_execution={"enhanced_execution_fingerprint_sha256": "a" * 64, "components": {}},
                enhanced_specs_path=pf.FROZEN_SPECS_PATH)
            pinned = True
        except run_manifest.EnhancedExecutionConditionMismatch:
            pinned = False
        refused = False
        try:
            run_manifest.ensure_run_manifest(
                world.config, run_id, stage="enhanced_tests", profile="fixture",
                enhanced_execution={"enhanced_execution_fingerprint_sha256": "b" * 64, "components": {}},
                enhanced_specs_path=pf.FROZEN_SPECS_PATH)
        except run_manifest.EnhancedExecutionConditionMismatch:
            refused = True
        check("OVR-5: the first enhanced invocation on a T0-created manifest pins its fingerprint; a "
              "second, different fingerprint is refused", pinned and refused)
    with tempfile.TemporaryDirectory() as tmp:
        # MS-3: duplicate model ids
        def duplicate(c):
            c["models"].append(dict(c["models"][0], enabled=False, model_name="other"))
        path = repo_config_copy(tmp, mutate=duplicate)
        contract = contract_for(path)
        check("MS-3: a duplicated model id (even disabled) -> NOT_READY",
              contract["status"] == "NOT_READY" and blockers_mention(contract, "duplicate model id"))
    with tempfile.TemporaryDirectory() as tmp:
        # CTR-06: variant-suffix / iter tail base run ids
        for bad in ("pilot_002__x", "pilot_002__static_feedback", "pilot_002_iter1"):
            contract = contract_for(CONFIG_PATH, run_id=bad)
            check("CTR-06: base run id %r -> NOT_READY (iteration / variant-like)" % bad,
                  contract["status"] == "NOT_READY" and blockers_mention(contract, "repair-iteration"))
    with tempfile.TemporaryDirectory() as tmp:
        # CTR-08 / POP-5 / MS-6: malformed artifacts never crash the builder
        path = repo_config_copy(tmp, mutate=lambda c: c["outputs"].__setitem__(
            "freeze_artifacts", {"population": (Path(tmp) / "pop.json").as_posix()}))
        (Path(tmp) / "pop.json").write_text("[1, 2, 3]", encoding="utf-8")
        contract = contract_for(path)
        check("CTR-08: a population artifact that is a JSON list -> NOT_READY (MALFORMED), no crash",
              contract["status"] == "NOT_READY" and blockers_mention(contract, "population freeze MALFORMED"))
        cross = Path(tmp) / "cross.json"
        cross.write_text('"not an object"', encoding="utf-8")
        path = repo_config_copy(tmp, mutate=lambda c: c["outputs"].__setitem__("cross_pilot_artifact", cross.as_posix()))
        contract = contract_for(path)
        check("CTR-08: a cross-pilot artifact that is not an object -> NOT_READY, no crash",
              contract["status"] == "NOT_READY" and blockers_mention(contract, "not a JSON object"))
    # CTR-11: a stale readiness artifact
    with tempfile.TemporaryDirectory() as tmp:
        readiness = json.loads(pf.READINESS_PATH.read_text(encoding="utf-8"))
        readiness["repair_condition_sha256"] = "9" * 64
        stale = Path(tmp) / "readiness.json"
        atomic_io.atomic_write_json(stale, readiness)
        path = repo_config_copy(tmp, mutate=lambda c: c["outputs"].__setitem__("readiness_artifact", stale.as_posix()))
        contract = contract_for(path)
        check("CTR-11: a READY readiness artifact whose repair condition does not reproduce -> NOT_READY",
              contract["status"] == "NOT_READY" and blockers_mention(contract, "readiness artifact stale"))
    # OVR-6: an unknown source label counts as an override source
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        invocation = {"stage": "enhanced", "effective_values": {"jobs": {"value": "serial=4", "source": "cli"}}}
        check("OVR-6: a misspelt source label is treated as an override source (fail closed)",
              bool(ei.override_plan_problems(invocation, world.contract)))
    # MS-9: secret-like keys are never frozen verbatim
    refused = None
    try:
        pf._refuse_secret_like({"extra_body": {"api_key": "x"}}, "models[m]")
    except ValueError as exc:
        refused = str(exc)
    check("MS-9: a secret-like key inside the reasoning configuration is refused from the freeze",
          refused is not None and "secret-like" in refused)
    # POP-3: the prompt artifact is pinned LF-normalized
    check("POP-3: the population pins the prompt artifact by its LF-normalized sha (EOL-independent)",
          artifact["source"]["prompt_artifact_sha256_lf_normalized"] == ch.lf_normalized_sha256(
              REPO_ROOT / config["prompts"]["path"])
          and "prompt_artifact_raw_sha256_at_freeze" in artifact["volatile"])
    # MS-4: endpoint identities are hashes, never values
    identities = ra.provider_endpoint_identities(config)
    check("MS-4: provider endpoint identities are recorded as hashes (or UNSET/None), never URL values",
          all(v is None or v.startswith("UNSET:") or (len(v) == 64 and "://" not in v)
              for v in identities.values()) and len(identities) == 11)


def run_manifest_evidence(config, run_id):
    from thesis.evaluation.run_manifest import load_manifest

    return (load_manifest(config, run_id) or {}).get("runtime_evidence")


def main() -> int:
    for test in (test_population, test_model_set, test_reuse, test_publication, test_overrides,
                 test_contract, test_preflight_lines, test_review_round1):
        test()
    if FAILURES:
        print("\n%d of %d checks FAILED:" % (len(FAILURES), CHECKS))
        for failure in FAILURES:
            print("  - " + failure)
        return 1
    print("\nAll %d pilot_002 freeze checks passed." % CHECKS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
