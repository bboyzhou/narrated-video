# 生成式视频素材

生成式视频是可选的外部素材阶段，不属于最终渲染器。项目仍只声明 `type: image/video`；需要动态生成的分镜使用 `asset_strategy: generated_video`。成功生成的 MP4 在运行时解析成普通 `type: video`，失败、缓存失配或文件损坏时继续使用项目镜头原有的图片/视频素材。

当前 provider：

- `wan22_kaggle`：Wan2.2 TI2V-5B，Kaggle 官方原生 Worker；稳定基线使用单个 `torchrun` 作业的 FSDP + Ulysses 多 GPU模式，单卡仅作为实验 profile；
- `cogvideox_colab`：旧 CogVideoX/Colab 工作流的兼容适配器。

要比较其他文生视频/图生视频玩法，使用 [视频 provider 测试矩阵](video-provider-matrix.md)。矩阵中的额度、价格和免费分辨率是资源快照，不是 pipeline 的运行时依赖；线上平台测试必须由用户选择并确认额度消耗。

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
        "checkpoint_path": "/kaggle/input/wan22-ti2v5b/Wan2.2-TI2V-5B",
        "source_path": "/kaggle/input/wan22-source",
        "profile": "native_dual_t4",
        "size": "1280*704",
        "max_frame_num": 49,
        "world_size": 2,
        "ulysses_size": 2,
        "t5_fsdp": true,
        "dit_fsdp": true,
        "t5_cpu": false,
        "convert_model_dtype": false,
        "offload_model": false,
        "offline": true
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

## Kaggle Worker：官方原生稳定基线

`kaggle/run_wan_job.py` 是 native Worker 的作业入口：读取显式任务配置、执行环境检查并启动一个 `torchrun` 作业。每个 rank 参与同一份 `WanTI2V` 模型并行推理，不是多个独立生成 Worker。Worker 在同一次模型加载中顺序处理 job。

输入路径优先级必须是：任务 JSON 显式路径 → 环境变量 → 失败。不要用 `INPUT.rglob()` 猜测模型或源码路径；这样可避免同时挂载多个 Dataset 时误选。

稳定基线要求：

1. 解压后的 `video_jobs.json` 和 `input/`；
2. Wan2.2 官方源码目录；
3. Wan2.2-TI2V-5B 权重目录。

当前固定组合：

- 官方源码仓库 `Wan-Video/Wan2.2`，commit `42bf4cfaa384bc21833865abc2f9e6c0e67233dc`，随 Kernel 代码目录提交到 `kaggle/wan22_source/`；
- 权重 Dataset `ihsannika/wan2-2-ti2v-5b`，目录名 `Wan2.2-TI2V-5B`，通过 `kernel-metadata.json` 的 `dataset_sources` 挂载；
- 权重目录结构必须包含 `Wan2.2_VAE.pth`、三段 `diffusion_pytorch_model-*.safetensors`、index JSON 和 `models_t5_umt5-xxl-enc-bf16.pth`。Worker 会在启动时拒绝缺失目录或文件。

这样源码版本与权重来源可审计，权重不被复制进 Kernel 包，也不会在运行时自动联网下载。

复制 `kaggle/kernel-metadata.example.json` 为 `kernel-metadata.json`，填写自己的 Kaggle 用户名和输入源；首轮使用与 `world_size` 一致的 GPU 数量，并确认 Kaggle Internet 关闭时仍能运行。

不要为每个镜头启动一次 `generate.py`，也不要启动多个独立完整模型 Worker。`torchrun`、`world_size` 和 Ulysses 只表示一个 native 多 GPU 作业的 rank 数；每个 rank 只构造一次 `WanTI2V`，顺序处理任务。单卡 profile 必须显式关闭 FSDP/Ulysses，并不能使用 `t5_cpu + t5_fsdp` 的冲突组合。

启动模型前写入 `/kaggle/working/preflight.json`，至少记录 Python/PyTorch/CUDA、GPU 型号与空闲 VRAM、系统 RAM、磁盘空间、模型目录、输入图片和 FFmpeg。资源不足时主动停止：可用 RAM 小于 8GB、磁盘小于 15GB 时禁止正式运行；RAM 超过 93% 或 VRAM 超过 92% 时终止当前 job 并交由 Supervisor 处理。

默认 profile：`native_smoke` 使用约 832×480、17 帧、8–10 steps；`native_dual_t4` 使用 480P area、49 帧、18–24 steps、`world_size=2`、`ulysses_size=2`；`native_hd` 仅在 standard 连续稳定后启用。官方 native 路径没有 Q8/INT8 参数；`convert_model_dtype` 只表示 dtype 转换，不得写成量化。

输出先写 `<output>.mp4.partial`，生成和 FFmpeg/ffprobe 验证通过后用原子替换提交。验证至少包含视频流存在、duration > 0、可识别 codec 和 frame count > 0。

Worker 不访问 PyPI、不动态安装依赖、不下载模型。依赖放在固定 Kaggle Dataset 的 wheels 和 `requirements.lock` 中，使用 `pip --no-index --find-links=...` 或已验证的基础环境。模型、源码和 runtime 版本都写入 preflight 与任务结果。

每个 job 独立写 `status.json`、`metrics.json`、`worker.log` 和输出文件；状态至少为 `pending/running/done/failed/retrying`。重启时跳过已验证的 `done`，只继续未完成 job。Job 完成后清理临时 tensor、`gc.collect()` 和 `torch.cuda.empty_cache()`；清理用于降低缓存残留，不是 OOM 的根本修复。

错误统一为 `E_CONFIG`、`E_INPUT`、`E_MODEL`、`E_DEPENDENCY`、`E_RAM_PRESSURE`、`E_GPU_OOM`、`E_SIGKILL`、`E_GENERATION`、`E_EXPORT`。若 return code 为 `-9`，记录 `E_SIGKILL` 和疑似系统 OOM，不只暴露 `CalledProcessError`。

发生 `E_GPU_OOM`、`E_RAM_PRESSURE` 或 `E_SIGKILL` 时，native 作业必须退出并记录原因；外层 Supervisor（尚未由当前入口实现）再降低 profile 并创建干净作业，每个 job 最多自动重试一次。禁止在已发生 CUDA OOM 的进程内继续重试。

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

## Diffusers 与后续边界

当前不把 Diffusers 作为本次修复目标。官方仓库的 native `WanTI2V` 与独立的 `Wan2.2-TI2V-5B-Diffusers` 模型是两套加载契约；切换 Diffusers 时必须另建 Worker、锁定独立模型版本并重新验证显存。Kaggle CLI 自动提交也必须在 native 手动流程通过后再增加。

## 生产验收

- native smoke 连续 10 次无 SIGKILL、CUDA OOM 或 Kernel restart；
- 同一 Worker 连续完成 3 个镜头；
- 模拟中断后只恢复未完成 job；
- Internet=OFF 时完整运行；
- HD OOM 后 Worker 退出、Supervisor 降级到 standard 并重试；
- Wan 镜头失败两次后，项目仍使用图片运镜并输出完整 MP4。
