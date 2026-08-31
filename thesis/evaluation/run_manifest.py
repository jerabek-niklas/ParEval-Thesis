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


def load_manifest(config: "Dict[str, Any]", run_id: str) -> "Optional[Dict[str, Any]]":
    path = manifest_path(config, run_id)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None


ENHANCED_SPECS_DEFAULT = "thesis/results/cache/enhanced/specs.jsonl"


def enhanced_specs_info(config: "Dict[str, Any]") -> "Optional[Dict[str, Any]]":
    """{path, sha256, spec_count} of the enhanced spec file, or None when
    it is missing (runs without the enhanced stage stay possible; the
    caller warns). The specs are part of the TEST SET but live under
    results/cache/ and are gitignored — the manifest's git commit does
    NOT pin them, this hash does. spec_count counts valid-JSON lines."""
    import hashlib

    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    raw = stage.get("specs_file") or ENHANCED_SPECS_DEFAULT
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
    untouched. Stages that do not pass one are unaffected."""
    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    path = manifest_path(config, run_id)

    existing = load_manifest(config, run_id)

    specs_info = enhanced_specs_info(config)

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


def _utc_now() -> str:
    from thesis.generation.common import utc_now_iso

    return utc_now_iso()
