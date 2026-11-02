import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import types
import sys
import math
from bgagent10.live_producer import PublicLogProducer,installed_build
from bgagent10.live_encoding import *
from bgagent10.live_data import *
from bgagent10.live import GameSession, preflight, start, ExclusiveLease


def known(value):return {'value':value,'known':True,'source':'explicit synthetic fixture; not client evidence'}


def empty_facts():
    return {'globals':{n:known(0) for n in GLOBAL_NAMES},'lobby_races':{n:known(0) for n in RACES},'quests':[{'present':known(0)} for _ in range(3)],'pending_kind':known(0),'board':[{'present':known(0)} for _ in range(7)],'hand':[{'present':known(0)} for _ in range(10)],'shop':[{'present':known(0)} for _ in range(8)],'choices':[{'present':known(0)} for _ in range(16)],'opponents':[{n:known(0) for n in OPP_NAMES} for _ in range(7)],'opponent_boards':[{'present':known(0)} for _ in range(49)],'card_ids':{key:[known('') for _ in range(count)] for key,count in CARD_GROUPS}}


def make_episode(root,eid='test1',game_key='same-game',source='real-client',rank=8,count=16):
    # Fabricated fixtures exercise intake only; never counted as played games.
    with Journal(root,eid) as j:
        ref=j.capture(b'explicit test fixture, NOT actual game evidence')
        j.append('begin',{'source':source,'game_key':game_key,'versions':{k:'fixture-v1' for k in VERSION_FIELDS}})
        for i in range(count):
            j.append('decision',{'turn':1,'seat_id':0,'observation':{'features':[0.]*3227,'cards':[0]*124,'action_mask':[1]+[0]*244},'history':[],'missing_fields':[],'confidence':1.,'legal_actions':[0],'suggested_action':0,'executed_action':0,'execution':{'request_id':str(i),'confirmed':True,'before_evidence':ref,'after_evidence':ref},'behavior_probability':1.,'value_prediction':0.,'after':{},'battle_result':None,'flags':[]})
        j.append('terminal',{'rank':rank,'reason':'normal','evidence':ref})
    return ingest(root,eid)


class EncodingTests(unittest.TestCase):
    def test_native_producer_never_defaults_controller_one(self):
        parser=PublicLogProducer();parser.feed(b'GameState.DebugPrintPower() - CREATE_GAME\nGameState.DebugPrintPower() - Player EntityID=2 PlayerID=1\nGameState.DebugPrintPower() - tag=RESOURCES value=7\n')
        report=parser.snapshot()
        self.assertIsNone(report['observer'])
        # Unknown leaves are explicit; neither controller 1 nor its resources
        # may become the observer's known gold or a usable policy observation.
        gold=report['facts']['globals']['gold']
        self.assertIs(gold['known'],False)
        self.assertIsNone(gold['value'])
        self.assertFalse(report['complete'])
        self.assertFalse(report['policy_ready'])
        self.assertIsNone(report['model_observation'])
        self.assertIn('observer',[gap['path'] for gap in report['gaps']])
    def test_installed_metadata_independent_from_historical_log(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);(path/'Hearthstone.exe').write_bytes(b'fixture executable');(path/'.product.db').write_bytes(b'local-metadata:37.0.0.255790')
            self.assertEqual(installed_build(path/'Hearthstone.exe')['build'],'37.0.0.255790')
    def test_keyword_and_numeric_layout(self):
        facts=empty_facts();minion={n:known(0) for n in MINION_NAMES}
        minion.update(present=known(1),attack=known(250),health=known(3),max_health=known(40),DIVINE_SHIELD=known(1),NAGA=known(1))
        facts['board'][0]=minion;f=encode_public(facts,{})['features']
        self.assertEqual(f[68:72],[1.,25.,.3,4.])
        self.assertEqual(f[68+9],1.)
        self.assertEqual(f[68+30],1.)
    def test_all_245_action_layout_boundaries(self):
        actions=[decode_action(i) for i in range(245)]
        self.assertEqual(len({json.dumps(a,sort_keys=True) for a in actions}),245)
        self.assertEqual(actions[125],{'type':'play','hand':9,'position':7})
        self.assertEqual(actions[195],{'type':'magnetize','hand':9,'board':6})
        self.assertEqual(actions[244],{'type':'reorder','board':6,'position':6})
        with self.assertRaises(ValueError):decode_action(245)
    def test_schema_shape_known_padding(self):
        obs=encode_public(empty_facts(),{})
        self.assertEqual((len(obs['features']),len(obs['cards'])),(3227,124))
        self.assertEqual(obs['features'][59:68],[1.]+[0.]*8)
    def test_missing_scalar_not_zero(self):
        facts=empty_facts();del facts['globals']['gold']
        with self.assertRaises(IncompleteObservation) as ctx:encode_public(facts,{})
        self.assertIn('globals/gold',ctx.exception.gaps)
    def test_unknown_collection_not_empty(self):
        facts=empty_facts();facts['shop']=[]
        with self.assertRaises(IncompleteObservation):encode_public(facts,{})
    def test_unmapped_card_refuses(self):
        facts=empty_facts();facts['card_ids']['identity'][0]=known('new-card')
        with self.assertRaises(IncompleteObservation):encode_public(facts,{})
        self.assertEqual(encode_public(facts,{'new-card':44})['cards'][0],45)
    def test_target_actions_are_not_collapsed(self):
        state={'live_options':[{'action':{'kind':'hero_power','target':'enemy'}}]}
        report=map_options(state);self.assertFalse(report['complete']);self.assertEqual(sum(report['action_mask']),0)
    def test_evidenced_buy(self):
        state={'shop':[{'id':'actual-entity'}],'live_options':[{'action':{'kind':'buy','source':'actual-entity'},'receipt':{'index':3}}]}
        report=map_options(state);self.assertEqual(report['action_mask'][8],1);self.assertEqual(report['commands'][8]['receipt']['index'],3)


class DataTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_immutable_and_exclusive(self):
        with Journal(self.root,'x') as j:
            j.append('begin',{})
            with self.assertRaises(FileExistsError):Journal(self.root,'x')
            with self.assertRaises(FileExistsError):immutable(j.path/'00000000.json',{})
    def test_loss_kept_and_duplicate_quarantined(self):
        first=make_episode(self.root,rank=8);self.assertEqual(first['status'],'qualified')
        second=make_episode(self.root,'alias',rank=1);self.assertEqual(second['status'],'quarantine')
        self.assertEqual(first['split'],second['split'])
    def test_fixtures_are_not_real(self):
        result=make_episode(self.root,source='fixture')
        self.assertIn('not_real_client',result['reasons'])
    def test_crash_tail_quarantined(self):
        with Journal(self.root,'crash') as j:j.append('begin',{})
        (j.path/'00000001.json').write_bytes(b'{')
        result=ingest(self.root,'crash');self.assertEqual(result['status'],'quarantine')
    def test_raw_tamper_never_requalified(self):
        make_episode(self.root)
        path=self.root/'raw/test1/00000017.json';row=json.loads(path.read_text('utf8'));row['data']['rank']=1;path.write_bytes(canonical(row))
        self.assertIn('raw_mutated_since_intake',ingest(self.root,'test1')['reasons'])
        self.assertIn('raw_mutated_since_intake',ingest(self.root,'test1')['reasons'])
    def test_evidence_tamper(self):
        make_episode(self.root)
        next((self.root/'raw/test1/evidence').glob('*')).write_bytes(b'changed')
        self.assertEqual(ingest(self.root,'test1')['status'],'quarantine')
    def test_aux_cap_and_no_ppo(self):
        for i in range(5):make_episode(self.root,f'g{i}',f'g{i}')
        batch=sample_auxiliary(self.root,[[{'simulation':True}]],100)
        live=[s for s in batch if s['source']=='live']
        self.assertLessEqual(len(live),5)
        self.assertEqual(len({s['episode_id'] for s in live}),len(live))
        for item in live:
            self.assertEqual(item['loss_weight'],1.)
            self.assertNotIn('outcome_target',item['steps'][0]['observation'])
            self.assertEqual(item['steps'][0]['outcome_target']['rank'],8)
        record_usage(self.root,batch,'representation')
        self.assertEqual(summarize(self.root)['actual_used_sequences'],len(live))
        with self.assertRaises(ValueError):sample_auxiliary(self.root,[[]],10,purpose='ppo')
    def test_version_filtered_auxiliary_never_uses_old_semantics(self):
        make_episode(self.root,game_key='g0')
        batch=sample_auxiliary(self.root,[[]],16,expected_versions={'engine_hash':'different-version'})
        self.assertTrue(all(s['source']=='simulation' for s in batch))
    def test_rare_source_stochastic_rounding_1000_independent_seeds(self):
        make_episode(self.root,game_key='g0',count=2)
        totals={}
        for weight in (1.,3.):
            used=0
            for seed in range(1000):
                batch=sample_auxiliary(self.root,[[]]*1000,16,2,seed=seed,live_weight=weight)
                live=[s for s in batch if s['source']=='live']
                self.assertLessEqual(len(live),1)  # rare cap floor(16*.10)
                used+=len(live)
            probability=16*weight/(1000+weight)
            expected=1000*probability
            tolerance=4*math.sqrt(1000*probability*(1-probability))+2
            self.assertLessEqual(abs(used-expected),tolerance,(weight,used,expected,tolerance))
            self.assertGreater(used,0)
            totals[weight]=used
        self.assertGreater(totals[3.],totals[1.])
    def test_zero_ratio_and_subslot_sparse_cap_never_sample(self):
        make_episode(self.root,game_key='g0',count=2)
        for seed in range(50):
            for options in ({'live_weight':0.},{'live_cap':0.}):
                batch=sample_auxiliary(self.root,[[]],16,2,seed=seed,**options)
                self.assertTrue(all(s['source']=='simulation' for s in batch))
            # Sparse cap .10, batch9 => hard cap floor(.9)=0 even when
            # prioritized population probability is positive and very high.
            batch=sample_auxiliary(self.root,[[]],9,2,seed=seed)
            self.assertTrue(all(s['source']=='simulation' for s in batch))
    def test_stochastic_rounding_never_breaches_thirty_percent_or_source_cap(self):
        created=0
        for i in range(100):
            key='cap-game-'+str(i)
            if int(hashlib.sha256(key.encode()).hexdigest()[:8],16)%5==0:continue
            make_episode(self.root,'cap-'+str(i),key,count=2);created+=1
            if created==32:break
        for seed in range(10):
            batch=sample_auxiliary(self.root,[[]],16,2,seed=seed)
            live=[s for s in batch if s['source']=='live']
            self.assertEqual(len(live),4)  # floor(16*.30), never rounds to5
            self.assertEqual(len({s['episode_id'] for s in live}),4)
    def test_no_future_label_in_input(self):
        self.assertFalse(input_boundary({'features':[1],'final_rank':1}))
        self.assertFalse(input_boundary({'history':[{'rng':2}]}))


class FakeTransport:
    source='fixture'
    def __init__(self):self.submissions=[];self.changed=False;self.receipt_wrong=False
    def observe(self):return {'features':[0.]*3227,'cards':[0]*124,'action_mask':[1]+[0]*244,'token':'changed' if self.changed else 'stable','window':{'fixture':True},'evidence':{'fixture':True},'confidence':1.,'missing_fields':[],'turn':1,'seat_id':0}
    def guard(self,window):pass
    def plan(self,action,before):return {'no_real_input':True}
    def submit(self,plan,request):self.submissions.append(request)
    def confirm(self,request,timeout,stop):return {'execution':{'confirmed':True,'request_id':request,'executed_action':1 if self.receipt_wrong else 0}}


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'model').write_bytes(b'fixed-fixture')
        self.config={'checkpoint':str(self.root/'model'),'session_root':str(self.root/'session'),'data_root':str(self.root),'emergency_stop_path':str(self.root/'STOP')}
        self.transport=FakeTransport();self.policy=lambda obs,h:(0,1.,0.,'hidden')
    def tearDown(self):self.tmp.cleanup()
    def session(self):return GameSession(self.config,self.transport,self.policy)
    def test_real_preflight_fails_closed(self):
        result=preflight(self.config);self.assertFalse(result['ready']);self.assertEqual(start(self.config)['state'],'blocked')
    def test_successful_preflight_has_reachable_start_and_lease_release(self):
        import bgagent10.live as live
        class TerminalTransport:
            source='fixture'
            def observe(self):return {'terminal':{'reason':'normal','rank':8}}
        class Adapter:
            def create(self,*args):return TerminalTransport()
            def begin(self,config,model_sha):return {'game_key':'fixture-not-real','versions':dict({k:'fixture' for k in VERSION_FIELDS},policy_version=model_sha)}
        class Catalog:
            def __init__(self,*args):pass
            def manifest(self):return {'runtime_ids':['','fixture']}
        class InlineThread:
            def __init__(self,target,**kwargs):self.target=target
            def start(self):self.target()
        # This terminal-only fixture is deliberately not qualified client data.
        # A single session finishes intake; default automatic queuing must pause
        # on that quarantine rather than attempt to start another client game.
        for automatic,expected_state in ((False,'completed'),(True,'paused')):
            with self.subTest(default_auto_queue=automatic):
                config=dict(self.config,client_lease_path=str(self.root/'client.lock'),
                    session_root=str(self.root/('automatic' if automatic else 'single')))
                if not automatic:config['auto_queue']=False
                predict=Mock(side_effect=AssertionError('terminal fixture must not infer or act'))
                modules={'bgagent10.model':types.SimpleNamespace(load_policy=lambda *a:None,predict_public=predict),'bgagent10.encoding':types.SimpleNamespace(CardCatalog=Catalog),'bgagent10.engine':types.SimpleNamespace(DEFAULT_RULES='fixture')}
                with patch.dict(sys.modules,modules),patch.object(live,'preflight',return_value={'ready':True}),patch.dict(live.ADAPTERS,{'native-public-v1':Adapter()}),patch.object(live.threading,'Thread',InlineThread):
                    result=live.start(config)
                self.assertEqual(result['state'],'starting')
                self.assertFalse((self.root/'client.lock').exists())
                status=live.status(config['session_root'])
                self.assertEqual(status['state'],expected_state)
                self.assertEqual(status['intake']['status'],'quarantine')
                predict.assert_not_called()
    def test_commit_before_single_submission(self):
        session=self.session()
        with Journal(self.root) as journal:
            session.journal=journal
            session.decision()
            self.assertEqual([r['kind'] for r in read_events(journal.path)],['decision_commit','decision'])
            self.assertEqual(len(self.transport.submissions),1)
    def test_stale_state_aborts_before_submission(self):
        session=self.session()
        def policy(obs,hidden):self.transport.changed=True;return 0,1.,0.,None
        session.policy=policy
        with Journal(self.root) as j:
            session.journal=j
            with self.assertRaises(RuntimeError):session.decision()
        self.assertFalse(self.transport.submissions)
    def test_emergency_stop_no_input(self):
        session=self.session();(self.root/'STOP').touch()
        with Journal(self.root) as j:
            session.journal=j
            with self.assertRaises(RuntimeError):session.decision()
        self.assertFalse(self.transport.submissions)
    def test_model_mutation_no_input(self):
        session=self.session();(self.root/'model').write_bytes(b'changed')
        with Journal(self.root) as j:
            session.journal=j
            with self.assertRaises(RuntimeError):session.decision()
        self.assertFalse(self.transport.submissions)
    def test_bad_receipt_never_retried(self):
        session=self.session();self.transport.receipt_wrong=True
        with Journal(self.root) as j:
            session.journal=j
            with self.assertRaises(RuntimeError):session.decision()
        self.assertEqual(len(self.transport.submissions),1)


if __name__=='__main__':unittest.main()
