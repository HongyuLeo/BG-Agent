"""Pure saved-image scene evidence; never captures, focuses, or sends inputs.

Menu fallback is explicitly bound to the coordinator-reviewed actual255790
window screenshot and its observed window->client crop. Three dispersed image
patches must agree. Result detection uses formal locale outcome + continue OCR;
it does not certify a game terminal or rank (the log/controller does that).
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from .live_public_vision import windows_ocr

CLIENT_CROP=(1,29,1099,647)
WINDOW_PATCHES=((320,31,535,60),(776,195,874,232),(240,477,620,550))
WINDOW_START=(829,519)
REFERENCE_SHA='28655b935de3e8a7be97f22ddd602bc95c350d18314972a9555e31d5576a3fe5'
BOARD_REFERENCE_SHA='0dc70f7e43c7b73a5621e2ba6250fff5c877979fd9f0564afadcafc63b41503b'
BOARD_PATCHES=((224,55,415,83),(909,352,937,428),(190,580,340,614))


def _compact(text):return re.sub(r'\s+','',text)
def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _reference(relative='data/live-config/setup-255790/bg-menu-window.png'):
    for parent in Path(__file__).resolve().parents:
        path=parent/relative
        if path.is_file():return path
    return None
def _locale():
    root=Path('D:/Hearthstone/Strings/zhCN');data={};sources=[]
    for name in ('GLOBAL','GAMEPLAY','GLUE'):
        path=root/(name+'.txt')
        if not path.is_file():continue
        sources.append({'path':str(path),'sha256':_sha(path)})
        for line in path.read_text('utf8').splitlines():
            row=line.split('\t')
            if len(row)>1:data[row[0]]=row[1]
    return data,sources
def _text_hit(ocr,text,exact=True):
    hits=[];needle=_compact(text)
    for line in ocr.get('lines',[]):
        hay=_compact(line.get('text',''))
        if not (hay==needle if exact else needle in hay):continue
        words=line.get('words',[])
        if not words:continue
        left=min(w['x'] for w in words);top=min(w['y'] for w in words)
        right=max(w['x']+w['width'] for w in words);bottom=max(w['y']+w['height'] for w in words)
        hits.append({'x':(left+right)/2,'y':(top+bottom)/2,'rect':[left,top,right,bottom],'text':text,'source':'exact_ocr_word_bounds'})
    return hits


def _menu_template(image,viewport,reference_path=None,expected_sha=REFERENCE_SHA,patches=WINDOW_PATCHES,kind='actual_255790_menu_template',start=WINDOW_START):
    from PIL import Image
    import numpy as np
    path=Path(reference_path) if reference_path else _reference()
    if path is None or not path.is_file():return None
    reference_sha=_sha(path)
    if reference_sha!=expected_sha:return None
    original=Image.open(path).convert('RGB');ref=original.crop(CLIENT_CROP)
    # Caller supplies an anchor-confirmed content viewport in current client
    # image coordinates. The exact observed window screenshot is also accepted
    # after its explicitly recorded system-border crop, never called native.
    if viewport is None:
        if image.size==original.size and hashlib.sha256(image.tobytes()).digest()==hashlib.sha256(original.tobytes()).digest():
            viewport={'x':CLIENT_CROP[0],'y':CLIENT_CROP[1],'width':ref.width,'height':ref.height,'proof':'exact reviewed window image crop'}
        elif image.size==ref.size:viewport={'x':0,'y':0,'width':ref.width,'height':ref.height,'proof':'same observed client geometry'}
        else:return None
    x,y,w,h=[float(viewport[k]) for k in ('x','y','width','height')]
    if min(w,h)<=0 or x<0 or y<0 or x+w>image.width or y+h>image.height:return None
    candidate=image.crop((round(x),round(y),round(x+w),round(y+h))).resize(ref.size,Image.Resampling.LANCZOS)
    metrics=[]
    for left,top,right,bottom in patches:
        box=(left-CLIENT_CROP[0],top-CLIENT_CROP[1],right-CLIENT_CROP[0],bottom-CLIENT_CROP[1])
        a=np.asarray(ref.crop(box),dtype=np.float32);b=np.asarray(candidate.crop(box),dtype=np.float32)
        color_mae=float(abs(a-b).mean()/255)
        aa=a-a.mean();bb=b-b.mean();den=float(np.sqrt((aa*aa).sum()*(bb*bb).sum()))
        ncc=float((aa*bb).sum()/den) if den>0 else 0.
        metrics.append({'window_rect':list((left,top,right,bottom)),'client_rect':list(box),'color_mae':color_mae,'ncc':ncc,'passed':color_mae<=.08 and ncc>=.90})
    offset=(0,0)
    if not all(m['passed'] for m in metrics):
        # Rendering the same menu at 1080p/4K changes font antialiasing and
        # pixel rounding. Compare at the reference resolution with a one-pixel
        # low-pass filter and ONE shared translation, never independently move
        # semantic patches. Keep the original score/color thresholds, and also
        # require the visible start label before returning a click location.
        if kind!='actual_255790_menu_template' or not start:return None
        from PIL import ImageFilter
        aimage=ref.filter(ImageFilter.GaussianBlur(1.0))
        bimage=candidate.filter(ImageFilter.GaussianBlur(1.0))
        boxes=[(l-CLIENT_CROP[0],t-CLIENT_CROP[1],r-CLIENT_CROP[0],b-CLIENT_CROP[1])
               for l,t,r,b in (*patches,(798,507,861,535))]
        arrays=[np.asarray(aimage.crop(box),dtype=np.float32) for box in boxes]
        best=None
        for dx in range(-3,4):
            for dy in range(-3,4):
                trial=[]
                for box,a in zip(boxes,arrays):
                    l,t,r,b=box;target=(l+dx,t+dy,r+dx,b+dy)
                    if min(target[:2])<0 or target[2]>candidate.width or target[3]>candidate.height:break
                    other=np.asarray(bimage.crop(target),dtype=np.float32)
                    mae=float(abs(a-other).mean()/255);aa=a-a.mean();bb=other-other.mean()
                    denominator=float(np.sqrt((aa*aa).sum()*(bb*bb).sum()))
                    score=float((aa*bb).sum()/denominator) if denominator>0 else 0.
                    trial.append({'client_rect':list(box),'color_mae':mae,'ncc':score,'passed':mae<=.08 and score>=.90})
                if len(trial)==len(boxes) and all(m['passed'] for m in trial):
                    quality=min(m['ncc'] for m in trial)
                    if best is None or quality>best[0]:best=(quality,(dx,dy),trial)
        if best is None:return None
        _,offset,metrics=best
    button=None
    if start:
        sx=x+(start[0]-CLIENT_CROP[0]+offset[0])*w/ref.width;sy=y+(start[1]-CLIENT_CROP[1]+offset[1])*h/ref.height
        button={'x':sx,'y':sy,'rect':None,'text':'开始','source':kind}
    return {'button':button,'viewport':viewport,'proof':{'kind':kind,'reference_path':str(path),'reference_sha256':reference_sha,'reference_was_window_capture':True,'observed_window_to_client_crop':list(CLIENT_CROP),'start_center_window':list(start) if start else None,'patches':metrics,'shared_reference_pixel_offset':list(offset),'antialias_filter_radius':1.0 if len(metrics)>len(patches) else 0,'thresholds':{'all_patch_color_mae_max':.08,'all_patch_ncc_min':.90}}}


def recognize_scene(image_path,game_key=None,phase=None,viewport=None,ocr_backend=None):
    from PIL import Image
    path=Path(image_path).resolve();image=Image.open(path).convert('RGB')
    base={'known':False,'scene':'unknown','buttons':{},'game_key':game_key,'phase':phase,'viewport':viewport,'evidence':{'image_path':str(path),'image_sha256':_sha(path)},'reason':'no_complete_positive_scene_evidence'}
    if game_key and phase in ('recruit','combat'):
        board_path=_reference('data/client-capture/20261030-234853/hero-select-screen.png')
        board=_menu_template(image,viewport,board_path,expected_sha=BOARD_REFERENCE_SHA,patches=BOARD_PATCHES,kind='actual_255790_board_layout_template',start=None) if board_path else None
        if board:
            return dict(base,known=True,scene=phase,viewport=board['viewport'],reason='current_log_phase_plus_three_actual_board_frame_patches',evidence=dict(base['evidence'],template=board['proof'],layout_only_not_inferred_game_state=True,current_log_phase_required=True))
    template=_menu_template(image,viewport)
    if not template and viewport is not None:
        # Black edge detection is a proposal: window borders/taskbar occlusion
        # can look like letterboxing. The full client is another candidate,
        # accepted only when the same dispersed menu landmarks match.
        full={'x':0,'y':0,'width':image.width,'height':image.height}
        if any(viewport.get(k)!=v for k,v in full.items()):
            template=_menu_template(image,full)
    if template:
        return dict(base,known=True,scene='menu',buttons={'start':template['button']},viewport=template['viewport'],reason='three_actual255790_menu_patches_match',evidence=dict(base['evidence'],template=template['proof']))
    ocr=(ocr_backend or windows_ocr)(path);strings,sources=_locale();base['evidence'].update(ocr=ocr,locale_sources=sources)
    continue_word=strings.get('GLOBAL_CONTINUE','继续');continues=_text_hit(ocr,continue_word)
    # Whole formal outcome label, never a substring like 最佳成绩第一名 or 名.
    labels=[strings[k] for k in strings if k.startswith('GAMEPLAY_END_OF_GAME_PLACE_') and not k.endswith('RATING')]
    labels += [strings[k] for k in ('GAMEPLAY_END_OF_GAME_VICTORY','GAMEPLAY_END_OF_GAME_DEFEAT') if k in strings]
    outcomes=[]
    for label in labels:outcomes += _text_hit(ocr,label)
    if len(continues)==1 and outcomes:
        return dict(base,known=True,scene='result',buttons={'continue':continues[0]},reason='formal_outcome_and_continue_visible',evidence=dict(base['evidence'],outcomes=outcomes,log_terminal_still_required=True))
    starts=_text_hit(ocr,strings.get('GLOBAL_PLAY','开始'))
    bg=_text_hit(ocr,strings.get('GLUE_BACON','酒馆战棋'),exact=False)
    rating=_text_hit(ocr,strings.get('GLUE_BACON_RATING_LABEL','等级'))
    if len(starts)==1 and bg and rating:
        return dict(base,known=True,scene='menu',buttons={'start':starts[0]},reason='bg_title_rating_and_start_visible')
    home=[_text_hit(ocr,strings.get(key,value)) for key,value in (('GLOBAL_PROGRESSION_PROFILE_PLAY_MODE','传统对战'),('GLUE_BACON','酒馆战棋'),('GLUE_ADVENTURE','冒险模式'))]
    if all(len(hits)==1 for hits in home) and not starts and not continues:return dict(base,known=True,scene='home',buttons={'battlegrounds':home[1][0]},reason='three_formal_mode_labels_visible')
    return base
