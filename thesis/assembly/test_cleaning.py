"""Tests for thesis/assembly/cleaning.py and assemble_sources.py.

Run:
    python thesis/assembly/test_cleaning.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.assembly import cleaning
from thesis.assembly.assemble_sources import assemble_content, patch_signature_line


PROMPT = """struct Point {
\tdouble x, y;
};

double distance(Point const& p1, Point const& p2) {
\treturn std::sqrt(std::pow(p2.x-p1.x, 2) + std::pow(p2.y-p1.y, 2));
}

/* Return the distance between the closest two points in the vector points.
   Example:

   input: [{2, 3}, {12, 30}, {40, 50}, {5, 1}, {12, 10}, {3, 4}]
   output: 1.41421
*/
double closestPair(std::vector<Point> const& points) {"""

BODY = """\tdouble min = std::numeric_limits<double>::max();
\tfor (size_t i = 0; i < points.size(); i++) {
\t\tfor (size_t j = i+1; j < points.size(); j++) {
\t\t\tmin = std::min(min, distance(points[i], points[j]));
\t\t}
\t}
\treturn min;
}"""


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "ok" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        raise AssertionError(name)


def assemble(raw_text: str) -> tuple[str, cleaning.AssemblyCleaningResult]:
    result = cleaning.clean_for_assembly(PROMPT, raw_text)
    content = assemble_content(PROMPT, result)
    result.metadata.braces_balanced = cleaning.braces_balanced(content)
    return content, result


def test_plain_body() -> None:
    print("plain body continuation (intended format)")
    content, result = assemble(BODY)
    check("no fence detected", not result.metadata.used_fence)
    check("signature not duplicated", not result.metadata.signature_found_in_output)
    check("NO_INLINE patched", "double NO_INLINE closestPair" in content)
    check("braces balanced", result.metadata.braces_balanced)
    check("body present", "std::numeric_limits<double>::max()" in content)


def test_fenced_full_function() -> None:
    print("fenced response repeating the full function")
    raw = (
        "Here is the implementation:\n\n```cpp\n"
        "double closestPair(std::vector<Point> const& points) {\n"
        + BODY
        + "\n```\n\nThis uses a brute-force O(n^2) approach."
    )
    content, result = assemble(raw)
    check("fence used", result.metadata.used_fence)
    check("signature deduplicated", result.metadata.signature_found_in_output)
    check("only one definition", content.count("closestPair(") == 1)
    check("braces balanced", result.metadata.braces_balanced)


def test_full_prompt_echo_with_includes() -> None:
    print("response echoing prompt, with includes and a new helper")
    raw = (
        "#include <vector>\n#include <cmath>\n#include <limits>\n\n"
        "struct Point {\n\tdouble x, y;\n};\n\n"
        "static double dist2(Point const& a, Point const& b) {\n"
        "\treturn (a.x-b.x)*(a.x-b.x) + (a.y-b.y)*(a.y-b.y);\n}\n\n"
        "double closestPair(std::vector<Point> const& points) {\n" + BODY
    )
    content, result = assemble(raw)
    check("signature deduplicated", result.metadata.signature_found_in_output)
    check(
        "prompt struct dropped",
        result.metadata.dropped_duplicated_prompt_lines >= 2,
        f"dropped={result.metadata.dropped_duplicated_prompt_lines}",
    )
    check("new helper kept", "dist2" in content)
    check(
        "helper placed before signature",
        content.index("dist2") < content.index("NO_INLINE closestPair"),
    )
    check("includes relocated to top", content.startswith("#include <vector>"))
    check("struct Point defined once", content.count("struct Point") == 1)
    check("braces balanced", result.metadata.braces_balanced)


def test_body_with_leading_includes() -> None:
    print("body continuation with leading includes (would break compilation)")
    raw = "#include <limits>\n#include <algorithm>\n" + BODY
    content, result = assemble(raw)
    check("includes relocated", len(result.metadata.relocated_includes) == 2)
    check("include not inside function", "{\n#include" not in content)
    check("braces balanced", result.metadata.braces_balanced)


def test_unfenced_with_prose() -> None:
    print("unfenced response with leading and trailing prose")
    raw = (
        "Sure! The most straightforward approach is a nested loop.\n"
        "It runs in O(n^2) time.\n\n" + BODY + "\n\n"
        "Let me know if you would like an O(n log n) version."
    )
    content, result = assemble(raw)
    check("leading prose dropped", result.metadata.dropped_leading_lines >= 2)
    check("trailing prose dropped", result.metadata.dropped_trailing_lines >= 1)
    check("no prose in file", "Let me know" not in content and "Sure!" not in content)
    check("braces balanced", result.metadata.braces_balanced)


def test_multiple_fences_takes_longest() -> None:
    print("multiple fences: longest block wins")
    raw = (
        "Usage example:\n```cpp\nclosestPair(points);\n```\n"
        "Implementation:\n```cpp\n" + BODY + "\n```"
    )
    content, result = assemble(raw)
    check("two fences seen", result.metadata.fence_count == 2)
    check("implementation chosen", "std::numeric_limits" in content)
    check("usage example not chosen", "closestPair(points);" not in content)


def test_truncated_output_flagged() -> None:
    print("truncated output flagged by brace check")
    truncated = BODY.rsplit("}", 2)[0]  # cut the closing braces
    content, result = assemble(truncated)
    check("braces flagged unbalanced", not result.metadata.braces_balanced)


def test_renamed_params_suspect() -> None:
    print("full function with renamed params is flagged as suspect")
    raw = (
        "double closestPair(std::vector<Point> const& pts) {\n"
        "\treturn 0.0;\n}"
    )
    content, result = assemble(raw)
    check("signature not matched", not result.metadata.signature_found_in_output)
    check("flagged suspect", result.metadata.signature_suspect)


def test_patch_signature() -> None:
    print("NO_INLINE patching mirrors upstream")
    patched = patch_signature_line("double closestPair(std::vector<Point> const& points) {")
    check(
        "NO_INLINE after return type",
        patched.startswith("double NO_INLINE closestPair("),
    )


def main() -> None:
    tests = [
        test_plain_body,
        test_fenced_full_function,
        test_full_prompt_echo_with_includes,
        test_body_with_leading_includes,
        test_unfenced_with_prose,
        test_multiple_fences_takes_longest,
        test_truncated_output_flagged,
        test_renamed_params_suspect,
        test_patch_signature,
    ]

    for test in tests:
        test()
        print()

    print(f"All {len(tests)} cleaning/assembly tests passed.")


if __name__ == "__main__":
    main()
