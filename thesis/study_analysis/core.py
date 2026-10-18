"""Shared core of the study analysis: identities, the frozen methodology,
the normalized table schemas, deterministic writers and small helpers.

Every other module of the package builds on these schemas: normalize.py
fills them from the authorized readers, metrics.py/stats.py compute the
methodology's metrics from them, tables.py/figures.py render the results,
validate.py checks them. Nothing here reads results or writes into the
repository.

Python 3.8 compatible syntax (the main container runs 3.12).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.condition_hashing import canonical_sha256  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402

# -- identities ---------------------------------------------------------------------

ANALYSIS_ID = "study_analysis_001"
METHODOLOGY_SCHEMA = "study_analysis_methodology.v1"
METHODOLOGY_REL = "thesis/study_analysis/methodology.json"
ADDENDUM_SCHEMA = "study_analysis_methodology_addendum.v1"
ADDENDUM_REL = "thesis/study_analysis/methodology_addendum.json"
ADDENDUM_STATUS = "DECLARED_AFTER_DRY_RUN"
RESULTS_SCHEMA = "study_analysis_results.v1"
MANIFEST_SCHEMA = "study_analysis_manifest.v1"
VALIDATION_SCHEMA = "study_analysis_validation.v1"
DATASET_SCHEMA = "study_analysis_dataset.v1"
OUTPUT_REL = "thesis/results/analysis/" + ANALYSIS_ID
PACKAGE_REL = "thesis/study_analysis"
CLOSURE_REL = "thesis/evaluation/closure/study_closure_001/global_verification.json"
ACCEPTANCE_REL = "thesis/evaluation/pilot_002_result_acceptance.json"
EXPECTED_COMPOSITE_SHA256 = "953ce41b7f050559b1af875139c626995c562c43cba2fc632096c22d45e3e2b0"

PILOT = pl.PILOT                  # pilot_002
PARENT = pl.PARENT                # full_ext_001
OWNERS = pl.OWNERS                # full_ext_recovery_001..004
PHASE2 = pl.SUCCESSOR             # full_ext_phase2_001
RUNS = (PILOT, PARENT) + OWNERS + (PHASE2,)
MODELS = pl.MODELS
VARIANTS = pl.VARIANTS
MAX_ITERATIONS = pl.MAX_ITERATIONS
EXCLUDED_RUNS = pl.EXCLUDED_HISTORICAL_RUNS
EXECUTION_MODELS = ("serial", "omp", "mpi")
BLOCKS = ("pilot", "full_ext")
COMPOSITE = "composite"
BLOCK_BASE_RUN = OrderedDict([("pilot", PILOT), ("full_ext", PARENT)])
BL01_BENCHMARK = "dense_la/00_dense_la_lu_decomp"

STATIC_TOOLS = ("compiler", "gcc_analyzer", "clang_tidy", "cppcheck", "infer", "parcoach", "llov")
STATIC_ANALYSIS_TOOLS = STATIC_TOOLS[1:]          # the compiler is a build precondition
DYNAMIC_TOOLS = ("asan_ubsan", "tsan", "memcheck", "must")
TOOL_STATES = ("COMPLETED", "PARTIAL", "TIMEOUT", "TOOL_ERROR", "NOT_ANALYZED", "NOT_APPLICABLE",
               "ABSENT_INAPPLICABLE")
GAP_STATES = ("PARTIAL", "TIMEOUT", "TOOL_ERROR", "NOT_ANALYZED")
INAPPLICABLE_STATES = ("NOT_APPLICABLE", "ABSENT_INAPPLICABLE")
CORRECTNESS_VERDICTS = ("pass", "build_failed", "validation_failed", "runtime_error", "timeout",
                        "baseline_incompatible")
CORRECTNESS_EXCLUDED = ("baseline_incompatible",)
ENHANCED_STATUSES = ("pass", "fail", "build_failed", "crash", "timeout", "runtime_error",
                     "baseline_incompatible", "numerically_unstable")
ENHANCED_GATED = ("baseline_incompatible", "numerically_unstable")
TERMINAL_STATUSES = ("stopped_clean", "stopped_tests_pass", "stopped_budget", "stopped_analysis_incomplete",
                     "repair_unusable", "stopped_baseline_incompatible", "stopped_api_exhausted")
NON_MODEL_TERMINAL = ("stopped_baseline_incompatible", "stopped_analysis_incomplete", "stopped_api_exhausted")
THREE_STATE = ("DIRTY", "CLEAN_COMPLETE", "NO_FINDING_INCOMPLETE")
CLEANING_FLAGS = ("used_fence", "dropped_leading_lines", "dropped_trailing_lines",
                  "dropped_duplicated_prompt_lines", "relocated_includes", "auto_closed",
                  "signature_suspect", "braces_unbalanced")
RUNTIME_OUTLIER_SECONDS = 3600
EXAMPLES = 10

# -- normalized table schemas ------------------------------------------------------------
# Types: str, int, bool, float, json (a JSON-encoded value), opt_int / opt_float (empty = null).
# Booleans are written as 1/0 in CSV. Column order is the CSV column order.

def _schema(*columns):
    return OrderedDict(columns)


SCHEMAS = OrderedDict([
    ("base_cells", _schema(
        ("cell_id", "str"), ("block", "str"), ("model_id", "str"), ("benchmark", "str"), ("family", "str"),
        ("execution_model", "str"), ("sample_id", "str"), ("base_run", "str"), ("source_sha256", "str"),
        ("bl01", "bool"))),
    ("artifacts", _schema(
        ("artifact_id", "str"), ("cell_id", "str"), ("block", "str"), ("model_id", "str"), ("benchmark", "str"),
        ("family", "str"), ("execution_model", "str"), ("sample_id", "str"), ("variant", "str"),
        ("iteration", "int"), ("source_run", "str"), ("loop_owner", "str"), ("source_sha256", "str"),
        ("generation_success", "bool"), ("assembled", "bool"), ("generation_truncated", "bool"),
        ("clean_used_fence", "bool"), ("clean_dropped_leading_lines", "bool"),
        ("clean_dropped_trailing_lines", "bool"), ("clean_dropped_duplicated_prompt_lines", "bool"),
        ("clean_relocated_includes", "bool"), ("clean_auto_closed", "bool"), ("clean_signature_suspect", "bool"),
        ("clean_braces_unbalanced", "bool"), ("clean_any", "bool"), ("clean_any_including_fence", "bool"),
        ("build_ok", "bool"), ("correctness_verdict", "str"), ("correctness_owner", "str"),
        ("static_owner", "str"), ("static_supplemented_by", "json"), ("dynamic_owner", "str"),
        ("enhanced_owner", "str"),
        ("static_three_state", "str"), ("dynamic_three_state", "str"), ("compile_error", "bool"),
        ("low_confidence_any", "bool"), ("static_analysis_complete", "bool"), ("dynamic_analysis_complete", "bool"),
        ("enh_pairs", "int"), ("enh_valid", "int"), ("enh_gated", "int"), ("enh_pass", "int"), ("enh_fail", "int"),
        ("enh_build_failed", "int"), ("enh_crash", "int"), ("enh_timeout", "int"), ("enh_runtime_error", "int"),
        ("enh_all_pass", "opt_int"))),
    ("tool_entries", _schema(
        ("artifact_id", "str"), ("stage", "str"), ("tool", "str"), ("applicable", "bool"), ("state", "str"),
        ("ran", "bool"), ("duration_seconds", "opt_float"), ("num_findings", "int"), ("num_reported_blocking", "int"),
        ("num_low_confidence", "int"), ("num_non_blocking", "int"), ("owner", "str"))),
    ("findings", _schema(
        ("artifact_id", "str"), ("stage", "str"), ("tool", "str"), ("check_id", "str"), ("family", "str"),
        ("severity", "str"), ("kind", "str"), ("line", "opt_int"))),
    ("enhanced_pairs", _schema(
        ("artifact_id", "str"), ("spec_key", "str"), ("size", "opt_int"), ("pattern", "str"), ("spec_source", "str"),
        ("status", "str"), ("gated", "bool"), ("duration_seconds", "opt_float"))),
    ("trajectories", _schema(
        ("trajectory_id", "str"), ("cell_id", "str"), ("block", "str"), ("model_id", "str"), ("variant", "str"),
        ("loop_owner", "str"), ("loop_kind", "str"), ("final_iteration", "int"), ("terminal_status", "str"),
        ("stop_reason", "str"), ("status_iter0", "str"), ("status_iter1", "str"), ("status_iter2", "str"),
        ("test_verdict_final", "str"), ("artifact_iter0", "str"), ("artifact_iter1", "str"), ("artifact_iter2", "str"),
        ("final_artifact", "str"), ("request_rounds", "int"))),
    ("generations", _schema(
        ("artifact_id", "str"), ("kind", "str"), ("provider", "str"), ("success", "bool"), ("timing_mode", "str"),
        ("duration_seconds", "opt_float"), ("input_tokens", "opt_int"), ("output_tokens", "opt_int"),
        ("reasoning_tokens", "opt_int"), ("request_chars", "opt_int"), ("finish_reason", "str"))),
])
# finding kinds (findings.kind)
FINDING_KINDS = ("reported_blocking", "low_confidence", "non_blocking")


def artifact_id(block, model, source_run, sample_id):
    return "%s|%s|%s|%s" % (block, model, source_run, sample_id)


def cell_id(block, model, sample_id):
    return "%s|%s|%s" % (block, model, sample_id)


def trajectory_id(cell, variant):
    return "%s|%s" % (cell, variant)


def family_of(benchmark):
    return benchmark.split("/", 1)[0]


class AnalysisRefused(RecoveryRefused):
    """The analysis cannot proceed (integrity, ownership or definition problem)."""


# -- methodology ------------------------------------------------------------------------------

def load_methodology(root=REPO_ROOT, relative=METHODOLOGY_REL):
    path = checked_path(Path(root).resolve(), relative)
    data = path.read_bytes()
    document = json.loads(data.decode("utf-8"), object_pairs_hook=OrderedDict)
    if document.get("schema_version") != METHODOLOGY_SCHEMA or document.get("methodology_id") != ANALYSIS_ID:
        raise AnalysisRefused("not the %s methodology of %s" % (METHODOLOGY_SCHEMA, ANALYSIS_ID))
    if document.get("status") != "FROZEN_BEFORE_AGGREGATION":
        raise AnalysisRefused("the methodology is not frozen")
    ids = [m["id"] for m in document.get("metrics") or []]
    if len(ids) != len(set(ids)) or not ids:
        raise AnalysisRefused("methodology metric ids are empty or not unique")
    return document


def methodology_identity(root=REPO_ROOT):
    path = checked_path(Path(root).resolve(), METHODOLOGY_REL)
    data = path.read_bytes()
    document = load_methodology(root)
    return OrderedDict([("relative", METHODOLOGY_REL), ("raw_sha256", hashlib.sha256(data).hexdigest()),
                        ("lf_sha256", hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()),
                        ("canonical_sha256", canonical_sha256(document))])


def metric_ids(methodology):
    return [m["id"] for m in methodology["metrics"]]


def load_addendum(root=REPO_ROOT, relative=ADDENDUM_REL, methodology=None):
    """The post-freeze methodology addendum, bound to the frozen methodology
    by its canonical sha256 (an addendum for another methodology refuses).
    Its metric ids must not collide with the frozen ones."""
    path = checked_path(Path(root).resolve(), relative)
    document = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=OrderedDict)
    if document.get("schema_version") != ADDENDUM_SCHEMA or document.get("status") != ADDENDUM_STATUS:
        raise AnalysisRefused("not a %s addendum with status %s" % (ADDENDUM_SCHEMA, ADDENDUM_STATUS))
    methodology = methodology if methodology is not None else load_methodology(root)
    if (document.get("amends") or {}).get("methodology_canonical_sha256") != canonical_sha256(methodology):
        raise AnalysisRefused("the addendum amends another methodology than the frozen one")
    ids = [m["id"] for m in document.get("metrics") or []]
    if len(ids) != len(set(ids)) or set(ids) & set(metric_ids(methodology)):
        raise AnalysisRefused("addendum metric ids are not unique or collide with frozen ids")
    return document


def addendum_identity(root=REPO_ROOT):
    path = checked_path(Path(root).resolve(), ADDENDUM_REL)
    data = path.read_bytes()
    document = load_addendum(root)
    return OrderedDict([("relative", ADDENDUM_REL), ("raw_sha256", hashlib.sha256(data).hexdigest()),
                        ("lf_sha256", hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()),
                        ("canonical_sha256", canonical_sha256(document)), ("status", document["status"])])


def addendum_metric_ids(addendum):
    return [m["id"] for m in addendum["metrics"]]


def all_metric_ids(methodology, addendum):
    """Frozen metric ids followed by the post-freeze addendum ids."""
    return metric_ids(methodology) + addendum_metric_ids(addendum)


def statistics_settings(methodology):
    return methodology["statistics"]


# -- deterministic serialisation -------------------------------------------------------------------

def _cell(value, kind):
    if kind == "bool":
        if value is None:
            raise AnalysisRefused("null boolean")
        return "1" if value else "0"
    if kind in ("opt_int", "opt_float"):
        return "" if value is None else (str(int(value)) if kind == "opt_int" else repr(float(value)))
    if kind == "int":
        return str(int(value))
    if kind == "float":
        return repr(float(value))
    if kind == "json":
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "" if value is None else str(value)


def table_csv_bytes(name, rows):
    """CSV bytes of a normalized table in its schema column order (LF)."""
    schema = SCHEMAS[name]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(schema))
    for row in rows:
        missing = [c for c in schema if c not in row]
        if missing:
            raise AnalysisRefused("%s row lacks %s" % (name, missing[:5]))
        writer.writerow([_cell(row[c], k) for c, k in schema.items()])
    return buffer.getvalue().encode("utf-8")


def gzip_bytes(data):
    """Deterministic gzip (mtime 0, no file name)."""
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0, compresslevel=9) as handle:
        handle.write(data)
    return out.getvalue()


def json_bytes(document):
    return (json.dumps(document, indent=2, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def json_stable(value):
    return json.loads(json.dumps(value, default=str), object_pairs_hook=OrderedDict)


def self_hash(document, field):
    body = OrderedDict((k, v) for k, v in document.items() if k not in ("volatile", field))
    return canonical_sha256(body)


def write_bytes(path, data):
    """Atomic write of bytes (temp file in the same directory + replace)."""
    from thesis.evaluation import atomic_io

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_io.atomic_write_bytes(path, data)
    return path


def utc_now():
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def git_state(root=REPO_ROOT):
    import subprocess

    root = Path(root).resolve()
    git = ["git", "-c", "safe.directory=" + root.as_posix(), "-C", str(root)]
    head = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    branch = subprocess.check_output(git + ["rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
    status = subprocess.check_output(git + ["status", "--porcelain", "--untracked-files=all"], text=True)
    paths = sorted(line[3:].strip() for line in status.splitlines() if line.strip())
    return OrderedDict([("head", head), ("branch", branch), ("clean", not paths),
                        ("uncommitted_paths", paths[:50]), ("uncommitted_count", len(paths))])


def package_sources(root=REPO_ROOT):
    """LF sha256 of every module and data file of the package (code pins)."""
    root = Path(root).resolve()
    pins = OrderedDict()
    for path in sorted((root / PACKAGE_REL).iterdir()):
        if path.is_file() and path.suffix in (".py", ".json", ".md"):
            data = path.read_bytes().replace(b"\r\n", b"\n")
            pins[path.relative_to(root).as_posix()] = hashlib.sha256(data).hexdigest()
    return pins


# -- dataset container -----------------------------------------------------------------------------

class Dataset:
    """The normalized tables (name -> list of row OrderedDicts) plus the
    identities of the inputs they were read from. Indexes are built lazily."""

    def __init__(self, tables, provenance=None):
        unknown = [name for name in tables if name not in SCHEMAS]
        if unknown:
            raise AnalysisRefused("unknown normalized table(s): %s" % unknown)
        self.tables = OrderedDict((name, list(tables.get(name) or [])) for name in SCHEMAS)
        self.provenance = OrderedDict(provenance or {})
        self._index = {}

    def rows(self, name):
        return self.tables[name]

    def by(self, name, key):
        """Unique index name.key -> row (a duplicate refuses)."""
        cache_key = (name, key)
        if cache_key not in self._index:
            index = OrderedDict()
            for row in self.tables[name]:
                if row[key] in index:
                    raise AnalysisRefused("duplicate %s.%s %r" % (name, key, row[key]))
                index[row[key]] = row
            self._index[cache_key] = index
        return self._index[cache_key]

    def group(self, name, key):
        """name.key -> [rows] (non-unique)."""
        cache_key = (name, key, "group")
        if cache_key not in self._index:
            index = OrderedDict()
            for row in self.tables[name]:
                index.setdefault(row[key], []).append(row)
            self._index[cache_key] = index
        return self._index[cache_key]

    def counts(self):
        return OrderedDict((name, len(rows)) for name, rows in self.tables.items())


def provider_isolation(config=None):
    """Apply the phase-2 provider isolation (no .env import, scrubbed keys)."""
    pl.isolate_providers()
    if config is not None:
        pl.scrub_provider_environment(config)
    return True


def load_config(root=REPO_ROOT):
    """The phase-2 config (the composite view's config) under provider isolation."""
    from thesis.config.load_config import load_config as _load

    provider_isolation()
    config = _load(str((Path(root).resolve() / pl.CONFIG_REL).resolve()))
    pl.scrub_provider_environment(config)
    return config
