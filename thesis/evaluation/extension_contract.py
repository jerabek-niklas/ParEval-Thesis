"""Independent fresh extension contract, derived from verified methodology.

No old condition is substituted for changed source. The runner source pin is
additional to v3's existing conditions and explicitly compared on composite
level. No authorization, runtime probe, freeze, or result write occurs here.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from thesis.evaluation import condition_hashing as ch
from thesis.evaluation import method_equivalence as me

ROOT=Path(__file__).resolve().parents[2]
CERTIFICATE=ROOT/'thesis/evaluation/full_extension_equivalence.json'
PILOT_SHA='4aaa00c265ee14a8ea5389c2191e9be568122154b74976325b911afd536b1d48'
RUNNER='thesis/evaluation/run_enhanced_tests.py'

def build(config_path, run_id=None, primary_compiler='g++'):
    from thesis.evaluation import pilot_run_contract as pc
    from thesis.config.load_config import load_config
    if run_id not in (None,'full_ext_001'):
        raise ValueError('full_extension is bound to full_ext_001')
    config=load_config(config_path)
    baseline=pc.build_contract(config_path,'pilot','pilot_002',primary_compiler)
    if baseline['status']!='READY' or baseline['contract_sha256']!=PILOT_SHA:
        raise me.Refuse('pilot methodology changed beyond permitted backfill routing')
    profile=config['profiles']['full_extension']
    if (profile.get('run_id')!='full_ext_001' or profile.get('selection')!='complement'
            or profile.get('num_samples_per_prompt')!=1):
        raise me.Refuse('extension profile identity/sample policy mismatch')
    population=pc.population_view(config,profile)
    if population['error'] or population['expected_prompt_count']!=144 or population['expected_sample_count']!=144:
        raise me.Refuse('extension population invalid: '+str(population['error']))
    certificate=json.loads(CERTIFICATE.read_text(encoding='utf-8'))
    certificate_sha=certificate.get('certificate_sha256')
    me.validate_certificate(certificate,certificate_sha)
    old_conditions=copy.deepcopy(baseline['conditions'])
    new_conditions=copy.deepcopy(old_conditions)
    pair=next(p for p in certificate['pairs'] if p['condition']=='enhanced_runner_sources_sha256')
    old_conditions['enhanced_runner_sources_sha256']=pair['old_fingerprint']
    new_conditions['enhanced_runner_sources_sha256']=ch.canonical_sha256({RUNNER:ch.raw_sha256(ROOT/RUNNER)})
    me.compare_conditions(old_conditions,new_conditions,certificate,certificate_sha)
    selected={k:population['prompt_hashes'][k] for k in population['selected_prompt_keys']}
    benchmarks=sorted({'/'.join(k.split('|')[:2]) for k in selected})
    artifact={'schema_version':'full_extension_population.v1','run_id':'full_ext_001','profile':'full_extension',
              'population_source':'FULL_PROMPT_SET_MINUS_FROZEN_PILOT','benchmark_ids':benchmarks,
              'prompt_hashes':selected,'model_ids':baseline['model_ids'],'execution_models':population['execution_models'],
              'samples_per_prompt':1,'benchmark_count':48,'prompt_count':144,'model_count':11,
              'total_model_prompt_cells':1584,'exclude_population_sha256':baseline['population_freeze']['sha256'],
              'pilot_contract_sha256':PILOT_SHA}
    artifact['population_sha256']=ch.canonical_sha256(artifact)
    contract=copy.deepcopy(baseline)
    contract.update(run_id='full_ext_001',profile='full_extension',population=population,
                    selected_prompt_hashes=selected,conditions=new_conditions)
    contract['base_run']=dict(run_id='full_ext_001',expected_base_run_id='full_ext_001',
                              status='CONFIGURED',forbid_iteration_variants=True,historical_baseline_run_id=None)
    contract['population_freeze']=dict(artifact,sha256=artifact['population_sha256'],status='FRESH',
                                       path='thesis/evaluation/full_ext_001_population.json')
    contract['reuse_policy']=dict(policy='NO_MEASUREMENT_REUSE_INSIDE_EXTENSION',decided=True,
                                  reuse_status='DECIDED',generation_reuse=False,repair_reuse=False)
    contract['publication_policy']=dict(policy='COMPOSITE_VERIFICATION_AND_EXPLICIT_ACCEPTANCE_REQUIRED',
                                        decided=True,publication_allowed_before_result_acceptance=False)
    contract['methodology_freeze']=dict(schema_version='full_extension_methodology.v1',
                                      pilot_contract_sha256=PILOT_SHA,equivalence_sha256=certificate_sha)
    contract['policy_state']=dict(population_status='DECIDED',expected_base_run_status='CONFIGURED',
                                  expected_base_run_id='full_ext_001',forbid_iteration_variants=True,
                                  reuse_status='DECIDED',publication_status='DECIDED')
    contract['extension_provenance']=dict(pilot_contract_sha256=PILOT_SHA,
                                         equivalence_sha256=certificate_sha,
                                         certificate_path=CERTIFICATE.relative_to(ROOT).as_posix())
    contract['contract_sha256']=pc.contract_sha256(contract)
    return contract
