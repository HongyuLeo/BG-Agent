"""Standalone entry. This process has no CUDA context or training controller."""
from pathlib import Path
import os,sys,traceback
ROOT=Path(__file__).resolve().parent
os.environ.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',
    PYTHONPATH=str(ROOT/'app'),CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'app'))
try:
    from bgagent10.live_desktop import main
    main()
except Exception:
    path=ROOT/'startup-error.txt';path.write_text(traceback.format_exc(),'utf8')
    if os.name=='nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,'启动失败，报告已保存：\n'+str(path),'BGagent 实战测试',0x10)
    raise
