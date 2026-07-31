# Evaluation environment for the ParEval thesis pipeline.
#
# Contains the complete toolchain for correctness tests and static analysis:
#   - gcc/g++ (OpenMP, AddressSanitizer, ThreadSanitizer, UBSan)
#   - clang / clang-tidy / clang-tools (Clang Static Analyzer)
#   - cppcheck
#   - Meta Infer (separation-logic static analysis)
#   - OpenMPI (mpicxx, mpirun)
#   - Python 3 + thesis pipeline dependencies
#
# Build (repo root):
#   docker build -t pareval-thesis -f docker/Dockerfile .
#
# Run (repo mounted, results land directly in the repo):
#   docker run --rm -it -v "$(pwd)":/workspace --env-file .env pareval-thesis
#
# Tool versions are recorded at build time in /opt/toolchain-versions.txt (for methodology chapter).

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        -o Acquire::Retries=3 \
        build-essential \
        g++ \
        clang \
        clang-tidy \
        clang-tools \
        # clang sanitizer runtimes (TSan for the dynamic stage: clang++ +
        # libomp + libarcher is the low-false-positive OpenMP race setup;
        # gcc/libgomp+TSan reports races inside the OpenMP runtime itself)
        libclang-rt-18-dev \
        # llvm-symbolizer, required by clang sanitizer runtimes to symbolize
        # reports (without it stack frames are <null> and findings cannot be
        # attributed to the model file)
        llvm-18 \
        cppcheck \
        # dynamic binary instrumentation (Memcheck/Helgrind/DRD) — the
        # second, compile-independent detection method for memory errors
        # and data races next to the compile-time sanitizers
        valgrind \
        libomp-dev \
        openmpi-bin \
        libopenmpi-dev \
        python3 \
        python3-pip \
        git \
        time \
        ca-certificates \
        curl \
        xz-utils \
        # MUST build/runtime deps (cmake/make to build, libxml2 for GTI,
        # libdw for the Backward stacktrace module)
        cmake \
        make \
        libxml2-dev \
        libdw-dev \
        wget \
    && rm -rf /var/lib/apt/lists/*

# MUST (RWTH/TUDa): dynamic MPI correctness checking (deadlock detection,
# type matching, collective verification) via PnMPI interposition. Runs the
# target under `mustrun`; findings land in MUST_Output.html.
ARG MUST_VERSION=1.11.0
RUN wget -q --tries=3 "https://hpc.rwth-aachen.de/must/files/MUST-v${MUST_VERSION}.tar.gz" -O /tmp/must.tar.gz \
    && tar -C /opt -xzf /tmp/must.tar.gz \
    && cd "/opt/MUST-v${MUST_VERSION}" \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_INSTALL_PREFIX=/opt/must -DCMAKE_BUILD_TYPE=Release \
        -DENABLE_FORTRAN=OFF -DENABLE_TESTS=OFF > /dev/null \
    && make -j"$(nproc)" install > /dev/null \
    && rm -rf "/opt/MUST-v${MUST_VERSION}" /tmp/must.tar.gz
# NOTE: /opt/must/bin is deliberately NOT on PATH — it ships its own
# `timeout` script that would shadow coreutils. The MustTool invokes
# /opt/must/bin/mustrun by absolute path.

# Meta Infer (static analysis via separation logic / bi-abduction). The 1.1.0
# release binary bundles its own clang and runs on Ubuntu 24.04; it adds a
# detection method independent of clang-tidy/cppcheck (interprocedural
# null-deref, resource/memory leaks, uninitialized values). Verified that its
# bundled clang parses modern libstdc++ + <mpi.h>.
ARG INFER_VERSION=1.1.0
RUN curl -sSL "https://github.com/facebook/infer/releases/download/v${INFER_VERSION}/infer-linux64-v${INFER_VERSION}.tar.xz" \
        | tar -C /opt -xJ \
    && ln -s "/opt/infer-linux64-v${INFER_VERSION}/bin/infer" /usr/local/bin/infer \
    && infer --version

# Sanitizer runtimes look up "llvm-symbolizer" on PATH (unversioned).
RUN ln -sf /usr/lib/llvm-18/bin/llvm-symbolizer /usr/local/bin/llvm-symbolizer

# NOTE (dynamic stage): LLVM's TSan requires vm.mmap_rnd_bits <= 28. Newer
# kernels (incl. Docker Desktop's WSL2 VM, kernel 6.6) default to 32, which
# makes TSan-instrumented binaries segfault at startup. Once per VM boot:
#   docker run --privileged --rm ubuntu:24.04 sysctl -w vm.mmap_rnd_bits=28
# The TsanTool preflight detects this and reports an actionable error.

# OpenMPI inside containers: runs as root, and benchmark rank counts may
# exceed available cores (oversubscribe).
ENV OMPI_ALLOW_RUN_AS_ROOT=1 \
    OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    OMPI_MCA_rmaps_base_oversubscribe=true

# Slim Python dependencies for the thesis pipeline only (NOT the upstream
# ParEval requirements.txt, which pulls in torch/transformers for local
# model inference that this pipeline does not use).
COPY thesis/requirements.txt /tmp/thesis-requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/thesis-requirements.txt

# Exact tool versions for reproducibility / methodology chapter.
RUN { \
        echo "== toolchain versions ($(date -u +%Y-%m-%dT%H:%M:%SZ)) =="; \
        gcc --version | head -1; \
        g++ --version | head -1; \
        clang --version | head -1; \
        clang-tidy --version | grep -i version; \
        cppcheck --version; \
        mpirun --version | head -1; \
        infer --version | head -1; \
        python3 --version; \
    } > /opt/toolchain-versions.txt \
    && cat /opt/toolchain-versions.txt

# Build-time self-test: image build fails if any part of the toolchain is
# broken (serial, OpenMP, MPI multi-rank, TSan, ASan, clang-tidy, cppcheck).
RUN set -e; \
    cd /tmp; \
    printf 'int main(){return 0;}\n' > t.cc; \
    g++ -std=c++17 -O3 t.cc -o t_serial && ./t_serial; \
    printf '#include <omp.h>\n#include <cstdio>\nint main(){int n=0;\n#pragma omp parallel\n{\n#pragma omp single\nn=omp_get_num_threads();\n}\nprintf("omp threads: %%d\\n", n);return n>0?0:1;}\n' > o.cc; \
    g++ -std=c++17 -fopenmp o.cc -o t_omp && OMP_NUM_THREADS=4 ./t_omp; \
    printf '#include <mpi.h>\nint main(int argc,char**argv){MPI_Init(&argc,&argv);int r;MPI_Comm_rank(MPI_COMM_WORLD,&r);MPI_Finalize();return 0;}\n' > m.cc; \
    mpicxx -std=c++17 m.cc -o t_mpi && mpirun -np 4 ./t_mpi; \
    g++ -std=c++17 -fsanitize=thread -fopenmp o.cc -o t_tsan; \
    # compile+link only: RUNNING TSan binaries needs vm.mmap_rnd_bits<=28 on
    # the build host (see note above), which would make image builds
    # host-dependent; runtime operability is verified by verify_detection.py
    clang++ -std=c++17 -fsanitize=thread -fopenmp o.cc -o t_tsan_clang; \
    g++ -std=c++17 -fsanitize=address t.cc -o t_asan && ./t_asan; \
    clang-tidy --checks='bugprone-*' t.cc -- -std=c++17 > /dev/null; \
    cppcheck --enable=warning t.cc > /dev/null 2>&1; \
    valgrind --tool=memcheck --error-exitcode=99 ./t_serial; \
    printf 'int deref(int*p){return *p;}\nint hf(){int*q=0;return deref(q);}\n' > ih.hpp; \
    printf '#include "ih.hpp"\n' > ic.cc; \
    infer run --headers -o /tmp/infer-out --keep-going -- clang++ -std=c++17 -c ic.cc > /dev/null 2>&1; \
    grep -q NULL_DEREFERENCE /tmp/infer-out/report.json; \
    rm -rf t.cc o.cc m.cc ih.hpp ic.cc t_serial t_omp t_mpi t_tsan t_asan infer-out; \
    echo "toolchain self-test passed"

# Docker CLI (client only, static binary — no daemon) so the repair
# orchestrator can start the PARCOACH/LLOV sibling containers itself
# (stages.repair.external_tools_mode: docker). Without it the loop would
# have to stop at every wave and wait for the containers to be run by hand,
# which is not workable for 11 models x 3 variants x N iterations.
#
# Requires at RUN time (docker-outside-of-docker, NOT docker-in-docker):
#   -v /var/run/docker.sock:/var/run/docker.sock
# The sibling containers are started by the HOST daemon, so their -v mounts
# take HOST paths — the orchestrator therefore templates {host_repo}, see
# stages.repair.external_tool_commands in config.yaml.
ARG DOCKER_CLI_VERSION=27.3.1
RUN curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
        -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp docker/docker \
    && mv /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz \
    && docker --version

WORKDIR /workspace

CMD ["/bin/bash"]
