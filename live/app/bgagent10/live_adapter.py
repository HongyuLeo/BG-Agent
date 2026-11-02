"""Native log/UI adapter with explicit per-action receipts and local menu proofs."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import threading
import time
from .live_producer import PublicLogProducer, inspect_log
from .live_encoding import encode_public, IncompleteObservation
from .live_data import digest, VERSION_FIELDS
from .live_menus import Calibration, MenuProtocol, plan_action, effect_matches
from .live_adaptive import LayoutManager,AdaptiveCalibration,LayoutUnavailable,WindowIdentityChanged,ActionUncertain
from .live_vision_bridge import RaceContextMixin


class _UnsentStateChanged(RuntimeError):
    def __init__(self,observation):self.observation=observation


class _ReceiptAvailable(RuntimeError):pass


def layout_manager_for(native,profile,stop,config):
    if config.get('layout_mode')=='log' or profile.get('layout_mode')=='log':
        from .live_log_layout import LogLayoutManager
        return LogLayoutManager(native,profile,stop,config)
    return LayoutManager(native,profile,stop,config)


class NativePublicAdapter:
    source='real-client'
    adapter_id='native-public-v1'
    def create(self,config,card_mapping):return NativeTransport(config,card_mapping)
    def probe_queue(self,config):
        """A positively recognized idle menu may precede the first Power.log."""
        from .live_native import WindowsGame
        native=WindowsGame(title=config['window_title']);stop=threading.Event()
        profile=json.loads(Path(config['calibration_path']).read_text('utf-8'))
        manager=layout_manager_for(native,profile,stop,{**config,'window_wait_seconds':1})
        window=manager.ensure();native.guard(window,stop)
        if Path(window.get('exe','')).resolve()!=Path(config['client_path']).resolve():raise ValueError('排队窗口与目标客户端不符')
        if config.get('layout_mode')=='log':
            # Connection checks identity/geometry/log availability. The bounded
            # queue worker recognizes menus using the reused legacy templates.
            # A current active game takes the ordinary log-based probe path.
            from .live_quick_setup import log_snapshot
            report=log_snapshot(config)
            path=Path(config['log_path'])
            if report.get('game_key') and not report.get('terminal') and path.is_file() and time.time()-path.stat().st_mtime<=30:
                raise ValueError('当前已有对局，转入日志状态检查')
            return {'name':'queue_entry','ok':True,'detail':{'window':window,'method':'legacy-log-geometry','screenshot_required':False,'game_validation':'new game, build, observer and complete state required before policy'}}
        scenes=[]
        for name,cue in profile.get('queue_cues',{}).items():
            proof=native.cue(cue,window,stop)
            if proof['matched']:scenes.append({'scene':name,'proof':proof})
        if not scenes and config.get('auto_scene_detection'):
            from .live_quick_setup import capture_scene
            proof=capture_scene(config,native,window,stop)
            if proof.get('known') and proof.get('scene') in {'menu','home','result'}:
                scenes.append({'scene':proof['scene'],'proof':proof})
        if len(scenes)!=1 or scenes[0]['scene'] not in {'menu','home','result','loading','queueing'}:raise ValueError('当前画面未唯一匹配已校准的排队入口')
        return {'name':'queue_entry','ok':True,'detail':{'scene':scenes[0],'window':window,'game_validation':'deferred until new CREATE_GAME; log build/mode/observer/completeness checked before policy'}}
    def begin(self,config,model_sha,transport=None):
        if transport is None:raise ValueError('开始记录必须绑定已校验的同一transport当前局')
        report=transport.read_snapshot();transport.validate_runtime(report,transport.native.locate());versions=config.get('expected_versions',{})
        from .live import deployment_contract
        contract=deployment_contract(config)
        if report.get('phase') not in contract['report'].get('validated_phases',[]):raise ValueError('当前阶段尚未获跨版本映射放行：'+str(report.get('phase')))
        if any(not versions.get(k) for k in VERSION_FIELDS if k!='policy_version'):raise ValueError('必须登记当前模型兼容版本')
        if not report.get('game_key') or report.get('observer') is None:raise ValueError('对局起点或观察者未锚定')
        actual=copy.deepcopy(report.get('version_contract',{}))
        recorded=dict(versions,policy_version=model_sha,
            model_rules_target=actual.get('model_rules_target',config['model_rules_target']),
            card_data_build=actual.get('card_data_build'),
            installed_client_build=actual.get('installed_client_build'),
            log_build_number=actual.get('log_build_number'))
        # Accurate capture may be qualified for replay without silently treating
        # another client build as accepted255130 auxiliary training data.
        recorded['auxiliary_training_compatible']=recorded['installed_client_build']==recorded['model_rules_target']
        return {'game_key':report['game_key'],'versions':recorded,
            'client_version_contract':actual,'seat_id':report.get('seat_id',report['observer'])}
    def probe(self,config):
        try:
            from .encoding import CardCatalog
            from .engine import DEFAULT_RULES
            catalog=CardCatalog(config.get('rules_path') or DEFAULT_RULES)
            mapping={cid:i-1 for i,cid in enumerate(catalog.runtime_ids) if i}
            transport=self.create(config,mapping)
            transport.layout_manager.config['window_wait_seconds']=config.get('preflight_window_wait_seconds',1)
            before=transport.observe(wait_seconds=1.)
            report=transport.last_snapshot;numeric={k:before[k] for k in ('features','cards','action_mask')}
            window=transport.native.locate();transport.calibration.guard(window)
            binding=transport.validate_runtime(report,window)
            good=bool(report.get('game_key')) and report.get('observer') is not None
            return [{'name':'public_producer','ok':good,'detail':{'game_key':report.get('game_key'),'observer':report.get('observer'),'runtime_binding':binding,'gaps':report.get('gaps',[]),'dimensions':{k:len(v) for k,v in numeric.items()}}}]
        except Exception as exc:return [{'name':'public_producer','ok':False,'detail':str(exc)}]


class NativeTransport(RaceContextMixin):
    source='real-client'
    def __init__(self,config,card_mapping,journal=None,*,native=None,producer=None,layout_manager=None,race_reader=None):
        from .live_native import WindowsGame
        self.config=config;self.mapping=card_mapping;self.journal=journal
        self.native=native or WindowsGame(title=config['window_title'])
        self.profile=json.loads(Path(config['calibration_path']).read_text('utf-8'))
        self.profile.setdefault('layout_profile','hs-37-1600x900')
        self.calibration=Calibration(self.profile);self.menu=MenuProtocol()
        from .live_producer import installed_build
        installed=installed_build(config['client_path']).get('build') if config.get('client_path') else None
        self.producer=producer or PublicLogProducer(rules_path=config.get('rules_path'),card_mapping=card_mapping,
            installed_client_build=installed)
        self.offset=0;self.partial=b'';self.pending={}
        self.stop_event=threading.Event();self.last_snapshot=None;self.raw_evidence=None;self.log_identity=None;self.game_key=None;self.last_bytes_at=0;self.journal_bound=False
        self.layout_manager=layout_manager or layout_manager_for(self.native,self.profile,self.stop_event,config)
        self.calibration=AdaptiveCalibration(self.profile,self.layout_manager)
        self.race_reader=race_reader
    def ensure_layout(self,expected=None):
        self.check_stop();self.layout_manager.stop=self.stop_event
        return self.layout_manager.ensure(expected)
    def check_stop(self):
        emergency=self.config.get('emergency_stop_path')
        control=Path(self.config.get('session_root','.'))/'control.json'
        if self.stop_event.is_set() or emergency and Path(emergency).exists():raise RuntimeError('实战紧停已触发')
        if control.exists() and json.loads(control.read_text('utf-8')).get('command')=='stop':raise RuntimeError('实战停止已登记')
    def read_snapshot(self):
        self.check_stop();self.ensure_layout();path=Path(self.config['log_path']);stat=path.stat()
        identity=(stat.st_dev,stat.st_ino)
        if self.log_identity is not None and (identity!=self.log_identity or stat.st_size<self.offset):raise RuntimeError('当前局日志轮转/截断，停止并保留证据')
        self.log_identity=identity
        if self.journal and not self.journal_bound:
            # A preflight-read transport may be bound to its journal later. Copy
            # consumed evidence once, without reparsing or resetting current state.
            with path.open('rb') as stream:
                remaining=self.offset
                while remaining:
                    evidence=stream.read(min(8*1024*1024,remaining))
                    if not evidence:raise RuntimeError('绑定原始证据时日志变化')
                    self.raw_evidence=self.journal.capture(evidence);remaining-=len(evidence)
            self.journal_bound=True
        with path.open('rb') as stream:
            stream.seek(self.offset);had_bytes=False
            # Initial catch-up reaches EOF before binding game_key. A large file
            # containing historical games is never mistaken for a cross-game input.
            while raw:=stream.read(8*1024*1024):
                had_bytes=True;self.last_bytes_at=time.monotonic()
                previous=self.offset;self.offset+=len(raw);combined=self.partial+raw
                split=combined.rfind(b'\n')
                if split>=0:
                    complete=combined[:split+1];self.producer.feed(complete,offset=previous-len(self.partial),source=str(path.resolve()));self.partial=combined[split+1:]
                else:self.partial=combined
                self.raw_evidence=self.journal.capture(raw) if self.journal else {'path':str(path.resolve()),'offset':previous,'length':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        if not had_bytes and not self.partial and self.last_bytes_at and time.monotonic()-self.last_bytes_at>=.25:
            ledger=getattr(self.producer,'ledger',None)
            if ledger is not None:ledger.seal_options()
        report=self.producer.snapshot()
        window=self.ensure_layout()
        if hasattr(self.producer,'set_public_context') and report.get('game_key') and not report.get('terminal'):
            from .live_native import InputStopped,WindowChanged
            try:self.apply_race_context(report,window)
            except InputStopped:
                self.native.release();raise
            except (LayoutUnavailable,WindowChanged):
                self.check_stop();self.ensure_layout(window)
            report=self.producer.snapshot()
        if self.game_key and report.get('game_key') and report['game_key']!=self.game_key:raise RuntimeError('当前固定模型会话遇到另一局，禁止跨局延续记忆')
        self.game_key=report.get('game_key') or self.game_key;self.last_snapshot=report
        return report
    def validate_runtime(self,report,window):
        import os
        from .service import process_identity
        expected=self.config.get('client_target','37.0.0.255790')
        if int(expected.rsplit('.',1)[1]) not in report.get('build_numbers',[]):raise ValueError('当前日志未证明目标客户端构建：'+expected)
        if report.get('game_type') not in {'GT_BATTLEGROUNDS','GT_BATTLEGROUNDS_FRIENDLY'}:raise ValueError('当前日志不是酒馆战棋单人对局')
        if not report.get('game_key') or report.get('terminal') or report.get('phase') in {'finished','unknown',None}:raise ValueError('旧终局或未开始对局不能作为当前可执行状态')
        stat=Path(self.config['log_path']).stat();age=time.time()-stat.st_mtime
        if not -2<=age<=self.config.get('max_log_age_seconds',30):raise ValueError('当前公开日志不新鲜')
        client=Path(self.config['client_path']).resolve()
        if Path(window.get('exe','')).resolve()!=client:raise ValueError('窗口进程路径与目标客户端不符')
        identity=process_identity(window['pid'])
        if not identity:raise ValueError('无法绑定当前客户端进程创建时间')
        if os.name=='nt':
            created=int(identity)/10000000-11644473600
            if stat.st_mtime+2<created:raise ValueError('日志早于当前客户端进程，不能复用旧局')
        return {'client_pid':window['pid'],'process_created':identity,'client_path':str(client),'log_path':str(Path(self.config['log_path']).resolve()),'log_identity':list(self.log_identity),'log_age_seconds':age,'log_build':report.get('build_numbers')}
    def numeric(self,report):
        if report.get('model_observation') is not None:
            numeric=report['model_observation']
            if tuple(len(numeric[k]) for k in ('features','cards','action_mask'))!=(3227,124,245):raise ValueError('公开观察维度错误')
            return numeric
        numeric=encode_public(report['facts'],self.mapping)
        mapped=report.get('action_mapping',{})
        if report.get('gaps') or mapped.get('gaps') or report.get('unsupported_options'):raise IncompleteObservation(['public action mapping incomplete'])
        commands=report.get('commands',mapped.get('commands',{}))
        mask=report.get('action_mask',mapped.get('action_mask'))
        if mask is None:mask=[int(i in commands or str(i) in commands) for i in range(245)]
        if len(mask)!=245:raise ValueError('动作掩码尺寸错误')
        return dict(numeric,action_mask=mask)
    def normalize(self,report,*,allow_incomplete=False):
        window=self.ensure_layout()
        result={'token':report.get('token') or digest(report),'window':window,'evidence':self.raw_evidence,
            'commands':report.get('commands',report.get('action_mapping',{}).get('commands',{})),
            'facts':report.get('facts',{}),'stage':report.get('stage',{}),'zones':report.get('zones',{}),
            'turn':report.get('turn'),'seat_id':report.get('seat_id',report.get('observer')),'history':report.get('history',[]),
            'terminal':report.get('terminal'),'summary':report.get('summary',{}),'confidence':1.,'missing_fields':[]}
        if result['turn'] is None:result['turn']=report.get('facts',{}).get('globals',{}).get('turn',{}).get('value')
        if not result['summary']:
            result['summary']={key:report.get('facts',{}).get('globals',{}).get(key,{}).get('value') for key in ('gold','tier','frozen')}
            result['summary'].update(phase=report.get('phase'),option_batch=report.get('option_batch',getattr(getattr(self.producer,'ledger',None),'option_batch',None)))
        if result['terminal']:
            result['terminal']=copy.deepcopy(result['terminal'])
            result['terminal']['native_source']=result['terminal'].get('evidence')
            result['terminal']['evidence']=self.raw_evidence
        try:result.update(self.numeric(report))
        except (IncompleteObservation,ValueError):
            if not allow_incomplete and not result['terminal']:raise
        return result
    def observe(self,wait_seconds=None):
        deadline=time.monotonic()+(self.config.get('observation_wait_seconds',30) if wait_seconds is None else wait_seconds)
        last_error=None
        while True:
            report=self.read_snapshot()
            try:
                base=self.normalize(report)
                if base.get('terminal'):return base
                if self.config.get('deployment_contract_path') and (self.menu.pending or any(base.get('action_mask',[]))):
                    from .live import deployment_contract
                    allowed=deployment_contract(self.config)['report'].get('validated_phases',[])
                    if report.get('phase') not in allowed:raise ValueError('当前客户端阶段未在部署映射报告放行：'+str(report.get('phase')))
                if self.menu.pending:return self.menu.overlay(base)
                if any(base['action_mask']):return base
                last_error=ValueError('等待当前玩家公开可行动菜单')
            except IncompleteObservation as exc:last_error=exc
            if time.monotonic()>=deadline:raise TimeoutError('公开观察/当前菜单等待超时：'+str(last_error))
            self.guard(self.native.locate())
            if self.stop_event.wait(.05):raise RuntimeError('等待公开观察时紧停')
    def guard(self,window):
        self.check_stop()
        if getattr(self.native,'down',False):return self.native.guard(window,self.stop_event)
        current=self.ensure_layout(window)
        for pending in self.pending.values():pending['plan']['window']=current
        return current
    def plan(self,index,before):
        before=dict(before,window=self.ensure_layout(before['window']))
        self.calibration.context=before
        plan=plan_action(index,before,self.calibration)
        if plan.get('continuation') and not plan['continuation'].get('model_observation') and hasattr(self.producer,'preview_observation'):
            plan['continuation']=copy.deepcopy(plan['continuation'])
            plan['continuation']['model_observation']=self.producer.preview_observation(plan['command'])
        return plan
    def wait_display(self,before,window,timeout,check_state=None):
        """Only gate rendered readiness; the log remains the state authority."""
        previous_reason=None
        def notify(reason):
            nonlocal previous_reason
            self.check_stop()
            if check_state:check_state()
            if reason!=previous_reason and self.config.get('session_root'):
                from .live_data import atomic
                atomic(Path(self.config['session_root'])/'status.json',
                    {'state':'waiting_public_state','message':reason,
                     'episode_id':getattr(self.journal,'episode_id',None)})
                previous_reason=reason
        return self.native.wait_ready(before,window,self.stop_event,timeout=timeout,on_wait=notify)
    def submit(self,plan,request_id):
        from .live_native import InputStopped,WindowChanged
        if request_id in self.pending:raise ValueError('同一输入禁止重复提交')
        self.guard(plan['window']);fresh=self.observe()
        def cancelled(current):
            return {'cancelled':True,'safe_to_replan':True,'client_input_sent':False,'request_id':request_id,
                'reason':'public_state_changed_before_input','before_token':plan['before_token'],
                'current_token':current['token'],'current_evidence':current.get('evidence')}
        if fresh['token']!=plan['before_token'] or fresh.get('terminal'):return cancelled(fresh)
        # Geometry may have changed after inference; replan the same semantic
        # action against freshly recognized anchors before any input is sent.
        previous=plan['window'];plan=self.plan(plan['index'],fresh)
        if previous!=plan['window'] and self.journal:self.journal.append('layout_replanned',{'request_id':request_id,'before_window':previous,'after_window':plan['window'],'viewport':self.layout_manager.layout.viewport()})
        before=copy.deepcopy(fresh)
        receipts=len(self.last_snapshot.get('receipts',[]))
        self.pending[request_id]={'plan':plan,'before':before,'receipt_count':receipts,'submitted':False,'interrupted':False,'mouse_down_observed':False,'gestures_completed':0}
        # This flag belongs to this request, not the preceding successful click.
        self.native.last_input_pressed=False
        try:
            def check_unsent_state():
                latest=self.normalize(self.read_snapshot(),allow_incomplete=True)
                if latest['token']!=plan['before_token'] or latest.get('terminal'):
                    raise _UnsentStateChanged(latest)
            def check_selected_choice():
                current=self.normalize(self.read_snapshot(),allow_incomplete=True)
                # A receipt can arrive after selection without another click.
                # Hand it to exact confirm() validation before doing anything.
                if len(self.last_snapshot.get('receipts',[]))!=receipts:raise _ReceiptAvailable()
                command=current.get('commands',{}).get(plan['index'],current.get('commands',{}).get(str(plan['index']),{}))
                if (current.get('terminal') or current.get('stage',{}).get('pending_id')!=before.get('stage',{}).get('pending_id')
                        or command.get('entity_id')!=plan['command'].get('entity_id')):
                    raise ActionUncertain('选择期间游戏状态已变化，未再点击确认，请检查当前选择')
            display_stage=before.get('stage',{}).get('kind')
            if plan['gestures'] and (hasattr(self.native,'wait_ready') or hasattr(self.native,'wait_stable')):
                try:
                    if hasattr(self.native,'wait_ready') and display_stage in {'recruit','hero_select','discover','trinket'}:
                        self.wait_display(before,plan['window'],self.config.get('display_wait_seconds',180.),check_unsent_state)
                    elif hasattr(self.native,'wait_stable'):
                        self.native.wait_stable(plan['window'],self.stop_event)
                except TimeoutError as exc:
                    raise LayoutUnavailable('尚未发送输入，等待客户端界面就绪超时：'+str(exc)) from exc
                except _UnsentStateChanged as exc:
                    self.pending.pop(request_id);return cancelled(exc.observation)
                # Animation may have delivered new state while we waited. No
                # mouse-down has happened yet, so discard this proposal safely.
                latest=self.observe();self.check_stop()
                if latest['token']!=plan['before_token'] or latest.get('terminal'):
                    self.pending.pop(request_id);return cancelled(latest)
            if plan['mode']=='cancel':
                self.native.cancel_pending(plan['window'],self.stop_event)
                self.pending[request_id]['mouse_down_observed'] |= bool(getattr(self.native,'last_input_pressed',True))
            else:
                for step,gesture in enumerate(plan['gestures']):
                    if step:
                        # The client must finish the selection animation before
                        # the confirmation click. Never replay the selection.
                        if self.stop_event.wait(.10):raise InputStopped('分步确认前已停止')
                        self.check_stop()
                        if display_stage in {'hero_select','trinket'}:
                            try:
                                check_selected_choice()
                                # MULLIGAN's unselected white border changes after selection.
                                # Reuse legacy select -> settle -> confirm; keep exact
                                # log identity/receipt and window guards for both clicks.
                                if display_stage=='trinket' and hasattr(self.native,'wait_ready'):
                                    self.wait_display(before,plan['window'],8.,check_selected_choice)
                                check_selected_choice()
                            except TimeoutError as exc:
                                raise ActionUncertain('选择步骤已发送，但确认界面尚未就绪：'+str(exc)) from exc
                            except _ReceiptAvailable:
                                self.pending[request_id]['submitted']=True;return
                    self.native.last_input_pressed=False
                    self.native.guard(plan['window'],self.stop_event)
                    self.native.gesture(gesture,plan['window'],self.stop_event)
                    self.pending[request_id]['mouse_down_observed'] |= bool(getattr(self.native,'last_input_pressed',True))
                    self.pending[request_id]['gestures_completed']+=1
                    if self.journal:self.journal.append('client_input_step',{'request_id':request_id,'action':plan['index'],'step':step,'points':gesture,'window':plan['window'],'server_commit_confirmed':False})
            self.pending[request_id]['submitted']=True
        except (WindowChanged,InputStopped) as exc:
            self.pending[request_id]['mouse_down_observed'] |= bool(getattr(self.native,'last_input_pressed',False))
            self.native.release();self.check_stop()
            self.pending[request_id]['interrupted']=True
            if self.journal:self.journal.append('window_input_interrupted',{'request_id':request_id,'reason':str(exc),'mouse_released':True})
    def _result(self,request_id,after,*,kind,proof):
        pending=self.pending.pop(request_id);plan=pending['plan']
        return {'execution':{'confirmed':True,'request_id':request_id,'executed_action':plan['index'],
            'confirmation_kind':kind,'before_evidence':plan.get('before_evidence'),'after_evidence':after.get('evidence'),'proof':proof},
            'after':{k:after.get(k) for k in ('features','cards','action_mask')},'battle_result':after.get('battle_result'),'flags':[]}
    def confirm(self,request_id,timeout,stop_event):
        from .live_native import WindowChanged,InputStopped
        while True:
            try:
                if self.pending[request_id].get('interrupted'):return self.recover_interrupted(request_id,timeout,stop_event)
                return self._confirm_once(request_id,timeout,stop_event)
            except (WindowChanged,InputStopped):
                self.native.release();self.check_stop()
                if request_id not in self.pending:raise
                self.pending[request_id]['interrupted']=True
            except TimeoutError as exc:
                if self.pending.get(request_id,{}).get('plan',{}).get('mode')=='wait_turn':
                    raise LayoutUnavailable('等待下一招募回合超时；本动作没有发送点击：'+str(exc)) from exc
                raise ActionUncertain('输入已尝试发送但未获完整回执/效果，保留证据，禁止重复提交：'+str(exc)) from exc
    def recover_interrupted(self,request_id,timeout,stop_event):
        """Confirm a delivered action first. Never resend an ambiguous action."""
        from .live_native import WindowChanged,InputStopped
        pending=self.pending[request_id];plan=pending['plan'];before=pending['before']
        self.native.release();plan['window']=self.ensure_layout(plan['window'])
        settle=self.config.get('resize_receipt_wait_seconds',2.)
        try:
            # Handles receipt-before-resize and inputs which finished despite
            # mouse release. This path never submits a second gesture.
            return self._confirm_once(request_id,settle,stop_event)
        except TimeoutError:pass
        report=self.read_snapshot();receipts=report.get('receipts',[])[pending['receipt_count']:]
        if receipts:raise ActionUncertain('窗口恢复后已有输入回执但效果未完整确认，保留证据，禁止重复执行')
        attempted=pending.get('mouse_down_observed') or pending.get('submitted') and bool(plan.get('gestures'))
        if attempted and plan['mode']!='open_menu':
            raise ActionUncertain('窗口变化前已发生mouse-down或已完整发送；没有回执不能证明未生效，已暂停且绝不重发')
        if not attempted:
            after=self.normalize(report,allow_incomplete=True)
            if not self.unchanged_public_state(before,after):raise ActionUncertain('未发送提案前公开状态已变，等待复核')
            self.pending.pop(request_id,None)
            return {'cancelled':True,'safe_to_replan':True,'request_id':request_id,'recovery':{'no_mouse_down':True,'no_completed_gesture':True,'public_state_unchanged':True}}
        # No client commitment was logged. Cancel any partial drag/aim before
        # checking the unchanged public state twice across a quiet boundary.
        for _ in range(self.config.get('resize_cancel_attempts',5)):
            window=self.ensure_layout(plan['window']);plan['window']=window
            try:self.native.cancel_pending(window,stop_event);break
            except (WindowChanged,InputStopped):self.native.release();self.check_stop()
        else:raise LayoutUnavailable('窗口持续变化，取消未确认，等待手动检查')
        if hasattr(self.native,'wait_stable'):self.native.wait_stable(plan['window'],stop_event)
        neutral=self.profile.get('cues',{}).get('menu_cleared')
        if not neutral:raise ActionUncertain('本地菜单取消缺正向画面模板，不能推定未生效')
        cancellation=self.native.cue(neutral,plan['window'],stop_event)
        if not cancellation.get('matched'):raise ActionUncertain('本地菜单未获正向取消确认，禁止重复')
        quiet=self.config.get('resize_cancel_quiet_seconds',1.)
        deadline=time.monotonic()+quiet
        after=None
        while True:
            self.check_stop();report=self.read_snapshot();after=self.normalize(report,allow_incomplete=True)
            if report.get('receipts',[])[pending['receipt_count']:]:
                # A delayed commitment appeared; validate it, never replan it.
                try:return self._confirm_once(request_id,timeout,stop_event)
                except TimeoutError as exc:raise ActionUncertain('取消期间出现延迟回执，效果不明，禁止重复') from exc
            if not self.unchanged_public_state(before,after):raise ActionUncertain('中断后公开状态已有变化但缺匹配回执，禁止重复执行')
            if time.monotonic()>=deadline:break
            if stop_event.wait(.05):raise RuntimeError('恢复核对时紧停')
        self.menu.clear();self.pending.pop(request_id,None)
        proof={'local_menu_cancelled_positive':cancellation,'cancel_input_delivered':True,'receipt_count_after':0,'public_state_unchanged':True,
            'quiet_seconds':quiet,'window':after['window'],'viewport':self.layout_manager.layout.viewport()}
        if self.journal:self.journal.append('window_input_cancelled',{'request_id':request_id,'proof':proof,'safe_to_replan':True})
        return {'cancelled':True,'safe_to_replan':True,'request_id':request_id,'recovery':proof}
    @staticmethod
    def unchanged_public_state(before,after):
        if before.get('turn')!=after.get('turn') or after.get('terminal'):return False
        for key in ('gold','tier','frozen','phase','option_batch'):
            if before.get('summary',{}).get(key)!=after.get('summary',{}).get(key):return False
        for zone in ('board','hand','shop'):
            a=before.get('zones',{}).get(zone,[]);b=after.get('zones',{}).get(zone,[])
            if a!=b:return False
        return before.get('stage',{}).get('pending_id')==after.get('stage',{}).get('pending_id')
    def _confirm_once(self,request_id,timeout,stop_event):
        pending=self.pending[request_id];plan=pending['plan'];before=pending['before']
        duration=self.config.get('turn_wait_seconds',180) if plan['mode']=='wait_turn' else timeout
        # A selected hero is acknowledged before the lobby finishes choosing.
        # Only a proven commitment gets the separate transition budget. Keep
        # its absolute deadline across window recovery; never resubmit it.
        hero_transition=before.get('stage',{}).get('kind')=='hero_select'
        deadline=pending.get('observation_deadline',time.monotonic()+duration)
        observation_failure=pending.get('observation_failure')
        while time.monotonic()<deadline:
            if stop_event.wait(.05):raise RuntimeError('等待确认时紧停')
            self.guard(plan['window'])
            if plan['mode'] in {'open_menu','cancel'}:
                if self.config.get('layout_mode')=='log':
                    # Reuse the legacy sequential-input protocol. A local step
                    # is recorded as dispatched, NEVER as a server commitment.
                    # The final selected target/subchoice still requires the
                    # exact SendOption receipt and resulting public-state change.
                    if pending.get('interrupted') or not pending.get('submitted'):
                        raise ActionUncertain('本地分步输入未完整发送，禁止推定已执行')
                    report=self.read_snapshot();after=self.normalize(report,allow_incomplete=True)
                    if report.get('receipts',[])[pending['receipt_count']:]:
                        raise ActionUncertain('本地分步期间出现服务端回执，停止复核，禁止继续点击')
                    if not self.unchanged_public_state(before,after):
                        raise ActionUncertain('本地分步期间公开状态变化，停止复核')
                    kind=plan['continuation']['kind'] if plan['mode']=='open_menu' else 'menu_cleared'
                    if kind=='choose_one':
                        from .live_legacy_visual import legacy_subchoice_ready
                        captured,_=self.native.capture(encode=False)
                        if any(captured[k]!=plan['window'][k] for k in ('hwnd','pid','x','y','width','height')):
                            raise WindowChanged('抉择显示期间窗口变化')
                        if not legacy_subchoice_ready(self.native.last_rgb):continue
                    elif stop_event.wait(.10):raise RuntimeError('分步输入时紧停')
                    self.native.guard(plan['window'],stop_event)
                    if plan['mode']=='open_menu':self.menu.open(plan,before,self.mapping)
                    else:self.menu.clear()
                    after=self.observe()
                    proof={'method':'legacy-sequential-input-with-log-receipt-on-final-step',
                        'local_input_dispatched':True,'server_commit_confirmed':False,
                        'public_options_unchanged':True,'subchoice_frame_checked':kind=='choose_one',
                        'gesture_count':pending.get('gestures_completed',0)}
                    result=self._result(request_id,after,kind='local-input-dispatched',proof=proof)
                    return result
                kind=plan['continuation']['kind'] if plan['mode']=='open_menu' else 'menu_cleared'
                cue=self.profile.get('cues',{}).get(kind)
                if not cue:raise ValueError('分步菜单需要正向视觉确认模板：'+kind)
                proof=self.native.cue(cue,plan['window'],self.stop_event)
                if not proof['matched']:continue
                if self.journal:
                    _,png=self.native.capture()
                    proof['ui_evidence']=self.journal.capture(png,'screenshot')
                if plan['mode']=='open_menu':self.menu.open(plan,before,self.mapping)
                else:self.menu.clear()
                after=self.observe()
                return self._result(request_id,after,kind='local-ui-menu',proof=proof)
            report=self.read_snapshot();after=self.normalize(report,allow_incomplete=True)
            if plan['mode']=='wait_turn':
                if effect_matches(plan,before,after):
                    if not after.get('terminal'):
                        try:after=self.normalize(report)
                        except IncompleteObservation:continue
                    return self._result(request_id,after,kind='public-turn-transition',proof={'turn':after.get('turn'),'terminal':after.get('terminal')})
                continue
            receipts=report.get('receipts',[])[pending['receipt_count']:]
            committed=pending.get('execution_confirmed')
            if not receipts:
                if committed:raise ActionUncertain('已确认的英雄选择回执消失，停止核对，不重复输入')
                continue
            if any(receipt.get('complete') is False for receipt in receipts):
                if committed:raise ActionUncertain('英雄选择已确认，但后续出现未完成的输入回执，停止核对')
                continue
            expected=[plan['expected_receipt']]+plan.get('receipt_aliases',[])
            def matches(receipt):return any(all(receipt.get(k)==v for k,v in alternative.items() if k in {'index','sub','target','position','choice_id','entities'}) for alternative in expected)
            if len(receipts)!=1 or not matches(receipts[0]):raise RuntimeError('输入回执不符/出现外部操作，不重试')
            comparison_before=before
            if self.menu.pending:
                comparison_before=dict(before,stage=self.menu.pending['stage'])
            if not committed and not effect_matches(plan,comparison_before,after):continue
            if hero_transition and not committed:
                committed={'request_id':request_id,'action':plan['index'],
                    'server_commit_confirmed':True,'semantic_effect_confirmed':True,
                    'receipt':copy.deepcopy(receipts[0]),'after_evidence':after.get('evidence'),
                    'client_input_retried':False,'observation_wait_seconds':180}
                pending['execution_confirmed']=committed
                pending['observation_deadline']=deadline=time.monotonic()+180
                if self.journal:self.journal.append('action_execution_confirmed',committed)
            self.menu.clear()
            if not after.get('terminal'):
                try:
                    after=self.normalize(report)
                    if hero_transition and not any(after.get('action_mask',[])):
                        raise IncompleteObservation(['action_mask/no_actionable_menu'])
                except IncompleteObservation as exc:
                    observation_failure={'request_id':request_id,'action':plan['index'],
                        'server_commit_confirmed':True,'semantic_effect_confirmed':True,
                        'policy_observation_complete':False,'receipt':receipts[0],
                        'after_evidence':after.get('evidence'),'phase':report.get('phase'),
                        'stage':after.get('stage'),
                        'gaps':copy.deepcopy(report.get('gaps') or exc.gaps),
                        'client_input_retried':False}
                    if hero_transition:
                        pending['observation_failure']=observation_failure
                        if not pending.get('waiting_status_written'):
                            if self.config.get('session_root'):
                                from .live_data import atomic
                                atomic(Path(self.config['session_root'])/'status.json',
                                    {'state':'waiting_public_state','message':'英雄选择已确认，等待选人阶段结束和招募状态就绪；不会重复点击',
                                     'episode_id':getattr(self.journal,'episode_id',None),
                                     'request_id':request_id,'server_commit_confirmed':True,
                                     'client_input_retried':False})
                            pending['waiting_status_written']=True
                    continue
            # Layout/observation reads may block while a window is unavailable.
            # Check the absolute budget again before completing the decision.
            if pending.get('execution_confirmed') and time.monotonic()>=deadline:break
            if hero_transition and pending.get('waiting_status_written') and self.config.get('session_root'):
                from .live_data import atomic
                atomic(Path(self.config['session_root'])/'status.json',
                    {'state':'running','message':'英雄选择后的对局状态已就绪',
                     'episode_id':getattr(self.journal,'episode_id',None)})
            return self._result(request_id,after,kind='server-receipt-and-effect',proof=receipts[0])
        if pending.get('execution_confirmed'):
            # Window recovery can exhaust the transition budget before the
            # first strict observation attempt. The committed proof still wins.
            observation_failure=observation_failure or dict(pending['execution_confirmed'],
                policy_observation_complete=False,gaps=['post_hero/actionable_observation_unavailable'])
            if self.journal:self.journal.append('action_observation_incomplete',observation_failure)
            names=[g.get('path',str(g)) if isinstance(g,dict) else str(g) for g in observation_failure['gaps']]
            raise LayoutUnavailable('英雄选择已确认，但等待后续可行动状态超过180秒；未重复输入。仍缺少：'+', '.join(names))
        if observation_failure:
            if self.journal:self.journal.append('action_observation_incomplete',observation_failure)
            gaps=observation_failure['gaps']
            names=[g.get('path',str(g)) if isinstance(g,dict) else str(g) for g in gaps]
            raise ActionUncertain('操作回执和效果已确认，但后续公开状态不完整：'+', '.join(names))
        if self.journal:self.journal.append('action_confirmation_timeout',{'request_id':request_id,'action':plan['index'],'semantic':plan['semantic'],'gestures_completed':pending.get('gestures_completed',0),'expected_receipt':plan.get('expected_receipt'),'new_receipts':self.last_snapshot.get('receipts',[])[pending['receipt_count']:],'latest_evidence':self.raw_evidence,'client_input_retried':False})
        stage=plan.get('before_stage',{}).get('kind')
        detail='选择英雄后的确认' if stage=='hero_select' else plan['semantic']['type']
        raise TimeoutError(detail+' 未获完整回执与效果确认，保留记录，不盲重试')
