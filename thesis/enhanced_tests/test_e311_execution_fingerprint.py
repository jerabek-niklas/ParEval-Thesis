#!/usr/bin/env python3
"""E3.1.1 tests: the four execution-condition gaps E3.1 left open.

E3.1 fingerprinted the spec set, policy, harness, benchmark oracles, drivers and
the enhanced settings. Four things that can still change a record were missing:

    A  the effective run timeout          (timeout vs. pass/fail)
    B  the effective jobs map incl. --jobs (operational, can cause timeouts)
    C  the actual assembled CANDIDATE CODE (sample_id is a name, not a hash)
    D  the real MPI toolchain identity     (only when MPI actually runs)

plus the CLI `--specs` / manifest consistency finding.

Run:  python thesis/enhanced_tests/test_e311_execution_fingerprint.py
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.enhanced_tests import execution_provenance as execprov  # noqa: E402
from thesis.enhanced_tests.specs import DEFAULT_SETTINGS  # noqa: E402

FROZEN_FINAL = REPO_ROOT / "thesis" / "enhanced_tests" / "frozen" / "e3_final_specs.jsonl"
FROZEN_PRE = REPO_ROOT / "thesis" / "enhanced_tests" / "frozen" / "e3_pre_specs.jsonl"
FAILURES = []

BASE_RUNTIME = {"run_timeout_seconds": 30.0,
                "effective_jobs": {"serial": 1, "omp": 1, "mpi": 1}}


def check(label, condition, detail=""):
    if condition:
        print("  [ok] %s" % label)
    else:
        print("  [FAIL] %s%s" % (label, (" - " + detail) if detail else ""))
        FAILURES.append(label)


def fingerprint(specs=FROZEN_FINAL, runtime=None, settings=None,
                include_toolchain=False):
    return execprov.enhanced_execution_fingerprint(
        specs, settings or dict(DEFAULT_SETTINGS),
        runtime=runtime if runtime is not None else dict(BASE_RUNTIME),
        include_toolchain=include_toolchain)


def sha(fp):
    return fp["enhanced_execution_fingerprint_sha256"]


# ---------------------------------------------------------------------------
# A. run timeout
# ---------------------------------------------------------------------------

def group_timeout():
    print("A. the effective run timeout is part of the condition")
    base = fingerprint()
    check("run_timeout_seconds is recorded",
          base["components"]["G_effective_config"]["run_timeout_seconds"] == 30.0)

    other = fingerprint(runtime={**BASE_RUNTIME, "run_timeout_seconds": 60.0})
    check("30s -> 60s changes the fingerprint", sha(base) != sha(other))
    allowed, why = execprov.resume_allowed(base, other)
    check("timeout drift -> resume REFUSED", not allowed, why)
    check("the refusal names the config component", "G_effective_config" in why, why)

    same = fingerprint()
    check("an unchanged timeout keeps the fingerprint", sha(base) == sha(same))


# ---------------------------------------------------------------------------
# B. effective jobs
# ---------------------------------------------------------------------------

def group_jobs():
    print("B. the effective jobs map (after the --jobs override) is part of it")
    base = fingerprint()
    check("effective_jobs is recorded",
          base["components"]["G_effective_config"]["effective_jobs"]
          == {"mpi": 1, "omp": 1, "serial": 1})

    override = fingerprint(runtime={**BASE_RUNTIME,
                                    "effective_jobs": {"serial": 2, "omp": 1, "mpi": 1}})
    check("--jobs serial=2 changes the fingerprint", sha(base) != sha(override))
    allowed, why = execprov.resume_allowed(base, override)
    check("jobs drift -> resume REFUSED", not allowed, why)

    # the jobs map must be order-insensitive, so a dict ordering difference
    # alone never invalidates a resume
    reordered = fingerprint(runtime={**BASE_RUNTIME,
                                     "effective_jobs": {"mpi": 1, "serial": 1, "omp": 1}})
    check("jobs dict ordering alone does NOT change the fingerprint",
          sha(base) == sha(reordered))

    # the runner must resolve jobs BEFORE it computes the fingerprint
    import inspect
    from thesis.evaluation import run_enhanced_tests as runner
    source = inspect.getsource(runner.main).splitlines()

    def first(needle):
        return next((i for i, line in enumerate(source) if needle in line), None)

    jobs_line = first("jobs = resolve_jobs(")
    timeout_line = first("run_timeout = float(")
    fp_line = first("execprov.enhanced_execution_fingerprint(")
    check("the runner resolves jobs before fingerprinting",
          jobs_line is not None and fp_line is not None and jobs_line < fp_line,
          "jobs=%s fingerprint=%s" % (jobs_line, fp_line))
    check("the runner resolves the timeout before fingerprinting",
          timeout_line is not None and fp_line is not None and timeout_line < fp_line)
    check("the runner passes both into the fingerprint",
          "run_timeout" in source[fp_line + 1] + source[fp_line + 2]
          and "jobs" in source[fp_line + 1] + source[fp_line + 2])


# ---------------------------------------------------------------------------
# C. candidate sources
# ---------------------------------------------------------------------------

def write_fake_assembly(root, run_id, model_id, sources):
    """A minimal but REAL assembly.jsonl the productive discovery path reads."""
    model_dir = root / "thesis" / "results" / "intermediate" / run_id / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for sample_id, text in sources.items():
        sample_dir = model_dir / "sources" / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        source = sample_dir / "generated-code.hpp"
        source.write_text(text, encoding="utf-8")
        lines.append(json.dumps({
            "schema_version": "assembly.v1",
            "run_id": run_id,
            "model_id": model_id,
            "sample_id": sample_id,
            "assembled": True,
            "source_path": str(source.relative_to(root)).replace("\\", "/"),
            "drivers": {"benchmark_dir": "drivers/cpp/benchmarks/reduce/25_reduce_xor",
                        "model_driver": "serial-driver.cc"},
        }))
    (model_dir / "assembly.jsonl").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
    return model_dir.parent.parent  # intermediate_dir


def group_candidate_sources():
    print("C. the actual assembled candidate code is part of the condition")
    global_fp = fingerprint()
    sample_id = "m1__reduce__25_reduce_xor__serial__sample_0"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        intermediate = write_fake_assembly(
            root, "r1", "m1", {sample_id: "// candidate A\nbool f(){return true;}\n"})

        first = execprov.candidate_source_fingerprint(
            intermediate, "r1", "m1", repo_root=root)
        check("the candidate fingerprint sees the assembled sample",
              first["sample_count"] == 1, str(first["sample_count"]))
        check("it hashes the source CONTENT, not the sample_id",
              first["samples"][0]["source_sha256"] is not None)
        check("it records the sample identity too",
              first["samples"][0]["sample_id"] == sample_id)

        model_first = execprov.model_execution_fingerprint(global_fp, first)

        # THE decisive test: same run_id, model_id, sample_id - different code
        write_fake_assembly(
            root, "r1", "m1", {sample_id: "// candidate B\nbool f(){return false;}\n"})
        second = execprov.candidate_source_fingerprint(
            intermediate, "r1", "m1", repo_root=root)
        model_second = execprov.model_execution_fingerprint(global_fp, second)

        check("same sample_id + different source changes the candidate hash",
              first["combined_sha256"] != second["combined_sha256"])
        check("...and the model execution fingerprint",
              model_first["model_execution_fingerprint_sha256"]
              != model_second["model_execution_fingerprint_sha256"])
        allowed, why = execprov.model_resume_allowed(model_first, model_second)
        check("same sample_id + different candidate source -> resume REFUSED",
              not allowed, why)
        check("the refusal names the candidate sources",
              "candidate source" in why, why)

        # unchanged code resumes
        allowed, why = execprov.model_resume_allowed(model_second, model_second)
        check("identical candidate code -> resume ACCEPTED", allowed, why)

        # a global drift also refuses at model level
        other_global = fingerprint(runtime={**BASE_RUNTIME, "run_timeout_seconds": 99.0})
        model_other = execprov.model_execution_fingerprint(other_global, second)
        allowed, why = execprov.model_resume_allowed(model_second, model_other)
        check("global drift also refuses at model level", not allowed, why)
        check("the refusal names the global condition",
              "global execution condition" in why, why)

        # missing provenance
        allowed, why = execprov.model_resume_allowed(None, model_second)
        check("missing model provenance -> resume REFUSED", not allowed, why)
        allowed, why = execprov.model_resume_allowed(
            {"enhanced_execution_fingerprint_sha256": sha(global_fp)}, model_second)
        check("a pre-E3.1.1 (global-only) record -> resume REFUSED", not allowed, why)


# ---------------------------------------------------------------------------
# D. MPI toolchain
# ---------------------------------------------------------------------------

def group_mpi_toolchain():
    print("D. MPI identity is part of the condition, but only when MPI runs")
    versions = {"g++": "g++ (test) 13.3.0",
                execprov.MPI_COMPILER: "mpicxx: Open MPI 4.1.6",
                execprov.MPI_RUNTIME: "mpirun (Open MPI) 4.1.6"}
    original = execprov._tool_version
    try:
        execprov._tool_version = lambda tool: versions.get(tool)

        mpi_settings = dict(DEFAULT_SETTINGS)
        mpi_settings["execution_models"] = ["serial", "mpi"]
        mpi_a = fingerprint(settings=mpi_settings, include_toolchain=True)
        toolchain = mpi_a["components"]["H_toolchain"]
        check("MPI compiler identity is recorded",
              toolchain.get("mpi_compiler") == execprov.MPI_COMPILER
              and toolchain.get("mpi_compiler_version") == versions[execprov.MPI_COMPILER])
        check("MPI runtime identity is recorded",
              toolchain.get("mpi_runtime") == execprov.MPI_RUNTIME
              and toolchain.get("mpi_runtime_version") == versions[execprov.MPI_RUNTIME])

        versions[execprov.MPI_RUNTIME] = "mpirun (Open MPI) 5.0.0"
        mpi_b = fingerprint(settings=mpi_settings, include_toolchain=True)
        check("an MPI version change changes the fingerprint", sha(mpi_a) != sha(mpi_b))
        allowed, why = execprov.resume_allowed(mpi_a, mpi_b)
        check("MPI toolchain drift -> resume REFUSED", not allowed, why)

        # serial-only must NOT depend on an unused MPI installation
        serial_settings = dict(DEFAULT_SETTINGS)
        serial_settings["execution_models"] = ["serial"]
        versions[execprov.MPI_RUNTIME] = "mpirun (Open MPI) 4.1.6"
        serial_a = fingerprint(settings=serial_settings, include_toolchain=True)
        versions[execprov.MPI_RUNTIME] = "mpirun (Open MPI) 9.9.9"
        versions[execprov.MPI_COMPILER] = "mpicxx: Open MPI 9.9.9"
        serial_b = fingerprint(settings=serial_settings, include_toolchain=True)
        check("serial-only is NOT affected by an unused MPI version",
              sha(serial_a) == sha(serial_b))
        check("serial-only records no MPI identity",
              "mpi_compiler_version" not in serial_a["components"]["H_toolchain"])

        # an absent tool yields None, never an invented string
        execprov._tool_version = lambda tool: None
        absent = fingerprint(settings=mpi_settings, include_toolchain=True)
        check("an absent MPI tool records None, not a made-up version",
              absent["components"]["H_toolchain"]["mpi_runtime_version"] is None)
    finally:
        execprov._tool_version = original


# ---------------------------------------------------------------------------
# E. CLI --specs consistency + F. identical
# ---------------------------------------------------------------------------

def group_specs_and_manifest():
    print("E. the spec artifact the CLI actually used is pinned consistently")
    base = fingerprint(specs=FROZEN_FINAL)
    other = fingerprint(specs=FROZEN_PRE)
    check("a different --specs file changes the fingerprint", sha(base) != sha(other))
    allowed, why = execprov.resume_allowed(base, other)
    check("spec artifact drift -> resume REFUSED", not allowed, why)

    from thesis.evaluation import run_manifest
    import inspect
    signature = inspect.signature(run_manifest.enhanced_specs_info)
    check("enhanced_specs_info accepts the actual specs path",
          "specs_path" in signature.parameters)
    signature = inspect.signature(run_manifest.ensure_run_manifest)
    check("ensure_run_manifest accepts the actual specs path",
          "enhanced_specs_path" in signature.parameters)
    runner_source = inspect.getsource(
        __import__("thesis.evaluation.run_enhanced_tests",
                   fromlist=["x"]).main)
    check("the runner passes args.specs into the manifest",
          "enhanced_specs_path=args.specs" in runner_source)

    info = run_manifest.enhanced_specs_info(
        {"stages": {}}, specs_path=str(FROZEN_FINAL))
    check("the manifest pins the CLI artifact's own hash",
          info["sha256"] == base["components"]["A_spec_set"]["specs_sha256"],
          str(info)[:120])

    print()
    print("F. identical everything still resumes")
    allowed, why = execprov.resume_allowed(base, fingerprint(specs=FROZEN_FINAL))
    check("identical global condition -> resume ACCEPTED", allowed, why)


# ---------------------------------------------------------------------------
# multi-model registration under one run_id
# ---------------------------------------------------------------------------

def group_multi_model():
    print("multi-model: additive registration, per-model fail-closed")
    from thesis.evaluation import run_manifest

    global_fp = fingerprint()
    with tempfile.TemporaryDirectory() as tmp:
        config = {"outputs": {"intermediate_dir": tmp}, "stages": {}}
        run_manifest.ensure_run_manifest(
            config, "r_multi", stage="enhanced_tests",
            enhanced_execution=global_fp)

        run_manifest.register_model_execution(config, "r_multi", "model_a", "sha_a")
        ok = True
        try:
            run_manifest.register_model_execution(
                config, "r_multi", "model_b", "sha_b")
        except run_manifest.EnhancedExecutionConditionMismatch:
            ok = False
        check("a SECOND model registers additively under the same run_id", ok)

        manifest = json.loads(
            run_manifest.manifest_path(config, "r_multi").read_text(encoding="utf-8"))
        check("both models are recorded",
              manifest["model_execution_fingerprints"]
              == {"model_a": "sha_a", "model_b": "sha_b"},
              str(manifest.get("model_execution_fingerprints")))

        ok = True
        try:
            run_manifest.register_model_execution(
                config, "r_multi", "model_a", "sha_a")
        except run_manifest.EnhancedExecutionConditionMismatch:
            ok = False
        check("re-registering the same model with the same fingerprint is fine", ok)

        raised = False
        try:
            run_manifest.register_model_execution(
                config, "r_multi", "model_a", "sha_a_DIFFERENT")
        except run_manifest.EnhancedExecutionConditionMismatch as error:
            raised = "fresh run_id" in str(error)
        check("the same model with a DIFFERENT fingerprint hard-fails", raised)


def main():
    groups = (group_timeout, group_jobs, group_candidate_sources,
              group_mpi_toolchain, group_specs_and_manifest, group_multi_model)
    for group in groups:
        group()
        print()
    if FAILURES:
        print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("All %d E3.1.1 execution-fingerprint test groups passed." % len(groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
