"""Every metric of the frozen methodology, computed from a core.Dataset.

WHY this shape
- Cohorts are taken exclusively from the trajectory rows (the loops' own
  state ledgers, normalized): BASE = the iteration-0 artifact of every base
  cell, STEP[v][k] = artifact_iter<min(k, final_iteration)> (last artifact
  carried forward), FINAL[v] = final_artifact (== STEP[v][2]). No held-out
  or post-hoc evidence takes part in the selection, and every variant and
  step uses the identical base-cell cohort.
- Every estimate is a ratio of sums over its observation units. The
  sufficient statistics (numerator, denominator) are aggregated ONCE per
  (metric, population, block, strata) and benchmark cluster; the stratified
  cluster bootstrap (stats.ClusterBootstrap, one shared weight matrix per
  replicate count) only touches these per-cluster sums, so the cost does not
  grow with the number of pairs/findings.
- 'composite' pools the two disjoint blocks; every unit contributes to its
  own block and to the composite.
- Fail closed: the derived artifact columns of the normalizer
  (three-state verdicts, compile_error, completeness, low_confidence_any,
  cleaning unions, enh_* counts) are recomputed from tool_entries,
  findings and enhanced_pairs and must agree; contradictions, duplicates,
  missing rows and foreign values raise core.AnalysisRefused.
- Terminal statuses are trajectory facts only: a SUCCESSFUL REPAIR is an
  improvement on an explicit endpoint (R02); stopped_clean /
  stopped_tests_pass never enter a success count.

Conservative readings of ambiguous methodology text (reported as deviations)
1. Paired Q06 cohort: a base cell is excluded from every paired Q06 metric
   (R01-R05, G01, C05) when ANY of its artifacts (base or a STEP artifact of
   any variant) is baseline_incompatible, so all variants share one cohort.
   Unpaired Q06/Q07/Q09/Q10 rates exclude baseline_incompatible artifacts
   from their denominators ("missingness: as Q06"). 0 such artifacts exist
   in the frozen data; the rule is kept.
2. Paired E02 cohort: cells with >= 1 valid pair at baseline; every artifact
   of a cell must carry the same number of valid pairs (spec-level gates),
   otherwise the pipeline refuses.
3. Tool applicability: tool_entries.applicable must equal
   (state not in INAPPLICABLE_STATES) and be uniform per (tool, execution
   model); S02/D02 and the F05 artifact shares use the applicable artifacts
   as denominator; F06 additionally requires both tools COMPLETED.
4. C04 (applicability "ran tools") uses entries with ran == true:
   NOT_APPLICABLE entries carry a duration but did not run. TIMEOUT entries
   are excluded and counted, null durations excluded and counted.
5. SA1 repeats Q06 (BASE, FINAL) and R02/R04/R05 for both paired endpoints
   (Q06 and E02); the methodology names the metrics, not the endpoints.
   Q09 "raw-clean" = assembled and Q04 any_including_fence false (the Q04
   flags are defined on assembled artifacts only).
6. C05 "requests" = repair generation records (one per candidate, C01);
   request rounds (provider retries) are reported by C01 only.
7. Strata keys beyond the spec list: iteration (GENERATED per iteration,
   R06 final iteration), quantity (C01/C02/C05/F05 sub-quantities),
   outlier_rule (C04), sensitivity (SA1). Extra estimate keys: statistic
   (share/difference/mean/median/count/scaled_rate/agreement), excluded
   (units removed by an exclusion rule), and metric-specific extras (E04
   groups, F06 2x2, C02 coverage/median, C03/C04 p95/n, C04 ran_entries /
   timeout_share, G01 reference). F05 keeps the finding class under the
   strata key 'family' (the tables consume that key).
8. Interval support: an estimate resting on < 2 benchmark clusters, or on a
   cluster of a single-cluster bootstrap stratum, is reported without an
   interval (and without a p-value), the note says why (stats.support). The
   pilot has one benchmark per family, so pilot per-family estimates are
   point estimates; the methodology's "approximate" pilot label does not
   cover a zero-width interval. A primary hypothesis without a p-value
   refuses.
9. Tool universe: the frozen core.STATIC_TOOLS / DYNAMIC_TOOLS, every artifact
   carries an entry of every tool ("an ABSENT entry for an APPLICABLE tool
   is a data error"); a dataset that records the frozen scope
   (provenance tool_scope, normalize) must agree with the observed
   applicability per (tool, execution model).
10. Replicate counts: the primary and the descriptive bootstrap must use the
   methodology's counts (10,000 / 2,000); other counts refuse unless the
   caller passes exploratory=True, and then every bootstrapped estimate is
   labelled exploratory / not confirmatory.
11. SA1 is a re-analysis without the BL-01 benchmark: its intervals come from
   a separate bootstrap over the remaining clusters (same seed and
   replicate count), not from the main bootstrap with an empty cluster.
12. Finding families must belong to the frozen class vocabulary
   (finding_rules.families); input/output token counts must be present
   (only reasoning_tokens may be null, C02); a null refuses.

Post-freeze addendum_1 (methodology_addendum.json, declared after the dry run)
The frozen definitions above are untouched; the addendum adds descriptive
sensitivity metrics X01-X06 (no p-values, no Holm, note prefix
"POST-FREEZE addendum_1 (descriptive): ") and three estimate fields. Every
estimate carries `post_freeze` (True exactly for X01-X06), `ci_degenerate`
(None without an interval, else ci_low == ci_high; a zero-width interval
also gets the DEGENERATE_NOTE sentence), `p_resolution` and
`p_holm_resolution` (primary family only, else None). The addendum is bound
to the frozen methodology by its canonical sha256 and its X01-X06 names; its
top-N and vocabulary are read from / checked against its text.
Readings of the addendum contract (reported as deviations):
13. p_resolution = 2 / replicates_primary, the DRAWN replicate count of the
   primary bootstrap (the methodology's 10,000 in every confirmatory run, an
   exploratory run's own count), the contract rule tables.py and validate.py
   check. When resamples with a zero denominator are skipped, the p-value
   rests on fewer usable replicates and its own smallest positive value
   2 / usable is coarser; the note of such a hypothesis states both (the
   frozen data skips none). The Holm input is passed in sort_key order, so
   Holm ties - and the p_holm_resolution order - are broken by sort_key.
14. X01 `excluded` = every base cell of the block outside the X01 cohort: the
   paired cells removed by the auto-closed rule plus the endpoint's own
   exclusions (R04's `excluded`); the note gives the split. "Any artifact on
   any trajectory" = the base artifact and every iteration artifact 1..final
   of the three trajectories.
15. X02 `dirty_only_under_frozen_rule` is carried by the DIRTY estimates only.
16. X03 uses the F01 tool set (core.STATIC_ANALYSIS_TOOLS, applicable
   entries, compiler excluded) for both parts; "DIRTY only via t" = t is the
   only such tool with a reported blocking finding; reported blocking findings
   count in every entry state (the frozen rule X03 decomposes). A reported
   blocking finding of such a tool without a check id refuses (strata value)
   in X03, its only reader: the frozen metrics and compute_primary never
   depend on check_id.
17. X04 numerator = artifacts in the denominator (verdict neither pass nor
   baseline_incompatible: Q06's domain) with that static state, so the share
   is a subset ratio; the frozen data has no baseline_incompatible artifact.
18. X05 / X06 emit every listed stratum, also with denominator 0 (value None).
"""
from __future__ import annotations

import json
import re
from collections import Counter, OrderedDict
from itertools import combinations

from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.study_analysis import core, normalize, stats

PASS = "pass"
BASELINE_INCOMPATIBLE = "baseline_incompatible"
COMPLETED = "COMPLETED"
TIMEOUT = "TIMEOUT"
DIRTY, CLEAN_COMPLETE, NO_FINDING_INCOMPLETE = core.THREE_STATE
STOPPED_BUDGET = "stopped_budget"
STOPPED_ANALYSIS_INCOMPLETE = "stopped_analysis_incomplete"
P95 = 0.95                      # "p95" of C03/C04
TOKENS_SCALE = 1000000          # C05 "per 1,000,000 repair output tokens"
REQUESTS_SCALE = 100            # C05 "per 100 repair requests"

STRATA_ORDER = ("model_id", "execution_model", "variant", "family", "step", "tool", "check_id", "state", "verdict",
                "status", "kind", "transition", "heldout_transition", "endpoint", "comparison", "flag", "class", "pair",
                "iteration", "quantity", "outlier_rule", "sensitivity")
COMPOSITE = core.COMPOSITE
BLOCKS_ALL = core.BLOCKS + (COMPOSITE,)

ALL = ((),)
BY_M = ((), ("model_id",))
BY_E = ((), ("execution_model",))
BY_ME = ((), ("model_id",), ("execution_model",))
BY_MEX = BY_ME + (("model_id", "execution_model"),)
BY_MEF = BY_ME + (("family",),)
BY_MEXF = BY_MEX + (("family",),)
BY_ITER = ((), ("iteration",))

ENDPOINT_STATES = OrderedDict([("Q06", ("pass", "not_pass")), ("E02", ("all_pass", "not_all_pass")),
                               ("F01", core.THREE_STATE), ("F02", core.THREE_STATE)])
BINARY_ENDPOINTS = ("Q06", "E02")
COMPARISONS = tuple(combinations(core.VARIANTS, 2))
Q04_FLAGS = core.CLEANING_FLAGS + ("any", "any_including_fence")
KIND_COLUMNS = OrderedDict([("reported_blocking", "num_reported_blocking"),
                            ("low_confidence", "num_low_confidence"),
                            ("non_blocking", "num_non_blocking")])
ENH_STATUS_COLUMNS = OrderedDict([("pass", "enh_pass"), ("fail", "enh_fail"), ("build_failed", "enh_build_failed"),
                                  ("crash", "enh_crash"), ("timeout", "enh_timeout"),
                                  ("runtime_error", "enh_runtime_error")])
TOKEN_FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens")
OUTLIER_RULES = ("all", "excluding_above_threshold")
# F06: (pair label, (tool a, tool b), family class, class label, execution models, methodology phrase)
F06_PAIRS = (
    ("tsan+llov", ("tsan", "llov"), ("race",), "race", ("omp",), "(tsan, llov) race on omp"),
    ("must+parcoach", ("must", "parcoach"), ("mpi_usage", "deadlock"), "mpi_usage+deadlock", ("mpi",),
     "(must, parcoach) mpi_usage/deadlock on mpi"),
    ("asan_ubsan+memcheck", ("asan_ubsan", "memcheck"), ("memory",), "memory", core.EXECUTION_MODELS,
     "(asan_ubsan, memcheck) memory on all"),
    ("gcc_analyzer+cppcheck", ("gcc_analyzer", "cppcheck"), ("memory", "null_deref", "uninitialized"),
     "memory+null_deref+uninitialized", core.EXECUTION_MODELS,
     "(gcc_analyzer, cppcheck) memory+null_deref+uninitialized on all"),
)
DIAGNOSTIC = "diagnostic population, never mixed with BASE/STEP/FINAL rates"
STAGE_OF = OrderedDict([(t, "static") for t in core.STATIC_TOOLS] + [(t, "dynamic") for t in core.DYNAMIC_TOOLS])
REQUIRED_TOKENS = ("input_tokens", "output_tokens")      # C02: only reasoning_tokens may be null

# -- post-freeze addendum_1 (module docstring) --
ADDENDUM_LABEL = "addendum_1"
POST_FREEZE_NOTE = "POST-FREEZE %s (descriptive): " % ADDENDUM_LABEL
ADDENDUM_METRICS = OrderedDict([
    ("X01", "paired_auto_closed_sensitivity"), ("X02", "three_state_tool_verdict_reading"),
    ("X03", "dirty_composition"), ("X04", "statically_clean_but_incorrect"), ("X05", "iterations_to_clean"),
    ("X06", "joint_parEval_heldout_transitions")])
ESTIMATE_FIELDS = ("ci_degenerate", "p_resolution", "p_holm_resolution")
DEGENERATE_NOTE = "degenerate percentile interval (zero width): every supporting cluster has the same value"
CLEAN_STOPS = ("stopped_clean", "stopped_tests_pass")          # X05 (checked against the addendum text)
X04_STATES = (CLEAN_COMPLETE, NO_FINDING_INCOMPLETE)


def _refuse(message, *args):
    raise core.AnalysisRefused(message % args if args else message)


def finding_families(methodology):
    """The frozen finding-class vocabulary (finding_rules.families, the
    classes classify_finding returns), parsed from the methodology text;
    a text without exactly one '->' list of identifiers refuses."""
    text = methodology["finding_rules"].get("families") or ""
    parts = text.split("->")
    if len(parts) != 2:
        _refuse("the methodology does not state one finding-family list")
    families = tuple(f.strip() for f in parts[1].split(","))
    if not families or len(set(families)) != len(families) or \
            not all(re.match(r"^[a-z][a-z_]*$", f) for f in families):
        _refuse("the methodology finding-family list is not a list of class identifiers")
    return families


def addendum_settings(methodology, addendum):
    """The post-freeze addendum that X01-X06 implement (fail closed): its
    schema/status, bound to THIS frozen methodology (canonical sha256),
    declaring exactly X01-X06 under their names and the three estimate
    fields. The top-N of X03 is read from its text (one '<n> check ids'
    phrase) and the vocabulary the definitions use (the tool-verdict states
    of normalize.VERDICT_STATES, the clean stops, the X04 states, the
    auto-closed flag) must be the words of its text - a reworded addendum
    refuses instead of silently meaning something else."""
    if not isinstance(addendum, dict):
        _refuse("the addendum is not a document")
    if addendum.get("schema_version") != core.ADDENDUM_SCHEMA or addendum.get("status") != core.ADDENDUM_STATUS:
        _refuse("not a %s addendum with status %s", core.ADDENDUM_SCHEMA, core.ADDENDUM_STATUS)
    if addendum.get("addendum_id") != "%s.%s" % (core.ANALYSIS_ID, ADDENDUM_LABEL):
        _refuse("the addendum is not %s.%s", core.ANALYSIS_ID, ADDENDUM_LABEL)
    if (addendum.get("amends") or {}).get("methodology_canonical_sha256") != canonical_sha256(methodology):
        _refuse("the addendum amends another methodology than the frozen one")
    declared = OrderedDict((m.get("id"), m) for m in addendum.get("metrics") or [])
    if [(k, m.get("name")) for k, m in declared.items()] != list(ADDENDUM_METRICS.items()):
        _refuse("the addendum metrics are not %s", ", ".join("%s %s" % kv for kv in ADDENDUM_METRICS.items()))
    if set(declared) & set(core.metric_ids(methodology)):
        _refuse("addendum metric ids collide with frozen ids")
    if tuple(f.get("field") for f in addendum.get("estimate_fields") or []) != ESTIMATE_FIELDS:
        _refuse("the addendum estimate fields are not %s", ", ".join(ESTIMATE_FIELDS))
    tops = re.findall(r"\bthe ([0-9]+) check ids\b", declared["X03"].get("meaning") or "")
    if len(tops) != 1 or int(tops[0]) < 1:
        _refuse("the addendum does not state one X03 check-id count")
    verdict_states = tuple(normalize.VERDICT_STATES)
    if not verdict_states or not set(verdict_states) <= set(core.TOOL_STATES) - set(core.INAPPLICABLE_STATES):
        _refuse("normalize.VERDICT_STATES is not a set of analysis states")
    if not set(CLEAN_STOPS) <= set(core.TERMINAL_STATUSES) or not set(X04_STATES) <= set(core.THREE_STATE):
        _refuse("the X04/X05 vocabulary is not the frozen one")
    words = (("X01", ("clean_auto_closed",)), ("X02", (" or ".join(verdict_states),)), ("X04", X04_STATES),
             ("X05", (" or ".join(CLEAN_STOPS),)))
    for metric, needed in words:
        text = declared[metric].get("meaning") or ""
        missing = [w for w in needed if w not in text]
        if missing:
            _refuse("the addendum %s meaning does not use %s", metric, missing)
    return OrderedDict([("ids", tuple(declared)), ("top_checks", int(tops[0])), ("verdict_states", verdict_states)])


# -- estimates ---------------------------------------------------------------------------------

def make_strata(pairs):
    """Canonical strata: an OrderedDict in STRATA_ORDER (unknown or
    contradictory keys refuse)."""
    values = OrderedDict()
    for key, value in pairs:
        if key not in STRATA_ORDER:
            _refuse("unknown strata key %r", key)
        if key in values and values[key] != value:
            _refuse("contradictory strata %r", key)
        values[key] = value
    return OrderedDict((key, values[key]) for key in STRATA_ORDER if key in values)


def estimate(metric_id, population, block, strata, numerator=None, denominator=None, value=None, note=None,
             statistic="share", post_freeze=False):
    """An Estimate with every contract key (ci_degenerate is set when the
    estimate is stored, the resolutions by the Holm step)."""
    return OrderedDict([
        ("metric_id", metric_id), ("population", population), ("block", block), ("strata", make_strata(strata)),
        ("numerator", numerator), ("denominator", denominator), ("value", value),
        ("ci_low", None), ("ci_high", None), ("ci_method", None), ("replicates", None),
        ("p_value", None), ("p_holm", None), ("reject_holm", None), ("note", note), ("statistic", statistic),
        ("post_freeze", bool(post_freeze)), ("ci_degenerate", None), ("p_resolution", None),
        ("p_holm_resolution", None)])


def sort_key(est):
    return (est["metric_id"], est["population"], est["block"],
            json.dumps(est["strata"], sort_keys=True, separators=(",", ":")))


def _ratio(numerator, denominator):
    return None if denominator == 0 else numerator / denominator


def _notes(*notes):
    kept = [n for n in notes if n]
    return "; ".join(kept) if kept else None


class _Agg(object):
    """(metric, population, block, strata) -> {cluster: [num, den]} plus
    the count of units an exclusion rule removed."""

    def __init__(self):
        self.sums = OrderedDict()
        self.excluded = Counter()

    def add(self, key, cluster, num, den, excluded):
        bucket = self.sums.get(key)
        if bucket is None:
            bucket = self.sums[key] = {}
        pair = bucket.get(cluster)
        if pair is None:
            bucket[cluster] = [num, den]
        else:
            pair[0] += num
            pair[1] += den
        if excluded:
            self.excluded[key] += excluded


def _keys(unit, fixed, strata_sets):
    for keys in strata_sets:
        strata = fixed + tuple((key, unit[key]) for key in keys)
        yield unit["block"], strata
        yield COMPOSITE, strata


# -- definitions shared with validate ------------------------------------------------------------

def three_state(entries, finding_states=None):
    """finding_rules.analysis_verdict_three_state over tool entry rows of one
    stage: only APPLICABLE tools count; a gap without a finding is never
    clean. finding_states None is the frozen rule (a reported blocking finding
    in any entry state); a tuple of states (X02: normalize.VERDICT_STATES)
    counts only the findings of entries in those states."""
    applicable = [e for e in entries if e["applicable"]]
    if any(e["num_reported_blocking"] > 0 for e in applicable
           if finding_states is None or e["state"] in finding_states):
        return DIRTY
    if all(e["state"] == COMPLETED for e in applicable):
        return CLEAN_COMPLETE
    if any(e["state"] in core.GAP_STATES for e in applicable):
        return NO_FINDING_INCOMPLETE
    _refuse("applicable tool in a non-analysis state: %s", sorted(set(e["state"] for e in applicable)))


def _check_vocabulary(methodology):
    """The words the definitions use must be the frozen vocabularies."""
    vocab = methodology["state_vocabularies"]
    checks = [
        (PASS in core.CORRECTNESS_VERDICTS and BASELINE_INCOMPATIBLE in core.CORRECTNESS_EXCLUDED, "verdicts"),
        (list(vocab["correctness_verdicts"]) == list(core.CORRECTNESS_VERDICTS), "correctness_verdicts"),
        (list(vocab["tool_states"]) == list(core.TOOL_STATES), "tool_states"),
        (list(vocab["analysis_gap_states"]) == list(core.GAP_STATES), "gap states"),
        (list(vocab["enhanced_statuses"]) == list(core.ENHANCED_STATUSES), "enhanced statuses"),
        (list(vocab["enhanced_gated"]) == list(core.ENHANCED_GATED), "enhanced gated"),
        (list(vocab["terminal_statuses"]) == list(core.TERMINAL_STATUSES), "terminal statuses"),
        (STOPPED_BUDGET in core.TERMINAL_STATUSES and STOPPED_ANALYSIS_INCOMPLETE in core.NON_MODEL_TERMINAL,
         "R07/R08 statuses"),
        (tuple(KIND_COLUMNS) == core.FINDING_KINDS, "finding kinds"),
        (set(ENH_STATUS_COLUMNS) == set(core.ENHANCED_STATUSES) - set(core.ENHANCED_GATED), "enh columns"),
        (COMPLETED in core.TOOL_STATES and TIMEOUT in core.GAP_STATES, "COMPLETED/TIMEOUT"),
        (list(methodology["strata"]["variant"]) == list(core.VARIANTS), "variants"),
        (list(methodology["strata"]["execution_model"]) == list(core.EXECUTION_MODELS), "execution models"),
        (list(methodology["strata"]["iteration"]) == list(range(core.MAX_ITERATIONS + 1)), "iterations"),
    ]
    by_id = OrderedDict((m["id"], m) for m in methodology["metrics"])
    f06 = by_id.get("F06", {}).get("meaning", "")
    checks.append((all(pair[5] in f06 for pair in F06_PAIRS), "F06 predefined pairs"))
    families = set(finding_families(methodology))
    checks.append((all(set(pair[2]) <= families for pair in F06_PAIRS), "F06 classes in the finding families"))
    c05 = by_id.get("C05", {}).get("meaning", "")
    checks.append(("1,000,000" in c05 and "per 100 " in c05, "C05 scales"))
    for ok, what in checks:
        if not ok:
            _refuse("the frozen methodology/core vocabulary differs from the metric definitions: %s", what)


# -- cohorts -----------------------------------------------------------------------------------------

def cohorts(dataset):
    """BASE / STEP / FINAL cohorts from the normalized tables (fail closed).

    Returns OrderedDict: cells (cell_id -> base_cells row), clusters
    (benchmark -> block), artifacts (artifact_id -> row), base (cell_id ->
    iteration-0 artifact), candidates (artifact_id -> repair candidate),
    trajectories ((cell_id, variant) -> row), step (variant -> k -> cell_id
    -> artifact), final (variant -> cell_id -> artifact)."""
    cells = OrderedDict()
    clusters = OrderedDict()
    for row in sorted(dataset.rows("base_cells"), key=lambda r: r["cell_id"]):
        cid = row["cell_id"]
        if cid in cells:
            _refuse("duplicate base cell %s", cid)
        if row["block"] not in core.BLOCKS or row["execution_model"] not in core.EXECUTION_MODELS:
            _refuse("foreign block/execution model in base cell %s", cid)
        if cid != core.cell_id(row["block"], row["model_id"], row["sample_id"]):
            _refuse("base cell id does not follow core.cell_id: %s", cid)
        if row["family"] != core.family_of(row["benchmark"]):
            _refuse("family of %s is not the benchmark's", cid)
        if bool(row["bl01"]) != (row["benchmark"] == core.BL01_BENCHMARK):
            _refuse("bl01 flag of %s contradicts its benchmark", cid)
        if row["base_run"] != core.BLOCK_BASE_RUN[row["block"]]:
            _refuse("base cell %s not from its block's base run", cid)
        if clusters.setdefault(row["benchmark"], row["block"]) != row["block"]:
            _refuse("benchmark %s occurs in two blocks", row["benchmark"])
        cells[cid] = row
    if not cells:
        _refuse("no base cells")
    clusters = OrderedDict((b, clusters[b]) for b in sorted(clusters))

    artifacts = OrderedDict()
    base = OrderedDict()
    candidates = OrderedDict()
    for row in sorted(dataset.rows("artifacts"), key=lambda r: r["artifact_id"]):
        aid = row["artifact_id"]
        if aid in artifacts:
            _refuse("duplicate artifact %s", aid)
        cell = cells.get(row["cell_id"])
        if cell is None:
            _refuse("artifact %s without a base cell", aid)
        for key in ("block", "model_id", "benchmark", "family", "execution_model", "sample_id"):
            if row[key] != cell[key]:
                _refuse("artifact %s disagrees with its cell on %s", aid, key)
        if row["source_run"] in core.EXCLUDED_RUNS:
            _refuse("artifact %s from an excluded run", aid)
        if aid != core.artifact_id(row["block"], row["model_id"], row["source_run"], row["sample_id"]):
            _refuse("artifact id does not follow core.artifact_id: %s", aid)
        if row["correctness_verdict"] not in core.CORRECTNESS_VERDICTS:
            _refuse("unknown correctness verdict of %s", aid)
        iteration = row["iteration"]
        if isinstance(iteration, bool) or not isinstance(iteration, int) or not 0 <= iteration <= core.MAX_ITERATIONS:
            _refuse("artifact %s iteration outside 0..%d", aid, core.MAX_ITERATIONS)
        if iteration == 0:
            if row["variant"] != "" or row["cell_id"] in base or row["source_run"] != cell["base_run"]:
                _refuse("base artifact %s with a variant, a foreign run or a second base artifact", aid)
            base[row["cell_id"]] = row
        else:
            if row["variant"] not in core.VARIANTS:
                _refuse("repair candidate %s with an unknown variant", aid)
            candidates[aid] = row
        artifacts[aid] = row
    missing = [cid for cid in cells if cid not in base]
    if missing:
        _refuse("base cells without a base artifact: %s", missing[:3])
    base = OrderedDict((cid, base[cid]) for cid in cells)

    trajectories = OrderedDict()
    step = OrderedDict((v, OrderedDict((k, OrderedDict()) for k in range(core.MAX_ITERATIONS + 1)))
                       for v in core.VARIANTS)
    final = OrderedDict((v, OrderedDict()) for v in core.VARIANTS)
    referenced = Counter()
    for row in sorted(dataset.rows("trajectories"), key=lambda r: r["trajectory_id"]):
        cid, variant = row["cell_id"], row["variant"]
        cell = cells.get(cid)
        if cell is None or variant not in core.VARIANTS:
            _refuse("trajectory %s of an unknown cell or variant", row["trajectory_id"])
        if (cid, variant) in trajectories or row["trajectory_id"] != core.trajectory_id(cid, variant):
            _refuse("duplicate or misnamed trajectory %s", row["trajectory_id"])
        if row["block"] != cell["block"] or row["model_id"] != cell["model_id"]:
            _refuse("trajectory %s disagrees with its cell", row["trajectory_id"])
        last = row["final_iteration"]
        if isinstance(last, bool) or not isinstance(last, int) or not 0 <= last <= core.MAX_ITERATIONS:
            _refuse("trajectory %s final iteration outside 0..%d", row["trajectory_id"], core.MAX_ITERATIONS)
        if row["terminal_status"] not in core.TERMINAL_STATUSES:
            _refuse("trajectory %s has a non-terminal status", row["trajectory_id"])
        ids = [row["artifact_iter%d" % k] for k in range(core.MAX_ITERATIONS + 1)]
        for k, aid in enumerate(ids):
            status = row["status_iter%d" % k]
            if k > last:
                if aid != "" or status != "":
                    _refuse("trajectory %s references iteration %d beyond its final iteration", row["trajectory_id"], k)
                continue
            if status != (row["terminal_status"] if k == last else "active"):
                _refuse("trajectory %s status history is not active..terminal", row["trajectory_id"])
            artifact = artifacts.get(aid)
            if artifact is None or artifact["cell_id"] != cid or artifact["iteration"] != k:
                _refuse("trajectory %s iteration %d artifact missing or foreign", row["trajectory_id"], k)
            if k == 0 and aid != base[cid]["artifact_id"]:
                _refuse("trajectory %s does not start at the base artifact", row["trajectory_id"])
            if k >= 1:
                if artifact["variant"] != variant:
                    _refuse("trajectory %s iteration %d artifact of another variant", row["trajectory_id"], k)
                referenced[aid] += 1
        if row["final_artifact"] != ids[last]:
            _refuse("trajectory %s final_artifact is not artifact_iter%d", row["trajectory_id"], last)
        trajectories[(cid, variant)] = row
        for k in range(core.MAX_ITERATIONS + 1):
            step[variant][k][cid] = artifacts[ids[min(k, last)]]
        final[variant][cid] = artifacts[ids[last]]
    missing = [(cid, v) for cid in cells for v in core.VARIANTS if (cid, v) not in trajectories]
    if missing:
        _refuse("base cells without a trajectory: %s", missing[:3])
    if set(referenced) != set(candidates) or any(n != 1 for n in referenced.values()):
        _refuse("repair candidates and trajectory references differ")
    for v in core.VARIANTS:
        for k in range(core.MAX_ITERATIONS + 1):
            step[v][k] = OrderedDict((cid, step[v][k][cid]) for cid in cells)
        final[v] = OrderedDict((cid, final[v][cid]) for cid in cells)
        if any(final[v][cid] is not step[v][core.MAX_ITERATIONS][cid] for cid in cells):
            _refuse("FINAL[%s] differs from STEP[%s][%d]", v, v, core.MAX_ITERATIONS)
    trajectories = OrderedDict(((cid, v), trajectories[(cid, v)]) for cid in cells for v in core.VARIANTS)
    return OrderedDict([("cells", cells), ("clusters", clusters), ("artifacts", artifacts), ("base", base),
                        ("candidates", candidates), ("trajectories", trajectories), ("step", step),
                        ("final", final)])


def _bootstrap(given, clusters, settings, which, exploratory):
    """A shared ClusterBootstrap: an instance (must match the dataset's
    clusters and the frozen seed/confidence), a replicate count, or None
    (the methodology's count). A replicate count other than the
    methodology's (settings[which]) refuses unless `exploratory` (reading
    10): confirmatory p-values / Holm decisions and the published intervals
    rest on the frozen counts only."""
    expected = settings[which]
    if isinstance(given, stats.ClusterBootstrap):
        if list(given.cluster_strata.items()) != list(clusters.items()):
            _refuse("the given bootstrap was built over other clusters")
        if given.seed != settings["seed"] or given.confidence != settings["confidence"]:
            _refuse("the given bootstrap does not use the frozen seed/confidence")
        replicates = given.replicates
    else:
        replicates = expected if given is None else given
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
        _refuse("bootstrap replicates must be a positive integer")
    if replicates != expected and not exploratory:
        _refuse("%s: %d bootstrap replicates, the methodology fixes %d (pass exploratory=True for a "
                "non-confirmatory run)", which, replicates, expected)
    if isinstance(given, stats.ClusterBootstrap):
        return given
    return stats.ClusterBootstrap(clusters, replicates, settings["seed"], settings["confidence"])


# -- the computation ----------------------------------------------------------------------------

class _Builder(object):

    def __init__(self, dataset, methodology, bootstrap_primary, bootstrap_descriptive, exploratory=False,
                 primary_only=False, addendum=None):
        _check_vocabulary(methodology)
        self.methodology = methodology
        # compute_primary needs no addendum (the primary family is frozen); compute() always passes one
        self.addendum = addendum
        self.x = addendum_settings(methodology, addendum) if addendum is not None else None
        self.families = frozenset(finding_families(methodology))
        self.settings = stats.bootstrap_settings(methodology)
        self.dataset = dataset
        self.co = cohorts(dataset)
        clusters = self.co["clusters"]
        self.exploratory = bool(exploratory)
        self.primary = _bootstrap(bootstrap_primary, clusters, self.settings, "replicates_primary", exploratory)
        # compute_primary never emits a descriptive estimate: its descriptive bootstrap is a 1-replicate stub
        self.descriptive = _bootstrap(bootstrap_descriptive, clusters, self.settings, "replicates_descriptive",
                                      exploratory or primary_only)
        self.sa1 = None                  # the SA1 bootstrap (reading 11), built by _repair
        self.out = OrderedDict()
        self._cache = {}
        self._prepare_entries()
        self._prepare_findings()
        self._check_derived()
        self._prepare_enhanced()
        self._prepare_generations()
        self._prepare_paired()

    # ---- integrity / derived facts -------------------------------------------------------------

    def _prepare_entries(self):
        allowed = OrderedDict([("static", core.STATIC_TOOLS), ("dynamic", core.DYNAMIC_TOOLS)])
        entries = OrderedDict((aid, {}) for aid in self.co["artifacts"])
        seen = OrderedDict((stage, set()) for stage in allowed)
        applicability = {}
        for row in self.dataset.rows("tool_entries"):
            stage, tool, aid = row["stage"], row["tool"], row["artifact_id"]
            if stage not in allowed or tool not in allowed[stage]:
                _refuse("unknown tool entry %s/%s", stage, tool)
            if aid not in entries:
                _refuse("tool entry of an unknown artifact %s", aid)
            if tool in entries[aid]:
                _refuse("duplicate tool entry %s for %s", tool, aid)
            if row["state"] not in core.TOOL_STATES:
                _refuse("unknown tool state %r", row["state"])
            if bool(row["applicable"]) != (row["state"] not in core.INAPPLICABLE_STATES):
                _refuse("applicability of %s on %s contradicts its state %s", tool, aid, row["state"])
            counts = [row[c] for c in KIND_COLUMNS.values()]
            if any(isinstance(c, bool) or not isinstance(c, int) or c < 0 for c in counts + [row["num_findings"]]) \
                    or sum(counts) != row["num_findings"]:
                _refuse("finding counts of %s on %s are inconsistent", tool, aid)
            em = self.co["artifacts"][aid]["execution_model"]
            if applicability.setdefault((tool, em), bool(row["applicable"])) != bool(row["applicable"]):
                _refuse("applicability of %s is not uniform on %s", tool, em)
            entries[aid][tool] = row
            seen[stage].add(tool)
        # the universe is the FROZEN tool list, not whatever tools occur (reading 9)
        missing = [t for stage, tools in allowed.items() for t in tools if t not in seen[stage]]
        if missing:
            _refuse("no tool entry of the frozen tool(s) %s (an absent entry for an applicable tool fails closed)",
                    missing)
        self.tools = OrderedDict((stage, tuple(tools)) for stage, tools in allowed.items())
        universe = set(STAGE_OF)
        for aid, by_tool in entries.items():
            if set(by_tool) != universe:
                _refuse("artifact %s lacks tool entries %s", aid, sorted(universe - set(by_tool))[:3])
        self._check_scope(applicability)
        self.entries = entries
        self.all_tools = self.tools["static"] + self.tools["dynamic"]

    def _check_scope(self, applicability):
        """Observed applicability per (tool, execution model) == the frozen
        tool scope the normalizer recorded (provenance tool_scope: stage ->
        tool -> execution models). Synthetic datasets without the record
        skip this cross-check; the binding rules above apply regardless."""
        scope = self.dataset.provenance.get("tool_scope")
        if scope is None:
            return
        for stage, tools in self.tools.items():
            recorded = scope.get(stage) if isinstance(scope, dict) else None
            if not isinstance(recorded, dict) or set(recorded) != set(tools):
                _refuse("provenance tool_scope of stage %s differs from the frozen tools", stage)
            for tool in tools:
                models = recorded[tool]
                if not isinstance(models, (list, tuple)) or not set(models) <= set(core.EXECUTION_MODELS):
                    _refuse("provenance tool_scope of %s is not a list of execution models", tool)
        for (tool, em), applicable in sorted(applicability.items()):
            if applicable != (em in scope[STAGE_OF[tool]][tool]):
                _refuse("applicability of %s on %s contradicts the frozen tool scope", tool, em)

    def _prepare_findings(self):
        per_artifact = OrderedDict((aid, Counter()) for aid in self.co["artifacts"])
        kinds = Counter()
        blocking = {}
        checks = {}
        for row in self.dataset.rows("findings"):
            aid, tool, kind = row["artifact_id"], row["tool"], row["kind"]
            entry = self.entries.get(aid, {}).get(tool)
            if entry is None or entry["stage"] != row["stage"]:
                _refuse("finding without a tool entry: %s/%s", aid, tool)
            if kind not in KIND_COLUMNS:
                _refuse("finding of %s/%s with an unknown kind %r", aid, tool, kind)
            if row["family"] not in self.families:
                _refuse("finding of %s/%s with a family %r outside the frozen class vocabulary", aid, tool,
                        row["family"])
            if not entry["applicable"]:
                _refuse("finding of an inapplicable tool %s on %s", tool, aid)
            per_artifact[aid][(tool, row["family"], kind)] += 1
            kinds[(aid, tool, kind)] += 1
            if kind == "reported_blocking":
                blocking.setdefault(aid, {}).setdefault(tool, set()).add(row["family"])
                # check ids are validated by X03, their only reader (the frozen metrics never read them)
                checks.setdefault(aid, Counter())[(tool, row["check_id"])] += 1
        for aid, by_tool in self.entries.items():
            for tool, entry in by_tool.items():
                for kind, column in KIND_COLUMNS.items():
                    if kinds.get((aid, tool, kind), 0) != entry[column]:
                        _refuse("findings of %s/%s (%s) disagree with the entry count", aid, tool, kind)
        self.finding_counts = per_artifact
        self.blocking_families = blocking
        self.blocking_checks = checks          # artifact -> (tool, check_id) -> reported blocking findings

    def _check_derived(self):
        analysis = [t for t in self.tools["static"] if t in core.STATIC_ANALYSIS_TOOLS]
        for aid, a in self.co["artifacts"].items():
            e = self.entries[aid]
            static = [e[t] for t in analysis]
            dynamic = [e[t] for t in self.tools["dynamic"]]
            derived = OrderedDict([
                ("static_three_state", three_state(static)),
                ("dynamic_three_state", three_state(dynamic)),
                ("compile_error", e["compiler"]["num_reported_blocking"] > 0),
                ("static_analysis_complete", all(x["state"] == COMPLETED for x in static if x["applicable"])),
                ("dynamic_analysis_complete", all(x["state"] == COMPLETED for x in dynamic if x["applicable"])),
                ("low_confidence_any", any(x["num_low_confidence"] > 0 for x in e.values())),
                ("clean_any", any(a["clean_" + f] for f in core.CLEANING_FLAGS if f != "used_fence")),
                ("clean_any_including_fence", any(a["clean_" + f] for f in core.CLEANING_FLAGS)),
            ])
            for column, value in derived.items():
                if (a[column] if isinstance(value, str) else bool(a[column])) != value:
                    _refuse("artifact %s: %s contradicts the recomputed definition", aid, column)
            if a["correctness_verdict"] == PASS and not a["build_ok"]:
                _refuse("artifact %s passes without a build", aid)

    def _prepare_enhanced(self):
        artifacts = self.co["artifacts"]
        status = OrderedDict((aid, Counter()) for aid in artifacts)
        specs = OrderedDict((aid, []) for aid in artifacts)
        gates = {}
        seen = set()
        for row in self.dataset.rows("enhanced_pairs"):
            aid, key = row["artifact_id"], row["spec_key"]
            a = artifacts.get(aid)
            if a is None:
                _refuse("enhanced pair of an unknown artifact %s", aid)
            if row["status"] not in core.ENHANCED_STATUSES:
                _refuse("unknown enhanced status %r", row["status"])
            if bool(row["gated"]) != (row["status"] in core.ENHANCED_GATED):
                _refuse("gate flag of %s/%s contradicts its status", aid, key)
            if (aid, key) in seen:
                _refuse("duplicate enhanced pair %s/%s", aid, key)
            seen.add((aid, key))
            group = (a["block"], a["benchmark"], key, a["execution_model"])
            if gates.setdefault(group, bool(row["gated"])) != bool(row["gated"]):
                _refuse("mixed gate decision in group %s", group)
            status[aid][row["status"]] += 1
            specs[aid].append(key)
        for aid, a in artifacts.items():
            counts = status[aid]
            pairs = sum(counts.values())
            gated = sum(counts[s] for s in core.ENHANCED_GATED)
            valid = pairs - gated
            expected = OrderedDict([("enh_pairs", pairs), ("enh_gated", gated), ("enh_valid", valid)])
            for s, column in ENH_STATUS_COLUMNS.items():
                expected[column] = counts[s]
            expected["enh_all_pass"] = None if valid == 0 else int(counts[PASS] == valid)
            for column, value in expected.items():
                if a[column] != value:
                    _refuse("artifact %s: %s disagrees with its enhanced pairs", aid, column)
        self.pair_status = status
        self.pair_specs = specs
        self.gates = gates

    def _prepare_generations(self):
        artifacts = self.co["artifacts"]
        generations = OrderedDict()
        for row in self.dataset.rows("generations"):
            aid = row["artifact_id"]
            a = artifacts.get(aid)
            if a is None or aid in generations:
                _refuse("generation record of an unknown or duplicated artifact %s", aid)
            if row["kind"] != ("base" if a["iteration"] == 0 else "repair"):
                _refuse("generation kind of %s contradicts its iteration", aid)
            if bool(row["success"]) != bool(a["generation_success"]):
                _refuse("generation success of %s contradicts the artifact", aid)
            for field in TOKEN_FIELDS + ("request_chars",):
                value = row[field]
                if value is None and field in REQUIRED_TOKENS:
                    _refuse("generation %s without %s (only reasoning_tokens may be null)", aid, field)
                if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                    _refuse("invalid %s of %s", field, aid)
            if row["timing_mode"] != "direct" and row["duration_seconds"] is not None:
                _refuse("non-direct generation %s carries a duration", aid)
            generations[aid] = row
        missing = [aid for aid in artifacts if aid not in generations]
        if missing:
            _refuse("artifacts without a generation record: %s", missing[:3])
        self.generations = generations

    def _cell_artifacts(self, cid):
        out = [self.co["base"][cid]]
        for v in core.VARIANTS:
            out.extend(self.co["step"][v][k][cid] for k in range(1, core.MAX_ITERATIONS + 1))
        return out

    def _prepare_paired(self):
        """Paired cohorts per binary endpoint (conservative readings 1, 2)."""
        self.eligible = OrderedDict([("Q06", OrderedDict()), ("E02", OrderedDict())])
        for cid in self.co["cells"]:
            arts = self._cell_artifacts(cid)
            self.eligible["Q06"][cid] = all(a["correctness_verdict"] != BASELINE_INCOMPATIBLE for a in arts)
            if len(set(a["enh_valid"] for a in arts)) != 1:
                _refuse("valid enhanced pair counts differ within cell %s (gates must be spec-level)", cid)
            self.eligible["E02"][cid] = self.co["base"][cid]["enh_valid"] > 0

    # ---- primitives --------------------------------------------------------------------------------

    def _put(self, est):
        """Store a finished estimate: the post_freeze flag must match the
        metric id (an addendum note starts with the post-freeze label), and
        the zero-width flag is derived from the final bounds (one place for
        every estimate path)."""
        key = sort_key(est)
        if key in self.out:
            _refuse("duplicate estimate %s", key)
        if not isinstance(est["post_freeze"], bool) or est["post_freeze"] != (est["metric_id"] in ADDENDUM_METRICS):
            _refuse("post_freeze flag of %s contradicts its metric id", key)
        if est["post_freeze"] and not (est["note"] or "").startswith(POST_FREEZE_NOTE):
            _refuse("post-freeze estimate %s without the post-freeze label", key)
        est["ci_degenerate"] = stats.ci_degenerate(est["ci_low"], est["ci_high"])
        if est["ci_degenerate"]:
            est["note"] = _notes(est["note"], DEGENERATE_NOTE)
        self.out[key] = est

    def _add(self, agg, metric, population, unit, fixed, strata_sets, items):
        cluster = unit["benchmark"]
        for block, strata in _keys(unit, fixed, strata_sets):
            for pairs, num, den, excluded in items:
                agg.add((metric, population, block, strata + pairs), cluster, num, den, excluded)

    def _boot(self, boot, kind, per_cluster, reference=None):
        def token(values):
            return tuple(sorted((c, tuple(v)) for c, v in values.items() if v[0] or v[1]))
        key = (id(boot), kind, token(per_cluster), token(reference) if reference is not None else None)
        if key not in self._cache:
            data = OrderedDict((c, tuple(v)) for c, v in per_cluster.items())
            if kind == "ratio":
                self._cache[key] = boot.ratio(data)
            elif kind == "difference":
                self._cache[key] = boot.difference(data)
            else:
                ref = OrderedDict((c, tuple(v)) for c, v in reference.items())
                self._cache[key] = boot.ratio_difference(data, ref)
        return self._cache[key]

    def _apply(self, est, res, boot):
        est["numerator"], est["denominator"], est["value"] = res["numerator"], res["denominator"], res["value"]
        if res["value"] is not None and res["ci_low"] is not None:
            est["ci_low"], est["ci_high"] = res["ci_low"], res["ci_high"]
            est["ci_method"] = stats.CI_METHOD
            est["replicates"] = res["replicates"]
        if res["value"] is not None and res.get("ci_note"):
            est["note"] = _notes(est["note"], res["ci_note"])
        if res["degenerate"]:
            est["note"] = _notes(est["note"], "%d of %d bootstrap replicates skipped (denominator 0)"
                                 % (res["skipped"], boot.replicates))
        expected = self.settings["replicates_primary" if boot is self.primary else "replicates_descriptive"]
        if boot.replicates != expected:
            est["note"] = _notes(est["note"], "EXPLORATORY: %d bootstrap replicates (methodology %d), not "
                                 "confirmatory" % (boot.replicates, expected))
        return est

    def _emit(self, agg, boot=None, ci_when=None, note=None, excluded_reason=None, statistic="share",
              kind="ratio", primary_when=None, post_freeze=False, extras=None):
        """One estimate per aggregation key. `note` may be a callable of the
        key; `extras(est, key)` adds metric-specific keys before storing."""
        for key, per_cluster in agg.sums.items():
            metric, population, block, strata = key
            excluded = agg.excluded.get(key, 0)
            notes = [note(key) if callable(note) else note]
            if excluded_reason is not None and excluded:
                notes.append("excluded: %d %s" % (excluded, excluded_reason))
            est = estimate(metric, population, block, strata, note=_notes(*notes), statistic=statistic,
                           post_freeze=post_freeze)
            use = boot
            if primary_when is not None and primary_when(block, strata):
                use = self.primary
            elif ci_when is not None and not ci_when(strata):
                use = None
            if use is None:
                num = sum(v[0] for v in per_cluster.values())
                den = sum(v[1] for v in per_cluster.values())
                est["numerator"], est["denominator"], est["value"] = num, den, _ratio(num, den)
            else:
                res = self._boot(use, kind, per_cluster)
                self._apply(est, res, use)
                if use is self.primary:
                    est["p_value"] = res["p_value"]
            if excluded_reason is not None:
                est["excluded"] = excluded
            if extras is not None:
                extras(est, key)
            self._put(est)

    def _rates(self, metric, population, units, fixed, strata_sets, items_fn, boot=None, ci_when=None, note=None,
               excluded_reason=None, statistic="share", post_freeze=False):
        agg = _Agg()
        for unit in units:
            self._add(agg, metric, population, unit, fixed, strata_sets, items_fn(unit))
        self._emit(agg, boot, ci_when, note, excluded_reason, statistic, post_freeze=post_freeze)

    def _paired_pops(self, steps=True):
        yield "BASE", (), self.co["base"]
        if steps:
            for v in core.VARIANTS:
                for k in range(core.MAX_ITERATIONS + 1):
                    yield "STEP", (("variant", v), ("step", k)), self.co["step"][v][k]
        for v in core.VARIANTS:
            yield "FINAL", (("variant", v),), self.co["final"][v]

    def _tool_pops(self):
        yield "BASE", (), self.co["base"]
        for v in core.VARIANTS:
            yield "FINAL", (("variant", v),), self.co["final"][v]
        yield "GENERATED", (), self.co["artifacts"]

    # ---- Q: generation / assembly / correctness ------------------------------------------------------

    @staticmethod
    def _q06(a):
        excluded = a["correctness_verdict"] == BASELINE_INCOMPATIBLE
        return [((), int(a["correctness_verdict"] == PASS), int(not excluded), int(excluded))]

    @staticmethod
    def _q07(a):
        excluded = a["correctness_verdict"] == BASELINE_INCOMPATIBLE
        built = bool(a["build_ok"]) and not excluded
        return [((), int(built and a["correctness_verdict"] == PASS), int(built), int(excluded))]

    @staticmethod
    def _q04(a):
        assembled = bool(a["assembled"])
        values = OrderedDict((f, a["clean_" + f]) for f in core.CLEANING_FLAGS)
        values["any"] = a["clean_any"]
        values["any_including_fence"] = a["clean_any_including_fence"]
        return [((("flag", f),), int(assembled and bool(values[f])), int(assembled), int(not assembled))
                for f in Q04_FLAGS]

    @staticmethod
    def _q08(a):
        return [((("verdict", v),), int(a["correctness_verdict"] == v), 1, 0) for v in core.CORRECTNESS_VERDICTS]

    def _quality(self):
        base = self.co["base"].values()
        generated = self.co["artifacts"].values()
        bi = "baseline_incompatible artifact(s)"
        simple = OrderedDict([
            ("Q01", lambda a: [((), int(bool(a["generation_success"])), 1, 0)]),
            ("Q02", lambda a: [((), int(bool(a["assembled"])), 1, 0)]),
            ("Q03", lambda a: [((), int(bool(a["generation_truncated"])), 1, 0)]),
        ])
        for metric, fn in simple.items():
            self._rates(metric, "BASE", base, (), BY_MEX, fn)
            self._rates(metric, "GENERATED", generated, (), BY_ITER, fn, note=DIAGNOSTIC)
        self._rates("Q04", "BASE", base, (), BY_MEX, self._q04, excluded_reason="unassembled artifact(s)")
        self._rates("Q04", "GENERATED", generated, (), BY_ITER, self._q04, note=DIAGNOSTIC,
                    excluded_reason="unassembled artifact(s)")
        q05 = lambda a: [((), int(bool(a["build_ok"])), 1, 0)]  # noqa: E731
        for population, fixed, units in self._paired_pops():
            self._rates("Q05", population, units.values(), fixed, BY_MEX if population == "BASE" else BY_ME, q05,
                        boot=self.descriptive)
            self._rates("Q06", population, units.values(), fixed, BY_MEXF, self._q06, boot=self.descriptive,
                        excluded_reason=bi)
        for metric, fn in (("Q05", q05), ("Q06", self._q06)):
            self._rates(metric, "GENERATED", generated, (), BY_ITER, fn, boot=self.descriptive, note=DIAGNOSTIC,
                        excluded_reason=None if metric == "Q05" else bi)
        for population, fixed, units in self._paired_pops(steps=False):
            strata = BY_MEX if population == "BASE" else BY_ME
            self._rates("Q07", population, units.values(), fixed, strata, self._q07, excluded_reason=bi)
            self._rates("Q08", population, units.values(), fixed, strata, self._q08)
        self._rates("Q07", "GENERATED", generated, (), BY_ITER, self._q07, note=DIAGNOSTIC, excluded_reason=bi)
        self._rates("Q08", "GENERATED", generated, (), BY_ITER, self._q08, note=DIAGNOSTIC)

        def q09(a):
            raw_clean = bool(a["assembled"]) and not a["clean_any_including_fence"]
            excluded = a["correctness_verdict"] == BASELINE_INCOMPATIBLE
            den = raw_clean and not excluded
            return [((), int(den and a["correctness_verdict"] == PASS), int(den), int(raw_clean and excluded))]
        self._rates("Q09", "BASE", base, (), BY_MEX, q09, note="raw-clean subset (no cleaning intervention)",
                    excluded_reason=bi)

        def q10(a):
            kept = not a["clean_auto_closed"]
            excluded = a["correctness_verdict"] == BASELINE_INCOMPATIBLE
            den = kept and not excluded
            return [((), int(den and a["correctness_verdict"] == PASS), int(den), int(kept and excluded))]
        for population, fixed, units in self._paired_pops(steps=False):
            self._rates("Q10", population, units.values(), fixed, BY_ME, q10, note="sensitivity SA2",
                        excluded_reason=bi)

    # ---- E: held-out enhanced tests ---------------------------------------------------------------------

    def _enhanced(self):
        generated = self.co["artifacts"].values()
        e01 = lambda a: [((), a["enh_pass"], a["enh_valid"], 0)]  # noqa: E731

        def e02(a):
            valid = a["enh_valid"] > 0
            return [((), int(valid and a["enh_all_pass"] == 1), int(valid), int(not valid))]
        none_valid = "artifact(s) without a valid pair (counted separately)"
        for population, fixed, units in self._paired_pops():
            self._rates("E01", "ENH_PAIRS(%s)" % population, units.values(), fixed, BY_MEXF, e01,
                        boot=self.descriptive)
            self._rates("E02", population, units.values(), fixed, BY_MEXF, e02, boot=self.descriptive,
                        excluded_reason=none_valid)
        self._rates("E01", "ENH_PAIRS(GENERATED)", generated, (), BY_ITER, e01, boot=self.descriptive,
                    note=DIAGNOSTIC)
        self._rates("E02", "GENERATED", generated, (), BY_ITER, e02, boot=self.descriptive, note=DIAGNOSTIC,
                    excluded_reason=none_valid)

        def e03(a):
            counts = self.pair_status[a["artifact_id"]]
            return [((("status", s),), counts[s], a["enh_pairs"], 0) for s in core.ENHANCED_STATUSES]
        e04 = lambda a: [((), a["enh_gated"], a["enh_pairs"], 0)]  # noqa: E731
        for population, units, strata, note in (("BASE", self.co["base"].values(), BY_MEX, None),
                                               ("GENERATED", generated, ALL, DIAGNOSTIC)):
            label = "ENH_PAIRS(%s)" % population
            self._rates("E03", label, units, (), ALL, e03, note=note)
            self._rates("E04", label, units, (), strata, e04, note=note)
            groups = OrderedDict((block, set()) for block in BLOCKS_ALL)
            for a in units:
                for key in self.pair_specs[a["artifact_id"]]:
                    group = (a["block"], a["benchmark"], key, a["execution_model"])
                    groups[a["block"]].add(group)
                    groups[COMPOSITE].add(group)
            for block, members in groups.items():
                est = self.out[sort_key(estimate("E04", label, block, ()))]
                est["groups"] = len(members)
                est["gated_groups"] = sum(1 for g in members if self.gates[g])

        def e05(a):
            den = a["correctness_verdict"] == PASS and a["enh_valid"] > 0
            return [((), int(den and a["enh_all_pass"] == 1), int(den), 0)]
        for population, fixed, units in self._paired_pops(steps=False):
            self._rates("E05", population, units.values(), fixed, BY_ME, e05)

    # ---- S / D: tool states and coverage --------------------------------------------------------------

    def _tool_states(self):
        stages = (("static", "S01", "S02", "S03", "static_analysis_complete"),
                  ("dynamic", "D01", "D02", "D03", "dynamic_analysis_complete"))
        for stage, m_state, m_cover, m_complete, column in stages:
            tools = self.tools[stage]

            def states(a, tools=tools):
                e = self.entries[a["artifact_id"]]
                return [((("tool", t), ("state", s)), int(e[t]["state"] == s), 1, 0)
                        for t in tools for s in core.TOOL_STATES]

            def cover(a, tools=tools):
                e = self.entries[a["artifact_id"]]
                return [((("tool", t),), int(bool(e[t]["applicable"]) and e[t]["state"] == COMPLETED),
                         int(bool(e[t]["applicable"])), 0) for t in tools]

            def complete(a, column=column):
                return [((), int(bool(a[column])), 1, 0)]
            for population, fixed, units in self._tool_pops():
                note = DIAGNOSTIC if population == "GENERATED" else None
                self._rates(m_state, population, units.values(), fixed, ALL, states, note=note)
                self._rates(m_cover, population, units.values(), fixed, BY_E, cover,
                            note=_notes(note, "denominator: artifacts to which the tool applies"))
                self._rates(m_complete, population, units.values(), fixed, BY_E, complete, note=note)

    # ---- F: verdicts, findings, agreement -------------------------------------------------------------

    def _verdicts(self):
        def three(column):
            return lambda a: [((("state", s),), int(a[column] == s), 1, 0) for s in core.THREE_STATE]
        dirty = lambda strata: ("state", DIRTY) in strata  # noqa: E731
        f03 = lambda a: [((), int(bool(a["compile_error"])), 1, 0)]  # noqa: E731
        f04 = lambda a: [((), int(bool(a["low_confidence_any"])), 1, 0)]  # noqa: E731
        for population, fixed, units in self._paired_pops():
            self._rates("F01", population, units.values(), fixed, BY_ME, three("static_three_state"),
                        boot=self.descriptive, ci_when=dirty)
            self._rates("F02", population, units.values(), fixed, BY_ME, three("dynamic_three_state"))
            self._rates("F03", population, units.values(), fixed, BY_ME, f03)
        for population, fixed, units in self._paired_pops(steps=False):
            self._rates("F04", population, units.values(), fixed, BY_ME, f04)

    def _findings(self):
        combos = set()
        for counter in self.finding_counts.values():
            combos.update(counter)
        order = {t: i for i, t in enumerate(self.all_tools)}
        kinds = {k: i for i, k in enumerate(core.FINDING_KINDS)}
        combos = sorted(combos, key=lambda c: (order[c[0]], c[1], kinds[c[2]]))
        for population, fixed, units in self._tool_pops():
            counts = Counter()
            with_finding = Counter()
            applicable = Counter()
            for a in units.values():
                blocks = (a["block"], COMPOSITE)
                e = self.entries[a["artifact_id"]]
                for tool in self.all_tools:
                    if e[tool]["applicable"]:
                        for block in blocks:
                            applicable[(block, tool)] += 1
                for combo, n in self.finding_counts[a["artifact_id"]].items():
                    for block in blocks:
                        counts[(block,) + combo] += n
                        with_finding[(block,) + combo] += 1
            note = DIAGNOSTIC if population == "GENERATED" else None
            for block in BLOCKS_ALL:
                for tool, family, kind in combos:
                    strata = fixed + (("tool", tool), ("family", family), ("kind", kind))
                    key = (block, tool, family, kind)
                    est = estimate("F05", population, block, strata + (("quantity", "findings"),),
                                   numerator=counts[key], statistic="count",
                                   note=_notes(note, "count per tool (never summed across tools)"))
                    self._put(est)
                    den = applicable[(block, tool)]
                    est = estimate("F05", population, block, strata + (("quantity", "artifacts_with_finding"),),
                                   numerator=with_finding[key], denominator=den, value=_ratio(with_finding[key], den),
                                   note=_notes(note, "denominator: artifacts to which the tool applies"))
                    self._put(est)

    def _agreement(self):
        for label, (first, second), classes, class_label, scope, _phrase in F06_PAIRS:
            if first not in self.all_tools or second not in self.all_tools:
                _refuse("F06 pair %s needs tools without entries", label)
            tables = OrderedDict((block, Counter()) for block in BLOCKS_ALL)
            wanted = set(classes)
            for aid, a in self.co["artifacts"].items():
                if a["execution_model"] not in scope:
                    continue
                e = self.entries[aid]
                if not all(e[t]["applicable"] and e[t]["state"] == COMPLETED for t in (first, second)):
                    continue
                families = self.blocking_families.get(aid, {})
                cell = (bool(families.get(first, set()) & wanted), bool(families.get(second, set()) & wanted))
                tables[a["block"]][cell] += 1
                tables[COMPOSITE][cell] += 1
            for block, table in tables.items():
                n11, n10 = table[(True, True)], table[(True, False)]
                n01, n00 = table[(False, True)], table[(False, False)]
                n = n11 + n10 + n01 + n00
                note = "both tools COMPLETED on %s artifacts; reported blocking findings only; descriptive" % (
                    "/".join(scope))
                if n == 0:
                    note = _notes(note, "not estimable (no artifact with both tools COMPLETED)")
                est = estimate("F06", "GENERATED", block, (("pair", label), ("class", class_label)),
                               numerator=n11 + n00, denominator=n, value=_ratio(n11 + n00, n), note=note,
                               statistic="agreement")
                est.update(OrderedDict([("n11", n11), ("n10", n10), ("n01", n01), ("n00", n00),
                                        ("positive_agreement", stats.positive_agreement(n11, n10, n01, n00)),
                                        ("kappa", stats.cohens_kappa(n11, n10, n01, n00))]))
                self._put(est)

    # ---- R: repair outcomes ----------------------------------------------------------------------------

    def _state(self, endpoint, a):
        if endpoint == "Q06":
            return "pass" if a["correctness_verdict"] == PASS else "not_pass"
        if endpoint == "E02":
            return "all_pass" if a["enh_all_pass"] == 1 else "not_all_pass"
        return a["static_three_state" if endpoint == "F01" else "dynamic_three_state"]

    @staticmethod
    def _y(endpoint, a):
        if endpoint == "Q06":
            return int(a["correctness_verdict"] == PASS)
        return int(a["enh_all_pass"] == 1)

    def _eligible(self, endpoint, cid):
        return self.eligible[endpoint][cid] if endpoint in self.eligible else True

    def _paired(self, cell_filter=None, fixed=(), r01=True, strata_rx=BY_MEF, strata_r05=BY_ME):
        aggs = OrderedDict((m, _Agg()) for m in ("R01", "R02", "R03", "R04", "R05"))
        cells = self.co["cells"]
        for cid, cell in cells.items():
            if cell_filter is not None and not cell_filter(cell):
                continue
            b = self.co["base"][cid]
            for endpoint, states in ENDPOINT_STATES.items():
                ok = self._eligible(endpoint, cid)
                ep = (("endpoint", endpoint),)
                if r01:
                    sb = self._state(endpoint, b)
                    for v in core.VARIANTS:
                        targets = [("FINAL", (("variant", v),), BY_ME, self.co["final"][v][cid])]
                        targets += [("STEP", (("variant", v), ("step", k)), ALL, self.co["step"][v][k][cid])
                                    for k in range(1, core.MAX_ITERATIONS + 1)]
                        for population, extra, strata, art in targets:
                            sf = self._state(endpoint, art)
                            items = [((("transition", "%s->%s" % (x, y)),), int(ok and (sb, sf) == (x, y)), int(ok),
                                      int(not ok)) for x in states for y in states]
                            self._add(aggs["R01"], "R01", population, cell, fixed + ep + extra, strata, items)
                if endpoint not in BINARY_ENDPOINTS:
                    continue
                yb = self._y(endpoint, b)
                ys = OrderedDict((v, self._y(endpoint, self.co["final"][v][cid])) for v in core.VARIANTS)
                for v, yf in ys.items():
                    extra = fixed + ep + (("variant", v),)
                    self._add(aggs["R02"], "R02", "FINAL", cell, extra, strata_rx,
                              [((), int(ok and yb == 0 and yf == 1), int(ok and yb == 0), int(not ok))])
                    self._add(aggs["R03"], "R03", "FINAL", cell, extra, strata_rx,
                              [((), int(ok and yb == 1 and yf == 0), int(ok and yb == 1), int(not ok))])
                    self._add(aggs["R04"], "R04", "FINAL", cell, extra, strata_rx,
                              [((), (yf - yb) if ok else 0, int(ok), int(not ok))])
                for v1, v2 in COMPARISONS:
                    extra = fixed + ep + (("comparison", "%s-%s" % (v1, v2)),)
                    self._add(aggs["R05"], "R05", "FINAL", cell, extra, strata_r05,
                              [((), (ys[v1] - ys[v2]) if ok else 0, int(ok), int(not ok))])
        return aggs

    def _repair(self):
        reason = "base cell(s) outside the paired cohort"
        aggs = self._paired()

        def primary(block, strata):
            keys = set(k for k, _ in strata)
            return block == COMPOSITE and keys in ({"endpoint", "variant"}, {"endpoint", "comparison"})
        self._emit(aggs["R01"], note="transition counts on the identical base-cell cohort", excluded_reason=reason)
        self._emit(aggs["R02"], boot=self.descriptive, excluded_reason=reason)
        self._emit(aggs["R03"], boot=self.descriptive, excluded_reason=reason)
        self._emit(aggs["R04"], boot=self.descriptive, excluded_reason=reason, statistic="difference",
                   kind="difference", primary_when=primary)
        self._emit(aggs["R05"], boot=self.descriptive, excluded_reason=reason, statistic="difference",
                   kind="difference", primary_when=primary)
        self._holm()
        # SA1: a re-analysis without the BL-01 benchmark - its own bootstrap over the remaining clusters (same seed
        # and replicate count), so the pilot stratum resamples its 11 remaining benchmarks (reading 11)
        sa1 = (("sensitivity", "SA1"),)
        note = "sensitivity SA1: without %s (bootstrap over the remaining benchmarks)" % core.BL01_BENCHMARK
        keep = lambda cell: not cell["bl01"]  # noqa: E731
        clusters = self.co["clusters"]
        if core.BL01_BENCHMARK in clusters:
            kept_clusters = OrderedDict((c, s) for c, s in clusters.items() if c != core.BL01_BENCHMARK)
            if not kept_clusters:
                _refuse("SA1 leaves no benchmark cluster")
            self.sa1 = stats.ClusterBootstrap(kept_clusters, self.descriptive.replicates, self.descriptive.seed,
                                              self.descriptive.confidence)
        else:
            self.sa1 = self.descriptive
        aggs = self._paired(cell_filter=keep, fixed=sa1, r01=False, strata_rx=ALL, strata_r05=ALL)
        self._emit(aggs["R02"], boot=self.sa1, note=note, excluded_reason=reason)
        self._emit(aggs["R04"], boot=self.sa1, note=note, excluded_reason=reason, statistic="difference",
                   kind="difference")
        self._emit(aggs["R05"], boot=self.sa1, note=note, excluded_reason=reason, statistic="difference",
                   kind="difference")
        for population, fixed, units in self._paired_pops(steps=False):
            kept = [a for a in units.values() if keep(self.co["cells"][a["cell_id"]])]
            self._rates("Q06", population, kept, fixed + sa1, ALL, self._q06, boot=self.sa1, note=note,
                        excluded_reason="baseline_incompatible artifact(s)")

    def primary_estimates(self):
        out = []
        for metric in ("R04", "R05"):
            for endpoint in BINARY_ENDPOINTS:
                labels = core.VARIANTS if metric == "R04" else ["%s-%s" % pair for pair in COMPARISONS]
                for label in labels:
                    strata = (("endpoint", endpoint), ("variant" if metric == "R04" else "comparison", label))
                    key = sort_key(estimate(metric, "FINAL", COMPOSITE, strata))
                    if key not in self.out:
                        _refuse("primary hypothesis %s %s %s was not computed", metric, endpoint, label)
                    out.append(self.out[key])
        return out

    def _holm(self):
        """Holm over the 12 primary hypotheses plus the addendum resolutions.
        The Holm input is in sort_key order, so ties of the step-down (and of
        the p_holm_resolution running maximum) are broken by sort_key (the
        adjusted values themselves do not depend on the tie order).
        p_resolution is 2 / replicates_primary, the DRAWN replicate count of
        the primary bootstrap (reading 13) - the rule tables.py and
        validate.py check; a hypothesis whose p-value rests on fewer usable
        replicates says so in its note."""
        family = self.primary_estimates()
        if len(family) != self.settings["primary_hypotheses"]:
            _refuse("the primary family has %d hypotheses, the methodology states %d", len(family),
                    self.settings["primary_hypotheses"])
        drawn = self.primary.replicates
        p_values = OrderedDict()
        resolutions = OrderedDict()
        for est in sorted(family, key=sort_key):
            if est["p_value"] is None:
                _refuse("primary hypothesis %s without a p-value (%s)", sort_key(est), est["note"])
            p_values[sort_key(est)] = est["p_value"]
            resolutions[sort_key(est)] = stats.p_resolution(drawn)
        adjusted = stats.holm(p_values, self.settings["alpha"])
        bounds = stats.holm_resolution(p_values, resolutions)
        for est in family:
            key = sort_key(est)
            est["p_holm"], est["reject_holm"] = adjusted[key]
            est["p_resolution"] = resolutions[key]
            est["p_holm_resolution"] = bounds[key]
            if est["replicates"] != drawn:
                est["note"] = _notes(est["note"], "p_resolution = 2 / %d drawn replicates (replicates_primary); the "
                                     "p-value rests on %d usable replicates, its smallest positive value is 2 / %d"
                                     % (drawn, est["replicates"], est["replicates"]))
            est["note"] = _notes(est["note"], "primary family (Holm over %d hypotheses, alpha %s)"
                                 % (len(family), self.settings["alpha"]))

    # ---- R06-R10: trajectories ------------------------------------------------------------------------

    def _trajectory_units(self):
        units = []
        for (cid, v), t in self.co["trajectories"].items():
            cell = self.co["cells"][cid]
            unit = OrderedDict((k, cell[k]) for k in ("block", "benchmark", "model_id", "execution_model", "family"))
            unit.update(OrderedDict([("cell_id", cid), ("variant", v), ("final_iteration", t["final_iteration"]),
                                     ("terminal_status", t["terminal_status"]),
                                     ("request_rounds", t["request_rounds"])]))
            units.append(unit)
        return units

    def _trajectories(self):
        units = self._trajectory_units()
        statuses = core.TERMINAL_STATUSES
        iterations = range(core.MAX_ITERATIONS + 1)
        aggs = OrderedDict((m, _Agg()) for m in ("R06", "R07", "R08", "R09", "R10"))
        for u in units:
            fixed = (("variant", u["variant"]),)
            status, last = u["terminal_status"], u["final_iteration"]
            self._add(aggs["R06"], "R06", "TRAJECTORIES", u, fixed, BY_ME,
                      [((("status", s),), int(status == s), 1, 0) for s in statuses])
            self._add(aggs["R06"], "R06", "TRAJECTORIES", u, fixed, ALL,
                      [((("status", s), ("iteration", i)), int(status == s and last == i), 1, 0)
                       for s in statuses for i in iterations])
            self._add(aggs["R07"], "R07", "TRAJECTORIES", u, fixed, BY_ME, [((), int(status == STOPPED_BUDGET), 1, 0)])
            self._add(aggs["R08"], "R08", "TRAJECTORIES", u, fixed, BY_ME,
                      [((), int(status == STOPPED_ANALYSIS_INCOMPLETE), 1, 0)])
            self._add(aggs["R09"], "R09", "TRAJECTORIES", u, fixed, BY_ME, [((), int(last >= 1), 1, 0)])
            self._add(aggs["R10"], "R10", "TRAJECTORIES", u, fixed, BY_ME, [((), last, 1, 0)])
        note = "terminal statuses are trajectory facts, not success metrics"
        for metric, agg in aggs.items():
            self._emit(agg, note=note if metric == "R06" else None, statistic="mean" if metric == "R10" else "share")

    # ---- C: effort ---------------------------------------------------------------------------------------

    def _improved_q06(self, cid, variant):
        if not self.eligible["Q06"][cid]:
            return 0
        b = self.co["base"][cid]
        f = self.co["final"][variant][cid]
        return int(b["correctness_verdict"] != PASS and f["correctness_verdict"] == PASS)

    def _effort(self):
        effort = OrderedDict()
        for (cid, v), t in self.co["trajectories"].items():
            cell = self.co["cells"][cid]
            candidates = [self.co["step"][v][k][cid] for k in range(1, t["final_iteration"] + 1)]
            gens = [self.generations[a["artifact_id"]] for a in candidates]
            for block, strata in _keys(cell, (("variant", v),), BY_M):
                acc = effort.setdefault((block, strata), Counter())
                acc["trajectories"] += 1
                acc["rounds"] += t["request_rounds"]
                acc["improved"] += self._improved_q06(cid, v)
                acc["records"] += len(gens)
                acc["output_tokens"] += sum(g["output_tokens"] for g in gens)      # never null (reading 12)
        for (block, strata), acc in effort.items():
            for quantity, num, den in (("records_per_trajectory", acc["records"], acc["trajectories"]),
                                       ("request_rounds_per_trajectory", acc["rounds"], acc["trajectories"]),
                                       ("records_per_improved_cell", acc["records"], acc["improved"]),
                                       ("request_rounds_per_improved_cell", acc["rounds"], acc["improved"])):
                note = "records = repair generation records; rounds include provider retries"
                if quantity.endswith("improved_cell"):
                    note = _notes(note, "improved cell = Q06 R02 improvement")
                self._put(estimate("C01", "REPAIR_CANDIDATES", block, strata + (("quantity", quantity),),
                                   numerator=num, denominator=den, value=_ratio(num, den), note=note,
                                   statistic="mean"))
            tokens_note = "value = improved cells / output tokens x %d" % TOKENS_SCALE
            for quantity, den, scale, note in (
                    ("per_1M_output_tokens", acc["output_tokens"], TOKENS_SCALE, tokens_note),
                    ("per_100_requests", acc["records"], REQUESTS_SCALE,
                     "value = improved cells / repair requests x %d (requests = repair generation records)"
                     % REQUESTS_SCALE)):
                value = None if den == 0 else acc["improved"] * scale / den
                self._put(estimate("C05", "FINAL", block, strata + (("quantity", quantity),),
                                   numerator=acc["improved"], denominator=den, value=value,
                                   note=_notes(note, "descriptive only; no ranking"), statistic="scaled_rate"))
        self._tokens()
        self._latency()
        self._runtime()

    def _tokens(self):
        groups = OrderedDict()
        for aid, a in self.co["artifacts"].items():
            g = self.generations[aid]
            if a["iteration"] == 0:
                population, fixed = "BASE", ()
            else:
                population, fixed = "REPAIR_CANDIDATES", (("variant", a["variant"]),)
            for block, strata in _keys(a, fixed, BY_M):
                groups.setdefault((population, block, strata), []).append(g)
        for (population, block, strata), gens in groups.items():
            for field in TOKEN_FIELDS:
                values = [g[field] for g in gens if g[field] is not None]
                note = "provider-normalized usage; providers count tokens differently"
                if field == "reasoning_tokens":
                    note = _notes(note, "null = the provider reports no field (distinct from 0)")
                est = estimate("C02", population, block, strata + (("quantity", field),), numerator=sum(values),
                               denominator=len(values), value=_ratio(sum(values), len(values)),
                               note=_notes(note, DIAGNOSTIC if population == "REPAIR_CANDIDATES" else None),
                               statistic="mean")
                est["generations"] = len(gens)
                est["coverage"] = _ratio(len(values), len(gens))
                est["median"] = stats.median(values)
                self._put(est)

    def _latency(self):
        groups = OrderedDict()
        for aid, a in self.co["candidates"].items():
            for block, strata in _keys(a, (("variant", a["variant"]),), BY_M):
                groups.setdefault((block, strata), []).append(self.generations[aid])
        for (block, strata), gens in groups.items():
            direct = [g for g in gens if g["timing_mode"] == "direct"]
            values = [g["duration_seconds"] for g in direct if g["duration_seconds"] is not None]
            est = estimate("C03", "REPAIR_CANDIDATES", block, strata, denominator=len(values),
                           value=stats.median(values), statistic="median",
                           note="direct-mode request wall time; batch spans never used")
            est["p95"] = stats.quantile(values, P95)
            est["n"] = len(values)
            est["excluded_null"] = len(direct) - len(values)
            est["excluded_not_direct"] = len(gens) - len(direct)
            self._put(est)

    def _runtime(self):
        groups = OrderedDict()
        threshold = core.RUNTIME_OUTLIER_SECONDS
        for aid, a in self.co["artifacts"].items():
            for tool in self.all_tools:
                entry = self.entries[aid][tool]
                if not entry["ran"]:
                    continue
                for block, strata in _keys(a, (("tool", tool),), BY_E):
                    groups.setdefault((block, strata), []).append(entry)
        for (block, strata), entries in groups.items():
            timeouts = sum(1 for e in entries if e["state"] == TIMEOUT)
            timed = [e for e in entries if e["state"] != TIMEOUT]
            values = [e["duration_seconds"] for e in timed if e["duration_seconds"] is not None]
            above = sum(1 for v in values if v > threshold)
            for rule in OUTLIER_RULES:
                kept = values if rule == "all" else [v for v in values if v <= threshold]
                est = estimate("C04", "GENERATED", block, strata + (("outlier_rule", rule),), denominator=len(kept),
                               value=stats.median(kept), statistic="median",
                               note=_notes(DIAGNOSTIC, "ran entries; TIMEOUT excluded and counted; "
                                           "reporting threshold %d s (SA4)" % threshold))
                est["p95"] = stats.quantile(kept, P95)
                est["n"] = len(kept)
                est["timeouts"] = timeouts
                # the TIMEOUT share of the ran entries (methodology: "reported as their own share"); identical
                # under both outlier rules because the rule only filters numeric non-TIMEOUT durations
                est["ran_entries"] = len(entries)
                est["timeout_share"] = _ratio(timeouts, len(entries))
                est["above_threshold"] = above
                est["excluded_null"] = len(timed) - len(values)
                self._put(est)

    # ---- G: held-out robustness ---------------------------------------------------------------------------

    def _heldout(self):
        rate = _Agg()
        reference = _Agg()
        for cid, cell in self.co["cells"].items():
            b = self.co["base"][cid]
            den = b["correctness_verdict"] == PASS and b["enh_valid"] > 0
            self._add(reference, "G01", "FINAL", cell, (), BY_M,
                      [((), int(den and b["enh_all_pass"] == 1), int(den), 0)])
            for v in core.VARIANTS:
                f = self.co["final"][v][cid]
                improved = self._improved_q06(cid, v)
                den = improved and f["enh_valid"] > 0
                self._add(rate, "G01", "FINAL", cell, (("variant", v),), BY_M,
                          [((), int(den and f["enh_all_pass"] == 1), int(den), int(improved and not den))])
        self._emit(rate, boot=self.descriptive, note="Q06-improved cells: final artifact enhanced all-pass",
                   excluded_reason="improved cell(s) without a valid pair")
        for (metric, population, block, strata), per_cluster in rate.sums.items():
            plain = tuple(p for p in strata if p[0] != "variant")
            ref = reference.sums[(metric, population, block, plain)]
            res = self._boot(self.descriptive, "ratio_difference", per_cluster, ref)
            est = estimate("G01", "FINAL", block, strata + (("comparison", "G01-E05(BASE)"),),
                           note="difference to the enhanced all-pass share of baseline-pass cells (E05 BASE)",
                           statistic="difference")
            self._apply(est, res, self.descriptive)
            est["reference_numerator"] = res["reference_numerator"]
            est["reference_denominator"] = res["reference_denominator"]
            self._put(est)
        e01 = lambda a: [((), a["enh_pass"], a["enh_valid"], 0)]  # noqa: E731
        endpoints = OrderedDict([
            ("Q06", self._q06), ("E01", e01),
            ("E02", lambda a: [((), int(a["enh_valid"] > 0 and a["enh_all_pass"] == 1), int(a["enh_valid"] > 0),
                                int(a["enh_valid"] == 0))])])
        for v in core.VARIANTS:
            for k in range(core.MAX_ITERATIONS + 1):
                for endpoint, fn in endpoints.items():
                    fixed = (("endpoint", endpoint), ("variant", v), ("step", k))
                    self._rates("G02", "STEP", self.co["step"][v][k].values(), fixed, ALL, fn,
                                boot=self.descriptive, note="identical base-cell cohort per step (goal G3)")

    # ---- X: post-freeze addendum_1 (descriptive; no p-values, no Holm) -----------------------------------

    def _x01(self):
        """X01: R04 / R05 for Q06 and E02 on the paired cohort minus every base
        cell with an auto-closed artifact at any iteration of any of its three
        trajectories (paired version of the frozen SA2 / Q10). Selecting on
        post-repair artifacts is a selection on a repair outcome, so this is a
        sensitivity next to the frozen R04/R05, never a corrected effect."""
        agg = _Agg()
        removed = Counter()                 # (block, endpoint) -> paired cells removed by the auto-closed rule
        outside = Counter()                 # (block, endpoint) -> cells outside the endpoint's paired cohort
        for cid, cell in self.co["cells"].items():
            closed = any(bool(a["clean_auto_closed"]) for a in self._cell_artifacts(cid))
            b = self.co["base"][cid]
            for endpoint in BINARY_ENDPOINTS:
                paired = self._eligible(endpoint, cid)
                ok = paired and not closed
                for block in (cell["block"], COMPOSITE):
                    removed[(block, endpoint)] += int(paired and closed)
                    outside[(block, endpoint)] += int(not paired)
                ep = (("endpoint", endpoint),)
                yb = self._y(endpoint, b)
                ys = OrderedDict((v, self._y(endpoint, self.co["final"][v][cid])) for v in core.VARIANTS)
                for v, yf in ys.items():
                    self._add(agg, "X01", "FINAL", cell, ep + (("variant", v),), ALL,
                              [((), (yf - yb) if ok else 0, int(ok), int(not ok))])
                for v1, v2 in COMPARISONS:
                    self._add(agg, "X01", "FINAL", cell, ep + (("comparison", "%s-%s" % (v1, v2)),), ALL,
                              [((), (ys[v1] - ys[v2]) if ok else 0, int(ok), int(not ok))])

        def split(key):
            _, _, block, strata = key
            endpoint = OrderedDict(strata)["endpoint"]
            return removed[(block, endpoint)], outside[(block, endpoint)]

        def note(key):
            strata = OrderedDict(key[3])
            closed, other = split(key)
            what = ("R04 net gain (improved - regressed) / cells" if "variant" in strata
                    else "R05 variant difference (sum of y_v1 - y_v2) / cells")
            return (POST_FREEZE_NOTE + "%s for %s on the paired cohort without the base cells that have an "
                    "auto-closed artifact (clean_auto_closed) at any iteration of any of their three trajectories; "
                    "the exclusion selects on post-repair artifacts (a sensitivity next to the frozen %s, not a "
                    "corrected effect); excluded: %d base cell(s) = %d with an auto-closed artifact + %d outside "
                    "the endpoint's paired cohort"
                    % (what, strata["endpoint"], "R04" if "variant" in strata else "R05", closed + other, closed,
                       other))

        def extras(est, key):
            closed, other = split(key)
            est["excluded"] = agg.excluded.get(key, 0)
            if est["excluded"] != closed + other or est["denominator"] + est["excluded"] != sum(
                    1 for c in self.co["cells"].values() if key[2] == COMPOSITE or c["block"] == key[2]):
                _refuse("X01 cohort bookkeeping of %s is inconsistent", key)
        self._emit(agg, boot=self.descriptive, note=note, statistic="difference", post_freeze=True, extras=extras)

    def _x02(self):
        """X02: the static three-state F01 under the tool-verdict reading -
        reported blocking findings count only from applicable entries in a
        normalize.VERDICT_STATES state (COMPLETED / PARTIAL), the states in
        which framework.tool_verdict can yield a defect verdict."""
        analysis = [t for t in self.tools["static"] if t in core.STATIC_ANALYSIS_TOOLS]
        states = self.x["verdict_states"]
        reading = OrderedDict()
        for aid, a in self.co["artifacts"].items():
            r = three_state([self.entries[aid][t] for t in analysis], states)
            if r == DIRTY and a["static_three_state"] != DIRTY:
                _refuse("artifact %s is DIRTY under the tool-verdict reading only", aid)
            reading[aid] = r
        dirty = lambda strata: ("state", DIRTY) in strata  # noqa: E731
        note = (POST_FREEZE_NOTE + "static three-state F01 recomputed under the tool-verdict reading: reported "
                "blocking findings count only from applicable tools in state %s (findings of %s entries do not make "
                "an artifact DIRTY)" % (" or ".join(states), " / ".join(s for s in core.GAP_STATES if s not in states)))
        pops = [("BASE", (), self.co["base"], BY_E)]
        pops += [("FINAL", (("variant", v),), self.co["final"][v], ALL) for v in core.VARIANTS]
        for population, fixed, units, strata_sets in pops:
            agg = _Agg()
            only = _Agg()
            for a in units.values():
                r = reading[a["artifact_id"]]
                self._add(agg, "X02", population, a, fixed, strata_sets,
                          [((("state", s),), int(r == s), 1, 0) for s in core.THREE_STATE])
                self._add(only, "X02", population, a, fixed, strata_sets,
                          [((("state", DIRTY),), int(a["static_three_state"] == DIRTY and r != DIRTY), 0, 0)])

            def extras(est, key, only=only):
                if est["strata"].get("state") == DIRTY:
                    est["dirty_only_under_frozen_rule"] = sum(v[0] for v in only.sums[key].values())
            self._emit(agg, boot=self.descriptive, ci_when=dirty, note=note, post_freeze=True, extras=extras)

    def _x03(self):
        """X03: composition of the BASE F01 DIRTY verdicts - per static analysis
        tool the DIRTY artifacts whose reported blocking findings come from that
        tool only, and per (tool, check id) for the top-N check ids of the tool
        (composite BASE reported blocking findings, ties by check id; selected
        once on the composite, reused for the blocks) the findings and the
        artifacts with >= 1 of them. No CI, counts and shares only."""
        analysis = [t for t in self.tools["static"] if t in core.STATIC_ANALYSIS_TOOLS]
        # the check id is an X03 strata value: a reported blocking finding of an analysis tool without one
        # refuses here, where it is read (every artifact, as the finding table is checked as a whole)
        for aid, by_check in self.blocking_checks.items():
            for tool, check in by_check:
                if tool in analysis and (not isinstance(check, str) or not check):
                    _refuse("reported blocking finding of %s on %s without a check id (X03 strata)", tool, aid)
        dirty, only, applicable, findings, with_check = Counter(), Counter(), Counter(), Counter(), Counter()
        for a in self.co["base"].values():
            aid = a["artifact_id"]
            e = self.entries[aid]
            tools = [t for t in analysis if e[t]["applicable"] and e[t]["num_reported_blocking"] > 0]
            if bool(tools) != (a["static_three_state"] == DIRTY):
                _refuse("artifact %s: F01 DIRTY contradicts its reported blocking findings", aid)
            checks = [(tc, n) for tc, n in sorted(self.blocking_checks.get(aid, {}).items()) if tc[0] in analysis]
            for block in (a["block"], COMPOSITE):
                for t in analysis:
                    applicable[(block, t)] += int(bool(e[t]["applicable"]))
                if tools:
                    dirty[block] += 1
                    if len(tools) == 1:
                        only[(block, tools[0])] += 1
                for (t, c), n in checks:
                    findings[(block, t, c)] += n
                    with_check[(block, t, c)] += 1
        top = self.x["top_checks"]
        selected = OrderedDict()
        for t in analysis:
            ranked = sorted(((c, n) for (b, tool, c), n in findings.items() if b == COMPOSITE and tool == t),
                            key=lambda item: (-item[1], item[0]))
            selected[t] = [c for c, _ in ranked[:top]]
        head = POST_FREEZE_NOTE + "composition of the BASE F01 DIRTY verdicts (frozen rule); "
        caveat = "DIRTY = >= 1 finding the frozen tool configuration marks blocking, not a confirmed defect"
        for block in BLOCKS_ALL:
            for t in analysis:
                self._put(estimate(
                    "X03", "BASE", block, (("tool", t), ("quantity", "dirty_only_via_tool")),
                    numerator=only[(block, t)], denominator=dirty[block], value=_ratio(only[(block, t)], dirty[block]),
                    note=head + "DIRTY artifacts whose reported blocking findings come from this tool only; "
                    "denominator: DIRTY artifacts; " + caveat, post_freeze=True))
                for c in selected[t]:
                    rank = ("check id among the top %d of the tool by composite BASE reported blocking findings "
                            "(ties by check id; selected on the composite, reused per block)" % top)
                    self._put(estimate(
                        "X03", "BASE", block, (("tool", t), ("check_id", c), ("quantity", "blocking_findings")),
                        numerator=findings[(block, t, c)], statistic="count", post_freeze=True,
                        note=head + "reported blocking findings of this check id (count per tool, never summed "
                        "across tools); " + rank))
                    den, num = applicable[(block, t)], with_check[(block, t, c)]
                    self._put(estimate(
                        "X03", "BASE", block, (("tool", t), ("check_id", c), ("quantity", "artifacts_with_check")),
                        numerator=num, denominator=den, value=_ratio(num, den),
                        post_freeze=True, note=head + "artifacts with >= 1 reported blocking finding of this check id; "
                        "denominator: artifacts to which the tool applies; " + rank))

    def _x04(self):
        """X04 (goal G4): among artifacts failing Q06, the share whose static
        verdict F01 is CLEAN_COMPLETE - code the static tools pass but the
        tests reject - and, separately, NO_FINDING_INCOMPLETE (reading 17).
        The note is a function of the state: under the frozen F01 rule a gap
        without a finding is never clean, so only the CLEAN_COMPLETE share is
        the G4 quantity; the NO_FINDING_INCOMPLETE share is its contrast."""
        def items(a):
            failing = a["correctness_verdict"] not in (PASS, BASELINE_INCOMPATIBLE)
            return [((("state", s),), int(failing and a["static_three_state"] == s), int(failing), 0)
                    for s in X04_STATES]
        meaning = OrderedDict([
            (CLEAN_COMPLETE, "statically clean (every applicable static analysis tool COMPLETED, no reported "
                             "blocking finding) but incorrect: the goal G4 quantity"),
            (NO_FINDING_INCOMPLETE, "no reported blocking finding but >= 1 applicable static analysis tool in an "
                                    "analysis-gap state (%s), so the static verdict is incomplete, NOT clean; shown "
                                    "separately as a contrast to the G4 quantity (the %s share)"
                                    % (" / ".join(core.GAP_STATES), CLEAN_COMPLETE)),
        ])

        def note(key):
            state = OrderedDict(key[3])["state"]
            return (POST_FREEZE_NOTE + "artifacts failing Q06 (verdict not pass, baseline_incompatible excluded) "
                    "whose static verdict F01 is %s: %s" % (state, meaning[state]))
        for population, fixed, units in self._paired_pops(steps=False):
            self._rates("X04", population, units.values(), fixed, ALL, items, boot=self.descriptive, note=note,
                        post_freeze=True)

    def _x05(self):
        """X05 (goal G4): final_iteration of the trajectories that ended with the
        loop's own clean stop - mean and distribution over the iterations."""
        mean, share = _Agg(), _Agg()
        iterations = range(core.MAX_ITERATIONS + 1)
        for u in self._trajectory_units():
            clean = u["terminal_status"] in CLEAN_STOPS
            last = u["final_iteration"]
            fixed = (("variant", u["variant"]),)
            self._add(mean, "X05", "TRAJECTORIES", u, fixed, ALL, [((), last if clean else 0, int(clean), 0)])
            self._add(share, "X05", "TRAJECTORIES", u, fixed, ALL,
                      [((("iteration", k),), int(clean and last == k), int(clean), 0) for k in iterations])
        note = (POST_FREEZE_NOTE + "final_iteration of the trajectories ending %s (the loop's own clean stop, not a "
                "success metric)" % " or ".join(CLEAN_STOPS))
        self._emit(mean, note=note + "; mean iterations", statistic="mean", post_freeze=True)
        self._emit(share, note=note + "; share ending at this iteration", post_freeze=True)

    def _x06(self):
        """X06: joint R01 transition of the same base cell on Q06 and E02 over
        the cells in both paired cohorts (e.g. Q06 not_pass->pass with E02
        not_all_pass->not_all_pass: repaired on the known tests only)."""
        labels = OrderedDict((endpoint, ["%s->%s" % (x, y) for x in ENDPOINT_STATES[endpoint]
                                         for y in ENDPOINT_STATES[endpoint]]) for endpoint in BINARY_ENDPOINTS)
        agg = _Agg()
        for cid, cell in self.co["cells"].items():
            ok = all(self._eligible(endpoint, cid) for endpoint in BINARY_ENDPOINTS)
            b = self.co["base"][cid]
            for v in core.VARIANTS:
                f = self.co["final"][v][cid]
                q, h = ["%s->%s" % (self._state(endpoint, b), self._state(endpoint, f))
                        for endpoint in BINARY_ENDPOINTS]
                self._add(agg, "X06", "FINAL", cell, (("variant", v),), ALL,
                          [((("transition", x), ("heldout_transition", y)), int(ok and (q, h) == (x, y)), int(ok), 0)
                           for x in labels["Q06"] for y in labels["E02"]])
        note = (POST_FREEZE_NOTE + "joint transition of the same base cell on Q06 (transition) and E02 "
                "(heldout_transition); denominator: cells in both paired cohorts (>= 1 valid enhanced pair)")
        self._emit(agg, note=note, post_freeze=True)

    def _addendum(self):
        if self.x is None:
            _refuse("the post-freeze addendum metrics need the addendum")
        self._x01()
        self._x02()
        self._x03()
        self._x04()
        self._x05()
        self._x06()

    # ---- run -------------------------------------------------------------------------------------------------

    def run(self):
        self._quality()
        self._enhanced()
        self._tool_states()
        self._verdicts()
        self._findings()
        self._agreement()
        self._repair()
        self._trajectories()
        self._effort()
        self._heldout()
        self._addendum()
        produced = set(est["metric_id"] for est in self.out.values())
        declared = core.all_metric_ids(self.methodology, self.addendum)
        expected = set(declared)
        if produced != expected or len(declared) != len(expected):
            _refuse("produced metric ids differ from the methodology and its addendum: missing %s, extra %s",
                    sorted(expected - produced), sorted(produced - expected))
        return [self.out[key] for key in sorted(self.out)]


def compute(dataset, methodology, bootstrap_primary=None, bootstrap_descriptive=None, exploratory=False,
            addendum=None):
    """Every methodology metric and every post-freeze addendum metric
    (X01-X06) as a sorted list of Estimates.

    bootstrap_primary / bootstrap_descriptive: a stats.ClusterBootstrap over
    the dataset's benchmark clusters, a replicate count, or None for the
    frozen methodology counts (10,000 / 2,000). The seed and the confidence
    level are always the methodology's. A replicate count other than the
    methodology's refuses unless exploratory=True (tests, probes); such a
    run labels every bootstrapped estimate EXPLORATORY / not confirmatory.
    addendum: the addendum document (None loads core.load_addendum bound to
    `methodology`); the produced metric ids must be
    core.all_metric_ids(methodology, addendum)."""
    if addendum is None:
        addendum = core.load_addendum(methodology=methodology)
    return _Builder(dataset, methodology, bootstrap_primary, bootstrap_descriptive, exploratory=exploratory,
                    addendum=addendum).run()


def compute_primary(dataset, methodology, bootstrap_primary=None, exploratory=False):
    """Only the 12 primary hypotheses (R04/R05 on the composite cohort) with
    p-values and Holm - the reproducibility rerun of run.py (replicate rule
    as compute())."""
    builder = _Builder(dataset, methodology, bootstrap_primary, 1, exploratory=exploratory, primary_only=True)
    aggs = builder._paired(r01=False, strata_rx=ALL, strata_r05=ALL)
    reason = "base cell(s) outside the paired cohort"
    for metric in ("R04", "R05"):
        agg = _Agg()
        for key, per_cluster in aggs[metric].sums.items():
            if key[2] == COMPOSITE:
                agg.sums[key] = per_cluster
                if aggs[metric].excluded.get(key):
                    agg.excluded[key] = aggs[metric].excluded[key]
        builder._emit(agg, boot=builder.primary, excluded_reason=reason, statistic="difference", kind="difference",
                      primary_when=lambda block, strata: True)
    builder._holm()
    return sorted(builder.primary_estimates(), key=sort_key)
