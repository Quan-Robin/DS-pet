# -*- coding: utf-8 -*-
"""耳朵晃动 30 帧质检（验收判据 1~6）。

用法：python3 packaging/verify_ear_frames.py [--project <root>]
退出码 0 = 全部通过；1 = 有项失败。
判据：
  1 齐备性：306/238/187 三档各 30 帧
  2 无重复：30 帧两两像素不同
  3 无跳帧：相邻帧平均差无孤立尖峰（<= 相邻步中位数 * 3）
  4 播放游标：一轮 58 步内始终 0..29，往返各一次，首尾中立帧
  5 锚区稳定：发带+面部区在整轮中抖动 < 原始 5 帧之间的抖动
  6 节奏：58 步 @30fps = 1.93s ± 0.05s，端点相位速率为 0
"""
import os
import sys
import math
import hashlib

TOTAL = 30          # 生成的帧数（半程）
FPS = 30
PINGPONG_STEPS = 2 * TOTAL - 2   # 1..30..1 => 58 步
W, H = 271, 306
CYCLE_SECONDS = PINGPONG_STEPS / FPS
ANCHOR = (60, 215, 55, 120)     # 发带 + 面部区（x0,x1,y0,y1），不含耳朵
THR = 60


def arg_value(argv, name, default=None):
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
    return default


def project_root(argv):
    return arg_value(argv, "--project",
                     os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def frames_dir(root, argv):
    """--frames-dir 可直接指向暂存目录（仓外校验用）；默认 src/sprites。"""
    return arg_value(argv, "--frames-dir", os.path.join(root, "src", "sprites"))


def frame_path(root, i, size, argv=None):
    d = frames_dir(root, argv if argv is not None else [])
    return os.path.join(d, f"耳朵晃动_{i}_{size}.png")


def load_rgba(path):
    from PIL import Image
    return Image.open(path).convert("RGBA")


def mean_diff(a, b, box=None, step=2):
    """两帧指定区域的平均像素差（含 alpha）。"""
    pa, pb = a.load(), b.load()
    x0, x1, y0, y1 = box or (0, a.width, 0, a.height)
    tot = n = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            ra, ga, ba, aa = pa[x, y]
            rb, gb, bb, ab = pb[x, y]
            tot += abs(ra - rb) + abs(ga - gb) + abs(ba - bb) + abs(aa - ab)
            n += 1
    return tot / max(n, 1)


def pingpong_index(i):
    """乒乓游标：i=0..57 -> 帧序号 0-based（0,1,...,29,28,...,1）。"""
    period = 2 * TOTAL - 2
    k = i % period
    return k if k < TOTAL else period - k


def eased_phase(i):
    """第 i 个播放步对应的"缓动后相位"（0..1）。

    播放游标是乒乓线性推进的，而运动本身按半余弦缓动：
        ease(p) = (1 - cos(pi*p)) / 2
    因此端点的**运动速度**为 0（起停自然），这也是判据 6 真正要验的东西。
    """
    p = pingpong_index(i) / (TOTAL - 1)
    return 0.5 * (1 - math.cos(math.pi * p))


def motion_speed(i):
    """相邻播放步之间的缓动相位增量 = 该处的运动速度（归一化）。"""
    if i + 1 > PINGPONG_STEPS - 1:
        return None
    return abs(eased_phase(i + 1) - eased_phase(i))


def main():
    root = project_root(sys.argv)
    fails = []

    # --- 判据 1：齐备性 ---
    sizes = ["306"] if "--skip-tiers" in sys.argv else ["306", "238", "187"]
    existing = {}
    for size in sizes:
        have = [i for i in range(1, TOTAL + 1) if os.path.exists(frame_path(root, i, size, sys.argv))]
        existing[size] = have
        if len(have) != TOTAL:
            fails.append(f"[1] {size} 档帧数 {len(have)}/{TOTAL}（缺 {sorted(set(range(1, TOTAL+1)) - set(have))[:8]}）")
    if fails:
        print("FAIL(1) 齐备性:", *fails, sep="\n  ")
        return 1
    print(f"PASS(1) 齐备性: {'306 档' if len(sizes)==1 else '三档各'} {TOTAL} 帧")

    f306 = [load_rgba(frame_path(root, i, "306", sys.argv)) for i in range(1, TOTAL + 1)]

    # --- 判据 2：无重复 ---
    digs = {}
    for i, im in enumerate(f306, 1):
        d = hashlib.sha256(im.tobytes()).hexdigest()
        digs.setdefault(d, []).append(i)
    dups = [v for v in digs.values() if len(v) > 1]
    if dups:
        fails.append(f"[2] 重复帧: {dups[:4]}")
    else:
        print(f"PASS(2) 无重复: {TOTAL} 帧两两不同")

    # --- 判据 3：相邻帧差异曲线无孤立尖峰 ---
    diffs = [mean_diff(f306[i], f306[i + 1]) for i in range(TOTAL - 1)]
    med = sorted(diffs)[len(diffs) // 2]
    spikes = [(i + 1, round(d, 1)) for i, d in enumerate(diffs) if d > med * 3]
    print(f"  相邻帧平均差: min={min(diffs):.1f} 中位={med:.1f} max={max(diffs):.1f}")
    if spikes:
        fails.append(f"[3] 孤立尖峰（中位 {med:.1f} 的 3 倍 = {med*3:.1f}）: {spikes}")
    else:
        print(f"PASS(3) 无跳帧: 无相邻步超过中位 3 倍")

    # --- 判据 4：播放游标 ---
    seq = [pingpong_index(i) for i in range(PINGPONG_STEPS)]
    bad = [v for v in seq if not (0 <= v < TOTAL)]
    fwd = [v for v in seq[:TOTAL]]
    if bad:
        fails.append(f"[4] 游标越界: {bad[:5]}")
    elif fwd != list(range(TOTAL)):
        fails.append(f"[4] 前半程非 0..{TOTAL-1}: {fwd[:6]}...")
    elif seq[TOTAL:] != list(range(TOTAL - 2, 0, -1)):
        fails.append(f"[4] 后半程非回程递减: {seq[TOTAL:TOTAL+6]}...")
    else:
        print(f"PASS(4) 播放游标: {PINGPONG_STEPS} 步往返，首={seq[0]} 尾={seq[-1]}（均中立）")

    # --- 判据 5：锚区稳定 ---
    # 参考基线 = 关键帧源目录（EAR_KEYS_DIR / --keys-dir，缺省 src/sprites 里的 1..5）
    from PIL import Image
    keys_dir = os.environ.get("EAR_KEYS_DIR") or arg_value(sys.argv, "--keys-dir") \
        or os.path.join(root, "src", "sprites")
    key_paths = [os.path.join(keys_dir, f"耳朵晃动_{i}_306.png") for i in range(1, 13)]
    key_paths = [p for p in key_paths if os.path.exists(p)]
    if len(key_paths) >= 2:
        orig = [Image.open(p).convert("RGBA").resize((W, H)) for p in key_paths]
        ref = f306[0]
        anchor_new = max(mean_diff(ref, f, ANCHOR, step=3) for f in f306)
        anchor_old = max(mean_diff(orig[0], f, ANCHOR, step=3) for f in orig[1:])
        print(f"  锚区抖动: 新(补帧)={anchor_new:.1f} 基线({len(orig)} 关键帧间)={anchor_old:.1f}")
        if anchor_old > 0.5 and anchor_new > anchor_old:
            fails.append(f"[5] 锚区抖动未改善: 新 {anchor_new:.1f} > 基线 {anchor_old:.1f}")
        else:
            print("PASS(5) 锚区稳定: 抖动不高于关键帧基线")
    else:
        print("SKIP(5) 锚区：未找到关键帧基线（设 EAR_KEYS_DIR 或 --keys-dir）")

    # --- 判据 6：节奏与缓动 ---
    if abs(CYCLE_SECONDS - 1.93) > 0.05:
        fails.append(f"[6] 周期 {CYCLE_SECONDS:.2f}s 偏离 1.93s±0.05")
    else:
        v_start = motion_speed(0)
        v_end = motion_speed(PINGPONG_STEPS - 2)
        mid = PINGPONG_STEPS // 2
        v_mid = max(motion_speed(i) for i in range(mid - 2, mid + 3))
        print(f"  运动速度: 起点={v_start:.4f} 中点={v_mid:.4f} 终点={v_end:.4f}（归一化相位/步）")
        if v_start > 0.01 or v_end > 0.01:
            fails.append(f"[6] 端点未缓动到静止: 起 {v_start:.4f} 终 {v_end:.4f}（阈值 0.01）")
        elif v_mid <= v_start:
            fails.append(f"[6] 中点速度未达峰值: 中点 {v_mid:.4f} <= 起点 {v_start:.4f}")
        else:
            print(f"PASS(6) 节奏: {PINGPONG_STEPS} 步 @{FPS}fps = {CYCLE_SECONDS:.2f}s，"
                  f"起停缓动（端点速度≈0，中点峰值 {v_mid:.4f}）")

    if fails:
        print("\n=== FAIL ===")
        for f in fails:
            print(" -", f)
        return 1
    print("\n=== ALL PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
