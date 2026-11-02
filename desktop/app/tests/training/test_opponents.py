import copy,hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
import torch
from bgagent10.engine import DEFAULT_RULES,EnvironmentProcess,public_input
from bgagent10.encoding import CardCatalog
from bgagent10.model import PolicyModel
from bgagent10.opponents import FrozenPool,heuristic_action,policy_fingerprint
from bgagent10.training import Collector,checkpoint,validate_config,evaluation_summary

class OpponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2);cls.catalog=CardCatalog(DEFAULT_RULES); env=EnvironmentProcess()
        cls.meta=env.metadata;cls.obs=env.request('reset',seed=97);env.close()
    def make_history(self,tmp):
        model=PolicyModel(self.catalog,self.meta['layout'],'micro');opt=torch.optim.AdamW(model.parameters());scheduler=torch.optim.lr_scheduler.LambdaLR(opt,lambda _:1)
        path=Path(tmp)/'history.pt';checkpoint(path,model,opt,scheduler,validate_config({'model_preset':'micro'}),self.catalog,self.meta['binding'],
            dict(completed_games=0,attempted_games=0,round=0,updates=0,quarantined=[]),None)
        return path,hashlib.sha256(path.read_bytes()).hexdigest()
    def test_deterministic_assignment_and_heuristics(self):
        pool=FrozenPool('mixed',None,self.catalog,self.meta['binding'],self.meta['layout'],'cpu')
        self.assertEqual(pool.assignments(97),pool.assignments(97));self.assertEqual(pool.assignments(97).count('learner'),1)
        self.assertEqual(pool.assignments(97)[97%8],'learner')
        selfplay=FrozenPool('selfplay',None,self.catalog,self.meta['binding'],self.meta['layout'],'cpu')
        self.assertEqual(selfplay.assignments(97),['learner']*8)
        import random
        for style in ('balanced','economy','tempo','conservative','random'):
            action=heuristic_action(public_input(self.obs),random.Random(97),style)
            self.assertTrue(self.obs['action_mask'][action])
    def test_history_versions_and_only_learner_ppo_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,sha=self.make_history(tmp);spec=[dict(kind='checkpoint',path=str(path),sha256=sha)]
            config=validate_config(dict(workers=1,train_opponents='history',train_opponent_pool=spec,model_preset='micro',eval_opponent='history',eval_opponent_pool=spec))
            meta=self.meta;initial=self.obs
            class FixtureEnv:
                def __init__(self,*args):self.metadata=meta;self.tick=0
                def close(self):pass
                def request(self,command,**kwargs):
                    if command=='reset':self.tick=0
                    else:self.tick+=1
                    obs=copy.deepcopy(initial);obs['seat']=obs['current_seat']=self.tick%8
                    if self.tick==16:obs['diagnostics']=dict(done=True,terminated=True,truncated=False,stop_reason='normal_elimination',placements=list(range(1,9)))
                    return obs
            with patch('bgagent10.training.EnvironmentProcess',FixtureEnv):collector=Collector(config,self.catalog)
            actor=collector.train_pool.models['opponent-0']; before=policy_fingerprint(actor); memories=[]
            hook=actor.register_forward_pre_hook(lambda mod,args:memories.append(args[3].clone()))
            learner=PolicyModel(self.catalog,self.meta['layout'],'micro')
            games,failures=collector.collect(learner,[97]); hook.remove();collector.close()
            self.assertFalse(failures);self.assertEqual(len(games),1)
            self.assertEqual([len(x) for x in games[0]['trajectories']],[0,2,0,0,0,0,0,0])
            self.assertTrue(all(torch.count_nonzero(x)==0 for x in memories[:7]))
            self.assertTrue(all(torch.count_nonzero(x)>0 for x in memories[7:]))
            self.assertEqual(policy_fingerprint(actor),before);self.assertFalse(any(p.requires_grad for p in actor.parameters()))
            bad=[dict(spec[0],sha256='0'*64)]
            with self.assertRaisesRegex(ValueError,'SHA mismatch'):FrozenPool('history',bad,self.catalog,self.meta['binding'],self.meta['layout'],'cpu')
            payload=torch.load(path,weights_only=False);payload['binding']['schema']='wrong';torch.save(payload,path)
            bad=[dict(spec[0],sha256=hashlib.sha256(path.read_bytes()).hexdigest())]
            with self.assertRaisesRegex(ValueError,'version mismatch'):FrozenPool('history',bad,self.catalog,self.meta['binding'],self.meta['layout'],'cpu')
    def test_worker_constructor_cleanup(self):
        first=MagicMock()
        with patch('bgagent10.training.EnvironmentProcess',side_effect=[first,RuntimeError('second failed')]):
            with self.assertRaises(RuntimeError):Collector(validate_config({'workers':2}),self.catalog)
        first.close.assert_called_once()
        with patch('subprocess.Popen'),patch('threading.Thread'),patch.object(EnvironmentProcess,'request',side_effect=RuntimeError('metadata failed')),patch.object(EnvironmentProcess,'close') as cleanup:
            with self.assertRaises(RuntimeError):EnvironmentProcess()
            cleanup.assert_called_once()
    def test_small_sample_interval_is_not_zero_width(self):
        summary=evaluation_summary([dict(ranks=[8]*8,learner_seat=0,seed=i) for i in (1,2)],'scripted','fixture')
        self.assertLess(summary['ci_low'],summary['ci_high']);self.assertIn('Hoeffding',summary['ci_method'])

if __name__=='__main__':unittest.main()
