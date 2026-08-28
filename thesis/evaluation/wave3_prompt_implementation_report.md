# Wave 3 — Atomic Prompt Wave: Implementation Report

Methodischer Audit-Report der atomaren Prompt-Wave vor `pilot_002`.
Alle Änderungen dieser Wave synchronisieren die Generierungs-Prompts mit den
in Wave 2A/2B implementierten, eingefrorenen Semantiken. Keine offene
semantische Entscheidung wurde getroffen; keine Rechenvorschrift wurde
eingeführt.

---

## 9.1 Provenance

| Feld | Wert |
|---|---|
| Repository | `jerabek-niklas/ParEval-Thesis` |
| Branch | `thesis-static-analysis` |
| Wave-3-Start-HEAD | `69c1e4783c6fb4d5e421e73bfa28f35127acd551` ("fixes 5", Wave-2B-Abschluss) |
| Working Tree vor Änderungen | clean (`git status --porcelain` leer) |
| Finaler Arbeitsstand | 75 geänderte/neue Pfade, unkommittiert: 69 raw-Prompts (M), `generation-prompts-thesis.json` (M), `prompt_oracle_fixtures.json` (M), `wave1_final_gate_report.md` (M, nur markierter Interlock-Hinweis), neu (??): `wave3_regeneration_set.json`, `prompt_oracle_interlock.json`, dieser Report |
| Datum | 2026-08-27 |
| Source of Truth (Prompts) | `thesis/prompts/raw/<problem_type>/<name>/{serial,omp,mpi}` |
| Generiertes Artefakt | `thesis/prompts/generation-prompts-thesis.json` (ausschließlich per Generator regeneriert) |
| pilot_001 Prompt-Baseline | Commit `6846d689fd81186b2161786dc7f52d485ccf2b5c` |
| Baseline-Verifikation | `thesis/results/intermediate/pilot_001/run_manifest.json`: `git_commit == 6846d689…`, `git_dirty == False`; Commit ist Vorfahr von HEAD; P0-Promptstand byte-exakt via `git show` extrahiert |

**PILOT_001_PROMPT_BASELINE_VERIFIED = true.**

## 9.2 Prompt-Source-of-Truth

- **raw/ versioniert:** ja — 180 getrackte Dateien (60 Benchmarks × {serial, omp, mpi}), CRLF, ohne Trailing-Newline.
- **raw/ vollständig:** ja — jede der 180 Identitäten hat genau eine Datei.
- **raw → generated reproduzierbar:** ja. Vor der Wave: Regeneration byte-identisch zum eingecheckten Stand. Nach den Edits: zweiter Generatorlauf byte-identisch zum ersten (SHA-256 `5e73e79ef89f81e42ccbce5e5f0a37d4c7340aff34f2b225091c6933e66c3341`).
- **Generator-Command:** `python thesis/prompts/create_generation_prompts.py` (Default-Optionen).
- **Generatoroptionen:** keine; insbesondere **`--add-imports` NICHT verwendet** (wie für pilot_001) und kein `--function-suffix`.
- **PromptValidator:** läuft per Default (`--no-validate` nicht gesetzt); 0 Verstöße. Alle 180 Prompts enden mit `{`, enthalten ein Worked Example, omp-Prompts nennen "OpenMP", mpi-Prompts "MPI" + "initialized".
- **Reihenfolge stabil:** ja — deterministische sortierte Verzeichnis-Iteration, Modellreihenfolge [serial, omp, mpi]; Identitätsreihenfolge P0 → P2 exakt identisch (`unintended_prompt_order_change = false`).
- **PROMPT_SOURCE_DIVERGENCE = false** (raw und generiertes JSON konsistent, vor und nach der Wave).

`copy_prompt_subset.py` (destruktives `rmtree`) wurde nicht ausgeführt.

## 9.3 pilot_001-Population (aus Records rekonstruiert)

Quelle: `assembly.jsonl`/`correctness.jsonl` der Basis-Run-Verzeichnisse mit
`run_id == "pilot_001"`, Sample-IDs geparst als
`<model>__<ptype>__<name>__<exec>__sample_<n>`.

| Dimension | Wert |
|---|---|
| Benchmarks | 12: dense_la/00, fft/05, geometry/10, graph/15, histogram/20, reduce/25, scan/30, search/35, sort/40, sparse_la/45, stencil/50, transform/55 |
| Modelle | 11 (die 11 enabled der 15 konfigurierten) |
| Execution Models | 3: serial, omp, mpi |
| Samples pro Zelle | 1 (`sample_0`) |
| Records | assembly: 396; correctness (Basisrun): 396; identische Zellmengen |
| Rechteckig | ja — 11 × 12 × 3 × 1 = 396, fehlende Zellen: 0 |

**PILOT_001_POPULATION_VERIFIED = true.** Die 60-Benchmark-Suite ist NICHT
mit dieser tatsächlich gelaufenen Population gleichzusetzen.

## 9.4 Wave-3-Promptänderungen

Alle Edits wurden im raw-Bestand identisch auf serial, omp und mpi angewandt
(mechanisch erzwungen: exakt-einmal-Anker pro Datei, Abbruch sonst). Jede
Zeile der Tabelle steht daher für die drei Prompt-Einträge
`<problem_type>/<name>/{serial,omp,mpi}` (abgeleitete `prompt_id`s; nie
Array-Indizes). Für alle gilt: **semantic** (Klarstellung des Vertrags auf den
implementierten, eingefrorenen Stand) und
**requires_pilot_002_regeneration = true**. Kategorien:
(a) KONVENTION_EXPLIZIT_GEMACHT, (b) DOMAENENRESTRIKTION,
(c) BEISPIELKORREKTUR; (d) RECHENVORSCHRIFT kam nicht vor.

| Benchmark | Alte relevante Semantik (Prompt) | Neue relevante Semantik (Prompt) | Frozen Source | Kat. |
|---|---|---|---|---|
| fft/05_fft_inverse_fft | Größe von x unspezifiziert | "size of x is always a power of two" | I12 / FFT-Familienaudit | b |
| fft/06_fft_dft | DFT-Konvention unspezifiziert; Beispiel k=1/k=3 vertauscht | unnormalisierte Forward-DFT, Negativ-Exponent; Beispiel `[30+0i, -8+12i, -10-0i, -8-12i]` | I12; Oracle-Output verifiziert | a, c |
| fft/07_fft_fft_conjugate | "imaginary conjugate of each value" (mehrdeutig); Beispiel = unkonjugierte FT | Ergebnis = elementweise komplexe Konjugation der unnormalisierten Forward-FT (Negativ-Exponent); power-of-two; Beispiel konjugiert | I12 + Wave-2B B3 (Top-Level-Konjugation, B3.1b unabhängig verifiziert) | a, b, c |
| fft/08_fft_split_fft | Länge unspezifiziert | "length of x is a power of two" | I12 | b |
| fft/09_fft_fft_out_of_place | Größe unspezifiziert; Beispiel-Tippfehler `-2.42421` | power-of-two; `-2.41421` | I12; Oracle-Output | b, c |
| geometry/10_geometry_convex_hull | Hull-Elementsemantik unspezifiziert | Hull der distinkten Punktmenge; jeder Eckpunkt genau einmal, beliebige Reihenfolge; Kantenpunkte ausgeschlossen; <3 distinkte Punkte → genau diese | I11 + Wave-2B B5 | a |
| geometry/11_geometry_convex_hull_perimeter | Degenerate Fälle unspezifiziert | Ergebnis hängt nur von distinkter Punktmenge ab; kollinear/<3 distinkt → 2·Spannweite; alle gleich/leer → 0 | I11 + Wave-2B B5 | a |
| graph/19_graph_shortest_path | Kantengewichte/Sentinels unspezifiziert | symmetrisch, Nulldiagonale, Einheitskanten, gültige Indizes; source==dest → 0; unerreichbar → INT_MAX | frozen Graph-19-Vertrag (Wave 2A A6) | b, a |
| histogram/21_histogram_bin_0-100 | Zugehörigkeit von exakt 100 offen; Init unspezifiziert | 100 → bins[9] (Obergrenze inklusiv); bins zero-initialisiert | frozen Domain [0,100] (Wave-2B-Tripwire) | a |
| histogram/23_histogram_first_letter_counts | nur "lower case" | "lower case **and non-empty**" | frozen Domain (Wave-2B-Tripwire) | b |
| histogram/24_histogram_count_quartile | Wertebereich unspezifiziert | nicht-negativ und < 2147483648 (2^31) | frozen Domain (Wave-2B-Tripwire) | b |
| reduce/28_reduce_smallest_odd_number | Verhalten ohne ungerade Zahl / leer unspezifiziert | Elemente nicht-negativ; keine ungerade Zahl (insb. leer) → `std::numeric_limits<int>::max()` | frozen Domain + Sentinel (Wave-2B-Tripwire) | b, a |
| search/38_search_find_the_first_even_number | Verhalten ohne gerade Zahl unspezifiziert | keine gerade Zahl → `x.size()` | frozen Sentinel (Wave 2A A4) | a |
| sort/41_sort_k-th_smallest_element | k-Semantik unspezifiziert; Beispiel `6` (falsch) | k 1-indiziert, 1 ≤ k ≤ x.size(), Duplikate separat gezählt (Multiset-Rang); Beispiel `2` | frozen k∈[1,n] (Wave 2A A5); Oracle-Output | a, c |
| sort/42_sort_sorted_ranks | Tie-Semantik unspezifiziert; Beispiel 2 mit unklarer Tie-Vergabe | Ranks = Permutation von 0..n-1; gleiche Werte dürfen ihre Tie-Ranks in beliebiger Reihenfolge erhalten; Beispiel `[4, 0, 2, 3, 1]` | I10-Invariantenvalidator (Wave-2B B10) | a, c |
| sparse_la/45_sparse_la_sparse_solve | A-Eigenschaften unspezifiziert | quadratisch, nichtsingulär, COO duplikatfrei, Indizes in [0,N); eindeutiges x mit Ax=b | D4-Konstruktion + I5 (Wave 2A) | b, a |
| sparse_la/46_sparse_la_spmm | COO-Eigenschaften unspezifiziert | beide COO-Listen duplikatfrei, Indizes innerhalb der Dimensionen | I5 (Wave 2A) | b |
| sparse_la/47_sparse_la_spmv | dito | row < M, column < N, keine doppelten (row, column) | I5 (Wave 2A) | b |
| sparse_la/48_sparse_la_sparse_axpy | dito | aufsteigend sortiert, Indizes je Vektor eindeutig, gültige Positionen in z | I5 (Wave 2A) | b |
| sparse_la/49_sparse_la_sparse_lu_decomp | Faktorisierbarkeit/Outputform unspezifiziert | COO duplikatfrei; führende Hauptminoren 1..N-1 ≠ 0 (pivotfreie LU existiert); exakt diese Faktorisierung (keine Permutation, als Output-Relation formuliert); L/U dense row-major, Einheitsdiagonale/Nullen außerhalb der Dreiecke | D5-Konstruktion (Wave 2A) | b, a |
| stencil/50_stencil_xor_kernel | Nachbarschaft unspezifiziert (pilot_001-Fehlerklasse: 31/33 falsch benotet) | bis zu 8 umgebende Zellen (Moore); außerhalb des Gitters nicht gezählt | I4 Moore (Wave-2B B8, Oracle umgestellt) | a |
| stencil/51_stencil_edge_kernel | Pixelwertebereich unspezifiziert | genau N*N Werte; Werte in [0, 255] | frozen Domain (Wave-2B-Tripwire) | b |
| stencil/54_stencil_game_of_life | Randsemantik unspezifiziert | außerhalb tot (zählt 0), kein Wrap-around | I14 dead-outside (Wave-2B B8.4) | a |

**Aggregate:** Benchmarks geprüft: **60/60**. Benchmarks Wave-3 geändert:
**23/60**. Prompt-Einträge Wave-3 geändert: **69/180**.
Kategorien (auf Benchmark-Ebene, Mehrfachnennung möglich):
KONVENTION_EXPLIZIT_GEMACHT = **14**, DOMAENENRESTRIKTION = **14**,
BEISPIELKORREKTUR = **5**, RECHENVORSCHRIFT = **0**
(`implemented_RECHENVORSCHRIFT_count == 0`).

**Explizit NICHT geändert (Beschluss lag vor, kein Prompt-Edit nötig/erlaubt):**
scan/33 (frozen Tabellenzeile: `prompt_restriction_needed: "no"` —
Durchsetzung generatorseitig + Tripwire; ein früher 2B-Entwurfseintrag §29 ist
damit überstimmt), sort/40 und sort/43 (I10-Invariantenvalidatoren machen
Tie-Sätze überflüssig), histogram/20, reduce/26, transform/59 (kein
promptseitiger Vertragsbestandteil betroffen).

## 9.5 Offene Semantik — BLOCKED_PENDING_SEMANTIC_DECISION

Kein Edit; ein Satz hätte die offene Semantik im Rahmen der Prompt-Wave
entschieden (verboten). Alle Execution Models (serial, omp, mpi) betroffen.

| Benchmark | Problem | Source | Status | Promptzustand | Oraclezustand | Grund für Nichtänderung |
|---|---|---|---|---|---|---|
| dense_la/00_dense_la_lu_decomp | absolute 1e-3-Toleranz für alternative Eliminationsreihenfolgen ggf. unerreichbar | BL-01 / #71 (Oracle-Audit) | offen ("FROZEN IMPLEMENTATION TARGET NOT SPECIFIED") | keine Toleranzaussage | absolute ε-Vergleiche | Toleranzregime nicht eingefroren |
| geometry/12_geometry_smallest_triangle | n<3, degenerierte (kollineare/duplizierte) Tripel | BL-05 | offen | keine Degenerate-Aussage | implementierungsdefiniert | Konvention nicht eingefroren |
| geometry/13_geometry_closest_pair_2d | n<2, DBL_MAX-Sentinel | BL-06 | offen | keine n<2-Aussage | DBL_MAX als Implementierungszufall | Konvention nicht eingefroren |
| geometry/14_geometry_closest_pair_1d | n<2, DBL_MAX-Sentinel | BL-07 | offen | keine n<2-Aussage | dito | Konvention nicht eingefroren |
| histogram/22_histogram_count_quadrants | Achsenpunkte (x==0 / y==0) | Decision-Tabelle: "no decision has been recorded yet" | offen | keine Achsenkonvention | implizit über Vergleichsoperatoren | ausdrücklich keine Entscheidung protokolliert; der queued Satz wurde deshalb NICHT implementiert |
| scan/34_scan_largest_contiguous_subarray_sum | leeres Subarray zulässig? size-0-Ergebnis? | BL-10/BL-11 ("decision deliberately left open") | offen | keine Aussage | eine der beiden Standardkonventionen | beide Optionen live |
| search/37_search_find_the_closest_number_to_pi | Tie-Break bei gleichem Abstand zu π | Decision-Tabelle (36/37/39-Queue-Asymmetrie dokumentiert) | offen | keine Tie-Aussage | implizit über Scanreihenfolge | Tie-Regel nicht eingefroren |

**BLOCKED_PENDING_SEMANTIC_DECISION count = 7.**
Verwandte offene Punkte ohne Prompt-Blockade (keine Grading-Konvention über
Kandidatenoutputs): search/36, search/39 (size-0/modulo-0-Treiberecken),
search/35 `numTries=5` (undokumentiert, unverändert gelassen — Wave-2B-Befund).

## 9.6 Prompt↔Oracle-Interlock

Registry: `thesis/evaluation/prompt_oracle_interlock.json` (neu in Wave 3).

- **Aktive Interlocks: 7** — exakt die Tabelle aus 9.5.
- **Betroffene Benchmarks:** dense_la/00, geometry/12, geometry/13,
  geometry/14, histogram/22, scan/34, search/37.
- **Betroffene Prompt-/Execution-Model-Paare:** 7 × {serial, omp, mpi} = **21**.
- **applies_to:** enhanced_stage, timing_stage, pilot_002.
- **enforcement:** `disclosure_required` — KEIN automatischer Ausschluss,
  keine Verdict-Änderung; per-Benchmark-Berichte der genannten Stufen müssen
  die offene Entscheidung neben dem Ergebnis ausweisen.
- **Neu:** 7. **Weitergeführt:** 0 (Registry existierte vorher nicht).
  **Entfernt:** 0.

**Harte Invariante erfüllt: `blocked_semantic_decisions_without_interlock == 0`**
(7 blockierte Entscheidungen, 7 Interlocks, bijektiv).

## 9.7 Prompt↔Oracle-Gate

- **Command:** `docker run --rm -u 0 -v "<repo>:/workspace" -w /workspace pareval-thesis python3 thesis/evaluation/check_prompt_oracle_consistency.py`
- **Exitcode:** 0
- **PASS (consistent): 60/60** — **INCONSISTENT: 0** — **not_covered: 0** — **infra_error: 0**

Vor der Wave waren 5 Benchmarks INCONSISTENT (06, 07, 09, 41, 42 — alle
eingefrorene Beispielkorrekturen im Wave-3-Scope); alle 5 sind durch die
Prompt-/Fixture-Korrekturen konsistent. Es verbleibt kein INCONSISTENT, damit
entfällt die Pflicht zu Source+Decision+Interlock je INCONSISTENT. Die
Fixtures 06/07/09/41/42 wurden ausschließlich auf die frozen Worked-Example-
Fixes angepasst (`expected_json` + `example_source` verbatim; bei 42 zusätzlich
die inzwischen faktisch falsche Grader-Beschreibung im
`canonicalization`-Feld auf den I10-Stand korrigiert).

## 9.8 Prompt-Text-Regeneration-Set

Referenz: `thesis/evaluation/wave3_regeneration_set.json`.

| Kennzahl | Wert |
|---|---|
| pilot_001-Baseline (P0) | `6846d689fd81186b2161786dc7f52d485ccf2b5c` |
| PRE_WAVE3_PROMPT_CHANGE (P0→P1) | **0** Einträge (P1 byte-identisch zu P0) |
| WAVE3_PROMPT_CHANGE (P1→P2) | **69** Einträge |
| P0 → P2 Diff gesamt | **69** Einträge (== Wave-3-Änderungen) |
| E_prompt_entries | 69 |
| E_semantic | 69 |
| E_cosmetic | 0 (kosmetische Änderungen kamen nicht vor; keine wurde herausgefiltert) |
| Betroffene Benchmarks (E) | 23 |
| all-three changed | 23/23 |
| partial changes | **benchmarks_partially_changed = 0** |
| Regeneration je Execution Model | serial 23, omp 23, mpi 23 |
| ALL_CHANGED_MODEL_PROMPTS_REQUIRE_REGENERATION | **true** (alle 69 Einträge `requires_pilot_002_regeneration: true`) |

**Bestätigt: `E == benchmark_projection(regeneration_set)`** — die
`E_benchmark_projection`-Liste des Artefakts (23) ist exakt die Projektion der
69 Einträge auf (problem_type, name); mechanisch per Assertion beim Bau und
unabhängig im Verifikationsskript geprüft.

## 9.9 Full Generation Condition

| Kennzahl | Wert |
|---|---|
| SYSTEM_PROMPT_CHANGED_SINCE_PILOT_001 | **false** — SHA-256 beidseitig `2ca303b59cbb767706d2d4ea0153f6ad0afc2e00ad2988c748990d24be302e4a` |
| GENERATION_PARAMS_CHANGED_SINCE_PILOT_001 | **false** — kanonisches JSON (generation_defaults + Modellfelder ohne Preise), SHA-256 beidseitig `e22ce9beb2bd9f9d85940a00585b6017eae389ad8bb933acda99f45f2d7d3281`; Modell-ID-Mengen identisch, Felddiffs: keine; Preise (nicht generierungsrelevant) ebenfalls identisch; Pilot-Profil identisch |
| PROMPT_TEXT_REGENERATION_SET | 69 Einträge / 23 Benchmarks |
| FULL_GENERATION_CONDITION_CHANGED_SET | **== Prompt-Text-Regeneration-Set** (69 Prompt-Identitäten); Status: vollständig bestimmt |
| Betroffene Modelle/Provider | alle 11 enabled Modelle gleichermaßen (die Änderung liegt im Prompttext, nicht in Modell-/Providerkonfiguration) |
| Betroffene Zellen | pilot_001-Population: 4 der 12 Benchmarks × 3 × 11 = **132 von 396 Zellen**; volle Suite (falls pilot_002 alle 60 fährt): 69 Identitäten × 11 Modelle = 759 Generationszellen |

**NECESSARY_BUT_NOT_SUFFICIENT: nein — hier fallen die Mengen zusammen.**
Da System-Prompt und Generation Parameters hash-verifiziert unverändert sind,
ist Prompt-Identität in dieser Wave nicht nur notwendig, sondern auch
hinreichend für Generation-Condition-Identität einer Zelle. (Die Aussage gilt
nur unter genau dieser Verifikation; bei künftiger Änderung eines der beiden
anderen Bestandteile wäre sie hinfällig.)

## 9.10 pilot_002-Reuse

**PILOT_002_REUSES_PILOT_001_GENERATIONS = UNDECIDED.**

Source: Es existiert kein Artefakt (Config, Manifest, Code, Dokumentation),
das eine Cross-Pilot-Reuse-Entscheidung festhält. Der einzige Mechanismus, der
vorhandene Samples überspringt, ist das Same-run_id-Resume der
Generierungspipeline (`thesis/generation/common.py`, Resume-Regel: "SAME
run_id (resume adds only the missing samples)", Z. 441; `load_resume_state`
Z. 181). Ein `pilot_002`-Run hätte eine neue run_id und würde damit per
Konstruktion alles neu generieren, sofern nicht eine — bislang nicht
existierende — explizite Import-Entscheidung getroffen wird. Diese Wave
erfindet keine solche Entscheidung.

## 9.11 A/B/C/D-Baseline-Konsistenz

Kategorien (Wave-2B-Report §34): A Input-Konstruktion, B Validator/Oracle-
Semantik, C Größendomäne, D zusätzliche Validierungsfälle. E (diese Wave) =
Prompt-Text.

| Kategorie | Source | Baseline | Rekonstruktionsmethode | Auf pilot_001 normalisiert? |
|---|---|---|---|---|
| A (8: 19, 38, 41, 45, 46, 47, 48, 49) | wave2b-Report §34 (frozen) | Benchmark-Stand vor Domain-Approval-Wave = pilot_001-Commit `6846d689` **plus** Wave-1/1b-Transport | frozen §34-Tabelle (Union Domain-Approval + 2A + 2B, je Benchmark einmal) | ja, mit dokumentiertem suite-weiten Transport-Zusatz |
| B (24) | dito | dito | dito | dito |
| C (3: 07, 12, 26) | dito | dito | dito | dito |
| D (3: 02, 04, 46; plus 38 Attempt-REDUKTION) | dito | dito | dito | dito |
| E (23) | `wave3_regeneration_set.json` | **exakt** pilot_001-Commit `6846d689` (P0, byte-verifiziert; P0→P1 = 0) | byte-Diff P0 vs. P2 | ja, exakt |

- **ABCD_BASELINE:** einheitlich der Stand nach Wave 1/1b. Die Wave-1/1b-
  Comparator-/Transport-Semantik (BI-Vokabular, Size-Mismatch-FAIL,
  Non-Finite-Candidate-FAIL) liegt VOR der §34-Union und betrifft ALLE 60
  Benchmarks relativ zu pilot_001; §34 führt sie als expliziten suite-weiten
  Zusatzvermerk, nicht als per-Benchmark-Zeilen.
- **UNION_BASELINE_INCONSISTENT = false**, mit Begründung: Für die von E
  gemessene Dimension (Prompttext) ist der Stand bei `6846d689` und der Stand
  nach Wave 1/1b identisch (P0→P1 = 0 byte-verifiziert); für die von A–D
  gemessenen Dimensionen liegt zwischen pilot_001 und der A–D-Baseline nur
  das suite-weite Transport-Delta, das als eigener, alle 60 betreffender
  Posten mitgeführt wird. Die per-Benchmark-Union A∪B∪C∪D∪E ist damit auf
  einer konsistenten Baseline darstellbar, solange der suite-weite
  Transportvermerk stets mitberichtet wird (hier geschehen).

## 9.12 Full-Benchmark-Change-Analysis (A/B/C/D/E über 60 Benchmarks)

| Menge | Benchmarks | Anzahl |
|---|---|---|
| A | 19, 38, 41, 45–49 | 8 |
| B | §34-Spalte "Validator/oracle" | 24 |
| C | 07, 12, 26 | 3 |
| D | 02, 04, 46 (+ 38 Attempt-Reduktion) | 3 |
| E | 05, 06, 07, 08, 09, 10, 11, 19, 21, 23, 24, 28, 38, 41, 42, 45–49, 50, 51, 54 | 23 |
| A∪B∪C∪D | §34: 29 | 29 |
| **A∪B∪C∪D∪E** | 29 ∪ {05, 06, 08, 09, 23} | **34** |

E fügt der §34-Union genau 5 Benchmarks hinzu (fft/05, 06, 08, 09,
histogram/23 — reine Prompt-Klarstellungen ohne Benchmark-seitige Änderung).
Suite-weit zusätzlich (alle 60): Wave-1/1b-Transportsemantik. Unverändert in
allen fünf Kategorien: 26 Benchmarks.

## 9.13 Actual-Cross-Pilot-Analysis

Basis ist die TATSÄCHLICHE pilot_001-Population (9.3), nicht die 60er-Suite.

| Kennzahl | Wert |
|---|---|
| PILOT_001_BENCHMARK_SET | 12 (Liste in 9.3) |
| PILOT_001_CHANGED_SET (A∪B∪C∪D∪E ∩ Pilotmenge) | **6**: fft/05 (E), geometry/10 (B+E), histogram/20 (B), sort/40 (B), sparse_la/45 (A+B+E), stencil/50 (B+E) |
| PILOT_001_METHOD_UNCHANGED_SET (soweit bestimmbar) | **6**: dense_la/00, graph/15, reduce/25, scan/30, search/35, transform/55 — modulo suite-weitem Transport-Delta; 00 trägt zusätzlich den offenen BL-01-Interlock; 35 ist formal geändert (crash→BI-Marker), von §34 als klassenerhaltend (F) eingestuft |
| PILOT_001_FULL_GENERATION_CONDITION_UNCHANGED_SET | **8** Benchmarks (alle außer 05, 10, 45, 50): 00, 15, 20, 25, 30, 35, 40, 55 — Status: vollständig bestimmt (Prompt byte-identisch + System-Prompt/Params hash-identisch) |
| PILOT_001_FULL_GENERATION_CONDITION_UNCHANGED_CELLS | **264** von 396 (8 × 3 × 11 × 1) |
| Tatsächlich vergleichbare Zellen (Generierung UND Bewertungsmethode unverändert) | **198** (6 × 3 × 11), modulo Transport-Delta |
| Samples je vergleichbarer Zelle | **1** — pilot_001 erlaubt KEINE Innerhalb-Zelle-Varianzschätzung |
| Vorbestehende statistische Limits | 1 Sample/Zelle; 12-von-60-stratifizierte Auswahl; 11 von 15 Modellen enabled; NaN-Referenz-Blindspot der frozen Records (Wave-1 §8.4, retroaktiv nicht schließbar); retrospektiv identifizierte vakuose Enhanced-Passes (Wave-1 §9) |
| Reuse-Folge | Bei Reuse (UNDECIDED): Generationsidentität der 264 Zellen per Konstruktion, Verdicts-Deltas wären rein bewertungsseitig attribuierbar. Ohne Reuse: Neu-Generierung unter verifiziert identischer Condition; batch-API-Nichtdeterminismus bleibt trotz temperature 0.0 als Restrauschen, Attribution entsprechend schwächer. |
| Selektionsbias | E-Rate in der Pilotmenge 4/12 (33,3 %) vs. 23/60 (38,3 %); Gesamtänderungsrate 6/12 (50,0 %) vs. 34/60 (56,7 %) — die Pilotmenge ist gegenüber der Suite leicht UNTERdurchschnittlich von Änderungen betroffen; Richtung und Ausmaß dokumentiert, keine Korrektur vorgenommen |
| Methodisch zulässige Vergleichsformen | (1) Aggregat nur über die method-unchanged-Teilmenge; (2) per-Benchmark-Vorher/Nachher mit Provenance-Annotation (§34-Tabelle + E); (3) Regressions-Evidenz (dokumentierte Verdict-Inversionsklassen); (4) Innerhalb-pilot_002-Modellvergleiche |
| **Abschlussklassifikation** | **PILOT_SUBSET_ONLY_QUANTITATIVE_COMPARISON_DEFENSIBLE** — quantitativ vertretbar nur für die 198 Zellen der 6 method-unchanged-Benchmarks, stets mit (a) suite-weitem Transportvermerk, (b) 1-Sample-Limit, (c) 00-Interlock-Disclosure; die Attributionsschärfe (Generierung vs. Bewertung) hängt zusätzlich an der UNDECIDED-Reuse-Entscheidung (insoweit CROSS_PILOT_COMPARISON_DEPENDS_ON_REUSE_DECISION als Zusatzqualifikation). Für die 6 geänderten Pilot-Benchmarks: qualitative/Regressions-Evidenz, kein quantitativer Vorher/Nachher-Schluss auf Modellqualität. |

## 9.14 Upstream-ParEval-Divergenz

Vergleich gegen `prompts/generation-prompts.json` (Upstream, 420 Einträge).
Nur die gemeinsame Population zählt; zusätzliche Upstream-Parallelism-Modelle
sind KEINE Thesis-Divergenz.

| Kennzahl | Wert |
|---|---|
| UPSTREAM_COMMON_PROMPT_ENTRIES | **180** (60 Benchmarks × {serial, omp, mpi}; Identitätsmengen beidseitig deckungsgleich) |
| UPSTREAM_THESIS_ONLY_ENTRIES | 0 |
| UPSTREAM_EXTRA_PARALLELISM_ENTRIES | 240 (cuda 60, hip 60, kokkos 60, mpi+omp 60) — nicht gewertet |
| Preexisting mechanical divergent (vs. P0) | **120** — alle 60 omp- und alle 60 mpi-Einträge, ausschließlich das fehlende `#include <omp.h>`/`#include <mpi.h>`-Präfix (+ Leerzeile); erklärt vollständig durch **nicht verwendetes `--add-imports`**; systematisch aggregiert als EIN mechanischer Unterschied, nicht als 120 semantische |
| Preexisting semantic divergent (vs. P0) | **0** — alle 60 serial-Einträge waren byte-identisch zu Upstream; omp/mpi nach Abzug des Include-Präfixes ebenfalls |
| New Wave-3 mechanical divergent | 0 |
| New Wave-3 semantic divergent | **69** Einträge (23 Benchmarks × 3, keine partiellen) |
| Final semantic divergent prompt entries (P2 vs. Upstream) | 69 |
| **Final semantic divergent benchmarks** | **23** (== Wave-3-Regeneration-Set; sämtliche semantische Upstream-Divergenz ist Wave-3-dokumentiert) |

Methodische Aussage: Für diese 23 Benchmarks sind publizierte
ParEval-Ergebnisse nicht unter exakt derselben Promptbedingung entstanden.
Das dokumentiert ausschließlich eine Promptbedingungs-Divergenz — es besagt
NICHT, dass ParEval falsch sei, publizierte Ergebnisse ungültig seien oder
jeder Vergleich unmöglich wäre.

## 9.15 Tests und deterministische Checks

| Command | Exitcode | PASS/FAIL | Relevante Counts | Bemerkung |
|---|---|---|---|---|
| `docker run … pareval-thesis python3 thesis/evaluation/check_prompt_oracle_consistency.py` | 0 | PASS | consistent 60, INCONSISTENT 0, not_covered 0, infra_error 0 | Gate 9.7 |
| `python thesis/prompts/create_generation_prompts.py` (2×) | 0 | PASS | 180 Prompts; 2. Lauf byte-identisch (SHA `5e73e79e…`) | Validator default-on, 0 Verstöße |
| Verifikationsskript P0↔P2 (scratch `verify_p2.py`) | 0 | PASS | 180/180; Ordnung identisch; 69 geändert; 23 Benchmarks; partial 0; Nicht-Prompt-Felder 0 Diffs | stabile Identität, serial/omp/mpi-Konsistenz, Reihenfolge |
| Raw-Edit-Skript (scratch `apply_prompt_edits.py`) | 0 | PASS | 69 Dateien geändert, 0 Ankerfehler | exakt-einmal-Anker, CRLF erhalten |
| `.venv\Scripts\python.exe thesis/assembly/test_cleaning.py` | 0 | PASS | 13/13 | — |
| `docker run … pareval-thesis python3 thesis/evaluation/test_comparator_semantics.py` | 0 | PASS | "all comparator-semantics checks passed" | Host-Lauf ohne g++ übersprungen, Container-Lauf maßgeblich |
| `.venv\Scripts\python.exe thesis/enhanced_tests/derive_shapes.py --check` | 0 | PASS | "stored shapes match the derivation" | keine Shapes-Drift durch die Wave |
| Generation-Condition-Vergleich (scratch `gen_condition.py`) | 0 | PASS | System-Prompt- und Params-Hashes identisch | 9.9 |
| pilot_001-Populationsrekonstruktion (scratch `pilot_population.py`) | 0 | PASS | 396 Zellen, rechteckig | 9.3 |
| Upstream-Divergenz (scratch `upstream_divergence2.py`) | 0 | PASS | 180 common; 120 mechanical; 69 semantic (alle Wave 3) | 9.14 |

## 9.16 Invarianten — explizit bestätigt

- keine Verdict-Änderung; keine neuen Verdict-Klassen
- keine produktive Schema-Änderung; kein spec_key-Wandel
- keine Repair-Semantik geändert
- keine Benchmark-, Oracle- oder Validator-Semantik geändert (kein
  `drivers/**`-, `baseline.hpp`- oder `cpu.cc`-Touch in dieser Wave)
- keine Enhanced-Harness-Änderung; keine Enhanced Specs regeneriert
  (ENHANCED_SPEC_REGENERATION_REQUIRED durch Prompttext-Änderungen: false;
  die aus Wave 2B queued Enhanced-Pattern/Harness-Wave bleibt aus
  benchmarkseitigen Gründen queued)
- keine Modellgeneration durchgeführt; kein pilot_002 gestartet
- keine `thesis/results`-Daten verändert (read-only respektiert)
- keine S/M/L-Domain geändert; keine Tool-Konfiguration geändert
- kein System-Prompt geändert; keine Generation Parameters geändert;
  keine Modell-/Reasoning-Konfiguration geändert (9.9, hash-verifiziert)
- keine offene Semantik entschieden (7 blockiert, 7 interlocked)
- keine Rechenvorschrift als Modellhilfe eingeführt (Kategorie-(d)-Count 0;
  fft/07 und sparse_la/49 bewusst als I/O-Relation bzw. Output-Relation
  formuliert)
- keine Reuse-Entscheidung erfunden (UNDECIDED, 9.10)
- `generation-prompts-thesis.json` ausschließlich aus `raw/` regeneriert
- `copy_prompt_subset.py` nicht ausgeführt; `wave1_final_gate_report.md` nur
  um den klar markierten nachgelagerten Interlock-Hinweis ergänzt
- kein `git add`, kein Commit

---

*Ende des Wave-3-Reports. Dieser Report ist bewusst unkommittiert.*

---

# POST-WAVE-3 PROVENANCE UPDATE

> **[NACHTRAG — hinzugefügt von der Wave-3-Cleanup-Wave (2026-08-27), NICHT
> Teil des historischen Wave-3-Reports oberhalb dieser Linie. Der historische
> Report beschrieb korrekt den unmittelbar post-Wave unkommittierten Zustand
> ("75 geänderte/neue Pfade, unkommittiert", "kein Commit, kein git add" —
> damals zutreffend); dieser Nachtrag dokumentiert ausschließlich dessen
> spätere Persistierung und verfälscht keine historische Aussage.]**

| Feld | Wert |
|---|---|
| Ursprünglicher Wave-3-Start-HEAD | `69c1e4783c6fb4d5e421e73bfa28f35127acd551` ("fixes 5") |
| Persistierender Commit | `730c0afe5fcfee2272fcdb8c12ea3ad58e3f923f` ("fixes 6") |
| Commit-Parent | `69c1e4783c6fb4d5e421e73bfa28f35127acd551` (== Wave-3-Start-HEAD, keine Zwischencommits) |
| Commit-Datum | 2026-08-27T21:16:01+02:00 |
| Working-Tree-/Commit-Beziehung | Der zum Report-Zeitpunkt unkommittierte Arbeitsstand wurde nachträglich als ein einzelner Commit persistiert; Working Tree bei Cleanup-Beginn clean auf `730c0afe`. |

**WAVE3_REPORTED_TREE_MATCHES_COMMITTED_TREE = true.** Verifikation:
`git diff --name-status 69c1e478..730c0afe` liefert exakt die 75 im Report
(§9.1) beschriebenen Pfade (69 × `thesis/prompts/raw/**` M; `prompt_oracle_fixtures.json` M;
`wave1_final_gate_report.md` M; `generation-prompts-thesis.json` M;
`prompt_oracle_interlock.json`, `wave3_regeneration_set.json`, dieser Report A) —
keine zusätzlichen, keine fehlenden Pfade. Inhaltlich: der SHA-256 des
committeten `generation-prompts-thesis.json` ist identisch mit dem im
historischen Report und im Regeneration-Set festgehaltenen Wert
`5e73e79ef89f81e42ccbce5e5f0a37d4c7340aff34f2b225091c6933e66c3341`; das
Regeneration-Set weist unverändert 69 Einträge / 23 Benchmarks aus. Der
historische Report beschreibt also den unmittelbar post-Wave unkommittierten
Zustand, und `730c0afe` ist genau dessen spätere Persistierung.

# POST-WAVE-3 CLEANUP / PROVENANCE & CROSS-PILOT GATE

> **[NACHTRAG der Wave-3-Cleanup-Wave (2026-08-27). Der folgende Abschnitt
> ERSETZT die Cross-Pilot-Einschätzung in §9.13 als aktuellen methodischen
> Stand (maschinenlesbar: `thesis/evaluation/cross_pilot_comparability.json`).
> §9.13 bleibt als historischer Text unverändert stehen; seine 198-Zellen-
> Aussage ist NICHT mehr der aktuelle Gate-Stand.]**

## 6.1 Post-Commit-Provenance

Siehe POST-WAVE-3 PROVENANCE UPDATE oben: finaler Wave-3-Commit `730c0afe`,
Parent `69c1e478` (= Wave-3-Start-HEAD),
**WAVE3_REPORTED_TREE_MATCHES_COMMITTED_TREE = true**.

## 6.2 Interlock-Materialisierung

`thesis/evaluation/prompt_oracle_interlock.json` wurde kompatibel erweitert
(kein Consumer parst die Datei — verifiziert: Referenzen existieren nur in
Report-Prosa; keine Breaking-Änderung):

- **INTERLOCK_BENCHMARK_COUNT = 7**
- **INTERLOCK_PROMPT_PAIR_COUNT = 21** (aus dem finalen Artefakt validiert,
  duplikatfrei)
- Jeder Eintrag trägt `parallelism_models: ["serial", "omp", "mpi"]`
  (kanonische Reihenfolge) und eine deterministische `prompt_pairs`-Projektion
  mit `prompt_id = f"{problem_type}/{name}/{parallelism_model}"` — die
  eingefrorene Wave-3-Atomaritätsregel materialisiert, nicht neu empirisch
  untersucht.
- **enforcement = `disclosure_required`** unverändert: kein automatischer
  Ausschluss, keine Suite-Verkleinerung, kein Verdict-Override; die
  Execution-Model-Metadaten dienen nur eindeutiger Adressierbarkeit.

## 6.3 F0-Machbarkeit (historische Evidenzbasis)

Aus den tatsächlichen frozen pilot_001-Iteration-0-Records (Basisrun,
`run_id == "pilot_001"`; **396 Zellen** = 12 Benchmarks × 3 Execution Models ×
11 Modelle × 1 Sample — NICHT die 1903 Overview-/Repair-/Analyse-Rows):

- **HISTORICAL_CORRECTNESS_SCHEMA_VERSION = `correctness.v1`** (explizites
  Feld in allen 396 Records).
- Strukturierte Felder in jedem Record: `schema_version, run_id, model_id,
  sample_id, execution_model, created_at_utc, compile{ok, exit_code,
  timed_out, duration_seconds, stderr}, runs[]{params, argv, exit_code,
  timed_out, duration_seconds, validation, verdict, stdout, stderr
  [, mismatches, mismatch_total]}, run_verdicts, verdict`.
- **PILOT_001_STDOUT_AVAILABLE = true** — pro Run gespeichert; 1129 von 1144
  Run-Einträgen non-empty (die 15 leeren sind exakt die Crash-/Timeout-Runs).
- **PILOT_001_STDOUT_TRUNCATED_CELLS = 0** — keine Trunkierungsmarker, max.
  Länge 389 Zeichen (weit unter jeder Kappungsgrenze); die Treiber-eigene
  Anzeige von max. 3 MISMATCH-Zeilen ist Ausgabeformat, keine
  Record-Trunkierung. Nicht aus der heutigen OUTPUT_CAP-Konstante geschlossen.
- **Explizite Feststellung: Historisches stdout wurde NICHT mit dem heutigen
  authentifizierten Nonce-Parser als Verdictvergleich re-parst.** pilot_001
  datiert vor der Nonce-Einführung; die nackte Legacy-Zeile
  `Validation: PASS` durch den heutigen Parser zu schicken erzeugte
  `HarnessTransportError` — eine Protokollinkompatibilität der Messapparatur,
  kein inhaltlicher Verdictbefund. Die F-Analyse ist klassen- und
  code-/recordstruktur-basiert.

## 6.4 F-Änderungsklassen (F = WAVE1_TRANSPORT_CHANGE, getrennt von A–E)

| ID | Beschreibung | Source | Klassifikation | Erreichbarkeitsfilter / historische Evidenz |
|---|---|---|---|---|
| K1 | Authentifizierter Nonce-Transport (parevalEmitValidation, per-Launch-Token, fail-closed Parser) | Wave-1 §2–§5; `harness-markers.hpp`, `run_correctness.py` | **TRANSPORT_ONLY** | Verdictberechnung unverändert; Wave-1-Tests belegen korrekte Nonce-Emission der trusted Driver (§3.3, §4, §12.1: 1125 Checks, real serial/omp/mpi); §8.2: 0 wirksame selbst-deklarierte Marker im vollständigen pilot_001-stdout-Korpus → kein historisches Verdict hing an einer unauthentifizierten Zeile. Kein Reparse nötig oder durchgeführt. |
| K2 | Non-finite REFERENCE → `BASELINE_INCOMPATIBLE` (aus Denominator entfernt; historisch NaN-blinder stiller Pass) | Wave-1 §3.4, §8.4, §9; `utilities.hpp:363–378, 425–428, 520–523` | **VERDICT_RELEVANT** | Benchmarkfilter: unerreichbar für diskrete Payloads (15/25/35); dense_la/00 in-principle erreichbar (ungepivotete Division `baseline.hpp:16`); scan/30 + transform/55 oracle-seitig unter Correctness-Inputs unerreichbar. Historische NaN-Referenzen strukturell unsichtbar (§8.4). |
| K3 | Size-Mismatch → expliziter FAIL (historisch `assert` unter `-DNDEBUG` entfallen → stiller Pass möglich) | Wave-1 §8.3, §13; `utilities.hpp:196–204, 401–408` | **VERDICT_RELEVANT** | Nur Container-Payloads (00/30/55); skalare Benchmarks (15/25/35) haben keinen Container im Graded Path. Ein stiller historischer Wrong-Length-Pass hinterlässt keine Record-Spur. |
| K4 | Non-finite CANDIDATE → erzwungener FAIL (historisch NaN-blinde Toleranz → stiller Pass möglich) | Wave-1 §8.3/§8.4, §12.1; `utilities.hpp:185–214, 430–438, 525–530` | **VERDICT_RELEVANT** | Konstruktiv unerreichbar für 15/25/35 (int/bool/size_t-Skalare, Non-Finite-Branches compile-time tot). Für 00/30/55 erreichbar; §8.4 fand 4 Correctness-Records mit non-finite `got=` (alle sichtbar = bereits FAIL); verdeckte NaN-Pässe sind aus frozen Records nicht bestimmbar. |
| K5 | Authentisches BI outranked Prozesszustand (timeout/crash/exit) und Modellverdict | Wave-1 §3.4, §12.1; `run_correctness.py:453–490, 639–653` | **VERDICT_RELEVANT** | Setzt einen erreichbaren BI-Zustand voraus; pilot_001 datiert vor dem BI-Vokabular (0 Marker in den Records). Für 15/25/35 unerreichbar (kein BI-Pfad kann feuern; der TEST_SIZE==0-Guard von 35 kann bei Correctness-Größe nicht greifen). |
| K6 | Repair-Terminalstatus `stopped_baseline_incompatible` | Wave-1 §6 (F3b); `orchestrator.py`, `run_repair.py`, `build_overview.py` | **VERDICT_RELEVANT** (Klassifikationsebene) | Außerhalb der 396-Zellen-Population (Repair-State); nachweislich 0 betroffene pilot_001-Records (0 BI-stop_reasons in 1903 Repair-Rows). |
| K7 | Legacy-Parser-Robustheitsfix (`driver_wrapper.py`: erstes Token nach Doppelpunkt) | Wave-1 §2.2, §5, §12.3 | **TRANSPORT_ONLY** | Identisches Parse-Ergebnis für alle intendierte Legacy-Ausgabe; reale Upstream-Regression rc=0 (§12.3). |

**NON_FINITE_REACHABLE je Candidate-Subset-Benchmark** (read-only
Code-Beurteilung, keine Oracle-/Comparator-Änderung):
dense_la/00 **true** (Oracle: ungepivotete Pivot-Division; Kandidat:
`vector<double>`-Payload) · graph/15 **false** (skalarer int) · reduce/25
**false** (skalarer bool) · scan/30 **true** (Kandidatenpfad; Oracle unter
Correctness-Inputs unerreichbar) · search/35 **false** (skalarer size_t) ·
transform/55 **true** (Kandidatenpfad; Oracle ohne Arithmetik). Integer-/
Bool-Pfade wurden entsprechend NICHT zellenweise über historische Records
untersucht.

## 6.5 Cross-Pilot-Candidate-Subset (Neubewertung der 198-Zellen-Aussage)

Die 6 Benchmarks der bisherigen 198-Zellen-Aussage, deterministisch aus dem
Wave-3-Report (§9.13 METHOD_UNCHANGED_SET) und den pilot_001-Records
rekonstruiert: dense_la/00_dense_la_lu_decomp, graph/15_graph_edge_count,
reduce/25_reduce_xor, scan/30_scan_prefix_sum,
search/35_search_search_for_last_struct_by_key, transform/55_transform_relu.

Ergebnis der klassenbasierten Prüfung:

- **CANDIDATE_SUBSET_BENCHMARKS = [graph/15_graph_edge_count,
  reduce/25_reduce_xor, search/35_search_search_for_last_struct_by_key]** —
  ausschließlich diskrete Skalar-Payloads; K2/K3/K4/K5 konstruktiv
  unerreichbar, K1/K7 transport-only → alle Zellen methodenstabil per
  Konstruktion, ohne Einzelrecord-/stdout-Analyse.
- **CANDIDATE_SUBSET_MODELS** = die 11 pilot_001-Modelle (aus Records):
  claude_fable_5, claude_opus_5, deepseek_v4_flash, deepseek_v4_pro,
  gemini_31_pro, gemini_36_flash, openai_gpt55, openai_gpt56_sol,
  qwen36_35b_a3b, qwen37_max, qwen3_coder_api.
- **CANDIDATE_SUBSET_EXECUTION_MODELS = ["serial", "omp", "mpi"]**.
- **CROSS_PILOT_SUBSET_CELLS_TOTAL = 99** (3 × 11 × 3 × 1).
- Über die ursprünglich vorgeschlagenen 198 Zellen:
  **TRANSPORT_VERDICT_PRESERVING = 99**, **TRANSPORT_VERDICT_CHANGED = 0**
  (kein konkreter Wechsel belegt), **TRANSPORT_EFFECT_UNRESOLVED = 99**
  (die 33er-Blöcke von 00/30/55).
- **Ausgeschlossen: dense_la/00, scan/30, transform/55** (99 Zellen).
  Grund: Floating-Point-Payloads; der pilot_001-Comparator war NaN-blind
  (`std::abs(a−b) > eps` ist für NaN nie true), ein verdeckter NaN-Pass
  hinterlässt keinerlei Record-Spur; ob eine konkrete historische PASS-Zelle
  betroffen ist, ist ohne Neumessung nicht bestimmbar. Fehlende Evidenz wurde
  ausdrücklich NICHT als verdict-preserving interpretiert. (Zulässiger
  Kurzschluss des Kontrakts, benchmarkweise angewandt: keine vollständige
  Per-Zellen-Tabelle für die ausgeschlossenen 99 Zellen erforderlich, da die
  Nichtbestimmbarkeit klassenbasiert feststeht; einzelne FAIL-Zellen dort
  tragen finite Mismatch-Evidenz und sind plausibel preserving, es wird aber
  bewusst kein Per-Zellen-Anspruch erhoben.)

## 6.6 Aktualisierte Cross-Pilot-Klassifikation

**PILOT_SUBSET_ONLY_QUANTITATIVE_COMPARISON_DEFENSIBLE_WITH_EXCLUSIONS.**

Die quantitative Vergleichbarkeit ist **formal zulässig, praktisch/statistisch
schwach**, ausdrücklich begrenzt durch:

- genau **1 Sample pro Zelle** — keine Innerhalb-Zelle-Varianzschätzung;
- nur **12/60** Benchmarks in pilot_001, davon nur noch **3** quantitativ
  vergleichbar (**99 von 396 Zellen**);
- **doppelte Subset-Selektion** (stratifizierte Pilotauswahl, dann
  Methodenstabilitätsfilter) und strukturelle Selektion: die verbleibenden
  Benchmarks sind ausschließlich skalare Diskret-Output-Aufgaben — die
  einfachste Output-Klasse; Ergebnisse generalisieren nicht auf die Suite;
- **PILOT_002_REUSES_PILOT_001_GENERATIONS = UNDECIDED**.

Die Klassifikation behauptet NICHT, pilot_001 sei eine starke, präzise oder
belastbare quantitative Baseline. Die frühere 198-Zellen-Aussage (§9.13) ist
damit zurückgenommen und ersetzt; der historische Reporttext war zum damaligen
Kenntnisstand formuliert und bleibt unverändert stehen. **A∪B∪C∪D∪E = 34/60
bleibt ausschließlich die benchmarkbezogene A–E-Änderungsmenge; F =
WAVE1_TRANSPORT_CHANGE bleibt eine separate, suite-/zellenbezogene
Messpipeline-Dimension und wird nicht in die Union gezählt.**

## 6.7 Staleness-Provenance

- **state_commit = `730c0afe5fcfee2272fcdb8c12ea3ad58e3f923f`**
- Candidate-Subset-Benchmarks: 3; je Benchmark gespeichert: `cpu_cc_sha256`
  (vorhanden 3/3, Rohbytes), `baseline_hpp_sha256` (3/3, Rohbytes),
  `prompt_sha256.{serial,omp,mpi}` (9/9, UTF-8 des modellseitigen
  Promptstrings, Identitäts-Join, nie Arrayposition),
  `enhanced_spec_keys_sha256` (3/3 verfügbar; kanonisch sortierte
  benchmarklokale Projektion der `specs.jsonl`-Rohzeilen — Änderungen an
  Specs ANDERER Benchmarks machen dieses Gate nicht stale; Projektionsumfang
  10/9/8 Zeilen).
- **CROSS_PILOT_GATE_STALE = false** — durch tatsächliches erneutes Hashen
  unmittelbar nach Erzeugung verifiziert (18/18 Fingerprints identisch), kein
  manuelles Flag; Negativkontrolle: eine manipulierte Artefaktkopie meldet
  STALE (Exit 1) mit `comparability_re_evaluation_required`.
- **STALENESS_RECOMPUTABLE = true** — die autoritative Prüfung ist das
  Neu-Hashen unter den in `thesis/evaluation/check_cross_pilot_gate.py`
  dokumentierten Regeln (Exit 0 = frisch, 1 = stale, 2 = UNRESOLVED). Ein
  Hash-Diff erzwingt Re-Evaluation der Vergleichbarkeit und erzeugt NICHT
  automatisch eine neue Klassifikation; ein nicht mehr adressierbarer
  Zustand ergibt UNRESOLVED, nie stillschweigend false.

## 6.8 Aktuelles maschinenlesbares Gate

**`thesis/evaluation/cross_pilot_comparability.json` ist der aktuelle
Cross-Pilot-Gate-Stand** (`supersedes_wave3_report_cross_pilot_claim: true`).
Spätere Waves dürfen die 198-Zellen-Prosa aus §9.13 NICHT als aktuellen
Gate-Stand übernehmen; maßgeblich sind ausschließlich dieses Artefakt und
sein Staleness-Checker.

---

# FINAL CROSS-PILOT SHARED/EVALUATION STATE STALENESS UPDATE

> **[NACHTRAG — hinzugefügt von der finalen Gate-Cleanup-Mini-Wave
> (2026-08-28), NICHT Teil der historischen Texte oberhalb. Diese Mini-Wave
> hat KEINE neue Cross-Pilot-Analyse durchgeführt: die Ergebnisse
> 99 retained / 0 demonstrated changed / 99 unresolved, die
> F-Klassen K1–K7, das Candidate-Subset und die Klassifikation
> `PILOT_SUBSET_ONLY_QUANTITATIVE_COMPARISON_DEFENSIBLE_WITH_EXCLUSIONS`
> sind unverändert. Geändert wurde ausschließlich die spätere
> Drift-Erkennbarkeit des Gates.]**

## Warum benchmarklokale Hashes allein nicht ausreichten

Die bisherige Stalenessprüfung (Abschnitt 6.7) deckte cpu.cc, baseline.hpp,
die drei Promptstrings und die benchmarklokale Enhanced-Spec-Projektion ab.
Das Verdict desselben Kandidatencodes kann sich aber auch ändern, ohne dass
eine dieser Quellen ein Byte ändert: durch Änderungen an gemeinsamen
Comparator-/Transport-/Driver-/Enhanced-Dateien, an der
Modellgenerationsbedingung oder an der Auswertungsbedingung (Launch-Grid,
Compilerflags, NDEBUG, Problemgröße, Timeouts). Das Gate friert deshalb
jetzt zusätzlich `shared_state` ein: 12 gemeinsame Dateien (Rohbyte-SHA-256)
plus `generation_condition_sha256` und `evaluation_condition_sha256` als
kanonische Projektionen. Jede relevante Änderung — benchmarklokal, shared,
Generation Condition oder Evaluation Condition — löst mechanisch
`CROSS_PILOT_GATE_STALE = true` aus.

## Shared-State Dependency Inventory (produktive Pfade, read-only bestimmt)

| Datei | Granularität | Begründung (Kurzform) |
|---|---|---|
| drivers/cpp/utilities.hpp | **semantic** | gemeinsamer Comparator-Kern: Finite-/Non-Finite-Logik, Scalar-/Vector-Helfer, Mismatch, BI-Emitter, MAX_VALIDATION_ATTEMPTS-Default |
| drivers/cpp/harness-markers.hpp | **semantic** | authentifizierter Marker-Transport (parevalEmitValidation, Nonce, BI-/Validation-Format) |
| drivers/cpp/enhanced-fill.hpp | **semantic** | Enhanced-Input-Semantik (Patterns, Runtime-Fill, ENHANCED_TEST_SIZE) |
| drivers/cpp/models/serial-driver.cc | **semantic** | gemeinsamer Serial-Driver-Main (Validation-Aufrufpfad, argv-Vertrag) |
| drivers/cpp/models/omp-driver.cc | **semantic** | gemeinsamer OMP-Driver-Main (argv[1]=Threads, festes NITER, Validation-Pfad) |
| drivers/cpp/models/mpi-driver.cc | **semantic** | gemeinsamer MPI-Driver-Main (Rank-Setup, Root-Verdict-Pfad) |
| thesis/evaluation/build_config.py | **semantic** | deklarierte Single Source of Truth für Compile+Launch (Flags, USE_*, Compiler, Default-Grids) |
| thesis/evaluation/run_correctness.py | **coarse** | echte Verdictsemantik (Parser, BI, Prioritäten) PLUS CLI/Config/Logging/Runnerlogik |
| thesis/evaluation/framework.py | **coarse** | run_command (Timeout-/Exit-Erfassung → timeout/runtime_error) plus operativer Code |
| thesis/evaluation/run_enhanced_tests.py | **coarse** | produktiver Enhanced-Ausführungs-/Verdictpfad plus Runner-/CLI-Code |
| thesis/enhanced_tests/specs.py | **semantic** | Spec-Interpretation, build_benchmark_specs, spec_key-Identität |
| thesis/enhanced_tests/baseline_selftest.py | **coarse** | Enhanced-Baseline-Gate plus operativer Code |

Semantik der Granularität: Ein **semantic**-Diff ist mit hoher
Wahrscheinlichkeit methodisch relevant („shared semantic dependency
changed"). Ein **coarse**-Diff löst ebenfalls STALE aus, bedeutet aber nur
„Datei geändert; prüfen, ob der Diff die relevante Mess-/Verdictsemantik
betrifft" — er ist KEIN Beweis einer Semantikänderung. Der Checker-Output
zeigt die Granularität je Datei an und formuliert entsprechend.
Bewusst NICHT aufgenommen: Tests, Reports, Dokumentation, rein analytische
Skripte; `thesis/evaluation/tools.py` (der einzige verdictrelevante Wert,
`DRIVER_PROBLEM_SIZE`, wird von der Evaluation Condition selbst erfasst —
eine Änderung dort macht das Gate über `evaluation_condition_sha256` stale).

## Generation Condition

`generation_condition_sha256 = e22ce9beb2bd9f9d85940a00585b6017eae389ad8bb933acda99f45f2d7d3281`
— **identische Felddefinition wie der Wave-3-Generation-Condition-Vergleich**
(§9.9), empirisch bestätigt: der neu berechnete Hash reproduziert exakt den
dort dokumentierten Params-Hash. Kanonische Projektion: `generation_defaults`
(inkl. system_prompt, temperature, top_p, max_output_tokens, api_mode,
api_mode_overrides, retry_attempts, sleep_seconds_between_requests,
timeout_seconds) plus alle Modellfelder außer den Preisen, Modelle nach
stabiler Modell-ID; kanonisches JSON (sort_keys, Separatoren `(",", ":")`,
UTF-8), SHA-256. **Keine Secrets** (api_key_env ist ein
Umgebungsvariablen-NAME), keine Preise, keine run_id, keine Pfade, keine
Profile. Keine komplette config.yaml byteweise gehasht.
**GENERATION_CONDITION_RECOMPUTABLE = true.**

## Evaluation Condition

`evaluation_condition_sha256 = 7f53b0903e3d5e2be2ca4de8bd085da00d3cc6e9e350fc03bf390cac66c35e74`
— kanonische Projektion der verdictrelevanten Correctness-
Auswertungsbedingung, zur Prüfzeit deterministisch aus den produktiven
Quellen rekonstruiert (build_config.py, tools.py, run_correctness.py,
utilities.hpp, config.yaml `stages.correctness_tests`). Enthalten:

- **Launch-Grid**: serial direkt (argv[1]=niter); omp Threads **1, 2, 4, 8**
  (argv[1] + OMP_NUM_THREADS; Driver-internes NITER fest 5); mpi Ranks
  **1, 2, 4, 8** via `mpirun -np` — keine `launch_overrides` in der Config
  (null).
- **niter = 1** (Config), **MAX_VALIDATION_ATTEMPTS = 2** (utilities.hpp-
  Default, per Regex extrahiert; kein `-D`-Override im Build).
- **Compiler/Flags**: serial/omp `g++` (produktiver CLI-Default), mpi
  `mpicxx`; je Modell geordnete Flagliste `-std=c++17 -O3 [-fopenmp]
  -DUSE_* -DDRIVER_PROBLEM_SIZE=(1<<8)` (Original-Flagreihenfolge erhalten,
  nur Dict-Keys kanonisch sortiert).
- **NDEBUG**: `ndebug_defined = false` — im produktiven Correctness-Build
  wird NDEBUG NICHT definiert (explizit repräsentiert, da die historische
  Size-Mismatch-Semantik davon abhing).
- **DRIVER_PROBLEM_SIZE = (1<<8)** (Correctness-Problemgröße; nicht mit der
  Enhanced-Test-Size vermischt).
- **build_timeout_seconds = 120.0**, **run_timeout_seconds = 120.0**
  (Timeouts erzeugen direkt build_failed/timeout/runtime_error).
- Bewusst ausgeschlossen (verdictinvariant/operativ): Include-Pfade,
  `MISMATCH_REPORT_MAX` (reiner Anzeige-Cap), run_id, Output-/Cache-/
  Report-Pfade, Logging.

**EVALUATION_CONDITION_RECOMPUTABLE = true.**

## Coverage-Matrix

Maschinenlesbar im Gate (`staleness_coverage`): benchmark_semantics,
oracle_semantics, validator_semantics, enhanced_test_semantics,
prompt_semantics (je: benchmarklokale Hashes + zugeordnete shared Dateien),
generation_condition (`generation_condition_sha256`), evaluation_condition
(`evaluation_condition_sha256`) — alle `coverage_complete = true`.
`validity.invalidated_by_changes_to` enthält jetzt zusätzlich
`generation_condition` und `evaluation_condition`.
**SHARED_STATE_COVERAGE_COMPLETE = true**, mit zwei transparent
dokumentierten Scope-Grenzen (keine verdeckten Lücken): (1) der
Generation-/Assembly-PIPELINE-CODE (Modellantwort → Kandidatenquelle) ist
keine der sieben Kategorien und wird nicht gefingerprintet; (2)
Umgebungszustand (Container-Image, Compiler-Binärversionen) ist kein
Repo-Dateizustand und wird nicht gehasht (operativ über das gepinnte
Container-Image adressiert).

## Checker-Erweiterung und Negativkontrollen

[check_cross_pilot_gate.py](thesis/evaluation/check_cross_pilot_gate.py)
prüft jetzt vier Gruppen (`BENCHMARK_LOCAL_STATE`, `SHARED_STATE` mit
sichtbarer Granularität, `GENERATION_CONDITION`, `EVALUATION_CONDITION`);
Exit 0 = frisch, 1 = STALE (jeder reproduzierbare Hash-Diff), 2 =
UNRESOLVED (nicht mehr adressierbare notwendige Quelle — nie stillschweigend
false). Ein Hash-Diff verlangt weiterhin nur
`comparability_re_evaluation_required` und erzeugt keine neue
Klassifikation, kein neues Subset, keine neuen Zellzahlen. Benötigt PyYAML
(Repo-venv oder Analyse-Container).

Negativkontrollen (ausschließlich an Scratch-Kopien, kein Produktivzustand
verändert): benchmarklokal → Exit 1 · shared semantic (utilities.hpp) →
Exit 1 mit `granularity=semantic` · shared coarse (run_correctness.py) →
Exit 1 mit `granularity=coarse` und ohne Semantikänderungs-Behauptung
(Verbots-Substring geprüft) · generation_condition → Exit 1 ·
evaluation_condition → Exit 1 · nicht mehr adressierbare Quelle → Exit 2.
Alle 6 bestanden.

## Aktueller Zustand

- **CROSS_PILOT_GATE_STALE = false** (Current-State-Checker Exit 0 auf
  `state_commit 4e0e9159a58ec7c46f64867bc3391f5bc7923462`; durch
  tatsächliches Neu-Hashen bestimmt, kein manuelles Flag)
- **STALENESS_RECOMPUTABLE = true**
- Eingefrorener Cross-Pilot-Inhalt vor/nach der Erweiterung byte-identisch
  verifiziert: Candidate-Subset (Benchmarks/Modelle/Execution
  Models/99 Zellen), Klassifikation, transport_effect-Counts (99/0/99),
  non_finite_reachable-Tabelle, statistical_caveats, candidate_subset_state.
- Offene methodische Policy-Frage vor pilot_002 (hier NICHT entschieden):
  **QUANTITATIVE_99_CELL_SUBSET_VS_QUALITATIVE_PILOT_001 = OPEN** — ob die
  formal zulässige quantitative 99-Zellen-Auswertung als quantitative
  Thesis-Evidenz verwendet wird oder pilot_001 ausschließlich qualitativ
  als Findings-/Debugging-Pilot berichtet wird, ist eine separate
  Publikationsentscheidung.

---

# FINAL PILOT-CONDITION CLOSURE: INVOCATION / ASSEMBLY / ENVIRONMENT

> **[NACHTRAG — hinzugefügt von der finalen Pilot-Condition-Closure-Mini-Wave
> (2026-08-28), NICHT Teil der historischen Texte oberhalb. KEINE neue
> Cross-Pilot-Analyse, KEINE neue Candidate-Subset-Auswahl, KEINE
> Publikationsentscheidung: Klassifikation, 99/0/99, K1–K7, Subset und
> Caveats sind byte-identisch verifiziert. Geschlossen werden ausschließlich
> drei Drift-Erkennungs-Lücken: effektive Invocation, Assembly-Semantik,
> Environment-Zustand.]**

## Invocation-Lücke und Policy

Der `evaluation_condition`-Hash friert den Config-/Default-Zustand ein; der
reale Runner erlaubt aber runtimewirksame CLI-Overrides. Read-only-Inventur
aller 6 CLI-Optionen von `run_correctness.py`: **alle sind verdict- oder
populationsrelevant** — `--primary-compiler` (Default g++, Wahl g++|clang++),
`--run-timeout` (überschreibt Config 120 s stillschweigend), `--config`
(gesamte Laufzeitkonfiguration), `--profile`/`--run-id` (Population via
run_id, inkl. Repair-Iterationspopulationen), `--model-id`
(Populationsrestriktion); rein kosmetische Flags existieren nicht.
Konkrete, dokumentierte **Provenance-Lücken**: der effektive
`--run-timeout`-Wert wird **nirgends** persistiert (weder Manifest noch
Records — nur `timed_out`-Booleans, nie das geltende Limit); der Manifest
friert `primary_compiler` nur beim ersten Stage-Kontakt ein (spätere
abweichende Invocations unsichtbar, kein config_drift); das Compile-argv
wird nicht pro Record gespeichert; die ambiente Umgebung (PATH-Auflösung von
g++/mpicxx/mpirun, `OMP_*`/`OMPI_MCA_*`) fließt vollständig und
unaufgezeichnet in jeden Build/Run.

**Gewählte Policy** (`effective_invocation_policy`, konservativ, ohne
Runner-Umbau): `mode = must_match_frozen_evaluation_condition` — pilot_002
muss die eingefrorene Evaluation Condition verwenden; verdictrelevante
Overrides sind entweder nicht gesetzt oder ihr effektiver Wert muss vor dem
Run maschinenlesbar materialisiert und gegen das Gate geprüft werden (keine
stillschweigende Mischung). Erwartete Werte (aus dem produktiven Zustand
abgeleitet): `primary_compiler = g++`, `run_timeout_seconds = 120.0`;
Populationsconstraints: kein `--model-id` für den Basisrun, `--config`
content-adressiert über die eingefrorenen Condition-Hashes, run_id =
Basisrun (keine `__iterN`-Varianten). Bei Abweichung:
`PILOT_CONDITION_MATCH = false` → `CROSS_PILOT_GATE_STALE = true` →
`pilot_002_not_authorized`. **EFFECTIVE_INVOCATION_RUNTIME_CHECK =
REQUIRED** — der Repo-Checker validiert nur die Reproduzierbarkeit der
ERWARTETEN Werte und behauptet ausdrücklich nicht, eine künftige
tatsächliche Invocation geprüft zu haben.

## Assembly-State

Produktionspfad read-only verifiziert: `generations.jsonl` →
`assemble_sources.assemble_model` → `cleaning.clean_for_assembly`
(Fence-Extraktion, Prose-Stripping, Signatur-Dedup inkl. NO_INLINE-Variante,
Include-Relocation, kommentar-/string-bewusste Brace-Balance) →
`assemble_content` → `generated-code.hpp`; der Repair-Loop nutzt denselben
Pfad. Gate-Erweiterung `assembly_state`:

- `thesis/assembly/cleaning.py` — SHA-256 `3fadc217…`, **granularity =
  semantic** (alle 420 Zeilen reine Transformationssemantik, pure Funktion
  von (prompt_text, raw_text), kein CLI/IO).
- `thesis/assembly/assemble_sources.py` — SHA-256 `f610284d…`,
  **granularity = coarse** (Konstruktionskern ~50/335 Zeilen plus
  CLI/IO/Reporting/Exporter).
- `assembly_condition_sha256 = a1488514eb2482a27fd07ba3170a7d0ef5ce2d07358852b95e5a86b08c14cb4c`
  — kanonische Projektion `{stage: assembly, auto_close_single_brace: true}`;
  per Audit ist `stages.assembly.auto_close_single_brace` die **einzige**
  Configoption, die `generated-code.hpp`-Bytes verändert (übrige
  Stage-Optionen unkonsumiert bzw. nur Pfade/Reporting; keine komplette
  Config byteweise gehasht).

Ein Assembly-Diff löst STALE/Exit 1 aus und verlangt Re-Evaluation — er ist
kein automatisch bewiesener Vergleichbarkeitsverlust.
**Assembly-Coverage: complete = true.**

## Environment-Condition und Container-Pinning

Vorhandene Provenance wiederverwendet: Die pilot_001-Toolchain ist
authoritativ in `thesis/results/intermediate/pilot_001/toolchain-versions.txt`
aufgezeichnet (containergebackenes `/opt/toolchain-versions.txt`, Image-Build
2026-07-31); der Manifest selbst trägt `primary_compiler="g++"`, aber
`primary_compiler_version=null` / `toolchain_versions=null`, weil er
host-seitig von der Generation-Stage eingefroren wurde. Eingefrorene
erwartete Werte (aus der Provenance-Datei abgeleitet, nicht hartcodiert):
Compiler **`g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`**, MPI **Open MPI**,
Zeile **`mpirun (Open MPI) 4.1.6`**, Container `pareval-thesis`
(FROM `ubuntu:24.04`).

**CONTAINER_IMAGE_PINNING = TAG_ONLY** — ehrlich klassifiziert: kein
`@sha256:`-Digest in irgendeinem Dockerfile/Runbefehl, kein Image-Digest/-ID
in irgendeinem Provenance-Artefakt; `FROM ubuntu:24.04` und ungepinnte
apt-Pakete sind KEINE Digest-Reproduzierbarkeit (die Repo-eigene
Readiness-Review führt dies bereits als Befund R12). Die
`toolchain-versions.txt` spiegelt Image-BUILD-Zeit, nicht Laufzeit — ein
neu gebautes Image kann still driften. Deshalb:
**ENVIRONMENT_RUNTIME_CHECK = REQUIRED**: Vor pilot_002 müssen im
Ausführungscontainer `g++ --version`, `mpirun --version` und die konkrete
Image-ID/der Digest erfasst und per Preflight verglichen werden; fehlende
Runtime-Provenance ist UNRESOLVED und blockiert den Pilot (nie als Match
interpretiert). **Environment-Coverage: complete = false** (transparent).

## Preflight-Contract und Checker-Erweiterung

Neu: [pilot_preflight.py](thesis/evaluation/pilot_preflight.py) (read-only)
vergleicht eine materialisierte effektive Invocation (`--invocation`) und
die tatsächliche Laufzeitumgebung (`--environment`) gegen das Gate:
`PILOT_CONDITION_MATCH` / `PILOT_ENVIRONMENT_MATCH` = true/false/UNRESOLVED;
Exit 0 nur bei Repo-Gate frisch UND beiden Matches; Mismatch → Exit 1
(`pilot_002_not_authorized`, Re-Evaluation, keine Neuklassifikation);
fehlende Provenance → Exit 2. Im Gate materialisiert als `pilot_preflight`
mit `required_checks = [cross_pilot_repo_state_fresh,
effective_invocation_matches, runtime_environment_matches,
interlock_disclosure_ready]` und `on_failure = pilot_002_not_authorized`.

[check_cross_pilot_gate.py](thesis/evaluation/check_cross_pilot_gate.py)
prüft jetzt sieben Gruppen (zusätzlich `ASSEMBLY_STATE`,
`EFFECTIVE_INVOCATION_POLICY` repo-seitig, `ENVIRONMENT_CONDITION`
repo-seitig) und unterscheidet im Schlussurteil explizit
**CROSS_PILOT_REPO_STATE_STALE** vom separaten Runtime-Match — keine falsche
Sicherheit durch Gleichsetzung von CLI-Default und tatsächlicher Invocation.
`validity.invalidated_by_changes_to` umfasst jetzt zehn Kategorien (neu:
`assembly_semantics`, `effective_invocation`, `environment_condition`);
die Coverage-Matrix wurde entsprechend erweitert (assembly complete=true;
invocation/environment ehrlich complete=false mit dokumentierten
Runtime-Preflight-Pflichten).

## Negativkontrollen und aktueller Status

Alle nur an Scratch-Kopien/Scratch-JSONs: Assembly-Datei → Exit 1
(semantic-Wortlaut) · assembly_condition → Exit 1 · Invocation-Timeout
120→60 → `PILOT_CONDITION_MATCH = false`, Exit 1 · Compiler g++→clang++ →
false, Exit 1 · MPI-Versions-Mismatch → `PILOT_ENVIRONMENT_MATCH = false`,
Exit 1 · fehlende Compiler-Provenance → UNRESOLVED, Exit 2 (nie true) ·
Positivkontrolle (alles passend) → Exit 0. Die sechs bestehenden
Kontrollen (benchmark-local, shared semantic/coarse, generation/evaluation
condition, unresolved) weiterhin grün; Comparator-Regression Exit 0.

**Aktueller repo-seitiger Status: CROSS_PILOT_REPO_STATE_STALE = false**
(Exit 0 auf `state_commit 496c03745919a29b2afacfca13b093857d82a931`),
STALENESS_RECOMPUTABLE = true. Runtime-Checks (Invocation + Environment)
bleiben vor pilot_002 verpflichtend offen.

---

# FINAL PILOT PREFLIGHT DECLARATION / POPULATION HARDENING

> **[NACHTRAG — hinzugefügt von der finalen Preflight-Hardening-Mini-Wave
> (2026-08-28), NICHT Teil der historischen Texte oberhalb. KEINE
> Cross-Pilot-Neuanalyse: Klassifikation, Candidate Subset,
> candidate_subset_state und 99/0/99 sind byte-identisch verifiziert. KEINE
> pilot_002-Populations- oder Run-ID-Entscheidung, keine Config-Änderung.]**

## Ursprünglicher Preflight-Gap

`pilot_preflight.py` prüfte bisher im Wesentlichen nur `primary_compiler`
und `run_timeout_seconds`, obwohl `--config`, `--profile`, `--model-id` und
`--run-id` gleichermaßen verdict- bzw. populationsrelevant sind (Inventur
der vorherigen Mini-Wave: alle 6 CLI-Flags von `run_correctness.py`
relevant). Zudem war der Preflight nicht als das gekennzeichnet, was er ist:
eine **Deklarationsprüfung**, keine Laufzeitdurchsetzung.

## Vollständige Invocation-Deklaration (Self-Declaration)

`invocation.json` muss jetzt die vollständige GEPLANTE effektive Invocation
beschreiben (Werte NACH Anwendung von CLI-Overrides, nicht raw argv):
`config_path`, `profile`, `effective_run_id`, `selected_model_ids`,
`primary_compiler`, `run_timeout_seconds`, `model_id_cli_override`.
Fehlende Pflichtfelder → `PILOT_CONDITION_MATCH = UNRESOLVED`, Exit 2.
Im Gate und im Tool-Output materialisiert:
**`INVOCATION_SELF_DECLARED = true`** und
**`PREFLIGHT_IS_DECLARATION_CHECK_NOT_ENFORCEMENT = true`** — ein
bestandener Preflight bedeutet nur „die deklarierte geplante Invocation ist
mit dem Gate kompatibel", NICHT „der spätere tatsächliche Lauf ist bewiesen".

## Content-addressed Config-Prüfung

Der Configpfad ist nicht die methodische Identität. Der Preflight lädt die
deklarierte Config und projiziert sie durch die **bestehenden**
autoritativen Definitionen (`generation_condition_projection` /
`evaluation_condition_projection` aus `check_cross_pilot_gate.py`, minimal
refaktoriert um einen optionalen expliziten Configpfad — Default-Verhalten
unverändert, beide eingefrorenen Hashes `e22ce9be…`/`7f53b090…` exakt
reproduziert, keine zweite Condition-Definition). Abweichung →
`CONFIG_GENERATION_CONDITION_MATCH = false` bzw.
`CONFIG_EVALUATION_CONDITION_MATCH = false` → Exit 1.

## pilot_002-Population: eigenständiger offener Sollzustand

Die pilot_001-Population (stratified / 36 / **1 Sample pro Zelle**) wird
ausdrücklich NICHT als pilot_002-Soll übernommen — 1 Sample/Zelle ist eine
dokumentierte pilot_001-Schwäche; eine bewusste Erhöhung wäre eine
methodische Verbesserung und darf vom Preflight nicht blockiert werden.
Neu im Gate: `expected_pilot_002_population` mit
`selection/prompt_limit/num_samples_per_prompt = null`,
**`status = NOT_YET_DECIDED`**. Solange nicht DECIDED:
`PROFILE_POPULATION_MATCH = UNRESOLVED`, `PILOT_002_POPULATION_READY =
false` — ausdrücklich KEIN Mismatch gegen pilot_001. Offen:
**PILOT_002_POPULATION_DECISION = OPEN**, insbesondere
**PILOT_002_NUM_SAMPLES_PER_PROMPT = OPEN**.

## pilot_002-Basisrun-ID: eigenständig, nicht konfiguriert

Die Config trägt weiterhin `pilot.run_id = pilot_001`; dieser Wert wird
NICHT als erwartete pilot_002-Run-ID gespeichert. Neu:
`expected_pilot_002_base_run` mit `run_id = null`,
**`status = NOT_YET_CONFIGURED`**, `forbid_iteration_variants = true` →
`RUN_ID_MATCH = UNRESOLVED`, `PILOT_002_BASE_RUN_ID_READY = false`.
Unabhängig davon werden reservierte/iterative IDs IMMER abgelehnt
(`pilot_001`, `smoke_*`, `full_*`, `repair_smoke_*`, `model_check_*`,
jedes `__iter`-/Varianten-Suffix): ein Repair-Iteration-Run kann den
Basisrun-Preflight nie bestehen.

## Modellpopulation vs. Generation Condition (keine doppelte Source of Truth)

Der Generation-Condition-Hash friert bereits ein, WELCHE Modellpopulation
die Config definiert (enabled, Provider, Modellname, Reasoning-Config). Der
separate Modellpopulationscheck prüft ausschließlich, ob die konkrete
geplante Invocation diese **vollständige** Population AUSFÜHRT:
`set(selected_model_ids) == set(enabled ids der validierten Config)`;
`model_id_cli_override != null` → `MODEL_ID_RESTRICTION_PRESENT = true` →
`MODEL_POPULATION_MATCH = false` → Exit 1 (Targeted Smokes/Debug-Runs sind
keine Basis-Piloten).

## Interlock-Zuständigkeit und Post-Run-Nachweis

Die frühere Inkonsistenz (`interlock_disclosure_ready` in
`required_checks`, obwohl das Tool dies nie prüfte) ist behoben:
`pilot_preflight` unterscheidet jetzt `tool_checks` (10 tool-eigene
Dimensionen) von `external_final_gate_checks`
(`interlock_disclosure_ready`, `pilot_002_population_decided`,
`pilot_002_base_run_id_configured`, `reuse_decision_ready`,
`publication_policy_ready`) — das Tool behauptet nie, externe Gates geprüft
zu haben. Ein erfolgreicher Lauf meldet
`technical_cross_pilot_preflight_passed` UND
`final_pilot_gate_still_required`, niemals „pilot_002 fully authorized".
**`POST_RUN_MANIFEST_VERIFICATION = REQUIRED_NOT_IMPLEMENTED`** ist im Gate
materialisiert: Der nachlaufende read-only Abgleich des tatsächlichen
pilot_002-`run_manifest.json` (frozen Config, effektiver Compiler,
Run-Identität, Config-Drift, Toolchain-Provenance) gegen das Gate ist ein
späterer Pflichtschritt; `run_manifest.py` blieb unverändert (bekannte
Lücke dort weiterhin dokumentiert: effektiver `--run-timeout` wird nicht
persistiert). PRE-RUN (geplante Bedingung kompatibel?) und POST-RUN
(tatsächlich so gelaufen?) sind sprachlich und strukturell getrennt.

## Environment-Wording

`PILOT_ENVIRONMENT_TOOLCHAIN_COMPATIBLE` (Compiler-/MPI-Version passen zur
aufgezeichneten Toolchain) ist von
`PILOT_RUNTIME_IMAGE_IDENTITY_CAPTURED` (aktuelle Image-ID/Digest erfasst)
getrennt; `PILOT_ENVIRONMENT_MATCH` ist explizit definiert als „recorded
toolchain condition compatible AND required current runtime provenance
present" — da pilot_001 keinen Digest aufzeichnete, ist eine heutige
Image-ID ausdrücklich KEIN Beweis historisch identischer Container-Identität
(das Tool sagt dies wörtlich; Wording-Kontrolle geprüft).

## Coverage-Semantik

Für `effective_invocation` gilt jetzt differenziert:
**`policy_coverage_complete = true`** (alle sechs CLI-Dimensionen deklariert
und geprüft bzw. gegated), **`runtime_declaration_check_required = true`**,
**`post_run_execution_verification_required = true`**;
`coverage_complete` bleibt ehrlich `false`, solange die konkrete zukünftige
Invocation unbekannt ist.

## Kontrollen

Alle nur in Scratch (Gate-Kopien, Scratch-Configs, Scratch-JSONs): falsche
Generation-Config → Exit 1 · falsche Evaluation-Config → Exit 1 ·
unbekanntes Profil → Exit 1 · Population NOT_YET_DECIDED →
UNRESOLVED/NOT_READY (Exit 2, kein pilot_001-Fallback, „NOT a mismatch
against pilot_001" verifiziert) · Modell-Teilmenge → Exit 1 ·
`model_id_cli_override` → Exit 1 · Run-ID NOT_YET_CONFIGURED →
UNRESOLVED/NOT_READY · falsche konfigurierte Run-ID (synthetisches Gate) →
Exit 1 · `pilot_002__repair__iter1` → `REPAIR_ITERATION_RUN = true`, Exit 1
· Populations-Mismatch bei DECIDED → Exit 1 · fehlendes Pflichtfeld →
Exit 2 · Environment-Wording-Kontrolle (keine
historische-Identitäts-Behauptung) → PASS · **synthetische
Complete-Policy-Positivkontrolle** (hypothetisch entschiedene Population
num_samples=3 + konfigurierte Run-ID `pilot_002` + passende Scratch-Config
mit hash-identischen Conditions) → **Exit 0** mit
`technical_cross_pilot_preflight_passed` + `final_pilot_gate_still_required`
· die vier früheren Preflight-Kontrollen (Timeout/Compiler/Env-Mismatch,
Env-Unresolved) auf das vollständige Deklarationsschema gehoben und grün ·
Gate-Bestandskontrollen (benchmark-local, shared semantic/coarse,
generation/evaluation condition, unresolved, assembly) grün ·
Repo-Checker Exit 0 · Comparator-Regression Exit 0.

Der **ehrliche aktuelle Zustand** des echten Gates ist NOT_READY (Exit 2)
für einen vollständigen Basisrun-Preflight — korrekt, solange Population
und Basisrun-ID offen sind; das ist kein Testfehler, sondern der
dokumentierte offene Final-Gate-Zustand.
