"""Raw-byte protection for historical base AND iteration artifacts."""
from pathlib import Path
from thesis.evaluation import condition_hashing as ch
from thesis.evaluation.recovery_lineage import checked_path, RecoveryRefused


def verify(root, document):
    root = Path(root).resolve()
    if document.get("schema_version") != "recovery_protected_history.v1" or not document.get("files"):
        raise RecoveryRefused("missing protected history inventory")
    paths = set()
    for area in ("raw", "intermediate"):
        directory = root / "thesis/results" / area
        for run in directory.iterdir():
            if run.is_dir() and any(run.name == p or run.name.startswith(p + "__") for p in ("pilot_002", "full_ext_001")):
                paths.update(p.relative_to(root).as_posix() for p in run.rglob("*") if p.is_file())
    paths.update("thesis/evaluation/" + p for p in (
        "full_extension_equivalence.json", "full_ext_001_population.json", "full_001_composite.json"))
    if paths != set(document["files"]):
        raise RecoveryRefused("historical artifact membership changed")
    for path in sorted(paths):
        if ch.raw_sha256(checked_path(root, path)) != document["files"][path]:
            raise RecoveryRefused("protected historical bytes changed: " + path)
    return dict(inventory_sha256=ch.canonical_sha256(document), file_count=len(paths),
                pilot_files=sum("/pilot_002" in p for p in paths),
                full_ext_files=sum(p.startswith(("thesis/results/raw/full_ext_001", "thesis/results/intermediate/full_ext_001")) for p in paths))
