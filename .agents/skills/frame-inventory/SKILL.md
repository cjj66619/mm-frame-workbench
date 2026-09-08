---
name: frame-inventory
description: 盘点 paper/sections/*.md 的标题树：编号风格、层级、语义角色（问题重述 / 模型假设 / 问题章 / 模型建立…）、术语切分、标点、正文统计，输出 frame/frame_inventory.json。
---

# frame-inventory

```bash
python .agents/skills/frame-inventory/scripts/inventory_frame.py <proj> [--src paper/sections] [--out frame/frame_inventory.json]
```

- 文件顺序取 `paper/paper.yaml` 的 `sections`，缺省按文件名排序。
- 只认 Markdown ATX 标题（`#`–`######`），代码块里的 `#` 不算。
- 每个标题：`id`（`文件:行号`，1 基，apply 计划用它定位）、`num` / `num_style`（arabic / cn / appendix / none）、
  `title`（去编号）、`role`（见 `_references/heading_roles.json`；`strict_level` 角色只在规定层级生效）、
  `terms` / `ascii` / `unknown`（按 `_references/term_bank.json` 切分，`unknown` 是术语库外的连续汉字，仅供人工确认）、
  `punct`、`own_body` / `subtree`（汉字数、图、表、行间公式、代码块、行数）。
- 项目确认过的领域术语写在 `<proj>/frame/FRAME_TERMS.json`：`{"domain_terms": ["…"]}`，盘点时并入术语库
  （随项目走，不进本仓库）。

`frame_common.py` 是各技能共用的解析模块（编号拆分、角色分类、术语切分、正文统计），改它后必跑 smoke test。
