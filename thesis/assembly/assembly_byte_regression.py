"""GATE 1 - real pilot_001 assembly byte regression (read-only on history).

Re-assembles EVERY generation record of the historical runs (base run and
all repair-iteration runs) with the CURRENT assembly code into a scratch
intermediate directory and byte-compares each new generated-code.hpp with
the historical file. Nothing under the historical output tree is written.

Per file:
    IDENTICAL          raw bytes equal
    DIFFERENT          raw bytes differ; sub-classified NEWLINE_ONLY (equal
                       after CRLF->LF normalization) or CONTENT
    NOT_REPRODUCIBLE   no generation record / not assembled now / assembly
                       raised (reason recorded)

Because the source writer is host dependent (CRLF on Windows, LF in the
Linux container) the gate compares each historical file ON ITS OWN HOST
CONVENTION: a historical CRLF file re-assembled on a Windows host, an LF
file re-assembled in the container. Files whose historical convention
differs from this host's convention are reported separately as
CROSS_HOST (their NEWLINE_ONLY difference is expected and not a semantic
regression); DIFFERENT_SAME_HOST is the gate number and must be 0.

    python thesis/assembly/assembly_byte_regression.py --config thesis/config/config.yaml \
        --run-prefix pilot_001 --out <json>
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import sys
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import condition_hashing as ch  # noqa: E402

SOURCE_FILE_NAME = "generated-code.hpp"
FLAG_KEYS = ("assembled", "skip_reason", "generation_truncated")

HOST_CONVENTION = "CRLF" if os.linesep == "\r\n" else "LF"


def tree_mtime_signature(root: Path) -> "tuple[int, int]":
    """(file count, max mtime_ns) - proof that history was not touched."""
    count = 0
    newest = 0
    for path in Path(root).rglob("*"):
        if path.is_file():
            count += 1
            newest = max(newest, path.stat().st_mtime_ns)
    return count, newest


def load_entries(path: Path) -> "dict[str, dict]":
    if not path.is_file():
        return {}
    entries = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                entry = json.loads(line)
                entries[entry["sample_id"]] = entry
    return entries


def flags_of(entry: dict) -> dict:
    flags = {key: entry.get(key) for key in FLAG_KEYS}
    flags["cleaning"] = entry.get("cleaning")
    flags["drivers"] = entry.get("drivers")
    return flags


def regress(config: dict, run_prefix: str, scratch: Path,
            model_filter: "set[str] | None" = None) -> "OrderedDict":
    from thesis.assembly import assemble_sources

    raw_root = Path(config["outputs"]["raw_dir"])
    hist_root = Path(config["outputs"]["intermediate_dir"])
    scratch_config = copy.deepcopy(config)
    scratch_config["outputs"]["intermediate_dir"] = str(scratch / "intermediate")

    known_models = {m["id"]: m for m in config.get("models", [])}

    runs = OrderedDict()
    totals = OrderedDict([
        ("TOTAL", 0), ("IDENTICAL", 0), ("DIFFERENT", 0),
        ("DIFFERENT_SAME_HOST", 0), ("DIFFERENT_CROSS_HOST_NEWLINE_ONLY", 0),
        ("DIFFERENT_CONTENT", 0), ("NOT_REPRODUCIBLE", 0),
        ("LF_NORMALIZED_EQUAL", 0), ("FLAG_MISMATCHES", 0), ("UNEXPECTED_NEW_SOURCES", 0),
    ])
    different = []
    not_reproducible = []
    flag_mismatches = []
    started = time.perf_counter()

    for run_dir in sorted(raw_root.iterdir()):
        run_id = run_dir.name
        if not run_dir.is_dir() or not run_id.startswith(run_prefix):
            continue
        run_report = OrderedDict([("kind", "base" if run_id == run_prefix else "repair_iteration"),
                                  ("models", OrderedDict())])
        for model_dir in sorted(run_dir.iterdir()):
            model_id = model_dir.name
            if model_filter and model_id not in model_filter:
                continue
            if not (model_dir / "generations.jsonl").is_file():
                continue
            hist_model = hist_root / run_id / model_id
            hist_sources = hist_model / "sources"
            hist_entries = load_entries(hist_model / "assembly.jsonl")
            historical = OrderedDict()
            if hist_sources.is_dir():
                for sample_dir in sorted(hist_sources.iterdir()):
                    source = sample_dir / SOURCE_FILE_NAME
                    if source.is_file():
                        historical[sample_dir.name] = source
            if not historical:
                continue

            model_config = dict(known_models.get(model_id) or {"id": model_id})
            model_config["id"] = model_id
            error = None
            try:
                assemble_sources.assemble_model(
                    scratch_config, {"run_id": run_id}, model_config,
                    export_pareval_json=False, register_manifest=False)
            except Exception as exc:  # noqa: BLE001 - reported, never hidden
                error = "%s: %s" % (type(exc).__name__, exc)

            new_model = Path(scratch_config["outputs"]["intermediate_dir"]) / run_id / model_id
            new_entries = load_entries(new_model / "assembly.jsonl")
            new_sources = {}
            if (new_model / "sources").is_dir():
                for sample_dir in (new_model / "sources").iterdir():
                    if (sample_dir / SOURCE_FILE_NAME).is_file():
                        new_sources[sample_dir.name] = sample_dir / SOURCE_FILE_NAME

            m = OrderedDict([("historical_files", len(historical)), ("IDENTICAL", 0),
                             ("DIFFERENT", 0), ("DIFFERENT_SAME_HOST", 0),
                             ("DIFFERENT_CROSS_HOST_NEWLINE_ONLY", 0), ("DIFFERENT_CONTENT", 0),
                             ("NOT_REPRODUCIBLE", 0), ("historical_conventions", {}),
                             ("assembly_error", error)])
            for sample_id, hist_path in historical.items():
                totals["TOTAL"] += 1
                old = hist_path.read_bytes()
                convention = ch.newline_convention(old)
                m["historical_conventions"][convention] = m["historical_conventions"].get(convention, 0) + 1
                new_path = new_sources.get(sample_id)
                if error or new_path is None:
                    reason = error or ("no generation record" if sample_id not in new_entries
                                       else "not assembled now: %s" % new_entries[sample_id].get("skip_reason"))
                    m["NOT_REPRODUCIBLE"] += 1
                    totals["NOT_REPRODUCIBLE"] += 1
                    not_reproducible.append(OrderedDict([("run_id", run_id), ("model_id", model_id),
                                                         ("sample_id", sample_id), ("reason", reason)]))
                    continue
                new = new_path.read_bytes()
                lf_equal = ch.lf_normalize(old) == ch.lf_normalize(new)
                if lf_equal:
                    totals["LF_NORMALIZED_EQUAL"] += 1
                if old == new:
                    m["IDENTICAL"] += 1
                    totals["IDENTICAL"] += 1
                else:
                    m["DIFFERENT"] += 1
                    totals["DIFFERENT"] += 1
                    same_host = convention == HOST_CONVENTION
                    if lf_equal and not same_host:
                        kind = "CROSS_HOST_NEWLINE_ONLY"
                        m["DIFFERENT_CROSS_HOST_NEWLINE_ONLY"] += 1
                        totals["DIFFERENT_CROSS_HOST_NEWLINE_ONLY"] += 1
                    else:
                        kind = "NEWLINE_ONLY_SAME_HOST" if lf_equal else "CONTENT"
                        m["DIFFERENT_SAME_HOST"] += 1
                        totals["DIFFERENT_SAME_HOST"] += 1
                        if not lf_equal:
                            m["DIFFERENT_CONTENT"] += 1
                            totals["DIFFERENT_CONTENT"] += 1
                    different.append(OrderedDict([
                        ("run_id", run_id), ("model_id", model_id), ("sample_id", sample_id),
                        ("kind", kind), ("historical_convention", convention),
                        ("new_convention", ch.newline_convention(new)),
                        ("historical_sha256", ch.raw_sha256_bytes(old)),
                        ("new_sha256", ch.raw_sha256_bytes(new)),
                        ("lf_normalized_equal", lf_equal),
                    ]))
                # cleaning flag parity old record vs new record
                old_entry = hist_entries.get(sample_id)
                new_entry = new_entries.get(sample_id)
                if old_entry is not None and new_entry is not None:
                    if flags_of(old_entry) != flags_of(new_entry):
                        totals["FLAG_MISMATCHES"] += 1
                        flag_mismatches.append(OrderedDict([
                            ("run_id", run_id), ("model_id", model_id), ("sample_id", sample_id)]))
            unexpected = sorted(set(new_sources) - set(historical))
            if unexpected:
                totals["UNEXPECTED_NEW_SOURCES"] += len(unexpected)
                m["unexpected_new_sources"] = unexpected
            run_report["models"][model_id] = m
        if run_report["models"]:
            runs[run_id] = run_report

    return OrderedDict([
        ("schema_version", "assembly_byte_regression.v1"),
        ("run_prefix", run_prefix),
        ("host", OrderedDict([("platform", sys.platform), ("os_linesep", repr(os.linesep)),
                              ("host_convention", HOST_CONVENTION),
                              ("python_version", platform.python_version())])),
        ("totals", totals),
        ("elapsed_seconds", round(time.perf_counter() - started, 3)),
        ("runs", runs),
        ("different", different),
        ("not_reproducible", not_reproducible),
        ("flag_mismatches", flag_mismatches),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-prefix", default="pilot_001")
    parser.add_argument("--models", default=None, help="comma-separated model ids (default all)")
    parser.add_argument("--scratch", default=None, help="scratch dir (default: a temp dir)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    config = load_config(Path(args.config).resolve())
    hist_root = Path(config["outputs"]["intermediate_dir"])
    before = tree_mtime_signature(hist_root)

    model_filter = set(args.models.split(",")) if args.models else None
    if args.scratch:
        scratch = Path(args.scratch)
        scratch.mkdir(parents=True, exist_ok=True)
        result = regress(config, args.run_prefix, scratch, model_filter)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            result = regress(config, args.run_prefix, Path(tmp), model_filter)

    after = tree_mtime_signature(hist_root)
    result["historical_tree_untouched"] = before == after
    result["historical_tree_signature"] = {"before": list(before), "after": list(after)}

    t = result["totals"]
    print("PILOT001_ASSEMBLY_BYTE_REGRESSION_TOTAL = %d" % t["TOTAL"])
    print("PILOT001_ASSEMBLY_BYTE_IDENTICAL = %d" % t["IDENTICAL"])
    print("PILOT001_ASSEMBLY_BYTE_DIFFERENT = %d" % t["DIFFERENT"])
    print("PILOT001_ASSEMBLY_BYTE_DIFFERENT_SAME_HOST = %d" % t["DIFFERENT_SAME_HOST"])
    print("PILOT001_ASSEMBLY_BYTE_DIFFERENT_CROSS_HOST_NEWLINE_ONLY = %d"
          % t["DIFFERENT_CROSS_HOST_NEWLINE_ONLY"])
    print("PILOT001_ASSEMBLY_BYTE_DIFFERENT_CONTENT = %d" % t["DIFFERENT_CONTENT"])
    print("PILOT001_ASSEMBLY_NOT_REPRODUCIBLE = %d" % t["NOT_REPRODUCIBLE"])
    print("PILOT001_ASSEMBLY_LF_NORMALIZED_EQUAL = %d" % t["LF_NORMALIZED_EQUAL"])
    print("PILOT001_ASSEMBLY_FLAG_MISMATCHES = %d" % t["FLAG_MISMATCHES"])
    print("HOST_CONVENTION = %s" % HOST_CONVENTION)
    print("HISTORICAL_TREE_UNTOUCHED = %s" % str(result["historical_tree_untouched"]).lower())
    for run_id, run in result["runs"].items():
        for model_id, m in run["models"].items():
            print("  %-40s %-20s hist=%3d ident=%3d diff=%3d same_host_diff=%3d cross=%3d nr=%3d conv=%s"
                  % (run_id, model_id, m["historical_files"], m["IDENTICAL"], m["DIFFERENT"],
                     m["DIFFERENT_SAME_HOST"], m["DIFFERENT_CROSS_HOST_NEWLINE_ONLY"],
                     m["NOT_REPRODUCIBLE"], m["historical_conventions"]))
    if args.out:
        atomic_io.atomic_write_json(Path(args.out), result)
        print("written:", args.out)

    # A gate that compared nothing has proven nothing: an empty comparison,
    # an unreproducible sample or a cleaning-flag difference all FAIL, and
    # ASSEMBLY_SEMANTICS_CHANGED is only claimed false when the run actually
    # established it.
    problems = []
    if t["TOTAL"] == 0:
        problems.append("no historical sample was compared (wrong --run-prefix/--models, "
                        "or the historical evidence is missing)")
    if t["NOT_REPRODUCIBLE"]:
        problems.append("%d sample(s) could not be re-assembled" % t["NOT_REPRODUCIBLE"])
    if t["DIFFERENT_CONTENT"]:
        problems.append("%d content difference(s)" % t["DIFFERENT_CONTENT"])
    if t["DIFFERENT_SAME_HOST"]:
        problems.append("%d same-host byte difference(s)" % t["DIFFERENT_SAME_HOST"])
    if t["FLAG_MISMATCHES"]:
        problems.append("%d cleaning-flag mismatch(es)" % t["FLAG_MISMATCHES"])
    if t["UNEXPECTED_NEW_SOURCES"]:
        problems.append("%d new source(s) without a historical counterpart"
                        % t["UNEXPECTED_NEW_SOURCES"])
    if not result["historical_tree_untouched"]:
        problems.append("the historical evidence tree changed during the run")

    semantics_undecided = t["TOTAL"] == 0 or t["NOT_REPRODUCIBLE"] > 0
    print("ASSEMBLY_SEMANTICS_CHANGED = %s"
          % ("UNDECIDED (nothing comparable was reproduced)" if semantics_undecided
             else ("false" if t["DIFFERENT_CONTENT"] == 0 and t["FLAG_MISMATCHES"] == 0
                   else "true")))
    for problem in problems:
        print("  GATE PROBLEM: %s" % problem)
    print("GATE_1_PILOT001_ASSEMBLY_BYTE_REGRESSION = %s"
          % ("PASS" if not problems else "FAIL"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
