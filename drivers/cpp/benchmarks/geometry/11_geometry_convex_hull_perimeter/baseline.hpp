#pragma once
#include <vector>
#include <algorithm>
#include <cmath>

/* Return the perimeter of the smallest convex polygon that contains all the points in the vector points.
   Example:

   input: [{0, 3}, {1, 1}, {2, 2}, {4, 4}, {0, 0}, {1, 2}, {3, 1}, {3, 3}]
   output: 13.4477
*/
double NO_INLINE correctConvexHullPerimeter(std::vector<Point> const& points) {
    // Wave 2B (frozen I11 family semantics): the perimeter is a function of
    // the DISTINCT point set — duplicates are irrelevant; one distinct point
    // (or an empty vector) -> 0; two or more distinct collinear points ->
    // twice the length of the spanning segment (2 * extent). The historical
    // code guarded on points.size() and was NOT set-invariant: {(0,0),(3,4)}
    // -> 0 but {(0,0),(0,0),(3,4)} -> 10 for the SAME point set (audit
    // BL-02, class F).
    auto dist = [](Point const& p1, Point const& p2) {
        return sqrt(pow(p2.x-p1.x, 2) + pow(p2.y-p1.y, 2));
    };

    std::vector<Point> pointsSorted = points;

    std::sort(pointsSorted.begin(), pointsSorted.end(), [](Point const& a, Point const& b) {
        return a.x < b.x || (a.x == b.x && a.y < b.y);
    });
    pointsSorted.erase(std::unique(pointsSorted.begin(), pointsSorted.end(),
                                   [](Point const& a, Point const& b) {
                                       return a.x == b.x && a.y == b.y;
                                   }),
                       pointsSorted.end());

    if (pointsSorted.size() <= 1) {
        // empty input or all points coincident
        return 0;
    }
    if (pointsSorted.size() == 2) {
        // degenerate segment: closed boundary = there and back
        return 2.0 * dist(pointsSorted[0], pointsSorted[1]);
    }
    // (>= 3 distinct collinear points need no special branch: the monotone
    // chain below reduces them to the two extremes and the closing loop then
    // yields exactly 2 * extent.)

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

    double perimeter = 0;
    for (size_t i = 0; i < upperHull.size() - 1; i++) {
        perimeter += dist(upperHull[i], upperHull[i+1]);
    }
    perimeter += dist(upperHull[0], upperHull[upperHull.size() - 1]);

    return perimeter;
}
