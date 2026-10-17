"""Entry point of the study closure.

    python3 -B -m thesis.study_closure.run --dry-run [--out DIR] [--no-reverify]
    python3 -B -m thesis.study_closure.run --write   [--no-reverify]

--dry-run (default) computes every section, prints the closure summary and
writes NOTHING into the repository (--out DIR, outside the repository, dumps
the would-be artifacts for inspection). --write is the formal closure: it
refuses a dirty worktree or a successor lock, persists the composite through
the phase-2 writer (composite_closure), then writes the closure artifacts
under thesis/evaluation/closure/study_closure_001/. Both modes run under
provider isolation and never contact a provider, measure or repair.

Exit codes: 0 closure PASS, 1 closure FAIL (document written in --write mode
only if every write guard held), 2 refused before any write.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.recovery_lineage import RecoveryRefused  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.study_closure import core, report  # noqa: E402

PROTECTED_WRITE_ROOTS = ("thesis/results", "thesis/config", "thesis/recovery_successor_003",
                         "thesis/recovery_successor_004", "thesis/recovery_successor_005",
                         "thesis/evaluation/recovery")


def log(message):
    sys.stderr.write("[closure %s] %s\n" % (time.strftime("%H:%M:%S", time.gmtime()), message))
    sys.stderr.flush()


def require_clean(root):
    state = core.git_state(root)
    if not state["clean"]:
        raise core.ClosureRefused("the worktree is not clean (%d uncommitted path(s): %s) - commit first; "
                                  "a formal closure binds committed code only"
                                  % (state["uncommitted_count"], state["uncommitted_paths"][:5]))
    return state


def require_no_locks(root):
    from thesis.evaluation import successor_writer as sw

    directory = Path(root) / sw.LOCK_DIR
    locks = sorted(p.name for p in directory.glob("*.lock")) if directory.is_dir() else []
    if locks:
        raise core.ClosureRefused("successor writer locks exist: %s" % locks)
    return locks


def artifact_dir(root):
    relative = core.ARTIFACT_DIR_REL
    for prefix in PROTECTED_WRITE_ROOTS:
        if relative == prefix or relative.startswith(prefix + "/"):
            raise core.ClosureRefused("closure artifacts may not live under " + prefix)
    if pl.is_protected_relative(relative):
        raise core.ClosureRefused("closure artifacts may not live in a protected run tree")
    return Path(root).resolve() / relative


def write_text(path, text):
    from thesis.evaluation import atomic_io

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_io.atomic_write_text(path, text, newline="\n")


def write_json(path, document):
    from thesis.evaluation import atomic_io

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_io.atomic_write_json(path, document)


def collect_sections(ctx):
    """Every section in evidence order. A section module that raises is
    recorded as a failing section (never swallowed)."""
    from thesis.study_closure import acceptance, coverage, disclosures, runs, study

    sections = []
    for name, module in (("runs", runs), ("study", study), ("coverage", coverage),
                         ("acceptance", acceptance), ("disclosures", disclosures)):
        ctx.log("section group %s" % name)
        try:
            produced = ctx.timed(name, module.collect, ctx)
        except Exception as error:  # noqa: BLE001 - a crashed section is a FAIL
            failed = core.Section(name)
            failed.add("collect", False, "%s: %s" % (type(error).__name__, error))
            produced = [failed]
        if isinstance(produced, core.Section):
            produced = [produced]
        sections.extend(produced)
    return sections


def artifacts(ctx, document):
    """(relative name -> content) of every closure artifact derived from the
    closure document and the cached section outputs."""
    from thesis.study_closure import acceptance, disclosures

    items = OrderedDict()
    items[core.GLOBAL_JSON] = document
    items[core.GLOBAL_MD] = report.render_markdown(document)
    register = ctx.cache.get("disclosure_register")
    if register is not None:
        items[core.DISCLOSURES_JSON] = register
        items[core.DISCLOSURES_MD] = disclosures.render_markdown(register)
    template = ctx.cache.get("acceptance_template")
    if template is not None:
        items[core.ACCEPTANCE_TEMPLATE] = template
        readiness = ctx.cache.get("acceptance_readiness")
        if readiness is None:
            readiness = acceptance.readiness_document(ctx, ctx.cache.get("publication_gate"), template)
        items[core.ACCEPTANCE_READINESS] = readiness
    return items


def dump(directory, items):
    written = []
    for name, content in items.items():
        path = Path(directory) / name
        if isinstance(content, str):
            write_text(path, content)
        else:
            write_json(path, content)
        written.append(str(path))
    return written


def persist_hook(ctx):
    """--write: the composite is persisted by the phase-2 writer right after
    its reconstruction (study.collect calls this hook before the persisted
    check)."""
    from thesis.study_closure import composite_closure

    def hook(document):
        ctx.log("persisting the composite under " + core.COMPOSITE_REL)
        result = composite_closure.persist_composite(ctx.root, document, log=ctx.log)
        ctx.cache["composite_persist_result"] = result
        return result

    return hook


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="compute everything, write nothing (default)")
    mode.add_argument("--write", action="store_true", help="formal closure: persist the composite and the artifacts")
    parser.add_argument("--out", default=None, help="dry run: dump the would-be artifacts here (outside the repo)")
    parser.add_argument("--no-reverify", action="store_true",
                        help="skip the retrospective re-verification of recovery_002/003/004")
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != REPO_ROOT:
        raise RecoveryRefused("run from the repository root (outputs are repo-relative)")
    formal = bool(args.write)
    out_dir = None
    if args.out:
        out_dir = Path(args.out).resolve()
        if formal:
            raise RecoveryRefused("--out is a dry-run option")
        try:
            out_dir.relative_to(REPO_ROOT)
            raise RecoveryRefused("--out must lie outside the repository")
        except ValueError:
            pass
    options = OrderedDict([("write", formal), ("reverify", not args.no_reverify)])
    ctx = core.load_context(REPO_ROOT, options=options, log=log)
    if formal:
        try:
            require_clean(REPO_ROOT)
            require_no_locks(REPO_ROOT)
            target = artifact_dir(REPO_ROOT)
        except RecoveryRefused as refused:
            log("REFUSED: %s" % refused)
            return 2
        ctx.options["persist_composite"] = persist_hook(ctx)
    sections = collect_sections(ctx)
    document = report.build_document(sections, ctx, formal)
    items = artifacts(ctx, document)
    if formal:
        written = dump(target, items)
        for path in written:
            log("written " + Path(path).relative_to(REPO_ROOT).as_posix())
    elif out_dir is not None:
        for path in dump(out_dir, items):
            log("dumped " + path)
    sys.stdout.write(json.dumps(OrderedDict([
        ("closure_id", core.CLOSURE_ID), ("status", document["status"]), ("formal", formal),
        ("closure_sha256", document["closure_sha256"]), ("flags", document["flags"]),
        ("sections", [(s["section"], s["status"], s["checks"], s["failing"]) for s in document["sections"]]),
        ("summary", document["summary"]), ("timings_seconds", ctx.timings),
    ]), indent=1, default=str) + "\n")
    return 0 if document["status"] == core.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
