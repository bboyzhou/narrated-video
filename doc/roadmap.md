# Narrated Video：AI Mini Studio 项目 RoadMap

> 文档版本：V1.3
>
> 状态基线：2026-09-13
>
> 文档性质：项目演进规划，不代表当前 skill 已具备全部能力。

## 1. 愿景与定位

项目计划从“图片运镜解说视频”逐步演进为适合电影化历史叙事的 AI Mini Studio。目标不是让所有镜头都依赖生成式视频，而是组合导演式分镜、角色资产、多角色语音、声音设计、确定性静帧运镜和少量关键动态镜头，在资源受限的本地或远端执行环境中稳定完成作品。

核心原则：

1. 导演工程优先于模型堆叠，先判断镜头是否真的需要生成动态画面。
2. Lip Sync、复杂动作和高质量 I2V 等昂贵能力只用于少量高价值镜头。
3. 静帧负责清晰传递信息，动态镜头负责情绪、转折和高潮。
4. 优先用画外音、反应镜头、物件特写和声音设计规避模型弱项。
5. 角色、声音、场景、项目派生物和缓存资产分离，支持跨项目复用。
6. Provider、Runtime、Hardware 与执行参数保持解耦，按实际环境动态规划。
7. 所有增强能力都必须有确定性降级路径，单点失败不能阻断最终 MP4。

## 2. 当前基线

| 阶段 | 当前成熟度 | 已有基础 | 主要缺口 |
| --- | --- | --- | --- |
| Phase 0：架构与协议 | 部分完成 | Project、Video Job、RuntimePlan 和 Provider Capability Schema | 独立 Script、Shot Plan、Audio Timeline 与通用 Audio/Image Provider 协议 |
| Phase 1：多引擎、多角色语音 | 部分完成 | MeloTTS、CosyVoice、AudioFile、逐句 WAV、批量缓存、语速与响度处理 | AudioService、Voice Registry、统一 Provider、逐角色路由、试听、对白重叠和 Audio QA |
| Phase 2：电影化静态视频 | 部分完成 | FFmpeg 图片/视频图层、关键帧、转场、字幕和混音 | Director 规则、电影镜头语义、J-cut/L-cut 和可选 Renderer Adapter |
| Phase 3：通用 I2V | 主体完成 | Provider/Runtime/Hardware/RuntimePlan 解耦、任务包、导入、预算和回退 | 统一取消、进度、自动画面质量检测及更多真实 Runtime smoke |
| Phase 4：场景声音 | 起步阶段 | 旁白、BGM、响度归一化和基础混音 | Ambience、SFX、Transition 分层、自动 ducking 和空间模板 |
| Phase 5：历史世界资产库 | 未实现 | 项目素材和离线素材目录 | 世界、角色、服饰、地点、声音及跨项目引用协议 |
| Phase 6：自动导演与质量闭环 | 未实现 | 结构检查、媒体解码和部分时长验证 | 镜头评分、决策报告、综合 QA、重试和自动替代镜头 |

成熟度描述以仓库实际代码和测试为准。RoadMap 中的示例名称、目录和接口只有进入实现并通过验收后，才能写入 README 的“当前能力”。

## 3. 目标工作流

```text
原始文案
  ↓
Script Planner：旁白、对白、动作、场景结构化
  ↓
Director：镜头设计、叙事价值、成本判断、降级策略
  ↓
Asset Resolver：角色、声音、场景、图片、视频、音效解析
  ↓
并行生产
  ├─ Image Provider：静帧、角色、环境、物件
  ├─ I2V Provider：少量关键动态镜头
  ├─ TTS Router：旁白与多角色对白
  └─ Audio Designer：环境声、动作音效、BGM
  ↓
Dialogue Timeline + Visual Timeline
  ↓
Renderer Adapter（当前 Python + FFmpeg；未来可选 Remotion）
  ↓
自动校验、人工审看、失败降级、最终 MP4
```

## 4. 稳定架构边界

### 4.1 内容协议

- `script` 描述场景、旁白、对白、动作和情绪，不携带模型或运行平台参数。
- `shot_plan` 描述镜头语义、素材策略、时间、运镜和降级策略。
- `audio_timeline` 描述对白、停顿、重叠、环境声、音效、BGM 和混音意图。
- 角色、场景和声音通过稳定 ID 引用，不把本期生成产物复制为新的基础资产。

协议建设采用兼容式演进：先为现有 Project v1 增加可选字段和独立 Schema，再提供显式迁移工具；在新协议稳定前，不移除旧项目仍需的字段。

### 4.2 Provider 与执行环境

- `Profile` 只表达速度、质量、成本等用户意图。
- `Provider` 只表示模型或外部服务及其能力。
- `Runtime` 只表示执行位置与方式，通过可扩展 Adapter 注册，不绑定或枚举具体平台。
- `Hardware` 是运行时探测到的设备、显存、精度和资源约束。
- `RuntimePlan` 是分辨率、帧数、步数、dtype、offload 和超时等执行参数的唯一来源。
- Job 只携带内容输入、语义运动、seed、目标时间线时长和输出约定。

不得把平台与硬件组合重新定义为业务 Profile，也不得让 Script 或 Shot Plan 直接依赖某个具体模型、设备或托管平台。

### 4.3 渲染边界

当前确定性主渲染链路是 Python + FFmpeg。`remotion_motion` 目前是普通镜头和 I2V 失败时的路由/回退语义，不代表仓库已有独立 Remotion 工程。

未来若引入 Remotion，应实现为 Renderer Adapter，并与 FFmpeg 共用 Shot Plan、Audio Timeline、资产引用和验证协议；不能让项目数据重新绑定单一渲染器。

### 4.4 Speech 与场景声音边界

语音生成和场景声音是两个独立子系统：

- Speech Pipeline 负责旁白、角色对白、逻辑音色、TTS 路由、语音缓存、后处理、对白时间线和语音 QA。
- Audio Designer 负责 Ambience、SFX、BGM、Transition、声像和自动 ducking。
- Mixer 只消费标准化音频资产和 Audio Timeline，不直接调用任何 TTS SDK。
- 视频渲染层只消费音频路径及时间信息，不感知 Kokoro、MeloTTS、Edge-TTS 或 CosyVoice 等底层引擎。

目标调用关系：

```text
Script / Dialogue
        ↓
   AudioService
        ↓
Voice Registry → TTS Router → TTS Provider
                              ↓
                 Post Process + Speech QA + Cache
                              ↓
                      Dialogue Timeline
                              ↓
                Audio Mixer → Video Renderer
```

## 5. Phase 0：架构与协议固化

### 目标

稳定 AI Mini Studio 的内容和资产协议，使 TTS、I2V、图片生成、声音设计及渲染器可以独立替换。

### 交付物

- `script.schema.json`：场景、旁白、对白、动作、情绪及说话人。
- `shot-plan.schema.json`：镜头类型、素材策略、时长、运镜、优先级和降级链。
- `audio-timeline.schema.json`：对白、停顿、重叠、Ambience、SFX、BGM 和 Transition。
- `voice-registry.schema.json`：逻辑音色、底层 Provider/Speaker、语言、标签、参考音频、版本和许可。
- `tts-provider-capability.schema.json`：语言、输入长度、输出格式、设备后端、联网要求、批处理、参考音频及并发能力。
- `TTSRequest` / `TTSResult` 最小契约：内容层只提交逻辑音色和生成意图，结果记录实际 Provider、Speaker、版本、时长、格式、缓存命中及降级信息。
- Image、Audio Provider 的最小统一契约；复用现有 I2V Provider/Worker 约束。
- 角色资产、世界资产、项目派生资产和缓存资产的目录及引用规则。
- Project v1 到新增协议的兼容映射、版本策略和迁移测试。

首批镜头语义：

```text
establishing
character
reaction
insert
silhouette
action_detail
dialogue_hidden
dialogue_lipsync
action_i2v
```

### 验收标准

- 同一份 Script/Shot Plan 可切换 TTS 或 I2V Provider，不修改内容字段。
- 逻辑音色可更换底层 Provider/Speaker，而不修改已有 Script 和 Shot Plan。
- 不支持的能力可在任务启动前识别，并给出原因与可用降级方案。
- 旧项目可继续读取；迁移前后主要时间线和资产引用保持一致。
- 所有 Schema 示例、错误示例和兼容行为均有自动化测试。

## 6. Phase 1：多引擎、多角色语音 MVP

### 目标

把现有嵌入 `pipeline.py` 的语音实现迁移为 AudioService + TTS Provider + Voice Registry + TTS Router 架构，让旁白和主要人物具有稳定、可区分、可复用的声音身份，并形成自然的多人对白节奏。

Provider 必须声明自身支持的设备后端、资源需求和并发能力；Runtime 通过能力探测提供实际环境信息，Planner 再生成兼容的执行计划。MVP 不绑定特定操作系统、处理器、加速后端或硬件型号。

### 建议模块

```text
scripts/audio/
├── service.py
├── models.py
├── registry.py
├── router.py
├── cache.py
├── postprocess.py
├── qa.py
├── alignment.py
├── dialogue_timeline.py
├── mixer.py
└── providers/
    ├── base.py
    ├── audio_file.py
    ├── kokoro.py
    ├── melotts.py
    ├── edge_tts.py
    ├── cosyvoice.py
    └── ...
```

目录名称是目标结构，不要求一次性移动全部旧代码。迁移期间由兼容层继续读取现有 `voice.engine`、`voice.command` 和 `voice.batch_command` 配置。

### Provider 定位

| Provider | 当前状态 | 路线图定位 | 启用条件 |
| --- | --- | --- | --- |
| AudioFile | 已有 | 人工配音或已有授权录音；最高确定性输入 | 文件通过 PCM WAV、来源和许可检查 |
| MeloTTS | 已有 | 本地快速预览及 fallback 候选 | 已选择环境通过离线 preflight 和 speaker 试听 |
| CosyVoice | 已有可选适配 | 核心角色、高质量或参考音频场景的实验性 Provider | 本地或远端 Runtime 性能可接受，模型、许可和参考音频均已确认 |
| Kokoro | 规划候选 | 本地轻量多音色 Production 候选 | 中文音色、许可证、模型版本、目标 Runtime 性能和长文本稳定性通过 benchmark 与试听 |
| Edge-TTS | 规划候选 | 在线多音色补充，不作为唯一 Provider | 用户允许联网，外部服务可用，隐私、许可和使用条款可接受 |
| Qwen3-TTS、Piper、GPT-SoVITS 等 | 后续候选 | 通过同一 Provider 契约扩展 | 先完成能力、成本、安全和运行环境评估 |

Kokoro 和 Edge-TTS 在完成验收前不得写成默认可用能力。Provider 的角色定位是初始假设，不是永久绑定；最终默认值由目标机器 benchmark、授权检查和用户试听结果决定。

### 生成模式

| 模式 | 意图 | 默认策略 |
| --- | --- | --- |
| `preview` | 最快得到可审核 Demo | 优先已验证的本地快速 Provider，保留缓存，执行最小完整性 QA |
| `production` | 正式成片和角色连续性 | 使用已试听批准的逻辑音色，执行后处理、完整 Speech QA 和可复现记录 |
| `premium` | 少量核心人物或高价值片段 | 显式允许高成本、本地重型或远端 Provider；失败时遵循角色级降级策略 |

模式只表达质量、速度和成本意图，不永久绑定某个 Provider。项目可锁定逻辑音色和 Provider policy；同一作品内不得随机切换声音。

### 6.1 Audio Core

1. 定义统一的 `TTSProvider` 能力接口，包括 `available`、`capabilities`、`list_voices`、`synthesize` 和可选 `synthesize_batch`。
2. `TTSRequest` 使用逻辑音色 ID、语言、文本、emotion、速度、pitch、模式、目标格式和可选时长意图，不要求业务层提供底层 Speaker ID。
3. `TTSResult` 记录实际 Provider、Speaker、模型版本、音频路径、时长、采样率、缓存命中、重试和降级原因。
4. `AudioService` 是视频流水线的唯一语音入口；`pipeline.py`、字幕和渲染代码不再直接调用 TTS SDK。
5. 支持常驻的 Provider 优先复用模型实例并批量生成；并发限制来自 Provider Capability 和目标 Runtime 实测数据，不在业务代码中硬编码。

### 6.2 Voice Registry 与路由

Voice Registry 使用稳定的逻辑音色 ID，例如 `history_male_01`，映射实际 Provider 和 Speaker。注册项至少包含：

- `display_name`、language、tags 和适用场景；
- 首选 Provider/Speaker 与有序 fallback；
- 语速、pitch、FX、参考音频和逐项允许范围；
- 模型/Voice Registry revision、来源、许可和试听资产哈希；
- 是否允许联网、是否允许参考音频及适用生成模式。

路由优先级是“项目显式逻辑音色 → 角色锁定音色 → 项目默认音色 → 已批准全局默认音色”。Agent 不随机选择声音；只有用户要求推荐时，才按语言、角色和标签给出候选并等待试听选择。

核心角色降级不得静默换声：先重试同一 Provider/Speaker，再按角色已批准 fallback 执行；如果会明显改变角色身份，则使 Demo 批准失效并要求重新试听。临时角色可按项目策略回退到通用声音，但必须记录实际 Provider、Speaker 和原因。

### 6.3 兼容迁移与候选接入

1. 先用 Provider Adapter 包装现有 AudioFile、MeloTTS 和 CosyVoice 行为，保持旧项目、缓存和 preflight 可用。
2. 增加 Voice Registry 和 Router；旧 `voice.engine` 配置通过兼容映射生成临时逻辑音色，不要求用户立即迁移。
3. 在独立分支或实验入口验证 Kokoro：固定测试文本、模型版本、许可、启动时间、峰值内存、实时率、中文专名和长文本稳定性。
4. 验证 Edge-TTS 的超时、限流、断网、输出格式和服务变化；网络未获许可时必须在路由前排除。
5. 候选 Provider 只有完成契约测试、试听、许可证记录和项目 preflight 后，才能加入 Production fallback 链。
6. 最后让 `pipeline.py` 只调用 AudioService，并用旧项目完成端到端回归。

### 6.4 试听、缓存与后处理

- CLI 至少支持列出逻辑音色、生成统一文案试听和显示底层 Provider/Speaker、许可及可用状态；Web 音色管理页不属于 MVP。
- 所有 Provider 输出进入统一后处理，最终提供非空 PCM WAV；项目首选 48 kHz mono，无法原生输出时在后处理阶段重采样。
- 后处理包括有界的响度归一化、真峰值限制、可选 EQ/压缩/轻微变调、停顿处理和时长测量；不默认裁掉自然句首句尾。
- 缓存键至少覆盖：规范化文本、逻辑音色及 revision、实际 Provider/Speaker、模型版本、语言、emotion、速度、pitch、输出格式和后处理版本。
- 缓存 metadata 不必保存完整敏感文本，但必须记录内容哈希、来源版本、时长、采样率、实际路由和降级信息。
- Provider 和后处理模型在批次内只加载一次；初始并发由保守策略、Provider Capability 和目标 Runtime benchmark 共同决定。在线 Provider 另设速率限制和重试退避。

### 6.5 Dialogue Timeline 与 Speech QA

- 第一阶段按每句处理后音频的真实样本时长建立字幕和对白时间线，不按字数估时。
- 支持普通接话、语义停顿、打断和少量重叠，分别记录 speech end 与占位 end，避免字幕覆盖纯停顿。
- 文本规范化处理数字、年份、百分比和单位，但必须保存原始显示文本；不得为适配 TTS 改写事实或语义。
- QA 基线包括：文件存在、PCM 格式、非空、可解码、时长范围、静音、截断、爆音、响度、角色映射和缓存元数据。
- ASR/forced alignment 属于可选增强；用于专名、数字、年份、地名和漏读检查，不把文本相似度作为唯一质量结论，也不默认自动替换用户已批准发音。
- 单句失败只重试当前句；超过有界次数后按批准的 fallback 执行，不重新生成无关角色和句子。

### MVP 范围

- 1 个稳定旁白音色。
- 3～5 个可明显区分的核心角色音色。
- 2～3 个可复用的通用配角音色。
- 士兵和群众允许使用基础音色加轻量 FX，但不把 FX 表述为新声纹。
- AudioFile、MeloTTS、CosyVoice 先完成统一契约迁移；Kokoro 和 Edge-TTS 按验证结果渐进加入，不要求同时成为 Production Provider。
- 不训练专属 TTS、不默认启用声音克隆、不引入 Redis/独立队列服务、不建设 Voice Web UI。

### 验收标准

- 同一场景至少支持 3 个角色连续对白。
- 核心角色仅凭声音可基本区分，跨两个测试项目保持相近声纹与基础节奏。
- 所有输出统一为标准 PCM WAV，并通过响度和完整性检查。
- 单句失败可单独重试，不要求重新生成整段或其他角色音频。
- Provider 降级、角色误配和参考音频变更能够使相关缓存准确失效。
- 可以列出和试听可用逻辑音色，并显示实际 Provider、Speaker、许可和可用性。
- Preview 和 Production 使用不同策略但不硬编码固定引擎；Production 使用已批准音色。
- 在线 Provider 断网或未获网络许可时可在任务开始前排除，并按策略回退。
- 现有 `voice.engine` 项目无需立即迁移，仍能通过兼容层生成相同结构的时间线和最终视频。

## 7. Phase 2：电影化静态视频 MVP

### 目标

不依赖生成式视频，仅通过高质量静帧、镜头语言、多角色对白、声音和剪辑完成结构完整的历史微电影。

### Director 首批规则

- `dialogue_lipsync` 默认禁止，仅允许用于经过批准的极短高潮台词。
- 长对白优先拆为 `dialogue_hidden + reaction + insert`。
- 复杂全身动作优先拆为 `action_detail + silhouette + reaction + sound`。
- 宏大场面优先使用远景静帧、烟尘、局部动态和声音扩展规模感。
- 视觉信息通常每 2～5 秒发生变化，但按语义和情绪节点切镜，不机械套用固定间隔。
- 支持 J-cut/L-cut，让声音跨镜头延续并降低正面口型压力。

### 确定性合成能力

- 在现有关键帧和图层能力上增加前后景视差、遮罩、烟雾、火光、粒子和光影叠加。
- 字幕按 Dialogue Timeline 生成，并能区分旁白与角色对白。
- 统一控制转场、色调、画幅、片头和片尾。
- 支持 16:9 与 2.35:1 输出预设。
- 先扩展 FFmpeg 主链路；Remotion 只有在 Renderer Adapter 协议明确并有实际收益时再接入。

### 验收样片

制作一条 45～90 秒历史片段，至少包含 1 个环境建立镜头、2 名角色对白、2 个反应镜头、2 个物件或动作局部特写，以及 1 次 J-cut 或 L-cut；全程不使用 Lip Sync。

### 验收标准

- I2V 完全关闭时仍可生成结构完整、节奏自然且可发布的 MP4。
- 对白期间不强制展示说话者正面嘴部。
- 画面、字幕和对白时间误差处于可接受范围并有自动报告。
- 任一镜头素材缺失时可替换为静帧运镜继续渲染。

## 8. Phase 3：通用 I2V 收口

### 目标

在现有通用 I2V 架构上补齐任务生命周期和自动质量门禁，使 I2V 始终是可替换增强层。

### 剩余建设内容

- 为各类 Runtime Adapter 统一取消、超时、进度与结构化日志。
- 在目标 Runtime 执行硬件探测并重算 RuntimePlan，拒绝不安全或不兼容的计划。
- 自动检测黑屏、严重花屏、损坏帧、异常冻结、错误时长和分辨率。
- 记录 `requested_provider`、`actual_provider`、状态、错误码、重试次数和降级原因。
- 为每个正式支持的 Provider/Runtime 组合维护可复现 smoke 计划。

### 镜头调用策略

优先用于人物转身、抬眼、拔剑等 2～4 秒短动作，以及旌旗、烟尘、火焰、风雪、水面和远景剪影。默认不用于长时间正面说话、精确手部交互、多人近景打斗、骑马近景或需要严格物理连续性的机械动作。

### 降级链

```text
目标 I2V Provider
  ↓ 失败、取消、超时、OOM 或质量不合格
同 Provider 的安全 RuntimePlan，或已明确兼容的轻量 Provider
  ↓ 再失败
已批准本地视频
  ↓
静帧 + 视差/粒子/光影
  ↓
保留声音和剪辑节奏，继续完成成片
```

降级必须重新经过 Planner，不能由 Worker 擅自修改帧数、精度或分辨率后生成不可追踪的结果。

### 验收标准

- 统一 Job 可在兼容的不同 Provider/Runtime 间迁移。
- 系统能区分取消、超时、OOM、Provider 错误、Runtime 错误和质量不合格。
- 全部 I2V 失败时，最终视频仍能以确定性静帧方案完成。
- 本地测试与真实 Runtime smoke 结果分开报告。

## 9. Phase 4：场景声音系统

### 目标

在 Phase 1 已生成并通过 QA 的 Speech Timeline 之上，用声音建立空间、规模和动作感，减少对复杂视频生成的依赖。本阶段不重新实现 TTS、Voice Registry 或 Speech QA。

### 声音层级

```text
Dialogue   旁白与角色对白
Ambience   军营、风雨、树林、城池、人群
SFX        拍案、甲胄、脚步、马嘶、兵器、火焰
BGM        情绪和段落结构
Transition 撞击、呼啸、低频与设计性静默
```

### 建设内容

- 建立带来源、许可证、哈希和标签的环境声与音效资产索引。
- 场景模板可引入基础 Ambience，Director 可在动作节点声明 SFX cue。
- Mixer 以 Dialogue Timeline 的讲话区间为 sidechain 输入，不直接访问 TTS Provider。
- 对白出现时自动压低 BGM 和非必要环境声，段落结束后平滑恢复。
- 支持有界的声像、距离、空间混响和响度控制。
- 将 0.2～0.5 秒静默作为可声明的情绪和转场手段。

### 验收标准

- 静帧场景仅依靠声音也能表达明确动作或空间变化。
- 对白保持清晰，不被 BGM、Ambience 或 SFX 掩盖。
- 最终混音无明显爆音、音量跳变、首尾截断或非预期静音。

## 10. Phase 5：历史世界资产库

### 目标

使同一人物和场景跨作品出现时，在外观、声音、身份和叙事风格上保持连续。

### 建议结构

```text
worlds/three_kingdoms/
├── world.yaml
├── style_guide.yaml
├── characters/
│   └── cao_cao/
│       ├── character.yaml
│       ├── reference_front.png
│       ├── reference_side.png
│       ├── voice_reference.wav
│       └── voice.yaml
├── locations/
├── costumes/
├── props/
├── voices/
├── ambience/
└── sfx/
```

### 资产分级

| 等级 | 对象 | 资产要求 |
| --- | --- | --- |
| S | 核心人物 | 专属外观、参考音色、固定语言风格和高强度连续性检查 |
| A | 重要人物 | 稳定外观、独立或高区分度音色 |
| B | 将领、使者、谋士 | 模板角色加受控差异 |
| C | 士兵、群众 | 通用资产池按规则组合 |

### 验收标准

- 核心人物跨两个样片复用时保持可识别的外观和声音。
- 新项目通过世界 ID 和角色 ID 解析基础图片、声音及风格配置。
- 项目只保存引用和本期派生结果，不复制不可变基础资产。
- 资产来源、许可、版本和哈希可追踪。

## 11. Phase 6：自动导演与质量闭环

### 目标

让系统根据叙事价值、生成风险、资源成本和降级质量选择表现方式，而不是机械调用模型。

### 镜头决策指标

- `narrative_value`：该镜头对信息、人物或情绪的贡献。
- `motion_need`：动态表现是否必要。
- `generation_risk`：模型失败或失真的概率。
- `compute_cost`：时间、显存、额度和金钱成本。
- `fallback_quality`：确定性替代方案的可接受程度。

Director 输出选择结果和可解释原因，例如把“长对白 + 正脸 + 高口型要求”改写为人物开场、画外对白、地图、反应和物件特写；把“万马冲锋”拆为远处烟尘、水杯震动、士兵反应、马蹄声和极短骑兵剪影。

### 自动 QA

- Speech：静音、截断、爆音、响度、异常时长、角色映射、实际 Provider/Speaker、缓存版本和降级记录。
- 发音：可选 ASR/forced alignment 检查漏读、数字、年份、地名和专名；低置信度进入人工复核，不直接覆盖已批准读音。
- 混音：对白可懂度、ducking、非预期静默、声道、首尾截断和峰值。
- 视频：黑屏、冻结、损坏帧、时长、分辨率和帧率。
- 字幕：缺行、重叠、越界、时间错位和说话人样式。
- 时间线：空洞时段、镜头过短、对白被切断及不合理重叠。
- 连续性：核心角色误用通用音色、必要资产缺失和版本漂移。

### 验收标准

- 每个自动选择或降级镜头都有结构化原因报告。
- 单个资产失败后能够按已批准规则替换，不中断整片生成。
- 相同输入、版本、seed 和配置可复现主要时间线、角色映射与选择结果。

## 12. 建议里程碑

### 里程碑 A：多角色静态微电影 MVP

完成 Phase 0 的最小语音协议，以及 AudioService、Voice Registry、TTS Router、Dialogue Timeline、Audio FX、Director 基础规则和 FFmpeg 电影化静态合成。先把现有 AudioFile、MeloTTS、CosyVoice 迁入统一契约，再通过独立 benchmark、许可检查和试听决定是否把 Kokoro、Edge-TTS 加入 Production 候选。

成果是一条不依赖 I2V 的 45～90 秒、多角色、可发布历史微电影。

### 里程碑 B：关键动态镜头增强

补齐 I2V 取消、超时、进度、质量检测和完整降级链。每条验收样片仅使用 1～3 个短 I2V 镜头。

成果是 I2V 只增强高潮，不控制整条流水线能否完成。

### 里程碑 C：历史世界持续生产

建立首个历史世界、核心人物和声音资产，增加场景声音模板、Director 评分和 QA 报告。

成果是新剧本可复用既有角色、场景和声音资产，降低单期制作成本。

## 13. MVP 明确不做

- 不训练角色专属 TTS 模型或 LoRA。
- 不默认启用声音克隆；参考音频必须由用户提供或具有明确授权。
- 不把尚未完成本机 benchmark 和试听的 TTS 候选设为 Production 默认。
- 不在未获联网许可时调用 Edge-TTS 或其他在线语音服务。
- 不追求全片 AI 动态视频。
- 不实现长对白精确 Lip Sync。
- 不挑战多人近景打斗、骑马和复杂手部交互。
- 不将 Worker 固定到某个执行平台、设备后端或硬件型号。
- 不在首个里程碑同时接入大量 TTS/I2V 模型。
- 不先建设复杂 UI，优先稳定 Schema、CLI、状态和流水线。

## 14. 风险与控制措施

| 风险 | 影响 | 控制措施 |
| --- | --- | --- |
| 高成本语音 Provider 在目标 Runtime 上性能不足 | 核心对白耗时 | 通过 capability 和 benchmark 路由；仅用于高价值片段；逐句缓存并提供已批准降级 |
| Kokoro 中文能力或本机性能不符合预期 | 无法承担本地 Production | 固定版本执行 benchmark、长文本测试和用户试听；未通过前仅作为候选 |
| 在线 TTS 服务不可用或策略变化 | 生成中断、隐私或复现风险 | 显式联网许可、超时与限流、本地 fallback、记录服务和音色版本，不作为唯一 Provider |
| 参考声音来源不稳定 | 角色声音漂移 | 固定授权参考音频、参考文本、Speaker ID、参数、版本和哈希 |
| Audio FX 处理过重 | 声音失真 | 限制 pitch/EQ/混响范围；保留原始 WAV；Demo 人工试听 |
| I2V 耗时长或结果不可用 | 阻塞制作 | Hero Shot 预算、超时、取消、质量检测和静帧降级 |
| 角色资产跨期漂移 | 世界连续性下降 | 稳定角色 ID、标准参考图、版本和风格指南 |
| 自动分镜过度切换 | 叙事碎片化 | 按语义和情绪节点切镜，限制无意义视觉变化 |
| 音效和 BGM 版权不明 | 发布风险 | 记录来源、许可证和用途，优先使用明确可商用资产 |
| 协议一次性改动过大 | 破坏旧项目 | 兼容式字段、版本化 Schema、迁移工具和回归样例 |

## 15. 成功指标

- **稳定性**：单个 TTS、I2V 或素材 Provider 失败不影响整片完成。
- **效率**：重复角色、场景和音频能命中缓存，不需每期重建。
- **辨识度**：核心人物声音和外观可跨作品识别。
- **语音可替换性**：业务内容只引用逻辑音色；更换底层 Provider/Speaker 不要求重写 Script。
- **语音可追踪性**：每个输出能追溯逻辑音色、实际 Provider/Speaker、模型版本、后处理版本和降级原因。
- **影视感**：对白不依赖长时间正面口型，镜头、声音和节奏共同叙事。
- **资源可控**：昂贵 I2V 镜头占总时长比例可配置，默认控制在 5%～15%。
- **可扩展性**：新增 TTS、I2V 或执行平台通过 Provider/Adapter 接入。
- **可降级性**：最差情况下仍能输出完整的静帧运镜解说视频。

## 16. 近期优先级

### 当前声画增强修复切片（2026-09-15）

P0：修复 Remotion 图层生命周期、分段关键帧、局部视频时间、转场、BGM 索引和缓存身份；安装包同步含 renderer 与备份哈希清单。

P1：最终逐句 PCM → 带音频/文本哈希的词级 spans → 原文字符区间 cue → 状态事件；提供严格本地 Whisper 适配和外部 Provider 契约，拒绝无根据时间 fallback。加入逐帧保守几何与必需状态检查，不宣称自动语义/主观同步验收。

P2：基础 selector/formula/nodes/coin 图形组件；P3：有界视差、粒子、光扫和暗角。以上是小范围可测试增强，不代表全量 Remotion 编辑器、通用物理系统或整段语音强制对齐服务。真实发音代理映射、浏览器字形测量、逐词字幕高亮、角色语义一致性仍需后续建设。

近期优先推进里程碑 A：

```text
最小内容、Voice Registry 与 TTS Provider Schema
+ AudioService / Provider Contract
+ Voice Registry
+ TTS Provider / Router
+ 现有 AudioFile / MeloTTS / CosyVoice 兼容迁移
+ Kokoro / Edge-TTS 独立验证
+ Audition / Cache / Audio Post Process / Speech QA
+ Dialogue Timeline
+ Director 基础镜头规则
+ FFmpeg 电影化静态合成
```

语音实施顺序应保持小步兼容：先抽离现有 Provider，再引入逻辑音色和 Router，然后接入候选引擎，最后让 `pipeline.py` 只依赖 AudioService。每一步都用旧项目回归，避免一次性重写视频渲染、分镜或图片生成逻辑。

在这套稳定底座上，再收口 I2V 的任务生命周期与质量门禁。项目的长期竞争力不只来自模型能力，而是系统能够判断什么时候该生成、什么时候该剪辑，以及什么时候只需要让观众听见。
