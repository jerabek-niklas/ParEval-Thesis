# Evaluation Environment (WSL2 + Docker)

The generation stage (API calls) runs anywhere. The evaluation stages
(compilation, correctness tests, static analysis) require a Linux
toolchain and run inside the Docker container defined in
`docker/Dockerfile`. The container pins the exact toolchain — cite
`/opt/toolchain-versions.txt` in the methodology chapter.

## One-time setup (Windows)

1. Install WSL2 with Ubuntu (PowerShell, admin):

       wsl --install -d Ubuntu-24.04

2. Inside Ubuntu, install Docker Engine (or install Docker Desktop on
   Windows with the WSL2 backend — either works):

       curl -fsSL https://get.docker.com | sudo sh
       sudo usermod -aG docker $USER   # then close and reopen the shell

3. Clone the repo **into the WSL filesystem** (important: not under
   /mnt/c/... — accessing Windows paths from WSL is an order of magnitude
   slower, and OneDrive must never sync a working repo):

       cd ~
       git clone <repo-url> ParEval-Thesis
       cd ParEval-Thesis
       git checkout thesis-static-analysis

4. Create `.env` in the repo root with the API keys (only needed if
   generation also runs in the container):

       ANTHROPIC_API_KEY=...
       OPENAI_API_KEY=...
       GEMINI_API_KEY=...
       OPENAI_COMPATIBLE_API_KEY=...

## Build the image

    docker build -t pareval-thesis -f docker/Dockerfile .

The build runs a toolchain self-test (serial, OpenMP, MPI 4 ranks, TSan,
ASan, clang-tidy, cppcheck) and fails if anything is broken.

## Run

Interactive shell with the repo mounted (results land directly in the
repo, nothing lives only inside the container):

    docker run --rm -it -v "$(pwd)":/workspace --env-file .env pareval-thesis

Inside the container the usual commands work unchanged, e.g.:

    python3 thesis/assembly/assemble_sources.py \
        --config thesis/config/config.yaml --profile smoke

## Typical workflow

| Step        | Where                          |
|-------------|--------------------------------|
| Generation  | Windows or container (API only)|
| Assembly    | Either (pure Python)           |
| Correctness | Container                      |
| Static analysis | Container                  |
| Repair loop | Container (needs API keys)     |

Sync between Windows and WSL via git (push/pull), not via shared folders.

## Moving to a rented server (optional)

If the full run is too slow locally, the identical container runs on any
Linux host:

    docker build -t pareval-thesis -f docker/Dockerfile .
    docker run --rm -it -v "$(pwd)":/workspace --env-file .env pareval-thesis

No code changes required; results are bit-comparable because the
toolchain is identical.

## Known limitations

- MUST (MPI correctness checker) is not yet in the image; it requires a
  source build and will be added with the static-analysis stage.
- Performance numbers measured in WSL2/Docker are not meaningful for
  scaling claims (shared host, virtualization overhead). The thesis
  measures correctness and code quality; runtime is recorded only as a
  sanity signal, not as a result.
