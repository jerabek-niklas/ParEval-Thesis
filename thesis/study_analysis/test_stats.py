"""Unit tests of stats.py on hand-computable fixtures (no repository data
except the frozen methodology's bootstrap settings).

    python3 -B -m unittest -v thesis.study_analysis.test_stats
"""
from __future__ import annotations

import random
import unittest
from collections import OrderedDict

from thesis.study_analysis import core, stats

SEED = 20261017
CONF = 0.95


def strata(**sizes):
    """OrderedDict cluster -> stratum with `size` clusters per stratum."""
    out = OrderedDict()
    for stratum, size in sorted(sizes.items()):
        for i in range(size):
            out["%s_%02d" % (stratum, i)] = stratum
    return out


class PercentileTest(unittest.TestCase):

    def test_type7_known_values(self):
        values = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(stats.percentile(values, 0.0), 1.0)
        self.assertEqual(stats.percentile(values, 1.0), 4.0)
        self.assertAlmostEqual(stats.percentile(values, 0.5), 2.5)
        self.assertAlmostEqual(stats.percentile(values, 0.25), 1.75)      # numpy default (linear)
        self.assertAlmostEqual(stats.percentile(values, 0.9), 3.7)
        self.assertEqual(stats.percentile([7], 0.3), 7)

    def test_percentile_refuses(self):
        with self.assertRaises(core.AnalysisRefused):
            stats.percentile([], 0.5)
        with self.assertRaises(core.AnalysisRefused):
            stats.percentile([2, 1], 0.5)
        with self.assertRaises(core.AnalysisRefused):
            stats.percentile([1, 2], 1.5)

    def test_median_quantile(self):
        self.assertEqual(stats.median([3, 1, 2]), 2)
        self.assertAlmostEqual(stats.median([4, 1, 3, 2]), 2.5)
        self.assertIsNone(stats.median([]))
        self.assertAlmostEqual(stats.quantile(list(range(1, 101)), 0.95), 95.05)
        with self.assertRaises(core.AnalysisRefused):
            stats.quantile([1, None], 0.5)


class TestsAndAgreementTest(unittest.TestCase):

    def test_bootstrap_p_value(self):
        self.assertAlmostEqual(stats.bootstrap_p_value([-1, 1, 2, 3]), 0.5)
        self.assertEqual(stats.bootstrap_p_value([1, 2, 3]), 0.0)
        self.assertEqual(stats.bootstrap_p_value([0, 0, 0]), 1.0)       # ties count on both sides, clamped
        self.assertAlmostEqual(stats.bootstrap_p_value([-2, -1, None, 1]), 2.0 / 3.0)   # None skipped
        self.assertIsNone(stats.bootstrap_p_value([None, None]))

    def test_holm_known_values_and_monotonicity(self):
        p = OrderedDict([("a", 0.01), ("b", 0.04), ("c", 0.03), ("d", 0.005)])
        adjusted = stats.holm(p, 0.05)
        self.assertEqual(list(adjusted), ["a", "b", "c", "d"])                 # input order kept
        self.assertAlmostEqual(adjusted["d"][0], 0.02)
        self.assertAlmostEqual(adjusted["a"][0], 0.03)
        self.assertAlmostEqual(adjusted["c"][0], 0.06)
        self.assertAlmostEqual(adjusted["b"][0], 0.06)                         # running max
        self.assertEqual([adjusted[k][1] for k in "abcd"], [True, False, False, True])
        order = sorted(p, key=lambda k: p[k])
        values = [adjusted[k][0] for k in order]
        self.assertEqual(values, sorted(values))                               # monotone in p
        for k in p:
            self.assertGreaterEqual(adjusted[k][0], p[k])

    def test_holm_ties_and_clamp(self):
        adjusted = stats.holm(OrderedDict([("x", 0.02), ("y", 0.02), ("z", 0.9)]), 0.05)
        self.assertAlmostEqual(adjusted["x"][0], 0.06)
        self.assertAlmostEqual(adjusted["y"][0], 0.06)
        self.assertAlmostEqual(adjusted["z"][0], 0.9)
        self.assertEqual(stats.holm(OrderedDict([("u", 0.4), ("v", 0.45)]), 0.05)["u"][0], 0.8)
        self.assertEqual(stats.holm(OrderedDict([("u", 0.6), ("v", 0.7)]), 0.05)["u"][0], 1.0)   # clamped
        self.assertFalse(any(r for _, r in adjusted.values()))

    def test_holm_refuses_missing_p(self):
        with self.assertRaises(core.AnalysisRefused):
            stats.holm(OrderedDict([("a", None)]), 0.05)

    def test_p_resolution(self):
        self.assertEqual(stats.p_resolution(10000), 2.0 / 10000)
        self.assertAlmostEqual(stats.p_resolution(10000), 0.0002)
        self.assertEqual(stats.p_resolution(4), 0.5)
        # the smallest positive p over n replicates: one replicate on the minority side
        self.assertEqual(stats.bootstrap_p_value([-1] + [1] * 9), stats.p_resolution(10))
        for bad in (0, -3, 2.5, None, True):
            with self.assertRaises(core.AnalysisRefused):
                stats.p_resolution(bad)

    def test_holm_resolution_tied_zeros(self):
        """Twelve tied p = 0 at B = 10,000: the Holm-adjusted p is 0 but only
        known to be below 12 * 2 / B = 0.0024 (not 2 / B)."""
        keys = ["h%02d" % i for i in range(12)]
        p = OrderedDict((k, 0.0) for k in keys)
        res = OrderedDict((k, stats.p_resolution(10000)) for k in keys)
        bounds = stats.holm_resolution(p, res)
        self.assertEqual(list(bounds), keys)
        self.assertEqual(bounds["h00"], 12 * (2.0 / 10000))                  # first in the Holm order
        self.assertAlmostEqual(bounds["h00"], 0.0024)
        self.assertEqual(set(bounds.values()), {12 * (2.0 / 10000)})            # running maximum
        self.assertTrue(all(adj == 0.0 for adj, _ in stats.holm(p, 0.05).values()))

    def test_holm_resolution_order_and_running_max(self):
        p = OrderedDict([("a", 0.0), ("b", 0.0), ("c", 0.01), ("d", 0.2)])
        res = OrderedDict([("a", 0.01), ("b", 0.05), ("c", 0.01), ("d", 0.01)])
        bounds = stats.holm_resolution(p, res)
        self.assertAlmostEqual(bounds["a"], 4 * 0.01)                          # rank 1
        self.assertAlmostEqual(bounds["b"], 3 * 0.05)                          # rank 2: max(0.04, 0.15)
        self.assertAlmostEqual(bounds["c"], 3 * 0.05)                          # running max
        self.assertAlmostEqual(bounds["d"], 3 * 0.05)
        # ties keep the input order (the caller passes metrics.sort_key order): b first now
        swapped = stats.holm_resolution(OrderedDict([("b", 0.0), ("a", 0.0), ("c", 0.01), ("d", 0.2)]), res)
        self.assertAlmostEqual(swapped["b"], 4 * 0.05)
        self.assertAlmostEqual(swapped["a"], 4 * 0.05)
        self.assertEqual(list(swapped), ["b", "a", "c", "d"])
        # not clamped at 1 (the addendum's rule; only tiny exploratory replicate counts get there)
        tiny = stats.holm_resolution(OrderedDict((k, 0.0) for k in "xyz"), OrderedDict((k, 0.5) for k in "xyz"))
        self.assertEqual(tiny["x"], 1.5)
        with self.assertRaises(core.AnalysisRefused):
            stats.holm_resolution(OrderedDict([("a", 0.0)]), OrderedDict())
        with self.assertRaises(core.AnalysisRefused):
            stats.holm_resolution(OrderedDict([("a", None)]), OrderedDict([("a", 0.1)]))

    def test_ci_degenerate(self):
        self.assertIsNone(stats.ci_degenerate(None, None))
        self.assertTrue(stats.ci_degenerate(1.0, 1.0))
        self.assertTrue(stats.ci_degenerate(0.0, 0.0))
        self.assertFalse(stats.ci_degenerate(0.1, 0.2))
        with self.assertRaises(core.AnalysisRefused):
            stats.ci_degenerate(None, 0.2)

    def test_kappa_and_positive_agreement(self):
        self.assertAlmostEqual(stats.cohens_kappa(20, 5, 10, 15), 0.4)
        self.assertAlmostEqual(stats.positive_agreement(20, 5, 10, 15), 40.0 / 55.0)
        self.assertEqual(stats.cohens_kappa(5, 0, 0, 5), 1.0)
        self.assertAlmostEqual(stats.cohens_kappa(0, 5, 5, 0), -1.0)
        self.assertIsNone(stats.cohens_kappa(0, 0, 0, 0))
        self.assertIsNone(stats.cohens_kappa(7, 0, 0, 0))          # chance agreement 1
        self.assertIsNone(stats.positive_agreement(0, 0, 0, 9))
        with self.assertRaises(core.AnalysisRefused):
            stats.cohens_kappa(-1, 0, 0, 0)

    def test_methodology_settings(self):
        settings = stats.bootstrap_settings(core.load_methodology())
        self.assertEqual(settings["alpha"], 0.05)
        self.assertEqual(settings["primary_hypotheses"], 12)
        self.assertEqual(settings["confidence"], 0.95)
        self.assertEqual(settings["replicates_primary"], 10000)
        self.assertEqual(settings["replicates_descriptive"], 2000)
        self.assertEqual(settings["seed"], SEED)


class ClusterBootstrapTest(unittest.TestCase):

    def test_deterministic_and_seed_sensitive(self):
        clusters = strata(full_ext=6, pilot=3)
        first = stats.ClusterBootstrap(clusters, 50, SEED, CONF)
        second = stats.ClusterBootstrap(OrderedDict(reversed(list(clusters.items()))), 50, SEED, CONF)
        self.assertEqual(first.weights, second.weights)                       # cluster order irrelevant
        self.assertEqual(first.clusters, sorted(clusters))
        other = stats.ClusterBootstrap(clusters, 50, SEED + 1, CONF)
        self.assertNotEqual(first.weights, other.weights)

    def test_draw_order_replicate_major_strata_sorted(self):
        clusters = strata(full_ext=4, pilot=2)
        boot = stats.ClusterBootstrap(clusters, 3, SEED, CONF)
        rng = random.Random(SEED)
        index = {c: i for i, c in enumerate(sorted(clusters))}
        members = OrderedDict((s, [index[c] for c in sorted(clusters) if clusters[c] == s])
                              for s in sorted(set(clusters.values())))
        for row in boot.weights:
            expected = [0] * len(clusters)
            for stratum in members.values():
                for _ in range(len(stratum)):
                    expected[stratum[rng.randrange(len(stratum))]] += 1
            self.assertEqual(row, expected)

    def test_weights_stay_within_strata(self):
        clusters = strata(full_ext=5, pilot=3)
        boot = stats.ClusterBootstrap(clusters, 200, SEED, CONF)
        pilot = [i for i, c in enumerate(boot.clusters) if clusters[c] == "pilot"]
        full = [i for i, c in enumerate(boot.clusters) if clusters[c] == "full_ext"]
        for row in boot.weights:
            self.assertEqual(sum(row[i] for i in pilot), 3)
            self.assertEqual(sum(row[i] for i in full), 5)
            self.assertTrue(all(isinstance(w, int) and w >= 0 for w in row))

    def test_known_ratio_and_constant_interval(self):
        clusters = strata(a=4)
        boot = stats.ClusterBootstrap(clusters, 100, SEED, CONF)
        per = OrderedDict((c, (2, 4)) for c in clusters)                     # every cluster 0.5
        res = boot.ratio(per)
        self.assertEqual((res["numerator"], res["denominator"]), (8, 16))
        self.assertEqual(res["value"], 0.5)
        self.assertEqual((res["ci_low"], res["ci_high"]), (0.5, 0.5))
        self.assertEqual(res["replicates"], 100)
        self.assertFalse(res["degenerate"])                  # no skipped replicate ...
        self.assertTrue(res["ci_degenerate"])                # ... but a zero-width interval

    def test_zero_width_flag_at_the_boundary(self):
        """Regression (review): every supporting cluster at 100% gives the
        percentile 'interval' [1, 1]; it is flagged, not presented as certain."""
        clusters = strata(full_ext=4, pilot=3)
        boot = stats.ClusterBootstrap(clusters, 200, SEED, CONF)
        full = boot.ratio(OrderedDict((c, (3, 3)) for c in clusters))
        self.assertEqual((full["value"], full["ci_low"], full["ci_high"], full["ci_degenerate"]), (1.0, 1.0, 1.0, True))
        none = boot.difference(OrderedDict((c, (0, 5)) for c in clusters))
        self.assertTrue(none["ci_degenerate"])
        rng = random.Random(4)
        varied = boot.ratio(OrderedDict((c, (rng.randint(0, 9), 9)) for c in clusters))
        self.assertLess(varied["ci_low"], varied["ci_high"])
        self.assertFalse(varied["ci_degenerate"])
        single = boot.ratio(OrderedDict([(sorted(clusters)[0], (2, 3))]))
        self.assertIsNone(single["ci_degenerate"])            # no interval at all
        self.assertIsNone(boot.ratio(OrderedDict())["ci_degenerate"])
        same = boot.ratio_difference(OrderedDict((c, (3, 4)) for c in clusters),
                                     OrderedDict((c, (1, 4)) for c in clusters))
        self.assertTrue(same["ci_degenerate"])
        mixed = boot.ratio_difference(OrderedDict((c, (i % 4, 4)) for i, c in enumerate(sorted(clusters))),
                                      OrderedDict((c, (1, 4)) for c in clusters))
        self.assertFalse(mixed["ci_degenerate"])
        self.assertIsNone(boot.ratio_difference(OrderedDict([(sorted(clusters)[0], (1, 2))]),
                                                OrderedDict((c, (1, 4)) for c in clusters))["ci_degenerate"])

    def test_ratio_of_sums_not_mean_of_rates(self):
        clusters = strata(a=2)
        boot = stats.ClusterBootstrap(clusters, 20, SEED, CONF)
        names = sorted(clusters)
        res = boot.ratio(OrderedDict([(names[0], (1, 1)), (names[1], (0, 9))]))
        self.assertAlmostEqual(res["value"], 0.1)                             # not (1 + 0) / 2
        values = boot.replicate_values(OrderedDict([(names[0], (1, 1)), (names[1], (0, 9))]))
        for row, value in zip(boot.weights, values):
            self.assertAlmostEqual(value, row[0] * 1.0 / (row[0] * 1 + row[1] * 9))

    def test_interval_brackets_and_reproduces(self):
        clusters = strata(full_ext=8, pilot=4)
        rng = random.Random(3)
        per = OrderedDict((c, (rng.randint(0, 10), 10)) for c in clusters)
        a = stats.ClusterBootstrap(clusters, 500, SEED, CONF).ratio(per)
        b = stats.ClusterBootstrap(clusters, 500, SEED, CONF).ratio(per)
        self.assertEqual(a, b)
        self.assertLessEqual(a["ci_low"], a["value"])
        self.assertGreaterEqual(a["ci_high"], a["value"])

    def test_degenerate_denominators(self):
        clusters = strata(a=3)
        boot = stats.ClusterBootstrap(clusters, 300, SEED, CONF)
        names = sorted(clusters)
        res = boot.ratio(OrderedDict([(names[0], (1, 2)), (names[1], (1, 4))]))     # third cluster (0, 0)
        expected_skips = sum(1 for row in boot.weights if row[0] == 0 and row[1] == 0)
        self.assertGreater(expected_skips, 0)
        self.assertTrue(res["degenerate"])
        self.assertEqual(res["skipped"], expected_skips)
        self.assertEqual(res["replicates"], 300 - expected_skips)
        self.assertAlmostEqual(res["value"], 2.0 / 6.0)
        self.assertEqual(res["clusters"], 2)
        empty = boot.ratio(OrderedDict([(names[0], (0, 0))]))
        self.assertIsNone(empty["value"])
        self.assertIsNone(empty["ci_low"])
        self.assertIsNone(empty["ci_high"])
        self.assertEqual(boot.ratio(OrderedDict())["denominator"], 0)

    def test_single_cluster_estimate_has_no_interval(self):
        """Regression: a ratio resting on ONE cluster is invariant to its
        weight; the old code published a zero-width 'interval' for it."""
        clusters = strata(full_ext=6, pilot=4)
        boot = stats.ClusterBootstrap(clusters, 400, SEED, CONF)
        only = sorted(c for c in clusters if clusters[c] == "pilot")[0]
        per = OrderedDict([(only, (21, 27))])
        values = [v for v in boot.replicate_values(per) if v is not None]
        self.assertEqual(set(values), {21 / 27.0})                       # why: every replicate == the estimate
        res = boot.ratio(per)
        self.assertAlmostEqual(res["value"], 21 / 27.0)
        self.assertEqual((res["ci_low"], res["ci_high"], res["replicates"], res["clusters"]), (None, None, 0, 1))
        self.assertIn("CI not estimable", res["ci_note"])
        self.assertFalse(res["degenerate"])
        diff = boot.difference(OrderedDict([(only, (3, 9))]))
        self.assertAlmostEqual(diff["value"], 1 / 3.0)
        self.assertIsNone(diff["p_value"])
        self.assertIsNone(diff["ci_low"])
        both = boot.ratio_difference(per, OrderedDict((c, (1, 4)) for c in clusters))
        self.assertAlmostEqual(both["value"], 21 / 27.0 - 0.25)
        self.assertIsNone(both["ci_low"])                                # one side rests on one cluster
        self.assertIn("CI not estimable", both["ci_note"])
        reverse = boot.ratio_difference(OrderedDict((c, (1, 4)) for c in clusters), per)
        self.assertIsNone(reverse["ci_low"])
        self.assertTrue(reverse["ci_note"].startswith("reference: CI not estimable"))

    def test_singleton_stratum_is_never_resampled(self):
        clusters = strata(full_ext=4, pilot=1)
        boot = stats.ClusterBootstrap(clusters, 200, SEED, CONF)
        pilot = [c for c in clusters if clusters[c] == "pilot"][0]
        full = sorted(c for c in clusters if clusters[c] == "full_ext")
        self.assertTrue(all(row[boot.index[pilot]] == 1 for row in boot.weights))
        mixed = boot.ratio(OrderedDict([(pilot, (1, 3)), (full[0], (2, 3))]))
        self.assertIsNone(mixed["ci_low"])
        self.assertIn("single-cluster bootstrap stratum pilot", mixed["ci_note"])
        inside = boot.ratio(OrderedDict([(full[0], (1, 3)), (full[1], (2, 3))]))
        self.assertIsNotNone(inside["ci_low"])
        self.assertIsNone(inside["ci_note"])

    def test_one_carrying_cluster_in_a_stratum_is_flagged(self):
        clusters = strata(full_ext=6, pilot=4)
        boot = stats.ClusterBootstrap(clusters, 300, SEED, CONF)
        pilot = sorted(c for c in clusters if clusters[c] == "pilot")
        full = sorted(c for c in clusters if clusters[c] == "full_ext")
        per = OrderedDict([(pilot[0], (5, 9))] + [(c, (i, 9)) for i, c in enumerate(full)])
        res = boot.ratio(per)
        self.assertLess(res["ci_low"], res["ci_high"])                   # the pilot weight still varies
        self.assertEqual(res["clusters"], 7)
        self.assertEqual(res["ci_note"], "only 1 supporting benchmark cluster in bootstrap stratum pilot")

    def test_packed_sums_equal_plain_sums(self):
        clusters = strata(full_ext=9, pilot=4)
        boot = stats.ClusterBootstrap(clusters, 257, SEED, CONF)
        rng = random.Random(11)
        for _ in range(20):
            values = [rng.choice([0, 0, rng.randint(-50, 50), rng.randint(0, 10 ** 6)]) for _ in clusters]
            self.assertEqual(boot.replicate_sums(values), boot.plain_sums(values))
        floats = [0.5 * i for i in range(len(clusters))]
        self.assertEqual(boot.replicate_sums(floats), boot.plain_sums(floats))
        huge = [2 ** 62] + [0] * (len(clusters) - 1)                         # beyond the packed bound
        self.assertEqual(boot.replicate_sums(huge), boot.plain_sums(huge))

    def test_difference_and_p_value(self):
        clusters = strata(a=10)
        boot = stats.ClusterBootstrap(clusters, 400, SEED, CONF)
        positive = boot.difference(OrderedDict((c, (3, 10)) for c in clusters))
        self.assertAlmostEqual(positive["value"], 0.3)
        self.assertEqual(positive["p_value"], 0.0)
        null = boot.difference(OrderedDict((c, (0, 10)) for c in clusters))
        self.assertEqual(null["value"], 0.0)
        self.assertEqual(null["p_value"], 1.0)
        mixed = boot.difference(OrderedDict((c, (1 if i % 2 else -1, 5)) for i, c in enumerate(sorted(clusters))))
        self.assertEqual(mixed["value"], 0.0)
        self.assertGreater(mixed["p_value"], 0.05)
        self.assertLessEqual(mixed["ci_low"], 0.0)
        self.assertGreaterEqual(mixed["ci_high"], 0.0)

    def test_ratio_difference_shares_resamples(self):
        clusters = strata(a=5)
        boot = stats.ClusterBootstrap(clusters, 100, SEED, CONF)
        a = OrderedDict((c, (3, 4)) for c in clusters)
        b = OrderedDict((c, (1, 4)) for c in clusters)
        res = boot.ratio_difference(a, b)
        self.assertAlmostEqual(res["value"], 0.5)
        self.assertAlmostEqual(res["ci_low"], 0.5)
        self.assertAlmostEqual(res["ci_high"], 0.5)
        self.assertEqual((res["reference_numerator"], res["reference_denominator"]), (5, 20))

    def test_unknown_cluster_and_bad_arguments_refuse(self):
        boot = stats.ClusterBootstrap(strata(a=2), 5, SEED, CONF)
        with self.assertRaises(core.AnalysisRefused):
            boot.ratio(OrderedDict([("zzz", (1, 1))]))
        with self.assertRaises(core.AnalysisRefused):
            stats.ClusterBootstrap(OrderedDict(), 5, SEED, CONF)
        with self.assertRaises(core.AnalysisRefused):
            stats.ClusterBootstrap(strata(a=2), 0, SEED, CONF)
        with self.assertRaises(core.AnalysisRefused):
            stats.ClusterBootstrap(strata(a=2), 5, SEED, 1.5)

    def test_default_confidence_is_frozen(self):
        boot = stats.ClusterBootstrap(strata(a=2), 3, SEED)
        self.assertEqual(boot.confidence, 0.95)


if __name__ == "__main__":
    unittest.main()
