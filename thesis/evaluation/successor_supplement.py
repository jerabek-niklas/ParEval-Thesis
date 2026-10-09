"""Successor-owned static-tool supplements for PREDECESSOR iteration targets.

A missing external tool entry (LLOV) of a predecessor iteration record is
measured by the successor and persisted in a successor-owned ledger, never
merged into the predecessor static_analysis.jsonl. Consumers read a MERGED
VIEW: the verified predecessor record plus the supplement entry, appended in
the same position the native merge (run_static_analysis.run_model) would have
used, with the record-level derived fields recomputed by the native helpers.

The per-sample entry is produced by exactly the steps of run_model
(tool_execution_condition -> fingerprint -> tool.run -> mark_low_confidence
-> to_dict + num_low_confidence + fingerprint + condition; NOT_APPLICABLE for
out-of-scope samples), see test_successor_infrastructure for the
byte-equivalence test against run_model itself.

Python 3.8 compatible (runs inside pareval-llov).
"""
from __future__ import annotations

import copy
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation.recovery_lineage import RecoveryRefused

SUPPLEMENT_SCHEMA = "successor_static_supplement.v1"


def supplement_relative(successor_run, model, predecessor_target, tool):
    for value in (successor_run, model, predecessor_target, tool):
        if not value or "/" in value or "\\" in value or value.startswith("."):
            raise RecoveryRefused("invalid supplement identity")
    return "thesis/results/intermediate/%s/%s/supplements/%s/static.%s.jsonl" % (
        successor_run, model, predecessor_target, tool)


def assembled_samples(repo_root, assembly_rows, run_id, model_id):
    """framework.iter_assembled_samples over VERIFIED rows (no file re-open)."""
    from thesis.evaluation import framework

    samples = []
    for entry in assembly_rows:
        if not entry.get("assembled"):
            continue
        drivers = entry.get("drivers", {})
        sample_id = entry["sample_id"]
        parts = sample_id.split("__")
        execution_model = parts[-2] if len(parts) >= 2 else "serial"
        name = parts[-3] if len(parts) >= 3 else "unknown"
        problem_type = parts[-4] if len(parts) >= 4 else "unknown"
        source_path = Path(entry["source_path"].replace("\\", "/"))
        if not source_path.is_absolute():
            source_path = Path(repo_root) / source_path
        benchmark_dir_raw = drivers.get("benchmark_dir", "").replace("\\", "/")
        samples.append(framework.AssembledSample(
            sample_id=sample_id, model_id=model_id, run_id=run_id,
            execution_model=execution_model, problem_type=problem_type, name=name,
            source_path=source_path, benchmark_dir=Path(repo_root) / benchmark_dir_raw,
            model_driver_file=drivers.get("model_driver", ""), assembly_entry=entry))
    return samples


def measure_entry(tool, settings, sample, context, source_sha256):
    """One tool entry exactly as run_static_analysis.run_model builds it."""
    from thesis.evaluation import run_static_analysis as rsa
    from thesis.evaluation import static_provenance as provenance
    from thesis.evaluation.tool_config import mark_low_confidence

    if not settings.applies_to(sample.execution_model):
        return rsa.not_applicable_entry(tool.name, sample.execution_model)
    condition = provenance.tool_execution_condition(
        tool, settings, sample.execution_model, context.primary_compiler, source_sha256)
    fingerprint = provenance.tool_execution_fingerprint_sha256(condition)
    result = tool.run(sample, context)
    num_low_confidence = mark_low_confidence(result.findings, settings)
    entry = result.to_dict()
    entry["num_low_confidence"] = num_low_confidence
    entry["tool_execution_fingerprint_sha256"] = fingerprint
    entry["tool_execution_condition"] = condition
    return entry


def validate_entry(entry, tool, execution_model, settings, source_sha256, current_implementation=None):
    """Structural + fingerprint validation of one supplement entry."""
    from thesis.evaluation.condition_hashing import canonical_sha256
    from thesis.evaluation.framework import STATE_NOT_APPLICABLE

    if not isinstance(entry, dict) or entry.get("tool") != tool:
        raise RecoveryRefused("supplement entry belongs to another tool")
    applicable = settings.applies_to(execution_model)
    if not applicable:
        if entry.get("analysis_state") != STATE_NOT_APPLICABLE or entry.get("ran") is not False:
            raise RecoveryRefused("out-of-scope supplement entry is not NOT_APPLICABLE")
        if "tool_execution_condition" in entry:
            raise RecoveryRefused("NOT_APPLICABLE entry carries an execution condition")
        return True
    condition = entry.get("tool_execution_condition")
    if not isinstance(condition, dict):
        raise RecoveryRefused("applicable supplement entry lacks its execution condition")
    if entry.get("tool_execution_fingerprint_sha256") != canonical_sha256(condition):
        raise RecoveryRefused("supplement fingerprint does not reproduce")
    if condition.get("tool") != tool or condition.get("sample_source_sha256") != source_sha256:
        raise RecoveryRefused("supplement condition is bound to another tool or source")
    build = condition.get("build") or {}
    if build.get("execution_model") != execution_model:
        raise RecoveryRefused("supplement condition is bound to another execution model")
    if current_implementation is not None:
        for key in ("implementation_sha256", "shared_modules_sha256"):
            if condition.get(key) != current_implementation.get(key):
                raise RecoveryRefused("supplement was produced by another tool implementation (%s)" % key)
    return True


def index_rows(rows, *, successor_run, predecessor_target, model, tool, expected):
    """sample_id -> row for one supplement ledger; duplicates/foreign rows refuse.

    `expected` maps every assembled predecessor sample to its execution model."""
    indexed = OrderedDict()
    for row in rows:
        sample = row.get("sample_id")
        if (row.get("schema_version") != SUPPLEMENT_SCHEMA or row.get("run_id") != successor_run
                or row.get("candidate_source_run") != predecessor_target
                or row.get("model_id") != model or row.get("tool") != tool
                or sample not in expected or sample in indexed
                or row.get("execution_model") != expected[sample]):
            raise RecoveryRefused("foreign or duplicate supplement row for %s/%s/%s"
                                  % (predecessor_target, model, tool))
        indexed[sample] = row
    return indexed


def merge_static_records(predecessor_records, supplements):
    """Merged view: deep copies of the predecessor records with each
    supplement entry appended (supplements: ordered {tool: {sample: entry}}).

    A tool already present in the predecessor record refuses: a stored
    predecessor entry (including TIMEOUT/TOOL_ERROR) is never replaced."""
    from thesis.evaluation import run_static_analysis as rsa

    merged = OrderedDict()
    for sample_id, record in predecessor_records.items():
        view = copy.deepcopy(record)
        tools = view.setdefault("tools", {})
        changed = False
        for tool, entries in supplements.items():
            if sample_id not in entries:
                continue
            if tool in tools:
                raise RecoveryRefused("predecessor already carries %s for %s; supplements never "
                                      "replace stored entries" % (tool, sample_id))
            tools[tool] = copy.deepcopy(entries[sample_id])
            changed = True
        if changed:
            view["has_blocking_findings"] = rsa.record_has_blocking(view)
            view["low_confidence_count"] = rsa.record_low_confidence_count(view)
            view["analysis_gaps"] = rsa.record_analysis_gaps(view)
        merged[sample_id] = view
    for tool, entries in supplements.items():
        stray = set(entries) - set(predecessor_records)
        if stray:
            raise RecoveryRefused("supplement %s carries samples without a predecessor record" % tool)
    return merged
