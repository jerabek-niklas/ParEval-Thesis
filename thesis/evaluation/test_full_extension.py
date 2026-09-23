"""Synthetic refusal tests and read-only real-population checks. No tool runs."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from thesis.evaluation import composite_study as cs, condition_hashing as ch
from thesis.evaluation import method_equivalence as me
from thesis.generation import common
from thesis.repair.backfill_authority import refuse_partial

ROOT = Path(__file__).resolve().parents[2]

class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.prompts = json.loads((ROOT/'thesis/prompts/generation-prompts-thesis.json').read_text())
        self.pilot = json.loads((ROOT/'thesis/evaluation/pilot_002_population.json').read_text())
        self.hashes = {'%s|%s|%s'%(p['problem_type'],p['name'],p['parallelism_model']):ch.utf8_sha256(p['prompt']) for p in self.prompts}
        selected = self.select()
        self.a = dict(run_id='pilot_002',contract_sha256='4aaa00c265ee14a8ea5389c2191e9be568122154b74976325b911afd536b1d48',
                      benchmark_ids=self.pilot['benchmark_ids'],prompt_hashes=self.pilot['prompt_hashes'],
                      model_ids=self.pilot['model_ids'],samples_per_prompt=1,execution_models=['serial','omp','mpi'],measurement_conditions={'test':'same'})
        self.a['verification'] = dict(status='PASS',counts={'PASS':269,'FAIL':0,'UNRESOLVED':0},run_id='pilot_002',contract_sha256=self.a['contract_sha256'])
        self.b=copy.deepcopy(self.a)
        self.b.update(run_id='full_ext_001',contract_sha256='synthetic-new-contract',
                      benchmark_ids=sorted({p['problem_type']+'/'+p['name'] for p in selected}),
                      prompt_hashes={'%s|%s|%s'%(p['problem_type'],p['name'],p['parallelism_model']):ch.utf8_sha256(p['prompt']) for p in selected})

    def select(self, prompts=None, **kwargs):
        options=dict(execution_models=['serial','omp','mpi'],problem_types=None,prompt_limit=None,selection='complement',
                     exclude_population='thesis/evaluation/pilot_002_population.json')
        options.update(kwargs)
        return common.select_prompts(self.prompts if prompts is None else prompts, **options)[0]

    def verify(self):
        return cs.validate_blocks(self.a,self.b,self.hashes)

    def test_exact_union_and_cells(self):
        self.assertEqual({'pilot_cells':396,'extension_cells':1584,'composite_cells':1980,'overlap':0},self.verify())

    def test_deterministic_original_prompts(self):
        self.assertEqual(self.select(),self.select())
        self.assertTrue(all(p in self.prompts for p in self.select()))

    def test_overlap_refused(self):
        self.b['benchmark_ids'][0]=self.a['benchmark_ids'][0]
        with self.assertRaises(ValueError): self.verify()

    def test_missing_benchmark_refused(self):
        with self.assertRaises(ValueError): self.select(self.prompts[3:])

    def test_duplicate_prompt_refused(self):
        with self.assertRaises(ValueError): self.select(self.prompts+[self.prompts[0]])

    def test_changed_prompt_refused(self):
        self.b['prompt_hashes'][next(iter(self.b['prompt_hashes']))]='changed'
        with self.assertRaises(ValueError): self.verify()

    def test_model_mismatch_refused(self):
        self.b['model_ids'][0]='other'
        with self.assertRaises(ValueError): self.verify()

    def test_execution_mismatch_refused(self):
        self.b['execution_models']=['serial']
        with self.assertRaises(ValueError): self.verify()

    def test_sample_mismatch_refused(self):
        self.b['samples_per_prompt']=2
        with self.assertRaises(ValueError): self.verify()

    def test_pilot_nonpass_refused(self):
        self.a['verification']['status']='UNRESOLVED'
        with self.assertRaises(ValueError): self.verify()

    def test_wrong_pilot_contract_refused(self):
        self.a['contract_sha256']='wrong'
        with self.assertRaises(ValueError): self.verify()

    def test_unknown_condition_difference_refused(self):
        self.b['measurement_conditions']['test']='changed'
        with self.assertRaises(ValueError): self.verify()

    def test_condition_key_set_drift_refused(self):
        self.b['measurement_conditions']['new']='anything'
        with self.assertRaises(ValueError): self.verify()

    def test_selection_narrowing_refused(self):
        for options in ({'prompt_limit':3},{'problem_types':['sort']},{'execution_models':['serial']}):
            with self.subTest(options=options),self.assertRaises(ValueError): self.select(**options)

    def test_partial_correctness_dynamic_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('correctness_tests.jsonl','dynamic_analysis.jsonl'):
                path=Path(tmp)/name
                path.write_text(json.dumps({'sample_id':'one'})+'\n')
                with self.assertRaises(ValueError): refuse_partial(path,['one','two'])

    def test_existing_gap_not_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'dynamic.jsonl'
            path.write_text(json.dumps({'sample_id':'one','analysis_state':'TOOL_ERROR'})+'\n')
            self.assertEqual('complete',refuse_partial(path,['one']))

    def test_missing_stage_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual('missing',refuse_partial(Path(tmp)/'absent',['one']))

    def test_reader_duplicates_missing_and_source(self):
        row=dict(benchmark='a',execution_model='serial',model_id='m',sample_index=0,run_id='pilot_002')
        key=('a','serial','m',0)
        result=cs.union_rows([('pilot_002',[row])],{key})
        self.assertIs(row,result[0]['record'])
        for sources, expected in (([('pilot_002',[row,row])],{key}),([], {key}),([('full_ext_001',[row])],{key})):
            with self.assertRaises(ValueError): cs.union_rows(sources,expected)

    def test_certificate_is_not_automatic_permission(self):
        with self.assertRaises(ValueError): me.compare_conditions({'enhanced_runner_sources_sha256':'old'}, {'enhanced_runner_sources_sha256':'new'}, {})

    def test_exact_pair_and_all_other_drift_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.py'; path.write_text('safe\n')
            cert=dict(schema_version='method_equivalence.v1',status='PROVEN',
                      unchanged_fields={k:{'old':'same','new':'same'} for k in me.INVARIANTS},
                      tests=[{'status':'PASS','evidence_sha256':'synthetic'}],source_pins={'source.py':ch.lf_normalized_sha256(path)},
                      pairs=[dict(condition='enhanced_runner_sources_sha256',old_fingerprint='old',new_fingerprint='new',exact_diff='synthetic',classification=me.CLASSIFICATION)])
            sha=me.fingerprint(cert); cert['certificate_sha256']=sha
            me.compare_conditions({'enhanced_runner_sources_sha256':'old'},{'enhanced_runner_sources_sha256':'new'},cert,sha,Path(tmp))
            for old,new in (({'other':'old'},{'other':'new'}),({'enhanced_runner_sources_sha256':'old'},{'enhanced_runner_sources_sha256':'unknown'})):
                with self.assertRaises(ValueError): me.compare_conditions(old,new,cert,sha,Path(tmp))
            path.write_text('drift\n')
            with self.assertRaises(ValueError): me.validate_certificate(cert,sha,Path(tmp))

if __name__=='__main__':
    unittest.main(verbosity=2)
