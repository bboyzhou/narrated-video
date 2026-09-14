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

当前 Adapter 支持图片/视频镜头、基础 Ken Burns 运镜、图层关键帧、受控素材暂存和 Demo/full 两阶段。首次接入先做同一测试项目的 FFmpeg/Remotion 双渲染，比较分辨率、FPS、总帧数、字幕边界和抽帧；高级粒子、视差、光扫等效果应在协议对齐后再加入。Remotion bundle 按代码版本缓存，不要每条视频重新 bundle。
