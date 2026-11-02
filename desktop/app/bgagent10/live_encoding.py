"""Player-public facts -> frozen obs.rs layout. Missing facts never become zero.

The caller must evidence collection completeness, including genuinely empty slots.
Numbers are game values, not pre-normalized. Card indices are stable-ID map + 1.
This module does not reconstruct unknown server state.
"""
from __future__ import annotations
import math

GLOBAL_NAMES = ('turn hero_select game_over alive_count alive health armor gold max_gold_bonus gold_next_turn tier upgrade_price refresh_price minion_price free_refreshes frozen power0_usable power0_price power0_uses power1_usable power1_price power1_uses dark_gift_usable dark_gift_uses trinket_count deity_attack deity_health won_last lost_last spell_attack spell_health gem_attack gem_health board_count hand_count deity_present hand_queue_count next_is_ghost tavern_attack tavern_health effect_count chronum').split()
GLOBAL_SCALE = [20,1,1,8,1,40,20,10,5,5,6,10,2,3,3,1,1,5,5,1,5,5,1,3,2,10,10,1,1,5,5,5,5,7,10,1,5,1,10,10,5,4]
RACES = 'BEAST DEMON DRAGON ELEMENTAL MECHANICAL MURLOC PIRATE QUILBOAR UNDEAD ABERRATION NAGA'.split()
KEYWORDS = 'TAUNT DIVINE_SHIELD WINDFURY REBORN VENOMOUS POISONOUS STEALTH MAGNETIC MEGA_WINDFURY CLEAVE IMMUNE IMMUNE_ATTACKING'.split()
MINION_NAMES = ['present','attack','health','max_health','tier','golden','attached_count','shield_hits'] + KEYWORDS + RACES
MINION_SCALE = [1,10,10,10,6,1,3,3] + [1]*23
ITEM_NAMES = 'present is_minion cost locked temporary combined frozen kept marked'.split()
OPP_NAMES = 'present alive health armor tier board_count placement last_opponent next_opponent'.split()
OPP_SCALE = [1,1,40,20,6,7,8,1,1]
CARD_GROUPS = [('identity',5),('quest_reward_identity',9),('secrets',5),('board',7),('hand',10),('shop',8),('choices',16),('trinkets',8),('opponent_heroes',7),('opponent_boards',49)]


class IncompleteObservation(ValueError):
    def __init__(self, gaps):
        self.gaps = gaps
        super().__init__('公开观察不完整: ' + ', '.join(gaps[:12]))


def encode_public(facts, card_mapping):
    """Each leaf: {value, known: True, source: nonempty evidence reference}.

    facts has globals, lobby_races, quests(3x2), pending_kind(0..8),
    board(7 rows), hand/shop/choices(10/8/16 rows of header+minion),
    opponents(7 rows), opponent_boards(49 rows), card_ids(groups).
    Known absent rows still need an evidenced `present=0`; then padding is
    defined by the frozen schema and is not an inference about missing state.
    """
    gaps=[]
    def value(row,key,path):
        leaf=row.get(key) if isinstance(row,dict) else None
        if not isinstance(leaf,dict) or leaf.get('known') is not True or not leaf.get('source') or 'value' not in leaf:
            gaps.append(path+'/'+str(key)); return None
        return leaf['value']
    def number(row,key,path,scale=1):
        x=value(row,key,path)
        if not isinstance(x,(int,float)) or not math.isfinite(x):
            if x is not None:gaps.append(path+'/'+str(key)+':not_finite_numeric')
            return 0.0  # output discarded if any gap exists
        return float(x)/scale
    def rows(key,count):
        xs=facts.get(key)
        if not isinstance(xs,list) or len(xs)!=count:
            gaps.append(key+':complete_collection_required');return [{} for _ in range(count)]
        return xs
    def minion(row,path):
        present=value(row,'present',path)
        if present==0:return [0.0]*31
        if present!=1:gaps.append(path+'/present:expected_0_or_1')
        return [number(row,n,path,s) for n,s in zip(MINION_NAMES,MINION_SCALE)]
    def item(row,path):
        present=value(row,'present',path)
        if present==0:return [0.0]*40
        head=[number(row,n,path,5 if n=='cost' else 1) for n in ITEM_NAMES]
        kind=value(row,'is_minion',path)
        if kind==1:return head+minion(row.get('minion',{}),path+'/minion')
        if kind==0:
            # Spell payload mirrors push_item (data/6, tier/6). Non-item
            # hero/target menu entries use only the present bit.
            menu=value(row,'menu_only',path)
            if menu is True:return [1.0]+[0.0]*39
            return head+[1.0,number(row,'spell_data',path,6),0.,0.,number(row,'tier',path,6)]+[0.]*26
        gaps.append(path+'/is_minion:invalid');return [0.]*40
    f=[number(facts.get('globals',{}),n,'globals',s) for n,s in zip(GLOBAL_NAMES,GLOBAL_SCALE)]
    f += [number(facts.get('lobby_races',{}),n,'lobby_races') for n in RACES]
    for i,row in enumerate(rows('quests',3)):
        present=value(row,'present',f'quests/{i}')
        if present==0:f += [0.,0.]
        else:
            goal=number(row,'goal',f'quests/{i}')
            f += [number(row,'present',f'quests/{i}'),number(row,'progress',f'quests/{i}')/max(goal,1)]
    pending=value(facts,'pending_kind','')
    if type(pending)!=int or pending not in range(9):gaps.append('pending_kind:invalid')
    f += [float(i==pending) for i in range(9)]
    for i,row in enumerate(rows('board',7)):f+=minion(row,f'board/{i}')
    for key,count in [('hand',10),('shop',8),('choices',16)]:
        for i,row in enumerate(rows(key,count)):f+=item(row,f'{key}/{i}')
    for i,row in enumerate(rows('opponents',7)):
        f += [number(row,n,f'opponents/{i}',s) for n,s in zip(OPP_NAMES,OPP_SCALE)]
    for i,row in enumerate(rows('opponent_boards',49)):f+=minion(row,f'opponent_boards/{i}')
    c=[]
    for key,count in CARD_GROUPS:
        group=facts.get('card_ids',{}).get(key)
        if not isinstance(group,list) or len(group)!=count:
            gaps.append('card_ids/'+key+':complete_collection_required');group=[{}]*count
        for i,leaf in enumerate(group):
            cid=value({'id':leaf},'id',f'card_ids/{key}/{i}')
            if cid is None:c.append(0)
            elif cid=='':c.append(0)  # explicitly known absent, never unknown
            elif cid not in card_mapping:gaps.append('unmapped_card:'+str(cid));c.append(0)
            else:c.append(card_mapping[cid]+1)
    if gaps:raise IncompleteObservation(sorted(set(gaps)))
    assert len(f)==3227 and len(c)==124
    return {'features':f,'cards':c}


def decode_action(index):
    if type(index)!=int or not 0<=index<245:raise ValueError('动作编号必须在0..244')
    if index<8:return {'type':['end','refresh','freeze','upgrade','hero_power','hero_power','dark_gift','cancel'][index],**({'slot':index-4} if index in (4,5) else {})}
    for lo,hi,kind,field in [(8,16,'buy','shop'),(16,23,'sell','board'),(23,30,'activate','board'),(30,46,'choice','option')]:
        if lo<=index<hi:return {'type':kind,field:index-lo}
    if index<126:return {'type':'play','hand':(index-46)//8,'position':(index-46)%8}
    if index<196:return {'type':'magnetize','hand':(index-126)//7,'board':(index-126)%7}
    return {'type':'reorder','board':(index-196)//7,'position':(index-196)%7}


def map_options(state):
    """Convert evidenced old typed public options without collapsing menus.

    Returns current restricted execution mask; unsupported actions stay explicit
    gaps. Targeted play/power/activation cannot map to atomic new actions until
    the separate Target/Choose continuation is observed. Never infer legality
    from gold or simulator hidden state.
    """
    mapped={};gaps=[];ambiguous=set()
    def slot(zone,eid):
        found=[i for i,e in enumerate(state.get(zone,[])) if str(e.get('id'))==str(eid)]
        if len(found)!=1:raise ValueError('实体映射不唯一:'+zone+'/'+str(eid))
        return found[0]
    for row in state.get('live_options',[]):
        a=row.get('action',{});kind=a.get('kind');index=None
        try:
            if a.get('target') or (kind!='choice' and a.get('choice',-1)>=0):raise ValueError('target/subchoice requires separate observed continuation')
            if kind in ('end','refresh','freeze','unfreeze','upgrade','dark_gift','cancel'):
                index={'end':0,'refresh':1,'freeze':2,'unfreeze':2,'upgrade':3,'dark_gift':6,'cancel':7}[kind]
            elif kind=='buy':index=8+slot('shop',a['source'])
            elif kind=='sell':index=16+slot('board',a['source'])
            elif kind=='activate':index=23+slot('board',a['source'])
            elif kind=='choice':index=30+a['choice']
            elif kind=='play':index=46+8*slot('hand',a['source'])+max(a['position'],0)
            elif kind=='reorder':index=196+7*slot('board',a['source'])+a['position']
            elif kind=='hero_power':index=4+slot('hero_buttons',row.get('main_entity'))
            else:raise ValueError('unsupported option type:'+str(kind))
            if index in ambiguous:raise ValueError('ambiguous index remains blocked')
            if index in mapped:
                mapped.pop(index)
                ambiguous.add(index)
                raise ValueError('multiple protocol commands collapse to same index')
            semantic=decode_action(index)
            if semantic['type']!=('freeze' if kind=='unfreeze' else kind):raise ValueError('zone or slot overflow')
            mapped[index]=row
        except (KeyError,ValueError,TypeError) as exc:gaps.append({'action':a,'reason':str(exc)})
    mask=[int(i in mapped) for i in range(245)]
    return {'action_mask':mask,'commands':mapped,'gaps':gaps,'complete':not gaps}
