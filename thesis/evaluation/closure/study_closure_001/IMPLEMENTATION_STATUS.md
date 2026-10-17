# study_closure_001 - formal closure of the study (implemented; dry run PASS 99/99; awaiting commit + formal `--write`)

Global read-only verification over the seven experiment runs (pilot_002, full_ext_001,
full_ext_recovery_001..004, full_ext_phase2_001) and the persisted final composite
(`thesis/results/intermediate/full_ext_phase2_001/phase2_composite.json`, schema
`phase2_composite.v1`, written only by the phase-2 writer `composite.write_document` under the
phase-2 successor writer lock). The closure never measures, generates, repairs or contacts a
provider (provider isolation of the phase-2 package: `.env` import disabled, provider variables
scrubbed, AST scan of the closure package), and never changes a historical byte. The author's
result acceptance of the pilot is prepared but never taken.

## Package `thesis/study_closure/` (new; no existing file edited)

| module | section(s) | content |
|---|---|---|
| `core.py` | - | identities, run registry (role / config / frozen contract / definitions / verifier per run), `Section`, `Context`, helpers |
| `runs.py` | identity, runs, tree | git state, source pins, provider isolation; per run: manifest complete, frozen contract self-hash == manifest, native post-run authorization view (`run_authorization.authorization_state`), fragment integrity incl. the manifest snapshot, T0 runtime evidence (+ native `verify_pilot_run` runtime / config-drift checks), stage runtime stamps, model set; runtime / static / repair condition identity uniform across the 7 runs; enhanced spec identity uniform; results-tree scope (study / excluded / out-of-study / unexplained), no locks, raw-byte inventory of the phase-2 tree (the new protected set), the excluded aborted parent repair present and never adopted |
| `study.py` | history, population, phase2 | phase-2 lineage verification (9,485 protected files + definitions), custody chain, phase-2 definitions chain, target table re-derivation; census 66/66 + census digest == frozen lineage, 1,980 base cells, derived lineages own no base cell, composite reconstruction (5,460 cells), cell partition, evidence owners, persisted composite == reconstruction; phase-2 plan empty, 11 verification reports present AND reproduced (checks + counts recomputed), enhanced pair totals, stage history, ledger hygiene, registered invocations |
| `composite_closure.py` | - | guarded persistence of the composite (`--write` only): target == `phase2_composite.json` inside the phase-2 tree, no writer lock, manifest complete, every stage completed, byte-identical idempotence, read-back + self-hash check; additionally gated on every preceding closure check |
| `coverage.py` | coverage | verification evidence of all 7 runs: pilot post-run report, parent base report, 003/004 successor reports (their then-open work == phase-2 targets), the retrospective read-only re-verification of 002/003/004 through their NATIVE verifiers (new scope `RETROSPECTIVE_READONLY_COVERAGE_OF_RECOVERY_001_002_BY_STUDY_CLOSURE_001`), the explicit coverage maps of recovery_001 and recovery_002, unique verification scopes |
| `acceptance.py` | acceptance | pilot publication gate (`pilot_freeze.publication_decision`) evaluated now, mandatory disclosure sources, the PENDING result-acceptance template (never ACCEPTED), the readiness document, `--check PATH` validator |
| `disclosures.py` | disclosures | the computed disclosure register (17 items, every number computed from artifacts) + markdown |
| `report.py`, `run.py` | - | closure document (`study_global_verification.v1`, self-hashed), markdown, CLI (`--dry-run` / `--write`, `--no-reverify`, `--out`) |
| `test_*.py` | - | 279 tests (synthetic repositories; 5 optional real-repository tests behind `STUDY_CLOSURE_REAL=1`), all green in pareval-thesis (Python 3.12) |

## Artifacts of the formal `--write` (this directory)

`global_verification.json` / `.md` (the closure document, `closure_sha256`), `disclosures.json` /
`.md`, `pilot_002_result_acceptance.TEMPLATE.json` (status PENDING by construction),
`pilot_002_acceptance_readiness.json`, `full_ext_recovery_002_inprocess_verification_excerpt.txt`
(copied container-log evidence: volatile, NOT a verification artifact), this note. The composite
itself is persisted under the phase-2 results tree (gitignored); the closure document pins its
`composite_sha256` and raw sha256.

## Dry run 2026-10-17 (non-productive; nothing written into the repository)

`python3 -B -m thesis.study_closure.run --dry-run --out /scratch/dryrun_001` in pareval-thesis,
47 min, exit 0, status PASS, 9 sections / 99 checks, 0 failing, closure sha256 `387fe998...`
(dry run on the uncommitted package: `git.clean = false`, hence not formal).

| fact | value |
|---|---|
| base population | 1,980 = pilot_002 396 + full_ext_001 1,584 (`full_001_composite.json`, derived runs own 0) |
| composite cells | 5,460 = pilot 943 (396 base + 547 candidates) + full_ext 4,517 (1,584 base + 2,933 candidates); candidates per iteration: pilot it1 358 / it2 189, full_ext it1 1,879 / it2 1,054 |
| repair loops | 66/66 terminal: pilot_002 33; full_ext recovery_001 6, 002 4, 003 8, 004 15; one repair condition `98b8be0f...` |
| enhanced pairs | 109,200 = pilot 18,860 + full_ext 90,340 (rows == expected pairs, composite == verifier) |
| composite | `composite_sha256 = 953ce41b7f050559b1af875139c626995c562c43cba2fc632096c22d45e3e2b0` (reconstructed, not yet persisted; `composite_write_allowed` reports the write open) |
| phase-2 plan | every stage 0 open items, 0 open targets, 0 integrity findings |
| phase-2 reports | 11/11 PASS, reproduced check-for-check and count-for-count |
| runtime identity | all 7 runs: readiness == fresh runtime `0d5f4889...`, static `1f773327...`, repair `98b8be0f...`; enhanced specs `49b0229c...` |
| retrospective re-verification | 002 (2 models), 003 (4), 004 (5): every model `PASS_WITH_SUBSTITUTED_AUTHORITY_CHECK` (the native read-only mode fails exactly the authority check, substituted by the closure's frozen-contract + authorization checks); 003/004 reproduce their persisted reports (names, statuses, variants, counts, open work) |
| phase-2 incidents | 0 archived torn tails, 0 repeated build groups, 1 interrupted `dynamic` invocation (Docker bind-mount I/O error 2026-10-14 01:14Z; resumed missing-only) |
| pilot gate | `publication_allowed = false`, single reason: result acceptance pending; all 11 mandatory disclosure sources satisfied |

## Recovery 001 / 002 verification coverage (no persisted historical reports)

- **full_ext_recovery_001** - native verifier `verify_recovery_run.py` was never persisted (it only
  prints) and its acceptance predicate (33/33 terminal loops inside recovery_001) is unsatisfiable
  after the successor handoff by design: status `NOT_APPLICABLE_AFTER_HANDOFF`, no PASS claimed.
  Its 6 owned loops (the test_feedback loops of claude_fable_5, claude_opus_5, gemini_31_pro,
  openai_gpt55, deepseek_v4_flash, qwen3_coder_api) and the iteration-1 trajectories of the 12
  continued loops are covered by: the census (terminal, owner = recovery_001), the 003 verifier's
  adopted / iteration-1 checks (persisted) and the 002 verifier's (in-process at the time;
  retrospective now), byte protection through the 002/003/004/phase-2 lineages (custody chain),
  the phase-2 reports for every `full_ext_recovery_001__*` candidate target, and the closure's own
  contract / authorization / runtime / config-drift checks. Adopted vs new: every recovery_001
  answer was adopted by hash-bound reference; nothing was regenerated.
- **full_ext_recovery_002** - no persisted report (the retired 002 verifier had no `write_report`);
  the in-process verification printed PASS for both models (log excerpt attached, volatile).
  Status `NOT_PERSISTED_INPROCESS_PASS`; covered by the retrospective read-only re-verification
  of the closure (new scope), the 003/004 sibling inventories, the phase-2 reports for its 4
  iteration-2 targets, and the closure's run checks.

## Pilot acceptance (author decision required)

The gate (`pilot_freeze.publication_decision`) is closed for exactly one reason: no
`pilot_002_result_acceptance.v1` artifact. The template carries the verifiable values
(post_run_verification_sha256 `53d8397c...`, frozen contract `4aaa00c2...`, run_id, status PASS)
and `status: PENDING`, `decided_by: null`, `decided_on: null`. Only the author sets ACCEPTED or
REJECTED, their name and the date; `python3 -B -m thesis.study_closure.acceptance --check <path>`
validates a candidate file and reports the gate. ACCEPTED allows publication only under the pilot
label and with every mandatory disclosure.

## Known limitations

- The closure binds committed code only: `--write` refuses a dirty worktree; the formal closure is
  the `--write` run after the commit (expected ~50 min).
- The retrospective re-verification runs the native verifiers in their read-only mode: the
  authority check cannot pass there and is substituted (documented per model).
- The archived interrupted lock `.successor_locks/full_ext_phase2_001.writer.lock.interrupted-20261014T011442Z`
  and the duplicated `dynamic` stage invocation document the phase-2 interruption; no torn ledger,
  no repeated build group resulted.
