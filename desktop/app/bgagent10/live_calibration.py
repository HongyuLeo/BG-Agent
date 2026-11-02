"""Client-area calibration editor. Captures only; clicks stay inside its own Tk UI."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from .live_data import atomic


def validate_profile(profile,build,title):
    if profile.get('build')!=build or profile.get('window_title')!=title:raise ValueError('校准文件绑定的版本/窗口不一致')
    if len(profile.get('size',[]))!=2 or min(profile['size'])<1:raise ValueError('校准尺寸无效')
    for key,point in profile.get('points',{}).items():
        if len(point)!=2 or not all(0<v<1 for v in point):raise ValueError('校准坐标无效：'+key)
    return profile


class CalibrationEditor:
    def __init__(self,root,image_path,profile_path,profile,capture_layout=None):
        from PIL import Image,ImageTk
        self.root=root;self.path=Path(profile_path);self.profile=profile;self.image=Image.open(image_path).convert('RGB');self.corner=None;self.capture_layout=capture_layout
        self.original_size=list(self.image.size)
        profile.setdefault('adaptive',{}).setdefault('reference_image',str(Path(image_path).resolve()))
        profile.setdefault('layout_profile','hs-37-1600x900')
        self.image.thumbnail((1100,700));self.photo=ImageTk.PhotoImage(self.image)
        root.title('BGagent · 窗口坐标与菜单模板校准')
        self.key=tk.StringVar(value='fixed:refresh');self.mode=tk.StringVar(value='point');self.message=tk.StringVar(value='输入校准键，再点图中位置。模板模式依次点左上与右下。')
        bar=ttk.Frame(root,padding=10);bar.pack(fill='x')
        choices={'刷新按钮':('fixed:refresh','point'),'升级按钮':('fixed:upgrade','point'),'冻结按钮':('fixed:freeze','point'),
            '族表悬停位置':('fixed:lobby_races_hover','point'),'英雄技能':('power:0','point'),'额外英雄技能':('power:1','point'),
            '匹配开始画面模板':('queue:menu','cue'),'上一局结果画面模板':('queue:result','cue'),'酒馆入口画面模板':('queue:home','cue'),
            '目标选择画面模板':('target','cue'),'抉择画面模板':('choose_one','cue'),'选择已取消画面模板':('menu_cleared','cue')}
        label=tk.StringVar(value='刷新按钮');picker=ttk.Combobox(bar,textvariable=label,values=list(choices),state='readonly',width=24);picker.pack(side='left',padx=8)
        picker.bind('<<ComboboxSelected>>',lambda event:(self.key.set(choices[label.get()][0]),self.mode.set(choices[label.get()][1])))
        ttk.Radiobutton(bar,text='坐标点',variable=self.mode,value='point').pack(side='left')
        ttk.Radiobutton(bar,text='画面模板',variable=self.mode,value='cue').pack(side='left')
        ttk.Radiobutton(bar,text='布局锚点',variable=self.mode,value='anchor').pack(side='left')
        ttk.Button(bar,text='保存文件',command=self.save).pack(side='right')
        advanced=ttk.Frame(root);advanced.pack(fill='x');show_advanced=tk.BooleanVar(value=False)
        key_entry=ttk.Entry(advanced,textvariable=self.key,width=45)
        ttk.Checkbutton(advanced,text='高级自定义位置（通常无需设置）',variable=show_advanced,command=lambda:key_entry.pack(side='left',padx=8) if show_advanced.get() else key_entry.pack_forget()).pack(side='left',padx=10)
        canvas=tk.Canvas(root,width=self.image.width,height=self.image.height);canvas.pack();canvas.create_image(0,0,image=self.photo,anchor='nw');canvas.bind('<Button-1>',self.click)
        ttk.Label(root,textvariable=self.message,padding=10).pack(fill='x')
        ttk.Label(root,text='坐标键：fixed:refresh / freeze / upgrade / buy_drop / sell_drop / cast_drop，power:0，hand:张数:序号，board:张数:序号，shop:张数:序号，gap:张数:序号，choices:菜单:张数:序号。\n族表只需校准悬停点 fixed:lobby_races_hover，完整中文名单由OCR读取并按局缓存。\n锚点默认自动提取；可框选4个以上分散的稳定边框细节，键名global:名称（共用）/board:名称/hud:名称（独立锚组）。每个独立组至少4个分散点。',wraplength=1050,padding=10).pack(fill='x')
        self.original_path=Path(image_path)
    def click(self,event):
        key=self.key.get().strip()
        if not key:return
        x,y=event.x/self.image.width,event.y/self.image.height
        if not 0<x<1 or not 0<y<1:return
        if self.mode.get()=='point':
            self.profile.setdefault('points',{})[key]=self.reference_point([x,y]);self.message.set('已记录坐标：'+key);return
        if self.corner is None:self.corner=(x,y);self.message.set('已选左上角，请选右下角');return
        x0,y0=self.corner;self.corner=None
        if x<=x0 or y<=y0:self.message.set('右下角必须大于左上角，请重新框选');return
        from PIL import Image
        original=Image.open(self.original_path).convert('RGB');actual_box=[x0,y0,x,y]
        box=self.reference_point([x0,y0])+self.reference_point([x,y])
        crop=original.crop(tuple(round(v*(original.width if i%2==0 else original.height)) for i,v in enumerate(actual_box)))
        if self.mode.get()=='anchor':
            group=key.split(':',1)[0] if ':' in key else 'global'
            if group not in {'global','board','hud'}:raise ValueError('锚组须为global/board/hud')
            anchors=self.profile.setdefault('adaptive',{}).setdefault('anchors',[])
            anchors[:]=[a for a in anchors if a['name']!=key];anchors.append({'name':key,'group':group,'box':box})
            self.message.set('已记录布局锚点：'+key);return
        folder=self.path.parent/'calibration-cues';folder.mkdir(parents=True,exist_ok=True)
        target=folder/(key.replace(':','-')+'.png');crop.save(target)
        spec={'box':box,'image_path':str(target.resolve()),'threshold':10}
        if key.startswith('queue:'):self.profile.setdefault('queue_cues',{})[key.split(':',1)[1]]=spec
        elif key.startswith('race:'):
            _,race,enabled=key.split(':');self.profile.setdefault('lobby_race_cues',{}).setdefault(race,{})[enabled]=spec
        else:self.profile.setdefault('cues',{})[key]=spec
        self.message.set('已记录正向画面模板：'+key)
    def reference_point(self,point):
        if self.capture_layout is None:return point
        import numpy as np
        matrix=self.capture_layout.matrix
        affine=np.array([[matrix[0,0],matrix[1,0],matrix[2,0]],[matrix[0,1],matrix[1,1],matrix[2,1]],[0,0,1.]])
        pixel=np.array([point[0]*self.original_size[0],point[1]*self.original_size[1],1.])
        result=np.linalg.solve(affine,pixel)
        return [float(result[0]/self.profile['size'][0]),float(result[1]/self.profile['size'][1])]
    def save(self):
        atomic(self.path,self.profile);self.message.set('已保存：'+str(self.path))


def main():
    parser=argparse.ArgumentParser(description='BGagent只读截图与校准编辑器')
    parser.add_argument('--config',required=True);parser.add_argument('--image');parser.add_argument('--capture',action='store_true')
    args=parser.parse_args();config=json.loads(Path(args.config).read_text('utf-8'));path=Path(config['calibration_path'])
    profile=json.loads(path.read_text('utf-8')) if path.exists() else {'build':config['expected_build'],'window_title':config['window_title'],'points':{}}
    image_path=Path(args.image) if args.image else path.with_suffix('.capture.png')
    if args.capture:
        if profile.get('adaptive',{}).get('reference_image'):
            import time
            image_path=path.with_name(path.stem+'.capture-'+str(time.time_ns())+'.png')
        root=tk.Tk();root.title('BGagent · 截图准备');root.geometry('540x190')
        text=tk.StringVar(value='点击下方按钮后，请在5秒内切换到游戏窗口。\n只读截图，不自动切换焦点或操作游戏。')
        ttk.Label(root,textvariable=text,padding=24,wraplength=500).pack()
        def capture_after_delay(remaining):
            if remaining:
                text.set(f'{remaining} 秒后截图，请切换到游戏窗口。')
                root.after(1000,lambda:capture_after_delay(remaining-1));return
            try:
                from .live_native import WindowsGame
                window,png=WindowsGame(title=config['window_title']).capture();path.parent.mkdir(parents=True,exist_ok=True);image_path.write_bytes(png)
                size=[window['width'],window['height']]
                layout=None
                if profile.get('size') and profile['size']!=size:
                    from .live_adaptive import AnchorResolver
                    import numpy as np
                    from PIL import Image
                    layout=AnchorResolver(profile,path).resolve(np.asarray(Image.open(image_path).convert('RGB')))
                else:profile['size']=size
                profile['capture_window']=window
                for child in root.winfo_children():child.destroy()
                CalibrationEditor(root,image_path,path,profile,capture_layout=layout);root.deiconify()
            except Exception as exc:
                text.set('截图未完成：'+str(exc)+'\n请重新开始倒计时并切换窗口。');button.configure(state='normal')
        button=ttk.Button(root,text='开始5秒倒计时',command=lambda:(button.configure(state='disabled'),capture_after_delay(5)))
        button.pack(pady=10);root.mainloop();return
    if not image_path.is_file():raise ValueError('请提供当前窗口截图或指定--capture只读截图')
    if not profile.get('size'):
        from PIL import Image
        with Image.open(image_path) as image:profile['size']=list(image.size)
    root=tk.Tk();CalibrationEditor(root,image_path,path,profile);root.mainloop()


if __name__=='__main__':main()
