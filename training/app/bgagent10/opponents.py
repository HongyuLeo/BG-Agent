"""Frozen offline opponent pools. Heuristic styles are not human skill models."""
import hashlib,json,math,random
from pathlib import Path
import torch
from .encoding import digest
from .model import PolicyModel, build_checkpoint_model, STABLE_ACTOR_VERSION

STYLES=('balanced','economy','tempo','conservative','random')

def heuristic_action(obs,rng,style='balanced',state=None):
    if style not in STYLES: raise ValueError('unknown heuristic style')
    legal=[i for i,v in enumerate(obs['action_mask']) if v]
    if not legal: raise ValueError('no legal heuristic decision')
    if style=='random': return rng.choice(legal)
    # All data below are public numeric observation fields. State contains only
    # this seat's own action budget within the public turn; reset every new turn.
    f=obs['features']; turn=round(f[0]*20)
    state={} if state is None else state
    if state.get('turn')!=turn:
        state.clear();state.update(turn=turn,actions=0,swaps=0,powers=0,activations=[],refreshes=0)
    def choose(action):
        if not 30<=action<46:state['actions']+=1
        if 16<=action<23:state['swaps']+=1
        if 4<=action<6:state['powers']+=1
        if 23<=action<30:state['activations'].append(action)
        if action==1:state['refreshes']+=1
        return action
    def strength(offset,header=0):
        offset+=header
        return 10*(max(0,f[offset+1])+max(0,f[offset+2]))+3*f[offset+7]+2*f[offset+5]
    def hand_strength(index):return strength(285+40*index,9)
    def best(actions,score):
        highest=max(score(a) for a in actions)
        return rng.choice([a for a in actions if abs(score(a)-highest)<1e-6])
    choices=[i for i in legal if 30<=i<46]
    if choices: return choose(rng.choice(choices))
    if state['actions']>=24 and 0 in legal:return 0
    play=[i for i in legal if 46<=i<126]
    if play:return choose(best(play,lambda a:hand_strength((a-46)//8)))
    magnetic=[i for i in legal if 126<=i<196]
    if magnetic:return choose(best(magnetic,lambda a:hand_strength((a-126)//7)))
    if style=='economy' and 3 in legal: return choose(3)
    buys=[i for i in legal if 8<=i<16]
    if buys:return choose(best(buys,lambda a:strength(685+40*(a-8),9)))
    if style=='balanced' and 3 in legal and f[0]*20%3<1: return choose(3)
    active=[i for i in legal if 23<=i<30 and i not in state['activations']]
    if active and f[34]>.9 and len(state['activations'])<2:return choose(rng.choice(active))
    powers=[i for i in legal if 4<=i<6]
    if powers and state['powers']==0:return choose(rng.choice(powers))
    sells=[i for i in legal if 16<=i<23]
    hand_minions=[h for h in range(10) if f[285+40*h]>0 and f[286+40*h]>0 and f[288+40*h]==0]
    if sells and f[33]>.99 and hand_minions and state['swaps']==0:
        weakest=min(strength(68+31*(a-16)) for a in sells)
        strongest=max(hand_strength(h) for h in hand_minions)
        # At most one replacement per turn; never sell an entire warband.
        # Saturation also permits a bounded sidegrade so a stable draw can change.
        if strongest>weakest+2 or f[34]>.99:
            return choose(best(sells,lambda a:-strength(68+31*(a-16))))
    if style=='tempo' and 1 in legal and f[7]>.1 and f[34]<.99 and state['refreshes']<2:return choose(1)
    if 0 in legal: return 0
    return rng.choice(legal)

def policy_fingerprint(model):
    sha=hashlib.sha256()
    # Equal tensors with different forward semantics are different policies.
    if getattr(model,'actor_version',None)==STABLE_ACTOR_VERSION:
        sha.update(STABLE_ACTOR_VERSION.encode('utf8'))
    for name,tensor in sorted(model.state_dict().items()):
        value=tensor.detach().cpu().contiguous()
        sha.update(name.encode());sha.update(str((value.dtype,tuple(value.shape))).encode());sha.update(value.numpy().tobytes())
    return sha.hexdigest()

def read_pool(spec):
    if spec is None: return None
    if isinstance(spec,str):
        path=Path(spec).resolve(); value=json.loads(path.read_text('utf-8-sig'))
        entries=value['opponents'] if isinstance(value,dict) else value
        for entry in entries:
            if entry.get('kind')=='checkpoint': entry['path']=str((path.parent/entry['path']).resolve())
        return entries
    if isinstance(spec,list): return json.loads(json.dumps(spec))
    raise ValueError('pool must be manifest path or list of opponent entries')

class FrozenPool:
    def __init__(self,mode,spec,catalog,binding,layout,device):
        from .training import learning_contract
        self.models={}; self.entries=[]
        entries=read_pool(spec)
        if entries is None:
            if mode in ('scripted','random'): entries=[{'kind':'scripted','style':'balanced' if mode=='scripted' else 'random'}]
            elif mode=='mixed': entries=[{'kind':'scripted','style':s} for s in STYLES[:-1]]
            elif mode=='selfplay': entries=[]
            else: raise ValueError('history requires an explicit frozen checkpoint pool')
        if not entries and mode!='selfplay': raise ValueError('empty opponent pool')
        for index,entry in enumerate(entries):
            kind=entry.get('kind'); weight=entry.get('weight',1.)
            if not isinstance(weight,(float,int)) or not math.isfinite(weight) or weight<=0: raise ValueError('pool weight must be positive finite')
            identity='opponent-'+str(index)
            if kind=='scripted':
                style=entry.get('style','balanced')
                if style not in STYLES: raise ValueError('unknown heuristic style')
                item=dict(id=identity,kind=kind,style=style,weight=weight,version='public-heuristics-v2',
                    heuristic_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
                if mode=='history': raise ValueError('history pool must contain checkpoint opponents')
            elif kind=='checkpoint':
                path=Path(entry['path']).resolve();sha=hashlib.sha256(path.read_bytes()).hexdigest()
                if entry.get('sha256')!=sha: raise ValueError('history checkpoint SHA mismatch; explicit pinned hash required')
                saved=torch.load(path,map_location='cpu',weights_only=False)
                model=build_checkpoint_model(saved,catalog,{'binding':binding,'layout':layout},device=device)
                model.eval(); model.requires_grad_(False)
                self.models[identity]=model
                item=dict(id=identity,kind=kind,path=str(path),sha256=sha,weight=weight,
                    policy_fingerprint=policy_fingerprint(model),model_preset=model.preset,learning_contract=saved['contract'])
            else: raise ValueError('opponent kind must be scripted or checkpoint')
            self.entries.append(item)
        self.manifest={'mode':mode,'opponents':self.entries,'heuristics_are_human_models':False}
        self.manifest_hash=digest(self.manifest)

    def assignments(self,seed,evaluation=False):
        learner=seed%8
        if self.manifest['mode']=='selfplay' and not evaluation: return ['learner']*8
        if not self.entries: raise ValueError('evaluation requires an opponent pool')
        rng=random.Random(seed^0x5A17ACED)
        chosen=rng.choices([e['id'] for e in self.entries],[e['weight'] for e in self.entries],k=8)
        chosen[learner]='learner'
        return chosen

    def entry(self,identity): return next(e for e in self.entries if e['id']==identity)
