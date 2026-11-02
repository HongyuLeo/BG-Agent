"""245 actions to explicit, calibrated UI transactions and local continuations."""
from __future__ import annotations
import copy
import math
from .live_encoding import decode_action, encode_public


class Calibration:
    def __init__(self, profile):
        self.profile=profile
        if not isinstance(profile.get('size'),list) or len(profile['size'])!=2:raise ValueError('校准缺窗口尺寸')
    def guard(self,window):
        if self.profile['size']!=[window['width'],window['height']]:raise ValueError('窗口尺寸变化，需要重新校准')
    def point(self,key):
        value=self.profile.get('points',{}).get(key)
        if not isinstance(value,list) or len(value)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<1 for v in value):raise ValueError('需要校准位置：'+key)
        return value
    def zone(self,before,name,index):
        rows=before.get('zones',{}).get(name,[])
        if index not in range(len(rows)):raise ValueError('当前可见实体索引越界：'+name)
        return self.point(f'{name}:{len(rows)}:{index}')


def plan_action(index,before,calibration):
    """No UI positions are guessed, including variable hand fans and board gaps."""
    calibration.guard(before['window']);action=decode_action(index)
    commands=before.get('commands',{})
    command=commands.get(index,commands.get(str(index)))
    if not command:raise ValueError('本次公开Options不包含该动作')
    kind=action['type'];p=calibration.point
    zone=lambda name,i:calibration.zone(before,name,i)
    board_count=len(before.get('zones',{}).get('board',[]))
    steps=[];mode='server';continuation=command.get('continuation')
    stage=before.get('stage') or {}
    if kind=='end':mode='wait_turn'
    elif kind in ('refresh','freeze','upgrade','dark_gift'):steps=[[p('fixed:'+kind)]]
    elif kind=='hero_power':steps=[[p('power:'+str(action['slot']))]]
    elif kind=='buy':steps=[[zone('shop',action['shop']),p('fixed:buy_drop')]]
    elif kind=='sell':steps=[[zone('board',action['board']),p('fixed:sell_drop')]]
    elif kind=='activate':steps=[[zone('board',action['board'])],[zone('board',action['board'])]]
    elif kind=='play':
        if action['position']>board_count:raise ValueError('落点超出当前场上空隙')
        hand=before.get('zones',{}).get('hand',[])
        row=hand[action['hand']] if action['hand']<len(hand) else {}
        is_spell=command.get('is_spell') or row.get('facts',{}).get('is_minion',{}).get('value')==0
        drop=p('fixed:cast_drop') if is_spell else p(f'gap:{board_count}:{action["position"]}')
        steps=[[zone('hand',action['hand']),drop]]
    elif kind=='magnetize':steps=[[zone('hand',action['hand']),zone('board',action['board'])]]
    elif kind=='reorder':
        if action['position']>=board_count:raise ValueError('移动目标超出当前场上范围')
        gap=action['position']+int(action['board']<action['position'])
        steps=[[zone('board',action['board']),p(f'gap:{board_count}:{gap}')]]
    elif kind=='cancel':mode='cancel';steps=[]
    elif kind=='choice':
        options=stage.get('options',[]);option=next((o for o in options if o.get('index')==action['option']),None)
        if option is None:raise ValueError('选择项不属于当前菜单')
        if option.get('legal') is False:raise ValueError('该子选项当前不可用')
        if option.get('zone') in {'board','hand','shop','hero_buttons'}:
            steps=[[zone(option['zone'],option['slot'])]]
        elif option.get('zone') in {'hero','opponent_hero','opponent_board'}:
            steps=[[p(f'target:{option["zone"]}:{option["slot"]}')]]
        elif stage.get('kind')=='target':raise ValueError('目标必须锚定实际实体所在区域，不能当成发现牌位置')
        else:steps=[[p(f'choices:{stage.get("kind","choice")}:{len(options)}:{option.get("slot",action["option"])}')]]
        if stage.get('confirm_button'):steps.append([p('fixed:'+stage['confirm_button'])])
    else:raise ValueError('未知245动作语义')
    if continuation:mode='open_menu'
    receipt=command.get('receipt')
    if mode=='server' and not isinstance(receipt,dict):raise ValueError('缺原生回执约束')
    return {'index':index,'semantic':action,'gestures':steps,'mode':mode,'window':before['window'],
        'expected_receipt':receipt,'receipt_aliases':copy.deepcopy(command.get('receipt_aliases',[])),'command':copy.deepcopy(command),'continuation':continuation,
        'before_token':before['token'],'before_evidence':before.get('evidence'),
        'before_turn':before.get('turn'),'before_stage':stage,'before_zones':copy.deepcopy(before.get('zones',{})),
        'before_summary':copy.deepcopy(before.get('summary',{}))}


class MenuProtocol:
    def __init__(self):self.pending=None
    def open(self,plan,before,mapping):
        menu=copy.deepcopy(plan['continuation'])
        if menu.get('kind') not in {'target','choose_one','discover','hero_select','trinket'}:raise ValueError('未知本地分步菜单')
        options=menu.get('options')
        if not isinstance(options,list) or not options or len(options)>16:raise ValueError('菜单选项未完整锚定')
        mask=[0]*245;commands={}
        for i,option in enumerate(options):
            if option.get('index',i)!=i:raise ValueError('菜单顺序不连续')
            option['index']=i
            if option.get('legal') is False:continue
            mask[30+i]=1
            receipt=copy.deepcopy(plan['expected_receipt'] or {})
            if menu['kind']=='target':receipt['target']=int(option.get('server_target') or option['entity_id'])
            else:receipt['sub']=int(option.get('server_sub',option.get('sub',i)))
            commands[30+i]={'receipt':receipt,'parent_index':plan['index'],'option':option}
            aliases=[]
            for alias in plan.get('receipt_aliases',[]):
                alias=copy.deepcopy(alias)
                if menu['kind']=='target':alias['target']=receipt['target']
                else:alias['sub']=receipt['sub']
                aliases.append(alias)
            if aliases:commands[30+i]['receipt_aliases']=aliases
            if option.get('continuation'):commands[30+i]['continuation']=option['continuation']
        if menu.get('cancellable',True):mask[7]=1;commands[7]={'cancel_local':True}
        numeric=menu.get('model_observation')
        if numeric is None:
            facts=copy.deepcopy(before['facts'])
            proof={'kind':'public-option-menu','options_source':menu.get('source'),'parent':plan['before_token']}
            leaf=lambda value:{'value':value,'known':True,'source':proof}
            facts['pending_kind']=leaf(4 if menu['kind']=='target' else 3 if menu['kind']=='choose_one' else 2)
            if menu.get('source_card'):facts['card_ids']['identity'][4]=copy.deepcopy(menu['source_card'])
            choices=[];cards=[]
            for option in options:
                if 'facts' not in option or 'card_id' not in option:raise ValueError('菜单缺公开目标数值/身份事实')
                choices.append(option['facts']);cards.append(option['card_id'])
            while len(choices)<16:choices.append({'present':leaf(0)});cards.append(leaf(''))
            facts['choices']=choices;facts['card_ids']['choices']=cards
            numeric=encode_public(facts,mapping)
        self.pending={'stage':menu,'numeric':numeric,'commands':commands,'mask':mask,'base':before}
        return self.pending
    def overlay(self,observation):
        if not self.pending:return observation
        pending=self.pending
        return {**observation,**pending['numeric'],'action_mask':pending['mask'],'commands':pending['commands'],'stage':pending['stage'],
            'token':str(observation['token'])+':menu:'+str(pending['stage'].get('pending_id'))}
    def clear(self):self.pending=None


def effect_matches(plan,before,after):
    """Require semantic state proof, not merely a matching outbound receipt."""
    kind=plan['semantic']['type'];old=before.get('summary',{});new=after.get('summary',{})
    zones_before=before.get('zones',{});zones_after=after.get('zones',{})
    ids=lambda zone,z:[str(e.get('id',e.get('entity_id'))) for e in z.get(zone,[])]
    if after.get('terminal'):return True
    if kind=='end':return before.get('turn')!=after.get('turn') or old.get('phase')!=new.get('phase')
    if kind=='buy':return ids('shop',zones_before)!=ids('shop',zones_after) and (ids('hand',zones_before)!=ids('hand',zones_after) or old.get('gold')!=new.get('gold'))
    if kind in ('play','magnetize'):return ids('hand',zones_before)!=ids('hand',zones_after)
    if kind=='sell':return ids('board',zones_before)!=ids('board',zones_after)
    if kind=='reorder':
        source=ids('board',zones_before)[plan['semantic']['board']]
        return source in ids('board',zones_after) and ids('board',zones_after).index(source)==plan['semantic']['position']
    if kind=='upgrade':return new.get('tier',-1)>old.get('tier',-1)
    if kind=='freeze':return 'frozen' in old and old.get('frozen')!=new.get('frozen')
    if kind=='refresh':return ids('shop',zones_before)!=ids('shop',zones_after) or old.get('option_batch')!=new.get('option_batch')
    if kind=='choice':return before.get('stage',{}).get('pending_id')!=after.get('stage',{}).get('pending_id') or old.get('option_batch')!=new.get('option_batch')
    return old.get('option_batch')!=new.get('option_batch') or old.get('gold')!=new.get('gold')
