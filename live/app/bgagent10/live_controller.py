"""Bounded calibrated menu navigation and repeat-game orchestration."""
from __future__ import annotations
import json
from pathlib import Path
import time
from .live_data import atomic
from .live_adaptive import LayoutManager,AdaptiveCalibration
from .live_vision_bridge import RaceContextMixin
from .live_native import InputStopped,WindowChanged
from .live_adaptive import LayoutUnavailable


class QueueController(RaceContextMixin):
    def __init__(self,config,native,stop_event,producer_factory,layout_manager=None):
        self.config=config;self.native=native;self.stop=stop_event;self.producer_factory=producer_factory
        self.profile=json.loads(Path(config['calibration_path']).read_text('utf-8'))
        self.profile.setdefault('layout_profile','hs-37-1600x900')
        from .live_adapter import layout_manager_for
        self.layout_manager=layout_manager or layout_manager_for(native,self.profile,stop_event,config)
        self.calibration=AdaptiveCalibration(self.profile,self.layout_manager)
        self.race_reader=None;self.journal=None;self.stop_event=stop_event
        self.producer=producer_factory();self.offset=0;self.identity=None
    def _snapshot(self,window):
        path=Path(self.config['log_path'])
        if not path.is_file():return {}
        stat=path.stat();identity=(stat.st_dev,stat.st_ino)
        if self.identity is not None and (identity!=self.identity or stat.st_size<self.offset):
            self.producer=self.producer_factory();self.offset=0
        self.identity=identity
        with path.open('rb') as stream:
            stream.seek(self.offset)
            while raw:=stream.read(8*1024*1024):
                self.producer.feed(raw,offset=self.offset,source=str(path.resolve()));self.offset+=len(raw)
        report=self.producer.snapshot()
        return report
    def _check_stop(self):
        if self.stop.is_set() or Path(self.config['emergency_stop_path']).exists():raise InputStopped('排队时紧停')
    def check(self,window):
        self._check_stop()
        return self.layout_manager.ensure(window)
    def _retry_layout(self):
        # Keep the menu latch and pending facts intact. Only the next loop may
        # re-read this same window and retry the missing public observation.
        self.native.release();self._check_stop()
        if self.stop.wait(.05):raise InputStopped('排队窗口恢复时紧停')
        self._check_stop()
    def queue_match(self,previous_game_key,timeout=180):
        """Only calibrated recognized screens are clicked, once per screen identity."""
        window=self.native.locate();deadline=time.monotonic()+timeout
        active_scene=None;candidate_scene=None;candidate_count=0;input_latched=False
        last_gaps=[]
        while time.monotonic()<deadline:
            try:
                window=self.check(window)
                report=self._snapshot(window)
                if report.get('game_key') and report['game_key']!=previous_game_key and not report.get('terminal'):
                    if not report.get('complete'):
                        self.apply_race_context(report,window);report=self.producer.snapshot()
                    if report.get('complete') and report.get('observer') is not None:
                        self._check_stop()
                        return {'window':window,'game_key':report['game_key'],'observer':report.get('observer')}
                    last_gaps=report.get('gaps',[])
                    atomic(Path(self.config['session_root'])/'status.json',{'state':'waiting_public_state','message':'新局已出现，等待完整公开观察，未发送模型操作','gaps':last_gaps})
            except (WindowChanged,LayoutUnavailable):
                self._retry_layout();continue
            except InputStopped:
                self.native.release();raise
            scenes=[]
            try:
                if self.config.get('layout_mode')=='log' and not (report.get('game_key') and report['game_key']!=previous_game_key and not report.get('terminal')):
                    from .live_legacy_menu import capture_menu
                    proof=capture_menu(self.native,window,self.stop)
                    if proof['known'] and (proof['scene']!='result' or report.get('terminal')):
                        scenes.append((proof['scene'],proof))
                for name,cue in self.profile.get('queue_cues',{}).items():
                    proof=self.native.cue(cue,window,self.stop)
                    if proof['matched']:scenes.append((name,proof))
                if not scenes and self.config.get('auto_scene_detection'):
                    from .live_quick_setup import capture_scene
                    proof=capture_scene(self.config,self.native,window,self.stop,report)
                    if proof.get('known') and proof.get('scene') in {'menu','result','home'}:
                        scenes.append((proof['scene'],proof))
            except (WindowChanged,LayoutUnavailable):
                self._retry_layout();continue
            except InputStopped:
                self.native.release();raise
            if len(scenes)>1:raise RuntimeError('排队界面识别冲突，禁止输入')
            if scenes:
                name,proof=scenes[0]
                if name in {'disconnected','login','update'}:raise RuntimeError('需要用户处理客户端：'+name)
                confirmed_scene=name==active_scene
                if active_scene is None:
                    active_scene=name;confirmed_scene=True
                elif name!=active_scene:
                    if candidate_scene==name:candidate_count+=1
                    else:candidate_scene=name;candidate_count=1
                    # Two consecutive, uniquely recognized frames prove a scene
                    # transition. Pixel hashes cannot unlock an input latch.
                    if candidate_count>=2:
                        active_scene=name;input_latched=False;confirmed_scene=True
                        candidate_scene=None;candidate_count=0
                else:candidate_scene=None;candidate_count=0
                if confirmed_scene and name not in {'queueing','loading'}:
                    if not input_latched:
                        point=self.calibration.point('queue:'+name)
                        window=self.check(window);point=self.calibration.point('queue:'+name)
                        if proof.get('buttons'):
                            from .live_quick_setup import capture_scene
                            fresh=capture_scene(self.config,self.native,window,self.stop,report)
                            if not fresh.get('known') or fresh.get('scene')!=name:continue
                            button=fresh['buttons'].get('start' if name=='menu' else 'continue' if name=='result' else 'battlegrounds')
                            if not button:raise ValueError('已识别界面但缺少明确按钮位置：'+name)
                            point=[button['x']/window['width'],button['y']/window['height']]
                            if not all(0<v<1 for v in point):raise ValueError('识别按钮超出当前窗口')
                        input_latched=True
                        try:self.native.gesture([point],window,self.stop)
                        except WindowChanged:
                            self.native.release()
                            # If mouse-down never happened, no click was sent.
                            # Otherwise retain latch until a proved scene change.
                            if not getattr(self.native,'last_input_pressed',True):input_latched=False
                            self._retry_layout()
                        except InputStopped:
                            self.native.release();raise
            else:
                # A transient unknown frame does not establish that the menu was
                # left, nor can it reset a previously submitted input.
                candidate_scene=None;candidate_count=0
            if self.stop.wait(.20):raise InputStopped('排队已停止')
        raise TimeoutError('排队未确认可用的新局公开状态，未重复点击未知界面；缺失：'+json.dumps(last_gaps[:8],ensure_ascii=False))


def run_series(config,adapter,policy,card_mapping,begin,first_session,lease):
    """A single exclusive lease covers result confirmation, menus and next match."""
    from .live import GameSession
    from .live_producer import PublicLogProducer
    from functools import partial
    limit=int(config.get('max_games',1))
    if not 1<=limit<=10000:raise ValueError('连续实战局数范围1..10000')
    session=first_session;root=Path(config['session_root']);receipts=[]
    try:
        for game_index in range(limit):
            result=session.run(begin,external_lease=lease,release_external=False)
            receipts.append(result)
            if result.get('state')=='failed' or first_session.stop_event.is_set():return result
            if result.get('status')!='qualified':
                report={'state':'paused','message':result.get('message') or '实战数据校验未合格，停止自动续局等待审查','error_report':result.get('error_report'),'intake':result,'completed_live_games':game_index}
                atomic(root/'status.json',report);return report
            if game_index==limit-1:break
            atomic(root/'status.json',{'state':'queueing','completed_live_games':len(receipts),'message':'结果已确认，识别菜单并等待下一局'})
            queue=QueueController(config,session.transport.native,first_session.stop_event,partial(PublicLogProducer,rules_path=config.get('rules_path')))
            queue.queue_match(begin['game_key'],config.get('queue_timeout',180))
            transport=adapter.create(config,card_mapping);transport.stop_event=first_session.stop_event
            session=GameSession(config,transport,policy);session.stop_event=first_session.stop_event
            begin=adapter.begin(config,session.model_sha,transport=transport)
        result={'state':'completed','completed_live_games':len(receipts),'intakes':receipts}
        atomic(root/'status.json',result);return result
    finally:lease.__exit__()
