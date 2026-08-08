"""Build and launch configuration for the evaluation stages.

This is the single source of truth for how a sample is compiled and run.
Both the compilation stage and the static-analysis stage derive their
compile commands from here, so analysis sees exactly the flags the
compiler saw (the same translation unit, the same include paths).

Differences from the upstream ParEval build configs:
  - Upstream launches via Slurm (srun). This pipeline targets plain Linux
    inside the Docker container, so OpenMP runs the binary directly with
    OMP_NUM_THREADS and MPI uses mpirun -np.
  - The primary compiler is configurable (g++ or clang++); MPI always uses
    the MPI compiler wrapper (mpicxx) regardless, since it injects the
    correct MPI include/link flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Execution models in scope for the thesis.
SUPPORTED_EXECUTION_MODELS = ("serial", "omp", "mpi")

# Map execution model -> upstream model driver file (relative to drivers/cpp).
MODEL_DRIVER_FILES = {
    "serial": "models/serial-driver.cc",
    "omp": "models/omp-driver.cc",
    "mpi": "models/mpi-driver.cc",
}

# Macro the drivers switch on (e.g. -DUSE_SERIAL).
EXECUTION_MODEL_MACROS = {
    "serial": "USE_SERIAL",
    "omp": "USE_OMP",
    "mpi": "USE_MPI",
}

# Base flags shared by every compile and every analysis run.
BASE_CXX_STANDARD = "c++17"
BASE_OPTIMIZATION = "-O3"

# Diagnostic flags. Always passed on the diagnostic compile (see below).
# Warnings are recorded; only a non-zero compiler exit is blocking.
DIAGNOSTIC_FLAGS = ("-Wall", "-Wextra", "-Wpedantic")


@dataclass
class BuildConfig:
    """Resolved build configuration for one execution model."""

    execution_model: str
    compiler: str
    cxxflags: list[str]
    macro: str
    needs_openmp: bool
    model_driver_file: str

    def base_command(
        self,
        sources: list[str],
        output_path: str,
        include_dirs: list[str],
        extra_flags: list[str] | None = None,
    ) -> list[str]:
        """Assemble a compile command as an argv list (no shell)."""
        cmd = [self.compiler, f"-std={BASE_CXX_STANDARD}", BASE_OPTIMIZATION]
        cmd += self.cxxflags
        cmd += [f"-D{self.macro}"]

        for include_dir in include_dirs:
            cmd += ["-I", include_dir]

        if extra_flags:
            cmd += extra_flags

        cmd += sources
        cmd += ["-o", output_path]

        return cmd


def resolve_compiler(execution_model: str, primary_compiler: str) -> tuple[str, bool]:
    """Return (compiler, needs_openmp) for an execution model.

    MPI always uses the MPI compiler wrapper, which itself wraps the
    primary compiler but adds the MPI include/link flags. OpenMP needs the
    -fopenmp flag; serial needs neither.
    """
    if execution_model == "mpi":
        return "mpicxx", False

    if execution_model == "omp":
        return primary_compiler, True

    if execution_model == "serial":
        return primary_compiler, False

    raise ValueError(f"Unsupported execution model: {execution_model}")


def missing_toolchain(
    execution_models: "list[str]",
    primary_compiler: str = "g++",
) -> "list[str]":
    """Human-readable list of toolchain pieces MISSING in this environment
    for the given execution models — the build-side environment gate
    (2026-08-08, same rationale as the dynamic preflight gate: a missing
    compiler must abort the run loudly, not produce a full dataset of
    build_failed records that looks like model failures).

    Checks the exact binaries this module's configs use: the primary
    compiler for serial/omp, mpicxx AND mpirun for mpi (mpirun is the
    launch side — a compile-only check would let runs die later)."""
    import shutil

    required: "dict[str, str]" = {}

    if any(model in ("serial", "omp") for model in execution_models):
        required[primary_compiler] = "serial/omp builds"

    if "mpi" in execution_models:
        required["mpicxx"] = "mpi builds"
        required["mpirun"] = "mpi launches"

    return [
        "%s (%s)" % (binary, why)
        for binary, why in required.items()
        if shutil.which(binary) is None
    ]


def get_build_config(
    execution_model: str,
    primary_compiler: str = "g++",
    diagnostic: bool = False,
) -> BuildConfig:
    if execution_model not in SUPPORTED_EXECUTION_MODELS:
        raise ValueError(
            f"Unsupported execution model '{execution_model}'. "
            f"Supported: {SUPPORTED_EXECUTION_MODELS}"
        )

    compiler, needs_openmp = resolve_compiler(execution_model, primary_compiler)

    cxxflags: list[str] = []

    if needs_openmp:
        cxxflags.append("-fopenmp")

    if diagnostic:
        cxxflags.extend(DIAGNOSTIC_FLAGS)

    return BuildConfig(
        execution_model=execution_model,
        compiler=compiler,
        cxxflags=cxxflags,
        macro=EXECUTION_MODEL_MACROS[execution_model],
        needs_openmp=needs_openmp,
        model_driver_file=MODEL_DRIVER_FILES[execution_model],
    )


@dataclass
class LaunchConfig:
    """How to run a compiled benchmark binary for one execution model."""

    execution_model: str
    # Each entry becomes one run; for nondeterministic models several
    # parallelism degrees are exercised.
    params: list[dict[str, Any]] = field(default_factory=list)

    def command(
        self,
        exec_path: str,
        params: dict[str, Any],
        niter: int | None = None,
    ) -> tuple[list[str], dict[str, str]]:
        """Return (argv, extra_env) for a single run.

        `niter` maps onto the drivers' argv contract where they support it:
        the serial and mpi drivers read argv[1] as the iteration count of the
        timing loops. The omp driver instead reads argv[1] as the thread
        count (its NITER is fixed at 5), so `niter` is ignored there.
        Correctness runs pass niter=1: validation happens before the timing
        loops and is unaffected, this only keeps the runs short.
        """
        if self.execution_model == "serial":
            argv = [exec_path]
            if niter is not None:
                argv.append(str(niter))
            return argv, {}

        if self.execution_model == "omp":
            num_threads = params["num_threads"]
            # The omp driver reads argv[1] as the thread count; set both the
            # env var and the arg so behaviour matches regardless.
            return [exec_path, str(num_threads)], {"OMP_NUM_THREADS": str(num_threads)}

        if self.execution_model == "mpi":
            num_procs = params["num_procs"]
            argv = ["mpirun", "-np", str(num_procs), exec_path]
            if niter is not None:
                argv.append(str(niter))
            return argv, {}

        raise ValueError(f"Unsupported execution model: {self.execution_model}")


# Default launch parameters. Smaller than upstream (which scales to 512
# ranks on a cluster); these are sensible for a single host / container and
# can be overridden from config. The thesis measures correctness, so the
# point of multiple degrees is to surface nondeterministic races, not to
# produce scaling curves.
DEFAULT_LAUNCH_PARAMS = {
    "serial": [{}],
    "omp": [{"num_threads": 1}, {"num_threads": 2}, {"num_threads": 4}, {"num_threads": 8}],
    "mpi": [{"num_procs": 1}, {"num_procs": 2}, {"num_procs": 4}, {"num_procs": 8}],
}


def get_launch_config(
    execution_model: str,
    overrides: dict[str, list[dict[str, Any]]] | None = None,
) -> LaunchConfig:
    params_map = dict(DEFAULT_LAUNCH_PARAMS)

    if overrides and execution_model in overrides:
        params_map[execution_model] = overrides[execution_model]

    return LaunchConfig(
        execution_model=execution_model,
        params=params_map[execution_model],
    )
