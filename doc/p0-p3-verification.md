# P0–P3 修复与验证记录

日期：2026-09-15。范围为 narrated-video 能力包及本机已安装 Skill；未修改 binary-explainer 的项目配置、视频或批准记录，未提交/推送。

## 已实现

| 优先级 | 落地内容 |
|---|---|
| P0 | 图层半开生命周期、全部分段关键帧、局部视频时间、源末帧停留/循环、上一镜转场时长、基础运镜边缘覆盖；修复 Remotion+BGM 输入索引、Demo 渲染器配置指纹；增加源码/素材 bundle 缓存、视觉产物哈希校验、preflight 包版本检查与明确降级原因；安装包备份同步 |
| P1 | 最终逐句 PCM 的音频/原文哈希契约、原文字符区间 cue、重复词消歧、过期/低分/无边界拒绝；本地 Whisper 严格 ASR 及固定版本 attention-DTW 路径；逐帧保守几何、重叠、可见时段、必需标签和状态检查 |
| P2 | selector/formula/nodes/coin 基础教学图形；高亮状态跟随事件，硬币动画限定在自身容器并落定 |
| P3 | 有界横向视差、可复现粒子、光扫和暗角；增强字段禁止静默降级为不支持的 FFmpeg 画面 |

Skill 入口增加声画事件参考和准确能力边界，补充 3 个行为评估案例。评估案例已编写，未进行独立模型行为评分，不把它们计作自动测试通过。

## 实际验证

- Python 单元测试：仓库与安装目录各 75 项全部通过（显式配置现有 FFMPEG，没有跳过）。
- Node 动画规则测试：7 项通过，覆盖中间关键帧、图层结束边界、运镜覆盖、状态保持、缺状态/隐藏状态/碰撞及轨迹越界。
- 旧 FFmpeg 回归：通过完整脚本；Demo 67 帧、全片 103 帧，无变化时 0 项重新渲染；修改非 Demo 素材仅重做相关缓存。
- Remotion 真浏览器测试：仓库及安装目录各通过 Demo/full；使用现有 Chrome、Remotion 4.0.524 与 FFmpeg。安装目录测试全片 103 帧，复跑 0 项重新渲染、13 项缓存复用；逐帧计划 QA 通过。测试覆盖三镜、不同转场、短视频停留/循环、局部视频图层、字幕和 BGM。
- 查看了仓库测试的第 15、48、85 帧，核对高亮、局部视频与硬币画面；这是 320×180 合成测试，不是生产美术验收或全片逐帧人工审核。
- 真实音频：只读原项目 N030 最终 WAV。严格 ASR 因错字拒绝；固定 Whisper 20231117/small 官方哈希的 attention-DTW 生成有效 spans。“一个字节”事件解析为 1.86 秒/第 56 帧；“八个比特”低分事件被拒绝。没有把低分标成成功，没有伪造人工试听。
- quick_validate（仓库与安装目录）、Python compileall、git diff --check 通过；Git 仅有已有行尾设置产生的 LF/CRLF 提示。

本机结果保留在 `.test-output/validation-vivpp3ck`、`.test-output/remotion-gf5o7hxd`、`.test-output/installed/remotion-ixcjj6ku` 与 `.test-output/real-forced.json`。这些均为忽略的本地测试文件，不进入提交。

## 安装与恢复

已同步到 `C:/Users/Lenovo/.codex/skills/narrated-video`，包含完整 `renderers/remotion` 及复制的本地 node_modules，不联网、不安装新版本。初次同步校验 11529 个文件；安装目录 `installation-manifest.json` 记录各文件哈希与最近一次备份位置。

原安装文件的首轮备份位于 `C:/Users/Lenovo/.codex/skill-backups/narrated-video-wxkze9yp`，后续小批量同步另建备份，不删除目标独有文件。新任务加载更新后的说明；已加载的旧会话上下文不会自动改写。

## 剩余边界

- 这不是全量 Remotion 编辑器，也不修改原项目中历史的定制 FFmpeg 动画脚本。
- 词级对齐不是全自动准确率保证：发音代理需要显式映射 Provider，低分须试听复核；内部 attention-DTW 仅支持已测试版本、30 秒以内逐句音频。未做全片真实语音准确率 benchmark。
- 自动 QA 检查的是同一渲染计划的保守几何/事件，不是字形测量、OCR、语义理解或角色一致性模型。主观同步、字体可读性和知识表达仍保留人工验收。
- 当前仍先走兼容 FFmpeg 基础视觉流程再覆盖 Remotion 视觉，有额外渲染开销。bundle 缓存未实施自动回收。
