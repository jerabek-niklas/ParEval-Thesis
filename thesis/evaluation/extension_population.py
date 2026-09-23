"""Exact complement selection. No manual second benchmark list; no result writes."""
from __future__ import annotations
import json
from pathlib import Path
from collections import defaultdict
from thesis.evaluation import condition_hashing as ch

ROOT = Path(__file__).resolve().parents[2]
MODELS = {"serial", "omp", "mpi"}

def select_complement(prompts, execution_models, problem_types, prompt_limit, exclude_population):
    from thesis.evaluation.pilot_freeze import document_sha256
    if set(execution_models or []) != MODELS or len(execution_models) != 3:
        raise ValueError("complement requires exactly serial/omp/mpi")
    if problem_types is not None or prompt_limit is not None or not exclude_population:
        raise ValueError("complement refuses narrowing or missing exclude population")
    path = Path(exclude_population)
    if not path.is_absolute():
        path = ROOT / path
    pilot = json.loads(path.read_text(encoding="utf-8"))
    if (pilot.get("run_id") != "pilot_002" or
            document_sha256(pilot, "population_sha256") != pilot.get("population_sha256")):
        raise ValueError("invalid pilot population identity/fingerprint")
    groups, hashes = defaultdict(list), {}
    for prompt in prompts:
        benchmark = "%s/%s" % (prompt["problem_type"], prompt["name"])
        key = "%s|%s|%s" % (prompt["problem_type"], prompt["name"], prompt["parallelism_model"])
        if key in hashes:
            raise ValueError("duplicate prompt: " + key)
        hashes[key] = ch.utf8_sha256(prompt["prompt"])
        groups[benchmark].append(prompt["parallelism_model"])
    if len(groups) != 60 or len(hashes) != 180:
        raise ValueError("full population must be exactly 60/180")
    if any(len(values) != 3 or set(values) != MODELS for values in groups.values()):
        raise ValueError("incomplete execution-model triple")
    excluded = pilot.get("benchmark_ids") or []
    if len(excluded) != 12 or len(set(excluded)) != 12 or not set(excluded) <= set(groups):
        raise ValueError("pilot population must be twelve distinct full-population benchmarks")
    expected = {key: value for key,value in hashes.items()
                if "/".join(key.split("|")[:2]) in excluded}
    if expected != pilot.get("prompt_hashes"):
        raise ValueError("pilot prompt hash/key disagreement")
    selected = [p for p in prompts if "%s/%s" % (p["problem_type"],p["name"]) not in excluded]
    if len(selected) != 144:
        raise ValueError("extension must contain 144 prompts")
    return selected
