"""Offline Chinese lobby-type OCR with closed grammar and whole-game caching.

No game window control. Hover/capture belongs to the guarded execution layer.
An available list alone is insufficient: require a complementary disabled list,
an explicit item count, or an explicit complete-enumeration footer. This avoids
turning an accidentally cropped list into eleven invented known bits.
"""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import uuid

RACES='BEAST DEMON DRAGON ELEMENTAL MECHANICAL MURLOC PIRATE QUILBOAR UNDEAD ABERRATION NAGA'.split()
CHINESE={'野兽':'BEAST','恶魔':'DEMON','龙':'DRAGON','元素':'ELEMENTAL','机械':'MECHANICAL','鱼人':'MURLOC','海盗':'PIRATE','野猪人':'QUILBOAR','亡灵':'UNDEAD','畸变体':'ABERRATION','纳迦':'NAGA'}
ALIASES=dict(CHINESE,**{'龙族':'DRAGON'})
_PREFIX=r'(?:(?:本局|本场(?:对局)?|此局|本轮)(?:中)?)?'
_NOUN=r'(?:的)?(?:随从)?(?:类型|种族|种类)'
_COUNT=r'(?:[（(](?:共)?(?P<count>\d+)(?:种)?[）)])?'
# Exact installed255790 zhCN GAMEPLAY strings, independently read without UI:
# MULLIGAN_AVAILABLE_RACES: 本局对战中的随从类型：
# TOOLTIP_BACON_AVAILABLE_RACES_HEADLINE: 本局对战中有：
# TOOLTIP_BACON_UNAVAILABLE_RACES_HEADLINE: 本局对战中没有：
# Legacy semantic aliases still require the same complete-enumeration proof.
_POS_TITLE=r'(?:'+_PREFIX+r'(?:可用|使用|存在|出现|包含)'+_NOUN+r'|本局对战中的随从类型|本局对战中有|本局随从类型)'
_NEG_TITLE=r'(?:'+_PREFIX+r'(?:不可用|未使用|不使用|不存在|没有出现|不会出现|未出现|没有|不出现|不包含|未包含)'+_NOUN+r'|本局对战中没有)'
POS=re.compile(r'(?<![\u4e00-\u9fff])'+_POS_TITLE+_COUNT+r'[:：]?')
NEG=re.compile(r'(?<![\u4e00-\u9fff])'+_NEG_TITLE+r'[:：]?')
INACTIVE=re.compile(r'(?<![\u4e00-\u9fff])敬请期待[:：]')
FOOTER=re.compile(r'(?:以上(?:为|是)|这(?:就)?是)(?:本局|本场对局)?全部(?:可用)?(?:随从)?(?:种族|类型|种类)[。.!！]?')
SEPARATORS=re.compile(r'[、,，;；/|·•:：\n\r\t ]+')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')
def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('xb') as file:file.write(canonical(value));file.flush();os.fsync(file.fileno())
    os.replace(temp,path)
def immutable(path,value):
    with Path(path).open('xb') as file:file.write(canonical(value));file.flush();os.fsync(file.fileno())


def parse_lobby_races(text):
    """Return a complete eleven-bit classification or an explicit rejection.

    Whitespace inside OCR CJK tokens may be removed. No fuzzy name correction,
    substring tribe detection, shop-card inference, or default absent tribes.
    """
    normalized=re.sub(r'[^\S\n]+','',str(text)).replace('\r','')
    unavailable=list(NEG.finditer(normalized));inactive=list(INACTIVE.finditer(normalized))
    negative=unavailable+inactive
    positive=[m for m in POS.finditer(normalized) if not any(m.start()<n.end() and m.end()>n.start() for n in negative)]
    headings=sorted([(m.start(),m.end(),'enabled',m) for m in positive]+[(m.start(),m.end(),'disabled',m) for m in negative])
    if not positive:return {'known':False,'reason':'missing_positive_lobby_type_heading','normalized':normalized}
    if len(positive)!=1 or len(unavailable)>1 or len(inactive)>1:return {'known':False,'reason':'ambiguous_multiple_type_panels','normalized':normalized}
    groups={};count=None;closed=False
    for i,(start,end,kind,match) in enumerate(headings):
        body=normalized[end:headings[i+1][0] if i+1<len(headings) else len(normalized)]
        footer=FOOTER.search(body)
        if footer:body=body[:footer.start()];closed=True
        if kind=='enabled' and match.groupdict().get('count'):count=int(match['count'])
        # Explicit count may be shown after the list, rather than in its title.
        tail_count=re.search(r'(?:共|合计)(\d+)种[。.!！]?$',body)
        if tail_count:
            if kind=='enabled':
                declared=int(tail_count[1])
                if count is not None and count!=declared:return {'known':False,'reason':'inconsistent_declared_type_count'}
                count=declared
            body=body[:tail_count.start()]
        tokens=[x for x in SEPARATORS.split(body.strip('。.!！:：\n')) if x]
        if not tokens:return {'known':False,'reason':'empty_'+kind+'_enumeration'}
        unknown=[x for x in tokens if x not in ALIASES]
        if unknown:return {'known':False,'reason':'unknown_or_merged_type_tokens','tokens':unknown,'normalized':normalized}
        races=[ALIASES[x] for x in tokens]
        if len(set(races))!=len(races):return {'known':False,'reason':'duplicate_type_tokens','normalized':normalized}
        if kind in groups:
            if groups[kind]&set(races):return {'known':False,'reason':'duplicate_type_tokens','normalized':normalized}
            groups[kind].update(races)
        else:groups[kind]=set(races)
    enabled=groups['enabled'];disabled=groups.get('disabled')
    if disabled is not None:
        if enabled&disabled:return {'known':False,'reason':'contradictory_enabled_disabled_types'}
        if enabled|disabled!=set(RACES):return {'known':False,'reason':'incomplete_complementary_enumeration','missing':sorted(set(RACES)-enabled-disabled)}
        proof='explicit_enabled_and_disabled_complete11_partition'
    elif count is not None:
        if len(enabled)!=count:return {'known':False,'reason':'declared_type_count_mismatch','declared':count,'recognized':len(enabled)}
        if not 1<=count<=len(RACES):return {'known':False,'reason':'invalid_declared_type_count'}
        disabled=set(RACES)-enabled;proof='positive_complete_heading_and_exact_declared_count'
    elif closed:
        disabled=set(RACES)-enabled;proof='explicit_complete_enumeration_footer'
    else:return {'known':False,'reason':'list_completeness_unproved_need_disabled_complement_or_count_or_footer','recognized_enabled':sorted(enabled)}
    return {'known':True,'enabled':[r for r in RACES if r in enabled],'disabled':[r for r in RACES if r in disabled],'bits':{r:int(r in enabled) for r in RACES},'proof':proof,'normalized':normalized}


def viewport_roi(viewport,image_size,box=None):
    """Normalized ROI relative to current anchored viewport, not desktop origin.

    viewport x/y are coordinates inside the captured client image. Moving the
    desktop window does not alter client-image x/y. Reference size is ignored.
    """
    width,height=image_size
    x,y,w,h=[viewport[k] for k in ('x','y','width','height')]
    if not all(type(v) in (int,float) and math.isfinite(v) for v in (x,y,w,h)) or min(w,h)<=0:raise ValueError('invalid viewport')
    if x<0 or y<0 or x+w>width or y+h>height:raise ValueError('viewport outside captured client image')
    box=box or (0.,0.,1.,1.)
    if len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box):raise ValueError('invalid normalized ROI')
    left,top,right,bottom=box
    if not 0<=left<right<=1 or not 0<=top<bottom<=1:raise ValueError('ROI outside viewport')
    return (math.floor(x+w*left),math.floor(y+h*top),math.ceil(x+w*right),math.ceil(y+h*bottom))


def parse_ocr_result(result):
    """Locate a complete semantic tooltip in full-viewport OCR line order.

    UI labels outside the proven panel need not become list tokens. Selection
    stops only once an exact complete grammar has succeeded, never after an
    incomplete partial list or a misspelled type. All competing complete panels
    must agree. Original OCR lines/bounding rectangles remain in evidence.
    """
    direct=parse_lobby_races(result.get('text',''))
    if direct.get('known'):return direct
    if direct.get('reason') in ('contradictory_enabled_disabled_types','duplicate_type_tokens','inconsistent_declared_type_count'):return direct
    lines=result.get('lines',[]);candidates=[]
    for start,line in enumerate(lines):
        text=re.sub(r'[^\S\n]+','',line.get('text',''))
        title=POS.match(text)
        if not title:continue
        for end in range(start,min(len(lines),start+16)):
            content='\n'.join(x.get('text','') for x in lines[start:end+1])
            parsed=parse_lobby_races(content)
            if parsed.get('known'):
                candidates.append(dict(parsed,selected_line_indices=list(range(start,end+1))));break
            if parsed.get('reason') in ('unknown_or_merged_type_tokens','duplicate_type_tokens','contradictory_enabled_disabled_types','ambiguous_multiple_type_panels'):break
    if not candidates:return direct
    if any(x['bits']!=candidates[0]['bits'] for x in candidates):return {'known':False,'reason':'conflicting_complete_ocr_panels'}
    return candidates[0]


def windows_ocr(image_path,timeout=30):
    if os.name!='nt':raise RuntimeError('Windows local OCR requires Windows')
    host=Path(os.environ.get('WINDIR','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    script=Path(__file__).with_name('windows_ocr.ps1')
    result=subprocess.run([str(host),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),'-InputImage',str(Path(image_path).resolve())],capture_output=True,timeout=timeout,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise RuntimeError('Windows OCR failed: '+result.stderr[-1200:])
    try:return json.loads(result.stdout.lstrip('\ufeff'))
    except ValueError as exc:raise RuntimeError('Windows OCR did not return structured evidence') from exc


class LobbyRaceReader:
    def __init__(self,cache_root,ocr_backend=windows_ocr):
        self.root=Path(cache_root).resolve();self.root.mkdir(parents=True,exist_ok=True);self.backend=ocr_backend
        self.active=None
        try:self.active=json.loads((self.root/'active.json').read_text('utf8'))
        except (OSError,ValueError):pass
        if not isinstance(self.active,dict):self.active=None
    def bind_game(self,game_key):
        if not isinstance(game_key,str) or not game_key:raise ValueError('game_key must be positively anchored')
        if self.active is None or self.active.get('game_key')!=game_key:
            self.active={'game_key':game_key,'known':False,'reason':'new_game_requires_new_public_type_evidence'}
            atomic(self.root/'active.json',self.active)
    def get(self,game_key):
        if not self.active or self.active.get('game_key')!=game_key:return {'known':False,'reason':'game_key_changed_or_not_bound'}
        if not self.active.get('known'):return dict(self.active)
        leaves=self.active.get('lobby_races',{})
        if set(leaves)!=set(RACES) or not self.active.get('evidence') or any(not isinstance(leaf,dict) or leaf.get('known') is not True or leaf.get('value') not in (0,1) or not isinstance(leaf.get('source'),dict) or leaf['source'].get('game_key')!=game_key for leaf in leaves.values()):
            self.active={'game_key':game_key,'known':False,'reason':'cached_record_schema_invalid'};atomic(self.root/'active.json',self.active);return dict(self.active)
        for proof in self.active['evidence']:
            path=Path(proof['path'])
            if not path.is_relative_to(self.root) or not path.is_file() or sha(path)!=proof['sha256']:
                self.active={'game_key':game_key,'known':False,'reason':'cached_image_or_ocr_evidence_changed'};atomic(self.root/'active.json',self.active);return dict(self.active)
        return dict(self.active,cached=True)
    def observe(self,image_path,game_key,viewport,roi=None,force=False):
        self.bind_game(game_key)
        cached=self.get(game_key)
        if cached.get('known') and not force:return cached
        from PIL import Image
        source=Path(image_path).resolve();raw=source.read_bytes();image_sha=hashlib.sha256(raw).hexdigest()
        attempt=self.root/'attempts'/uuid.uuid4().hex;attempt.mkdir(parents=True)
        original=attempt/('source'+source.suffix.lower())
        with original.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        image=Image.open(original).convert('RGB')
        try:region=viewport_roi(viewport,image.size,roi)
        except ValueError as exc:
            result={'game_key':game_key,'known':False,'reason':'viewport_changed_or_invalid','detail':str(exc),'evidence':[{'path':str(original),'sha256':image_sha}]}
            immutable(attempt/'RESULT.json',result);self.active=result;atomic(self.root/'active.json',result);return result
        crop=image.crop(region);evidence=[{'path':str(original),'sha256':image_sha}];passes=[]
        for scale in (1,2):
            candidate=crop if scale==1 else crop.resize((crop.width*2,crop.height*2),Image.Resampling.LANCZOS)
            path=attempt/f'roi-{scale}x.png';candidate.save(path)
            result=self.backend(path);parsed=parse_ocr_result(result)
            ocr_path=attempt/f'ocr-{scale}x.json';immutable(ocr_path,{'scale':scale,'ocr':result,'parsed':parsed,'confidence_note':'Windows OCR supplies no confidence. Closed-vocabulary grammar and independent-scale consensus are validation gates, not a fabricated OCR confidence.'})
            evidence += [{'path':str(path),'sha256':sha(path)},{'path':str(ocr_path),'sha256':sha(ocr_path)}]
            passes.append(parsed)
        if not all(p.get('known') for p in passes):
            result={'game_key':game_key,'known':False,'reason':'ocr_complete_enumeration_not_proven','passes':passes,'evidence':evidence,'viewport':viewport,'roi':list(region)}
        elif passes[0]['bits']!=passes[1]['bits']:
            result={'game_key':game_key,'known':False,'reason':'ocr_scale_disagreement','passes':passes,'evidence':evidence,'viewport':viewport,'roi':list(region)}
        else:
            source_proof={'kind':'local_public_visual_ocr','game_key':game_key,'image_sha256':image_sha,'image_path':str(original),'ocr_paths':[e['path'] for e in evidence if e['path'].endswith('.json')],'grammar_proof':passes[0]['proof'],'scale_agreement':[1,2],'observed_utc':datetime.now(timezone.utc).isoformat(),'viewport_at_capture':viewport,'roi_at_capture':list(region)}
            result={'game_key':game_key,'known':True,'lobby_races':{r:{'known':True,'value':passes[0]['bits'][r],'source':source_proof,'basis':'complete public enumeration, no shop inference'} for r in RACES},'evidence':evidence,'grammar_proof':passes[0]['proof'],'cached':False}
        immutable(attempt/'RESULT.json',result);self.active=result;atomic(self.root/'active.json',result);return result


def public_context(result):
    if not result.get('known'):raise ValueError('完整族表尚无可用公开视觉证据')
    return {'lobby_races':result['lobby_races']}
