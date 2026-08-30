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
from thesis.enhanced_tests import capabilities
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


def effective_patterns_for(benchmark: str, settings: Dict[str, Any]) -> "List[str]":
    """E2-A: the patterns this benchmark may actually be asked for.

    effective = globally offered INTERSECT benchmark-supported, taken from the
    ONE capability source (thesis/enhanced_tests/capabilities.py). Offering a
    pattern the benchmark cannot vary produced specs that only faked diversity
    and that validate_spec now rejects anyway.
    """
    return capabilities.effective_patterns(benchmark, list(settings["offered_patterns"]))


def _pattern_block(benchmark: str, settings: Dict[str, Any]) -> str:
    names = effective_patterns_for(benchmark, settings)

    if not names:
        return ("- (this benchmark supports no fill pattern at all; vary the "
                "size only)")

    lines = []
    for name in names:
        doc = PATTERN_DOCS.get(name, name)
        if name == "explicit_values":
            doc = doc % {"max": int(settings["explicit_values_max_size"])}
        lines.append("- " + doc + _accepted_params_note(benchmark, name))

    if names == ["random"]:
        lines.append(
            "- NOTE: this benchmark builds its input with its own generator, "
            "so the `pattern` field cannot change the input. Pattern variation "
            "is NOT available here: use \"random\" for every spec and create "
            "diversity through `size` alone. Do not propose any other pattern.")

    return "\n".join(lines)


def _accepted_params_note(benchmark: str, pattern: str) -> str:
    """E2-A.1: which fill parameters THIS pattern accepts here.

    Read from the ONE canonical relevance table, so the prompt can never ask
    for a parameter the validator then rejects as irrelevant.
    """
    if not capabilities.has_fill_hook(benchmark):
        return "  [accepts NO pattern_params and no values]"
    accepted = [
        name for name in ("value_range", "k")
        if capabilities.pattern_uses(pattern, name)
    ]
    if capabilities.pattern_uses(pattern, "values"):
        accepted.append("values")
    if not accepted:
        return "  [accepts NO pattern_params and no values]"
    return "  [accepts only: %s]" % ", ".join(accepted)


def _parameter_rules_block(benchmark: str, settings: Dict[str, Any]) -> str:
    """The hard parameter rules the validator enforces, stated up front.

    Every rule here is read from capabilities.py, the same source validate_spec
    uses, so the generator can never be asked for a spec that is rejected for a
    parameter reason.
    """
    if not capabilities.has_fill_hook(benchmark):
        return (
            "- This benchmark has NO fill hook: `pattern_params` MUST be "
            "omitted or empty and `values` MUST NOT be given. A value_range or "
            "k here would not change the input at all.")

    capability = capabilities.fill_type_capability(benchmark)
    domain = capabilities.fill_domain_capability(benchmark)
    rules = [
        "- `pattern_params` may only contain the keys \"value_range\" and "
        "\"k\". Any other key is rejected.",
        "- \"k\" is ONLY allowed for: %s. Any other pattern is rejected if it "
        "carries k." % ", ".join(capabilities.K_PATTERNS),
        "- \"values\" is ONLY allowed for the explicit_values pattern.",
        "- \"value_range\" is ONLY allowed for patterns that actually read it "
        "(marked above); for all_zeros and explicit_values it is rejected.",
        "- value_range endpoints must be FINITE numbers (no NaN, no Infinity) "
        "with lo <= hi.",
        "- explicit values must be FINITE numbers.",
    ]

    # E2-B: the DOMAIN the benchmark declares, read from the same capability
    # source validate_spec enforces, so the model is never asked for a range
    # the validator then discards.
    if domain.get("global_value_range_supported"):
        rules.append(
            "- allowed value_range: [%.6g, %.6g] - this is the benchmark's own "
            "declared input domain and every value_range AND every explicit "
            "value must lie inside it. A range outside it is discarded, never "
            "clipped."
            % (float(domain["domain_lo"]), float(domain["domain_hi"])))
        rules.append(
            "- a degenerate value_range (lo == hi) is only accepted for "
            "\"all_same\": every other pattern would produce the same constant "
            "array under it.")
    else:
        roles = "; ".join(
            "%s in [%.6g, %.6g]" % (d.get("semantic_role"), d.get("lo"), d.get("hi"))
            for d in domain.get("site_domains") or [])
        rules.append(
            "- value_range not available for this benchmark: it fills several "
            "inputs with different declared domains (%s), so a single range "
            "would be ambiguous. Do NOT propose a value_range. Vary size and "
            "pattern instead." % roles)

    rules.append(
        "- technical limit of the fill container(s) (%s): every value must be "
        "representable in [%.6g, %.6g] and hi - lo must not exceed %.6g."
        % ("/".join(capability.get("element_types") or []),
           float(capability["value_min"]), float(capability["value_max"]),
           float(capability["max_finite_span"])))

    size_zero = capabilities.size_zero_policy(benchmark)
    if size_zero.get("policy") == "DISALLOWED":
        rules.append(
            "- size 0 is NOT a valid test size for this benchmark (%s). Use "
            "size >= 1." % (size_zero.get("reason") or "")[:180])
    return "\n".join(rules)


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
        '    "pattern_params": {},    // ONLY the keys the chosen pattern accepts (see PARAMETER RULES)\n'
        '    "values": [<numbers>],   // explicit_values pattern only\n'
        '    "rationale": "<one sentence: which edge case / branch this targets>"\n'
        "  },\n"
        "  ...\n"
        "]"
    ) % {
        "max_size": int(settings["max_spec_size"]),
        "patterns": ", ".join('"%s"' % p for p in effective_patterns_for(benchmark, settings)),
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

PARAMETER RULES (enforced — a spec breaking one of these is discarded):
%(parameter_rules_block)s

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
        "pattern_block": _pattern_block(benchmark, settings),
        "parameter_rules_block": _parameter_rules_block(benchmark, settings),
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


def make_call_llm(config: Dict[str, Any], spec_model_id: str, system_prompt: str):
    """The productive spec-generation client, as one reusable callable.

    Factored out of main() unchanged so a caller that regenerates only PART of
    the cache (E3) uses exactly the same provider, model, generation defaults,
    timeout and retry behaviour as a full run. There is no second client path.
    """
    models = [m for m in config.get("models", []) if m.get("id") == spec_model_id]
    if not models:
        raise SystemExit("spec_model '%s' not found in config models." % spec_model_id)
    model_config = models[0]
    adapter = load_adapter(model_config["provider"])
    api_key = common.get_api_key(model_config, adapter.default_api_key_env)
    generation_defaults = config.get("generation_defaults", {})
    client = adapter.create_client(
        model_config, api_key,
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

    return call_llm, model_config


def generate_for_benchmark(
    call_llm: "Callable[[str], Optional[str]]",
    benchmark: str,
    serial_prompt: str,
    baseline: str,
    settings: Dict[str, Any],
    known: "set",
    spec_model_id: str,
    retained_specs: "Optional[List[dict]]" = None,
    replacement_budget: "Optional[int]" = None,
) -> "Tuple[List[dict], List[dict], bool]":
    """Initial ask + up to REFILL_ROUNDS refills until the target number of
    valid specs exists. Returns (accepted, discarded_log_entries, under_target).

    call_llm(user_prompt) -> raw response text or None (API failure /
    refusal); injected so tests can drive the quota logic with a fake.

    E3 REPLACEMENT MODE (both optional arguments given):

      retained_specs      specs that STAY in the cache. Their spec_keys seed
                          the dedupe set, so a replacement can never collide
                          with a retained spec, and they are shown to the model
                          as ALREADY ACCEPTED so it does not re-propose them.
      replacement_budget  how many NEW specs may be produced. The target
                          replaces llm_specs_min, the ask is sized from it, and
                          accepting stops once it is reached.

    This is the SAME generation, validation and dedupe logic as a normal run -
    only the starting dedupe set and the target count differ. There is
    deliberately no separate E3 generator.
    """
    llm_min = int(settings["llm_specs_min"])
    llm_max = int(settings["llm_specs_max"])

    retained = list(retained_specs or [])
    target = llm_min if replacement_budget is None else int(replacement_budget)
    cap = None if replacement_budget is None else int(replacement_budget)

    accepted: "List[dict]" = []
    discarded: "List[dict]" = []
    # E3: retained spec_keys are already taken, so a replacement can never
    # duplicate one of them
    seen_keys = {spec_key(s) for s in retained}

    def run_round(ask_count: "Optional[int]", reasons: "List[str]") -> None:
        shown = (retained + accepted) or None
        prompt = build_user_prompt(
            benchmark, serial_prompt, baseline, settings,
            already_accepted=shown,
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
                allowed_patterns=effective_patterns_for(benchmark, settings),
                explicit_values_max_size=int(settings["explicit_values_max_size"]),
            )

            if ok:
                if cap is not None and len(accepted) >= cap:
                    discarded.append(
                        {"benchmark": benchmark,
                         "reason": "over replacement budget", "spec": item}
                    )
                    continue
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

    run_round(ask_count=(cap if cap is not None else None), reasons=[])

    refills = 0
    while len(accepted) < target and refills < REFILL_ROUNDS:
        refills += 1
        if cap is not None:
            missing = max(cap - len(accepted), 1)
        else:
            missing = max(llm_max - len(accepted), 1)
        reasons = [d["reason"] for d in discarded if "spec" in d]
        run_round(ask_count=missing, reasons=reasons)

    return accepted, discarded, len(accepted) < target


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

    # E2-A.1 FAIL-CLOSED PREFLIGHT. Runs before the output file is opened or
    # truncated, before any spec is written and before a single model call, so
    # a missing/stale/incoherent capability policy costs nothing but an exit
    # code. Everything below this point either persists data or spends money.
    try:
        policy_provenance = capabilities.policy_preflight(
            expected_benchmarks=[b for b, _ in parameterizable_benchmarks()])
    except capabilities.EnhancedPolicyError as error:
        raise SystemExit(
            "ENHANCED CAPABILITY POLICY PREFLIGHT FAILED - nothing was written "
            "and no model was called.\n%s" % error)
    print("Enhanced capability policy: %s (%s benchmarks, sha256 %s)"
          % (policy_provenance["enhanced_policy_status"],
             policy_provenance["enhanced_policy_benchmark_count"],
             policy_provenance["enhanced_policy_sha256"][:16]))

    spec_model_id = stage.get("spec_model")
    if not spec_model_id:
        raise SystemExit("stages.enhanced_tests.spec_model is not set in the config.")

    system_prompt = stage.get("spec_system_prompt")
    if not system_prompt:
        raise SystemExit("stages.enhanced_tests.spec_system_prompt is not set in the config.")

    call_llm, model_config = make_call_llm(config, spec_model_id, system_prompt)
    provider = model_config["provider"]

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
