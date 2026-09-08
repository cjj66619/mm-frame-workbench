---
name: frame-apply
description: 执行 frame_plan.json：改标题 / 层级 / 顺序、整节删除、新增空标题，重排编号并同步正文交叉引用（留痕），零漂移校验通过才写 frame/sections/，原稿只读。
---

# frame-apply

```bash
python .agents/skills/frame-apply/scripts/apply_frame.py <proj> [--plan frame/frame_plan.json] [--src paper/sections] [--out frame/sections] [--dry-run] [--strict]
```

- 解析 Markdown 为扁平标题序列（子树由层级推出），按 op 顺序执行，最后统一 `link_parents` 检查层级连续。
- `numbering: auto`：一级章按原稿风格（阿拉伯 / 中文）连续编号；无编号的摘要 / 参考文献保持无编号；附录 A、B、C…
  子节 A.1；下级按 `chap.sec.sub`。旧编号 → 新编号的映射写进 `frame_apply.json.numbering`。
- **引用同步只改四种显式写法**：`第 N 章`、`N.N 节 / 小节`、`§N.N`、`见 / 参见 / 详见 / 如 N.N`；一次扫描完成
  （避免 4.5→4.6 再被 4.6→4.7 连锁改写）；标题行与代码块不动；每处替换记 `refs[{file,line,old,new}]`。
  裸数字（3.14、表 2.1 之类）不碰。merge_up 掉的节的旧编号指向接收它的节。
- **零漂移校验 `verify_drift`**：原稿非标题行多重集 = 新稿 + 被删节正文 + 引用替换；被删节内定义的
  `{#fig:…}` / `{#tbl:…}` / `{#eq:…}` 仍被 `@` 引用 → FAIL。任何 FAIL / 问题都不写文件（`NOT WRITTEN`）。
- `verify.warn`：正文"见 N.N 节"指向被删节 —— 不是 FAIL（工具不改正文），但要报给用户。
- 写出：`frame/sections/*.md`（文件名与原稿一致）、`frame/paper.yaml`（复制）、`frame/frame_apply.json`。
