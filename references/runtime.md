# 软件与资源路径

在新项目首次选择环境、诊断资源查找失败、切换软件/缓存目录或跨 Agent 会话复用环境时读取。

先按照 [项目配置及命令](project.md) 的“入口与交付”初始化项目及命令变量。

## 选择并保存运行环境

`init` 后立即运行 `paths/configure/preflight`，不需要也不得先填写文案和镜头。`paths` 只展示项目、全局运行环境和当前进程中的候选，不选择、不写配置，也不是全盘资源搜索工具。agent 应结合用户给定安装目录及已有项目进一步查找，集中展示候选后请用户选择。

```powershell
python $pipeline paths $project
# 下列均为示例占位路径，必须替换为用户实际选中的路径。
python $pipeline configure $project --python 'D:/tools/MeloTTS/.venv/Scripts/python.exe' --ffmpeg 'D:/tools/ffmpeg.exe' --nltk-data 'D:/resources/nltk-data' --hf-home 'D:/resources/huggingface-cache' --transformers-cache 'D:/resources/huggingface-cache/transformers' --offline true
python $pipeline doctor $project
python $pipeline preflight $project
python $pipeline remember-runtime $project
```

macOS/Linux 使用相同的命令，将解释器和工具路径换成 POSIX 路径，例如 `/opt/homebrew/bin/ffmpeg` 和 `/Users/me/melo/.venv/bin/python`。

`configure` 记录选择，不代替用户做选择；只验证文件/目录存在，不导入模型或下载资源。`doctor` 是轻量诊断；`preflight` 是制作前硬门禁，成功后写入项目 `.narrated-video/preflight.json`。用户明确同意时再运行 `remember-runtime`，将通过当前 preflight 的路径保存到当前用户的全局配置文件 `${CODEX_HOME}/narrated-video/runtime.json`（未设置时为 `~/.codex/narrated-video/runtime.json`）。这个文件供不同 Agent 会话复用，不修改系统 PATH，也不需要管理员权限。

CogVideoX 等生成式视频 provider 不属于本地运行环境门禁。可在项目中记录 `video_generation.provider: cogvideox_colab`、`execution: remote_manual` 和 `local_gpu_required: false`；`preflight` 不检查 CUDA、torch、diffusers、模型权重或 Colab 连通性。生成式视频任务包和结果导回分别使用 [生成式视频](generated-video.md) 中的工具。

`preflight` 检查 FFmpeg 的版本、`perspective`/`xfade`/`subtitles`/响度与混音滤镜以及 `libx264`/AAC 编码器。MeloTTS 模式还检查模块、NLTK，并强制离线实际加载所选语言模型与 speaker，确保缓存完整；CosyVoice 模式使用临时短句验证命令、模型目录和 PCM WAV 输出，配置了 `batch_command` 时优先按一条 job 的 manifest 验证批量入口；`files` 模式跳过 TTS 检查。临时样本会删除，不生成项目媒体。

后续 CLI 会自动按“命令行临时参数 > 项目 `runtime` > 全局运行环境 > 当前进程环境 > PATH/当前 Python”解析路径，并在导入 NLTK、Transformers、MeloTTS 或 CosyVoice 原生推理脚本**之前**注入项目资源路径。即使最初用另一套 Python 启动，也会转到配置的解释器执行。直接在其他程序中 `import Project` 不会自动重启解释器，需调用方使用已配置环境，推荐使用 CLI。

```json
"runtime": {
  "python": "D:/tools/MeloTTS/.venv/Scripts/python.exe",
  "ffmpeg": "D:/tools/ffmpeg.exe",
  "nltk_data": "D:/resources/nltk-data",
  "hf_home": "D:/resources/huggingface-cache",
  "hf_hub_cache": "D:/resources/huggingface-cache/hub",
  "transformers_cache": "D:/resources/huggingface-cache/transformers",
  "offline": true
}
```

- 所有相对路径以项目 JSON 所在目录为基准。软件路径指向可执行文件，资源路径指向现有目录；只有用到的字段需要填写。改路径可再次运行 configure；清除某项可编辑 JSON 删除相应键。
- `nltk_data` 对应 `NLTK_DATA`，应包含 `corpora/` 和 `taggers/`。
- `hf_home` 对应 `HF_HOME`；选择该根目录后，未单独配置的 hub 与 transformers 缓存统一指向它的 `hub/` 子目录，覆盖调用进程遗留的旧目录。资源分开存放时明确配置两个缓存字段。
- `hf_hub_cache` 对应 `HF_HUB_CACHE`；`transformers_cache` 对应 `TRANSFORMERS_CACHE`。显式项目值优先于进程环境变量，未配置的字段保留原环境行为。
- `HF_HOME` 通常足够；未单独配置两个子目录时，脚本将 Hub 与 Transformers 缓存统一指向其 `hub/` 子目录。只有已有缓存分开存放时才分别配置 `hf_hub_cache` 和 `transformers_cache`。
- FFmpeg 优先级：本次 `--ffmpeg` > 项目 `runtime.ffmpeg` > 全局运行环境 > `NARRATED_VIDEO_FFMPEG`/`FFMPEG` > PATH。显式路径无效就报错，不静默回退；临时覆盖不会更新已保存路径，正式换环境应通过 configure。
- 可选的跨会话候选变量为 `NARRATED_VIDEO_FFMPEG` 和 `NARRATED_VIDEO_MELOTTS_PYTHON`；`FFMPEG`、`NLTK_DATA`、`HF_HOME`、`HF_HUB_CACHE`、`TRANSFORMERS_CACHE` 继续兼容。环境变量只是候选，`remember-runtime` 保存的全局配置和项目配置优先。
- 新建项目 `offline: true`，设置 Hugging Face 和 Transformers 离线模式。`false` 仅表示允许相关库联网，不能视为安装或下载授权。旧项目没有 runtime 时保持原启动方式，agent 在下一次使用前补做用户路径选择。
- `doctor` 使用所选 Python 做轻量检查，不导入整个 TTS 模型；`preflight` 才执行严格的离线模型加载或临时短句测试。任何 `check`、审批记录、配音、渲染和验证都要求当前 preflight 有效。
- 字体继续使用 `subtitles.font` 的已安装字体名称；首版不自动安装字体、不支持单独字体文件路径。
- runtime、配音引擎、语言、speaker、模型命令或可执行文件变化会使 preflight 失效；必须重新检查后才能继续。runtime 变化也会使 Demo 批准和缓存失效，避免换解释器或资源后误用旧配音。模型在原位置更新时仍需递增 `voice.revision`。`remember-runtime` 只写用户自己的全局配置文件，不修改系统级环境变量；删除或改名该文件即可清除记忆路径。
- macOS/Linux 不依赖 shell 启动文件发现全局环境，避免从图形界面启动的 Agent 继承不到 `.zshrc`/`.bashrc`；Windows、macOS 和 Linux 均使用同一份 JSON 配置格式。
- 2026-09 版本把 script fingerprint 限定为有序的句子 ID 和文字，不再把逐句 `audio` 路径误算成文案变化。升级已有项目后，若旧 state 使用旧算法，首次继续时可能要求用原有实际回复重新记录一次 script 批准；之后仅补充非 Demo 音频不会撤销文案批准。

