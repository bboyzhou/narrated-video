# 生成式视频素材

生成式视频是可选的素材生成阶段，不是本地渲染器的一部分。当前 provider 是 `cogvideox_colab`，采用图生视频（I2V）：已批准的分镜图片和独立的 `motion_prompt` 进入外部 Colab，得到短 MP4 后再作为普通 `type: video` 镜头导入。未来可增加其他 provider，而不改变 `pipeline.py` 的时间轴职责。

## 何时使用

只有当静态图片运镜不足以表达动作，且动作可以用短、低幅度的镜头描述时才建议使用。历史人物优先写“衣摆、旗帜、尘土、雾气、光影、缓慢镜头移动”等可控运动，避免要求模型生成大幅行走、复杂手势或无法核验的历史细节。人物骨骼动作、自动抠图和遮挡补全仍不由本 skill 保证。

每个生成镜头必须先完成静态分镜和 storyboard 批准，再声明：

```json
{
  "asset_strategy": "generated_video",
  "source_image": "images/S003.png",
  "motion_prompt": "The general remains standing while his robe and banners move gently in the wind. Slow cinematic push-in.",
  "motion_constraints": ["preserve character identity", "preserve costume", "preserve composition"],
  "generation": {"provider": "cogvideox_colab", "mode": "i2v", "duration_target": 6, "seed": 42}
}
```

图片 `prompt` 负责主体、服装、地点、时代和构图；`motion_prompt` 负责运动与镜头；`motion_constraints` 负责保持项。不要将两者拼成一个模糊提示词，也不要使用新的 `type: ai_video`。

## 本地准备

本地不安装 CUDA、torch CUDA、diffusers、transformers、CogVideoX 或模型权重。保留现有 Python、FFmpeg、MeloTTS/CosyVoice 和 pipeline。`preflight` 不检查 CogVideoX；项目可选记录：

```json
"video_generation": {
  "provider": "cogvideox_colab",
  "execution": "remote_manual",
  "local_gpu_required": false
}
```

在已批准 storyboard 和静态源图准备好后，先只为 Demo 镜头生成任务包：

```powershell
python scripts/prepare_video_jobs.py D:/videos/example/storyboard.json `
  --project D:/videos/example/project.json --stage demo `
  --output D:/videos/example/video_jobs.json
```

脚本只选择 `asset_strategy: generated_video` 的镜头，复制源图并生成 `video_jobs.zip`。它不访问网络、不调用 Colab、不下载模型。任务包包含 shot ID、源图、motion prompt、约束、seed、目标时长和回退素材。不要在 storyboard 未批准或 Demo 未确定前打包全片。

## Colab 步骤

打开随附 [CogVideoX I2V Notebook](../notebooks/cogvideox_i2v_colab.ipynb)，上传 `video_jobs.zip` 并运行全部单元格。Notebook 在远程环境安装和加载模型，逐个读取 `image + motion_prompt`，输出 `output/<shot_id>.mp4`，最后生成 `cogvideo-output.zip`。免费 Colab 的 GPU、运行时长、显存和模型下载可用性不作保证；不要把它当作稳定后台服务，也不要让 `pipeline.py` 通过 HTTP 调用 Colab。Notebook 中的模型仓库、版本和推理参数应在实际运行前检查许可、显存和 API 兼容性；生成结果必须人工查看。

## 结果导回

将 `cogvideo-output.zip` 和 `video_jobs.json` 放回项目附近，然后运行：

```powershell
python scripts/import_generated_videos.py D:/videos/example/project.json `
  D:/videos/example/cogvideo-output.zip `
  --jobs D:/videos/example/video_jobs.json
```

导入器检查 shot ID、MP4 视频流、分辨率和可读时长，将文件复制到 `assets/generated-video/`，把对应项目镜头更新为 `type: video`、`motion: still`，并写入 `.narrated-video/generated-video-import.json`。它不会把音频带入时间轴；原有配音和配乐仍由 pipeline 混音。导入后重新运行 `check`，为 Demo 重新生成并确认样片；未导入的镜头保持原来的图片配置。

## 失败和降级

生成失败、Colab 不可用、结果不合格或许可不清时，不阻塞 narrated-video 项目。按以下顺序处理：

1. 使用已批准并通过检查的生成视频；
2. 使用已批准的本地或现有视频素材；
3. 使用已批准的分镜图片和原有关键帧运镜。

降级时说明哪些镜头未使用生成视频以及原因；不要把未审阅的生成结果静默放进全片。生成视频的运动若改变叙事、人物身份、历史服装或构图，须更新 storyboard 并重新取得对应批准。

## 审批顺序

Demo 中包含 `generated_video` 时，顺序为：口播批准 → 完整 storyboard 批准 → 准备 Demo 图片 → 生成 Demo 视频任务包 → 用户在外部 Colab 执行并导回 → 渲染 Demo → 用户确认 Demo → 准备并导回其余镜头 → 渲染全片。生成式视频 provider 的失败不会绕过脚本、分镜或 Demo 审批。

生成式视频结果必须记录 provider、模型/版本（如果可得）、seed、源图哈希、motion prompt、生成时间、输出哈希和许可/使用条件。不要声称外部模型结果具有商业许可，除非已核对实际条款。
