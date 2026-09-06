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

Run on the host (docker available) - it starts the containers itself:

  python thesis/evaluation/check_static_repair_readiness.py \
      --config thesis/config/config.yaml [--json thesis/evaluation/static_repair_readiness.json]

Exit 0 = READY, 1 = NOT_READY (a measured failure), 2 = UNRESOLVED (a
check could not be executed, e.g. no docker). pilot_preflight.py consumes
the JSON artifact and treats a stale or missing one as UNRESOLVED.
"""
from __future__ import annotations

import argparse
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

READINESS_SCHEMA = "static_repair_readiness.v1"
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
