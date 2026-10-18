"""Input manifest of the study analysis (study_analysis_manifest.v1).

The manifest names every input the results depend on, by repo-relative
path and raw sha256: the code (package sources, LF-pinned), the frozen
methodology and next to it its post-freeze addendum (core.addendum_identity:
raw / LF / canonical sha256 and status), the closure, the persisted
composite, the pilot acceptance,
the target/lineage/census identities the dataset was built against, and
every file the normalizer itself opened (dataset.provenance files_read)
plus extra files of the caller. It is self-hashed (manifest_sha256 over
everything except `volatile`, which alone holds timestamps and the
interpreter), so two runs over the same inputs produce the same hash.

rehash() re-reads every named input and returns the paths whose bytes
changed (or vanished, or appeared in the package): run.py builds the
manifest before aggregation and rehashes after it, so a result can never
silently mix two states of an input.

A file the normalizer hashed and the caller lists again (extra_files) must
carry the same bytes: two different states of one input refuse.

Shape (documented reading of the specification): files_read maps each
repo-relative path to OrderedDict(raw_sha256, bytes) - the sha256 the
normalizer recorded (or, for extra files, the one hashed here) and the size
at manifest time, so totals.bytes needs no second read; rehash() compares
both. dataset=None gives the start manifest (no dataset identities).

Python 3.8 compatible syntax.
"""
from __future__ import annotations

import hashlib
import platform
from collections import OrderedDict
from pathlib import Path

from thesis.study_analysis import core
from thesis.study_analysis import preflight as pf

PROVENANCE_KEYS = ("targets_sha256", "census_digest", "readers", "files_read")


class Paths:
    """checked_path semantics (canonical relative path, no escape, no link or
    junction on the way) with every directory verified once: thousands of
    input files share a few hundred directories, and each stat costs on the
    Windows bind mount."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.verified = set()

    def path(self, relative):
        if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
            raise core.AnalysisRefused("expected canonical repo-relative path: %r" % (relative,))
        parts = relative.split("/")
        if relative.startswith("/") or any(part in ("", ".", "..") for part in parts):
            raise core.AnalysisRefused("path escapes the repository: %r" % relative)
        current = self.root
        for position, part in enumerate(parts):
            current = current / part
            key = str(current)
            if key in self.verified:
                continue
            if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
                raise core.AnalysisRefused("symlink/junction evidence is forbidden: " + relative)
            if position < len(parts) - 1:
                self.verified.add(key)
        return current

    def relative(self, path):
        """A repo-relative POSIX path (absolute paths must lie inside root)."""
        text = str(path).replace("\\", "/")
        candidate = Path(text)
        if candidate.is_absolute():
            try:
                # no resolve(): a link on the given path must not be followed away
                text = candidate.relative_to(self.root).as_posix()
            except ValueError:
                raise core.AnalysisRefused("input outside the repository: %s" % path)
        self.path(text)
        return text


def file_facts(root, relative, paths=None):
    """OrderedDict(raw_sha256, bytes) of one repo-relative file; missing refuses."""
    path = (paths or Paths(root)).path(relative)
    if not path.is_file():
        raise core.AnalysisRefused("missing input file: " + relative)
    data = path.read_bytes()
    return OrderedDict([("raw_sha256", hashlib.sha256(data).hexdigest()), ("bytes", len(data))])


def _provenance(dataset):
    provenance = dataset.provenance
    missing = [key for key in PROVENANCE_KEYS if key not in provenance]
    if missing:
        raise core.AnalysisRefused("dataset provenance lacks %s" % missing)
    return provenance


def input_manifest(root, dataset, extra_files=()):
    """The self-hashed input manifest. dataset may be None for the start
    manifest (before the normalizer ran): the dataset identities are then
    null and files_read holds only extra_files."""
    root = Path(root).resolve()
    paths = Paths(root)
    closure, closure_raw, closure_bytes = pf.read_closure(root)
    composite, composite_raw, composite_bytes = pf.read_composite(root)
    acceptance, acceptance_raw, acceptance_bytes = pf.read_acceptance(root)
    files = OrderedDict()
    if dataset is not None:
        provenance = _provenance(dataset)
        for relative, sha in (provenance.get("files_read") or {}).items():
            relative = paths.relative(relative)
            if not isinstance(sha, str) or len(sha) != 64:
                raise core.AnalysisRefused("files_read entry without a sha256: " + relative)
            path = paths.path(relative)
            files[relative] = OrderedDict([("raw_sha256", sha),
                                           ("bytes", path.stat().st_size if path.is_file() else None)])
        dataset_inputs = OrderedDict([
            ("targets_sha256", provenance.get("targets_sha256")),
            ("lineage_sha256", provenance.get("lineage_sha256")),
            ("census_digest", provenance.get("census_digest")),
            ("readers", list(provenance.get("readers") or [])),
            ("counts", dataset.counts()),
        ])
    else:
        dataset_inputs = OrderedDict([("targets_sha256", None), ("lineage_sha256", None), ("census_digest", None),
                                      ("readers", []), ("counts", None)])
    extras = []
    for path in extra_files or ():
        relative = paths.relative(path)
        facts = file_facts(root, relative, paths)
        if relative in files and files[relative]["raw_sha256"] != facts["raw_sha256"]:
            raise core.AnalysisRefused("two states of one input: %s (normalizer %s, now %s)"
                                       % (relative, files[relative]["raw_sha256"], facts["raw_sha256"]))
        files[relative] = facts
        extras.append(relative)
    files = OrderedDict((relative, files[relative]) for relative in sorted(files))
    missing = [relative for relative, facts in files.items() if facts["bytes"] is None]
    if missing:
        raise core.AnalysisRefused("files_read names missing file(s): %s" % missing[:5])
    document = OrderedDict([
        ("schema_version", core.MANIFEST_SCHEMA),
        ("analysis_id", core.ANALYSIS_ID),
        ("git", core.git_state(root)),
        ("methodology", core.methodology_identity(root)),
        ("addendum", core.addendum_identity(root)),
        ("package_sources", core.package_sources(root)),
        ("closure", OrderedDict([("relative", core.CLOSURE_REL), ("raw_sha256", closure_raw),
                                 ("bytes", closure_bytes), ("closure_sha256", closure.get("closure_sha256"))])),
        ("composite", OrderedDict([("relative", pf.pc.DOCUMENT_REL), ("raw_sha256", composite_raw),
                                   ("bytes", composite_bytes),
                                   ("composite_sha256", composite.get("composite_sha256"))])),
        ("acceptance", OrderedDict([("relative", core.ACCEPTANCE_REL), ("raw_sha256", acceptance_raw),
                                    ("bytes", acceptance_bytes), ("status", acceptance.get("status"))])),
        ("dataset_inputs", dataset_inputs),
        ("extra_files", sorted(extras)),
        ("files_read", files),
        ("totals", OrderedDict([("files", len(files)), ("bytes", sum(f["bytes"] for f in files.values()))])),
        ("volatile", OrderedDict([("generated_at_utc", core.utc_now()), ("python", platform.python_version()),
                                  ("platform", platform.platform())])),
    ])
    document = core.json_stable(document)
    document["manifest_sha256"] = core.self_hash(document, "manifest_sha256")
    return document


def verify_manifest(manifest):
    if manifest.get("schema_version") != core.MANIFEST_SCHEMA or manifest.get("analysis_id") != core.ANALYSIS_ID:
        raise core.AnalysisRefused("not a %s manifest of %s" % (core.MANIFEST_SCHEMA, core.ANALYSIS_ID))
    if core.self_hash(manifest, "manifest_sha256") != manifest.get("manifest_sha256"):
        raise core.AnalysisRefused("the input manifest does not reproduce its hash")
    return True


def rehash(root, manifest):
    """Sorted repo-relative paths whose bytes differ from the manifest
    (changed, vanished; for the package also files added or removed)."""
    root = Path(root).resolve()
    paths = Paths(root)
    changed = set()

    def compare(relative, expected_sha, expected_bytes=None):
        try:
            facts = file_facts(root, relative, paths)
        except Exception:  # noqa: BLE001 - a vanished or unreadable input is a change
            changed.add(relative)
            return
        if facts["raw_sha256"] != expected_sha or (expected_bytes is not None and facts["bytes"] != expected_bytes):
            changed.add(relative)

    for relative, facts in (manifest.get("files_read") or {}).items():
        compare(relative, facts.get("raw_sha256"), facts.get("bytes"))
    for block in ("closure", "composite", "acceptance"):
        entry = manifest.get(block) or {}
        if not entry.get("relative"):
            changed.add("<%s>" % block)
            continue
        compare(entry["relative"], entry.get("raw_sha256"), entry.get("bytes"))
    methodology = manifest.get("methodology") or {}
    compare(methodology.get("relative") or core.METHODOLOGY_REL, methodology.get("raw_sha256"))
    addendum = manifest.get("addendum") or {}
    compare(addendum.get("relative") or core.ADDENDUM_REL, addendum.get("raw_sha256"))
    recorded = manifest.get("package_sources") or {}
    try:
        current = core.package_sources(root)
    except Exception:  # noqa: BLE001
        current = OrderedDict()
        changed.add(core.PACKAGE_REL)
    for relative in set(recorded) | set(current):
        if recorded.get(relative) != current.get(relative):
            changed.add(relative)
    return sorted(changed)
