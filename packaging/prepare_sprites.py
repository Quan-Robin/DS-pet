# -*- coding: utf-8 -*-
"""把用户制作的素材（探头图/趴下图/耳朵晃动帧）预处理为程序精灵规格。

关键改进：以"内容包围盒"为准做归一化——裁剪透明边缘后，
按人物实际高度统一缩放（而不是按画布尺寸），再贴底水平居中，
保证多帧动画人物大小一致、不跳动。

用法：python3 packaging/prepare_sprites.py
素材源目录：素材导出/探头/、素材导出/趴下/、素材导出/耳朵晃动/
输出：src/sprites/ 下的精灵文件（透明 PNG）
"""
import os
from collections import deque
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "素材导出")
OUT = os.path.join(ROOT, "src", "sprites")
H = 306  # 精灵统一高度（人物实际高度）

def remove_white_bg_flood(img, thr=232):
    """白底抠图（洪水填充法）：只清除与画面边缘连通的浅色背景，
    人物内部的白色（被深色轮廓包围）保留——解决白裙/白毛人物的误抠。"""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    v = memoryview(img.bits())
    visited = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.append((x, 0))
        q.append((x, h - 1))
    for y in range(h):
        q.append((0, y))
        q.append((w - 1, y))
    while q:
        x, y = q.popleft()
        if visited[y * w + x]:
            continue
        visited[y * w + x] = 1
        i = (y * w + x) * 4
        if min(v[i], v[i + 1], v[i + 2]) < thr:
            continue  # 遇到深色（人物轮廓）停住
        v[i + 3] = 0  # 背景转透明
        if x > 0:
            q.append((x - 1, y))
        if x < w - 1:
            q.append((x + 1, y))
        if y > 0:
            q.append((x, y - 1))
        if y < h - 1:
            q.append((x, y + 1))
    return img

def content_bbox(img):
    """内容（非透明像素）包围盒：返回 (x, y, w, h)；空图返回 (0,0,0,0)。"""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    v = memoryview(img.bits())
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        row = y * w * 4
        for x in range(w):
            if v[row + x * 4 + 3] > 30:
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
    if maxx < 0:
        return (0, 0, 0, 0)
    return (minx, miny, maxx - minx + 1, maxy - miny + 1)

def normalize(path, out_name, remove_bg=False, canvas_w=None):
    """裁剪透明边缘 → 人物统一高度 H → 贴底水平居中 → 画布 (canvas_w or 内容宽) x H。"""
    img = QImage(path)
    if img.isNull():
        print("跳过（无法读取）:", path)
        return None
    if remove_bg:
        img = remove_white_bg_flood(img)
    bx, by, bw, bh = content_bbox(img)
    if bh == 0:
        print("跳过（无内容）:", path)
        return None
    crop = img.copy(bx, by, bw, bh)
    scaled = crop.scaledToHeight(H, Qt.TransformationMode.SmoothTransformation)
    if canvas_w is None:
        canvas_w = scaled.width()
    canvas = QImage(canvas_w, H, QImage.Format.Format_RGBA8888)
    canvas.fill(Qt.GlobalColor.transparent)
    p = QPainter(canvas)
    p.drawImage((canvas_w - scaled.width()) // 2, 0, scaled)
    p.end()
    ok = canvas.save(os.path.join(OUT, out_name), "PNG")
    print(f"{'OK ' if ok else 'FAIL'} {out_name} (人物 {scaled.width()}x{H}, 画布 {canvas_w}x{H})")
    return scaled.width()

# 探头图（单张姿态）
probe = os.path.join(SRC, "探头", "探头-ai-v2.png")
if os.path.exists(probe):
    normalize(probe, "探头_306.png")

# 趴下图（白底，需抠图）
lie = os.path.join(SRC, "趴下", "趴下-v3-ai.png")
if os.path.exists(lie):
    normalize(lie, "趴下_306.png", remove_bg=True)

# 耳朵晃动帧：先统一人物大小（内容高度 → H），画布宽取组内最宽
ear_dir = os.path.join(SRC, "耳朵晃动")
ear_files = sorted(os.listdir(ear_dir)) if os.path.isdir(ear_dir) else []
ear_srcs = [f for f in ear_files if f.lower().endswith(".png")]
ear_w = 0
for f in ear_srcs:
    img = QImage(os.path.join(ear_dir, f))
    if img.isNull():
        continue
    _, _, bw, bh = content_bbox(img)
    if bh:
        ear_w = max(ear_w, int(bw * H / bh))  # 缩放到统一高度后的内容宽度
for i, f in enumerate(ear_srcs, 1):
    normalize(os.path.join(ear_dir, f), f"耳朵晃动_{i}_306.png", canvas_w=ear_w)
