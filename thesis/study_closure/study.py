"""Study sections of the closure: history, population, phase2 (read-only).

  history     the phase-2 lineage re-verifies (every protected byte of the six
              historical runs), the chain of custody back to recovery_001,
              the frozen phase-2 definitions chain lineage -> targets ->
              proof -> readiness -> contract -> config, and the target table
              re-derives from the repository;
  population  the census (66/66 terminal repair loops, one repair condition,
              1,980 base cells), its digest frozen in the lineage, the
              derived lineages (no base cell), the composite reconstruction
              (every cell of both blocks), its partition into base cells and
              candidates bound to the target table, the stage owners, and
              the persisted composite (if any) equal to the reconstruction;
  phase2      the missing-only plan is empty, the eleven persisted phase-2
              verification reports are present, bound and reproduce exactly
              (checks, counts, run binding), the enhanced pair totals agree
              between the reports and the composite, the stage invocation
              history ended 'completed' per stage with every (stage, model)
              invocation registered, ledger hygiene, recorded run binding.

collect(ctx, models=None) runs the three sections in dependency order (the
lineage verification first, the census before the table re-derivation, the
plan before the composite) and returns them as a list [history, population,
phase2]; models is a test seam (default core.MODELS) that restricts every
per-model loop to the given study models. In --write mode the composite is
persisted only when every preceding check passed (persisted_check). Every expensive shared result goes into ctx.cache (lineage_verify,
census, census_summary, population, plan_summary, composite_cells,
composite_document, phase2_reports, phase2_verify). Every count is computed
from the artifacts; the methodological constants come from the phase-2
package (pc.EXPECTED_POPULATION, pc.POPULATION_CELLS, pl.MODELS, pl.VARIANTS,
pl.MAX_ITERATIONS, pl.STAGES). The real study is expected to show 5,460
composite cells (943 pilot + 4,517 full_ext), 1,980 base cells and 109,200
enhanced pairs - never assumed here.

Python 3.8 compatible syntax.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.evaluation.condition_hashing import canonical_sha256, lf_normalized_sha256
from thesis.evaluation.recovery_lineage import checked_path
from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import plan as pp
from thesis.recovery_successor_005 import targets as pt
from thesis.recovery_successor_005 import verify as pv
from thesis.study_closure import composite_closure as cc
from thesis.study_closure import core
from thesis.study_closure.core import FAIL, PASS, ClosureRefused, Section  # noqa: F401

EXAMPLES = 10
SECTIONS = ("history", "population", "phase2")
FRAGMENTS_REL = core.PHASE2_RESULTS_REL + "/run_manifest.fragments"
# how freeze.py bound the census: targets.build_table stores
# canonical_sha256(census.summary(census.census(root, models))) as the table's
# census_digest, and freeze.step_lineage passes that digest to lineage.build
CENSUS_DIGEST_RULE = "canonical_sha256(census.summary(census.census(root, MODELS)))"
STATIC_FEEDBACK = "static_feedback"
TEST_FEEDBACK = "test_feedback"
# verify.py's legitimate string detail of full_ext:phase2_ledgers_bound_to_targets
# for a model without a phase-2 supplements directory
NO_LEDGERS_DETAIL = "no phase-2 ledgers"
# modules the closure process must never load (preflight.FORBIDDEN_IMPORTS
# plus the remaining provider SDK). dotenv is excluded on purpose: the config
# loader imports it at module level and pl.isolate_providers neutralises its
# load_dotenv (identity:provider_isolation proves the no-op); orchestrator is
# imported by the native verifiers and the census by design.
FORBIDDEN_MODULES = ("thesis.generation.generate", "thesis.generation.batch_api", "thesis.repair.run_repair",
                     "anthropic", "openai", "google.genai", "google.generativeai", "dashscope")


def _problems_detail(problems, **facts):
    detail = OrderedDict(facts)
    detail["problems"] = problems[:EXAMPLES]
    detail["problem_count"] = len(problems)
    return detail


# -- history ---------------------------------------------------------------------------

def definitions_bound(root, config_path, table_sha=None, lineage_sha=None):
    """The frozen phase-2 definitions reproduce their self-hashes and chain:
    lineage -> targets (table_sha256, census_digest) -> proof -> readiness
    -> frozen contract provenance (lineage, targets, proof, readiness LF
    sha, config LF sha, census digest, provider_calls NONE). Raw JSON reads
    with the hash rules of the producing modules; raises ClosureRefused."""
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.recovery_successor_005 import equivalence as pe
    from thesis.recovery_successor_005 import readiness as prd

    root = Path(root).resolve()
    defs = pl.DEFINITIONS_REL
    lineage = core.read_json(root, defs + "/lineage.json")
    if (lineage.get("schema_version") != pl.SCHEMA or lineage.get("run_id") != core.PHASE2
            or pl.fingerprint(lineage) != lineage.get("lineage_sha256")):
        raise ClosureRefused("the phase-2 lineage does not reproduce its self-hash")
    lineage_sha256 = lineage["lineage_sha256"]
    if lineage_sha is not None and lineage_sha256 != lineage_sha:
        raise ClosureRefused("the frozen lineage differs from the loaded one")
    targets = core.read_json(root, defs + "/targets.json")
    body = OrderedDict((k, v) for k, v in targets.items() if k != "table_sha256")
    if (targets.get("schema_version") != pt.SCHEMA or targets.get("run_id") != core.PHASE2
            or canonical_sha256(body) != targets.get("table_sha256")):
        raise ClosureRefused("the phase-2 target table does not reproduce its self-hash")
    if targets["table_sha256"] != lineage.get("targets_sha256"):
        raise ClosureRefused("the target table is not the one bound by the lineage")
    if table_sha is not None and targets["table_sha256"] != table_sha:
        raise ClosureRefused("the frozen target table differs from the loaded one")
    if not targets.get("census_digest") or targets.get("census_digest") != lineage.get("census_digest"):
        raise ClosureRefused("targets and lineage disagree on the census digest")
    proof = core.read_json(root, defs + "/equivalence.json")
    body = OrderedDict((k, v) for k, v in proof.items() if k != "proof_sha256")
    if (proof.get("schema_version") != pe.SCHEMA or proof.get("status") != "PROVEN"
            or proof.get("phase2_run_id") != core.PHASE2 or canonical_sha256(body) != proof.get("proof_sha256")):
        raise ClosureRefused("the phase-2 equivalence proof does not reproduce its self-hash")
    readiness = core.read_json(root, defs + "/readiness.json")
    body = OrderedDict((k, v) for k, v in readiness.items() if k != "readiness_sha256")
    if (readiness.get("schema_version") != prd.SCHEMA or readiness.get("gate") != "READY"
            or readiness.get("run_id") != core.PHASE2 or canonical_sha256(body) != readiness.get("readiness_sha256")
            or readiness.get("lineage_sha256") != lineage_sha256
            or readiness.get("equivalence_sha256") != proof["proof_sha256"]
            or readiness.get("provider_calls") != "NONE"):
        raise ClosureRefused("the phase-2 readiness is tampered or not bound to lineage/proof")
    contract = prc.load_frozen(checked_path(root, defs + "/contract.json"))
    if contract.get("run_id") != core.PHASE2 or contract.get("status") != prc.STATUS_READY:
        raise ClosureRefused("the frozen phase-2 contract is not the READY phase-2 contract")
    expected = OrderedDict([
        ("lineage_sha256", lineage_sha256),
        ("targets_sha256", targets["table_sha256"]),
        ("equivalence_sha256", proof["proof_sha256"]),
        ("readiness_lf_sha256", lf_normalized_sha256(checked_path(root, defs + "/readiness.json"))),
        ("config_lf_sha256", lf_normalized_sha256(Path(config_path))),
        ("census_digest", lineage["census_digest"]),
        ("provider_calls", "NONE"),
    ])
    provenance = contract.get("phase2_provenance") or {}
    wrong = [key for key, value in expected.items() if provenance.get(key) != value]
    if wrong:
        raise ClosureRefused("the frozen phase-2 contract provenance differs from the definitions: %s" % wrong)
    return OrderedDict([
        ("lineage_sha256", lineage_sha256), ("targets_sha256", targets["table_sha256"]),
        ("census_digest", lineage["census_digest"]), ("proof_sha256", proof["proof_sha256"]),
        ("readiness_sha256", readiness["readiness_sha256"]),
        ("readiness_lf_sha256", expected["readiness_lf_sha256"]),
        ("config_lf_sha256", expected["config_lf_sha256"]), ("contract_sha256", contract["contract_sha256"]),
    ])


def table_rederivation(rebuilt, frozen_sha):
    """The re-derived target table document equals the frozen one by sha."""
    ok = bool(frozen_sha) and rebuilt.get("table_sha256") == frozen_sha
    return ok, OrderedDict([("frozen_table_sha256", frozen_sha), ("rebuilt_table_sha256", rebuilt.get("table_sha256")),
                            ("target_count", rebuilt.get("target_count")),
                            ("sample_totals", rebuilt.get("sample_totals"))])


# -- population ------------------------------------------------------------------------

def census_problems(summary, models, expected_population=None, population_cells=None,
                    repair_conditions=None):
    """Every repair loop terminal, both blocks complete, the base population,
    exactly one repair condition (equal to every run's recorded condition
    when given: run -> sha)."""
    expected_population = expected_population or pc.EXPECTED_POPULATION
    population_cells = population_cells if population_cells is not None else pc.POPULATION_CELLS
    per_block = len(models) * len(pl.VARIANTS)
    loops = 2 * per_block
    problems = []
    if summary.get("total_repair_loops_done") != "%d/%d" % (loops, loops):
        problems.append("repair loops done: %s, expected %d/%d" % (summary.get("total_repair_loops_done"), loops, loops))
    blocks = summary.get("blocks") or {}
    for block in (pc.PILOT_BLOCK, pc.FULL_BLOCK):
        entry = blocks.get(block) or {}
        if entry.get("loops") != per_block or entry.get("terminal") != per_block:
            problems.append("%s block: %s/%s terminal, expected %d/%d"
                            % (block, entry.get("terminal"), entry.get("loops"), per_block, per_block))
        if entry.get("open"):
            problems.append("%s block: open loops %s" % (block, list(entry["open"])[:EXAMPLES]))
        if entry.get("not_started"):
            problems.append("%s block: not started %s" % (block, list(entry["not_started"])[:EXAMPLES]))
    base = summary.get("base_cells") or {}
    if (base.get(pc.PILOT_BLOCK) != expected_population[core.PILOT]
            or base.get(pc.FULL_BLOCK) != expected_population[core.PARENT]
            or base.get("total") != population_cells):
        problems.append("base cells %s, expected pilot %d, full_ext %d, total %d"
                        % (dict(base), expected_population[core.PILOT], expected_population[core.PARENT],
                           population_cells))
    conditions = list(summary.get("repair_conditions") or [])
    if len(conditions) != 1:
        problems.append("repair conditions: %s (exactly one expected)" % conditions)
    for run, sha in (repair_conditions or {}).items():
        if len(conditions) == 1 and sha != conditions[0]:
            problems.append("%s recorded repair condition %s differs from the census condition %s"
                            % (run, core.short(sha), core.short(conditions[0])))
    return problems


def census_digest(summary):
    """The digest rule of targets.build_table / freeze.step_lineage."""
    return canonical_sha256(summary)


def compact_census_summary(summary):
    """The census summary with the per-block open / not_started lists
    truncated to EXAMPLES (counts kept): the check detail stays small, the
    full summary lives in population.data['census_summary']."""
    compact = OrderedDict()
    for key, value in (summary or {}).items():
        if key != "blocks":
            compact[key] = value
            continue
        blocks = OrderedDict()
        for block, entry in (value or {}).items():
            entry = OrderedDict(entry or {})
            for field in ("open", "not_started"):
                items = list(entry.get(field) or [])
                entry[field] = items[:EXAMPLES]
                entry[field + "_count"] = len(items)
            blocks[block] = entry
        compact["blocks"] = blocks
    return compact


def provider_modules_loaded(modules=None):
    """Names of FORBIDDEN_MODULES (or a submodule of them) present in
    sys.modules: the census import chain (census -> repair.orchestrator ->
    generation.common / repair.feedback) must never pull provider or
    generation code into the closure process."""
    loaded = sys.modules if modules is None else modules
    return [name for name in FORBIDDEN_MODULES
            if name in loaded or any(key.startswith(name + ".") for key in loaded)]


def population_check(root):
    """pc.check_population over the frozen composite study plus pv.population
    (which also proves the phase-2 tree owns no base cell)."""
    counts = pc.check_population(pc.population_counts(root))
    result = pv.population(root)
    ok = result.get("status") == PASS
    return ok, OrderedDict([("population", counts), ("phase2_population", result)])


def derived_lineage_problems(entries):
    """Every derived run (recovery_001..004, phase 2) owns no base cell and
    carries its frozen contract sha."""
    problems = []
    runs = [entry.get("run_id") for entry in entries]
    if runs != list(pc.DERIVED_RUNS):
        problems.append("derived runs %s, expected %s" % (runs, list(pc.DERIVED_RUNS)))
    for entry in entries:
        if entry.get("base_cells") != 0:
            problems.append("%s owns %s base cell(s)" % (entry.get("run_id"), entry.get("base_cells")))
        if not entry.get("contract_sha256"):
            problems.append("%s carries no frozen contract sha" % entry.get("run_id"))
    return problems


def pilot_candidate_counts(root, models):
    """source_run -> assembled candidates of the pilot repair iterations
    (pc.pilot_runs / pc.pilot_target: every source re-hashed)."""
    counts = OrderedDict()
    for model in models:
        for run, variant, iteration in pc.pilot_runs(root, model):
            if iteration == 0:
                continue
            target = pc.pilot_target(root, model, run, variant, iteration)
            counts[run] = counts.get(run, 0) + len(target.samples)
    return counts


def candidate_runs():
    """Every admissible candidate source run of the repair design."""
    return set(pt.iteration_run(owner, variant, iteration)
               for owner in (core.PILOT,) + core.OWNERS for variant in pl.VARIANTS
               for iteration in range(1, pl.MAX_ITERATIONS + 1))


def cells_partition(cells, table, expected_population=None, pilot_expected=None):
    """The composite cells partition into the base population (iteration 0,
    pilot_002 / full_ext_001, counts == expected population) and candidates
    (iteration runs of the pilot and the four owners, <= MAX_ITERATIONS,
    never an excluded run); keys unique; every full_ext candidate appears in
    exactly one target with its source hash; the candidate counts equal the
    table (full_ext) and the pilot iteration assemblies (pilot)."""
    expected_population = expected_population or pc.EXPECTED_POPULATION
    problems = []
    keys = Counter((c["block"], c["model_id"], c["source_run"], c["sample_id"]) for c in cells)
    duplicates = [key for key, n in keys.items() if n > 1]
    if duplicates:
        problems.append("%d duplicate cell key(s): %s" % (len(duplicates), duplicates[:3]))
    per_block, base, candidates, per_run = Counter(), Counter(), Counter(), Counter()
    admissible = candidate_runs()
    base_run = OrderedDict([(pc.PILOT_BLOCK, core.PILOT), (pc.FULL_BLOCK, core.PARENT)])
    for cell in cells:
        block, run, iteration = cell["block"], cell["source_run"], cell["iteration"]
        per_block[block] += 1
        if block not in base_run:
            problems.append("unknown block %r" % block)
            continue
        if run in core.EXCLUDED_RUNS:
            problems.append("cell from the excluded run %s: %s" % (run, cell["sample_id"]))
        if iteration == 0:
            base[block] += 1
            if run != base_run[block]:
                problems.append("base cell of %s from %s" % (block, run))
            if cell.get("owner") != base_run[block]:
                problems.append("base cell owner %s" % cell.get("owner"))
        else:
            candidates[block] += 1
            per_run[run] += 1
            owner = run.split("__")[0]
            variant = cell.get("variant")
            # the short-circuit order keeps pt.iteration_run inside the design
            designed = (run in admissible and variant in pl.VARIANTS and type(iteration) is int
                        and 1 <= iteration <= pl.MAX_ITERATIONS
                        and run == pt.iteration_run(owner, variant, iteration))
            if not designed:
                problems.append("candidate cell outside the repair design: %s iteration %r variant %r"
                                % (run, iteration, variant))
            elif (block == pc.PILOT_BLOCK and owner != core.PILOT) or (block == pc.FULL_BLOCK
                                                                      and owner not in core.OWNERS):
                problems.append("candidate of block %s owned by %s" % (block, owner))
            expected_owner = core.PILOT if block == pc.PILOT_BLOCK else run
            if cell.get("owner") != expected_owner:
                problems.append("candidate owner %s, expected %s" % (cell.get("owner"), expected_owner))
    if len(cells) != per_block.get(pc.PILOT_BLOCK, 0) + per_block.get(pc.FULL_BLOCK, 0):
        problems.append("cells outside the two blocks")
    for block, run in base_run.items():
        if base.get(block, 0) != expected_population[run]:
            problems.append("%s base cells %d, expected %d" % (block, base.get(block, 0), expected_population[run]))
    index = OrderedDict()
    for target in table.targets:
        if target.is_base:
            continue
        for sample_id, facts in target.samples.items():
            key = (target.model_id, target.source_run, sample_id)
            if key in index:
                problems.append("table sample in two targets: %s" % (key,))
            index[key] = facts["source_sha256"]
    seen = set()
    for cell in cells:
        if cell["block"] == pc.FULL_BLOCK and cell["iteration"] != 0:
            key = (cell["model_id"], cell["source_run"], cell["sample_id"])
            if index.get(key) != cell.get("source_sha256"):
                problems.append("full_ext candidate not bound to a table target: %s/%s" % (key[1], key[2]))
            seen.add(key)
    if candidates.get(pc.FULL_BLOCK, 0) != len(index) or len(seen) != len(index):
        problems.append("full_ext candidates %d (%d distinct), table candidates %d"
                        % (candidates.get(pc.FULL_BLOCK, 0), len(seen), len(index)))
    if pilot_expected is not None:
        expected_pilot = sum(pilot_expected.values())
        if candidates.get(pc.PILOT_BLOCK, 0) != expected_pilot:
            problems.append("pilot candidates %d, pilot iteration assemblies hold %d"
                            % (candidates.get(pc.PILOT_BLOCK, 0), expected_pilot))
        for run in sorted(set(pilot_expected) | set(r for r in per_run if r.startswith(core.PILOT + "__"))):
            if per_run.get(run, 0) != pilot_expected.get(run, 0):
                problems.append("%s: %d cells, assembly holds %d" % (run, per_run.get(run, 0), pilot_expected.get(run, 0)))
    detail = _problems_detail(
        problems, cells_total=len(cells),
        base_per_block=OrderedDict((b, base.get(b, 0)) for b in pc.BLOCKS),
        candidates_per_block=OrderedDict((b, candidates.get(b, 0)) for b in pc.BLOCKS),
        candidates_per_owner_run=pc.counts(per_run),
        pilot_block=per_block.get(pc.PILOT_BLOCK, 0), full_ext_block=per_block.get(pc.FULL_BLOCK, 0),
        table_candidates=len(index), pilot_iteration_assemblies=pilot_expected)
    return problems, detail


def owner_problems(coverage, cells, table):
    """Stage owners of the composite: pilot block owned by pilot_002 only
    (every stage with evidence for every cell); full_ext enhanced owned by
    phase 2 only; correctness/dynamic: phase 2 owns exactly the samples of
    the static_feedback candidate targets, historical owners the rest;
    static supplements only by the 002/003 owners and phase 2, the phase-2
    static supplements only on test_feedback candidate cells."""
    problems = []
    pilot = coverage.get(pc.PILOT_BLOCK) or {}
    for stage in pc.STAGES:
        entry = pilot.get(stage) or {}
        owners = entry.get("owners") or {}
        if entry.get("with_evidence") != entry.get("cells") or not entry.get("cells"):
            problems.append("pilot %s: %s of %s cells with evidence" % (stage, entry.get("with_evidence"), entry.get("cells")))
        if list(owners) != [core.PILOT]:
            problems.append("pilot %s owners %s" % (stage, list(owners)))
    full = coverage.get(pc.FULL_BLOCK) or {}
    for stage in pc.STAGES:
        entry = full.get(stage) or {}
        if entry.get("with_evidence") != entry.get("cells") or not entry.get("cells"):
            problems.append("full_ext %s: %s of %s cells with evidence" % (stage, entry.get("with_evidence"), entry.get("cells")))
    enhanced = (full.get("enhanced") or {}).get("owners") or {}
    if list(enhanced) != [core.PHASE2]:
        problems.append("full_ext enhanced owners %s, expected %s only" % (list(enhanced), core.PHASE2))
    static_feedback_candidates = sum(len(t.samples) for t in table.select(variant=STATIC_FEEDBACK, base=False))
    admissible = candidate_runs() | set([core.PARENT])
    for stage in ("correctness", "dynamic"):
        owners = (full.get(stage) or {}).get("owners") or {}
        if owners.get(core.PHASE2, 0) != static_feedback_candidates:
            problems.append("full_ext %s: phase 2 owns %d, static_feedback candidates %d"
                            % (stage, owners.get(core.PHASE2, 0), static_feedback_candidates))
        foreign = [owner for owner in owners if owner != core.PHASE2 and owner not in admissible]
        if foreign:
            problems.append("full_ext %s: foreign owners %s" % (stage, foreign[:EXAMPLES]))
    allowed = set(pt.SUPPLEMENT_OWNERS + (core.PHASE2,))
    supplemented_by = (full.get("static") or {}).get("supplemented_by") or {}
    foreign = [owner for owner in supplemented_by if owner not in allowed]
    if foreign:
        problems.append("full_ext static supplemented by %s" % foreign)
    phase2_supplements = Counter()
    for cell in cells:
        static = cell.get("static")
        if static is None:
            continue
        for tool, by in (static.get("supplemented") or {}).items():
            if cell["block"] == pc.PILOT_BLOCK:
                problems.append("pilot cell %s supplemented by %s" % (cell["sample_id"], by))
            elif by not in allowed:
                problems.append("cell %s supplemented by %s" % (cell["sample_id"], by))
            elif by == core.PHASE2:
                phase2_supplements[tool] += 1
                if cell.get("variant") != TEST_FEEDBACK or cell["iteration"] == 0:
                    problems.append("phase-2 static supplement on a %s cell: %s" % (cell.get("variant"), cell["sample_id"]))
    detail = _problems_detail(problems, coverage=coverage, static_feedback_candidates=static_feedback_candidates,
                              phase2_static_supplements=pc.counts(phase2_supplements))
    return problems, detail


def persist_if_requested(ctx, document):
    """--write: run.py hands the persistence hook (composite_closure.
    persist_composite under the phase-2 writer lock) in
    ctx.options["persist_composite"]; the composite is persisted right after
    its reconstruction, before the persisted check compares it. Dry-run or
    no hook: nothing happens (None)."""
    hook = ctx.options.get("persist_composite") if ctx.options.get("write") else None
    if hook is None:
        return None
    return hook(document)


def persisted_composite(root, document, write_mode=False):
    """The persisted composite (core.COMPOSITE_REL) equals the recomputed
    document; absent: PASS in dry-run (reported), FAIL in write mode (the
    lead persists before this section runs)."""
    root = Path(root).resolve()
    path = checked_path(root, core.COMPOSITE_REL)
    if not path.is_file():
        detail = OrderedDict([("persisted", False), ("relative", core.COMPOSITE_REL),
                              ("composite_sha256", document.get("composite_sha256")),
                              ("note", "not persisted yet" if not write_mode else "missing in write mode")])
        return not write_mode, detail
    data = path.read_bytes()
    loaded = json.loads(data.decode("utf-8"), object_pairs_hook=OrderedDict)
    pc.verify_document(loaded)
    equal = (loaded.get("composite_sha256") == document.get("composite_sha256")
             and core.json_stable(loaded) == core.json_stable(document))
    # the dry run predicts the --write outcome: composite_write_allowed
    # accepts only the writer's own bytes (a foreign serialisation of the
    # same document would be refused as 'a different composite')
    identical = data == cc.document_bytes(document)
    detail = OrderedDict([("persisted", True), ("relative", core.COMPOSITE_REL),
                          ("raw_sha256", hashlib.sha256(data).hexdigest()),
                          ("composite_sha256", loaded.get("composite_sha256")),
                          ("recomputed_composite_sha256", document.get("composite_sha256")), ("equal", equal),
                          ("bytes_identical", identical)])
    return equal and identical, detail


def persist_blockers(*sections):
    """The failing checks of the sections that precede the composite
    persistence (history, population so far, the phase-2 plan): any of them
    blocks the --write of the composite."""
    blocking = []
    for section in sections:
        blocking.extend(section.failing())
    return blocking


def persisted_check(ctx, document, blocking, write_mode=False):
    """The body of population:composite_persisted. The persistence hook
    runs only when no preceding check failed (ground rule 5: --write never
    materialises the composite of a failed closure; the write guard of
    composite_closure covers ownership and state, the section status is
    gated here) and a blocked persistence is a FAIL in write mode. Then the
    persisted composite is compared with the reconstruction."""
    if blocking:
        persist = OrderedDict([("persisted", False), ("note", "not persisted: preceding checks failed"),
                               ("failing", list(blocking)[:EXAMPLES]), ("failing_count", len(blocking))])
        if write_mode:
            detail = OrderedDict([("persisted", False), ("relative", core.COMPOSITE_REL),
                                  ("composite_sha256", document.get("composite_sha256")),
                                  ("note", persist["note"]), ("failing", persist["failing"]),
                                  ("failing_count", len(blocking)), ("persist", persist)])
            return False, detail
    else:
        persist = persist_if_requested(ctx, document)
    ok, detail = persisted_composite(ctx.root, document, write_mode)
    detail["persist"] = persist
    return ok, detail


# -- phase2 ----------------------------------------------------------------------------

def plan_summary(root, config, table):
    return pp.summary(pp.plan(root, config, table, strict=True))


def plan_problems(summary):
    """Every phase-2 stage has no open item and no open target; no integrity
    finding; no stage outside the design."""
    problems = []
    totals = summary.get("totals") or {}
    findings = summary.get("integrity_findings") or []
    if findings:
        problems.append("%d integrity finding(s): %s" % (len(findings), list(findings)[:3]))
    for stage in pl.STAGES:
        entry = totals.get(stage)
        if entry is None:
            problems.append("stage %s absent from the plan totals" % stage)
        elif entry.get("items") != 0 or entry.get("targets_open") != 0:
            problems.append("stage %s: %s open item(s) in %s target(s)" % (stage, entry.get("items"), entry.get("targets_open")))
    extra = [stage for stage in totals if stage not in pl.STAGES]
    if extra:
        problems.append("stages outside the design: %s" % extra)
    return problems


def load_reports(root, models):
    """model -> (persisted phase-2 verification report, raw sha256); a
    missing or unreadable report refuses."""
    reports = OrderedDict()
    for model in models:
        relative = pv.report_relative(model)
        reports[model] = (core.read_json(root, relative), core.raw_sha256(root, relative))
    return reports


def report_problems(report, model, lineage_sha, targets_sha, contract_sha, authorization_sha):
    """Schema, scope, identity, PASS/complete, lineage/targets binding and
    the run binding of one persisted phase-2 report."""
    expected = OrderedDict([
        ("schema_version", pv.SCHEMA), ("scope", pv.SCOPE), ("run_id", core.PHASE2), ("model_id", model),
        ("status", PASS), ("model_complete", True), ("lineage_sha256", lineage_sha), ("targets_sha256", targets_sha)])
    problems = ["%s is %r, expected %r" % (key, report.get(key), value)
                for key, value in expected.items() if report.get(key) != value]
    binding = report.get("run_binding") or {}
    if not isinstance(binding, dict) or binding.get("contract_sha256") != contract_sha:
        problems.append("run_binding.contract_sha256 differs from the run's contract")
    if not isinstance(binding, dict) or binding.get("authorization_sha256") != authorization_sha:
        problems.append("run_binding.authorization_sha256 differs from the run's authorization")
    if not report.get("written_at_utc"):
        problems.append("written_at_utc missing")
    return problems


def reproduce_differences(persisted, recomputed):
    """The recomputed verification equals the persisted report in checks,
    counts and run binding (deep equality after json_stable) and BOTH are a
    complete PASS (equal checks alone would let a persisted FAIL
    'reproduce')."""
    stable_p, stable_r = core.json_stable(persisted), core.json_stable(recomputed)
    checks_p = OrderedDict((c.get("check"), c) for c in stable_p.get("checks") or [])
    checks_r = OrderedDict((c.get("check"), c) for c in stable_r.get("checks") or [])
    names = list(checks_p) + [name for name in checks_r if name not in checks_p]
    differing = [name for name in names if checks_p.get(name) != checks_r.get(name)]
    counts_equal = stable_p.get("counts") == stable_r.get("counts")
    binding_equal = stable_p.get("run_binding") == stable_r.get("run_binding")
    status_ok = (stable_p.get("status") == PASS and stable_r.get("status") == PASS
                 and stable_p.get("model_complete") is True and stable_r.get("model_complete") is True)
    ok = status_ok and not differing and counts_equal and binding_equal and bool(checks_r)
    detail = OrderedDict([
        ("status", stable_r.get("status")), ("model_complete", stable_r.get("model_complete")),
        ("persisted_status", stable_p.get("status")), ("persisted_model_complete", stable_p.get("model_complete")),
        ("checks", len(checks_r)), ("checks_equal", not differing), ("differing_checks", differing[:EXAMPLES]),
        ("differing_count", len(differing)), ("counts_equal", counts_equal), ("run_binding_equal", binding_equal)])
    return ok, detail


def enhanced_totals(results, coverage):
    """Enhanced pairs: per block the reports' expected pairs equal their
    rows, and the composite stage coverage carries the same pair totals."""
    problems = []
    if not results:
        problems.append("no recomputed verification results")
    pairs, rows = Counter(), Counter()
    for model, result in (results or {}).items():
        counts = result.get("counts") or {}
        for block in pc.BLOCKS:
            enhanced = (counts.get(block) or {}).get("enhanced") or {}
            pairs[block] += enhanced.get("expected_pairs") or 0
            rows[block] += enhanced.get("rows") or 0
    composite = OrderedDict((block, ((coverage.get(block) or {}).get("enhanced") or {}).get("pairs"))
                            for block in pc.BLOCKS)
    for block in pc.BLOCKS:
        if pairs[block] != rows[block]:
            problems.append("%s: %d expected pairs, %d rows" % (block, pairs[block], rows[block]))
        if composite[block] != pairs[block]:
            problems.append("%s: composite pairs %s, verification pairs %d" % (block, composite[block], pairs[block]))
    detail = _problems_detail(problems, pilot_pairs=pairs[pc.PILOT_BLOCK], full_ext_pairs=pairs[pc.FULL_BLOCK],
                              total=pairs[pc.PILOT_BLOCK] + pairs[pc.FULL_BLOCK],
                              rows=OrderedDict((b, rows[b]) for b in pc.BLOCKS), composite_pairs=composite,
                              models=len(results or {}))
    return problems, detail


def fragment_names(root):
    """File names directly under the phase-2 manifest fragments directory."""
    directory = checked_path(Path(root).resolve(), FRAGMENTS_REL)
    if not directory.is_dir():
        raise ClosureRefused("missing artifact: " + FRAGMENTS_REL)
    return sorted(p.name for p in directory.iterdir() if p.is_file())


def invocation_fragments(root):
    """name -> parsed fragment of every current invocation.* fragment (the
    history directory holds superseded and refused copies; not read)."""
    directory = checked_path(Path(root).resolve(), FRAGMENTS_REL)
    result = OrderedDict()
    for name in fragment_names(root):
        if name.startswith("invocation.") and name.endswith(".json"):
            result[name] = json.loads((directory / name).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    return result


def fragment_identity(name):
    """invocation.<stage>@<model>[@<suffix>].json -> (stage, model)."""
    stem = name[len("invocation."):]
    if stem.endswith(".json"):
        stem = stem[:-len(".json")]
    stage, _, tail = stem.partition("@")
    return stage, tail.split("@")[0]


def fragment_problems(name, fragment, stage, model):
    """The content of one invocation fragment names the phase-2 run, the
    stage and the model, and is not a refused registration."""
    if not isinstance(fragment, dict):
        return ["%s: unreadable fragment" % name]
    problems = []
    content = fragment.get("content") or {}
    if fragment.get("run_id") != core.PHASE2 or content.get("run_id") != core.PHASE2:
        problems.append("%s: not a phase-2 fragment (run_id %r/%r)"
                        % (name, fragment.get("run_id"), content.get("run_id")))
    if content.get("stage") != stage:
        problems.append("%s: content stage %r, expected %s" % (name, content.get("stage"), stage))
    scope = content.get("model_scope")
    if not isinstance(scope, list) or model not in scope:
        problems.append("%s: %s not in model_scope %r" % (name, model, scope))
    if fragment.get("outcome") == "REFUSED":
        problems.append("%s: refused registration" % name)
    return problems


def stage_history(rows, fragments, models, stages=pl.STAGES):
    """Per stage: the last log row is 'completed' with no open item; the
    invocations are counted (an 'invoked' row without a 'completed' row
    before the next 'invoked' is an interrupted invocation - reported, not a
    failure); an invocation fragment invocation.<stage>@<model>[@...].json
    exists for every (stage, model) and its CONTENT names the phase-2 run,
    the stage and the model (never a refused copy); a fragment of a stage or
    model outside the study is a problem. fragments: name -> parsed
    fragment (invocation_fragments)."""
    problems = []
    per_stage = OrderedDict((stage, OrderedDict([("invoked", 0), ("completed", 0), ("other", 0),
                                                 ("interrupted_invocations", 0), ("last_status", None),
                                                 ("last_open_items", None), ("invocation_fragments", 0)]))
                            for stage in stages)
    pending = {}
    for row in rows:
        if row.get("run_id") != core.PHASE2:
            problems.append("foreign stage invocation row (run_id %r)" % row.get("run_id"))
            continue
        stage, status = row.get("stage"), row.get("status")
        entry = per_stage.get(stage)
        if entry is None:
            problems.append("unknown stage %r in the invocation log" % stage)
            continue
        if status == cc.STATUS_INVOKED:
            if pending.get(stage):
                entry["interrupted_invocations"] += 1
            pending[stage] = True
            entry["invoked"] += 1
        elif status == cc.STATUS_COMPLETED:
            pending[stage] = False
            entry["completed"] += 1
        else:
            entry["other"] += 1
        entry["last_status"] = status
        entry["last_open_items"] = row.get("open_items")
    for stage, entry in per_stage.items():
        if entry["last_status"] != cc.STATUS_COMPLETED or entry["last_open_items"] != []:
            problems.append("%s: last invocation %r with open items %r" % (stage, entry["last_status"], entry["last_open_items"]))
        if pending.get(stage):
            entry["interrupted_invocations"] += 1
        for model in models:
            prefix = "invocation.%s@%s" % (stage, model)
            found = [n for n in fragments
                     if n.startswith(prefix) and (n[len(prefix):] == ".json" or n[len(prefix):].startswith("@"))]
            if not found:
                problems.append("no invocation fragment for %s@%s" % (stage, model))
            for name in found:
                problems.extend(fragment_problems(name, fragments[name], stage, model))
            entry["invocation_fragments"] += len(found)
    outside = [name for name in fragments
               if fragment_identity(name)[0] not in stages or fragment_identity(name)[1] not in models]
    if outside:
        problems.append("invocation fragment(s) outside the study: %s" % outside[:EXAMPLES])
    detail = _problems_detail(problems, stages=per_stage,
                              interrupted_invocations=sum(e["interrupted_invocations"] for e in per_stage.values()),
                              models=len(models), fragments=len(fragments))
    return problems, detail


def ledger_hygiene(reports):
    """From the persisted reports: no stray phase-2 ledger and no temporary
    file for any model; archived torn tails and repeated build groups are
    incidents (counted for the disclosures, not failures)."""
    problems = []
    per_model = OrderedDict()
    torn = repeated = stray_total = temporary_total = 0
    for model, report in (reports or {}).items():
        checks = OrderedDict((c.get("check"), c) for c in report.get("checks") or [])
        bound = checks.get("full_ext:phase2_ledgers_bound_to_targets")
        detail = bound.get("detail") if isinstance(bound, dict) else None
        if detail == NO_LEDGERS_DETAIL and bound.get("status") == PASS:
            # a model without a phase-2 supplements directory: nothing stray,
            # torn or temporary (verify.py returns the plain string)
            detail = OrderedDict([("stray", []), ("archived_torn_tails", []), ("temporary_files", [])])
        if not isinstance(detail, dict):
            problems.append("%s: no phase2_ledgers_bound_to_targets detail" % model)
            continue
        stray = list(detail.get("stray") or [])
        temporary = list(detail.get("temporary_files") or [])
        torn_tails = list(detail.get("archived_torn_tails") or [])
        if bound.get("status") != PASS or stray:
            problems.append("%s: stray phase-2 ledgers %s" % (model, stray[:EXAMPLES]))
        if temporary:
            problems.append("%s: temporary files %s" % (model, temporary[:EXAMPLES]))
        groups = sum((c.get("detail") or {}).get("repeated_build_groups") or 0
                     for name, c in checks.items() if name.endswith(":phase2_provenance")
                     and isinstance(c.get("detail"), dict))
        torn += len(torn_tails)
        repeated += groups
        stray_total += len(stray)
        temporary_total += len(temporary)
        per_model[model] = OrderedDict([("stray", len(stray)), ("temporary_files", len(temporary)),
                                        ("archived_torn_tails", torn_tails[:EXAMPLES]), ("repeated_build_groups", groups)])
    if not reports:
        problems.append("no persisted reports")
    detail = _problems_detail(problems, per_model=per_model, stray=stray_total, temporary_files=temporary_total,
                              archived_torn_tails=torn, repeated_build_groups=repeated)
    return problems, detail


def invocations_registered(binding, reports, stages=pl.STAGES):
    """The recorded run binding (manifest fragments) registers at least one
    invocation and one stage runtime sha per stage, and every persisted
    report's run_binding registers both per stage."""
    problems = []
    registered = OrderedDict()
    if not isinstance(binding, dict) or binding.get("error") or not binding.get("contract_sha256"):
        problems.append("no recorded run binding (%s)" % ((binding or {}).get("error") if isinstance(binding, dict) else binding))
    else:
        for field in ("invocation_sha256", "stage_runtime_sha256"):
            values = binding.get(field) or {}
            for stage in stages:
                if not values.get(stage):
                    problems.append("%s: no %s registered" % (stage, field))
        registered = OrderedDict((stage, len((binding.get("invocation_sha256") or {}).get(stage) or []))
                                 for stage in stages)
    for model, report in (reports or {}).items():
        recorded = report.get("run_binding") or {}
        for field in ("invocation_sha256", "stage_runtime_sha256"):
            values = recorded.get(field) if isinstance(recorded, dict) else None
            empty = [stage for stage in stages if not (values or {}).get(stage)]
            if empty:
                problems.append("%s: report %s empty for %s" % (model, field, empty))
    detail = _problems_detail(problems, invocations_per_stage=registered, reports=len(reports or {}))
    return problems, detail


# -- section assembly ----------------------------------------------------------------------

def _cached(ctx, key):
    value = ctx.cache.get(key)
    if value is None:
        raise ClosureRefused("input unavailable: " + key)
    return value


def _census(ctx, models):
    """census.census over the study models, computed once (cached); the
    census import chain must not load provider code (fail-closed)."""
    if ctx.cache.get("census") is None or ctx.cache.get("census_summary") is None:
        from thesis.recovery_successor_004 import census

        result = ctx.timed("census", census.census, ctx.root, list(models))
        loaded = provider_modules_loaded()
        if loaded:
            raise ClosureRefused("provider/generation module(s) loaded in the closure process: %s" % loaded)
        ctx.cache["census"] = result
        ctx.cache["census_summary"] = census.summary(result)
    return ctx.cache["census"], ctx.cache["census_summary"]


def _run_repair_conditions(ctx):
    """run -> repair_condition_sha256 from the runs section (when available)."""
    bindings = ctx.cache.get("run_bindings") or OrderedDict()
    result = OrderedDict()
    for run, binding in bindings.items():
        sha = ((binding or {}).get("runtime") or {}).get("repair_cond")
        if sha:
            result[run] = sha
    return result


def collect(ctx, models=None):
    """The sections history, population and phase2, in dependency order.
    models: the study models (default core.MODELS; a test seam restricting
    every per-model loop)."""
    root = ctx.root
    models = list(models) if models else list(core.MODELS)
    history, population, phase2 = Section("history"), Section("population"), Section("phase2")
    write_mode = bool(ctx.options.get("write"))

    # history ------------------------------------------------------------------------
    def lineage_verify():
        result = ctx.timed("lineage_verify", pv.immutability, ctx.lineage)
        ctx.cache["lineage_verify"] = result
        history.data["lineage_sha256"] = ctx.lineage.sha256
        history.data["targets_sha256"] = ctx.lineage.targets_sha256
        return result.get("status") == PASS, result.get("detail")

    history.guard("phase2_lineage_verify", lineage_verify)

    def custody_chain():
        bindings = pl.custody(root, ctx.lineage.document["protected"])
        history.data["custody"] = bindings
        return True, bindings

    history.guard("custody_chain", custody_chain)

    def definitions():
        from thesis.recovery_successor_005 import preflight as pf

        facts = definitions_bound(root, ctx.config_path, table_sha=ctx.table.sha256, lineage_sha=ctx.lineage.sha256)
        chain = pf.binding_chain(root, ctx.config, ctx.config_path, ctx.lineage)
        wrong = [key for key, value in chain.items() if facts.get(key) != value]
        if wrong:
            raise ClosureRefused("preflight.binding_chain disagrees with the definitions on %s" % wrong)
        history.data["definitions"] = facts
        return True, OrderedDict([("definitions", facts), ("binding_chain", chain)])

    history.guard("phase2_definitions_bound", definitions)

    def rederives():
        result, _ = _census(ctx, models)
        rebuilt = ctx.timed("build_table", pt.build_table, root, census_result=result)
        return table_rederivation(rebuilt, ctx.table.sha256)

    history.guard("target_table_rederives", rederives)

    # population ---------------------------------------------------------------------------
    def census_terminal():
        _, summary = _census(ctx, models)
        population.data["census_summary"] = summary
        repair = _run_repair_conditions(ctx)
        problems = census_problems(summary, models, repair_conditions=repair)
        return not problems, _problems_detail(problems, summary=compact_census_summary(summary),
                                              run_repair_conditions=repair)

    population.guard("census_66_66", census_terminal)

    def digest_frozen():
        _, summary = _census(ctx, models)
        computed = census_digest(summary)
        frozen = ctx.lineage.document.get("census_digest")
        in_table = ctx.table.document.get("census_digest")
        ok = bool(frozen) and computed == frozen and computed == in_table
        return ok, OrderedDict([("rule", CENSUS_DIGEST_RULE), ("computed", computed), ("lineage", frozen),
                                ("targets", in_table)])

    population.guard("census_digest_frozen", digest_frozen)

    def base_cells():
        ok, detail = population_check(root)
        ctx.cache["population"] = detail["population"]
        population.data["population"] = detail["population"]
        return ok, detail

    population.guard("base_cells_1980", base_cells)

    def derived():
        entries = pc.derived_lineages(root)
        problems = derived_lineage_problems(entries)
        return not problems, _problems_detail(problems, lineages=entries)

    population.guard("derived_lineages_own_no_base_cells", derived)

    # phase2: the plan (its totals are part of the composite document) ---------------
    def plan_empty():
        summary = ctx.timed("plan", plan_summary, root, ctx.config, ctx.table)
        ctx.cache["plan_summary"] = summary
        phase2.data["plan_totals"] = summary["totals"]
        problems = plan_problems(summary)
        return not problems, _problems_detail(problems, totals=summary["totals"],
                                              integrity_findings=list(summary["integrity_findings"])[:EXAMPLES])

    phase2.guard("plan_empty", plan_empty)

    # population: the composite ------------------------------------------------------------
    population.data["composite"] = OrderedDict([("relative", core.COMPOSITE_REL), ("persisted", False),
                                                ("raw_sha256", None), ("composite_sha256", None)])

    def reconstruction():
        plan = _cached(ctx, "plan_summary")
        cells = ctx.timed("composite_cells", lambda: list(pc.iter_cells(root, ctx.config, ctx.table, models)))
        ctx.cache["composite_cells"] = cells
        document = pc.composite_document(root, ctx.config, ctx.table, ctx.lineage.sha256, plan["totals"],
                                         population=ctx.cache.get("population"), cells=cells)
        pc.verify_document(document)
        ctx.cache["composite_document"] = document
        population.data["cells"] = document["cells"]
        population.data["composite"]["composite_sha256"] = document["composite_sha256"]
        return True, OrderedDict([("composite_sha256", document["composite_sha256"]), ("cells", document["cells"]),
                                  ("model_ids", len(document["model_ids"]))])

    population.guard("composite_reconstruction", reconstruction)

    def partition():
        cells = _cached(ctx, "composite_cells")
        pilot_expected = pilot_candidate_counts(root, models)
        problems, detail = cells_partition(cells, ctx.table, pc.EXPECTED_POPULATION, pilot_expected)
        return not problems, detail

    population.guard("composite_cells_partition", partition)

    def owners():
        document = _cached(ctx, "composite_document")
        problems, detail = owner_problems(document["stage_coverage"], _cached(ctx, "composite_cells"), ctx.table)
        return not problems, detail

    population.guard("composite_owners", owners)

    def persisted():
        document = _cached(ctx, "composite_document")
        # --write persists only a composite every preceding check vouches for
        blocking = persist_blockers(history, population, phase2)
        ok, detail = persisted_check(ctx, document, blocking, write_mode)
        population.data["composite"] = OrderedDict([
            ("relative", core.COMPOSITE_REL), ("persisted", detail["persisted"]),
            ("raw_sha256", detail.get("raw_sha256")), ("composite_sha256", detail.get("composite_sha256"))])
        return ok, detail

    population.guard("composite_persisted", persisted)

    # phase2: reports ------------------------------------------------------------------------------
    def reports_present():
        # the readable reports are cached BEFORE the binding is consulted: a
        # crashed runs section costs the binding problems, not the inputs of
        # ledger_hygiene / manifest_invocations_registered
        loaded = load_reports(root, models)
        ctx.cache["phase2_reports"] = OrderedDict((model, report) for model, (report, _) in loaded.items())
        phase2.data["reports"] = OrderedDict((model, sha) for model, (_, sha) in loaded.items())
        binding = (ctx.cache.get("run_bindings") or {}).get(core.PHASE2)
        per_model = OrderedDict()
        failing = []
        for model, (report, sha) in loaded.items():
            problems = report_problems(report, model, ctx.lineage.sha256, ctx.table.sha256,
                                       (binding or {}).get("contract_sha256"),
                                       (binding or {}).get("authorization_sha256"))
            if binding is None:
                problems.append("run binding input unavailable: run_bindings[%s]" % core.PHASE2)
            per_model[model] = OrderedDict([("status", report.get("status")), ("model_complete", report.get("model_complete")),
                                            ("raw_sha256", sha), ("problems", problems[:EXAMPLES])])
            if problems:
                failing.append(model)
        return not failing, OrderedDict([("models", per_model), ("failing_models", failing),
                                         ("run_binding_available", binding is not None)])

    phase2.guard("reports_present", reports_present)

    def reports_reproduce():
        immutability = _cached(ctx, "lineage_verify")
        if immutability.get("status") != PASS:
            # minutes of verify_model over drifted bytes cannot reproduce a PASS
            raise ClosureRefused("the lineage verification failed: no report can reproduce a PASS")
        reports = ctx.cache.get("phase2_reports") or OrderedDict()
        deep = pv.prepare_deep_checks(root, ctx.lineage, {"immutability": immutability})
        results, per_model, failing = OrderedDict(), OrderedDict(), []
        for model in models:
            result = ctx.timed("verify_model." + model, pv.verify_model, root, ctx.config, ctx.table, model,
                               ctx.lineage, deep)
            results[model] = result
            if model not in reports:
                per_model[model] = OrderedDict([("status", result.get("status")), ("persisted", False)])
                failing.append(model)
                continue
            ok, detail = reproduce_differences(reports[model], result)
            per_model[model] = detail
            if not ok:
                failing.append(model)
        ctx.cache["phase2_verify"] = results
        return not failing, OrderedDict([("models", per_model), ("failing_models", failing)])

    phase2.guard("reports_reproduce", reports_reproduce)

    def pairs_total():
        results = _cached(ctx, "phase2_verify")
        document = _cached(ctx, "composite_document")
        problems, detail = enhanced_totals(results, document["stage_coverage"])
        phase2.data["enhanced_pairs"] = OrderedDict([("pilot", detail["pilot_pairs"]), ("full_ext", detail["full_ext_pairs"]),
                                                     ("total", detail["total"])])
        return not problems, detail

    phase2.guard("enhanced_pairs_total", pairs_total)

    incidents = OrderedDict([("archived_torn_tails", None), ("repeated_build_groups", None),
                             ("interrupted_invocations", None)])
    phase2.data["incidents"] = incidents

    def history_of_stages():
        problems, detail = stage_history(cc.stage_invocation_rows(root), invocation_fragments(root), models)
        incidents["interrupted_invocations"] = detail["interrupted_invocations"]
        phase2.data["stage_history"] = detail["stages"]
        return not problems, detail

    phase2.guard("stage_history", history_of_stages)

    def hygiene():
        problems, detail = ledger_hygiene(_cached(ctx, "phase2_reports"))
        incidents["archived_torn_tails"] = detail["archived_torn_tails"]
        incidents["repeated_build_groups"] = detail["repeated_build_groups"]
        return not problems, detail

    phase2.guard("ledger_hygiene", hygiene)

    def registered():
        binding = pv.recorded_binding(root)
        problems, detail = invocations_registered(binding, ctx.cache.get("phase2_reports") or OrderedDict())
        return not problems, detail

    phase2.guard("manifest_invocations_registered", registered)
    return [history, population, phase2]
