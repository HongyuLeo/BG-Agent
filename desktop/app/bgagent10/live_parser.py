"""Incremental, byte-proven public Power.log state, one logical stream only.

Zero-default policy: omitted numeric scalar tags are zero only on entities whose
complete FULL/SHOW creation was seen within this CREATE_GAME. Composite counters
are never inferred from omitted scalar tags. Named player aliases remain local
to the parser and are not included in model/history output.
"""
from __future__ import annotations
import hashlib
import re
import time

REF=re.compile(r'\bid=(\d+)\b')
FULL=re.compile(r'FULL_ENTITY - (?:Creating ID=(\d+)|Updating (.+?)) CardID=(\S*)')
SHOW=re.compile(r'(?:SHOW_ENTITY|CHANGE_ENTITY) - Updating Entity=(.+?) CardID=(\S*)')
TAG=re.compile(r'TAG_CHANGE Entity=(.+?) tag=(\S+) value=(\S*)')
DETAIL=re.compile(r'(?:^|\s)tag=(\S+) value=(\S*)')
OPTION=re.compile(r'\boption (\d+) type=(\S+) mainEntity=(.*?) error=(\S+)(?: errorParam=|\s*$)')
SUB=re.compile(r'\bsubOption (\d+) (?:type=(\S+) )?(?:mainEntity|entity)=(.*?) error=(\S+)')
TARGET=re.compile(r'\btarget (\d+) entity=(.*?) error=(\S+)')
FORBIDDEN_TAGS={'GAME_SEED','RANDOM_SEED'}


def known(value,source,basis='explicit_log'):return {'value':value,'known':True,'source':source,'basis':basis}
def unknown(reason):return {'value':None,'known':False,'source':'unknown','basis':reason}


class PowerLedger:
    def __init__(self):
        self.offset=0;self.partial=b'';self.source=None;self.games=[];self.file_build=None;self.file_build_source=None;self.reset()
    def reset(self):
        self.entities={};self.players={};self.aliases={};self.game=None;self.game_key=None;self.saw_create=False;self.create_proof=None
        self.pending=None;self.options=[];self.current_option=None;self.target_owner=None;self.option_batch=None;self.options_complete=False;self.collecting=False
        self.choice=None;self.choice_entities=[];self.choice_source=None;self.choice_owner=None;self.choice_complete=False;self.choice_collecting=False;self.observer=None;self.observer_conflict=False
        self.shop_controller=None;self.revision=0;self.receipts=[];self.history=[];self.blocks=0;self.block_cards=[];self.build=self.file_build;self.build_source=self.file_build_source;self.game_type=None
        self.last_line_at=0.;self.last_proof=None;self.events=[];self.combat_boundary=None;self.public_names={}
    def entity(self,eid):return self.entities.setdefault(eid,{'id':eid,'tags':{},'card_id':unknown('unrevealed identity'),'identity_authoritative':False,'complete':False,'created':None})
    def ref(self,text):
        text=text.strip()
        if text.isdigit():return int(text)
        m=REF.search(text)
        if m:
            eid=int(m[1]);row=self.entity(eid)
            for key,tag in [('player','CONTROLLER'),('zone','ZONE'),('zonePos','ZONE_POSITION')]:
                if x:=re.search(r'\b'+key+r'=([^\s\]]*)',text):row['tags'].setdefault(tag,known(x[1],self.last_proof,'embedded_reference'))
            if (x:=re.search(r'\bcardId=([^\s\]]*)',text)) and x[1] and not row['identity_authoritative']:row['card_id']=known(x[1],self.last_proof,'embedded_public_reference')
            if (x:=re.search(r'\bcardId=([^\s\]]*)',text)) and x[1] and not row['card_id']['known']:row['card_id']=known(x[1],self.last_proof,'embedded_reference')
            return eid
        if text=='GameEntity':return self.game
        return self.aliases.get(text)
    def scalar(self,eid,key,default_zero=False):
        row=self.entities.get(eid)
        if not row:return unknown('entity not observed')
        leaf=row['tags'].get(key)
        if leaf:
            try:return dict(leaf,value=int(leaf['value']))
            except (ValueError,TypeError):return dict(leaf)
        if default_zero and row['complete'] and self.saw_create:return known(0,row['created'],'protocol_omitted_numeric_scalar_zero')
        return unknown('tag not observed:'+key)
    def val(self,eid,key,default=None):
        leaf=self.scalar(eid,key)
        return leaf['value'] if leaf['known'] else default
    def bind_observer(self,pid,proof):
        if pid not in self.players:return
        if self.observer is not None and self.observer!=pid:self.observer_conflict=True
        self.observer=pid
    def feed(self,raw,offset=None,source='Power.log',eof=False):
        if isinstance(raw,str):raw=raw.encode('utf8')
        if self.source is not None and source!=self.source:
            self.file_build=None;self.file_build_source=None;self.reset();self.offset=0;self.partial=b''
        self.source=source
        if offset is not None and offset!=self.offset:
            if self.partial:raise ValueError('noncontiguous byte range with partial line')
            self.offset=offset
        data=self.partial+raw;start=self.offset-len(self.partial);self.offset+=len(raw)
        lines=data.splitlines(keepends=True);self.partial=b''
        if lines and not lines[-1].endswith((b'\n',b'\r')):self.partial=lines.pop()
        for line in lines:
            proof={'path':source,'offset':start,'length':len(line),'sha256':hashlib.sha256(line).hexdigest()};start+=len(line)
            self.line(line.decode('utf8',errors='replace').rstrip('\r\n'),proof)
        if eof and not self.partial:self.seal_options()
    def seal_options(self):
        self.seal_choice()
        if self.collecting and self.options and [o['index'] for o in self.options]==list(range(len(self.options))):
            self.options_complete=True;self.collecting=False
    def seal_choice(self):
        if self.choice_collecting and self.choice:
            indices=[x['index'] for x in self.choice_entities]
            self.choice_complete=bool(indices) and indices==list(range(len(indices))) and len(indices)>=self.choice['count_min']
            self.choice_collecting=False
    def line(self,text,proof):
        if 'PowerTaskList.DebugPrintPower()' in text:return
        self.last_proof=proof;self.last_line_at=time.monotonic()
        if 'GameState.DebugPrintPower()' in text and 'CREATE_GAME' in text:
            if self.game_key:self.games.append({'game_key':self.game_key,'game_type':self.game_type,'build':self.build})
            self.reset();self.last_proof=proof;self.saw_create=True;self.create_proof=proof;self.game_key=hashlib.sha256((str(proof['path'])+':'+str(proof['offset'])+':'+proof['sha256']).encode()).hexdigest()
        self.revision+=1
        if m:=re.search(r'BuildNumber=(\d+)',text):self.build=self.file_build=int(m[1]);self.build_source=self.file_build_source=proof
        if m:=re.search(r'GameType=(\w+)',text):self.game_type=m[1]
        if m:=re.search(r'DebugPrintGame\(\).*?PlayerID=(\d+), PlayerName=(.+?)\s*$',text):
            self.aliases[m[2]]=self.players.get(int(m[1]))
        is_option='DebugPrintOptions()' in text
        if self.collecting and not is_option:self.seal_options()
        if self.choice_collecting and 'DebugPrintEntityChoices()' not in text:self.seal_choice()
        if m:=re.search(r'GameEntity EntityID=(\d+)',text):
            self.game=self.pending=int(m[1]);row=self.entity(self.pending);row.update(complete=self.saw_create,created=proof)
        elif m:=re.search(r'Player EntityID=(\d+) PlayerID=(\d+)',text):
            eid,pid=map(int,m.groups());self.players[pid]=eid;self.pending=eid;self.entity(eid).update(complete=self.saw_create,created=proof)
        elif m:=FULL.search(text):
            eid=int(m[1]) if m[1] else self.ref(m[2]);self.pending=eid
            if eid is not None:self.entity(eid).update(card_id=known(m[3],proof) if m[3] else unknown('FULL_ENTITY unrevealed CardID'),identity_authoritative=True,complete=self.saw_create,created=proof)
        elif m:=SHOW.search(text):
            eid=self.ref(m[1]);self.pending=eid
            if eid is not None:
                # SHOW reveals a new authoritative tag set; old transformed
                # attributes must not silently survive CHANGE_ENTITY.
                if 'CHANGE_ENTITY' in text:self.entity(eid)['tags']={}
                self.entity(eid).update(card_id=known(m[2],proof) if m[2] else unknown('SHOW_ENTITY unrevealed CardID'),identity_authoritative=True,complete=self.saw_create,created=proof)
        elif m:=TAG.search(text):
            eid=self.ref(m[1]);self.pending=None
            if eid is None and m[2]=='BACON_CURRENT_COMBAT_PLAYER_ID' and self.game_type in ('GT_BATTLEGROUNDS','GT_BATTLEGROUNDS_FRIENDLY'):
                # During combat the Bob network player is renamed to the
                # opponent's bare display name. This Player-only tag provides
                # explicit seat linkage, not an assumed controller number.
                merchants={self.val(e,'CONTROLLER') for e,row in self.entities.items() if row['card_id'].get('value')=='TB_BaconShopBob' or str(row['card_id'].get('value','')).startswith('TB_BaconShopBob_SKIN_')}
                merchants.discard(None)
                try:combat_seat=int(m[3])
                except ValueError:combat_seat=-1
                own_player=self.players.get(self.observer)
                own_combat=self.val(own_player,'BACON_CURRENT_COMBAT_PLAYER_ID')
                expected={self.val(e,'NEXT_OPPONENT_PLAYER_ID') for e in (own_player,self.val(own_player,'HERO_ENTITY'),self.game)}
                if len(merchants)==1 and self.observer is not None and own_combat==self.observer and combat_seat in expected and combat_seat in range(1,9) and combat_seat!=self.observer:
                    bob=next(iter(merchants));eid=self.players.get(bob)
                    if eid is not None:self.aliases[m[1].strip()]=eid
            if eid is not None and m[2] not in FORBIDDEN_TAGS:
                row=self.entity(eid);old=row['tags'].get(m[2]);row['tags'][m[2]]=known(m[3],proof)
                self.events.append({'kind':'tag','entity_id':eid,'tag':m[2],'old':old,'value':m[3],'source':proof})
        elif 'HIDE_ENTITY' in text:
            m=re.search(r'Entity=(.+?)(?: tag=|$)',text);eid=self.ref(m[1]) if m else None
            if eid is not None:self.entity(eid).update(card_id=unknown('HIDE_ENTITY'),identity_authoritative=True)
            self.pending=None
        elif (m:=DETAIL.search(text)) and self.pending is not None:
            if m[1] not in FORBIDDEN_TAGS:self.entity(self.pending)['tags'][m[1]]=known(m[2],proof)
        else:self.pending=None
        if 'BLOCK_START' in text:
            self.blocks+=1
            block_ref=re.search(r' Entity=(.+?) EffectCardId=',text);block_entity=self.ref(block_ref[1]) if block_ref else None
            self.block_cards.append(self.entity(block_entity)['card_id'].get('value') if block_entity is not None else None)
        if 'BLOCK_END' in text:
            self.blocks=max(0,self.blocks-1)
            if self.block_cards:self.block_cards.pop()
        if is_option:
            if m:=re.search(r' - id=(\d+)\s*$',text):
                self.options=[];self.current_option=None;self.option_batch=int(m[1]);self.options_complete=False;self.collecting=True;self.blocks=0
            elif m:=OPTION.search(text):
                row={'index':int(m[1]),'type':m[2],'entity_id':self.ref(m[3]),'error':m[4],'targets':[],'suboptions':[],'source':proof};self.options.append(row);self.current_option=self.target_owner=row
                cid=self.entity(row['entity_id'])['card_id']['value'] if row['entity_id'] is not None else None
                if cid in ('TB_BaconShop_8p_Reroll_Button','TB_BaconShopLockAll_Button') and row['error']=='NONE':self.bind_observer(self.val(row['entity_id'],'CONTROLLER'),proof)
            elif (m:=SUB.search(text)) and self.current_option:
                row={'index':int(m[1]),'type':m[2],'entity_id':self.ref(m[3]),'error':m[4],'targets':[],'source':proof};self.current_option['suboptions'].append(row);self.target_owner=row
            elif (m:=TARGET.search(text)) and self.target_owner is not None:self.target_owner['targets'].append({'index':int(m[1]),'entity_id':self.ref(m[2]),'error':m[3],'source':proof})
        if 'DebugPrintEntityChoices()' in text:
            if m:=re.search(r'id=(\d+) Player=(.+?) TaskList=\S+ ChoiceType=(\S+) CountMin=(\d+) CountMax=(\d+)',text):
                self.choice={'id':int(m[1]),'type':m[3],'count_min':int(m[4]),'count_max':int(m[5]),'source':proof};self.choice_entities=[];self.choice_source=None;self.choice_owner=None;self.choice_complete=False;self.choice_collecting=True;self.options_complete=False;self.blocks=0
                owner=self.ref(m[2]);self.choice_owner=next((p for p,e in self.players.items() if e==owner),None)
            elif m:=re.search(r'Source=(.+)',text):self.choice_source=self.ref(m[1])
            elif m:=re.search(r'Entities\[(\d+)\]=(.+)',text):
                eid=self.ref(m[2]);self.choice_entities.append({'index':int(m[1]),'entity_id':eid,'source':proof})
                owners={self.val(x['entity_id'],'CONTROLLER') for x in self.choice_entities}
                if len(owners)==1 and self.choice and self.choice['type']=='MULLIGAN' and self.choice['count_min']==self.choice['count_max']==1:self.choice_owner=next(iter(owners))
                if self.choice_owner:self.bind_observer(self.choice_owner,proof)
        if m:=re.search(r'SendOption\(\).*?selectedOption=(\d+).*?selectedSubOption=(-?\d+).*?selectedTarget=(-?\d+).*?selectedPosition=(-?\d+)',text):
            receipt=dict(zip(('index','sub','target','position'),map(int,m.groups())),source=proof,serial=len(self.receipts)+1)
            option=next((o for o in self.options if o['index']==receipt['index']),None)
            eid=option['entity_id'] if option else None;cid=self.entity(eid)['card_id']['value'] if eid is not None else None
            kind='power' if self.val(eid,'CARDTYPE') in ('HERO_POWER','10') else 'option'
            self.receipts.append(receipt);self.history.append({'kind':kind,'slot':self.val(eid,'ADDITIONAL_HERO_POWER_INDEX',0) if kind=='power' else None,'card_id':cid,'turn':self.val(self.game,'TURN'),'index':receipt['index'],'sub':receipt['sub'],'target_entity':receipt['target'],'position':receipt['position'],'source':proof});self.options_complete=False
        if 'DebugPrintEntitiesChosen()' in text and re.search(r' - id=\d+',text):
            chosen_id=int(re.search(r' - id=(\d+)',text)[1]);count=re.search(r'EntitiesCount=(\d+)',text)
            self.receipts.append({'kind':'choice','choice_id':chosen_id,'entities':[],'count':int(count[1]) if count else None,'complete':False,'source':proof,'serial':len(self.receipts)+1})
            self.history.append({'kind':'choice','pending_id':self.choice['id'] if self.choice else None,'source':proof});self.choice=None;self.choice_entities=[];self.options_complete=False
        elif 'DebugPrintEntitiesChosen()' in text and (m:=re.search(r'Entities\[(\d+)\]=(.+)',text)):
            if self.receipts and self.receipts[-1].get('kind')=='choice':
                receipt=self.receipts[-1];eid=self.ref(m[2])
                if eid is not None:receipt['entities'].append(eid);receipt['complete']=len(receipt['entities'])==receipt['count']
        if 'SendChoices()' in text:self.options_complete=False
        if getattr(self,'event_hook',None):self.event_hook(text)
    def all_tags(self):return {t for e in self.entities.values() for t in e['tags']}
