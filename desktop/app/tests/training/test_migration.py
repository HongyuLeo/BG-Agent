import copy,tempfile,unittest
from pathlib import Path
import torch
from bgagent10.engine import DEFAULT_RULES,EnvironmentProcess
from bgagent10.encoding import CardCatalog,card_semantics
from bgagent10.model import PolicyModel
from bgagent10.training import checkpoint,validate_config
from bgagent10.migration import migrate_checkpoint,prove_policy_unchanged

class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2); cls.catalog=CardCatalog(DEFAULT_RULES); env=EnvironmentProcess()
        cls.meta=env.metadata;env.close()
    def make_source(self,root):
        model=PolicyModel(self.catalog,self.meta['layout'],'micro')
        opt=torch.optim.AdamW(model.parameters()); sched=torch.optim.lr_scheduler.LambdaLR(opt,lambda _:1)
        path=Path(root)/'source.pt'; checkpoint(path,model,opt,sched,validate_config({'model_preset':'micro'}),self.catalog,self.meta['binding'],
            dict(completed_games=0,attempted_games=0,round=0,updates=0,quarantined=[]),None)
        return path,model
    def test_reorder_preserves_functions(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,model=self.make_source(tmp); original=source.read_bytes(); cat=copy.deepcopy(self.catalog)
            cat.runtime_ids=['']+list(reversed(cat.runtime_ids[1:])); stable={key:i for i,key in enumerate(cat.stable_ids)}
            cat.runtime_to_stable=torch.tensor([stable[x] for x in cat.runtime_ids])
            from bgagent10.encoding import digest
            cat.mapping_hash=digest(cat.runtime_ids)
            dest=Path(tmp)/'candidate.pt'; report=migrate_checkpoint(source,dest,cat,self.meta['binding'],self.meta['layout'],kind='mapping-reorder')
            saved=torch.load(dest,weights_only=False)
            self.assertEqual(source.read_bytes(),original); self.assertFalse(report['promoted'])
            self.assertTrue(torch.equal(saved['model']['identity.weight'],model.identity.weight))
            self.assertTrue(torch.equal(saved['model']['runtime_to_stable'],cat.runtime_to_stable))
    def test_new_card_and_numeric_adaptation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,model=self.make_source(tmp); cat=copy.deepcopy(self.catalog)
            cat.stable_ids.append('ZZZ_TEST_EXISTING_MECHANISM');cat.runtime_ids.append('ZZZ_TEST_EXISTING_MECHANISM')
            cat.runtime_to_stable=torch.cat((cat.runtime_to_stable,torch.tensor([len(cat.stable_ids)-1])))
            from bgagent10.encoding import digest
            cat.mapping_hash=digest(cat.runtime_ids)
            cat.semantics=torch.cat((cat.semantics,torch.tensor([card_semantics({'tier':2,'text':'Battlecry: Give a friendly minion +2 Attack.'})])))
            dest=Path(tmp)/'new.pt'; report=migrate_checkpoint(source,dest,cat,self.meta['binding'],self.meta['layout'],kind='new-existing-mechanism-card')
            saved=torch.load(dest,weights_only=False)
            self.assertEqual(report['new_stable_ids'],['ZZZ_TEST_EXISTING_MECHANISM'])
            self.assertTrue(torch.equal(saved['model']['identity.weight'][:-1],model.identity.weight))
            self.assertEqual(saved['optimizer']['state'],{});self.assertIsNone(saved['evaluation'])
            changed=copy.deepcopy(self.catalog); changed.semantics[1,0]+=1
            dest2=Path(tmp)/'numeric.pt';migrate_checkpoint(source,dest2,changed,self.meta['binding'],self.meta['layout'],kind='numeric-rule-adaptation')
            self.assertTrue(torch.equal(torch.load(dest2,weights_only=False)['model']['semantics'],changed.semantics))
    def test_ast_proof_rejects_forward_change(self):
        import bgagent10.model as module
        text=Path(module.__file__).read_text('utf8')
        self.assertTrue(prove_policy_unchanged(text,text+'\n# harmless loader comment')['PolicyModel_AST_equal'])
        with self.assertRaises(ValueError):prove_policy_unchanged(text,text.replace('hidden=self.memory(tokens[:,0],hidden)','hidden=self.memory(tokens[:,0],hidden)*0'))
        with self.assertRaises(ValueError):prove_policy_unchanged(text,text.replace("'micro':(48,1,4)","'micro':(48,1,2)"))

if __name__=='__main__':unittest.main()
