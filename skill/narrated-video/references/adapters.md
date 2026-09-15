# Render Adapter

NarratedProject 在 TTS 和素材落地后编译为 frame-exact `RenderPlan v1`。Adapter 只读取该派生计划，不读取 `pipeline.py` 内部字典。

## FFmpeg

适合确定性图片运镜、视频镜头、图层关键帧、转场、字幕和混音。不支持 graphics、effects 或 parallax；命中这些字段时必须拒绝或由用户选择其他 Adapter。

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
