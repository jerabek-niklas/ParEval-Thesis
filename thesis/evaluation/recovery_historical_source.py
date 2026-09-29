"""Verify historical sources against Git objects, never the live checkout.

No checkout, index, contract, or evidence file is written by this module.
The commit is taken from the hash-bound parent manifest, not from HEAD.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from functools import lru_cache

from thesis.evaluation import condition_hashing as ch
from thesis.evaluation.recovery_lineage import RecoveryRefused


@lru_cache(maxsize=2048)
def git_blob(root, commit, relative):
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise RecoveryRefused("invalid historical commit")
    if (not relative or relative.startswith("/") or "\\" in relative
            or ":" in relative or ".." in relative.split("/")):
        raise RecoveryRefused("invalid historical source path")
    result = subprocess.run(
        ["git", "-c", "safe.directory=" + str(root), "-C", str(root),
         "show", commit + ":" + relative], capture_output=True, check=False)
    if result.returncode:
        raise RecoveryRefused("historical Git blob unavailable: " + relative)
    return result.stdout


def verify(root, manifest, contract, read_blob=git_blob):
    commit = manifest.get("git_commit")
    if manifest.get("git_dirty") is not False:
        raise RecoveryRefused("parent source snapshot was not clean")
    relative = "thesis/evaluation/full_extension_equivalence.json"
    certificate = json.loads(read_blob(root, commit, relative))
    body = {k: v for k, v in certificate.items() if k != "certificate_sha256"}
    expected = (contract.get("extension_provenance") or {}).get("equivalence_sha256")
    if (not expected or certificate.get("certificate_sha256") != expected
            or ch.canonical_sha256(body) != expected
            or certificate.get("status") != "PROVEN"
            or not certificate.get("source_pins")):
        raise RecoveryRefused("historical certificate/contract mismatch")
    for path, pin in certificate["source_pins"].items():
        raw = read_blob(root, commit, path)
        actual = hashlib.sha256(raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()
        if actual != pin:
            raise RecoveryRefused("historical source pin mismatch: " + path)
    return {"commit": commit, "clean": True, "certificate_sha256": expected,
            "source_pins_sha256": ch.canonical_sha256(certificate["source_pins"]),
            "verified_source_count": len(certificate["source_pins"])}
