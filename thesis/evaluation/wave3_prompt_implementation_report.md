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
