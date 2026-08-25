#pragma once
// ---------------------------------------------------------------------------
// Trusted harness markers: the per-execution authentication token and the
// Validation verdict line (execution contract F1).
//
// WHY A SEPARATE HEADER, not utilities.hpp:
// the model drivers (models/serial-driver.cc, omp-driver.cc, mpi-driver.cc,
// mpi-omp-driver.cc, kokkos-driver.cc, cuda-driver.cu, hip-driver.cu) are
// compiled STANDALONE by drivers/cpp/Makefile with
//     g++ -std=c++17 -O3 -c models/<x>-driver.cc
// i.e. WITHOUT -DUSE_<MODEL> and WITHOUT -DDRIVER_PROBLEM_SIZE. Including
// utilities.hpp there fires its two #error guards (verified in-container), so
// the shared helper cannot live in utilities.hpp without breaking the upstream
// build and with it test/test-serial.bash. This header therefore depends on
// nothing but <cstdio>/<cstdlib> and is included BY utilities.hpp as well, so
// there is exactly ONE implementation of the token on both sides.
//
// ---------------------------------------------------------------------------
// THREAT MODEL (contract F1.1)
//
//   A) UNINTENTIONAL candidate output — a generated implementation that
//      happens to print "Validation: PASS" or the BI marker. stdout is shared
//      between harness and candidate, so a constant marker string has no
//      authority. The per-execution token defeats this case: a candidate
//      cannot guess 128 random bits.
//
//   B) DELIBERATELY adversarial candidate code that reads its own process
//      environment and copies the token. This is NOT solved here and no
//      cryptographic guarantee is claimed. With one process and one shared
//      stdout it is not solvable at this level.
//
// ---------------------------------------------------------------------------
// TWO OPERATING MODES (contract F1.3)
//
//   THESIS-AUTHENTICATED — PAREVAL_BI_NONCE set and non-empty:
//       Validation: PASS nonce=<token>
//       Validation: FAIL nonce=<token>
//
//   LEGACY — no token in the environment:
//       Validation: PASS
//       Validation: FAIL
//
// The legacy line is byte-identical to the historical one, because
// drivers/driver_wrapper.py (used by drivers/run-all.py and
// test/test-serial.bash) parses it. The NEW thesis evaluation pipeline must
// never rely on the legacy mode: every thesis launch sets a token, and a
// thesis parser that finds only the legacy form treats it as a TRANSPORT
// ERROR, not as a verdict (contract F1.6 rule 7).
//
// ---------------------------------------------------------------------------
// MPI ASYMMETRY (contract F1.4) — deliberate, not an oversight:
//
//   BI          is a LOCAL ORACLE DISCOVERY. Any rank can make it, so any
//               rank may emit its own BI marker (at most once per rank).
//   Validation  is the FINAL DRIVER VERDICT. The mpi driver represents it on
//               the root rank only, so it is emitted EXACTLY ONCE per
//               `mpirun` execution.
//
// This header implements no rank logic at all. The mpi drivers keep calling
// the emitter from their existing root-only verdict path; that control flow
// is unchanged.
// ---------------------------------------------------------------------------

#include <cstdio>
#include <cstdlib>

// Historical name. It now carries the SHARED harness authentication token for
// BOTH the BASELINE_INCOMPATIBLE marker and the Validation verdict line — one
// token per child execution. A second environment variable was deliberately
// not introduced just because the old name says "BI".
#define PAREVAL_HARNESS_NONCE_ENV "PAREVAL_BI_NONCE"

inline const char *parevalReadHarnessNonce() {
    const char *value = std::getenv(PAREVAL_HARNESS_NONCE_ENV);
    return (value != 0 && value[0] != '\0') ? value : "";
}

// The token of THIS process, or "" when the environment carries none.
// Read exactly once (function-local static: thread-safe initialisation).
inline const char *parevalHarnessNonce() {
    static const char *const cached = parevalReadHarnessNonce();
    return cached;
}

inline bool parevalAuthenticatedMode() {
    return parevalHarnessNonce()[0] != '\0';
}

// ONE complete line, then an immediate flush: against a pipe stdout is block
// buffered, so a process that is killed on timeout or aborts afterwards would
// otherwise lose the verdict inside the buffer (same rationale as the BI
// marker's flush).
inline void parevalEmitValidation(bool isValid) {
    const char *const verdict = isValid ? "PASS" : "FAIL";
    const char *const nonce = parevalHarnessNonce();

    if (nonce[0] != '\0') {
        printf("Validation: %s nonce=%s\n", verdict, nonce);
    } else {
        printf("Validation: %s\n", verdict);
    }

    fflush(stdout);
}
