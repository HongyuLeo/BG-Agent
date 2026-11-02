"""Explicit offline model migration. Originals stay immutable; candidates unpromoted.

This does not relax training/model loading checks or migrate old environment state.
Callers must validate the new rules authority and independently evaluate the result.
"""
import ast, copy, hashlib, os
from pathlib import Path
import torch
from .model import PolicyModel
from .training import learning_contract
from .encoding import digest

def policy_ast(source):
    tree=ast.parse(source)
    names=('PolicyModel','observation_tensors')
    selected={node.name:ast.dump(node,include_attributes=False) for node in tree.body
              if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in names}
    if set(selected)!=set(names): raise ValueError('missing policy class/tensor adapter for audit')
    presets=[node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='PRESETS' for target in node.targets)]
    if len(presets)!=1: raise ValueError('missing unique architecture preset declaration')
    selected['PRESETS']=ast.dump(presets[0],include_attributes=False)
    return selected

def prove_policy_unchanged(old_source,new_source):
    before=policy_ast(old_source); after=policy_ast(new_source)
    if before!=after: raise ValueError('policy forward/parameter or tensor adapter AST changed; migration requires separate implementation')
    return {'PolicyModel_AST_equal':True,'observation_tensors_AST_equal':True,'PRESETS_AST_equal':True,
        'old_source_sha':hashlib.sha256(old_source.encode()).hexdigest(),
        'new_source_sha':hashlib.sha256(new_source.encode()).hexdigest()}

def migrate_checkpoint(source,destination,catalog,binding,layout,*,kind,old_model_source=None,
                       seed=97,new_rules_path=None):
    if kind not in ('mapping-reorder','new-existing-mechanism-card','numeric-rule-adaptation','load-check-only'):
        raise ValueError('unsupported migration kind')
    source=Path(source).resolve(); destination=Path(destination).resolve()
    if source==destination or destination.exists(): raise ValueError('migration destination must be new; original immutable')
    original_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    saved=torch.load(source,map_location='cpu',weights_only=False)
    if saved.get('format')!='bgagent10-recurrent-ppo-v1': raise ValueError('unsupported source format')
    old_contract=saved.get('contract',{}); current=learning_contract()
    for key in ('reward','observation','action','memory'):
        if old_contract.get(key)!=current[key]: raise ValueError('changed learning contract '+key+' needs dedicated migration')
    proof=None
    if old_contract.get('model_code')!=current['model_code'] or kind=='load-check-only':
        if old_model_source is None: raise ValueError('old model source required for AST audit')
        old_path=Path(old_model_source)
        old_text=old_path.read_text('utf8')
        encoding_text=(old_path.parent/'encoding.py').read_text('utf8')
        archived_code=digest({'model.py':old_text,'encoding.py':encoding_text})
        if archived_code!=old_contract.get('model_code'): raise ValueError('archived source does not match source checkpoint code contract')
        if encoding_text!=(Path(__file__).parent/'encoding.py').read_text('utf8'):
            raise ValueError('encoding implementation changed; dedicated semantic code migration required')
        proof=prove_policy_unchanged(old_text,(Path(__file__).parent/'model.py').read_text('utf8'))
    old_ids=saved['catalog']['stable_ids']; new_ids=catalog.stable_ids
    if len(set(old_ids))!=len(old_ids) or len(set(new_ids))!=len(new_ids): raise ValueError('duplicate stable identities')
    if catalog.mapping_hash!=digest(catalog.runtime_ids): raise ValueError('new runtime identity mapping hash mismatch')
    if len(catalog.runtime_ids)!=len(catalog.runtime_to_stable) or len(new_ids)!=len(catalog.semantics): raise ValueError('catalog dimensions mismatch')
    for runtime_id,stable_index in zip(catalog.runtime_ids,catalog.runtime_to_stable.tolist()):
        if not 0<=stable_index<len(new_ids) or runtime_id!=new_ids[stable_index]: raise ValueError('runtime-to-stable mapping mismatch')
    if kind=='load-check-only' and (saved['catalog']!=catalog.manifest() or saved['binding']!=binding):
        raise ValueError('load-check-only cannot alter rules/catalog')
    if kind=='mapping-reorder' and set(old_ids)!=set(new_ids): raise ValueError('mapping-only migration cannot add/drop identities')
    if kind=='mapping-reorder':
        prior={key:i for i,key in enumerate(old_ids)}
        for i,key in enumerate(new_ids):
            if not torch.equal(catalog.semantics[i],saved['model']['semantics'][prior[key]]):
                raise ValueError('mapping-only migration cannot change card semantics')
    with torch.random.fork_rng():
        torch.manual_seed(seed)
        model=PolicyModel(catalog,layout,saved['config']['model_preset'])
    state=model.state_dict(); special={'identity.weight','semantics','runtime_to_stable'}
    shared=[]
    for key,value in saved['model'].items():
        if key in special: continue
        if key not in state or state[key].shape!=value.shape: raise ValueError('shared architecture mismatch: '+key)
        state[key]=value.clone(); shared.append(key)
    if set(state)-special!=set(shared): raise ValueError('unmigrated shared model parameter')
    old_map={key:i for i,key in enumerate(old_ids)}; reused=[]; added=[]
    for i,key in enumerate(new_ids):
        if key in old_map:
            state['identity.weight'][i]=saved['model']['identity.weight'][old_map[key]]; reused.append(key)
        else: added.append(key)
    # New semantics/runtime buffers remain from the qualified destination catalog.
    model.load_state_dict(state)
    candidate=copy.deepcopy(saved); candidate['model']=model.state_dict(); candidate['catalog']=catalog.manifest()
    candidate['binding']=copy.deepcopy(binding); candidate['contract']=current
    optimizer=torch.optim.AdamW(model.parameters(),lr=saved['config']['learning_rate'])
    scheduler=torch.optim.lr_scheduler.LambdaLR(optimizer,lambda _:1.)
    candidate['optimizer']=optimizer.state_dict(); candidate['scheduler']=scheduler.state_dict(); candidate['scaler']=None
    candidate['evaluation']=None; candidate['last_promotion']=None; candidate['anchor']=None
    candidate['curriculum']={'stage':'adaptation-candidate','promotion_requires_independent_evaluation':True}
    candidate['sampler']={'boundary':'no active lobbies; old environment not migrated',
        'next_training_seed':saved['config']['seed']+saved['counters']['attempted_games']}
    if new_rules_path is not None: candidate['config']['rules_path']=str(Path(new_rules_path).resolve())
    report={'kind':kind,'source':str(source),'source_sha256':original_sha,'candidate':str(destination),
        'policy_ast_proof':proof,'identity_rows_reused':len(reused),'new_stable_ids':added,
        'removed_stable_ids':sorted(set(old_ids)-set(new_ids)),'shared_parameters_preserved':shared,
        'optimizer':'explicit reset; no old moments migrated','old_environment_migrated':False,
        'promoted':False,'independent_evaluation_passed':False,'bug_recovery_proved':False,
        'old_binding':saved['binding'],'new_binding':binding,
        'destination_authority':'caller must supply reviewed qualified catalog/binding; migration does not certify rules'}
    candidate['migration']=report
    candidate['versions']['migration_code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    destination.parent.mkdir(parents=True,exist_ok=True); temporary=destination.with_suffix('.tmp')
    with temporary.open('xb') as stream: torch.save(candidate,stream); stream.flush(); os.fsync(stream.fileno())
    if hashlib.sha256(source.read_bytes()).hexdigest()!=original_sha:
        temporary.unlink(); raise ValueError('source changed during migration')
    os.replace(temporary,destination)
    return report
