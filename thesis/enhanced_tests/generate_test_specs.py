"""LLM seed generation for enhanced-test input specs.

Reuses the existing generation infrastructure (thesis/generation/common.py +
the provider adapters) instead of new API plumbing: the adapter supplies
create_client/generate incl. retries, truncation and refusal handling; this
script only builds different prompts and parses/validates a different output.

Per parameterizable benchmark the model receives the problem description +
signature (the serial ParEval prompt, incl. prompt-defined types), the
BASELINE reference implementation (baseline.hpp), the available fill
patterns and the spec JSON schema, and is asked for 5-8 edge-case specs
with rationale. The response must be a strict JSON array; invalid responses
are retried (max 2 retries), invalid items discarded and logged. Which
model generates the specs comes from config (stages.enhanced_tests.
spec_model) — a deliberate, documented methodology decision, not a
hardcoded choice.

Usage (host or main container, needs the spec model's API key):
    python thesis/enhanced_tests/generate_test_specs.py \
        --config thesis/config/config.yaml [--limit 3] [--benchmark <type>/<name>]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.enhanced_tests.specs import (  # noqa: E402
    DEFAULT_MAX_SPEC_SIZE,
    PATTERNS,
    validate_spec,
)

BENCHMARKS_DIR = REPO_ROOT / "drivers" / "cpp" / "benchmarks"
PROMPTS_JSON = REPO_ROOT / "prompts" / "generation-prompts.json"
DEFAULT_OUTPUT = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"

MAX_RETRIES = 2

# provider -> (script file, adapter class); mirrors generate.py's script map
ADAPTERS = {
    "openai": ("generate-openai.py", "OpenAIAdapter"),
    "gemini": ("generate-gemini.py", "GeminiAdapter"),
    "anthropic": ("generate-anthropic.py", "AnthropicAdapter"),
    "openai_compatible": ("generate-openai-compatible.py", "OpenAICompatibleAdapter"),
}

SPEC_SCHEMA_DOC = """[
  {
    "size": <int, 0..%(max_size)d>,
    "pattern": <one of: %(patterns)s>,
    "pattern_params": {"value_range": [<lo>, <hi>]},   // optional
    "rationale": "<one sentence: which edge case / branch this targets>"
  },
  ...
]"""


def load_adapter(provider: str) -> Any:
    script_name, class_name = ADAPTERS[provider]
    script_path = REPO_ROOT / "thesis" / "generation" / script_name

    spec = importlib.util.spec_from_file_location(script_name.replace("-", "_"), script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return getattr(module, class_name)()


def parameterizable_benchmarks() -> "list[tuple[str, Path]]":
    result = []
    for cpu_cc in sorted(BENCHMARKS_DIR.glob("*/*/cpu.cc")):
        if "ENHANCED_TEST_SIZE_DEFAULT" in cpu_cc.read_text(encoding="utf-8"):
            benchmark_dir = cpu_cc.parent
            result.append((f"{benchmark_dir.parent.name}/{benchmark_dir.name}", benchmark_dir))
    return result


def load_serial_prompts() -> dict:
    prompts = json.loads(PROMPTS_JSON.read_text(encoding="utf-8"))
    return {
        entry["name"]: entry["prompt"]
        for entry in prompts
        if entry.get("parallelism_model") == "serial"
    }


def build_user_prompt(benchmark: str, serial_prompt: str, baseline: str, max_size: int) -> str:
    schema = SPEC_SCHEMA_DOC % {
        "max_size": max_size,
        "patterns": ", ".join(f'"{p}"' for p in PATTERNS),
    }

    return f"""You are designing edge-case test inputs for a differential test of the
following C++ benchmark function. A candidate implementation will be run
against the reference implementation below on inputs described by "specs".

PROBLEM AND SIGNATURE:
```cpp
{serial_prompt.rstrip()}
```

REFERENCE IMPLEMENTATION (the test oracle — read it carefully):
```cpp
{baseline.rstrip()}
```

INPUT MODEL: the test harness creates the input container(s) with a given
`size` and fills them with a `pattern`:
- random: uniform values in value_range (default range of the benchmark)
- all_zeros | all_same | ascending | descending | alternating | extreme_values
  (extreme_values alternates numeric_limits lowest/max)
An optional value_range [lo, hi] overrides the fill bounds.

TASK: propose 5-8 specs that are likely to expose bugs a plain random test
misses. Explicitly target branches and special cases OF THE REFERENCE
IMPLEMENTATION: divisions (zero divisors), loop bounds (off-by-one),
recursion base cases, sign handling, duplicate/equal elements, overflow.
Sizes must be small (edge sizes like 0/1/2/3 and small odd/even sizes are
good; stay <= {max_size}).

OUTPUT: ONLY a JSON array following exactly this schema — no markdown, no
explanations outside the array:
{schema}"""


def parse_spec_response(raw_text: str) -> "list | None":
    text = raw_text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```"))

    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None

    return data if isinstance(data, list) else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LLM edge-case specs per benchmark.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=None, help="Only the first N benchmarks.")
    parser.add_argument("--benchmark", default=None, help="Single benchmark (<type>/<name>).")
    args = parser.parse_args()

    config = load_config(Path(args.config).resolve())
    stage = (config.get("stages") or {}).get("enhanced_tests") or {}

    spec_model_id = stage.get("spec_model")
    if not spec_model_id:
        raise SystemExit("stages.enhanced_tests.spec_model is not set in the config.")

    max_size = int(stage.get("max_spec_size", DEFAULT_MAX_SPEC_SIZE))

    system_prompt = stage.get("spec_system_prompt")
    if not system_prompt:
        raise SystemExit("stages.enhanced_tests.spec_system_prompt is not set in the config.")

    models = [m for m in config.get("models", []) if m.get("id") == spec_model_id]
    if not models:
        raise SystemExit(f"spec_model '{spec_model_id}' not found in config models.")

    model_config = models[0]
    provider = model_config["provider"]

    adapter = load_adapter(provider)
    api_key = common.get_api_key(model_config, adapter.default_api_key_env)
    client = adapter.create_client(model_config, api_key)
    generation_defaults = config.get("generation_defaults", {})

    benchmarks = parameterizable_benchmarks()
    if args.benchmark:
        benchmarks = [(b, d) for b, d in benchmarks if b == args.benchmark]
    if args.limit:
        benchmarks = benchmarks[: args.limit]

    serial_prompts = load_serial_prompts()
    known = {b for b, _ in benchmarks}

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    discarded_path = output_path.with_name(output_path.stem + "_discarded.jsonl")

    accepted_total = 0
    discarded_total = 0

    print(f"Spec generation | model: {spec_model_id} ({provider}) | benchmarks: {len(benchmarks)}")
    print(f"Output: {output_path}")

    with output_path.open("w", encoding="utf-8") as out, discarded_path.open(
        "w", encoding="utf-8"
    ) as discarded_out:
        for benchmark, benchmark_dir in benchmarks:
            name = benchmark_dir.name

            if name not in serial_prompts:
                print(f"  [{benchmark}] no serial prompt, skipping")
                continue

            baseline = (benchmark_dir / "baseline.hpp").read_text(encoding="utf-8")
            user_prompt = build_user_prompt(
                benchmark, serial_prompts[name], baseline, max_size
            )

            specs = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    result = adapter.generate(
                        client=client,
                        model_config=model_config,
                        generation_defaults=generation_defaults,
                        system_prompt=system_prompt,
                        messages=[{"role": "user", "content": user_prompt}],
                        retry_attempts=2,
                        sleep_seconds=0.0,
                    )
                except common.ModelRefusal as refusal:
                    print(f"  [{benchmark}] refused: {refusal}")
                    break
                except Exception as error:  # noqa: BLE001 - logged, benchmark skipped
                    print(f"  [{benchmark}] API error: {error}")
                    break

                specs = parse_spec_response(result.raw_text)

                if specs is not None:
                    break

                print(f"  [{benchmark}] unparseable JSON (attempt {attempt + 1}), retrying")

            if specs is None:
                discarded_out.write(
                    json.dumps({"benchmark": benchmark, "reason": "no valid JSON array"}) + "\n"
                )
                discarded_total += 1
                continue

            accepted = 0
            for item in specs:
                if isinstance(item, dict):
                    # the loop, not the model, decides the benchmark; fill in
                    # the fixed fields before validation
                    item["benchmark"] = benchmark
                    item["source"] = "llm"
                    item.setdefault("pattern_params", {})

                ok, reason = validate_spec(item, known, max_size)

                if ok:
                    out.write(json.dumps(item, ensure_ascii=False) + "\n")
                    accepted += 1
                else:
                    discarded_out.write(
                        json.dumps({"benchmark": benchmark, "reason": reason, "spec": item}) + "\n"
                    )
                    discarded_total += 1

            accepted_total += accepted
            print(f"  [{benchmark}] accepted {accepted}/{len(specs)}")

    print(f"\naccepted: {accepted_total}, discarded: {discarded_total}")
    print(f"specs: {output_path}\ndiscarded log: {discarded_path}")


if __name__ == "__main__":
    main()
