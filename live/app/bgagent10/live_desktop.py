"""Dedicated live test UI: no training service, worker control or shared data."""
import argparse,json,os,time,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk
from .desktop import Desktop,BG
from .service import read_json,atomic_json
from .live_workspace import PROJECT,settings,bounded_config,snapshot_model

class LiveDesktop(Desktop):
    def __init__(self,root,checkpoint=None):
        # Do not call Desktop.__init__: it owns training process discovery/control.
        self.root=root;self.data_root=PROJECT/'data';self.closing=False
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='live-test-ui')
        self.model_info_task=None;self.model_info_key=None
        self.task=None;self.live_preflight=None;self.prepared_live_config=None;self.last_live_signature=None
        self.root.title('BGagent · 实战自动操作测试（独立）');self.root.geometry('1240x850');self.root.minsize(1000,680);self.root.configure(bg=BG);self.style()
        header=ttk.Frame(root,padding=20);header.pack(fill='x')
        ttk.Label(header,text='BGagent 实战测试',style='Title.TLabel').pack(side='left')
        ttk.Label(header,text='独立模型副本 · CPU推理 · 不控制训练进程',style='Muted.TLabel').pack(side='left',padx=16)
        self.footer=tk.StringVar(value='测试记录仅保存在独立目录；关闭本窗口只停止实战。')
        ttk.Label(root,textvariable=self.footer,padding=16).pack(side='bottom',fill='x')
        self.tabs=ttk.Notebook(root);self.tabs.pack(fill='both',expand=True,padx=16,pady=8)
        saved=settings(read_json(self.data_root/'live-settings.json',{}))
        if checkpoint:saved['checkpoint']=checkpoint
        self.live_extra_config={}
        self.live_vars={k:tk.StringVar(value=str(v)) for k,v in bounded_config({**saved,'session_root':str(self.data_root/'live-sessions'/str(time.time_ns()))}).items() if not isinstance(v,bool)}
        for k,v in [('checkpoint',''),('window_title','炉石传说'),('client_path','D:/Hearthstone/Hearthstone.exe'),('log_path','')]:
            if k not in self.live_vars:self.live_vars[k]=tk.StringVar(value=v)
        tab=self.tab('自动操作')
        ttk.Label(tab,text='选择模型 → 连接并开始实战 → 5秒内切回炉石',style='Accent.TLabel').pack(anchor='w',pady=(0,10))
        ttk.Label(tab,text='可与训练同时运行。开始前复制所选模型，训练产生新检查点不会改变正在测试的模型。',style='Muted.TLabel').pack(anchor='w')
        form=ttk.Frame(tab);form.pack(fill='x',pady=10);form.columnconfigure(1,weight=1)
        for row,(key,label) in enumerate([('checkpoint','测试使用的模型'),('window_title','游戏窗口标题'),('client_path','游戏程序')]):
            ttk.Label(form,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
            ttk.Entry(form,textvariable=self.live_vars[key]).grid(row=row,column=1,sticky='ew',pady=4)
            if key!='window_title':ttk.Button(form,text='选择…',command=lambda k=key:self.browse_live(k)).grid(row=row,column=2,padx=8)
        self.model_info_text=tk.StringVar(value='正在读取所选模型的实际训练记录…')
        ttk.Label(tab,textvariable=self.model_info_text,style='Muted.TLabel',wraplength=1100).pack(anchor='w',fill='x',pady=(0,6))
        ttk.Button(tab,text='选择最新训练模型',command=lambda:self.guard(self.select_latest_model)).pack(anchor='w',pady=(0,10))
        options=ttk.Frame(tab);options.pack(fill='x')
        self.live_auto_queue=tk.BooleanVar(value=saved.get('auto_queue',True));self.live_max_games=tk.StringVar(value=str(saved.get('max_games',2)))
        ttk.Checkbutton(options,text='结束后自动下一局',variable=self.live_auto_queue).pack(side='left')
        ttk.Label(options,text='本次最多局数').pack(side='left',padx=10);ttk.Spinbox(options,from_=1,to=10000,width=7,textvariable=self.live_max_games).pack(side='left')
        ttk.Button(options,text='保存设置',command=lambda:self.guard(self.save_live_settings)).pack(side='right')
        bar=ttk.Frame(tab);bar.pack(fill='x',pady=12)
        self.quick_start_button=ttk.Button(bar,text='连接并开始实战',command=self.quick_start_live);self.quick_start_button.pack(side='left')
        self.preflight_button=ttk.Button(bar,text='检查模型与连接',command=lambda:self.live_countdown(self.preflight));self.preflight_button.pack(side='left',padx=8)
        self.live_start_button=ttk.Button(bar,text='开始实战',command=lambda:self.live_countdown(self.start_live),state='disabled');self.live_start_button.pack(side='left')
        for text,fn in [('紧急停止',self.stop_live),('解除紧停',lambda:self.guard(self.clear_live_stop)),('复制问题报告',lambda:self.guard(self.copy_live_report))]:ttk.Button(bar,text=text,command=fn).pack(side='left',padx=8)
        self.live_text=self.text_area(tab)
        data=self.tab('测试记录');ttk.Label(data,text='这些记录只属于实战测试，不会自动用于训练。').pack(anchor='w')
        ttk.Button(data,text='打开测试文件夹',command=lambda:os.startfile(str(self.data_root))).pack(anchor='w',pady=8)
        ttk.Button(data,text='刷新测试统计',command=self.refresh_data).pack(anchor='w',pady=8)
        self.data_text=self.text_area(data);self.discover_live_paths()
        self.write_text(self.live_text,'在炉石酒馆战棋菜单点击连接；也可以检查当前对局。实机效果仍由你验收。')
        self.root.protocol('WM_DELETE_WINDOW',self.on_close);self.refresh()

    def select_latest_model(self):
        from .live_model_info import latest_checkpoint
        path=latest_checkpoint(PROJECT.parent/'data/runs')
        if path is None:raise ValueError('尚未找到已经保存的训练检查点')
        self.live_vars['checkpoint'].set(str(path))
        self.footer.set('已选择最新落盘模型；将在下次连接时使用，本局固定模型不变。')

    def refresh_model_summary(self):
        from .live_model_info import inspect_checkpoint,format_summary
        path=self.live_vars['checkpoint'].get().strip()
        try:
            stamp=Path(path).stat() if path else None
            key=(path,stamp.st_size,stamp.st_mtime_ns) if stamp else (path,None,None)
        except OSError:key=(path,None,None)
        if self.model_info_task and self.model_info_task[0].done():
            future,requested=self.model_info_task;self.model_info_task=None
            if requested==key:
                try:self.model_info_text.set(format_summary(future.result()))
                except Exception as exc:self.model_info_text.set('模型信息暂不可用：'+str(exc))
        if key!=self.model_info_key and self.model_info_task is None and not self.task:
            self.model_info_key=key
            if not path:self.model_info_text.set('请选择已保存的训练模型。');return
            self.model_info_text.set('正在读取所选模型的实际训练记录…')
            self.model_info_task=(self.executor.submit(inspect_checkpoint,path),key)

    def live_config(self):return bounded_config(super().live_config())
    def discover_live_paths(self):
        client=Path(self.live_vars['client_path'].get())
        if client.is_file():
            logs=list((client.parent/'Logs').glob('*/Power.log'))
            if logs:self.live_vars['log_path'].set(str(max(logs,key=lambda p:p.stat().st_mtime_ns)))
    def _check_open(self,config):
        if self.closing or Path(config['emergency_stop_path']).exists():raise RuntimeError('实战已停止，不会继续启动')
    def _prepare(self,config):
        from .live_quick_setup import prepare_connection
        from .live_setup import prepare_model
        self._check_open(config);config=dict(config,checkpoint=snapshot_model(config['checkpoint']))
        self._check_open(config);config=prepare_model(config)
        self._check_open(config);config=prepare_connection(config);self._check_open(config)
        return config
    def preflight(self):
        config=self.live_config();signature=json.dumps(config,sort_keys=True)
        def work():
            from .live import preflight,record_failure
            try:
                prepared=self._prepare(config);return dict(preflight(prepared),_prepared_config=prepared)
            except Exception as exc:return record_failure(config['session_root'],exc,state='blocked',stage='isolated_preflight')
        def done(result):
            self.prepared_live_config=result.pop('_prepared_config',None);self.live_preflight=result;self.last_live_signature=signature
            self.live_start_button.configure(state='normal' if result.get('ok') else 'disabled')
        self.async_call(work,self.live_text,done)
    def connect_and_start(self):
        config=self.live_config()
        def work():
            from .live import start,record_failure
            try:
                prepared=self._prepare(config);self._check_open(prepared);return start(prepared)
            except Exception as exc:return record_failure(config['session_root'],exc,state='blocked',stage='isolated_connection')
        self.async_call(work,self.live_text)
    def start_live(self):
        if self.closing:return
        return super().start_live()
    def refresh(self):
        if self.closing:return
        try:
            self.refresh_model_summary()
            if self.task and self.task[0].done():
                future,widget,callback=self.task;self.task=None
                try:
                    result=future.result()
                    if callback:callback(result)
                    self.write_text(widget,self.format_result(result,widget))
                except Exception as exc:self.write_text(widget,'操作未完成：'+str(exc))
            if json.dumps(self.live_config(),sort_keys=True)!=self.last_live_signature:self.live_start_button.configure(state='disabled')
            self.preflight_button.configure(state='disabled' if self.task else 'normal')
            self.quick_start_button.configure(state='disabled' if self.task or getattr(self,'live_countdown_pending',False) else 'normal')
            if not self.task and not getattr(self,'live_countdown_pending',False):
                path=Path(self.live_vars['session_root'].get())/'status.json'
                if path.exists() and path.stat().st_mtime_ns!=getattr(self,'last_live_status_stamp',None):
                    self.last_live_status_stamp=path.stat().st_mtime_ns;self.write_text(self.live_text,self.format_result(read_json(path,{}),self.live_text))
        except Exception as exc:self.footer.set(str(exc))
        self.root.after(700,self.refresh)
    def stop_live_on_close(self):
        config=self.live_config();atomic_json(Path(config['emergency_stop_path']),{'command':'stop','source':'isolated_live_close'})
        from .live import stop
        stop(config['session_root'])
    def on_close(self):
        self.closing=True;self.live_countdown_pending=False;self.stop_live_on_close()
        self.executor.shutdown(wait=False,cancel_futures=True);self.root.destroy()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--checkpoint');args=parser.parse_args()
    import torch
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    root=tk.Tk();LiveDesktop(root,args.checkpoint);root.mainloop()
