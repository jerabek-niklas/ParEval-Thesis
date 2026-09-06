"""AST inventory of every provider call site in the repository.

The safety invariant of the pre-run enforcement wave is:

    NO cost-causing provider request can technically be executed without a
    valid run authorization.

A guard that lives in the known runners cannot establish that - a new runner
simply forgets it. The guard has to sit at the CHOKEPOINTS every provider
call passes through, and this module is the machine-readable proof that
those chokepoints really are the only way out:

    PROVIDER_CALL_SITES          every SDK/provider invocation found by AST
    PROVIDER_SUBMIT_SITES        the cost-causing batch submissions
    GUARDED_PROVIDER_CALL_SITES  sites reachable ONLY through a chokepoint
    UNGUARDED_PROVIDER_CALL_SITES  everything else - must be empty

Detection is code-based (ast), never doc-based: it walks every tracked .py
file, records provider SDK constructions and method calls by attribute path,
and resolves for each site whether its enclosing function is a chokepoint,
is executed by a chokepoint (the `fn=lambda: ...` handed to
call_with_retries), or is reachable only from chokepoints.

    python thesis/evaluation/provider_call_sites.py [--out inventory.json]

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import warnings

# parsing third-party-style sources emits SyntaxWarnings for regex strings;
# they say nothing about provider call sites
warnings.filterwarnings("ignore", category=SyntaxWarning)
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SEARCH_ROOTS = ("thesis", "drivers", "scripts")
SKIP_DIR_PARTS = {"__pycache__", ".git", ".venv", "results", "node_modules"}

# Provider SDK entry points. Keyed by the ATTRIBUTE PATH SUFFIX of the call,
# because the receiver is always a locally built client object.
COST_CAUSING_METHODS = {
    # direct completion / message APIs
    "messages.create": "direct_completion",
    "responses.create": "direct_completion",
    "chat.completions.create": "direct_completion",
    "completions.create": "direct_completion",
    "models.generate_content": "direct_completion",
    "generate_content": "direct_completion",
    # batch submission APIs
    "messages.batches.create": "batch_submit",
    "batches.create": "batch_submit",
    "files.create": "batch_upload",
}
READ_ONLY_METHODS = {
    "messages.batches.retrieve": "batch_poll",
    "messages.batches.results": "batch_results",
    "batches.retrieve": "batch_poll",
    "batches.get": "batch_poll",
    "batches.cancel": "batch_cancel",
    "files.content": "batch_results",
    "models.list": "model_list",
}
# SDK client constructors: they may open a connection, so the guard has to be
# able to sit in front of them as well (measured separately).
CLIENT_CONSTRUCTORS = {"Anthropic", "OpenAI", "AsyncOpenAI", "AsyncAnthropic", "Client"}
CLIENT_MODULES = {"anthropic", "openai", "genai", "google.genai"}

# The chokepoints this repository commits to.
DIRECT_CHOKEPOINT = "thesis/generation/common.py::call_with_retries"
BATCH_SUBMIT_CHOKEPOINT = "thesis/generation/batch_api.py::submit_batch"
BATCH_POLL_CHOKEPOINT = "thesis/generation/batch_api.py::poll_batch"
CHOKEPOINTS = (DIRECT_CHOKEPOINT, BATCH_SUBMIT_CHOKEPOINT, BATCH_POLL_CHOKEPOINT)
CHOKEPOINT_FUNCTIONS = {"call_with_retries", "submit_batch", "poll_batch"}


def repo_files() -> "List[Path]":
    files = []
    for root in SEARCH_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if SKIP_DIR_PARTS & set(path.parts):
                continue
            files.append(path)
    return sorted(files)


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def attribute_path(node: ast.AST) -> Optional[str]:
    """Dotted path of an attribute expression, e.g. client.messages.create."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        parts.append("<call>")
    elif isinstance(node, ast.Subscript):
        parts.append("<subscript>")
    else:
        parts.append("<expr>")
    return ".".join(reversed(parts))


class ModuleScan:
    """One module: its functions, its calls, and its provider call sites."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rel = relative(path)
        self.tree = ast.parse(path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8"))
        self.functions: "Dict[str, ast.AST]" = {}
        self.calls_by_function: "Dict[str, Set[str]]" = defaultdict(set)
        self.sites: "List[Dict[str, Any]]" = []
        self._scan()

    # -- helpers ---------------------------------------------------------
    def _enclosing_stack(self) -> "List[str]":
        return [name for name, _ in self._stack]

    def _scan(self) -> None:
        self._stack: "List[Tuple[str, ast.AST]]" = []
        self._executed_by: "List[str]" = []
        self._visit(self.tree)

    def _qualname(self) -> str:
        if not self._stack:
            return "<module>"
        return ".".join(name for name, _ in self._stack)

    def _visit(self, node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._stack.append((child.name, child))
                self.functions[self._qualname()] = child
                self._visit(child)
                self._stack.pop()
                continue
            if isinstance(child, ast.ClassDef):
                self._stack.append((child.name, child))
                self._visit(child)
                self._stack.pop()
                continue
            if isinstance(child, ast.Call):
                self._record_call(child)
            self._visit(child)

    def _record_call(self, call: ast.Call) -> None:
        enclosing = self._qualname()
        func = call.func
        path = attribute_path(func) if isinstance(func, (ast.Attribute, ast.Name)) else None
        if path:
            self.calls_by_function[enclosing].add(path.split(".")[-1])
            self.calls_by_function[enclosing].add(path)

        # provider SDK method call?
        kind = None
        matched = None
        if path:
            for suffix, category in COST_CAUSING_METHODS.items():
                if path == suffix or path.endswith("." + suffix):
                    kind, matched = category, suffix
                    break
            if kind is None:
                for suffix, category in READ_ONLY_METHODS.items():
                    if path == suffix or path.endswith("." + suffix):
                        kind, matched = category, suffix
                        break
        # SDK client construction
        if kind is None and isinstance(func, ast.Name) and func.id in CLIENT_CONSTRUCTORS:
            kind, matched = "client_construction", func.id
        if kind is None and isinstance(func, ast.Attribute) and func.attr in CLIENT_CONSTRUCTORS:
            receiver = attribute_path(func.value) or ""
            if receiver.split(".")[-1] in CLIENT_MODULES or receiver in CLIENT_MODULES:
                kind, matched = "client_construction", path
        if kind is None:
            return

        self.sites.append(OrderedDict([
            ("file", self.rel),
            ("line", call.lineno),
            ("enclosing_function", enclosing),
            ("call", path or matched),
            ("matched", matched),
            ("kind", kind),
            ("executed_by", list(self._executed_by)),
        ]))

    def lambda_arguments_of(self, callee_names: "Set[str]") -> "List[Tuple[int, int]]":
        """Line ranges of lambda/function expressions handed to one of the
        given callees (e.g. `call_with_retries(fn=lambda: client...create())`).
        A provider call inside such an expression can only ever be executed by
        that callee, so the callee is its chokepoint."""
        ranges = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            name = attribute_path(node.func) if isinstance(node.func, (ast.Attribute, ast.Name)) else None
            if not name or name.split(".")[-1] not in callee_names:
                continue
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, (ast.Lambda, ast.FunctionDef)):
                    start = getattr(arg, "lineno", None)
                    end = getattr(arg, "end_lineno", None) or start
                    if start:
                        ranges.append((start, end, name.split(".")[-1]))
        return ranges


def build_inventory() -> "OrderedDict[str, Any]":
    scans = []
    for path in repo_files():
        try:
            scans.append(ModuleScan(path))
        except SyntaxError as exc:
            print("WARNING: %s: %s" % (relative(path), exc))
    # reverse call graph over plain function names (module-qualified callees
    # such as batch_api.submit_batch collapse to their function name, which is
    # exactly the granularity a chokepoint argument needs)
    callers_of: "Dict[str, Set[str]]" = defaultdict(set)
    for scan in scans:
        for enclosing, called in scan.calls_by_function.items():
            for name in called:
                callers_of[name.split(".")[-1]].add("%s::%s" % (scan.rel, enclosing))

    sites: "List[Dict[str, Any]]" = []
    for scan in scans:
        lambda_ranges = scan.lambda_arguments_of(CHOKEPOINT_FUNCTIONS)
        for site in scan.sites:
            site = OrderedDict(site)
            site["is_test"] = ("test" in Path(site["file"]).name
                               or "/tests/" in site["file"])
            enclosing_id = "%s::%s" % (site["file"], site["enclosing_function"])
            chokepoint = None
            # (a) the site sits inside a chokepoint function itself
            if site["enclosing_function"].split(".")[-1] in CHOKEPOINT_FUNCTIONS:
                chokepoint = enclosing_id
            # (b) the site sits in a callable handed to a chokepoint (the
            #     `fn=lambda: <sdk call>` of call_with_retries)
            if chokepoint is None:
                for start, end, callee in lambda_ranges:
                    if start <= site["line"] <= end:
                        chokepoint = callee
                        break
            # (c) the enclosing function is reachable only through chokepoints
            if chokepoint is None:
                chokepoint = _reachable_only_via_chokepoint(
                    site["enclosing_function"], scan, callers_of)
            site["chokepoint"] = chokepoint
            site["guarded"] = chokepoint is not None
            site["cost_causing"] = site["kind"] in ("direct_completion", "batch_submit",
                                                    "batch_upload")
            sites.append(site)

    call_sites = [s for s in sites if not s["is_test"]]
    submit_sites = [s for s in call_sites if s["kind"] in ("batch_submit", "batch_upload")]
    cost_sites = [s for s in call_sites if s["cost_causing"]]
    guarded = [s for s in cost_sites if s["guarded"]]
    unguarded = [s for s in cost_sites if not s["guarded"]]

    return OrderedDict([
        ("schema_version", "provider_call_sites.v1"),
        ("chokepoints", OrderedDict([
            ("direct", DIRECT_CHOKEPOINT),
            ("batch_submit", BATCH_SUBMIT_CHOKEPOINT),
            ("batch_poll", BATCH_POLL_CHOKEPOINT),
        ])),
        ("files_scanned", len(scans)),
        ("PROVIDER_CALL_SITES", call_sites),
        ("PROVIDER_SUBMIT_SITES", submit_sites),
        ("GUARDED_PROVIDER_CALL_SITES", guarded),
        ("UNGUARDED_PROVIDER_CALL_SITES", unguarded),
        ("test_sites", [s for s in sites if s["is_test"]]),
        ("counts", OrderedDict([
            ("provider_call_sites", len(call_sites)),
            ("cost_causing", len(cost_sites)),
            ("submit_sites", len(submit_sites)),
            ("guarded", len(guarded)),
            ("unguarded", len(unguarded)),
            ("test_sites", sum(1 for s in sites if s["is_test"])),
        ])),
    ])


def _reachable_only_via_chokepoint(enclosing: str, scan: "ModuleScan",
                                   callers_of: "Dict[str, Set[str]]",
                                   depth: int = 0) -> Optional[str]:
    """A provider call in a private helper is guarded when EVERY caller of
    that helper is a chokepoint (or itself only reachable through one)."""
    if depth > 6:
        return None
    name = enclosing.split(".")[-1]
    callers = callers_of.get(name) or set()
    if not callers:
        return None
    resolved = []
    for caller in callers:
        caller_function = caller.split("::")[-1].split(".")[-1]
        if caller_function in CHOKEPOINT_FUNCTIONS:
            resolved.append(caller)
            continue
        deeper = _reachable_only_via_chokepoint(caller_function, scan, callers_of, depth + 1)
        if deeper is None:
            return None
        resolved.append(deeper)
    return sorted(resolved)[0] if resolved else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    inventory = build_inventory()
    counts = inventory["counts"]
    print("PROVIDER_CALL_SITES = %d (cost-causing %d, of which submit %d)"
          % (counts["provider_call_sites"], counts["cost_causing"], counts["submit_sites"]))
    print("GUARDED_PROVIDER_CALL_SITES = %d" % counts["guarded"])
    print("UNGUARDED_PROVIDER_CALL_SITES = %d" % counts["unguarded"])
    if not args.quiet:
        for site in inventory["PROVIDER_CALL_SITES"]:
            print("  %-46s:%-5d %-28s %-18s %s"
                  % (site["file"], site["line"], site["enclosing_function"][:28],
                     site["kind"], site["chokepoint"] or "UNGUARDED"))
    for site in inventory["UNGUARDED_PROVIDER_CALL_SITES"]:
        print("  UNGUARDED: %s:%d %s (%s)"
              % (site["file"], site["line"], site["call"], site["kind"]))
    if args.out:
        from thesis.evaluation import atomic_io

        atomic_io.atomic_write_json(Path(args.out), inventory)
        print("written:", args.out)
    return 0 if not inventory["UNGUARDED_PROVIDER_CALL_SITES"] else 1


if __name__ == "__main__":
    sys.exit(main())
