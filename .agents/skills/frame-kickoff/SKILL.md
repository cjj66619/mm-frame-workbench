---
name: frame-kickoff
description: 论文框架与目录命名优化工作流入口。给定 draft 产出的数模项目目录，盘点标题树、按优秀论文语料 lint 术语与结构、写计划给用户确认，确认后应用到 frame/sections 并校验正文零漂移。
---

# frame-kickoff

## 何时用

用户说"目录不专业 / 标题太口语 / 章节起名天马行空 / 框架不像数模论文"，且项目是 `mm-draft-workbench` 产出的
`paper/sections/*.md` + `paper/paper.yaml` 结构。**只动框架与标题，不改正文**（唯一例外：整节删除）。

## 流程

1. **盘点 + lint（只读）**：`python .agents/skills/frame-kickoff/scripts/run_frame.py <proj>`
   → `frame/frame_inventory.json`、`frame/FRAME_LINT.md`。先通读 LINT 的"术语与角色"部分，再看结构与硬指标。
2. **写计划**：按 `frame-plan/SKILL.md` 手写 `frame/frame_plan.json`（每条 op 带 `why` 与证据），再跑一次
   `run_frame.py <proj>` 生成 `frame/FRAME_PLAN.md`（含前后目录对照、未处理 WARN、需人工处理的提醒）。
   若某些"不认识"的词其实是领域规范术语，写进 `frame/FRAME_TERMS.json` 的 `domain_terms` 后重跑，INFO 就消失。
3. **交用户确认**：把 `FRAME_PLAN.md` 给用户看；根据反馈改 `frame_plan.json`，直到确认。不要在确认前 `--apply`。
4. **应用**：`run_frame.py <proj> --apply --strict` → `frame/sections/`、`frame/paper.yaml`、`frame_apply.json`、
   `FRAME_LINT_AFTER.md`、`FRAME_REPORT.md`。apply 有问题或校验 FAIL 时不写出，看输出的 `!` 行修计划。
5. **交付**：报告里"需人工处理"的提醒（引用了被删节）要告知用户；下游 polish / layout 以 `frame/sections` 为输入，
   Word 由 draft 的构建脚本以它为源重新生成，本工作流不碰 `paper/main.docx`。

## 参数

| 参数 | 作用 |
| --- | --- |
| `--src paper/sections` | 源目录（相对 proj） |
| `--apply` | 有 `frame/frame_plan.json` 时应用并写 `frame/sections/` |
| `--strict` | lint 有 FAIL / plan dry-run 有问题时非零退出 |

## 产物

`frame/frame_inventory.json`、`FRAME_LINT.md`、`frame_lint.json`、`frame_plan.json`（手写）、`FRAME_PLAN.md`、
`sections/`、`paper.yaml`、`frame_apply.json`、`after_inventory.json`、`FRAME_LINT_AFTER.md`、`frame_lint_after.json`、`FRAME_REPORT.md`。
