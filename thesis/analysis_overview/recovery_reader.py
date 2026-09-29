"""Stage-aware reader; never relabels native records as a single fake run."""
from pathlib import Path
import json

from thesis.evaluation.recovery_lineage import PARENT, PILOT, RECOVERY, RecoveryRefused
from thesis.evaluation.verify_parent_base_evidence import records

BASE_FILES = {"generation": ("raw", "generations.jsonl"),
              "assembly": ("intermediate", "assembly.jsonl"),
              "static": ("intermediate", "static_analysis.jsonl"),
              "correctness": ("intermediate", "correctness.jsonl"),
              "dynamic": ("intermediate", "dynamic_analysis.jsonl")}


def stage_sources(stage):
    if stage in BASE_FILES:
        return (PILOT, PARENT)
    if stage in ("enhanced", "repair"):
        return (PILOT, RECOVERY)
    raise RecoveryRefused("unknown composite stage")


def read_stage(root, stage, models):
    """Use after composite V2 verification; return original rows in envelopes."""
    root = Path(root)
    result = []
    seen = set()
    for source in stage_sources(stage):
        for model in models:
            if stage == "repair":
                paths = sorted((root / "thesis/results/raw").glob(source + "__*/" + model + "/generations.jsonl"))
            else:
                area, name = BASE_FILES.get(stage, ("intermediate", "enhanced_tests.jsonl"))
                paths = [root / "thesis/results" / area / source / model / name]
                if stage == "enhanced":
                    paths += sorted((root / "thesis/results/intermediate").glob(source + "__*/" + model + "/" + name))
            for path in paths:
                native_run = path.parents[1].name
                for row in records(path):
                    if row.get("run_id") != native_run or row.get("model_id", (row.get("model") or {}).get("id")) != model:
                        raise RecoveryRefused("native composite source identity mismatch")
                    key = (native_run, model, row.get("sample_id"), json.dumps(row.get("spec"), sort_keys=True))
                    # Repair transport attempts may repeat the same sample;
                    # preserve them rather than silently choosing 'latest'.
                    if stage != "repair" and key in seen:
                        raise RecoveryRefused("duplicate composite result ownership")
                    seen.add(key)
                    result.append(dict(source_run=native_run, stage=stage,
                                       source_artifact=path.relative_to(root).as_posix(), record=row))
    return result
