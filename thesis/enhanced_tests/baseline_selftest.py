"""Baseline self-test for the enhanced-tests stage (gate for components 2-4).

For every parameterizable benchmark and every size in the static base set
(0, 1, 2, 7) this runs TWO probes against the ParEval baseline itself:

  1. crash/hang probe: generated-code.hpp forwards to the correct*()
     baseline, compiled normally. A crash, non-zero exit or timeout means
     the ORACLE cannot handle this size -> spec is baseline_incompatible
     for this benchmark (a crashing oracle must never count as a model
     failure).
  2. numerical-stability probe: the same forwarding wrapper compiled with
     -ffast-math (forces floating-point reordering) against the normally
     compiled oracle. "Validation: FAIL" means two CORRECT implementations
     that differ only in FP operation order diverge beyond the fequal
     tolerance on this input -> the differential oracle is meaningless
     here -> numerically_unstable. (Discovered on dense_la/00 at size 7
     with plain random fill: near-singular matrix, no pivoting.)

Results: one JSONL row per (benchmark, size) with a status out of
  ok | baseline_incompatible (crash/hang/selffail) | numerically_unstable |
  wrapper_failed | build_failed | not_parameterizable
plus a console matrix. Output: thesis/results/cache/enhanced/baseline_selftest.jsonl

Run inside the main container:
    python3 thesis/enhanced_tests/baseline_selftest.py [--sizes 0 1 2 7] [--jobs 8]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Single source for the marker string and its authentication (execution
# contract A1/C2b); the driver side that prints it is
# drivers/cpp/utilities.hpp.
from thesis.evaluation.run_correctness import (  # noqa: E402
    BASELINE_INCOMPATIBLE_NONCE_ENV,
    MARKER_NONCE,
    classify_baseline_incompatible,
)

BENCHMARKS_DIR = REPO_ROOT / "drivers" / "cpp" / "benchmarks"
DRIVERS_CPP = REPO_ROOT / "drivers" / "cpp"
PROMPTS_JSON = REPO_ROOT / "prompts" / "generation-prompts.json"
OUTPUT_PATH = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "baseline_selftest.jsonl"

COMPILE_TIMEOUT = 120
RUN_TIMEOUT = 30

# identifier at the end of a parameter declaration (strips &, *, defaults)
PARAM_NAME_RE = re.compile(r"([A-Za-z_]\w*)\s*$")
BASELINE_CALL_RE = re.compile(r"\b(correct\w+)\s*\(")


def load_serial_signatures() -> dict:
    """benchmark name -> FULL serial prompt text, from the upstream JSON.

    The full prompt is needed (not just the signature line): several
    benchmarks define types in the prompt itself (e.g. `struct Point`), and
    their cpu.cc includes generated-code.hpp BEFORE baseline.hpp precisely
    because even the baseline expects those types from the generated file.
    The wrapper therefore mirrors a real assembled sample: full prompt text
    + forwarding body + closing brace.
    """
    prompts = json.loads(PROMPTS_JSON.read_text(encoding="utf-8"))
    signatures = {}

    for entry in prompts:
        if entry.get("parallelism_model") != "serial":
            continue
        signatures[entry["name"]] = entry["prompt"]

    return signatures


def split_params(param_text: str) -> list:
    """Split a parameter list at top-level commas (angle-bracket aware)."""
    parts, depth, current = [], 0, ""

    for char in param_text:
        if char in "<(":
            depth += 1
        elif char in ">)":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char

    if current.strip():
        parts.append(current)

    return parts


def build_wrapper(benchmark_dir: Path, prompt_text: str) -> "str | None":
    """generated-code.hpp forwarding to correct*(), shaped like a real
    assembled sample: full prompt (incl. prompt-defined types) + body."""
    lines = [l for l in prompt_text.splitlines() if l.strip()]
    if not lines:
        return None

    signature = lines[-1].rstrip()
    if signature.endswith("{"):
        signature = signature[:-1].rstrip()

    match = re.match(r"^(.*?)([A-Za-z_]\w*)\s*\((.*)\)\s*$", signature, re.S)
    if not match:
        return None

    return_type = match.group(1).strip()
    params = match.group(3).strip()

    arg_names = []
    if params:
        for param in split_params(params):
            name_match = PARAM_NAME_RE.search(param.strip())
            if not name_match:
                return None
            arg_names.append(name_match.group(1))

    # baseline function name from the benchmark's own best() call
    cpu_cc = (benchmark_dir / "cpu.cc").read_text(encoding="utf-8")
    call_match = BASELINE_CALL_RE.search(cpu_cc)
    if not call_match:
        return None

    baseline_name = call_match.group(1)
    call = f"{baseline_name}({', '.join(arg_names)});"
    body = f"return {call}" if return_type != "void" else call

    # Block-scope forward declaration of the baseline: several benchmarks
    # include generated-code.hpp BEFORE baseline.hpp, so correct*() is not
    # declared yet at this point in the TU. The declaration reuses the model
    # signature's parameter list (ParEval convention: identical signatures).
    declaration = f"{return_type} {baseline_name}({params});"

    return prompt_text.rstrip() + f"\n    {declaration}\n    {body}\n}}\n"


def build_probe_wrapper(prompt_text: str, benchmark_dir: Path) -> "str | None":
    """generated-code.hpp for the stability probe (single-TU design).

    The model slot receives a SECOND copy of the baseline, compiled with
    forced FP reordering via `#pragma GCC optimize("fast-math")` inside a
    named namespace — in the SAME translation unit. validate() then compares
    the normally compiled oracle against a differently-rounded instance of
    the same reference. A genuine perturbation, unlike compiling both sides
    with the same flags (bit-identical by construction, can never fail).

    Single-TU solves what a separate perturbed TU cannot: prompt-defined
    types (struct Point, COOElement, ...) exist ONCE globally (no ODR/type-
    identity mismatch across TUs), helper functions from the prompt preamble
    exist once, and there is no extra compile/link step — compile_and_run()
    is reused as-is. The baseline text is embedded (not #include'd) because
    its `#pragma once` would make a second include a no-op in the 39
    benchmarks that include baseline.hpp before generated-code.hpp.
    NO_INLINE/NO_OPTIMIZE are push_macro'd to empty within the copy: gcc's
    optimize("...") function attribute would otherwise RESET the fast-math
    pragma exactly on the copied oracle.
    """
    lines = [l for l in prompt_text.splitlines() if l.strip()]
    if not lines:
        return None

    signature = lines[-1].rstrip()
    if signature.endswith("{"):
        signature = signature[:-1].rstrip()

    match = re.match(r"^(.*?)([A-Za-z_]\w*)\s*\((.*)\)\s*$", signature, re.S)
    if not match:
        return None

    return_type = match.group(1).strip()
    params = match.group(3).strip()

    arg_names = []
    if params:
        for param in split_params(params):
            name_match = PARAM_NAME_RE.search(param.strip())
            if not name_match:
                return None
            arg_names.append(name_match.group(1))

    cpu_cc = (benchmark_dir / "cpu.cc").read_text(encoding="utf-8")
    call_match = BASELINE_CALL_RE.search(cpu_cc)
    if not call_match:
        return None

    baseline_name = call_match.group(1)

    # embed baseline.hpp text; hoist its #include lines to global scope and
    # drop #pragma once (meaningless for embedded text)
    baseline_text = (benchmark_dir / "baseline.hpp").read_text(encoding="utf-8")
    hoisted_includes = []
    baseline_body = []
    for line in baseline_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#include"):
            hoisted_includes.append(stripped)
        elif stripped.startswith("#pragma once"):
            continue
        else:
            baseline_body.append(line)

    # prompt preamble (types/helpers) without the trailing open signature
    preamble_end = prompt_text.rfind(lines[-1])
    preamble = prompt_text[:preamble_end]

    call = f"enhanced_probe::{baseline_name}({', '.join(arg_names)});"
    body = f"return {call}" if return_type != "void" else call

    return (
        "\n".join(hoisted_includes)
        + "\n"
        + preamble
        + "\n#pragma GCC push_options\n"
        # fast-math enables reassociation; the target arch enables FMA
        # contraction (fp-contract) — the decisive rounding difference for
        # update-form kernels whose loops offer no reassociation freedom
        + '#pragma GCC optimize ("O2","fast-math","fp-contract=fast")\n'
        + '#pragma GCC target ("arch=x86-64-v3")\n'
        + '#pragma push_macro("NO_INLINE")\n#pragma push_macro("NO_OPTIMIZE")\n'
        + "#define NO_INLINE\n#define NO_OPTIMIZE\n"
        + "namespace enhanced_probe {\n"
        + "\n".join(baseline_body)
        + "\n}\n"
        + '#pragma pop_macro("NO_OPTIMIZE")\n#pragma pop_macro("NO_INLINE")\n'
        + "#pragma GCC pop_options\n"
        + signature
        + " {\n    "
        + body
        + "\n}\n"
    )


def stability_probe(
    benchmark_dir: Path,
    prompt_text: str,
    defines: "list[str]",
    extra_headers: "dict | None" = None,
) -> str:
    """pass | validate_fail | crash | hang | build_failed — normally compiled
    oracle vs. fast-math-perturbed second oracle instance (single TU)."""
    wrapper = build_probe_wrapper(prompt_text, benchmark_dir)

    if wrapper is None:
        return "build_failed"

    return compile_and_run(benchmark_dir, wrapper, defines, extra_headers=extra_headers)


def compile_and_run(
    benchmark_dir: Path,
    wrapper: str,
    defines: "list[str]",
    fast_math: bool = False,
    extra_headers: "dict | None" = None,
) -> str:
    """Compile the serial TU with `wrapper` as generated-code.hpp and the
    given -D defines (e.g. ["ENHANCED_TEST_SIZE=7", "ENHANCED_FILL_PATTERN=3"]),
    then run it. Returns: pass | validate_fail | crash | hang | build_failed.

    extra_headers ({filename: text}) are written next to the wrapper into
    the -I'd src dir — used by the explicit_values pattern, whose data
    travels via a generated enhanced-explicit-values.hpp.

    Shared between the size self-test (this script) and the per-spec
    baseline gate in run_enhanced_tests.py.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src_dir = Path(tmp) / "src"
        src_dir.mkdir()
        (src_dir / "generated-code.hpp").write_text(wrapper, encoding="utf-8")

        for header_name, text in (extra_headers or {}).items():
            (src_dir / header_name).write_text(text, encoding="utf-8")

        binary = Path(tmp) / "selftest.out"

        argv = [
            "g++", "-std=c++17", "-O1",
            *(["-ffast-math"] if fast_math else []),
            "-DUSE_SERIAL", "-DDRIVER_PROBLEM_SIZE=(1<<4)",
            *[f"-D{define}" for define in defines],
            "-I", str(DRIVERS_CPP), "-I", str(DRIVERS_CPP / "models"), "-I", str(src_dir),
            str(DRIVERS_CPP / "models" / "serial-driver.cc"),
            str(benchmark_dir / "cpu.cc"),
            "-o", str(binary),
        ]

        try:
            build = subprocess.run(argv, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
        except subprocess.TimeoutExpired:
            return "build_failed"

        if build.returncode != 0:
            return "build_failed"

        # contract C2b: the gate authenticates the marker exactly like the
        # pipeline stages do, so the two cannot disagree about what counts
        # as an oracle signal
        env = dict(os.environ)
        env[BASELINE_INCOMPATIBLE_NONCE_ENV] = MARKER_NONCE

        timed_out = False

        try:
            result = subprocess.run(
                [str(binary), "1"], capture_output=True, text=True,
                timeout=RUN_TIMEOUT, cwd=tmp, env=env,
            )
            stdout = result.stdout or ""
            returncode = result.returncode
        except subprocess.TimeoutExpired as expired:
            # contract C2c: a hang must not swallow an already-flushed
            # marker — a non-finite reference that then hangs is an oracle
            # defect, not a spec that merely runs too long
            raw = expired.stdout or b""
            stdout = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
            returncode = None
            timed_out = True

        # Execution contract A1f: a NON-FINITE REFERENCE in the baseline gate
        # is an invalid oracle output for this spec. Checked before the
        # PASS/FAIL marker AND before the process state, because the
        # comparator lets the run finish and print PASS while the reference
        # was NaN/Inf. The caller maps every non-"pass" probe result onto
        # baseline_incompatible and keeps this precise cause in baseline_gate.
        authentic, _spoofed = classify_baseline_incompatible(stdout, MARKER_NONCE)
        if authentic:
            return "non_finite_reference"

        if timed_out:
            return "hang"

        if returncode != 0:
            return "crash"

        return "pass" if "Validation: PASS" in stdout else "validate_fail"


def selftest_one(benchmark_dir: Path, wrapper: str, prompt_text: str, size: int) -> dict:
    defines = [f"ENHANCED_TEST_SIZE={size}"]

    # probe 1: oracle survives this size at all?
    plain = compile_and_run(benchmark_dir, wrapper, defines, fast_math=False)

    if plain != "pass":
        status = "baseline_incompatible"
    else:
        # probe 2: is the differential comparison numerically stable here?
        # (two-TU probe: perturbed-FP second oracle instance — comparing a
        # same-flags recompile would be bit-identical by construction)
        perturbed = stability_probe(benchmark_dir, prompt_text, defines)
        if perturbed == "pass":
            status = "ok"
        elif perturbed == "validate_fail":
            status = "numerically_unstable"
        elif perturbed in ("crash", "hang", "non_finite_reference"):
            # the perturbed oracle itself misbehaves on this input; a
            # non-finite reference there is an invalid oracle output, not a
            # stability property (contract A1f keeps the two categories
            # separate)
            status = "baseline_incompatible"
        else:
            # probe tooling failure (build) — distinct from oracle verdicts
            status = "probe_failed"

    return {"size": size, "status": status, "probe1": plain, "probe2": perturbed if plain == "pass" else None}


def main() -> None:
    parser = argparse.ArgumentParser(description="Baseline self-test over all benchmarks.")
    parser.add_argument("--sizes", type=int, nargs="*", default=[0, 1, 2, 7])
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()

    signatures = load_serial_signatures()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    benchmarks = sorted(BENCHMARKS_DIR.glob("*/*"))
    rows = []
    jobs = []

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for benchmark_dir in benchmarks:
            name = benchmark_dir.name
            benchmark_id = f"{benchmark_dir.parent.name}/{name}"

            cpu_cc = (benchmark_dir / "cpu.cc").read_text(encoding="utf-8")
            if "ENHANCED_TEST_SIZE_DEFAULT" not in cpu_cc:
                rows.append({"benchmark": benchmark_id, "size": None, "status": "not_parameterizable"})
                continue

            if name not in signatures:
                rows.append({"benchmark": benchmark_id, "size": None, "status": "wrapper_failed",
                             "detail": "no serial prompt"})
                continue

            wrapper = build_wrapper(benchmark_dir, signatures[name])
            if wrapper is None:
                rows.append({"benchmark": benchmark_id, "size": None, "status": "wrapper_failed",
                             "detail": "signature parse"})
                continue

            for size in args.sizes:
                jobs.append(
                    (
                        benchmark_id,
                        pool.submit(
                            selftest_one, benchmark_dir, wrapper, signatures[name], size
                        ),
                    )
                )

        for benchmark_id, future in jobs:
            result = future.result()
            result["benchmark"] = benchmark_id
            rows.append(result)

    with OUTPUT_PATH.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row) + "\n")

    # console matrix
    by_benchmark = {}
    for row in rows:
        if row.get("size") is not None:
            by_benchmark.setdefault(row["benchmark"], {})[row["size"]] = row["status"]

    symbol = {
        "ok": ".",
        "baseline_incompatible": "X",
        "numerically_unstable": "~",
        "probe_failed": "!",
    }

    print(f"\n{'benchmark':52s} " + " ".join(f"{s:>4d}" for s in args.sizes))
    for benchmark_id in sorted(by_benchmark):
        cells = by_benchmark[benchmark_id]
        line = " ".join(f"{symbol.get(cells.get(s), '?'):>4s}" for s in args.sizes)
        print(f"{benchmark_id:52s} {line}")

    totals = {}
    for row in rows:
        totals[row["status"]] = totals.get(row["status"], 0) + 1

    per_size_ok = {s: sum(1 for b in by_benchmark.values() if b.get(s) == "ok") for s in args.sizes}

    print(f"\nlegend: .=ok  X=baseline_incompatible  ~=numerically_unstable  !=probe_failed")
    print(f"totals: {totals}")
    print(f"parameterizable benchmarks fully ok per size: "
          + ", ".join(f"size {s}: {per_size_ok[s]}/{len(by_benchmark)}" for s in args.sizes))
    print(f"output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
