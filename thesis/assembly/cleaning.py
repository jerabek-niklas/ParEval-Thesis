"""Cleaning of LLM-generated C++ code for assembly into compilable sources.

This is the single authoritative cleaning implementation. The generation
stage uses extract_code() for the informational cleaned_code field; the
assembly stage (assemble_sources.py) uses clean_for_assembly(), which is a
pure function of (prompt_text, raw_text) and can therefore be re-run at any
time without repeating API calls.

Pipeline:
    1. extract_code        strip Markdown fences / surrounding prose
    2. split at signature  if the model repeated the prompt's function
                           signature, keep new helper code before it and the
                           body after it; drop lines that duplicate prompt
    3. relocate includes   move top-level #include/using lines above the
                           prompt so they never end up inside a function
    4. brace check         flag obviously unbalanced output

Every transformation is recorded in CleaningMetadata so cleaning decisions
are auditable in the thesis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


CODE_LINE_PATTERN = re.compile(
    r"^\s*(#\s*include|#\s*define|#\s*pragma|//|/\*|template\b|using\b|typedef\b|"
    r"namespace\b|struct\b|class\b|enum\b|inline\b|static\b|constexpr\b|extern\b|"
    r"void\b|int\b|long\b|short\b|float\b|double\b|bool\b|char\b|auto\b|size_t\b|"
    r"unsigned\b|signed\b|std::|"
    r"for\b|if\b|while\b|do\b|switch\b|return\b|else\b)"
)

INCLUDE_OR_USING_PATTERN = re.compile(r"^\s*(#\s*include\b|using\s+namespace\b)")


def is_prose_line(line: str) -> bool:
    """Conservative prose detection for unfenced responses.

    A line only counts as prose (and may be dropped from the edges of the
    response) if nothing about it looks like code: no statement or brace
    characters, not indented (code bodies are), and no code-keyword start.
    When in doubt the line is kept — wrongly kept prose produces an obvious
    compile error, wrongly dropped code silently corrupts the sample.
    """
    stripped = line.strip()

    if not stripped:
        return False

    if line.startswith((" ", "\t")):
        return False

    if any(char in stripped for char in (";", "{", "}", "#")):
        return False

    return not CODE_LINE_PATTERN.match(line)


@dataclass
class CleaningMetadata:
    used_fence: bool = False
    fence_count: int = 0
    dropped_leading_lines: int = 0
    dropped_trailing_lines: int = 0
    signature_found_in_output: bool = False
    dropped_duplicated_prompt_lines: int = 0
    kept_pre_signature_lines: int = 0
    relocated_includes: list[str] = field(default_factory=list)
    braces_balanced: bool = True
    auto_closed: bool = False
    signature_suspect: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssemblyCleaningResult:
    body: str
    pre_signature_code: str
    relocated_includes: list[str]
    metadata: CleaningMetadata


# ---------------------------------------------------------------------------
# Step 1: fence / prose extraction
# ---------------------------------------------------------------------------

FENCE_PATTERN = re.compile(
    r"```(?:cpp|c\+\+|cxx|C\+\+|c)?\s*\n?(.*?)```",
    flags=re.DOTALL | re.IGNORECASE,
)


def extract_code(raw_text: str, metadata: CleaningMetadata | None = None) -> str:
    """Extract the code part from a raw model response.

    Fenced responses: take the longest fenced block (models sometimes emit a
    short usage example next to the actual code; the implementation is the
    longest block in practice).
    Unfenced responses: drop leading prose lines until the first code-like
    line and trailing prose after the last closing brace.
    """
    if metadata is None:
        metadata = CleaningMetadata()

    fences = FENCE_PATTERN.findall(raw_text)
    metadata.fence_count = len(fences)

    if fences:
        metadata.used_fence = True
        return max(fences, key=len).strip()

    lines = raw_text.splitlines()

    # leading prose: drop lines only while they are clearly prose
    start = 0
    while start < len(lines) and (
        not lines[start].strip() or is_prose_line(lines[start])
    ):
        if lines[start].strip():
            metadata.dropped_leading_lines += 1
        start += 1

    if start == len(lines):
        # everything looked like prose; keep the input rather than destroy it
        return raw_text.strip()

    # trailing prose: same rule from the bottom
    end = len(lines)
    while end > start and (
        not lines[end - 1].strip() or is_prose_line(lines[end - 1])
    ):
        if lines[end - 1].strip():
            metadata.dropped_trailing_lines += 1
        end -= 1

    return "\n".join(lines[start:end]).strip()


# ---------------------------------------------------------------------------
# Step 2: signature deduplication
# ---------------------------------------------------------------------------


def get_signature_line(prompt_text: str) -> str:
    """ParEval prompts end with the function signature line ending in '{'."""
    for line in reversed(prompt_text.splitlines()):
        if line.strip():
            return line

    raise ValueError("Prompt is empty; cannot determine signature line.")


def get_function_name(signature_line: str) -> str | None:
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", signature_line)
    return match.group(1) if match else None


def find_whitespace_insensitive(haystack: str, needle: str) -> tuple[int, int]:
    """Find needle in haystack ignoring all whitespace differences.

    Returns (start, end) indices into haystack, or (-1, -1).
    """
    needle_key = "".join(needle.split())

    if not needle_key:
        return -1, -1

    positions: list[int] = []  # haystack index of each non-ws char
    chars: list[str] = []

    for index, char in enumerate(haystack):
        if not char.isspace():
            positions.append(index)
            chars.append(char)

    compact = "".join(chars)
    found = compact.find(needle_key)

    if found == -1:
        return -1, -1

    start = positions[found]
    end = positions[found + len(needle_key) - 1] + 1

    return start, end


def normalize_line(line: str) -> str:
    return "".join(line.split())


def split_at_signature(
    prompt_text: str,
    code: str,
    metadata: CleaningMetadata,
) -> tuple[str, str]:
    """Split model output at a repeated prompt signature.

    Returns (pre_signature_code, body).
    - If the model repeated the signature, body is everything after it.
      Lines before it that duplicate prompt lines (struct defs, helpers,
      comments the model echoed) are dropped; genuinely new lines (new
      helper functions, forward declarations) are kept as pre-signature
      code, to be placed between the prompt and the signature line.
    - If the signature is not found, the output is treated as a plain body
      continuation and returned unchanged.
    """
    signature = get_signature_line(prompt_text)
    start, end = find_whitespace_insensitive(code, signature)

    if start == -1:
        # Heuristic warning: output may still contain a (modified) full
        # function definition, e.g. with renamed parameters, which would
        # produce a duplicate definition after assembly.
        function_name = get_function_name(signature)

        if function_name:
            definition_pattern = re.compile(
                rf"^\s*[A-Za-z_][\w:<>,&*\s]*\b{re.escape(function_name)}\s*\(",
                flags=re.MULTILINE,
            )
            if definition_pattern.search(code):
                metadata.signature_suspect = True

        return "", code

    metadata.signature_found_in_output = True

    pre_part = code[:start]
    body = code[end:]

    prompt_line_keys = {
        normalize_line(line) for line in prompt_text.splitlines() if line.strip()
    }

    kept_lines: list[str] = []
    dropped = 0
    previous_dropped = False

    for line in pre_part.splitlines():
        if not line.strip():
            continue

        key = normalize_line(line)
        is_match = key in prompt_line_keys
        # Trivial lines like "}" or "};" match prompt lines by accident.
        # They are only treated as prompt duplicates when they continue a
        # block that is already being dropped; otherwise they belong to new
        # model code (e.g. the closing brace of a new helper function).
        is_trivial = len(key) <= 2

        if is_match and (not is_trivial or previous_dropped):
            dropped += 1
            previous_dropped = True
        else:
            kept_lines.append(line)
            previous_dropped = False

    metadata.dropped_duplicated_prompt_lines = dropped
    metadata.kept_pre_signature_lines = len(kept_lines)

    return "\n".join(kept_lines), body.lstrip("\n")


# ---------------------------------------------------------------------------
# Step 3: include relocation
# ---------------------------------------------------------------------------


def relocate_includes(code: str, metadata: CleaningMetadata) -> tuple[list[str], str]:
    """Pull top-level #include / using-namespace lines out of the code.

    Returns (includes, remaining_code). Assembly places includes above the
    prompt so a body continuation never ends up with an #include inside the
    function.
    """
    includes: list[str] = []
    remaining: list[str] = []

    for line in code.splitlines():
        if INCLUDE_OR_USING_PATTERN.match(line):
            includes.append(line.strip())
        else:
            remaining.append(line)

    metadata.relocated_includes = includes

    return includes, "\n".join(remaining).strip("\n")


# ---------------------------------------------------------------------------
# Step 4: brace sanity check
# ---------------------------------------------------------------------------


def brace_balance(text: str) -> int | None:
    """Return the final brace balance of the source text, or None.

    Ignores braces inside string/char literals and comments. Returns None
    if the balance ever goes negative (a closing brace without an opener);
    otherwise the number of unclosed braces (0 == balanced). Intended to be
    called on the fully assembled file.
    """
    balance = 0
    index = 0
    length = len(text)
    in_line_comment = in_block_comment = in_string = in_char = False

    while index < length:
        char = text[index]
        nxt = text[index + 1] if index + 1 < length else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
        elif in_block_comment:
            if char == "*" and nxt == "/":
                in_block_comment = False
                index += 1
        elif in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif in_char:
            if char == "\\":
                index += 1
            elif char == "'":
                in_char = False
        else:
            if char == "/" and nxt == "/":
                in_line_comment = True
                index += 1
            elif char == "/" and nxt == "*":
                in_block_comment = True
                index += 1
            elif char == '"':
                in_string = True
            elif char == "'":
                in_char = True
            elif char == "{":
                balance += 1
            elif char == "}":
                balance -= 1
                if balance < 0:
                    return None

        index += 1

    return balance


def braces_balanced(text: str) -> bool:
    return brace_balance(text) == 0


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def clean_for_assembly(prompt_text: str, raw_text: str) -> AssemblyCleaningResult:
    metadata = CleaningMetadata()

    code = extract_code(raw_text, metadata)
    pre_signature_code, body = split_at_signature(prompt_text, code, metadata)

    pre_includes, pre_signature_code = (
        relocate_includes(pre_signature_code, CleaningMetadata())
        if pre_signature_code
        else ([], "")
    )
    body_includes, body = relocate_includes(body, metadata)

    includes = list(dict.fromkeys(pre_includes + body_includes))
    metadata.relocated_includes = includes

    # metadata.braces_balanced is set by the assembler on the final content.
    return AssemblyCleaningResult(
        body=body,
        pre_signature_code=pre_signature_code,
        relocated_includes=includes,
        metadata=metadata,
    )
