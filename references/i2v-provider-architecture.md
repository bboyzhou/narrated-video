# 通用 I2V Provider 架构

I2V 是 Remotion + FFmpeg 生产链路上的可选视觉增强层。四个边界必须保持独立：

```text
Profile（速度/质量/成本意图）
  + Provider（模型或服务）
  + Runtime（运行位置）
  + Hardware（实际资源）
  -> Provider Planner
  -> RuntimePlan
  -> Worker
```

## 稳定协议

- Profile：`smoke/fast/balanced/quality/max_quality`。不得含 GPU、dtype、帧数、steps 或加速开关。
- Provider：`skyreels_v2/wan22/cogvideox/svd_xt/cloud_i2v`。不得含 Kaggle、Colab、RunPod 等平台名。
- Runtime：`auto/local/kaggle/colab/runpod/remote_worker/cloud_api`。Runtime 不决定模型。
- Hardware：运行时探测 GPU 数量、型号、VRAM、compute capability、FP16/BF16、RAM、CUDA 与 PyTorch。探测不到时使用保守计划，并要求执行端在加载模型前重新探测和规划。
- RuntimePlan：唯一允许出现 `dtype/resolution/frame_num/fps/steps/attention/offload/world_size` 的对象。它由系统生成，必须记录 `plan_digest`、硬件依据和预估/软/硬 timeout。
- Worker：只接收内容型 Request 与已生成 RuntimePlan；不选择 Profile、Provider 或 Runtime，不猜硬件。

## 项目配置

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
        "model_revision": "固定提交"
      }
    }
  }
}
```

`providers` 只保存模型、源码、服务端点和固定版本等 Provider 元数据；不能保存 Planner 所有的执行参数。Runtime 的设备限制只放在 `runtime.overrides`，默认只支持 `device` 和 `max_vram_gib`。

## Job v3

Job 只描述内容与意图：图片、正负提示词、约束、语义 motion、目标时间线时长、seed 和输出路径。不得出现 Provider/Profile/Runtime 或任何底层模型参数。`target_duration_sec` 是最终时间线时长，不等于 I2V 生成时长；短生成片段由 Remotion 用慢放、freeze、push/pan、crossfade 等方式延展。

一个任务包只包含一个 Provider、Profile、RuntimePlan；不同 Provider 或 Runtime 分包。缓存键覆盖 Provider 配置、通用 Profile 与 Job 内容；Runtime launcher 可按实际 Hardware 重建 RuntimePlan 而不改变内容请求键，最终结果另存 `runtime_plan_digest` 以便审计。导入时核对请求键、RuntimePlan、完整解码、尺寸、生成时长和哈希；导入器只登记 `generated_video`，不覆盖原镜头 fallback。

## Router 与失败隔离

普通镜头默认使用 `remotion_motion`。只有已批准分镜显式标为 `motion_mode: i2v` 或 `asset_strategy: generated_video` 的 Hero Shot 才进入 I2V Router，并受项目 `i2v_budget` 限制。

I2V timeout、Provider failure、Runtime failure、OOM 或损坏输出都只影响当前镜头。记录标准错误码后回退到 `remotion_motion` 或已批准本地素材；最终视频继续。`VideoResult` 至少记录 `requested_provider`、`actual_provider`、`status` 和 `reason`。

## 旧配置迁移

读取时允许以下别名，写出时必须使用拆分后的名称：

| 旧 Provider | 新 Provider | Runtime |
|---|---|---|
| `skyreels_v2_kaggle` | `skyreels_v2` | `kaggle` |
| `svd_xt_kaggle` | `svd_xt` | `kaggle` |
| `wan22_kaggle` | `wan22` | `kaggle` |
| `cogvideox_kaggle` | `cogvideox` | `kaggle` |
| `cogvideox_colab` | `cogvideox` | `colab` |

旧硬件 Profile 不能原样迁移为新 Profile；按原意映射到 `smoke/fast/balanced/quality`，然后让 Planner 重新生成 RuntimePlan。
