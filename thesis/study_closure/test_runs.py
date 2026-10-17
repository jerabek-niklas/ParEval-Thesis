"""Tests of the identity / runs / tree sections (thesis.study_closure.runs).

Synthetic temp repositories carry fake manifests, contracts self-hashed with
the real rule (pilot_run_contract.contract_sha256, so load_frozen accepts
them), start authorizations fingerprinted with the real rule
(run_authorization.authorization_fingerprint), T0 runtime evidence with a
runtime condition fingerprinted with the real rule
(static_provenance.runtime_condition_sha256, run_authorization.t0_evidence_fingerprint,
so the native bound-T0 rule accepts it), stage runtime stamps fingerprinted
with the real rule (stage_runtime._evidence_fingerprint) and a merged
snapshot whose fragments section records the registered fingerprints as
merge_fragments does. Three read-only tests look at the real repository
(marked in their docstrings).

    python3 -B -m unittest -v thesis.study_closure.test_runs
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import types
import unittest
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import manifest_fragments as mf
from thesis.evaluation import pilot_run_contract as prc
from thesis.evaluation import run_authorization as ra
from thesis.evaluation import stage_runtime as sr
from thesis.evaluation import static_provenance as sp
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.recovery_successor_005 import lineage as pl
from thesis.study_closure import core, runs

REPO_ROOT = Path(__file__).resolve().parents[2]
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


ST = sha("static")
RP = sha("repair")


def runtime_identity_fixture(static_sha, repair_sha):
    """A pinned runtime condition over the required domains, fingerprinted
    with the real rule: its sha is the fixture's runtime identity, so the
    native bound-T0 rule (verify_pilot_run._bound_t0_problems) resolves."""
    environments = OrderedDict(
        (domain, OrderedDict([("image_id", sha("image " + domain)),
                              ("tool_identities", OrderedDict([("gcc", sha("gcc " + domain))]))]))
        for domain in ra.REQUIRED_RUNTIME_DOMAINS)
    condition = OrderedDict([("condition_version", "runtime_condition.v1"), ("environments", environments),
                             ("static_analysis_condition_sha256", static_sha),
                             ("repair_condition_sha256", repair_sha),
                             ("fully_pinned", True), ("unpinned_environments", [])])
    return OrderedDict([("condition", condition), ("runtime", sp.runtime_condition_sha256(condition)),
                        ("static", static_sha), ("repair", repair_sha)])


IDENTITY = runtime_identity_fixture(ST, RP)
OTHER_IDENTITY = runtime_identity_fixture(ST, sha("other repair"))
RT = IDENTITY["runtime"]
SPECS_BYTES = b'{"benchmark": "x", "spec": 1}\n'
SPECS_SHA = hashlib.sha256(SPECS_BYTES).hexdigest()
EXCLUDED = core.EXCLUDED_RUNS[0]
MODEL = core.MODELS[0]
OTHER = core.MODELS[1]
ITERATIONS = ("pilot_002__static_feedback__iter1", "full_ext_recovery_004__test_feedback__iter2")


def write_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def statuses(section):
    return OrderedDict((c["check"], c["status"]) for c in section.checks)


def check(section, check_id):
    return [c for c in section.checks if c["check"] == check_id][0]


class FakeTable:
    """Only what the tree section reads of the phase-2 target table."""

    def __init__(self, source_runs):
        self.targets = [types.SimpleNamespace(source_run=run) for run in source_runs]
        self.sha256 = sha("table")


class Repo:
    """A tiny study world: the seven bound runs, two iteration directories
    with assembly rows, the excluded parent repair under both areas, a
    phase-2 results tree and out-of-study directories."""

    def __init__(self, tmp):
        self.root = Path(tmp).resolve()
        self.intermediate = self.root / core.INTERMEDIATE_REL
        self.raw = self.root / core.RAW_REL
        self.intermediate.mkdir(parents=True)
        self.raw.mkdir(parents=True)
        (self.intermediate / runs.LOCKS_DIR_NAME).mkdir()
        frozen = self.root / runs.FROZEN_SPECS_REL
        frozen.parent.mkdir(parents=True, exist_ok=True)
        frozen.write_bytes(SPECS_BYTES)
        write_json(self.root / runs.METHODOLOGY_FREEZE_REL,
                   OrderedDict([("enhanced", OrderedDict([("frozen_specs_sha256", SPECS_SHA)]))]))
        write_json(self.root / runs.PHASE2_READINESS_REL,
                   OrderedDict([("origin_runtime_condition_sha256", RT),
                                ("static_analysis_condition_sha256", ST), ("repair_condition_sha256", RP)]))
        write_json(self.root / runs.ORIGIN_READINESS_REL,
                   OrderedDict([("runtime_condition_sha256", RT),
                                ("static_analysis_condition_sha256", ST), ("repair_condition_sha256", RP)]))
        for run in core.RUNS:
            self.make_run(run)
        for run in (core.PILOT, core.PARENT):
            write_jsonl(self.raw / run / MODEL / "generations.jsonl", [{"sample_id": "s0"}])
            self.assembly(run, MODEL, ["s0"])
        for name in ITERATIONS:
            (self.raw / name).mkdir()
            self.assembly(name, MODEL, ["s0", "s1"])
        (self.intermediate / EXCLUDED).mkdir()
        write_jsonl(self.raw / EXCLUDED / OTHER / "generations.jsonl", [{"sample_id": "a"}, {"sample_id": "b"}])
        write_jsonl(self.intermediate / core.PHASE2 / MODEL / "phase2_invocations.jsonl", [{"stage": "enhanced"}])
        (self.intermediate / "pilot_001").mkdir()
        (self.raw / "smoke_001__static_feedback__iter1").mkdir()
        (self.raw / "model_check_001").mkdir()

    # -- builders ---------------------------------------------------------------------
    def assembly(self, run, model, samples, source_run=None):
        rows = [OrderedDict([("run_id", run), ("model_id", model), ("sample_id", sample), ("assembled", True),
                             ("source_path", "%s/%s/%s/sources/%s/generated-code.hpp"
                              % (core.INTERMEDIATE_REL, source_run or run, model, sample))])
                for sample in samples]
        write_jsonl(self.intermediate / run / model / "assembly.jsonl", rows)

    def fragments_dir(self, run):
        return self.intermediate / run / runs.FRAGMENTS_DIR_NAME

    def fragment(self, run, name, kind, owner, content, fingerprint):
        document = OrderedDict([
            ("schema_version", "run_manifest_fragment.v1"), ("run_id", run), ("kind", kind), ("owner", owner),
            ("fingerprint_sha256", fingerprint), ("content_sha256", canonical_sha256(content)),
            ("registered_at_utc", "2026-01-01T00:00:00Z"), ("writer", "fixture"), ("content", content)])
        write_json(self.fragments_dir(run) / name, document)
        return document

    def contract_document(self, run, identity=IDENTITY):
        entry = core.RUN_REGISTRY[run]
        model_ids = list(core.MODELS) if run in runs.FULL_MODEL_RUNS else [MODEL, OTHER]
        contract = OrderedDict([
            ("schema_version", prc.CONTRACT_SCHEMA_VERSION), ("run_id", run), ("profile", entry["profile"]),
            ("model_ids", model_ids),
            ("conditions", OrderedDict([
                ("static_repair_runtime_condition_sha256", identity["runtime"]),
                ("static_analysis_condition_sha256", identity["static"]),
                ("repair_condition_sha256", identity["repair"]), ("enhanced_frozen_specs_sha256", SPECS_SHA),
                ("enhanced_frozen_specs_path", runs.FROZEN_SPECS_REL)])),
            ("status", prc.STATUS_READY), ("blockers", []), ("built_at_utc", "2026-01-01T00:00:00Z"),
            ("builder", "fixture")])
        contract["contract_sha256"] = prc.contract_sha256(contract)
        return contract

    def authorization_document(self, run, contract_sha, identity=IDENTITY, **overrides):
        content = OrderedDict([
            ("schema_version", ra.AUTHORIZATION_SCHEMA_VERSION),
            ("authorization_policy_version", ra.AUTHORIZATION_POLICY_VERSION), ("run_id", run),
            ("frozen_contract_sha256", contract_sha), ("rebuilt_contract_sha256", contract_sha),
            ("readiness_runtime_condition_sha256", identity["runtime"]),
            ("fresh_t0_runtime_condition_sha256", identity["runtime"]),
            ("decision", ra.DECISION_ALLOWED), ("required_runtime_domains", list(ra.REQUIRED_RUNTIME_DOMAINS)),
            ("authorized_at_utc", "2026-01-01T00:00:00Z"), ("hostname", "fixture"), ("pid", 1),
            ("thread_id", 1), ("probe_duration_seconds", 0.1)])
        content.update(overrides)
        content["authorization_sha256"] = ra.authorization_fingerprint(content)
        return content

    def evidence_document(self, run, contract_sha, identity=IDENTITY):
        """T0 runtime evidence (t0_runtime_evidence.v2) the native bound-T0
        rule resolves: the runtime condition content, every required domain
        pinned with tool identities and no probe error."""
        domains = OrderedDict()
        for domain, environment in identity["condition"]["environments"].items():
            domains[domain] = OrderedDict([("image_id", environment["image_id"]),
                                           ("tool_identities", OrderedDict(environment["tool_identities"])),
                                           ("probe_error", None)])
        return OrderedDict([
            ("evidence_version", "t0_runtime_evidence.v2"), ("run_id", run),
            ("contract_sha256", contract_sha), ("probe_status", "OK"),
            ("fresh_runtime_condition_sha256", identity["runtime"]),
            ("readiness_runtime_condition_sha256", identity["runtime"]),
            ("static_analysis_condition_sha256", identity["static"]),
            ("repair_condition_sha256", identity["repair"]),
            ("runtime_condition", identity["condition"]),
            ("required_runtime_domains", list(ra.REQUIRED_RUNTIME_DOMAINS)), ("domains", domains)])

    def snapshot_fragments(self, run):
        """The snapshot's fragments section as merge_fragments records it."""
        entries = OrderedDict()
        for name, fragment in mf.load_fragments(self.intermediate, run):
            entries[name] = OrderedDict([("kind", fragment["kind"]), ("owner", fragment["owner"]),
                                         ("fingerprint_sha256", fragment["fingerprint_sha256"]),
                                         ("registered_at_utc", fragment["registered_at_utc"])])
        return entries

    def rebind(self, run, **snapshot):
        """Re-merge the snapshot after a fragment was replaced on disk: the
        fragments section follows the disk, the given top-level copies
        (e.g. authorization=..., runtime_evidence=...) are updated."""
        manifest = self.manifest(run)
        manifest["fragments"] = self.snapshot_fragments(run)
        manifest.update(snapshot)
        self.write_manifest(run, manifest)

    def stamp_content(self, run, stage, contract_sha, auth_sha, **overrides):
        content = OrderedDict([
            ("schema_version", sr.STAGE_RUNTIME_EVIDENCE_VERSION), ("run_id", run), ("stage", stage),
            ("runtime_domains", ["main"]), ("observation_mode", sr.MODE_INSIDE),
            ("contract_sha256", contract_sha), ("authorization_sha256", auth_sha),
            ("expected_t0_runtime_condition_sha256", RT), ("observed_runtime_condition_sha256", None),
            ("match", True), ("drift_fields", []),
            ("domains", OrderedDict([("main", OrderedDict([("expected_t0_domain_sha256", sha("main")),
                                                            ("observed_domain_sha256", sha("main"))]))]))])
        content.update(overrides)
        content["stage_runtime_sha256"] = sr._evidence_fingerprint(content)
        return content

    def stamp(self, run, stage, contract_sha, auth_sha, **overrides):
        content = self.stamp_content(run, stage, contract_sha, auth_sha, **overrides)
        return self.fragment(run, "runtime.stage.%s.json" % stage, "runtime", "stage." + stage, content,
                             content["stage_runtime_sha256"])

    def make_run(self, run, identity=IDENTITY):
        """A bound run under the given runtime identity (every artifact of
        the run agrees with it); rewrites the run when called again."""
        entry = core.RUN_REGISTRY[run]
        if self.fragments_dir(run).is_dir():
            shutil.rmtree(self.fragments_dir(run))
        contract = self.contract_document(run, identity)
        write_json(self.root / entry["contract"], contract)
        auth = self.authorization_document(run, contract["contract_sha256"], identity)
        self.fragment(run, "authorization.start.json", "authorization", "start", auth, auth["authorization_sha256"])
        evidence = self.evidence_document(run, contract["contract_sha256"], identity)
        self.fragment(run, "runtime.evidence.json", "runtime", "evidence", evidence,
                      ra.t0_evidence_fingerprint(evidence))
        for stage in ("correctness", "static.main"):
            self.stamp(run, stage, contract["contract_sha256"], auth["authorization_sha256"],
                       expected_t0_runtime_condition_sha256=identity["runtime"])
        history = self.fragments_dir(run) / "history"
        history.mkdir(exist_ok=True)
        write_json(history / "authorization.start.20260101T000000.000000Z.1.json",
                   OrderedDict([("run_id", run), ("outcome", "created")]))
        write_json(history / "authorization.start.20260101T000001.000000Z.1.json",
                   OrderedDict([("run_id", run), ("outcome", "REFUSED")]))
        manifest = OrderedDict([
            ("schema_version", "run_manifest_merged.v1"), ("run_id", run), ("profile", entry["profile"]),
            ("created_at_utc", "2026-01-01T00:00:00Z"), ("git_commit", "0" * 40), ("git_dirty", False),
            ("enhanced_specs", OrderedDict([("path", "thesis/results/cache/enhanced/specs.jsonl"),
                                            ("sha256", SPECS_SHA), ("spec_count", 1)])),
            ("config_drift", []), ("runtime_evidence", evidence),
            ("runtime_evidence_sha256", ra.t0_evidence_fingerprint(evidence)),
            ("contract_sha256", contract["contract_sha256"]),
            ("authorization", auth), ("authorization_sha256", auth["authorization_sha256"]),
            ("fragments", self.snapshot_fragments(run)),
            ("unexpected_fragments", []), ("missing_expected_fragments", []), ("complete", True)])
        self.write_manifest(run, manifest)

    def manifest_path(self, run):
        return self.intermediate / run / "run_manifest.json"

    def manifest(self, run):
        return read_json(self.manifest_path(run))

    def write_manifest(self, run, document):
        write_json(self.manifest_path(run), document)

    def context(self, **options):
        config = OrderedDict([("outputs", OrderedDict([("intermediate_dir", core.INTERMEDIATE_REL),
                                                         ("raw_dir", core.RAW_REL)])), ("models", [])])
        ctx = core.Context(self.root, config, self.root / "thesis/config/config.yaml", options=options)
        ctx.run_config = lambda run: config
        ctx._table = FakeTable([core.PILOT, core.PARENT] + list(ITERATIONS))
        return ctx


class SyntheticRepoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="study_closure_runs_")
        self.repo = Repo(self._tmp)
        self.root = self.repo.root

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)


# -- runs section ------------------------------------------------------------------------

class RunsSectionTest(SyntheticRepoTest):
    def test_fixture_passes_and_binds_every_run(self):
        ctx = self.repo.context()
        section = runs.collect_runs(ctx)
        self.assertEqual(section.failing(), [])
        self.assertEqual(section.status, core.PASS)
        self.assertEqual(len(section.checks), 7 * len(core.RUNS) + 2)
        bindings = ctx.cache["run_bindings"]
        self.assertEqual(list(bindings), list(core.RUNS))
        for run in core.RUNS:
            self.assertEqual(bindings[run]["contract_sha256"], self.repo.contract_document(run)["contract_sha256"])
            self.assertEqual(bindings[run]["authorization_sha256"], self.repo.manifest(run)["authorization_sha256"])
            self.assertTrue(bindings[run]["manifest_complete"])
            self.assertEqual(bindings[run]["git_commit"], "0" * 40)
            self.assertEqual(bindings[run]["runtime"], OrderedDict([("readiness_rt", RT), ("fresh_rt", RT),
                                                                    ("static_cond", ST), ("repair_cond", RP)]))
        self.assertEqual(len(bindings[core.PILOT]["model_ids"]), len(core.MODELS))
        self.assertEqual(len(bindings[core.OWNERS[1]]["model_ids"]), 2)
        facts = section.data["runs"][core.PHASE2]
        self.assertEqual(facts["stage_stamps"], ["correctness", "static.main"])
        self.assertEqual(facts["fragments"], 4)
        self.assertEqual(set(facts["checks"].values()), {core.PASS})
        integrity = check(section, "runs:%s:fragment_integrity" % core.PILOT)["detail"]
        self.assertEqual(integrity["refused_history_entries"], 1)
        self.assertEqual(integrity["history_outcomes"], OrderedDict([("REFUSED", 1), ("created", 1)]))
        self.assertEqual(integrity["snapshot_fragments"], 4)
        self.assertEqual(integrity["stray_files"], [])
        t0 = check(section, "runs:%s:runtime_t0" % core.PILOT)["detail"]
        self.assertEqual([c["check"] for c in t0["native"]], ["runtime_evidence_bound_at_t0", "methodical_config_drift"])
        self.assertTrue(t0["fingerprint_reproduces"])
        self.assertEqual((t0["bound_t0_problems"], t0["bound_t0_unresolved"]), ([], []))
        uniform = check(section, "runs:runtime_identity_uniform")["detail"]
        self.assertEqual(uniform["values"]["repair_cond"], RP)
        specs = check(section, "runs:enhanced_specs_uniform")["detail"]
        self.assertEqual(specs["sha256"], SPECS_SHA)
        self.assertEqual(specs["recorded_paths_present"], [])
        json.dumps(core.json_stable(section.document()))

    def test_manifest_incomplete_fails(self):
        manifest = self.repo.manifest(core.PILOT)
        manifest["complete"] = False
        manifest["missing_expected_fragments"] = ["enhanced.claude_fable_5.json"]
        self.repo.write_manifest(core.PILOT, manifest)
        ctx = self.repo.context()
        section = runs.collect_runs(ctx)
        self.assertEqual(section.failing(), ["runs:pilot_002:manifest_complete"])
        problems = check(section, "runs:pilot_002:manifest_complete")["detail"]["problems"]
        self.assertTrue(any("complete is False" in p for p in problems))
        self.assertTrue(any("missing_expected_fragments" in p for p in problems))
        self.assertFalse(ctx.cache["run_bindings"][core.PILOT]["manifest_complete"])

    def test_manifest_dirty_or_foreign_fails(self):
        manifest = self.repo.manifest(core.PARENT)
        manifest["git_dirty"] = True
        manifest["run_id"] = "someone_else"
        self.repo.write_manifest(core.PARENT, manifest)
        section = runs.collect_runs(self.repo.context())
        self.assertIn("runs:full_ext_001:manifest_complete", section.failing())

    def test_manifest_missing_fails_closed(self):
        self.repo.manifest_path(core.OWNERS[0]).unlink()
        section = runs.collect_runs(self.repo.context())
        failing = section.failing()
        self.assertIn("runs:full_ext_recovery_001:manifest_complete", failing)
        self.assertIn("runs:full_ext_recovery_001:runtime_t0", failing)
        # the cross-run checks fail closed too: that run's runtime identity and
        # enhanced specs are unknown; no other run's checks fail
        self.assertIn("runs:runtime_identity_uniform", failing)
        self.assertIn("runs:enhanced_specs_uniform", failing)
        self.assertTrue(all(f.startswith("runs:full_ext_recovery_001:") or f in
                            ("runs:runtime_identity_uniform", "runs:enhanced_specs_uniform") for f in failing), failing)

    def test_contract_hash_broken_fails(self):
        path = self.root / core.RUN_REGISTRY[core.PARENT]["contract"]
        contract = read_json(path)
        contract["model_ids"] = contract["model_ids"][:-1]  # content changed, stored sha kept
        write_json(path, contract)
        section = runs.collect_runs(self.repo.context())
        failing = section.failing()
        self.assertIn("runs:full_ext_001:frozen_contract", failing)
        self.assertIn("ContractDrift", check(section, "runs:full_ext_001:frozen_contract")["detail"])
        # without a usable contract its enhanced-specs condition cannot be
        # referenced (fail closed); no other run's checks fail
        self.assertIn("runs:enhanced_specs_uniform", failing)
        self.assertTrue(all(f.startswith("runs:full_ext_001:") or f == "runs:enhanced_specs_uniform"
                            for f in failing), failing)
        self.assertEqual(check(section, "runs:%s:models" % core.PILOT)["status"], core.PASS)

    def test_contract_of_another_run_or_profile_fails(self):
        run = core.OWNERS[2]
        contract = self.repo.contract_document(run)
        contract["profile"] = "recovery_successor"
        contract["contract_sha256"] = prc.contract_sha256(contract)
        write_json(self.root / core.RUN_REGISTRY[run]["contract"], contract)
        section = runs.collect_runs(self.repo.context())
        detail = check(section, "runs:%s:frozen_contract" % run)["detail"]
        self.assertEqual(check(section, "runs:%s:frozen_contract" % run)["status"], core.FAIL)
        self.assertTrue(any("profile" in p for p in detail["problems"]))
        self.assertTrue(any("manifest" in p for p in detail["problems"]))

    def test_authorization_frozen_contract_mismatch_fails(self):
        run = core.OWNERS[1]
        content = self.repo.authorization_document(run, sha("another contract"))
        self.repo.fragment(run, "authorization.start.json", "authorization", "start", content,
                           content["authorization_sha256"])
        self.repo.rebind(run, authorization=content, authorization_sha256=content["authorization_sha256"])
        section = runs.collect_runs(self.repo.context())
        result = check(section, "runs:%s:authorization" % run)
        self.assertEqual(result["status"], core.FAIL)
        self.assertTrue(any("frozen_contract_sha256" in p for p in result["detail"]["problems"]))
        # the rewritten fragment is internally consistent and the snapshot
        # follows it: only the bindings fail (the native bound-T0 rule sees
        # the authorization contract contradiction too)
        self.assertEqual(check(section, "runs:%s:fragment_integrity" % run)["status"], core.PASS)
        self.assertEqual(check(section, "runs:%s:manifest_complete" % run)["status"], core.PASS)
        t0 = check(section, "runs:%s:runtime_t0" % run)
        self.assertEqual(t0["status"], core.FAIL)
        self.assertTrue(any("authorization contract" in p for p in t0["detail"]["bound_t0_problems"]))

    def test_fragment_replaced_on_disk_without_snapshot_fails(self):
        """A fragment rewritten on disk while the merged snapshot still carries
        the old copy and the old registered fingerprint: the snapshot is not
        the run's truth any more."""
        run = core.OWNERS[1]
        content = self.repo.authorization_document(run, sha("another contract"))
        self.repo.fragment(run, "authorization.start.json", "authorization", "start", content,
                           content["authorization_sha256"])
        section = runs.collect_runs(self.repo.context())
        result = check(section, "runs:%s:fragment_integrity" % run)
        self.assertEqual(result["status"], core.FAIL)
        problems = [p["problem"] for p in result["detail"]["problems"]]
        self.assertTrue(any("snapshot fingerprint_sha256" in p for p in problems), problems)
        self.assertTrue(any("snapshot authorization differs from the fragment content" in p for p in problems), problems)

    def test_snapshot_claims_a_fragment_deleted_from_disk_fails(self):
        """complete=true and missing_expected_fragments=[] in the snapshot do
        not make a deleted fragment present."""
        run = core.OWNERS[1]
        (self.repo.fragments_dir(run) / "runtime.stage.correctness.json").unlink()
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(check(section, "runs:%s:manifest_complete" % run)["status"], core.PASS)
        result = check(section, "runs:%s:fragment_integrity" % run)
        self.assertEqual(result["status"], core.FAIL)
        self.assertEqual(result["detail"]["fragments"], 3)
        self.assertEqual(result["detail"]["snapshot_fragments"], 4)
        self.assertIn(OrderedDict([("fragment", "runtime.stage.correctness.json"),
                                   ("problem", "registered in the snapshot but not on disk")]),
                      result["detail"]["problems"])
        self.assertTrue(all(f.startswith("runs:%s:" % run) for f in section.failing()), section.failing())

    def test_snapshot_evidence_edited_only_fails(self):
        """A runtime-evidence field edited in the snapshot only (one no other
        check reads): the snapshot differs from the fragment, the registered
        evidence fingerprint no longer reproduces and the native bound-T0
        rule leaves a required domain unresolved."""
        manifest = self.repo.manifest(core.PARENT)
        manifest["runtime_evidence"]["required_runtime_domains"] = ["main"]
        self.repo.write_manifest(core.PARENT, manifest)
        section = runs.collect_runs(self.repo.context())
        integrity = check(section, "runs:full_ext_001:fragment_integrity")
        self.assertEqual(integrity["status"], core.FAIL)
        self.assertTrue(any("snapshot runtime_evidence differs" in p["problem"] for p in integrity["detail"]["problems"]))
        t0 = check(section, "runs:full_ext_001:runtime_t0")
        self.assertEqual(t0["status"], core.FAIL)
        self.assertFalse(t0["detail"]["fingerprint_reproduces"])
        self.assertTrue(any("T0 identity incomplete" in p for p in t0["detail"]["bound_t0_unresolved"]))
        self.assertTrue(all(f.startswith("runs:full_ext_001:") for f in section.failing()), section.failing())

    def test_snapshot_authorization_edited_only_fails(self):
        """A volatile authorization field edited in the snapshot only: the
        fingerprint still reproduces, so only the snapshot-vs-fragment
        comparison can see it."""
        run = core.OWNERS[3]
        manifest = self.repo.manifest(run)
        manifest["authorization"]["hostname"] = "another-host"
        self.repo.write_manifest(run, manifest)
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(check(section, "runs:%s:authorization" % run)["status"], core.PASS)
        result = check(section, "runs:%s:fragment_integrity" % run)
        self.assertEqual(result["status"], core.FAIL)
        self.assertEqual([p["problem"] for p in result["detail"]["problems"]],
                         ["snapshot authorization differs from the fragment content"])

    def test_snapshot_registered_fingerprint_tampered_fails(self):
        manifest = self.repo.manifest(core.PHASE2)
        manifest["fragments"]["runtime.stage.static.main.json"]["fingerprint_sha256"] = sha("elsewhere")
        manifest["fragments"]["runtime.evidence.json"]["owner"] = "other"
        self.repo.write_manifest(core.PHASE2, manifest)
        section = runs.collect_runs(self.repo.context())
        result = check(section, "runs:full_ext_phase2_001:fragment_integrity")
        self.assertEqual(result["status"], core.FAIL)
        names = sorted(p["fragment"] for p in result["detail"]["problems"])
        self.assertEqual(names, ["runtime.evidence.json", "runtime.stage.static.main.json"])
        self.assertEqual(section.failing(), ["runs:full_ext_phase2_001:fragment_integrity"])

    def test_temporary_and_torn_files_in_fragments_dir_fail(self):
        """A crashed writer's '<name>.tmp-<pid>-<tid>-<token>' leftover
        (atomic_io naming), a '*.torn' archive and a non-json file are never
        silently skipped, and never counted as fragments."""
        run = core.OWNERS[2]
        directory = self.repo.fragments_dir(run)
        (directory / "runtime.stage.dynamic.json.tmp-123-4-abcd").write_text("{torn", encoding="utf-8")
        (directory / "runtime.evidence.json.torn").write_text("{torn", encoding="utf-8")
        (directory / "notes.txt").write_text("x", encoding="utf-8")
        section = runs.collect_runs(self.repo.context())
        result = check(section, "runs:%s:fragment_integrity" % run)
        self.assertEqual(result["status"], core.FAIL)
        self.assertEqual(result["detail"]["stray_files"],
                         ["notes.txt", "runtime.evidence.json.torn", "runtime.stage.dynamic.json.tmp-123-4-abcd"])
        self.assertEqual(result["detail"]["fragments"], 4)
        stamps = check(section, "runs:%s:stage_runtime_stamps" % run)
        self.assertEqual(stamps["status"], core.FAIL)
        self.assertEqual(stamps["detail"]["stages"], ["correctness", "static.main"])
        self.assertTrue(any("runtime.stage.dynamic.json.tmp-123-4-abcd" in p for p in stamps["detail"]["problems"]))
        self.assertEqual(section.failing(), ["runs:%s:fragment_integrity" % run,
                                             "runs:%s:stage_runtime_stamps" % run])

    def test_torn_or_temporary_history_entry_fails(self):
        run = core.OWNERS[0]
        history = self.repo.fragments_dir(run) / "history"
        (history / "assembly.x.20260101T000002.000000Z.1.json").write_text("{torn", encoding="utf-8")
        (history / "authorization.start.json.tmp-1-2-abc").write_text("{torn", encoding="utf-8")
        section = runs.collect_runs(self.repo.context())
        result = check(section, "runs:%s:fragment_integrity" % run)
        self.assertEqual(result["status"], core.FAIL)
        self.assertEqual(result["detail"]["stray_files"], ["history/authorization.start.json.tmp-1-2-abc"])
        self.assertEqual(result["detail"]["history_entries"], 3)
        problems = [p["problem"] for p in result["detail"]["problems"]]
        self.assertIn("unreadable history entry: JSONDecodeError", problems)
        self.assertEqual(section.failing(), ["runs:%s:fragment_integrity" % run])

    def test_stamp_under_another_stage_name_fails(self):
        """A stamp copied under another stage's file name: fingerprint and
        content hash still reproduce, only the file-name binding and the
        duplicate stage reveal it."""
        run = core.PILOT
        content = read_json(self.repo.fragments_dir(run) / "runtime.stage.static.main.json")["content"]
        self.repo.fragment(run, "runtime.stage.enhanced.json", "runtime", "stage.enhanced", content,
                           content["stage_runtime_sha256"])
        self.repo.rebind(run)
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(check(section, "runs:%s:fragment_integrity" % run)["status"], core.PASS)
        result = check(section, "runs:%s:stage_runtime_stamps" % run)
        self.assertEqual(result["status"], core.FAIL)
        self.assertEqual(result["detail"]["stages"], ["correctness", "static.main", "static.main"])
        problems = result["detail"]["problems"]
        self.assertTrue(any("not the stage of its file name" in p for p in problems), problems)
        self.assertTrue(any("stamped more than once" in p for p in problems), problems)
        self.assertEqual(section.failing(), ["runs:%s:stage_runtime_stamps" % run])

    def test_loader_failure_detail_carries_no_absolute_path(self):
        run = core.OWNERS[2]
        (self.root / core.RUN_REGISTRY[run]["contract"]).unlink()
        (self.root / runs.FROZEN_SPECS_REL).unlink()
        section = runs.collect_runs(self.repo.context())
        detail = check(section, "runs:%s:frozen_contract" % run)["detail"]
        self.assertIn("ContractDrift", detail)
        self.assertIn(core.RUN_REGISTRY[run]["contract"], detail)
        self.assertNotIn(self.root.as_posix(), detail)
        specs = check(section, "runs:enhanced_specs_uniform")["detail"]
        self.assertIn(runs.FROZEN_SPECS_REL, specs)
        self.assertNotIn(self.root.as_posix(), specs)

    def test_authorization_fragment_tampered_fails_integrity(self):
        run = core.OWNERS[3]
        path = self.repo.fragments_dir(run) / "authorization.start.json"
        fragment = read_json(path)
        fragment["content"]["decision"] = ra.DECISION_REFUSED  # fingerprint and content hash stale
        write_json(path, fragment)
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(check(section, "runs:%s:authorization" % run)["status"], core.FAIL)
        self.assertEqual(check(section, "runs:%s:fragment_integrity" % run)["status"], core.FAIL)

    def test_authorization_fragment_missing_fails(self):
        (self.repo.fragments_dir(core.PHASE2) / "authorization.start.json").unlink()
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(check(section, "runs:full_ext_phase2_001:authorization")["status"], core.FAIL)
        self.assertEqual(check(section, "runs:full_ext_phase2_001:stage_runtime_stamps")["status"], core.FAIL)
        integrity = check(section, "runs:full_ext_phase2_001:fragment_integrity")
        self.assertEqual(integrity["status"], core.FAIL)
        self.assertTrue(any(p["problem"] == "registered in the snapshot but not on disk"
                            for p in integrity["detail"]["problems"]))

    def test_config_outside_study_tree_fails_authorization(self):
        ctx = self.repo.context()
        ctx.run_config = lambda run: OrderedDict([("outputs", OrderedDict([("intermediate_dir", "thesis/results/elsewhere")]))])
        section = runs.collect_runs(ctx)
        for run in core.RUNS:
            self.assertIn("not the study tree", check(section, "runs:%s:authorization" % run)["detail"])

    def test_runtime_identity_divergence_fails(self):
        """One run bound consistently (contract, authorization, evidence,
        stamps, snapshot) to another repair condition: every per-run check
        passes, only the cross-run identity fails."""
        run = core.OWNERS[2]
        self.repo.make_run(run, identity=OTHER_IDENTITY)
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(section.failing(), ["runs:runtime_identity_uniform"])
        detail = check(section, "runs:runtime_identity_uniform")["detail"]
        self.assertIsNone(detail["values"]["repair_cond"])
        self.assertIsNone(detail["values"]["fresh_rt"])
        self.assertEqual(detail["values"]["static_cond"], ST)
        self.assertFalse(detail["per_run"][run]["repair_cond"])
        self.assertTrue(detail["per_run"][run]["static_cond"])
        self.assertTrue(detail["per_run"][core.PILOT]["static_cond"])
        for other in core.RUNS:
            self.assertEqual(check(section, "runs:%s:runtime_t0" % other)["status"], core.PASS)

    def test_runtime_identity_edited_in_snapshot_only_fails_closed(self):
        """The old shape of the divergence (a sha edited in the snapshot alone)
        is caught by the snapshot reconciliation and the T0 fingerprint too."""
        run = core.OWNERS[2]
        manifest = self.repo.manifest(run)
        manifest["runtime_evidence"]["repair_condition_sha256"] = sha("other repair")
        self.repo.write_manifest(run, manifest)
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(section.failing(), ["runs:%s:fragment_integrity" % run, "runs:%s:runtime_t0" % run,
                                             "runs:runtime_identity_uniform"])
        t0 = check(section, "runs:%s:runtime_t0" % run)["detail"]
        self.assertFalse(t0["fingerprint_reproduces"])
        self.assertTrue(any("runtime repair condition" in p for p in t0["bound_t0_problems"]))

    def test_runtime_identity_reference_mismatch_fails(self):
        document = read_json(self.root / runs.ORIGIN_READINESS_REL)
        document["runtime_condition_sha256"] = sha("another runtime")
        write_json(self.root / runs.ORIGIN_READINESS_REL, document)
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(section.failing(), ["runs:runtime_identity_uniform"])
        problems = check(section, "runs:runtime_identity_uniform")["detail"]["problems"]
        self.assertTrue(any(runs.ORIGIN_READINESS_REL in p for p in problems))

    def test_runtime_t0_probe_not_ok_fails(self):
        manifest = self.repo.manifest(core.PILOT)
        manifest["runtime_evidence"]["probe_status"] = "DEGRADED"
        manifest["runtime_evidence"]["fresh_runtime_condition_sha256"] = sha("fresh elsewhere")
        self.repo.write_manifest(core.PILOT, manifest)
        section = runs.collect_runs(self.repo.context())
        result = check(section, "runs:pilot_002:runtime_t0")
        self.assertEqual(result["status"], core.FAIL)
        native = [c for c in result["detail"]["native"] if c["check"] == "runtime_evidence_bound_at_t0"][0]
        self.assertEqual(native["status"], "FAIL")
        self.assertIn("runs:runtime_identity_uniform", section.failing())

    def test_methodical_config_drift_fails(self):
        manifest = self.repo.manifest(core.PHASE2)
        manifest["config_drift"] = [OrderedDict([("stage", "enhanced"), ("changed_keys", ["stages.enhanced_tests.jobs"])])]
        self.repo.write_manifest(core.PHASE2, manifest)
        section = runs.collect_runs(self.repo.context())
        result = check(section, "runs:full_ext_phase2_001:runtime_t0")
        self.assertEqual(result["status"], core.FAIL)
        self.assertTrue(any("methodical_config_drift=FAIL" in p for p in result["detail"]["problems"]))

    def test_stamp_drift_fails(self):
        contract_sha = self.repo.contract_document(core.PILOT)["contract_sha256"]
        auth_sha = self.repo.manifest(core.PILOT)["authorization_sha256"]
        self.repo.stamp(core.PILOT, "dynamic", contract_sha, auth_sha, match=False, drift_fields=["image_id"])
        self.repo.rebind(core.PILOT)
        section = runs.collect_runs(self.repo.context())
        result = check(section, "runs:pilot_002:stage_runtime_stamps")
        self.assertEqual(result["status"], core.FAIL)
        self.assertEqual(result["detail"]["stages"], ["correctness", "dynamic", "static.main"])
        self.assertTrue(any("match is False" in p for p in result["detail"]["problems"]))
        self.assertEqual(section.failing(), ["runs:pilot_002:stage_runtime_stamps"])

    def test_stamp_added_without_registration_fails_integrity(self):
        contract_sha = self.repo.contract_document(core.PILOT)["contract_sha256"]
        auth_sha = self.repo.manifest(core.PILOT)["authorization_sha256"]
        self.repo.stamp(core.PILOT, "dynamic", contract_sha, auth_sha)
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(section.failing(), ["runs:pilot_002:fragment_integrity"])
        problems = check(section, "runs:pilot_002:fragment_integrity")["detail"]["problems"]
        self.assertEqual([p["problem"] for p in problems], ["on disk but not registered in the snapshot"])

    def test_stamp_fingerprint_stale_fails(self):
        path = self.repo.fragments_dir(core.PILOT) / "runtime.stage.correctness.json"
        fragment = read_json(path)
        fragment["content"]["stage_runtime_sha256"] = sha("stale")
        write_json(path, fragment)
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(check(section, "runs:pilot_002:stage_runtime_stamps")["status"], core.FAIL)
        self.assertEqual(check(section, "runs:pilot_002:fragment_integrity")["status"], core.FAIL)

    def test_no_stamp_fails(self):
        for path in self.repo.fragments_dir(core.OWNERS[0]).glob("runtime.stage.*.json"):
            path.unlink()
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(check(section, "runs:full_ext_recovery_001:stage_runtime_stamps")["status"], core.FAIL)
        self.assertEqual(check(section, "runs:full_ext_recovery_001:fragment_integrity")["status"], core.FAIL)

    def test_enhanced_specs_divergence_fails(self):
        manifest = self.repo.manifest(core.PILOT)
        manifest["enhanced_specs"]["sha256"] = sha("other specs")
        self.repo.write_manifest(core.PILOT, manifest)
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(section.failing(), ["runs:enhanced_specs_uniform"])

    def test_enhanced_specs_frozen_file_mismatch_fails(self):
        (self.root / runs.FROZEN_SPECS_REL).write_bytes(b'{"changed": true}\n')
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(section.failing(), ["runs:enhanced_specs_uniform"])
        problems = check(section, "runs:enhanced_specs_uniform")["detail"]["problems"]
        self.assertTrue(any("raw sha256" in p for p in problems))

    def test_enhanced_specs_recorded_cache_copy_is_compared_when_present(self):
        cache = self.root / "thesis/results/cache/enhanced/specs.jsonl"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(SPECS_BYTES)
        section = runs.collect_runs(self.repo.context())
        detail = check(section, "runs:enhanced_specs_uniform")["detail"]
        self.assertEqual(detail["recorded_paths_present"], ["thesis/results/cache/enhanced/specs.jsonl"])
        self.assertEqual(section.failing(), [])
        cache.write_bytes(b'{"different": 1}\n')
        section = runs.collect_runs(self.repo.context())
        self.assertEqual(section.failing(), ["runs:enhanced_specs_uniform"])


class PureCheckTest(unittest.TestCase):
    def test_models_check(self):
        self.assertTrue(runs.models_check(list(core.MODELS), core.PILOT)[0])
        self.assertTrue(runs.models_check(list(reversed(core.MODELS)), core.PHASE2)[0])
        self.assertFalse(runs.models_check(list(core.MODELS)[:3], core.PILOT)[0])
        self.assertTrue(runs.models_check(list(core.MODELS)[:3], core.OWNERS[1])[0])
        ok, detail = runs.models_check(["nobody"], core.OWNERS[1])
        self.assertFalse(ok)
        self.assertTrue(any("unknown models" in p for p in detail["problems"]))
        self.assertFalse(runs.models_check([], core.OWNERS[1])[0])
        self.assertFalse(runs.models_check([MODEL, MODEL], core.OWNERS[1])[0])
        self.assertFalse(runs.models_check(None, core.OWNERS[3])[0])

    def test_stamp_problems(self):
        repo = Repo(tempfile.mkdtemp(prefix="study_closure_stamp_"))
        try:
            contract_sha, auth_sha = sha("contract"), sha("auth")
            good = repo.stamp_content(core.PILOT, "enhanced", contract_sha, auth_sha)
            self.assertEqual(runs.stamp_problems(good, core.PILOT, contract_sha, auth_sha), [])
            self.assertTrue(runs.stamp_problems(good, core.PARENT, contract_sha, auth_sha))
            self.assertTrue(runs.stamp_problems(good, core.PILOT, sha("x"), auth_sha))
            self.assertTrue(runs.stamp_problems(good, core.PILOT, contract_sha, None))
            bad = repo.stamp_content(core.PILOT, "enhanced", contract_sha, auth_sha, match=False)
            self.assertTrue(any("match" in p for p in runs.stamp_problems(bad, core.PILOT, contract_sha, auth_sha)))
            stale = OrderedDict(good)
            stale["domains"] = OrderedDict()  # content changed after fingerprinting
            self.assertTrue(any("reproduce" in p for p in runs.stamp_problems(stale, core.PILOT, contract_sha, auth_sha)))
        finally:
            shutil.rmtree(repo.root, ignore_errors=True)

    def test_runtime_identity(self):
        entry = OrderedDict([("readiness_rt", RT), ("fresh_rt", RT), ("static_cond", ST), ("repair_cond", RP)])
        values = OrderedDict((run, OrderedDict(entry)) for run in core.RUNS)
        references = OrderedDict([("readiness_rt", OrderedDict([("doc:a", RT)])), ("fresh_rt", OrderedDict([("doc:a", RT)])),
                                  ("static_cond", OrderedDict([("doc:b", ST)])), ("repair_cond", OrderedDict([("doc:b", RP)]))])
        ok, detail = runs.runtime_identity(values, references)
        self.assertTrue(ok, detail["problems"])
        self.assertEqual(detail["values"], entry)
        values[core.OWNERS[3]]["static_cond"] = sha("other static")
        ok, detail = runs.runtime_identity(values, references)
        self.assertFalse(ok)
        self.assertIsNone(detail["values"]["static_cond"])
        self.assertFalse(detail["per_run"][core.OWNERS[3]]["static_cond"])
        values[core.OWNERS[3]]["static_cond"] = ST
        references["repair_cond"]["doc:c"] = sha("other repair")
        self.assertFalse(runs.runtime_identity(values, references)[0])
        values[core.PILOT]["fresh_rt"] = None
        self.assertFalse(runs.runtime_identity(values, OrderedDict())[0])
        self.assertFalse(runs.runtime_identity(OrderedDict(), OrderedDict())[0])

    def test_enhanced_specs_uniform(self):
        records = OrderedDict((run, OrderedDict([("path", "p"), ("sha256", SPECS_SHA), ("spec_count", 3)])) for run in core.RUNS)
        references = OrderedDict([("frozen", SPECS_SHA), ("contract", SPECS_SHA)])
        ok, detail = runs.enhanced_specs_uniform(records, references)
        self.assertTrue(ok, detail["problems"])
        self.assertEqual(detail["sha256"], SPECS_SHA)
        records[core.PHASE2]["sha256"] = sha("x")
        self.assertFalse(runs.enhanced_specs_uniform(records, references)[0])
        records[core.PHASE2]["sha256"] = SPECS_SHA
        references["freeze"] = None
        ok, detail = runs.enhanced_specs_uniform(records, references)
        self.assertFalse(ok)
        self.assertTrue(any("freeze" in p for p in detail["problems"]))
        records[core.PILOT] = None
        self.assertFalse(runs.enhanced_specs_uniform(records, OrderedDict())[0])

    def test_manifest_and_contract_checks(self):
        manifest = OrderedDict([("run_id", core.PILOT), ("complete", True), ("missing_expected_fragments", []),
                                ("unexpected_fragments", []), ("git_dirty", False), ("fragments", {"a": 1})])
        self.assertTrue(runs.manifest_check(manifest, core.PILOT)[0])
        for key, value in (("complete", None), ("missing_expected_fragments", None), ("unexpected_fragments", ["x"]),
                           ("git_dirty", None), ("run_id", core.PARENT)):
            broken = OrderedDict(manifest)
            broken[key] = value
            self.assertFalse(runs.manifest_check(broken, core.PILOT)[0], key)
        contract = OrderedDict([("run_id", core.PILOT), ("status", "READY"), ("profile", "pilot"),
                                ("contract_sha256", sha("c")), ("model_ids", list(core.MODELS))])
        self.assertTrue(runs.contract_check(contract, core.PILOT, "pilot", sha("c"))[0])
        self.assertFalse(runs.contract_check(contract, core.PILOT, "pilot", sha("d"))[0])
        self.assertFalse(runs.contract_check(contract, core.PILOT, "pilot", None)[0])
        self.assertFalse(runs.contract_check(contract, core.PILOT, "full_extension", sha("c"))[0])
        contract["status"] = "NOT_READY"
        self.assertFalse(runs.contract_check(contract, core.PILOT, "pilot", sha("c"))[0])

    def test_authorization_check(self):
        auth_sha = sha("auth")
        state = OrderedDict([("present", True), ("decision", ra.DECISION_ALLOWED), ("authorization_sha256", auth_sha),
                             ("recomputed_sha256", auth_sha), ("frozen_contract_sha256", sha("c"))])
        fragment = OrderedDict([("content", OrderedDict([("run_id", core.PILOT), ("authorization_sha256", auth_sha)]))])
        self.assertTrue(runs.authorization_check(state, fragment, core.PILOT, sha("c"), auth_sha)[0])
        self.assertFalse(runs.authorization_check(state, fragment, core.PILOT, sha("other"), auth_sha)[0])
        self.assertFalse(runs.authorization_check(state, fragment, core.PILOT, sha("c"), sha("other"))[0])
        self.assertFalse(runs.authorization_check(state, fragment, core.PARENT, sha("c"), auth_sha)[0])
        self.assertFalse(runs.authorization_check(OrderedDict([("present", False)]), None, core.PILOT, sha("c"), auth_sha)[0])
        refused = OrderedDict(state)
        refused["decision"] = ra.DECISION_REFUSED
        self.assertFalse(runs.authorization_check(refused, fragment, core.PILOT, sha("c"), auth_sha)[0])
        tampered = OrderedDict(state)
        tampered["recomputed_sha256"] = sha("different")
        self.assertFalse(runs.authorization_check(tampered, fragment, core.PILOT, sha("c"), auth_sha)[0])


# -- tree section ------------------------------------------------------------------------

class TreeSectionTest(SyntheticRepoTest):
    def test_fixture_tree_passes(self):
        ctx = self.repo.context()
        section = runs.collect_tree(ctx)
        self.assertEqual(section.failing(), [])
        intermediate = check(section, "tree:intermediate_scope")["detail"]
        self.assertEqual(intermediate["counts"], OrderedDict([("study", len(core.RUNS) + len(ITERATIONS)),
                                                              ("excluded", 1), ("out_of_study", 1),
                                                              ("forbidden", 0), ("unexplained", 0)]))
        self.assertTrue(intermediate["locks_dir_present"])
        raw = check(section, "tree:raw_scope")["detail"]
        self.assertEqual(raw["study"], sorted([core.PILOT, core.PARENT] + list(ITERATIONS)))
        self.assertEqual(raw["out_of_study"], ["model_check_001", "smoke_001__static_feedback__iter1"])
        self.assertEqual(raw["excluded"], [EXCLUDED])
        inventory = section.data["phase2_inventory"]
        self.assertGreater(inventory["file_count"], 0)
        self.assertTrue(all(rel.startswith(core.PHASE2_RESULTS_REL + "/") for rel in inventory["files"]))
        self.assertEqual(inventory["inventory_sha256"], canonical_sha256(inventory["files"]))
        self.assertEqual(inventory["total_bytes"], sum(e["size"] for e in inventory["files"].values()))
        self.assertEqual(check(section, "tree:phase2_results_inventory")["detail"]["inventory_sha256"],
                         inventory["inventory_sha256"])
        self.assertEqual(section.data["excluded_answers"], OrderedDict([(EXCLUDED, 2)]))
        excluded = check(section, "tree:excluded_parent_repair_present_not_adopted")["detail"]
        self.assertEqual(excluded["assembly_rows"], 2 + 2 * len(ITERATIONS))
        self.assertEqual(excluded["foreign_rows"], 0)
        self.assertEqual(excluded["excluded_references"], 0)
        json.dumps(core.json_stable(section.document()))

    def test_inventory_is_deterministic(self):
        first = runs.tree_inventory(self.root, core.PHASE2_RESULTS_REL)
        second = runs.tree_inventory(self.root, core.PHASE2_RESULTS_REL)
        self.assertEqual(json.dumps(first), json.dumps(second))
        self.assertEqual(list(first), sorted(first))

    def test_unexplained_directory_fails(self):
        (self.repo.intermediate / "mystery_run").mkdir()
        section = runs.collect_tree(self.repo.context())
        self.assertEqual(section.failing(), ["tree:intermediate_scope"])
        self.assertEqual(check(section, "tree:intermediate_scope")["detail"]["unexplained"], ["mystery_run"])

    def test_phase2_under_raw_fails(self):
        (self.repo.raw / core.PHASE2).mkdir()
        section = runs.collect_tree(self.repo.context())
        self.assertEqual(section.failing(), ["tree:raw_scope"])
        self.assertEqual(check(section, "tree:raw_scope")["detail"]["forbidden"], [core.PHASE2])

    def test_missing_required_run_fails(self):
        shutil.rmtree(self.repo.raw / core.PARENT)
        section = runs.collect_tree(self.repo.context())
        self.assertIn("tree:raw_scope", section.failing())
        self.assertEqual(check(section, "tree:raw_scope")["detail"]["missing_required"], [core.PARENT])

    def test_temporary_file_in_phase2_tree_fails(self):
        (self.repo.intermediate / core.PHASE2 / MODEL / "enhanced_tests.jsonl.tmp-123-4-abcd").write_text("x")
        section = runs.collect_tree(self.repo.context())
        self.assertEqual(section.failing(), ["tree:phase2_results_inventory"])
        listed = check(section, "tree:phase2_results_inventory")["detail"]["temporary_or_torn"]
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0].endswith(".tmp-123-4-abcd"))

    def test_torn_archive_in_phase2_tree_fails(self):
        (self.repo.intermediate / core.PHASE2 / MODEL / "enhanced_tests.jsonl.torn").write_text("x")
        section = runs.collect_tree(self.repo.context())
        self.assertEqual(section.failing(), ["tree:phase2_results_inventory"])

    def test_lock_file_fails_but_archived_lock_does_not(self):
        locks = self.repo.intermediate / runs.LOCKS_DIR_NAME
        (locks / "full_ext_phase2_001.writer.lock.interrupted-20261014T011442Z").write_text("x")
        section = runs.collect_tree(self.repo.context())
        self.assertEqual(section.failing(), [])
        detail = check(section, "tree:no_successor_locks")["detail"]
        self.assertEqual(detail["other_entries"], ["full_ext_phase2_001.writer.lock.interrupted-20261014T011442Z"])
        (locks / "full_ext_phase2_001.writer.lock").write_text("x")
        section = runs.collect_tree(self.repo.context())
        self.assertEqual(section.failing(), ["tree:no_successor_locks"])
        self.assertEqual(check(section, "tree:no_successor_locks")["detail"]["lock_files"],
                         ["full_ext_phase2_001.writer.lock"])

    def test_assembly_row_referencing_excluded_run_fails(self):
        self.repo.assembly(ITERATIONS[1], MODEL, ["s0"], source_run=EXCLUDED)
        section = runs.collect_tree(self.repo.context())
        self.assertEqual(section.failing(), ["tree:excluded_parent_repair_present_not_adopted"])
        detail = check(section, "tree:excluded_parent_repair_present_not_adopted")["detail"]
        self.assertEqual(detail["excluded_references"], 1)
        self.assertEqual(detail["foreign_rows"], 1)
        self.assertEqual(detail["foreign_examples"][0]["file"],
                         "%s/%s/%s/assembly.jsonl" % (core.INTERMEDIATE_REL, ITERATIONS[1], MODEL))

    def test_assembly_row_pointing_at_another_study_run_fails(self):
        self.repo.assembly(ITERATIONS[0], MODEL, ["s0"], source_run=core.PILOT)
        section = runs.collect_tree(self.repo.context())
        detail = check(section, "tree:excluded_parent_repair_present_not_adopted")["detail"]
        self.assertEqual(detail["foreign_rows"], 1)
        self.assertEqual(detail["excluded_references"], 0)
        self.assertEqual(section.failing(), ["tree:excluded_parent_repair_present_not_adopted"])

    def test_excluded_run_as_target_source_fails(self):
        ctx = self.repo.context()
        ctx._table = FakeTable([core.PILOT, EXCLUDED])
        section = runs.collect_tree(ctx)
        self.assertEqual(section.failing(), ["tree:excluded_parent_repair_present_not_adopted"])

    def test_excluded_run_absent_fails(self):
        shutil.rmtree(self.repo.raw / EXCLUDED)
        section = runs.collect_tree(self.repo.context())
        self.assertIn("tree:excluded_parent_repair_present_not_adopted", section.failing())
        self.assertIn("tree:raw_scope", [c["check"] for c in section.checks])

    def test_classify_dirs(self):
        names = ["pilot_002", "pilot_002__test_feedback__iter2", "full_ext_recovery_003__static_feedback__iter2",
                 "full_ext_phase2_001", EXCLUDED, "pilot_001__combined_feedback__iter1", "smoke_004",
                 "repair_smoke_001__static_feedback__iter1", "model_check_001", "pilot_002__static_feedback__iter3",
                 "full_ext_001__test_feedback__iter1", "pilot_002__weird__iter1", "zzz"]
        classes = runs.classify_dirs(names, "intermediate")
        self.assertEqual(classes["study"], ["full_ext_phase2_001", "full_ext_recovery_003__static_feedback__iter2",
                                            "pilot_002", "pilot_002__test_feedback__iter2"])
        self.assertEqual(classes["excluded"], [EXCLUDED])
        self.assertEqual(classes["out_of_study"], ["model_check_001", "pilot_001__combined_feedback__iter1",
                                                   "repair_smoke_001__static_feedback__iter1", "smoke_004"])
        self.assertEqual(classes["forbidden"], [])
        self.assertEqual(classes["unexplained"], ["full_ext_001__test_feedback__iter1",
                                                  "pilot_002__static_feedback__iter3", "pilot_002__weird__iter1", "zzz"])
        self.assertEqual(runs.classify_dirs(["full_ext_phase2_001"], "raw")["forbidden"], ["full_ext_phase2_001"])
        self.assertEqual(runs.classify_dirs(["pilot_002__static_feedback__iter01"], "intermediate")["unexplained"],
                         ["pilot_002__static_feedback__iter01"])
        with self.assertRaises(core.ClosureRefused):
            runs.classify_dirs([], "processed")
        self.assertTrue(runs.is_study_iteration("full_ext_recovery_001__combined_feedback__iter1"))
        self.assertFalse(runs.is_study_iteration("full_ext_recovery_001__combined_feedback__iter"))
        self.assertFalse(runs.is_study_iteration("full_ext_recovery_001__combined_feedback__iter0"))
        # only the canonical spelling the study produces (targets.iteration_run)
        self.assertFalse(runs.is_study_iteration("pilot_002__static_feedback__iter01"))
        self.assertFalse(runs.is_study_iteration("pilot_002__static_feedback__iter001"))
        from thesis.recovery_successor_005 import targets as pt
        for number in range(1, pl.MAX_ITERATIONS + 1):
            self.assertTrue(runs.is_study_iteration(pt.iteration_run(core.OWNERS[0], core.VARIANTS[0], number)))


# -- identity section --------------------------------------------------------------------

class IdentityTest(unittest.TestCase):
    def test_provider_scan_catches_forbidden_import_and_name(self):
        tmp = Path(tempfile.mkdtemp(prefix="study_closure_scan_"))
        try:
            (tmp / "a.py").write_text("import openai\n", encoding="utf-8")
            (tmp / "b.py").write_text("from dotenv import load_dotenv\n", encoding="utf-8")
            # the chokepoint name is spelled only as text here (this test module is scanned too)
            (tmp / "c.py").write_text("from thesis.evaluation import run_authorization as ra\n"
                                      "x = ra.%s\n" % ("bootstrap_provider" + "_run"), encoding="utf-8")
            (tmp / "d.py").write_text("import json\nfrom thesis.repair import orchestrator\n", encoding="utf-8")
            scanned, offending = runs.provider_scan(tmp)
            self.assertEqual(scanned, ["a.py", "b.py", "c.py", "d.py"])
            # the native rule names the module and the imported attribute
            for expected in ("a.py imports openai", "b.py imports dotenv", "b.py imports dotenv.load_dotenv",
                             "c.py references bootstrap_provider" + "_run"):
                self.assertIn(expected, offending)
            self.assertEqual([o for o in offending if o.startswith("d.py")], [])
            self.assertEqual(len(offending), 4)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_source_pins_require_every_reused_module(self):
        tmp = Path(tempfile.mkdtemp(prefix="study_closure_pins_"))
        try:
            ok, detail, pins = runs.source_pins(tmp)
            self.assertFalse(ok)
            self.assertIsNone(pins)
            self.assertEqual(detail["missing"], list(core.REUSED_MODULES)[:runs.EXAMPLES])
            for rel in core.REUSED_MODULES:
                (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
                (tmp / rel).write_text("# pinned\n", encoding="utf-8")
            ok, detail, pins = runs.source_pins(tmp)
            self.assertFalse(ok)  # no closure module yet
            (tmp / runs.PACKAGE_REL).mkdir(parents=True)
            (tmp / runs.PACKAGE_REL / "core.py").write_text("x = 1\n", encoding="utf-8")
            ok, detail, pins = runs.source_pins(tmp)
            self.assertTrue(ok)
            self.assertEqual(detail["reused_modules"], len(core.REUSED_MODULES))
            self.assertEqual(list(pins["closure"]), [runs.PACKAGE_REL + "/core.py"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_git_identity_requires_clean_worktree_only_in_write_mode(self):
        """The write-mode gating over a stubbed core.git_state (no git
        command is run by the tests: ground rule 3)."""
        original = core.git_state

        def state(clean):
            paths = [] if clean else ["untracked.txt"]
            return lambda root: OrderedDict([("head", "0" * 40), ("branch", "fixture"), ("clean", clean),
                                             ("uncommitted_paths", paths), ("uncommitted_count", len(paths))])

        try:
            core.git_state = state(True)
            ok, detail, observed = runs.git_identity(REPO_ROOT, True)
            self.assertTrue(ok, detail)
            self.assertTrue(observed["clean"])
            self.assertEqual((detail["mode"], detail["clean_required"]), ("write", True))
            core.git_state = state(False)
            ok, detail, observed = runs.git_identity(REPO_ROOT, True)
            self.assertFalse(ok)
            self.assertEqual(observed["uncommitted_paths"], ["untracked.txt"])
            ok, detail, _ = runs.git_identity(REPO_ROOT, False)
            self.assertTrue(ok)
            self.assertEqual((detail["mode"], detail["clean_required"]), ("dry-run", False))
        finally:
            core.git_state = original

    def test_identity_section_fails_closed_without_git(self):
        tmp = Path(tempfile.mkdtemp(prefix="study_closure_identity_"))
        try:
            ctx = core.Context(tmp, OrderedDict([("models", [])]), tmp / "config.yaml")
            section = runs.collect_identity(ctx)
            self.assertEqual([c["check"] for c in section.checks],
                             ["identity:git_state", "identity:closure_source_pins", "identity:provider_isolation"])
            self.assertEqual(statuses(section)["identity:git_state"], core.FAIL)
            self.assertEqual(statuses(section)["identity:closure_source_pins"], core.FAIL)
            self.assertEqual(statuses(section)["identity:provider_isolation"], core.FAIL)  # no module scanned
            self.assertEqual(section.status, core.FAIL)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_provider_isolation_of_the_real_closure_package(self):
        """Read-only against the real repository: every closure module scans
        clean under a context built with provider isolation (as
        core.load_context builds it); a context whose config loader is NOT
        the no-op fails, and the check never calls that loader."""
        import thesis.config.load_config as loader

        def forbidden(*args, **kwargs):
            raise AssertionError("the check must never call a loader that is not the no-op")

        try:
            pl.isolate_providers()
            ok, detail = runs.provider_isolation(REPO_ROOT, OrderedDict([("models", [])]))
            self.assertTrue(ok, detail)
            self.assertIn("runs.py", detail["modules_scanned"])
            self.assertIn("test_runs.py", detail["modules_scanned"])
            self.assertTrue(detail["dotenv_disabled"])
            self.assertEqual(detail["dotenv_loader_module"], pl.__name__)
            loader.load_dotenv = forbidden
            ok, detail = runs.provider_isolation(REPO_ROOT, OrderedDict([("models", [])]))
            self.assertFalse(ok)
            self.assertFalse(detail["dotenv_disabled"])
            self.assertEqual(detail["dotenv_loader_module"], __name__)
            self.assertEqual(detail["offending"], [])
            # the check did not re-install the no-op behind the context's back
            self.assertIs(loader.load_dotenv, forbidden)
        finally:
            pl.isolate_providers()

    def test_collect_returns_the_three_sections_in_order(self):
        tmp = tempfile.mkdtemp(prefix="study_closure_collect_")
        try:
            repo = Repo(tmp)
            sections = runs.collect(repo.context())
            self.assertEqual([s.name for s in sections], ["identity", "runs", "tree"])
            self.assertEqual([s.status for s in sections[1:]], [core.PASS, core.PASS])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# -- real repository (read-only) -----------------------------------------------------------

class RealRepositoryTest(unittest.TestCase):
    """Read-only facts of the real repository (allowed by the specification)."""

    def test_real_results_tree_has_no_unexplained_directory(self):
        """Read-only against the real repository: every results directory is explained."""
        for relative, area in ((core.INTERMEDIATE_REL, "intermediate"), (core.RAW_REL, "raw")):
            names, files, _locks = runs.list_area(REPO_ROOT, relative)
            classes = runs.classify_dirs(names, area)
            self.assertEqual(classes["unexplained"], [], relative)
            self.assertEqual(classes["forbidden"], [], relative)
            self.assertEqual(files, [], relative)
            self.assertEqual(classes["excluded"], list(core.EXCLUDED_RUNS))
        study = runs.classify_dirs(runs.list_area(REPO_ROOT, core.INTERMEDIATE_REL)[0], "intermediate")["study"]
        self.assertTrue(set(core.RUNS) <= set(study))

    def test_real_runtime_identity_is_uniform(self):
        """Read-only against the real repository: one runtime identity across the seven manifests."""
        values = OrderedDict()
        for run in core.RUNS:
            evidence = core.read_json(REPO_ROOT, "%s/%s/run_manifest.json" % (core.INTERMEDIATE_REL, run))["runtime_evidence"]
            values[run] = OrderedDict((key, evidence.get(field)) for key, field in runs.RUNTIME_FIELDS.items())
        ok, detail = runs.runtime_identity(values, runs.runtime_references(REPO_ROOT))
        self.assertTrue(ok, detail["problems"])
        for value in detail["values"].values():
            self.assertRegex(value, SHA_RE)
        self.assertEqual(detail["values"]["readiness_rt"], detail["values"]["fresh_rt"])


if __name__ == "__main__":
    unittest.main()
