# 文生视频 / 图生视频测试矩阵

这份矩阵把外部视频生成服务当作“素材提供者”测试，不改变 narrated-video 的时间轴、字幕、配音、音乐或 FFmpeg 渲染器。表格中的额度、价格和免费分辨率来自用户提供的资源快照，可能随平台策略变化；测试记录应保存测试日期和实际账户结果，不能把它们硬编码成运行时保证。

## 能力矩阵

| Provider | 类型 | T2V | I2V | 主要限制 | 首测用途 | 优先级 |
|---|---|---:|---:|---|---|---:|
| PixVerse | 在线商业平台 | ✅ | ✅ | 免费分辨率和积分有效期受平台策略限制 | 最省事验证 I2V、特效 | 5 |
| Pika 2.5 | 在线商业平台 | ✅ | ✅ | 免费分辨率较低、月度额度有限 | 社交短视频、快速试镜头 | 5 |
| Runway | 在线商业平台 | ✅ | ✅ | 免费额度一次性，高级模型可能不可用 | 顶级商业工作流对照 | 3 |
| Leonardo.Ai | 在线商业平台 | ✅ | ⚠️ | 免费模型有限，上传图片做视频可能需要付费 | AI 图片后续动效 | 2 |
| Comfy Cloud | 云端 ComfyUI | ✅ | ✅ | 视频模型消耗积分较快 | Wan/Kling 等工作流对照 | 5 |
| Hugging Face ZeroGPU | 免费共享 GPU | ✅* | ✅* | 排队和每日 GPU 分钟数有限，取决于 Space | 开源模型快速 Demo | 3 |
| Wan2.2 TI2V-5B + Kaggle | 开源 + Kaggle GPU | ✅† | ✅ | 单 T4 显存、RAM、配额和 offload 稳定性需实测；双卡属于后续实验 | 零订阅成本、批量 I2V | 5 |
| Wan2.2 TI2V-5B 本地 | 开源本地 | ✅ | ✅ | 需要自行承担 GPU/电费和部署成本 | 4090 等本地生产线 | 5 |
| CogVideoX-5B-I2V + Colab | 开源 + Colab | — | ✅ | 免费 Colab 的 GPU/RAM 配额波动 | 学习和实验 | 3 |
| LTX-Video / LTX-2 | 开源 | ✅ | ✅ | 部署复杂度和硬件要求较高 | ComfyUI、关键帧和扩展 | 4 |
| Open-Sora 2.0 | 开源研究项目 | ✅ | 研究级 | 11B 部署门槛高 | 模型研究 | 2 |

注：`✅*` 表示能力取决于具体 Space 或工作流；`✅†` 表示 Wan2.2 TI2V-5B 模型能力支持 T2V，但当前 `wan22_kaggle` Worker 的任务契约要求输入图，首轮 Kaggle 稳定性测试是 I2V。T2V 需要另行增加无图输入路径后再纳入自动测试。

## 统一测试用例

所有 provider 尽量使用同一组短素材和提示词，避免把提示词差异误判为模型差异：

1. `t2v_basic`：无输入图，5 秒，单主体、单动作、固定 seed（仅支持 T2V 的 provider 执行）。
2. `i2v_basic`：同一张 16:9 首帧图，5 秒，慢速运动；检查主体、服装、构图保持。
3. `i2v_motion`：同一首帧图，加入镜头运动和环境运动；检查运动是否自然、是否出现闪烁或身份漂移。
4. `short_clip_decode`：下载 MP4 后检查视频流、分辨率、帧率、时长、首帧可解码。
5. `fallback`：人为标记 provider 失败或结果损坏，确认项目继续使用批准的图片运镜 fallback。
6. `cache_repeat`：完全相同的 provider、模型版本、源图哈希、提示词、seed 和采样参数不得重复提交。

## Kaggle Wan2.2 首轮验收

首轮只提交一个 `i2v_basic` Demo 镜头，目标是证明单卡环境和 Worker 生命周期稳定，不比较画质排名。必须同时满足：

- Kernel metadata 明确 `enable_gpu: true`、`machine_shape: NvidiaTeslaT4`；
- Worker 只启动一个模型进程，使用 `cuda:0`，不依赖 `torchrun`、`world_size` 或 NCCL；
- preflight 记录 GPU、VRAM、RAM、磁盘、模型路径和 runtime/依赖版本；
- `results.json` 中该镜头为 `completed`，有 `cache_key`、输出哈希和帧数；
- 导入器用 FFmpeg/ffprobe 验证 MP4 视频流、时长和分辨率；
- Demo 抽帧人工检查首帧、末帧、运动连续性和画面是否出现明显闪烁；
- 失败时保留 `results.json` 和失败日志，并验证 fallback 能继续渲染。

只有该用例稳定通过，才继续增加 3-job 批量、resume、OOM 降级或启用 Kaggle CLI 自动提交；在线平台的额度测试则必须由用户明确选择并确认消耗范围。

## 测试记录字段

每次测试至少记录：`provider`、`mode`、`model_revision`、`tested_at`、`account_or_runtime`、`resolution`、`duration`、`seed`、`source_image_sha256`（I2V）、`prompt`、`status`、`output_sha256`、`observed_limitations`、`fallback_verified`。不要把“免费额度”当作测试通过条件，只记录实际返回结果。
