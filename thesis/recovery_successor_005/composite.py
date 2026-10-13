"""Unified reader of the full-extension study after phase 2 (read-only).

One merged view for the analysis over all 11 models and both blocks:

  pilot     pilot_002 (its base cells) and pilot_002__<variant>__iter<N> (its
            own repair candidates); complete, read in place, owner pilot_002
  full_ext  the frozen phase-2 target table: the iteration-0 base cells
            (owner full_ext_001) and every repair candidate of
            full_ext_recovery_001..004 (owner = the iteration run holding it)

Per cell and stage the evidence comes from exactly ONE place, with the
presence semantics of the planner (ledger.py): the record of the cell's own
run, the 002/003 static supplements, or the phase-2 ledgers of
full_ext_phase2_001. Every cell names that owner, so an analysis can always
say which run measured what. Nothing is copied or relabelled; an integrity
problem (duplicate, foreign or torn evidence) refuses instead of yielding a
partial view. Missing evidence is yielded as None - completeness is the
verifier's verdict (verify.py), not the reader's.

composite_document() fingerprints that view as 'phase2_composite.v1': the
unchanged 1,980-cell base population (composite_study.read_base_cells over
full_001_composite.json), the derived lineages (recovery_001..004 and phase
2, none of which owns a base cell), candidate counts and stage coverage. The
frozen composite documents (full_001_composite.json, recovery_001
composite_v2.json) are only read. Main container only.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt

SCHEMA = "phase2_composite.v1"
PILOT_BLOCK = "pilot"
FULL_BLOCK = "full_ext"
BLOCKS = (PILOT_BLOCK, FULL_BLOCK)
STAGES = ("static", "correctness", "dynamic", "enhanced")
COMPOSITE_STUDY_REL = "thesis/evaluation/full_001_composite.json"
POPULATION_CELLS = 1980
EXPECTED_POPULATION = OrderedDict([(pl.PILOT, 396), (pl.PARENT, 1584)])
DERIVED_RUNS = pl.OWNERS + (pl.SUCCESSOR,)
DOCUMENT_REL = pl.RESULTS_REL + "/phase2_composite.json"


def counts(counter):
    """A Counter as a key-sorted OrderedDict (stable JSON, stable hashes)."""
    return OrderedDict(sorted((str(key), value) for key, value in counter.items()))


# -- pilot block (complete, read in place) ----------------------------------------

def pilot_runs(root, model):
    """(run, variant, iteration) of one model's pilot block: the base run
    always (a missing base assembly refuses later), every pilot repair
    iteration run that holds an assembly for the model."""
    runs = [(pl.PILOT, None, 0)]
    for variant in pl.VARIANTS:
        for iteration in range(1, pl.MAX_ITERATIONS + 1):
            run = pt.iteration_run(pl.PILOT, variant, iteration)
            if (Path(root) / pt.run_dir(run, model) / "assembly.jsonl").is_file():
                runs.append((run, variant, iteration))
    return runs


def pilot_target(root, model, run, variant, iteration):
    """A targets.Target over one pilot assembly (verified rows only, every
    source re-hashed), so the pilot is read with the same presence and
    expected-spec logic as the full extension."""
    samples, assembly = pt._samples(root, run, model)
    return pt.Target(OrderedDict([
        ("target_id", "%s/%s" % (model, run)), ("model_id", model), ("block", PILOT_BLOCK),
        ("variant", variant), ("iteration", iteration), ("source_run", run),
        ("loop_owner", pl.PILOT), ("loop_kind", "pilot"), ("assembly", assembly),
        ("sample_count", len(samples)), ("samples", list(samples.values()))]))


def pilot_targets(root, model):
    return [pilot_target(root, model, run, variant, iteration)
            for run, variant, iteration in pilot_runs(root, model)]


def pilot_enhanced_rows(root, target):
    return pt.read_jsonl(root, pt.run_dir(target.source_run, target.model_id) + "/" + pt.ENHANCED_FILE)


def enhanced_by_sample(target, rows):
    """sample_id -> {key_text: row} of a historical (pilot) enhanced file;
    foreign or duplicate rows refuse (the phase-2 ledgers are read with
    ledger.phase2_enhanced, which also checks the candidate provenance)."""
    from thesis.enhanced_tests.specs import spec_key

    present = OrderedDict()
    for row in rows:
        sample_id = row.get("sample_id")
        if (sample_id not in target.samples or row.get("model_id") != target.model_id
                or row.get("run_id") != target.source_run):
            raise RecoveryRefused("foreign enhanced row in " + target.target_id)
        key = pg.key_text(spec_key(row["spec"]))
        bucket = present.setdefault(sample_id, OrderedDict())
        if key in bucket:
            raise RecoveryRefused("duplicate enhanced (sample, spec) row for %s" % sample_id)
        bucket[key] = row
    return present


# -- full_ext block (table + history + phase-2 ledgers) ---------------------------

def static_owners(root, config, target):
    """sample_id -> {tool: owner run} for the merged static view: the target's
    own record, the 002/003 supplements, the phase-2 supplements. Overlaps are
    refused by ledger.merged_static, which callers run first."""
    from thesis.evaluation import successor_supplement as ss

    owners = OrderedDict()
    for sample_id, record in pt.historical_records(root, target, pt.STATIC_FILE).items():
        owners[sample_id] = OrderedDict((tool, target.source_run) for tool in (record.get("tools") or {}))
    expected = OrderedDict((sid, facts["execution_model"]) for sid, facts in target.samples.items())
    for owner in pt.SUPPLEMENT_OWNERS:
        for tool in pl.EXTERNAL_TOOLS:
            rows = pt.read_jsonl(root, ss.supplement_relative(owner, target.model_id, target.source_run, tool))
            if not rows:
                continue
            indexed = ss.index_rows(rows, successor_run=owner, predecessor_target=target.source_run,
                                    model=target.model_id, tool=tool, expected=expected)
            for sample_id in indexed:
                owners.setdefault(sample_id, OrderedDict())[tool] = owner
    for tool in pg.static_settings(config):
        for sample_id in pg.phase2_static(root, target, tool):
            owners.setdefault(sample_id, OrderedDict())[tool] = pl.SUCCESSOR
    return owners


# -- compact stage summaries -----------------------------------------------------

def static_summary(record, owner, tool_owners=None):
    from thesis.evaluation import framework

    if record is None:
        return None
    tools = record.get("tools") or {}
    return OrderedDict([
        ("owner", owner),
        ("tools", OrderedDict((tool, framework.analysis_state_of(entry)) for tool, entry in tools.items())),
        ("supplemented", OrderedDict((tool, by) for tool, by in (tool_owners or {}).items() if by != owner)),
    ])


def correctness_summary(owner, record):
    if record is None:
        return None
    return OrderedDict([("owner", owner), ("verdict", record.get("verdict"))])


def dynamic_summary(owner, record):
    if record is None:
        return None
    tools = record.get("tools") or {}
    return OrderedDict([("owner", owner), ("tools", OrderedDict(
        (tool, OrderedDict([("analysis_state", (entry or {}).get("analysis_state")),
                            ("ran", (entry or {}).get("ran"))])) for tool, entry in tools.items()))])


def enhanced_summary(owner, bucket):
    if not bucket:
        return None
    return OrderedDict([("owner", owner), ("pairs", len(bucket)),
                        ("statuses", counts(Counter(row.get("status") for row in bucket.values())))])


def _cell(block, target, facts, owner, static, correctness, dynamic, enhanced):
    return OrderedDict([
        ("block", block), ("model_id", target.model_id), ("variant", target.variant),
        ("iteration", target.iteration), ("sample_id", facts["sample_id"]),
        ("execution_model", facts["execution_model"]), ("benchmark", facts["benchmark"]),
        ("source_run", target.source_run), ("owner", owner),
        ("source_sha256", facts["source_sha256"]), ("source_path", facts["source_path"]),
        ("static", static), ("correctness", correctness), ("dynamic", dynamic), ("enhanced", enhanced)])


def pilot_cells(root, config, model):
    """The pilot block of one model (every stage owned by pilot_002)."""
    for target in pilot_targets(root, model):
        static = pt.historical_records(root, target, pt.STATIC_FILE)
        correctness = pt.historical_records(root, target, pt.CORRECTNESS_FILE)
        dynamic = pt.historical_records(root, target, pt.DYNAMIC_FILE)
        enhanced = enhanced_by_sample(target, pilot_enhanced_rows(root, target))
        for sample_id, facts in target.samples.items():
            yield _cell(PILOT_BLOCK, target, facts, pl.PILOT,
                        static_summary(static.get(sample_id), pl.PILOT),
                        correctness_summary(pl.PILOT, correctness.get(sample_id)),
                        dynamic_summary(pl.PILOT, dynamic.get(sample_id)),
                        enhanced_summary(pl.PILOT, enhanced.get(sample_id)))


def full_ext_cells(root, config, target):
    """One full_ext target (base cells or repair candidates)."""
    owner = target.source_run
    merged = pg.merged_static(root, config, target)
    owners = static_owners(root, config, target)
    correctness = pg.present_records(root, target, pt.CORRECTNESS_FILE)
    dynamic = pg.present_records(root, target, pt.DYNAMIC_FILE)
    enhanced = pg.phase2_enhanced(root, target)
    for sample_id, facts in target.samples.items():
        c_owner, c_record = correctness.get(sample_id, (None, None))
        d_owner, d_record = dynamic.get(sample_id, (None, None))
        yield _cell(FULL_BLOCK, target, facts, owner,
                    static_summary(merged.get(sample_id), owner, owners.get(sample_id)),
                    correctness_summary(c_owner, c_record),
                    dynamic_summary(d_owner, d_record),
                    enhanced_summary(pl.SUCCESSOR, enhanced.get(sample_id)))


def iter_cells(root, config, table, models=None):
    """One OrderedDict per (block, model, variant, iteration, sample): the
    pilot block (MODELS order, base run first) then the full_ext block (frozen
    table order)."""
    root = Path(root).resolve()
    models = list(models) if models else list(pl.MODELS)
    unknown = [m for m in models if m not in pl.MODELS]
    if unknown:
        raise RecoveryRefused("not a phase-2 model: %s" % unknown)
    for model in models:
        for cell in pilot_cells(root, config, model):
            yield cell
    for target in table.targets:
        if target.model_id in models:
            for cell in full_ext_cells(root, config, target):
                yield cell


# -- population and derived lineages ------------------------------------------------

def population_counts(root):
    """The methodical base population, read in place by
    composite_study.read_base_cells over the frozen composite study."""
    from thesis.evaluation import composite_study

    root = Path(root).resolve()
    data = checked_path(root, COMPOSITE_STUDY_REL).read_bytes()
    study = json.loads(data.decode("utf-8"))
    rows = composite_study.read_base_cells(study, root)
    per_run = Counter(row["source_run"] for row in rows)
    return OrderedDict([
        ("source", COMPOSITE_STUDY_REL),
        ("source_raw_sha256", hashlib.sha256(data).hexdigest()),
        ("study_manifest_sha256", study.get("manifest_sha256")),
        ("base_cells", len(rows)),
        ("per_run", OrderedDict((run, per_run.get(run, 0)) for run in sorted(per_run))),
    ])


def check_population(population):
    """1,980 = 396 pilot + 1,584 full-extension base cells, nothing else."""
    if (population.get("base_cells") != POPULATION_CELLS
            or dict(population.get("per_run") or {}) != dict(EXPECTED_POPULATION)):
        raise RecoveryRefused("base population is %s (%s), not 1,980 = 396 + 1,584"
                              % (population.get("base_cells"), dict(population.get("per_run") or {})))
    return population


def _base_generation_rows(root, run):
    """Base-cell generation rows a derived run would own (raw/<run>/<model>)."""
    directory = Path(root) / pt.RAW_REL / run
    total = 0
    if directory.is_dir():
        for path in sorted(directory.glob("*/generations.jsonl")):
            total += len(pt.read_jsonl(root, path.relative_to(Path(root)).as_posix()))
    return total


def derived_lineages(root):
    """recovery_001..004 and phase 2: frozen contract (self-hash reproduced)
    and measured base cells (0 - they own candidates and measurements, never a
    base cell). The phase-2 contract is None until it is frozen."""
    from thesis.evaluation import pilot_run_contract as prc

    root = Path(root).resolve()
    result = []
    for run in DERIVED_RUNS:
        relative = "thesis/evaluation/recovery/%s/contract.json" % run
        path = checked_path(root, relative)
        entry = OrderedDict([("run_id", run),
                             ("role", "phase2_measurements" if run == pl.SUCCESSOR else "repair_candidates"),
                             ("base_cells", _base_generation_rows(root, run)), ("contract_path", relative)])
        if entry["base_cells"]:
            raise RecoveryRefused("derived lineage %s owns %d base cell(s)" % (run, entry["base_cells"]))
        if path.is_file():
            data = path.read_bytes()
            contract = json.loads(data.decode("utf-8"), object_pairs_hook=OrderedDict)
            if contract.get("run_id") != run or prc.contract_sha256(contract) != contract.get("contract_sha256"):
                raise RecoveryRefused("frozen contract of %s does not reproduce its hash" % run)
            entry["contract_sha256"] = contract["contract_sha256"]
            entry["contract_raw_sha256"] = hashlib.sha256(data).hexdigest()
        elif run == pl.SUCCESSOR:
            entry["contract_sha256"] = None
            entry["contract_raw_sha256"] = None
        else:
            raise RecoveryRefused("missing frozen contract of " + run)
        result.append(entry)
    return result


# -- document ---------------------------------------------------------------------------

def _coverage(cells):
    """Per block and stage: cells with evidence, evidence owners, plus the
    enhanced pair/status totals."""
    coverage = OrderedDict()
    for block in BLOCKS:
        stages = OrderedDict()
        for stage in STAGES:
            stages[stage] = OrderedDict([("cells", 0), ("with_evidence", 0), ("owners", Counter())])
        stages["static"]["supplemented_by"] = Counter()
        stages["enhanced"]["pairs"] = 0
        stages["enhanced"]["statuses"] = Counter()
        coverage[block] = stages
    for cell in cells:
        stages = coverage[cell["block"]]
        for stage in STAGES:
            entry = stages[stage]
            entry["cells"] += 1
            evidence = cell[stage]
            if evidence is None:
                continue
            entry["with_evidence"] += 1
            entry["owners"][evidence["owner"]] += 1
        if cell["static"] is not None:
            for by in cell["static"]["supplemented"].values():
                stages["static"]["supplemented_by"][by] += 1
        if cell["enhanced"] is not None:
            stages["enhanced"]["pairs"] += cell["enhanced"]["pairs"]
            stages["enhanced"]["statuses"].update(cell["enhanced"]["statuses"])
    for stages in coverage.values():
        for entry in stages.values():
            for key, value in list(entry.items()):
                if isinstance(value, Counter):
                    entry[key] = counts(value)
    return coverage


def _cell_counts(cells):
    totals = Counter()
    base = Counter()
    candidates = OrderedDict((block, OrderedDict()) for block in BLOCKS)
    for cell in cells:
        totals[cell["block"]] += 1
        if cell["iteration"] == 0:
            base[cell["block"]] += 1
            continue
        per_variant = candidates[cell["block"]].setdefault(cell["variant"], Counter())
        per_variant["iter%d" % cell["iteration"]] += 1
    for block in BLOCKS:
        candidates[block] = OrderedDict((variant, counts(candidates[block][variant]))
                                        for variant in pl.VARIANTS if variant in candidates[block])
    return OrderedDict([
        ("total", sum(totals.values())),
        ("per_block", OrderedDict((block, totals.get(block, 0)) for block in BLOCKS)),
        ("base_per_block", OrderedDict((block, base.get(block, 0)) for block in BLOCKS)),
        ("candidates", candidates),
    ])


def _json_stable(value):
    return json.loads(json.dumps(value), object_pairs_hook=OrderedDict)


def composite_document(root, config, table, lineage_sha, plan_totals, population=None, cells=None,
                       models=None):
    """The 'phase2_composite.v1' document (deterministic: no timestamps, self
    sha256 over everything else). population/cells are injectable (tests,
    or a caller that already computed them)."""
    root = Path(root).resolve()
    population = check_population(population if population is not None else population_counts(root))
    cells = list(cells) if cells is not None else list(iter_cells(root, config, table, models))
    keys = [(c["block"], c["model_id"], c["source_run"], c["sample_id"]) for c in cells]
    if len(keys) != len(set(keys)):
        raise RecoveryRefused("a composite cell occurs twice")
    document = OrderedDict([
        ("schema_version", SCHEMA),
        ("run_id", pl.SUCCESSOR),
        ("lineage_sha256", lineage_sha),
        ("targets_sha256", table.sha256),
        ("model_ids", sorted(set(c["model_id"] for c in cells), key=list(pl.MODELS).index)),
        ("population", OrderedDict(list(population.items()) + [("derived_base_cells", 0)])),
        ("derived_lineages", derived_lineages(root)),
        ("cells", _cell_counts(cells)),
        ("stage_coverage", _coverage(cells)),
        ("plan_totals", plan_totals),
    ])
    document = _json_stable(document)
    document["composite_sha256"] = canonical_sha256(document)
    return document


def verify_document(document):
    body = OrderedDict((k, v) for k, v in document.items() if k != "composite_sha256")
    if document.get("schema_version") != SCHEMA or canonical_sha256(body) != document.get("composite_sha256"):
        raise RecoveryRefused("phase-2 composite document does not reproduce its hash")
    return True


def write_document(root, document, relative=DOCUMENT_REL):
    """Persist the composite document atomically (phase-2 tree only)."""
    from thesis.evaluation import atomic_io

    verify_document(document)
    path = pl.require_writable(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_io.atomic_write_json(path, document)
    return path
