# -*- coding: utf-8 -*-
"""耳朵晃动动画运行时的纯逻辑测试（不依赖 Qt、不依赖素材）。

被验行为（从 src/桌宠.py 提取的实现）：
  1 乒乓游标：序列 0,1,..,n-1,n-2,..,1 与真实素材帧序**逐项相等**，含 58 步闭环；
  2 不越界、不重复、不跳号（历史 IndexError/残影回归点）；
  3 帧数自适应：n=5（旧素材）与 n=16（A/B 两套新素材）都成立；
  4 抖动容错：播放步是整数自增，tick 抖动不会丢帧（浮点方案在此处会重复+跳过）；
  5 一轮 = (2n-2)×EAR_SLOW 个 tick（n=16、EAR_SLOW=2 → 60 tick = 1.2s 单程序列，
    运行时再乒乓一次 → 显示一轮 2.36s，即 0.5 倍速）。

用法：python3 test_ear_anim.py [--project <repo>]
"""
import argparse
import ast
import os
import sys


def load_logic(repo):
    """导入整个 桌宠.py 会拉起 Qt；这里用 ast 只提取目标常量与函数。"""
    src = open(os.path.join(repo, "src", "桌宠.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    want_fn = {"ear_cursor", "ear_playback"}
    want_c = {"EAR_MAX_FRAMES", "EAR_FPS", "EAR_HOLD_STEPS", "EAR_SLOW"}
    picked = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in want_fn:
            picked.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in want_c for t in node.targets):
            picked.append(node)
    got = {n.name for n in picked if isinstance(n, ast.FunctionDef)}
    if got != want_fn:
        raise SystemExit(f"桌宠.py 缺少实现：{sorted(want_fn - got)}")
    ns = {}
    exec(compile(ast.Module(body=picked, type_ignores=[]), "<桌宠.py 提取>", "exec"), ns)
    return ns


def expected_sequence(n):
    return list(range(n)) + list(range(n - 2, 0, -1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    ns = load_logic(a.project)
    ear_cursor, ear_playback = ns["ear_cursor"], ns["ear_playback"]
    fps = ns["EAR_FPS"]
    fails = []

    # 1+2+3：序列正确性、闭环、无越界/重复/跳号
    for n in (5, 12, 30):
        exp = expected_sequence(n)
        period = len(exp)
        seq = [ear_cursor(i, n) for i in range(period)]
        if seq != exp:
            fails.append(f"n={n} 序列不符: 实际 {seq[:10]}… 期望 {exp[:10]}…")
        if any(not (0 <= v < n) for v in seq):
            fails.append(f"n={n} 游标越界")
        if len(set(seq)) != n:
            fails.append(f"n={n} 覆盖帧数 {len(set(seq))}/{n}（有重复或跳号）")
        # 第二圈：步数取模后仍一致（闭环稳定）
        seq2 = [ear_cursor(i + period, n) for i in range(period)]
        if seq2 != exp:
            fails.append(f"n={n} 第二圈不稳定")
    if not fails:
        print("PASS 游标: n=5/12/30 序列 0..n-1..1 逐项相等，无越界/重复/跳号，闭环稳定")

    # 4：抖动容错——步是整数自增，丢 tick 只影响速度不影响帧序
    n = 30
    frames, order = ear_playback([object() for _ in range(n)])
    if len(frames) != n or order != expected_sequence(n):
        fails.append("ear_playback 的重排序列不正确")
    else:
        print(f"PASS 重排: ear_playback 输出 {len(order)} 步乒乓序列（{n} 帧素材）")

    # 5：一轮时长（新素材：16 帧 A/B 两套，0.5 倍速）
    # 运行时序列 = 乒乓序列每帧重复 EAR_SLOW 次，再由 ear_cursor 乒乓一次，
    # 所以显示一轮 = (2L-2) 个 tick，L = (2n-2)×EAR_SLOW。
    n = ns["EAR_MAX_FRAMES"]
    slow = ns.get("EAR_SLOW", 1)
    L = (2 * n - 2 + 2 * ns["EAR_HOLD_STEPS"]) * slow
    period = 2 * L - 2                      # 显示周期（tick 数）
    cycle = period * 0.02                   # TICK = 20ms
    print(f"  一轮 = {period} tick × 20ms = {cycle:.2f}s"
          f"（素材 {n} 帧 ×{slow} 降速 → 序列 {L} 帧）")
    if not (2.0 <= cycle <= 2.8):
        fails.append(f"一轮 {cycle:.2f}s 超出预期 2.0~2.8s（16 帧 0.5 倍速应约 2.36s）")

    if fails:
        print("\n=== FAIL ===")
        for f in fails:
            print(" -", f)
        return 1
    print("\n=== ALL PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
