# -*- coding: utf-8 -*-
"""耳朵晃动 30 帧（旋转版，干净实现）。

关键设计（多次失败后的结论）：
  1) 只旋转**紧抠的鳍片补丁**（= 发际以外 + 少量重叠），绝不带头发一起转——带头发转就会
     在根部留下"残影"（v2~v5 的病根）；
  2) 补丁外的一切像素逐点复制自底图，**不抹平、不填充、不羽化**——没有合成就没有色差；
  3) 底图 = 最平耳朵那张关键帧（外侧区域本来就是透明背景，鳍片转开后不会露馅）；
  4) 逐帧旋转量 = 目标角度 − 模板帧角度，绕实测枢轴做双线性旋转。
"""
import json
import math
import os
import sys
from PIL import Image

SPR = os.environ.get("EAR_KEYS_DIR", "b1final306")
OUT = sys.argv[1] if len(sys.argv) > 1 else "out_rot"
TOTAL = 30
PAD = 12
Y_BAND = (72, 152)


def load():
    keys = sorted([f for f in os.listdir(SPR) if f.endswith(".png")],
                  key=lambda s: int(s.split("_")[1]))
    return [Image.open(os.path.join(SPR, f)).convert("RGBA") for f in keys]


def rotate(img, pivot, deg):
    """绕 pivot 旋转（逆采样 + 双线性 + alpha 预乘）。"""
    W, H = img.size
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    src, dst = img.load(), out.load()
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    for y in range(H):
        for x in range(W):
            dx, dy = x - pivot[0], y - pivot[1]
            sx = c * dx + s * dy + pivot[0]
            sy = -s * dx + c * dy + pivot[1]
            if sx < 0 or sy < 0 or sx >= W - 1 or sy >= H - 1:
                continue
            x0, y0 = int(sx), int(sy)
            fx, fy = sx - x0, sy - y0
            r = g = b = aw = 0.0
            for ox, oy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                              (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
                if w <= 0:
                    continue
                rr, gg, bb, aa = src[x0 + ox, y0 + oy]
                if aa == 0:
                    continue
                r += rr * aa * w; g += gg * aa * w; b += bb * aa * w; aw += aa * w
            if aw <= 0:
                continue
            dst[x, y] = (int(r / aw), int(g / aw), int(b / aw), int(min(255, aw)))
    return out


def fin_patch(base, im, side, edge, overlap=6):
    """从 im 抠出"发际以外"的鳍片（含 overlap 像素重叠），其余透明。"""
    W, H = base.size
    patch = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bp, sp, pp = base.load(), im.load(), patch.load()
    for y in range(Y_BAND[0], Y_BAND[1]):
        b = edge.get(y)
        if b is None:
            continue
        if side > 0:
            for x in range(max(0, b - overlap), W):
                pp[x, y] = sp[x, y]
        else:
            for x in range(0, min(W, b + overlap + 1)):
                pp[x, y] = sp[x, y]
    return patch


def main():
    ims = load()
    cal = json.load(open("b1-calib.json"))
    ang_r = cal["angles_r"]
    piv_r = tuple(cal["pivot_r"]); piv_l = tuple(cal["pivot_l"])
    W, H = ims[0].size
    # 发际轮廓（各帧最内侧外缘的极值）
    def solid(im, y, side):
        px = im.load()
        rng = range(W - 1, W // 2, -1) if side > 0 else range(0, W // 2)
        for x in rng:
            if px[x, y][3] > 60:
                return x
        return None
    edge_r, edge_l = {}, {}
    for y in range(Y_BAND[0], Y_BAND[1]):
        rs = [v for v in (solid(im, y, +1) for im in ims) if v]
        ls = [v for v in (solid(im, y, -1) for im in ims) if v]
        if rs: edge_r[y] = min(rs) + 6
        if ls: edge_l[y] = max(ls) - 6
    # 底图 = 最平耳朵帧（外侧不透明像素最少）
    def outside(im, side):
        px = im.load()
        e = edge_r if side > 0 else edge_l
        n = 0
        for y in range(Y_BAND[0], Y_BAND[1]):
            b = e.get(y)
            if b is None: continue
            rng = range(b, W) if side > 0 else range(0, b + 1)
            n += sum(1 for x in rng if px[x, y][3] > 60)
        return n
    i_right = min(range(len(ims)), key=lambda i: outside(ims[i], +1))
    i_left = min(range(len(ims)), key=lambda i: outside(ims[i], -1))
    base = ims[i_right].copy()
    # 左侧底图区域换成最平左耳的帧（左右可来自不同帧，互不影响）
    if i_left != i_right:
        bl, sl = base.load(), ims[i_left].load()
        for y in range(Y_BAND[0], Y_BAND[1]):
            b = edge_l.get(y)
            if b is None: continue
            for x in range(0, b + 1):
                bl[x, y] = sl[x, y]
    print(f"底图：右耳取帧#{i_right+1}、左耳取帧#{i_left+1}")

    a_lo, a_hi = min(a for a in ang_r if a is not None), max(a for a in ang_r if a is not None)
    os.makedirs(OUT, exist_ok=True)
    canvas_w = W + 2 * PAD
    used = []
    for k in range(TOTAL):
        ease = 0.5 * (1 - math.cos(math.pi * k / (TOTAL - 1)))
        target = a_lo + (a_hi - a_lo) * ease
        ti = min(range(len(ims)), key=lambda i: abs((ang_r[i] or 999) - target))
        used.append(ti + 1)
        frame = base.copy()
        for side, piv, edge, key in ((+1, piv_r, edge_r, "右"), (-1, piv_l, edge_l, "左")):
            patch = fin_patch(base, ims[ti], side, edge)
            delta = target - (ang_r[ti] or target)
            rot = patch if abs(delta) < 1e-6 else rotate(patch, piv, delta)
            frame = Image.alpha_composite(frame, rot)
        out = Image.new("RGBA", (canvas_w, H), (0, 0, 0, 0))
        out.paste(frame, (PAD, 0), frame)
        out.save(os.path.join(OUT, f"耳朵晃动_{k+1}_306.png"))
    print(f"输出 {TOTAL} 帧 → {OUT}")
    print("模板帧 #:", used)


if __name__ == "__main__":
    main()
