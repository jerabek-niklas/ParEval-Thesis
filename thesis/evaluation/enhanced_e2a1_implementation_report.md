# Enhanced E2-A.1 — Implementation Report

Range Safety, Canonical Spec Semantics & Fail-Closed Capability Enforcement

---

## 1. Provenance

| | |
|---|---|
| Repository | `jerabek-niklas/ParEval-Thesis` |
| Branch | `thesis-static-analysis` |
| Start-HEAD | `3374aaf7218fbc007e6b75f1c0105b7753d585b0` („fixes 13") — **verifiziert**, nicht übernommen |
| Parent | `801c31f33e956e18d619590cb79d722685fa8601` („fixes 12", = E2-A-Basis) |
| Working Tree bei Start | **clean** — `git status --porcelain --untracked-files=all` leer; weder tracked noch untracked Änderungen |
| `.claude/` | gitignored, deshalb nicht einmal als untracked gemeldet; **nicht untersucht, nicht verändert** |
| End-HEAD | unverändert `3374aaf7…` — **kein Commit erstellt**, alle Änderungen liegen unkommittiert im Working Tree |

**Vorher-Läufe** (Repo-venv `.venv\Scripts\python.exe`; die System-Python-Installation hat kein PyYAML):

| Kommando | Exit |
|---|---|
| `check_enhanced_capabilities.py` | **0** (`ENHANCED_CAPABILITIES_CONSISTENT = true`) |
| `derive_enhanced_policy.py --check` | **0** (Policy = Derivation) |
| `test_capabilities.py` | **0** |
| `check_cross_pilot_gate.py` | **1 — STALE** (erwartet: fixes 13 hat bereits `enhanced-fill.hpp` und `specs.py` geändert) |

Keine Fingerprints aktualisiert — weder vorher noch nachher.

---

## 2. Bestätigte Auditbefunde (Ausgangslage)

Der read-only Codex-Audit nach E2-A hat drei reale Restlücken belegt. Alle drei
wurden vor der Implementierung an der Quelle nachvollzogen:

1. **VALUE_RANGE SAFETY.** `validate_spec` prüfte `value_range` nur auf
   „zwei Zahlen mit `lo <= hi`". NaN wurde dadurch nur **zufällig** abgelehnt
   (jeder Vergleich mit NaN ist falsch), `±Inf` wurde **akzeptiert**, und
   technisch nicht berechenbare Spannen wie `[INT_MIN, INT_MAX]`,
   `[-FLT_MAX, FLT_MAX]`, `[-DBL_MAX, DBL_MAX]` ebenso. Im Fill-Layer führte das
   zu signed overflow (`hi - lo`, `span + 1`), Modulo-/Division-by-zero in
   `fillRand`s Integralzweig (`rand() % (max - min)`), FPE und deterministischem
   NaN/Inf.
2. **PARAMETER-LEVEL FAKE DIVERSITY.** E2-A hat die *Pattern*-Fake-Diversität
   geschlossen, nicht die *Parameter*-Fake-Diversität: ein `k` auf einem
   Nicht-K-Pattern, eine `value_range` auf `all_zeros`/`extreme_values`/
   `explicit_values`, `values` neben `random`, oder überhaupt irgendein
   Fillparameter auf einem Benchmark ohne Fill-Hook erzeugte einen **anderen
   `spec_key` bei identischem Input**.
3. **POLICY FAILS OPEN.** `capabilities.load_policy()` lieferte bei fehlender
   Datei bewusst `{"benchmarks": {}}`; damit war die gesamte Enforcement still
   abgeschaltet. Ein Benchmark, den die Policy nicht kannte, galt als
   *unrestricted*. Der Consistency-Checker übersprang bei fehlender Policy alle
   P-Checks und lieferte **Exit 0**. Die Derivations-Exaktheitsprüfung existierte
   nur als CLI-Flag, nicht als verpflichtender Preflight.

Zusätzlich bestätigt und hier behoben: der Define-Pfad castete den
Range-Override mit `(decltype(lo))(ENHANCED_FILL_LO)` **vor** dem sicheren
Endpoint-Helper, also an jedem Call-Site mit integralen Literalen selbst — eine
out-of-range Floating→Integral-Konversion, die den E2-A-Helper vollständig
umging.

**Ausdrücklich nicht ausgeweitet** (Auftragsvorgabe): der `[c,c]`-Integral-Guard
aus fixes 13 bleibt unverändert und weiterhin ohne Reexecution-Bedarf; der
complex-Fill-Dispatch bleibt unverändert und erreicht weiterhin 0 produktive
Fill-Sites — die latente Template-Semantikabweichung bleibt als offene
technische Notiz (§20).

---

## 3. Range Safety Fix

**Python (produktive Specvalidation).** `capabilities.value_range_rejection`
beantwortet drei getrennte technische Fragen, in dieser Reihenfolge:

| # | Frage | Reason |
|---|---|---|
| 1 | Sind beide Endpunkte endliche Zahlen? | `non_finite_value_range` |
| 2 | Ist jeder Endpunkt in **jedem** vom Pattern erreichten Fill-Container darstellbar? | `range_not_representable_for_benchmark` |
| 3 | Kann die aktuelle Fillarithmetik die Spanne in diesen Containern berechnen? | `unsafe_value_range_span` |

Regel (3) ist **eine konservative Regel für alle range-lesenden Patterns**, keine
Teilpolicy pro Pattern. `alternating` würde technisch eine weitere Range
überleben als `ascending`; eine Ausnahme dafür würde nichts gewinnen (kein
existierender Spec braucht sie) und wäre genau die Art partieller Policy, die
diese Wave vermeiden soll.

Grenzwerte je Elementtyp (aus `fill_type_capability`, siehe §12):

| Typ | `value_min` | `value_max` | `max_finite_span` | Begründung |
|---|---|---|---|---|
| `int` | −2147483648 | 2147483647 | 2147483646 | `hi-lo` **und** `span+1` müssen in `int` passen (`position % (span+1)`) |
| `float` | −FLT_MAX | FLT_MAX | FLT_MAX | `hi-lo` muss in `float` endlich bleiben |
| `double` | −DBL_MAX | DBL_MAX | DBL_MAX | `hi-lo` muss in `double` endlich bleiben |

Bei mehreren Fill-Sites wird die **Schnittmenge** gebildet (`value_min` = Maximum
der Untergrenzen, `value_max` = Minimum der Obergrenzen, `max_finite_span` =
Minimum). Ein Benchmark der Suite (`sort/43`) hat gemischte Sites (`float`+`int`)
und bekommt dadurch automatisch die engere `int`-Grenze.

**Reject, nicht clip.** Es gibt keinen Clipping-, Saturations- oder Wrap-Pfad in
der Validation. Der Test „an unrepresentable range is rejected, not clipped"
prüft zusätzlich, dass `validate_spec` das abgelehnte Spec-Objekt **nicht
verändert**. Das ist bewusst **keine** `VALUE_RANGE_DOMAIN_POLICY`: beantwortet
wird ausschließlich „kann der Harness diesen Wert halten und damit rechnen", nie
„ist dieser Wert für die Aufgabe sinnvoll".

**C++ (defensiv, nicht nur Python).** `drivers/cpp/enhanced-fill.hpp`:

* `enhancedRangeSpanIsSafe<DType>(lo, hi)` — dieselbe Regel im Header;
  integral über den **unsigned Gegentyp** (`hi - lo` kann so kein signed
  overflow sein), floating über `std::isfinite(hi - lo)`.
* `enhancedRampValue` (Integralzweig) und `enhancedMidValue` (Integralzweig)
  rechnen jetzt vollständig in `std::make_unsigned_t<DType>`. Für jede Range,
  die der Validator zulässt, ist das Ergebnis **bit-identisch** zur bisherigen
  Rechnung (die Modulo-Operation passiert weiterhin in `size_t`, `step <= span`,
  also `lo + step <= hi`).
* Ein zentraler Guard in `enhancedFillPatternTyped` prüft die Spanne **einmal**
  für genau die Patterns, die die Range lesen (alles außer `all_zeros`,
  `extreme_values`, `explicit_values` — dieselbe Aufteilung wie
  `PATTERN_PARAM_RELEVANCE`), und bricht sonst über `enhancedFillAbort`
  **kontrolliert** mit Diagnose ab, statt UB auszuführen.
* Der `[c,c]`-Guard aus fixes 13 bleibt unverändert; `span == 0` ⇒ `span+1 == 1`
  ist unter der neuen Regel weiterhin sicher.

`fillRand` in `utilities.hpp` bleibt **unangetastet** (es bedient auch die
normalen Correctness-Läufe). Nach dem Guard sieht sein Integralzweig nur noch
Spannen mit `0 < span < max(DType)`, für die `rand() % span + min` weder
überläuft noch durch null teilt.

---

## 4. Nonfinite Validation

* `capabilities.non_finite_range_reason` ist **die eine** Finitheitsregel für
  `value_range`. `validate_spec` ruft sie **vor** dem `lo <= hi`-Vergleich auf,
  damit NaN nie mehr aus einer Vergleichseigenheit heraus abgelehnt wird, und
  `value_range_rejection` ruft sie als ersten Schritt.
  Abgelehnt: `[NaN,1]`, `[0,NaN]`, `[-Inf,1]`, `[0,+Inf]`, `[-Inf,+Inf]`.
* `capabilities.explicit_values_rejection` lehnt **jeden** nicht-endlichen
  Einzelwert ab — für `int`-, `float`- **und** `double`-Benchmarks, ohne
  Ausnahme für `double`. Ein nicht-endlicher Wert gehört nicht in einen regulären
  Enhanced Spec; es gibt dafür **keine** BI-Spätklassifikation.

---

## 5. Pattern Parameter Relevance

`thesis/enhanced_tests/capabilities.py::PATTERN_PARAM_RELEVANCE` ist die **eine
kanonische Definition**. Jeder Eintrag nennt die Stelle in
`drivers/cpp/enhanced-fill.hpp`, die den Parameter liest bzw. ignoriert — die
Tabelle ist damit gegen den Harness prüfbar und nicht bloß behauptet.

| Pattern | `value_range` | `k` | `values` |
|---|---|---|---|
| `random` | ja | nein | nein |
| `all_zeros` | nein | nein | nein |
| `all_same` | ja | nein | nein |
| `ascending` | ja | nein | nein |
| `descending` | ja | nein | nein |
| `alternating` | ja | nein | nein |
| `extreme_values` | nein | nein | nein |
| `duplicate_at` | ja | **ja** | nein |
| `sorted_except_one` | ja | **ja** | nein |
| `spike_at` | ja | **ja** | nein |
| `explicit_values` | nein | nein | **ja** |

Abgeleitet daraus, ohne zweite Liste: `K_PATTERNS`, `RANGE_PATTERNS`,
`VALUES_PATTERNS`. `specs.py::K_PATTERNS` **ist** jetzt
`capabilities.K_PATTERNS`; die frühere eigene Tupelliteral-Liste ist entfernt.
Ein Modul-Guard in `specs.py` wirft beim Import, falls `PATTERNS` und die
Relevanztabelle je auseinanderlaufen.

`validate_spec` lehnt danach ab:

| Fall | Reason |
|---|---|
| `k` bei Nicht-K-Pattern | `irrelevant_pattern_parameter` |
| `values` bei Nicht-`explicit_values` | `irrelevant_pattern_parameter` |
| `value_range` bei `all_zeros` / `extreme_values` / `explicit_values` | `irrelevant_pattern_parameter` |
| unbekannter `pattern_params`-Key (erlaubt: nur `value_range`, `k`) | `unknown_pattern_parameter` |
| irgendein Fillparameter auf einem Benchmark ohne Fill-Hook | `inert_parameter_for_benchmark` |

**Reject statt kanonisieren.** Ein stilles Normalisieren („den irrelevanten
Parameter einfach weglassen") würde zwei *unterschiedliche gespeicherte* Specs
gleichsetzen und historische `spec_key`s umdeuten. `spec_key` bleibt daher
**unverändert**; Fake-Diversität wird dadurch verhindert, dass die betroffenen
Specs nicht mehr gültig sind.

Auch der Mutationspfad folgt derselben Quelle: ein Seed mit irrelevantem
Parameter erzeugt **gar keine** Nachkommen, eine `value_range`-Mutation gibt es
nur für range-lesende Patterns und nur, wenn die verschobene/verengte Range
selbst technisch sicher ist, und ein Pattern-Swap wird verworfen, wenn das
Zielpattern die geerbten Parameter nicht liest.

---

## 6. NONE / NOT_APPLICABLE — kanonische Semantik

11 der 60 Benchmarks haben **0 Fill-Sites** (`pattern_effect` NONE bzw.
NOT_APPLICABLE): `dense_la/01`, `graph/15`–`graph/19`, `histogram/23`,
`reduce/25`, `sort/44`, `sparse_la/45`, `sparse_la/49`.

Für sie ist `random` die kanonische Patternrepräsentation und **jeder**
Fillparameter inert. Deshalb gilt jetzt:

```
graph/15 + random                          -> valid
graph/15 + random + value_range [0,1]      -> reject (inert_parameter_for_benchmark)
```

Diversität entsteht dort ausschließlich über `size`. Der Generator bietet diesen
Benchmarks entsprechend **keine** Fillparameter mehr an
(„this benchmark has NO fill hook: `pattern_params` MUST be omitted or empty").

---

## 7. Define/Runtime Safety

Der Define-Pfad reicht den Range-Override jetzt als **`double`** an
`enhancedFillPattern` weiter:

```c
#define ENHANCED_FILL(x, lo, hi) \
    enhancedFillPattern((x), (double)(ENHANCED_FILL_LO), \
                        (double)(ENHANCED_FILL_HI), (ENHANCED_FILL_PATTERN), \
                        (size_t)(ENHANCED_FILL_PARAM_K))
```

statt `(decltype(lo))(…)`. `double` ist genau der Typ, den `spec_defines()`
emittiert, und die breiteste Quelle, die `enhancedRangeEndpoint` behandelt: beide
Pfade führen die Konversion damit **genau einmal, an genau einer Stelle** aus.

Dass das für gültige Specs **wertidentisch** ist, folgt aus dem Katalog: kein
einziger der 70 Fill-Sites paart integrale Call-Site-Literale mit einem
floating Container (die 17 Sites mit `int`-Literalen haben `int`-Container), und
für integrale Container reproduziert truncate-then-saturate den
konstantgefalteten Cast exakt. Empirisch belegt in §14.

---

## 8. Policy Fail-Closed

`capabilities.load_policy()` wirft jetzt `EnhancedPolicyError`, wenn die Policy

* fehlt, nicht lesbar oder kein gültiges JSON ist,
* `status != "ENFORCED"` trägt,
* keine `benchmarks`-Sektion hat,
* für irgendeinen Benchmark eine unvollständige oder überlappende
  Pattern-Partition, ein fehlendes/kaputtes `fill_type_capability` oder ein
  strukturell ungültiges `size_constraint` enthält.

`benchmark_policy(name)` wirft für einen **unbekannten Benchmark** — der Fall
„nicht in der Policy ⇒ unrestricted" existiert nicht mehr. Das gilt konsistent
für `validate_spec`, Generator und Mutation, weil alle drei über dieselben
Funktionen gehen.

`check_enhanced_capabilities.py` **failt** bei fehlender Policy (P0) statt die
Sektion zu überspringen, und prüft zusätzlich P7 (Status), P8
(Derivations-Exaktheit), P9 (Range-Type-Capability gegen die Katalog-Fill-Sites),
P10 (Size-Regel **byte-gleich** zum Katalogblock) und P11 (Relevanztabelle deckt
genau die implementierte Patternbibliothek ab).

---

## 9. Exact-Derivation Preflight

`derive_enhanced_policy.policy_matches_derivation()` ist die importierbare
Zwillingsfunktion von `--check` — **kein Subprozess-Duplikat**.
`capabilities.policy_preflight(expected_benchmarks=None)` kombiniert:
Fail-Closed-Laden + Derivations-Exaktheit + optionale Abdeckungsprüfung gegen die
Benchmarks, die der Lauf anfassen wird, und liefert bei Erfolg den
Provenance-Record.

---

## 10. Side-Effect Ordering

| Konsument | Preflight steht vor |
|---|---|
| `run_enhanced_tests.py::main` | Environment-Gate, `ensure_run_manifest(...)`, `--force`-`path.unlink()`, `output_path.open(...)`, `load_llm_specs(...)`, jedem Build, jedem Gate-Cache-Eintrag |
| `generate_test_specs.py::main` | `output_path.parent.mkdir(...)`, `--force`-`path.unlink()`, `output_path.open(...)`, `load_adapter(...)`, `adapter.create_client(...)`, jedem Modellaufruf |

Beide Reihenfolgen sind getestet (statisch über die Zeilenpositionen in `main`
und, für den Generator, dynamisch: mit einem fehlschlagenden Preflight bricht er
ab, ohne dass Ausgabedatei **oder Ausgabeverzeichnis** entstehen und ohne dass
der Adapter überhaupt geladen wird).

---

## 11. Size Source-of-Truth

Die neun E2-A-Size-Regeln stehen jetzt **ausschließlich** normalisiert im
Auditkatalog, pro Benchmark unter `enforced_size_safety` mit
`min_size` / `size_predicate`, `reason`, `evidence` und `policy_dependency`. Die
manuelle Tabelle `derive_enhanced_policy.py::SIZE_CONSTRAINTS` ist **entfernt**;
die Derivation kopiert den Katalogblock. P10 prüft die Byte-Gleichheit, P8 die
Gesamtexaktheit — eine stale Regel (z. B. `graph/19 min_size = 0`) schlägt damit
sowohl im Checker als auch im Runtime-Preflight fehl.

Migration additiv: kein Auditfeld, keine Rationale und keine Historie wurde
entfernt (maschinell verifiziert). Kein Benchmark hinzugefügt, keine Regel
verbreitert, keine globale Size-Zero-Policy entschieden.

Betroffene Benchmarks (unverändert 9): `dense_la/01` (min 1), `graph/19` (min 2),
`search/36`, `search/37`, `search/39` (je min 1), `fft/05`, `fft/07`, `fft/08`,
`fft/09` (`power_of_two_or_below_two`).

---

## 12. Range-Type Source-of-Truth

Ebenfalls **eine** Quelle: `fill_sites[].container_value_type_normalized` im
Katalog (neu, additiv; die menschenlesbare `container_value_type` bleibt
unverändert daneben stehen). Daraus leitet
`derive_enhanced_policy::_fill_type_capability` pro Benchmark

```json
"fill_type_capability": {
  "element_types": ["int"], "has_fill_hook": true,
  "value_min": -2147483648.0, "value_max": 2147483647.0,
  "max_finite_span": 2147483646.0, "all_integral": true, "reason": "..."
}
```

ab. **Sowohl** `explicit_values` **als auch** `value_range` validieren gegen
diesen einen Block; die frühere separate `explicit_values_bounds`-Tabelle ist
ersetzt (semantisch identisch: für `int`/`float` dieselben Grenzen, für `double`
neu explizit ±DBL_MAX statt „unbeschränkt", was bei bereits erzwungener
Finitheit nichts zusätzlich ablehnt).

Verteilung über die 60 Benchmarks: 31× `double`, 15× `int`, 2× `float`,
1× `float`+`int`, 11× kein Fill-Hook.

---

## 13. Policy Provenance Hash

`capabilities.policy_provenance()` liefert:

| Feld | Wert in diesem Stand |
|---|---|
| `enhanced_policy_sha256` | `1dbb58967f902b33bcb2f35d98f20683be5251ac654ae448cace42058df42694` |
| `enhanced_policy_status` | `ENFORCED` |
| `enhanced_policy_benchmark_count` | `60` |
| `derived_from` | `thesis/enhanced_tests/enhanced_capabilities.json` |
| `derived_from_sha256` | `a3e213fdb8aad9c609777742ec4aae2baa061016210eb2c47a5a5f6fe7202bb6` |
| `derivation_version` / `derivation_module_version` | `e2a1.1` / `e2a1.1` |

Beide Hashes sind über den **Dateiinhalt** gebildet — nicht über mtime,
Dateiname oder Git-Commit. Erfasst wird das

* im **Run-Manifest** (`enhanced_policy`, additiv nach dem Muster von
  `enhanced_specs`/`prompt_selection`: bei Erstellung geschrieben, in ein
  Manifest ohne das Feld **einmal** nachgetragen, frozen fields unberührt;
  Stages, die keins übergeben, sind unbetroffen), und
* in der **Enhanced-Summary** (`enhanced_policy_provenance`).

Das produktive Record-Schema `enhanced_tests.v1` ist **nicht** verändert.

---

## 14. Sanitizer Evidence

### 14.1 Matrix

GCC 13.3.0 im `pareval-thesis`-Container, `-fsanitize=undefined,
float-cast-overflow,address`, `-O1 -g`, `UBSAN_OPTIONS=halt_on_error=0`. Der
Probe inkludiert das **echte** `drivers/cpp/utilities.hpp` (also den echten
`fillRand` und, an dessen Ende, `enhanced-fill.hpp`) — es wird der produktive
Fillpfad gemessen, keine Nachbildung. Gemessen wurde jede Kombination zweimal:
gegen den **fixes-13-Header (OLD)** und gegen den **E2-A.1-Header (NEW)**.

Achsen: 3 Elementtypen × 9 Ranges × 10 Patterns (0–9) × 2 Pfade (define,
runtime) = **180 Läufe pro Header**, 360 insgesamt.

| Range | `int` (Call-Site-Literale `0`/`100`) | `float` | `double` |
|---|---|---|---|
| `[0,100]` | gültig | — | — |
| `[5,5]` | gültig (`[c,c]`-Guard) | — | — |
| `[-100,100]` | — | gültig | gültig |
| `[INT_MIN,INT_MAX]` | **technisch invalid** (Span) | — | — |
| `[-1e300,1e300]` | **technisch invalid** (Repräsentierbarkeit) | **technisch invalid** | — |
| `[-FLT_MAX,FLT_MAX]` | — | **technisch invalid** (Span) | — |
| `[-DBL_MAX,DBL_MAX]` | — | — | **technisch invalid** (Span) |

**Ergebnis:**

| | OLD (fixes 13) | **NEW (E2-A.1)** |
|---|---|---|
| CLEAN | 149 | **100** |
| SANITIZER-Diagnostik | **31** | **0** |
| kontrollierter Abbruch (`enhancedFillAbort`) | 0 | **80** |

* **Remaining diagnostics: 0.** Kein einziger Lauf des neuen Headers erzeugt
  eine Sanitizer-Diagnostik.
* Die 80 kontrollierten Abbrüche sind exakt `5 invalide Ranges × 8
  range-lesende Patterns × 2 Pfade`. Die je 4 verbleibenden Läufe pro invalider
  Range (`all_zeros`, `extreme_values`, beide Pfade) bleiben korrekt **CLEAN**:
  diese Patterns lesen die Range nicht, also greift der Guard nicht — genau die
  Aufteilung aus `PATTERN_PARAM_RELEVANCE`.
* Auf allen **gültigen** Ranges: **0** Abbrüche, **0** Diagnostiken, in beiden
  Headern und beiden Pfaden.

### 14.2 Konkrete Belege

`int`, `[INT_MIN, INT_MAX]`, `ascending`, **OLD** — die vom Audit beschriebene
Kette Overflow → Division-by-zero → FPE in einem einzigen Lauf:

```
enhanced-fill.hpp:172:38: runtime error: signed integer overflow:
    2147483647 - -2147483648 cannot be represented in type 'int'
enhanced-fill.hpp:176:68: runtime error: division by zero
AddressSanitizer: FPE ... in enhancedRampValue<int>(...) enhanced-fill.hpp:176
```

`int`, `[INT_MIN, INT_MAX]`, `random`, **OLD** — derselbe Overflow im
`fillRand`-Integralzweig:

```
utilities.hpp:160:33: runtime error: signed integer overflow:
    2147483647 - -2147483648 cannot be represented in type 'int'
```

`int`, `[-1e300, 1e300]`, `all_zeros`, **OLD** — der **Define-Pre-Cast**: die
Konversion passiert am **Call-Site**, bevor irgendein Pattern läuft, und trifft
deshalb sogar ein Pattern, das die Range gar nicht liest:

```
probe.cc:28:5: runtime error: 1e+300 is outside the range of representable values of type 'int'
probe.cc:28:5: runtime error: -1e+300 is outside the range of representable values of type 'int'
```

Der Runtime-Pfad war im selben Fall **CLEAN** — genau die vom Audit genannte
Pfadasymmetrie. Unter **NEW** sind beide Pfade CLEAN.

`float`, `[-FLT_MAX, FLT_MAX]`, `ascending`, **OLD** — **keine**
Sanitizer-Diagnostik (IEEE-Overflow ist kein UB), aber ein deterministisch
nicht-endlicher Input:

```
-nan
inf
inf
... (6×)
```

Dieselbe Kombination unter **NEW**:

```
ENHANCED_FILL: value_range span is not representable in the fill container
element type (integral: hi-lo and span+1 must fit; floating: hi-lo must stay
finite). Such a spec is rejected by thesis/enhanced_tests/specs.py::validate_spec
and must never reach the harness; refusing to execute undefined behaviour
exit=134
```

### 14.3 Keine Inputdrift für weiterhin gültige Specs

Für die vier **gültigen** Ranges (`int [0,100]`, `int [5,5]`,
`float [-100,100]`, `double [-100,100]`) wurden alle 10 Patterns in beiden
Pfaden Wert für Wert zwischen OLD und NEW verglichen:

| | |
|---|---|
| Vergleiche | **80** |
| Wertabweichungen | **0** |
| Nicht-CLEAN-Läufe auf gültigen Ranges | **0** |

Das deckt beide C++-Änderungen ab: die widened-unsigned Arithmetik in Ramp und
Midpoint **und** den entfernten Define-Pre-Cast. E2-A.1 fügt damit **keine**
neue Driftquelle hinzu; die Drift-Menge bleibt exakt die aus E2-A (7 + 4 Specs,
4 Benchmarks).

Zusätzlich wurde die E2-A-Probe an den **echten Drivern** unverändert
wiederholt (UBSan+ASan+float-cast-overflow, `ENHANCED_RUNTIME_FILL`,
reduce/28, scan/31, sort/42, alle dort aktiven Patterns): **21/21 clean**,
`fail=0` — identisch zum E2-A-Ergebnis.

### 14.4 Define/Runtime-Parität, inkl. Fehlersemantik

| | |
|---|---|
| Verglichene Kombinationen (NEW) | **90** |
| Verdict-Abweichungen define vs. runtime | **0** |
| Wertabweichungen bei CLEAN-Läufen | **0** |

Beide Pfade akzeptieren und verweigern also **dieselben** Ranges und liefern für
akzeptierte identische Bytes. Die Fehlersemantik ist zusätzlich in
`test_enhanced.py` festgeschrieben: für eine verweigerte Range prüft die
Testgruppe „range conversion" jetzt gleichen Exitstatus, in **beiden** Pfaden
die `ENHANCED_FILL:`-Diagnose und leere Ausgabe — statt wie bisher nur
Outputparität.

---

## 15. Existing Spec Reclassification

`thesis/enhanced_tests/classify_specs_e2a1.py`, read-only, **neu berechnet** —
die fixes-13-Partition (65 / 7 / 4 / 407) wurde nicht als erwartete Wahrheit
verwendet.

| Klasse | E2-A (fixes 13) | **E2-A.1** |
|---|---|---|
| `TOTAL_EXISTING_SPECS` | 483 | **483** |
| `INVALID_BY_POLICY_ONLY` | 65 | **76** |
| `INPUT_DRIFTED_BUT_STILL_VALID` | 7 | **7** |
| `INVALID_AND_DRIFTED` | 4 | **4** |
| `UNCHANGED_AND_VALID` | 407 | **396** |
| Summe | 483 ✓ | **76+7+4+396 = 483 ✓** |

Die 11 zusätzlich invaliden Specs sind exakt die drei neuen Kategorien
(8 + 2 + 1); keine bestehende Kategorie hat sich verschoben.

### Pflicht-Einzelfälle

| Fall | im Cache | valid nachher | Reason |
|---|---|---|---|
| `dense_la/03` `ascending` `[-1e308, 1e308]` | 1 | **0** | `unsafe_value_range_span` |
| `sort/41` Specs mit irrelevantem `k` | 8 | **0** | `irrelevant_pattern_parameter` |
| `sort/44` `random` mit inerter `value_range` | 4 | **0** | `inert_parameter_for_benchmark` / `no_pattern_effect` |
| `sparse_la/49` `random` mit inerter `value_range` | 6 | **0** | `inert_parameter_for_benchmark` / `no_pattern_effect` |

Die beiden identischen `sort/41`-`explicit_values`-Specs, die sich nur im
irrelevanten `k` unterschieden, sind damit **beide** ungültig — nicht einer von
beiden „gewinnt", und keiner wird stillschweigend auf denselben `spec_key`
normalisiert.

### Delta: genau welche 11 Specs E2-A.1 zusätzlich invalidiert

`407 − 396 = 11`, vollständig aufgelistet (alle waren unter fixes 13 gültig):

| Benchmark | size | pattern | `k`? | range? | neue Reason |
|---|---|---|---|---|---|
| `dense_la/03_dense_la_axpy` | 5 | `ascending` | – | ✓ | `unsafe_value_range_span` |
| `sort/41_sort_k-th_smallest_element` | 1 | `explicit_values` | ✓ | – | `irrelevant_pattern_parameter` |
| `sort/41_sort_k-th_smallest_element` | 2 | `explicit_values` | ✓ | – | `irrelevant_pattern_parameter` |
| `sort/41_sort_k-th_smallest_element` | 2 | `explicit_values` | ✓ | – | `irrelevant_pattern_parameter` |
| `sort/41_sort_k-th_smallest_element` | 8 | `explicit_values` | ✓ | – | `irrelevant_pattern_parameter` |
| `sort/41_sort_k-th_smallest_element` | 6 | `explicit_values` | ✓ | – | `irrelevant_pattern_parameter` |
| `sort/41_sort_k-th_smallest_element` | 3 | `all_zeros` | ✓ | – | `irrelevant_pattern_parameter` |
| `sort/41_sort_k-th_smallest_element` | 4 | `extreme_values` | ✓ | – | `irrelevant_pattern_parameter` |
| `sort/41_sort_k-th_smallest_element` | 5 | `descending` | ✓ | ✓ | `irrelevant_pattern_parameter` |
| `sort/44_sort_sort_non-zero_elements` | 4096 | `random` | – | ✓ | `inert_parameter_for_benchmark` |
| `sparse_la/49_sparse_la_sparse_lu_decomp` | 4 | `random` | – | ✓ | `inert_parameter_for_benchmark` |

Die vier `sort/41`-`explicit_values`-Specs der Größen 1/2/2/8 sind der belegte
Fake-Diversity-Fall: gleiche `values`, gleicher Header, gleiche Runtime-Env,
gleicher separat gezogener Driver-`k`, identischer Input — nur der
`pattern_params.k` unterschied die `spec_key`s.

---

## 16. New invalidation reasons

Vollständige Reason-Verteilung über alle 80 invaliden Specs, getrennt
ausgewiesen — keine Kategorie ist zusammengefasst oder verschleiert:

| Reason | Anzahl | seit |
|---|---|---|
| `no_pattern_effect` | 49 | E2-A |
| `invalid_size_for_benchmark` | 12 | E2-A |
| `irrelevant_pattern_parameter` | **8** | **E2-A.1** |
| `deferred_policy_pattern` | 6 | E2-A |
| `inert_parameter_for_benchmark` | **2** | **E2-A.1** |
| `unsafe_pattern_for_benchmark` | 1 | E2-A |
| `unsafe_value_range_span` | **1** | **E2-A.1** |
| `value_not_representable_for_benchmark` | 1 | E2-A |
| `unknown_pattern_parameter` | 0 | E2-A.1 (im Bestand nicht vorhanden) |
| `non_finite_value_range` | 0 | E2-A.1 (im Bestand nicht vorhanden) |
| `non_finite_explicit_value` | 0 | E2-A.1 (im Bestand nicht vorhanden) |
| `range_not_representable_for_benchmark` | 0 | E2-A.1 (im Bestand nicht vorhanden) |

Die vier Nullzeilen sind **keine** ungeprüften Kategorien: sie sind im aktuellen
Cache schlicht nicht instanziiert (der Audit hatte 0 non-finite Ranges und
0 außerhalb der Repräsentierbarkeit gefunden) und werden vom Testsuite-Teil
„range safety" / „non-finite" synthetisch abgedeckt.

---

## 17. Regeneration vs Reexecution

| | |
|---|---|
| `ENHANCED_SPECS_REGENERATION_REQUIRED` | **true**, **80** Specs (76 invalid-only + 4 invalid-and-drifted) |
| `ENHANCED_SPECS_REEXECUTION_REQUIRED` | **true**, **7** Specs (drifted, weiterhin gültig) |
| Specs tatsächlich regeneriert | **false** — diese Wave regeneriert nichts |
| `spec_key` geändert | **false** |
| `HISTORICAL_ENHANCED_INPUT_REPRODUCIBLE_UNDER_E2A1` | `false` für `reduce/28`, `scan/31`, `sort/42`, `sort/43` (unverändert aus E2-A; E2-A.1 fügt **keine** neue Driftquelle hinzu) |

Vier Benchmarks haben nach E2-A.1 **keinen** gültigen Bestandsspec mehr und
brauchen in E3 eine vollständige Neugenerierung: `graph/15`, `sort/41`,
`sparse_la/45`, `sparse_la/49`.

`capability_limited_spec_count` ist aktualisiert und **ehrlich**: kein Benchmark
wird durch irrelevante Ranges, irrelevante `k` oder Fake-Labels wieder auf 20
aufgefüllt. Der Regressionstest „every spec differs in size" und
„no generated/mutated spec carries an irrelevant or unsafe parameter" halten das
strukturell fest.

---

## 18. Cross-Pilot impact

**Nachher: Exit 1, `CROSS_PILOT_REPO_STATE_STALE = true`** (schon vorher stale).
Keine Fingerprints aktualisiert, keine Neuklassifikation, keine
99/0/99-Materialisierung, Candidate-Subset unverändert.

Geänderte fingerprinted Dateien:

| Datei | Granularität | Status | seit |
|---|---|---|---|
| `drivers/cpp/enhanced-fill.hpp` | semantic | STALE | schon fixes 13 |
| `thesis/enhanced_tests/specs.py` | semantic | STALE | schon fixes 13 |
| `thesis/evaluation/run_enhanced_tests.py` | coarse | STALE | **neu in E2-A.1** |

`run_enhanced_tests.py` ist die einzige **zusätzlich** betroffene fingerprinted
Datei. Der Diff ist 33 Einfügungen / 1 Ersetzung und besteht ausschließlich aus
dem Policy-Preflight, der Provenance-Weitergabe und dem Summary-Feld — keine
Änderung an Compile-Gruppierung, Verdict-Semantik, Timing oder Record-Schema.

Nicht fingerprinted und deshalb nur informativ mitgeändert:
`thesis/evaluation/run_manifest.py` (additives optionales Feld),
`thesis/enhanced_tests/{capabilities,derive_enhanced_policy,generate_test_specs,
check_enhanced_capabilities}.py`, `enhanced_capabilities.json`,
`enhanced_policy.json`.

Unverändert und explizit geprüft: alle Benchmark-lokalen Fingerprints
(`cpu.cc`, `baseline.hpp`, `enhanced_spec_keys`, alle drei Prompt-Hashes) der
drei Kandidaten, `utilities.hpp`, `harness-markers.hpp`, alle drei Driver,
`build_config.py`, `run_correctness.py`, `framework.py`,
`baseline_selftest.py`, Assembly, Generation- und Evaluation-Condition.

---

## 19. No-Correctness-Regression

**`NORMAL_CORRECTNESS_INPUT_PATH_CHANGED = false`**, quellenbelegt:

* Ohne die `ENHANCED_*`-Defines expandiert `ENHANCED_FILL(x, lo, hi)` weiterhin
  byte-gleich zu `fillRand((x), (lo), (hi))` — die betreffende Zeile ist im Diff
  unverändert.
* `fillRand` und `drivers/cpp/utilities.hpp` insgesamt sind **unverändert**
  (`git diff` leer).
* Alle neuen Helfer (`enhancedFillAbort`, `enhancedRangeSpanIsSafe`, die
  widened-unsigned Zweige) leben in Templates bzw. einer `inline`-Funktion, die
  ohne die Defines nicht instanziiert bzw. nicht aufgerufen wird — kein Codegen
  im Correctness-Build.
* `run_correctness.py`, `framework.py`, `build_config.py`, alle Driver und alle
  Benchmark-Quellen sind unverändert.

Compile-Grouping-Regression: die Gruppierungslogik in `run_enhanced_tests.py`
(ein Compile pro `sample × size`, Runtime-Fill) ist unberührt; der Diff liegt
vollständig vor der Modellschleife.

---

## 20. Remaining E2-B policies

Unverändert offen und in dieser Wave **nicht** entschieden:

`EXTREME_PATTERN_SEMANTICS`, `VALUE_RANGE_DOMAIN_POLICY`,
`SIZE_ZERO_SPEC_POLICY`, `TOLERANCE_POLICY`, `GRAPH_ADAPTER_VOCABULARY`,
`SPARSE_ADAPTER_POLICY`, `SORT44_ADAPTER_POLICY`, `LARGE_SIZE_POLICY`.

Weiterhin offene technische Notizen (bewusst nicht ausgeweitet):

* **complex-Fill-Dispatch** — `fillRand`s `complex<double>`-Zweig ist mit
  komplexen Endpunkten nicht instanziierbar (latenter Vor-E2-A-Bug). Der
  E2-A-Dispatch über die Double-Endpunkte erreicht weiterhin **0** produktive
  Fill-Sites und **0** aktuelle Specs, erzeugt **0** Inputdrift und wurde in
  E2-A.1 **nicht** erweitert.
* **`[c,c]`-Guard** — betrifft weiterhin **0** der 483 historischen Specs,
  erfordert **keine** Reexecution, ist bei `[c,c]` mathematisch exakt und bleibt
  unverändert bestehen.

E2-B (Policyentscheidungen) und E3 (Spec-Regeneration, Reexecution) bleiben die
nächsten Wellen. Es wurde keine Reuse-, Publication- oder
pilot_002-Populationsentscheidung getroffen, kein `run_id` gewechselt und kein
pilot_002 gestartet.
