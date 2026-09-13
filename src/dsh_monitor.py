# -*- coding: utf-8 -*-
"""
DeepSeek Harness (DSH) 对话状态监控 —— 只读轮询 DSH 会话事件日志。

数据源：~/.dsh/sessions/**/session.jsonl.zstd（zstd 压缩的仅追加事件流）。
完成信号：事件 "turn/end"（含 seq）——一轮对话完成（整轮完成信号，
与 DSH 桌面端 balance.js 的 checkTurnEnd 判定一致）。
开始信号：事件 "user/message"——用户新消息（新轮开始）。

程序不修改任何 DSH 文件，只读轮询；状态机只报告转换（idle<->working）。

解压+解析在后台线程执行（大文件全量解压可达数百毫秒以上，放在
Qt 主线程会卡住桌宠）；结果按 (mtime, size) 缓存，文件没变就不重解压。
回调（on_change / on_turn_end）在后台线程触发——涉及 UI 的操作
需自行抛回主线程（见 桌宠.py 的 _say_queue）。
"""
import glob
import json
import os
import threading
import time

try:
    import zstandard
except ImportError:
    zstandard = None

DSH_SESSIONS = os.path.join(os.path.expanduser("~"), ".dsh", "sessions")
CHECK_EVERY = 3.0   # 秒：轮询间隔
MAX_DECOMPRESS = 512 * 1024 * 1024  # 解压上限


class DshMonitor:
    """监控 DSH 活跃会话的对话状态。

    on_change(state) 回调：state 为 "idle" / "working"，仅在状态转换时触发
    （首次 poll 静默建立基线，不回调）。on_turn_end(summary) 在对话完成时触发。

    start() 启动后台轮询线程（stop() 停止）；poll() 也可手动同步调用。
    """

    def __init__(self, on_change, on_turn_end=None):
        self.on_change = on_change
        self.on_turn_end = on_turn_end
        self.state = None           # None | "idle" | "working"
        self.last_seq = 0           # 已见的最大 turn/end seq
        self.last_user_seq = 0      # 已见的最大 user/message seq
        self.last_summary = ""      # 最近一次完成轮的回复摘要
        self.baseline = False       # 首次扫描后置 True（基线不触发回调）
        self._cache = {}            # file -> (mtime, size, events)
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ---------- 后台轮询 ----------

    def start(self):
        """启动后台轮询线程（daemon）。"""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dsh-monitor")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=CHECK_EVERY + 1)
            self._thread = None

    def _run(self):
        while not self._stop.wait(CHECK_EVERY):
            try:
                self.poll()
            except Exception:
                pass  # 单次失败不影响后续轮询

    # ---------- 状态机 ----------

    def poll(self):
        """检查一次；返回当前状态字符串。"""
        latest, mtime = self._latest_session()
        if latest is None:
            return self.state or "idle"
        try:
            events = self._read_events(latest, mtime)
        except Exception:
            return self.state or "idle"

        # 状态是"闩锁"式的：user/message 进入 working，turn/end 回到 idle。
        # 早期实现每轮把 working 重置为 False，且只在"本轮读到新的 user/message"
        # 时才置 True —— 用户消息之后的第一轮就误判为空闲，于是整个工作期间
        # 桌宠一直显示"DSH 空闲"（已用真实会话复现：连续 6 次轮询全为 idle）。
        changed = False
        for ev in events:
            t = ev.get("type")
            seq = ev.get("seq") or 0
            if t == "user/message":
                if seq > self.last_user_seq:
                    self.last_user_seq = seq
                    if self.state != "working":
                        self.state = "working"
                        changed = True
            elif t == "turn/end":
                if seq > self.last_seq:
                    self.last_seq = seq
                    if self.state != "idle":
                        self.state = "idle"
                        changed = True
                    if self.baseline and self.on_turn_end is not None:
                        self.on_turn_end(self.last_summary)
            elif t == "assistant/message":
                content = ((ev.get("data") or {}).get("message") or {}).get("content") or []
                text = "".join(c.get("text", "") for c in content
                               if isinstance(c, dict) and c.get("type") == "text").strip()
                if text:
                    self.last_summary = text

        if not self.baseline:
            self.baseline = True
            self.state = self.state or "idle"
        elif changed and self.on_change is not None:
            self.on_change(self.state)
        return self.state or "idle"

    # dsh 0.1.5+ 的会话文件是 session.v3.jsonl.zstd；早期版本用 session.jsonl.zstd。
    # 只 glob 旧名字会读到过期的空文件（本机实测：读到 8 月的 legacy 文件、只有 1 个
    # session 事件）→ 状态永远判定为 idle，桌宠一直显示"DSH 空闲"。
    _SESSION_NAMES = ("session.v3.jsonl.zstd", "session.jsonl.zstd")

    def _latest_session(self):
        """最新（mtime 最大）的会话文件；返回 (路径, mtime) 或 (None, 0)。

        优先新格式：只要存在 v3 文件就只在 v3 里挑最新的；都没有才回退旧格式。
        """
        for name in self._SESSION_NAMES:
            best = None
            try:
                for f in glob.glob(os.path.join(DSH_SESSIONS, "*", "*", name)):
                    try:
                        m = os.path.getmtime(f)
                    except OSError:
                        continue
                    if os.path.getsize(f) > 100 and (best is None or m > best[1]):
                        best = (f, m)
            except Exception:
                best = None
            if best:
                return best
        return (None, 0)

    def _read_events(self, path, mtime=None):
        """解压并解析会话文件，返回事件列表；(mtime, size) 未变时直接用缓存。"""
        if zstandard is None:
            return []
        st = os.stat(path)
        with self._lock:
            c = self._cache.get(path)
            if c and c[0] == st.st_mtime and c[1] == st.st_size:
                return c[2]
        # 必须用"流式跨帧"解压：dsh 的会话文件是多帧追加写入的（本机实测 4.3MB
        # / 4932 行），而一次性 decompress() 只解出第一帧 —— 于是只拿到首行
        # `session` 事件，user/message 与 turn/end 全部看不到，状态永远判为 idle
        # （这正是桌宠一直显示"DSH 空闲"的根因）。
        dctx = zstandard.ZstdDecompressor()
        with open(path, "rb") as fh:
            try:
                reader = dctx.stream_reader(fh, read_across_frames=True)
            except TypeError:      # 老版本 python-zstandard 无此参数
                reader = dctx.stream_reader(fh)
            with reader:
                buf = reader.read(MAX_DECOMPRESS)
        events = []
        for line in buf.decode("utf-8", "replace").split("\n"):
            if '"type"' not in line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        with self._lock:
            # 仅保留少量最近文件，避免缓存无界增长
            if len(self._cache) > 8:
                self._cache.clear()
            self._cache[path] = (st.st_mtime, st.st_size, events)
        return events
