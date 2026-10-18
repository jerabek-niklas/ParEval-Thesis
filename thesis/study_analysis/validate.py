"""Validation of the study analysis (study_analysis_validation.v1), read-only.

The numbers of the analysis are checked against sources that did NOT
produce them: the normalized dataset against the persisted composite
(cells, stage coverage), the census and the repair state ledgers; the
dataset against the composite cells (per artifact) and the reproduced
composite fingerprint; EVERY estimate against an independent recomputation
from the normalized dataset (Recompute below: an estimate whose shape the
recomputation does not define FAILS, it is never counted as checked);
aggregates against their own algebra (transition and distribution sums,
block additivity, Holm); the bootstrap settings of every interval against
the frozen methodology; the input manifest against the dataset it claims
to describe. A contradiction in any single number is a FAIL of its check;
an exception inside a check is a FAIL with its message (fail-closed, never
a skip). What stays outside the recomputation is named explicitly: the
interval bounds and p-values themselves (only their bootstrap settings,
their presence where the methodology demands an interval, their
degeneracy flag, their resolution fields and their reproduction by the
rerun are checked) and the free-text notes (except the two sentences the
estimate contract fixes: the POST-FREEZE prefix of the addendum estimates
and the degenerate-interval sentence).

Checks (in order):
  addendum_bound        the post-freeze addendum (methodology_addendum.json,
                        status DECLARED_AFTER_DRY_RUN) amends exactly the
                        frozen methodology (canonical sha256), its ids do not
                        collide with the frozen ones and it declares exactly
                        the metrics recomputed here (X01-X06, by name)
  inputs_bound          dataset provenance == target table == persisted
                        composite (self-hash, EXPECTED sha) == census digest
  counts_composite      cells block (total, per block, base, candidates per
                        block/variant/iteration) and population
  counts_stage_coverage stage_coverage cells / with_evidence / owners /
                        supplemented_by / enhanced pairs and statuses
  counts_census         loops terminal, sample states per block and loop,
                        owners, base cells, trajectories = cells x variants
  trajectories_ledger   final iteration, statuses, stop reason, test
                        verdict, loop owner, loop kind and request rounds
                        per trajectory == the loops' own state ledgers;
                        every wave state and state row carries its loop's
                        identity (owner / recovery_001 for the overlaid
                        rows, model, variant); continued/native == the
                        census loop kind
  composite_binding     pc.composite_document over the composite cells
                        reproduces the persisted composite_sha256; per
                        artifact owners, verdict, tool states, enhanced
                        status counts == the composite cell
  uniqueness            artifact, base cell, trajectory, pair, generation,
                        tool entry identities
  ownership             owner of every stage within the block's allowed set
  excluded_runs         no excluded run (and no parent repair file) anywhere
  block_separation      pilot runs only pilot_002*, full_ext runs only
                        full_ext_001 / recovery_001..004 iteration runs;
                        disjoint benchmarks; ids follow core's id helpers
  table_targets         the full_ext artifacts are exactly the frozen
                        target table's samples (facts equal)
  dataset_consistency   base cells / generations / trajectories partition
                        the artifacts; enh_* columns == the pair rows; tool
                        entries complete and applicable per config; finding
                        kinds == entry counts; derived artifact columns
  applicability         NOT_APPLICABLE / ABSENT_INAPPLICABLE never gaps:
                        three-state and completeness recomputed per artifact
  enhanced_gates        gate uniformity per (block, benchmark, spec,
                        execution model); identical valid sets per cell
  trajectory_structure  final_artifact == artifact_iter<final>, candidates
                        referenced exactly once, statuses before final active
  estimates_schema      keys, vocabularies of every strata value and
                        population label (STEP carries a step, FINAL none),
                        interval fields; every interval rests on the
                        methodology's replicate count (replicates + the
                        skipped replicates its note documents ==
                        replicates_primary for the primary family,
                        replicates_descriptive otherwise); an EXPLORATORY
                        (non-confirmatory) estimate FAILS; the four contract
                        keys of every estimate: post_freeze (true exactly for
                        the addendum metrics, whose notes start with the
                        POST-FREEZE prefix), ci_degenerate (None without an
                        interval, else ci_low == ci_high; a degenerate
                        interval's note carries the degenerate sentence),
                        p_resolution (2 / replicates_primary on the primary
                        family, None elsewhere), p_holm_resolution (None
                        outside the primary family); check_id (a check id the
                        dataset's findings of that tool carry) and
                        heldout_transition (the R01 E02 labels)
  metric_coverage       every methodology AND addendum metric id has
                        estimates (core.all_metric_ids)
  estimate_bounds       numerator <= denominator, shares in [0, 1], ...
  estimate_recompute    every estimate recomputed from the dataset:
                        numerator, denominator, value and the metric's
                        extra facts (R01 transition cells, F05 counts and
                        artifact shares, F06 2x2 tables / agreement / kappa,
                        C01-C05 effort, tokens, latency and runtime
                        quantiles, E04 gated groups, G01 reference
                        difference); F05 / F06 / R01 completeness; an
                        interval wherever the methodology demands one and
                        the cluster support makes it estimable; the addendum
                        metrics X01-X06 on their own code paths (Recompute
                        _x01.._x06, never metrics.py): numerator, denominator,
                        value, excluded (X01), dirty_only_under_frozen_rule
                        (X02), the shape label `statistic` DESIGN2 fixes (X01
                        difference, X05 mean / share, X03 finding count), the
                        complete set of their shapes (X01 comparisons == the
                        R05 labels, X03 top check ids per tool, X06 every
                        transition pair), the CI mandate of X01, the X02 DIRTY
                        share and X04 (descriptive count) and NO interval on
                        the others (X03, X05, X06, the other X02 shares)
  final_equals_step2 / distribution_sums / block_additivity / primary_family
                        the estimate algebra (primary family: 12
                        hypotheses, Holm, the primary replicate count,
                        p_holm_resolution = the Holm-order running maximum
                        of (m - rank + 1) * p_resolution)
  tables / figures      every table names population and unit; every ratio
                        cell carries numerator and denominator (rate / diff
                        cells equal n/N); a percentage string needs an n/N;
                        a table with a pilot / composite Q06 / E02 cell
                        carries the addendum's BL01 note text; a table with a
                        post-freeze cell carries the POST-FREEZE label (title
                        or notes), T12_addendum's title starts with
                        'POST-FREEZE (addendum_1, descriptive): '; a
                        degenerate interval shown in a ci / ci_pp column is
                        marked (cell ci_degenerate true) and only a
                        degenerate one, and the table then carries the
                        DEGENERATE_CI note text (other cells only keep the
                        flag consistent with the bounds). Figures: structure;
                        BL01 on F1/F2/F3/F5, REASONING on F3/F5 and every
                        per-model figure, EFFECTIVE_STATES on F4 (DESIGN2
                        2.2), BL01 / POST-FREEZE for the sources their data
                        rows name and DEGENERATE_CI for a degenerate row
  input_stability       the manifest is self-hashed, describes THIS dataset
                        (dataset_inputs == provenance and counts, every
                        file the normalizer read listed with its sha) and
                        manifest.rehash() is empty; with the start manifest
                        code, methodology, addendum, closure, composite,
                        acceptance and HEAD are unchanged between start and
                        end; the manifest's addendum is the validated one;
                        in write mode both manifests were built on a clean
                        tree at the preflight HEAD
  reproducibility       the primary family recomputed with the same seed is
                        identical (estimates_rerun)

Conservative readings (documented deviations, see the module report):
  * ownership is checked per block: the pilot block is owned by pilot_002 in
    every stage; full_ext static {own run, recovery_002/003, phase 2},
    correctness/dynamic {own run, phase 2}, enhanced {phase 2} only.
  * applicability: an applicable tool in an inapplicable state is a
    contradiction (never observed in the frozen data); the three-state
    verdict counts a stage as incomplete only on an applicable tool in a
    GAP state.
  * the composite binding accepts exactly one documented difference between
    the composite's raw state (framework.analysis_state_of) and the
    normalized record-level state (framework.effective_tool_state): a
    non-compiler TOOL_ERROR / PARTIAL that the record-level rule maps to
    NOT_ANALYZED because the compiler rejected the translation unit
    (compiler COMPLETED with a reported blocking finding).
  * every estimate is recomputed; an estimate whose (metric, population,
    strata) the recomputation does not define - a foreign population label,
    variant, step, model, family, tool, state, transition, quantity or an
    unknown strata key - FAILS estimate_recompute (never skipped). Label
    vocabularies the methodology does not fix are read as in the
    specification: R01 transitions 'x->y' over pass/not_pass (Q06),
    all_pass/not_all_pass (E02) and the three-state words (F01/F02); F05
    quantities findings / artifacts_with_finding; F06 pair 'a+b' with the
    class words of the methodology joined by '+' or '/'; C05 quantities
    per_<n>[M]_output_tokens / per_<n>_requests whose scales must equal the
    methodology's C05 text; G01 comparison names the E05 (BASE) reference.
  * paired Q06 cohort (R01-R05, G01, C01/C05 improved cells): a base cell is
    excluded from every variant when ANY artifact of its trajectories is
    baseline_incompatible (identical cohort across variants); unpaired Q06
    rates exclude only the artifact. Paired E02 cohort: cells whose base and
    target artifacts carry >= 1 valid pair.
  * CI mandate: the metrics whose methodology aggregation names a CI (Q05,
    Q06, E01, E02, F01 - only its DIRTY share, R02-R05, G01 - only the
    difference to its E05 reference, G02) must carry a cluster-bootstrap
    percentile interval when the value is defined and the interval is
    estimable: >= 2 benchmark clusters carry the estimate and each lies in a
    bootstrap stratum (block) of >= 2 clusters (SA1: the clusters without the
    BL-01 benchmark). A one-cluster ratio is invariant to its bootstrap
    weight, so no interval is demanded there. An estimate whose note
    documents that every replicate was skipped needs no interval either.
  * C03/C04 medians and p95 are type-7 quantiles (specification 3.1); C04
    counts the entries with ran == true ('ran tools'), TIMEOUT excluded and
    counted; C01/C05 repair requests are the repair generation records.
  * Holm's alpha is 1 - statistics.bootstrap.confidence_level (0.05),
    rounded to 12 digits.
  * a missing estimates_rerun FAILS the reproducibility check; in write mode
    a missing start manifest or preflight head FAILS input_stability.

Readings of the addendum contract (DESIGN2 section 1; documented deviations):
  * X01 cohort: the paired cohort of the endpoint (Q06: the identical paired
    cohort above; E02: base and target artifacts with >= 1 valid pair; the
    comparison form: both compared targets) minus every base cell with a
    clean_auto_closed artifact on ANY of its three trajectories (iterations
    0..final_iteration). `excluded` admits the two readings of the contract
    sentence - the auto-closed removals from the paired cohort alone, or
    those plus the endpoint's own exclusions (= base cells of the block -
    denominator) - but ONE reading for every X01 estimate (any other value,
    or a mixture, FAILS). They coincide on the real data.
  * X02 recomputes the three-state over the applicable STATIC_ANALYSIS_TOOLS
    entries: DIRTY iff a COMPLETED / PARTIAL entry carries a reported
    blocking finding, else NO_FINDING_INCOMPLETE on a gap state, else
    CLEAN_COMPLETE (VERDICT_STATES below, the framework.tool_verdict states).
  * X03 'dirty only via tool t': the applicable static analysis tools with
    >= 1 reported blocking finding are exactly {t} (the compiler is a build
    precondition and outside F01); check-id counts are the reported blocking
    findings rows of BASE artifacts; the top-N selection (N parsed from the
    addendum text, ties by check id ascending) is made once on the composite
    BASE and reused for the blocks.
  * X04 numerator is a subset of its denominator (Q06 not pass: verdict
    neither pass nor baseline_incompatible, addendum text).
  * tables: a 'dagger-marked' interval is a cell of a ci / ci_pp column
    (the only column kinds the renderers print an interval and its dagger
    in) whose ci_degenerate is true; a shown interval is such a cell with
    finite ci_low and ci_high. A rate / diff / mean cell prints 'value (n/N)'
    without its interval, so a zero-width interval there needs neither the
    mark nor the DEGENERATE_CI note. A cell triggers the BL01 note when its
    source is a Q06 / E02 aggregate - the metric is one of BL01_METRICS (Q06,
    Q07, Q08, Q09, Q10, E02, E05, G01, C05, X04, X06: they count the Q06
    correctness or the E02 held-out verdict) or the endpoint stratum is Q06
    / E02 (R01-R05, G02, X01) - in the pilot or composite block and its
    strata do not exclude the BL-01 benchmark (sensitivity SA1, or a model /
    execution model / family without BL-01 cells in that block). A cell is
    post-freeze when its source metric is an addendum id or it carries
    post_freeze true; the table / figure then needs 'POST-FREEZE' in its
    title or notes.
  * figures: the figure contract carries no per-row source, so the figure
    notes are demanded by the fixed figure ids of DESIGN2 2.2, by a
    per-model data column (model / model_id: REASONING) and by the data rows
    that name their estimate (a nested source or a metric_id: BL01,
    POST-FREEZE); a row with ci_degenerate true demands DEGENERATE_CI.

Python 3.8 compatible syntax.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, OrderedDict
from fractions import Fraction
from pathlib import Path

from thesis.study_analysis import core
from thesis.study_analysis import manifest as mf
from thesis.study_analysis import preflight as pf
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.recovery_successor_004 import census as cs
from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt

PASS = pf.PASS
FAIL = pf.FAIL
EXAMPLES = core.EXAMPLES
TOLERANCE = 1e-9
STAGE_OWNER_COLUMNS = OrderedDict([("static", "static_owner"), ("correctness", "correctness_owner"),
                                   ("dynamic", "dynamic_owner"), ("enhanced", "enhanced_owner")])
STATIC_SUPPLEMENTERS = tuple(pt.SUPPLEMENT_OWNERS) + (core.PHASE2,)
# the four keys of DESIGN2 section 1 are part of every estimate (absent = schema FAIL)
CONTRACT_KEYS = ("post_freeze", "ci_degenerate", "p_resolution", "p_holm_resolution")
ESTIMATE_KEYS = ("metric_id", "population", "block", "strata", "numerator", "denominator", "value", "ci_low",
                 "ci_high", "ci_method", "replicates", "p_value", "p_holm", "reject_holm", "note") + CONTRACT_KEYS
ESTIMATE_BLOCKS = tuple(core.BLOCKS) + (core.COMPOSITE,)
# the specification's strata keys plus 'iteration' (GENERATED per iteration,
# R06 final iteration, X05) and 'quantity' (C01/C02/C05/F05/X03
# sub-quantities), which metrics.py emits, and the addendum's check_id (X03)
# and heldout_transition (X06)
STRATA_KEYS = ("model_id", "execution_model", "variant", "family", "step", "tool", "state", "verdict", "status",
               "kind", "transition", "endpoint", "comparison", "flag", "class", "pair", "iteration", "quantity",
               "outlier_rule", "sensitivity", "check_id", "heldout_transition")
CI_METHOD = "cluster_bootstrap_percentile"
SHARE_METRICS = ("Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09", "Q10", "E01", "E02", "E03",
                 "E04", "E05", "S01", "S02", "S03", "D01", "D02", "D03", "F01", "F02", "F03", "F04", "R01",
                 "R02", "R03", "R06", "R07", "R08", "R09", "G01", "G02")
DIFFERENCE_METRICS = ("R04", "R05")
MEAN_METRICS = ("R10",)
NON_ADDITIVE = ("F06", "C03", "C04")
PRIMARY_METRICS = ("R04", "R05")
PRIMARY_ENDPOINTS = ("Q06", "E02")
# distribution metrics: the category key(s). R06 reports the status alone and
# the joint (status, final iteration) distribution, so its 'iteration' is part
# of the category, never a population filter (so is X05's final-iteration
# distribution); for every other metric 'iteration' (GENERATED per
# iteration) and 'step' are population filters. X06 is the joint Q06 x E02
# transition distribution of one variant.
DISTRIBUTIONS = OrderedDict([("R01", ("transition",)), ("R06", ("status", "iteration")), ("Q08", ("verdict",)),
                             ("E03", ("status",)), ("S01", ("state",)), ("D01", ("state",)),
                             ("F01", ("state",)), ("F02", ("state",)), ("X02", ("state",)),
                             ("X05", ("iteration",)), ("X06", ("transition", "heldout_transition"))])
DISTRIBUTION_FILTERS = ("model_id", "execution_model", "family", "variant", "endpoint", "tool", "sensitivity",
                        "step", "iteration")
GROUP_FILTERS = ("model_id", "execution_model", "family", "sensitivity")
POPULATIONS = ("BASE", "GENERATED", "REPAIR_CANDIDATES", "FINAL", "STEP")
POPULATION_LABELS = POPULATIONS + ("TRAJECTORIES",)
ENH_PAIR_METRICS = ("E01", "E03", "E04")          # population ENH_PAIRS(<population>) (methodology E01/E03/E04)
PERCENT_RE = re.compile(r"^\s*[-+]?\d+(?:[.,]\d+)?\s*(?:\\?%|pp)\s*$")
FRACTION_RE = re.compile(r"[-+]?\d[\d,{}\s]*/\s*\d")
SKIPPED_RE = re.compile(r"(\d+) of (\d+) bootstrap replicates skipped")
EXPLORATORY = "EXPLORATORY"
TOOL_STAGE = OrderedDict([(t, "static") for t in core.STATIC_TOOLS] + [(t, "dynamic") for t in core.DYNAMIC_TOOLS])
TOKEN_FIELDS = tuple(c for c in core.SCHEMAS["generations"] if c.endswith("_tokens"))
TIMEOUT = "TIMEOUT"
COMPLETED = "COMPLETED"
PASS_VERDICT = "pass"
P95 = 0.95                                          # the methodology's "p95" (C03/C04)
# R01 state words per endpoint (the specification's transition labels 'x->y')
R01_STATES = OrderedDict([("Q06", ("pass", "not_pass")), ("E02", ("all_pass", "not_all_pass")),
                          ("F01", core.THREE_STATE), ("F02", core.THREE_STATE)])
F05_QUANTITIES = ("findings", "artifacts_with_finding")
C01_QUANTITIES = OrderedDict([("records_per_trajectory", ("records", "trajectories")),
                              ("request_rounds_per_trajectory", ("rounds", "trajectories")),
                              ("records_per_improved_cell", ("records", "improved")),
                              ("request_rounds_per_improved_cell", ("rounds", "improved"))])
C05_QUANTITY_RE = re.compile(r"^per_(\d+)(M?)_(output_tokens|requests)$")
OUTLIER_RULES = ("all", "excluding_above_threshold")
# the metrics whose methodology aggregation names a CI; F01 only for its DIRTY
# share, G01 only for the difference to its reference (module docstring)
CI_METRICS = ("Q05", "Q06", "E01", "E02", "F01", "R02", "R03", "R04", "R05", "G01", "G02")
SUPPORT_MIN = 2                                    # clusters / stratum size an interval needs
# extra estimate facts that must be present (the methodology's aggregation
# names them; the tables consume them); other extras are compared if present
REQUIRED_EXTRAS = OrderedDict([("F06", ("n11", "n10", "n01", "n00")), ("C02", ("coverage", "median")),
                               ("C03", ("p95", "n")), ("C04", ("p95", "n", "timeouts"))])
# -- the post-freeze addendum_1 (DESIGN2 section 1): the metrics recomputed here, by id and name; an
# addendum declaring other metrics refuses (addendum_bound) instead of passing unchecked
ADDENDUM_NAMES = OrderedDict([("X01", "paired_auto_closed_sensitivity"), ("X02", "three_state_tool_verdict_reading"),
                              ("X03", "dirty_composition"), ("X04", "statically_clean_but_incorrect"),
                              ("X05", "iterations_to_clean"), ("X06", "joint_parEval_heldout_transitions")])
# the addendum metrics whose aggregation names a (descriptive) CI; X02 only for its DIRTY share
ADDENDUM_CI_METRICS = ("X01", "X02", "X04")
ADDENDUM_SHARE_METRICS = ("X02", "X03", "X04", "X05", "X06")
POST_FREEZE_PREFIX = "POST-FREEZE %s (descriptive): "       # % the addendum id's last component (addendum_1)
DEGENERATE_NOTE = "degenerate percentile interval (zero width): every supporting cluster at the boundary"
# the states in which framework.tool_verdict can turn a blocking finding into a defect verdict (X02)
VERDICT_STATES = (COMPLETED, "PARTIAL")
X03_ONLY, X03_FINDINGS, X03_ARTIFACTS = "dirty_only_via_tool", "blocking_findings", "artifacts_with_check"
X03_QUANTITIES = (X03_ONLY, X03_FINDINGS, X03_ARTIFACTS)
X03_TOP_RE = re.compile(r"for the (\d+) check ids")         # the addendum X03 meaning: "... for the 10 check ids ..."
X04_STATES = ("CLEAN_COMPLETE", "NO_FINDING_INCOMPLETE")
X04_NOT_FAILING = (PASS_VERDICT,) + tuple(core.CORRECTNESS_EXCLUDED)
X05_STOPS = ("stopped_clean", "stopped_tests_pass")
X01_READINGS = ("auto_closed", "auto_closed_plus_endpoint_exclusions")
ALTERNATIVES = "_alternatives"         # Recompute.expected: field -> OrderedDict(reading -> value)
BL01_BLOCKS = (core.BLOCKS[0], core.COMPOSITE)    # the BL-01 benchmark is a pilot benchmark
# the metrics whose estimates aggregate the Q06 correctness verdict or the E02 held-out verdict (the addendum's
# BL01 "pilot or composite Q06 / E02 aggregate"); the metrics with an 'endpoint' stratum Q06 / E02 (R01-R05, G02,
# X01) trigger through that stratum (module docstring)
BL01_METRICS = ("Q06", "Q07", "Q08", "Q09", "Q10", "E02", "E05", "G01", "C05", "X04", "X06")
POST_FREEZE_LABEL = "POST-FREEZE"
TABLE_TITLE_PREFIX = "POST-FREEZE (%s, descriptive): "    # DESIGN2 s2.8 (% the addendum id's last component)
ADDENDUM_TABLE = "T12_addendum"
# DESIGN2 section 2.2: the disclosure notes (addendum table_notes ids) the fixed figures must carry; every
# figure with a per-model data column carries REASONING as well
FIGURE_NOTES = OrderedDict([("F1_correctness_before_after", ("BL01",)), ("F2_heldout_over_iterations", ("BL01",)),
                            ("F3_heatmap_model_variant", ("BL01", "REASONING")),
                            ("F4_tool_states", ("EFFECTIVE_STATES",)), ("F5_gain_vs_effort", ("BL01", "REASONING"))])
MODEL_COLUMNS = ("model", "model_id")
# the interval fields an addendum estimate without a CI mandate must leave empty
INTERVAL_FIELDS = ("ci_low", "ci_high", "ci_method", "replicates")


# -- small helpers -------------------------------------------------------------------------

def _plain(value):
    """JSON round trip into plain dicts (order-insensitive equality)."""
    return json.loads(json.dumps(value, default=str))


def _detail(problems, **facts):
    return pf.problems_detail(problems, **facts)


def _diff(problems, label, expected, actual):
    """Append a problem when two numbers / structures differ."""
    if _plain(expected) != _plain(actual):
        problems.append("%s: source %s, analysis %s" % (label, _short(expected), _short(actual)))


def _short(value, limit=300):
    text = json.dumps(_plain(value), sort_keys=True)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _strata(estimate):
    strata = estimate.get("strata")
    return strata if isinstance(strata, dict) else {}


def _skey(strata):
    return json.dumps(_plain(strata), sort_keys=True)


def estimate_key(estimate):
    return (estimate.get("metric_id"), estimate.get("population"), estimate.get("block"),
            _skey(_strata(estimate)))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite(value):
    return _number(value) and math.isfinite(value)


def _close(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= TOLERANCE * max(1.0, abs(float(a)), abs(float(b)))


def _same(a, b):
    """Equality of two estimate facts (numbers within TOLERANCE)."""
    if a is None or b is None:
        return a is None and b is None
    if _number(a) and _number(b):
        return _close(a, b)
    return _plain(a) == _plain(b)


def _ratio(numerator, denominator):
    return None if not denominator else float(numerator) / denominator


def _percentile(values, q):
    """Type-7 quantile (linear interpolation between the closest ranks,
    specification 3.1) of unsorted values; None for no values."""
    values = sorted(values)
    if not values:
        return None
    h = (len(values) - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (h - lo) * (values[hi] - values[lo])


def _kappa(n11, n10, n01, n00):
    """Cohen's kappa of a 2x2 table; None when empty or chance agreement 1."""
    n = n11 + n10 + n01 + n00
    if n == 0:
        return None
    observed = Fraction(n11 + n00, n)
    first, second = Fraction(n11 + n10, n), Fraction(n11 + n01, n)
    chance = first * second + (1 - first) * (1 - second)
    return None if chance == 1 else float((observed - chance) / (1 - chance))


def _positive_agreement(n11, n10, n01, n00):
    denominator = 2 * n11 + n10 + n01
    return None if denominator == 0 else float(Fraction(2 * n11, denominator))


def _skipped(estimate):
    """(skipped, total) bootstrap replicates an estimate's note documents
    ('N of M bootstrap replicates skipped'); (0, None) without such a note."""
    match = SKIPPED_RE.search(str(estimate.get("note") or ""))
    return (int(match.group(1)), int(match.group(2))) if match else (0, None)


def _step(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _base_population(population):
    """'ENH_PAIRS(BASE)' -> 'BASE'; other labels unchanged."""
    text = str(population or "")
    match = re.match(r"^ENH_PAIRS\((.+)\)$", text)
    return match.group(1) if match else text


def comparison_variants(label):
    """(v1, v2) named by an R05 comparison label, in label order, or None.
    Accepts full variant names or their first word (static/test/combined)."""
    text = str(label or "")
    found = []
    for variant in core.VARIANTS:
        short = variant.split("_")[0]
        position = text.find(variant)
        if position < 0:
            position = text.find(short)
        if position >= 0:
            found.append((position, variant))
    if len(found) != 2:
        return None
    return tuple(v for _, v in sorted(found))


def holm_adjusted(p_values):
    """key -> Holm step-down adjusted p (running max of min(1, (m - i) p_(i)))."""
    ordered = sorted(p_values.items(), key=lambda item: (item[1], str(item[0])))
    m = len(ordered)
    adjusted = OrderedDict()
    running = 0.0
    for index, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - index) * p))
        adjusted[key] = running
    return adjusted


def _tool_scope(config):
    """stage -> tool -> execution models of the enabled tools (config)."""
    from thesis.recovery_successor_005 import ledger as pg

    return OrderedDict([
        ("static", OrderedDict((name, tuple(s.execution_models)) for name, s in pg.static_settings(config).items())),
        ("dynamic", OrderedDict((name, tuple(s.execution_models)) for name, s in pg.dynamic_settings(config).items())),
    ])


# -- the post-freeze addendum -------------------------------------------------------------------

def addendum_problems(addendum, methodology):
    """Why an addendum document cannot be the one this validation recomputes:
    core.load_addendum's binding rules (schema, status, the frozen
    methodology's canonical sha256, ids unique and disjoint from the frozen
    ids) re-checked on the given document, plus exactly the metrics of
    ADDENDUM_NAMES (an addendum with other metrics would pass unchecked)."""
    problems = []
    if not isinstance(addendum, dict):
        return ["the addendum is not an object"]
    if addendum.get("schema_version") != core.ADDENDUM_SCHEMA or addendum.get("status") != core.ADDENDUM_STATUS:
        problems.append("not a %s addendum with status %s (%r / %r)" % (core.ADDENDUM_SCHEMA, core.ADDENDUM_STATUS,
                                                                        addendum.get("schema_version"),
                                                                        addendum.get("status")))
    amends = addendum.get("amends") or {}
    if amends.get("methodology_canonical_sha256") != canonical_sha256(methodology):
        problems.append("the addendum amends methodology %s, the frozen one is %s"
                        % (amends.get("methodology_canonical_sha256"), canonical_sha256(methodology)))
    if amends.get("methodology") != core.METHODOLOGY_REL:
        problems.append("the addendum names %r, not %s" % (amends.get("methodology"), core.METHODOLOGY_REL))
    declared = OrderedDict((m.get("id"), m.get("name")) for m in addendum.get("metrics") or [] if isinstance(m, dict))
    ids = [m.get("id") for m in addendum.get("metrics") or [] if isinstance(m, dict)]
    if len(ids) != len(set(ids)) or set(ids) & set(core.metric_ids(methodology)):
        problems.append("addendum metric ids are not unique or collide with frozen ids: %s" % ids)
    if list(declared.items()) != list(ADDENDUM_NAMES.items()):
        problems.append("the addendum declares %s, the validation recomputes %s"
                        % (list(declared.items()), list(ADDENDUM_NAMES.items())))
    return problems


def bound_addendum(root, methodology, addendum=None):
    """The addendum the validation uses: the given one (run.py passes the
    document it computed with) or core.load_addendum from root; refuses
    unless addendum_problems is empty."""
    if addendum is None:
        addendum = core.load_addendum(root, methodology=methodology)
    problems = addendum_problems(addendum, methodology)
    if problems:
        raise core.AnalysisRefused("; ".join(problems))
    return addendum


def post_freeze_prefix(addendum):
    """'POST-FREEZE addendum_1 (descriptive): ' for study_analysis_001.addendum_1."""
    return POST_FREEZE_PREFIX % str(addendum.get("addendum_id") or "").split(".")[-1]


def table_title_prefix(addendum):
    """'POST-FREEZE (addendum_1, descriptive): ' (the T12 title, DESIGN2 s2.8)."""
    return TABLE_TITLE_PREFIX % str(addendum.get("addendum_id") or "").split(".")[-1]


def addendum_text(addendum, metric, field):
    for m in addendum.get("metrics") or []:
        if m.get("id") == metric:
            return str(m.get(field) or "")
    raise core.AnalysisRefused("the addendum defines no metric %s" % metric)


def addendum_ci_problems(addendum):
    """ADDENDUM_CI_METRICS must be the addendum metrics whose aggregation
    names a CI ('no CI' does not)."""
    named = sorted(m["id"] for m in addendum.get("metrics") or []
                   if re.search(r"(?<!no )\bCI\b", m.get("aggregation") or ""))
    return [] if named == sorted(ADDENDUM_CI_METRICS) else [
        "the addendum names a CI for %s, the validation demands %s" % (named, sorted(ADDENDUM_CI_METRICS))]


def table_note_texts(addendum, required=("BL01", "DEGENERATE_CI")):
    """table note id -> text of the addendum (the required ids must exist)."""
    notes = OrderedDict((n.get("id"), n.get("text")) for n in addendum.get("table_notes") or [] if isinstance(n, dict))
    for key in required:
        if not isinstance(notes.get(key), str) or not notes[key].strip():
            raise core.AnalysisRefused("the addendum carries no %s table note" % key)
    return notes


# -- dataset index ------------------------------------------------------------------------------

class Index:
    """One pass over the normalized tables (first occurrence wins; the
    uniqueness check reports duplicates)."""

    def __init__(self, dataset):
        self.dataset = dataset
        self.artifacts = dataset.rows("artifacts")
        self.base_cells = dataset.rows("base_cells")
        self.trajectories = dataset.rows("trajectories")
        self.generations = dataset.rows("generations")
        self.entries = dataset.rows("tool_entries")
        self.findings = dataset.rows("findings")
        self.pairs = dataset.rows("enhanced_pairs")
        self.by_id = OrderedDict()
        for row in self.artifacts:
            self.by_id.setdefault(row["artifact_id"], row)
        self.cells = OrderedDict()
        for row in self.base_cells:
            self.cells.setdefault(row["cell_id"], row)
        self.base_of = OrderedDict()
        for row in self.artifacts:
            if row["iteration"] == 0:
                self.base_of.setdefault(row["cell_id"], row)
        self.trajectory = OrderedDict()
        for row in self.trajectories:
            self.trajectory.setdefault((row["cell_id"], row["variant"]), row)
        self.entry = OrderedDict()
        self.entries_of = OrderedDict()
        for row in self.entries:
            self.entry.setdefault((row["artifact_id"], row["stage"], row["tool"]), row)
            self.entries_of.setdefault(row["artifact_id"], []).append(row)
        self.pair_status = OrderedDict()
        for row in self.pairs:
            self.pair_status.setdefault(row["artifact_id"], Counter())[row["status"]] += 1
        self.generation = OrderedDict()
        for row in self.generations:
            self.generation.setdefault(row["artifact_id"], row)

    def block_artifacts(self, block):
        return [a for a in self.artifacts if a["block"] == block]

    def target_artifact(self, trajectory, step=None):
        """FINAL (step None) or STEP k artifact of a trajectory."""
        if step is None:
            return self.by_id.get(trajectory["final_artifact"])
        k = min(step, trajectory["final_iteration"])
        return self.by_id.get(trajectory["artifact_iter%d" % k])


def _group_key(base):
    return (base["block"], base["model_id"], base["execution_model"], base["family"],
            base["benchmark"] == core.BL01_BENCHMARK)


# -- count checks against the independent sources --------------------------------------------------

def composite_count_problems(document, index):
    problems = []
    cells = document.get("cells") or {}
    per_block = Counter(a["block"] for a in index.artifacts)
    base = Counter(a["block"] for a in index.artifacts if a["iteration"] == 0)
    _diff(problems, "cells.total", cells.get("total"), len(index.artifacts))
    for block in core.BLOCKS:
        _diff(problems, "cells.per_block.%s" % block, (cells.get("per_block") or {}).get(block), per_block[block])
        _diff(problems, "cells.base_per_block.%s" % block, (cells.get("base_per_block") or {}).get(block), base[block])
        _diff(problems, "base_cells.%s" % block, (cells.get("base_per_block") or {}).get(block),
              sum(1 for c in index.base_cells if c["block"] == block))
    candidates = OrderedDict((block, OrderedDict()) for block in core.BLOCKS)
    for a in index.artifacts:
        if a["iteration"] >= 1:
            bucket = candidates.setdefault(a["block"], OrderedDict()).setdefault(a["variant"], Counter())
            bucket["iter%d" % a["iteration"]] += 1
    recorded = cells.get("candidates") or {}
    for block in sorted(set(candidates) | set(recorded)):
        for variant in sorted(set(candidates.get(block) or {}) | set(recorded.get(block) or {})):
            mine = dict((candidates.get(block) or {}).get(variant) or {})
            theirs = (recorded.get(block) or {}).get(variant) or {}
            for key in sorted(set(mine) | set(theirs)):
                _diff(problems, "cells.candidates.%s.%s.%s" % (block, variant, key), theirs.get(key),
                      mine.get(key))
    population = document.get("population") or {}
    _diff(problems, "population.base_cells", population.get("base_cells"), len(index.base_cells))
    per_run = Counter(c["base_run"] for c in index.base_cells)
    recorded_runs = population.get("per_run") or {}
    for run in sorted(set(per_run) | set(recorded_runs)):
        _diff(problems, "population.per_run.%s" % run, recorded_runs.get(run), per_run.get(run, 0))
    models = sorted(set(a["model_id"] for a in index.artifacts),
                    key=lambda m: list(core.MODELS).index(m) if m in core.MODELS else len(core.MODELS))
    _diff(problems, "model_ids", document.get("model_ids"), models)
    return problems


def stage_coverage_problems(document, index):
    problems = []
    coverage = document.get("stage_coverage") or {}
    pairs_by_block = Counter()
    statuses_by_block = OrderedDict((block, Counter()) for block in core.BLOCKS)
    for row in index.pairs:
        artifact = index.by_id.get(row["artifact_id"])
        block = artifact["block"] if artifact else "?"
        pairs_by_block[block] += 1
        statuses_by_block.setdefault(block, Counter())[row["status"]] += 1
    for block in core.BLOCKS:
        arts = index.block_artifacts(block)
        recorded = coverage.get(block) or {}
        for stage, column in STAGE_OWNER_COLUMNS.items():
            entry = recorded.get(stage) or {}
            if stage == "enhanced":
                evidence = [a for a in arts if a["enh_pairs"] > 0 and a[column]]
            else:
                evidence = [a for a in arts if a[column]]
            _diff(problems, "%s.%s.cells" % (block, stage), entry.get("cells"), len(arts))
            _diff(problems, "%s.%s.with_evidence" % (block, stage), entry.get("with_evidence"), len(evidence))
            owners = Counter(a[column] for a in evidence)
            theirs = entry.get("owners") or {}
            for owner in sorted(set(owners) | set(theirs)):
                _diff(problems, "%s.%s.owners.%s" % (block, stage, owner), theirs.get(owner), owners.get(owner, 0))
        supplemented = Counter(by for a in arts for by in (a["static_supplemented_by"] or {}).values())
        theirs = (recorded.get("static") or {}).get("supplemented_by") or {}
        for owner in sorted(set(supplemented) | set(theirs)):
            _diff(problems, "%s.static.supplemented_by.%s" % (block, owner), theirs.get(owner),
                  supplemented.get(owner, 0))
        enhanced = recorded.get("enhanced") or {}
        _diff(problems, "%s.enhanced.pairs" % block, enhanced.get("pairs"), pairs_by_block[block])
        _diff(problems, "%s.enhanced.pairs(enh_pairs)" % block, enhanced.get("pairs"), sum(a["enh_pairs"] for a in arts))
        theirs = enhanced.get("statuses") or {}
        mine = statuses_by_block.get(block) or Counter()
        for status in sorted(set(mine) | set(theirs)):
            _diff(problems, "%s.enhanced.statuses.%s" % (block, status), theirs.get(status), mine.get(status, 0))
        gated = sum(n for s, n in theirs.items() if s in core.ENHANCED_GATED)
        _diff(problems, "%s.enhanced.gated(enh_gated)" % block, gated, sum(a["enh_gated"] for a in arts))
        _diff(problems, "%s.enhanced.gated(rows)" % block, gated,
              sum(1 for r in index.pairs if r["gated"] and (index.by_id.get(r["artifact_id"]) or {}).get("block") == block))
    if "?" in pairs_by_block:
        problems.append("%d enhanced pair(s) of unknown artifacts" % pairs_by_block["?"])
    return problems


def census_count_problems(summary, result, index, provenance_digest=None):
    problems = []
    models = list(core.MODELS)
    per_block_loops = len(models) * len(core.VARIANTS)
    total_loops = len(core.BLOCKS) * per_block_loops
    _diff(problems, "total_repair_loops_done", summary.get("total_repair_loops_done"),
          "%d/%d" % (total_loops, total_loops))
    blocks = summary.get("blocks") or {}
    for block in core.BLOCKS:
        entry = blocks.get(block) or {}
        trajectories = [t for t in index.trajectories if t["block"] == block]
        _diff(problems, "%s.loops" % block, entry.get("loops"), per_block_loops)
        _diff(problems, "%s.terminal" % block, entry.get("terminal"), per_block_loops)
        if entry.get("open") or entry.get("not_started"):
            problems.append("%s: open %s, not started %s" % (block, entry.get("open"), entry.get("not_started")))
        states = Counter(t["terminal_status"] for t in trajectories)
        theirs = entry.get("sample_states") or {}
        for status in sorted(set(states) | set(theirs)):
            _diff(problems, "%s.sample_states.%s" % (block, status), theirs.get(status), states.get(status, 0))
        loops = OrderedDict()
        for t in trajectories:
            loops.setdefault((t["model_id"], t["variant"]), set()).add(t["loop_owner"])
        owners = Counter()
        for key, found in loops.items():
            if len(found) != 1:
                problems.append("%s %s/%s: trajectories name %d loop owners %s" % (block, key[0], key[1], len(found),
                                                                                   sorted(found)))
            owners[sorted(found)[0]] += 1
        theirs = entry.get("owners") or {}
        for owner in sorted(set(owners) | set(theirs)):
            _diff(problems, "%s.owners.%s" % (block, owner), theirs.get(owner), owners.get(owner, 0))
        cells = sum(1 for c in index.base_cells if c["block"] == block)
        _diff(problems, "base_cells.%s" % block, (summary.get("base_cells") or {}).get(block), cells)
        _diff(problems, "%s.trajectories" % block, cells * len(core.VARIANTS), len(trajectories))
        _diff(problems, "%s.sample_states.total" % block, sum(theirs_n for theirs_n in
                                                              (entry.get("sample_states") or {}).values()),
              len(trajectories))
    _diff(problems, "base_cells.total", (summary.get("base_cells") or {}).get("total"), len(index.base_cells))
    by_loop = OrderedDict()
    for t in index.trajectories:
        by_loop.setdefault((t["block"], t["model_id"], t["variant"]), []).append(t)
    seen = set()
    for loop in (result or {}).get("loops") or []:
        key = (loop.get("block"), loop.get("model"), loop.get("variant"))
        seen.add(key)
        mine = by_loop.get(key) or []
        _diff(problems, "loop %s/%s/%s samples" % key, loop.get("expected_cells"), len(mine))
        states = Counter(t["terminal_status"] for t in mine)
        theirs = loop.get("status_counts") or {}
        for status in sorted(set(states) | set(theirs)):
            _diff(problems, "loop %s/%s/%s status %s" % (key + (status,)), theirs.get(status), states.get(status, 0))
        owners = sorted(set(t["loop_owner"] for t in mine))
        if owners != [loop.get("owner")]:
            problems.append("loop %s/%s/%s: census owner %s, trajectories %s" % (key + (loop.get("owner"), owners)))
    missing = sorted(set(by_loop) - seen)
    if missing:
        problems.append("trajectories of %d loop(s) the census does not know: %s" % (len(missing), missing[:3]))
    digest = canonical_sha256(summary)
    if provenance_digest is not None and digest != provenance_digest:
        problems.append("census digest %s differs from the dataset provenance %s" % (digest, provenance_digest))
    return problems


def ledger_histories(root, census_result):
    """(block, model, variant, sample_id) -> (owner, [state rows in order],
    request rounds, loop kind) read from the loops' own ledgers (continued
    loops: recovery_001 rows overlaid by the owner rows; request rounds:
    001's iteration 1 + the owner's iteration 2). Every wave state and state
    row must carry its loop's identity (owner resp. recovery_001 for the
    overlaid rows, model, variant) and the kind read from the wave state
    (continued / native) must be the census loop's kind - this reader is
    the independent source of the trajectories, so it refuses what the
    normalizer's reader would refuse."""
    root = Path(root).resolve()
    histories = OrderedDict()
    for loop in census_result.get("loops") or []:
        block, model, variant, owner = loop["block"], loop["model"], loop["variant"], loop.get("owner")
        if not owner:
            raise core.AnalysisRefused("loop %s/%s/%s has no owner" % (block, model, variant))
        directory = cs._repair(root, owner, model, variant)
        wave_path = directory / "wave_state.json"
        if not wave_path.is_file():
            raise core.AnalysisRefused("missing wave state of %s/%s/%s" % (owner, model, variant))
        wave = json.loads(wave_path.read_text(encoding="utf-8"))
        if (wave.get("run_id"), wave.get("model_id"), wave.get("variant")) != (owner, model, variant):
            raise core.AnalysisRefused("foreign wave state in %s/%s/%s: %s/%s/%s" % (
                owner, model, variant, wave.get("run_id"), wave.get("model_id"), wave.get("variant")))
        continued = wave.get("predecessor_run_id") == cs.ORIGIN
        kind = "continued" if continued else "native"
        if loop.get("kind") != kind:
            raise core.AnalysisRefused("loop %s/%s/%s: census kind %r, wave state %s"
                                       % (block, model, variant, loop.get("kind"), kind))
        rows = cs._jsonl(directory / "state.jsonl")
        if any(r.get("run_id") != owner or r.get("model_id") != model or r.get("variant") != variant for r in rows):
            raise core.AnalysisRefused("foreign state row in %s/%s/%s" % (owner, model, variant))
        rounds = _rounds(directory / "request_rounds.json")
        if continued:
            origin = cs._repair(root, cs.ORIGIN, model, variant)
            origin_rows = cs._jsonl(origin / "state.jsonl")
            if any(r.get("run_id") != cs.ORIGIN or r.get("model_id") != model or r.get("variant") != variant
                   for r in origin_rows):
                raise core.AnalysisRefused("foreign %s state row overlaid on %s/%s/%s" % (cs.ORIGIN, owner, model,
                                                                                         variant))
            if any(type(r.get("iteration")) is not int or r["iteration"] < 1 for r in rows):
                raise core.AnalysisRefused("continued owner %s wrote an iteration-0 row" % owner)
            origin_rounds = _rounds(origin / "request_rounds.json")
            for sample_id, entry in origin_rounds.items():
                if set(entry) - {"1"}:
                    raise core.AnalysisRefused("recovery_001 request rounds of a continued loop beyond iteration 1: "
                                               + sample_id)
            for sample_id, entry in rounds.items():
                if set(entry) - {"2"}:
                    raise core.AnalysisRefused("continued owner request rounds outside iteration 2: " + sample_id)
            merged_rounds = OrderedDict()
            for source in (origin_rounds, rounds):
                for sample_id, entry in source.items():
                    merged_rounds[sample_id] = merged_rounds.get(sample_id, 0) + sum(entry.values())
            rows = origin_rows + rows
        else:
            merged_rounds = OrderedDict((sid, sum(entry.values())) for sid, entry in rounds.items())
        per_sample = OrderedDict()
        for row in rows:
            per_sample.setdefault(row["sample_id"], []).append(row)
        for sample_id, history in per_sample.items():
            histories[(block, model, variant, sample_id)] = (owner, history, merged_rounds.get(sample_id, 0), kind)
        stray = [sid for sid in merged_rounds if sid not in per_sample]
        if stray:
            raise core.AnalysisRefused("request rounds for samples without a state row: %s" % stray[:3])
    return histories


def _rounds(path):
    if not Path(path).is_file():
        return OrderedDict()
    document = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    result = OrderedDict()
    for sample_id, entry in document.items():
        if not isinstance(entry, dict) or any(type(v) is not int or v < 0 for v in entry.values()):
            raise core.AnalysisRefused("malformed request rounds entry: %s" % sample_id)
        result[sample_id] = OrderedDict((str(k), v) for k, v in entry.items())
    return result


def ledger_problems(histories, index):
    problems = []
    seen = set()
    for t in index.trajectories:
        base = index.base_of.get(t["cell_id"])
        if base is None:
            problems.append("trajectory %s without a base artifact" % t["trajectory_id"])
            continue
        key = (t["block"], t["model_id"], t["variant"], base["sample_id"])
        seen.add(key)
        if key not in histories:
            problems.append("trajectory %s has no state ledger rows" % t["trajectory_id"])
            continue
        owner, history, rounds, kind = histories[key]
        final = history[-1]
        label = t["trajectory_id"]
        _diff(problems, "%s loop_kind" % label, kind, t["loop_kind"])
        _diff(problems, "%s final_iteration" % label, final.get("iteration"), t["final_iteration"])
        _diff(problems, "%s terminal_status" % label, final.get("status"), t["terminal_status"])
        _diff(problems, "%s stop_reason" % label, final.get("stop_reason") or "", t["stop_reason"])
        verdict = final.get("test_verdict")
        if verdict is None or isinstance(verdict, str):
            _diff(problems, "%s test_verdict_final" % label, verdict or "", t["test_verdict_final"])
        _diff(problems, "%s loop_owner" % label, owner, t["loop_owner"])
        _diff(problems, "%s request_rounds" % label, rounds, t["request_rounds"])
        by_iteration = OrderedDict()
        for row in history:
            by_iteration[row.get("iteration")] = row.get("status")
        iterations = [row.get("iteration") for row in history]
        if iterations != list(range(len(history))):
            problems.append("%s ledger iterations %s are not 0..final" % (label, iterations))
        for k in range(core.MAX_ITERATIONS + 1):
            _diff(problems, "%s status_iter%d" % (label, k), by_iteration.get(k) or "", t["status_iter%d" % k])
    unknown = sorted(set(histories) - seen)
    if unknown:
        problems.append("%d ledger sample(s) without a trajectory: %s" % (len(unknown), unknown[:3]))
    return problems


# -- composite binding ------------------------------------------------------------------------------------

def binding_problems(cells, index):
    """Per artifact: the normalized facts equal the composite cell summary."""
    problems = []
    subsumed = 0
    seen = set()
    for cell in cells:
        artifact_id = core.artifact_id(cell["block"], cell["model_id"], cell["source_run"], cell["sample_id"])
        if artifact_id in seen:
            problems.append("composite cell twice: %s" % artifact_id)
            continue
        seen.add(artifact_id)
        a = index.by_id.get(artifact_id)
        if a is None:
            problems.append("composite cell without an artifact: %s" % artifact_id)
            continue
        for field, expected in (("variant", cell["variant"] or ""), ("iteration", cell["iteration"]),
                                ("execution_model", cell["execution_model"]), ("benchmark", cell["benchmark"]),
                                ("source_sha256", cell["source_sha256"])):
            if a[field] != expected:
                problems.append("%s %s: composite %r, artifact %r" % (artifact_id, field, expected, a[field]))
        correctness = cell.get("correctness")
        if correctness is None:
            problems.append("%s: no correctness evidence in the composite" % artifact_id)
        else:
            if correctness.get("owner") != a["correctness_owner"]:
                problems.append("%s correctness owner: composite %s, artifact %s"
                                % (artifact_id, correctness.get("owner"), a["correctness_owner"]))
            if correctness.get("verdict") != a["correctness_verdict"]:
                problems.append("%s verdict: composite %s, artifact %s"
                                % (artifact_id, correctness.get("verdict"), a["correctness_verdict"]))
        entries = OrderedDict(((row["stage"], row["tool"]), row) for row in index.entries_of.get(artifact_id) or [])
        static = cell.get("static")
        if static is None:
            problems.append("%s: no static evidence in the composite" % artifact_id)
        else:
            if static.get("owner") != a["static_owner"]:
                problems.append("%s static owner: composite %s, artifact %s"
                                % (artifact_id, static.get("owner"), a["static_owner"]))
            if _plain(static.get("supplemented") or {}) != _plain(a["static_supplemented_by"] or {}):
                problems.append("%s static supplements: composite %s, artifact %s"
                                % (artifact_id, _short(static.get("supplemented")), _short(a["static_supplemented_by"])))
            subsumed += _tool_states(problems, artifact_id, a, "static", static.get("tools") or {}, entries)
        dynamic = cell.get("dynamic")
        if dynamic is None:
            problems.append("%s: no dynamic evidence in the composite" % artifact_id)
        else:
            if dynamic.get("owner") != a["dynamic_owner"]:
                problems.append("%s dynamic owner: composite %s, artifact %s"
                                % (artifact_id, dynamic.get("owner"), a["dynamic_owner"]))
            tools = OrderedDict((tool, (entry or {}).get("analysis_state"))
                                for tool, entry in (dynamic.get("tools") or {}).items())
            _tool_states(problems, artifact_id, a, "dynamic", tools, entries)
            for tool, entry in (dynamic.get("tools") or {}).items():
                row = entries.get(("dynamic", tool))
                if row is not None and bool((entry or {}).get("ran")) != bool(row["ran"]):
                    problems.append("%s dynamic %s ran: composite %s, entry %s"
                                    % (artifact_id, tool, (entry or {}).get("ran"), row["ran"]))
        enhanced = cell.get("enhanced")
        statuses = index.pair_status.get(artifact_id) or Counter()
        if enhanced is None:
            if a["enh_pairs"] or statuses:
                problems.append("%s: %d pair(s), the composite holds none" % (artifact_id, a["enh_pairs"]))
        else:
            if enhanced.get("owner") != a["enhanced_owner"]:
                problems.append("%s enhanced owner: composite %s, artifact %s"
                                % (artifact_id, enhanced.get("owner"), a["enhanced_owner"]))
            if enhanced.get("pairs") != a["enh_pairs"] or enhanced.get("pairs") != sum(statuses.values()):
                problems.append("%s enhanced pairs: composite %s, artifact %s, rows %d"
                                % (artifact_id, enhanced.get("pairs"), a["enh_pairs"], sum(statuses.values())))
            if _plain(enhanced.get("statuses") or {}) != _plain(dict(statuses)):
                problems.append("%s enhanced statuses: composite %s, rows %s"
                                % (artifact_id, _short(enhanced.get("statuses")), _short(dict(statuses))))
    missing = [aid for aid in index.by_id if aid not in seen]
    if missing:
        problems.append("%d artifact(s) without a composite cell: %s" % (len(missing), missing[:3]))
    return problems, subsumed


def _tool_states(problems, artifact_id, artifact, stage, composite_tools, entries):
    """Tool states of one stage; returns the number of accepted subsumed
    rejections (see the module docstring)."""
    subsumed = 0
    normalized = OrderedDict((tool, row) for (s, tool), row in entries.items() if s == stage)
    compiler = entries.get(("static", "compiler"))
    for tool, row in normalized.items():
        if tool not in composite_tools:
            if row["state"] != "ABSENT_INAPPLICABLE":
                problems.append("%s %s %s: no composite entry, normalized %s" % (artifact_id, stage, tool, row["state"]))
            continue
        recorded = composite_tools[tool]
        if recorded == row["state"]:
            continue
        if (stage == "static" and tool != "compiler" and row["state"] == "NOT_ANALYZED"
                and recorded in ("TOOL_ERROR", "PARTIAL") and artifact["compile_error"] is True
                and compiler is not None and compiler["state"] == "COMPLETED"
                and compiler["num_reported_blocking"] > 0):
            subsumed += 1
            continue
        problems.append("%s %s %s: composite %s, normalized %s" % (artifact_id, stage, tool, recorded, row["state"]))
    for tool in composite_tools:
        if tool not in normalized:
            problems.append("%s %s %s: composite entry without a normalized entry" % (artifact_id, stage, tool))
    return subsumed


# -- structural checks ------------------------------------------------------------------------------------

def _duplicates(values):
    counts = Counter(values)
    return sorted((key for key, n in counts.items() if n > 1), key=str)


def uniqueness_problems(index):
    problems = []
    checks = OrderedDict([
        ("artifact_id", [a["artifact_id"] for a in index.artifacts]),
        ("base cell_id", [c["cell_id"] for c in index.base_cells]),
        ("trajectory_id", [t["trajectory_id"] for t in index.trajectories]),
        ("(cell, variant)", [(t["cell_id"], t["variant"]) for t in index.trajectories]),
        ("(artifact, spec_key)", [(p["artifact_id"], p["spec_key"]) for p in index.pairs]),
        ("generation artifact_id", [g["artifact_id"] for g in index.generations]),
        ("(artifact, stage, tool)", [(e["artifact_id"], e["stage"], e["tool"]) for e in index.entries]),
        ("(block, model, source_run, sample)", [(a["block"], a["model_id"], a["source_run"], a["sample_id"])
                                                for a in index.artifacts]),
    ])
    for label, values in checks.items():
        duplicates = _duplicates(values)
        if duplicates:
            problems.append("%d duplicate %s: %s" % (len(duplicates), label, [str(d) for d in duplicates[:3]]))
    for t in index.trajectories:
        if t["trajectory_id"] != core.trajectory_id(t["cell_id"], t["variant"]):
            problems.append("trajectory id %s is not core.trajectory_id(cell, variant)" % t["trajectory_id"])
    return problems


def ownership_problems(index):
    problems = []
    for a in index.artifacts:
        aid, block, run = a["artifact_id"], a["block"], a["source_run"]
        entries = index.entries_of.get(aid) or []
        supplemented = a["static_supplemented_by"] or {}
        if block == "pilot":
            for column in STAGE_OWNER_COLUMNS.values():
                if a[column] != core.PILOT:
                    problems.append("%s %s %r is not %s" % (aid, column, a[column], core.PILOT))
            if supplemented:
                problems.append("%s: pilot static supplements %s" % (aid, _short(supplemented)))
            bad = sorted(set(e["owner"] for e in entries if e["owner"] != core.PILOT))
            if bad:
                problems.append("%s: pilot tool entry owners %s" % (aid, bad))
            expected_loop = "" if a["iteration"] == 0 else core.PILOT
            if a["loop_owner"] != expected_loop:
                problems.append("%s loop_owner %r, expected %r" % (aid, a["loop_owner"], expected_loop))
            continue
        if block != "full_ext":
            problems.append("%s: unknown block %r" % (aid, block))
            continue
        if a["static_owner"] != run:
            problems.append("%s static_owner %r is not its own run %s" % (aid, a["static_owner"], run))
        for column in ("correctness_owner", "dynamic_owner"):
            if a[column] not in (run, core.PHASE2):
                problems.append("%s %s %r not in {own run, %s}" % (aid, column, a[column], core.PHASE2))
        if a["enhanced_owner"] != core.PHASE2 and (a["enhanced_owner"] or a["enh_pairs"]):
            problems.append("%s enhanced_owner %r is not %s" % (aid, a["enhanced_owner"], core.PHASE2))
        for row in entries:
            if row["stage"] == "static":
                allowed = (run,) + STATIC_SUPPLEMENTERS
                if row["owner"] not in allowed:
                    problems.append("%s static %s owner %r not allowed" % (aid, row["tool"], row["owner"]))
                if row["owner"] != a["static_owner"] and supplemented.get(row["tool"]) != row["owner"]:
                    problems.append("%s static %s owner %s missing from static_supplemented_by"
                                    % (aid, row["tool"], row["owner"]))
            elif row["owner"] != a["dynamic_owner"]:
                problems.append("%s dynamic %s owner %r differs from the record owner %r"
                                % (aid, row["tool"], row["owner"], a["dynamic_owner"]))
        for tool, by in supplemented.items():
            entry = index.entry.get((aid, "static", tool))
            if by not in STATIC_SUPPLEMENTERS or entry is None or entry["owner"] != by or by == a["static_owner"]:
                problems.append("%s static_supplemented_by %s=%s contradicts the tool entry" % (aid, tool, by))
        if a["iteration"] == 0:
            if a["loop_owner"] != "":
                problems.append("%s: base artifact with loop_owner %r" % (aid, a["loop_owner"]))
        elif a["loop_owner"] not in core.OWNERS:
            problems.append("%s loop_owner %r is not a recovery owner" % (aid, a["loop_owner"]))
    for t in index.trajectories:
        allowed = (core.PILOT,) if t["block"] == "pilot" else tuple(core.OWNERS)
        if t["loop_owner"] not in allowed:
            problems.append("trajectory %s loop_owner %r not allowed" % (t["trajectory_id"], t["loop_owner"]))
    return problems


def _excluded_path(relative):
    parts = str(relative).replace("\\", "/").split("/")
    if len(parts) >= 4 and parts[:2] == ["thesis", "results"] and parts[3] in core.EXCLUDED_RUNS:
        return True
    # EXCLUDE_ALL_PARENT_REPAIR: the aborted repair inside the base run
    return (len(parts) >= 6 and parts[:2] == ["thesis", "results"] and parts[3] == core.PARENT
            and parts[5] == "repair")


def excluded_problems(index, files=()):
    problems = []
    excluded = set(core.EXCLUDED_RUNS)
    for a in index.artifacts:
        values = [a["source_run"], a["loop_owner"]] + [a[c] for c in STAGE_OWNER_COLUMNS.values()] + \
            list((a["static_supplemented_by"] or {}).values())
        hit = sorted(set(v for v in values if v in excluded))
        if hit:
            problems.append("%s references excluded run(s) %s" % (a["artifact_id"], hit))
    for row in index.entries:
        if row["owner"] in excluded:
            problems.append("tool entry %s/%s owned by an excluded run" % (row["artifact_id"], row["tool"]))
    for t in index.trajectories:
        if t["loop_owner"] in excluded:
            problems.append("trajectory %s owned by an excluded run" % t["trajectory_id"])
    for g in index.generations:
        if any(run in g["artifact_id"].split("|") for run in excluded):
            problems.append("generation of an excluded run: %s" % g["artifact_id"])
    for relative in files:
        if _excluded_path(relative):
            problems.append("an excluded run's file was read: %s" % relative)
    return problems


def block_problems(index):
    problems = []
    benchmarks = OrderedDict((block, set()) for block in core.BLOCKS)
    for a in index.artifacts:
        aid, block, run, iteration = a["artifact_id"], a["block"], a["source_run"], a["iteration"]
        if block not in core.BLOCKS:
            problems.append("%s: unknown block %r" % (aid, block))
            continue
        benchmarks[block].add(a["benchmark"])
        if aid != core.artifact_id(block, a["model_id"], run, a["sample_id"]):
            problems.append("%s is not core.artifact_id(...)" % aid)
        if a["cell_id"] != core.cell_id(block, a["model_id"], a["sample_id"]):
            problems.append("%s cell_id %s is not core.cell_id(...)" % (aid, a["cell_id"]))
        if a["family"] != core.family_of(a["benchmark"]):
            problems.append("%s family %s does not match its benchmark" % (aid, a["family"]))
        if iteration == 0:
            if run != core.BLOCK_BASE_RUN[block] or a["variant"] != "":
                problems.append("%s: base artifact of run %s variant %r" % (aid, run, a["variant"]))
            continue
        if a["variant"] not in core.VARIANTS or not 1 <= iteration <= core.MAX_ITERATIONS:
            problems.append("%s: variant %r iteration %r outside the design" % (aid, a["variant"], iteration))
            continue
        owners = (core.PILOT,) if block == "pilot" else tuple(core.OWNERS)
        expected = [pt.iteration_run(owner, a["variant"], iteration) for owner in owners]
        if run not in expected:
            problems.append("%s: run %s is not a %s iteration run of %s/%d" % (aid, run, block, a["variant"], iteration))
        elif block == "full_ext":
            maker = run.split("__")[0]
            if maker != a["loop_owner"] and not (iteration == 1 and maker == pl.ORIGIN):
                problems.append("%s: run %s does not belong to its loop owner %s" % (aid, run, a["loop_owner"]))
    overlap = sorted(benchmarks["pilot"] & benchmarks["full_ext"])
    if overlap:
        problems.append("benchmarks in both blocks: %s" % overlap[:5])
    for c in index.base_cells:
        if c["block"] in core.BLOCKS and c["base_run"] != core.BLOCK_BASE_RUN[c["block"]]:
            problems.append("base cell %s of run %s" % (c["cell_id"], c["base_run"]))
        if c["bl01"] != (c["benchmark"] == core.BL01_BENCHMARK):
            problems.append("base cell %s bl01 flag contradicts its benchmark" % c["cell_id"])
        if not c["cell_id"].startswith(c["block"] + "|"):
            problems.append("base cell %s does not carry its block" % c["cell_id"])
    for t in index.trajectories:
        cell = index.cells.get(t["cell_id"])
        if cell is None or cell["block"] != t["block"] or cell["model_id"] != t["model_id"]:
            problems.append("trajectory %s block/model differ from its base cell" % t["trajectory_id"])
    return problems, OrderedDict((b, len(v)) for b, v in benchmarks.items())


def table_problems(table, index):
    problems = []
    expected = OrderedDict()
    for target in table.targets:
        for sample_id, facts in target.samples.items():
            aid = core.artifact_id("full_ext", target.model_id, target.source_run, sample_id)
            expected[aid] = (target, facts)
    actual = set(a["artifact_id"] for a in index.artifacts if a["block"] == "full_ext")
    missing = sorted(set(expected) - actual)
    extra = sorted(actual - set(expected))
    if missing:
        problems.append("%d target sample(s) without an artifact: %s" % (len(missing), missing[:3]))
    if extra:
        problems.append("%d full_ext artifact(s) outside the target table: %s" % (len(extra), extra[:3]))
    for aid, (target, facts) in expected.items():
        a = index.by_id.get(aid)
        if a is None:
            continue
        for field, value in (("execution_model", facts["execution_model"]), ("benchmark", facts["benchmark"]),
                             ("source_sha256", facts["source_sha256"]), ("variant", target.variant or ""),
                             ("iteration", target.iteration), ("loop_owner", target.loop_owner or "")):
            if a[field] != value:
                problems.append("%s %s: table %r, artifact %r" % (aid, field, value, a[field]))
    return problems


def consistency_problems(index, scope):
    problems = []
    base_ids = set(a["cell_id"] for a in index.artifacts if a["iteration"] == 0)
    cell_ids = set(index.cells)
    if base_ids != cell_ids:
        problems.append("base cells %d differ from the iteration-0 artifacts %d (sym. diff %s)"
                        % (len(cell_ids), len(base_ids), sorted(base_ids ^ cell_ids)[:3]))
    for cell_id, cell in index.cells.items():
        base = index.base_of.get(cell_id)
        if base is None:
            continue
        for field in ("block", "model_id", "benchmark", "family", "execution_model", "sample_id", "source_sha256"):
            if cell[field] != base[field]:
                problems.append("base cell %s %s differs from its artifact" % (cell_id, field))
    for a in index.artifacts:
        base = index.base_of.get(a["cell_id"])
        if base is None:
            problems.append("%s: its cell has no base artifact" % a["artifact_id"])
            continue
        for field in ("block", "model_id", "benchmark", "execution_model", "sample_id"):
            if a[field] != base[field]:
                problems.append("%s %s differs from its base artifact" % (a["artifact_id"], field))
    generated = set(index.generation)
    if generated != set(index.by_id):
        problems.append("generations cover %d of %d artifacts (sym. diff %s)"
                        % (len(generated & set(index.by_id)), len(index.by_id), sorted(generated ^ set(index.by_id))[:3]))
    for g in index.generations:
        a = index.by_id.get(g["artifact_id"])
        if a is not None and bool(a["generation_success"]) != bool(g["success"]):
            problems.append("%s generation_success contradicts its generation record" % g["artifact_id"])
        if a is not None and g["kind"] != ("base" if a["iteration"] == 0 else "repair"):
            problems.append("generation %s kind %s contradicts iteration %d" % (g["artifact_id"], g["kind"], a["iteration"]))
        if g["timing_mode"] != "direct" and g["duration_seconds"] is not None:
            problems.append("generation %s carries a %s duration" % (g["artifact_id"], g["timing_mode"]))
    expected_trajectories = set((c, v) for c in cell_ids for v in core.VARIANTS)
    if set(index.trajectory) != expected_trajectories:
        problems.append("trajectories %d differ from base cells x variants %d"
                        % (len(index.trajectory), len(expected_trajectories)))
    finding_counts = Counter((f["artifact_id"], f["stage"], f["tool"], f["kind"]) for f in index.findings)
    entry_keys = set(index.entry)
    stray = sorted(set((k[0], k[1], k[2]) for k in finding_counts) - entry_keys)
    if stray:
        problems.append("%d finding group(s) without a tool entry: %s" % (len(stray), stray[:3]))
    for f in index.findings:
        if f["kind"] not in core.FINDING_KINDS:
            problems.append("finding of %s/%s with kind %r" % (f["artifact_id"], f["tool"], f["kind"]))
            break
    cleaning = [c for c in core.SCHEMAS["artifacts"] if c.startswith("clean_") and c not in
                ("clean_any", "clean_any_including_fence")]
    for a in index.artifacts:
        aid = a["artifact_id"]
        if a["correctness_verdict"] not in core.CORRECTNESS_VERDICTS:
            problems.append("%s verdict %r outside the vocabulary" % (aid, a["correctness_verdict"]))
        statuses = index.pair_status.get(aid) or Counter()
        unknown = [s for s in statuses if s not in core.ENHANCED_STATUSES]
        if unknown:
            problems.append("%s enhanced statuses outside the vocabulary: %s" % (aid, unknown))
        pairs = sum(statuses.values())
        gated = sum(n for s, n in statuses.items() if s in core.ENHANCED_GATED)
        valid = pairs - gated
        expected = OrderedDict([("enh_pairs", pairs), ("enh_gated", gated), ("enh_valid", valid)])
        for status in core.ENHANCED_STATUSES:
            if status not in core.ENHANCED_GATED:
                expected["enh_" + status] = statuses.get(status, 0)
        expected["enh_all_pass"] = None if valid == 0 else (1 if statuses.get("pass", 0) == valid else 0)
        for column, value in expected.items():
            if a.get(column) != value:
                problems.append("%s %s %r, the pair rows give %r" % (aid, column, a.get(column), value))
        any_flag = any(a[c] for c in cleaning if c != "clean_used_fence")
        if a["clean_any"] != any_flag or a["clean_any_including_fence"] != any(a[c] for c in cleaning):
            problems.append("%s clean_any flags contradict the cleaning columns" % aid)
        entries = OrderedDict(((r["stage"], r["tool"]), r) for r in index.entries_of.get(aid) or [])
        for stage, tools in scope.items():
            for tool, models in tools.items():
                row = entries.get((stage, tool))
                if row is None:
                    problems.append("%s: no %s entry for %s" % (aid, stage, tool))
                    continue
                if row["applicable"] != (a["execution_model"] in models):
                    problems.append("%s %s %s applicable=%s contradicts the config" % (aid, stage, tool, row["applicable"]))
                if row["state"] not in core.TOOL_STATES:
                    problems.append("%s %s %s state %r outside the vocabulary" % (aid, stage, tool, row["state"]))
                if row["state"] == "ABSENT_INAPPLICABLE" and row["applicable"]:
                    problems.append("%s %s %s: ABSENT entry for an applicable tool" % (aid, stage, tool))
                counts = [finding_counts.get((aid, stage, tool, kind), 0) for kind in core.FINDING_KINDS]
                recorded = [row["num_reported_blocking"], row["num_low_confidence"], row["num_non_blocking"]]
                if counts != recorded or row["num_findings"] != sum(counts):
                    problems.append("%s %s %s counts %s/%s, finding rows %s" % (aid, stage, tool, recorded,
                                                                                 row["num_findings"], counts))
        extra = [key for key in entries if key[1] not in scope.get(key[0], {})]
        if extra:
            problems.append("%s: tool entries outside the config %s" % (aid, extra))
        compiler = entries.get(("static", "compiler"))
        if compiler is not None and a["compile_error"] != (compiler["num_reported_blocking"] > 0):
            problems.append("%s compile_error contradicts the compiler entry" % aid)
        low = any(r["num_low_confidence"] > 0 for r in entries.values())
        if a["low_confidence_any"] != low:
            problems.append("%s low_confidence_any contradicts the tool entries" % aid)
    return problems


def three_state(rows):
    """(verdict, complete) over the applicable entries of one stage."""
    applicable = [r for r in rows if r["applicable"]]
    if any(r["num_reported_blocking"] > 0 for r in applicable):
        verdict = "DIRTY"
    elif any(r["state"] in core.GAP_STATES for r in applicable):
        verdict = "NO_FINDING_INCOMPLETE"
    else:
        verdict = "CLEAN_COMPLETE"
    complete = all(r["state"] == "COMPLETED" for r in applicable)
    return verdict, complete


def applicability_problems(index):
    problems = []
    gaps_inapplicable = 0
    for a in index.artifacts:
        rows = index.entries_of.get(a["artifact_id"]) or []
        for row in rows:
            if row["applicable"] and row["state"] in core.INAPPLICABLE_STATES:
                problems.append("%s %s %s: applicable tool in the inapplicable state %s"
                                % (a["artifact_id"], row["stage"], row["tool"], row["state"]))
            if not row["applicable"] and row["state"] in core.GAP_STATES:
                gaps_inapplicable += 1
        static = [r for r in rows if r["stage"] == "static" and r["tool"] in core.STATIC_ANALYSIS_TOOLS]
        dynamic = [r for r in rows if r["stage"] == "dynamic" and r["tool"] in core.DYNAMIC_TOOLS]
        for label, stage_rows, verdict_column, complete_column in (
                ("static", static, "static_three_state", "static_analysis_complete"),
                ("dynamic", dynamic, "dynamic_three_state", "dynamic_analysis_complete")):
            verdict, complete = three_state(stage_rows)
            if a[verdict_column] != verdict:
                problems.append("%s %s: recomputed %s, normalized %s" % (a["artifact_id"], verdict_column, verdict,
                                                                         a[verdict_column]))
            if a[complete_column] != complete:
                problems.append("%s %s: recomputed %s, normalized %s" % (a["artifact_id"], complete_column, complete,
                                                                         a[complete_column]))
    return problems, gaps_inapplicable


def gate_problems(index):
    problems = []
    groups = OrderedDict()
    for row in index.pairs:
        a = index.by_id.get(row["artifact_id"])
        if a is None:
            continue
        key = (a["block"], a["benchmark"], row["spec_key"], a["execution_model"])
        groups.setdefault(key, set()).add(bool(row["gated"]))
        if bool(row["gated"]) != (row["status"] in core.ENHANCED_GATED):
            problems.append("pair %s/%s gated=%s contradicts status %s" % (row["artifact_id"], row["spec_key"][:40],
                                                                          row["gated"], row["status"]))
    mixed = [key for key, flags in groups.items() if len(flags) > 1]
    if mixed:
        problems.append("%d mixed gate group(s): %s" % (len(mixed), [list(k) for k in mixed[:3]]))
    for a in index.artifacts:
        base = index.base_of.get(a["cell_id"])
        if base is not None and (a["enh_pairs"], a["enh_valid"]) != (base["enh_pairs"], base["enh_valid"]):
            problems.append("%s: pairs/valid %s differ from its base cell %s"
                            % (a["artifact_id"], (a["enh_pairs"], a["enh_valid"]), (base["enh_pairs"], base["enh_valid"])))
    gated_groups = Counter(key[0] for key, flags in groups.items() if True in flags)
    return problems, OrderedDict([("groups", len(groups)), ("gated_groups", sum(gated_groups.values())),
                                  ("gated_groups_per_block", OrderedDict((b, gated_groups.get(b, 0)) for b in core.BLOCKS))])


def trajectory_problems(index):
    problems = []
    referenced = Counter()
    for t in index.trajectories:
        label = t["trajectory_id"]
        if t["variant"] not in core.VARIANTS:
            problems.append("%s variant %r" % (label, t["variant"]))
            continue
        final = t["final_iteration"]
        if type(final) is not int or not 0 <= final <= core.MAX_ITERATIONS:
            problems.append("%s final_iteration %r outside 0..%d" % (label, final, core.MAX_ITERATIONS))
            continue
        base = index.base_of.get(t["cell_id"])
        if base is None or t["artifact_iter0"] != base["artifact_id"]:
            problems.append("%s artifact_iter0 is not the base artifact" % label)
        for k in range(1, core.MAX_ITERATIONS + 1):
            aid = t["artifact_iter%d" % k]
            if k <= final:
                a = index.by_id.get(aid)
                if a is None:
                    problems.append("%s artifact_iter%d %r does not exist" % (label, k, aid))
                    continue
                referenced[aid] += 1
                if a["cell_id"] != t["cell_id"] or a["variant"] != t["variant"] or a["iteration"] != k:
                    problems.append("%s artifact_iter%d is %s/%s/%s" % (label, k, a["cell_id"], a["variant"],
                                                                        a["iteration"]))
                if a["loop_owner"] != t["loop_owner"]:
                    problems.append("%s artifact_iter%d loop owner %s, trajectory %s" % (label, k, a["loop_owner"],
                                                                                         t["loop_owner"]))
            elif aid != "":
                problems.append("%s artifact_iter%d %r beyond the final iteration %d" % (label, k, aid, final))
        for k in range(core.MAX_ITERATIONS + 1):
            status = t["status_iter%d" % k]
            if k < final and status != "active":
                problems.append("%s status_iter%d %r before the final iteration" % (label, k, status))
            if k > final and status != "":
                problems.append("%s status_iter%d %r beyond the final iteration" % (label, k, status))
        if t["final_artifact"] != t["artifact_iter%d" % final]:
            problems.append("%s final_artifact %s is not artifact_iter%d" % (label, t["final_artifact"], final))
        if t["terminal_status"] != t["status_iter%d" % final] or t["terminal_status"] not in core.TERMINAL_STATUSES:
            problems.append("%s terminal_status %r (status_iter%d %r)" % (label, t["terminal_status"], final,
                                                                         t["status_iter%d" % final]))
        if type(t["request_rounds"]) is not int or t["request_rounds"] < 0:
            problems.append("%s request_rounds %r" % (label, t["request_rounds"]))
    candidates = set(a["artifact_id"] for a in index.artifacts if a["iteration"] >= 1)
    twice = sorted(aid for aid, n in referenced.items() if n > 1)
    if twice:
        problems.append("%d candidate(s) referenced twice: %s" % (len(twice), twice[:3]))
    unreferenced = sorted(candidates - set(referenced))
    if unreferenced:
        problems.append("%d candidate(s) no trajectory selects: %s" % (len(unreferenced), unreferenced[:3]))
    return problems


# -- independent recomputation ---------------------------------------------------------------------------------

class NotRecomputable(Exception):
    """An estimate whose (metric, population, strata) the independent
    recomputation does not define: a foreign label or value, an unknown
    strata key or category. recompute_problems reports it as a FAIL."""


def _y_q06(a):
    verdict = a["correctness_verdict"]
    if verdict in core.CORRECTNESS_EXCLUDED:
        return None
    return 1 if verdict == PASS_VERDICT else 0


def _y_e02(a):
    return None if a["enh_valid"] == 0 else (1 if a["enh_all_pass"] == 1 else 0)


ENDPOINT_Y = OrderedDict([("Q06", _y_q06), ("E02", _y_e02)])


class Recompute:
    """Every estimate from the dataset alone.

    Ratio metrics: per (metric, population, variant, step, category,
    iteration) the units are aggregated once at the finest group (block,
    model, execution model, family, bl01) together with the benchmark
    clusters that carry them; an estimate's filters sum the matching groups
    (numerator, denominator, carrying clusters -> interval support). The
    other metrics (F05, F06, C01-C05, the G01 difference) have their own
    cached tables. expected(estimate) returns every fact the estimate must
    carry; NotRecomputable for a shape the methodology does not define."""

    ARTIFACT_METRICS = ("Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09", "Q10", "E01", "E02", "E03",
                        "E04", "E05", "F01", "F02", "F03", "F04", "S01", "S02", "S03", "D01", "D02", "D03", "G02")
    CELL_METRICS = ("R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10", "G01")
    CELL_POPULATIONS = OrderedDict([("R01", ("FINAL", "STEP")), ("R02", ("FINAL", "STEP")), ("R03", ("FINAL", "STEP")),
                                    ("R04", ("FINAL", "STEP")), ("R05", ("FINAL", "STEP")), ("G01", ("FINAL",)),
                                    ("R06", ("TRAJECTORIES",)), ("R07", ("TRAJECTORIES",)),
                                    ("R08", ("TRAJECTORIES",)), ("R09", ("TRAJECTORIES",)),
                                    ("R10", ("TRAJECTORIES",))])

    def __init__(self, index, methodology=None, addendum=None):
        self.index = index
        self._methodology = methodology
        self._addendum = addendum
        self.tables = {}
        self.sums = {}
        self._cache = {}
        self._x_cache = {}

    def _memo(self, key, build):
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    # dataset / methodology facts ------------------------------------------------------------------
    def methodology(self):
        if self._methodology is None:
            self._methodology = core.load_methodology()
        return self._methodology

    def addendum(self):
        if self._addendum is None:
            self._addendum = core.load_addendum(methodology=self.methodology())
        return self._addendum

    def _metric_text(self, metric, field):
        for m in self.methodology().get("metrics") or []:
            if m.get("id") == metric:
                return str(m.get(field) or "")
        raise core.AnalysisRefused("the methodology defines no metric %s" % metric)

    def models(self):
        return self._memo(("models",), lambda: frozenset(c["model_id"] for c in self.index.base_cells))

    def families(self):
        return self._memo(("families",), lambda: frozenset(c["family"] for c in self.index.base_cells))

    def finding_families(self):
        """The frozen finding-class vocabulary (finding_rules.families)."""
        def build():
            parts = str(self.methodology()["finding_rules"].get("families") or "").split("->")
            families = frozenset(f.strip() for f in parts[-1].split(",") if f.strip()) if len(parts) == 2 else None
            if not families:
                raise core.AnalysisRefused("the methodology states no finding-family list")
            return families
        return self._memo(("finding_families",), build)

    def f06_definitions(self):
        """frozenset(tool pair) -> (family classes, execution models), parsed
        from the methodology's F06 text ('(a, b) class[/+class] on <em|all>')."""
        def build():
            text = self._metric_text("F06", "meaning")
            found = re.findall(r"\((\w+), (\w+)\) ([a-z_]+(?:[/+][a-z_]+)*) on (\w+)", text)
            if not found:
                raise core.AnalysisRefused("the methodology F06 text names no tool pair")
            definitions = OrderedDict()
            for first, second, classes, scope in found:
                models = core.EXECUTION_MODELS if scope == "all" else (scope,)
                if first not in TOOL_STAGE or second not in TOOL_STAGE or not set(models) <= set(core.EXECUTION_MODELS):
                    raise core.AnalysisRefused("the methodology F06 pair (%s, %s) on %s is unknown" % (first, second,
                                                                                                      scope))
                definitions[frozenset((first, second))] = (frozenset(re.split(r"[/+]", classes)), tuple(models))
            return definitions
        return self._memo(("f06",), build)

    def c05_scales(self):
        """{'output_tokens': n, 'records': n}: the C05 scales of the methodology
        text ('per 1,000,000 repair output tokens and per 100 repair requests')."""
        def build():
            text = self._metric_text("C05", "meaning")
            tokens = re.findall(r"per ([\d,]+) repair output tokens", text)
            requests = re.findall(r"per ([\d,]+) repair requests", text)
            if len(tokens) != 1 or len(requests) != 1:
                raise core.AnalysisRefused("the methodology C05 text does not state both scales")
            return OrderedDict([("output_tokens", int(tokens[0].replace(",", ""))),
                                ("records", int(requests[0].replace(",", "")))])
        return self._memo(("c05",), build)

    def clusters(self):
        """(benchmark -> block, stratum sizes, SA1 stratum sizes): the
        bootstrap clusters are the benchmarks of the base cells, stratified by
        block; SA1 resamples the clusters without the BL-01 benchmark."""
        def build():
            block_of = OrderedDict()
            for c in self.index.base_cells:
                block_of.setdefault(c["benchmark"], c["block"])
            sizes = Counter(block_of.values())
            sa1 = Counter(b for benchmark, b in block_of.items() if benchmark != core.BL01_BENCHMARK)
            return block_of, sizes, sa1
        return self._memo(("clusters",), build)

    def _supported(self, carrying, sa1):
        block_of, sizes, sa1_sizes = self.clusters()
        use = sa1_sizes if sa1 else sizes
        return len(carrying) >= SUPPORT_MIN and all(use.get(block_of.get(c), 0) >= SUPPORT_MIN for c in carrying)

    def q06_eligible(self, cell_id):
        """Paired Q06 cohort: no artifact of the cell's trajectories (base and
        every candidate of every variant) is baseline_incompatible."""
        def build():
            index = self.index
            eligible = OrderedDict((cid, _y_q06(base) is not None) for cid, base in index.base_of.items())
            for t in index.trajectory.values():
                final = t["final_iteration"]
                if type(final) is not int or not 0 <= final <= core.MAX_ITERATIONS:
                    raise core.AnalysisRefused("trajectory %s final_iteration %r" % (t["trajectory_id"], final))
                for k in range(final + 1):
                    a = index.by_id.get(t["artifact_iter%d" % k])
                    if a is None:
                        raise core.AnalysisRefused("trajectory %s selects no artifact at iteration %d"
                                                   % (t["trajectory_id"], k))
                    if _y_q06(a) is None:
                        eligible[t["cell_id"]] = False
            return eligible
        return self._memo(("q06_eligible",), build).get(cell_id, False)

    def _paired_y(self, endpoint, cell_id, a):
        if endpoint == "Q06":
            return (1 if a["correctness_verdict"] == PASS_VERDICT else 0) if self.q06_eligible(cell_id) else None
        if endpoint == "E02":
            return _y_e02(a)
        raise NotRecomputable("paired endpoint %r" % (endpoint,))

    def _r01_state(self, endpoint, cell_id, a):
        if endpoint in ("Q06", "E02"):
            y = self._paired_y(endpoint, cell_id, a)
            return None if y is None else R01_STATES[endpoint][0 if y == 1 else 1]
        return a["static_three_state" if endpoint == "F01" else "dynamic_three_state"]

    def _entry(self, aid, tool):
        row = self.index.entry.get((aid, TOOL_STAGE[tool], tool))
        if row is None:
            raise core.AnalysisRefused("no %s entry for %s" % (tool, aid))
        return row

    def _finding_counts(self):
        def build():
            counts = OrderedDict()
            for f in self.index.findings:
                counts.setdefault(f["artifact_id"], Counter())[(f["tool"], f["family"], f["kind"])] += 1
            return counts
        return self._memo(("finding_counts",), build)

    def _blocking(self):
        def build():
            blocking = OrderedDict()
            for f in self.index.findings:
                if f["kind"] == "reported_blocking":
                    blocking.setdefault(f["artifact_id"], {}).setdefault(f["tool"], set()).add(f["family"])
            return blocking
        return self._memo(("blocking",), build)

    def _pair_gates(self):
        def build():
            gates = OrderedDict()
            for row in self.index.pairs:
                gates.setdefault(row["artifact_id"], []).append((row["spec_key"], bool(row["gated"])))
            return gates
        return self._memo(("pair_gates",), build)

    @staticmethod
    def _in(row, block, model=None):
        return (block == core.COMPOSITE or row["block"] == block) and (model is None or row["model_id"] == model)

    def _check_filters(self, strata):
        for key, known in (("model_id", self.models()), ("execution_model", core.EXECUTION_MODELS),
                           ("family", self.families())):
            value = strata.get(key)
            if value is not None and value not in known:
                raise NotRecomputable("foreign %s %r" % (key, value))
        if strata.get("sensitivity") not in (None, "SA1"):
            raise NotRecomputable("sensitivity %r" % (strata.get("sensitivity"),))
        variant = strata.get("variant")
        if variant is not None and variant not in core.VARIANTS:
            raise NotRecomputable("variant %r" % (variant,))
        for key in ("step", "iteration"):
            if key in strata:
                value = _step(strata[key])
                if value is None or not 0 <= value <= core.MAX_ITERATIONS:
                    raise NotRecomputable("%s %r" % (key, strata[key]))

    # units ----------------------------------------------------------------------------------------------
    def _artifact_units(self, population, variant, step, iteration=None):
        index = self.index
        if population in ("BASE", "FINAL", "STEP") and iteration is not None:
            raise NotRecomputable("%s with an iteration" % population)
        if population == "BASE":
            if variant is not None or step is not None:
                raise NotRecomputable("BASE with variant/step")
            return [a for a in index.artifacts if a["iteration"] == 0]
        if population == "GENERATED":
            if variant is not None or step is not None:
                raise NotRecomputable("GENERATED with variant/step")
            return [a for a in index.artifacts if iteration is None or a["iteration"] == iteration]
        if population == "REPAIR_CANDIDATES":
            if step is not None:
                raise NotRecomputable("REPAIR_CANDIDATES with step")
            return [a for a in index.artifacts if a["iteration"] >= 1 and (variant is None or a["variant"] == variant)
                    and (iteration is None or a["iteration"] == iteration)]
        if population in ("FINAL", "STEP"):
            if variant is None or (population == "STEP") != (step is not None):
                raise NotRecomputable("%s needs variant%s" % (population, " and step" if population == "STEP" else ""))
            units = []
            for t in index.trajectories:
                if t["variant"] == variant:
                    target = index.target_artifact(t, step)
                    if target is None:
                        raise core.AnalysisRefused("trajectory %s selects no artifact" % t["trajectory_id"])
                    units.append(target)
            return units
        raise NotRecomputable("population %r" % population)

    def _artifact_value(self, metric, a, category):
        index = self.index
        y = _y_q06(a)
        if metric == "Q01":
            g = index.generation.get(a["artifact_id"])
            if g is None:
                raise core.AnalysisRefused("no generation for " + a["artifact_id"])
            return int(bool(g["success"])), 1
        if metric == "Q02":
            return int(a["assembled"]), 1
        if metric == "Q03":
            return int(a["generation_truncated"]), 1
        if metric == "Q04":
            flag = str(category)
            column = flag if flag.startswith("clean_") else "clean_" + flag
            if column not in a:
                raise NotRecomputable("cleaning flag %r" % category)
            return (int(bool(a[column])) if a["assembled"] else 0), int(bool(a["assembled"]))
        if metric == "Q05":
            return int(a["build_ok"]), 1
        if metric == "Q06":
            return (0, 0) if y is None else (y, 1)
        if metric == "Q07":
            return (0, 0) if y is None or not a["build_ok"] else (y, 1)
        if metric == "Q08":
            if category not in core.CORRECTNESS_VERDICTS:
                raise NotRecomputable("verdict %r" % (category,))
            return int(a["correctness_verdict"] == category), 1
        if metric == "Q09":
            # raw-clean = assembled without any cleaning intervention (Q04 applies to assembled artifacts)
            return (0, 0) if y is None or not a["assembled"] or a["clean_any_including_fence"] else (y, 1)
        if metric == "Q10":
            return (0, 0) if y is None or a["clean_auto_closed"] else (y, 1)
        if metric == "E01":
            return a["enh_pass"], a["enh_valid"]
        if metric == "E02":
            e = _y_e02(a)
            return (0, 0) if e is None else (e, 1)
        if metric == "E03":
            if category not in core.ENHANCED_STATUSES:
                raise NotRecomputable("enhanced status %r" % (category,))
            return (index.pair_status.get(a["artifact_id"]) or Counter()).get(category, 0), a["enh_pairs"]
        if metric == "E04":
            return a["enh_gated"], a["enh_pairs"]
        if metric == "E05":
            e = _y_e02(a)
            return (0, 0) if e is None or y != 1 else (e, 1)
        if metric in ("F01", "F02"):
            if category not in core.THREE_STATE:
                raise NotRecomputable("three-state %r" % (category,))
            return int(a["static_three_state" if metric == "F01" else "dynamic_three_state"] == category), 1
        if metric == "F03":
            return int(a["compile_error"]), 1
        if metric == "F04":
            return int(a["low_confidence_any"]), 1
        if metric == "S03":
            return int(a["static_analysis_complete"]), 1
        if metric == "D03":
            return int(a["dynamic_analysis_complete"]), 1
        if metric in ("S01", "S02", "D01", "D02"):
            tool, state = category
            stage = "static" if metric[0] == "S" else "dynamic"
            if TOOL_STAGE.get(tool) != stage or (state is not None and state not in core.TOOL_STATES):
                raise NotRecomputable("%s tool %r state %r" % (metric, tool, state))
            row = self._entry(a["artifact_id"], tool)
            if metric in ("S01", "D01"):
                return int(row["state"] == state), 1
            return int(bool(row["applicable"]) and row["state"] == COMPLETED), int(bool(row["applicable"]))
        raise NotRecomputable(metric)

    def _cell_value(self, metric, base, t, others, category, step, iteration):
        index = self.index
        cell_id = base["cell_id"]
        if metric in ("R06", "R07", "R08", "R09", "R10"):
            status = t["terminal_status"]
            if metric == "R06":
                return int(status == category and (iteration is None or t["final_iteration"] == iteration)), 1
            if metric == "R07":
                return int(status == "stopped_budget"), 1
            if metric == "R08":
                return int(status == "stopped_analysis_incomplete"), 1
            if metric == "R09":
                return int(t["final_iteration"] >= 1), 1
            return t["final_iteration"], 1
        target = index.target_artifact(t, step)
        if target is None:
            raise core.AnalysisRefused("trajectory %s selects no artifact" % t["trajectory_id"])
        if metric == "G01":
            improved = self._paired_y("Q06", cell_id, base) == 0 and self._paired_y("Q06", cell_id, target) == 1
            e = _y_e02(target)
            return (0, 0) if not improved or e is None else (e, 1)
        if metric == "R01":
            endpoint, (x, y) = category
            sb, st = self._r01_state(endpoint, cell_id, base), self._r01_state(endpoint, cell_id, target)
            return (0, 0) if sb is None or st is None else (int((sb, st) == (x, y)), 1)
        endpoint = category[0] if isinstance(category, tuple) else category
        if endpoint not in ENDPOINT_Y:
            raise NotRecomputable("endpoint %r" % (endpoint,))
        if metric == "R05":
            first, second = (index.target_artifact(other, step) for other in others)
            if first is None or second is None:
                raise core.AnalysisRefused("cell %s: a compared trajectory selects no artifact" % cell_id)
            y1, y2 = self._paired_y(endpoint, cell_id, first), self._paired_y(endpoint, cell_id, second)
            return (0, 0) if y1 is None or y2 is None else (y1 - y2, 1)
        yb, yt = self._paired_y(endpoint, cell_id, base), self._paired_y(endpoint, cell_id, target)
        if yb is None or yt is None:
            return 0, 0
        if metric == "R02":
            return (int(yt == 1), 1) if yb == 0 else (0, 0)
        if metric == "R03":
            return (int(yt == 0), 1) if yb == 1 else (0, 0)
        if metric == "R04":
            return yt - yb, 1
        raise NotRecomputable(metric)

    # spec of an estimate ---------------------------------------------------------------------------------
    def spec(self, estimate):
        metric = estimate.get("metric_id")
        strata = _strata(estimate)
        label = estimate.get("population")
        population = _base_population(label)
        if population not in POPULATION_LABELS:
            raise NotRecomputable("population %r" % (label,))
        if (population != label) != (metric in ENH_PAIR_METRICS):
            raise NotRecomputable("population label %r for %s" % (label, metric))
        known = set(GROUP_FILTERS) | {"variant", "step"}
        if population in ("GENERATED", "REPAIR_CANDIDATES") or metric == "R06":
            known.add("iteration")
        category = None
        if metric in ("Q04",):
            category, known = strata.get("flag"), known | {"flag"}
        elif metric == "Q08":
            category, known = strata.get("verdict"), known | {"verdict"}
        elif metric in ("F01", "F02"):
            category, known = strata.get("state"), known | {"state"}
        elif metric == "E03":
            category, known = strata.get("status"), known | {"status"}
        elif metric == "R06":
            category, known = strata.get("status"), known | {"status"}
            if category not in core.TERMINAL_STATUSES:
                raise NotRecomputable("terminal status %r" % (category,))
        elif metric in ("S01", "D01"):
            if strata.get("state") is None:
                raise NotRecomputable("%s without state" % metric)
            category, known = (strata.get("tool"), strata.get("state")), known | {"tool", "state"}
        elif metric in ("S02", "D02"):
            category, known = (strata.get("tool"), None), known | {"tool"}
        elif metric in ("R02", "R03", "R04"):
            category, known = strata.get("endpoint"), known | {"endpoint"}
        elif metric == "R05":
            category, known = (strata.get("endpoint"), strata.get("comparison")), known | {"endpoint", "comparison"}
        elif metric == "R01":
            endpoint, transition = strata.get("endpoint"), strata.get("transition")
            states = R01_STATES.get(endpoint)
            parts = str(transition or "").split("->")
            if states is None or len(parts) != 2 or not all(p in states for p in parts):
                raise NotRecomputable("R01 endpoint %r transition %r" % (endpoint, transition))
            category, known = (endpoint, tuple(parts)), known | {"endpoint", "transition"}
        elif metric == "G02":
            category, known = strata.get("endpoint"), known | {"endpoint"}
        unknown = sorted(set(strata) - known)
        if unknown:
            raise NotRecomputable("strata %s" % unknown)
        if category is None and metric in ("Q04", "Q08", "F01", "F02", "E03", "R06", "R02", "R03", "R04", "G02"):
            raise NotRecomputable("category missing")
        if isinstance(category, tuple) and category[0] is None:
            raise NotRecomputable("category missing")
        self._check_filters(strata)
        variant = strata.get("variant")
        step = _step(strata["step"]) if "step" in strata else None
        iteration = _step(strata["iteration"]) if "iteration" in strata else None
        if metric == "G02":
            if category not in ("Q06", "E02", "E01") or variant is None or step is None or population != "STEP":
                raise NotRecomputable("G02 shape")
            return ("artifact", category, "STEP", variant, step, None, None)
        if metric in self.ARTIFACT_METRICS:
            return ("artifact", metric, population, variant, step, category, iteration)
        if metric in self.CELL_METRICS:
            if population not in self.CELL_POPULATIONS[metric]:
                raise NotRecomputable("%s on population %r" % (metric, label))
            if (population == "STEP") != (step is not None):
                raise NotRecomputable("%s %s with step %r" % (metric, population, step))
            if iteration is not None and metric != "R06":
                raise NotRecomputable("%s with an iteration" % metric)
            if metric == "R05":
                if variant is not None:
                    raise NotRecomputable("R05 with a variant stratum")
                pair = comparison_variants(category[1])
                if pair is None:
                    raise NotRecomputable("unparseable R05 comparison %r" % (category[1],))
                category = (category[0], pair)
            elif variant is None:
                raise NotRecomputable("%s without variant" % metric)
            return ("cell", metric, population, variant, step, category, iteration)
        raise NotRecomputable(metric)

    @staticmethod
    def _bump(groups, base, num, den):
        key = _group_key(base)
        bucket = groups.get(key)
        if bucket is None:
            bucket = groups[key] = [0, 0, set()]
        bucket[0] += num
        bucket[1] += den
        if num or den:
            bucket[2].add(base["benchmark"])

    def table(self, spec):
        if spec in self.tables:
            return self.tables[spec]
        groups = {}
        if spec[0] == "x":
            for base, num, den in self._x_units(spec):
                self._bump(groups, base, num, den)
            self.tables[spec] = groups
            return groups
        kind, metric, population, variant, step, category, iteration = spec
        index = self.index
        if kind == "artifact":
            for a in self._artifact_units(population, variant, step, iteration):
                base = index.base_of.get(a["cell_id"]) or a
                num, den = self._artifact_value(metric, a, category)
                self._bump(groups, base, num, den)
        else:
            for cell_id, base in index.base_of.items():
                if metric == "R05":
                    v1, v2 = category[1]
                    others = (index.trajectory.get((cell_id, v1)), index.trajectory.get((cell_id, v2)))
                    if None in others:
                        raise core.AnalysisRefused("cell %s lacks a trajectory of %s/%s" % (cell_id, v1, v2))
                    t = others[0]
                else:
                    t = index.trajectory.get((cell_id, variant))
                    others = None
                    if t is None:
                        raise core.AnalysisRefused("cell %s lacks a %s trajectory" % (cell_id, variant))
                num, den = self._cell_value(metric, base, t, others, category, step, iteration)
                self._bump(groups, base, num, den)
        self.tables[spec] = groups
        return groups

    def _key(self, estimate):
        spec = self.spec(estimate)
        strata = _strata(estimate)
        block = estimate.get("block")
        if block not in ESTIMATE_BLOCKS:
            raise NotRecomputable("block %r" % (block,))
        filters = (block, strata.get("model_id"), strata.get("execution_model"), strata.get("family"),
                   strata.get("sensitivity") == "SA1")
        return spec, filters

    def _sum(self, spec, filters):
        key = (spec, filters)
        if key not in self.sums:
            block, model_f, em_f, family_f, sa1 = filters
            num = den = 0
            carrying = set()
            for (b, model, em, family, bl01), (n, d, clusters) in self.table(spec).items():
                if block != core.COMPOSITE and b != block:
                    continue
                if model_f is not None and model != model_f:
                    continue
                if em_f is not None and em != em_f:
                    continue
                if family_f is not None and family != family_f:
                    continue
                if sa1 and bl01:
                    continue
                num += n
                den += d
                carrying |= clusters
            self.sums[key] = (num, den, frozenset(carrying))
        return self.sums[key]

    def estimate(self, estimate):
        """(numerator, denominator) of a ratio / difference / mean estimate."""
        num, den, _ = self._sum(*self._key(estimate))
        return num, den

    def estimable(self, estimate):
        """Whether a percentile interval is estimable (module docstring)."""
        strata = _strata(estimate)
        if estimate.get("metric_id") in ADDENDUM_NAMES:
            _, support = self._x(estimate)
            return support is not None and support[0] != 0 and self._supported(support[1], False)
        if estimate.get("metric_id") == "G01" and "comparison" in strata:
            rate, reference = self._g01_parts(estimate)
            return self.estimable(rate) and self.estimable(reference)
        spec, filters = self._key(estimate)
        _, den, carrying = self._sum(spec, filters)
        return den != 0 and self._supported(carrying, filters[4])

    def expected(self, estimate):
        """OrderedDict fact -> value the estimate must carry."""
        metric = estimate.get("metric_id")
        if estimate.get("block") not in ESTIMATE_BLOCKS:
            raise NotRecomputable("block %r" % (estimate.get("block"),))
        strata = _strata(estimate)
        if metric in ADDENDUM_NAMES:
            return OrderedDict(self._x(estimate)[0])
        special = OrderedDict([("F05", self._f05), ("F06", self._f06), ("C01", self._c01), ("C02", self._c02),
                               ("C03", self._c03), ("C04", self._c04), ("C05", self._c05)])
        if metric in special:
            return special[metric](estimate, strata)
        if metric == "G01" and "comparison" in strata:
            return self._g01_difference(estimate)
        num, den = self.estimate(estimate)
        out = OrderedDict([("numerator", num), ("denominator", den), ("value", _ratio(num, den))])
        if metric == "E04" and (not strata or "groups" in estimate or "gated_groups" in estimate):
            out.update(self._e04_groups(estimate))
        return out

    # E04 / G01 ------------------------------------------------------------------------------------------
    def _e04_groups(self, estimate):
        spec, (block, model, em, family, sa1) = self._key(estimate)
        groups, gated = set(), set()
        gates = self._pair_gates()
        for a in self._artifact_units(spec[2], spec[3], spec[4], spec[6]):
            if not self._in(a, block, model) or (em is not None and a["execution_model"] != em) \
                    or (family is not None and a["family"] != family) or (sa1 and a["benchmark"] == core.BL01_BENCHMARK):
                continue
            for key, flag in gates.get(a["artifact_id"], ()):
                group = (a["block"], a["benchmark"], key, a["execution_model"])
                groups.add(group)
                if flag:
                    gated.add(group)
        return OrderedDict([("groups", len(groups)), ("gated_groups", len(gated))])

    def _g01_parts(self, estimate):
        strata = _strata(estimate)
        if "E05" not in str(strata.get("comparison")):
            raise NotRecomputable("G01 comparison %r names no E05 reference" % (strata.get("comparison"),))
        rest = OrderedDict((k, v) for k, v in strata.items() if k != "comparison")
        if set(rest) - {"variant", "model_id"}:
            raise NotRecomputable("G01 comparison strata %s" % sorted(rest))
        rate = OrderedDict(estimate)
        rate["strata"] = rest
        reference = OrderedDict([("metric_id", "E05"), ("population", "BASE"), ("block", estimate.get("block")),
                                 ("strata", OrderedDict((k, v) for k, v in rest.items() if k == "model_id"))])
        return rate, reference

    def _g01_difference(self, estimate):
        rate, reference = self._g01_parts(estimate)
        num, den = self.estimate(rate)
        rnum, rden = self.estimate(reference)
        value = None if not den or not rden else float(num) / den - float(rnum) / rden
        return OrderedDict([("numerator", num), ("denominator", den), ("value", value),
                            ("reference_numerator", rnum), ("reference_denominator", rden)])

    # F05 / F06 --------------------------------------------------------------------------------------------
    def _f05_table(self, population, variant, step):
        """block -> (finding counts, artifacts with a finding, applicable
        artifacts per tool, total findings) of a population."""
        def build():
            out = OrderedDict((b, (Counter(), Counter(), Counter(), [0])) for b in ESTIMATE_BLOCKS)
            counts = self._finding_counts()
            for a in self._artifact_units(population, variant, step):
                applicable = [tool for tool in TOOL_STAGE if self._entry(a["artifact_id"], tool)["applicable"]]
                for block in (a["block"], core.COMPOSITE):
                    if block not in out:
                        continue
                    found, withs, tools, total = out[block]
                    for combo, n in (counts.get(a["artifact_id"]) or {}).items():
                        found[combo] += n
                        withs[combo] += 1
                        total[0] += n
                    for tool in applicable:
                        tools[tool] += 1
            return out
        return self._memo(("f05", population, variant, step), build)

    def f05_total(self, population, variant, step, block):
        return self._f05_table(population, variant, step)[block][3][0]

    def _f05_shape(self, estimate, strata):
        unknown = sorted(set(strata) - {"variant", "step", "tool", "family", "kind", "quantity"})
        if unknown:
            raise NotRecomputable("F05 strata %s" % unknown)
        if strata.get("tool") not in TOOL_STAGE or strata.get("kind") not in core.FINDING_KINDS \
                or strata.get("family") not in self.finding_families() or strata.get("quantity") not in F05_QUANTITIES:
            raise NotRecomputable("F05 tool/family/kind/quantity %r/%r/%r/%r" % (
                strata.get("tool"), strata.get("family"), strata.get("kind"), strata.get("quantity")))
        population = estimate.get("population")
        if population not in POPULATIONS:
            raise NotRecomputable("F05 population %r" % (population,))
        # F05 keeps the finding class under 'family' (not the benchmark family): only variant / step are filters
        self._check_filters(OrderedDict((k, v) for k, v in strata.items() if k in ("variant", "step")))
        step = _step(strata["step"]) if "step" in strata else None
        return population, strata.get("variant"), step

    def _f05(self, estimate, strata):
        population, variant, step = self._f05_shape(estimate, strata)
        found, withs, tools, _ = self._f05_table(population, variant, step)[estimate["block"]]
        combo = (strata["tool"], strata["family"], strata["kind"])
        if strata["quantity"] == "findings":
            return OrderedDict([("numerator", found[combo]), ("denominator", None), ("value", None)])
        den = tools[strata["tool"]]
        return OrderedDict([("numerator", withs[combo]), ("denominator", den), ("value", _ratio(withs[combo], den))])

    def f06_definition(self, strata):
        """(first tool, second tool, classes, execution models) of an F06
        estimate's pair label 'a+b' and class label (classes joined by + or /)."""
        tools = str(strata.get("pair") or "").split("+")
        definition = self.f06_definitions().get(frozenset(tools)) if len(tools) == 2 else None
        if definition is None:
            raise NotRecomputable("F06 pair %r is not a methodology pair" % (strata.get("pair"),))
        classes, models = definition
        if frozenset(re.split(r"[/+]", str(strata.get("class") or ""))) != classes:
            raise NotRecomputable("F06 class %r of %s" % (strata.get("class"), strata.get("pair")))
        return tools[0], tools[1], classes, models

    def _f06(self, estimate, strata):
        if set(strata) != {"pair", "class"} or estimate.get("population") != "GENERATED":
            raise NotRecomputable("F06 shape %s %s" % (estimate.get("population"), sorted(strata)))
        first, second, classes, models = self.f06_definition(strata)

        def build():
            tables = OrderedDict((b, Counter()) for b in ESTIMATE_BLOCKS)
            blocking = self._blocking()
            for aid, a in self.index.by_id.items():
                if a["execution_model"] not in models:
                    continue
                rows = [self._entry(aid, tool) for tool in (first, second)]
                if not all(r["applicable"] and r["state"] == COMPLETED for r in rows):
                    continue
                families = blocking.get(aid) or {}
                cell = (bool(families.get(first, set()) & classes), bool(families.get(second, set()) & classes))
                for block in (a["block"], core.COMPOSITE):
                    if block in tables:
                        tables[block][cell] += 1
            return tables
        table = self._memo(("f06", first, second), build)[estimate["block"]]
        n11, n10, n01, n00 = table[(True, True)], table[(True, False)], table[(False, True)], table[(False, False)]
        n = n11 + n10 + n01 + n00
        return OrderedDict([("numerator", n11 + n00), ("denominator", n), ("value", _ratio(n11 + n00, n)),
                            ("n11", n11), ("n10", n10), ("n01", n01), ("n00", n00),
                            ("positive_agreement", _positive_agreement(n11, n10, n01, n00)),
                            ("kappa", _kappa(n11, n10, n01, n00))])

    # C01-C05 ---------------------------------------------------------------------------------------------
    def _effort_shape(self, estimate, strata, population, allowed):
        if estimate.get("population") != population:
            raise NotRecomputable("%s population %r" % (estimate.get("metric_id"), estimate.get("population")))
        unknown = sorted(set(strata) - set(allowed))
        if unknown:
            raise NotRecomputable("%s strata %s" % (estimate.get("metric_id"), unknown))
        self._check_filters(strata)

    def _effort(self):
        """(block, model or None, variant) -> trajectories, request rounds,
        Q06-improved cells (paired cohort), repair generation records and
        their output tokens."""
        def build():
            index = self.index
            out = {}

            def bump(row, variant, field, n):
                for block in (row["block"], core.COMPOSITE):
                    for model in (None, row["model_id"]):
                        out.setdefault((block, model, variant), Counter())[field] += n
            for (cell_id, variant), t in index.trajectory.items():
                base = index.base_of.get(cell_id)
                final = index.target_artifact(t)
                if base is None or final is None:
                    raise core.AnalysisRefused("trajectory %s without its base or final artifact" % t["trajectory_id"])
                bump(t, variant, "trajectories", 1)
                bump(t, variant, "rounds", t["request_rounds"])
                bump(t, variant, "improved", int(self._paired_y("Q06", cell_id, base) == 0
                                                 and self._paired_y("Q06", cell_id, final) == 1))
            for g in index.generations:
                a = index.by_id.get(g["artifact_id"])
                if a is None or a["iteration"] < 1:
                    continue
                if g["output_tokens"] is None:
                    raise core.AnalysisRefused("repair generation %s without output_tokens" % g["artifact_id"])
                bump(a, a["variant"], "records", 1)
                bump(a, a["variant"], "output_tokens", g["output_tokens"])
            return out
        return self._memo(("effort",), build)

    def _c01(self, estimate, strata):
        self._effort_shape(estimate, strata, "REPAIR_CANDIDATES", ("variant", "model_id", "quantity"))
        if strata.get("variant") is None or strata.get("quantity") not in C01_QUANTITIES:
            raise NotRecomputable("C01 variant/quantity %r/%r" % (strata.get("variant"), strata.get("quantity")))
        acc = self._effort().get((estimate["block"], strata.get("model_id"), strata["variant"])) or Counter()
        num_field, den_field = C01_QUANTITIES[strata["quantity"]]
        return OrderedDict([("numerator", acc[num_field]), ("denominator", acc[den_field]),
                            ("value", _ratio(acc[num_field], acc[den_field]))])

    def _c05(self, estimate, strata):
        self._effort_shape(estimate, strata, "FINAL", ("variant", "model_id", "quantity"))
        match = C05_QUANTITY_RE.match(str(strata.get("quantity") or ""))
        if strata.get("variant") is None or match is None:
            raise NotRecomputable("C05 variant/quantity %r/%r" % (strata.get("variant"), strata.get("quantity")))
        field = "output_tokens" if match.group(3) == "output_tokens" else "records"
        scale = int(match.group(1)) * (1000000 if match.group(2) == "M" else 1)
        if scale != self.c05_scales()[field]:
            raise NotRecomputable("C05 quantity %r: scale %d, the methodology states %d"
                                  % (strata["quantity"], scale, self.c05_scales()[field]))
        acc = self._effort().get((estimate["block"], strata.get("model_id"), strata["variant"])) or Counter()
        den = acc[field]
        return OrderedDict([("numerator", acc["improved"]), ("denominator", den),
                            ("value", None if not den else acc["improved"] * scale / float(den))])

    def _generations(self, population, variant, block, model):
        def build():
            groups = OrderedDict()
            for g in self.index.generations:
                a = self.index.by_id.get(g["artifact_id"])
                if a is None:
                    continue
                if population == "BASE" and a["iteration"] != 0:
                    continue
                if population == "REPAIR_CANDIDATES" and (a["iteration"] < 1 or a["variant"] != variant):
                    continue
                for b in (a["block"], core.COMPOSITE):
                    for m in (None, a["model_id"]):
                        groups.setdefault((b, m), []).append(g)
            return groups
        return self._memo(("generations", population, variant), build).get((block, model)) or []

    def _c02(self, estimate, strata):
        population = estimate.get("population")
        if population not in ("BASE", "REPAIR_CANDIDATES"):
            raise NotRecomputable("C02 population %r" % (population,))
        self._effort_shape(estimate, strata, population, ("variant", "model_id", "quantity"))
        if (population == "BASE") != (strata.get("variant") is None) or strata.get("quantity") not in TOKEN_FIELDS:
            raise NotRecomputable("C02 variant/quantity %r/%r" % (strata.get("variant"), strata.get("quantity")))
        gens = self._generations(population, strata.get("variant"), estimate["block"], strata.get("model_id"))
        values = [g[strata["quantity"]] for g in gens if g[strata["quantity"]] is not None]
        return OrderedDict([("numerator", sum(values)), ("denominator", len(values)),
                            ("value", _ratio(sum(values), len(values))), ("generations", len(gens)),
                            ("coverage", _ratio(len(values), len(gens))), ("median", _percentile(values, 0.5))])

    def _c03(self, estimate, strata):
        self._effort_shape(estimate, strata, "REPAIR_CANDIDATES", ("variant", "model_id"))
        if strata.get("variant") is None:
            raise NotRecomputable("C03 without variant")
        gens = self._generations("REPAIR_CANDIDATES", strata["variant"], estimate["block"], strata.get("model_id"))
        direct = [g for g in gens if g["timing_mode"] == "direct"]
        values = [g["duration_seconds"] for g in direct if g["duration_seconds"] is not None]
        return OrderedDict([("numerator", None), ("denominator", len(values)), ("value", _percentile(values, 0.5)),
                            ("p95", _percentile(values, P95)), ("n", len(values)),
                            ("excluded_null", len(direct) - len(values)), ("excluded_not_direct", len(gens) - len(direct))])

    def _c04(self, estimate, strata):
        self._effort_shape(estimate, strata, "GENERATED", ("tool", "execution_model", "outlier_rule"))
        tool, rule = strata.get("tool"), strata.get("outlier_rule")
        if tool not in TOOL_STAGE or rule not in OUTLIER_RULES:
            raise NotRecomputable("C04 tool/outlier_rule %r/%r" % (tool, rule))

        def build():
            ran = []
            for aid, a in self.index.by_id.items():
                row = self._entry(aid, tool)
                if row["ran"]:
                    ran.append((a, row))
            return ran
        em = strata.get("execution_model")
        entries = [row for a, row in self._memo(("c04", tool), build)
                   if self._in(a, estimate["block"]) and (em is None or a["execution_model"] == em)]
        threshold = core.RUNTIME_OUTLIER_SECONDS
        timeouts = sum(1 for row in entries if row["state"] == TIMEOUT)
        timed = [row for row in entries if row["state"] != TIMEOUT]
        values = [row["duration_seconds"] for row in timed if row["duration_seconds"] is not None]
        kept = values if rule == "all" else [v for v in values if v <= threshold]
        return OrderedDict([("numerator", None), ("denominator", len(kept)), ("value", _percentile(kept, 0.5)),
                            ("p95", _percentile(kept, P95)), ("n", len(kept)), ("timeouts", timeouts),
                            ("ran_entries", len(entries)), ("timeout_share", _ratio(timeouts, len(entries))),
                            ("above_threshold", sum(1 for v in values if v > threshold)),
                            ("excluded_null", len(timed) - len(values))])

    # post-freeze addendum X01-X06 (own code paths; module docstring readings) --------------------------
    def _x(self, estimate):
        """(facts, support) of an addendum estimate; support = (denominator,
        carrying clusters) where the addendum demands a CI, else None."""
        key = estimate_key(estimate)
        if key not in self._x_cache:
            metric, block = estimate.get("metric_id"), estimate.get("block")
            if block not in ESTIMATE_BLOCKS:
                raise NotRecomputable("block %r" % (block,))
            handler = OrderedDict([("X01", self._x01), ("X02", self._x02), ("X03", self._x03), ("X04", self._x04),
                                   ("X05", self._x05), ("X06", self._x06)]).get(metric)
            if handler is None:
                raise NotRecomputable(metric)
            self._x_cache[key] = handler(estimate.get("population"), _strata(estimate), block)
        return self._x_cache[key]

    @staticmethod
    def _shape(metric, population, strata, shapes):
        """Refuse a (population, strata keys) the addendum does not define."""
        if population not in shapes or set(strata) not in shapes[population]:
            raise NotRecomputable("%s shape %r %s" % (metric, population, sorted(strata)))

    def _final(self, cell_id, variant):
        t = self.index.trajectory.get((cell_id, variant))
        if t is None:
            raise core.AnalysisRefused("cell %s lacks a %s trajectory" % (cell_id, variant))
        target = self.index.target_artifact(t)
        if target is None:
            raise core.AnalysisRefused("trajectory %s selects no artifact" % t["trajectory_id"])
        return target

    def block_cells(self, block):
        return sum(1 for base in self.index.base_of.values() if block == core.COMPOSITE or base["block"] == block)

    def auto_closed_cells(self):
        """Base cells with a clean_auto_closed artifact on ANY of their
        trajectories (iterations 0..final_iteration of every variant)."""
        def build():
            closed = set()
            for t in self.index.trajectory.values():
                final = t["final_iteration"]
                if type(final) is not int or not 0 <= final <= core.MAX_ITERATIONS:
                    raise core.AnalysisRefused("trajectory %s final_iteration %r" % (t["trajectory_id"], final))
                for k in range(final + 1):
                    a = self.index.by_id.get(t["artifact_iter%d" % k])
                    if a is None:
                        raise core.AnalysisRefused("trajectory %s selects no artifact at iteration %d"
                                                   % (t["trajectory_id"], k))
                    if a["clean_auto_closed"]:
                        closed.add(t["cell_id"])
            return frozenset(closed)
        return self._memo(("auto_closed",), build)

    def static_reading(self):
        """artifact id -> (X02 tool-verdict-reading three-state, frozenset of
        the applicable static analysis tools with >= 1 reported blocking
        finding)."""
        def build():
            facts = {}
            for aid in self.index.by_id:
                rows = [r for r in self.index.entries_of.get(aid) or [] if r["stage"] == "static"
                        and r["tool"] in core.STATIC_ANALYSIS_TOOLS and r["applicable"]]
                blocking = frozenset(r["tool"] for r in rows if r["num_reported_blocking"] > 0)
                if any(r["num_reported_blocking"] > 0 and r["state"] in VERDICT_STATES for r in rows):
                    reading = "DIRTY"
                elif any(r["state"] in core.GAP_STATES for r in rows):
                    reading = "NO_FINDING_INCOMPLETE"
                else:
                    reading = "CLEAN_COMPLETE"
                facts[aid] = (reading, blocking)
            return facts
        return self._memo(("static_reading",), build)

    def _blocking_checks(self):
        """(artifact, tool, check id) -> reported blocking findings."""
        def build():
            return Counter((f["artifact_id"], f["tool"], f["check_id"]) for f in self.index.findings
                           if f["kind"] == "reported_blocking")
        return self._memo(("blocking_checks",), build)

    def x03_top(self):
        """tool -> the check ids with most reported blocking findings on the
        composite BASE (ties by check id ascending; N from the addendum text;
        fewer when the tool has fewer)."""
        def build():
            match = X03_TOP_RE.search(addendum_text(self.addendum(), "X03", "meaning"))
            if match is None:
                raise core.AnalysisRefused("the addendum X03 text states no top-N check ids")
            top = int(match.group(1))
            counts = OrderedDict((tool, Counter()) for tool in core.STATIC_ANALYSIS_TOOLS)
            for f in self.index.findings:
                a = self.index.by_id.get(f["artifact_id"])
                if a is not None and a["iteration"] == 0 and f["kind"] == "reported_blocking" and f["tool"] in counts:
                    counts[f["tool"]][f["check_id"]] += 1
            return OrderedDict((tool, tuple(c for c, _ in sorted(found.items(), key=lambda item: (-item[1], item[0]))
                                            [:top])) for tool, found in counts.items())
        return self._memo(("x03_top",), build)

    @staticmethod
    def r01_labels(endpoint):
        states = R01_STATES[endpoint]
        return tuple("%s->%s" % (x, y) for x in states for y in states)

    @staticmethod
    def _transition(endpoint, before, after):
        states = R01_STATES[endpoint]
        return "%s->%s" % (states[0 if before == 1 else 1], states[0 if after == 1 else 1])

    def _x_units(self, spec):
        """(base cell, numerator, denominator) per observation unit of one
        addendum quantity (aggregated by table() / _sum like every ratio)."""
        index = self.index
        name = spec[1]
        if name in ("X01", "X01-auto"):
            endpoint, (form, value) = spec[2], spec[3]
            closed = self.auto_closed_cells()
            for cell_id, base in index.base_of.items():
                if form == "variant":
                    first, second = self._final(cell_id, value), base
                else:
                    first, second = self._final(cell_id, value[0]), self._final(cell_id, value[1])
                y1, y2 = self._paired_y(endpoint, cell_id, first), self._paired_y(endpoint, cell_id, second)
                if y1 is None or y2 is None:
                    continue                      # outside the endpoint's paired cohort
                if name == "X01-auto":
                    if cell_id in closed:
                        yield base, 1, 0
                elif cell_id not in closed:
                    yield base, y1 - y2, 1
        elif name in ("X02", "X02-only", "X04"):
            population, variant = spec[2], spec[3]
            reading = self.static_reading()
            for a in self._artifact_units(population, variant, None):
                base = index.base_of.get(a["cell_id"]) or a
                state = reading[a["artifact_id"]][0]
                if name == "X02":
                    yield base, int(state == spec[4]), 1
                elif name == "X02-only":
                    yield base, int(a["static_three_state"] == "DIRTY" and state != "DIRTY"), 1
                else:
                    failing = a["correctness_verdict"] not in X04_NOT_FAILING
                    yield base, int(failing and a["static_three_state"] == spec[4]), int(failing)
        elif name in ("X03-only", "X03-findings", "X03-artifacts"):
            tool = spec[2]
            reading = self.static_reading()
            checks = self._blocking_checks()
            for a in self._artifact_units("BASE", None, None):
                base = index.base_of.get(a["cell_id"]) or a
                if name == "X03-only":
                    dirty = a["static_three_state"] == "DIRTY"
                    yield base, int(dirty and reading[a["artifact_id"]][1] == frozenset([tool])), int(dirty)
                    continue
                found = checks.get((a["artifact_id"], tool, spec[3]), 0)
                if name == "X03-findings":
                    yield base, found, 0
                else:
                    yield base, int(found > 0), int(bool(self._entry(a["artifact_id"], tool)["applicable"]))
        elif name == "X05":
            variant, k = spec[2], spec[3]
            for t in index.trajectory.values():
                if t["variant"] != variant or t["terminal_status"] not in X05_STOPS:
                    continue
                base = index.base_of.get(t["cell_id"])
                if base is None:
                    raise core.AnalysisRefused("trajectory %s without a base artifact" % t["trajectory_id"])
                final = t["final_iteration"]
                yield base, (final if k is None else int(final == k)), 1
        elif name == "X06":
            variant, wanted = spec[2], (spec[3], spec[4])
            for cell_id, base in index.base_of.items():
                target = self._final(cell_id, variant)
                labels = []
                for endpoint in PRIMARY_ENDPOINTS:
                    before, after = self._paired_y(endpoint, cell_id, base), self._paired_y(endpoint, cell_id, target)
                    if before is None or after is None:
                        labels = None             # outside one of the two paired cohorts
                        break
                    labels.append(self._transition(endpoint, before, after))
                if labels is not None:
                    yield base, int(tuple(labels) == wanted), 1
        else:
            raise NotRecomputable("addendum quantity %r" % (name,))

    @staticmethod
    def _facts(num, den, **extra):
        out = OrderedDict([("numerator", num), ("denominator", den), ("value", _ratio(num, den))])
        out.update(sorted(extra.items()))
        return out

    def _x01(self, population, strata, block):
        self._shape("X01", population, strata, {"FINAL": ({"endpoint", "variant"}, {"endpoint", "comparison"})})
        endpoint = strata["endpoint"]
        if endpoint not in ENDPOINT_Y:
            raise NotRecomputable("X01 endpoint %r" % (endpoint,))
        if "variant" in strata:
            if strata["variant"] not in core.VARIANTS:
                raise NotRecomputable("X01 variant %r" % (strata["variant"],))
            shape = ("variant", strata["variant"])
        else:
            pair = comparison_variants(strata["comparison"])
            if pair is None:
                raise NotRecomputable("unparseable X01 comparison %r" % (strata["comparison"],))
            shape = ("comparison", pair)
        filters = (block, None, None, None, False)
        num, den, carrying = self._sum(("x", "X01", endpoint, shape), filters)
        closed = self._sum(("x", "X01-auto", endpoint, shape), filters)[0]
        facts = self._facts(num, den, excluded=closed, statistic="difference")
        facts[ALTERNATIVES] = OrderedDict([("excluded", OrderedDict([
            (X01_READINGS[0], closed), (X01_READINGS[1], self.block_cells(block) - den)]))])
        return facts, (den, carrying)

    def _x02(self, population, strata, block):
        self._shape("X02", population, strata, {"BASE": ({"state"}, {"execution_model", "state"}),
                                                "FINAL": ({"variant", "state"},)})
        state, variant, em = strata["state"], strata.get("variant"), strata.get("execution_model")
        if state not in core.THREE_STATE or (population == "FINAL" and variant not in core.VARIANTS) \
                or (em is not None and em not in core.EXECUTION_MODELS):
            raise NotRecomputable("X02 state/variant/execution model %r/%r/%r" % (state, variant, em))
        filters = (block, None, em, None, False)
        num, den, carrying = self._sum(("x", "X02", population, variant, state), filters)
        only = self._sum(("x", "X02-only", population, variant), filters)[0]
        return self._facts(num, den, dirty_only_under_frozen_rule=only), (den, carrying)

    def _x03(self, population, strata, block):
        self._shape("X03", population, strata, {"BASE": ({"tool", "quantity"}, {"tool", "check_id", "quantity"})})
        tool, quantity = strata["tool"], strata["quantity"]
        if tool not in core.STATIC_ANALYSIS_TOOLS or quantity not in X03_QUANTITIES \
                or (quantity == X03_ONLY) != ("check_id" not in strata):
            raise NotRecomputable("X03 tool/quantity %r/%r with%s check id" % (tool, quantity,
                                                                              "" if "check_id" in strata else "out"))
        filters = (block, None, None, None, False)
        if quantity == X03_ONLY:
            num, den, _ = self._sum(("x", "X03-only", tool), filters)
            return self._facts(num, den), None
        check = strata["check_id"]
        if check not in self.x03_top()[tool]:
            raise NotRecomputable("X03 check id %r is not among the top %s check ids of %s"
                                  % (check, len(self.x03_top()[tool]), tool))
        if quantity == X03_FINDINGS:
            num = self._sum(("x", "X03-findings", tool, check), filters)[0]
            return OrderedDict([("numerator", num), ("denominator", None), ("value", None),
                                ("statistic", "count")]), None
        num, den, _ = self._sum(("x", "X03-artifacts", tool, check), filters)
        return self._facts(num, den), None

    def _x04(self, population, strata, block):
        self._shape("X04", population, strata, {"BASE": ({"state"},), "FINAL": ({"variant", "state"},)})
        state, variant = strata["state"], strata.get("variant")
        if state not in X04_STATES or (population == "FINAL" and variant not in core.VARIANTS):
            raise NotRecomputable("X04 state/variant %r/%r" % (state, variant))
        num, den, carrying = self._sum(("x", "X04", population, variant, state), (block, None, None, None, False))
        return self._facts(num, den), (den, carrying)

    def _x05(self, population, strata, block):
        self._shape("X05", population, strata, {"TRAJECTORIES": ({"variant"}, {"variant", "iteration"})})
        variant, k = strata["variant"], None
        if variant not in core.VARIANTS:
            raise NotRecomputable("X05 variant %r" % (variant,))
        if "iteration" in strata:
            k = _step(strata["iteration"])
            if k is None or not 0 <= k <= core.MAX_ITERATIONS:
                raise NotRecomputable("X05 iteration %r" % (strata["iteration"],))
        num, den, _ = self._sum(("x", "X05", variant, k), (block, None, None, None, False))
        return self._facts(num, den, statistic="mean" if k is None else "share"), None

    def _x06(self, population, strata, block):
        self._shape("X06", population, strata, {"FINAL": ({"variant", "transition", "heldout_transition"},)})
        variant, q, h = strata["variant"], strata["transition"], strata["heldout_transition"]
        if variant not in core.VARIANTS or q not in self.r01_labels("Q06") or h not in self.r01_labels("E02"):
            raise NotRecomputable("X06 variant/transition/heldout_transition %r/%r/%r" % (variant, q, h))
        num, den, _ = self._sum(("x", "X06", variant, q, h), (block, None, None, None, False))
        return self._facts(num, den), None


def addendum_anchors(engine, estimates):
    """(anchors, problems): every (metric, population, block, strata) the
    addendum contract demands per block (DESIGN2 section 1) - X01 per
    endpoint x variant and per endpoint x the R05 comparison labels of the
    same block, X02 BASE per state (+ per execution model of the block) and
    FINAL per variant x state, X03 per tool (only-via share) and per top
    check id x quantity, X04 BASE / FINAL per state, X05 per variant (mean
    and iterations 0..MAX), X06 per variant x every Q06 x E02 transition."""
    index = engine.index
    problems = []
    r05 = OrderedDict()
    for e in estimates:
        strata = _strata(e) if isinstance(e, dict) else {}
        if isinstance(e, dict) and e.get("metric_id") == "R05" and set(strata) == {"endpoint", "comparison"}:
            r05.setdefault((e.get("block"), strata.get("endpoint")), set()).add(strata.get("comparison"))
    pairs = len(core.VARIANTS) * (len(core.VARIANTS) - 1) // 2
    top = engine.x03_top()
    anchors = []
    for block in ESTIMATE_BLOCKS:
        for endpoint in PRIMARY_ENDPOINTS:
            for variant in core.VARIANTS:
                anchors.append(("X01", "FINAL", block, OrderedDict([("endpoint", endpoint), ("variant", variant)])))
            labels = r05.get((block, endpoint)) or set()
            if len(labels) != pairs:
                problems.append("X01 %s %s: %d R05 comparison label(s) %s to pair with, expected %d"
                                % (block, endpoint, len(labels), sorted(labels, key=str), pairs))
            for label in sorted(labels, key=str):
                anchors.append(("X01", "FINAL", block, OrderedDict([("endpoint", endpoint), ("comparison", label)])))
        models = [em for em in core.EXECUTION_MODELS if any(
            c["execution_model"] == em and (block == core.COMPOSITE or c["block"] == block) for c in index.base_cells)]
        for state in core.THREE_STATE:
            anchors.append(("X02", "BASE", block, OrderedDict([("state", state)])))
            for em in models:
                anchors.append(("X02", "BASE", block, OrderedDict([("execution_model", em), ("state", state)])))
            for variant in core.VARIANTS:
                anchors.append(("X02", "FINAL", block, OrderedDict([("variant", variant), ("state", state)])))
        for tool in core.STATIC_ANALYSIS_TOOLS:
            anchors.append(("X03", "BASE", block, OrderedDict([("tool", tool), ("quantity", X03_ONLY)])))
            for check in top[tool]:
                for quantity in (X03_FINDINGS, X03_ARTIFACTS):
                    anchors.append(("X03", "BASE", block, OrderedDict([("tool", tool), ("check_id", check),
                                                                       ("quantity", quantity)])))
        for state in X04_STATES:
            anchors.append(("X04", "BASE", block, OrderedDict([("state", state)])))
            for variant in core.VARIANTS:
                anchors.append(("X04", "FINAL", block, OrderedDict([("variant", variant), ("state", state)])))
        for variant in core.VARIANTS:
            anchors.append(("X05", "TRAJECTORIES", block, OrderedDict([("variant", variant)])))
            for k in range(core.MAX_ITERATIONS + 1):
                anchors.append(("X05", "TRAJECTORIES", block, OrderedDict([("variant", variant), ("iteration", k)])))
            for q in engine.r01_labels("Q06"):
                for h in engine.r01_labels("E02"):
                    anchors.append(("X06", "FINAL", block, OrderedDict([("variant", variant), ("transition", q),
                                                                        ("heldout_transition", h)])))
    for e in estimates:
        strata = _strata(e) if isinstance(e, dict) else {}
        if isinstance(e, dict) and e.get("metric_id") == "X01" and "comparison" in strata:
            if strata.get("comparison") not in (r05.get((e.get("block"), strata.get("endpoint"))) or set()):
                problems.append("X01 %s %s: comparison label %r is not an R05 label of the block"
                                % (e.get("block"), strata.get("endpoint"), strata.get("comparison")))
    return anchors, problems


def required_anchors():
    """(metric, population or None, strata) every block must report."""
    anchors = [("Q06", "BASE", {}), ("E02", "BASE", {})]
    for variant in core.VARIANTS:
        anchors.append(("Q06", "FINAL", {"variant": variant}))
        anchors.append(("E02", "FINAL", {"variant": variant}))
        for k in range(core.MAX_ITERATIONS + 1):
            anchors.append(("Q06", "STEP", {"variant": variant, "step": k}))
        for endpoint in PRIMARY_ENDPOINTS:
            for metric in ("R02", "R03", "R04"):
                anchors.append((metric, None, {"endpoint": endpoint, "variant": variant}))
        for endpoint, states in R01_STATES.items():
            for x in states:
                for y in states:
                    anchors.append(("R01", "FINAL", {"endpoint": endpoint, "variant": variant,
                                                     "transition": "%s->%s" % (x, y)}))
        for metric in ("R07", "R08", "R09", "R10"):
            anchors.append((metric, None, {"variant": variant}))
    return anchors


def _required_facts(estimate):
    metric, strata = estimate.get("metric_id"), _strata(estimate)
    facts = ["numerator", "denominator", "value"] + list(REQUIRED_EXTRAS.get(metric, ()))
    if metric == "G01" and "comparison" in strata:
        facts += ["reference_numerator", "reference_denominator"]
    if metric == "E04" and not strata:
        facts += ["groups", "gated_groups"]
    if metric == "X01":
        facts.append("excluded")
    # the shape labels DESIGN2 section 1 fixes (X01 difference, X05 mean / share, X03 finding count)
    if metric in ("X01", "X05") or (metric == "X03" and strata.get("quantity") == X03_FINDINGS):
        facts.append("statistic")
    if metric == "X02" and strata.get("state") == "DIRTY":
        facts.append("dirty_only_under_frozen_rule")
    return facts


def ci_required(estimate):
    """The methodology (or the addendum) demands an interval for this
    estimate's metric: F01 / X02 only for the DIRTY share, G01 only for the
    difference to its reference."""
    metric, strata = estimate.get("metric_id"), _strata(estimate)
    if metric in ("F01", "X02"):
        return strata.get("state") == "DIRTY"
    if metric == "G01":
        return "comparison" in strata
    return metric in CI_METRICS or metric in ADDENDUM_CI_METRICS


def ci_metric_problems(methodology):
    """CI_METRICS must be the metrics whose frozen aggregation names a CI."""
    named = sorted(m["id"] for m in methodology.get("metrics") or [] if re.search(r"\bCI\b", m.get("aggregation") or ""))
    return [] if named == sorted(CI_METRICS) else ["the methodology names a CI for %s, the validation demands %s"
                                                   % (named, sorted(CI_METRICS))]


def recompute_problems(estimates, index, methodology=None, addendum=None):
    problems = []
    engine = Recompute(index, methodology, addendum)
    if methodology is not None:
        problems.extend(ci_metric_problems(methodology))
    problems.extend(addendum_ci_problems(engine.addendum()))
    checked = Counter()
    failed = Counter()
    ci = Counter()
    f05_groups = OrderedDict()
    f06_seen = set()
    readings = OrderedDict()      # (metric, field) -> [estimates, Counter(reading -> estimates it fits)]
    for e in estimates:
        if not isinstance(e, dict):
            continue
        metric = e.get("metric_id")
        label = "%s %s %s %s" % (metric, e.get("population"), e.get("block"), _skey(_strata(e)))
        try:
            expected = engine.expected(e)
        except NotRecomputable as error:
            failed[metric] += 1
            problems.append("%s: not recomputable from the dataset (%s)" % (label, error))
            continue
        alternatives = expected.pop(ALTERNATIVES, None) or {}
        checked[metric] += 1
        required = set(_required_facts(e))
        for field, value in expected.items():
            if field not in e:
                if field in required:
                    problems.append("%s: lacks %s (recomputed %r)" % (label, field, value))
                continue
            if field in alternatives:
                fitting = [r for r, v in alternatives[field].items() if _same(e.get(field), v)]
                if not fitting:
                    problems.append("%s: %s %r, recomputed %s under the readings %s" % (
                        label, field, e.get(field), list(alternatives[field].values()), list(alternatives[field])))
                entry = readings.setdefault((metric, field), [0, Counter()])
                entry[0] += 1
                entry[1].update(fitting)
                continue
            if not _same(e.get(field), value):
                problems.append("%s: %s %r, recomputed %r" % (label, field, e.get(field), value))
        if metric == "F05" and _strata(e).get("quantity") == "findings":
            strata = _strata(e)
            key = (e.get("population"), strata.get("variant"), _step(strata.get("step")), e.get("block"))
            f05_groups[key] = f05_groups.get(key, 0) + (e.get("numerator") or 0)
        if metric == "F06":
            first, second, _, _ = engine.f06_definition(_strata(e))
            f06_seen.add((frozenset((first, second)), e.get("block")))
        if ci_required(e) and expected.get("value") is not None:
            if engine.estimable(e):
                ci["required"] += 1
                skipped, total = _skipped(e)
                if e.get("ci_method") == CI_METHOD and e.get("ci_low") is not None and e.get("ci_high") is not None:
                    ci["present"] += 1
                elif not (total is not None and skipped == total):
                    problems.append("%s: the methodology demands a cluster-bootstrap CI and the cluster support "
                                    "makes it estimable, the estimate carries none" % label)
        elif metric in ADDENDUM_NAMES and not ci_required(e):
            # the other direction: an addendum estimate the definition gives no CI (X03, X05, X06, the non-DIRTY
            # X02 shares) never carries one (a descriptive count dressed with inferential uncertainty)
            ci["addendum_without_ci"] += 1
            carried = [f for f in INTERVAL_FIELDS if e.get(f) is not None]
            if carried:
                problems.append("%s: the addendum defines no interval for this estimate, it carries %s"
                                % (label, carried))
    for (population, variant, step, block), total in f05_groups.items():
        expected_total = engine.f05_total(population, variant, step, block)
        if total != expected_total:
            problems.append("F05 %s %s %s: the per tool x family x kind counts sum to %d, the population holds %d "
                            "findings (a combination is missing or foreign)" % (population, variant or "", block,
                                                                               total, expected_total))
    for population, variants in (("BASE", (None,)), ("GENERATED", (None,)), ("FINAL", core.VARIANTS)):
        for variant in variants:
            for block in ESTIMATE_BLOCKS:
                if (population, variant, None, block) not in f05_groups and \
                        engine.f05_total(population, variant, None, block):
                    problems.append("F05 %s %s %s: no finding counts" % (population, variant or "", block))
    for pair in engine.f06_definitions():
        for block in ESTIMATE_BLOCKS:
            if (pair, block) not in f06_seen:
                problems.append("F06 %s %s: no agreement estimate" % ("+".join(sorted(pair)), block))
    present = set()
    for e in estimates:
        if isinstance(e, dict):
            present.add((e.get("metric_id"), e.get("population"), e.get("block"), _skey(_strata(e))))
            present.add((e.get("metric_id"), None, e.get("block"), _skey(_strata(e))))
    missing = []
    for block in ESTIMATE_BLOCKS:
        for metric, population, strata in required_anchors():
            if (metric, population, block, _skey(strata)) not in present:
                missing.append("%s %s %s %s" % (metric, population or "*", block, _skey(strata)))
    if missing:
        problems.append("%d required estimate(s) missing: %s" % (len(missing), missing[:5]))
    # the addendum shapes: complete (X01 comparisons == the R05 labels, top check ids, every transition pair)
    anchors, anchor_problems = addendum_anchors(engine, estimates)
    problems.extend(anchor_problems)
    missing_addendum = ["%s %s %s %s" % (m, p, b, _skey(s)) for m, p, b, s in anchors
                        if (m, p, b, _skey(s)) not in present]
    if missing_addendum:
        problems.append("%d required addendum estimate(s) missing: %s" % (len(missing_addendum),
                                                                          missing_addendum[:5]))
    # one reading of an ambiguous contract field for every estimate of the metric (module docstring)
    used = OrderedDict()
    for (metric, field), (n, fitting) in readings.items():
        consistent = sorted(r for r, k in fitting.items() if k == n)
        used["%s.%s" % (metric, field)] = consistent
        if n and not consistent:
            problems.append("%s %s: no single reading fits all %d estimates (estimates per reading %s)"
                            % (metric, field, n, dict(fitting)))
    return problems, OrderedDict([("recomputed", sum(checked.values())), ("not_recomputed", sum(failed.values())),
                                  ("recomputed_per_metric", OrderedDict(sorted(checked.items()))),
                                  ("not_recomputed_per_metric", OrderedDict(sorted(failed.items()))),
                                  ("ci_required", ci["required"]), ("ci_present", ci["present"]),
                                  ("addendum_without_ci", ci["addendum_without_ci"]),
                                  ("missing_anchors", len(missing)), ("missing_addendum_anchors", len(missing_addendum)),
                                  ("readings", used)])


# -- estimate algebra --------------------------------------------------------------------------------------

def _is_primary(estimate):
    return any(estimate.get(k) is not None for k in ("p_value", "p_holm", "reject_holm"))


STRATA_VOCABULARY = OrderedDict([
    ("variant", core.VARIANTS), ("execution_model", core.EXECUTION_MODELS), ("tool", tuple(TOOL_STAGE)),
    ("verdict", core.CORRECTNESS_VERDICTS), ("kind", core.FINDING_KINDS), ("endpoint", tuple(R01_STATES) + ("E01",)),
    ("sensitivity", ("SA1",)), ("outlier_rule", OUTLIER_RULES)])
ENH_PAIR_POPULATIONS = ("BASE", "STEP", "FINAL", "GENERATED")


def strata_value_problems(metric, strata, check_ids=None):
    """Strata values outside their closed vocabulary (model ids and benchmark
    families are checked against the dataset by the recomputation).
    check_id: a non-empty string and, with check_ids (tool -> the check ids
    of the dataset's findings of that tool), one the tool's findings carry;
    heldout_transition: the R01 E02 labels (X06 transition: the R01 Q06
    labels); X03 quantity: its three sub-quantities."""
    problems = []
    for key, value in strata.items():
        if key in ("step", "iteration"):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= core.MAX_ITERATIONS:
                problems.append("%s %r outside 0..%d" % (key, value, core.MAX_ITERATIONS))
            continue
        if key == "check_id":
            if not isinstance(value, str) or not value.strip():
                problems.append("check_id %r is not a non-empty string" % (value,))
            elif check_ids is not None and value not in (check_ids.get(strata.get("tool")) or ()):
                problems.append("check_id %r occurs in no finding of the tool %r" % (value, strata.get("tool")))
            continue
        allowed = STRATA_VOCABULARY.get(key)
        if key == "state":
            allowed = core.TOOL_STATES if metric in ("S01", "D01") else core.THREE_STATE
        elif key == "status":
            allowed = core.TERMINAL_STATUSES if metric == "R06" else core.ENHANCED_STATUSES
        elif key == "heldout_transition":
            allowed = Recompute.r01_labels("E02")
        elif key == "transition" and metric == "X06":
            allowed = Recompute.r01_labels("Q06")
        elif key == "quantity" and metric == "X03":
            allowed = X03_QUANTITIES
        if allowed is not None and value not in allowed:
            problems.append("%s %r outside its vocabulary" % (key, value))
    return problems


def contract_field_problems(estimate, post_freeze_ids, prefix, resolution):
    """The four DESIGN2 section 1 keys of one estimate (p_holm_resolution's
    value is checked over the whole family by primary_problems)."""
    problems = []
    metric, note = estimate.get("metric_id"), str(estimate.get("note") or "")
    flag = estimate.get("post_freeze")
    if not isinstance(flag, bool):
        problems.append("post_freeze %r is not a boolean" % (flag,))
    elif flag != (metric in post_freeze_ids):
        problems.append("post_freeze %s on a %s metric" % (flag, "post-freeze addendum" if metric in post_freeze_ids
                                                           else "frozen"))
    if metric in post_freeze_ids and not note.startswith(prefix):
        problems.append("a post-freeze estimate whose note does not start with %r" % prefix)
    low, high, degenerate = estimate.get("ci_low"), estimate.get("ci_high"), estimate.get("ci_degenerate")
    if low is None or high is None:
        if degenerate is not None:
            problems.append("ci_degenerate %r without an interval (must be None)" % (degenerate,))
    elif not isinstance(degenerate, bool) or degenerate != (low == high):
        problems.append("ci_degenerate %r contradicts the interval [%r, %r]" % (degenerate, low, high))
    elif degenerate and DEGENERATE_NOTE not in note:
        problems.append("a degenerate interval whose note lacks %r" % DEGENERATE_NOTE)
    if _is_primary(estimate):
        value = estimate.get("p_resolution")
        if not _finite(value) or not _close(value, resolution):
            problems.append("p_resolution %r, 2 / replicates_primary = %r" % (value, resolution))
        if not _finite(estimate.get("p_holm_resolution")):
            problems.append("p_holm_resolution %r is not a number" % (estimate.get("p_holm_resolution"),))
    else:
        for field in ("p_resolution", "p_holm_resolution"):
            if estimate.get(field) is not None:
                problems.append("%s %r outside the primary family (must be None)" % (field, estimate.get(field)))
    return problems


def bootstrap_problems(estimate, methodology):
    """An interval must rest on the methodology's replicate count: the
    replicates used plus the skipped ones the note documents equal
    replicates_primary (primary family) or replicates_descriptive; an
    EXPLORATORY (non-confirmatory) estimate is never valid."""
    problems = []
    stats = core.statistics_settings(methodology)["bootstrap"]
    expected = int(stats["replicates_primary"] if _is_primary(estimate) else stats["replicates_descriptive"])
    if EXPLORATORY in str(estimate.get("note") or ""):
        problems.append("EXPLORATORY (non-confirmatory) estimate: %s" % _short(estimate.get("note"), 160))
    if estimate.get("ci_method") is not None or _is_primary(estimate):
        replicates = estimate.get("replicates")
        skipped, total = _skipped(estimate)
        if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
            problems.append("replicates %r is not a positive integer" % (replicates,))
        elif total is not None and total != expected:
            problems.append("the note documents a %d-replicate bootstrap, the methodology fixes %d" % (total, expected))
        elif replicates + skipped != expected:
            problems.append("%d bootstrap replicates (+ %d skipped), the methodology fixes %d%s"
                            % (replicates, skipped, expected, " (primary family)" if _is_primary(estimate) else ""))
    return problems


def schema_problems(estimates, methodology, addendum=None, index=None):
    """Per-estimate schema. addendum None: core.load_addendum bound to the
    methodology; index (validate passes it): the check_id vocabulary of the
    dataset's findings."""
    problems = [] if estimates else ["no estimates"]
    addendum = addendum if addendum is not None else core.load_addendum(methodology=methodology)
    post_freeze_ids = set(core.addendum_metric_ids(addendum))
    ids = set(core.all_metric_ids(methodology, addendum))
    prefix = post_freeze_prefix(addendum)
    resolution = 2.0 / int(core.statistics_settings(methodology)["bootstrap"]["replicates_primary"])
    check_ids = None
    if index is not None:
        check_ids = OrderedDict()
        for f in index.findings:
            check_ids.setdefault(f["tool"], set()).add(f["check_id"])
    for position, e in enumerate(estimates):
        label = "#%d %s" % (position, e.get("metric_id") if isinstance(e, dict) else e)
        if not isinstance(e, dict):
            problems.append("%s is not an object" % label)
            continue
        missing = [k for k in ESTIMATE_KEYS if k not in e]
        if missing:
            problems.append("%s lacks %s" % (label, missing))
            continue
        label = "%s %s %s %s" % (e["metric_id"], e["population"], e["block"], _skey(_strata(e)))
        if e["metric_id"] not in ids:
            problems.append("%s: unknown metric id" % label)
        if e["block"] not in ESTIMATE_BLOCKS:
            problems.append("%s: block %r" % (label, e["block"]))
        if not isinstance(e["population"], str) or not e["population"]:
            problems.append("%s: no population" % label)
        else:
            base = _base_population(e["population"])
            wrapped = base != e["population"]
            if base not in POPULATION_LABELS or (wrapped and base not in ENH_PAIR_POPULATIONS):
                problems.append("%s: population %r outside the methodology's populations" % (label, e["population"]))
            elif isinstance(e["strata"], dict) and (base == "STEP") != ("step" in e["strata"]):
                problems.append("%s: population %s %s a step stratum" % (label, base,
                                                                        "without" if base == "STEP" else "with"))
        if not isinstance(e["strata"], dict):
            problems.append("%s: strata is not an object" % label)
        else:
            unknown = sorted(set(e["strata"]) - set(STRATA_KEYS))
            if unknown:
                problems.append("%s: unknown strata key(s) %s" % (label, unknown))
            problems.extend("%s: %s" % (label, p) for p in strata_value_problems(e["metric_id"], e["strata"],
                                                                                   check_ids))
        problems.extend("%s: %s" % (label, p) for p in contract_field_problems(e, post_freeze_ids, prefix, resolution))
        for field in ("numerator", "denominator", "value", "ci_low", "ci_high", "p_value", "p_holm"):
            value = e[field]
            if value is not None and not _finite(value):
                problems.append("%s: %s %r is not a finite number" % (label, field, value))
        if e["ci_method"] not in (None, CI_METHOD):
            problems.append("%s: ci_method %r" % (label, e["ci_method"]))
        if e["ci_method"] is None and (e["ci_low"] is not None or e["ci_high"] is not None):
            problems.append("%s: CI without a ci_method" % label)
        problems.extend("%s: %s" % (label, p) for p in bootstrap_problems(e, methodology))
        if e["ci_method"] is not None:
            if e["value"] is not None and (e["ci_low"] is None) != (e["ci_high"] is None):
                problems.append("%s: half-open CI" % label)
            if _finite(e["ci_low"]) and _finite(e["ci_high"]) and e["ci_low"] > e["ci_high"] + TOLERANCE:
                problems.append("%s: ci_low > ci_high" % label)
        if _is_primary(e) and not all(e[k] is not None for k in ("p_value", "p_holm", "reject_holm")):
            problems.append("%s: incomplete test fields" % label)
    keys = [estimate_key(e) for e in estimates if isinstance(e, dict)]
    duplicates = _duplicates(keys)
    if duplicates:
        problems.append("%d estimate key(s) occur twice: %s" % (len(duplicates), [list(d) for d in duplicates[:3]]))
    return problems


def bounds_kind(estimate):
    """'share', 'difference', 'mean' or None (no range rule: counts, quantiles,
    agreement, effort ratios, the X03 finding counts)."""
    metric, strata = estimate.get("metric_id"), _strata(estimate)
    if metric in DIFFERENCE_METRICS or metric == "X01" or (metric == "G01" and "comparison" in strata):
        return "difference"
    if metric in MEAN_METRICS or (metric == "X05" and "iteration" not in strata):
        return "mean"
    if metric == "X03" and strata.get("quantity") == X03_FINDINGS:
        return None
    if metric in SHARE_METRICS or metric in ADDENDUM_SHARE_METRICS:
        return "share"
    return None


def bounds_problems(estimates):
    problems = [] if estimates else ["no estimates"]
    for e in estimates:
        metric = e.get("metric_id")
        strata = _strata(e)
        num, den, value = e.get("numerator"), e.get("denominator"), e.get("value")
        label = "%s %s %s %s" % (metric, e.get("population"), e.get("block"), _skey(strata))
        kind = bounds_kind(e)
        difference, share = kind == "difference", kind == "share"
        if kind is None:
            continue
        if num is None or den is None:
            problems.append("%s: numerator/denominator missing" % label)
            continue
        if den < 0 or (share and not 0 <= num <= den) or (difference and abs(num) > den + TOLERANCE):
            problems.append("%s: numerator %r / denominator %r out of range" % (label, num, den))
        if kind == "mean" and not 0 <= num <= core.MAX_ITERATIONS * den:
            problems.append("%s: mean numerator %r outside [0, %d * %r]" % (label, num, core.MAX_ITERATIONS, den))
        if den == 0:
            if value is not None or e.get("ci_low") is not None or e.get("ci_high") is not None:
                problems.append("%s: value/CI for a zero denominator" % label)
            continue
        if difference and metric == "G01":
            continue
        if not _close(value, float(num) / den):
            problems.append("%s: value %r != numerator/denominator %r" % (label, value, float(num) / den))
        low, high = (0.0, 1.0) if share else ((-1.0, 1.0) if difference else (0.0, float(core.MAX_ITERATIONS)))
        for field in ("value", "ci_low", "ci_high"):
            v = e.get(field)
            if v is not None and _finite(v) and not low - TOLERANCE <= v <= high + TOLERANCE:
                problems.append("%s: %s %r outside [%s, %s]" % (label, field, v, low, high))
    return problems


def final_step_problems(estimates):
    problems = []
    steps = OrderedDict()
    for e in estimates:
        if _base_population(e.get("population")) == "STEP" and _step(_strata(e).get("step")) == core.MAX_ITERATIONS:
            rest = OrderedDict((k, v) for k, v in _strata(e).items() if k != "step")
            steps.setdefault((e.get("metric_id"), e.get("block"), _skey(rest)), []).append(e)
    pairs = 0
    q06 = 0
    for e in estimates:
        if _base_population(e.get("population")) != "FINAL":
            continue
        key = (e.get("metric_id"), e.get("block"), _skey(_strata(e)))
        for other in steps.get(key, []):
            pairs += 1
            q06 += e.get("metric_id") == "Q06"
            for field in ("numerator", "denominator", "value"):
                if not _close(e.get(field), other.get(field)):
                    problems.append("%s %s %s: FINAL %s %r, STEP k=%d %r" % (key + (field, e.get(field),
                                                                                    core.MAX_ITERATIONS,
                                                                                    other.get(field))))
            for field in ("ci_low", "ci_high"):
                if e.get(field) is not None and other.get(field) is not None and not _close(e.get(field),
                                                                                           other.get(field)):
                    problems.append("%s %s %s: FINAL %s %r, STEP k=%d %r" % (key + (field, e.get(field),
                                                                                    core.MAX_ITERATIONS,
                                                                                    other.get(field))))
    expected = len(ESTIMATE_BLOCKS) * len(core.VARIANTS)
    if q06 < expected:
        problems.append("only %d Q06 FINAL/STEP k=%d pairs, expected >= %d" % (q06, core.MAX_ITERATIONS, expected))
    return problems, pairs


class CohortSizes:
    """Base cells of a paired cohort (R01 denominators): every base cell of
    the strata; for Q06 only cells of the identical paired cohort (no
    baseline_incompatible artifact in any of the cell's trajectories,
    Recompute.q06_eligible), for E02 only cells whose base AND target
    artifact carry a valid pair. Aggregated once per (endpoint, variant,
    step)."""

    def __init__(self, index, engine=None):
        self.index = index
        self.engine = engine if engine is not None else Recompute(index)
        self.tables = {}

    def size(self, block, strata, endpoint, step):
        variant = strata.get("variant")
        key = (endpoint if endpoint in ENDPOINT_Y else None, variant, step)
        if key not in self.tables:
            groups = Counter()
            for cell_id, base in self.index.base_of.items():
                if key[0] is not None:
                    t = self.index.trajectory.get((cell_id, variant))
                    if t is None:
                        return None
                    target = self.index.target_artifact(t, step)
                    if target is None or self.engine._paired_y(endpoint, cell_id, base) is None                             or self.engine._paired_y(endpoint, cell_id, target) is None:
                        continue
                groups[_group_key(base)] += 1
            self.tables[key] = groups
        size = 0
        for (b, model, em, family, bl01), n in self.tables[key].items():
            if block != core.COMPOSITE and b != block:
                continue
            if any(strata.get(k) is not None and value != strata[k]
                   for k, value in (("model_id", model), ("execution_model", em), ("family", family))):
                continue
            if strata.get("sensitivity") == "SA1" and bl01:
                continue
            size += n
        return size


def distribution_problems(estimates, index):
    """Distribution metrics: within one group (same metric, population,
    block and filter strata) every category occurs once, the denominators
    agree, and the numerators sum to the denominator when the remaining
    strata are population filters (else they must not exceed it); R01
    denominators equal the paired cohort."""
    problems = []
    cohorts = CohortSizes(index)
    groups = OrderedDict()
    for e in estimates:
        metric = e.get("metric_id")
        if metric not in DISTRIBUTIONS:
            continue
        categories = DISTRIBUTIONS[metric]
        strata = _strata(e)
        if categories[0] not in strata:
            continue
        present = tuple(k for k in categories if k in strata)
        rest = OrderedDict((k, v) for k, v in strata.items() if k not in present)
        filters = set(DISTRIBUTION_FILTERS) - set(categories)
        exact = set(rest) <= filters
        key = (metric, e.get("population"), e.get("block"), _skey(rest), present)
        entry = groups.setdefault(key, OrderedDict([("exact", exact), ("rest", rest), ("rows", [])]))
        entry["rows"].append(e)
    checked = 0
    for key, entry in groups.items():
        rows = entry["rows"]
        categories = [tuple(_strata(e).get(k) for k in key[4]) for e in rows]
        if len(categories) != len(set(json.dumps(c, sort_keys=True) for c in categories)):
            problems.append("%s: a category occurs twice" % (key[:4],))
        denominators = set(e.get("denominator") for e in rows)
        if len(denominators) != 1 or None in denominators:
            problems.append("%s: denominators %s differ" % (key[:4], sorted(denominators, key=str)))
            continue
        den = denominators.pop()
        total = sum(e.get("numerator") or 0 for e in rows)
        checked += 1
        if entry["exact"] and not _close(total, den):
            problems.append("%s: numerators sum to %r, denominator %r" % (key[:4], total, den))
        elif not entry["exact"] and total > den + TOLERANCE:
            problems.append("%s: numerators sum to %r > denominator %r" % (key[:4], total, den))
        rest = entry["rest"]
        cohort_keys = {"endpoint", "variant", "step", "model_id", "execution_model", "family", "sensitivity"}
        if key[0] == "R01" and entry["exact"] and set(rest) <= cohort_keys and rest.get("sensitivity") in (None, "SA1"):
            endpoint = rest.get("endpoint")
            step = _step(rest.get("step")) if "step" in rest else None
            if endpoint in ENDPOINT_Y and rest.get("variant") in core.VARIANTS and ("step" not in rest or step is not None):
                size = cohorts.size(key[2], rest, endpoint, step)
                if size is not None and not _close(den, size):
                    problems.append("%s: transition denominator %r, cohort %d" % (key[:4], den, size))
            elif endpoint in ("F01", "F02") and rest.get("variant") in core.VARIANTS:
                size = cohorts.size(key[2], rest, endpoint, None)
                if size is not None and not _close(den, size):
                    problems.append("%s: transition denominator %r, cohort %d" % (key[:4], den, size))
    if not any(k[0] == "R01" for k in groups):
        problems.append("no R01 transition estimates")
    return problems, checked


def additivity_problems(estimates):
    problems = []
    by_key = OrderedDict()
    for e in estimates:
        by_key.setdefault((e.get("metric_id"), e.get("population"), e.get("block"), _skey(_strata(e))), []).append(e)
    checked = partial = 0
    for (metric, population, block, skey), rows in by_key.items():
        if block != core.COMPOSITE or metric in NON_ADDITIVE:
            continue
        if metric == "G01" and "comparison" in json.loads(skey):
            continue
        for e in rows:
            if e.get("numerator") is None or e.get("denominator") is None:
                continue
            parts = []
            for b in core.BLOCKS:
                candidates = [x for x in by_key.get((metric, population, b, skey), [])
                              if x.get("numerator") is not None and x.get("denominator") is not None]
                parts.append(candidates[0] if candidates else None)
            present = [p for p in parts if p is not None]
            if len(present) == len(core.BLOCKS):
                checked += 1
                for field in ("numerator", "denominator"):
                    total = sum(p[field] for p in present)
                    if not _close(e[field], total):
                        problems.append("%s %s %s: composite %s %r, blocks sum %r" % (metric, population, skey, field,
                                                                                       e[field], total))
            elif present:
                partial += 1
                for field in ("numerator", "denominator"):
                    if metric not in DIFFERENCE_METRICS and present[0][field] > e[field] + TOLERANCE:
                        problems.append("%s %s %s: block %s %r exceeds the composite %r"
                                        % (metric, population, skey, field, present[0][field], e[field]))
    if not checked:
        problems.append("no composite estimate with both block counterparts")
    return problems, checked, partial


def primary_problems(estimates, methodology):
    problems = []
    statistics = core.statistics_settings(methodology)
    alpha = round(1.0 - float(statistics["bootstrap"]["confidence_level"]), 12)
    primary = [e for e in estimates if _is_primary(e)]
    expected = set()
    for endpoint in PRIMARY_ENDPOINTS:
        for variant in core.VARIANTS:
            expected.add(("R04", endpoint, variant))
        for i, v1 in enumerate(core.VARIANTS):
            for v2 in core.VARIANTS[i + 1:]:
                expected.add(("R05", endpoint, tuple(sorted((v1, v2)))))
    found = []
    for e in primary:
        strata = _strata(e)
        label = "%s %s" % (e.get("metric_id"), _skey(strata))
        if e.get("metric_id") not in PRIMARY_METRICS or e.get("block") != core.COMPOSITE:
            problems.append("%s %s carries test fields outside the primary family" % (label, e.get("block")))
            continue
        if e.get("metric_id") == "R04":
            if set(strata) != {"endpoint", "variant"}:
                problems.append("%s: primary R04 strata must be endpoint and variant" % label)
                continue
            found.append(("R04", strata.get("endpoint"), strata.get("variant")))
        else:
            pair = comparison_variants(strata.get("comparison")) if set(strata) == {"endpoint", "comparison"} else None
            if pair is None:
                problems.append("%s: primary R05 strata must be endpoint and a two-variant comparison" % label)
                continue
            found.append(("R05", strata.get("endpoint"), tuple(sorted(pair))))
        if e.get("ci_method") != CI_METHOD or e.get("ci_low") is None or e.get("ci_high") is None:
            problems.append("%s: primary estimate without a cluster-bootstrap CI" % label)
        # confirmatory p-values and Holm decisions rest on replicates_primary only (statistics.tests.p_values)
        problems.extend("%s: %s" % (label, p) for p in bootstrap_problems(e, methodology))
        p, adjusted = e.get("p_value"), e.get("p_holm")
        if not (_finite(p) and 0 <= p <= 1 and _finite(adjusted) and 0 <= adjusted <= 1) or adjusted < p - TOLERANCE:
            problems.append("%s: p %r / Holm p %r invalid" % (label, p, adjusted))
        if not isinstance(e.get("reject_holm"), bool):
            problems.append("%s: reject_holm %r is not a boolean" % (label, e.get("reject_holm")))
    if len(primary) != len(expected) or sorted(found, key=str) != sorted(expected, key=str):
        problems.append("primary family: %d estimate(s) %s, expected the %d hypotheses %s"
                        % (len(primary), sorted(found, key=str)[:12], len(expected), sorted(expected, key=str)))
    if not problems:
        adjusted = holm_adjusted(OrderedDict((i, e["p_value"]) for i, e in enumerate(primary)))
        for i, e in enumerate(primary):
            if not _close(e["p_holm"], adjusted[i]):
                problems.append("%s %s: Holm p %r, recomputed %r" % (e["metric_id"], _skey(_strata(e)), e["p_holm"],
                                                                    adjusted[i]))
            if e["reject_holm"] != (adjusted[i] <= alpha):
                problems.append("%s %s: reject %r at alpha %s with Holm p %r" % (e["metric_id"], _skey(_strata(e)),
                                                                                e["reject_holm"], alpha, adjusted[i]))
        for e, expected_resolution in holm_resolutions(primary, methodology):
            if not _close(e.get("p_holm_resolution"), expected_resolution):
                problems.append("%s %s: p_holm_resolution %r, the Holm-order rule gives %r"
                                % (e["metric_id"], _skey(_strata(e)), e.get("p_holm_resolution"), expected_resolution))
    return problems, len(primary), alpha


def holm_resolutions(primary, methodology):
    """[(estimate, p_holm_resolution)] by DESIGN2 section 1: over the Holm
    order (ascending p_value, ties by the deterministic estimate order
    metric_id, population, block, strata) the running maximum of
    (m - rank + 1) * p_resolution, rank 1-based, p_resolution = 2 /
    replicates_primary. With one resolution for the whole family the running
    maximum is m * p_resolution for every hypothesis (the tie order cannot
    change it)."""
    resolution = 2.0 / int(core.statistics_settings(methodology)["bootstrap"]["replicates_primary"])
    ordered = sorted(primary, key=lambda e: (e["p_value"],) + estimate_key(e))
    m = len(ordered)
    out = []
    running = 0.0
    for rank, e in enumerate(ordered, 1):
        running = max(running, (m - rank + 1) * resolution)
        out.append((e, running))
    return out


def reproducibility_problems(estimates, rerun):
    if rerun is None:
        return ["estimates_rerun not provided: the reproducibility of the primary family is not demonstrated"]
    problems = []

    def primary(rows):
        result = OrderedDict()
        for e in rows:
            if isinstance(e, dict) and _is_primary(e):
                key = estimate_key(e)
                if key in result:
                    problems.append("primary estimate twice: %s" % (key,))
                result[key] = e
        return result

    first, second = primary(estimates), primary(rerun)
    if not first:
        problems.append("no primary estimates to compare")
    if set(first) != set(second):
        problems.append("rerun primary keys differ: %d vs %d" % (len(first), len(second)))
    for key in sorted(set(first) & set(second), key=str):
        for field in ("numerator", "denominator", "value", "ci_low", "ci_high", "replicates", "p_value", "p_holm",
                      "reject_holm") + CONTRACT_KEYS:
            if first[key].get(field) != second[key].get(field):
                problems.append("%s %s: %r, rerun %r" % (key, field, first[key].get(field), second[key].get(field)))
    return problems


# -- tables / figures -----------------------------------------------------------------------------------------

RATIO_COLUMN_KINDS = ("rate", "diff", "mean")
CI_COLUMN_KINDS = ("ci", "ci_pp")


def _ratio_cell_problems(label, column, value):
    """A structured ratio cell (tables.py: numerator, denominator, value,
    ci_low, ci_high) must carry its denominator; rate and diff cells must
    equal numerator / denominator (they are estimate facts, unrounded)."""
    kind = column.get("kind")
    if value is None:
        return []
    if not isinstance(value, dict) or "numerator" not in value or "denominator" not in value:
        return ["%s: %s cell without numerator/denominator: %s" % (label, kind, _short(value, 120))]
    num, den, val = value.get("numerator"), value.get("denominator"), value.get("value")
    if val is None:
        return []
    if not _finite(den) or not _finite(num) or den <= 0:
        return ["%s: %s value %r without a positive denominator (%r/%r)" % (label, kind, val, num, den)]
    problems = []
    if kind in ("rate", "diff") and not _close(val, float(num) / den):
        problems.append("%s: %s value %r != %r/%r" % (label, kind, val, num, den))
    if kind == "rate" and not 0 <= num <= den:
        problems.append("%s: rate %r/%r out of range" % (label, num, den))
    if kind == "diff" and abs(num) > den + TOLERANCE:
        problems.append("%s: difference %r/%r out of range" % (label, num, den))
    return problems


def table_render_problems(tables):
    """Every table names its population and unit, has unique column keys and
    headers and rows matching its columns; every percentage carries its
    denominator: structured ratio cells (column kind rate / diff / mean) carry
    numerator and denominator, a formatted percentage string needs an n/N
    in its row."""
    problems = []
    ids = [t.get("id") if isinstance(t, dict) else None for t in tables]
    duplicates = _duplicates(i for i in ids if i)
    if duplicates:
        problems.append("duplicate table id(s) %s" % duplicates)
    if not tables:
        problems.append("no tables")
    for t in tables:
        if not isinstance(t, dict):
            problems.append("a table is not an object")
            continue
        label = t.get("id") or "?"
        for field in ("id", "title", "population", "unit"):
            if not isinstance(t.get(field), str) or not t.get(field).strip():
                problems.append("table %s names no %s" % (label, field))
        columns = t.get("columns") or []
        keys = [c.get("key") for c in columns if isinstance(c, dict)]
        headers = [c.get("header") for c in columns if isinstance(c, dict)]
        if not columns or len(keys) != len(columns) or None in keys:
            problems.append("table %s has malformed columns" % label)
            continue
        if len(set(keys)) != len(keys) or len(set(headers)) != len(headers):
            problems.append("table %s: column keys/headers not unique" % label)
        rows = t.get("rows")
        if not isinstance(rows, list) or not rows:
            problems.append("table %s has no rows" % label)
            continue
        by_key = OrderedDict((c["key"], c) for c in columns)
        for position, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) != set(keys):
                problems.append("table %s row %d does not match the columns" % (label, position))
                continue
            for key, value in row.items():
                column = by_key[key]
                where = "table %s row %d %s" % (label, position, key)
                if column.get("kind") in RATIO_COLUMN_KINDS:
                    problems.extend(_ratio_cell_problems(where, column, value))
                elif column.get("kind") in CI_COLUMN_KINDS and isinstance(value, dict):
                    low, high = value.get("ci_low"), value.get("ci_high")
                    if _finite(low) and _finite(high) and low > high + TOLERANCE:
                        problems.append("%s: CI [%r, %r] inverted" % (where, low, high))
            texts = [v for v in row.values() if isinstance(v, str)]
            shares = [v for v in texts if PERCENT_RE.match(v) or (v.strip().endswith("%") and not FRACTION_RE.search(v))]
            if shares and not any(FRACTION_RE.search(v) for v in texts):
                problems.append("table %s row %d: percentage cell(s) %s without an n/N denominator"
                                % (label, position, shares[:2]))
    return problems


def _norm(text):
    return " ".join(str(text).split())


def _strings(value):
    """Every string inside a (nested) note structure."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def _row_cells(value):
    """Every mapping inside a table row value (cells may nest)."""
    if isinstance(value, dict):
        yield value
        for v in value.values():
            for c in _row_cells(v):
                yield c
    elif isinstance(value, (list, tuple)):
        for v in value:
            for c in _row_cells(v):
                yield c


def bl01_groups(index):
    """(block, model, execution model, family) of the BL-01 base cells."""
    return frozenset((c["block"], c["model_id"], c["execution_model"], c["family"])
                     for c in index.base_cells if c["bl01"])


def bl01_cell(cell, groups=None):
    """Whether a table cell shows a pilot / composite Q06 or E02 aggregate
    that contains BL-01 cells (module docstring): its source metric is one of
    BL01_METRICS or carries the endpoint stratum Q06 / E02. groups None (no
    dataset): every such pilot / composite cell except SA1 and other
    families."""
    source = cell.get("source")
    if not isinstance(source, dict):
        return False
    strata = source.get("strata") if isinstance(source.get("strata"), dict) else {}
    if source.get("metric_id") not in BL01_METRICS and strata.get("endpoint") not in PRIMARY_ENDPOINTS:
        return False
    block = source.get("block")
    if block not in BL01_BLOCKS or strata.get("sensitivity") == "SA1":
        return False
    if groups is None:
        return strata.get("family") in (None, core.family_of(core.BL01_BENCHMARK))
    return any((block == core.COMPOSITE or b == block) and all(
        strata.get(key) is None or str(strata.get(key)) == value
        for key, value in (("model_id", model), ("execution_model", em), ("family", family)))
        for b, model, em, family in groups)


def post_freeze_cell(cell, addendum_ids):
    """Whether a table / figure cell shows a post-freeze addendum result: its
    source metric is an addendum id or the cell (or its source) carries
    post_freeze true."""
    source = cell.get("source")
    if cell.get("post_freeze") is True:
        return True
    return isinstance(source, dict) and (source.get("metric_id") in addendum_ids or source.get("post_freeze") is True)


def _example(cell):
    source = cell.get("source") if isinstance(cell.get("source"), dict) else cell
    return "%s %s %s" % (source.get("metric_id"), source.get("block"), _short(source.get("strata"), 80))


def post_freeze_problems(kind, label, cells, title, carried, addendum_ids, facts):
    """A table / figure showing post-freeze cells carries the POST-FREEZE
    label in its title or its notes (the addendum rule: every addendum item
    is labelled post-freeze and presented as post-hoc)."""
    post = [c for c in cells if post_freeze_cell(c, addendum_ids)]
    if not post:
        return []
    facts["post_freeze_%ss" % kind] += 1
    if POST_FREEZE_LABEL in _norm(title) or POST_FREEZE_LABEL in carried:
        return []
    return ["%s %s shows %d post-freeze addendum cell(s) (e.g. %s) without the %s label in its title or notes"
            % (kind, label, len(post), _example(post[0]), POST_FREEZE_LABEL)]


def table_note_problems(tables, addendum, index=None):
    """DESIGN2 sections 2.1, 2.2, 2.8 and 3.5: a table with a pilot /
    composite Q06 / E02 cell (bl01_cell) carries the addendum's BL01 note
    text (notes, footnotes or CI note); a table with a post-freeze cell
    carries the POST-FREEZE label (title or notes) and T12_addendum's title
    starts with 'POST-FREEZE (addendum_1, descriptive): '. Intervals are
    shown (and marked with the dagger) only in the columns of kind ci / ci_pp
    (CI_COLUMN_KINDS): there a finite ci_low == ci_high is marked (cell
    ci_degenerate true), a marked one is degenerate, and a table showing one
    carries the DEGENERATE_CI note text. A cell of another kind (rate / diff
    / mean: 'value (n/N)', no interval) needs no mark and no note; its
    ci_degenerate must only agree with its bounds."""
    texts = table_note_texts(addendum)
    bl01, degenerate_note = _norm(texts["BL01"]), _norm(texts["DEGENERATE_CI"])
    groups = bl01_groups(index) if index is not None else None
    addendum_ids = frozenset(core.addendum_metric_ids(addendum))
    title_prefix = table_title_prefix(addendum)
    problems = []
    facts = Counter()
    for t in tables:
        if not isinstance(t, dict):
            continue
        label = t.get("id") or "?"
        title = t.get("title") if isinstance(t.get("title"), str) else ""
        carried = _norm(" ".join(_strings([t.get("notes"), t.get("footnotes"), t.get("ci_note")])))
        kinds = OrderedDict((c.get("key"), c.get("kind")) for c in t.get("columns") or [] if isinstance(c, dict))
        located = [(key, kinds.get(key), c) for row in t.get("rows") or [] if isinstance(row, dict)
                   for key, v in row.items() for c in _row_cells(v)]
        cells = [c for _, _, c in located]
        triggering = [c for c in cells if bl01_cell(c, groups)]
        if triggering:
            facts["bl01_tables"] += 1
            if bl01 not in carried:
                problems.append("table %s shows %d pilot/composite Q06/E02 cell(s) (e.g. %s) without the BL01 note"
                                % (label, len(triggering), _example(triggering[0])))
        problems.extend(post_freeze_problems("table", label, cells, title, carried, addendum_ids, facts))
        if label == ADDENDUM_TABLE and not title.startswith(title_prefix):
            problems.append("table %s: the title %r does not start with %r" % (label, title[:80], title_prefix))
        degenerate = 0
        for key, kind, c in located:
            if "ci_low" not in c and "ci_high" not in c and "ci_degenerate" not in c:
                continue
            low, high, flag = c.get("ci_low"), c.get("ci_high"), c.get("ci_degenerate")
            zero = _finite(low) and _finite(high) and low == high
            if kind not in CI_COLUMN_KINDS:
                if zero:
                    facts["degenerate_unshown_cells"] += 1
                if (flag is True and not zero) or (flag is False and zero):
                    problems.append("table %s column %s (kind %s, no interval shown): ci_degenerate %r contradicts "
                                    "the bounds [%r, %r]" % (label, key, kind, flag, low, high))
            elif flag is True and not zero:
                problems.append("table %s column %s: a dagger-marked interval [%r, %r] is not degenerate"
                                % (label, key, low, high))
            elif zero:
                degenerate += 1
                if flag is not True:
                    problems.append("table %s column %s: the degenerate interval [%r, %r] is not marked "
                                    "(ci_degenerate %r)" % (label, key, low, high, flag))
        facts["degenerate_cells"] += degenerate
        if degenerate and degenerate_note not in carried:
            problems.append("table %s shows %d degenerate interval(s) without the DEGENERATE_CI note"
                            % (label, degenerate))
    return problems, facts


def _figure_cells(figure):
    """The cells of a figure's data rows that name their estimate: nested
    mappings with a source, or rows carrying a metric_id themselves (then the
    row is its own source)."""
    out, sources = [], set()
    for row in figure.get("data_rows") or []:
        for c in _row_cells(row):          # parents before their children
            if isinstance(c.get("source"), dict):
                out.append(c)
                sources.add(id(c["source"]))
            elif "metric_id" in c and id(c) not in sources:
                out.append(OrderedDict([("source", c), ("post_freeze", c.get("post_freeze"))]))
    return out


def figure_note_problems(figures, addendum, index=None):
    """The disclosures of the figures (DESIGN2 sections 2.1, 2.2): the notes
    FIGURE_NOTES names per fixed figure id (BL01 on F1/F2/F3/F5, REASONING on
    F3/F5, EFFECTIVE_STATES on F4), REASONING on every figure with a
    per-model data column, BL01 on every figure whose data rows name a pilot
    / composite Q06 / E02 source, the POST-FREEZE label for post-freeze
    sources and the DEGENERATE_CI note when a data row carries ci_degenerate
    true (the figures draw / tabulate the interval of their rows). The note
    texts come from the addendum and are looked for in the title, notes and
    footnotes (figure_caption_tex prints these)."""
    texts = table_note_texts(addendum)
    groups = bl01_groups(index) if index is not None else None
    addendum_ids = frozenset(core.addendum_metric_ids(addendum))
    problems = []
    facts = Counter()
    for f in figures:
        if not isinstance(f, dict):
            continue
        label = f.get("id") or "?"
        title = f.get("title") if isinstance(f.get("title"), str) else ""
        carried = _norm(" ".join(_strings([f.get("title"), f.get("notes"), f.get("footnotes"), f.get("caption")])))
        cells = _figure_cells(f)
        columns = [c.get("key") if isinstance(c, dict) else c for c in f.get("data_columns") or []]
        demanded = OrderedDict((note, "DESIGN2 section 2.2") for note in FIGURE_NOTES.get(label, ()))
        if any(c in MODEL_COLUMNS for c in columns):
            demanded.setdefault("REASONING", "per-model data column")
        triggering = [c for c in cells if bl01_cell(c, groups)]
        if triggering:
            demanded.setdefault("BL01", "pilot/composite Q06/E02 source (e.g. %s)" % _example(triggering[0]))
        if any(isinstance(row, dict) and row.get("ci_degenerate") is True for row in f.get("data_rows") or []):
            demanded.setdefault("DEGENERATE_CI", "a data row with ci_degenerate true")
        for note, reason in demanded.items():
            text = texts.get(note)
            if not isinstance(text, str) or not text.strip():
                raise core.AnalysisRefused("the addendum carries no %s table note" % note)
            facts["%s_figures" % note.lower()] += 1
            if _norm(text) not in carried:
                problems.append("figure %s lacks the %s note (%s)" % (label, note, reason))
        problems.extend(post_freeze_problems("figure", label, cells, title, carried, addendum_ids, facts))
    return problems, facts


def figure_problems(figures):
    problems = []
    ids = [f.get("id") if isinstance(f, dict) else None for f in figures]
    duplicates = _duplicates(i for i in ids if i)
    if duplicates:
        problems.append("duplicate figure id(s) %s" % duplicates)
    if not figures:
        problems.append("no figures")
    for f in figures:
        if not isinstance(f, dict):
            problems.append("a figure is not an object")
            continue
        label = f.get("id") or "?"
        for field in ("id", "title", "kind"):
            if not isinstance(f.get(field), str) or not f.get(field).strip():
                problems.append("figure %s names no %s" % (label, field))
        columns = f.get("data_columns") or []
        names = [c.get("key") if isinstance(c, dict) else c for c in columns]
        if not names or len(set(map(str, names))) != len(names):
            problems.append("figure %s: data columns empty or not unique" % label)
            continue
        rows = f.get("data_rows")
        if not isinstance(rows, list) or not rows:
            problems.append("figure %s has no data rows" % label)
            continue
        for position, row in enumerate(rows):
            ok = (isinstance(row, dict) and set(row) == set(names)) or \
                (isinstance(row, (list, tuple)) and len(row) == len(names))
            if not ok:
                problems.append("figure %s data row %d does not match the data columns" % (label, position))
                break
    return problems


# -- input stability ---------------------------------------------------------------------------------------------

MANIFEST_IDENTITY_BLOCKS = ("package_sources", "methodology", "addendum", "closure", "composite", "acceptance")


def manifest_problems(root, manifest, dataset, start=None, write_mode=False, preflight_head=None, addendum=None):
    """The end manifest describes THIS dataset and its inputs did not change.

    * self-hash; dataset_inputs (targets, lineage, census digest, readers,
      table counts) == the dataset's provenance and counts; files_read is
      non-empty and lists every file the normalizer read with the sha256 it
      recorded; manifest.rehash() finds no changed input;
    * the manifest's addendum identity is the addendum the validation used
      (canonical sha256, when given);
    * with the start manifest (built before the normalizer ran): self-hash,
      identical code pins, methodology, addendum, closure, composite,
      acceptance and git HEAD, every start file in the end manifest with the
      same sha256;
    * write mode: both manifests were built on a clean worktree at the HEAD
      the write-mode preflight passed on (a missing start manifest or
      preflight head FAILS)."""
    problems = []
    if not manifest:
        raise core.AnalysisRefused("no input manifest")
    if dataset is None or not hasattr(dataset, "provenance"):
        raise core.AnalysisRefused("no dataset to bind the manifest to")
    mf.verify_manifest(manifest)
    provenance = dataset.provenance
    inputs = manifest.get("dataset_inputs") or {}
    for key in ("targets_sha256", "census_digest"):
        if not provenance.get(key):
            problems.append("the dataset provenance lacks %s" % key)
    for key in ("targets_sha256", "lineage_sha256", "census_digest"):
        _diff(problems, "dataset_inputs.%s (dataset vs manifest)" % key, provenance.get(key), inputs.get(key))
    _diff(problems, "dataset_inputs.readers (dataset vs manifest)", list(provenance.get("readers") or []),
          inputs.get("readers"))
    _diff(problems, "dataset_inputs.counts (dataset vs manifest)", dataset.counts(), inputs.get("counts"))
    files = manifest.get("files_read") or {}
    read = provenance.get("files_read") or {}
    if not files:
        problems.append("the manifest lists no input file (a start manifest cannot bind the dataset)")
    if not read:
        problems.append("the dataset provenance lists no file the normalizer read")
    unlisted = sorted(r for r in read if r not in files)
    if unlisted:
        problems.append("%d file(s) the normalizer read are not in the manifest: %s" % (len(unlisted), unlisted[:3]))
    differing = sorted(r for r, sha in read.items() if r in files and (files[r] or {}).get("raw_sha256") != sha)
    if differing:
        problems.append("%d file(s) carry another sha256 in the manifest than the normalizer recorded: %s"
                        % (len(differing), differing[:3]))
    problems.extend("input changed: %s" % c for c in mf.rehash(root, manifest))
    if addendum is not None:
        _diff(problems, "addendum canonical_sha256 (validated vs manifest)", canonical_sha256(addendum),
              (manifest.get("addendum") or {}).get("canonical_sha256"))
    head = (manifest.get("git") or {}).get("head")
    if start is not None:
        mf.verify_manifest(start)
        for key in MANIFEST_IDENTITY_BLOCKS:
            if _plain(start.get(key)) != _plain(manifest.get(key)):
                problems.append("%s differs between the start and the end manifest" % key)
        _diff(problems, "git.head (start vs end manifest)", (start.get("git") or {}).get("head"), head)
        for relative, facts in (start.get("files_read") or {}).items():
            if (files.get(relative) or {}).get("raw_sha256") != (facts or {}).get("raw_sha256"):
                problems.append("start-manifest input %s is missing from or differs in the end manifest" % relative)
    if write_mode:
        if start is None:
            problems.append("write mode needs the start manifest")
        if not preflight_head:
            problems.append("write mode needs the HEAD the write-mode preflight passed on")
        for name, document in (("end", manifest), ("start", start)):
            if document is None:
                continue
            git = document.get("git") or {}
            if git.get("clean") is not True:
                problems.append("write mode: the %s manifest was built on a dirty worktree (%s path(s))"
                                % (name, git.get("uncommitted_count")))
            if preflight_head and git.get("head") != preflight_head:
                problems.append("write mode: the %s manifest HEAD %s is not the preflight HEAD %s"
                                % (name, git.get("head"), preflight_head))
    return problems


# -- the validation ----------------------------------------------------------------------------------------------

def validate(root, config, table, dataset, estimates, tables, figures, manifest, composite_cells=None,
             estimates_rerun=None, census_result=None, methodology=None, manifest_start=None, write_mode=False,
             preflight_head=None, addendum=None):
    """OrderedDict(schema_version, analysis_id, status, checks, summary,
    validation_sha256). Never raises; reads only.

    manifest is the END manifest (built after aggregation over the dataset);
    manifest_start the manifest built before the normalizer ran; write_mode
    and preflight_head (the HEAD the write-mode preflight passed on) bind a
    formal run to clean committed inputs (manifest_problems); addendum is the
    post-freeze addendum the estimates were computed with (None: loaded from
    root and bound to the methodology)."""
    root = Path(root).resolve()
    gate = pf.CheckList()
    state = OrderedDict()
    estimates = list(estimates or [])

    def need(key):
        if key not in state:
            raise core.AnalysisRefused("input unavailable: %s (an earlier check failed to provide it)" % key)
        return state[key]

    def index_step():
        state["index"] = Index(dataset)
        state["methodology"] = methodology if methodology is not None else core.load_methodology(root)
        return True, OrderedDict([("counts", dataset.counts())])

    gate.guard("dataset_index", index_step)

    def addendum_step():
        document = bound_addendum(root, need("methodology"), addendum)
        state["addendum"] = document
        return True, OrderedDict([("addendum_id", document.get("addendum_id")), ("status", document.get("status")),
                                  ("canonical_sha256", canonical_sha256(document)),
                                  ("metrics", core.addendum_metric_ids(document)),
                                  ("methodology_canonical_sha256", canonical_sha256(need("methodology")))])

    gate.guard("addendum_bound", addendum_step)

    def inputs_bound():
        document, raw, _ = pf.read_composite(root)
        state["composite"] = document
        provenance = dataset.provenance
        problems = []
        if document.get("composite_sha256") != core.EXPECTED_COMPOSITE_SHA256:
            problems.append("persisted composite %s is not the expected %s" % (document.get("composite_sha256"),
                                                                             core.EXPECTED_COMPOSITE_SHA256))
        if table is None:
            raise core.AnalysisRefused("no target table")
        _diff(problems, "targets_sha256 (table vs dataset)", table.sha256, provenance.get("targets_sha256"))
        _diff(problems, "targets_sha256 (composite vs table)", document.get("targets_sha256"), table.sha256)
        lineage_sha = provenance.get("lineage_sha256") or pl.load(root).sha256
        state["lineage_sha"] = lineage_sha
        _diff(problems, "lineage_sha256 (composite vs dataset)", document.get("lineage_sha256"), lineage_sha)
        result = census_result if census_result is not None else cs.census(root, list(core.MODELS))
        state["census_result"] = result
        state["census_summary"] = cs.summary(result)
        digest = canonical_sha256(state["census_summary"])
        _diff(problems, "census_digest (census vs dataset)", digest, provenance.get("census_digest"))
        return not problems, _detail(problems, composite_sha256=document.get("composite_sha256"), composite_raw_sha256=raw,
                                     targets_sha256=table.sha256, lineage_sha256=lineage_sha, census_digest=digest)

    gate.guard("inputs_bound", inputs_bound)

    def counts_composite():
        problems = composite_count_problems(need("composite"), need("index"))
        return not problems, _detail(problems, cells=need("composite").get("cells"))

    gate.guard("counts_composite", counts_composite)

    def counts_coverage():
        problems = stage_coverage_problems(need("composite"), need("index"))
        return not problems, _detail(problems)

    gate.guard("counts_stage_coverage", counts_coverage)

    def counts_census():
        problems = census_count_problems(need("census_summary"), need("census_result"), need("index"),
                                         dataset.provenance.get("census_digest"))
        return not problems, _detail(problems, repair_loops=need("census_summary").get("total_repair_loops_done"))

    gate.guard("counts_census", counts_census)

    def ledgers():
        histories = ledger_histories(root, need("census_result"))
        problems = ledger_problems(histories, need("index"))
        return not problems, _detail(problems, ledger_samples=len(histories))

    gate.guard("trajectories_ledger", ledgers)

    def binding():
        index = need("index")
        document = need("composite")
        cells = list(composite_cells) if composite_cells is not None else list(pc.iter_cells(root, config, table))
        problems, subsumed = binding_problems(cells, index)
        rebuilt = pc.composite_document(root, config, table, need("lineage_sha"), document.get("plan_totals"),
                                        cells=cells)
        if rebuilt.get("composite_sha256") != document.get("composite_sha256"):
            problems.insert(0, "the composite cells reproduce %s, the persisted composite is %s"
                            % (rebuilt.get("composite_sha256"), document.get("composite_sha256")))
        if rebuilt.get("composite_sha256") != core.EXPECTED_COMPOSITE_SHA256:
            problems.insert(0, "the reproduced composite %s is not the expected %s"
                            % (rebuilt.get("composite_sha256"), core.EXPECTED_COMPOSITE_SHA256))
        return not problems, _detail(problems, cells=len(cells), reproduced_sha256=rebuilt.get("composite_sha256"),
                                     subsumed_rejections=subsumed)

    gate.guard("composite_binding", binding)

    gate.guard("uniqueness", lambda: _wrap(uniqueness_problems(need("index"))))
    gate.guard("ownership", lambda: _wrap(ownership_problems(need("index"))))

    def excluded():
        files = list((dataset.provenance.get("files_read") or {}).keys())
        files += list(((manifest or {}).get("files_read") or {}).keys())
        files += list(((manifest_start or {}).get("files_read") or {}).keys())
        problems = excluded_problems(need("index"), files)
        return not problems, _detail(problems, files_checked=len(files))

    gate.guard("excluded_runs", excluded)

    def blocks():
        problems, benchmarks = block_problems(need("index"))
        return not problems, _detail(problems, benchmarks=benchmarks)

    gate.guard("block_separation", blocks)

    def targets_check():
        if table is None:
            raise core.AnalysisRefused("no target table")
        problems = table_problems(table, need("index"))
        return not problems, _detail(problems, targets=len(table.targets))

    gate.guard("table_targets", targets_check)

    def consistency():
        scope = _tool_scope(config)
        problems = []
        for stage, tools in (("static", core.STATIC_TOOLS), ("dynamic", core.DYNAMIC_TOOLS)):
            if sorted(scope.get(stage) or {}) != sorted(tools):
                problems.append("config %s tools %s differ from %s" % (stage, list(scope.get(stage) or {}), list(tools)))
        problems.extend(consistency_problems(need("index"), scope))
        return not problems, _detail(problems)

    gate.guard("dataset_consistency", consistency)

    def applicability():
        problems, inapplicable_gaps = applicability_problems(need("index"))
        return not problems, _detail(problems, inapplicable_tools_in_gap_states=inapplicable_gaps)

    gate.guard("applicability", applicability)

    def gates():
        problems, facts = gate_problems(need("index"))
        return not problems, _detail(problems, **facts)

    gate.guard("enhanced_gates", gates)
    gate.guard("trajectory_structure", lambda: _wrap(trajectory_problems(need("index"))))
    gate.guard("estimates_schema", lambda: _wrap(schema_problems(estimates, need("methodology"), need("addendum"),
                                                                 need("index"))))

    def coverage():
        expected = set(core.all_metric_ids(need("methodology"), need("addendum")))
        produced = set(e.get("metric_id") for e in estimates if isinstance(e, dict))
        problems = []
        if produced - expected:
            problems.append("unknown metric ids %s" % sorted(produced - expected, key=str))
        if expected - produced:
            problems.append("metric ids without an estimate %s" % sorted(expected - produced))
        post_freeze = sum(1 for e in estimates if isinstance(e, dict) and e.get("post_freeze") is True)
        return not problems, _detail(problems, metrics=len(expected), estimates=len(estimates),
                                     post_freeze_estimates=post_freeze)

    gate.guard("metric_coverage", coverage)
    gate.guard("estimate_bounds", lambda: _wrap(bounds_problems(estimates)))

    def recompute():
        problems, facts = recompute_problems(estimates, need("index"), need("methodology"), need("addendum"))
        return not problems, _detail(problems, **facts)

    gate.guard("estimate_recompute", recompute)

    def final_step():
        problems, pairs = final_step_problems(estimates)
        return not problems, _detail(problems, pairs=pairs)

    gate.guard("final_equals_step2", final_step)

    def distributions():
        problems, groups = distribution_problems(estimates, need("index"))
        return not problems, _detail(problems, groups=groups)

    gate.guard("distribution_sums", distributions)

    def additivity():
        problems, checked, partial = additivity_problems(estimates)
        return not problems, _detail(problems, checked=checked, partial_counterparts=partial)

    gate.guard("block_additivity", additivity)

    def primary():
        problems, n, alpha = primary_problems(estimates, need("methodology"))
        return not problems, _detail(problems, hypotheses=n, alpha=alpha)

    gate.guard("primary_family", primary)

    def tables_check():
        problems = table_render_problems(list(tables or []))
        notes, facts = table_note_problems(list(tables or []), need("addendum"), need("index"))
        problems.extend(notes)
        return not problems, _detail(problems, tables=len(tables or []), **facts)

    gate.guard("tables", tables_check)

    def figures_check():
        problems = figure_problems(list(figures or []))
        notes, facts = figure_note_problems(list(figures or []), need("addendum"), need("index"))
        problems.extend(notes)
        return not problems, _detail(problems, figures=len(figures or []), **facts)

    gate.guard("figures", figures_check)

    def stability():
        problems = manifest_problems(root, manifest, dataset, manifest_start, write_mode, preflight_head,
                                     need("addendum"))
        return not problems, _detail(problems, files=len(manifest.get("files_read") or {}),
                                     manifest_sha256=manifest.get("manifest_sha256"),
                                     start_manifest_sha256=(manifest_start or {}).get("manifest_sha256"),
                                     write_mode=bool(write_mode))

    gate.guard("input_stability", stability)
    gate.guard("reproducibility", lambda: _wrap(reproducibility_problems(estimates, estimates_rerun)))
    counts = dataset.counts() if hasattr(dataset, "counts") else None
    summary = OrderedDict([
        ("checks", len(gate.checks)), ("passed", len(gate.checks) - len(gate.failing())),
        ("failing", gate.failing()), ("dataset_counts", counts), ("estimates", len(estimates)),
        ("tables", len(tables or [])), ("figures", len(figures or [])),
        ("composite_sha256", (state.get("composite") or {}).get("composite_sha256")),
        ("addendum_canonical_sha256", canonical_sha256(state["addendum"]) if "addendum" in state else None),
        ("census_digest", canonical_sha256(state["census_summary"]) if "census_summary" in state else None),
        ("manifest_sha256", (manifest or {}).get("manifest_sha256")),
    ])
    document = OrderedDict([("schema_version", core.VALIDATION_SCHEMA), ("analysis_id", core.ANALYSIS_ID),
                            ("status", gate.status), ("checks", gate.checks), ("summary", summary)])
    document = core.json_stable(document)
    document["validation_sha256"] = core.self_hash(document, "validation_sha256")
    return document


def _wrap(problems):
    return not problems, _detail(problems)
