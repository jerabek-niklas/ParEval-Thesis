#pragma once
// Enhanced-tests support: overridable validation size + injectable fill
// patterns (thesis enhanced_tests stage, EvalPlus-style differential
// testing). Included at the end of utilities.hpp.
//
// WITHOUT the ENHANCED_* compile defines this header changes NOTHING:
//   - ENHANCED_TEST_SIZE_DEFAULT(n) evaluates to n (the benchmark's
//     original TEST_SIZE), mirroring the DRIVER_PROBLEM_SIZE pattern.
//   - ENHANCED_FILL(x, lo, hi) expands to fillRand(x, lo, hi).
//   - the pattern template below stays uninstantiated (no codegen).
//
// Defines used by thesis/evaluation/../enhanced_tests runners:
//   -DENHANCED_TEST_SIZE=<n>      override the validate() TEST_SIZE
//   -DENHANCED_FILL_PATTERN=<id>  select a fill pattern (ids below)
//   -DENHANCED_FILL_LO=<v> / -DENHANCED_FILL_HI=<v>
//                                 override the call site's value range
//                                 (both must be given)

#include <complex>
#include <cstddef>
#include <limits>

#if defined(ENHANCED_TEST_SIZE)
#define ENHANCED_TEST_SIZE_DEFAULT(dflt) (ENHANCED_TEST_SIZE)
#else
#define ENHANCED_TEST_SIZE_DEFAULT(dflt) (dflt)
#endif

// Fill pattern ids. Keep in sync with the spec pattern names in
// thesis/enhanced_tests/ (specs use the names, the runner maps to ids):
//   0 random          uniform in [lo, hi]  (identical to fillRand)
//   1 all_zeros
//   2 all_same        midpoint of [lo, hi]
//   3 ascending       linear ramp lo -> hi
//   4 descending      linear ramp hi -> lo
//   5 alternating     lo, hi, lo, hi, ...
//   6 extreme_values  numeric_limits lowest/max alternating

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

template <typename T, typename DType>
void enhancedFillPattern(T &x, DType lo, DType hi, int pattern) {
    const size_t n = x.size();

    for (size_t i = 0; i < n; i += 1) {
        switch (pattern) {
            case 1:  // all_zeros
                x[i] = DType(0);
                break;
            case 2:  // all_same
                x[i] = enhancedMidValue<DType>(lo, hi);
                break;
            case 3:  // ascending
                x[i] = enhancedRampValue<DType>(lo, hi, i, n, false);
                break;
            case 4:  // descending
                x[i] = enhancedRampValue<DType>(lo, hi, i, n, true);
                break;
            case 5:  // alternating
                x[i] = (i % 2 == 0) ? lo : hi;
                break;
            case 6:  // extreme_values
                x[i] = enhancedExtremeValue<DType>(i);
                break;
            default:  // 0 / unknown: random, identical to fillRand
                break;
        }
    }

    if (pattern == 0) {
        fillRand(x, lo, hi);
    }
}

#if defined(ENHANCED_FILL_PATTERN)
#if defined(ENHANCED_FILL_LO) && defined(ENHANCED_FILL_HI)
#define ENHANCED_FILL(x, lo, hi) \
    enhancedFillPattern((x), (decltype(lo))(ENHANCED_FILL_LO), \
                        (decltype(lo))(ENHANCED_FILL_HI), (ENHANCED_FILL_PATTERN))
#else
#define ENHANCED_FILL(x, lo, hi) \
    enhancedFillPattern((x), (lo), (hi), (ENHANCED_FILL_PATTERN))
#endif
#else
#define ENHANCED_FILL(x, lo, hi) fillRand((x), (lo), (hi))
#endif
