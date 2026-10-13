# AWS Architecture Challenge — Complete Development Specification V1.2

**Kiro START × 16 AWS Service Cards × ESP32-S3 (ESP-IDF) × USB × RDK X5 (Linux HMI)**  
**日期：2026-10-14 · 文档状态：开发规格已合并；并非已实现/实机验收通过**

> **设计目标**：将16张实体服务卡变成可玩的云架构教学游戏，所有模式离线运行：Guided Build、Free Build、Builder Rush 60（正式榜/练习），后续扩展Duel/Team。17个物理按键（Kiro独立入口且无NeoPixel），四路NeoPixel服务区；数据协议要求可靠、可解释、可调试。

## 使用方式与优先级

- 本文件是**完整合并规范**，各技术章节也在`docs/`中独立提供；根目录README包含文件导航和本地测试命令。
- **P0交付**：17键/四路灯带/USB、Kiro模式入口、Guided + Free + Rush60、Solution验证、排行与P0异常安全。
- **P1**：Ghost Pace、成就增强、运营工具；**P2**：Duel、Team、QR/本地LLM解释。
- 产品不调用AWS API、不实际部署资源；完成画面必须写`SIMULATED SOLUTION COMPLETE / 模拟架构构建完成`。
- 所有数字规格（例如24灯/面板、5V 10A、电源/PCB GPIO）在没有实测前只能作为**配置示例**。详见最后的OPEN_DECISIONS。

## 阅读导图

1. 系统职责、启动/失效状态与部署
2. 物理17键、逻辑ID/LED与供电接口
3. ESP↔X5 AWG1通信协议和多设备时钟裁决
4. 游戏玩法、规则图谱、计分与榜单
5. X5 HMI API及中英双语
6. 双设备握手与边界状态时序
7. 全量测试矩阵与开发任务/优先级
8. 原版本冲突合并决策及待确认硬件

---

---

# PART I — 系统架构

## 1. 硬件部署

```text
RDK X5 [USB Type-A HOST] --USB data cable--> ESP32-S3 [NATIVE USB DEVICE / TinyUSB CDC]
  |                                                   |
  | systemd backend / SQLite                           | 17 button GPIO inputs
  | rules / sessions / leaderboard                     | 4 RMT lanes -> 16 WS2812B service panels
  | WebSocket -> Chromium kiosk HMI                    | START = Kiro, independent dry contact
  +-- HDMI/DSI display + audio                          +-- optional ordinary button lamps (not WS2812)
```

X5运行Linux：`wall-backend`单进程独占 `/dev/aws-wall-mcu`，提供 `http://127.0.0.1:8080/`（样例端口）和同源`/ws`供HMI使用，SQLite持久化；HMI与串口必须进程解耦。X5 Type-A作为Host；S3 USB-C必须连接原生USB-OTG接口而非只供调试的USB-UART桥。USB CDC二进制消息端口不得输出日志。若自供电，要按Espressif官方要求考虑VBUS检测/电源路径，不能USB与外置5V直接硬并联。

## 2. Single Source of Truth

| 状态/时间 | 权威 | 备份/镜像 |
|---|---|---|
| 物理press_id、候选按下时间、去抖、按钮是否已松 | ESP32-S3 | X5事件日志 |
| 预备倒计时GO/60秒结束单调时钟 | ESP32-S3 | X5同步时间镜像（显示用） |
| 当前允许输入的`armed_context`和step_epoch | X5决定；ESP收到ARM后生效，ACK为边界 | 双方共同持有并校验 |
| Mission图谱、步骤、评分、合法组合 | X5 Backend | 只读UI |
| RGB帧/最大亮度/灯珠长度 | ESP32-S3 | X5声明高层`SCENE_SET` |
| Leaderboard与最终结果 | X5 SQLite事务 | UI只读 |
| 外部玩家身份 | 不必收集真实身份 | 可选匿名昵称 |

**不允许两套游戏主控**：ESP不写Solution匹配；X5不通过USB逐帧流式发送RGB像素。按键的即时本地短闪可由ESP渲染，但**这不代表击键已被认可**，只有X5验证后才更新已选/得分状态。

## 3. 逻辑模块

ESP-IDF组件：`board_support`、`input_scan`、`button_gesture`、`strip_engine`、`scene_engine`、`timer_engine`、`usb_transport`、`protocol`、`fault_manager`、`diag`、`nvs_config`。

X5模块：`serial_link`、`session_fsm`、`mission_catalog`、`rule_engine`、`graph_builder`、`scoring`、`leaderboard_store`、`realtime_ws`、`audio`、`admin`。

Frontend：`Idle`、`ModeLobby`、`MissionIntro`、`Guided`、`FreeBuilder`、`RushHUD`、`Result`、`Leaderboard`、`Operator`。`HMI`界面重载只重建视图，不重置后端权威会话。

## 4. 全局FSM

`BOOT → SELF_TEST → USB_WAIT → IDLE → MODE_LOBBY → PREPARE → COUNTDOWN → ACTIVE → SETTLING/RESULT → IDLE`

- `ACTIVE.mode`区分 `GUIDED`/`FREE`/`RUSH60_RANKED`/`RUSH60_PRACTICE`/`DUEL`/`TEAM`；V1.2优先实现前三种。
- 每次玩家会话有`session_id`；每个任务有`round_id`；每一步只有一个递增`step_epoch`；每次X5场景更新有递增`scene_id`。
- `PREPARE`和`STEP_ARM`都应确认上一阶段需要的实体按键已松开；未释放不算下一次击键。
- `ACTIVE`仅在握手、任务和GO有效之后接受击键；`RESULT`不接受Service击键；`LOBBY`中的EC2/S3/Lambda快捷模式键仅在LOBBY有菜单语义。
- 断线：Guided/Free可进入`PAUSED_LINK`并确认后恢复；Ranked/Duel官方赛一旦USB中断/ESP复位，直接`INTERRUPTED`不入榜。
- 当设备故障导致服务区域无法识别时应停止/中断正式竞技并明显提示；**未有电流/光传感器时不能自动证明灯箱坏了**。

## 5. FreeRTOS参考分工与非阻塞约束

- 输入扫描：约1ms一次，独立每键去抖；不可在GPIO ISR或输入Task中阻塞串口。
- USB RX：流式解析与命令队列，校验、CRC、限流；实际行为由单一游戏硬件调度任务提交。
- Scene：30fps起步，4 RMT数据路分别刷新；每个lane只一个持有者；动画可降帧，但按键扫描不受影响。
- Timer：`esp_timer_get_time`单调时钟、计时器期限与`INPUT_DRAINED`水位线。
- Health：每秒心跳、堆栈、队列水位、断开标志；任务Watchdog策略按真实硬件配置。
- 不应在长临界区或USB RX callback里直接刷新整条NeoPixel。

## 6. 设备启动/关机

1. S3先全灭/低亮安全状态，验证 NVS 与管脚布局CRC；不得开机直接全墙满白。
2. USB枚举：ESP发送HELLO，X5校验设备与版本，发HELLO_ACK，双方GET_SNAPSHOT；若主板mapping CRC不匹配进入OPERATOR而不是比赛。
3. X5规则数据经校验后读入内存，再开放Kiro进入LOBBY；规则数据损坏则回滚last-known-good或阻止比赛。
4. 断电后不自动续上次正式榜游戏；boot_id变化使未结算的正式局标记中断。
5. `systemd`启动后端与Chromium kiosk；后台崩溃自动重启，重启后对正在运行的正式局按异常规则中断，不凭旧前端状态续榜。

## 7. 本地网络和品牌

全部本地运行，不调用AWS API，不把游戏完成描述成实际部署完成；屏幕写“SIMULATED SOLUTION COMPLETE / 模拟架构构建完成”。现场如另有主办方对AWS字样/Logo规定，显示名采用独立locale/display_name映射，内部stable_key和图谱不受影响。Kiro作为独立游戏入口，不算第17项AWS Service，且其面板无NeoPixel。

## 8. 外部技术依据与锁版

- Espressif USB Device: https://docs.espressif.com/projects/esp-usb/en/latest/esp32s3/usb_device.html
- Espressif WS2812 component: https://components.espressif.com/components/espressif/led_strip
- RDK X5 hardware: https://github.com/D-Robotics/rdk_doc/blob/main/docs/01_Quick_start/hardware_introduction/rdk_x5.md
- 推荐在Bring-up时冻结 **具体ESP-IDF 5.x版本及 managed component版本**，并保存 `dependencies.lock`；不能把本文示例当成已核对硬件引脚。


---

# PART II — 硬件与固件

## 1. 已知与待确认

已知：单Service面板约200.4mm方形（`Sketch6.svg`几何）；16个Service+1个Kiro开始键；Service使用WS2812系列5V 60 LED/m；ESP32-S3 ESP-IDF控制，X5 USB连接；START没有NeoPixel。**未知**：每卡最终灯珠数(旧记录中曾讨论32/24)、GPIO及具体开发板、PCB开关输入、是否带独立普通LED、额定电源与线束实物、电气连接类型。若实测与此文冲突，调整`hardware.json`和PCB，而不是篡改逻辑服务ID。

## 2. 16 Service Stable IDs（逻辑永久不随物理位置变）

| id | key | en | zh | slot |
|--:|---|---|---|---|
| 0 | KIRO_START | Kiro START | 开始构建 | START |
| 1 | EC2 | Amazon EC2 | 弹性计算 | A1 |
| 2 | S3 | Amazon S3 | 对象存储 | A2 |
| 3 | LAMBDA | AWS Lambda | 无服务器计算 | A3 |
| 4 | DYNAMODB | Amazon DynamoDB | NoSQL数据库 | A4 |
| 5 | API_GATEWAY | Amazon API Gateway | API 管理 | B1 |
| 6 | CLOUDFRONT | Amazon CloudFront | 内容分发 | B2 |
| 7 | IOT_CORE | AWS IoT Core | 物联网 | B3 |
| 8 | SQS | Amazon SQS | 消息队列 | B4 |
| 9 | BEDROCK | Amazon Bedrock | 生成式 AI | C1 |
|10 | AGENTCORE | Amazon Bedrock AgentCore | AI 智能体 | C2 |
|11 | SAGEMAKER_AI | Amazon SageMaker AI | 机器学习 | C3 |
|12 | REKOGNITION | Amazon Rekognition | 计算机视觉 | C4 |
|13 | TRANSCRIBE | Amazon Transcribe | 语音识别 | D1 |
|14 | POLLY | Amazon Polly | 语音合成 | D2 |
|15 | CLOUDWATCH | Amazon CloudWatch | 可观测性 | D3 |
|16 | COGNITO | Amazon Cognito | 身份认证 | D4 |

`A/B/C/D`标识4个2×2分组，**不是正面四行编号**。真正视觉4×4的row,column，须另有`display_grid`以现场安装为准；不要用组件编号猜列位。

## 3. 输入线路

机械按钮常开触点(NO)与GND形成低电平触发；优先外部10k上拉到3.3V、1k串联+100nF滤波示例，软件周期1ms、稳定20ms。ESP不承受外置12V按钮灯电流，必须完全分离。GPIO引脚待按实际ESP32-S3 PCB/开发板冻结：USB原生GPIO19/20不可占，Flash/PSRAM/启动相关脚需校验。GPIO不够时才引入MCP23017，需修改板级抽象和IRQ/采样方案。

## 4. LED与灯箱

- 4路ESP32 RMT：lane A/B/C/D，各路4个服务段串行`DIN→DOUT`；每组5V/GND星型并联，供电不依赖灯带上细铜箔的前后级穿越。
- `first_pixel/count/color_order`按实际安装写入配置与mapping校验，不能假设24/32颗永远成立。
- Espressif `led_strip`组件或等价IDF RMT实现，建议30fps，避免与输入、USB共享长时锁。
- 3.3V控制数据经过5V供电SN74AHCT125转换，数据串联电阻/去耦；长线真实示波/灯效测试，通讯地与LED电源参考地共地。
- LED语义：`OFF`、`AVAILABLE`(静态弱亮)、`TARGET_HINT`(Guided专用)、`PRESSED`(即时局部确认)、`ACCEPTED`、`REJECTED`、`SELECTED_FREE`、`COMBO`、`COMPLETE`、`LAST10`、`LINK_LOST`、`FAULT`。一个场景以原子方式取代旧状态，overlay cue按期限到期复位。
- 模式大厅尽量只亮当前菜单相关分组；Kiro START无NeoPixel，采用印刷箭头和X5提示，若按键自带普通灯需另测规格、加驱动、feature flag。

## 5. 电源/灯效限额

传统WS2812按 `60mA/颗` 估全白满亮上限；假设24颗/面板、384颗全墙，理论上限23A@5V；所以“正常只有一个区亮”**不能作为无条件供电上限**，因为完成场景会有多个卡牌保留发光。候选5V 10A电源须结合全墙实测、亮度上限和受限灯效使用；固件执行global brightness cap=25%与软件估算电流预算，所有全白测试须受控；硬件保险和导线额定能力按实际选型。

建议：四个 HUB分别供电+保险、主板逻辑电源独立保护、最大电流对接连接器额定值，主供电USB防反灌，PCB大电流分区布铜，不从USB线传灯带电流。分组断路只能保证故障隔离，若前段NeoPixel数据链断开，同组后续灯可能不亮。

## 6. 灯光层级与3-2-1

最高至最低：`SAFETY_FAULT > LINK_LOST > COUNTDOWN/TIMEOUT > PRESS_FEEDBACK > COMPLETED_SOLUTIONS > AVAILABLE/IDLE`。计数3/2/1用4组服务区呈现“周边向内收缩”的独立灯效；对高闪烁敏感观众提供reduce_motion模式，快速闪烁不超过2Hz；60秒最后10秒由HMI数字和**不泄露答案的全区低频**提示，而不是用目标灯指出正确按键。

## 7. 校准与配对

正式比赛前逐一测试：① HMI显示`A1`与`EC2`对应；②按物理EC2记录id1；③点亮lane A段1验证面板图标；④按键释放后重测；⑤重复至16服务；⑥Kiro id0。保存`physical_slot→service_key→(input_pin,led_lane,first,count)`于X5和ESP一致版本，记录`mapping_crc32`。不一致时只允许OPERATOR校准，拒绝Ranked。

## 8. 控制层接口（固件内部）

```c
// 仅接口契约示例，不代表可直接编译的ESP-IDF项目
void hw_init_from_config(const hw_config_t *cfg);
void input_scan_tick(uint64_t now_us);  // 1ms扫描，非阻塞
bool input_pop_event(input_event_t *out);
esp_err_t panel_scene_apply(const scene_t *scene); // 16区原子场景更新
esp_err_t cue_play(const cue_t *cue);              // 非阻塞，返回job id
void timer_tick(uint64_t now_us);
uint64_t now_monotonic_us(void);
```

## 9. 验收前置

- 每个按键按100次，稳定单击只计一次；按住不松无重复；16键并发输入事件可追踪；
- 最亮非额定极限场景测电源电压/温升/线束；
- START断开NeoPixel仍完整可用；若无独立灯，`LAMP_SET`应`ERR_UNSUPPORTED`；
- 连续8小时至少100局稳定、断电重启安全暗态。


---

# PART III — USB通信协议

## 1. 版本兼容性与线路

**保留 V1.0 `AWG1` 二进制帧**，新增 `proto_minor=2` 和消息种类；没有静默变更旧消息含义的许可。发送时版本字节仍是`1`，HELLO的minor升级为`2`，X5要求`proto_minor>=2`才可进行正式排位。既有V1.0主机若不认识`ROUND_ARM/INPUT_DRAINED`只能进入非竞技诊断；本项目没有无条件兼容旧固件的诉求。

ESP32-S3作为原生USB CDC-ACM Device，RDK X5 Type-A作为Host。Linux建立稳定设备路径（`udev`按vendor/product/serial或`/dev/serial/by-path`）；`/dev/ttyACM0`仅临时调试；协议口绝不可混入`ESP_LOGI()`文字日志。一个后台进程独占USB，不允许浏览器直接读串口。

## 2. 帧封装 AWG1（小端）

```text
OFFSET  SIZE  FIELD
0       2    magic [0xA5,0x5A]
2       1    major_version 1
3       1    msg_type
4       1    flags [0:ack_required, 1:is_response]
5       1    reserved 0
6       4    seq u32 little endian
10      2    payload_len u16 little endian <= 2048
12      N    UTF-8 JSON object
12+N    4    crc32 IEEE over bytes OFFSET 2 .. OFFSET 11+N (不含magic和crc自身)
```

完整包字节数 `16 + N`。RX解析器必须处理任意拆包、粘包、非法UTF-8、超长帧、未知version/type、CRC损坏与magic同步恢复。生产限额：payload 2048 byte；单条服务区`SCENE_SET`含16区状态在此限额内；未知枚举值拒绝不执行。发送 seq 各端独立计数，每次启动可以从1重新计数，因此去重使用 `(device_id,boot_id,press_id)` / `(session_id,request_id)`，不使用裸 seq 去重跨启动事件。

## 3. 消息注册表（协议类型ID冻结）

| Hex | 名称 | 方向 | Reliable? | 用途 |
|---|---|---|---|---|
| 01 | HELLO | ESP→X5 | Y | 版本、capabilities、boot_id、mapping_crc |
| 02 | HELLO_ACK | X5→ESP | Y | host、版本接受、心跳频率 |
| 03 | HEARTBEAT | ↔ | N | 连接活性、monotonic时间估计 |
| 04 | STATE_SNAPSHOT | ESP→X5 | Y | 物理输入、scene、timer、armed上下文和故障 |
| 05 | CONFIG_SET | X5→ESP | Y | 仅OPERATOR模式，可调亮度、布局等 |
| 06 | SNAPSHOT_REQUEST | X5→ESP | Y | 请求完整快照 |
| 10 | BUTTON_HIT | ESP→X5 | Y | 经去抖稳定确认的一次按击 |
| 11 | BUTTON_RELEASE | ESP→X5 | N | 松开通知，可用于诊断/等待ARM |
| 12 | START_GESTURE | ESP→X5 | Y | Kiro CLICK / DOUBLE / HOLD |
| 20 | SCENE_SET | X5→ESP | Y | 16服务全部状态原子替换（scene_id递增） |
| 21 | CUE_PLAY | X5→ESP | Y | 指定短时视觉反馈，绝不直接决定得分 |
| 22 | SCENE_CLEAR | X5→ESP | Y | 熄灭/回IDLE |
| 23 | LAMP_SET | X5→ESP | Y | 可选普通按钮灯；不存在则ERR_UNSUPPORTED |
| 30 | COUNTDOWN_START | X5→ESP | Y | 预备倒计时及游戏时长参数（非开放输入授权） |
| 31 | COUNTDOWN_EVENT | ESP→X5 | Y | 3/2/1/GO事件 |
| 32 | TIMER_EVENT | ESP→X5 | Y | GO、EXPIRED、剩余时间 |
| 33 | TIMER_CONTROL | X5→ESP | Y | 取消/非排行暂停/恢复 |
| 34 | ROUND_ARM | X5→ESP | Y | 指定游戏与候选键释放前提，准备GO |
| 35 | ROUND_ARMED | ESP→X5 | Y | 报告映射有效/键已松与GO安排情况 |
| 36 | STEP_ARM | X5→ESP | Y | 单一步骤/任务接受输入授权；含step_epoch与accepted_from_us |
| 37 | STEP_ARMED | ESP→X5 | Y | 确认新epoch生效并给单调时间边界 |
| 38 | INPUT_DRAINED | ESP→X5 | Y | 物理最后一击稳定判定、最终HIT事件均已入可靠发送队列并给最终press_id；仅用于计时结算屏障 |
| 39 | RESULT_ACK | X5→ESP | Y | 主机确认终态会话（非成绩本身） |
| 40 | SELF_TEST | X5→ESP | Y | 操作员模式硬件诊断 |
| 41 | DIAG_RESULT | ESP→X5 | Y | 诊断结果 |
| 7E | ERROR | ↔ | N | schema/状态/请求/能力错误 |
| 7F | ACK | ↔ | N | 帧可靠接收确认，携`ack_seq`, `request_id`, `status` |

**注意**：上表中十六进制类型例如 `10` 代表 `0x10`，不是十进制10。具体帧中只传1byte类型值。`ACK`表示命令已在指定语义阶段处理；`STEP_ARMED`才表示新STEP开始接受计分，`COUNTDOWN_START`的ACK并不表示GO已经发生。

## 4. 各端序列与状态防窜题

稳定标识：`device_id`、`boot_id`、`session_id`、`round_id`、`step_epoch`、`scene_id`、`request_id`、`press_id`。

- `boot_id` 每次MCU上电/复位重新生成；同一设备跨重启不得复用以推断是同一次按击。
- `press_id` MCU每次去抖成功单调递增（u64推荐）；一次持续按住只触发一次，松开才允许下一击。
- `round_id` 每个Mission独立，不能与ranked整个session混淆；`step_epoch`每次接受输入范围变化而递增。
- `scene_id` 同一session严格递增；过时场景返回`STALE_SCENE`且不覆盖当前显示。
- X5必须把收到的`BUTTON_HIT`关联**ESP在拍击候选时冻结的armed上下文**，而不是关联“消息到达时”X5正在播放的新题。
- 同一时间戳两次不同按钮：按 `(raw_t_us, button_id, press_id)` 稳定排序；**仅当其拍击时间位于已ARM且合法的步骤/角色窗口才可能得分**，不能按同时按键的顺序偷偷跨步完成。

## 5. 推荐 JSON Payload

HELLO：
```json
{"device_id":"wall-mcu-01","boot_id":"9cf31b2a","fw":"1.2.0","proto_major":1,"proto_minor":2,"mapping_crc32":"D4E3A129","button_count":17,"service_count":16,"capabilities":{"rmt_lanes":4,"start_neopixel":false,"button_lamps":false,"countdown":true,"raw_press_time":true}}
```

ROUND_ARM：
```json
{"session_id":"s101","round_id":"r1","request_id":"arm-1","mode":"RUSH60_RANKED","require_all_released":true,"ruleset_hash":"sha256:...","pack_id":"EVENT-20261014-A","duration_ms":60000}
```

ROUND_ARMED：
```json
{"session_id":"s101","round_id":"r1","request_id":"arm-1","ready":true,"all_released":true,"mapping_crc32":"D4E3A129","t_us":81200223}
```

STEP_ARM：
```json
{"session_id":"s101","round_id":"r1","request_id":"step-2","step_epoch":2,"require_release":true,"allowed_button_ids":[3],"deadline_us":144000223}
```

`allowed_button_ids` 是**硬件计分窗口门禁**的可选白名单。对于 Guided/Free 可省略或放16个服务键；Ranked 出于防作弊原则，**不得让该字段/其灯光直接泄露答案**：正式竞技下请改为`allowed_button_ids`:全部16个，硬件只管时窗，业务正确性由X5判定。上述单一ID仅为协议功能举例。

STEP_ARMED：
```json
{"session_id":"s101","round_id":"r1","step_epoch":2,"accepted_from_us":83100000,"held_buttons":[],"ready":true}
```

BUTTON_HIT：
```json
{"device_id":"wall-mcu-01","boot_id":"9cf31b2a","session_id":"s101","round_id":"r1","step_epoch":2,"press_id":804,"button_id":3,"service_key":"LAMBDA","raw_press_t_us":83230400,"confirmed_t_us":83250400,"mapping_version":4}
```

COUNTDOWN_START：
```json
{"session_id":"s101","round_id":"r1","request_id":"timer-1","pre_countdown_ms":3000,"game_duration_ms":60000,"policy":"INVALIDATE_ON_USB_LOSS"}
```

TIMER_EVENT：
```json
{"session_id":"s101","round_id":"r1","event":"EXPIRED","deadline_us":144000223}
```

INPUT_DRAINED：
```json
{"session_id":"s101","round_id":"r1","deadline_us":144000223,"input_confirmed_through_us":144040223,"final_press_id":855,"input_event_count":22,"all_hit_events_acked":true}
```

SCENE_SET：
```json
{"session_id":"s101","round_id":"r1","request_id":"scene-114","scene_id":114,"default_state":"OFF","brightness_cap":0.25,"panels":[{"id":3,"state":"ACCEPTED"},{"id":10,"state":"AVAILABLE"}]}
```

ACK：
```json
{"ack_seq":1148,"request_id":"scene-114","status":"OK","applied_scene_id":114}
```

状态事件必须做 schema 校验：无效button_id、超长字符串、不存在状态、超界亮度、非法计时均拒绝；不要直接信任来自浏览器的JSON。

## 6. GO、步骤ARM与60秒判定（强制统一）

1. X5准备session、`pack_id`、映射CRC；`ROUND_ARM`等待所有服务键释放；有任一键卡住则不启动正式挑战。
2. X5预先发出当前任务首步`STEP_ARM`，ESP记录首步epoch并等待GO门禁，然后X5发送`COUNTDOWN_START`，ESP产生3/2/1准备倒计时；GO实际时刻`t0_us`由ESP产生，`deadline_us=t0_us+60_000_000`。HMI只用ESP时间映射显示。
3. 正式赛输入准入：按钮原始候选时间`t_raw >= armed_at_us`、`t_raw >= t0_us`且` t_raw < deadline_us`；稳定20ms确认后才生成HIT；失败消抖候选永远无效。
4. **在截止前5ms落下，截止后15ms确认**：有效（以t_raw判定）；截止后1ms才落下：无效。
5. 到时ESP立刻停止新窗口，进入`SETTLING`，继续确认截止前候选按击（示例消抖20ms，最多预留40ms稳定判断）。所有已确认HIT进入可靠发送队列，**并等待X5对这些HIT的可靠接收/持久化ACK**，再发送`INPUT_DRAINED`尾水位线；不能只以最大press_id猜测有无丢事件。
6. X5在收到`INPUT_DRAINED`前不提交最终成绩；还需确认事件数量等于`input_event_count`（按此round适用的稳定按击计数）、所有HIT都已去重持久化并按时间排序，或者因丢包/超时标记中断。`INPUT_DRAINED`消息必须在所有对应HIT已获得X5端持久化ACK后才作为有效结算屏障（ACK/replay保护），不能只是先排一个普通日志消息。
7. X5使用SQLite事务一次性`FINALIZE`。END时长60秒不因动画、网络故障或串口延迟延长。
8. 每一题/Step切换：旧epoch取消 → 等待必要按钮释放 → X5下发新`STEP_ARM` → S3 ACK `STEP_ARMED` → 新epoch计分。过渡按击记为`IGNORED_TRANSITION`、提示但不记为下一题正确；尽量缩短可视化空档。
9. 为减少不公平的等待，在Ranked**全程60秒计时不因过渡、动画而暂停**；完成动画≤800ms，可后台切换题，但必须让玩家明确何时可开始下一题。

### STEP epoch与并发击键的冲突说明

S3只能识别物理时间与其当前窗口，无法推断X5复杂DAG中哪个逻辑角色合法。为了公平，Ranked X5对物理多按进行一次**同step批次归属**：在该epoch内发生的若干press全部记录，但仅规则允许的第一个有效角色能推动当前step；同epoch后续按击不能预先满足step_epoch+1。对于允许并行的分支节点，必须由任务预先定义`frontier`，X5可接受同epoch内多个不同服务作为并行节点，且保证结果确定性。超快拍击不可将无效顺序合成为多步Solution。

## 7. ACK/重试、缓存、断连

- 可靠命令建议超时150ms、最多3次，总超时约1s作为本地起点，**所有请求幂等**；`(session_id,request_id)`相同应返回同一结果，不得重复启动timer/cue。
- `BUTTON_HIT`可靠送达，发送队列最少64条（实机调优）；`press_id`去重；队列满不能悄悄覆盖未确认按击，Ranked转`INPUT_OVERFLOW`并中断。
- ACK/心跳是高优先级；场景CUE可以降级或丢弃过时scene（不得丢计分事件）。
- 心跳1s、3s超时为参考阈值；USB物理失联/MCU重启或关键事件无法确认时正式Ranked直接`INTERRUPTED`，不从PAUSED_LINK续榜。
- Guided/Free可暂停并恢复，但`boot_id`变更必须用户确认重新开始，并明确显示是否保留Free选中列表。
- 进程/浏览器重启：HMI刷新不影响X5后台；后台进程重启时正式Ranked标记中断。
- 事件时间来自同一ESP boot的`esp_timer_get_time()`，不同boot的时间戳不可直接比较；每次启动生成新的boot_id。
- 断线后旧`session_id/round_id/scene_id`不能复活新玩家回合。

## 8. Kiro START手势

- 独立输入ID=0；**无NeoPixel**。
- 消抖约20ms；CLICK 延迟判定窗口300ms；DOUBLE 两次click间隔≤300ms；HOLD≥2000ms，长按事件独占，不得再触发单击；物理释放才重新可用。
- 默认大厅：CLICK打开/确认模式；Service EC2=Guided、S3=Free、Lambda=Rush60快捷，仅在LOBBY用作菜单控制。HMI优先触摸选模式。
- Free CLICK=`Analyze`，DOUBLE=`Undo`；Guided CLICK=暂停菜单；Ranked ACTIVE CLICK不影响提示、计时、任务和计分，HOLD仅申请弃赛确认；RESULT CLICK=返回大厅。后台必须校验状态，不以ESP手势类型直接修改业务。
- 双击不应执行先发生的单击动作；选择加入点击延迟或状态显示明确等待。

## 9. 灯光命令契约与异常

16区域逻辑状态：`OFF,AVAILABLE,TARGET_HINT,PRESSED,ACCEPTED,REJECTED,SELECTED_FREE,COMBO,COMPLETE,LAST10,LINK_LOST,FAULT`。scene完整声明16区域默认态和覆盖态，并按`scene_id`原子替换；短CUE叠加后恢复下层场景。硬性亮度封顶由MCU执行；若X5要求过亮应拒绝或截断并上报。无物理按钮灯驱动时`LAMP_SET`返回`ERR_UNSUPPORTED`，不得假ACK。最后10秒提示不能泄露Ranked正确服务。

## 10. 推荐错误码

`BAD_CRC`, `BAD_FRAME`, `BAD_JSON`, `VERSION_MISMATCH`, `UNSUPPORTED`, `BAD_STATE`, `BAD_SESSION`, `STALE_EPOCH`, `STALE_SCENE`, `MAP_MISMATCH`, `BUTTON_STUCK`, `INPUT_OVERFLOW`, `FAULT_POWER`, `LINK_LOST`, `ERR_UNSUPPORTED`, `RESULT_ALREADY_FINALIZED`, `RULESET_INVALID`。

## 11. 协议测试清单

见 `TEST_PLAN.md`。至少：空包、半包、粘包、CRC损坏后复位、长度超限、重复HIT、旧SESSION注入、逆序SCENE、100次USB插拔、倒计时边界、HIT和TIME_EXPIRED到达顺序颠倒、STEP_ARM和SCENE_SET的跨序乱序。


---

# PART IV — Solution及Gamification

## 1. 产品定义

Physical BuilderCards，不是随便亮灯的打地鼠。通过16张实体服务卡模拟搭建**有向图**；每次“构建”代表教育用简化Solution，而不是云端已部署应用。界面默认中英文兼容，现场品牌用词支持单独审核替换。

## 2. 模式与Kiro统一手势

| 当前状态 | Kiro单击 | 双击 | 长按≥2s |
|---|---|---|---|
| IDLE | 进入模式大厅 | 无效 | 受控OPERATOR入口 |
| LOBBY | 确认模式并开始 | 切换模式(可选) | 退出大厅 |
| GUIDED | 暂停选项 | UNDO(仅任务允许) | 退出确认 |
| FREE | 分析组合 | 撤销最后一次操作 | 退出确认 |
| RUSH_RANKED | 无计分效果/只显示状态 | 无动作 | 弃赛确认、不暂停时间 |
| RESULT | 下一局/回大厅 | 无动作 | 退出 |

LOBBY可选快捷键：`EC2=GUIDED`、`S3=FREE`、`LAMBDA=RUSH60_RANKED`、`DYNAMODB=DUEL`（后续）；**只在大厅**有菜单语义，游戏内仍是服务卡。一次单击要等待300ms双击窗口，避免单击后反悔；长按不能额外生成click。

## 3. Guided Build

随机选择一个已验证的Mission，RDK X5以故事+每一步能力提示引导玩家；接受按`frontier`已满足前驱的节点；EASY允许弱目标灯提示，NORMAL只给角色短语，ADVANCED只给目标输入/输出。接受的卡以分类色保留，错误短红闪、说明原因。完成节点集后显示图谱和中英解释。奖励教学徽章，不进入正式Rush榜。

## 4. Free Build

玩家按Service→Toggle选择集合，按Kiro单击提交`ANALYZE`；X5按当前服务集、可能的角色映射和有向边推理最多3种候选，返回`VALID_COMPLETE`、`VALID_PARTIAL`、`VALID_VARIANT`、`UNSUPPORTED`。不能把未知组合宣判“在云端不可能”。`CloudWatch`通常作为观测分支；`Cognito`认证分支，不是强行数据流尾部。

Free Build单个物理Lambda代表选择一种服务，不等于一个“Lambda节点”；如必须添加同一Service的多个角色，X5 HMI提供`Add Instance`与明确角色选择，不能用盲连拍猜意图。选择16个服务不自动判完成；规则引擎必须解释具体场景、最短必要角色、依赖/连接和缺失组件，最终用户确认候选场景才颁“构建完成”成就。

**推荐匹配流程**：
1. 按当前已选集合筛选Mission/Variant的必要节点服务是否是子集；2. 根据必要节点“多重集合”与角色关系识别已有/缺失，不只`set()`；3. 构建角色图并验证依赖DAG，输出`confidence`仅用于排序而非真假；4. 无法确定方向时请求HMI选择业务场景；5. 图谱完成经模板和依赖检验后才奖励。以`required_count/total_required_count`作为进度，但**比例不代表部署成功概率**。

## 5. Rush 60 竞技（V1.2唯一权威）

- 标准榜使用不可变`pack_id`和`pack_hash`；同一榜单 `challenge_pack, ruleset_version, scoring_version, difficulty/prompt policy, participant_class`必须相同。
- 3秒预备倒计时不计入60秒。ESP提供GO与strict deadline；按键raw按下时间在 `[GO, deadline)`、稳定消抖成功才算；最后按键可能在结束后被确认，需要等待`INPUT_DRAINED`结算。
- 固定任务顺序、公平提示；Practice可随机题并高亮正确面板，但**不得进正式榜**。
- 排名优先：`solutions_completed DESC, score DESC, invalid_hits ASC, last_completed_t_ms ASC`；并列在UI注明，不用玩家昵称偷偷排序技能高低。
- 分数：有效逻辑节点`+100`；Solution完成`+300`；连击从第二击起额外`min((streak-1)*20,100)`；错误`-50`，显示总分不低于0；排行榜首位仍是完成Solution数量。
- 禁止通过拔USB冻结时间、按住键刷多个击键、上一题动画提前完成下一题；Ranked断连/硬件重启/事件队列溢出标`INTERRUPTED`且不得上榜。
- 每完成一个Solution光效≤800ms，时钟继续走，下一Mission需新的`round_id/STEP_ARM`且显示其已就绪。题包到末尾标`PACK_CLEARED`并停止，不能无限重复简单题。
- 可选节点加分只有在题包事先固定时启用，避免赛道不公平。最初Ranked建议只计强制节点，选中CloudWatch之类无额外加分。
- **Ghost Pace**可显示历史榜首在同一固定题包中第t秒完成多少项，需有历史进度轨迹；不是另一个玩家的实时输入。

## 6. Duel/Team（独立赛道，P2）

DUEL两名玩家**顺序**打相同pack，不用一个墙同时比赛；存储`match_id,session_a,session_b,winner`，不与单人榜混排。TEAM支持多人协作完成一个方案，但17键无法识别各自手的身份，不设计个人归属统计；若竞技，团队人数/时长和pack分榜。合作模式注意玩家身体安全，不设计鼓励冲撞的玩法。

## 7. 成就（需图谱证据）

- FIRST BUILD：第一次验证完整有效Solution；
- SERVERLESS MAKER：完成可解释的无服务器Web类方案；
- AGENT BUILDER：AgentCore+Bedrock带Agent Runtime的有效架构；
- VOICE WIZARD：语音输入→模型→语音输出的完整工作流；
- IoT CONNECTOR：IoT设备连接、处理、存储的完整架构；
- ARCHITECT EXPLORER：至少5种不同Mission类型完成记录（无跨会话身份时仅本会话统计）。

这些成就是**游戏徽章，不是 AWS 官方证书**。可匿名昵称，允许清除纪录/管理员管理；不用手机号/微信实名才能参与。

## 8. Solution内容与角色图谱

`config/solutions.json`包含8个基础任务、不可变节点ID、service key、role、required、depends_on和bilingual解释。**DAG不等于所有服务严格串行**：静态S3/CloudFront分支和Web API/DynamoDB分支并存；CloudWatch观测节点是aux而不是业务数据下游；AgentCore运行Agent并调用Bedrock模型。M07的两次Lambda是两个`node_id`，同一个实体按钮，必须释放后第二次按下且新step已ARM。

约束：必需节点服务可以重复，但`node_id`唯一、依赖必须引用存在的`node_id`、全图无环、每步角色提示中英齐全、每个Mission有至少一项训练内容。多解架构不能按服务集合自动猜唯一走向：要么预定义variant并附能力解释，要么返回候选供玩家选择。AI自然语言模型如后续加入，仅参与解释，不能作为未经校验的竞技裁决。

## 9. HMI 页面和屏幕行为

1. `IDLE`：Kiro起点提示、TOP5、当前纪录；
2. `MODE_LOBBY`：三个大模式选项与快捷键提示；
3. `MISSION_INTRO`：故事、输入/输出、规则；
4. `COUNTDOWN`：3→2→1→GO；
5. `GAME_ACTIVE`：当前能力角色、实体卡提示、已完成图谱、错误说明；
6. `FREE_ANALYSIS`：最多三候选、已有节点/缺失服务/分支说明；
7. `RUSH_HUD`：60秒计时、已完成Solution数量、积分、错误数、Ghost进度；
8. `RESULT`：VALID/INTERRUPTED明确区分、成绩、完赛时间、成就；
9. `LEADERBOARD`：Today/Event/AllTime（同组政策）、匿名前10；
10. `OPERATOR`：按键/灯带映射测试、故障、协议版本、维护日志。

双语：物理面板英文为主、中文辅助，HMI支持中文/英文切换。中英内容显示从国际`official_en`和本地`display_name_cn_event`读取，不自动把`AWS`字符串全换成`Amazon`；Kiro独立面板可按活动规范不出现AWS字样。结果屏明确写“SIMULATED SOLUTION COMPLETE / 模拟架构构建完成”。

## 10. SQLite排行榜事务要求

- 仅`state=VALID, mode=RUSH60_RANKED`且相同`pack_id+pack_hash+ruleset+scoring+participant_class`同榜；
- 事件日志唯一`(boot_id,press_id)`，同一会话结果只提交一次，后端使用事务与unique key；
- 排行榜绝不信任浏览器上传的分数；由权威输入事件+规则引擎重算；
- 同昵称不等于同一个人；提供匿名编号和可选昵称，防HTML脚本和过长输入；
- 今天榜以**活动现场设置的时区**界定而不是随意按UTC切；日终规则版本可保留以追溯；
- 无公网时结果QR不可承诺手机必能打开，V1.2默认屏幕拍照友好成绩卡，联网/AP分享作为后续。

## 11. 排名示例

玩家A完成4套分数2400，玩家B完成3套分数2900：A领先，因为完整Solution数是第一指标。若都4套则比分数，再比较错误数/最后完成时间；DUEL和TEAM与单人榜分开展示。所有示例为虚构演示数据。


---

# PART V — X5 HMI后台接口

## 1. 部署选择

- `wall-backend`仅本机监听 `127.0.0.1:8080`（实例端口）；HMI以同源Chromium kiosk访问，USB串口由Backend独占。
- 固件协议与HMI API是**两种不同接口**。前端不传USB二进制帧，也不能直接宣称成绩。
- 如果后续开放局域网设备访问，必须额外设计认证、CORS/Origin、CSRF/限流和隐私边界；V1.2默认离线localhost访问。

## 2. 建议 HTTP API

| Method | Path | 用途 | 数据来源/权限 |
|---|---|---|---|
| GET | `/api/health` | 设备/后端/USB/HMI健康状态 | 公共只读 |
| GET | `/api/snapshot` | 当前会话、模式、任务、计时、16灯牌状态 | 公共只读 |
| GET | `/api/content/services` | 官方名、中文简称、分类关键词/ICON id | 公共只读 |
| GET | `/api/content/missions` | Guided/Free可用任务及双语提示 | 公共只读；按难度裁剪答案 |
| POST | `/api/mode/select` | Lobby选择模式 | 仅LOBBY允许 |
| POST | `/api/game/start` | 请求启动已选任务 | LOBBY/PREPARE；不能直接改硬件Arm状态 |
| POST | `/api/free/analyze` | 对当前后台选择集求候选 | 仅FREE |
| POST | `/api/free/instance` | 添加同服务图节点并声明角色 | 仅FREE；需规则约束 |
| GET | `/api/leaderboard?pack_id=...` | 严格同pack的前10名 | 只读，后端计算 |
| GET | `/api/result/{session_id}` | 完赛信息/简化DAG/徽章 | 只读，未授权时仅公开别名 |
| POST | `/api/player/alias` | 设置本次显示匿名昵称 | 会话拥有者或本地kiosk |
| POST | `/api/admin/login` | 本机维护认证 | OPERATOR |
| POST | `/api/admin/test-panel` | 灯/按钮诊断 | OPERATOR，比赛时不可用 |
| POST | `/api/admin/config` | 修改LED亮度与规则配置 | OPERATOR，需重新校准/版本记录 |
| POST | `/api/admin/leaderboard/clear` | 清理榜单 | OPERATOR+二次确认 |

所有前端变更请求仅表达**意图**：后端经过状态机检查，修改游戏状态并下发USB命令；禁止UI直接传`score=999999`覆盖数据库。

## 3. WebSocket事件（本地HMI只读事件总线）

标准服务端推送包：
```json
{
  "type":"game.step_updated",
  "server_seq":217,
  "session_id":"s101",
  "round_id":"r1",
  "step_epoch":4,
  "state_revision":23,
  "payload": {
    "mission_id":"M01_VOICE",
    "next_role_hint":{"zh":"文字转语音","en":"Text to speech"},
    "selected_nodes":["speech_to_text","dialogue_orchestrator","model_inference"],
    "remaining_ms":38250
  }
}
```

事件名：`device.state`、`game.lobby`、`game.countdown`、`game.step_updated`、`game.input_feedback`、`game.mission_completed`、`game.result_finalized`、`game.interrupted`、`leaderboard.updated`、`admin.fault`。每条带递增`state_revision`，客户端重复/逆序事件不得倒退UI；断线重连先拉`/api/snapshot`再订阅新状态。

**`remaining_ms`仅作显示近似值**，成绩以ESP raw时钟和后台事务为准。前端UI动画可50/60fps，但服务器事件推送无需每帧，建议10–20Hz以内的倒计时状态同步，浏览器本地插值；静态屏/减少动画模式也可读。

## 4. 玩家昵称与隐私

长度最多16 Unicode代码点，滤除控制字符，前端渲染HTML escape；默认`BUILDER-042`。无需收集姓名/手机号；作品墙和结果展示可关闭；提供管理员删除和活动结束本地清理。公网分享功能V1.2不承诺存在。

## 5. UI布局和操作视图

- **Attract**：顶部当前最强纪录，中心 `HIT KIRO TO START / 拍下 Kiro`、侧边固定4x4示意。
- **Mode Lobby**：Guided / Free / Builder Rush 60三大选择，大字清晰，支持触摸与实体快捷方式。
- **Rush HUD**：`60.0s`主视觉；`SOLUTIONS n`其次；任务英文+中文两行；当前角色短标签；Score/Combo/Error；榜首Ghost对比；保持HMI不泄露准确实体服务Id（正式排位）。
- **Free Canvas**：左侧已选服务（可Toggle），中间架构图，右侧“候选/缺失组件”；允许HMI手动增加同service不同实例。
- **Result**：SIMULATED SOLUTION COMPLETE、完成数/分数/排名、合规双语解释、拍照友好面板。
- **Operator**：实时每键按下日志、每路NeoPixel单步诊断、MappingCRC、版本、日志下载、亮度/屏幕设置；PIN/物理确认。

响应式建议横屏1920×1080优先，竖屏自适应；若X5显示分辨率未确定，以上只是基线，不应写死画布像素。

## 6. 技术实现建议

- 后端Python `asyncio`或等价进程架构：串口线程/async RX → 验证事件 → 事件分发队列 → 单线程权威Game reducer → SQLite事务 → WS推送。
- 不要让音效/图形渲染阻塞计分；结果基于权威事件日志重放可还原，`Reducer`相同输入及pack产生相同输出。
- 在数据库中记录`server_seq`/state_revision和最后一次有效ARM上下文；正式赛Backend意外重启时判中断，不自动续榜。


---

# PART VI — 双设备交互示例

这些Trace是**预期行为**，不是已经抓取的实机运行日志。时间戳均为S3启动后的微秒计数；具体seq/request_id示例为说明用途。

## A. 从Kiro到完整Guided Voice

```text
ESP   -> X5     HELLO boot_id=B12 proto_minor=2 mapping_crc=M0
X5    -> ESP    HELLO_ACK + SNAPSHOT_REQUEST
ESP   -> X5     STATE_SNAPSHOT IDLE 17 keys released 4 lanes healthy
PLAYER: Kiro press/release
ESP   -> X5     START_GESTURE CLICK press_id=100
X5    -> HMI    MODE_LOBBY (Guided / Free / Rush60)
PLAYER: selected Guided on HMI
X5    -> ESP    ROUND_ARM session=S1 round=R1 require_all_released=true
ESP   -> X5     ROUND_ARMED ready=true
X5    -> ESP    STEP_ARM epoch=1 all service keys eligible (only Guided hints visual)
ESP   -> X5     STEP_ARMED epoch=1 accepted_from_us=T1
X5    -> ESP    COUNTDOWN_START 3000ms
ESP   -> X5     COUNTDOWN_EVENT 3 / 2 / 1
ESP   -> X5     TIMER_EVENT GO=G (inputs from max(T1,G))
PLAYER: Transcribe pressed
ESP   -> X5     BUTTON_HIT id=13 epoch=1 raw_press=G+... press_id=101
X5 GameEngine   match 'speech_to_text' -> score & graph; then STEP_ARM epoch=2
...           Lambda(id=3), Bedrock(id=9), Polly(id=14)
X5    -> HMI    SIMULATED SOLUTION COMPLETE + DAG + bilingual explanation
X5    -> ESP    SCENE_SET 16-panel state; CUE_PLAY solution flow
```

## B. Deadline race（59.995秒落键，60.015确认）

```text
ESP G = 4,000,000 us     deadline=64,000,000
button raw_press =63,995,000 (before deadline)
button debounce confirm=64,015,000 (20ms stable)
ESP emits TIMER_EVENT EXPIRED when monotonic clock reaches deadline
ESP emits BUTTON_HIT (physically valid according to raw_press and epoch)
ESP waits for all candidate presses before deadline to be settled (max40ms example)
ESP sends INPUT_DRAINED, final_press_id=... after queueing all candidate events
X5 receives hit even if after EXPIRED, sorts and validates t_raw
X5 verifies all required reliable events arrived, transactions finalize once
If last hit completes solution at valid physical time -> solution counts
```

## C. 下一Step抢拍

玩家在Lambda Step尚未收到`STEP_ARMED epoch=3`时拍下Bedrock：事件要么带旧`epoch=2`，要么标`INPUT_NOT_ARMED`。HMI可以短反馈“请等下一步”，**不得算作epoch=3**。在新的STEP已ARM之前持续按住Bedrock，必须释放并重新拍才能计分。多任务切换同理，旧round无法完成下一Mission。

## D. USB在Ranked中拔掉

ESP或X5检测传输失联→`LINK_LOST`；X5 Session标`INTERRUPTED`；HMI清楚显示“本局中断，不入正式榜”；ESP灯进入安全静态状态，计时可继续物理走完但**绝不续榜**；重连后HELLO/快照重新握手，进入Lobby重新挑战。Guided/Free则可以提供恢复/结束选项，前提状态校验通过。

## E. Free Build多解与重复Lambda

玩家按 S3、Lambda、Rekognition → 后端返回图像分析候选（部分）和建议补DynamoDB；Kiro CLICK提交Analyze，允许选择“图像分析”场景。若玩家按 Lambda 再次则Toggle取消选择；要表达两个Lambda角色，须在X5 UI对同一Service选择“添加实例”并赋角色，单个物理键不自动派生两个实例。M07正式赛的Lambda×2则有预设producer、worker两次独立STEP_ARM。

## F. Duel两人同包

A与B轮流，各一次独立session；使用完全相同pack_id、hash、角色提示、评分版本。双方结束后对比完成Solution数→分数→错误次数→完成时间；胜场进入Duel榜，**不会写入单人Ranked榜**（除非有单独正式赛制明示）。


---

# PART VII — Corner Cases与验收

状态：测试计划/预期结果；**没有实物验证的项目不得标记PASS**。自动化Reference Tests只验证Python参考协议与内容。

| ID | P | 类别 | 输入/故障注入 | 必须达到的结果 |
|---|---|---|---|---|
| HW-01 | P0 | 输入 | 17键每键按100次 | 对应唯一service/start id、无错映射 |
| HW-02 | P0 | 输入 | 服务键持续按下30秒 | 仅一次HIT，卡键提示，不自动重复 |
| HW-03 | P0 | 输入 | Kiro双击，间隔250ms | 仅DOUBLE，不先触发CLICK |
| HW-04 | P0 | 输入 | Kiro持续按住2s | 仅HOLD，松手不再发CLICK |
| HW-05 | P0 | 输入 | 已按住Lambda时启动游戏 | 所有键释放之前不能ROUND_ARMED |
| HW-06 | P0 | 输入 | 两键同毫秒按击 | 各事件独立去抖；排序确定性 |
| HW-07 | P0 | 输入 | 16键几乎同时击键 | 不死机、不产生幻键；如果队列饱和明确报故障 |
| HW-08 | P1 | 输入 | 弹跳噪声9ms | 不误认稳定HIT |
| HW-09 | P1 | 输入 | 机械触点卡住/线短路 | 维护界面暴露异常；正式赛禁止启动 |
| HW-10 | P0 | 灯 | A/B/C/D依次各亮4面板 | 每次仅对应卡片亮、无串台、无错色序 |
| HW-11 | P0 | 灯 | 彩色/白光25%多区保留 | 供电/温升在评审限额内 |
| HW-12 | P0 | 灯 | Kiro无NeoPixel | 不尝试发送不存在的START灯带数据 |
| HW-13 | P1 | 灯 | 一分组第一颗WS2812坏 | 其他3lane照常；同组下游可能故障，明确显示待维护 |
| HW-14 | P1 | 电源 | X5 USB与外置5V供电 | 不反灌，外置电源切断时行为安全 |
| HW-15 | P0 | 自检 | 断电重启 | LED默认安全暗态，需Kiro重新启动 |
| PT-01 | P0 | 传输 | 每字节拆包发送合法帧 | 仅完整帧校验后执行一次 |
| PT-02 | P0 | 传输 | 两个合法帧粘包 | 两帧分别解析执行 |
| PT-03 | P0 | 传输 | CRC位翻转 | 丢弃，不执行命令，能对齐后续帧 |
| PT-04 | P0 | 传输 | payload_len=2049或非法utf8 | 拒绝且资源有上限 |
| PT-05 | P0 | 传输 | 重复request_id/seq | 幂等，无重复开始倒计时或cue |
| PT-06 | P0 | 传输 | 旧scene_id消息晚到 | 不覆盖最新灯光场景 |
| PT-07 | P0 | 传输 | 旧session/round的HIT迟到 | 不能当本局正确击键 |
| PT-08 | P0 | 传输 | 同一boot_id/press_id重发3次 | 只计一次积分和一次日志记录 |
| PT-09 | P0 | 传输 | 主控复位boot_id变化 | 当前Ranked被中断、老事件不得复活 |
| PT-10 | P0 | 传输 | USB热拔100次 | 不死机；竞技一断即中断、不入榜 |
| PT-11 | P1 | 传输 | USB端口ttyACM号改变 | X5稳定设备发现，不依赖编号 |
| PT-12 | P1 | 传输 | Unknown message/proto_minor<2 | 不启用正式竞赛、诊断友好错误 |
| TM-01 | P0 | 计时 | GO前按下/GO后通过消抖 | 无效，不能得开场分 |
| TM-02 | P0 | 计时 | 59,995ms触点下落，60,015ms去抖完成 | 最后一击**有效**，settling收到后入账 |
| TM-03 | P0 | 计时 | 60,001ms按下 | 无效，计时不延长 |
| TM-04 | P0 | 计时 | EXPIRED先于最后BUTTON_HIT抵达X5 | 最终结果仍一致；等待INPUT_DRAINED和事件水位线 |
| TM-05 | P0 | 计时 | 输入队列丢HIT但收到INPUT_DRAINED | 不能正常VALID结算，标 INTERRUPTED |
| TM-06 | P0 | 计时 | 切题动画期间提前按下一Mission正确键 | 不进入下一题成绩，需STEP_ARMED后重新按 |
| TM-07 | P0 | 计时 | 旧step按住Lambda跨新step | 无二次击键，释放并重新按才有效 |
| TM-08 | P0 | 计时 | UART/USB重发TIME_EXPIRED | 最多一次Finalization事务 |
| TM-09 | P1 | 计时 | X5/HMI卡顿1秒 | ESP事件时间不变，正确性/分数不受屏幕卡顿改变；必要时标体验降级 |
| GM-01 | P0 | Guided | 完成8基础Mission | 每个节点依赖/并行分支正确 |
| GM-02 | P0 | Free | S3+Lambda+Rekognition | 返回AI视觉可行部分方案+明确缺失/可选 |
| GM-03 | P0 | Free | Transcribe+Bedrock+Polly | 提供语音候选及编排建议，不声称生产级完整 |
| GM-04 | P0 | Free | EC2+Polly+SQS | UNSUPPORTED而不是错误断言不可能 |
| GM-05 | P0 | Free | 16服务全选 | 不仅凭个数自动Complete/获最高成就 |
| GM-06 | P0 | Free | 同一集合匹配多场景 | 展示最多3候选并请求确认应用目标 |
| GM-07 | P0 | Game | M07 Lambda producer→SQS→Lambda worker | 同一个实体键可作为2实例且必须重新抬起/独立STEP |
| GM-08 | P0 | Ranked | 两玩家同固定pack相同输入轨迹 | 总分、完成数、排序完全一致 |
| GM-09 | P0 | Ranked | 不同pack同一游戏日 | 不混榜 |
| GM-10 | P0 | Ranked | 连击10、错误1 | 分数与预定义公式一致 |
| GM-11 | P0 | Ranked | 赛程最后一道题完成 | PACK_CLEARED 不无限刷短题 |
| GM-12 | P0 | Ranked | 单人榜和Duel/Team榜 | 完全隔离按赛制分榜 |
| GM-13 | P1 | Achievement | 只按了Bedrock+AgentCore但无架构 | 不颁Agent Builder徽章 |
| DB-01 | P0 | DB | RESULT_FINALIZED并发提交2次 | sessions唯一终态、无两条排行榜项 |
| DB-02 | P0 | DB | SQLite事务中途断电 | 重新启动数据库完整、不会半条VALID |
| DB-03 | P0 | DB | 前端直接提交fake score | 后端拒绝/忽略，score只能由事件重算 |
| DB-04 | P1 | DB | 昵称HTML JS/emoji超长 | 合法截断/转义，不能脚本执行或撑坏页面 |
| DB-05 | P1 | DB | today跨午夜 | 活动时区正确分榜，历史保留 |
| OPS-01 | P0 | 现场 | RDK X5浏览器刷新 | 后端任务未重启，UI从快照恢复 |
| OPS-02 | P0 | 现场 | X5后端崩溃 | Ranked中断；Guided/Free有明确恢复决策 |
| OPS-03 | P0 | 现场 | 整机断网8h | 仍可完成 Guided/Free/Ranked与本地排行榜 |
| OPS-04 | P0 | 现场 | 连续8小时≥100局 | 无死机/内存泄漏/误映射/静默失联 |
| OPS-05 | P0 | 现场 | mapping_crc与当前UV位置不匹配 | 禁止正式冲榜，进入校准界面 |
| OPS-06 | P1 | 现场 | 传输日志打印到同一USB协议口 | 设计禁止；固件测试检出违规 |
| OPS-07 | P1 | 操作 | 管理员清空榜单与重校准 | 需要认证/确认，操作审计可追踪 |
| OPS-08 | P1 | 无障碍 | reduce_motion模式 | 仍可识别成功/失败，无>2Hz高对比频闪 |

## 合格标准

- **P0全部通过**方可宣称展会可用；P1可列Known Limitations并评估风险。
- 按击P95延迟目标<100ms、P99<200ms是目标非已实测；ESP去抖20ms包含在物理→HMI延迟中。
- 1000次随机重放与顺序变化测试：无重复得分；模拟100组60s边界、一致结算；USB断连100次不脏榜。
- 项目验收附：固件Hash、mapping CRC、ruleset版本、pack/hash、现场电流/温升测量结果、失败用例、回放日志。


---

# PART VIII — 开发执行任务

每条任务必须包含代码/自动测试/日志和可复现实测记录；**Done不等于代码能编译**，必须通过对应验收。

| ID | 依赖 | 交付 | DoD（Definition of Done） |
|---|---|---|---|
| T00 | 无 | 版本基线 | ESP-IDF & esp_tinyusb & led_strip锁版本；X5镜像记录；文件结构/CI可运行 |
| T01 | T00 | 实物映射/电源冻结 | 17输入、四数据lane、每面板灯珠数、供电接法形成hardware.json、mapping CRC |
| T02 | T01 | ESP输入组件 | 17键1ms轮询/去抖20ms、候选raw时间、Press/Release、保持/重按，100次测试 |
| T03 | T02 | Kiro手势 | SINGLE/DOUBLE/HOLD互斥，250–300ms双击窗、2s长按，无独立LED时正常 |
| T04 | T01 | NeoPixel RMT | 4lane分组独立，色序/长度可配置、亮度上限、LED Test/故障提示 |
| T05 | T04 | Scene Engine | 16面板语义状态+原子Scene、Cue叠层与超时、30fps目标 |
| T06 | T00 | AWG1协议C/Python | 相同帧与CRC；坏包/半包/粘包/重放测试一致通过 |
| T07 | T02,T06 | USB CDC TX/RX | HELLO/HEARTBEAT/SNAPSHOT、输入事件可重试队列，实机X5连接 |
| T08 | T03,T05,T07 | ESP权威Timer & ARM | 倒计时/GO/deadline/raw边界/STEP_ARMED/INPUT_DRAINED所有P0通过 |
| T09 | T07 | X5 serial link daemon | udev端口、唯一打开、复连、消息解析、后台重启规则、服务systemd |
| T10 | T09 | Session FSM | idle/lobby/prep/active/settling/result, session/round/epoch状态一致 |
| T11 | T10 | Mission parser/validator | 16服务stable key、8任务图无环，异常图报错+快照版本锁 |
| T12 | T11 | Graph/Rule Engine | 角色实例/依赖/optional/候选；S3+Lambda+Rekognition等边界正确 |
| T13 | T10,T12 | Guided HMI | Kiro→挑任务→3/2/1→4服务AI Voice→架构屏完成回大厅 |
| T14 | T12,T13 | Free HMI | 选择/取消、Analyze、缺失建议、3个候选、同服务多节点UI |
| T15 | T08,T12,T13 | Rush60 Ranked | pack不可变、无泄露提示、权威事件时间与结算barrier |
| T16 | T15 | Score/Achievement | 连击/错误/完成分，成就通过规则证据而非图标数量 |
| T17 | T15,T16 | SQLite结果事务/排行榜 | 唯一事件、唯一终态、分榜、虚假前端得分无效 |
| T18 | T17 | Ghost/HUD | Top榜进度轨迹与本人比较；结果卡拍照友好 |
| T19 | T14,T17 | Operator/HMI维护 | 映射校准、按键测试、灯测试、亮度/规则/榜单管理 |
| T20 | T18 | Duel | 两位轮流同pack、胜者/平局、独立胜场榜 |
| T21 | T20 | Team | 人数分榜、协作模式、不假定按钮可识别个人 |
| T22 | T19 | Fault Injection & 8h Soak | TEST_PLAN P0全绿、8小时100局运行日志、明确Known Issues |
| T23 | T22 | 现场部署与回滚 | systemd/kiosk自启、数据库备份、断电恢复、操作手册、版本/回滚包 |

## 工作包边界

- **ESP固件开发者**：T00,T01,T02,T03,T04,T05,T06(C),T07,T08；不可实现云架构“判定真伪”。
- **X5后端开发者**：T06(Python),T09,T10,T11,T12,T15,T16,T17；后端是成绩唯一权威。
- **HMI开发者**：T13,T14,T18,T19；前端不能直接更改成绩，也不独占串口。
- **集成负责人**：T22,T23；实物配置/现场协调/品牌最终审核。

## 里程碑（并行开发的实际门槛）

- **M0 Bring-up**：17键+四lane灯+USB双向 `HELLO/BUTTON_HIT/SCENE_SET`；无游戏。
- **M1 Vertical Slice**：Kiro→Guided Voice→打4个服务→完成图谱/结果，端到端。
- **M2 Playable**：8任务+Free解释引擎+模拟/错误处理。
- **M3 Ranked**：60秒公平题包+计时边界+SQLite榜单。
- **M4 Exhibition Ready**：P0全测通过、8h稳定与回滚方案。

## 功能锁定与拒绝隐式需求

首发P0：Guided/Free/Ranked/Kiro/USB/17键/RMT/本地榜；P1：Ghost与成就、异常维护；P2：Duel/Team、QR分享/本地LLM解释。**不做**真正的AWS API部署、不做用户隐私收集、不做网络依赖、不做Kiro NeoPixel、不做凭“16张都拍过”自动完成Solution。


---

# PART IX — 变更与决策

## 来源

- `AWS_Architecture_Challenge_Firmware_Spec_V1.0.md`（2026-10-14）：ESP32、RDK X5、17键、4lane、AWG1、三模式、8个Mission。
- `Gamification_Leaderboard_V1.1.md`（2026-10-14）：固定任务包、公平计分、排行、Ghost、Duel/Team、比赛结算。
- 聊天中Corner Cases复审：deadline后消抖确认、同时按击、未释放键、Step Epoch、X5卡顿、网络故障、自由建造多解。

## 原版本冲突→唯一V1.2规则

| 原问题 | V1.2定义 |
|---|---|
| V1.0 竞技USB掉线可暂停继续；V1.1要求中断 | **Ranked/Duel正式比赛**USB/ESP重启立刻INTERRUPTED不入榜；Guided/Free可选择恢复 |
| 60s到点立刻结算 vs 截止前按下后才完成消抖 | ESP保留`raw_press`时间、稳定20ms后确认，X5等待`INPUT_DRAINED`可靠水位再提交 |
| X5新Mission画面出现，但ESP仍在上一场景 | 使用`session_id/round_id/step_epoch`和`STEP_ARMED`明确输入窗口 |
| Kiro双击引起单击副作用 | 300ms点击待判窗口、双击/长按互斥；Ranked时Kiro不影响成绩 |
| Free再次拍Lambda表示取消，但M07需要2个Lambda | Free按Service Toggle + HMI Add Instance；Guided/Rush按明确逻辑角色两次独立击键 |
| 只有服务集合却输出唯一架构图 | 返回候选+明确角色/分支/缺失项，未验证仅提示PARTIAL/UNSUPPORTED |
| 一分钟随机难度题目却混榜 | 正式榜相同不可变pack/hash/hints/variants/scoring version；Practice随机不入榜 |
| 多次收到计分事件/最终完成通知 | `device_id+boot_id+press_id`去重，SQLite单次最终提交 |
| 原始帧协议增补导致不兼容 | 保留AWG1 v1二进制封装，握手协商`proto_minor=2`和新增消息；不满足则拒绝Ranked |
| 全部灯同时亮可能冲电源 | 默认软件25% cap，分组供电/保险，电源和亮度实测后才放行 |
| START没有NeoPixel | Kiro接触点ID0，普通按钮灯未确认，`start_neopixel:false`永远保持 |

## 本次新增

- `docs/HMI_API.md` + `docs/STATE_SEQUENCES.md`：前后端API和GO/SETTLING/ARM完整轨迹。
- `config/solutions.json`：V1.0 8套基础Mission转换成标准数据结构并补双语角色提示与显式图谱关系；**新增候选M09_PROTECTED_WEB仅Guided/Free，不进入Ranked base pack**。
- `config/hardware.example.json`：明确未确认硬件参数而非编造GPIO。
- `config/game_config.json` + 2语言词条 + SQLite草案 + 参考Python协议解析/评分/验证测试。
- `docs/OPEN_DECISIONS.md`：最后冻结问题清单。

## Known Limitations

- 文档与参考测试通过**不代表ESP-IDF固件/HMI已经写好**；USB/NeoPixel实机尚未联调。
- M01–M09均是教学简化架构，不包含真实生产部署所需的全部IAM、VPC、访问控制、成本和监控方案。
- CloudWatch当前设计为可选观测分支，没有强制的专项Mission；此为明确的内容取舍，后续可补充。
- 活动方品牌/中国区服务显示名仍需审核，不自动替换16张已绘制的官方服务图标。


---

# PART X — 生产前待确认事项

这是**待确认事项**，不得被开发者默认为已知事实。

| ID | 需要确认 | 影响/行动 |
|---|---|---|
| O01 | ESP32-S3具体开发板、USB Device口与PCB GPIO | 决定 `board_support` 和TinyUSB初始化、供电隔离 |
| O02 | 17触点是否全部NO/COM对GND | 去抖极性，需实测 |
| O03 | 16张面板实际NeoPixel数、每组DIN/DOUT链接顺序 | 软件offset及布线映射 |
| O04 | 是否16个普通按键自带LED，额定电压和共地关系 | 是否需要单独MOSFET/按钮灯板；无驱动则feature-flag false |
| O05 | Kiro START自带灯吗 | 已知无NeoPixel；单色灯另选驱动或默认无灯 |
| O06 | 电源额定值、分线接口电流、最坏灯效压降 | 5V 10A为候选非批准额定；确认保险/线径与亮度cap |
| O07 | X5镜像、浏览器显示/触摸、音频输出方式 | kiosk启动与HMI布局 |
| O08 | 分组ABC D和正面4x4布局及UV印刷最终服务对应位置 | 映射CRC与现场校准 |
| O09 | 活动方商标与中文显示名 | `official_en`不自行篡改；独立display_name配置发布审核 |
| O10 | 当日排行榜与规则更新政策 | 固定pack_id/hash，活动时区/赛事赛道确认 |
| O11 | 异常场次的现场运营决策 | 断连不得上榜、Free恢复入口、维护人员密码 |
| O12 | 网络二维码是否要实现 | 纯离线MVP只做本地屏拍照成绩卡，手机访问需后续网络设计 |

## 需确认而不应自动修正的技术内容

- 原V1.0内容定义8个基础Mission，V1.2 `solutions.json`原样继承核心服务结构并补了关系边和中英提示；新提出M09带身份认证Web场景**仅用于Guided/Free，未加入初版正式Ranked固定题包**。
- S3/CloudFront 和 AgentCore/Bedrock 是示意架构的子模块关系，不假设它们需要一条单线数据流。
- CloudWatch在现有基础Mission全部为可选观测分支，这是教学设计选择，不是忘了该服务。若要让它成为强制节点，需要设计“Observability”专项任务并进行活动方确认。


---

# PART XI — 固件与Backend实施伪代码

## 1. ESP按键采样与去抖（每键独立状态）

```c
// pseudocode - not literal ESP-IDF source
scan_key(k, now_us) {
  level = gpio_read(k.pin);
  if (level != k.candidate_level) {
    k.candidate_level = level;
    k.candidate_since_us = now_us;
    k.candidate_context = current_armed_context_snapshot();
  }
  if (level != k.stable_level && now_us - k.candidate_since_us >= 20_000) {
    k.stable_level = level;
    if (level == PRESSED) {
      event = {button_id, press_id++, raw_t: k.candidate_since_us,
               confirmed_t: now_us, context: k.candidate_context};
      reliable_queue_push(event);  // overflow -> explicit FAULT, Ranked interrupted
      local_cue(PRESSED);          // feedback is not game correctness
    } else emit_optional_release();
  }
}
```

**关键点**：候选开始时就锁定`round_id/step_epoch`，避免20ms消抖期间恰巧任务切换造成误归属。候选按下时若未ARM，则即使确认时已ARM仍不可计分。

## 2. ESP计时/GO/最后按键结算

```text
ROUND_ARM受理前检查17键输入（Kiro除非业务需要）全部释放/映射CRC一致
首步STEP_ARM记录epoch但GO前关闭计分门；COUNTDOWN_START开始3/2/1
GO: t0=monotonic(), deadline=t0+60,000,000; open gate
每个稳定按下：若候选raw_t位于[GO,deadline)且context=armed epoch -> reliable HIT
TIME_EXPIRED: close gate; wait until debounce candidates before deadline settled
当全部已产生HIT持久化ACK + no unsent candidate -> send INPUT_DRAINED(event_count, final_press_id)
若2s内仍有unacked HIT、USB失联或队列溢出 -> ESP fault, X5 INTERRUPTED
```

`2s`仅是建议的`SETTLING`等待超时上限，用于判断通信故障，**不延长比赛时间**。Kiro手势时间戳也来自同一时钟，但它在Ranked ACTIVE不能暂停/跳题。

## 3. X5确定性Reducer (single authoritative writer)

```python
# conceptual pseudocode
async def on_physical_hit(hit):
    if db.seen(hit.device_id, hit.boot_id, hit.press_id):
        return ACK_OK  # duplicate, never score again
    db.persist_event(hit)  # commit or durable insert before ACK
    if not session.active or hit.session_id != session.id:
        mark_disposition(hit, 'REJECTED_SESSION'); return ACK_OK
    if hit.round_id != session.round_id or hit.step_epoch != session.armed_epoch:
        mark_disposition(hit, 'IGNORED_TRANSITION'); return ACK_OK
    if not in_physical_window(hit.raw_press_t_us, session.go_us, session.deadline_us):
        mark_disposition(hit, 'OUTSIDE_WINDOW'); return ACK_OK
    # Deterministic event ordering: (raw_t, button_id, press_id)
    if not current_frontier_allows(service(hit.button_id)):
        score.invalid_node(); mark_disposition(hit, 'INVALID_ROLE')
    else:
        assign_single_role_instance(hit)
        score.valid_node(); mark_disposition(hit, 'VALID_ROLE')
        if frontier_advanced():
            await step_arm_next_epoch()  # must wait for MCU STEP_ARMED
        if solution_complete():
            score.complete_solution_once(round_id)
    persist_events_and_score_transactionally()
    return ACK_OK
```

正式实现应以一个确定性单写者队列序列化物理事件；上面伪代码的`db.persist_event`与计分状态需置于可恢复事务/重放机制中。**如果并发输入可能产生时间逆序到达，必须短窗口缓冲/按raw物理时间排序再判定**，不能立即根据USB到达顺序改变step。新的STEP_ARM只基于排序后已确定的输入前缀推进。输入排序窗口/性能上限应在模拟与实机测试中冻结。

## 4. Free Build Matching（不是云模型幻觉）

```text
selected service multiset + optional explicit chosen roles
 -> mission candidate shortlist: coverage by service, missing required roles
 -> graph solver: required nodes can map to selected/service_instances
 -> validate prerequisite DAG and graph_edges relationships
 -> 0~3 candidates sorted by explainable coverage
 -> user chooses business context when multiple plausible
 -> 'VALID_COMPLETE' only after accepted graph relationships are present
```

Free中**服务集合仅能产生候选**；要声称完整有效，需要包含场景/角色/依赖的已知规则匹配。若候选服务集合恰好完整但存在多种连接方向，须请用户选目标场景。`UNKNOWN`与`UNSUPPORTED`表示本地内容库暂未覆盖，不能表达为AWS不支持。

## 5. 游戏内部事件模型

服务端建议统一事件记录：
```json
{
  "event_id":"device01/boot09/press000403",
  "origin":"MCU",
  "session_id":"s1",
  "round_id":"r3",
  "step_epoch":7,
  "service_key":"LAMBDA",
  "raw_t_us":59995000,
  "confirmed_t_us":60015000,
  "disposition":"VALID_ROLE",
  "graph_node_id":"producer_lambda",
  "state_revision":103
}
```

服务端还记录`GAME_ARMED`, `GAME_GO`, `STEP_ARMED`, `MISSION_COMPLETE`, `INPUT_DRAINED`, `SESSION_INTERRUPTED`, `RESULT_FINALIZED`等非按键事件。成绩可由事件日志/冻结pack重放验证；不要用前端屏幕当前状态直接算分。

## 6. 生产与运营注意

- `udev`稳定节点、`systemd`自动启动与Watchdog；可拔插USB后恢复诊断，但Ranked不继续旧局。
- X5 SSH管理可用但展会默认UI不能泄露后台端口、管理密码或任意Shell权限。
- `CONFIG_SET`要请求方为OPERATOR且非ACTIVE，硬件mapping变更后新的CRC强制重新校准。
- `missions.json`与scoring更改后重新计算pack/hash并新建同组Leaderboard，不对旧记录悄悄重算。
- 先写host模拟器：虚拟ESP每次测试可调时戳、乱序、CRC失败、连续按下/松开，以便在硬件到齐前并行开发UI。


---

## 数据与可运行参考索引

- `config/services.json`：16服务稳定键和官方英文名；`KIRO_START` id0。
- `config/solutions.json`：V1.0原有8 Mission + V1.2新增1个可选延展场景；双语提示/有向关系。
- `config/game_config.json`：Ranked赛制/计分/手势/灯效参数与开发用pack hash。
- `config/hardware.example.json`：硬件**未验证**参数样例；禁止直接Flash当正式配置。
- `config/i18n`：中文/英文 HMI显示文案。
- `db/schema.sql`：SQLite持久化结构草案。
- `reference/awg1_protocol.py`：AWG1帧编码、CRC与增量解析参考；`reference/scoring_reference.py`：评分算法参考。
- `reference/validate_content.py`：固定ServiceID、Mission DAG与Ranked包校验。
- `tests/`：协议/内容/评分单元测试，**不能替代ESP32/RDK X5硬件联调**。

**结论：这是能交付开发执行的统一规范和参考工具包，设备端ESP-IDF固件、RDK X5服务与HMI仍需按TASKS实现并通过TEST_PLAN后方可交付现场。**
