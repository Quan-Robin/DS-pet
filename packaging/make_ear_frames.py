# -*- coding: utf-8 -*-
"""耳朵晃动 30 帧（终版 v6）：关键帧头发 + 无耳图擦鳍 + 纯旋转鳍片。

设计（每一层都对应一个已验证的失败原因）：
  * 底图 = **关键帧**（不是 AI 生成的无耳图）→ 头发、发丝、衣服与角色完全一致，
    不会出现"两个版本的头"混合导致的跳变（v5 的 max 跳变 25 来自这里）；
  * 底图自带的鳍片，用**无耳图对应区域**擦掉 → 无耳图正是"同一角色、同一区域、
    只有头发"的像素，所以擦完是真头发，不是涂色（v2/v4 的色斑来自自己涂色）；
  * 鳍片 = 模板关键帧里"发际以外"的像素，绕实测枢轴旋转 → 没有跨帧混色，无残影；
  * 全程只做"擦 + 贴"，不再有任何模式切换或交叉淡化。
"""
import json
import math
import os
import sys
from collections import deque
from PIL import Image

SPR = os.environ.get("EAR_KEYS_DIR", "b1final306")
BASE_IMG = os.environ.get("EAR_BASE_IMG", "b1in/无耳朵-cutout.png")
OUT = sys.argv[1] if len(sys.argv) > 1 else "out_rot6"
TOTAL = 30
PAD = 12
Y_BAND = (72, 152)


def load():
    keys = sorted([f for f in os.listdir(SPR) if f.endswith(".png")],
                  key=lambda s: int(s.split("_")[1]))
    return [Image.open(os.path.join(SPR, f)).convert("RGBA") for f in keys]


def region_diff(a, b, box, step=3):
    x0, y0, x1, y1 = box
    tot = n = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            ra, ga, ba, aa = a.getpixel((x, y))
            rb, gb, bb, ab = b.getpixel((x, y))
            tot += abs(ra-rb)+abs(ga-gb)+abs(ba-bb)+abs(aa-ab); n += 1
    return tot / max(n, 1)


def load_noear(ref):
    """无耳图 → 与关键帧同尺寸并对齐（作为"擦鳍"的填充源）。"""
    im = Image.open(BASE_IMG).convert("RGBA")
    bb = im.split()[3].point(lambda v: 255 if v > 40 else 0).getbbox()
    crop = im.crop(bb)
    W, H = ref.size
    scale = H / float(crop.height)
    small = crop.resize((max(1, int(round(crop.width*scale))), H), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.paste(small, (PAD, 0), small)
    anchor = (int(W*0.30), int(H*0.06), int(W*0.72), int(H*0.42))
    best = (0, 0, region_diff(ref, canvas, anchor))
    for rng, step in ((8, 2), (4, 1), (2, 1)):
        cur = best
        for dy in range(cur[1]-rng, cur[1]+rng+1, step):
            for dx in range(cur[0]-rng, cur[0]+rng+1, step):
                c2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                c2.paste(canvas, (dx, dy), canvas)
                d = region_diff(ref, c2, anchor)
                if d < best[2]: best = (dx, dy, d)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(canvas, (best[0], best[1]), canvas)
    print(f"无耳图对齐：dx={best[0]} dy={best[1]} 锚区残差={best[2]:.1f}")
    return out


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


def fin_cells(im, edge, side, thr=60, grow=3):
    """鳍片像素 = 发际以外的不透明像素（最大连通块），向内膨胀 grow 以盖住接缝。"""
    px = im.load(); W = im.width
    cells = set()
    for y in range(Y_BAND[0], Y_BAND[1]):
        b = edge.get(y)
        if b is None: continue
        rng = range(b+1, W) if side > 0 else range(0, b)
        cells.update((x, y) for x in rng if px[x, y][3] > thr)
    cells = largest(cells)
    out = set(cells)
    for _ in range(grow):
        nxt = set(out)
        for (x, y) in out:
            for nb in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)): nxt.add(nb)
        out = nxt
    return out


def layer(im, cells):
    W, H = im.size
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sp, lp = im.load(), lay.load()
    for (x, y) in cells:
        if 0 <= x < W and 0 <= y < H: lp[x, y] = sp[x, y]
    return lay


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

    # 底图 = 最平耳关键帧（头发与角色一致）
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
        for x in range(0, b+1): bl[x, y] = sl[x, y]
    print(f"底图 = 关键帧 #{flat_r+1}(右) / #{flat_l+1}(左)")

    noear = load_noear(ims[0])
    # 用无耳图把底图自带的鳍擦掉（同区域、只有头发的真实像素）
    for side, edge in ((+1, edge_r), (-1, edge_l)):
        cells = fin_cells(base, edge, side)
        bp, np_ = base.load(), noear.load()
        erased = 0
        for (x, y) in cells:
            if 0 <= x < W and 0 <= y < H:
                q = np_[x, y]
                if q[3] >= 200:
                    bp[x, y] = q; erased += 1
        print(f"  {'右' if side>0 else '左'}耳 用无耳图擦除 {erased}/{len(cells)} px")
    base.save("preview/rot6-base.png")

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
