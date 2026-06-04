from pathlib import Path
import shutil

SRC = Path("prompts/raw")
DST = Path("thesis/prompts/raw")

KEEP = {"serial", "omp", "mpi"}

if not SRC.exists():
    raise FileNotFoundError(f"Source folder not found: {SRC}")

if DST.exists():
    shutil.rmtree(DST)

count = 0

for file in SRC.rglob("*"):
    if file.is_file() and file.name in KEEP:
        relative_path = file.relative_to(SRC)
        target = DST / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        count += 1

print(f"Copied {count} prompt files to {DST}")
