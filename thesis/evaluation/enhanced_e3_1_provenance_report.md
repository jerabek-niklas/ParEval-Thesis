# Enhanced E3.1 — Frozen Spec Artifact, Canonical Mutation Frontier & Fail-Closed Execution Resume

Provenance hardening for E3. No spec was generated, no API was called, no policy
was touched, no pilot was started.

---

## 1. Provenance

| | |
|---|---|
| Repository | `jerabek-niklas/ParEval-Thesis` |
| Branch | `thesis-static-analysis` |
| Start-HEAD | `b038eb1e8d7ebf94a4ea3b221c40df719ffda56e` („fixes", 2026-08-30 20:14) — **verifiziert** |
| Parent | `dffbaa8145667bf74033decebb0217abbf150855` (E3) |
| Working Tree bei Start | **tracked clean**, keine untracked Dateien |
| End-HEAD | unverändert `b038eb1e…` — **kein Commit erstellt** |

**Gates vor jeder Änderung** — alle Exit 0: `check_enhanced_capabilities.py`,
`derive_enhanced_policy.py --check`, `test_capabilities.py`,
`test_e2a1_safety.py`, `test_e2b_policy.py`, `test_e3_cache.py`.
`check_cross_pilot_gate.py`: **Exit 1 — STALE**, wie erwartet, nicht aktualisiert.

---

## 2. Local cache hash verification

Zuerst geprüft, bevor irgendetwas kopiert oder geändert wurde:

| Artefakt | erwartet | gemessen | Match |
|---|---|---|---|
| `thesis/results/cache/enhanced/specs.jsonl` | `49b0229c…` | `49b0229c508f063008078bd58cb61bfebc82c2b2b75c680b42cdd262bd440292` | **PRE_E3_LOCAL_SHA_MATCH / FINAL_E3_LOCAL_SHA_MATCH = true** |
| `thesis/results/cache/enhanced/specs.pre_e3_dffbaa8.jsonl` | `0fe9561e…` | `0fe9561e13504ef8a2dd6455711628a6e8512848e9347e5576a02d777d0e1874` | **true** |

Keine andere lokale Datei wurde als Wahrheit verwendet.

---

## 3. Frozen artifact paths and hashes

Die beiden Artefakte liegen jetzt **außerhalb** des ignorierten Cachebaums, als
versionierte Provenance-Artefakte — nicht als mutabler Generatorcache:

| | |
|---|---|
| `thesis/enhanced_tests/frozen/e3_pre_specs.jsonl` | `0fe9561e13504ef8a2dd6455711628a6e8512848e9347e5576a02d777d0e1874` |
| `thesis/enhanced_tests/frozen/e3_final_specs.jsonl` | `49b0229c508f063008078bd58cb61bfebc82c2b2b75c680b42cdd262bd440292` |

Beide sind **binär exakte** Kopien (`byte-identical = True` gegen die lokalen
Originale). Keine Neuserialisierung, keine UTF-8-Normalisierung, keine
Sortierung, keine Rationale-Änderung. `git check-ignore` bestätigt: nicht
ignoriert, also committbar.

**Trennung von Generator und Execution-Input.** `run_enhanced_tests.py` nimmt
`--specs` jetzt standardmäßig aus dem eingefrorenen Artefakt statt aus
`thesis/results/cache/`. Der Generatorworkflow behält seinen mutablen ignorierten
Cache; wer daraus laufen will, übergibt ihn explizit. Das ist die kleinste
Architektur, die die Anforderung erfüllt — keine neue Config-Ebene.

| | |
|---|---|
| `FINAL_CACHE_VERSION_CONTROLLED` | **true** |
| `FINAL_CACHE_FULLY_RECONSTRUCTIBLE_FROM_COMMITTED_HEAD` | **true** |
| `FRESH_CLONE_CAN_RECREATE_EXACT_FINAL_CACHE_WITHOUT_LLM` | **true** |

Nicht, weil ein LLM-Lauf deterministisch wiederholbar wäre, sondern weil das
**tatsächlich akzeptierte Experimentartefakt selbst** versioniert eingefroren
ist. Genau das ist die geforderte Reproduzierbarkeit.

**Ehrliche Einschränkung.** Die rohen Provider-Antworten und der vollständige
Discarded-Proposal-Log des E3-Generationslaufs wurden **nicht** als Artefakt
persistiert und werden hier **nicht** rekonstruiert oder erfunden. Versioniert
und exakt wiederverwendbar ist das *akzeptierte* Artefakt; das *Erzeugungs-
verfahren* ist nicht re-derivierbar. Manifestfelder
`raw_provider_responses_retained = false` und `raw_provider_responses_note`
halten das fest. Das ist kein Blocker für die Wiederverwendung des
eingefrorenen Caches.

---

## 4. Fresh-clone reproducibility

`thesis/enhanced_tests/verify_e3_frozen_artifacts.py` prüft **ausschließlich aus
committeten Dateien** (beide Snapshots, das E3-Manifest, die aktuelle
Policy/Source) alle 17 geforderten Punkte: beide Hashes, 483/471 Pre-Counts,
471 Final, 12 Duplicate-Zeilen, 60 Benchmarks, Retention 262/10, invalid 199,
replacements 199, Replacement-Set exakt, Reexecution-Set exakt, final invalid 0,
duplicate 0, unsupported 0, out-of-domain 0, kein valider alter Spec verloren,
kein valides altes Objekt verändert.

**Fresh-Clone-Test.** Alle 1046 tracked bzw. zu committenden Dateien wurden in
ein Temp-Verzeichnis kopiert, `thesis/results/**` **ausgelassen**, kein venv,
kein API-Zugang. Dort:

```
thesis/results/ absent: good
E3_FROZEN_ARTIFACTS_REPRODUCIBLE = true
exit=0
```

**Fresh-clone verification: PASS.**

---

## 5. Duplicate identity audit correction

Der E3-Report behauptete, die 12 Duplicate-Zeilen hätten „nie einen Testfall
erzeugt". Das ist **zu stark** und wurde korrigiert (Nachtrag im E3-Report):

* **Direkte Ausführung:** korrekt — `build_benchmark_specs` dedupliziert auf
  `spec_key`, die Identität lief genau einmal. Die 12 Gruppen sind
  execution-equivalent (Unterschied nur im Freitext `rationale`, der weder in
  `spec_key` noch in `spec_defines` noch in `spec_runtime_env` eingeht).
* **Abgeleitete Ausführung:** falsch — bis E3.1 wurde die Mutation-Frontier aus
  den **rohen** Zeilen gebildet (`frontier = list(seeds)`).

Ebenfalls korrigiert: „byte-for-byte retained". Von den 272 erhaltenen
Identitäten sind **6 Zeilen nicht byteidentisch** (Nicht-ASCII im `rationale`
wird beim Schreiben anders kodiert); **alle 272 geparsten Objekte sind gleich**.
Korrekte Aussage: gleiches geparstes JSON-Spec-Objekt, gleicher `spec_key`,
gleiche Inputsemantik.

---

## 6. Historical mutation-frontier effect

Gemessen am versionierten Pre-E3-Snapshot, die beiden Effekte **getrennt**:

| Effekt | Benchmarks | raw-only Keys | canonical-only Keys | order-only |
|---|---|---|---|---|
| **1. Duplicate-Zeilen** (raw vs. first-occurrence-dedup) | **7** | **21** | **21** | `fft/08` |
| **2. Invalide Seedzeilen** (dedup vs. dedup+valid-only) | **46** | **152** | **138** | `scan/33`, `sparse_la/47` |

Effekt 1 reproduziert den Auditbefund exakt. Betroffen: `fft/05`, `fft/07`,
`geometry/10`, `histogram/23`, `search/39`, `sparse_la/46`, `sparse_la/49`.

Effekt 2 war bisher **nicht quantifiziert** und ist deutlich größer — invalide
Seeds wurden selbst nie emittiert, erzeugten aber Mutanten.

Mechanik in beiden Fällen: die Frontier-Länge bestimmt die Länge der
Mutationsliste, deren `rng.shuffle` und damit, welche Mutanten den
`target_cases_per_benchmark`-Cap überleben.

Diese historischen Mutationskeys werden **nicht** als Specs „wiederhergestellt".
Sie waren ein Artefakt der Zeilenvielfachheit, nicht eine methodische
Entscheidung.

---

## 7. Canonical frontier implementation

`thesis/enhanced_tests/specs.py::canonical_seed_identities(...)` reduziert die
Seedzeilen auf **ein Objekt pro `spec_key`: die erste VALIDE Occurrence**.
`build_benchmark_specs` baut daraus sowohl die emittierten Seeds als auch die
Mutation-Frontier.

* Identität ist `spec_key`; **Validität wird pro Objekt** entschieden, eine
  invalide erste Serialisierung maskiert also keine spätere valide Identität
  (getestet, auch wenn der aktuelle Bestand diesen Fall nicht enthält).
* Reihenfolge des ersten validen Auftretens bleibt erhalten.

| | |
|---|---|
| `canonical frontier implemented` | **true** |
| `invalid seeds excluded from frontier` | **true** |
| Duplicate-Zeilen können die abgeleitete Suite noch ändern | **nein** (getestet über den Pre-E3-Snapshot) |
| Invalide Zeilen können sie noch ändern | **nein** (dito) |

### Scope-Entscheidung, die der Auftrag nicht vorwegnimmt

Die Kanonisierung gilt für die **Seedzeilen aus dem Artefakt**, nicht für deren
Vereinigung mit dem statischen Basisset. Grund, gemessen: das eingefrorene
Artefakt ist bereits **0 Duplikate / 0 invalide** — die Kanonisierung der
Cachezeilen ist darauf also beweisbar ein No-op. Die zunächst gebaute Variante,
die `static + llm` gemeinsam dedupliziert, veränderte dagegen die eingefrorene
Suite in **10 Benchmarks**, weil `static_base_specs` in **12 Benchmarks mit 38
Identitäten** mit LLM-Seeds kollidiert. Eine solche Kollision ist keine
Serialisierungsvielfachheit, sondern zwei Generatoren, die dieselbe Identität
vorschlagen; sie erzeugt auch keine Fake-Diversity (die Emission dedupliziert
bereits), sondern verlängert nur die Mutationsliste vor dem Shuffle. Sie zu
kollabieren hätte die von E3 gerade eingefrorene Suite still umsortiert — was
der Auftrag explizit als BLOCKED-Bedingung nennt. Der Befund ist damit
dokumentiert und für eine spätere Welle offen, nicht stillschweigend
mitentschieden.

---

## 8. Proof the final E3 productive set is unchanged

Über alle 60 Benchmarks, `build_benchmark_specs` auf dem **versionierten finalen
Artefakt**, vor vs. nach dem Refactor:

| | |
|---|---|
| `FINAL_SEED_KEYS_CHANGED` | **0** |
| `FINAL_PRODUCTIVE_SPEC_KEYS_CHANGED` | **0** |
| `FINAL_PRODUCTIVE_SPEC_ORDER_CHANGED` | **0** |
| abgeleitete Specs gesamt | 1200 → **1200**, listenweise identisch |
| finaler Snapshot | 471 Specs, 471 Keys, 60 Benchmarks, invalid 0, unsupported 0, deferred 0, out-of-domain 0 |
| `final frozen SHA unchanged` | **true** (`49b0229c…`) |

---

## 9. Execution fingerprint composition

`thesis/enhanced_tests/execution_provenance.py::enhanced_execution_fingerprint()`
liefert eine kanonische JSON-Struktur plus `enhanced_execution_fingerprint_sha256`
(SHA-256 über die kanonische Kodierung, sortierte Keys).

| Komponente | Inhalt |
|---|---|
| **A** spec set | tatsächlicher Specs-Datei-SHA-256, Zeilen, distinkte `spec_key`s, Benchmarkzahl |
| **B** policy | `enhanced_policy` SHA, Capability-Katalog SHA, `derivation_version` |
| **C** harness | `drivers/cpp/enhanced-fill.hpp`, `drivers/cpp/utilities.hpp`, `thesis/enhanced_tests/specs.py`, `thesis/enhanced_tests/capabilities.py` |
| **D** runner | `thesis/evaluation/run_enhanced_tests.py` |
| **E** benchmark sources | `cpu.cc` + `baseline.hpp` je Benchmark (60), plus **ein** kombinierter kanonischer Hash |
| **F** driver/execution | serial/omp/mpi Driver, `harness-markers.hpp`, `build_config.py` |
| **G** effective config | `execution_models`, `enhanced_launch`, `max_spec_size`, `target_cases_per_benchmark`, `static_base_sizes`, `offered_patterns`, `explicit_values_max_size`, `llm_specs_min/max` |
| **H** toolchain | Compileridentität/-version über den bestehenden `run_manifest`-Helfer, plus ob MPI in den Execution-Models steckt — **kein** neues Environment-Subsystem |

Alles ist **content-addressed**. Kein mtime, kein bloßer Pfad, **kein Git-HEAD**:
ein README-Commit invalidiert keinen Resume. Der HEAD darf danebenstehen, geht
aber nicht in den Hash ein (getestet).

| | |
|---|---|
| aktueller `enhanced_execution_fingerprint_sha256` | `2cd031f5ef0c66f0a1e31e012398a513387cf13df34d3950bb15c09f06df241b` |

Gespeichert wird der Block in **Enhanced Summary**
(`enhanced_execution_provenance`) **und** im **Run-Manifest**
(`enhanced_execution`).

---

## 10. Resume test matrix

Die Entscheidung liegt in genau einer Funktion,
`execution_provenance.resume_allowed(recorded, current)`, die der Runner
aufruft, bevor die `done`-Menge benutzt wird.

| # | Fall | Erwartung | Ergebnis |
|---|---|---|---|
| 1 | identische Provenance | resume accepted | **PASS** |
| 2 | andere Policy (B) | refused | **PASS** |
| 3a | fehlende Provenance | refused | **PASS** |
| 3b | leere Provenance | refused | **PASS** |
| 3c | nur Policy-Provenance (Pre-E3.1-Record) | refused | **PASS** |
| 4 | anderer Spec-Artefakt-SHA (A) | refused | **PASS** |
| 5 | geändertes `enhanced-fill.hpp` (C) | refused | **PASS** |
| 6a/6b | geändertes `specs.py` / `capabilities.py` (C) | refused | **PASS** |
| 7 | geänderte Benchmark-`cpu.cc`/`baseline.hpp` (E) | refused | **PASS** |
| 8a–8d | geänderter Driver / `build_config.py` / Runner / effective config (F, D, G) | refused | **PASS** |
| 9a | Manifest, gleicher Fingerprint | akzeptiert | **PASS** |
| 9b | Manifest, anderer Fingerprint | **hard fail** | **PASS** |
| 9c | Pre-E3.1-Manifest ohne Fingerprint | nicht backfillen-und-weiterlaufen | **PASS** |

Zusätzlich geprüft: die Refusal-Meldung **benennt die abweichende
Komponentengruppe**, der Guard steht **vor** der Verwendung der Resume-Menge,
und der Pfad beendet den Lauf (`sys.exit(3)`) statt Zeilen zu überspringen.

| | |
|---|---|
| `RESUME_GUARD_COVERS_POLICY_CHANGE` | **true** |
| `RESUME_GUARD_COVERS_SPEC_CACHE_CHANGE` | **true** |
| `RESUME_GUARD_COVERS_HARNESS_CHANGE` | **true** |
| `RESUME_GUARD_COVERS_DRIVER_CHANGE` | **true** |
| `RESULT_REUSE_STALE_RISK` (für die fingerprinted Condition) | **false** |

---

## 11. Run-manifest fail-closed behaviour

`ensure_run_manifest(..., enhanced_execution=...)` ist der einzige Parameter,
der **nicht** als Drift protokolliert, sondern **hart abbricht**: bei
abweichendem (oder fehlendem) `enhanced_execution_fingerprint_sha256` wirft er
`EnhancedExecutionConditionMismatch`, **bevor** ein Record geschrieben oder
übersprungen wird, mit dem Hinweis auf eine frische `run_id`. Ein bestehendes
Manifest wird **nicht** still auf die neue Semantik umgeschrieben, und `--force`
macht zwei semantisch verschiedene Läufe nicht zu einem.

---

## 12. Legacy result handling

Der lokale Bestand (77 nichtleere Enhanced-Recordfiles, 22 220 Records,
Summaries ohne `enhanced_policy_provenance`, Manifeste ohne Enhanced-Provenance)
wurde **nicht angefasst**: keine Datei gelesen-und-geschrieben, kein Backfill,
keine Löschung. Unter E3.1 gilt für sie: Resume **fail-closed** — sie tragen
keine Execution-Provenance, Fall 3a/3c oben, also Refusal und eine frische
`run_id`. Genau das ist gewollt: nicht backfillen und dann skippen.

---

## 13. Shortfall classification fix

Der Audit fand `SHORTFALL_CLASSIFICATION_SOUND = false`, weil `e3_regenerate.py`
auf ein `api_failed` prüfte, das produktiv nie gesetzt wurde — jeder Shortfall
wäre als `CAPABILITY_LIMITED` erschienen.

`generate_for_benchmark` liefert jetzt zusätzlich ein `outcome` mit
`reason ∈ {TARGET_MET, API_FAILURE, PARSE_OR_REFILL_EXHAUSTED,
CAPABILITY_LIMITED}` plus Telemetrie (Runden, API-Fehler, Parse-Fehler, gesehene
Proposals). `CAPABILITY_LIMITED` wird nur vergeben, wenn Antworten kamen **und**
parsebar waren **und** alle Refill-Runden liefen **und** alles Nicht-Akzeptierte
von der Validierung oder als Duplikat verworfen wurde. `e3_regenerate.py` liest
diese Ursache, statt sie zu raten; API-/Parsefehler werden
`GENERATION_FAILURE:<reason>`, ein fehlendes Outcome
`OTHER_BLOCKER:no_generator_outcome_recorded`.

Alle vier Klassen sind getestet (echte API-Ausfall-, Garbage- und
Nur-Invalid-Provider im Test). Der abgeschlossene E3-Lauf hatte
`replacement_shortfall = 0`, es gibt also **keine Datenkorrektur** — nur
Robustheit. **`shortfall classification: SOUND`.**

---

## 14. E3 report corrections

`thesis/evaluation/enhanced_e3_regeneration_report.md` bekam einen
Nachtragsblock plus drei Inline-Präzisierungen (Duplicate-Wirkung,
Retention-Gleichheit, Versionierung). **Keine Zahl wurde geändert**; der
E3-Stand bleibt als Dokument erhalten. **`E3 report corrected: true`.**

Das E3-Manifest wurde ergänzt um: `pre_e3_frozen_specs_path`, `pre_e3_sha256`,
`final_e3_frozen_specs_path`, `final_e3_sha256`,
`exact_cache_reconstruction_available`, `fresh_clone_verification_command`,
`duplicate_row_count`, `duplicate_group_count`, `duplicate_rows_valid`,
`duplicate_row_semantics`, `mutation_frontier_canonicalization_version`,
`retention_equality_semantics`, `raw_provider_responses_retained` und
`raw_provider_responses_note`. Keine bestehende Zahl wurde entfernt.

---

## 15. Cross-Pilot status

**Exit 1, `CROSS_PILOT_REPO_STATE_STALE = true`** — unverändert STALE. Keine
Fingerprints aktualisiert, keine 99/0/99-Neuberechnung, keine
Candidate-Neuklassifikation, kein Cross-Pilot-Artefakt geschrieben.

Zu vermerken für die nächste Welle: Cross-Pilot muss nun zusätzlich gegen den
**endgültig versionierten und fingerprinted** Enhanced Execution State neu
bewertet werden — die drei `enhanced_spec_keys`-Fingerprints der Kandidaten sind
seit E3 stale, und mit E3.1 existiert erstmals ein einziger Hash
(`2cd031f5…`), der die gesamte Enhanced Execution Condition adressiert.

---

## 16. Final E3 acceptance status

| | |
|---|---|
| finaler Snapshot | 471 Specs / 471 Keys / 60 Benchmarks / invalid 0 |
| SHA unverändert | `49b0229c…` |
| version controlled | **ja** |
| aus committetem HEAD rekonstruierbar | **ja** |
| ohne LLM/API reproduzierbar | **ja** |
| Mutation deterministisch aus Seedidentitäten | **ja** |
| Resume an die volle Execution Condition gebunden | **ja** |

**E3 ist damit vollständig akzeptierbar**, und der Weg zur
Cross-Pilot-Reevaluation ist frei: das Enhanced-Artefakt ist eingefroren,
versioniert, unabhängig prüfbar und gegen stille Wiederverwendung geschützt.
