"""Read-only composite/extension preflight. Never authorizes or measures."""
from __future__ import annotations
import json
import subprocess
import tempfile
from pathlib import Path
from thesis.evaluation import condition_hashing as ch, pilot_run_contract as pc
from thesis.evaluation import run_freshness as rf, verify_pilot_run as pv
from thesis.evaluation import extension_contract as ec, composite_study as cs
from thesis.config.load_config import load_config

ROOT=Path(__file__).resolve().parents[2]

def runtime_images(config):
    from thesis.evaluation.run_manifest import load_manifest
    domains=((load_manifest(config,'pilot_002') or {}).get('runtime_evidence') or {}).get('domains') or {}
    observations={}
    for name in ('main','parcoach','llov'):
        domain=domains.get(name) or {}
        if not domain.get('image_ref') or not domain.get('image_id'):
            raise ValueError('missing pinned image identity: '+name)
        # Never load the user's Docker credential/config file for an inspect.
        with tempfile.TemporaryDirectory(prefix='pareval-docker-readonly-') as directory:
            result=subprocess.run(['docker','--config',directory,'image','inspect','--format','{{.Id}}',domain['image_ref']],
                                  capture_output=True,text=True,timeout=15)
        if result.returncode or result.stdout.strip()!=domain['image_id']:
            raise ValueError('Docker unavailable or image drift: '+name)
        observations[name]=result.stdout.strip()
    return observations

def build_study(config_path):
    config=load_config(config_path)
    root=Path(config['outputs']['intermediate_dir'])
    pilot=pc.load_frozen(root/'pilot_002/run_contract.json')
    report_path=root/'pilot_002/post_run_verification.json'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    actual=pv.verify(config,'pilot_002',root/'pilot_002/run_contract.json')
    if actual['counts']!={'PASS':269,'FAIL':0,'UNRESOLVED':0}:
        raise ValueError('pilot post-run regression')
    extension=ec.build(config_path)
    certificate=json.loads(ec.CERTIFICATE.read_text(encoding='utf-8'))
    pair=certificate['pairs'][0]
    a=dict(run_id='pilot_002',role='accepted_pilot_block',contract_sha256=pilot['contract_sha256'],
           contract_path=(root/'pilot_002/run_contract.json').as_posix(),
           verification={key:report[key] for key in ('run_id','contract_sha256','status','counts')},
           post_run_verification_path=report_path.as_posix(),post_run_verification_sha256=ch.raw_sha256(report_path),
           benchmark_ids=pilot['population_freeze']['benchmark_ids'],prompt_hashes=pilot['selected_prompt_hashes'],
           model_ids=pilot['model_ids'],samples_per_prompt=pilot['population']['num_samples_per_prompt'],
           execution_models=pilot['execution_models'],measurement_conditions=dict(pilot['conditions'],
                    enhanced_runner_sources_sha256=pair['old_fingerprint']))
    # Verify the old runner pin against EVERY model's stored global evidence.
    for model in pilot['model_ids']:
        summary=json.loads((root/'pilot_002'/model/'enhanced_tests_summary.json').read_text(encoding='utf-8'))
        components=summary['enhanced_execution_provenance']['components']['D_runner_sources']
        if ch.canonical_sha256(components)!=pair['old_fingerprint']:
            raise ValueError('pilot Enhanced source pin mismatch: '+model)
    b=dict(run_id='full_ext_001',role='fresh_extension_block',contract_sha256=extension['contract_sha256'],
           contract_path=(root/'full_ext_001/run_contract.json').as_posix(),
           benchmark_ids=extension['population_freeze']['benchmark_ids'],prompt_hashes=extension['selected_prompt_hashes'],
           model_ids=extension['model_ids'],samples_per_prompt=1,execution_models=extension['execution_models'],
           measurement_conditions=extension['conditions'])
    counts=cs.validate_blocks(a,b,pilot['population']['prompt_hashes'],certificate,certificate['certificate_sha256'])
    study=dict(schema_version='composite_study.v1',study_id='full_001',status='PLANNED_NOT_MEASURED',
               source_runs=[a,b],expected=counts,equivalence_sha256=certificate['certificate_sha256'])
    study['manifest_sha256']=ch.canonical_sha256(study)
    return study,extension

def preflight(config_path, expected_head):
    blockers=[]
    git=['git','-c','safe.directory='+ROOT.as_posix()]
    head=subprocess.check_output(git+['rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    status=subprocess.check_output(git+['status','--porcelain'],cwd=ROOT,text=True).strip()
    if head!=expected_head: blockers.append('HEAD differs from explicitly expected commit')
    if status: blockers.append('worktree is not clean (including untracked files)')
    config=load_config(config_path)
    freshness=rf.inspect_run_freshness(config,'full_ext_001')
    if freshness['status']!='FRESH': blockers.append('extension run is not FRESH')
    study=contract=None
    try:
        study,contract=build_study(config_path)
    except (ValueError,OSError,KeyError) as error:
        blockers.append('composite/contract: '+str(error))
    frozen=Path(config['outputs']['intermediate_dir'])/'full_ext_001/run_contract.json'
    if not frozen.is_file(): blockers.append('extension contract not frozen')
    elif contract and pc.load_frozen(frozen)['contract_sha256']!=contract['contract_sha256']:
        blockers.append('extension frozen contract drift')
    images={}
    try:
        images=runtime_images(config)
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        blockers.append('runtime image readiness: '+str(error))
    return dict(status='REFUSE' if blockers else 'PASS',head=head,git_status_porcelain=status,
                blockers=blockers,extension_freshness=freshness,contract_ready=bool(contract and contract['status']=='READY'),
                composite_verified=study is not None,pinned_runtime_images=images,
                runtime_scope='Docker daemon and immutable images only; fresh in-container T0 probe still mandatory',
                provider_calls=0,new_measurements=0)
