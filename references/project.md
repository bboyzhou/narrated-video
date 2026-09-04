# 项目配置及命令

脚本位置：本 skill 的 `scripts/pipeline.py`。使用现有 Python 3.10+，仅标准库；渲染需要带 libx264、libass、xfade、loudnorm 的 FFmpeg。配音生成需要已有 MeloTTS Python 环境。首次使用先由用户选择软件和资源路径，不自动安装包。

软件和资源路径的首次选择、字段优先级及诊断见 [运行环境](runtime.md)。同一项目路径已选定且有效时直接复用。

## 入口与交付

```powershell
# 将变量换成实际路径；不要把下面的示例值当作本机路径。
$pipeline = 'D:/workspace/narrated-video/scripts/pipeline.py'
$project = 'D:/videos/example/project.json'
$ffmpeg = 'D:/tools/ffmpeg.exe'
python $pipeline init $project --source 'D:/documents/source.md'
```

`init` 只复制原文并建立空配置，不把 Markdown 标题等自动转成口播。也可省略 `--source`，由 agent 将对话文案以 UTF-8 保存为项目 `source.txt`。目录输入必须恰好包含一个 `.txt`/`.md`，多个时明确选择。现有项目不会被覆盖。

用户批准完整改写稿后，将纯口播文字写入 `approved-script.txt`，将自然短句配置到 `narration`。脚本检查去除空白后的内容完全一致，标点仍须一致。不要把说明、标题、批准回复混入该文件。

```powershell
python $pipeline check $project
python $pipeline record $project --stage script --quote '用户实际批准回复'
python $pipeline tts $project --stage demo
python $pipeline render $project --stage demo --ffmpeg $ffmpeg
# agent 抽帧查看、试听，并将 Demo 交给用户；此处等待真实回复。
python $pipeline record $project --stage demo --quote '用户实际批准 Demo 的回复'
python $pipeline render $project --stage full --ffmpeg $ffmpeg
python $pipeline verify $project --stage full --ffmpeg $ffmpeg
```

`record` 是记录器，不判断回复含义，也不代表用户已经批准。必须由 agent 根据实际对话填写。`--skip` 仅在用户明确跳过相应阶段时使用，`--quote` 保留原话与跳过范围。普通 Demo 批准要求当前配置已渲染，并检查样片文件未改变。测试项目中可使用明确标注的测试授权，但不能复制到真实项目。

Demo 未批准时，`tts/render --stage full` 拒绝执行；Demo 模式只处理选中的镜头，不要求其他镜头的图片/音频已存在。项目目录 `.narrated-video/state.json` 保存批准和渲染记录；`.narrated-video/cache/` 保存缓存。不要并发渲染同一项目。

产物在 `deliverables/`：`demo.mp4` 或 `full.mp4`、同名 SRT、时间轴、素材清单、验证报告、3 张抽帧、项目配置副本和批准记录副本。项目副本保留原项目的相对路径；可移交的完整项目应连同原项目目录、素材、源文件和缓存配音一起复制，单独复制 deliverables 不是可移植工程。

## 配置示例

所有输入相对路径以原 `project.json` 所在目录为基准，允许绝对路径。配置版本为 `1`。

```json
{
  "version": 1,
  "title": "示例项目",
  "script": "approved-script.txt",
  "style": {"name": "水墨", "visual": "留白与统一墨色", "tone": "自然沉稳"},
  "output": {"width": 1280, "height": 720, "fps": 30},
  "voice": {"engine": "melotts", "language": "ZH", "speaker": "ZH", "device": "cpu", "speed": 0.95, "revision": "1"},
  "subtitles": {"enabled": true, "font": "Microsoft YaHei", "size": 24, "margin": 28, "max_chars": 24},
  "narration": [
    {"id": "N001", "text": "故事从这里开始。"},
    {"id": "N002", "text": "接下来，我们走近这段历史。"}
  ],
  "shots": [
    {"id": "S001", "type": "image", "asset": "images/001.png", "narration": ["N001"], "motion": "push", "transition": 0.3, "prompt": "已使用的图片提示词", "source": "生成工具及生成记录"},
    {"id": "S002", "type": "image", "asset": "images/002.png", "narration": ["N002"], "motion": "pan-right", "transition": 0.3, "prompt": "已使用的图片提示词", "source": "生成工具及生成记录"}
  ],
  "demo": {"shots": ["S001", "S002"]},
  "music": [
    {"path": "music/track.mp3", "start": 0, "end": 30, "volume": 0.15, "fade_in": 2, "fade_out": 3, "source": "实际来源链接或用户提供记录", "license": "实际许可及署名要求"}
  ]
}
```

示例素材必须换为真实文件；不需要配乐时使用空数组 `music: []`。风格是创作说明，不会自动改变图像或配音；具体行为由图片、voice、shots、subtitles、music 实现。字体需已安装，FFmpeg 可能静默替代缺失字体，必须检查抽帧。

### 配音和时间轴

- `voice.engine` 为 `melotts` 或 `files`。每句可提供 `audio: "audio/N001.wav"` 覆盖 TTS，必须为非空 PCM WAV。只有整段录音时，先取得可靠分句对齐，再用实际边界切成逐句 WAV；不支持按字数猜时间。
- 本地 MeloTTS 的 speaker 名称须存在于模型，常用中文为 `ZH`。`revision` 用于本地模型/权重更新后的主动缓存失效，更新模型后递增它。MeloTTS 可能在模型未缓存时联网获取模型；无下载授权时先确认现有环境和模型缓存齐全。
- MeloTTS 的 g2p_en 导入可能触发 NLTK 数据下载，脚本先检查 `cmudict.zip` 和 `averaged_perceptron_tagger.zip`。查找失败时显示搜索路径，先让用户选择 `runtime.nltk_data` 指向已有资源，不能据此判断机器没有安装；仅在确认需要新增资源后征得下载授权。不通过关闭网络安全检查解决。
- 每句 WAV 以真实样本数测量时长，再向上对齐整数视频帧，只在句尾补不足一帧的静音，不裁掉讲话。时间轴和 SRT 使用这些帧边界。因此长片总时长可能比原 WAV 时长之和多出少量补齐时间。
- 一个镜头可引用多句，必须按原顺序完整覆盖所有句子一次，不允许重复、漏句、重排。ID 仅用英文字母、数字、下划线、短横线。
- 字幕每句一个时间区间，可折成两行，不伪造逐字时间。单句超过 `2 * max_chars` 时需在真实口播停顿处分句，更新批准稿/分句审批后重跑。size、margin 是 720p 参考像素值，随分辨率缩放；移动端预览通常从 32px（720p）起步，再以抽帧确认可读性。每句字幕不得跨越不对应的镜头。

### 运镜、转场及 Demo

- `motion`：`still`、`push`、`pull`、`pan-left`、`pan-right`。推拉幅度 6%，平移保持轻度裁切；输入按画幅裁切填满。
- `transition` 是该镜头到下一镜头的叠化秒数，`0` 表示硬切，范围 0–2 秒，须短于相邻两镜头。脚本额外生成运镜尾帧，与下一镜头开头叠化；不压缩解说、不累积提前切镜。
- `demo.shots` 是连续镜头 ID 列表，20–40 秒是创作建议，非硬编码限制。中段 Demo 需设置 `demo.start_seconds`，用于在全片音乐时间轴上截取相同段落。制作 Demo 前可依据文案估算该位置，完成全片真实配音后必须核对；如音乐听感改变，更新 Demo 并重新确认。
- `music` 为多段音轨，可重叠；不足长度自动循环，分别淡入淡出，并依据解说进行 sidechain ducking。start/end 使用全片秒数。每个项目先询问创作者音乐意图，再检索至少 3 个候选并让创作者试听；明确选择后才下载和写入 `music`。候选阶段只记录在 `music-selection.json`，不要把未批准音频放入项目。记录预览链接、下载地址、许可、用户选择原话和 SHA-256，避免跨项目无意复用同一曲目。解说统一响度至目标 -18 LUFS，混音加峰值限制器，最终仍需试听成片。

### 增量与验证

文案/分句改变会使 script 和 Demo 批准失效；style、voice、字幕、输出、音乐及 Demo 镜头内容改变使 Demo 批准失效。其他镜头换图不要求重新批准 Demo。文件内容用 SHA-256 检查，路径相同但内容变了也会失效。

缓存分为 TTS、图片运镜、镜头音视频、拼接、最终字幕混音。每步成功后写入校验记录；失败的 partial 文件不会被当作成功缓存。换图重做相关运镜和叠化的下一镜头，换字幕不重做图片，改配音仅重做受影响内容和下游。最终封装/校验仍需遍历整片，不代表完全免除全片处理。渲染器代码变化使缓存失效，模型更新用 voice.revision 失效。缓存不自动清理。

`check` 仅检查结构、口播一致性与引用覆盖；`verify` 完整解码视频/音频、检查视频帧数和时间轴连续性、抽取首中尾三帧。报告里的视觉和试听项默认 pending，agent 实际看过/听过后可补充范围和结论；不能把结构验证当作内容、史实、声画同步或听感全面合格。

同一错误连续出现两次先调查原因。不要删除缓存强行重跑，也不要新增临时主题专用渲染脚本；修正通用实现或项目配置。

## 脚本回归测试

`scripts/test_pipeline.py` 使用已有两张不同图片、临时生成的 PCM 测试音和真实 FFmpeg，在指定输出目录下建立独立临时工程，检查审批门禁、时长、增量更新、失败续跑和缓存损坏恢复。测试批准明确标为 TEST FIXTURE，不适用于真实制作。命令参数为 `--ffmpeg`、`--image`、`--alternate-image`、`--output`。音色和长片性能不在该测试覆盖范围内。
