"""One read-only policy exhibition, isolated from training and live clients."""
from pathlib import Path
import argparse, hashlib, json, os, random, secrets, shutil, sys, time, traceback

from .atomic_io import atomic_json
from .service import launch_lock, process_identity, read_json, TrainingService


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReorderGuard:
    """Stop an exhibition, never alter the model's chosen/legal action."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.count=0; self.seen={}; self.turn=None

    def observe(self, observation, action):
        turn=observation['features'][0]
        if not 196<=action<245:
            self.reset(); return None
        if turn!=self.turn:
            self.reset(); self.turn=turn
        self.count+=1
        # Includes every public feature/card/mask, not merely card names.
        key=hashlib.sha256(json.dumps(observation,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.seen[key]=self.seen.get(key,0)+1
        reason=None
        if self.count>=12 and self.seen[key]>=3:reason='repeated_public_state'
        elif self.count>=32:reason='consecutive_reorder_limit'
        if reason:
            return dict(reason=reason,consecutive_reorders=self.count,
                        repeated_public_state_count=self.seen[key],action_not_executed=action)
        return None


class SimulationService:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.root = self.project / 'data/simulations'
        self.root.mkdir(parents=True, exist_ok=True)

    def sessions(self):
        return sorted((p for p in self.root.iterdir() if p.is_dir() and (p/'status.json').exists()), reverse=True)

    def snapshot(self, session):
        status = read_json(session/'status.json', {})
        child = read_json(session/'process.json', {})
        identity = child.get('identity')
        alive = bool(identity and process_identity(child['pid']) == identity)
        if status.get('state') in ('starting', 'running') and not alive:
            status = dict(status, state='failed', message='模拟进程已退出；请打开记录查看 process.log，未计作完整对局。')
        return dict(status, process_alive=alive)

    def training_runs(self):
        return sorted((p for p in (self.project/'data/runs').iterdir() if p.is_dir() and (p/'config.json').is_file() and not p.name.startswith('engineering-')),reverse=True)

    def latest(self, run=None):
        candidates = []
        runs=[Path(run).resolve()] if run is not None else self.training_runs()
        for source_run in runs:
            if not (source_run/'config.json').is_file():raise ValueError('所选训练记录不存在')
            candidates.extend((p.stat().st_mtime_ns, str(p), source_run) for p in (source_run/'checkpoints').glob('step-*.pt') if p.is_file())
        if not candidates:
            raise ValueError('这条训练记录还没有已保存的模型，请等它保存第一个检查点；不会替换为旧记录。')
        _, path, run = max(candidates)
        return Path(path), run

    def resolve_model(self, source='running', run=None, checkpoint=None):
        if source=='running':
            active=TrainingService(self.project/'data/runs').active_runs()
            if len(active)!=1:
                raise ValueError('没有唯一正在运行的训练任务，请在“指定训练记录”中选择要测试的记录。')
            return self.latest(active[0])
        if source=='run':
            if not run:raise ValueError('请先选择训练记录')
            return self.latest(run)
        if source=='checkpoint':
            p=Path(checkpoint or '').resolve()
            if not p.is_file() or p.suffix.lower()!='.pt':raise ValueError('请选择已保存的 .pt 模型文件')
            owner=p.parent.parent if p.parent.name=='checkpoints' and (p.parent.parent/'config.json').is_file() else None
            return p,owner
        if source=='latest':return self.latest()
        raise ValueError('未知模型来源')

    def start(self, seed=None, deterministic=False, *, source='running', run=None, checkpoint=None):
        import subprocess
        with launch_lock(self.root/'.launch.lock'):
            if any(self.snapshot(p)['process_alive'] for p in self.sessions()):
                raise ValueError('已有模拟正在运行，请等待完成或停止后再开始。')
            checkpoint, run = self.resolve_model(source,run,checkpoint)
            seed = secrets.randbelow(2**31) if seed is None else int(seed)
            if not 0 <= seed < 2**31:
                raise ValueError('开局种子须在 0～2147483647；留空则随机开局。')
            session = self.root/(time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
            session.mkdir()
            atomic_json(session/'request.json', dict(checkpoint=str(checkpoint), source_run=str(run) if run else None, model_source=source, seed=seed, deterministic=bool(deterministic)))
            atomic_json(session/'status.json', dict(state='starting', message='正在读取所选模型：'+checkpoint.name))
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
            try:
                with (session/'process.log').open('ab', buffering=0) as log:
                    proc = subprocess.Popen([sys.executable, '-B', '-m', 'bgagent10.simulation', '--project', str(self.project), '--session', str(session)], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                atomic_json(session/'process.json', dict(pid=proc.pid, identity=process_identity(proc.pid)))
            except Exception as exc:
                atomic_json(session/'status.json', dict(state='failed', message='无法启动模拟：'+str(exc)))
                raise
            return session

    def stop(self, session):
        if self.snapshot(session)['process_alive']:
            atomic_json(session/'control.json', {'command':'stop'})


def view(obs, cards):
    """Presentation only: decode the same public numeric contract as the policy."""
    f, ids = obs['features'], obs['cards']
    def card(index):
        if not ids[index]: return None
        return cards[ids[index]-1]
    def name(index):
        c = card(index)
        return (c.get('name_zh') or c.get('name') or c['id']) if c else '空'
    def zone(start, offset, count, width, header=0):
        result=[]
        for i in range(count):
            c=card(start+i); base=offset+i*width
            if not f[base]: continue
            row={'slot':i+1,'name':name(start+i),'id':c['id'] if c else '', 'text':(c.get('text_zh') or c.get('text','')) if c else ''}
            if width==31 or f[base+1]:
                row.update(attack=round(f[base+header+1]*10), health=round(f[base+header+2]*10), golden=bool(f[base+header+5]))
            if header: row['cost']=round(f[base+2]*5)
            result.append(row)
        return result
    return dict(turn=round(f[0]*20), hero=name(0), health=round(f[5]*40), armor=round(f[6]*20), gold=round(f[7]*10), tier=round(f[10]*6), alive_count=round(f[3]*8),
                board=zone(19,68,7,31),hand=zone(26,285,10,40,9),shop=zone(36,685,8,40,9),choices=zone(44,1005,16,40,9))


def action_text(index, state):
    from .live_encoding import decode_action
    a=decode_action(index); kind=a['type']
    def name(zone,slot):
        return next((x['name'] for x in state[zone] if x['slot']==slot+1),f'位置{slot+1}')
    if kind=='buy': return '购买 '+name('shop',a['shop'])
    if kind=='sell': return '出售 '+name('board',a['board'])
    if kind=='choice': return '选择 '+name('choices',a['option'])
    if kind=='activate': return '激活 '+name('board',a['board'])
    if kind=='play': return f"打出 {name('hand',a['hand'])} → 位置{a['position']+1}"
    if kind=='magnetize': return f"磁力 {name('hand',a['hand'])} → {name('board',a['board'])}"
    if kind=='reorder': return f"移动 {name('board',a['board'])} → 位置{a['position']+1}"
    return {'end':'结束回合','refresh':'刷新酒馆','freeze':'切换冻结','upgrade':'升级酒馆','hero_power':'使用英雄技能','dark_gift':'购买黑暗之赐','cancel':'取消选择'}.get(kind,kind)


def run(project, session):
    import torch
    from .engine import EnvironmentProcess, public_input
    from .encoding import CardCatalog
    from .model import build_checkpoint_model, observation_tensors
    from .opponents import FrozenPool, heuristic_action
    from .training_recovery import prepare_config
    from .policy_recovery import prepare_policy_config
    from .simulation_policy import ExhibitionPolicy, VERSION as decoder_version
    project,session=Path(project),Path(session)
    driver=None; decisions=0; learner_steps=0; obs=None
    try:
        request=read_json(session/'request.json'); seed=request['seed']
        config=read_json(Path(request['source_run'])/'config.json') if request.get('source_run') else torch.load(request['checkpoint'],map_location='cpu',weights_only=False)['config'].copy()
        config['resume_from']=request['checkpoint']
        config,rr=prepare_config(config,project);config,pr=prepare_policy_config(config,project)
        source=Path(config['resume_from']); before=sha(source)
        frozen=session/'model.pt';shutil.copyfile(source,frozen)
        if sha(frozen)!=before or sha(source)!=before: raise ValueError('模型保存期间发生变化，请重新模拟。')
        torch.set_num_threads(2);torch.manual_seed(seed)
        catalog=CardCatalog(config['rules_path']);driver=EnvironmentProcess(config['rules_path'])
        saved=torch.load(frozen,map_location='cpu',weights_only=False)
        model=build_checkpoint_model(saved,catalog,driver.metadata,device='cpu');model.eval();model.requires_grad_(False)
        mode=config.get('eval_opponent','mixed')
        pool=FrozenPool(mode,config.get('eval_opponent_pool'),catalog,driver.metadata['binding'],driver.metadata['layout'],'cpu')
        assignments=pool.assignments(seed,evaluation=True);learner=assignments.index('learner')
        cards=json.loads((Path(config['rules_path'])/'source/crates/taverngym/data/cards.json').read_text('utf8'))['cards']
        manifest=dict(format='bgagent10-offline-exhibition-v1',request=request,checkpoint=str(source),model_sha256=before,actor_version=model.actor_version,model_counters=saved['counters'],rules_path=config['rules_path'],binding=driver.metadata['binding'],opponents=pool.manifest,opponent_pool_hash=pool.manifest_hash,assignments=assignments,learner_seat=learner,rule_recovery=rr,policy_recovery=pr,training_data=False,strength_certification=False)
        manifest['exhibition_decoder']=decoder_version
        manifest['assisted_decisions']=True
        manifest['decoder_scope']='learner_only'
        manifest['decoder_limits']=dict(unchanged_board_moves='n-1',turn_action_threshold=128,end_only_when_legal=True)
        atomic_json(session/'manifest.json',manifest)
        obs=driver.request('reset',seed=seed);hidden={};states={};rng=random.Random(seed);last=0;decoder=ExhibitionPolicy()
        with (session/'actions.jsonl').open('w',encoding='utf8') as actions, (session/'replay.jsonl').open('w',encoding='utf8') as replay:
            while not obs['diagnostics']['done']:
                if read_json(session/'control.json',{}).get('command')=='stop':
                    atomic_json(session/'status.json',dict(state='stopped',message='已停止模拟；不计作完整对局。',decisions=decisions,learner_steps=learner_steps));return
                if decisions>=int(config.get('max_decisions',30000)):raise RuntimeError('模拟达到动作保护上限，未产生正常终局。')
                seat=obs['current_seat']
                if seat is None or obs['seat']!=seat:raise ValueError('公开行动座位不一致')
                identity=assignments[seat];pred=None;decision_info=None;decision_ticket=None
                if identity!='learner' and pool.entry(identity)['kind']=='scripted':
                    action=heuristic_action(obs,rng,pool.entry(identity)['style'],states.setdefault(seat,{}))
                else:
                    actor=model if identity=='learner' else pool.models[identity]
                    with torch.inference_mode():
                        logits,value,new_hidden,_=actor(*observation_tensors([public_input(obs)],'cpu'),hidden.get(seat))
                        dist=torch.distributions.Categorical(logits=logits)
                        if identity=='learner':
                            action,decision_info,decision_ticket=decoder.choose(logits,public_input(obs),request['deterministic'])
                        else:action=int(dist.sample().item())
                        pred=dist.probs[0].tolist();hidden[seat]=new_hidden.detach()
                if not obs['action_mask'][action]:raise ValueError('模型输出非法动作；未替换')
                row=None
                if identity=='learner':
                    public=public_input(obs)
                    state=view(obs,cards);learner_steps+=1
                    top=sorted((i for i,v in enumerate(obs['action_mask']) if v),key=lambda i:pred[i],reverse=True)[:3]
                    row=dict(step=learner_steps,decision=decisions+1,seat=seat,action=action,action_text=action_text(action,state),probability=pred[action],top_actions=[{'text':action_text(i,state),'probability':pred[i]} for i in top],view=state,observation=public_input(obs))
                    row['decision_policy']=decision_info
                    if action>=196 and decision_info.get('formation_phase')=='fixed_plan':
                        row['action_text']=f"回合末固定排阵 {decision_info['formation_plan_index']+1}/{decision_info['formation_plan_steps']}："+row['action_text']
                    row['raw_preferred_action_text']=action_text(decision_info['raw_preferred_action'],state)
                # Only commit a replay action after the authoritative step succeeds.
                next_obs=driver.request('step',index=action);decisions+=1
                if decision_ticket is not None:decoder.commit(decision_ticket)
                actions.write(json.dumps(dict(decision=decisions,seat=seat,actor=identity,action=action,decision_policy=decision_info))+'\n');actions.flush()
                if row:
                    replay.write(json.dumps(row,ensure_ascii=False)+'\n');replay.flush()
                obs=next_obs
                if time.monotonic()-last>.4:
                    atomic_json(session/'status.json',dict(state='running',message=f'模拟进行中；防循环/动作预算辅助已调整原始首选 {decoder.interventions} 次。',decisions=decisions,learner_steps=learner_steps,learner_seat=learner,turn=round(obs['features'][0]*20)))
                    last=time.monotonic()
        diag=obs['diagnostics'];ranks=diag.get('placements')
        if not diag['terminated'] or diag['truncated'] or diag['stop_reason']!='normal_elimination' or not ranks or sorted(ranks)!=list(range(1,9)):
            raise ValueError('模拟未正常结束：'+json.dumps(diag))
        atomic_json(session/'result.json',dict(completed=True,rank=ranks[learner],placements=ranks,learner_seat=learner,seed=seed,decisions=decisions,learner_steps=learner_steps,terminal_reason=diag['stop_reason'],model_sha256=before,opponent_pool_hash=pool.manifest_hash,strength_certification=False,exhibition_decoder=decoder_version,assisted_decisions=True,preferred_action_interventions=decoder.interventions))
        atomic_json(session/'status.json',dict(state='completed',message=f'防循环模拟完成：第 {ranks[learner]} 名，辅助调整原始首选 {decoder.interventions} 次。结果包含决策辅助，不是裸模型棋力认证。',rank=ranks[learner],decisions=decisions,learner_steps=learner_steps))
    except Exception as exc:
        error=dict(message=str(exc),traceback=traceback.format_exc(),decisions=decisions,learner_steps=learner_steps,whole_lobby_quarantined=True)
        if driver:
            try:driver.request('dump_debug',path=str(session/'errors/private-snapshot.json'))
            except Exception as debug:error['snapshot_error']=str(debug)
        (session/'errors').mkdir(exist_ok=True);atomic_json(session/'errors/error.json',error)
        atomic_json(session/'status.json',dict(state='failed',message='模拟异常，整局已隔离：'+str(exc),error_report=str(session/'errors/error.json')))
        raise
    finally:
        if driver:driver.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--project',required=True);parser.add_argument('--session',required=True);args=parser.parse_args()
    run(args.project,args.session)
