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
//   - the ENHANCED_RUNTIME_FILL block below is preprocessed away.
//
// Defines used by the enhanced-tests runners:
//   -DENHANCED_TEST_SIZE=<n>      override the validate() TEST_SIZE
//                                 (ALWAYS a compile define — also in
//                                 runtime-fill mode)
//   -DENHANCED_FILL_PATTERN=<id>  select a fill pattern (ids below)
//   -DENHANCED_FILL_LO=<v> / -DENHANCED_FILL_HI=<v>
//                                 override the call site's value range
//                                 (both must be given)
//   -DENHANCED_FILL_PARAM_K=<k>   position parameter of the k-patterns
//                                 (duplicate_at / sorted_except_one /
//                                 spike_at); validated in Python to
//                                 k in [0, size-1] and size >= 2
//   -DENHANCED_RUNTIME_FILL       runtime-fill mode: the pattern and its
//                                 parameters come from ENVIRONMENT
//                                 variables instead of the defines above
//                                 (one compile per (sample, size) serves
//                                 every fill pattern). Mutually exclusive
//                                 with ENHANCED_FILL_PATTERN.
//
// Runtime-fill mode (ENHANCED_RUNTIME_FILL) environment variables, read
// once on the first ENHANCED_FILL call (benchmarks without a fill site
// never read them — exactly like the define path, where the fill defines
// have no effect there):
//   ENHANCED_FILL_PATTERN      MANDATORY, the same integer id the define
//                              carries. Missing or unknown -> immediate
//                              abort with a clear stderr message. This is
//                              a DELIBERATE difference from the define
//                              path, which maps unknown ids to random:
//                              the runtime path never falls back silently.
//   ENHANCED_FILL_RANGE_LO/HI  optional; both -> override the call site's
//                              lo/hi, neither -> keep the call site's
//                              values, exactly one -> abort.
//   ENHANCED_FILL_K            mandatory for the k-patterns (7/8/9),
//                              invalid -> abort; ignored elsewhere.
//   ENHANCED_FILL_VALUES_FILE  mandatory for explicit_values (10): path
//                              to a file with one number per line
//                              (row-major); missing, empty or unreadable
//                              -> abort; ignored elsewhere.
// Numbers are parsed with std::from_chars (locale-independent by
// definition; C++17, double support in libstdc++ since GCC 11 — verified
// in the container, GCC 13.3). The harness never calls setlocale(): the
// process goes on to execute model code, and global locale state would be
// a harness side effect inside the measured object. If double from_chars
// is unavailable, the documented fallback is an istringstream imbued with
// std::locale::classic() (also without touching the process locale).
//
// Pattern id 10 (explicit_values) in DEFINE mode reads its data from a
// GENERATED header `enhanced-explicit-values.hpp` that the runner writes
// next to the build (an -I'd temp dir), defining:
//     static const double ENHANCED_EXPLICIT_VALUES[] = {...};
//     static const size_t ENHANCED_EXPLICIT_COUNT = ...;
// In RUNTIME mode the same values come from ENHANCED_FILL_VALUES_FILE.
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

#if defined(ENHANCED_RUNTIME_FILL) && defined(ENHANCED_FILL_PATTERN)
#error "ENHANCED_RUNTIME_FILL and ENHANCED_FILL_PATTERN are mutually exclusive: a binary is configured either at run time (env) or at compile time (defines)"
#endif

#if defined(ENHANCED_RUNTIME_FILL)

#include <cerrno>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>
#if !(defined(__cpp_lib_to_chars) && __cpp_lib_to_chars >= 201611L)
#include <locale>
#include <sstream>
#endif

[[noreturn]] inline void enhancedRuntimeAbort(const char *what, const char *detail) {
    std::fprintf(stderr, "ENHANCED_RUNTIME_FILL: %s%s%s\n",
                 what, detail ? ": " : "", detail ? detail : "");
    std::abort();
}

inline double enhancedRuntimeParseDouble(const char *text, const char *what) {
#if defined(__cpp_lib_to_chars) && __cpp_lib_to_chars >= 201611L
    const char *last = text + std::strlen(text);
    double value = 0.0;
    const std::from_chars_result parsed = std::from_chars(text, last, value);
    if (parsed.ec != std::errc() || parsed.ptr != last) {
        enhancedRuntimeAbort(what, text);
    }
    return value;
#else
    // documented fallback for libstdc++ without double from_chars (< GCC
    // 11): classic-locale istringstream — locale-independent WITHOUT
    // touching the global process locale
    std::istringstream stream((std::string(text)));
    stream.imbue(std::locale::classic());
    double value = 0.0;
    stream >> value;
    if (stream.fail() || !stream.eof()) {
        enhancedRuntimeAbort(what, text);
    }
    return value;
#endif
}

inline long enhancedRuntimeParseLong(const char *text, const char *what) {
    // integer from_chars is baseline C++17 (libstdc++ since GCC 8)
    const char *last = text + std::strlen(text);
    long value = 0;
    const std::from_chars_result parsed = std::from_chars(text, last, value);
    if (parsed.ec != std::errc() || parsed.ptr != last) {
        enhancedRuntimeAbort(what, text);
    }
    return value;
}

template <typename DType>
DType enhancedRuntimeRangeValue(double value) {
    // Mirror of the define path's (decltype(lo))(LITERAL) range cast,
    // which GCC constant-folds with TRUNCATE-THEN-SATURATE semantics
    // (measured in-container at -O0/-O2/-O3: (unsigned long)(-1.0) folds
    // to 0, (int)(3e9) to INT_MAX). A plain runtime static_cast would take
    // the x86-64 cvttsd2si wrap/indefinite path instead
    // ((unsigned long)(-1.0) -> 2^64-1) — bit-divergent inputs on integral
    // fill sites (e.g. the sparse_la index vectors, filled 0UL..TEST_SIZE)
    // whenever a spec's value_range exceeds the site type's range.
    if constexpr (std::is_integral_v<DType>) {
        const double truncated = std::trunc(value);
        if (std::isnan(truncated)) {
            return DType(0);
        }
        if (truncated <= static_cast<double>(std::numeric_limits<DType>::min())) {
            return std::numeric_limits<DType>::min();
        }
        if (truncated >= static_cast<double>(std::numeric_limits<DType>::max())) {
            return std::numeric_limits<DType>::max();
        }
        return static_cast<DType>(truncated);
    } else {
        return enhancedFromDouble<DType>(value);
    }
}

struct EnhancedRuntimeFillConfig {
    int pattern;
    bool has_range;
    double lo;
    double hi;
    size_t k;
    std::vector<double> values;
};

inline const EnhancedRuntimeFillConfig &enhancedRuntimeFillConfig() {
    // magic static: parsed once, on the FIRST fill call. Every rule below
    // aborts instead of falling back — a misconfigured harness must never
    // silently run a different input than the spec describes.
    static const EnhancedRuntimeFillConfig config = [] {
        EnhancedRuntimeFillConfig parsed;
        parsed.pattern = 0;
        parsed.has_range = false;
        parsed.lo = 0.0;
        parsed.hi = 0.0;
        parsed.k = 0;

        const char *pattern_text = std::getenv("ENHANCED_FILL_PATTERN");
        if (pattern_text == nullptr) {
            enhancedRuntimeAbort(
                "ENHANCED_FILL_PATTERN is mandatory in runtime mode (the "
                "compile-define path maps unknown patterns to random; the "
                "runtime path aborts by design — no silent fallback)",
                nullptr);
        }
        const long pattern =
            enhancedRuntimeParseLong(pattern_text, "ENHANCED_FILL_PATTERN is not an integer");
        if (pattern < 0 || pattern > 10) {
            enhancedRuntimeAbort("unknown ENHANCED_FILL_PATTERN id (implemented: 0..10)",
                                 pattern_text);
        }
        parsed.pattern = static_cast<int>(pattern);

        const char *lo_text = std::getenv("ENHANCED_FILL_RANGE_LO");
        const char *hi_text = std::getenv("ENHANCED_FILL_RANGE_HI");
        if ((lo_text == nullptr) != (hi_text == nullptr)) {
            enhancedRuntimeAbort(
                "ENHANCED_FILL_RANGE_LO and ENHANCED_FILL_RANGE_HI must be given "
                "both or not at all", nullptr);
        }
        if (lo_text != nullptr) {
            parsed.has_range = true;
            parsed.lo = enhancedRuntimeParseDouble(lo_text, "ENHANCED_FILL_RANGE_LO is not a number");
            parsed.hi = enhancedRuntimeParseDouble(hi_text, "ENHANCED_FILL_RANGE_HI is not a number");
        }

        if (parsed.pattern == 7 || parsed.pattern == 8 || parsed.pattern == 9) {
            const char *k_text = std::getenv("ENHANCED_FILL_K");
            if (k_text == nullptr) {
                enhancedRuntimeAbort(
                    "ENHANCED_FILL_K is mandatory for the k-patterns "
                    "(duplicate_at / sorted_except_one / spike_at)", nullptr);
            }
            const long k = enhancedRuntimeParseLong(k_text, "ENHANCED_FILL_K is not an integer");
            if (k < 0) {
                enhancedRuntimeAbort("ENHANCED_FILL_K must be >= 0", k_text);
            }
            parsed.k = static_cast<size_t>(k);
        }

        if (parsed.pattern == 10) {
            const char *file_text = std::getenv("ENHANCED_FILL_VALUES_FILE");
            if (file_text == nullptr) {
                enhancedRuntimeAbort(
                    "ENHANCED_FILL_VALUES_FILE is mandatory for explicit_values", nullptr);
            }
            std::ifstream file(file_text);
            if (!file) {
                enhancedRuntimeAbort("cannot open ENHANCED_FILL_VALUES_FILE", file_text);
            }
            std::string line;
            while (std::getline(file, line)) {
                while (!line.empty() &&
                       (line.back() == '\r' || line.back() == ' ' || line.back() == '\t')) {
                    line.pop_back();
                }
                const size_t first = line.find_first_not_of(" \t");
                if (first == std::string::npos) {
                    continue;  // blank line (e.g. trailing newline)
                }
                parsed.values.push_back(enhancedRuntimeParseDouble(
                    line.c_str() + first, "ENHANCED_FILL_VALUES_FILE line is not a number"));
            }
            if (file.bad()) {
                enhancedRuntimeAbort("read error on ENHANCED_FILL_VALUES_FILE", file_text);
            }
            if (parsed.values.empty()) {
                enhancedRuntimeAbort("ENHANCED_FILL_VALUES_FILE is empty", file_text);
            }
        }

        return parsed;
    }();
    return config;
}

template <typename T, typename DType>
void enhancedRuntimeFill(T &x, DType lo, DType hi) {
    const EnhancedRuntimeFillConfig &config = enhancedRuntimeFillConfig();

    if (config.has_range) {
        // conversion equivalent to the define path's constant-folded
        // (decltype(lo))(LITERAL) cast — saturating for integral DType,
        // see enhancedRuntimeRangeValue (complex gets a real-only value)
        lo = enhancedRuntimeRangeValue<DType>(config.lo);
        hi = enhancedRuntimeRangeValue<DType>(config.hi);
    }

    if (config.pattern == 10) {
        // explicit_values: cyclic fill from the values file — mirrors the
        // define path's generated-header loop exactly (the switch's case
        // 10 is only compiled in define mode, where the header exists);
        // like it, this performs NO rand() call
        const size_t n = x.size();
        for (size_t i = 0; i < n; i += 1) {
            x[i] = enhancedFromDouble<DType>(config.values[i % config.values.size()]);
        }
        return;
    }

    // shared body with the define path: identical code, therefore an
    // identical rand() call sequence per pattern — the equivalence-critical
    // property (one extra rand() call would shift ALL subsequent inputs;
    // fillRand draws from unseeded, deterministic rand())
    enhancedFillPattern(x, lo, hi, config.pattern, config.k);
}

#define ENHANCED_FILL(x, lo, hi) enhancedRuntimeFill((x), (lo), (hi))

#elif defined(ENHANCED_FILL_PATTERN)
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
