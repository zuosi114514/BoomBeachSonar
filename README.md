# BoomBeachSonarAuto

基于 **ADB + OpenCV + EasyOCR** 的海岛奇兵声呐活动界面自动化与菱形网格识别工具。项目通过 ADB 获取模拟器截图，使用模板匹配进入活动页面，读取人工校准点位或自动识别菱形网格中心点，优先使用潜艇搜索算法探索潜艇位置，最后生成命中可视化图片并自动点击命中格。

推荐使用 **四模拟器总控 GUI**（`gui_app.py`）并行管理多台设备；也支持单设备命令行模式（`main.py`）。

> 说明：本项目仅用于图像识别、自动化流程和个人学习研究。使用前请确认不会违反目标应用的用户协议或平台规则。请自觉在 24 小时后删除。
> 建议有 Python 或自动化工具开发基础的人员使用，使用本软件的风险完全由用户自行承担，作者不对任何直接或间接损失承担责任。

## 功能特性

- **四模拟器总控 GUI**：tkinter 面板，支持 4 个槽位独立绑定 ADB 设备，一键全部启动/停止/重启。
- **国服 / 国际服**：每个槽位可单独选择游戏版本，自动切换包名与登录流程。
- **自动循环跑关**：进入活动后自动识别关卡，弹药耗尽时可选自动领取活动奖励后继续。
- **关卡识别**：模板匹配 + EasyOCR 双重识别当前海域编号。
- **弹药 OCR**：读取右下角蓝弹药数量，探测过程中也会检查弹药。
- **潜艇搜索策略**：1 至 36 号海域自动化探索，显著减少实际探测次数。
- **人工校准点位**：优先使用 `save_points/points.json` 固定点位，缺失时回退自动识别。
- **弱网 / 断网控制**：root ADB shell + iptables，按游戏 UID 控制 DROP 弱网与 REJECT 断网。
- **胜利界面处理**：自动跳过胜利弹层；命中格点击后若未出现胜利界面会自动重试统一点击。
- **PyQt6 调试工具**：坐标查看、ROI 选区、模板保存、人工校准点位、弱网诊断等。

## Update

2026.7 (new)
- 新增 **四模拟器并行总控 GUI**（`gui_app.py` + `worker.py`），每个槽位独立子进程、独立日志与输出目录。
- 新增 **`settings.json`** 用户配置，GUI「全局设置」页可直接修改超时、OCR、弱网等参数并保存。
- 支持 **国服 / 国际服** 分槽位配置；国际服为默认包名 `com.supercell.boombeach`。
- 主流程支持 **自动识别关卡 + 弹药 OCR + 弹药用尽领取奖励** 的多轮循环。
- 命中格点击后若未出现胜利界面，会 **自动重试统一点击** 一次。
- 每关开始前恢复弱网保护；关卡识别前等待延迟出现的胜利界面。

2026.6
- 进入活动流程改为最多 5 次有限重试，失败时重启游戏、等待登录后再重新进入。
- 主流程输出统一走日志，命中矩阵和结果图片路径会记录到日志文件。
- 补充主流程入口恢复逻辑的单元测试。
- 舍弃原有全海域逐格迭代，改用潜艇搜索策略。
- 当前已完全支持 1 至 36 号海域的自动化搜索算法探索。
- 完全修复弱网不稳定问题，使用 REJECT 断网消除本地缓存。
- 网络控制已区分为两类规则：DROP 弱网和 REJECT 断网。

## 项目结构

```text
.
├── gui_app.py                 # 四模拟器总控 GUI（推荐入口）
├── worker.py                  # 单设备无界面 worker，由总控启动
├── main.py                    # 单设备命令行主流程
├── config.py                  # 路径、包名、网格、模板匹配等底层配置
├── settings.json              # 用户可改配置（GUI 保存到此文件）
├── take_screenshot.py         # 保存海域截图，用于新增海域点位校准
├── run_gui.bat                # Windows 一键启动 GUI（conda 环境）
├── requirements.txt           # Python 依赖
├── assets/
│   └── app_background.png     # GUI 背景图
├── template/                  # 模板匹配所需图片
├── save_points/
│   ├── points.py              # 点位 JSON 读写工具
│   ├── points.json            # 人工/自动生成的固定点位数据
│   └── imgs/                  # 各海域参考截图（关卡识别用）
├── utils/
│   ├── adb_control.py         # ADB 封装、手势、应用启动和弱网/断网控制
│   ├── image_match.py         # 模板匹配
│   ├── diamond_centers.py     # 菱形网格检测与中心点计算
│   ├── diamond_hit.py         # 点击前后截图对比与命中判断
│   ├── submarine_strategy.py  # 潜艇搜索策略
│   ├── ocr_helper.py          # 关卡 / 弹药 OCR 识别
│   ├── reward_helper.py       # 活动奖励领取
│   ├── user_settings.py       # settings.json 读写与应用
│   ├── runtime_context.py     # 多实例运行目录与停止信号
│   └── logger.py              # 日志配置
├── tests/                     # 策略、OCR、多实例与主流程单元测试
├── runtime/                   # 多实例运行时目录（git 忽略，按槽位生成）
│   └── slotN/
│       ├── logs/bbma.log
│       ├── outputs/
│       └── screenshots/
├── _debug/
│   ├── debug_gui.py           # 实时坐标 / ROI / 模板保存 GUI
│   ├── point_editor.py        # 人工点位校准 GUI
│   ├── weak_network_gui.py    # 弱网与断网开关、诊断 GUI
│   ├── screenshots/           # 单设备模式调试截图
│   └── logs/                  # 单设备模式日志
└── outputs/                   # 单设备模式命中可视化输出
```

## 环境要求

- Python 3.10 或更高版本。
- 已安装并可在命令行使用的 `adb` 工具。
- 一台或多台已开启 ADB 调试的安卓设备或模拟器。
- 设备需要支持 `adb root`，否则脚本无法使用 iptables 自动控制弱网或断网。
- 海岛奇兵 **国服或国际服**（每个槽位可单独选择）；非默认包名请在 GUI 或 `settings.json` 中调整。
- 建议使用雷电模拟器，并将分辨率设置为 `1280x720`。
- 首次运行 EasyOCR 会下载识别模型（脚本已配置国内镜像加速）。
- 当前模板图片需与设备分辨率、游戏界面语言、UI 状态尽量一致。

## 安装

进入项目目录后运行：

```powershell
python -m venv .venv
.\.venv\Scripts\activate

pip install -r requirements.txt
```

macOS / Linux 虚拟环境激活：

```bash
source .venv/bin/activate
```

连接设备前可以先检查 ADB：

```powershell
adb devices
adb connect 127.0.0.1:5555
```

弱网和断网控制依赖 root shell，运行前建议确认：

```powershell
adb -s 127.0.0.1:5555 shell id -u
```

输出 `0` 表示当前 ADB shell 已具备 root 权限。

## 使用方法（推荐：GUI 总控）

1. 启动 1 至 4 台安卓模拟器，分辨率 `1280x720`，登录到游戏主界面。
2. 运行总控 GUI：

```powershell
python gui_app.py
```

Windows 也可双击 `run_gui.bat`（需已配置 conda 环境 `boom-beach-sonar`）。

3. 在「设备总控」页为每个槽位配置：
   - **启用**：是否参与「全部启动」
   - **版本**：国服 / 国际服
   - **ADB**：从下拉列表选择设备序列号（点「刷新设备」）
   - **指定关卡**：留空则自动识别；填写数字则首关固定该海域
4. 点击 **保存配置**，再点 **全部启动** 或各槽位的 **启动**。
5. 右侧日志面板可查看总控与各槽位 worker 的实时输出（关卡、弹药、运行时间等）。

每个槽位的独立输出位于：

```text
runtime/slot1/outputs/hit_map_level_<level>.png
runtime/slot1/logs/bbma.log
runtime/slot1/screenshots/
```

GUI 工具栏还支持：**全部停止**、各槽位 **停止 / 重启**、**隐藏 / 显示日志**。

## 使用方法（单设备命令行）

适合只跑一台设备、或调试主流程时使用。

1. 编辑 `settings.json` 中的 `adb_serial`、`game_package_name` 等（或直接改 `config.py`）。
2. 确认设备已登录主界面且声呐活动入口可见。
3. 运行：

```powershell
python main.py          # 自动识别关卡并循环跑关
python main.py 18       # 命令行指定首关为 18 号海域
```

单设备模式的输出路径：

```text
outputs/hit_map_level_<level>.png
_debug/logs/bbma.log
_debug/screenshots/run_debug/
```

## 配置

日常参数优先改 **`settings.json`**，GUI「全局设置」页保存后会写回该文件。`config.py` 保留网格边长、潜艇长度、ROI 等底层常量。

### settings.json 主要字段

| 配置项 | 说明 |
| --- | --- |
| `adb_serial` | 单设备模式默认 ADB 地址 |
| `game_package_name` | 单设备模式默认游戏包名 |
| `log_level` | 日志级别：DEBUG / INFO / WARNING / ERROR |
| `manual_level` | 全局手动指定关卡；`null` 为自动识别 |
| `match_threshold` | 模板匹配阈值 |
| `use_saved_points` | 是否优先使用校准点位 |
| `ocr_enabled` | 是否启用 OCR 辅助关卡识别 |
| `claim_rewards_when_ammo_empty` | 弹药用尽时是否自动领取活动奖励 |
| `hit_click_interval` | 点击命中格间隔（秒） |
| `victory_wait_timeout` | 点击命中格后等待胜利界面超时（秒） |
| `activity_button_timeout` | 等待活动按钮超时（秒） |
| `sonar_wait_timeout` | 等待海里声纳浮标超时（秒） |
| `instances` | 四槽位配置：启用、ADB、版本、指定关卡 |

每个 `instances` 槽位示例：

```json
{
  "slot": "slot1",
  "enabled": true,
  "serial": "emulator-5554",
  "game_region": "cn",
  "manual_level": null
}
```

`game_region` 可选 `cn`（国服）或 `international`（国际服）。

### config.py 常用底层项

| 配置项 | 说明 |
| --- | --- |
| `LEVEL_GRID_SIZES` | 各海域菱形网格边长 |
| `SUBMARINES` | 各海域潜艇长度列表 |
| `USE_SAVED_POINTS` | 是否优先使用 `save_points/points.json` |
| `SAVED_POINTS_FILE` | 固定点位 JSON 文件 |
| `DEFAULT_MATCH_THRESHOLD` | 默认模板匹配阈值 |
| `LEVEL_REF_DIR` | 关卡参考截图目录 |
| `OCR_ROI` / `AMMO_ROI` | 关卡数字 / 弹药数字识别区域 |

多实例 worker 启动时会通过环境变量 `BBMA_ADB_SERIAL`、`BBMA_GAME_REGION`、`BBMA_RUNTIME_DIR` 覆盖单设备默认值。

## 支持自定义海域

目前已完全支持 1 至 36 号海域的自动化搜索算法探索。若想手动支持后续海域，需要补充潜艇长度和人工点位：

1. 修改 `config.py` 中的 `SUBMARINES`，填写目标海域的潜艇长度列表。
2. 模拟器进入目标声呐界面（不要手动拖放或缩放海域视角）。
3. 修改 `take_screenshot.py` 中的保存路径，将截图保存为 `save_points/imgs/<海域编号>.png`，然后运行：

```powershell
python take_screenshot.py
```

4. 使用点位校准工具打开刚才保存的截图，调整定位并保存：

```powershell
python _debug/point_editor.py
```

## 人工点位

主流程默认 `use_saved_points = true`，会优先读取 `save_points/points.json`：

- 固定点位包含关卡截图路径、网格边长、图片尺寸、大菱形四角和每个小格中心点。

人工校准点位：

```powershell
python _debug/point_editor.py
```

点位校准 GUI 支持拖动外层大菱形四角、拖动每个小菱形中心点，并保存到 `save_points/points.json`。

## 弱网控制

主流程通过 ADB root + iptables 自动实现游戏网络控制。脚本在进入活动前开启游戏弱网，在重启游戏和退出脚本时关闭弱网。

项目同时提供 REJECT 断网能力。REJECT 使用独立 `BBMA_REJECTNET` 链，不会关闭整机 Wi-Fi 或移动数据。

单独启动弱网/断网调试工具：

```powershell
python _debug/weak_network_gui.py
```

弱网调试工具支持：

- `开启弱网(DROP)` / `关闭弱网(DROP)`
- `开启断网(REJECT)` / `关闭断网(REJECT)`

专用日志：`_debug/logs/weak_network_gui.log`

## 图片说明

启动脚本前需手动登录进主界面（如图）：

<p align="left"><img src="docs/images/home.png" height="400"></p>

最终输出示例，红色方框即为潜艇：

<p align="left"><img src="docs/images/hit_map_level_18.png" height="400"></p>

## 调试工具

截图调试和模板裁剪 GUI：

```powershell
python _debug/debug_gui.py
```

常见用途：

- 自动点击位置不准时，查看鼠标实时坐标，左键单击标点，或输入 x/y 坐标跳转标记。
- 需要完整模拟器画面时，直接保存当前完整截图。
- 新设备或新分辨率适配时，左键拖拽选中 ROI 后保存到 `template/` 下。

人工点位校准 GUI：

```powershell
python _debug/point_editor.py
```

弱网与断网开关、诊断 GUI：

```powershell
python _debug/weak_network_gui.py
```

## 模板图片说明

当前主流程会使用以下模板：

| 文件 | 用途 |
| --- | --- |
| `template/activity_button.png` | 活动入口按钮 |
| `template/login.png` | 登录按钮 |
| `template/quit_activity.png` | 活动详情页退出按钮 |
| `template/ship.png` | 母舰图标 |
| `template/retry.png` | 断网重试图标 |
| `template/victory.png` | 胜利界面（金色星星 + 蓝条） |
| `template/sonar_join.png` | 海里声纳「参加」浮标 |
| `template/sonar_join_label.png` | 声纳浮标文字辅助匹配 |
| `template/reward_title.png` | 活动奖励弹窗标题 |
| `template/reward_close.png` | 活动奖励关闭按钮 |
| `template/sub_reward_btn.png` | 潜艇奖励入口按钮 |

`template/qnet_button_off.png` 为旧版 QNET 流程参考；当前主流程不再依赖该模板。

如果界面发生变化、分辨率不同或模板匹配失败，需要重新裁剪对应模板。

## 输出与调试文件

**多实例 GUI 模式（按槽位）：**

- `runtime/slotN/outputs/`：命中可视化结果图
- `runtime/slotN/logs/bbma.log`：该槽位主流程日志
- `runtime/slotN/screenshots/`：运行过程中的截图和中间图

**单设备命令行模式：**

- `outputs/`：主流程结果图
- `_debug/screenshots/`：运行过程中的截图和中间图
- `_debug/screenshots/run_debug/`：点击前后截图、退出按钮匹配调试图
- `_debug/logs/bbma.log`：主流程日志文件
- `_debug/logs/weak_network_gui.log`：弱网调试 GUI 日志

## 常见问题

### 找不到 ADB 设备

先运行：

```powershell
adb devices
```

如果没有设备，检查模拟器是否开启 ADB，或重新执行：

```powershell
adb connect <设备地址>
```

GUI 中点击「刷新设备」，并在对应槽位选择正确的序列号。多开时各槽位 **不能绑定同一个 ADB 地址**。

### GUI 启动 worker 失败

可能原因：

- 槽位未填写 ADB 或设备未处于 `device` 状态。
- 设备未安装对应版本的游戏包（国服 / 国际服包名不同）。
- 设备分辨率不是 `1280x720`（会警告但仍可尝试运行）。
- 无法获得 root shell。

可先单独运行设备检查：

```powershell
python worker.py --slot slot1 --serial emulator-5554 --runtime-dir runtime/slot1 --game-region international --check-only
```

### 无法开启弱网或断网

可能原因：

- 当前设备不支持 `adb root`。
- `adb shell id -u` 输出不是 `0`。
- 设备缺少 `iptables`。
- 游戏包名配置不正确，导致无法读取 UID。

主流程启动时会执行 `adb.ensure_root_shell()`。如果无法获得 root shell，脚本会中止。

### 模板匹配失败

可能原因：

- 模板图片与当前分辨率不一致（请设置为 1280×720）。
- 模板区域裁剪过大或包含动态背景。
- 国服 / 国际服 UI 文字不同，需重新裁剪模板。

可以使用 `_debug/debug_gui.py` 左键拖拽 ROI 并保存为模板，再适当调整 `match_threshold`。

### 关卡识别不准

可能原因：

- `save_points/imgs/` 中缺少对应海域参考图。
- OCR 模型尚未下载完成，或 ROI 与当前 UI 不匹配。
- 使用了特殊海岛基地皮肤（建议换为原版）。

可查看 `_debug/screenshots/level_detect/` 或 `runtime/slotN/screenshots/level_detect/` 下的调试图。也可在 GUI 或槽位配置中 **手动指定关卡** 作为临时方案。

### 菱形网格识别失败

可能原因：

- 截图中网格区域被遮挡。
- 当前画面不是活动详情页。
- 当前关卡没有人工点位，且自动识别没有找到稳定外框。

建议优先使用 `_debug/point_editor.py` 为该关卡保存人工点位。

## License

本项目源码公开，仅允许非商业用途。

未经作者书面授权，禁止将本项目用于商业产品、付费服务、商业自动化、商业代练、商业测试、商业运营、二次售卖或任何直接/间接盈利场景。

详见 [LICENSE](./LICENSE)。
