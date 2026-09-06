"""Tests for the Static/Repair tool-state wave (tool_state.v1).

Host-only (no container toolchain): tool processes are faked through
`tools.run_command`, the repair provider through the orchestrator test
fakes. Container-level fixture evidence lives in verify_tool_states.py.

Groups (contract tests A-O):
  A  state model: verdict matrix, legacy derivation, record-level subsumption
  B  per-tool state rules with faked processes (compiler, gcc_analyzer,
     clang_tidy, cppcheck) incl. adversarial cases
  C  gcc -fanalyzer event path: one defect = one finding + capped path
  D  merged summary describes the final record state, order-independent
  E  source-hash pinning: changed candidate source -> hard fail, no write
  F  execution fingerprints: idempotent re-run keeps, changed condition
     refuses, cross-container merge of different tools allowed
  G  feedback never renders an analysis gap as a finding
  H  grace_once identity (tool, check_id, file, line), legacy 2-field keys
  I  analysis gap -> stopped_analysis_incomplete, gap + issue -> active,
     subsumed rejection is not a gap, test_feedback ignores external gaps
  J  bounded orchestrator retry rounds -> stopped_api_exhausted (direct)
  K  batch: completed batch without the sample's response is resubmitted,
     bounded by the same ledger
  L  config parity: the repair path registers tools WITH the config
  M  repair condition pinned in the wave state; changed policy refuses resume
  N  static/repair condition fingerprints reproducible, sensitive to options
  O  manifest condition registration: first write, mismatch hard-fails

Run:  python thesis/evaluation/test_tool_state.py
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import framework, static_provenance, tools  # noqa: E402
from thesis.evaluation import run_manifest, run_static_analysis as rsa  # noqa: E402
from thesis.evaluation.framework import (  # noqa: E402
    STATE_COMPLETED,
    STATE_NOT_ANALYZED,
    STATE_NOT_APPLICABLE,
    STATE_PARTIAL,
    STATE_TIMEOUT,
    STATE_TOOL_ERROR,
    CommandResult,
    Finding,
    ToolResult,
)
from thesis.evaluation.tool_config import ToolSettings, resolve_tool_settings  # noqa: E402
from thesis.evaluation.verify_detection import CLEAN_SOURCES, make_raw_sample  # noqa: E402
from thesis.repair import feedback, orchestrator  # noqa: E402
from thesis.repair.orchestrator import (  # noqa: E402
    STATUS_ACTIVE,
    STATUS_ANALYSIS_INCOMPLETE,
    STATUS_API_EXHAUSTED,
    STATUS_CLEAN,
    evaluate_stop,
)
from thesis.repair.test_orchestrator import (  # noqa: E402
    FakeAdapter,
    correctness_record,
    dynamic_record,
    finding,
    make_loop,
    make_world,
    static_record,
    stop_config,
)

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def context() -> framework.EvaluationContext:
    return framework.EvaluationContext(
        repo_root=REPO_ROOT, drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
        primary_compiler="g++", config={},
    )


def fake_command(stdout="", stderr="", returncode=0, timed_out=False, on_call=None):
    def run(argv, timeout, cwd=None, extra_env=None, **kwargs):
        if on_call:
            on_call(argv)
        return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr,
                             timed_out=timed_out, duration_seconds=0.01)
    return run


def run_tool_with(tool, execution_model, source, command):
    original = tools.run_command
    tools.run_command = command
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sample = make_raw_sample(tmp, source, execution_model, "t")
            return tool.run(sample, context())
    finally:
        tools.run_command = original


def state_of(result):
    resolved = result.resolved_state()
    return resolved[0] if isinstance(resolved, tuple) else resolved


# ---------------------------------------------------------------------------
# A  state model
# ---------------------------------------------------------------------------

def test_state_model():
    print("A: state model")
    tv = framework.tool_verdict
    check("NOT_APPLICABLE verdict", tv(STATE_NOT_APPLICABLE, 0) == framework.VERDICT_NOT_APPLICABLE)
    check("COMPLETED + 0 blocking = CLEAN", tv(STATE_COMPLETED, 0) == framework.VERDICT_CLEAN)
    check("COMPLETED + blocking = DEFECT_FOUND", tv(STATE_COMPLETED, 2) == framework.VERDICT_DEFECT_FOUND)
    check("PARTIAL + blocking = DEFECT_FOUND (findings on analyzed paths are real)",
          tv(STATE_PARTIAL, 1) == framework.VERDICT_DEFECT_FOUND)
    for state in (STATE_PARTIAL, STATE_NOT_ANALYZED, STATE_TOOL_ERROR, STATE_TIMEOUT):
        check("%s + 0 blocking is NO_TRUSTWORTHY_VERDICT, never clean" % state,
              tv(state, 0) == framework.VERDICT_NO_TRUSTWORTHY
              and not framework.entry_is_clean({"analysis_state": state, "num_blocking": 0}))

    # legacy (pilot_001-shaped) entries
    legacy = framework.legacy_analysis_state
    check("legacy llov 'Directive Not Analyzed' raw -> NOT_ANALYZED",
          legacy({"tool": "llov", "ran": True, "findings": [],
                  "raw_stderr": "Directive Not Analyzed by the verifier.\nFile : /x/generated-code.hpp:3:3\n"})[0]
          == STATE_NOT_ANALYZED)
    check("legacy llov race + not analyzed -> PARTIAL",
          legacy({"tool": "llov", "ran": True, "findings": [{"check_id": "llov-data-race"}],
                  "raw_stderr": "Data Race detected.\nRegion Not Analyzed by the verifier.\n"})[0]
          == STATE_PARTIAL)
    check("legacy llov race free -> COMPLETED",
          legacy({"tool": "llov", "ran": True, "findings": [],
                  "raw_stderr": "Region is Data Race Free.\n"})[0] == STATE_COMPLETED)
    check("legacy llov no verdict at all -> NOT_ANALYZED",
          legacy({"tool": "llov", "ran": True, "findings": [], "raw_stderr": ""})[0] == STATE_NOT_ANALYZED)
    check("legacy gcc bail-out in a header -> PARTIAL",
          legacy({"tool": "gcc_analyzer", "ran": True, "findings": [],
                  "raw_stderr": "stl_iterator.h:1148:47: warning: analysis bailed out early (1341 'after-snode' enodes) [-Wanalyzer-too-complex]\n"})[0]
          == STATE_PARTIAL)
    check("legacy gcc location-less cc1plus bail-out -> PARTIAL",
          legacy({"tool": "gcc_analyzer", "ran": True, "findings": [],
                  "raw_stderr": "cc1plus: warning: analysis bailed out early (461 'after-snode' enodes) [-Wanalyzer-too-complex]\n"})[0]
          == STATE_PARTIAL)
    check("legacy parcoach timed out -> TIMEOUT",
          legacy({"tool": "parcoach", "ran": True, "error": "parcoach timed out", "findings": []})[0] == STATE_TIMEOUT)
    check("legacy parcoach reduced-TU failure -> TOOL_ERROR",
          legacy({"tool": "parcoach", "ran": True, "error": "clang -emit-llvm failed for the reduced TU"})[0] == STATE_TOOL_ERROR)
    check("legacy clang-diagnostic-error -> TOOL_ERROR",
          legacy({"tool": "clang_tidy", "ran": True, "findings": [{"check_id": "clang-diagnostic-error"}]})[0] == STATE_TOOL_ERROR)
    check("legacy compiler exit -1 with timeout marker -> TIMEOUT",
          legacy({"tool": "compiler", "ran": True, "exit_code": -1,
                  "findings": [{"check_id": "compile-failed", "message": "compilation failed (timeout)"}]})[0] == STATE_TIMEOUT)
    check("legacy not applicable", legacy({"tool": "llov", "ran": False, "error": "not applicable: x"})[0] == STATE_NOT_APPLICABLE)

    # record-level subsumption
    compiler_failed = {"tool": "compiler", "ran": True, "exit_code": 1, "num_blocking": 1,
                       "findings": [{"check_id": "error", "blocking": True}]}
    compiler_ok = {"tool": "compiler", "ran": True, "exit_code": 0, "num_blocking": 0, "findings": []}
    clang_rejected = {"tool": "clang_tidy", "ran": True, "analysis_state": STATE_TOOL_ERROR,
                      "analysis_gap_reason": "clang-diagnostic-error: x",
                      "analysis_details": {"tu_rejected": True}, "findings": []}
    rec = {"tools": {"compiler": compiler_failed, "clang_tidy": clang_rejected}}
    check("rejection of a TU the compiler also rejected -> NOT_ANALYZED (subsumed)",
          framework.effective_tool_state(rec, "clang_tidy")[0] == STATE_NOT_ANALYZED)
    rec = {"tools": {"compiler": compiler_ok, "clang_tidy": clang_rejected}}
    check("rejection of a TU the compiler builds stays TOOL_ERROR (a real gap)",
          framework.effective_tool_state(rec, "clang_tidy")[0] == STATE_TOOL_ERROR)
    timeout_entry = {"tool": "parcoach", "ran": True, "analysis_state": STATE_TIMEOUT, "findings": []}
    rec = {"tools": {"compiler": compiler_failed, "parcoach": timeout_entry}}
    check("a timeout is never subsumed", framework.effective_tool_state(rec, "parcoach")[0] == STATE_TIMEOUT)
    check("compiler itself never subsumed",
          framework.effective_tool_state({"tools": {"compiler": compiler_failed}}, "compiler")[0] == STATE_COMPLETED)


# ---------------------------------------------------------------------------
# B  per-tool rules with faked processes
# ---------------------------------------------------------------------------

def test_tool_rules():
    print("B: per-tool state rules (faked processes)")
    tools.register_default_tools(primary_compiler="g++", config=None)
    clean = CLEAN_SOURCES["serial"]
    compiler = framework.get_tool("compiler")
    analyzer = framework.get_tool("gcc_analyzer")
    tidy = framework.get_tool("clang_tidy")
    cpp = framework.get_tool("cppcheck")

    r = run_tool_with(compiler, "serial", clean, fake_command(returncode=-1, timed_out=True))
    check("compiler timeout -> TIMEOUT, no synthetic finding",
          state_of(r) == STATE_TIMEOUT and not r.findings)
    r = run_tool_with(compiler, "serial", clean,
                      fake_command(stderr="command not found: [Errno 2] No such file", returncode=-1))
    check("compiler missing binary -> TOOL_ERROR, no compile-failed",
          state_of(r) == STATE_TOOL_ERROR and not any(f.check_id == "compile-failed" for f in r.findings)
          and r.analysis_details.get("toolchain_failure") is True)
    r = run_tool_with(compiler, "serial", clean,
                      fake_command(stderr="generated-code.hpp:3:5: error: expected ';'\n", returncode=1))
    check("compiler model error -> COMPLETED + blocking (the build verdict)",
          state_of(r) == STATE_COMPLETED and r.blocking_findings and r.analysis_details.get("build_ok") is False)
    r = run_tool_with(compiler, "serial", clean,
                      fake_command(stderr="g++: internal compiler error: Segmentation fault signal terminated program cc1plus\n", returncode=4))
    check("compiler ICE -> TOOL_ERROR, no compile-failed",
          state_of(r) == STATE_TOOL_ERROR and not r.blocking_findings)
    r = run_tool_with(compiler, "serial", clean, fake_command(stderr="", returncode=1))
    check("compiler non-zero exit without any error diagnostic -> TOOL_ERROR",
          state_of(r) == STATE_TOOL_ERROR and not r.findings)
    r = run_tool_with(compiler, "serial", clean, fake_command(stderr="", returncode=0))
    check("compiler exit 0 -> COMPLETED build_ok", state_of(r) == STATE_COMPLETED
          and r.analysis_details.get("build_ok") is True)
    r = run_tool_with(compiler, "serial", clean, fake_command(
        stderr="/usr/bin/ld: model.o: in function main: undefined reference to luFactorize(std::vector<double>&, unsigned long)\ncollect2: error: ld returned 1 exit status\n",
        returncode=1))
    check("compiler LINK failure is the model's build failure (COMPLETED + compile-failed)",
          state_of(r) == STATE_COMPLETED and any(f.check_id == "compile-failed" for f in r.findings)
          and r.analysis_details.get("build_ok") is False)

    r = run_tool_with(analyzer, "serial", clean, fake_command(stderr="", returncode=0))
    check("gcc_analyzer clean -> COMPLETED", state_of(r) == STATE_COMPLETED)
    r = run_tool_with(analyzer, "serial", clean, fake_command(
        stderr="/usr/include/c++/13/bits/stl_iterator.h:1148:47: warning: analysis bailed out early (1341 'after-snode' enodes; 4652 enodes) [-Wanalyzer-too-complex]\n"))
    check("gcc_analyzer bail-out located in a system header -> PARTIAL, 0 findings",
          state_of(r) == STATE_PARTIAL and not r.findings and r.analysis_details.get("bailed_out_early") is True)
    r = run_tool_with(analyzer, "serial", clean, fake_command(
        stderr="cc1plus: warning: analysis bailed out early (461 'after-snode' enodes; 1200 enodes) [-Wanalyzer-too-complex]\n"))
    check("gcc_analyzer location-less bail-out -> PARTIAL", state_of(r) == STATE_PARTIAL)
    r = run_tool_with(analyzer, "serial", clean, fake_command(stderr="x.cc:1:1: error: nope\n", returncode=1))
    check("gcc_analyzer non-compiling TU -> TOOL_ERROR tu_rejected",
          state_of(r) == STATE_TOOL_ERROR and r.analysis_details.get("tu_rejected") is True)
    r = run_tool_with(analyzer, "serial", clean, fake_command(returncode=-1, timed_out=True))
    check("gcc_analyzer timeout -> TIMEOUT", state_of(r) == STATE_TIMEOUT)

    def tidy_run(stderr, returncode, fixes_yaml=None):
        def on_call(argv):
            if fixes_yaml is not None:
                path = next(a for a in argv if a.startswith("--export-fixes=")).split("=", 1)[1]
                Path(path).write_text(fixes_yaml, encoding="utf-8")
        return run_tool_with(tidy, "serial", clean,
                             fake_command(stderr=stderr, returncode=returncode, on_call=on_call))

    r = tidy_run("22981 warnings generated.\n", 0)
    check("clang_tidy exit 0 + diagnostic summary, no fixes file -> COMPLETED",
          state_of(r) == STATE_COMPLETED and r.analysis_details.get("fixes_present") is False)
    r = tidy_run("", 0)
    check("clang_tidy exit 0 without fixes file AND without any summary -> TOOL_ERROR",
          state_of(r) == STATE_TOOL_ERROR)
    r = tidy_run("Error opening output file: No such file or directory\n", 1)
    check("clang_tidy exit 1 without front-end rejection -> TOOL_ERROR (tool failure)",
          state_of(r) == STATE_TOOL_ERROR and r.analysis_details.get("tu_rejected") is False)
    r = tidy_run("1 error generated.\nError while processing cpu.cc.\nFound compiler error(s).\n", 1)
    check("clang_tidy 'Found compiler error(s)' without attributed finding -> TOOL_ERROR tu_rejected",
          state_of(r) == STATE_TOOL_ERROR and r.analysis_details.get("tu_rejected") is True)
    r = tidy_run("", -1)
    check("clang_tidy exit -1 (missing binary) -> TOOL_ERROR", state_of(r) == STATE_TOOL_ERROR)
    r = run_tool_with(tidy, "serial", clean, fake_command(returncode=-1, timed_out=True))
    check("clang_tidy timeout -> TIMEOUT", state_of(r) == STATE_TIMEOUT)

    xml = ('<?xml version="1.0"?><results version="2"><cppcheck version="2.13.0"/><errors>%s</errors></results>')
    err = ('<error id="%s" severity="%s" msg="%s" verbose="%s"><location file="generated-code.hpp" line="3" column="1"/></error>')
    r = run_tool_with(cpp, "serial", clean, fake_command(stderr=xml % ""))
    check("cppcheck empty results -> COMPLETED clean", state_of(r) == STATE_COMPLETED and not r.findings)
    r = run_tool_with(cpp, "serial", clean, fake_command(stderr=xml % (err % ("syntaxError", "error", "syntax error: !}", "x"))))
    check("cppcheck syntaxError -> PARTIAL, non-blocking, tu_rejected",
          state_of(r) == STATE_PARTIAL and not r.blocking_findings and r.analysis_details.get("tu_rejected") is True)
    r = run_tool_with(cpp, "serial", clean, fake_command(
        stderr=xml % (err % ("preprocessorErrorDirective", "error", "#error planted", "#error planted"))))
    check("cppcheck genuine #error stays COMPLETED + blocking",
          state_of(r) == STATE_COMPLETED and r.blocking_findings)
    r = run_tool_with(cpp, "serial", clean, fake_command(
        stderr=xml % (err % ("preprocessorErrorDirective", "error", "No pair for character ('). Can&apos;t process file.", "x"))))
    check("cppcheck lexer 'No pair for character' -> PARTIAL non-blocking",
          state_of(r) == STATE_PARTIAL and not r.blocking_findings)
    r = run_tool_with(cpp, "serial", clean, fake_command(stderr='<?xml version="1.0"?><results version="2"><errors><error id="x"'))
    check("cppcheck malformed XML -> TOOL_ERROR", state_of(r) == STATE_TOOL_ERROR and r.analysis_details.get("xml") == "malformed")
    r = run_tool_with(cpp, "serial", clean, fake_command(stdout="cppcheck: error: could not find or open any of the paths given.", returncode=1))
    check("cppcheck CLI error (stdout, empty stderr) -> TOOL_ERROR with the stdout message",
          state_of(r) == STATE_TOOL_ERROR and "could not find" in (r.analysis_gap_reason or ""))
    r = run_tool_with(cpp, "serial", clean, fake_command(returncode=-1, timed_out=True))
    check("cppcheck timeout -> TIMEOUT", state_of(r) == STATE_TIMEOUT)


# ---------------------------------------------------------------------------
# C  gcc event path
# ---------------------------------------------------------------------------

GCC_PATH_STDERR = """In function 'double sum_buffer(double*, size_t)',
    inlined from 'void luFactorize(std::vector<double>&, size_t)' at /tmp/x/generated-code.hpp:21:20:
/tmp/x/generated-code.hpp:11:15: warning: dereference of NULL '0' [CWE-476] [-Wanalyzer-null-dereference]
   11 |     s += buf[i];
      |          ~~~~~^
  'void luFactorize(std::vector<double>&, size_t)': events 1-2
    |   16 | void NO_INLINE luFactorize(std::vector<double> &A, size_t N) {
    |      |                (1) entry to 'luFactorize'
    |   21 |   A[1] = sum_buffer(buf, N);
    |      |                    (2) inlined call to 'sum_buffer' from 'luFactorize'
    +--> 'double sum_buffer(double*, size_t)': events 3-6
           |   10 |   for (size_t i = 0; i < N; ++i) {
           |      |                        (3) following 'true' branch (when 'N > i')...
           |   11 |     s += buf[i];
           |      |               (4) ...to here
           |      |               (5) '0' is NULL
           |      |               (6) dereference of NULL '(<unknown> + (i * 8))'
"""


def test_gcc_event_path():
    print("C: gcc -fanalyzer event path")
    findings = [f for f in tools.parse_gcc_clang_diagnostics(GCC_PATH_STDERR, "gcc_analyzer")
                if f.check_id.startswith("-Wanalyzer")]
    check("exactly one finding for one diagnostic (events are not findings)", len(findings) == 1)
    tools.attach_gcc_analyzer_paths(findings, GCC_PATH_STDERR)
    path = findings[0].path if findings else []
    check("path events attached", 3 <= len(path) <= tools.ANALYZER_PATH_MAX_EVENTS)
    check("events numbered and carry text", all(e.get("n") is not None and e.get("text") for e in path if e.get("n") is not None))
    long_path = [{"n": i, "text": "e%d" % i, "line": i} for i in range(1, 40)]
    capped = tools.cap_analyzer_path(long_path)
    check("cap is deterministic and bounded", len(capped) <= tools.ANALYZER_PATH_MAX_EVENTS + 1
          and capped == tools.cap_analyzer_path(long_path))
    rendered = feedback.render_finding(
        {"line": 11, "check_id": "-Wanalyzer-null-dereference", "message": "dereference of NULL", "path": path},
        feedback.feedback_settings({}))
    check("feedback renders the path under the finding", "path:" in rendered and "(1)" in rendered)


# ---------------------------------------------------------------------------
# D/E/F  run_model: merge, summary, source hash, fingerprints
# ---------------------------------------------------------------------------

class FakeStaticTool:
    """ToolResult-producing stand-in registered under a REAL tool name so the
    provenance helpers (implementation hash, option snapshot) apply."""
    execution_models = ("serial", "omp", "mpi")

    def __init__(self, name, state=STATE_COMPLETED, blocking=0, timeout=10.0):
        self.name = name
        self.state = state
        self.blocking = blocking
        self.timeout = timeout

    def is_available(self):
        return True

    def run(self, sample, ctx):
        findings = [Finding(tool=self.name, check_id="planted", severity="error",
                            message="m", file="generated-code.hpp", line=3, blocking=True)
                    for _ in range(self.blocking)]
        return ToolResult(tool=self.name, ran=True, exit_code=0, duration_seconds=0.1,
                          findings=findings, analysis_state=self.state,
                          analysis_gap_reason=None if self.state == STATE_COMPLETED else "faked gap")


def settings_for(names, execution_models=("serial", "omp", "mpi")):
    return {n: ToolSettings(name=n, enabled=True, execution_models=tuple(execution_models),
                            low_precision_warning=False, low_precision_families=())
            for n in names}


class StaticWorld:
    def __init__(self, tmp, sources):
        self.intermediate = Path(tmp) / "intermediate"
        self.samples = []
        for sample_id, (execution_model, source) in sources.items():
            src_dir = Path(tmp) / sample_id
            src_dir.mkdir(parents=True, exist_ok=True)
            path = src_dir / "generated-code.hpp"
            path.write_text(source, encoding="utf-8")
            self.samples.append(SimpleNamespace(sample_id=sample_id, execution_model=execution_model,
                                                source_path=path))
        self.fakes = {}

    def register(self, *fake_tools):
        for tool in fake_tools:
            self.fakes[tool.name] = tool

    def run(self, run_id, names, **kwargs):
        original_get = rsa.framework.get_tool
        original_iter = rsa.framework.iter_assembled_samples
        rsa.framework.get_tool = lambda name: self.fakes[name]
        rsa.framework.iter_assembled_samples = lambda *a, **k: list(self.samples)
        try:
            return rsa.run_model(context=context(), intermediate_dir=self.intermediate,
                                 run_id=run_id, model_id="m", tool_settings=settings_for(names),
                                 expected_tools=settings_for(["compiler", "clang_tidy", "cppcheck"]),
                                 **kwargs)
        finally:
            rsa.framework.get_tool = original_get
            rsa.framework.iter_assembled_samples = original_iter

    def records(self, run_id):
        path = self.intermediate / run_id / "m" / "static_analysis.jsonl"
        return {json.loads(l)["sample_id"]: json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}

    def summary(self, run_id):
        return json.loads((self.intermediate / run_id / "m" / "static_analysis_summary.json").read_text(encoding="utf-8"))


def comparable_summary(summary):
    s = copy.deepcopy(summary)
    s.pop("invocations", None)
    s.pop("tools_run", None)
    s.pop("tools_skipped", None)
    s.pop("created_at_utc", None)
    return s


def test_merge_and_summary():
    print("D: merged summary is order-independent and describes the final records")
    sources = {"m__a__b__serial__sample_0": ("serial", "int a;\n"),
               "m__a__b__omp__sample_0": ("omp", "int b;\n")}
    with tempfile.TemporaryDirectory() as tmp:
        world = StaticWorld(tmp, sources)
        world.register(FakeStaticTool("compiler"), FakeStaticTool("clang_tidy", blocking=1),
                       FakeStaticTool("cppcheck", state=STATE_TIMEOUT))
        world.run("order_a", ["compiler", "cppcheck"], invocation_label="inv1")
        world.run("order_a", ["clang_tidy"], invocation_label="inv2")
        world.run("order_b", ["clang_tidy"], invocation_label="inv1")
        world.run("order_b", ["compiler", "cppcheck"], invocation_label="inv2")
        a, b = world.summary("order_a"), world.summary("order_b")
        check("summary carries the current schema version",
              a.get("schema_version") == rsa.STATIC_SUMMARY_SCHEMA_VERSION)
        check("final summaries identical regardless of invocation order",
              comparable_summary(a) == comparable_summary(b))
        per_tool = a["per_tool"]
        check("per_tool covers every expected tool, not just the last invocation",
              set(per_tool) == {"compiler", "clang_tidy", "cppcheck"})
        check("cppcheck timeouts counted, never as clean",
              per_tool["cppcheck"]["timeout"] == 2 and per_tool["cppcheck"]["clean_completed"] == 0)
        check("clang_tidy blocking counted from the merged records", per_tool["clang_tidy"]["blocking"] == 2)
        check("tools with analysis gaps listed", "cppcheck" in a["tools_with_analysis_gaps"])
        check("invocation history appended (2 invocations)", len(a["invocations"]) == 2)
        check("legacy tools_run = last invocation only, documented",
              a["tools_run"] == ["clang_tidy"] and "summary_semantics" in a)
        records = world.records("order_a")
        rec = records["m__a__b__serial__sample_0"]
        check("record carries analysis_gaps with the timeout", any(g["tool"] == "cppcheck" and g["analysis_state"] == STATE_TIMEOUT for g in rec["analysis_gaps"]))
        check("record pins sample_source_sha256", len(rec.get("sample_source_sha256") or "") == 64)
        check("tool entries carry execution fingerprints",
              all(len(e.get("tool_execution_fingerprint_sha256") or "") == 64 for e in rec["tools"].values()))


def test_source_hash_and_fingerprints():
    print("E/F: source-hash pinning and execution fingerprints")
    sources = {"m__a__b__serial__sample_0": ("serial", "int a;\n")}
    with tempfile.TemporaryDirectory() as tmp:
        world = StaticWorld(tmp, sources)
        world.register(FakeStaticTool("compiler"), FakeStaticTool("clang_tidy"))
        world.run("r", ["compiler"])
        before = (world.intermediate / "r" / "m" / "static_analysis.jsonl").read_bytes()
        # cross-container merge of a different tool: allowed
        world.run("r", ["clang_tidy"])
        rec = world.records("r")["m__a__b__serial__sample_0"]
        check("different tool merged into the same record", set(rec["tools"]) == {"compiler", "clang_tidy"})
        # idempotent re-run of the same tool under the same condition: kept
        summary = world.run("r", ["compiler"])
        check("identical condition -> entry kept (idempotent)",
              summary["invocations"][-1]["entries_kept_idempotent"].get("compiler") == 1)
        # changed condition (option drift) -> refused
        world.register(FakeStaticTool("compiler", timeout=99.0))
        try:
            world.run("r", ["compiler"])
            check("changed tool condition refused", False)
        except static_provenance.StaticMergeConflict as conflict:
            check("changed tool condition refused", "fingerprint" in str(conflict))
        summary = world.run("r", ["compiler"], replace_tool_entries=["compiler"])
        check("explicit --replace-tool-entries re-runs", summary["invocations"][-1]["entries_run"].get("compiler") == 1)
        # source drift -> hard fail, nothing written
        snapshot = (world.intermediate / "r" / "m" / "static_analysis.jsonl").read_bytes()
        world.samples[0].source_path.write_text("int a; int drift;\n", encoding="utf-8")
        try:
            world.run("r", ["clang_tidy"])
            check("changed candidate source hard-fails", False)
        except static_provenance.StaticMergeConflict as conflict:
            check("changed candidate source hard-fails", "generated-code.hpp changed" in str(conflict))
        check("no write on the refused merge",
              (world.intermediate / "r" / "m" / "static_analysis.jsonl").read_bytes() == snapshot)
        del before
        # legacy entry without fingerprint -> refuse silent mixing
        path = world.intermediate / "r" / "m" / "static_analysis.jsonl"
        rec = world.records("r")["m__a__b__serial__sample_0"]
        rec["tools"]["clang_tidy"].pop("tool_execution_fingerprint_sha256", None)
        rec["sample_source_sha256"] = static_provenance.sample_source_sha256(world.samples[0].source_path)
        path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        try:
            world.run("r", ["clang_tidy"])
            check("legacy (unfingerprinted) entry refused without explicit replace", False)
        except static_provenance.StaticMergeConflict as conflict:
            check("legacy (unfingerprinted) entry refused without explicit replace", "legacy" in str(conflict))
        # gap entries are terminal unless --rerun-gaps
        world.register(FakeStaticTool("cppcheck", state=STATE_TOOL_ERROR))
        world.run("r", ["cppcheck"])
        world.register(FakeStaticTool("cppcheck", state=STATE_COMPLETED))
        summary = world.run("r", ["cppcheck"])
        check("a persisted gap is kept (terminal) on a plain re-run",
              summary["invocations"][-1]["entries_kept_idempotent"].get("cppcheck") == 1)
        summary = world.run("r", ["cppcheck"], rerun_gaps=True)
        check("--rerun-gaps re-analyzes the gap entry", summary["invocations"][-1]["entries_run"].get("cppcheck") == 1)


# ---------------------------------------------------------------------------
# G  feedback never renders a gap
# ---------------------------------------------------------------------------

def test_feedback_gap_not_rendered():
    print("G: analysis gaps are never rendered as findings")
    record = static_record({"compiler": [], "clang_tidy": []})
    record["tools"]["parcoach"] = {"tool": "parcoach", "ran": True, "exit_code": -1,
                                   "error": "parcoach timed out", "analysis_state": STATE_TIMEOUT,
                                   "analysis_gap_reason": "parcoach exceeded 60 s", "findings": []}
    groups = feedback.collect_findings(stop_config(), {"generated-code.hpp": "int x;"}, record, None)
    check("no bucket contains the timeout", all(not v for v in groups.values()))


# ---------------------------------------------------------------------------
# H  grace_once identity
# ---------------------------------------------------------------------------

def lc_record(tool="parcoach", check_id="parcoach-collective", line=7, file="generated-code.hpp"):
    f = finding(tool, check_id, "mismatch", line=line, low_confidence=True)
    f["file"] = file
    return static_record({"compiler": [], "clang_tidy": [], tool: [f]})


def test_grace_identity():
    print("H: grace_once identity (tool, check_id, file, line)")
    config = stop_config()
    first = evaluate_stop(config, "static_feedback", 1, 3, lc_record(), None, None, None)
    check("A: new finding blocks with a 4-field key",
          first.status == STATUS_ACTIVE and first.low_confidence_keys == [["parcoach", "parcoach-collective", "generated-code.hpp", 7]])
    second = evaluate_stop(config, "static_feedback", 2, 3, lc_record(), None, None, first.low_confidence_keys)
    check("B: identical identity persists -> grace consumed -> clean", second.status == STATUS_CLEAN)
    other_tool = evaluate_stop(config, "static_feedback", 2, 3, lc_record(tool="clang_tidy"), None, None, first.low_confidence_keys)
    check("C: same check_id+line from another TOOL is a new identity -> blocks", other_tool.status == STATUS_ACTIVE)
    other_file = evaluate_stop(config, "static_feedback", 2, 3, lc_record(file="other.hpp"), None, None, first.low_confidence_keys)
    check("D: same check_id+line in another FILE is a new identity -> blocks", other_file.status == STATUS_ACTIVE)
    legacy = evaluate_stop(config, "static_feedback", 2, 3, lc_record(), None, None, [["parcoach-collective", 7]])
    check("E: legacy 2-field key still matches on (check_id, line)", legacy.status == STATUS_CLEAN)
    legacy_miss = evaluate_stop(config, "static_feedback", 2, 3, lc_record(line=8), None, None, [["parcoach-collective", 7]])
    check("E: legacy key with another line does not match", legacy_miss.status == STATUS_ACTIVE)


# ---------------------------------------------------------------------------
# I  analysis gap semantics in evaluate_stop
# ---------------------------------------------------------------------------

def gap_config():
    config = stop_config()
    config["stages"]["static_analysis"]["tools"]["parcoach"] = {
        "enabled": True, "execution_models": ["mpi"], "low_precision_warning": True}
    return config


def mpi_record(parcoach_entry, compiler_findings=None):
    record = static_record({"compiler": compiler_findings or [], "clang_tidy": []})
    record["execution_model"] = "mpi"
    record["tools"]["parcoach"] = parcoach_entry
    return record


def test_analysis_gap_stop():
    print("I: analysis gap -> stopped_analysis_incomplete")
    config = gap_config()
    timeout = {"tool": "parcoach", "ran": True, "exit_code": -1, "error": "parcoach timed out",
               "analysis_state": STATE_TIMEOUT, "analysis_gap_reason": "parcoach exceeded 60 s", "findings": []}
    d = evaluate_stop(config, "static_feedback", 1, 3, mpi_record(timeout), None, None, None)
    check("no issues + required tool TIMEOUT -> stopped_analysis_incomplete",
          d.status == STATUS_ANALYSIS_INCOMPLETE and d.counts["analysis_gaps"] == 1
          and d.analysis_gaps[0]["tool"] == "parcoach")
    check("reason names tool and state", "parcoach TIMEOUT" in d.stop_reason)
    check("status is terminal and non-model",
          STATUS_ANALYSIS_INCOMPLETE in orchestrator.TERMINAL_STATUSES
          and STATUS_ANALYSIS_INCOMPLETE in orchestrator.NON_MODEL_TERMINAL_STATUSES)
    with_issue = evaluate_stop(config, "static_feedback", 1, 3,
                               mpi_record(timeout, [finding("compiler", "error", "boom", line=2)]), None, None, None)
    check("gap + real issue -> active (the issue is repaired, the gap stays recorded)",
          with_issue.status == STATUS_ACTIVE and with_issue.counts["analysis_gaps"] == 1)
    completed = dict(timeout, analysis_state=STATE_COMPLETED, error=None, exit_code=0, analysis_gap_reason=None)
    clean = evaluate_stop(config, "static_feedback", 1, 3, mpi_record(completed), None, None, None)
    check("COMPLETED parcoach + no issues -> stopped_clean", clean.status == STATUS_CLEAN)
    rejected = {"tool": "parcoach", "ran": True, "exit_code": 1,
                "error": "clang -emit-llvm failed for the reduced TU", "analysis_state": STATE_TOOL_ERROR,
                "analysis_gap_reason": "reduced TU did not compile in the PARCOACH container: x",
                "analysis_details": {"tu_rejected": True}, "findings": []}
    broken = mpi_record(rejected, [finding("compiler", "error", "boom", line=2)])
    d = evaluate_stop(config, "static_feedback", 1, 3, broken, None, None, None)
    check("rejection subsumed by the compiler failure is not a gap", d.counts["analysis_gaps"] == 0 and d.status == STATUS_ACTIVE)
    tf = evaluate_stop(config, "test_feedback", 1, 3, mpi_record(timeout), dynamic_record(),
                       correctness_record("pass"), None)
    check("test_feedback ignores the external tool gap", tf.status == orchestrator.STATUS_TESTS_PASS)
    missing = static_record({"compiler": [], "clang_tidy": []})
    missing["execution_model"] = "mpi"
    d = evaluate_stop(config, "static_feedback", 1, 3, missing, None, None, None)
    check("a MISSING entry is not a gap here (pending is handled upstream)", d.counts["analysis_gaps"] == 0)


# ---------------------------------------------------------------------------
# J  bounded direct retries
# ---------------------------------------------------------------------------

def test_bounded_direct_retries():
    print("J: bounded orchestrator retry rounds (direct)")
    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp, repair_overrides={"request_retry_rounds": 2})
        adapter = FakeAdapter(["error", "error", "error", "error"])
        outcomes = []
        for _ in range(4):
            loop = make_loop(config, profile, model_config, adapter)
            outcomes.append(loop.run())
        check("first run blocks on the transport failure", outcomes[0] == "blocked_api")
        check("the run that uses the last round ends the sample (no further resubmission)",
              outcomes[1] == "done" and outcomes[2] == "done")
        check("exactly request_retry_rounds generate calls, never more", len(adapter.calls) == 2)
        final = loop.sample_states()[sample_id]
        check("terminal status stopped_api_exhausted", final["status"] == STATUS_API_EXHAUSTED)
        check("reason says infrastructure, not model", "not a model failure" in final["stop_reason"])
        check("not repair_unusable", final["status"] != orchestrator.STATUS_UNUSABLE)
        ledger = json.loads(loop.paths.retry_ledger_path.read_text(encoding="utf-8"))
        check("ledger persisted per sample/iteration", ledger[sample_id]["1"] == 2)
        history = loop.paths.iter_generations_path(1).with_name("failed_responses.jsonl")
        check("dropped failure records kept as history", history.exists() and len(history.read_text(encoding="utf-8").splitlines()) == 2)
        row = loop.status_row()
        check("status_row counts the exhausted sample separately",
              row["stopped_api_exhausted"] == 1 and row["repair_unusable"] == 0)
        check("wave state pins the repair condition", len(loop.load_wave_state().get("repair_condition_sha256") or "") == 64)
        # a subsequent run must not resubmit
        loop = make_loop(config, profile, model_config, adapter)
        check("terminal: further runs never resubmit", loop.run() == "done" and len(adapter.calls) == 2)


# ---------------------------------------------------------------------------
# K  batch: completed without the sample's response
# ---------------------------------------------------------------------------

def test_batch_missing_response_bounded():
    print("K: batch completed without a response -> resubmitted, bounded")
    from thesis.generation import batch_api

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp, repair_overrides={"request_retry_rounds": 2})
        config["stages"]["repair"]["api_mode_overrides"] = {"openai_compatible": "batch"}
        adapter = FakeAdapter([])
        calls = {"submit": 0, "poll": 0}

        def fake_submit(provider, model_config, generation_defaults, system_prompt, requests):
            calls["submit"] += 1
            return {"batch_id": "batch_%d" % calls["submit"]}

        def fake_poll(provider, model_config, batch_info):
            calls["poll"] += 1
            return batch_api.BatchStatus(state="completed", detail="ended", responses={})

        original = (batch_api.submit_batch, batch_api.poll_batch)
        batch_api.submit_batch, batch_api.poll_batch = fake_submit, fake_poll
        try:
            outcomes = [make_loop(config, profile, model_config, adapter).run() for _ in range(6)]
            loop = make_loop(config, profile, model_config, adapter)
            final = loop.sample_states()[sample_id]
            check("submissions bounded by request_retry_rounds", calls["submit"] == 2)
            check("no forever-poll of the finished batch", calls["poll"] == 2)
            check("terminal stopped_api_exhausted", final["status"] == STATUS_API_EXHAUSTED)
            check("loop ends", outcomes[-1] == "done")
        finally:
            batch_api.submit_batch, batch_api.poll_batch = original


# ---------------------------------------------------------------------------
# L  config parity
# ---------------------------------------------------------------------------

def test_config_parity():
    print("L: repair path registers tools with the config")
    captured = {}
    real_register = tools.register_default_tools

    def fake_register(primary_compiler="g++", config=None):
        captured["config"] = config
        captured["primary_compiler"] = primary_compiler
        real_register(primary_compiler=primary_compiler, config=config)

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp)
        config["stages"]["static_analysis"]["tools"]["gcc_analyzer"] = {"enabled": True, "timeout_seconds": 7}

        class ParityLoop(orchestrator.RepairLoop):
            def _check_tools_available(self, names):
                return None

        loop = make_loop(config, profile, model_config, FakeAdapter([]), loop_cls=ParityLoop)
        loop.load_or_create_iteration_samples = getattr(loop, "load_or_create_iteration_samples", None)
        originals = (tools.register_default_tools, rsa.run_model, rsa.record_toolchain_versions)
        tools.register_default_tools = fake_register
        rsa.run_model = lambda **kwargs: {"samples": 1}
        rsa.record_toolchain_versions = lambda *a, **k: None
        try:
            try:
                loop._run_analysis_stages(0, ["static"])
            except Exception as error:  # noqa: BLE001 - only the registration call matters here
                print("    (analysis stage stopped after registration: %s)" % type(error).__name__)
            check("register_default_tools receives the loop config",
                  captured.get("config") is config)
            check("gcc_analyzer option resolved from the config on the repair path",
                  captured and framework.get_tool("gcc_analyzer").timeout == 7.0)
        finally:
            tools.register_default_tools, rsa.run_model, rsa.record_toolchain_versions = originals
            tools.register_default_tools(primary_compiler="g++", config=None)


# ---------------------------------------------------------------------------
# M/N/O  conditions and manifests
# ---------------------------------------------------------------------------

def test_conditions_and_manifest():
    print("M/N/O: condition fingerprints, wave-state pin, manifest registration")
    config = json.loads(json.dumps(stop_config()))
    sha1 = static_provenance.repair_condition_sha256(static_provenance.repair_condition(config))
    sha2 = static_provenance.repair_condition_sha256(static_provenance.repair_condition(config))
    check("repair condition reproducible", sha1 == sha2 and len(sha1) == 64)
    changed = json.loads(json.dumps(config))
    changed["stages"]["repair"]["request_retry_rounds"] = 5
    check("repair condition sensitive to the retry policy",
          static_provenance.repair_condition_sha256(static_provenance.repair_condition(changed)) != sha1)
    tools.register_default_tools(primary_compiler="g++", config=None)
    s1 = static_provenance.static_analysis_condition_sha256(static_provenance.static_analysis_condition(config, "g++", None, False))
    drift = json.loads(json.dumps(config))
    drift.setdefault("stages", {}).setdefault("static_analysis", {}).setdefault("tools", {})["gcc_analyzer"] = {"enabled": True, "timeout_seconds": 5}
    tools.register_default_tools(primary_compiler="g++", config=drift)
    s2 = static_provenance.static_analysis_condition_sha256(static_provenance.static_analysis_condition(drift, "g++", None, False))
    tools.register_default_tools(primary_compiler="g++", config=None)
    check("static condition sensitive to a tool option", s1 != s2)
    cond = static_provenance.static_analysis_condition(config, "g++", None, False)
    check("condition records tool implementation hashes and TU strategy",
          all("implementation_sha256" in t and "tu_strategy" in t for t in cond["tools"].values()))
    # cross-PROCESS reproducibility (str hash randomization changed the repr
    # of set-typed tables between interpreters until the tables were
    # canonicalized): two fresh interpreters must agree
    import subprocess
    snippet = ("import sys; sys.path.insert(0, %r); from thesis.evaluation import tools; "
               "print(' '.join(tools.tool_implementation_sha256(n) for n in "
               "('compiler','gcc_analyzer','clang_tidy','cppcheck','infer','parcoach','llov')))" % str(REPO_ROOT))
    runs = [subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True).stdout.strip()
            for _ in range(2)]
    check("implementation hashes identical across interpreter processes", runs[0] and runs[0] == runs[1])

    with tempfile.TemporaryDirectory() as tmp:
        cfg = {"outputs": {"intermediate_dir": tmp}}
        path = run_manifest.manifest_path(cfg, "run_x")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"run_id": "run_x", "created_by_stage": "generation"}), encoding="utf-8")
        run_manifest.register_static_condition(cfg, "run_x", "a" * 64, {"k": 1})
        manifest = json.loads(path.read_text(encoding="utf-8"))
        check("first registration writes sha + condition + backfill note",
              manifest["static_analysis_condition_sha256"] == "a" * 64 and manifest.get("condition_backfills"))
        run_manifest.register_static_condition(cfg, "run_x", "a" * 64, {"k": 1})
        try:
            run_manifest.register_static_condition(cfg, "run_x", "b" * 64, {"k": 2})
            check("different condition on the same run hard-fails", False)
        except run_manifest.AnalysisConditionMismatch:
            check("different condition on the same run hard-fails", True)

    with tempfile.TemporaryDirectory() as tmp:
        config, profile, model_config, sample_id = make_world(tmp)
        loop = make_loop(config, profile, model_config, FakeAdapter(["ok"]))
        loop.run()
        pinned = loop.load_wave_state().get("repair_condition_sha256")
        check("wave state carries the repair condition", len(pinned or "") == 64)
        config["stages"]["repair"]["max_iterations"] = 9
        try:
            make_loop(config, profile, model_config, FakeAdapter([])).load_wave_state()
            check("changed repair policy refuses to resume", False)
        except RuntimeError as error:
            check("changed repair policy refuses to resume", "Refusing to resume" in str(error))


def main() -> int:
    for test in (test_state_model, test_tool_rules, test_gcc_event_path, test_merge_and_summary,
                 test_source_hash_and_fingerprints, test_feedback_gap_not_rendered, test_grace_identity,
                 test_analysis_gap_stop, test_bounded_direct_retries, test_batch_missing_response_bounded,
                 test_config_parity, test_conditions_and_manifest):
        print()
        try:
            test()
        except Exception as error:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILURES.append("%s raised %s: %s" % (test.__name__, type(error).__name__, error))
    print()
    if FAILURES:
        print("FAILED (%d):" % len(FAILURES))
        for label in FAILURES:
            print("  - " + label)
        return 1
    print("All tool-state test groups passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
