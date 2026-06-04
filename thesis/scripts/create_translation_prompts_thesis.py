from argparse import ArgumentParser
from glob import glob
from pathlib import Path
from typing import Optional
import json
import re


TRANSLATION_TASKS = [
    ("serial", "omp"),
    ("serial", "mpi"),
]

EXECUTION_MODEL_CLEAN_NAME_MAP = {
    "serial": "Serial",
    "omp": "OpenMP",
    "mpi": "MPI",
}

TRANSLATION_PROMPT_FORMAT = """// {src_model} implementation of {function_name}
{src_model_example}

// {dst_model} implementation of {function_name}
{dst_model_prompt}
"""

CPU_FUNCTION_NAME_PATTERN = re.compile(r"\s*[a-zA-Z_][a-zA-Z0-9_:<>*&\s]*\s+([a-zA-Z0-9_]+)\s*\(")


def get_args():
    parser = ArgumentParser(
        description="Create Serial-to-OpenMP and Serial-to-MPI translation prompts for thesis experiments."
    )
    parser.add_argument(
        "--generation-prompts",
        type=str,
        default="thesis/prompts/generation-prompts-serial-omp-mpi.json",
        help="Path to filtered generation prompts."
    )
    parser.add_argument(
        "--results-root",
        type=str,
        required=True,
        help="Path to results root directory containing */results.json files."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="thesis/prompts/translation-prompts-serial-to-omp-mpi.json",
        help="Path to output JSON file."
    )
    return parser.parse_args()


def read_json(path: str | Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_function_name(prompt: str) -> str:
    lines = [line for line in prompt.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Prompt is empty.")

    header = lines[-1]
    match = CPU_FUNCTION_NAME_PATTERN.match(header)

    if match is None:
        raise ValueError(f"Could not find function name in prompt header: {header}")

    return match.group(1)


def prepend_to_every_line(text: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def find_correct_implementation(
    task_name: str,
    src_model: str,
    all_results: list[list[dict]]
) -> Optional[str]:
    """
    Search all result files for a correct generated implementation of a given task
    and execution model.
    """
    for results in all_results:
        matching = [
            r for r in results
            if r.get("name") == task_name and r.get("parallelism_model") == src_model
        ]

        if len(matching) != 1:
            continue

        outputs = matching[0].get("outputs", [])

        correct_outputs = [
            output for output in outputs
            if output.get("are_all_valid") is True
        ]

        if correct_outputs:
            return correct_outputs[0].get("generated_output")

    return None


def main():
    args = get_args()

    generation_prompts = read_json(args.generation_prompts)

    # Load result files.
    result_paths = glob(str(Path(args.results_root) / "*" / "results.json"))
    all_results = [read_json(path) for path in result_paths]

    print(f"Loaded {len(generation_prompts)} generation prompts.")
    print(f"Loaded {len(all_results)} result files.")

    translation_prompts = []

    for src_model, dst_model in TRANSLATION_TASKS:
        src_prompts = [
            p for p in generation_prompts
            if p.get("parallelism_model") == src_model
        ]
        dst_prompts = [
            p for p in generation_prompts
            if p.get("parallelism_model") == dst_model
        ]

        print(f"\nCreating prompts for {src_model} -> {dst_model}")
        print(f"Source prompts: {len(src_prompts)}")
        print(f"Destination prompts: {len(dst_prompts)}")

        for dst_prompt in dst_prompts:
            task_name = dst_prompt["name"]

            correct_impl = find_correct_implementation(
                task_name=task_name,
                src_model=src_model,
                all_results=all_results
            )

            if correct_impl is None:
                print(f"Skipping {task_name}: no correct {src_model} implementation found.")
                continue

            matching_src_prompts = [
                p for p in src_prompts
                if p["name"] == task_name
            ]

            if len(matching_src_prompts) != 1:
                print(f"Skipping {task_name}: expected one matching source prompt, found {len(matching_src_prompts)}.")
                continue

            src_prompt = matching_src_prompts[0]["prompt"]
            dst_model_prompt = dst_prompt["prompt"]

            function_name = get_function_name(dst_model_prompt)

            src_model_clean = EXECUTION_MODEL_CLEAN_NAME_MAP[src_model]
            dst_model_clean = EXECUTION_MODEL_CLEAN_NAME_MAP[dst_model]

            src_example = prepend_to_every_line(
                src_prompt + "\n" + correct_impl,
                "// "
            )

            translation_prompt_text = TRANSLATION_PROMPT_FORMAT.format(
                src_model=src_model_clean,
                dst_model=dst_model_clean,
                function_name=function_name,
                src_model_example=src_example,
                dst_model_prompt=dst_model_prompt
            )

            translation_prompt = dst_prompt.copy()
            translation_prompt["translation_prompt"] = translation_prompt_text
            translation_prompt["translation_src_model"] = src_model
            translation_prompt["translation_dst_model"] = dst_model
            translation_prompt["translation_src_example"] = src_prompt + "\n" + correct_impl
            translation_prompt["translation_function_name"] = function_name

            translation_prompts.append(translation_prompt)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(translation_prompts, f, indent=2)

    print(f"\nWrote {len(translation_prompts)} translation prompts to {output_path}")


if __name__ == "__main__":
    main()