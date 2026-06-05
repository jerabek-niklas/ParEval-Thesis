"""
Validate generation JSONL files produced by the thesis generation pipeline.

This script checks:
- whether the JSONL file is readable
- whether every line has the expected schema
- whether sample_id values are unique
- whether successful generations contain raw_text and cleaned_code
- whether failed generations contain error information
- optionally whether the number of records matches the selected config profile
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from thesis.config.load_config import load_config
except ImportError:
    load_config = None


VALID_EXECUTION_MODELS = {"serial", "omp", "mpi"}

REQUIRED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "run_id",
    "sample_id",
    "created_at_utc",
    "model",
    "prompt",
    "generation_parameters",
    "output",
    "status",
}

REQUIRED_MODEL_FIELDS = {
    "id",
    "provider",
    "model_name",
}

REQUIRED_PROMPT_FIELDS = {
    "problem_type",
    "name",
    "language",
    "parallelism_model",
    "prompt_field",
    "prompt_text",
}

REQUIRED_OUTPUT_FIELDS = {
    "raw_text",
    "cleaned_code",
}

REQUIRED_STATUS_FIELDS = {
    "success",
    "error_type",
    "error_message",
    "duration_seconds",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate thesis generation JSONL output files."
    )

    parser.add_argument(
        "--input",
        default=None,
        help="Path to one generations.jsonl file. If omitted, path is inferred from config/profile/model-id.",
    )

    parser.add_argument(
        "--config",
        default="thesis/config/config.yaml",
        help="Path to central config YAML. Used when --input is omitted or for expected-count validation.",
    )

    parser.add_argument(
        "--profile",
        default="smoke",
        help="Profile name from config. Default: smoke.",
    )

    parser.add_argument(
        "--model-id",
        default=None,
        help="Optional model id. If omitted, all model output files for the profile are validated.",
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as validation errors.",
    )

    parser.add_argument(
        "--summary-output",
        default=None,
        help="Optional path to write validation summary JSON.",
    )

    return parser.parse_args()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = []
    invalid_lines = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as error:
                invalid_lines.append(
                    {
                        "line": line_number,
                        "error": str(error),
                        "content_preview": line[:200],
                    }
                )
                continue

            if not isinstance(parsed, dict):
                invalid_lines.append(
                    {
                        "line": line_number,
                        "error": "Line is valid JSON but not a JSON object.",
                        "content_preview": line[:200],
                    }
                )
                continue

            parsed["_line_number"] = line_number
            records.append(parsed)

    return records, invalid_lines


def get_nested_dict(record: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = record.get(key)

    if isinstance(value, dict):
        return value

    return None


def missing_fields(obj: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(field for field in required if field not in obj)


def is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_record(record: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []

    line = record.get("_line_number", "?")
    sample_id = record.get("sample_id", "<missing sample_id>")

    top_missing = missing_fields(record, REQUIRED_TOP_LEVEL_FIELDS)

    if top_missing:
        errors.append(
            f"line {line}, sample {sample_id}: missing top-level fields: {top_missing}"
        )

    model = get_nested_dict(record, "model")

    if model is None:
        errors.append(f"line {line}, sample {sample_id}: field 'model' is not an object")
    else:
        model_missing = missing_fields(model, REQUIRED_MODEL_FIELDS)

        if model_missing:
            errors.append(
                f"line {line}, sample {sample_id}: missing model fields: {model_missing}"
            )

    prompt = get_nested_dict(record, "prompt")

    if prompt is None:
        errors.append(f"line {line}, sample {sample_id}: field 'prompt' is not an object")
    else:
        prompt_missing = missing_fields(prompt, REQUIRED_PROMPT_FIELDS)

        if prompt_missing:
            errors.append(
                f"line {line}, sample {sample_id}: missing prompt fields: {prompt_missing}"
            )

        execution_model = prompt.get("parallelism_model")

        if execution_model not in VALID_EXECUTION_MODELS:
            errors.append(
                f"line {line}, sample {sample_id}: invalid parallelism_model: {execution_model}"
            )

        if not is_nonempty_string(prompt.get("prompt_text")):
            errors.append(
                f"line {line}, sample {sample_id}: prompt.prompt_text is empty or not a string"
            )

    output = get_nested_dict(record, "output")

    if output is None:
        errors.append(f"line {line}, sample {sample_id}: field 'output' is not an object")
    else:
        output_missing = missing_fields(output, REQUIRED_OUTPUT_FIELDS)

        if output_missing:
            errors.append(
                f"line {line}, sample {sample_id}: missing output fields: {output_missing}"
            )

    status = get_nested_dict(record, "status")

    if status is None:
        errors.append(f"line {line}, sample {sample_id}: field 'status' is not an object")
    else:
        status_missing = missing_fields(status, REQUIRED_STATUS_FIELDS)

        if status_missing:
            errors.append(
                f"line {line}, sample {sample_id}: missing status fields: {status_missing}"
            )

        success = status.get("success")

        if not isinstance(success, bool):
            errors.append(
                f"line {line}, sample {sample_id}: status.success must be boolean"
            )

        if success is True:
            if output is not None:
                if not is_nonempty_string(output.get("raw_text")):
                    errors.append(
                        f"line {line}, sample {sample_id}: successful record has empty output.raw_text"
                    )

                if not is_nonempty_string(output.get("cleaned_code")):
                    errors.append(
                        f"line {line}, sample {sample_id}: successful record has empty output.cleaned_code"
                    )

                cleaned_code = output.get("cleaned_code")

                if isinstance(cleaned_code, str) and "```" in cleaned_code:
                    warnings.append(
                        f"line {line}, sample {sample_id}: cleaned_code still contains Markdown fence"
                    )

            if status.get("error_type") is not None or status.get("error_message") is not None:
                warnings.append(
                    f"line {line}, sample {sample_id}: successful record still contains error information"
                )

        if success is False:
            if not is_nonempty_string(status.get("error_type")):
                errors.append(
                    f"line {line}, sample {sample_id}: failed record has empty status.error_type"
                )

            if not is_nonempty_string(status.get("error_message")):
                errors.append(
                    f"line {line}, sample {sample_id}: failed record has empty status.error_message"
                )

        duration = status.get("duration_seconds")

        if duration is not None and not isinstance(duration, (int, float)):
            warnings.append(
                f"line {line}, sample {sample_id}: status.duration_seconds is not numeric"
            )

    if not is_nonempty_string(record.get("sample_id")):
        errors.append(f"line {line}: sample_id is empty or missing")

    if not is_nonempty_string(record.get("run_id")):
        errors.append(f"line {line}, sample {sample_id}: run_id is empty or missing")

    return errors, warnings


def load_config_if_available(config_path: Path) -> dict[str, Any] | None:
    if load_config is None:
        return None

    if not config_path.exists():
        return None

    return load_config(config_path)


def get_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})

    if profile_name not in profiles:
        available = ", ".join(profiles.keys())
        raise KeyError(
            f"Profile '{profile_name}' not found in config. Available profiles: {available}"
        )

    return profiles[profile_name]


def infer_generation_files(
    config: dict[str, Any],
    profile_name: str,
    model_id: str | None,
) -> list[Path]:
    profile = get_profile(config, profile_name)
    run_id = profile["run_id"]

    outputs = config.get("outputs", {})
    raw_dir = Path(outputs.get("raw_dir", "thesis/results/raw"))

    run_dir = raw_dir / run_id

    if model_id:
        return [run_dir / model_id / "generations.jsonl"]

    if not run_dir.exists():
        return []

    return sorted(run_dir.glob("*/generations.jsonl"))


def compute_expected_count(
    config: dict[str, Any],
    profile_name: str,
) -> int | None:
    profile = get_profile(config, profile_name)

    prompts_config = config.get("prompts", {})
    prompt_path = Path(prompts_config.get("path", ""))

    if not prompt_path.exists():
        return None

    prompts = read_json(prompt_path)

    if not isinstance(prompts, list):
        return None

    execution_models = prompts_config.get("execution_models")
    problem_types = prompts_config.get("problem_types")
    prompt_limit = profile.get("prompt_limit")
    num_samples_per_prompt = int(profile.get("num_samples_per_prompt", 1))

    filtered = prompts

    if execution_models:
        allowed_execution_models = set(execution_models)
        filtered = [
            prompt for prompt in filtered
            if prompt.get("parallelism_model") in allowed_execution_models
        ]

    if problem_types:
        allowed_problem_types = set(problem_types)
        filtered = [
            prompt for prompt in filtered
            if prompt.get("problem_type") in allowed_problem_types
        ]

    if prompt_limit is not None:
        filtered = filtered[: int(prompt_limit)]

    return len(filtered) * num_samples_per_prompt


def validate_file(
    path: Path,
    expected_count: int | None,
    strict: bool,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "records": 0,
        "success": 0,
        "error": 0,
        "invalid_json_lines": 0,
        "duplicate_sample_ids": [],
        "expected_count": expected_count,
        "errors": [],
        "warnings": [],
        "by_execution_model": {},
        "by_problem_type": {},
    }

    if not path.exists():
        summary["errors"].append(f"File does not exist: {path}")
        return summary

    records, invalid_lines = read_jsonl(path)

    summary["records"] = len(records)
    summary["invalid_json_lines"] = len(invalid_lines)

    for invalid in invalid_lines:
        summary["errors"].append(
            f"line {invalid['line']}: invalid JSON: {invalid['error']}"
        )

    sample_ids = [record.get("sample_id") for record in records if record.get("sample_id")]
    sample_id_counts = Counter(sample_ids)
    duplicates = sorted(
        sample_id for sample_id, count in sample_id_counts.items() if count > 1
    )

    summary["duplicate_sample_ids"] = duplicates

    for duplicate in duplicates:
        summary["errors"].append(f"Duplicate sample_id: {duplicate}")

    execution_model_counter = Counter()
    problem_type_counter = Counter()

    for record in records:
        status = record.get("status", {})
        prompt = record.get("prompt", {})

        if isinstance(status, dict):
            if status.get("success") is True:
                summary["success"] += 1
            elif status.get("success") is False:
                summary["error"] += 1

        if isinstance(prompt, dict):
            execution_model_counter[prompt.get("parallelism_model")] += 1
            problem_type_counter[prompt.get("problem_type")] += 1

        record_errors, record_warnings = validate_record(record)
        summary["errors"].extend(record_errors)
        summary["warnings"].extend(record_warnings)

    summary["by_execution_model"] = dict(sorted(execution_model_counter.items()))
    summary["by_problem_type"] = dict(sorted(problem_type_counter.items()))

    if expected_count is not None and len(records) != expected_count:
        summary["errors"].append(
            f"Record count mismatch: expected {expected_count}, found {len(records)}"
        )

    if strict and summary["warnings"]:
        summary["errors"].extend(
            [f"STRICT WARNING: {warning}" for warning in summary["warnings"]]
        )

    return summary


def print_file_summary(summary: dict[str, Any]) -> None:
    print()
    print(f"File: {summary['path']}")
    print("-" * 80)
    print(f"Exists:             {summary['exists']}")
    print(f"Records:            {summary['records']}")
    print(f"Expected count:     {summary['expected_count']}")
    print(f"Success:            {summary['success']}")
    print(f"Error records:      {summary['error']}")
    print(f"Invalid JSON lines: {summary['invalid_json_lines']}")
    print(f"Duplicate IDs:      {len(summary['duplicate_sample_ids'])}")
    print(f"Warnings:           {len(summary['warnings'])}")
    print(f"Errors:             {len(summary['errors'])}")

    if summary["by_execution_model"]:
        print("By execution model:")
        for key, value in summary["by_execution_model"].items():
            print(f"  {key}: {value}")

    if summary["errors"]:
        print()
        print("First errors:")
        for error in summary["errors"][:10]:
            print(f"  - {error}")

    if summary["warnings"]:
        print()
        print("First warnings:")
        for warning in summary["warnings"][:10]:
            print(f"  - {warning}")


def main() -> None:
    args = parse_args()

    config_path = Path(args.config)
    config = load_config_if_available(config_path)

    if args.input:
        files = [Path(args.input)]
    else:
        if config is None:
            raise ValueError(
                "No --input provided and config could not be loaded. "
                "Provide --input or a valid --config."
            )

        files = infer_generation_files(
            config=config,
            profile_name=args.profile,
            model_id=args.model_id,
        )

    if not files:
        raise FileNotFoundError("No generation JSONL files found to validate.")

    expected_count = None

    if config is not None:
        expected_count = compute_expected_count(
            config=config,
            profile_name=args.profile,
        )

    all_summaries = []

    for file_path in files:
        summary = validate_file(
            path=file_path,
            expected_count=expected_count,
            strict=args.strict,
        )
        all_summaries.append(summary)
        print_file_summary(summary)

    total_errors = sum(len(summary["errors"]) for summary in all_summaries)
    total_warnings = sum(len(summary["warnings"]) for summary in all_summaries)

    final_summary = {
        "files_validated": len(all_summaries),
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "files": all_summaries,
    }

    if args.summary_output:
        write_json(Path(args.summary_output), final_summary)
        print()
        print(f"Wrote validation summary to: {args.summary_output}")

    print()
    print("Validation finished.")
    print(f"Total errors:   {total_errors}")
    print(f"Total warnings: {total_warnings}")

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()