"""Simple responsive public-state board; no game logic and no hidden-state input."""
import math
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

ZONE_META = [('shop','酒馆商品',8,'#e6f1ff','#3973b9'),
             ('board','己方场上',7,'#e5f4ef','#287b64'),
             ('hand','手牌',10,'#f3ecff','#8061ad'),
             ('choices','当前待选项',0,'#fff1d9','#ad7726')]


def highlighted_slots(action):
    from .live_encoding import decode_action
    a=decode_action(action);kind=a['type'];slots=set()
    if kind=='buy':slots.add(('shop',a['shop']+1))
    elif kind in ('sell','activate'):slots.add(('board',a['board']+1))
    elif kind=='choice':slots.add(('choices',a['option']+1))
    elif kind in ('play','magnetize'):
        slots.add(('hand',a['hand']+1))
        if kind=='magnetize':slots.add(('board',a['board']+1))
    elif kind=='reorder':slots.add(('board',a['board']+1))
    return slots


class SimulationBoard(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.row=None;self.card_boxes=[];self._pending=None
        self.name_font=tkfont.Font(family='Microsoft YaHei UI',size=9,weight='bold')
        self.canvas=tk.Canvas(self,bg='#f3f6fb',highlightthickness=0,width=760,height=440)
        scrollbar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');self.canvas.pack(fill='both',expand=True)
        self.caption=tk.StringVar(value='点击卡片查看文字效果；橙色边框表示当前操作涉及的牌。')
        self.caption_label=ttk.Label(self,textvariable=self.caption,wraplength=850,style='Muted.TLabel')
        self.caption_label.pack(fill='x',pady=4)
        self.canvas.bind('<Configure>',self.resize)
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        self.canvas.bind('<Button-1>',self.inspect)
        self.draw()

    def resize(self,event=None):
        if self._pending:self.after_cancel(self._pending)
        self._pending=self.after_idle(self.draw)

    def set_row(self,row):
        self.row=row
        self.caption.set('点击卡片查看文字效果；橙色边框表示当前操作涉及的牌。')
        self.draw()

    def clear(self):
        self.row=None;self.draw()

    def text(self,x,y,value,**kw):
        return self.canvas.create_text(x,y,text=value,anchor='nw',fill='#20334a',font=('Microsoft YaHei UI',10),**kw)

    def short_name(self,name,width):
        lines=['']
        for i,char in enumerate(name):
            if self.name_font.measure(lines[-1]+char)>width:
                if len(lines)==2:
                    while lines[-1] and self.name_font.measure(lines[-1]+'…')>width:lines[-1]=lines[-1][:-1]
                    lines[-1]+='…';break
                lines.append('')
            lines[-1]+=char
        return '\n'.join(lines)

    def draw(self):
        self._pending=None;c=self.canvas;c.delete('all');self.card_boxes=[]
        width=max(280,c.winfo_width());margin=12;available=width-2*margin
        self.caption_label.configure(wraplength=available)
        if not self.row:
            self.text(24,34,'等待模拟对局…\n开始一局或选择历史记录后，在这里查看棋盘。',width=available-24)
            c.configure(scrollregion=(0,0,width,180));return
        row=self.row;v=row['view'];hero=v['hero'] if v['hero']!='空' else '待选择英雄'
        c.create_rectangle(margin,4,width-margin,60,fill='#203a59',outline='')
        c.create_text(24,18,text=f"第 {v['turn']} 回合  ·  {hero}",anchor='nw',fill='white',font=('Microsoft YaHei UI',12,'bold'),width=available-24)
        c.create_text(24,43,text=f"酒馆 {v['tier']} 星    金币 {v['gold']}    生命 {v['health']} + 护甲 {v['armor']}    存活 {v.get('alive_count','?')}/8",anchor='nw',fill='#e5efff',font=('Microsoft YaHei UI',10),width=available-24)
        c.create_rectangle(margin,64,width-margin,92,fill='#fff0ce',outline='#efd397')
        self.text(22,69,f"第 {row['step']} 手：{row['action_text']}  ·  执行前画面",width=available-20)
        y=98;highlight=highlighted_slots(row['action'])
        for zone,title,capacity,fill,edge in ZONE_META:
            cards=v[zone]
            if zone=='choices' and not cards:continue
            count=max(capacity,max((x['slot'] for x in cards),default=0))
            cols=max(1,min(count,int(available/76)));gap=7;cw=(available-gap*(cols-1))/cols
            self.text(margin,y,f'{title}  {len(cards)}/{capacity}' if capacity else f'{title}  {len(cards)} 项')
            y+=21;by_slot={x['slot']:x for x in cards}
            for i in range(count):
                x=margin+(i%cols)*(cw+gap);top=y+(i//cols)*91;card=by_slot.get(i+1)
                hot=(zone,i+1) in highlight
                c.create_rectangle(x,top,x+cw,top+84,fill=fill if card else '#edf1f6',outline='#ed8b24' if hot else edge if card else '#d6dee9',width=3 if hot else 1,dash=() if card else (3,3))
                c.create_text(x+6,top+5,text=f'{i+1}',anchor='nw',fill=edge,font=('Microsoft YaHei UI',8))
                if not card:
                    c.create_text(x+cw/2,top+49,text='空位',fill='#a0aabb',font=('Microsoft YaHei UI',9));continue
                c.create_text(x+cw-5,top+5,text='金色' if card.get('golden') else '',anchor='ne',fill='#9c6714',font=('Microsoft YaHei UI',8,'bold'))
                c.create_text(x+cw/2,top+20,text=self.short_name(card['name'],cw-10),anchor='n',fill='#172d45',font=self.name_font)
                if 'attack' in card:
                    c.create_text(x+8,top+70,text=str(card['attack']),anchor='w',fill='#88631d',font=('Microsoft YaHei UI',12,'bold'))
                    c.create_text(x+cw-8,top+70,text=str(card['health']),anchor='e',fill='#a33c46',font=('Microsoft YaHei UI',12,'bold'))
                    c.create_text(x+cw/2,top+71,text='/',fill='#64748b',font=('Microsoft YaHei UI',9))
                elif zone=='choices':
                    c.create_text(x+cw/2,top+70,text='待选',fill=edge,font=('Microsoft YaHei UI',9))
                else:
                    c.create_text(x+cw/2,top+70,text='法术 / 效果',fill=edge,font=('Microsoft YaHei UI',8))
                if 'cost' in card and zone!='choices':
                    c.create_text(x+cw/2,top+54,text=f"费用 {card['cost']}",fill='#526176',font=('Microsoft YaHei UI',8))
                self.card_boxes.append((x,top,x+cw,top+84,title,card))
            y+=math.ceil(count/cols)*91+2
        self.text(margin,y,'金色数字为攻击力 · 红色数字为生命值 · 空位保持真实站位',width=available);y+=35
        c.configure(scrollregion=(0,0,width,max(y,c.winfo_height())))

    def inspect(self,event):
        x=self.canvas.canvasx(event.x);y=self.canvas.canvasy(event.y)
        for x0,y0,x1,y1,zone,card in self.card_boxes:
            if x0<=x<=x1 and y0<=y<=y1:
                self.caption.set(f"{zone} {card['slot']}号位 · {card['name']}：{card.get('text') or '无额外文字效果'}");return
