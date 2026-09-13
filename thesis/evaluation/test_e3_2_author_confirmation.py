#!/usr/bin/env python3
"""E3.2 author confirmation - option-specific fixtures.

The eight author choices (thesis/evaluation/e3_2_decisions.json,
thesis/evaluation/e3_2_author_confirmation.json) are A/B/A/A/C/B/B/A. Four
of them change productive code or config; every such change has its own
fixture group here, and the four FREEZE_AS_IS choices have a regression
group proving that nothing moved:

  E32-02 B  Infer scope serial/mpi, OpenMP NOT_APPLICABLE (config only)
  E32-08 C  clang-tidy FileOffset -> (line, column) against the RAW BYTES
  E32-09 B  gcc_analyzer Phase-0 T1-T5 demotion as low_confidence marking
  E32-11 B  -Wanalyzer-malloc-leak joins the demotion under the same
            signatures only
  E32-01 A / E32-03 A / E32-07 A / E32-12 A  unchanged argv / frozen
            artifacts / driver

Run:  python thesis/evaluation/test_e3_2_author_confirmation.py
No provider calls, no containers, no historical file is written.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.evaluation import framework, static_provenance, tools  # noqa: E402
from thesis.evaluation.framework import (  # noqa: E402
    STATE_COMPLETED,
    STATE_NOT_ANALYZED,
    STATE_NOT_APPLICABLE,
    AssembledSample,
    Finding,
)
from thesis.evaluation.run_static_analysis import not_applicable_entry  # noqa: E402
from thesis.evaluation.tool_config import (  # noqa: E402
    HARD_CAPABILITIES,
    ToolSettings,
    mark_low_confidence,
    resolve_tool_settings,
)
from thesis.evaluation.tools import (  # noqa: E402
    GCC_ANALYZER_DEMOTION_FAMILIES,
    GCC_ANALYZER_FP_DEMOTION_RULES,
    ClangTidyTool,
    apply_gcc_analyzer_fp_demotion,
    gcc_analyzer_fp_demotion_rule,
    gcc_diagnostic_quoted_expr,
    offset_to_line_col,
)
from thesis.repair import feedback, orchestrator  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0

LQ, RQ = "‘", "’"  # GCC's quote pair in the UTF-8 locale


def check(label: str, condition: bool) -> None:
    global CHECKS
    CHECKS += 1
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def q(text: str) -> str:
    return LQ + text + RQ


CONFIG = load_config(REPO_ROOT / "thesis/config/config.yaml")


# ---------------------------------------------------------------------------
# E32-08 C: clang-tidy raw-byte location mapping
# ---------------------------------------------------------------------------

def clang_tidy_sample(tmp: Path, data: bytes) -> tuple[Path, AssembledSample]:
    src = tmp / "generated-code.hpp"
    src.write_bytes(data)
    sample = AssembledSample(
        sample_id="x", model_id="m", run_id="r", execution_model="serial",
        problem_type="p", name="n", source_path=src,
        benchmark_dir=tmp, model_driver_file="", assembly_entry={},
    )
    return src, sample


def fixes_yaml(src: Path, diagnostics: list[tuple[str, str, int, str]]) -> str:
    out = ["---", "MainSourceFile: '%s'" % src.as_posix(), "Diagnostics:"]
    for name, message, offset, level in diagnostics:
        out += [
            "  - DiagnosticName: %s" % name,
            "    DiagnosticMessage:",
            "      Message: '%s'" % message,
            "      FilePath: '%s'" % src.as_posix(),
            "      FileOffset: %d" % offset,
            "    Level: %s" % level,
        ]
    return "\n".join(out) + "\n"


def parse(tmp: Path, data: bytes, diagnostics) -> list[Finding]:
    src, sample = clang_tidy_sample(tmp, data)
    fixes = tmp / "fixes.yaml"
    fixes.write_text(fixes_yaml(src, diagnostics), encoding="utf-8")
    return ClangTidyTool()._parse_fixes(fixes, sample)


def test_clang_tidy_raw_byte_mapping() -> None:
    print("E32-08 C: clang-tidy FileOffset mapped against the raw source bytes")

    lf = b"int a = 0;\nint b = 1;\nlong c = a * b;\n"
    crlf = lf.replace(b"\n", b"\r\n")
    # semantic position: the `*` of line 3 (byte column 12)
    off_lf = lf.index(b"*")
    off_crlf = crlf.index(b"*")
    check("A ASCII LF: (3, 12)", offset_to_line_col(lf, off_lf) == (3, 12))
    check("B ASCII CRLF: (3, 12) - same line and column as LF",
          offset_to_line_col(crlf, off_crlf) == (3, 12))
    # negative control: the pilot_001 conversion counted the byte offset on
    # the universal-newline text (2 bytes shorter here), i.e. 2 columns off
    check("B negative control: counting the CRLF byte offset on newline-normalised text "
          "misplaces the finding (column 14 instead of 12)",
          offset_to_line_col(crlf.replace(b"\r\n", b"\n"), off_crlf) == (3, 14))

    many = b"a\r\n" * 40 + b"int x = y;\r\n" + b"b\r\n" * 30
    off_many = many.index(b"y")
    check("C several CRLF before the finding: line 41", offset_to_line_col(many, off_many) == (41, 9))
    check("C negative control: on newline-normalised text the same byte offset lands 40 bytes "
          "further (line 41 -> a later line): the pilot_001 line shift",
          offset_to_line_col(many.replace(b"\r\n", b"\n"), off_many)[0] > 41)

    # D/E: the SAME semantic source with LF and with CRLF -> identical
    # (line, column) identity for every non-newline byte
    ident_lf, ident_crlf = [], []
    pos_lf = 0
    for line_no, line in enumerate(lf.split(b"\n")[:-1], start=1):
        for col in range(len(line)):
            ident_lf.append(offset_to_line_col(lf, pos_lf + col))
        pos_lf += len(line) + 1
    pos_crlf = 0
    for line_no, line in enumerate(crlf.split(b"\r\n")[:-1], start=1):
        for col in range(len(line)):
            ident_crlf.append(offset_to_line_col(crlf, pos_crlf + col))
        pos_crlf += len(line) + 2
    check("D same semantic source LF vs CRLF -> same line identity",
          [i[0] for i in ident_lf] == [i[0] for i in ident_crlf] and len(ident_lf) == len(lf) - 3)
    check("E same semantic source LF vs CRLF -> same column identity",
          ident_lf == ident_crlf)

    # F/G: UTF-8 multibyte before the finding (byte-based column = clang's
    # column convention). Under the pilot_001 conversion this offset (21)
    # exceeded the decoded text (20 code points) and the location was
    # dropped as (0, 0) / line null.
    utf8 = "// äöü π\nint z = q;\n".encode("utf-8")
    off_q = utf8.index(b"q")
    check("F UTF-8 multibyte on an earlier line: line 2, column 9", offset_to_line_col(utf8, off_q) == (2, 9))
    same_line = "int ää = q;\n".encode("utf-8")
    off_same = same_line.index(b"q")
    check("F UTF-8 multibyte BEFORE the finding on the same line: byte column 12 "
          "(2 two-byte characters), not code-point column 10",
          offset_to_line_col(same_line, off_same) == (1, 12) and same_line.decode("utf-8").index("q") + 1 == 10)
    utf8_crlf = utf8.replace(b"\n", b"\r\n")
    check("G UTF-8 + CRLF: line 2, column 9", offset_to_line_col(utf8_crlf, utf8_crlf.index(b"q")) == (2, 9))

    check("H finding at the first byte: (1, 1)", offset_to_line_col(crlf, 0) == (1, 1))
    check("H finding at the first byte of line 2 (byte after the CRLF): (2, 1)",
          offset_to_line_col(crlf, crlf.index(b"\n") + 1) == (2, 1))
    check("I finding after several lines: last line of the CRLF fixture is line 3",
          offset_to_line_col(crlf, crlf.rindex(b"c")) == (3, 6))

    # J: EOF - clang-tidy reports e.g. a missing trailing newline / EOF
    # diagnostic at offset == byte length. Under the universal-newline
    # conversion a CRLF file's EOF offset exceeded the decoded length and
    # the location was dropped (line null in 6 pilot_001 findings).
    check("J EOF offset on a CRLF file maps to (line count + 1, 1)",
          offset_to_line_col(crlf, len(crlf)) == (4, 1))
    check("J EOF offset on a file without trailing newline maps to the last line",
          offset_to_line_col(b"ab\r\ncd", 6) == (2, 3))
    check("J out-of-range offset is still rejected as (0, 0)",
          offset_to_line_col(crlf, len(crlf) + 1) == (0, 0) and offset_to_line_col(crlf, -1) == (0, 0))
    check("mapping refuses decoded text (no universal-newline path left)",
          _raises(TypeError, lambda: offset_to_line_col("ab\ncd", 3)))

    # K-P: parser behaviour through _parse_fixes on real files
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        src_bytes = b"void f() {\r\n  int x = 0;\r\n  long y = x * 4;\r\n}\r\n"
        star = src_bytes.index(b"*")
        diags = [
            ("bugprone-implicit-widening-of-multiplication-result", "widening", star, "Warning"),
            ("performance-for-range-copy", "expensive copy", 13, "Warning"),
            ("clang-analyzer-optin.mpi.MPI-Checker", "mpi family", 13, "Warning"),
            ("bugprone-eof", "at end of file", len(src_bytes), "Error"),
        ]
        found = parse(t, src_bytes, diags)
        # the driver diagnostic filter is exercised by test_evaluation.py
        check("K raw export-fixes parsing unchanged: 4 model-file diagnostics parsed",
              [f.check_id for f in found] == [d[0] for d in diags])
        check("K messages unchanged", [f.message for f in found] == [d[1] for d in diags])
        check("L check_id unchanged", found[0].check_id == "bugprone-implicit-widening-of-multiplication-result")
        check("M severity unchanged (Warning -> warning, Error -> error)",
              [f.severity for f in found] == ["warning", "warning", "warning", "error"])
        check("N blocking unchanged (bugprone/clang-analyzer blocking, performance not)",
              [f.blocking for f in found] == [True, False, True, True])
        settings = resolve_tool_settings(CONFIG, "static_analysis")["clang_tidy"]
        mark_low_confidence(found, settings)
        check("O low_confidence unchanged (only the configured MPI-Checker family)",
              [f.low_confidence for f in found] == [False, False, True, False])
        check("P location of the CRLF finding is the raw-byte one: line 3, column 14",
              (found[0].line, found[0].column) == (3, 14))
        check("P EOF finding keeps a location on the CRLF file (was null under universal newlines)",
              (found[3].line, found[3].column) == (5, 1))
        lf_found = parse(t, src_bytes.replace(b"\r\n", b"\n"),
                         [("bugprone-implicit-widening-of-multiplication-result", "widening",
                           src_bytes.replace(b"\r\n", b"\n").index(b"*"), "Warning")])
        check("P LF twin of the same source yields the same (line, column)",
              (lf_found[0].line, lf_found[0].column) == (3, 14))

    # P: only the location mapping changed - the classification tables and
    # is_blocking_check are byte-identical to commit 0cb83fa (pre-E32-08)
    parts = ["%s=%s" % (sym, tools._canonical_table(getattr(tools, sym)))
             for sym in ("CLANG_TIDY_CHECKS", "CLANG_TIDY_BLOCKING_GROUPS",
                         "CLANG_TIDY_BLOCKING_EXCEPTIONS", "CLANG_TIDY_LEVEL")]
    parts.append(inspect.getsource(tools.is_blocking_check))
    pin = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    check("P clang-tidy classification tables + is_blocking_check unchanged (pinned at 0cb83fa)",
          pin == "e7df93329aa3eae7736bd3b9685aa37fa815c62291bd4c7620930f5a5f8e66fb")
    src = inspect.getsource(ClangTidyTool._parse_fixes)
    check("P _parse_fixes reads the analysed file as raw bytes and no longer decodes it with universal newlines",
          "Path(file_path).read_bytes()" in src and "Path(file_path).read_text" not in src)


def _raises(exc_type, fn) -> bool:
    try:
        fn()
    except exc_type:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


# ---------------------------------------------------------------------------
# E32-09 B / E32-11 B: gcc_analyzer Phase-0 demotion
# ---------------------------------------------------------------------------

VEC = ("counts.std::vector<int>::<anonymous>.std::_Vector_base<int, std::allocator<int> >"
       "::_M_impl.std::_Vector_base<int, std::allocator<int> >::_Vector_impl_data::_M_start")


def gcc(check_id: str, message: str, blocking: bool = True, tool: str = "gcc_analyzer") -> Finding:
    return Finding(tool=tool, check_id=check_id, severity="warning", message=message,
                   file="generated-code.hpp", line=7, column=3, blocking=blocking,
                   path=[{"n": 1, "text": "event", "line": 7, "file": None, "function": None}])


def rule(check_id: str, message: str, **kw) -> str | None:
    return gcc_analyzer_fp_demotion_rule(gcc(check_id, message, **kw))


def test_gcc_analyzer_demotion_predicate() -> None:
    print("E32-09 B: Phase-0 T1-T5 predicate (exact matching conditions, positive + near-miss)")
    NULL, PNULL, UNINIT = ("-Wanalyzer-null-dereference", "-Wanalyzer-possible-null-dereference",
                           "-Wanalyzer-use-of-uninitialized-value")

    check("rule table carries T1..T5 with condition and source evidence",
          [r[0] for r in GCC_ANALYZER_FP_DEMOTION_RULES] == ["T1", "T2", "T3", "T4", "T5"]
          and all(len(r) == 4 and "pilot-001-corrected-numbers.md" in r[3] for r in GCC_ANALYZER_FP_DEMOTION_RULES))
    # rule table <-> code: every table row id is produced by a positive fixture
    # below and no fixture yields an id outside the table (drift guard)
    produced = {rule(NULL, "dereference of NULL %s [CWE-476]" % q("0")),
                rule(PNULL, "dereference of possibly-NULL %s" % q("operator new(16)")),
                rule(PNULL, "dereference of possibly-NULL %s" % q("<unknown>")),
                rule(UNINIT, "use of uninitialized value %s" % q("*__first.Point::x")),
                rule(UNINIT, "use of uninitialized value %s" % q("v._M_finish"))}
    check("every rule id of the table is produced by a canonical fixture and vice versa",
          produced == {r[0] for r in GCC_ANALYZER_FP_DEMOTION_RULES})
    check("demotion families are exactly the three Phase-0 families + malloc-leak (E32-11 B)",
          set(GCC_ANALYZER_DEMOTION_FAMILIES) == {NULL, PNULL, UNINIT, "-Wanalyzer-malloc-leak"})

    # quoted_expr helper
    check("quoted_expr = text inside the first U+2018/U+2019 pair",
          gcc_diagnostic_quoted_expr("dereference of NULL %s [CWE-476]" % q("0")) == "0")
    check("quoted_expr empty without a quote pair", gcc_diagnostic_quoted_expr("heap-based buffer under-read") == "")

    # T1 - vector-internal storage tokens anywhere in the message
    check("T1 positive: possibly-NULL of vector storage (_Vector_base/_M_impl/_M_start)",
          rule(PNULL, "dereference of possibly-NULL %s [CWE-690]" % q("*" + VEC)) == "T1")
    check("T1 positive: token _M_finish alone", rule(UNINIT, "use of uninitialized value %s" % q("v._M_finish")) == "T1")
    check("T1 near-miss: a named model pointer stays blocking",
          rule(PNULL, "dereference of possibly-NULL %s [CWE-690]" % q("localB")) is None)
    check("T1 near-miss: another libstdc++ member (_M_size) is NOT a listed token",
          rule(PNULL, "dereference of possibly-NULL %s" % q("v._M_size")) is None)

    # T2 - reserved-identifier iterator/algorithm internals in quoted_expr
    check("T2 positive: *__it1$_M_current.Point::x", rule(UNINIT, "use of uninitialized value %s [CWE-457]" % q("*__it1$_M_current.Point::x")) == "T2")
    check("T2 positive: *__first.Point::x (starts with *__)", rule(UNINIT, "use of uninitialized value %s [CWE-457]" % q("*__first.Point::x")) == "T2")
    check("T2 positive: __i$ reserved identifier with $", rule(UNINIT, "use of uninitialized value %s" % q("__i$")) == "T2")
    check("T2 near-miss: single-underscore *_first is not reserved", rule(UNINIT, "use of uninitialized value %s" % q("*_first.x")) is None)
    check("T2 near-miss: __first without * and without $ (a plain reserved name)",
          rule(UNINIT, "use of uninitialized value %s" % q("__first")) is None)
    check("T2 near-miss: reserved identifier outside the quotes does not count",
          rule(UNINIT, "use of uninitialized value %s via __it$" % q("x")) is None)

    # T3 - symbol lost by the analyzer
    check("T3 positive: <unknown>", rule(PNULL, "dereference of possibly-NULL %s [CWE-690]" % q("<unknown>")) == "T3")
    check("T3 positive: *<unknown>", rule(UNINIT, "use of uninitialized value %s [CWE-457]" % q("*<unknown>")) == "T3")
    check("T3 near-miss: a variable literally named unknown", rule(UNINIT, "use of uninitialized value %s" % q("unknown")) is None)

    # T4 - throwing new modelled as fallible
    check("T4 positive: operator new(16)", rule(PNULL, "dereference of possibly-NULL %s [CWE-690]" % q("operator new(16)")) == "T4")
    check("T4 near-miss: a pointer named new_buf", rule(PNULL, "dereference of possibly-NULL %s" % q("new_buf")) is None)
    check("T4 near-miss: 'operator new' outside the quotes", rule(PNULL, "dereference of possibly-NULL %s from operator new" % q("p")) is None)

    # T5 - NULL '0' in the null-dereference family only
    check("T5 positive: dereference of NULL '0'", rule(NULL, "dereference of NULL %s [CWE-476]" % q("0")) == "T5")
    check("T5 near-miss: possible-null family with '0' does NOT match T5",
          rule(PNULL, "dereference of possibly-NULL %s" % q("0")) is None)
    check("T5 near-miss: NULL 'buf' (named pointer, a genuine constant-propagated nullptr in model code)",
          rule(NULL, "dereference of NULL %s [CWE-476]" % q("buf")) is None)
    check("T5 near-miss: NULL '00' / '0x0'", rule(NULL, "dereference of NULL %s" % q("00")) is None
          and rule(NULL, "dereference of NULL %s" % q("0x0")) is None)
    check("T5 near-miss: ASCII quotes (C locale) are not the evidenced quote pair -> stays blocking (fail-closed)",
          rule(NULL, "dereference of NULL '0' [CWE-476]") is None)

    # families and preconditions
    check("out-of-bounds never matches even with a T1 token in the message",
          rule("-Wanalyzer-out-of-bounds", "heap-based buffer under-read of %s" % q("*" + VEC)) is None)
    check("double-free / use-after-free never match", rule("-Wanalyzer-double-free", "double-%s of %s" % ("free", q("*" + VEC))) is None
          and rule("-Wanalyzer-use-after-free", "use after %s of %s" % ("free", q("<unknown>"))) is None)
    check("non-blocking findings are never demoted (precondition finding.blocking)",
          rule(NULL, "dereference of NULL %s" % q("0"), blocking=False) is None)
    check("another tool's finding with the same text is never demoted",
          rule(NULL, "dereference of NULL %s" % q("0"), tool="compiler") is None)
    check("T1 wins over T5 when both hold (first hit reported; the mark is the same)",
          rule(NULL, "dereference of NULL %s" % q("0") + " in " + VEC) == "T1")


def test_malloc_leak_signed_demotion() -> None:
    print("E32-11 B: malloc-leak demoted only under a T1-T5 signature")
    LEAK = "-Wanalyzer-malloc-leak"
    check("positive: leak of vector-internal storage (T1 signature)",
          rule(LEAK, "leak of %s [CWE-401]" % q("localRx." + VEC)) == "T1")
    check("positive: leak of operator new(64) (T4 signature)", rule(LEAK, "leak of %s [CWE-401]" % q("operator new(64)")) == "T4")
    check("positive: leak of <unknown> (T3 signature)", rule(LEAK, "leak of %s [CWE-401]" % q("<unknown>")) == "T3")
    check("negative: leak of a named model buffer stays blocking",
          rule(LEAK, "leak of %s [CWE-401]" % q("buf")) is None)
    check("negative: leak of 'new_data' (near-miss of T4) stays blocking",
          rule(LEAK, "leak of %s [CWE-401]" % q("new_data")) is None)
    check("negative: malloc-leak with quoted '0' does not borrow T5 (null-dereference only)",
          rule(LEAK, "leak of %s" % q("0")) is None)
    check("no blanket rule: check_id alone never demotes",
          rule(LEAK, "leak of memory") is None)


def test_demotion_keeps_findings() -> None:
    print("E32-09 B: demotion marks, never deletes or edits")
    NULL, LEAK, OOB = ("-Wanalyzer-null-dereference", "-Wanalyzer-malloc-leak", "-Wanalyzer-out-of-bounds")
    findings = [
        gcc(NULL, "dereference of NULL %s [CWE-476]" % q("0")),
        gcc(LEAK, "leak of %s [CWE-401]" % q("x." + VEC)),
        gcc(LEAK, "leak of %s [CWE-401]" % q("buf")),
        gcc(OOB, "heap-based buffer under-read [CWE-127]"),
        gcc("-Wanalyzer-too-complex", "analysis bailed out", blocking=False),
    ]
    before = [json.dumps(f.to_dict(), sort_keys=True) for f in findings]
    counts = apply_gcc_analyzer_fp_demotion(findings)
    after = [f.to_dict() for f in findings]

    check("per-rule counts returned", counts == {"T1": 1, "T5": 1})
    check("no finding deleted", len(findings) == 5)
    check("demoted findings carry low_confidence = true", after[0]["low_confidence"] and after[1]["low_confidence"])
    check("non-matching findings untouched (near-miss leak, out-of-bounds, too-complex)",
          not after[2]["low_confidence"] and not after[3]["low_confidence"] and not after[4]["low_confidence"])
    check("blocking field is the tool's assessment and stays true on demoted findings "
          "(the existing low_confidence semantics: parcoach / MPI-Checker keep blocking too)",
          after[0]["blocking"] and after[1]["blocking"] and after[2]["blocking"] and after[3]["blocking"])
    for i in (0, 1):
        restored = dict(after[i]); restored["low_confidence"] = False
        check("demoted finding %d differs from its pre-demotion form ONLY in low_confidence" % i,
              json.dumps(restored, sort_keys=True) == before[i])
    for i in (2, 3, 4):
        check("untouched finding %d is byte-identical" % i, json.dumps(after[i], sort_keys=True) == before[i])

    result = framework.ToolResult(tool="gcc_analyzer", ran=True, exit_code=0, duration_seconds=0.1,
                                  findings=findings, analysis_state=STATE_COMPLETED)
    entry = result.to_dict()
    check("num_findings / num_blocking unchanged by the demotion (4 blocking of 5)",
          entry["num_findings"] == 5 and entry["num_blocking"] == 4)
    settings = resolve_tool_settings(CONFIG, "static_analysis")["gcc_analyzer"]
    check("gcc_analyzer config carries no low_precision settings (the demotion is the evidenced predicate, not a family switch)",
          not settings.low_precision_warning and settings.low_precision_families == ())
    check("num_low_confidence counts the tool-side marks (mark_low_confidence returns the total)",
          mark_low_confidence(findings, settings) == 2)
    check("the run() wiring records the per-rule counts in analysis_details",
          '"fp_demotion": fp_demotion' in inspect.getsource(tools.GccAnalyzerTool.run)
          and "apply_gcc_analyzer_fp_demotion(findings)" in inspect.getsource(tools.GccAnalyzerTool.run))
    check("the implementation hash covers the predicate and its tables",
          {"gcc_analyzer_fp_demotion_rule", "apply_gcc_analyzer_fp_demotion"} <= set(tools._IMPLEMENTATION_DEPS["gcc_analyzer"])
          and {"GCC_ANALYZER_DEMOTION_FAMILIES", "GCC_ANALYZER_FP_DEMOTION_RULES", "GCC_DIAGNOSTIC_QUOTED_RE"}
          <= set(tools._IMPLEMENTATION_TABLES["gcc_analyzer"]))


def test_demotion_rederived_on_pilot_001() -> None:
    print("E32-09/11 B: re-derivation on the pilot_001 base records (read-only; E3.2 evidence numbers)")
    root = REPO_ROOT / "thesis/results/intermediate/pilot_001"
    if not root.is_dir():
        print("  [skip] pilot_001 base records not present on this host (gitignored results tree)")
        return
    by_rule: dict[str, int] = {}
    blocking_total = 0
    residue: dict[str, int] = {}
    for model_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        path = model_dir / "static_analysis.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            entry = (record.get("tools") or {}).get("gcc_analyzer") or {}
            for raw in entry.get("findings") or []:
                if not raw.get("blocking"):
                    continue
                blocking_total += 1
                finding = Finding(**{k: raw.get(k) for k in ("tool", "check_id", "severity", "message", "file", "line", "column", "blocking", "low_confidence")})
                r = gcc_analyzer_fp_demotion_rule(finding)
                if r:
                    by_rule[r] = by_rule.get(r, 0) + 1
                else:
                    residue[raw["check_id"]] = residue.get(raw["check_id"], 0) + 1
    demoted = sum(by_rule.values())
    print("    blocking=%d demoted=%d by_rule=%s residue=%s" % (blocking_total, demoted, dict(sorted(by_rule.items())), residue))
    check("181 blocking gcc_analyzer findings on the base records (E3.2 evidence)", blocking_total == 181)
    check("T1-T5 demote 172 (E3.2 evidence) + 4 malloc-leak (E32-11 B, all T1) = 176",
          demoted == 176 and by_rule.get("T1") == 72 and by_rule.get("T2") == 5 and by_rule.get("T3") == 19 and by_rule.get("T5") == 80)
    check("residue stays blocking: 3 uninitialized-value (MEM[...] / num_threads) + 2 out-of-bounds",
          residue == {"-Wanalyzer-use-of-uninitialized-value": 3, "-Wanalyzer-out-of-bounds": 2})


# ---------------------------------------------------------------------------
# E32-02 B: Infer applicability matrix
# ---------------------------------------------------------------------------

def test_infer_applicability_matrix() -> None:
    print("E32-02 B: Infer configured scope serial/mpi, OpenMP NOT_APPLICABLE")
    settings = resolve_tool_settings(CONFIG, "static_analysis")
    infer = settings["infer"]
    check("configured scope is exactly (serial, mpi)", infer.execution_models == ("serial", "mpi"))
    check("A serial -> Infer applicable", infer.applies_to("serial"))
    check("B mpi -> Infer applicable", infer.applies_to("mpi"))
    check("C omp -> Infer not applicable", not infer.applies_to("omp"))
    entry = not_applicable_entry("infer", "omp")
    check("C omp record entry is NOT_APPLICABLE (not NOT_ANALYZED)",
          entry["analysis_state"] == STATE_NOT_APPLICABLE and entry["ran"] is False)
    check("C NOT_APPLICABLE is not an analysis gap",
          framework.record_analysis_gap({"tools": {"infer": entry}}, "infer") is None)
    check("hard capability and tool semantics unchanged (config narrows only)",
          HARD_CAPABILITIES["infer"] == ("serial", "omp", "mpi")
          and tools.InferTool.execution_models == ("serial", "omp", "mpi"))
    check("Infer implementation (class, parser, level filter) and TU strategy unchanged (pinned at 0cb83fa)",
          tools.tool_implementation_sha256("infer") == "fe31b23c74e06c668c93bd11befcf2701315ed320ee459fd4cf9670b762791de"
          and static_provenance.TU_STRATEGY["infer"] == "full: benchmark cpu.cc with --headers")
    for variant in ("static_feedback", "combined_feedback"):
        req_omp = orchestrator.required_static_tools(CONFIG, variant, "omp")
        req_ser = orchestrator.required_static_tools(CONFIG, variant, "serial")
        req_mpi = orchestrator.required_static_tools(CONFIG, variant, "mpi")
        check("D %s: expected static tool set for OMP excludes infer (%s)" % (variant, ",".join(req_omp)),
              "infer" not in req_omp and "llov" in req_omp and "gcc_analyzer" in req_omp)
        check("E %s: expected static tool set for serial/mpi still contains infer" % variant,
              "infer" in req_ser and "infer" in req_mpi)
    check("other tools' scopes unchanged (compiler/gcc_analyzer/clang_tidy/cppcheck all three; parcoach mpi; llov omp)",
          all(settings[n].execution_models == ("serial", "omp", "mpi") for n in ("compiler", "gcc_analyzer", "clang_tidy", "cppcheck"))
          and settings["parcoach"].execution_models == ("mpi",) and settings["llov"].execution_models == ("omp",))


def omp_record(infer_entry: dict, llov_state: str) -> dict:
    def done(tool):
        return {"tool": tool, "ran": True, "findings": [], "num_blocking": 0,
                "analysis_state": STATE_COMPLETED, "analysis_details": {}}
    return {
        "sample_id": "s", "execution_model": "omp",
        "tools": {
            "compiler": dict(done("compiler"), analysis_details={"build_ok": True}, exit_code=0),
            "gcc_analyzer": done("gcc_analyzer"),
            "clang_tidy": done("clang_tidy"),
            "cppcheck": done("cppcheck"),
            "infer": infer_entry,
            "llov": {"tool": "llov", "ran": True, "findings": [], "num_blocking": 0,
                     "analysis_state": llov_state,
                     "analysis_gap_reason": None if llov_state == STATE_COMPLETED else "region not analyzed"},
        },
    }


def test_repair_stop_with_new_inputs() -> None:
    print("Repair: the stop criterion consumes the new tool / finding classes through the existing policy")
    na = not_applicable_entry("infer", "omp")
    legacy_abort = {"tool": "infer", "ran": True, "findings": [], "num_blocking": 0,
                    "analysis_state": STATE_NOT_ANALYZED,
                    "analysis_gap_reason": "infer frontend aborted translation of at least one method"}

    d = orchestrator.evaluate_stop(CONFIG, "static_feedback", 0, 3, omp_record(na, STATE_COMPLETED), None, None, None)
    check("C issue-free OMP sample with Infer NOT_APPLICABLE and every other tool COMPLETED -> stopped_clean",
          d.status == orchestrator.STATUS_CLEAN and d.counts["analysis_gaps"] == 0)
    d = orchestrator.evaluate_stop(CONFIG, "static_feedback", 0, 3, omp_record(legacy_abort, STATE_COMPLETED), None, None, None)
    check("C (control) the pilot_001 situation - Infer NOT_ANALYZED as a required tool - vetoed the stop; "
          "under the narrowed scope the entry is not required and does not",
          d.status == orchestrator.STATUS_CLEAN)
    d = orchestrator.evaluate_stop(CONFIG, "static_feedback", 0, 3, omp_record(na, STATE_NOT_ANALYZED), None, None, None)
    check("D an LLOV gap still makes the OMP sample analysis_incomplete",
          d.status == orchestrator.STATUS_ANALYSIS_INCOMPLETE and [g["tool"] for g in d.analysis_gaps] == ["llov"])

    # low-confidence repair behaviour with a demoted gcc_analyzer finding
    def demoted_record(extra=None):
        rec = omp_record(na, STATE_COMPLETED)
        f = gcc("-Wanalyzer-null-dereference", "dereference of NULL %s [CWE-476]" % q("0"))
        apply_gcc_analyzer_fp_demotion([f])
        findings = [f.to_dict()] + (extra or [])
        rec["tools"]["gcc_analyzer"] = {"tool": "gcc_analyzer", "ran": True, "findings": findings,
                                        "num_blocking": sum(1 for x in findings if x["blocking"]),
                                        "analysis_state": STATE_COMPLETED, "analysis_details": {}}
        return rec

    groups = feedback.collect_findings(CONFIG, ["compiler_errors", "static_findings"], demoted_record(), None)
    check("A feedback groups the demoted finding as low_confidence (verify-first hint), not as blocking",
          len(groups["low_confidence"]) == 1 and groups["blocking"] == [] and groups["compiler_errors"] == [])
    d0 = orchestrator.evaluate_stop(CONFIG, "static_feedback", 0, 3, demoted_record(), None, None, previous_low_confidence_keys=None)
    check("A grace_once: a NEW demoted finding counts once (low_confidence_effective 1) -> loop continues",
          d0.status == orchestrator.STATUS_ACTIVE and d0.counts["low_confidence_effective"] == 1 and d0.counts["blocking"] == 0)
    d1 = orchestrator.evaluate_stop(CONFIG, "static_feedback", 1, 3, demoted_record(), None, None,
                                    previous_low_confidence_keys=d0.low_confidence_keys)
    check("A grace_once: the same demoted finding persisting into the next iteration stops counting -> stopped_clean",
          d1.status == orchestrator.STATUS_CLEAN and d1.counts["low_confidence_effective"] == 0)
    real = gcc("-Wanalyzer-out-of-bounds", "heap-based buffer under-read [CWE-127]").to_dict()
    d2 = orchestrator.evaluate_stop(CONFIG, "static_feedback", 1, 3, demoted_record([real]), None, None,
                                    previous_low_confidence_keys=d0.low_confidence_keys)
    check("B a real blocking finding (out-of-bounds, undemoted) keeps the sample a repair target",
          d2.status == orchestrator.STATUS_ACTIVE and d2.counts["blocking"] == 1)
    check("stop mode is the productive grace_once", orchestrator.repair_settings(CONFIG)["low_confidence_stop_mode"] == "grace_once")


# ---------------------------------------------------------------------------
# FREEZE_AS_IS choices and condition ownership
# ---------------------------------------------------------------------------

def test_freeze_as_is_choices() -> None:
    print("E32-01 A / E32-03 A / E32-07 A / E32-12 A: nothing moved")
    src = inspect.getsource(tools.GccAnalyzerTool.run)
    check("E32-01 A: gcc_analyzer compile argv carries no OMPI_SKIP_MPICXX", "OMPI_SKIP_MPICXX" not in src)
    check("E32-01 A: PARCOACH keeps its own define", "-DOMPI_SKIP_MPICXX" in inspect.getsource(tools.ParcoachTool))
    from thesis.evaluation.build_config import get_build_config
    for model in ("serial", "omp", "mpi"):
        argv = get_build_config(model, primary_compiler="g++").base_command(
            sources=["x.cc"], output_path="x.o", include_dirs=[], extra_flags=["-fanalyzer", "-c"])
        check("E32-01 A: %s base command has no OMPI_SKIP_MPICXX" % model, not any("OMPI_SKIP_MPICXX" in a for a in argv))

    cpu = REPO_ROOT / "drivers/cpp/benchmarks/search/35_search_search_for_last_struct_by_key/cpu.cc"
    check("E32-12 A: search/35 keeps `const size_t numTries = 5;`",
          cpu.is_file() and re.search(r"\bconst size_t numTries = 5;", cpu.read_text(encoding="utf-8", errors="replace")) is not None)
    check("E32-12 A / E32-03 A / E32-07 A: drivers tree unchanged (drivers_tree_sha256 pinned at 0cb83fa)",
          static_provenance.drivers_tree_sha256() == "a6105f1d3b9b384ebb7c2f4fbe1e7a71277001cbcd5abedf0bef7092fcf72ee2")

    frozen = REPO_ROOT / "thesis/enhanced_tests/frozen/e3_final_specs.jsonl"
    policy = REPO_ROOT / "thesis/enhanced_tests/enhanced_policy.json"
    check("E32-03/07 A: frozen E3 specs and enhanced policy are present (byte identity is pinned by the E3 verifier and the semantic gate)",
          frozen.is_file() and policy.is_file())
    pol = json.loads(policy.read_text(encoding="utf-8"))["benchmarks"]
    geo = {k.split("_", 1)[0]: v for k, v in pol.items() if k.startswith("geometry/1")}
    check("E32-03 A: geometry/12,13,14 size_constraint.min_size stays 1 and size_zero_policy DISALLOWED (no size-0 re-enable)",
          all((geo["geometry/%d" % n].get("size_constraint") or {}).get("min_size") == 1
              and (geo["geometry/%d" % n].get("size_constraint") or {}).get("size_zero_policy") == "DISALLOWED"
              for n in (12, 13, 14)))

    readiness = json.loads((REPO_ROOT / "thesis/evaluation/static_repair_readiness.json").read_text(encoding="utf-8"))
    repair_now = static_provenance.repair_condition_sha256(static_provenance.repair_condition(CONFIG))
    check("repair condition of the final state equals the frozen readiness value (no repair method change)",
          repair_now == readiness["repair_condition_sha256"])
    static_now = static_provenance.static_analysis_condition_sha256(
        static_provenance.static_analysis_condition(CONFIG, include_identities=False))
    check("static condition of the final state equals the frozen readiness value (re-frozen once)",
          static_now == readiness["static_analysis_condition_sha256"])


def main() -> int:
    for test in (
        test_clang_tidy_raw_byte_mapping,
        test_gcc_analyzer_demotion_predicate,
        test_malloc_leak_signed_demotion,
        test_demotion_keeps_findings,
        test_demotion_rederived_on_pilot_001,
        test_infer_applicability_matrix,
        test_repair_stop_with_new_inputs,
        test_freeze_as_is_choices,
    ):
        test()
    if FAILURES:
        print("\n%d of %d checks FAILED:" % (len(FAILURES), CHECKS))
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("\nAll %d E3.2 author-confirmation checks passed." % CHECKS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
