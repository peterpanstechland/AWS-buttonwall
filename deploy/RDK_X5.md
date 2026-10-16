# RDK X5 部署

## 192.168.88.123

2026-10-16 部署到 `sunrise@192.168.88.123`（主机名 `booth-03`）。系统 Ubuntu 22.04.5 / aarch64、Python 3.10.12、Chromium 149。RDK 程序仅依赖 Python 标准库；没有部署或刷写 ESP 固件。

- 版本目录：`/opt/aws-wall/releases/20261016-kiro31`，入口软链接 `/opt/aws-wall/current`。上一版 `20261016-physical-controls` 保留，可回滚原界面和语音；持久数据库未改，本次只更新界面提示和音频资源。
- 配置：`/etc/aws-wall.env`，模板 `deploy/aws-wall.env.example`。
- 持久数据库：`/var/lib/aws-wall/wall.db`，独立于版本目录。
- 浏览器 profile：`/var/lib/aws-wall-kiosk/chromium`。
- 局域网地址：`http://192.168.88.123:8091/`。实测有线 MAC 每次重启变化，DHCP 地址先后为 `.123`、`.182`、`.213`；经用户确认，现通过 `/etc/netplan/90-aws-wall-eth0.yaml` 固定为 `192.168.88.123/24`，网关和 DNS 保留 `192.168.88.1`。原 netplan 文件已备份到下述备份目录，Wi-Fi 配置未改。板上访问 `http://127.0.0.1:8091/?kiosk=1&effects=off`；SSH 也可使用 `booth-03.local`。
- 原拍照亭的 `booth@sunrise`、`booth-kiosk@sunrise`、`booth-log-vacuum.timer`、`booth-quiet-spidev` 已停止并取消自启，文件保留。原服务状态及配置备份在 `/home/sunrise/aws-wall-backup-20261016-015305`。

## 显示方式

`wall-display.service` 在 tty7 启动专用 Xorg，使用 Xauthority cookie，只开放本地 X socket。`wall-kiosk.service` 以 sunrise 用户启动独立 D-Bus 会话、关闭合成的 xfwm4 窗口管理器和 Chromium kiosk。窗口管理器是必要条件：这台系统上只有 Xorg 时 Chromium 的 kiosk 参数仍停在 945×1060，加入 xfwm4 后实测铺满 1920×1080。

`display.sh` 使用 `modetest -M vs-drm -c` 主动探测 HDMI，等待插入后启动显示。这版驱动冷启动后的 sysfs 状态会一直是 `unknown`，仅轮询 sysfs 无法启动，必须先执行 DRM 探测。`kiosk.py` 读取 xrandr 的 EDID 模式，按屏幕报告顺序选择第一个横屏、非隔行、不超过 1920×1080 的模式，并每 5 秒检查。小屏按其支持的模式显示；更换屏幕后重新选择。当前屏幕首个模式 2048×1152 超过所设上限，因此实际选择 1920×1080@60Hz。RDK 官方 HDMI 输出说明见 [显示屏使用](https://d-robotics.github.io/rdk_x_doc/Quick_start/display_use/display_rdkx5/)。

当前 Xorg/Chromium 使用软件图形路径，默认 `WALL_EFFECTS=off`、`WALL_REDUCED_MOTION=0`。`?kiosk=1&effects=off` 保留轻量首页演示，关闭 WebGL 和持续运行的架构装饰动画。可设置 `WALL_REDUCED_MOTION=1` 将首页也切为静态三步说明。中文字体由系统 Noto CJK 提供。没有安装远程字体或 CDN 依赖。

HMI 已增加低矮横屏样式和 `vh` 回退。局域网 HTTP 缺少 `crypto.randomUUID()` 时改用 `crypto.getRandomValues()`，可以正常操作。1024×600 以上更适合架构文字阅读；800×480 虽可容纳控制区，架构文字仍很小。

## 运行与维护

设备需要 `Xorg`、`xrandr`、`xauth`、`mcookie`、`chvt`、`xset`、`xprop`、`xfwm4`、`dbus-run-session`、`chromium` 和中文字体；本机已具备。安装服务时使用 `install -m 644`，版本文件归 root 所有并设为普通只读文件，避免 Windows 打包权限被解释为全局可写。

```bash
sudo systemctl status wall-backend wall-display wall-kiosk
curl http://127.0.0.1:8091/api/health
sudo journalctl -u wall-backend -u wall-display -u wall-kiosk -n 80

# 配置或程序更新后
sudo systemctl restart wall-backend wall-kiosk

# 显示服务需要重启时，先关闭浏览器，再依次启动
sudo systemctl stop wall-kiosk
sudo systemctl restart wall-display
sudo systemctl start wall-kiosk
```

`WALL_HOST=0.0.0.0` 用于本次局域网演示；可改为 `127.0.0.1` 限制本机访问。维护 PIN 通过 `WALL_OPERATOR_PIN` 设置，未设置时维护登录不可用。`WALL_DEBUG_PORT` 仅供临时诊断，默认关闭，不要向局域网开放调试端口。

## 离线语音与无人值守

`hmi/audio/` 包含 44 组中英文提示，共 88 段 MP3：20 组通用说明、16 组服务名称、8 组场景选择。`prompts.json` 是文案及文件映射，`build-report.json` 记录 Edge TTS 音色、时长、速率和 SHA-256。修改文案后，安装 `edge-tts mutagen`，运行 `python tools/generate_edge_voice.py`；制作时联网调用 Edge TTS，中文使用 XiaoxiaoNeural，英文使用 JennyNeural。运行时仅播放本地文件，不依赖互联网。引导模式逐步播报目标服务名称，竞速保持独立判断；开始键统一称 Kiro。

kiosk 设置 `XDG_RUNTIME_DIR=/run/user/1000` 和 `PULSE_SERVER=unix:/run/user/1000/pulse/native`，对应本机 sunrise 用户。用户 lingering 已启用，`pulseaudio.socket` 随用户管理器启动。Chromium 允许本地自动播报；USB 音箱插入后，`kiosk.py` 每 5 秒选择 USB sink 并迁移 Chromium 音频流。未检测到 USB 时使用系统默认输出，音量不被反复覆盖。可用 `pactl list short sinks`、`pactl get-default-sink` 检查输出，用 `pactl set-sink-volume @DEFAULT_SINK@ 70%` 调整现场音量。

语言、语音、重听、音量和减少动态均通过实体设置键操作，正常界面隐藏触屏按钮。待机长按 Kiro 2 秒，或菜单按 D4 进入设置；具体槽位表见 README。偏好保存在 `/var/lib/aws-wall/wall.db` 的 `ui_preferences`，自动创建该表并保留原有成绩。状态切换会停止上一段播报。菜单／设置 90 秒、自由探索／暂停 120 秒、结果 30 秒无人操作后回首页；参数在 `config/game_config.json` 的 `inactivity`。竞速中不自动跳出，仍需 Kiro 长按后双击确认结束。

后端 `navigation` 同时驱动实体键事件映射和屏幕 4×4 方形按键图。`light_plan` 含 16 键灯效和亮度上限：蓝呼吸可选、黄脉冲选中、紫常亮设置、白常亮返回。ESP 尚未连接，本次仅输出计划和屏幕预览（`hardware_applied=false`），没有刷写固件。Kiro 是第 17 个物理键，内部 ID 仍为 0，实际按钮灯保持硬件常亮。

如需恢复原拍照亭，先停止并取消按钮墙三个服务自启，再启用原两项主服务：

```bash
sudo systemctl disable --now wall-kiosk wall-display wall-backend
sudo systemctl enable --now booth@sunrise booth-kiosk@sunrise
```

## 验证及当前边界

2026-10-16 Edge TTS 更新：本机 70 项单元测试和新增语音行为检查通过；中英文 × 首页／模式／场景／设置 × 三分辨率共 24 组页面检查无溢出。RDK 验证 88 个 MP3 的 SHA-256、ffmpeg 完整解码及 Chromium 解码全部通过，欢迎语自动播放，中英文设置语音和引导目标 S3 播放正常。引导目标按架构当前能力顺序选择，前端状态轮询不会重复播报，竞速不播报目标答案。临时调试端口验证后关闭。

以下为上一版实体导航部署记录：

纯实体导航版本在本机通过 70 项单元测试。浏览器通过 43 项仅使用模拟实体电平／按键的交互检查，涵盖 8 关选择、全部设置、刷新持久化、游戏键不触发菜单和竞速退出。模式／场景／设置三页 × 三分辨率复核无溢出，所有 16 格为正方形。首页 1920×1080、1280×720、1024×600 中英文六阶段动效和减少动态模式均检查通过，第 17 键标识始终可见。

本次实体导航版本在 RDK 上通过 69 项单元测试（不运行本机端口工具测试）。板上 Chromium 实测视口与页面均为 1920×1080，首页 16 个服务键及 Kiro 图形均为正方形，无页面溢出。仅通过模拟实体按键完成设置、切换中英文、调音量、静音／重听、减少动态、选择模式和场景、进入游戏、暂停及返回首页；游戏中 D4 仍是服务键。40 段 MP3 全部在板端浏览器成功解码，欢迎语自动播放，音量设置实际作用于播放对象，无 JavaScript 异常。验证后恢复中文、语音开启、音量 80%、动态开启。

PulseAudio 已检测到 Chromium 音频流。当前仅检测到板载 ES8326 声卡，USB 音箱实物尚未插入，尚未验证该音箱的实际声压、音量或热插拔。

初次部署时完成整机重启实测：三个按钮墙服务自动启动，`NRestarts=0`；浏览器窗口为 1920×1080，旧项目四项自启保持禁用。本次更新完成服务重启与持久设置检查，临时 Chromium 调试端口已关闭。该检查不替代 8 小时稳定性测试或真实硬件联调。

目前后端只有 VirtualMcu，ESP 固件仍是 `BW PING/SLOT/OFF` 逐口测试协议；AWG1 真实串口传输尚未实现。设备 USB 枚举中也没有 ESP32。因此界面保持 DEMO，模拟成绩不进正式榜；不能把此次部署视为实体按键、按钮灯、灯带或正式比赛的联调验收。

## 鼠标测试与翻译提示

DEMO 页面默认允许直接点击菜单方块，并可从顶栏“测试按键”打开非模态 4×4 服务键面板。Kiro 保留单击、双击、长按两秒的模拟电平行为。正式串口模式不会启用这些模拟入口。页面声明 `google notranslate` 和 `translate="no"`；设备安装 `deploy/chromium-policy.json` 到 `/etc/chromium/policies/managed/aws-wall.json`，通过 `TranslateEnabled=false` 禁用 Chromium 翻译提示。用户自己的浏览器由网页标记阻止本页自动翻译，不修改其全局设置。



## BW2 实机刷写与启用（2026-10-16）

ESP32-S3（MAC `84:c7:bb:79:bf:94`、16 MB Flash、8 MB PSRAM）已刷写 BW2 统一固件，三个写入区域均通过 esptool 数据校验。应用 SHA-256：`beb747c0d5668a746741f38275435438a77a2b53534d37d255b31d1603615f9c`。刷写前完整 16 MB Flash 保存在 `/home/sunrise/aws-wall-backup-fw-20261016/esp32-before-bw2.bin`，SHA-256：`0401b3ce599ed08377b581f7eb0b05ddf19791eb0295a9348f2b2742d59b0e2a`。同目录保存切换前的环境配置。

`/etc/aws-wall.env` 当前为 `DEVICE_MODE=bw_serial`，端口 `/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_84:C7:BB:79:BF:94-if00`。后端服务已加入 dialout 附加组。实体模式关闭鼠标模拟入口，使用真实按键；如需恢复鼠标测试，将 DEVICE_MODE 改回 mock 后重启后端。

真实 USB 验证通过：15 秒连续 149 个状态包、CRC 匹配、完整灯效帧确认、按钮灯初始化成功；未发现 task_wdt 报警。故意停止心跳 2.6 秒后收到固件 WATCHDOG 退出确认。服务重启后 BW2 在线且 ready。以上不代替所有物理槽位、颜色和长时间运行的现场验收。仍是主机计时体验模式，不入正式排行榜。

## 当前版本：31 颗单元 + Kiro 灯箱 / BW3

2026-10-16 已刷写并启用 BW3：每单元 31 颗，A/B/C 各 124，D 路 D1→D2→D3→D4→START 共 155，总计 527。Kiro 位于 D 路零基偏移 124，长 31；服务 GPIO 和 MCP 位号不变。映射 CRC 为十进制 1248758811。

新应用 SHA-256：`07a19db3d509bf94461971d83fb9afb4f43b34ed3cd5c54ba636f82b1783dd7e`。刷写前读取旧应用到 `/home/sunrise/aws-wall-backup-fw-20261016/bw2-before-kiro31.bin`，其哈希与上一版发布文件一致。仅更新应用分区；BW3 后端与固件必须配对回滚。

固件编译与写入校验通过，板端 96 项测试通过；真实设备 BW3 在线、ready、灯效确认和按钮灯驱动就绪。界面在三种分辨率验证实体模式的 Kiro 仍禁用鼠标输入，但透明度为 1、背景为完整紫色。用户确认完整硬件尚未组装；实际灯箱颜色和 D4/START 边界尚未实测，待装配后验收。
