"""One-button connection and evidence-bound scene references. No mouse input."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
import numpy as np
from PIL import Image
from .service import atomic_json
from .live_adaptive import AnchorResolver,AdaptiveCalibration,Layout,LayoutUnavailable,content_bounds


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def log_snapshot(config):
    path=Path(config.get('log_path',''))
    if not path.is_file():return {'game_key':None,'phase':None,'source':{'log_exists':False}}
    from .live_producer import inspect_log
    report=inspect_log(path,rules_path=config.get('rules_path'))
    report['quick_setup_source']={'path':str(path.resolve()),'size':path.stat().st_size,'mtime':path.stat().st_mtime,'token':report.get('token')}
    return report


class CurrentLogReader:
    """Incremental public log reader; layout checks do not replay whole games."""
    def __init__(self):
        self.identity=None;self.offset=0;self.producer=None;self.last=None;self.changed_at=0
    def __call__(self,config):
        path=Path(config.get('log_path',''))
        if not path.is_file():return {'game_key':None,'phase':None}
        stat=path.stat();identity=(str(path.resolve()),stat.st_dev,stat.st_ino)
        if identity!=self.identity or stat.st_size<self.offset:
            from .live_producer import PublicLogProducer
            self.producer=PublicLogProducer(rules_path=config.get('rules_path'))
            self.identity=identity;self.offset=0;self.last=None
        if stat.st_size!=self.offset or self.last is None:
            with path.open('rb') as stream:
                stream.seek(self.offset)
                while raw:=stream.read(8*1024*1024):
                    self.producer.feed(raw,offset=self.offset,source=str(path.resolve()));self.offset+=len(raw)
            self.last=self.producer.snapshot()
            self.changed_at=time.monotonic()
            self.last['quick_setup_source']={'path':str(path.resolve()),'size':stat.st_size,'mtime':stat.st_mtime,'token':self.last.get('token')}
        elif time.monotonic()-self.changed_at>=.25 and self.producer.ledger.collecting:
            self.producer.ledger.seal_options();self.last=self.producer.snapshot()
            self.last['quick_setup_source']={'path':str(path.resolve()),'size':stat.st_size,'mtime':stat.st_mtime,'token':self.last.get('token')}
        return self.last


def visual_scene(path,report,config,detector=None):
    if detector is None:
        from .live_scene import recognize_scene
        detector=recognize_scene
    image=np.asarray(Image.open(path).convert('RGB'));x0,y0,x1,y1=content_bounds(image)
    viewport={'x':x0,'y':y0,'width':x1-x0,'height':y1-y0}
    result=detector(str(path),game_key=report.get('game_key'),phase=report.get('phase'),viewport=viewport)
    if result.get('known'):return result
    # Hero selection requires both a visible semantic heading and two current
    # public choice names. A phase label alone cannot register a new reference.
    if report.get('phase')=='hero_select' and report.get('game_key'):
        from .live_public_vision import windows_ocr
        from .engine import DEFAULT_RULES
        ocr=windows_ocr(path);text=re.sub(r'\s+','',ocr.get('text',''))
        cards=json.loads((Path(config.get('rules_path') or DEFAULT_RULES)/'source/crates/taverngym/data/cards.json').read_text('utf-8'))['cards']
        names={c['id']:c.get('name_zh','') for c in cards};matched=[]
        for option in report.get('stage',{}).get('options',[]):
            cid=option.get('card_id',{}).get('value');name=names.get(cid,'')
            if len(name)>=2 and re.sub(r'\s+','',name) in text:matched.append(name)
        if len(set(matched))>=2 and any(header in text for header in ('选择英雄','选择你的英雄','选择一个英雄')):
            return {'known':True,'scene':'hero_select','game_key':report['game_key'],'phase':'hero_select','viewport':viewport,
                'evidence':{'kind':'visual-hero-heading-and-current-choice-names','image_sha256':sha(path),'matched_names':matched,'ocr':ocr}}
    return result


def validate_scene(result,report):
    if not result.get('known') or not result.get('evidence'):raise LayoutUnavailable('当前画面尚未正向识别，未创建连接参考')
    scene=result.get('scene');phase=report.get('phase');key=report.get('game_key')
    game_scenes={'hero_select','recruit','combat'}
    if scene in game_scenes:
        if not key or result.get('game_key')!=key or phase!=scene:raise LayoutUnavailable('视觉场景与当前日志对局/阶段不匹配')
    elif scene in {'menu','home','result'}:
        if phase in game_scenes:raise LayoutUnavailable('日志仍在活动对局，拒绝注册菜单参考')
    else:raise LayoutUnavailable('当前场景不在已识别连接范围')
    return scene,key if scene in game_scenes else None


def register_scene(profile,path,result,report):
    scene,key=validate_scene(result,report)
    with Image.open(path) as image:size=list(image.size)
    entry={'scene':scene,'game_key':key,'phase':report.get('phase'),'image_path':str(Path(path).resolve()),'image_sha256':sha(path),'size':size,
        'viewport':result.get('viewport'),'visual_evidence':result['evidence'],'log_source':report.get('quick_setup_source',{}),'created_ns':time.time_ns()}
    adaptive=profile.setdefault('adaptive',{});bank=adaptive.setdefault('scene_references',[])
    bank[:]=[e for e in bank if not(e['scene']==scene and e.get('game_key')==key)];bank.append(entry)
    return entry


def prepare_connection(config,*,native=None,recognizer=None,read_log=None):
    """Default: legacy measured geometry + current logs, no image prerequisite."""
    if config.get('connection_mode')=='visual':
        return _prepare_visual_connection(config,native=native,recognizer=recognizer,read_log=read_log)
    config=dict(config)
    if config.get('follow_current_client_log',True) and config.get('client_path'):
        folders=sorted((Path(config['client_path']).parent/'Logs').glob('Hearthstone_*'),key=lambda p:p.stat().st_mtime,reverse=True)
        if folders:config['log_path']=str((folders[0]/'Power.log').resolve())
    if native is None:
        from .live_native import WindowsGame
        native=WindowsGame(title=config.get('window_title'))
    window=native.locate()
    if not window.get('foreground') or window.get('minimized'):raise LayoutUnavailable('请在倒计时内切回游戏前台后重试连接')
    if config.get('client_path') and Path(window.get('exe','')).resolve()!=Path(config['client_path']).resolve():raise LayoutUnavailable('窗口不是所选客户端')
    from .live_log_layout import LogLayoutManager
    import threading
    profile={'build':config.get('client_target','37.0.0.255790'),'window_title':config.get('window_title'),
        'size':[1600,900],'layout_profile':'hs-37-1600x900','layout_mode':'log','points':{}}
    manager=LogLayoutManager(native,profile,threading.Event(),{**config,'window_wait_seconds':1})
    manager.ensure(window)
    root=Path(config.get('data_root',config.get('session_root','data')))/'connection'
    root.mkdir(parents=True,exist_ok=True);path=root/'log-profile.json'
    defaults=AdaptiveCalibration(profile,manager)
    for key in ['fixed:refresh','fixed:upgrade','fixed:freeze','fixed:buy_drop','fixed:sell_drop','fixed:cast_drop','fixed:hero_confirm','fixed:trinket_confirm','fixed:lobby_races_hover','queue:menu','queue:result','queue:home']:
        value=defaults.default_point(key)
        if value is not None:profile['points'][key]=value
    report=(read_log or log_snapshot)(config)
    profile['connection_window']=window
    atomic_json(path,profile)
    evidence={'state':'prepared','method':'experience-1-2-3-log-and-measured-layout','window':window,
        'log_path':config.get('log_path'),'log':{k:report.get(k) for k in ('phase','game_key','terminal','quick_setup_source')},
        'screenshot_required':False,'real_client_accepted':False}
    atomic_json(root/'latest-log-connection.json',evidence)
    return {**config,'connection_mode':'log','layout_mode':'log','auto_scene_detection':False,
        'calibration_path':str(path.resolve()),'connection':evidence}


def _prepare_visual_connection(config,*,native=None,recognizer=None,read_log=None):
    """GUI calls AFTER its visible five-second countdown; never moves/clicks."""
    config=dict(config)
    if config.get('follow_current_client_log',True) and config.get('client_path'):
        candidates=sorted((Path(config['client_path']).parent/'Logs').glob('Hearthstone_*'),key=lambda p:p.stat().st_mtime,reverse=True)
        if candidates:config['log_path']=str((candidates[0]/'Power.log').resolve())
    if native is None:
        from .live_native import WindowsGame
        native=WindowsGame(title=config.get('window_title'))
    window,png=native.capture()
    if not window.get('foreground') or window.get('minimized'):raise LayoutUnavailable('请在倒计时内切回游戏前台后重试连接')
    if config.get('client_path') and Path(window.get('exe','')).resolve()!=Path(config['client_path']).resolve():raise LayoutUnavailable('截图窗口不是所选客户端')
    root=Path(config.get('data_root',config.get('session_root','data')))/'connection'
    root.mkdir(parents=True,exist_ok=True);image=root/('reference-'+uuid.uuid4().hex+'.png');image.write_bytes(png)
    diagnostic={'image_path':str(image.resolve()),'image_sha256':sha(image),'window':window,
                'log_path':config.get('log_path'),'model_checkpoint':config.get('checkpoint')}
    diagnostic_path=image.with_suffix('.json')
    try:
        report=(read_log or log_snapshot)(config)
        diagnostic['log']={key:report.get(key) for key in ('game_key','phase','terminal','quick_setup_source')}
        result=visual_scene(image,report,config,recognizer)
        diagnostic['recognition']=result
        validate_scene(result,report)
    except Exception as exc:
        diagnostic.update(state='blocked',error_type=type(exc).__name__,message=str(exc))
        atomic_json(diagnostic_path,diagnostic)
        exc.connection_evidence=str(diagnostic_path.resolve())
        raise
    diagnostic['state']='recognized'
    atomic_json(diagnostic_path,diagnostic)
    path=Path(config.get('calibration_path') or root/'profile.json')
    old=json.loads(path.read_text('utf-8')) if path.is_file() else {}
    profile=copy.deepcopy(old)
    profile.update(build=config.get('client_target','37.0.0.255790'),window_title=config.get('window_title'),layout_profile='hs-37-1600x900')
    if not profile.get('size'):
        profile['size']=[window['width'],window['height']]
        profile.setdefault('adaptive',{})['reference_image']=str(image.resolve())
    profile.setdefault('points',{})
    defaults=AdaptiveCalibration(profile,None)
    for key in ['fixed:refresh','fixed:upgrade','fixed:freeze','fixed:buy_drop','fixed:sell_drop','fixed:cast_drop','fixed:hero_confirm','fixed:trinket_confirm','fixed:lobby_races_hover','queue:menu','queue:result','queue:home']:
        point=defaults.default_point(key)
        if point is not None:profile['points'].setdefault(key,point)
    entry=register_scene(profile,image,result,report);profile['capture_window']=window
    atomic_json(path,profile);config['calibration_path']=str(path.resolve())
    # Preserve the selected log target if Power.log has not yet appeared.
    if not config.get('log_path') and config.get('client_path'):
        candidates=sorted((Path(config['client_path']).parent/'Logs').glob('Hearthstone_*'),key=lambda p:p.stat().st_mtime,reverse=True)
        if candidates:config['log_path']=str((candidates[0]/'Power.log').resolve())
    return {**config,'auto_scene_detection':True,'connection':{'state':'prepared','scene':entry['scene'],'reference':entry,'message':'连接资料已自动保存，无需填写坐标或JSON'}}


def capture_scene(config,native,window,stop,report=None):
    """Application runtime only. A saved current screenshot proves each menu."""
    native.guard(window,stop)
    actual,png=native.capture()
    if any(actual[k]!=window[k] for k in ('hwnd','pid','x','y','width','height')):
        from .live_native import WindowChanged
        raise WindowChanged('识别菜单时窗口变化，重新观察')
    folder=Path(config['session_root'])/'scene-evidence';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(hashlib.sha256(png).hexdigest()+'.png')
    if not path.exists():path.write_bytes(png)
    report=log_snapshot(config) if report is None else report
    result=visual_scene(path,report,config)
    if result.get('known') and result.get('scene')=='result' and not report.get('terminal'):
        return {'known':False,'reason':'结果画面已出现，等待日志确认终局','window':actual}
    return {**result,'window':actual}


class SceneAdaptiveResolver:
    """Resolver reads fresh logs before adopting an unmatched new UI scene."""
    def __init__(self,profile,config,*,recognizer=None,read_log=None):
        self.profile=profile;self.config=dict(config);self.recognizer=recognizer;self.read_log=read_log or CurrentLogReader()
        self.active=None;self.local_layout=None;self.active_entry=None
    def validate_cached(self,rgb,layout):
        if self.active is None or self.active_entry is None:return False
        report=self.read_log(self.config);key=self.active_entry.get('game_key')
        if key is not None and key!=report.get('game_key'):return False
        if key is None and report.get('phase') in {'hero_select','recruit','combat'}:return False
        return self.active.validate_cached(rgb,self.local_layout)
    def resolve(self,rgb):
        report=self.read_log(self.config);key=report.get('game_key');phase=report.get('phase')
        refs=self.profile.get('adaptive',{}).get('scene_references',[])
        for entry in reversed(refs):
            if entry.get('game_key') is not None and entry['game_key']!=key:continue
            if entry.get('game_key') is None and phase in {'hero_select','recruit','combat'}:continue
            if not Path(entry['image_path']).is_file() or sha(entry['image_path'])!=entry['image_sha256']:continue
            candidate=copy.deepcopy(self.profile);candidate['size']=entry['size'];candidate['adaptive']={'reference_image':entry['image_path']}
            try:
                resolver=AnchorResolver(candidate);local=resolver.resolve(rgb)
                self.active=resolver;self.local_layout=local;self.active_entry=entry
                return self.compose(local,entry)
            except LayoutUnavailable:pass
        folder=Path(self.config.get('calibration_path','profile.json')).resolve().parent/'scene-references';folder.mkdir(parents=True,exist_ok=True)
        path=folder/(uuid.uuid4().hex+'.png');Image.fromarray(rgb).save(path)
        result=visual_scene(path,report,self.config,self.recognizer)
        entry=register_scene(self.profile,path,result,report)
        atomic_json(Path(self.config['calibration_path']),self.profile)
        # The current raster is the new scene reference, positively identified
        # and bound to the current game; match it rather than guessing a scene.
        candidate=copy.deepcopy(self.profile);candidate['size']=entry['size'];candidate['adaptive']={'reference_image':str(path)}
        resolver=AnchorResolver(candidate);local=resolver.resolve(rgb)
        self.active=resolver;self.local_layout=local;self.active_entry=entry
        return self.compose(local,entry)
    def compose(self,layout,entry):
        # Convert the profile's measured reference camera to this scene's camera
        # before applying image-derived placement. Full-client ratios are unused.
        def camera(size):
            w,h=size;s=min(h/900,w/1200);return (w-1600*s)/2,(h-900*s)/2,s
        rx,ry,rs=camera(self.profile['size']);tx,ty,ts=camera(entry['size']);ratio=ts/rs
        prefix=np.array([[ratio,0,0],[0,ratio,0],[tx-rx*ratio,ty-ry*ratio,1.]])
        matrix=prefix@layout.matrix
        proof={**layout.proof,'scene':entry['scene'],'game_key':entry.get('game_key'),'visual_scene_evidence':entry['visual_evidence']}
        return Layout(matrix,self.profile['size'],layout.client_size,layout.bounds,proof)
