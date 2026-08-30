#!/usr/bin/env python3
"""Pick representative E3 replacement specs and emit a container smoke script.

E3 changed specs, not harness semantics, so no new sanitizer wave is needed.
What DOES need proving is that the newly generated specs actually serialize,
compile and run through the real driver's baseline path - once per
representative class:

    int / float / double fill container, no-fill, multi-fill,
    size-zero-allowed, size-zero-disallowed replacement,
    value_range, explicit_values, K-pattern

For every picked spec the emitted script builds the REAL serial driver plus the
benchmark's cpu.cc with a candidate that forwards to the frozen oracle, under
UBSan+ASan+float-cast-overflow, and runs it BOTH ways:

    define path   the spec's spec_defines() (+ generated explicit-values header)
    runtime path  -DENHANCED_RUNTIME_FILL with the spec's spec_runtime_env()

A spec passes when both paths exit cleanly with no sanitizer diagnostic and no
NaN/Inf in the output.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests import capabilities  # noqa: E402
from thesis.enhanced_tests.specs import (  # noqa: E402
    explicit_values_file_text,
    explicit_values_header,
    spec_defines,
    spec_key,
    spec_runtime_env,
)

CACHE = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced" / "specs.jsonl"

# benchmark -> the candidate body that forwards to the frozen oracle
CANDIDATES = {
    "reduce/28_reduce_smallest_odd_number":
        "int correctSmallestOdd(std::vector<int> const& x);\n"
        "int smallestOdd(std::vector<int> const& x) { return correctSmallestOdd(x); }",
    "scan/31_scan_scan_with_min_function":
        "void correctPartialMinimums(std::vector<float> &x);\n"
        "void partialMinimums(std::vector<float> &x) { correctPartialMinimums(x); }",
    "dense_la/00_dense_la_lu_decomp":
        "void correctLuFactorize(std::vector<double> &A, size_t N);\n"
        "void luFactorize(std::vector<double> &A, size_t N) { correctLuFactorize(A, N); }",
    "dense_la/03_dense_la_axpy":
        "void correctAxpy(double alpha, std::vector<double> const& x,"
        " std::vector<double> const& y, std::vector<double> &z);\n"
        "void axpy(double alpha, std::vector<double> const& x,"
        " std::vector<double> const& y, std::vector<double> &z)"
        " { correctAxpy(alpha, x, y, z); }",
    "graph/15_graph_edge_count":
        "int correctEdgeCount(std::vector<int> const& A, size_t N);\n"
        "int edgeCount(std::vector<int> const& A, size_t N)"
        " { return correctEdgeCount(A, N); }",
    "reduce/27_reduce_average":
        "double correctAverage(std::vector<double> const& x);\n"
        "double average(std::vector<double> const& x) { return correctAverage(x); }",
    "stencil/50_stencil_xor_kernel":
        "void correctXorKernel(std::vector<int> const& input,"
        " std::vector<int> &output, size_t N);\n"
        "void cellsXOR(std::vector<int> const& input, std::vector<int> &output,"
        " size_t N) { correctXorKernel(input, output, N); }",
}


def classes_for(spec):
    """Every representative class this spec covers."""
    benchmark = spec["benchmark"]
    params = spec.get("pattern_params") or {}
    out = []
    capability = capabilities.fill_type_capability(benchmark)
    if capability.get("has_fill_hook"):
        for element_type in capability.get("element_types") or []:
            out.append("type:" + element_type)
        if len(capability.get("element_types") or []) > 0 and len(
                capabilities.fill_domain_capability(benchmark).get("site_domains") or []) > 1:
            out.append("multi-fill")
    else:
        out.append("no-fill")
    if params.get("value_range"):
        out.append("value_range")
    if spec.get("values"):
        out.append("explicit_values")
    if spec["pattern"] in capabilities.K_PATTERNS:
        out.append("K-pattern")
    policy = capabilities.size_zero_policy(benchmark).get("policy")
    if policy == "ALLOWED":
        out.append("size-zero-allowed")
    elif policy == "DISALLOWED":
        out.append("size-zero-disallowed")
    return out


def pick(specs, manifest):
    """Greedy cover: the fewest replacement specs that hit every class."""
    replacement_keys = {entry["spec_key"] for entry in manifest["replacement_specs"]}
    candidates = [s for s in specs
                  if repr(spec_key(s)) in replacement_keys
                  and s["benchmark"] in CANDIDATES]
    wanted = set()
    for spec in candidates:
        wanted.update(classes_for(spec))
    picked, covered = [], set()
    while covered != wanted:
        best, best_gain = None, 0
        for spec in candidates:
            if spec in picked:
                continue
            gain = len(set(classes_for(spec)) - covered)
            if gain > best_gain:
                best, best_gain = spec, gain
        if best is None:
            break
        picked.append(best)
        covered.update(classes_for(best))
    return picked, sorted(covered), sorted(wanted - covered)


def emit(picked, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "#!/bin/bash",
        "# E3 replacement-spec smoke probe (generated by e3_smoke_specs.py).",
        "set -u",
        "W=/work",
        "FAIL=0",
        'SAN="-fsanitize=undefined,address,float-cast-overflow -fno-omit-frame-pointer"',
        'COMMON="-std=c++17 -O1 -g -DUSE_SERIAL -DDRIVER_PROBLEM_SIZE=(1<<4) -DMISMATCH_REPORT_MAX=3"',
        "",
        "probe() {  # $1 label  $2 bench  $3 cand file  $4 defines  $5 env",
        '  local label="$1" bench="$2" cand="$3" defines="$4" envs="$5"',
        '  local dir="$W/drivers/cpp/benchmarks/$bench"',
        '  local tmp; tmp=$(mktemp -d)',
        '  cp "$cand" "$tmp/generated-code.hpp"',
        '  if [ -f "$cand.values.hpp" ]; then cp "$cand.values.hpp" "$tmp/enhanced-explicit-values.hpp"; fi',
        '  if [ -f "$cand.values.txt" ]; then cp "$cand.values.txt" "$tmp/values.txt"; fi',
        '  if ! g++ $COMMON $SAN $defines -I "$W/drivers/cpp" -I "$dir" -I "$tmp" \\',
        '        "$W/drivers/cpp/models/serial-driver.cc" "$dir/cpu.cc" -o "$tmp/b" 2>"$tmp/build.log"; then',
        '    echo "  [BUILD FAIL] $label"; head -4 "$tmp/build.log"; FAIL=1; rm -rf "$tmp"; return; fi',
        '  local o; o=$(cd "$tmp" && env $envs UBSAN_OPTIONS=print_stacktrace=0:halt_on_error=0 \\',
        '        ASAN_OPTIONS=detect_leaks=0 ./b 1 2>&1); local rc=$?',
        '  if echo "$o" | grep -qiE "runtime error|AddressSanitizer|Floating point exception"; then',
        '    echo "  [SANITIZER] $label"; echo "$o" | grep -iE "runtime error|ERROR: " | head -2; FAIL=1',
        '  elif echo "$o" | grep -qiE "(^| )(nan|inf|-inf)( |$)"; then',
        '    echo "  [NON-FINITE] $label"; FAIL=1',
        '  elif [ $rc -ne 0 ]; then echo "  [EXIT $rc] $label"; FAIL=1',
        '  else echo "  [clean] $label"; fi',
        '  rm -rf "$tmp"',
        "}",
        "",
    ]

    manifest_rows = []
    for index, spec in enumerate(picked):
        stem = "spec%02d" % index
        cand = out_dir / (stem + ".hpp")
        cand.write_text(CANDIDATES[spec["benchmark"]] + "\n", encoding="utf-8")

        header = explicit_values_header(spec)
        if header:
            (out_dir / (stem + ".hpp.values.hpp")).write_text(header, encoding="utf-8")
        values_text = explicit_values_file_text(spec)
        if values_text:
            (out_dir / (stem + ".hpp.values.txt")).write_text(values_text, encoding="ascii")

        define_flags = " ".join("-D" + d for d in spec_defines(spec))
        env = spec_runtime_env(spec, values_file="values.txt" if values_text else None)
        env_flags = " ".join("%s=%s" % (k, shlex.quote(v)) for k, v in env.items())
        label = "%s %s size=%s" % (spec["benchmark"], spec["pattern"], spec["size"])

        lines.append('probe %s "%s" "/probe/%s" "%s" ""'
                     % (shlex.quote("define  " + label), spec["benchmark"],
                        cand.name, define_flags))
        lines.append('probe %s "%s" "/probe/%s" "-DENHANCED_TEST_SIZE=%d -DENHANCED_RUNTIME_FILL" "%s"'
                     % (shlex.quote("runtime " + label), spec["benchmark"],
                        cand.name, spec["size"], env_flags))
        manifest_rows.append(OrderedDict([
            ("benchmark", spec["benchmark"]),
            ("spec_key", repr(spec_key(spec))),
            ("pattern", spec["pattern"]),
            ("size", spec["size"]),
            ("classes", classes_for(spec)),
            ("defines", spec_defines(spec)),
            ("runtime_env", env),
        ]))

    lines += ["", 'echo "smoke done fail=$FAIL"', "exit $FAIL", ""]
    script = out_dir / "smoke.sh"
    with open(script, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    (out_dir / "picked.json").write_text(json.dumps(manifest_rows, indent=1),
                                         encoding="utf-8")
    return script, manifest_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", default=str(CACHE))
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    specs = [json.loads(line) for line in
             Path(args.specs).read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    picked, covered, missing = pick(specs, manifest)
    script, rows = emit(picked, args.out_dir)
    print("picked %d replacement specs" % len(picked))
    for row in rows:
        print("  %-46s %-16s size=%-5s %s"
              % (row["benchmark"], row["pattern"], row["size"], row["classes"]))
    print("covered classes:", covered)
    if missing:
        print("NOT covered:", missing)
    print("wrote", script)
    return 0


if __name__ == "__main__":
    sys.exit(main())
