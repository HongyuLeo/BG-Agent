"""Built-in two-choice display heuristic copied from legacy live_native.py.

Source (read-only): BG-Agent体验版2.0/bgagent/live_native.py,
SHA256 2be4652c20227df16fae30b6d0b698c7bda65f6d25cdad297fd8c8204bb2dfdf.
Same source in the original training experience and3.0. This is only local
pixel readiness, never a server receipt, legal-action oracle or model state.
"""


def legacy_subchoice_ready(rgb):
    if rgb is None:
        return False
    import numpy as np
    from .live_legacy_layout import canonical_frame
    rgb=canonical_frame(rgb)
    def green(box):
        x0,y0,x1,y1=box
        sample=rgb[y0:y1,x0:x1].astype(np.int16)
        return float(((sample[:,:,1]>160)&(sample[:,:,1]>sample[:,:,0]*1.25)&
                      (sample[:,:,1]>sample[:,:,2]*1.15)).mean())>.15
    return green((520,275,550,580)) and green((1050,275,1080,580))


# Reused pixel thresholds and stable-frame logic from experience 3.0.
from pathlib import Path
import copy

class _LegacyReadinessProbe:
    def scene_ready(self, state):
            """Reject transition overlays before any card input (1600x900 profile)."""
            self.scene_reason = None
            def blocked(reason):
                self.scene_reason = reason
                return False
            rgb = getattr(self, "last_rgb", None)
            if rgb is None:
                return blocked('尚未取得游戏画面')
            import numpy as np
            from .live_legacy_layout import canonical_frame
            rgb=canonical_frame(rgb)
            choice = state.get("choice_request") or {}
            if choice and any(e.get('observed_tags',{}).get('CARDTYPE')=='BATTLEGROUND_TRINKET' for e in state.get('choices',[])):
                ROOT = self.root
                with np.load(ROOT/'data/live-ui-1600-legacy.npz',allow_pickle=False) as templates:
                    return float(np.abs(rgb[140:215,630:970].astype(np.int16)-templates['trinket_title'].astype(np.int16)).mean())<16
            if choice:
                header=rgb[70:200,540:1080].astype(np.int16)
                purple=float(((header[:,:,0]>90)&(header[:,:,2]>90)&(header[:,:,1]<header[:,:,2]*.75)).mean())
                if purple<.08:
                    return blocked('等待发现或英雄选择界面显示')
            if choice.get("type") == "MULLIGAN":
                # Stable white outline of the confirmation button. It is absent
                # during the tavern-to-selection transition.
                sample = rgb[679:744, 742:865].astype(np.int16)
                return float(((sample.max(2)-sample.min(2)<35) & (sample.min(2)>155)).mean()) > .12
            if choice:
                # Discover cards: bright, saturated header and unobscured card faces.
                return True
            if 'gold' in state:
                read_gold = self.gold_reader
                shown_gold=read_gold(rgb)
                if shown_gold is None or shown_gold[0] != state['gold']:
                    return blocked(f"等待金币显示同步（日志 {state['gold']}，画面 {shown_gold[0] if shown_gold else '未识别'}）")
            # TaskList zone updates can precede the rendered shop cards. A live
            # reroll button alone is insufficient during that transition.
            shop=state.get('shop',[])
            for index,card in enumerate(shop):
                if card.get('observed_tags',{}).get('CARDTYPE') not in ('MINION','4'):
                    continue
                x=round(800+(index-(len(shop)-1)/2)*116)
                sample=rgb[275:375,x-50:x+50].astype(np.int16)
                r,g,b=sample[:,:,0],sample[:,:,1],sample[:,:,2]
                art_visible = float((((b>r*1.15)|(g>r*1.12)) & (np.maximum(b,g)>70)).mean()) >= .04
                # Divine Shield can cover the whole portrait with yellow light.
                # Tier banners and health gems still establish a rendered minion;
                # do not require a particular artwork colour to continue playing.
                tier = rgb[243:280,x-18:x+18].astype(np.int16)
                health = rgb[360:402,x+18:x+52].astype(np.int16)
                tier_visible = float(((tier[:,:,0]>85)&(tier[:,:,2]>75)&(tier[:,:,1]<tier[:,:,2]*.8)).mean()) > .12
                health_visible = float(((health[:,:,0]>105)&(health[:,:,0]>health[:,:,1]*1.55)&
                                        (health[:,:,0]>health[:,:,2]*1.4)).mean()) > .04
                if not (art_visible or (tier_visible and health_visible)):
                    return blocked(f'等待商店第 {index+1} 张随从显示')
            # Reroll purple face, which is hidden/dimmed during battle and banners.
            sample = rgb[140:195, 919:959].astype(np.int16)
            ready = float(((sample[:,:,0]>65)&(sample[:,:,2]>65)&(sample[:,:,1]<sample[:,:,2]*.72)).mean()) > .22
            return ready or blocked('等待招募画面恢复')

    def scene_stable(self, state):
            import numpy as np
            from .live_legacy_layout import canonical_frame
            rgb=canonical_frame(self.last_rgb)
            # Server effects and option receipts precede visible transforms. Sample
            # card faces across frames so an in-progress replacement is never hit.
            frames=[rgb[245:580:3,480:1130:3].astype(np.int16)]
            if state.get('hand'):
                # Generated/drawn cards animate over the hero before entering the
                # fan. Board stability alone can click the next identical card.
                frames.append(rgb[610:900:3,320:1230:3].astype(np.int16))
            key=(state['game_serial'],state['turn'],state['gold'],
                 tuple(tuple(e['id'] for e in state[z]) for z in ('shop','board','hand','choices')))
            now=self.now
            previous=getattr(self,'_stable_frame',None)
            self._stable_frame=(key,frames,now)
            if (previous is None or previous[0]!=key or len(previous[1])!=len(frames)
                    or any(a.shape!=b.shape for a,b in zip(previous[1],frames))):
                self._stable_since=now
                return False
            changed=max(float((np.abs(a-b).max(2)>35).mean()) for a,b in zip(frames,previous[1]))
            if changed>.035:
                self._stable_since=now
                return False
            return now-getattr(self,'_stable_since',now)>=(.4 if state.get('hand') else .25)


def _value(value):
    if isinstance(value,dict) and 'known' in value:
        return value.get('value') if value.get('known') is True else None
    return value


def legacy_scene_state(before,*,include_gold=False):
    """Map public v2 snapshot or old experience state, without inventing facts."""
    if 'stage' not in before and 'summary' not in before and 'zones' not in before:
        state=copy.deepcopy(before)
        state.setdefault('game_serial',None);state.setdefault('turn',None)
        for zone in ('shop','board','hand','choices'):state.setdefault(zone,[])
        return state
    stage=before.get('stage') or {};summary=before.get('summary') or {};zones=before.get('zones') or {}
    state={'game_serial':(before.get('game_key') or before.get('game_serial') or before.get('token'),stage.get('kind'),stage.get('pending_id'),summary.get('option_batch')),
        'turn':before.get('turn',summary.get('turn'))}
    if include_gold and _value(summary.get('gold')) is not None:state['gold']=_value(summary['gold'])
    for zone in ('shop','board','hand'):
        state[zone]=[]
        for card in zones.get(zone,[]):
            row=copy.deepcopy(card);row.setdefault('id',row.get('entity_id'))
            tags=row.setdefault('observed_tags',{})
            if _value(row.get('facts',{}).get('is_minion'))==1:tags.setdefault('CARDTYPE','MINION')
            state[zone].append(row)
    state['choices']=[]
    for card in stage.get('options',[]):
        row=copy.deepcopy(card);row.setdefault('id',row.get('entity_id'))
        if stage.get('kind')=='trinket':row.setdefault('observed_tags',{})['CARDTYPE']='BATTLEGROUND_TRINKET'
        state['choices'].append(row)
    if stage.get('kind') in {'hero_select','discover','trinket'}:
        state['choice_request']={'type':'MULLIGAN' if stage['kind']=='hero_select' else 'GENERAL','id':stage.get('pending_id')}
    return state


def _valid_rgb(rgb):
    import numpy as np
    return isinstance(rgb,np.ndarray) and rgb.ndim==3 and rgb.shape[2]==3 and rgb.dtype==np.uint8 and rgb.shape[0]>=360 and rgb.shape[1]>=640


def legacy_scene_ready(before,rgb,*,templates_path=None,gold_reader=None):
    """Pure display readiness; does not certify server state or send input.

    gold_reader, when provided, receives canonical RGB and returns (gold,max).
    No glyph bank exists in this deployment; no default OCR is performed.
    """
    if not _valid_rgb(rgb):return {'ready':False,'reason':'尚未取得有效游戏画面','gold_checked':False}
    stage=(before.get('stage') or {}).get('kind') or (before.get('summary') or {}).get('phase') or before.get('phase')
    if before.get('terminal') or stage in {'combat','finished','unknown'}:
        return {'ready':False,'reason':'当前公开阶段不可发送卡牌操作：'+str(stage),'gold_checked':False}
    if stage in {'target','choose_one'}:
        # These are local continuation overlays, not recruit screens.
        return {'ready':False,'reason':'本地抉择/目标由专用菜单显示回执判断','gold_checked':False}
    state=legacy_scene_state(before,include_gold=gold_reader is not None)
    gold_checked='gold' in state and gold_reader is not None
    if gold_reader is None:state.pop('gold',None)
    probe=_LegacyReadinessProbe();probe.last_rgb=rgb;probe.gold_reader=gold_reader
    path=Path(templates_path) if templates_path else Path(__file__).resolve().parents[2]/'data/live-ui-1600-legacy.npz'
    # The legacy method expects root/data/name; an arbitrary injected filename
    # is deliberately not silently redirected to a different template bank.
    if path.name!='live-ui-1600-legacy.npz':return {'ready':False,'reason':'旧版模板文件名不匹配','gold_checked':gold_checked}
    probe.root=path.parent.parent
    try:ready=bool(probe.scene_ready(state))
    except (OSError,ValueError,KeyError) as exc:
        return {'ready':False,'reason':'画面模板不可用：'+str(exc),'gold_checked':gold_checked}
    return {'ready':ready,'reason':None if ready else probe.scene_reason or '等待选择标题或确认按钮显示',
        'gold_checked':gold_checked,'gold_note':None if gold_checked else '金币显示未验证（未配置字库读取器或选择阶段不适用）',
        'method':'experience3-scene-ready-pixels'}


def legacy_scene_stable(before,rgb,previous=None,*,now):
    """Pure temporal detector. Retain returned memory for the next same plan.

    A static combat screenshot can be stable; caller must also require ready.
    Clearing memory after pointer parking preserves the old park reset contract.
    """
    if not _valid_rgb(rgb):return {'stable':False,'reason':'尚未取得有效游戏画面','memory':None}
    import math
    if not math.isfinite(now):raise ValueError('稳定检测时间必须为有限单调时刻')
    state=legacy_scene_state(before,include_gold=True);state.setdefault('gold',None)
    probe=_LegacyReadinessProbe();probe.last_rgb=rgb;probe.now=float(now)
    if previous:
        frame=previous.get('frame');since=previous.get('since')
        if frame is not None and since is not None and now>=frame[2]:
            probe._stable_frame=frame;probe._stable_since=since
    stable=bool(probe.scene_stable(state))
    memory={'frame':probe._stable_frame,'since':probe._stable_since}
    return {'stable':stable,'reason':None if stable else '等待卡面/手牌动画及当前公开菜单稳定','memory':memory}


scene_ready=legacy_scene_ready
scene_stable=legacy_scene_stable
