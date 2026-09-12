# -*- coding: utf-8 -*-
"""耳朵晃动 30 帧生成器：以 5 张 AI 关键帧为源，合成乒乓循环用的 30 帧。

核心思路（纯 PIL，无 numpy/OpenCV）：
  1) 配准：以「发带+面部」锚区把 5 帧对齐到帧 1（平移 + 小幅缩放，粗到细搜索）
  2) 头发底板：逐像素时间中位数压掉 AI 帧间抖动；耳朵带内改为"沿行取头发色"填充，
     即所谓 flatten —— 把鳍片（含分离的"动态线"弧线）从底板上彻底抹掉，
     否则耳朵转开后残留的鳍片会显成重影。
  3) 鳍片角度标定：每帧鳍尖相对固定枢轴的夹角（枢轴=鳍根，实测稳定）
  4) 采样 30 帧：鳍片绕枢轴旋转到正弦缓动后的目标角度，贴回底板
  5) 输出 耳朵晃动_1..30_306.png

用法：python3 packaging/make_ear_frames.py [--project <root>] [--out <dir>]
"""
import os
import sys
import math
from PIL import Image, ImageFilter

TOTAL = 30
Y_BAND = (55, 175)        # 耳朵竖向范围
CX = 137                  # 人物中心 x
PROTRUDE = 6              # 超出头发包络多少 px 判为鳍片
PIVOT_R = (203, 131)      # 右耳枢轴（鳍根）
PIVOT_L = (135, 131)      # 左耳枢轴（镜像）
BOX_R = (188, 52, 271, 178)   # 右耳工作框 (x0,y0,x1,y1)
BOX_L = (0, 52, 151, 178)     # 左耳工作框


# ------------------------------------------------------------------ 工具
def arg_value(argv, name, default=None):
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
    return default


def project_root(argv):
    return arg_value(argv, "--project",
                     os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_frames(root):
    spr = os.path.join(root, "src", "sprites")
    ims = []
    for i in range(1, 6):
        p = os.path.join(spr, f"耳朵晃动_{i}_306.png")
        if not os.path.exists(p):
            raise SystemExit(
                f"缺少关键帧源 {p}\n提示：素材导出/ 被 .gitignore 排除；"
                f"若 src/sprites/耳朵晃动_1..30_306.png 已入库，则无需重跑本脚本。")
        ims.append(Image.open(p).convert("RGBA"))
    return ims


def alpha_reader(img):
    """返回 alpha 取值函数。注意：必须持有 band 引用，否则像素访问随临时对象失效。"""
    band = img.split()[3]
    px = band.load()
    return lambda x, y: px[x, y]


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


# ------------------------------------------------------------------ 配准
def register(ref, im):
    anchor = (40, 30, ref.width - 40, 135)
    best = (0, 0, 1.0, region_diff(ref, im, anchor))
    for rng, step_px, scales in ((4, 4, [0.97, 0.98, 0.99, 1.0, 1.01, 1.02, 1.03]),
                                 (2, 2, [best[2]]),
                                 (1, 1, [best[2]])):
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
    W, H = frames[0].size
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px_out = out.load()
    grids = [list(f.getdata()) for f in frames]
    for idx in range(W * H):
        rs = gs = bs = as_ = None
        rs, gs, bs, as_ = [], [], [], []
        for g in grids:
            r, gg, b, a = g[idx]
            if a > 40:
                rs.append(r); gs.append(gg); bs.append(b); as_.append(a)
        if not rs:
            continue
        rs.sort(); gs.sort(); bs.sort(); as_.sort()
        m = len(rs) // 2
        px_out[idx % W, idx // W] = (rs[m], gs[m], bs[m], as_[m])
    return out


# ------------------------------------------------------------------ 鳍片测量
def outer_hull(img, side):
    """每行最外侧不透明像素 x（side=+1 右, -1 左）。"""
    hull = {}
    alpha = alpha_reader(img)
    W = img.width
    for y in range(Y_BAND[0], Y_BAND[1]):
        xs = range(W - 1, CX - 1, -1) if side > 0 else range(0, CX + 1)
        for x in xs:
            if alpha(x, y) > 60:
                hull[y] = x
                break
    return hull


def hair_baseline(hulls):
    """头发轮廓 = 逐行外缘的中位数。

    各帧鳍片朝向不同，同一行里"多数帧"的外缘就是头发本身；
    中位数比最小值稳（最小值容易被分离的动态线或镂空带偏）。
    """
    base = {}
    for y in range(Y_BAND[0], Y_BAND[1]):
        vals = sorted(h[y] for h in hulls if y in h)
        if vals:
            base[y] = vals[len(vals) // 2]
    return base


def fin_rows(img, baseline, side, protrude=PROTRUDE):
    """鳍片行 → {y: (inner_x, outer_x)}：外缘明显超出包络的行。

    只在解剖学耳朵带 EAR_Y 内检测：再往下的"外凸"是长发轮廓的自然起伏，
    不是鳍片（会把抹平区扩到脸上）。
    """
    rows = {}
    hull = outer_hull(img, side)
    for y in range(EAR_Y[0], EAR_Y[1]):
        b, far = baseline.get(y), hull.get(y)
        if b is None or far is None:
            continue
        if ((far - b) if side > 0 else (b - far)) <= protrude:
            continue
        inner = (b - 2) if side > 0 else (b + 2)
        rows[y] = (min(inner, far), max(inner, far))
    return rows


def fin_angle(rows, pivot, side):
    """鳍尖相对枢轴的朝向角（度）。"""
    if not rows:
        return None
    y_tip = max(rows, key=lambda y: abs(rows[y][1] - rows[y][0]))
    lo, hi = rows[y_tip]
    x_tip = hi if side > 0 else lo
    return math.degrees(math.atan2(y_tip - pivot[1], (x_tip - pivot[0]) * side))


# ------------------------------------------------------------------ 抹平
HAIR_INNER_R = (150, 200)   # 右耳侧"纯头发"取样带（远离鳍根，必为头发）
HAIR_INNER_L = (74, 124)    # 左耳侧镜像取样带


def hair_color_at(pristine, y, x0, x1):
    """取某行内纯头发区域的中位色（不受描边/高光极值影响）。"""
    cols = []
    for x in range(x0, x1 + 1):
        p = pristine.getpixel((x, y))
        if p[3] > 200:
            cols.append(p)
    if not cols:
        return (36, 44, 92, 255)
    cols.sort(key=lambda c: c[0] + c[1] + c[2])
    return cols[len(cols) // 2]


MIN_RUN = 12   # 行长阈值：更短的不透明段视为与身体分离的装饰性"动态线"


def solid_outer(img, y, side):
    """某行最外侧"实体段"的 x（跳过分离的小弧线）。"""
    alpha = alpha_reader(img)
    W = img.width
    if side > 0:
        x = W - 1
        while x >= CX:
            if alpha(x, y) > 60:
                end = start = x
                while start - 1 >= CX and alpha(start - 1, y) > 60:
                    start -= 1
                if end - start + 1 >= MIN_RUN:
                    return end
                x = start - 1
            else:
                x -= 1
    else:
        x = 0
        while x <= CX:
            if alpha(x, y) > 60:
                start = end = x
                while end + 1 <= CX and alpha(end + 1, y) > 60:
                    end += 1
                if end - start + 1 >= MIN_RUN:
                    return start
                x = end + 1
            else:
                x += 1
    return None


# 耳朵实际所在的行范围（解剖学约束）：低于此范围的外凸属于长发轮廓，不是鳍片。
# 实测 5 帧鳍尖 y 在 81..135 之间，取上界 140 留出余量。
EAR_Y = (58, 140)

EAR_ZONE = {  # 耳朵"作业区"：从该 x 到画布边缘，该带内一律清成头发
    "右": (196, 271),
    "左": (0, 76),
}


def build_hair_plate(regs, rows_per_list, side, name, box):
    """构造"耳朵区无鳍头发底板"。

    对作业区每个像素：
      * 候选 = 各帧中"该像素属于鳍片"的帧要排除（rows_per_list 已给出各帧鳍片行区间），
        剩下的帧里取中位色 —— 于是填进来的是**真实发色**，不是模糊色团；
      * alpha 另算：只要有任一帧在该像素是"头发"（非鳍片且不透明），就取最大 alpha，
        全都不算头发的位置保持透明 —— 否则会把背景的半透明像素抄进来，
        形成一条条横向色带（踩过的坑）。
    """
    W, H = regs[0].size
    x_lo, x_hi = EAR_ZONE[name]
    ys = sorted({y for rows in rows_per_list for y in rows})
    if not ys:
        return None
    y_lo, y_hi = ys[0], ys[-1]

    plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band = HAIR_INNER_R if side > 0 else HAIR_INNER_L
    for y in range(y_lo, y_hi + 1):
        fallback = hair_color_at(regs[0], y, *band)
        for x in range(max(0, x_lo), min(W, x_hi)):
            cols, alpha = [], 0
            for f, rows in zip(regs, rows_per_list):
                rng = rows.get(y)
                if rng and rng[0] <= x <= rng[1]:
                    continue                      # 该帧此处是鳍片，不算头发
                p = f.getpixel((x, y))
                if p[3] > 200:
                    cols.append(p)
                    alpha = max(alpha, p[3])
            if not cols:
                continue                          # 全帧都不是头发 → 透明
            cols.sort(key=lambda c: c[0] + c[1] + c[2])
            plate.putpixel((x, y), cols[len(cols) // 2][:3] + (alpha,))
    return plate


def flatten_band(base, plate, rows_per, side, name):
    """把底板的耳朵作业区整体替换为无鳍头发底板（耳朵随后贴回，遮住接缝）。"""
    if plate is None:
        return 0
    W, H = base.size
    x_lo, x_hi = EAR_ZONE[name]
    ys = sorted({y for rows in rows_per for y in rows})
    if not ys:
        return 0
    for y in range(ys[0], ys[-1] + 1):
        for x in range(max(0, x_lo), min(W, x_hi)):
            base.putpixel((x, y), plate.getpixel((x, y)))
    return ys[-1] - ys[0] + 1


# ------------------------------------------------------------------ 旋转
def rotate_patch(patch, pivot, deg):
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
                r += rr * aa * w; g += gg * aa * w; b += bb * aa * w; aw += aa * w
            if aw <= 0:
                continue
            dst[x, y] = (int(r / aw), int(g / aw), int(b / aw), int(min(255, aw)))
    return out


def make_patch(frame, rows, box):
    """按鳍片行抠出补丁（行内区间像素，其余透明）。box = (x0,y0,x1,y1)。"""
    x0, y0, x1, y1 = box
    patch = frame.crop(box).copy()
    px = patch.load()
    for yy in range(patch.height):
        y = y0 + yy
        if y not in rows:
            for xx in range(patch.width):
                px[xx, yy] = (0, 0, 0, 0)
            continue
        lo, hi = rows[y]
        for xx in range(patch.width):
            if not (lo <= x0 + xx <= hi):
                px[xx, yy] = (0, 0, 0, 0)
    return patch


# ------------------------------------------------------------------ 主流程
def main():
    root = project_root(sys.argv)
    spr = os.path.join(root, "src", "sprites")
    ims = load_frames(root)
    W, H = ims[0].size
    print(f"输入 5 帧 {W}x{H}")

    regs = []
    for i, im in enumerate(ims, 1):
        dx, dy, sc, d = register(ims[0], im)
        regs.append(apply_transform((W, H), im, dx, dy, sc))
        print(f"  帧{i} 配准 dx={dx} dy={dy} scale={sc:.2f} 锚区残差={d:.1f}")

    base = temporal_median(regs)
    med_img = temporal_median(regs)   # 耳朵区柔化填充的素材（用未被修改的副本）

    cfg = {"右": (+1, PIVOT_R, BOX_R), "左": (-1, PIVOT_L, BOX_L)}
    sides = {}
    for name, (side, pivot, box) in cfg.items():
        hulls = [outer_hull(f, side) for f in regs]
        baseline = hair_baseline(hulls)
        rows_per = [fin_rows(f, baseline, side) for f in regs]
        flat_i = min(range(5), key=lambda i: len(rows_per[i]))
        plate = build_hair_plate(regs, rows_per, side, name, box)
        n_rows = flatten_band(base, plate, rows_per, side, name)
        angles = [fin_angle(r, pivot, side) for r in rows_per]
        sides[name] = dict(side=side, pivot=pivot, box=box, rows_per=rows_per,
                           angles=angles, flat_i=flat_i)
        print(f"  {name}耳 鳍片行数 " + ",".join(str(len(r)) for r in rows_per) +
              " 角度 " + ",".join("--" if a is None else f"{a:+.1f}" for a in angles) +
              f" 底板取帧{flat_i + 1}（抹平 {n_rows} 行）")

    out_frames = []
    for k in range(1, TOTAL + 1):
        p = (k - 1) / (TOTAL - 1)
        ease = 0.5 * (1 - math.cos(math.pi * p))
        frame = base.copy()
        for name, c in sides.items():
            valid = [a for a in c["angles"] if a is not None]
            if not valid:
                continue
            lo_a, hi_a = min(valid), max(valid)
            target = lo_a + (hi_a - lo_a) * ease
            # 模板取鳍片行数最多的帧：鳍形最完整，避免逐帧换模板造成闪烁
            src_i = max(range(5), key=lambda i: len(c["rows_per"][i]))
            if not c["rows_per"][src_i] or c["angles"][src_i] is None:
                continue
            patch = make_patch(regs[src_i], c["rows_per"][src_i], c["box"])
            pivot_local = (c["pivot"][0] - c["box"][0], c["pivot"][1] - c["box"][1])
            delta = target - c["angles"][src_i]
            rot = patch if abs(delta) < 1e-9 else rotate_patch(patch, pivot_local, delta)
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            layer.paste(rot, (c["box"][0], c["box"][1]))
            frame = Image.alpha_composite(frame, layer)
        out_frames.append(frame)

    outdir = arg_value(sys.argv, "--out", spr)
    os.makedirs(outdir, exist_ok=True)
    for i, f in enumerate(out_frames, 1):
        f.save(os.path.join(outdir, f"耳朵晃动_{i}_306.png"), "PNG")
    print(f"输出 {len(out_frames)} 帧 → {outdir}")


if __name__ == "__main__":
    main()
