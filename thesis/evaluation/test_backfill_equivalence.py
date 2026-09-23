"""Differential source and fail-closed routing tests; no analyzers/providers."""
import ast
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from thesis.repair import backfill_authority as ba

ROOT=Path(__file__).resolve().parents[2]
OLD='1a24be7be943b979457e2cb8b3bf22fef5b99a4a'

def old_source(path):
    return subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'show',OLD+':'+path],cwd=ROOT).decode('utf-8')

class RoutingNormalization(ast.NodeTransformer):
    def visit_Assign(self,node):
        if any(isinstance(t,ast.Name) and t.id=='authority_run_id' for t in node.targets): return None
        return self.generic_visit(node)
    def visit_If(self,node):
        if isinstance(node.test,ast.Attribute) and node.test.attr=='backfill_base_run_id': return None
        return self.generic_visit(node)
    def visit_Name(self,node):
        if node.id=='authority_run_id': node.id='run_id'
        return node
    def visit_Expr(self,node):
        if (isinstance(node.value,ast.Call) and node.value.args and
                isinstance(node.value.args[0],ast.Constant) and
                node.value.args[0].value=='--backfill-base-run-id'): return None
        return self.generic_visit(node)

class EquivalenceTests(unittest.TestCase):
    def test_static_missing_only_preserves_compiler_and_gaps(self):
        from thesis.evaluation.test_tool_state import StaticWorld, FakeStaticTool
        from thesis.evaluation.framework import STATE_TOOL_ERROR
        class Counted(FakeStaticTool):
            calls=0
            def run(self,sample,ctx):
                self.calls+=1
                return super().run(sample,ctx)
        with tempfile.TemporaryDirectory() as tmp:
            sample='m__a__b__serial__sample_0'
            world=StaticWorld(tmp,{sample:('serial','int x;\n')})
            compiler=Counted('compiler',state=STATE_TOOL_ERROR)
            tidy=Counted('clang_tidy')
            world.register(compiler,tidy)
            world.run('synthetic',['compiler'])
            before=copy.deepcopy(world.records('synthetic')[sample]['tools']['compiler'])
            world.run('synthetic',['compiler','clang_tidy'])
            self.assertEqual(before,world.records('synthetic')[sample]['tools']['compiler'])
            self.assertEqual((1,1),(compiler.calls,tidy.calls))
            world.run('synthetic',['compiler','clang_tidy'])
            self.assertEqual((1,1),(compiler.calls,tidy.calls))

    def test_real_fresh_authorization_then_prepopulated_start_refused(self):
        from thesis.evaluation.test_post_run_verification import World, fake_prober
        from thesis.evaluation import run_authorization as ra
        with tempfile.TemporaryDirectory() as tmp:
            # World invokes the real FRESH authorization path BEFORE synthetic
            # records. Only runtime identity is supplied by its fake prober.
            world=World(Path(tmp),run_id='full_ext_001')
            authorization=ra.load_authorization(world.config,world.run_id)
            self.assertEqual('START_ALLOWED',authorization['decision'])
            with self.assertRaises(ra.StartRefused):
                ra.authorize_start(world.config,world.config_path,'fixture',world.run_id,
                                   world.contract_path,prober=fake_prober)

    def test_runners_only_change_authority_routing(self):
        for path in ('thesis/evaluation/run_static_analysis.py','thesis/evaluation/run_enhanced_tests.py'):
            with self.subTest(path=path):
                old=ast.parse(old_source(path))
                new=RoutingNormalization().visit(ast.parse((ROOT/path).read_text(encoding='utf-8')))
                self.assertEqual(ast.dump(old),ast.dump(new))

    def test_measurement_implementations_byte_identical(self):
        paths=('thesis/evaluation/dynamic_tools.py','thesis/evaluation/run_dynamic_analysis.py',
               'thesis/evaluation/run_correctness.py','thesis/evaluation/tools.py',
               'thesis/evaluation/framework.py','thesis/evaluation/build_config.py',
               'thesis/evaluation/tool_config.py','thesis/evaluation/stage_runtime.py',
               'thesis/assembly/cleaning.py','thesis/assembly/assemble_sources.py',
               'thesis/repair/orchestrator.py','thesis/repair/feedback.py',
               'thesis/enhanced_tests/specs.py','thesis/enhanced_tests/capabilities.py')
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(old_source(path).replace('\r\n','\n'),(ROOT/path).read_text(encoding='utf-8'))

    def target(self,tmp,base='base',target='base__static_feedback__iter1',enhanced=False,terminal=True,sample='s'):
        config={'outputs':{'intermediate_dir':tmp}}
        directory=Path(tmp)/target/'m'; directory.mkdir(parents=True,exist_ok=True)
        (directory/'assembly.jsonl').write_text(json.dumps({'run_id':target,'model_id':'m','sample_id':sample})+'\n')
        state={'enforced':True,'contract':{'model_ids':['m'],'repair_plan':{'variants':['static_feedback'],'max_iterations':2}}}
        terminality={'state_present':True,'terminal':terminal,'unknown_statuses':{},'invalid_iterations':0}
        with patch('thesis.evaluation.stage_runtime.enforcement_state',return_value=state), \
             patch('thesis.repair.orchestrator.load_sample_states',return_value={'s':{'iteration':1}}), \
             patch('thesis.repair.run_backfill.loop_state_terminality',return_value=terminality):
            return ba.validate_target(config,base,target,'m',enhanced)

    def test_valid_external_target(self):
        with tempfile.TemporaryDirectory() as tmp: self.assertTrue(self.target(tmp)['enforced'])

    def test_wrong_base_refused(self):
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError): self.target(tmp,base='other')

    def test_sample_without_repair_history_refused(self):
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError): self.target(tmp,sample='foreign')

    def test_iteration_above_recorded_state_refused(self):
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError): self.target(tmp,target='base__static_feedback__iter2')

    def test_enhanced_active_refused(self):
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError): self.target(tmp,enhanced=True,terminal=False)

    def test_enhanced_terminal_allowed(self):
        with tempfile.TemporaryDirectory() as tmp: self.target(tmp,enhanced=True)

    def test_exclusive_lock_and_stale_lock_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'base'/'m'; directory.mkdir(parents=True)
            config={'outputs':{'intermediate_dir':tmp}}
            with ba.backfill_lock(config,'base','m'):
                with self.assertRaises(FileExistsError):
                    with ba.backfill_lock(config,'base','m'): pass
            (directory/'backfill.lock').write_text('stale')
            with self.assertRaises(FileExistsError):
                with ba.backfill_lock(config,'base','m'): pass

if __name__=='__main__': unittest.main(verbosity=2)
