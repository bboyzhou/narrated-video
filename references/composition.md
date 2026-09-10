# 动态素材合成

使用现有 Python 标准库与 FFmpeg，不新增模型或 Python 依赖。合成前检查 overlay、scale、pad、rotate、geq、tpad、fps 滤镜。旧纯图片配置仍可使用。

## 素材获取

优先项目文件，再查询配置的离线素材库。缺素材时，agent 可用当前联网工具检索，核对具体素材的来源、许可、署名与下载权限后，下载到项目目录。需要付费、账户或许可不明确时由用户提供资源或选择可用替代。当前无平台 API、自动爬虫或内置素材包，也无自动语义选材；渲染器不联网、不下载。不要把“免费”直接等同可商用。音乐仍遵循独立的试听选择流程。

项目顶层设置 `"asset_library": "D:/MediaLibrary/index.json"`。目录文件为 UTF-8：

```json
{
  "version": 1,
  "assets": [
    {
      "id": "smoke-soft",
      "type": "video",
      "path": "effects/smoke-soft.mov",
      "tags": ["smoke", "烟雾"],
      "source": "实际来源或自制记录",
      "license": "实际许可和署名要求"
    }
  ]
}
```

`path` 相对于目录所在文件夹，解析后须位于该文件夹内部；ID 唯一。用 `python scripts/composition.py <index.json> --query smoke` 只读查询，返回类型、路径、来源、许可与可用性；按文本匹配，不做视觉理解。通过 `"asset": "library:smoke-soft"` 引用。仅当前所选镜头素材需要存在，非 Demo 缺失素材不阻塞 Demo。

网络素材在制作阶段获取一次，并在镜头/图层记录 `source/license`。manifest 自动记录实际路径和 SHA-256；目录引用还携带目录条目的元数据。工程移交时复制选中素材进项目并替换引用，或一起携带素材库并调整目录路径；渲染不会自动打包外部素材。

## 图层配置

给已有镜头增加 `layers`，按数组从下到上合成，位于最终字幕下方：

```json
{
  "layers": [
    {
      "id": "character",
      "type": "image",
      "asset": "images/character-cutout.png",
      "source": "用户提供",
      "license": "实际使用说明",
      "start": 0.5,
      "end": 5.5,
      "width": 0.3,
      "height": 0.6,
      "easing": "smoothstep",
      "keyframes": [
        {"time": 0, "x": -0.2, "y": 0.5, "scale": 0.9, "rotation": -5, "opacity": 0},
        {"time": 1, "x": 0.3, "y": 0.5, "scale": 1, "rotation": 0, "opacity": 1},
        {"time": 4, "x": 0.35, "y": 0.48, "scale": 1.05, "rotation": 3, "opacity": 1},
        {"time": 5, "x": 0.4, "y": 0.48, "scale": 1, "rotation": 0, "opacity": 0}
      ]
    }
  ]
}
```

- `start/end` 是镜头内秒数，采用 `[start,end)`，不能超过实际配音帧对齐时长。不按字数猜测同步。
- `width/height` 是相对输出画幅的适配框，默认均 0.3；素材等比缩入，空白透明。
- `x/y` 是素材框中心的屏幕归一化坐标，左上 `(0,0)`，右下 `(1,1)`，允许画外入场。不会自动跟随基础图像运镜。
- `scale` 是相对适配框的倍率；`rotation` 为绕中心旋转角度；`opacity` 为 0..1，与原有 alpha 相乘。透明 PNG 或解码后带 alpha 的视频保留透明；黑底视频不会自动去黑。
- 每个关键帧必须完整包含五个属性，`time` 相对图层起点，首帧为 0，严格递增且不晚于 `end-start`。末帧之后保持最后状态。
- `easing` 支持 linear/smoothstep，默认 smoothstep，在相邻关键帧间插值。每镜最多 16 层，每层 32 帧；旋转画布边长不超过 8192 像素。大透明图层会增加计算量，优先裁去无用透明边距。

背景和图层先合成，再参与镜头转场。图层在 end 结束，不延长至额外转场尾帧；自然退场应在结束前设置透明度动画。说明卡片、箭头等可由透明 PNG 实现，当前未新增动态文字或 ASS 高亮渲染。

## 视频素材

镜头或图层使用 `"type": "video"`；基础视频镜头须显式 `"motion": "still"`，等比居中裁切填满画幅，视频图层等比适配图层框。

- `source_start` 默认为 0，从源视频第几秒开始，需处于可解码范围。
- `loop` 默认为 false：视频不足时停留末帧；true 循环整个输入文件。偏移用于首次读取，后续按文件循环；固定片段循环应先准备裁好的视频。
- 只取第一条视频流，素材原声全部忽略，继续使用已有配音/配乐。图片不接受截取/循环选项。
- 无自动抠图、语义识别、遮挡补全、骨骼动画或生成式人物动作。

## 分镜与验证

`storyboard.json` 对应镜头须与项目保持相同 `layers/type/source_start/loop`，旧图片分镜可省略。审阅时说明图层用途、来源、起止时间和关键动作，不只交原始 JSON。素材和配置参与缓存及 Demo 指纹，非 Demo 图层变更保留未受影响的 Demo 批准。

沿用 `check/render/verify`。渲染前检查文件和滤镜，得到实际音频后检查区间；自动验证解码和总帧数。人工额外检查图层开始、中间、结束、旋转边界、透明区域、转场与字幕遮挡；首中尾三张抽帧不等于所有动画合格。

manifest 保留兼容字段 `images`（镜头列表，其中 type 可为 video），新增 `layers`，含图层来源及哈希。SRT 继续交付。

开发验证：设置 `FFMPEG` 为已有可执行文件后运行 `python -m unittest discover -s scripts -p "test_*.py"`。不设置会跳过真实媒体验证，不代表渲染检查通过。
