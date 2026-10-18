"""Inference primitives of the study analysis (stdlib only, deterministic).

WHY a stratified cluster bootstrap: every artifact, enhanced pair, model,
execution model, variant and iteration of one benchmark shares the prompt
family and the oracle, so the benchmark is the independent unit
(methodology statistics.inference_unit). Benchmarks are resampled with
replacement WITHIN their block (pilot among its 12, full_ext among its 48;
statistics.bootstrap.stratified_by), and one weight matrix per
(cluster set, replicates, seed) is shared by every estimate so paired
estimates (R04, R05, G01) see identical resamples.

Determinism: clusters are sorted, strata are sorted, the draws are made
with ``random.Random(seed).randrange(len(stratum))`` in replicate-major,
stratum-sorted order. The same inputs give bit-identical weights, sums,
intervals and p-values in every process.

Point estimates are ratios of sums over the ORIGINAL data (all weights 1);
replicate estimates are ratios of weighted sums. A replicate whose weighted
denominator is 0 is skipped and counted (``degenerate``); an original
denominator of 0 gives value None and no interval (never a default).

Interval support (structural, independent of the values): a ratio of sums
that rests on ONE cluster is invariant to that cluster's weight, so every
non-degenerate replicate equals the point estimate and a percentile
"interval" would claim zero uncertainty; a cluster in a single-cluster
stratum always gets weight 1 and is never resampled. An estimate therefore
gets an interval only when >= 2 clusters carry its data and every one of
them lies in a stratum of >= 2 clusters; otherwise value is reported with
ci_low/ci_high None and ``ci_note`` says why (and p_value is None). This
matters for the study: the pilot has exactly one benchmark per family, so
pilot per-family estimates are point estimates only. A stratum in which
only one cluster carries the estimate (e.g. the pilot benchmark of a family
inside a composite per-family estimate) keeps its interval - its weight still
varies, which is the domain-size variation of a stratified domain estimate -
and is flagged in ``ci_note``.

Zero-width intervals (post-freeze addendum_1, estimate field
``ci_degenerate``): an estimable interval can still have ci_low == ci_high,
when every non-degenerate replicate equals the point estimate - in the study
almost always because every supporting cluster sits at 0% or 100% (e.g. 12/12
passes over 12 pilot clusters). The bootstrap then cannot express the sampling
uncertainty. Such an interval is kept (it is what the frozen protocol
computes) but flagged: ``ci_degenerate`` is True, False for a positive width
and None without an interval; tables mark it and never present it as
certainty.

Resolution of the bootstrap p-value (addendum_1, ``p_resolution`` /
``p_holm_resolution``): with n usable replicates the smallest positive
two-sided p is 2 / n, so p = 0 means p < 2 / n; the Holm-adjusted value of a
p = 0 hypothesis is bounded by the Holm-order running maximum of
(m - rank + 1) * 2 / n (12 * 2 / 10,000 = 0.0024 for tied zeros), not by 2 / n.

Percentiles use linear interpolation between the closest ranks (Hyndman &
Fan type 7, the default of R and numpy): with n sorted values and
h = (n - 1) * q the percentile is x[floor(h)] + (h - floor(h)) *
(x[floor(h) + 1] - x[floor(h)]).

Performance: the weighted sums of an integer estimate are computed for all
replicates at once by packing each cluster's replicate weights into one
Python integer with 64-bit fields (one big-integer multiply-add per
non-zero cluster, one struct.unpack per estimate). The result is exactly
the plain ``sum(w * x for ...)`` (integer arithmetic, no overflow: a bound
check falls back to the plain loop); a unit test asserts the identity.
"""
from __future__ import annotations

import math
import random
import re
import struct
from collections import OrderedDict
from fractions import Fraction

from thesis.study_analysis import core

CI_METHOD = "cluster_bootstrap_percentile"
MIN_SUPPORT = 2                              # clusters an interval needs (see module docstring)
_FIELD_BITS = 64
_FIELD_LIMIT = 1 << (_FIELD_BITS - 1)        # keep a safety bit below 2**64


# -- methodology settings -----------------------------------------------------------------

def bootstrap_settings(methodology):
    """The frozen bootstrap/test settings (methodology statistics). The
    Holm alpha and the size of the primary family are only stated in prose
    in the frozen document; they are parsed from it (fail closed when the
    text does not carry exactly one value) instead of being typed here."""
    statistics = core.statistics_settings(methodology)
    boot = statistics["bootstrap"]
    tests = statistics["tests"]
    alphas = re.findall(r"\balpha\s+([0-9]*\.[0-9]+|[0-9]+)", tests.get("multiplicity") or "")
    sizes = re.findall(r"\b([0-9]+)\s+hypotheses\b", tests.get("primary_family") or "")
    if len(alphas) != 1 or len(sizes) != 1:
        raise core.AnalysisRefused("the methodology does not state exactly one Holm alpha / primary family size")
    alpha = float(alphas[0])
    confidence = float(boot["confidence_level"])
    if not (0.0 < alpha < 1.0 and 0.0 < confidence < 1.0):
        raise core.AnalysisRefused("methodology alpha/confidence out of range")
    settings = OrderedDict([
        ("confidence", confidence),
        ("replicates_primary", int(boot["replicates_primary"])),
        ("replicates_descriptive", int(boot["replicates_descriptive"])),
        ("seed", int(boot["seed"])),
        ("alpha", alpha),
        ("primary_hypotheses", int(sizes[0])),
    ])
    if settings["replicates_primary"] < 1 or settings["replicates_descriptive"] < 1:
        raise core.AnalysisRefused("methodology replicate counts must be positive")
    return settings


def _frozen_settings():
    return bootstrap_settings(core.load_methodology())


# -- percentiles / descriptive ------------------------------------------------------------

def percentile(sorted_values, q):
    """Type-7 percentile (linear interpolation between closest ranks) of an
    ascending list. An empty or unsorted list, or q outside [0, 1], refuses."""
    values = list(sorted_values)
    if not values:
        raise core.AnalysisRefused("percentile of an empty list")
    if not 0.0 <= q <= 1.0:
        raise core.AnalysisRefused("percentile q outside [0, 1]: %r" % (q,))
    if any(values[i] > values[i + 1] for i in range(len(values) - 1)):
        raise core.AnalysisRefused("percentile input is not sorted")
    h = (len(values) - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (h - lo) * (values[hi] - values[lo])


def quantile(values, q):
    """Type-7 quantile of unsorted values; None for no values (callers count
    and report what they excluded). None entries refuse - missingness is the
    caller's decision, never silently dropped here."""
    values = list(values)
    if any(v is None for v in values):
        raise core.AnalysisRefused("quantile over a null value")
    if not values:
        return None
    return percentile(sorted(values), q)


def median(values):
    return quantile(values, 0.5)


def interval(replicate_values, confidence):
    """Percentile interval at `confidence` over the non-degenerate
    replicate values (None when there are none)."""
    values = sorted(v for v in replicate_values if v is not None)
    if not values:
        return None, None
    tail = (1.0 - confidence) / 2.0
    return percentile(values, tail), percentile(values, 1.0 - tail)


def bootstrap_p_value(replicate_diffs):
    """Two-sided bootstrap p = min(1, 2 * min(P(d <= 0), P(d >= 0))) over
    the non-degenerate replicate differences (None entries are skipped);
    None when no replicate is usable."""
    values = [v for v in replicate_diffs if v is not None]
    if not values:
        return None
    n = float(len(values))
    below = sum(1 for v in values if v <= 0) / n
    above = sum(1 for v in values if v >= 0) / n
    return min(1.0, 2.0 * min(below, above))


def p_resolution(replicates):
    """The smallest positive two-sided bootstrap p-value over `replicates`
    usable replicate differences: 2 / replicates (one replicate on the
    minority side, bootstrap_p_value). A p-value of 0 means p < this."""
    if isinstance(replicates, bool) or not _is_int(replicates) or replicates < 1:
        raise core.AnalysisRefused("p resolution needs a positive replicate count, got %r" % (replicates,))
    return 2.0 / replicates


def ci_degenerate(ci_low, ci_high):
    """None without an interval, else whether it has zero width (module
    docstring). A half-open interval refuses."""
    if ci_low is None and ci_high is None:
        return None
    if ci_low is None or ci_high is None:
        raise core.AnalysisRefused("interval with one missing bound: %r, %r" % (ci_low, ci_high))
    return ci_low == ci_high


def _holm_order(items, what):
    """Indices of `items` ((key, p) pairs) in the Holm order: ascending p,
    ties in input order (callers pass a deterministic input order)."""
    for key, p in items:
        if p is None or not (0.0 <= p <= 1.0):
            raise core.AnalysisRefused("%s over an invalid p-value for %r: %r" % (what, key, p))
    return sorted(range(len(items)), key=lambda i: (items[i][1], i))


def holm(p_values, alpha=None):
    """Holm step-down: key -> (adjusted p, reject) in the input order.
    Adjusted p_(j) = max_{i <= j} min(1, (m - i + 1) p_(i)) over the
    ascending order (ties keep input order; tied p get identical adjusted
    values); reject iff adjusted p <= alpha, which equals the sequential
    rejection rule. A missing or invalid p refuses."""
    if alpha is None:
        alpha = _frozen_settings()["alpha"]
    items = list(p_values.items())
    order = _holm_order(items, "Holm")
    m = len(items)
    adjusted = [None] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * items[i][1]))
        adjusted[i] = running
    return OrderedDict((items[i][0], (adjusted[i], adjusted[i] <= alpha)) for i in range(m))


def holm_resolution(p_values, resolutions):
    """key -> the resolution of the Holm-adjusted p (addendum_1
    p_holm_resolution), in the input order: over holm()'s order (ascending
    p, ties in input order) the running maximum of (m - rank + 1) *
    resolutions[key], rank 1-based. WHY: the adjusted value of a p = 0
    hypothesis is max_{i <= j} (m - i + 1) p_(i) with every p_(i) only known
    to be below its resolution, so it is only known to be below this bound
    (m * 2 / B for tied zeros). Not clamped at 1 (the addendum's rule; only
    tiny exploratory replicate counts reach 1). Missing resolutions refuse."""
    items = list(p_values.items())
    order = _holm_order(items, "Holm resolution")
    m = len(items)
    out = [None] * m
    running = 0.0
    for rank, i in enumerate(order, 1):
        key = items[i][0]
        resolution = resolutions.get(key)
        if resolution is None or not resolution > 0:
            raise core.AnalysisRefused("Holm resolution without a positive p resolution for %r" % (key,))
        running = max(running, (m - rank + 1) * resolution)
        out[i] = running
    return OrderedDict((items[i][0], out[i]) for i in range(m))


def cohens_kappa(n11, n10, n01, n00):
    """Cohen's kappa of a 2x2 agreement table (exact arithmetic); None when
    the table is empty or chance agreement is 1 (kappa undefined)."""
    counts = (n11, n10, n01, n00)
    if any(c is None or c < 0 for c in counts):
        raise core.AnalysisRefused("invalid 2x2 counts %r" % (counts,))
    n = sum(counts)
    if n == 0:
        return None
    observed = Fraction(n11 + n00, n)
    first = Fraction(n11 + n10, n)
    second = Fraction(n11 + n01, n)
    chance = first * second + (1 - first) * (1 - second)
    if chance == 1:
        return None
    return float((observed - chance) / (1 - chance))


def positive_agreement(n11, n10, n01, n00):
    """2 n11 / (2 n11 + n10 + n01); None when no tool reported a positive."""
    counts = (n11, n10, n01, n00)
    if any(c is None or c < 0 for c in counts):
        raise core.AnalysisRefused("invalid 2x2 counts %r" % (counts,))
    denominator = 2 * n11 + n10 + n01
    if denominator == 0:
        return None
    return float(Fraction(2 * n11, denominator))


# -- cluster bootstrap ---------------------------------------------------------------------

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, float)


class ClusterBootstrap(object):
    """Shared replicate weights of a stratified cluster bootstrap.

    ``cluster_strata``: OrderedDict cluster_id -> stratum (benchmark -> block).
    ``self.weights``: replicates x clusters integer multiplicities (cluster
    order = ``self.clusters``, sorted). ``confidence`` defaults to the frozen
    methodology value."""

    def __init__(self, cluster_strata, replicates, seed, confidence=None):
        if not cluster_strata:
            raise core.AnalysisRefused("a bootstrap needs at least one cluster")
        if not _is_int(replicates) or replicates < 1:
            raise core.AnalysisRefused("replicates must be a positive integer")
        if confidence is None:
            confidence = _frozen_settings()["confidence"]
        if not 0.0 < confidence < 1.0:
            raise core.AnalysisRefused("confidence outside (0, 1)")
        self.clusters = sorted(cluster_strata)
        self.cluster_strata = OrderedDict((c, cluster_strata[c]) for c in self.clusters)
        self.index = OrderedDict((c, i) for i, c in enumerate(self.clusters))
        self.replicates = replicates
        self.seed = seed
        self.confidence = float(confidence)
        self.strata = OrderedDict()
        for stratum in sorted(set(self.cluster_strata.values())):
            self.strata[stratum] = [i for i, c in enumerate(self.clusters) if self.cluster_strata[c] == stratum]
        rng = random.Random(seed)
        weights = []
        for _ in range(replicates):
            row = [0] * len(self.clusters)
            for members in self.strata.values():
                size = len(members)
                for _ in range(size):
                    row[members[rng.randrange(size)]] += 1
            weights.append(row)
        self.weights = weights
        self._max_weight = max(len(m) for m in self.strata.values())
        self._packed = None

    # identity of the resampling design (validate / rerun checks)
    def identity(self):
        return OrderedDict([("clusters", len(self.clusters)),
                            ("strata", OrderedDict((s, len(m)) for s, m in self.strata.items())),
                            ("replicates", self.replicates), ("seed", self.seed),
                            ("confidence", self.confidence)])

    def _columns(self):
        if self._packed is None:
            fmt = "<%dQ" % self.replicates
            self._packed = [int.from_bytes(struct.pack(fmt, *[row[i] for row in self.weights]), "little")
                            for i in range(len(self.clusters))]
        return self._packed

    def _vector(self, per_cluster, position):
        vector = [0] * len(self.clusters)
        for cluster, pair in per_cluster.items():
            if cluster not in self.index:
                raise core.AnalysisRefused("estimate over a cluster outside the bootstrap: %r" % (cluster,))
            vector[self.index[cluster]] = pair[position]
        return vector

    def replicate_sums(self, values):
        """Per replicate: sum over clusters of weight * value (values in
        cluster order). Integer inputs use the packed fast path."""
        nonzero = [i for i, v in enumerate(values) if v]
        if not nonzero:
            return [0] * self.replicates
        if all(_is_int(values[i]) for i in nonzero) and (
                sum(abs(values[i]) for i in nonzero) * self._max_weight < _FIELD_LIMIT):
            columns = self._columns()
            positive = 0
            negative = 0
            for i in nonzero:
                if values[i] > 0:
                    positive += values[i] * columns[i]
                else:
                    negative += -values[i] * columns[i]
            fmt = "<%dQ" % self.replicates
            size = 8 * self.replicates
            plus = struct.unpack(fmt, positive.to_bytes(size, "little"))
            if not negative:
                return list(plus)
            minus = struct.unpack(fmt, negative.to_bytes(size, "little"))
            return [a - b for a, b in zip(plus, minus)]
        return self.plain_sums(values)

    def plain_sums(self, values):
        """Reference implementation: sum(w * x for ...) per replicate."""
        nonzero = [i for i, v in enumerate(values) if v]
        return [sum(row[i] * values[i] for i in nonzero) for row in self.weights]

    def replicate_values(self, per_cluster):
        """Per replicate the weighted ratio of sums (None where the weighted
        denominator is 0), aligned with the replicate index."""
        numerators = self.replicate_sums(self._vector(per_cluster, 0))
        denominators = self.replicate_sums(self._vector(per_cluster, 1))
        return [(n / d if d != 0 else None) for n, d in zip(numerators, denominators)]

    def support(self, per_cluster):
        """(clusters, estimable, ci_note) of one estimate: the number of
        clusters that carry its data (a non-zero component), whether a
        percentile interval is estimable (module docstring) and the note
        explaining a missing interval or flagging a stratum in which only one
        cluster carries the estimate (None when there is nothing to say)."""
        carrying = []
        for cluster, pair in per_cluster.items():
            if cluster not in self.index:
                raise core.AnalysisRefused("estimate over a cluster outside the bootstrap: %r" % (cluster,))
            if any(pair):
                carrying.append(cluster)
        if len(carrying) < MIN_SUPPORT:
            return len(carrying), False, (
                "CI not estimable: the estimate rests on %d benchmark cluster(s) (a ratio over one cluster is "
                "invariant to its bootstrap weight)" % len(carrying))
        per_stratum = OrderedDict()
        for cluster in carrying:
            stratum = self.cluster_strata[cluster]
            per_stratum[stratum] = per_stratum.get(stratum, 0) + 1
        fixed = [s for s in sorted(per_stratum) if len(self.strata[s]) < MIN_SUPPORT]
        if fixed:
            return len(carrying), False, (
                "CI not estimable: supporting cluster(s) in single-cluster bootstrap stratum %s (never resampled)"
                % ", ".join(fixed))
        single = [s for s in sorted(per_stratum) if per_stratum[s] == 1]
        note = None
        if single:
            note = "only 1 supporting benchmark cluster in bootstrap stratum %s" % ", ".join(single)
        return len(carrying), True, note

    def _summary(self, numerator, denominator, replicate_values, support):
        clusters, estimable, note = support
        out = OrderedDict([("value", None), ("ci_low", None), ("ci_high", None), ("replicates", 0),
                           ("numerator", numerator), ("denominator", denominator), ("degenerate", False),
                           ("skipped", 0), ("clusters", clusters), ("ci_note", None), ("ci_degenerate", None)])
        if denominator == 0:
            return out
        out["value"] = numerator / denominator
        out["ci_note"] = note
        if not estimable:
            return out
        usable = [v for v in replicate_values if v is not None]
        out["replicates"] = len(usable)
        out["skipped"] = self.replicates - len(usable)
        out["degenerate"] = out["skipped"] > 0           # skipped replicates (zero weighted denominator)
        out["ci_low"], out["ci_high"] = interval(usable, self.confidence)
        out["ci_degenerate"] = ci_degenerate(out["ci_low"], out["ci_high"])     # zero width
        return out

    def _ratio(self, per_cluster):
        """(summary, replicate values, interval estimable); replicate values
        are only computed for an estimable interval."""
        support = self.support(per_cluster)
        numerator = sum(pair[0] for pair in per_cluster.values())
        denominator = sum(pair[1] for pair in per_cluster.values())
        estimable = denominator != 0 and support[1]
        values = self.replicate_values(per_cluster) if estimable else []
        return self._summary(numerator, denominator, values, support), values, estimable

    def ratio(self, per_cluster):
        """per_cluster: {cluster: (num, den)} (absent cluster = (0, 0))."""
        return self._ratio(per_cluster)[0]

    def difference(self, per_cluster):
        """Paired difference: {cluster: (sum of per-unit differences, units)};
        as ratio() plus the two-sided bootstrap p-value of the difference
        (over the same non-degenerate replicates as the interval; None when
        the interval is not estimable)."""
        out, values, estimable = self._ratio(per_cluster)
        out["p_value"] = bootstrap_p_value(values) if estimable else None
        return out

    def ratio_difference(self, per_cluster_a, per_cluster_b):
        """ratio(a) - ratio(b) with the SAME resamples (unpaired units, shared
        clusters); a replicate is skipped when either ratio is undefined. No
        interval unless BOTH ratios have an estimable one (a ratio resting
        on one cluster is constant over the replicates, so the interval
        would only reflect the other ratio)."""
        a, values_a, estimable_a = self._ratio(per_cluster_a)
        b, values_b, estimable_b = self._ratio(per_cluster_b)
        out = OrderedDict([("value", None), ("ci_low", None), ("ci_high", None), ("replicates", 0),
                           ("numerator", a["numerator"]), ("denominator", a["denominator"]),
                           ("reference_numerator", b["numerator"]), ("reference_denominator", b["denominator"]),
                           ("degenerate", False), ("skipped", 0), ("clusters", a["clusters"]),
                           ("reference_clusters", b["clusters"]), ("ci_note", None), ("ci_degenerate", None)])
        if a["value"] is None or b["value"] is None:
            return out
        out["value"] = a["value"] - b["value"]
        notes = [n for n in (a["ci_note"], "reference: " + b["ci_note"] if b["ci_note"] else None) if n]
        out["ci_note"] = "; ".join(notes) if notes else None
        if not (estimable_a and estimable_b):
            return out
        diffs = [x - y for x, y in zip(values_a, values_b) if x is not None and y is not None]
        out["replicates"] = len(diffs)
        out["skipped"] = self.replicates - len(diffs)
        out["degenerate"] = out["skipped"] > 0
        out["ci_low"], out["ci_high"] = interval(diffs, self.confidence)
        out["ci_degenerate"] = ci_degenerate(out["ci_low"], out["ci_high"])
        return out
