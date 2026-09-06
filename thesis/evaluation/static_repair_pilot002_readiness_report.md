# Static/Repair + LLOV Tool-State Hardening — pilot_002 readiness report

Wave: *Static/Repair + LLOV Tool-State Hardening — Fail-Closed Analysis States,
Cross-Container Merge Safety, Repair Semantics & Cross-Pilot Reevaluation*.
Date: 2026-09-05. Every number below is either read from a committed artifact,
measured in this wave (host tests, container fixture runs, read-only scans of
the pilot_001 records) or explicitly marked as unknown. Nothing in pilot_001
was re-run or rewritten.

## 1. Provenance

| item | value |
| --- | --- |
| repository / branch | jerabek-niklas/ParEval-Thesis, `thesis-static-analysis` |
| start HEAD | `59ee9c863637af63970eed32af0c3c35494cc2df` (verified before the wave; parent chain intact; working tree clean, `.claude/` not inspected) |
| end state | uncommitted working tree on top of the start HEAD (14 modified, 9 new files incl. this report and the readiness artifact; listed in the final report). No commit was made by the wave. |
| pilot_001 commit | `6846d689` (ancestor of the start HEAD, 23 commits back) |
| audit evidence | 8 empirical read-only audits + 8 adversarial reviews executed on a detached snapshot worktree of the start HEAD (compiler/gcc_analyzer, clang_tidy/cppcheck, infer, parcoach, llov, merge/summary, repair retry, pilot_001 forensics); their measured facts are cited per section |
| fixture evidence | `thesis/tool_validation/results/tool_state_fixtures/{pareval-thesis,parcoach-demo,pareval-llov}.json` (measured in the three containers with the final code) |
| pilot inventory | `thesis/evaluation/static_repair_pilot001_inventory.json` (built by `build_static_repair_inventory.py`, records read only) |
| LLM / API calls | 0 (all repair tests use the fake adapter and mocked batch API) |

## 2. Ausgangsgates (before any change)

| gate | result |
| --- | --- |
| `check_cross_pilot_gate.py` | CURRENT (exit 0) |
| `check_semantic_decisions.py` | PASS_WITH_DISCLOSURE (6 resolved, 1 accepted disclosure dense_la/00) |
| `check_prompt_oracle_consistency.py` | PASS (inside pareval-thesis) |
| `thesis/repair/test_orchestrator.py` | 12 groups green |
| `thesis/repair/test_feedback.py` | 8 tests green |
| `thesis/repair/test_backfill.py` | 7 groups green |
| `thesis/evaluation/test_evaluation.py` | 27 tests green |
| `thesis/analysis_overview/test_overview.py` | 7 groups green |
| `thesis/evaluation/test_comparator_semantics.py` | green |

## 3. Tool matrix (measured in the respective container)

| tool | enabled | hard capability | configured scope | container | executable / measured identity | timeout | TU strategy | attribution | blocking rule | low-confidence rule | known inconclusive state | known process-failure state | validation evidence (committed) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| compiler | yes | serial/omp/mpi | serial/omp/mpi | pareval-thesis | `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`, `mpicxx` → same g++ | build 120 s | full: model driver + benchmark cpu.cc + generated-code.hpp | model-file diagnostics; non-model **errors** tagged `(in driver/benchmark)` | `error` diagnostics; synthetic `compile-failed` only when the build completed with an error diagnostic | none | none (the build has a verdict or a toolchain failure) | timeout, missing binary, ICE, `cc1plus: fatal error` → TIMEOUT / TOOL_ERROR | build gate; no precision suite (not a detector) |
| gcc_analyzer | yes | serial/omp/mpi | serial/omp/mpi | pareval-thesis | same g++ 13.3.0, `-fanalyzer -Wanalyzer-too-complex -c` | 300 s (config) | reduced: cpu.cc system-include preamble + `<vector>` + utilities.hpp + generated-code.hpp | `-Wanalyzer-*` in the model file; path events attached to the finding | every `-Wanalyzer-*` except too-complex | none | `analysis bailed out early` / too-complex → PARTIAL | non-compiling TU → TOOL_ERROR; timeout → TIMEOUT | Juliet `compiler_fanalyzer`: precision 0.937, recall 0.477 |
| clang_tidy | yes | serial/omp/mpi | serial/omp/mpi | pareval-thesis | `Ubuntu LLVM version 18.1.3` | 180 s | full: benchmark cpu.cc, `--header-filter=generated-code.hpp$` | fixes.yaml → model file | curated groups (bugprone/concurrency/clang-analyzer/mpi/openmp) | `clang-analyzer-optin.mpi` family | none | front-end rejection (`clang-diagnostic-error` / `Found compiler error(s).`) → TOOL_ERROR (NOT_ANALYZED when the compiler failed too); exit ≠ 0 without rejection → TOOL_ERROR; timeout → TIMEOUT | Juliet `clang_sa`: precision 0.822, recall 0.383; MBI `clang_sa`: precision 0.569 |
| cppcheck | yes | serial/omp/mpi | serial/omp/mpi | pareval-thesis | `Cppcheck 2.13.0` | 120 s | full: benchmark cpu.cc (`--enable=warning,portability --inconclusive`) | XML → model file | severity `error` (checker ids) | none | tool-side ids (`syntaxError`, lexer `preprocessorErrorDirective`, `internalError`, …) → PARTIAL | exit ≠ 0 (message on stdout), missing/malformed `<results>` → TOOL_ERROR; timeout → TIMEOUT | Juliet: precision 1.0, recall 0.214 |
| infer | yes | serial/omp/mpi (omp effectively not analyzable, see §10) | serial/omp/mpi | pareval-thesis | `Infer version v1.1.0` (bundled clang 11.1.0) | 300 s (constructor default; not config-exposed) | full: benchmark cpu.cc via `infer run -- clang++ -c` | report.json → model file, InferBO L1/L2 filter (unchanged) | severity `error` | none | frontend abort `Aborting translation of method` → PARTIAL (findings elsewhere) / NOT_ANALYZED | exit ≠ 0, no/unparseable report.json, "nothing to analyze" → TOOL_ERROR; timeout → TIMEOUT | Juliet `infer`: precision 0.805, recall 0.095; `infer_bo_l1l2`: precision 0.867 |
| parcoach | yes | mpi | mpi | `registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1` | `/usr/bin/parcoach`, `--version` prints only `Ubuntu LLVM version 15.0.7` (cmake package version 2.4.0; tag 2.4.1); clang fallback `/usr/lib/llvm-15/bin/clang` 15.0.7 | 60 s (config) | reduced: cpu.cc preamble + `<vector>` + utilities.hpp + generated-code.hpp, `-emit-llvm`, external declares stubbed | `PARCOACH: <file>: warning:` lines in the model file | all warnings blocking | `low_precision_warning: true` → every finding low-confidence | none of its own (a `No issues found` on an empty module is vacuous) | reduced-TU compile failure / crash → TOOL_ERROR; compile-step or parcoach timeout → TIMEOUT | MBI: precision 0.506, recall 0.6 (unchanged; stays low-confidence) |
| llov | yes | omp | omp | `pareval-llov` | `clang version 7.1.0 (LLVMOMPVerify 93321be…)`, plugin `OpenMPVerify.so`; interpreter `python3.8` (system python3 is 3.6.9) | 180 s | reduced: cpu.cc preamble + `<vector>` + utilities.hpp + generated-code.hpp, plugin compile with the canonical Polly flags | `Source :` / `File :` lines (`path:line` and `path:line:col`) in the model file | `llov-data-race` blocking; not-analyzed info | none | `Region/Directive Not Analyzed` → NOT_ANALYZED / PARTIAL; no region verdict → NOT_ANALYZED | non-zero clang exit (incl. plugin crash exit 254) → TOOL_ERROR; timeout → TIMEOUT | DRB: precision 0.878, recall 0.448 |

Container identities are TAG_ONLY pins for pilot_001 (no image digest recorded); the readiness artifact records what the current images measure.

## 4. Current tool-state defects (measured on the start HEAD)

* **Tool key ≠ completed analysis (Hinweis A confirmed).** No consumer read `ToolResult.error` or `exit_code`: `feedback.collect_findings`, `evaluate_stop`, `missing_internal_stages`, `pending_external`, `run_backfill.stage_coverage` and `build_overview` all decided on key presence / findings only. pilot_001 base run: 98 tool-error entries with `ran=True` (gcc_analyzer 11, infer 10, llov 28, parcoach 49) counted as verdict B; 50 of the 69 gap-only OMP/MPI samples were decided `stopped_clean` at iteration 0 in static_feedback.
* **Compiler timeout / missing binary / ICE became a model compile error**: synthetic `compile-failed` finding rendered as `line ?: [compile-failed] compilation failed (timeout)` and sent to the LLM (0 occurrences in pilot_001; measured on fixtures).
* **gcc -fanalyzer bail-out invisible**: `analysis bailed out early` attributed to a libstdc++ header or emitted location-less (`cc1plus: warning:`) was dropped by the model-file filter; a planted null dereference next to STL code is missed while the record looks clean; 37 pilot records carry the line, 34 without any finding; 49 records are too-complex-only.
* **clang-diagnostic-error as blocking model defect**: 23 base + 60 iteration findings, all in compiler-failed records (duplicate wording, off-by-one line); a GCC-only builtin that g++ builds is rejected by clang and was a blocking "defect".
* **cppcheck**: never set `error`; exit 1 (CLI/path errors on stdout, empty stderr), malformed/empty XML and timeouts all looked clean; lexer failures (`No pair for character`) were blocking.
* **infer**: 130/130 OpenMP records carry `Aborting translation of method` (the whole kernel dropped by infer's clang 11) with exit 0 and a report.json → recorded clean; timeout / no report were classified but not consumed.
* **PARCOACH**: 19 timeouts and 30 reduced-TU compile failures (22 on g++-buildable code: missing `<algorithm>`/`<array>` symbols) in the base run — all "covered" and clean for the loop; timeouts deterministic (re-run hangs again).
* **LLOV**: parser missed `Directive Not Analyzed` (28 records whose only output was that line stored as 0 findings) and `path:line:col` locations (2 records lost their only race verdict); 26 of 28 LLOV errors compile with g++ (missing preamble).
* **Summary last-writer-wins (Hinweis B confirmed)**: every pilot_001 `static_analysis_summary.json` says `tools_run=['llov']`; invocation order A vs B produced byte-different summaries over identical records; `tools_skipped` erased by the next invocation.
* **Config parity (Hinweis C confirmed, latent)**: orchestrator registered tools without `config=`; identical values today only by coincidence (300 s / level 2 / 60 s equal the constructor defaults).
* **Event path (Hinweis D confirmed)**: one finding, path events only in raw stderr; 174 of 181 pilot blocking analyzer findings lost even their warning line to the 8000-char cap.
* **grace identity (Hinweis E confirmed)**: `(check_id, line)` collides across tools and files.
* **Retry (Hinweis F confirmed)**: direct mode 1 generate call (= retry_attempts+1 = 3 provider attempts) per `run_repair.py` restart, unbounded; batch: failed → resubmit unbounded; completed batch with item error or missing response → re-polled forever, never resubmitted.

## 5. Tool-state model (`tool_state.v1`)

Additive fields on every tool entry: `analysis_state`, `analysis_complete`, `analysis_gap_reason`, `analysis_details`, `tool_verdict`, `tool_state_schema`. States: `NOT_APPLICABLE`, `COMPLETED`, `PARTIAL`, `NOT_ANALYZED`, `TOOL_ERROR`, `TIMEOUT`. Verdicts: `DEFECT_FOUND` (blocking finding in a COMPLETED or PARTIAL run), `CLEAN` (COMPLETED, no blocking finding), `NO_TRUSTWORTHY_VERDICT` (everything else), `NOT_APPLICABLE`. A state is never a finding and never reaches the repair LLM. Records written before the wave are classified by `framework.legacy_analysis_state` (persisted fields + raw output); the record-level `effective_tool_state` turns a front-end rejection of a TU the authoritative compiler also rejected into `NOT_ANALYZED` (subsumed by the compiler's blocking verdict, no gap of its own). Schema versions: `static_analysis.v3` (records, additive), `static_analysis_summary.v2`, `repair_state.v2` (4-field grace keys, `analysis_gaps`, `request_rounds`; v1 read tolerantly).

Host test `thesis/evaluation/test_tool_state.py` group A covers the verdict matrix, the legacy derivation and the subsumption.

## 6. compiler

Rules: build completed with exit 0 → COMPLETED (`build_ok`); exit ≠ 0 with an error diagnostic (incl. linker `undefined reference` / `ld returned`) → COMPLETED + blocking (synthetic `compile-failed` when no located error was parsed); timeout → TIMEOUT, **no** synthetic finding; missing binary (`command not found`), `internal compiler error`, `cc1plus:/g++: fatal error`, non-zero exit without any error diagnostic → TOOL_ERROR, no synthetic finding. Fixtures (container): clean COMPLETED/0, model compile error COMPLETED/1 blocking, timeout TIMEOUT/0 without `compile-failed`, missing binary TOOL_ERROR/0 — all PASS. Host tests add the link-failure case (COMPLETED + `compile-failed`) and the no-diagnostic case. The compiler `note:` findings (26 in pilot_001, non-blocking) are left untouched to keep finding identities stable.

## 7. gcc_analyzer

Rules: timeout → TIMEOUT; non-zero exit → TOOL_ERROR (`tu_rejected`; NOT_ANALYZED when the compiler also failed); `analysis bailed out early` anywhere in stderr (header-located or location-less) or any `-Wanalyzer-too-complex` diagnostic judged **before** the model-file filter → PARTIAL; otherwise COMPLETED. Too-complex findings keep their identities (999 in pilot_001, info, non-blocking; not deduplicated to preserve counts). Fixtures: clean COMPLETED, multi-step null path COMPLETED/1 blocking **with attached path events**, vector/iota kernel PARTIAL (19 program points, 10 in the model file), STL-heavy kernel with planted null dereference PARTIAL with 0 findings (the measured false negative is now visibly not clean), broken TU TOOL_ERROR, timeout TIMEOUT — all PASS. Reviewer caveat recorded: the absence of a bail-out line is necessary, not sufficient, for full coverage (the analyzer budget depends on the whole TU); `-DOMPI_SKIP_MPICXX` was **not** adopted because it changes 15 of 20 pilot MPI finding sets (68 → 40 blocking).

## 8. clang_tidy

Rules (LLVM 18 measured: check findings never change the exit code): timeout → TIMEOUT; front-end rejection = any `clang-diagnostic-error` finding **or** stderr `Found compiler error(s).` (clang may locate every error in baseline.hpp/cpu.cc) → TOOL_ERROR with the diagnostic kept non-blocking (`tu_rejected`); exit ≠ 0 without rejection → TOOL_ERROR (unwritable fixes file, bad config, missing binary); exit 0 without fixes.yaml and without any diagnostic summary → TOOL_ERROR; otherwise COMPLETED. Adversarial check: `__builtin_shuffle` builds with g++ and is rejected by clang → TOOL_ERROR, 0 blocking (measured; before the wave a blocking "defect"); the reverse case exists in pilot_001 (`-Wchanges-meaning`: g++ rejects, clang accepts) — only the compiler is authoritative. MPI-Checker low-confidence family unchanged (measured working). Fixtures: clean, narrowing (1 blocking), GCC-only builtin, broken TU, timeout — all PASS. The false comment ("normal findings also yield exit 1") was replaced.

## 9. cppcheck

Rules: timeout → TIMEOUT; exit ≠ 0 → TOOL_ERROR carrying the stdout message; missing or malformed `<results>` block → TOOL_ERROR (`_parse_xml` now returns the XML state); tool-side ids (`syntaxError`, `internalError`, `internalAstError`, `cppcheckError`, `unknownMacro`, `missingInclude*`, and `preprocessorErrorDirective` whose message does **not** start with `#error`/`#warning`) → non-blocking, state PARTIAL (NOT_ANALYZED when the compiler failed); a genuine `#error` directive stays a blocking model defect; otherwise COMPLETED with blocking = severity `error`. Fixtures: clean, bounds (1 blocking), broken TU PARTIAL/0, `#error` COMPLETED/1, prose apostrophe PARTIAL/0, malformed XML TOOL_ERROR, CLI error TOOL_ERROR, timeout — all PASS.

## 10. infer

Rules: timeout → TIMEOUT; exit ≠ 0 → TOOL_ERROR (`tu_rejected`); no report.json → TOOL_ERROR; unparseable report.json → TOOL_ERROR; `Nothing to compile` / `There was nothing to analyze` with exit 0 → TOOL_ERROR; `Aborting translation of method '<m>'` → PARTIAL when findings exist elsewhere, NOT_ANALYZED otherwise (the aborted method is the OpenMP kernel in every pilot_001 OMP record); otherwise COMPLETED. InferBO L1/L2 filter unchanged; `--keep-going` measured to have no effect on capture failures (kept); `--fail-on-issue` must never be added. Fixtures: clean COMPLETED, OMP kernel NOT_ANALYZED, null dereference COMPLETED/1, broken TU TOOL_ERROR, report missing TOOL_ERROR, timeout — all PASS. Consequence: infer has no OpenMP kernel verdict in pilot_001 (140 NOT_ANALYZED effective: 130 aborts + 10 subsumed). `HARD_CAPABILITIES['infer']` still lists omp; changing the scope is a config decision left open (reported, not decided).

## 11. parcoach

Rules: non-mpi → NOT_APPLICABLE; reduced-TU compile timeout → TIMEOUT ("reduced-TU compile timed out"); reduced-TU compile failure → TOOL_ERROR (`tu_rejected`, NOT_ANALYZED when the compiler failed too); parcoach timeout → TIMEOUT; non-zero parcoach exit → TOOL_ERROR; otherwise COMPLETED (`No issues found` or warnings). Reduced TU now carries the cpu.cc system-include preamble (method change; measured: identical findings on already-analyzable samples, 22/22 compile-OK pilot failures compile). Fixtures A–D (container): unconditional collective COMPLETED/0, rank-conditional COMPLETED/1 blocking marked low-confidence (`mark_low_confidence` with the config), same collective in both branches COMPLETED/0, `std::array` shape (histogram/20 benchmark) COMPLETED/0 (pilot_001: compile failure), `std::sort` shape compiles and then hits PARCOACH's own genuine 60 s timeout (TIMEOUT, as on the sort benchmarks of pilot_001), broken TU TOOL_ERROR, timeout TIMEOUT, omp NOT_APPLICABLE — 8/8 PASS. Precision stays at the MBI 0.506 low-confidence classification; PARCOACH warning message text is order-nondeterministic, so identities stay `(check_id, line)`-based.

## 12. llov

Rules: non-omp → NOT_APPLICABLE; timeout → TIMEOUT; non-zero clang exit (incl. plugin crash exit 254, plugin load error) → TOOL_ERROR, verdict lines of the failed run discarded; per-region counts (`race`, `free`, `not_analyzed`) drive the state: race → COMPLETED (PARTIAL if regions were also not analyzed), free + not analyzed → PARTIAL, not analyzed only → NOT_ANALYZED, no region verdict at all → NOT_ANALYZED, free only → COMPLETED. Parser accepts `Directive Not Analyzed` and `path:line:col`. Flags: `LLOV_ANALYSIS_FLAGS` identical to the Dockerfile self-test; plugin loaded (identity measured `clang version 7.1.0 … LLVMOMPVerify 93321be`). Fixtures (container, python3.8): race free COMPLETED/0, shared-scalar race COMPLETED/1, function call in loop NOT_ANALYZED, mixed PARTIAL, compile error TOOL_ERROR, `std::sort` without include COMPLETED (pilot_001: exit 1), tasks-only NOT_ANALYZED, timeout TIMEOUT, serial NOT_APPLICABLE, plus two parser unit checks — 11/11 PASS. "Region Not Analyzed" ≠ "Race Free" is enforced at the state level (`entry_is_clean` requires COMPLETED). Summary counts per run: race detected / race free completed / region not analyzed / partial / tool error / timeout (`llov_classes`).

## 13. Merge semantics

`run_static_analysis.run_model` merges per `sample_id` across invocations. New: a per-sample `sample_source_sha256` pinned on the record; `provenance.check_merge` refuses a merge when the candidate source changed (hard fail, exit 3, nothing written); a per-tool `tool_execution_fingerprint_sha256` with the full `tool_execution_condition` on every entry; `check_tool_entry_merge` keeps an identical entry (idempotent), refuses a changed condition unless `--replace-tool-entries TOOL` is passed, and refuses to mix an unfingerprinted legacy entry with a fingerprinted one. A persisted gap entry is terminal on a plain re-run; `--rerun-gaps` re-analyzes it explicitly. Different tools from their correct containers merge freely. Host tests D/E/F cover all seven matrix cases.

## 14. Summary semantics

`static_analysis_summary.v2` is a pure function of the merged records, the config-enabled expectation and the append-only invocation history: `expected_tools`, `per_tool` {execution_models, applicable_samples, samples_with_entry, samples_missing_entry, completed, partial, not_analyzed, not_analyzed_subsumed_by_compiler, tool_error, timeout, incomplete, clean_completed, findings, blocking, low_confidence}, `tools_with_applicable_samples`, `tools_completed_on_all_applicable`, `tools_with_analysis_gaps`, `tools_with_missing_entries`, `findings_per_tool`/`blocking_per_tool`/`low_confidence_per_tool`, `llov_classes`, `invocations` (label, tools requested/run/skipped, entries run/kept, legacy pins). `tools_run`/`tools_skipped` at top level are the legacy last-invocation views, documented as such. Test D proves: main→parcoach→llov and the reverse order give identical summaries apart from the invocation history; `tools_skipped` of an earlier invocation survives in the history.

## 15. Source-hash / resume safety

Test E: same sample_id with changed `generated-code.hpp` bytes → `StaticMergeConflict`, file bytes unchanged. Legacy records without a pinned hash are pinned on first contact and the limitation is logged/recorded in the invocation. Reviewer finding adopted: driver/benchmark changes are invisible to the per-sample hash, therefore the run-level static condition now carries `drivers_tree_sha256` over `drivers/cpp`.

## 16. Execution fingerprints

Per tool entry: implementation hash (`inspect.getsource` of the tool class + its helper functions and tables), shared-modules hash, effective settings (scope, low-precision policy), options (timeouts, InferBO level, primary compiler, LLOV home), build config (macro, cxxflags), TU strategy, measured runtime identity (`--version`), candidate source hash → `tool_execution_fingerprint_sha256` (content-addressed, not git HEAD; a README change does not invalidate anything). Run level: `static_analysis_condition_sha256` (tool list, per-tool condition without runtime identities so all containers agree, build config per execution model, external command templates, low-confidence policy, drivers tree, tools module) and `repair_condition_sha256` (variants, max_iterations, strategies, history mode, low-confidence policy, feedback template fingerprint, tool-state schema, retry policy: provider `retry_attempts` vs orchestrator `request_retry_rounds`). Final values (deterministic across interpreter processes): `static_analysis_condition_sha256 = 327b235a8014cb682befe013a6176895c0b65a0ba8938a56f34ed1736aa820a3`, `repair_condition_sha256 = 09a8e8a20a0582202e5b35496c47b17cdf8b4fdf5badc4b824035482bca9cd36`, `drivers_tree_sha256 = a6105f1d3b9b384ebb7c2f4fbe1e7a71277001cbcd5abedf0bef7092fcf72ee2`. A reproducibility defect was found and fixed inside this wave: set-typed constant tables (`CPPCHECK_TOOL_SIDE_IDS`, `CPPCHECK_BLOCKING_SEVERITIES`, `LLVM_DECLARE_ATTR_TOKENS`) made the cppcheck and parcoach implementation hashes vary between interpreter processes (str hash randomization); the tables are now canonicalized (`_canonical_table`) and test O compares two fresh interpreters. Both are registered in the run manifest (`register_static_condition` / `register_repair_condition`: first contact writes, a different value later hard-fails) and the repair condition is pinned in `wave_state.json` (resume under a changed policy is refused). Test N/O: reproducible, sensitive to a tool option and to the retry policy. pilot_001 has none of these fields → reconstructed / HISTORICAL_PROVENANCE_LIMITATION (see §24).

## 17. Repair config parity

`RepairLoop._run_analysis_stages` now calls `register_default_tools(primary_compiler=…, config=self.config)`; test L injects `gcc_analyzer.timeout_seconds = 7` and verifies the repair path resolves it (audit measured the old path resolving 300/2/60 regardless of a synthetic 7/1/9 config). The repair summary expectation covers the external tools too, so a pilot_002 iteration summary reports parcoach/llov as missing until their containers ran.

## 18. Analysis-gap semantics

`required_static_tools(config, variant, execution_model)` = enabled static tools in scope (test_feedback: compiler only). `evaluate_stop` collects `analysis_gaps` (tool, state, reason) from the effective record states; a gap is never an issue. Outcomes: no issue + gap → **`stopped_analysis_incomplete`** (terminal, non-model; reason lists `tool STATE (reason)`); issue + gap → `active` with the gap persisted in `counts.analysis_gaps` and the state entry; complete coverage + no issue → `stopped_clean`; a rejection subsumed by the compiler's failure is not a gap. `missing_internal_stages` / `pending_external` still wait only for a MISSING entry (NO RECORD = pending); a persisted TIMEOUT/TOOL_ERROR/NOT_ANALYZED entry is terminal and never re-run on resume (the deterministic PARCOACH 60 s hang is not paid again); `external_coverage()` logs the split (pending vs each state) while waiting. Consumers updated: `status_row` and `run_repair.print_status` (columns `gap`, `api`), `build_overview` (per-tool `<tool>_analysis_state` columns, verdict cells only for COMPLETED/PARTIAL, non-model statuses as their own `na_reason`), `run_backfill` unchanged (key-presence = record exists, which is the intended pending criterion). Test I covers all cases; test J/K the persistence.

## 19. Low-confidence grace_once

Identity widened to `LOW_CONFIDENCE_IDENTITY_FIELDS = (tool, check_id, file, line)`; legacy 2-field keys are matched on `(check_id, line)` only (documented, never re-interpreted as "never seen"). Policy unchanged: one-iteration memory (a finding that disappears and returns gets a new grace round — the documented design, confirmed by the reviewer against design doc and config). Tests A–E in `test_tool_state.py::test_grace_identity`; pilot_001 states keep their 2-field keys (17 records), nothing rewritten.

## 20. GCC event path

`parse_gcc_analyzer_paths` reads the analyzer's inline event trace (`(N) text` lines with their source line and function frames) and attaches it to the ONE finding (`Finding.path`), capped deterministically (`ANALYZER_PATH_MAX_EVENTS = 12`: head 5 + tail 7). `feedback.render_finding` renders `path:` with numbered events (origin → branch condition → defect), non-model frames marked as context. No finding count change (test C; pilot_001 re-parse of 237 uncapped records identical). Raw-stderr truncation at 8000 chars remains (path events are attached at run time, before the cap).

## 21. Direct retry audit

Measured: each `run_repair.py` invocation makes one `adapter.generate` call with `retry_attempts = 2` (3 provider attempts) and drops the failed record on the next load → unbounded across restarts. Now: `request_rounds.json` (per sample, per iteration) counts orchestrator-level submissions before each call; `stages.repair.request_retry_rounds` (validated positive integer, default **2** = initial submission + one resubmission = up to 6 provider attempts; justification: provider-internal retries already cover transient errors, one restart-level round covers an outage window, anything beyond is an infrastructure condition to resolve, not to pay for silently); dropped failure records are appended to `failed_responses.jsonl` (history). Test J: first run blocks, the run using the last round ends the sample, exactly 2 generate calls, ledger persisted, further runs never resubmit.

## 22. Batch retry audit

Measured: failed batch → resubmit unbounded; completed batch with per-item error → record merged then dropped, `batch.json` kept → the finished batch is polled forever; completed batch without the sample → polled forever. Now: a completed batch's unanswered requests get an explicit non-terminal `BatchResponseMissing` record and `batch.json` is consumed, so the next run resubmits — counted as a new round in the same ledger; failed batches resubmit under the same bound. Test K: 2 submissions, 2 polls, then `stopped_api_exhausted`. Provider asymmetry recorded, not changed: Anthropic's poll never returns `failed` (item-level errors), batch `EmptyResponse` with finish_reason length is non-terminal while direct maps it to `ReasoningBudgetExhausted`.

## 23. Retry exhaustion semantics

`stopped_api_exhausted` (terminal, in `NON_MODEL_TERMINAL_STATUSES` with `stopped_baseline_incompatible` and `stopped_analysis_incomplete`): reason names the rounds used and the last failure; never `repair_unusable`; counted in its own status_row column; re-opened only by resetting the ledger explicitly. `ModelRefusal` → `repair_unusable` and `ReasoningBudgetExhausted` → `repair_unusable` unchanged (terminal error types, no provider retry multiplication).

## 24. pilot_001 static inventory

Base run: 396 records (11 models × 12 benchmarks × 3 execution models × 1 sample), schema `static_analysis.v2`, all 7 tool keys present in every record, no summary trusted (all 11 say `tools_run=['llov']`).

Effective states (legacy derivation + subsumption; records read only):

| tool | COMPLETED | PARTIAL | NOT_ANALYZED | TOOL_ERROR | TIMEOUT | NOT_APPLICABLE |
| --- | --- | --- | --- | --- | --- | --- |
| compiler | 396 | 0 | 0 | 0 | 0 | 0 |
| gcc_analyzer | 231 | 154 | 11 (subsumed) | 0 | 0 | 0 |
| clang_tidy | 386 | 0 | 10 (subsumed) | 0 | 0 | 0 |
| cppcheck | 396 | 0 | 0 | 0 | 0 | 0 |
| infer | 256 | 0 | 140 (130 frontend aborts + 10 subsumed) | 0 | 0 | 0 |
| parcoach | 83 | 0 | 8 (subsumed) | 22 | 19 | 264 |
| llov | 49 | 10 | 47 (2 subsumed) | 26 | 0 | 264 |

258 records carry an analysis gap of at least one required tool; 119 have every applicable tool COMPLETED and clean. LLOV re-derivation from the retained raw output (never capped): stored 63 findings / 32 race findings → 67 / 36; classes stored {error 28, no_finding 57, not_analyzed_only 21, race 26} → re-derived {error 28, race_free_only 25, not_analyzed_only 45, race 28, free_and_not_analyzed 6}; 73 of 132 OMP samples have no trustworthy race verdict. Iteration runs (6 directories, separate population): the same gap pattern recurs (inventory JSON, per directory). gcc_analyzer PARTIAL is a lower bound (raw stderr capped in 148 records).

## 25. pilot_001 repair inventory

33 loops (11 models × 3 variants), all `phase=done` at iteration 2; 1903 `repair_state.v1` records; statuses only active / stopped_clean / stopped_tests_pass / stopped_budget (no refusal, no BI, no gap/API statuses — vocabulary postdates the pilot); final: static_feedback 340 clean / 56 budget, test_feedback 337 tests_pass / 59 budget, combined_feedback 292 clean / 104 budget; 66 iteration generation files, 715 records, 715 success, 0 provider errors / refusals (failure history was erased by drop-on-load, so orchestrator-level resubmissions are not reconstructible); grace keys 2-field in 17 records; no `repair_condition_sha256` anywhere. Re-assessment of the clean stops under the tool-state model (no record rewritten): static_feedback 207 of 340 and combined_feedback 167 of 292 would have been `stopped_analysis_incomplete` (infer OMP abort 120/101, gcc bail-out/too-complex 102/76, LLOV not-analyzed 58/43, LLOV error 30/27, PARCOACH timeout 19/15, PARCOACH reduced-TU failure 25/23); test_feedback 337/337 keep complete coverage (compiler only).

## 26. Per-tool comparability (pilot_001 vs prospective pilot_002)

| tool | class | reason (short) |
| --- | --- | --- |
| compiler | DIRECTLY_COMPARABLE | same g++ 13.3.0 image, parser and flags; rule change touches 0 pilot records |
| gcc_analyzer | COMPARABLE_WITH_LIMITATIONS | identical tool; states re-derived (PARTIAL lower bound); compare COMPLETED populations only |
| clang_tidy | COMPARABLE_WITH_LIMITATIONS | identical tool; clang-diagnostic-error no longer blocking (23 findings, all compiler-failed records) |
| cppcheck | COMPARABLE_WITH_LIMITATIONS | identical tool; 1 lexer finding no longer blocking |
| infer | METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE for omp; COMPARABLE_WITH_LIMITATIONS for serial/mpi | frontend abort recognised; pilot_001 has no OMP kernel verdict |
| parcoach | METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE | reduced-TU preamble; TAG_ONLY container identity |
| llov | METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE | parser fix + preamble; TAG_ONLY identity (clang 7.1.0 recorded) |

Unknown stays unknown: no pilot_001 image digest, no per-tool timestamps, no per-tool argv.

## 27. Repair comparability

METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE: stop semantics (analysis-incomplete status), grace identity, bounded retries, pinned repair condition, LLOV/infer/parcoach coverage changes alter what a `stopped_clean` means; feedback content unchanged except the analyzer path rendering and the removal of duplicate clang lines; `baseline_incompatible` status unchanged; provider/retry semantics changed (bounded); history mode, variants, max_iterations unchanged. pilot_001 repair OUTCOMES therefore compare only as "clean under the old semantics" and must not be set against pilot_002 rates without the re-assessment table of §25.

## 28. K6

K6 (`repair terminal status`, VERDICT_RELEVANT, outside the 396 iteration-0 cells) is extended in the cross-pilot artifact to the three non-model terminal statuses `stopped_baseline_incompatible` / `stopped_analysis_incomplete` / `stopped_api_exhausted`, with the measured pilot_001 effect (0 persisted records; 207/167 clean stops would reclassify). K1–K5 untouched.

## 29. Preflight integration

`thesis/evaluation/check_static_repair_readiness.py` measures: config (repair policy incl. `request_retry_rounds`, docker mode, a command template per external tool), the current static/repair condition fingerprints, and — in the containers — the minimal fixtures per tool (clean + verdict) for the five internal tools in `pareval-thesis` and for parcoach/llov through the configured images (`parcoach-demo:2.4.1` / `pareval-llov` with `python3.8`); result READY / NOT_READY / UNRESOLVED written to `thesis/evaluation/static_repair_readiness.json`. `pilot_preflight.py` consumes the artifact (section STATIC_REPAIR_READINESS_CHECK): missing → UNRESOLVED, measured under another static/repair condition → UNRESOLVED (stale), NOT_READY → mismatch, READY → pass. "Image exists" is never accepted as "analysis works". Result of the run in this wave: see §32.

## 30. Finding-set regression

| tool | FINDING_SET_CHANGED_BY_TOOL | explanation |
| --- | --- | --- |
| compiler | false | parser unchanged; the new toolchain-failure rule matches 0 pilot_001 records |
| gcc_analyzer | false | parser unchanged; 237/237 uncapped pilot records re-parse identically; path events attached only |
| clang_tidy | true (blocking flags only) | 23 base + 60 iteration `clang-diagnostic-error` findings blocking → non-blocking; identities unchanged; every one in a compiler-failed record, no stop decision changes |
| cppcheck | true (blocking flags only) | 1 base (+ 3 + 3 iteration) lexer/syntax findings blocking → non-blocking; identities unchanged |
| infer | false | parser and L1/L2 filter unchanged; state only |
| parcoach | COVERAGE_ONLY | parser unchanged; the preamble makes 22 base entries analyzable (measured: identical findings on already-analyzable samples) |
| llov | true (parser bug fix) | +4 race findings and +not-analyzed entries re-derivable from pilot_001 raw output; reported next to the stored values, stored records untouched |

No precision threshold changed; PARCOACH stays low-confidence; InferBO L1/L2 unchanged; `verify_detection.py` (planted detection regression) result: see §32.

## 31. Remaining limitations

* gcc_analyzer COMPLETED means "no coverage-loss signal emitted", not proof of full exploration (reviewer measurement: the bail-out budget depends on the whole TU).
* infer analyzes no OpenMP kernel (clang-11 frontend); whether to narrow its configured scope to serial/mpi is a config decision not taken here.
* PARCOACH: deterministic hangs on `std::sort`-heavy kernels remain TIMEOUT gaps; validation precision unchanged at 0.506.
* LLOV: race Source-line attribution jitters between runs (measured), so identities stay `(check_id, line)`; plugin crashes (exit 254) are TOOL_ERROR gaps.
* raw_stderr cap of 8000 chars keeps truncating gcc_analyzer/cppcheck MPI output; states are computed before the cap.
* pilot_001: no condition fingerprints, TAG_ONLY container identities, no retry history — historical provenance limitations, not reconstructed as facts.
* `run_backfill.stage_coverage` keeps key-presence semantics (record exists); gap reporting there is left to the reporting wave.
* The batch provider asymmetry (`EmptyResponse` vs `ReasoningBudgetExhausted`) is documented, not changed.

## 32. Final readiness

### Final gate runs (after all changes)

| gate / suite | result |
| --- | --- |
| `check_cross_pilot_gate.py` | CURRENT (exit 0) after the recorded reevaluation of `framework.py` (function-level assessment stored in the artifact); self-fingerprint `44821aee46ce3541984ea22894c153a6ef854100be1e1f8fdc78b5941e4fdb53` |
| `check_semantic_decisions.py` | PASS_WITH_DISCLOSURE (unchanged: 6 resolved, 1 accepted disclosure) |
| `check_prompt_oracle_consistency.py` (pareval-thesis) | PASS (23 consistent) |
| `check_static_repair_readiness.py` (host, containers started by the tool) | **READY**; static condition `327b235a8014cb682befe013a6176895c0b65a0ba8938a56f34ed1736aa820a3`, repair condition `09a8e8a20a0582202e5b35496c47b17cdf8b4fdf5badc4b824035482bca9cd36` |
| `pilot_preflight.py` STATIC_REPAIR_READINESS_CHECK | see below |
| `verify_detection.py` (pareval-thesis, planted detection regression) | see below |
| `test_comparator_semantics.py` (pareval-thesis) | see below |
| host suites | test_tool_state (13 groups incl. cross-process reproducibility), test_orchestrator 12, test_feedback 8, test_backfill 7, test_evaluation 27, test_overview 7, test_semantic_decisions, test_cleaning 13, test_generation 10, test_enhanced 11, e311 6, e31 4, e3_cache 6, e2b 7, e2a1 7, capabilities: all green |
| frozen assets | `git diff` clean for thesis/enhanced_tests/frozen, thesis/prompts, semantic decisions, interlock registry, drivers/ |

Readiness fixtures measured by the tool (image → fixture → status → state):

| tool | fixture | status | state |
| --- | --- | --- | --- |
| compiler | compiler clean | PASS | COMPLETED |
| compiler | compiler model compile error | PASS | COMPLETED |
| gcc_analyzer | gcc_analyzer clean | PASS | COMPLETED |
| gcc_analyzer | gcc_analyzer multi-step null path | PASS | COMPLETED |
| clang_tidy | clang_tidy clean | PASS | COMPLETED |
| clang_tidy | clang_tidy narrowing | PASS | COMPLETED |
| cppcheck | cppcheck clean | PASS | COMPLETED |
| cppcheck | cppcheck bounds | PASS | COMPLETED |
| infer | infer clean | PASS | COMPLETED |
| infer | infer null dereference | PASS | COMPLETED |
| parcoach | parcoach A unconditional collective | PASS | COMPLETED |
| parcoach | parcoach B rank-conditional collective (low confidence) | PASS | COMPLETED |
| llov | llov race free | PASS | COMPLETED |
| llov | llov data race | PASS | COMPLETED |

`verify_detection.py` (container) tail:

```
  [PASS] clean/mpi: asan_ubsan
  [PASS] clean/mpi: must
  [PASS] broken: compiler (expected blocking; got blocking=True error=False)
  [PASS] broken: gcc_analyzer (expected error; got blocking=False error=True)
  [PASS] broken: clang_tidy (expected blocking_or_error; got blocking=False error=True)
  [info] broken: cppcheck (exempt) -> findings=1 error=None
  [PASS] broken: infer (expected error; got blocking=False error=True)
  [PASS] broken: asan_ubsan (expected error; got blocking=False error=True)
  [PASS] broken: tsan (expected error; got blocking=False error=True)
  [PASS] broken: memcheck (expected error; got blocking=False error=True)
  [PASS] broken: must (expected error; got blocking=False error=True)
  [PASS] broken: helgrind (expected error; got blocking=False error=True)
  [PASS] broken: drd (expected error; got blocking=False error=True)
TOTAL  detection: 15/16  clean: 23/24  fail-safe: 10/10
```

`test_comparator_semantics.py` (container) tail:

```
all comparator-semantics checks passed
```

`pilot_preflight.py` run with a scratch self-declaration (pilot_002 population and base run id are still OPEN, so the overall result is the expected honest NOT_READY/UNRESOLVED; the static/repair section is what this wave adds):

```
STATIC_REPAIR_READINESS_CHECK
  readiness artifact gate = READY (created 2026-09-05T18:53:18.228834Z)
  static_analysis_condition_sha256 = 327b235a8014cb682befe013a6176895c0b65a0ba8938a56f34ed1736aa820a3
  repair_condition_sha256 = 09a8e8a20a0582202e5b35496c47b17cdf8b4fdf5badc4b824035482bca9cd36
  compiler (pareval-thesis): PASS
  gcc_analyzer (pareval-thesis): PASS
  clang_tidy (pareval-thesis): PASS
  cppcheck (pareval-thesis): PASS
  infer (pareval-thesis): PASS
  parcoach (registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1): PASS
  llov (pareval-llov): PASS
STATIC_REPAIR_READINESS = READY
RESULT: NOT_READY - pilot_002_not_authorized (open declarations/decisions or missing provenance; with the pilot_002 population and base-run-id targets still open this is the expected honest state, not a test failure)
```

### Readiness verdict

Static/Repair is technically ready for pilot_002 under the tool-state model: every fail-closed guarantee of the contract is implemented, tested on the host and measured in the three containers, the merge/summary/provenance path is order-independent and hard-fails on drift, the repair loop no longer reports gaps as clean and no longer retries without bound, and the cross-pilot artifact records the static/repair comparability honestly. The remaining blockers before pilot_002 are outside this wave: pilot_002 population (NOT_YET_DECIDED), base run id (NOT_YET_CONFIGURED), reuse (UNDECIDED), publication (unchanged), semantic disclosure rendering (reporting wave), post-run manifest verification (REQUIRED_NOT_IMPLEMENTED), and the runtime image pinning (TAG_ONLY; digests are now measurable and were recorded in the readiness declaration).
