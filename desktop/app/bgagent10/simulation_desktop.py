"""Offline model exhibition and per-decision public-state replay."""
import json, os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .simulation import SimulationService
from .service import read_json
from .simulation_board import SimulationBoard


class SimulationPanel:
    def __init__(self, parent, project):
        self.parent=parent;self.service=SimulationService(project)
        self.session=None;self.offset=0;self.rows=[];self.playing=False;self.history=[];self.manifest_seen=False;self.owned=set();self.closed=False
        self.stop_requested=False;self.terminal_stop_seen=False
        self.message=tk.StringVar(value='选择模型后开始模拟，无需打开炉石。')
        self.model=tk.StringVar(value='回放模型：尚未选择模拟记录。')
        self.seed=tk.StringVar();self.greedy=tk.BooleanVar(value=False)
        self.source_modes={'正在训练的模型':'running','指定训练记录':'run','指定模型文件':'checkpoint'}
        self.source_mode=tk.StringVar(value='正在训练的模型');self.source_run=tk.StringVar();self.source_checkpoint=None
        self.source_preview=tk.StringVar();self.run_choices=[]
        sourcebar=ttk.Frame(parent);sourcebar.pack(fill='x',pady=(0,3))
        ttk.Label(sourcebar,text='模拟模型来源').pack(side='left')
        modebox=ttk.Combobox(sourcebar,textvariable=self.source_mode,values=list(self.source_modes),state='readonly',width=17)
        modebox.pack(side='left',padx=5);modebox.bind('<<ComboboxSelected>>',lambda e:self.refresh_source())
        self.run_choice=ttk.Combobox(sourcebar,textvariable=self.source_run,state='readonly',width=30)
        self.run_choice.pack(side='left',padx=4);self.run_choice.bind('<<ComboboxSelected>>',self.choose_run)
        ttk.Button(sourcebar,text='选模型文件…',command=self.browse_model).pack(side='left',padx=3)
        ttk.Button(sourcebar,text='刷新模型',command=self.refresh_source).pack(side='left')
        ttk.Label(parent,textvariable=self.source_preview,style='Accent.TLabel',wraplength=1100).pack(anchor='w',pady=3)
        bar=ttk.Frame(parent);bar.pack(fill='x')
        self.start_button=ttk.Button(bar,text='用所选模型模拟一局',style='Accent.TButton',command=self.start);self.start_button.pack(side='left')
        self.stop_button=ttk.Button(bar,text='停止模拟',command=self.stop);self.stop_button.pack(side='left',padx=6)
        ttk.Label(bar,text='开局种子（留空随机）').pack(side='left',padx=5)
        ttk.Entry(bar,textvariable=self.seed,width=12).pack(side='left')
        ttk.Checkbutton(bar,text='选最高概率动作（防循环）',variable=self.greedy).pack(side='left',padx=10)
        ttk.Label(parent,text='回合末一次规划站位：先完成经营，再执行固定阵型，不反复重排。结果含决策辅助，详见文字记录。',style='Muted.TLabel').pack(anchor='w')
        ttk.Label(parent,textvariable=self.model,wraplength=1100,style='Muted.TLabel').pack(anchor='w',pady=3)
        ttk.Label(parent,textvariable=self.message,style='Accent.TLabel',wraplength=1100).pack(anchor='w',pady=3)
        history=ttk.Frame(parent);history.pack(fill='x',pady=5)
        ttk.Label(history,text='模拟记录').pack(side='left')
        self.picker=ttk.Combobox(history,state='readonly',width=32);self.picker.pack(side='left',padx=6);self.picker.bind('<<ComboboxSelected>>',self.pick)
        ttk.Button(history,text='刷新记录',command=self.reload_history).pack(side='left')
        ttk.Button(history,text='打开记录文件夹',command=self.open_folder).pack(side='left',padx=6)
        ttk.Button(history,text='复制错误报告',command=self.copy_error).pack(side='left')
        panes=ttk.Panedwindow(parent,orient='horizontal');panes.pack(fill='both',expand=True,pady=6)
        left=ttk.Frame(panes,width=230);right=ttk.Frame(panes);panes.add(left,weight=0);panes.add(right,weight=1)
        self.tree=ttk.Treeview(left,columns=('turn','gold','action'),show='headings',selectmode='browse',height=12)
        for key,title,width in [('turn','回合',42),('gold','金币',42),('action','模型执行的操作',150)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,stretch=key=='action')
        scroll=ttk.Scrollbar(left,orient='vertical',command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True);self.tree.bind('<<TreeviewSelect>>',self.show)
        self.views=ttk.Notebook(right);self.views.pack(fill='both',expand=True)
        self.board=SimulationBoard(self.views);self.views.add(self.board,text='棋盘画面')
        text_page=ttk.Frame(self.views);self.views.add(text_page,text='详细文字与概率')
        self.details=tk.Text(text_page,wrap='word',font=('Microsoft YaHei UI',10),background='white',relief='flat',width=50,state='disabled')
        ds=ttk.Scrollbar(text_page,orient='vertical',command=self.details.yview);self.details.configure(yscrollcommand=ds.set);ds.pack(side='right',fill='y');self.details.pack(fill='both',expand=True)
        playback=ttk.Frame(parent);playback.pack(fill='x')
        ttk.Button(playback,text='上一手',command=lambda:self.move(-1)).pack(side='left')
        ttk.Button(playback,text='下一手',command=lambda:self.move(1)).pack(side='left',padx=5)
        self.play_button=ttk.Button(playback,text='自动回放',command=self.toggle_play);self.play_button.pack(side='left')
        ttk.Button(playback,text='上一回合',command=lambda:self.move_turn(-1)).pack(side='left',padx=(12,3))
        ttk.Button(playback,text='下一回合',command=lambda:self.move_turn(1)).pack(side='left')
        self.speed=tk.StringVar(value='正常');ttk.Combobox(playback,textvariable=self.speed,values=['慢速','正常','快速'],state='readonly',width=6).pack(side='left',padx=7)
        ttk.Label(playback,text='橙框 = 当前操作的牌 · 点击卡片查看效果',style='Muted.TLabel').pack(side='left',padx=4)
        self.reload_history()
        if self.history:self.select(self.history[0])
        self.timer=parent.after(700,self.tick)

    def reload_history(self):
        self.history=self.service.sessions();self.picker['values']=[p.name for p in self.history]
        if self.session in self.history:self.picker.current(self.history.index(self.session))

    def select(self, session):
        self.session=session;self.offset=0;self.rows=[];self.manifest_seen=False;self.playing=False
        self.stop_requested=False;self.terminal_stop_seen=False
        self.play_button.configure(text='自动回放');self.tree.delete(*self.tree.get_children());self.set_details('正在读取模拟记录…')
        self.board.clear()
        self.model.set('正在读取模型信息…');self.reload_history();self.refresh()

    def pick(self,event=None):
        i=self.picker.current()
        if i>=0:self.select(self.history[i])

    def start(self):
        try:
            session=self.service.start(self.seed.get().strip() or None,self.greedy.get(),**self.source_arguments());self.owned.add(session);self.select(session)
            self.playing=True;self.play_button.configure(text='暂停回放')
        except Exception as exc:messagebox.showerror('无法开始模拟',str(exc),parent=self.parent)

    def source_arguments(self):
        run=next((p for p in self.run_choices if p.name==self.source_run.get()),None)
        return dict(source=self.source_modes[self.source_mode.get()],run=run,checkpoint=self.source_checkpoint)

    def refresh_source(self):
        self.run_choices=self.service.training_runs()
        self.run_choice.configure(values=[p.name for p in self.run_choices])
        try:
            checkpoint,run=self.service.resolve_model(**self.source_arguments())
            self.source_preview.set(f"待模拟模型：{run.name if run else '自选文件'} / {checkpoint.name}（读取最近保存的权重，训练可以继续）")
        except ValueError as exc:self.source_preview.set(str(exc))

    def choose_run(self,event=None):
        self.source_mode.set('指定训练记录');self.refresh_source()

    def use_training_run(self,run):
        self.source_run.set(Path(run).name);self.source_mode.set('指定训练记录');self.refresh_source()

    def browse_model(self):
        path=filedialog.askopenfilename(parent=self.parent,title='选择要模拟的模型检查点',initialdir=str(self.service.project/'data/runs'),filetypes=[('模型检查点','*.pt')])
        if path:
            self.source_checkpoint=path;self.source_mode.set('指定模型文件');self.refresh_source()

    def stop(self):
        # Stop the visible playback immediately, including a completed session's
        # buffered frames. Worker cancellation alone does not stop this timer.
        self.playing=False;self.stop_requested=True
        self.play_button.configure(text='自动回放')
        # Stop the active exhibition even when a historical replay is selected.
        errors=[];requested=False
        for session in self.service.sessions():
            if self.service.snapshot(session)['process_alive']:
                try:self.service.stop(session);requested=True
                except Exception as exc:errors.append(str(exc))
        self.message.set('画面回放已停止。'+('后台停止请求失败：'+'；'.join(errors) if errors else
            '已请求停止后台模拟，等待当前规则步骤结束。' if requested else '后台模拟已结束。'))

    def set_details(self,text):
        self.details.configure(state='normal');self.details.delete('1.0','end');self.details.insert('end',text);self.details.configure(state='disabled')

    def show(self,event=None):
        selected=self.tree.selection()
        if not selected:return
        row=self.rows[int(selected[0])];v=row['view']
        self.board.set_row(row)
        lines=[f"第 {v['turn']} 回合 · {v['hero']}",f"生命 {v['health']} + 护甲 {v['armor']}　金币 {v['gold']}　酒馆 {v['tier']} 星",f"操作：{row['action_text']}（原始模型概率 {row['probability']:.1%}）",'']
        policy=row.get('decision_policy')
        if policy:
            lines += [f"模型原始首选：{row['raw_preferred_action_text']}",
                      f"防循环后执行概率：{policy['execution_probability']:.1%}",
                      f"本步辅助排除 {len(policy['excluded_actions'])} 个候选" + ('；原始首选被排除。' if policy['preferred_action_excluded'] else '；原始首选未被排除。'),
                      '执行方式：'+('按剩余候选最高评分选择。' if policy['mode']=='greedy' else '按剩余候选分布抽样。'),'']
        for key,title in [('board','场上阵容'),('hand','手牌'),('shop','酒馆商品'),('choices','当前选择')]:
            lines.append(title)
            for card in v[key]:
                stats=f"　{card['attack']}/{card['health']}" if 'attack' in card else ''
                cost=f"　费用 {card['cost']}" if 'cost' in card else ''
                lines.append(f"  {card['slot']}. {'[金色] ' if card.get('golden') else ''}{card['name']}{stats}{cost}")
                if card['text']:lines.append('      '+card['text'])
            if not v[key]:lines.append('  无')
            lines.append('')
        lines.append('原始模型概率最高的合法动作（应用防循环辅助之前）')
        lines += [f"  {x['probability']:.1%}  {x['text']}" for x in row['top_actions']]
        result=read_json(self.session/'result.json') if self.session else None
        if result:
            lines+=['','最终排名']+[f"  {seat+1}号{'（模型）' if seat==result['learner_seat'] else ''}：第{rank}名" for seat,rank in enumerate(result['placements'])]
        self.set_details('\n'.join(lines))

    def move(self,delta):
        if not self.rows:return
        selected=self.tree.selection();index=int(selected[0]) if selected else -1
        index=max(0,min(len(self.rows)-1,index+delta));self.tree.selection_set(str(index));self.tree.see(str(index));self.show()

    def toggle_play(self):
        self.stop_requested=False
        self.playing=not self.playing;self.play_button.configure(text='暂停回放' if self.playing else '自动回放')
        if self.playing and self.tree.selection() and int(self.tree.selection()[0])==len(self.rows)-1:
            self.tree.selection_set('0');self.show()

    def move_turn(self,delta):
        if not self.rows:return
        self.playing=False;self.play_button.configure(text='自动回放')
        selected=self.tree.selection();index=int(selected[0]) if selected else 0
        turn=self.rows[index]['view']['turn']
        candidates=[i for i,r in enumerate(self.rows) if (r['view']['turn']-turn)*delta>0]
        if candidates:
            target=min(candidates) if delta>0 else max(candidates)
            previous=self.rows[target]['view']['turn']
            target=next(i for i,r in enumerate(self.rows) if r['view']['turn']==previous)
            self.tree.selection_set(str(target));self.tree.see(str(target));self.show()

    def refresh(self):
        self.refresh_source()
        active=any(self.service.snapshot(p)['process_alive'] for p in self.service.sessions())
        self.start_button.configure(state='disabled' if active else 'normal')
        if not self.session:return
        status=self.service.snapshot(self.session);self.message.set(status.get('message','等待开始'))
        if status.get('state') in ('stopped','failed','paused') and not self.terminal_stop_seen:
            self.terminal_stop_seen=True;self.playing=False
            self.play_button.configure(text='自动回放')
        if self.stop_requested:
            self.message.set('画面回放已停止。'+('正在等待后台模拟退出。' if active else '后台模拟已结束。'))
        self.stop_button.configure(state='normal' if active or self.playing else 'disabled')
        manifest=read_json(self.session/'manifest.json')
        if manifest and not self.manifest_seen:
            original=Path(manifest['request']['checkpoint']);actual=Path(manifest['checkpoint'])
            note=' · 使用已审查修复副本' if original!=actual else ''
            note+=' · 防循环辅助' if manifest.get('exhibition_decoder') else ' · 历史原始策略（未启用防循环）'
            self.model.set(f"当前回放使用：{original.parent.parent.name} / {original.name} · {manifest['actor_version']}{note}\n累计训练 {manifest['model_counters'].get('completed_games',0)} 局 · 开局种子 {manifest['request']['seed']} · 模型座位 {manifest['learner_seat']+1} · {manifest['opponents']['mode']} 固定对手")
            self.manifest_seen=True
        path=self.session/'replay.jsonl'
        if path.exists():
            with path.open('rb') as f:
                f.seek(self.offset)
                # Bounded ingestion keeps Stop responsive with a large backlog.
                for _ in range(100):
                    line=f.readline()
                    if not line.endswith(b'\n'):break
                    row=json.loads(line);row.pop('observation',None);i=len(self.rows);self.rows.append(row)
                    self.tree.insert('', 'end',iid=str(i),values=(row['view']['turn'],row['view']['gold'],row['action_text']));self.offset=f.tell()
        if self.rows and not self.tree.selection():self.tree.selection_set('0');self.show()

    def tick(self):
        if self.closed:return
        try:
            self.refresh()
            if self.playing:
                selected=self.tree.selection()
                if selected and int(selected[0])==len(self.rows)-1:
                    if self.session and not self.service.snapshot(self.session)['process_alive']:self.playing=False;self.play_button.configure(text='自动回放')
                else:self.move(1)
        except Exception as exc:self.message.set('读取模拟记录失败：'+str(exc))
        self.timer=self.parent.after({'慢速':1500,'正常':700,'快速':250}[self.speed.get()],self.tick)

    def open_folder(self):
        os.startfile(str(self.session or self.service.root))

    def copy_error(self):
        if not self.session:return
        status=self.service.snapshot(self.session)
        report=read_json(Path(status['error_report']),status) if status.get('error_report') else read_json(self.session/'errors/error.json',status)
        self.parent.clipboard_clear();self.parent.clipboard_append(json.dumps(dict(session=str(self.session),report=report),ensure_ascii=False,indent=2))

    def shutdown(self):
        if self.closed:return
        self.closed=True
        self.parent.after_cancel(self.timer)
        for session in self.owned:self.service.stop(session)
