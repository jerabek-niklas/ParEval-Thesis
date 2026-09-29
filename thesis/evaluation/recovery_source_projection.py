"""Exact inverse of the registered Enhanced routing-only change.

This is used for differential tests, not execution. Every inserted statement
must occur exactly once. It cannot normalize arbitrary source differences.
"""

INSERTIONS = (
    '''    from thesis.evaluation import recovery_context
    recovery = recovery_context.is_recovery(run_id)
    candidate_run_id = recovery_context.candidate_run(run_id)
    if recovery:
        if args.force or not args.model_id:
            raise ValueError("recovery enhanced requires one model and forbids force")
        recovery_context.validate_target(config, run_id, args.model_id, enhanced=True)
        authority_run_id = "full_ext_recovery_001"
''',
    '''                            if recovery:
                                row.update(recovery_context.candidate_provenance(config, run_id, model_id, row["sample_id"]))
''',
    '''                            if recovery:
                                record.update(recovery_context.candidate_provenance(config, run_id, model_id, record["sample_id"]))
''',
)
REPLACEMENTS = (
    ("            intermediate_dir, candidate_run_id, model_id)",
     "            intermediate_dir, run_id, model_id)"),
    ("            REPO_ROOT, intermediate_dir, candidate_run_id, model_id",
     "            REPO_ROOT, intermediate_dir, run_id, model_id"),
)


def pre_recovery_enhanced_source(text):
    for insertion in INSERTIONS:
        if text.count(insertion) != 1:
            raise ValueError("unregistered enhanced routing statements")
        text = text.replace(insertion, "", 1)
    for new, old in REPLACEMENTS:
        if text.count(new) != 1:
            raise ValueError("unregistered enhanced candidate call")
        text = text.replace(new, old, 1)
    return text
