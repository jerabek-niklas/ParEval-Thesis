#!/usr/bin/env python3
"""Measure the RUNTIME IDENTITY of the container it is executed in.

Static/Repair.1. The static-analysis SEMANTIC condition deliberately drops
per-tool runtime identities so the three images (main toolchain, PARCOACH,
LLOV) can contribute entries to ONE static condition. A readiness proof,
however, is only valid for the runtime it was measured on — this probe
collects exactly that evidence, cheaply (no fixtures, no analysis run):

  main      compiler / gcc_analyzer / clang_tidy / cppcheck / infer identity
            plus the MPI launcher line and the baked toolchain stamp
  parcoach  the PARCOACH executable itself (path + sha256), its cmake
            package version and the LLVM backend string — deliberately NOT
            asserting a PARCOACH program version, because `parcoach
            --version` prints only the LLVM backend identity
  llov      LLOV's own clang identity and the OpenMPVerify plugin hash, so
            "same clang, different plugin" is visible as runtime drift

Prints ONE json object on stdout: {"role", "tool_identities", "evidence"}.
Volatile facts (timestamps, hostname, container name) are deliberately NOT
collected — the caller fingerprints this output.

Run inside each container with the repository mounted at /workspace:

  pareval-thesis:      python3   thesis/evaluation/probe_runtime_identity.py --role main
  parcoach-demo:2.4.1: python3   thesis/evaluation/probe_runtime_identity.py --role parcoach
  pareval-llov:        python3.8 thesis/evaluation/probe_runtime_identity.py --role llov

Python 3.8 compatible (the LLOV image ships no newer interpreter).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ROLE_TOOLS = {
    "main": ("compiler", "gcc_analyzer", "clang_tidy", "cppcheck", "infer"),
    "parcoach": ("parcoach",),
    "llov": ("llov",),
}


def first_line(argv, timeout=20.0):
    """First non-empty line of a `--version`-style call, or None. Never
    invents a value: an absent binary yields None."""
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.decode("utf-8", "replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0][:200] if lines else None


def sha256_file(path):
    try:
        digest = hashlib.sha256()
        with open(str(path), "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def which(name):
    line = first_line(["/bin/sh", "-c", "command -v %s" % name])
    return line or None


def main_evidence():
    evidence = OrderedDict()
    evidence["mpi_version_line"] = first_line(["mpirun", "--version"])
    stamp = Path("/opt/toolchain-versions.txt")
    evidence["toolchain_versions_file"] = str(stamp) if stamp.is_file() else None
    evidence["toolchain_versions_sha256"] = sha256_file(stamp) if stamp.is_file() else None
    return evidence


def parcoach_evidence():
    """PARCOACH identity. `parcoach --version` prints the LLVM BACKEND banner
    (and its 4th line is host-CPU derived), so that string is recorded as
    what it is and never as a PARCOACH version. The program version comes
    from the documented `--parcoach-version` flag and is cross-checked
    against the installed cmake package version; the image TAG is recorded
    separately and is not assumed to agree with either."""
    from thesis.evaluation import tools as tools_module

    evidence = OrderedDict()
    executable = which("parcoach")
    evidence["executable_path"] = executable
    evidence["executable_sha256"] = sha256_file(executable) if executable else None
    evidence["llvm_backend_identity"] = first_line(["parcoach", "--version"])
    evidence["llvm_backend_identity_note"] = (
        "first line of `parcoach --version` = the LLVM backend banner, NOT a "
        "PARCOACH version; later banner lines are host-CPU dependent and are "
        "deliberately not collected"
    )

    # `--parcoach-version` is listed in `parcoach --help-list` as
    # "Show PARCOACH version" and prints e.g. "PARCOACH version 2.4.0".
    program_version_line = first_line(["parcoach", "--parcoach-version"])
    evidence["program_version_line"] = program_version_line
    version_claim = None
    if program_version_line and "version" in program_version_line.lower():
        version_claim = program_version_line.rsplit(" ", 1)[-1].strip() or None
    evidence["program_version"] = version_claim
    evidence["program_version_source"] = (
        "parcoach --parcoach-version" if version_claim else None
    )

    version = None
    version_file = None
    cmake_dir = Path("/usr/lib/cmake/Parcoach")
    if cmake_dir.is_dir():
        for candidate in sorted(cmake_dir.glob("*")):
            if "version" not in candidate.name.lower():
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if "PACKAGE_VERSION" in line and '"' in line:
                    version = line.split('"')[1]
                    version_file = str(candidate)
                    break
            if version:
                break
    evidence["cmake_package_version"] = version
    evidence["cmake_package_version_file"] = version_file
    evidence["version_sources"] = OrderedDict([
        ("program_self_report", version_claim),
        ("cmake_package_version", version),
        ("image_tag", "carried by the configured image reference, recorded by "
                      "the caller as image_ref - it is a TAG and need not "
                      "agree with the program version"),
    ])
    evidence["version_sources_agree"] = (
        bool(version_claim) and bool(version) and version_claim == version
    )

    clang = None
    try:
        clang = tools_module.ParcoachTool()._clang()
    except Exception:  # noqa: BLE001
        clang = None
    evidence["clang_path"] = str(clang) if clang else None
    evidence["clang_identity"] = first_line([str(clang), "--version"]) if clang else None
    return evidence


def llov_evidence():
    from thesis.evaluation import tools as tools_module

    evidence = OrderedDict()
    try:
        tool = tools_module.LLOVTool()
        home = getattr(tool, "llov_home", None)
        clang = getattr(tool, "_clang", None)
        plugin = getattr(tool, "_plugin", None)
    except Exception:  # noqa: BLE001
        home = clang = plugin = None

    evidence["llov_home"] = str(home) if home else None
    evidence["clang_path"] = str(clang) if clang else None
    evidence["clang_identity"] = (
        first_line([str(clang), "--version"]) if clang and Path(str(clang)).exists() else None
    )
    evidence["plugin_path"] = str(plugin) if plugin else None
    evidence["plugin_sha256"] = (
        sha256_file(plugin) if plugin and Path(str(plugin)).exists() else None
    )
    return evidence


EVIDENCE = {"main": main_evidence, "parcoach": parcoach_evidence, "llov": llov_evidence}


def probe(role, tool_names=None):
    from thesis.evaluation import tools as tools_module

    names = tuple(tool_names) if tool_names else ROLE_TOOLS.get(role, ())
    identities = OrderedDict()
    for name in names:
        try:
            identities[name] = tools_module.tool_runtime_identity(name)
        except Exception as error:  # noqa: BLE001 - a probe never fails the run
            identities[name] = None
            print("probe: %s identity unavailable: %s" % (name, error), file=sys.stderr)

    evidence = EVIDENCE.get(role, lambda: OrderedDict())()
    evidence["interpreter_identity"] = "Python %s" % platform.python_version()

    return OrderedDict([
        ("role", role),
        ("tool_identities", identities),
        ("evidence", evidence),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--role", required=True, choices=sorted(ROLE_TOOLS))
    parser.add_argument("--tools", nargs="*", default=None,
                        help="override the tools measured for this role")
    args = parser.parse_args()

    print(json.dumps(probe(args.role, args.tools)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
