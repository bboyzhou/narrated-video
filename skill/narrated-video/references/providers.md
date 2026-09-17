# Provider 边界

## 本地镜头动画的选择

用户要求非 AI I2V、需要保留原图质感，或镜头适合可控的分层与关节动画时，可主动选择 [本地图片动画](local-image-animation.md)。这是一种制作方式，不是新的 AI Provider、Profile 或 I2V Runtime。

本地分支可直接作为首选，不必先运行 I2V。作为 I2V 失败后的替代时，仅在现有授权覆盖该替代方案时执行，保留失败记录；禁止 AI I2V 的任务不得自动切换到生成式服务。本地完成的视频按普通资产规则验证和登记，能力与编辑性边界见 [adapters.md](adapters.md)。

## Image

Image Provider 生成或登记图片资产；提示词、负面提示词、来源、许可、版本与哈希进入 NarratedProject。渲染器不联网生成图片。

## TTS

TTS Provider 接收批准文本与逻辑音色，返回逐句 PCM WAV、实际 Provider/Speaker、版本、时长和哈希。后处理负责响度、软语速归一化和语义停顿；字幕继续读取原始 `text`。

使用整段录音时先取得可靠分句边界再切分。不要按字符比例伪造时间戳。词级动画只接受与最终音频哈希匹配的对齐结果。

## I2V

保持以下边界：

```text
Profile + Provider + Runtime + Hardware → Planner → RuntimePlan → Worker
```

- Profile 只使用 `smoke/fast/balanced/quality/max_quality`。
- Provider 只表示模型或服务；Runtime 只表示运行位置。
- dtype、尺寸、帧数、steps、attention、offload、TeaCache、world size 只允许出现在 RuntimePlan。
- Worker 不选择 Provider/Profile/Runtime，也不猜 GPU。
- 正式远端任务固定模型、源码和依赖版本，先预检再加载模型。
- OOM 或 Worker 被杀后退出旧进程；已完成镜头不重做。

生成视频始终是镜头增强资产。导入器核对 request/cache key、RuntimePlan digest、完整解码、尺寸、时长与哈希；失败时继续使用已批准图片运镜或本地视频。

## Browser I2V

`browser_i2v` 是网页执行方式，不是模型名称，也不使用模型 Worker 的 RuntimePlan。工程只保存平台偏好和 `free_only=true`；远端任务编号、登录态、额度快照、排队状态和网页观察保存在 `.narrated-video/i2v/`。

Browser Executor 只负责登录态检查、页面导航、上传、填写参数、提交、读取状态和下载。任务去重、状态机、重试、路由、媒体验证和工程更新由 Python 完成。使用前读取 [browser-i2v.md](browser-i2v.md)。

当前支持的平台标识是 `pixverse`、`jimeng` 和 `kling`。存在操作指南只表示系统知道如何检查该平台；只有真实检查确认账号可用、免费额度足够且本次费用为零后，平台才可进入路由。网页免费额度不能推导出 API 免费额度。
