# -*- coding: utf-8 -*-
"""耳朵晃动 30 帧（旋转版 v4 · 定稿候选）。

v4 相对前几版的改动：
  1) 底图不再"整片抹平"，只抹掉**底图帧自身那只静耳**（发际以外的鳍片掩码，实测仅
     55px/409px），用**相邻行**的头发像素补——相邻行比同一行更像头发纹样，
     不会出现横向色带（v2 的败因）；
  2) 只旋转紧抠的鳍片，补丁不外扩，避免发丝/衣物被带走（用户反馈的"偏移"）；
  3) 不引入任何跨帧混色，所以没有残影。
"""
import json
import math
import os
import sys
from collections import deque
from PIL import Image

SPR = os.environ.get("EAR_KEYS_DIR", "b1final306")
OUT = sys.argv[1] if len(sys.argv) > 1 else "out_rot4"
TOTAL = 30
PAD = 12
Y_BAND = (72, 152)


def load():
    keys = sorted([f for f in os.listdir(SPR) if f.endswith(".png")],
                  key=lambda s: int(s.split("_")[1]))
    return [Image.open(os.path.join(SPR, f)).convert("RGBA") for f in keys]


def largest(cells):
    cells = set(cells); best = set()
    while cells:
        seed = cells.pop(); comp = {seed}; q = deque([seed])
        while q:
            x, y = q.popleft()
            for nb in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                if nb in cells:
                    cells.discard(nb); comp.add(nb); q.append(nb)
        if len(comp) > len(best): best = comp
    return best


def fin_cells(im, edge, side, thr=60, min_run=2):
    px = im.load(); W = im.width
    cells = set()
    for y in range(Y_BAND[0], Y_BAND[1]):
        b = edge.get(y)
        if b is None: continue
        rng = range(b + 1, W) if side > 0 else range(0, b)
        xs = [x for x in rng if px[x, y][3] > thr]
        if len(xs) >= min_run:
            cells.update((x, y) for x in xs)
    return largest(cells)


def erase_from_rows(img, cells, side):
    """用相邻行（优先上一行，其次下一行）的像素补掉 cells —— 保持发丝纹样走向。"""
    px = img.load(); W, H = img.size
    for (x, y) in sorted(cells):
        done = False
        for dy in (-1, 1, -2, 2, -3, 3):
            ny = y + dy
            if not (0 <= ny < H): continue
            q = px[x, ny]
            if q[3] >= 250 and (x, ny) not in cells:
                px[x, y] = q; done = True; break
        if done: continue
        for off in range(1, 12):                 # 兜底：同行向内取样
            cx = x - off if side > 0 else x + off
            if 0 <= cx < W:
                q = px[cx, y]
                if q[3] >= 250 and (cx, y) not in cells:
                    px[x, y] = q; break
    return img


def rotate(img, pivot, deg):
    W, H = img.size
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    src, dst = img.load(), out.load()
    th = math.radians(deg); c, s = math.cos(th), math.sin(th)
    for y in range(H):
        for x in range(W):
            dx, dy = x - pivot[0], y - pivot[1]
            sx = c*dx + s*dy + pivot[0]; sy = -s*dx + c*dy + pivot[1]
            if sx < 0 or sy < 0 or sx >= W-1 or sy >= H-1: continue
            x0, y0 = int(sx), int(sy); fx, fy = sx-x0, sy-y0
            r = g = b = aw = 0.0
            for ox, oy, w in ((0,0,(1-fx)*(1-fy)),(1,0,fx*(1-fy)),(0,1,(1-fx)*fy),(1,1,fx*fy)):
                if w <= 0: continue
                rr, gg, bb, aa = src[x0+ox, y0+oy]
                if aa == 0: continue
                r += rr*aa*w; g += gg*aa*w; b += bb*aa*w; aw += aa*w
            if aw <= 0: continue
            dst[x, y] = (int(r/aw), int(g/aw), int(b/aw), int(min(255, aw)))
    return out


def layer(im, cells):
    W, H = im.size
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sp, lp = im.load(), lay.load()
    for (x, y) in cells:
        if 0 <= x < W and 0 <= y < H:
            lp[x, y] = sp[x, y]
    return lay


def main():
    ims = load()
    cal = json.load(open("b1-calib.json")); ang = cal["angles_r"]
    W, H = ims[0].size
    def outer(im, y, side):
        px = im.load()
        rng = range(W-1, W//2, -1) if side > 0 else range(0, W//2)
        for x in rng:
            if px[x, y][3] > 60: return x
        return None
    edge_r, edge_l = {}, {}
    for y in range(Y_BAND[0], Y_BAND[1]):
        rs = [v for v in (outer(im, y, +1) for im in ims) if v]
        ls = [v for v in (outer(im, y, -1) for im in ims) if v]
        if rs: edge_r[y] = min(rs)
        if ls: edge_l[y] = max(ls)

    def outside_n(im, side, edge):
        px = im.load(); n = 0
        for y in range(Y_BAND[0], Y_BAND[1]):
            b = edge.get(y)
            if b is None: continue
            rng = range(b+1, W) if side > 0 else range(0, b)
            n += sum(1 for x in rng if px[x, y][3] > 60)
        return n
    flat_r = min(range(len(ims)), key=lambda i: outside_n(ims[i], +1, edge_r))
    flat_l = min(range(len(ims)), key=lambda i: outside_n(ims[i], -1, edge_l))
    base = ims[flat_r].copy()
    bl, sl = base.load(), ims[flat_l].load()
    for y in range(Y_BAND[0], Y_BAND[1]):
        b = edge_l.get(y)
        if b is None: continue
        for x in range(0, b+1):
            bl[x, y] = sl[x, y]
    print(f"底图：右#{flat_r+1} 左#{flat_l+1}")
    # 精准抹掉底图自带的静耳（只用底图帧自身的鳍掩码）
    for side, edge in ((+1, edge_r), (-1, edge_l)):
        cells = fin_cells(base, edge, side)
        erase_from_rows(base, cells, side)
        print(f"  {'右' if side>0 else '左'}耳 抹除底图静耳 {len(cells)} px")
    base.save("preview/rot4-base.png")

    piv = {+1: tuple(cal["pivot_r"]), -1: tuple(cal["pivot_l"])}
    a_lo = min(a for a in ang if a is not None); a_hi = max(a for a in ang if a is not None)
    os.makedirs(OUT, exist_ok=True)
    for k in range(TOTAL):
        ease = 0.5 * (1 - math.cos(math.pi * k / (TOTAL - 1)))
        target = a_lo + (a_hi - a_lo) * ease
        ti = min(range(len(ims)), key=lambda i: abs((ang[i] or 999) - target))
        delta = target - (ang[ti] or target)
        frame = base.copy()
        for side, edge in ((+1, edge_r), (-1, edge_l)):
            fin = layer(ims[ti], fin_cells(ims[ti], edge, side))
            frame = Image.alpha_composite(frame, fin if abs(delta) < 1e-6 else rotate(fin, piv[side], delta))
        out = Image.new("RGBA", (W + 2*PAD, H), (0, 0, 0, 0))
        out.paste(frame, (PAD, 0), frame)
        out.save(os.path.join(OUT, f"耳朵晃动_{k+1}_306.png"))
    print(f"输出 {TOTAL} 帧 → {OUT}")


if __name__ == "__main__":
    main()
