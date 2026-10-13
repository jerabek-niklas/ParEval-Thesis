"""Phase-2 static backfill of the test_feedback candidates (stages
static.main, static.parcoach, static.llov).

The test_feedback repair loops analysed their candidates with the compiler
only (their feedback never reads static findings), so every other enabled
static tool is missing from those records. Phase 2 measures exactly the
missing (sample, tool) pairs (ledger.missing_static: a present entry -
TIMEOUT / TOOL_ERROR included - is never re-measured) and persists each as a
supplement row under the phase-2 identity, never touching the historical
static_analysis.jsonl:

  run_main      main-container tools (gcc_analyzer, clang_tidy, cppcheck,
                infer; compiler if ever missing) in-process, registered
                exactly as run_static_analysis.main registers them;
  run_external  PARCOACH / LLOV in their pinned images via external.py
                (one container per (target, tool), token in the environment).

Rows of both paths come from external.supplement_target: one schema, the
native entry (successor_supplement.measure_entry, NOT_APPLICABLE for an
out-of-scope tool exactly as run_model writes it).

Error classes: lineage.GlobalStop (integrity / contract / provenance /
runtime conflict - the whole run stops), lineage.TargetFailure (confined to
one target and stage), EnvironmentError (environment gate before any
record).

Python 3.8 compatible.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.evaluation import successor_writer as sw
from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.recovery_successor_005 import external as ex
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl

MAIN_STAGE = "static.main"
TARGET_VARIANT = ex.TARGET_VARIANT
CONTAINER_LABEL = "pareval.successor_run"
EXTERNAL_MODULE = "thesis.recovery_successor_005.external"
TOKEN_ENV = sw.TOKEN_ENV


def _global(scope, refused):
    """A refusal of the core modules (token, foreign row, drift, torn
    history ...) is an integrity conflict of the whole run."""
    if isinstance(refused, pl.GlobalStop):
        return refused
    stop = pl.GlobalStop("%s: %s" % (scope, refused))
    stop.__cause__ = refused
    return stop


def main_tools(config):
    """Enabled static tools of the main container, config order."""
    return [name for name in pg.static_settings(config) if name not in pl.EXTERNAL_TOOLS]


def _selected(table, targets, counts, log):
    """The table's own Target objects for the requested items (Target or
    target id); targets outside the frozen table refuse, other variants are
    not this stage's work."""
    selected = []
    for item in targets:
        target = table.get(item if isinstance(item, str) else item.target_id)
        if not isinstance(item, str) and item.document != target.document:
            raise pl.GlobalStop("target %s differs from the frozen table" % target.target_id)
        if target.variant != TARGET_VARIANT:
            counts["skipped_targets"] += 1
            continue
        selected.append(target)
    if counts["skipped_targets"]:
        log("static.main: %d non-test_feedback target(s) skipped (not assigned to this stage)"
            % counts["skipped_targets"])
    return selected


def run_main(root, config, table, authority, targets, log=print, stop=None, open_items=None):
    """Missing main-container static tools of the test_feedback targets.

    Order: token -> per target: archive torn tails + missing-only work list
    -> environment gate over every tool with APPLICABLE work (before any
    record) -> per target: authority.check(), enforce static.main once per
    model, supplement rows. Returns the Counter of the invocation."""
    from thesis.evaluation import framework
    from thesis.evaluation import tools as tools_module

    root = Path(root).resolve()
    counts = Counter()
    try:
        selected = _selected(table, targets, counts, log)
        settings = pg.static_settings(config)
        names = main_tools(config)
        # exactly the registration of run_static_analysis.main (config options)
        tools_module.register_default_tools(primary_compiler="g++", config=config)
        instruments = OrderedDict((name, (framework.get_tool(name), settings[name])) for name in names)
        sw.require_token(root, pl.SUCCESSOR, authority.token)
        work = OrderedDict()
        for target in selected:
            ex.archive_all_ledgers(root, config, target, log)
            pending = OrderedDict()
            for sample_id, tools in pg.missing_static(root, config, target).items():
                mine = [tool for tool in tools if tool in instruments]
                if mine:
                    pending[sample_id] = mine
            work[target.target_id] = pending
    except (pl.GlobalStop, pl.TargetFailure, EnvironmentError):
        raise
    except RecoveryRefused as refused:
        raise _global("static.main planning", refused)
    needed = OrderedDict()
    for target in selected:
        for sample_id, tools in work[target.target_id].items():
            for tool in tools:
                if settings[tool].applies_to(target.samples[sample_id]["execution_model"]):
                    needed[tool] = True
    unavailable = [tool for tool in needed if not instruments[tool][0].is_available()]
    if unavailable:
        raise EnvironmentError("ENVIRONMENT GATE FAILED - aborting before any record: static tool(s) %s "
                               "unavailable in this environment (wrong host or container?)"
                               % ", ".join(unavailable))
    context = ex.evaluation_context(config, root)
    runner = ex.runner_block(None)
    enforced = set()
    for target in selected:
        if not work[target.target_id]:
            continue
        if stop is not None and stop():
            counts["stopped"] = 1
            log("static.main: stop requested - %s and later targets left open" % target.target_id)
            break
        authority.check()
        if target.model_id not in enforced:
            authority.enforce(MAIN_STAGE, target.model_id)
            enforced.add(target.model_id)
        try:
            result, stopped = ex.supplement_target(
                root, config, target, instruments, context, authority.binding(MAIN_STAGE, target.model_id),
                runner, authority.token, log=log, stop=stop)
        except pl.TargetFailure as failure:
            # confined to this target: rows already written stay (missing-only
            # resume); the other targets continue
            counts["target_failures"] += 1
            log("PHASE2_TARGET_FAILURE static.main %s: %s" % (target.target_id, failure))
            if open_items is not None:
                open_items.append("static.main %s" % target.target_id)
            continue
        except (pl.GlobalStop, EnvironmentError):
            raise
        except RecoveryRefused as refused:
            raise _global("static.main %s" % target.target_id, refused)
        counts.update(result)
        counts["targets"] += 1
        if stopped:
            counts["stopped"] = 1
            break
    log("static.main: %d row(s) (%d NOT_APPLICABLE) for %d sample(s) of %d target(s)"
        % (counts["rows"], counts["not_applicable"], counts["samples"], counts["targets"]))
    return counts


# -- container tools ----------------------------------------------------------------

def container_name(target, tool):
    source = re.sub(r"[^A-Za-z0-9_.-]", "-", target.source_run)
    return "pareval-%s-%s-%s-%s" % (pl.SUCCESSOR, target.model_id, source, tool)


def external_command(root, config, target, tool):
    """Docker command of the phase-2 tool runner. Same image and interpreter
    as the configured template (the measurement container is unchanged); a
    unique --name refuses a concurrent duplicate; the label lets the driver
    find an orphan; the writer token travels in the environment (-e NAME
    without a value), never on the command line."""
    from thesis.evaluation.check_static_repair_readiness import parse_docker_template

    if tool not in pl.EXTERNAL_TOOLS:
        raise RecoveryRefused("%s is not a container tool" % tool)
    settings = (config.get("stages") or {}).get("repair") or {}
    template = (settings.get("external_tool_commands") or {}).get(tool)
    if not template:
        raise ValueError("stages.repair.external_tool_commands has no template for '%s'" % tool)
    image, interpreter = parse_docker_template(template)
    marker = " %s %s " % (image, interpreter)
    if not image or marker not in template or not template.startswith("docker run "):
        raise RecoveryRefused("external template is not a docker image/interpreter command")
    head = template[:template.index(marker)].format(
        host_repo=host_repo_path(settings), repo=str(Path(root).resolve()))
    flags = " --name %s --label %s=%s -e %s" % (container_name(target, tool), CONTAINER_LABEL,
                                                pl.SUCCESSOR, TOKEN_ENV)
    return ("%s%s %s %s -B -m %s --config %s --profile %s --run-id %s --target-id %s --tool %s"
            % (head, flags, image, interpreter, EXTERNAL_MODULE, pl.CONFIG_REL, pl.PROFILE,
               pl.SUCCESSOR, target.target_id, tool))


def host_repo_path(settings):
    """orchestrator.host_repo_path restated (the package never imports the
    repair orchestrator): stages.repair.host_repo_path, else PAREVAL_HOST_REPO
    (native order). The native last resort REPO_ROOT would silently mount an
    empty directory from inside the driver container: refused instead."""
    value = settings.get("host_repo_path") or os.environ.get("PAREVAL_HOST_REPO")
    if not value:
        raise RecoveryRefused("PAREVAL_HOST_REPO is not set (the tool containers mount the host repository)")
    return value


def host_repo_path_or_none(settings):
    return settings.get("host_repo_path") or os.environ.get("PAREVAL_HOST_REPO") or None


def missing_rows(root, config, target, tool):
    """(sample, tool) pairs of one tool still missing from the merged view."""
    return sum(1 for tools in pg.missing_static(root, config, target).values() if tool in tools)


def run_external(root, config, authority, target, tool, log=print, runner=None):
    """One container run for the missing rows of (target, tool); returns the
    number of rows it wrote (0 without starting a container when nothing is
    missing).

    The driver re-verifies the authority before and after the container (the
    container itself checks only the cheap binding chain). Exit 3/4/5 is a
    global conflict; any other non-zero exit, or an exit 0 that leaves rows
    missing, is a failure of this target. A BaseException (Ctrl-C, SystemExit)
    kills the named container so no writer outlives the driver. `runner`
    replaces subprocess.run (tests)."""
    root = Path(root).resolve()
    run = runner if runner is not None else subprocess.run
    if tool not in pl.EXTERNAL_TOOLS or target.variant != TARGET_VARIANT:
        raise pl.GlobalStop("phase 2 runs container tools on test_feedback targets only (%s, %s)"
                            % (target.target_id, tool))
    try:
        sw.require_token(root, pl.SUCCESSOR, authority.token)
        ex.archive_all_ledgers(root, config, target, log)
        before = missing_rows(root, config, target, tool)
    except (pl.GlobalStop, pl.TargetFailure, EnvironmentError):
        raise
    except RecoveryRefused as refused:
        raise _global("static.%s %s" % (tool, target.target_id), refused)
    if not before:
        log("static.%s %s: nothing missing, no container started" % (tool, target.target_id))
        return 0
    authority.check()
    if not host_repo_path_or_none((config.get("stages") or {}).get("repair") or {}):
        raise EnvironmentError("PAREVAL_HOST_REPO is not set: the tool containers mount the HOST repository "
                               "(start the driver with -e PAREVAL_HOST_REPO=...)")
    try:
        command = external_command(root, config, target, tool)
    except (RecoveryRefused, ValueError) as refused:
        raise pl.GlobalStop("static.%s %s: the container command cannot be built: %s"
                            % (tool, target.target_id, refused))
    name = container_name(target, tool)
    environment = dict(os.environ)
    environment[TOKEN_ENV] = authority.token
    log("external %s %s (%d missing row(s)): %s" % (tool, target.target_id, before, command))
    try:
        result = run(command, shell=True, env=environment)
    except BaseException:
        try:
            run(["docker", "kill", name], capture_output=True)
        except Exception:  # noqa: BLE001 - the original interruption is what matters
            pass
        raise
    code = result.returncode
    if code in ex.GLOBAL_CONFLICT_EXITS:
        raise pl.GlobalStop("external %s of %s exited %d: %s - global stop"
                            % (tool, target.target_id, code, ex.GLOBAL_CONFLICT_EXITS[code]))
    if code == ex.EXIT_ENVIRONMENT:
        raise EnvironmentError("ENVIRONMENT GATE FAILED in the %s container (exit %d) - the stage stops "
                               "before any further container" % (tool, code))
    if code != 0:
        raise pl.TargetFailure("external %s of %s exited %d" % (tool, target.target_id, code))
    authority.check()
    try:
        after = missing_rows(root, config, target, tool)
    except RecoveryRefused as refused:
        raise _global("static.%s %s (after the container)" % (tool, target.target_id), refused)
    if after:
        raise pl.TargetFailure("external %s of %s exited 0 but %d row(s) are still missing"
                               % (tool, target.target_id, after))
    log("static.%s %s: %d row(s) written by the container" % (tool, target.target_id, before))
    return before
