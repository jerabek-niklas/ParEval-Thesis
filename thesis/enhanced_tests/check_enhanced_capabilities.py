#!/usr/bin/env python3
"""Read-only consistency checker for thesis/enhanced_tests/enhanced_capabilities.json.

The catalog is AUDIT METADATA (status AUDIT_ONLY_NOT_ENFORCED): nothing in the
productive spec pipeline reads it. This checker verifies its INTERNAL
CONSISTENCY only — it never re-judges the technical findings and contains no
semantic heuristics.

The catalog separates four axes that must never substitute for one another:

    fill_type_safe          is producing/assigning the pattern value into the
                            input container C++-safe? (conversion layer only)
    domain_valid            is the produced input inside the benchmark's frozen
                            input domain? (independent of type representability)
    oracle_execution_safe   can the frozen oracle run on it without C/C++ UB?
                            IEEE Inf/NaN is NOT UB and stays true here.
    verdict_outcome_class   what happens to the COUNTED evaluation result?
                            INFORMATIVE / REDUCED / VACUOUS_PASS /
                            NO_VERDICT_BI / FALSE_FAIL_RISK / UNKNOWN

Checks performed (structural only):
  1  exactly 60 benchmarks, unique ids
  2  required top-level and per-benchmark fields present
  3  all axis fields use the normalized vocabulary (no bare "none")
  4  all eleven pattern keys present per benchmark
  5  pattern_effect NONE/NOT_APPLICABLE => no pattern claims EFFECTIVE
  6  oracle_execution_safe false => recommendation is not an unqualified KEEP
  7  verdict NO_VERDICT_BI => baseline_gate_only_risk is not false
  8  verdict VACUOUS_PASS => recommendation is not an unqualified KEEP
  9  verdict FALSE_FAIL_RISK => recommendation is not an unqualified KEEP
 10  verdict INFORMATIVE => no contradicting axis on the same entry
     (fill_type_safe/oracle_execution_safe false, baseline_gate_only_risk true)
 11  VACUOUS_PASS carries evidence (a cited source location in notes/conditions)
 12  type_unsafe fill-site summary is exactly the set of sites whose
     fill_type_safe is false (an oracle hazard must not appear there)
 13  every summary count is reproducible from the detail data
 14  verdict_outcome_class UNKNOWN carries verdict_outcome_conditions

Exit codes: 0 = consistent, 1 = contradictions found, 2 = infrastructure error.
Read-only: this script writes nothing.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

CATALOG = Path(__file__).resolve().parent / "enhanced_capabilities.json"

PATTERNS = ("random", "all_zeros", "all_same", "ascending", "descending",
            "alternating", "extreme_values", "duplicate_at",
            "sorted_except_one", "spike_at", "explicit_values")

TRISTATE = (True, False, "conditional", "UNKNOWN", "NOT_APPLICABLE")

VERDICT_CLASSES = ("INFORMATIVE", "REDUCED", "VACUOUS_PASS", "NO_VERDICT_BI",
                   "FALSE_FAIL_RISK", "UNKNOWN")

EFFECT_VALUES = ("EFFECTIVE", "PARTIAL", "NONE", "NOT_APPLICABLE", "UNKNOWN")

AXIS_FIELDS = ("fill_type_safe", "domain_valid", "oracle_execution_safe",
               "sentinel_collision", "baseline_gate_only_risk")

# a recommendation counts as QUALIFIED when it is not a bare keep, i.e. it either
# names a different action or carries a parenthetical/qualifying clause
KEEP_RE = re.compile(r"^\s*KEEP_CANDIDATE\s*$", re.IGNORECASE)

# "cited evidence" = something that looks like a source reference
EVIDENCE_RE = re.compile(r"(\.py|\.cc|\.hpp|:\d+)")


class Report:
    def __init__(self):
        self.errors = []
        self.checked = 0

    def fail(self, check, where, message):
        self.errors.append((check, where, message))

    def ok(self):
        return not self.errors


def is_unqualified_keep(text):
    return bool(KEEP_RE.match(str(text or "")))


def check_catalog(doc, rep):
    # --- 1/2 structure -----------------------------------------------------
    if doc.get("status") != "AUDIT_ONLY_NOT_ENFORCED":
        rep.fail("2-status", "<root>",
                 "status must stay AUDIT_ONLY_NOT_ENFORCED, got %r"
                 % doc.get("status"))

    benchmarks = doc.get("benchmarks") or []
    if len(benchmarks) != 60:
        rep.fail("1-count", "<root>", "expected 60 benchmarks, got %d" % len(benchmarks))

    ids = [b.get("benchmark") for b in benchmarks]
    dupes = [k for k, v in Counter(ids).items() if v > 1]
    if dupes:
        rep.fail("1-unique", "<root>", "duplicate benchmark ids: %s" % dupes)

    required = ("benchmark", "size_override_effect", "pattern_effect",
                "pattern_source", "large_size_status", "e2_actions",
                "fill_sites", "pattern_audit", "domain")
    unsafe_sites_detail = []
    verdict_counter = Counter()
    conditional_cases = 0
    oracle_unsafe_cases = []
    domain_invalid_cases = 0
    bi_cases = 0
    site_total = 0
    site_safe = site_unsafe = site_unknown = site_conditional = 0
    fill_unsafe_cases = []
    fill_conditional_cases = 0

    for bench in benchmarks:
        name = bench.get("benchmark", "<unnamed>")

        for field in required:
            if field not in bench:
                rep.fail("2-fields", name, "missing field %r" % field)

        if bench.get("pattern_effect") not in EFFECT_VALUES:
            rep.fail("3-enum", name, "pattern_effect %r invalid"
                     % bench.get("pattern_effect"))
        if bench.get("size_override_effect") not in EFFECT_VALUES:
            rep.fail("3-enum", name, "size_override_effect %r invalid"
                     % bench.get("size_override_effect"))

        # --- fill sites ----------------------------------------------------
        for site in bench.get("fill_sites") or []:
            site_total += 1
            value = site.get("fill_type_safe")
            if value not in TRISTATE:
                rep.fail("3-enum", name,
                         "fill_sites.fill_type_safe %r invalid (line %s)"
                         % (value, site.get("line")))
            if value is False:
                site_unsafe += 1
                unsafe_sites_detail.append((name, site.get("line")))
            elif value is True:
                site_safe += 1
            elif value == "conditional":
                site_conditional += 1
            else:
                site_unknown += 1
            if "type_safe" in site:
                rep.fail("3-vocab", name,
                         "fill site line %s still carries the ambiguous legacy "
                         "field 'type_safe'; use fill_type_safe"
                         % site.get("line"))

        # --- pattern audit -------------------------------------------------
        audit = bench.get("pattern_audit") or {}
        missing = [p for p in PATTERNS if p not in audit]
        if missing:
            rep.fail("4-patterns", name, "pattern_audit missing keys: %s" % missing)

        bench_effect = bench.get("pattern_effect")

        for pattern, entry in audit.items():
            rep.checked += 1
            where = "%s / %s" % (name, pattern)

            for field in AXIS_FIELDS:
                if field not in entry:
                    rep.fail("2-fields", where, "missing axis field %r" % field)
                elif entry[field] not in TRISTATE:
                    rep.fail("3-enum", where,
                             "%s = %r is not one of true/false/'conditional'/"
                             "'UNKNOWN'/'NOT_APPLICABLE'" % (field, entry[field]))

            effect = entry.get("current_technical_effect")
            if effect not in EFFECT_VALUES:
                rep.fail("3-enum", where,
                         "current_technical_effect %r invalid" % effect)

            verdict = entry.get("verdict_outcome_class")
            if verdict not in VERDICT_CLASSES:
                rep.fail("3-enum", where,
                         "verdict_outcome_class %r invalid" % verdict)
                continue

            verdict_counter[verdict] += 1
            conditions = entry.get("verdict_outcome_conditions") or []
            if conditions:
                conditional_cases += 1

            recommendation = entry.get("recommendation_for_e2", "")
            notes = str(entry.get("notes", ""))

            # --- 5: no EFFECTIVE claim on a benchmark without pattern effect
            if bench_effect in ("NONE", "NOT_APPLICABLE") and effect == "EFFECTIVE":
                rep.fail("5-effect", where,
                         "benchmark pattern_effect is %s but the pattern claims "
                         "EFFECTIVE" % bench_effect)

            # --- 6: oracle-unsafe must not be an unqualified keep
            if entry.get("oracle_execution_safe") is False:
                oracle_unsafe_cases.append(where)
                if is_unqualified_keep(recommendation):
                    rep.fail("6-oracle-keep", where,
                             "oracle_execution_safe=false with unqualified "
                             "KEEP_CANDIDATE")

            if entry.get("fill_type_safe") is False:
                fill_unsafe_cases.append(where)
            elif entry.get("fill_type_safe") == "conditional":
                fill_conditional_cases += 1

            if entry.get("domain_valid") is False:
                domain_invalid_cases += 1

            if entry.get("baseline_gate_only_risk") is True:
                bi_cases += 1

            # --- 7: deterministic BI must not claim no gate risk
            if verdict == "NO_VERDICT_BI" and entry.get("baseline_gate_only_risk") is False:
                rep.fail("7-bi-gate", where,
                         "verdict NO_VERDICT_BI but baseline_gate_only_risk=false")

            # --- 8/9: biasing outcomes must not be an unqualified keep
            if verdict in ("VACUOUS_PASS", "FALSE_FAIL_RISK") and is_unqualified_keep(recommendation):
                rep.fail("8/9-keep", where,
                         "verdict %s with unqualified KEEP_CANDIDATE" % verdict)

            # --- 10: INFORMATIVE must not contradict its own axes
            if verdict == "INFORMATIVE":
                if entry.get("oracle_execution_safe") is False:
                    rep.fail("10-informative", where,
                             "INFORMATIVE but oracle_execution_safe=false")
                if entry.get("fill_type_safe") is False:
                    rep.fail("10-informative", where,
                             "INFORMATIVE but fill_type_safe=false")
                if entry.get("baseline_gate_only_risk") is True:
                    rep.fail("10-informative", where,
                             "INFORMATIVE but baseline_gate_only_risk=true")

            # --- 11: VACUOUS_PASS needs a cited code path
            if verdict == "VACUOUS_PASS":
                evidence = notes + " " + " ".join(
                    str(c.get("evidence", "")) for c in conditions)
                if not EVIDENCE_RE.search(evidence):
                    rep.fail("11-vacuous-evidence", where,
                             "VACUOUS_PASS without a cited source location "
                             "(notes/conditions must name the code path that "
                             "counts the pass)")

            # --- 14: UNKNOWN needs conditions
            if verdict == "UNKNOWN" and not conditions:
                rep.fail("14-unknown", where,
                         "verdict_outcome_class UNKNOWN without "
                         "verdict_outcome_conditions")

            for condition in conditions:
                if condition.get("class") not in VERDICT_CLASSES:
                    rep.fail("3-enum", where,
                             "verdict_outcome_conditions class %r invalid"
                             % condition.get("class"))

    # --- 12/13: summary reproducibility ------------------------------------
    summary = (doc.get("_meta") or {}).get("suite_summary") or {}

    stored_unsafe = summary.get("type_unsafe_fill_sites")
    if stored_unsafe is None:
        rep.fail("12-summary", "<summary>", "type_unsafe_fill_sites missing")
    else:
        stored = sorted((s.get("benchmark"), s.get("line")) for s in stored_unsafe)
        if stored != sorted(unsafe_sites_detail):
            rep.fail("12-summary", "<summary>",
                     "type_unsafe_fill_sites %s does not equal the sites whose "
                     "fill_type_safe is false %s (an oracle/domain hazard must "
                     "not be listed as a fill-type problem)"
                     % (stored, sorted(unsafe_sites_detail)))

    stored_unsafe_cases = summary.get("fill_type_unsafe_pattern_case_list")
    if stored_unsafe_cases is not None and sorted(stored_unsafe_cases) != sorted(fill_unsafe_cases):
        rep.fail("12-summary", "<summary>",
                 "fill_type_unsafe_pattern_case_list does not match the detail data")

    expected_counts = {
        "enhanced_fill_sites_total": site_total,
        "fill_type_safe_sites": site_safe,
        "fill_type_unsafe_sites": site_unsafe,
        "fill_type_unknown_sites": site_unknown,
        "fill_type_conditional_sites": site_conditional,
        "fill_type_unsafe_pattern_cases": len(fill_unsafe_cases),
        "fill_type_conditional_pattern_cases": fill_conditional_cases,
        "domain_invalid_pattern_cases": domain_invalid_cases,
        "baseline_gate_only_pattern_cases": bi_cases,
        "oracle_unsafe_pattern_cases": len(oracle_unsafe_cases),
        "conditional_cases": conditional_cases,
    }
    for key, expected in expected_counts.items():
        if key not in summary:
            rep.fail("13-summary", "<summary>", "missing count %r" % key)
        elif summary[key] != expected:
            rep.fail("13-summary", "<summary>",
                     "%s = %r but the detail data yields %r"
                     % (key, summary[key], expected))

    stored_verdicts = summary.get("verdict_outcome_summary")
    if stored_verdicts is None:
        rep.fail("13-summary", "<summary>", "verdict_outcome_summary missing")
    else:
        for cls in VERDICT_CLASSES:
            if stored_verdicts.get(cls, 0) != verdict_counter.get(cls, 0):
                rep.fail("13-summary", "<summary>",
                         "verdict_outcome_summary[%s] = %r but the detail data "
                         "yields %r" % (cls, stored_verdicts.get(cls, 0),
                                        verdict_counter.get(cls, 0)))


def main():
    if not CATALOG.is_file():
        print("ERROR: catalog missing: %s" % CATALOG)
        return 2
    try:
        doc = json.loads(CATALOG.read_text(encoding="utf-8"))
    except ValueError as exc:
        print("ERROR: catalog is not valid JSON: %s" % exc)
        return 2

    rep = Report()
    check_catalog(doc, rep)

    print("checked pattern entries: %d" % rep.checked)
    if rep.ok():
        print("ENHANCED_CAPABILITIES_CONSISTENT = true")
        return 0

    print("ENHANCED_CAPABILITIES_CONSISTENT = false")
    for check, where, message in rep.errors:
        print("  [%s] %s: %s" % (check, where, message))
    print("contradictions: %d" % len(rep.errors))
    return 1


if __name__ == "__main__":
    sys.exit(main())
