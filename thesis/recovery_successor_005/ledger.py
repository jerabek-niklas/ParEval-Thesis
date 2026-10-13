"""Presence semantics of phase 2, shared by planner, measurement modules and
verifier (one definition of "present" and "missing").

PRESENT means: a result exists for the (sample[, tool][, spec]) - whatever
its state. A stored TIMEOUT / TOOL_ERROR / PARTIAL / NOT_ANALYZED entry, a
build_failed / timeout / crash correctness record, a gated enhanced row
(baseline_incompatible, numerically_unstable) are measurements and are
never re-measured.

Sources of a target's evidence:
  static       the target's own historical static_analysis.jsonl record,
               the 002/003 supplement ledgers (recovery_001 iteration 1),
               and the phase-2 supplement ledgers static.<tool>.jsonl
  correctness  historical correctness.jsonl OR phase-2 correctness.jsonl
  dynamic      historical dynamic_analysis.jsonl OR phase-2 dynamic_analysis.jsonl
  enhanced     phase-2 enhanced_tests.jsonl only
A phase-2 row for something the history already holds is an integrity
error (never a silent duplicate).

Read-only; never archives or repairs a ledger (the writers do that under
the writer lock). Python 3.8 compatible: the enhanced helpers import the
main-container modules lazily.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt

PROVENANCE_FIELDS = ("writer_run_id", "authority_run_id", "candidate_source_run",
                     "candidate_source_sha256", "candidate_source_path", "variant", "iteration")


class TornLedger(RecoveryRefused):
    """A phase-2 ledger ends in an unterminated line (interrupted append)."""


def ledger_rows(root, model, source_run, name):
    """Rows of one phase-2 ledger; a torn tail raises TornLedger (the writer
    archives it under the lock before resuming)."""
    relative = pt.ledger_relative(model, source_run, name)
    path = checked_path(Path(root), relative)
    if not path.is_file():
        return []
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise TornLedger("torn phase-2 ledger tail: " + relative)
    rows = []
    try:
        for line in data.decode("utf-8").split("\n"):
            if line.strip():
                rows.append(json.loads(line, object_pairs_hook=OrderedDict))
    except ValueError as error:
        raise RecoveryRefused("undecodable phase-2 ledger line in %s: %s" % (relative, error))
    return rows


def check_provenance(target, row, label):
    expected = pt.provenance(target, row.get("sample_id"))
    for field in PROVENANCE_FIELDS:
        if row.get(field) != expected[field]:
            raise RecoveryRefused("%s row of %s carries a foreign %s" % (label, target.target_id, field))
    return True


# -- tool settings ---------------------------------------------------------------

def static_settings(config):
    """Enabled static tools (name -> ToolSettings), config order."""
    from thesis.evaluation.tool_config import resolve_tool_settings

    return OrderedDict((name, s) for name, s in resolve_tool_settings(config, "static_analysis").items()
                       if s.enabled)


def dynamic_settings(config):
    from thesis.evaluation.tool_config import resolve_tool_settings

    return OrderedDict((name, s) for name, s in resolve_tool_settings(config, "dynamic_analysis").items()
                       if s.enabled)


# -- static ---------------------------------------------------------------------

def phase2_static(root, target, tool):
    """sample_id -> phase-2 supplement row of one tool (validated)."""
    from thesis.evaluation import successor_supplement as ss

    rows = ledger_rows(root, target.model_id, target.source_run, "static.%s.jsonl" % tool)
    expected = OrderedDict((sid, f["execution_model"]) for sid, f in target.samples.items())
    indexed = ss.index_rows(rows, successor_run=pl.SUCCESSOR, predecessor_target=target.source_run,
                            model=target.model_id, tool=tool, expected=expected)
    for sample_id, row in indexed.items():
        if (row.get("candidate_source_sha256") != target.samples[sample_id]["source_sha256"]
                or row.get("authority_run_id") != pl.SUCCESSOR
                or row.get("variant") != target.variant or row.get("iteration") != target.iteration):
            raise RecoveryRefused("phase-2 static row bound to another candidate: %s/%s" % (tool, sample_id))
    return indexed


def merged_static(root, config, target):
    """sample_id -> merged static record (history + 002/003 + phase-2).
    A phase-2 entry for a tool the history already carries refuses."""
    from thesis.evaluation import successor_supplement as ss

    historical = pt.historical_static(root, target)
    supplements = OrderedDict()
    for tool in static_settings(config):
        rows = phase2_static(root, target, tool)
        if rows:
            supplements[tool] = OrderedDict((sid, row["entry"]) for sid, row in rows.items())
    stray = [sid for entries in supplements.values() for sid in entries if sid not in historical]
    if stray:
        raise RecoveryRefused("phase-2 static rows without a historical record: %s" % stray[:3])
    return ss.merge_static_records(historical, supplements)


def missing_static(root, config, target):
    """sample_id -> [enabled static tools without an entry] (config order).
    A tool counts as present whatever its state; an inapplicable tool still
    needs its native NOT_APPLICABLE entry."""
    merged = merged_static(root, config, target)
    tools = list(static_settings(config))
    missing = OrderedDict()
    for sample_id in target.samples:
        record = merged.get(sample_id)
        if record is None:
            raise RecoveryRefused("no static record for candidate %s" % sample_id)
        absent = [tool for tool in tools if tool not in (record.get("tools") or {})]
        if absent:
            missing[sample_id] = absent
    return missing


# -- correctness / dynamic ----------------------------------------------------------

def phase2_records(root, target, file_name):
    rows = ledger_rows(root, target.model_id, target.source_run, file_name)
    records = OrderedDict()
    for row in rows:
        sample_id = row.get("sample_id")
        if (sample_id not in target.samples or row.get("model_id") != target.model_id
                or row.get("run_id") != target.source_run):
            raise RecoveryRefused("foreign phase-2 %s row in %s" % (file_name, target.target_id))
        if sample_id in records:
            raise RecoveryRefused("duplicate phase-2 %s row for %s" % (file_name, sample_id))
        check_provenance(target, row, file_name)
        records[sample_id] = row
    return records


def present_records(root, target, file_name):
    """sample_id -> (owner, record) for correctness/dynamic."""
    historical = pt.historical_records(root, target, file_name)
    phase2 = phase2_records(root, target, file_name)
    overlap = sorted(set(historical) & set(phase2))
    if overlap:
        raise RecoveryRefused("phase-2 %s duplicates a historical record: %s" % (file_name, overlap[:3]))
    present = OrderedDict()
    for sample_id in target.samples:
        if sample_id in historical:
            present[sample_id] = (target.source_run, historical[sample_id])
        elif sample_id in phase2:
            present[sample_id] = (pl.SUCCESSOR, phase2[sample_id])
    return present


def missing_records(root, target, file_name):
    present = present_records(root, target, file_name)
    return [sample_id for sample_id in target.samples if sample_id not in present]


# -- enhanced -------------------------------------------------------------------------

def frozen_specs_path(root):
    return Path(root).resolve() / "thesis/enhanced_tests/frozen/e3_final_specs.jsonl"


def load_frozen_specs(root):
    from thesis.evaluation import run_enhanced_tests as ret

    return ret.load_llm_specs(frozen_specs_path(root))


def enhanced_scope(config):
    from thesis.enhanced_tests.specs import stage_settings

    settings = stage_settings(config)
    return list(settings["execution_models"])


def parameterizable(root, benchmark):
    cpu = Path(root).resolve() / "drivers/cpp/benchmarks" / benchmark / "cpu.cc"
    return cpu.is_file() and "ENHANCED_TEST_SIZE_DEFAULT" in cpu.read_text(encoding="utf-8")


def key_text(key):
    """A spec_key tuple as canonical JSON text (stable across processes)."""
    return json.dumps(key, sort_keys=True, separators=(",", ":"), default=list)


def expected_enhanced(root, config, target, llm_specs=None, cache=None):
    """sample_id -> OrderedDict(key_text -> spec) of the expected enhanced
    specs (build_benchmark_specs over the frozen spec artifact)."""
    from thesis.enhanced_tests.specs import build_benchmark_specs, spec_key

    llm_specs = llm_specs if llm_specs is not None else load_frozen_specs(root)
    cache = cache if cache is not None else {}
    scope = enhanced_scope(config)
    expected = OrderedDict()
    for sample_id, facts in target.samples.items():
        if facts["execution_model"] not in scope or not parameterizable(root, facts["benchmark"]):
            continue
        benchmark = facts["benchmark"]
        if benchmark not in cache:
            cache[benchmark] = build_benchmark_specs(benchmark, llm_specs.get(benchmark, []), config)
        expected[sample_id] = OrderedDict((key_text(spec_key(spec)), spec) for spec in cache[benchmark])
    return expected


def phase2_enhanced(root, target):
    """sample_id -> {key_text: row} of the phase-2 enhanced ledger."""
    from thesis.enhanced_tests.specs import spec_key

    rows = ledger_rows(root, target.model_id, target.source_run, pt.ENHANCED_FILE)
    present = OrderedDict()
    for row in rows:
        sample_id = row.get("sample_id")
        if (sample_id not in target.samples or row.get("model_id") != target.model_id
                or row.get("run_id") != target.source_run):
            raise RecoveryRefused("foreign enhanced row in " + target.target_id)
        check_provenance(target, row, "enhanced")
        key = key_text(spec_key(row["spec"]))
        bucket = present.setdefault(sample_id, OrderedDict())
        if key in bucket:
            raise RecoveryRefused("duplicate enhanced (sample, spec) row for %s" % sample_id)
        bucket[key] = row
    return present


def missing_enhanced(root, config, target, llm_specs=None, cache=None):
    """sample_id -> [pending specs] (expected minus present)."""
    expected = expected_enhanced(root, config, target, llm_specs, cache)
    present = phase2_enhanced(root, target)
    unexpected = [(sid, key) for sid, keys in present.items() for key in keys
                  if key not in expected.get(sid, {})]
    if unexpected:
        raise RecoveryRefused("unexpected enhanced rows in %s: %s" % (target.target_id, unexpected[:2]))
    missing = OrderedDict()
    for sample_id, specs in expected.items():
        pending = [spec for key, spec in specs.items() if key not in present.get(sample_id, {})]
        if pending:
            missing[sample_id] = pending
    return missing
