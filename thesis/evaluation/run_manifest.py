"""Run manifest: freeze the run's configuration AT RUN TIME (2026-08-08).

build_overview.py used to read the LIVE config.yaml at report-build time
and print it as the "Effective config snapshot" — after any later config
edit the report documented a configuration the run never ran under. The
manifest closes that gap: the FIRST stage that touches a run directory
writes results/intermediate/<run_id>/run_manifest.json with the
profile-resolved config plus environment provenance; every later stage
invocation compares its config against the frozen one and, on deviation,
prints a WARN line and APPENDS the changed key paths to the manifest's
config_drift list. Continuation runs with a changed config are allowed —
but visible, in the terminal AND in the artifact.

The frozen fields are NEVER overwritten; only config_drift grows.

Python 3.8 compatible; additive file, no record-schema change.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

MANIFEST_NAME = "run_manifest.json"


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so tuple/scalar-type differences never show
    up as false config drift (YAML loads lists, code may pass tuples)."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def config_key_diff(
    old: Any, new: Any, prefix: str = ""
) -> "List[str]":
    """Dot-paths where two (JSON-normalized) config trees differ.

    Dicts recurse (added/removed keys included); everything else compares
    wholesale — a changed list reports its own path, not per-element noise."""
    if isinstance(old, dict) and isinstance(new, dict):
        paths: "List[str]" = []
        for key in sorted(set(old) | set(new)):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            if key not in old:
                paths.append(child_prefix + " (added)")
            elif key not in new:
                paths.append(child_prefix + " (removed)")
            else:
                paths.extend(config_key_diff(old[key], new[key], child_prefix))
        return paths

    if old != new:
        return [prefix or "<root>"]

    return []


def _git_info() -> "Dict[str, Any]":
    """Commit + dirty flag; tolerant — containers may lack git entirely."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=20, cwd=str(REPO_ROOT),
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True,
            timeout=30, cwd=str(REPO_ROOT),
        )
        if commit.returncode == 0:
            return {
                "git_commit": commit.stdout.strip(),
                "git_dirty": bool(status.stdout.strip())
                if status.returncode == 0 else None,
            }
    except (OSError, subprocess.SubprocessError):
        pass
    return {"git_commit": "unknown", "git_dirty": None}


def _compiler_version(compiler: str) -> "Optional[str]":
    try:
        result = subprocess.run(
            [compiler, "--version"], capture_output=True, text=True, timeout=20
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _toolchain_versions_text(intermediate_dir: Path, run_id: str) -> "Optional[str]":
    """Reuse the existing toolchain-versions.txt logic (copy-into-run-dir)
    from run_static_analysis instead of duplicating it, then read the
    result. Lazy import: run_static_analysis imports THIS module."""
    from thesis.evaluation.run_static_analysis import record_toolchain_versions

    record_toolchain_versions(intermediate_dir, run_id)

    target = intermediate_dir / run_id / "toolchain-versions.txt"
    if target.exists():
        return target.read_text(encoding="utf-8")
    return None


def manifest_path(config: "Dict[str, Any]", run_id: str) -> Path:
    return Path(config["outputs"]["intermediate_dir"]) / run_id / MANIFEST_NAME


def _write_manifest(path: Path, data: "Dict[str, Any]") -> None:
    """ATOMIC write: temp file in the SAME directory + os.replace.

    With parallel per-model terminals, two processes can start the same
    run_id near-simultaneously — both see no manifest and both write. The
    content is identical in that case (same config), but a reader must
    never catch a partially written file: the rename makes every
    observable state a complete manifest (last writer wins, benignly).
    Same-directory temp file because os.replace is only atomic within one
    filesystem. The drift/enrichment rewrites go through this too — the
    torn-read hazard is identical there."""
    path.parent.mkdir(parents=True, exist_ok=True)

    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent),
        prefix=path.name + ".", suffix=".tmp", delete=False,
    )
    try:
        with handle as file:
            json.dump(data, file, indent=2, sort_keys=True)
            file.write("\n")
        os.replace(handle.name, str(path))
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def _intermediate_dir(config: "Dict[str, Any]") -> Path:
    return Path(config["outputs"]["intermediate_dir"])


def uses_fragments(config: "Dict[str, Any]", run_id: str) -> bool:
    """Fragment-based run (every new run; pilot_001 stays a legacy
    shared-manifest run and is never migrated in place)."""
    from thesis.evaluation import manifest_fragments

    return manifest_fragments.uses_fragments(_intermediate_dir(config), run_id)


def manifest_architecture(config: "Dict[str, Any]", run_id: str) -> str:
    """PER_WRITER_FRAGMENTS | LEGACY_SHARED_MANIFEST | NONE"""
    from thesis.evaluation import manifest_fragments

    if manifest_fragments.fragments_dir(_intermediate_dir(config), run_id).is_dir():
        return "PER_WRITER_FRAGMENTS"
    if manifest_path(config, run_id).is_file():
        return "LEGACY_SHARED_MANIFEST"
    return "NONE"


def load_manifest(config: "Dict[str, Any]", run_id: str) -> "Optional[Dict[str, Any]]":
    """The run's manifest. For fragment-based runs this is the deterministic
    MERGE of the fragments (the truth), not the snapshot file; legacy runs
    return their shared run_manifest.json as before."""
    from thesis.evaluation import manifest_fragments

    intermediate_dir = _intermediate_dir(config)
    if manifest_fragments.fragments_dir(intermediate_dir, run_id).is_dir():
        try:
            return manifest_fragments.merge_fragments(intermediate_dir, run_id)
        except (json.JSONDecodeError, OSError):
            return None
    path = manifest_path(config, run_id)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None


def _register_via_fragment(config: "Dict[str, Any]", run_id: str, kind: str,
                           owner: "Optional[str]", content: "Dict[str, Any]",
                           fingerprint: "Optional[str]", writer: str,
                           conflict_type: type) -> None:
    """Fragment registration + snapshot refresh; a fingerprint conflict is
    re-raised as the caller's documented exception type."""
    from thesis.evaluation import manifest_fragments

    intermediate_dir = _intermediate_dir(config)
    try:
        manifest_fragments.register_fragment(
            intermediate_dir, run_id, kind, owner, content,
            fingerprint=fingerprint, writer=writer)
    except manifest_fragments.FragmentConflict as conflict:
        raise conflict_type(str(conflict)) from conflict
    manifest_fragments.write_snapshot(intermediate_dir, run_id)


class AssemblySetMismatch(RuntimeError):
    """The same run already registers a different assembly set for a model."""


class RuntimeEvidenceMismatch(RuntimeError):
    """The same run already registers different T0 runtime evidence."""


class ContractMismatch(RuntimeError):
    """The same run already registers a different frozen contract sha."""


def register_assembly_set(config: "Dict[str, Any]", run_id: str, model_id: str,
                          sample_count: int, assembly_set_sha256: str,
                          assembly_condition_sha256: str,
                          counts: "Optional[Dict[str, int]]" = None) -> None:
    """Per-model assembly set: first registration records it, an identical
    re-registration is idempotent, a DIFFERENT set for the same model under
    the same run is a hard failure (never last-writer-wins). Legacy runs
    without a fragments dir are left untouched (their manifest is frozen
    history); the per-model assembly_summary.json still carries the set."""
    if not uses_fragments(config, run_id):
        return
    content = {
        "model_id": model_id,
        "sample_count": int(sample_count),
        "assembly_set_sha256": assembly_set_sha256,
        "assembly_condition_sha256": assembly_condition_sha256,
        "counts": dict(counts or {}),
    }
    fingerprint = _fingerprint({
        "assembly_set_sha256": assembly_set_sha256,
        "assembly_condition_sha256": assembly_condition_sha256,
        "sample_count": int(sample_count),
    })
    _register_via_fragment(config, run_id, "assembly", model_id, content, fingerprint,
                           "assembly", AssemblySetMismatch)


def register_runtime_evidence(config: "Dict[str, Any]", run_id: str,
                              evidence: "Dict[str, Any]",
                              fingerprint: "Optional[str]" = None) -> None:
    """T0 runtime evidence (contract sha, main runtime sha, static/repair
    runtime sha, compiler/MPI identities) bound to the run BEFORE any
    cost-causing request; a different evidence set later is refused."""
    if not uses_fragments(config, run_id):
        raise RuntimeEvidenceMismatch(
            "run %s is a legacy shared-manifest run; runtime evidence can only "
            "be bound to a fragment-based run" % run_id)
    # the fingerprint is the METHODICAL identity of the measured runtime; the
    # caller supplies it so volatile fields (probe timestamp/duration) cannot
    # make two starters disagree about the same runtime
    _register_via_fragment(config, run_id, "runtime", "evidence", _jsonable(evidence),
                           fingerprint, "t0_guard", RuntimeEvidenceMismatch)


def register_contract(config: "Dict[str, Any]", run_id: str,
                      contract_sha256: str, contract: "Dict[str, Any]") -> None:
    """Bind the frozen pilot run contract sha to the run (T0)."""
    if not uses_fragments(config, run_id):
        raise ContractMismatch(
            "run %s is a legacy shared-manifest run; a contract can only be bound "
            "to a fragment-based run" % run_id)
    content = {"contract_sha256": contract_sha256, "contract": _jsonable(contract)}
    _register_via_fragment(config, run_id, "contract", None, content, contract_sha256,
                           "t0_guard", ContractMismatch)


def _fingerprint(obj: Any) -> str:
    from thesis.evaluation.condition_hashing import canonical_sha256

    return canonical_sha256(obj)


ENHANCED_SPECS_DEFAULT = "thesis/results/cache/enhanced/specs.jsonl"


def enhanced_specs_info(config: "Dict[str, Any]",
                        specs_path: "Optional[str]" = None
                        ) -> "Optional[Dict[str, Any]]":
    """{path, sha256, spec_count} of the enhanced spec file, or None when
    it is missing (runs without the enhanced stage stay possible; the
    caller warns). The specs are part of the TEST SET but live under
    results/cache/ and are gitignored — the manifest's git commit does
    NOT pin them, this hash does. spec_count counts valid-JSON lines."""
    import hashlib

    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    # E3.1.1: the caller may pass the spec file this invocation ACTUALLY used
    # (run_enhanced_tests --specs). Without it the manifest would pin the config
    # default while enhanced_execution hashes the CLI file - two contradictory
    # spec provenances for one run.
    raw = specs_path or stage.get("specs_file") or ENHANCED_SPECS_DEFAULT
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path

    if not path.exists():
        return None

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)

    spec_count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                json.loads(line)
                spec_count += 1
            except ValueError:
                continue

    return {"path": str(raw), "sha256": digest.hexdigest(),
            "spec_count": spec_count}


class AnalysisConditionMismatch(RuntimeError):
    """A run manifest already records a different static/repair condition."""


def _register_condition(config: "Dict[str, Any]", run_id: str, field: str,
                        sha: str, condition: "Dict[str, Any]") -> None:
    """Static/Repair tool-state wave: pin a content-addressed condition
    (static_analysis_condition_sha256 / repair_condition_sha256) in the run
    manifest. First contact writes it; a later contact with a DIFFERENT sha
    is a hard failure - the same run must not mix analysis conditions.
    Manifests that predate the field (pilot_001) are backfilled ONCE and the
    backfill is recorded as a limitation, never silently.

    Fragment-based runs write their own fragment (static.condition.json /
    repair.condition.json) instead of read-modify-writing the shared file;
    the mismatch rule is identical."""
    if uses_fragments(config, run_id):
        if manifest_architecture(config, run_id) == "NONE":
            return
        name = field.replace("_sha256", "")
        kind = "static" if name.startswith("static") else "repair"
        _register_via_fragment(config, run_id, kind, "condition", {name: condition},
                               sha, kind, AnalysisConditionMismatch)
        return
    path = manifest_path(config, run_id)
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    recorded = manifest.get(field)
    if recorded is None:
        manifest[field] = sha
        manifest[field.replace("_sha256", "")] = condition
        if manifest.get("created_by_stage") not in (None, "static_analysis", "repair"):
            manifest.setdefault("condition_backfills", []).append(
                {"field": field, "note": "condition pinned after run creation "
                                          "(earlier stages ran without it)"})
        _write_manifest(path, manifest)
        return
    if recorded != sha:
        raise AnalysisConditionMismatch(
            "run manifest %s records %s = %s... but this invocation computes %s.... "
            "The tool implementation, tool config, build config, TU strategy or "
            "repair policy changed mid-run; use a fresh run_id."
            % (path, field, recorded[:12], sha[:12]))


def register_static_condition(config: "Dict[str, Any]", run_id: str,
                              sha: str, condition: "Dict[str, Any]") -> None:
    _register_condition(config, run_id, "static_analysis_condition_sha256", sha, condition)


def register_repair_condition(config: "Dict[str, Any]", run_id: str,
                              sha: str, condition: "Dict[str, Any]") -> None:
    _register_condition(config, run_id, "repair_condition_sha256", sha, condition)


def register_model_execution(config: "Dict[str, Any]", run_id: str,
                             model_id: str, fingerprint_sha: str) -> None:
    """Register one model's execution fingerprint in the run manifest.

    E3.1.1. The manifest is run_id-global but a run may legitimately cover
    several models, each with its own candidate code. So the per-model condition
    is an ADDITIVE mapping:

        first time a model appears   -> recorded, allowed
        same model, same fingerprint -> allowed
        same model, other fingerprint-> hard fail (different experiment)

    A second model under the same run_id is therefore never blocked just
    because a first model registered earlier.

    Fragment-based runs: one fragment per model (enhanced.<model_id>.json),
    so two models registering concurrently can never lose each other.
    """
    if uses_fragments(config, run_id):
        if manifest_architecture(config, run_id) == "NONE":
            return
        _register_via_fragment(
            config, run_id, "enhanced", model_id,
            {"model_id": model_id, "enhanced_execution_fingerprint_sha256": fingerprint_sha},
            fingerprint_sha, "enhanced_tests", EnhancedExecutionConditionMismatch)
        return
    path = manifest_path(config, run_id)
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mapping = manifest.setdefault("model_execution_fingerprints", {})
    recorded = mapping.get(model_id)
    if recorded is None:
        mapping[model_id] = fingerprint_sha
        _write_manifest(path, manifest)
        return
    if recorded != fingerprint_sha:
        raise EnhancedExecutionConditionMismatch(
            "run manifest %s already records model %r under model execution "
            "fingerprint %s, but this invocation runs it under %s. The candidate "
            "code, the spec set or the harness differs; use a fresh run_id."
            % (path, model_id, recorded, fingerprint_sha))


class EnhancedExecutionConditionMismatch(RuntimeError):
    """The run manifest belongs to a different enhanced execution condition.

    Fail-closed: raised BEFORE any record is written or skipped, so a run can
    never mix two conditions under one manifest.
    """


def ensure_run_manifest(
    config: "Dict[str, Any]",
    run_id: str,
    stage: str,
    profile: "Optional[str]" = None,
    primary_compiler: str = "g++",
    prompt_selection: "Optional[Dict[str, Any]]" = None,
    enhanced_policy: "Optional[Dict[str, Any]]" = None,
    enhanced_execution: "Optional[Dict[str, Any]]" = None,
    enhanced_specs_path: "Optional[str]" = None,
) -> "Dict[str, Any]":
    """Create the manifest on first contact with a run directory; on later
    contacts detect and RECORD config drift (never overwrite the frozen
    snapshot). Returns the manifest dict (frozen or freshly created).

    prompt_selection (optional, from common.prompt_selection_report):
    stored at creation; if the manifest already exists WITHOUT one, it is
    added once — an additive enrichment, the frozen fields stay untouched.

    enhanced_specs pins the gitignored spec file ({path, sha256,
    spec_count}) with resolved_config semantics: written once at
    creation, later contacts only COMPARE and record deviations in
    config_drift ("spec file changed after run start") — never an abort.

    enhanced_execution (optional, from
    execution_provenance.enhanced_execution_fingerprint, E3.1) pins the FULL
    enhanced execution condition. Unlike every other field here it is a HARD
    GATE: if an existing manifest records a different fingerprint (or none),
    this raises EnhancedExecutionConditionMismatch instead of recording drift.

    enhanced_policy (optional, from capabilities.policy_preflight, E2-A.1)
    records WHICH enforced capability policy governed the run: content
    hashes of the policy artifact and of the audit catalog it was derived
    from, plus status, benchmark count and derivation version. Stored at
    creation and backfilled ONCE into a manifest that lacks it — the same
    additive enrichment prompt_selection uses; the frozen fields stay
    untouched. Stages that do not pass one are unaffected.

    Concurrency (pilot_002 pre-run wave): every NEW run is fragment-based -
    the frozen snapshot, each enrichment, each drift record and each later
    registration is its own atomically written file, merged read-only (see
    manifest_fragments.py). Legacy runs with a shared run_manifest.json and
    no fragments dir keep the read-modify-write path below, unchanged."""
    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    path = manifest_path(config, run_id)

    if uses_fragments(config, run_id):
        return _ensure_run_manifest_fragments(
            config, run_id, stage, profile, primary_compiler, prompt_selection,
            enhanced_policy, enhanced_execution, enhanced_specs_path)

    existing = load_manifest(config, run_id)

    specs_info = enhanced_specs_info(config, enhanced_specs_path)

    if existing is None:
        if specs_info is None:
            print(
                f"[{stage}] WARNING: enhanced spec file not found — "
                "recording enhanced_specs: null in the manifest (runs "
                "without the enhanced stage stay possible)."
            )
        manifest: "Dict[str, Any]" = {
            "run_id": run_id,
            "profile": profile,
            "created_at_utc": _utc_now(),
            "created_by_stage": stage,
            **_git_info(),
            "python_version": platform.python_version(),
            "primary_compiler": primary_compiler,
            "primary_compiler_version": _compiler_version(primary_compiler),
            "toolchain_versions": _toolchain_versions_text(
                intermediate_dir, run_id
            ),
            "resolved_config": _jsonable(config),
            "enhanced_specs": specs_info,
            "config_drift": [],
        }
        if prompt_selection is not None:
            manifest["prompt_selection"] = _jsonable(prompt_selection)
        if enhanced_policy is not None:
            manifest["enhanced_policy"] = _jsonable(enhanced_policy)
        if enhanced_execution is not None:
            manifest["enhanced_execution"] = _jsonable(enhanced_execution)
        _write_manifest(path, manifest)
        print(f"[{stage}] run manifest frozen: {path}")
        return manifest

    enriched = False

    if prompt_selection is not None and "prompt_selection" not in existing:
        existing["prompt_selection"] = _jsonable(prompt_selection)
        enriched = True

    if enhanced_policy is not None and "enhanced_policy" not in existing:
        existing["enhanced_policy"] = _jsonable(enhanced_policy)
        enriched = True

    # E3.1 HARD GATE for productive enhanced runs. Unlike config drift, a
    # changed enhanced EXECUTION CONDITION means the existing records and the
    # ones this invocation would write are not the same experiment. Recording
    # it as drift and continuing would let one manifest describe two conditions,
    # so this aborts BEFORE anything is written or skipped. A manifest that
    # predates the fingerprint is not silently backfilled either: it has no
    # evidence of the condition its records were produced under.
    if enhanced_execution is not None:
        recorded = existing.get("enhanced_execution")
        recorded_sha = (recorded or {}).get(
            "enhanced_execution_fingerprint_sha256")
        current_sha = enhanced_execution.get(
            "enhanced_execution_fingerprint_sha256")
        if recorded_sha != current_sha:
            raise EnhancedExecutionConditionMismatch(
                "run manifest %s was frozen under enhanced execution "
                "fingerprint %s but this invocation runs under %s. The two are "
                "different experiments; use a fresh run_id. (A --force rerun "
                "does not make them the same run.)"
                % (path, recorded_sha or "<none recorded>", current_sha))

    # legacy manifests (pre enhanced_specs) get the pin backfilled ONCE
    # without counting it as drift — there is no frozen value to deviate
    # from
    if "enhanced_specs" not in existing:
        existing["enhanced_specs"] = specs_info
        enriched = True

    if enriched:
        _write_manifest(path, existing)

    changed = config_key_diff(
        existing.get("resolved_config"), _jsonable(config)
    )

    specs_changed = config_key_diff(
        existing.get("enhanced_specs"), _jsonable(specs_info),
        prefix="enhanced_specs",
    )
    if specs_changed:
        print(
            f"[{stage}] WARNING: enhanced spec file changed after run "
            "start (%s) — the run's enhanced results no longer rest on "
            "the pinned spec set; recorded in config_drift."
            % ", ".join(specs_changed)
        )

    changed = changed + specs_changed

    if changed:
        if changed != specs_changed:  # config part present
            print(
                f"[{stage}] WARNING: current config deviates from the run "
                f"manifest frozen at {existing.get('created_at_utc')} — "
                "continuation runs with a changed config are allowed but "
                "RECORDED. Changed keys: " + ", ".join(changed)
            )

        drift = existing.setdefault("config_drift", [])
        # skip only exact consecutive repeats (every resumed stage would
        # otherwise append an identical entry per invocation)
        if not drift or drift[-1].get("changed_keys") != changed:
            drift.append({
                "detected_at_utc": _utc_now(),
                "stage": stage,
                "changed_keys": changed,
            })
            _write_manifest(path, existing)

    return existing


def _ensure_run_manifest_fragments(
    config: "Dict[str, Any]",
    run_id: str,
    stage: str,
    profile: "Optional[str]",
    primary_compiler: str,
    prompt_selection: "Optional[Dict[str, Any]]",
    enhanced_policy: "Optional[Dict[str, Any]]",
    enhanced_execution: "Optional[Dict[str, Any]]",
    enhanced_specs_path: "Optional[str]",
) -> "Dict[str, Any]":
    """Fragment-based ensure_run_manifest: same semantics as the legacy path
    (frozen first contact, additive enrichment, recorded drift, hard gate on
    the enhanced execution condition) without any read-modify-write."""
    from thesis.evaluation import manifest_fragments as mf

    intermediate_dir = _intermediate_dir(config)
    specs_info = enhanced_specs_info(config, enhanced_specs_path)
    global_path = mf.fragment_path(intermediate_dir, run_id, "global")
    # E3.1: only the invocation that CREATES the run may pin the enhanced
    # execution condition. A run that already exists without one has no
    # evidence of the condition its records were produced under, so it is
    # never backfilled-and-reused (identical to the legacy shared-manifest
    # rule).
    creating_run = not global_path.is_file()

    if creating_run:
        if specs_info is None:
            print(
                f"[{stage}] WARNING: enhanced spec file not found — "
                "recording enhanced_specs: null in the manifest (runs "
                "without the enhanced stage stay possible)."
            )
        frozen: "Dict[str, Any]" = {
            "run_id": run_id,
            "profile": profile,
            "created_at_utc": _utc_now(),
            "created_by_stage": stage,
            **_git_info(),
            "python_version": platform.python_version(),
            "primary_compiler": primary_compiler,
            "primary_compiler_version": _compiler_version(primary_compiler),
            "toolchain_versions": _toolchain_versions_text(intermediate_dir, run_id),
            "resolved_config": _jsonable(config),
            "enhanced_specs": specs_info,
            "manifest_architecture": "PER_WRITER_FRAGMENTS",
        }
        # the frozen snapshot is content-addressed by its CONFIG, so two
        # processes creating the same run concurrently (same config) are
        # idempotent, while a different config for the same fresh run_id is
        # a conflict, not a silent last-writer-wins
        fingerprint = _fingerprint({"resolved_config": frozen["resolved_config"],
                                    "enhanced_specs": specs_info,
                                    "primary_compiler": primary_compiler})
        try:
            mf.register_fragment(intermediate_dir, run_id, "global", None, frozen,
                                 fingerprint=fingerprint, writer=stage)
            print(f"[{stage}] run manifest frozen (fragments): {global_path.parent}")
        except mf.FragmentConflict:
            # another process froze a different config first: fall through
            # and record OUR deviation as drift against the frozen one
            pass

    merged = mf.merge_fragments(intermediate_dir, run_id)

    for field, value in (("prompt_selection", prompt_selection),
                         ("enhanced_policy", enhanced_policy)):
        if value is None:
            continue
        content = {field: _jsonable(value)}
        try:
            mf.register_fragment(intermediate_dir, run_id, "enrichment", field, content,
                                 writer=stage)
        except mf.FragmentConflict:
            # legacy semantics: the first recorded value stays frozen; a
            # deviating later value is RECORDED, not silently accepted
            _register_drift_fragment(intermediate_dir, run_id, stage,
                                     ["%s (conflicting later value)" % field])

    if enhanced_execution is not None:
        recorded_sha = (merged.get("enhanced_execution") or {}).get(
            "enhanced_execution_fingerprint_sha256")
        current_sha = enhanced_execution.get("enhanced_execution_fingerprint_sha256")
        if recorded_sha is None and not creating_run and _enhanced_records_exist(intermediate_dir, run_id):
            # a run that already holds enhanced records under NO recorded
            # fingerprint predates the gate: refused. A run whose manifest
            # T0 / generation created WITHOUT enhanced records lets its FIRST
            # enhanced invocation pin the fingerprint (the productive order
            # of a contracted run).
            raise EnhancedExecutionConditionMismatch(
                "run manifest %s was frozen under enhanced execution fingerprint "
                "<none recorded> but this invocation runs under %s. The two are "
                "different experiments; use a fresh run_id. (A --force rerun does "
                "not make them the same run.)" % (global_path.parent, current_sha))
        if recorded_sha is not None and recorded_sha != current_sha:
            raise EnhancedExecutionConditionMismatch(
                "run manifest %s was frozen under enhanced execution "
                "fingerprint %s but this invocation runs under %s. The two are "
                "different experiments; use a fresh run_id. (A --force rerun "
                "does not make them the same run.)"
                % (global_path.parent, recorded_sha, current_sha))
        try:
            mf.register_fragment(intermediate_dir, run_id, "enhanced_execution", None,
                                 _jsonable(enhanced_execution),
                                 fingerprint=current_sha, writer=stage)
        except mf.FragmentConflict as conflict:
            raise EnhancedExecutionConditionMismatch(str(conflict)) from conflict

    merged = mf.merge_fragments(intermediate_dir, run_id)

    changed = config_key_diff(merged.get("resolved_config"), _jsonable(config))
    specs_changed = config_key_diff(merged.get("enhanced_specs"), _jsonable(specs_info),
                                    prefix="enhanced_specs")
    if specs_changed:
        print(
            f"[{stage}] WARNING: enhanced spec file changed after run "
            "start (%s) — the run's enhanced results no longer rest on "
            "the pinned spec set; recorded in config_drift."
            % ", ".join(specs_changed)
        )
    changed = changed + specs_changed
    if changed:
        if changed != specs_changed:
            print(
                f"[{stage}] WARNING: current config deviates from the run "
                f"manifest frozen at {merged.get('created_at_utc')} — "
                "continuation runs with a changed config are allowed but "
                "RECORDED. Changed keys: " + ", ".join(changed)
            )
        _register_drift_fragment(intermediate_dir, run_id, stage, changed)

    mf.write_snapshot(intermediate_dir, run_id)
    return mf.merge_fragments(intermediate_dir, run_id)


def _enhanced_records_exist(intermediate_dir: Path, run_id: str) -> bool:
    run_dir = Path(intermediate_dir) / run_id
    if not run_dir.is_dir():
        return False
    try:
        return any((entry / "enhanced_tests.jsonl").is_file()
                   for entry in run_dir.iterdir() if entry.is_dir())
    except OSError:
        return True  # unreadable: fail closed


def _register_drift_fragment(intermediate_dir: Path, run_id: str, stage: str,
                             changed: "List[str]") -> None:
    """One drift record per distinct set of changed keys: content-keyed, so
    the same deviation seen by many invocations (legacy rule: "exact
    consecutive repeats are skipped") is recorded once, by the stage that
    first saw it, and never read-modified-written."""
    from thesis.evaluation import manifest_fragments as mf

    key = _fingerprint({"changed_keys": changed})[:12]
    content = {"detected_at_utc": _utc_now(), "stage": stage, "changed_keys": changed}
    try:
        mf.register_fragment(intermediate_dir, run_id, "drift", key,
                             content, fingerprint=key, writer=stage, history=False)
    except mf.FragmentConflict:
        pass


def _utc_now() -> str:
    from thesis.generation.common import utc_now_iso

    return utc_now_iso()
