# Enhanced E2-A — Implementation Report

Harness correctness, fill-type safety, oracle/size safety and capability-aware
fake-diversity enforcement. E2-A implements only fixes whose correctness does
**not** depend on an open P2 policy; every policy-dependent case is carried as
`deferred_policy`, never silently supported.

## 1. Provenance

| Feld | Wert |
|---|---|
| Repository / Branch | `jerabek-niklas/ParEval-Thesis` / `thesis-static-analysis` |
| Start-HEAD | `801c31f33e956e18d619590cb79d722685fa8601` ("fixes 12") |
| Parent | `591a79092298080131a4d91f71f288628f309c1b` (E1 consistency correction) |
| Working Tree bei Start | clean |
| Compiler | `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0` (Container `pareval-thesis`) |
| MPI | `mpirun (Open MPI) 4.1.6` |
| Python (Host-venv) | 3.14.5; Container-Läufe mit `python3` |
| E1-Consistency-Checker **vor** Änderung | `python thesis/enhanced_tests/check_enhanced_capabilities.py` → **Exit 0**, `ENHANCED_CAPABILITIES_CONSISTENT = true`, 660 Einträge |
| Cross-Pilot **vor** Änderung | `python thesis/evaluation/check_cross_pilot_gate.py` → **Exit 0**, `CROSS_PILOT_REPO_STATE_STALE = false` |

> ## Nachtrag E2-A.1 (2026-08-30) — Geltungsbereich der Sanitizer-Aussage
>
> Dieser Report bleibt unveraendert als Dokument des Standes **fixes 13**
> (`3374aaf7218fbc007e6b75f1c0105b7753d585b0`). Ein anschliessender read-only
> Audit hat eine **Restluecke** gefunden, die E2-A nicht abgedeckt hat und die
> hier deshalb nicht behauptet, aber auch nicht ausgeschlossen wurde:
>
> * **E2-A initial finding:** die DType-Deduktion war der UB-Verursacher; nach
>   dem Typfix waren `extreme_values` und `spike_at` sanitizerfrei.
> * **E2-A.1 correction:** die Aussage „**0 runtime errors** in beiden Pfaden"
>   in §6 und die Zeile „UBSan+ASan Fill-Layer … 0 Fehler" in §14 gelten
>   **ausschliesslich fuer die damals gemessene Probe** — DType-Fix,
>   `extreme_values`/`spike_at`, Call-Site-Ranges. Sie gelten **nicht** fuer
>   beliebige `value_range`-Specs: mit `[INT_MIN, INT_MAX]`, `[-FLT_MAX,
>   FLT_MAX]`, `[-DBL_MAX, DBL_MAX]` oder `[-1e300, 1e300]` konnte der
>   Fill-Layer weiterhin signed overflow, Modulo-/Division-by-zero, eine FPE
>   oder deterministische NaN/Inf erzeugen, und der Define-Pfad konnte ueber
>   `(decltype(lo))(ENHANCED_FILL_LO)` sogar **vor** dem sicheren
>   Endpoint-Helper eine out-of-range Floating->Integral-Konversion ausfuehren.
>
> Diese Luecke wird in **E2-A.1** geschlossen (technische
> Repraesentierbarkeits- und Span-Pruefung in `validate_spec`, defensive
> widened-unsigned Arithmetik plus kontrollierter Abbruch im Header, Entfernung
> des Define-Pre-Casts). Details, Sanitizer-Matrix und die neu berechnete
> Spec-Partition stehen in
> `thesis/evaluation/enhanced_e2a1_implementation_report.md`.
>
> Ebenfalls nur fuer den Stand fixes 13 gueltig: die Zeile
> „Compile-Grouping-Regression | `run_enhanced_tests.py` **unveraendert**".
> E2-A.1 aendert diese Datei — ausschliesslich um den Fail-Closed-Policy-
> Preflight vor jeden persistenten Side Effect zu setzen und die
> Policy-Provenance in Manifest/Summary zu schreiben. Die Compile-Gruppierung
> selbst (ein Compile pro sample x size, Runtime-Fill) ist unberuehrt.

## 2. Scope

Implementiert: (1) Fill-Type-Sicherheit, (2) Oracle-/Harness-Sicherheit über
Capability-Ausschluss, (3) benchmark-spezifische Size-Constraints, (4)
Fake-Diversity-Enforcement, (5) capability-aware Validation/Generation/Mutation,
(6) Tests + Drift-/Provenance-Analyse. **Nicht** entschieden:
`EXTREME_PATTERN_SEMANTICS`, `VALUE_RANGE_DOMAIN_POLICY`,
`SIZE_ZERO_SPEC_POLICY`, Tolerance-Policy, Graph-/Sparse-/sort44-Adapter,
Large-Size-Policy. Keine Spec-Regeneration, kein `spec_key`-Wandel, kein
pilot_002.

## 3. Rekonstruierte P0/P1-Fixliste (aus dem aktuellen Katalog, nicht aus Prosa)

* **P0 Fill-Type:** 8 definitive Fälle auf 4 Benchmarks — `reduce/28`,
  `scan/31`, `sort/42`, `sort/43`, je `extreme_values` + `spike_at`.
* **P0 Oracle:** 10 definitive Fälle auf 6 Benchmarks — `histogram/20`,
  `histogram/21`, `histogram/24` (je extreme+spike), `scan/34` (extreme),
  `stencil/54` (extreme), `transform/58` (extreme+spike).
* **P0 Size:** `fft/05` (heap-OOB bei non-power-of-two), `fft/07/08/09`
  (Floor-Halving-Oracle ⇒ falsche Referenz; frozen Prompt: power-of-two),
  `graph/19` (N=0/1 UB), `dense_la/01` (N=0 UB), `search/36/37/39` (N=0 UB).
* **P1 Fake Diversity:** 11 Benchmarks mit `pattern_effect` NONE/NOT_APPLICABLE.

## 4. DType-Blast-Radius (vor dem Fix bestimmt, alle 70 Sites)

| Kennzahl | Wert |
|---|---:|
| Fill-Sites gesamt | **70** |
| `SITES_WITH_UNCHANGED_DTYPE` | **66** |
| `SITES_WITH_CHANGED_DTYPE` | **4** |

| Benchmark | Site | old_dtype | global_new_dtype | hypothetical_local_fix_dtype |
|---|---|---|---|---|
| reduce/28 | cpu.cc:63 (`vector<int>`, `0.0, 100.0`) | double | **int** | **int** (`0, 100`) |
| scan/31 | cpu.cc:59 (`vector<float>`, `-100.0, 100.0`) | double | **float** | **float** (`-100.0f, 100.0f`) |
| sort/42 | cpu.cc:127 (`vector<float>`, `-100.0, 100.0`) | double | **float** | **float** (`-100.0f, 100.0f`) |
| sort/43 | cpu.cc:156 (`vector<float>`, `-1.0, 1.0`) | double | **float** | **float** (`-1.0f, 1.0f`) |

Die sieben im E1-Katalog als `conditional` geführten Sites wurden geprüft:
`transform/56` (:54), `transform/58` (:55), `transform/59` (:59) haben
**keinen** Literaltyp-Mismatch (int-Container mit int-Literalen) — ihre
Konditionalität stammt ausschließlich aus `explicit_values` und den konkreten
Spec-Werten. *Conditional site ≠ DType-Problem* ist damit bestätigt.

## 5. Global vs. Local — datenbasierte Entscheidung

`GLOBAL_FIX_CHANGED_SITE_SET == LOCAL_FIX_REQUIRED_SITE_SET` = **true**
(beide = {reduce/28, scan/31, sort/42, sort/43}), und an **jeder** dieser Sites
gilt `global_new_dtype == hypothetical_local_fix_dtype`. Nach der Entscheidungs­regel
ist damit der **globale Fix** vorzuziehen: ein zentraler Typgrundsatz statt vier
divergierender Call-Site-Literalkonventionen. Empirisch bestätigt: die 66
unveränderten Sites liefern **bit-identische** Container (siehe §7).

## 6. Fill-Type-Fix (P0)

`drivers/cpp/enhanced-fill.hpp`: der Pattern-Wertetyp ist jetzt der
**Container-Elementtyp** (`typename T::value_type`), nicht mehr der Typ der
lo/hi-Literale. Neue Bausteine:

* `enhancedRangeEndpoint<VType>(src)` — konvertiert Range-Endpunkte
  (Call-Site-Literal **oder** Spec-`value_range`) in den Elementtyp mit der
  bereits dokumentierten *truncate-then-saturate*-Semantik; auch für
  Floating-Ziele (double→float out-of-range ist ebenfalls UB).
* `enhancedFillPatternTyped(...)` — **gemeinsamer Kern**; Define- und
  Runtime-Pfad rufen ausschließlich ihn mit bereits konvertierten Endpunkten
  auf, wodurch Pfaddivergenz strukturell ausgeschlossen ist.
* `enhancedFillRandom(...)` — dispatcht komplexe Container auf die
  Double-Endpunkte (`fillRand`s complex-Branch ist mit komplexen Endpunkten
  nicht instanziierbar — eine vorbestehende Latenz); `fillRand` selbst bleibt
  unangetastet, weil es die normalen Correctness-Läufe bedient.
* UB-Guard: eine degenerierte ganzzahlige Spanne (`lo == hi`, erreichbar über
  `value_range [c,c]`) würde in `fillRand`s `rand() % (max-min)` eine
  Modulo-Null-Division auslösen; sie wird direkt mit `lo` gefüllt. Das ist ein
  UB-Guard, **keine** Range-Policy (nichts wird geklippt oder umgedeutet).

**Option A bleibt Option A:** `extreme_values` erzeugt weiterhin
Elementtyp-Extrema (für `reduce/28` nun INT_MIN/INT_MAX statt ±DBL_MAX). Es
wurde **nicht** auf lo/hi-/Domain-Extrema umdefiniert.

**Sanitizer-Nachweis.** Alt (`-fsanitize=float-cast-overflow,undefined`):
`enhanced-fill.hpp:200: runtime error: -1.79769e+308 is outside the range of
representable values of type 'int'` und `:212: ... 8.98847e+307 ...`. Neu:
**0 runtime errors** in beiden Pfaden.
*(E2-A.1-Korrektur: diese Aussage gilt fuer den gemessenen Probenumfang —
DType-Fix, `extreme_values`/`spike_at`, Call-Site-Ranges. Sie ist **keine**
Aussage ueber beliebige `value_range`-Specs; siehe Nachtrag oben und den
E2-A.1-Report.)*

## 7. Input-Drift-Audit (gemessene Container-Werte, nicht Specs)

Deterministische Probe (`srand(1)`, n=6, k=2), alte vs. neue Fill-Konstruktion,
je Pattern und Shape; die beiden Extremmuster wurden am alten Pfad **nicht**
ausgeführt (dort UB) und sind statisch als Drift klassifiziert.

| Shape | INPUT_DRIFT = true | INPUT_DRIFT = false |
|---|---|---|
| reduce/28 (`int` ← double) | random, ascending, descending, duplicate_at, sorted_except_one, *extreme_values*, *spike_at* | all_zeros, all_same, alternating, explicit_values |
| scan/31, sort/42, sort/43 (`float` ← double) | ascending, descending, sorted_except_one, *extreme_values*, *spike_at* | random, all_zeros, all_same, alternating, duplicate_at, explicit_values |
| **alle 66 unveränderten Sites** | – | **alle Patterns, bit-identisch** |

`INPUT_DRIFT_FROM_DTYPE_FIX = false` für alle Sites mit
`old_dtype == new_dtype`; keine andere E2-A-Änderung berührt den Inputpfad
(`fillRand`, Benchmark-Code und der No-Enhanced-Zweig sind unverändert).
Driftursachen: Wechsel des Rechentyps (Integral- statt Floating-Branch von
`fillRand`, inkl. `hi`-Exklusivität), integraler Modulo-Ramp statt
truncated-double-Ramp, float- statt double-Ramp-Arithmetik, und die
notwendigerweise anderen Extremwerte. **UNKNOWN wurde nicht benötigt** — jede
Zelle ist entweder gemessen oder (bei altem UB) statisch begründet.

**Runtime/Define-Parität:** 240 Vergleiche (10 Patterns × 24 Shapes),
**0 Abweichungen → PASS**; zusätzlich bestätigt der bestehende Testgroup
„range conversion: runtime path bit-equal to define path".

## 8. Oracle-Safety (P0) — Lösungsweg je Fall

Alle 10 definitiven Fälle sind **Strategie A** (Pattern liegt eindeutig
außerhalb der frozen Benchmarkdomain und ist kein legitimer regulärer
Modelltest) und werden capabilityseitig ausgeschlossen — **kein**
Comparator-Eingriff, **keine** neue Domain, **keine** Oracle-Änderung:

| Benchmark | Pattern | Root Cause | Lösung |
|---|---|---|---|
| histogram/20 | extreme_values, spike_at | Oracle indiziert `bins[x[i]]` ⇒ heap-OOB außerhalb [0,255] | unsupported |
| histogram/21 | extreme_values, spike_at | out-of-range Konversion im Oracle außerhalb [0,100] | unsupported |
| histogram/24 | extreme_values, spike_at | out-of-range Konversion außerhalb [0,2³¹) | unsupported |
| scan/34 | extreme_values | `currSum += x[j]` signed-overflow im Oracle | unsupported |
| stencil/54 | extreme_values | rohe 8-Nachbar-int-Summe ⇒ signed-overflow (Domain {0,1}) | unsupported |
| transform/58 | extreme_values, spike_at | `x*x` signed-overflow (sicher nur \|x\|≤46340) | unsupported |

Für **keinen** dieser Fälle wäre eine offene P2-Policy nötig: die frozen Domain
ist jeweils dokumentiert und der Input liegt eindeutig außerhalb.
Testnachweis: alle 10 sind über **alle drei Pfade** (Validation, Generator,
Mutation) unerreichbar — 0 Leaks.

## 9. Size-Safety (P0), benchmark-spezifisch

`SIZE_ZERO_SPEC_POLICY` bleibt **offen**: es gibt keine globale
`min_size=1`-Regel, und jeder Benchmark ohne Eintrag akzeptiert weiterhin
Größe 0 (durch Test abgesichert).

| Benchmark | Constraint | Hazard |
|---|---|---|
| dense_la/01 | `min_size 1` | `i < N-1` size_t-Underflow, OOB-Read |
| graph/19 | `min_size 2` | N=0 Underflow; N=1 Modulo-0 + nichtterminierende Ziehung |
| search/36, /37, /39 | `min_size 1` | `rand() % size` Modulo-0 + OOB |
| fft/05, /07, /08, /09 | `size ≤ 1 oder Zweierpotenz` | 05: heap-OOB; 07/08/09: Floor-Halving ⇒ falsche Referenz (frozen Prompt fordert Zweierpotenz) |

Der statische Base-Set filtert unsichere Größen jetzt pro Benchmark heraus.

## 10. Capability-Architektur — eine Quelle, drei Konsumenten

```
enhanced_capabilities.json  (AUDIT_ONLY_NOT_ENFORCED)
        │  derive_enhanced_policy.py   (R1, R2, R3, R4, R4b, R5)
        ▼
enhanced_policy.json        (ENFORCED)
        ▲
        │  capabilities.py   effective_patterns / pattern_rejection /
        │                    size_rejection / explicit_values_rejection
   ┌────┴───────────────┬──────────────────────┐
validate_spec      generate_test_specs     _mutants_of
 (specs.py)                                 (specs.py)
```

Audit-Metadaten und enforced Policy bleiben getrennt; es existiert **keine**
zweite Capabilitytabelle (Test „one capability source, three consumers").
Ableitungsregeln: **R1** kein Pattern-Effekt → nur `random`; **R2**
`oracle_execution_safe=false` → unsupported; **R3** auditierte Fill-UB → nach
dem Typfix `deferred` (`extreme_semantics_deferred`); **R4**
`FALSE_FAIL_RISK` → `deferred`; **R4b** `explicit_values` außerhalb der
Repräsentierbarkeit des Containers → **rejected, nicht geklippt**; **R5**
benchmark-spezifische Size-Constraints. `derive_enhanced_policy.py --check`
verifiziert die Ableitung reproduzierbar.

**Policy-Bilanz:** 60 Benchmarks · **499 supported**, **139 unsupported**
(110 `no_pattern_effect`, 19 `no_single_canonical_fill_site`, 10
`unsafe_pattern_for_benchmark`), **22 deferred** (14
`false_fail_risk_deferred`, 8 `extreme_semantics_deferred`), 9 Benchmarks mit
Size-Constraint, 18 mit Repräsentierbarkeitsgrenzen.

## 11. Fake-Diversity-Enforcement (P1)

Die 11 Benchmarks ohne Pattern-Effekt (`dense_la/01`, `graph/15–19`,
`histogram/23`, `reduce/25`, `sort/44`, `sparse_la/45`, `sparse_la/49`)
unterstützen produktiv nur noch das kanonische Label `random`; 110
Patternfälle sind als `no_pattern_effect` ausgeschlossen. **Sizevariation
bleibt vollständig erhalten** (Test: „size variation still happens there").

* **histogram/23** (Stringinput): keine erfundene numerische Patternsemantik;
  Prompt sagt ausdrücklich „Pattern variation is NOT available here".
* **Graph / Sparse / sort/44**: keine Adapter erfunden — Patternvariation
  bleibt schlicht nicht verfügbar (P3/E2-B).
* **PARTIAL** (`dense_la/02`, `dense_la/04`, `sparse_la/46`): **nicht** pauschal
  deaktiviert; die wirksamen Patterns bleiben unterstützt, die unvollständige
  Abdeckung ist als `pattern_coverage: partial` dokumentiert statt behauptet.
* **Keine Fake-Padding:** die Zielanzahl (20) wird nicht mit
  Duplikat-Patternlabels aufgefüllt; `capability_limited_spec_count` ist die
  ehrliche Folge (z.B. graph/15: nur noch size-variierte Specs, alle mit
  unterschiedlicher Größe, keine Duplikate).

## 12. Bestandsspecs — getrennte Mengen (keine Regeneration durchgeführt)

`thesis/enhanced_tests/classify_specs_e2a.py` (read-only):

| Menge | Anzahl |
|---|---:|
| `TOTAL_EXISTING_SPECS` | **483** |
| `INVALID_BY_POLICY_ONLY` | **65** |
| `INPUT_DRIFTED_BUT_STILL_VALID` | **7** |
| `INVALID_AND_DRIFTED` | **4** |
| `UNCHANGED_AND_VALID` | **407** |

65+7+4+407 = 483 ✓ (überschneidungsfrei, per Assertion geprüft).
Ablehnungsgründe: `no_pattern_effect` 49, `invalid_size_for_benchmark` 12,
`deferred_policy_pattern` 6, `unsafe_pattern_for_benchmark` 1,
`value_not_representable_for_benchmark` 1.
Drift-Benchmarks: `reduce/28`, `scan/31`, `sort/42`, `sort/43`.

**`ENHANCED_SPECS_REGENERATION_REQUIRED = true`** (für die 69
invalid-by-policy Specs) und **`ENHANCED_SPECS_REEXECUTION_REQUIRED = true`**
(für die 11 input-drifted Specs) sind **getrennt** bestimmt. Drifted-but-valid
Specs werden **nicht** regeneriert: gleicher `spec_key`, gleiche Parameter —
sie müssen unter dem korrigierten Harness lediglich **neu ausgeführt** werden.
Der Drift wird **nicht** über einen neuen `spec_key` kaschiert; die
Unterscheidung historisch/neu erfolgt über Harness-/Code-Provenance.

**`HISTORICAL_ENHANCED_INPUT_REPRODUCIBLE_UNDER_E2A = false`** für
`reduce/28`, `scan/31`, `sort/42`, `sort/43`. Historische Enhanced-Ergebnisse
dieser Specs dürfen nicht als input-identische Wiederholung des neuen
Harnesszustands gelten.

## 13. Verdict-Outcome-Bilanz (aktiv nach Enforcement)

| Klasse | vorher (660) | aktiv danach (499) |
|---|---:|---:|
| INFORMATIVE | 330 | 250 |
| REDUCED | 171 | **150** (`REDUCED_REMAINING_FOR_E2_B`) |
| VACUOUS_PASS | 0 | **0** (Regression gehalten) |
| NO_VERDICT_BI | 40 | **29** (semantisch offene adversariale Fälle, E2-B) |
| FALSE_FAIL_RISK | 14 | **0** (alle 14 deferred) |
| UNKNOWN | 105 | 70 |

`FALSE_FAIL_RISK` ist damit vollständig aus dem aktiven Bestand entfernt —
**nicht** durch eine Toleranzänderung, sondern durch Deferral (Kategorie B/C
der Kontraktlogik: das Risiko besteht auch bei regulären Inputs bzw. ist
k-/range-abhängig, die Auflösung braucht die Tolerance-/Domain-Policy).
`parallel_bias_risk`: 17 auditierte Fälle, davon **11 weiterhin aktiv**
(fft-Spike 5×, reduce 4×, scan 2× — nach Abzug der deferred) — als gerichtetes
Risiko gegen omp/mpi-Kandidaten für E2-B hervorgehoben.

## 14. Tests und Nachweise

| Prüfung | Ergebnis |
|---|---|
| `check_enhanced_capabilities.py` (inkl. neuer P1–P6-Policy-Checks) | **Exit 0** |
| `test_enhanced.py` (Bestand, 11 Gruppen) | **Exit 0** |
| `test_capabilities.py` (neu, 7 Gruppen) | **Exit 0** |
| `derive_enhanced_policy.py --check` | **Exit 0** |
| `derive_shapes.py --check` | shapes match |
| `test_comparator_semantics.py` | passed |
| `test_cleaning.py` | 13/13 |
| DType-Blast-Radius-Probe (24 Shapes × 10 Patterns, alt vs. neu) | 20/20 unveränderte Shapes **bit-identisch** |
| Define/Runtime-Parität | 240 Vergleiche, 0 Abweichungen |
| UBSan+ASan Fill-Layer (`extreme_values`, `spike_at`, beide Pfade) | 0 Fehler (alt: 2 dokumentierte `runtime error`) — **Geltungsbereich: genau diese Probe**, nicht beliebige `value_range` (E2-A.1-Nachtrag) |
| UBSan+ASan+float-cast-overflow, **echte Driver** (reduce/28, scan/31, sort/42, alle aktiven Patterns) | 21/21 clean |
| P0-Unerreichbarkeit über Validation/Generator/Mutation (10 oracle + 8 fill) | 0 Leaks |
| Spec-Partition-Konsistenz | 65+7+4+407 = 483 ✓ |
| No-Enhanced-Regression | Testgroup „no defines: ENHANCED_FILL is exactly fillRand" grün; plain-Pfad-Probe unverändert |
| Compile-Grouping-Regression | `run_enhanced_tests.py` **unverändert** (git diff = 0) ⇒ ein Compile pro sample×size, Runtime-Fill-Parität erhalten — *E2-A.1 ändert die Datei für den Policy-Preflight/die Provenance, die Gruppierung selbst bleibt* |

## 15. Cross-Pilot-Staleness und Impact (keine Neuklassifikation)

Cross-Pilot **nach** E2-A: **Exit 1**, `CROSS_PILOT_REPO_STATE_STALE = true`.
Das ist der erwartete Zustand, **kein Fehler**. Es wurden **keine**
Fingerprints aktualisiert, `cross_pilot_comparability.json` **nicht** angefasst,
99/0/99 und das Candidate-Subset **nicht** verändert.

**`CROSS_PILOT_REEVALUATION_REQUIRED = true`.**
Geänderte fingerprinted Shared-Files: `drivers/cpp/enhanced-fill.hpp`
(semantic), `thesis/enhanced_tests/specs.py` (semantic). Benchmarklokale
Dateien (`cpu.cc`, `baseline.hpp`): **keine**. Prompts: **keine**.

| Candidate | direkt geändert | shared betroffen | Enhanced-only? | normale Correctness betroffen? | Input-Drift |
|---|---|---|---|---|---|
| graph/15_graph_edge_count | nein | ja (2 Dateien) | **ja** | nein | nein (0 Fill-Sites) |
| reduce/25_reduce_xor | nein | ja (2 Dateien) | **ja** | nein | nein (0 Fill-Sites) |
| search/35_search_search_for_last_struct_by_key | nein | ja (2 Dateien) | **ja** | nein | nein (int-Site, DType unverändert) |

Begründung „Enhanced-only": ohne die `ENHANCED_*`-Defines expandiert
`ENHANCED_FILL` weiterhin **exakt** zu `fillRand` (Testgroup + Probe), und
`specs.py` wird vom Correctness-Pfad nicht benutzt. Die 396
Correctness-Records sind daher nicht betroffen.

**Historical Enhanced Reproducibility ≠ Correctness Cross-Pilot Comparability:**
strikt getrennt behandelt. Der Enhanced-Inputdrift betrifft 4 Benchmarks (keiner
davon im Candidate-Subset) und sagt **nichts** über die Gültigkeit der
99/0/99-Klassifikation aus; deren Neubewertung ist ein separater Schritt.

## 16. Offene E2-B-Policies (unverändert offen)

`EXTREME_PATTERN_SEMANTICS`, `VALUE_RANGE_DOMAIN_POLICY`,
`SIZE_ZERO_SPEC_POLICY`, Tolerance-Policy, Graph-Adapter-Vokabular,
Sparse-Adapter-Policy, sort/44-Adapter-Policy, Large-Size-Policy. Zusätzlich
für E2-B: die 22 deferred Patternfälle, 150 REDUCED, 29 NO_VERDICT_BI, 11
aktive `parallel_bias_risk`-Fälle.

## 17. E3-Readiness

E3 (Spec-Regeneration) kann starten, sobald die E2-B-Policies entschieden sind:
69 Specs sind invalid-by-policy (ersetzen), 11 sind input-drifted
(**behalten**, `spec_key` behalten, nur neu ausführen), 407 unverändert gültig.
In E2-A wurde **keine** Spec verändert oder regeneriert.
