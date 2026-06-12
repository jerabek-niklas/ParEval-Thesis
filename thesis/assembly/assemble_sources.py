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
    <intermediate_dir>/<run_id>/<model_id>/assembly.jsonl     (schema assembly.v1)

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
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.assembly import cleaning  # noqa: E402

ASSEMBLY_SCHEMA_VERSION = "assembly.v1"

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

    return {
        "benchmark_dir": str(benchmark_dir),
        "benchmark_dir_exists": (REPO_ROOT / benchmark_dir).is_dir(),
        "model_driver": str(model_driver),
        "model_driver_exists": (REPO_ROOT / model_driver).is_file(),
    }


def assemble_model(
    config: dict[str, Any],
    profile: dict[str, Any],
    model_config: dict[str, Any],
    export_pareval_json: bool,
) -> dict[str, int]:
    run_id = profile["run_id"]
    model_id = model_config["id"]

    generations_path, _ = common.get_output_paths(config, profile, model_config)

    if not generations_path.exists():
        print(f"[{model_id}] no generations file at {generations_path}, skipping.")
        return {"assembled": 0, "skipped": 0, "warnings": 0}

    intermediate_dir = Path(config["outputs"]["intermediate_dir"]) / run_id / model_id
    sources_dir = intermediate_dir / "sources"
    assembly_path = intermediate_dir / "assembly.jsonl"

    if assembly_path.exists():
        assembly_path.unlink()

    counts = {"assembled": 0, "skipped": 0, "warnings": 0}
    pareval_outputs: dict[str, dict[str, Any]] = {}

    with generations_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            record = json.loads(line)
            sample_id = record["sample_id"]

            entry: dict[str, Any] = {
                "schema_version": ASSEMBLY_SCHEMA_VERSION,
                "run_id": run_id,
                "model_id": model_id,
                "sample_id": sample_id,
                "created_at_utc": common.utc_now_iso(),
                "generation_truncated": (record.get("status") or {}).get(
                    "truncated", False
                ),
            }

            status = record.get("status") or {}

            if not status.get("success"):
                entry["assembled"] = False
                entry["skip_reason"] = (
                    f"generation not successful "
                    f"(error_type={status.get('error_type')})"
                )
                common.append_jsonl(assembly_path, entry)
                counts["skipped"] += 1
                continue

            prompt_text = record["prompt"]["prompt_text"]
            raw_text = record["output"]["raw_text"]

            result = cleaning.clean_for_assembly(prompt_text, raw_text)
            content = assemble_content(prompt_text, result)
            result.metadata.braces_balanced = cleaning.braces_balanced(content)

            source_path = sources_dir / sample_id / "generated-code.hpp"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(content, encoding="utf-8")

            entry["assembled"] = True
            entry["source_path"] = str(source_path)
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

            common.append_jsonl(assembly_path, entry)
            counts["assembled"] += 1

            if export_pareval_json:
                prompt = record["prompt"]
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
        f"skipped: {counts['skipped']}, with warnings: {counts['warnings']}"
    )
    print(f"[{model_id}] metadata: {assembly_path}")

    return counts


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

    totals = {"assembled": 0, "skipped": 0, "warnings": 0}

    for model_config in models:
        counts = assemble_model(
            config=config,
            profile=profile,
            model_config=model_config,
            export_pareval_json=args.export_pareval_json,
        )

        for key in totals:
            totals[key] += counts[key]

    print()
    print(
        f"Assembly finished. Total assembled: {totals['assembled']}, "
        f"skipped: {totals['skipped']}, with warnings: {totals['warnings']}"
    )


if __name__ == "__main__":
    main()
