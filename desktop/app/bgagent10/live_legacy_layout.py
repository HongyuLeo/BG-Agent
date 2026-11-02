"""Measured layout in a centred, height-scaled Hearthstone viewport."""
import re


def viewport(size):
    width, height = size
    if width < 640 or height < 360:
        raise ValueError('游戏客户区过小，等待恢复窗口')
    # Hearthstone expands the camera horizontally; stretching the full client
    # at 4:3 or ultrawide aspect ratios moves every card away from its centre.
    scale = min(height / 900, width / 1200)
    return ((width - 1600 * scale) / 2, (height - 900 * scale) / 2, scale)


def map_point(point, source_size, target_size):
    sx, sy, ss = viewport(source_size)
    tx, ty, ts = viewport(target_size)
    x = (point[0] * source_size[0] - sx) / ss
    y = (point[1] * source_size[1] - sy) / ss
    mapped = [(tx + x * ts) / target_size[0], (ty + y * ts) / target_size[1]]
    if not all(0 < value < 1 for value in mapped):
        raise ValueError('操作位置不在当前游戏可见区域，等待恢复窗口')
    return mapped


def canonical_frame(rgb):
    """Use exactly the inverse transform of input, including clipped margins."""
    import numpy as np
    height, width = rgb.shape[:2]
    if (width, height) == (1600, 900):
        return rgb
    left, top, scale = viewport((width, height))
    xs = np.floor(left + (np.arange(1600) + .5) * scale).astype(int)
    ys = np.floor(top + (np.arange(900) + .5) * scale).astype(int)
    valid_x, valid_y = (xs >= 0) & (xs < width), (ys >= 0) & (ys < height)
    result = rgb[np.clip(ys, 0, height-1)[:, None], np.clip(xs, 0, width-1)[None, :]].copy()
    result[~valid_y] = 0
    result[:, ~valid_x] = 0
    return result


def measured_point(key, calibration):
    if calibration.get("profile") != "hs-37-1600x900":
        return None
    fixed = {"upgrade": [658/1600,168/900], "refresh": [939/1600,168/900],
             "freeze": [1030/1600,150/900], "buy_drop": [.48,.94],
             "sell_drop": [.5,.17], "cast_drop": [.5,.54],
             "hero_power": [948/1600,690/900], "dark_gift": [1340/1600,260/900],
             "hero_confirm": [.5,710/900], "trinket_confirm":[.5,628/900]}
    if key.startswith("fixed:"):
        return fixed.get(key[6:])
    if key in ("subchoices:2:0","subchoices:2:1"):
        return [590/1600 if key.endswith(":0") else 990/1600,440/900]
    if m := re.fullmatch(r'trinkets:4:([0-3])',key):
        return [(800+(int(m[1])-1.5)*232)/1600,420/900]
    if m := re.fullmatch(r'discover:3:([0-2])',key):
        return [(800+(int(m[1])-1)*324)/1600,450/900]
    if key.startswith("shop:"):
        _, types, idx = key.split(":")
        count, index = len(types.split(",")), int(idx)
        if 1 <= count <= 8 and 0 <= index < count:
            return [(800+(index-(count-1)/2)*116)/1600,335/900]
    if m := re.fullmatch(r"(board|hand|gap|choices):(\d+):(\d+)", key):
        zone, count, index = m[1], int(m[2]), int(m[3])
        if zone == "board" and 1 <= count <= 7 and index < count:
            return [(800+(index-(count-1)/2)*116)/1600,495/900]
        if zone == "gap" and 0 <= count <= 7 and index <= count:
            return [(800+(index-count/2)*116)/1600,495/900]
        if zone == "hand" and 1 <= count <= 10 and index < count:
            step = min(93,650/max(1,count-1))
            return [(768+(index-(count-1)/2)*step)/1600,850/900]
        if zone == "choices" and count in (3,4) and index < count:
            return [(800+(index-(count-1)/2)*284)/1600,400/900]
    return None
