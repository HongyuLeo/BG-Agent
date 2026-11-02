"""Training desktop launches the separate live app without owning its lifecycle."""
import os,subprocess,sys
from pathlib import Path
from tkinter import ttk
from .desktop import Desktop

PROJECT=Path(__file__).resolve().parents[2]

def open_live_test(checkpoint=None):
    folder=PROJECT/'实战自动操作测试';entry=folder/'start.py'
    if not entry.is_file():raise ValueError('独立实战测试入口尚未安装')
    python=Path(sys.executable).with_name('pythonw.exe')
    if not python.exists():python=Path(sys.executable)
    command=[str(python),'-B',str(entry)]
    if checkpoint:command+=['--checkpoint',str(Path(checkpoint).resolve())]
    # Child environment only; do not change the training UI/worker environment.
    env=os.environ.copy();env.update(PYTHONPATH=str(folder/'app'),PYTHONDONTWRITEBYTECODE='1',CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    return subprocess.Popen(command,cwd=folder,env=env,stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

class TrainingDesktop(Desktop):
    def __init__(self,root,data_root):
        super().__init__(root,data_root)
        root.title('BGagent 正式版1.0 · 模型训练')
    def live_tab(self):
        tab=self.tab('独立实战测试')
        ttk.Label(tab,text='自动操作已移至独立程序',style='Accent.TLabel').pack(anchor='w',pady=12)
        ttk.Label(tab,text='训练与实战分别运行、保存设置和记录。关闭或紧停实战不会暂停训练。\n实战使用模型副本和CPU推理；可以在训练继续时专门测试自动操作。',style='Muted.TLabel').pack(anchor='w',pady=12)
        ttk.Button(tab,text='打开实战自动操作测试',command=lambda:self.guard(open_live_test)).pack(anchor='w',pady=12)
    def data_tab(self):pass
    def use_live_checkpoint(self):
        checkpoint=self.guard(self.selected_checkpoint)
        if checkpoint:self.guard(lambda:open_live_test(checkpoint))
    def stop_live_on_close(self):pass
    def refresh(self):
        try:
            self.refresh_view()
            if self.close_when_safe and not self.service.active_runs():self.destroy();return
        except Exception as exc:self.footer.set('刷新失败（稍后重试）：'+str(exc))
        self.root.after(1000,self.refresh)
