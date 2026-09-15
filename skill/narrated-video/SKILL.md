---
name: narrated-video
description: 制作、继续、迁移或局部修改 NarratedProject 图片/视频解说工程，覆盖文案与分镜审批、TTS、字幕、声画对齐、图片运镜、Remotion、I2V fallback、Demo 和增量渲染。用户提到 narrated-video、图片解说、解说视频工程、NarratedProject、Wan/TI2V/Kaggle、词级动画、断点恢复或可编辑时间线时使用。不用于只润色文案、只生成单张图片、普通视频剪辑，或与解说工程无关的 Remotion 开发。
---

# Narrated video production

把 `NarratedProject v1` 视为唯一可持久化的视频工程标准。Skill 负责创作判断、审批门禁与编排；Provider 负责生成素材；FFmpeg、Remotion、OpenChatCut Adapter 只消费由工程编译出的派生 RenderPlan。不要把运行时依赖、缓存或渲染器源码写进工程文件。

## 先识别任务

- 新工程：环境预检 → 文案批准 → 完整分镜批准 → Demo → Demo 批准 → 全片。
- 继续工程：读取 NarratedProject、`.narrated-video/state.json` 与最近验证报告，从未完成阶段继续。
- 局部修改：先计算对文案、分镜、Demo 和缓存的影响，再只重做受影响范围。
- 旧工程：先通过兼容加载器检查；需要持久化升级时用 `migrate` 输出新文件，禁止原地覆盖。

生产工作开始前，按任务读取以下一层参考；不要加载无关分支：

- 新建、继续、审批或交付：读取 [workflow.md](references/workflow.md)。
- 编辑工程 JSON、迁移或排查字段：读取 [project-contract.md](references/project-contract.md)。
- 选择或运行 Image/TTS/I2V：读取 [providers.md](references/providers.md)。
- 选择 FFmpeg、Remotion 或 OpenChatCut：读取 [adapters.md](references/adapters.md)。

## 不可破坏的边界

- 文案、镜头、Provider 意图与可编辑参数只写入 NarratedProject。
- 实际 GPU 参数只写入系统生成的 RuntimePlan；Provider、Profile、Runtime 与 Hardware 保持独立。
- 配音、图片和 I2V 结果先登记为带来源、版本与哈希的资产，再由镜头引用。
- I2V 失败只影响对应镜头，保留失败记录并使用已批准 fallback。
- RenderPlan 是按真实音频帧编译的临时产物，不是第二种工程格式。
- Adapter 能力不足时生成 loss/capability report；不得静默忽略 graphics、effects、parallax 或可编辑性。
- Runtime 路径、审批、缓存和生成任务状态保存在 `.narrated-video/`，不进入可移植工程。

## 执行入口

优先使用项目仓库中的 `scripts/pipeline.py`。若仓库位置未知，要求用户选择现有路径；不要安装依赖或猜测路径。Skill 自带的薄入口只转发到用户明确选择的 runtime：

```powershell
python scripts/cli.py --root D:/path/to/narrated-video -- --help
```

关键命令：

```text
init              创建 NarratedProject v1
migrate           从旧 project.json + storyboard.json 生成 v1
paths/preflight   检查用户选择的运行环境
check/record      校验并记录真实批准回复
tts/render/verify 生成并验证媒体
video-prepare     生成外部 I2V 任务包
video-import      校验并登记生成结果
adapter-export    导出 OpenChatCut 可编辑时间线计划
```

## 验证与汇报

执行与改动风险相匹配的 schema、迁移、Adapter、媒体和人工视听检查。明确区分自动检查、实际观看/试听与未验证项。交付工程、MP4、SRT、素材清单、审批记录和验证报告；仅复制 deliverables 不等于可移植工程。
