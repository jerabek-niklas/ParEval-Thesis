# Enhanced E3.1.1 — Complete Execution Fingerprint

Closing the four remaining gaps in `enhanced_execution_fingerprint`: candidate
sources, run timeout, effective jobs and MPI toolchain identity. No spec was
touched, no policy changed, no API called.

---

## 1. Provenance

| | |
|---|---|
| Repository | `jerabek-niklas/ParEval-Thesis` |
| Branch | `thesis-static-analysis` |
| Start-HEAD | `137695e62d94852ee970603274733f12604ef461` („fixes", 2026-08-31 13:15) — **verifiziert** |
| Parent | `b038eb1e8d7ebf94a4ea3b221c40df719ffda56e` (E3.1) |
| Working Tree bei Start | **tracked clean**, keine untracked Dateien |
| End-HEAD | unverändert `137695e6…` — **kein Commit erstellt** |

**Gates vor jeder Änderung — alle grün:** `check_enhanced_capabilities.py`,
`derive_enhanced_policy.py --check`, `test_capabilities.py`,
`test_e2a1_safety.py`, `test_e2b_policy.py`, `test_e3_cache.py`,
`test_e31_execution_provenance.py`, `verify_e3_frozen_artifacts.py`
(`E3_FROZEN_ARTIFACTS_REPRODUCIBLE = true`).
`check_cross_pilot_gate.py`: **Exit 1 — STALE**, nicht aktualisiert.

Beide Frozen-Hashes zu Beginn bestätigt:
`e3_final_specs.jsonl = 49b0229c…`, `e3_pre_specs.jsonl = 0fe9561e…`.

---

## 2. Timeout gap and fix

**Lücke.** `run_enhanced_tests.py` löst
`run_timeout = float(stage.get("run_timeout_seconds", DEFAULT_RUN_TIMEOUT))`
**separat** aus `stages.enhanced_tests` auf und reicht den Wert an die
Spec-Ausführung weiter. `stage_settings(config)` enthält dieses Feld **nicht**,
und der Fingerprint wurde mit `stage_settings` gebildet — eine Änderung
30 s → 60 s ließ den Fingerprint also unverändert, obwohl sie denselben
Kandidaten von `timeout` nach `pass`/`fail` kippen kann.

**Fix.** `enhanced_execution_fingerprint(...)` bekommt einen expliziten
`runtime`-Block; `G_effective_config` enthält jetzt
`run_timeout_seconds` mit dem **tatsächlich aufgelösten** Wert (Stage-Config,
sonst `DEFAULT_RUN_TIMEOUT`), nach derselben Auflösung wie im Runner. Der
Fingerprint verlässt sich nicht mehr implizit darauf, dass `stage_settings`
alles enthält.

Aktuell aufgelöst: **`run_timeout_seconds = 60.0`**.

---

## 3. Jobs gap and fix

**Lücke.** Die Provenance wurde berechnet, **bevor**
`cli_jobs = parse_jobs_arg(args.jobs)` und `jobs = resolve_jobs(settings, cli_jobs)`
liefen. Ein `--jobs serial=2` war damit nicht im Fingerprint.

**Fix.** Reihenfolge im Runner umgestellt auf: Settings → Timeout → CLI-Jobs
parsen → effektive Jobs auflösen → **dann** Fingerprint. `G_effective_config`
enthält jetzt `effective_jobs` nach dem Merge aus Built-in-Defaults, Config und
CLI-Override, **sortiert** abgelegt, damit eine bloße Dict-Reihenfolge keinen
Resume invalidiert (getestet).

Formulierung bewusst zurückhaltend: das ist **keine** Aussage, dass
Parallelität die mathematische Semantik ändert, sondern eine *operational
execution condition capable of affecting timeout outcomes* — genau das, was der
Runner in seiner eigenen Overcommit-Notiz festhält.

Aktuell aufgelöst: **`effective_jobs = {mpi: 1, omp: 1, serial: 2}`**.

---

## 4. Candidate source gap and fix

**Lücke.** Der Record hängt am getesteten Programm, der Fingerprint enthielt es
nicht. `sample_id` ist ein **Name**, keine Content-Adresse
(`<model>__<type>__<name>__<exec>__sample_<i>`). Gleiches
`run_id` + `model_id` + `sample_id` + `spec_key` bei **anderem**
`generated-code.hpp` hätte denselben `done`-Key ergeben — Resume hätte den alten
Record behalten.

**Fix.** `candidate_source_fingerprint(intermediate_dir, run_id, model_id)`
hasht die **tatsächlichen Sourcebytes** jedes assemblierten Samples. Discovery
läuft über den produktiven Pfad `framework.iter_assembled_samples(...)` (der
`assembly.jsonl` konsumiert) — **keine zweite Kandidaten-Discovery-Logik**.

Geprüft: `assembly.jsonl` (`schema_version assembly.v1`) enthält **keinen**
Content-Hash des Assemblats, nur `source_path`. Also wird der Sourceinhalt
direkt gehasht; lokale mutable Metadaten werden dafür nicht vertraut.

Pro Sample erfasst: `sample_id`, `model_id`, `execution_model`, `benchmark`,
`source_logical_path` (repo-relativ, damit ein Verzeichnisprefix nichts ändert)
und `source_sha256`. Die Liste wird nach `sample_id` sortiert und kanonisch
gehasht.

**Scope-Architektur.** Enhanced-Summaries und Resume laufen **pro Modell**,
also:

```
GLOBAL   enhanced_execution_fingerprint         Specs, Policy, Harness,
                                                Benchmarks, Driver, Config,
                                                Toolchain
PRO MODELL  candidate_source_fingerprint        die Sourcebytes dieses Modells
            model_execution_fingerprint         global + candidate
```

Der Resume-Check vergleicht den **model execution fingerprint**.

Verifikation auf echten Daten (read-only): `pilot_001` / `claude_fable_5` →
**36 assemblierte Samples, 0 fehlende Sources**, kombinierter Hash `58ea17a2…`.

---

## 5. MPI toolchain gap and fix

**Lücke.** `H_toolchain` enthielt `primary_compiler`,
`primary_compiler_version` und `mpi_in_execution_models`, aber keine MPI-
Implementierungs-/Versionidentität.

**Fix.** Über den bestehenden Helfer `run_manifest._compiler_version` (der
generisch `<tool> --version` ausführt) — **keine neue Environmentarchitektur**:

| Feld | im Container gemessen |
|---|---|
| `mpi_compiler` / `mpi_compiler_version` | `mpicxx` → `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0` |
| `mpi_runtime` / `mpi_runtime_version` | `mpirun` → `mpirun (Open MPI) 4.1.6` |

**Ehrlicher Befund:** `mpicxx --version` gibt die **Backend-Compilerversion**
zurück, nicht die Open-MPI-Version — der OpenMPI-Wrapper reicht `--version`
durch. `mpi_compiler_version` allein würde zwei Open-MPI-Installationen mit
demselben g++ also **nicht** unterscheiden. Deshalb wird zusätzlich
`mpirun --version` erfasst, das die tatsächliche MPI-Identität trägt. Beide
zusammen sind fingerprinted.

**Nur wenn MPI wirklich läuft.** Die MPI-Felder werden ausschließlich
aufgenommen, wenn `mpi ∈ execution_models` — ein serial-only Lauf wird also
nicht von einer ungenutzten MPI-Installation abhängig (getestet: MPI 4.1.6 →
9.9.9 lässt den serial-only Fingerprint unverändert).

Fehlt ein Tool, steht dort `None` — **kein erfundener Versionsstring**. Ein
produktiver MPI-Lauf kommt in dem Zustand ohnehin nicht am Environment-Gate
vorbei.

---

## 6. CLI specs / manifest consistency

**Nebenbefund bestätigt.** `run_enhanced_tests.py` fingerprintet `args.specs`,
`run_manifest.enhanced_specs_info(config)` las dagegen
`stages.enhanced_tests.specs_file` bzw. den Default. Mit
`--specs <anderes File>` hätte ein Manifest zwei widersprüchliche
Spec-Provenienzen dokumentiert: `enhanced_execution` den CLI-Hash,
`enhanced_specs` einen anderen Pfad/Hash.

**Fix (klein).** `enhanced_specs_info(config, specs_path=None)` und
`ensure_run_manifest(..., enhanced_specs_path=...)`; der Runner reicht
`args.specs` durch. Getestet: der Manifest-Hash entspricht exakt dem
`A_spec_set.specs_sha256` des Fingerprints.

---

## 7. Old vs. new fingerprint composition

| Komponente | E3.1 | **E3.1.1** |
|---|---|---|
| A spec set | ✓ | ✓ |
| B policy | ✓ | ✓ |
| C harness sources | ✓ | ✓ |
| D runner | ✓ | ✓ |
| E benchmark cpu.cc/baseline.hpp | ✓ | ✓ |
| F driver/build sources | ✓ | ✓ |
| G effective config | Settings | **+ `run_timeout_seconds`, + `effective_jobs`** |
| H toolchain | Compiler + MPI-Flag | **+ `mpi_compiler(_version)`, `mpi_runtime(_version)`** (nur bei MPI) |
| **Kandidatencode** | **fehlte** | **neu, pro Modell** (`candidate_source_fingerprint`) |
| Resume-Vergleichsobjekt | globaler Fingerprint | **`model_execution_fingerprint`** (global + Kandidatenhashes) |

`FINGERPRINT_VERSION` von `e3.1` auf **`e3.1.1`** gehoben. Weiterhin
content-addressed, weiterhin **ohne** Git-HEAD (ein README-Commit invalidiert
keinen Resume).

| | |
|---|---|
| aktueller globaler Fingerprint | `be65d65c8c6e31103aec2b80e791da485f4948b8c6d7c1bc981f576820c75ef1` |
| Beispiel Kandidaten-Fingerprint | `pilot_001`/`claude_fable_5`, 36 Samples → `58ea17a21ec82da5…` |
| Beispiel Modell-Fingerprint | aus beiden zusammengesetzt (Testfixture, kein realer Lauf ausgeführt) |

---

## 8. Resume matrix

Die E3.1-Matrix bleibt vollständig erhalten und wird ergänzt:

| Fall | Erwartung | Ergebnis |
|---|---|---|
| **A** run timeout 30 → 60 | REFUSED | **PASS** |
| **B** effektive Jobs `--jobs serial=2` | REFUSED | **PASS** |
| B′ nur Dict-Reihenfolge der Jobs | **kein** Refusal | **PASS** |
| **C** gleiches `sample_id`, anderer Kandidatensource | REFUSED | **PASS** |
| C′ identischer Kandidatencode | ACCEPTED | **PASS** |
| C″ globale Drift, gleicher Kandidat | REFUSED | **PASS** |
| **D** MPI-Version A → B bei MPI | REFUSED | **PASS** |
| D′ ungenutzte MPI-Version bei serial-only | **kein** Refusal | **PASS** |
| **E** anderes `--specs`-Artefakt | REFUSED | **PASS** |
| **F** alles identisch | ACCEPTED | **PASS** |
| Policy-Drift | REFUSED | **PASS** (E3.1) |
| Harness-Drift (`enhanced-fill.hpp`, `specs.py`, `capabilities.py`) | REFUSED | **PASS** (E3.1) |
| Benchmark-/Driver-Drift | REFUSED | **PASS** (E3.1) |
| fehlende Provenance | REFUSED | **PASS** |
| Record nur mit globaler (Pre-E3.1.1) Provenance | REFUSED | **PASS** |
| Manifest: gleiches Modell, anderer Fingerprint | **hard fail** | **PASS** |
| Manifest: **zweites Modell** unter derselben `run_id` | additiv erlaubt | **PASS** |

**Multi-Model.** Das Manifest ist `run_id`-global, deshalb pinnt es die globale
Execution Condition **und** führt zusätzlich eine additive Abbildung
`model_execution_fingerprints[model_id]`. Ein Modell wird einmal registriert;
dasselbe Modell mit anderem Fingerprint schlägt hart fehl, ein **neues** Modell
unter derselben `run_id` wird nicht blockiert, nur weil ein anderes Modell
zuerst lief.

---

## 9. Frozen suite unchanged

| | |
|---|---|
| `e3_final_specs.jsonl` SHA | **`49b0229c508f063008078bd58cb61bfebc82c2b2b75c680b42cdd262bd440292`** (unverändert) |
| `e3_pre_specs.jsonl` SHA | `0fe9561e…` (unverändert) |
| Frozen Spec Count | **471** |
| `FINAL_SEED_KEYS_CHANGED` | **0** |
| `FINAL_PRODUCTIVE_SPEC_KEYS_CHANGED` | **0** |
| `FINAL_PRODUCTIVE_SPEC_ORDER_CHANGED` | **0** |
| abgeleitete Suite | 1200 Specs, listenweise identisch über alle 60 Benchmarks |
| `verify_e3_frozen_artifacts.py` | `E3_FROZEN_ARTIFACTS_REPRODUCIBLE = true` |

Keine Spec regeneriert, keine Spec geändert, `spec_key` unverändert,
`enhanced_tests.v1` unverändert, E2-B-Policy unverändert, **0 API-Calls**.

---

## 10. Cross-Pilot

**Exit 1, `CROSS_PILOT_REPO_STATE_STALE = true`** — unverändert STALE. Keine
Fingerprints aktualisiert, keine 99/0/99-Neuberechnung, keine
Candidate-Neubewertung, kein Artefakt geschrieben.

Für die nächste Welle bleibt festzuhalten: die Cross-Pilot-Reevaluation kann
sich jetzt auf einen Enhanced Execution State stützen, der **vollständig**
content-adressiert ist — Specs, Policy, Harness, Benchmarks, Driver, Config,
Timeout, Jobs, Toolchain **und** den tatsächlich getesteten Kandidatencode.

---

## 11. Result-reuse assessment

`RESULT_REUSE_STALE_RISK = false` ist nach E3.1.1 **defensibel** für die
definierte Enhanced Execution Condition: jede der Achsen, über die ein Record
veralten kann — Spec-Artefakt, Policy, Harness, Benchmark-Oracle, Driver,
Runner, effektive Config, Timeout, Jobs, Toolchain (inkl. MPI, wenn benutzt) und
der Kandidatencode selbst — ist content-adressiert und wird vor jeder
Wiederverwendung verglichen; fehlende Provenance blockiert.

Die Aussage gilt ausdrücklich **für diese definierte Condition** und nicht für
Einflüsse außerhalb davon (z. B. Kernel-/libc-Unterschiede, Maschinenlast
jenseits der Jobkonfiguration). Diese liegen weiterhin außerhalb des
Enhanced-Fingerprints und sind kein Gegenstand dieser Welle.
