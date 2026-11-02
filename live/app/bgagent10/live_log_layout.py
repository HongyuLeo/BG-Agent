"""Log-driven measured geometry. No capture, OCR, template matching or input."""
from __future__ import annotations
import json
import ntpath
from pathlib import Path
import time
from .live_adaptive import Layout,LayoutUnavailable,WindowIdentityChanged
from .live_native import WindowChanged

SOURCE_PROVENANCE = {'layout_source': 'LOCAL_WORKSPACE/BG-Agent体验版3.0\\bgagent\\live_layout.py', 'layout_sha256': '975d46316856c92ec29e9196910c7c077c100a30e25a46c947974e534b3b0f3a', 'control_source': 'LOCAL_WORKSPACE/BG-Agent体验版3.0\\bgagent\\live.py', 'control_sha256': '5d36cb9d61fd79eb5a070126a89521df5db257190e65307f5951160652bf7fc4', 'reviewed_control_methods': [{'name': '_check_window', 'line': 778, 'end_line': 826}, {'name': '_sync_window', 'line': 828, 'end_line': 875}], 'reuse': 'exact viewport/map_point; identity/rebase principles only, no focus/capture/resize recovery copied'}

def viewport(size):
    width, height = size
    if width < 640 or height < 360:
        raise ValueError('游戏客户区过小，等待恢复窗口')
    # Hearthstone expands the camera horizontally; stretching the full client
    # at 4:3 or ultrawide aspect ratios moves every card away from its centre.
    scale = min(height / 900, width / 1200)
    return ((width - 1600 * scale) / 2, (height - 900 * scale) / 2, scale)

def map_point(point, source_size, target_size):
    sx, sy, ss = viewport(source_size)
    tx, ty, ts = viewport(target_size)
    x = (point[0] * source_size[0] - sx) / ss
    y = (point[1] * source_size[1] - sy) / ss
    mapped = [(tx + x * ts) / target_size[0], (ty + y * ts) / target_size[1]]
    if not all(0 < value < 1 for value in mapped):
        raise ValueError('操作位置不在当前游戏可见区域，等待恢复窗口')
    return mapped


def geometry_layout(reference_size,client_size):
    """Matrix equivalent of the copied map_point, in current Layout's API."""
    sx,sy,ss=viewport(reference_size);tx,ty,ts=viewport(client_size)
    ratio=ts/ss;width,height=client_size
    matrix=[[ratio,0.],[0.,ratio],[tx-sx*ratio,ty-sy*ratio]]
    bounds=[max(0.,tx),max(0.,ty),min(float(width),tx+1600*ts),min(float(height),ty+900*ts)]
    proof={'method':'legacy-log-measured-client-geometry','screenshot_required':False,
        'layout_source_sha256':SOURCE_PROVENANCE['layout_sha256'],
        'reference_camera':[sx,sy,ss],'current_camera':[tx,ty,ts]}
    return Layout(matrix,list(reference_size),list(client_size),bounds,proof)


def _identity(window):
    executable=window.get('exe')
    return {'hwnd':window.get('hwnd'),'pid':window.get('pid'),
        'exe':ntpath.normcase(ntpath.normpath(str(executable))) if executable else None}


class LogLayoutManager:
    """Drop-in LayoutManager using only client geometry and window guards.

    No native.capture/cue/move/focus/standardize call is made. Interrupted input
    remains owned by the existing transport's pending/receipt recovery logic.
    """
    def __init__(self,native,profile,stop,config,resolver=None):
        self.native=native;self.profile=profile if isinstance(profile,dict) else {};self.stop=stop;self.config=dict(config or {})
        self.profile.setdefault('size',[1600,900]);self.reference_size=list(self.profile['size'])
        try:viewport(self.reference_size)
        except (ValueError,TypeError,ZeroDivisionError) as exc:raise LayoutUnavailable('参考客户区尺寸无效') from exc
        self.current=None;self.layout=None;self.identity=None;self.last_reason=None
        self.resolver=None  # Compatibility field, never constructs an image resolver.
    def _check_stop(self):
        if self.stop.is_set():raise RuntimeError('已停止窗口恢复')
        emergency=self.config.get('emergency_stop_path')
        if emergency and Path(emergency).exists():raise RuntimeError('紧停文件已触发')
        root=self.config.get('session_root')
        control=Path(root)/'control.json' if root else None
        if control and control.is_file():
            try:command=json.loads(control.read_text('utf-8')).get('command')
            except (OSError,ValueError) as exc:raise RuntimeError('停止控制文件无法读取，拒绝继续') from exc
            if command=='stop':raise RuntimeError('已登记停止')
    def ensure(self,expected=None):
        deadline=time.monotonic()+float(self.config.get('window_wait_seconds',300))
        identity=self.identity or (_identity(expected) if expected else None)
        previous=expected or self.current
        while True:
            self._check_stop()
            try:
                current=dict(self.native.locate());actual=_identity(current)
                if any(actual.get(k) is None for k in ('hwnd','pid','exe')):raise WindowIdentityChanged('缺窗口/PID/进程身份，拒绝接管')
                if identity and any(value is not None and actual.get(key)!=value for key,value in identity.items()):raise WindowIdentityChanged('游戏窗口/PID/进程已改变，拒绝自动接管')
                if identity is None:identity=actual
                if not current.get('foreground') or current.get('minimized'):raise LayoutUnavailable('等待游戏窗口恢复前台，不抢焦点')
                if hasattr(self.native,'occluded') and self.native.occluded(current):raise LayoutUnavailable('等待游戏窗口解除遮挡')
                if getattr(self.native,'down',False) and previous and any(current[k]!=previous[k] for k in ('x','y','width','height')):
                    raise WindowChanged('输入过程中窗口改变，交由pending事务先释放并核对回执')
                # Guard is the inspected Win32 identity/geometry/foreground guard;
                # it reads no pixels. Re-read races are retried between inputs.
                if hasattr(self.native,'guard'):self.native.guard(current,self.stop)
                layout=geometry_layout(self.reference_size,[current['width'],current['height']])
                self.current=current;self.layout=layout;self.identity=actual;self.last_reason=None
                self.native.adaptive_layout=layout
                return current
            except WindowIdentityChanged:raise
            except WindowChanged:
                if getattr(self.native,'down',False):raise
                self.last_reason='窗口几何仍在变化，重新读取客户区'
            except (RuntimeError,ValueError) as exc:
                self.last_reason=str(exc)
                self._check_stop()
                if identity and hasattr(self.native,'window_exists') and not self.native.window_exists(identity):raise WindowIdentityChanged('原游戏窗口已关闭或进程已更换') from exc
            if time.monotonic()>=deadline:raise LayoutUnavailable('等待可用游戏窗口超时：'+str(self.last_reason))
            if self.stop.wait(float(self.config.get('window_poll_seconds',.03))):raise RuntimeError('等待窗口时已停止')
