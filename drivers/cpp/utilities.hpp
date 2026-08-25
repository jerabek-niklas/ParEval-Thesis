#pragma once
#include <cassert>
#include <cmath>
#include <climits>
#include <cfloat>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <complex>
#include <queue>
#include <type_traits>

// The shared harness authentication token and the trusted Validation emitter.
// Deliberately a separate, dependency-free header: the model drivers are
// compiled standalone by drivers/cpp/Makefile WITHOUT -DUSE_<MODEL> and
// WITHOUT -DDRIVER_PROBLEM_SIZE, so they cannot include this file — but both
// sides must agree on ONE token implementation.
#include "harness-markers.hpp"

// make sure some parallel model is defined
#if !defined(USE_SERIAL) && !defined(USE_OMP) && !defined(USE_MPI) && !defined(USE_MPI_OMP) && !defined(USE_KOKKOS) && !defined(USE_CUDA) && !defined(USE_HIP)
#error "No parallel model not defined"
#endif

#define NO_OPTIMIZE __attribute__((optimize("O0")))
#define NO_INLINE __attribute__((noinline)) __attribute__((optimize("O3")))

#if !defined(DRIVER_PROBLEM_SIZE)
#error "DRIVER_PROBLEM_SIZE not defined"
#endif

#if !defined(MAX_VALIDATION_ATTEMPTS)
#define MAX_VALIDATION_ATTEMPTS 2
#endif

#if !defined(SPARSE_LA_SPARSITY)
// sparsity to use for sparse linear algebra benchmarks
#define SPARSE_LA_SPARSITY 0.1
#endif

// include the necessary libraries for the parallel model
#if defined(USE_OMP) || defined(USE_MPI_OMP)
#include <omp.h>
#elif defined(USE_MPI) || defined(USE_MPI_OMP)
#include <mpi.h>
#elif defined(USE_KOKKOS)
#include <Kokkos_Core.hpp>
#elif defined(USE_CUDA)
#include <cuda_runtime.h>
#elif defined(USE_HIP)
#include <hip/hip_runtime.h>
#endif

// some helper macros to unify CUDA and HIP interfaces
#if defined(USE_CUDA)
#define GRID_STRIDE_LOOP(i, n) for (int i = blockIdx.x * blockDim.x + threadIdx.x; i < (n); i += blockDim.x * gridDim.x)
#define ALLOC(ptr, size) cudaMalloc(&(ptr), (size))
#define COPY_H2D(dst, src, size) cudaMemcpy((dst), (src), (size), cudaMemcpyHostToDevice)
#define COPY_D2H(dst, src, size) cudaMemcpy((dst), (src), (size), cudaMemcpyDeviceToHost)
#define FREE(ptr) cudaFree((ptr))
#define SYNC() cudaDeviceSynchronize()
#define DOUBLE_COMPLEX_T cuDoubleComplex
#define MAKE_DOUBLE_COMPLEX(r,i) make_cuDoubleComplex((r),(i))
#elif defined(USE_HIP)
#define GRID_STRIDE_LOOP(i, n) for (int i = hipBlockIdx_x * hipBlockDim_x + hipThreadIdx_x; i < (n); i += hipBlockDim_x * hipGridDim_x)
#define ALLOC(ptr, size) hipMalloc(&(ptr), (size))
#define COPY_H2D(dst, src, size) hipMemcpy((dst), (src), (size), hipMemcpyHostToDevice)
#define COPY_D2H(dst, src, size) hipMemcpy((dst), (src), (size), hipMemcpyDeviceToHost)
#define FREE(ptr) hipFree((ptr))
#define SYNC() hipDeviceSynchronize()
#define DOUBLE_COMPLEX_T hipDoubleComplex
#define MAKE_DOUBLE_COMPLEX(r,i) make_hipDoubleComplex((r),(i))
#endif

#if defined(USE_CUDA) || defined(USE_HIP)
__device__ double atomicMul(double* address, double val) { 
  unsigned long long int* address_as_ull = (unsigned long long int*)address; 
  unsigned long long int old = *address_as_ull, assumed; 
  do { 
    assumed = old; 
    old = atomicCAS(address_as_ull, assumed, __double_as_longlong(val * __longlong_as_double(assumed))); 
  } while (assumed != old); return __longlong_as_double(old);
} 
#endif

// Kokkos utilities
#if defined(USE_KOKKOS)
template <typename DType>
void copyVectorToView(std::vector<DType> const& vec, Kokkos::View<DType*> view) {
    assert(vec.size() == view.size());
    for (int i = 0; i < vec.size(); i += 1) {
        view(i) = vec[i];
    }
}

template <typename DType>
void copyViewToVector(Kokkos::View<DType*> view, std::vector<DType>& vec) {
    assert(vec.size() == view.size());
    for (int i = 0; i < vec.size(); i += 1) {
        vec[i] = view(i);
    }
}

template <typename DType>
void fillRandKokkos(Kokkos::View<DType*> &x, DType min, DType max) {
    for (int i = 0; i < x.size(); i += 1) {
        DType val;
        if constexpr (std::is_floating_point_v<DType>) {
            val = (rand() / (double) RAND_MAX) * (max - min) + min;
        } else if constexpr (std::is_integral_v<DType>) {
            val = rand() % (max - min) + min;
        }
        x(i) = val;
    }
}
#endif


// MPI utilities
#if defined(USE_MPI) || defined(USE_MPI_OMP)
#define IS_ROOT(rank) ((rank) == 0)
#define BCAST(vec,dtype) MPI_Bcast((vec).data(), (vec).size(), MPI_##dtype, 0, MPI_COMM_WORLD)
#define BCAST_PTR(ptr,size,dtype) MPI_Bcast(ptr, size, MPI_##dtype, 0, MPI_COMM_WORLD)
#define SYNC() MPI_Barrier(MPI_COMM_WORLD)
#define GET_RANK(rank) MPI_Comm_rank(MPI_COMM_WORLD, &(rank))
#else
#define IS_ROOT(rank) true
#define BCAST(vec,dtype)
#define BCAST_PTR(ptr,size,dtype)
#define GET_RANK(rank) rank = 0
#if !defined(SYNC)
#define SYNC()
#endif
#endif


template <typename T>
void fillRandString(T &x, size_t minLen, size_t maxLen) {
    for (int i = 0; i < x.size(); i += 1) {
        size_t len = rand() % (maxLen - minLen) + minLen;
        std::string str(len, ' ');
        for (int j = 0; j < len; j += 1) {
            str[j] = 'a' + rand() % 26;
        }
        x[i] = str;
    }
}

// utility functions
template <typename T, typename DType>
void fillRand(T &x, DType min, DType max) {
    
    for (int i = 0; i < x.size(); i += 1) {
        DType val;
        if constexpr (std::is_floating_point_v<DType>) {
            val = (rand() / (double) RAND_MAX) * (max - min) + min;
        } else if constexpr (std::is_integral_v<DType>) {
            val = rand() % (max - min) + min;
        } else if constexpr (std::is_same_v<DType, std::complex<double>>) {
            const double real = (rand() / (double) RAND_MAX) * (max - min) + min;
            const double imag = (rand() / (double) RAND_MAX) * (max - min) + min;
            val = std::complex<double>(real, imag);
        }
        x[i] = val;
    }
}

// Is this value finite? Non-finite = NaN or +/-Inf. Integral and boolean
// value types are finite by construction, so the check compiles away for
// them. complex<double> is finite iff BOTH components are.
template <typename V>
inline bool mismatchIsFinite(V const& v) {
    if constexpr (std::is_same_v<V, std::complex<double>>) {
        return std::isfinite(v.real()) && std::isfinite(v.imag());
    } else if constexpr (std::is_floating_point_v<V>) {
        return std::isfinite(v);
    } else {
        (void)v;
        return true;
    }
}

// compare two vectors of floating point numbers
//
// Non-finite semantics (execution contract A1c): fequal is SYMMETRIC and
// never returns true when any operand is non-finite. It deliberately does
// NOT classify which side caused it — that is the job of the role-aware
// reportAndCompare* helpers and of the gate level. Without the explicit
// check `std::abs(a - b) > epsilon` is FALSE for a NaN operand, i.e. a NaN
// silently compared EQUAL to anything.
//
// The tolerance itself is untouched (contract A1d): for two finite operands
// the behaviour is bit-identical to before.
//
// The former `assert(a.size() == b.size())` is gone for the same reason as
// in reportAndCompareWith (contract A2): under -DNDEBUG it vanished and left
// an out-of-bounds read behind a silent true.
template <typename Vec, typename FType>
bool fequal(Vec const& a, Vec const& b, FType epsilon = 1e-6) {
    if (a.size() != b.size()) {
        return false;
    }
    for (size_t i = 0; i < a.size(); i += 1) {
        if (!mismatchIsFinite(a[i]) || !mismatchIsFinite(b[i])) {
            return false;
        }
        if (std::abs(a[i] - b[i]) > epsilon) {
            return false;
        }
    }
    return true;
}

// ---------------------------------------------------------------------------
// Mismatch reporting for the repair loop (repair-loop-design.md §4).
//
// reportAndCompare* behave exactly like the comparisons they replace
// (fequal / std::equal / scalar !=), but on a mismatch they print bounded,
// machine-parseable details to stdout:
//
//     MISMATCH index=5 expected=3.1415926535897931 got=0 rel=1.00e+00 input=0.84700000000000009
//     MISMATCH_SUMMARY shown=3 total=47
//
// Numeric values print with ROUND-TRIP precision (max_digits10: double 17,
// float 9). With the default %g precision (6 significant digits) a real
// difference below the print resolution rendered expected and got as
// IDENTICAL text ("expected=182071 got=182071" at |diff| < 0.5 on
// magnitude 1.8e5, measured on smoke_002) — self-contradictory feedback
// that ran two models into stopped_budget. Only the report formatting
// changed at that time; the tolerance is still byte-compatible with
// ParEval. (fequal was called UNTOUCHED here until the non-finite
// semantics of execution contract A1 were added — see fequal above: the
// tolerance is still unchanged, only NaN/Inf operands and a size mismatch
// are now rejected instead of silently comparing equal.)
//
// rel=<|a-b| / max(|a|,|b|, denorm guard)> is printed for floating-point
// and complex comparisons (scientific, 3 significant digits): the model
// sees immediately whether it hunts a rounding or a logic error, and the
// evaluation can mechanically split rounding signatures (rel ~1e-9 at
// many indices) from genuine bugs (rel large / nan) — the classification
// the omp/mpi enhanced pilot needs. Integral/bool comparisons carry no
// rel field (any exact difference is a real bug); the parser treats it as
// optional.
//
// The MISMATCH_SUMMARY line is MANDATORY on every failing comparison, even
// when total <= shown: the model must be able to tell 3-of-3 outliers from
// 3-of-47 (a surface problem) — never silently truncate. No output on the
// PASS path (timing unaffected). Only rank 0 prints. fillRand draws from
// UNSEEDED rand() (as if srand(1)), so inputs are identical across runs
// and iterations; the draw ORDER within a process still shifts between
// call sites (see the design doc §4).
//
// MISMATCH_REPORT_MAX (default 3) is set by the runners from the single
// config source stages.repair.feedback.mismatch_report_max_indices.
// ---------------------------------------------------------------------------

#if !defined(MISMATCH_REPORT_MAX)
#define MISMATCH_REPORT_MAX 3
#endif

template <typename V>
void mismatchPrintValue(V const& v) {
    // printf with an explicit per-call precision — deliberately NOT
    // std::cout + setprecision, whose sticky stream state would leak into
    // the rest of the driver output (marker lines must stay byte-identical)
    if constexpr (std::is_same_v<V, std::complex<double>>) {
        printf("(%.*g,%.*g)",
               std::numeric_limits<double>::max_digits10, v.real(),
               std::numeric_limits<double>::max_digits10, v.imag());
    } else if constexpr (std::is_floating_point_v<V>) {
        printf("%.*g", std::numeric_limits<V>::max_digits10,
               static_cast<double>(v));
    } else if constexpr (std::is_same_v<V, bool>) {
        printf("%d", static_cast<int>(v));
    } else if constexpr (std::is_integral_v<V>) {
        printf("%lld", static_cast<long long>(v));
    } else {
        printf("?");  // non-printable element type; field still present
    }
}

// |a-b| / max(|a|,|b|, denorm guard); nan propagates (a nan operand IS the
// diagnosis). The guard makes 0-vs-0 impossible to reach (equal values never
// mismatch) and 0-vs-tiny come out as rel=1.
template <typename V>
double mismatchRelDiff(V const& a, V const& b) {
    double diff, magA, magB;

    if constexpr (std::is_same_v<V, std::complex<double>>) {
        diff = std::abs(a - b);
        magA = std::abs(a);
        magB = std::abs(b);
    } else {
        const double da = static_cast<double>(a);
        const double db = static_cast<double>(b);
        diff = std::fabs(da - db);
        magA = std::fabs(da);
        magB = std::fabs(db);
    }

    const double denom = std::fmax(std::fmax(magA, magB),
                                   std::numeric_limits<double>::min());
    return diff / denom;
}

inline bool mismatchIsRoot() {
    int mmRank;
    GET_RANK(mmRank);
    return IS_ROOT(mmRank);
}

// ---------------------------------------------------------------------------
// Non-finite REFERENCE detection (execution contract A1).
//
// A NaN/Inf value produced by the ORACLE is a property of the baseline, never
// a model failure. The comparator level only DETECTS it and announces it on
// stdout; the classification into the verdict `baseline_incompatible` happens
// in the Python stage that parses this marker (contract A1c: comparator safe,
// gate level classifies).
//
// MARKER AUTHENTICITY (contract C2b). stdout is shared between harness and
// candidate code, so a CONSTANT marker string has no authority: any candidate
// that happens to print the same line would be read as an oracle defect. The
// marker therefore carries a per-execution nonce the runner generates and
// passes in through the environment variable PAREVAL_BI_NONCE:
//
//     BASELINE_INCOMPATIBLE: non_finite_reference nonce=<hex>
//
// The parser accepts ONLY the nonce it generated for this process. Threat
// model: this defeats UNINTENTIONAL collisions (case A). It is explicitly NOT
// forgery-proof against a candidate that deliberately reads the environment
// (case B) — with a shared process and a shared stdout that is not solvable
// here, and no cryptographic guarantee is claimed. Transport is the
// environment and not a compile define because the enhanced stage reuses ONE
// binary across many runs (build groups) and configures the harness through
// the environment already (ENHANCED_RUNTIME_FILL in enhanced-fill.hpp);
// build command lines stay untouched.
//
// The marker is printed at most ONCE PER PROCESS, i.e. once per MPI RANK
// (contract C2.2). It is deliberately NOT root-only: a non-root rank that
// detects a non-finite reference must be able to say so, otherwise the case
// silently degrades to `Validation: FAIL`. No collective is introduced here —
// several markers under MPI are normal and the parser treats them as such.
//
// stdout is FLUSHED immediately after the marker (contract C2c): against a
// pipe it is block-buffered, so a process that hangs, is killed on timeout or
// aborts afterwards would otherwise lose the marker inside the buffer.
// ---------------------------------------------------------------------------
inline size_t &mismatchNonFiniteReferenceCount() {
    static size_t count = 0;
    return count;
}

// The token this process was launched with, or "" when the environment does
// not carry one (hand-run binary). ONE implementation, shared with the model
// drivers' Validation emitter — see drivers/cpp/harness-markers.hpp.
inline const char *mismatchMarkerNonce() {
    return parevalHarnessNonce();
}

inline void mismatchNoteNonFiniteReference() {
    mismatchNonFiniteReferenceCount() += 1;

    static bool emitted = false;
    if (emitted) {
        return;
    }
    emitted = true;

    const char *nonce = mismatchMarkerNonce();
    // "none" when unset: the line stays readable for a hand-run binary, but a
    // parser that expects a nonce will NOT accept it as authentic.
    printf("BASELINE_INCOMPATIBLE: non_finite_reference nonce=%s\n",
           (nonce[0] != '\0') ? nonce : "none");
    fflush(stdout);
}

// `a` is the REFERENCE (expected), `b` the CANDIDATE (got) at every call
// site; the roles are what makes the non-finite rule of contract A1b
// decidable here.
//
// `selected(i)` restricts the GRADED index set. Several benchmarks grade only
// an interior (1d stencils skip both ends, 2d stencils skip the border ring):
// their hand-written loops carried that restriction in the loop bounds. Moving
// them onto this helper keeps the graded set BIT-IDENTICAL while giving them
// the role-aware non-finite and size semantics (contract C1.5). Indices the
// selector rejects are not part of the comparison, so a non-finite value there
// is neither a mismatch nor a baseline_incompatible signal — grading an
// ungraded index would be a change of benchmark semantics.
template <typename Vec, typename InVec, typename Pred, typename Sel>
bool reportAndCompareSelectedWith(Vec const& a, Vec const& b, InVec const* input,
                                  Pred differs, Sel selected) {
    const bool isRoot = mismatchIsRoot();

    // Contract A2: this used to be `assert(a.size() == b.size())`. Under
    // -DNDEBUG the assert vanished and a wrong-length candidate compared
    // EQUAL element-wise up to the shorter size, i.e. a silent PASS (plus an
    // out-of-bounds read when the candidate was shorter). Report and fail.
    if (a.size() != b.size()) {
        if (isRoot) {
            printf("SIZE_MISMATCH expected=%zu got=%zu\n",
                   (size_t)a.size(), (size_t)b.size());
            printf("MISMATCH_SUMMARY shown=0 total=1\n");
        }
        return false;
    }

    size_t total = 0;
    size_t shown = 0;

    for (size_t i = 0; i < a.size(); i += 1) {
        if (!selected(i)) {
            continue;
        }

        using V = typename Vec::value_type;
        const V va = static_cast<V>(a[i]);
        const V vb = static_cast<V>(b[i]);

        // Contract A1b case 1, checked FIRST: a non-finite REFERENCE is a
        // baseline problem. It is neither a mismatch nor a pass — the index
        // is skipped and the process-wide marker is emitted.
        if (!mismatchIsFinite(va)) {
            mismatchNoteNonFiniteReference();
            continue;
        }

        // Contract A1b case 2: finite reference, non-finite candidate -> FAIL.
        // The tolerance predicate cannot see this (every ordered comparison
        // with NaN is false), so it is decided before `differs` runs.
        const bool nonFiniteCandidate = !mismatchIsFinite(vb);

        // Contract A1b case 3: both finite -> unchanged behaviour.
        if (!nonFiniteCandidate && !differs(va, vb)) {
            continue;
        }

        total += 1;

        if (isRoot && shown < (size_t)(MISMATCH_REPORT_MAX)) {
            shown += 1;
            printf("MISMATCH index=%zu expected=", i);
            mismatchPrintValue(va);
            printf(" got=");
            mismatchPrintValue(vb);
            if constexpr (std::is_floating_point_v<V>
                          || std::is_same_v<V, std::complex<double>>) {
                printf(" rel=%.2e", mismatchRelDiff(va, vb));
            }
            if (input != nullptr && i < input->size()) {
                using I = typename InVec::value_type;
                printf(" input=");
                mismatchPrintValue(static_cast<I>((*input)[i]));
            }
            printf("\n");
        }
    }

    if (total > 0 && isRoot) {
        printf("MISMATCH_SUMMARY shown=%zu total=%zu\n", shown, total);
    }

    return total == 0;
}

// Every index graded — the behaviour every existing call site had before the
// selector existed.
template <typename Vec, typename InVec, typename Pred>
bool reportAndCompareWith(Vec const& a, Vec const& b, InVec const* input, Pred differs) {
    return reportAndCompareSelectedWith(a, b, input, differs,
                                        [](size_t) { return true; });
}

// fequal replacement (same tolerance semantics), optional input vector
template <typename Vec, typename FType>
bool reportAndCompare(Vec const& a, Vec const& b, FType epsilon = 1e-6) {
    return reportAndCompareWith(
        a, b, static_cast<Vec const*>(nullptr),
        [epsilon](typename Vec::value_type const& x, typename Vec::value_type const& y) {
            return std::abs(x - y) > epsilon;
        });
}

template <typename Vec, typename FType, typename InVec>
bool reportAndCompare(Vec const& a, Vec const& b, FType epsilon, InVec const& input) {
    return reportAndCompareWith(
        a, b, &input,
        [epsilon](typename Vec::value_type const& x, typename Vec::value_type const& y) {
            return std::abs(x - y) > epsilon;
        });
}

// std::equal replacement (exact equality), optional input vector
template <typename Vec>
bool reportAndCompareEq(Vec const& a, Vec const& b) {
    return reportAndCompareWith(
        a, b, static_cast<Vec const*>(nullptr),
        [](typename Vec::value_type const& x, typename Vec::value_type const& y) {
            return !(x == y);
        });
}

template <typename Vec, typename InVec>
bool reportAndCompareEq(Vec const& a, Vec const& b, InVec const& input) {
    return reportAndCompareWith(
        a, b, &input,
        [](typename Vec::value_type const& x, typename Vec::value_type const& y) {
            return !(x == y);
        });
}

// scalar variants (single-value comparisons in verdicts); the summary is
// mandatory here too (shown=1 total=1)
template <typename V>
bool reportAndCompareScalarImpl(V const& expected, V const& got, bool equal) {
    // Contract A1b case 1, checked FIRST: non-finite REFERENCE is a baseline
    // problem, never a model failure. Announce it and do not fail the model.
    if (!mismatchIsFinite(expected)) {
        mismatchNoteNonFiniteReference();
        return true;
    }

    // Contract A1b case 2: finite reference, non-finite candidate -> FAIL.
    // `equal` was computed by the caller with a NaN-blind predicate, so it
    // must be overridden here.
    if (!mismatchIsFinite(got)) {
        equal = false;
    }

    if (equal) {
        return true;
    }

    if (mismatchIsRoot()) {
        printf("MISMATCH expected=");
        mismatchPrintValue(expected);
        printf(" got=");
        mismatchPrintValue(got);
        if constexpr (std::is_floating_point_v<V>
                      || std::is_same_v<V, std::complex<double>>) {
            printf(" rel=%.2e", mismatchRelDiff(expected, got));
        }
        printf("\nMISMATCH_SUMMARY shown=1 total=1\n");
    }

    return false;
}

template <typename V>
bool reportAndCompareScalar(V const& expected, V const& got) {
    return reportAndCompareScalarImpl(expected, got, expected == got);
}

template <typename V, typename FType>
bool reportAndCompareScalar(V const& expected, V const& got, FType epsilon) {
    return reportAndCompareScalarImpl(
        expected, got, !(std::abs(expected - got) > epsilon));
}

// enhanced-tests support (overridable TEST_SIZE + injectable fill patterns);
// a no-op unless the ENHANCED_* compile defines are set. Needs fillRand above.
#include "enhanced-fill.hpp"
