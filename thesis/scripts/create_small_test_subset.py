import json
from pathlib import Path

INPUT = Path("thesis/prompts/generation-prompts-serial-omp-mpi.json")
OUTPUT = Path("thesis/prompts/generation-prompts-smoke-test.json")

with INPUT.open("r", encoding="utf-8") as f:
    prompts = json.load(f)

selected = []
for model in ["serial", "omp", "mpi"]:
    selected.append(next(p for p in prompts if p["parallelism_model"] == model))

with OUTPUT.open("w", encoding="utf-8") as f:
    json.dump(selected, f, indent=2)

print(f"Wrote {len(selected)} prompts to {OUTPUT}")