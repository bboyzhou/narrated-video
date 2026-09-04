# 软件与资源路径

在新项目首次选择环境、诊断资源查找失败或切换软件/缓存目录时读取。

先按照 [项目配置及命令](project.md) 的“入口与交付”初始化项目及命令变量。

## 选择并保存运行环境

`init` 后即可运行 `paths/configure/doctor`，不需要先填写文案和镜头。`paths` 只展示项目和当前进程中的候选，不选择、不写配置，也不是全盘资源搜索工具。agent 应结合用户给定安装目录及已有项目进一步查找，集中展示候选后请用户选择。

```powershell
python $pipeline paths $project
# 下列均为示例占位路径，必须替换为用户实际选中的路径。
python $pipeline configure $project --python 'D:/tools/MeloTTS/.venv/Scripts/python.exe' --ffmpeg 'D:/tools/ffmpeg.exe' --nltk-data 'D:/resources/nltk-data' --hf-home 'D:/resources/huggingface-cache' --transformers-cache 'D:/resources/huggingface-cache/transformers' --offline true
python $pipeline doctor $project
```

`configure` 记录选择，不代替用户做选择；只验证文件/目录存在，不导入模型或下载资源。后续 CLI 会自动使用所选 Python，并在导入 NLTK、Transformers、MeloTTS 或 CosyVoice 原生推理脚本**之前**注入项目资源路径。即使最初用另一套 Python 启动，也会转到配置的解释器执行。直接在其他程序中 `import Project` 不会自动重启解释器，需调用方使用已配置环境，推荐使用 CLI。

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
- FFmpeg 优先级：本次 `--ffmpeg` > 项目 `runtime.ffmpeg` > `FFMPEG` > PATH。显式路径无效就报错，不静默回退；临时覆盖不会更新已保存路径，正式换环境应通过 configure。
- 新建项目 `offline: true`，设置 Hugging Face 和 Transformers 离线模式。`false` 仅表示允许相关库联网，不能视为安装或下载授权。旧项目没有 runtime 时保持原启动方式，agent 在下一次使用前补做用户路径选择。
- `doctor` 使用所选 Python，检查 FFmpeg 可运行、MeloTTS 模块可定位、NLTK zip 可找到且词典可读取。使用 `files` 或 `cosyvoice` 配音时跳过 MeloTTS/NLTK 检查；CosyVoice 的 `command` 和模型权重由用户选择，首次使用必须运行一条获授权的短句试听来验证原生环境和输出 WAV。模型目录存在不等于模型齐全，doctor 不导入整个模型、不生成音频。
- 字体继续使用 `subtitles.font` 的已安装字体名称；首版不自动安装字体、不支持单独字体文件路径。
- runtime 变化会使 Demo 批准和缓存失效，避免换解释器或资源后误用旧配音。模型在原位置更新时仍需递增 `voice.revision`。不会修改用户/系统级环境变量。
- 2026-09 版本把 script fingerprint 限定为有序的句子 ID 和文字，不再把逐句 `audio` 路径误算成文案变化。升级已有项目后，若旧 state 使用旧算法，首次继续时可能要求用原有实际回复重新记录一次 script 批准；之后仅补充非 Demo 音频不会撤销文案批准。

