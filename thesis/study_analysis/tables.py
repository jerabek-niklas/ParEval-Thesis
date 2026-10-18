"""Study tables T1..T12 built from the metric estimates (no file system access).

Every table is an OrderedDict

    id, title, population, unit, notes [str], ci_note (str or None),
    columns [OrderedDict(key, header, align, kind[, group, sub, digits, mark, width, display])],
    rows [OrderedDict(column key -> raw cell)], footnotes [OrderedDict(mark, text)]

Raw cells keep the UNROUNDED estimate facts (rounding happens only when a
table is rendered: table_csv here, table_tex in latex.py), so the JSON form is
machine-readable and every rendered number can be traced back to its
estimate. A rate cell is OrderedDict(numerator, denominator, value, ci_low,
ci_high, ci_method, replicates, primary, excluded, ci_degenerate,
post_freeze, note, source): numerator and denominator travel with every
percentage (the "n/N" of the rendering), the interval facts (method,
replicate count, primary family or not, zero width) with every CI, the
exclusion count of the methodology's missingness rule (`excluded`, rendered
"k excl." when k > 0) and the producer's note with every estimate, and
`source` names the estimate (metric, population, block, strata - strata
values keep the estimate's types, e.g. step stays an int). Plain counts are
ints; p-values floats or OrderedDict(value, resolution); flags bools; labels
strings; None renders as "--".

Column kinds: text, block (pilot carries the footnote mark), count, rate
("pct (n/N)"), ci ("[lo, hi]" in percent), diff ("+pp (+n/N)"), ci_pp, mean
("x.xx (num/den)"), pp (signed difference only), number (column digits),
dnumber ({value, digits}), p (a plain float, or {value, resolution}: a p below
its resolution is shown as "<resolution"; optional column `resolution`),
flag, count_pair ([findings, n, N] -> "f (n/N)"), mapping (further
statistics "k=v; ..."). A text column may carry `display` (raw value ->
shown label, e.g. an abbreviation explained in the notes); the JSON keeps the
raw value.

Estimate contract (spec 3.2 + DESIGN2 section 1, as produced by metrics.py;
strata values are compared as strings, so step 0 == "0"):
  * every estimate carries post_freeze (True exactly for the addendum
    metrics X01-X06), ci_degenerate (None without an interval, else
    ci_low == ci_high), p_resolution / p_holm_resolution (primary family
    only: 2 / replicates_primary and the Holm-order running maximum of
    (m - rank + 1) * p_resolution); a missing or contradicting key refuses.
  * FINAL[v] = population "FINAL" + strata variant; STEP[v][k] = "STEP" +
    variant + step; strata {} is the "all" row; per model / execution model /
    family via the keys model_id / execution_model / family.
  * E01 (unit: pair) lives in ENH_PAIRS(BASE) / ENH_PAIRS(STEP) /
    ENH_PAIRS(FINAL); E04 in ENH_PAIRS(BASE|GENERATED) (extra gated_groups).
  * Q04 sub-metrics: strata flag (cleaning flag, "any", "any_including_fence").
  * S01/D01: strata tool + state; S02/D02: tool (+ execution_model); D03:
    {} / execution_model; F01/F02: state (three-state); R06: status (or
    status + one of step / final_iteration / iteration, which is summed).
  * R01: endpoint + variant + transition; R02/R03/R04: strata endpoint
    ("Q06" / "E02") + variant; R05: endpoint + comparison; SA1 adds strata
    sensitivity "SA1" (Q06 BASE/FINAL, R02, R04, R05 for both endpoints);
    G01: variant (share) and variant + one comparison label (difference to
    the E05 BASE reference, extra reference_numerator/denominator); G02:
    endpoint + variant + step.
  * X01 FINAL: endpoint + variant (net gain) / endpoint + comparison (as R05),
    with excluded; X02 BASE state (+ execution_model), FINAL variant + state,
    DIRTY with dirty_only_under_frozen_rule; X03 BASE tool + quantity
    dirty_only_via_tool and tool + check_id + quantity blocking_findings /
    artifacts_with_check; X04 BASE state / FINAL variant + state; X05
    TRAJECTORIES variant (mean) and variant + iteration (share); X06 FINAL
    variant + transition + heldout_transition (the R01 Q06 / E02 labels).
  * Populations of R*, G*, C01, C03, C04, C05 and F06 are matched by
    wildcard (a unique match is required, an ambiguous one refuses).
  * F05: strata tool + family + kind + quantity ("findings" count /
    "artifacts_with_finding" share); F06: one estimate per tool pair (strata
    pair / class), extra keys n11, n10, n01, n00, positive_agreement, kappa.
  * C01/C02/C05 sub-quantities in strata quantity (C02 "output_tokens" is
    the token sum used by F5); C03/C04: value = median, extra keys p95, n;
    C04 strata tool (+ execution_model) + outlier_rule ("all" /
    "excluding_above_threshold"), extra key timeouts.
  * the primary family = estimates with p_holm not None (its size is parsed
    from the methodology by stats.bootstrap_settings).

Row sets are never taken from whatever estimates exist: models and execution
models come from the dataset (summarize_dataset: per block, execution models
within the methodology strata), tools from the frozen core.STATIC_TOOLS /
DYNAMIC_TOOLS (and must equal the dataset's tool entries), F06 pairs from the
methodology's predefined pairs, the effort grid from the dataset's
trajectories / repair candidates per variant, the runtime grid from the
dataset's ran tool entries (C04 ran_entries must equal the dataset count),
the X06 transition labels from the R01 estimates and the X03 check ids from
the composite (selected once there, required in every block). Every expected
stratum is looked up as required, and estimates carrying a different set
refuse. (Model ids outside core.MODELS are ordered after them, not refused
here: model identity is checked by normalize / validate, and the synthetic
test datasets use synthetic ids.)

Interval statement: the CI note of a table is generated from the intervals it
actually shows: every shown interval must carry ci_method and its replicate
count, and the DRAWN count must be the methodology's (replicates_primary for
the primary family, replicates_descriptive otherwise). `replicates` is the
number of usable replicates (stats.py skips resamples with a zero
denominator and the note says "k of B bootstrap replicates skipped"), so the
drawn count is usable + skipped and such intervals are counted in the note.
A different drawn count is only accepted when the producer labelled the
estimate EXPLORATORY, and then the table title and CI note carry the label
(never a silent misstatement). A shown interval of zero width
(ci_degenerate) carries a dagger (CSV: appended to the CI text; LaTeX:
\\textsuperscript{\\dag}) and the table the addendum's DEGENERATE_CI note as
the dagger footnote.

Disclosures (addendum, never typed here): the table notes BL01 (every table
showing a pilot or composite aggregate of Q06 / E01 / E02 or of a metric
resting on them, see IMPLIED_REFS), REASONING (every table with a per-model
cell), EFFECTIVE_STATES (the ids its applies_to names) and the interpretive
caveats IC1..IC7 (by applies_to: an exact table / figure id - only the ids
the outputs split, SPLIT_IDS T2_initial_quality / T7_heldout, cover their
parts, any other unknown id refuses -, a metric id the table shows, directly,
as an endpoint stratum or via IMPLIED_REFS, or a variant name: the caveat then
attaches to every table / figure showing an estimate of that variant, by
strata variant or by a comparison label naming it, e.g. IC6 on every
static_feedback result) are appended to the notes as
"<id>: <text>". Tables showing post-freeze (X) estimates carry a
POST-FREEZE note built from the addendum (id, status, declaration date and
each metric's limits); the addendum tables' titles start "POST-FREEZE
(addendum_1, descriptive): ".

Fail closed (core.AnalysisRefused): an unknown metric id, block or ci_method,
duplicate estimates, a missing estimate the spec guarantees, an ambiguous
wildcard match, contradictions between estimates that the methodology ties
together (R04 = R02 - R03 numerators, STEP[v][0] == BASE, STEP[v][2] ==
FINAL[v], the identical-cohort rule: BASE, STEP[v][k], FINAL[v], the paired
R02-R04 cells and X01 rest on the same units (denominator + excluded),
R07/R08 == R06 statuses, R06 sums / E04 (incl. gated groups) / Q01 == the
dataset inventory, per-block primary estimates add up to the composite,
one X01 cohort (denominator and excluded) for every variant and comparison
of a (block, endpoint) - the auto-closed rule removes a base cell over all
three trajectories, X02 DIRTY == F01 DIRTY - dirty_only_under_frozen_rule,
X03 only for core.STATIC_ANALYSIS_TOOLS in the contract strata, at most the
addendum's top-N check ids per tool, dirty-only denominators == F01 BASE
DIRTY and artifacts_with_check denominators == the S02 BASE denominator of
the tool, X04 denominator == the Q06 failing artifacts (Q06 denominator -
numerator of the same population), X05 mean numerator == sum of k * n_k, X06
cohort within the cells of both R04 paired cohorts and its marginals within
the R01 Q06 / E02 transition counts), a
missing excluded count where the methodology reports exclusions (Q04,
Q06/Q07/Q09/Q10, E02, R01-R05, G01, X01), contract keys (post_freeze,
ci_degenerate, p_resolution, p_holm_resolution) that are missing or
contradict their rule, and a primary family other than the methodology's
composite R04/R05 hypotheses at the primary replicate count (the DRAWN count:
usable + skipped replicates). An explicitly passed addendum must pass the
checks of core.load_addendum (schema, status, binding to the methodology in
use by its canonical sha256, metric ids). A category of a
counts-and-shares distribution without an estimate is 0 ONLY when the present
categories already sum to the common denominator; otherwise the distribution
is incomplete and the table refuses. Cells the producer does not compute at a
stratification (F01/F02 per model x execution model) render "--" under a
column header carrying a footnote, never a default. GENERATED /
REPAIR_CANDIDATES numbers carry the methodology's "diagnostic" use in the
population field and notes. p = 0 of the primary family is shown as
"<p_resolution" and its Holm-adjusted p as "<p_holm_resolution".

Readings documented as deviations: T1 is split into T1 (counts) and T1b
(evidence owners, input identities); T2 is split per block and metric group
(T2a/T2b/T2c = composite/pilot/full_ext with Q02 Q05 Q06 Q04, T2d/T2e/T2f =
the same blocks with E01 E02 E04 F01 F02) so that each part fits a page; T6
is split into T6 (stops) and T6b (effort, long format, one row per
C01/C02/C03/C05 estimate, because the shapes of these multi-quantity metrics
are not pinned by the spec); T7 is split into T7a (rates: E01 BASE/FINAL,
G02 steps of E02 and Q06 - step 0 is BASE and the last step FINAL, checked),
T7b (E02 transitions, G01 vs E05) and T7c (the X06 crosstab: rows variant x
Q06 transition, columns E02 transitions; its shape does not align with the
block x variant rows of T7b); T8 shows D03 (dynamic analysis complete, per
execution model) instead of D02, which is a per-tool share that would have to
be pooled across tools; T9b shows the 12 hypotheses per block as column
groups (pilot, full_ext; the composite is T9, the blocks are checked to add
up to it); T10 has one row
per (block, endpoint, R04 variant / R05 pair) with main, SA1 and X01 side by
side, R02 main/SA1 on the R04 rows and the frozen Q10 columns on the Q06 R04
rows (the SA1 BASE/FINAL rates are checked, not shown); T12 has one row per
(block, BASE / FINAL[v]) with F01 vs X02 DIRTY and X04; T12b holds X03 (the
DIRTY-only-via-tool shares and the top check ids: one row per tool / check id);
T12c holds X05 (a trajectory metric per block x variant, split off because T12
did not fit a landscape page). Tables keep the population definitions and
metric legends in `definitions` (OrderedDict(ref, text); the LaTeX rendering
cites them by reference) and carry LaTeX rendering hints in `latex`
(LATEX_HINTS).
No number is derived here that the estimates do not carry (the X02
dirty-only share uses the estimate's own count and denominator);
build_tables needs summarize_dataset(dataset) (or the Dataset itself)
because dataset.counts() alone carries no per-block facts (T1 inventory,
owners, and the expected row sets above). Columns carry a `kind` (and
optionally group/sub/digits/mark/width/resolution/display) in addition to
the spec's key/header/align because the renderers need it. F05 cells show
the findings count with the artifact share "(n/N applicable artifacts)"
(the F05 artifacts_with_finding estimate).
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import OrderedDict

from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.study_analysis import core, stats

ANY = "*"                                  # population wildcard (no real population is "*")
CONTRACT_FIELDS = ("post_freeze", "ci_degenerate", "p_resolution", "p_holm_resolution")
ESTIMATE_FIELDS = ("metric_id", "population", "block", "strata", "numerator", "denominator", "value",
                   "ci_low", "ci_high", "ci_method", "replicates", "p_value", "p_holm", "reject_holm",
                   "note") + CONTRACT_FIELDS
CI_METHOD = "cluster_bootstrap_percentile"
TABLE_IDS = ("T1_inventory", "T1b_provenance", "T2a_initial_quality_composite", "T2b_initial_quality_pilot",
             "T2c_initial_quality_full_ext", "T2d_initial_heldout_composite", "T2e_initial_heldout_pilot",
             "T2f_initial_heldout_full_ext", "T3_tool_coverage", "T4_findings", "T4b_tool_agreement",
             "T5_repair_by_model", "T5b_repair_by_model_heldout", "T6_stops_effort", "T6b_effort",
             "T7a_heldout_rates", "T7b_heldout_transitions", "T7c_joint_transitions", "T8_execution_models",
             "T9_primary_tests", "T9b_primary_by_block", "T10_sensitivity", "T11_runtime", "T12_addendum",
             "T12b_dirty_checks", "T12c_iterations_to_clean")
ENDPOINTS = ("Q06", "E02")                 # endpoint strata values of R01..R05 (metric ids)
SENSITIVITY_KEY, SA1 = "sensitivity", "SA1"
MARGINAL_KEYS = ("step", "final_iteration", "iteration")
QUANTITY_KEY = "quantity"                  # sub-quantity stratum of C01/C02/C05/F05/X03 (metrics.py)
C02_TOKEN_KEY, C02_OUTPUT = QUANTITY_KEY, ("output_tokens",)
F05_FINDINGS, F05_ARTIFACTS = "findings", "artifacts_with_finding"
C04_ALL, C04_EXCL = "all", "excluding_above_threshold"
X03_DIRTY_ONLY, X03_FINDINGS, X03_ARTIFACTS = "dirty_only_via_tool", "blocking_findings", "artifacts_with_check"
X02_ONLY = "dirty_only_under_frozen_rule"
X04_STATES = core.THREE_STATE[1:]          # contract X04: CLEAN_COMPLETE, NO_FINDING_INCOMPLETE
EFFORT_METRICS = ("C01", "C02", "C03", "C05")
EFFORT_DIGITS = OrderedDict([("C01", 2), ("C02", 0), ("C03", 1), ("C05", 3)])
# (metric, population) of the effort estimates -> the dataset units every (block, variant) cell rests on
# (metrics.py: C01/C05 over the trajectories of a variant, C02/C03 over its repair candidates, C02 BASE
# over the base generations of a block); a (block, variant) with such units must carry the estimate
EFFORT_GRID = OrderedDict([(("C01", "REPAIR_CANDIDATES"), "trajectories_by_variant"),
                           (("C02", "BASE"), "base_cells"),
                           (("C02", "REPAIR_CANDIDATES"), "candidates_by_variant"),
                           (("C03", "REPAIR_CANDIDATES"), "candidates_by_variant"),
                           (("C05", "FINAL"), "trajectories_by_variant")])
POPULATION_ABBREVIATIONS = OrderedDict([("REPAIR_CANDIDATES", "REPAIR_CAND.")])   # T6b (cell width)
# LaTeX rendering hints of a table (key `latex`; measured with pdflatex on the real study size, see latex.py):
# size = body font, longtable = break over pages although short (its notes then flow after it)
LATEX_HINTS = OrderedDict([("T7c_joint_transitions", (("size", "scriptsize"),)),
                           ("T12_addendum", (("longtable", True),))])
LONGTABLE_ROWS = 40
PILOT_BLOCK = core.BLOCKS[0]               # "pilot" - the block whose numbers carry the pilot label
PILOT_MARK, NOT_STRATIFIED_MARK, OMITTED_MARK, UNDEFINED_MARK, COHORT_MARK = "a", "b", "c", "d", "e"
DAGGER = "†"                          # degenerate (zero-width) interval mark; LaTeX \dag
NOT_STRATIFIED_TEXT = ("--: not estimated at this stratification (the producer computes F01/F02 per model "
                       "and per execution model, not per model x execution model)")
EXPLORATORY = "EXPLORATORY"                # metrics.py label of a run with non-methodology replicate counts
# units an exclusion rule removes from a denominator (methodology missingness / applicability: "excluded and
# reported", "counted separately"); metrics.py records the count in the estimate key `excluded`
_BI = "baseline_incompatible artifact(s)"
_PAIRED = "base cell(s) outside the paired cohort"
EXCLUSION_REASONS = OrderedDict([
    ("Q04", "unassembled artifact(s) (Q04 counts over assembled artifacts)"), ("Q06", _BI), ("Q07", _BI),
    ("Q09", _BI), ("Q10", _BI), ("E02", "artifact(s) without a valid pair (counted separately)"),
    ("R01", _PAIRED), ("R02", _PAIRED), ("R03", _PAIRED), ("R04", _PAIRED), ("R05", _PAIRED),
    ("G01", "improved cell(s) without a valid pair"),
    ("X01", "base cell(s) removed by the auto-closed rule or outside the endpoint's paired cohort")])
SUMMARY_KEYS = ("models", "benchmarks", "families", "base_cells", "bl01_cells", "candidates", "artifacts",
                "trajectories", "terminal", "enhanced_pairs", "enhanced_valid", "enhanced_gated", "gated_groups",
                "generations", "owners", "supplemented", "model_ids", "execution_models",
                "trajectories_by_variant", "candidates_by_variant", "ran_entries", "tools")
STAGES = OrderedDict([("static", core.STATIC_TOOLS), ("dynamic", core.DYNAMIC_TOOLS)])
# addendum table notes: these three are placed by rule (their applies_to is prose); every other note must name
# its tables / figures in applies_to
REQUIRED_NOTES = ("BL01", "REASONING", "EFFECTIVE_STATES", "DEGENERATE_CI")
RULE_NOTES = ("BL01", "REASONING", "DEGENERATE_CI")
BL01_ENDPOINTS = ("Q06", "E01", "E02")     # aggregates of these verdicts include the BL-01 benchmark (pilot)
# the endpoints / metrics a metric's value rests on (methodology and addendum definitions), so that a table
# showing e.g. G01 carries the Q06 / E02 disclosures: Q07-Q10 are Q06 verdict aggregates, E05 / G01 condition E02 on
# Q06, C05 counts R02 Q06 improvements, X01 is R04/R05 on a sub-cohort, X02/X03 re-read F01, X04 conditions F01
# on Q06, X06 joins the Q06 and E02 transitions (R01 labels; not the F01 / F02 transitions of R01)
IMPLIED_REFS = OrderedDict([("Q07", ("Q06",)), ("Q08", ("Q06",)), ("Q09", ("Q06",)), ("Q10", ("Q06",)),
                            ("E05", ("Q06", "E02")),
                            ("G01", ("Q06", "E02", "E05")), ("C05", ("Q06", "R02")), ("X01", ("R04", "R05")),
                            ("X02", ("F01",)), ("X03", ("F01",)), ("X04", ("Q06", "F01")),
                            ("X06", ("Q06", "E02"))])
_TARGET = re.compile(r"\b([TF]\d+[a-z]?_[A-Za-z0-9_]+)")
# spec table ids the outputs split (module docstring): an addendum applies_to naming one covers its parts; every
# other id must be an exact table / figure id (a typo never attaches a note to a whole number family)
SPLIT_IDS = OrderedDict([
    ("T2_initial_quality", ("T2a_initial_quality_composite", "T2b_initial_quality_pilot",
                            "T2c_initial_quality_full_ext", "T2d_initial_heldout_composite",
                            "T2e_initial_heldout_pilot", "T2f_initial_heldout_full_ext")),
    ("T7_heldout", ("T7a_heldout_rates", "T7b_heldout_transitions", "T7c_joint_transitions"))])


def refuse(message):
    raise core.AnalysisRefused(message)


# -- estimate index ------------------------------------------------------------------------------

def _strata_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) or isinstance(value, str):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    refuse("unsupported strata value %r" % (value,))


def strata_key(strata):
    if strata is None:
        strata = {}
    if not isinstance(strata, dict):
        refuse("strata must be a mapping, got %r" % (strata,))
    items = []
    for key, value in strata.items():
        if not isinstance(key, str) or not key:
            refuse("strata keys must be non-empty strings: %r" % (key,))
        items.append((key, _strata_value(value)))
    return tuple(sorted(items))


def _strata_text(skey):
    return ", ".join("%s=%s" % item for item in skey) or "{}"


def _check_contract(est, post_freeze_ids):
    """The DESIGN2 section-1 keys: post_freeze exactly for the addendum
    metrics, ci_degenerate None without an interval and ci_low == ci_high
    otherwise, resolutions only in the primary family (checked there)."""
    metric = est["metric_id"]
    flag = est["post_freeze"]
    if not isinstance(flag, bool) or flag != (metric in post_freeze_ids):
        refuse("%s: post_freeze %r (post-freeze is true exactly for the addendum metrics %s)" % (
            _label(est), flag, ", ".join(sorted(post_freeze_ids))))
    low, high, degenerate = est["ci_low"], est["ci_high"], est["ci_degenerate"]
    if low is None and high is None:
        if degenerate is not None:
            refuse("%s: ci_degenerate %r without an interval" % (_label(est), degenerate))
    elif low is None or high is None:
        refuse("%s: a half-open interval [%r, %r]" % (_label(est), low, high))
    elif not isinstance(degenerate, bool) or degenerate != (low == high):
        refuse("%s: ci_degenerate %r contradicts the interval [%r, %r]" % (_label(est), degenerate, low, high))
    if est["p_holm"] is None and (est["p_resolution"] is not None or est["p_holm_resolution"] is not None):
        refuse("%s: a p resolution outside the primary family" % _label(est))


class EstimateIndex:
    """Exact index over the estimates: (metric, population, block, strata).
    Unknown metric ids / blocks / CI methods, duplicates and estimates
    violating the contract keys refuse, so a table can never silently pick
    one of two contradicting numbers."""

    def __init__(self, estimates, methodology, addendum):
        known = set(core.all_metric_ids(methodology, addendum))
        post_freeze_ids = set(core.addendum_metric_ids(addendum))
        self.blocks = tuple(methodology["strata"]["block"])
        self.exact = {}
        self.loose = {}
        self.scan_index = {}
        for est in estimates:
            if not isinstance(est, dict):
                refuse("an estimate is not a mapping: %r" % (est,))
            missing = [f for f in ESTIMATE_FIELDS if f not in est]
            if missing:
                refuse("estimate %r lacks %s" % (est.get("metric_id"), missing))
            metric, population, block = est["metric_id"], est["population"], est["block"]
            if metric not in known:
                refuse("foreign metric id %r (not in the methodology or its addendum)" % (metric,))
            if block not in self.blocks:
                refuse("foreign block %r in %s" % (block, metric))
            if not isinstance(population, str) or not population or population == ANY:
                refuse("bad population %r in %s" % (population, metric))
            if est["ci_method"] not in (None, CI_METHOD):
                refuse("foreign ci_method %r in %s" % (est["ci_method"], metric))
            skey = strata_key(est["strata"])
            key = (metric, population, block, skey)
            if key in self.exact:
                refuse("duplicate estimate %s %s %s {%s}" % (metric, population, block, _strata_text(skey)))
            _check_contract(est, post_freeze_ids)
            self.exact[key] = est
            self.loose.setdefault((metric, block, skey), []).append(est)
            self.scan_index.setdefault((metric, block), []).append((population, skey, est))
        for entries in self.scan_index.values():
            entries.sort(key=lambda item: (item[0], item[1]))

    def scan(self, metric, block, population=ANY):
        for population_, skey, est in self.scan_index.get((metric, block), ()):
            if population == ANY or population == population_:
                yield population_, skey, est

    def get(self, metric, block, strata=None, population=ANY, required=True):
        skey = strata_key(strata)
        if population == ANY:
            found = self.loose.get((metric, block, skey), [])
            if len(found) > 1:
                refuse("ambiguous estimate %s %s {%s}: populations %s" % (
                    metric, block, _strata_text(skey), sorted(e["population"] for e in found)))
            est = found[0] if found else None
        else:
            est = self.exact.get((metric, population, block, skey))
        if est is None and required:
            near = ["%s {%s}" % (p, _strata_text(s)) for p, s, _ in self.scan(metric, block)][:8]
            refuse("missing estimate %s %s %s {%s}; available: %s" % (
                metric, "any population" if population == ANY else population, block,
                _strata_text(skey), near or "none"))
        return est

    def values(self, metric, block, key, base=None, population=ANY):
        """Distinct values of strata `key` among estimates whose strata are
        exactly base + {key}."""
        base_items = set(strata_key(base))
        want = set(k for k, _ in base_items) | {key}
        out = set()
        for _, skey, _est in self.scan(metric, block, population):
            if set(k for k, _ in skey) == want and base_items <= set(skey):
                out.add(dict(skey)[key])
        return out


def ordered(values, preferred):
    values = set(values)
    preferred = [str(p) for p in preferred]
    return [p for p in preferred if p in values] + sorted(values - set(preferred))


def source_of(est):
    """The estimate's identity (strata values keep their estimate types)."""
    strata = est["strata"] or {}
    return OrderedDict([("metric_id", est["metric_id"]), ("population", est["population"]),
                        ("block", est["block"]), ("strata", OrderedDict((k, strata[k]) for k in sorted(strata)))])


def _label(est):
    return "%s %s %s {%s}" % (est.get("metric_id"), est.get("population"), est.get("block"),
                              _strata_text(strata_key(est.get("strata"))))


def excluded_count(est):
    """The units an exclusion rule removed from the estimate's denominator.
    Metrics whose methodology rule reports exclusions must carry the count
    (the G01 difference-to-reference estimate is not a share and has none)."""
    rule = est["metric_id"] in EXCLUSION_REASONS and not (
        est["metric_id"] == "G01" and "comparison" in (est["strata"] or {}))
    value = est.get("excluded")
    if value is None:
        if rule:
            refuse("%s lacks its excluded count (methodology: %s are excluded and reported)" % (
                _label(est), EXCLUSION_REASONS[est["metric_id"]]))
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        refuse("%s: excluded count %r is not a count" % (_label(est), value))
    return value


def cell(est):
    """The raw cell of one estimate (facts unrounded, metadata carried)."""
    if est is None:
        return None
    out = OrderedDict((k, est[k]) for k in ("numerator", "denominator", "value", "ci_low", "ci_high"))
    out["ci_method"] = est["ci_method"]
    out["replicates"] = est["replicates"]
    out["primary"] = est["p_holm"] is not None
    out["excluded"] = excluded_count(est)
    out["ci_degenerate"] = est["ci_degenerate"]
    out["post_freeze"] = est["post_freeze"]
    out["note"] = est["note"]
    out["source"] = source_of(est)
    return out


def _plain_cell(numerator, denominator, note, post_freeze=False):
    """A cell the tables derive from estimates (a zero category of a complete
    distribution, a sum over a marginal stratum): no interval, no source."""
    return OrderedDict([("numerator", numerator), ("denominator", denominator),
                        ("value", (float(numerator) / denominator) if denominator else None),
                        ("ci_low", None), ("ci_high", None), ("ci_method", None), ("replicates", None),
                        ("primary", False), ("excluded", None), ("ci_degenerate", None),
                        ("post_freeze", post_freeze), ("note", note), ("source", None)])


def _zero_cell(denominator, post_freeze=False):
    return _plain_cell(0, denominator, "category without an estimate in a complete distribution (0)", post_freeze)


def _units(c):
    return c["denominator"] + (c.get("excluded") or 0)


def same_cohort(base, other, what):
    """Identical-cohort rule (methodology populations.rules): BASE, STEP[v][k],
    FINAL[v] and the paired cells of one stratum rest on the same units; a
    denominator may differ only by the estimate's own excluded count."""
    if base is None or other is None or base["denominator"] is None or other["denominator"] is None:
        refuse("%s: a cohort cell without its denominator" % what)
    if _units(base) != _units(other):
        refuse("%s: not the identical cohort (%s + %s excluded vs %s + %s excluded units)" % (
            what, base["denominator"], base.get("excluded") or 0, other["denominator"], other.get("excluded") or 0))


def _replicate_counts(values):
    return " / ".join(format(v, ",") for v in sorted(values))


_SKIPPED = re.compile(r"\b(\d+) of (\d+) bootstrap replicates skipped\b")


def drawn_replicates(c, where):
    """(drawn, used) bootstrap replicates of an estimate / cell. `replicates`
    is the number of USABLE replicates (stats.py: resamples with a zero
    denominator are skipped and the note says 'k of B bootstrap replicates
    skipped'), so the drawn count B = used + skipped; a note contradicting the
    used count refuses."""
    used = c.get("replicates")
    if isinstance(used, bool) or not isinstance(used, int) or used < 1:
        refuse("%s: an interval without its bootstrap replicate count (%r)" % (where, used))
    found = _SKIPPED.findall(c.get("note") or "")
    if not found:
        return used, used
    if len(found) != 1:
        refuse("%s: more than one skipped-replicate statement in the note" % where)
    skipped, drawn = int(found[0][0]), int(found[0][1])
    if drawn - skipped != used:
        refuse("%s: %d usable replicates contradict the note (%d of %d skipped)" % (where, used, skipped, drawn))
    return drawn, used


def interval_audit(cells, methodology, where):
    """The facts behind the intervals a table / figure SHOWS (cells as made
    by cell()): every shown interval carries ci_method and its replicate
    count, and the count is the methodology's (primary family: the primary
    count, everything else: the descriptive count). A different count is only
    accepted for an estimate the producer labelled EXPLORATORY."""
    boot = methodology["statistics"]["bootstrap"]
    expected = {True: int(boot["replicates_primary"]), False: int(boot["replicates_descriptive"])}
    audit = OrderedDict([("descriptive", set()), ("primary", set()), ("primary_sources", set()),
                         ("exploratory", False), ("shown", 0), ("skipped", 0), ("min_used", None),
                         ("zero_width", 0)])
    for c in cells:
        if c is None:
            continue
        low, high = c.get("ci_low"), c.get("ci_high")
        if low is None and high is None:
            continue
        if low is None or high is None:
            refuse("%s: a half-open interval [%r, %r]" % (where, low, high))
        if c.get("ci_method") != CI_METHOD:
            refuse("%s: an interval with ci_method %r" % (where, c.get("ci_method")))
        drawn, used = drawn_replicates(c, where)
        primary = bool(c.get("primary"))
        if drawn != expected[primary]:
            if EXPLORATORY not in (c.get("note") or ""):
                refuse("%s: a %s interval with %d replicates, the methodology fixes %d (and the estimate is "
                       "not labelled %s)" % (where, "primary-family" if primary else "descriptive", drawn,
                                             expected[primary], EXPLORATORY))
            audit["exploratory"] = True
        if used < drawn:
            audit["skipped"] += 1
            audit["min_used"] = used if audit["min_used"] is None else min(audit["min_used"], used)
        if c.get("ci_degenerate"):
            audit["zero_width"] += 1
        audit["primary" if primary else "descriptive"].add(drawn)
        if primary:
            source = c.get("source") or {}
            audit["primary_sources"].add("%s %s with strata %s" % (
                source.get("metric_id"), source.get("block"), "+".join(sorted(source.get("strata") or {}))))
        audit["shown"] += 1
    return audit


def ci_note_text(methodology, audit, tests=False):
    """The CI statement of the shown intervals (from interval_audit)."""
    boot = methodology["statistics"]["bootstrap"]
    level = int(round(float(boot["confidence_level"]) * 100))
    parts = ["%d%% CI: %s, stratified by %s; seed %s; cluster = benchmark" % (
        level, boot["method"], boot["stratified_by"], boot["seed"])]
    if audit["descriptive"]:
        parts.append("%s replicates (descriptive, unadjusted)" % _replicate_counts(audit["descriptive"]))
    if audit["primary"]:
        parts.append("%s replicates for the primary-family estimates (%s; Holm-adjusted tests in T9)" % (
            _replicate_counts(audit["primary"]), ", ".join(sorted(audit["primary_sources"]))))
    if audit["skipped"]:
        parts.append("%d interval(s) rest on fewer usable replicates (resamples with a zero denominator skipped "
                     "and counted in the estimate note; at least %s used)" % (
                         audit["skipped"], format(audit["min_used"], ",")))
    if audit["zero_width"]:
        parts.append("%d interval(s) of zero width marked %s" % (audit["zero_width"], DAGGER))
    if not audit["shown"]:
        parts.append("no interval is estimable for the cells shown")
    if audit["exploratory"]:
        parts.append("%s: replicate counts other than the methodology's (%s primary, %s descriptive); not "
                     "confirmatory" % (EXPLORATORY, format(int(boot["replicates_primary"]), ","),
                                       format(int(boot["replicates_descriptive"]), ",")))
    if tests:
        parts += ["p-values: " + methodology["statistics"]["tests"]["p_values"],
                  methodology["statistics"]["tests"]["multiplicity"]]
    return "; ".join(parts)


def is_exploratory(cells):
    return any(EXPLORATORY in (c.get("note") or "") for c in cells if isinstance(c, dict))


def _merged(strata, **extra):
    merged = OrderedDict(strata or {})
    merged.update(extra)
    return merged


def _summed_cells(ix, metric, block, base, key, population):
    """category -> cell summed over one marginal stratum (R06 x final iteration)."""
    base_items = set(strata_key(base))
    for marginal in MARGINAL_KEYS:
        want = set(k for k, _ in base_items) | {key, marginal}
        groups = OrderedDict()
        for _, skey, est in ix.scan(metric, block, population):
            if set(k for k, _ in skey) == want and base_items <= set(skey):
                groups.setdefault(dict(skey)[key], []).append(est)
        if groups:
            cells = OrderedDict()
            for category, ests in groups.items():
                dens = set(e["denominator"] for e in ests)
                if len(dens) != 1:
                    refuse("%s %s: denominators differ across %s" % (metric, block, marginal))
                den = dens.pop()
                num = sum(e["numerator"] for e in ests)
                cells[category] = _plain_cell(num, den, "%s summed over %s" % (metric, marginal))
            return cells
    return OrderedDict()


def distribution(ix, metric, block, base, key, categories, population=ANY, required=True, marginal=False):
    """OrderedDict(category -> cell) of a counts-and-shares metric. Categories
    without an estimate are zero only if the present ones sum to the common
    denominator (completeness is proven, never assumed)."""
    categories = [str(c) for c in categories]
    present = ix.values(metric, block, key, base, population)
    cells = OrderedDict((c, cell(ix.get(metric, block, _merged(base, **{key: c}), population)))
                        for c in sorted(present))
    if not cells and marginal:
        cells = _summed_cells(ix, metric, block, base, key, population)
    if not cells:
        if required:
            refuse("no %s estimates %s %s {%s} by %s" % (metric, block, population, _strata_text(
                strata_key(base)), key))
        return None
    unknown = sorted(set(cells) - set(categories))
    if unknown:
        refuse("%s %s: foreign %s values %s" % (metric, block, key, unknown))
    dens = set(c["denominator"] for c in cells.values())
    if len(dens) != 1:
        refuse("%s %s {%s}: the %s shares have different denominators %s" % (
            metric, block, _strata_text(strata_key(base)), key, sorted(dens)))
    den = dens.pop()
    total = sum(c["numerator"] for c in cells.values())
    if total != den:                        # every distribution used here is a partition of its denominator
        refuse("%s %s {%s}: incomplete %s distribution (%s of %s)" % (
            metric, block, _strata_text(strata_key(base)), key, total, den))
    post = any(c["post_freeze"] for c in cells.values())
    return OrderedDict((c, cells.get(c) or _zero_cell(den, post)) for c in categories)


def _same_counts(a, b, what):
    if (a["numerator"], a["denominator"]) != (b["numerator"], b["denominator"]):
        refuse("contradictory estimates: %s (%s/%s vs %s/%s)" % (
            what, a["numerator"], a["denominator"], b["numerator"], b["denominator"]))


def _int_extra(est, key):
    value = est.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        refuse("%s lacks its count %s (%r)" % (_label(est), key, value))
    return value


# -- addendum disclosures -----------------------------------------------------------------------------

def refs_of(source):
    """The metric ids / endpoints an estimate's value rests on."""
    strata = source.get("strata") or {}
    refs = {source["metric_id"]} | set(IMPLIED_REFS.get(source["metric_id"], ()))
    if "endpoint" in strata:
        refs.add(str(strata["endpoint"]))
    return refs


def variants_of(source, variants):
    """The variants an estimate's value is about: its strata variant and the
    variants a comparison label names ('v1-v2'; a name counts only as a whole
    token, so one variant name inside another never matches)."""
    strata = source.get("strata") or {}
    out = set()
    if "variant" in strata and str(strata["variant"]) in variants:
        out.add(str(strata["variant"]))
    if strata.get("comparison") is not None:
        label = str(strata["comparison"])
        out |= set(v for v in variants
                   if re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(v), label))
    return out


def checked_addendum(addendum, methodology):
    """The addendum the tables / figures render. None -> core.load_addendum
    (bound to the methodology there); an explicitly passed addendum must pass
    the same identity checks (schema, status, binding to THIS methodology by
    its canonical sha256, unique metric ids not colliding with the frozen
    ones), so a draft or an addendum of another methodology is never rendered
    under the addendum_1 label."""
    if addendum is None:
        return core.load_addendum(methodology=methodology)
    if not isinstance(addendum, dict):
        refuse("the addendum is not a mapping")
    if addendum.get("schema_version") != core.ADDENDUM_SCHEMA or addendum.get("status") != core.ADDENDUM_STATUS:
        refuse("not a %s addendum with status %s (got %r / %r)" % (
            core.ADDENDUM_SCHEMA, core.ADDENDUM_STATUS, addendum.get("schema_version"), addendum.get("status")))
    amends = addendum.get("amends")
    if not isinstance(amends, dict) or amends.get("methodology_canonical_sha256") != canonical_sha256(methodology):
        refuse("the addendum amends another methodology than the one in use (canonical sha256)")
    ids = [m.get("id") if isinstance(m, dict) else None for m in addendum.get("metrics") or []]
    if len(ids) != len(set(ids)) or None in ids or set(ids) & set(core.metric_ids(methodology)):
        refuse("addendum metric ids are not unique or collide with frozen ids")
    return addendum


def post_freeze_prefix(addendum):
    """'POST-FREEZE (addendum_1, descriptive): ' (the suffix of addendum_id)."""
    return "POST-FREEZE (%s, descriptive): " % str(addendum["addendum_id"]).rsplit(".", 1)[-1]


class Disclosure:
    """The addendum's table notes and interpretive caveats and where they
    apply (module docstring). `targets` = every table and figure id, so that
    an applies_to id is resolved (exact ids; a SPLIT_IDS id covers its parts)
    and any other id refuses."""

    def __init__(self, addendum, methodology, targets):
        self.addendum = addendum
        self.targets = tuple(targets)
        self.notes = OrderedDict()
        for note in addendum.get("table_notes") or []:
            nid, text = note.get("id"), note.get("text")
            if not nid or not isinstance(text, str) or not text.strip() or nid in self.notes:
                refuse("addendum table note %r without id / text or duplicated" % (nid,))
            self.notes[nid] = note
        missing = [n for n in REQUIRED_NOTES if n not in self.notes]
        if missing:
            refuse("the addendum lacks the table note(s) %s" % missing)
        self.note_targets = OrderedDict()
        for nid, note in self.notes.items():
            ids = _TARGET.findall(note.get("applies_to") or "")
            if ids:
                self.note_targets[nid] = set(t for i in ids for t in self.resolve(i))
            elif nid not in RULE_NOTES:
                refuse("addendum table note %s: applies_to %r names no table / figure and no known rule" % (
                    nid, note.get("applies_to")))
        self.metric_ids = core.all_metric_ids(methodology, addendum)
        self.variants = tuple(methodology["strata"]["variant"])
        metric_set = set(self.metric_ids)
        self.caveats = []
        for caveat in addendum.get("interpretive_caveats") or []:
            cid, text = caveat.get("id"), caveat.get("text")
            if not cid or not isinstance(text, str) or not text.strip():
                refuse("addendum caveat %r without id / text" % (cid,))
            targets_, split, metrics_, subjects = set(), set(), set(), set()
            for token in caveat.get("applies_to") or []:
                if re.match(r"^[TF]\d+[a-z]?_", str(token)):
                    (targets_ if token in self.targets else split).update(self.resolve(token))
                elif token in metric_set:
                    metrics_.add(token)
                elif token in self.variants:
                    subjects.add(token)            # the variant's results: every shown estimate of that variant
                else:
                    refuse("addendum caveat %s: unknown applies_to %r" % (cid, token))
            # an id the outputs split (T7_heldout) covers its parts; when the caveat also names metrics or
            # variants, only the parts showing them carry it (they already do through those tokens)
            if not metrics_ and not subjects:
                targets_ |= split
            self.caveats.append((cid, text, targets_, metrics_, subjects))
        self.post_freeze_ids = core.addendum_metric_ids(addendum)
        self.addendum_metrics = OrderedDict((m["id"], m) for m in addendum["metrics"])

    def resolve(self, token):
        """An exact table / figure id, or the parts of a SPLIT_IDS id; any
        other id refuses (a typo must never attach a note silently)."""
        if token in self.targets:
            return [token]
        parts = SPLIT_IDS.get(token)
        if parts is None:
            refuse("the addendum names an unknown table / figure %r (exact ids only; split ids: %s)" % (
                token, ", ".join(SPLIT_IDS)))
        missing = [p for p in parts if p not in self.targets]
        if missing:
            refuse("split id %r: parts %s are not table / figure ids" % (token, missing))
        return list(parts)

    def text(self, note_id):
        return self.notes[note_id]["text"]

    def apply(self, target_id, sources):
        """[(id, text)] of the table notes and caveats that apply to a table /
        figure showing these estimate sources (DEGENERATE_CI is the dagger
        footnote, placed by the caller)."""
        refs, subjects, bl01, per_model = set(), set(), False, False
        for source in sources:
            these = refs_of(source)
            refs |= these
            subjects |= variants_of(source, self.variants)
            if source["block"] in (PILOT_BLOCK, core.COMPOSITE) and these & set(BL01_ENDPOINTS):
                bl01 = True
            if "model_id" in (source.get("strata") or {}):
                per_model = True
        out = []
        for nid, note in self.notes.items():
            if nid in self.note_targets:
                hit = target_id in self.note_targets[nid]
            else:
                hit = {"BL01": bl01, "REASONING": per_model}.get(nid, False)
            if hit:
                out.append((nid, note["text"]))
        for cid, text, targets_, metrics_, variants_ in self.caveats:
            if target_id in targets_ or refs & metrics_ or subjects & variants_:
                out.append((cid, text))
        return out

    def post_freeze_note(self, ids):
        a = self.addendum
        return ("POST-FREEZE (%s, %s, declared %s; descriptive, not part of the frozen methodology): %s" % (
            a["addendum_id"], a["status"], a.get("declared_on"), "; ".join(
                "%s %s - %s" % (m, self.addendum_metrics[m]["name"], self.addendum_metrics[m]["limits"])
                for m in ids)))


# -- dataset inventory -----------------------------------------------------------------------------

def _flag(value):
    """A boolean dataset field (in memory bool; 0/1 or "0"/"1" from CSV)."""
    if isinstance(value, bool):
        return value
    if value in (0, 1, "0", "1"):
        return str(value) == "1"
    refuse("not a boolean dataset value: %r" % (value,))


def _supplements(value):
    if value is None or value == "":
        return OrderedDict()
    if isinstance(value, str):
        value = json.loads(value, object_pairs_hook=OrderedDict)
    if not isinstance(value, dict):
        refuse("static_supplemented_by is not a mapping: %r" % (value,))
    return value


def summarize_dataset(dataset):
    """Per-block facts of a core.Dataset (single pass per table; composite =
    all rows, distinct counts as unions): the T1 inventory and the expected
    row sets of the other tables (model ids, execution models, trajectories
    and repair candidates per variant, ran tool entries per tool x execution
    model, the tools of the tool entries per stage)."""
    if not isinstance(dataset, core.Dataset):
        refuse("summarize_dataset needs a core.Dataset")
    scopes = core.BLOCKS + (core.COMPOSITE,)
    sets = OrderedDict((s, OrderedDict((k, set()) for k in ("models", "benchmarks", "families",
                                                             "execution_models"))) for s in scopes)
    facts = OrderedDict()
    for s in scopes:
        facts[s] = OrderedDict([
            ("base_cells", 0), ("bl01_cells", 0), ("candidates", OrderedDict()), ("artifacts", 0),
            ("trajectories", 0), ("terminal", OrderedDict()), ("enhanced_pairs", 0), ("enhanced_valid", 0),
            ("enhanced_gated", 0), ("enhanced_pair_rows", 0), ("gated_groups", 0), ("generations", OrderedDict()),
            ("owners", OrderedDict((stage, OrderedDict()) for stage in
                                   ("correctness", "static", "dynamic", "enhanced"))),
            ("supplemented", OrderedDict()), ("trajectories_by_variant", OrderedDict()),
            ("candidates_by_variant", OrderedDict()), ("ran_entries", OrderedDict()),
            ("tools", OrderedDict((stage, set()) for stage in STAGES))])

    def scopes_of(block):
        if block not in core.BLOCKS:
            refuse("foreign block %r in the dataset" % (block,))
        return (block, core.COMPOSITE)

    def bump(mapping, key, n=1):
        mapping[key] = mapping.get(key, 0) + n

    for row in dataset.rows("base_cells"):
        for s in scopes_of(row["block"]):
            sets[s]["models"].add(row["model_id"])
            sets[s]["benchmarks"].add(row["benchmark"])
            sets[s]["families"].add(row["family"])
            sets[s]["execution_models"].add(row["execution_model"])
            facts[s]["base_cells"] += 1
            facts[s]["bl01_cells"] += 1 if _flag(row["bl01"]) else 0
    where = {}
    for row in dataset.rows("artifacts"):
        where[row["artifact_id"]] = (row["block"], row["benchmark"], row["execution_model"])
        for s in scopes_of(row["block"]):
            f = facts[s]
            f["artifacts"] += 1
            if int(row["iteration"]) >= 1:
                bump(f["candidates"], str(int(row["iteration"])))
                bump(f["candidates_by_variant"], row["variant"])
            for stage in ("correctness", "static", "dynamic", "enhanced"):
                bump(f["owners"][stage], row["%s_owner" % stage])
            for _tool, owner in _supplements(row["static_supplemented_by"]).items():
                bump(f["supplemented"], owner)
            f["enhanced_pairs"] += int(row["enh_pairs"])
            f["enhanced_valid"] += int(row["enh_valid"])
            f["enhanced_gated"] += int(row["enh_gated"])
    for row in dataset.rows("trajectories"):
        for s in scopes_of(row["block"]):
            facts[s]["trajectories"] += 1
            bump(facts[s]["terminal"], row["terminal_status"])
            bump(facts[s]["trajectories_by_variant"], row["variant"])
    for row in dataset.rows("tool_entries"):
        if row["artifact_id"] not in where:
            refuse("tool entry of an unknown artifact %r" % (row["artifact_id"],))
        if row["stage"] not in STAGES:
            refuse("tool entry with a foreign stage %r" % (row["stage"],))
        block, _benchmark, execution_model = where[row["artifact_id"]]
        for s in scopes_of(block):
            facts[s]["tools"][row["stage"]].add(row["tool"])
            if _flag(row["ran"]):
                bump(facts[s]["ran_entries"].setdefault(row["tool"], OrderedDict()), execution_model)
    for row in dataset.rows("generations"):
        if row["artifact_id"] not in where:
            refuse("generation of an unknown artifact %r" % (row["artifact_id"],))
        for s in scopes_of(where[row["artifact_id"]][0]):
            bump(facts[s]["generations"], row["kind"])
    groups = {}
    for row in dataset.rows("enhanced_pairs"):
        if row["artifact_id"] not in where:
            refuse("enhanced pair of an unknown artifact %r" % (row["artifact_id"],))
        block, benchmark, execution_model = where[row["artifact_id"]]
        group = (block, benchmark, row["spec_key"], execution_model)
        groups[group] = bool(groups.get(group)) or _flag(row["gated"])
        for s in scopes_of(block):
            facts[s]["enhanced_pair_rows"] += 1
    for (block, _b, _s, _e), gated in groups.items():
        if gated:
            for s in scopes_of(block):
                facts[s]["gated_groups"] += 1
    statuses = list(core.TERMINAL_STATUSES)
    tool_order = core.STATIC_TOOLS + core.DYNAMIC_TOOLS
    for s in scopes:
        f = facts[s]
        if f["enhanced_pair_rows"] != f["enhanced_pairs"]:
            refuse("%s: %s enhanced pair rows but the artifacts count %s pairs" % (
                s, f["enhanced_pair_rows"], f["enhanced_pairs"]))
        if f["enhanced_valid"] + f["enhanced_gated"] != f["enhanced_pairs"]:
            refuse("%s: valid + gated pairs != pairs" % s)
        f["candidates"] = OrderedDict((k, f["candidates"][k]) for k in sorted(f["candidates"], key=int))
        f["terminal"] = OrderedDict((k, f["terminal"][k]) for k in ordered(f["terminal"], statuses))
        f["generations"] = OrderedDict((k, f["generations"][k]) for k in sorted(f["generations"]))
        for stage in f["owners"]:
            f["owners"][stage] = OrderedDict(sorted(f["owners"][stage].items()))
        f["supplemented"] = OrderedDict(sorted(f["supplemented"].items()))
        for key in ("trajectories_by_variant", "candidates_by_variant"):
            f[key] = OrderedDict((v, f[key][v]) for v in ordered(f[key], core.VARIANTS))
        f["ran_entries"] = OrderedDict(
            (t, OrderedDict((e, f["ran_entries"][t][e]) for e in ordered(f["ran_entries"][t], core.EXECUTION_MODELS)))
            for t in ordered(f["ran_entries"], tool_order))
        f["tools"] = OrderedDict((stage, ordered(f["tools"][stage], tool_order)) for stage in f["tools"])
        f["model_ids"] = ordered(sets[s]["models"], core.MODELS)
        f["execution_models"] = ordered(sets[s]["execution_models"], core.EXECUTION_MODELS)
        for k in ("models", "benchmarks", "families"):
            f[k] = len(sets[s][k])
        f.move_to_end("families", last=False)
        f.move_to_end("benchmarks", last=False)
        f.move_to_end("models", last=False)
        del f["enhanced_pair_rows"]
    provenance = OrderedDict((k, dataset.provenance[k]) for k in ("targets_sha256", "lineage_sha256",
                                                                   "census_digest") if k in dataset.provenance)
    return OrderedDict([("blocks", facts), ("counts", dataset.counts()), ("provenance", provenance)])


# -- table assembly ----------------------------------------------------------------------------------

def col(key, header, kind, align=None, group=None, sub=None, digits=None, mark=None, width=None, display=None):
    """A column; `width` (e.g. "3.5cm") makes a text column wrap in LaTeX;
    `display` maps raw text values to the shown labels."""
    column = OrderedDict([("key", key), ("header", header),
                          ("align", align or ("l" if kind in ("text", "block", "mapping") else "r")),
                          ("kind", kind)])
    if group is not None:
        column["group"] = group
        column["sub"] = sub if sub is not None else header
    if digits is not None:
        column["digits"] = digits
    if mark is not None:
        column["mark"] = mark
    if width is not None:
        column["width"] = width
    if display is not None:
        column["display"] = OrderedDict(display)
    return column


def rate_cols(key, label, ci=False, mark=None):
    """A rate column (+ its CI column) under one group header."""
    cols = [col(key, "%s %% (n/N)" % label, "rate", group=label, sub="% (n/N)", mark=mark)]
    if ci:
        cols.append(col(key + "_ci", "%s 95%% CI" % label, "ci", group=label, sub="95% CI"))
    return cols


class Definition(str):
    """A population definition or metric legend (methodology / addendum text):
    make_table keeps it in the table's `definitions` (OrderedDict(ref, text)),
    not in its notes, so that the LaTeX rendering can cite it by reference
    (the full text stays in the JSON form)."""

    def __new__(cls, text, ref):
        obj = str.__new__(cls, text)
        obj.ref = ref
        return obj


def make_table(table_id, title, population, unit, columns, rows, notes, ci_note, footnotes, sources=()):
    """`notes`: table notes and Definition items (split here); `sources`:
    estimates a table shows as plain values (no cell), so that the
    disclosures see them (they are dropped by _finish)."""
    headers = [c["header"] for c in columns]
    keys = [c["key"] for c in columns]
    if len(set(headers)) != len(headers) or len(set(keys)) != len(keys):
        refuse("%s: column headers / keys are not unique" % table_id)
    for row in rows:
        if list(row) != keys:
            refuse("%s: row keys %s do not match the columns" % (table_id, list(row)))
    if not population or not unit:
        refuse("%s: population and unit are required" % table_id)
    definitions = [OrderedDict([("ref", n.ref), ("text", str(n))]) for n in notes if isinstance(n, Definition)]
    return OrderedDict([("id", table_id), ("title", title), ("population", population), ("unit", unit),
                        ("notes", [str(n) for n in notes if not isinstance(n, Definition)]),
                        ("definitions", definitions), ("ci_note", ci_note), ("columns", columns), ("rows", rows),
                        ("footnotes", [OrderedDict([("mark", m), ("text", t)]) for m, t in footnotes]),
                        ("latex", OrderedDict(LATEX_HINTS.get(table_id, ()))),
                        ("_sources", [source_of(e) for e in sources])])


class _Ctx:
    """Shared lookups (orders from the methodology, expected row sets from
    the dataset summary - never from whichever estimates happen to exist)."""

    def __init__(self, ix, methodology, summary, addendum, disclosure):
        self.ix = ix
        self.meth = methodology
        self.addendum = addendum
        self.disclosure = disclosure
        self.summary = summary
        self.facts = summary["blocks"]
        self.blocks = list(methodology["strata"]["block"])
        self.variants = list(methodology["strata"]["variant"])
        self.exec_models = list(methodology["strata"]["execution_model"])
        self.steps = [str(s) for s in methodology["strata"]["iteration"]]
        self.metrics = OrderedDict((m["id"], m) for m in list(methodology["metrics"]) + list(addendum["metrics"]))
        self.settings = stats.bootstrap_settings(methodology)
        self.pilot_text = "pilot: %s; %s" % (methodology["reporting"]["pilot_label"],
                                             methodology["statistics"]["small_cluster_warning"])
        self.post_prefix = post_freeze_prefix(addendum)
        for block in self.blocks:
            if block not in self.facts:
                refuse("the dataset summary has no block %r" % block)
            missing = [k for k in SUMMARY_KEYS if k not in self.facts[block]]
            if missing:
                refuse("the dataset summary of %s lacks %s (build it with summarize_dataset(dataset))" % (
                    block, missing))

    def models(self, block, metric="Q06", population="BASE"):
        """The block's models of the dataset; the estimates must carry exactly
        this model set (a model missing from the producer output refuses)."""
        expected = list(self.facts[block]["model_ids"])
        found = self.ix.values(metric, block, "model_id", None, population)
        if found != set(expected):
            refuse("%s %s %s: the per-model estimates cover models %s, the dataset has %s" % (
                metric, population, block, sorted(found), expected))
        return expected

    def exec_of(self, block, metric="Q06", population="BASE"):
        """The block's execution models (dataset, within the methodology
        strata); the estimates must carry exactly this set."""
        data = list(self.facts[block]["execution_models"])
        foreign = [e for e in data if e not in self.exec_models]
        if foreign:
            refuse("%s: execution model(s) %s outside the methodology strata" % (block, foreign))
        expected = [e for e in self.exec_models if e in data]
        found = self.ix.values(metric, block, "execution_model", None, population)
        if found != set(expected):
            refuse("%s %s %s: the per-execution-model estimates cover %s, the dataset has %s" % (
                metric, population, block, sorted(found), expected))
        return expected

    def legend(self, *ids, **options):
        """numerator / denominator / unit of each metric (methodology or
        addendum) as Definition items; meaning=(ids...) adds the metric's
        meaning and makes the legend a printed note (a table that must state
        a metric's meaning, e.g. T6 R09)."""
        meaning = options.get("meaning", ())
        notes = []
        for mid in ids:
            m = self.metrics[mid]
            if mid in meaning:
                notes.append("%s %s: meaning = %s; numerator = %s; denominator = %s; unit = %s." % (
                    mid, m["name"], m["meaning"], m["numerator"], m["denominator"], m["unit"]))
                continue
            notes.append(Definition("%s %s: numerator = %s; denominator = %s; unit = %s." % (
                mid, m["name"], m["numerator"], m["denominator"], m["unit"]), "%s %s" % (mid, m["name"])))
        return notes

    def use(self, name):
        return self.meth["populations"][name]["use"]

    def population(self, *names):
        """Definition AND use of each population (GENERATED /
        REPAIR_CANDIDATES therefore always carry 'diagnostic only'; the
        population field of those tables states the use as well)."""
        pops = self.meth["populations"]
        return [Definition("%s: %s (use: %s)" % (n, pops[n]["definition"], pops[n]["use"]), n) for n in names]

    def pilot_footnotes(self, blocks):
        return [(PILOT_MARK, self.pilot_text)] if PILOT_BLOCK in blocks else []


def _block_col(header="Block"):
    return col("block", header, "block")


CI_KINDS = ("ci", "ci_pp")


def _finish(ctx, table, tests=False):
    """Statements derived from the cells a table SHOWS: the CI note (method
    and the replicate counts actually carried), the dagger footnote of
    zero-width intervals, the EXPLORATORY label, the denominator exclusions
    (methodology: excluded units are reported), the POST-FREEZE note and the
    addendum disclosures."""
    columns = table["columns"]
    shown = [(c, row[c["key"]]) for row in table["rows"] for c in columns
             if isinstance(row[c["key"]], dict) and "source" in row[c["key"]]]
    sources = [v["source"] for _c, v in shown if v.get("source")] + table.pop("_sources")
    ci_cells = [v for c, v in shown if c["kind"] in CI_KINDS]
    if any(c["kind"] in CI_KINDS for c in columns):
        audit = interval_audit(ci_cells, ctx.meth, table["id"])
        table["ci_note"] = ci_note_text(ctx.meth, audit, tests)
    elif table["ci_note"] is not None:
        refuse("%s: a CI note without an interval column" % table["id"])
    if any(v.get("ci_degenerate") for v in ci_cells):
        table["footnotes"].append(OrderedDict([("mark", DAGGER), ("text", ctx.disclosure.text("DEGENERATE_CI"))]))
    if is_exploratory([v for _, v in shown]):
        table["title"] = "%s (not confirmatory): %s" % (EXPLORATORY, table["title"])
        table["notes"].append("%s: estimates of this table carry the producer's %s label (bootstrap replicate "
                              "counts other than the methodology's); not confirmatory." % (EXPLORATORY,
                                                                                           EXPLORATORY))
    rules = OrderedDict()
    for c, v in shown:
        if c["kind"] in RATIO_KINDS and v.get("excluded") is not None:
            metric = v["source"]["metric_id"]
            rules[metric] = rules.get(metric, False) or v["excluded"] > 0
    if rules:
        parts = []
        nonzero = [m for m in rules if rules[m]]
        zero = [m for m in rules if not rules[m]]
        if nonzero:
            parts.append("a cell marked 'k excl.' excludes k units (%s); cells without the mark exclude none" % (
                "; ".join("%s: %s" % (m, EXCLUSION_REASONS.get(m, "excluded units")) for m in nonzero)))
        if zero:
            parts.append("no unit is excluded in this table by %s" % "; ".join(
                "%s (%s)" % (m, EXCLUSION_REASONS.get(m, "excluded units")) for m in zero))
        table["notes"].append("Denominator exclusions (methodology missingness rules; JSON key excluded): "
                              + "; ".join(parts) + ".")
    post = [m for m in ctx.disclosure.post_freeze_ids if any(s["metric_id"] == m for s in sources)]
    if post:
        table["notes"].append(ctx.disclosure.post_freeze_note(post))
    for nid, text in ctx.disclosure.apply(table["id"], sources):
        table["notes"].append("%s: %s" % (nid, text))
    return table


# -- T1 inventory / T1b provenance ---------------------------------------------------------------------------

def _block_columns(ctx, kind="count"):
    return [col(block, block, kind, mark=PILOT_MARK if block == PILOT_BLOCK else None) for block in ctx.blocks]


def _fact(facts, *path):
    def get(block):
        node = facts[block]
        for p in path:
            node = node.get(p, 0) if isinstance(node, dict) else 0
        return node
    return get


def _t1(ctx, summary):
    ix = ctx.ix
    facts = summary["blocks"]
    statuses = list(ctx.meth["state_vocabularies"]["terminal_statuses"])
    r06 = OrderedDict()
    for block in ctx.blocks:
        sums = OrderedDict()
        for v in ctx.variants:
            dist = distribution(ix, "R06", block, {"variant": v}, "status", statuses, marginal=True)
            for status, c in dist.items():
                sums[status] = sums.get(status, 0) + c["numerator"]
        total = sum(sums.values())
        if total != facts[block]["trajectories"]:
            refuse("T1 %s: R06 sums %s trajectories, the dataset has %s" % (
                block, total, facts[block]["trajectories"]))
        for status, n in sums.items():
            if n != facts[block]["terminal"].get(status, 0):
                refuse("T1 %s: R06 %s = %s, the dataset has %s" % (block, status, n,
                                                                   facts[block]["terminal"].get(status, 0)))
        r06[block] = sums
        e04 = ix.get("E04", block, {}, "ENH_PAIRS(GENERATED)")
        if (e04["numerator"], e04["denominator"]) != (facts[block]["enhanced_gated"], facts[block]["enhanced_pairs"]):
            refuse("T1 %s: E04 %s/%s contradicts the dataset %s/%s" % (
                block, e04["numerator"], e04["denominator"], facts[block]["enhanced_gated"],
                facts[block]["enhanced_pairs"]))
        if "gated_groups" not in e04:
            refuse("T1 %s: E04 ENH_PAIRS(GENERATED) lacks gated_groups (methodology E04: also gated groups)"
                   % block)
        if e04["gated_groups"] != facts[block]["gated_groups"]:
            refuse("T1 %s: E04 gated groups %s contradict the dataset %s" % (
                block, e04["gated_groups"], facts[block]["gated_groups"]))
        q01 = ix.get("Q01", block, {}, "BASE")
        if q01["denominator"] != facts[block]["base_cells"]:
            refuse("T1 %s: Q01 BASE denominator %s != %s base cells" % (
                block, q01["denominator"], facts[block]["base_cells"]))
    columns = [col("quantity", "Quantity", "text", width="6.5cm"), col("unit", "Unit", "text")]
    columns += _block_columns(ctx)
    rows = []

    def add(quantity, unit, values):
        row = OrderedDict([("quantity", quantity), ("unit", unit)])
        for block in ctx.blocks:
            row[block] = values(block)
        rows.append(row)

    fact = lambda *path: _fact(facts, *path)  # noqa: E731
    add("models", "model", fact("models"))
    add("benchmarks (resampling clusters)", "benchmark", fact("benchmarks"))
    add("benchmark families (problem types)", "family", fact("families"))
    add("base cells (BASE)", "base cell", fact("base_cells"))
    add("base cells of the BL-01 benchmark %s (removed by SA1)" % core.BL01_BENCHMARK, "base cell",
        fact("bl01_cells"))
    iterations = sorted(set(k for b in ctx.blocks for k in facts[b]["candidates"]), key=int)
    for k in iterations:
        add("repair candidates, iteration %s" % k, "artifact", fact("candidates", k))
    add("repair candidates (REPAIR_CANDIDATES)", "artifact",
        lambda b: sum(facts[b]["candidates"].values()))
    add("artifacts (GENERATED)", "artifact", fact("artifacts"))
    add("trajectories (base cells x variants)", "trajectory", fact("trajectories"))
    for status in ordered(set(s for b in ctx.blocks for s in r06[b]), statuses):
        add("terminal status %s (R06 sum over variants)" % status, "trajectory",
            lambda b, s=status: r06[b].get(s, 0))
    add("enhanced pairs, all (ENH_PAIRS(GENERATED))", "enhanced pair", fact("enhanced_pairs"))
    add("enhanced pairs, valid", "enhanced pair", fact("enhanced_valid"))
    add("enhanced pairs, gated (E04 numerator)", "enhanced pair", fact("enhanced_gated"))
    add("gated (benchmark, spec, execution model) groups", "group", fact("gated_groups"))
    for kind in sorted(set(k for b in ctx.blocks for k in facts[b]["generations"])):
        add("generation records, %s" % kind, "generation", fact("generations", kind))
    notes = ["Counts of the normalized dataset per block; composite = pilot + full_ext (distinct counts: union); "
             "evidence owners and input identities in T1b.",
             "Terminal statuses are trajectory facts, not success metrics (R06).",
             "Cross-checked: R06 sums == trajectories per status, E04 == enhanced pairs/gated, "
             "Q01 BASE denominator == base cells."]
    return make_table(
        "T1_inventory", "Study inventory per block", "BASE, REPAIR_CANDIDATES, GENERATED, TRAJECTORIES, "
        "ENH_PAIRS(GENERATED) (counts)", "count; the observation unit of each row is in column Unit",
        columns, rows, notes, None, ctx.pilot_footnotes(ctx.blocks))


def _t1b(ctx, summary):
    facts = summary["blocks"]
    columns = ([col("quantity", "Quantity", "text", width="5.6cm"), col("unit", "Unit", "text")]
               + _block_columns(ctx) + [col("identity", "Identity", "text", width="4.6cm")])
    rows = []

    def add(quantity, unit, values, identity=None):
        row = OrderedDict([("quantity", quantity), ("unit", unit)])
        for block in ctx.blocks:
            row[block] = values(block) if values else None
        row["identity"] = identity
        rows.append(row)

    for stage in ("correctness", "static", "dynamic", "enhanced"):
        owners = sorted(set(o for b in ctx.blocks for o in facts[b]["owners"][stage]))
        unit = "artifact (pair set)" if stage == "enhanced" else "artifact (record)"
        for owner in owners:
            add("%s evidence owner %s" % (stage, owner), unit, _fact(facts, "owners", stage, owner))
    for owner in sorted(set(o for b in ctx.blocks for o in facts[b]["supplemented"])):
        add("static tool entries supplemented by %s" % owner, "artifact x tool",
            _fact(facts, "supplemented", owner))
    for key, value in (summary.get("provenance") or {}).items():
        add("dataset input %s" % key, "identity", None, str(value))
    add("methodology %s (canonical sha256)" % ctx.meth["methodology_id"], "identity", None,
        canonical_sha256(ctx.meth))
    add("addendum %s, %s (canonical sha256)" % (ctx.addendum["addendum_id"], ctx.addendum["status"]), "identity",
        None, canonical_sha256(ctx.addendum))
    notes = ["Evidence owners: the run whose records each artifact's stage evidence comes from (per block; "
             "composite = pilot + full_ext); supplemented: static tool entries taken from another owner than the "
             "static record. Identities: the inputs the dataset and the analysis rest on (-- in the block "
             "columns: an identity is not a count)."]
    return make_table("T1b_provenance", "Evidence owners and input identities", "GENERATED (evidence records)",
                      "artifact / artifact x tool (owners); identity (sha256)", columns, rows, notes, None,
                      ctx.pilot_footnotes(ctx.blocks))


# -- T2 initial quality ------------------------------------------------------------------------------------

T2_PARTS = OrderedDict([
    ("quality", ("Initial code quality (BASE)", ("Q02", "Q05", "Q06", "Q04"))),
    ("heldout", ("Initial held-out pass and analysis verdicts (BASE)", ("E01", "E02", "E04", "F01", "F02")))])


def _t2(ctx, block, table_id, part):
    """One block, one metric group (the two groups together are spec T2).
    Rows: all, per execution model, per model and per model x execution model."""
    ix = ctx.ix
    title, metrics = T2_PARTS[part]
    specs = [("all", "all", OrderedDict())]
    for em in ctx.exec_of(block):
        specs.append(("all", em, OrderedDict([("execution_model", em)])))
    for m in ctx.models(block):
        specs.append((m, "all", OrderedDict([("model_id", m)])))
        for em in ctx.exec_of(block):
            specs.append((m, em, OrderedDict([("model_id", m), ("execution_model", em)])))
    rows = []
    for model, em, strata in specs:
        full = len(strata) == 2
        row = OrderedDict([("model_id", model), ("execution_model", em)])
        if part == "quality":
            row["q02"] = cell(ix.get("Q02", block, strata, "BASE"))
            for key, metric in (("q05", "Q05"), ("q06", "Q06")):
                row[key] = row[key + "_ci"] = cell(ix.get(metric, block, strata, "BASE"))
            row["q04"] = cell(ix.get("Q04", block, _merged(strata, flag="any"), "BASE"))
            row["q04_auto"] = cell(ix.get("Q04", block, _merged(strata, flag="auto_closed"), "BASE"))
        else:
            for key, metric, population in (("e01", "E01", "ENH_PAIRS(BASE)"), ("e02", "E02", "BASE")):
                row[key] = row[key + "_ci"] = cell(ix.get(metric, block, strata, population))
            row["e04"] = cell(ix.get("E04", block, strata, "ENH_PAIRS(BASE)"))     # BY model x execution model
            for key, metric in (("f01", "F01"), ("f02", "F02")):
                dist = distribution(ix, metric, block, strata, "state", core.THREE_STATE, "BASE", required=not full)
                row[key] = dist["DIRTY"] if dist else None
        rows.append(row)
    dashed = set(k for row in rows for k, v in row.items() if v is None)
    labels = col("model_id", "Model", "text"), col("execution_model", "Execution model", "text")
    if part == "quality":
        columns = (list(labels) + rate_cols("q02", "Q02 assembled") + rate_cols("q05", "Q05 build", True)
                   + rate_cols("q06", "Q06 pass", True) + rate_cols("q04", "Q04 any cleaning")
                   + rate_cols("q04_auto", "Q04 auto_closed"))
    else:
        def mark(key):
            return NOT_STRATIFIED_MARK if key in dashed else None
        columns = (list(labels) + rate_cols("e01", "E01 pair pass", True) + rate_cols("e02", "E02 all-pass", True)
                   + rate_cols("e04", "E04 gated pairs") + rate_cols("f01", "F01 static DIRTY", mark=mark("f01"))
                   + rate_cols("f02", "F02 dynamic DIRTY", mark=mark("f02")))
    if dashed - set(("f01", "f02")):
        refuse("%s: unexpected missing cells in %s" % (table_id, sorted(dashed)))
    uses_dash = bool(dashed)
    if part == "quality":
        population, unit = "BASE (iteration-0 artifacts of the base cells)", "artifact (base cell)"
        cells_note = "Cells: percentage (numerator/denominator) of base cells; Q04 over assembled artifacts."
    else:
        population = "BASE (iteration-0 artifacts of the base cells); E01/E04: ENH_PAIRS(BASE)"
        unit = "artifact (base cell); E01/E04: enhanced pair"
        cells_note = ("Cells: percentage (numerator/denominator); E01 and E04 count enhanced pairs, E02/F01/F02 "
                      "base cells; F01/F02 DIRTY = >= 1 reported blocking finding of an applicable tool (union "
                      "over tools, labelled as such).")
    notes = (["Block: %s." % block] + ctx.population("BASE", "ENH_PAIRS")[:1 if part == "quality" else 2]
             + [cells_note] + ctx.legend(*metrics))
    footnotes = ctx.pilot_footnotes([block])
    if uses_dash:
        footnotes.append((NOT_STRATIFIED_MARK, NOT_STRATIFIED_TEXT))
    return make_table(table_id, "%s, block %s" % (title, block), population, unit, columns, rows, notes,
                      None, footnotes)


# -- T3 tool coverage ----------------------------------------------------------------------------------------

def frozen_tools(ix, stage, blocks, metric, populations=("BASE", "GENERATED")):
    """The frozen tool list of a stage (core.STATIC_TOOLS / DYNAMIC_TOOLS,
    the tool universe of metrics.py); the coverage estimates of every block
    and population must carry exactly these tools."""
    tools = list(STAGES[stage])
    for block in blocks:
        for population in populations:
            found = ix.values(metric, block, "tool", None, population)
            if found != set(tools):
                refuse("%s %s %s: tools %s, the frozen %s tool list is %s" % (
                    metric, population, block, sorted(found), stage, tools))
    return tools


def _tools(ctx, stage, metric):
    tools = frozen_tools(ctx.ix, stage, ctx.blocks, metric)
    for block in ctx.blocks:
        data = list(ctx.facts[block]["tools"][stage])
        if set(data) != set(tools):
            refuse("%s: the dataset's %s tool entries name tools %s, the frozen list is %s" % (
                block, stage, data, tools))
    return tools


def _t3(ctx):
    ix = ctx.ix
    states = list(ctx.meth["state_vocabularies"]["tool_states"])
    columns = [col("stage", "Stage", "text"), col("tool", "Tool", "text"), _block_col()]
    for s in states:
        columns.append(col("state_" + s, "S01/D01 %s %% (n/N)" % s, "rate", group="GENERATED state shares",
                           sub=s))
    columns += [col("cov_base", "S02/D02 coverage BASE % (n/N)", "rate", group="definitive coverage", sub="BASE"),
                col("cov_gen", "S02/D02 coverage GENERATED % (n/N)", "rate", group="definitive coverage",
                    sub="GENERATED")]
    rows = []
    for stage, dist_metric, cov_metric in (("static", "S01", "S02"), ("dynamic", "D01", "D02")):
        tools = _tools(ctx, stage, cov_metric)
        for block in ctx.blocks:
            found = set(dict(skey).get("tool") for _, skey, _e in ix.scan(dist_metric, block, "GENERATED"))
            if found != set(tools):
                refuse("%s GENERATED %s: tools %s, the frozen %s tool list is %s" % (
                    dist_metric, block, sorted(found), stage, tools))
        for tool in tools:
            for block in ctx.blocks:
                row = OrderedDict([("stage", stage), ("tool", tool), ("block", block)])
                dist = distribution(ix, dist_metric, block, {"tool": tool}, "state", states, "GENERATED")
                for s in states:
                    row["state_" + s] = dist[s]
                row["cov_base"] = cell(ix.get(cov_metric, block, {"tool": tool}, "BASE"))
                row["cov_gen"] = cell(ix.get(cov_metric, block, {"tool": tool}, "GENERATED"))
                rows.append(row)
    notes = (ctx.population("GENERATED", "BASE")
             + ["State shares over all GENERATED artifacts (diagnostic population); NOT_APPLICABLE and "
                "ABSENT_INAPPLICABLE are shown separately and never counted as analysis gaps; coverage = "
                "COMPLETED among artifacts to which the tool applies."]
             + ctx.legend("S01", "S02", "D01", "D02"))
    return make_table("T3_tool_coverage", "Analysis tool states and definitive coverage per tool and block",
                      "GENERATED (state shares; %s); BASE and GENERATED (coverage)" % ctx.use("GENERATED"),
                      "artifact x tool",
                      columns, rows, notes, None, ctx.pilot_footnotes(ctx.blocks))


# -- T4 findings / T4b agreement -----------------------------------------------------------------------------

def _t4(ctx):
    ix = ctx.ix
    kinds = list(core.FINDING_KINDS)
    pops = ("BASE", "GENERATED")
    tool_order = list(core.STATIC_TOOLS + core.DYNAMIC_TOOLS)
    observed = set()                       # (tool, family, kind) with an F05 estimate anywhere
    for block in ctx.blocks:
        for population, skey, _est in ix.scan("F05", block):
            strata = dict(skey)
            if set(strata) - {"variant"} != {"tool", "family", "kind", QUANTITY_KEY}:
                refuse("F05 estimate with strata {%s} (expected tool, family, kind, %s)" % (
                    _strata_text(skey), QUANTITY_KEY))
            if strata["kind"] not in kinds or strata[QUANTITY_KEY] not in (F05_FINDINGS, F05_ARTIFACTS):
                refuse("F05 foreign kind / quantity in {%s}" % _strata_text(skey))
            if strata["tool"] not in tool_order:
                refuse("F05 foreign tool in {%s}" % _strata_text(skey))
            observed.add((strata["tool"], strata["family"], strata["kind"]))
    if not observed:
        refuse("no F05 estimates")
    combos = set((t, f) for t, f, _k in observed)
    rows, sources = [], []
    for tool in ordered(set(t for t, _ in combos), tool_order):
        for family in sorted(f for t, f in combos if t == tool):
            for block in ctx.blocks:
                row = OrderedDict([("tool", tool), ("family", family), ("block", block)])
                for population in pops:
                    for kind in kinds:
                        # metrics.py emits every observed (tool, family, kind) for every block and population
                        # (zero counts included): such a cell is required, an unobserved triple has no estimate
                        required = (tool, family, kind) in observed
                        strata = OrderedDict([("tool", tool), ("family", family), ("kind", kind)])
                        found = ix.get("F05", block, _merged(strata, quantity=F05_FINDINGS), population,
                                       required=required)
                        with_finding = ix.get("F05", block, _merged(strata, quantity=F05_ARTIFACTS), population,
                                              required=required)
                        if found is None:
                            row["%s_%s" % (population, kind)] = None
                            continue
                        if with_finding["denominator"] is None or not 0 <= with_finding["numerator"] <= \
                                with_finding["denominator"]:
                            refuse("F05 %s %s {%s}: artifacts with a finding %s of %s applicable" % (
                                population, block, _strata_text(strata_key(strata)), with_finding["numerator"],
                                with_finding["denominator"]))
                        sources += [found, with_finding]
                        row["%s_%s" % (population, kind)] = [found["numerator"], with_finding["numerator"],
                                                             with_finding["denominator"]]
                rows.append(row)
    dashed = set(k for row in rows for k, v in row.items() if v is None)
    columns = [col("tool", "Tool", "text"), col("family", "Finding family", "text"), _block_col()]
    for population in pops:
        for kind in kinds:
            key = "%s_%s" % (population, kind)
            columns.append(col(key, "%s %s findings (artifacts n/N)" % (population, kind), "count_pair",
                               group=population, sub=kind, mark=OMITTED_MARK if key in dashed else None))
    notes = (ctx.population("BASE", "GENERATED")
             + ["Cells: recorded findings of the tool (artifacts with >= 1 such finding / artifacts to which the "
                "tool applies; F05 sub-quantities %s and %s); findings of different tools are never added (no "
                "cross-tool sum); kinds per the methodology finding_rules; GENERATED counts are diagnostic."
                % (F05_FINDINGS, F05_ARTIFACTS)]
             + ctx.legend("F05"))
    footnotes = ctx.pilot_footnotes(ctx.blocks)
    if dashed:
        footnotes.append((OMITTED_MARK, "--: no finding of this tool / family / kind is recorded in any block or "
                                        "population (the producer emits no F05 estimate for it)"))
    return make_table("T4_findings", "Recorded findings per tool and finding family",
                      "BASE and GENERATED (GENERATED: %s)" % ctx.use("GENERATED"),
                      "finding (artifacts n/N applicable in parentheses)", columns, rows, notes, None, footnotes,
                      sources)


def predefined_pairs(methodology):
    """The F06 tool pairs predefined by the methodology (metric meaning
    '(tool, tool) class on ...'), as frozensets."""
    meaning = OrderedDict((m["id"], m) for m in methodology["metrics"])["F06"]["meaning"]
    pairs = [frozenset(p) for p in re.findall(r"\(([a-z][a-z_]*), ([a-z][a-z_]*)\)", meaning)]
    if not pairs or len(set(pairs)) != len(pairs) or any(len(p) != 2 for p in pairs):
        refuse("the methodology F06 text does not predefine distinct tool pairs")
    return pairs


def _t4b(ctx):
    ix = ctx.ix
    columns = [col("pair", "Tool pair", "text", width="2.6cm"), col("class", "Family class", "text", width="2.4cm"),
               col("scope", "Further strata", "text"), _block_col(), col("n", "Both COMPLETED", "count"),
               col("n11", "both flag", "count", group="2x2 counts", sub="both"),
               col("n10", "first only", "count", group="2x2 counts", sub="first only"),
               col("n01", "second only", "count", group="2x2 counts", sub="second only"),
               col("n00", "neither", "count", group="2x2 counts", sub="neither"),
               col("positive_agreement", "Positive agreement", "number", digits=3),
               col("kappa", "Cohen's kappa", "number", digits=3)]
    expected = predefined_pairs(ctx.meth)
    entries = []
    for b_index, block in enumerate(ctx.blocks):
        pairs = []
        for _, skey, est in ix.scan("F06", block):
            strata = dict(skey)
            for key in ("n11", "n10", "n01", "n00", "positive_agreement", "kappa"):
                if key not in est:
                    refuse("F06 estimate %s {%s} lacks %s" % (block, _strata_text(skey), key))
            if sum(est[k] for k in ("n11", "n10", "n01", "n00")) != est["denominator"]:
                refuse("F06 %s {%s}: the 2x2 counts do not sum to the denominator" % (block, _strata_text(skey)))
            pairs.append(frozenset(str(strata.get("pair", "")).split("+")))
            scope = ", ".join("%s=%s" % (k, v) for k, v in skey if k not in ("pair", "class"))
            entries.append(((strata.get("pair", ""), strata.get("class", ""), scope, b_index), block, est))
        if len(pairs) != len(expected) or set(pairs) != set(expected):
            refuse("F06 %s: tool pairs %s, the methodology predefines %s" % (
                block, sorted("+".join(sorted(p)) for p in pairs), sorted("+".join(sorted(p)) for p in expected)))
    rows = []
    for (pair, klass, scope, _), block, est in sorted(entries, key=lambda e: e[0]):
        rows.append(OrderedDict([
            ("pair", pair), ("class", klass), ("scope", scope), ("block", block), ("n", est["denominator"]),
            ("n11", est["n11"]), ("n10", est["n10"]), ("n01", est["n01"]), ("n00", est["n00"]),
            ("positive_agreement", est["positive_agreement"]), ("kappa", est["kappa"])]))
    if not any(row["scope"] for row in rows):          # no further strata: drop the empty column
        columns = [c for c in columns if c["key"] != "scope"]
        for row in rows:
            del row["scope"]
    notes = (ctx.population("GENERATED")
             + ["Agreement on the presence of a reported blocking finding of the family class on artifacts where "
                "both tools COMPLETED; descriptive, no test; low-confidence findings excluded; -- = not "
                "estimable (no overlap or an undefined statistic)."] + ctx.legend("F06"))
    return make_table("T4b_tool_agreement", "Agreement of predefined tool pairs",
                      "GENERATED (%s)" % ctx.use("GENERATED"), "artifact (both tools COMPLETED)", columns, rows,
                      notes, None, ctx.pilot_footnotes(ctx.blocks), [e for _k, _b, e in entries])


# -- T5 repair by model --------------------------------------------------------------------------------------

def _repair_cells(ix, block, endpoint, variant, strata, sensitivity=False):
    """R02, R03, R04 cells; R04 must equal (improved - regressed) / (base-fail
    + base-pass cells). SA1 covers Q06 R02 R04 R05 only, so R03 is optional
    there (the identity is then checked only when R03 exists)."""
    base = _merged(strata, endpoint=endpoint, variant=variant)
    if sensitivity:
        base[SENSITIVITY_KEY] = SA1
    r02, r04 = ix.get("R02", block, base), ix.get("R04", block, base)
    r03 = ix.get("R03", block, base, required=not sensitivity)
    if r03 is not None and (r04["numerator"] != r02["numerator"] - r03["numerator"] or
                            r04["denominator"] != r02["denominator"] + r03["denominator"]):
        refuse("R04 contradicts R02/R03 for %s %s %s {%s}" % (block, endpoint, variant,
                                                              _strata_text(strata_key(base))))
    return cell(r02), cell(r03), cell(r04)


def _t5(ctx, endpoint, table_id):
    ix = ctx.ix
    label = {"Q06": "Q06 correctness pass", "E02": "E02 enhanced all-pass"}[endpoint]
    columns = [_block_col(), col("model_id", "Model", "text"), col("variant", "Variant", "text"),
               col("base", "BASE % (n/N)", "rate", group=label, sub="BASE"),
               col("final", "FINAL % (n/N)", "rate", group=label, sub="FINAL"),
               col("improved", "R02 improved % (n/base-fail)", "rate", group="repair", sub="R02 improved"),
               col("regressed", "R03 regressed % (n/base-pass)", "rate", group="repair", sub="R03 regressed"),
               col("gain", "R04 net gain pp (n/N)", "diff", group="R04 net gain", sub="pp (n/N)"),
               col("gain_ci", "R04 net gain 95% CI", "ci_pp", group="R04 net gain", sub="95% CI")]
    rows = []
    for block in ctx.blocks:
        for model in ["all"] + ctx.models(block):
            strata = OrderedDict() if model == "all" else OrderedDict([("model_id", model)])
            base = cell(ix.get(endpoint, block, strata, "BASE"))
            for v in ctx.variants:
                final = cell(ix.get(endpoint, block, _merged(strata, variant=v), "FINAL"))
                r02, r03, r04 = _repair_cells(ix, block, endpoint, v, strata)
                what = "%s %s %s model %s" % (endpoint, block, v, model)
                same_cohort(base, final, "FINAL vs BASE " + what)
                same_cohort(base, r04, "R04 vs BASE " + what)
                rows.append(OrderedDict([("block", block), ("model_id", model), ("variant", v), ("base", base),
                                         ("final", final), ("improved", r02), ("regressed", r03), ("gain", r04),
                                         ("gain_ci", r04)]))
    notes = (ctx.population("BASE", "FINAL")
             + ["Paired by base cell; a successful repair is an improvement on the endpoint (R02), terminal statuses "
                "play no role; net gain = (improved - regressed) / cells; BASE, FINAL[v] and R02-R04 rest on the "
                "identical base cells (checked)."]
             + ctx.legend(endpoint, "R02", "R03", "R04"))
    return make_table(table_id, "Repair outcome per model and variant (%s)" % label,
                      "BASE paired with FINAL[v] (identical base-cell cohort)", "base cell", columns, rows,
                      notes, None, ctx.pilot_footnotes(ctx.blocks))


# -- T6 stops / T6b effort -----------------------------------------------------------------------------------

def _t6(ctx):
    ix = ctx.ix
    statuses = list(ctx.meth["state_vocabularies"]["terminal_statuses"])
    dists = OrderedDict()
    for v in ctx.variants:
        for block in ctx.blocks:
            dists[(v, block)] = distribution(ix, "R06", block, {"variant": v}, "status", statuses, marginal=True)
    shown = [s for s in statuses if any(d[s]["numerator"] for d in dists.values())]
    omitted = [s for s in statuses if s not in shown]
    columns = [col("variant", "Variant", "text"), _block_col()]
    prefix = "stopped_"
    for s in shown:
        columns.append(col("r06_" + s, "R06 %s %% (n/N)" % s, "rate", group="R06 terminal status (%s...)" % prefix,
                           sub=s[len(prefix):] if s.startswith(prefix) else s))
    columns += [col("r07", "R07 budget exhausted % (n/N)", "rate", group="R07", sub="budget"),
                col("r08", "R08 analysis-incomplete stop % (n/N)", "rate", group="R08", sub="analysis incomplete"),
                col("r09", "R09 >=1 repair requested % (n/N)", "rate", group="R09", sub=">=1 repair requested"),
                col("r10", "R10 mean iterations (sum/N)", "mean", digits=2, group="R10", sub="mean iterations")]
    rows = []
    for (v, block), dist in dists.items():
        row = OrderedDict([("variant", v), ("block", block)])
        for s in shown:
            row["r06_" + s] = dist[s]
        strata = {"variant": v}
        r07, r08 = cell(ix.get("R07", block, strata)), cell(ix.get("R08", block, strata))
        _same_counts(r07, dist["stopped_budget"], "R07 vs R06 stopped_budget %s %s" % (v, block))
        _same_counts(r08, dist["stopped_analysis_incomplete"],
                     "R08 vs R06 stopped_analysis_incomplete %s %s" % (v, block))
        row["r07"], row["r08"] = r07, r08
        row["r09"] = cell(ix.get("R09", block, strata))
        row["r10"] = cell(ix.get("R10", block, strata))
        rows.append(row)
    notes = (["TRAJECTORIES: %s." % ctx.meth["observation_units"]["trajectory"],
              "Stop statuses are trajectory facts, NOT success metrics; R09 counts trajectories that requested a "
              "repair, not successful repairs (R02 in T5/T5b).",
              "R07 equals the R06 stopped_budget share and R08 the R06 stopped_analysis_incomplete share "
              "(identical counts, checked); both are shown under their own metric ids."]
             + ctx.legend("R06", "R07", "R08") + ctx.legend("R09", meaning=("R09",)) + ctx.legend("R10"))
    footnotes = ctx.pilot_footnotes(ctx.blocks)
    if omitted:
        footnotes.append((OMITTED_MARK, "terminal statuses with 0 trajectories in every row (not shown): "
                          + ", ".join(omitted)))
    return make_table("T6_stops_effort", "Loop stops per variant and block", "TRAJECTORIES", "trajectory",
                      columns, rows, notes, None, footnotes)


def _extras(est):
    return OrderedDict((k, est[k]) for k in sorted(est) if k not in ESTIMATE_FIELDS)


def _plain_number(value, sep=True):
    """Compact rendering of a further statistic (4 significant digits)."""
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return format(value, ",") if sep else str(value)
    if isinstance(value, float):
        if abs(value) >= 1e4:
            return format(value, ",.0f" if sep else ".0f")
        return format(value, ".4g")
    return str(value)


def _t6b(ctx):
    ix = ctx.ix
    columns = [col("variant", "Variant", "text"), _block_col(), col("metric", "Metric", "text"),
               col("population", "Population", "text", width="1.9cm", display=POPULATION_ABBREVIATIONS),
               col("quantity", "Quantity / strata", "text", width="2.6cm"),
               col("numerator", "Numerator", "count"), col("denominator", "Denominator", "count"),
               col("value", "Value", "dnumber"), col("extra", "Further statistics", "mapping", width="3.8cm")]
    entries = []
    grid = OrderedDict()                   # (metric, population) -> {(block, variant): set(sub-quantities)}
    for metric in EFFORT_METRICS:
        for b_index, block in enumerate(ctx.blocks):
            for population, skey, est in ix.scan(metric, block):
                strata = dict(skey)
                if "model_id" in strata:
                    continue
                if (metric, population) not in EFFORT_GRID:
                    refuse("T6b: unexpected %s population %s (expected %s)" % (
                        metric, population, [p for m, p in EFFORT_GRID if m == metric]))
                variant = strata.get("variant", "")
                if variant and variant not in ctx.variants:
                    refuse("T6b: %s with a foreign variant %r" % (metric, variant))
                v_index = ctx.variants.index(variant) if variant in ctx.variants else -1
                rest = ", ".join(v if k == QUANTITY_KEY else "%s=%s" % (k, v) for k, v in skey if k != "variant")
                grid.setdefault((metric, population), OrderedDict()).setdefault((block, variant), set()).add(rest)
                entries.append(((v_index, variant, b_index, metric, population, rest), block, est))
    for (metric, population), basis in EFFORT_GRID.items():
        # the cells every (block, variant) with units of the basis must carry (dataset facts, never the estimates)
        expected = set()
        for block in ctx.blocks:
            facts = ctx.facts[block]
            if basis == "base_cells":
                if facts["base_cells"]:
                    expected.add((block, ""))
            else:
                expected |= set((block, v) for v in ctx.variants if facts[basis].get(v, 0))
        got = grid.get((metric, population), OrderedDict())
        if set(got) != expected:
            refuse("T6b: %s %s estimates cover %s, the dataset's %s imply %s" % (
                metric, population, sorted(got), basis, sorted(expected)))
        if len(set(frozenset(s) for s in got.values())) > 1:
            refuse("T6b: the %s %s sub-quantities differ between blocks / variants: %s" % (
                metric, population, OrderedDict((k, sorted(s)) for k, s in got.items())))
    rows = []
    for (_, variant, _, metric, population, rest), block, est in sorted(entries, key=lambda e: e[0]):
        value = OrderedDict([("value", est["value"]), ("digits", EFFORT_DIGITS[metric])])
        rows.append(OrderedDict([("variant", variant or "(base generation)"), ("block", block), ("metric", metric),
                                 ("population", population), ("quantity", rest), ("numerator", est["numerator"]),
                                 ("denominator", est["denominator"]), ("value", value), ("extra", _extras(est))]))
    abbreviations = "; ".join("%s = %s" % (short, full) for full, short in POPULATION_ABBREVIATIONS.items())
    notes = (ctx.population("BASE", "REPAIR_CANDIDATES")
             + ["One row per effort estimate (all models); value = the estimate's point value (C01 per "
                "trajectory or per improved cell as given by its strata, C02 tokens per generation, C03 median "
                "seconds, C05 improved cells per effort unit); descriptive only, no ranking.",
                "Abbreviation in column Population: %s (the JSON form keeps the full name)." % abbreviations]
             + ctx.legend("C01", "C02", "C03", "C05"))
    return make_table("T6b_effort", "Repair effort per variant and block",
                      "REPAIR_CANDIDATES (%s; C02 also BASE, C05 FINAL[v] vs BASE)" % ctx.use("REPAIR_CANDIDATES"),
                      "generation / repair request (see metric)", columns, rows, notes, None,
                      ctx.pilot_footnotes(ctx.blocks), [e for _k, _b, e in entries])


# -- T7a / T7b / T7c held-out ----------------------------------------------------------------------------------

def _g01_difference(ix, block, variant, e05):
    """The G01 difference estimate (strata variant + one comparison label):
    its reference must be the E05 BASE share of the same block."""
    labels = ix.values("G01", block, "comparison", {"variant": variant})
    if len(labels) != 1:
        refuse("G01 %s %s: expected one difference-to-reference estimate, found %s" % (block, variant,
                                                                                       sorted(labels)))
    est = ix.get("G01", block, {"variant": variant, "comparison": labels.pop()})
    for key in ("reference_numerator", "reference_denominator"):
        if key not in est:
            refuse("G01 difference estimate lacks %s" % key)
    if (est["reference_numerator"], est["reference_denominator"]) != (e05["numerator"], e05["denominator"]):
        refuse("contradictory estimates: G01 reference %s/%s vs E05 BASE %s/%s (%s %s)" % (
            est["reference_numerator"], est["reference_denominator"], e05["numerator"], e05["denominator"],
            block, variant))
    return cell(est)


def _step_header(endpoint, k, steps):
    tag = " BASE" if k == steps[0] else (" FINAL" if k == steps[-1] else "")
    return "%s step %s%s %% (n/N)" % (endpoint, k, tag), "step %s%s" % (k, tag)


def _t7a(ctx):
    ix = ctx.ix
    columns = [_block_col(), col("variant", "Variant", "text"),
               col("e01_base", "E01 BASE % (n/N pairs)", "rate", group="E01 pair pass", sub="BASE"),
               col("e01_final", "E01 FINAL % (n/N pairs)", "rate", group="E01 pair pass", sub="FINAL")]
    for endpoint, label in (("E02", "E02 all-pass (G02)"), ("Q06", "Q06 pass (G02)")):
        for k in ctx.steps:
            header, sub = _step_header(endpoint, k, ctx.steps)
            columns.append(col("%s_step%s" % (endpoint.lower(), k), header, "rate", group=label, sub=sub))
    rows = []
    for block in ctx.blocks:
        e01_base = cell(ix.get("E01", block, {}, "ENH_PAIRS(BASE)"))
        bases = OrderedDict((e, cell(ix.get(e, block, {}, "BASE"))) for e in ("E02", "Q06"))
        for v in ctx.variants:
            e01_final = cell(ix.get("E01", block, {"variant": v}, "ENH_PAIRS(FINAL)"))
            same_cohort(e01_base, e01_final, "E01 FINAL vs BASE valid pairs %s %s" % (block, v))
            row = OrderedDict([("block", block), ("variant", v), ("e01_base", e01_base), ("e01_final", e01_final)])
            for endpoint, base in bases.items():
                final = cell(ix.get(endpoint, block, {"variant": v}, "FINAL"))
                same_cohort(base, final, "%s FINAL vs BASE %s %s" % (endpoint, block, v))
                for k in ctx.steps:
                    g02 = cell(ix.get("G02", block, {"endpoint": endpoint, "variant": v, "step": k}))
                    step = cell(ix.get(endpoint, block, {"variant": v, "step": k}, "STEP"))
                    _same_counts(g02, step, "G02 vs %s STEP[%s][%s] (%s)" % (endpoint, v, k, block))
                    same_cohort(base, step, "%s STEP[%s][%s] vs BASE (%s)" % (endpoint, v, k, block))
                    if k == ctx.steps[0]:
                        _same_counts(g02, base, "%s STEP[%s][%s] vs BASE (%s)" % (endpoint, v, k, block))
                    if k == ctx.steps[-1]:
                        _same_counts(g02, final, "%s STEP[%s][%s] vs FINAL (%s)" % (endpoint, v, k, block))
                    row["%s_step%s" % (endpoint.lower(), k)] = g02
            rows.append(row)
    notes = (ctx.population("BASE", "STEP", "FINAL", "ENH_PAIRS")
             + ["E01 counts valid enhanced pairs, all other columns base cells; the step columns are the G02 "
                "estimates (checked equal to the endpoint's STEP[v][k]; step %s == BASE and step %s == FINAL[v], "
                "checked)." % (ctx.steps[0], ctx.steps[-1])]
             + ctx.legend("E01", "E02", "Q06", "G02"))
    return make_table("T7a_heldout_rates", "Held-out (enhanced) and ParEval pass rates over the repair steps",
                      "BASE, STEP[v][k], FINAL[v]; E01: ENH_PAIRS(BASE) / ENH_PAIRS(FINAL)",
                      "base cell; E01: enhanced pair", columns, rows, notes, None, ctx.pilot_footnotes(ctx.blocks))


def _t7b(ctx):
    ix = ctx.ix
    columns = [_block_col(), col("variant", "Variant", "text"),
               col("e02_improved", "E02 R02 improved % (n/base-fail)", "rate", group="E02 transitions",
                   sub="R02 improved"),
               col("e02_regressed", "E02 R03 regressed % (n/base-pass)", "rate", group="E02 transitions",
                   sub="R03 regressed"),
               col("g01", "G01 repaired cells all-pass % (n/N)", "rate", group="G01", sub="% (n/N)"),
               col("e05_base", "E05 BASE reference % (n/N)", "rate", group="G01", sub="reference E05"),
               col("g01_diff", "G01 minus reference pp", "pp", group="G01", sub="difference pp"),
               col("g01_diff_ci", "G01 minus reference 95% CI", "ci_pp", group="G01", sub="95% CI")]
    rows = []
    for block in ctx.blocks:
        e02_base = cell(ix.get("E02", block, {}, "BASE"))
        e05 = cell(ix.get("E05", block, {}, "BASE"))
        for v in ctx.variants:
            r02, r03, r04 = _repair_cells(ix, block, "E02", v, {})
            same_cohort(e02_base, r04, "E02 R04 vs BASE %s %s" % (block, v))
            diff = _g01_difference(ix, block, v, e05)
            rows.append(OrderedDict([("block", block), ("variant", v), ("e02_improved", r02),
                                     ("e02_regressed", r03), ("g01", cell(ix.get("G01", block, {"variant": v}))),
                                     ("e05_base", e05), ("g01_diff", diff), ("g01_diff_ci", diff)]))
    notes = (ctx.population("BASE", "FINAL")
             + ["E02 transitions of the same base cell (identical cohort, checked); G01 vs the E05 BASE reference "
                "(all-pass share of cells passing Q06 at baseline): difference in pp; joint Q06 / E02 transitions "
                "(X06): T7c."]
             + ctx.legend("R02", "R03", "G01", "E05"))
    return make_table("T7b_heldout_transitions", "Held-out (enhanced) transitions of the repairs",
                      "BASE paired with FINAL[v]; G01: base cells improved on Q06", "base cell", columns, rows, notes,
                      None, ctx.pilot_footnotes(ctx.blocks))


def transition_order(labels):
    """R01 labels 'a->b' ordered improved, regressed, unchanged failing,
    unchanged passing (a state starting with 'not_' is the failing one)."""
    def key(label):
        parts = str(label).split("->")
        if len(parts) != 2 or not all(parts):
            refuse("not a transition label: %r" % (label,))
        start, end = [not p.startswith("not_") for p in parts]
        return ({(False, True): 0, (True, False): 1, (False, False): 2, (True, True): 3}[(start, end)], label)
    return sorted(labels, key=key)


def _r01_labels(ix, block, endpoint, variants):
    found = None
    for v in variants:
        labels = ix.values("R01", block, "transition", {"endpoint": endpoint, "variant": v}, "FINAL")
        if not labels or (found is not None and labels != found):
            refuse("R01 FINAL %s %s: transition labels %s differ between variants or are missing" % (
                block, endpoint, sorted(labels)))
        found = labels
    return transition_order(found)


def x06_cohort_checks(ix, block, variant, cells, q_labels, h_labels, cohort):
    """X06 rests on the cells in BOTH paired cohorts (contract): with the R04
    cohorts A (Q06) and B (E02) of the same base cells U,
    |A| + |B| - |U| <= cohort <= min(|A|, |B|); and its marginals are the
    R01 transitions of the cells it keeps: for a Q06 label q,
    R01(q) - (|A_R01| - cohort) <= sum_h X06(q, h) <= R01(q), the E02 labels
    alike. A union, a one-endpoint cohort or rescaled counts refuse."""
    what = "X06 FINAL %s %s" % (block, variant)
    paired = OrderedDict((e, cell(ix.get("R04", block, {"endpoint": e, "variant": variant}))) for e in ENDPOINTS)
    for e, c in paired.items():
        if c["denominator"] is None:
            refuse("%s: R04 %s without its paired cohort" % (what, e))
    units = max(_units(c) for c in paired.values())
    upper = min(c["denominator"] for c in paired.values())
    lower = sum(c["denominator"] for c in paired.values()) - units
    if not lower <= cohort <= upper:
        refuse("%s: a cohort of %s cells; the cells in both paired cohorts (R04 %s of %s base cells) are between %s "
               "and %s" % (what, cohort, ", ".join("%s %s" % (e, c["denominator"]) for e, c in paired.items()),
                           units, max(lower, 0), upper))
    for endpoint, labels, axis in (("Q06", q_labels, 0), ("E02", h_labels, 1)):
        r01 = distribution(ix, "R01", block, {"endpoint": endpoint, "variant": variant}, "transition", labels,
                           "FINAL")
        outside = r01[labels[0]]["denominator"] - cohort        # cells of the endpoint cohort not in X06
        for label in labels:
            kept = sum(c["numerator"] for key, c in cells.items() if key[axis] == label)
            full = r01[label]["numerator"]
            if not full - outside <= kept <= full:
                refuse("%s: %s cells with the %s transition %s, the R01 count is %s (%s cells of the %s cohort are "
                       "outside X06)" % (what, kept, endpoint, label, full, outside, endpoint))


def _t7c(ctx):
    ix = ctx.ix
    block = core.COMPOSITE
    q_labels = _r01_labels(ix, block, "Q06", ctx.variants)
    h_labels = _r01_labels(ix, block, "E02", ctx.variants)
    columns = [col("variant", "Variant", "text"), col("q06", "Q06 transition", "text")]
    for h in h_labels:
        columns.append(col("h_" + h, "E02 %s %% (n/N)" % h, "rate", group="E02 transition (held-out)", sub=h))
    columns.append(col("total", "Q06 transition total % (n/N)", "rate", group="all E02", sub="total"))
    rows = []
    for v in ctx.variants:
        seen = set()
        for _, skey, est in ix.scan("X06", block, "FINAL"):
            strata = dict(skey)
            if strata.get("variant") == v:
                if set(strata) != {"variant", "transition", "heldout_transition"}:
                    refuse("X06 estimate with strata {%s}" % _strata_text(skey))
                seen.add((strata["transition"], strata["heldout_transition"]))
        expected = set((q, h) for q in q_labels for h in h_labels)
        if seen != expected:
            refuse("X06 FINAL %s %s: transitions %s, the R01 labels imply every (Q06, E02) pair %s" % (
                block, v, sorted(seen), sorted(expected)))
        cells = OrderedDict(((q, h), cell(ix.get("X06", block, {"variant": v, "transition": q,
                                                                "heldout_transition": h}, "FINAL")))
                            for q in q_labels for h in h_labels)
        dens = set(c["denominator"] for c in cells.values())
        if len(dens) != 1 or sum(c["numerator"] for c in cells.values()) != list(dens)[0]:
            refuse("X06 FINAL %s %s: the joint transitions are not a partition of one cohort" % (block, v))
        den = dens.pop()
        x06_cohort_checks(ix, block, v, cells, q_labels, h_labels, den)
        for q in q_labels:
            row = OrderedDict([("variant", v), ("q06", q)])
            for h in h_labels:
                row["h_" + h] = cells[(q, h)]
            row["total"] = _plain_cell(sum(cells[(q, h)]["numerator"] for h in h_labels), den,
                                       "X06 summed over the E02 transitions", post_freeze=True)
            rows.append(row)
    notes = (ctx.population("BASE", "FINAL")
             + ["Block: composite; cell = base cells with this Q06 (row) and E02 (column) transition; Q06 "
                "not_pass->pass with E02 not_all_pass->not_all_pass = repaired on ParEval, not on the held-out specs; "
                "the cohort lies within both R04 paired cohorts and the row / column sums within the R01 Q06 / E02 "
                "transition counts (checked)."]
             + ctx.legend("X06", "R01"))
    return make_table("T7c_joint_transitions", ctx.post_prefix + "Joint Q06 / E02 transitions of the same base "
                      "cell (X06)", "BASE paired with FINAL[v] (cells in both paired cohorts)", "base cell", columns,
                      rows, notes, None, [])


# -- T8 execution models -------------------------------------------------------------------------------------

def _t8(ctx):
    ix = ctx.ix
    columns = [_block_col(), col("execution_model", "Execution model", "text"), col("variant", "Variant", "text"),
               col("q06_base", "Q06 BASE % (n/N)", "rate", group="Q06 pass", sub="BASE"),
               col("q06_final", "Q06 FINAL % (n/N)", "rate", group="Q06 pass", sub="FINAL"),
               col("gain", "R04 Q06 net gain pp (n/N)", "diff", group="R04 Q06 net gain", sub="pp (n/N)"),
               col("gain_ci", "R04 Q06 net gain 95% CI", "ci_pp", group="R04 Q06 net gain", sub="95% CI"),
               col("e02_base", "E02 BASE % (n/N)", "rate", group="E02 all-pass", sub="BASE"),
               col("e02_final", "E02 FINAL % (n/N)", "rate", group="E02 all-pass", sub="FINAL"),
               col("f01_dirty", "F01 DIRTY BASE % (n/N)", "rate", group="F01 static DIRTY", sub="BASE"),
               col("d03", "D03 dynamic analysis complete BASE % (n/N)", "rate", group="D03 dynamic complete",
                   sub="BASE")]
    rows = []
    for block in ctx.blocks:
        for em in ctx.exec_of(block):
            strata = OrderedDict([("execution_model", em)])
            q06_base = cell(ix.get("Q06", block, strata, "BASE"))
            e02_base = cell(ix.get("E02", block, strata, "BASE"))
            f01 = distribution(ix, "F01", block, strata, "state", core.THREE_STATE, "BASE")["DIRTY"]
            d03 = cell(ix.get("D03", block, strata, "BASE"))
            for v in ctx.variants:
                _r02, _r03, r04 = _repair_cells(ix, block, "Q06", v, strata)
                q06_final = cell(ix.get("Q06", block, _merged(strata, variant=v), "FINAL"))
                e02_final = cell(ix.get("E02", block, _merged(strata, variant=v), "FINAL"))
                what = "%s %s %s" % (block, em, v)
                same_cohort(q06_base, q06_final, "Q06 FINAL vs BASE " + what)
                same_cohort(q06_base, r04, "Q06 R04 vs BASE " + what)
                same_cohort(e02_base, e02_final, "E02 FINAL vs BASE " + what)
                rows.append(OrderedDict([
                    ("block", block), ("execution_model", em), ("variant", v), ("q06_base", q06_base),
                    ("q06_final", q06_final), ("gain", r04), ("gain_ci", r04), ("e02_base", e02_base),
                    ("e02_final", e02_final), ("f01_dirty", f01), ("d03", d03)]))
    notes = (ctx.population("BASE", "FINAL")
             + ["Dynamic coverage per execution model is shown as D03 (every applicable dynamic tool COMPLETED, "
                "artifact level): D02 is a per-tool share (T3) and is never pooled across tools here."]
             + ctx.legend("Q06", "R04", "E02", "F01", "D03"))
    footnotes = ctx.pilot_footnotes(ctx.blocks)
    return make_table("T8_execution_models", "Outcomes per execution model and variant",
                      "BASE paired with FINAL[v]", "base cell", columns, rows, notes, None, footnotes)


# -- T9 primary tests / T9b per block ------------------------------------------------------------------------

def comparison_order(text, variants):
    positions = sorted((text.find(v), i) for i, v in enumerate(variants) if v in text)
    return tuple(i for _, i in positions), text


def primary_size(methodology):
    """The size of the primary family as the methodology states it
    (statistics.tests, parsed by stats.bootstrap_settings)."""
    return stats.bootstrap_settings(methodology)["primary_hypotheses"]


def _close(a, b):
    return isinstance(a, (int, float)) and not isinstance(a, bool) and math.isclose(
        float(a), float(b), rel_tol=1e-9, abs_tol=1e-15)


def check_resolutions(family, replicates):
    """p_resolution = 2 / replicates_primary (an EXPLORATORY estimate: 2 /
    its own replicate count) and p_holm_resolution = the Holm-order running
    maximum of (m - rank + 1) * p_resolution (DESIGN2 section 1; the Holm
    order is ascending p - with equal resolutions the running maximum does
    not depend on how ties are broken)."""
    m = len(family)
    for est in family:
        res = est["p_resolution"]
        allowed = [2.0 / replicates]
        if EXPLORATORY in (est["note"] or ""):
            allowed += [2.0 / n for n in drawn_replicates(est, _label(est))]
        if not any(_close(res, a) for a in allowed):
            refuse("%s: p_resolution %r, expected 2 / %s replicates" % (_label(est), res, replicates))
    running = 0.0
    for rank, est in enumerate(sorted(family, key=lambda e: (e["p_value"], _label(e))), 1):
        running = max(running, (m - rank + 1) * float(est["p_resolution"]))
        if not _close(est["p_holm_resolution"], running):
            refuse("%s: p_holm_resolution %r, the Holm-order running maximum of (m - rank + 1) * p_resolution "
                   "is %r" % (_label(est), est["p_holm_resolution"], running))


def primary_family(estimates, methodology):
    """The primary hypotheses (p_holm set), checked against the methodology:
    the composite R04 x variants + R05 x variant pairs for Q06 and E02, each
    with a percentile interval at the primary replicate count (a different
    count only under the producer's EXPLORATORY label) and the p resolutions
    of the contract."""
    family = [e for e in estimates if e.get("p_holm") is not None]
    variants = list(methodology["strata"]["variant"])
    replicates = int(methodology["statistics"]["bootstrap"]["replicates_primary"])
    size = primary_size(methodology)
    if len(family) != size:
        refuse("primary family has %d hypotheses, expected %d" % (len(family), size))
    keyed = []
    for est in family:
        strata = OrderedDict((k, _strata_value(v)) for k, v in (est["strata"] or {}).items())
        if est["block"] != core.COMPOSITE or est["metric_id"] not in ("R04", "R05"):
            refuse("primary hypothesis outside the composite R04/R05 family: %s %s" % (est["metric_id"],
                                                                                      est["block"]))
        if strata.get("endpoint") not in ENDPOINTS or est["p_value"] is None or \
                not isinstance(est["reject_holm"], bool):
            refuse("primary hypothesis %s {%s} lacks endpoint / p / reject" % (
                est["metric_id"], _strata_text(strata_key(strata))))
        count = est["replicates"]
        what = "primary hypothesis %s {%s}" % (est["metric_id"], _strata_text(strata_key(strata)))
        if isinstance(count, bool) or not isinstance(count, int) or est["ci_method"] != CI_METHOD or \
                est["ci_low"] is None or est["ci_high"] is None:
            refuse("%s without a %s interval and its replicate count (%r)" % (what, CI_METHOD, count))
        drawn, _used = drawn_replicates(est, what)
        if drawn != replicates and EXPLORATORY not in (est["note"] or ""):
            refuse("primary hypothesis with %s replicates (methodology %s)" % (drawn, replicates))
        extra = set(strata) - {"endpoint", "variant", "comparison"}
        if extra:
            refuse("primary hypothesis with further strata %s" % sorted(extra))
        if est["metric_id"] == "R04":
            if strata.get("variant") not in variants:
                refuse("primary R04 without a known variant")
            order = (variants.index(strata["variant"]),)
            label = strata["variant"]
        else:
            if "comparison" not in strata:
                refuse("primary R05 without a comparison")
            order, label = comparison_order(strata["comparison"], variants)
        keyed.append(((ENDPOINTS.index(strata["endpoint"]), est["metric_id"], order, label), strata, est))
    keyed.sort(key=lambda item: item[0])
    pairs = set(frozenset((a, b)) for a in range(len(variants)) for b in range(a + 1, len(variants)))
    for endpoint in ENDPOINTS:
        r04 = set(k[2] for k, s, _ in keyed if s["endpoint"] == endpoint and k[1] == "R04")
        r05 = [frozenset(k[2]) for k, s, _ in keyed if s["endpoint"] == endpoint and k[1] == "R05"]
        if r04 != set((i,) for i in range(len(variants))) or len(r05) != len(pairs) or set(r05) != pairs:
            refuse("primary family for %s is not R04 x {%s} + R05 x the %d variant pairs" % (
                endpoint, ", ".join(variants), len(pairs)))
    check_resolutions(family, replicates)
    return [(strata, est, key[3]) for key, strata, est in keyed]


def hypothesis_text(metric, label, variants):
    if metric == "R04":
        return "FINAL[%s] - BASE" % label
    order, _ = comparison_order(label, variants)
    return ("FINAL[%s] - FINAL[%s]" % (variants[order[0]], variants[order[1]]) if len(order) == 2
            else "FINAL difference %s" % label)


def _p_cell(value, resolution):
    return OrderedDict([("value", value), ("resolution", resolution)])


def _t9(ctx, estimates):
    columns = [col("endpoint", "Endpoint", "text"), col("metric", "Metric", "text"),
               col("hypothesis", "Hypothesis (H0: difference = 0)", "text", width="3.4cm"),
               col("estimate", "Difference pp (n/N)", "diff", group="difference", sub="pp (n/N)"),
               col("ci", "Difference 95% CI (pp)", "ci_pp", group="difference", sub="95% CI"),
               col("p_value", "Bootstrap p", "p"),
               col("p_holm", "Holm-adjusted p", "p", group="Holm step-down", sub="adjusted p"),
               col("reject", "Reject H0 (Holm)", "flag", group="Holm step-down", sub="reject H0")]
    rows = []
    family = primary_family(estimates, ctx.meth)
    # the DRAWN count B (usable + skipped, drawn_replicates) is what the methodology fixes and what p_resolution
    # = 2 / B rests on; skipped resamples are stated in the CI note
    counts = sorted(set(drawn_replicates(est, _label(est))[0] for _s, est, _l in family))
    for strata, est, label in family:
        rows.append(OrderedDict([("endpoint", strata["endpoint"]), ("metric", est["metric_id"]),
                                 ("hypothesis", hypothesis_text(est["metric_id"], label, ctx.variants)),
                                 ("estimate", cell(est)), ("ci", cell(est)),
                                 ("p_value", _p_cell(est["p_value"], est["p_resolution"])),
                                 ("p_holm", _p_cell(est["p_holm"], est["p_holm_resolution"])),
                                 ("reject", est["reject_holm"])]))
    expected = ctx.settings["replicates_primary"]
    if counts == [expected]:
        count_note = ("Every hypothesis rests on the methodology's primary replicate count (B = %s drawn, checked; "
                      "resamples skipped for a zero denominator, if any, are counted in the CI note)"
                      % format(expected, ","))
    else:
        count_note = ("%s: the hypotheses rest on %s drawn replicates instead of the methodology's %s; not "
                      "confirmatory" % (EXPLORATORY, _replicate_counts(counts), format(expected, ",")))
    fields = OrderedDict((f["field"], f["rule"]) for f in ctx.addendum.get("estimate_fields") or [])
    for field in ("p_resolution", "p_holm_resolution"):
        if field not in fields:
            refuse("the addendum does not define the estimate field %s" % field)
    resolutions = sorted(set(_resolution_text(e["p_resolution"]) for _s, e, _l in family))
    holm = sorted(set(_resolution_text(e["p_holm_resolution"]) for _s, e, _l in family))
    notes = (ctx.population("BASE", "FINAL")
             + ["Composite cohort (pilot + full_ext); " + ctx.meth["statistics"]["tests"]["primary_family"],
                count_note + "; everything outside this table is descriptive (unadjusted CIs, no tests); the "
                "per-block estimates of the same hypotheses are in T9b.",
                "Resolution (B = %s replicates; a p below its resolution is shown as '<resolution'): "
                "p_resolution = 2/B = %s (%s); p_holm_resolution = %s (%s)." % (
                    _replicate_counts(counts), " / ".join(resolutions), fields["p_resolution"], " / ".join(holm),
                    fields["p_holm_resolution"])]
             + ctx.legend("R04", "R05"))
    return make_table("T9_primary_tests", "Primary hypotheses (Holm-adjusted)", "BASE paired with FINAL[v]; "
                      "FINAL[v1] vs FINAL[v2] (composite)", "base cell", columns, rows, notes, None, [])


def _t9b(ctx, estimates):
    ix = ctx.ix
    family = primary_family(estimates, ctx.meth)
    columns = [col("endpoint", "Endpoint", "text"), col("metric", "Metric", "text"),
               col("hypothesis", "Hypothesis", "text", width="3.4cm")]
    shown = [b for b in ctx.blocks if b != core.COMPOSITE]      # the composite estimates are T9
    for block in shown:
        mark = PILOT_MARK if block == PILOT_BLOCK else None
        columns += [col(block, "%s difference pp (n/N)" % block, "diff", group=block, sub="pp (n/N)", mark=mark),
                    col(block + "_ci", "%s 95%% CI" % block, "ci_pp", group=block, sub="95% CI")]
    rows = []
    for strata, comp, label in family:
        row = OrderedDict([("endpoint", strata["endpoint"]), ("metric", comp["metric_id"]),
                           ("hypothesis", hypothesis_text(comp["metric_id"], label, ctx.variants))])
        parts = []
        for block in shown:
            est = ix.get(comp["metric_id"], block, comp["strata"], comp["population"])
            if est["p_value"] is not None or est["p_holm"] is not None:
                refuse("%s: a per-block estimate of a primary hypothesis carries a test" % _label(est))
            parts.append(est)
            row[block] = row[block + "_ci"] = cell(est)
        if (sum(e["numerator"] for e in parts), sum(e["denominator"] for e in parts)) != (
                comp["numerator"], comp["denominator"]):
            refuse("%s: the per-block estimates do not add up to the composite (%s/%s)" % (
                _label(comp), comp["numerator"], comp["denominator"]))
        rows.append(row)
    notes = (ctx.population("BASE", "FINAL")
             + ["The 12 primary hypotheses of T9 per block (methodology SA3: every headline estimate per block "
                "next to the composite, which is T9); descriptive (descriptive replicate count, unadjusted, no "
                "test); the block numerators and denominators add up to the composite of T9 (checked)."]
             + ctx.legend("R04", "R05"))
    return make_table("T9b_primary_by_block", "Primary hypotheses per block (descriptive)",
                      "BASE paired with FINAL[v]; FINAL[v1] vs FINAL[v2] (per block)", "base cell",
                      columns, rows, notes, None, ctx.pilot_footnotes(ctx.blocks), [comp for _s, comp, _l in family])


# -- T10 sensitivity / T11 runtime ---------------------------------------------------------------------------

def _comparisons(ix, block, endpoint, variants, metric="R05"):
    labels = ix.values(metric, block, "comparison", {"endpoint": endpoint})
    pairs = len(variants) * (len(variants) - 1) // 2
    if len(labels) != pairs:
        refuse("%s %s %s: %d comparison labels %s, expected the %d variant pairs" % (
            metric, block, endpoint, len(labels), sorted(labels), pairs))
    return sorted(labels, key=lambda text: comparison_order(text, variants))


def single_x01_cohort(block, endpoint, named_cells):
    """X01 removes a base cell when ANY artifact on ANY of its three
    trajectories was auto-closed (contract), so one cohort - the same
    denominator and the same excluded count - serves every variant and every
    comparison of a (block, endpoint); a cohort that depends on the variant
    (e.g. removal by the variant's own trajectory) refuses."""
    cohorts = OrderedDict()
    for name, c in named_cells:
        cohorts.setdefault((c["denominator"], c["excluded"]), []).append(name)
    if len(cohorts) != 1:
        refuse("X01 %s %s: the auto-closed cohort differs between the variants / comparisons (%s); the rule removes "
               "a base cell over all three trajectories, so one cohort serves every variant" % (
                   block, endpoint, "; ".join("%s cells + %s excluded: %s" % (d, x, ", ".join(names))
                                              for (d, x), names in cohorts.items())))


def _t10(ctx):
    ix = ctx.ix
    sa1 = OrderedDict([(SENSITIVITY_KEY, SA1)])
    columns = [_block_col(), col("endpoint", "Endpoint", "text"),
               col("hypothesis", "Difference", "text", width="1.9cm"),
               col("r02", "R02 improved main % (n/base-fail)", "rate", group="R02 improved", sub="main",
                   mark=UNDEFINED_MARK),
               col("r02_sa1", "R02 improved SA1 % (n/base-fail)", "rate", group="R02 improved", sub="SA1"),
               col("main", "R04/R05 main pp (n/N)", "diff", group="R04 / R05 main (frozen)", sub="pp (n/N)"),
               col("main_ci", "R04/R05 main 95% CI", "ci_pp", group="R04 / R05 main (frozen)", sub="95% CI"),
               col("sa1", "SA1 pp (n/N)", "diff", group="SA1 without BL-01", sub="pp (n/N)"),
               col("sa1_ci", "SA1 95% CI", "ci_pp", group="SA1 without BL-01", sub="95% CI"),
               col("x01", "X01 pp (n/N)", "diff", group="X01 without auto-closed (post-freeze)", sub="pp (n/N)"),
               col("x01_ci", "X01 95% CI", "ci_pp", group="X01 without auto-closed (post-freeze)", sub="95% CI"),
               col("q10_base", "Q10 BASE % (n/N)", "rate", group="SA2 (Q10, frozen)", sub="BASE", mark=COHORT_MARK),
               col("q10_final", "Q10 FINAL % (n/N)", "rate", group="SA2 (Q10, frozen)", sub="FINAL")]
    rows = []
    for block in ctx.blocks:
        q10_base = cell(ix.get("Q10", block, {}, "BASE"))
        q06_base_sa1 = cell(ix.get("Q06", block, sa1, "BASE"))
        for endpoint in ENDPOINTS:
            x01_cohort = []                    # (row, cell) of every X01 estimate of this (block, endpoint)
            for v in ctx.variants:
                r02, _r03, r04 = _repair_cells(ix, block, endpoint, v, {})
                r02_sa1, _x, r04_sa1 = _repair_cells(ix, block, endpoint, v, {}, sensitivity=True)
                x01 = cell(ix.get("X01", block, {"endpoint": endpoint, "variant": v}, "FINAL"))
                x01_cohort.append((v, x01))
                what = "%s %s %s" % (block, endpoint, v)
                same_cohort(r04, x01, "X01 vs R04 " + what)
                q10 = (None, None)
                if endpoint == "Q06":
                    final_sa1 = cell(ix.get("Q06", block, _merged(sa1, variant=v), "FINAL"))
                    same_cohort(q06_base_sa1, final_sa1, "SA1 Q06 FINAL vs BASE " + what)
                    same_cohort(q06_base_sa1, r04_sa1, "SA1 Q06 R04 vs BASE " + what)
                    q10 = (q10_base, cell(ix.get("Q10", block, {"variant": v}, "FINAL")))
                rows.append(OrderedDict([
                    ("block", block), ("endpoint", endpoint), ("hypothesis", hypothesis_text("R04", v, ctx.variants)),
                    ("r02", r02), ("r02_sa1", r02_sa1), ("main", r04), ("main_ci", r04), ("sa1", r04_sa1),
                    ("sa1_ci", r04_sa1), ("x01", x01), ("x01_ci", x01), ("q10_base", q10[0]),
                    ("q10_final", q10[1])]))
            x01_labels = _comparisons(ix, block, endpoint, ctx.variants, "X01")
            for label in _comparisons(ix, block, endpoint, ctx.variants):
                if label not in x01_labels:
                    refuse("X01 %s %s: no comparison %s (X01 uses the R05 labels)" % (block, endpoint, label))
                r05 = cell(ix.get("R05", block, {"endpoint": endpoint, "comparison": label}))
                r05_sa1 = cell(ix.get("R05", block, _merged(sa1, endpoint=endpoint, comparison=label)))
                x01 = cell(ix.get("X01", block, {"endpoint": endpoint, "comparison": label}, "FINAL"))
                x01_cohort.append((label, x01))
                same_cohort(r05, x01, "X01 vs R05 %s %s %s" % (block, endpoint, label))
                rows.append(OrderedDict([
                    ("block", block), ("endpoint", endpoint),
                    ("hypothesis", hypothesis_text("R05", label, ctx.variants)), ("r02", None), ("r02_sa1", None),
                    ("main", r05), ("main_ci", r05), ("sa1", r05_sa1), ("sa1_ci", r05_sa1), ("x01", x01),
                    ("x01_ci", x01), ("q10_base", None), ("q10_final", None)]))
            single_x01_cohort(block, endpoint, x01_cohort)
    analyses = OrderedDict((a["id"], a) for a in ctx.meth["sensitivity_analyses"])
    notes = (ctx.population("BASE", "FINAL")
             + ["%s %s: %s" % (k, analyses[k]["name"], analyses[k]["rule"]) for k in ("SA1", "SA2", "SA3")]
             + ["One row per block, endpoint and hypothesis of the primary family (R04 per variant, R05 per variant "
                "pair): the frozen estimate, SA1 (without the BL-01 benchmark cells; its Q06 BASE / FINAL rates are "
                "checked on the identical SA1 cohort and given in the estimates) and the post-freeze X01 (without "
                "base cells with an auto-closed artifact; X01 and the frozen estimate rest on the same base cells "
                "before exclusion, and one X01 cohort serves every variant and comparison of a block and endpoint, "
                "checked; 'k excl.' counts the removed cells)."]
             + ctx.legend("R02", "R04", "R05", "Q10", "X01"))
    footnotes = ctx.pilot_footnotes(ctx.blocks) + [
        (UNDEFINED_MARK, "--: not defined for this row (R02 is a per-variant share and Q10 a per-variant Q06 pass "
                         "rate; they are shown on the R04 rows, Q10 on the Q06 rows only)"),
        (COHORT_MARK, "Q10 (frozen SA2) is unpaired: its BASE and FINAL[v] columns rest on different cohorts "
                      "(artifacts without auto-closing at each stage), see IC7; the paired sensitivity is X01")]
    return make_table("T10_sensitivity", "Sensitivity analyses SA1 (without BL-01 benchmark), X01 (post-freeze, "
                      "without auto-closed cells) and SA2 (Q10)",
                      "BASE paired with FINAL[v]; FINAL[v1] vs FINAL[v2]; SA1 without the BL-01 benchmark cells; X01 "
                      "without base cells with an auto-closed artifact", "base cell", columns, rows, notes, None,
                      footnotes)


def runtime_grid(ctx):
    """(tool, execution model or "all", block) combos the dataset's RAN tool
    entries imply (C04 applicability: ran tools) -> number of ran entries."""
    grid = OrderedDict()
    for block in ctx.blocks:
        for tool, ems in ctx.facts[block]["ran_entries"].items():
            total = 0
            for em, n in ems.items():
                if n:
                    grid[(tool, em, block)] = n
                    total += n
            if total:
                grid[(tool, "all", block)] = total
    return grid


def _t11(ctx):
    ix = ctx.ix
    columns = [col("tool", "Tool", "text"), col("execution_model", "Execution model", "text"), _block_col()]
    for rule, label in ((C04_ALL, "all entries"), (C04_EXCL, "excluding > %s s" % format(
            core.RUNTIME_OUTLIER_SECONDS, ","))):
        columns += [col("median_" + rule, "median s (%s)" % label, "number", digits=1, group=label, sub="median s"),
                    col("p95_" + rule, "p95 s (%s)" % label, "number", digits=1, group=label, sub="p95 s"),
                    col("n_" + rule, "n (%s)" % label, "count", group=label, sub="n")]
    columns.append(col("timeouts", "TIMEOUT entries (excluded)", "count"))
    combos = set()
    for block in ctx.blocks:
        for _, skey, _est in ix.scan("C04", block):
            strata = dict(skey)
            if set(strata) - {"execution_model"} != {"tool", "outlier_rule"} or \
                    strata["outlier_rule"] not in (C04_ALL, C04_EXCL):
                refuse("C04 estimate with strata {%s}" % _strata_text(skey))
            combos.add((strata["tool"], strata.get("execution_model", "all"), block))
    grid = runtime_grid(ctx)
    if combos != set(grid):
        refuse("C04 estimates cover %s (tool, execution model, block) combos, the dataset's ran tool entries imply "
               "%s; missing %s, extra %s" % (len(combos), len(grid), sorted(set(grid) - combos)[:6],
                                             sorted(combos - set(grid))[:6]))
    if not combos:
        refuse("no C04 estimates")
    tool_order = list(core.STATIC_TOOLS + core.DYNAMIC_TOOLS)
    rows, sources = [], []
    for tool in ordered(set(c[0] for c in combos), tool_order):
        for em in ordered(set(c[1] for c in combos if c[0] == tool), ["all"] + ctx.exec_models):
            for block in ctx.blocks:
                if (tool, em, block) not in combos:
                    continue                       # the tool never ran there (dataset fact, checked above)
                row = OrderedDict([("tool", tool), ("execution_model", em), ("block", block)])
                timeouts = None
                for rule in (C04_ALL, C04_EXCL):
                    strata = OrderedDict([("tool", tool), ("outlier_rule", rule)])
                    if em != "all":
                        strata["execution_model"] = em
                    est = ix.get("C04", block, strata)
                    for key in ("p95", "n", "timeouts", "ran_entries"):
                        if key not in est:
                            refuse("C04 estimate %s {%s} lacks %s" % (block, _strata_text(strata_key(strata)), key))
                    if est["ran_entries"] != grid[(tool, em, block)]:
                        refuse("C04 %s {%s}: %s ran entries, the dataset has %s" % (
                            block, _strata_text(strata_key(strata)), est["ran_entries"], grid[(tool, em, block)]))
                    sources.append(est)
                    row["median_" + rule] = est["value"]
                    row["p95_" + rule] = est["p95"]
                    row["n_" + rule] = est["n"]
                    if rule == C04_ALL:
                        timeouts = est["timeouts"]
                row["timeouts"] = timeouts
                rows.append(row)
    analyses = OrderedDict((a["id"], a) for a in ctx.meth["sensitivity_analyses"])
    notes = (ctx.population("GENERATED")
             + ["SA4 %s: %s; raw durations unchanged, no standby estimate subtracted; wall-clock, host-dependent; "
                "rows exist for every (tool, execution model, block) with ran tool entries (checked against the "
                "dataset)." % (analyses["SA4"]["name"], analyses["SA4"]["rule"])] + ctx.legend("C04"))
    return make_table("T11_runtime", "Tool runtime per tool and execution model (SA4)",
                      "GENERATED (%s)" % ctx.use("GENERATED"),
                      "artifact x tool (entries with a numeric duration, TIMEOUT excluded)", columns, rows, notes,
                      None, ctx.pilot_footnotes(ctx.blocks), sources)


# -- T12 / T12b post-freeze addendum -------------------------------------------------------------------------

def _t12(ctx):
    ix = ctx.ix
    states = core.THREE_STATE
    group_dirty, group_x04 = ("static DIRTY: frozen F01 vs X02 tool-verdict reading",
                              "X04 among Q06-failing artifacts")
    columns = [_block_col(), col("population", "Population", "text", width="2.3cm"),
               col("f01", "F01 DIRTY frozen % (n/N)", "rate", group=group_dirty, sub="F01 frozen"),
               col("x02", "X02 DIRTY tool-verdict % (n/N)", "rate", group=group_dirty, sub="X02"),
               col("x02_ci", "X02 DIRTY 95% CI", "ci", group=group_dirty, sub="X02 95% CI"),
               col("x02_only", "DIRTY only under the frozen rule % (n/N)", "rate", group=group_dirty,
                   sub="F01 only")]
    for state, key in zip(X04_STATES, ("x04_clean", "x04_nfi")):
        columns += [col(key, "X04 %s %% (n/N)" % state, "rate", group=group_x04, sub=state),
                    col(key + "_ci", "X04 %s 95%% CI" % state, "ci", group=group_x04, sub="95% CI")]
    rows = []
    for block in ctx.blocks:
        scopes = [("BASE", "BASE", OrderedDict())] + [("FINAL[%s]" % v, "FINAL", OrderedDict([("variant", v)]))
                                                      for v in ctx.variants]
        for label, population, strata in scopes:
            what = "%s %s" % (block, label)
            f01 = distribution(ix, "F01", block, strata, "state", states, population)["DIRTY"]
            x02 = distribution(ix, "X02", block, strata, "state", states, population)["DIRTY"]
            x02_est = ix.get("X02", block, _merged(strata, state="DIRTY"), population)
            only = _int_extra(x02_est, X02_ONLY)
            if x02["denominator"] != f01["denominator"]:
                refuse("X02 vs F01 %s: different artifact cohorts (%s vs %s)" % (
                    what, x02["denominator"], f01["denominator"]))
            if x02["numerator"] != f01["numerator"] - only:
                refuse("X02 vs F01 %s: X02 DIRTY %s != F01 DIRTY %s - %s %s" % (
                    what, x02["numerator"], f01["numerator"], X02_ONLY, only))
            row = OrderedDict([("block", block), ("population", label), ("f01", f01), ("x02", x02),
                               ("x02_ci", x02),
                               ("x02_only", _plain_cell(only, x02["denominator"], "X02 %s" % X02_ONLY, True))])
            x04 = [cell(ix.get("X04", block, _merged(strata, state=s), population)) for s in X04_STATES]
            if len(set(c["denominator"] for c in x04)) != 1:
                refuse("X04 %s: the states rest on different Q06-failing cohorts" % what)
            # contract: denominator = artifacts with a verdict neither pass nor baseline_incompatible, i.e. the
            # Q06 denominator (baseline_incompatible excluded) minus its pass numerator, same population
            q06 = ix.get("Q06", block, strata, population)
            if q06["denominator"] is None or q06["numerator"] is None or \
                    x04[0]["denominator"] != q06["denominator"] - q06["numerator"]:
                refuse("X04 %s: denominator %s, the Q06 %s artifacts failing Q06 are %s - %s" % (
                    what, x04[0]["denominator"], label, q06["denominator"], q06["numerator"]))
            if sum(c["numerator"] for c in x04) > x04[0]["denominator"]:
                refuse("X04 %s: the states count more artifacts than the Q06-failing cohort" % what)
            row["x04_clean"] = row["x04_clean_ci"] = x04[0]
            row["x04_nfi"] = row["x04_nfi_ci"] = x04[1]
            rows.append(row)
    notes = (ctx.population("BASE", "FINAL")
             + ["F01 only = artifacts DIRTY under the frozen rule (findings of any entry state) but not under X02 "
                "(only COMPLETED / PARTIAL entries count): X02 DIRTY = F01 DIRTY - F01 only (checked); X04 "
                "denominator = the artifacts failing Q06 of the same population (Q06 denominator - pass, checked); "
                "the DIRTY composition per tool is T12b, X05 is T12c."]
             + ctx.legend("F01", "X02", "X04"))
    return make_table("T12_addendum", ctx.post_prefix + "Static DIRTY under the tool-verdict reading (X02 vs F01) "
                      "and statically clean but incorrect artifacts (X04)", "BASE / FINAL[v]", "artifact", columns,
                      rows, notes, None, ctx.pilot_footnotes(ctx.blocks))


def _t12c(ctx):
    ix = ctx.ix
    iterations = [str(k) for k in range(core.MAX_ITERATIONS + 1)]
    columns = [_block_col(), col("variant", "Variant", "text"),
               col("mean", "X05 mean final iteration (sum/N)", "mean", digits=2, group="X05 clean stops",
                   sub="mean iteration")]
    for k in iterations:
        columns.append(col("it" + k, "X05 final iteration %s %% (n/N)" % k, "rate", group="X05 clean stops",
                           sub="iteration %s" % k))
    rows = []
    for block in ctx.blocks:
        for v in ctx.variants:
            strata = OrderedDict([("variant", v)])
            mean = ix.get("X05", block, strata, "TRAJECTORIES")
            dist = distribution(ix, "X05", block, strata, "iteration", iterations, "TRAJECTORIES")
            total = sum(int(k) * c["numerator"] for k, c in dist.items())
            if (mean["numerator"], mean["denominator"]) != (total, dist[iterations[0]]["denominator"]):
                refuse("X05 %s %s: the mean %s/%s contradicts the distribution (sum %s over %s)" % (
                    block, v, mean["numerator"], mean["denominator"], total, dist[iterations[0]]["denominator"]))
            row = OrderedDict([("block", block), ("variant", v), ("mean", cell(mean))])
            for k in iterations:
                row["it" + k] = dist[k]
            rows.append(row)
    notes = (["TRAJECTORIES: %s." % ctx.meth["observation_units"]["trajectory"],
              "Trajectories ending stopped_clean or stopped_tests_pass (the loop's own clean stop, not a success "
              "metric): mean final iteration (sum / trajectories) and its distribution over the iterations "
              "(mean = sum of k x n_k, checked)."]
             + ctx.legend("X05"))
    return make_table("T12c_iterations_to_clean", ctx.post_prefix + "Iterations to a clean stop (X05)",
                      "TRAJECTORIES (ending stopped_clean / stopped_tests_pass)", "trajectory", columns, rows, notes,
                      None, ctx.pilot_footnotes(ctx.blocks))


def x03_top(addendum):
    """The number of check ids X03 selects per tool, as the addendum states it
    ('... for the <n> check ids with most reported blocking findings ...')."""
    meaning = OrderedDict((m["id"], m) for m in addendum["metrics"]).get("X03", {}).get("meaning") or ""
    found = re.findall(r"\bthe ([0-9]+) check ids\b", meaning)
    if len(found) != 1 or int(found[0]) < 1:
        refuse("the addendum X03 text does not state one check-id count (found %s)" % found)
    return int(found[0])


def x03_shapes(ix, blocks):
    """Every X03 estimate in the contract shapes: population BASE, a tool of
    core.STATIC_ANALYSIS_TOOLS (an extra tool would be silently dropped
    otherwise), strata {tool, quantity dirty_only_via_tool} or {tool,
    check_id, quantity blocking_findings / artifacts_with_check}."""
    tools_ = set(core.STATIC_ANALYSIS_TOOLS)
    for block in blocks:
        for population, skey, _est in ix.scan("X03", block):
            strata = dict(skey)
            quantity = strata.get(QUANTITY_KEY)
            want = ({"tool", QUANTITY_KEY} if quantity == X03_DIRTY_ONLY else
                    {"tool", "check_id", QUANTITY_KEY} if quantity in (X03_FINDINGS, X03_ARTIFACTS) else None)
            if population != "BASE" or want is None or set(strata) != want:
                refuse("X03 estimate %s %s with strata {%s} (contract: BASE, tool + %s, or tool + check_id + %s / %s)"
                       % (population, block, _strata_text(skey), X03_DIRTY_ONLY, X03_FINDINGS, X03_ARTIFACTS))
            if strata["tool"] not in tools_:
                refuse("X03 %s {%s}: a tool outside the static analysis tools %s" % (
                    block, _strata_text(skey), list(core.STATIC_ANALYSIS_TOOLS)))


def _t12b(ctx):
    ix = ctx.ix
    composite = core.COMPOSITE
    top_n = x03_top(ctx.addendum)
    x03_shapes(ix, ctx.blocks)
    columns = [col("tool", "Tool", "text"), col("check_id", "Check id", "text", width="4.2cm")]
    for block in ctx.blocks:
        mark = PILOT_MARK if block == PILOT_BLOCK else None
        columns += [col(block + "_findings", "%s reported blocking findings" % block, "count", group=block,
                        sub="findings", mark=mark),
                    col(block + "_artifacts", "%s artifacts %% (n/N)" % block, "rate", group=block,
                        sub="artifacts % (n/N)")]
    rows, sources = [], []
    dirty = OrderedDict((block, distribution(ix, "F01", block, {}, "state", core.THREE_STATE, "BASE")["DIRTY"])
                        for block in ctx.blocks)
    for tool in core.STATIC_ANALYSIS_TOOLS:
        row = OrderedDict([("tool", tool), ("check_id", "(any check) DIRTY only via this tool")])
        for block in ctx.blocks:
            est = ix.get("X03", block, {"tool": tool, QUANTITY_KEY: X03_DIRTY_ONLY}, "BASE")
            if est["denominator"] != dirty[block]["numerator"]:
                refuse("X03 %s %s: dirty-only denominator %s != F01 BASE DIRTY %s" % (
                    block, tool, est["denominator"], dirty[block]["numerator"]))
            row[block + "_findings"] = None
            row[block + "_artifacts"] = cell(est)
        rows.append(row)
        checks = None
        for block in [composite] + [b for b in ctx.blocks if b != composite]:
            for quantity in (X03_FINDINGS, X03_ARTIFACTS):
                found = ix.values("X03", block, "check_id", {"tool": tool, QUANTITY_KEY: quantity}, "BASE")
                if checks is None:
                    checks = found
                elif found != checks:
                    refuse("X03 %s %s %s: check ids %s, the composite selection is %s" % (
                        block, tool, quantity, sorted(found), sorted(checks)))
        if len(checks) > top_n:
            refuse("X03 %s: %d check ids, the addendum selects the top %d per tool" % (tool, len(checks), top_n))
        if checks:
            for block in ctx.blocks:
                # 'BASE artifacts to which t applies' = the S02 BASE denominator of the tool, one per (block, tool)
                applicable = ix.get("S02", block, {"tool": tool}, "BASE")["denominator"]
                dens = sorted(set(ix.get("X03", block, {"tool": tool, "check_id": c, QUANTITY_KEY: X03_ARTIFACTS},
                                         "BASE")["denominator"] for c in checks), key=str)
                if dens != [applicable]:
                    refuse("X03 %s %s %s: denominators %s, the BASE artifacts to which the tool applies (S02 BASE) "
                           "are %s" % (block, tool, X03_ARTIFACTS, dens, applicable))
        top = OrderedDict()
        for check in checks:
            top[check] = ix.get("X03", composite, {"tool": tool, "check_id": check, QUANTITY_KEY: X03_FINDINGS},
                                "BASE")["numerator"]
        for check in sorted(top, key=lambda c: (-top[c], c)):
            row = OrderedDict([("tool", tool), ("check_id", check)])
            for block in ctx.blocks:
                base = OrderedDict([("tool", tool), ("check_id", check)])
                findings = ix.get("X03", block, _merged(base, **{QUANTITY_KEY: X03_FINDINGS}), "BASE")
                arts = ix.get("X03", block, _merged(base, **{QUANTITY_KEY: X03_ARTIFACTS}), "BASE")
                if isinstance(findings["numerator"], bool) or not isinstance(findings["numerator"], int):
                    refuse("X03 %s %s %s: blocking findings %r is not a count" % (block, tool, check,
                                                                                  findings["numerator"]))
                sources.append(findings)
                row[block + "_findings"] = findings["numerator"]
                row[block + "_artifacts"] = cell(arts)
            rows.append(row)
    notes = (ctx.population("BASE")
             + ["Per static analysis tool: the first row is the share of BASE DIRTY artifacts (F01 frozen rule) "
                "that are DIRTY only through this tool (denominator = F01 BASE DIRTY, checked); then its check ids "
                "with the most reported blocking findings on the composite BASE (at most %d per tool, selected once "
                "there and reused for the blocks, checked): reported blocking findings and BASE artifacts with >= 1 "
                "such finding / BASE artifacts to which the tool applies (= the S02 BASE denominator, checked). "
                "Findings of different tools are never added." % top_n]
             + ctx.legend("X03", "F01"))
    return make_table("T12b_dirty_checks", ctx.post_prefix + "Composition of the static DIRTY verdicts (X03)",
                      "BASE", "artifact (shares) / finding (counts)", columns, rows, notes, None,
                      ctx.pilot_footnotes(ctx.blocks), sources)


# -- entry point ---------------------------------------------------------------------------------------------

def disclosure_for(methodology, addendum):
    """The addendum disclosures resolved against every table and figure id."""
    from thesis.study_analysis import figures as _figures          # import here: figures imports this module

    return Disclosure(addendum, methodology, TABLE_IDS + tuple(_figures.FIGURE_IDS))


def build_tables(estimates, dataset_summary, methodology, addendum=None):
    """All study tables in TABLE_IDS order. `dataset_summary` is
    summarize_dataset(dataset) or the core.Dataset itself (the expected row
    sets and the inventory come from the dataset, never from the estimates);
    `addendum` None -> core.load_addendum(methodology=methodology), a passed
    one is checked the same way (checked_addendum)."""
    if isinstance(dataset_summary, core.Dataset):
        dataset_summary = summarize_dataset(dataset_summary)
    if not isinstance(dataset_summary, dict) or "blocks" not in dataset_summary:
        refuse("build_tables needs summarize_dataset(dataset) (dataset.counts() alone has no per-block facts)")
    addendum = checked_addendum(addendum, methodology)
    estimates = list(estimates)
    ix = EstimateIndex(estimates, methodology, addendum)
    ctx = _Ctx(ix, methodology, dataset_summary, addendum, disclosure_for(methodology, addendum))
    tables = [_t1(ctx, dataset_summary), _t1b(ctx, dataset_summary),
              _t2(ctx, core.COMPOSITE, "T2a_initial_quality_composite", "quality"),
              _t2(ctx, "pilot", "T2b_initial_quality_pilot", "quality"),
              _t2(ctx, "full_ext", "T2c_initial_quality_full_ext", "quality"),
              _t2(ctx, core.COMPOSITE, "T2d_initial_heldout_composite", "heldout"),
              _t2(ctx, "pilot", "T2e_initial_heldout_pilot", "heldout"),
              _t2(ctx, "full_ext", "T2f_initial_heldout_full_ext", "heldout"),
              _t3(ctx), _t4(ctx), _t4b(ctx),
              _t5(ctx, "Q06", "T5_repair_by_model"), _t5(ctx, "E02", "T5b_repair_by_model_heldout"),
              _t6(ctx), _t6b(ctx), _t7a(ctx), _t7b(ctx), _t7c(ctx), _t8(ctx), _t9(ctx, estimates),
              _t9b(ctx, estimates), _t10(ctx), _t11(ctx), _t12(ctx), _t12b(ctx), _t12c(ctx)]
    if tuple(t["id"] for t in tables) != TABLE_IDS:
        refuse("table ids drifted from TABLE_IDS")
    return [_finish(ctx, t, tests=t["id"] == "T9_primary_tests") for t in tables]


# -- rendering (shared by CSV and LaTeX) ---------------------------------------------------------------------

def _qty(value, sep):
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return format(value, ",") if sep else str(value)
    return format(float(value), ",.2f" if sep else ".2f")


def _signed_qty(value, sep):
    text = _qty(value, sep)
    return text if text.startswith("-") or text in ("0", "0.00") else "+" + text


def _fixed(value, digits, sep, signed=False):
    text = format(float(value), ("+" if signed else "") + (",." if sep else ".") + "%df" % digits)
    if text.lstrip("+-").strip("0.,") == "":           # never "-0.0"
        text = text.lstrip("+-")
    return text


def _pct(value, sep, signed=False):
    return _fixed(float(value) * 100.0, 1, sep, signed)


def _frac(c, sep, signed=False, excl=True):
    num = _signed_qty(c["numerator"], sep) if signed else _qty(c["numerator"], sep)
    den = "?" if c["denominator"] is None else _qty(c["denominator"], sep)
    text = "%s/%s" % (num, den)
    if excl and c.get("excluded"):                       # units an exclusion rule removed (methodology)
        text += "; %s excl." % _qty(c["excluded"], sep)
    return text


def excluded_text(c, sep=False):
    """'k excl.' of a ratio cell (LaTeX sets it on a line of its own), or None."""
    return ("%s excl." % _qty(c["excluded"], sep)) if c and c.get("excluded") else None


def _resolution_text(resolution):
    return ("%.8f" % resolution).rstrip("0").rstrip(".")


def ci_parts(c):
    """(interval text, degenerate) of a CI cell; the dagger is added by the
    renderer (CSV: appended, LaTeX: \\textsuperscript{\\dag})."""
    if c is None or c.get("ci_low") is None or c.get("ci_high") is None:
        return "--", False
    return "[%s, %s]" % (_pct(c["ci_low"], False), _pct(c["ci_high"], False)), bool(c.get("ci_degenerate"))


def _ci_text(c):
    text, degenerate = ci_parts(c)
    return text + (DAGGER if degenerate else "")


RATIO_KINDS = ("rate", "diff", "mean")       # cells shown as "value (numerator/denominator)"


def cell_parts(value, column, sep=False, excl=True):
    """(value text, "(n/N)" text) of a ratio cell; LaTeX sets them on two
    lines (three with 'k excl.', excl=False leaves it out here), CSV on one."""
    kind = column["kind"]
    if kind not in RATIO_KINDS:
        refuse("cell_parts of a %s column" % kind)
    if kind == "rate":
        main = "n/a" if value["value"] is None else _pct(value["value"], sep)
        return main, "(%s)" % _frac(value, sep, excl=excl)
    if kind == "diff":
        main = "n/a" if value["value"] is None else _pct(value["value"], sep, signed=True)
        return main, "(%s)" % _frac(value, sep, signed=True, excl=excl)
    main = "n/a" if value["value"] is None else _fixed(value["value"], column.get("digits", 2), sep)
    return main, "(%s)" % _frac(value, sep, excl=excl)


def p_text(value, resolution=None):
    """A p-value; below its resolution shown as '<resolution' (p = 0 of a
    bootstrap over B replicates means p < 2/B)."""
    if isinstance(value, dict):
        resolution = value.get("resolution", resolution)
        value = value.get("value")
    if value is None:
        return "--"
    if resolution is not None and float(value) < float(resolution):
        return "<" + _resolution_text(float(resolution))
    return "<0.0001" if float(value) < 0.0001 else "%.4f" % float(value)


def cell_text(value, column, sep=False):
    """The display text of one raw cell (sep: thousands separators)."""
    kind = column["kind"]
    if kind in ("text", "block"):
        if value is None:
            return ""
        return str((column.get("display") or {}).get(value, value))
    if value is None:
        return "--"
    if kind == "count":
        return _qty(value, sep)
    if kind in RATIO_KINDS:
        return "%s %s" % cell_parts(value, column, sep)
    if kind in CI_KINDS:
        return _ci_text(value)
    if kind == "pp":
        return "n/a" if value["value"] is None else _pct(value["value"], sep, signed=True)
    if kind == "number":
        return _fixed(value, column.get("digits", 2), sep)
    if kind == "dnumber":
        return "n/a" if value["value"] is None else _fixed(value["value"], value["digits"], sep)
    if kind == "mapping":
        return "; ".join("%s=%s" % (k, _plain_number(v, sep)) for k, v in value.items())
    if kind == "p":
        return p_text(value, column.get("resolution"))
    if kind == "flag":
        return "yes" if value else "no"
    if kind == "count_pair":
        first = _qty(value[0], sep)
        if len(value) == 3:
            return "%s (%s/%s)" % (first, _qty(value[1], sep), "?" if value[2] is None else _qty(value[2], sep))
        return first if value[1] is None else "%s (%s)" % (first, _qty(value[1], sep))
    refuse("unknown column kind %r" % kind)


def header_text(column):
    return column["header"] + (" [%s]" % column["mark"] if column.get("mark") else "")


def block_text(value, mark_pilot=True):
    return value + (" [%s]" % PILOT_MARK) if (mark_pilot and value == "pilot") else value


def table_csv(table):
    """The displayed grid as CSV (LF, no thousands separators; pilot block
    cells carry the footnote mark, zero-width intervals the dagger)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    columns = table["columns"]
    writer.writerow([header_text(c) for c in columns])
    for row in table["rows"]:
        out = []
        for c in columns:
            text = cell_text(row[c["key"]], c)
            out.append(block_text(text) if c["kind"] == "block" else text)
        writer.writerow(out)
    return buffer.getvalue().encode("utf-8")


def table_json(table):
    """The table object itself (raw, unrounded cells; strata values with
    their estimate types) as stable JSON."""
    return core.json_bytes(table)
