# -*- coding: utf-8 -*-
"""耳朵晃动 30 帧生成器（B1 关键帧版）。

输入：N 张"只有耳鳍角度不同、其余像素一致"的关键帧（已归一化到统一高度）。
输出：30 张 耳朵晃动_1..30_306.png，按半余弦缓动在实测角度区间内摆动。

管线：
  1) 去背景残留（保留 alpha 最大连通域）
  2) 配准（以「发带+面部」锚区对齐到首帧）
  3) 底板 = 逐像素时间中位数，alpha 用"多数帧表决"（避免半透明灰块）
  4) 耳朵作业区（发际以外）用"无鳍头发底板"抹平，避免鳍片残影与旋转后鳍片重影
  5) 摆角由 B1 实测角度表驱动；模板取角度最接近的关键帧，绕鳍根旋转后贴回

用法：python3 packaging/make_ear_frames.py [--project <root>] [--out <dir>]
关键帧目录可用环境变量 EAR_KEYS_DIR 覆盖（开发期指向归一化素材）。
"""
import os
import sys
import math
from collections import deque
from PIL import Image

TOTAL = 30                     # 输出帧数（单程）
MAX_KEYS = 12                  # 关键帧上限
Y_BAND = (78, 150)             # 耳朵竖向范围（306 高画布）
CX = 122                       # 人物中心 x
PIVOT_R = (200, 111)           # 右耳枢轴=鳍根（实测：12 帧鳍尖拟合半径 50±3.5px）
PIVOT_L = (44, 111)            # 左耳枢轴（按中心线镜像）
BOX_R = (196, 74, 244, 152)    # 右耳工作框 (x0,y0,x1,y1)
BOX_L = (0, 74, 48, 152)       # 左耳工作框
ZONE_R = (200, 243)            # 右耳作业区（x 范围，含端点）
ZONE_L = (0, 44)               # 左耳作业区
HAIR_R = (150, 195)            # 右耳侧纯头发取样带
HAIR_L = (49, 94)              # 左耳侧纯头发取样带


def arg_value(argv, name, default=None):
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
    return default


def project_root(argv):
    return arg_value(argv, "--project",
                     os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def alpha_reader(img):
    """返回 alpha 取值函数；必须持有 band 引用，否则像素访问会失效。"""
    band = img.split()[3]
    px = band.load()
    return lambda x, y: px[x, y]


def keep_main_blob(img, thr=60):
    """只保留 alpha 的最大 4 邻接连通域，清掉背景残留（抠图没抠净会留下色块）。"""
    W, H = img.size
    px = alpha_reader(img)
    seen = bytearray(W * H)
    best = []
    for y0 in range(H):
        for x0 in range(W):
            if seen[y0 * W + x0] or px(x0, y0) <= thr:
                continue
            comp = []
            q = deque([(x0, y0)])
            seen[y0 * W + x0] = 1
            while q:
                x, y = q.popleft()
                comp.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and not seen[ny * W + nx] and px(nx, ny) > thr:
                        seen[ny * W + nx] = 1
                        q.append((nx, ny))
            if len(comp) > len(best):
                best = comp
    keep = set(best)
    out = img.copy()
    op = out.load()
    for y in range(H):
        for x in range(W):
            if px(x, y) > thr and (x, y) not in keep:
                op[x, y] = (0, 0, 0, 0)
    return out


def load_frames(root, cap=MAX_KEYS):
    """按 耳朵晃动_1..N_306.png 顺序加载关键帧（N 自适应；素材需先归一化到统一高度）。"""
    spr = os.environ.get("EAR_KEYS_DIR") or os.path.join(root, "src", "sprites")
    ims = []
    for i in range(1, cap + 1):
        p = os.path.join(spr, f"耳朵晃动_{i}_306.png")
        if not os.path.exists(p):
            if ims:
                break
            raise SystemExit(
                f"缺少关键帧源 {p}\n提示：可用 EAR_KEYS_DIR 指定归一化后的关键帧目录。")
        ims.append(keep_main_blob(Image.open(p).convert("RGBA")))
    if len(ims) < 2:
        raise SystemExit(f"关键帧不足（{len(ims)} 张），至少需要 2 张")
    return ims


# ------------------------------------------------------------------ 配准
def region_diff(a, b, box, step=3):
    x0, y0, x1, y1 = box
    tot = n = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            ra, ga, ba, aa = a.getpixel((x, y))
            rb, gb, bb, ab = b.getpixel((x, y))
            tot += abs(ra - rb) + abs(ga - gb) + abs(ba - bb) + abs(aa - ab)
            n += 1
    return tot / max(n, 1)


def register(ref, im):
    """粗到细搜索 (dx, dy, scale)，使锚区（发带+面部）残差最小。"""
    anchor = (30, 25, ref.width - 30, int(ref.height * 0.44))
    best = (0, 0, 1.0, region_diff(ref, im, anchor))
    for rng, step_px, scales in ((4, 4, [0.98, 0.99, 1.0, 1.01, 1.02]),
                                 (2, 2, [best[2]]), (1, 1, [best[2]])):
        cur = best
        for sc in scales:
            scaled = im if sc == 1.0 else im.resize(
                (max(1, round(im.width * sc)), max(1, round(im.height * sc))), Image.LANCZOS)
            ox = (scaled.width - im.width) // 2
            oy = (scaled.height - im.height) // 2
            for dy in range(cur[1] - rng, cur[1] + rng + 1, step_px):
                for dx in range(cur[0] - rng, cur[0] + rng + 1, step_px):
                    canvas = Image.new("RGBA", ref.size, (0, 0, 0, 0))
                    canvas.paste(scaled, (dx - ox, dy - oy))
                    d = region_diff(ref, canvas, anchor)
                    if d < best[3]:
                        best = (dx, dy, sc, d)
    return best


def apply_transform(size, im, dx, dy, sc):
    scaled = im if sc == 1.0 else im.resize(
        (max(1, round(im.width * sc)), max(1, round(im.height * sc))), Image.LANCZOS)
    ox = (scaled.width - im.width) // 2
    oy = (scaled.height - im.height) // 2
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.paste(scaled, (dx - ox, dy - oy))
    return canvas


# ------------------------------------------------------------------ 底板
def temporal_median(frames):
    """逐像素时间中位数；alpha 用"多数帧不透明"表决（否则少数帧不透明处会被 0 稀释成灰块）。"""
    W, H = frames[0].size
    n = len(frames)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px_out = out.load()
    grids = [list(f.getdata()) for f in frames]
    for idx in range(W * H):
        cols, alphas = [], []
        for g in grids:
            r, gg, b, a = g[idx]
            if a > 40:
                cols.append((r, gg, b))
                alphas.append(a)
        if len(cols) * 2 < n:
            continue
        cols.sort(key=lambda c: c[0] + c[1] + c[2])
        alphas.sort()
        px_out[idx % W, idx // W] = cols[len(cols) // 2] + (alphas[len(alphas) // 2],)
    return out


def hair_color_at(img, y, x0, x1):
    """取某行纯头发区的中位色；无可用像素返回 None（绝不用固定色兜底）。"""
    cols = []
    for x in range(x0, x1 + 1):
        p = img.getpixel((x, y))
        if p[3] >= 250:
            cols.append(p)
    if not cols:
        return None
    cols.sort(key=lambda c: c[0] + c[1] + c[2])
    return cols[len(cols) // 2]


def build_hair_plate(regs, rows_per, side, name, band, edge):
    """构造"耳朵区无鳍头发底板"。

    对作业区每个像素：排除该帧"此处属鳍片"的帧，取余下帧的中位色与最大 alpha；
    一帧都不剩则保持透明。于是填进来的是真实发色，而不是模糊色团。
    """
    W, H = regs[0].size
    x_lo, x_hi = ZONE_R if side > 0 else ZONE_L
    ys = sorted({y for rows in rows_per for y in rows})
    if not ys:
        return None
    plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for y in range(ys[0], ys[-1] + 1):
        lim = edge.get(y)
        for x in range(max(0, x_lo), min(W, x_hi)):
            # 只填到该行头发轮廓为止；轮廓之外是背景/鳍片所占空间，留透明
            if lim is not None and ((side > 0 and x > lim + 2) or (side < 0 and x < lim - 2)):
                continue
            cols, alpha = [], 0
            for f, rows in zip(regs, rows_per):
                rng = rows.get(y)
                if rng and rng[0] <= x <= rng[1]:
                    continue                      # 该帧此处是鳍片，不算头发
                q = f.getpixel((x, y))
                if q[3] >= 250:
                    cols.append(q)
                    alpha = max(alpha, q[3])
            if not cols:
                continue
            cols.sort(key=lambda c: c[0] + c[1] + c[2])
            plate.putpixel((x, y), cols[len(cols) // 2][:3] + (alpha,))
    # 兜底：个别行整行无候选时，用纯头发取样带的中位色补齐（仍是真实发色）
    for y in range(ys[0], ys[-1] + 1):
        col = hair_color_at(regs[0], y, *band)
        if col is None:
            continue
        for x in range(max(0, x_lo), min(W, x_hi)):
            if lim is not None and ((side > 0 and x > lim + 2) or (side < 0 and x < lim - 2)):
                continue
            if plate.getpixel((x, y))[3] < 250:
                plate.putpixel((x, y), col)
    return plate


def flatten_zone(base, plate, rows_per, side):
    """用无鳍头发底板替换作业区；基版透明处保持透明（绝不刷背景）。"""
    if plate is None:
        return 0
    W, H = base.size
    x_lo, x_hi = ZONE_R if side > 0 else ZONE_L
    ys = sorted({y for rows in rows_per for y in rows})
    if not ys:
        return 0
    n = 0
    for y in range(ys[0], ys[-1] + 1):
        for x in range(max(0, x_lo), min(W, x_hi)):
            src = plate.getpixel((x, y))
            if src[3] < 250:
                continue
            if base.getpixel((x, y))[3] < 40:
                continue
            base.putpixel((x, y), src)
        n += 1
    return n


def solid_outer(img, y, side, cx):
    """某行最外侧"实体段"的 x（跳过分离的装饰弧线）。"""
    a = alpha_reader(img)
    W = img.width
    if side > 0:
        x = W - 1
        while x >= cx:
            if a(x, y) > 60:
                end = start = x
                while start - 1 >= cx and a(start - 1, y) > 60:
                    start -= 1
                if end - start + 1 >= 6:
                    return end
                x = start - 1
            else:
                x -= 1
    else:
        x = 0
        while x <= cx:
            if a(x, y) > 60:
                start = end = x
                while end + 1 <= cx and a(end + 1, y) > 60:
                    end += 1
                if end - start + 1 >= 6:
                    return start
                x = end + 1
            else:
                x += 1
    return None


def hair_edge(regs, side):
    """逐行头发轮廓：各帧最内侧实体外缘（鳍片只会更外 → 最小值/最大值即无鳍轮廓）。"""
    edge = {}
    for y in range(Y_BAND[0], Y_BAND[1]):
        vals = [v for v in (solid_outer(f, y, side, CX) for f in regs) if v is not None]
        if vals:
            edge[y] = min(vals) if side > 0 else max(vals)
    return edge


# ------------------------------------------------------------------ 旋转
def rotate_patch(patch, pivot, deg):
    """绕 pivot 旋转（逆采样 + 双线性 + alpha 预乘），返回同尺寸新图。"""
    W, H = patch.size
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    src, dst = patch.load(), out.load()
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    pxc, pyc = pivot
    for y in range(H):
        for x in range(W):
            dx, dy = x - pxc, y - pyc
            sx = c * dx + s * dy + pxc
            sy = -s * dx + c * dy + pyc
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
                r += rr * aa * w
                g += gg * aa * w
                b += bb * aa * w
                aw += aa * w
            if aw <= 0:
                continue
            dst[x, y] = (int(r / aw), int(g / aw), int(b / aw), int(min(255, aw)))
    return out


def make_patch(frame, box, x_lo, x_hi):
    """抠出鳍片补丁：box 内、x 落在 [x_lo, x_hi] 的部分，其余透明。"""
    x0, y0, x1, y1 = box
    patch = frame.crop(box).copy()
    px = patch.load()
    for yy in range(patch.height):
        for xx in range(patch.width):
            if not (x_lo <= x0 + xx <= x_hi):
                px[xx, yy] = (0, 0, 0, 0)
    return patch


def rows_of(frame, x_lo, x_hi):
    """作业区内不透明像素的逐行区间 {y: (lo, hi)}。"""
    rows = {}
    for y in range(Y_BAND[0], Y_BAND[1]):
        xs = [x for x in range(max(0, x_lo), min(frame.width, x_hi + 1))
              if frame.getpixel((x, y))[3] > 60]
        if xs:
            rows[y] = (min(xs), max(xs))
    return rows


# ------------------------------------------------------------------ 主流程
def main():
    root = project_root(sys.argv)
    ims = load_frames(root)
    NKEY = len(ims)
    W, H = ims[0].size
    print(f"输入 {NKEY} 帧关键帧 {W}x{H}")

    regs = []
    for i, im in enumerate(ims, 1):
        dx, dy, sc, d = register(ims[0], im)
        regs.append(apply_transform((W, H), im, dx, dy, sc))
        print(f"  帧{i:2d} 配准 dx={dx} dy={dy} scale={sc:.2f} 锚区残差={d:.1f}")

    base = temporal_median(regs)
    cfg = {"右": (+1, PIVOT_R, BOX_R, ZONE_R, HAIR_R),
           "左": (-1, PIVOT_L, BOX_L, ZONE_L, HAIR_L)}
    for name, (side, pivot, box, (zx0, zx1), band) in cfg.items():
        rows_per = [rows_of(f, zx0, zx1) for f in regs]
        plate = build_hair_plate(regs, rows_per, side, name, band, hair_edge(regs, side))
        print(f"  {name}耳 作业区 {zx0}..{zx1} 抹平 {flatten_zone(base, plate, rows_per, side)} 行")

    out_frames = []
    for k in range(1, TOTAL + 1):
        ease = 0.5 * (1 - math.cos(math.pi * (k - 1) / (TOTAL - 1)))   # 端点慢、中间快
        frame = base.copy()
        for name, (side, pivot, box, (zx0, zx1), band) in cfg.items():
            angs = [(i, B1_ANGLES.get(i, {}).get(name)) for i in range(1, NKEY + 1)]
            valid = [(i, a) for i, a in angs if a is not None]
            if len(valid) < 2:
                continue
            lo_a = min(a for _, a in valid)
            hi_a = max(a for _, a in valid)
            target = lo_a + (hi_a - lo_a) * ease
            ti, ta = min(valid, key=lambda t: abs(t[1] - target))
            patch = make_patch(regs[ti - 1], box, zx0, zx1)
            delta = target - ta
            rot = patch if abs(delta) < 1e-9 else rotate_patch(
                patch, (pivot[0] - box[0], pivot[1] - box[1]), delta)
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            layer.paste(rot, (box[0], box[1]))
            frame = Image.alpha_composite(frame, layer)
        out_frames.append(frame)

    outdir = arg_value(sys.argv, "--out", os.path.join(root, "src", "sprites"))
    os.makedirs(outdir, exist_ok=True)
    for i, f in enumerate(out_frames, 1):
        f.save(os.path.join(outdir, f"耳朵晃动_{i}_306.png"), "PNG")
    print(f"输出 {len(out_frames)} 帧 → {outdir}")


B1_ANGLES = {
    1: {"右": None, "左": -49.6},
    2: {"右": -33.7, "左": -35.0},
    3: {"右": -34.4, "左": -38.7},
    4: {"右": -36.4, "左": -36.4},
    5: {"右": -31.9, "左": -35.0},
    6: {"右": -31.9, "左": -35.0},
    7: {"右": -27.5, "左": -35.7},
    8: {"右": -14.9, "左": -25.4},
    9: {"右": 5.3, "左": 4.9},
    10: {"右": 11.6, "左": 12.7},
    11: {"右": 14.9, "左": 18.0},
    12: {"右": 26.1, "左": 24.9},
}


if __name__ == "__main__":
    main()
