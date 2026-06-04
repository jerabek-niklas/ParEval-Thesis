"""
Create a generation-prompts JSON file for the thesis subset of ParEval.

Expected folder structure:

thesis/prompts/
├── create_generation_prompts.py
├── raw/
│   ├── <problem_type>/
│   │   ├── <problem_name>/
│   │   │   ├── serial
│   │   │   ├── omp
│   │   │   └── mpi
│   │   └── ...
│   └── ...
└── generation-prompts-thesis.json

Output format:

[
  {
    "problem_type": "reduce",
    "language": "cpp",
    "name": "01_problem_name",
    "parallelism_model": "omp",
    "prompt": "..."
  }
]
"""

from argparse import ArgumentParser
from pathlib import Path
from collections import Counter
import json
import re


SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_RAW_ROOT = SCRIPT_DIR / "raw"
DEFAULT_OUTPUT = SCRIPT_DIR / "generation-prompts-thesis.json"

KEEP_MODELS = ["serial", "omp", "mpi"]


class PromptValidator:
    def __init__(self, model: str):
        self.model = model

    def check_valid(self, prompt: str, prompt_path: Path) -> None:
        if not prompt.strip():
            raise ValueError(f"Prompt is empty: {prompt_path}")

        if not prompt.rstrip().endswith("{"):
            raise ValueError(f"Prompt does not end with '{{': {prompt_path}")

        for required in ["Example", "input:", "output:"]:
            if required not in prompt:
                raise ValueError(
                    f"Prompt does not contain required substring '{required}': {prompt_path}"
                )

        if self.model == "omp" and "OpenMP" not in prompt:
            raise ValueError(f"OpenMP prompt does not contain 'OpenMP': {prompt_path}")

        if self.model == "mpi":
            for required in ["MPI", "initialized"]:
                if required not in prompt:
                    raise ValueError(
                        f"MPI prompt does not contain required substring '{required}': {prompt_path}"
                    )

    def function_suffix(self) -> str:
        if self.model == "serial":
            return ""
        if self.model == "omp":
            return "OpenMP"
        if self.model == "mpi":
            return "MPI"
        raise ValueError(f"Unknown model: {self.model}")

    def add_imports(self, prompt: str) -> str:
        if self.model == "omp" and "#include <omp.h>" not in prompt:
            return "#include <omp.h>\n\n" + prompt

        if self.model == "mpi" and "#include <mpi.h>" not in prompt:
            return "#include <mpi.h>\n\n" + prompt

        return prompt


def parse_args():
    parser = ArgumentParser(
        description="Create thesis generation-prompts JSON from copied raw ParEval prompts."
    )

    parser.add_argument(
        "--raw-root",
        default=str(DEFAULT_RAW_ROOT),
        help=f"Path to copied raw prompts. Default: {DEFAULT_RAW_ROOT}",
    )

    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Path to output JSON file. Default: {DEFAULT_OUTPUT}",
    )

    parser.add_argument(
        "--models",
        nargs="+",
        default=KEEP_MODELS,
        choices=KEEP_MODELS,
        help="Execution models to include. Default: serial omp mpi",
    )

    parser.add_argument(
        "--function-suffix",
        choices=["none", "model", "parallel"],
        default="none",
        help="Optionally append a suffix to function names. Default: none",
    )

    parser.add_argument(
        "--add-imports",
        action="store_true",
        help="Add #include <omp.h> and #include <mpi.h> to OpenMP/MPI prompts.",
    )

    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip prompt validation.",
    )

    return parser.parse_args()


def append_to_function_name(prompt: str, suffix: str) -> str:
    if not suffix:
        return prompt

    lines = prompt.splitlines()

    if not lines:
        raise ValueError("Prompt has no lines.")

    header = lines[-1]

    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", header)

    if not match:
        raise ValueError(f"Could not find function name in prompt header: {header}")

    function_name = match.group(1)
    new_function_name = function_name + suffix

    lines[-1] = (
        header[: match.start(1)]
        + new_function_name
        + header[match.end(1):]
    )

    return "\n".join(lines)


def iter_problem_dirs(raw_root: Path):
    for problem_type_dir in sorted(raw_root.iterdir()):
        if not problem_type_dir.is_dir():
            continue

        problem_type = problem_type_dir.name

        for problem_dir in sorted(problem_type_dir.iterdir()):
            if not problem_dir.is_dir():
                continue

            yield problem_type, problem_dir.name, problem_dir


def parse_prompt_file(
    problem_type: str,
    problem_name: str,
    model: str,
    prompt_path: Path,
    validate: bool,
    function_suffix: str,
    add_imports: bool,
) -> dict:
    prompt = prompt_path.read_text(encoding="utf-8")

    validator = PromptValidator(model)

    if validate:
        validator.check_valid(prompt, prompt_path)

    if function_suffix == "model":
        prompt = append_to_function_name(prompt, validator.function_suffix())
    elif function_suffix == "parallel":
        prompt = append_to_function_name(prompt, "Parallel")

    if add_imports:
        prompt = validator.add_imports(prompt)

    return {
        "problem_type": problem_type,
        "language": "cpp",
        "name": problem_name,
        "parallelism_model": model,
        "prompt": prompt,
    }


def main():
    args = parse_args()

    raw_root = Path(args.raw_root)
    output_path = Path(args.output)
    selected_models = list(args.models)

    if not raw_root.exists():
        raise FileNotFoundError(f"Raw prompts root does not exist: {raw_root}")

    all_prompts = []
    missing_files = []

    for problem_type, problem_name, problem_dir in iter_problem_dirs(raw_root):
        for model in selected_models:
            prompt_path = problem_dir / model

            if not prompt_path.exists():
                missing_files.append(prompt_path)
                continue

            if not prompt_path.is_file():
                raise ValueError(f"Expected file but found non-file path: {prompt_path}")

            prompt_entry = parse_prompt_file(
                problem_type=problem_type,
                problem_name=problem_name,
                model=model,
                prompt_path=prompt_path,
                validate=not args.no_validate,
                function_suffix=args.function_suffix,
                add_imports=args.add_imports,
            )

            all_prompts.append(prompt_entry)

    if missing_files:
        print("\nMissing prompt files:")
        for path in missing_files:
            print(f"  {path}")

        raise FileNotFoundError(f"Missing {len(missing_files)} expected prompt files.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(all_prompts, f, indent=2)

    by_model = Counter(p["parallelism_model"] for p in all_prompts)
    by_problem_type = Counter(p["problem_type"] for p in all_prompts)

    print(f"\nWrote {len(all_prompts)} prompts to:")
    print(f"  {output_path}")

    print("\nBy execution model:")
    for model, count in sorted(by_model.items()):
        print(f"  {model}: {count}")

    print("\nBy problem type:")
    for problem_type, count in sorted(by_problem_type.items()):
        print(f"  {problem_type}: {count}")


if __name__ == "__main__":
    main()