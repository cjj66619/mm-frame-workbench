---
name: frame-plan
description: 依据 FRAME_LINT 手写 frame/frame_plan.json（rename / relevel / merge_up / delete / move / insert，每条带理由与证据），plan_frame.py 做 dry-run 校验并渲染 FRAME_PLAN.md（前后目录对照）交用户确认。
---

# frame-plan

## 计划文件 `frame/frame_plan.json`

```json
{
  "src": "paper/sections",
  "numbering": "auto",
  "ops": [
    {"op": "rename",   "id": "04_x.md:77",  "new": "模型建立",  "why": "语料主流写法 67 次；原题「精修」为工程腔（term_map）"},
    {"op": "relevel",  "id": "04_x.md:112", "level": 2,        "why": "内容独立成节，与兄弟节平级"},
    {"op": "merge_up", "id": "04_x.md:112",                    "why": "独子节，标题去掉正文并入上节"},
    {"op": "delete",   "id": "08_x.md:162",                    "why": "无结论、与 8.4 重复；正文 3 行无图无公式"},
    {"op": "move",     "id": "06_x.md:66",  "after": "06_x.md:80", "why": "结果分析应在方法之后"},
    {"op": "insert",   "after": "05_x.md:1", "level": 2, "title": "问题分析", "why": "问题章缺分析环节（语料 0.56/章）"}
  ],
  "keep": [
    {"id": "02_x.md:9", "why": "「总体技术路线」是本篇重要导览，保留冒号"}
  ]
}
```

- `id` 取自 `frame_inventory.json` 的 `id`（`文件:行号`），全部指向**原稿**位置；ops 顺序执行，但 id 始终按原稿解析。
- `rename.new` 不带编号、不带 `#`；编号由 `numbering: auto` 统一重排（保留原稿的阿拉伯 / 中文 / 附录风格，摘要与参考文献不编号）。
  `numbering: keep` 保留原编号不动。
- `relevel` 平移整棵子树；`merge_up` 只去标题、正文归入前一节、子节层级不变；`delete` 删整棵子树含正文；
  `move` 只在同一文件内挪整棵子树；`insert` 只加空标题，不许生成正文。
- `why` 必填并给证据：语料频次 / 角色主流写法 / term_map 候选 / 正文用法 / 用户原话。
- `keep` 记录看过但决定保留的 WARN（带 `why`），FRAME_PLAN.md 会把它们从"未处理"里移到"计划声明保留"。
- `notes`（可选，字符串列表）：整份计划的原则性说明（如为什么不改问题章句式、为什么不压 H2 数量），渲染到"计划说明"。

## 校验与渲染

```bash
python .agents/skills/frame-plan/scripts/plan_frame.py <proj> [--strict]
```

dry-run 跑一遍 apply 但不写文件：op 不存在 / 越界 / 跨文件 / 层级不连续 → 问题；正文漂移 / 标签悬空 → FAIL；
正文引用了被删节 → 提醒（工具不改正文，用户决定不删或回 polish 改句子）。`FRAME_PLAN.md` 含总览、变更清单、
前后目录对照（`←` 标改动、删除线标删节）、未处理的 WARN。**用户确认 FRAME_PLAN.md 之前不要 apply。**

## 写计划的原则

1. 先定一级章骨架（重述 → 分析 → 假设与符号 → 问题 N → 检验 / 评价 → 参考文献 → 附录），再逐章看二三级。
2. 改名优先用语料里该角色的主流写法；领域术语按正文实际用词，不生造；口语 / 比喻 / 工程腔换规范词；
   冒号后的说明、数量词、内部代号、"（第 N 章）"式引用移出标题（这些信息正文里本来就有）。
3. 二级标题总数远超语料 P75 时，优先 merge_up 独子节 / 过薄节，而不是删有内容的节。
4. 每章保留一个"小结"即可；"本质""思路""路线图"类标题归到问题分析 / 技术路线角色。
