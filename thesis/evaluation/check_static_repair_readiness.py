#!/usr/bin/env python3
"""Static/Repair readiness gate (tool-state wave): is the static-analysis
and repair infrastructure actually able to run pilot_002 under the
tool-state model?

Checks (each PASS / FAIL / UNRESOLVED, never inferred from configuration
alone where a measurement is possible):

  1. config: every configured static tool resolves; repair policy valid
     (request_retry_rounds, external_tools_mode = docker with a command
     template per external tool); the tool-state schema is the current one
  2. internal tools (compiler, gcc_analyzer, clang_tidy, cppcheck, infer):
     MEASURED inside the toolchain image with the minimal fixtures of
     verify_tool_states.py (a clean kernel must yield COMPLETED and a
     planted defect must yield a blocking finding); identities recorded
  3. external images (parcoach, llov): the docker command template of the
     config is executed against the image with minimal fixtures - the
     image must START and PRODUCE A VERDICT (race free / race, collective
     ok / rank-conditional), not merely exist
  4. condition fingerprints: static_analysis_condition_sha256 and
     repair_condition_sha256 computed and recorded, so the preflight can
     detect drift between this readiness run and the actual pilot
  5. RUNTIME condition (Static/Repair.1): the immutable identity of each of
     the three container environments (image ID / RepoDigest) together with
     the measured tool identities, the LLOV plugin hash and the PARCOACH
     executable hash. The static SEMANTIC condition deliberately excludes
     runtime identities so the three images can merge results under one
     condition - which means it can NOT detect an image or tool swap. The
     runtime condition can, and `runtime_condition_sha256` is what the pilot
     preflight re-measures against.

Run on the host (docker available) - it starts the containers itself:

  python thesis/evaluation/check_static_repair_readiness.py \
      --config thesis/config/config.yaml [--json thesis/evaluation/static_repair_readiness.json]

Exit 0 = READY, 1 = NOT_READY (a measured failure), 2 = UNRESOLVED (a
check could not be executed, e.g. no docker). pilot_preflight.py consumes
the JSON artifact and treats a stale or missing one as UNRESOLVED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.evaluation import static_provenance  # noqa: E402
from thesis.evaluation.framework import TOOL_STATE_SCHEMA_VERSION  # noqa: E402
from thesis.evaluation.tool_config import resolve_tool_settings, validate_repair_config  # noqa: E402
from thesis.repair import orchestrator  # noqa: E402

# v2 (Static/Repair.1) adds runtime / runtime_condition /
# runtime_condition_sha256. A v1 artifact carries no runtime proof at all and
# is therefore treated as unusable by the pilot preflight, never as fresh.
READINESS_SCHEMA = "static_repair_readiness.v2"
DEFAULT_JSON = REPO_ROOT / "thesis" / "evaluation" / "static_repair_readiness.json"
TOOLCHAIN_IMAGE = "pareval-thesis"
INTERNAL_TOOLS = ("compiler", "gcc_analyzer", "clang_tidy", "cppcheck", "infer")

# minimal fixtures per tool (names of verify_tool_states fixtures): one that
# must COMPLETE cleanly and one that must produce a verdict/finding
MINIMAL_FIXTURES = {
    "compiler": ["compiler clean", "compiler model compile error"],
    "gcc_analyzer": ["gcc_analyzer clean", "gcc_analyzer multi-step null path"],
    "clang_tidy": ["clang_tidy clean", "clang_tidy narrowing"],
    "cppcheck": ["cppcheck clean", "cppcheck bounds"],
    "infer": ["infer clean", "infer null dereference"],
    "parcoach": ["parcoach A unconditional collective", "parcoach B rank-conditional collective (low confidence)"],
    "llov": ["llov race free", "llov data race"],
}


# role -> (tools measured by the probe, interpreter default)
RUNTIME_ROLES = OrderedDict([
    ("main", {"image": TOOLCHAIN_IMAGE, "interpreter": "python3",
              "role_note": "internal static tools"}),
    ("parcoach", {"tool": "parcoach", "role_note": "external static tool (MPI collectives)"}),
    ("llov", {"tool": "llov", "role_note": "external static tool (OpenMP data races)"}),
])

PROBE = "thesis/evaluation/probe_runtime_identity.py"


def docker_image_identity(image_ref: str) -> dict:
    """Immutable identity of a local image: its image ID and, when the image
    came from a registry, its RepoDigests. A TAG IS NOT AN IDENTITY - if
    neither is obtainable the caller must not claim a pinned runtime."""
    identity = OrderedDict([("image_ref", image_ref), ("image_id", None),
                            ("repo_digests", []), ("rootfs_layers_sha256", None),
                            ("rootfs_layer_count", None), ("inspect_error", None)])
    argv = ["docker", "image", "inspect", image_ref, "--format",
            "{{.Id}}\t{{join .RepoDigests \",\"}}\t{{join .RootFS.Layers \",\"}}"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        identity["inspect_error"] = "docker image inspect failed: %s" % error
        return identity
    if proc.returncode != 0:
        identity["inspect_error"] = (proc.stderr or proc.stdout or "").strip()[:300]
        return identity
    line = (proc.stdout or "").strip().split("\n")[0]
    parts = line.split("\t")
    identity["image_id"] = parts[0].strip() or None
    digests = parts[1].strip() if len(parts) > 1 else ""
    identity["repo_digests"] = sorted(d for d in digests.split(",") if d.strip())
    layers = [l for l in (parts[2].strip() if len(parts) > 2 else "").split(",") if l.strip()]
    if layers:
        # ORDERED: the layer sequence is part of the identity
        identity["rootfs_layers_sha256"] = hashlib.sha256(
            "\n".join(layers).encode("utf-8")).hexdigest()
        identity["rootfs_layer_count"] = len(layers)
    return identity


def probe_environment(name: str, image_ref: str, interpreter: str, host_repo: str,
                      timeout: float = 300.0) -> dict:
    """Measure one environment: immutable image identity (host side) plus the
    in-container identity probe. Cheap - no fixtures, ~1 s per container."""
    environment = OrderedDict(docker_image_identity(image_ref))
    environment["role"] = RUNTIME_ROLES.get(name, {}).get("role_note")
    environment["interpreter"] = interpreter
    environment["tool_identities"] = OrderedDict()
    environment["evidence"] = OrderedDict()
    environment["probe_error"] = None

    argv = ["docker", "run", "--rm", "-u", "0",
            "-v", "%s:/workspace" % host_repo, "-w", "/workspace", image_ref,
            interpreter, PROBE, "--role", name]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        environment["probe_error"] = "identity probe could not run: %s" % error
        return environment

    payload = None
    for line in reversed((proc.stdout or "").splitlines()):
        if line.strip().startswith("{"):
            try:
                payload = json.loads(line)
            except ValueError:
                payload = None
            break
    if payload is None:
        environment["probe_error"] = (
            "identity probe produced no JSON (exit %d): %s"
            % (proc.returncode, ((proc.stderr or proc.stdout or "").strip()[-300:] or "no output")))
        return environment

    environment["tool_identities"] = payload.get("tool_identities") or {}
    environment["evidence"] = payload.get("evidence") or {}
    return environment


def measure_runtime(config: dict, host_repo: "str | None" = None) -> dict:
    """The measured runtime of all three environments (Static/Repair.1).

    Shared by the readiness gate and the pilot preflight, so the preflight
    re-measures with EXACTLY the same definition it later compares against.
    """
    host_repo = host_repo or host_repo_path(config)
    repair = orchestrator.repair_settings(config)
    templates = ((config.get("stages") or {}).get("repair") or {}).get(
        "external_tool_commands") or {}

    environments = OrderedDict()
    environments["main"] = probe_environment(
        "main", TOOLCHAIN_IMAGE, "python3", host_repo)

    for name in ("parcoach", "llov"):
        if name not in repair["external_tools"]:
            continue
        image, interpreter = parse_docker_template(templates.get(name) or "")
        if not image:
            environments[name] = OrderedDict([
                ("image_ref", None), ("image_id", None), ("repo_digests", []),
                ("role", RUNTIME_ROLES[name]["role_note"]),
                ("probe_error", "no docker command template configured for %s" % name),
                ("tool_identities", {}), ("evidence", {}),
            ])
            continue
        environments[name] = probe_environment(
            name, image, interpreter or "python3", host_repo)

    return environments


def host_repo_path(config: dict) -> str:
    repair = (config.get("stages") or {}).get("repair") or {}
    return (os.environ.get("PAREVAL_HOST_REPO") or repair.get("host_repo_path")
            or REPO_ROOT.as_posix())


def parse_docker_template(template: str) -> tuple[str | None, str | None]:
    """(image, interpreter) from a `docker run ... <image> <python> ...`
    command template of the config; None when the template is not docker."""
    tokens = shlex.split(template.replace("\n", " "))
    if not tokens or tokens[0] != "docker":
        return None, None
    for index, token in enumerate(tokens):
        if re.match(r"^(?:[\w.\-]+/)*[\w.\-]+(?::[\w.\-]+)?$", token) and index >= 2 \
                and tokens[index - 1] not in ("-v", "-w", "-u", "--name", "-e") \
                and not token.startswith("-") and token != "run" \
                and index + 1 < len(tokens) and tokens[index + 1].startswith("python"):
            return token, tokens[index + 1]
    return None, None


def run_fixtures_in(image: str, interpreter: str, host_repo: str, tools: list[str],
                    only: list[str], timeout: float = 900.0) -> dict:
    """Run verify_tool_states.py inside `image` for the named fixtures."""
    results = OrderedDict()
    with tempfile.TemporaryDirectory() as tmp:
        for fixture in only:
            out_name = re.sub(r"[^a-z0-9]+", "_", fixture.lower()) + ".json"
            argv = [
                "docker", "run", "--rm", "-u", "0",
                "-v", "%s:/workspace" % host_repo, "-w", "/workspace", image,
                interpreter, "thesis/evaluation/verify_tool_states.py",
                "--tools", *tools, "--only", fixture,
                "--json", "/workspace/.readiness_%s" % out_name,
            ]
            try:
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            except FileNotFoundError:
                results[fixture] = {"status": "UNRESOLVED", "detail": "docker CLI not available"}
                continue
            except subprocess.TimeoutExpired:
                results[fixture] = {"status": "FAIL", "detail": "container run exceeded %.0f s" % timeout}
                continue
            evidence_path = REPO_ROOT / (".readiness_%s" % out_name)
            evidence = None
            if evidence_path.exists():
                try:
                    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                finally:
                    evidence_path.unlink()
            row = OrderedDict()
            row["returncode"] = proc.returncode
            if evidence is None:
                row["status"] = "FAIL" if proc.returncode != 0 else "UNRESOLVED"
                row["detail"] = (proc.stderr or proc.stdout or "")[-600:]
            else:
                fixtures = evidence.get("fixtures") or []
                match = [f for f in fixtures if f.get("name") == fixture]
                if not match:
                    row["status"] = "UNRESOLVED"
                    row["detail"] = "fixture not executed in the container"
                else:
                    f = match[0]
                    row["status"] = "PASS" if f.get("passed") else "FAIL"
                    row["measured_state"] = f.get("measured_state")
                    row["num_blocking"] = f.get("num_blocking")
                    row["duration_seconds"] = f.get("duration_seconds")
                    row["detail"] = "; ".join(f.get("problems") or [])
                row["tool_identities"] = evidence.get("tool_identities")
            results[fixture] = row
    del tmp
    return results


def evaluate(config: dict, config_path: str, skip_containers: bool = False) -> dict:
    report = OrderedDict()
    report["schema_version"] = READINESS_SCHEMA
    report["config_path"] = config_path
    report["tool_state_schema"] = TOOL_STATE_SCHEMA_VERSION
    problems: list[str] = []
    unresolved: list[str] = []

    # ---- 1. config -------------------------------------------------------
    cfg_check = OrderedDict()
    try:
        validate_repair_config(config)
        cfg_check["repair_config"] = "PASS"
    except ValueError as error:
        cfg_check["repair_config"] = "FAIL: %s" % error
        problems.append("repair config invalid: %s" % error)
    repair = orchestrator.repair_settings(config)
    cfg_check["request_retry_rounds"] = repair["request_retry_rounds"]
    cfg_check["external_tools_mode"] = repair["external_tools_mode"]
    cfg_check["external_tools"] = list(repair["external_tools"])
    templates = ((config.get("stages") or {}).get("repair") or {}).get("external_tool_commands") or {}
    external_images = OrderedDict()
    if repair["external_tools_mode"] == "docker":
        for name in repair["external_tools"]:
            template = templates.get(name)
            image, interpreter = parse_docker_template(template or "")
            external_images[name] = {"image": image, "interpreter": interpreter}
            if not template or not image:
                problems.append("no docker command template for external tool %s" % name)
    else:
        unresolved.append("external_tools_mode is %s, the docker templates are not exercised"
                          % repair["external_tools_mode"])
    settings = resolve_tool_settings(config, "static_analysis")
    cfg_check["enabled_static_tools"] = [n for n, s in settings.items() if s.enabled]
    report["config"] = cfg_check
    report["external_images"] = external_images

    # ---- 4. conditions (computed on the host: no identities) --------------
    try:
        static_condition = static_provenance.static_analysis_condition(
            config, "g++", None, include_identities=False)
        report["static_analysis_condition_sha256"] = static_provenance.static_analysis_condition_sha256(static_condition)
        report["repair_condition_sha256"] = static_provenance.repair_condition_sha256(
            static_provenance.repair_condition(config))
        report["drivers_tree_sha256"] = static_condition.get("drivers_tree_sha256")
        report["tools_module_sha256"] = static_condition.get("tools_module_sha256")
    except Exception as error:  # noqa: BLE001
        unresolved.append("condition fingerprints not computable: %s" % error)

    # ---- 2./3. measured container checks -----------------------------------
    host_repo = host_repo_path(config)
    report["host_repo_path"] = host_repo

    # ---- 5. measured RUNTIME condition -------------------------------------
    if skip_containers:
        unresolved.append("runtime identity not measured (--skip-containers): "
                          "a readiness artifact without a runtime proof is never READY")
    else:
        environments = measure_runtime(config, host_repo)
        report["runtime"] = environments
        condition = static_provenance.runtime_condition(
            environments,
            static_analysis_condition_sha256=report.get("static_analysis_condition_sha256"),
            repair_condition_sha256=report.get("repair_condition_sha256"),
        )
        report["runtime_condition"] = condition
        report["runtime_condition_sha256"] = static_provenance.runtime_condition_sha256(condition)
        report["runtime_fully_pinned"] = condition["fully_pinned"]
        for name, environment in environments.items():
            if environment.get("probe_error"):
                # An identity probe that could not RUN is an unmeasurable
                # condition, not a measured contradiction: it must not push
                # the gate to NOT_READY (which the pilot preflight maps to a
                # cross-pilot mismatch). A failed FIXTURE below still does.
                unresolved.append("%s: identity probe did not run (%s)"
                                  % (name, environment["probe_error"]))
            if environment.get("inspect_error"):
                unresolved.append("%s: image identity not obtainable (%s)"
                                  % (name, environment["inspect_error"]))
        for name in condition["unpinned_environments"]:
            unresolved.append(
                "%s: neither a RepoDigest nor an image ID could be measured - the "
                "runtime is NOT fully pinned (a tag is not an immutable identity)"
                % name)
    measured = OrderedDict()
    if skip_containers:
        unresolved.append("container checks skipped (--skip-containers)")
    else:
        internal = [t for t in INTERNAL_TOOLS if t in cfg_check["enabled_static_tools"]]
        for tool in internal:
            rows = run_fixtures_in(TOOLCHAIN_IMAGE, "python3", host_repo, [tool], MINIMAL_FIXTURES[tool])
            measured[tool] = {"image": TOOLCHAIN_IMAGE, "fixtures": rows}
        for name, spec in external_images.items():
            if name not in cfg_check["enabled_static_tools"]:
                measured[name] = {"image": spec.get("image"), "skipped": "tool disabled in config"}
                continue
            if not spec.get("image"):
                continue
            rows = run_fixtures_in(spec["image"], spec["interpreter"] or "python3", host_repo,
                                   [name], MINIMAL_FIXTURES[name])
            measured[name] = {"image": spec["image"], "interpreter": spec["interpreter"], "fixtures": rows}
        for tool, block in measured.items():
            for fixture, row in (block.get("fixtures") or {}).items():
                if row.get("status") == "FAIL":
                    problems.append("%s: %s -> %s" % (tool, fixture, row.get("detail") or "failed"))
                elif row.get("status") == "UNRESOLVED":
                    unresolved.append("%s: %s -> %s" % (tool, fixture, row.get("detail") or "not executed"))
    report["measured"] = measured

    report["problems"] = problems
    report["unresolved"] = unresolved
    if problems:
        report["gate"] = "NOT_READY"
    elif unresolved:
        report["gate"] = "UNRESOLVED"
    else:
        report["gate"] = "READY"
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="thesis/config/config.yaml")
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--skip-containers", action="store_true",
                    help="config + fingerprints only (result is UNRESOLVED, never READY)")
    args = ap.parse_args()

    config = load_config(Path(args.config).resolve())
    report = evaluate(config, args.config, skip_containers=args.skip_containers)
    from thesis.generation import common
    report["created_at_utc"] = common.utc_now_iso()

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("STATIC_REPAIR_READINESS_CHECK")
    print("  tool_state_schema = %s" % report["tool_state_schema"])
    print("  static_analysis_condition_sha256 = %s" % report.get("static_analysis_condition_sha256"))
    print("  repair_condition_sha256 = %s" % report.get("repair_condition_sha256"))
    print("  runtime_condition_sha256 = %s (fully pinned: %s)"
          % (report.get("runtime_condition_sha256"), report.get("runtime_fully_pinned")))
    for name, environment in (report.get("runtime") or {}).items():
        print("  runtime %-9s %s image=%s rootfs=%s digests=%s"
              % (name, environment.get("image_ref"),
                 (environment.get("image_id") or "UNKNOWN")[:19],
                 (environment.get("rootfs_layers_sha256") or "UNKNOWN")[:12],
                 ",".join(environment.get("repo_digests") or []) or "none"))
        for tool, identity in (environment.get("tool_identities") or {}).items():
            print("      %-14s %s" % (tool, identity))
    for tool, block in report["measured"].items():
        for fixture, row in (block.get("fixtures") or {}).items():
            print("  [%s] %s :: %s -> %s %s" % (
                row.get("status"), tool, fixture, row.get("measured_state"),
                ("(" + row["detail"] + ")") if row.get("detail") else ""))
    for problem in report["problems"]:
        print("  PROBLEM: %s" % problem)
    for item in report["unresolved"]:
        print("  UNRESOLVED: %s" % item)
    print("STATIC_REPAIR_READINESS = %s" % report["gate"])
    print("evidence: %s" % args.json)
    return {"READY": 0, "NOT_READY": 1, "UNRESOLVED": 2}[report["gate"]]


if __name__ == "__main__":
    sys.exit(main())
