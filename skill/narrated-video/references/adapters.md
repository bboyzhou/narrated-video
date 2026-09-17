# Render Adapter

NarratedProject 在 TTS 和素材落地后编译为 frame-exact `RenderPlan v1`。Adapter 只读取该派生计划，不读取 `pipeline.py` 内部字典。

## FFmpeg

适合确定性图片运镜、视频镜头、图层关键帧、转场、字幕和混音。不支持 graphics、effects 或 parallax；命中这些字段时必须拒绝或由用户选择其他 Adapter。

此限制指当前 Adapter 对结构化字段的支持，不代表 FFmpeg 无法编码由 Blender/Python 已合成的复杂镜头。预渲染视频可作为普通视频素材使用，但其内部视差、骨骼和粒子已烘焙。

## Blender / Python 本地预渲染

制作步骤见 [local-image-animation.md](local-image-animation.md)。这是素材制作阶段，不是新增 Render Adapter，也没有新增 pipeline 命令。

- **预渲染镜头**：使用 Blender、Python 或 Remotion 生成合成帧，再由 FFmpeg 编码。独立任务直接交付；接入解说工程时按现有 Schema 的视频镜头和资产规则引用，保留来源、版本、哈希与媒体信息。不为本地素材伪造 I2V request key 或 RuntimePlan，也不假设 I2V 专用导入器接受任意视频。
- **分层交付**：需要继续编辑时额外交付 Alpha 序列、独立音轨、图层、脚本或打包纹理的 `.blend`。先验证接收工具对 Alpha、帧率和轨道的支持；不能仅凭导出素材就声称完成可编辑时间线导入。
- **可移植性**：素材使用可解析的相对路径；本机程序路径、依赖和缓存留在运行环境中。只使用真实存在且已核对语义的 Schema 字段；协议表达不了的制作细节保留在源工程和制作记录中，不私自扩展字段。
- **时序**：镜头持续时间与最终时间线一致。接入有旁白工程时由真实音频帧数决定需要的长度；核对是否发生额外裁切、二次运镜或变速，避免破坏预渲染动作与接触关系。
- **可编辑性**：普通视频素材仍可剪辑、调色和混音；内部效果需回源工程重渲染。明确报告烘焙造成的编辑能力损失。

## Remotion

适合 graphics、effects、parallax 和教学动画。Adapter 可把绝对素材路径暂存到自身资源目录，但不得把暂存路径写回 NarratedProject。Node、浏览器、`node_modules` 和 bundle cache 是外部 runtime，不属于 Skill 发布包。

渲染前检查固定 lockfile、本地依赖和显式浏览器路径；真实兼容性必须通过浏览器 smoke。失败回退时写入实际 Adapter 和原因；增强字段不能回退到不支持它们的 FFmpeg。

## OpenChatCut

OpenChatCut 用于移交可编辑多轨工程。Adapter 将 RenderPlan 映射为视频、overlay、旁白、音乐和字幕轨，并生成 capability/loss report。

其内部持久化格式可能演进，因此只通过公开 MCP/EditorCore 命令应用导入计划，禁止直接写 OpenChatCut 私有本地存储。没有运行中的编辑器时只生成离线 import plan，不声称已创建工程。

```powershell
python scripts/pipeline.py adapter-export narrated-project.json `
  --adapter openchatcut --stage full --output openchatcut-import.json
```
