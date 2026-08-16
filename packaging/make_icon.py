# -*- coding: utf-8 -*-
"""把 sprites/icon.png 放大为 256x256 的桌面图标"""
import os
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt

src = os.path.join(os.path.dirname(__file__), "..", "src", "sprites", "icon.png")
out = os.path.join(os.path.dirname(__file__), "..", "dist", "dafeiyu-pet.png")
os.makedirs(os.path.dirname(out), exist_ok=True)

img = QImage(src)
scaled = img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
ok = scaled.save(out, "PNG")
print("saved" if ok else "FAILED", out, scaled.size())
