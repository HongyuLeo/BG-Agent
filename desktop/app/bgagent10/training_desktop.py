"""Training desktop launches the separate live app without owning its lifecycle."""
import os,subprocess,sys
from pathlib import Path
from tkinter import ttk
import tkinter as tk
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
    def training_tab(self):
        super().training_tab()
        self.training_model_code=tk.StringVar(value='等待训练记录…')
        bar=self.run_picker.master
        ttk.Label(bar.master,textvariable=self.training_model_code,style='Accent.TLabel',wraplength=730).pack(after=bar,fill='x',pady=(7,0))
        ttk.Button(bar,text='模拟此模型',command=self.simulate_training_model).pack(side='right',padx=5)

    def simulate_training_model(self):
        if self.run:
            self.simulation_panel.use_training_run(self.run)
            self.tabs.select(self.simulation_panel.parent)

    def refresh_view(self):
        super().refresh_view()
        if not self.run:return
        from .simulation import SimulationService
        try:
            checkpoint,_=SimulationService(PROJECT).latest(self.run)
            self.training_model_code.set(f'训练任务代号：{self.run.name}\n最新模型文件：{checkpoint.name}（步数只在本次训练内比较）')
        except ValueError:
            self.training_model_code.set(f'训练任务代号：{self.run.name}\n最新模型文件：尚未保存，请等待第一个检查点')
    def live_tab(self):
        tab=self.tab('独立实战测试')
        ttk.Label(tab,text='自动操作已移至独立程序',style='Accent.TLabel').pack(anchor='w',pady=12)
        ttk.Label(tab,text='训练与实战分别运行、保存设置和记录。关闭或紧停实战不会暂停训练。\n实战使用模型副本和CPU推理；可以在训练继续时专门测试自动操作。',style='Muted.TLabel').pack(anchor='w',pady=12)
        ttk.Button(tab,text='打开实战自动操作测试',command=lambda:self.guard(open_live_test)).pack(anchor='w',pady=12)
    def data_tab(self):
        from .simulation_desktop import SimulationPanel
        self.simulation_panel=SimulationPanel(self.tab('模型模拟对局'),PROJECT)
    def use_live_checkpoint(self):
        checkpoint=self.guard(self.selected_checkpoint)
        if checkpoint:self.guard(lambda:open_live_test(checkpoint))
    def stop_live_on_close(self):
        if hasattr(self,'simulation_panel'):self.simulation_panel.shutdown()
    def refresh(self):
        try:
            self.refresh_view()
            if self.close_when_safe and not self.service.active_runs():self.destroy();return
        except Exception as exc:self.footer.set('刷新失败（稍后重试）：'+str(exc))
        self.root.after(1000,self.refresh)
