#pragma once
#include <vector>
#include <algorithm>

/* Find the set of points that defined the smallest convex polygon that contains all the points in the vector points. Store the result in `hull`.
   Example:

   input: [{0, 3}, {1, 1}, {2, 2}, {4, 4}, {0, 0}, {1, 2}, {3, 1}, {3, 3}]
   output: [{0, 3}, {4, 4}, {3, 1}, {0, 0}]
*/
void NO_INLINE correctConvexHull(std::vector<Point> const& points, std::vector<Point> &hull) {
    // Wave 2B (frozen I11 family semantics): the hull is a function of the
    // DISTINCT point set — duplicates in the input are irrelevant, and every
    // hull vertex appears exactly once in the result. The historical code
    // guarded on points.size() and could return a coincident point TWICE
    // (all-identical input -> a 2-entry "hull"). The result is graded as a
    // vertex SET (the validator sorts both sides), so deduplication changes
    // no non-degenerate verdict.
    std::vector<Point> pointsSorted = points;

    std::sort(pointsSorted.begin(), pointsSorted.end(), [](Point const& a, Point const& b) {
        return a.x < b.x || (a.x == b.x && a.y < b.y);
    });
    pointsSorted.erase(std::unique(pointsSorted.begin(), pointsSorted.end(),
                                   [](Point const& a, Point const& b) {
                                       return a.x == b.x && a.y == b.y;
                                   }),
                       pointsSorted.end());

    // Fewer than three DISTINCT points: the hull is those distinct points
    // themselves (one point -> that point once; two points -> the segment's
    // two endpoints).
    if (pointsSorted.size() < 3)   {
        hull = pointsSorted;
        return;
    }

    auto CrossProduct = [](Point const& a, Point const& b, Point const& c) {
        return (c.x - a.x) * (b.y - a.y) - (c.y - a.y) * (b.x - a.x) > 0;
    };

    std::vector<Point> upperHull;
    std::vector<Point> lowerHull;
    upperHull.push_back(pointsSorted[0]);
    upperHull.push_back(pointsSorted[1]);
    lowerHull.push_back(pointsSorted[pointsSorted.size() - 1]);
    lowerHull.push_back(pointsSorted[pointsSorted.size() - 2]);

    for (size_t i = 2; i < pointsSorted.size(); i++) {
        while (upperHull.size() > 1
               && !CrossProduct(upperHull[upperHull.size() - 2],
                                upperHull[upperHull.size() - 1],
                                pointsSorted[i])) {
            upperHull.pop_back();
        }
        upperHull.push_back(pointsSorted[i]);

        while (lowerHull.size() > 1
               && !CrossProduct(lowerHull[lowerHull.size() - 2],
                                lowerHull[lowerHull.size() - 1],
                                pointsSorted[pointsSorted.size() - i - 1])) {
            lowerHull.pop_back();
        }
        lowerHull.push_back(pointsSorted[pointsSorted.size() - i - 1]);
    }
    upperHull.insert(upperHull.end(), lowerHull.begin()+1, lowerHull.end()-1);

    hull = upperHull;
    return;
}
