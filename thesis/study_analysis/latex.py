"""LaTeX rendering of the study tables (booktabs; longtable for long tables)
and the recommended preamble.

The thesis includes these files verbatim, so the output must compile with
nothing but the packages of preamble_tex() and must never depend on the
content of a cell: every text cell is escaped (& % $ # _ { } ~ ^ \\ < > |),
numeric cells are rendered from the raw estimate facts here (thousands
separator {,}, minus $-$, percentages with one decimal, CIs as [lo, hi] - a
cell starting with "[" is braced so it can never be read as the optional
argument of a preceding \\\\; a zero-width interval carries
\\textsuperscript{\\dag}, the mark of the DEGENERATE_CI footnote). Only
booktabs rules are used (\\toprule \\midrule \\cmidrule \\bottomrule
\\addlinespace), the column spec comes from each column's align, and every row
has exactly one & per column separator (group headers use \\multicolumn
spans).

Ratio cells (rate / diff / mean) are set on two lines - the value above
"(n/N)" - in a nested core-LaTeX tabular, which halves the column width
(CSV keeps "value (n/N)" on one line). Tables whose body exceeds
tables.LONGTABLE_ROWS rendered text lines use longtable (repeated header,
continuation foot) - "rows" is read as rendered lines because a two-line
row is as tall as two plain rows (documented reading of the spec's "> 40
rows"); all others a table float. Both carry the caption and
\\label{tab:study_analysis_001:<id>}; a footnote whose mark appears nowhere
in the header or body (the pilot label of a single-block table, a
table-level statement) is anchored at the caption (\\caption[entry]{title +
mark}), so no footnote floats unattached. Long header labels are set on two
lines; text columns with a `width` wrap ragged-right in a \\parbox (breaks
allowed after _ + ; [ and every 16 characters of a long hex identity).
Tables with more than WIDE_COLUMNS columns (or the size hint) are set in
\\scriptsize with a reduced \\tabcolsep.

Page layout (LAYOUT, measured with the host pdflatex, MiKTeX pdfTeX 4.26,
11pt article with the preamble_tex() packages, on the tables built from the
dry-run estimates of the real study - 1,980 base cells, 4-5 digit n/N, the
longest real model ids - completed with the contract keys and addendum
estimates of real size): "portrait" = fits an A4 portrait text block of
16 cm x 24.7 cm; "landscape" = needs an A4 landscape page (text block
<= 25 cm x 15 cm) and fits there; a longtable continues over pages in either
orientation. T7a and T7b (and T7c) fit the landscape block as one float; T7b
and T9 also fit portrait; at 12pt T7b exceeds the landscape height by ~5 pt
and T9 the portrait block by ~10 pt (measured; reduce the notes font or use
11pt). To fit, the notes block is \\scriptsize and run in as one paragraph,
the population definitions and metric legends are cited by reference (full
text in the table's `definitions`, JSON form), "k excl." sits on a line of
its own, and tables.LATEX_HINTS set a \\scriptsize body (T7c) or force a
longtable (T12, whose notes then flow after it). The comment line of each
table file and preamble_tex() state the measured layout; the numbers of a cell
stay complete either way.

table_csv / table_json are re-exported from tables.py so that the three
renderings of a table are available from one module.
"""
from __future__ import annotations

import re
from collections import OrderedDict

from thesis.study_analysis import core
from thesis.study_analysis.tables import (CI_KINDS, DAGGER, LONGTABLE_ROWS, PILOT_BLOCK, PILOT_MARK,  # noqa: F401
                                          RATIO_KINDS, TABLE_IDS, cell_parts, cell_text, ci_parts, excluded_text,
                                          refuse, table_csv, table_json)

TEX_SPECIALS = OrderedDict([
    ("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
    ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
    ("<", r"\textless{}"), (">", r"\textgreater{}"), ("|", r"\textbar{}"), (DAGGER, r"\dag{}")])
PACKAGES = (r"\usepackage{booktabs}", r"\usepackage{longtable}")
WIDE_COLUMNS = 9
HEADER_SPLIT = 10                 # header labels longer than this go on two lines
WRAP_KINDS = ("text", "mapping")  # kinds that may be set in a p{width} column
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_MINUS = re.compile(r"(?<![\w.])-(?=\d)")
_HEX_RUN = re.compile(r"([0-9a-f]{16})(?=[0-9a-f]{8})")
DAG = r"\textsuperscript{\dag}"
# measured page layout per table (module docstring; B2_measure.py on the real study size, 11pt article); every
# table id is classified (a test checks it)
PORTRAIT = ("T1_inventory", "T7b_heldout_transitions", "T9_primary_tests", "T9b_primary_by_block", "T11_runtime",
            "T12c_iterations_to_clean")
LAYOUT = OrderedDict((t, "portrait" if t in PORTRAIT else "landscape") for t in TABLE_IDS)
LAYOUT_TEXT = OrderedDict([
    ("portrait", "fits an A4 portrait text block (16 cm x 24.7 cm; measured with pdflatex, 11pt article, on the "
                 "real study size)"),
    ("landscape", "needs an A4 landscape page (text block <= 25 cm x 15 cm, measured with pdflatex, 11pt article, on "
                  "the real study size): wrap the \\input in \\begin{landscape}...\\end{landscape} (pdflscape or "
                  "lscape)")])


def escape(text):
    """Escape arbitrary text for LaTeX text mode (single line)."""
    out = []
    for ch in str(text):
        if ch in "\r\n\t":
            out.append(" ")
        else:
            out.append(TEX_SPECIALS.get(ch, ch))
    return "".join(out)


def tex_number(text):
    """A rendered numeric cell: thousands separators -> {,}, minus -> $-$,
    the rest escaped; a leading "[" is protected by braces."""
    text = _MINUS.sub("\x01", _THOUSANDS.sub("\x00", text))
    text = escape(text).replace("\x00", "{,}").replace("\x01", "$-$")
    return "{%s}" % text if text.startswith("[") else text


def mark(symbol):
    """A footnote mark (the dagger of zero-width intervals is \\dag)."""
    return DAG if symbol == DAGGER else r"\textsuperscript{%s}" % escape(symbol)


def column_spec(column):
    """l / r / c; a wrapping column (width) is an l column whose cells are
    ragged-right \\parbox[t]{width} (core LaTeX - no array package needed,
    and the row-ending \\\\ stays outside the parbox group)."""
    if column.get("width"):
        if column["kind"] not in WRAP_KINDS or not re.match(r"^\d+(\.\d+)?(cm|mm|em|pt)$", column["width"]):
            refuse("bad wrap width %r for a %s column" % (column["width"], column["kind"]))
        return "l"
    if column["align"] not in ("l", "r", "c"):
        refuse("bad column alignment %r" % column["align"])
    return column["align"]


def _wrapped(tex, column):
    return r"\parbox[t]{%s}{\raggedright %s\strut}" % (column["width"], _breakable(tex))


def _breakable(tex):
    """Escaped text of a wrapping column: allow line breaks after _ + ; [ and
    every 16 characters of a long hex identity (sha256)."""
    tex = _HEX_RUN.sub(r"\1\\allowbreak{}", tex)
    return (tex.replace(r"\_", r"\_\allowbreak{}").replace("+", r"+\allowbreak{}")
            .replace(";", r";\allowbreak{}").replace("[", r"[\allowbreak{}"))


def cell_tex(value, column):
    """A cell; ratio cells (value + "(n/N)") are stacked on two lines with a
    nested core-LaTeX tabular, which halves the column width; wrapping text
    columns may break after + and ; ; a zero-width interval carries the dagger."""
    kind = column["kind"]
    if kind == "text":
        text = escape(cell_text(value, column))
        return _wrapped(text, column) if column.get("width") else text
    if kind == "block":
        text = escape(cell_text(value, column))
        return text + mark(PILOT_MARK) if value == PILOT_BLOCK else text
    if kind in RATIO_KINDS and value is not None:
        main, sub = cell_parts(value, column, sep=True, excl=False)
        parts = [tex_number(main), tex_number(sub)]
        excluded = excluded_text(value, sep=True)
        if excluded:                       # "k excl." on a line of its own keeps the column narrow
            parts.append(tex_number(excluded))
        return r"\begin{tabular}[t]{@{}%s@{}}%s\end{tabular}" % (column["align"], r"\\".join(parts))
    if kind in CI_KINDS:
        text, degenerate = ci_parts(value)
        return tex_number(text) + (DAG if degenerate else "")
    text = tex_number(cell_text(value, column, sep=True))
    return _wrapped(text, column) if (kind == "mapping" and column.get("width")) else text


def split_label(text, limit=None):
    """(first, second) line of a long header label, broken at the space /
    underscore / hyphen nearest the middle; None if short or unbreakable."""
    limit = HEADER_SPLIT if limit is None else limit
    if len(text) <= limit:
        return None
    breaks = [i for i, ch in enumerate(text) if ch == " " and 0 < i < len(text) - 1]
    if not breaks:                         # spaces first, then _ - /
        breaks = [i for i, ch in enumerate(text) if ch in "_-/" and 0 < i < len(text) - 1]
    if not breaks:
        return None
    middle = len(text) / 2.0
    i = min(breaks, key=lambda b: (abs(b - middle), b))
    return (text[:i], text[i + 1:]) if text[i] == " " else (text[:i + 1], text[i + 1:])


def label_tex(text, align="c"):
    parts = split_label(text)
    if parts is None:
        return escape(text)
    return r"\begin{tabular}[b]{@{}%s@{}}%s\\%s\end{tabular}" % (align, escape(parts[0]), escape(parts[1]))


def _header(column, text):
    align = "l" if column.get("width") else column["align"]
    return label_tex(text, align) + (mark(column["mark"]) if column.get("mark") else "")


def header_lines(columns):
    """One header row, or (if any column is grouped) a group row with
    \\multicolumn spans + \\cmidrule and a sub-header row. Long labels are set
    on two lines (nested tabular) so that headers do not dictate the width."""
    if not any("group" in c for c in columns):
        return [" & ".join(_header(c, c["header"]) for c in columns) + r" \\"]
    top, rules, i, n = [], [], 0, len(columns)
    while i < n:
        group = columns[i].get("group")
        j = i
        while group is not None and j + 1 < n and columns[j + 1].get("group") == group:
            j += 1
        if group is None:
            top.append("")
        else:
            label = label_tex(group) if j == i else escape(group)
            top.append(r"\multicolumn{%d}{c}{%s}" % (j - i + 1, label))
            rules.append(r"\cmidrule(lr){%d-%d}" % (i + 1, j + 1))
        i = j + 1
    bottom = [_header(c, c["sub"] if "group" in c else c["header"]) for c in columns]
    return [" & ".join(top) + r" \\", " ".join(rules), " & ".join(bottom) + r" \\"]


def body_lines(table):
    """Data rows; when the first (label) column repeats, a change of its
    value starts a visual group (\\addlinespace)."""
    columns = table["columns"]
    lines, previous = [], None
    first = columns[0]["key"]
    values = [row[first] for row in table["rows"]]
    grouped = columns[0]["kind"] in ("text", "block") and len(set(map(str, values))) < len(values)
    for index, row in enumerate(table["rows"]):
        if grouped and index and row[first] != previous:
            lines.append(r"\addlinespace")
        previous = row[first]
        lines.append(" & ".join(cell_tex(row[c["key"]], c) for c in columns) + r" \\")
    return lines


def _comment(text):
    return "% " + " ".join(str(text).split())


def notes_lines(table):
    """Population / unit, the CI statement, the notes and the definition
    references as ONE run-in paragraph (each note is a sentence starting with
    its subject; this keeps the block short enough for a landscape page) and
    one paragraph per footnote."""
    lines = [r"\textit{Population:} %s. \textit{Unit:} %s." % (escape(table["population"]), escape(table["unit"]))]
    if table.get("ci_note"):
        lines.append(r"\textit{CI:} %s." % escape(table["ci_note"]))
    lines += [escape(note if note.rstrip().endswith(".") else note + ".") for note in table["notes"]]
    if table.get("definitions"):
        lines.append(r"\textit{Definitions} (methodology%s; full text in the JSON form of this table): %s." % (
            " and addendum" if any(d["ref"][:1] == "X" for d in table["definitions"]) else "",
            escape("; ".join(d["ref"] for d in table["definitions"]))))
    lines[-1] += r"\par"                   # one run-in paragraph (the lines join with a space)
    lines += [mark(f["mark"]) + "~" + escape(f["text"]) + r"\par" for f in table["footnotes"]]
    return lines


def row_lines(table, row):
    """Text lines of one body row: a ratio cell takes two lines (three with
    'k excl.'), a plain row one."""
    lines = 1
    for c in table["columns"]:
        value = row[c["key"]]
        if c["kind"] in RATIO_KINDS and value is not None:
            lines = max(lines, 3 if excluded_text(value) else 2)
    return lines


def rendered_lines(table):
    """Text lines of the body (row_lines summed), so a 27-row repair table is
    as tall as a 54-row plain table."""
    return sum(row_lines(table, row) for row in table["rows"])


def is_long(table):
    """A longtable: more than LONGTABLE_ROWS rendered body lines, or the
    table's hint (tables.LATEX_HINTS: a float that would not fit a page)."""
    return rendered_lines(table) > LONGTABLE_ROWS or bool((table.get("latex") or {}).get("longtable"))


def caption_tex(table, anchored_tex):
    """\\caption[list entry]{title + marks}: a footnote whose mark appears
    nowhere in the header or body (a table-level statement such as the pilot
    label of a single-block table) is anchored at the caption, so no footnote
    floats unattached."""
    title = escape(table["title"])
    loose = [f["mark"] for f in table["footnotes"] if mark(f["mark"]) not in anchored_tex]
    if not loose:
        return r"\caption{%s}" % title
    return r"\caption[%s]{%s%s}" % (title, title, "".join(mark(m) for m in loose)
                                    if DAGGER in loose else mark(",".join(loose)))


def layout_comment(table_id):
    layout = LAYOUT.get(table_id)
    if layout is None:
        return _comment("Layout: not measured for %s" % table_id)
    return _comment("Layout: %s." % LAYOUT_TEXT[layout])


def table_tex(table):
    """The LaTeX source of one table (UTF-8 bytes, LF)."""
    columns = table["columns"]
    if not columns:
        refuse("%s has no columns" % table["id"])
    spec = "".join(column_spec(c) for c in columns)
    n = len(columns)
    label = r"\label{tab:%s:%s}" % (core.ANALYSIS_ID, table["id"])
    if n > WIDE_COLUMNS or (table.get("latex") or {}).get("size") == "scriptsize":
        size = [r"\scriptsize", r"\setlength{\tabcolsep}{%s}" % ("2.5pt" if n > WIDE_COLUMNS + 2 else "3pt")]
    else:
        size = [r"\footnotesize", r"\setlength{\tabcolsep}{4pt}"]
    notes_size = r"\scriptsize"            # the notes block (measured: footnotesize does not fit a landscape page)
    head = header_lines(columns)
    caption = caption_tex(table, "\n".join(head + body_lines(table)))
    out = [_comment("Table %s of %s - generated by thesis/study_analysis/latex.py; do not edit by hand."
                    % (table["id"], core.ANALYSIS_ID)),
           _comment("Required packages: " + " ".join(PACKAGES) + " (full preamble: tables/preamble.tex)"),
           layout_comment(table["id"]),
           _comment("Population: %s | Unit: %s" % (table["population"], table["unit"]))]
    if is_long(table):
        out += [r"\begingroup"] + size + [r"\begin{longtable}{%s}" % spec, caption + label + r" \\", r"\toprule"]
        out += head + [r"\midrule", r"\endfirsthead",
                       r"\multicolumn{%d}{l}{\textit{(continued)}} \\" % n, r"\toprule"]
        out += head + [r"\midrule", r"\endhead", r"\midrule",
                       r"\multicolumn{%d}{r}{\textit{continued on next page}} \\" % n, r"\endfoot",
                       r"\bottomrule", r"\endlastfoot"]
        out += body_lines(table) + [r"\end{longtable}", r"\par", r"{%s\raggedright" % notes_size]
        out += notes_lines(table) + ["}", r"\endgroup"]
    else:
        out += [r"\begin{table}[htbp]", r"\centering", caption, label] + size
        out += [r"\begin{tabular}{%s}" % spec, r"\toprule"] + head + [r"\midrule"]
        out += body_lines(table) + [r"\bottomrule", r"\end{tabular}", r"\par\smallskip",
                                    r"\begin{minipage}{\linewidth}%s\raggedright" % notes_size]
        out += notes_lines(table) + [r"\end{minipage}", r"\end{table}"]
    return ("\n".join(out) + "\n").encode("utf-8")


def preamble_tex():
    """The recommended preamble of the tables and figures (UTF-8 bytes, LF)."""
    landscape = [t for t in TABLE_IDS if LAYOUT.get(t) == "landscape"]
    portrait = [t for t in TABLE_IDS if LAYOUT.get(t) == "portrait"]
    lines = [_comment("Recommended preamble for the %s tables and figures - generated by "
                      "thesis/study_analysis/latex.py; do not edit by hand." % core.ANALYSIS_ID),
             r"\usepackage[T1]{fontenc}  % T1 encoding: underscores of identifiers copy correctly (OT1 drops them)",
             r"\usepackage{booktabs}     % \toprule \midrule \cmidrule \bottomrule \addlinespace",
             r"\usepackage{longtable}    %% tables with more than %d rendered body lines" % LONGTABLE_ROWS,
             r"\usepackage{pdflscape}    % landscape pages; \usepackage{lscape} works too (same page geometry, "
             r"no PDF page rotation)",
             r"\usepackage{pgfplots}     % figures (tikzpicture/axis, inline coordinates, no pgfplots library)",
             r"\pgfplotsset{compat=1.18}",
             _comment("No colorbrewer or other pgfplots library is used: the colours are defined inside each "
                      "picture (xcolor ships with TikZ)."),
             _comment("Page layout, measured with pdflatex on the real study size (A4 portrait text block 16 cm x "
                      "24.7 cm; A4 landscape text block <= 25 cm x 15 cm):"),
             _comment("Landscape needed (\\begin{landscape}\\input{tables/<id>.tex}\\end{landscape}): "
                      + ", ".join(landscape) + "."),
             _comment("Portrait fits: " + ", ".join(portrait) + "."),
             _comment("Longtables (more than %d rendered body lines) continue over pages in either orientation." %
                      LONGTABLE_ROWS),
             _comment("Figures: \\begin{figure}\\centering\\input{figures/<id>.tex}\\input{figures/<id>.caption.tex}"
                      "\\end{figure}; every figure fits the portrait text width.")]
    return ("\n".join(lines) + "\n").encode("utf-8")
