#pragma once
#include <cassert>
#include <cmath>
#include <climits>
#include <cfloat>
#include <cstdio>
#include <string>
#include <complex>
#include <queue>
#include <type_traits>

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

// compare two vectors of floating point numbers
template <typename Vec, typename FType>
bool fequal(Vec const& a, Vec const& b, FType epsilon = 1e-6) {
    assert(a.size() == b.size());
    for (int i = 0; i < a.size(); i += 1) {
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
//     MISMATCH index=5 expected=3.14159 got=0 input=0.847
//     MISMATCH_SUMMARY shown=3 total=47
//
// The MISMATCH_SUMMARY line is MANDATORY on every failing comparison, even
// when total <= shown: the model must be able to tell 3-of-3 outliers from
// 3-of-47 (a surface problem) — never silently truncate. No output on the
// PASS path (timing unaffected). Only rank 0 prints. Inputs are random
// without a persisted seed, so the report is symptom feedback, not a
// reproducible test case (see the design doc).
//
// MISMATCH_REPORT_MAX (default 3) is set by the runners from the single
// config source stages.repair.feedback.mismatch_report_max_indices.
// ---------------------------------------------------------------------------

#if !defined(MISMATCH_REPORT_MAX)
#define MISMATCH_REPORT_MAX 3
#endif

template <typename V>
void mismatchPrintValue(V const& v) {
    if constexpr (std::is_same_v<V, std::complex<double>>) {
        printf("(%g,%g)", v.real(), v.imag());
    } else if constexpr (std::is_floating_point_v<V>) {
        printf("%g", static_cast<double>(v));
    } else if constexpr (std::is_same_v<V, bool>) {
        printf("%d", static_cast<int>(v));
    } else if constexpr (std::is_integral_v<V>) {
        printf("%lld", static_cast<long long>(v));
    } else {
        printf("?");  // non-printable element type; field still present
    }
}

inline bool mismatchIsRoot() {
    int mmRank;
    GET_RANK(mmRank);
    return IS_ROOT(mmRank);
}

template <typename Vec, typename InVec, typename Pred>
bool reportAndCompareWith(Vec const& a, Vec const& b, InVec const* input, Pred differs) {
    assert(a.size() == b.size());

    const bool isRoot = mismatchIsRoot();
    size_t total = 0;
    size_t shown = 0;

    for (size_t i = 0; i < a.size(); i += 1) {
        using V = typename Vec::value_type;
        const V va = static_cast<V>(a[i]);
        const V vb = static_cast<V>(b[i]);

        if (!differs(va, vb)) {
            continue;
        }

        total += 1;

        if (isRoot && shown < (size_t)(MISMATCH_REPORT_MAX)) {
            shown += 1;
            printf("MISMATCH index=%zu expected=", i);
            mismatchPrintValue(va);
            printf(" got=");
            mismatchPrintValue(vb);
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
    if (equal) {
        return true;
    }

    if (mismatchIsRoot()) {
        printf("MISMATCH expected=");
        mismatchPrintValue(expected);
        printf(" got=");
        mismatchPrintValue(got);
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
