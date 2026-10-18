"""Entry point of the study analysis (study_analysis_001).

    python3 -B -u -m thesis.study_analysis.run --dry-run --out DIR
    python3 -B -u -m thesis.study_analysis.run --write

Pipeline: preflight (deep: the phase-2 lineage re-hashes every protected
historical byte) -> start manifest -> normalize.build_dataset (the only
reader of result files) -> metrics.compute (methodology replicate counts)
-> metrics.compute_primary (reproducibility rerun of the primary family)
-> tables / figures -> end manifest -> validate (independent recomputation,
composite / census / ledger binding, input stability) -> outputs.

--dry-run (default) writes ONLY into --out DIR, which must lie outside the
repository; without --out nothing is written at all. --write is the formal
run: it needs a write-mode preflight PASS (clean worktree, package and
methodology committed, output directory absent) AND a validation PASS, then
writes the complete output set into core.OUTPUT_REL through a temporary
sibling directory and one rename (no partial formal output). Neither mode
contacts a provider, measures, repairs or touches a result tree.

Exit codes: 0 PASS, 1 validation FAIL (dry run: outputs still dumped for
inspection), 2 refused before the analysis (preflight / arguments).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.study_analysis import core  # noqa: E402

RESULTS_DIR = "results"
DATA_PLAIN = ("base_cells", "artifacts", "trajectories", "generations", "tool_entries")
DATA_GZIP = ("findings", "enhanced_pairs")
ESTIMATE_COLUMNS = ("metric_id", "population", "block", "strata", "numerator", "denominator", "value", "ci_low",
                    "ci_high", "ci_method", "replicates", "p_value", "p_holm", "reject_holm", "note", "extra")
ESTIMATE_CORE_KEYS = ESTIMATE_COLUMNS[:-1]


def log(message):
    sys.stderr.write("[analysis %s] %s\n" % (time.strftime("%H:%M:%S", time.gmtime()), message))
    sys.stderr.flush()


class Timer:
    def __init__(self):
        self.timings = OrderedDict()

    def run(self, key, function, *args, **kwargs):
        start = time.time()
        log("start " + key)
        try:
            return function(*args, **kwargs)
        finally:
            self.timings[key] = round(time.time() - start, 1)
            log("done %s (%.1f s)" % (key, self.timings[key]))


# -- serialisation of the outputs --------------------------------------------------------------

def estimates_json_bytes(estimates):
    """Compact, deterministic JSON of every estimate (gzip-wrapped by the caller)."""
    text = json.dumps([core.json_stable(e) for e in estimates], sort_keys=False, separators=(",", ":"),
                      ensure_ascii=False, default=str)
    return (text + "\n").encode("utf-8")


def estimates_csv_bytes(estimates):
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(ESTIMATE_COLUMNS)
    for est in estimates:
        extra = OrderedDict((k, v) for k, v in est.items() if k not in ESTIMATE_CORE_KEYS)
        row = []
        for column in ESTIMATE_COLUMNS[:-1]:
            value = est.get(column)
            if column == "strata":
                value = json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            row.append("" if value is None else (("1" if value else "0") if isinstance(value, bool) else value))
        row.append(json.dumps(core.json_stable(extra), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                   if extra else "")
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def validation_markdown(document):
    lines = ["# %s - validation report (%s)" % (core.ANALYSIS_ID, document.get("status")), "",
             "Schema `%s`; validation sha256 `%s`." % (document.get("schema_version"),
                                                      document.get("validation_sha256")), "",
             "| check | status | detail |", "| --- | --- | --- |"]
    for check in document.get("checks") or []:
        detail = json.dumps(check.get("detail"), default=str)
        if len(detail) > 400:
            detail = detail[:397] + "..."
        lines.append("| %s | %s | %s |" % (check.get("check"), check.get("status"), detail.replace("|", "\\|")))
    lines.append("")
    summary = document.get("summary")
    if summary:
        lines += ["## Summary", "", "```json", json.dumps(summary, indent=1, default=str), "```", ""]
    return "\n".join(lines) + "\n"


def readme_markdown(results, tables, figures, addendum):
    lines = ["# %s - final scientific analysis outputs" % core.ANALYSIS_ID, "",
             "Mode: %s. Status: %s. Results sha256 `%s`." % (results["mode"], results["status"],
                                                             results["results_sha256"]), "",
             "Every number below is computed by `thesis/study_analysis` from the formally verified study "
             "(closure `%s`, composite `%s`) under the frozen methodology `%s` (status FROZEN_BEFORE_AGGREGATION) "
             "and its post-freeze addendum `%s` (status %s)."
             % (results["inputs"]["closure"]["closure_sha256"], results["inputs"]["composite"]["composite_sha256"],
                results["methodology"]["canonical_sha256"], results["addendum"]["canonical_sha256"],
                results["addendum"]["status"]), "",
             "Pilot results carry the label: *%s*." % results["pilot_label"], "",
             "## How to read the results", "",
             "- The primary hypothesis family (12 hypotheses, Holm) and every frozen metric (Q, E, S, D, F, R, C, G) "
             "follow `methodology.json`, frozen before any aggregation.",
             "- Metrics X01-X06 and the interpretive caveats IC1-IC7 come from `methodology_addendum.json`, declared "
             "AFTER a non-productive dry run and its independent review: they are post-hoc, descriptive "
             "sensitivity analyses (no tests) and must be presented as such.",
             "- Terminal loop statuses (stopped_clean, stopped_tests_pass, ...) are trajectory facts, never repair "
             "successes; a successful repair is an improvement of the same base cell on an explicit endpoint "
             "(R02).",
             "- 95% intervals are stratified benchmark-cluster bootstrap percentile intervals; pilot intervals rest "
             "on 12 clusters (approximate); intervals marked as degenerate have zero width because every supporting "
             "cluster has the same value (a share at 0% or 100%, or a difference of 0).", "",
             "## Mandatory disclosures", ""]
    for note in addendum.get("table_notes") or []:
        lines.append("- **%s** (%s): %s" % (note["id"], note["applies_to"], note["text"]))
    for caveat in addendum.get("interpretive_caveats") or []:
        lines.append("- **%s**: %s" % (caveat["id"], caveat["text"]))
    for item in addendum.get("disclosures_outside_the_analysis") or []:
        lines.append("- %s" % item)
    lines += ["", "## LaTeX usage", "",
              "- `tables/preamble.tex` lists the packages the tables and figures need (booktabs, longtable, "
              "pgfplots compat 1.18, T1 font encoding); wide tables need landscape pages (pdflscape or lscape) - "
              "see the comments in `tables/preamble.tex` and in each table file.",
              "- Figures: `\\begin{figure}\\centering\\input{figures/<id>.tex}\\input{figures/<id>.caption.tex}"
              "\\end{figure}`; SVG files are previews of the same data.", "",
              "## Contents", "",
              "- `manifest.json` / `manifest_start.json`: input manifest (every input file with its sha256) at the "
              "end and the start of the run",
              "- `preflight.json`, `validation_report.json` / `.md`: preconditions and the independent validation",
              "- `methodology.json` / `METHODOLOGY.md`, `methodology_addendum.json` / `METHODOLOGY_ADDENDUM.md`",
              "- `results.json`: identities, counts, the primary hypothesis family and the output index; "
              "`results/estimates.json.gz` / `.csv.gz`: every estimate",
              "- `data/`: the normalized tables (CSV; findings and enhanced pairs gzip-compressed)",
              "- `tables/<id>.{csv,json,tex}` and `figures/<id>.{csv,tex,caption.tex,svg}`", "", "## Tables", ""]
    for table in tables:
        lines.append("- `%s`: %s (population: %s)" % (table["id"], table["title"], table["population"]))
    lines += ["", "## Figures", ""]
    for figure in figures:
        lines.append("- `%s`: %s" % (figure["id"], figure["title"]))
    lines.append("")
    return "\n".join(lines) + "\n"


def output_files(root, preflight_doc, manifest_start, manifest_end, dataset, estimates, tables, figures,
                 validation, results_core, methodology_bytes, methodology_md, addendum_bytes, addendum_md, addendum):
    """relative output path -> bytes (deterministic except the volatile blocks)."""
    from thesis.study_analysis import figures as fg
    from thesis.study_analysis import latex
    from thesis.study_analysis import tables as tb

    files = OrderedDict()
    files["preflight.json"] = core.json_bytes(preflight_doc)
    files["manifest_start.json"] = core.json_bytes(manifest_start)
    files["manifest.json"] = core.json_bytes(manifest_end)
    files["methodology.json"] = methodology_bytes
    files["METHODOLOGY.md"] = methodology_md
    files["methodology_addendum.json"] = addendum_bytes
    files["METHODOLOGY_ADDENDUM.md"] = addendum_md
    files["tables/preamble.tex"] = latex.preamble_tex()
    files["validation_report.json"] = core.json_bytes(validation)
    files["validation_report.md"] = validation_markdown(validation).encode("utf-8")
    estimates_json = core.gzip_bytes(estimates_json_bytes(estimates))
    estimates_csv = core.gzip_bytes(estimates_csv_bytes(estimates))
    files[RESULTS_DIR + "/estimates.json.gz"] = estimates_json
    files[RESULTS_DIR + "/estimates.csv.gz"] = estimates_csv
    for name in DATA_PLAIN:
        files["data/%s.csv" % name] = core.table_csv_bytes(name, dataset.rows(name))
    for name in DATA_GZIP:
        files["data/%s.csv.gz" % name] = core.gzip_bytes(core.table_csv_bytes(name, dataset.rows(name)))
    for table in tables:
        files["tables/%s.csv" % table["id"]] = tb.table_csv(table)
        files["tables/%s.json" % table["id"]] = tb.table_json(table)
        files["tables/%s.tex" % table["id"]] = latex.table_tex(table)
    for figure in figures:
        files["figures/%s.csv" % figure["id"]] = fg.figure_csv(figure)
        files["figures/%s.tex" % figure["id"]] = fg.figure_pgfplots(figure)
        files["figures/%s.caption.tex" % figure["id"]] = fg.figure_caption_tex(figure)
        files["figures/%s.svg" % figure["id"]] = fg.figure_svg(figure)
    index = OrderedDict((path, OrderedDict([("sha256", core.sha256_bytes(data)), ("bytes", len(data))]))
                        for path, data in files.items())
    results = OrderedDict(results_core)
    results["outputs"] = index
    results = core.json_stable(results)
    results["results_sha256"] = core.self_hash(results, "results_sha256")
    files["results.json"] = core.json_bytes(results)
    files["README.md"] = readme_markdown(results, tables, figures, addendum).encode("utf-8")
    return files, results


def write_tree(target, files):
    target = Path(target)
    for relative, data in files.items():
        core.write_bytes(target / relative, data)
    return sorted(files)


def formal_write(root, files):
    """All outputs into core.OUTPUT_REL via <OUTPUT_REL>.partial-<pid> and one
    rename; an existing output directory refuses (never overwrite)."""
    root = Path(root).resolve()
    final = root / core.OUTPUT_REL
    if final.exists():
        raise core.AnalysisRefused("%s exists - a formal run never overwrites its outputs" % core.OUTPUT_REL)
    partial = final.parent / (final.name + ".partial-%d" % os.getpid())
    if partial.exists():
        raise core.AnalysisRefused("stale partial output directory %s" % partial.name)
    try:
        write_tree(partial, files)
        for relative, data in files.items():
            if (partial / relative).read_bytes() != data:
                raise core.AnalysisRefused("read-back mismatch of %s" % relative)
        os.replace(str(partial), str(final))
    except BaseException:
        if partial.exists():
            shutil.rmtree(str(partial), ignore_errors=True)
        raise
    return final


# -- the pipeline ------------------------------------------------------------------------------------

def primary_family(estimates):
    return [OrderedDict((k, e.get(k)) for k in ("metric_id", "population", "block", "strata", "numerator",
                                                "denominator", "value", "ci_low", "ci_high", "replicates",
                                                "p_value", "p_resolution", "p_holm", "p_holm_resolution",
                                                "reject_holm"))
            for e in estimates if e.get("p_holm") is not None]


def run(write_mode, out_dir=None):
    from thesis.study_analysis import figures as fg
    from thesis.study_analysis import manifest as mf
    from thesis.study_analysis import metrics
    from thesis.study_analysis import methodology_doc
    from thesis.study_analysis import normalize
    from thesis.study_analysis import preflight as pf
    from thesis.study_analysis import tables as tb
    from thesis.study_analysis import validate as vd
    from thesis.recovery_successor_004 import census as cs
    from thesis.recovery_successor_005 import composite as pc
    from thesis.recovery_successor_005 import lineage as pl
    from thesis.recovery_successor_005 import targets as pt

    root = core.REPO_ROOT
    timer = Timer()
    started = core.utc_now()
    core.provider_isolation()
    preflight_doc = timer.run("preflight", pf.preflight, root, write_mode=write_mode, deep=True)
    if preflight_doc.get("status") != pf.PASS:
        log("REFUSED by the preflight: %s" % preflight_doc.get("failing"))
        if out_dir is not None:
            write_tree(out_dir, OrderedDict([("preflight.json", core.json_bytes(preflight_doc))]))
        return 2, preflight_doc
    methodology = core.load_methodology(root)
    methodology_bytes = (root / core.METHODOLOGY_REL).read_bytes()
    methodology_md = methodology_doc.render_bytes(root)
    addendum = core.load_addendum(root, methodology=methodology)
    addendum_bytes = (root / core.ADDENDUM_REL).read_bytes()
    addendum_md = methodology_doc.render_addendum_bytes(root)
    config = core.load_config(root)
    lineage = pl.load(root)
    table = pt.load_table(root, lineage.targets_sha256)
    manifest_start = timer.run("manifest_start", mf.input_manifest, root, None)
    census_result = timer.run("census", cs.census, root, list(core.MODELS))
    dataset = timer.run("normalize", normalize.build_dataset, root, config, table, census_result, log,
                        None, lineage.sha256)
    estimates = timer.run("metrics", metrics.compute, dataset, methodology, addendum=addendum)
    rerun = timer.run("metrics_primary_rerun", metrics.compute_primary, dataset, methodology)
    summary = tb.summarize_dataset(dataset)
    tables = timer.run("tables", tb.build_tables, estimates, summary, methodology, addendum=addendum)
    figures = timer.run("figures", fg.build_figures, estimates, methodology, summary, addendum=addendum)
    composite_cells = timer.run("composite_cells", lambda: list(pc.iter_cells(root, config, table)))
    manifest_end = timer.run("manifest_end", mf.input_manifest, root, dataset)
    validation = timer.run("validate", vd.validate, root, config, table, dataset, estimates, tables, figures,
                           manifest_end, composite_cells=composite_cells, estimates_rerun=rerun,
                           census_result=census_result, methodology=methodology, manifest_start=manifest_start,
                           write_mode=write_mode,
                           preflight_head=(preflight_doc.get("facts") or {}).get("git_head"), addendum=addendum)
    status = validation.get("status")
    composite = json.loads((root / pc.DOCUMENT_REL).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    closure = json.loads((root / core.CLOSURE_REL).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    results_core = OrderedDict([
        ("schema_version", core.RESULTS_SCHEMA), ("analysis_id", core.ANALYSIS_ID),
        ("mode", "formal" if write_mode else "dry-run"), ("status", status),
        ("git", core.git_state(root)),
        ("methodology", core.methodology_identity(root)),
        ("addendum", core.addendum_identity(root)),
        ("package_sources", core.package_sources(root)),
        ("inputs", OrderedDict([
            ("closure", OrderedDict([("relative", core.CLOSURE_REL),
                                     ("closure_sha256", closure.get("closure_sha256"))])),
            ("composite", OrderedDict([("relative", pc.DOCUMENT_REL),
                                       ("composite_sha256", composite.get("composite_sha256"))])),
            ("lineage_sha256", lineage.sha256), ("targets_sha256", table.sha256),
            ("census_digest", dataset.provenance.get("census_digest")),
            ("manifest_sha256", manifest_end.get("manifest_sha256")),
            ("validation_sha256", validation.get("validation_sha256"))])),
        ("dataset_counts", dataset.counts()),
        ("dataset_disclosures", OrderedDict((k, dataset.provenance.get(k)) for k in (
            "effective_state_overrides", "dirty_only_from_gap_state_entries", "gated_groups"))),
        ("statistics", core.statistics_settings(methodology)),
        ("estimates", OrderedDict([("count", len(estimates)),
                                   ("with_interval", sum(1 for e in estimates if e.get("ci_low") is not None)),
                                   ("files", [RESULTS_DIR + "/estimates.json.gz", RESULTS_DIR + "/estimates.csv.gz"])])),
        ("primary_family", primary_family(estimates)),
        ("tables", [t["id"] for t in tables]), ("figures", [f["id"] for f in figures]),
        ("pilot_label", methodology["reporting"]["pilot_label"]),
        ("post_freeze", OrderedDict([
            ("addendum_id", addendum["addendum_id"]), ("status", addendum["status"]),
            ("metrics", core.addendum_metric_ids(addendum)),
            ("estimates", sum(1 for e in estimates if e.get("post_freeze"))),
            ("rule", addendum["amends"]["rule"])])),
        ("volatile", OrderedDict([("started_at_utc", started), ("finished_at_utc", core.utc_now()),
                                  ("timings_seconds", timer.timings)])),
    ])
    files, results = output_files(root, preflight_doc, manifest_start, manifest_end, dataset, estimates, tables,
                                  figures, validation, results_core, methodology_bytes, methodology_md,
                                  addendum_bytes, addendum_md, addendum)
    if write_mode:
        if status != pf.PASS:
            log("validation FAIL - nothing is written in write mode: %s"
                % [c["check"] for c in validation.get("checks") or [] if c.get("status") != pf.PASS])
            return 1, results
        target = formal_write(root, files)
        log("formal outputs written to %s (%d files)" % (Path(target).relative_to(root).as_posix(), len(files)))
    elif out_dir is not None:
        write_tree(out_dir, files)
        log("dry-run outputs dumped to %s (%d files)" % (out_dir, len(files)))
    return (0 if status == pf.PASS else 1), results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="compute and validate; write only into --out")
    mode.add_argument("--write", action="store_true", help="formal run: write into %s" % core.OUTPUT_REL)
    parser.add_argument("--out", default=None, help="dry run: dump directory OUTSIDE the repository")
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != core.REPO_ROOT:
        sys.stderr.write("run from the repository root\n")
        return 2
    out_dir = None
    if args.out:
        if args.write:
            sys.stderr.write("--out is a dry-run option\n")
            return 2
        out_dir = Path(args.out).resolve()
        try:
            out_dir.relative_to(core.REPO_ROOT)
            sys.stderr.write("--out must lie outside the repository\n")
            return 2
        except ValueError:
            pass
    code, results = run(bool(args.write), out_dir)
    summary = OrderedDict((k, results.get(k)) for k in ("analysis_id", "mode", "status", "results_sha256",
                                                        "dataset_counts", "primary_family", "tables", "figures"))
    summary["timings_seconds"] = (results.get("volatile") or {}).get("timings_seconds")
    if "failing" in results:
        summary["preflight_failing"] = results.get("failing")
    sys.stdout.write(json.dumps(summary, indent=1, default=str) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
