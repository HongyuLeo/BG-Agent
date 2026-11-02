"""Local desktop entry; subprocesses inherit the same isolated application path."""
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
os.environ['PYTHONUTF8'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONPATH'] = str(ROOT / 'app')
sys.path.insert(0, str(ROOT / 'app'))
try:
    from bgagent10.desktop import main
    main()
except Exception:
    error = traceback.format_exc()
    (ROOT / 'startup-error.txt').write_text(error, encoding='utf8')
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, '启动失败，错误已保存：\n' + str(ROOT / 'startup-error.txt'),
                                       'BGagent 正式版 1.0 开发验证', 0x10)
    raise
