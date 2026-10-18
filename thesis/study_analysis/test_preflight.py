"""Tests of the study-analysis preflight (preflight.py) and the input
manifest (manifest.py) on synthetic repositories: every check FAILs on its
own contradiction, the gate never raises, nothing is written.

    python3 -B -m unittest -v thesis.study_analysis.test_preflight

The real-repository run (about a minute) only with STUDY_ANALYSIS_REAL=1.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest import mock

from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.study_analysis import core, manifest, preflight
from thesis.study_closure import core as sc

REPO_ROOT = Path(__file__).resolve().parents[2]
HEAD = "a" * 40


def write(root, relative, data):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        data = json.dumps(data, indent=2)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def closure_document(composite_raw, composite_sha, **overrides):
    document = OrderedDict([
        ("schema_version", sc.SCHEMA), ("closure_id", preflight.CLOSURE_ID), ("formal", True),
        ("run_ids", list(core.RUNS)), ("model_ids", list(core.MODELS)),
        ("git", OrderedDict([("head", HEAD), ("clean", True)])), ("status", "PASS"),
        ("flags", OrderedDict([("MEASUREMENTS_COMPLETE", "YES"), ("COMPOSITE_VERIFICATION_COMPLETE", "YES"),
                               ("FORMAL_GLOBAL_VERIFICATION_COMPLETE", "YES"), ("PILOT_ACCEPTANCE_COMPLETE", "NO"),
                               ("PUBLICATION_READY", "NO"), ("READY_FOR_SCIENTIFIC_ANALYSIS", "YES")])),
        ("summary", OrderedDict([("composite", OrderedDict([
            ("relative", preflight.pc.DOCUMENT_REL), ("persisted", True), ("raw_sha256", composite_raw),
            ("composite_sha256", composite_sha)]))])),
        ("sections", [OrderedDict([("section", "identity"), ("status", "PASS")]),
                      OrderedDict([("section", "population"), ("status", "PASS")])]),
        ("volatile", OrderedDict([("generated_at_utc", "2026-10-17T00:00:00Z")])),
    ])
    document.update(overrides)
    document = json.loads(json.dumps(document), object_pairs_hook=OrderedDict)
    document["closure_sha256"] = sc.self_hash(document, "closure_sha256")
    return document


def composite_document(lineage_sha="1" * 64, targets_sha="2" * 64):
    document = OrderedDict([
        ("schema_version", preflight.pc.SCHEMA), ("run_id", core.PHASE2), ("lineage_sha256", lineage_sha),
        ("targets_sha256", targets_sha), ("model_ids", list(core.MODELS)),
        ("cells", OrderedDict([("total", 3)])), ("plan_totals", OrderedDict()),
    ])
    document["composite_sha256"] = canonical_sha256(document)
    return document


def census_result(models=None, drop_terminal=False):
    models = list(models or core.MODELS)
    loops = []
    for block in core.BLOCKS:
        for model in models:
            for variant in core.VARIANTS:
                loops.append(OrderedDict([
                    ("block", block), ("model", model), ("variant", variant),
                    ("owner", core.PILOT if block == "pilot" else core.OWNERS[3]), ("expected_cells", 1),
                    ("state", "TERMINAL"), ("terminal", True), ("kind", "native"),
                    ("repair_condition_sha256", "c" * 64), ("samples", 1),
                    ("status_counts", OrderedDict([("stopped_clean", 1)]))]))
    if drop_terminal:
        loops[0].update(state="OPEN", terminal=False)
    return OrderedDict([("models", models),
                        ("base_cells", OrderedDict([("pilot", preflight.pc.EXPECTED_POPULATION[core.PILOT]),
                                                    ("full_ext", preflight.pc.EXPECTED_POPULATION[core.PARENT])])),
                        ("loops", loops), ("non_model_terminal_statuses", [])])


class FakeLineage:
    def __init__(self, sha, targets_sha, census_digest, fail_verify=False):
        self.sha256 = sha
        self.targets_sha256 = targets_sha
        self.document = OrderedDict([("census_digest", census_digest)])
        self.fail_verify = fail_verify
        self.verified = False

    def verify(self):
        if self.fail_verify:
            raise core.AnalysisRefused("protected run file changed: x")
        self.verified = True
        return OrderedDict([(core.PILOT, 1)])


class FakeTable:
    def __init__(self, sha, census_digest):
        self.sha256 = sha
        self.targets = []
        self.document = OrderedDict([("census_digest", census_digest)])


class FakeGit:
    """The read-only git commands preflight issues, answered from sets."""

    def __init__(self, untracked=(), changed=(), ancestor=True):
        self.untracked = set(untracked)
        self.changed = list(changed)
        self.ancestor = ancestor
        self.calls = []

    def __call__(self, root, *args):
        self.calls.append(args)
        if args[0] == "ls-files":
            paths = list(args[args.index("--") + 1:])
            return 0, "".join(p + "\0" for p in paths if p not in self.untracked)
        if args[0] == "status":
            paths = list(args[args.index("--") + 1:])
            lines = [line for line in self.changed if any(line[3:].startswith(p) for p in paths)]
            return 0, "\n".join(lines)
        if args[0] == "merge-base":
            return (0 if self.ancestor else 1), ""
        raise AssertionError("unexpected git command %s" % (args,))


def git_state(clean=True):
    return OrderedDict([("head", HEAD), ("branch", "thesis"), ("clean", clean),
                        ("uncommitted_paths", [] if clean else ["x.txt"]), ("uncommitted_count", 0 if clean else 1)])


class World:
    """A synthetic repository with every preflight input, and the patches
    that stand in for the expensive real readers."""

    def __init__(self, root):
        self.root = Path(root)
        write(root, core.METHODOLOGY_REL, (REPO_ROOT / core.METHODOLOGY_REL).read_bytes())
        write(root, core.ADDENDUM_REL, (REPO_ROOT / core.ADDENDUM_REL).read_bytes())
        write(root, core.PACKAGE_REL + "/clean_module.py", "import json\nfrom thesis.study_analysis import core\n")
        self.composite = composite_document()
        composite_path = write(root, preflight.pc.DOCUMENT_REL, self.composite)
        self.composite_raw = hashlib.sha256(composite_path.read_bytes()).hexdigest()
        self.closure = closure_document(self.composite_raw, self.composite["composite_sha256"])
        write(root, core.CLOSURE_REL, self.closure)
        self.acceptance = OrderedDict([("status", "ACCEPTED"), ("run_id", core.PILOT)])
        write(root, core.ACCEPTANCE_REL, self.acceptance)
        self.census = census_result()
        digest = canonical_sha256(preflight.cs.summary(self.census))
        self.lineage = FakeLineage("1" * 64, "2" * 64, digest)
        self.table = FakeTable("2" * 64, digest)
        self.git = FakeGit()
        self.git_clean = True
        self.validation = OrderedDict([("status", "ACCEPTED"), ("valid_for_gate", True), ("publication_allowed", True),
                                       ("reasons", []), ("problems", []), ("label_required", "pilot label")])

    def patches(self):
        world = self
        return [
            mock.patch.object(core, "EXPECTED_COMPOSITE_SHA256", self.composite["composite_sha256"]),
            mock.patch.object(core, "git_state", lambda root: git_state(world.git_clean)),
            mock.patch.object(preflight, "_git", self.git),
            mock.patch.object(preflight.pl, "load", lambda root: world.lineage),
            mock.patch.object(preflight.pt, "load_table", lambda root, sha=None: world.table),
            mock.patch.object(preflight.cs, "census", lambda root, models=None: world.census),
            mock.patch.object(preflight.ca, "validate_acceptance", lambda root, doc: world.validation),
            mock.patch.object(core, "load_config", lambda root=None: {"models": []}),
        ]

    def run(self, **kwargs):
        patches = self.patches()
        for p in patches:
            p.start()
        try:
            return preflight.preflight(self.root, **kwargs)
        finally:
            for p in reversed(patches):
                p.stop()


def check(result, name):
    for entry in result["checks"]:
        if entry["check"] == name:
            return entry
    raise AssertionError("no check %s in %s" % (name, [c["check"] for c in result["checks"]]))


class PreflightGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="study_analysis_preflight_")
        self.world = World(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assertFails(self, result, name, fragment=None):
        entry = check(result, name)
        self.assertEqual(entry["status"], "FAIL", json.dumps(entry, indent=1, default=str))
        self.assertEqual(result["status"], "FAIL")
        if fragment:
            self.assertIn(fragment, json.dumps(entry["detail"], default=str))

    def test_clean_world_passes_in_both_modes(self):
        result = self.world.run()
        self.assertEqual(result["status"], "PASS", json.dumps(result, indent=1, default=str)[:4000])
        names = [c["check"] for c in result["checks"]]
        self.assertEqual(names, ["git", "package_committed", "closure", "composite", "acceptance", "phase2_lineage",
                                 "census", "provider_isolation_scan", "provider_environment", "methodology",
                                 "addendum", "output_target"])
        self.assertEqual(result["facts"]["composite_sha256"], self.world.composite["composite_sha256"])
        self.assertEqual(result["facts"]["closure_sha256"], self.world.closure["closure_sha256"])
        self.assertEqual(result["facts"]["addendum"], core.addendum_identity(self.world.root))
        self.assertEqual(result["facts"]["addendum"]["status"], core.ADDENDUM_STATUS)
        self.assertEqual(self.world.run(write_mode=True)["status"], "PASS")

    def test_addendum_must_bind_to_the_frozen_methodology_and_be_committed(self):
        original = json.loads((REPO_ROOT / core.ADDENDUM_REL).read_text(encoding="utf-8"),
                              object_pairs_hook=OrderedDict)
        # bound to another methodology (one changed canonical sha) -> refused by core.load_addendum
        foreign = copy.deepcopy(original)
        foreign["amends"]["methodology_canonical_sha256"] = "0" * 64
        write(self.tmp, core.ADDENDUM_REL, foreign)
        self.assertFails(self.world.run(), "addendum", "amends another methodology")
        # a post-freeze id colliding with a frozen metric id
        colliding = copy.deepcopy(original)
        colliding["metrics"][0]["id"] = "Q06"
        write(self.tmp, core.ADDENDUM_REL, colliding)
        self.assertFails(self.world.run(), "addendum", "collide with frozen ids")
        # another status (e.g. a draft) or another methodology file
        draft = copy.deepcopy(original)
        draft["status"] = "DRAFT"
        write(self.tmp, core.ADDENDUM_REL, draft)
        self.assertFails(self.world.run(), "addendum", core.ADDENDUM_STATUS)
        renamed = copy.deepcopy(original)
        renamed["amends"]["methodology"] = "thesis/other/methodology.json"
        write(self.tmp, core.ADDENDUM_REL, renamed)
        self.assertFails(self.world.run(), "addendum", "thesis/other/methodology.json")
        # tracked and unmodified only in write mode (like methodology.json)
        write(self.tmp, core.ADDENDUM_REL, (REPO_ROOT / core.ADDENDUM_REL).read_bytes())
        self.world.git.untracked.add(core.ADDENDUM_REL)
        self.assertEqual(check(self.world.run(), "addendum")["status"], "PASS")
        self.assertFails(self.world.run(write_mode=True), "addendum", "not tracked")
        self.world.git.untracked.clear()
        self.world.git.changed.append(" M " + core.ADDENDUM_REL)
        self.assertFails(self.world.run(write_mode=True), "addendum", "differs from HEAD")
        self.world.git.changed.clear()
        os.remove(str(self.world.root / core.ADDENDUM_REL))
        result = self.world.run()
        self.assertFails(result, "addendum")
        self.assertIsNone(result["facts"]["addendum"])

    def test_deep_runs_the_lineage_verification(self):
        result = self.world.run(deep=True)
        self.assertEqual(check(result, "phase2_lineage_verify")["status"], "PASS")
        self.assertTrue(self.world.lineage.verified)
        self.world.lineage.fail_verify = True
        self.assertFails(self.world.run(deep=True), "phase2_lineage_verify", "protected run file changed")
        self.assertNotIn("phase2_lineage_verify", [c["check"] for c in self.world.run()["checks"]])

    def test_write_mode_requires_clean_committed_code_and_a_fresh_output(self):
        self.world.git_clean = False
        self.assertEqual(check(self.world.run(), "git")["status"], "PASS")
        self.assertFails(self.world.run(write_mode=True), "git", "clean worktree")
        self.world.git_clean = True
        self.world.git.untracked.add(core.PACKAGE_REL + "/clean_module.py")
        self.assertEqual(check(self.world.run(), "package_committed")["status"], "PASS")
        self.assertFails(self.world.run(write_mode=True), "package_committed", "not tracked")
        self.world.git.untracked.clear()
        self.world.git.changed.append(" M %s/clean_module.py" % core.PACKAGE_REL)
        self.assertFails(self.world.run(write_mode=True), "package_committed", "differs from HEAD")
        self.world.git.changed.clear()
        (self.world.root / core.OUTPUT_REL).mkdir(parents=True)
        self.assertEqual(check(self.world.run(), "output_target")["status"], "PASS")
        self.assertFails(self.world.run(write_mode=True), "output_target", "never overwritten")

    def test_closure_contradictions_fail(self):
        cases = [
            (dict(status="FAIL"), "status"),
            (dict(formal=False), "formal"),
            (dict(run_ids=list(core.RUNS)[:-1]), "run_ids"),
        ]
        for overrides, fragment in cases:
            document = closure_document(self.world.composite_raw, self.world.composite["composite_sha256"], **overrides)
            write(self.tmp, core.CLOSURE_REL, document)
            self.assertFails(self.world.run(), "closure", fragment)
        flags = copy.deepcopy(self.world.closure["flags"])
        flags["READY_FOR_SCIENTIFIC_ANALYSIS"] = "NO"
        write(self.tmp, core.CLOSURE_REL, closure_document(self.world.composite_raw,
                                                          self.world.composite["composite_sha256"], flags=flags))
        self.assertFails(self.world.run(), "closure", "READY_FOR_SCIENTIFIC_ANALYSIS")
        sections = [OrderedDict([("section", "coverage"), ("status", "FAIL")])]
        write(self.tmp, core.CLOSURE_REL, closure_document(self.world.composite_raw,
                                                          self.world.composite["composite_sha256"], sections=sections))
        self.assertFails(self.world.run(), "closure", "coverage")

    def test_tampered_or_untracked_closure_fails(self):
        tampered = copy.deepcopy(self.world.closure)
        tampered["status"] = "PASS "
        write(self.tmp, core.CLOSURE_REL, tampered)
        result = self.world.run()
        self.assertFails(result, "closure", "reproduce its hash")
        self.assertFails(result, "composite", "closure document is unavailable")
        write(self.tmp, core.CLOSURE_REL, self.world.closure)
        self.world.git.untracked.add(core.CLOSURE_REL)
        self.assertFails(self.world.run(), "closure", "not tracked")
        self.world.git.untracked.clear()
        self.world.git.changed.append(" M " + core.CLOSURE_REL)
        self.assertFails(self.world.run(), "closure", "differs from HEAD")
        self.world.git.changed.clear()
        self.world.git.ancestor = False
        self.assertFails(self.world.run(), "closure", "not an ancestor")
        os.remove(str(self.world.root / core.CLOSURE_REL))
        self.assertFails(self.world.run(), "closure", "missing input")

    def test_composite_must_be_the_fingerprinted_one(self):
        with mock.patch.object(core, "EXPECTED_COMPOSITE_SHA256", "f" * 64):
            patches = [p for p in self.world.patches() if getattr(p, "attribute", None) != "EXPECTED_COMPOSITE_SHA256"]
            for p in patches:
                p.start()
            try:
                result = preflight.preflight(self.world.root)
            finally:
                for p in reversed(patches):
                    p.stop()
        self.assertFails(result, "composite", "is not the expected")
        # a different (self-consistent) composite contradicts the closure's raw and composite sha
        other = composite_document(lineage_sha="9" * 64)
        write(self.tmp, preflight.pc.DOCUMENT_REL, other)
        result = self.world.run()
        self.assertFails(result, "composite", "closure summary.composite.composite_sha256")
        self.assertFails(result, "phase2_lineage", "composite lineage_sha256")
        # one changed byte of the persisted composite
        path = self.world.root / preflight.pc.DOCUMENT_REL
        write(self.tmp, preflight.pc.DOCUMENT_REL, self.world.composite)
        path.write_bytes(path.read_bytes() + b"\n")
        self.assertFails(self.world.run(), "composite", "raw_sha256")

    def test_acceptance_must_be_accepted_valid_and_tracked(self):
        self.world.validation = OrderedDict([("status", "PENDING"), ("valid_for_gate", False),
                                             ("publication_allowed", False), ("reasons", ["pending"]),
                                             ("problems", ["decided_by must be a non-empty string"])])
        result = self.world.run()
        self.assertFails(result, "acceptance", "PENDING")
        self.assertIn("publication is not allowed", json.dumps(check(result, "acceptance")["detail"]))
        self.world.validation["status"] = "ACCEPTED"
        self.world.validation["valid_for_gate"] = True
        self.assertFails(self.world.run(), "acceptance", "publication is not allowed")
        self.world.validation["publication_allowed"] = True
        self.world.git.untracked.add(core.ACCEPTANCE_REL)
        self.assertFails(self.world.run(), "acceptance", "not tracked")
        self.world.git.untracked.clear()
        write(self.tmp, core.ACCEPTANCE_REL, OrderedDict([("status", "REJECTED")]))
        self.assertFails(self.world.run(), "acceptance", "REJECTED")

    def test_lineage_and_census_bindings(self):
        self.world.table.sha256 = "3" * 64
        self.assertFails(self.world.run(), "phase2_lineage", "target table")
        self.world.table.sha256 = "2" * 64
        self.world.lineage.document["census_digest"] = "0" * 64
        self.assertFails(self.world.run(), "census", "lineage's")
        self.world.lineage.document["census_digest"] = self.world.table.document["census_digest"]
        self.world.census = census_result(drop_terminal=True)
        self.assertFails(self.world.run(), "census", "terminal")

        def broken(root):
            raise core.AnalysisRefused("invalid phase-2 lineage binding")
        with mock.patch.object(preflight.pl, "load", broken):
            patches = [p for p in self.world.patches() if getattr(p, "attribute", None) != "load"]
            for p in patches:
                p.start()
            try:
                result = preflight.preflight(self.world.root)
            finally:
                for p in reversed(patches):
                    p.stop()
        self.assertFails(result, "phase2_lineage", "invalid phase-2 lineage binding")
        self.assertFails(result, "census", "cannot be bound")

    def test_provider_scan_finds_imports_names_and_dynamic_imports(self):
        bad = {
            "a.py": "import anthropic\n",
            "b.py": "from thesis.generation import batch_api\n",
            "c.py": "import thesis.repair.run_repair as r\n",
            "d.py": "def f(client):\n    return client.submit_batch()\n",
            "e.py": "import importlib\nimportlib.import_module('openai')\n",
            "f.py": "from dotenv import load_dotenv\n",
            "g.py": "x = require_provider_call\n",
            "h.py": "import google.genai\n",
        }
        for name, source in bad.items():
            write(self.tmp, core.PACKAGE_REL + "/" + name, source)
        offending, modules = preflight.provider_scan(self.tmp)
        self.assertEqual(modules, len(bad) + 1)
        flagged = set(entry.split(" ")[0] for entry in offending)
        self.assertEqual(flagged, set(bad))
        self.assertFails(self.world.run(), "provider_isolation_scan", "a.py imports anthropic")
        # strings naming forbidden things are not code
        for name in bad:
            os.remove(str(self.world.root / core.PACKAGE_REL / name))
        write(self.tmp, core.PACKAGE_REL + "/strings.py", "FORBIDDEN = ('anthropic', 'submit_batch')\n")
        self.assertEqual(preflight.provider_scan(self.tmp)[0], [])

    def test_census_binding_is_mandatory(self):
        digest = self.world.table.document["census_digest"]
        self.world.lineage.document = OrderedDict()
        result = self.world.run(write_mode=True)
        self.assertFails(result, "census", "lineage carries no census_digest")
        self.world.lineage.document = OrderedDict([("census_digest", digest)])
        self.world.table.document = OrderedDict()
        self.assertFails(self.world.run(), "census", "target table carries no census_digest")
        self.world.table.document = OrderedDict([("census_digest", digest)])
        self.assertEqual(check(self.world.run(), "census")["status"], "PASS")

    def test_provider_scan_resolves_relative_imports_and_attribute_chains(self):
        bad = {
            "r1.py": "from ..generation.generate import main\n",
            "r2.py": "from .. import generation\nx = generation.generate.main\n",
            "r3.py": "import thesis.repair\nx = thesis.repair.run_repair\n",
            "r4.py": "from ..repair import run_repair as rr\n",
            "r5.py": "import thesis.generation as tg\ny = tg.batch_api.submit\n",
            "r6.py": "from ...... import x\n",
        }
        for name, source in bad.items():
            write(self.tmp, core.PACKAGE_REL + "/" + name, source)
        offending, _ = preflight.provider_scan(self.tmp)
        self.assertEqual(set(entry.split(" ")[0] for entry in offending), set(bad))
        self.assertIn("r1.py imports thesis.generation.generate", offending)
        self.assertIn("r2.py references thesis.generation.generate", offending)
        self.assertIn("r3.py references thesis.repair.run_repair", offending)
        self.assertIn("r5.py references thesis.generation.batch_api", offending)
        for name in bad:
            os.remove(str(self.world.root / core.PACKAGE_REL / name))
        # relative imports of the package itself and of harmless siblings are clean
        write(self.tmp, core.PACKAGE_REL + "/relative_ok.py",
              "from . import core\nfrom .core import AnalysisRefused\nfrom .. import evaluation\n"
              "from ..recovery_successor_005 import composite as pc\nx = core.load_methodology\n"
              "y = pc.iter_cells\nz = evaluation.framework\n")
        self.assertEqual(preflight.provider_scan(self.tmp)[0], [])

    def test_provider_environment(self):
        self.assertEqual(preflight.loaded_provider_modules({"json": 1, "openai.types": 1, "dotenv": 1}), ["openai"])
        self.assertEqual(preflight.loaded_provider_modules({"dotenv.main": 1}), [])
        core.provider_isolation()
        self.assertTrue(preflight.dotenv_disabled())
        with mock.patch.dict(os.environ, {"STUDY_ANALYSIS_TEST_KEY": "x"}):
            config = {"models": [{"api_key_env": "STUDY_ANALYSIS_TEST_KEY"}]}
            patches = [p for p in self.world.patches() if getattr(p, "attribute", None) != "load_config"]
            patches.append(mock.patch.object(core, "load_config", lambda root=None: config))
            for p in patches:
                p.start()
            try:
                result = preflight.preflight(self.world.root)
            finally:
                for p in reversed(patches):
                    p.stop()
        self.assertFails(result, "provider_environment", "provider variables present")

    def test_methodology_must_be_frozen(self):
        document = json.loads((REPO_ROOT / core.METHODOLOGY_REL).read_text(encoding="utf-8"),
                              object_pairs_hook=OrderedDict)
        document["status"] = "DRAFT"
        write(self.tmp, core.METHODOLOGY_REL, document)
        self.assertFails(self.world.run(), "methodology", "not frozen")

    def test_the_gate_never_raises_and_reports_every_failure(self):
        empty = tempfile.mkdtemp(prefix="study_analysis_empty_")
        try:
            result = preflight.preflight(empty)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        self.assertEqual(result["status"], "FAIL")
        self.assertGreaterEqual(len(result["failing"]), 5)
        for entry in result["checks"]:
            self.assertIn(entry["status"], ("PASS", "FAIL"))


class CheckListTest(unittest.TestCase):
    def test_guard_turns_exceptions_into_failures(self):
        checks = preflight.CheckList()
        self.assertTrue(checks.guard("ok", lambda: (True, {"n": 1})))
        self.assertFalse(checks.guard("boom", lambda: 1 / 0))
        self.assertFalse(checks.guard("no", lambda: (False, "detail")))
        self.assertEqual(checks.failing(), ["boom", "no"])
        self.assertEqual(checks.status, "FAIL")
        self.assertIn("ZeroDivisionError", checks.checks[1]["detail"])
        self.assertEqual(preflight.CheckList().status, "FAIL")  # no checks is never a PASS


class PureChecksTest(unittest.TestCase):
    def test_census_problems(self):
        summary = preflight.cs.summary(census_result())
        digest = canonical_sha256(summary)
        self.assertEqual(preflight.census_problems(summary, digest, digest), [])
        self.assertTrue(preflight.census_problems(summary, "0" * 64, digest))
        # an absent census binding is a problem, never 'not given' (fail closed)
        unbound = preflight.census_problems(summary)
        self.assertEqual(len(unbound), 2)
        self.assertTrue(all("carries no census_digest" in p for p in unbound))
        self.assertTrue(any("target table" in p for p in preflight.census_problems(summary, digest, None)))
        broken = copy.deepcopy(summary)
        broken["base_cells"]["pilot"] -= 1
        self.assertTrue(any("pilot base cells" in p for p in preflight.census_problems(broken, digest, digest)))
        broken = copy.deepcopy(summary)
        broken["repair_conditions"].append("d" * 64)
        self.assertTrue(any("repair conditions" in p for p in preflight.census_problems(broken, digest, digest)))
        # the loop total follows core.BLOCKS, not a literal 2
        with mock.patch.object(core, "BLOCKS", ("pilot",)):
            self.assertTrue(any("repair loops done" in p
                                for p in preflight.census_problems(summary, digest, digest)))

    def test_closure_problems_need_a_persisted_composite(self):
        document = closure_document("a" * 64, "b" * 64)
        self.assertEqual(preflight.closure_problems(document), [])
        document["summary"]["composite"]["persisted"] = False
        self.assertTrue(preflight.closure_problems(document))


@unittest.skipUnless(shutil.which("git"), "git unavailable")
class GitHelpersTest(unittest.TestCase):
    def test_tracked_changed_and_ancestry_on_a_scratch_repository(self):
        tmp = tempfile.mkdtemp(prefix="study_analysis_git_")
        try:
            def git(*args):
                subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
                                "-c", "commit.gpgsign=false", "-C", tmp] + list(args),
                               check=True, capture_output=True, text=True)
            git("init", "-q")
            write(tmp, "a.txt", "one\n")
            git("add", "a.txt")
            git("commit", "-q", "-m", "one")
            first = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True,
                                   text=True).stdout.strip()
            write(tmp, "b.txt", "two\n")
            self.assertEqual(preflight.git_untracked(tmp, ["a.txt", "b.txt"]), ["b.txt"])
            self.assertEqual(preflight.git_changed(tmp, ["a.txt"]), [])
            self.assertEqual(preflight.tracked_unmodified(tmp, "b.txt")[0], "b.txt is not tracked in git")
            write(tmp, "a.txt", "changed\n")
            self.assertEqual(preflight.git_changed(tmp, ["a.txt"]), ["M a.txt"])
            git("add", "a.txt", "b.txt")
            git("commit", "-q", "-m", "two")
            self.assertTrue(preflight.git_is_ancestor(tmp, first))
            self.assertFalse(preflight.git_is_ancestor(tmp, "HEAD", first))
            with self.assertRaises(core.AnalysisRefused):
                preflight.git_is_ancestor(tmp, "0" * 40)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="study_analysis_manifest_")
        self.world = World(self.tmp)
        self.read = OrderedDict()
        for relative, text in (("thesis/results/intermediate/pilot_002/m/assembly.jsonl", "{}\n"),
                               ("thesis/results/raw/pilot_002/m/generations.jsonl", "{\"x\": 1}\n")):
            write(self.tmp, relative, text)
            self.read[relative] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.dataset = core.Dataset(OrderedDict(), OrderedDict([
            ("targets_sha256", "2" * 64), ("lineage_sha256", "1" * 64), ("census_digest", "3" * 64),
            ("readers", ["thesis.recovery_successor_005.composite"]), ("files_read", self.read)]))
        self.patch = mock.patch.object(core, "git_state", lambda root: git_state())
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_manifest_is_self_hashed_deterministic_and_complete(self):
        extra = "thesis/evaluation/extra.json"
        write(self.tmp, extra, "{}")
        first = manifest.input_manifest(self.tmp, self.dataset, extra_files=[extra])
        second = manifest.input_manifest(self.tmp, self.dataset, extra_files=[extra])
        self.assertTrue(manifest.verify_manifest(first))
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
        self.assertEqual(first["schema_version"], core.MANIFEST_SCHEMA)
        self.assertEqual(list(first["files_read"]), sorted(list(self.read) + [extra]))
        self.assertEqual(first["totals"]["files"], 3)
        self.assertEqual(first["totals"]["bytes"], 3 + 9 + 2)
        self.assertEqual(first["closure"]["closure_sha256"], self.world.closure["closure_sha256"])
        self.assertEqual(first["composite"]["composite_sha256"], self.world.composite["composite_sha256"])
        self.assertEqual(first["acceptance"]["status"], "ACCEPTED")
        self.assertEqual(first["dataset_inputs"]["lineage_sha256"], "1" * 64)
        self.assertIn(core.METHODOLOGY_REL, first["package_sources"])
        # the addendum identity next to the methodology identity
        self.assertEqual(list(first)[list(first).index("methodology") + 1], "addendum")
        self.assertEqual(first["addendum"], core.addendum_identity(self.tmp))
        self.assertEqual(first["addendum"]["relative"], core.ADDENDUM_REL)
        self.assertEqual(manifest.rehash(self.tmp, first), [])
        tampered = copy.deepcopy(first)
        tampered["totals"]["files"] = 4
        with self.assertRaises(core.AnalysisRefused):
            manifest.verify_manifest(tampered)
        # only the volatile block may differ between two runs
        changed = copy.deepcopy(first)
        changed["volatile"]["generated_at_utc"] = "1999-01-01T00:00:00Z"
        self.assertTrue(manifest.verify_manifest(changed))
        start = manifest.input_manifest(self.tmp, None)
        self.assertEqual(start["files_read"], OrderedDict())
        self.assertIsNone(start["dataset_inputs"]["targets_sha256"])

    def test_rehash_names_every_changed_input(self):
        document = manifest.input_manifest(self.tmp, self.dataset)
        relative = list(self.read)[0]
        write(self.tmp, relative, "{\"changed\": true}\n")
        write(self.tmp, core.ACCEPTANCE_REL, OrderedDict([("status", "REJECTED")]))
        write(self.tmp, core.PACKAGE_REL + "/new_module.py", "x = 1\n")
        os.remove(str(Path(self.tmp) / list(self.read)[1]))
        changed = manifest.rehash(self.tmp, document)
        self.assertEqual(changed, sorted([relative, list(self.read)[1], core.ACCEPTANCE_REL,
                                          core.PACKAGE_REL + "/new_module.py"]))
        # a changed addendum byte is an input change as well
        document = manifest.input_manifest(self.tmp, None)
        path = Path(self.tmp) / core.ADDENDUM_REL
        path.write_bytes(path.read_bytes() + b"\n")
        self.assertEqual(manifest.rehash(self.tmp, document), [core.ADDENDUM_REL])

    def test_two_states_of_one_input_refuse(self):
        relative = list(self.read)[0]
        self.dataset.provenance["files_read"][relative] = "0" * 64
        with self.assertRaises(core.AnalysisRefused):
            manifest.input_manifest(self.tmp, self.dataset, extra_files=[relative])
        with self.assertRaises(core.AnalysisRefused):
            manifest.input_manifest(self.tmp, self.dataset, extra_files=["/elsewhere/file.txt"])
        missing = core.Dataset(OrderedDict(), OrderedDict([("targets_sha256", "x")]))
        with self.assertRaises(core.AnalysisRefused):
            manifest.input_manifest(self.tmp, missing)
        self.dataset.provenance["files_read"]["thesis/results/raw/none.jsonl"] = "1" * 64
        with self.assertRaises(core.AnalysisRefused):
            manifest.input_manifest(self.tmp, self.dataset)

    def test_paths_refuse_escapes_and_links(self):
        paths = manifest.Paths(self.tmp)
        relative = list(self.read)[0]
        self.assertEqual(paths.path(relative), Path(self.tmp).resolve() / relative)
        for bad in ("../x", "/etc/passwd", "a//b", "a\\b", "c:/x", "./a", ""):
            with self.assertRaises(core.AnalysisRefused):
                paths.path(bad)
        outside = tempfile.mkdtemp(prefix="study_analysis_outside_")
        try:
            write(outside, "secret.txt", "x")
            try:
                os.symlink(outside, str(Path(self.tmp) / "linked"))
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(core.AnalysisRefused):
                manifest.Paths(self.tmp).path("linked/secret.txt")
            document = manifest.input_manifest(self.tmp, self.dataset)
            document["files_read"]["linked/secret.txt"] = OrderedDict([
                ("raw_sha256", hashlib.sha256(b"x").hexdigest()), ("bytes", 1)])
            self.assertEqual(manifest.rehash(self.tmp, document), ["linked/secret.txt"])
        finally:
            shutil.rmtree(outside, ignore_errors=True)


@unittest.skipUnless(os.environ.get("STUDY_ANALYSIS_REAL") == "1", "real repository run (set STUDY_ANALYSIS_REAL=1)")
class RealRepositoryTest(unittest.TestCase):
    def test_real_preflight_passes_in_dry_mode(self):
        result = preflight.preflight(REPO_ROOT, write_mode=False, deep=False)
        self.assertEqual(result["status"], "PASS", json.dumps(result["failing"]))
        self.assertEqual(result["facts"]["composite_sha256"], core.EXPECTED_COMPOSITE_SHA256)
        self.assertEqual(check(result, "census")["detail"]["total_repair_loops_done"], "66/66")


if __name__ == "__main__":
    unittest.main()
