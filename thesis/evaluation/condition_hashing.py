"""Two hash classes, kept strictly apart (pilot_002 pre-run wave).

CONDITION HASH  - fingerprints of METHOD: source/policy/reporting
                  implementation files. Computed over LF-NORMALIZED bytes
                  (CRLF -> LF, lone CR -> LF, then SHA-256) so that a
                  condition detects a semantic/content change, never the
                  line-ending style of a git checkout (this repository is
                  checked out with core.autocrlf=true on Windows and LF in a
                  Linux clone; the committed blobs are LF).

ARTIFACT HASH   - fingerprints of ARTIFACTS: the bytes a compiler or a
                  reader actually sees (generated-code.hpp, records). Always
                  RAW BYTES, never normalized: `source_sha256` must be the
                  hash of exactly what was compiled.

Only NEW conditions use the LF-normalized rule. Existing condition versions
(static_condition.v1, repair_condition.v1, the cross-pilot gate's shared
state) keep their documented raw-byte semantics - a hash rule is part of a
condition's version and is never changed silently.

Python 3.8 compatible (the LLOV container).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

NEWLINE_LF = "LF"
NEWLINE_CRLF = "CRLF"
NEWLINE_MIXED = "MIXED"
NEWLINE_OTHER = "OTHER"

_CRLF_OR_CR = re.compile(rb"\r\n|\r")


# ---------------------------------------------------------------------------
# newline classification (artifact side, raw bytes)
# ---------------------------------------------------------------------------

def newline_convention(data: bytes) -> str:
    """LF / CRLF / MIXED / OTHER of raw bytes.

    LF    only "\\n" terminators
    CRLF  only "\\r\\n" terminators
    MIXED both kinds present
    OTHER no newline at all, or a lone "\\r" outside a "\\r\\n" pair
    """
    crlf = data.count(b"\r\n")
    lf_total = data.count(b"\n")
    cr_total = data.count(b"\r")
    lone_lf = lf_total - crlf
    lone_cr = cr_total - crlf
    if lone_cr:
        return NEWLINE_OTHER
    if crlf and lone_lf:
        return NEWLINE_MIXED
    if crlf:
        return NEWLINE_CRLF
    if lone_lf:
        return NEWLINE_LF
    return NEWLINE_OTHER


def has_trailing_newline(data: bytes) -> bool:
    return data.endswith(b"\n")


# ---------------------------------------------------------------------------
# condition hashes (method side, LF-normalized)
# ---------------------------------------------------------------------------

def lf_normalize(data: bytes) -> bytes:
    """CRLF -> LF, lone CR -> LF. The documented CONDITION-hash rule."""
    return _CRLF_OR_CR.sub(b"\n", data)


def lf_normalized_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(lf_normalize(data)).hexdigest()


def lf_normalized_sha256(path: Path) -> Optional[str]:
    """LF-normalized SHA-256 of a file; None if it does not exist."""
    path = Path(path)
    if not path.is_file():
        return None
    return lf_normalized_sha256_bytes(path.read_bytes())


def lf_normalized_source_sha256(obj: Any) -> str:
    """LF-normalized SHA-256 of a Python object's source (function/class),
    for conditions that pin ONE implementation rather than a whole file."""
    source = inspect.getsource(obj)
    return lf_normalized_sha256_bytes(source.encode("utf-8"))


def repo_relative(path: Path) -> str:
    """Logical, checkout-independent identity of a repository file."""
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


# ---------------------------------------------------------------------------
# artifact hashes (raw bytes)
# ---------------------------------------------------------------------------

def raw_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_sha256(path: Path) -> Optional[str]:
    """RAW-byte SHA-256 of an artifact; None if it does not exist. Never
    normalized: this is the identity of what a compiler actually reads."""
    path = Path(path)
    if not path.is_file():
        return None
    return raw_sha256_bytes(path.read_bytes())


def utf8_sha256(text: str) -> str:
    """SHA-256 of the exact UTF-8 encoding of a string (no BOM, no newline
    translation) - the artifact-hash rule for in-memory string inputs."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# canonical object hashing (shared by every new condition)
# ---------------------------------------------------------------------------

def canonical_sha256(obj: Any) -> str:
    """sort_keys, compact separators, ensure_ascii, default=str - the same
    rule static_provenance.canonical_sha256 uses, so every condition in the
    repository is addressed the same way."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                   default=str).encode("utf-8")).hexdigest()


def file_condition_entry(path: Path) -> "OrderedDict[str, Any]":
    """One implementation file as it appears inside a condition: logical
    path + LF-normalized hash (never the raw hash, never an absolute path)."""
    return OrderedDict([
        ("path", repo_relative(path)),
        ("lf_normalized_sha256", lf_normalized_sha256(path)),
    ])
