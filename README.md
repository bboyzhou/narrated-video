# narrated-video

`narrated-video` 是一个面向 Codex 的图片运镜解说视频 skill。它把口播稿、图片、视频、配音、字幕和配乐组织为可审阅、可恢复、可局部重跑的项目，最终通过 Python + FFmpeg 输出 MP4。

它适合知识讲解、产品介绍、故事叙述、图文纪录和其他以旁白驱动的短视频；重点是稳定的内容生产流程，而不是完整替代非线性剪辑软件或生成式视频平台。

## 当前能力

### 内容与审批

- 从对话文案或本地文本创建项目，维护口播稿、制作纲要和分镜。
- 在口播稿、完整分镜和 Demo 等关键阶段记录用户的实际批准，避免未确认内容直接进入全片渲染。
- 使用项目状态、缓存键和阶段产物支持断点恢复、局部修改与增量重跑。

### 画面与时间线

- 使用本地图片或视频作为镜头，也可在单个镜头中叠加多个图片/视频图层。
- 支持位置、缩放、旋转、透明度关键帧，以及常见推拉、平移、定格和转场效果。
- 根据真实配音时长生成时间线，并将镜头、字幕和音频对齐。
- 支持可选 Remotion Renderer Adapter：以统一 Render Plan 驱动 React 画面，音频混音仍由 FFmpeg 完成；Remotion 失败时可回退 FFmpeg。
- 可查询离线素材库；网络素材需要 Agent 先核对来源与许可并下载到本地，渲染器本身不联网。

### 配音、字幕与声音

- 支持已有音频文件，以及 MeloTTS、CosyVoice 等可选本地 TTS 工作流。
- 支持发音检查、分段合成、停顿和语速调整，并以实际 WAV 时长作为时间线依据。
- 生成字幕并完成背景音乐选择、裁切、循环、淡入淡出和响度混合。

### 可选生成式视频

- 可把少量已批准的 Hero Shot 路由到 I2V Provider，目前协议覆盖 `skyreels_v2`、`wan22`、`cogvideox`、`svd_xt` 和 `cloud_i2v`。
- 将速度/质量/成本意图（`Profile`）、模型或服务（`Provider`）、执行位置（`Runtime`）与实际硬件（`Hardware`）分开建模。
- Provider Planner 根据上述信息生成唯一的底层执行描述 `RuntimePlan`；内容型 Job 不携带 dtype、帧数、steps 或 offload 等实现参数。
- 支持 Local、Kaggle、Colab、RunPod、Remote Worker 和 Cloud API 等 Runtime 抽象，以及远端硬件探测后重新规划。
- I2V 超时、OOM、Provider 失败或产物损坏只影响当前镜头；系统记录原因并回退到已批准的本地素材或图片运镜，不阻塞全片。

## 能力边界

| 范围 | 当前状态 | 边界说明 |
| --- | --- | --- |
| 项目状态、审批门禁、时间线、字幕、合成与 MP4 渲染 | 内置稳定主链路 | 由仓库脚本和 FFmpeg 执行；仍需人工审看内容、构图、节奏和听感。 |
| 图片/视频图层与关键帧运镜 | 内置 | 适合确定性二维合成，不等同于 AE、Premiere 或 DaVinci Resolve 的完整编辑能力。 |
| 文案润色、分镜设计、素材搜索、图片生成和许可核对 | Agent 协作能力 | 由 Codex 及其可用工具完成，不是 `pipeline.py` 内部的无人值守网络服务。 |
| MeloTTS、CosyVoice 和其他本地模型 | 可选依赖 | 需要相应环境、模型缓存和可用设备；skill 不会自行安装依赖或下载模型。 |
| 本地或远端 I2V | 可选增强层 | 需要真实模型、GPU、磁盘、平台额度或 API 凭据；仓库单元测试不能证明目标 Runtime 当前可用。 |
| Cloud I2V | 通用协议边界 | `cloud_i2v` 提供统一接口和规划语义；具体供应商适配、鉴权、计费及服务条款由部署方负责。 |
| Remotion Renderer Adapter | 可选增强层 | `renderers/remotion` 使用固定版本的 Remotion 4；需配置 `runtime.browser`，不在渲染时自动下载浏览器；音频继续由 FFmpeg 混音。 |
| 主观质量与事实正确性 | 需要人工确认 | 解码、时长、分辨率和文件完整性可以自动验证，但事实、审美、人物一致性和口播自然度不能仅靠自动检查保证。 |

当前不提供骨骼动画、自动抠像与跟踪、逐词卡拉 OK 高亮、完整 GUI 时间线编辑器，也不保证生成式人物在多镜头间保持身份一致。若项目依赖这些能力，应在外部工具中完成后，以已批准的图片、视频或音频资产导入。

## 架构设计

主链路将“内容意图”“执行策略”和“媒体渲染”分离。普通镜头直接进入确定性合成；只有分镜明确标记且处于预算内的 Hero Shot 才进入 I2V 分支。

```text
用户输入 / 本地文档
        │
        ▼
口播稿 → 制作纲要 → 完整分镜 → Demo
  │                       │        │
  └──────── 审批门禁与项目状态 ────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
      本地图片/视频/TTS          可选 I2V Orchestrator
                                      │
                          Profile + Provider + Runtime
                                      │
                               Hardware Detection
                                      │
                                RuntimePlan + Job
                                      │
                               Worker 执行与产物导入
                                      │
                         失败 → 本地素材/图片运镜回退
              └───────────┬───────────┘
                          ▼
               时间线、字幕、配乐与图层合成
                          │
                 Remotion（可选）
                         │
                 FFmpeg（主链路/混音）
                          │
                          ▼
                 校验、Demo 与最终交付物
```

### 分层职责

| 层 | 主要职责 | 关键实现/协议 |
| --- | --- | --- |
| Skill 编排层 | 解释用户目标，安排审批、素材准备、Demo 和最终交付 | [`SKILL.md`](SKILL.md) |
| 项目与状态层 | 保存配置、分镜、批准记录、阶段状态与缓存信息 | [`scripts/pipeline.py`](scripts/pipeline.py)、[`references/project.md`](references/project.md) |
| 内容合成层 | 将镜头、图层、关键帧、字幕与音频映射到统一时间线 | [`scripts/composition.py`](scripts/composition.py)、[`references/composition.md`](references/composition.md) |
| I2V 控制层 | 选择 Provider/Runtime，探测硬件，生成 RuntimePlan，执行预算与回退策略 | [`scripts/runtime_planner.py`](scripts/runtime_planner.py)、[`scripts/generators/`](scripts/generators/) |
| I2V 执行层 | 在目标 Runtime 中消费 Job 与 RuntimePlan，并返回标准化结果 | [`scripts/workers/`](scripts/workers/)、[`kaggle/`](kaggle/) |
| 导入与校验层 | 校验缓存键、计划、哈希、分辨率、时长及完整解码，再登记生成资产 | [`scripts/import_generated_videos.py`](scripts/import_generated_videos.py) |
| 渲染与交付层 | 使用 FFmpeg 合成 Demo/全片并检查最终媒体 | [`scripts/pipeline.py`](scripts/pipeline.py) |

### I2V 核心约束

- **Profile 只表达意图**：`smoke`、`fast`、`balanced`、`quality`、`max_quality` 不绑定特定硬件参数。
- **Provider 只描述模型或服务**：不把 Kaggle、RunPod 等执行位置编码进 Provider ID。
- **Runtime 只描述执行位置**：平台不决定模型能力，也不直接出现在内容 Job 中。
- **RuntimePlan 是执行参数的唯一来源**：分辨率、帧数、fps、steps、dtype 和 offload 等参数由 Planner 生成。
- **Job 只描述内容**：输入图片、提示词、语义运动、约束、seed、目标时间线时长和输出位置保持可迁移。
- **失败可降级**：生成式视频从不成为最终成片的单点故障。

完整协议见 [I2V Provider 架构](references/i2v-provider-architecture.md)，操作流程见 [生成式视频](references/generated-video.md)，Provider 支持情况见 [Provider 矩阵](references/video-provider-matrix.md)。

## 项目规划

AI Mini Studio 的长期演进方向、阶段成熟度、验收标准和风险控制见 [项目 RoadMap](doc/roadmap.md)。RoadMap 是项目规划，不属于 skill 执行协议；其中标为“规划中”的模块不能视为当前可调用能力。

当前优先级是补齐多角色语音和电影化静态视频底座；通用 I2V 架构已完成主体重构，后续重点是取消、进度、自动质量检测和真实 Runtime smoke。

## 目录结构

```text
narrated-video/
├── SKILL.md                 # skill 入口与工作流约束
├── scripts/                 # 项目、合成、规划、导入和测试脚本
│   ├── generators/          # Provider 能力与路由
│   ├── runtimes/            # Runtime 注册与平台抽象
│   └── workers/             # 标准 Worker 契约
├── schemas/                 # Job、RuntimePlan、Provider Capability 等 Schema
├── references/              # 按需加载的详细规范
├── doc/                     # RoadMap 等项目级设计与规划文档
├── templates/               # 项目和测试计划模板
├── kaggle/                  # Kaggle Worker 入口
├── notebooks/               # 可移植 Runtime 示例
└── evals/                   # skill 行为评测场景
```

## 使用

将本目录作为 skill 使用，入口说明见 [SKILL.md](SKILL.md)。脚本命令和项目 JSON 见 [项目规范](references/project.md)，分镜规范见 [分镜规范](references/storyboard.md)；首次使用先阅读 [运行环境](references/runtime.md)，选择 Python、FFmpeg、NLTK 和模型缓存路径。

```powershell
python scripts/pipeline.py init D:/videos/example/project.json --source D:/documents/source.md
python scripts/pipeline.py paths D:/videos/example/project.json
python scripts/pipeline.py configure D:/videos/example/project.json --python D:/tools/python.exe --ffmpeg D:/tools/ffmpeg.exe --offline true
python scripts/pipeline.py preflight D:/videos/example/project.json
python scripts/pipeline.py remember-runtime D:/videos/example/project.json
python scripts/pipeline.py check D:/videos/example/project.json --stage script
python scripts/pipeline.py record D:/videos/example/project.json --stage script --quote "用户实际批准回复"
python scripts/pipeline.py check D:/videos/example/project.json
python scripts/pipeline.py record D:/videos/example/project.json --stage storyboard --quote "用户实际批准回复"
python scripts/pipeline.py video-prepare D:/videos/example/project.json --stage demo --ffmpeg PATH
# 在选择的 Runtime 中运行任务包并下载输出后：
python scripts/pipeline.py video-import D:/videos/example/project.json --stage demo --results OUTPUT_ZIP --ffmpeg PATH
python scripts/pipeline.py video-status D:/videos/example/project.json --stage demo --ffmpeg PATH
```

`preflight` 必须在文案和制作方案前通过；`remember-runtime` 会把通过门禁的运行环境保存到用户级配置，供后续项目和 Agent 会话复用。两者都不会自动安装依赖或下载模型。

## 验证

测试使用隔离的临时项目：

```powershell
python scripts/test_runtime.py
python scripts/test_storyboard.py
python scripts/test_pipeline.py --ffmpeg PATH --image IMAGE --alternate-image IMAGE2 --output TEMP_DIR
python scripts/test_motion.py --ffmpeg PATH --image IMAGE
python -m unittest discover -s scripts -p "test_*.py"
```

这些检查覆盖项目协议、规划、导入、回退和渲染逻辑。涉及真实 TTS、I2V 模型或远端平台时，还应在目标 Runtime 单独执行 smoke test，并人工审看最终视频。

`evals/evals.json` 保存用于审核 skill 行为的场景，不是视频素材或生产配置。
