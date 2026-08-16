# -*- coding: utf-8 -*-
"""
Reasonix 状态监控 —— 只读轮询 Reasonix 的本地会话状态文件。

原理：Reasonix 把活跃会话信息写在 ~/.reasonix/desktop-tabs.json（activeTab ->
sessionPath），会话内容追加写入对应的 .jsonl 文件。程序不修改任何
Reasonix 文件，只通过文件 mtime/size 变化判断"是否有新消息"：

- 有新消息写入 → Reasonix 工作中
- 持续一段时间无新消息 → 空闲（视为任务完成/暂停）

状态机只报告状态转换（idle<->working），供桌宠冒泡提醒。
"""
import json
import os
import time

DESKTOP_TABS = os.path.join(os.path.expanduser("~"), ".reasonix", "desktop-tabs.json")
IDLE_AFTER = 20.0   # 秒：超过该时长无新消息视为空闲（完成提醒触发阈值）
CHECK_EVERY = 3.0   # 秒：轮询间隔


class ReasonixMonitor:
    """监控 Reasonix 活跃会话的活动状态。

    on_change(state) 回调：state 为 "idle" / "working"，仅在状态
    转换时触发（首次 poll 静默建立基线，不回调）。
    """

    def __init__(self, on_change):
        self.on_change = on_change
        self.state = None            # None | "idle" | "working"
        self.session_path = None
        self.last_mark = None        # 上次观测到的 (mtime, size)
        self.last_activity = 0.0     # 最后一次发现新消息的时间戳

    def poll(self):
        """检查一次状态；返回当前状态字符串。"""
        path = self._active_session()
        mark = None
        if path:
            try:
                st = os.stat(path)
                mark = (st.st_mtime, st.st_size)
            except OSError:
                mark = None
        self.session_path = path

        now = time.time()
        fresh = bool(mark) and (now - mark[0]) < IDLE_AFTER
        if self.last_mark is not None and mark != self.last_mark:
            self.last_activity = now
            fresh = True
        self.last_mark = mark

        new_state = "working" if fresh else "idle"
        if new_state != self.state:
            first = self.state is None
            self.state = new_state
            if not first and self.on_change is not None:
                self.on_change(new_state)
        return new_state

    def _active_session(self):
        """读取 desktop-tabs.json，返回活跃会话的 jsonl 路径；无则 None。"""
        try:
            with open(DESKTOP_TABS, encoding="utf-8") as f:
                tabs = json.load(f)
        except (OSError, ValueError):
            return None
        for t in tabs.get("tabs", []):
            if t.get("id") == tabs.get("activeTab"):
                p = t.get("sessionPath")
                if p and os.path.exists(p):
                    return p
        return None
