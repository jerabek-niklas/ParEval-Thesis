"""LLM seed generation for enhanced-test input specs.

Reuses the existing generation infrastructure (thesis/generation/common.py +
the provider adapters): the adapter supplies create_client/generate incl.
retries, truncation and refusal handling; this script builds prompts,
parses/validates responses and enforces the per-benchmark quota.

Quota logic (config stages.enhanced_tests):
  - the model is asked for llm_specs_min..llm_specs_max specs
  - if fewer than llm_specs_min VALID specs remain after validation and
    dedupe, a refill round asks for the missing count, quoting the already
    accepted specs ("do not repeat") and the rejection reasons; at most
    2 refill rounds, then the benchmark proceeds under_target (logged)
  - resume: benchmarks that already have >= llm_specs_min valid specs in
    the output file are skipped (--force regenerates everything)

Every accepted spec gets spec_model set BY THE SCRIPT (like the benchmark
override) — never trusted from the model.

Usage (host or main container, needs the spec model's API key):
    python thesis/enhanced_tests/generate_test_specs.py \
        --config thesis/config/config.yaml [--limit 3] [--benchmark <b>] [--force]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.enhanced_tests.specs import (  # noqa: E402
    K_PATTERNS,
    benchmark_shape,
    spec_key,
    stage_settings,
    validate_spec,
)

BENCHMARKS_DIR = REPO_ROOT / "drivers" / "cpp" / "benchmarks"
PROMPTS_JSON = REPO_ROOT / "prompts" / "generation-prompts.json"
DEFAULT_OUTPUT = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"

PARSE_RETRIES = 2   # unparseable-JSON retries per call
REFILL_ROUNDS = 2   # additional asks when below llm_specs_min

# provider -> (script file, adapter class); mirrors generate.py's script map
ADAPTERS = {
    "openai": ("generate-openai.py", "OpenAIAdapter"),
    "gemini": ("generate-gemini.py", "GeminiAdapter"),
    "anthropic": ("generate-anthropic.py", "AnthropicAdapter"),
    "openai_compatible": ("generate-openai-compatible.py", "OpenAICompatibleAdapter"),
}

# one doc line per pattern, shown only for offered patterns
PATTERN_DOCS = {
    "random": "random: uniform values in value_range (benchmark default range)",
    "all_zeros": "all_zeros: every element 0",
    "all_same": "all_same: every element = midpoint of value_range",
    "ascending": "ascending: linear ramp lo -> hi",
    "descending": "descending: linear ramp hi -> lo",
    "alternating": "alternating: lo, hi, lo, hi, ...",
    "extreme_values": "extreme_values: numeric_limits lowest/max alternating",
    "duplicate_at": (
        'duplicate_at: random fill, then values[k] = values[k+1] — requires '
        'pattern_params {"k": <0..size-1>}, size >= 2'
    ),
    "sorted_except_one": (
        'sorted_except_one: ascending, then swap(values[k], values[k+1]) — '
        'requires pattern_params {"k": <0..size-1>}, size >= 2'
    ),
    "spike_at": (
        'spike_at: random fill, values[k] = numeric_limits::max()/2 — '
        'requires pattern_params {"k": <0..size-1>}, size >= 2'
    ),
    "explicit_values": (
        'explicit_values: you provide "values": [..] with exactly size '
        "numbers — for surgical cases; keep values <= %(max)d elements"
    ),
}


def load_adapter(provider: str) -> Any:
    script_name, class_name = ADAPTERS[provider]
    script_path = REPO_ROOT / "thesis" / "generation" / script_name

    spec = importlib.util.spec_from_file_location(script_name.replace("-", "_"), script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return getattr(module, class_name)()


def parameterizable_benchmarks() -> "List[Tuple[str, Path]]":
    result = []
    for cpu_cc in sorted(BENCHMARKS_DIR.glob("*/*/cpu.cc")):
        if "ENHANCED_TEST_SIZE_DEFAULT" in cpu_cc.read_text(encoding="utf-8"):
            benchmark_dir = cpu_cc.parent
            result.append(("%s/%s" % (benchmark_dir.parent.name, benchmark_dir.name), benchmark_dir))
    return result


def load_serial_prompts() -> dict:
    prompts = json.loads(PROMPTS_JSON.read_text(encoding="utf-8"))
    return {
        entry["name"]: entry["prompt"]
        for entry in prompts
        if entry.get("parallelism_model") == "serial"
    }


def _pattern_block(settings: Dict[str, Any]) -> str:
    lines = []
    for name in settings["offered_patterns"]:
        doc = PATTERN_DOCS.get(name, name)
        if name == "explicit_values":
            doc = doc % {"max": int(settings["explicit_values_max_size"])}
        lines.append("- " + doc)
    return "\n".join(lines)


def _shape_block(benchmark: str, settings: Dict[str, Any]) -> str:
    """Tell the generator the benchmark's input shape — above all how many
    values explicit_values needs here. Without this the model has to guess
    (it correctly assumed n*n for matrix benchmarks while the validator
    demanded n, which rejected 63 otherwise-good specs)."""
    shape = benchmark_shape(benchmark)
    sites = shape.get("fill_sites", 0)
    per_site = shape.get("elements_per_site") or []
    cap = int(settings["explicit_values_max_size"])

    if not shape.get("explicit_values_supported"):
        if sites == 0:
            reason = (
                "its inputs are built by a custom generator, so the `pattern` "
                "field has NO effect here — only `size` matters"
            )
        else:
            reason = (
                "it fills %d separate input containers, so a single value "
                "list could not be assigned unambiguously" % sites
            )
        return (
            "this benchmark does NOT support the \"explicit_values\" "
            "pattern: %s. Do not propose it." % reason
        )

    if per_site == ["n2"]:
        return (
            "this benchmark takes an N x N MATRIX (size N means N*N "
            "elements, row-major). If you use \"explicit_values\", provide "
            "exactly N*N values in row-major order (size 3 -> 9 values). "
            "At most %d values total, so N <= %d."
            % (cap, int(cap ** 0.5))
        )

    return (
        "this benchmark takes a 1-D container of N elements. If you use "
        "\"explicit_values\", provide exactly N values (size 3 -> 3 "
        "values). At most %d values total." % cap
    )


def build_user_prompt(
    benchmark: str,
    serial_prompt: str,
    baseline: str,
    settings: Dict[str, Any],
    already_accepted: Optional[List[dict]] = None,
    rejection_reasons: Optional[List[str]] = None,
    ask_count: Optional[int] = None,
) -> str:
    schema = (
        "[\n"
        "  {\n"
        '    "size": <int, 0..%(max_size)d>,\n'
        '    "pattern": <one of: %(patterns)s>,\n'
        '    "pattern_params": {"value_range": [<lo>, <hi>], "k": <int>},  // as required\n'
        '    "values": [<numbers>],   // explicit_values pattern only\n'
        '    "rationale": "<one sentence: which edge case / branch this targets>"\n'
        "  },\n"
        "  ...\n"
        "]"
    ) % {
        "max_size": int(settings["max_spec_size"]),
        "patterns": ", ".join('"%s"' % p for p in settings["offered_patterns"]),
    }

    if ask_count is None:
        ask = "propose %d-%d specs" % (
            int(settings["llm_specs_min"]),
            int(settings["llm_specs_max"]),
        )
    else:
        ask = "propose %d NEW specs" % ask_count

    prompt = """You are designing edge-case test inputs for a differential test of the
following C++ benchmark function. A candidate implementation will be run
against the reference implementation below on inputs described by "specs".

PROBLEM AND SIGNATURE:
```cpp
%(serial_prompt)s
```

REFERENCE IMPLEMENTATION (the test oracle — read it carefully):
```cpp
%(baseline)s
```

INPUT MODEL: the test harness creates the input container(s) with a given
`size` and fills them with a `pattern`:
%(pattern_block)s
An optional value_range [lo, hi] overrides the fill bounds.

INPUT SHAPE OF THIS BENCHMARK: %(shape_block)s

TASK: %(ask)s that are likely to expose bugs a plain random test misses.
Explicitly target branches and special cases OF THE REFERENCE
IMPLEMENTATION: divisions (zero divisors), loop bounds (off-by-one),
recursion base cases, sign handling, duplicate/equal elements, overflow.
Sizes must be small (edge sizes like 0/1/2/3 and small odd/even sizes are
good; stay <= %(max_size)d).

OUTPUT: ONLY a JSON array following exactly this schema — no markdown, no
explanations outside the array:
%(schema)s""" % {
        "serial_prompt": serial_prompt.rstrip(),
        "baseline": baseline.rstrip(),
        "pattern_block": _pattern_block(settings),
        "shape_block": _shape_block(benchmark, settings),
        "ask": ask,
        "max_size": int(settings["max_spec_size"]),
        "schema": schema,
    }

    if already_accepted:
        compact = json.dumps(
            [
                {"size": s["size"], "pattern": s["pattern"],
                 "pattern_params": s.get("pattern_params") or {}}
                for s in already_accepted
            ]
        )
        prompt += (
            "\n\nALREADY ACCEPTED specs — do NOT repeat these (vary size, "
            "pattern or parameters):\n%s" % compact
        )

    if rejection_reasons:
        unique_reasons = sorted(set(rejection_reasons))[:8]
        prompt += (
            "\n\nEarlier proposals were REJECTED for these reasons — avoid "
            "them:\n- %s" % "\n- ".join(unique_reasons)
        )

    return prompt


def parse_spec_response(raw_text: str) -> "Optional[list]":
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


def generate_for_benchmark(
    call_llm: "Callable[[str], Optional[str]]",
    benchmark: str,
    serial_prompt: str,
    baseline: str,
    settings: Dict[str, Any],
    known: "set",
    spec_model_id: str,
) -> "Tuple[List[dict], List[dict], bool]":
    """Initial ask + up to REFILL_ROUNDS refills until llm_specs_min valid
    specs exist. Returns (accepted, discarded_log_entries, under_target).

    call_llm(user_prompt) -> raw response text or None (API failure /
    refusal); injected so tests can drive the quota logic with a fake.
    """
    llm_min = int(settings["llm_specs_min"])
    llm_max = int(settings["llm_specs_max"])

    accepted: "List[dict]" = []
    discarded: "List[dict]" = []
    seen_keys = set()

    def run_round(ask_count: "Optional[int]", reasons: "List[str]") -> None:
        prompt = build_user_prompt(
            benchmark, serial_prompt, baseline, settings,
            already_accepted=accepted or None,
            rejection_reasons=reasons or None,
            ask_count=ask_count,
        )

        raw = None
        for _attempt in range(PARSE_RETRIES + 1):
            raw_text = call_llm(prompt)
            if raw_text is None:
                return  # API failure/refusal: no retries here, adapter did its own
            raw = parse_spec_response(raw_text)
            if raw is not None:
                break

        if raw is None:
            discarded.append({"benchmark": benchmark, "reason": "no valid JSON array"})
            return

        for item in raw:
            if isinstance(item, dict):
                # the loop, not the model, decides these fields
                item["benchmark"] = benchmark
                item["source"] = "llm"
                item["spec_model"] = spec_model_id
                item.setdefault("pattern_params", {})

            ok, reason = validate_spec(
                item,
                known,
                max_size=int(settings["max_spec_size"]),
                allowed_patterns=list(settings["offered_patterns"]),
                explicit_values_max_size=int(settings["explicit_values_max_size"]),
            )

            if ok:
                key = spec_key(item)
                if key in seen_keys:
                    discarded.append(
                        {"benchmark": benchmark, "reason": "duplicate spec", "spec": item}
                    )
                    continue
                seen_keys.add(key)
                accepted.append(item)
            else:
                discarded.append({"benchmark": benchmark, "reason": reason, "spec": item})

    run_round(ask_count=None, reasons=[])

    refills = 0
    while len(accepted) < llm_min and refills < REFILL_ROUNDS:
        refills += 1
        missing = max(llm_max - len(accepted), 1)
        reasons = [d["reason"] for d in discarded if "spec" in d]
        run_round(ask_count=missing, reasons=reasons)

    return accepted, discarded, len(accepted) < llm_min


def load_existing(output_path: Path, known: "set", settings: Dict[str, Any]) -> "Dict[str, int]":
    """benchmark -> count of valid specs already in the output (resume)."""
    counts: "Dict[str, int]" = {}

    if not output_path.exists():
        return counts

    with output_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            ok, _ = validate_spec(
                item, known,
                max_size=int(settings["max_spec_size"]),
                explicit_values_max_size=int(settings["explicit_values_max_size"]),
            )
            if ok:
                counts[item["benchmark"]] = counts.get(item["benchmark"], 0) + 1

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LLM edge-case specs per benchmark.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=None, help="Only the first N benchmarks.")
    parser.add_argument("--benchmark", default=None, help="Single benchmark (<type>/<name>).")
    parser.add_argument(
        "--force", action="store_true",
        help="Regenerate everything (default: resume — benchmarks with "
        ">= llm_specs_min valid specs are skipped).",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config).resolve())
    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    settings = stage_settings(config)

    spec_model_id = stage.get("spec_model")
    if not spec_model_id:
        raise SystemExit("stages.enhanced_tests.spec_model is not set in the config.")

    system_prompt = stage.get("spec_system_prompt")
    if not system_prompt:
        raise SystemExit("stages.enhanced_tests.spec_system_prompt is not set in the config.")

    models = [m for m in config.get("models", []) if m.get("id") == spec_model_id]
    if not models:
        raise SystemExit("spec_model '%s' not found in config models." % spec_model_id)

    model_config = models[0]
    provider = model_config["provider"]

    adapter = load_adapter(provider)
    api_key = common.get_api_key(model_config, adapter.default_api_key_env)
    generation_defaults = config.get("generation_defaults", {})
    client = adapter.create_client(
        model_config,
        api_key,
        common.get_timeout_seconds(model_config, generation_defaults),
    )

    def call_llm(user_prompt: str) -> "Optional[str]":
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
            print("  refused: %s" % refusal)
            return None
        except Exception as error:  # noqa: BLE001 - logged, benchmark skipped
            print("  API error: %s" % error)
            return None
        return result.raw_text

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

    if args.force:
        for path in (output_path, discarded_path):
            if path.exists():
                path.unlink()

    existing = load_existing(output_path, known, settings)
    llm_min = int(settings["llm_specs_min"])

    max_baseline = int(settings["baseline_prompt_max_chars"])

    accepted_total = 0
    discarded_total = 0
    under_target: "List[str]" = []

    print(
        "Spec generation | model: %s (%s) | benchmarks: %d | target %d-%d LLM specs each"
        % (spec_model_id, provider, len(benchmarks), llm_min, int(settings["llm_specs_max"]))
    )
    print("Output: %s" % output_path)

    with output_path.open("a", encoding="utf-8") as out, discarded_path.open(
        "a", encoding="utf-8"
    ) as discarded_out:
        for benchmark, benchmark_dir in benchmarks:
            name = benchmark_dir.name

            if existing.get(benchmark, 0) >= llm_min:
                print("  [%s] resume: %d valid specs exist, skipping" % (benchmark, existing[benchmark]))
                continue

            if name not in serial_prompts:
                print("  [%s] no serial prompt, skipping" % benchmark)
                continue

            baseline = (benchmark_dir / "baseline.hpp").read_text(encoding="utf-8")
            if len(baseline) > max_baseline:
                print(
                    "  [%s] baseline.hpp capped %d -> %d chars for the prompt"
                    % (benchmark, len(baseline), max_baseline)
                )
                baseline = baseline[:max_baseline]

            accepted, discarded, is_under = generate_for_benchmark(
                call_llm, benchmark, serial_prompts[name], baseline,
                settings, known, spec_model_id,
            )

            for item in accepted:
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
            for entry in discarded:
                discarded_out.write(json.dumps(entry, ensure_ascii=False) + "\n")

            accepted_total += len(accepted)
            discarded_total += len(discarded)

            status = " UNDER_TARGET" if is_under else ""
            print("  [%s] accepted %d, discarded %d%s" % (benchmark, len(accepted), len(discarded), status))

            if is_under:
                under_target.append(benchmark)

    print("\naccepted: %d, discarded: %d" % (accepted_total, discarded_total))
    if under_target:
        print("under_target (%d): %s" % (len(under_target), ", ".join(under_target)))
    print("specs: %s\ndiscarded log: %s" % (output_path, discarded_path))


if __name__ == "__main__":
    main()
