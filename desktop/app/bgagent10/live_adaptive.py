"""Image-evidenced viewport/anchor transforms; no full-client blind scaling."""
from __future__ import annotations
import itertools
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image


class LayoutUnavailable(RuntimeError):pass
class WindowIdentityChanged(RuntimeError):pass
class ActionUncertain(RuntimeError):pass


def content_bounds(rgb):
    """Trim positively black constant letterbox bars, not arbitrary dark artwork."""
    h,w=rgb.shape[:2];gray=rgb.astype(np.float32).mean(2)
    row=(gray.max(1)<13)&(gray.std(1)<2)
    col=(gray.max(0)<13)&(gray.std(0)<2)
    def trim(mask):
        left=0;right=len(mask)
        while left<right and mask[left]:left+=1
        while right>left and mask[right-1]:right-=1
        if left<4:left=0
        if len(mask)-right<4:right=len(mask)
        return left,right
    x0,x1=trim(col);y0,y1=trim(row)
    if x1-x0<320 or y1-y0<180:raise LayoutUnavailable('无法识别游戏可见视口')
    return [x0,y0,x1,y1]


def ncc(image,template):
    """FFT normalized correlation, with full local variance normalization."""
    image=np.asarray(image,np.float64);template=np.asarray(template,np.float64)
    h,w=image.shape;th,tw=template.shape
    if th>h or tw>w or min(th,tw)<3:raise LayoutUnavailable('锚点模板尺寸超出搜索范围')
    centered=template-template.mean();norm=float(np.square(centered).sum())
    if norm<1:raise LayoutUnavailable('锚点图像缺纹理')
    shape=(1<<(h+th-2).bit_length(),1<<(w+tw-2).bit_length())
    corr=np.fft.irfft2(np.fft.rfft2(image,s=shape)*np.fft.rfft2(centered[::-1,::-1],s=shape),s=shape)
    numerator=corr[th-1:h,tw-1:w]
    def sums(values):
        integral=np.pad(values,((1,0),(1,0))).cumsum(0).cumsum(1)
        return integral[th:,tw:]-integral[:-th,tw:]-integral[th:,:-tw]+integral[:-th,:-tw]
    total=sums(image);variance=np.maximum(sums(image*image)-total*total/(th*tw),0)
    scores=numerator/np.sqrt(np.maximum(variance*norm,1e-9))
    scores[variance<1.0]=-1
    return np.clip(scores,-1,1)


class Layout:
    def __init__(self,matrix,reference_size,client_size,bounds,proof,groups=None):
        self.matrix=np.asarray(matrix,float);self.reference_size=reference_size;self.client_size=client_size
        self.bounds=bounds;self.proof=proof;self.groups=groups or {}
    def pixel(self,point,group='global'):
        x,y=point[0]*self.reference_size[0],point[1]*self.reference_size[1]
        matrix=np.asarray(self.groups.get(group,self.matrix))
        out=np.array([x,y,1.])@matrix
        if not np.isfinite(out).all():raise LayoutUnavailable('布局坐标无效')
        return out.tolist()
    def normalized(self,point,group='global'):
        x,y=self.pixel(point,group);w,h=self.client_size
        if not 0<x<w or not 0<y<h:raise LayoutUnavailable('操作位置被裁出可见游戏区域，等待窗口恢复')
        return [x/w,y/h]
    def box(self,box,group='global'):
        first=self.pixel(box[:2],group);last=self.pixel(box[2:],group)
        return [round(first[0]),round(first[1]),round(last[0]),round(last[1])]
    def viewport(self):
        x0,y0,x1,y1=self.bounds
        return {'x':x0,'y':y0,'width':x1-x0,'height':y1-y0,'client_width':self.client_size[0],'client_height':self.client_size[1],
            'reference_width':self.reference_size[0],'reference_height':self.reference_size[1],'anchor_transform':self.matrix.tolist(),'proof':self.proof}


class AnchorResolver:
    def __init__(self,profile,profile_path=None):
        self.profile=profile;self.settings=profile.get('adaptive',{})
        path=self.settings.get('reference_image') or profile.get('capture_image')
        if not path and profile_path:path=str(Path(profile_path).with_suffix('.capture.png'))
        if not path or not Path(path).is_file():raise LayoutUnavailable('自适应需要首次校准参考截图及锚点，不能盲缩放')
        self.reference=np.asarray(Image.open(path).convert('RGB'))
        self.reference_size=list(profile['size'])
        if [self.reference.shape[1],self.reference.shape[0]]!=self.reference_size:raise LayoutUnavailable('参考截图尺寸与校准不符')
        self.anchors=self.settings.get('anchors') or self.auto_anchors()
        if len(self.anchors)<4:raise LayoutUnavailable('至少需要4个分散的可见校准锚点')
    def auto_anchors(self):
        """Generate textured candidates once; every use still needs image matches."""
        h,w=self.reference.shape[:2];candidates=[]
        for x in (.18,.25,.4,.6,.75,.82):
            for y in (.08,.16,.84,.92):
                rw=max(14,round(w*.025));rh=max(12,round(h*.025));cx,cy=round(w*x),round(h*y)
                patch=self.reference[max(0,cy-rh):cy+rh,max(0,cx-rw):cx+rw].mean(2)
                score=float(np.abs(np.diff(patch,axis=0)).mean()+np.abs(np.diff(patch,axis=1)).mean())
                if score>5:candidates.append((score,{'name':f'auto-{x}-{y}','box':[(cx-rw)/w,(cy-rh)/h,(cx+rw)/w,(cy+rh)/h],'group':'global'}))
        candidates.sort(key=lambda p:p[0],reverse=True)
        return [v for _,v in candidates[:16]]
    def fit(self,matches,client_size,bounds):
        if len(matches)<4:raise LayoutUnavailable('可见锚点不足4个，等待画面恢复')
        reference=np.array([m['reference'] for m in matches],float);actual=np.array([m['actual'] for m in matches],float)
        design=np.column_stack((reference,np.ones(len(reference))));best=None
        tolerance=max(3.,min(client_size)*.008)
        for triple in itertools.combinations(range(len(matches)),3):
            if abs(np.linalg.det(design[list(triple)]))<10:continue
            matrix=np.linalg.solve(design[list(triple)],actual[list(triple)])
            if matrix[0,0]<=0 or matrix[1,1]<=0:continue
            if abs(matrix[0,1])>matrix[0,0]*.03 or abs(matrix[1,0])>matrix[1,1]*.03:continue
            residual=np.linalg.norm(design@matrix-actual,axis=1);inliers=residual<=tolerance
            count=int(inliers.sum())
            if count>=4 and (best is None or count>best[0]):best=(count,inliers)
        if best is None:raise LayoutUnavailable('锚点不能证明一致布局变换')
        inliers=best[1];matrix=np.linalg.lstsq(design[inliers],actual[inliers],rcond=None)[0]
        spread=np.ptp(reference[inliers],axis=0)
        if spread[0]<self.reference_size[0]*.25 or spread[1]<self.reference_size[1]*.25:raise LayoutUnavailable('锚点覆盖不足，不能推断全场坐标')
        residual=np.linalg.norm(design[inliers]@matrix-actual[inliers],axis=1)
        proof={'method':'image-anchor-ransac-affine','matched':int(inliers.sum()),'max_residual_pixels':float(residual.max()),
            'matches':[m for i,m in enumerate(matches) if inliers[i]],'bounds':bounds}
        groups={}
        for group in {m.get('group','global') for m in matches}-{'global'}:
            selected=[dict(m,group='global') for m in matches if m.get('group')==group]
            # HUD and board can reflow independently. A failed group fit must
            # never silently inherit another group's camera transform.
            if len(selected)<4:raise LayoutUnavailable('独立布局锚组不足4个：'+group)
            fitted=self.fit(selected,client_size,bounds);groups[group]=fitted.matrix
            proof['matches'] += [dict(m,group=group) for m in fitted.proof['matches'] if m['name'] not in {x['name'] for x in proof['matches']}]
        return Layout(matrix,self.reference_size,client_size,bounds,proof,groups)
    def resolve(self,rgb):
        try:return self._resolve_anchors(rgb)
        except LayoutUnavailable:
            if self.profile.get('layout_profile',self.profile.get('profile'))!='hs-37-1600x900':raise
            # Reuse the historical client's measured centred, height-scaled
            # camera, with current detected bars. Never stretch the full client.
            h,w=rgb.shape[:2];bounds=content_bounds(rgb);ref_bounds=content_bounds(self.reference)
            def camera(box):
                x0,y0,x1,y1=box;cw,ch=x1-x0,y1-y0
                scale=min(ch/900,cw/1200)
                return x0+(cw-1600*scale)/2,y0+(ch-900*scale)/2,scale
            rx,ry,rs=camera(ref_bounds);tx,ty,ts=camera(bounds);ratio=ts/rs
            proof={'method':'historical-measured-camera-with-detected-letterbox','source':'bgagent/live_layout.py viewport/map_point; read-only reuse',
                'target_bar_bounds':bounds,'reference_bar_bounds':ref_bounds,'matched':0,'matches':[],'manual_acceptance':'窗口适应待用户手动验收'}
            layout=Layout([[ratio,0],[0,ratio],[tx-rx*ratio,ty-ry*ratio]],self.reference_size,[w,h],bounds,proof)
            scene=None
            for name,spec in {**self.profile.get('queue_cues',{}),**self.profile.get('cues',{})}.items():
                if not isinstance(spec,dict) or not spec.get('image_path') or not spec.get('box'):continue
                x0,y0,x1,y1=layout.box(spec['box']);reference=np.asarray(Image.open(spec['image_path']).convert('RGB'))
                if x0<0 or y0<0 or x1>w or y1>h or x1<=x0 or y1<=y0:continue
                patch=np.asarray(Image.fromarray(rgb[y0:y1,x0:x1]).resize((reference.shape[1],reference.shape[0]),Image.Resampling.BILINEAR))
                if float(np.abs(patch.astype(np.int16)-reference.astype(np.int16)).mean())<=spec.get('threshold',10):scene=name;break
            if scene is None:raise LayoutUnavailable('既无足够锚点，也未匹配已知场景，等待画面恢复')
            proof['positive_scene_cue']=scene
            return layout
    def _resolve_anchors(self,rgb):
        h,w=rgb.shape[:2];bounds=content_bounds(rgb);x0,y0,x1,y1=bounds
        gray=rgb.mean(2).astype(np.float32);rw,rh=self.reference_size
        ref_bounds=content_bounds(self.reference);rx0,ry0,rx1,ry1=ref_bounds
        sx=(x1-x0)/(rx1-rx0);sy=(y1-y0)/(ry1-ry0)
        scales={(sx,sy),(sy,sy),(min(sy,sx*4/3),)*2}
        matches=[]
        for anchor in self.anchors:
            box=anchor['box'];ax0,ay0,ax1,ay1=[round(v*(rw if i%2==0 else rh)) for i,v in enumerate(box)]
            patch=Image.fromarray(self.reference[ay0:ay1,ax0:ax1]);cx,cy=(ax0+ax1)/2,(ay0+ay1)/2
            predicted_x=x0+(cx-rx0)*sx;predicted_y=y0+(cy-ry0)*sy
            margin_x=max(70,round(w*.22));margin_y=max(50,round(h*.18))
            left=max(x0,round(predicted_x-margin_x));right=min(x1,round(predicted_x+margin_x));top=max(y0,round(predicted_y-margin_y));bottom=min(y1,round(predicted_y+margin_y))
            search=gray[top:bottom,left:right];best=None
            for scale_x,scale_y in scales:
                for adjustment in (.95,1.,1.05):
                    tw=max(5,round(patch.width*scale_x*adjustment));th=max(5,round(patch.height*scale_y*adjustment))
                    if tw>search.shape[1] or th>search.shape[0]:continue
                    template=np.asarray(patch.resize((tw,th),Image.Resampling.BILINEAR)).mean(2)
                    scores=ncc(search,template);iy,ix=np.unravel_index(np.argmax(scores),scores.shape);score=float(scores[iy,ix])
                    rivals=scores.copy();radius=max(3,min(tw,th)//2)
                    rivals[max(0,iy-radius):iy+radius+1,max(0,ix-radius):ix+radius+1]=-1
                    runner=float(rivals.max())
                    if best is None or score>best['score']:best={'reference':[cx,cy],'actual':[left+ix+tw/2,top+iy+th/2],'score':score,'runner_score':runner,'name':anchor['name'],'group':anchor.get('group','global')}
            if best and best['score']>=self.settings.get('min_score',.84) and best['score']-best['runner_score']>=self.settings.get('min_uniqueness_gap',.025):matches.append(best)
        return self.fit(matches,[w,h],bounds)
    def validate_cached(self,rgb,layout):
        if list(rgb.shape[1::-1])!=list(layout.client_size):return False
        by_name={a['name']:a for a in self.anchors};good=[];group_counts={}
        for match in layout.proof.get('matches',[]):
            anchor=by_name.get(match['name'])
            if not anchor:continue
            box=anchor['box'];rw,rh=self.reference_size
            ref_box=[round(v*(rw if i%2==0 else rh)) for i,v in enumerate(box)]
            group=anchor.get('group','global');x0,y0,x1,y1=layout.box(box,group)
            if x0<0 or y0<0 or x1>rgb.shape[1] or y1>rgb.shape[0] or x1<=x0 or y1<=y0:continue
            patch=np.asarray(Image.fromarray(rgb[y0:y1,x0:x1]).resize((ref_box[2]-ref_box[0],ref_box[3]-ref_box[1]),Image.Resampling.BILINEAR)).mean(2)
            reference=self.reference[ref_box[1]:ref_box[3],ref_box[0]:ref_box[2]].mean(2)
            a=patch-patch.mean();b=reference-reference.mean();den=float(np.sqrt((a*a).sum()*(b*b).sum()))
            if den>1 and float((a*b).sum()/den)>=self.settings.get('min_score',.84):
                good.append(match['reference']);group_counts[group]=group_counts.get(group,0)+1
        return len(good)>=4 and all(group_counts.get(g,0)>=4 for g in layout.groups) and np.all(np.ptp(np.asarray(good),axis=0)>=np.asarray(self.reference_size)*.25)


class LayoutManager:
    def __init__(self,native,profile,stop,config,resolver=None):
        self.native=native;self.profile=profile;self.stop=stop;self.config=dict(config)
        if resolver is None and profile.get('adaptive',{}).get('scene_references'):
            from .live_quick_setup import SceneAdaptiveResolver
            resolver=SceneAdaptiveResolver(profile,config)
        self.resolver=resolver or AnchorResolver(profile,config.get('calibration_path'))
        self.current=None;self.layout=None;self.identity=None;self.last_reason=None
    def ensure(self,expected=None):
        deadline=time.monotonic()+self.config.get('window_wait_seconds',300)
        identity=self.identity or ({k:expected.get(k) for k in ('hwnd','pid','exe')} if expected else None)
        while True:
            if self.stop.is_set():raise RuntimeError('窗口等待时紧停')
            emergency=self.config.get('emergency_stop_path')
            if emergency and Path(emergency).exists():raise RuntimeError('窗口等待时紧停文件已触发')
            try:
                current=self.native.locate()
                if identity and any(current.get(k)!=v for k,v in identity.items() if v is not None):raise WindowIdentityChanged('游戏窗口/PID/进程已更换，禁止自动接管')
                if not current.get('foreground') or current.get('minimized'):raise LayoutUnavailable('等待游戏窗口恢复前台，不抢焦点')
                if hasattr(self.native,'occluded') and self.native.occluded(current):raise LayoutUnavailable('等待游戏窗口解除遮挡')
                captured,_=self.native.capture(encode=False)
                if any(current[k]!=captured[k] for k in ('hwnd','pid','x','y','width','height')):raise LayoutUnavailable('窗口仍在移动或拉伸，等待稳定')
                if self.layout and self.resolver.validate_cached(self.native.last_rgb,self.layout):layout=self.layout
                else:layout=self.resolver.resolve(self.native.last_rgb)
                self.current=current;self.layout=layout;self.identity={k:current.get(k) for k in ('hwnd','pid','exe')};self.last_reason=None
                self.native.adaptive_layout=layout
                return current
            except WindowIdentityChanged:raise
            except (LayoutUnavailable,RuntimeError) as exc:
                self.last_reason=str(exc)
                if identity and hasattr(self.native,'window_exists') and not self.native.window_exists(identity):raise WindowIdentityChanged('游戏窗口已关闭或进程更换') from exc
                if time.monotonic()>=deadline:raise LayoutUnavailable('等待可识别窗口超时：'+str(exc)) from exc
                status=self.config.get('session_root')
                if status:
                    from .live_data import atomic
                    atomic(Path(status)/'status.json',{'state':'waiting_window','message':self.last_reason,'automatic_resume':True})
                if self.stop.wait(.08):raise RuntimeError('窗口等待时已停止')


class AdaptiveCalibration:
    def __init__(self,profile,manager):self.profile=profile;self.manager=manager
    def guard(self,window):return self.manager.ensure(window)
    def point(self,key):
        value=self.profile.get('points',{}).get(key)
        if value is None:value=self.default_point(key)
        if not isinstance(value,list) or len(value)!=2 or not all(0<v<1 for v in value):raise ValueError('需要首次校准位置：'+key)
        group='hud' if key.startswith(('fixed:','queue:','power:')) else 'board'
        return self.manager.layout.normalized(value,group)
    def default_point(self,key):
        """Historical measured layout, covering changing counts automatically."""
        import re
        fixed={'upgrade':[658/1600,168/900],'refresh':[939/1600,168/900],'freeze':[1030/1600,150/900],
            'buy_drop':[.48,.94],'sell_drop':[.5,.17],'cast_drop':[.5,.54],'dark_gift':[1340/1600,260/900],
            'hero_confirm':[.5,710/900],'trinket_confirm':[.5,628/900],
            'lobby_races_hover':[.93,.965]}
        value=None
        if key.startswith('fixed:'):value=fixed.get(key[6:])
        elif key.startswith('power:'):
            count=len(getattr(self,'context',{}).get('zones',{}).get('hero_buttons',[]))
            slot=int(key.split(':')[1]);value=([934/1600,721/900] if slot==0 else [993/1600,656/900]) if count==2 else [948/1600,690/900] if slot==0 else None
        elif key.startswith('queue:'):
            value={'menu':[.756,.79],'result':[.5,.55],'home':[.5,.375],'startup':[.5,.805],'notice':[.505,.726],'news':[.563,.645],'news_store':[.175,.87]}.get(key.split(':',1)[1])
        elif match:=re.fullmatch(r'(board|shop|hand|gap):(\d+):(\d+)',key):
            zone,n,i=match[1],int(match[2]),int(match[3])
            if zone in ('board','shop') and 1<=n<=(7 if zone=='board' else 8) and i<n:value=[(800+(i-(n-1)/2)*116)/1600,(495 if zone=='board' else 335)/900]
            elif zone=='gap' and 0<=n<=7 and i<=n:value=[(800+(i-n/2)*116)/1600,495/900]
            elif zone=='hand' and 1<=n<=10 and i<n:value=[(768+(i-(n-1)/2)*min(93,650/max(1,n-1)))/1600,850/900]
        elif match:=re.fullmatch(r'choices:(hero_select|discover|trinket|choose_one):(\d+):(\d+)',key):
            kind,n,i=match[1],int(match[2]),int(match[3])
            if i<n:
                if kind=='trinket' and n==4:value=[(800+(i-1.5)*232)/1600,420/900]
                elif kind=='discover' and n==3:value=[(800+(i-1)*324)/1600,.5]
                elif kind=='choose_one' and n==2:value=[(590 if i==0 else 990)/1600,440/900]
                elif kind=='hero_select' and n in (2,3,4):value=[(800+(i-(n-1)/2)*284)/1600,400/900]
        if value is None:return None
        # Map the old 1600x900 measured canvas into the reference capture once;
        # live mapping then uses anchors/current letterbox, not client ratios.
        w,h=self.profile['size'];scale=min(h/900,w/1200)
        return [(w/2+(value[0]*1600-800)*scale)/w,(h/2+(value[1]*900-450)*scale)/h]
    def zone(self,before,name,index):
        rows=before.get('zones',{}).get(name,[])
        if index not in range(len(rows)):raise ValueError('当前可见实体索引越界：'+name)
        return self.point(f'{name}:{len(rows)}:{index}')
