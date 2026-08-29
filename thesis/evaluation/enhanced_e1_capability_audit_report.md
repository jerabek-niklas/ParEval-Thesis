# Enhanced E1 — Capability Audit Report

Read-only Audit-Wave (E1) der Enhanced-Test-Infrastruktur. **Keine
produktive Enhanced-/Benchmark-Semantik wurde geändert**; E2
(Implementierung) und E3 (Spec-Regeneration) sind NICHT Teil dieser Wave.

## 1. Provenance

| Feld | Wert |
|---|---|
| Repository / Branch | `jerabek-niklas/ParEval-Thesis` / `thesis-static-analysis` |
| Start-HEAD | `509f08e63e1ab697bbaef874c0222f2c79e9372a` ("fixes 10"; Parent `5b22343…`) |
| Working Tree bei Start | clean |
| Datum | 2026-08-28 |
| Cross-Pilot-Checker vor E1 | Exit 0 (fresh) |
| Audit-Basis | aktueller Sourcecode aller 60 `drivers/cpp/benchmarks/**/cpu.cc` (+ baseline.hpp), `drivers/cpp/enhanced-fill.hpp`, `thesis/enhanced_tests/{specs.py, generate_test_specs.py, benchmark_shapes.json}`, `thesis/evaluation/run_enhanced_tests.py`, `config stages.enhanced_tests`, `thesis/results/cache/enhanced/specs.jsonl` (read-only), `pilot_readiness_review.md` |

Deliverables: **[enhanced_capabilities.json](thesis/enhanced_tests/enhanced_capabilities.json)**
(autoritativer 60-Benchmark-Katalog, Top-Level `"status": "AUDIT_ONLY_NOT_ENFORCED"`) und dieser Report.

## 2. Scope

Reines Source-Audit plus zwei Scratch-Verifikationen (Container-`decltype`/
Conversion-Probe; Key-Format-Check von `benchmark_shapes.json`). Kein
Produktivfile geändert, keine Specs geschrieben, keine Config geändert,
keine Results-Pfade beschrieben, keine UBSan-/ASan-/4096er-Matrix, keine
Adapter implementiert.

## 3. Historische W10-Einordnung

**HISTORICAL_W10_FINDING** (`pilot_readiness_review.md`, Befund B / R6):
Im Pilot-Enhanced-Lauf trugen graph/reduce/sparse_la Patternlabels ohne
Inputwirkung — **252 Artefakte, 5.040 Rows, 2.489 redundante Pattern-Rows =
22,7 %** aller Enhanced-Rows; empfohlener Fix R6 (Pattern-Gating bei
`fill_sites == 0`) ist bis heute **nicht implementiert**.

**CURRENT_E1_AUDIT_FINDING** (getrennt gehalten, andere Population): Die
strukturelle Ursache besteht fort und betrifft **11** Benchmarks
(`fill_sites == 0`); die aktuelle Specdatei (483 Specs, alle `source=llm`)
enthält darauf **49 non-random Pattern-Specs ≈ 10,1 %** des Spec-Budgets.
Historische Row-Zahlen und aktuelle Spec-Zahlen sind nicht dieselbe Metrik
und werden nicht vermischt.

## 4. 60-Benchmark Capability Summary

| Achse | EFFECTIVE | PARTIAL | NONE | NOT_APPLICABLE | UNKNOWN |
|---|---:|---:|---:|---:|---:|
| SIZE_OVERRIDE_EFFECT | **60** | 0 | 0 | 0 | 0 |
| PATTERN_EFFECT | **46** | **3** | **10** | **1** | 0 |

PARTIAL: dense_la/02 und /04 (deterministische Nonsquare-Shape-Probes per
`fillRand` außerhalb der Patternachse — dokumentiertes Design), sparse_la/46
(A8/I13-Nonsquare-Probe ungepatternt). NOT_APPLICABLE: histogram/23
(Stringinput). NONE: die 11 Fill-Site-freien Benchmarks minus 23 = 10.
`PATTERN_SOURCE`: ENHANCED_FILL für alle 49 EFFECTIVE/PARTIAL; NONE für die
11 (kein CUSTOM_EXISTING-Patternpfad existiert; BENCHMARK_ADAPTER ist
ausschließlich E2-Vorschlag, nirgends implementierter Zustand).

## 5. Fake-Diversity-Befund (P1-Kern)

11 Benchmarks, bei denen gleiche Größe + unterschiedliches Pattern
strukturell denselben relevanten Input erzeugen
(**STRUCTURALLY_NO_PATTERN_EFFECT** — bewusst NICHT als
PROVEN_INPUT_DUPLICATE deklariert, da ohne Ausführung nicht byte-bewiesen):

`dense_la/01`, `graph/15–19`, `histogram/23`, `reduce/25`, `sort/44`,
`sparse_la/45`, `sparse_la/49` — die bekannte Mindestmenge wurde bestätigt
und um `dense_la/01` erweitert; suiteweit wurden keine weiteren gefunden.
Aktuell tragen diese Benchmarks **49 non-random Pattern-Specs** (Detail im
Katalog `current_fake_diversity`), z.B. graph/15 mit 10/10 non-random
(all_same/all_zeros/extreme_values auf Adjazenzmatrix), sparse_la/49 11/12.
Diese Specs zählen per `spec_key` als distinkte Testfälle, obwohl der
Patternparameter den Input nie erreicht — sie dürfen nicht als
Testdiversität gewertet werden.

## 6. ENHANCED_FILL Type Audit

**70 Fill-Sites** suiteweit erfasst (Katalog `fill_sites` je Benchmark).
Kernmechanismus (per Container-Probe verifiziert, g++ 13.3 -O3): der
Template-Parameter `DType` wird aus den **lo/hi-Argumenten** deduziert,
nicht aus dem Container-Elementtyp; Patternwerte entstehen in DType und
werden per Zuweisung implizit konvertiert.

**5 typunsichere Sites (TYPE_SAFE = false):**

| Benchmark | Site | Container | deduzierter DType | Problem |
|---|---|---|---|---|
| reduce/28 | cpu.cc:63 | `vector<int>` | double (`0.0, 100.0`) | extreme/spike: DBL_MAX-Skala → double→int **UB** |
| scan/31 | cpu.cc:59 | `vector<float>` | double (`-100.0, 100.0`) | DBL_MAX → double→float **UB** |
| sort/42 | cpu.cc:127 | `vector<float>` | double | dito; inf-Werte werden von validRanks ungeprüft benotet |
| sort/43 | cpu.cc:156 | `vector<float>` (value-Feld) | double | dito; inf feuert zusätzlich non_finite_reference → BI-only |
| stencil/54 | cpu.cc:75 | `vector<int>` | int | Konversion sicher, aber extreme_values (INT_MIN/MAX) → **signed-overflow-UB im Oracle** (Raw-8-Nachbar-Summe, baseline.hpp:27-51) |

Alle übrigen 65 Sites: Literaltypen passen zum Elementtyp (double→double,
int→int) — kein Konversions-UB. Runtime- und Define-Pfad teilen die
Deduktion; nur der value_range-Override saturiert (Runtime) bzw.
constant-foldet (Define) — die Pattern-eigenen Extremwerte laufen an
Mismatch-Sites in beiden Modi in dieselbe UB-Konversion.

## 7. Type-Safe vs. Domain-Valid (getrennte Achsen)

Der Katalog führt beide Achsen pro Pattern getrennt. Suiteweite Muster:
**BI-only-Klasse** (typesafe, aber Pattern trifft deterministisch Tripwire/
non-finite-Reference → Kandidat wird nie benotet): extreme_values+spike_at
auf histogram/20/21/24, scan/33, stencil/51; extreme_values auf
fft/05/07/08/09 (Butterfly→inf/NaN, **vakuoser Pass**), dense_la/00/02/03/04,
sparse_la/46 (+47 teilweise), stencil/52/53 (Interior), reduce/26
(all_zeros→0·Inf=NaN deterministisch BI). **Oracle-UB-Klasse** (Pattern
löst UB im Oracle selbst aus): scan/34 (`currSum += x[j]` signed overflow —
Guard-Asymmetrie zu 33!), stencil/54, transform/58 (`x*x`), fft/05
(Heap-OOB bei non-power-of-two N≥3 — von der Spec-Ebene angebotene Größe 7
ist dort bereits UB!). **Tolerance-Cliff-Klasse** (typesafe+domainfrei,
aber absolute ε 1e-4/1e-6 gegen ~1e307-Magnituden → deterministische
False-FAILs für korrekt reassoziierende parallele Kandidaten): reduce/27/29,
dense_la/00/02/04-Spike-Reste, stencil/52/53-Spike, fft-Spike, geometry/10/12.

## 8. reduce/28 Deep Dive (P0-Referenzfall)

`std::vector<int> x(TEST_SIZE)` (cpu.cc:54) + `ENHANCED_FILL(x, 0.0, 100.0)`
(cpu.cc:63) → deduzierter DType **double** (Container-Probe). Wirkung je
Pattern: random/ramps/all_same/alternating erzeugen in-range-Doubles →
definierte Truncation (0..100); **extreme_values** erzeugt ±DBL_MAX,
**spike_at** DBL_MAX/2 → out-of-range double→int = **UB** (beobachtet:
Saturierung auf INT_MIN/INT_MAX — nicht garantiert). Der Wave-2B-Tripwire
(cpu.cc:76-89: `x[j]<0 || x[j]==INT_MAX` → BI) feuert erst NACH der
UB-Konversion und macht beide Patterns 100 % baseline-gate-only. Zusätzlich:
INT_MAX-Sentinel-Kollision (Fold-Identität == legaler odd-Wert) und die
explicit_values-Specs des Bestands verletzen die frozen Domain (negative
Werte). Runtime-/Define-Pfad gleich betroffen. **E2-Optionen** (nicht
entschieden): (a) FIX_FILL_SITE_TYPES `ENHANCED_FILL(x, 0, 100)` (DType=int;
extreme bleibt domain-invalid/BI-only, spike INT_MAX/2 wird valider
odd-Wert); (b) harnessseitig DType aus `container::value_type` deduzieren
(suiteweiter Fix, größerer Eingriff); (c) Pattern-Exclusion per Capability.

## 9. NO_FILL_SITE Summary

11 Benchmarks (Liste in §5), alle mit **EFFECTIVE size variation** — kein
Benchmark wurde pauschal als "Enhanced unsupported" klassifiziert; Size- und
Patternachse sind im Katalog getrennt. `benchmark_shapes.json` wurde für
alle 60 gegen den Code verifiziert (alle fill_sites-Angaben korrekt; der im
Pipeline-Audit aufgekommene Verdacht auf Backslash-Keys wurde geprüft und
ist **falsch** — 60/60 Forward-Slash-Keys, der explicit_values-Gate ist
funktionsfähig).

## 10. histogram/23 Referenzfall

Stringinput via `fillRandString` (bewusst ungewrappt) + rand()-Erstbuchstabe.
Numerische Patternbegriffe (ascending/extreme_values/spike_at) haben ohne
neue Semantik keine Bedeutung → **PATTERN_EFFECT = NOT_APPLICABLE**,
**ADAPTER_FEASIBILITY = NOT_MEANINGFUL** für globale numerische Patterns,
Empfehlung **NO_PATTERN_SUPPORT_RECOMMENDED + size-only variation** — der
Maßstabsfall für „ehrlich keine Patternvariation" statt künstlicher
Übertragung. (Bestand: 2 non-random Specs all_same/ascending → inert.)

## 11. graph/15–19

Alle EFFECTIVE size (Spec-size = Knotenzahl N, Elemente N²), alle NONE
pattern (custom {0,1}-Adjazenzbauer: 15 gerichtet mit Self-Loops, 16/17/18
symmetrisch/nulldiagonal, 19 spanning-path-verbunden + Skalare). Native
Freiheitsgrade existieren (Dichte p, geplante Komponenten-/Gradprofile,
Diameter; 18 profitiert am meisten — Default p=0,5 liefert fast immer genau
1 Komponente), erfordern aber ein eigenes Graph-Pattern-Vokabular →
**POSSIBLE_BUT_POLICY_NEEDED** (5×); „ascending graph" u.ä. wurde bewusst
nicht erfunden. Zusatzbefunde: 17-Oracle summiert Rohzellen (out-of-domain
wäre UB), Kantentest-Divergenz (==1 vs. truthy vs. Summe) als latente
Semantikfrage; **19 hat Live-Size-Hazards bei den angebotenen statischen
Größen 0/1** (size_t-Underflow-Loop, mod-0, Endlosschleife) → P0.

## 12. sort/44

`fillRandWithZeroes` (bewusst ungewrappt) — Zero-Dichte/-Positionen sind
bereits die aufgabenrelevante Struktur. Adapter (zero density/placement/
non-zero arrangement) wäre semantisch eindeutig ableitbar:
**POSSIBLE_BUT_POLICY_NEEDED**; globale numerische Patternnamen passen nicht.

## 13. sparse_la/45 und /49

Vollständige Konstruktionsdokumentation im Katalog: 45 baut das frozen
D4-Dominantsystem (COO-Topologie + Werte + b aus bekannter Lösung x_gen),
49 die frozen D5-Exakt-LU (pivotfreie Minoren, dense L/U-Ground-Truth) —
beide rand()-getrieben, ein generischer Fill würde die unabhängig benotete
Ground-Truth falsifizieren bzw. Gültigkeitsinvarianten (Nichtsingularität,
Minoren) brechen. Ein konstruktionsbewusster Adapter über die dokumentierten
freien Achsen (Topologie-Lattice, Werteverteilung innerhalb der
Dominanz-/Minoren-Constraints, RHS) ist möglich:
**POSSIBLE_BUT_POLICY_NEEDED** (beide). „ascending = sortierte Sparse-Werte"
oder „spike_at = großer Matrixwert" wurde ausdrücklich NICHT als
automatisch methodisch richtig behandelt (Singularitäts-/BI-/Schwierigkeitsfragen offen).

## 14. D6b-/domain-sensitive Summary

Geprüfte sensible Reihe (28, 40, 52, 55, 56, 58, 59 + alle weiteren
tripwired/gated gefundenen): Tripwires existieren aktuell in histogram/20/21/24,
reduce/28, scan/33, stencil/51, search/35 (Size-Guard), sort/40/42/43
(Referenz-Selftests), sparse-Familie (I5/D4/D5-Guards). Ergebnisse pro
Benchmark im Katalog (`domain.tripwires`, `pattern_audit`): auf allen
tripwired Sites sind extreme_values/spike_at deterministisch BI-only;
**Guard-Asymmetrien** als E2-Punkte: scan/34 (kein Guard, Oracle-UB) vs.
scan/33 (Guard); stencil/54 (kein Guard) vs. 51; transform/58 (kein Guard,
`x*x`-UB); transform/56 (INT_MIN even → UB-frei, aber Negativ-Semantik
unspezifiziert); transform/57 (all_zeros/all_same=Mittelwert 0 → volle
Singularität, ramps treffen exakt 0 u.a. bei Größe 7); search/37
(all_zeros → Voll-Tie, nur Baseline-First-Index bricht); 40 (extreme →
alle Magnituden inf → Ordnung degeneriert zur Permutationsprüfung);
search/36/37/39 (ungeguardete size-0-Crashes bei statischer Größe 0);
dense_la/01 (size-0-Loop-Underflow → OOB) und 19 (s.o.).

## 15. extreme_values / spike_at / value_range Suite-Impact

Vollständig je Benchmark im Katalog. Kurzfassung: **extreme_values** ist
unter Option A auf 46 EFFECTIVE-Benchmarks nur auf einer Minderheit
tatsächlich benotend UND sicher (Showcase: transform/59 mit gehärtetem
totalem Oracle; search-Familie typesafe); die Mehrheit ist BI-only,
Oracle-UB oder Tolerance-Cliff. **spike_at** ist häufiger benotbar
(z.B. valider odd-Wert nach 28-Typfix, sinnvoller Ausreißer auf scan/34),
teilt aber die Cliff-/BI-Risiken. **value_range** wird nur auf lo≤hi
validiert: kann frozen Domains verlassen (→BI-only-Runs), Elementtypgrenzen
überschreiten (saturiert; auf Mismatch-Sites bleibt die DType-UB) und
formal gültige, methodisch wertlose Specs erzeugen; Bestandsbefund: die
existierenden **explicit_values**-Specs von reduce/28 (negative) und
histogram/24 (−2147483649, 2^31) verletzen die frozen Domains bereits.

## 16. >4096-Ursachenklassifikation

| LARGE_SIZE_STATUS | Anzahl | Benchmarks |
|---|---:|---|
| BLOCKED_ONLY_BY_CURRENT_SPEC_POLICY | **54** | Rest der Suite (Heap-Vektoren, size_t-Sizing, keine festen Puffer/Narrowing) |
| BLOCKED_BY_BENCHMARK | **2** | geometry/12 (O(n³)-Oracle, ~1,1e10 Tripel bei 4096), reduce/26 (D6-Produktneutralitätsfenster endet ~n=308) |
| MULTIPLE_BLOCKERS | **4** | scan/34 (Policy + O(n²)-Oracle×Attempts), sparse_la/45 (O(N³)+O(N²)-Scratch), 46 (O(nnz²)), 49 (6 dichte N²-Arrays ~800 MB + O(N³)) |

Die bekannte 22er-Zielmenge wurde geprüft und ist vollständig
`BLOCKED_ONLY_BY_CURRENT_SPEC_POLICY` — **kein Harnessbug**; Caveats: fft
05/07/08/09 brauchen für jede Large-Size-Policy einen
**Power-of-two-Whitelist** (05: Heap-OOB-UB bei non-power-of-two N≥3 — gilt
schon bei kleinen Größen!), fft/06 O(n²)-Wallclock-Probe, O(N²)-Speicher
der Matrix-Benchmarks. **Bereits behobene historische Backlogpunkte**:
search/38-OOB (Wave 2A), search/35 size-0 (Wave 2B) u.a. wurden nicht als
aktuelle Defekte übernommen. `max_spec_size` wurde NICHT geändert; keine
8192-Policy erfunden.

## 17. Spec-Pipeline Capability Gap

**BENCHMARK_PATTERN_CAPABILITY_ENFORCEMENT_MISSING = true** (einzige
shape-bewusste Prüfung: explicit_values_supported, specs.py:335-341).
**LLM-Pfad-Gap = true** (alle 11 Patterns werden jedem Benchmark angeboten;
bei fill_sites==0 nur Prosa-Hinweis, hartes Verbot nur für explicit_values;
validate_spec kann No-Effect-Patterns nicht ablehnen). **Mutation-Pfad-Gap
= true** (random→extreme_values-Swap fabriziert deterministisch inerte
Pattern-Specs aus der statischen Basis; value_range-Shift kann Domains
verlassen; try_add validiert ohne allowed_patterns → umgeht sogar globales
offered_patterns-Narrowing). **Runner**: akzeptiert jede validierte Spec
(Text-Probe auf ENHANCED_TEST_SIZE_DEFAULT, keine Patternfilterung).
E2-Zielarchitektur (nur dokumentiert, NICHT implementiert):
`effective_patterns(benchmark) = globally_offered ∩ benchmark_supported`.

## 18. Priorisierte E2-Fixliste

**P0 — HARNESS CORRECTNESS**
1. DType-Deduktions-Fix oder Site-Fixes für die 5 typunsicheren Sites
   (reduce/28→int-Literale; scan/31, sort/42, sort/43→float-Literale;
   Grundsatzoption: DType aus value_type deduzieren). Files:
   enhanced-fill.hpp ODER die 4 cpu.cc. Risiko: Inputbit-Änderung für
   bestehende Specs → E3-Regeneration nötig. Test: Typprobe + Patternmatrix.
2. Oracle-UB-Guards/Pattern-Exclusion: scan/34 (33-artiger Guard),
   stencil/54 ({0,1}-Guard), transform/58 (|x|≤46340-Guard oder Exclusion),
   fft/05-Größenvalidierung (power-of-two; angebotene Größe 7 ist heute UB).
3. Size-0/1-Crashes bei angebotenen statischen Größen: graph/19 (N≥2-Guard),
   dense_la/01 (N=0-Underflow), search/36/37/39 (35-artige Guards oder
   Size-Exclusion).

**P1 — FAKE DIVERSITY**
4. Capability-Durchsetzung (R6): bei fill_sites==0 nur size-only/random;
   Enforcement in validate_spec/build_benchmark_specs + allowed_patterns
   auch im Mutations-/try_add-Pfad. Files: specs.py (+ Katalog als Quelle).
   Betroffen: 11 Benchmarks / 49 Bestands-Specs.
5. PATTERN_SWAPS fill-site-bewusst machen (kein random→extreme auf
   No-Effect-/BI-only-Benchmarks).

**P2 — DOMAIN/PATTERN POLICY**
6. EXTREME_PATTERN_SEMANTICS-Entscheidung umsetzen (Option A/B) + per-
   Benchmark-Exclusions für BI-only-Sets (histogram 20/21/24, scan 33,
   stencil 51/52/53, fft-Familie, dense_la 00/02/03/04, reduce 26/27/29,
   sparse 46/47/48-Fälle); value_range-Domainvalidierung (inkl.
   explicit_values-Magnituden für int-Sites — Bestandsverstöße 28/24).
7. Tolerance-Policy für Spike-/Extreme-Magnituden (absolute ε vs. 1e307).

**P3 — BENCHMARK ADAPTER** (nach Policy)
8. graph 15–19 (Dichte/Struktur-Vokabular), sort/44 (Zero-Struktur),
   dense_la/01 (Ground-Truth-x-Pattern + Nonsingularitätspolicy),
   sparse_la/45/49 (konstruktionsbewusste freie Achsen), reduce/25
   (bool-Dichte), sparse/46-Nonsquare-Probe (CLEAR, trivial).

**P4 — LARGE SIZE SUPPORT** (echte Blocker)
9. Nur falls Large-Size gewünscht: geometry/12- und reduce/26-Grenzen
   dokumentiert respektieren; scan/34-/sparse-45/46/49-Kostenprobes;
   fft-Power-of-two-Whitelist (überschneidet P0.2).

**P5 — POLICY ONLY**
10. max_spec_size-Entscheidung (54 Benchmarks haben keine Codebarriere);
    explicit_values_max_size; Größenverteilung des Specsets (Dominanz
    winziger Größen, nur 20 Specs >1000).

## 19. Offene E2-Policy-Entscheidungen

**EXTREME_PATTERN_SEMANTICS = OPEN** (Option A Elementtyp-Extrema vs.
Option B Domain-Extrema; suiteweite Auswirkungen in §15/Katalog).
**VALUE_RANGE_DOMAIN_POLICY = OPEN** (Domainvalidierung von value_range +
explicit_values). Ferner offen: Tolerance-Policy (P2.7), Graph-/Sparse-
Adapter-Vokabular (P3), Large-Size-Policy (P5). E1 hat keine dieser
Entscheidungen getroffen.

## 20. Verbleibende Unsicherheiten

- Kein Capability-Feld musste auf UNKNOWN gesetzt werden; einzelne
  Detailrisiken bleiben konditional (z.B. fft-Spike-Randrundung zu inf,
  sparse/48-Overflow nur bei Shared-Index-Treffern, Windows-RAND_MAX-Caveat
  41/44) und sind im Katalog als solche markiert.
- BI-only-/Cliff-Aussagen sind statische Ableitungen; exakte Häufigkeiten
  (z.B. „~80 % der Zeilen") wären erst per E2-Probe messbar.
- Ob die 3 PARTIAL-Benchmarks (02/04/46) ihre Probe-Fills patternfähig
  machen sollen, ist eine E2-Designfrage (46: CLEAR).

## Verifikation

Katalog: `python -m json.tool` Exit 0; 60 eindeutige IDs == aktuelle Suite;
Pflichtfelder vollständig; reduce/28 + alle 70 Fill-Sites im Type-Audit;
Fake-Diversity-Abschnitt deckt alle NONE/NOT_APPLICABLE-Benchmarks mit
Pattern-Specs ab. Cross-Pilot-Checker **nach** E1: Exit 0 (fresh,
unverändert — nur Audit-Artefakte hinzugefügt, keine Fingerprints
angefasst). `git status`: nur `thesis/enhanced_tests/enhanced_capabilities.json`
(neu) und dieser Report (neu); kein produktiver Sourcefile, keine Config,
keine Specs, keine Results geändert.
