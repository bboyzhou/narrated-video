# narrated-video

可配置的图片运镜解说视频 Codex skill：从文案、图片和配音生成带字幕、转场与配乐的 MP4。

首版只支持 `image` 镜头。工作流会先确认口播稿，再制作并确认 Demo，最后渲染全片；配音时间轴按实际 WAV 时长对齐，缓存支持局部重跑。

## 使用

将本目录作为 skill 使用，入口说明见 [SKILL.md](SKILL.md)。脚本命令和项目 JSON 见 [references/project.md](references/project.md)，首次使用先阅读 [references/runtime.md](references/runtime.md) 选择 Python、FFmpeg、NLTK 和模型缓存路径。

```powershell
python scripts/pipeline.py init D:/videos/example/project.json --source D:/documents/source.md
python scripts/pipeline.py paths D:/videos/example/project.json
python scripts/pipeline.py configure D:/videos/example/project.json --python D:/tools/python.exe --ffmpeg D:/tools/ffmpeg.exe --offline true
python scripts/pipeline.py doctor D:/videos/example/project.json
```

不自动安装依赖或下载模型。测试使用隔离临时工程：

```powershell
python scripts/test_runtime.py
python scripts/test_pipeline.py --ffmpeg PATH --image IMAGE --alternate-image IMAGE2 --output TEMP_DIR
```

`evals/evals.json` 保存用于审核 skill 行为的场景，不是视频素材或生产配置。
