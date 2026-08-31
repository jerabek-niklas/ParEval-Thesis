# Enhanced E3 — Spec Regeneration, Cache Freeze & Execution-Set Provenance

Policy-finalized replacement of the specs E2-B invalidated. No methodology was
decided, no policy changed, no harness semantics touched.

---

## 1. Provenance

| | |
|---|---|
| Repository | `jerabek-niklas/ParEval-Thesis` |
| Branch | `thesis-static-analysis` |
| Start-HEAD | `dffbaa8145667bf74033decebb0217abbf150855` („fixes", 2026-08-30 16:47) — **verifiziert** |
| Parent | `ab202b2b0ff8d6dd502fee00aba81a93e111c64e` (E2-B) |
| Working Tree bei Start | **tracked clean**, keine untracked Dateien |
| End-HEAD | unverändert `dffbaa8…` — **kein Commit erstellt** |
| Python | 3.14.5 (Repo-venv `.venv\Scripts\python.exe`) |
| Compiler | g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) im `pareval-thesis`-Container |

**Gates vor jeder Änderung** — alle Exit 0:

| Kommando | Ergebnis |
|---|---|
| `check_enhanced_capabilities.py` | `ENHANCED_CAPABILITIES_CONSISTENT = true` |
| `derive_enhanced_policy.py --check` | Policy = Derivation |
| `test_capabilities.py` | passed |
| `test_e2a1_safety.py` | passed |
| `test_e2b_policy.py` | passed |
| `check_cross_pilot_gate.py` | **Exit 1 — STALE** (seit E2-A erwartet) |

Keine Cross-Pilot-Fingerprints angefasst.

---

> ## Nachtrag E3.1 (2026-08-30) — zwei zu starke Aussagen in diesem Report
>
> Dieser Report bleibt als Dokument des E3-Standes bestehen. Ein anschließender
> read-only Audit hat zwei Formulierungen als **zu stark** belegt; beide werden
> hier korrigiert, die zugrunde liegenden Zahlen ändern sich nicht.
>
> **(1) „…sie haben also nie einen Testfall erzeugt" (§3, Duplicate-Zeilen).**
> Für die **direkte** Ausführung stimmt das: `build_benchmark_specs` dedupliziert
> auf `spec_key`, die Identität lief genau einmal. Die Zeilen waren aber **nicht
> wirkungslos**: die Mutation-Frontier wurde bis E3.1 aus den **rohen** Seedzeilen
> gebildet (`frontier = list(seeds)`), eine doppelt serialisierte Zeile stand also
> zweimal in der Frontier und veränderte über die Länge der Mutationsliste die
> Shuffle-Reihenfolge — und damit, welche Mutanten den Target-Cap überlebten.
> Gemessen am Pre-E3-Snapshot: **7 Benchmarks, 21 raw-only und 21
> canonical-only abgeleitete Keys**, dazu `fft/08` mit denselben Keys in anderer
> Reihenfolge. Derselbe Mechanismus galt für **invalide** Seedzeilen, dort
> deutlich größer: **46 Benchmarks, 152 raw-only / 138 canonical-only**.
>
> Richtig ist also: *die doppelte Identität wurde einmal ausgeführt, aber die
> doppelte Serialisierung konnte die abgeleitete Mutationsmenge verändern.*
> E3 hat die Duplicate-Serialisierung aus dem Cache entfernt; **E3.1**
> kanonisiert zusätzlich die Frontier, sodass künftig Seedidentitäten und nicht
> Zeilenvielfachheit bestimmen, was ein Benchmark testet. Siehe
> `thesis/evaluation/enhanced_e3_1_provenance_report.md`.
>
> **(2) „wortwörtlich übernommen" / „byte-for-byte" (§5, Retention).**
> Identität und Semantik stimmen, die Bytes nicht in allen Fällen: von den 272
> erhaltenen Identitäten sind **6 Zeilen nicht byteidentisch** zu ihrer
> Pre-E3-Serialisierung, weil Nicht-ASCII-Zeichen im Freitext `rationale` beim
> Schreiben anders kodiert werden. **Alle 272 geparsten JSON-Objekte sind
> gleich** (`VALID_OLD_SPECS_MODIFIED = 0` gilt unverändert, es vergleicht die
> Objekte). Korrekt formuliert: *dasselbe geparste JSON-Spec-Objekt, derselbe
> `spec_key`, dieselbe Inputsemantik* — nicht notwendig dieselbe Byte-Zeile.
>
> Ebenfalls präzisiert: §3 nennt den Cache „nicht versioniert". Das galt für
> E3. **E3.1 versioniert** die beiden Artefakte unter
> `thesis/enhanced_tests/frozen/` (`e3_pre_specs.jsonl`,
> `e3_final_specs.jsonl`), byte-exakt zu den hier genannten SHA-256.

## 2. Policy cleanup

Zwei nicht-funktionale Textreste aus E2-B, plus die davon abhängigen
Docstring-Passagen — **8 Edits**, ausschließlich in
`thesis/enhanced_tests/derive_enhanced_policy.py`:

| # | Stelle | vorher | nachher |
|---|---|---|---|
| 1 | `_meta.generated_by` (emittiert) | „…(E2-A, E2-A.1)" | „…(E2-A, E2-A.1, E2-B)" |
| 2 | `FILL_TYPE_REASON` (emittiert in **jedes** `fill_type_capability.reason`) | „clipping would decide VALUE_RANGE_DOMAIN_POLICY, **which stays open**" | benennt die technische Schranke als solche und verweist auf die von E2-B eingefrorene `SUBSET_OF_DECLARED_BENCHMARK_FILL_DOMAIN` |
| 3–8 | Docstring: Kopfzeile, Eröffnungsabsatz, R3-Titel, R3-Rationale, R4b, R5 | beschrieben EXTREME_PATTERN_SEMANTICS / VALUE_RANGE_DOMAIN_POLICY / SIZE_ZERO_SPEC_POLICY als „stays open" | benennen sie als von E2-B eingefroren und R3 als superseded |

**Beweis, dass nichts Produktives kippte** (alte vs. neu abgeleitete Policy,
Feld für Feld über alle 60 Benchmarks):

| | |
|---|---|
| Benchmarkmenge identisch | true (60) |
| **harte semantische Differenzen** | **0** |
| Einträge, die sich NUR in einem `reason`-String unterscheiden | 49, ausschließlich `fill_type_capability.reason` |
| `frozen_e2b_policies` identisch | true |
| `status` identisch | true |
| geänderte `_meta`-Keys | nur `generated_by` |

Verglichen wurden `supported_patterns`, `unsupported_patterns`,
`deferred_policy_patterns`, `size_constraint`, `fill_domain_capability`,
`fill_type_capability`, `adapter_policy`, `size_zero_policy`, `pattern_effect`,
`pattern_coverage`.

**`POLICY_BEHAVIOR_CHANGED_BY_E3_CLEANUP = false`.**

Nach dem Cleanup: `derive_enhanced_policy.py` → `--check` Exit 0,
`check_enhanced_capabilities.py` Exit 0.

| | |
|---|---|
| `E3_POLICY_SHA256` | `1173ac98200e65f4ae6e0995b9ea41db60d3851dc7d048151f8f89e91c1619b4` |
| `E3_CAPABILITY_CATALOG_SHA256` | `8f3a0b6ad84aa183339bb12129dc638470c9c322d3a7e6fc300d7895c98dbada` |
| `derivation_version` | `e2b.1` (unverändert — die Regeln wurden nicht angefasst) |

---

## 3. Old cache fingerprint

| | |
|---|---|
| `OLD_SPECS_PATH` | `thesis/results/cache/enhanced/specs.jsonl` |
| `OLD_SPECS_SHA256` | `0fe9561e13504ef8a2dd6455711628a6e8512848e9347e5576a02d777d0e1874` |
| Zeilen | 483 |
| **distinkte Specs** | **471** (siehe unten) |
| Benchmarks | 60 |
| Source-Verteilung | `llm` 483 |

**Befund, der die Auftragsannahme korrigiert.** Der Auftrag geht davon aus, der
Parent-Commit sei die unveränderliche historische Kopie und ein Backup deshalb
entbehrlich. Das trifft **nicht** zu: `.gitignore:23` ignoriert
`thesis/results/cache/`, der Speccache ist **nicht** versioniert
(`git show HEAD:…specs.jsonl` → „exists on disk, but not in 'HEAD'"). Die
Bedingung „…wenn die Datei versioniert ist" ist also nicht erfüllt, und E3 hat
vor jeder Änderung eine explizite Kopie angelegt:

`thesis/results/cache/enhanced/specs.pre_e3_dffbaa8.jsonl`, sha256
`0fe9561e…` (byteidentisch verifiziert). Der Retention-Beweis vergleicht gegen
diese Kopie, nicht gegen git.

**Zweiter Befund: 12 doppelte Zeilen.** Der historische Cache serialisiert 12
`spec_key`s zweimal (7 Paare beidseitig invalid, 5 beidseitig valid). Die
Duplikate unterscheiden sich **ausschließlich** im Freitext `rationale`, der
weder in `spec_key` noch in `spec_defines` noch in `spec_runtime_env` eingeht —
und `build_benchmark_specs` verwarf sie für die **direkte** Ausführung ohnehin
(es dedupliziert auf `spec_key`), die Identität lief also genau einmal.
*(E3.1-Korrektur: wirkungslos waren sie damit trotzdem nicht — bis E3.1 wurde
die Mutation-Frontier aus den rohen Zeilen gebildet, siehe Nachtrag oben.)* E3 behandelt sie als
**redundante Zeilen einer Spec**, nicht als zusätzliche Specs: Populationsbasis
sind die **471 distinkten Identitäten**, die erste Zeile bleibt erhalten. Damit
geht keine Spec verloren und der finale Cache erfüllt `UNIQUE_SPEC_KEYS`.

---

## 4. E2-B classification reproduction

`classify_specs_e2b.py` gegen den tatsächlichen committed Cache — **exakt** der
erwartete Stand, nichts hartkodiert:

| | erwartet | reproduziert |
|---|---|---|
| `TOTAL_EXISTING_SPECS` | 483 | **483** |
| `INVALID_BY_POLICY_ONLY` | 160 | **160** |
| `INPUT_DRIFTED_BUT_STILL_VALID` | 11 | **11** |
| `INVALID_AND_DRIFTED` | 46 | **46** |
| `UNCHANGED_AND_VALID` | 266 | **266** |
| invalid total | 206 | **206** |
| retained valid | 277 | **277** |

Auf Identitätsebene (Duplikate abgezogen): 199 invalid, 272 valid.

---

## 5. Retention strategy

`thesis/enhanced_tests/e3_partition.py` erzeugt vier **disjunkte** Mengen, deren
Vereinigung alle 483 Zeilen ist:

| Menge | Zeilen | Behandlung |
|---|---|---|
| `RETAINED_UNCHANGED` | **262** | unverändert übernommen (gleiches geparstes Objekt, gleicher `spec_key`) |
| `RETAINED_DRIFTED` | **10** | unverändert übernommen, gleicher `spec_key`, `requires_reexecution = true` |
| `INVALID_TO_REPLACE` | **199** | aus dem finalen Cache entfernt |
| `DUPLICATE_ROW` | **12** | redundante Zweitserialisierung, erste Zeile bleibt |

Retained Specs werden als **das ursprüngliche JSON-Objekt** übernommen — kein
Parametercleanup, kein Range-Normalisieren, kein Rationale-Umschreiben, kein
Pattern-/Sizewechsel. Der `spec_key` ist damit konstruktionsbedingt unverändert.
*(E3.1-Präzisierung: identisch ist das **geparste Objekt**, nicht in allen
Fällen die Byte-Zeile — 6 der 272 Zeilen kodieren Nicht-ASCII im `rationale`
anders. Siehe Nachtrag oben.)*

---

## 6. Invalid removal

Alle 199 invaliden Identitäten (206 Zeilen) sind entfernt. Keine wurde
„gerettet" durch Clippen, Normalisieren, Parameterentfernen, Umbenennen oder
Sizekorrektur. Gründe der Entfernung:

| Reason | Anzahl |
|---|---|
| `explicit_value_outside_declared_domain` | 48 |
| `no_pattern_effect` | 49 |
| `unsupported_pattern_for_benchmark` | 45 (41× `extreme_values`, 4× `all_zeros`) |
| `invalid_size_for_benchmark` | 24 |
| `value_range_outside_declared_domain` | 24 |
| `irrelevant_pattern_parameter` | 7 |
| `value_range_not_supported_for_benchmark` | 5 (`sort/43`) |
| `inert_parameter_for_benchmark` | 2 |
| `unsafe_value_range_span` | 1 |
| `value_not_representable_for_benchmark` | 1 |

---

## 7. Generation strategy

Ersatzspecs stammen **ausschließlich** aus dem produktiven Generatorpfad
`generate_test_specs.py::generate_for_benchmark`. Es wurde **kein** zweiter
Generator geschrieben; die Funktion bekam zwei optionale Argumente:

```python
generate_for_benchmark(..., retained_specs=None, replacement_budget=None)
```

* `retained_specs` — deren `spec_key`s initialisieren die Dedupe-Menge (eine
  Ersatzspec kann also nie mit einer erhaltenen kollidieren) und werden dem
  Modell als `ALREADY ACCEPTED` gezeigt;
* `replacement_budget` — ersetzt `llm_specs_min` als Ziel, bemisst den Ask
  („propose N NEW specs") und begrenzt die Annahme.

Prompt-Bau, Validierung, Capability-Enforcement, Dedupe und Refill sind
unverändert dieselben wie in einem normalen Lauf. Zusätzlich wurde die
Client-Verdrahtung aus `main()` in `make_call_llm()` gezogen, damit eine
Teilregeneration **exakt** denselben Provider, dasselbe Modell, dieselben
Generation-Defaults, denselben Timeout und dasselbe Retry-Verhalten benutzt —
statt sie zu duplizieren.

`spec_model` unverändert: **`glm_5_2`** (`openai_compatible`). Kein Provider-,
Modell-, Temperature-, Thinking- oder Retrywechsel. Keine handgeschriebene Spec.

---

## 8. Replacement budgets

Pro Benchmark `replacement_budget = invalid_count` (Identitäten), Obergrenze
`final_count <= old_count`. 57 der 60 Benchmarks brauchten Ersatz;
`histogram/20`, `histogram/21`, `stencil/51` hatten keine invaliden Specs.

| | |
|---|---|
| `REPLACEMENT_BUDGET_TOTAL` | **199** |
| `REPLACEMENTS_GENERATED` | **199** |
| `REPLACEMENT_SHORTFALL` | **0** |

---

## 9. Generator / API results

| | |
|---|---|
| Benchmarks regeneriert | 57 / 57 |
| Ersatzspecs akzeptiert | 199 / 199 |
| Benchmarks `under_target` | **0** |
| `GENERATION_FAILURE` | **0** |
| Refill-Runden nötig | in keinem Benchmark bis zur Erschöpfung |

Der Lauf lief einmal vollständig als **Dry-Run** (Cache unangetastet); die
akzeptierten Specs wurden inkrementell zwischengespeichert und der finale
atomare Schreibvorgang lief mit `--resume`, also **ohne einen einzigen
zusätzlichen Modellaufruf**.

---

## 10. Capability shortfalls

Keine. `CAPABILITY_LIMITED_REPLACEMENT_SHORTFALL = 0`, Liste leer. Es musste
kein Benchmark mit weniger Specs akzeptiert werden, und kein Shortfall musste
gegen `GENERATION_FAILURE` abgegrenzt werden.

---

## 11. Per-benchmark final counts

| | |
|---|---|
| `FINAL_TOTAL_SPECS` | **471** |
| `FINAL_BENCHMARK_COUNT` | **60** |
| `MIN_FINAL_SPECS_PER_BENCHMARK` | **5** |
| `MAX_FINAL_SPECS_PER_BENCHMARK` | **12** |
| Benchmarks mit `final_count < old_count` | **0** |
| Benchmarks mit `final_count > old_count` | **0** |

Für jeden Benchmark gilt `final_count == old_count` (distinkt). Die vollständige
Tabelle `old_row_count / duplicate_rows / old_count / retained_unchanged /
retained_drifted / invalid_removed / replacement_budget / replacements_generated
/ capability_shortfall / final_count / final_unique_spec_keys /
generation_sources / removed_reasons` steht im Manifest unter `per_benchmark`.

---

## 12. The six zero-valid-old benchmarks

Aus der aktuellen Klassifikation verifiziert (nicht übernommen) — alle sechs
sind vollständig neu besetzt:

| Benchmark | old | retained | replacements | final | invalid reasons | frozen capability |
|---|---|---|---|---|---|---|
| `fft/09_fft_fft_out_of_place` | 5 | 0 | **5** | **5** | `invalid_size` (size 0 / non-power-of-two), `explicit_value_outside_domain` | Domain `[-1,1]`, size-zero DISALLOWED, power-of-two-Predicate |
| `graph/15_graph_edge_count` | 10 | 0 | **10** | **10** | `no_pattern_effect` ×10 | kein Fill-Hook → nur kanonisches `random`, Variation über `size` |
| `search/37_search_find_the_closest_number_to_pi` | 8 | 0 | **8** | **8** | `constant_outside_declared_domain` (`all_zeros`), `explicit_value_outside_domain` | Domain `[100,1000]`, `min_size 1` |
| `sort/41_sort_k-th_smallest_element` | 8 | 0 | **8** | **8** | `irrelevant_pattern_parameter` ×8 (irrelevantes `k`) | Domain `[0,10000]`, size-zero DISALLOWED |
| `sparse_la/45_sparse_la_sparse_solve` | 5 | 0 | **5** | **5** | `no_pattern_effect` ×5 | kein Fill-Hook → nur `random` + `size` |
| `sparse_la/49_sparse_la_sparse_lu_decomp` | 10 | 0 | **10** | **10** | `no_pattern_effect`, `inert_parameter` | kein Fill-Hook → nur `random` + `size` |

Kein Benchmark hat nach E3 null Specs.

---

## 13. Final validation sweep

Jede Spec des temporären finalen Caches lief durch `validate_spec` gegen die
tatsächliche Benchmarkmenge, **bevor** irgendetwas ersetzt wurde:

| Prüfung | Ergebnis |
|---|---|
| `FINAL_INVALID_SPEC_COUNT` | **0** |
| `FINAL_DUPLICATE_SPEC_KEY_COUNT` | **0** |
| `FINAL_EXTREME_VALUES_COUNT` | **0** |
| `FINAL_UNSUPPORTED_PATTERN_COUNT` | **0** |
| `FINAL_DEFERRED_PATTERN_COUNT` | **0** |
| `FINAL_NONFINITE_PARAM_COUNT` | **0** |
| `FINAL_OUT_OF_DOMAIN_COUNT` | **0** |
| `FINAL_IRRELEVANT_PARAM_COUNT` | **0** |
| `FINAL_UNKNOWN_PARAM_COUNT` | **0** |
| `FINAL_INERT_PARAM_COUNT` | **0** |
| `FINAL_INVALID_SIZE_COUNT` | **0** |
| `FINAL_BENCHMARK_COUNT` | **60** |
| `MIN_FINAL_SPECS_PER_BENCHMARK` | **5** (≥ 1) |

**Atomarer Austausch.** Der vollständige neue Cache wurde in eine Temp-Datei im
Zielverzeichnis geschrieben, `fsync`ed und per `os.replace` eingesetzt — erst
nachdem alle Gates grün waren. Bei einem Fehler wäre der alte Cache unangetastet
geblieben (der Dry-Run demonstrierte genau das). Der auf Platte gemessene
SHA-256 entspricht exakt dem vorab berechneten: `ATOMIC_REPLACEMENT = PASS`.

---

## 14. Duplicate / fake-diversity checks

Gegen den **finalen** Cache (`test_e3_cache.py`, Gruppe 2):

| | |
|---|---|
| `extreme_values` | **0** |
| unsupported/deferred Patterns | **0** |
| irrelevante / inerte / unbekannte Parameter | **0** |
| out-of-domain Range oder expliziter Wert | **0** |
| non-finite Parameter | **0** |
| degenerierte Range auf einem anderen Label als `all_same` | **0** |
| Fillparameter auf einem no-fill Benchmark | **0** |
| no-fill Benchmark mit anderem Pattern als `random` | **0** |
| globale `value_range` auf `sort/43` | **0** |
| `k` auf einem Nicht-K-Pattern | **0** |
| `spike_at` out-of-domain oder mit size < 2 | **0** |
| doppelte `spec_key`s | **0** |

---

## 15. Retention proof

Gegen die explizite Pre-E3-Kopie (der Cache ist gitignored):

| | |
|---|---|
| `VALID_OLD_SPECS_DROPPED` | **0** |
| `VALID_OLD_SPECS_MODIFIED` | **0** |
| `INVALID_OLD_SPECS_RETAINED` | **0** |
| Benchmark über historischer distinkter Population | **0** |
| `spec_key` geändert | **false** |

---

## 16. Reexecution set

**`RETAINED_DRIFTED_REEXECUTION_COUNT = 10`** — die historischen Specs, deren
Identität gleich blieb, deren Input der Harness aber inzwischen anders baut
(E2-A DType-Fix und/oder E2-B Extreme-/Spike-Semantik). Sie wurden **nicht** neu
generiert und behalten ihren `spec_key`. Jeder Eintrag im Manifest unter
`requires_reexecution` trägt `benchmark`, `spec_key`, `pattern`, `size`,
`drift_reason`, `historical_harness_state`, `current_harness_state` (inkl.
Policy-Hash) und `requires_reexecution = true`.

**Abgrenzungshinweis.** Führt man `classify_specs_e2b.py` erneut über den
**post-E3**-Cache aus, meldet es 25 „drifted" statt 10. Seine Driftkarte ist
patternbasiert und markiert deshalb auch 15 **neu generierte** `spike_at`/
Ramp-Specs. Diese wurden unter der aktuellen Semantik erzeugt und nie
ausgeführt — sie können definitionsgemäß nicht driften. Autoritativ ist das
Manifest; `test_e3_cache.py` friert diese Unterscheidung als Assertion ein.

---

## 17. New replacement set

199 Ersatzspecs, alle mit `source = llm`, `spec_model = glm_5_2`,
`generation_reason = replacement_for_invalid`. Manifest:
`thesis/enhanced_tests/enhanced_e3_regeneration_manifest.json`,
Feld `replacement_specs` (benchmark, spec_key, pattern, size, source,
spec_model, generation_reason); Policy-/Katalog-Hash, Derivation-Version,
`spec_model` und der Generator-Config-Fingerprint stehen einmal im Kopf des
Manifests.

---

## 18. Old / new spec hashes

| | |
|---|---|
| `OLD_SPECS_SHA256` | `0fe9561e13504ef8a2dd6455711628a6e8512848e9347e5576a02d777d0e1874` |
| Backup | `thesis/results/cache/enhanced/specs.pre_e3_dffbaa8.jsonl` (byteidentisch) |
| Versionierter Snapshot (E3.1) | `thesis/enhanced_tests/frozen/e3_pre_specs.jsonl` / `e3_final_specs.jsonl`, byte-exakt |
| `NEW_SPECS_SHA256` | `49b0229c508f063008078bd58cb61bfebc82c2b2b75c680b42cdd262bd440292` |
| `policy_sha256` | `1173ac98200e65f4ae6e0995b9ea41db60d3851dc7d048151f8f89e91c1619b4` |
| `catalog_sha256` | `8f3a0b6ad84aa183339bb12129dc638470c9c322d3a7e6fc300d7895c98dbada` |

---

## 19. Source and distribution shifts

Nur Transparenz — es wurde keine Sourcequote erzwungen (der Generator definiert
keine).

| Source | alt | final |
|---|---|---|
| `llm` | 483 | **471** |

| Pattern | alt | final |
|---|---|---|
| `explicit_values` | 174 | 169 |
| `random` | 55 | **99** |
| `all_same` | 51 | 48 |
| `extreme_values` | **49** | **0** |
| `all_zeros` | 71 | 44 |
| `ascending` | 29 | 28 |
| `duplicate_at` | 19 | 25 |
| `alternating` | 6 | **20** |
| `spike_at` | 9 | 19 |
| `sorted_except_one` | 10 | 10 |
| `descending` | 10 | 9 |

Die Verschiebung ist genau das erwartete Bild der eingefrorenen Policy:
`extreme_values` verschwindet vollständig, `alternating` (das Label, das die
Konstruktion nach E2-B ehrlich beschreibt) verdreifacht sich, `random` wächst
dort, wo no-fill Benchmarks nur noch das kanonische Pattern kennen, und
`all_zeros` schrumpft dort, wo 0 außerhalb der deklarierten Domain liegt.

Size: alt min 0 / max 4096 / 23 distinkt → final min 0 / max 4096 / 24 distinkt.
Size-0-Specs: 62 → **44** (die von E2-B als DISALLOWED entschiedenen Benchmarks
haben keine mehr). `max_spec_size` unverändert 4096, keine Spec darüber.

---

## 20. Smoke tests

`e3_smoke_specs.py` wählt per Greedy-Cover die kleinste Menge **neu generierter**
Specs, die alle geforderten Klassen abdeckt, und baut daraus eine Containerprobe:
echter Serial-Driver + `cpu.cc` mit einem Kandidaten, der an das frozen Oracle
weiterreicht, unter UBSan+ASan+float-cast-overflow, **einmal über den
Define-Pfad und einmal über den Runtime-Pfad**.

| Spec | Klassen |
|---|---|
| `dense_la/03` `spike_at` size 2 | `type:double`, `multi-fill`, `value_range`, `K-pattern`, `size-zero-allowed` |
| `reduce/27` `explicit_values` size 2 | `type:double`, `explicit_values`, `size-zero-disallowed` |
| `graph/15` `random` size 0 | `no-fill`, `size-zero-allowed` |
| `reduce/28` `explicit_values` size 4 | `type:int`, `explicit_values` |
| `scan/31` `descending` size 4 | `type:float`, `value_range` |

Abgedeckt: `type:int`, `type:float`, `type:double`, `no-fill`, `multi-fill`,
`size-zero-allowed`, `size-zero-disallowed`, `value_range`, `explicit_values`,
`K-pattern` — **alle zehn**.

**Ergebnis: 10/10 clean, `fail=0`** (5 Specs × Define + Runtime), keine
Sanitizer-Diagnostik, kein NaN/Inf, Exit 0.

---

## 21. Result-reuse safety

**Audit.** Der Enhanced Runner besitzt zwei Wiederverwendungspfade:

* `gate_cache` — pro Prozess neu aufgebaut, **nicht** persistiert ⇒ kein Risiko.
* **Resume** — baut `done` aus der Recorddatei über `(sample_id, spec_key)` und
  überspringt diese Paare. `spec_key` kodiert weder Policy noch Harness, also
  hätte ein Resume über einen Policywechsel hinweg genau für die
  drifted-but-valid Specs ein veraltetes Ergebnis als aktuell behalten.

**`RESULT_REUSE_STALE_RISK = true`** vor E3 ⇒ E3 hat die geforderte minimale
fail-closed Grenze eingebaut (`run_enhanced_tests.py`): beim Resume wird der in
der Summary hinterlegte `enhanced_policy_provenance.enhanced_policy_sha256`
gegen den aktuellen verglichen; bei Abweichung (oder fehlender Aufzeichnung)
**bricht der Lauf mit Exit 3 ab**, statt alte Records zu behalten — mit dem
Hinweis, `--force` oder eine neue `run_id` zu verwenden. Die Prüfung steht vor
jeder Verwendung der Resume-Menge (Test in `test_e3_cache.py`, Gruppe 5).

**Keine historischen Ergebnisse gelöscht.** E3 hat ausschließlich
`specs.jsonl` ersetzt; `thesis/results/raw/`, `intermediate/` und alle
Pilotergebnisse sind unangetastet. Keine Reuse-Policy für pilot_001/pilot_002
wurde entschieden — hier ging es nur um die technische Cachesicherheit.

---

## 22. No-enhanced regression

**PASS.** Im Container: „no defines: `ENHANCED_FILL` is exactly `fillRand`",
„no defines: zero runtime machinery in the TU", „runtime define dispatches to
the runtime fill", „pattern define path unchanged", „both defines: hard
`#error`" — alle grün.

`NORMAL_CORRECTNESS_INPUT_PATH_CHANGED = **false**`: E3 hat `utilities.hpp`,
`baseline.hpp`, `cpu.cc`, `enhanced-fill.hpp` und `run_correctness.py`
**nicht** angefasst (`git status` bestätigt es).

---

## 23. Compile grouping

**PASS.** Die Gruppierungslogik in `run_enhanced_tests.py` ist unberührt: ein
Compile pro `sample × size`, `ENHANCED_TEST_SIZE` bleibt Compile-Define,
`ENHANCED_RUNTIME_FILL` bleibt enhanced-only, fresh process per spec. Die
einzige Änderung an dieser Datei ist die Resume-Provenance-Grenze aus §21, die
vor der Modellschleife liegt. Die Testgruppe „range conversion: runtime path
bit-equal to define path" ist unverändert grün (9/9).

---

## 24. Cross-Pilot impact

**Nachher: Exit 1, `CROSS_PILOT_REPO_STATE_STALE = true`** — wie vorher, jetzt
zusätzlich über die Spec-Keys. Keine Fingerprints aktualisiert, keine
Neuklassifikation, keine 99/0/99-Materialisierung, Candidate-Subset unverändert.

Neu stale gegenüber dem Stand vor E3:

| Fingerprint | Status |
|---|---|
| `graph/15_graph_edge_count enhanced_spec_keys_sha256` | STALE (`756dbdaf…` → `31f0c85a…`) |
| `reduce/25_reduce_xor enhanced_spec_keys_sha256` | STALE (`4e1af7b7…` → `2a013371…`) |
| `search/35_… enhanced_spec_keys_sha256` | STALE (`04b36d09…` → `c3a1c9f4…`) |

Bereits vorher stale und unverändert: `drivers/cpp/enhanced-fill.hpp`
(semantic), `thesis/enhanced_tests/specs.py` (semantic),
`thesis/evaluation/run_enhanced_tests.py` (coarse).

Pro Kandidat:

| Candidate | old | retained | replacements | final | Keys behalten / neu | Enhanced-Reproduzierbarkeit | normaler Correctnesspfad |
|---|---|---|---|---|---|---|---|
| `graph/15_graph_edge_count` | 10 | **0** | 10 | 10 | 0 / 10 | Spec-Key-Menge **vollständig** neu (alle 10 alten waren `no_pattern_effect`) | unberührt |
| `reduce/25_reduce_xor` | 9 | 7 | 2 | 9 | 7 / 2 | 7 Keys identisch, 0 drifted ⇒ keine Reexecution | unberührt |
| `search/35_search_search_for_last_struct_by_key` | 8 | 6 | 2 | 8 | 6 / 2 | 6 Keys identisch, 0 drifted ⇒ keine Reexecution | unberührt |

Keiner der drei Kandidaten hat einen drifted-retained Spec, ihre Reexecution-Last
ist also 0. Es wurde **keine** Cross-Pilot-Entscheidung getroffen.

---

## 25. Readiness for post-E3 cross-pilot reevaluation

**`ENHANCED_E3_SPEC_CACHE_FROZEN = true`.**

* Policy exact-derived und fail-closed, Textcleanup semantikneutral bewiesen;
* finaler Cache atomar erzeugt, jeder Spec valid, 60 Benchmarks, min 5 Specs;
* keine Duplikate, keine Fake-Diversity;
* alle historisch validen Specs unverändert erhalten, alle invaliden entfernt;
* 10 drifted-valid Specs korrekt als Reexecution markiert und **nicht** neu
  generiert;
* 199/199 Replacements erzeugt, kein Shortfall, kein Generation Failure;
* keine Methodikänderung, Manifest und Report vollständig.

**Verbleibende Blocker vor der Cross-Pilot-Reevaluation:** keine aus dem
Enhanced-Pfad. Offen bleibt die Cross-Pilot-Reevaluation selbst — sie muss die
drei neu stale gewordenen `enhanced_spec_keys`-Fingerprints und die seit E2-A
stale gebliebenen shared-state-Fingerprints bewerten — sowie die eigentliche
Ausführung: die 10 Reexecution-Specs und die 199 Replacements haben unter der
eingefrorenen Policy noch kein Enhanced-Ergebnis. Beides liegt außerhalb von E3.
