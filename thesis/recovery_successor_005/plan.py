"""Missing-only work plan of phase 2 (read-only).

Per target and stage the exact work that is still open, computed from the
frozen target table, the historical evidence and the phase-2 ledgers with
the presence semantics of ledger.py:

  static.main / static.parcoach / static.llov   test_feedback targets: one
      supplement row per (sample, tool) missing from the merged record
      (applicable -> measured, inapplicable -> native NOT_APPLICABLE entry)
  correctness / dynamic                         static_feedback targets: one
      record per sample without a historical or phase-2 record
  enhanced                                      every target: the expected
      (sample, spec) pairs without a phase-2 row

Every other (target, stage) must already be complete: a gap there is an
integrity finding (reported, never scheduled - phase 2 measures only what
the frozen design assigns to it).

    python3 -B -m thesis.recovery_successor_005.plan [--target-table PATH]

Python 3.8 compatible (enhanced counts need the main container).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.recovery_successor_005 import ledger as pg  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.recovery_successor_005 import targets as pt  # noqa: E402

MAIN_STATIC_STAGE = "static.main"
STATIC_STAGES = ("static.main", "static.parcoach", "static.llov")


def static_stage_of(tool):
    return "static.%s" % tool if tool in pl.EXTERNAL_TOOLS else MAIN_STATIC_STAGE


def assigned_stages(target):
    """The stages the frozen design assigns to a target in phase 2."""
    stages = ["enhanced"]
    if target.variant == "test_feedback":
        stages = list(STATIC_STAGES) + stages
    if target.variant == "static_feedback":
        stages = ["correctness", "dynamic"] + stages
    return stages


def target_plan(root, config, target, llm_specs=None, spec_cache=None, with_enhanced=True):
    """OrderedDict stage -> {items, samples, detail} of one target, plus the
    integrity findings for stages NOT assigned to it."""
    result = OrderedDict()
    findings = []
    assigned = assigned_stages(target)
    missing_static = pg.missing_static(root, config, target)
    settings = pg.static_settings(config)
    per_stage = OrderedDict((stage, OrderedDict()) for stage in STATIC_STAGES)
    for sample_id, tools in missing_static.items():
        for tool in tools:
            per_stage[static_stage_of(tool)].setdefault(sample_id, []).append(tool)
    for stage, samples in per_stage.items():
        applicable = Counter()
        for sample_id, tools in samples.items():
            for tool in tools:
                if settings[tool].applies_to(target.samples[sample_id]["execution_model"]):
                    applicable[tool] += 1
        entry = OrderedDict([("samples", len(samples)),
                             ("items", sum(len(t) for t in samples.values())),
                             ("applicable", OrderedDict(sorted(applicable.items()))),
                             ("work", samples)])
        if stage in assigned:
            result[stage] = entry
        elif samples:
            findings.append("%s: %s has %d sample(s) with missing static tools outside the phase-2 "
                            "assignment" % (target.target_id, stage, len(samples)))
    for stage, file_name in (("correctness", pt.CORRECTNESS_FILE), ("dynamic", pt.DYNAMIC_FILE)):
        missing = pg.missing_records(root, target, file_name)
        entry = OrderedDict([("samples", len(missing)), ("items", len(missing)), ("work", missing)])
        if stage in assigned:
            result[stage] = entry
        elif missing:
            findings.append("%s: %s missing for %d sample(s) outside the phase-2 assignment"
                            % (target.target_id, stage, len(missing)))
    if with_enhanced:
        missing = pg.missing_enhanced(root, config, target, llm_specs, spec_cache)
        expected = pg.expected_enhanced(root, config, target, llm_specs, spec_cache)
        result["enhanced"] = OrderedDict([
            ("samples", len(missing)), ("items", sum(len(v) for v in missing.values())),
            ("expected_samples", len(expected)),
            ("expected_pairs", sum(len(v) for v in expected.values())),
            ("work", missing)])
    return result, findings


def plan(root, config, table, models=None, with_enhanced=True, log=None, strict=True):
    """The full plan: per target and totals per stage. strict=False (status
    views only) reports a target whose ledgers are torn instead of raising;
    the productive path and the preflight are strict."""
    llm_specs = pg.load_frozen_specs(root) if with_enhanced else None
    spec_cache = {}
    targets = OrderedDict()
    totals = OrderedDict()
    findings = []
    for target in table.targets:
        if models and target.model_id not in models:
            continue
        try:
            stages, target_findings = target_plan(root, config, target, llm_specs, spec_cache, with_enhanced)
        except pg.TornLedger as torn:
            if strict:
                raise
            findings.append("%s: %s (archived by the next productive invocation)" % (target.target_id, torn))
            continue
        findings.extend(target_findings)
        targets[target.target_id] = stages
        for stage, entry in stages.items():
            bucket = totals.setdefault(stage, Counter())
            bucket["targets_open"] += 1 if entry["items"] else 0
            bucket["samples"] += entry["samples"]
            bucket["items"] += entry["items"]
            for tool, count in (entry.get("applicable") or {}).items():
                bucket["applicable." + tool] += count
            if "expected_pairs" in entry:
                bucket["expected_samples"] += entry["expected_samples"]
                bucket["expected_pairs"] += entry["expected_pairs"]
        if log:
            log("planned %s" % target.target_id)
    return OrderedDict([("targets", targets),
                        ("totals", OrderedDict((s, OrderedDict(sorted(c.items()))) for s, c in totals.items())),
                        ("integrity_findings", findings)])


def summary(result):
    """The plan without the per-sample work lists."""
    compact = OrderedDict()
    for target_id, stages in result["targets"].items():
        compact[target_id] = OrderedDict((stage, OrderedDict((k, v) for k, v in entry.items() if k != "work"))
                                         for stage, entry in stages.items())
    return OrderedDict([("totals", result["totals"]), ("integrity_findings", result["integrity_findings"]),
                        ("targets", compact)])


def main(argv=None):
    import argparse

    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description="phase-2 missing-only plan (read-only)")
    parser.add_argument("--config", default=pl.CONFIG_REL)
    parser.add_argument("--build-table", action="store_true",
                        help="derive the target table from the repository instead of the frozen one")
    parser.add_argument("--no-enhanced", action="store_true")
    parser.add_argument("--totals-only", action="store_true")
    args = parser.parse_args(argv)
    pl.isolate_providers()
    config = load_config((REPO_ROOT / args.config).resolve())
    pl.scrub_provider_environment(config)
    if args.build_table:
        table = pt.TargetTable(REPO_ROOT, pt.build_table(REPO_ROOT))
    else:
        table = pt.load_table(REPO_ROOT)
    result = plan(REPO_ROOT, config, table, with_enhanced=not args.no_enhanced)
    out = summary(result)
    if args.totals_only:
        out = OrderedDict([("totals", out["totals"]), ("integrity_findings", out["integrity_findings"])])
    sys.stdout.write(json.dumps(out, indent=1) + "\n")
    return 1 if result["integrity_findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
