# Static/Repair.1 — Runtime Readiness Identity Pinning & Legacy Static Merge Fail-Closed

Addendum to [static_repair_pilot002_readiness_report.md](static_repair_pilot002_readiness_report.md).
Date: 2026-09-06. Start HEAD `2120f74a73ab299d3d12620775500f5872e6cf30`
(verified; parent `59ee9c86`, working tree clean before the wave).

This wave closes **two provenance holes** and changes **no static/repair
methodology**: no finding semantics, no blocking policy, no tool thresholds,
no PARCOACH confidence, no InferBO level, no LLOV method, no repair stop or
retry policy, no prompts, no semantic decisions, no correctness or enhanced
artifacts, and no pilot_001 migration. Every number below was measured in
this wave; anything not measurable is named as such.

## 1. Why a semantic condition is not a runtime condition

`static_analysis_condition_sha256` answers **"under which tool/config/source
semantics may static results be merged?"**. It deliberately strips the
per-tool `tool_identity` before hashing
([static_provenance.py](static_provenance.py), `static_analysis_condition_sha256`),
because PARCOACH (LLVM 15), LLOV (clang 7) and the main image (g++ 13 /
clang 18) legitimately run different toolchains and must still contribute
entries to **one** static condition. That is correct for merging — and it
means the hash is **identity-blind by construction**.

Measured consequence (audit `preflight_staleness`, reproduced at the start
HEAD): five completely different tool-identity sets — including a fully
downgraded g++ 9.4 / LLVM 14 / Cppcheck 1.90 / Infer v0.17 / clang 6.0 —
all produce the same `static_analysis_condition_sha256`
`327b235a8014cb68…`, the value stored in the readiness artifact. An
end-to-end attack at the start HEAD (readiness artifact with both condition
hashes byte-identical but every image replaced by `evil/<tool>:fake-0.0.1`
and every identity replaced by `FAKE … 0.0.0-swapped-image`) made
`pilot_preflight.py` print **`STATIC_REPAIR_READINESS = READY`**.

The readiness **runtime** condition answers the other question: **"under
which actually measured environment was READY proven?"** — and that one
must carry the identities.

## 2. Runtime condition components (`static_repair_runtime.v1`)

`static_provenance.runtime_condition(environments, static_sha, repair_sha)`
plus `runtime_condition_sha256`. Fingerprinted per environment
(`RUNTIME_ENVIRONMENT_FIELDS`, an **allowlist** so a later measurement
cannot silently move the hash):

| field | meaning |
| --- | --- |
| `image_ref` | the reference the config asks for (a tag — never an identity by itself) |
| `image_id` | image ID of the local store |
| `repo_digests` | registry digests, i.e. real pull provenance, when the image was pulled |
| `rootfs_layers_sha256` | sha256 over the joined, ordered `RootFS.Layers` diff_ids — store-independent |
| `tool_identities` | measured `--version` identity per tool, via the pipeline's own `tools.tool_runtime_identity` |
| `evidence` | per-environment extra identity (LLOV plugin hash, PARCOACH executable hash and version, …) |

Plus `static_analysis_condition_sha256` and `repair_condition_sha256`, so a
single comparison answers both questions. `fully_pinned` /
`unpinned_environments` are derived (an environment counts as pinned only
through an immutable value — a tag never suffices) and are not hashed twice.

The measurement is `thesis/evaluation/probe_runtime_identity.py`, executed
inside each container (~1 s per environment, ~6 s for all three), driven
from the host by `check_static_repair_readiness.measure_runtime()`, which
adds the host-side `docker image inspect` identity.

## 3. Container immutable identities (measured 2026-09-06)

| environment | configured reference | image ID | rootfs layer-set sha256 | layers |
| --- | --- | --- | --- | --- |
| main | `pareval-thesis` | `sha256:eb1c2e93cfab755504b25e6fbf6e0df34e1b371e18c995f55d7eba77f74222aa` | `f6bc13cbc026618ba889236257111696557081179048b7da766a89e81fbdba7c` | 11 |
| parcoach | `registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1` | `sha256:dbac7091e60b218c72a27153639ed4b5ead0389aca0857313cfb821bd3d68030` | `2975b0d46cf4e416ccf29686442116977b9e67a4c30e69dde51c364109b368ee` | 12 |
| llov | `pareval-llov` | `sha256:67d8c6c0b36e691c72f80fe893fbfedf4d55e298abc82c841561cd46b95e3341` | `835fc4ef14332c3ca74c0801139820c48aa6dc8acf8940a87ffe0b248fbc80a5` | 13 |

All three report a `RepoDigests` entry, but only **parcoach-demo** has real
pull provenance: this host runs the containerd image store, so `Id` is the
OCI manifest digest and the two locally built images carry a `RepoDigests`
entry that merely repeats their own `Id`
(`Descriptor.mediaType = application/vnd.oci.image.index.v1+json`,
`Identity = {"Build":[…]}` versus parcoach's
`application/vnd.docker.distribution.manifest.v2+json`, `{"Pull":[…]}`).
That is why the store-independent `rootfs_layers_sha256` is pinned as well.

**Documented trade-off** (raised by the adversarial review, decided
deliberately): pinning the store-dependent `image_id` makes the proof
host-local — migrating the daemon's image store would invalidate an older
readiness proof even for byte-identical images. Accepted, because a
readiness proof *is* a statement about one measured host, the remedy is one
re-run of the readiness gate, and `runtime_drift()` names the field, so an
`image_id`-only drift with identical layer sets and identities is
recognisable for what it is. The reasoning is recorded in the code.

Not fingerprinted (measured volatile): container hostname (a fresh id per
run), `Metadata.LastTagTime`, `Identity.Build[].Ref/CreatedAt`, image tags
alone, per-run durations, probe timestamps.

## 4. Tool identities (measured, byte-equal across fresh containers)

| environment | tool | measured identity |
| --- | --- | --- |
| main | compiler / gcc_analyzer | `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0` |
| main | clang_tidy | `Ubuntu LLVM version 18.1.3` |
| main | cppcheck | `Cppcheck 2.13.0` |
| main | infer | `Infer version v1.1.0` |
| main | (evidence) | `mpirun (Open MPI) 4.1.6`; `/opt/toolchain-versions.txt` sha256 `6508d63d0ec5fd66…`; Python 3.12.3 |
| parcoach | parcoach | `Ubuntu LLVM version 15.0.7` (**LLVM backend banner**, see §6) |
| llov | llov | `clang version 7.1.0 (git@github.com-utpalbora:utpalbora/LLVMOMPVerify 93321be55c75b340df54c9a208d52e8ec5113dab)` |

The pipeline helper takes only the **first** `--version` line. That matters:
PARCOACH's banner line 4 is `Host CPU: alderlake`, i.e. host-hardware
derived — hashing the full block would make the fingerprint machine
dependent. LLOV's identity contains a **double space** after `7.1.0`, so
`strip()` alone is not enough; `normalize_identity` collapses every
whitespace run before hashing. The artifact keeps the raw string and hashes
the normalized one.

## 5. LLOV plugin identity

`LLOVTool` resolves `llov_home = /home/llvm/Work/LLOV`,
`clang = <home>/bin/clang++`, `plugin = <home>/lib/OpenMPVerify.so`. The
probe pins the plugin itself:

* `plugin_path` `/home/llvm/Work/LLOV/lib/OpenMPVerify.so`
* `plugin_sha256` `19bbc86baf211f443c6cce9e438c21d9567cdf677923416e2fa4697b1d720196`
* `clang_identity` as in §4, `interpreter_identity` `Python 3.8.0`

so **same clang + different plugin** is visible as runtime drift — verified
by test 5 and by the preflight regression.

## 6. PARCOACH identity — what may and may not be claimed

`parcoach --version` prints the **LLVM backend banner**
(`Ubuntu LLVM version 15.0.7` …), not a PARCOACH version, and it is recorded
under `llvm_backend_identity` with an explicit note; the pipeline's tool
identity for `parcoach` is that banner line and is labelled accordingly.

The adversarial review then refuted the assumption that no program version
is obtainable, and the correction was re-measured here directly:

```
$ parcoach --parcoach-version
PARCOACH version 2.4.0                 (exit 0)
$ parcoach --help-list | grep parcoach-version
  --parcoach-version   - Show PARCOACH version
```

Three concordant in-image sources say **2.4.0**: the program's own
`--parcoach-version`, `/usr/lib/cmake/Parcoach/ParcoachConfigVersion.cmake`
(`PACKAGE_VERSION "2.4.0"`) and the release tarball directory
`parcoach-2.4.0-shared-Linux/` inside `/scripts/parcoach.tgz`. The **image
tag says 2.4.1**. The artifact therefore records `program_version = "2.4.0"`
with its source, `cmake_package_version = "2.4.0"`, `version_sources_agree`,
and the tag separately as `image_ref` — the tag is never presented as the
program version and the discrepancy is visible rather than resolved.
Additional pins: executable `/usr/bin/parcoach`, sha256
`1bad67527d180d467b57fbf230b220e190b9e9ce130a6e9f384921e3b06bccec`; the
clang PARCOACH actually uses, `/usr/lib/llvm-15/bin/clang`
(`Ubuntu clang version 15.0.7`); Python 3.11.4.

## 7. Readiness staleness logic

The measured readiness of this wave:
`runtime_condition_sha256 = 8c382160852cad24c9f2d6bb826c287f706cf07a321e75b3865635ea1a502c3b`
(`static_repair_runtime.v1`, fully pinned, gate `READY`, created 2026-09-06T09:54:27.517481Z).

`check_static_repair_readiness.py` (schema **`static_repair_readiness.v2`**)
now measures the runtime before the fixtures and stores `runtime`,
`runtime_condition`, `runtime_condition_sha256`, `runtime_fully_pinned`. A
probe failure is a `problem`; a missing immutable identity or
`--skip-containers` is `unresolved` — so a run that could not measure the
runtime can never be `READY`.

`pilot_preflight.py` now requires **all three** conditions to match and
obtains the runtime **freshly**:

1. `static_analysis_condition_sha256` recomputed from the current repo/config,
2. `repair_condition_sha256` likewise,
3. `runtime_condition_sha256` **re-measured** — live via docker
   (`measure_runtime`, the same definition the artifact was built with), or
   from a supplied fresh provenance file (`--static-runtime`) on a host that
   cannot start containers. `--skip-runtime-probe` exists for testing and
   can never yield READY.

Additional hardening from the audits (both were measured defects at the
start HEAD):

* the `static_provenance` import sat **inside** the `try` block, so an
  `ImportError` left the comparison silently unperformed while the section
  still printed `READY` (reproduced by running the preflight from
  `thesis/evaluation/`). The repository root is now placed on `sys.path` by
  `pilot_preflight` itself, and a non-importable module is `stale`.
* a semantic condition that could **not** be recomputed skipped both
  comparisons and fell through to `READY`; a comparison that could not be
  performed is now itself a staleness reason.
* the artifact's `schema_version` is asserted against the current one, so a
  v1 artifact (no runtime proof at all) is refused instead of accepted.
* if no known field differs but the recorded fingerprint does, the
  **fingerprint wins**: the artifact was produced under a different
  runtime-condition definition and is refused.

Measured results (`--static-runtime` used to inject synthetic drift; the
real artifact was never modified):

| scenario | result |
| --- | --- |
| live docker probe, unchanged environment | `RUNTIME: measured live (docker) → …` + `runtime identity unchanged since the readiness proof` → **READY** |
| supplied fresh runtime (identical) | **READY** |
| LLOV image ID + digests changed | `UNRESOLVED (stale)`; drift `environments.llov.image_id`, `…repo_digests` |
| PARCOACH image ID + digests changed | `UNRESOLVED (stale)`; drift `environments.parcoach.image_id`, `…repo_digests` |
| compiler identity changed | `UNRESOLVED (stale)`; drift `environments.main.tool_identities.compiler` |
| infer identity changed | `UNRESOLVED (stale)`; drift `environments.main.tool_identities.infer` |
| LLOV plugin sha256 changed | `UNRESOLVED (stale)`; drift `environments.llov.evidence.plugin_sha256` |
| `--skip-runtime-probe` | `UNRESOLVED (stale)` — "not re-measured" |
| the start-HEAD attack (identical semantic hashes, all images and identities faked) | `UNRESOLVED (stale)` with 14 named drift paths — at the start HEAD the same artifact yielded `READY` |

## 8. The legacy static merge defect

At the start HEAD, `static_provenance.check_merge` returned silently for a
record whose `sample_source_sha256` was `None`, and
`run_static_analysis.run_model` then wrote the **current** source hash into
that record while rewriting its `schema_version` from `static_analysis.v2`
to `v3` — after which it read as a fully provenanced record. Reproduced
twice by the audit:

* synthetic: a v2 record with a `compiler` entry, run with
  `--tools clang_tidy`, came back pinned with `sample_source_sha256` next to
  a `compiler` entry that has neither a fingerprint nor a condition, and
  with **no per-record marker** of the pin;
* on a **copy** of real pilot_001 evidence (model `claude_fable_5`, 36
  records, copied out of the repository): with
  `--replace-tool-entries compiler` the run succeeded and produced
  `pinned after: 36`, `fingerprinted entries after: 36`,
  **`UNFINGERPRINTED entries after: 216`** — 216 never-verified legacy
  entries sitting under a freshly pinned hash of the current candidate.

The per-tool guard already blocked the *plain* case (a legacy entry without
a fingerprint is refused by `check_tool_entry_merge`), so the hole was
reachable exactly two ways: a tool with **no** existing entry, or
`--replace-tool-entries`.

Legacy data inventory (measured over
`thesis/results/intermediate/**/static_analysis.jsonl`): **1111 records,
all `static_analysis.v2`, all without `sample_source_sha256`, all carrying
tool entries** (0 with an empty `tools` dict), 7753 tool entries, all
unfingerprinted — pilot_001 396 plus the six iteration directories.

## 9. New fail-closed migration policy

`check_merge(..., replace_legacy_record=False)`:

| existing record | result |
| --- | --- |
| none, or already pinned with the same source | merge as before |
| pinned, source changed | `StaticMergeConflict` (unchanged) |
| unpinned **and no tool entries** | initialization allowed — pinning legitimizes nothing |
| unpinned **with tool entries** | **`LegacyRecordUnverified`** (a `StaticMergeConflict` subclass, so `run_static_analysis` still exits 3) |
| unpinned with tool entries **and** `--replace-legacy-record` | allowed; the runner retires **every** historical entry before re-analysis |
| the candidate source bytes cannot be read at all | `StaticMergeConflict` — nothing about the sample can be pinned or verified |

The last row was added after the adversarial review found two defects **in
the fix itself**, both rooted in an unhashable source: (a) the historical
entries were retired while nothing was pinned, leaving a mangled unpinned
`v3` record (the start HEAD left such a record untouched), and (b) a
*fresh* record written under that condition by container A — entries, no
pin — was then rejected as "legacy" by container B, i.e. exactly the
cross-container merge this wave must not break. Refusing an unverifiable
sample before any write removes both: no unpinned record with entries can
be produced any more, so "legacy" again means only "written before the
tool-state wave". Measured latent today: 0 of the 1111 assembled samples
across all seven run directories has a missing source file.

The refusal names the sample and the unverified tools and offers exactly two
remedies: a **fresh run_id**, or the explicit **full** recomputation. It
states that `--replace-tool-entries` does *not* satisfy it — a partial
replacement leaves the other entries unverified under a new pin.

`--replace-legacy-record` **retires** every historical entry — it moves
`record["tools"]` to `record["superseded_legacy_tools"]` (archived verbatim,
read by no consumer) rather than deleting it, then pins, and the **record
itself** says so afterwards
(`legacy_entries_dropped`, `provenance_note: "recomputed from an unpinned
static_analysis.v2 record …"`), so a v3 record born from a v2 one is never
indistinguishable from a natively provenanced one. The invocation history
records a **bounded** summary (`records`, `tool_entries`, per-tool
histogram, first 5 sample ids). Because the counter's meaning changed, the
summary schema was bumped explicitly to **`static_analysis_summary.v3`** and
`legacy_records_pinned` was renamed to `pre_existing_records_pinned`.

Two safeguards were added after the adversarial review flagged that the
flag, as first written, would have **deleted** evidence in place: the
entries are archived rather than dropped (above), and the flag now
**requires an explicit `--run-id`**. That closes the concrete foot-gun the
review measured: the `pilot` profile still resolves to `pilot_001`, so
`run_static_analysis.py --profile pilot --replace-legacy-record` would have
targeted the frozen pilot evidence (1111 records, 7753 unpinned tool
entries). It now refuses with

```
--replace-legacy-record requires an explicit --run-id (the profile default
resolves to 'pilot_001'). Name the run whose records you intend to
recompute; historical pilot evidence must not be recomputed at all - use a
fresh run_id instead.
```

(exit 2, nothing written).

**pilot_001 is not migrated.** No record under `thesis/results/` was read-
modified (`git status` for that path is empty; on a refused merge
`static_analysis.jsonl` is byte-identical — md5 measured before and after —
although the invocation does write `toolchain-versions.txt` and
`run_manifest.json` before refusing), and the read-only inventory
`build_static_repair_inventory.py` reproduces its artifact byte-identically.
Read-only consumers are unaffected: the inventory imports neither
`static_provenance` nor `run_model`, and `build_overview.py` references
none of them.

**Does the rule break a legitimate workflow?** Measured: in all seven
existing run directories, **0** records are missing an internal static tool
and **0** are missing an in-scope external entry, so
`orchestrator.missing_internal_stages`, `orchestrator.pending_external` and
`run_backfill.stage_coverage` report complete coverage and **no path reaches
`run_model`** on legacy data today (`run_backfill --status`: `static=ok`,
`external=-` in all 77 rows — other stages such as `enhanced=partial` do run
there, which is why the precise statement is "reaches `run_model`", not
"writes"). Note that iteration 0 of a repair variant *is* the base run id:
`LoopPaths.iter_run_id(0)` returns `pilot_001` itself, so every new variant
wave evaluates its coverage against pilot_001 directly — driven over 11
models × 3 variants × iterations 0–2, `missing_internal_stages` and
`pending_external` were empty in 99/99 rows. The exposure is real but latent
— it becomes live the moment a new static tool is enabled, a scope widens,
or entries are removed — and that is exactly when the refusal should fire.
`orchestrator.py` and `run_backfill.py` call `run_model` without the flag
and must keep doing so.

## 10. Tests

`thesis/evaluation/test_static_repair_provenance.py` (all green):

* **RUNTIME 1–7**: identical runtime → identical fingerprint; drift in LLOV
  image id, PARCOACH image id, PARCOACH repo digest, compiler / clang-tidy /
  infer identity, LLOV plugin hash, PARCOACH executable hash, and each of
  the three layer-set hashes → different fingerprint **and** a named drift
  path; tool-code and repair-policy changes surface as their own signals;
  timestamps, hostnames, container names and per-run durations leave the
  fingerprint untouched; whitespace/CRLF normalization; identical across
  fresh interpreter processes; an environment without any immutable
  identity is reported `unpinned`, never silently pinned.
* **LEGACY 8–13**: empty legacy record initialized; legacy record with
  historical entries refused (nothing written, no hash pinned); partial
  `--replace-tool-entries` cannot bypass it; explicit full recomputation
  drops every historical entry, pins, marks the record and stays idempotent;
  v3 cross-container merge and idempotence unchanged; v3 source drift still
  refused and distinguishable from the legacy refusal.
* **PREFLIGHT**: the real `pilot_preflight.py` in a subprocess accepts the
  runtime it was proven on, refuses a drifted one while naming the drifted
  fields, and never accepts a proof without fresh runtime evidence.

Everything else stays green: tool-state, orchestrator (12), feedback (8),
backfill (7), evaluation (27), overview (7), semantic decisions, cleaning
(13), generation (10) and all seven enhanced suites.

## 11. pilot_001 unchanged

`thesis/results/` has zero modified files. pilot_001 keeps TAG_ONLY
environment provenance — the new runtime pin describes the **current**
environment and is explicitly not attributed backwards. Its 1111 static
records stay `static_analysis.v2` without a source hash and are now
*refused* for augmentation instead of being silently pinned. The
comparability classes of the previous wave are unchanged (asserted
programmatically when the cross-pilot artifact was updated), and both
semantic condition fingerprints are byte-identical to the values recorded
there: `static_analysis_condition_sha256 = 327b235a8014cb682befe013a6176895c0b65a0ba8938a56f34ed1736aa820a3`,
`repair_condition_sha256 = 09a8e8a20a0582202e5b35496c47b17cdf8b4fdf5badc4b824035482bca9cd36`.

## 12. Remaining limitations (not solved in this wave)

* **TSan / ASLR environment requirement stays open.** `verify_detection.py`
  reports `clean/omp: tsan` as the single failure: *"TSan preflight binary
  exited -11 … Fix once per VM boot: `docker run --privileged --rm
  ubuntu:24.04 sysctl -w vm.mmap_rnd_bits=28`"*. Nothing here changes host
  sysctls, container privileges or disables TSan; the requirement must be
  checked by the final environment gate before pilot_002.
* **The runtime pin lives in the readiness artifact, not in the pilot's own
  evidence tree.** `run_manifest.json` carries the static/repair *condition*
  fingerprints but no container identity, and pilot_002's records will carry
  per-tool `tool_identity` (inside each entry's execution condition) but not
  the image id. Stamping the measured environment identity into the run
  manifest belongs to the final environment / post-run-manifest gate.
* **`not_applicable_entry` bypasses the per-tool merge check.** Measured
  (audit `legacy_merge`, confirmed and quantified by its review): an
  out-of-scope tool's not-applicable entry is written into `record["tools"]`
  unconditionally and without a fingerprint, so a narrowed config scope could
  overwrite a real analysis entry. Consequence for the escape hatch: because
  `parcoach` is scoped to `mpi` and `llov` to `omp`, even a *full*
  recomputation of pilot_001 would leave **528** unfingerprinted
  NOT_APPLICABLE entries (264 + 264, measured), so
  `--replace-legacy-record` does not produce a fully fingerprinted record
  set. It is unreachable for legacy records now (they are refused earlier)
  and harmless for the current configuration, but it is a merge-semantics
  gap of the same family and was deliberately **not** changed here — this
  wave must not touch static merge semantics beyond the two named holes.
* **A refusal aborts a whole backfill run.** `run_backfill.main()` has no
  `try/except` around `backfill_model`, so one `LegacyRecordUnverified` ends
  the backfill for every remaining model. Fail-closed and loud, but the
  operator sees one model's refusal instead of a per-model report.
* `image_id` in the fingerprint makes the readiness proof host-local (§3).
* **The runtime condition inherits the line-ending sensitivity of the static
  condition.** `runtime_condition` carries
  `static_analysis_condition_sha256`, which is derived from raw file bytes
  (`tools.py`, `framework.py`, `build_config.py`, `tool_config.py`,
  `drivers/cpp`). This repository is checked out with `core.autocrlf=true`
  and has no `.gitattributes`, so those files are CRLF here and LF on a
  fresh Linux clone: measured, `tools.py` hashes `9ed277a0bb3b74ea…` raw
  versus `9d3ec752b5f2b7cc…` LF-normalized. A readiness proof therefore does
  not transfer across checkouts with different line endings — the drift is
  reported honestly as `static_analysis_condition_sha256`, and re-running
  the readiness gate on the target checkout resolves it. Normalizing that
  hash would change the static condition itself and is out of scope here.
* **A failed identity probe is `unresolved`, not a `problem`.** The review
  showed that routing it to `problems` would make the gate `NOT_READY`,
  which the preflight maps to exit 1 = `CROSS_PILOT_GATE_STALE = true`; a
  transient docker failure must not trigger a comparability re-evaluation.
  A failed *fixture* stays a problem — that is a measured contradiction.
* **The cross-pilot artifact's copy of the runtime pin is descriptive.**
  `areas.F_static_repair.fingerprints.static_repair_readiness_runtime_condition_sha256`
  documents which runtime the readiness proof was obtained on;
  `check_cross_pilot_gate.py` does not validate it (the authoritative
  comparison is `pilot_preflight.py` against the readiness artifact).
* pilot_001 environment identity remains unknowable (TAG_ONLY, no digest was
  ever recorded); nothing in this wave invents one.
