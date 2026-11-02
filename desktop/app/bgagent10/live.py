"""Version-bound native play with model freezing, transaction proofs and journaling."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
import math
import traceback
from .live_data import digest
from .live_data import Journal, atomic, immutable, ingest
from .live_encoding import GLOBAL_NAMES, decode_action, map_options
from .live_producer import installed_build
from .live_adapter import NativePublicAdapter

MODEL_TARGET_BUILD='37.0.0.255130'
CLIENT_TARGET_BUILD='37.0.0.255790'
TARGET_BUILD=MODEL_TARGET_BUILD
ADAPTERS={'native-public-v1':NativePublicAdapter()}
_SESSIONS={}


def configuration(config):
    config=dict(config)
    config.setdefault('session_root',str(Path(config.get('data_root','.'))/'session'))
    config.setdefault('client_lease_path',str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BGagent10/client-control.lock'))
    config.setdefault('model_rules_target',MODEL_TARGET_BUILD)
    config.setdefault('client_target',CLIENT_TARGET_BUILD)
    config.setdefault('auto_queue',True)
    config.setdefault('max_games',100 if config['auto_queue'] else 1)
    if not config['auto_queue']:config['max_games']=1
    config['expected_build']=config['client_target']
    return config


def deployment_contract(config):
    """Explicitly approve a cross-client mapping, never relabel the model rules."""
    manifest=load(config['deployment_contract_path'])
    if manifest.get('format')!='bgagent10-deployment-v1':raise ValueError('部署契约格式无效')
    for key,expected in [('model_rules_target',MODEL_TARGET_BUILD),('client_target',config['client_target']),('checkpoint_sha256',sha(config['checkpoint']))]:
        if manifest.get(key)!=expected:raise ValueError('部署契约不匹配：'+key)
    proof=Path(manifest['mapping_validation_path'])
    if sha(proof)!=manifest.get('mapping_validation_sha256'):raise ValueError('跨版本映射验收报告SHA不匹配')
    report=load(proof)
    if report.get('state') not in {'passed','ready_for_user_acceptance'} or report.get('model_rules_target')!=MODEL_TARGET_BUILD or report.get('client_target')!=config['client_target']:raise ValueError('跨版本映射报告未就绪')
    if report.get('state')=='ready_for_user_acceptance' and report.get('runtime_observation_must_be_complete') is not True:raise ValueError('手动验收部署缺少完整观察保护')
    if report.get('unresolved_required_fields'):raise ValueError('仍有未解决的必需公开字段')
    if manifest.get('commander_approved') is not True:raise ValueError('部署契约未获指挥放行')
    return {'manifest':manifest,'report':report,'manifest_sha256':sha(config['deployment_contract_path'])}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def record_failure(root, exc, **details):
    path=Path(root)/'errors'/f'{uuid.uuid4().hex}.json'
    result={'state':'failed','error_type':type(exc).__name__,'message':str(exc),
        'traceback':traceback.format_exc(),'error_report':str(path),'new_live_games':0,**details}
    immutable(path,result);atomic(Path(root)/'status.json',result)
    return result


def passive_log_report(path):
    """Bounded passive byte inspection; neither seeks a live tail nor creates log config."""
    path=Path(path)
    with path.open('rb') as stream:
        size=path.stat().st_size;stream.seek(max(0,size-1024*1024));raw=stream.read(1024*1024)
    text=raw.decode('utf-8',errors='replace')
    return {'path':str(path.resolve()),'size':size,'sample_bytes':len(raw),'sample_sha256':hashlib.sha256(raw).hexdigest(),'create_game_seen':'CREATE_GAME' in text,'options_seen':'DebugPrintOptions' in text,'choices_seen':'DebugPrintEntityChoices' in text,'receipt_seen':'SendOption()' in text,'mtime':path.stat().st_mtime,'complete_observation_proven':False,'missing_field_groups':['native normalized global counters: '+', '.join(GLOBAL_NAMES),'complete card collections, equipped trinkets, quests/rewards/secrets','hand locked/temporary/combined/doomed/group, shop frozen/kept/ticket','attached_count, shield_hits, full keyword/race bitsets','seat-stable opponent summaries and last-seen warbands','server pending Target/Choose continuation and option order'],'note':'Presence of lines proves no field completeness, observer identity, current build, or server state.'}


def preflight(config):
    config=configuration(config)
    checks=[]
    def check(name,ok,detail):checks.append({'name':name,'ok':bool(ok),'detail':detail})
    expected=config['client_target']
    check('target_build',config['model_rules_target']==MODEL_TARGET_BUILD,{'model_rules_target':config['model_rules_target'],'required':MODEL_TARGET_BUILD,'model_load':'strict frozen255130; no checkpoint relabelling'})
    check('client_target',expected==CLIENT_TARGET_BUILD,{'requested':expected,'approved_route':CLIENT_TARGET_BUILD,'rule_target_unchanged':MODEL_TARGET_BUILD})
    checkpoint=Path(config.get('checkpoint',''))
    check('checkpoint',checkpoint.is_file(),'固定整局模型：'+str(checkpoint))
    try:deployment=deployment_contract(config);check('deployment_contract',True,deployment)
    except Exception as exc:check('deployment_contract',False,str(exc))
    client=Path(config.get('client_path',''))
    actual=None
    version=installed_build(client) if client.is_file() else {'build':None,'reason':'client executable unavailable'}
    actual=version.get('build')
    check('client_build',actual==expected,{'actual':actual,'expected':expected,'client_path':str(client),'evidence':version})
    log=Path(config.get('log_path',''))
    check('log_available',log.is_file() or config.get('auto_queue') and log.parent.is_dir(),{'Power_log_exists':log.is_file(),'queue_may_wait_for_new_CREATE_GAME':bool(config.get('auto_queue')),'path':str(log)})
    calibration=None
    try:calibration=load(config['calibration_path'])
    except (KeyError,OSError,ValueError):pass
    check('window_calibration',calibration and calibration.get('build')==expected and calibration.get('window_title')==config.get('window_title') and calibration.get('size') and calibration.get('points'),'需当前窗口内坐标、分辨率、构建和目标窗口标题绑定；每次输入重新核对')
    stop_path=config.get('emergency_stop_path')
    check('emergency_stop',stop_path and not Path(stop_path).exists(),'紧停文件必须已配置且未触发；窗口失焦/变化也停止')
    manifest=None
    try:manifest=load(config['adapter_manifest'])
    except (KeyError,OSError,ValueError):pass
    adapter=ADAPTERS.get((manifest or {}).get('adapter_id','native-public-v1'))
    check('public_mapping_adapter',adapter is not None,'注册原生公开状态与分步245动作适配；具体字段与菜单按证据逐项检查')
    check('real_adapter',adapter and getattr(adapter,'source',None)=='real-client','模拟传输不能成为真实验收')
    check('exclusive_client',not Path(config['client_lease_path']).exists(),{'lease':config['client_lease_path'],'note':'只检查可获取；start使用排他创建取得租约，决不抢占/自动删旧租约'})
    release=None
    try:release=load(config['release_path'])
    except (KeyError,OSError,ValueError):pass
    check('commander_release',release and release.get('live_released') is True and checkpoint.is_file() and release.get('checkpoint_sha256')==sha(checkpoint),'需指挥登记训练放行和当前模型SHA；不因存在旧授权自动点击')
    entry_mode='current_game'
    if adapter:
        try:
            queue=None
            if config.get('auto_queue') and isinstance(adapter,NativePublicAdapter):
                try:queue=adapter.probe_queue(config)
                except Exception:pass
            if queue:
                checks.append(queue);entry_mode='queue'
            else:
                for item in adapter.probe(config):checks.append(item)
        except Exception as exc:check('adapter_probe',False,str(exc))
    ready=all(c['ok'] for c in checks)
    return {'state':'ready' if ready else 'blocked','ready':ready,'ok':ready,'entry_mode':entry_mode,'checks':checks,'blockers':[c for c in checks if not c['ok']],'client_started':False,'new_live_games':0,'log_report':passive_log_report(log) if log.is_file() else None,'known_scope':'accepted fixed named target37 working contracts; no reopened rules gate'}


def status(session_root):
    try:return load(Path(session_root)/'status.json')
    except (OSError,ValueError):return {'state':'idle','message':'尚无实战会话','new_live_games':0}


def start(config):
    config=configuration(config)
    report=preflight(config)
    root=Path(config.get('session_root',Path(config.get('data_root','.'))/'session'))
    atomic(root/'preflight.json',report)
    if not report['ready']:
        result={'state':'blocked','message':'实战预检未通过，未发送客户端输入','preflight':report,'new_live_games':0}
        atomic(root/'status.json',result);return result
    lease=None
    try:
        lease=ExclusiveLease(config['client_lease_path']);lease.__enter__()
        # Clear a previous normal stop only after every preflight and exclusivity
        # check passed. Emergency signal is never silently cleared.
        (root/'control.json').unlink(missing_ok=True)
        from .model import load_policy,predict_public
        from .encoding import CardCatalog
        from .engine import DEFAULT_RULES
        frozen_sha=sha(config['checkpoint'])
        model=load_policy(config['checkpoint'],config.get('device','cpu'),config.get('rules_path'))
        if sha(config['checkpoint'])!=frozen_sha:raise RuntimeError('加载模型期间文件变化，拒绝局内版本不一致')
        catalog=CardCatalog(config.get('rules_path') or DEFAULT_RULES)
        mapping={cid:i-1 for i,cid in enumerate(catalog.manifest()['runtime_ids']) if i and cid}
        adapter_id=load(config['adapter_manifest']).get('adapter_id') if config.get('adapter_manifest') else 'native-public-v1'
        adapter=ADAPTERS[adapter_id]
        transport=adapter.create(config,mapping)
        def policy(observation,hidden):
            deterministic=config.get('deterministic',False)
            prediction=predict_public(model,observation,hidden,deterministic)
            probability=1. if deterministic else math.exp(prediction['log_prob'])
            return prediction['action'],probability,prediction['value'],prediction['hidden']
        session=GameSession(config,transport,policy);transport.stop_event=session.stop_event
        begin=None if report.get('entry_mode')=='queue' else adapter.begin(config,session.model_sha,transport=transport) if isinstance(adapter,NativePublicAdapter) else adapter.begin(config,session.model_sha)
        result={'state':'starting','message':'预检通过，已取得客户端租约并冻结本局模型','model_sha256':session.model_sha,'new_live_games':0}
        atomic(root/'status.json',result)
        def runner():
            try:
                game_begin=begin
                if game_begin is None:
                    from .live_controller import QueueController
                    from .live_producer import PublicLogProducer
                    queue=QueueController(config,transport.native,session.stop_event,PublicLogProducer)
                    old=queue._snapshot(transport.native.locate()).get('game_key')
                    atomic(root/'status.json',{'state':'queueing','message':'识别排队菜单，等待当前客户端新局日志'})
                    queue.queue_match(old,config.get('queue_timeout',180))
                    game_begin=adapter.begin(config,session.model_sha,transport=transport)
                if config.get('auto_queue') or int(config.get('max_games',1))>1:
                    from .live_controller import run_series
                    run_series(config,adapter,policy,mapping,game_begin,session,lease)
                else:session.run(game_begin,external_lease=lease)
            except Exception as exc:
                record_failure(root,exc,stage='queue_or_series',model_sha256=session.model_sha)
                if lease.path.exists():lease.__exit__()
            finally:_SESSIONS.pop(str(root.resolve()),None)
        thread=threading.Thread(target=runner,name='bgagent10-live',daemon=True)
        _SESSIONS[str(root.resolve())]=(session,thread);thread.start();return result
    except Exception as exc:
        if lease is not None:
            try:lease.__exit__()
            except FileNotFoundError:pass
        return record_failure(root,exc,stage='start')


def stop(session_root):
    root=Path(session_root);atomic(root/'control.json',{'command':'stop','time_ns':time.time_ns()})
    active=_SESSIONS.get(str(root.resolve()))
    if active:active[0].stop_event.set()
    result=status(root)
    if result.get('state') in ('starting','running','waiting_receipt'):result.update(state='stopping',message='等待安全停止，禁止继续输入')
    else:result.update(message='已登记停止；当前没有执行中的客户端输入')
    atomic(root/'status.json',result);return result


class ExclusiveLease:
    def __init__(self,path):self.path=Path(path);self.token=uuid.uuid4().hex
    def __enter__(self):
        immutable(self.path,{'pid':os.getpid(),'token':self.token,'time_ns':time.time_ns()});return self
    def __exit__(self,*_):
        if load(self.path).get('token')==self.token:self.path.unlink()


class GameSession:
    """Transport protocol: observe(), guard(window), plan(index,observation),
    submit(plan,request_id), confirm(request_id,timeout,stop_event).
    observe returns encoded public observation plus token/window/evidence,
    features/cards/action_mask and public history; private metadata is stripped
    before inference. confirm returns execution/after/battle_result and evidence.
    Native implementation requires calibrated menu cues and current public facts.
    """
    def __init__(self,config,transport,policy):
        self.config=config;self.transport=transport;self.policy=policy;self.stop_event=threading.Event()
        self.checkpoint=Path(config['checkpoint']);self.model_sha=sha(self.checkpoint)
        self.journal=None;self.hidden=None
    def check_stop(self):
        control=Path(self.config['session_root'])/'control.json'
        emergency=Path(self.config['emergency_stop_path'])
        if self.stop_event.is_set() or emergency.exists() or (control.exists() and load(control).get('command')=='stop'):raise RuntimeError('紧停已触发')
        if sha(self.checkpoint)!=self.model_sha:raise RuntimeError('局内模型文件变化，停止并隔离')
    def decision(self):
        if self.journal is None:raise RuntimeError('必须先建立对局原始记录')
        self.check_stop();before=self.transport.observe();self.transport.guard(before['window'])
        public={k:before[k] for k in ('features','cards','action_mask')}
        if tuple(map(len,(public['features'],public['cards'],public['action_mask'])))!=(3227,124,245):raise ValueError('公开观察编码尺寸不匹配')
        if before.get('missing_fields') or before.get('confidence')!=1:raise ValueError('公开观察缺失，禁止推理/执行')
        action,probability,value,new_hidden=self.policy(public,self.hidden)
        if type(action)!=int or action not in range(245) or not public['action_mask'][action]:raise ValueError('模型返回非法动作，不替换兜底')
        plan=self.transport.plan(action,before);request=uuid.uuid4().hex
        commit={'request_id':request,'observation':public,'action':action,'semantic':decode_action(action),'behavior_probability':probability,'value_prediction':value,'before_evidence':before['evidence'],'model_sha256':self.model_sha,'plan':plan}
        self.journal.append('decision_commit',commit)  # fsync BEFORE any client input
        self.check_stop();fresh=self.transport.observe()
        if fresh['token']!=before['token']:raise RuntimeError('输入前状态变化，已撤销；不盲重试')
        self.transport.guard(before['window']);self.check_stop()
        self.transport.submit(plan,request)  # exactly one submission, never retries
        self.check_stop()
        result=self.transport.confirm(request,8.,self.stop_event)
        if result.get('cancelled') and result.get('safe_to_replan'):
            self.journal.append('decision_aborted',{'request_id':request,'reason':'window_recovered_cancelled_before_commit','recovery':result.get('recovery')})
            return None  # Do not advance GRU memory for an unexecuted proposal.
        execution=result.get('execution',{})
        if not execution.get('confirmed') or execution.get('request_id')!=request or execution.get('executed_action')!=action:raise RuntimeError('执行回执不一致或超时，停止且保留待复核操作')
        self.hidden=new_hidden
        record={'turn':before['turn'],'seat_id':before['seat_id'],'observation':public,'history':before.get('history',[]),'missing_fields':[],'confidence':1.,'legal_actions':[i for i,m in enumerate(public['action_mask']) if m],'suggested_action':action,'executed_action':action,'execution':execution,'behavior_probability':probability,'value_prediction':value,'after':result.get('after'),'battle_result':result.get('battle_result'),'flags':result.get('flags',[])}
        if probability is None:record['probability_unknown_reason']=result.get('probability_unknown_reason','policy did not expose exact behavior probability')
        self.journal.append('decision',record);return record
    def run(self,begin,max_decisions=10000,external_lease=None,release_external=True):
        root=Path(self.config['session_root']);data_root=self.config['data_root']
        try:
            from contextlib import nullcontext
            with (nullcontext(external_lease) if external_lease else ExclusiveLease(self.config['client_lease_path'])),Journal(data_root) as journal:
                self.journal=journal;begin=dict(begin,source=self.transport.source)
                if hasattr(self.transport,'journal'):self.transport.journal=journal
                if begin['versions']['policy_version']!=self.model_sha:raise ValueError('冻结策略版本不匹配')
                journal.append('begin',begin)
                # Freeze bytes for forensic recovery, policy object must have loaded
                # exactly these bytes. Never reload latest policy mid-game.
                snapshot=journal.path/'policy.sha256.json';immutable(snapshot,{'sha256':self.model_sha,'checkpoint':str(self.checkpoint.resolve())})
                for _ in range(max_decisions):
                    atomic(root/'status.json',{'state':'running','episode_id':journal.episode_id,'model_sha256':self.model_sha,'events':journal.sequence})
                    self.check_stop();terminal=self.transport.observe().get('terminal')
                    if terminal:
                        journal.append('terminal',terminal);break
                    self.decision()
                else:raise RuntimeError('无进展/动作上限，保护停止不编造名次')
            receipt=ingest(data_root,self.journal.episode_id,self.config.get('expected_versions'))
            atomic(root/'status.json',{'state':'completed','intake':receipt});return receipt
        except Exception as exc:
            from .live_adaptive import LayoutUnavailable,ActionUncertain
            state='paused' if isinstance(exc,(LayoutUnavailable,ActionUncertain)) else 'failed'
            report=record_failure(root,exc,state=state,stage='model_game',episode_id=self.journal.episode_id if self.journal else None,client_input_retried=False,model_sha256=self.model_sha)
            if self.journal:ingest(data_root,self.journal.episode_id,self.config.get('expected_versions'))
            return report
        finally:
            self.hidden=None;self.journal=None
            if external_lease and release_external:external_lease.__exit__()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['preflight','start','stop','status']);parser.add_argument('--config');parser.add_argument('--session-root')
    args=parser.parse_args();config=load(args.config) if args.config else {}
    result={'preflight':lambda:preflight(config),'start':lambda:start(config),'stop':lambda:stop(args.session_root or config['session_root']),'status':lambda:status(args.session_root or config['session_root'])}[args.command]()
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
