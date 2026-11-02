"""Menu-only template navigation reused from experience 1/2/3; no model-state OCR.
Source live_queue.py SHA256 b7c3a0ddeb7ac930ca6dbf6dca93e937e3d8d76fe3cc20a27b0165988e5fb705.
Only menu_state is reused; old focus/launch/restart/authentication helpers are excluded.
"""
from pathlib import Path
import numpy as np

def template_path():
    for parent in Path(__file__).resolve().parents:
        path=parent/'data/live-ui-1600-legacy.npz'
        if path.is_file():return path
    raise FileNotFoundError('缺少旧版菜单模板')

def menu_state(rgb):
    from .live_legacy_layout import canonical_frame
    rgb=canonical_frame(rgb)
    with np.load(template_path(), allow_pickle=False) as templates:
        def match(name, box, tolerance=24):
            x0,y0,x1,y1=box
            return float(np.abs(rgb[y0:y1,x0:x1].astype(np.int16)-templates[name].astype(np.int16)).mean())<tolerance
        if 'disconnected' in templates and match('disconnected',(620,380,980,515),15):
            return 'disconnected'
        if 'startup' in templates and match('startup',(650,690,950,760),15):
            return 'startup'
        if 'notice_close' in templates and match('notice_close',(735,630,870,680),13):
            return 'notice'
        if 'news_button' in templates and match('news_button',(840,540,965,625),13):
            return 'news'
        if 'news_store' in templates and match('news_store',(520,5,820,50),14):
            return 'news_store'
        if 'home_bg' in templates and match('home_bg',(650,315,945,365),16):
            return 'home'
        if match('menu_title',(560,5,720,36)) and match('menu_start',(1165,690,1262,735),35):
            return 'menu'
        if match('result_frame',(580,485,650,585),20):
            return 'result'
    return 'unknown'

def capture_menu(native,window,stop):
    """Only called between games, never calibrates or encodes model state."""
    from .live_native import WindowChanged
    native.guard(window,stop)
    actual,_=native.capture(encode=False)
    if any(actual[k]!=window[k] for k in ('hwnd','pid','x','y','width','height')):
        raise WindowChanged('菜单检查时窗口变化，重新读取几何')
    scene=menu_state(native.last_rgb)
    return {'known':scene!='unknown','scene':scene,'method':'experience-1-2-3-menu-template','window':actual}
