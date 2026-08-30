# Enhanced E2-B — Policy Freeze Report

Freeze Input-Domain, Extreme-Pattern, Tolerance & Adapter Policies Before E3

---

## 1. Provenance

| | |
|---|---|
| Repository | `jerabek-niklas/ParEval-Thesis` |
| Branch | `thesis-static-analysis` |
| Start-HEAD | `ab202b2b0ff8d6dd502fee00aba81a93e111c64e` („fixes", 2026-08-30 15:17) — **verifiziert**, nicht übernommen |
| Parent | `3374aaf7218fbc007e6b75f1c0105b7753d585b0` („fixes 13") |
| Working Tree bei Start | **clean** (`git status --porcelain --untracked-files=all` leer) |
| End-HEAD | unverändert `ab202b2…` — **kein Commit erstellt** |

**Vorher-Gates** (Repo-venv `.venv\Scripts\python.exe`):

| Kommando | Exit |
|---|---|
| `check_enhanced_capabilities.py` | **0** |
| `derive_enhanced_policy.py --check` | **0** |
| `test_capabilities.py` | **0** |
| `test_e2a1_safety.py` | **0** |
| `check_cross_pilot_gate.py` | **1 — STALE** (erwartet, seit E2-A) |

---

## 2. Policy Decision Table

Erstellt **vor** jeder produktiven Codeänderung, gegen den aktuellen Sourcezustand
verifiziert.

| # | Policy | Evidence | Decision | Productive impact |
|---|---|---|---|---|
| 1 | **EXTREME_PATTERN_SEMANTICS** | Alle 70 Fill-Sites haben **numerische Literale** als `ENHANCED_FILL(x, lo, hi)`-Endpunkte (Katalog `fill_sites[].lo_expr/hi_expr`); die Domains sind eng ([-1,1], [0,100], [0,255], [0,2], …). `numeric_limits`-Extrema liegen bei jedem einzelnen Site weit außerhalb. | **`DECLARED_FILL_DOMAIN_EXTREMA`** | `enhancedExtremeValue` alterniert zwischen den **effektiven** Endpunkten (Call-Site oder validierter Spec-Range) statt `numeric_limits::lowest()/max()`. Erzeugt Inputdrift für bestehende `extreme_values`-Specs. |
| 1b | **EXTREME_VALUES als Label** | Unter (1) ist `extreme_values` konstruktionsgleich zu `alternating` (`case 5: x[i] = (i%2==0) ? lo : hi`) — **byteidentischer Input**. | **`extreme_values` = unsupported (`duplicate_of_alternating_under_domain_extrema`)** auf allen 60 Benchmarks | Die in E2-A eingefrorene Fake-Diversity-Regel verbietet zwei Labels für denselben Input. `alternating` bleibt (sein Name beschreibt die Konstruktion korrekt); der Harness implementiert die neue Extremsemantik weiterhin, damit Define/Runtime-Parität und historische Reproduzierbarkeit prüfbar bleiben. |
| 2 | **SPIKE_AT_SEMANTICS** | `enhancedSpikeValue` lieferte `numeric_limits<T>::max()/2` — bei Domain [0,2] also 1073741823, bei [-1,1] 8.99e307. Der integrale `fillRand`-Zweig ist **hi-exklusiv** (`rand() % (hi-lo) + lo`), der Spike-Wert `hi` liegt also beweisbar außerhalb des Randombildes. | **`DECLARED_DOMAIN_UPPER_EXTREME`** (Spike = effektives `hi`) | Spike innerhalb der Domain, deterministisch vom Randombild unterscheidbar. Zusatzregel: bei **degenerierter** effektiver Range (`lo == hi`) erzeugt jedes range-lesende Pattern dasselbe konstante Array und die Perturbation ist beweisbar ein No-op → nur `all_same` darf eine degenerierte Range tragen (§6). |
| 3 | **VALUE_RANGE_DOMAIN_POLICY** | 48 der 49 Fill-Hook-Benchmarks haben **eine identische** deklarierte Domain über alle ihre Sites; nur `sort/43` hat drei semantisch verschiedene ([0,100] `startTime`, [1,10] `duration`, [-1,1] `value`). 28 der 111 Bestandsranges liegen außerhalb der deklarierten Domain. | **`SUBSET_OF_DECLARED_BENCHMARK_FILL_DOMAIN`** | `validate_spec` fordert zusätzlich zur E2-A.1-Technikprüfung `domain_lo <= a <= b <= domain_hi`. `sort/43`: `global_value_range_supported = false`. Kein Clipping, kein Wrap — **reject**. Gilt auch für `explicit_values`. |
| 4 | **SIZE_ZERO_SPEC_POLICY** | Pro Benchmark aus Prompt + `baseline.hpp` + `cpu.cc validate()` bestimmt (§8). Belegte Gegenbeispiele: `reduce/27` liefert 0.0/0 = NaN → BI; `scan/34` leakt seinen Initialisierer `INT_MIN`; `geometry/12/13/14` haben einen im Prompt **nicht** genannten Early-Return `return 0`; `fft/05/07/08/09` fordern im Prompt „size … is always a power of two" (0 ist keine); `sort/41`/`search/35` fangen size 0 mit einem BI-Guard ab. | **`BENCHMARK_SEMANTICS_DEPENDENT`** | 44 ALLOWED / 11 DISALLOWED / 5 NOT_APPLICABLE. Keine globale Regel; DISALLOWED wird als benchmark-lokales `min_size >= 1` materialisiert. |
| 5 | **TOLERANCE_POLICY** | Alle 14 `FALSE_FAIL_RISK`- und die 10 `unsafe_pattern`-Fälle wurden durch `numeric_limits`-Extrema, out-of-domain Spikes oder absurd große Ranges ausgelöst (Katalog `oracle_hazards`). Unter (1)–(3) sind sie unerreichbar. | **`KEEP_FROZEN_COMPARATOR_AND_CONSTRAIN_ENHANCED_INPUTS`** | **Kein** Comparator, **kein** Epsilon, **keine** `baseline.hpp` geändert. `ACTIVE_FALSE_FAIL_RISK = 0` durch Inputbeschränkung. |
| 6 | **GRAPH_ADAPTER_VOCABULARY** | `graph/15`–`19` haben **0** `ENHANCED_FILL`-Hooks; die Adjazenzmatrizen entstehen in `fillRandDirectedGraph`/`fillRandUndirectedGraph` im frozen `cpu.cc`. | **`NO_NEW_ADAPTER_FOR_PILOT_002`** | Keine Zeile Adaptercode. `pattern_variation = unavailable` wird **explizit** als Entscheidung protokolliert, nicht implizit über `PATTERN_EFFECT=NONE`. Sizevariation bleibt (soweit die Sizepolicy sie erlaubt). |
| 7 | **SPARSE_ADAPTER_POLICY** | `sparse_la/45`, `sparse_la/49` haben 0 Fill-Hooks (Struktur aus `buildDominantSystem`/`buildLuGroundTruth`). | **`NO_NEW_ADAPTER_FOR_PILOT_002`** | wie (6). |
| 8 | **SORT44_ADAPTER_POLICY** | `sort/44` hat 0 Fill-Hooks (`fillRandWithZeroes` im frozen `cpu.cc`). | **`NO_NEW_ADAPTER_FOR_PILOT_002`** | wie (6). Ehrliche Capability-Limitierung statt erfundener „zero structure"-Diversität. |
| 9 | **LARGE_SIZE_POLICY** | `max_spec_size = 4096` in `specs.py::DEFAULT_SETTINGS`; benchmark-spezifische engere Grenzen existieren bereits (fft-Predicate, min_size). | **`KEEP_MAX_SPEC_SIZE_4096_FOR_PILOT_002`** | Configwert **unverändert**. Keine >4096-Expansion. |

**Konfliktprüfung.** Keine der neun Entscheidungen widerspricht frozen Prompt,
`baseline.hpp` oder Oracle. Der einzige Konflikt, den die Verifikation ergab, ist
(1b) — die Kollision von `extreme_values` mit `alternating` — und er wird nicht
durch eine erfundene dritte Semantik gelöst, sondern durch Anwendung der bereits
eingefrorenen Fake-Diversity-Regel. Eine benchmark-lokale Abweichung
(`stencil/54`, §7) wurde ebenfalls durch die vorhandenen Regeln aufgelöst, nicht
durch neue Semantik.

---

## 3. Methodological objective

Enhanced Tests sollen das Verhalten der generierten **Modelle** auf
ungewöhnlichen, randnahen, strukturierten, aber **semantisch legitimen**
Benchmarkinputs untersuchen — nicht, ob der Harness C++-`numeric_limits`
überlebt, ob der Oracle bei absurden Größenordnungen NaN/Inf produziert oder ob
ein absoluter Epsilonvergleich bei 1e307 versagt.

Der Auditbefund dazu ist eindeutig: **alle 70 Fill-Sites** deklarieren an ihrem
Call-Site einen **numerischen Literalbereich** — `[-1,1]` (23×), `[-1000,1000]`
(9×), `[-100,100]` (8×), `[0,100]`, `[0,255]`, `[0,2]`, `[1,10]`, … Gegen jede
dieser Domains liegen `±DBL_MAX`, `INT_MIN/INT_MAX` und `max()/2` um 300
Größenordnungen daneben. Das bisherige `extreme_values`/`spike_at` maß daher
überwiegend Oracle-Overflow und Comparator-Bruch, nicht Modellverhalten.

---

## 4. Declared fill-domain audit

Alle **70** Fill-Sites wurden neu inventarisiert und pro Site normalisiert
(`fill_sites[].declared_fill_domain`: `lo`, `hi`, `call_site_lo`,
`call_site_hi`, `semantic_role`, `overrideable_by_spec`, `reason`, `evidence`).
Quelle ist **ausschließlich** Benchmark-/Prompt-/Oracle-Semantik, nie ein
beobachteter historischer Spec.

**Regel.** Die deklarierte Domain ist der **Call-Site-Literalbereich** — der
Benchmark deklariert dort selbst, mit welchen Werten er gefüllt werden will.
Verengt wird **nur**, wo der frozen Prompt einen engeren Zustandsraum nennt.

Das ist **genau ein** Site in der ganzen Suite:

| Benchmark | Call-Site | Declared | Evidence |
|---|---|---|---|
| `stencil/54_stencil_game_of_life` (cpu.cc:75) | `[0, 2]` | **`[0, 1]`** | Prompt: „A cell is 1 if it is alive and 0 if it is dead"; „Cells outside the grid are dead: they contribute 0". Der Oracle summiert die **rohen** Nachbarwerte, eine 2 ist kein definierter Zellzustand. |

**Ergebnis pro Benchmark.**

* **49** Benchmarks haben einen Fill-Hook, **11** keinen.
* **48** der 49 deklarieren über **alle** ihre Sites **dieselbe** Domain →
  `global_value_range_supported = true`.
* **1** Benchmark hat unvereinbare Site-Domains und bekommt **keine** globale
  Range:

| Benchmark | Sites | Domains |
|---|---|---|
| `sort/43_sort_sort_an_array_of_structs_by_key` | `startTime` (int), `duration` (int), `value` (float) | `[0,100]`, `[1,10]`, `[-1,1]` |

Eine gemeinsame Domain wurde **nicht erfunden**; `value_range` ist dort
schlicht nicht unterstützt. Pattern- und Sizevariation bleiben.

19 Benchmarks sind Multi-Site; 18 davon haben identische Site-Domains.
Strukturelle/Index-Arrays sind unverändert **nicht** ENHANCED_FILL-gesteuert und
wurden nicht reaktiviert.

---

## 5. Extreme semantics

**Vorher:** `enhancedExtremeValue<DType>(i)` → `numeric_limits<DType>::lowest()`
bzw. `::max()`, alternierend.
**Nachher:** `enhancedExtremeValue<DType>(lo, hi, i)` → **die effektiven
Domain-Endpunkte**, alternierend — pro Fill-Site, also bei `sort/43` je Site die
eigenen. Mit gültiger Spec-`value_range` sind es deren Endpunkte, sonst die des
Call-Sites.

Gemessen (GCC 13.3, Define- und Runtime-Pfad, §14):

| Typ | Call-Site | `extreme_values` alt | `extreme_values` neu |
|---|---|---|---|
| `int` | `[0,100]` | `INT_MIN, INT_MAX, …` | `0, 100, 0, 100, …` |
| `int` | Spec `[10,20]` | `INT_MIN, INT_MAX, …` | `10, 20, 10, 20, …` |
| `float` | `[-100,100]` | `±FLT_MAX` | `-100, 100, …` |
| `double` | `[-10,10]` | `±DBL_MAX` | `-10, 10, …` |

### 5b. Der Konflikt: `extreme_values` ist danach `alternating`

`alternating` ist in `enhanced-fill.hpp` als `case 5: x[i] = (i % 2 == 0) ? lo :
hi` implementiert — also **genau** die neue Extremsemantik. Die Probe bestätigt
das: **12 von 12** Vergleichen byteidentisch.

Zwei Labels für denselben Input ist exakt der Fake-Diversity-Defekt, den E2-A
eingefroren hat. Es wurde **keine dritte Semantik erfunden**; stattdessen
greift die bestehende Regel:

**`extreme_values` = unsupported auf allen 60 Benchmarks**, Reason
`duplicate_of_alternating_under_domain_extrema`. `alternating` bleibt — sein Name
beschreibt die Konstruktion korrekt, „extreme" wäre nach der Domainbindung
irreführend.

Der Harness **implementiert** die neue Semantik weiterhin, damit Define/Runtime-
Parität und der Input eines bereits aufgezeichneten historischen
`extreme_values`-Specs nachweisbar bleiben.

---

## 6. Spike semantics

**Vorher:** `numeric_limits<T>::max()/2` (bei Domain `[0,2]` also 1073741823,
bei `[-1,1]` 8.99e307).
**Nachher:** `enhancedSpikeValue<DType>(hi)` → **das effektive `hi`**.

Der geforderte Nachweis, dass der Spike einen **deterministischen strukturellen
Unterschied** zur gleichen Randombasis erzeugt, ist quellenseitig **stärker als
statistisch**: `fillRand`s Integralzweig rechnet `rand() % (hi - lo) + lo`, ist
also **hi-exklusiv** — `hi` liegt beweisbar außerhalb des Randombildes. Gemessen:

```
int, call site [0,100]   base = 83,86,77,15,93,35     spike(k=2) = 83,86,100,15,93,35
int, spec [10,20]        base = 13,16,17,15,13,15     spike(k=2) = 13,16, 20,15,13,15
```

Für Floating-Sites ist `hi` nur bei `rand() == RAND_MAX` erreichbar.

**Degenerierte Range.** Bei `lo == hi` ist die Perturbation beweisbar ein
No-op — und tatsächlich erzeugen **alle** range-lesenden Patterns dann dasselbe
konstante Array. Daraus folgt direkt die Zusatzregel: eine degenerierte
`value_range` ist **nur für `all_same`** zulässig (Reason
`degenerate_range_not_canonical`), dem einzigen Label, das diesen Input ehrlich
beschreibt. Von den 38 degenerierten Bestandsranges ist **jede einzelne** bereits
`all_same` — die Regel invalidiert **0** Bestandsspecs und ist reine Prävention.
Der technische `[c,c]`-Guard aus E2-A.1 bleibt unverändert und weiter grün.

---

## 7. Value-range policy

Zusätzlich zur technischen E2-A.1-Prüfung (`fill_type_capability`) gilt jetzt
die Domainprüfung (`fill_domain_capability`). **Beide** müssen erfüllt sein.

| Prüfung | Reason |
|---|---|
| Benchmark hat keine eindeutige globale Domain | `value_range_not_supported_for_benchmark` |
| `[a,b] ⊄ [domain_lo, domain_hi]` | `value_range_outside_declared_domain` |
| `lo == hi` bei einem anderen Pattern als `all_same` | `degenerate_range_not_canonical` |
| expliziter Wert außerhalb der Domain | `explicit_value_outside_declared_domain` |

`explicit_values` sind **direkte** Inputs und damit genauso domaingebunden wie
ein Range-Endpunkt; sie ohne Domainprüfung zu lassen hätte genau die
out-of-domain Inputs offengelassen, die diese Wave entfernt.

Es gibt **keinen** Clipping-, Saturations- oder Wrap-Pfad. Ein Test prüft
zusätzlich, dass `validate_spec` das abgelehnte Spec-Objekt nicht verändert.

Enforcement in allen drei Konsumenten aus derselben Quelle: Validation
(`validate_spec`), Generator (der Prompt nennt benchmarkspezifisch
`allowed value_range: [lo,hi]` bzw. „value_range not available") und Mutation
(ein Shift/Narrowing, das die Domain verlassen würde, wird **nicht erzeugt** —
nie zurückgeklemmt).

| | |
|---|---|
| Range enabled | **48** Benchmarks |
| Range disabled | **1** — `sort/43_sort_sort_an_array_of_structs_by_key` (unvereinbare Site-Domains) |
| kein Fill-Hook (nie eine Range) | **11** |

---

## 8. Size-zero policy

`SIZE_ZERO_SPEC_POLICY = BENCHMARK_SEMANTICS_DEPENDENT`. Alle **60** Benchmarks
sind entschieden; es gibt **keine** globale Regel und **keine** UNKNOWNs.

**Regel S** (eingefroren): size 0 ist ALLOWED, wenn (1) der Oracle sicher ist
und ein **gradetes** Ergebnis liefert, (2) der frozen Prompt keine Vorbedingung
nennt, die size 0 verletzt, (3) das Ergebnis **nicht** aus einem Sonderfall-
Early-Return oder einem geleakten Initialisierer-Sentinel stammt, und (4) das
geforderte Ergebnis entweder ein leerer Ausgabecontainer, im Prompt genannt oder
die Identität der im Prompt definierten Reduktion ist.

| Klasse | Anzahl |
|---|---|
| **ALLOWED** | **44** |
| **DISALLOWED** | **11** |
| **NOT_APPLICABLE** | **5** |

**DISALLOWED (11)** mit dem konkreten Grund:

| Benchmark | Grund |
|---|---|
| `fft/05`, `fft/07`, `fft/08`, `fft/09` | frozen Prompt: „The size of x is always a power of two" — 0 ist keine Zweierpotenz |
| `geometry/12` | Oracle `if (points.size() < 3) return 0;` — Sonderfall, den der Prompt nicht nennt |
| `geometry/13` | Oracle `if (points.size() < 2) return 0;` — dito |
| `geometry/14` | Oracle `if (x.size() < 2) return 0;` — dito |
| `reduce/27` | `0.0/0 = NaN` → authentifizierter BASELINE_INCOMPATIBLE-Marker, **kein** Verdict |
| `scan/34` | Oracle leakt seinen Initialisierer `numeric_limits<int>::lowest()` als Antwort |
| `search/35` | `cpu.cc:67-76` BI-Guard; Quelle: „the frozen minimum size of this benchmark is n >= 1" |
| `sort/41` | `cpu.cc:64-73` BI-Guard; Prompt: `1 <= k <= x.size()` |

**NOT_APPLICABLE (5)**: `dense_la/01`, `graph/19`, `search/36`, `search/37`,
`search/39` — size 0 war schon durch eine benchmark-lokale **technische**
`min_size` ausgeschlossen, die semantische Frage stellt sich nicht.

Materialisierung: DISALLOWED wird zu einem benchmark-lokalen `min_size >= 1`,
**gemerged** mit dem technischen Minimum (das größere gewinnt); beide Provenienzen
bleiben im `size_constraint` sichtbar (`technical_min_size`, `size_zero_policy`).
Size 1 wird **nicht** mitentschieden; `graph/19` min 2, die fft-Predicates und
die K-Pattern-Mindestgröße 2 bleiben getrennt bestehen.

---

## 9. Tolerance policy

`KEEP_FROZEN_COMPARATOR_AND_CONSTRAIN_ENHANCED_INPUTS`.

**Nicht geändert**: kein Comparator, kein Epsilon, keine `baseline.hpp`, keine
`utilities.hpp`, keine Verdict-Klasse, keine Correctness-Semantik. `git diff`
über `drivers/cpp/utilities.hpp`, alle `baseline.hpp`, alle `cpu.cc`, alle
Driver und `thesis/evaluation/run_correctness.py` ist **leer**.

Stattdessen wurde der **Input** beschränkt — genau der vom Auftrag vorgesehene
Weg.

---

## 10. FALSE_FAIL_RISK reevaluation

Alle **14** `FALSE_FAIL_RISK`-Fälle und alle **10** `unsafe_pattern`-Fälle sowie
die **8** `extreme_semantics_deferred`-Fälle wurden einzeln gegen die neue
Domain-, Extreme- und Spike-Semantik geprüft (`pattern_audit[].e2b_reevaluation`
im Katalog, additiv — kein Auditfeld wurde überschrieben).

| Status | Anzahl | Bedeutung |
|---|---|---|
| `RESOLVED_BY_DOMAIN_POLICY` | 24 | der Hazard brauchte einen out-of-domain Wert und ist unerreichbar |
| `RESOLVED_BY_FROZEN_PROMPT` | 3 | `reduce/28` `all_zeros`/`all_same`/`alternating`: der No-Odd-Sentinel ist im Prompt gepinnt („in particular if x is empty") |
| `NO_LONGER_REACHABLE` | 5 | das Pattern ist jetzt unsupported (out-of-domain Konstante bzw. out-of-domain `hi`) |
| `UNKNOWN` | **0** | — |

Beispiele: `histogram/20` `bins[image[i]]` ist bei Domain `[0,255]` in-bounds;
`scan/34` `currSum` ist bei `[-100,100]` durch `100 · 4096 = 409600` beschränkt;
`stencil/54` Nachbarsumme bei `[0,1]` durch 8; `transform/58` `x*x` bei
`[-50,50]` durch 2500.

| | vorher | nachher |
|---|---|---|
| `FALSE_FAIL_RISK` (Auditfeld) | 14 | 14 (Auditfeld unverändert) |
| **ACTIVE_FALSE_FAIL_RISK** (aktiv **und** ohne auflösende Re-Evaluation) | 14 | **0** |
| aktive `unsafe_pattern_for_benchmark` | 10 | **0** |
| deferred Patternfälle | 22 | **0** |

Ehrliche Einschränkung: 5 **aktive** Patternfälle tragen im Auditkatalog
weiterhin das Rohfeld `verdict_outcome_class = FALSE_FAIL_RISK`
(`reduce/27 spike_at`, `reduce/28 all_zeros|all_same|alternating`,
`reduce/29 spike_at`). Das Feld ist die **E1-Aufzeichnung** und wurde bewusst
nicht überschrieben; jeder dieser fünf trägt eine explizite auflösende
E2-B-Re-Evaluation. Es blieb **kein** Fall ohne Verdict.

---

## 11. Parallel-bias reevaluation

Alle **17** `parallel_bias_risk`-Fälle wurden neu bewertet. Die E1-Begründung
ist in jedem Fall ausschließlich die **Größenordnung**: „1 ulp at ~9e307 is
~1e292, so the 1e-4 ABSOLUTE tolerance deterministically fails any candidate
whose summation order differs". Mit Spike = Domain-`hi` und Extrema =
Domain-Endpunkten liegt der Ausreißer in derselben Größenordnung wie der Rest
des Inputs; der Reassoziationsfehler bleibt weit unter dem Comparatorfenster.

| | vorher | nachher |
|---|---|---|
| `parallel_bias_risk` (Auditfeld) | 17 | 17 |
| **aktiv ohne auflösende Re-Evaluation** | 11 | **0** |

Alle 17 tragen jetzt `RESOLVED_BY_DOMAIN_POLICY` bzw. `NO_LONGER_REACHABLE`.
`TOLERANCE_LIMITATION_REMAINS`: **keine** — es musste kein Pattern wegen eines
verbleibenden Toleranzrisikos deaktiviert werden.

---

## 12.–14. Adapter decisions (Graph / Sparse / sort44)

`GRAPH_ADAPTER_VOCABULARY = SPARSE_ADAPTER_POLICY = SORT44_ADAPTER_POLICY =
NO_NEW_ADAPTER_FOR_PILOT_002`.

**Keine Zeile Adaptercode** wurde geschrieben — kein Edge-Pattern-Vokabular,
keine Graphtopologie-Labels, kein Sparsity-Pattern, kein Row/Column-Adapter,
kein „zero structure"-Adapter.

Neu ist, dass die Abwesenheit von Patternvariation jetzt eine **protokollierte
Entscheidung** ist statt eines impliziten `PATTERN_EFFECT=NONE`: alle 11
Benchmarks ohne Fill-Hook tragen `adapter_policy` mit
`decision`, `policy_field`, `pattern_variation: unavailable`, `reason` und
`evidence`.

| Policy-Feld | Benchmarks |
|---|---|
| `GRAPH_ADAPTER_VOCABULARY` | `graph/15`, `graph/16`, `graph/17`, `graph/18`, `graph/19` |
| `SPARSE_ADAPTER_POLICY` | `sparse_la/45`, `sparse_la/49` |
| `SORT44_ADAPTER_POLICY` | `sort/44` |
| `NO_HOOK_NO_ADAPTER` | `dense_la/01`, `histogram/23`, `reduce/25` |

Sizevariation bleibt überall dort erhalten, wo die Sizepolicy sie zulässt
(getestet: `graph/15` erzeugt weiterhin mehrere verschiedene Größen).

---

## 15. Large-size decision

`LARGE_SIZE_POLICY = KEEP_MAX_SPEC_SIZE_4096_FOR_PILOT_002`.
`specs.py::DEFAULT_SETTINGS["max_spec_size"]` ist **unverändert 4096**; Size 4096
wird weiterhin akzeptiert, 4097 weiterhin abgelehnt. Keine >4096-Expansion.
Benchmark-spezifisch engere Grenzen (fft-Predicate, `min_size`) bleiben.

---

## 16. Productive policy changes

| Datei | Änderung |
|---|---|
| `enhanced_capabilities.json` | **additiv**: `declared_fill_domain` (70 Sites), `e2b_size_zero` (60), `e2b_adapter_policy` (11), `e2b_reevaluation` (43 Patternfälle), `_meta.e2b_policy_freeze`. Maschinell verifiziert: nichts entfernt oder umgeschrieben. |
| `derive_enhanced_policy.py` | neue Regeln R6–R10; `SIZE_CONSTRAINTS` bleibt entfernt; `DERIVATION_VERSION = e2b.1` |
| `enhanced_policy.json` | neu: `fill_domain_capability`, `size_zero_policy`, `adapter_policy`, gemergtes `size_constraint`, `frozen_e2b_policies`; `open_policies_not_decided_here` jetzt **leer** |
| `capabilities.py` | `value_range_domain_rejection`, `explicit_values_domain_rejection`, `declared_domain`, `size_zero_policy`, `adapter_policy`; erweiterte Fail-Closed-Strukturprüfung; erweiterte `policy_summary` |
| `specs.py` | Domainprüfung in `validate_spec`; domainbewusste Range-Mutation |
| `generate_test_specs.py` | Prompt nennt `allowed value_range` / „not available" / Size-0-Verbot |
| `enhanced-fill.hpp` | `enhancedExtremeValue(lo, hi, i)`, `enhancedSpikeValue(hi)`, `extreme_values` im Span-Guard |
| `check_enhanced_capabilities.py` | P12–P17; P5 respektiert die Re-Evaluation; P10 prüft den Merge |

Die Kette bleibt: `enhanced_capabilities.json` → `derive_enhanced_policy.py` →
`enhanced_policy.json` → `capabilities.py` → Validation/Generator/Mutation/Runner.
**Keine vierte Capabilityquelle.** Policy weiterhin fail-closed und exact-derived;
`policy_preflight` unverändert, Manifest-/Summary-Provenance unverändert.

| | |
|---|---|
| `enhanced_policy_sha256` | `0ac49ea0d58ff0e768819ecb4abd4efbd60d65c55f3d947f7b16181e6ca7bfbd` |
| `derived_from_sha256` | `8f3a0b6ad84aa183339bb12129dc638470c9c322d3a7e6fc300d7895c98dbada` |
| `derivation_version` | `e2b.1` |

---

## 17. Input drift

Aus der Harness-Semantik neu abgeleitet, **nicht** aus der E2-A-Map übernommen:

| Quelle | Wirkung |
|---|---|
| E2-A DType-Fix (4 Fill-Sites) | unverändert übernommen — Eigenschaft der Sites, nicht einer Policy |
| **NEU** `extreme_values` | `numeric_limits` → Domain-Endpunkte ⇒ **jeder** historische `extreme_values`-Spec auf einem Fill-Hook-Benchmark driftet |
| **NEU** `spike_at` | `max()/2` → Domain-`hi` ⇒ dito |
| Domainregel, Size-0-Regel, Degenerate-Regel | ändern **Gültigkeit**, nicht den Input ⇒ **kein** Drift |

Gemessen (OLD = HEAD, NEW = Working Tree, 48 Läufe je Header):

| | |
|---|---|
| `extreme_values` + `spike_at`, OLD vs NEW | **24 geändert / 0 unverändert** |
| `random` + `alternating`, OLD vs NEW | **0 geändert / 24 unverändert** |
| Define/Runtime-Parität (NEW) | **24 Vergleiche, 0 Abweichungen** |
| Sanitizer-Verdicts | OLD 48× CLEAN, NEW 48× CLEAN |

Driftquellen im Bestand: DType allein 7, E2-B-Semantik allein 46, beides 4.
Nach Pattern: `extreme_values` 41, `spike_at` 9, `descending` 3, `ascending` 2,
`sorted_except_one` 2.

---

## 18. Existing-spec reclassification

`thesis/enhanced_tests/classify_specs_e2b.py`, read-only, **neu berechnet** —
die E2-A.1-Partition wurde nicht als erwartete Wahrheit verwendet.

| Klasse | E2-A.1 | **E2-B** |
|---|---|---|
| `TOTAL_EXISTING_SPECS` | 483 | **483** |
| `INVALID_BY_POLICY_ONLY` | 76 | **160** |
| `INPUT_DRIFTED_BUT_STILL_VALID` | 7 | **11** |
| `INVALID_AND_DRIFTED` | 4 | **46** |
| `UNCHANGED_AND_VALID` | 396 | **266** |
| Summe | 483 ✓ | **160+11+46+266 = 483 ✓** |

Reason-Verteilung über die 206 invaliden Specs:

| Reason | Anzahl | seit |
|---|---|---|
| `no_pattern_effect` | 49 | E2-A |
| `explicit_value_outside_declared_domain` | **48** | **E2-B** |
| `unsupported_pattern_for_benchmark` | **45** | **E2-B** (41 `extreme_values`, 4 `all_zeros`) |
| `invalid_size_for_benchmark` | 24 | E2-A (12) + **E2-B Size-0 (12)** |
| `value_range_outside_declared_domain` | **24** | **E2-B** |
| `irrelevant_pattern_parameter` | 7 | E2-A.1 |
| `value_range_not_supported_for_benchmark` | **5** | **E2-B** (`sort/43`) |
| `inert_parameter_for_benchmark` | 2 | E2-A.1 |
| `unsafe_value_range_span` | 1 | E2-A.1 |
| `value_not_representable_for_benchmark` | 1 | E2-A |

Sechs Benchmarks haben danach **keinen** gültigen Bestandsspec mehr und
brauchen in E3 vollständige Neugenerierung: `fft/09`, `graph/15`, `search/37`,
`sort/41`, `sparse_la/45`, `sparse_la/49`.

---

## 19. Regeneration / reexecution counts

| | |
|---|---|
| `ENHANCED_SPECS_REGENERATION_REQUIRED` | **true**, **206** (160 invalid-only + 46 invalid-and-drifted) |
| `ENHANCED_SPECS_REEXECUTION_REQUIRED` | **true**, **11** (drifted, weiterhin gültig) |
| Specs tatsächlich regeneriert | **false** |
| `spec_key` geändert | **false** |
| `enhanced_tests.v1` geändert | **false** |

`capability_limited_spec_count` ist aktualisiert und ehrlich — kein Benchmark
wird durch irrelevante Ranges, inerte Parameter oder Fake-Labels wieder
aufgefüllt.

---

## 20. Capability counts

| | vorher (E2-A.1) | **nachher (E2-B)** |
|---|---|---|
| supported pattern cases | 499 | **470** |
| unsupported pattern cases | 139 | **190** |
| deferred / inactive pattern cases | 22 | **0** |
| range-enabled Benchmarks | — | **48** |
| range-disabled Benchmarks | — | **1** (+ 11 ohne Fill-Hook) |
| size-zero allowed / disallowed / n.a. | — | **44 / 11 / 5** |
| adapter-disabled Benchmarks | — | **11** |
| ACTIVE_FALSE_FAIL_RISK | 14 | **0** |
| aktives `parallel_bias_risk` | 11 | **0** |
| aktives `NO_VERDICT_BI` | 29 | **16** |
| aktives `REDUCED` | 150 | **138** |
| aktives `INFORMATIVE` | 250 | **245** |

Unsupported-Gründe nachher: `no_pattern_effect` 110,
`duplicate_of_alternating_under_domain_extrema` 49,
`no_single_canonical_fill_site` 19, `constant_outside_declared_fill_domain` 7,
`reaches_value_outside_declared_fill_domain` 5.

**Policy-UNKNOWNs: 0.** Getrennt davon behält das E1-Auditfeld
`verdict_outcome_class` für 66 aktive Patternfälle den Wert `UNKNOWN`. Das ist
eine **Audit-Vorhersage** darüber, wie ein Verdict ausfallen wird, kein
Policy-Loch: Pattern-, Range-, Size- und Adapterstatus sind für jeden dieser
Fälle entschieden, E3 bleibt dadurch nicht unbestimmt. Eine Neubestimmung dieser
Vorhersagen wäre ein E1-Re-Audit und ist bewusst **nicht** Teil dieser Wave.

---

## 21. Tests

| Nachweis | Ergebnis |
|---|---|
| `check_enhanced_capabilities.py` | **Exit 0** (660 Patternentries, inkl. neuer P12–P17) |
| `derive_enhanced_policy.py --check` | **Exit 0** |
| `test_capabilities.py` | passed |
| `test_e2a1_safety.py` | passed (7 Gruppen) |
| **`test_e2b_policy.py`** (neu) | passed (7 Gruppen, 85 Assertions) |
| `test_enhanced.py` | passed (11 Gruppen, im Container inkl. der g++-Gruppen) |
| Extreme Define/Runtime-Parität | **PASS** (24 Vergleiche, 0 Abweichungen) |
| Spike Define/Runtime-Parität | **PASS** (in denselben 24 enthalten) |
| `extreme_values == alternating` | **12/12 byteidentisch** (belegt R8) |
| Spike ist deterministisch vom Randombild verschieden | **PASS** (integral hi-exklusiv) |
| Declared-Domain-Rangetests | **PASS** (`[-1,1]` ✓, `[-0.5,0.5]` ✓, `[-2,1]` ✗, `[-1,2]` ✗; Split-Domain: jede Range ✗) |
| Size-Zero-Tests | **PASS** (allowed/disallowed/`graph/19` min 2/fft-Predicate/K-Pattern size<2) |
| FALSE-FAIL-Reachability | **PASS** (Validation, Generator und Mutation erzeugen keinen der 5 ausgeschlossenen Fälle) |
| Generator- und Mutationstests | **PASS** (kein Mutant verlässt die Domain, kein Clamping) |
| Real-Driver UBSan+ASan+float-cast-overflow | **58/58 clean, fail=0** über `reduce/28`, `scan/31`, `sort/42`, `sort/43` (Multi-Fill, 3 Domains), `stencil/54` (verengte Domain), `dense_la/00` (double), `dense_la/03` (Multi-Fill) |
| Keine NaN/Inf aus Patternsemantik | **PASS** (Probe prüft die Ausgabe zusätzlich auf `nan`/`inf`) |
| No-Enhanced-Regression | **PASS** („no defines: ENHANCED_FILL is exactly fillRand") |
| Compile-Grouping-Regression | **PASS** (`run_enhanced_tests.py` in dieser Wave unverändert) |
| Existing-Spec-Reclassification | 160+11+46+266 = 483 ✓ |

---

## 22. Cross-Pilot impact

**Nachher: Exit 1, `CROSS_PILOT_REPO_STATE_STALE = true`** — wie vorher.
Keine Fingerprints aktualisiert, keine Neuklassifikation, keine
99/0/99-Materialisierung, Candidate-Subset unverändert.

Stale fingerprinted Dateien: `drivers/cpp/enhanced-fill.hpp` (semantic),
`thesis/enhanced_tests/specs.py` (semantic),
`thesis/evaluation/run_enhanced_tests.py` (coarse).
**E2-B fügt keine zusätzliche fingerprinted Datei hinzu** — dieselben drei wie
nach E2-A.1; `run_enhanced_tests.py` wurde in dieser Wave gar nicht angefasst.

Unverändert und geprüft: alle Benchmark-lokalen Fingerprints der drei Kandidaten
(`cpu.cc`, `baseline.hpp`, `enhanced_spec_keys`, alle drei Prompt-Hashes),
`utilities.hpp`, `harness-markers.hpp`, alle drei Driver, `build_config.py`,
`run_correctness.py`, `framework.py`, `baseline_selftest.py`, Assembly,
Generation- und Evaluation-Condition.

`NORMAL_CORRECTNESS_INPUT_PATH_CHANGED = **false**`: ohne die `ENHANCED_*`-Defines
expandiert `ENHANCED_FILL` weiterhin byte-gleich zu `fillRand`, `utilities.hpp`
und `fillRand` sind unverändert, und die neuen Helfer leben in Templates, die
ohne die Defines nicht instanziiert werden.

---

## 23. E3 readiness

**`ENHANCED_POLICY_FROZEN_FOR_E3 = true`.**

* alle acht Policies (plus SPIKE_AT_SEMANTICS) entschieden und in
  `enhanced_policy.json::_meta.frozen_e2b_policies` materialisiert;
* `open_policies_not_decided_here` ist leer;
* 0 deferred Patternfälle, 0 aktive unsafe Fälle, `ACTIVE_FALSE_FAIL_RISK = 0`,
  0 aktive ungelöste Parallel-Bias-Fälle, 0 Policy-UNKNOWNs;
* Policy exact-derived und fail-closed, eine Quelle für Domain, Typ und Size;
* Validation, Generator, Mutation und Runner konsistent aus `capabilities.py`;
* die 483 Bestandsspecs sind neu klassifiziert, **keiner** wurde regeneriert.

**Verbleibende Enhanced-Blocker vor E3:** keine methodischen. Offen bleibt die
**Arbeit** von E3 — Regeneration von 206 Specs (sechs Benchmarks haben keinen
gültigen Bestandsspec mehr), Re-Execution von 11 drifted Specs — sowie die
Cross-Pilot-Re-Evaluation, die weiterhin außerhalb der Enhanced-Wellen liegt.

