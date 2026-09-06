"""Tests: newline/hash discipline, assembly integrity and provenance,
crash safety, base/repair cleaning parity, manifest binding of assembly
sets (pilot_002 pre-run wave).

Run:  python thesis/assembly/test_assembly_provenance.py
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.assembly import assemble_sources as asm  # noqa: E402
from thesis.assembly import assembly_provenance as ap  # noqa: E402
from thesis.assembly import cleaning  # noqa: E402
from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import condition_hashing as ch  # noqa: E402
from thesis.evaluation import run_manifest  # noqa: E402
from thesis.generation import common  # noqa: E402

FAILURES = []


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


PROMPT = ("#include <vector>\n/* Compute the sum of the elements of x. */\n"
          "double sumOf(std::vector<double> const& x) {")
RAW = ("```cpp\ndouble sumOf(std::vector<double> const& x) {\n  double s = 0;\n"
       "  for (auto v : x) s += v;\n  return s;\n}\n```")
RAW2 = RAW.replace("s += v", "s = s + v")
MODEL = "m"


def sid(exec_model="serial", i=0):
    return "%s__reduce__01_reduce_sum__%s__sample_%d" % (MODEL, exec_model, i)


def record(sample_id, raw=RAW, ok=True, truncated=False, exec_model="serial"):
    return {
        "sample_id": sample_id,
        "prompt": {"problem_type": "reduce", "name": "01_reduce_sum",
                   "parallelism_model": exec_model, "language": "cpp",
                   "prompt_text": PROMPT},
        "output": {"raw_text": raw},
        "status": {"success": ok, "truncated": truncated,
                   "error_type": None if ok else "ModelRefusal"},
        "generation_parameters": {"sample_index": 0},
    }


class World:
    def __init__(self, tmp, run_id="r1"):
        self.tmp = Path(tmp)
        self.run_id = run_id
        self.config = {
            "outputs": {"raw_dir": (self.tmp / "raw").as_posix(),
                        "intermediate_dir": (self.tmp / "inter").as_posix()},
            "stages": {"assembly": {"auto_close_single_brace": True}},
            "models": [{"id": MODEL, "enabled": True}],
        }
        self.profile = {"run_id": run_id}
        self.model = {"id": MODEL}

    def write_records(self, records, run_id=None):
        prof = {"run_id": run_id or self.run_id}
        path, _ = common.get_output_paths(self.config, prof, self.model)
        if path.exists():
            path.unlink()
        for r in records:
            common.append_jsonl(path, r)

    def assemble(self, run_id=None, register=False):
        prof = {"run_id": run_id or self.run_id}
        return asm.assemble_model(self.config, prof, self.model, False,
                                  register_manifest=register)

    def model_dir(self, run_id=None):
        return self.tmp / "inter" / (run_id or self.run_id) / MODEL

    def entries(self, run_id=None):
        return {e["sample_id"]: e
                for e in ap.load_assembly_entries(self.model_dir(run_id) / "assembly.jsonl")}

    def source(self, sample_id, run_id=None):
        return self.model_dir(run_id) / "sources" / sample_id / "generated-code.hpp"


def main():
    print("== newline / hash discipline ==")
    check("LF classified", ch.newline_convention(b"a\nb\n") == "LF")
    check("CRLF classified", ch.newline_convention(b"a\r\nb\r\n") == "CRLF")
    check("MIXED classified", ch.newline_convention(b"a\r\nb\n") == "MIXED")
    check("lone CR is OTHER", ch.newline_convention(b"a\rb\n") == "OTHER")
    check("no newline is OTHER", ch.newline_convention(b"abc") == "OTHER")
    check("trailing newline detected", ch.has_trailing_newline(b"x\n") and not ch.has_trailing_newline(b"x"))
    check("condition hash: CRLF and LF checkouts hash identically",
          ch.lf_normalized_sha256_bytes(b"def f():\r\n    pass\r\n")
          == ch.lf_normalized_sha256_bytes(b"def f():\n    pass\n"))
    check("condition hash: lone CR normalized too",
          ch.lf_normalized_sha256_bytes(b"a\rb") == ch.lf_normalized_sha256_bytes(b"a\nb"))
    check("artifact hash: CRLF and LF bytes hash DIFFERENTLY (raw, never normalized)",
          ch.raw_sha256_bytes(b"x\r\n") != ch.raw_sha256_bytes(b"x\n"))
    with tempfile.TemporaryDirectory() as tmp:
        crlf = Path(tmp) / "crlf.py"
        lf = Path(tmp) / "lf.py"
        crlf.write_bytes(b"import os\r\nX = 1\r\n")
        lf.write_bytes(b"import os\nX = 1\n")
        check("file condition entry independent of checkout line endings",
              ch.lf_normalized_sha256(crlf) == ch.lf_normalized_sha256(lf))
        check("file artifact hash depends on the real bytes", ch.raw_sha256(crlf) != ch.raw_sha256(lf))
    check("canonical hash deterministic across key order",
          ch.canonical_sha256({"b": 1, "a": [1, 2]}) == ch.canonical_sha256({"a": [1, 2], "b": 1}))
    check("repo-relative logical path has no drive letter or absolute prefix",
          ":" not in ch.repo_relative(REPO_ROOT / "thesis" / "assembly" / "cleaning.py")
          and ch.repo_relative(REPO_ROOT / "thesis" / "assembly" / "cleaning.py")
          == "thesis/assembly/cleaning.py")

    print("== assembly condition (METHOD) ==")
    cond = ap.assembly_condition({"stages": {"assembly": {"auto_close_single_brace": True}}})
    sha = ap.assembly_condition_sha256(cond)
    cond2 = ap.assembly_condition({"stages": {"assembly": {"auto_close_single_brace": True}}})
    check("condition is deterministic", ap.assembly_condition_sha256(cond2) == sha)
    check("condition version present", cond["condition_version"] == ap.ASSEMBLY_CONDITION_VERSION)
    check("condition names both implementation files by logical path",
          [e["path"] for e in cond["implementation"]][:2]
          == ["thesis/assembly/cleaning.py", "thesis/assembly/assemble_sources.py"])
    check("condition never contains an absolute path, hostname or timestamp",
          all(":" not in e["path"] and not e["path"].startswith("/") for e in cond["implementation"])
          and "created_at" not in json.dumps(cond) and os.linesep not in json.dumps(cond["source_writer"]))
    check("writer policy is stated as HOST_DEPENDENT (measured, not pinned)",
          cond["source_writer"]["newline_policy"] == "HOST_DEPENDENT"
          and asm.ASSEMBLY_WRITER_NEWLINE_HOST_DEPENDENT is True)
    cond_policy = ap.assembly_condition({"stages": {"assembly": {"auto_close_single_brace": False}}})
    check("content-affecting policy changes the condition",
          ap.assembly_condition_sha256(cond_policy) != sha)
    # a changed cleaner implementation changes the condition; a re-checkout
    # with other line endings does not (the entry's logical path is held
    # constant here, only the bytes vary)
    original = ap.CLEANING_PY
    impl_sha = cond["implementation"][0]["lf_normalized_sha256"]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            patched = Path(tmp) / "cleaning.py"
            patched.write_bytes(original.read_bytes() + b"\n# semantic change\n")
            ap.CLEANING_PY = patched
            changed = ap.assembly_condition({"stages": {"assembly": {"auto_close_single_brace": True}}})
            check("cleaner implementation change -> condition change",
                  changed["implementation"][0]["lf_normalized_sha256"] != impl_sha
                  and ap.assembly_condition_sha256(changed) != sha)
            lf_bytes = ch.lf_normalize(original.read_bytes())
            patched.write_bytes(lf_bytes.replace(b"\n", b"\r\n"))
            crlf = ap.assembly_condition({"stages": {"assembly": {"auto_close_single_brace": True}}})
            check("cleaner CRLF re-checkout -> implementation hash unchanged",
                  crlf["implementation"][0]["lf_normalized_sha256"] == impl_sha)
    finally:
        ap.CLEANING_PY = original
    gen = ap.generation_cleaning_condition()
    check("generation cleaning condition pins clean_generated_code and extract_code",
          set(gen["implementation"]) >= {"common.clean_generated_code", "cleaning.extract_code"})
    check("generation cleaning condition pins provider extraction of all adapters",
          all(v is not None for v in gen["provider_extraction"].values())
          and len(gen["provider_extraction"]) == 7)
    check("condition carries the generation cleaning condition sha",
          cond["generation_cleaning_condition_sha256"]
          == ap.generation_cleaning_condition_sha256(gen))

    print("== assembly input identity ==")
    a = ap.assembly_input_sha256(PROMPT, RAW)
    check("assembly input sha deterministic", a == ap.assembly_input_sha256(PROMPT, RAW))
    check("changed raw_text -> different input sha", ap.assembly_input_sha256(PROMPT, RAW2) != a)
    check("truncated flag is part of the input identity (it gates auto-close)",
          ap.assembly_input_sha256(PROMPT, RAW, True) != a)
    check("input sha does not depend on provider metadata",
          ap.assembly_input_sha256_of_record(record(sid())) == a
          and ap.assembly_input_sha256_of_record(
              dict(record(sid()), api_response={"usage": {"x": 1}})) == a)

    print("== A: determinism ==")
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        w1, w2 = World(t1), World(t2)
        for w in (w1, w2):
            w.write_records([record(sid()), record(sid("omp"), exec_model="omp")])
            w.assemble()
        e1, e2 = w1.entries(), w2.entries()
        check("same input, same host, same condition -> identical source bytes",
              w1.source(sid()).read_bytes() == w2.source(sid()).read_bytes())
        check("... identical source_sha256 / input sha / condition sha",
              all(e1[s][k] == e2[s][k] for s in e1
                  for k in ("source_sha256", "assembly_input_sha256", "assembly_condition_sha256"))
              and all(e1[s]["assembled"] for s in e1))
        check("... identical per-model assembly_set_sha256",
              ap.assembly_set_sha256(e1.values()) == ap.assembly_set_sha256(e2.values()))
        check("set fingerprint uses logical paths only (no scratch dir inside)",
              t1 not in json.dumps(ap.assembly_set_projection(e1.values()))
              and all(not Path(r["logical_source_path"]).is_absolute()
                      for r in ap.assembly_set_projection(e1.values())))
        check("schema assembly.v2 with every provenance field",
              e1[sid()]["schema_version"] == "assembly.v2"
              and all(k in e1[sid()] for k in ("assembly_input_sha256", "source_sha256",
                                                "newline_convention", "byte_size",
                                                "logical_source_path", "assembly_condition_sha256",
                                                "trailing_newline", "execution_model", "benchmark")))
        real = w1.source(sid()).read_bytes()
        check("source_sha256 is the hash of the REAL post-write bytes",
              e1[sid()]["source_sha256"] == ch.raw_sha256_bytes(real)
              and e1[sid()]["byte_size"] == len(real)
              and e1[sid()]["newline_convention"] == ch.newline_convention(real))
        expected_convention = "CRLF" if os.linesep == "\r\n" else "LF"
        check("newline_convention reflects this host's writer (%s)" % expected_convention,
              e1[sid()]["newline_convention"] == expected_convention)
        summary = json.loads((w1.model_dir() / "assembly_summary.json").read_text(encoding="utf-8"))
        check("per-model summary carries set sha, counts and condition",
              summary["assembly_set_sha256"] == ap.assembly_set_sha256(e1.values())
              and summary["sample_count"] == 2 and summary["counts"]["records_considered"] == 2
              and summary["assembly_condition_sha256"] == e1[sid()]["assembly_condition_sha256"])
        check("integrity verification passes on an intact model dir",
              ap.verify_assembly(w1.model_dir())["status"] == "PASS")

    print("== B: changed input -> drift ==")
    with tempfile.TemporaryDirectory() as t1:
        w = World(t1)
        w.write_records([record(sid())])
        w.assemble()
        first = w.entries()[sid()]
        w.write_records([record(sid(), raw=RAW2)])
        w.assemble()
        second = w.entries()[sid()]
        check("changed assembly input -> input sha drift", first["assembly_input_sha256"] != second["assembly_input_sha256"])
        check("changed assembly input -> source sha drift", first["source_sha256"] != second["source_sha256"])
        check("changed assembly input -> set sha drift",
              ap.assembly_set_sha256([first]) != ap.assembly_set_sha256([second]))

    print("== D/E/F: tamper, missing, orphan (verification refuses) ==")
    with tempfile.TemporaryDirectory() as t1:
        w = World(t1)
        w.write_records([record(sid()), record(sid("omp"), exec_model="omp")])
        w.assemble()
        src = w.source(sid())
        src.write_bytes(src.read_bytes() + b"// tampered\n")
        v = ap.verify_assembly(w.model_dir())
        check("record sha X vs file sha Y -> REFUSED (FAIL, tampered listed)",
              v["status"] == "FAIL" and [t["sample_id"] for t in v["tampered_sources"]] == [sid()])
        src.unlink()
        v = ap.verify_assembly(w.model_dir())
        check("record exists + source missing -> REFUSED/incomplete",
              v["status"] == "FAIL" and v["missing_sources"] == [sid()])
        orphan = w.model_dir() / "sources" / "ghost__sample" / "generated-code.hpp"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"int x;\n")
        v = ap.verify_assembly(w.model_dir())
        check("source without record -> ORPHAN DETECTED", "ghost__sample" in v["orphan_sources"])
        v = ap.verify_assembly(w.model_dir(), expected_sample_ids=[sid(), sid("omp"), sid("mpi")])
        check("expected population: missing record reported", v["not_recorded"] == [sid("mpi")])

    print("== G: duplicate sample id -> REFUSED before any write ==")
    with tempfile.TemporaryDirectory() as t1:
        w = World(t1)
        w.write_records([record(sid()), record(sid(), raw=RAW2)])
        try:
            w.assemble()
            check("duplicate sample_id refused", False)
        except ap.AssemblyIntegrityError as err:
            check("duplicate sample_id refused", "duplicate" in str(err))
        check("nothing written on refusal (no records, no sources)",
              not (w.model_dir() / "assembly.jsonl").exists()
              and not (w.model_dir() / "sources").exists())
        entries = [{"sample_id": "a", "assembled": True, "source_sha256": "0" * 64},
                   {"sample_id": "a", "assembled": True, "source_sha256": "1" * 64}]
        v = ap.verify_assembly(w.model_dir(), entries=entries)
        check("verification reports duplicates (no last-writer-wins)", "a" in v["duplicates"])

    print("== crash safety ==")
    with tempfile.TemporaryDirectory() as t1:
        w = World(t1)
        w.write_records([record(sid()), record(sid("omp"), exec_model="omp")])
        w.assemble()
        old_omp = w.source(sid("omp")).read_bytes()
        original_write = asm.write_source
        calls = {"n": 0}

        def crashing_write(path, content):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("simulated crash during the second source write")
            original_write(path, content)

        asm.write_source = crashing_write
        try:
            w.write_records([record(sid(), raw=RAW2), record(sid("omp"), raw=RAW2, exec_model="omp")])
            try:
                w.assemble()
                check("crash propagates", False)
            except OSError:
                check("crash propagates", True)
        finally:
            asm.write_source = original_write
        check("failed re-assembly leaves NO assembly.jsonl (fail-closed: zero samples, not stale ones)",
              not (w.model_dir() / "assembly.jsonl").exists()
              and not (w.model_dir() / "assembly_summary.json").exists())
        check("no half-written source: the untouched old source is intact and the new one complete",
              w.source(sid("omp")).read_bytes() == old_omp
              and w.source(sid()).read_bytes().endswith(b"}" + os.linesep.encode()))
        check("no temp files left behind",
              not list((w.model_dir() / "sources").rglob("*.tmp-*")))
        v = ap.verify_assembly(w.model_dir())
        check("the leftover sources are reported as orphans, never used silently",
              v["status"] == "FAIL" and set(v["orphan_sources"]) == {sid(), sid("omp")})
        # a crash while writing the record file: sources complete, record file absent
        w.write_records([record(sid()), record(sid("omp"), exec_model="omp")])
        original_jsonl = atomic_io.atomic_write_jsonl

        def crashing_jsonl(target, records):
            raise OSError("simulated crash while writing assembly.jsonl")

        atomic_io.atomic_write_jsonl = crashing_jsonl
        try:
            try:
                w.assemble()
            except OSError:
                pass
        finally:
            atomic_io.atomic_write_jsonl = original_jsonl
        check("crash before the record write: no partial assembly.jsonl exists",
              not (w.model_dir() / "assembly.jsonl").exists())
        w.assemble()
        check("a clean re-run recovers completely", ap.verify_assembly(w.model_dir())["status"] == "PASS")
        # atomic_write_text never exposes a partial target
        target = Path(t1) / "atomic.txt"
        atomic_io.atomic_write_text(target, "complete\n")
        check("atomic text write lands complete", target.read_text(encoding="utf-8") == "complete\n"
              and not list(Path(t1).glob("atomic.txt.tmp-*")))

    print("== stale sources on re-assembly ==")
    with tempfile.TemporaryDirectory() as t1:
        w = World(t1)
        w.write_records([record(sid()), record(sid("omp"), exec_model="omp")])
        w.assemble()
        w.write_records([record(sid()), record(sid("omp"), ok=False, exec_model="omp")])
        counts = w.assemble()
        check("sample now skipped -> its old source is removed (no stale usable source)",
              not w.source(sid("omp")).exists() and counts["stale_sources_removed"] == 1
              and w.entries()[sid("omp")]["stale_source_removed"] is True)
        w.write_records([record(sid())])
        counts = w.assemble()
        check("sample gone from the records -> no orphan remains",
              ap.verify_assembly(w.model_dir())["status"] == "PASS"
              and sorted(w.entries()) == [sid()])

    print("== base / repair cleaning parity ==")
    with tempfile.TemporaryDirectory() as t1:
        w = World(t1)
        iter_run = "r1__static_feedback__iter1"
        w.write_records([record(sid())])
        w.write_records([record(sid())], run_id=iter_run)
        w.assemble()
        w.assemble(run_id=iter_run)
        check("same record assembled under base and iteration run -> identical bytes",
              w.source(sid()).read_bytes() == w.source(sid(), iter_run).read_bytes())
        check("... identical assembly condition sha",
              w.entries()[sid()]["assembly_condition_sha256"]
              == w.entries(iter_run)[sid()]["assembly_condition_sha256"])
        from thesis.repair import orchestrator
        source = inspect.getsource(orchestrator.RepairLoop._assemble) \
            if hasattr(orchestrator, "RepairLoop") else ""
        if not source:
            for name in dir(orchestrator):
                obj = getattr(orchestrator, name)
                if inspect.isclass(obj) and hasattr(obj, "_assemble"):
                    source = inspect.getsource(obj._assemble)
                    break
        check("the repair loop calls the SAME assemble_model (no second cleaning path)",
              "assemble_sources.assemble_model(" in source)
        check("iteration entries are never counted as base population by the projection",
              ap.assembly_set_projection(w.entries(iter_run).values())[0]["logical_source_path"]
              == ap.assembly_set_projection(w.entries().values())[0]["logical_source_path"]
              and ap.classify_legacy_run(list(w.entries(iter_run).values())) == "PINNED")

    print("== legacy classification ==")
    legacy = [{"sample_id": "x", "assembled": True, "schema_version": "assembly.v1",
               "source_path": "thesis/results/intermediate/pilot_001/m/sources/x/generated-code.hpp"}]
    check("assembly.v1 records without source hash -> LEGACY_UNPINNED_ASSEMBLY",
          ap.classify_legacy_run(legacy) == ap.LEGACY_ASSEMBLY_CLASS and ap.is_legacy_entry(legacy[0]))
    with tempfile.TemporaryDirectory() as t1:
        w = World(t1)
        w.write_records([record(sid())])
        legacy_entry = {"schema_version": "assembly.v1", "run_id": w.run_id, "model_id": MODEL,
                        "sample_id": sid(), "assembled": True,
                        "source_path": w.source(sid()).as_posix()}
        common.append_jsonl(w.model_dir() / "assembly.jsonl", legacy_entry)
        w.source(sid()).parent.mkdir(parents=True)
        w.source(sid()).write_bytes(b"int historical;\r\n")
        before = (w.model_dir() / "assembly.jsonl").read_bytes()
        try:
            w.assemble()
            check("in-place re-assembly of a legacy assembly.v1 run is REFUSED", False)
        except ap.AssemblyIntegrityError as err:
            check("in-place re-assembly of a legacy assembly.v1 run is REFUSED", "legacy" in str(err))
        check("legacy records and sources untouched after the refusal",
              (w.model_dir() / "assembly.jsonl").read_bytes() == before
              and w.source(sid()).read_bytes() == b"int historical;\r\n")
    with tempfile.TemporaryDirectory() as t1:
        w = World(t1)
        w.write_records([record(sid())])
        w.assemble()
        e = w.entries()[sid()]
        e.pop("source_sha256")
        v = ap.verify_assembly(w.model_dir(), entries=[e])
        check("verification of legacy entries reports the class instead of a false PASS",
              v["status"] == ap.LEGACY_ASSEMBLY_CLASS and v["legacy_unpinned"] == [sid()])

    print("== manifest binding of the per-model assembly set ==")
    with tempfile.TemporaryDirectory() as t1:
        w = World(t1)
        run_manifest.ensure_run_manifest(w.config, w.run_id, stage="assembly", profile="t")
        w.write_records([record(sid())])
        w.assemble(register=True)
        manifest = run_manifest.load_manifest(w.config, w.run_id)
        set_sha = ap.assembly_set_sha256(w.entries().values())
        check("assembly_model_sets[model] registered with sample_count and set sha",
              manifest["assembly_model_sets"][MODEL]["assembly_set_sha256"] == set_sha
              and manifest["assembly_model_sets"][MODEL]["sample_count"] == 1
              and manifest["assembly_condition_sha256"] == w.entries()[sid()]["assembly_condition_sha256"])
        w.assemble(register=True)
        check("identical re-registration is idempotent",
              run_manifest.load_manifest(w.config, w.run_id)["assembly_model_sets"][MODEL]["assembly_set_sha256"] == set_sha)
        w.write_records([record(sid(), raw=RAW2)])
        try:
            w.assemble(register=True)
            check("same model, different assembly set under one run -> HARD FAIL", False)
        except run_manifest.AssemblySetMismatch:
            check("same model, different assembly set under one run -> HARD FAIL", True)
        check("the registered set is unchanged after the refusal",
              run_manifest.load_manifest(w.config, w.run_id)["assembly_model_sets"][MODEL]["assembly_set_sha256"] == set_sha)

    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("All assembly provenance test groups passed.")


if __name__ == "__main__":
    main()
