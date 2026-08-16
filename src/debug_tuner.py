# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 · 调试参数窗口

- 参数按尺寸档位（大/中/小）分别设置：写 config.json 的 键名_档位。
- 拖动滑条实时写入 ~/.config/dafeiyu-pet/config.json，
  桌宠每 1.5s 检测变化并热重载，无需重启桌宠。
- 用法：python3 debug_tuner.py
"""
import json
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "dafeiyu-pet", "config.json")
LABELS = ["大", "中", "小"]

# (config键, 显示名, 滑条最小, 滑条最大, 滑条步进, 默认滑条值, 除因子)
PARAMS = [
    ("peek_edge_bottom", "底部超屏 (px)", 0, 200, 1, 17, 1),
    ("peek_edge_top", "顶部超屏 (px)", 0, 200, 1, 5, 1),
    ("peek_edge_left", "左部超屏 (px)", 0, 200, 1, 10, 1),
    ("peek_edge_right", "右部超屏 (px)", 0, 200, 1, 7, 1),
    ("peek_hold", "探头停留 (秒)", 10, 600, 10, 50, 10),
    ("peek_move", "探入/缩回 (秒)", 1, 100, 1, 8, 10),
    ("peek_chance", "出屏概率 (%)", 0, 100, 5, 25, 100),
    ("probe_scale", "探头图缩放 (%)", 40, 200, 5, 90, 100),
    ("walk_speed", "散步速度 (px/s)", 0, 2000, 10, 200, 1),
    ("follow_speed", "跟随速度 (px/s)", 0, 3000, 50, 400, 1),
    ("lie_hold", "趴下时长 (秒)", 5, 300, 5, 50, 10),
    ("lie_scale", "趴下图缩放 (%)", 40, 200, 5, 100, 100),
]


def load_cfg():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class Tuner(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("大肥鱼桌宠 · 调试参数")
        self.setMinimumWidth(380)
        self.cfg = load_cfg()
        self._migrate()
        self._rows = []
        self._dirty = False

        lay = QVBoxLayout(self)

        head = QHBoxLayout()
        head.addWidget(QLabel("尺寸档位："))
        self.combo = QComboBox()
        self.combo.addItems(LABELS)
        self.combo.currentTextChanged.connect(self._on_label_changed)
        tip = QLabel("拖动滑条 → 1.5s 内生效（无需重启）")
        tip.setStyleSheet("color: #888; font-size: 12px;")
        head.addWidget(self.combo)
        head.addWidget(tip, 1)
        lay.addLayout(head)

        for key, name, lo, hi, step, default, div in PARAMS:
            row = QHBoxLayout()
            lab = QLabel(name)
            lab.setFixedWidth(130)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(lo, hi)
            slider.setSingleStep(step)
            slider.setPageStep(step * 2)
            val = QLabel()
            val.setFixedWidth(56)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(lab)
            row.addWidget(slider, 1)
            row.addWidget(val)
            lay.addLayout(row)
            slider.valueChanged.connect(lambda _v, k=key, s=slider, v=val, d=div: self._on_change(k, s, v, d))
            self._rows.append((key, slider, val, div))

        btns = QHBoxLayout()
        reset = QPushButton("恢复本档默认")
        reset.clicked.connect(self._reset)
        self.status = QLabel("")
        self.status.setStyleSheet("color: #2a7; font-size: 12px;")
        btns.addWidget(reset)
        btns.addWidget(self.status, 1)
        lay.addLayout(btns)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush)

        self._reload_sliders()

    # ---- 档位 ----
    @property
    def label(self):
        return self.combo.currentText()

    def _migrate(self):
        """旧配置（无后缀键）→ 复制为 _中（用户此前调好的就是中档），并删除旧键，
        避免"大/小"档 fallback 到中档旧值而非默认值。"""
        if any(f"{k}_{l}" in self.cfg for k, _, _, _, _, _, _ in PARAMS for l in LABELS):
            return
        for key, _, _, _, _, _, _ in PARAMS:
            if key in self.cfg:
                self.cfg[f"{key}_中"] = self.cfg[key]
                del self.cfg[key]
        save_cfg(self.cfg)

    def _on_label_changed(self, _label):
        self._reload_sliders()
        self.status.setText(f"当前档位：{self.label}")

    def _reload_sliders(self):
        for key, slider, val, div in self._rows:
            cur = self.cfg.get(f"{key}_{self.label}", self.cfg.get(key))
            if cur is None:
                default = next(d for k, _, _, _, _, d, _ in PARAMS if k == key)
                cur = default / div
            slider.blockSignals(True)
            slider.setValue(int(round(cur * div)))
            slider.blockSignals(False)
            val.setText(f"{slider.value() / div:g}")

    # ---- 读写 ----
    def _on_change(self, key, slider, val, div):
        v = slider.value() / div
        val.setText(f"{v:g}")
        self.cfg[f"{key}_{self.label}"] = round(v, 2)
        self.status.setText("待写入…")
        self._dirty = True
        self._save_timer.start(300)  # 防抖

    def _flush(self):
        if self._dirty:
            save_cfg(self.cfg)
            self._dirty = False
            self.status.setText(f"已写入（{self.label}），1.5s 内生效 ✓")

    def _reset(self):
        for key, slider, val, div in self._rows:
            default = next(d for k, _, _, _, _, d, _ in PARAMS if k == key)
            slider.setValue(default)
            self._on_change(key, slider, val, div)
        self._flush()
        self.status.setText(f"已恢复 {self.label} 档默认 ✓")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Tuner()
    w.show()
    sys.exit(app.exec())
