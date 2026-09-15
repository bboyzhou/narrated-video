# NarratedProject v1

`NarratedProject v1` 是唯一可编辑、可迁移、可持久化的工程协议。权威 Schema 位于 runtime 仓库的 `schemas/narrated-project-v1.schema.json`。

```text
NarratedProject
├─ project       ID 与标题
├─ sources       批准稿及原始输入引用
├─ creative      creative brief 与风格
├─ providers     image、tts、i2v 的选择和固定版本
├─ assets        可选素材库入口
├─ timeline      narration、shots、music、demo
└─ render        adapter、画布、字幕、节奏、运镜与混音
```

工程实例必须包含：

```json
{
  "$schema": "https://openai.local/narrated-video/narrated-project-v1.schema.json",
  "kind": "NarratedProject",
  "version": 1
}
```

镜头同时保存创作语义与可执行描述，避免旧 project/storyboard 的重复字段漂移。旁白 ID 必须唯一，shots 必须按顺序完整覆盖旁白一次，Demo 镜头必须连续。

以下内容不属于工程协议：本机程序路径、密钥、审批记录、缓存、实际 GPU、I2V RuntimePlan、临时 RenderPlan 和验证日志。

旧工程只读兼容；迁移时在原文件旁创建新文件以保持相对素材路径，禁止覆盖原文件：

```powershell
python scripts/pipeline.py migrate project.json --output narrated-project.json
```

`project.schema.json` 仅作为兼容别名。新增字段必须先进入 v1 Schema 和语义校验，再由编译器与 Adapter 使用；不要只在 `pipeline.py` 增加私有字段。
