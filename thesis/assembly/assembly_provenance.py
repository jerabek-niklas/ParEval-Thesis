"""Assembly integrity and provenance (pilot_002 pre-run wave).

The candidate-code chain is

    provider/model output  ->  generation record output.raw_text
                           ->  [generation-side clean_generated_code -> output.cleaned_code,
                                informational + repair-history input]
                           ->  assembly-side clean_for_assembly(prompt_text, raw_text)
                           ->  assemble_content()  ->  generated-code.hpp
                           ->  evaluation

and this module makes every link content-addressed:

  assembly_input_sha256      the EXACT stage-2 input: the (prompt_text,
                             raw_text) pair handed to clean_for_assembly,
                             hashed over its UTF-8 representation, nothing
                             else (no provider metadata, timing, usage)
  source_sha256              RAW bytes of generated-code.hpp, re-read after
                             the write - what the compiler actually sees
  newline_convention         LF / CRLF / MIXED / OTHER of those bytes
  assembly_condition         the METHOD (LF-normalized implementation files,
                             the policy config, the schema version)
  generation_cleaning_condition
                             the generation-side cleaning implementation,
                             which was covered by no condition before
  assembly_set_sha256        per (run, model): the canonical projection of
                             every assembled sample

plus the fail-closed verifications a post-run verifier and the tests use:
record vs file (tamper), missing source, orphan source, duplicate sample_id.

Legacy pilot_001 assembly records (assembly.v1) carry none of these fields
and are NEVER rewritten; they are classified LEGACY_UNPINNED_ASSEMBLY.

Python 3.8 compatible.
"""
from __future__ import annotations

import inspect
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

from thesis.evaluation import condition_hashing as ch  # noqa: E402

ASSEMBLY_CONDITION_VERSION = "assembly_condition.v1"
GENERATION_CLEANING_CONDITION_VERSION = "generation_cleaning_condition.v1"
ASSEMBLY_SET_VERSION = "assembly_set.v1"
LEGACY_ASSEMBLY_CLASS = "LEGACY_UNPINNED_ASSEMBLY"

# What exactly assembly_input_sha256 covers. Stated once, hashed into the
# condition, so a later redefinition is a condition change.
ASSEMBLY_INPUT_DEFINITION = (
    "sha256 over the canonical JSON object {\"prompt_text\": <prompt_text>, "
    "\"raw_text\": <raw_text>, \"generation_truncated\": <bool>} (sort_keys, "
    "compact separators, ensure_ascii) encoded as UTF-8: exactly the two "
    "arguments handed to cleaning.clean_for_assembly(prompt_text, raw_text) "
    "plus the one further record-borne value that determines the assembled "
    "bytes (status.truncated gates the single-brace auto-close). Strings are "
    "taken exactly as json.loads returns them from the generation record (no "
    "strip, no newline translation); provider output that is not part of "
    "raw_text (usage, timing, response ids, finish reason) is excluded."
)

SOURCE_FILE_NAME = "generated-code.hpp"

CLEANING_PY = REPO_ROOT / "thesis" / "assembly" / "cleaning.py"
ASSEMBLE_PY = REPO_ROOT / "thesis" / "assembly" / "assemble_sources.py"


class AssemblyIntegrityError(RuntimeError):
    """Fail-closed refusal: duplicate sample id, tampered or missing source,
    or a drifted assembly set under one run."""


# ---------------------------------------------------------------------------
# conditions (METHOD, LF-normalized)
# ---------------------------------------------------------------------------

# Provider text extraction: the FIRST byte-changing step of the chain
# (provider response object -> output.raw_text). The adapter files are
# scripts with hyphenated names (not importable), so their extraction
# functions are pinned by AST-located, LF-normalized source segments.
PROVIDER_EXTRACTION_FUNCTIONS = OrderedDict([
    ("thesis/generation/generate-anthropic.py", ["_extract_text"]),
    ("thesis/generation/generate-openai.py", ["_extract_text"]),
    ("thesis/generation/generate-gemini.py", ["_extract_text"]),
    ("thesis/generation/generate-openai-compatible.py", ["_extract_text"]),
    ("thesis/generation/batch_api.py",
     ["_anthropic_extract_text", "_openai_body_response", "_gemini_extract_text"]),
])


def function_source_segments(path: Path, names: "List[str]") -> "OrderedDict[str, Optional[str]]":
    """LF-normalized source of the named function definitions (nested ones
    included) in a Python file; None when a name is not defined there."""
    import ast

    text = Path(path).read_bytes()
    normalized = ch.lf_normalize(text).decode("utf-8")
    tree = ast.parse(normalized)
    found = OrderedDict((name, None) for name in names)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in found:
            segment = ast.get_source_segment(normalized, node)
            if found[node.name] is None:
                found[node.name] = segment
    return found


def provider_extraction_condition() -> "OrderedDict[str, Any]":
    entries = OrderedDict()
    for rel_path, names in PROVIDER_EXTRACTION_FUNCTIONS.items():
        segments = function_source_segments(REPO_ROOT / rel_path, names)
        for name, segment in segments.items():
            key = "%s::%s" % (rel_path, name)
            entries[key] = (ch.lf_normalized_sha256_bytes(segment.encode("utf-8"))
                            if segment is not None else None)
    return entries


def generation_cleaning_condition() -> "OrderedDict[str, Any]":
    """The generation-side transformations between the provider response and
    the generation record:

      provider response -> output.raw_text   (adapter _extract_text and the
                                              batch extraction helpers)
      output.raw_text   -> output.cleaned_code (common.clean_generated_code
                                              -> cleaning.extract_code)

    cleaned_code is not the assembly input (the repair history is built from
    the ASSEMBLED generated-code.hpp, not from cleaned_code); it is the
    validator's view of the answer - still a byte-changing candidate-code
    transformation with a persisted output, so it is covered by a
    condition. Every hash here is LF-normalized (checkout-independent)."""
    from thesis.assembly import cleaning
    from thesis.generation import common

    condition = OrderedDict()
    condition["condition_version"] = GENERATION_CLEANING_CONDITION_VERSION
    condition["provider_extraction"] = provider_extraction_condition()
    condition["implementation"] = OrderedDict([
        ("common.clean_generated_code",
         ch.lf_normalized_source_sha256(common.clean_generated_code)),
        ("cleaning.extract_code", ch.lf_normalized_source_sha256(cleaning.extract_code)),
        ("cleaning.is_prose_line", ch.lf_normalized_source_sha256(cleaning.is_prose_line)),
        ("cleaning.FENCE_PATTERN", cleaning.FENCE_PATTERN.pattern),
        ("cleaning.CODE_LINE_PATTERN", cleaning.CODE_LINE_PATTERN.pattern),
    ])
    condition["output_field"] = "generation record output.cleaned_code"
    condition["consumers"] = ["validate_generations (informational field; never the assembly input)"]
    return condition


def generation_cleaning_condition_sha256(condition: "Dict[str, Any]") -> str:
    return ch.canonical_sha256(condition)


def assembly_condition(config: "Optional[Dict[str, Any]]") -> "OrderedDict[str, Any]":
    """The assembly METHOD. Content-addressed; independent of git HEAD,
    timestamps, hostnames, the output root and - by LF normalization - of
    the checkout's line-ending style."""
    from thesis.assembly import assemble_sources

    stage = ((config or {}).get("stages") or {}).get("assembly") or {}
    condition = OrderedDict()
    condition["condition_version"] = ASSEMBLY_CONDITION_VERSION
    condition["assembly_schema_version"] = assemble_sources.ASSEMBLY_SCHEMA_VERSION
    condition["implementation"] = [
        ch.file_condition_entry(CLEANING_PY),
        ch.file_condition_entry(ASSEMBLE_PY),
        ch.file_condition_entry(Path(__file__)),
    ]
    condition["generation_cleaning_condition_sha256"] = generation_cleaning_condition_sha256(
        generation_cleaning_condition())
    condition["policy"] = OrderedDict([
        # the only config key that changes generated-code.hpp bytes
        ("auto_close_single_brace", bool(stage.get("auto_close_single_brace", True))),
    ])
    condition["assembly_input_definition"] = ASSEMBLY_INPUT_DEFINITION
    condition["source_writer"] = OrderedDict([
        ("encoding", "utf-8"),
        # a statement about the CODE (text-mode write_text, newline=None),
        # deliberately not about this host: os.linesep is never hashed
        ("newline_policy", assemble_sources.ASSEMBLY_WRITER_NEWLINE_POLICY),
    ])
    return condition


def assembly_condition_sha256(condition: "Dict[str, Any]") -> str:
    return ch.canonical_sha256(condition)


# ---------------------------------------------------------------------------
# per-sample artifact facts (ARTIFACT, raw bytes)
# ---------------------------------------------------------------------------

def assembly_input_sha256(prompt_text: str, raw_text: str,
                          generation_truncated: bool = False) -> str:
    """See ASSEMBLY_INPUT_DEFINITION."""
    payload = json.dumps({"prompt_text": prompt_text, "raw_text": raw_text,
                          "generation_truncated": bool(generation_truncated)},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return ch.utf8_sha256(payload)


def assembly_input_sha256_of_record(record: "Dict[str, Any]") -> str:
    return assembly_input_sha256(
        record["prompt"]["prompt_text"], record["output"]["raw_text"],
        bool((record.get("status") or {}).get("truncated", False)))


def source_artifact_facts(path: Path) -> "OrderedDict[str, Any]":
    """Re-read the written file and describe the REAL bytes."""
    data = Path(path).read_bytes()
    return OrderedDict([
        ("source_sha256", ch.raw_sha256_bytes(data)),
        ("newline_convention", ch.newline_convention(data)),
        ("byte_size", len(data)),
        ("trailing_newline", ch.has_trailing_newline(data)),
    ])


def logical_source_path(model_id: str, sample_id: str) -> str:
    """Run-relative identity of a source file (never an absolute or mount
    path): <model_id>/sources/<sample_id>/generated-code.hpp."""
    return "%s/sources/%s/%s" % (model_id, sample_id, SOURCE_FILE_NAME)


# ---------------------------------------------------------------------------
# per-model assembly set
# ---------------------------------------------------------------------------

def assembly_set_projection(entries: Iterable[Dict[str, Any]]) -> "List[Dict[str, Any]]":
    """Canonical, sorted projection of the ASSEMBLED entries of one model."""
    rows = []
    for entry in entries:
        if not entry.get("assembled"):
            continue
        rows.append(OrderedDict([
            ("sample_id", entry.get("sample_id")),
            ("execution_model", entry.get("execution_model")),
            ("benchmark", entry.get("benchmark")),
            ("logical_source_path", entry.get("logical_source_path")),
            ("source_sha256", entry.get("source_sha256")),
        ]))
    rows.sort(key=lambda r: (str(r["sample_id"]), str(r["logical_source_path"])))
    return rows


def assembly_set_sha256(entries: Iterable[Dict[str, Any]]) -> str:
    return ch.canonical_sha256({
        "set_version": ASSEMBLY_SET_VERSION,
        "rows": assembly_set_projection(entries),
    })


def assembly_set_summary(model_id: str, entries: "List[Dict[str, Any]]",
                         counts: "Dict[str, int]") -> "OrderedDict[str, Any]":
    return OrderedDict([
        ("set_version", ASSEMBLY_SET_VERSION),
        ("model_id", model_id),
        ("sample_count", sum(1 for e in entries if e.get("assembled"))),
        ("assembly_set_sha256", assembly_set_sha256(entries)),
        ("counts", OrderedDict(sorted(counts.items()))),
    ])


# ---------------------------------------------------------------------------
# verification (records vs files), used by tests and the post-run verifier
# ---------------------------------------------------------------------------

def is_legacy_entry(entry: "Dict[str, Any]") -> bool:
    return entry.get("assembled") is True and not entry.get("source_sha256")


def load_assembly_entries(path: Path) -> "List[Dict[str, Any]]":
    if not Path(path).is_file():
        return []
    with Path(path).open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def verify_assembly(model_dir: Path, entries: "Optional[List[Dict[str, Any]]]" = None,
                    expected_sample_ids: "Optional[Iterable[str]]" = None
                    ) -> "OrderedDict[str, Any]":
    """Fail-closed integrity view of one model's assembly under a run dir:

      duplicates   the same sample_id recorded twice (never last-writer-wins)
      missing      assembled record whose source file does not exist
      tampered     source file bytes != recorded source_sha256
      orphans      source file without an ASSEMBLED record (a crash between
                   source write and record write, a stale file, or a sample
                   that no longer assembles)
      legacy       assembled records without a pinned source hash
      not_expected / not_recorded  against an optional expected id set

    Never modifies anything.
    """
    model_dir = Path(model_dir)
    if entries is None:
        entries = load_assembly_entries(model_dir / "assembly.jsonl")

    seen = set()
    duplicates = []
    missing = []
    tampered = []
    legacy = []
    assembled_ids = set()

    for entry in entries:
        sample_id = entry.get("sample_id")
        if sample_id in seen:
            duplicates.append(sample_id)
        seen.add(sample_id)
        if not entry.get("assembled"):
            continue
        assembled_ids.add(sample_id)
        source = model_dir / "sources" / str(sample_id) / SOURCE_FILE_NAME
        if not source.is_file():
            missing.append(sample_id)
            continue
        recorded = entry.get("source_sha256")
        if not recorded:
            legacy.append(sample_id)
            continue
        actual = ch.raw_sha256(source)
        if actual != recorded:
            tampered.append(OrderedDict([("sample_id", sample_id),
                                         ("recorded", recorded), ("actual", actual)]))

    orphans = []
    sources_dir = model_dir / "sources"
    if sources_dir.is_dir():
        for candidate in sorted(sources_dir.iterdir()):
            if (candidate / SOURCE_FILE_NAME).is_file() and candidate.name not in assembled_ids:
                orphans.append(candidate.name)

    not_expected = []
    not_recorded = []
    if expected_sample_ids is not None:
        expected = set(expected_sample_ids)
        not_expected = sorted(seen - expected)
        not_recorded = sorted(expected - seen)

    problems = []
    if duplicates:
        problems.append("duplicate sample ids: %s" % ", ".join(sorted(set(duplicates))))
    if missing:
        problems.append("assembled records without a source file: %s" % ", ".join(missing))
    if tampered:
        problems.append("source bytes differ from the recorded source_sha256: %s"
                        % ", ".join(t["sample_id"] for t in tampered))
    if orphans:
        problems.append("source files without an assembled record (orphans): %s"
                        % ", ".join(orphans))
    if not_expected:
        problems.append("records for samples outside the expected population: %s"
                        % ", ".join(not_expected))
    if not_recorded:
        problems.append("expected samples without any assembly record: %s"
                        % ", ".join(not_recorded))

    if problems:
        status = "FAIL"
    elif legacy:
        status = LEGACY_ASSEMBLY_CLASS
    else:
        status = "PASS"

    return OrderedDict([
        ("status", status),
        ("records", len(entries)),
        ("assembled", len(assembled_ids)),
        ("skipped", sum(1 for e in entries if not e.get("assembled"))),
        ("duplicates", sorted(set(duplicates))),
        ("missing_sources", missing),
        ("tampered_sources", tampered),
        ("orphan_sources", orphans),
        ("legacy_unpinned", legacy),
        ("not_expected", not_expected),
        ("not_recorded", not_recorded),
        ("problems", problems),
    ])


def classify_legacy_run(entries: "List[Dict[str, Any]]") -> str:
    """LEGACY_UNPINNED_ASSEMBLY when at least one assembled record carries no
    source hash (pilot_001), PINNED when all do, EMPTY otherwise."""
    assembled = [e for e in entries if e.get("assembled")]
    if not assembled:
        return "EMPTY"
    if any(not e.get("source_sha256") for e in assembled):
        return LEGACY_ASSEMBLY_CLASS
    return "PINNED"


def implementation_source(obj: Any) -> str:
    """Helper for tests: the LF-normalized source text of an implementation."""
    return inspect.getsource(obj).replace("\r\n", "\n").replace("\r", "\n")
