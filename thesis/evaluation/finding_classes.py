"""check_id -> error-class map for the pipeline evaluation.

Modeled on the tool-validation cwe_map: PREFIX-BASED rules held as data
(first match wins, so more specific prefixes go first), conservative
assignments, and an honest "other" for everything unassigned — with one
log line per NEW unknown (tool, check_id) so the map can grow instead of
silently swallowing ids (the cwe_map's honest-zeros philosophy).

The class vocabulary is deliberately coarse — these are the classes the
thesis wants to talk about ("model X mostly produces class Y"), not a
CWE taxonomy:

    memory         overflow/OOB, use-after-free, double-free, leak,
                   invalid free
    uninitialized  uninitialized reads/values
    null_deref     null-pointer dereferences and null arguments
    arithmetic     integer overflow/underflow, div-by-zero, UB arithmetic,
                   lossy numeric conversions
    race           data races / thread-safety violations
    deadlock       lock-order inversions, blocking collectives/waits
    mpi_usage      request lifecycle, type mismatches, collective misuse,
                   buffer reuse
    api_misuse     other API-contract violations (incl. non-memory
                   resource leaks)
    build          compile errors
    other          everything unassigned (logged)

Classification is ORTHOGONAL to low_confidence: an MPI-Checker finding is
mpi_usage AND low_confidence — the class says what kind of defect is
claimed, the confidence says how much the claim is worth.

Applied READ-ONLY at overview-join time (build_overview.py derives the
class from the recorded check_id while reading); the stage JSONLs and
schemas are unchanged.

Python 3.8 compatible.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

CLASSES = (
    "memory",
    "uninitialized",
    "null_deref",
    "arithmetic",
    "race",
    "deadlock",
    "mpi_usage",
    "api_misuse",
    "build",
    "other",
)

# Per tool: ordered (check_id prefix, class) rules — FIRST match wins.
# Every line carries its justification; unlisted ids fall through to
# "other" WITH a log line (see classify_finding).
CLASS_RULES: "Dict[str, Tuple[Tuple[str, str], ...]]" = {
    # gcc/clang diagnostics. check_id is the -W flag, or "error"/"note"
    # (parse fallback), or "compile-failed" (synthetic blocking marker),
    # possibly suffixed " (in driver/benchmark)".
    "compiler": (
        ("error", "build"),               # compile error = does not build
        ("compile-failed", "build"),      # synthetic marker, same meaning
        ("-Warray-bounds", "memory"),     # OOB access proven by the FE
        ("-Wstringop-", "memory"),        # stringop overflow/overread family
        ("-Wdangling-pointer", "memory"),
        ("-Wfree-nonheap-object", "memory"),
        ("-Wreturn-local-addr", "memory"),
        ("-Wuninitialized", "uninitialized"),
        ("-Wmaybe-uninitialized", "uninitialized"),
        ("-Wnull-dereference", "null_deref"),
        ("-Wnonnull", "null_deref"),      # null passed to nonnull parameter
        ("-Wdiv-by-zero", "arithmetic"),
        ("-Woverflow", "arithmetic"),
        ("-Wshift-", "arithmetic"),       # shift count/overflow family
        ("-Wstrict-overflow", "arithmetic"),
        # signed/unsigned comparison and lossy conversions are integer-
        # semantics hazards; kept in arithmetic rather than invented classes
        ("-Wsign-compare", "arithmetic"),
        ("-Wsign-conversion", "arithmetic"),
        ("-Wconversion", "arithmetic"),
        # "note" continuation lines and style warnings carry no defect class
        ("note", "other"),
    ),

    # GCC -fanalyzer. Translation of the validation cwe_map's
    # _FANALYZER_ADDITIONS (GCC self-annotates these with CWE ids, e.g.
    # [CWE-476]) into the coarse vocabulary.
    "gcc_analyzer": (
        ("-Wanalyzer-out-of-bounds", "memory"),           # CWE-787/125
        ("-Wanalyzer-malloc-leak", "memory"),             # CWE-401
        ("-Wanalyzer-double-free", "memory"),             # CWE-415
        ("-Wanalyzer-use-after-free", "memory"),          # CWE-416
        ("-Wanalyzer-free-of-non-heap", "memory"),        # CWE-590 invalid free
        ("-Wanalyzer-write-to-const", "memory"),          # invalid write target
        ("-Wanalyzer-write-to-string-literal", "memory"),
        ("-Wanalyzer-use-of-uninitialized-value", "uninitialized"),  # CWE-457
        ("-Wanalyzer-null-dereference", "null_deref"),    # CWE-476
        ("-Wanalyzer-possible-null-dereference", "null_deref"),
        ("-Wanalyzer-null-argument", "null_deref"),
        ("-Wanalyzer-possible-null-argument", "null_deref"),
        ("-Wanalyzer-deref-before-check", "null_deref"),
        # file-descriptor/stream leaks are resource-contract violations,
        # not memory unsafety (cwe_map: CWE-775)
        ("-Wanalyzer-file-leak", "api_misuse"),
        ("-Wanalyzer-fd-", "api_misuse"),
        # the analyzer's own give-up notes (non-blocking info) are coverage
        # information, not a defect
        ("-Wanalyzer-too-complex", "other"),
        ("-Wanalyzer-symbol-too-complex", "other"),
    ),

    # clang-tidy incl. the Clang Static Analyzer (clang-analyzer-*) and the
    # AST-based mpi-*/openmp-* checks. low_confidence (the optin.mpi family)
    # stays orthogonal to the class.
    "clang_tidy": (
        ("clang-analyzer-core.NullDereference", "null_deref"),
        # CallAndMessage flags garbage/uninitialized arguments — grouped
        # with uninitialized, matching the validation cwe_map
        ("clang-analyzer-core.CallAndMessage", "uninitialized"),
        ("clang-analyzer-core.uninitialized", "uninitialized"),
        ("clang-analyzer-core.DivideZero", "arithmetic"),
        ("clang-analyzer-core.StackAddressEscape", "memory"),
        ("clang-analyzer-unix.Malloc", "memory"),
        ("clang-analyzer-unix.MismatchedDeallocator", "memory"),
        ("clang-analyzer-cplusplus.NewDelete", "memory"),  # incl. NewDeleteLeaks
        ("clang-analyzer-cplusplus.PlacementNew", "memory"),
        ("clang-analyzer-optin.mpi", "mpi_usage"),
        ("mpi-", "mpi_usage"),            # AST checks: buffer-deref, type-mismatch
        # thread-safety violations (mt-unsafe calls in concurrent context)
        ("concurrency-", "race"),
        # exceptions escaping a parallel region violate the OpenMP contract
        ("openmp-exception-escape", "api_misuse"),
        # style recommendation (fires on correct code; non-blocking anyway)
        ("openmp-use-default-none", "other"),
        # numeric conversion/widening hazards
        ("bugprone-narrowing-conversions", "arithmetic"),
        ("bugprone-implicit-widening", "arithmetic"),
        ("bugprone-misplaced-widening-cast", "arithmetic"),
        ("bugprone-integer-division", "arithmetic"),
        ("bugprone-incorrect-roundings", "arithmetic"),
        ("cppcoreguidelines-narrowing-conversions", "arithmetic"),
        # object-lifetime contract, not memory unsafety in the ASan sense
        ("bugprone-use-after-move", "api_misuse"),
        ("bugprone-dangling-handle", "memory"),
        # TU failed to parse -> nothing was analyzed
        ("clang-diagnostic-error", "build"),
    ),

    # cppcheck ids (camelCase).
    "cppcheck": (
        ("arrayIndexOutOfBounds", "memory"),
        ("bufferAccessOutOfBounds", "memory"),
        ("outOfBounds", "memory"),
        ("negativeIndex", "memory"),
        ("pointerOutOfBounds", "memory"),
        ("memleak", "memory"),
        ("doubleFree", "memory"),
        ("deallocuse", "memory"),         # use after dealloc
        ("mismatchAllocDealloc", "memory"),
        ("invalidFree", "memory"),
        ("uninit", "uninitialized"),      # uninitvar/uninitdata/uninitMemberVar
        ("nullPointer", "null_deref"),
        ("zerodiv", "arithmetic"),
        ("integerOverflow", "arithmetic"),
        ("shiftTooManyBits", "arithmetic"),
        ("signConversion", "arithmetic"),
    ),

    # Meta Infer bug_types (verbatim upper-case ids), incl. the InferBO
    # additions (BUFFER_OVERRUN_L*, INTEGER_OVERFLOW_L*).
    "infer": (
        ("NULL_DEREFERENCE", "null_deref"),
        ("NULLPTR_DEREFERENCE", "null_deref"),
        ("BUFFER_OVERRUN", "memory"),     # all InferBO levels
        ("MEMORY_LEAK", "memory"),
        ("USE_AFTER_", "memory"),         # USE_AFTER_FREE/_DELETE/_LIFETIME
        ("DOUBLE_FREE", "memory"),
        ("DANGLING_POINTER_DEREFERENCE", "memory"),
        ("STACK_VARIABLE_ADDRESS_ESCAPE", "memory"),
        ("INTEGER_OVERFLOW", "arithmetic"),
        ("UNINITIALIZED_VALUE", "uninitialized"),
        # file/stream handles: resource contract, not memory (see fanalyzer
        # file-leak)
        ("RESOURCE_LEAK", "api_misuse"),
        ("DEAD_STORE", "other"),          # quality signal, no defect class
    ),

    # LLOV: exactly two verdict ids.
    "llov": (
        ("llov-data-race", "race"),
        # honest "could not analyze" note, not a defect
        ("llov-region-not-analyzed", "other"),
    ),

    # PARCOACH emits one finding type in our parse: a collective possibly
    # not reached by all ranks — the defect class is the resulting DEADLOCK
    # risk (rank-dependent collective sequencing), which is also how the
    # tool's own paper frames it. Message-level subtypes beyond "Call
    # Ordering Error" do not occur with PARCOACH 2.4.1 on our reduced TU.
    "parcoach": (
        ("parcoach-collective-ordering", "deadlock"),
    ),

    # ASan/LSan/UBSan (asan_ubsan tool). Every AddressSanitizer report class
    # (heap/stack/global overflow, use-after-*, double free, invalid free)
    # is a memory-safety violation, and LeakSanitizer reports leaks ->
    # prefix rules cover the whole space honestly. UBSan's single check_id
    # (ubsan-runtime-error) is split by MESSAGE below (see _UBSAN_RULES).
    "asan_ubsan": (
        ("asan-", "memory"),
        ("lsan-", "memory"),
    ),

    # TSan/Archer.
    "tsan": (
        ("tsan-data-race", "race"),
        ("tsan-lock-order", "deadlock"),  # lock-order-inversion reports
    ),

    # Valgrind memcheck kinds (slugged).
    "memcheck": (
        ("memcheck-invalid", "memory"),   # invalid-read/-write/-free
        ("memcheck-mismatched", "memory"),
        ("memcheck-leak", "memory"),      # leak-definitely-lost etc.
        ("memcheck-uninit", "uninitialized"),
        # syscall-param = uninitialized/unaddressable bytes handed to the OS
        ("memcheck-syscall-param", "uninitialized"),
    ),

    # Helgrind/DRD (default-disabled, map kept complete regardless).
    "helgrind": (
        ("helgrind-race", "race"),
        ("helgrind-lock-order", "deadlock"),
    ),
    "drd": (
        ("drd-conflicting-access", "race"),
        ("drd-lock-order", "deadlock"),
    ),

    # MUST runtime checks: a detected deadlock is its own class, everything
    # else (datatype null/mismatch, request lifecycle, integer args, buffer
    # reuse) is MPI API usage.
    "must": (
        ("must-deadlock", "deadlock"),
        ("must-", "mpi_usage"),
    ),
}

# UBSan reports share ONE check_id (ubsan-runtime-error); the defect class
# lives in the message. Keyword rules, first match wins; unmatched UBSan
# messages fall to "other" with a log (conservative, never guessed).
_UBSAN_RULES: "Tuple[Tuple[str, str], ...]" = (
    ("null pointer", "null_deref"),       # "member access within null pointer ..."
    ("out of bounds", "memory"),          # "index N out of bounds for type ..."
    ("overflow", "arithmetic"),           # signed integer overflow / shift overflow
    ("division by zero", "arithmetic"),
    ("shift exponent", "arithmetic"),
    ("negation of", "arithmetic"),        # -INT_MIN
)

# one log line per NEW unknown id — the mechanism that lets the map grow
_LOGGED_UNKNOWN: set = set()


def classify_finding(tool: str, check_id: str, message: str = "") -> str:
    """Error class for one finding; conservative, never raises.

    Unknown tools/ids return "other" and log ONCE per (tool, check_id) so
    the map can grow deliberately instead of guessing.
    """
    check_id = check_id or ""

    if tool == "asan_ubsan" and check_id.startswith("ubsan-"):
        lowered = (message or "").lower()
        for keyword, cls in _UBSAN_RULES:
            if keyword in lowered:
                return cls
        _log_unknown(tool, "ubsan-runtime-error: %s" % lowered[:60])
        return "other"

    for prefix, cls in CLASS_RULES.get(tool, ()):
        if check_id.startswith(prefix):
            return cls

    _log_unknown(tool, check_id)
    return "other"


def _log_unknown(tool: str, check_id: str) -> None:
    key = (tool, check_id)
    if key in _LOGGED_UNKNOWN:
        return
    _LOGGED_UNKNOWN.add(key)
    print(
        "[finding_classes] unmapped check_id -> class 'other': %s / %s "
        "(extend CLASS_RULES if this is a real defect class)" % (tool, check_id)
    )
