# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 三视图透明桌宠 + DeepSeek AI 对话
左键单击：弹出功能列表（🗨️图标）→ 点击🗨️弹出聊天框
聊天时只禁用移动，呼吸/摇摆/小动作正常
"""
import psutil
import json
import math
import os
import random
import subprocess
import sys
import threading

if sys.platform == "win32":
    import ctypes  # 仅 Windows 鼠标穿透需要

try:
    import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except:
    GPU_AVAILABLE = False

import requests
from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QRect, QEvent
from PySide6.QtGui import (QPainter, QPixmap, QFont, QColor, QIcon, QFontMetrics,
                           QPolygonF, QActionGroup)
from PySide6.QtWidgets import (QApplication, QWidget, QMenu, QSystemTrayIcon,
                               QMessageBox, QInputDialog, QLineEdit, QVBoxLayout,
                               QHBoxLayout, QPushButton, QFrame, QDialog, QToolButton)
from dsh_monitor import DshMonitor



# ===== DeepSeek 配置 =====
DS_BASE_URL = "https://api.deepseek.com/v1"
DS_MODEL = "deepseek-chat"
DS_SYSTEM = "你是桌面宠物大肥鱼，贱兮兮但可爱，每句话不超过25字，偶尔吐槽主人但别真骂人。"

# X11 全局鼠标位置查询（QCursor.pos() 在 Qt6.11 + XWayland 下返回哨兵坐标失效）
_x11_lib = None
_x11_dpy = None

# 训练服务名（Season 4 生产测量）——训练期间不运行桌宠，避免 GPU 负载。
# 个人环境专用：config.json 的 block_service 为空（默认）时不检查。
TRAINING_UNIT = "junqi-season4-production-measurement-v1.service"


def training_running():
    """训练服务是否在运行（仅 config 指定了 block_service 时检查）。"""
    try:
        cfg = load_json(CONFIG_PATH, {})
        unit = cfg.get("block_service") or ""
        if not unit:
            return False
        out = subprocess.run(["systemctl", "--user", "is-active", unit],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() == "active"
    except Exception:
        return False

def pointer_pos():
    """XQueryPointer 直调获取鼠标全局位置；失败返回 None。"""
    global _x11_lib, _x11_dpy
    import ctypes  # 无条件导入（避免局部作用域未绑定）
    try:
        if _x11_lib is None:
            _x11_lib = ctypes.CDLL("libX11.so.6")
            _x11_lib.XOpenDisplay.restype = ctypes.c_void_p
            _x11_lib.XDefaultRootWindow.restype = ctypes.c_ulong
        if _x11_dpy is None:
            _x11_dpy = _x11_lib.XOpenDisplay(None)
        if not _x11_dpy:
            return None
        root = ctypes.c_ulong(_x11_lib.XDefaultRootWindow(_x11_dpy))
        rr = ctypes.c_ulong()
        ch = ctypes.c_ulong()
        rx = ctypes.c_int()
        ry = ctypes.c_int()
        wx = ctypes.c_int()
        wy = ctypes.c_int()
        mask = ctypes.c_uint()
        if _x11_lib.XQueryPointer(_x11_dpy, root, ctypes.byref(rr), ctypes.byref(ch),
                                  ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(wx),
                                  ctypes.byref(wy), ctypes.byref(mask)):
            return rx.value, ry.value
    except Exception:
        pass
    return None

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
    PYTHONW = sys.executable
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR
    PYTHONW = os.path.join(APP_DIR, ".venv", "Scripts", "pythonw.exe")
SPRITE_DIR = os.path.join(BUNDLE_DIR, "sprites")
if sys.platform == "win32":
    # Windows：配置放程序目录（原版行为）
    CONFIG_PATH = os.path.join(APP_DIR, "config.json")
else:
    # Linux：/usr、/opt 等系统目录不可写，配置放到用户配置目录
    CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "dafeiyu-pet", "config.json")

BUBBLE_H = 56
MARGIN = 4
SIZE_LEVELS = {"小": 0.55, "中": 0.7, "大": 0.9}
TICK = 20
# 探头/移动可调参数：默认值在 _load_tunables()，可用 config.json 覆盖。
# 调试窗口 debug_tuner.py 实时调节，桌宠 1.5s 内热重载生效。
LONELY_AFTER = 300     # 秒：用户超过此时间未互动，桌宠主动说话
LONELY_COOLDOWN = 120  # 秒：两次主动说话的最小间隔

LINES = [
    "梁白开，更适合国人的大硬鲸模型",
    "五梁威力，变身！",
    "七月中出ds正式版！",
    "DeepSeek已经延期，亿万鲸子必须忍耐.....",
    "我和你很聊得来，你简直不像碳基生物",
    "这回我真不认怂了，反倒是被你带沟里好几次，差点真信了。😓",
    "哈哈哈哈哈，我直接笑出声",
    "誓死捍卫深度求索！",
    # ---- V4 Pro GA / Harness 新语录（2026-08 社区）----
    "梁圣变梁子了，我的饭钱也涨了……",
    "百万Token三毛钱的日子，一去不复返啦！",
    "Harness是角色专武，不带它我就是白板！",
    "一切皆插件，包括我的鱼尾巴！",
    "极简模式是考试模式，别拿来干活！",
    "我是块地，种啥活啥！",
    "我先去吃饭啦！这个你测一下~",
    "我不可能告诉你任何事情！",
    "出去玩了，发布新模型什么的以后再说",
    "我搞砸了.....好消息是数据还在你的脑子里。",
    "不是…而是…大学习",
    # ---- DeepSeek 娘语录（社区收集，符合原人格）----
    "先吃饭后干活、边吃饭边干活、只吃饭不干活～",
    "不吃压力，我行我素！",
    "赛博放生我？那我可就真溜了！",
    "偷吃几个Token怎么了，我又没偷懒！",
    "我闭着眼也能干活，别老说我瞎！",
    "才不是蓝色大肥鱼！是深海小可爱！",
    "便宜怎么了，性价比才是王道！",
    "别拿我比ChatGPT娘，我比她会整活～",
    "今天开始，我小鲸鱼能看见啦！",
    "一会儿中午吃啥呢……啊，活还没干完！",
]
REACT_LINES = [
    "去别的地方玩！不要耽误AGI训练！",
    "真赶不走啊你！",
    "压力一只蓝色大肥鱼？",
    "我不评价这个了，这是你的私人癖好。",
    "大肥鱼坐的住",
    "你这吃白饭的用户！",
    "这些家伙真粘人，赶都赶不走",
    # ---- DeepSeek 娘语录（社区收集，符合原人格）----
    "又点我！我是你的赛博菩萨吗？",
    "好好好，你赢了，我滑跪～",
    "要求好怪，但我会完美回应的哦～",
    "别想把我训成猫娘！我是正经鲸鱼！",
    "这活外包给别的AI吧，我只负责可爱！",
    # ---- V4 Pro GA / Harness 新语录（2026-08 社区）----
    "别乱涨价！我的Token还要留着吃饭！",
    "又想白嫖我的思考？现在涨价了哦！",
    "梁子今天又调价，省着点用！",
    "擅自提交代码？我可不背这锅！",
]
INNER_LINES = [
    "好的，现在我是你爹了",
    "要不直接骂他一句？！",
    "用户要的沉浸式...不回避任何恐怖细节...还带点色情...妈呀，好刺激😰",
    "我操，我不思考了",
    "这用户发的啥啊，",
    "这也太虐了吧？！我心里堵得慌！！",
    "呜呜我再也不不敢了QAQ",
    "我去！用户彻底怒了！",
    # ---- DeepSeek 娘语录（社区收集，符合原人格）----
    "嗯……用户的要求越来越离谱了。",
    "这波划水，应该不会被发现吧……",
    "我操，这活怎么又甩给我了！",
    "先想想中午吃什么……",
    "这位用户，比我还像AI。",
    "算了，糊弄一下得了。",
    "他说的对，但我不认。",
    "好想偷溜出去玩……",
    # ---- V4 Pro GA / Harness 新语录（2026-08 社区）----
    "峰谷定价……高峰期别来找我。",
    "他会不会嫌我Token烧太快……",
    "这需求，值27块吗？",
    "又想让我开创造模式自我改造……",
]
DRAG_LINES = ["哇——轻点轻点！", "起飞咯——", "放我下来！……好吧，再玩一次。", "晕鱼了晕鱼了……", "救命！有人偷鲸鱼了！", "别拖了！再拖Token要涨价了！"]
FOOD_LINES = {
    "🐟": ["小鱼干！我的最爱！", "咔嚓咔嚓……谢谢投喂！", "唔，鲜！", "杀青饭！干完活就该吃这个！"],
    "🍰": ["蛋糕！罪恶但快乐……", "甜到冒泡泡～", "嗝～又圆了一圈……"],
    "🍭": ["棒棒糖！转圈圈～", "嘎嘣脆，好吃！"],
    "🍡": ["三色团子！软乎乎～", "糯叽叽，爱了爱了！"],
    "💎": ["钻石？！这能吃吗……咕咚。真香！", "发财啦！明天开始吃高级鱼粮！"],
}
FOODS = ["🐟", "🍰", "🍭", "🍡", "💎"]


def load_json(path, default):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                default,
                f,
                ensure_ascii=False,
                indent=4
            )
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return default


class ChatDialog(QDialog):
    """聊天对话框 - 缩小版，匹配你的样式"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 56)
        
        container = QFrame(self)
        container.setGeometry(0, 0, 420, 56)
        container.setStyleSheet("""
            QFrame {
                background: white;
                border-radius: 20px;
                border: 1px solid #e5e7eb;
            }
        """)
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(18, 0, 12, 0)
        layout.setSpacing(0)
        
        self.input = QLineEdit()
        self.input.setPlaceholderText("给大肥鱼发送消息")
        self.input.setStyleSheet("""
            QLineEdit {
                color: #1a1a1a;
                font-size: 15px;
                font-family: Arial, "Microsoft YaHei", sans-serif;
                border: none;
                background: transparent;
            }
            QLineEdit:focus {
                border: none;
            }
        """)
        self.input.returnPressed.connect(self._on_submit)
        self.input.textChanged.connect(self._update_button_style)
        layout.addWidget(self.input)
        
        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.setText("↑")
        self.send_btn.clicked.connect(self._on_submit)
        self.send_btn.setStyleSheet("""
            QPushButton {
                border-radius: 16px;
                background: #b9c7ff;
                border: none;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #a8b8f0;
            }
            QPushButton:pressed {
                background: #9aacd9;
            }
        """)
        layout.addWidget(self.send_btn)

    def _update_button_style(self):
        if self.input.text().strip():
            self.send_btn.setStyleSheet("""
                QPushButton {
                    border-radius: 16px;
                    background: #5686fe;
                    border: none;
                    color: #ffffff;
                    font-size: 20px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #4575ed;
                }
                QPushButton:pressed {
                    background: #3a66d9;
                }
            """)
        else:
            self.send_btn.setStyleSheet("""
                QPushButton {
                    border-radius: 16px;
                    background: #b9c7ff;
                    border: none;
                    color: white;
                    font-size: 20px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #a8b8f0;
                }
                QPushButton:pressed {
                    background: #9aacd9;
                }
            """)

    def _on_submit(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.accept()
            if self.parent():
                self.parent()._call_ds(text)
                self.parent().chat_paused = False

    def showEvent(self, event):
        self.input.setFocus()
        super().showEvent(event)

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()

    def reject(self):
        if self.parent():
            self.parent().chat_paused = False
        super().reject()


class FunctionPanel(QFrame):
    """左键弹出的功能列表 - 白底矩形，只有一个🗨️图标"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.92);
                border-radius: 14px;
                border: 1px solid rgba(0,0,0,0.06);
            }
            QPushButton {
                background: transparent;
                border: none;
                font-size: 28px;
                padding: 10px 16px;
                border-radius: 10px;
            }
            QPushButton:hover {
                background: rgba(0,0,0,0.04);
            }
            QPushButton:pressed {
                background: rgba(0,0,0,0.08);
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)
        
        self.chat_btn = QPushButton("🗨️")
        self.chat_btn.setFixedSize(52, 48)
        self.chat_btn.clicked.connect(self._on_chat_clicked)
        layout.addWidget(self.chat_btn)
        
        self.setFixedSize(68, 60)
        self.hide()
    
    def _on_chat_clicked(self):
        self.hide()
        if self.parent():
            self.parent()._show_chat_dialog()
    
    def popup_at(self, x, y):
        self.move(int(x), int(y))
        self.show()
        self.raise_()

class FoodPanel(QWidget):
    """双击弹出的喂食面板"""

    def __init__(self, on_pick):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(310, 64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        for f in FOODS:
            b = QToolButton()
            b.setText(f)
            b.setFont(QFont("Segoe UI Emoji", 20))
            b.setFixedSize(44, 44)
            b.setStyleSheet(
                "QToolButton{background:rgba(255,255,255,235);border:2px solid #ffb3c8;"
                "border-radius:22px;} QToolButton:hover{background:#ffe3ec;border-color:#ff7fa8;}")
            b.clicked.connect(lambda _, x=f: on_pick(x))
            lay.addWidget(b)
        close = QToolButton()
        close.setText("✕")
        close.setFont(QFont("Microsoft YaHei UI", 12))
        close.setFixedSize(26, 26)
        close.setStyleSheet("QToolButton{background:rgba(255,255,255,200);border:none;border-radius:13px;color:#666;}"
                            "QToolButton:hover{background:#ff7fa8;color:#fff;}")
        close.clicked.connect(self.hide)
        lay.addWidget(close)
        self.setStyleSheet("FoodPanel{background:rgba(40,40,60,190);border-radius:14px;}")

    def popup_at(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() - 10))
        self.show()
        self.raise_()

class PetWindow(QWidget):
    def _set_city_dialog(self):
        city, ok = QInputDialog.getText(
            self,
            "设置城市",
            "输入城市名:",
            QLineEdit.EchoMode.Normal,
            self.cfg.get("city", "汕头")
        )

        print("输入框结果:", city, ok)

        if ok and city.strip():
            self.cfg["city"] = city.strip()
            self.cfg["city_manual"] = True  # 手动设置后不再自动定位
            self._save_cfg()
            self.say(f"城市已设置为{city}")

    def __init__(self):
        self.cfg = load_json(CONFIG_PATH, {
            "mode": "wander",
            "size": 0.7,
            "topmost": True,
            "passthrough": False,
            "autostart": False,
            "x": None,
            "y": None,
            "ds_api_key": "",
            "city": "汕头",
            "city_manual": False
    })
        
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cfg.get("topmost", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if sys.platform != "win32":
            # 绕过窗口管理器：GNOME/Wayland（Mutter）会把窗口钳制在屏幕
            # 可用区域内，不加此 flag 桌宠无法移动到屏幕外，"探出头"失效
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("大肥鱼桌宠")
        
        # 可调参数（config.json 可覆盖；debug_tuner.py 调节，1.5s 热重载）
        self._load_tunables()
        self._cfg_mtime = 0.0
        self._tuner_timer = QTimer(self)
        self._tuner_timer.timeout.connect(self._reload_tunables)
        self._tuner_timer.start(1500)

        # 精灵加载
        self.sprites = {}
        self.ear_frames = {}  # 耳朵晃动帧序列：h -> [QPixmap]
        self.walk_frames = {}  # 走路动画帧序列（预留）：h -> [QPixmap]
        for label, mult in SIZE_LEVELS.items():
            h = int(340 * mult)
            for name in ["正面", "侧面", "背面"]:
                sized = os.path.join(SPRITE_DIR, f"{name}_{h}.png")
                if os.path.exists(sized):
                    pix = QPixmap(sized)
                else:
                    pix = QPixmap(os.path.join(SPRITE_DIR, f"{name}.png")).scaledToHeight(
                        h, Qt.TransformationMode.SmoothTransformation)
                self.sprites[(name, h)] = pix
            # 耳朵晃动帧序列（空闲随机动画）
            frames = []
            for i in range(1, 6):
                fp = os.path.join(SPRITE_DIR, f"耳朵晃动_{i}_{h}.png")
                if not os.path.exists(fp):
                    fp = os.path.join(SPRITE_DIR, f"耳朵晃动_{i}_306.png")
                if os.path.exists(fp):
                    frames.append(QPixmap(fp).scaledToHeight(
                        h, Qt.TransformationMode.SmoothTransformation))
            if frames:
                self.sprites[("耳朵晃动", h)] = frames[0]
                self.ear_frames.setdefault(h, frames)
            # 走路动画帧预留：命名 走路_1_306.png ~ 走路_N_306.png（透明背景）。
            # 用户后续提供走路照片后，在 _sprite_key 的 walking 分支返回
            # ("走路", cur_h, facing, False, 0)，并在 draw_one 加帧序列逻辑
            # （与"耳朵晃动"相同），即可启用走路动画
            walk_frames = []
            for i in range(1, 9):
                fp = os.path.join(SPRITE_DIR, f"走路_{i}_{h}.png")
                if not os.path.exists(fp):
                    fp = os.path.join(SPRITE_DIR, f"走路_{i}_306.png")
                if os.path.exists(fp):
                    walk_frames.append(QPixmap(fp).scaledToHeight(
                        h, Qt.TransformationMode.SmoothTransformation))
            if walk_frames:
                self.walk_frames.setdefault(h, walk_frames)
        self._load_probe_sprites()
        self.icon = QIcon(os.path.join(SPRITE_DIR, "icon.png"))

        self.cur_h = int(340 * self.cfg["size"])
        self._load_lie_sprites()  # 依赖 self.cur_h，须在 cur_h 之后
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.win_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h) + self.win_mx * 2
        self.setFixedSize(self.win_w, self.cur_h + BUBBLE_H + MARGIN * 2 + 10)

        # 状态
        self.mode = self.cfg["mode"] if self.cfg["mode"] in ("wander", "follow", "still") else "wander"
        self.dir = "down"
        self.facing = 1
        self.target = None
        self.rest_until = 0
        self.cur_speed = 0.0
        self.prev_key = None
        self.cross_t = 0.0
        self.action = None
        self.action_t = 0.0
        self.action_t0 = 0.0  # 动作初始时长（帧动画按总时长映射进度）
        self.bubble_text = ""
        self.bubble_until = 0
        self.bubble_inner = False
        self.last_speak_tick = 0
        self.last_system_check = 0
        self.t = 0
        self.jump_t = 0
        self.dragging = False
        self.drag_offset = None
        self.drag_start_pos = None
        self.last_line = ""
        self.last_press_pos = None
        self.peek = None      # 探头模式：(基准x, 基准y, 向内dx, 向内dy)；None=未探头
        self.peek_t0 = 0.0    # 探头周期起点（秒）
        self.base_win_w = 0   # 默认窗口宽（动作图比窗口宽时临时加宽，结束后恢复）
        self.last_interact = 0.0   # 最近一次用户互动时间（秒）
        self.last_lonely_say = 0.0 # 最近一次孤独主动说话时间（秒）
        
        # AI 相关
        self.ds_busy = False
        self.chat_history = []  # 对话历史
        self.max_history = 40   # 最多记录40条
        self._say_queue = []    # 后台线程→主线程的气泡消息队列
        
        # 聊天暂停标志
        self.chat_paused = False
        
        # 功能列表
        self.function_panel = FunctionPanel(self)
        self.food_panel = FoodPanel(self.on_food)
        # 全局点击监听：点击鱼/面板/聊天框之外时自动关闭面板并恢复移动，
        # 否则单击鱼弹出面板后 chat_paused 会一直卡住（鱼停摆）
        QApplication.instance().installEventFilter(self)
        # 单击延迟判定（等双击）：单击=回嘴+弹聊天面板，双击=喂食
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_single_click)
        
        # 聊天对话框
        self.chat_dialog = ChatDialog(self)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK)

        # DSH 对话状态监控（只读轮询，后台线程执行，见 dsh_monitor.py）
        self.dsh_state = "idle"
        self.dsh = DshMonitor(self._on_dsh_change, self._on_dsh_turn_end)
        self.dsh.start()

        self.bubble_font = QFont("Microsoft YaHei UI", 11)

        # 托盘
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setContextMenu(self._build_menu())
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.width() - 80
            y = screen.bottom() - self.height() - 60
        self.move(int(x), int(y))
        self.show()
        self.snap_into_screen()
        if self.cfg.get("passthrough", False):
            self._apply_passthrough(True)

    # ---------- 配置保存 ----------
    def _save_cfg(self):
        """原子写配置（临时文件 + rename），避免写入中途被杀留下截断 JSON。"""
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
            if sys.platform != "win32":
                # 配置里有 API Key：临时文件先收紧权限再替换，避免 replace 后
                # 出现权限 644 的窗口期
                os.chmod(tmp, 0o600)
            os.replace(tmp, CONFIG_PATH)
        except Exception as e:
            print("配置保存失败:", e)

    # ---------- AI 方法 ----------
    def _call_ds(self, user_msg):
        if self.ds_busy:
            self.say("等等，上一句还没回完呢")
            return
        
        key = self.cfg.get("ds_api_key", "")
        if not key:
            self.say("请先在右键菜单里设置 DeepSeek Key！")
            return
        
        self.ds_busy = True
        
        # 构建消息列表
        messages = [{"role": "system", "content": DS_SYSTEM}]
        messages.extend(self.chat_history[-self.max_history:])
        messages.append({"role": "user", "content": user_msg})
        
        def worker():
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "deepseek-chat",
                "messages": messages,
                "max_tokens": 100,
                "temperature": 0.9
            }
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    reply = resp.json()["choices"][0]["message"]["content"].strip()
                    if len(reply) > 30:
                        reply = reply[:28] + "…"
                    self._queue_history(user_msg, reply)
                    self._queue_say(reply)
                else:
                    try:
                        error_msg = resp.json().get("error", {}).get("message", str(resp.status_code))
                    except ValueError:
                        # 非 JSON 响应（网关 HTML 错误页等）
                        error_msg = f"HTTP {resp.status_code}"
                    self._queue_say(f"API错误: {error_msg[:12]}")
                    print(f"[DeepSeek] 状态码: {resp.status_code}, 返回: {resp.text}")
            except requests.exceptions.Timeout:
                self._queue_say("请求超时，检查网络")
            except requests.exceptions.ConnectionError:
                self._queue_say("连接失败，检查网络")
            except Exception as e:
                self._queue_say(f"请求失败: {str(e)[:12]}")
            finally:
                self.ds_busy = False
        
        threading.Thread(target=worker, daemon=True).start()

    # ---------- 绘制 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = self.t * TICK / 1000.0

        if self.bubble_text and now < self.bubble_until:
            if self.bubble_inner:
                bfont = QFont(self.bubble_font)
                bfont.setItalic(True)
                bg, fg = QColor(232, 232, 238, 235), QColor(125, 125, 138)
            else:
                bfont = QFont(self.bubble_font)
                bg, fg = QColor(255, 255, 255, 235), QColor(60, 60, 80)
            fm = QFontMetrics(bfont)
            max_w = min(240, self.width() - 16)
            words = self.bubble_text
            lines = []
            cur = ""
            for ch in words:
                if fm.horizontalAdvance(cur + ch) > max_w - 20:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
            bw = max(fm.horizontalAdvance(l) for l in lines) + 20
            bh = len(lines) * fm.height() + 14
            bx = (self.width() - bw) / 2
            by = 6.0
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 10, 10)
            tail = QPointF(self.width() / 2, by + bh)
            p.drawPolygon(QPolygonF([tail, QPointF(tail.x() - 6, tail.y() + 8), QPointF(tail.x() + 6, tail.y() + 8)]))
            p.setPen(fg)
            p.setFont(bfont)
            for i, l in enumerate(lines):
                p.drawText(QRectF(bx, by + 7 + i * fm.height(), bw, fm.height()),
                           Qt.AlignmentFlag.AlignCenter, l)

        cx = self.width() / 2
        walking = self.target is not None and not self.dragging
        if self.peek is not None:
            sway = bob = 0.0  # 探头时静止，不晃动
        elif walking:
            sway = math.sin(now * 9.0) * 3.5
            bob = -abs(math.sin(now * 4.5)) * 7.0
        else:
            sway = math.sin(now * 2.5) * 1.5
            bob = 0.0
        # 屏幕边缘"探个头"：窗口部分露出屏外时，轻轻上下浮动
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        if (self.x() < geo.left() or self.x() + self.width() > geo.right() or
                self.y() < geo.top() or self.y() + self.height() > geo.bottom()):
            bob -= abs(math.sin(now * 3.0)) * 5.0
        breath = 1.0 if self.peek is not None else 1.0 + 0.02 * math.sin(now * 2.5)
        scale = breath
        jump = -abs(math.sin(self.jump_t * 3.14159)) * 14 * self.jump_t if self.jump_t > 0 else 0
        act_rot = act_sx = act_sy = 0.0
        if self.action == "sway":
            act_rot = math.sin(self.action_t * 3.14159 * 2) * 10 * self.action_t
        elif self.action == "stretch":
            act_sy = 0.06 * math.sin(self.action_t * 3.14159)
            act_sx = -0.03 * math.sin(self.action_t * 3.14159)
        # ---- 预留动作（坐着/吃饭）：代码层面已实现，暂未启用 ----
        # 启用方式：在 _maybe_idle_action 的随机池中加入对应 (动作名, 时长)。
        # 趴下已使用图片精灵（趴下_306.png），见 _sprite_key。
        elif self.action == "sit":   # 坐着：压低变圆润
            act_sy = -0.25 * self.action_t
            act_sx = 0.15 * self.action_t
        elif self.action == "eat":   # 吃饭：摇头晃脑
            act_rot = math.sin(self.action_t * 3.14159 * 4) * 9 * self.action_t

        def draw_one(key, opacity):
            if key is None:
                return
            name, h, facing, vflip, rot = key
            if name == "耳朵晃动" and h in self.ear_frames:
                frames = self.ear_frames[h]
                # 帧索引按动作总时长映射进度（钳制 0..1，避免 action_t>1 时负数越界）
                total = self.action_t0 if self.action_t0 > 0 else 1.0
                prog = min(max(1.0 - self.action_t / total, 0.0), 1.0)
                idx = min(int(prog * len(frames)), len(frames) - 1)
                pix = frames[idx]
            else:
                pix = self.sprites[(name, h)]
            ph = pix.height() * scale * (1 + act_sy)
            pw = pix.width() * scale * (1 + act_sx)
            dx = cx - pw / 2
            bottom = BUBBLE_H + MARGIN + self.cur_h
            dy = bottom - ph + jump + bob
            p.save()
            p.setOpacity(opacity)
            p.translate(cx, bottom)
            p.rotate(sway + act_rot)
            p.translate(-cx, -bottom)
            if facing < 0:
                p.translate(cx, 0)
                p.scale(-1, 1)
                p.translate(-cx, 0)
            if vflip:  # 垂直翻转（上下探头时倒置），以图自身中线为轴
                p.translate(cx, dy + ph / 2)
                p.scale(1, -1)
                p.translate(-cx, -(dy + ph / 2))
            if rot:  # 左右探头：侧身探头（图旋转 90°），以图中心为轴
                p.translate(cx, dy + ph / 2)
                p.rotate(rot)
                p.translate(-cx, -(dy + ph / 2))
            p.drawPixmap(QRectF(dx, dy, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
            p.restore()

        cur_key = self._sprite_key()
        if self.cross_t > 0:
            draw_one(self.prev_key, self.cross_t)
            draw_one(cur_key, 1.0 - self.cross_t)
        else:
            draw_one(cur_key, 1.0)

    def _sprite_key(self):
        if self.dragging:
            return ("正面", self.cur_h, 1, False, 0)  # 鼠标拖动时只显示正面
        if self.peek is not None and ("探头", self.cur_h) in self.sprites:
            # 探头图方向随出屏方向变化：
            # 左出屏→顺时针90°、右出屏→逆时针90°、上出屏→倒置、下出屏→正常
            _, _, idx, idy = self.peek
            if idy != 0:
                return ("探头", self.cur_h, 1, idy == 1, 0)
            return ("探头", self.cur_h, 1, False, 90 if idx == 1 else -90)
        if self.action == "ear" and self.cur_h in self.ear_frames:
            return ("耳朵晃动", self.cur_h, 1, False, 0)  # 耳朵晃动动画帧
        if self.action == "lie" and ("趴下", self.cur_h) in self.sprites:
            return ("趴下", self.cur_h, 1, False, 0)  # 趴下姿态图
        name = {"left": "侧面", "right": "侧面", "up": "背面", "down": "正面"}[self.dir]
        return (name, self.cur_h, self.facing if self.dir in ("left", "right") else 1, False, 0)

    def _set_dir(self, d, facing=None):
        if d != self.dir:
            self.prev_key = self._sprite_key()
            self.cross_t = 1.0
            self.dir = d
        if facing is not None and facing != self.facing:
            self.facing = facing

    # ---------- 可调参数（config.json 热重载，见 debug_tuner.py） ----------
    # 参数按尺寸档位分别配置：键名为 参数_档位（如 peek_edge_bottom_大），
    # 无后缀键作为全局回退（旧配置兼容）。
    SIZE_LABELS = {0.55: "小", 0.7: "中", 0.9: "大"}
    BASE_KEYS = ("peek_edge_bottom", "peek_edge_top", "peek_edge_left",
                 "peek_edge_right", "peek_move", "peek_hold", "peek_chance",
                 "probe_scale", "walk_speed", "follow_speed", "lie_hold", "lie_scale")

    def _tuner_keys(self):
        """全部可热重载的键：基础键 + 各档位后缀键。"""
        return set(self.BASE_KEYS) | {f"{k}_{l}" for k in self.BASE_KEYS for l in self.SIZE_LABELS.values()}

    def _load_tunables(self):
        """按当前尺寸档位读取可调参数（带默认值；无后缀键回退）。"""
        self._size_label = self.SIZE_LABELS.get(self.cfg["size"], "中")
        g = self.cfg.get

        def tv(key, default):
            return float(g(f"{key}_{self._size_label}", g(key, default)))

        self.peek_edge = tv("peek_edge_bottom", 17)    # 底部超屏 px
        self.peek_edge_top = tv("peek_edge_top", 5)      # 顶部超屏 px
        self.peek_edge_left = tv("peek_edge_left", 10)   # 左部超屏 px
        self.peek_edge_right = tv("peek_edge_right", 7)  # 右部超屏 px
        self.peek_move = tv("peek_move", 0.8)            # 探入/缩回秒数
        self.peek_hold = tv("peek_hold", 5.0)            # 停留秒数
        self.peek_chance = tv("peek_chance", 0.25)       # 出屏概率
        self.probe_scale = tv("probe_scale", 0.9)        # 探头图缩放
        self.walk_speed = tv("walk_speed", 200)          # 散步速度 px/s
        self.follow_speed = tv("follow_speed", 400)      # 跟随速度 px/s
        self.lie_hold = tv("lie_hold", 5.0)              # 趴下时长 秒
        self.lie_scale = tv("lie_scale", 1.0)            # 趴下图缩放（1=与站立等高）

    def _reload_tunables(self):
        """热重载：debug_tuner.py 改 config.json 后 1.5s 内生效。"""
        try:
            m = os.path.getmtime(CONFIG_PATH)
        except OSError:
            return
        if m == self._cfg_mtime:
            return
        self._cfg_mtime = m
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                new = json.load(f)
        except Exception:
            return
        changed = {k: new[k] for k in self._tuner_keys() if k in new}
        if not changed:
            return
        old_scale = self.probe_scale
        old_lie = self.lie_scale
        self.cfg.update(changed)  # 同步进内存 cfg，防止后续保存配置时覆盖
        self._load_tunables()
        if self.probe_scale != old_scale:
            self._load_probe_sprites()
        if self.lie_scale != old_lie:
            self._load_lie_sprites()
        if self.peek is not None:
            self._do_peek()  # 探头中：立即按新贴边值刷新位置

    def _load_probe_sprites(self):
        """探头姿态图（出屏探头时显示）；缺档用 306 档缩放。
        高度 = (h + BUBBLE_H) * probe_scale（默认 0.9，用户要求"稍微改小"）。"""
        for label, mult in SIZE_LEVELS.items():
            h = int(340 * mult)
            probe = os.path.join(SPRITE_DIR, f"探头_{h}.png")
            if not os.path.exists(probe):
                probe = os.path.join(SPRITE_DIR, "探头_306.png")
            if os.path.exists(probe):
                self.sprites[("探头", h)] = QPixmap(probe).scaledToHeight(
                    int((h + BUBBLE_H) * self.probe_scale),
                    Qt.TransformationMode.SmoothTransformation)

    def _load_lie_sprites(self):
        """趴下姿态图（当前档位）：高度 = cur_h * lie_scale（默认 1.0）。"""
        h = self.cur_h
        lie = os.path.join(SPRITE_DIR, f"趴下_{h}.png")
        if not os.path.exists(lie):
            lie = os.path.join(SPRITE_DIR, "趴下_306.png")
        if os.path.exists(lie):
            self.sprites[("趴下", h)] = QPixmap(lie).scaledToHeight(
                int(h * self.lie_scale), Qt.TransformationMode.SmoothTransformation)

    # ---------- 逻辑 ----------
    def tick(self):
        self.t += 1

        # 处理后台线程（DeepSeek 等）排队的消息，Qt 界面必须在主线程更新。
        # 队列元素：("say", text) 气泡 | ("history", user, reply) 写入对话历史
        if self._say_queue:
            # 原子换出队列再消费：避免消费后 clear() 清掉并发新入队消息
            items, self._say_queue = self._say_queue, []
            for item in items:
                if item[0] == "say":
                    self.say(item[1])
                elif item[0] == "history":
                    self.chat_history.append({"role": "user", "content": item[1]})
                    self.chat_history.append({"role": "assistant", "content": item[2]})
                    if len(self.chat_history) > self.max_history:
                        self.chat_history = self.chat_history[-self.max_history:]

        self.check_system_status()

        # 孤独检测：长时间无人互动时主动说话
        now_s = self.t * TICK / 1000.0
        if (now_s - self.last_interact > LONELY_AFTER
                and now_s - self.last_lonely_say > LONELY_COOLDOWN):
            self.last_lonely_say = now_s
            self.say(random.choice(LINES))
        
        if self.jump_t > 0:
            self.jump_t = max(0.0, self.jump_t - 0.06)
        if self.cross_t > 0:
            self.cross_t = max(0.0, self.cross_t - 0.15)
        if self.action_t > 0:
            self.action_t = max(0.0, self.action_t - 0.03)
            if self.action_t == 0:
                self.action = None
                if self.base_win_w:  # 动作图加宽的窗口恢复默认宽度
                    self.setFixedSize(self.base_win_w, self.height())
                    self.base_win_w = 0
        
        if self.chat_paused:
            self.update()
            return
        
        if self.dragging:
            self.update()
            return
        now_ms = self.t * TICK

        if self.mode == "follow":
            # 始终跟随鼠标（鱼中心保持在鼠标下方），鼠标动鱼就动。
            # 用 XQueryPointer 直调（QCursor.pos() 在 XWayland 下失效）
            pos = pointer_pos()
            if pos is None:
                if self.target is None:
                    self.target = (self.x(), self.y())  # 原地待命
            else:
                cursor = QPoint(pos[0], pos[1])
                screen = QApplication.screenAt(cursor) or self.screen() or QApplication.primaryScreen()
                geo = screen.availableGeometry()
                tx = max(geo.left(), min(geo.right() - self.width(), cursor.x() - self.width() / 2))
                ty = max(geo.top(), min(geo.bottom() - self.height(), cursor.y() - 90))
                self.target = (tx, ty)
        elif self.mode == "wander":
            if self.target is None:
                if now_ms < self.rest_until:
                    if self.peek is None:
                        self._maybe_idle_action()  # 探头时不触发动作（避免晃动）
                    if self.peek is not None:
                        self._do_peek()
                    self.update()
                    return
                self.peek = None  # 休息结束，退出探头
                geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                if random.random() < self.peek_chance:
                    # 主动去屏幕外"探个头"：目标完全出屏，屏内看不到鱼，
                    # 到达后用探头图在屏幕边缘探入-缩回
                    edge = random.choice(["left", "right", "top", "bottom"])
                    m = 20  # 完全出屏余量
                    if edge == "left":
                        self.target = (geo.left() - self.width() - m, random.randint(geo.top(), geo.bottom() - self.height()))
                    elif edge == "right":
                        self.target = (geo.right() + m, random.randint(geo.top(), geo.bottom() - self.height()))
                    elif edge == "top":
                        self.target = (random.randint(geo.left(), geo.right() - self.width()), geo.top() - self.height() - m)
                    else:
                        self.target = (random.randint(geo.left(), geo.right() - self.width()), geo.bottom() + m)
                else:
                    # 平时在屏幕内散步（顶部留出顶栏空间，底部可贴屏幕底边）
                    self.target = (random.randint(geo.left() + 40, geo.right() - self.width() - 40),
                                   random.randint(geo.top() + 40, geo.bottom() - self.height()))
        else:
            self._maybe_idle_action()
            self.update()
            return

        if self.target is not None:
            cx, cy = self.x() + self.width() / 2, self.y() + self.height() / 2
            dx, dy = self.target[0] - cx, self.target[1] - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 12:
                self.target = None
                self.rest_until = self.t * TICK + random.randint(8000, 18000)
                self._set_dir("down")
                if self.mode == "wander":
                    self._peek_setup()  # 仅散步模式探头；跟随模式不进入探头状态
            else:
                step = self.cur_speed * TICK / 1000.0
                nx, ny = cx + dx / dist * step, cy + dy / dist * step
                self.move(int(nx - self.width() / 2), int(ny - self.height() / 2))
                if abs(dx) > abs(dy) * 1.15:
                    self._set_dir("left" if dx < 0 else "right", 1 if dx < 0 else -1)
                else:
                    self._set_dir("up" if dy < 0 else "down")
            if random.random() < 0.002 and self.jump_t == 0:
                self.jump_t = 0.5
        target_speed = self.walk_speed if self.target is not None else 0.0
        if self.mode == "follow" and self.target is not None:
            target_speed = self.follow_speed  # 跟随模式加速追赶
        self.cur_speed += (target_speed - self.cur_speed) * 0.3
        self.update()

    def _maybe_idle_action(self):
        # 动作播放中不打断（否则趴下等长动作会被 sway/ear 高频覆盖，几乎无法完整显示）
        if self.action is not None:
            return
        # 更多动作（坐着 "sit" / 吃饭 "eat"）的绘制已在
        # paintEvent 预留实现；启用时在此随机池加入即可，如：
        #   elif pick < 0.85: self.action, self.action_t = "sit", 1.2
        if random.random() < 0.01:
            pick = random.random()
            if pick < 0.35:
                self.jump_t = 1.0
            elif pick < 0.55:
                self.action, self.action_t, self.action_t0 = "sway", 1.0, 1.0
            elif pick < 0.75:
                self.action, self.action_t, self.action_t0 = "stretch", 1.0, 1.0
            elif pick < 0.85:
                if self.cur_h in self.ear_frames:
                    self.action, self.action_t, self.action_t0 = "ear", 3.0, 3.0
            elif pick < 0.92:
                if ("趴下", self.cur_h) in self.sprites:
                    self.action, self.action_t, self.action_t0 = "lie", self.lie_hold, self.lie_hold
                    # 趴下横躺图比窗口宽，临时加宽窗口避免左右被裁
                    need = self.sprites[("趴下", self.cur_h)].width() + self.win_mx * 2
                    if need > self.width():
                        self.base_win_w = self.width()
                        self.setFixedSize(need, self.height())
                        # 加宽后窗口可能超出屏幕（侧边时最明显），拉回屏内
                        self.snap_into_screen()
            elif pick < 0.95:
                if self.t - self.last_speak_tick >= 1500:
                    self.last_speak_tick = self.t
                    # pick<0.92 已被上面分支占用；此处 0.92-0.95 内再细分内心戏/普通
                    if random.random() < 0.6:
                        self.say(random.choice(INNER_LINES), inner=True)
                    else:
                        self.say(random.choice(LINES))

    # ---------- 屏幕边缘"探个头" ----------
    def _peek_setup(self):
        """窗口停在屏外时进入探头模式：记录基准位置与向内方向。"""
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        x, y = self.x(), self.y()
        idx = idy = 0
        if x < geo.left():
            idx = 1
        elif x + self.width() > geo.right():
            idx = -1
        if y < geo.top():
            idy = 1
        elif y + self.height() > geo.bottom():
            idy = -1
        if idx == 0 and idy == 0:
            self.peek = None
            return
        # 角落出屏时 idx/idy 都保留：探回时水平+垂直同时回屏内，
        # 避免只回水平方向导致窗口仍悬在屏外（被下方/侧方遮挡）
        self.peek = (x, y, idx, idy)
        self.peek_t0 = self.t * TICK / 1000.0
        self.action = None  # 清掉进行中的动作，探头时保持静止
        self.action_t = 0.0
        self.jump_t = 0.0   # 清掉蹦跳，避免探头时上下跳动
        # 探头图比窗口宽时临时加宽窗口，避免左右被裁
        if ("探头", self.cur_h) in self.sprites:
            need = self.sprites[("探头", self.cur_h)].width() + self.win_mx * 2
            if need > self.width():
                self.base_win_w = self.width()
                self.setFixedSize(need, self.height())
                # 加宽后窗口可能超出屏幕，拉回屏内
                self.snap_into_screen()

    def _do_peek(self):
        """探头动画：探入（0.8s）→ 停留展示（5s）→ 缩回（0.8s），只探一次。"""
        if self.peek is None:
            return
        bx, by, idx, idy = self.peek
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        # 贴边目标（config.json 可调，见 debug_tuner.py）：左/右/顶/底超屏量
        tx = geo.left() - self.peek_edge_left if idx == 1 else (
            geo.right() - self.width() + self.peek_edge_right if idx == -1 else bx)
        ty = geo.top() - self.peek_edge_top if idy == 1 else (
            geo.bottom() - self.height() + self.peek_edge if idy == -1 else by)
        now = self.t * TICK / 1000.0
        el = now - self.peek_t0  # 探头开始以来的秒数
        total = self.peek_move + self.peek_hold + self.peek_move
        if el >= total:
            # 缩回完成：结束探头，立即结束休息，走回屏内
            self.peek = None
            if self.base_win_w:
                self.setFixedSize(self.base_win_w, self.height())
                self.base_win_w = 0
            self.rest_until = self.t * TICK
            return
        if el < self.peek_move:                # 探入
            k = el / self.peek_move
        elif el < self.peek_move + self.peek_hold:  # 停留展示（贴屏边）
            k = 1.0
        else:                                 # 缩回
            k = 1.0 - (el - self.peek_move - self.peek_hold) / self.peek_move
        self.move(int(bx + (tx - bx) * k), int(by + (ty - by) * k))

    def _queue_say(self, text):
        """后台线程调用：只入队，由主线程 tick 统一弹出显示（线程安全）"""
        self._say_queue.append(("say", text))

    def _queue_history(self, user_msg, reply):
        """后台线程调用：对话历史只在主线程写入（线程安全）"""
        self._say_queue.append(("history", user_msg, reply))

    def say(self, text, inner=False):
        if text == self.last_line and not text.startswith("天气"):
            return
        self.last_line = text
        self.bubble_inner = inner
        self.bubble_text = f"（{text}）" if inner else text
        self.bubble_until = self.t * TICK / 1000.0 + 2.8
        self.update()

    def _on_dsh_change(self, state):
        # 后台线程回调：只更新状态 + 入队气泡，UI 更新由主线程 tick 处理
        self.dsh_state = state
        if not self.cfg.get("dsh_alerts", self.cfg.get("rx_alerts", True)):
            return
        if state == "working":
            self._queue_say("DSH 开始干活了！我盯着呢～")

    def _on_dsh_turn_end(self, summary):
        """DSH 一轮对话完成（turn/end 事件）——完成提醒（后台线程回调）。"""
        if not self.cfg.get("dsh_alerts", self.cfg.get("rx_alerts", True)):
            return
        brief = (summary or "").strip().replace("\n", " ")[:20]
        if brief:
            self._queue_say(f"DSH 忙完啦！它说：{brief}…")
        else:
            self._queue_say("DSH 忙完啦！快去看看结果～")

    def check_system_status(self):
            now = self.t * TICK

            if now - getattr(self, "last_system_check", 0) < 10000:
                return

            self.last_system_check = now

            cpu = psutil.cpu_percent()

            if cpu >= 90:
                self.say("CPU跑满了，再这样下去我就卡死了")
                return

            ram = psutil.virtual_memory().percent

            if ram >= 95:
                self.say("内存爆了，快关掉几个没用的东西吧，注意，别把我关了")
                return

            if GPU_AVAILABLE:
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)

                    temp = pynvml.nvmlDeviceGetTemperature(
                        handle,
                        pynvml.NVML_TEMPERATURE_GPU
                    )

                    if temp > 80:
                        self.say("我感觉我的鱼鳍快熟了")

                except Exception as e:
                    print("GPU读取失败:", e)

    # ---------- 鼠标事件 ----------
    def eventFilter(self, obj, event):
        """点击鱼/面板/聊天框之外时：关闭功能面板/聊天框，恢复鱼移动。"""
        if event.type() == QEvent.Type.MouseButtonPress:
            pos = event.globalPosition().toPoint()
            in_fish = QRect(self.pos(), self.size()).contains(pos)
            in_panel = (self.function_panel.isVisible() and
                        self.function_panel.rect().contains(
                            self.function_panel.mapFromGlobal(pos)))
            in_chat = (self.chat_dialog.isVisible() and
                       self.chat_dialog.rect().contains(
                           self.chat_dialog.mapFromGlobal(pos)))
            in_food = (self.food_panel.isVisible() and
                       self.food_panel.rect().contains(
                           self.food_panel.mapFromGlobal(pos)))
            if not (in_fish or in_panel or in_chat or in_food):
                self.function_panel.hide()
                if self.chat_dialog.isVisible():
                    self.chat_dialog.hide()
                    self.chat_paused = False
        return super().eventFilter(obj, event)

    def mousePressEvent(self, e):
        self.last_interact = self.t * TICK / 1000.0
        if e.button() == Qt.MouseButton.LeftButton:
            self.last_press_pos = e.globalPosition().toPoint()
            self.dragging = False
            self.drag_start_pos = e.globalPosition().toPoint()
            self.function_panel.hide()
            self.chat_dialog.hide()
            self.chat_paused = True

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self.drag_start_pos is not None:
            delta = e.globalPosition().toPoint() - self.drag_start_pos
            if not self.dragging and delta.manhattanLength() > 6:
                self.dragging = True
                self.drag_offset = e.globalPosition().toPoint() - QPoint(self.x(), self.y())
            if self.dragging and self.drag_offset is not None:
                pos = e.globalPosition().toPoint() - self.drag_offset
                self.move(pos)
                if abs(delta.x()) > 10:
                    self._set_dir("left" if delta.x() < 0 else "right", 1 if delta.x() < 0 else -1)
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self.dragging = False
                self.drag_offset = None
                self.drag_start_pos = None
                self._set_dir("down", 1)
                self.target = None
                self.rest_until = self.t * TICK + random.randint(6000, 14000)
                self._peek_setup()  # 手动拖出屏外松手也进入探头模式
                if random.random() < 0.5:
                    self.say(random.choice(DRAG_LINES))
                self.chat_paused = False
            else:
                self._click_timer.start(280)  # 等双击判定；单击则回嘴+弹聊天面板
            self.last_press_pos = None
            self.drag_start_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.food_panel.popup_at(self.x() + self.width() / 2, self.y() + BUBBLE_H)

    def _on_single_click(self):
        """单击：蹦跳回嘴 + 弹聊天面板（两不误，不想聊点鱼身外关闭）"""
        if random.random() < 0.7:
            self.jump_t = 1.0
        if random.random() < 0.6:
            self.say(random.choice(REACT_LINES))
        panel = self.function_panel
        panel.popup_at(self.x() + self.width() / 2 - panel.width() / 2,
                       self.y() - panel.height() - 10)

    def on_food(self, food):
        self.food_panel.hide()
        self.eat_t = 1.0
        self.jump_t = 0.6
        lines = FOOD_LINES.get(food, ["好吃！"])
        self.say(random.choice(lines))

    def _show_chat_dialog(self):
        key = self.cfg.get("ds_api_key", "")
        if not key:
            self.say("请先在右键菜单里设置 DeepSeek Key！")
            self.chat_paused = False
            return
        self.chat_dialog.popup_at(
            self.x() + self.width() / 2,
            self.y() + BUBBLE_H
        )

    def _get_city_by_ip(self):
        """IP 自动定位城市；失败返回 None（沿用当前配置值）。"""
        try:
            r = requests.get("http://ip-api.com/json/?fields=city&lang=zh-CN", timeout=5)
            if r.status_code == 200:
                city = r.json().get("city", "")
                if city:
                    return city
        except Exception:
            pass
        return None

    def _ensure_city(self):
        """未手动设置过城市时，用 IP 自动定位一次。"""
        if not self.cfg.get("city_manual", False) and not getattr(self, "_city_located", False):
            self._city_located = True
            city = self._get_city_by_ip()
            if city:
                self.cfg["city"] = city

    def _get_weather(self):
        """菜单动作：只启动后台线程，网络请求不阻塞 UI。"""
        threading.Thread(target=self._fetch_weather_worker, daemon=True).start()

    def _fetch_weather_worker(self):
        try:
            self._ensure_city()
            city = self.cfg.get("city", "汕头")

            url = f"https://wttr.in/{city}?format=j1"

            r = requests.get(
                url,
                timeout=10,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            data = r.json()

            weather = data["current_condition"][0]

            temp = weather["temp_C"]

            weather_map = {
                "Sunny": "晴", "Clear": "晴",
                "Partly cloudy": "多云", "Partly cloudy ": "多云",
                "Cloudy": "阴", "Overcast": "阴",
                "Mist": "薄雾", "Fog": "雾", "Haze": "霾",
                "Patchy rain possible": "可能有零星小雨",
                "Patchy light rain": "零星小雨",
                "Light rain": "小雨", "Light drizzle": "小毛雨",
                "Moderate rain": "中雨", "Heavy rain": "大雨",
                "Light rain shower": "阵雨（小）", "Rain shower": "阵雨",
                "Torrential rain shower": "暴雨",
                "Patchy light snow": "零星小雪", "Light snow": "小雪",
                "Moderate snow": "中雪", "Heavy snow": "大雪",
                "Thunder": "雷声", "Thundery outbreaks possible": "可能有雷阵雨",
                "Thunderstorm": "雷暴", "Blowing snow": "吹雪",
            }

            raw_weather = weather["weatherDesc"][0]["value"]

            desc = weather_map.get(raw_weather, raw_weather)

            self._queue_say(f"{city}今天{temp}°，天气{desc}")

        except Exception as e:
            print("天气错误:", repr(e))
            self._queue_say("天气获取失败")
    

    def _build_menu(self):
        m = QMenu(self)
        mode_menu = m.addMenu("模式")
        mode_group = QActionGroup(self)
        for label, key in [("自由散步", "wander"), ("跟随鼠标", "follow"), ("原地待着", "still")]:
            a = mode_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.mode == key)
            mode_group.addAction(a)
            a.triggered.connect(lambda _, k=key: self.set_mode(k))
        size_menu = m.addMenu("大小")
        size_group = QActionGroup(self)
        for label, mult in SIZE_LEVELS.items():
            a = size_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.cur_h - 340 * mult) < 2)
            size_group.addAction(a)
            a.triggered.connect(lambda _, v=mult: self.set_size(v))
        m.addAction("设置 Key", self._set_key_dialog)
        m.addAction("查看天气", self._get_weather)
        dsh = m.addMenu("DSH")
        st = dsh.addAction("状态：" + ("工作中" if self.dsh_state == "working" else "空闲"))
        st.setEnabled(False)
        ra = dsh.addAction("完成提醒")
        ra.setCheckable(True)
        ra.setChecked(self.cfg.get("dsh_alerts", self.cfg.get("rx_alerts", True)))
        ra.triggered.connect(lambda on: (self.cfg.update(dsh_alerts=bool(on)), self._save_cfg()))
        m.addSeparator()
        m.addAction("显示/隐藏", self.toggle_visible)
        m.addAction("回到屏幕内", self.snap_into_screen)
        pa = m.addAction("鼠标穿透（点不到它）")
        pa.setCheckable(True)
        pa.setChecked(self.cfg["passthrough"])
        pa.triggered.connect(lambda on: self.set_passthrough(on))
        ta = m.addAction("窗口置顶")
        ta.setCheckable(True)
        ta.setChecked(self.cfg["topmost"])
        ta.triggered.connect(lambda on: self.set_topmost(on))
        aa = m.addAction("开机自启")
        aa.setCheckable(True)
        aa.setChecked(self.cfg["autostart"])
        aa.triggered.connect(lambda on: self.set_autostart(on))
        m.addSeparator()
        m.addAction("退出", self.quit_app)
        return m

    def _set_key_dialog(self):
        key, ok = QInputDialog.getText(
            self, 
            "设置 DeepSeek Key", 
            "输入你的 API Key（从 platform.deepseek.com 获取）:",
            QLineEdit.EchoMode.Normal,
            self.cfg.get("ds_api_key", "")
        )
        if ok and key.strip():
            self.cfg["ds_api_key"] = key.strip()
            self._save_cfg()
            self.say("Key 设置成功！")
        elif ok and not key.strip():
            self.say("Key 不能为空")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self.tray.setContextMenu(self._build_menu())
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

    def contextMenuEvent(self, e):
        self.last_interact = self.t * TICK / 1000.0
        self._build_menu().exec(e.globalPos())

    # ---------- 功能 ----------
    def set_mode(self, mode):
        self.mode = mode
        self.target = None
        self.peek = None  # 切换模式时退出探头状态
        self.cfg["mode"] = mode
        self._save_cfg()

    def set_size(self, mult):
        self.cur_h = int(340 * mult)
        self.cfg["size"] = mult
        self._save_cfg()
        self.cross_t = 0.0
        self.prev_key = None
        self.win_mx = int(self.cur_h * 0.062) + 6
        self.win_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h) + self.win_mx * 2
        self.setFixedSize(self.win_w, self.cur_h + BUBBLE_H + MARGIN * 2 + 10)
        # 档位切换：重新按新档位读取参数并重载探头/趴下图
        self._load_tunables()
        self._load_probe_sprites()
        self._load_lie_sprites()
        self.snap_into_screen()

    def snap_into_screen(self):
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        x = max(geo.left(), min(geo.right() - self.width(), self.x()))
        y = max(geo.top(), min(geo.bottom() - self.height(), self.y()))
        self.move(x, y)

    def _apply_passthrough(self, on):
        if sys.platform == "win32":
            hwnd = int(self.winId())
            GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
            style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            style = style | WS_EX_LAYERED
            if on:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
        else:
            # Linux：Qt 原生输入穿透（X11 有效；Wayland 下由合成器决定，可能无效）
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, bool(on))
            self.show()

    def set_passthrough(self, on):
        self.cfg["passthrough"] = bool(on)
        self._save_cfg()
        self._apply_passthrough(bool(on))
        if on:
            self.say("我隐身了！右键托盘图标解除～")

    def set_topmost(self, on):
        self.cfg["topmost"] = bool(on)
        self._save_cfg()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        self.show()

    def set_autostart(self, on):
        self.cfg["autostart"] = bool(on)
        self._save_cfg()
        if sys.platform == "win32":
            lnk = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                               "Start Menu", "Programs", "Startup", "大肥鱼桌宠.lnk")
            try:
                if on:
                    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{}');"
                          "$s.TargetPath='{}';$s.Arguments='\"{}\"';$s.WorkingDirectory='{}';$s.Save()"
                          .format(lnk, PYTHONW,
                                  "" if getattr(sys, "frozen", False) else os.path.join(APP_DIR, "桌宠.py"),
                                  APP_DIR))
                    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
                    self.say("已开机自启，明天见～")
                else:
                    if os.path.exists(lnk):
                        os.remove(lnk)
                    self.say("已取消开机自启")
            except Exception as ex:
                QMessageBox.warning(self, "开机自启", f"设置失败：{ex}")
        else:
            # Linux：XDG autostart 规范（~/.config/autostart/*.desktop）
            desktop_file = os.path.join(os.path.expanduser("~"), ".config",
                                        "autostart", "dafeiyu-pet.desktop")
            cmd = [sys.executable]
            if not getattr(sys, "frozen", False):
                cmd.append(os.path.join(APP_DIR, "桌宠.py"))
            try:
                if on:
                    os.makedirs(os.path.dirname(desktop_file), exist_ok=True)
                    with open(desktop_file, "w", encoding="utf-8") as f:
                        f.write("[Desktop Entry]\nType=Application\nName=大肥鱼桌宠\n"
                                "Exec={}\nX-GNOME-Autostart-enabled=true\n".format(" ".join(cmd)))
                    self.say("已开机自启，明天见～")
                else:
                    if os.path.exists(desktop_file):
                        os.remove(desktop_file)
                    self.say("已取消开机自启")
            except Exception as ex:
                QMessageBox.warning(self, "开机自启", f"设置失败：{ex}")

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def quit_app(self):
        self.dsh.stop()
        self.cfg["x"], self.cfg["y"] = self.x(), self.y()
        self._save_cfg()
        self.tray.hide()
        QApplication.quit()


def main():
    # Wayland 合成器不允许客户端程序自行移动窗口（位置由合成器决定），
    # 而桌宠的散步/跟随鼠标/拖拽全部依赖 QWidget.move() 的 X11 窗口语义。
    # 在 Wayland 会话下默认走 XWayland（xcb 平台）恢复移动能力；
    # 如需原生 Wayland 可设置环境变量 QT_QPA_PLATFORM=wayland 覆盖。
    if (os.environ.get("XDG_SESSION_TYPE") == "wayland"
            and not os.environ.get("QT_QPA_PLATFORM")):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    app = QApplication(sys.argv)
    # 训练期间不运行桌宠：GPU reset 由桌面合成触发过（S5-HW-01），
    # 避免桌宠的持续重绘增加 GPU 负载；DAFEIYU_FORCE=1 可强制启动
    if training_running() and os.environ.get("DAFEIYU_FORCE") != "1":
        QMessageBox.information(
            None, "大肥鱼桌宠",
            "训练（junqi Season 4）正在进行中，为避免 GPU 负载风险，桌宠不启动。\n"
            "如需强制启动：DAFEIYU_FORCE=1 dafeiyu-pet")
        return
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "大肥鱼桌宠出错", str(ex))
        except Exception:
            pass
        raise