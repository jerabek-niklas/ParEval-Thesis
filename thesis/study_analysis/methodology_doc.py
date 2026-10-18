"""Human-readable rendering of the frozen methodology (methodology.json ->
METHODOLOGY.md). The markdown is DERIVED: it is never edited by hand, and a
test asserts that the committed METHODOLOGY.md equals the rendering, so the
machine-readable contract and the text the thesis cites cannot drift.

    python3 -B -m thesis.study_analysis.methodology_doc            (print)
    python3 -B -m thesis.study_analysis.methodology_doc --check    (exit 1 if METHODOLOGY.md differs)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from thesis.study_analysis import core

DOC_REL = core.PACKAGE_REL + "/METHODOLOGY.md"
METRIC_FIELDS = (("meaning", "Meaning"), ("population", "Population"), ("unit", "Observation unit"),
                 ("numerator", "Numerator"), ("denominator", "Denominator"), ("applicability", "Applicability"),
                 ("missingness", "Missingness / error states"), ("aggregation", "Aggregation"),
                 ("limits", "Limits of interpretation"))


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def render(methodology):
    lines = []
    out = lines.append
    out("# Methodology %s (`%s`, %s)" % (methodology["methodology_id"], methodology["schema_version"],
                                         methodology["status"]))
    out("")
    out("Generated from `%s` by `thesis/study_analysis/methodology_doc.py` - do not edit by hand. "
        "Frozen on %s, before any aggregation." % (core.METHODOLOGY_REL, methodology["frozen_on"]))
    out("")
    applies = methodology["applies_to"]
    out("Applies to the runs %s (closure `%s`, composite `%s`); excluded: %s." % (
        ", ".join("`%s`" % r for r in applies["runs"]), applies["closure"], applies["composite_schema"],
        ", ".join("`%s`" % r for r in applies["excluded_runs"])))
    out("")
    goals = methodology["study_goals"]
    out("## Study goals")
    out("")
    out("Source: %s." % goals["source"])
    out("")
    out("**Official research questions:** %s." % goals["official_research_questions"])
    out("")
    for goal in goals["goals"]:
        out("- **%s** (section %s): %s" % (goal["id"], goal["source_section"], goal["text"]))
    out("")
    if goals.get("documented_deviations"):
        out("Documented deviations:")
        out("")
        for item in goals["documented_deviations"]:
            out("- %s" % item)
        out("")
    out("## Observation units")
    out("")
    for key, text in methodology["observation_units"].items():
        out("- **%s**: %s" % (key, text))
    out("")
    out("## Populations")
    out("")
    for key, entry in methodology["populations"].items():
        if key == "rules":
            continue
        out("- **%s**: %s. *Use:* %s." % (key, entry["definition"], entry["use"]))
    out("")
    out("Rules:")
    out("")
    for rule in methodology["populations"]["rules"]:
        out("- %s" % rule)
    out("")
    out("## Strata")
    out("")
    for key, value in methodology["strata"].items():
        out("- **%s**: %s" % (key, ", ".join(str(v) for v in value) if isinstance(value, list) else value))
    out("")
    out("## State vocabularies and rules")
    out("")
    for key, value in methodology["state_vocabularies"].items():
        if isinstance(value, list) and value and key.endswith("rules"):
            out("**%s**" % key.replace("_", " "))
            out("")
            for item in value:
                out("- %s" % item)
            out("")
        else:
            out("- **%s**: %s" % (key, ", ".join("`%s`" % v for v in value)))
    out("")
    out("## Finding rules")
    out("")
    for key, value in methodology["finding_rules"].items():
        out("- **%s**: %s" % (key, value))
    out("")
    out("## Metrics")
    out("")
    for metric in methodology["metrics"]:
        out("### %s `%s`" % (metric["id"], metric["name"]))
        out("")
        out("| field | definition |")
        out("| --- | --- |")
        for key, label in METRIC_FIELDS:
            out("| %s | %s |" % (label, _cell(metric.get(key, "-"))))
        out("")
    out("## Sensitivity analyses")
    out("")
    for item in methodology["sensitivity_analyses"]:
        out("- **%s** `%s`: %s" % (item["id"], item["name"], item["rule"]))
    out("")
    stats = methodology["statistics"]
    out("## Statistics")
    out("")
    out("- **Inference unit**: %s" % stats["inference_unit"])
    for key, value in stats["bootstrap"].items():
        out("- **bootstrap.%s**: %s" % (key, value))
    out("- **Point estimates**: %s" % stats["point_estimates"])
    out("- **Paired differences**: %s" % stats["paired_differences"])
    for key, value in stats["tests"].items():
        out("- **tests.%s**: %s" % (key, value))
    out("- **Small-cluster warning**: %s" % stats["small_cluster_warning"])
    out("- **Not done**: %s" % "; ".join(stats["not_done"]))
    out("")
    out("## Reporting")
    out("")
    for key, value in methodology["reporting"].items():
        out("- **%s**: %s" % (key, ", ".join(value) if isinstance(value, list) else value))
    out("")
    return "\n".join(lines)


ADDENDUM_DOC_REL = core.PACKAGE_REL + "/METHODOLOGY_ADDENDUM.md"


def render_addendum(addendum):
    lines = []
    out = lines.append
    out("# Methodology addendum %s (`%s`, %s)" % (addendum["addendum_id"], addendum["schema_version"],
                                                 addendum["status"]))
    out("")
    out("Generated from `%s` by `thesis/study_analysis/methodology_doc.py` - do not edit by hand. "
        "Declared on %s, AFTER a non-productive dry run and its independent review." % (
            core.ADDENDUM_REL, addendum["declared_on"]))
    out("")
    amends = addendum["amends"]
    out("Amends `%s` (canonical sha256 `%s`). %s" % (amends["methodology"], amends["methodology_canonical_sha256"],
                                                     amends["rule"]))
    out("")
    out("Trigger: %s." % addendum["trigger"])
    out("")
    out("## Post-freeze descriptive metrics")
    out("")
    for metric in addendum["metrics"]:
        out("### %s `%s` (post-freeze, descriptive)" % (metric["id"], metric["name"]))
        out("")
        out("| field | definition |")
        out("| --- | --- |")
        for key, label in METRIC_FIELDS:
            out("| %s | %s |" % (label, _cell(metric.get(key, "-"))))
        out("")
    out("## Estimate fields")
    out("")
    for item in addendum["estimate_fields"]:
        out("- **%s**: %s" % (item["field"], item["rule"]))
    out("")
    out("## Interpretive caveats (must be stated in the thesis text)")
    out("")
    for item in addendum["interpretive_caveats"]:
        out("- **%s** (applies to %s): %s" % (item["id"], ", ".join("`%s`" % a for a in item["applies_to"]),
                                              item["text"]))
    out("")
    out("## Mandatory table and figure notes")
    out("")
    for item in addendum["table_notes"]:
        out("- **%s** (%s): %s" % (item["id"], item["applies_to"], item["text"]))
    out("")
    out("## Disclosures outside the analysis outputs")
    out("")
    for item in addendum["disclosures_outside_the_analysis"]:
        out("- %s" % item)
    out("")
    out("## Goals without a frozen metric")
    out("")
    for item in addendum["goals_without_frozen_metric"]:
        out("- %s -> %s" % (item["goal"], item["addendum_metric"]))
    out("")
    return "\n".join(lines)


def render_bytes(root=core.REPO_ROOT):
    return render(core.load_methodology(root)).encode("utf-8")


def render_addendum_bytes(root=core.REPO_ROOT):
    return render_addendum(core.load_addendum(root)).encode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="render METHODOLOGY.md from methodology.json")
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed markdown differs")
    parser.add_argument("--addendum", action="store_true", help="render METHODOLOGY_ADDENDUM.md instead")
    args = parser.parse_args(argv)
    data, relative = ((render_addendum_bytes(), ADDENDUM_DOC_REL) if args.addendum else (render_bytes(), DOC_REL))
    if args.check:
        path = core.REPO_ROOT / relative
        current = path.read_bytes().replace(b"\r\n", b"\n") if path.is_file() else None
        if current != data:
            sys.stderr.write("%s differs from its rendering\n" % relative)
            return 1
        return 0
    sys.stdout.write(data.decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
