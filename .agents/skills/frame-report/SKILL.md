---
name: frame-report
description: 汇总 apply 前后的盘点与 lint、校验结果、删节 / 改名 / 引用同步留痕，写 frame/FRAME_REPORT.md。
---

# frame-report

```bash
python .agents/skills/frame-report/scripts/report_frame.py <proj>
```

读 `frame_inventory.json` / `frame_lint.json`（前）、`after_inventory.json` / `frame_lint_after.json`（后）、`frame_apply.json`。
输出：状态行、前后指标表（H1/H2/H3 数、lint 各级计数、WARN 按规则）、应用与校验（删节、引用同步、标题变更、
需人工处理的提醒）、应用后仍存在的 WARN / FAIL、下游交接说明。未 apply 时只写"前"的状态。
