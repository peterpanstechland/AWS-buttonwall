# AWS Architecture Challenge — RDK X5 HMI / Game Backend Development Specification V1.2.1

> 状态：RDK X5 专项实施规格；继承 `AWS Architecture Challenge Complete Spec V1.2`，不是独立重新定义 MCU 线路协议。  
> 日期：2026-10-14。硬件基础：ESP32-S3（ESP-IDF，17触点、16个NeoPixel服务区、Kiro START无NeoPixel）通过原生USB CDC-ACM接入 RDK X5 USB Type-A Host。  
> 目标：离线即玩、完整可追溯、双语 HMI、从Kiro到真实可解释的教学Solution、稳定冲榜、可操作运维。  
> 此文为*待实现规格*，不表示功能已开发或实机验收。既有 v1.2 通讯协议、stable service IDs、ruleset 和 SQLite 表结构优先级高于此文中任何示例。

## 0. 已有/未定事实与强制约束

**已确定**：RDK X5 主机＋ ESP32-S3 USB Device；17 个实体键；服务 `1..16` 与 Kiro `0`；16个服务图案；RDK负责游戏、显示、存储；无需互联网或真正AWS资源；三种首发模式 GUIDED/FREE/RUSH60_RANKED；Kiro面板不接NeoPixel。

**待硬件确认**：X5系统镜像和Python版本；HDMI/DSI与触摸是否有；音频输出；X5供电及USB总线供电/ESP外部5V隔离；ESP CDC VID/PID/序列号；每面板LED数量、4组灯条拓扑、GPIO映射；实体按钮内置单色灯电压。所有待确认量进入 config/hardware.example.json，不得硬编码成量产事实。

**品牌约束**：Kiro START 物理面板不出现AWS字样；HMI名词由 `branding.json` 可配置，按活动方批准版本发布；服务稳定key独立于中文/国际版显示名。所有游戏结论是**模拟架构构建完成**，不是线上部署成功。

**部署基线**：RDK X5 官方资料支持USB Type-A Host、HDMI/DSI输出以及Ubuntu 22.04镜像（版本随发货镜像核实）；推荐HDMI 1920×1080横屏＋Chromium Kiosk。不能据此声称任意版本Chromium/音频已完成兼容测试。文档：https://github.com/D-Robotics/rdk_doc/blob/main/docs/01_Quick_start/hardware_introduction/rdk_x5.md

## 1. 产品目标、上线顺序与不做什么

**P0必须交付**：Kiro入口；三种模式；最少8个基础Mission（沿用V1.2）和本地配置校验；ESP设备发现与AWG1通信；17键映射；可解释Solution Graph；60s正式榜；中英双语；现场诊断；启动自恢复；故障注入测试。

**P1**：Ghost历史纪录对比、解锁成就、可拍照结果海报、可选背景音效和屏幕触摸/实体键双导航；本地作品墙。

**P2**：Duel双人轮流、Team协作、QR离线局域网分享、本地LLM解释。首发不需要X5 NPU推理，不要把随机LLM文案当规则结论。

**明确不做**：真AWS账号连接/资源创建，远程云依赖，强制用户手机号/实名，上传个人数据，靠拍满16键自动获胜，Kiro NeoPixel灯效，缺省接入外部AI接口。

## 2. 进程架构与单写者原则

```text
RDK X5 Ubuntu / systemd
 ├── wall-backend.service (Python asyncio; one authoritative game process)
 │    ├── DeviceSupervisor         /dev/aws-wall-mcu | /dev/serial/by-path/*
 │    │     ├── SerialReader        pySerial + AWG1 stream parser
 │    │     ├── ReliableOutbox      retry/ack/replay guard
 │    │     ├── DeviceStateMirror   boot_id, mapping_crc, capabilities
 │    │     └── LinkHealth          heartbeat/reconnect policy
 │    ├── EventIngress              bounded queue, event schema validator
 │    ├── GameReducer               SINGLE WRITER of authoritative game state
 │    │     ├── SessionFSM          session/round/step epoch + arm barrier
 │    │     ├── MissionScheduler    current mission, pack pinning
 │    │     ├── SolutionMatcher     roles, graph edges, valid variants
 │    │     ├── ScoringEngine       streak, penalties, completion-only awards
 │    │     └── Finalizer           terminal state once; ranked settle barrier
 │    ├── Repository                SQLite WAL, migrations, event log
 │    ├── ContentRegistry           16 services + mission rules + i18n
 │    ├── HMI StateBroadcaster      compact WebSocket changes / snapshot
 │    └── AdminService             pin/config/calibration/health
 └── wall-kiosk.service (Chromium -> http://127.0.0.1:8080)
      └── HMI (React + TypeScript)
           ├── Attract / Mode Select
           ├── Guided / Free Builder / Rush HUD
           ├── Architecture SVG / Solution Result
           ├── Leaderboard / Ghost / Achievement
           └── Operator Tools
```

技术建议：Python 3.10+ + FastAPI / Uvicorn / pySerial / SQLite 3；浏览器用React+TypeScript+Vite build静态文件。后端串口**单进程独占**；浏览器不能直接打开USB，也不能直接写 `score`。HMI只是状态投影，可随时刷新。

**事件处理序列**：串口Reader解析CRC → 校验协议与时钟上下文 → 消息事件进入有界队列 → GameReducer按确定规则归属 → SQLite事务写入raw event及状态 → 持久化后ACK可靠HIT → 生成持久版本revision → 推送HMI并下发幂等灯效命令。耗时动画/声音不得阻塞Reducer。高优先级事件（HIT, ARM, EXPIRED）与低优先级UI灯光日志分队列。

## 3. USB端接入与连接恢复

### 3.1 设备发现

- X5 **Type-A Host**接ESP32-S3 **原生USB CDC-ACM Device**；预期枚举 `/dev/ttyACM*`，实机按 `dmesg`, `lsusb`, `udevadm info` 校验。
- 用**真正的USB数据线**；不要误将ESP32的USB-UART桥当TinyUSB设备口。
- `udev`以实测VID/PID/serial配置 `/dev/aws-wall-mcu`；未确认前可用 `/dev/serial/by-path/`；不要写死ttyACM0。
- pySerial 以**原始字节流**读写，支持任意断帧/粘包；CDC行速115200配置仅是兼容参数，不能据此估带宽。
- 全部ESP调试日志输出到独立串口或其他通道，绝不混进二进制AWG1。

### 3.2 握手及安全闸门

1. 连接端口，等待 `HELLO`。校验 `proto_major=1`、`proto_minor>=2`、17按钮、16服务、4组NeoPixel能力及 `boot_id`。
2. 收到 `HELLO` 后发送 `HELLO_ACK`，随后 `SNAPSHOT_REQUEST`；核对 `mapping_crc32`与本地已审核的映射；映射不一致禁止正式排位。
3. 读取 `STATE_SNAPSHOT` 核对实际压住的键、armed/timer/scene及故障标记；若 X5 的 session 未得到ESP相同的boot/session/round确认，不能继续正式赛。
4. 待 `READY` 才开放 Kiro 游戏入口；服务状态未同步时界面显示设备连接中。
5. 心跳每1000ms，3s断连阈值作为基线；异常触发 `DEVICE_OFFLINE`、日志与用户提示。

### 3.3 状态恢复

- `GUIDED`/`FREE`：断线保存当前选择与图谱，重连后重新获取S3快照，提示继续或结束；若S3 reboot则必须重新ARM，所有先前按住键均先放开。
- `RUSH60_RANKED`：USB失联、ESP重启、后台崩溃、按键队列溢出、无法确认完整事件时 **INTERRUPTED，不入正式榜**；不暂停赚额外时间。
- HMI浏览器重载只重新拉 `GET /api/snapshot`，不能主动重启游戏。
- 旧 `scene_id`、`step_epoch`、`round_id`、`session_id` 对新的活动无效；重发使用相同`request_id`，只执行一次。

## 4. AWG1 协议：X5侧实现契约（严格沿用V1.2）

**AWG1帧：** 2字节魔数`A5 5A`；major 1；type 1；flags 1；reserved 1；`seq:uint32 LE`；`len:uint16 LE <=2048`；UTF-8 JSON对象；CRC32 IEEE校验 `version..payload`。总长 `16 + len`。协议类型见继承的 `docs/PROTOCOL.md`；附带 `reference/awg1_protocol.py` 是参考编解码器，不是完整USB运行服务。

**X5必需处理消息**：`HELLO/HELLO_ACK(01/02)`、`HEARTBEAT(03)`、`STATE_SNAPSHOT(04)`、`SNAPSHOT_REQUEST(06)`、`BUTTON_HIT(10)`、`START_GESTURE(12)`、`SCENE_SET(20)`、`CUE_PLAY(21)`、`COUNTDOWN_START(30)`、`COUNTDOWN_EVENT(31)`、`TIMER_EVENT(32)`、`ROUND_ARM(34)/ROUND_ARMED(35)`、`STEP_ARM(36)/STEP_ARMED(37)`、`INPUT_DRAINED(38)`、`ACK(7F)`、`ERROR(7E)`。类型数字为hex。

**必需关联键**：`device_id, boot_id, press_id, session_id, round_id, step_epoch, scene_id, request_id`。RAW按键到达时，不可简单按目前前端当前Mission归属；必须尊重ESP冻结的有效epoch及时间窗。

**两个时间基准**：ESP monotonic 微秒权威计分时钟；X5 monotonic本地供屏幕倒计时外插。用心跳收发时间估算偏移，但绝不可按浏览器Date.now()判定最后一击。X5本地时钟变更/手工调整不影响比赛。

**ACK真正语义**：可重发按键事务的ACK须在 **SQLite持久化后** 才给ESP；串口读到了但尚未保存不能ACK成功。场景命令超时可重发，但相同`request_id`必须幂等；`STEP_ARMED`而非普通ACK才代表新步骤开放。

### 4.1 60秒结算竞态

- ESP发 GO 并提供`t0_us`；截止=`t0_us+60_000_000`；物理候选时间 `raw_press_t_us`须 `< deadline`；经20ms稳定消抖后才成立。
- 倒计时归零后X5显示「正在结算」，**不得即时FINALIZE**；允许ESP后续发送截止前物理已落下、截止后才确认的事件。
- ESP `INPUT_DRAINED` 是最终收件屏障：要求该局所有合格HIT已持久化ACK且计数一致（不能只靠最大press_id判断）。
- 如果屏障在配置超时内没有完成，结果标记中断，不写正式榜。
- 如果同一步骤几乎同时拍两键，按 `(raw_press_t_us, button_id, press_id)` 排序；不能用第二键预先满足下一step。当前步骤的并行角色仅根据事先定义的 `frontier` 接受。

### 4.2 模拟硬件模式

`DEVICE_MODE=mock` 是首发开发刚需：注入与真实ESP同schema的 `HELLO`、`ROUND_ARMED`、`BUTTON_HIT`、`STEP_ARMED`、`INPUT_DRAINED`，不绕过 GameReducer。可对任意服务注入按击、延迟、丢包、坏CRC、超时事件、热拔插；绝不把模拟比赛写进正式赛事榜。所有 Mock HMI应展示醒目的DEMO状态。

## 5. Session状态机（后端唯一权威）

```text
BOOT → CONNECTING → IDLE → LOBBY → PREPARE
                                      ↓
                                WAIT_KEYS_RELEASED
                                      ↓
                                 COUNTDOWN
                                      ↓
                                     ACTIVE
                                      ↓
           ┌──── SOLUTION_RESULT / NEXT_ROUND (60s不断) ───┐
           │                                              │
           └──────────────────────────────────────────────┘
                                      ↓
                         EXPIRED → SETTLING → FINALIZED
                     └─ link error → INTERRUPTED (ranked)
           Guided/Free: PAUSED_LINK → RESUME or ABORT
```

每个状态记录 `state_revision` 并将其与赛题包 `pack_id / pack_hash / ruleset_version / scoring_version` 绑定。进入下一道Mission要生成新`round_id`；进入下一步要生成新`step_epoch`；`STEP_ARMED`应返回ESP的`accepted_from_us`。用 `ROUND_ARM`确保开局所有服务键先松开，防止按住拿分；切题不跨epoch自动计分。

`Kiro` 0号键职责：IDLE CLICK→Lobby；Lobby三种大模式按钮，实体EC2/ S3/ Lambda可作为快捷方式；FREE CLICK→Analyze、DOUBLE→Undo；RANKED中Kiro CLICK不产生得分、HOLD请求弃赛确认；Guided click可调暂停菜单；RESULT CLICK→大厅。**Kiro不参与NeoPixel**，普通内置灯能力由capabilities决定。

**同一时刻只能有一个ACTIVE session**。新玩家不能在上一局终态未提交时开赛。浏览器刷新不得创建第二个会话，UI POST动作需带幂等 `client_action_id`。

## 6. Solution / Graph规则引擎（核心差异化）

### 6.1 内容输入与版本

读取配置 `services.json` 16 Stable Keys、`solutions.json` 8+1个教学Mission、`game_config.json`，启动时进行严格校验（全部服务存在、DAG无循环、节点角色无重复ID、字符串有中英翻译、Ranked only eligible）。不允许会话进行中替换规则集；启动时按文件计算canonical hash绑定session；旧榜保持旧版本。

### 6.2 数据模型

`Mission` = nodes(service, role, required, after, node_type) + graph_edges(业务真实关系) + language hints + allowed variants + teaching points。选择一个Service并不天然规定其在架构中的连接方向。后台维护当前`selected_instances`、已满足`role_instance_ids`、依赖frontier、可选分支和候选图。

同一个服务可有多个逻辑实例（M07 `Lambda` producer/worker），自由模式需由HMI显式 `Add instance` 选择角色，而不以双击实体按钮隐式添加。CloudWatch/Cognito放辅助支路，不强行串到请求链尾。

### 6.3 Guided / Ranked / Free判定

- **Guided**：屏幕显示能力提示/业务故事；接收按键后根据可满足frontier判断正确/错误/可选；解释原因；有效节点在架构图出现，发灯光scene。动画不得改变计分截止时间。
- **Ranked**：从固定`pack_hash`序列载入Mission；只显示角色线索不显示实体服务答案；每个Step明确ARM，禁止跨步抢拍；所有有效节点/重复实例按规则正确推进；同包同评分版本才能比较。
- **Free**：按键第一次选择、第二次默认Toggle取消；Kiro提交Analyze；返回 `VALID_COMPLETE | VALID_VARIANT | VALID_PARTIAL | UNSUPPORTED`，展示最多3个候选与“已具备能力/仍需哪些角色”。无业务场景且多种方案匹配时**请玩家选目标**，不能任意编造唯一架构。

**特别注意**：`S3+Lambda+Rekognition` 只是图片智能处理的部分能力；添加DynamoDB可形成“持久化结果”的教学版；`Transcribe+Bedrock+Polly`可解释为三种核心能力但缺少编排角色；选满16个Logo不是合法架构的充分条件。

## 7. HMI交互与视觉规格

### 7.1 基准屏幕与布局

默认HDMI横屏1920×1080；所有页面CSS响应式支持1280×720，需在实机运行Chromium测试。UI以“游戏节奏和观众可见”为优先：大标题、中英文对照、充足负空间；AWS服务图标使用现成官方本地SVG，勿生成伪Logo；Kiro START面板UI文案可受品牌设置限制，避免禁用词印在物理面板上。

配色建议：背景深海军蓝，计时与START强调紫，判定正确用绿、错误用红、服务节点保留分类识别色。所有动画尊重 `reduce_motion`；不要全墙 >2Hz 高对比闪烁。

### 7.2 页面详细需求

| Page | 核心内容 | 实体/HMI互动 | Done条件 |
|---|---|---|---|
| `Attract` | 大字Kiro START引导、场次纪录、16服务墙缩略布局 | Kiro CLICK | 无网络可在5秒内识别起始入口 |
| `ModeLobby` | Guided/Free/Rush三个巨大卡片，玩法与时长两语说明 | 触摸或EC2/S3/Lambda快捷；Kiro确认 | 无触摸屏也能完成模式选择 |
| `MissionIntro` | 本次场景故事、目标、角色提示、简化架构背景 | Kiro进入/倒计时 | 非正式榜不泄露后台内部拓扑细节 |
| `Countdown` | 屏幕3/2/1/GO，配合16区域灯光 | ESP权威GO | 时间轴与ESP相同 |
| `Guided` | 当前能力线索、已完成节点、右侧Graph | 拍服务键 | 每步可解释、支持超时/错误提示 |
| `FreeCanvas` | 所选Logo、候选Solution、缺失组件、手动多实例与关系编辑 | 服务键Toggle、Kiro Analyze、HMI编辑 | 可得到多候选而非强行单解 |
| `RushHUD` | 60s、完成Solutions、分数、错误、Combo、当前角色、历史Ghost | 服务键按击 | 不泄露具体答案，高帧率不影响后台 |
| `BuildResult` | DAG按架构实际关系和分支呈现、为何合理、中英结论 | 结果页Kiro | 不误导实际部署完成 |
| `Leaderboard` | Top 10、玩家排名、同Pack比较、日榜/场榜 | Kiro回大厅 | 只显示合法结果，空榜正常呈现 |
| `Operator` | 17键/16区灯映射、供电状态（若有传感器）、USB/版本/恢复、赛事设置 | PIN/实体确认 | 正式赛中维护项禁用 |

### 7.3 适合围观的Rush HUD布局

```text
┌──────────────────────────────────────────────────┐
│  BUILDER RUSH 60       00:37.8      SOLUTIONS: 03 │
├─────────────────────────┬────────────────────────┤
│ CURRENT MISSION         │ ARCHITECTURE PREVIEW   │
│ AI VOICE ASSISTANT      │                         │
│ AI语音助手               │     [Transcribe]        │
│                         │          ↓              │
│ Next capability:        │       [Lambda]          │
│ 处理对话请求               │                         │
├─────────────────────────┴────────────────────────┤
│ SCORE 2550  COMBO x4  ERRORS 1   TOP BUILDER: 4  │
└──────────────────────────────────────────────────┘
```

**Ghost挑战**：基于历史同Pack前三/第一名的 `ghost_milestones(elapsed_ms, mission_index)` 画对手进度；不表示对方实时在线。不要拿不同Pack纪录当Ghost。

### 7.4 双语、Logo、字体与印刷约束

本地 `zh-CN`、`en-US` 文本存独立语言包，布局允许 `中文+English`同时显示；长的`Amazon Bedrock AgentCore`等名称做响应式换行。英文可使用有授权的字体；中文优先有合规开源授权的Noto Sans SC；**不能在项目包内非法分发Amazon Ember字体**。Logo必须由官方素材本地引入且符合品牌审核要求；资料使用权限按活动方确认，别通过算法自行重绘Logo。

## 8. HTTP / WebSocket 对接（供前端开发）

默认`127.0.0.1:8080`，前端与API同源，本地也加权限控制。API清单如下：

| Method | Path | 请求意图 | 返回 |
|---|---|---|---|
| GET | `/api/health` | 硬件与后台健康检查 | `device_online,boot_id,db_ok,...` |
| GET | `/api/snapshot` | 浏览器载入/重连的唯一状态快照 | 当前revision/session/mission/lighting |
| GET | `/api/content/services` | 16服务名、能力、官方Logo asset id | 所有服务的中英数据 |
| GET | `/api/content/missions` | Guided/Free任务简介；Ranked隐藏答案 | 面向用户的任务数据 |
| POST | `/api/mode/select` | Lobby改变模式 | `request_id, state_revision,mode` |
| POST | `/api/game/start` | 正式发起准备/ARM流程 | `session_id,state_revision` |
| POST | `/api/free/analyze` | Free解读（后端现有选集） | `status,candidates,missing_roles` |
| POST | `/api/free/instance` | 添加同服务的第二逻辑实例（经校验） | `node_instance_id` |
| GET | `/api/leaderboard?pack_id=...` | 同规则榜单 | Top N（默认10） |
| GET | `/api/result/{session_id}` | 完赛结果 | 可解释graph、score、achievement |
| POST | `/api/player/alias` | 设置自选昵称 | 名称合法化结果 |
| POST | `/api/admin/login` | Operator认证 | 仅本机session |
| POST | `/api/admin/test-panel` | 检查映射/灯光 | 禁止ACTIVE时调用 |
| POST | `/api/admin/config` | 亮度/映射/赛事规则 | 审计、禁用比赛中变更 |

所有POST状态修改带`client_action_id`防重复提交。输入全做schema校验，浏览器**绝对不可提交分数、完成Solution或UUID作为权威事实**。

`WS /ws/events` 推送：`device.state, game.lobby, game.countdown, game.step_updated, game.input_feedback, game.mission_completed, game.result_finalized, game.interrupted, leaderboard.updated, admin.fault`；每条含`server_seq,state_revision,session_id,round_id,step_epoch,payload`。浏览器丢帧或见到Revision间隙，立即获取snapshot再应用后续事件。低频时间同步≤10Hz，倒计时用浏览器monotonic插值但分数只以后端/ESP结算为准。

## 9. 排行榜、公平性与持久化

使用 `config/leaderboard_schema.sql`（原V1.2源内容）初始化SQLite，WAL模式，数据库默认 `/var/lib/aws-wall/wall.db`。至少存储 `sessions, raw_input_events, round_results, achievement_unlocks, ghost_milestones`。写事务中 `(device_id,boot_id,press_id)` 唯一约束；同一个round结果只写一次；`sessions.status`只允许终态单向迁移。

**正式成绩合法条件**：`mode=RUSH60_RANKED`、`status=VALID`、没有通信/映射/事件遗失问题、同`pack_id+pack_hash+ruleset_version+scoring_version+participant_class`、`INPUT_DRAINED`最终结算完成。

正式排行榜排序优先：`solutions_completed DESC`→`score DESC`→`invalid_hits ASC`→`last_completed_t_ms ASC`。日期分榜还需加入统一的`event_id/day_key`数据或单独映射，**当前原始V1.2 schema没有event_id字段**；新增迁移后才能实装每日/场次榜。不要以修改后的schema假装已实施迁移。

单独区分 Solo、Duel、Team 榜。Ghost显示历史轨迹，不参与即时判定。玩家昵称默认`BUILDER-xxxx`，允许匿名；不收手机号，隐藏/清理榜单有Operator权限。

### 9.1 建议额外迁移（实施时执行）

```sql
-- 与原V1.2 schema有意分开；数据库迁移版本v2
ALTER TABLE sessions ADD COLUMN event_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sessions ADD COLUMN day_key TEXT;
CREATE INDEX IF NOT EXISTS idx_event_rank ON sessions(
 event_id,day_key,mode,status,pack_id,pack_hash,ruleset_version,scoring_version,participant_class
);
```

数据库写入要检查SQLite `busy_timeout`、磁盘空间和意外断电恢复；数据写失败必须中断Ranked，而不是UI显示上榜成功。绝不自动把INTERRUPTED成绩修复为VALID。

## 10. 音效引擎和时间同步

推荐音频资产以本地WAV/OGG部署：`start, countdown3, countdown2, countdown1, go, hit_ok, hit_bad, combo, mission_complete, new_record, error, time_up`。音效由X5/HMI播放，不经过ESP；浏览器Web Audio的自动播放策略须**在自启动kiosk环境实测**，必要时改用后端本地音频服务。音效失败不得阻塞分数/游戏逻辑。音乐频率/音量上限现场可调整，减少噪声干扰。

倒计时与GO权威事件来自ESP。前端动画可提前排程（估算延时），但到达正式GO/EXPIRED需服从后台权威状态。不同浏览器/屏幕设备的时钟不能拿来比较排名。

## 11. Operator / 维护与故障恢复

Operator页面PIN保护（仅本机）；登陆超时、错误次数限流；不能在正式赛事ACTIVE状态下修改映射或直接测试LED。配置改动写审计日志与备份，重启重新加载后需验证CRC。

维护动作：16个Service按键＋1 Kiro逐一按键验证、每LED lane与服务槽位映射、总亮度限制、实际NeoPixel数、角色提示预览、连接错误统计、CRC错误数、波特/端口状态、最近100个事件、数据库存储、屏幕/声音、版本。若PCB无电流传感器，不能宣称能自动检测哪块灯箱熄灭。

崩溃/异常规则：ESP重启→Ranked作废；USB断线→Ranked作废；浏览器崩溃→后台继续，屏幕自恢复；Python后台崩溃→Ranked作废并重启服务；数据库IO错误→Ranked不入榜；卡键→待释放/暂停；亮度指令越界→拒绝且记录。

## 12. 部署、监控、升级与回滚

**推荐目录**：

```text
/opt/aws-wall/current/     # 当前发行版本，只读程序/前端静态资源
/opt/aws-wall/releases/    # 可回滚版本
/etc/aws-wall/config.yaml  # 本机GPIO/USB/赛事配置
/var/lib/aws-wall/wall.db  # SQLite持久数据及备份
/var/log/aws-wall/         # 可选；主要建议journald
```

systemd负责后端开机自启(`Restart=always`, `RestartSec=2`, `After=multi-user.target`)和kiosk等待后端ready。RDK上实际GUI会话、DISPLAY、XAUTHORITY与音频用户必须核实，不能把示例kiosk service无修改直接当生产部署。

部署必须支持 offline：依赖wheel文件/前端build提前打包，含完整版本锁；停服→备份SQLite→迁移→替换release原子软链→启动→健康检查→失败回滚；重大schema变更回滚需要兼容性迁移或DB备份恢复。

**X5实际运行检查**：`cat /etc/os-release`, `uname -a`, `lsusb`, `dmesg`, `ls -l /dev/serial/by-*`, `python3 --version`, `xrandr`（X11环境）, 音频设备信息；不使用猜测的设备号。

## 13. 测试与验收（X5部分）

### P0模拟自动化

- AWG1拆包、粘包、坏CRC、超长包、不完整UTF8、重复ACK/PressId、乱序Scene。
- Session/FSM/Kiro 手势入口、Step Arm epoch门禁，防抢拍；开始前键已按住无法免费得分。
- 60s边界59.995s候选+20ms确认有效、60.001s候选无效；收到`TIMER_EXPIRED`不立即Final，不完整`INPUT_DRAINED`不得上榜。
- Ranked失联/后台重启/映射变化/数据库写失败/输入队列溢出→INTERRUPTED。
- Free选择/取消、重复Lambda实例、`S3+Lambda+Rekognition`部分有效、多个候选与未知组合不乱报。
- 排位相同pack+score版本才能互比；不同Pack/参与类型隔离；Ghost在相同Pack下回放。
- 语言切换不打断会话；logo静态资产缺失给占位但不导致服务ID变化。

### P0实机验收

- X5 Type-A Host热插拔ESP10次以上无不可恢复阻塞；`udev`稳定路径；开机断网状态可玩。
- 17键与16灯独立诊断完成映射，硬件ID校准签字；设备时钟不同步时按键有效性正确。
- 1920×1080 1080P与常见低分辨率画面无溢出；中英双语/超长服务名可读；断网与桌面重启自动恢复。
- 连续8小时/100场仿真＋实拍；关键P0全绿；无双计分、跨题、ranked断线后续赛。
- 模拟20次系统异常结束后数据库可打开、Leaderboard正式成绩无损坏；有备份/回滚演练记录。

## 14. 明确拆分开发任务（可交给编码Agent）

| ID | 任务 | 前置 | Done |
|---|---|---|---|
| X5-00 | 冻结系统镜像/USB/显示/声音 | 实机 | 硬件事实表、环境脚本可执行 |
| X5-01 | AWG1 codec + USB Device Supervisor | X5-00 | CRC/断线/HELLO/ACK/snapshot自动测试通过 |
| X5-02 | MockDevice/Event Replay | X5-01 | 无ESP也可从Kiro到结果全流程 |
| X5-03 | EventStore+SQLite迁移与备份 | X5-01 | 唯一约束、故障回滚、事件重放 |
| X5-04 | SessionReducer+ARM/Timer结算 | X5-02,03 | Boundary/USB断线P0通过 |
| X5-05 | ConfigValidator+SolutionGraphEngine | X5-03 | DAG、角色、缺失、并行、Free多解测试 |
| X5-06 | REST/WS接口与Snapshot | X5-04,05 | 合约schema、权限、revision恢复 |
| X5-07 | HMI Attract/Lobby/Guided | X5-06 | Kiro→AI Voice全流程，不需鼠标 |
| X5-08 | HMI Free Canvas + Graph | X5-06,07 | 可选服务、添加实例、Analyze/Undo |
| X5-09 | Rush60/Fixed Pack/Score/Leaderboard | X5-04,05 | 排名公平、输入settle屏障、事务终态 |
| X5-10 | Ghost/成就/音效/结果海报 | X5-09 | 延迟回放正确、关音也正常 |
| X5-11 | Operator/权限/本地化品牌配置 | X5-07,09 | Calibration/诊断无破坏、非公开端点 |
| X5-12 | Kiosk+systemd+离线部署回滚 | X5-11 | 重启直达Attract、重连/断电验收 |
| X5-13 | 端到端压力/Fault Injection/现场手册 | 全部P0 | 8h/100局、P0无阻塞问题 |

### 建议里程碑

- M0：X5可枚举S3、按键事件进入Python、UI能反映按钮。
- M1：Guided AI Voice闭环（从Kiro开始到Solution完成的4个服务）。
- M2：Free Build候选/缺失、8套Mission可通。
- M3：Rush60 + 榜单 + 最后1ms正确结算。
- M4：展会版自动启动、断连/重启/无网稳定、运营入口。

## 15. 接口与硬件条件等待确认

1. X5系统镜像具体版本与桌面/Server版、浏览器是否预装。
2. 展会屏幕：横/竖、分辨率、是否触摸、音频输出设备。
3. S3 CDC VID/PID/unique serial、固定板USB口、供电隔离。
4. MCU硬件mapping crc、真实4 lane与每服务灯珠数量；确认普通按钮灯的电气能力。
5. 决定Ranked启用默认 `BASE-8-V1.2` 还是活动特供题包，锁定hash后不得中途变更。
6. 赛事日界线：`Asia/Shanghai`还是举办地点时区，活动主办方品牌词与Logo使用要求。

---

## 源文档与资料

- 《AWS Architecture Challenge V1.2 Complete Spec》：本专项必须继承其`PROTOCOL.md, GAME_DESIGN.md, STATE_SEQUENCES.md, services.json, solutions.json, game_config.json, schema.sql`。
- RDK X5官方接口文档：https://github.com/D-Robotics/rdk_doc/blob/main/docs/01_Quick_start/hardware_introduction/rdk_x5.md
- RDK X5显示使用文档：https://d-robotics.github.io/rdk_doc/en/Quick_start/display_use/display_rdkx5/
- RDK X5系统镜像说明：https://developer.d-robotics.cc/rdk_doc/en/Quick_start/download/
- ESP32-S3 USB CDC文档：https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/usb_device.html
