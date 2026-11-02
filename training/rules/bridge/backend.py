"""Independent upstream-baseline candidate. Private snapshots are NEVER policy input."""
from pathlib import Path
import copy as _copy
import hashlib,json,struct,threading,uuid,sys,functools

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'runtime'))
import taverngym as tg
SCHEMA='bg-new-rule-backend-v7-current9-roster'
COMMIT='fb61201a557ddd36a411cf44aac51ce4d9b606ce'
TREE='c40b8465ce85f3e678a3a03e09d8b18fc04e6c03'
PYD_SHA='BUILD_REQUIRED'
SOURCE_HASH='13d71ac51a979679'
PATCH_SHA='15d85cef8c397310164e6d51b496429a5636729056d05a62034a54a09dba237a'
def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode('utf8')).hexdigest()
def file_sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def target_roster_binding(manifest, expected_sha256):
    """Bind an already reviewed external manifest; this verifies bytes, not source authority."""
    if not isinstance(manifest,dict) or manifest.get('source_qualified') is not True:
        raise ContractError('target roster requires an explicit source-qualified declaration')
    actual=digest(manifest)
    if expected_sha256!=actual:raise ContractError('target roster manifest SHA256 mismatch')
    return {'manifest':_copy.deepcopy(manifest),'manifest_sha256':actual}

def _integer(x):return type(x) is int
_LOADED_CODE_SHA=file_sha(__file__)

class ContractError(ValueError):pass

def _atomic_public_operation(fn):
    @functools.wraps(fn)
    def operation(self,*args,**kwargs):
        with self._lock:
            if self._busy:self._reject('reentrant operation rejected')
            before=self._operation_checkpoint()
            try:return fn(self,*args,**kwargs)
            except Exception:
                self._operation_rollback(before)
                self.rejections.append({'revision':getattr(self,'revision',None),'episode_id':getattr(self,'episode_id',None),'reason':fn.__name__+' public-operation failure rolled back'})
                raise
    return operation

def build_binding():
    dep=json.loads((HERE/'BUILD_DEPENDENCY.json').read_text('utf8'))
    info=tg.build_info()
    package_path=(HERE/dep['package']).resolve();extension_path=(HERE/dep['extension']).resolve()
    if Path(sys.executable).resolve()!=Path(dep['python']).resolve():raise ContractError('native interpreter mismatch')
    if file_sha(__file__)!=_LOADED_CODE_SHA:raise ContractError('loaded backend source changed')
    if (Path(info['file']).resolve()!=extension_path or
        file_sha(info['file'])!=PYD_SHA or info['source_hash']!=SOURCE_HASH or info['profile']!='release'):
        raise ContractError('native build mismatch')
    lock=json.loads((HERE/'SOURCE_LOCK.json').read_text('utf8'))
    if lock['commit']!=COMMIT or lock['tree']!=TREE:raise ContractError('source lock mismatch')
    package_expected=next(r['sha256'] for r in lock['files'] if r['path'].replace('\\','/')=='python/taverngym/__init__.py')
    if Path(tg.__file__).resolve()!=package_path or file_sha(package_path)!=package_expected:raise ContractError('native package mismatch')
    variant=json.loads((HERE/'SOURCE_VARIANT.json').read_text('utf8'))
    if (file_sha(HERE.parent/'BULK30_COMBINED.patch')!=PATCH_SHA or variant['patch_SHA256']!=PATCH_SHA or
        variant['source_hash']!=SOURCE_HASH or tg.source_hash(HERE/variant['source_root'])!=SOURCE_HASH):raise ContractError('source variant mismatch')
    return {'schema':SCHEMA,'commit':COMMIT,'tree':TREE,'source_hash':SOURCE_HASH,
            'extension_SHA':PYD_SHA,'target_overrides_SHA':file_sha(HERE.parent/'TARGET_OVERRIDES.json'),'wave_ledger_SHA':file_sha(HERE.parent/'IDENTITY_LEDGER30.json'),'named_target_roster_binding_SHA':file_sha(HERE.parent/'TARGET_ROSTER_BINDING.json'),'conditional_source_sidecar_SHA':file_sha(HERE.parent/'CONDITIONAL_RELATION_PROVENANCE.json'),'profile':'release','source_lock_SHA':file_sha(HERE/'SOURCE_LOCK.json'),
            'native_package_SHA':file_sha(package_path),'source_variant_SHA':file_sha(HERE/'SOURCE_VARIANT.json'),'patch_SHA':PATCH_SHA,
            'card_table_file_SHA':variant['source_files']['crates/taverngym/data/cards.json'],
            'backend_SHA':file_sha(__file__),'API_SHA':file_sha(HERE/'API_CONTRACT.json'),
            'target_cross_table_SHA':file_sha(HERE/'TARGET_CROSS_TABLE.json'),
            'policy_SHA':file_sha(HERE/'POLICY.json'),'layout_SHA':digest(tg.layout()),'action_names_SHA':digest([tg.action_name(i) for i in range(245)])}

class Backend:
    def __init__(self,seed=7,config=None,controls=None,episode_id=None,*,policy_id='700-upstream-provisional-v1'):
        self._lock=threading.RLock();self._busy=False;self._g=None
        self._binding=build_binding();self.policy_id=policy_id
        if policy_id!='700-upstream-provisional-v1':raise ContractError('unqualified policy; strict37 not supported')
        defaults=json.loads(tg.default_config_json())
        config={} if config is None else _copy.deepcopy(config)
        if not isinstance(config,dict) or set(config)-(set(defaults)|{'target_roster'}):raise ContractError('unknown config')
        if config.get('target_roster') is not None:
            roster=config['target_roster']
            if not isinstance(roster,dict) or set(roster)!={'manifest','manifest_sha256'}:raise ContractError('invalid target roster binding')
            config['target_roster']=target_roster_binding(roster['manifest'],roster['manifest_sha256'])
        elif 'target_roster' in config:
            del config['target_roster']
        self._config={**defaults,**config}
        if self._config['content']!='Implemented':raise ContractError('AllVanilla/non-Implemented content is not a rule candidate')
        n=self._config['num_players']
        self.controls=tuple(range(n)) if controls is None else tuple(controls)
        if any(not _integer(x) for x in self.controls) or sorted(self.controls)!=list(range(n)):
            raise ContractError('controls must be a complete ordered seat permutation; subset and Batch unsupported')
        self.rejections=[];self.terminal_history=[];self._terminal=None
        self.reset(seed,episode_id)

    def _raw(self):return self._g.state_json()
    def _state(self):return json.loads(self._raw())
    def _operation_checkpoint(self):
        fields=('seed','episode_id','_public_episode_id','revision','_last_seat','_terminal','terminal_history')
        return {'raw':None if self._g is None else self._raw(),'fields':{name:_copy.deepcopy(getattr(self,name)) for name in fields if hasattr(self,name)},'field_names':fields}
    def _operation_rollback(self,before):
        self._g=None if before['raw'] is None else tg.Game.from_json(before['raw'])
        if before['raw'] is not None and self._raw()!=before['raw']:raise RuntimeError('public-operation native rollback not exact')
        for name in before['field_names']:
            if name in before['fields']:setattr(self,name,_copy.deepcopy(before['fields'][name]))
            elif hasattr(self,name):delattr(self,name)
    def _enter(self):
        if self._busy:self._reject('reentrant operation rejected')
        self._busy=True
    def _reject(self,reason):
        self.rejections.append({'revision':getattr(self,'revision',None),'episode_id':getattr(self,'episode_id',None),'reason':reason})
        raise ContractError(reason)
    def _diag(self):
        turncap=bool(self._g.turn_limit_end);combats=int(self._g.truncated_combats);over=bool(self._g.is_over())
        native_stop=self._state().get('stopped_reason')
        truncated=turncap or combats>0 or native_stop is not None
        done=over or truncated
        reason='max_turns' if turncap else 'combat_guard' if combats else str(native_stop) if native_stop is not None else 'normal_elimination' if over else 'running'
        return {'done':done,'terminated':over and not truncated,'truncated':truncated,'stop_reason':reason,
                'turn':int(self._g.turn),'turn_limit_end':turncap,'truncated_combats':combats,
                'placements':list(self._g.placements()) if over else None,
                'source_rules':'36.6.3.253932','target_rules_complete':False,'policy_id':self.policy_id,'700_contract_verified':False,'strict37_rules_complete':False}
    def _seat(self):
        if self._diag()['done']:return None
        return next((p for p in self.controls if self._g.needs_action(p)),None)
    def _token(self):
        # Includes exact native entity/option/PRNG snapshot; only an opaque digest leaves the driver.
        return digest({'native':self._raw(),'revision':self.revision,'episode':self.episode_id,
                       'controls':self.controls,'binding':self._binding,'seed':self.seed})

    @_atomic_public_operation
    def reset(self,seed,episode_id=None,force=False):
        with self._lock:
            self._enter()
            try:
                if not _integer(seed) or not 0<=seed<2**64:self._reject('invalid seed')
                ep=str(uuid.uuid4()) if episode_id is None else episode_id
                if not isinstance(ep,str) or not ep:self._reject('invalid episode')
                if self._g is not None:
                    if not self._diag()['done'] and not force:self._reject('active reset requires force')
                    if not self._diag()['done']:
                        self.terminal_history.append({'diagnostics':{'stop_reason':'explicit_abandonment','truncated':True},'private_snapshot':self._snapshot()})
                    elif self._terminal:self.terminal_history.append(_copy.deepcopy(self._terminal))
                g=tg.Game(seed,config_json=canonical(self._config))
                if json.loads(g.state_json())['cfg']!=self._config:self._reject('native config mismatch')
                self._g=g;self.seed=seed;self.episode_id=ep;self._public_episode_id=uuid.uuid4().hex;self.revision=0;self._last_seat=self.controls[0];self._terminal=None
                self._capture_terminal();return self._observe()
            finally:self._busy=False

    def _observe(self,seat=None):
        current=self._seat();p=(self._last_seat if current is None else current) if seat is None else seat
        if not _integer(p) or p not in self.controls:self._reject('invalid observer seat')
        floats,cards=self._g.observe(p)
        features=list(struct.unpack('<'+str(len(floats)//4)+'f',floats));card_ids=list(struct.unpack('<'+str(len(cards)//4)+'i',cards))
        mask=list(self._g.legal_mask(p)) if p==current else [0]*245
        if (len(features),len(card_ids),len(mask))!=(3227,124,245):raise ContractError('numeric schema drift')
        return {'schema':SCHEMA,'seat':p,'current_seat':current,'episode_id':self._public_episode_id,'revision':self.revision,
                'features':features,'cards':card_ids,'action_mask':mask,'diagnostics':self._diag(),
                'knowledge':{'source':'native numeric player observation','opponents':'native historically seen/public projection; unexposed information not supplied','entitlement_audit':'bounded B/C evidence only; full37 audit open'}}
    def observe(self,seat=None):
        with self._lock:
            if self._busy:self._reject('reentrant observation rejected')
            return self._observe(seat)
    def _tickets(self):
        p=self._seat()
        if p is None:return []
        token=self._token()
        return [{'index':i,'name':tg.action_name(i),'seat':p,'revision':self.revision,
                 'episode_id':self._public_episode_id,'token':token} for i,v in enumerate(self._g.legal_mask(p)) if v]
    def legal_actions(self):
        with self._lock:
            if self._busy:self._reject('reentrant actions rejected')
            return self._tickets()

    @_atomic_public_operation
    def step(self,ticket):
        with self._lock:
            self._enter()
            try:
                if not isinstance(ticket,dict) or set(ticket)!={'index','name','seat','revision','episode_id','token'}:
                    self._reject('invalid ticket schema')
                if not all(_integer(ticket[k]) for k in ('index','seat','revision')):self._reject('invalid ticket scalar')
                if ticket not in self._tickets():self._reject('illegal stale foreign or wrong-seat ticket')
                before=self._raw();rev=self.revision
                try:self._g.step(ticket['seat'],ticket['index'])
                except Exception as ex:
                    self._g=tg.Game.from_json(before)
                    if self._raw()!=before:raise RuntimeError('native rollback failed') from ex
                    self.revision=rev;self._reject('native step failure rolled back')
                self.revision+=1;self._last_seat=ticket['seat'];self._capture_terminal()
                return self._observe()
            finally:self._busy=False

    def _snapshot(self):
        raw=self._raw();state=json.loads(raw)
        payload={'schema':SCHEMA,'policy_id':self.policy_id,'binding':self._binding,'config':self._config,'config_SHA':digest(self._config),
                 'controls':list(self.controls),'controls_SHA':digest(self.controls),'seed':self.seed,'episode_id':self.episode_id,
                 'revision':self.revision,'public_episode_id':self._public_episode_id,'last_seat':self._last_seat,'card_table':state['card_table'],
                 'native_raw':raw,'native_raw_SHA':hashlib.sha256(raw.encode()).hexdigest()}
        return {'payload':_copy.deepcopy(payload),'checksum':digest(payload)}
    def snapshot(self):
        with self._lock:
            if self._busy:self._reject('reentrant snapshot rejected')
            return self._snapshot()
    @_atomic_public_operation
    def restore(self,envelope):
        with self._lock:
            self._enter()
            try:
                if not isinstance(envelope,dict) or set(envelope)!={'payload','checksum'}:self._reject('foreign snapshot envelope')
                p=_copy.deepcopy(envelope['payload'])
                expected={'schema','policy_id','binding','config','config_SHA','controls','controls_SHA','seed','episode_id','revision','public_episode_id','last_seat','card_table','native_raw','native_raw_SHA'}
                if not isinstance(p,dict) or set(p)!=expected or envelope['checksum']!=digest(p):self._reject('snapshot checksum/schema mismatch')
                if p['policy_id']!=self.policy_id:self._reject('snapshot policy mismatch')
                if p['schema']!=SCHEMA or p['binding']!=self._binding:self._reject('snapshot build/version mismatch')
                if canonical(p['config'])!=canonical(self._config) or p['config_SHA']!=digest(self._config):self._reject('snapshot config mismatch')
                if type(p['controls']) is not list or any(not _integer(x) for x in p['controls']) or p['controls']!=list(self.controls) or p['controls_SHA']!=digest(self.controls):self._reject('snapshot seat-order mismatch')
                if type(p['seed']) is not int or p['seed']!=self.seed or p['episode_id']!=self.episode_id:self._reject('snapshot seed/episode mismatch')
                if not _integer(p['revision']) or p['revision']<0 or not _integer(p['last_seat']) or p['last_seat'] not in self.controls:self._reject('snapshot revision/seat mismatch')
                if not isinstance(p['public_episode_id'],str) or len(p['public_episode_id'])!=32 or any(c not in '0123456789abcdef' for c in p['public_episode_id']):self._reject('invalid public episode identity')
                raw=p['native_raw']
                if not isinstance(raw,str) or p['native_raw_SHA']!=hashlib.sha256(raw.encode()).hexdigest():self._reject('native raw digest mismatch')
                state=json.loads(raw)
                if (not p['card_table'] or p['card_table']!=self._state()['card_table'] or state.get('card_table')!=p['card_table'] or
                    canonical(state.get('cfg'))!=canonical(self._config) or type(state.get('seed')) is not int or state['seed']!=self.seed):self._reject('native identity/config mismatch')
                players=state.get('players')
                if not isinstance(players,list) or len(players)!=len(self.controls) or any(type(x.get('id')) is not int or x['id']!=i for i,x in enumerate(players)):
                    self._reject('native player identity/order mismatch')
                try:g=tg.Game.from_json(raw)
                except Exception:self._reject('native snapshot rejected')
                if g.state_json()!=raw:self._reject('native snapshot not exact canonical raw')
                self._g=g;self.revision=p['revision'];self._public_episode_id=p['public_episode_id'];self._last_seat=p['last_seat'];self._terminal=None
                self._capture_terminal();return self._observe()
            except ContractError:raise
            except (ValueError,TypeError,KeyError,OverflowError):self._reject('malformed snapshot rejected')
            finally:self._busy=False
    def copy(self):
        with self._lock:
            if self._busy:self._reject('reentrant copy rejected')
            envelope=self._snapshot()
            clone=Backend(self.seed,self._config,self.controls,self.episode_id);clone.restore(envelope)
            if clone.snapshot()!=envelope:raise RuntimeError('copy envelope divergence')
            return clone
    def _capture_terminal(self):
        if self._diag()['done'] and self._terminal is None:
            self._terminal={'diagnostics':self._diag(),'observation':self._observe(self._last_seat),'private_snapshot':self._snapshot()}
    def terminal_record(self):
        with self._lock:
            if self._busy:self._reject('reentrant terminal read rejected')
            return _copy.deepcopy(self._terminal)
    def qualification_report(self,required_ids=None):
        ids=[] if required_ids is None else list(required_ids)
        return {'source_rules':'36.6.3.253932','target_rules':'37.0.0.255130','strict37_qualified':False,'active_target_roster':None if self._config.get('target_roster') is None else {'ruleset_id':self._config['target_roster']['manifest']['ruleset_id'],'manifest_sha256':self._config['target_roster']['manifest_sha256'],'offering_contract_only':True},'policy_id':self.policy_id,'requested_ids':ids,'unresolved':['exact37 server roster/weights','unreviewed target behavior','D03 natural acquisition/awakening qualification']+(['700 target/live/cancel/payment/distribution/golden-body'] if any(c in ('BG36_700','BG36_700_G') for c in ids) else []),'IDs_silently_dropped':[]}
    def require_qualification(self,target_rules,required_ids=None):
        with self._lock:self._reject('strict target qualification unavailable: '+canonical(self.qualification_report(required_ids)))
    def reject_legacy_model(self,metadata):
        with self._lock:self._reject('model loading/migration unsupported; foreign metadata rejected')

class BatchBackend:
    def __init__(self,*args,**kwargs):raise NotImplementedError('Batch backend not in v1; use explicit Game Backend')
