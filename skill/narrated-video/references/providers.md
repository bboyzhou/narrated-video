# Provider 边界

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
