# Pilot 001 Readiness Review

*Stand: 2026-08-22. Gegenstand ist ausschließlich der eingefrorene Run `pilot_001`. Alle bestehenden Pilot-Records, Manifeste, Konfigurationen, Specs, Artefakte sowie `overview.md` und `overview.csv` wurden read-only untersucht. Kontrollläufe erfolgten isoliert und schrieben nicht in den Pilot.*

## Executive Summary

- **Full Run: NO-GO.** Vor einem Full Run sind eindeutig nachgewiesene Oracle-, Validierungs- und Harness-Fehler zu beheben und in einem fokussierten Re-Pilot zu bestätigen.
- **Stencil und Sparse LA sind keine legitimen „besonders schwierigen“ Ausreißer.** Stencil prüft vier statt der im Prompt geforderten acht Nachbarn; Sparse LA konstruiert `b` mit additiver COO-Semantik, die Baseline aber mit Overwrite-Semantik, und akzeptiert zudem NaN als korrekt.
- **Die Enhanced-Stufe ist teilweise kontaminiert.** Ein Performance-Lauf folgt auf die eigentliche Validation, drei Benchmarks ignorieren Pattern-Inputs, Sparse-Gates sind NaN-blind, und ein normaler Buildfehler wird durch ein Enhanced-Include maskiert.
- **Toolfehler werden fälschlich wie erfolgreiche Null-Finding-Läufe behandelt.** Dadurch sind 74/340 als `stopped_clean` bezeichnete Static-Fälle nicht tool-vollständig; auch die publizierte LLOV/TSan-Kreuztabelle und Teile der Stop-Attribution sind verzerrt.
- **Die Record-Struktur ist vollständig, aber noch nicht Full-Run-ready.** 396 Initialsamples und 1.903 Overview-Rows sind lückenlos und duplikatfrei; `max_iterations = 2` sollte beibehalten werden. Nach den Pflichtfixes sind mindestens Stencil/Sparse-Reparaturpfade, Static/Combined-Pfade mit geänderter Tool-Completeness und die gesamte Enhanced-Stufe fokussiert zu wiederholen.

## 1. Stencil

### Ausgewählter Benchmark und Initialbefund

Das stratified Sampling wählte `stencil/50_stencil_xor_kernel`.

| Execution Model | pass | validation_failed | build_failed | timeout | runtime_error |
|---|---:|---:|---:|---:|---:|
| serial | 0 | 11 | 0 | 0 | 0 |
| omp | 0 | 11 | 0 | 0 | 0 |
| mpi | 1 | 9 | 1 | 0 | 0 |
| **Gesamt** | **1** | **31** | **1** | **0** | **0** |

Die niedrige Rate ist nicht durch FP-Toleranz, Launch-Probleme oder allgemeine Benchmark-Schwierigkeit erklärbar.

### Ursache und Evidenz

Der Prompt in `thesis/prompts/generation-prompts-thesis.json` und insbesondere sein 4×4-Beispiel definieren die Moore-Nachbarschaft mit acht umgebenden Zellen. Die Referenz in `drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/baseline.hpp::correctCellsXOR` zählt dagegen nur Nord, Süd, Ost und West. Für das im Prompt dokumentierte Beispiel unterscheiden sich die 4er- und 8er-Ausgabe an 7/16 Zellen.

Die Modellquellen liefern eine starke unabhängige Plausibilisierung:

- 32/33 Initialquellen implementieren erkennbar acht Nachbarn einschließlich Diagonalen.
- Der einzige Pass, `deepseek_v4_flash` MPI, implementiert genau die fehlerhafte 4er-Oracle.
- `qwen3_coder_api` MPI implementiert ebenfalls acht Nachbarn, scheitert aber legitim beim Build an einer Typinkonsistenz in `std::min(int, size_t)`.
- Alle 31 `validation_failed` sind exakte Integerabweichungen. Es gibt keine numerische Rundungskomponente.

Der normale Validator in `drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/cpu.cc::validate` prüft außerdem nur Interior-Zellen. Weil er einen manuellen Vergleich statt `reportAndCompareEq` nutzt, enthalten alle 31 Fehler keinen `mismatch_total`. Die Schleife mit unsigned Grenzen läuft bei Enhanced-Größe 0 in einen Underflow/Hang und prüft Randzellen grundsätzlich nicht.

Die Enhanced-Specs reproduzieren die falsche 4er-Oracle: typische task-korrekte 8er-Artefakte erreichen 11 `pass`/7 `fail`, während die einzige 4er-Lösung 18/0 erreicht. Mehrere Rationales nennen ausdrücklich vier Nachbarn; ein anderer Spec enthält zugleich das dokumentierte 8er-Beispiel. Normal- und Enhanced-Test sind also untereinander konsistent, aber gemeinsam inkonsistent mit der gemessenen Aufgabe.

### Driver-, Interface- und Referenzkontrolle

Eine isolierte Referenzkontrolle mit der aktuellen 4er-Baseline, unverändertem normalen Driver und unveränderten Flags bestand zuverlässig:

- serial;
- OpenMP mit 1/2/4/8 Threads;
- MPI mit 1/2/4/8 Prozessen.

Damit sind Signatur, Datenaufteilung, OpenMP-/MPI-Launch und die normale Problemgröße als gemeinsame Fehlerursache ausgeschlossen. Der Kontrolllauf zeigt zugleich das eigentliche Problem: Eine zur implementierten Oracle passende 4er-Lösung besteht, task-korrekte 8er-Lösungen werden abgelehnt.

### Klassifikation und Empfehlung

| Klasse | Urteil |
|---|---|
| A – tatsächlich sehr schwierig | **nein** |
| B – Prompt-/Interface-Missverständnis | **sekundär ja**; Prosa/Specs und Oracle sind nicht konsistent |
| C – numerische Toleranz | **nein** |
| D – Driver-/Baseline-/Harness-Bug | **eindeutig ja** |
| E – andere Ursache | nein |

Minimal erforderlich:

1. `baseline.hpp::correctCellsXOR` auf acht Nachbarn korrigieren.
2. `cpu.cc::validate` über den vollständigen Ergebnisvektor mit `reportAndCompareEq` ausführen. Das behebt Randabdeckung, Größe-0-Underflow und fehlende Mismatchdiagnose.
3. Prompttext explizit auf „acht Nachbarn einschließlich Diagonalen“ festlegen und Stencil-Enhanced-Specs/Rationales gegen dieselbe Semantik neu erzeugen; neuer Spec-Hash, ohne den eingefrorenen Pilot-Hash zu überschreiben.

Betroffen sind alle Stencil-Correctness-, Enhanced- und Repairtrajektorien: 260 Overview-Zeilen beziehungsweise alle 33 Modell/Execution-Model-Samples über die Varianten. Initiale Rohgenerationen und statische Rohfindings können archiviert bleiben; für Vergleichbarkeit mit einem geklärten Full-Run-Prompt ist ein fokussierter Stencil-Re-Pilot erforderlich.

## 2. Sparse LA

### Ausgewählter Benchmark und Initialbefund

Das Sampling wählte `sparse_la/45_sparse_la_sparse_solve`.

| Execution Model | pass | validation_failed | build_failed/timeout/runtime_error |
|---|---:|---:|---:|
| serial | 1 | 10 | 0 |
| omp | 3 | 8 | 0 |
| mpi | 3 | 8 | 0 |
| **Gesamt** | **7** | **26** | **0** |

Kein Execution Model fällt wegen Launch oder Parallelisierung fast vollständig aus; derselbe strukturelle Oraclefehler betrifft serial, OMP und MPI.

### Inkonsistente COO-Duplikatsemantik

Der Driver in `drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc` erzeugt `b`, indem er jeden COO-Eintrag additiv berücksichtigt. Die Referenz in `baseline.hpp::correctSolveLinearSystem` baut die dichte Matrix dagegen per Zuweisung auf und überschreibt frühere Werte bei doppelten Koordinaten.

Die eingefrorene glibc-`rand()`-Folge des normalen Drivers enthält tatsächlich zahlreiche Duplikate:

| Trial | Einträge | eindeutige Koordinaten | zusätzliche Duplikate | duplizierte Koordinaten | max. Multiplizität |
|---|---:|---:|---:|---:|---:|
| 1 | 1.638 | 1.565 | 73 | 70 | 3 |
| 2 | 1.638 | 1.557 | 81 | 76 | 4 |

Eine deterministische Reproduktion ergab:

- Matrixaufbau mit `+=` rekonstruiert den gepflanzten Lösungsvektor an 128/128 Stellen innerhalb `1e-3`; Medianfehler etwa `3.6e-14`, Maximum `1.7e-13`.
- Die Overwrite-Oracle weicht an 128/128 Stellen ab; Medianfehler 11,3 beziehungsweise 21,8, Maximum 64 beziehungsweise 111.
- 18 Artefakte aus serial, OMP und MPI liefern identisch den gepflanzten Vektor, beginnend mit `[6.568282105293223, -6.132839087458608, -8.500929902541081]`. Die Oracle erwartet stattdessen `[25.17203357835558, -8.317308503733528, 0.5468600963459435]`.
- 24/26 Initial-Fails melden 128 Mismatches, zwei melden 126. Das ist strukturell und nicht eine kleine FP-Abweichung.

Die Aufgabe spezifiziert das Verhalten bei doppelten COO-Koordinaten nicht explizit. Das erklärt, warum Modelle unterschiedlich entscheiden; der Driver und seine eigene Baseline dürfen aber nicht unterschiedliche Semantiken verwenden.

### NaN-False-Passes

`drivers/cpp/utilities.hpp::reportAndCompare` verwendet im Wesentlichen `abs(x-y) > epsilon`. Ist ein Operand NaN, ist die Bedingung falsch und der Wert wird nicht als Mismatch gezählt.

Direkte Kontrollen:

- Ein absichtlich ausschließlich NaN ausgebendes Artefakt bestand mit dem unveränderten normalen Sparse-Driver.
- Ein instrumentiertes Qwen36-MPI-Reparaturartefakt erzeugte in beiden Trials 128 nicht-finite Werte und erhielt dennoch `Validation: PASS`.
- Fünf der sieben Initial-Passes nutzen iterative Solver mit fehlender Diagonale beziehungsweise nicht-finiten Pfaden. Nur die Fable-Serial- und Fable-OMP-Lösungen sind echte Pässe unter der derzeitigen Last-wins-Oracle.

Die beobachtete Initial-Passrate 7/33 überschätzt somit sogar die Korrektheit.

### Enhanced-Konsistenz und Repair

21/26 normal inkorrekte Initialartefakte bestehen 20/20 Enhanced-Specs; keines der 33 Initialartefakte hat einen Enhanced-`fail`. Die verbleibenden Anomalien sind Crash/Timeout. Das ist keine unabhängige Bestätigung:

- `benchmark_shapes.json` weist `fill_sites: 0` aus; Pattern wie `all_zeros`, `duplicate_at` und `extreme_values` verändern den Input nicht.
- Mit `nVals = floor(0.1*N²)` sind die kleinen Systeme singulär oder unterbestimmt.
- Die Baseline produziert nicht-finite Werte; derselbe NaN-blinde Comparator lässt Baseline- und Candidate-NaNs sowie das Baseline-Gate passieren.

Die stärkere finale Rate von `test_feedback` ist daher überwiegend kein valider Reparaturgewinn. Die sieben zusätzlichen Test-Pässe gegenüber Static sind Fable MPI, Opus serial/OMP/MPI, GPT-5.6 serial, Qwen3 OMP und Qwen36 MPI. Sechs änderten den COO-Aufbau ausdrücklich von `+=` auf `=` und lernten damit die fehlerhafte Oracle; Qwen36 ist der nachgewiesene 128-NaN-False-Pass. Static Feedback sieht den Output-/Oracle-Mismatch nicht und kann diese Anpassung nicht gezielt erzeugen.

Ein Last-wins-Referenzsolver bestand isoliert mit dem normalen Driver in serial, OMP 1/2/4/8 und MPI 1/2/4/8. Signatur und Launch funktionieren; der Lauf bestätigt nur die derzeitige fehlerhafte Oracle-Semantik.

### Klassifikation und Empfehlung

| Klasse | Urteil |
|---|---|
| A – tatsächlich sehr schwierig | nicht aus diesen Pilotverdicts ableitbar |
| B – Prompt-/Interface-Missverständnis | **ja**, Duplicate-Semantik fehlt |
| C – numerische Toleranz | **nein** |
| D – Driver-/Baseline-/Harness-Bug | **eindeutig ja**, zwei unabhängige Fehler |
| E – andere Ursache | Enhanced-Inputdesign zusätzlich ungeeignet |

Minimal erforderlich:

1. In `baseline.hpp::correctSolveLinearSystem` den COO-Aufbau mit `+=` an `b` angleichen und additive Duplicate-Semantik im Prompt ausdrücklich festlegen. Alternativ wären Duplikate vollständig aus der Eingabe zu entfernen; dies wäre die stärkere Änderung und ist nicht empfohlen.
2. In diesem Benchmark-Validator Candidate **und** Referenz explizit auf `std::isfinite` prüfen. Ein lokaler Fix ist wissenschaftlich enger als eine ungeprüfte globale Änderung aller FP-Vergleiche.
3. Enhanced-Sparse-Inputs als deterministisch nonsinguläre Systeme mit bekannter Lösung erzeugen. Bis dies validiert ist, Sparse Enhanced als `unsupported/baseline_incompatible` behandeln, nicht als Pass oder Modell-Fail.

Betroffen sind alle Sparse-LA-Normal-, Enhanced- und Repairdaten: 247 Overview-Zeilen. Wegen geänderter Aufgabenpräzisierung und Repairtrajektorien ist ein fokussierter Sparse-LA-Re-Pilot erforderlich.

## 3. Enhanced-Test-Anomalien

### Deduplizierte Grundgesamtheit

Für die Artefaktebene wurde auf `(sample_id, artifact_variant, iteration)` dedupliziert. Die 396 Initialartefakte wurden als `shared_initial` genau einmal gezählt und nicht durch Carry-Forward dreifach vervielfacht.

- 1.111 tatsächlich erzeugte Artefaktversionen;
- 22.220 Spec-Runs, exakt 20 pro Artefakt;
- 369 Artefakte mit mindestens einem `fail`, `crash`, `timeout` oder `build_failed`;
- davon 299 mit `fail`, 43 mit `crash`, 13 mit `timeout` und 28 mit `build_failed`; Status können sich je Artefakt überlappen.

| Spec-Status | Anzahl |
|---|---:|
| pass | 17.523 |
| fail | 2.072 |
| crash | 663 |
| timeout | 164 |
| build_failed | 518 |
| baseline_incompatible | 752 |
| numerically_unstable | 528 |
| **Gesamt** | **22.220** |

Die vom Overview berichteten Spec-Zahlen werden exakt reproduziert:

| exec | Artefakte | any anomaly | fail art. | crash art. | timeout art. | build art. | pass specs | fail specs | crash specs | timeout specs | build specs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| serial | 275 | 100 | 87 | 10 | 0 | 3 | 4.271 | 591 | 196 | 0 | 56 |
| omp | 367 | 105 | 86 | 10 | 2 | 7 | 5.995 | 601 | 170 | 40 | 136 |
| mpi | 469 | 164 | 126 | 23 | 11 | 18 | 7.257 | 880 | 297 | 124 | 326 |
| **Gesamt** | **1.111** | **369** | **299** | **43** | **13** | **28** | **17.523** | **2.072** | **663** | **164** | **518** |

### Artefakte nach Problemtyp und Benchmark

| Problemtyp / Benchmark | N | any | fail | crash | timeout | build |
|---|---:|---:|---:|---:|---:|---:|
| dense_la / `00_dense_la_lu_decomp` | 82 | 4 | 3 | 0 | 0 | 1 |
| fft / `05_fft_inverse_fft` | 81 | 10 | 7 | 0 | 0 | 3 |
| geometry / `10_geometry_convex_hull` | 132 | 85 | 71 | 15 | 0 | 5 |
| graph / `15_graph_edge_count` | 36 | 1 | 0 | 0 | 0 | 1 |
| histogram / `20_histogram_pixel_histogram` | 39 | 2 | 0 | 0 | 0 | 2 |
| reduce / `25_reduce_xor` | 35 | 7 | 6 | 1 | 0 | 0 |
| scan / `30_scan_prefix_sum` | 103 | 7 | 1 | 1 | 2 | 3 |
| search / `35_search_search_for_last_struct_by_key` | 62 | 10 | 9 | 0 | 0 | 1 |
| sort / `40_sort_sort_an_array_of_complex_numbers_by_magnitude` | 91 | 17 | 14 | 0 | 6 | 3 |
| sparse_la / `45_sparse_la_sparse_solve` | 181 | 30 | 0 | 23 | 3 | 4 |
| stencil / `50_stencil_xor_kernel` | 194 | 189 | 184 | 0 | 1 | 5 |
| transform / `55_transform_relu` | 75 | 7 | 4 | 3 | 1 | 0 |

### Artefakte nach Modell

| Modell | N | any | fail | crash | timeout | build |
|---|---:|---:|---:|---:|---:|---:|
| claude_fable_5 | 82 | 25 | 25 | 0 | 0 | 0 |
| claude_opus_5 | 87 | 28 | 27 | 0 | 0 | 1 |
| deepseek_v4_flash | 110 | 27 | 20 | 1 | 0 | 6 |
| deepseek_v4_pro | 108 | 35 | 28 | 2 | 0 | 7 |
| gemini_31_pro | 101 | 25 | 21 | 0 | 3 | 1 |
| gemini_36_flash | 107 | 34 | 32 | 0 | 0 | 2 |
| openai_gpt55 | 101 | 47 | 28 | 19 | 0 | 0 |
| openai_gpt56_sol | 87 | 31 | 26 | 4 | 0 | 1 |
| qwen36_35b_a3b | 106 | 35 | 29 | 1 | 1 | 5 |
| qwen37_max | 99 | 35 | 32 | 6 | 0 | 1 |
| qwen3_coder_api | 123 | 47 | 31 | 10 | 9 | 4 |

### Artefakte nach Feedbackvariante und Iteration

| Variante / Iteration | N | any | fail | crash | timeout | build |
|---|---:|---:|---:|---:|---:|---:|
| shared_initial / 0 | 396 | 83 | 63 | 8 | 3 | 11 |
| static / 1 | 159 | 48 | 42 | 6 | 1 | 2 |
| static / 2 | 76 | 24 | 18 | 6 | 0 | 2 |
| test / 1 | 98 | 47 | 38 | 7 | 2 | 2 |
| test / 2 | 70 | 41 | 34 | 5 | 1 | 2 |
| combined / 1 | 189 | 73 | 60 | 7 | 3 | 5 |
| combined / 2 | 123 | 53 | 44 | 4 | 3 | 4 |

### Buildfehler: normaler Correctness-Build gegen Enhanced

Alle 28 Enhanced-`build_failed`-Artefakte scheitern auch im normalen ParEval-Correctness-Build. Diese 518 Spec-Status sind legitime Modell-Buildfehler.

Es gibt jedoch 29 normale Buildfehler. Der fehlende 29. Fall ist `gemini_31_pro`, Sparse LA, MPI, `combined_feedback` Iteration 2:

- normal: `std::memset` ist wegen fehlendem `<cstring>` nicht definiert;
- Enhanced: `drivers/cpp/enhanced-fill.hpp` inkludiert `<cstring>` vor `generated-code.hpp` und maskiert den Modellfehler;
- Ergebnis: Enhanced kompiliert und meldet 20 Timeouts statt Buildfehler.

Der normale Correctness-Build muss deshalb als autoritativer Preflight gelten. Enhanced-Infrastruktur darf fehlende Modell-Includes nicht implizit reparieren.

### Eindeutige Enhanced-Harness-Bugs

#### A. Nach der Validation läuft ein fremder Performance-Workload

`thesis/evaluation/run_enhanced_tests.py` startet den normalen Driver mit `niter=1`. Nach `validate()` führen `drivers/cpp/models/serial-driver.cc`, `omp-driver.cc` und `mpi-driver.cc` weiterhin den festen Performance-Workload mit `DRIVER_PROBLEM_SIZE` aus. Der Status kann damit vom Spec statt vom nachfolgenden, nicht zum Spec gehörenden Lauf stammen.

Hart nachgewiesen sind 19 Artefaktversionen und mindestens 40 falsche Spec-Status:

- 14 Versionen haben für `N==0` einen sicheren frühen Return, ihre zwei Größe-0-Specs crashen aber danach: 28 sicher post-validation erzeugte Crash-Status;
- 5 Versionen zeigen dasselbe bei Timeout: 12 sicher post-validation erzeugte Timeout-Status;
- diese 19 Artefakte enthalten insgesamt 380 Crash-/Timeout-Rows. Für positive Größen ist nicht rekonstruierbar, welcher Anteil bereits in `validate()` scheitert; 380 ist daher nur die phasenambige Obermenge, nicht die Zahl nachgewiesener Fehlklassifikationen.

`niter=0` ist kein sicherer Fix: OMP ignoriert den Wert, Serial und MPI teilen später durch `NITER`. Minimal ist ein Python-3.8-kompatibles Compile-Define wie `ENHANCED_VALIDATION_ONLY` und ein sauberer Return unmittelbar nach erfolgreicher Validation; bei MPI müssen alle Ranks Ressourcen freigeben und `MPI_Finalize()` ausführen.

#### B. Drei Benchmarks ignorieren Pattern-Inputs

Der Runner akzeptiert einen Benchmark bereits wegen `ENHANCED_TEST_SIZE_DEFAULT`. Graph, Reduce und Sparse rufen in `validate()` aber nie `ENHANCED_FILL` auf; `benchmark_shapes.json` dokumentiert für alle drei `fill_sites: 0`.

| Benchmark | Artefakte | Rows | Größen | redundante Pattern-Rows | Statusvariation innerhalb `(Artefakt, Größe)` |
|---|---:|---:|---:|---:|---:|
| graph | 36 | 720 | 12 | 288 | 0/432 Gruppen |
| reduce | 35 | 700 | 14 | 210 | 0/490 Gruppen |
| sparse_la | 181 | 3.620 | 9 | 1.991 | 0/1.629 Gruppen |
| **Gesamt** | **252** | **5.040** |  | **2.489** | **0/2.551 Gruppen** |

Damit tragen 22,7 % aller Enhanced-Rows Patternlabels, die den Input nicht verändern. Der risikoärmste Fix ist, in `thesis/enhanced_tests/specs.py::validate_spec/build_benchmark_specs` bei `fill_sites == 0` nur size-only/random-Fälle zuzulassen und andere Pattern als unsupported zu markieren oder pro Größe zu kanonisieren. Driver-spezifische Hooks sind erst nach Invariantenprüfung sinnvoll; insbesondere bei Sparse sind COO-Indizes, Werte, `b` und bekannte Lösung gekoppelt.

#### C. Sparse Baseline-Gate ist NaN-blind

Die Enhanced-Größen sind `0,1,2,3,4,6,7,8,14`. Für jede positive Pilotgröße erzeugt die deterministische Sparse-Referenz in beiden Validation-Trials **null finite Ausgabewerte**; zum Beispiel `N=1`: 1 NaN, `N=8`: 7 NaN + 1 Inf, `N=14`: 13 NaN + 1 Inf.

| Größenbereich | pass | crash | timeout | build | baseline_incompatible | numerically_unstable |
|---|---:|---:|---:|---:|---:|---:|
| N = 0 | 320 | 28 | 6 | 8 | 0 | 0 |
| N > 0 | 2.718 | 414 | 54 | 72 | 0 | 0 |

Alle 2.718 positiven Sparse-`pass`-Rows sind deshalb methodisch unbrauchbar beziehungsweise potenzielle False Passes. Das Baseline-/Fast-Math-Gate benutzt denselben NaN-blinden Validator und gate-t keinen Fall. Nicht-finite Oracle-Ausgaben müssen als `baseline_incompatible` gelten, niemals als Modell-Pass oder Modell-Fail. Danach sind nonsinguläre Sparse-Inputs nötig; andernfalls würden alle positiven Specs nur ausgeschlossen.

#### D. Phaseninformation geht bei Crash/Timeout verloren

Nach einem Timeout verwirft `run_enhanced_tests.py` die Rückgabe des abschließenden `communicate()`; Crash-Records persistieren keinen stdout-/Validation-Marker. Deshalb lässt sich bei den phasenambigen Rows nicht erkennen, ob `Validation: PASS` bereits ausgegeben war. Dies ist primär ein Diagnostikdefizit, verstärkt aber die Post-validation-Kontamination.

### Crash-, Timeout- und Fail-Muster

Abseits der nachgewiesenen Post-validation-Gruppe sind die Crash-/Timeout-Ursachen modellnah und nicht breit über unabhängige Modelle verteilt:

- Sparse: 162 direkte Crash-Rows, überwiegend Assertions/Ausnahmen fehlerhafter Modellsysteme;
- Geometry: 174 Crash-Rows, OMP-Segfaults und MPI-`Gatherv`/Abort;
- Reduce: 20 MPI-Rows;
- Scan: 2 OMP-Rows mit double-free/corruption;
- Transform: 25 Rows mit fehlerhaften MPI-Collectives;
- Sort MPI: 44 direkte Timeout-Rows über 6 Qwen3-Artefakte, nachdem Vektorgrößen rankabhängig mutiert werden;
- Stencil MPI: 10 direkte Timeout-Rows eines Artefakts durch `MPI_Gather` mit rankabhängigem `send_count`;
- Transform MPI: 10 direkte Timeout-Rows eines Artefakts durch inkonsistentes `local_n`.

Die seriell ausgeführten Baseline-Gates erklären diese target-spezifischen OMP-/MPI-Fehler nicht. Signaturen, die über viele Modelle wiederkehren, sind vor allem Stencil-`fail` wegen der falschen Oracle und Geometry-Edge-Cases; breite Crash-/Timeout-Signaturen fehlen.

Kleine Größen tragen überproportional zu Crash/Timeout bei, erklären sie aber nicht allein:

- `fail` bei N=0/1/2: 120/2.072; kein Artefakt scheitert ausschließlich dort;
- `crash` bei N=0/1/2: 315/663; 41/43 Artefakte haben kleine Crash-Fälle, nur eines ausschließlich kleine;
- `timeout` bei N=0/1/2: 93/164; alle 13 Artefakte haben kleine Timeout-Fälle, keines ausschließlich kleine.

Raw Patternzahlen:

| Pattern | fail | crash | timeout | build |
|---|---:|---:|---:|---:|
| all_same | 246 | 43 | 20 | 63 |
| all_zeros | 102 | 102 | 21 | 54 |
| alternating | 33 | 7 | 5 | 11 |
| ascending | 53 | 16 | 8 | 32 |
| descending | 12 | 69 | 9 | 20 |
| duplicate_at | 18 | 58 | 8 | 19 |
| explicit_values | 430 | 6 | 18 | 69 |
| extreme_values | 68 | 87 | 28 | 57 |
| random | 1.070 | 242 | 47 | 169 |
| sorted_except_one | 40 | 33 | 0 | 24 |

Für Graph, Reduce und Sparse dürfen diese Patternzahlen wegen der wirkungslosen Hooks nicht interpretiert werden.

Nur 301/2.072 `fail`-Rows enthalten Mismatchdiagnostik; 1.771 nutzen manuelle Validatoren. Von 132 auswertbaren relativen Abweichungen sind 124 finite, 7 NaN und 1 Inf. Die finiten Werte liegen zwischen 0,2 und 2,0, Median 1,0; kein Wert liegt bei oder unter `1e-6`. Es gibt **keinen** Hinweis auf eine zu enge FP-Toleranz.

### Ursachenübersicht

Statusspalten und Ursachen können sich auf Artefaktebene überlappen. Die ersten drei Zeilen sind rohe `fail`-Mengen; Stencil darin ist wegen Abschnitt 1 nicht als legitimer Modellfehler zu interpretieren.

| Ursache | exec | betroffene Artefakte | betroffene Specs | Harness-Bug? | Full-Run-Relevanz |
|---|---|---:|---:|---|---|
| beobachtete funktionale/strukturelle Fails | serial | 87 | 591 | teilweise: Stencil | nach Oracle-Fix neu messen |
| beobachtete funktionale/strukturelle Fails | omp | 86 | 601 | teilweise: Stencil | nach Oracle-Fix neu messen |
| beobachtete funktionale/strukturelle Fails | mpi | 126 | 880 | teilweise: Stencil | nach Oracle-Fix neu messen |
| direkte Modellcrashes außerhalb der Kontaminationsgruppe | serial | 2 | 36 | nein | legitime Modellfehler |
| direkte Modellcrashes außerhalb der Kontaminationsgruppe | omp | 4 | 50 | nein | legitime Modellfehler |
| direkte Modellcrashes außerhalb der Kontaminationsgruppe | mpi | 23 | 297 | nein | legitime Modellfehler |
| direkte Modelltimeouts außerhalb der Kontaminationsgruppe | mpi | 8 | 64 | nein | legitime MPI-Modellfehler |
| post-validation Performance-Workload | alle | 19 | mindestens 40 sicher; 380 phasenambig | **ja** | Validation-only vor Full Run |
| normal und Enhanced nicht kompilierbar | alle | 28 | 518 | nein | legitime Modell-Buildfehler |
| normaler Buildfehler durch Enhanced-Include maskiert | mpi | 1 | 20 | **ja** | normaler Build als Preflight |
| Pattern-Hook fehlt | alle | 252 | 5.040 | **ja** | Patternaussagen ungültig |
| Sparse-Oracle nicht-finite, Gate NaN-blind | alle | 181 | 3.620, darunter 2.718 positive Pässe | **ja** | Sparse Enhanced ungültig |

Nach den Fixes A–C und dem Build-Preflight ist die gesamte Enhanced-Pilotstufe in einem neuen Ergebnisnamespace neu zu rechnen. Generationen, normale Correctness und Repair müssen dafür allein nicht erneut ausgeführt werden; Stencil/Sparse und geänderte Repair-Stopregeln erfordern jedoch unabhängig davon eigene Re-Pilots.

## 4. LLOV vs TSan

### Gemeinsame, erfolgreiche Grundgesamtheit

Die veröffentlichte Kreuztabelle `beide 1 / nur LLOV 79 / nur TSan 43 / weder 244` behandelt erfolglose oder unvollständige Läufe implizit wie null Findings. Das ist nicht zulässig. Zwar besitzen beide Tools für alle 367 OMP-Artefakte physische Records mit `ran=true`, aber nur 286 LLOV- und 357 TSan-Records haben `error=null`. LLOV hat 61 Exit-1- und 20 Exit-254-Fehler; TSan hat 8 Instrumentierungs-Buildfehler und 2 Laufzeit-Timeouts.

Von 367 OMP-Artefakten waren beide Tools nur bei 282 erfolgreich. Unter strikter Trennung von „nicht gelaufen/Fehler/Timeout“ und „erfolgreich, 0 Findings“ ergibt sich:

| nur erfolgreich vergleichbare Artefakte | TSan Race | TSan kein Race | Gesamt |
|---|---:|---:|---:|
| LLOV Race | 0 | 76 | 76 |
| LLOV kein Race | 28 | 178 | 206 |
| **Gesamt** | **28** | **254** | **282** |

85 Artefakte sind nicht streng vergleichbar: bei 75 fehlt nur ein erfolgreicher LLOV-Lauf, bei 4 nur ein erfolgreicher TSan-Lauf, bei 6 fehlen beide. Unter den LLOV-inconclusive Fällen besitzen 15 einen TSan-Witness; unter den TSan-inconclusive Fällen besitzen 4 einen LLOV-Fund.

Der publizierte „both“-Fall ist Qwen3 Scan. LLOV meldet Zeile 26 im lokalen ersten Prefix-Pass (`output[i] = output[i-1] + x[i]`); TSan meldet Zeile 66 beim Task-Write `output[i] += offset`. Der TSan-Gesamtlauf endet später im 8-Thread-Fall mit Timeout. Als partielle Evidenz sind beide Hinweise relevant, als erfolgreicher gemeinsamer Toollauf oder gegenseitige Quellstellenbestätigung aber nicht. Der TSan-Fund ist quellenlogisch plausibel, der LLOV-Fund im disjunkten Chunk-Pass wirkt dagegen wie ein polyhedrales False Positive.

### Repräsentative Quellstellen

| Gruppe | Beispiel | Vergleich |
|---|---|---|
| LLOV-only | Fable Dense-LU, parallele Zeilenschleife | LLOV markiert Zugriff in der Parallelregion; jede Iteration schreibt eine andere Matrixzeile und liest den gemeinsamen Pivot. TSan bleibt ohne Witness. Nach Quellprüfung wahrscheinliches statisches False Positive. |
| LLOV-only | Fable Stencil, parallele Output-Schleife | getrennte Output-Indizes, read-only Input; TSan bleibt ohne Witness. Klarer Kandidat für ein LLOV-False-Positive. |
| LLOV-only | Qwen36 Search, `reduction(max:result)` | LLOV markiert die Zuweisung an `result`; OpenMP macht die Reduktionsvariable thread-private und führt sie regelkonform zusammen. TSan bleibt ohne Finding, repariertes Artefakt besteht ParEval und Enhanced. |
| TSan-only | Qwen36 Scan, gemeinsames `num_threads` | alle Threads schreiben ohne `single`/Reduktion/Atomic auf dieselbe Variable. Auch identische Werte sind ein C++-Data-Race; LLOV findet nichts. |
| TSan-only | Fable Sparse LA | TSan attribuiert an die Modellregion, die Rohstacks zeigen jedoch `memset`/`___kmp_free` in libomp; wahrscheinlich Runtime-/Attributions-False-Positive. |
| TSan-only | DeepSeek Flash Geometry | Rohzugriffe sind `pthread_mutex_lock` gegen `pthread_mutex_init` in libomp; Modellframes stehen nur im Aufrufstack. Ebenfalls Runtime-nah und nicht als sicherer Modellrace zu werten. |
| apparent both | Qwen3 Scan | unterschiedliche Quellstellen/Race-Arten; TSan-Lauf später unvollständig, daher keine echte Übereinstimmung. |

Die Diskrepanz ist fachlich plausibel: LLOV ist statisch und kann disjunkte Iterationen/komplexe OpenMP-Konstrukte falsch approximieren; TSan benötigt einen tatsächlich ausgelösten Interleaving-Witness und hat eigene OpenMP-/Instrumentierungsgrenzen. Übereinstimmung ist deshalb weder zu erwarten noch als Gütekriterium zu erzwingen.

Die vorhandene Toolvalidation spricht dennoch klar gegen „LLOV allein = sichere Race“:

| Tool | TP | FN | FP | TN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| LLOV | 43 | 53 | 6 | 87 | 0,878 | 0,448 | 0,593 |
| TSan | 80 | 18 | 19 | 73 | 0,808 | 0,816 | 0,812 |

Auf 93 gemeinsam race-positiven Validierungskerneln melden beide 38, nur LLOV 5, nur TSan 38 und keines 12; Jaccard 0,469. TSan-Abwesenheit widerlegt ein statisches Race nicht, aber LLOV hat bei geringer Recall und nachgewiesenen False Positives keine ausreichende Evidenz für einen alleinigen harten Stop-Blocker.

### Die 18 berichteten `stopped_budget`-Fälle

Die Zahl 18 ist durch zwei Attributionseffekte überhöht:

- 6 gehören zur `test_feedback`-Strategie, in der LLOV nicht die Reparaturquelle ist;
- 3 Combined-Fälle hatten zusätzlich ein `validation_failed` und damit einen funktionalen Blocker.

Strategie- und statuskorrekt bleiben **9** Fälle, in denen ein LLOV-Race der einzige aufgezeichnete Stopgrund ist: 6 Static und 3 Combined.

| Variante | Modell / Benchmark |
|---|---|
| static | Fable / Dense LU; DeepSeek Pro / Dense LU; GPT-5.6 / Sparse LA; Qwen37 / Dense LU; Qwen36 / Search; DeepSeek Flash / Scan |
| combined | Fable / Dense LU; Gemini 3.6 / Dense LU; DeepSeek Flash / Scan |

Für diese neun gilt:

- alle Modelle änderten ihren Code als Reaktion auf die Iterationen;
- acht bestehen am Ende normales ParEval; 9/9 bestehen alle aufgezeichneten Enhanced-Specs;
- der neunte ist ein Sparse-Static-Fall mit normalem `validation_failed`, dessen 20/20 Enhanced-Pässe wegen der Sparse-Bugs nicht als Entlastung gelten;
- 9/9 haben einen erfolgreichen finalen TSan-Lauf ohne Modell-Finding;
- bei 5/9 ist ein LLOV-Blocking-Fund in jeder Iteration vorhanden; zwei folgen `LLOV → kein auswertbarer/kein Blocking-Fund → LLOV`, zwei Scan-Fälle `Buildfehler → LLOV → mehr LLOV`;
- die gemeldete Zeile verschiebt sich typischerweise nach Edits, obwohl die konzeptionelle Fundklasse gleich bleibt; reine `check_id+line`-Identität würde sie fälschlich als neu behandeln;
- es gibt keinen final nachgewiesenen funktionalen Schaden; ein Dense-LA-Fall regressierte zwischenzeitlich von Pass zu Buildfehler und wurde danach wieder zum Pass;
- die verbleibenden LLOV-Hinweise sind nicht dynamisch durch einen erfolgreichen TSan-Witness an derselben Quellstelle bestätigt.

Damit belegt der Pilot nicht, dass LLOV wertlos ist. Er belegt aber, dass LLOV-only in funktional korrekten Artefakten Budget verbrauchen und den Endstatus bestimmen kann, ohne hinreichend validierte harte Evidenz.

### Policyoptionen

| Option | Bewertung |
|---|---|
| A – Status quo: LLOV blockiert allein | nicht empfohlen; Toolfehler und False Positives können Repair und Stopstatus dominieren |
| **B – LLOV als Low-Confidence-Hinweis, nicht alleiniger Stop-Blocker** | **empfohlen**; der Hinweis bleibt im Feedback, kann aber bei sonst bestandener Correctness/Enhanced-Stufe nicht allein `stopped_budget` erzwingen |
| C – Race nur bei TSan-Witness oder mehrfacher Evidenz | zu streng; dynamische Nichtauslösung und TSan-Abdeckung würden echte statische Risiken verwerfen |
| D – confidence-gewichtete Eskalation | methodisch möglich, aber für den Full Run komplexer als B; erst mit separater Kalibrierung |

Empfehlung B ist eine Policyänderung und wird hier **nicht** implementiert. Wird sie für den Full Run übernommen, müssen betroffene OMP-Static-/Combined-Trajektorien des Piloten unter derselben Regel erneut gefahren oder aus dem direkten Vergleich ausgeschlossen werden. Unabhängig davon muss die Kreuztabelle künftig ausschließlich den gemeinsamen erfolgreichen Nenner ausweisen.

## 5. PARCOACH

### Vollständige Timeoutanalyse

Von 469 MPI-Artefaktläufen sind 310 erfolgreich und auswertbar, 84 scheitern beim Reduced-TU-Compile und 75 laufen exakt in das 60-s-Limit.

| Status | Artefakte | Anteil |
|---|---:|---:|
| erfolgreich auswertbar | 310 | 66,1 % |
| Reduced-TU-Compilefehler | 84 | 17,9 % |
| Timeout | 75 | 16,0 % |

Verteilung aller 75 Timeouts:

| Dimension | Verteilung |
|---|---|
| problem_type / benchmark | sparse_la 27, geometry 17, search 13, stencil 6, dense_la 5, sort 3, fft 2, transform 2 |
| model | GPT-5.6 13, Gemini 3.6 12, GPT-5.5 10, Qwen36 10, DeepSeek Pro 7, DeepSeek Flash 6, Opus 5, Qwen3 Coder 5, Fable 3, Gemini 3.1 2, Qwen37 2 |
| variant | initial/shared 19, static 23, test 9, combined 24 |
| iteration | 0: 19, 1: 37, 2: 19 |

Die 75 Fälle umfassen 71 unterschiedliche Code-Hashes. Vier identische Hashes treten je zweimal auf und timeouten bei beiden Wiederholungen. Alle Laufzeiten liegen zwischen 60,026 und 60,063 s. Das ist ein Toolprozess-Ceiling, keine breit streuende Docker-Startup-Latenz.

Quellmerkmale sind gegenüber 310 erfolgreichen Läufen stark angereichert:

| Merkmal | Timeout | erfolgreicher Lauf |
|---|---:|---:|
| `MPI_Allreduce` | 40,0 % | 9,7 % |
| Lambda | 40,0 % | 4,8 % |
| `while` | 21,3 % | 3,5 % |
| `MPI_Sendrecv` | 10,7 % | 0,6 % |

Alle stderr-Tails enthalten die PARCOACH-Meldung „no main“; 52/75 enthalten zusätzlich Warnungen zu nicht aufgelösten LLVM-/External-Funktionen, häufig `fmuladd.f64`, `ctlz` oder `is.constant`. Es gibt kein Docker-Crash-, Parser-Abort- oder Startup-Muster unmittelbar vor dem Timeout; vielmehr bleibt die eigentliche Analyse hängen.

### Isolierte 1×/2×-Kontrolle

Drei repräsentative Timeout-Artefakte wurden außerhalb der Pilotrecords mit read-only Workspace-Mount im identischen PARCOACH-2.4.1-Image `sha256:dbac7091e60b…` erneut analysiert:

| Artefakt | 60-s-Lauf | 120-s-Lauf | Findings |
|---|---:|---:|---:|
| GPT-5.6 Stencil MPI | 60,060 s Timeout | 120,096 s Timeout | 0 / 0 |
| GPT-5.5 Geometry MPI | 60,059 s Timeout | 120,097 s Timeout | 0 / 0 |
| DeepSeek Flash Sparse MPI | 60,060 s Timeout | 120,099 s Timeout | 0 / 0 |

Die stderr-Signaturen blieben gleich (`no main`; bei Geometry/Sparse zusätzlich fehlende `llvm.fmuladd`-Modelle). Eine Verdopplung des Limits würde diese Stichprobe nur doppelt so teuer machen. Es wurden keine Pilotrecords geschrieben oder verändert.

**Klassifikation:** A/D – erwartete Tool-/LLVM-Limitierung für bestimmte Quellmuster; diese Fälle sind `unsupported/inconclusive`. Das 60-s-Limit ist nicht zu aggressiv und sollte nicht erhöht werden.

### Separater Harness-Bug: Reduced TU

`thesis/evaluation/tools.py` erzeugt für PARCOACH und LLOV eine reduzierte Translation Unit mit nur `<vector>`, Utilities und Modellcode. Der echte Benchmark-Driver stellt jedoch weitere Standardheader wie `<algorithm>`, `<array>` oder `<complex>` bereit.

Von 84 PARCOACH-Compilefehlern:

- 59 Artefakte bestehen normale Correctness;
- 6 kompilieren normal und enden mit `validation_failed`;
- nur 19 scheitern auch im normalen Build.

Damit sind 65/84 PARCOACH-Compilefehler Harness-induziert. Der minimale Fix ist, die tatsächlich vom jeweiligen `cpu.cc` bereitgestellten Standardincludes in die reduzierte TU zu übernehmen, ohne Driverfunktionen oder Semantik einzukopieren. Derselbe Fix ist für LLOV erforderlich. Verbleibende alte-Plugin-/LLVM-Fehler werden explizit als `unsupported/inconclusive` klassifiziert.

PARCOACH-Timeouts und Compilefehler dürfen weder als „0 Findings“ noch als `clean` in Stopentscheidung oder Overview eingehen.

## 6. Repair Iteration Budget

### Beobachtete Trajektorie

| Stand | static | test | combined |
|---|---:|---:|---:|
| Initial ParEval-Pässe | 315/396 (79,5 %) | 315/396 (79,5 %) | 315/396 (79,5 %) |
| nach Iteration 1 | netto +12 | netto +20 | netto +9 |
| nach Iteration 2 | 328/396 (82,8 %) | 341/396 (86,1 %) | 333/396 (84,1 %) |

Die Übergänge zeigen Gewinn **und** Regression:

| Variante | Übergang | fail→pass | pass→fail | Netto |
|---|---|---:|---:|---:|
| static | 0→1 | 14 | 2 | +12 |
| static | 1→2 | 2 | 1 | +1 |
| test | 0→1 | 21 | 1 | +20 |
| test | 1→2 | 6 | 0 | +6 |
| combined | 0→1 | 18 | 9 | +9 |
| combined | 1→2 | 11 | 2 | +9 |

Diese Zahlen sind keine unverzerrte Schätzung eines dritten Repair-Schritts: Stencil- und Sparse-Oraclefehler verändern genau jene Correctness-Signale, auf die Test/Combined reagieren; sechs Sparse-Testgewinne lernen nachweislich die fehlerhafte Overwrite-Oracle und ein weiterer ist ein NaN-False-Pass.

### `stopped_budget` nach Iteration 2

„Funktional“ bezeichnet in der folgenden Tabelle den **beobachteten** normalen Correctness-Status. Ein Teil davon ist wegen Stencil/Sparse kein echter Modellfehler.

| Variante | stopped_budget | normal funktional nicht bestanden | normal pass | nur Toolblocker | funktional + Toolblocker | nur funktional | ausschließlich Low-Confidence |
|---|---:|---:|---:|---:|---:|---:|---:|
| static | 56 | 21 (18 validation, 2 build, 1 runtime) | 35 | 35 | 21 | 0 | 5 |
| test | 59 | 55 (52 validation, 2 build, 1 runtime) | 4 | 4 | 4 | 51 | 0 |
| combined | 104 | 63 (57 validation, 5 build, 1 runtime) | 41 | 41 | 34 | 29 | 3 |

Über alle 219 Endpunkte sind das 127 `validation_failed`, 9 `build_failed`, 3 `runtime_error` und 80 ParEval-Pässe. Verbleibende Blocking-Findings überlappen; am häufigsten sind GCC Analyzer 104, Clang-Tidy 36, LLOV 21, Infer 16, PARCOACH 12, TSan 11, Compiler 9, MUST 7 und Cppcheck 6.

Problemhäufungen:

- Static: scan 12, stencil 11, sparse_la 11, transform 6, fft 5, geometry 5, dense_la 4, search 2.
- Test: stencil 32, sparse_la 19, sort 5, dense_la 2, geometry 1.
- Combined: stencil 33, sparse_la 25, scan 12, geometry 9, transform 8, dense_la 6, fft 5, sort 4, search 2.

Damit sind die verbleibenden Budgets gerade in Test/Combined stark von den beiden nachgewiesen fehlerhaften Benchmarks geprägt. Tool-only-Fälle enthalten zusätzlich LLOV-only Stopps und Tool-Completeness-Probleme. Vor einer dritten Iteration muss daher die Messung repariert werden; sonst würde mehr Budget vor allem fehlerhafte oder niedrig-konfidente Signale optimieren.

Unter genau den späteren 219 Budgetendpunkten sinkt die Blocking-Zahl von Iteration 1→2 bei 64, steigt bei 52 und bleibt bei 103 unverändert. 12 wechseln funktional von Fail zu Pass; 121 ändern mindestens Verdict oder Blocking-Zahl. Es gibt also noch Bewegung, aber kein monotones Konvergenzsignal.

### Kosten und marginales Potenzial

Eine naive dritte Iteration für alle 219 Budgetfälle würde auf Basis der beobachteten Pilotkosten ungefähr verursachen:

| Variante | Kandidaten | zusätzliche API-Kosten, geschätzt | zusätzliche aggregierte Analysezeit, geschätzt |
|---|---:|---:|---:|
| static | 56 | ca. $2,23 | ca. 2,37 h |
| test | 59 | ca. $2,55 | ca. 2,16 h |
| combined | 104 | ca. $4,00 | ca. 4,12 h |
| **Gesamt** | **219** | **ca. $8,78** | **ca. 8,65 h** |

Das sind Größenordnungen aus dem Pilot, keine Preisgarantie; Wall-clock-Orchestrierungszeit und Wiederholungen kommen hinzu. Der wissenschaftliche Einwand ist wichtiger als die absolute Summe: Der marginale Static-Gewinn fällt von netto +12 auf +1, der Testgewinn von +20 auf +6. Combined bleibt netto +9, bezahlt dies aber mit 9 beziehungsweise 2 Regressionen und ist besonders von fehlerhaften/Tool-only Signalen belastet.

Als preisunabhängige Größenordnung: Der Pilot verbrauchte für 715 Repairaufrufe 1.103.354 Prompt- und 2.180.350 Completion-Tokens. Eine dritte Iteration für 219 Endpunkte entspräche bei Pilotmitteln etwa +219 Calls (+30,6 %), +338.000 Prompt- und +668.000 Completion-Tokens, jeweils zuzüglich der vollständigen Compile-/Tool-/Correctness-/Enhanced-Auswertung.

**Empfehlung: `max_iterations = 2` beibehalten.** Nach den Pflichtfixes ist zunächst ein fokussierter Re-Pilot unter korrekter Semantik auszuwerten. Nur wenn dessen Übergang 1→2 noch klar positive, valide Correctnessgewinne bei niedriger Regression zeigt, sollte eine separate Iterations-3-Studie erwogen werden.

## 7. Statically Clean but Incorrect

### Rohbefund

Static endet bei 340/396 Samples mit `stopped_clean`. Darunter:

- 47/340 = 13,8 % normales ParEval-incorrect;
- 57/340 = 16,8 % mit mindestens einem Enhanced-`fail/crash/timeout/build_failed`;
- 28 erfüllen beides.

Von den 47 normalen Fehlern sind 46 `validation_failed` und einer `runtime_error`.

| Problemtyp | ParEval-incorrect | Enhanced-bad |
|---|---:|---:|
| stencil | 22 | 22 |
| sparse_la | 17 | 1 |
| dense_la | 3 | 1 |
| geometry | 1 | 21 |
| reduce | 1 | 5 |
| search | 1 | 3 |
| sort | 1 | 3 |
| transform | 1 | 1 |

| Execution Model | ParEval-incorrect | Enhanced-bad |
|---|---:|---:|
| serial | 20 | 17 |
| omp | 18 | 21 |
| mpi | 9 | 19 |

| Modell | ParEval-incorrect | Enhanced-bad |
|---|---:|---:|
| claude_fable_5 | 3 | 4 |
| claude_opus_5 | 5 | 5 |
| deepseek_v4_flash | 5 | 5 |
| deepseek_v4_pro | 3 | 7 |
| gemini_31_pro | 4 | 3 |
| gemini_36_flash | 4 | 5 |
| openai_gpt55 | 2 | 5 |
| openai_gpt56_sol | 4 | 6 |
| qwen36_35b_a3b | 5 | 5 |
| qwen37_max | 4 | 7 |
| qwen3_coder_api | 8 | 5 |

Der Befund ist also nicht auf ein Modell oder Execution Model beschränkt. Stencil und Sparse erklären 39/47 normale Fehler, allerdings aufgrund der nachgewiesenen Oraclebugs. Die verbleibenden Fälle und die breit verteilten Enhanced-Edge-Case-Fails sind überwiegend algorithmische/logische Fehler: falsche Randbehandlung, falsche Such-/Sortierlogik, falsche Spezialfallbehandlung oder funktional falsche Parallelalgorithmen. Solche Fehler liegen außerhalb dessen, was die verwendeten statischen Werkzeuge zuverlässig beweisen.

### „Clean“ ist in 74 Fällen nicht tool-vollständig

Bei 74/340 finalen `stopped_clean`-Artefakten ist mindestens ein anwendbares externes statisches Tool nicht erfolgreich:

- PARCOACH: 19 Timeouts und 25 Reduced-TU-Compilefehler;
- LLOV: 22 Exit-1-Compilefehler und 8 Exit-254-Plugincrashes.

Dasselbe Completeness-Problem betrifft 65 als clean bezeichnete Combined-Endpunkte und einen `stopped_tests_pass`-Endpunkt. Die genaue Fehlerart unterscheidet sich, die Semantik ist dieselbe: fehlende Toolinformation wurde nicht von einem erfolgreichen Null-Finding-Lauf getrennt.

Alle internen statischen Tools liefen in diesen 340 Fällen, aber die externe Abdeckung ist nicht vollständig. Der Fehlerpfad ist eindeutig:

- `thesis/repair/orchestrator.py::pending_external` prüft nur, ob der Tool-Key vorhanden ist;
- `thesis/repair/feedback.py::collect_findings` und `orchestrator.py::evaluate_stop` zählen Findings, ignorieren aber `error` ohne Findings;
- `thesis/analysis_overview/build_overview.py` schreibt für `ran=true` selbst bei Fehler `num_blocking=0`.

Beispielhaft besitzt ein Histogram-MPI-Record von `openai_gpt55` einen PARCOACH-Exit 1 mit `clang -emit-llvm failed for the reduced TU`, erscheint im Overview aber als `parcoach_blocking=0` und `stopped_clean`.

Mit strengem Success-Predicate — anwendbar, `ran == true`, `error is None` und kein Timeout — bleiben 266 vollständig untersuchte Static-Clean-Fälle:

- 43/266 = 16,2 % ParEval-incorrect;
- 42/266 = 15,8 % Enhanced-bad;
- 26 erfüllen beides.

Nach Entfernen der fehlerhaften Tool-Completeness-Zuordnung wird der qualitative Befund somit **nicht schwächer**. Die korrekte Aussage lautet:

> 340 Artefakte hatten keinen aufgezeichneten Blocking-Fund; 266 davon hatten vollständige erfolgreiche Abdeckung aller anwendbaren statischen Tools. Auch in dieser strikten Teilmenge bleiben 16,2 % ParEval-incorrect und 15,8 % Enhanced-bad.

Das Thesis-Ergebnis „statisch ohne Finding bedeutet nicht funktional korrekt“ ist methodisch belastbar. Nicht belastbar sind die Bezeichnung aller 340 als vollständig „clean“ und die Stencil/Sparse-spezifischen Anteile vor deren Re-Pilot.

## 8. Data Integrity

### Vollständigkeit und Identität

| Prüfung | Ergebnis |
|---|---|
| Initialsample-Kreuzprodukt | **bestanden:** exakt 11 Modelle × 12 Benchmarks × 3 Execution Models = 396 |
| Initialgenerationen | **bestanden:** keine fehlende Generation; je Modell 36 |
| Assembly/Correctness/Static/Dynamic | **bestanden:** für alle erwarteten Basis- und erzeugten Iterationsartefakte vorhanden |
| Enhanced | **bestanden strukturell:** 1.111 Artefakte × 20 eindeutige `spec_key` = 22.220 Rows |
| Overview | **bestanden:** 1.903 Rows, 1.903 eindeutige `(sample_id, variant, iteration)`, `incomplete=0` |
| Overview-Komposition | 396 Initialartefakte als drei Variantenansichten = 1.188 Rows plus 715 tatsächlich erzeugte Repairrows |
| Carry-Forward | **bestanden:** aktive Zustände verweisen exakt auf vorhandene nächste Iterationsartefakte; keine Lücke wird nur durch Carry-Forward verdeckt |
| gemischte Runs/Modelle | **keine:** `run_id`, Modell, Variante und Sampleidentität stimmen |
| Duplicate Records | **keine** in Generation, Evaluation, Tools, Enhanced oder Overview für die jeweiligen natürlichen Schlüssel |
| Resume/alte Artefakte | **kein Hinweis:** keine verwaisten aktiven Zustände oder übernommenen Fremdrecords |
| JSONL | **bestanden:** keine ungültigen Records |

`incomplete: 0` ist damit als **strukturelle Record-Vollständigkeit** korrekt. Es bedeutet aber nicht, dass jedes Tool erfolgreich Information geliefert hat. Die 74 False-clean-Fälle zeigen, dass Toolfehler derzeit semantisch nicht als „information missing“ propagiert werden.

### Manifest, Config, Git und Spec-Hash

- Die kanonische aktuelle Config stimmt mit der eingefrorenen Base-Manifest-Config überein; alle Kindläufe verwenden dieselbe Config und denselben Enhanced-Spec-Verweis.
- Der eingefrorene Enhanced-Spec-SHA ist `0fe9561e13504ef8a2dd6455711628a6e8512848e9347e5576a02d777d0e1874` bei 483 Specs und stimmt mit dem aktuellen frozen cache überein.
- Das Base-Manifest referenziert Git-Commit `6846d689…` und einen sauberen Worktree. Der aktuelle HEAD ist `912133…`; der relevante Unterschied besteht in hinzugefügten Analyseoutputs, nicht in einer stillen Änderung der gemessenen Harnessquellen.
- Die Pilotrecords enthalten keine Daten aus einem anderen `run_id`.

Zwei Provenanzschwächen sind vor dem Full Run zu beheben:

1. Iterations-Kindmanifeste werden teilweise erst in Analyse-/Containerpfaden erzeugt, weil der Orchestrator `assemble_model` direkt aufruft. Iteration-1-Manifeste enthalten deshalb `git_commit/git_dirty = null`; Iteration 2 enthält zwar den Base-Commit, aber `dirty=true`. Die Records sind intern konsistent, die Provenanz ist jedoch unnötig schwach.
2. `toolchain_versions` und Compiler-Version sind im Base-Manifest null, obwohl `toolchain-versions.txt` Versionen enthält. Container-Tags, insbesondere LLOV, sind nicht durchgehend als immutable Digests eingefroren.

Minimal ist, Kindmanifeste auf dem Host vor jeder Wave zu erzeugen und Git-Commit, Dirty-Status, Config-/Spec-Hash, Toolversionen sowie Container-Image-Digests zu persistieren. Dies ändert keine Pilotverdicts und erfordert für `pilot_001` keinen Rerun, ist aber für die Full-Run-Reproduzierbarkeit erforderlich.

### Python 3.8

Das Base-Manifest zeichnet für den Hostlauf Python 3.14.5 auf; LLOV läuft dagegen im Python-3.8-Container. Die produktiven Harnesspfade wurden deshalb zusätzlich syntaktisch auf Python 3.8 geprüft; die vorgeschlagenen Fixes sind ohne `match`, PEP-604-Unions oder andere neuere Syntax implementierbar. Zwei alte vendorte MBI-Generatoren enthalten neuere Syntax, liegen aber nicht auf dem produktiven Pilotpfad. Regressionstests müssen dennoch explizit unter Python 3.8 oder dem eingefrorenen Python-3.8-Container laufen.

### Teststatus

Die bestehenden Testgruppen für Evaluation, Orchestrator, Overview und Enhanced bestanden. Sie decken den zentralen Fall „`ToolResult.error` bei `ran=true` darf nicht clean sein“ sowie NaN-Oracles, wirkungslose Fill-Sites und Validation-only derzeit nicht ausreichend ab; dafür sind gezielte Regressionstests Pflichtbestandteil der Fixes.

## Required Changes Before Full Run

Die folgenden Änderungen sind durch konkrete Pilotfehler begründet. Sie sollen erst nach Review dieses Berichts implementiert werden. Bestehende `pilot_001`-Dateien bleiben unverändert; korrigierte Ergebnisse erhalten einen neuen Run-/Spec-Namespace.

| ID | Datei/Funktion | genaue Ursache | minimaler Fix | beeinflusst Pilotdaten? | Pilot nach Fix wiederholen? | wissenschaftliche Vergleichbarkeit |
|---|---|---|---|---|---|---|
| R1 | `drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/baseline.hpp::correctCellsXOR`; Stencil-Promptquelle | Oracle zählt 4, Aufgabe/Beispiel 8 Nachbarn | Diagonalen in Referenz aufnehmen; Prompt auf acht Nachbarn einschließlich Diagonalen explizieren | ja, alle Stencil-Correctness-/Repairverdicts | **ja**, alle 33 Stencil-Samples und ihre Varianten | alte und neue Stencil-Verdicts nicht poolen; frozen Pilot als Bugbefund erhalten |
| R2 | `drivers/cpp/benchmarks/stencil/50_stencil_xor_kernel/cpu.cc::validate` | nur Interior, unsigned Underflow bei N=0, keine Mismatchdiagnostik | vollständigen Vektor mit `reportAndCompareEq` prüfen | ja, Normal und Enhanced Stencil | **ja**, zusammen mit R1 | gleiche Tasksemantik, aber größere korrekte Testabdeckung |
| R3 | `drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/baseline.hpp::correctSolveLinearSystem`; Sparse-Promptquelle | `b` summiert COO-Duplikate, Oracle überschreibt; Prompt schweigt | `=` zu `+=`; additive Duplicate-Semantik im Prompt festlegen | ja, alle Sparse-Correctness-/Repairverdicts | **ja**, alle 33 Sparse-Samples und Varianten | alte Overwrite- und neue additive Semantik nicht vergleichen |
| R4 | `drivers/cpp/benchmarks/sparse_la/45_sparse_la_sparse_solve/cpu.cc::validate` | NaN/Inf passieren `abs(diff)>eps` | Referenz und Candidate lokal per `std::isfinite` prüfen; nicht-finite Candidate-Ausgabe fail, nicht-finite Oracle Harnessfehler/gate | ja, mindestens 5 Initial-False-Pässe und spätere Repairs | **ja**, zusammen mit R3 | verhindert False-Pässe; globale FP-Semantik bleibt sonst unverändert |
| R5 | `thesis/evaluation/run_enhanced_tests.py::precompute_gates` und Sparse-Enhanced-Inputerzeugung | Sparse-Oracle aller positiven Pilotgrößen nicht-finite; Gate NaN-blind | nicht-finite Oracle als `baseline_incompatible`; deterministisch nonsinguläre Systeme mit bekannter Lösung erzeugen | ja, 181 Artefakte/3.620 Rows | **ja**, Enhanced Sparse vollständig | neuer Spec-Hash; alte Sparse-Enhanced-Pässe sind ungültig |
| R6 | `thesis/enhanced_tests/specs.py::validate_spec/build_benchmark_specs` | Pattern werden trotz `fill_sites: 0` zugelassen | nur size-only/random zulassen oder non-random als unsupported kanonisieren; `spec_key`-Feld/Schema unverändert lassen | ja, 252 Artefakte/5.040 Rows | **ja**, Graph/Reduce/Sparse Enhanced | Patternanalysen erst ab korrigiertem Specset; neuer Hash |
| R7 | `thesis/evaluation/run_enhanced_tests.py::launch_command`; `drivers/cpp/models/{serial,omp,mpi}-driver.cc` | nach Validation läuft fremder Performance-Workload | `ENHANCED_VALIDATION_ONLY` und sauberer früher Return; MPI auf allen Ranks finalisieren | ja, mindestens 40 sicher falsche Status; 380 phasenambig | **ja**, gesamte Enhanced-Stufe | alte Crash-/Timeout-Raten nicht mit korrigierten mischen |
| R8 | `thesis/evaluation/run_enhanced_tests.py::process_sample` | Enhanced-Includes können Modell-Buildfehler maskieren | normalen Correctness-Build als autoritativen Preflight verwenden | ja, 1 Artefakt/20 Rows im Pilot; weitere im Full Run möglich | Enhanced neu rechnen; kein Generationsrerun allein hierfür | Modellfehler bleibt Modellfehler, keine implizite Reparatur |
| R9 | `thesis/repair/orchestrator.py::pending_external/evaluate_stop`; `thesis/repair/feedback.py::collect_findings`; `thesis/analysis_overview/build_overview.py` | `ran=true,error!=None` wird als 0 Findings/clean behandelt | einheitliches Success-Predicate; Fehler/Timeout als fehlende Information, nie 0; bounded retry ohne Toolfehler als Modellfeedback; nach Ausschöpfung bestehendes incomplete/budget-Reporting statt clean | ja, mindestens 74 Static-clean; 65 Combined-clean; weitere Attributionen | **ja**, Static und Combined zumindest für alle betroffenen Pfade; bevorzugt vollständiger fokussierter Strategierepilot | exakte `clean`-Nenner und Trajektorien ändern sich; qualitative Sensitivitätsanalyse separat berichten |
| R10 | `thesis/evaluation/tools.py::ParcoachTool/LLOVTool` | reduzierte TU fehlen vom realen Driver bereitgestellte Standardincludes | benchmark-spezifische Standardincludes aus `cpu.cc` übernehmen, ohne Driverlogik zu kopieren | ja, 65 normal kompilierbare PARCOACH-Fälle und zahlreiche LLOV-Fälle erhalten erstmals Toolinformation | **ja**, externe Static-Tools und davon abhängige Static/Combined-Repairs | vorherige „kein Finding“-Werte waren fehlende Daten; nicht als Null fortschreiben |
| R11 | LLOV-Konfidenz in Repair-Konfiguration/`evaluate_stop` | LLOV-only stoppt trotz geringer validierter Recall und nachgewiesener FPs; 9 echte sole-blocker Budgets | nach Policyfreigabe Option B: LLOV als Low-Confidence-Hinweis behalten, aber nicht allein `stopped_budget` erzwingen, wenn Correctness/Enhanced bestanden sind | ja, mindestens 9 finale Fälle und frühere OMP-Trajektorien | **ja**, betroffene OMP-Static-/Combined-Pfade | Policywechsel klar versionieren; alte/neue Repairergebnisse nicht direkt poolen |
| R12 | `thesis/evaluation/run_manifest.py` und Aufrufreihenfolge in `thesis/repair/orchestrator.py` | Kindmanifeste werden zu spät erzeugt; Tool-/Imageversionen unvollständig | Manifest vor jeder Wave auf Host einfrieren; Commit, Dirty, Config-/Spec-SHA, Toolversionen und immutable Image-Digests persistieren | nein, keine Verdicts | nein | verbessert Provenanz ohne Ergebnisänderung |
| R13 | Regressionstests in `thesis/evaluation/test_evaluation.py`, `thesis/repair/test_orchestrator.py`, `thesis/analysis_overview/test_overview.py` und `thesis/enhanced_tests/test_enhanced.py` | nachgewiesene Fehlerpfade sind nicht abgedeckt | Tests für NaN/Inf, Toolerror≠clean, gemeinsame Toolnenner, `fill_sites:0`, normal-build preflight und validation-only; unter Python 3.8 ausführen | nein, aber schützt Full Run | nein, zusätzlich zu den fachlichen Re-Pilots | verhindert erneute stille Semantikdrift |

### Erforderliche Re-Pilot-Sequenz

1. R1–R10 und R12–R13 implementieren und reviewen; R11 als explizite Policyentscheidung freigeben oder mit begründeter Abweichung dokumentieren.
2. Neue Config-/Prompt-/Spec-Hashes und immutable Containerdigests erzeugen; `pilot_001` nicht überschreiben.
3. Stencil und Sparse LA von der Generation beziehungsweise mindestens vom unveränderten Promptartefakt aus vollständig durch alle drei Varianten neu führen. Wegen Promptpräzisierungen ist eine Neugeneration wissenschaftlich sauberer.
4. Static/Combined unter korrekter Tool-Completeness und der beschlossenen LLOV-Regel fokussiert neu führen; Test nur soweit Stencil/Sparse oder andere Upstreamfixes betroffen sind.
5. Enhanced für alle 1.111 vorhandenen beziehungsweise neu erzeugten Artefaktversionen vollständig in einem neuen Namespace rechnen.
6. Dieselben Integritäts- und Sensitivitätschecks erneut ausführen. Erst bei `incomplete=0` **und** explizit ausgewiesener Tool-Completeness lautet die Entscheidung „GO WITH FIXES“.

## Optional Improvements

- Crash-/Timeout-stdout und stderr-Tails sowie eine explizite Phase (`build`, `validation`, `post-validation`) persistieren. Dies ist additiv und ändert kein Verdict.
- Manuelle Validatoren schrittweise auf strukturierte Mismatchdiagnostik umstellen; aktuell fehlen Details bei 1.771/2.072 Enhanced-Fails.
- Nach dem risikoarmen `fill_sites:0`-Gate driver-spezifische Graph-/Reduce-Hooks prüfen. Für Sparse nur eine invariantenbewahrende Systemerzeugung verwenden.
- Transiente externe Toolfehler begrenzt wiederholen und Wiederholungsanzahl/Dauer berichten; persistente Parser-/LLVM-Limits als `unsupported/inconclusive` cachen.
- Einen globalen NaN/Inf-sicheren FP-Comparator erst nach benchmarkweiter Auswirkungsanalyse einführen. Für den Full Run genügt der nachgewiesene lokale Sparse-Fix plus Enhanced-Gate.
- Nach dem korrigierten Re-Pilot optional eine kleine, vorab definierte Iteration-3-Ablation durchführen, statt `max_iterations` im Full Run pauschal zu erhöhen.

## No Change Recommended

- **Keine numerische Toleranz lockern.** Die auswertbaren Abweichungen sind strukturell groß; es gibt keinen Rundungskandidaten.
- **`max_iterations = 2` beibehalten.** Eine dritte Iteration kompensiert derzeit hauptsächlich Oracle-/Toolfehler und liefert bei Static nur noch netto +1.
- **PARCOACH-Timeout bei 60 s beibehalten.** Drei 120-s-Kontrollen lieferten ebenfalls keine Ergebnisse.
- **Keine Forderung nach LLOV/TSan-Übereinstimmung.** Die Tools messen unterschiedliche Evidenz; nur ihr Erfolgsstatus und die Confidence müssen korrekt behandelt werden.
- **Keine legitimen Modellfehler „wegfixen“.** Dazu gehören 28 normal und Enhanced nicht kompilierbare Artefakte, direkte MPI-Collective-Hänger/Crashes und die nach Bereinigung verbleibenden algorithmischen Enhanced-Fails.
- **Die 96 normal-passenden Artefakte mit echten held-out Enhanced-Fails nicht entfernen.** Nach Ausschluss der nachgewiesenen Kontamination sind solche Edge-Case-Funde ein gewünschtes Messergebnis.
- **Keine Änderung an Record-Schemas, Feedbackvarianten, Toolkonfigurationen oder `spec_key`-Semantik.** Die Pflichtfixes können mit bestehenden Feldern und klar versionierten neuen Spec-Inhalten umgesetzt werden; die eingefrorenen Pilotdaten bleiben unverändert.
