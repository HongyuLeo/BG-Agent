"""Shared per-game public tribe input; default to the read-only client field."""
from pathlib import Path
import hashlib
from .live_adaptive import LayoutUnavailable

class RaceContextMixin:
    def apply_race_context(self,report,window):
        existing=report.get('facts',{}).get('lobby_races',{})
        complete=len(existing)==11 and all(v.get('known') is True and v.get('source') for v in existing.values())
        our_client_context=complete and all(isinstance(v['source'],dict) and v['source'].get('kind')=='local_public_client_field' for v in existing.values())
        if complete and not our_client_context:return
        if self.config.get('lobby_race_source','client')=='visual':
            return self._apply_visual_race_context(report,window)
        # CREATE_GAME and DebugPrintGame's build line arrive in separate writes.
        # Keep the observation pending until the header arrives. Missing is not
        # a mismatched build, and must not terminate a newly queued game.
        if not report.get('build_numbers'):return
        from .live_client_races import PublicClientRaceReader,check_stop
        if not getattr(self,'client_race_reader',None):
            self.client_race_reader=PublicClientRaceReader(Path(self.config.get('data_root',self.config['session_root']))/'race-client-cache')
        result=self.client_race_reader.observe(report,window,self.config,self.stop_event)
        check_stop(self.config,self.stop_event)
        current=self.native.locate()
        if any(current[k]!=window[k] for k in ('hwnd','pid','exe')):
            from .live_adaptive import WindowIdentityChanged
            raise WindowIdentityChanged('读取种族时客户端身份改变，禁止沿用结果')
        if not complete:
            self.producer.set_public_context({'lobby_races':result['lobby_races']},game_key=report['game_key'],source=result['evidence'])
            if self.journal:self.journal.append('public_client_races',{'game_key':report['game_key'],'result':result})

    def _apply_visual_race_context(self,report,window):
        """A proved whole-lobby list is cached by game, never reread every step."""
        existing=report.get('facts',{}).get('lobby_races',{})
        if len(existing)==11 and all(v.get('known') is True and v.get('source') for v in existing.values()):return
        from .live_public_vision import LobbyRaceReader,public_context
        import uuid
        if self.race_reader is None:self.race_reader=LobbyRaceReader(Path(self.config.get('data_root',self.config['session_root']))/'race-vision-cache')
        key=report['game_key'];result=self.race_reader.get(key)
        if not result or not result.get('known'):
            folder=Path(self.config.get('data_root',self.config['session_root']))/'ui-evidence'/hashlib.sha256(str(key).encode()).hexdigest()[:16]
            folder.mkdir(parents=True,exist_ok=True)
            def capture():
                current,png=self.native.capture()
                if any(current[k]!=window[k] for k in ('hwnd','pid','x','y','width','height')):raise LayoutUnavailable('族表截图时布局变化，稍后重取')
                path=folder/(uuid.uuid4().hex+'.png');path.write_bytes(png)
                if self.journal:self.journal.append('public_ui_capture',{'game_key':key,'evidence':self.journal.capture(png,'screenshot'),'viewport':self.layout_manager.layout.viewport()})
                return self.race_reader.observe(path,key,self.layout_manager.layout.viewport(),roi=self.profile.get('lobby_races_roi'))
            result=capture()
            if not result.get('known'):
                # The measured default is available without manually inserting
                # internal point keys into a JSON profile.
                point=self.calibration.point('fixed:lobby_races_hover')
                self.native.guard(window,self.stop_event);self.native.move(point,window)
                if self.stop_event.wait(self.config.get('lobby_races_hover_seconds',.6)):raise RuntimeError('族表悬停时紧停')
                self.native.guard(window,self.stop_event);result=capture()
        if result and result.get('known'):self.producer.set_public_context(public_context(result),game_key=key,source=result.get('evidence'))
