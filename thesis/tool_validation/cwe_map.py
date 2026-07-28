"""Bug<->finding matching rules for the validation scorer.

Juliet: a finding counts as a true positive ONLY if its check_id belongs to
the CWE class of the testcase (class matching, not "any finding") — otherwise
unrelated noise would count as detection. The mapping is deliberately
conservative and prefix-based; empty sets are honest zeros (the tool, as
configured in the pipeline, has no checker for that class).

DataRaceBench / MBI: file-level matching (the label applies to the whole
kernel), restricted to the tool's relevant finding families so that style
noise does not count as detection.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

# ---------------------------------------------------------------------------
# Juliet: CWE -> tool -> check_id prefixes
# ---------------------------------------------------------------------------

_BUFFER_COMPILER = ("-Warray-bounds", "-Wstringop-overflow", "-Wstringop-overread")

# Runtime ids (asan_ubsan / memcheck on EXECUTED Juliet testcases; see the
# dynamic-semantics footnote in summary.md — recall not directly comparable
# to static tools). Conservative:
#   - ASan buffer ids cover heap/stack/global variants; wild OOB often
#     surfaces as SEGV.
#   - Memcheck does NOT track stack redzones -> honest zeros for pure
#     stack overflows (CWE121); heap accesses appear as InvalidRead/Write.
#   - Uninitialized (CWE457) is MSan's domain, not ASan/UBSan -> honest
#     zero for asan_ubsan; Memcheck covers it (UninitValue/UninitCondition).
#   - Integer overflow (CWE190/191) is exactly UBSan's runtime check.
_BUFFER_ASAN = (
    "asan-heap-buffer-overflow",
    "asan-stack-buffer-overflow",
    "asan-stack-buffer-underflow",
    "asan-global-buffer-overflow",
    "asan-segv",
)
_HEAP_MEMCHECK = ("memcheck-invalid-read", "memcheck-invalid-write")
_BUFFER_CPPCHECK = (
    "arrayIndexOutOfBounds",
    "bufferAccessOutOfBounds",
    "outOfBounds",
    "negativeIndex",
    "objectIndex",
)
_BUFFER_INFER = ("BUFFER_OVERRUN",)  # requires inferbo; honest zero otherwise

JULIET_MATCHERS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "CWE121": {
        "compiler": _BUFFER_COMPILER,
        "clang_tidy": (),
        "cppcheck": _BUFFER_CPPCHECK,
        "infer": _BUFFER_INFER,
        "asan_ubsan": _BUFFER_ASAN,
        "memcheck": (),
    },
    "CWE122": {
        "compiler": _BUFFER_COMPILER,
        # calibration note: unix.Malloc (clang SA) and memleak (cppcheck)
        # appear on CWE122 bad kernels but are most likely INCIDENTAL leak
        # reports on the testcase scaffolding, not detection of the heap
        # overflow itself — deliberately NOT mapped (conservative recall
        # beats counting noise as detection).
        "clang_tidy": (),
        "cppcheck": _BUFFER_CPPCHECK,
        "infer": _BUFFER_INFER,
        "asan_ubsan": _BUFFER_ASAN,
        "memcheck": _HEAP_MEMCHECK,
    },
    "CWE124": {
        "compiler": _BUFFER_COMPILER,
        "clang_tidy": (),
        "cppcheck": _BUFFER_CPPCHECK,
        "infer": _BUFFER_INFER,
        "asan_ubsan": _BUFFER_ASAN,
        "memcheck": ("memcheck-invalid-write",),
    },
    "CWE126": {
        "compiler": _BUFFER_COMPILER,
        "clang_tidy": (),
        "cppcheck": _BUFFER_CPPCHECK,
        "infer": _BUFFER_INFER,
        "asan_ubsan": _BUFFER_ASAN,
        "memcheck": ("memcheck-invalid-read",),
    },
    "CWE127": {
        "compiler": _BUFFER_COMPILER,
        "clang_tidy": (),
        "cppcheck": _BUFFER_CPPCHECK,
        "infer": _BUFFER_INFER,
        "asan_ubsan": _BUFFER_ASAN,
        "memcheck": ("memcheck-invalid-read",),
    },
    "CWE190": {
        "compiler": ("-Woverflow",),
        "clang_tidy": (),
        "cppcheck": ("integerOverflow",),
        "infer": ("INTEGER_OVERFLOW",),
        "asan_ubsan": ("ubsan-runtime-error",),
        "memcheck": (),
    },
    "CWE191": {
        "compiler": ("-Woverflow",),
        "clang_tidy": (),
        "cppcheck": ("integerOverflow",),
        "infer": ("INTEGER_OVERFLOW",),
        "asan_ubsan": ("ubsan-runtime-error",),
        "memcheck": (),
    },
    "CWE401": {
        "compiler": (),
        "clang_tidy": (
            "clang-analyzer-unix.Malloc",
            "clang-analyzer-cplusplus.NewDeleteLeaks",
        ),
        "cppcheck": ("memleak",),
        "infer": ("MEMORY_LEAK", "PULSE_MEMORY_LEAK"),
        "asan_ubsan": ("lsan-detected-memory-leaks",),
        "memcheck": ("memcheck-leak-definitely-lost",),
    },
    "CWE415": {
        # calibrated: gcc reports double free via -Wuse-after-free
        # ("pointer used after 'free'") — verified on CWE415 _01 kernels
        "compiler": ("-Wuse-after-free",),
        "clang_tidy": (
            "clang-analyzer-unix.Malloc",
            "clang-analyzer-cplusplus.NewDelete",
        ),
        "cppcheck": ("doubleFree",),
        "infer": ("USE_AFTER_FREE", "USE_AFTER_DELETE", "DOUBLE_FREE"),
        "asan_ubsan": ("asan-attempting-double-free",),
        "memcheck": ("memcheck-invalid-free",),
    },
    "CWE416": {
        "compiler": ("-Wuse-after-free",),
        "clang_tidy": (
            "clang-analyzer-unix.Malloc",
            "clang-analyzer-cplusplus.NewDelete",
        ),
        "cppcheck": ("deallocuse",),
        "infer": ("USE_AFTER_FREE", "USE_AFTER_DELETE", "DANGLING_POINTER"),
        "asan_ubsan": ("asan-heap-use-after-free",),
        "memcheck": _HEAP_MEMCHECK,
    },
    "CWE457": {
        "compiler": ("-Wuninitialized", "-Wmaybe-uninitialized"),
        "clang_tidy": (
            "clang-analyzer-core.uninitialized",
            "clang-analyzer-core.CallAndMessage",
        ),
        "cppcheck": ("uninit",),
        "infer": ("UNINITIALIZED_VALUE",),
        "asan_ubsan": (),
        "memcheck": ("memcheck-uninit-value", "memcheck-uninit-condition"),
    },
    "CWE476": {
        "compiler": ("-Wnull-dereference",),
        "clang_tidy": ("clang-analyzer-core.NullDereference",),
        "cppcheck": ("nullPointer",),
        "infer": ("NULL_DEREFERENCE", "NULLPTR_DEREFERENCE"),
        "asan_ubsan": ("asan-segv",),
        "memcheck": _HEAP_MEMCHECK,
    },
    "CWE590": {
        "compiler": ("-Wfree-nonheap-object",),
        # calibrated: Clang SA reports free-of-stack as a BadFree through the
        # unix.Malloc / cplusplus.NewDelete checkers — verified on CWE590 _01
        "clang_tidy": (
            "clang-analyzer-unix.MismatchedDeallocator",
            "clang-analyzer-unix.Malloc",
            "clang-analyzer-cplusplus.NewDelete",
        ),
        "cppcheck": ("autovarInvalidDeallocation", "mismatchAllocDealloc"),
        "infer": (),
        "asan_ubsan": ("asan-attempting-free",),
        "memcheck": ("memcheck-invalid-free", "memcheck-mismatched-free"),
    },
}

# ---------------------------------------------------------------------------
# DRB / MBI: tool -> relevant finding families (file-level matching)
# ---------------------------------------------------------------------------

DRB_RELEVANT: Dict[str, Tuple[str, ...]] = {
    "llov": ("llov-data-race",),
    "tsan": ("tsan-data-race",),
    "parcoach": ("parcoach-",),
    # justification measurements (not pipeline tools)
    "helgrind": ("helgrind-race",),
    "drd": ("drd-conflicting-access",),
    "tsan_noarcher": ("tsan-data-race",),
}

MBI_RELEVANT: Dict[str, Tuple[str, ...]] = {
    "clang_tidy": ("clang-analyzer-optin.mpi", "mpi-"),
    "parcoach": ("parcoach-",),
    "must": ("must-",),
}

# ---------------------------------------------------------------------------
# VARIANT tools (justification measurements, not pipeline tools):
#   compiler_fanalyzer = compiler + -fanalyzer   (GCC path-sensitive analyzer)
#   infer_bo           = infer + --bufferoverrun (InferBO abstract interpretation)
#
# Each variant INHERITS its base tool's mapping (it runs the base analysis
# too — every base finding is still produced) and adds the check_ids of the
# extra component below. Verified against gcc 13.3.0 / Infer 1.1.0 as
# installed in the pareval-thesis image (`gcc --help=warnings`, canary run):
# every prefix listed here exists in that toolchain. Warnings that do not
# exist, or whose defect class differs, are deliberately NOT mapped — the
# resulting zeros are honest.
# ---------------------------------------------------------------------------

# InferBO additions. Justification per entry — these are exactly the 7 classes
# where default Infer (Pulse/biabduction) has no checker at all and therefore
# a structural zero:
#   - BUFFER_OVERRUN* (levels L1..L5/U5/S2 are bug_type SUFFIXES, so the
#     prefix covers every confidence level) is InferBO's out-of-bounds
#     report -> the five buffer classes CWE121/122/124/126/127.
#   - INTEGER_OVERFLOW* is InferBO's arithmetic-overflow report -> CWE190
#     (overflow) and CWE191 (underflow); Infer does not distinguish the
#     direction, so both map to the same prefix.
_INFER_BO_BUFFER = ("BUFFER_OVERRUN",)
_INFER_BO_INTEGER = ("INTEGER_OVERFLOW",)

# GCC -fanalyzer additions. Justification per entry (GCC annotates its
# analyzer diagnostics with the CWE id itself — e.g. the canary emits
# "'free' of '&b' which points to memory on the stack [CWE-590]
# [-Wanalyzer-free-of-non-heap]" — so the mapping follows GCC's own labels):
#   - -Wanalyzer-out-of-bounds: the analyzer's single out-of-bounds report
#     (read and write) -> all five buffer classes.
#   - -Wanalyzer-malloc-leak (CWE-401) -> CWE401. -Wanalyzer-file-leak is
#     GCC's FILE*-leak counterpart (CWE-775); mapped alongside it because
#     Juliet CWE401 contains fopen-based leak variants, and it is an honest
#     zero on the malloc variants.
#   - -Wanalyzer-double-free (CWE-415) -> CWE415.
#   - -Wanalyzer-use-after-free (CWE-416) -> CWE416.
#   - -Wanalyzer-use-of-uninitialized-value (CWE-457) -> CWE457.
#   - -Wanalyzer-null-dereference (CWE-476) -> CWE476.
#   - -Wanalyzer-free-of-non-heap (CWE-590) -> CWE590 (verified empirically).
#   - CWE190/191: GCC's analyzer has NO integer-overflow checker (the
#     -Wanalyzer-shift-count-* warnings are a different defect) -> honest
#     zero, nothing mapped.
_FANALYZER_ADDITIONS: Dict[str, Tuple[str, ...]] = {
    "CWE121": ("-Wanalyzer-out-of-bounds",),
    "CWE122": ("-Wanalyzer-out-of-bounds",),
    "CWE124": ("-Wanalyzer-out-of-bounds",),
    "CWE126": ("-Wanalyzer-out-of-bounds",),
    "CWE127": ("-Wanalyzer-out-of-bounds",),
    "CWE401": ("-Wanalyzer-malloc-leak", "-Wanalyzer-file-leak"),
    "CWE415": ("-Wanalyzer-double-free",),
    "CWE416": ("-Wanalyzer-use-after-free",),
    "CWE457": ("-Wanalyzer-use-of-uninitialized-value",),
    "CWE476": ("-Wanalyzer-null-dereference",),
    "CWE590": ("-Wanalyzer-free-of-non-heap",),
}

_INFER_BO_ADDITIONS: Dict[str, Tuple[str, ...]] = {
    "CWE121": _INFER_BO_BUFFER,
    "CWE122": _INFER_BO_BUFFER,
    "CWE124": _INFER_BO_BUFFER,
    "CWE126": _INFER_BO_BUFFER,
    "CWE127": _INFER_BO_BUFFER,
    "CWE190": _INFER_BO_INTEGER,
    "CWE191": _INFER_BO_INTEGER,
}

for _cwe, _tools in JULIET_MATCHERS.items():
    # inherit base mapping, then add the extra component's check_ids
    _tools["compiler_fanalyzer"] = tuple(
        dict.fromkeys(_tools.get("compiler", ()) + _FANALYZER_ADDITIONS.get(_cwe, ()))
    )
    _tools["infer_bo"] = tuple(
        dict.fromkeys(_tools.get("infer", ()) + _INFER_BO_ADDITIONS.get(_cwe, ()))
    )
    # virtual sub-variant (scorer-side, no second run): InferBO restricted to
    # its two most reliable confidence levels — see score_validation.py
    _tools["infer_bo_l1l2"] = _tools["infer_bo"]


# ---------------------------------------------------------------------------
# Virtual-tool split of clang_tidy (scorer-side, see score_validation.py):
# redundancy in the thesis is defined over the detection METHOD, and
# clang-tidy bundles two of them — AST matchers ("clang_tidy_ast") and the
# Clang Static Analyzer's symbolic execution ("clang_sa",
# check_ids prefixed clang-analyzer-). The split needs no second run (same
# engine invocation); it only partitions the findings for metrics/overlap.
# ---------------------------------------------------------------------------

CLANG_SA_PREFIX = "clang-analyzer-"

for _tools in JULIET_MATCHERS.values():
    _tidy = _tools.get("clang_tidy", ())
    _tools["clang_sa"] = tuple(p for p in _tidy if p.startswith(CLANG_SA_PREFIX))
    _tools["clang_tidy_ast"] = tuple(p for p in _tidy if not p.startswith(CLANG_SA_PREFIX))

MBI_RELEVANT["clang_sa"] = ("clang-analyzer-optin.mpi",)
MBI_RELEVANT["clang_tidy_ast"] = ("mpi-",)


# Capability/status markers that are NOT defect reports and must never count
# as detection (neither TP nor FP). Justification per entry:
#   - must-unsupported: MUST announcing "feature not supported in this
#     configuration" — a capability disclaimer. Counting it as detection
#     inflated the MBI FP rate to 0.633 (468 of 484 FP kernels carried ONLY
#     this marker, concentrated in the CallOrdering family).
NON_FINDINGS = ("must-unsupported",)


# ---------------------------------------------------------------------------
# MBI STRICT matching: check_id prefix -> labeled error categories it
# IDENTIFIES (not merely co-occurs with). Grounded in (a) the empirical
# category x check_id matrix over the full run and (b) the tools' documented
# check semantics. Justification per entry:
#   - must-deadlock counts for categories whose defect MANIFESTS as deadlock
#     (mismatched/misordered calls, bad src/dest, unstarted requests): MBI's
#     own expected-outcome model treats a deadlock report as the correct
#     symptom of these root causes.
#   - must-leak-* identify the corresponding leak categories; leak-request
#     also identifies missingwait (an unwaited request IS a leaked request).
#     must-leak-comm on communicatormatching kernels is an incidental
#     secondary defect -> NOT mapped there.
#   - must-integer-* are MUST's argument-validation reports -> the
#     invalid-argument family.
#   - parcoach-collective-ordering identifies call-matching/ordering
#     defects; its firings on messagerace kernels are symptomatic hits of a
#     method that cannot identify races -> NOT mapped (strict FN).
#   - The Clang SA MPI-Checker emits ONE opaque check_id for all its
#     reports; its documented checks are request-lifecycle (missing/
#     unmatched wait, double request) -> mapped to that family only.
#   - mpi-* AST checks: literal same-call type/buffer errors (honest zeros
#     in the data, mapping kept for completeness).
# ---------------------------------------------------------------------------

_DEADLOCK_MANIFESTING = frozenset({
    "callmatching", "ihcallmatching", "callordering", "communicatormatching",
    "tagmatching", "invalidsrcdest", "bufferinghazard", "missingstart",
    "doubleepoch", "epochlifecycle",
})

_INVALID_ARG_FAMILY = frozenset({
    "invalidroot", "invalidtag", "invalidsrcdest", "invalidotherarg",
})

MBI_STRICT: Dict[str, frozenset] = {
    "must-deadlock": _DEADLOCK_MANIFESTING,
    "must-message-lost": frozenset({"callmatching", "ihcallmatching"}),
    "must-collective-call-mismatch": frozenset({"callmatching", "ihcallmatching", "doubleepoch"}),
    "must-collective-op-mismatch": frozenset({"operatormatching"}),
    "must-collective-root-mismatch": frozenset({"rootmatching"}),
    "must-typematch-mismatch": frozenset({"datatypematching"}),
    "must-leak-comm": frozenset({"communicatorleak"}),
    "must-leak-group": frozenset({"groupleak"}),
    "must-leak-op": frozenset({"operatorleak"}),
    "must-leak-datatype": frozenset({"typeleak"}),
    "must-leak-request": frozenset({"missingwait", "requestleak"}),
    "must-request-inactive": frozenset({"missingstart"}),
    "must-datatype-null": frozenset({"invaliddatatype"}),
    "must-comm-null": frozenset({"invalidcommunicator"}),
    "must-not-cart-comm": frozenset({"invalidcommunicator"}),
    "must-operation-null": frozenset({"invalidoperator"}),
    "must-integer-": _INVALID_ARG_FAMILY,        # prefix
    "must-overlapped-": frozenset({"messagerace"}),  # prefix
    "must-selfoverlapped": frozenset({"invalidbuffer"}),
    "must-win-epoch": frozenset({"missingepoch", "doubleepoch", "epochlifecycle"}),
    "parcoach-collective-ordering": frozenset({"callmatching", "ihcallmatching", "callordering"}),
    "clang-analyzer-optin.mpi": frozenset({"missingwait", "requestleak"}),
    "mpi-type-mismatch": frozenset({"datatypematching", "invaliddatatype"}),
    "mpi-buffer-deref": frozenset({"invalidbuffer"}),
}


def matches_strict(
    suite: str, classes: List[str], tool: str, findings: Iterable[dict]
) -> bool:
    """Category-aware TP: at least one finding must IDENTIFY one of the
    kernel's labeled defect categories.

    Juliet is already type-aware (CWE-class matching) and DRB has a single
    defect category (data race), so strict == lax there; only MBI labels
    carry categories that the lax file-level filter ignores.
    """
    if suite != "mbi":
        return matches(suite, classes, tool, findings)

    labeled = set(classes)

    for check_id in _check_ids(findings):
        for prefix, categories in MBI_STRICT.items():
            if check_id.startswith(prefix) and labeled & categories:
                return True

    return False


def _check_ids(findings: Iterable[dict]) -> List[str]:
    return [
        f.get("check_id", "")
        for f in findings
        if f.get("check_id", "") not in NON_FINDINGS
    ]


def matches(suite: str, classes: List[str], tool: str, findings: Iterable[dict]) -> bool:
    """Does this tool's finding list count as detecting the labeled bug
    (bad kernels) resp. as a class-relevant report (good kernels -> FP)?"""
    ids = _check_ids(findings)

    if suite == "juliet":
        prefixes: Tuple[str, ...] = ()
        for cwe in classes:
            prefixes += JULIET_MATCHERS.get(cwe, {}).get(tool, ())
        return any(cid.startswith(p) for cid in ids for p in prefixes)

    relevant = (DRB_RELEVANT if suite == "drb" else MBI_RELEVANT).get(tool, ())
    return any(cid.startswith(p) for cid in ids for p in relevant)
