"""Final scientific analysis of the study (study_analysis_001).

Reads the formally verified study (closure study_closure_001, composite
phase2_composite.v1, the frozen phase-2 target table and the repair state
ledgers) through the authorized phase-2 readers, builds normalized tables,
computes the metrics frozen in methodology.json and renders CSV / JSON /
LaTeX (booktabs) tables and pgfplots / SVG figures.

Never measures, generates, repairs or contacts a provider; never writes into
a result tree. Formal outputs go to thesis/results/analysis/study_analysis_001/
and require committed code (clean worktree).

    python3 -B -m thesis.study_analysis.run --dry-run --out DIR
    python3 -B -m thesis.study_analysis.run --write
"""
