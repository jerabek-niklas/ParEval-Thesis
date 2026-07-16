#pragma once
// Enhanced-tests support: overridable validation size + injectable fill
// patterns (thesis enhanced_tests stage, EvalPlus-style differential
// testing). Included at the end of utilities.hpp.
//
// WITHOUT the ENHANCED_* compile defines this header changes NOTHING:
//   - ENHANCED_TEST_SIZE_DEFAULT(n) evaluates to n (the benchmark's
//     original TEST_SIZE), mirroring the DRIVER_PROBLEM_SIZE pattern.
//   - ENHANCED_FILL(x, lo, hi) expands to fillRand(x, lo, hi).
//   - the pattern templates below stay uninstantiated (no codegen).
//
// Defines used by the enhanced-tests runners:
//   -DENHANCED_TEST_SIZE=<n>      override the validate() TEST_SIZE
//   -DENHANCED_FILL_PATTERN=<id>  select a fill pattern (ids below)
//   -DENHANCED_FILL_LO=<v> / -DENHANCED_FILL_HI=<v>
//                                 override the call site's value range
//                                 (both must be given)
//   -DENHANCED_FILL_PARAM_K=<k>   position parameter of the k-patterns
//                                 (duplicate_at / sorted_except_one /
//                                 spike_at); validated in Python to
//                                 k in [0, size-1] and size >= 2
//
// Pattern id 10 (explicit_values) reads its data from a GENERATED header
// `enhanced-explicit-values.hpp` that the runner writes next to the build
// (an -I'd temp dir), defining:
//     static const double ENHANCED_EXPLICIT_VALUES[] = {...};
//     static const size_t ENHANCED_EXPLICIT_COUNT = ...;
// Containers larger than the value list (e.g. row-major matrices of
// size*size elements for a spec size of N) are filled CYCLICALLY:
// x[i] = values[i % count] — for a size x size matrix with count == size
// this repeats the given row pattern per matrix row.

#include <complex>
#include <cstddef>
#include <limits>
#include <utility>

#if defined(ENHANCED_TEST_SIZE)
#define ENHANCED_TEST_SIZE_DEFAULT(dflt) (ENHANCED_TEST_SIZE)
#else
#define ENHANCED_TEST_SIZE_DEFAULT(dflt) (dflt)
#endif

#if !defined(ENHANCED_FILL_PARAM_K)
#define ENHANCED_FILL_PARAM_K 0
#endif

#if defined(ENHANCED_FILL_PATTERN) && (ENHANCED_FILL_PATTERN == 10)
#include "enhanced-explicit-values.hpp"
#endif

// Fill pattern ids. Keep in sync with PATTERNS in
// thesis/enhanced_tests/specs.py (specs use the names, the runner maps
// to ids):
//   0 random            uniform in [lo, hi]  (identical to fillRand)
//   1 all_zeros
//   2 all_same          midpoint of [lo, hi]
//   3 ascending         linear ramp lo -> hi
//   4 descending        linear ramp hi -> lo
//   5 alternating       lo, hi, lo, hi, ...
//   6 extreme_values    numeric_limits lowest/max alternating
//   7 duplicate_at(k)   random fill, then x[k] = x[(k+1) % n]
//   8 sorted_except_one(k) ascending ramp, then swap(x[k], x[(k+1) % n])
//   9 spike_at(k)       random fill, then x[k] = numeric_limits::max()/2
//                       (complex: spike on the real part)
//  10 explicit_values   values from the generated header (cyclic)

template <typename DType>
DType enhancedRampValue(DType lo, DType hi, size_t index, size_t n, bool descending) {
    const size_t position = descending ? (n - 1 - index) : index;

    if constexpr (std::is_floating_point_v<DType>) {
        if (n <= 1) {
            return lo;
        }
        return lo + (hi - lo) * (static_cast<DType>(position) / static_cast<DType>(n - 1));
    } else if constexpr (std::is_integral_v<DType>) {
        const DType span = (hi > lo) ? static_cast<DType>(hi - lo) : DType(0);
        if (span == DType(0)) {
            return lo;
        }
        return static_cast<DType>(lo + static_cast<DType>(position % static_cast<size_t>(span + 1)));
    } else if constexpr (std::is_same_v<DType, std::complex<double>>) {
        const double ramp = (n <= 1)
            ? lo.real()
            : lo.real() + (hi.real() - lo.real()) * (static_cast<double>(position) / static_cast<double>(n - 1));
        return DType(ramp, ramp);
    }
}

template <typename DType>
DType enhancedExtremeValue(size_t index) {
    if constexpr (std::is_floating_point_v<DType>) {
        return (index % 2 == 0) ? std::numeric_limits<DType>::lowest()
                                : std::numeric_limits<DType>::max();
    } else if constexpr (std::is_integral_v<DType>) {
        return (index % 2 == 0) ? std::numeric_limits<DType>::min()
                                : std::numeric_limits<DType>::max();
    } else if constexpr (std::is_same_v<DType, std::complex<double>>) {
        const double v = (index % 2 == 0) ? std::numeric_limits<double>::lowest()
                                          : std::numeric_limits<double>::max();
        return DType(v, v);
    }
}

template <typename DType>
DType enhancedMidValue(DType lo, DType hi) {
    if constexpr (std::is_same_v<DType, std::complex<double>>) {
        return DType((lo.real() + hi.real()) / 2.0, (lo.imag() + hi.imag()) / 2.0);
    } else {
        return static_cast<DType>(lo + (hi - lo) / 2);
    }
}

template <typename DType>
DType enhancedSpikeValue() {
    // half of max: an extreme but arithmetic-surviving magnitude
    if constexpr (std::is_floating_point_v<DType>) {
        return std::numeric_limits<DType>::max() / 2;
    } else if constexpr (std::is_integral_v<DType>) {
        return std::numeric_limits<DType>::max() / 2;
    } else if constexpr (std::is_same_v<DType, std::complex<double>>) {
        return DType(std::numeric_limits<double>::max() / 2, 0.0);  // real-part spike
    }
}

template <typename DType>
DType enhancedFromDouble(double value) {
    if constexpr (std::is_same_v<DType, std::complex<double>>) {
        return DType(value, 0.0);
    } else {
        return static_cast<DType>(value);
    }
}

template <typename T, typename DType>
void enhancedFillPattern(T &x, DType lo, DType hi, int pattern, size_t param_k) {
    const size_t n = x.size();

    if (n == 0) {
        return;
    }

    const size_t k = param_k % n;  // Python validates; modulo as a backstop

    switch (pattern) {
        case 1:  // all_zeros
            for (size_t i = 0; i < n; i += 1) x[i] = DType(0);
            break;
        case 2:  // all_same
            for (size_t i = 0; i < n; i += 1) x[i] = enhancedMidValue<DType>(lo, hi);
            break;
        case 3:  // ascending
            for (size_t i = 0; i < n; i += 1) x[i] = enhancedRampValue<DType>(lo, hi, i, n, false);
            break;
        case 4:  // descending
            for (size_t i = 0; i < n; i += 1) x[i] = enhancedRampValue<DType>(lo, hi, i, n, true);
            break;
        case 5:  // alternating
            for (size_t i = 0; i < n; i += 1) x[i] = (i % 2 == 0) ? lo : hi;
            break;
        case 6:  // extreme_values
            for (size_t i = 0; i < n; i += 1) x[i] = enhancedExtremeValue<DType>(i);
            break;
        case 7:  // duplicate_at(k): random, then duplicate neighbor value
            fillRand(x, lo, hi);
            x[k] = x[(k + 1) % n];
            break;
        case 8:  // sorted_except_one(k): ascending, then one swap
            for (size_t i = 0; i < n; i += 1) x[i] = enhancedRampValue<DType>(lo, hi, i, n, false);
            std::swap(x[k], x[(k + 1) % n]);
            break;
        case 9:  // spike_at(k): random in original range, one huge outlier
            fillRand(x, lo, hi);
            x[k] = enhancedSpikeValue<DType>();
            break;
#if defined(ENHANCED_FILL_PATTERN) && (ENHANCED_FILL_PATTERN == 10)
        case 10:  // explicit_values: cyclic fill from the generated header
            for (size_t i = 0; i < n; i += 1) {
                x[i] = enhancedFromDouble<DType>(
                    ENHANCED_EXPLICIT_VALUES[i % ENHANCED_EXPLICIT_COUNT]);
            }
            break;
#endif
        default:  // 0 / unknown: random, identical to fillRand
            fillRand(x, lo, hi);
            break;
    }
}

#if defined(ENHANCED_FILL_PATTERN)
#if defined(ENHANCED_FILL_LO) && defined(ENHANCED_FILL_HI)
#define ENHANCED_FILL(x, lo, hi) \
    enhancedFillPattern((x), (decltype(lo))(ENHANCED_FILL_LO), \
                        (decltype(lo))(ENHANCED_FILL_HI), (ENHANCED_FILL_PATTERN), \
                        (size_t)(ENHANCED_FILL_PARAM_K))
#else
#define ENHANCED_FILL(x, lo, hi) \
    enhancedFillPattern((x), (lo), (hi), (ENHANCED_FILL_PATTERN), \
                        (size_t)(ENHANCED_FILL_PARAM_K))
#endif
#else
#define ENHANCED_FILL(x, lo, hi) fillRand((x), (lo), (hi))
#endif
