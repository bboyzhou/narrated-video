# 分镜设计与审批

在口播稿批准后、生成图片或配音前读取。本阶段把“说什么”转换为可审核的“怎么拍”，目标是让画面生成、运镜、节奏和 Demo 验证都有明确依据。

## 制作顺序

1. 从已批准口播稿提炼制作纲要，不新增未经查证的事实。
2. 先按叙事节拍划分镜头，再写画面；一个镜头可以覆盖多句，但所有句子必须按原顺序覆盖一次。
3. 为全部镜头填写 `storyboard.json`，同步项目 `shots` 中的口播映射、正负提示词、运镜与转场。
4. 运行 `check`，处理结构错误和时长警告。口播阶段使用 `check --stage script`；完整分镜阶段使用默认 `check`。
5. 向用户展示制作纲要、完整逐镜表、Demo 选段理由和验证目标，等待实际批准。
6. 批准后记录：

```powershell
python $pipeline record $project --stage storyboard --quote '用户实际批准回复'
```

没有实际批准时不得记录。用户明确要求跳过审核时才可加 `--skip`，但仍须建立完整分镜，保证制作输入明确。

## 制作纲要

`creative_brief` 必须回答：

- 给谁看、在哪里发布、希望观众看完理解或感受到什么；
- 目标时长、叙事起伏和节奏密度；
- 画面风格、口播方向和配乐方向；
- 跨镜头必须保持的角色外观、服装、道具、场景、时代、色彩或光线；
- 画面禁忌、事实边界、品牌或平台限制。

未获得用户输入时可以提出有依据的建议，但应标为建议并在同一次分镜审批中确认。`music_direction` 只是创作方向，不能代替实际曲目试听和授权确认。

## 逐镜头标准

每个镜头必须明确：

- `purpose`：这张画面承担的叙事信息或情绪作用；
- `narration` 与 `estimated_duration_seconds`：对应口播及预计停留时长；
- `visual`：主体、动作、环境、景别、构图、光线与色彩；
- `continuity`：从全局锚点中继承或延续的具体要素；
- `asset_strategy`：`user`、`generate`、`licensed` 或 `mixed`；
- `prompt` 与 `negative_prompt`：实际用于图像检索或生成的正负约束；
- `motion` 与 `transition_seconds`：必须与项目渲染配置一致。

提示词应写可见内容和构图，避免只写“震撼”“高级”“电影感”等不可执行形容词。角色或地点重复出现时，使用一致的名称和连续性描述；镜头需要变化时写清变化点，不靠生成工具自行推断。

## Demo 选择

选择连续、具有代表性的约 20–40 秒，不必默认使用开头。`selection_reason` 说明为什么这段能代表全片；`validation_goals` 应覆盖其中真正需要验证的风险，例如：

- 同一人物跨镜头的一致性；
- 远中近景切换与运镜是否自然；
- 专名读音、口播速度和字幕可读性；
- 音乐情绪与转折点是否匹配；
- 特殊构图、历史细节或图解是否清楚。

短片可选择更短 Demo，但必须说明理由。`check` 对 20–40 秒只给警告，不替代创作者判断。

## 审阅格式

先用短段落展示制作纲要，再用表格展示所有镜头。每行至少包含：

| 镜头 | 对应口播 | 预计时长 | 叙事作用 | 画面与构图 | 连续性 | 运镜/转场 | 素材策略 |
|---|---|---:|---|---|---|---|---|

表格后单列 Demo 镜头、选择理由、验证目标和仍需用户决定的问题。正负提示词较长时可放在镜头表后的折叠详情或分组列表，但不能省略不交付。

## JSON 示例

```json
{
  "version": 1,
  "creative_brief": {
    "audience": "对主题感兴趣的普通观众",
    "platform": "横屏公开视频平台",
    "purpose": "清楚解释事件因果并保留克制情绪",
    "target_duration_seconds": 90,
    "narrative_arc": "背景铺垫—冲突升级—结果与余韵",
    "visual_style": "写实历史插画，低饱和土色，统一人物设定",
    "pacing": "前段舒缓，中段加快，结尾停顿",
    "voice_direction": "沉稳自然，语速略慢，专名清晰",
    "music_direction": "无歌词、低干扰、冲突段能量上升",
    "continuity_anchors": ["主角深色布衣与右侧束发", "统一低饱和土色"],
    "constraints": ["不出现现代物件", "不在画面内生成文字"]
  },
  "shots": [
    {
      "id": "S001",
      "narration": ["N001"],
      "purpose": "交代人物与环境",
      "estimated_duration_seconds": 7.5,
      "visual": {
        "subject": "主角",
        "action": "站在城门外观察远处",
        "setting": "薄雾中的古代城门",
        "shot_size": "中远景",
        "composition": "人物位于左三分线，右下保留字幕安全区",
        "lighting_color": "清晨侧逆光，低饱和土灰色"
      },
      "continuity": ["沿用深色布衣和右侧束发", "城门形制在后续镜头保持一致"],
      "asset_strategy": "generate",
      "prompt": "写实历史插画，中远景……",
      "negative_prompt": "现代建筑、文字、水印、服装变化、额外人物",
      "motion": "push",
      "transition_seconds": 0.3
    }
  ],
  "demo": {
    "shots": ["S001"],
    "selection_reason": "包含人物、环境和代表性运镜",
    "validation_goals": ["验证人物设定、字幕安全区和缓推速度"]
  }
}
```

## 修改与批准失效

- 口播文字或分句变化：重新批准 script、storyboard 和 Demo。
- 制作纲要、Demo 选段或 Demo 镜头变化：重新批准 storyboard 并重做/批准 Demo。
- 只修改非 Demo 分镜：重新批准 storyboard；原 Demo 批准保留。
- 只替换非 Demo 的实际素材或配音且分镜意图不变：不撤销 storyboard 或 Demo。

旧项目首次升级时补充 `storyboard` 路径和完整文件。既有 script 批准在口播未变时可沿用；由于 Demo 指纹新增了分镜内容，需按新分镜重新生成并批准一次 Demo。
