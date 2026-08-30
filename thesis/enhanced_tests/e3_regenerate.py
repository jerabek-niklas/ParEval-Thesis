#!/usr/bin/env python3
"""E3: policy-driven replacement of the invalidated enhanced specs.

    RETAIN every spec that is still valid under the frozen E2-B policy
      + GENERATE at most `invalid_count` replacements per benchmark
      = the final pilot_002 enhanced spec cache

The replacements come from the PRODUCTIVE generator path
(generate_test_specs.generate_for_benchmark, in its E3 retention/budget mode),
so they pass exactly the same prompt construction, validation, capability
enforcement and dedupe as any normal run. There is no E3-only generator and no
hand-written spec.

Safety properties this script guarantees:

  * the existing cache is never written incrementally. The full new cache is
    built in a temp file, fully validated, and only then replaced atomically
    (os.replace). Any failure leaves the old cache untouched.
  * a retained spec is copied VERBATIM (the original JSON object), so its
    spec_key and its content are unchanged by construction.
  * a replacement can never collide with a retained spec_key or with another
    replacement.
  * the final population per benchmark never exceeds the old DISTINCT count.

Run:
    python thesis/enhanced_tests/e3_regenerate.py --partition <partition.json> \\
        --out-manifest <manifest.json> [--dry-run] [--benchmark X] [--resume F]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.enhanced_tests import capabilities  # noqa: E402
from thesis.enhanced_tests import generate_test_specs as gen  # noqa: E402
from thesis.enhanced_tests.specs import (  # noqa: E402
    spec_key,
    stage_settings,
    validate_spec,
)

DEFAULT_SPECS = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"
DEFAULT_CONFIG = REPO_ROOT / "thesis" / "config" / "config.yaml"


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_rows(path):
    return [json.loads(line) for line in
            Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

def split_rows(rows, partition):
    """Map the partition's original_index back onto the actual spec objects."""
    retained_idx, drifted_idx, invalid_idx, dup_idx = (
        {r["original_index"] for r in partition[name]}
        for name in ("retained_unchanged", "retained_drifted",
                     "invalid_to_replace", "duplicate_rows"))
    retained, drifted, invalid, duplicates = [], [], [], []
    for index, spec in enumerate(rows):
        if index in retained_idx:
            retained.append(spec)
        elif index in drifted_idx:
            drifted.append(spec)
        elif index in invalid_idx:
            invalid.append(spec)
        elif index in dup_idx:
            duplicates.append(spec)
        else:
            raise SystemExit("row %d is in no partition set" % index)
    return retained, drifted, invalid, duplicates


def final_checks(final_specs, known_benchmarks, settings):
    """Every acceptance gate the contract requires on the assembled cache."""
    report = OrderedDict()
    invalid = []
    for spec in final_specs:
        ok, reason = validate_spec(
            spec, known_benchmarks,
            max_size=int(settings["max_spec_size"]),
            explicit_values_max_size=int(settings["explicit_values_max_size"]))
        if not ok:
            invalid.append((spec.get("benchmark"), spec.get("pattern"), reason))
    report["FINAL_INVALID_SPEC_COUNT"] = len(invalid)
    report["final_invalid_examples"] = invalid[:5]

    keys = [spec_key(s) for s in final_specs]
    report["FINAL_DUPLICATE_SPEC_KEY_COUNT"] = len(keys) - len(set(keys))

    report["FINAL_EXTREME_VALUES_COUNT"] = sum(
        1 for s in final_specs if s.get("pattern") == "extreme_values")

    unsupported = deferred = 0
    for spec in final_specs:
        status, _why = capabilities.pattern_status(spec["benchmark"], spec["pattern"])
        if status == "unsupported":
            unsupported += 1
        elif status == "deferred_policy":
            deferred += 1
    report["FINAL_UNSUPPORTED_PATTERN_COUNT"] = unsupported
    report["FINAL_DEFERRED_PATTERN_COUNT"] = deferred

    import math
    nonfinite = out_of_domain = irrelevant = unknown_param = inert = 0
    bad_size = 0
    for spec in final_specs:
        params = spec.get("pattern_params") or {}
        values = spec.get("values") or []
        rng = params.get("value_range")
        if rng is not None and not all(
                isinstance(v, (int, float)) and math.isfinite(float(v)) for v in rng):
            nonfinite += 1
        if any(not math.isfinite(float(v)) for v in values):
            nonfinite += 1
        if capabilities.value_range_domain_rejection(
                spec["benchmark"], spec["pattern"], rng) is not None:
            out_of_domain += 1
        if capabilities.explicit_values_domain_rejection(
                spec["benchmark"], values) is not None:
            out_of_domain += 1
        why = capabilities.parameter_rejection(
            spec["benchmark"], spec["pattern"], params, bool(values))
        if why is not None:
            if why.startswith(capabilities.REASON_UNKNOWN_PARAM):
                unknown_param += 1
            elif why.startswith(capabilities.REASON_INERT_PARAM):
                inert += 1
            else:
                irrelevant += 1
        if capabilities.size_rejection(spec["benchmark"], spec["size"]) is not None:
            bad_size += 1
        if spec["size"] > int(settings["max_spec_size"]):
            bad_size += 1
    report["FINAL_NONFINITE_PARAM_COUNT"] = nonfinite
    report["FINAL_OUT_OF_DOMAIN_COUNT"] = out_of_domain
    report["FINAL_IRRELEVANT_PARAM_COUNT"] = irrelevant
    report["FINAL_UNKNOWN_PARAM_COUNT"] = unknown_param
    report["FINAL_INERT_PARAM_COUNT"] = inert
    report["FINAL_INVALID_SIZE_COUNT"] = bad_size

    per_benchmark = Counter(s["benchmark"] for s in final_specs)
    report["FINAL_TOTAL_SPECS"] = len(final_specs)
    report["FINAL_BENCHMARK_COUNT"] = len(per_benchmark)
    report["MIN_FINAL_SPECS_PER_BENCHMARK"] = min(per_benchmark.values()) if per_benchmark else 0
    report["MAX_FINAL_SPECS_PER_BENCHMARK"] = max(per_benchmark.values()) if per_benchmark else 0
    report["benchmarks_without_specs"] = sorted(
        set(capabilities.policy_benchmarks()) - set(per_benchmark))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", default=str(DEFAULT_SPECS))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--partition", required=True)
    ap.add_argument("--out-manifest", required=True)
    ap.add_argument("--generated", default="",
                    help="JSON file the generated replacements are cached in "
                         "(written incrementally, reused with --resume)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="assemble and validate, but do not touch the cache")
    ap.add_argument("--benchmark", default=None)
    args = ap.parse_args()

    config = load_config(Path(args.config).resolve())
    settings = stage_settings(config)
    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    spec_model_id = stage.get("spec_model")
    system_prompt = stage.get("spec_system_prompt")
    if not spec_model_id or not system_prompt:
        raise SystemExit("stages.enhanced_tests.spec_model / spec_system_prompt missing")

    # fail-closed policy preflight, exactly as the productive entrypoints do
    provenance = capabilities.policy_preflight()
    print("policy: %s | %d benchmarks | sha256 %s | derivation %s"
          % (provenance["enhanced_policy_status"],
             provenance["enhanced_policy_benchmark_count"],
             provenance["enhanced_policy_sha256"][:16],
             provenance["derivation_version"]))

    old_sha = sha256_file(args.specs)
    rows = load_rows(args.specs)
    partition = json.loads(Path(args.partition).read_text(encoding="utf-8"))
    if partition["summary"]["OLD_TOTAL_ROWS"] != len(rows):
        raise SystemExit("partition does not match the current cache")

    retained_unchanged, retained_drifted, invalid, duplicates = split_rows(rows, partition)
    retained_all = retained_unchanged + retained_drifted
    retained_by_benchmark = {}
    for spec in retained_all:
        retained_by_benchmark.setdefault(spec["benchmark"], []).append(spec)

    per_benchmark_plan = partition["per_benchmark"]
    benchmarks = [b for b, plan in per_benchmark_plan.items()
                  if plan["replacement_budget"] > 0]
    if args.benchmark:
        benchmarks = [b for b in benchmarks if b == args.benchmark]

    generated_path = Path(args.generated) if args.generated else None
    generated = {}
    if args.resume and generated_path and generated_path.exists():
        generated = json.loads(generated_path.read_text(encoding="utf-8"))
        print("resume: %d benchmarks already generated" % len(generated))

    todo = [b for b in benchmarks if b not in generated]
    if todo:
        serial_prompts = gen.load_serial_prompts()
        benchmark_dirs = dict(gen.parameterizable_benchmarks())
        known = set(benchmark_dirs)
        call_llm, model_config = gen.make_call_llm(config, spec_model_id, system_prompt)
        print("spec_model: %s (%s) | benchmarks to regenerate: %d"
              % (spec_model_id, model_config["provider"], len(todo)))

        max_baseline = int(settings["baseline_prompt_max_chars"])
        for position, benchmark in enumerate(todo, 1):
            plan = per_benchmark_plan[benchmark]
            budget = plan["replacement_budget"]
            directory = benchmark_dirs[benchmark]
            name = directory.name
            if name not in serial_prompts:
                generated[benchmark] = {"accepted": [], "discarded": [],
                                        "under_target": True,
                                        "note": "no serial prompt"}
                continue
            baseline = (directory / "baseline.hpp").read_text(encoding="utf-8")
            if len(baseline) > max_baseline:
                baseline = baseline[:max_baseline] + "\n// ... truncated ...\n"

            print("  [%d/%d] %s budget=%d retained=%d"
                  % (position, len(todo), benchmark, budget,
                     len(retained_by_benchmark.get(benchmark, []))))
            accepted, discarded, under = gen.generate_for_benchmark(
                call_llm, benchmark, serial_prompts[name], baseline, settings,
                known, spec_model_id,
                retained_specs=retained_by_benchmark.get(benchmark, []),
                replacement_budget=budget,
            )
            for spec in accepted:
                spec["source"] = "llm"
                spec["spec_model"] = spec_model_id
            generated[benchmark] = {
                "accepted": accepted,
                "discarded": [{k: v for k, v in d.items() if k != "spec"}
                              for d in discarded],
                "under_target": bool(under),
                "generated_at_utc": utc_now(),
            }
            print("      -> accepted %d/%d%s"
                  % (len(accepted), budget, "  (UNDER TARGET)" if under else ""))
            if generated_path:
                generated_path.write_text(
                    json.dumps(generated, indent=1), encoding="utf-8")

    # ---------------- assemble the final cache -----------------------------
    # Identity-based, never object-identity: a duplicate ROW of an invalid spec
    # must be dropped too, and it differs from the first occurrence in its
    # free-text rationale.
    invalid_keys = {spec_key(s) for s in invalid}
    final_specs = []
    seen = set()
    for spec in rows:                       # original order, duplicates skipped
        key = spec_key(spec)
        if key in seen:
            continue
        seen.add(key)                       # also blocks later duplicate rows
        if key in invalid_keys:
            continue
        final_specs.append(spec)
    replacements = []
    for benchmark in sorted(generated):
        for spec in generated[benchmark]["accepted"]:
            key = spec_key(spec)
            if key in seen:
                continue
            seen.add(key)
            replacements.append(spec)
            final_specs.append(spec)

    known_benchmarks = {b for b, _d in gen.parameterizable_benchmarks()}
    checks = final_checks(final_specs, known_benchmarks, settings)

    # ---------------- retention proof --------------------------------------
    old_valid_keys = {spec_key(s) for s in retained_all}
    final_keys = {spec_key(s) for s in final_specs}
    dropped = old_valid_keys - final_keys
    invalid_keys = {spec_key(s) for s in invalid}
    retained_invalid = invalid_keys & final_keys
    modified = []
    final_by_key = {spec_key(s): s for s in final_specs}
    for spec in retained_all:
        other = final_by_key.get(spec_key(spec))
        if other is not None and other != spec:
            modified.append(spec["benchmark"])
    checks["VALID_OLD_SPECS_DROPPED"] = len(dropped)
    checks["VALID_OLD_SPECS_MODIFIED"] = len(modified)
    checks["INVALID_OLD_SPECS_RETAINED"] = len(retained_invalid)

    gate = (checks["FINAL_INVALID_SPEC_COUNT"] == 0
            and checks["FINAL_DUPLICATE_SPEC_KEY_COUNT"] == 0
            and checks["FINAL_EXTREME_VALUES_COUNT"] == 0
            and checks["FINAL_UNSUPPORTED_PATTERN_COUNT"] == 0
            and checks["FINAL_DEFERRED_PATTERN_COUNT"] == 0
            and checks["FINAL_NONFINITE_PARAM_COUNT"] == 0
            and checks["FINAL_OUT_OF_DOMAIN_COUNT"] == 0
            and checks["FINAL_IRRELEVANT_PARAM_COUNT"] == 0
            and checks["FINAL_UNKNOWN_PARAM_COUNT"] == 0
            and checks["FINAL_INERT_PARAM_COUNT"] == 0
            and checks["FINAL_INVALID_SIZE_COUNT"] == 0
            and checks["FINAL_BENCHMARK_COUNT"] == 60
            and checks["MIN_FINAL_SPECS_PER_BENCHMARK"] >= 1
            and checks["VALID_OLD_SPECS_DROPPED"] == 0
            and checks["VALID_OLD_SPECS_MODIFIED"] == 0
            and checks["INVALID_OLD_SPECS_RETAINED"] == 0)

    print()
    print(json.dumps(checks, indent=1))
    print("ALL_GATES_PASS =", gate)

    # ---------------- per-benchmark accounting ------------------------------
    final_counts = Counter(s["benchmark"] for s in final_specs)
    replacement_counts = Counter(s["benchmark"] for s in replacements)
    per_benchmark = OrderedDict()
    for benchmark, plan in per_benchmark_plan.items():
        made = replacement_counts.get(benchmark, 0)
        budget = plan["replacement_budget"]
        shortfall = budget - made
        info = generated.get(benchmark) or {}
        reason = None
        if shortfall > 0:
            reason = ("GENERATION_FAILURE" if info.get("under_target")
                      and not info.get("accepted") and info.get("api_failed")
                      else "CAPABILITY_LIMITED")
        per_benchmark[benchmark] = OrderedDict([
            ("old_row_count", plan["old_row_count"]),
            ("duplicate_rows", plan["duplicate_rows"]),
            ("old_count", plan["old_count"]),
            ("retained_unchanged_count", plan["retained_unchanged"]),
            ("retained_drifted_count", plan["retained_drifted"]),
            ("invalid_removed_count", plan["invalid_count"]),
            ("replacement_budget", budget),
            ("replacements_generated", made),
            ("capability_shortfall", shortfall),
            ("shortfall_reason", reason),
            ("final_count", final_counts.get(benchmark, 0)),
            ("final_unique_spec_keys",
             len({spec_key(s) for s in final_specs if s["benchmark"] == benchmark})),
            ("generation_sources", dict(Counter(
                s.get("source") for s in final_specs if s["benchmark"] == benchmark))),
            ("removed_reasons", plan["removed_reasons"]),
            ("under_target", bool(info.get("under_target"))),
        ])

    manifest = OrderedDict([
        ("wave", "E3"),
        ("generated_at_utc", utc_now()),
        ("start_head", os.environ.get("E3_START_HEAD", "")),
        ("old_specs_path", str(args.specs)),
        ("old_specs_sha256", old_sha),
        # the cache is gitignored, so the pre-E3 state is NOT recoverable from
        # git; E3 keeps an explicit hashed backup instead
        ("old_specs_backup", sorted(
            str(p) for p in Path(args.specs).parent.glob("specs.pre_e3_*.jsonl"))),
        ("old_specs_version_controlled", False),
        ("policy_sha256", provenance["enhanced_policy_sha256"]),
        ("catalog_sha256", provenance["derived_from_sha256"]),
        ("derivation_version", provenance["derivation_version"]),
        ("spec_model", spec_model_id),
        ("generator_entrypoint",
         "thesis/enhanced_tests/generate_test_specs.py::generate_for_benchmark "
         "(retention/budget mode)"),
        ("generator_config_fingerprint", OrderedDict([
            ("llm_specs_min", settings["llm_specs_min"]),
            ("llm_specs_max", settings["llm_specs_max"]),
            ("max_spec_size", settings["max_spec_size"]),
            ("explicit_values_max_size", settings["explicit_values_max_size"]),
            ("offered_patterns", list(settings["offered_patterns"])),
            ("refill_rounds", gen.REFILL_ROUNDS),
            ("parse_retries", gen.PARSE_RETRIES),
        ])),
        ("old_total_rows", partition["summary"]["OLD_TOTAL_ROWS"]),
        ("old_duplicate_rows", partition["summary"]["OLD_DUPLICATE_ROWS"]),
        ("old_total", partition["summary"]["OLD_TOTAL_SPECS"]),
        ("retained_unchanged", len(retained_unchanged)),
        ("retained_drifted", len(retained_drifted)),
        ("invalid_removed", len(invalid)),
        ("replacements_generated", len(replacements)),
        ("replacement_budget_total",
         partition["summary"]["REPLACEMENT_BUDGET_TOTAL"]),
        ("replacement_shortfall",
         partition["summary"]["REPLACEMENT_BUDGET_TOTAL"] - len(replacements)),
        ("final_total", len(final_specs)),
        ("final_benchmark_count", checks["FINAL_BENCHMARK_COUNT"]),
        ("final_checks", checks),
        ("all_gates_pass", gate),
        ("requires_reexecution", [
            OrderedDict([
                ("benchmark", r["benchmark"]),
                ("spec_key", r["spec_key"]),
                ("pattern", r["pattern"]),
                ("size", r["size"]),
                ("drift_reason", r.get("drift_reason", "")),
                ("historical_harness_state",
                 "pre-E2-A DType deduction and/or pre-E2-B numeric_limits "
                 "extreme/spike semantics"),
                ("current_harness_state",
                 "E2-A DType fix + E2-B DECLARED_FILL_DOMAIN_EXTREMA / "
                 "DECLARED_DOMAIN_UPPER_EXTREME; policy sha256 "
                 + provenance["enhanced_policy_sha256"]),
                ("requires_reexecution", True),
            ])
            for r in partition["retained_drifted"]
        ]),
        ("replacement_specs", [
            OrderedDict([
                ("benchmark", s["benchmark"]),
                ("spec_key", repr(spec_key(s))),
                ("pattern", s["pattern"]),
                ("size", s["size"]),
                ("source", s.get("source")),
                ("spec_model", s.get("spec_model")),
                ("generation_reason", "replacement_for_invalid"),
            ]) for s in replacements
        ]),
        ("per_benchmark", per_benchmark),
    ])

    # ---------------- atomic replacement -----------------------------------
    payload = "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in final_specs)
    new_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    manifest["new_specs_sha256"] = new_sha

    if not gate:
        manifest["atomic_replacement"] = "SKIPPED (gates failed)"
        Path(args.out_manifest).write_text(json.dumps(manifest, indent=1) + "\n",
                                           encoding="utf-8")
        print("GATES FAILED - the existing cache was NOT touched.")
        return 1

    if args.dry_run:
        manifest["atomic_replacement"] = "DRY_RUN (cache untouched)"
        Path(args.out_manifest).write_text(json.dumps(manifest, indent=1) + "\n",
                                           encoding="utf-8")
        print("DRY RUN: cache untouched. new sha256 would be %s" % new_sha)
        return 0

    target = Path(args.specs)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=str(target.parent),
        prefix=".e3_", suffix=".jsonl")
    try:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, str(target))
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    written = sha256_file(target)
    manifest["atomic_replacement"] = "PASS" if written == new_sha else "FAIL"
    Path(args.out_manifest).write_text(json.dumps(manifest, indent=1) + "\n",
                                       encoding="utf-8")
    print("cache replaced atomically: %s  sha256 %s" % (target, written))
    return 0 if written == new_sha else 1


if __name__ == "__main__":
    sys.exit(main())
