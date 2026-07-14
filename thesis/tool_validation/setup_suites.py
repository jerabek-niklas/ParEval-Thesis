"""Download the three labeled benchmark suites for the tool validation.

Everything lands under thesis/tool_validation/suites/ (gitignored):
    suites/juliet/   -- Juliet C/C++ 1.3 (NIST SARD), unpacked zip
    suites/drb/      -- LLNL DataRaceBench (git clone)
    suites/mbi/      -- MPI Bugs Initiative (git clone + generated codes)

Run on the host (needs git + python3 + network) or inside the main
container. Idempotent: existing suites are kept unless --force is given.

MBI note: the repository ships *generators*; the actual .c kernels are
produced by its own tooling. This script attempts the documented
generation entry points and reports what worked — if generation fails,
run MBI's generator manually inside suites/mbi (see error output).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

SUITES_DIR = Path(__file__).resolve().parent / "suites"

JULIET_URL = (
    "https://samate.nist.gov/SARD/downloads/test-suites/"
    "2017-10-01-juliet-test-suite-for-c-cplusplus-v1-3.zip"
)

DRB_GIT = "https://github.com/LLNL/dataracebench.git"

MBI_GITS = [
    "https://gitlab.com/MpiBugsInitiative/MpiBugsInitiative.git",
    "https://github.com/MpiBugsInitiative/MpiBugsInitiative.git",
]


def run(argv: list, cwd: "Path | None" = None) -> int:
    print(f"  $ {' '.join(str(a) for a in argv)}")
    return subprocess.call([str(a) for a in argv], cwd=str(cwd) if cwd else None)


def setup_juliet(force: bool) -> None:
    target = SUITES_DIR / "juliet"

    if target.exists() and not force:
        print(f"[juliet] exists, skipping ({target})")
        return

    if target.exists():
        shutil.rmtree(target)

    target.mkdir(parents=True)
    zip_path = target / "juliet.zip"

    print(f"[juliet] downloading {JULIET_URL} (~several hundred MB) ...")
    # NIST answers 403 to urllib's default user agent; identify as a browser,
    # fall back to curl if urllib still fails.
    request = urllib.request.Request(
        JULIET_URL, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    )
    try:
        with urllib.request.urlopen(request) as response, zip_path.open("wb") as out:
            shutil.copyfileobj(response, out)
    except Exception as error:  # noqa: BLE001 - fall through to curl
        print(f"[juliet] urllib failed ({error}), trying curl ...")
        if run(["curl", "-fSL", "-A", "Mozilla/5.0", "-o", zip_path, JULIET_URL]) != 0:
            print("[juliet] ERROR: download failed")
            return

    print("[juliet] unpacking ...")
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(target)

    zip_path.unlink()

    # normalize: the zip contains a top-level "C" directory
    testcases = list(target.rglob("testcasesupport"))
    if not testcases:
        print("[juliet] WARNING: testcasesupport/ not found after unpack")
    else:
        print(f"[juliet] ok: {testcases[0].parent}")


def setup_drb(force: bool) -> None:
    target = SUITES_DIR / "drb"

    if target.exists() and not force:
        print(f"[drb] exists, skipping ({target})")
        return

    if target.exists():
        shutil.rmtree(target)

    print("[drb] cloning DataRaceBench ...")
    if run(["git", "clone", "--depth", "1", DRB_GIT, target]) != 0:
        print("[drb] ERROR: clone failed")
        return

    kernels = list((target / "micro-benchmarks").glob("*.c"))
    print(f"[drb] ok: {len(kernels)} micro-benchmark files")


def setup_mbi(force: bool) -> None:
    target = SUITES_DIR / "mbi"

    if target.exists() and not force:
        print(f"[mbi] exists, skipping ({target})")
        return

    if target.exists():
        shutil.rmtree(target)

    cloned = False
    for url in MBI_GITS:
        print(f"[mbi] cloning {url} ...")
        if run(["git", "clone", "--depth", "1", url, target]) == 0:
            cloned = True
            break

    if not cloned:
        print("[mbi] ERROR: no mirror reachable")
        return

    gencodes = target / "gencodes"

    if not gencodes.exists() or not list(gencodes.glob("*.c")):
        print("[mbi] generating kernels (MBI ships generators, not codes) ...")
        # documented entry points, tried in order
        for argv in (
            [sys.executable, "MBI.py", "-c", "generate"],
            [sys.executable, "scripts/MBI.py", "-c", "generate"],
        ):
            if (target / argv[1]).exists():
                if run(argv, cwd=target) == 0:
                    break

    kernels = list(gencodes.glob("*.c")) if gencodes.exists() else []

    if kernels:
        print(f"[mbi] ok: {len(kernels)} generated kernels")
    else:
        print(
            "[mbi] WARNING: no kernels in gencodes/ — run MBI's generator "
            "manually inside suites/mbi (see its README), then re-run "
            "the validation runner."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Download validation suites.")
    parser.add_argument("--force", action="store_true", help="Re-download existing suites.")
    parser.add_argument(
        "--only",
        choices=["juliet", "drb", "mbi"],
        default=None,
        help="Set up a single suite.",
    )
    args = parser.parse_args()

    SUITES_DIR.mkdir(parents=True, exist_ok=True)

    if args.only in (None, "juliet"):
        setup_juliet(args.force)
    if args.only in (None, "drb"):
        setup_drb(args.force)
    if args.only in (None, "mbi"):
        setup_mbi(args.force)


if __name__ == "__main__":
    main()
