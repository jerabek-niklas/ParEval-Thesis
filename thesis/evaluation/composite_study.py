"""Reference-only composite validation. No result copying or relabeling."""
from __future__ import annotations
import json
from pathlib import Path
from thesis.evaluation import condition_hashing as ch
from thesis.evaluation.method_equivalence import Refuse, compare_conditions

def validate_blocks(pilot, extension, full_prompt_hashes, certificate=None, certificate_sha=None):
    if pilot.get("run_id") != "pilot_002" or extension.get("run_id") != "full_ext_001":
        raise Refuse("unexpected composite source run")
    if pilot.get("contract_sha256") != "4aaa00c265ee14a8ea5389c2191e9be568122154b74976325b911afd536b1d48":
        raise Refuse("pilot contract SHA mismatch")
    report = pilot.get("verification") or {}
    if (report.get("status") != "PASS" or report.get("counts") != {"PASS":269,"FAIL":0,"UNRESOLVED":0}
            or report.get("contract_sha256") != pilot["contract_sha256"]
            or report.get("run_id") != "pilot_002"):
        raise Refuse("pilot verification not PASS/bound")
    all_keys = set(full_prompt_hashes)
    full_benchmarks = {"/".join(k.split("|")[:2]) for k in all_keys}
    if len(all_keys) != 180 or len(full_benchmarks) != 60:
        raise Refuse("full prompt universe must be exactly 60/180")
    populations = []
    for block, count in ((pilot,12),(extension,48)):
        hashes = block.get("prompt_hashes") or {}
        benchmark_ids = block.get("benchmark_ids") or []
        benchmark_set = set(benchmark_ids)
        if len(benchmark_ids) != count or len(benchmark_set) != count or len(hashes) != count*3:
            raise Refuse("wrong population size/duplicate benchmarks")
        expected_keys = {key for key in all_keys if "/".join(key.split("|")[:2]) in benchmark_set}
        if set(hashes) != expected_keys or any(full_prompt_hashes.get(k) != v for k,v in hashes.items()):
            raise Refuse("prompt hash/key disagreement")
        for benchmark in benchmark_set:
            models = [k.split("|")[2] for k in hashes if "/".join(k.split("|")[:2]) == benchmark]
            if sorted(models) != ["mpi","omp","serial"]:
                raise Refuse("incomplete execution triple")
        if sorted(block.get("execution_models",[])) != ["mpi","omp","serial"]:
            raise Refuse("execution-model mismatch")
        if block.get("samples_per_prompt") != 1:
            raise Refuse("samples-per-prompt mismatch")
        if len(block.get("model_ids",[])) != 11 or len(set(block["model_ids"])) != 11:
            raise Refuse("model set must have eleven unique IDs")
        populations.append(benchmark_set)
    if set(pilot["model_ids"]) != set(extension["model_ids"]):
        raise Refuse("model-set disagreement")
    if populations[0] & populations[1] or populations[0] | populations[1] != full_benchmarks:
        raise Refuse("overlap or incomplete union")
    compare_conditions(pilot["measurement_conditions"], extension["measurement_conditions"],
                       certificate, certificate_sha)
    return {"pilot_cells":396,"extension_cells":1584,"composite_cells":1980,"overlap":0}

def union_rows(sources, expected_keys, repair=False):
    """Materialize and validate before yielding anything; preserve every original row.

    Callers supply expected repair keys from terminal trajectories, not from
    a Cartesian iteration grid. Returned envelopes retain source provenance.
    """
    result, seen = [], set()
    for source_run, rows in sources:
        for row in rows:
            fields = ("benchmark", "execution_model", "model_id", "sample_index")
            if repair:
                fields += ("variant", "iteration")
            if any(field not in row for field in fields):
                raise Refuse("missing canonical cell identity")
            if row.get("run_id") != source_run:
                raise Refuse("source run identity mismatch")
            key = tuple(row[field] for field in fields)
            if key in seen:
                raise Refuse("duplicate composite cell")
            seen.add(key)
            result.append({"source_run":source_run, "record":row})
    if seen != set(expected_keys):
        raise Refuse("missing/unexpected composite cells")
    return result

def verify_manifest(path, require_complete=False):
    """Reopen all pinned artifacts. A planned study is never a completed study."""
    from thesis.evaluation import pilot_run_contract as pc
    from thesis.evaluation.extension_contract import ROOT, CERTIFICATE
    study=json.loads(Path(path).read_text(encoding='utf-8'))
    body={k:v for k,v in study.items() if k!='manifest_sha256'}
    if study.get('schema_version')!='composite_study.v1' or study.get('study_id')!='full_001' or ch.canonical_sha256(body)!=study.get('manifest_sha256'):
        raise Refuse('composite manifest identity/fingerprint mismatch')
    blocks=study.get('source_runs') or []
    if len(blocks)!=2 or [b.get('run_id') for b in blocks]!=['pilot_002','full_ext_001']:
        raise Refuse('unexpected composite sources')
    contracts=[]
    for block in blocks:
        expected=ROOT/'thesis/results/intermediate'/block['run_id']/'run_contract.json'
        observed=Path(block['contract_path'])
        if not observed.is_absolute(): observed=ROOT/observed
        if observed.resolve()!=expected.resolve(): raise Refuse('contract path outside declared source')
        contract=pc.load_frozen(expected)
        if contract['contract_sha256']!=block.get('contract_sha256') or contract['run_id']!=block['run_id'] or contract['status']!='READY':
            raise Refuse('source contract identity/fingerprint disagreement')
        for field, actual in (('model_ids',contract['model_ids']),('execution_models',contract['execution_models']),
                              ('samples_per_prompt',contract['population']['num_samples_per_prompt']),
                              ('prompt_hashes',contract['selected_prompt_hashes']),('benchmark_ids',contract['population_freeze']['benchmark_ids'])):
            if block.get(field)!=actual: raise Refuse('manifest/contract field disagreement: '+field)
        if block['run_id']=='full_ext_001' and block['measurement_conditions']!=contract['conditions']:
            raise Refuse('extension measurement condition disagreement')
        if block['run_id']=='pilot_002':
            for key,value in contract['conditions'].items():
                if block['measurement_conditions'].get(key)!=value: raise Refuse('pilot condition disagreement')
        contracts.append(contract)
    report_path=ROOT/'thesis/results/intermediate/pilot_002/post_run_verification.json'
    if ch.raw_sha256(report_path)!=blocks[0].get('post_run_verification_sha256'):
        raise Refuse('pilot report file fingerprint disagreement')
    report=json.loads(report_path.read_text(encoding='utf-8'))
    if blocks[0]['verification']!={key:report[key] for key in ('run_id','contract_sha256','status','counts')}:
        raise Refuse('pilot report summary disagreement')
    certificate=json.loads(CERTIFICATE.read_text(encoding='utf-8'))
    sha=study.get('equivalence_sha256')
    if (contracts[1].get('extension_provenance') or {}).get('equivalence_sha256')!=sha:
        raise Refuse('extension/composite equivalence pin disagreement')
    result=validate_blocks(blocks[0],blocks[1],contracts[0]['population']['prompt_hashes'],certificate,sha)
    if require_complete:
        extension_report=ROOT/'thesis/results/intermediate/full_ext_001/post_run_verification.json'
        if not extension_report.is_file(): raise Refuse('extension has not completed verification')
        report=json.loads(extension_report.read_text(encoding='utf-8'))
        if report.get('status')!='PASS' or report.get('contract_sha256')!=contracts[1]['contract_sha256']:
            raise Refuse('extension verification not PASS/bound')
        rows=read_base_cells(study,ROOT)
        if len(rows)!=1980: raise Refuse('incomplete composite base cells')
    return dict(status='PASS',scope='COMPLETE_BASE_POPULATION' if require_complete else 'PLANNED_COMPOSITE_ONLY',**result)

def read_base_cells(study,root):
    """Read original generation rows in place, retain them verbatim in envelopes."""
    expected=set(); sources=[]
    for block in study['source_runs']:
        run=block['run_id']; normalized=[]
        for model in block['model_ids']:
            for key in block['prompt_hashes']:
                kind,name,execution=key.split('|')
                for index in range(block['samples_per_prompt']):
                    expected.add((kind+'/'+name,execution,model,index))
            path=Path(root)/'thesis/results/raw'/run/model/'generations.jsonl'
            if not path.is_file(): raise Refuse('missing source generations: '+run+'/'+model)
            for line in path.read_text(encoding='utf-8').splitlines():
                if not line.strip(): continue
                row=json.loads(line); prompt=row.get('prompt') or {}
                kind,name,execution=(prompt.get(k) for k in ('problem_type','name','parallelism_model'))
                key='%s|%s|%s'%(kind,name,execution)
                if (row.get('run_id')!=run or (row.get('model') or {}).get('id')!=model or
                        block['prompt_hashes'].get(key)!=ch.utf8_sha256(prompt.get('prompt_text') or '')):
                    raise Refuse('source record identity/prompt disagreement')
                prefix='%s__%s__%s__%s__sample_'%(model,kind,name,execution)
                sample=row.get('sample_id') or ''
                suffix=sample[len(prefix):] if sample.startswith(prefix) else ''
                if not suffix.isdigit() or suffix!=str(int(suffix)):
                    raise Refuse('invalid canonical sample identity')
                normalized.append(dict(run_id=run,benchmark=kind+'/'+name,execution_model=execution,
                                       model_id=model,sample_index=int(suffix),original_record=row))
        sources.append((run,normalized))
    return union_rows(sources,expected)
