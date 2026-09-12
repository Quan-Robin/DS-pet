# -*- coding: utf-8 -*-
"""在归一化后的关键帧（306 高）上实测：头发轮廓、各帧鳍尖、拟合枢轴、每帧角度。"""
from PIL import Image
import os, math, json

SPR = os.environ["EAR_KEYS_DIR"]
files = sorted([f for f in os.listdir(SPR) if f.endswith(".png")],
               key=lambda s: int(s.split("_")[1]))

def alpha_of(im):
    band = im.split()[3]; px = band.load()
    return band, (lambda x, y: px[x, y])

ims = [Image.open(os.path.join(SPR, f)).convert("RGBA") for f in files]
W, H = ims[0].size
print(f"{len(ims)} 帧，画布 {W}x{H}")

Y0, Y1 = int(H*0.26), int(H*0.46)     # 耳带粗略范围
def solid_outer(im, y, side, cx):
    """该行最外侧实体段（跳过分离的小弧线）。"""
    band, a = alpha_of(im)
    if side > 0:
        x = W - 1
        while x >= cx:
            if a(x, y) > 60:
                end = start = x
                while start - 1 >= cx and a(start - 1, y) > 60: start -= 1
                if end - start + 1 >= 6: return end
                x = start - 1
            else: x -= 1
    else:
        x = 0
        while x <= cx:
            if a(x, y) > 60:
                start = end = x
                while end + 1 <= cx and a(end + 1, y) > 60: end += 1
                if end - start + 1 >= 6: return start
                x = end + 1
            else: x += 1
    return None

# 人物中心：用发带区（上部）不透明像素的中点
b0, a0 = alpha_of(ims[0])
xs = [x for y in range(int(H*0.05), int(H*0.18)) for x in range(W) if a0(x, y) > 60]
CX = (min(xs) + max(xs)) // 2
print(f"人物中心 CX={CX}（发带区 x {min(xs)}..{max(xs)}）")

# 头发轮廓 = 各帧最内侧实体外缘
edge_r, edge_l = {}, {}
for y in range(Y0, Y1):
    rs = [v for v in (solid_outer(im, y, +1, CX) for im in ims) if v is not None]
    ls = [v for v in (solid_outer(im, y, -1, CX) for im in ims) if v is not None]
    if rs: edge_r[y] = min(rs)
    if ls: edge_l[y] = max(ls)

def tip(im, side, edge):
    best = None
    for y in range(Y0, Y1):
        far = solid_outer(im, y, side, CX)
        b = edge.get(y)
        if far is None or b is None: continue
        beyond = (far - b) if side > 0 else (b - far)
        if beyond > 1 and (best is None or beyond > best[2]): best = (far, y, beyond)
    return best

tips_r = [tip(im, +1, edge_r) for im in ims]
tips_l = [tip(im, -1, edge_l) for im in ims]

def fit_pivot(pts, cx0):
    best = None
    for span in (60, 20, 6, 2):
        if best is None: cxs, cys = range(cx0-span, cx0+span+1, max(1,span//20)), range(int(H*0.30), int(H*0.40))
        else: cxs, cys = range(int(best[0]-span), int(best[0]+span+1), max(1,span//20)), range(int(best[1]-span), int(best[1]+span+1), max(1,span//20))
        for cx in cxs:
            for cy in cys:
                ds = [math.hypot(x-cx, y-cy) for x, y, _ in pts]
                m = sum(ds)/len(ds)
                var = sum((d-m)**2 for d in ds)/len(ds)
                if best is None or var < best[2]: best = (cx, cy, var, m)
    return best

pr = fit_pivot([t for t in tips_r if t], CX + int(W*0.29))
# 左枢轴按人物中线镜像右枢轴（同物种左右对称，独立拟合会漂到画面中心导致角度失真）
pl = (2*CX - pr[0], pr[1], pr[2], pr[3])
print(f"右耳枢轴={pr[0],pr[1]} 半径={pr[3]:.1f}±{math.sqrt(pr[2]):.1f}")
print(f"左耳枢轴={pl[0],pl[1]}（镜像自右耳）")

out = {"CX": CX, "W": W, "H": H, "Y_BAND": [Y0, Y1],
       "PIVOT_R": [int(pr[0]), int(pr[1])], "PIVOT_L": [int(pl[0]), int(pl[1])],
       "frames": []}
for i, f in enumerate(files, 1):
    tr, tl = tips_r[i-1], tips_l[i-1]
    ar = math.degrees(math.atan2(-(tr[1]-pr[1]), (tr[0]-pr[0]))) if tr else None
    al = math.degrees(math.atan2(-(tl[1]-pl[1]), (pl[0]-tl[0]))) if tl else None
    out["frames"].append({"file": f, "tip_r": tr[:2] if tr else None, "ang_r": ar,
                          "tip_l": tl[:2] if tl else None, "ang_l": al})
    print(f"  {f:22s} 右角={ar if ar is None else round(ar,1)!s:>7s} 右尖={tr[:2] if tr else '-'}  左角={al if al is None else round(al,1)!s:>7s} 左尖={tl[:2] if tl else '-'}")
json.dump(out, open("b1-measure.json", "w"), ensure_ascii=False, indent=1)
angr = [f["ang_r"] for f in out["frames"] if f["ang_r"] is not None]
angl = [f["ang_l"] for f in out["frames"] if f["ang_l"] is not None]
print(f"\n右耳角度范围 {min(angr):+.1f} .. {max(angr):+.1f}（跨度 {max(angr)-min(angr):.1f}°）")
print(f"左耳角度范围 {min(angl):+.1f} .. {max(angl):+.1f}（跨度 {max(angl)-min(angl):.1f}°）")
