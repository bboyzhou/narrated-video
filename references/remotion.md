# Remotion 渲染 Adapter

Remotion 只作为可选视觉渲染器。Python 先根据真实配音帧数生成 Render Plan，Remotion 消费该 JSON 生成无声画面，随后由 FFmpeg 继续完成字幕、配音、BGM ducking、响度处理和最终封装。项目数据不能直接依赖 React 组件。

配置示例：

```json
{
  "runtime": {
    "node": "C:/Program Files/nodejs/node.exe",
    "browser": "C:/Program Files/Google/Chrome/Application/chrome.exe"
  },
  "renderer": {"engine": "remotion", "fallback": "ffmpeg"}
}
```

`renderers/remotion/package.json` 与 `package-lock.json` 必须固定版本。渲染前必须确认 Node、浏览器和依赖已存在；不要调用会自动下载 Chrome 的默认路径。Remotion 不可用时只回退当前渲染阶段，并在 renderer 报告中记录实际引擎和原因。

当前 Adapter 支持图片/视频镜头、Ken Burns 运镜、分段图层关键帧、图层局部视频时间、循环/末帧停留、受控素材暂存和 Demo/full 两阶段。叠化使用上一镜的出场时长控制下一镜入场透明度，图层随镜头一起叠化。高级字段见 [声画事件与动画 QA](animation-alignment.md)：提供基础 selector/formula/nodes/coin、视差 depth、粒子、暗角和光扫，不代表完整编辑器或任意动态图形系统。

Remotion bundle 按源码、lockfile 和暂存素材内容缓存至 runtime 的 `.bundle-cache`；计划/渲染器源码参与视频缓存，命中时校验输出哈希。依赖和 bundle cache 不进入 Skill 发布包。音频与最终封装由公共后处理链路完成。

`preflight` 检查已选 Node/浏览器路径和本地包可导入；真实浏览器兼容性必须用 `scripts/test_remotion_smoke.py` 验证，不能仅凭包存在宣称可用。该测试使用临时项目、合成音和显式人工时间戳，不评价真实语音识别质量。输出 `{stage}-render-plan-qa.json` 与 `{stage}-renderer.json`，后者包含请求/实际引擎与 fallback_reason。QA 的 passed 只覆盖报告声明的规则；字体、可读性、主观同步仍需人工复核。

Remotion Adapter 属于 runtime 仓库，不属于 Skill。Skill 只包含选择规则和薄入口；`scripts/build_skill.py` 会拒绝 `renderers/`、`node_modules`、缓存和测试输出。Runtime 更新后校验源码与 lockfile、运行 quick validate 和真实 smoke；当前会话已加载的旧说明不会自动替换，新任务会加载新 Skill。
