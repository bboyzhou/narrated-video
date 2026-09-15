# 声画事件与动画 QA

## 对齐输入与门禁

只对响度、语速、句尾停顿处理后的逐句 PCM WAV 做对齐，使用 `pipeline.py alignment-prepare PROJECT --stage demo` 导出请求（全片沿用 Demo 批准门禁）。禁止以 BGM 混音、裁切 Demo 的局部时间或字数均分推算声画事件。

请求位于 `.narrated-video/alignment-requests/<stage>/<sentence>.json`，含绝对音频路径、显示原文 `text`、实际口播 `tts_text`、duration 与音频/文本 SHA-256。选择用户已有的本地对齐 Provider、固定 revision，再配置 argv `command`（必须含 `{request}` 与 `{output}`），运行：

```text
python scripts/alignment.py REQUEST.json ALIGNMENT.json
```

Provider 输出 version=1、audio_sha256、text_sha256、provider、revision、spans。每段包含零基 Unicode 字符区间 `[char_start,char_end)`、音频秒数 start/end、confidence 与 method（forced/asr_mapped/manual）。必须递增、无重叠、在音频内；结果写入 `narration[].alignment`。后续改语速/配音/文本后，旧 hash 不匹配会拒绝渲染。

已有 openai-whisper 环境可用 `scripts/whisper_alignment.py` 作为 Provider。请求额外需要 `model_path`（已有文件绝对路径）、`model_sha256`、`ffmpeg`、已安装 openai-whisper 的准确版本 `revision`，可选 language/device。command 为 `[已选Python, whisper_alignment.py绝对路径, "{request}", "{output}"]`。不下载模型或安装依赖；完整 ASR 字符序列必须匹配原文（忽略标点/大小写），否则拒绝。识别词内部不均分时间；无法命中 token 边界须更换可靠对齐 Provider。`tts_text` 与原文不同时此适配器拒绝执行，改用能显式映射发音代理的 Provider。此处不是通用强制对齐算法，Whisper confidence 也不是经校准的同步准确率。

同一适配器可显式选择 `mode: forced`：当前仅支持已验证的 Whisper `20231117`，需要 `model_name` 和对应官方模型哈希，直接用原文 token 的 attention-DTW 计算边界（不是把 ASR 错字替换回原文）。单句上限 30 秒，不能超过模型 token 上限；它仍不支持发音代理映射，也不是专业声学对齐准确率保证。ASR 不匹配时不会自动偷偷改为 forced，须显式选择。两种模式都保留 `.diagnostics.json`；强制对齐仍可能产生低分或零时长，不能为了通过检查而伪造边界/置信度。

人工修订须标 method=manual；使用它的 cue 必须显式 `allow_manual: true`，报告保留方法来源。不能把人工秒数称为自动实测。重复词以字符区间消歧，不以第一次搜索命中作为锚点。显示字幕继续使用 SRT 原文；尚无逐词字幕高亮。

## 可复用动画字段

在项目 shot 和对应 storyboard shot 中写入相同 `graphics`/`effects`。graphics 位置为左上角归一化 x/y/width/height；图层位置仍是中心点。图形 start_frame/end_frame 是相对镜头的半开区间，不能超过实际口播总帧数。状态 cue 示例：

```json
{
  "id": "switch", "kind": "selector",
  "x": 0.1, "y": 0.15, "width": 0.8, "height": 0.25,
  "start_frame": 0, "end_frame": 90,
  "items": ["高电平", "低电平", "导通", "关闭"],
  "required_indices": [0, 1, 2, 3],
  "states": [
    {"index": 0, "cue": {"sentence": "N1", "char_start": 0, "char_end": 3, "text": "高电平"}}
  ]
}
```

该片段仅示范字段；必须补齐四个状态，否则 required_indices 检查会失败。默认 confidence 门槛为 0.7；低可信、缺词、错原文、旧音频和越界事件均拒绝，不填估计 fallback。非口播驱动的装饰/设计时序可用 `frame` + `timing_source: manual`，不要冒充词级对齐。

- `selector`：卡片行与状态高亮；`formula`：公式 token 行与结果 label；`nodes`：带连接线的节点行；`coin`：容器内一次抛起、旋转并落定（不是物理仿真）。
- `required_labels` 声明不可丢失的原文字串，`required_indices` 声明必须出现的选择状态。二进制科普可保留 1011、8/4/2/1、8+2+1=11，但不要把这些领域数据写死为所有项目规则。
- 图层 `depth` 范围 -2..2，叠加横向镜头视差；`constrain_to_frame: true` 检查旋转/缩放后的全轨迹安全区。
- `effects` 可选 `particles`（0..80 整数）、`vignette`/`light_sweep`（0..0.5）。均为可复现装饰，不改变音频或事件时间。
- 增强字段仅 Remotion 支持，必须 `renderer: {engine: remotion, fallback: none}`，避免降级丢失关键信息。

## 验证范围

`{stage}-render-plan-qa.json` 检查每个状态和每个口播帧的图形/图层保守边界，包括旋转和视差；图形间、图形与图层间默认不可重叠。确有设计需要才用 `allow_overlap_with: [ID]` 显式豁免；图层彼此叠加默认允许。不允许仅以另写的容器示意证明运动轨迹正确。

检查状态顺序、可见时段、索引范围、必需内容和相邻转场。此层是协议/几何检查，不是浏览器文字测量、OCR、语义理解或角色一致性识别；report.pending_review 必须保留。最终视频至少核对事件前/后帧、所有状态、首中尾和切镜，并试听对应关键词。只有实际查看/试听过的范围才写为人工通过。

自动回归入口：`python -m unittest discover -s scripts -p "test_*.py"`、`node renderers/remotion/scripts/test.mjs`、`scripts/test_remotion_smoke.py --help`。新增模板时先加入失败案例（缺状态、旧 hash、中间关键帧越界、碰撞）再扩效果。
