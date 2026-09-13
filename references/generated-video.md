# 生成式视频素材

生成式视频是可选外部素材阶段，不属于最终渲染器。项目镜头仍声明可直接渲染的 `type: image/video` fallback；成功生成的 MP4 在运行时解析成普通视频素材，失败、缓存失配或文件损坏时继续使用已批准 fallback。

架构边界、Registry、RuntimePlan 和旧配置迁移规则见 [I2V Provider 架构](i2v-provider-architecture.md)。Provider 对比与试验记录见 [视频 provider 测试矩阵](video-provider-matrix.md)。

## 配置与分镜

项目分别配置 Provider、通用 Profile 和 Runtime：

```json
{
  "video_generation": {
    "enabled": true,
    "provider": "skyreels_v2",
    "profile": "balanced",
    "runtime": {"type": "kaggle"},
    "policy": "highlights",
    "i2v_budget": {
      "enabled": true,
      "max_shots": 3,
      "max_generated_seconds_per_shot": 4
    },
    "providers": {
      "skyreels_v2": {
        "model": "Skywork/SkyReels-V2-I2V-1.3B-540P",
        "model_revision": "e86231f3882225e5a93eeec740c77bc7f01954ca",
        "source_revision": "9351d13152207cc04de780e055346b08ade0b851"
      }
    }
  }
}
```

Provider 配置只保存模型/源码/服务版本等元数据。不要在这里填写 dtype、帧数、steps、offload、attention、TeaCache 或 world size。

每个生成镜头保留可渲染 fallback：

```json
{
  "id": "S003",
  "asset_strategy": "generated_video",
  "source_image": "images/S003.png",
  "prompt": "第一帧的主体、服装、地点、构图和光色",
  "negative_prompt": "文字、水印、身份改变、时代错误",
  "motion_prompt": "Banners move naturally. Dust drifts slowly.",
  "motion_constraints": ["preserve identity", "preserve composition"],
  "generation": {
    "provider": "skyreels_v2",
    "mode": "i2v",
    "target_duration_sec": 8,
    "seed": 38123,
    "motion": {"strength": "high", "camera": "tracking"}
  },
  "type": "image",
  "motion": "push"
}
```

`target_duration_sec` 是最终时间线镜头时长，不要求 I2V 一次生成相同时长。Planner 依据 Profile、Provider、Runtime 与 Hardware 决定实际生成长度；Remotion 负责必要的慢放、freeze、push/pan 和转场延展。

## 准备任务包

完整分镜批准后仅准备当前阶段：

```powershell
python scripts/pipeline.py video-prepare D:/videos/example/project.json `
  --stage demo `
  --ffmpeg D:/tools/ffmpeg.exe
```

或调用底层脚本：

```powershell
python scripts/prepare_video_jobs.py D:/videos/example/storyboard.json `
  --project D:/videos/example/project.json `
  --stage demo
```

输出 `.narrated-video/video-jobs-demo.json` 与 ZIP。一个包只含一个 Provider 和一个 RuntimePlan；混用 Provider 时用 `--provider` 分包。任务包必须符合 `schemas/video-job.schema.json`，RuntimePlan 必须符合 `schemas/runtime_plan.schema.json`。

Job 只含内容、语义 motion、seed、目标时间线时长与输出路径。底层模型参数只存在于 `runtime_plan.execution`。Worker 启动前调用统一契约校验，并完整打印 Provider、Profile、Runtime、GPU、dtype、尺寸、帧数、fps、steps、attention、TeaCache、offload、生成时长和目标时长。

未知远端硬件会得到 `hardware_basis: unknown_conservative` 的保守计划；任务包内的 `runtime_support/runtime_planner.py` 可供 Runtime launcher 在模型加载前按实际硬件重建 RuntimePlan。重规划不改变内容请求键，执行结果必须记录最终 `runtime_plan_digest`。Worker 只执行最终 RuntimePlan。

## Provider 与 Runtime 注意事项

- `skyreels_v2`：支持文字动作约束；Provider Planner 可按显存与 BF16 能力决定 dtype、offload、TeaCache、帧数与 steps。已验证的 Kaggle 脚本仍位于 `kaggle/skyreels_v2/`，但 Kaggle 不是 Provider 名的一部分。
- `svd_xt`：不按文字提示词控制动作；`motion_prompt` 保留创作意图，实际运动由 Planner 生成的 `motion_bucket_id` 与 `noise_aug_strength` 控制。Temporal VAE 不支持 slicing，使用小块解码控制显存。
- `wan22`：TI2V-5B 对显存要求较高；资源未知或受限时 Planner 只给保守 smoke 计划。`convert_model_dtype` 不等于 INT8。FSDP/Ulysses 仅能由支持它们的 RuntimePlan 开启。
- `cogvideox`：受限显存可规划 INT8 weight-only 与 sequential offload；资源充足时可使用 BF16/无量化计划。
- `cloud_i2v`：通过 `cloud_api` Runtime 接入；Job Schema 不因服务商变化。

Kaggle、Colab、RunPod、Local 只是 Runtime。启动时必须核对实际 GPU，不能只相信平台元数据；双 GPU 不能被当作合并显存。不得动态使用 `main/latest` 权重，正式离线运行不得临时访问 PyPI 或下载模型。

## 结果与回退

外部 Runtime 输出 MP4 和 `results.json` 后导入：

```powershell
python scripts/pipeline.py video-import D:/videos/example/project.json `
  --stage demo `
  --results D:/downloads/results.zip `
  --ffmpeg D:/tools/ffmpeg.exe
```

导入器核对 Job cache key、RuntimePlan、输出哈希、分辨率、生成时长与完整解码。成功后只增加 `generated_video` 记录，不覆盖 `type/asset/motion` fallback。失败记录到导入报告，并按“已批准本地视频 → 已批准图片运镜/Remotion”降级。

统一错误至少覆盖 `E_I2V_TIMEOUT`、`E_PROVIDER_FAILURE`、`E_RUNTIME_FAILURE`、`E_GPU_UNSUPPORTED`、`E_GPU_OOM`、`E_SIGKILL`、`E_GENERATION` 和 `E_EXPORT`。任何单镜头失败都不得阻塞最终 narrated-video。

## 验证

运行 `scripts/test_generated_video.py` 验证 Profile 去硬件化、别名迁移、硬件自适应 RuntimePlan、Job 禁止底层参数、任务包、Worker 契约、Hero Shot Budget 和 Remotion fallback。远端 Worker 还需各自在目标 Runtime 做 smoke；本地单元测试不证明模型、显存或平台额度可用。
