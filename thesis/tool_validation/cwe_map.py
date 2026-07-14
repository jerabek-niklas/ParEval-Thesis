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
