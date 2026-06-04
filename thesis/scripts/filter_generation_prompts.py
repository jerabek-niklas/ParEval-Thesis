import json
from pathlib import Path
from collections import Counter

INPUT_FILE = Path("prompts/generation-prompts.json")
OUTPUT_FILE = Path("thesis/prompts/generation-prompts-serial-omp-mpi.json")

KEEP_MODELS = {"serial", "omp", "mpi"}

def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Could not find {INPUT_FILE}")

    with INPUT_FILE.open("r", encoding="utf-8") as f:
        prompts = json.load(f)

    filtered = [
        item for item in prompts
        if item.get("parallelism_model") in KEEP_MODELS
    ]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2)

    print(f"Original prompts: {len(prompts)}")
    print(f"Filtered prompts: {len(filtered)}")
    print()

    print("By parallelism model:")
    for model, count in sorted(Counter(item["parallelism_model"] for item in filtered).items()):
        print(f"  {model}: {count}")

    print()

    print("By problem type:")
    for problem_type, count in sorted(Counter(item["problem_type"] for item in filtered).items()):
        print(f"  {problem_type}: {count}")

if __name__ == "__main__":
    main()