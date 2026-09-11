# 生成式视频素材

生成式视频是可选的外部素材阶段，不属于最终渲染器。项目仍只声明 `type: image/video`；需要动态生成的分镜使用 `asset_strategy: generated_video`。成功生成的 MP4 在运行时解析成普通 `type: video`，失败、缓存失配或文件损坏时继续使用项目镜头原有的图片/视频素材。

当前 provider：

- `wan22_kaggle`：Wan2.2 TI2V-5B，Kaggle 双 GPU 手动任务；
- `cogvideox_colab`：旧 CogVideoX/Colab 工作流的兼容适配器。

不要使用新的 `type: ai_video`，也不要把 Wan、Kaggle 或 CUDA 逻辑写入 FFmpeg 合成器。

## 项目和分镜配置

项目级配置：

```json
{
  "video_generation": {
    "enabled": true,
    "provider": "wan22_kaggle",
    "execution": "remote_manual",
    "policy": "highlights",
    "max_scenes": 5,
    "providers": {
      "wan22_kaggle": {
        "model_revision": "实际固定的模型或 Kaggle Dataset 版本",
        "size": "1280*704",
        "max_frame_num": 121,
        "world_size": 2,
        "ulysses_size": 2
      }
    }
  }
}
```

`model_revision` 不能使用 `main/latest`；它必须标识实际挂载的权重版本，否则无法保证缓存安全。`policy` 支持 `none/highlights/selected/all`。`highlights` 只表达创作策略，具体镜头仍必须在已批准分镜中显式标记，脚本不会擅自做语义选择。

每个生成镜头先保留可渲染的 fallback：

```json
{
  "id": "S003",
  "asset_strategy": "generated_video",
  "source_image": "images/S003.png",
  "prompt": "第一帧的主体、服装、地点、构图和光色",
  "negative_prompt": "文字、水印、身份改变、时代错误",
  "motion_prompt": "Banners move naturally. Dust drifts slowly. Slow cinematic push-in.",
  "motion_constraints": ["preserve identity", "preserve costume", "preserve composition"],
  "generation": {
    "provider": "wan22_kaggle",
    "mode": "i2v",
    "duration_target": 5,
    "seed": 38123
  },
  "type": "image",
  "motion": "push"
}
```

项目 `shots` 中的 `type/asset/motion` 始终表示 fallback。导入器只增加 `generated_video` 结果记录，不覆盖这些字段，因此 storyboard 批准保持有效；Demo 镜头的生成结果改变仍会使 Demo 批准失效。

## V1：准备任务包

完整分镜批准后，仅准备当前阶段：

```powershell
python scripts/pipeline.py video-prepare D:/videos/example/project.json `
  --stage demo `
  --ffmpeg D:/tools/ffmpeg.exe
```

也可直接调用底层脚本：

```powershell
python scripts/prepare_video_jobs.py D:/videos/example/storyboard.json `
  --project D:/videos/example/project.json `
  --stage demo
```

默认输出 `.narrated-video/video-jobs-demo.json` 和同名 ZIP。一个任务包只含一个 provider；混用 provider 时分别传 `--provider`。任务包格式见 `schemas/video-job.schema.json` 和 `templates/wan_job.json`。

缓存键为以下内容的规范化 SHA-256：provider、模型及固定版本、backend 推理配置、源图内容哈希、motion prompt、约束、seed、帧数与采样参数。缓存命中不会复制源图或重新提交任务；缓存文件内容哈希不符时自动视为 miss。

## Kaggle Worker

`kaggle/run_wan_job.py` 是固定入口，负责寻找三个挂载输入：

1. 解压后的 `video_jobs.json` 和 `input/`；
2. Wan2.2 官方源码目录；
3. Wan2.2-TI2V-5B 权重目录。

自动发现不唯一时，可设置 `NARRATED_VIDEO_JOB`、`WAN22_ROOT`、`WAN22_CKPT`。复制 `kaggle/kernel-metadata.example.json` 为 `kernel-metadata.json`，填写自己的 Kaggle 用户名和输入源，在 Kaggle UI 中确认双 GPU 后运行。

入口通过 `torch.distributed.run` 启动 `world_size=2`。`wan_worker.py` 每个 rank 只构造一次 `WanTI2V`，随后在同一次模型加载中依次处理全部镜头。输出写到 `/kaggle/working/output/<shot_id>.mp4`，并增量写入 `/kaggle/working/results.json`。不要改成每个镜头调用一次官方 `generate.py`，否则会重复加载模型。

官方 TI2V-5B 配置为 24fps、默认 121 帧，支持 `1280*704` 和 `704*1280`。任务准备器会将目标时长归一为 `4n+1` 帧并限制到 `max_frame_num`。双 T4 只代表官方分布式参数在结构上成立，不代表显存和 Kaggle 配额一定足够；首次运行必须先用一个 Demo 镜头实测。

Worker 不自动下载模型、不安装依赖。Kaggle 环境必须已有 Wan 官方依赖、源码和权重；实际源码/权重版本应与 `model_revision` 记录一致。

## 导入、状态和 fallback

下载 Kaggle 输出后：

```powershell
python scripts/pipeline.py video-import D:/videos/example/project.json `
  --stage demo `
  --jobs D:/videos/example/.narrated-video/video-jobs-demo.json `
  --results D:/downloads/wan-output.zip `
  --ffmpeg D:/tools/ffmpeg.exe

python scripts/pipeline.py video-status D:/videos/example/project.json `
  --stage demo `
  --ffmpeg D:/tools/ffmpeg.exe
```

导入器使用 `ffprobe`；找不到时直接用所选 FFmpeg 解码首帧并读取流信息。它检查 shot ID、缓存键、MP4 视频流、分辨率、时长和输出哈希。有效文件保存到：

```text
assets/generated-video/<provider>/<cache_key>/<shot_id>.mp4
```

索引和最近报告分别写入：

```text
.narrated-video/generated-video-index.json
.narrated-video/generated-video-import.json
```

`results.json` 标记失败、输出缺失、当前缓存键不匹配或文件损坏时，镜头状态为 `fallback`，继续使用已批准的项目 `asset + motion`，不阻塞整片。未审阅的生成结果不能静默进入全片；导入 Demo 后先渲染、抽帧和观看，再记录 Demo 批准。

## 审批顺序

口播批准 → 完整 storyboard 批准 → Demo 静态源图 → `video-prepare --stage demo` → Kaggle 生成 → `video-import --stage demo` → 渲染和确认 Demo → 准备/导入其余镜头 → 渲染全片。

每个结果记录 provider、模型/版本、seed、源图哈希、motion prompt、生成参数、输出哈希和使用条件。除非已核对实际模型与素材条款，不声称生成结果可商用。

## V2 边界

在目标 Kaggle 账号上证明双 GPU 能稳定生成一个 Demo 镜头后，才增加 `kaggle kernels push/status/output` 自动提交。自动化沿用同一任务包、Worker、结果格式、缓存和导入器，不改变项目 schema 或渲染器。
