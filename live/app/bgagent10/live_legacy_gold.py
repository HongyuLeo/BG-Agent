"""Legacy experience3 gold display matcher. Display/log sync only; no model facts.

Source copied read-only; SOURCE.json records hashes. No runtime old-root imports.
"""
"""Small, locally measured glyph bank for the visible gold counter."""
from functools import lru_cache
import re
import numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def glyphs():
    with np.load(ROOT/'data/live-digits-1600-legacy.npz', allow_pickle=False) as bank:
        return [(('/' if k.startswith('slash') else k.split('_')[0]), bank[k]) for k in bank.files]


def read_gold_crop(rgb):
    if rgb.shape != (19,64,3):
        return None
    mask = (rgb.min(2)>165) & ((rgb.max(2).astype(np.int16)-rgb.min(2))<75)
    spans, start = [], None
    for x, occupied in enumerate(list(mask.any(0))+[False]):
        if occupied and start is None:
            start=x
        elif not occupied and start is not None:
            spans.append((start,x));start=None
    if not 3 <= len(spans) <= 5:
        return None
    chars=[]
    for left,right in spans:
        g=mask[:,left:right]
        ys=np.where(g.any(1))[0]
        g=g[ys[0]:ys[-1]+1]
        scores={}
        for char, template in glyphs():
            if any(abs(a-b)>2 for a,b in zip(g.shape,template.shape)):
                continue
            resized=template[(np.arange(g.shape[0])*template.shape[0]/g.shape[0]).astype(int)[:,None],
                             (np.arange(g.shape[1])*template.shape[1]/g.shape[1]).astype(int)[None,:]]
            # Fractional UI scaling shifts a narrow stroke by one canonical
            # pixel. Align within that rounding error, keeping the same score
            # and ambiguity limits instead of accepting poorer digit matches.
            padded=np.pad(resized, 1)
            score=min(float(np.logical_xor(g,
                padded[1+dy:1+dy+g.shape[0],1+dx:1+dx+g.shape[1]]).mean())
                + .015*(abs(dx)+abs(dy)) for dy in (-1,0,1) for dx in (-1,0,1))
            scores[char]=min(score,scores.get(char,1))
        ordered=sorted(scores.items(),key=lambda row:row[1])
        if not ordered or ordered[0][1]>.18 or (len(ordered)>1 and ordered[1][1]-ordered[0][1]<.045):
            return None
        chars.append(ordered[0][0])
    text=''.join(chars)
    if not re.fullmatch(r'\d{1,2}/\d{1,2}',text):
        return None
    current,maximum=map(int,text.split('/'))
    # Coins, trinkets and other effects may grant spendable gold above the
    # natural turn allowance shown after the slash.
    return (current,maximum) if 0<=current<=99 and 0<=maximum<=30 else None


def read_gold(rgb):
    if rgb.shape[:2] != (900,1600):
        return None
    return read_gold_crop(rgb[825:844,1016:1080])
