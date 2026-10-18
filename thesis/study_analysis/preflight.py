"""Preflight gate of the study analysis (study_analysis_001), read-only.

The analysis may only aggregate a study that is formally verified, whose
composite is the one the closure fingerprinted, whose pilot results the
author accepted, and whose code cannot reach a provider. Every check below
is guarded: an exception is a FAIL with its message, never a skip.

  git            HEAD and branch; clean worktree only in write mode, where
                 every package file (incl. methodology.json) must also be
                 tracked at HEAD and unmodified (formal results come from
                 committed code only)
  closure        study_closure_001/global_verification.json: tracked and
                 unmodified, self-hash reproduced (report.verify_document),
                 status PASS, formal, every section PASS, the four technical
                 flags YES, the seven runs and eleven models, computed on an
                 ancestor of HEAD
  composite      phase2_composite.json: self-hash reproduced, composite_sha256
                 == core.EXPECTED_COMPOSITE_SHA256 == the closure's
                 summary.composite (composite AND raw sha256), persisted
  acceptance     pilot_002_result_acceptance.json: tracked and unmodified,
                 validate_acceptance valid_for_gate, publication_allowed,
                 status ACCEPTED
  phase2_lineage the lineage loads (self-hash), the frozen target table loads
                 with its sha, the composite names both; deep=True also runs
                 lineage.verify() (every protected byte; minutes)
  census         66/66 repair loops terminal, the 1,980-cell base population,
                 one repair condition, digest == lineage == table digest
                 (both frozen digests are mandatory: an absent binding FAILS)
  provider_*     AST scan of the package (forbidden imports - relative ones
                 resolved against the package - forbidden names, aliases and
                 dotted attribute chains naming a forbidden module), no
                 provider variable after the scrub, the .env import disabled,
                 no provider module loaded in this process
  methodology    loads (frozen, unique metric ids)
  addendum       the post-freeze methodology addendum loads through
                 core.load_addendum (schema, status DECLARED_AFTER_DRY_RUN,
                 bound to the frozen methodology by its canonical sha256, ids
                 unique and disjoint from the frozen ones), names the frozen
                 methodology file and declares >= 1 metric; in write mode it is
                 tracked and unmodified like methodology.json
  output_target  write mode: core.OUTPUT_REL must not exist (never overwrite)

Deviation from the specification (documented, conservative): the closure
check requires COMPOSITE_VERIFICATION_COMPLETE, FORMAL_GLOBAL_VERIFICATION_
COMPLETE and READY_FOR_SCIENTIFIC_ANALYSIS in addition to MEASUREMENTS_
COMPLETE, every closure section PASS and the closure commit to be an
ancestor of HEAD; closure and acceptance must be unmodified as well as
tracked. PILOT_ACCEPTANCE_COMPLETE / PUBLICATION_READY are NOT required: the
closure was computed before the author's decision; the decision is
validated live by the acceptance check.

Python 3.8 compatible syntax.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

from thesis.study_analysis import core
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import checked_path
from thesis.recovery_successor_004 import census as cs
from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt
from thesis.study_closure import acceptance as ca
from thesis.study_closure import report as cr

PASS = "PASS"
FAIL = "FAIL"
CLOSURE_ID = "study_closure_001"
# the technical closure flags the analysis needs; the two author flags are
# validated live (acceptance check), the closure predates the decision
REQUIRED_CLOSURE_FLAGS = ("MEASUREMENTS_COMPLETE", "COMPOSITE_VERIFICATION_COMPLETE",
                          "FORMAL_GLOBAL_VERIFICATION_COMPLETE", "READY_FOR_SCIENTIFIC_ANALYSIS")
ACCEPTED = "ACCEPTED"
# provider code the package must never import (prefix match) and the
# provider chokepoints it must never name
FORBIDDEN_IMPORTS = ("thesis.generation.generate", "thesis.generation.batch_api", "thesis.repair.run_repair",
                     "anthropic", "openai", "google.genai", "google.generativeai", "dashscope", "dotenv")
FORBIDDEN_NAMES = ("require_provider_call", "call_with_retries", "submit_batch", "poll_batch",
                   "bootstrap_provider_run")
# modules that must not be loaded in the analysis process. dotenv is not
# among them: the config loader imports it at module level and
# pl.isolate_providers neutralises its load_dotenv (checked separately)
FORBIDDEN_MODULES = tuple(name for name in FORBIDDEN_IMPORTS if name != "dotenv")
EXAMPLES = core.EXAMPLES


# -- check accumulation ----------------------------------------------------------------

class CheckList:
    """Ordered checks; guard() turns every exception into a FAIL with its
    message (fail-closed). Shared with validate.py."""

    def __init__(self):
        self.checks = []

    def add(self, check, ok, detail=None):
        self.checks.append(OrderedDict([("check", check), ("status", PASS if ok else FAIL),
                                        ("detail", core.json_stable(detail))]))
        return bool(ok)

    def guard(self, check, function, *args, **kwargs):
        """function returns (ok, detail)."""
        try:
            ok, detail = function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - every failure is reported
            return self.add(check, False, "%s: %s" % (type(error).__name__, error))
        return self.add(check, ok, detail)

    def failing(self):
        return [c["check"] for c in self.checks if c["status"] != PASS]

    @property
    def status(self):
        return PASS if self.checks and not self.failing() else FAIL


def problems_detail(problems, **facts):
    detail = OrderedDict(facts)
    detail["problems"] = list(problems)[:EXAMPLES]
    detail["problem_count"] = len(problems)
    return detail


# -- read helpers (shared with manifest.py / validate.py) ---------------------------------

def read_json_file(root, relative):
    """(document, raw sha256, bytes) of a repo-relative JSON file; missing refuses."""
    path = checked_path(Path(root).resolve(), relative)
    if not path.is_file():
        raise core.AnalysisRefused("missing input: " + relative)
    data = path.read_bytes()
    document = json.loads(data.decode("utf-8"), object_pairs_hook=OrderedDict)
    return document, hashlib.sha256(data).hexdigest(), len(data)


def read_closure(root):
    """The closure document, self-hash verified."""
    document, raw, size = read_json_file(root, core.CLOSURE_REL)
    cr.verify_document(document)
    return document, raw, size


def read_composite(root):
    """The persisted phase-2 composite, self-hash verified."""
    document, raw, size = read_json_file(root, pc.DOCUMENT_REL)
    pc.verify_document(document)
    return document, raw, size


def read_acceptance(root):
    return read_json_file(root, core.ACCEPTANCE_REL)


# -- git -------------------------------------------------------------------------------

def _git(root, *args):
    """(returncode, stdout) of a read-only git command in root."""
    root = Path(root).resolve()
    command = ["git", "-c", "safe.directory=" + root.as_posix(), "-C", str(root)] + list(args)
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    return completed.returncode, completed.stdout


def git_untracked(root, relatives):
    """The given repo-relative paths git does not track."""
    code, out = _git(root, "ls-files", "-z", "--", *relatives)
    if code != 0:
        raise core.AnalysisRefused("git ls-files failed (exit %d)" % code)
    tracked = set(p for p in out.split("\0") if p)
    return [r for r in relatives if r not in tracked]


def git_changed(root, relatives):
    """Porcelain status lines (modified, staged, untracked) for the paths."""
    code, out = _git(root, "status", "--porcelain", "--untracked-files=all", "--", *relatives)
    if code != 0:
        raise core.AnalysisRefused("git status failed (exit %d)" % code)
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def git_is_ancestor(root, commit, head="HEAD"):
    code, _ = _git(root, "merge-base", "--is-ancestor", commit, head)
    if code not in (0, 1):
        raise core.AnalysisRefused("git merge-base --is-ancestor failed for %s (exit %d)" % (commit, code))
    return code == 0


def package_files(root):
    """Repo-relative paths of every regular file of the package directory
    (the code and data the formal results are bound to)."""
    root = Path(root).resolve()
    base = checked_path(root, core.PACKAGE_REL)
    if not base.is_dir():
        raise core.AnalysisRefused("missing package directory " + core.PACKAGE_REL)
    files = sorted(p.relative_to(root).as_posix() for p in base.iterdir() if p.is_file())
    if core.METHODOLOGY_REL not in files:
        raise core.AnalysisRefused("the frozen methodology is missing: " + core.METHODOLOGY_REL)
    return files


def tracked_unmodified(root, relative):
    """(ok, problems) for one input that must be tracked and unmodified."""
    problems = []
    if git_untracked(root, [relative]):
        problems.append("%s is not tracked in git" % relative)
    changed = git_changed(root, [relative])
    if changed:
        problems.append("%s differs from HEAD: %s" % (relative, changed[:3]))
    return problems


# -- pure checks ---------------------------------------------------------------------------

def closure_problems(document):
    """Problems of an (already self-hash verified) closure document."""
    problems = []
    if document.get("closure_id") != CLOSURE_ID:
        problems.append("closure_id %r is not %s" % (document.get("closure_id"), CLOSURE_ID))
    if document.get("status") != PASS:
        problems.append("closure status %r is not PASS" % document.get("status"))
    if document.get("formal") is not True:
        problems.append("the closure is not formal (formal=%r)" % document.get("formal"))
    flags = document.get("flags") or {}
    for flag in REQUIRED_CLOSURE_FLAGS:
        if flags.get(flag) != "YES":
            problems.append("closure flag %s is %r, not YES" % (flag, flags.get(flag)))
    if list(document.get("run_ids") or []) != list(core.RUNS):
        problems.append("closure run_ids %s differ from %s" % (document.get("run_ids"), list(core.RUNS)))
    if list(document.get("model_ids") or []) != list(core.MODELS):
        problems.append("closure model_ids differ from the study models")
    sections = document.get("sections") or []
    if not sections:
        problems.append("the closure has no sections")
    for section in sections:
        if section.get("status") != PASS:
            problems.append("closure section %s is %s" % (section.get("section"), section.get("status")))
    composite = (document.get("summary") or {}).get("composite") or {}
    if composite.get("relative") != pc.DOCUMENT_REL or composite.get("persisted") is not True:
        problems.append("the closure's summary.composite does not name a persisted %s" % pc.DOCUMENT_REL)
    if not ((document.get("git") or {}).get("head")):
        problems.append("the closure records no git head")
    return problems


def composite_problems(document, raw_sha256, closure):
    """The persisted composite is the fingerprinted one (self-hash already verified)."""
    problems = []
    sha = document.get("composite_sha256")
    if sha != core.EXPECTED_COMPOSITE_SHA256:
        problems.append("composite_sha256 %s is not the expected %s" % (sha, core.EXPECTED_COMPOSITE_SHA256))
    named = ((closure or {}).get("summary") or {}).get("composite") or {}
    if named.get("composite_sha256") != sha:
        problems.append("closure summary.composite.composite_sha256 %s differs from %s"
                        % (named.get("composite_sha256"), sha))
    if named.get("raw_sha256") != raw_sha256:
        problems.append("closure summary.composite.raw_sha256 %s differs from the file's %s"
                        % (named.get("raw_sha256"), raw_sha256))
    if named.get("relative") != pc.DOCUMENT_REL or named.get("persisted") is not True:
        problems.append("the closure does not name the persisted composite %s" % pc.DOCUMENT_REL)
    if document.get("run_id") != core.PHASE2:
        problems.append("composite run_id %r is not %s" % (document.get("run_id"), core.PHASE2))
    if list(document.get("model_ids") or []) != list(core.MODELS):
        problems.append("composite model_ids differ from the study models")
    return problems


def acceptance_problems(document, validation):
    """The author's decision is ACCEPTED and valid for the live gate."""
    problems = []
    if not isinstance(document, dict) or document.get("status") != ACCEPTED:
        problems.append("acceptance status %r is not ACCEPTED"
                        % (document.get("status") if isinstance(document, dict) else None))
    if validation.get("status") != ACCEPTED:
        problems.append("validated status %r is not ACCEPTED" % validation.get("status"))
    if validation.get("valid_for_gate") is not True:
        problems.append("the acceptance is not valid for the gate: %s" % (validation.get("problems") or [])[:3])
    if validation.get("publication_allowed") is not True:
        problems.append("publication is not allowed: %s" % (validation.get("reasons") or [])[:3])
    return problems


def census_problems(summary, lineage_digest=None, table_digest=None, models=None):
    """Every repair loop terminal, the base population, one repair
    condition, the frozen census digests. Both digests are mandatory: a
    lineage or target table without its census binding (None) is a problem,
    never 'not given' (fail closed)."""
    models = list(models or core.MODELS)
    per_block = len(models) * len(core.VARIANTS)
    total = len(core.BLOCKS) * per_block
    problems = []
    if summary.get("total_repair_loops_done") != "%d/%d" % (total, total):
        problems.append("repair loops done %s, expected %d/%d" % (summary.get("total_repair_loops_done"),
                                                                  total, total))
    blocks = summary.get("blocks") or {}
    for block in core.BLOCKS:
        entry = blocks.get(block) or {}
        if entry.get("loops") != per_block or entry.get("terminal") != per_block:
            problems.append("%s: %s/%s loops terminal, expected %d" % (block, entry.get("terminal"),
                                                                       entry.get("loops"), per_block))
        if entry.get("open") or entry.get("not_started"):
            problems.append("%s: open %s, not started %s" % (block, entry.get("open"), entry.get("not_started")))
    base = summary.get("base_cells") or {}
    expected = OrderedDict([("pilot", pc.EXPECTED_POPULATION[core.PILOT]),
                            ("full_ext", pc.EXPECTED_POPULATION[core.PARENT])])
    for block, cells in expected.items():
        if base.get(block) != cells:
            problems.append("%s base cells %s, expected %d" % (block, base.get(block), cells))
    if base.get("total") != pc.POPULATION_CELLS:
        problems.append("base cells %s, expected %d" % (base.get("total"), pc.POPULATION_CELLS))
    if len(summary.get("repair_conditions") or []) != 1:
        problems.append("repair conditions %s, expected exactly one" % summary.get("repair_conditions"))
    digest = canonical_sha256(summary)
    for name, frozen in (("lineage", lineage_digest), ("target table", table_digest)):
        if not frozen:
            problems.append("the %s carries no census_digest: the census is unbound" % name)
        elif digest != frozen:
            problems.append("census digest %s differs from the %s's %s" % (digest, name, frozen))
    return problems


PACKAGE_MODULE = core.PACKAGE_REL.replace("/", ".")   # thesis.study_analysis


def _forbidden(name):
    return any(name == f or name.startswith(f + ".") for f in FORBIDDEN_IMPORTS)


def _from_module(node, package=PACKAGE_MODULE):
    """Absolute module of an ImportFrom: a relative import ('from ..x
    import y', 'from . import z') resolves against the package (level 1 =
    the package itself); None when it climbs above the top-level package."""
    if not node.level:
        return node.module
    parts = package.split(".")
    if node.level - 1 >= len(parts):
        return None
    base = parts[:len(parts) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def _dotted(node):
    """'a.b.c' of a Name/Attribute chain, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def provider_scan(root):
    """Offending imports / names in the package modules (AST scan).

    Absolute and relative imports (resolved against the package), the names
    they bind (an alias of a forbidden module or of its parent package is
    followed through attribute chains: 'generation.generate.main' after
    'from .. import generation'), dotted attribute chains naming a forbidden
    module ('thesis.repair.run_repair'), the forbidden chokepoint names and
    __import__ / import_module with a literal name."""
    root = Path(root).resolve()
    base = checked_path(root, core.PACKAGE_REL)
    offending = []
    modules = sorted(base.glob("*.py"))
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        aliases[alias.asname] = alias.name
                    else:
                        top = alias.name.split(".")[0]
                        aliases.setdefault(top, top)
            elif isinstance(node, ast.ImportFrom):
                module = _from_module(node)
                if module is None:
                    offending.append("%s imports beyond the top-level package (level %d)" % (path.name, node.level))
                    continue
                for alias in node.names:
                    aliases[alias.asname or alias.name] = "%s.%s" % (module, alias.name)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = _from_module(node)
                if module is not None:
                    names = [module] + ["%s.%s" % (module, alias.name) for alias in node.names]
            for name in names:
                if _forbidden(name):
                    offending.append("%s imports %s" % (path.name, name))
            if isinstance(node, (ast.Name, ast.Attribute)):
                identifier = node.id if isinstance(node, ast.Name) else node.attr
                if identifier in FORBIDDEN_NAMES:
                    offending.append("%s references %s" % (path.name, identifier))
                dotted = _dotted(node)
                if dotted is not None:
                    head, _, rest = dotted.partition(".")
                    resolved = aliases.get(head, head) + ("." + rest if rest else "")
                    if "." in resolved and _forbidden(resolved):
                        offending.append("%s references %s" % (path.name, resolved))
            function = node.func if isinstance(node, ast.Call) else None
            called = function.id if isinstance(function, ast.Name) else \
                (function.attr if isinstance(function, ast.Attribute) else None)
            if called in ("__import__", "import_module") and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                name = node.args[0].value
                if _forbidden(name):
                    offending.append("%s dynamically imports %s" % (path.name, name))
    return sorted(set(offending)), len(modules)


def loaded_provider_modules(modules=None):
    loaded = sys.modules if modules is None else modules
    return sorted(name for name in FORBIDDEN_MODULES
                  if name in loaded or any(key.startswith(name + ".") for key in loaded))


def dotenv_disabled():
    """True iff the config loader's load_dotenv is the isolation no-op
    (never calls it: an un-isolated call would import .env)."""
    import thesis.config.load_config as loader

    function = getattr(loader, "load_dotenv", None)
    module = getattr(function, "__module__", "") or ""
    return function is not None and not module.startswith("dotenv")


# -- the gate ----------------------------------------------------------------------------------

def preflight(root=core.REPO_ROOT, write_mode=False, deep=False):
    """OrderedDict(analysis_id, write_mode, deep, status PASS/FAIL, checks,
    facts). Never raises; nothing is written."""
    root = Path(root).resolve()
    gate = CheckList()
    facts = OrderedDict([("git_head", None), ("closure_sha256", None), ("closure_raw_sha256", None),
                         ("composite_sha256", None), ("composite_raw_sha256", None),
                         ("acceptance_raw_sha256", None), ("lineage_sha256", None), ("targets_sha256", None),
                         ("census_digest", None), ("methodology", None), ("addendum", None)])
    state = OrderedDict()
    try:
        core.provider_isolation()
        isolation_error = None
    except Exception as error:  # noqa: BLE001
        isolation_error = "%s: %s" % (type(error).__name__, error)

    def git_check():
        git = core.git_state(root)
        facts["git_head"] = git["head"]
        problems = []
        if write_mode and not git["clean"]:
            problems.append("write mode needs a clean worktree (%d uncommitted path(s): %s)"
                            % (git["uncommitted_count"], git["uncommitted_paths"][:5]))
        return not problems, problems_detail(problems, head=git["head"], branch=git["branch"], clean=git["clean"],
                                             uncommitted_count=git["uncommitted_count"],
                                             uncommitted_paths=git["uncommitted_paths"][:EXAMPLES])

    gate.guard("git", git_check)

    def package_check():
        files = package_files(root)
        untracked = git_untracked(root, files)
        changed = git_changed(root, [core.PACKAGE_REL])
        problems = []
        if write_mode and untracked:
            problems.append("package file(s) not tracked at HEAD: %s" % untracked[:5])
        if write_mode and changed:
            problems.append("package differs from HEAD: %s" % changed[:5])
        return not problems, problems_detail(problems, files=len(files), untracked=untracked[:EXAMPLES],
                                             changed=changed[:EXAMPLES], required=bool(write_mode))

    gate.guard("package_committed", package_check)

    def closure_check():
        document, raw, size = read_closure(root)
        state["closure"] = document
        facts["closure_sha256"] = document.get("closure_sha256")
        facts["closure_raw_sha256"] = raw
        problems = closure_problems(document)
        problems.extend(tracked_unmodified(root, core.CLOSURE_REL))
        head = (document.get("git") or {}).get("head")
        if head and not git_is_ancestor(root, head):
            problems.append("the closure commit %s is not an ancestor of HEAD" % head)
        return not problems, problems_detail(problems, relative=core.CLOSURE_REL, raw_sha256=raw, bytes=size,
                                             closure_sha256=document.get("closure_sha256"),
                                             closure_head=head, flags=document.get("flags"))

    gate.guard("closure", closure_check)

    def composite_check():
        document, raw, size = read_composite(root)
        state["composite"] = document
        facts["composite_sha256"] = document.get("composite_sha256")
        facts["composite_raw_sha256"] = raw
        if "closure" not in state:
            raise core.AnalysisRefused("the closure document is unavailable (closure check failed to load it)")
        problems = composite_problems(document, raw, state["closure"])
        return not problems, problems_detail(problems, relative=pc.DOCUMENT_REL, raw_sha256=raw, bytes=size,
                                             composite_sha256=document.get("composite_sha256"),
                                             expected=core.EXPECTED_COMPOSITE_SHA256)

    gate.guard("composite", composite_check)

    def acceptance_check():
        document, raw, size = read_acceptance(root)
        facts["acceptance_raw_sha256"] = raw
        validation = ca.validate_acceptance(root, document)
        problems = acceptance_problems(document, validation)
        problems.extend(tracked_unmodified(root, core.ACCEPTANCE_REL))
        return not problems, problems_detail(problems, relative=core.ACCEPTANCE_REL, raw_sha256=raw,
                                             status=validation.get("status"),
                                             valid_for_gate=validation.get("valid_for_gate"),
                                             publication_allowed=validation.get("publication_allowed"),
                                             label_required=validation.get("label_required"))

    gate.guard("acceptance", acceptance_check)

    def lineage_check():
        lineage = pl.load(root)
        state["lineage"] = lineage
        facts["lineage_sha256"] = lineage.sha256
        table = pt.load_table(root, lineage.targets_sha256)
        state["table"] = table
        facts["targets_sha256"] = table.sha256
        problems = []
        if table.sha256 != lineage.targets_sha256:
            problems.append("target table %s differs from the lineage's %s" % (table.sha256, lineage.targets_sha256))
        composite = state.get("composite")
        if composite is None:
            problems.append("the composite is unavailable (composite check failed to load it)")
        else:
            if composite.get("lineage_sha256") != lineage.sha256:
                problems.append("composite lineage_sha256 %s differs from %s"
                                % (composite.get("lineage_sha256"), lineage.sha256))
            if composite.get("targets_sha256") != table.sha256:
                problems.append("composite targets_sha256 %s differs from %s"
                                % (composite.get("targets_sha256"), table.sha256))
        return not problems, problems_detail(problems, lineage_sha256=lineage.sha256, targets_sha256=table.sha256,
                                             targets=len(table.targets))

    gate.guard("phase2_lineage", lineage_check)
    if deep:
        def lineage_verify():
            lineage = state.get("lineage")
            if lineage is None:
                raise core.AnalysisRefused("the lineage is unavailable")
            return True, OrderedDict([("protected_file_counts", lineage.verify())])

        gate.guard("phase2_lineage_verify", lineage_verify)

    def census_check():
        result = cs.census(root, list(core.MODELS))
        summary = cs.summary(result)
        facts["census_digest"] = canonical_sha256(summary)
        lineage, table = state.get("lineage"), state.get("table")
        if lineage is None or table is None:
            raise core.AnalysisRefused("lineage / target table unavailable: the census digest cannot be bound")
        problems = census_problems(summary, (lineage.document or {}).get("census_digest"),
                                   (table.document or {}).get("census_digest"))
        return not problems, problems_detail(problems, census_digest=facts["census_digest"],
                                             total_repair_loops_done=summary.get("total_repair_loops_done"),
                                             base_cells=summary.get("base_cells"),
                                             sample_states=OrderedDict(
                                                 (b, (summary["blocks"].get(b) or {}).get("sample_states"))
                                                 for b in core.BLOCKS))

    gate.guard("census", census_check)

    def scan_check():
        offending, modules = provider_scan(root)
        return not offending, problems_detail(offending, modules_scanned=modules)

    gate.guard("provider_isolation_scan", scan_check)

    def environment_check():
        if isolation_error:
            raise core.AnalysisRefused("provider isolation failed: " + isolation_error)
        config = core.load_config(root)
        present = pl.provider_environment(config)
        problems = []
        if present:
            problems.append("provider variables present after the scrub: %s" % present)
        if not dotenv_disabled():
            problems.append("the config loader's .env import is not disabled")
        loaded = loaded_provider_modules()
        if loaded:
            problems.append("provider module(s) loaded in the analysis process: %s" % loaded)
        return not problems, problems_detail(problems, provider_variables=len(present), dotenv_import="DISABLED"
                                             if dotenv_disabled() else "ENABLED", provider_modules=loaded)

    gate.guard("provider_environment", environment_check)

    def methodology_check():
        document = core.load_methodology(root)
        ids = core.metric_ids(document)
        identity = core.methodology_identity(root)
        facts["methodology"] = identity
        problems = [] if len(ids) == len(set(ids)) and ids else ["metric ids empty or not unique"]
        return not problems, problems_detail(problems, metrics=len(ids), identity=identity)

    gate.guard("methodology", methodology_check)

    def addendum_check():
        methodology = core.load_methodology(root)
        document = core.load_addendum(root, methodology=methodology)
        identity = core.addendum_identity(root)
        facts["addendum"] = identity
        ids = core.addendum_metric_ids(document)
        problems = []
        if (document.get("amends") or {}).get("methodology") != core.METHODOLOGY_REL:
            problems.append("the addendum amends %r, not %s" % ((document.get("amends") or {}).get("methodology"),
                                                                core.METHODOLOGY_REL))
        if not ids:
            problems.append("the addendum declares no metric")
        if write_mode:
            problems.extend(tracked_unmodified(root, core.ADDENDUM_REL))
        return not problems, problems_detail(problems, metrics=ids, identity=identity,
                                             required_committed=bool(write_mode),
                                             methodology_canonical_sha256=canonical_sha256(methodology))

    gate.guard("addendum", addendum_check)

    def output_check():
        path = checked_path(root, core.OUTPUT_REL)
        exists = path.exists() or path.is_symlink()
        problems = []
        if write_mode and exists:
            problems.append("%s exists: formal outputs are never overwritten" % core.OUTPUT_REL)
        return not problems, problems_detail(problems, relative=core.OUTPUT_REL, exists=exists,
                                             required_absent=bool(write_mode))

    gate.guard("output_target", output_check)
    return OrderedDict([("analysis_id", core.ANALYSIS_ID), ("write_mode", bool(write_mode)), ("deep", bool(deep)),
                        ("status", gate.status), ("failing", gate.failing()), ("checks", gate.checks),
                        ("facts", core.json_stable(facts))])


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="study_analysis_001 preflight (read-only)")
    parser.add_argument("--write-mode", action="store_true", help="apply the formal (write) requirements")
    parser.add_argument("--deep", action="store_true", help="also re-hash every protected byte (minutes)")
    args = parser.parse_args(argv)
    result = preflight(core.REPO_ROOT, write_mode=args.write_mode, deep=args.deep)
    sys.stdout.write(json.dumps(result, indent=2, default=str) + "\n")
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
