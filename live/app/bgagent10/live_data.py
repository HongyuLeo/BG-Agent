"""Immutable decision journal, whole-game intake, and auxiliary-only replay."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import time
import uuid
from contextlib import contextmanager


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')


def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def immutable(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())


def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    immutable(temp,value);os.replace(temp,path)


class Journal:
    """One writer per episode; already committed event files never change.

    A crash may leave a final incomplete file. read_events reports it and intake
    quarantines the episode. Reopen only after the coordinator proves no writer
    remains; no automatic stale-lock stealing.
    """
    def __init__(self,root,episode_id=None):
        self.episode_id=episode_id or uuid.uuid4().hex
        if not self.episode_id.replace('-','').replace('_','').isalnum():raise ValueError('invalid episode ID')
        self.path=Path(root)/'raw'/self.episode_id;self.path.mkdir(parents=True,exist_ok=True)
        self.lock=self.path/'writer.lock';immutable(self.lock,{'pid':os.getpid(),'time':time.time()})
        try:
            events=read_events(self.path)
            self.sequence=len(events);self.previous=digest(events[-1]) if events else ''
        except Exception:
            self.lock.unlink();raise
    def append(self,kind,data):
        row={'sequence':self.sequence,'kind':kind,'time_ns':time.time_ns(),'previous':self.previous,'data':data}
        immutable(self.path/f'{self.sequence:08d}.json',row)
        self.previous=digest(row);self.sequence+=1
        return row
    def capture(self,raw,kind='log'):
        blob_sha=hashlib.sha256(raw).hexdigest();name='evidence/'+blob_sha+'.bin'
        path=self.path/name;path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            with path.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        return {'path':name,'sha256':blob_sha,'kind':kind,'size':len(raw)}
    def close(self):self.lock.unlink(missing_ok=True)
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


def read_events(path):
    previous='';rows=[]
    for i,file in enumerate(sorted(Path(path).glob('[0-9]*.json'))):
        row=json.loads(file.read_text(encoding='utf-8'))
        if file.name!=f'{i:08d}.json' or row.get('sequence')!=i or row.get('previous')!=previous:
            raise ValueError('journal chain/sequence mismatch')
        canonical(row);previous=digest(row);rows.append(row)
    return rows


VERSION_FIELDS='engine_hash rules_manifest_hash observation_schema action_schema card_mapping_hash reward_version policy_version software_version'.split()
DECISION_FIELDS='turn seat_id observation history missing_fields confidence legal_actions suggested_action executed_action execution behavior_probability value_prediction after battle_result flags'.split()
FORBIDDEN={'seed','rng','snapshot','token','debug','hidden_state','final_rank','placement','episode_id','game_key'}


def input_boundary(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if key in FORBIDDEN:return False
            if not input_boundary(item):return False
    elif isinstance(value,list):return all(input_boundary(x) for x in value)
    return True


def verify_evidence(reference,episode_path):
    if not isinstance(reference,dict) or not reference.get('sha256') or not reference.get('path'):return False
    path=(Path(episode_path)/reference['path']).resolve()
    if not path.is_relative_to(Path(episode_path).resolve()):return False
    try:return hashlib.sha256(path.read_bytes()).hexdigest()==reference['sha256']
    except OSError:return False


def validate(rows,expected,episode_path):
    reasons=[]
    if not rows or rows[0]['kind']!='begin':return ['missing_begin']
    begin=rows[0]['data'];versions=begin.get('versions',{})
    for key in VERSION_FIELDS:
        if not versions.get(key):reasons.append('missing_version:'+key)
        if key in expected and versions.get(key)!=expected[key]:reasons.append('version_mismatch:'+key)
    if begin.get('source')!='real-client':reasons.append('not_real_client')
    if not begin.get('game_key'):reasons.append('missing_game_key')
    if rows[-1]['kind']!='terminal':reasons.append('incomplete_episode')
    elif rows[-1]['data'].get('reason')!='normal' or rows[-1]['data'].get('rank') not in range(1,9) or not verify_evidence(rows[-1]['data'].get('evidence'),episode_path):reasons.append('unverified_terminal')
    decisions=[r for r in rows if r['kind']=='decision']
    if not decisions:reasons.append('no_decisions')
    requests=set()
    for r in decisions:
        d=r['data'];prefix=f"decision:{r['sequence']}:"
        for key in DECISION_FIELDS:
            if key not in d:reasons.append(prefix+'missing:'+key)
        if not input_boundary(d.get('observation',{})) or not input_boundary(d.get('history',[])):reasons.append(prefix+'input_leakage')
        observation=d.get('observation',{})
        if (len(observation.get('features',[])),len(observation.get('cards',[])),len(observation.get('action_mask',[])))!=(3227,124,245):reasons.append(prefix+'observation_shape')
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in observation.get('features',[])):reasons.append(prefix+'nonfinite_features')
        if any(type(x)!=int or x<0 for x in observation.get('cards',[])):reasons.append(prefix+'invalid_card_index')
        if any(x not in (0,1,True,False) for x in observation.get('action_mask',[])):reasons.append(prefix+'invalid_mask')
        if d.get('missing_fields') or d.get('confidence',0)<1:reasons.append(prefix+'uncertain_observation')
        if d.get('flags'):reasons.append(prefix+'intervention_or_error')
        action=d.get('executed_action');mask=observation.get('action_mask',[])
        if type(action)!=int or action not in range(245) or action not in d.get('legal_actions',[]) or len(mask)!=245 or not mask[action]:reasons.append(prefix+'illegal_action')
        if d.get('suggested_action')!=action:reasons.append(prefix+'action_divergence')
        execution=d.get('execution',{});request=execution.get('request_id')
        if not request or request in requests:reasons.append(prefix+'duplicate_or_missing_request')
        requests.add(request)
        if not execution.get('confirmed') or not execution.get('before_evidence') or not execution.get('after_evidence'):reasons.append(prefix+'execution_not_confirmed')
        if not all(verify_evidence(execution.get(key),episode_path) for key in ('before_evidence','after_evidence')):reasons.append(prefix+'evidence_hash_or_path_invalid')
        p=d.get('behavior_probability')
        if p is not None and (not isinstance(p,(float,int)) or not math.isfinite(p) or not 0<=p<=1):reasons.append(prefix+'invalid_probability')
        if p is None and not d.get('probability_unknown_reason'):reasons.append(prefix+'unexplained_probability')
    return sorted(set(reasons))


@contextmanager
def database(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'catalog.sqlite',timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS episodes (id TEXT PRIMARY KEY, game_key TEXT, raw_hash TEXT, split TEXT, status TEXT, reasons TEXT, path TEXT, decisions INTEGER, versions TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS usage (time REAL, episode_id TEXT, sequence_start INTEGER, count INTEGER, purpose TEXT)')
    try:
        with db:yield db
    finally:db.close()


def ingest(root,episode_id,expected=None):
    path=Path(root)/'raw'/episode_id
    # Only local IDs, never arbitrary paths from imported content.
    if path.resolve().parent!=(Path(root)/'raw').resolve():raise ValueError('invalid episode path')
    if (path/'writer.lock').exists():raise RuntimeError('episode writer still active')
    try:
        rows=read_events(path);reasons=validate(rows,expected or {},path)
        raw_hash=digest(rows);begin=rows[0]['data'] if rows else {}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        rows=[];begin={};reasons=['corrupt_raw:'+str(exc)];raw_hash=''
    game_key=begin.get('game_key','');split='evaluation' if game_key and int(hashlib.sha256(game_key.encode()).hexdigest()[:8],16)%5==0 else 'train'
    with database(root) as db:
        existing=db.execute('SELECT id, raw_hash, status FROM episodes WHERE game_key=? AND status != ?',(game_key,'quarantine')).fetchone() if game_key else None
        if existing and existing[0]!=episode_id:reasons.append('duplicate_game_key:'+existing[0])
        old=db.execute('SELECT raw_hash FROM episodes WHERE id=?',(episode_id,)).fetchone()
        if old and old[0]!=raw_hash:
            reasons.append('raw_mutated_since_intake');raw_hash=old[0]
        status='quarantine' if reasons else 'qualified'
        db.execute('INSERT OR REPLACE INTO episodes VALUES (?,?,?,?,?,?,?,?,?)',(episode_id,game_key,raw_hash,split,status,json.dumps(reasons),str(path.resolve()),sum(r['kind']=='decision' for r in rows),json.dumps(begin.get('versions',{}))))
    receipt={'episode_id':episode_id,'game_key':game_key,'raw_hash':raw_hash,'split':split,'status':status,'reasons':reasons,'ppo_eligible':False,'time_ns':time.time_ns()}
    immutable(Path(root)/'intake'/f'{episode_id}-{uuid.uuid4().hex}.json',receipt)
    return receipt


def quarantine(root,episode_ids,reason):
    with database(root) as db:
        for eid in episode_ids:
            db.execute('UPDATE episodes SET status=?,reasons=? WHERE id=?',('quarantine',json.dumps([reason]),eid))
    immutable(Path(root)/'quarantine'/f'{uuid.uuid4().hex}.json',{'episode_ids':list(episode_ids),'reason':reason})


def summarize(root):
    with database(root) as db:
        rows=db.execute('SELECT status,split,count(*),sum(decisions) FROM episodes GROUP BY status,split').fetchall()
        reasons=db.execute('SELECT reasons FROM episodes WHERE status=?',('quarantine',)).fetchall()
        usage=db.execute('SELECT count(*),count(distinct episode_id),coalesce(sum(count),0) FROM usage').fetchone()
    return {'groups':[{'status':a,'split':b,'games':c,'decisions':d or 0} for a,b,c,d in rows], 'new_live_games':sum(r[2] for r in rows),'qualified_games':sum(r[2] for r in rows if r[0]=='qualified'),'quarantine_reasons':[json.loads(r[0]) for r in reasons],'actual_used_sequences':usage[0],'effective_sources':usage[1],'actual_used_steps':usage[2],'real_evidence_authentication':'local provenance only; not server authentication','ppo_live_samples':0}


def sample_auxiliary(root,simulation_sequences,batch_size,sequence_length=16,seed=0,purpose='representation',live_weight=3.,live_cap=.30,expected_versions=None):
    """Sample continuous real sequences, at most one per source game per batch.

    Returned weights are 1; no additional live loss multiplier. Derived simulator
    branches are supplied as ordinary simulation sequences, never live evidence.
    Caller must invoke record_usage only after a successful auxiliary update.
    """
    if purpose not in ('representation','outcome_prediction','screened_distillation'):raise ValueError('历史实战禁止混入PPO；用途须独立验证')
    if batch_size<1 or sequence_length<1 or not 0<=live_cap<=.30 or not 0<=live_weight<=3:raise ValueError('invalid replay bounds')
    rng=random.Random(seed)
    with database(root) as db:
        candidates=db.execute('SELECT id,path,raw_hash,versions FROM episodes WHERE status=? AND split=?',('qualified','train')).fetchall()
    catalog=[(eid,path,h) for eid,path,h,versions in candidates if all(json.loads(versions).get(k)==v for k,v in (expected_versions or {}).items() if k!='policy_version')]
    eligible=[]
    for eid,path,raw_hash in catalog:
        try:rows=read_events(path)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            quarantine(root,[eid],'raw_read_failed:'+str(exc));continue
        if digest(rows)!=raw_hash:quarantine(root,[eid],'raw_hash_changed');continue
        source_versions=rows[0]['data'].get('versions',{}) if rows else {}
        if source_versions.get('auxiliary_training_compatible') is False:
            # Retain valid captured games for inspection/evaluation. A current
            # client adaptation alone does not change the sealed training rules.
            continue
        reasons=validate(rows,expected_versions or {},path)
        if reasons:quarantine(root,[eid],'replay_revalidation:'+','.join(reasons));continue
        decisions=[r for r in rows if r['kind']=='decision']
        if len(decisions)>=sequence_length:eligible.append((eid,decisions))
    # 3x relative weight; fraction caps conservatively lower with few games.
    fraction=(live_weight*len(eligible))/(len(simulation_sequences)+live_weight*len(eligible)) if eligible else 0
    cap=min(live_cap,max(.10,len(eligible)/100)) if eligible else 0.
    # Unbiased stochastic rounding preserves rare-source probability across
    # batches. Deterministic floor used to make small positive probabilities
    # permanently zero, irrespective of seed. Hard caps remain per batch, so
    # a fractional sparse-source cap below one slot still cannot emit one.
    expected_live=min(batch_size*min(fraction,cap),len(eligible),math.floor(batch_size*cap))
    live_n=math.floor(expected_live)
    remainder=expected_live-live_n
    if remainder>0 and rng.random()<remainder:live_n+=1
    output=[]
    for eid,decisions in rng.sample(eligible,live_n):
        start=rng.randrange(len(decisions)-sequence_length+1)
        rank=next(r['data']['rank'] for r in reversed(read_events(next(p for e,p,h in catalog if e==eid))) if r['kind']=='terminal')
        output.append({'source':'live','episode_id':eid,'sequence_start':start,'steps':[dict(r['data'],outcome_target={'rank':rank,'label_source':'normal_terminal','not_policy_input':True}) for r in decisions[start:start+sequence_length]],'loss_weight':1.})
    if len(output)<batch_size and not simulation_sequences:raise ValueError('模拟辅助序列不足，不能突破实战占比上限')
    for _ in range(batch_size-len(output)):output.append({'source':'simulation','steps':rng.choice(simulation_sequences),'loss_weight':1.})
    rng.shuffle(output)
    return output


def record_usage(root,batch,purpose):
    if purpose not in ('representation','outcome_prediction','screened_distillation'):raise ValueError('PPO forbidden')
    with database(root) as db:
        for sequence in batch:
            if sequence['source']=='live':db.execute('INSERT INTO usage VALUES (?,?,?,?,?)',(time.time(),sequence['episode_id'],sequence['sequence_start'],len(sequence['steps']),purpose))
