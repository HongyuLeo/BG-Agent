"""Public Power.log -> versioned 3227/124 facts and 245 staged commands.

The native training observation has composite counters that do not all have a
public Power.log tag. Initial counters use the pinned Player::new/Default rules,
not an unknown-zero fill. Affected counters are invalidated on unbound effects.
External public UI facts (not hidden snapshots) can provide missing lobby types
or explicitly read counters with their own evidence. Every leaf has provenance.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import re
from .live_parser import PowerLedger,known,unknown
from .live_encoding import GLOBAL_NAMES,RACES,KEYWORDS,MINION_NAMES,OPP_NAMES,CARD_GROUPS,encode_public,IncompleteObservation,decode_action
from .engine import DEFAULT_RULES
from .live_queue import PublicHandQueueGuard

SOURCE_DEFAULTS='frozen source/state.rs Player::new + PlayerStats::default; source/obs.rs padding and public masking'
SCALAR_DEFAULTS='complete CREATE_GAME + authoritative FULL/SHOW; omitted scalar tags have protocol numeric zero (legacy public parser contract)'
GLOBAL_DIRECT={
 'free_refreshes':['BACON_FREE_REFRESH_COUNT'], 'spell_attack':['TAVERN_SPELL_ATTACK_INCREASE'],
 'spell_health':['TAVERN_SPELL_HEALTH_INCREASE'], 'gem_attack':['BLOOD_GEM_ATTACK_INCREASE'],
 'gem_health':['BLOOD_GEM_HEALTH_INCREASE'], 'deity_attack':['BACON_OLD_GOD_ATTACK'],
 'deity_health':['BACON_OLD_GOD_HEALTH'], 'won_last':['BACON_WON_LAST_COMBAT'],
 'lost_last':['BACON_DIED_LAST_COMBAT'], 'max_gold_bonus':['MAXRESOURCES_BONUS'],
 'gold_next_turn':['EXTRA_MANA_NEXT_TURN'], 'chronum':['CHRONUM'],
 'tavern_attack':['TAVERN_MINION_ATTACK_INCREASE'], 'tavern_health':['TAVERN_MINION_HEALTH_INCREASE'],
}
RACE_ENUM={20:'BEAST',15:'DEMON',24:'DRAGON',18:'ELEMENTAL',17:'MECHANICAL',14:'MURLOC',23:'PIRATE',43:'QUILBOAR',11:'UNDEAD',126:'ABERRATION',92:'NAGA'}


def numeric(leaf):return leaf.get('value') if leaf and leaf.get('known') else None
def derived(value,*sources,basis='public_derivation'):
    if any(not s.get('known') for s in sources):return unknown('dependency missing: '+','.join(s.get('basis','') for s in sources if not s.get('known')))
    return known(value,[s['source'] for s in sources],basis)


class PublicLogProducer:
    def __init__(self,rules_path=None,card_mapping=None,installed_client_build=None):
        self.rules_path=Path(rules_path or DEFAULT_RULES);self.ledger=PowerLedger();self.context={};self.context_game=None
        data=json.loads((self.rules_path/'source/crates/taverngym/data/cards.json').read_text('utf8'))['cards']
        self.catalogue={x['id']:x for x in data};self.card_mapping=card_mapping or {c['id']:i for i,c in enumerate(data)}
        self.hand_queue_guard=PublicHandQueueGuard(self.catalogue)
        self.dbf_mapping={c['dbf']:c['id'] for c in data if c.get('dbf')}
        self.installed_client_build=installed_client_build
        self.version_contract={'model_rules_target':'37.0.0.255130','card_data_build':'37.0.0.255130','authorized_client_target':'37.0.0.255790','mapping_policy':'explicit stable CardID/DBF identity; live numeric tags override base stats; unknown identity or unbound changed mechanic blocks; model rules are not restickered'}
        self.catalogue_sha=hashlib.sha256((self.rules_path/'source/crates/taverngym/data/cards.json').read_bytes()).hexdigest()
        self.known_boards={};self.last_combat_pid=None;self.last_phase=None;self.tracked_game=None;self.memory_event_cursor=0
        self.combat_attack_seen=False
        self.combat_prestart_uncertain=False
        self.dynamic_context_revision=None
        self.invalidated_context=set()
        self.ledger.event_hook=self._on_event
    @property
    def offset(self):return self.ledger.offset
    @property
    def entities(self):return self.ledger.entities
    @property
    def players(self):return self.ledger.players
    @property
    def receipts(self):return self.ledger.receipts
    def feed(self,raw,offset=None,source='Power.log',eof=False):
        # Feed line by line so combat history captures the last observed public
        # board at the transition, not the final board of an unrelated opponent.
        if isinstance(raw,str):raw=raw.encode('utf8')
        self.ledger.feed(raw,offset,source,eof)
        if self.tracked_game!=self.ledger.game_key:
            self.known_boards={};self.last_combat_pid=None;self.last_phase=None;self.tracked_game=self.ledger.game_key;self.memory_event_cursor=0
            if self.context_game is not None and self.context_game!=self.ledger.game_key:self.context={};self.context_game=None
        self._update_memory()
    def set_public_context(self,context,game_key=None,source=None):
        """Only known/source leaves; e.g. screenshot-proven full lobby race list.

        Caller provenance remains inspectable. This API cannot assert hidden
        hands/shops/pool/RNG, and does not authenticate the screenshot itself.
        Context may be supplied before CREATE for deterministic public fixtures.
        """
        allowed={'lobby_races','globals','quests','quest_reward_identity','trinkets','secrets','deity','hand_flags','shop_flags','item_data','effects','next_opponent'}
        bad=set(context)-allowed
        if bad:raise ValueError('forbidden public context keys:'+','.join(sorted(bad)))
        def leaves(value):
            if isinstance(value,dict) and 'known' in value:
                if value.get('known') is not True or not value.get('source'):raise ValueError('public context needs explicit positive evidence')
            elif isinstance(value,dict):
                for v in value.values():leaves(v)
            elif isinstance(value,list):
                for v in value:leaves(v)
            else:raise ValueError('public context values must be evidenced leaves')
        leaves(context);self.context.update(copy.deepcopy(context));self.context_game=game_key or self.ledger.game_key
        self.invalidated_context.difference_update(context)
        if set(context)-{'lobby_races','deity'}:self.dynamic_context_revision=self.ledger.revision
    def _on_event(self,text):
        self.hand_queue_guard.observe(self.ledger,text)
        if self.tracked_game!=self.ledger.game_key:
            self.known_boards={};self.last_combat_pid=None;self.last_phase=None;self.tracked_game=self.ledger.game_key;self.combat_attack_seen=False
            if self.context_game is None and self.context and self.ledger.game_key is not None:self.context_game=self.ledger.game_key
            elif self.context_game is not None and self.context_game!=self.ledger.game_key:self.context={};self.context_game=None;self.dynamic_context_revision=None;self.invalidated_context=set()
        if self.dynamic_context_revision is not None and self.ledger.revision>self.dynamic_context_revision and any(x in text for x in ('TAG_CHANGE','FULL_ENTITY','SHOW_ENTITY','CHANGE_ENTITY','SendOption()','DebugPrintEntitiesChosen()')):
            self.invalidated_context.update(k for k in self.context if k not in ('lobby_races','deity'))
            self.context={k:v for k,v in self.context.items() if k in ('lobby_races','deity')};self.dynamic_context_revision=None
        if self._phase()=='combat' and not self.combat_attack_seen and (m:=re.search(r'TAG_CHANGE Entity=(.+?) tag=(ATK|HEALTH|DAMAGE|ZONE) value=',text)):
            eid=self.ledger.ref(m[1]);source=self.ledger.block_cards[-1] if self.ledger.block_cards else None
            if self.ledger.val(eid,'CONTROLLER')==self._shop_controller() and self.ledger.val(eid,'CARDTYPE') in ('MINION','4') and source and source not in ('TB_BaconShop_8P_PlayerE','TB_BaconShop_FXWatcher','Bacon_TagTransferPlayerE'):
                self.combat_prestart_uncertain=True
        if 'BlockType=ATTACK' in text:
            self._update_memory();self.combat_attack_seen=True;return
        if any(x in text for x in ('BACON_IN_COMBAT_PHASE','BACON_CURRENT_COMBAT_PLAYER_ID','FULL_ENTITY','SHOW_ENTITY','TAG_CHANGE','BLOCK_START')):
            self._update_memory()
    def _default(self,value,reason=SOURCE_DEFAULTS):
        l=self.ledger
        if not l.saw_create:return unknown('missing complete CREATE_GAME; no initialization defaults')
        return known(value,{'create':l.create_proof,'contract':reason},'rule_initialization_or_schema_padding')
    def _card(self,eid):
        leaf=self.entities.get(eid,{}).get('card_id',unknown('missing entity identity'))
        if numeric(leaf) and numeric(leaf) not in self.catalogue:
            parent=self.ledger.scalar(eid,'BACON_SKIN_PARENT_ID')
            if numeric(parent) in self.dbf_mapping:return derived(self.dbf_mapping[numeric(parent)],leaf,parent,basis='explicit cosmetic skin parent DBF identity mapping')
        return leaf
    def _tag(self,eid,key,zero=True):return self.ledger.scalar(eid,key,default_zero=zero)
    def _tag_any(self,entities,names,default=None):
        for eid in entities:
            for name in names:
                leaf=self.ledger.scalar(eid,name)
                if leaf['known']:return leaf
        return default if default is not None else unknown('no public tag '+','.join(names))
    def _rows(self,controller,zone,types=None):
        l=self.ledger;rows=[]
        for eid,row in self.entities.items():
            if l.val(eid,'CONTROLLER')!=controller or l.val(eid,'ZONE') not in (zone,str({'PLAY':1,'HAND':3,'SETASIDE':6}.get(zone,-1))):continue
            if types and l.val(eid,'CARDTYPE') not in types:continue
            rows.append(eid)
        return sorted(rows,key=lambda eid:(l.val(eid,'ZONE_POSITION',0),eid))
    def _hero(self,pid):
        if pid is None:return None
        ref=self.ledger.val(self.players.get(pid),'HERO_ENTITY')
        if ref in self.entities:return ref
        rows=self._rows(pid,'PLAY',('HERO','3'))
        if len(rows)==1:return rows[0]
        panels=[e for e in self.entities if self.ledger.val(e,'PLAYER_ID')==pid and self.ledger.val(e,'CARDTYPE') in ('HERO','3')]
        return panels[-1] if panels else None
    def _playable(self):
        # The live client has two network Player entities (local and Bob).
        # Other lobby seats are public hero panels with PLAYER_ID, not separate
        # network controllers. Solo8 topology is a rule, not eight invented
        # observations: unobserved panel fields stay unknown/masked.
        l=self.ledger
        if l.game_type in ('GT_BATTLEGROUNDS','GT_BATTLEGROUNDS_FRIENDLY') and l.observer in range(1,9):return list(range(1,9))
        return sorted(p for p in self.players if p!=self._shop_controller())
    def _shop_controller(self):
        rows={self.ledger.val(eid,'CONTROLLER') for eid in self.entities if numeric(self._card(eid))=='TB_BaconShopBob' or str(numeric(self._card(eid))).startswith('TB_BaconShopBob_SKIN_')}
        rows.discard(None)
        return next(iter(rows)) if len(rows)==1 else None
    def _phase(self):
        l=self.ledger;pid=l.observer;player=self.players.get(pid);hero=self._hero(pid)
        if l.choice and l.choice['type']=='MULLIGAN' and l.choice['count_min']==l.choice['count_max']==1:return 'hero_select'
        if l.val(l.game,'STATE') in ('COMPLETE','4') or l.val(player,'PLAYSTATE') in ('WON','LOST','QUIT','TIED',4,5,6,8):return 'finished'
        phase=self._tag_any((l.game,hero,player),('BACON_IN_COMBAT_PHASE',))
        if numeric(phase)==1:return 'combat'
        if numeric(phase)==0:return 'recruit'
        if l.options_complete and l.observer is not None and self._shop_controller() is not None:return 'recruit'
        return 'unknown'
    def _minion(self,eid):
        l=self.ledger;cid=self._card(eid);card=self.catalogue.get(numeric(cid));row={}
        row['present']=derived(1,cid)
        for key,tag in [('attack','ATK'),('max_health','HEALTH')]:row[key]=self._tag(eid,tag)
        damage=self._tag(eid,'DAMAGE');hp=row['max_health']
        row['health']=derived(numeric(hp)-numeric(damage),hp,damage) if hp['known'] and damage['known'] else unknown('missing maximum health or damage')
        tier=self._tag(eid,'TECH_LEVEL',False)
        row['tier']=tier if tier['known'] else known(card['tier'],{'catalogue_sha':self.catalogue_sha,'card':numeric(cid)},'frozen_card_attributes') if card else unknown('unmapped minion tier')
        premium=self._tag(eid,'PREMIUM');row['golden']=derived(int(numeric(premium)==1 or bool(card and card.get('normal'))),premium,cid)
        attached=[x for x in self.entities if l.val(x,'ATTACHED')==eid and l.val(x,'MAGNETIC')==1]
        row['attached_count']=self._default(len(attached),'public complete-entity magnetic attachment links; unidentified attachments block below')
        # Additional shield lives are not the boolean DIVINE_SHIELD tag.
        shield=self._tag(eid,'DIVINE_SHIELD')
        row['shield_hits']=derived(int(bool(numeric(shield))),shield,basis='state.rs normal shield has one current hit; absent shield has0')
        extra=self._tag_any((eid,),('DIVINE_SHIELD_EXTRA_LIVES','DIVINE_SHIELD_EXTRA_LIVES_BACON'))
        if extra['known'] and numeric(extra):row['shield_hits']=unknown('extra shield lives tag requires reviewed remaining-lives semantics')
        for key in KEYWORDS:
            tag={'MEGA_WINDFURY':'MEGA_WINDFURY','IMMUNE_ATTACKING':'IMMUNE_WHILE_ATTACKING'}.get(key,key)
            leaf=self._tag(eid,tag);row[key]=derived(int(bool(numeric(leaf))),leaf)
        races=set(card.get('races',[])) if card else set()
        if 'ALL' in races:races=set(RACES)
        explicit=self.ledger.val(eid,'CARDRACE')
        if isinstance(explicit,int) and explicit in RACE_ENUM:races.add(RACE_ENUM[explicit])
        elif isinstance(explicit,int) and explicit not in (0,26):
            for race in RACES:row[race]=unknown('unmapped dynamic CARDRACE:'+str(explicit))
            return row
        for race in RACES:row[race]=known(int(race in races),{'catalogue_sha':self.catalogue_sha,'card':numeric(cid)},'current_card_race_semantics') if card else unknown('unmapped current race')
        return row
    def _item(self,eid,zone,menu_only=False):
        cid=self._card(eid);card=self.catalogue.get(numeric(cid));l=self.ledger
        if menu_only:
            return {**{n:self._default(0) for n in ('is_minion','cost','locked','temporary','combined','frozen','kept','marked')},'present':derived(1,cid),'menu_only':self._default(True)}
        typ=l.val(eid,'CARDTYPE');is_minion=typ in ('MINION',4,'4') or bool(card and card['kind']=='minion')
        zero=self._default(0)
        row={'present':derived(1,cid),'is_minion':derived(int(is_minion),cid),'menu_only':self._default(False),'cost':self._tag(eid,'COST') if zone!='hand' else self._default(0,'obs.rs hand item cost is always0'),'locked':self._tag_any((eid,),('BACON_TURNS_LEFT_TO_ACTIVATE','DORMANT'),zero),'temporary':self._tag_any((eid,),('TEMPORARY','BACON_SPELLCRAFT_TEMPORARY'),zero),'combined':self._tag_any((eid,),('CHOOSE_ONE_COMBINED',),zero),'frozen':self._tag(eid,'FROZEN') if zone=='shop' else self._tag_any((eid,),('BACON_DIES_IF_PLAYED_THIS_TURN',),zero),'kept':self._default(0),'marked':self._tag_any((eid,),('DARKMOON_TICKET',),zero)}
        if is_minion:row['minion']=self._minion(eid)
        else:
            row['spell_data']=self.context.get('item_data',{}).get(str(eid),self._default(0,'ordinary spell payload defaults0; unbound numeric mechanics separately block'))
            payload_cards={'TB_BaconShop_Triples_01','BG24_Reward_134','BG27_Reward_812'}
            if str(eid) not in self.context.get('item_data',{}) and (numeric(cid) in payload_cards or card and card.get('kind')=='dark_gift'):
                row['spell_data']=unknown('data-bearing spell requires sourced per-instance payload; script data tag is not automatically native Item.data')
            row['tier']=known(card['tier'],{'catalogue_sha':self.catalogue_sha,'card':numeric(cid)}) if card else unknown('unmapped spell tier')
        flags=self.context.get('hand_flags' if zone=='hand' else 'shop_flags',{}).get(str(eid),{})
        row.update(flags)
        return row
    def _update_memory(self):
        # Existing events carry phase boundary and current combat-controller
        # updates. Capture only the opponent board explicitly linked to local
        # combat. Never record arbitrary live opponent boards as seen memory.
        l=self.ledger;pid=l.observer
        if pid is None:return
        phase=self._phase()
        shop=self._shop_controller()
        opponent=self._tag_any((self.players.get(shop),self._hero(shop)),('BACON_CURRENT_COMBAT_PLAYER_ID',))
        other=numeric(opponent)
        if phase!='combat':self.combat_attack_seen=False;self.combat_prestart_uncertain=False
        if phase=='combat' and not self.combat_attack_seen and other in self._playable() and other!=pid:
            self.last_combat_pid=other
            displayed_controller=other if other in self.players else self._shop_controller()
            self.known_boards[other]={'rows':[self._minion(e) for e in self._rows(displayed_controller,'PLAY',('MINION','4'))],'cards':[self._card(e) for e in self._rows(displayed_controller,'PLAY',('MINION','4'))],'known':not self.combat_prestart_uncertain,'observed_at_revision':l.revision,'source':'explicit local combat linkage; Bob controller hosts displayed enemy warband'}
        self.last_phase=phase
    def _global_facts(self,phase,zones,heroes,powers,playable):
        l=self.ledger;pid=l.observer;player=self.players.get(pid);hero=heroes.get(pid)
        # Composite initialization is valid until observed mechanisms invalidate
        # it, not a generic fallback for missing arbitrary observations.
        g={n:self._default(0) for n in GLOBAL_NAMES}
        alive=[]
        for p in playable:
            h=heroes.get(p);hp=self._tag(h,'HEALTH');damage=self._tag(h,'DAMAGE')
            if phase=='hero_select':alive.append(self._default(1,'solo8 alive at initial hero selection'))
            elif hp['known'] and damage['known']:alive.append(derived(int(numeric(hp)-numeric(damage)>0),hp,damage))
            else:alive.append(unknown('unobserved opponent alive/public health'))
        g['alive_count']=derived(sum(numeric(a) or 0 for a in alive),*alive)
        g['alive']=self._default(int(l.val(player,'PLAYSTATE') not in ('LOST','QUIT',5,6)),'public own PLAYSTATE ledger')
        g['hero_select']=self._default(int(phase=='hero_select'));g['game_over']=self._default(int(phase=='finished'))
        turn=self._tag(l.game,'TURN')
        g['turn']=derived((int(numeric(turn))+1)//2,turn,basis='native Hearthstone two-player TURN to BG recruit round; ceil(TURN/2)') if turn['known'] else unknown('missing TURN')
        if phase=='hero_select':g['turn']=self._default(0,'target native HeroSelect turn0')
        health=self._tag(hero,'HEALTH');damage=self._tag(hero,'DAMAGE')
        g['health']=derived(numeric(health)-numeric(damage),health,damage) if health['known'] and damage['known'] else self._default(30) if phase=='hero_select' else unknown('hero health not observed')
        g['armor']=self._tag(hero,'ARMOR') if hero else self._default(0) if phase=='hero_select' else unknown('hero missing')
        g['tier']=self._tag_any((hero,player),('PLAYER_TECH_LEVEL',),self._default(1) if phase=='hero_select' else None)
        resource=self._tag(player,'RESOURCES');used=self._tag(player,'RESOURCES_USED');temporary=self._tag(player,'TEMP_RESOURCES')
        g['gold']=derived(numeric(resource)-numeric(used)+numeric(temporary),resource,used,temporary) if all(x['known'] for x in (resource,used,temporary)) else unknown('gold dependencies unknown')
        refresh=next((e for e in self.entities if numeric(self._card(e))=='TB_BaconShop_8p_Reroll_Button' and l.val(e,'CONTROLLER')==pid),None)
        upgrade=next((e for e in self.entities if str(numeric(self._card(e))).startswith('TB_BaconShopTechUp') and l.val(e,'CONTROLLER')==pid),None)
        g['refresh_price']=self._tag(refresh,'COST') if refresh else self._default(1) if phase=='hero_select' else unknown('refresh button cost missing')
        g['upgrade_price']=self._tag(upgrade,'COST') if upgrade else self._tag_any((hero,),('BACON_TAVERN_UPGRADE_COST',),self._default(6,'frozen flow.rs initialize upgrade_cost = cfg.upgrade_costs[0](5)+discount_per_turn(1)') if phase=='hero_select' else None)
        g['minion_price']=self._default(3,'frozen cfg.buy_cost=3 baseline; per-card current purchase prices remain distinct')
        if any(numeric(self._card(p)) in ('TB_BaconShop_HP_054','TB_BaconShop_HP_014') for p in powers):g['minion_price']=self._default(2,'frozen recruit.rs minion_price hero exception')
        for field,tags in GLOBAL_DIRECT.items():g[field]=self._tag_any((hero,player,l.game),tags,g[field])
        for slot in range(2):
            power=powers[slot] if slot<len(powers) else None
            options=[o for o in l.options if o['entity_id']==power and o['error']=='NONE']
            g[f'power{slot}_usable']=self._default(int(bool(options)))
            g[f'power{slot}_price']=self._tag(power,'COST') if power else self._default(0)
            g[f'power{slot}_uses']=self._tag_any((power,),('NUM_TIMES_HERO_POWER_USED_THIS_GAME',),self._default(sum(1 for h in l.history if h.get('kind')=='power' and h.get('card_id')==numeric(self._card(power)))))
        gift=next((o for o in l.options if numeric(self._card(o['entity_id']))=='BG36_Button_DarkGift' and o['error']=='NONE'),None)
        g['dark_gift_usable']=self._default(int(gift is not None))
        g['dark_gift_uses']=self._default(sum(1 for h in l.history if h.get('card_id')=='BG36_Button_DarkGift'))
        g['board_count']=self._default(len(zones['board']));g['hand_count']=self._default(len(zones['hand']))
        g['hand_queue_count']=self.hand_queue_guard.fact(l)
        frozen=[self._tag(e,'FROZEN') for e in zones['shop']]
        g['frozen']=derived(int(any(numeric(x) for x in frozen)),*frozen) if frozen else self._default(0)
        g.update(self.context.get('globals',{}))
        return g
    def _mechanism_gaps(self,phase,owned):
        """Do not silently keep initialized counters after unbound effects."""
        gaps=[];invalid=set();l=self.ledger
        for eid in owned:
            cid=numeric(self._card(eid));card=self.catalogue.get(cid,{})
            text=re.sub('<[^>]+>',' ',card.get('text','')).lower()
            if ('blood gems give' in text or 'blood gems grant' in text) and ('extra' in text or 'additional' in text):invalid.update(('gem_attack','gem_health'))
            if 'tavern spells' in text and ('extra' in text or 'additional' in text):invalid.update(('spell_attack','spell_health'))
            if 'minions in the tavern' in text and ('this game' in text or 'permanent' in text):invalid.update(('tavern_attack','tavern_health'))
            if 'maximum gold' in text:invalid.add('max_gold_bonus')
            if 'next turn' in text and ('gold' in text or 'coin' in text):invalid.add('gold_next_turn')
            if 'chronum' in text or 'timewarp' in text:invalid.add('chronum')
            if ('minions cost' in text or 'first minion' in text) and ('free' in text or 'cost' in text):invalid.add('minion_price')
            # Unbound player/hero enchantments can encode composite counters,
            # delayed effects, temporary card flags or generated rule context.
            if l.val(eid,'CARDTYPE') in ('ENCHANTMENT','6') and l.val(eid,'ZONE') in ('PLAY','1') and l.val(eid,'ATTACHED') in (self.players.get(l.observer),self._hero(l.observer)) and cid not in ('TB_BaconShop_8P_PlayerE','TB_BaconShop_3ofKindChecke','TB_BaconShop_FXWatcher','Bacon_TagTransferPlayerE','Bacon_Free_Refresh_Player_Ench','TB_BaconShop_HP_038e','BG29_813e'):
                gaps.append({'path':'effects/'+str(eid),'card_id':cid,'reason':'public persistent player effect lacks verified engine-effect decomposition'})
        return invalid,gaps
    def _collections(self,pid,hero):
        l=self.ledger;blank=self._default('');result={};gaps=[]
        def dbf_leaf(leaf):
            dbf=numeric(leaf)
            if dbf==0:return self._default('')
            if dbf in self.dbf_mapping:return derived(self.dbf_mapping[dbf],leaf,basis='frozen stable DBF to CardID mapping')
            return unknown('unmapped public DBF:'+str(dbf))
        trinkets=[]
        for tag in ('BACON_FIRST_TRINKET_DATABASE_ID','BACON_SECOND_TRINKET_DATABASE_ID'):
            leaf=self._tag(hero,tag) if hero else self._default(0)
            if numeric(leaf):trinkets.append(dbf_leaf(leaf))
        result['trinkets']=copy.deepcopy(self.context.get('trinkets',trinkets))
        deity=self._tag_any((hero,self.players.get(pid),l.game),('BACON_GLOBAL_OLD_GOD_DBID','BACON_OLD_GOD'),self._default(0))
        result['deity']=copy.deepcopy(self.context.get('deity',dbf_leaf(deity)))
        quests=[];identities=[];rewards=[];secrets=[]
        for eid,row in self.entities.items():
            if l.val(eid,'CONTROLLER')!=pid or l.val(eid,'ZONE') not in ('PLAY','SECRET','1','7'):continue
            cid=self._card(eid);card=self.catalogue.get(numeric(cid),{})
            if card.get('kind')=='quest':
                progress=self._tag(eid,'QUEST_PROGRESS');goal=self._tag(eid,'QUEST_PROGRESS_TOTAL',False)
                reward=self._tag_any((eid,),('QUEST_REWARD_DATABASE_ID','QUEST_REWARD_DBF_ID'))
                quests.append({'present':derived(1,cid),'progress':progress,'goal':goal})
                identities.append((cid,dbf_leaf(reward)))
            if card.get('kind')=='quest_reward':rewards.append(cid)
            if l.val(eid,'SECRET')==1:secrets.append(cid)
        result['quests']=copy.deepcopy(self.context.get('quests',quests))
        qident=[]
        for i in range(3):qident.extend([*(identities[i] if i<len(identities) else (blank,blank)),rewards[i] if i<len(rewards) else blank])
        result['quest_reward_identity']=copy.deepcopy(self.context.get('quest_reward_identity',qident))
        result['secrets']=copy.deepcopy(self.context.get('secrets',secrets))
        return result,gaps
    def snapshot(self):
        l=self.ledger;pid=l.observer;phase=self._phase();shop_pid=self._shop_controller();gaps=[]
        self.version_contract['log_build_source']=copy.deepcopy(l.build_source)
        gaps += [{'path':'public_context/'+k,'reason':'mutable UI evidence invalidated by subsequent state event; reobserve, do not restore initial zero'} for k in sorted(self.invalidated_context)]
        playable=self._playable()
        heroes={p:self._hero(p) for p in playable};powers=self._rows(pid,'PLAY',('HERO_POWER','10')) if pid is not None else []
        powers.sort(key=lambda e:(l.val(e,'ADDITIONAL_HERO_POWER_INDEX',0),l.val(e,'ZONE_POSITION',0),e))
        zones={'board':self._rows(pid,'PLAY',('MINION','4')),'hand':self._rows(pid,'HAND'),'shop':self._rows(shop_pid,'PLAY',('MINION','4','BATTLEGROUND_SPELL','42')) if shop_pid is not None else []}
        if phase=='hero_select':zones={'board':[],'hand':[],'shop':[]}
        if l.game_type not in ('GT_BATTLEGROUNDS','GT_BATTLEGROUNDS_FRIENDLY'):gaps.append({'path':'game_type','reason':'not positively identified BG solo lobby','actual':l.game_type})
        if len(playable)!=8:gaps.append({'path':'players','reason':'need exact8 public players excluding evidenced Bob','actual':len(playable)})
        if not l.saw_create:gaps.append({'path':'create','reason':'CREATE_GAME missing; cannot initialize counters or empty collections'})
        if pid is None or l.observer_conflict:gaps.append({'path':'observer','reason':'local controller unanchored or conflicting'})
        if phase=='unknown':gaps.append({'path':'phase','reason':'no current choice/phase/options boundary'})
        f={'globals':self._global_facts(phase,zones,heroes,powers,playable),'lobby_races':copy.deepcopy(self.context.get('lobby_races',{})), 'quests':[],'pending_kind':self._default(0),'board':[],'hand':[],'shop':[],'choices':[],'opponents':[],'opponent_boards':[],'card_ids':{key:[] for key,n in CARD_GROUPS}}
        collections,collection_gaps=self._collections(pid,heroes.get(pid));gaps+=collection_gaps
        def pads(rows,n,pad):
            if len(rows)>n:gaps.append({'path':'collection_overflow','reason':f'{len(rows)} exceeds schema {n}'})
            return rows[:n]+[copy.deepcopy(pad) for _ in range(max(0,n-len(rows)))]
        empty={'present':self._default(0)};blank=self._default('')
        f['board']=pads([self._minion(e) for e in zones['board']],7,empty)
        for z,n in [('hand',10),('shop',8)]:f[z]=pads([self._item(e,z) for e in zones[z]],n,empty)
        identity=[self._card(heroes.get(pid)) if heroes.get(pid) and phase!='hero_select' else blank]+pads([self._card(e) for e in powers],2,blank)+[collections['deity'],self._card(l.choice_source) if l.choice_source and l.choice_source!=l.game else blank]
        f['card_ids']['identity']=identity
        f['quests']=pads(collections['quests'],3,empty)
        f['card_ids']['quest_reward_identity']=pads(collections['quest_reward_identity'],9,blank)
        f['card_ids']['secrets']=pads(collections['secrets'],5,blank)
        for z,n in [('board',7),('hand',10),('shop',8)]:f['card_ids'][z]=pads([self._card(e) for e in zones[z]],n,blank)
        f['card_ids']['trinkets']=pads(collections['trinkets'],8,blank)
        f['globals']['trinket_count']=self._default(len(collections['trinkets']))
        f['globals']['deity_present']=derived(int(bool(numeric(collections['deity']))),collections['deity'])
        if 'effects' in self.context:f['globals']['effect_count']=self._default(len(self.context['effects']),'explicit public effect decomposition list')
        stage={'kind':phase,'source':'public-log','pending_id':None,'options':[]};commands={}
        if l.choice:
            if not l.choice_complete:gaps.append({'path':'choice_batch','reason':'choice indices duplicate/gapped or transport batch not sealed'})
            kind=1 if phase=='hero_select' else 6 if any(l.val(e['entity_id'],'CARDTYPE') in ('BATTLEGROUND_TRINKET','44') for e in l.choice_entities) else 2
            f['pending_kind']=self._default(kind)
            stage.update(kind={1:'hero_select',2:'discover',6:'trinket'}[kind],pending_id=l.choice['id'],confirm_button='hero_confirm' if kind==1 else 'trinket_confirm' if kind==6 else None)
            ordered=sorted(l.choice_entities,key=lambda x:x['index'])
            for order,c in enumerate(ordered):
                eid=c['entity_id'];row=self._item(eid,'choices',menu_only=phase=='hero_select')
                f['choices'].append(row);f['card_ids']['choices'].append(self._card(eid))
                position=l.val(eid,'ZONE_POSITION',0);ui_slot=position-1 if position and position>0 else order
                option={'index':order,'entity_id':eid,'zone':'choices','slot':ui_slot,'position':position,'card_id':self._card(eid),'facts':row,'source':c['source']}
                stage['options'].append(option)
                if order<16:commands[30+order]={'index':30+order,'type':'choice','option_idx':ui_slot,'model_option_idx':order,'entity_id':eid,'pending_id':l.choice['id'],'receipt':{'kind':'choice','choice_id':l.choice['id'],'entities':[eid]},'source':c['source']}
        f['choices']=pads(f['choices'],16,empty);f['card_ids']['choices']=pads(f['card_ids']['choices'],16,blank)
        others=[playable[(playable.index(pid)+i)%len(playable)] for i in range(1,8)] if pid in playable and len(playable)==8 else [None]*7
        next_leaf=self.context.get('next_opponent') or self._tag_any((self.players.get(pid),heroes.get(pid),l.game),('NEXT_OPPONENT_PLAYER_ID','BACON_NEXT_OPPONENT_PLAYER_ID','BACON_NEXT_COMBAT_PLAYER_ID'))
        next_pid=numeric(next_leaf)
        for op in others:
            if phase=='hero_select':row=dict(zip(OPP_NAMES,[self._default(v,'obs.rs hero-select public mask') for v in (1,1,40,0,1,0,0,0,0)]));hero_card=blank
            else:
                oh=heroes.get(op);pe=self.players.get(op);hp=self._tag(oh,'HEALTH');damage=self._tag(oh,'DAMAGE')
                current=derived(numeric(hp)-numeric(damage),hp,damage) if hp['known'] and damage['known'] else unknown('opponent public health unknown')
                row={'present':self._default(1 if op is not None else 0),'alive':derived(int((numeric(current) or 0)>0),current),'health':current,'armor':self._tag(oh,'ARMOR'),'tier':self._tag_any((oh,pe),('PLAYER_TECH_LEVEL',)),'board_count':self._default(len(self.known_boards.get(op,{}).get('rows',[]))),'placement':self._default(0,'obs.rs placement0 while alive') if numeric(current) and numeric(current)>0 else self._tag_any((oh,pe),('PLAYER_LEADERBOARD_PLACE',),self._default(0)),'last_opponent':self._default(int(op==self.last_combat_pid)),'next_opponent':derived(int(op==next_pid),next_leaf)};hero_card=self._card(oh)
            f['opponents'].append(row);f['card_ids']['opponent_heroes'].append(hero_card)
            memory=self.known_boards.get(op,{})
            if memory and not memory.get('known',True):gaps.append({'path':'opponent_memory/'+str(op),'reason':'pre-start combat mutations cannot be equated to native pre-combat last_board; public boundary evidence required'})
            f['opponent_boards']+=pads(copy.deepcopy(memory.get('rows',[])),7,empty)
            f['card_ids']['opponent_boards']+=pads(copy.deepcopy(memory.get('cards',[])),7,blank)
        if not l.choice and l.options_complete and phase=='recruit':commands.update(self._actions(zones,powers,f))
        zones_for_ui={z:[{'entity_id':e,'id':str(e),'slot':i,'card_id':self._card(e),'facts':self._item(e,z) if z!='board' else self._minion(e)} for i,e in enumerate(es)] for z,es in zones.items()}
        zones_for_ui['hero_buttons']=[{'entity_id':e,'id':str(e),'slot':i,'card_id':self._card(e)} for i,e in enumerate(powers)]
        zones_for_ui['hero']=[{'entity_id':heroes[pid],'id':str(heroes[pid]),'slot':0,'card_id':self._card(heroes[pid])}] if heroes.get(pid) else []
        zones_for_ui['opponent_hero']=[{'entity_id':heroes[op],'id':str(heroes[op]),'slot':i,'controller':op,'card_id':self._card(heroes[op])} for i,op in enumerate(others) if heroes.get(op)]
        owned=[e for e in self.entities if l.val(e,'CONTROLLER')==pid]
        invalid,mechanism_gaps=self._mechanism_gaps(phase,owned)
        for name in invalid:
            if name not in self.context.get('globals',{}) and not any(n in self.entities.get(heroes.get(pid),{}).get('tags',{}) or n in self.entities.get(self.players.get(pid),{}).get('tags',{}) for n in GLOBAL_DIRECT.get(name,[])):f['globals'][name]=unknown('observed mechanism can change '+name+'; no bound public counter')
        gaps+=mechanism_gaps
        model_observation=None
        try:
            encoded=encode_public(f,self.card_mapping)
            if not gaps:model_observation=dict(encoded,action_mask=[int(i in commands) for i in range(245)])
        except IncompleteObservation as exc:gaps += [{'path':p,'reason':'required public fact missing or unbound'} for p in exc.gaps]
        ledger={}
        def visit(value,path=''):
            if isinstance(value,dict) and 'known' in value:ledger[path]=copy.deepcopy(value)
            elif isinstance(value,dict):
                for k,v in value.items():visit(v,path+'/'+str(k))
            elif isinstance(value,list):
                for i,v in enumerate(value):visit(v,path+'/'+str(i))
        visit(f)
        for gap in gaps:
            ledger.setdefault('/'+gap['path'].lstrip('/'),unknown(gap['reason']))
        raw_summary={'game_key':l.game_key,'revision':l.revision,'option_batch':l.option_batch,'choice':l.choice['id'] if l.choice else None,'phase':phase}
        token=hashlib.sha256(json.dumps(raw_summary,sort_keys=True).encode()).hexdigest()
        terminal=None
        if phase=='finished':
            rank=self._tag_any((heroes.get(pid),self.players.get(pid)),('PLAYER_LEADERBOARD_PLACE',))
            if numeric(rank) in range(1,9):terminal={'reason':'normal','rank':numeric(rank),'evidence':rank['source']}
            else:gaps.append({'path':'terminal/rank','reason':'game ended but final public placement missing'})
        return {'schema':'bgagent10-live-public-v2','version_contract':dict(self.version_contract,installed_client_build=self.installed_client_build,log_build_number=l.build),'game_key':l.game_key,'observer':pid,'seat_id':playable.index(pid) if pid in playable else None,'observer_entity_id':self.players.get(pid),'shop_controller':shop_pid,'phase':phase,'turn':numeric(f['globals']['turn']),'revision':l.revision,'token':token,'facts':f,'model_observation':model_observation,'observation':model_observation,'commands':commands,'stage':stage,'summary':{'gold':numeric(f['globals']['gold']),'tier':numeric(f['globals']['tier']),'frozen':numeric(f['globals']['frozen']),'phase':phase,'option_batch':l.option_batch},'zones':zones_for_ui,'field_sources':ledger,'gaps':gaps,'history':copy.deepcopy(l.history),'terminal':terminal,'complete':not gaps and model_observation is not None,'policy_ready':not gaps and model_observation is not None and any(model_observation['action_mask']),'source':'real-read','game_type':l.game_type,'build_numbers':[l.build] if l.build else [],'observed_entity_count':len(l.entities),'observed_options':len(l.options),'native_options':copy.deepcopy(l.options),'receipts':copy.deepcopy(l.receipts),'public_provenance_not_server_authentication':True}
    def _actions(self,zones,powers,facts):
        l=self.ledger;commands={};lookup={eid:(z,i) for z,ids in zones.items() for i,eid in enumerate(ids)}
        for p in self._playable():
            hero=self._hero(p)
            if hero is not None:lookup[hero]=('hero' if p==l.observer else 'opponent_hero',0 if p==l.observer else sorted(x for x in self._playable() if x!=l.observer).index(p))
            if p not in (l.observer,self._shop_controller()):
                for i,e in enumerate(self._rows(p,'PLAY',('MINION','4'))):lookup[e]=('opponent_board',i)
        def add(index,option,**extra):
            if not 0<=index<245:raise ValueError('native option outside245 schema')
            receipt={'kind':'option','index':option['index'],'sub':-1,'target':0,'position':0}
            row={'index':index,**decode_action(index),'server_option':option['index'],'receipt':receipt,'native_targets':copy.deepcopy(option['targets']),'native_suboptions':copy.deepcopy(option['suboptions']),'source':option['source'],**extra}
            if option['targets'] or option['suboptions']:
                sub=option['suboptions'];targets=[x for x in option['targets'] if x['error']=='NONE'];opts=[]
                for i,t in enumerate(sub if sub else targets):
                    eid=t['entity_id'];z,slot=lookup.get(eid,('choices',i) if sub else ('unknown',None))
                    if z in ('hero','opponent_hero'):
                        # Native Target options expose no Item for hero targets:
                        # present menu entry, card0, per obs.rs target lookup.
                        item=self._item(eid,z,menu_only=True);target_card=self._default('','obs.rs hero target has no Item and card0')
                    else:item=self._item(eid,z,menu_only=bool(sub));target_card=self._card(eid)
                    if sub:
                        item=self._item(option['entity_id'],'choices',menu_only=True)
                        target_card=self._card(option['entity_id'])
                    else:
                        # Target options in obs.rs have cost0 and no item flags,
                        # regardless of the target card's purchase price.
                        item['cost']=self._default(0,'obs.rs Target option cost0')
                        for flag in ('locked','temporary','combined','frozen','kept','marked'):item[flag]=self._default(0,'obs.rs Target flags false')
                    opts.append({'index':i,'entity_id':eid,'zone':z,'slot':slot,'card_id':target_card,'facts':item,'server_target':eid if not sub else None,'server_sub':t['index'] if sub else -1,'legal':t['error']=='NONE','source':t['source']})
                    if sub and t.get('targets'):
                        nested=[]
                        for j,target in enumerate(x for x in t['targets'] if x['error']=='NONE'):
                            teid=target['entity_id'];tz,ts=lookup.get(teid,('unknown',None));hero_target=tz in ('hero','opponent_hero')
                            target_facts=self._item(teid,tz,menu_only=hero_target);target_facts['cost']=self._default(0)
                            for flag in ('locked','temporary','combined','frozen','kept','marked'):target_facts[flag]=self._default(0)
                            nested.append({'index':j,'entity_id':teid,'zone':tz,'slot':ts,'facts':target_facts,'card_id':self._default('') if hero_target else self._card(teid),'server_target':teid,'server_sub':t['index'],'source':target['source']})
                        opts[-1]['continuation']={'kind':'target','pending_id':f'local-{l.option_batch}-{index}-sub{t["index"]}','options':nested,'source_entity':option['entity_id'],'source_card':self._card(option['entity_id']),'cancel_index':7}
                row['continuation']={'kind':'choose_one' if sub else 'target','pending_id':f'local-{l.option_batch}-{index}','options':opts,'source_entity':option['entity_id'],'source_card':self._card(option['entity_id']),'cancel_index':7}
            if index in commands:
                # Drag and activate can have identical POWER options; preserve
                # alternatives explicitly for exact command/gesture resolution.
                commands[index].setdefault('receipt_aliases',[]).append(receipt)
            else:commands[index]=row
            return row
        for option in l.options:
            if option['error']!='NONE':continue
            eid=option['entity_id'];cid=numeric(self._card(eid));zone,slot=lookup.get(eid,(None,None))
            if cid in ('TB_BaconShop_DragBuy','TB_BaconShop_DragBuy_Spell','TB_BaconShop_DragSell'):
                buy=cid!='TB_BaconShop_DragSell'
                for t in option['targets']:
                    z,i=lookup.get(t['entity_id'],(None,None))
                    if t['error']=='NONE' and z==('shop' if buy else 'board'):
                        row=add((8 if buy else 16)+i,dict(option,targets=[],suboptions=[]),entity_id=t['entity_id'],shop_idx=i if buy else None,board_idx=i if not buy else None)
                        row['receipt']['target']=t['entity_id']
            elif cid=='TB_BaconShop_8p_Reroll_Button':add(1,option)
            elif cid=='TB_BaconShopLockAll_Button':add(2,option)
            elif str(cid).startswith('TB_BaconShopTechUp'):add(3,option)
            elif cid=='BG36_Button_DarkGift':add(6,option)
            elif eid in powers:
                power_slot=powers.index(eid)
                if power_slot<2:add(4+power_slot,option,entity_id=eid,power_idx=power_slot)
            elif zone=='hand' and slot<10:
                card=self.catalogue.get(cid,{})
                is_minion=l.val(eid,'CARDTYPE') in ('MINION','4') or card.get('kind')=='minion'
                positions=range(len(zones['board'])+1) if is_minion and len(zones['board'])<7 else [] if is_minion else [0]
                for pos in positions:
                    row=add(46+8*slot+pos,option,entity_id=eid,hand_idx=slot,position=pos)
                    row['receipt']['position']=pos+1 if is_minion else 0
                if is_minion and numeric(self._minion(eid).get('MAGNETIC')):
                    for b,target in enumerate(zones['board']):
                        races=[n for n in RACES if numeric(self._minion(target)[n])]
                        eligible=any(t['entity_id']==target and t['error']=='NONE' for t in option['targets'])
                        if 'MECHANICAL' in races and eligible:
                            row=add(126+slot*7+b,dict(option,targets=[],suboptions=[]),entity_id=eid,hand_idx=slot,board_idx=b,target_entity=target,mode='magnetize_direct')
                            row['receipt']['target']=target
            elif zone=='board' and slot<7:
                if l.val(eid,'INTERACTABLE_OBJECT')==1 and l.val(eid,'HAS_ACTIVATE_POWER')==1:add(23+slot,option,entity_id=eid,board_idx=slot)
                if not option['targets'] and not option['suboptions']:
                    for pos in range(len(zones['board'])):
                        if pos!=slot:
                            row=add(196+7*slot+pos,option,entity_id=eid,board_idx=slot,position=pos)
                            row['receipt']['position']=pos+1
        # EndTurn in this client is an evidenced wait for recruit timer/phase,
        # not an invented server input option. Controller handles no-input wait.
        if l.options_complete:commands[0]={'index':0,'type':'end','mode':'wait_phase','source':l.last_proof}
        return commands
    def preview_observation(self,command):
        snapshot=self.snapshot()
        if not snapshot['complete']:raise IncompleteObservation([x['path'] for x in snapshot['gaps']])
        continuation=command.get('continuation')
        if not continuation:raise ValueError('command has no public continuation')
        f=copy.deepcopy(snapshot['facts']);options=continuation['options'];kind=continuation['kind']
        f['pending_kind']=self._default(3 if kind=='choose_one' else 4)
        f['card_ids']['identity'][4]=copy.deepcopy(continuation['source_card'])
        f['choices']=[copy.deepcopy(x['facts']) for x in options]
        f['card_ids']['choices']=[copy.deepcopy(x['card_id']) for x in options]
        while len(f['choices'])<16:f['choices'].append({'present':self._default(0)});f['card_ids']['choices'].append(self._default(''))
        result=encode_public(f,self.card_mapping)
        legal={30+i for i,opt in enumerate(options) if opt.get('legal',True)}
        result['action_mask']=[int(i==7 or i in legal) for i in range(245)]
        return result


def inspect_log(path,max_bytes=64*1024*1024,**kwargs):
    path=Path(path)
    if path.stat().st_size>max_bytes:raise ValueError('bounded log limit exceeded; use incremental producer')
    producer=PublicLogProducer(**kwargs)
    with path.open('rb') as stream:
        while chunk:=stream.read(256*1024):producer.feed(chunk,source=str(path.resolve()))
    producer.ledger.seal_options()
    return producer.snapshot()


def installed_build(client_path):
    root=Path(client_path).parent;info=root/'.build.info'
    if info.is_file():
        lines=info.read_text('utf8').splitlines()
        if len(lines)>1:
            headers=lines[0].split('|');values=lines[1].split('|')
            for i,key in enumerate(headers):
                if key.startswith('Version!'):return {'build':values[i],'source':str(info),'sha256':hashlib.sha256(info.read_bytes()).hexdigest()}
    product=root/'.product.db'
    if product.is_file():
        raw=product.read_bytes();versions=sorted(set(x.decode('ascii') for x in re.findall(rb'(?<![0-9])\d{2}\.\d+\.\d+\.\d{6}(?![0-9])',raw)))
        return {'build':versions[0] if len(versions)==1 else None,'candidates':versions,'source':str(product),'sha256':hashlib.sha256(raw).hexdigest()}
    return {'build':None,'reason':'installed game version metadata unavailable'}
