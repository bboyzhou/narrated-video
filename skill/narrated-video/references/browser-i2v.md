# Browser I2V 执行与恢复

此流程通过用户当前已登录的网页账户使用免费额度。Python 管理确定性状态；Computer Use 处理会变化的网页。不得自动购买、充值、订阅、绕过验证码或把付费余额当成免费额度。`cost_confirmed_zero` 表示不会扣现金、会员额度或付费余额；平台明确从赠送的免费积分中扣除时仍可为 `true`。

## 工程配置

在已批准的 `generated_video` 镜头中使用 `generation.provider: browser_i2v`，并在工程 Provider 中配置：

```json
{
  "enabled": true,
  "provider": "browser_i2v",
  "profile": "balanced",
  "runtime": {"type": "browser"},
  "policy": "selected",
  "i2v_budget": {"enabled": true, "max_shots": 3, "max_generated_seconds_per_shot": 5},
  "providers": {
    "browser_i2v": {
      "platforms": ["pixverse", "jimeng", "kling"],
      "free_only": true,
      "quota_max_age_seconds": 600,
      "query_interval_seconds": 1800,
      "max_attempts": 2
    }
  }
}
```

平台顺序是用户允许的偏好，不是可用性承诺。每次提交都以当前页面观察为准。

## 命令与动作循环

```powershell
python scripts/pipeline.py i2v-plan narrated-project.json --stage demo
python scripts/pipeline.py i2v-next narrated-project.json --stage demo
python scripts/pipeline.py i2v-observe narrated-project.json --observation observation.json
python scripts/pipeline.py i2v-status narrated-project.json
python scripts/pipeline.py i2v-sync narrated-project.json --stage demo --ffmpeg D:/path/ffmpeg.exe
```

`i2v-next` 返回 `inspect`、`submit`、`query`、`query_history`、`download` 或 `none`。执行者按照动作中的平台和请求操作网页，将可核验结果写入 UTF-8 JSON，再用 `i2v-observe` 接收。动作文件同时保存在 `.narrated-video/i2v/requests/`。

检查成功回执示例：

```json
{
  "action_id": "BI2V-S003-abc-INSPECT-1",
  "platform": "pixverse",
  "outcome": "available",
  "logged_in": true,
  "free_eligible": true,
  "cost_confirmed_zero": true,
  "model": "页面显示的模型名称",
  "quota_hint": "页面显示的免费余额",
  "queue_hint": "页面显示的排队信息"
}
```

提交成功必须记录 `remote_task_id`、`task_url` 或足以唯一匹配的 `visible_signature`。点击提交后无法确认结果时返回 `outcome: unknown`；系统进入 `SUBMISSION_UNKNOWN` 并先执行 `query_history`，禁止直接重新提交。

查询回执使用 `submitted`、`queued`、`generating`、`completed`、`failed` 或 `not_found`。下载回执必须使用 `downloaded` 并提供本地文件路径。登录、验证码、额度、费用不明、平台繁忙、UI 变化和下载不可用使用对应 outcome；系统记录该平台失败并尝试下一个被允许的平台，全部不可用时才阻塞任务。

## 状态和停止条件

任务生命周期：

```text
PLANNED → READY → SUBMITTED/QUEUED/GENERATING → COMPLETED
        → DOWNLOADED → ATTACHED
```

另有 `SUBMISSION_UNKNOWN`、`FAILED`、`CANCELLED` 和 `SUPERSEDED`。请求摘要由源图哈希、提示词、约束、目标参数与路由构成；相同摘要重用原任务，源图或请求改变时旧任务标记为 `SUPERSEDED`。

- 一个已领取但未回执的动作不会再次领取。
- 排队、生成或结果不明的任务不重复提交。
- 下载失败只重试下载，不重新生成。
- 页面没有任务记录且无法唯一匹配时停止，请用户核实。
- Python 进程退出后不会自行轮询；再次运行 `i2v-next` 才继续。

## 平台操作指南

只读取实际动作对应的平台：

- [PixVerse](browser-providers/pixverse.md)
- [即梦](browser-providers/jimeng.md)
- [可灵](browser-providers/kling.md)

操作指南描述业务意图，不固定像素坐标或 CSS。若当前页面和指南不一致，记录 `ui_changed`，不要猜测会消耗额度的按钮。

## 下载、验证与接入

下载后执行 `i2v-sync`。系统检查视频流、尺寸、时长、完整解码和哈希，再复制到 `assets/generated-video/browser_i2v/<request-digest>/` 并登记到镜头。水印、主体一致性、动作质量和使用条件仍需人工观看；自动解码通过不代表内容合格。

生成期间工程可能变化。接入时请求摘要必须仍与当前镜头相符；否则旧结果只保留为历史任务，不进入渲染。原图资产始终保留为回退。
