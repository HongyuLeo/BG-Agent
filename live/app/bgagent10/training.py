"""Synchronous complete-lobby recurrent PPO and independent evaluation.

Workers execute the exact sealed environment in independent processes. Batched
inference runs in the learner; no stale replay enters the on-policy objective.
"""
import argparse, concurrent.futures, json, math, os, random, statistics, sys, time, traceback
from pathlib import Path
import torch
from torch.distributions import Categorical
from .engine import DEFAULT_RULES, EnvironmentProcess, public_input
from .encoding import CardCatalog, digest
from .model import PolicyModel, observation_tensors
from .opponents import FrozenPool,heuristic_action,policy_fingerprint

DEFAULT_CONFIG = dict(workers=2,rounds=1,games_per_round=2,eval_every_games=10,eval_games=2,
    eval_opponent='scripted',learning_rate=1e-4,ppo_epochs=2,model_preset='small',device='cpu',seed=97,
    resume_from=None,gamma=1.,gae_lambda=.995,ppo_clip=.2,sequence_length=32,burn_in=8,
    max_decisions=30000,max_grad_norm=.5,target_kl=.03,entropy_coefficient=.01,
    value_coefficient=.5,placement_coefficient=.05,torch_threads=4,
    live_data_root=None,auxiliary_batch_size=16,auxiliary_updates=0,auxiliary_sequence_length=16,
    train_opponents='selfplay',train_opponent_pool=None,eval_opponent_pool=None)

def atomic_json(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp-'+str(os.getpid()))
    with temp.open('w',encoding='utf8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False); f.flush(); os.fsync(f.fileno())
    os.replace(temp,path)

def append_json(path,value):
    with Path(path).open('a',encoding='utf8') as f:
        f.write(json.dumps(dict(time=time.time(),**value),ensure_ascii=False,allow_nan=False)+'\n'); f.flush()

def utility(rank):
    if not 1<=rank<=8: raise ValueError('invalid terminal rank')
    return (9-2*rank)/7

def advantages(values,rank,gamma=1.,lam=.995):
    # One per-seat trajectory, ending only at a validated normal game terminal.
    returns=[]; adv=0.; next_value=0.
    for i in reversed(range(len(values))):
        reward=utility(rank) if i==len(values)-1 else 0.
        delta=reward+gamma*next_value-values[i]
        adv=delta+gamma*lam*adv
        returns.append((adv,adv+values[i])); next_value=values[i]
    return list(reversed(returns))

def scripted_action(obs,rng,kind='scripted'):
    legal=[i for i,v in enumerate(obs['action_mask']) if v]
    if not legal: raise ValueError('script called without legal action')
    if kind=='random': return rng.choice(legal)
    # Deliberately labelled basic baseline, all decisions use public numeric state.
    for lo,hi in ((30,46),(46,126),(8,16)):
        options=[i for i in legal if lo<=i<hi]
        if options: return rng.choice(options)
    if 3 in legal and obs['features'][0]*20%3<1: return 3
    if 0 in legal: return 0
    return rng.choice(legal)

class Collector:
    def __init__(self,config,catalog):
        self.config=config; self.catalog=catalog
        self.workers=[]
        try:
            for _ in range(config['workers']): self.workers.append(EnvironmentProcess(config['rules_path']))
            self.metadata=self.workers[0].metadata
            for worker in self.workers:
                if worker.metadata['binding']!=self.metadata['binding']: raise ValueError('worker binding mismatch')
            if self.metadata['binding']['card_table_file_SHA']!=catalog.source_sha: raise ValueError('card table bytes mismatch')
            self.train_pool=FrozenPool(config['train_opponents'],config['train_opponent_pool'],catalog,self.metadata['binding'],self.metadata['layout'],config['device'])
            self.eval_pool=FrozenPool(config['eval_opponent'],config['eval_opponent_pool'],catalog,self.metadata['binding'],self.metadata['layout'],config['device'])
            self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=len(self.workers))
        except BaseException:
            for worker in self.workers: worker.close()
            raise
    def close(self):
        for worker in self.workers: worker.close()
        self.pool.shutdown(wait=True,cancel_futures=True)

    def collect(self,model,seeds,evaluation=False,error_dir=None,progress=None):
        model.eval(); device=next(model.parameters()).device
        opponent_pool=self.eval_pool if evaluation else self.train_pool
        learner_version=policy_fingerprint(model)
        waiting=iter(seeds); active={}; completed=[]; failures=[]; last_progress=0
        def start(i,seed):
            obs=self.workers[i].request('reset',seed=seed)
            active[i]=dict(obs=obs,episode_id=obs.get('episode_id'),seed=seed,trajectories=[[] for _ in range(8)],hidden={},count=0,
                rng=random.Random(seed),learner_seat=seed%8,assignments=opponent_pool.assignments(seed,evaluation),heuristic_states={})
        def fail(i,exc):
            state=active.pop(i)
            failure=dict(seed=state['seed'],decisions=state['count'],error=str(exc),
                traceback=traceback.format_exc(),terminal_reason='quarantined_whole_lobby',worker_pid=self.workers[i].metadata['pid'])
            failures.append(failure)
            if error_dir:
                try: self.workers[i].request('dump_debug',path=str(Path(error_dir)/('private-'+str(state['seed'])+'.json')))
                except Exception as debug_error: failure['debug_capture_error']=str(debug_error)
                atomic_json(Path(error_dir)/('episode-'+str(state['seed'])+'.json'),failure)
        for i in range(min(len(seeds),len(self.workers))): start(i,next(waiting))
        while active:
            if progress and time.monotonic()-last_progress>3:
                progress({'valid_completed_in_batch':len(completed),'active_lobbies':len(active),
                    'decisions_in_active_lobbies':sum(s['count'] for s in active.values()),
                    'worker_pids':[w.metadata['pid'] for w in self.workers]})
                last_progress=time.monotonic()
            decisions=[]; learned=[]
            for i,state in list(active.items()):
                obs=state['obs']; diag=obs['diagnostics']
                if diag['done']:
                    ranks=diag.get('placements')
                    if not diag['terminated'] or diag['truncated'] or diag['stop_reason']!='normal_elimination' or not ranks or sorted(ranks)!=list(range(1,9)):
                        fail(i,ValueError('non-normal terminal: '+json.dumps(diag))); continue
                    completed.append(dict(seed=state['seed'],episode_id=state['episode_id'],trajectories=state['trajectories'],ranks=ranks,
                        learner_seat=state['learner_seat'],decisions=state['count'],terminal_reason=diag['stop_reason'],
                        assignments=state['assignments'],learner_version=learner_version,opponent_pool_hash=opponent_pool.manifest_hash))
                    del active[i]; continue
                if state['count']>=self.config['max_decisions']:
                    fail(i,RuntimeError('driver decision guard')); continue
                seat=obs['current_seat']
                if seat is None or obs['seat']!=seat:
                    fail(i,ValueError('no actionable current public seat')); continue
                identity=state['assignments'][seat]
                if identity!='learner' and opponent_pool.entry(identity)['kind']=='scripted':
                    decisions.append((i,heuristic_action(obs,state['rng'],opponent_pool.entry(identity)['style'],
                        state=state['heuristic_states'].setdefault(seat,{}))))
                else: learned.append((i,seat,public_input(obs),identity))
            groups={}
            for item in learned: groups.setdefault(item[3],[]).append(item)
            for identity,group in groups.items():
                actor=model if identity=='learner' else opponent_pool.models[identity]
                inputs=observation_tensors([o for _,_,o,_ in group],device)
                hidden=torch.stack([active[i]['hidden'].get(seat,torch.zeros(actor.width,device=device)) for i,seat,_,_ in group])
                with torch.no_grad():
                    logits,values,new_hidden,_=actor(*inputs,hidden)
                    dist=Categorical(logits=logits); actions=dist.sample(); logs=dist.log_prob(actions)
                for j,(i,seat,obs,_) in enumerate(group):
                    action=int(actions[j]); state=active[i]
                    if identity=='learner':
                        state['trajectories'][seat].append(dict(observation=obs,action=action,log_prob=float(logs[j]),value=float(values[j]),behavior_hidden=hidden[j].detach().cpu()))
                    state['hidden'][seat]=new_hidden[j].detach(); decisions.append((i,action))
            futures={self.pool.submit(self.workers[i].request,'step',index=action):i for i,action in decisions}
            for future,i in futures.items():
                try: active[i]['obs']=future.result(); active[i]['count']+=1
                except Exception as exc: fail(i,exc)
            for i in range(len(self.workers)):
                if i not in active:
                    try: seed=next(waiting)
                    except StopIteration: continue
                    try: start(i,seed)
                    except Exception as exc:
                        failures.append(dict(seed=seed,error=str(exc),terminal_reason='reset_failure'))
        return completed,failures

def update(model,optimizer,games,config):
    trajectories=[]; all_adv=[]
    for game in games:
        for seat,rows in enumerate(game['trajectories']):
            if not rows: continue
            labels=advantages([r['value'] for r in rows],game['ranks'][seat],config['gamma'],config['gae_lambda'])
            trajectories.append((rows,labels,game['ranks'][seat])); all_adv += [a for a,_ in labels]
    if not all_adv: raise ValueError('no validated on-policy decisions')
    mean=statistics.mean(all_adv); std=statistics.pstdev(all_adv)+1e-8
    device=next(model.parameters()).device; total_steps=0; kls=[]; losses=[]; grad_norms=[]
    # ID dropout remains disabled during PPO likelihood calculation so ratios refer
    # to exactly the same policy as sampling. Configured dropout is available for
    # separately labelled representation/auxiliary experiments.
    model.eval()
    for epoch in range(config['ppo_epochs']):
        random.shuffle(trajectories)
        stop=False
        for rows,labels,rank in trajectories:
            for start in range(0,len(rows),config['sequence_length']):
                end=min(len(rows),start+config['sequence_length']); burn_start=max(0,start-config['burn_in'])
                cached=rows[burn_start].get('behavior_hidden')
                hidden=cached.to(device).unsqueeze(0) if cached is not None else torch.zeros((1,model.width),device=device)
                # Cached per-seat behavior memory with a contiguous burn-in prefix.
                # This bounds replay cost; no random independent timestep training.
                with torch.no_grad():
                    for row in rows[burn_start:start]:
                        _,_,hidden,_=model(*observation_tensors([row['observation']],device),hidden)
                optimizer.zero_grad(set_to_none=True); terms=[]; chunk_kls=[]
                for t in range(start,end):
                    row=rows[t]; adv,ret=labels[t]
                    logits,value,hidden,placement=model(*observation_tensors([row['observation']],device),hidden)
                    dist=Categorical(logits=logits); log=dist.log_prob(torch.tensor([row['action']],device=device))
                    ratio=(log-row['log_prob']).exp(); normalized=(adv-mean)/std
                    policy=-torch.minimum(ratio*normalized,ratio.clamp(1-config['ppo_clip'],1+config['ppo_clip'])*normalized).mean()
                    value_loss=(value-ret).square().mean()
                    place_loss=torch.nn.functional.cross_entropy(placement,torch.tensor([rank-1],device=device))
                    terms.append(policy+config['value_coefficient']*value_loss+config['placement_coefficient']*place_loss-config['entropy_coefficient']*dist.entropy().mean())
                    chunk_kls.append(float(((ratio-1)-(log-row['log_prob'])).detach()))
                loss=torch.stack(terms).mean()
                if not torch.isfinite(loss): raise ValueError('nonfinite PPO loss')
                loss.backward(); norm=torch.nn.utils.clip_grad_norm_(model.parameters(),config['max_grad_norm'],error_if_nonfinite=True)
                optimizer.step(); total_steps+=1; losses.append(float(loss.detach())); grad_norms.append(float(norm)); kls+=chunk_kls
                if statistics.mean(chunk_kls)>config['target_kl']: stop=True; break
            if stop: break
        if stop: break
    return dict(optimizer_steps=total_steps,loss=statistics.mean(losses),approx_kl=statistics.mean(kls),
        max_gradient_norm=max(grad_norms),decisions=len(all_adv),epochs_started=epoch+1)

def checkpoint(path,model,optimizer,scheduler,config,catalog,binding,counters,evaluation):
    payload=dict(format='bgagent10-recurrent-ppo-v1',model=model.state_dict(),optimizer=optimizer.state_dict(),
        scheduler=scheduler.state_dict(),scaler=None,config=config,catalog=catalog.manifest(),binding=binding,
        counters=counters,python_rng=random.getstate(),torch_rng=torch.get_rng_state(),
        cuda_rng=torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
        normalization={'type':'native fixed scales; no running moments'},
        sampler={'next_training_seed':config['seed']+counters['attempted_games'], 'boundary':'no active lobbies'},
        curriculum={'stage':'A-complete-game-pipeline'},opponent_pool=counters.get('opponent_pool_manifest',{'state':'not initialized; unit fixture only'}),
        anchor=None,quarantine_manifest=counters['quarantined'],evaluation=evaluation,last_promotion=None,
        contract=learning_contract(),
        versions={'python':sys.version,'torch':torch.__version__,'code':digest({p.name:p.read_text('utf8') for p in Path(__file__).parent.glob('*.py')})})
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_suffix('.tmp')
    with temp.open('wb') as f: torch.save(payload,f); f.flush(); os.fsync(f.fileno())
    os.replace(temp,path)

def evaluation_summary(games,opponent,path):
    ranks=[g['ranks'][g['learner_seat']] for g in games]
    if not ranks: raise ValueError('zero valid independent evaluation games')
    mean=statistics.mean(ranks)
    # One learned seat per independent lobby, normal 95% interval explicitly labelled.
    half=7*math.sqrt(math.log(2/.05)/(2*len(ranks)))
    return dict(games=len(ranks),mean_rank=mean,top4_rate=statistics.mean(r<=4 for r in ranks),
        win_rate=statistics.mean(r==1 for r in ranks),ci_low=max(1,mean-half),
        ci_high=min(8,mean+half),ci_method='bounded rank [1,8] Hoeffding 95%; independent lobbies; fixed evaluation only',
        opponent=opponent,checkpoint=str(path),ranks=ranks,seeds=[g['seed'] for g in games],
        opponent_pool_hashes=sorted(set(g.get('opponent_pool_hash','legacy') for g in games)),
        assignments=[g.get('assignments') for g in games])

def validate_config(user):
    unknown=set(user)-set(DEFAULT_CONFIG)-{'rules_path'}
    if unknown: raise ValueError('unknown configuration: '+str(sorted(unknown)))
    config={**DEFAULT_CONFIG,**user}; config['rules_path']=str(Path(config.get('rules_path',DEFAULT_RULES)).resolve())
    for key in ('workers','rounds','games_per_round','eval_every_games','eval_games','ppo_epochs','sequence_length','max_decisions','torch_threads'):
        if type(config[key]) is not int or config[key]<1: raise ValueError(key+' must be a positive integer')
    for key in ('auxiliary_batch_size','auxiliary_sequence_length'):
        if type(config[key]) is not int or config[key]<1: raise ValueError('invalid '+key)
    if type(config['auxiliary_updates']) is not int or config['auxiliary_updates']<0: raise ValueError('invalid auxiliary_updates')
    if config['eval_opponent'] not in ('scripted','random','history','mixed'): raise ValueError('unsupported evaluation opponent')
    if config['train_opponents'] not in ('selfplay','history','mixed'): raise ValueError('unsupported training opponents')
    if config['model_preset'] not in ('main','small','micro'): raise ValueError('unsupported model preset')
    if config['gamma']!=1: raise ValueError('v1 complete-game utility requires gamma=1')
    if config['seed']<0 or config['seed']>=2**62: raise ValueError('seed out of range')
    for key in ('learning_rate','gae_lambda','ppo_clip','max_grad_norm','target_kl'):
        if not math.isfinite(config[key]) or config[key]<=0: raise ValueError('invalid '+key)
    if not 0<=config['burn_in'] or config['gae_lambda']>1: raise ValueError('invalid sequence config')
    return config

def learning_contract():
    return dict(reward='rank-linear-9-2rank-over7-v1',observation='numeric3227-cards124-public-v1',
        action='semantic245-native-order-v1',memory='seat-gru-burnin-v1',
        model_code=digest({name:(Path(__file__).parent/name).read_text('utf8') for name in ('model.py','encoding.py')}))

def auxiliary_update(model,optimizer,games,config,binding,catalog):
    """Separate representation objective; historical live samples NEVER enter PPO.

    This initial public-state reconstruction objective tests actual data consumption;
    it is not a demonstrated strength improvement or policy imitation claim.
    """
    if not config['auxiliary_updates']: return []
    if not config['live_data_root']: raise ValueError('auxiliary updates require live_data_root')
    from . import live_data
    simulation=[]
    for game in games:
        for trajectory in game['trajectories']:
            if trajectory:
                for start in range(0,len(trajectory),config['auxiliary_sequence_length']):
                    simulation.append([dict(observation=r['observation'],confidence=1.,missing_fields=[],flags=[]) for r in trajectory[start:start+config['auxiliary_sequence_length']]])
    reports=[]; device=next(model.parameters()).device
    contract=learning_contract()
    expected_versions=dict(engine_hash=digest(binding),rules_manifest_hash=binding['named_target_roster_binding_SHA'],
        observation_schema=contract['observation'],action_schema=contract['action'],
        card_mapping_hash=catalog.mapping_hash,reward_version=contract['reward'])
    for iteration in range(config['auxiliary_updates']):
        # Python RNG is included in every checkpoint. Draw a fresh sampler seed
        # across batches, with exact continuation after restoring that RNG state.
        sampling_seed=random.getrandbits(63)
        batch=live_data.sample_auxiliary(config['live_data_root'],simulation,config['auxiliary_batch_size'],
            sequence_length=config['auxiliary_sequence_length'],seed=sampling_seed,purpose='representation',live_weight=3.,live_cap=.30,
            expected_versions=expected_versions)
        used=[]; terms=[]; optimizer.zero_grad(set_to_none=True)
        for sequence in batch:
            hidden=None; sequence_terms=[]
            for step in sequence['steps']:
                observation=step.get('observation')
                if not observation or step.get('missing_fields') or step.get('flags') or step.get('confidence',0)<.95:
                    sequence_terms=[]; break
                tensors=observation_tensors([public_input(observation)],device)
                _,_,hidden,_=model(*tensors,hidden)
                target=tensors[0][:,:model.layout['GLOBAL_F']]
                sequence_terms.append(torch.nn.functional.smooth_l1_loss(model.reconstruct_public(hidden),target))
            if sequence_terms:
                terms.append(torch.stack(sequence_terms).mean()); used.append(sequence)
        if not terms: continue
        loss=torch.stack(terms).mean()
        if not torch.isfinite(loss): raise ValueError('nonfinite auxiliary representation loss')
        loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),config['max_grad_norm'],error_if_nonfinite=True)
        optimizer.step()
        live_data.record_usage(config['live_data_root'],used,purpose='representation')
        reports.append(dict(loss=float(loss.detach()),objective='public-state-reconstruction-v1',sampling_seed=sampling_seed,
            live_sequences=sum(s['source']=='live' for s in used),simulation_sequences=sum(s['source']=='simulation' for s in used),
            live_episode_ids=[s.get('episode_id') for s in used if s['source']=='live'],loss_weight=1.0))
    return reports

def run(config,run_dir):
    config=validate_config(config); run_dir=Path(run_dir).resolve(); run_dir.mkdir(parents=True,exist_ok=True)
    lock=run_dir/'writer.lock'
    # Exclusive create rejects simultaneous and stale ownership instead of guessing.
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY); os.write(fd,str(os.getpid()).encode()); os.close(fd)
    collector=None; counters=dict(completed_games=0,attempted_games=0,eval_attempted_games=0,round=0,updates=0,quarantined=[]); last_checkpoint=None; evaluation=None
    def status(state,message):
        atomic_json(run_dir/'status.json',dict(state=state,pid=os.getpid(),checkpoint=last_checkpoint,message=message,**{k:counters[k] for k in ('completed_games','round','updates')},updated=time.time()))
    try:
        atomic_json(run_dir/'config.json',config); (run_dir/'errors').mkdir(exist_ok=True)
        status('starting','验证封存后端、卡牌语义与训练配置')
        torch.set_num_threads(config['torch_threads']); random.seed(config['seed']); torch.manual_seed(config['seed'])
        catalog=CardCatalog(config['rules_path']); collector=Collector(config,catalog)
        model=PolicyModel(catalog,collector.metadata['layout'],config['model_preset']).to(config['device'])
        optimizer=torch.optim.AdamW(model.parameters(),lr=config['learning_rate']); scheduler=torch.optim.lr_scheduler.LambdaLR(optimizer,lambda _:1.)
        if config['resume_from']:
            saved=torch.load(config['resume_from'],map_location=config['device'],weights_only=False)
            if saved['format']!='bgagent10-recurrent-ppo-v1' or saved['binding']!=collector.metadata['binding'] or saved['catalog']!=catalog.manifest() or saved.get('contract')!=learning_contract(): raise ValueError('checkpoint rules/catalog/learning semantics mismatch; audited migration required')
            if saved['config']['model_preset']!=config['model_preset']: raise ValueError('checkpoint architecture mismatch')
            if saved['config']['seed']!=config['seed']: raise ValueError('resume seed mismatch')
            model.load_state_dict(saved['model']); optimizer.load_state_dict(saved['optimizer']); scheduler.load_state_dict(saved['scheduler']); counters=saved['counters']
            for key in ('gamma','gae_lambda','ppo_clip','sequence_length','burn_in'):
                if saved['config'][key]!=config[key]: raise ValueError('resume learning configuration mismatch: '+key)
            # Explicit current configuration overrides saved optimizer LR.
            for group in optimizer.param_groups: group['lr']=config['learning_rate']; group['initial_lr']=config['learning_rate']
            scheduler.base_lrs=[config['learning_rate'] for _ in optimizer.param_groups]
            random.setstate(saved['python_rng']); torch.set_rng_state(saved['torch_rng'].cpu())
            if saved['cuda_rng'] is not None and torch.cuda.is_available(): torch.cuda.set_rng_state_all([state.cpu() for state in saved['cuda_rng']])
            evaluation=saved['evaluation']; last_checkpoint=str(Path(config['resume_from']).resolve())
            if 'eval_attempted_games' not in counters:
                previous_eval_seeds=(evaluation or {}).get('seeds',[])
                counters['eval_attempted_games']=max(0,max(previous_eval_seeds,default=config['seed']+2**40-1)-(config['seed']+2**40)+1)
        if hasattr(collector,'train_pool'):
            if evaluation and evaluation.get('opponent_pool_hashes') != [collector.eval_pool.manifest_hash]:
                append_json(run_dir/'events.jsonl',dict(event='previous_evaluation_not_reused',
                    reason='opponent pool changed; new evaluation required',
                    previous_pool_hashes=evaluation.get('opponent_pool_hashes'),
                    current_pool_hash=collector.eval_pool.manifest_hash))
                evaluation=None
            counters['opponent_pool_manifest']={'training':collector.train_pool.manifest,'training_hash':collector.train_pool.manifest_hash,
                'evaluation':collector.eval_pool.manifest,'evaluation_hash':collector.eval_pool.manifest_hash}
        append_json(run_dir/'events.jsonl',dict(event='started',config=config,worker_pids=[w.metadata['pid'] for w in collector.workers],parameters=sum(p.numel() for p in model.parameters()),opponent_pool=counters.get('opponent_pool_manifest')))
        # Split logical rounds into update/evaluation boundaries so large rounds
        # cannot skip scheduled evaluations or delay pause for an entire round.
        batches=[]; future_completed=counters['completed_games']
        for logical_round in range(config['rounds']):
            remaining=config['games_per_round']
            while remaining:
                until_eval=config['eval_every_games']-future_completed%config['eval_every_games']
                count=min(remaining,until_eval,config['workers'])
                batches.append((logical_round,count)); remaining-=count; future_completed+=count
        base_round=counters['round']
        for batch_index,(logical_round,n) in enumerate(batches):
            command=json.loads((run_dir/'control.json').read_text('utf8')).get('command') if (run_dir/'control.json').exists() else None
            if command in ('pause','stop'):
                last_checkpoint=str(run_dir/'checkpoints'/f"step-{counters['updates']:08d}.pt")
                checkpoint(last_checkpoint,model,optimizer,scheduler,config,catalog,collector.metadata['binding'],counters,evaluation)
                status('paused' if command=='pause' else 'stopped','已在安全边界保存'); return
            status('running','真实完整对局采样与连续序列 PPO')
            started=time.perf_counter(); seed=config['seed']+counters['attempted_games']
            games,failures=collector.collect(model,list(range(seed,seed+n)),error_dir=run_dir/'errors',
                progress=lambda detail:atomic_json(run_dir/'progress.json',dict(phase='sampling',updated=time.time(),**detail)))
            counters['attempted_games']+=n; counters['quarantined']+=failures
            append_json(run_dir/'events.jsonl',dict(event='sampling_lobbies',
                engine_hash=digest(collector.metadata['binding']),
                rules_manifest_hash=collector.metadata['binding']['named_target_roster_binding_SHA'],
                card_mapping_hash=catalog.mapping_hash,learning_contract=learning_contract(),
                lobbies=[{key:game[key] for key in ('seed','episode_id','terminal_reason','ranks','decisions','learner_seat','learner_version','opponent_pool_hash','assignments') if key in game} for game in games]))
            if failures:
                append_json(run_dir/'events.jsonl',dict(event='quarantined',games=len(failures),details=failures))
                last_checkpoint=str(run_dir/'checkpoints'/f"step-{counters['updates']:08d}.pt")
                checkpoint(last_checkpoint,model,optimizer,scheduler,config,catalog,collector.metadata['binding'],counters,evaluation)
                status('paused','环境异常整局隔离，已保存私有快照与动作轨迹，等待审查'); return
            if not games: raise RuntimeError('all sampled lobbies quarantined; no gradient permitted')
            metrics=update(model,optimizer,games,config)
            auxiliary_reports=auxiliary_update(model,optimizer,games,config,collector.metadata['binding'],catalog)
            for report in auxiliary_reports: append_json(run_dir/'events.jsonl',dict(event='auxiliary_update',**report))
            scheduler.step()
            counters['updates']+=metrics['optimizer_steps']+len(auxiliary_reports); counters['completed_games']+=len(games); counters['round']=base_round+logical_round+1
            last_checkpoint=str(run_dir/'checkpoints'/f"step-{counters['updates']:08d}.pt")
            checkpoint(last_checkpoint,model,optimizer,scheduler,config,catalog,collector.metadata['binding'],counters,evaluation)
            append_json(run_dir/'events.jsonl',dict(event='update',**metrics,**{k:counters[k] for k in ('completed_games','round','updates')},elapsed_seconds=time.perf_counter()-started,checkpoint=last_checkpoint))
            previous=counters['completed_games']-len(games)
            if counters['completed_games']//config['eval_every_games']>previous//config['eval_every_games'] or batch_index==len(batches)-1:
                status('evaluating','独立完整对局评估；每局仅一个受测座位')
                eval_seed=config['seed']+2**40+counters.get('eval_attempted_games',0)
                counters['eval_attempted_games']=counters.get('eval_attempted_games',0)+config['eval_games']
                eg,ef=collector.collect(model,list(range(eval_seed,eval_seed+config['eval_games'])),evaluation=True,error_dir=run_dir/'errors',
                    progress=lambda detail:atomic_json(run_dir/'progress.json',dict(phase='evaluation',updated=time.time(),**detail)))
                if ef:
                    counters['quarantined']+=ef
                    checkpoint(last_checkpoint,model,optimizer,scheduler,config,catalog,collector.metadata['binding'],counters,evaluation)
                    status('paused','独立评估出现环境异常，整局隔离等待审查'); return
                evaluation=evaluation_summary(eg,config['eval_opponent'],last_checkpoint)
                evaluation.update({k:counters[k] for k in ('completed_games','updates','round')})
                evaluation['quarantined_games']=len(ef); append_json(run_dir/'evaluations.jsonl',evaluation)
                checkpoint(last_checkpoint,model,optimizer,scheduler,config,catalog,collector.metadata['binding'],counters,evaluation)
        command=json.loads((run_dir/'control.json').read_text('utf8')).get('command') if (run_dir/'control.json').exists() else None
        status('paused' if command=='pause' else 'stopped' if command=='stop' else 'completed','训练任务结束；正式晋级需独立验收')
    except BaseException as exc:
        atomic_json(run_dir/'errors'/f'fatal-{int(time.time())}.json',dict(error=str(exc),traceback=traceback.format_exc(),checkpoint=last_checkpoint))
        status('failed',str(exc)); raise
    finally:
        if collector: collector.close()
        lock.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True); parser.add_argument('--run-dir',required=True)
    args=parser.parse_args(); run(json.loads(Path(args.config).read_text('utf-8-sig')),args.run_dir)

if __name__=='__main__': main()
