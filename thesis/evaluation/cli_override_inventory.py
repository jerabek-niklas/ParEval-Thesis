"""AST inventory of the CLI options of every productive runner.

The question this answers is not "what does the documentation say" but
"which command-line values can change the real experiment". Every
`parser.add_argument(...)` of the runners is read from the source, split
into

    METHODICAL_CLI_OVERRIDES_BY_STAGE    changes what is executed/measured
    NON_METHODICAL_CLI_OPTIONS_BY_STAGE  diagnostics, output shape, resume

and the methodical ones are exactly the values the effective-invocation
provenance must persist and the post-run verifier must compare against the
frozen contract.

    python thesis/evaluation/cli_override_inventory.py [--out inventory.json]

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import ast
import sys
import warnings
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

warnings.filterwarnings("ignore", category=SyntaxWarning)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# stage -> the module that owns its CLI
RUNNERS = OrderedDict([
    ("generation", "thesis/generation/common.py"),
    ("generation_driver", "thesis/generation/generate.py"),
    ("assembly", "thesis/assembly/assemble_sources.py"),
    ("correctness", "thesis/evaluation/run_correctness.py"),
    ("static", "thesis/evaluation/run_static_analysis.py"),
    ("dynamic", "thesis/evaluation/run_dynamic_analysis.py"),
    ("enhanced", "thesis/evaluation/run_enhanced_tests.py"),
    ("repair", "thesis/repair/run_repair.py"),
])

# A CLI value is METHODICAL when it changes what is executed or measured.
# Each entry carries the reason, so the classification is auditable rather
# than asserted.
METHODICAL_DESTS = OrderedDict([
    ("config", "selects the whole resolved configuration"),
    ("profile", "selects run id, population selection and limits"),
    ("run_id", "selects which run's artifacts are produced/extended"),
    ("model_id", "restricts the population to a subset of models"),
    ("models", "restricts the population to a subset of models"),
    ("primary_compiler", "changes the toolchain that produces the verdicts"),
    ("compiler", "changes the toolchain that produces the verdicts"),
    ("run_timeout", "changes the per-run timeout that decides timeout verdicts"),
    ("run_timeout_seconds", "changes the per-run timeout that decides timeout verdicts"),
    ("timeout", "changes a measurement timeout"),
    ("build_timeout", "changes the build timeout"),
    ("niter", "changes how often a benchmark is executed"),
    ("specs", "selects the enhanced spec set"),
    ("specs_file", "selects the enhanced spec set"),
    ("tools", "selects which analysis tools produce findings"),
    ("tool", "selects which analysis tool produces findings"),
    ("variants", "selects which repair variants run"),
    ("variant", "selects which repair variant runs"),
    ("max_iterations", "changes the repair budget"),
    ("iterations", "changes the repair budget"),
    ("execution_models", "restricts the measured execution models"),
    ("execution_model", "restricts the measured execution models"),
    ("jobs", "changes the parallelism of the measurement (execution condition)"),
    ("sample_id", "restricts the measured population"),
    ("samples", "restricts the measured population"),
    ("prompt_limit", "restricts the population"),
    ("num_samples_per_prompt", "changes the population size"),
    ("contract", "selects the frozen run contract the run is authorized under"),
    ("replace_tool_entries", "replaces existing tool findings"),
    ("replace_legacy_record", "replaces historical records"),
    ("rerun_gaps", "re-runs tools over analysis gaps"),
    ("api_mode", "selects direct vs batch execution of the same requests"),
    ("provider", "selects the provider adapter that produces the answers"),
    ("skip_unavailable_tools", "lets a stage finish without a tool's findings, "
                               "which changes analysis coverage"),
    ("max_wave", "bounds the repair waves that are executed"),
    ("continue_on_error", "keeps generating after a model fails, so the produced "
                          "population can differ from the contracted one"),
])

NON_METHODICAL_REASONS = OrderedDict([
    ("force", "overwrite protection for derived outputs"),
    ("restart", "resume behaviour, not the measured content"),
    ("poll", "status read of an already submitted job"),
    ("dry_run", "prints what would happen"),
    ("verbose", "diagnostic verbosity"),
    ("quiet", "diagnostic verbosity"),
    ("out", "output path of a derived report"),
    ("output", "output path of a derived report"),
    ("export_pareval_json", "additional derived export"),
    ("skip_runtime_probe", "testing switch of a checker, not a runner"),
    ("skip_repo_check", "testing switch of a checker, not a runner"),
    ("skip_containers", "testing switch of a checker, not a runner"),
    ("invocation", "path of a declaration file"),
    ("environment", "path of a measured environment file"),
    ("static_runtime", "path of a measured runtime file"),
    ("output_file_name", "name of the stage's own output file - the measured content "
                         "is unchanged (verified: run_enhanced_tests only renames the "
                         "result file)"),
    ("status", "prints the loop overview and exits without measuring "
               "(verified: run_repair returns before any wave)"),
])


def parse_module(path: Path) -> "List[OrderedDict]":
    source = path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    tree = ast.parse(source)
    options = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
            continue
        flags = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        kwargs = {}
        for kw in node.keywords:
            if kw.arg in ("dest", "action", "default", "type", "required", "nargs", "help"):
                try:
                    kwargs[kw.arg] = ast.literal_eval(kw.value)
                except Exception:  # noqa: BLE001 - keep the expression's source
                    kwargs[kw.arg] = ast.dump(kw.value)[:60]
        long_flags = [f for f in flags if f.startswith("--")]
        positional = [f for f in flags if not f.startswith("-")]
        dest = kwargs.get("dest")
        if not dest:
            base = (long_flags[0] if long_flags else (positional[0] if positional else ""))
            dest = base.lstrip("-").replace("-", "_")
        options.append(OrderedDict([
            ("flags", flags),
            ("dest", dest),
            ("action", kwargs.get("action")),
            ("default", kwargs.get("default")),
            ("required", kwargs.get("required")),
            ("help", (kwargs.get("help") or "")[:160]),
            ("line", node.lineno),
        ]))
    return options


def classify(option: "Dict[str, Any]") -> "OrderedDict[str, Any]":
    dest = option["dest"]
    if dest in METHODICAL_DESTS:
        return OrderedDict([("methodical", True), ("reason", METHODICAL_DESTS[dest])])
    if dest in NON_METHODICAL_REASONS:
        return OrderedDict([("methodical", False), ("reason", NON_METHODICAL_REASONS[dest])])
    # unknown option: default to METHODICAL - an unclassified switch that can
    # change the experiment must not slip through as "diagnostic"
    return OrderedDict([("methodical", True),
                        ("reason", "unclassified CLI option - treated as methodical until "
                                   "it is explicitly classified")])


def build_inventory() -> "OrderedDict[str, Any]":
    methodical = OrderedDict()
    non_methodical = OrderedDict()
    for stage, relative in RUNNERS.items():
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        entries = []
        for option in parse_module(path):
            verdict = classify(option)
            entry = OrderedDict(option)
            entry["file"] = relative
            entry.update(verdict)
            entries.append(entry)
        methodical[stage] = [e for e in entries if e["methodical"]]
        non_methodical[stage] = [e for e in entries if not e["methodical"]]
    return OrderedDict([
        ("schema_version", "cli_override_inventory.v1"),
        ("runners", RUNNERS),
        ("METHODICAL_CLI_OVERRIDES_BY_STAGE", methodical),
        ("NON_METHODICAL_CLI_OPTIONS_BY_STAGE", non_methodical),
        ("counts", OrderedDict([
            ("methodical", sum(len(v) for v in methodical.values())),
            ("non_methodical", sum(len(v) for v in non_methodical.values())),
        ])),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    inventory = build_inventory()
    print("METHODICAL_CLI_OVERRIDES_BY_STAGE (%d):" % inventory["counts"]["methodical"])
    for stage, entries in inventory["METHODICAL_CLI_OVERRIDES_BY_STAGE"].items():
        print("  %-16s %s" % (stage, ", ".join(e["dest"] for e in entries) or "-"))
    print("NON_METHODICAL_CLI_OPTIONS_BY_STAGE (%d):" % inventory["counts"]["non_methodical"])
    for stage, entries in inventory["NON_METHODICAL_CLI_OPTIONS_BY_STAGE"].items():
        print("  %-16s %s" % (stage, ", ".join(e["dest"] for e in entries) or "-"))
    if args.out:
        from thesis.evaluation import atomic_io

        atomic_io.atomic_write_json(Path(args.out), inventory)
        print("written:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
