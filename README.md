# DS-pet 🐟

大肥鱼 Linux 桌面宠物（DeepSeek 娘桌宠）。一条会散步、会出屏探头、会趴下休息、会盯着你干活的鱼。

本项目**完全由 DeepSeek 系列模型创建并维护。**

## 项目背景

本项目是 [dafeiyu-pet](https://github.com/1190fasheqi/dafeiyu-pet)（Windows 桌面宠物）的 **Linux 移植与二改**，并适配了 [DSH-desktop-for-Linux](https://github.com/Quan-Robin/DSH-desktop-for-Linux) 的对话事件接口——桌宠能感知 DSH 的对话状态，在一轮对话完成时冒泡提醒你。

## 新增功能与改进（对比原项目）

### Linux 化
- **自包含 .deb 安装包**：PyInstaller 打包（含 Qt6 运行时依赖），安装到 `/opt`，提供 `.desktop` 桌面入口与 hicolor 图标，`sudo dpkg -i` 一键安装
- **鼠标穿透**：`WindowTransparentForInput`（X11 下不挡桌面操作）
- **开机自启**：XDG autostart（`~/.config/autostart`）
- **配置迁移**：config.json 移至 `~/.config/dafeiyu-pet/`（原版放程序目录，/opt 下不可写）
- **Wayland 适配**：自动检测会话类型，Wayland 下切 XCB（XWayland）保证窗口可自由移动

### 出屏探头动画（新增）
- 通过 `X11BypassWindowManagerHint` 绕过窗口管理器对窗口的屏幕钳制，桌宠可完全移出屏幕
- 随机出屏 → 屏幕边缘探头图探入 → 停留展示 → 缩回 → 回到屏内
- 探头方向自适应：上下左右四个方向的贴边偏移量独立可调

### 动作系统（新增）
- **趴下**：趴下休息（图片精灵 + 窗口自动加宽适配），时长/大小可调
- **耳朵晃动**：5 帧帧动画（慢速）
- **走路动画预留**：提供 `走路_N_306.png` 帧序列加载接口，后续补充素材即可启用

### DSH 对话状态提醒（适配 DSH-desktop-for-Linux）
- 只读轮询 DSH 会话事件日志 `~/.dsh/sessions/**/session.jsonl.zstd`（zstd 压缩）
- `user/message` 事件 → 状态"工作中"；**`turn/end` 事件 → 一轮对话完成**，冒泡提醒并附上完成轮的回复摘要
- 判定逻辑与 DSH 桌面版 `balance.js` 的 `checkTurnEnd` 完全一致，不修改任何 DSH 文件
- 右键菜单显示 DSH 实时状态，完成提醒可开关

### 参数调试窗口（新增）
- `debug_tuner.py`：拖动滑条实时调节 12 项参数（四向贴边超屏、探头停留/速度、出屏概率、探头图缩放、散步/跟随速度、趴下时长/缩放）
- 参数按尺寸档位（大/中/小）**独立配置**，互不影响
- 写入 config.json 后桌宠 1.5s 内热重载生效，无需重启

### 其他改进
- **跟随鼠标模式修复**：直调 `XQueryPointer` 获取鼠标位置（规避 Qt6.11 XWayland 下 `QCursor.pos()` 返回哨兵值的缺陷）
- **语录更新**：补充 DeepSeek V4 Pro GA / DeepSeek Harness 发布后的社区语录（涨价梗、角色专武梗等）
- 聊天面板点击外部自动关闭（修复卡死停摆）

## 安装

```bash
sudo dpkg -i dafeiyu-pet_1.0.0_amd64.deb
```

依赖：`libxcb-cursor0` 等 Qt6 运行时库（Ubuntu 24.04 默认满足；缺失时 `sudo apt install libxcb-cursor0`）。

## 从源码运行

```bash
cd src
pip install --user PySide6 psutil pynvml zstandard   # zstandard 用于 DSH 事件读取
python3 桌宠.py
```

## 调试参数

```bash
cd src && python3 debug_tuner.py
```

顶部下拉框选择尺寸档位（大/中/小），拖动滑条即写配置，桌宠 1.5s 内生效。

## 构建 .deb

```bash
cd src
python3 -m PyInstaller --noconfirm --onedir --windowed --name dafeiyu-pet \
  --add-data "sprites:sprites" --collect-all psutil --collect-all pynvml 桌宠.py
cd .. && packaging/build_deb.sh
```

## 素材与版权

- 基础精灵图与原始语录来自原项目 [dafeiyu-pet](https://github.com/1190fasheqi/dafeiyu-pet)（原作者：1190fasheqi）
- 探头 / 趴下 / 耳朵晃动素材为 AI 生成（`src/sprites/` 为处理后的运行时素材）
- 本项目完全由 DeepSeek 系列模型创建并维护。
