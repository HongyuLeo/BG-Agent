"""Windows foreground-only calibrated input and client-area capture. No automatic focus or resize."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import os,struct,zlib,time
class InputStopped(RuntimeError): pass
class WindowChanged(InputStopped): pass
class WindowsGame:
    def __init__(self, executable="Hearthstone.exe", title=None):
        if os.name != "nt":
            raise RuntimeError("实盘操作需要 Windows")
        self.executable = executable.lower()
        self.window_title = title
        self.u = C.WinDLL("user32", use_last_error=True)
        self.g = C.WinDLL("gdi32", use_last_error=True)
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.u.SetThreadDpiAwarenessContext.argtypes = [W.HANDLE]
        self.u.SetThreadDpiAwarenessContext.restype = W.HANDLE
        self.u.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        for name in ("GetForegroundWindow", "GetDC"):
            getattr(self.u, name).restype = W.HANDLE
        self.u.GetDC.argtypes = [W.HWND]
        self.u.ReleaseDC.argtypes = [W.HWND, W.HDC]
        self.u.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        self.u.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
        self.u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        for name in ("IsWindowVisible", "IsIconic", "SetForegroundWindow"):
            getattr(self.u, name).argtypes = [W.HWND]
        self.u.BringWindowToTop.argtypes = [W.HWND]
        self.u.ShowWindow.argtypes = [W.HWND, C.c_int]
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.g.CreateCompatibleDC.argtypes = [W.HDC]
        self.g.CreateCompatibleDC.restype = W.HDC
        self.g.CreateCompatibleBitmap.argtypes = [W.HDC, C.c_int, C.c_int]
        self.g.CreateCompatibleBitmap.restype = W.HBITMAP
        self.g.SelectObject.argtypes = [W.HDC, W.HANDLE]
        self.g.SelectObject.restype = W.HANDLE
        self.g.DeleteObject.argtypes = [W.HANDLE]
        self.g.DeleteDC.argtypes = [W.HDC]
        self.g.BitBlt.argtypes = [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.HDC, C.c_int, C.c_int, W.DWORD]
        self.g.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, W.LPVOID, W.LPVOID, W.UINT]
        self.down = False

    def locate(self):
        self.u.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        found = []
        callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

        def visit(hwnd, _):
            if not self.u.IsWindowVisible(hwnd):
                return True
            pid = W.DWORD()
            self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
            process = self.k.OpenProcess(0x1000, False, pid.value)
            if not process:
                return True
            try:
                size = W.DWORD(32768)
                path = C.create_unicode_buffer(size.value)
                if self.k.QueryFullProcessImageNameW(process, 0, path, C.byref(size)) and os.path.basename(path.value).lower() == self.executable:
                    if self.window_title:
                        title=C.create_unicode_buffer(512)
                        self.u.GetWindowTextW(hwnd,title,len(title))
                        if title.value != self.window_title:
                            return True
                    rect = W.RECT()
                    self.u.GetClientRect(hwnd, C.byref(rect))
                    if rect.right >= 320 and rect.bottom >= 180:
                        found.append((int(hwnd), pid.value, path.value))
            finally:
                self.k.CloseHandle(process)
            return True

        callback = callback_type(visit)
        self.u.EnumWindows.argtypes = [callback_type, W.LPARAM]
        self.u.EnumWindows(callback, 0)
        if len(found) != 1:
            raise RuntimeError("需要唯一可见的 " + self.executable + " 窗口")
        hwnd, pid, path = found[0]
        rect, origin = W.RECT(), W.POINT(0, 0)
        self.u.GetClientRect(hwnd, C.byref(rect))
        self.u.ClientToScreen(hwnd, C.byref(origin))
        return {"hwnd": hwnd, "pid": pid, "exe": path, "x": origin.x, "y": origin.y,
                "width": rect.right, "height": rect.bottom,
                "foreground": self.u.GetForegroundWindow() == hwnd,
                "minimized": bool(self.u.IsIconic(hwnd))}

    def guard(self, expected, stop):
        self.u.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        if stop.is_set():
            raise InputStopped("已停止")
        hwnd = expected["hwnd"]
        rect, origin, pid = W.RECT(), W.POINT(0, 0), W.DWORD()
        if not self.u.GetClientRect(hwnd, C.byref(rect)):
            raise InputStopped("游戏窗口已关闭")
        self.u.ClientToScreen(hwnd, C.byref(origin))
        self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
        foreground = self.u.GetForegroundWindow()
        # Windows may briefly report NULL while activating a window. Do not
        # inject during that gap, and never refocus over a real other window.
        for _ in range(5):
            if foreground or stop.wait(.01):
                break
            foreground = self.u.GetForegroundWindow()
        if stop.is_set():
            raise InputStopped("已停止")
        window = {**expected, "pid": pid.value, "x": origin.x, "y": origin.y,
                  "width": rect.right, "height": rect.bottom,
                  "foreground": foreground == hwnd,
                  "minimized": bool(self.u.IsIconic(hwnd))}
        if not window["foreground"] or window["minimized"]:
            foreground=self.u.GetForegroundWindow()
            other_pid=W.DWORD()
            self.u.GetWindowThreadProcessId(foreground,C.byref(other_pid))
            raise InputStopped(f"游戏失去前台，已暂停操作（前台进程 {other_pid.value}）")
        if any(window[k] != expected[k] for k in ("hwnd", "pid", "x", "y", "width", "height")):
            raise WindowChanged("游戏窗口位置或尺寸变化，正在重新同步")
        return window

    def _mouse(self, flags, x=0, y=0):
        # The union must include the full x64 MOUSEINPUT size, including alignment.
        class Mouse(C.Structure):
            _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                        ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]
        class Payload(C.Union):
            _fields_ = [("mi", Mouse)]
        class Input(C.Structure):
            _anonymous_ = ("payload",)
            _fields_ = [("type", W.DWORD), ("payload", Payload)]
        event = Input(type=0, mi=Mouse(x, y, 0, flags, 0, 0))
        self.u.SendInput.argtypes = [W.UINT, C.POINTER(Input), C.c_int]
        if self.u.SendInput(1, C.byref(event), C.sizeof(Input)) != 1:
            raise C.WinError(C.get_last_error())

    def release(self):
        if self.down:
            try:
                self._mouse(0x0004)
            finally:
                self.down = False

    def move(self, point, window):
        px = window["x"] + round(point[0] * window["width"])
        py = window["y"] + round(point[1] * window["height"])
        vx, vy = self.u.GetSystemMetrics(76), self.u.GetSystemMetrics(77)
        vw, vh = self.u.GetSystemMetrics(78), self.u.GetSystemMetrics(79)
        self._mouse(0x8000 | 0x4000 | 0x0001,
                    round((px - vx) * 65535 / max(1, vw - 1)),
                    round((py - vy) * 65535 / max(1, vh - 1)))

    def gesture(self, points, window, stop, duration_ms=110):
        self.last_input_pressed = False
        self.guard(window, stop)
        self.move(points[0], window)
        try:
            if stop.wait(0.025):
                raise InputStopped("已停止")
            self.guard(window, stop)
            self._mouse(0x0002)
            self.down = True
            self.last_input_pressed = True
            if len(points) > 1:
                start, finish = points[0], points[-1]
                steps = max(4, round(duration_ms / 12))
                for i in range(1, steps + 1):
                    if stop.wait(duration_ms / steps / 1000):
                        raise InputStopped("已停止")
                    self.guard(window, stop)
                    self.move([start[j] + (finish[j] - start[j]) * i / steps for j in (0, 1)], window)
            # The client polls button state per frame. A 25 ms press can fall
            # between two rendered frames even when the window has focus.
            elif stop.wait(0.100):
                raise InputStopped("已停止")
            self.guard(window, stop)
        finally:
            self.release()
        # Unity can poll the current pointer when consuming mouse-up. Keep it
        # at the release point through a frame before parking or the next input.
        if stop.wait(.075):
            raise InputStopped("已停止；鼠标已松开")
        self.guard(window, stop)

    def capture(self, encode=True):
        window = self.locate()
        if not window["foreground"] or window["minimized"]:
            raise RuntimeError("先将游戏放到前台，再截取校准画面")
        width, height = window["width"], window["height"]
        screen = self.u.GetDC(None)
        memory = self.g.CreateCompatibleDC(screen)
        bitmap = self.g.CreateCompatibleBitmap(screen, width, height)
        previous = self.g.SelectObject(memory, bitmap)
        try:
            if not self.g.BitBlt(memory, 0, 0, width, height, screen, window["x"], window["y"], 0x00CC0020 | 0x40000000):
                raise C.WinError()
            self.g.SelectObject(memory, previous)
            header = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
            info = C.create_string_buffer(header)
            pixels = C.create_string_buffer(width * height * 4)
            if self.g.GetDIBits(memory, bitmap, 0, height, pixels, info, 0) != height:
                raise C.WinError()
            # BGRA -> RGB; ndarray uses the existing numpy dependency.
            import numpy as np
            rgb = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)[:, :, [2, 1, 0]]
            self.last_rgb = rgb.copy()
            if not encode:
                return window, None
            rows = b"".join(b"\0" + row.tobytes() for row in rgb)
            def chunk(kind, data):
                return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            png += chunk(b"IDAT", zlib.compress(rows, 3)) + chunk(b"IEND", b"")
            return window, png
        finally:
            self.g.DeleteObject(bitmap)
            self.g.DeleteDC(memory)
            self.u.ReleaseDC(None, screen)

    def cancel_pending(self,window,stop):
        self.guard(window,stop)
        self.move([.91,.60],window)
        self._mouse(0x0008)
        try:
            if stop.wait(.10):raise InputStopped('取消操作时紧停')
        finally:self._mouse(0x0010)
        self.guard(window,stop)

    def cue(self,spec,window,stop):
        """Positive image evidence for a menu; no presumed success after a click."""
        import numpy as np
        from PIL import Image
        from pathlib import Path
        import hashlib
        self.guard(window,stop);captured,_=self.capture(encode=False)
        if any(captured[k]!=window[k] for k in ('hwnd','pid','x','y','width','height')):raise WindowChanged('截图期间窗口变化')
        box=spec.get('box')
        if not isinstance(box,list) or len(box)!=4 or not all(0<=v<=1 for v in box):raise ValueError('菜单识别区域未校准')
        x0,y0,x1,y1=[round(v*(window['width'] if i%2==0 else window['height'])) for i,v in enumerate(box)]
        patch=self.last_rgb[y0:y1,x0:x1]
        reference=np.asarray(Image.open(Path(spec['image_path'])).convert('RGB'))
        if patch.shape!=reference.shape:raise ValueError('菜单模板尺寸与当前窗口不一致')
        difference=float(np.abs(patch.astype(np.int16)-reference.astype(np.int16)).mean())
        threshold=float(spec.get('threshold',10))
        if not 0<threshold<=35:raise ValueError('菜单模板阈值范围无效')
        return {'matched':difference<=threshold,'difference':difference,'threshold':threshold,
            'image_sha256':hashlib.sha256(patch.tobytes()).hexdigest(),'reference_sha256':hashlib.sha256(reference.tobytes()).hexdigest(),'box':box}

    def public_context(self,profile,window,stop):
        from .live_encoding import RACES
        result={}
        specs=profile.get('lobby_race_cues',{})
        if specs:
            races={}
            for race in RACES:
                rule=specs.get(race)
                if not rule:raise ValueError('完整可用种族提示未校准：'+race)
                enabled=self.cue(rule['enabled'],window,stop);disabled=self.cue(rule['disabled'],window,stop)
                if enabled['matched']==disabled['matched']:raise ValueError('可用种族提示不唯一：'+race)
                races[race]={'value':int(enabled['matched']),'known':True,'source':{'kind':'public-ui-template','enabled':enabled,'disabled':disabled}}
            result['lobby_races']=races
        return result

    def wait_stable(self,window,stop,timeout=4.):
        """Wait for card-area animations to settle; never inject during a resize."""
        import numpy as np
        previous=None;stable_since=None;deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.guard(window,stop);current,_=self.capture(encode=False)
            if any(current[k]!=window[k] for k in ('hwnd','pid','x','y','width','height')):raise WindowChanged('等待动画时窗口变化')
            sample=self.last_rgb[round(window['height']*.2):round(window['height']*.95):4,round(window['width']*.2):round(window['width']*.8):4].astype(np.int16)
            now=time.monotonic()
            if previous is not None and previous.shape==sample.shape and float((np.abs(sample-previous).max(2)>30).mean())<.025:
                if stable_since is None:stable_since=now
                if now-stable_since>=.25:return
            else:stable_since=None
            previous=sample
            if stop.wait(.08):raise InputStopped('等待画面稳定时紧停')
        raise TimeoutError('卡牌区域动画未稳定，禁止发送输入')


_FixedWindowsGame=WindowsGame


class WindowsGame(_FixedWindowsGame):
    """Same-window adaptation; never focuses, resizes or restores user windows."""
    def window_exists(self,expected):
        self.u.IsWindow.argtypes=[W.HWND];self.u.IsWindow.restype=W.BOOL
        if not self.u.IsWindow(expected['hwnd']):return False
        pid=W.DWORD();self.u.GetWindowThreadProcessId(expected['hwnd'],C.byref(pid))
        return pid.value==expected['pid']
    def occluded(self,window):
        self.u.WindowFromPoint.argtypes=[W.POINT];self.u.WindowFromPoint.restype=W.HWND
        self.u.GetAncestor.argtypes=[W.HWND,W.UINT];self.u.GetAncestor.restype=W.HWND
        for x in (.25,.5,.75):
            for y in (.2,.5,.8):
                hwnd=self.u.WindowFromPoint(W.POINT(round(window['x']+window['width']*x),round(window['y']+window['height']*y)))
                if not hwnd:return True
                top=self.u.GetAncestor(hwnd,2);pid=W.DWORD();self.u.GetWindowThreadProcessId(top,C.byref(pid))
                if top!=window['hwnd'] and pid.value!=window['pid']:return True
        return False
    def guard(self,expected,stop):
        _FixedWindowsGame.guard(self,expected,stop)
        if self.occluded(expected):raise WindowChanged('游戏窗口被其他窗口遮挡，等待恢复')
    def cue(self,spec,window,stop):
        import numpy as np,hashlib
        from PIL import Image
        from .live_adaptive import LayoutUnavailable
        self.guard(window,stop)
        layout=getattr(self,'adaptive_layout',None)
        if layout is None:raise LayoutUnavailable('未取得实际视口/锚点布局，不能匹配菜单')
        captured,_=self.capture(encode=False)
        if any(captured[k]!=window[k] for k in ('hwnd','pid','x','y','width','height')):raise WindowChanged('菜单截图期间窗口变化')
        x0,y0,x1,y1=layout.box(spec['box'],spec.get('group','global'))
        if x0<0 or y0<0 or x1>window['width'] or y1>window['height']:raise LayoutUnavailable('菜单识别区域被裁切')
        reference=np.asarray(Image.open(spec['image_path']).convert('RGB'))
        patch=np.asarray(Image.fromarray(self.last_rgb[y0:y1,x0:x1]).resize((reference.shape[1],reference.shape[0]),Image.Resampling.BILINEAR))
        difference=float(np.abs(patch.astype(np.int16)-reference.astype(np.int16)).mean());threshold=float(spec.get('threshold',10))
        if not 0<threshold<=35:raise ValueError('菜单模板阈值无效')
        return {'matched':difference<=threshold,'difference':difference,'threshold':threshold,'image_sha256':hashlib.sha256(patch.tobytes()).hexdigest(),
            'reference_sha256':hashlib.sha256(reference.tobytes()).hexdigest(),'viewport':layout.viewport(),'box':spec['box']}
    def cancel_pending(self,window,stop):
        self.guard(window,stop)
        layout=getattr(self,'adaptive_layout',None)
        if layout is None:raise WindowChanged('取消操作前必须重新定位视口')
        self.last_input_pressed=False
        self.move(layout.normalized([.91,.60]),window);self._mouse(0x0008);self.last_input_pressed=True
        try:
            if stop.wait(.1):raise InputStopped('取消时紧停')
        finally:self._mouse(0x0010)
        self.guard(window,stop)

