# AWS Architecture Challenge — 双设备固件与游戏开发规格书 V1.0

> 状态：开发基线草案（待核实 PCB 管脚、LED 数量及实体按钮灯电压后冻结）  
> 日期：2026-10-14  
> 对象：ESP32-S3（ESP-IDF）+ RDK X5（Linux HMI）  
> 原则：17 个物理按键；16 个服务；Kiro 为独立 START；全本地运行；现场可靠；真实、可解释的 Solution；中英双语。

## 0. 执行摘要与设计决策

- **硬件控制由 ESP32-S3 负责**：采样与去抖、独立按键编号、NeoPixel 帧渲染、灯效时间表、60s 计时权威时间戳、故障安全状态、USB 设备通信。
- **游戏逻辑由 RDK X5 负责**：HMI、三种模式、Mission/Graph/Rule Engine、正确性判定、得分、动画、离线存档、音效、排行榜。
- **USB 实体连接**：X5 USB Type-A Host → S3 原生 USB 设备口；ESP-IDF TinyUSB CDC-ACM。不能误连 X5 的默认 Device Type-C 口。先验证 S3 开发板接口走向与供电方式。
- **通信**：自定义版本化的二进制帧封装 UTF-8 JSON，有 CRC32、序号、命令 ACK、会话编号、重连状态同步。日志绝不混入协议端口。
- **灯效命令语义化**：X5 下发 `SET_SCENE` / `PLAY_CUE` 等，S3 本地合成像素帧，不逐帧从 USB 推送 384/512 颗 RGB。
- **模式**：`GUIDED` 引导构建、`FREE` 自由构建、`RUSH60` 一分钟构建挑战。START 独立 Kiro 按键，不占 16 个 Service ID。
- **Solution 是有向图 DAG + 多角色/多支路**，不是无意义地把所有图标串成一条线；规则可解释、不编造玩家组合能完成的功能。一个服务可在流程中重复出现（如两个 Lambda 任务），但仍只有一个实体按钮。
- **未定硬件**：是否有 16 个街机按钮自带灯及其电压；Kiro 按钮有没有普通单色灯。V1 先通过各 Service 的 WS2812 背光做功能光效，机械按键仅作为触点；物理按钮灯另做选装驱动接口，不能把可能的 12V 灯误接 5V 或 GPIO。

### 0.1 必须区分：已确定 / 暂定 / 待确认

| 类别 | 决策 | 状态 |
|---|---|---|
| 服务按钮 | 16 个固定服务，一颗对应一个 Service ID | 已确定 |
| START | Kiro 独立按钮，共 17 个触点 | 已确定 |
| 主控/HMI | ESP32-S3 + RDK X5，USB 连接 | 已确定 |
| 软件 | ESP-IDF / X5 Linux | 已确定 |
| 物理面板 | 单块约 200.4×200.4mm，100mm 游戏按钮帽 | 已确定（以 CAD/实物为准） |
| NeoPixel | WS2812 系列 60 LED/m，服务区分组控制 | 规划基线 |
| 灯珠数 | 默认 24 或 32 颗每 Service，**参数化**；真实安装后清点 | 待确认 |
| 数据连接 | 4 路各控制一个 2×2 区域 | 推荐，需 PCB 确认 |
| 按钮灯 | 可能为普通单色 LED，与 NeoPixel 不是同一回事 | 未确认 |
| Kiro灯 | **无 NeoPixel**；若有按钮自带 LED，再单独接驱动 | 已知 / 细节待确认 |
| X5 HMI | 本地网页触摸大屏或 Chromium Kiosk | 推荐 |

---

## 1. 业务范围与游戏体验

### 1.1 核心循环

1. 待机：X5 展示 `HIT KIRO TO START / 拍下 Kiro，开始构建`；服务灯箱低亮度呼吸或静态显示，Kiro 无 NeoPixel 动画承诺。
2. 拍 Kiro：进入模式选择或启动上次选择的模式（规则见 §4）。
3. X5 展示任务 Mission / Clue；S3 执行准备倒计时 `3→2→1→GO`。
4. 玩家按物理 AWS Service：S3 发送带毫秒时间戳的 `BUTTON_HIT`，X5 验证角色与规则、驱动架构图变化，再发送 `SCENE_SET`。
5. 完成某个解决方案：逐节点回放服务灯效、屏幕显示 DAG（允许分支）、一句中英双语解释、奖励/得分。
6. 一轮结束：返回模式大厅或直接加载下一个 Mission；`RUSH60` 在剩余时间内自动衔接。

### 1.2 三个游戏模式

| 模式 | 玩家看到 | 玩家做什么 | 如何判定完成 |
|---|---|---|---|
| Guided Build | 场景故事 + 分步骤能力提示，可选目标灯弱提示 | 根据功能猜服务并拍击 | 拓扑要求被满足 |
| Free Build | 空白方案画板 + 已选服务卡 + `推荐组合 / 缺少什么` | 任意选择、取消、提交分析 | 构成完整预置方案/支持的变体时 `VALID`；否则给 `PARTIAL/UNSUPPORTED` |
| Rush 60s | 任务名称、短能力提示、剩余时间、连击与累计 Solution | 60s 内快速选正确服务并完成多个任务 | 按完成 Solution 数排名，其次时间/错误数 |

**重要**：60s 模式不是“系统亮哪个就拍哪个”的机械打地鼠。HMI 至少要给**服务角色**提示，如“连接设备→处理数据→保存结果”；初始不直接把答案服务灯逐一高亮，否则不需要理解架构。Guided 模式可以开放提示，竞技模式降低提示。

### 1.3 玩家反馈原则

- 正确：服务卡由待选态进入绿色确认闪（250ms）后保持服务分类色或白色弱高亮，屏幕将节点加入 DAG。
- 选错：当前按键快速红色提示一次（两次以内，每次 150–250ms），HMI 显示准确理由，例如“这个节点不能代替消息队列”。错误按键不加入结果。
- 选中可选项：HMI 提示“可选增强项”，得少量加分，但绝不虚称其属于核心数据流。
- 组合完整：仅参与 Solution 的面板按照架构拓扑顺序点亮；并行节点同时或分组点亮。
- 所有高对比闪烁不超过 2Hz，提供 `reduce_motion`/静态模式；不要全墙高亮高频闪烁。

---

## 2. 17 个按钮 / 16 个服务的唯一映射

**逻辑编号永久稳定，与电路物理 GPIO 解耦。** `0 = KIRO_START`；服务 ID `1..16`。服务名称使用约定的展会 UI 列表；UI 若采用中国区商品名展示，可使用 `display_name_cn_event` 单独处理，不更改稳定 `service_key`。不要把 `Amazon IoT Core` 与 `AWS IoT Core` 变成两个逻辑 Service。

| ID | 稳定 key | 官方国际名称 | 中文短分类 | 物理分组 / 槽位 |
|---:|---|---|---|---|
| 0 | KIRO_START | Kiro START | 开始构建 | 独立 |
| 1 | EC2 | Amazon EC2 | 弹性计算 | A1 |
| 2 | S3 | Amazon S3 | 对象存储 | A2 |
| 3 | LAMBDA | AWS Lambda | 无服务器计算 | A3 |
| 4 | DYNAMODB | Amazon DynamoDB | NoSQL 数据库 | A4 |
| 5 | API_GATEWAY | Amazon API Gateway | API 管理 | B1 |
| 6 | CLOUDFRONT | Amazon CloudFront | 内容分发 | B2 |
| 7 | IOT_CORE | AWS IoT Core | 物联网连接 | B3 |
| 8 | SQS | Amazon SQS | 消息队列 | B4 |
| 9 | BEDROCK | Amazon Bedrock | 生成式 AI | C1 |
| 10 | AGENTCORE | Amazon Bedrock AgentCore | 智能体基础设施 | C2 |
| 11 | SAGEMAKER_AI | Amazon SageMaker AI | 机器学习 | C3 |
| 12 | REKOGNITION | Amazon Rekognition | 视觉分析 | C4 |
| 13 | TRANSCRIBE | Amazon Transcribe | 语音识别 | D1 |
| 14 | POLLY | Amazon Polly | 语音合成 | D2 |
| 15 | CLOUDWATCH | Amazon CloudWatch | 可观测性 | D3 |
| 16 | COGNITO | Amazon Cognito | 身份认证 | D4 |

物理配对使用两级映射（**不能直接拿 GPIO 编号推断 Logo**）：

```text
ESP32 GPIO (PCB) → Physical Key ID (A1..D4) → service_key (LAMBDA etc.)
NeoPixel: LED output lane + first_pixel + count → Physical Key ID → service_key
```

首次开机的 `Hardware Calibration` 页面显示 A1…D4；按下哪一个，X5 将对应位置点绿并显示 Service Name，确认 `physical_slot → service_key` 正确；单独保存 `mapping_version` 和 `mapping_crc32`。禁止在运行中随意动态交换按键和服务名称，避免错灯。

### 2.1 建议 LED 拓扑

4 路输出 A、B、C、D，**每路数据串联4张卡**、电源按分组并联。板上 NeoPixel 总量配置为：

```json
{
  "led_layout_version": 1,
  "lanes": [
    {"name":"A","gpio":"TBD","panel_ids":[1,2,3,4]},
    {"name":"B","gpio":"TBD","panel_ids":[5,6,7,8]},
    {"name":"C","gpio":"TBD","panel_ids":[9,10,11,12]},
    {"name":"D","gpio":"TBD","panel_ids":[13,14,15,16]}
  ],
  "default_leds_per_panel": 32,
  "color_order":"GRB",
  "global_brightness_limit":0.25,
  "idle_brightness_limit":0.08,
  "max_simultaneous_full_lit_panels":1
}
```

`default_leds_per_panel` 只是默认值；如果你的实际每块是24灯，则配置 24；不要让灯条段长“估算值”写死在 firmware。服务卡 4×4 的展示坐标和 PCB 分线槽位应各自保存，可重排但不改变 `service_id`。

**当前 PCB 待查**：每个面板 NeoPixel 是否串接 DIN/DOUT；若每张卡的 DIN 均独立回 HUB，则要根据 HUB 实际接法改变实现，不能直接套用此逻辑布局。

---

## 3. 系统职责与容错边界

| 功能 | ESP32-S3 | RDK X5 |
|---|---|---|
| 按键 GPIO 扫描、消抖、边沿事件 | 主责 | 接收事件 |
| WS2812 电气驱动、缓冲、RMT、颜色与亮度 | 主责 | 发送场景语义 |
| 每回合 3-2-1、本地可视提示 | 执行并回报时间戳 | 发送命令、同步显示/音效 |
| 60秒倒计时权威时间与失效点 | **主责**：单调时钟、判定超时边界 | 根据状态显示时钟、计分 |
| 模式、任务、游戏规则、完整架构校验 | 不实现业务图谱 | **唯一权威** |
| UI、中英双语、音效、动画和排行榜 | 无 | 主责 |
| USB 失联 | 保留故障状态，安全停止灯效并暂停时间 | 重连 / 同步恢复 |
| 断电复位 | 重置硬件状态、记录 `boot_id` | 会话恢复/中止、提示玩家 |

**避免两个游戏主控**：S3 不保存复杂 Mission Rule，X5 不在每帧操纵像素。S3 内置最小灯效自检程序，便于不接 X5 时调试。

---

## 4. Kiro START：17键下的模式选择与组合操作

**优先原则**：Kiro 始终是入口/控制键，服务键在非游戏期间不触发游戏；X5 HMI 负责主要模式选择，**不依赖“复杂的按钮连招”让普通玩家记忆**。

| 当前状态 | Kiro 单击 | Kiro 双击 | Kiro 长按 ≥2s | 16个 Service 按键 |
|---|---|---|---|---|
| IDLE | 打开/聚焦模式大厅，若明确启用 Quick Start 可直接运行上次模式 | 无动作（提示单击） | 操作员模式（需 X5 确认） | 不参与；维护模式可测试 |
| MODE_LOBBY | 开始 UI 当前选中模式 | 切换下一个模式（可选） | 返回 IDLE | 可选实体快捷键：EC2=Guided，S3=Free，Lambda=Rush60（只在大厅有效） |
| GUIDED | 显示暂停/继续选项（不直接重置） | 撤销上一笔（如该模式允许） | 退出确认 → IDLE | 选择服务 |
| FREE | **提交分析**（Analyze Build） | **撤销最近一个服务** | 退出确认 → IDLE | 追加/选择服务 |
| RUSH60 | 只切换 HMI 提示面板，不打断计时 | 不使用 | 请求弃赛，X5 二次确认 | 选择当前 Mission 需要的服务 |
| RESULT | 下一局/返回大厅（按模式） | 无动作 | 回 IDLE | 不参与 |

**核心防误操作**：采用延迟 250–300ms 的点击判定窗口以区分单击/双击；进入 `MODE_LOBBY` 后仅 EC2、S3、Lambda 三个键有模式快捷选择含义，不应把它们算成架构服务。HMI 上必须展示这三个实体快捷方式，但**不能依赖它们作为唯一入口**。

**替代 UX**：如果有触摸屏，默认只需要玩家拍一次 Kiro → X5 显示 3 个大按钮选择模式 → 再拍一次 Kiro 或触摸屏开始，最容易被现场观众理解。上面服务键快捷映射属于可选加速。

Kiro START **没有 NeoPixel**：S3 只采集它的触点。若实体 Kiro 按钮另有单色 LED，增加 `start_lamp_set` 抽象接口；无灯时 X5 的模式屏与服务灯箱承担倒计时、提示职责。**不能在固件里默认它支持 RGB 或呼吸灯。**

---

## 5. ESP32-S3 ESP-IDF 固件模块设计

### 5.1 模块目录

```text
firmware/
  main/app_main.c
  components/
    board_support/        # PCB GPIO 表、NVS 配置、启动检查
    input_scan/           # 17 GPIO scan + debounce + press/release + Kiro 手势
    strip_engine/         # espressif/led_strip, RMT, 4 output lanes
    scene_engine/         # Layer compositor、FX、时间轴
    timer_engine/         # 3-2-1 和 60s 权威计时
    usb_transport/        # TinyUSB CDC-ACM RX/TX
    wire_protocol/        # 帧解析、CRC、ACK、序号、防重放
    hardware_diag/        # 开机自检、点对点灯键检验
    config_store/         # NVS pinmap, strip layout, brightness, build ID
  test/
    unity/                # ESP-IDF 单元测试
    host_protocol/        # PC 模拟 X5 的协议测试脚本
```

版本建议锁定经过硬件验证的 **ESP-IDF 5.x 同一小版本**，依赖使用版本锁文件；灯条组件 `espressif/led_strip`、USB `esp_tinyusb` 从官方 Component Registry 固定兼容版本，不要开发中用 `*` 跟随最新。S3 支持 RMT 驱动 WS2812，RMT/SPI 驱动使用官方 `led_strip` 组件。参考：<https://components.espressif.com/components/espressif/led_strip>。

### 5.2 FreeRTOS Task 分工与优先级建议

| Task | 目标 | 调度方式 |
|---|---|---|
| `input_task` | 1ms GPIO 扫描（或 GPIO ISR +去抖任务） | 每1ms扫描，消抖15–25ms，输出事件队列 |
| `usb_rx_task` | 处理 CDC 输入字节流、CRC、解析消息 | 事件触发；不可在回调中做重活 |
| `protocol_task` | ACK、会话状态、命令调度 | 事件队列 |
| `scene_task` | 每20–33ms更新合成帧 | 30–50fps；有灯光资源争用时降为30fps |
| `timer_task` | monotonic deadline、倒计时状态、结束事件 | 10–20ms检查；时间基准用 `esp_timer_get_time()` |
| `health_task` | RAM、堆栈、输入状态、USB 活性 | 每1s |

`scene_task` 内部调用 RMT `refresh` 可能存在等待，不得与输入采样路径共享一个长临界区。4路 128LED/路更新预期只需毫秒量级，但要通过全灯测试实测响应时间；不要把刷新接口直接放 USB RX 回调里。

### 5.3 输入扫描与状态机

- `NO` 接 GPIO、`COM` 接 GND，启用内部或 PCB 外部上拉。GPIO 只读3.3V安全信号；按钮内灯单独驱动。
- 事件只有 `PRESS`、`RELEASE`，**每次稳定按下仅产生一个 `BUTTON_HIT`**；长按绝不重复计分。
- 消抖稳定门限：20ms（配置允许10–40ms）；扫描周期：1ms；每键不共享消抖状态。
- Kiro 手势单独处理：单击、双击、长按分离；服务键默认无双击业务含义。
- 同时按下两个服务时：两个 HIT 均单独报告，带 `press_id` 和本地单调时间；X5 按事件顺序处理，并允许明确的 `simultaneous` 检测。
- ESP32-S3 GPIO必须按实际开发板核对，保留 USB D-/D+ 所在 GPIO19/20，不使用启动限制脚及板载 Flash/PSRAM 占用脚；正式 `board_pins.h` 只能依据最终 PCB 原理图冻结。

### 5.4 灯带驱动：四路 RMT + 层叠场景

建议每块面板以一个 `panel_state` 渲染，而不是每次游戏去直接设置物理灯珠地址。

```c
// 概念接口；不是直接可编译的实现
void panel_set_state(uint8_t service_id, panel_visual_state_t st);
void panel_set_rgb(uint8_t service_id, rgb_t color, uint8_t intensity);
void scene_play_cue(cue_type_t cue, uint32_t duration_ms);
void scene_apply(const scene_desc_t *scene); // atomic frame commit
void scene_all_off(void);
```

每路物理灯带初始化：`strip_gpio_num`、`max_leds`、`GRB`、`rmt` 均从配置读出；四色服务类别颜色由 X5 参数提供，S3 不要保存公司品牌 Logo 色对应关系。建议每 32ms 刷新，亮度采取 **gamma 校正 + 全局预算限制 + 电流估算限流**；只有一处允许 `led_strip_refresh()`，避免两个 Task 同时写同一条灯。

**灯效叠层（从高到低）**：`FAULT/SAFETY` > `COUNTDOWN/TIMEOUT` > `HIT_FEEDBACK` > `SOLUTION_PROGRESS` > `IDLE`。上层灯效到期后回到下层，不用每次重新猜测之前哪个服务已点亮。

### 5.5 LED状态词典（视觉契约）

| 状态码 | 默认表现 | 用途 |
|---|---|---|
| `OFF` | 黑色 | 不参与、待机暗 |
| `AVAILABLE` | 分类色 6–12% 静态 | 可用服务，方便玩家识别 |
| `TARGET_HINT` | 分类色 20–30% 柔和脉冲 | Guided 模式提示 |
| `PRESSED` | 白色/分类色 200ms 亮一下 | 机械触发立即反馈（S3本地） |
| `ACCEPTED` | 绿色确认一次，再分类色 20–30% 常亮 | 该服务进入架构 |
| `REJECTED` | 红色短闪 1–2 次 | 不匹配/非法服务 |
| `SELECTED_FREE` | 蓝白色常亮或分类色常亮 | Free Build 已选服务 |
| `COMBO` | 对应服务顺序跑光，500–1000ms | 联动成功 |
| `COMPLETE` | 对应 Solution 子图按拓扑亮灯 2s | 架构完成 |
| `LAST10` | **仅任务候选/外框区域** 1Hz 警示脉冲 | 60秒剩10秒 |
| `LINK_LOST` | 整墙低亮静态橙色/紫色 | X5串口断开 |
| `FAULT` | 静态红色定位错误分区 | 硬件异常 |

所有颜色和速度可配置；不要高频全墙闪烁。**START 自身不属于这些 NeoPixel 区域。**

### 5.6 倒计时设计

- **准备倒计时**：`READY` 可选独立过渡（默认关闭）→ `3` 1s → `2` 1s → `1` 1s → `GO`，由 ESP 本地定时。HMI 使用同一个 `COUNTDOWN_STARTED` 时间戳更新倒计时动画。
- `3`：四个象限外沿弱琥珀色；`2`：两组切换；`1`：当前目标分组稳定亮；`GO`：结束闪烁、进入可操作。
- 60s 计时器：S3 设置 `deadline_us = esp_timer_get_time() + 60*1000000`；只认 **输入事件物理时间戳** `t_us <= deadline_us`。界面时间只用于显示。
- 结束前10秒：屏幕数字倒计时+候选面板 1Hz 提示，不改变原有 Selected 状态；最后 3 秒可以提高音效紧张感，但视觉闪烁不超过2Hz。
- `TIME_EXPIRED` 由 S3 发送且生效，不依赖 X5 某帧 UI；到期后新 HIT 不参与当前轮计分。
- 断线时先进入 `PAUSED_LINK` 并冻结剩余时间（`remaining_ms`）。X5 重连同步后才能 `RESUME`；若断线 >15s，可按现场配置直接结束本局并标记中断，而不是悄悄补分。

### 5.7 16颗/17颗普通按钮灯（硬件可选）

**Service NeoPixel 背光 ≠ 机械按钮内置灯。** 若实体游戏按钮内有独立单色 LED：

- PCB 若尚未设计按钮内灯驱动：**V1 不支持16路独立按钮灯控**，默认仅 NeoPixel 区域表达目标/选择状态。
- 若要支持16路独立按钮灯（尤其12V按钮）：需新增 **隔离的16路晶体管低边驱动 + 专用灯电源**（如级联74HC595/驱动芯片 + 合适 MOSFET/ULN2803），S3输出不能直接承载12V/灯电流。
- 若 Kiro 也自带普通LED，可单独加第17路，信号 `KIRO_LAMP`。不要将Kiro加入 WS2812 数据链。
- 运行时能力探测 `capabilities.start_lamp` 和 `capabilities.button_lamps`，由 X5 决定是否显示灯光控制项。`START_LAMP_SET` 只有硬件实现后才 ACK 成功，否则返回 `ERR_UNSUPPORTED`。

---

## 6. ESP32-S3 ↔ RDK X5 USB 物理与软件栈

### 6.1 连线

```text
RDK X5 USB Type-A Host  ─── USB A-to-C data cable ─── ESP32-S3 USB Device/OTG Port
RDK X5 HDMI / DSI        ─── HMI Display
5V独立受控电源          ─── LED 供电母线 + ESP/逻辑供电（按 PCB 的防反灌方案）
```

RDK X5 官方硬件说明：Type-A 为 Host；默认 Type-C 用于 X5 本身 Device 模式/烧录，不应作为连接 S3 的默认 Host 端。见 <https://developer.d-robotics.cc/rdk_doc/en/Quick_start/hardware_introduction/rdk_x5/>。

ESP32-S3 的原生 USB-OTG 与 USB Serial/JTAG 共享内部 PHY；选 **TinyUSB CDC-ACM 设备类**后，必须核对开发板原生 USB 口走 GPIO19/20 并正确配置 ESP-IDF；调试口如能独立提供 UART log 更好。见 <https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/usb_device.html>。

**USB CDC 的波特率配置不是数据带宽保证**：Linux `pyserial` 可设 115200 作兼容设置，但 USB 全速总线并非普通UART按这个波特率计时。每次读可能是任意大小字节块，不等于一条消息。

### 6.2 Linux设备与服务

- 插入后通常得到 `/dev/ttyACM0`（随拔插改变）；使用 `udev` 自定义稳定 `/dev/aws-wall-mcu`；若 descriptor 的 VID/PID/serial 未最后确认，暂时用 `/dev/serial/by-path` 定位，不能假定 `/dev/ttyACM0` 永远固定。
- 主服务：`aws-wall-hmi.service`（systemd自动重启、Watchdog）；UI本地 `http://127.0.0.1:...` 通过 Chromium Kiosk 启动。
- 主机进程：Python 3.11+（按 X5 镜像自带 Python 调整）；`pyserial` 或 `asyncio` transport；WebSocket → HTML/Canvas/SVG 界面。
- USB端口只能由一个进程打开；调试日志用第二个 UART/日志接口，不向协议通道 `printf()`。

---

## 7. USB Application Protocol V1（`AWG1`）

### 7.1 设计原则

- 对 USB 字节流做明确**消息帧**，解决半包、粘包和断线。
- 每条命令具有 `seq`；会修改状态的消息携带 `session_id`、`request_id`；**重复请求不得产生第二次灯效计分或启动第二个计时器**。
- 小体积 UTF-8 JSON 业务载荷便于 Python/C 实现，二进制头保证清晰 framing 和 CRC。
- HMI 侧保存完整业务状态。S3 的 `STATE_SNAPSHOT` 提供物理状态与计时状态，重连时以 `boot_id` 判定是否硬件重启。

### 7.2 帧格式（Little Endian）

| 字段 | 大小 | 说明 |
|---|---:|---|
| magic | 2 byte | `0xA5 0x5A` |
| version | u8 | `1` |
| msg_type | u8 | 见 §7.3 |
| flags | u8 | bit0=ACK_REQUIRED, bit1=IS_RESPONSE；其余0 |
| reserved | u8 | 必须为0 |
| seq | u32 | 发送端每次启动从1自增；重启以`boot_id`区分 |
| payload_len | u16 | 最大 `2048` byte |
| payload | N byte | JSON UTF-8，必须是对象 `{}` |
| crc32 | u32 | IEEE CRC32 over `version..payload`，**不含magic和crc字段自身** |

**固定头12字节、尾4字节，总长16+N字节。** RX状态机：搜索magic → 检查长度与版本 → 等待完整帧 → CRC → JSON schema → dispatch。长度超限直接丢帧并报告计数，不分配无限大内存。`seq` 各方向单独计数，无跨启动复用保证；可靠性依赖 boot_id/session_id/请求ID。

### 7.3 业务消息类型（0x十六进制）

| ID | 名称 | 方向 | 含义 |
|---|---|---|---|
| 0x01 | `HELLO` | S3→X5 | 启动自报版本/能力/boot_id |
| 0x02 | `HELLO_ACK` | X5→S3 | 主机握手与兼容版本选择 |
| 0x03 | `HEARTBEAT` | 双向 | 设备、心跳与时间戳 |
| 0x04 | `STATE_SNAPSHOT` | S3→X5 | 硬件输入、timer、scene、session、fault |
| 0x05 | `CONFIG_SET` | X5→S3 | LED布局、亮度、按键映射/校准设置 |
| 0x10 | `BUTTON_HIT` | S3→X5 | 触点确认的按下事件 |
| 0x11 | `BUTTON_RELEASE` | S3→X5 | 触点松开（按需） |
| 0x12 | `START_GESTURE` | S3→X5 | Kiro click/double/hold |
| 0x20 | `SCENE_SET` | X5→S3 | 声明所有16面板目标状态（原子替换） |
| 0x21 | `CUE_PLAY` | X5→S3 | 对当前场景叠加一次命名灯效 |
| 0x22 | `SCENE_CLEAR` | X5→S3 | 全灭/回待机 |
| 0x23 | `LAMP_SET` | X5→S3 | 可选：独立普通按钮灯控制 |
| 0x30 | `COUNTDOWN_START` | X5→S3 | 3-2-1启动准备与计时参数 |
| 0x31 | `COUNTDOWN_EVENT` | S3→X5 | 3/2/1/GO 本地时间戳 |
| 0x32 | `TIMER_EVENT` | S3→X5 | 开始/暂停/剩余/到期 |
| 0x33 | `TIMER_CONTROL` | X5→S3 | PAUSE/RESUME/CANCEL |
| 0x40 | `SELF_TEST` | X5→S3 | 诊断指定 slot / lane / button |
| 0x41 | `DIAG_RESULT` | S3→X5 | 诊断结果 |
| 0x7E | `ERROR` | 双向 | 结构化错误码与原因 |
| 0x7F | `ACK` | 双向 | 对可靠事件/命令的回执 |

### 7.4 标准 JSON payload 例子

```json
{"boot_id":"b4a9e8c1","fw":"1.0.0","proto":1,"device_id":"wall-mcu-01","service_count":16,"button_count":17,"capabilities":{"led_lanes":4,"service_backlight":true,"button_lamps":false,"start_lamp":false,"countdown":true}}
```

上面是 `HELLO`；`HELLO_ACK` 示例：

```json
{"proto":1,"host":"rdk-x5-01","ruleset_version":"rules-v1","session_id":"s-20261014-001","heartbeat_ms":1000}
```

按钮事件（物理稳定按下才发，不重复触发）：

```json
{"session_id":"s-20261014-001","press_id":837,"button_id":10,"slot":"C2","service_key":"AGENTCORE","t_us":251904427,"mapping_version":1}
```

Kiro 手势事件：

```json
{"session_id":"s-20261014-001","button_id":0,"gesture":"CLICK","press_id":838,"t_us":252004427}
```

原子场景设置（16个面板的状态 **全量声明**，消除前一场景残留）：

```json
{
  "session_id":"s-20261014-001",
  "request_id":"req-0092",
  "scene_id":93,
  "transition_ms":120,
  "panels":[
    {"id":1,"state":"AVAILABLE"},
    {"id":3,"state":"ACCEPTED"},
    {"id":10,"state":"TARGET_HINT"}
  ],
  "default_state":"OFF",
  "brightness_cap":0.25
}
```

计时开始：

```json
{"session_id":"s-20261014-001","request_id":"req-0093","pre_countdown_ms":3000,"game_duration_ms":60000,"timer_mode":"RUSH60","on_disconnect":"PAUSE"}
```

完成事件：

```json
{"session_id":"s-20261014-001","event":"EXPIRED","t_us":312000000,"remaining_ms":0}
```

ACK：

```json
{"ack_seq":135,"status":"OK","request_id":"req-0093","applied_scene_id":93}
```

### 7.5 ACK、重复包和重连策略

- S3→X5 `BUTTON_HIT` 必须可靠送达：序号 + `press_id`，主机收到后 ACK；如未 ACK，重发最多3次；X5 同 `session_id,boot_id,press_id` **只计一次**。
- X5→S3 `SCENE_SET`、`COUNTDOWN_START`、`TIMER_CONTROL` 必须 ACK，建议超时150ms，重试2次后进入 `LINK_UNHEALTHY`；同 `session_id,request_id` 重复请求只返回原结果。
- 场景乱序：`scene_id` 必须单调递增，旧场景不得覆盖新场景。
- USB反复枚举：S3 自动 `HELLO`，X5 调用 `STATE_SNAPSHOT`；如 `boot_id` 变化则丢弃旧按钮未确认事件，显示“控制器已重启，请重新开始”。
- 异步事件的 ACK 优先级高于 LED CUE；队列预留≥64条事件；队列满时不覆盖未确认的 HIT，而是停止接新游戏请求并报告 `ERR_QUEUE_FULL`。
- 心跳1秒，连续3秒无心跳进入 `PAUSED_LINK`；保留现场已选面板静态状态，不无限闪烁。恢复后必须显示“继续/结束”选择。
- CRC错误、JSON错误、未知命令、版本不兼容均返回 `ERROR`（对于无效帧可仅计错并拒绝执行，不能回复损坏帧）。

### 7.6 安全与权限

USB是本地可信物理连接，但仍要严控输入：最大长度、枚举值、最大亮度、LED 总数量、负数索引、非法颜色、未授权工厂命令；无 UI 用户权限的普通游戏界面不得发送 `CONFIG_SET` 修改引脚/校准映射。故障/维护模式在 HMI 操作员页需要 PIN 或物理确认。

---

## 8. RDK X5 HMI 软件设计

### 8.1 推荐进程架构

```text
X5/Linux
  systemd aws-wall.service
  Python Game Server
    ├─ SerialLinkService → /dev/aws-wall-mcu
    ├─ SessionManager
    ├─ MissionCatalog (JSON/YAML)
    ├─ RuleEngine
    ├─ GraphBuilder (DAG)
    ├─ ScoreEngine
    ├─ AudioEngine
    └─ SQLite (missions, sessions, leaderboards)
  HTTP/WebSocket 127.0.0.1
  Chromium Kiosk / HMI Frontend
    ├─ Lobby / ModeSelect
    ├─ GuidedGame
    ├─ FreeBuildCanvas
    ├─ Rush60 HUD
    ├─ ArchitectureResult
    └─ Operator Diagnostics
```

- **不用把网页 UI 与 USB 串口耦在一起**：后台消费协议并将标准化事件推送 WebSocket。UI 崩溃时主机后台仍能保留游戏状态。
- UI 所有服务名双语，物理面板上的正式展示文字通过独立 `display_name` 字段提供。中文标注是易懂的能力解释，不冒充唯一官方译名。
- 分辨率自适应：触摸一体屏、竖屏、横屏均显示“Mission + Solution画布 + 时间/错误/连击”。
- 本地数据：SQLite，避免云依赖；日志按天滚动并脱敏（无需录入姓名）；排行榜可匿名昵称或编号，采用现场可关闭的模式。

### 8.2 UI 页面

1. `ATTRACT/IDLE`：待机动态、`PRESS KIRO TO START`、三个模式简介。
2. `MODE_SELECT`：Guided、Free、Rush60 三张卡；可触摸或 Kiro+指定物理键选择。
3. `MISSION_INTRO`：Mission 标题、应用示意、人类问题、建造目标、若干 capability clues。
4. `GAME_ACTIVE`：左侧任务/进度、中间 DAG 架构构建区、右侧服务简报/计时。
5. `BUILD_ANALYSIS`：Free 下的已选图标、匹配到的 solution、缺失组件、依赖错误、可选服务。
6. `SOLUTION_COMPLETE`：动画沿拓扑 DAG 点亮，简短的中英双语说明，计分。
7. `FINAL_RESULT`：Rush60 完成数量/准确率/最佳 Combo，匿名排行。
8. `OPERATOR`：16个按钮/LED测试、映射校准、亮度、日志、版本与接入状态。

### 8.3 实时端到端延迟目标（非硬件已实测）

- **按钮→S3本地灯效**：稳定按下后 <30ms（含软件消抖；通过实物测试）。
- **按钮→X5界面反馈**：P95 <100ms、P99 <200ms（USB及UI运行正常）。
- **HMI命令→S3执行**：P95 <80ms（本地USB）。
- **灯效更新**：>=30fps，USB短时阻塞不得卡住按键扫描。
- **计时误差**：回合有效时间以 ESP 本地 monotonic 时间为权威；HMI在同步后显示误差目标<100ms。

---

## 9. Solution 规则引擎：核心产品逻辑

### 9.1 数据结构

**不要只保存“服务正确顺序数组”。** 定义 Mission 为 **节点需求 + 依赖边 + 可选项 + 可替代实现 + 图谱解释**。节点可附 `node_instance_id`、`service_key`、`role`、`mandatory`、`depends_on`；一个 `service_key` 可以对应多个实例。

```json
{
  "id":"M07_EVENT_DRIVEN",
  "title":{"zh":"事件驱动任务处理","en":"Event-Driven Processing"},
  "story":{"zh":"接收请求并排队处理后台任务","en":"Receive requests and process work asynchronously"},
  "difficulty":"medium",
  "nodes":[
    {"node":"entry","service":"API_GATEWAY","role":"api_entry","required":true},
    {"node":"producer","service":"LAMBDA","role":"enqueue_job","required":true,"after":["entry"]},
    {"node":"queue","service":"SQS","role":"queue","required":true,"after":["producer"]},
    {"node":"worker","service":"LAMBDA","role":"dequeue_worker","required":true,"after":["queue"]},
    {"node":"db","service":"DYNAMODB","role":"store_result","required":true,"after":["worker"]},
    {"node":"monitor","service":"CLOUDWATCH","role":"observability","required":false}
  ],
  "valid_variants":[],
  "teaching_points":["SQS 不是处理器，而是消息队列","同一AWS Lambda服务可以用在生产者和消费者两个逻辑节点"]
}
```

### 9.2 规则判定的四种结果

- `VALID_COMPLETE`：找到至少一个模板的所有必需功能，能解释数据流/依赖，不宣称部署完成。
- `VALID_PARTIAL`：组成了可解释子图，缺少必要角色；给最多3个可补服务，例如“缺少输入/API”。
- `VALID_VARIANT`：匹配模板允许的替代方案（EC2 替代 Lambda 作为计算节点时必须调整周边接入模式，不能无条件互换）。
- `UNSUPPORTED/CONFLICT`：所选服务无法以当前规则集构成完整已知 Solution，明确说“本地规则库暂未匹配”，**不能直接说在 AWS 上不可能**。

**无云端大模型也要能用**：V1 本地规则匹配 + scoring + 模板组合（deterministic）；可选 V2 接 X5 本地轻量 LLM **仅解释**，生成候选必须经规则校验。不要把模型自然语言输出直接当成安全可靠的架构判定。

### 9.3 可组合性与重复服务

- Guided 和 Rush：玩家按 Mission 的“下一缺失角色”服务；对于并行可选节点可以任意顺序完成，正确判定不应强制单一线性顺序。
- Free：每个服务第一击 `SELECT`，再次击可 `DESELECT`，或使用 Kiro 双击 `UNDO`。同一个物理服务按钮无法表示任意多个同服务实例；Free 的重复实例由 HMI 中的“添加第二个该服务角色”操作或上下文推导完成，不要求玩家连拍两次来猜。
- Rush 中具有重复 Lambda 的事件驱动 Mission：第一次拍 Lambda 记为 producer，SQS 后再次拍 Lambda 记为 worker，UI清晰显示 `Lambda ×2`，两个任务不是两种独立 AWS 产品。
- 当玩家选入 CloudWatch、Cognito 等辅助分支，结果图将其定位在旁路，不能机械接到业务数据流末端假装请求经过 CloudWatch。
- 游戏数据库版本号 `ruleset_version` 与结果共同保存，后续更新不会导致旧排行榜失去意义。

### 9.4 八套基础 Mission（简化教学架构，不代替生产级方案）

| ID | Mission（中英） | 强制服务 | 数据流/附属架构逻辑 | 可选增强 |
|---|---|---|---|---|
| M01 | AI Voice Assistant / AI语音助手 | TRANSCRIBE, LAMBDA, BEDROCK, POLLY | 语音→Transcribe→Lambda协调→Bedrock生成→Polly播报 | CLOUDWATCH |
| M02 | AI Vision / AI视觉识别 | S3, LAMBDA, REKOGNITION, DYNAMODB | S3上传触发Lambda；Lambda调用Rekognition分析；结果入DynamoDB | CLOUDWATCH |
| M03 | Smart IoT / 智能物联网 | IOT_CORE, LAMBDA, DYNAMODB | 设备→IoT Core消息规则→Lambda→DynamoDB；CloudWatch旁路监控 | CLOUDWATCH |
| M04 | Generative AI Agent / 生成式智能体 | API_GATEWAY, LAMBDA, AGENTCORE, BEDROCK | App→APIGW→Lambda→AgentCore运行Agent；Agent访问Bedrock模型 | DYNAMODB, CLOUDWATCH |
| M05 | Serverless Web / 无服务器Web | CLOUDFRONT, S3, API_GATEWAY, LAMBDA, DYNAMODB | CloudFront→S3静态资源；前端→APIGW→Lambda→DynamoDB | COGNITO |
| M06 | Classic Web / 经典云计算Web | EC2, S3, CLOUDFRONT | EC2应用计算；S3存静态文件；CloudFront用于分发S3内容 | CLOUDWATCH |
| M07 | Async Processing / 事件驱动处理 | API_GATEWAY, LAMBDA×2, SQS, DYNAMODB | APIGW→Lambda producer→SQS→Lambda worker→DynamoDB | CLOUDWATCH |
| M08 | Machine Learning / 机器学习推理 | S3, SAGEMAKER_AI, API_GATEWAY, LAMBDA | 数据S3→SageMaker训练/部署；APIGW→Lambda→SageMaker模型推理 | CLOUDWATCH |

这8套共覆盖16个服务（Cognito 在 M05 为可选认证服务）。为保证每张服务牌都有上场机会，还应把 16 服务的“使用率分布”作为内容运营指标；增加2个包含 Cognito 的身份场景、以及AgentCore与Bedrock的对照教学 Mission，成为第二批扩展内容。

### 9.5 Free Build 解读示例

玩家选择：`S3 + LAMBDA + REKOGNITION`。

```
状态：VALID_PARTIAL
可解释方案：AI Image Analysis / 图片智能分析
已有：S3上传图片 → Lambda触发分析 → Rekognition识别
推荐补充：DynamoDB（存储识别结果）
可选：CloudWatch（观测运行）
```

玩家选择：`TRANSCRIBE + BEDROCK + POLLY`。

```
状态：VALID_PARTIAL / VOICE_AI_MINIMAL
解释：具备语音转文字→模型推理→语音输出这三个基本能力。
推荐补充：Lambda（请求编排/服务调用），使架构更完整。
```

玩家选择：`EC2 + POLLY + SQS`。

```
状态：UNSUPPORTED（当前规则库未匹配）
解释：三者理论上可能构成某种应用，但缺乏用户场景与连接路径。
建议：选择“语音服务”或“异步任务”方向，并补充相关服务。
```

**不能在 unsupported 状态下声称“这组在AWS上不可能”。**

---

## 10. 三种模式的详细状态机

### 10.1 全局状态

```text
BOOT → SELF_TEST → USB_HANDSHAKE → IDLE
    → MODE_LOBBY → PREPARE → COUNTDOWN → ACTIVE
    → SOLUTION_COMPLETE → (NEXT_MISSION / FINAL_RESULT)
    → IDLE
                    ↘ PAUSED_LINK ↗
                    ↘ ABORT / ERROR
```

`ACTIVE`下 `MODE` 为 GUIDED / FREE / RUSH60；状态变化必须具备 `session_id` 和 `round_id`，迟到的上一回合命令不影响新回合。

### 10.2 Guided Build

1. Kiro → Mode Select → Guided；Mission 可以随机或人工指定。
2. 显示任务与故事，在 3s 倒计时后显示当前能力提示，不直接给 Logo 名称（easy难度可启用弱目标高亮）。
3. 用户按键；正确节点进入 DAG，并亮 `ACCEPTED`；错误只短闪不累计。
4. 每完成一个逻辑 Combo，可显示一条短知识点（如 `S3 can trigger Lambda / S3可触发Lambda`）。
5. 所有必需节点达成→Solution Complete→展示 DAG 和中文/英文解释→返回大厅。

引导难度：`EASY` 候选目标温和闪；`NORMAL` 只给角色关键词；`ADVANCED` 只给 Mission + 输入/输出，不提示服务。

### 10.3 Free Build

1. Kiro→Free；X5展示空白画板、16服务缩略图、已选数量、Analyze按钮。
2. 拍任意服务：增加到选中集合，灯箱保持 `SELECTED_FREE`；同一按钮再次拍：默认**取消该选择**，若需要服务多实例由HMI编辑逻辑节点。
3. 每增加一个服务，后台增量分析：可匹配哪些架构模板、缺哪个角色，显示 `POSSIBLE` 候选而非未经证实的完成结论。
4. Kiro单击或X5 `ANALYZE`：匹配完整方案、列出候选排名与架构拓扑；最多显示3个候选；若信息不足，提示用户选择业务场景（语音、视觉、IoT、Web、AI Agent等）。
5. 玩家点选一个候选，X5绘制带角色注释的架构图；可以继续追加服务改进。错误/无效组合也有教学解释，不扣分。
6. Kiro双击撤销最后一次操作；长按退出确认。

若 Free 玩家先选 `CloudWatch`，不立即判错，显示“运维/可观测性辅助组件，建议再加入被监控的计算或AI服务”。

### 10.4 Rush 60s

- 开始时 3s 预备倒计时，不计入60秒。
- `GO` 后 S3本地开始60,000ms倒计时；X5 每次给短Mission与角色线索，玩家依次拍正确服务。
- 首次错误扣 `-50分` 且不增加流程；连续正确形成连击 `combo`。
- 完成1个Mission立刻 `complete_count++`、快速回放灯效（≤1秒）并切换下一个，**60秒倒计时不断**。
- **挑战奖项主排行**：`solutions_completed` 高者胜；同数量按 `score` 高者胜；再次按 `invalid_hits` 少者胜。
- 游戏完成时至少显示：完成数、得分、正确率、最短Mission耗时、参与服务统计。
- Mission 调度必须考虑难度和重复率：每局从 easy/medium 池中按题目长度权重抽样，连续两题不重复；不出现“5服务题”和“3服务题”同分却难度大差异的比较问题。

**建议评分公式（可配置）**：每个必需有效角色 +100，完成Solution +300，连续正确额外 `min(5, combo)×20`，错误−50，可选分支完成+50，提示−80；最终排行以完成数优先，避免堆刷某个服务获得高分。

### 10.5 竞争公平性

- 用户可以通过 HMI 选择 `Standard 60s`：固定题库轮换、全部玩家难度权重一致；另有 `Random Practice` 可随机任务。
- 题目可能包含 Lambda×2，计分按角色实例，不只按唯一服务个数。
- 对 `Cognito`、`CloudWatch` 可作为可选得分项，Rush核心 Mission 不强制需要它们，或者专门加入认证/监控 Mission，使比赛公平。
- 一键作弊/抢拍随机16次不能完成 Mission：只接受可解释的下一个角色，乱拍扣分；不能通过一路重复按同一个服务完成新题。

---

## 11. 可维护的数据配置和内容引擎

```text
content/
  services.yaml           # 16稳定ID、中英名称、tag、分类色、图标路径、短描述
  missions.yaml           # 8+ Mission DAGs及变体
  difficulty.yaml         # easy/normal/rush线索和计分规则
  lighting.yaml           # 灯光状态颜色/动画、闪烁速度、降亮度
  hardware_mapping.json  # 由现场校准产生（GUI导出版本）
  i18n/zh-CN.json
  i18n/en-US.json
```

数据变化必须经过本地校验：服务引用存在、必需节点有路径、依赖图无环、全部能力提示至少双语；任务不允许引用现场不存在的服务 ID。内容升级可替换 YAML/JSON，无需重新编译 ESP32 固件。

---

## 12. 错误处理、现场运营与维护

| 故障 | 期望行为 |
|---|---|
| USB线被拔 | S3暂停当前60s计时、停止闪烁→静态低亮；X5显示断线，不删除得分 |
| ESP32重新上电 | X5发现boot_id变化，当前轮标记中断，不合并旧 press_id |
| X5 HMI重载 | 游戏后端继续；页面重新订阅状态和剩余时间 |
| 某面板灯断电 | 仅该分区熄灯，其他分区工作；HMI标记需要维护（没有电流检测时只能人工诊断，不能声称自动检测） |
| 某面板NeoPixel数据链断 | 同组下游可能不亮；HMI `lamp_test` 对第一个坏段定位 |
| 某按键卡住常闭 | 连续按住只记一次，长于30s标记疑似卡键，维护页提示 |
| 两键同时拍 | 各自去抖并上报；按时间顺序规则判定 |
| 断电后恢复 | 默认 `IDLE`，输出先全灭后安全待机，须Kiro重新开启 |
| 规则文件损坏 | 回滚到内置 last-known-good 规则集，禁止让随机无意义组合得分 |
| 缺少X5或屏幕 | 可做硬件自检，不宣称能完整运行架构游戏；恢复连接提示 |

维护页支持每个服务 `PRESS TEST`、`LIGHT TEST`、四路LED lane辨别、亮度上限、倒计时演示、协议状态、实时press log。上电自检禁止直接全墙满白。

---

## 13. 开发阶段与责任分配

### Phase 0 — Hardware bring-up（优先，1–2天粗估）

- S3用 IDF 编译/烧录，稳定启动；在 X5 用Type-A枚举为 ttyACM 或其它正确设备节点。
- 17个触点逐一调试，校验板上GPIO与服务编号对应；校验Kiro长短按。
- 4路灯带分别点亮一张测试卡，确认颜色顺序、数据方向、供电压降与刷新性能。
- 针对实际 USB 类型、所有实际 LED 段长、按钮内LED电压打一个 `hardware_config` 版本。

### Phase 1 — USB协议 + 灯带/按钮内核（2–4天粗估）

- Binary Frame、CRC32、partial RX、ACK、HELLO、重连。
- 17个按钮事件不重复；4路 NeoPixel；`SCENE_SET/CUE_PLAY`；COUNTDOWN。
- X5上写 Python protocol client/虚拟串口模拟器；使用 pytest 做回放。

### Phase 2 — Guided Mode + HMI（2–4天粗估）

- 完整UI: Idle、ModeLobby、Mission、Guided、Result。
- 8套预设任务、DAG拓扑展示、中文/英文双语。
- 按键与面板编号严格校准；从Kiro一击开始到Solution Complete完整通关。

### Phase 3 — Free Builder（2–4天粗估）

- 组合规则引擎、匹配和证据解释、建议缺失节点、Undo、各类部分解。
- 明确区分：有效、有效变体、部分有效、未匹配；多条可选拓扑路径。
- 本地测试不少于30组自由组合，杜绝乱报 Solution。

### Phase 4 — Rush60 + 运营版（2–3天粗估）

- 60s硬件时间与UI同步；连续出题、连击、排行榜；实物长时间热测试。
- 两种 HMI 设备分辨率自适应；断线恢复；开机自启动；维修页面。

**总粗估 9–17个工作日，依赖硬件已稳定、X5系统可用、UI素材就绪；这是工程规划，不是已完成进度。** 并行开发可缩短日历天数。

### 13.1 推荐最小开发分工

- ESP 工程师：`input_scan`、`strip_engine`、`wire_protocol`、timer、自检。
- Linux/HMI 工程师：串口服务、游戏状态机、Web UI、音效、SQLite。
- 规则/交互负责人：16服务实际架构验证、任务文案、评分可玩性与现场测试。

---

## 14. 验收标准（必须可复现）

**基本硬件测试**

- 17个按钮100次连续点击，100%按正确ID记录（人为按击可重复性需记录）；单次长按只上报一次 HIT；按键同时按下不丢。
- 四组灯带可独立点亮；每块卡的颜色/服务 ID 与 UI 对应；未确认情况下不允许默认全墙全亮。
- 3-2-1和60s计时：先由S3返回权威时间戳，HMI显示同步；耗时误差相对S3目标<100ms。
- 亮度 25%及多Solution完整回放，分别测试10A电源压降、接插件发热、板卡温度；5V输入不得明显掉至WS2812无效区域。

**协议测试**

- 随机拆分消息字节片段、多个帧粘包、CRC破坏、非法JSON、超长payload；不能死机或执行损坏命令。
- `BUTTON_HIT` 重发两次只计一次；旧 `SCENE_SET` 不能覆盖新场景；错session不得引入旧用户游戏。
- 热拔 USB 10次、S3软重启5次、HMI页面重载10次；能断线恢复或清楚提示重开，不错误续分。

**游戏验收**

- Guided 完成八个模板的有效组合；出错显示“角色为什么不匹配”；并行支路正确呈现在架构图中。
- Free：至少30个边界案例，包含 `S3+Lambda+Rekognition`、`Transcribe+Bedrock+Polly`、`EC2+Polly+SQS`；不虚构 Solution。
- Rush60：整60s精确停止，连续任务和分数正确；迟到事件不计分；同一服务可映射不同节点角色。
- Kiro硬件无NeoPixel时，功能完整；所有普通按钮灯相关特性必须feature-flag管理。

**稳定性**

- 展会前连续运行≥8小时，至少100场完整游戏；无崩溃、无无声失联、无明显灯带乱色、无按键/LED映射错误。
- 上电无需互联网，可在离线环境用X5正常选择任务并完成Solution。

---

## 15. 冻结前必须确认的 6 项实物信息

1. **ESP32-S3 具体开发板/PCB原理图**及可用GPIO，USB 端口是否原生USB-OTG。
2. **16个按钮/START的触点脚**、是否内置LED以及 LED 电压/共阴共阳/独立电源。
3. **每块 Service NeoPixel 实际颗数**（24/32/其它）、颜色顺序、前后接线方向。
4. **4组 HUB 是否真的 DATA 串行**、供电是否每组并联、主控实际DATA管脚及上拉/电平转换。
5. **RDK X5 系统镜像版本、显示屏方向/分辨率**、采用Chromium/Qt何种HMI。
6. **最终按钮上 UV Logo/中文/英文与实际硬件槽位表**；特别核对 Lambda、IoT Core 等中国区展示名称，但保持系统 key 不变。

这些信息未确认前，本文所有 `GPIO TBD`、LED 数、功率预算等均属于**方案默认值**，不应作为已测定硬件参数或直接量产承诺。

---

## 16. 开发资料与事实依据

本规格书的硬件接口/API边界参考：

- ESP-IDF ESP32-S3 USB Device / TinyUSB CDC-ACM：<https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/usb_device.html>
- Espressif 官方 LED Strip Component：<https://components.espressif.com/components/espressif/led_strip>
- D-Robotics RDK X5 USB Host 硬件说明：<https://developer.d-robotics.cc/rdk_doc/en/Quick_start/hardware_introduction/rdk_x5/>
- AWS S3触发Lambda示例：<https://docs.aws.amazon.com/lambda/latest/dg/with-s3.html>
- AWS SQS→Lambda Event Source Mapping：<https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html>
- Amazon Bedrock AgentCore Runtime：<https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html>

**注意：8套Mission为本项目设计的教学简化架构**；真实生产系统还需要IAM授权、网络/VPC/安全策略、成本、运维、边界异常等进一步设计。完整成功页面应使用 `SIMULATED SOLUTION COMPLETE / 模拟架构构建完成` 等表述，不让人误解设备已经在云上创建了资源。
