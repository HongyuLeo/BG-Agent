"""Built-in two-choice display heuristic copied from legacy live_native.py.

Source (read-only): BG-Agent体验版2.0/bgagent/live_native.py,
SHA256 2be4652c20227df16fae30b6d0b698c7bda65f6d25cdad297fd8c8204bb2dfdf.
Same source in the original training experience and3.0. This is only local
pixel readiness, never a server receipt, legal-action oracle or model state.
"""


def legacy_subchoice_ready(rgb):
    if rgb is None:
        return False
    import numpy as np
    from .live_legacy_layout import canonical_frame
    rgb=canonical_frame(rgb)
    def green(box):
        x0,y0,x1,y1=box
        sample=rgb[y0:y1,x0:x1].astype(np.int16)
        return float(((sample[:,:,1]>160)&(sample[:,:,1]>sample[:,:,0]*1.25)&
                      (sample[:,:,1]>sample[:,:,2]*1.15)).mean())>.15
    return green((520,275,550,580)) and green((1050,275,1080,580))
