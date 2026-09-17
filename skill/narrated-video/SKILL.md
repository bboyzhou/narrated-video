---
name: narrated-video
description: 制作、继续、迁移或局部修改 NarratedProject 图片/视频解说工程，也可将单张图片制作成本地动态镜头，或通过免费额度优先的浏览器 I2V 异步生成视频。用于 narrated-video、图片解说、NarratedProject、图片电影感短片、分层视差、原图角色骨骼动画、Browser I2V、I2V fallback、字幕对齐及增量渲染。不用于只润色文案、只生成静态图片、普通视频剪辑或无关的 Remotion 开发。
---

# Narrated video production

解说工程以 `NarratedProject v1` 为唯一持久化工程标准。Skill 负责创作判断、审批门禁与编排；Provider 负责生成素材；FFmpeg、Remotion、OpenChatCut Adapter 只消费由工程编译出的派生 RenderPlan。不要把运行时依赖、缓存或渲染器源码写进工程文件。

独立的本地图片动画可使用专用脚本、分层素材和 Blender 工程，不强行套入旁白覆盖规则，也不另创通用工程协议。进入解说工程时，再按现有协议登记为镜头资产。

## 先识别任务

- 新解说工程：环境预检 → 文案批准 → 完整分镜批准 → Demo → Demo 批准 → 全片。
- 继续工程：读取 NarratedProject、`.narrated-video/state.json` 与最近验证报告，从未完成阶段继续。
- 局部修改：先计算对文案、分镜、Demo 和缓存的影响，再只重做受影响范围。
- 旧工程：先通过兼容加载器检查；需要持久化升级时用 `migrate` 输出新文件，禁止原地覆盖。
- 独立单图短片或非 AI I2V 镜头：原图分析 → 全景静帧匹配 → 代表性动作试渲染 → 修正 → 完整渲染与验证。无旁白时不要求口播稿、TTS 或固定 20–40 秒 Demo。
- 解说工程中的本地镜头增强：先制作并验证对应镜头，再登记视频资产，仅重做受影响范围。
- 完整三维转身或绕拍：评估不可见部位、模型、材质及场景重建工作量；固定视角纹理网格不能冒充完整三维角色。
- 浏览器 I2V：只选择确实需要主体运动的已批准镜头；先核实登录、免费额度、实际零费用和下载条件，再异步提交。排队或生成中的任务必须恢复查询，禁止重复提交。

生产工作开始前，按任务读取以下一层参考；不要加载无关分支：

- 新建、继续、审批或交付：读取 [workflow.md](references/workflow.md)。
- 编辑工程 JSON、迁移或排查字段：读取 [project-contract.md](references/project-contract.md)。
- 选择或运行 Image/TTS/I2V：读取 [providers.md](references/providers.md)。
- 选择 FFmpeg、Remotion 或 OpenChatCut：读取 [adapters.md](references/adapters.md)。
- 本地单图动画、分层、骨骼重建或“没有动态效果”的诊断：读取 [local-image-animation.md](references/local-image-animation.md)。
- 使用网页免费额度生成视频、恢复任务或导入下载结果：读取 [browser-i2v.md](references/browser-i2v.md)，再只读取实际使用平台的操作指南。

## 不可破坏的边界

以下协议与运行计划边界适用于解说工程及其生成任务；独立本地镜头按上述专用制作流程保存源文件和验证记录。

- 文案、镜头、Provider 意图与可编辑参数只写入 NarratedProject。
- 实际 GPU 参数只写入系统生成的 RuntimePlan；Provider、Profile、Runtime 与 Hardware 保持独立。
- 配音、图片、I2V 结果和本地预渲染镜头先登记为带来源、版本与哈希的资产，再由镜头引用。
- I2V 失败只影响对应镜头，保留失败记录并使用已批准 fallback。
- RenderPlan 是按真实音频帧编译的临时产物，不是第二种工程格式。
- Adapter 能力不足时生成 loss/capability report；不得静默忽略 graphics、effects、parallax 或可编辑性。
- Runtime 路径、审批、缓存和生成任务状态保存在 `.narrated-video/`，不进入可移植工程。

## 执行入口

解说工程优先使用项目仓库中的 `scripts/pipeline.py`。若仓库位置未知，要求用户选择现有路径；不要安装依赖或猜测路径。Skill 自带的薄入口只转发到用户明确选择的 runtime：

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
i2v-plan          为浏览器 I2V 镜头建立持久任务
i2v-next          领取下一项语义化浏览器动作
i2v-observe       校验并保存真实页面观察结果
i2v-status/sync   查看状态／验证下载并接入工程
```

独立本地镜头使用已确认可用的 Python、Blender、FFmpeg 或 Remotion 编写任务专用脚本，记录实际调用命令。此分支是制作指南，尚无通用自动重建命令；不要编造 pipeline 子命令，也不要把已授权的本地制作自动切换为 AI I2V。

浏览器动作由具备当前页面访问能力的 Computer Use 执行；Python 命令只管理确定性的请求、状态和媒体。没有真实页面回执时，不得把任务标为已提交、完成或已下载。Browser I2V 不自动购买额度、不保存账号密码，也不承诺退出进程后自动轮询。

## 验证与汇报

执行与任务相匹配的 schema、迁移、Adapter、媒体和人工视听检查。独立本地镜头重点检查构图匹配、独立动作、接触点、遮挡和完整解码；未触及工程协议时不要求 schema 或迁移测试。明确区分自动检查、实际观看/试听与未验证项。

按实际任务交付源工程或脚本、MP4、适用时的 SRT、素材清单和验证报告；解说工程另保留审批记录。说明固定视角重建与完整三维的区别，以及烘焙后哪些效果仍可编辑。仅复制 deliverables 不等于可移植工程。
