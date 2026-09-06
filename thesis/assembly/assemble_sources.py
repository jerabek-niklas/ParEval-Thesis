"""Assemble compilable C++ sources from generation records.

For every successful generation record this script builds a
generated-code.hpp that is byte-compatible with what ParEval's
CppDriverWrapper.test_single_output() would produce (NO_INLINE-patched
prompt + completion), but with the improved cleaning from
thesis/assembly/cleaning.py and persisted to disk so that correctness
tests AND static analysis operate on the exact same file.

File layout (assembled file):

    // relocated model includes (if any)
    <prompt without its last line>
    <new pre-signature helper code from the model (if any)>
    <NO_INLINE-patched signature line>
    <cleaned body>

Outputs:
    <intermediate_dir>/<run_id>/<model_id>/sources/<sample_id>/generated-code.hpp
    <intermediate_dir>/<run_id>/<model_id>/assembly.jsonl          (schema assembly.v2)
    <intermediate_dir>/<run_id>/<model_id>/assembly_summary.json   (per-model set fingerprint)
    <intermediate_dir>/<run_id>/run_manifest.fragments/assembly.<model_id>.json

Integrity / provenance (pilot_002 pre-run wave, additive schema assembly.v2;
legacy assembly.v1 records are never rewritten):

    assembly_input_sha256      exact stage input (prompt_text, raw_text)
    source_sha256              RAW bytes of generated-code.hpp, re-read after
                               the write - never newline-normalized
    newline_convention         LF / CRLF / MIXED / OTHER of those bytes
    assembly_condition_sha256  the versioned assembly METHOD
    logical_source_path        run-relative identity, never an absolute path

Writes are crash-safe (temp file + fsync + os.replace); assembly.jsonl is
written once, atomically, after every source; a duplicate sample_id in the
generation records is refused before anything is written; sources of samples
that no longer assemble are removed so no stale usable source survives a
re-assembly; a failed re-assembly leaves no assembly.jsonl at all (a reader
then sees NO samples, never stale ones).

Newline policy of the source writer: text mode, newline=None, i.e. the
interpreter translates LF to os.linesep - HOST DEPENDENT (CRLF on Windows,
LF on Linux). Measured and documented, deliberately NOT changed by this
wave: pinning it would change assembled bytes and needs its own re-freeze.

Example:
    python thesis/assembly/assemble_sources.py --config thesis/config/config.yaml --profile smoke --model-id claude_fable_5
    python thesis/assembly/assemble_sources.py --config thesis/config/config.yaml --profile smoke   # all enabled models

Optional:
    --export-pareval-json writes a prompts+outputs JSON per model that
    upstream drivers/run-all.py can consume directly.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.assembly import cleaning  # noqa: E402
from thesis.evaluation import atomic_io  # noqa: E402

ASSEMBLY_SCHEMA_VERSION = "assembly.v2"
LEGACY_ASSEMBLY_SCHEMA_VERSION = "assembly.v1"

# The source writer's newline behaviour, stated once (and hashed into the
# assembly condition as a statement about the CODE, never about the host):
# text mode + newline=None -> "\n" becomes os.linesep on write.
ASSEMBLY_WRITER_NEWLINE_POLICY = "HOST_DEPENDENT"
ASSEMBLY_WRITER_NEWLINE_HOST_DEPENDENT = True

SOURCE_FILE_NAME = "generated-code.hpp"
SUMMARY_FILE_NAME = "assembly_summary.json"

MODEL_DRIVER_FILES = {
    "serial": "serial-driver.cc",
    "omp": "omp-driver.cc",
    "mpi": "mpi-driver.cc",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble C++ sources from generation records."
    )

    parser.add_argument("--config", required=True, help="Path to thesis config YAML.")
    parser.add_argument("--profile", required=True, help="Profile name from config.")
    parser.add_argument(
        "--model-id",
        default=None,
        help="Single model id. If omitted, all enabled models are assembled.",
    )
    parser.add_argument(
        "--export-pareval-json",
        action="store_true",
        help="Additionally write an upstream-ParEval-format prompts+outputs JSON.",
    )

    return parser.parse_args()


def patch_signature_line(signature_line: str) -> str:
    """Insert NO_INLINE after the return type (mirrors upstream patch_prompt)."""
    parts = signature_line.split(" ")

    if len(parts) < 2:
        raise ValueError(f"Could not parse return type from signature: {signature_line}")

    parts.insert(1, "NO_INLINE")
    return " ".join(parts)


def assemble_content(prompt_text: str, result: cleaning.AssemblyCleaningResult) -> str:
    prompt_lines = prompt_text.rstrip().splitlines()
    signature_line = prompt_lines[-1]
    prompt_head = "\n".join(prompt_lines[:-1])

    sections: list[str] = []

    if result.relocated_includes:
        sections.append("\n".join(result.relocated_includes))

    if prompt_head:
        sections.append(prompt_head)

    if result.pre_signature_code:
        sections.append(result.pre_signature_code)

    sections.append(patch_signature_line(signature_line))
    sections.append(result.body)

    return "\n".join(sections) + "\n"


def driver_paths(record: dict[str, Any]) -> dict[str, Any]:
    """Resolve the upstream driver files this sample will be tested against."""
    prompt = record["prompt"]
    parallelism_model = prompt["parallelism_model"]

    benchmark_dir = (
        Path("drivers/cpp/benchmarks") / prompt["problem_type"] / prompt["name"]
    )
    model_driver = Path("drivers/cpp/models") / MODEL_DRIVER_FILES.get(
        parallelism_model, ""
    )

    # Store POSIX (forward-slash) paths so the JSONL is portable: it may be
    # written on Windows and consumed in the Linux analysis container.
    return {
        "benchmark_dir": benchmark_dir.as_posix(),
        "benchmark_dir_exists": (REPO_ROOT / benchmark_dir).is_dir(),
        "model_driver": model_driver.as_posix(),
        "model_driver_exists": (REPO_ROOT / model_driver).is_file(),
    }


def build_source_content(
    record: dict[str, Any], auto_close_single_brace: bool
) -> "tuple[str, cleaning.AssemblyCleaningResult]":
    """The pure content function: generation record -> (content, cleaning
    result). Byte-identical to the legacy assembly.v1 path (same cleaning,
    same layout, same auto-close rule); the provenance wave only wraps it."""
    prompt_text = record["prompt"]["prompt_text"]
    raw_text = record["output"]["raw_text"]
    truncated = bool((record.get("status") or {}).get("truncated", False))

    result = cleaning.clean_for_assembly(prompt_text, raw_text)
    content = assemble_content(prompt_text, result)

    balance = cleaning.brace_balance(content)

    # Some models treat the task as "fill in the body" and leave the
    # function's closing brace to the scaffold. If exactly one brace
    # is missing at EOF and the generation was not truncated, close
    # it deterministically and flag it (auto_closed) so the rate of
    # this format deviation stays reportable per model.
    if auto_close_single_brace and balance == 1 and not truncated:
        content = content.rstrip("\n") + "\n}\n"
        balance = cleaning.brace_balance(content)
        result.metadata.auto_closed = True

    result.metadata.braces_balanced = balance == 0
    return content, result


def write_source(source_path: Path, content: str) -> None:
    """Crash-safe source write with the LEGACY newline semantics: text mode,
    newline=None (host-dependent line terminator, exactly what
    Path.write_text did in assembly.v1)."""
    atomic_io.atomic_write_text(source_path, content, encoding="utf-8", newline=None)


def load_generation_records(generations_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with generations_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def refuse_duplicate_sample_ids(records: list[dict[str, Any]], model_id: str) -> None:
    """A sample id must be unique within one model's generation records.
    Two records for one id would let the second silently overwrite the
    first's source (last-writer-wins) - refused before anything is written."""
    from thesis.assembly.assembly_provenance import AssemblyIntegrityError

    seen: set[str] = set()
    duplicates: list[str] = []
    for record in records:
        sample_id = record["sample_id"]
        if sample_id in seen:
            duplicates.append(sample_id)
        seen.add(sample_id)
    if duplicates:
        raise AssemblyIntegrityError(
            "[%s] duplicate sample_id(s) in the generation records: %s - refusing "
            "to assemble (no last-writer-wins). Deduplicate the generation records "
            "first." % (model_id, ", ".join(sorted(set(duplicates))))
        )


def refuse_legacy_rewrite(previous_entries: list[dict[str, Any]], run_id: str,
                          model_id: str, intermediate_dir: Path,
                          allow_legacy_rewrite: bool) -> None:
    """A legacy assembly.v1 run (pilot_001: records without source hashes)
    is historical evidence. Re-assembling it IN PLACE would rewrite every
    source with this host's newline convention and replace the v1 records,
    so it is refused unless explicitly allowed; re-assemble into a scratch
    intermediate dir (assembly_byte_regression.py) or use a fresh run id."""
    from thesis.assembly.assembly_provenance import (
        AssemblyIntegrityError, LEGACY_ASSEMBLY_CLASS, classify_legacy_run)

    if allow_legacy_rewrite or classify_legacy_run(previous_entries) != LEGACY_ASSEMBLY_CLASS:
        return
    raise AssemblyIntegrityError(
        "[%s] run %s carries a legacy %s record set under %s - refusing to re-assemble "
        "historical evidence in place (sources would be rewritten with this host's "
        "newline convention and the assembly.v1 records replaced). Re-assemble into "
        "a scratch intermediate dir or a fresh run id; pass allow_legacy_rewrite=True "
        "only for a deliberate, documented migration." % (
            model_id, run_id, LEGACY_ASSEMBLY_CLASS, intermediate_dir))


def assemble_model(
    config: dict[str, Any],
    profile: dict[str, Any],
    model_config: dict[str, Any],
    export_pareval_json: bool,
    register_manifest: bool = True,
    allow_legacy_rewrite: bool = False,
) -> dict[str, int]:
    from thesis.assembly import assembly_provenance as ap

    run_id = profile["run_id"]
    model_id = model_config["id"]

    generations_path, _ = common.get_output_paths(config, profile, model_config)

    if not generations_path.exists():
        print(f"[{model_id}] no generations file at {generations_path}, skipping.")
        return {"assembled": 0, "skipped": 0, "warnings": 0}

    intermediate_dir = Path(config["outputs"]["intermediate_dir"]) / run_id / model_id
    sources_dir = intermediate_dir / "sources"
    assembly_path = intermediate_dir / "assembly.jsonl"
    summary_path = intermediate_dir / SUMMARY_FILE_NAME

    assembly_stage = (config.get("stages") or {}).get("assembly") or {}
    auto_close_single_brace = bool(
        assembly_stage.get("auto_close_single_brace", True)
    )

    condition = ap.assembly_condition(config)
    condition_sha = ap.assembly_condition_sha256(condition)

    records = load_generation_records(generations_path)
    refuse_duplicate_sample_ids(records, model_id)

    # Fail-closed re-assembly: the previous assembly.jsonl disappears FIRST.
    # If this pass dies half-way, a reader finds no records at all (and the
    # verifier reports the leftover sources as orphans) instead of records
    # that describe sources from another pass.
    previous_entries = ap.load_assembly_entries(assembly_path)
    refuse_legacy_rewrite(previous_entries, run_id, model_id, intermediate_dir,
                          allow_legacy_rewrite)
    if assembly_path.exists():
        assembly_path.unlink()
    if summary_path.exists():
        summary_path.unlink()
    atomic_io.remove_stale_temp_files(intermediate_dir)

    counts = {
        "records_considered": len(records),
        "assembled": 0,
        "skipped": 0,
        "warnings": 0,
        "duplicates": 0,
        "stale_sources_removed": 0,
    }
    pareval_outputs: dict[str, dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []

    for record in records:
        sample_id = record["sample_id"]
        prompt = record.get("prompt") or {}
        source_path = sources_dir / sample_id / SOURCE_FILE_NAME

        entry: dict[str, Any] = {
            "schema_version": ASSEMBLY_SCHEMA_VERSION,
            "run_id": run_id,
            "model_id": model_id,
            "sample_id": sample_id,
            "created_at_utc": common.utc_now_iso(),
            "generation_truncated": (record.get("status") or {}).get(
                "truncated", False
            ),
            "execution_model": prompt.get("parallelism_model"),
            "benchmark": "%s/%s" % (prompt.get("problem_type"), prompt.get("name"))
            if prompt.get("name") is not None else None,
            "assembly_condition_version": condition["condition_version"],
            "assembly_condition_sha256": condition_sha,
        }

        status = record.get("status") or {}

        if not status.get("success"):
            entry["assembled"] = False
            entry["skip_reason"] = (
                f"generation not successful "
                f"(error_type={status.get('error_type')})"
            )
            # a source from an earlier pass must not survive as "usable"
            entry["stale_source_removed"] = False
            if source_path.is_file():
                atomic_io.remove_stale_temp_files(source_path.parent)
                source_path.unlink()
                entry["stale_source_removed"] = True
                counts["stale_sources_removed"] += 1
            entries.append(entry)
            counts["skipped"] += 1
            continue

        prompt_text = record["prompt"]["prompt_text"]
        raw_text = record["output"]["raw_text"]

        content, result = build_source_content(record, auto_close_single_brace)

        source_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_io.remove_stale_temp_files(source_path.parent)
        write_source(source_path, content)

        facts = ap.source_artifact_facts(source_path)

        entry["assembled"] = True
        entry["source_path"] = source_path.as_posix()
        entry["logical_source_path"] = ap.logical_source_path(model_id, sample_id)
        entry["assembly_input_sha256"] = ap.assembly_input_sha256_of_record(record)
        entry.update(facts)  # source_sha256, newline_convention, byte_size, trailing_newline
        entry["cleaning"] = result.metadata.to_dict()
        entry["drivers"] = driver_paths(record)

        has_warning = (
            not result.metadata.braces_balanced
            or result.metadata.signature_suspect
            or entry["generation_truncated"]
            or not entry["drivers"]["benchmark_dir_exists"]
            or not entry["drivers"]["model_driver_exists"]
        )

        if has_warning:
            counts["warnings"] += 1

        entries.append(entry)
        counts["assembled"] += 1

        if export_pareval_json:
            key = f"{prompt['name']}__{prompt['parallelism_model']}"

            pareval_outputs.setdefault(
                key,
                {
                    "problem_type": prompt["problem_type"],
                    "language": prompt["language"],
                    "name": prompt["name"],
                    "parallelism_model": prompt["parallelism_model"],
                    "prompt": prompt_text,
                    "outputs": [],
                },
            )["outputs"].append(
                (
                    record["generation_parameters"].get("sample_index", 0),
                    (
                        (result.pre_signature_code + "\n")
                        if result.pre_signature_code
                        else ""
                    )
                    + result.body,
                )
            )

    # sources of samples that are no longer in the generation records at all
    # (a previous pass assembled them) are stale as well
    current_ids = {record["sample_id"] for record in records}
    for previous in previous_entries:
        previous_id = previous.get("sample_id")
        if previous_id in current_ids or not previous.get("assembled"):
            continue
        stale = sources_dir / str(previous_id) / SOURCE_FILE_NAME
        if stale.is_file():
            stale.unlink()
            counts["stale_sources_removed"] += 1

    # ONE atomic write of the record file after every source exists
    atomic_io.atomic_write_jsonl(assembly_path, entries)

    summary = ap.assembly_set_summary(model_id, entries, counts)
    summary = OrderedDict(
        [("schema_version", "assembly_summary.v1"), ("run_id", run_id)]
        + list(summary.items())
        + [
            ("assembly_condition_version", condition["condition_version"]),
            ("assembly_condition_sha256", condition_sha),
            ("writer_newline_policy", ASSEMBLY_WRITER_NEWLINE_POLICY),
            ("observed_newline_conventions", _newline_histogram(entries)),
            # facts about THIS assembling process (evidence, never part of a
            # condition hash): they explain the observed newline convention
            ("assembly_host", OrderedDict([
                ("platform", sys.platform),
                ("os_linesep", repr(os.linesep)),
                ("python_version", platform.python_version()),
            ])),
        ]
    )
    atomic_io.atomic_write_json(summary_path, summary)

    if register_manifest:
        from thesis.evaluation import run_manifest

        run_manifest.register_assembly_set(
            config, run_id, model_id,
            sample_count=summary["sample_count"],
            assembly_set_sha256=summary["assembly_set_sha256"],
            assembly_condition_sha256=condition_sha,
            counts=summary["counts"],
        )

    if export_pareval_json and pareval_outputs:
        export = []

        for item in pareval_outputs.values():
            item["outputs"] = [
                output for _, output in sorted(item["outputs"], key=lambda x: x[0])
            ]
            export.append(item)

        export_path = intermediate_dir / "pareval-generations.json"
        common.write_json(export_path, export)
        print(f"[{model_id}] ParEval-format export: {export_path}")

    print(
        f"[{model_id}] assembled: {counts['assembled']}, "
        f"skipped: {counts['skipped']}, with warnings: {counts['warnings']}, "
        f"stale sources removed: {counts['stale_sources_removed']}"
    )
    print(f"[{model_id}] metadata: {assembly_path}")
    print(
        f"[{model_id}] assembly set {summary['assembly_set_sha256'][:12]}... "
        f"({summary['sample_count']} samples) under condition {condition_sha[:12]}..."
    )

    return counts


def _newline_histogram(entries: list[dict[str, Any]]) -> dict[str, int]:
    histogram: dict[str, int] = {}
    for entry in entries:
        if entry.get("assembled"):
            key = str(entry.get("newline_convention"))
            histogram[key] = histogram.get(key, 0) + 1
    return dict(sorted(histogram.items()))


def main() -> None:
    args = parse_args()

    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)

    models = [
        model
        for model in config.get("models", [])
        if model.get("enabled", False)
        and (args.model_id is None or model.get("id") == args.model_id)
    ]

    if not models:
        raise ValueError("No enabled models matched the selection.")

    # freeze the run configuration on first contact with the intermediate
    # run dir (or record config drift) — see run_manifest.py
    from thesis.evaluation.run_manifest import ensure_run_manifest

    ensure_run_manifest(
        config, profile["run_id"], stage="assembly", profile=args.profile
    )

    totals = {"assembled": 0, "skipped": 0, "warnings": 0}

    for model_config in models:
        counts = assemble_model(
            config=config,
            profile=profile,
            model_config=model_config,
            export_pareval_json=args.export_pareval_json,
        )

        for key in totals:
            totals[key] += counts.get(key, 0)

    print()
    print(
        f"Assembly finished. Total assembled: {totals['assembled']}, "
        f"skipped: {totals['skipped']}, with warnings: {totals['warnings']}"
    )


if __name__ == "__main__":
    main()
