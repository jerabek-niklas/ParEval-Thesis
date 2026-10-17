"""Sections `identity`, `runs` and `tree` of the study closure.

identity  who verifies: the git state of the worktree, the LF source pins of
          every closure and reused module, and the proof that no closure
          module can reach a provider (AST scan, scrubbed environment, the
          no-op dotenv loader installed by lineage.isolate_providers).
runs      the binding of each of the seven runs: complete manifest, frozen
          contract (self-hash), start authorization (native post-run view),
          fragment integrity (every fragment reproduces its fingerprint, no
          temporary / torn / foreign file in the fragments dir or its history,
          and the merged snapshot run_manifest.json reconciles with the
          fragments on disk: same set, same registered fingerprints, the
          runtime-evidence and authorization snapshots equal their fragments),
          T0 runtime evidence (fingerprint reproduces, native pilot checks and
          the native bound-T0 rule), every stage runtime stamp (bound to its
          file name, no duplicate stage), the contracted model set; plus the
          uniformity of the runtime identity and of the enhanced specs across
          the runs.
tree      the scope of the results tree: every directory under raw and
          intermediate explained (study / excluded / out of study), no
          successor writer lock, the raw-byte inventory of the phase-2
          results tree (no temporary or torn file), the excluded parent
          repair present but never adopted by any study assembly.

Read-only. Every check is a pure function over explicit inputs so the tests
can exercise it on synthetic artifacts; collect_*(ctx) wire the real inputs.
collect(ctx) returns the three sections in evidence order (run.py accepts a
list). The per-run bindings go into ctx.cache["run_bindings"] for the later
sections. Numbers are computed, never assumed; the real study is expected to
show 7 complete manifests, 29 stage runtime stamps, one runtime identity
(0d5f4889... / static 1f773327... / repair 98b8be0f...), 789 phase-2 result
files and 0 unexplained result directories.

    python3 -B -m thesis.study_closure.runs      (prints the three sections)

Python 3.8 compatible.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.condition_hashing import canonical_sha256  # noqa: E402
from thesis.evaluation.recovery_lineage import checked_path  # noqa: E402
from thesis.recovery_successor_005 import composite as pc  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.study_closure import core  # noqa: E402

EXAMPLES = 10
PACKAGE_REL = "thesis/study_closure"
# provider code no closure module may import: the generation / batch modules,
# the repair driver, the provider SDKs and the .env loader. The repair
# orchestrator is NOT listed: the native successor verifiers import it
# read-only and the closure imports those verifiers.
FORBIDDEN_IMPORTS = ("thesis.generation.generate", "thesis.generation.batch_api",
                     "thesis.repair.run_repair", "anthropic", "openai", "google.genai",
                     "google.generativeai", "dashscope", "dotenv")
FORBIDDEN_NAMES = ("require_provider_call", "call_with_retries", "submit_batch", "poll_batch",
                   "bootstrap_provider_run")
# binding key -> manifest runtime_evidence field (the four runtime identities)
RUNTIME_FIELDS = OrderedDict([
    ("readiness_rt", "readiness_runtime_condition_sha256"),
    ("fresh_rt", "fresh_runtime_condition_sha256"),
    ("static_cond", "static_analysis_condition_sha256"),
    ("repair_cond", "repair_condition_sha256"),
])
# runs whose frozen contract must name every study model
FULL_MODEL_RUNS = (core.PILOT, core.PARENT, pl.ORIGIN, core.PHASE2)
PHASE2_READINESS_REL = pl.DEFINITIONS_REL + "/readiness.json"
ORIGIN_READINESS_REL = "thesis/evaluation/recovery/" + pl.ORIGIN + "/readiness.json"
METHODOLOGY_FREEZE_REL = "thesis/evaluation/pilot_002_methodology_freeze.json"
FROZEN_SPECS_REL = "thesis/enhanced_tests/frozen/e3_final_specs.jsonl"
FRAGMENTS_DIR_NAME = "run_manifest.fragments"
# every entry a stage stamp writer can leave behind: the stamp itself and,
# after a crash, its '<name>.tmp-<pid>-<tid>-<token>' temp file (atomic_io)
STAGE_STAMP_GLOB = "runtime.stage.*"
STAGE_OWNER_PREFIX = "stage."
# the two fragments whose content the merged snapshot copies verbatim
SNAPSHOT_FRAGMENTS = (("runtime_evidence", ("runtime", "evidence")),
                      ("authorization", ("authorization", "start")))
LOCKS_DIR_NAME = ".successor_locks"
TEMP_MARKER = ".tmp-"
TORN_SUFFIX = ".torn"
AREAS = ("intermediate", "raw")
PASS = core.PASS


def short(value):
    return core.short(value)


def _json_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def _relative_text(root, text):
    """Error text without the absolute repository prefix: the native loaders
    name absolute paths (load_frozen, checked_path) and a check detail may
    only carry repo-relative ones."""
    if root is None:
        return text
    resolved = Path(root).resolve()
    for prefix in sorted({resolved.as_posix() + "/", str(resolved) + "/", str(resolved) + "\\"},
                         key=len, reverse=True):
        text = text.replace(prefix, "")
    return text


def _loaded(section, check_id, loader, *args, root=None):
    """Load an input of a check; a loader failure is that check's FAIL and
    yields None (dependent checks then fail with 'input unavailable')."""
    try:
        return loader(*args)
    except Exception as error:  # noqa: BLE001 - every failure is reported
        section.add(check_id, False, _relative_text(root, "%s: %s" % (type(error).__name__, error)))
        return None


def _stray_file(name):
    """A file no fragment reader may trust: a crashed writer's temp file
    ('<target>.tmp-<pid>-<tid>-<token>', atomic_io), a torn-tail archive
    ('*.torn') or anything that is not a .json fragment (load_fragments
    skips such names silently - the closure does not)."""
    return TEMP_MARKER in name or name.endswith(TORN_SUFFIX) or not name.endswith(".json")


def _require(**inputs):
    missing = [name for name, value in inputs.items() if value is None]
    if missing:
        raise core.ClosureRefused("input unavailable: " + ", ".join(missing))


def _last_detail(section):
    return section.checks[-1]["detail"] if section.checks else None


# -- identity -----------------------------------------------------------------------------

def git_identity(root, write):
    """The worktree state; a dirty worktree blocks only the formal (write) closure."""
    state = core.git_state(root)
    detail = OrderedDict(state)
    detail["mode"] = "write" if write else "dry-run"
    detail["clean_required"] = bool(write)
    return bool(state.get("clean")) or not write, detail, state


def source_pins(root):
    """LF pins of every closure module and reused module; a missing reused
    module means the closure would verify against code it cannot pin."""
    missing = [rel for rel in core.REUSED_MODULES if not checked_path(root, rel).is_file()]
    if missing:
        return False, OrderedDict([("missing", missing[:EXAMPLES])]), None
    pins = core.closure_source_pins(root)
    if not pins["closure"]:
        return False, OrderedDict([("missing", []), ("closure_modules", 0)]), pins
    detail = OrderedDict([("closure_modules", len(pins["closure"])),
                          ("reused_modules", len(pins["reused"])), ("missing", [])])
    return True, detail, pins


def provider_scan(directory):
    """AST scan of every module in a directory (the phase-2 preflight rule):
    forbidden provider imports and chokepoint names. Returns (scanned, offending)."""
    scanned, offending = [], []
    for path in sorted(Path(directory).glob("*.py")):
        scanned.append(path.name)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + ["%s.%s" % (node.module, a.name) for a in node.names]
            for name in names:
                if any(name == f or name.startswith(f + ".") for f in FORBIDDEN_IMPORTS):
                    offending.append("%s imports %s" % (path.name, name))
            if isinstance(node, (ast.Name, ast.Attribute)):
                identifier = node.id if isinstance(node, ast.Name) else node.attr
                if identifier in FORBIDDEN_NAMES:
                    offending.append("%s references %s" % (path.name, identifier))
    return scanned, offending


def provider_isolation(root, config):
    """No closure module can reach a provider, no provider variable is in the
    environment, and the config loader's .env import is the installed no-op.
    The loader is OBSERVED as the context left it (core.load_context installs
    the no-op before the first load_config): the check never installs the
    no-op itself (that would make the criterion vacuous) and never calls a
    loader that is not the no-op (that call would import a .env)."""
    import thesis.config.load_config as loader

    scanned, offending = provider_scan(Path(root) / PACKAGE_REL)
    environment = pl.provider_environment(config)
    loader_module = getattr(loader.load_dotenv, "__module__", None)
    dotenv_disabled = loader_module == pl.__name__ and loader.load_dotenv() is False
    problems = list(offending)
    if not scanned:
        problems.append("no closure module found under " + PACKAGE_REL)
    if environment:
        problems.append("provider variables present in the environment: %s" % environment)
    if not dotenv_disabled:
        problems.append("load_config.load_dotenv is not the isolate_providers no-op (%s)" % loader_module)
    detail = OrderedDict([("package", PACKAGE_REL), ("modules_scanned", scanned),
                          ("offending", offending[:EXAMPLES]), ("provider_environment", environment),
                          ("dotenv_disabled", dotenv_disabled), ("dotenv_loader_module", loader_module),
                          ("forbidden_imports", list(FORBIDDEN_IMPORTS)),
                          ("forbidden_names", list(FORBIDDEN_NAMES))])
    return not problems, detail


def collect_identity(ctx):
    section = core.Section("identity")

    def git_check():
        ok, detail, state = git_identity(ctx.root, bool(ctx.options.get("write")))
        section.data["git"] = state
        return ok, detail

    def pins_check():
        ok, detail, pins = source_pins(ctx.root)
        if pins is not None:
            section.data["source_pins"] = pins
        return ok, detail

    section.guard("git_state", git_check)
    section.guard("closure_source_pins", pins_check)
    section.guard("provider_isolation", provider_isolation, ctx.root, ctx.config)
    return section


# -- runs: pure checks over explicit inputs --------------------------------------------------

def manifest_check(manifest, run):
    """The merged manifest is the run's, complete, without missing or
    unexpected fragments and was created from a clean worktree."""
    problems = []
    if manifest.get("run_id") != run:
        problems.append("run_id is %r" % manifest.get("run_id"))
    if manifest.get("complete") is not True:
        problems.append("complete is %r" % manifest.get("complete"))
    if manifest.get("missing_expected_fragments") != []:
        problems.append("missing_expected_fragments: %r" % (manifest.get("missing_expected_fragments"),))
    if manifest.get("unexpected_fragments"):
        problems.append("unexpected_fragments: %r" % (manifest.get("unexpected_fragments"),))
    if manifest.get("git_dirty") is not False:
        problems.append("git_dirty is %r" % manifest.get("git_dirty"))
    detail = OrderedDict([("git_commit", manifest.get("git_commit")),
                          ("created_at_utc", manifest.get("created_at_utc")),
                          ("fragments", len(manifest.get("fragments") or [])),
                          ("config_drift_records", len(manifest.get("config_drift") or [])),
                          ("problems", problems)])
    return not problems, detail


def contract_check(contract, run, profile, manifest_contract_sha):
    """The frozen contract (already self-hash verified by load_frozen) is the
    run's READY contract of the registry profile and the manifest binds it."""
    from thesis.evaluation import pilot_run_contract as prc

    problems = []
    if contract.get("run_id") != run:
        problems.append("run_id is %r" % contract.get("run_id"))
    if contract.get("status") != prc.STATUS_READY:
        problems.append("status is %r" % contract.get("status"))
    if contract.get("profile") != profile:
        problems.append("profile %r != registry profile %r" % (contract.get("profile"), profile))
    if manifest_contract_sha is None:
        problems.append("manifest contract_sha256 unavailable")
    elif contract.get("contract_sha256") != manifest_contract_sha:
        problems.append("contract_sha256 %s != manifest %s" % (short(contract.get("contract_sha256")),
                                                                short(manifest_contract_sha)))
    detail = OrderedDict([("contract_sha256", contract.get("contract_sha256")),
                          ("profile", contract.get("profile")),
                          ("model_ids", len(contract.get("model_ids") or [])), ("problems", problems)])
    return not problems, detail


def authorization_check(state, fragment, run, contract_sha, manifest_auth_sha):
    """The native post-run view of the start authorization: present, allowed,
    fingerprint reproduces, bound to the frozen contract and to the manifest."""
    from thesis.evaluation import run_authorization as ra

    problems = []
    sha = state.get("authorization_sha256")
    if not state.get("present"):
        problems.append("no start authorization fragment")
    else:
        if state.get("decision") != ra.DECISION_ALLOWED:
            problems.append("decision is %r" % state.get("decision"))
        if not sha or sha != state.get("recomputed_sha256"):
            problems.append("authorization_sha256 %s != recomputed %s"
                            % (short(sha), short(state.get("recomputed_sha256"))))
        if contract_sha is None or state.get("frozen_contract_sha256") != contract_sha:
            problems.append("frozen_contract_sha256 %s != contract %s"
                            % (short(state.get("frozen_contract_sha256")), short(contract_sha)))
        if manifest_auth_sha is None or sha != manifest_auth_sha:
            problems.append("authorization_sha256 %s != manifest authorization %s"
                            % (short(sha), short(manifest_auth_sha)))
    content = (fragment or {}).get("content") or {}
    if content.get("run_id") != run:
        problems.append("fragment content run_id is %r" % content.get("run_id"))
    if content.get("authorization_sha256") != sha:
        problems.append("fragment content authorization_sha256 differs from the native view")
    detail = OrderedDict([("authorization_sha256", sha), ("decision", state.get("decision")),
                          ("schema_version", state.get("schema_version")),
                          ("policy_version", state.get("policy_version")), ("problems", problems)])
    return not problems, detail


def snapshot_binding(manifest, fragments, run):
    """The merged snapshot (run_manifest.json) against the fragments on disk
    ([(name, fragment)] as manifest_fragments.load_fragments returns them):
    the same fragment set, every registered (kind, owner, fingerprint) equal
    to the fragment's own and to its file name, every fragment the run's, and
    the runtime-evidence / authorization snapshots canonically equal to the
    fragment contents. A snapshot rewritten after a fragment was deleted or
    edited is otherwise self-consistent and would pass every other check."""
    from thesis.evaluation import manifest_fragments as mf

    if not isinstance(manifest, dict):
        return [OrderedDict([("fragment", None), ("problem", "manifest snapshot unavailable")])]
    problems = []
    loaded = OrderedDict(fragments)
    recorded = manifest.get("fragments")
    if not isinstance(recorded, dict):
        problems.append(OrderedDict([("fragment", None), ("problem", "snapshot without a fragments section")]))
        recorded = OrderedDict()
    for name in sorted(set(recorded) - set(loaded)):
        problems.append(OrderedDict([("fragment", name), ("problem", "registered in the snapshot but not on disk")]))
    for name in sorted(set(loaded) - set(recorded)):
        problems.append(OrderedDict([("fragment", name), ("problem", "on disk but not registered in the snapshot")]))
    for name in sorted(set(loaded) & set(recorded)):
        entry = recorded.get(name) if isinstance(recorded.get(name), dict) else {}
        fragment = loaded[name] if isinstance(loaded[name], dict) else {}
        kind, owner = mf._split(name)
        if (fragment.get("kind"), fragment.get("owner")) != (kind, owner):
            problems.append(OrderedDict([("fragment", name), ("problem", "fragment kind/owner %r differ from its file name"
                                                                % ((fragment.get("kind"), fragment.get("owner")),))]))
        if fragment.get("run_id") != run:
            problems.append(OrderedDict([("fragment", name), ("problem", "fragment run_id is %r" % fragment.get("run_id"))]))
        if not fragment.get("fingerprint_sha256"):
            problems.append(OrderedDict([("fragment", name), ("problem", "fragment without fingerprint")]))
        for field in ("kind", "owner", "fingerprint_sha256"):
            if entry.get(field) != fragment.get(field):
                problems.append(OrderedDict([("fragment", name), ("problem", "snapshot %s %r != fragment %r"
                                                                    % (field, entry.get(field), fragment.get(field)))]))
    for key, (kind, owner) in SNAPSHOT_FRAGMENTS:
        name = mf.fragment_name(kind, owner)
        content = (loaded.get(name) or {}).get("content") if isinstance(loaded.get(name), dict) else None
        snapshot = manifest.get(key)
        if not isinstance(content, dict) or not isinstance(snapshot, dict):
            problems.append(OrderedDict([("fragment", name), ("problem", "snapshot %s or fragment content missing" % key)]))
        elif canonical_sha256(content) != canonical_sha256(snapshot):
            problems.append(OrderedDict([("fragment", name), ("problem", "snapshot %s differs from the fragment content" % key)]))
    return problems


def fragment_integrity(intermediate_dir, run, manifest):
    """Every registered fragment reproduces its content hash and (where the
    rule lives in this repository) its fingerprint; no temporary, torn or
    foreign file in the fragments dir or its history (load_fragments would
    skip them silently); the merged snapshot reconciles with the fragments
    (snapshot_binding); history outcomes counted (REFUSED is reported)."""
    from thesis.evaluation import manifest_fragments as mf

    intermediate_dir = Path(intermediate_dir)
    directory = mf.fragments_dir(intermediate_dir, run)
    if not directory.is_dir():
        raise core.ClosureRefused("no fragments directory for " + run)
    problems = [core.json_stable(p) for p in mf.verify_fragment_integrity(intermediate_dir, run)]
    fragments = mf.load_fragments(intermediate_dir, run)
    stray = []
    for path in sorted(directory.iterdir()):
        if path.is_dir():
            if path.name != mf.HISTORY_DIR_NAME:
                stray.append(path.name + "/")
        elif _stray_file(path.name):
            stray.append(path.name)
    history = directory / mf.HISTORY_DIR_NAME
    outcomes = Counter()
    entries = 0
    if history.is_dir():
        for path in sorted(history.iterdir()):
            relative = mf.HISTORY_DIR_NAME + "/" + path.name
            if not path.is_file() or _stray_file(path.name):
                stray.append(relative)
                continue
            entries += 1
            try:
                outcomes[str(_json_file(path).get("outcome"))] += 1
            except Exception as error:  # noqa: BLE001 - an unreadable history entry is reported
                problems.append(OrderedDict([("fragment", relative),
                                             ("problem", "unreadable history entry: " + type(error).__name__)]))
    for name in stray:
        problems.append(OrderedDict([("fragment", name), ("problem", "temporary, torn or foreign file")]))
    if not fragments:
        problems.append(OrderedDict([("fragment", None), ("problem", "no fragment file")]))
    problems.extend(snapshot_binding(manifest, fragments, run))
    snapshot = (manifest or {}).get("fragments") if isinstance(manifest, dict) else None
    detail = OrderedDict([("fragments", len(fragments)),
                          ("snapshot_fragments", len(snapshot) if isinstance(snapshot, dict) else None),
                          ("stray_files", stray[:EXAMPLES]), ("history_entries", entries),
                          ("history_outcomes", pc.counts(outcomes)),
                          ("refused_history_entries", outcomes.get("REFUSED", 0)),
                          ("problems", [core.json_stable(p) for p in problems][:EXAMPLES])])
    return not problems, detail


def runtime_t0(manifest, contract, run):
    """T0 runtime evidence: the run's, probed OK, fresh == readiness, bound
    to the contract, its registered fingerprint (manifest
    runtime_evidence_sha256) reproduces; plus the native pilot checks and the
    native bound-T0 rule (verify_pilot_run._bound_t0_problems: the evidence,
    the authorization and the contract agree in every binding field and
    every required runtime domain is pinned) - UNRESOLVED counts as FAIL."""
    from thesis.evaluation import run_authorization as ra
    from thesis.evaluation import verify_pilot_run as vpr

    _require(manifest=manifest, contract=contract)
    evidence = manifest.get("runtime_evidence")
    problems = []
    fingerprint_ok = False
    if not isinstance(evidence, dict) or not evidence:
        problems.append("no runtime_evidence in the manifest")
        evidence = {}
    else:
        if evidence.get("run_id") != run:
            problems.append("runtime_evidence.run_id is %r" % evidence.get("run_id"))
        if evidence.get("probe_status") != "OK":
            problems.append("probe_status is %r" % evidence.get("probe_status"))
        fresh = evidence.get("fresh_runtime_condition_sha256")
        if not fresh or fresh != evidence.get("readiness_runtime_condition_sha256"):
            problems.append("fresh runtime %s != readiness runtime %s"
                            % (short(fresh), short(evidence.get("readiness_runtime_condition_sha256"))))
        if evidence.get("contract_sha256") != contract.get("contract_sha256"):
            problems.append("runtime_evidence.contract_sha256 %s != contract %s"
                            % (short(evidence.get("contract_sha256")), short(contract.get("contract_sha256"))))
        registered = manifest.get("runtime_evidence_sha256")
        fingerprint_ok = bool(registered) and registered == ra.t0_evidence_fingerprint(evidence)
        if not fingerprint_ok:
            problems.append("runtime_evidence_sha256 %s does not reproduce the evidence fingerprint" % short(registered))
    report = vpr.Report(run)
    vpr.check_runtime(report, manifest, contract)
    vpr.check_config_drift(report, manifest)
    native = [OrderedDict([("check", c["check"]), ("status", c["status"]), ("detail", c["detail"])])
              for c in report.checks]
    not_pass = ["%s=%s" % (c["check"], c["status"]) for c in native if c["status"] != vpr.PASS]
    if not_pass:
        problems.append("native checks not PASS (UNRESOLVED counts as FAIL): " + ", ".join(not_pass))
    bound, unresolved = vpr._bound_t0_problems(contract, manifest)
    bound, unresolved = [str(p) for p in bound], [str(p) for p in unresolved]
    if bound:
        problems.append("bound T0 evidence contradicted: " + "; ".join(bound[:EXAMPLES]))
    if unresolved:
        problems.append("bound T0 evidence unresolved (counts as FAIL): " + "; ".join(unresolved[:EXAMPLES]))
    detail = OrderedDict([("probe_status", evidence.get("probe_status")),
                          ("fresh_runtime_condition_sha256", evidence.get("fresh_runtime_condition_sha256")),
                          ("readiness_runtime_condition_sha256", evidence.get("readiness_runtime_condition_sha256")),
                          ("fingerprint_reproduces", fingerprint_ok), ("native", native),
                          ("bound_t0_problems", bound[:EXAMPLES]), ("bound_t0_unresolved", unresolved[:EXAMPLES]),
                          ("problems", problems)])
    return not problems, detail


def stamp_problems(stamp, run, contract_sha, authorization_sha):
    """One stage runtime stamp (mirror of verify_recovery_run): the run's,
    matched without drift, bound to contract and authorization, fingerprint reproduces."""
    from thesis.evaluation import stage_runtime as sr

    problems = []
    if stamp.get("run_id") != run:
        problems.append("run_id is %r" % stamp.get("run_id"))
    if stamp.get("match") is not True:
        problems.append("match is %r" % stamp.get("match"))
    if stamp.get("drift_fields"):
        problems.append("drift_fields: %r" % (stamp.get("drift_fields"),))
    if contract_sha is None or stamp.get("contract_sha256") != contract_sha:
        problems.append("contract_sha256 %s != %s" % (short(stamp.get("contract_sha256")), short(contract_sha)))
    if authorization_sha is None or stamp.get("authorization_sha256") != authorization_sha:
        problems.append("authorization_sha256 %s != %s"
                        % (short(stamp.get("authorization_sha256")), short(authorization_sha)))
    if sr._evidence_fingerprint(stamp) != stamp.get("stage_runtime_sha256"):
        problems.append("stage_runtime_sha256 does not reproduce")
    return problems


def stage_stamps(fragments_dir, run, contract_sha, authorization_sha):
    """Every runtime.stage.* entry of the run's fragments dir is a readable
    .json stamp (a crashed writer's '.tmp-' leftover or a '.torn' archive is
    a FAIL), its content validates (stamp_problems), its content.stage is the
    stage its file name is registered for (owner 'stage.<stage>') and no
    stage is stamped twice; at least one stamp."""
    directory = Path(fragments_dir)
    if not directory.is_dir():
        raise core.ClosureRefused("no fragments directory for " + run)
    stages, problems = [], []
    for path in sorted(directory.glob(STAGE_STAMP_GLOB)):
        if not path.is_file():
            problems.append(path.name + ": not a file")
            continue
        if _stray_file(path.name):
            problems.append(path.name + ": temporary, torn or foreign stamp file")
            continue
        content = _json_file(path).get("content")
        if not isinstance(content, dict):
            problems.append(path.name + ": no content")
            continue
        stage = content.get("stage")
        expected = STAGE_OWNER_PREFIX + str(stage)
        owner = path.name[len("runtime."):-len(".json")]
        if not isinstance(stage, str) or not stage or owner != expected:
            problems.append("%s: content.stage %r is not the stage of its file name" % (path.name, stage))
        stages.append(stage)
        problems.extend(path.name + ": " + p for p in stamp_problems(content, run, contract_sha, authorization_sha))
    duplicates = sorted(stage for stage, n in Counter(stages).items() if n > 1)
    if duplicates:
        problems.append("stage stamped more than once: %s" % duplicates[:EXAMPLES])
    if not stages:
        problems.append("no stage runtime stamp")
    detail = OrderedDict([("stages", stages), ("count", len(stages)), ("problems", problems[:EXAMPLES])])
    return not problems, detail


def models_check(model_ids, run):
    """contract.model_ids: non-empty subset of the study models; the pilot,
    the parent, the repair origin and phase 2 name every model."""
    problems = []
    ids = list(model_ids or [])
    if not ids:
        problems.append("empty model_ids")
    unknown = sorted(set(ids) - set(core.MODELS))
    if unknown:
        problems.append("unknown models: %s" % unknown[:EXAMPLES])
    if len(set(ids)) != len(ids):
        problems.append("duplicate model ids")
    full = run in FULL_MODEL_RUNS
    if full and sorted(set(ids)) != sorted(core.MODELS):
        problems.append("expected every study model (%d), got %d" % (len(core.MODELS), len(set(ids))))
    detail = OrderedDict([("model_ids", ids), ("count", len(ids)), ("full_set_required", full),
                          ("problems", problems)])
    return not problems, detail


def runtime_identity(values, references):
    """values: run -> {readiness_rt, fresh_rt, static_cond, repair_cond};
    references: key -> {label: expected sha}. Each of the four values must be
    one non-empty sha across every run and equal every reference."""
    problems = []
    uniform, per_run = OrderedDict(), OrderedDict()
    for key in RUNTIME_FIELDS:
        observed = OrderedDict((run, (entry or {}).get(key)) for run, entry in values.items())
        distinct = sorted(set(str(v) for v in observed.values()))
        first = next(iter(observed.values()), None)
        value = None
        if not observed:
            problems.append(key + ": no run")
        elif len(distinct) != 1 or not isinstance(first, str) or not first:
            problems.append("%s differs across runs: %s" % (key, distinct[:EXAMPLES]))
        else:
            value = first
        uniform[key] = value
        for run, observed_value in observed.items():
            per_run.setdefault(run, OrderedDict())[key] = (value is not None and observed_value == value)
        for label, expected in (references.get(key) or {}).items():
            if value is None or expected != value:
                problems.append("%s: %s %s != runs %s" % (key, label, short(expected), short(value)))
    detail = OrderedDict([("values", uniform), ("per_run", per_run), ("references", references),
                          ("problems", problems[:EXAMPLES])])
    return not problems, detail


def enhanced_specs_uniform(records, references):
    """records: run -> manifest.enhanced_specs ({path, sha256, spec_count});
    references: label -> expected sha. One sha across every run, equal to
    every reference (frozen specs file, contract conditions, methodology freeze)."""
    problems = []
    shas = OrderedDict((run, (record or {}).get("sha256")) for run, record in records.items())
    distinct = sorted(set(str(v) for v in shas.values()))
    first = next(iter(shas.values()), None)
    value = None
    if not shas:
        problems.append("no run")
    elif len(distinct) != 1 or not isinstance(first, str) or not first:
        problems.append("enhanced_specs.sha256 differs across runs: %s" % distinct[:EXAMPLES])
    else:
        value = first
    for label, expected in references.items():
        if value is None or expected != value:
            problems.append("%s: %s != runs %s" % (label, short(expected), short(value)))
    detail = OrderedDict([
        ("sha256", value),
        ("recorded_paths", sorted(set(str((r or {}).get("path")) for r in records.values()))),
        ("spec_counts", sorted(set(str((r or {}).get("spec_count")) for r in records.values()))),
        ("references", references), ("problems", problems[:EXAMPLES])])
    return not problems, detail


# -- runs: wiring --------------------------------------------------------------------------

def _authorization_state(root, config, run):
    """The native post-run view over the run's configured intermediate dir,
    made CWD-independent (load_authorization resolves a relative
    outputs.intermediate_dir against the process CWD) and verified to be the
    study tree."""
    from thesis.evaluation import run_authorization as ra

    configured = (config.get("outputs") or {}).get("intermediate_dir")
    if not isinstance(configured, str) or not configured:
        raise core.ClosureRefused("run config without outputs.intermediate_dir")
    resolved = Path(configured) if Path(configured).is_absolute() else Path(root) / configured
    expected = checked_path(root, core.INTERMEDIATE_REL)
    if resolved.resolve() != expected.resolve():
        raise core.ClosureRefused("the run config's intermediate_dir %s is not the study tree %s"
                                  % (configured, core.INTERMEDIATE_REL))
    view = OrderedDict([("outputs", OrderedDict([("intermediate_dir", str(expected))]))])
    return ra.authorization_state(view, run)


def _collect_run(ctx, section, run):
    """All checks of one run; returns (binding, facts, manifest, contract)."""
    entry = core.RUN_REGISTRY[run]
    prefix = run + ":"
    intermediate = checked_path(ctx.root, core.INTERMEDIATE_REL)
    fragments = intermediate / run / FRAGMENTS_DIR_NAME
    checks = OrderedDict()

    manifest = _loaded(section, prefix + "manifest_complete", ctx.manifest, run, root=ctx.root)
    manifest_ok = False
    if manifest is not None:
        manifest_ok = section.guard(prefix + "manifest_complete", manifest_check, manifest, run)
    checks["manifest_complete"] = section.checks[-1]["status"]

    contract = _loaded(section, prefix + "frozen_contract", ctx.frozen_contract, run, root=ctx.root)
    manifest_contract_sha = (manifest or {}).get("contract_sha256")
    if contract is not None:
        section.guard(prefix + "frozen_contract", contract_check, contract, run, entry["profile"],
                      manifest_contract_sha)
    checks["frozen_contract"] = section.checks[-1]["status"]
    contract_sha = (contract or {}).get("contract_sha256")

    manifest_auth_sha = ((manifest or {}).get("authorization") or {}).get("authorization_sha256")
    config = _loaded(section, prefix + "authorization", ctx.run_config, run, root=ctx.root)
    fragment = state = None
    if config is not None:
        fragment = _loaded(section, prefix + "authorization", ctx.authorization_fragment, run, root=ctx.root)
    if fragment is not None:
        state = _loaded(section, prefix + "authorization", _authorization_state, ctx.root, config, run,
                        root=ctx.root)
    if state is not None:
        section.guard(prefix + "authorization", authorization_check, state, fragment, run, contract_sha,
                      manifest_auth_sha)
    checks["authorization"] = section.checks[-1]["status"]
    auth_sha = (state or {}).get("authorization_sha256")

    section.guard(prefix + "fragment_integrity", fragment_integrity, intermediate, run, manifest)
    checks["fragment_integrity"] = section.checks[-1]["status"]
    fragment_detail = _last_detail(section)

    section.guard(prefix + "runtime_t0", runtime_t0, manifest, contract, run)
    checks["runtime_t0"] = section.checks[-1]["status"]

    section.guard(prefix + "stage_runtime_stamps", stage_stamps, fragments, run, contract_sha, auth_sha)
    checks["stage_runtime_stamps"] = section.checks[-1]["status"]
    stamp_detail = _last_detail(section)

    section.guard(prefix + "models", models_check, (contract or {}).get("model_ids"), run)
    checks["models"] = section.checks[-1]["status"]

    evidence = (manifest or {}).get("runtime_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    model_ids = list((contract or {}).get("model_ids") or [])
    binding = OrderedDict([
        ("contract_sha256", contract_sha), ("authorization_sha256", auth_sha),
        ("manifest_complete", bool(manifest_ok)), ("git_commit", (manifest or {}).get("git_commit")),
        ("model_ids", model_ids),
        ("runtime", OrderedDict((key, evidence.get(field)) for key, field in RUNTIME_FIELDS.items())),
    ])
    facts = OrderedDict([
        ("role", entry["role"]), ("block", entry["block"]), ("profile", entry["profile"]),
        ("contract", entry["contract"]),
        ("manifest", "%s/%s/run_manifest.json" % (core.INTERMEDIATE_REL, run)),
        ("contract_sha256", contract_sha), ("authorization_sha256", auth_sha),
        ("git_commit", (manifest or {}).get("git_commit")),
        ("created_at_utc", (manifest or {}).get("created_at_utc")),
        ("models", len(model_ids)),
        ("fragments", fragment_detail.get("fragments") if isinstance(fragment_detail, dict) else None),
        ("stage_stamps", stamp_detail.get("stages") if isinstance(stamp_detail, dict) else None),
        ("checks", checks),
    ])
    return binding, facts, manifest, contract


def runtime_references(root):
    """What the four runtime identities must equal: the phase-2 readiness
    (origin runtime, static, repair conditions) and the recovery_001 readiness."""
    phase2 = core.read_json(root, PHASE2_READINESS_REL)
    origin = core.read_json(root, ORIGIN_READINESS_REL)

    def ref(field_phase2, field_origin):
        return OrderedDict([(PHASE2_READINESS_REL + ":" + field_phase2, phase2.get(field_phase2)),
                            (ORIGIN_READINESS_REL + ":" + field_origin, origin.get(field_origin))])

    return OrderedDict([
        ("readiness_rt", ref("origin_runtime_condition_sha256", "runtime_condition_sha256")),
        ("fresh_rt", ref("origin_runtime_condition_sha256", "runtime_condition_sha256")),
        ("static_cond", ref("static_analysis_condition_sha256", "static_analysis_condition_sha256")),
        ("repair_cond", ref("repair_condition_sha256", "repair_condition_sha256")),
    ])


def _runtime_identity_check(root, bindings):
    values = OrderedDict((run, binding.get("runtime")) for run, binding in bindings.items())
    return runtime_identity(values, runtime_references(root))


def enhanced_specs_references(root, contracts):
    """The frozen specs file named by the pilot contract (raw sha), every
    contract's enhanced_frozen_specs_sha256 condition, the methodology freeze."""
    pilot = contracts.get(core.PILOT) or {}
    frozen_rel = (pilot.get("conditions") or {}).get("enhanced_frozen_specs_path") or FROZEN_SPECS_REL
    if not checked_path(root, frozen_rel).is_file():
        raise core.ClosureRefused("frozen enhanced specs file missing: " + frozen_rel)
    references = OrderedDict([(frozen_rel + " (raw sha256)", core.raw_sha256(root, frozen_rel))])
    for run, contract in contracts.items():
        references[run + " contract conditions.enhanced_frozen_specs_sha256"] = \
            ((contract or {}).get("conditions") or {}).get("enhanced_frozen_specs_sha256")
    freeze = core.read_json(root, METHODOLOGY_FREEZE_REL)
    references[METHODOLOGY_FREEZE_REL + ":enhanced.frozen_specs_sha256"] = \
        (freeze.get("enhanced") or {}).get("frozen_specs_sha256")
    return references


def _enhanced_specs_check(root, manifests, contracts):
    records = OrderedDict((run, (manifest or {}).get("enhanced_specs")) for run, manifest in manifests.items())
    references = enhanced_specs_references(root, contracts)
    # the manifests record the results-cache copy of the specs: when it still
    # exists its bytes must agree too (absence is no contradiction: the
    # frozen file is the binding reference)
    recorded = sorted(set((r or {}).get("path") for r in records.values()
                          if isinstance((r or {}).get("path"), str)))
    present = [rel for rel in recorded if checked_path(root, rel).is_file()]
    for rel in present:
        references[rel + " (recorded cache copy, raw sha256)"] = core.raw_sha256(root, rel)
    ok, detail = enhanced_specs_uniform(records, references)
    detail["recorded_paths_present"] = present
    return ok, detail


def collect_runs(ctx):
    section = core.Section("runs")
    bindings, facts, manifests, contracts = OrderedDict(), OrderedDict(), OrderedDict(), OrderedDict()
    for run in core.RUNS:
        ctx.log("runs: " + run)
        bindings[run], facts[run], manifests[run], contracts[run] = _collect_run(ctx, section, run)
    ctx.cache["run_bindings"] = bindings
    section.data["runs"] = facts
    section.guard("runtime_identity_uniform", _runtime_identity_check, ctx.root, bindings)
    section.guard("enhanced_specs_uniform", _enhanced_specs_check, ctx.root, manifests, contracts)
    return section


# -- tree ------------------------------------------------------------------------------------

def is_study_iteration(name):
    """<owner>__<variant>__iter<N>: owner the pilot or a repair owner, a
    study variant, 1 <= N <= MAX_ITERATIONS, N spelled canonically ('iter1',
    never 'iter01': the study only ever produces targets.iteration_run names)."""
    parts = name.split("__")
    if len(parts) != 3 or not parts[2].startswith("iter") or not parts[2][4:].isdigit():
        return False
    owner, variant, number = parts[0], parts[1], int(parts[2][4:])
    return (parts[2] == "iter%d" % number and owner in (core.PILOT,) + core.OWNERS
            and variant in core.VARIANTS and 1 <= number <= pl.MAX_ITERATIONS)


def classify_dirs(names, area):
    """Every directory directly under a results area: study (the seven runs
    and their iteration dirs), excluded, out_of_study, forbidden (phase 2
    under raw: it owns no raw tree) or unexplained."""
    if area not in AREAS:
        raise core.ClosureRefused("unknown results area: %r" % (area,))
    classes = OrderedDict((key, []) for key in ("study", "excluded", "out_of_study", "forbidden", "unexplained"))
    for name in sorted(names):
        if name == core.PHASE2 and area == "raw":
            classes["forbidden"].append(name)
        elif name in core.RUNS or is_study_iteration(name):
            classes["study"].append(name)
        elif name in core.EXCLUDED_RUNS:
            classes["excluded"].append(name)
        elif name.startswith(core.OUT_OF_STUDY_PREFIXES):
            classes["out_of_study"].append(name)
        else:
            classes["unexplained"].append(name)
    return classes


def list_area(root, relative):
    """(directory names, file names, locks dir present) of a results area;
    every directory path-checked (a link is refused)."""
    directory = checked_path(root, relative)
    if not directory.is_dir():
        raise core.ClosureRefused("results area missing: " + relative)
    names, files, locks = [], [], False
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        if entry.name == LOCKS_DIR_NAME and entry.is_dir():
            locks = True
        elif entry.is_dir():
            checked_path(root, relative + "/" + entry.name)
            names.append(entry.name)
        else:
            files.append(entry.name)
    return names, files, locks


def scope(root, relative, area, required):
    names, files, locks = list_area(root, relative)
    classes = classify_dirs(names, area)
    missing = [run for run in required if run not in names]
    ok = not classes["unexplained"] and not classes["forbidden"] and not missing
    detail = OrderedDict([("area", relative), ("directories", len(names)),
                          ("counts", OrderedDict((key, len(value)) for key, value in classes.items())),
                          ("study", classes["study"]), ("excluded", classes["excluded"]),
                          ("out_of_study", classes["out_of_study"]), ("forbidden", classes["forbidden"]),
                          ("unexplained", classes["unexplained"][:EXAMPLES]),
                          ("missing_required", missing), ("files_skipped", files[:EXAMPLES]),
                          ("locks_dir_present", locks)])
    return ok, detail


def successor_locks(root):
    """No successor writer lock (*.lock) under the lock directory; other
    entries (e.g. an archived interrupted lock) are reported."""
    from thesis.evaluation import successor_writer as sw

    directory = checked_path(root, sw.LOCK_DIR)
    if not directory.is_dir():
        return True, OrderedDict([("directory", sw.LOCK_DIR), ("present", False), ("lock_files", []),
                                  ("other_entries", [])])
    names = sorted(p.name for p in directory.iterdir())
    locks = [n for n in names if n.endswith(".lock")]
    detail = OrderedDict([("directory", sw.LOCK_DIR), ("present", True), ("lock_files", locks[:EXAMPLES]),
                          ("other_entries", [n for n in names if not n.endswith(".lock")][:EXAMPLES])])
    return not locks, detail


def tree_inventory(root, relative):
    """Raw sha256 + size of every file under a results-tree directory
    (path-checked: a link anywhere refuses the whole inventory)."""
    root = Path(root).resolve()
    base = checked_path(root, relative)
    if not base.is_dir():
        raise core.ClosureRefused("missing results tree: " + relative)
    relatives = sorted(p.relative_to(root).as_posix() for p in base.rglob("*"))

    def facts(rel):
        path = checked_path(root, rel)
        if not path.is_file():
            return None
        return rel, OrderedDict([("sha256", hashlib.sha256(path.read_bytes()).hexdigest()),
                                 ("size", path.stat().st_size)])

    return OrderedDict(item for item in pl.parallel_map(facts, relatives) if item is not None)


def inventory_problems(inventory):
    """Temporary (.tmp-) or torn-tail archive (.torn) files inside a results tree."""
    return [rel for rel in inventory
            if TEMP_MARKER in rel.rsplit("/", 1)[-1] or rel.endswith(TORN_SUFFIX)]


def phase2_inventory(root):
    inventory = tree_inventory(root, core.PHASE2_RESULTS_REL)
    problems = inventory_problems(inventory)
    document = OrderedDict([
        ("relative", core.PHASE2_RESULTS_REL), ("file_count", len(inventory)),
        ("total_bytes", sum(entry["size"] for entry in inventory.values())),
        ("inventory_sha256", canonical_sha256(inventory)), ("files", inventory)])
    if not inventory:
        problems = problems + ["empty phase-2 results tree"]
    detail = OrderedDict([("relative", core.PHASE2_RESULTS_REL), ("file_count", document["file_count"]),
                          ("total_bytes", document["total_bytes"]),
                          ("inventory_sha256", document["inventory_sha256"]),
                          ("temporary_or_torn", problems[:EXAMPLES])])
    return not problems, detail, document


def assembly_scan(root, study_dirs, excluded):
    """Every assembly row of every study directory must point at a source
    under its own run directory; rows under an excluded run are counted."""
    root = Path(root).resolve()
    files = rows = foreign = references = 0
    examples = []
    excluded_prefixes = tuple("%s/%s/" % (core.INTERMEDIATE_REL, run) for run in excluded)
    for name in sorted(study_dirs):
        own = "%s/%s/" % (core.INTERMEDIATE_REL, name)
        directory = checked_path(root, core.INTERMEDIATE_REL + "/" + name)
        for path in sorted(directory.glob("*/assembly.jsonl")):
            rel = path.relative_to(root).as_posix()
            files += 1
            for row in core.read_jsonl(root, rel):
                rows += 1
                source = row.get("source_path")
                if not isinstance(source, str) or not source.startswith(own):
                    foreign += 1
                    if len(examples) < EXAMPLES:
                        examples.append(OrderedDict([("file", rel), ("source_path", source)]))
                if isinstance(source, str) and excluded_prefixes and source.startswith(excluded_prefixes):
                    references += 1
    return OrderedDict([("files", files), ("rows", rows), ("foreign_rows", foreign),
                        ("foreign_examples", examples), ("excluded_references", references)])


def excluded_parent_repair(root, excluded, target_source_runs, study_dirs):
    """The excluded run exists (raw + intermediate), its answers are counted,
    it is no phase-2 target source and no study assembly adopts it."""
    root = Path(root).resolve()
    problems = []
    answers = OrderedDict()
    for run in excluded:
        if not checked_path(root, core.INTERMEDIATE_REL + "/" + run).is_dir():
            problems.append("missing under intermediate: " + run)
        raw = checked_path(root, core.RAW_REL + "/" + run)
        if not raw.is_dir():
            problems.append("missing under raw: " + run)
            answers[run] = 0
        else:
            answers[run] = sum(len(core.read_jsonl(root, p.relative_to(root).as_posix()))
                               for p in sorted(raw.glob("*/generations.jsonl")))
        if run in target_source_runs:
            problems.append("excluded run is a phase-2 target source: " + run)
    scan = assembly_scan(root, study_dirs, excluded)
    if not scan["rows"]:
        problems.append("no study assembly row found")
    if scan["foreign_rows"]:
        problems.append("%d assembly row(s) point outside their own run" % scan["foreign_rows"])
    if scan["excluded_references"]:
        problems.append("%d assembly row(s) reference an excluded run" % scan["excluded_references"])
    detail = OrderedDict([("excluded_runs", list(excluded)), ("excluded_answers", answers),
                          ("target_source_runs", len(target_source_runs)),
                          ("assembly_files", scan["files"]), ("assembly_rows", scan["rows"]),
                          ("foreign_rows", scan["foreign_rows"]), ("foreign_examples", scan["foreign_examples"]),
                          ("excluded_references", scan["excluded_references"]),
                          ("problems", problems[:EXAMPLES])])
    return not problems, detail, answers


def collect_tree(ctx):
    section = core.Section("tree")

    def inventory_check():
        ok, detail, document = phase2_inventory(ctx.root)
        section.data["phase2_inventory"] = document
        return ok, detail

    def excluded_check():
        names, _files, _locks = list_area(ctx.root, core.INTERMEDIATE_REL)
        study_dirs = classify_dirs(names, "intermediate")["study"]
        target_source_runs = sorted(set(target.source_run for target in ctx.table.targets))
        ok, detail, answers = excluded_parent_repair(ctx.root, core.EXCLUDED_RUNS, target_source_runs, study_dirs)
        section.data["excluded_answers"] = answers
        return ok, detail

    section.guard("intermediate_scope", scope, ctx.root, core.INTERMEDIATE_REL, "intermediate", core.RUNS)
    section.guard("raw_scope", scope, ctx.root, core.RAW_REL, "raw", (core.PILOT, core.PARENT))
    section.guard("no_successor_locks", successor_locks, ctx.root)
    section.guard("phase2_results_inventory", inventory_check)
    section.guard("excluded_parent_repair_present_not_adopted", excluded_check)
    return section


# -- entry -----------------------------------------------------------------------------------

def collect(ctx):
    """The three sections in evidence order (run.py accepts a list)."""
    return [collect_identity(ctx), collect_runs(ctx), collect_tree(ctx)]


def main(argv=None):
    """Read-only dry run of the three sections against the repository."""
    import argparse

    parser = argparse.ArgumentParser(description="study closure: identity / runs / tree sections (read-only)")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--full", action="store_true", help="print the full check list")
    args = parser.parse_args(argv)
    ctx = core.load_context(args.root, options={"write": False}, log=lambda m: print(m, file=sys.stderr))
    sections = collect(ctx)
    for section in sections:
        document = section.document()
        if not args.full:
            document = OrderedDict((k, v) for k, v in document.items() if k != "check_list")
            document["data"] = OrderedDict((k, v) for k, v in document["data"].items()
                                           if k not in ("phase2_inventory", "source_pins"))
        print(json.dumps(core.json_stable(document), indent=2, ensure_ascii=False))
    return 0 if all(s.status == PASS for s in sections) else 1


if __name__ == "__main__":
    sys.exit(main())
