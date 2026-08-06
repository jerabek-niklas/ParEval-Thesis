# Optimization-level probe — are the dense_la mini-differences O-level-dependent?

One-off verification experiment (thesis/experiments/opt_level_probe.py);
no pipeline, config or result changes. Build = run_correctness's exact
translation unit and flags plus a trailing `-O<level>` override;
`MISMATCH_REPORT_MAX=100000` so the COMPLETE mismatch list prints
(values at max_digits10 round-trip precision; fillRand inputs are
deterministic, so the lists are directly comparable).

## Sample under test: `qwen3_coder_api__dense_la__00_dense_la_lu_decomp__serial__sample_0` (run smoke_002)

| level | verdict | mismatch_total | list identical to -O0 |
| --- | --- | --- | --- |
| -O0 | validation_failed | 52 | reference |
| -O1 | validation_failed | 52 | yes |
| -O2 | validation_failed | 52 | yes |
| -O3 | validation_failed | 52 | yes |

Expected side identical across levels: **yes** — the baseline's values
do not move with the optimizer.

Got side identical across levels: **yes** — the model code's values
do not move either.

### Example mismatches (full precision, identical on every level)

| index | expected (baseline) | got (model) |
| --- | --- | --- |
| 205201 | `182070.86024185043` | `182070.86173061817` |
| 205202 | `182462.75775725482` | `182462.75924767149` |
| 205206 | `-144320.58203888888` | `-144320.58321323674` |

## Control sample: `openai_gpt56_sol__dense_la__00_dense_la_lu_decomp__serial__sample_0` (expected: pass everywhere)

| level | verdict | mismatch_total |
| --- | --- | --- |
| -O0 | pass | None |
| -O1 | pass | None |
| -O2 | pass | None |
| -O3 | pass | None |

## Conclusion

The 52 mismatches are **bit-identical across -O0/-O1/-O2/-O3** (expected and got side separately), and the control sample passes on every level — the mini-differences stem purely from the SOURCE-level operation order of the model code vs. the baseline, not from the optimizer: without -ffast-math GCC preserves IEEE evaluation order on all O levels.
