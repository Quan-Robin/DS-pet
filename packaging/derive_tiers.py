# -*- coding: utf-8 -*-
"""从 306 档耳朵晃动帧派生 238/187 档（构建 deb 前运行）。

为什么需要：桌宠按尺寸档加载 耳朵晃动_{i}_{档位}.png；缺失时会退回 306 档并在运行时
缩放（每帧一次，略糊）。派生好档位文件可让各档位都用预缩放的高质量图。

缩放用 alpha 预乘 + LANCZOS，避免半透明边缘出现黑边。

用法：python3 packaging/derive_tiers.py [--project <root>]
"""
import argparse
import os
import sys

from PIL import Image

TIERS = {"238": 238, "187": 187}
SRC_TIER = "306"
MAX_FRAMES = 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project",
                    default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    spr = os.path.join(a.project, "src", "sprites")
    made = 0
    for i in range(1, MAX_FRAMES + 1):
        src = os.path.join(spr, f"耳朵晃动_{i}_{SRC_TIER}.png")
        if not os.path.exists(src):
            break
        im = Image.open(src).convert("RGBA")
        for tier, h in TIERS.items():
            dst = os.path.join(spr, f"耳朵晃动_{i}_{tier}.png")
            scale = h / float(im.height)
            size = (max(1, round(im.width * scale)), h)
            # alpha 预乘缩放：颜色乘 alpha → LANCZOS → 还原，避免半透明边发黑
            src_px = im.load()
            buf = Image.new("RGBA", im.size)
            bp = buf.load()
            for y in range(im.height):
                for x in range(im.width):
                    r, g, b, al = src_px[x, y]
                    bp[x, y] = (r * al // 255, g * al // 255, b * al // 255, al)
            small = buf.resize(size, Image.LANCZOS)
            sp = small.load()
            out = Image.new("RGBA", size)
            op = out.load()
            for y in range(size[1]):
                for x in range(size[0]):
                    r, g, b, al = sp[x, y]
                    if al == 0:
                        op[x, y] = (0, 0, 0, 0)
                    else:
                        op[x, y] = (min(255, r * 255 // al), min(255, g * 255 // al),
                                    min(255, b * 255 // al), al)
            out.save(dst, "PNG")
            made += 1
    print(f"派生档位完成：{made} 个文件（{SRC_TIER} → {'/'.join(TIERS)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
