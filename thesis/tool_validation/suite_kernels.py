"""Kernel discovery and label parsing for the three validation suites.

Yields ValidationKernel objects: one standalone source file plus its ground
-truth label ("bad"/"good"), its defect classes, and how to compile it.

Label sources:
  - Juliet: every single-file testcase yields TWO kernels — the bad variant
    (-DOMITGOOD) and the good variant (-DOMITBAD). The CWE class comes from
    the testcase directory name. Multi-file testcases (letter-suffixed
    variants like _61a.c) are excluded: they cannot be analyzed standalone.
  - DataRaceBench: `-yes.c` = data race present, `-no.c` = race free.
  - MBI: the BEGIN_MBI_TESTS header block; `| ERROR: <Class>` lines mark
    defective kernels (classes collected), `| OK` marks correct ones.

Python 3.8 compatible (runs in the LLOV container).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

SUITES_DIR = Path(__file__).resolve().parent / "suites"

# Memory / pointer / overflow CWE subset (deliberately NOT the whole suite).
JULIET_CWES = {
    "CWE121",  # stack-based buffer overflow
    "CWE122",  # heap-based buffer overflow
    "CWE124",  # buffer underwrite
    "CWE126",  # buffer over-read
    "CWE127",  # buffer under-read
    "CWE190",  # integer overflow
    "CWE191",  # integer underflow
    "CWE401",  # memory leak
    "CWE415",  # double free
    "CWE416",  # use after free
    "CWE457",  # use of uninitialized variable
    "CWE476",  # NULL pointer dereference
    "CWE590",  # free of memory not on heap
}

# single-file flow variants: ..._01.c / ..._18.cpp; letter suffixes (_61a.c)
# are multi-file testcases -> excluded
JULIET_SINGLE_FILE = re.compile(r"_\d{2}\.(c|cpp)$")

MBI_TEST_BLOCK = re.compile(r"BEGIN_MBI_TESTS(.*?)END_MBI_TESTS", re.S)
MBI_ERROR_LINE = re.compile(r"\|\s*ERROR:\s*([\w.-]+)")
MBI_OK_LINE = re.compile(r"\|\s*OK\b")
MBI_NP = re.compile(r"mpirun\s+(?:[^|\n]*?)-np\s+(\d+)")


@dataclass
class ValidationKernel:
    suite: str
    kernel_id: str            # unique within the suite
    path: Path
    label: str                # "bad" | "good"
    classes: List[str]        # defect classes ("CWE121", "race", "deadlock", ...)
    execution_model: str      # serial | omp | mpi (drives flags/applicability)
    language: str             # "c" | "cpp"
    extra_defines: List[str] = field(default_factory=list)
    include_dirs: List[str] = field(default_factory=list)
    num_procs: int = 2        # mpi kernels: ranks from the MBI header


def _juliet_root() -> Optional[Path]:
    root = SUITES_DIR / "juliet"
    if not root.exists():
        return None

    support = list(root.rglob("testcasesupport"))
    return support[0].parent if support else None


def iter_juliet(per_class: Optional[int] = None) -> Iterator[ValidationKernel]:
    """Yield Juliet kernels; `per_class` caps the number of TESTCASE FILES
    per CWE class (each file yields one bad + one good kernel).

    The cap takes the alphabetically first N files per class — a
    deterministic, reproducible subset (documented in the README): the full
    suite (37,838 kernels) is unnecessary for overlap measurement and would
    multiply runtime without adding statistical value.
    """
    root = _juliet_root()

    if root is None:
        return

    support_dir = str(root / "testcasesupport")

    for cwe_dir in sorted((root / "testcases").iterdir()):
        cwe = cwe_dir.name.split("_")[0]

        if cwe not in JULIET_CWES:
            continue

        files_in_class = 0

        for path in sorted(cwe_dir.rglob("*")):
            if per_class is not None and files_in_class >= per_class:
                break

            if not JULIET_SINGLE_FILE.search(path.name):
                continue

            if "w32" in path.name:  # Windows-only API testcases
                continue

            files_in_class += 1

            language = "cpp" if path.suffix == ".cpp" else "c"
            rel = str(path.relative_to(root))

            # bad variant: good functions compiled out, defect present
            yield ValidationKernel(
                suite="juliet",
                kernel_id=rel + "#bad",
                path=path,
                label="bad",
                classes=[cwe],
                execution_model="serial",
                language=language,
                extra_defines=["OMITGOOD"],
                include_dirs=[support_dir],
            )
            # good variant: defect compiled out, must be clean
            yield ValidationKernel(
                suite="juliet",
                kernel_id=rel + "#good",
                path=path,
                label="good",
                classes=[cwe],
                execution_model="serial",
                language=language,
                extra_defines=["OMITBAD"],
                include_dirs=[support_dir],
            )


def iter_drb() -> Iterator[ValidationKernel]:
    bench_dir = SUITES_DIR / "drb" / "micro-benchmarks"

    if not bench_dir.exists():
        return

    for path in sorted(bench_dir.glob("*.c")):
        if path.name.endswith("-yes.c"):
            label = "bad"
        elif path.name.endswith("-no.c"):
            label = "good"
        else:
            continue

        yield ValidationKernel(
            suite="drb",
            kernel_id=path.name,
            path=path,
            label=label,
            classes=["race"],
            execution_model="omp",
            language="c",
        )


def iter_mbi() -> Iterator[ValidationKernel]:
    gencodes = SUITES_DIR / "mbi" / "gencodes"

    if not gencodes.exists():
        return

    for path in sorted(gencodes.glob("*.c")):
        try:
            header = path.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue

        block = MBI_TEST_BLOCK.search(header)

        if not block:
            continue  # unparseable label -> not part of the measurement

        errors = MBI_ERROR_LINE.findall(block.group(1))
        has_ok = MBI_OK_LINE.search(block.group(1)) is not None

        if not errors and not has_ok:
            continue

        np_match = MBI_NP.search(block.group(1))

        yield ValidationKernel(
            suite="mbi",
            kernel_id=path.name,
            path=path,
            label="bad" if errors else "good",
            classes=sorted({e.lower() for e in errors}) or ["ok"],
            execution_model="mpi",
            language="c",
            num_procs=int(np_match.group(1)) if np_match else 2,
        )


SUITE_ITERATORS = {
    "juliet": iter_juliet,
    "drb": iter_drb,
    "mbi": iter_mbi,
}


def load_kernels(
    suite: str,
    limit: Optional[int] = None,
    juliet_per_class: Optional[int] = None,
) -> List[ValidationKernel]:
    if suite == "juliet":
        kernels = list(iter_juliet(per_class=juliet_per_class))
    else:
        kernels = list(SUITE_ITERATORS[suite]())

    if limit is not None:
        # STRATIFIED limit: half bad, half good/no (in discovery order).
        # A plain head-slice produced all-bad smoke sets (DRB sorts yes
        # before no per pair), making the FP rate unmeasurable (tn=fp=0).
        bad_budget = (limit + 1) // 2
        good_budget = limit // 2

        chosen: List[ValidationKernel] = []
        for kernel in kernels:
            if kernel.label == "bad" and bad_budget > 0:
                chosen.append(kernel)
                bad_budget -= 1
            elif kernel.label == "good" and good_budget > 0:
                chosen.append(kernel)
                good_budget -= 1
            if bad_budget == 0 and good_budget == 0:
                break

        kernels = chosen

    return kernels
