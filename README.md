# narrated-video

可配置的图片运镜解说视频 Codex skill：从文案、图片和配音生成带字幕、转场与配乐的 MP4。

支持 `image/video` 镜头及图片/视频图层的位置、缩放、旋转、透明度关键帧；可查询并引用离线素材库，详见 [动态素材合成](references/composition.md)。工作流会依次确认口播稿、制作纲要与完整分镜、Demo，再渲染全片；配音时间轴按实际 WAV 时长对齐，缓存支持局部重跑。网络素材由 agent 核对来源与许可后落地，渲染器不联网。

生成式视频是可选的外部素材阶段：用 [生成式视频](references/generated-video.md) 和 `video-prepare` 准备任务包，由 Wan2.2 TI2V-5B/Kaggle Worker 批量生成后用 `video-import` 导回。模型只加载一次，结果按模型版本、源图、提示词、seed 和推理参数缓存；失败或缓存失配时回退到原图片运镜。旧 CogVideoX/Colab 任务仍可读取。

## 使用

将本目录作为 skill 使用，入口说明见 [SKILL.md](SKILL.md)。脚本命令和项目 JSON 见 [references/project.md](references/project.md)，分镜规范见 [references/storyboard.md](references/storyboard.md)；首次使用先阅读 [references/runtime.md](references/runtime.md) 选择 Python、FFmpeg、NLTK 和模型缓存路径。

```powershell
python scripts/pipeline.py init D:/videos/example/project.json --source D:/documents/source.md
python scripts/pipeline.py paths D:/videos/example/project.json
python scripts/pipeline.py configure D:/videos/example/project.json --python D:/tools/python.exe --ffmpeg D:/tools/ffmpeg.exe --offline true
python scripts/pipeline.py preflight D:/videos/example/project.json
python scripts/pipeline.py remember-runtime D:/videos/example/project.json
python scripts/pipeline.py check D:/videos/example/project.json --stage script
python scripts/pipeline.py record D:/videos/example/project.json --stage script --quote "用户实际批准回复"
python scripts/pipeline.py check D:/videos/example/project.json
python scripts/pipeline.py record D:/videos/example/project.json --stage storyboard --quote "用户实际批准回复"
python scripts/pipeline.py video-prepare D:/videos/example/project.json --stage demo --ffmpeg PATH
# 在 Kaggle 双 GPU Worker 中运行任务包并下载输出后：
python scripts/pipeline.py video-import D:/videos/example/project.json --stage demo --results OUTPUT_ZIP --ffmpeg PATH
python scripts/pipeline.py video-status D:/videos/example/project.json --stage demo --ffmpeg PATH
```

`preflight` 必须在文案和制作方案前通过；`remember-runtime` 会把通过门禁的运行环境保存到用户级配置，供后续项目和 Agent 会话复用。两者都不会自动安装依赖或下载模型。

不自动安装依赖或下载模型。测试使用隔离临时工程：

```powershell
python scripts/test_runtime.py
python scripts/test_storyboard.py
python scripts/test_pipeline.py --ffmpeg PATH --image IMAGE --alternate-image IMAGE2 --output TEMP_DIR
python scripts/test_motion.py --ffmpeg PATH --image IMAGE
python -m unittest discover -s scripts -p "test_*.py"
```

`evals/evals.json` 保存用于审核 skill 行为的场景，不是视频素材或生产配置。
