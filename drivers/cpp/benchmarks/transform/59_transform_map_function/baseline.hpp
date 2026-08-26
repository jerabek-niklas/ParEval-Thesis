#pragma once

//bool isPowerOfTwo(int);

#if defined(USE_CUDA) || defined(USE_HIP)
/* THIS IS FOR THE CUDA/HIP SAMPLES WHERE CALLING THE __device__ FUNCTION WOULD BE AN ERROR ON CPU */
bool isPowerOfTwoHOST(int x) {
    return (x > 0) && !(x & (x - 1));
}
#endif

namespace pareval_harness {

// Trusted reference predicate for the oracle below. The expected result must
// NEVER be computed by the candidate's own isPowerOfTwo: before this fix the
// CPU oracle called the candidate's definition (the declaration above is
// commented out), making the reference candidate-dependent — the defect the
// domain table marks as "oracle fix REQUIRED". Spelling: the prompt's
// short-circuit predicate, total for every int (x > 0 fails first for
// x <= 0, so x - 1 is never evaluated at INT_MIN).
inline bool referenceIsPowerOfTwo(int x) {
    return (x > 0) && !(x & (x - 1));
}

}  // namespace pareval_harness

/* Apply the isPowerOfTwo function to every value in x and store the results in mask.
   Example:

   input: [8, 0, 9, 7, 15, 64, 3]
   output: [true, false, false, false, false, true, false]
*/
void NO_INLINE correctMapPowersOfTwo(std::vector<int> const& x, std::vector<bool> &mask) {
    for (int i = 0; i < x.size(); i++) {
        #if defined(USE_CUDA) || defined(USE_HIP)
        mask[i] = isPowerOfTwoHOST(x[i]);
        #else
        mask[i] = pareval_harness::referenceIsPowerOfTwo(x[i]);
        #endif
    }
}