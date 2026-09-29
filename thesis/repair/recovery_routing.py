"""Opt-in recovery read routing, isolated from the legacy repair implementation.

Constructing a loop does not initialize state or authorize it. Productive use
still requires a READY recovery contract (not implemented by this module).
"""
from pathlib import Path

from thesis.evaluation.recovery_lineage import PARENT, RECOVERY, RecoveryRefused, compare_requests
from thesis.repair import orchestrator


class RecoveryLoopPaths(orchestrator.LoopPaths):
    def __init__(self, config, model, variant, lineage):
        super().__init__(config, RECOVERY, model, variant)
        for key, folder in (("raw_dir", "raw"), ("intermediate_dir", "intermediate")):
            if Path(config["outputs"][key]).resolve() != lineage.root / "thesis/results" / folder:
                raise RecoveryRefused("recovery outputs must use the bound repository layout")
        if model not in lineage.document.get("model_ids", []):
            raise RecoveryRefused("model outside parent population")
        self.lineage = lineage

    def _parent(self, name, raw=False):
        folder = "raw" if raw else "intermediate"
        return self.lineage.read_path("thesis/results/%s/%s/%s/%s" % (folder, PARENT, self.model_id, name))

    def iter_run_id(self, iteration):
        # This is the RESULT identity. Never return the parent here.
        return self.lineage.iteration_run(self.variant, iteration)

    def iter_generations_path(self, iteration):
        return self._parent("generations.jsonl", raw=True) if iteration == 0 else super().iter_generations_path(iteration)

    def assembly_path(self, iteration):
        return self._parent("assembly.jsonl") if iteration == 0 else super().assembly_path(iteration)

    def stage_path(self, iteration, stage_name):
        if iteration == 0:
            if stage_name not in ("static_analysis", "correctness_tests", "dynamic_analysis"):
                raise RecoveryRefused("unregistered parent stage")
            return self._parent(orchestrator.stage_output_file(self.config, stage_name))
        return super().stage_path(iteration, stage_name)

    def source_path(self, iteration, sample_id):
        if iteration == 0:
            return self._parent("sources/%s/generated-code.hpp" % sample_id)
        return super().source_path(iteration, sample_id)


class RecoveryRepairLoop(orchestrator.RepairLoop):
    def __init__(self, *args, lineage, **kwargs):
        super().__init__(*args, **kwargs)
        if self.paths.base_run_id != RECOVERY:
            raise RecoveryRefused("recovery loop cannot impersonate parent")
        self.lineage = lineage
        self.paths = RecoveryLoopPaths(self.config, self.model_id, self.variant, lineage)

    def step(self, *args, **kwargs):
        from thesis.evaluation.recovery_contract import build
        from thesis.evaluation.run_authorization import load_and_validate_run_authorization
        build(self.config_path, self.paths.base_run_id, self.primary_compiler)
        load_and_validate_run_authorization(
            self.config, self.paths.base_run_id, config_path=self.config_path,
            profile=self.profile_name)
        return super().step(*args, **kwargs)

    def _submit(self, target_iteration):
        if self.model_id == "openai_gpt55" and self.variant == "static_feedback" and target_iteration == 1:
            from thesis.evaluation.verify_parent_base_evidence import records
            relative = "thesis/results/intermediate/%s/%s/repair/%s/iter1/requests.jsonl" % (
                PARENT, self.model_id, self.variant)
            # The historical-only request ledger is an audit comparator, not
            # a runner input. Verify its inventory hash before comparing.
            ref = self.lineage.refs.get(relative)
            if ref is None or ref.stage != "historical_only":
                raise RecoveryRefused("missing bound historical request comparator")
            historical = records(ref.verify(self.lineage.root))
            self.verify_historical_request_set(historical)
            compare_requests(self.load_requests(1), historical)
        return super()._submit(target_iteration)

    def _run_analysis_stages(self, iteration, stages):
        if iteration == 0:
            raise RecoveryRefused("parent base evidence incomplete; never remeasure parent")
        return super()._run_analysis_stages(iteration, stages)

    def run_external_docker(self, pending, iteration):
        if iteration == 0:
            raise RecoveryRefused("parent external evidence incomplete; never backfill parent")
        return super().run_external_docker(pending, iteration)

    def external_command(self, tool, iteration):
        if iteration == 0:
            raise RecoveryRefused("parent measurements are immutable")
        return super().external_command(tool, iteration) + " --backfill-base-run-id " + self.paths.base_run_id

    def verify_historical_request_set(self, historical_requests):
        """Read-only reproduction; no state/response adoption and no providers."""
        if self.model_id != "openai_gpt55" or self.variant != "static_feedback":
            raise RecoveryRefused("historical request check is scoped to the interrupted wave")
        # Reproduce the initial decision independently of the *current*
        # recovery state, including on a resumed submission.
        static = self.load_stage_records(0, "static_analysis")
        active = [sample for sample in self.iteration_samples(0)
                  if orchestrator.evaluate_stop(
                      config=self.config, variant=self.variant, iteration=0,
                      max_iterations=self.settings["max_iterations"],
                      static_record=static.get(sample), dynamic_record=None,
                      correctness_record=None, previous_low_confidence_keys=None
                  ).status == orchestrator.STATUS_ACTIVE]
        derived = self.build_request_records(1, active)
        if len(derived) != 62 or len(historical_requests) != 62:
            raise RecoveryRefused("interrupted-wave request count is not 62")
        compare_requests(derived, historical_requests)
        return {"request_count": 62, "request_content_match": True,
                "historical_responses_consumed": False}
