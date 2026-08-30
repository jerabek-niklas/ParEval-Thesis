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

#include <cmath>
#include <complex>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <type_traits>
#include <utility>

// E2-A.1: controlled failure for a fill configuration the harness cannot
// execute without undefined behaviour. Only reachable when a spec bypassed
// thesis/enhanced_tests/specs.py::validate_spec (which rejects every such
// range upstream) or when the header is exercised directly by a safety probe:
// the harness stops with a diagnostic instead of executing UB. Defined
// unconditionally, but every caller lives in a template that stays
// uninstantiated without the ENHANCED_* defines, so a normal correctness build
// gets no codegen from it.
[[noreturn]] inline void enhancedFillAbort(const char *what, const char *detail) {
    std::fprintf(stderr, "ENHANCED_FILL: %s%s%s\n",
                 what, detail ? ": " : "", detail ? detail : "");
    std::abort();
}

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
//   6 extreme_values    E2-B: alternates the EFFECTIVE domain endpoints
//                       lo, hi (before E2-B: numeric_limits lowest/max)
//   7 duplicate_at(k)   random fill, then x[k] = x[(k+1) % n]
//   8 sorted_except_one(k) ascending ramp, then swap(x[k], x[(k+1) % n])
//   9 spike_at(k)       E2-B: random fill, then x[k] = the effective domain
//                       upper extreme hi (before E2-B: numeric_limits::max()/2)
//  10 explicit_values   values from the generated header (cyclic)

// E2-B extreme semantics (EXTREME_PATTERN_SEMANTICS =
// DECLARED_FILL_DOMAIN_EXTREMA, SPIKE_AT_SEMANTICS =
// DECLARED_DOMAIN_UPPER_EXTREME). Enhanced tests exist to probe MODEL BEHAVIOUR
// on unusual but semantically legitimate inputs, not to probe whether the
// harness survives C++ numeric_limits. Every fill site in the suite declares a
// narrow domain at its call site ([-1,1], [0,100], [0,255], [0,2], ...), so
// numeric_limits extrema were out-of-domain inputs that mostly measured oracle
// overflow. `extreme_values` therefore alternates the EFFECTIVE endpoints (the
// call site's, or the spec's validated value_range) and `spike_at` places the
// effective `hi` at index k. Both are per fill SITE, so a benchmark whose sites
// declare different domains gets each site's own endpoints, never one global
// numeric_limits value.
//
// Note for the policy layer: alternating the effective endpoints is exactly
// what pattern 5 (alternating) already does, so under this semantics
// `extreme_values` produces a byte-identical input. The enforced policy marks
// it unsupported for that reason (duplicate_of_alternating_under_domain_extrema);
// the implementation stays here so define/runtime parity and the historical
// input of an already-recorded extreme_values spec remain provable.
//
// E2-A fill-type safety (P0). The pattern VALUE TYPE is the CONTAINER's
// element type, never the type of the call site's lo/hi literals. Before
// E2-A the type was deduced from lo/hi, so a site like
// `ENHANCED_FILL(std::vector<int> x, 0.0, 100.0)` computed
// numeric_limits<double> extremes and assigned them to int elements — an
// out-of-range floating->integral conversion, i.e. undefined behaviour.
// This is a TYPE fix only: extreme_values still means "extrema of the value
// type" (Option A). It does NOT redefine extreme_values/spike_at in terms of
// the benchmark or fill domain (EXTREME_PATTERN_SEMANTICS stays open), and it
// introduces no clipping policy for spec value ranges
// (VALUE_RANGE_DOMAIN_POLICY stays open).
//
// enhancedRangeEndpoint converts a range endpoint (call-site literal, or a
// spec's ENHANCED_FILL_LO/HI / ENHANCED_FILL_RANGE_LO/HI override) into the
// container's element type. For integral targets it keeps the semantics the
// define path already had via the constant-folded (decltype(lo))(LITERAL)
// cast — TRUNCATE, then SATURATE — and the runtime path already implemented
// explicitly; a plain static_cast would be undefined for out-of-range values.
// Floating targets saturate for the same reason (double -> float out of range
// is undefined too). Both fill paths now funnel through this one helper, so
// the define and runtime paths cannot drift apart.
template <typename VType, typename SrcType>
VType enhancedRangeEndpoint(SrcType value) {
    if constexpr (std::is_same_v<VType, std::complex<double>>) {
        return VType(static_cast<double>(value), 0.0);
    } else if constexpr (std::is_same_v<SrcType, std::complex<double>>) {
        return static_cast<VType>(value.real());
    } else if constexpr (std::is_floating_point_v<SrcType>) {
        const double wide = static_cast<double>(value);
        if (std::isnan(wide)) {
            return VType(0);
        }
        if constexpr (std::is_integral_v<VType>) {
            const double truncated = std::trunc(wide);
            if (truncated <= static_cast<double>(std::numeric_limits<VType>::min())) {
                return std::numeric_limits<VType>::min();
            }
            if (truncated >= static_cast<double>(std::numeric_limits<VType>::max())) {
                return std::numeric_limits<VType>::max();
            }
            return static_cast<VType>(truncated);
        } else {
            if (wide <= static_cast<double>(std::numeric_limits<VType>::lowest())) {
                return std::numeric_limits<VType>::lowest();
            }
            if (wide >= static_cast<double>(std::numeric_limits<VType>::max())) {
                return std::numeric_limits<VType>::max();
            }
            return static_cast<VType>(wide);
        }
    } else {
        return static_cast<VType>(value);
    }
}

// E2-A.1 technical range safety, C++ side. Answers ONE question: can the fill
// arithmetic compute with this range in this element type?
//   integral  hi - lo must be representable in DType and span + 1 as well
//             (the ramp computes position % (span + 1)), so span < max(DType)
//   floating  hi - lo must stay finite
// This mirrors, in the harness, the rule
// thesis/enhanced_tests/capabilities.py::value_range_rejection enforces in
// Python. It is a REPRESENTABILITY statement, not a benchmark domain policy:
// VALUE_RANGE_DOMAIN_POLICY stays open and nothing here clips or reinterprets
// a value.
template <typename DType>
bool enhancedRangeSpanIsSafe(DType lo, DType hi) {
    if constexpr (std::is_integral_v<DType>) {
        using U = std::make_unsigned_t<DType>;
        if (hi < lo) {
            return false;
        }
        const U span = static_cast<U>(static_cast<U>(hi) - static_cast<U>(lo));
        return span < static_cast<U>(std::numeric_limits<DType>::max());
    } else if constexpr (std::is_floating_point_v<DType>) {
        if (!(hi >= lo)) {
            return false;
        }
        return std::isfinite(static_cast<DType>(hi - lo));
    } else {
        // complex<double>: filled through its double endpoints, whose span is
        // checked by the same rule one level down
        return true;
    }
}

template <typename DType>
DType enhancedRampValue(DType lo, DType hi, size_t index, size_t n, bool descending) {
    const size_t position = descending ? (n - 1 - index) : index;

    if constexpr (std::is_floating_point_v<DType>) {
        if (n <= 1) {
            return lo;
        }
        return lo + (hi - lo) * (static_cast<DType>(position) / static_cast<DType>(n - 1));
    } else if constexpr (std::is_integral_v<DType>) {
        // E2-A.1: span and offset are computed in the UNSIGNED counterpart of
        // DType, so hi - lo and lo + step can never be a signed overflow.
        // For every range the validator admits, the result is bit-identical to
        // the previous lo + position % (span + 1) computed in DType: the
        // modulo still happens in size_t and step <= span, so lo + step <= hi.
        using U = std::make_unsigned_t<DType>;
        if (!(hi > lo)) {
            return lo;
        }
        const U span = static_cast<U>(static_cast<U>(hi) - static_cast<U>(lo));
        const size_t modulus = static_cast<size_t>(span) + 1u;
        if (modulus == 0u) {
            return lo;  // defensive: unreachable, the span guard rejects it
        }
        const U step = static_cast<U>(position % modulus);
        return static_cast<DType>(static_cast<U>(static_cast<U>(lo) + step));
    } else if constexpr (std::is_same_v<DType, std::complex<double>>) {
        const double ramp = (n <= 1)
            ? lo.real()
            : lo.real() + (hi.real() - lo.real()) * (static_cast<double>(position) / static_cast<double>(n - 1));
        return DType(ramp, ramp);
    }
}

// E2-B: the extrema of the DECLARED FILL DOMAIN, not of the C++ type. lo/hi
// are the effective endpoints the caller already converted into DType, so this
// is per fill site by construction.
template <typename DType>
DType enhancedExtremeValue(DType lo, DType hi, size_t index) {
    return (index % 2 == 0) ? lo : hi;
}

template <typename DType>
DType enhancedMidValue(DType lo, DType hi) {
    if constexpr (std::is_same_v<DType, std::complex<double>>) {
        return DType((lo.real() + hi.real()) / 2.0, (lo.imag() + hi.imag()) / 2.0);
    } else if constexpr (std::is_integral_v<DType>) {
        // E2-A.1: same widened-unsigned treatment as the ramp. For hi >= lo
        // (the only ordering the validator admits) span/2 == (hi - lo) / 2,
        // so the midpoint is bit-identical to the previous computation.
        using U = std::make_unsigned_t<DType>;
        const U span = static_cast<U>(static_cast<U>(hi) - static_cast<U>(lo));
        return static_cast<DType>(
            static_cast<U>(static_cast<U>(lo) + static_cast<U>(span / U(2))));
    } else {
        return static_cast<DType>(lo + (hi - lo) / 2);
    }
}

// E2-B: the UPPER extreme of the declared fill domain. For an integral site
// this is provably outside the random base: fillRand's integral branch computes
// rand() % (hi - lo) + lo, which is hi-EXCLUSIVE, so x[k] = hi is a
// deterministic structural difference against the same random base. For a
// floating site hi is reachable only when rand() == RAND_MAX.
template <typename DType>
DType enhancedSpikeValue(DType hi) {
    return hi;
}

template <typename DType>
DType enhancedFromDouble(double value) {
    if constexpr (std::is_same_v<DType, std::complex<double>>) {
        return DType(value, 0.0);
    } else {
        return static_cast<DType>(value);
    }
}

// Random fill for the pattern core. fillRand's complex<double> branch is
// written for DOUBLE endpoints (it initializes `const double real` from
// max/min), so it is not instantiable with complex endpoints; complex
// containers are therefore filled through the double endpoints, which is
// exactly what the pre-E2-A call sites did. fillRand itself is shared with the
// normal (non-enhanced) correctness runs and stays untouched.
template <typename T, typename DType>
void enhancedFillRandom(T &x, DType lo, DType hi) {
    if constexpr (std::is_same_v<DType, std::complex<double>>) {
        fillRand(x, lo.real(), hi.real());
    } else {
        fillRand(x, lo, hi);
    }
}

// Shared pattern core. BOTH fill paths (compile defines and
// ENHANCED_RUNTIME_FILL) call exactly this function with endpoints already
// converted to the container's element type, so the two paths cannot diverge.
template <typename T, typename DType>
void enhancedFillPatternTyped(T &x, DType lo, DType hi, int pattern, size_t param_k) {
    const size_t n = x.size();

    if (n == 0) {
        return;
    }

    const size_t k = param_k % n;  // Python validates; modulo as a backstop

    // E2-A.1: the patterns that READ the range (everything except all_zeros
    // and explicit_values, which ignore lo/hi entirely - see
    // capabilities.PATTERN_PARAM_RELEVANCE; E2-B moved extreme_values INTO this
    // set because it now uses the domain endpoints) must not run on a span
    // the element type cannot express: the integral fillRand branch would
    // compute rand() % (max - min) on an overflowed difference, and the
    // float/double ramps would produce a deterministic Inf/NaN. validate_spec
    // rejects such a spec upstream; if one reaches the harness anyway, stop
    // with a diagnostic rather than execute undefined behaviour.
    const bool patternReadsRange = !(pattern == 1 || pattern == 10);
    if (patternReadsRange && !enhancedRangeSpanIsSafe<DType>(lo, hi)) {
        enhancedFillAbort(
            "value_range span is not representable in the fill container "
            "element type (integral: hi-lo and span+1 must fit; floating: hi-lo "
            "must stay finite). Such a spec is rejected by "
            "thesis/enhanced_tests/specs.py::validate_spec and must never reach "
            "the harness; refusing to execute undefined behaviour",
            nullptr);
    }

    // fillRand's integral branch computes rand() % (max - min): a degenerate
    // single-point range would be a modulo by zero, i.e. undefined behaviour.
    // A range [c, c] admits exactly one value, so fill it directly. This is a
    // UB guard, not a range policy — no value is clipped or reinterpreted.
    bool degenerateIntegralRange = false;
    if constexpr (std::is_integral_v<DType>) {
        degenerateIntegralRange = (lo == hi);
    }

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
        case 6:  // extreme_values: alternates the effective domain endpoints
            for (size_t i = 0; i < n; i += 1) x[i] = enhancedExtremeValue<DType>(lo, hi, i);
            break;
        case 7:  // duplicate_at(k): random, then duplicate neighbor value
            if (degenerateIntegralRange) {
                for (size_t i = 0; i < n; i += 1) x[i] = lo;
            } else {
                enhancedFillRandom(x, lo, hi);
            }
            x[k] = x[(k + 1) % n];
            break;
        case 8:  // sorted_except_one(k): ascending, then one swap
            for (size_t i = 0; i < n; i += 1) x[i] = enhancedRampValue<DType>(lo, hi, i, n, false);
            std::swap(x[k], x[(k + 1) % n]);
            break;
        case 9:  // spike_at(k): random in original range, one huge outlier
            if (degenerateIntegralRange) {
                for (size_t i = 0; i < n; i += 1) x[i] = lo;
            } else {
                enhancedFillRandom(x, lo, hi);
            }
            x[k] = enhancedSpikeValue<DType>(hi);
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
            if (degenerateIntegralRange) {
                for (size_t i = 0; i < n; i += 1) x[i] = lo;
            } else {
                enhancedFillRandom(x, lo, hi);
            }
            break;
    }
}

// Define-path entry point. Deduces the pattern value type from the CONTAINER
// (not from the lo/hi literals) and converts the endpoints into it, then calls
// the shared core.
template <typename T, typename SrcType>
void enhancedFillPattern(T &x, SrcType lo, SrcType hi, int pattern, size_t param_k) {
    using VType = typename T::value_type;
    enhancedFillPatternTyped<T, VType>(x,
                                       enhancedRangeEndpoint<VType>(lo),
                                       enhancedRangeEndpoint<VType>(hi),
                                       pattern, param_k);
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

// Superseded by the shared enhancedRangeEndpoint (E2-A) and kept only so the
// documented conversion contract has one named home; both paths now use
// enhancedRangeEndpoint, which generalizes this to non-double sources.
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

template <typename T, typename SrcType>
void enhancedRuntimeFill(T &x, SrcType lo_arg, SrcType hi_arg) {
    const EnhancedRuntimeFillConfig &config = enhancedRuntimeFillConfig();

    // E2-A: the value type is the CONTAINER's element type, exactly as in the
    // define path, and both paths convert their endpoints with the same
    // enhancedRangeEndpoint helper (truncate-then-saturate for integral
    // targets). A spec's ENHANCED_FILL_RANGE_LO/HI override replaces the call
    // site's endpoints before that conversion.
    using DType = typename T::value_type;

    DType lo = enhancedRangeEndpoint<DType>(lo_arg);
    DType hi = enhancedRangeEndpoint<DType>(hi_arg);

    if (config.has_range) {
        lo = enhancedRangeEndpoint<DType>(config.lo);
        hi = enhancedRangeEndpoint<DType>(config.hi);
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

    // shared body with the define path: BOTH call enhancedFillPatternTyped
    // with endpoints already in the container's element type, therefore an
    // identical rand() call sequence per pattern — the equivalence-critical
    // property (one extra rand() call would shift ALL subsequent inputs;
    // fillRand draws from unseeded, deterministic rand())
    enhancedFillPatternTyped<T, DType>(x, lo, hi, config.pattern, config.k);
}

#define ENHANCED_FILL(x, lo, hi) enhancedRuntimeFill((x), (lo), (hi))

#elif defined(ENHANCED_FILL_PATTERN)
#if defined(ENHANCED_FILL_LO) && defined(ENHANCED_FILL_HI)
// E2-A.1: the range override is carried to enhancedRangeEndpoint as a DOUBLE,
// never pre-cast to the call site literal type. The old
// (decltype(lo))(ENHANCED_FILL_LO) performed the floating->integral conversion
// ITSELF at every call site whose literals are integral (e.g.
// ENHANCED_FILL(v, 0, 100) on a vector<int>), so an out-of-range spec value was
// undefined behaviour BEFORE the safe endpoint helper ever saw it. double is
// the type spec_defines() emits and the widest source the helper handles, so
// both paths now perform exactly one conversion, in one place. For every range
// the validator admits this is value-identical to the old pre-cast: no fill
// site in the suite pairs integral call-site literals with a floating
// container, and for integral containers truncate-then-saturate reproduces the
// constant-folded cast exactly.
#define ENHANCED_FILL(x, lo, hi) \
    enhancedFillPattern((x), (double)(ENHANCED_FILL_LO), \
                        (double)(ENHANCED_FILL_HI), (ENHANCED_FILL_PATTERN), \
                        (size_t)(ENHANCED_FILL_PARAM_K))
#else
#define ENHANCED_FILL(x, lo, hi) \
    enhancedFillPattern((x), (lo), (hi), (ENHANCED_FILL_PATTERN), \
                        (size_t)(ENHANCED_FILL_PARAM_K))
#endif
#else
#define ENHANCED_FILL(x, lo, hi) fillRand((x), (lo), (hi))
#endif
