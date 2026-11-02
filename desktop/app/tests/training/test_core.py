import copy, json, tempfile, unittest
from pathlib import Path
import torch
import random,sys,types
from unittest.mock import patch
from types import SimpleNamespace
from bgagent10.engine import DEFAULT_RULES,EnvironmentProcess,public_input
from bgagent10.encoding import CardCatalog,action_descriptors,card_semantics
from bgagent10.model import PolicyModel,observation_tensors,load_policy
from bgagent10.training import advantages,utility,update,validate_config,checkpoint,run,auxiliary_update

class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.catalog=CardCatalog(DEFAULT_RULES); cls.env=EnvironmentProcess()
        cls.layout=cls.env.metadata['layout']; cls.obs=public_input(cls.env.request('reset',seed=973421))
    @classmethod
    def tearDownClass(cls): cls.env.close()
    def test_public_allowlist(self):
        polluted=dict(self.obs,seed=123,snapshot={'hidden':'secret'},episode_id='xxx',diagnostics={'placements':[1]})
        self.assertEqual(public_input(polluted),self.obs)
    def test_stable_mapping_and_semantics(self):
        cat=self.catalog
        for i,key in enumerate(cat.runtime_ids): self.assertEqual(cat.stable_ids[int(cat.runtime_to_stable[i])],key)
        a={'text':'After you buy a minion, give a friendly minion +2 Attack permanently.','tier':2}
        b=dict(a,text='At the start of combat, give an enemy minion +2 Attack this combat.')
        self.assertNotEqual(card_semantics(a),card_semantics(b))
        self.assertEqual(card_semantics(dict(a,id='X')),card_semantics(dict(a,id='Y')))
    def test_semantic_actions(self):
        a=action_descriptors(); self.assertEqual(len(a),245)
        self.assertEqual(a[8],(7,37,0,0,0)); self.assertEqual(a[46],(11,27,0,0,0)); self.assertEqual(a[244],(13,26,26,6,0))
    def test_masks_memory_and_real_gradient(self):
        model=PolicyModel(self.catalog,self.layout,'micro').eval()
        inputs=observation_tensors([self.obs],'cpu')
        logits,value,hidden,place=model(*inputs)
        probs=logits.softmax(-1)
        self.assertAlmostEqual(float(probs.sum()),1,places=6)
        self.assertEqual(float(probs[~inputs[2]].sum()),0)
        _,_,hidden2,_=model(*inputs,hidden)
        self.assertFalse(torch.equal(hidden,hidden2))
        loss=value.square().mean()+place.square().mean()-logits[:,inputs[2][0]].mean()
        before=model.value.weight.detach().clone(); optim=torch.optim.AdamW(model.parameters(),lr=1e-3)
        loss.backward(); optim.step(); self.assertFalse(torch.equal(before,model.value.weight))
        with self.assertRaises(ValueError): model(inputs[0],inputs[1],torch.zeros_like(inputs[2]))
    def test_rewards_and_sequence_ppo_fixture(self):
        self.assertEqual(utility(1),1); self.assertEqual(utility(8),-1)
        self.assertEqual(advantages([0,0],1,lam=1),[(1,1),(1,1)])
        model=PolicyModel(self.catalog,self.layout,'micro').eval(); optimizer=torch.optim.AdamW(model.parameters(),lr=1e-4)
        with torch.no_grad():
            logits,v,_,_=model(*observation_tensors([self.obs],'cpu')); dist=torch.distributions.Categorical(logits=logits); a=dist.sample()
        row=dict(observation=self.obs,action=int(a),log_prob=float(dist.log_prob(a)),value=float(v))
        # Explicit artificial one-step fixture; never counted as a completed game.
        fixture=[dict(trajectories=[[row]]+[[] for _ in range(7)],ranks=list(range(1,9)))]
        report=update(model,optimizer,fixture,validate_config({'model_preset':'micro','ppo_epochs':1}))
        self.assertEqual(report['optimizer_steps'],1)
    def test_checkpoint_atomic_and_strict_binding(self):
        model=PolicyModel(self.catalog,self.layout,'micro'); opt=torch.optim.AdamW(model.parameters()); scheduler=torch.optim.lr_scheduler.LambdaLR(opt,lambda _:1)
        config=validate_config({'model_preset':'micro'}); counters=dict(completed_games=0,attempted_games=0,round=0,updates=0,quarantined=[])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'a.pt'; checkpoint(path,model,opt,scheduler,config,self.catalog,self.env.metadata['binding'],counters,None)
            saved=torch.load(path,weights_only=False); self.assertEqual(saved['catalog'],self.catalog.manifest())
            self.assertEqual(saved['sampler']['next_training_seed'],97); self.assertFalse(path.with_suffix('.tmp').exists())
            self.assertEqual(saved['binding'],self.env.metadata['binding'])
    def test_wrong_action_rejected(self):
        with self.assertRaises(RuntimeError): self.env.request('step',index=244)

    def test_seat_and_episode_memory_reset(self):
        model=PolicyModel(self.catalog,self.layout,'micro').eval(); tensors=observation_tensors([self.obs],'cpu')
        with torch.no_grad():
            logits0,_,seat0,_=model(*tensors)
            logits1,_,seat1,_=model(*tensors) # Independent seat, zero initial memory.
            self.assertTrue(torch.equal(seat0,seat1)); self.assertTrue(torch.equal(logits0,logits1))
            _,_,recurrent,_=model(*tensors,seat0)
            self.assertFalse(torch.equal(recurrent,seat1))
            _,_,new_episode,_=model(*tensors,None)
            self.assertTrue(torch.equal(new_episode,seat1))

    def test_same_tensor_shape_wrong_semantics_rejected(self):
        model=PolicyModel(self.catalog,self.layout,'micro'); opt=torch.optim.AdamW(model.parameters()); scheduler=torch.optim.lr_scheduler.LambdaLR(opt,lambda _:1)
        counters=dict(completed_games=0,attempted_games=0,eval_attempted_games=0,round=0,updates=0,quarantined=[])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'a.pt'; checkpoint(path,model,opt,scheduler,validate_config({'model_preset':'micro'}),self.catalog,self.env.metadata['binding'],counters,None)
            payload=torch.load(path,weights_only=False)
            payload['contract']['reward']='incorrect-identical-tensor-shape'; torch.save(payload,path)
            with self.assertRaisesRegex(ValueError,'semantics mismatch'): load_policy(path)

    def test_abnormal_lobby_pauses_before_any_gradient(self):
        metadata=self.env.metadata
        class FailedCollector:
            def __init__(self,*args):
                self.metadata=metadata; self.workers=[SimpleNamespace(metadata=metadata)]
            def collect(self,*args,**kwargs): return [],[dict(seed=97,error='controlled combat_guard fixture')]
            def close(self): pass
        with tempfile.TemporaryDirectory() as tmp:
            with patch('bgagent10.training.Collector',FailedCollector),patch('bgagent10.training.update') as gradient:
                run({'model_preset':'micro','workers':1,'rounds':1,'games_per_round':1,'torch_threads':2},tmp)
                gradient.assert_not_called()
            status=json.loads((Path(tmp)/'status.json').read_text('utf8'))
            self.assertEqual(status['state'],'paused'); self.assertEqual(status['completed_games'],0)
            saved=torch.load(status['checkpoint'],weights_only=False)
            self.assertEqual(len(saved['quarantine_manifest']),1)
            self.assertEqual(saved['counters']['attempted_games'],1)
            self.assertFalse((Path(tmp)/'writer.lock').exists())

    @unittest.skipUnless(torch.cuda.is_available(),'CUDA-specific RNG roundtrip')
    def test_cuda_rng_checkpoint_roundtrip(self):
        original=torch.cuda.get_rng_state_all()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'rng.pt'
            torch.cuda.manual_seed_all(973421)
            captured=torch.cuda.get_rng_state_all()
            torch.save({'cuda_rng':captured},path)
            expected=torch.rand(8,device='cuda')
            loaded=torch.load(path,map_location='cuda',weights_only=False)
            self.assertTrue(all(state.device.type=='cuda' for state in loaded['cuda_rng']))
            torch.cuda.set_rng_state_all([state.cpu() for state in loaded['cuda_rng']])
            actual=torch.rand(8,device='cuda')
            self.assertTrue(torch.equal(expected,actual))
        torch.cuda.set_rng_state_all(original)

    def test_auxiliary_seed_varies_and_checkpoint_resume_repeats_next_seed(self):
        model=PolicyModel(self.catalog,self.layout,'micro').eval();optimizer=torch.optim.AdamW(model.parameters())
        scheduler=torch.optim.lr_scheduler.LambdaLR(optimizer,lambda _:1)
        config=validate_config(dict(model_preset='micro',auxiliary_updates=1,auxiliary_batch_size=1,live_data_root='controlled-fixture'))
        observed=[]; fixture=types.ModuleType('bgagent10.live_data')
        def sample(*args,**kwargs):
            observed.append(kwargs['seed'])
            return [dict(source='simulation',steps=[dict(observation=self.obs,confidence=1.,missing_fields=[],flags=[])],loss_weight=1.)]
        fixture.sample_auxiliary=sample; fixture.record_usage=lambda *args,**kwargs:None
        original=random.getstate()
        try:
            import bgagent10
            with patch.dict(sys.modules,{'bgagent10.live_data':fixture}),patch.object(bgagent10,'live_data',fixture,create=True),tempfile.TemporaryDirectory() as tmp:
                random.seed(973421)
                first=auxiliary_update(model,optimizer,[],config,self.env.metadata['binding'],self.catalog)
                path=Path(tmp)/'rng.pt'
                checkpoint(path,model,optimizer,scheduler,config,self.catalog,self.env.metadata['binding'],dict(completed_games=0,attempted_games=0,round=0,updates=1,quarantined=[]),None)
                second=auxiliary_update(model,optimizer,[],config,self.env.metadata['binding'],self.catalog)
                saved=torch.load(path,weights_only=False);random.setstate(saved['python_rng'])
                restored=auxiliary_update(model,optimizer,[],config,self.env.metadata['binding'],self.catalog)
                self.assertNotEqual(first[0]['sampling_seed'],second[0]['sampling_seed'])
                self.assertEqual(second[0]['sampling_seed'],restored[0]['sampling_seed'])
                self.assertEqual(observed,[first[0]['sampling_seed'],second[0]['sampling_seed'],restored[0]['sampling_seed']])
                self.assertEqual(restored[0]['live_sequences'],0)
        finally:random.setstate(original)

if __name__=='__main__': unittest.main()
