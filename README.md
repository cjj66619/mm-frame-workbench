# mm-frame-workbench

数模论文**框架与目录命名**优化工作台：输入 `mm-draft-workbench` 产出的 `paper/sections/*.md`，
依据往届优秀论文语料给标题树做术语 / 角色 / 结构 lint，出计划交人确认，再只改标题文字、层级、顺序（允许整节删除），
正文零漂移，输出到 `<proj>/frame/`。

```text
mm-draft-workbench → mm-frame-workbench → mm-polish-workbench → mm-figure-workbench → mm-layout-workbench
```

## 用法

```bash
# 1. 只读：盘点 + lint
python .agents/skills/frame-kickoff/scripts/run_frame.py <proj>
#    → frame/frame_inventory.json, frame/FRAME_LINT.md

# 2. 手写 frame/frame_plan.json（见 .agents/skills/frame-plan/SKILL.md），再跑一次得到 frame/FRAME_PLAN.md 给人确认
python .agents/skills/frame-kickoff/scripts/run_frame.py <proj>

# 3. 确认后应用
python .agents/skills/frame-kickoff/scripts/run_frame.py <proj> --apply --strict
#    → frame/sections/, frame/paper.yaml, frame/frame_apply.json, frame/FRAME_LINT_AFTER.md, frame/FRAME_REPORT.md
```

## 原则

- 正文一个字不改；唯一的正文操作是整节删除与编号引用同步（逐条留痕、多重集校验）。
- 术语优先：lint 的核心是标题是否用了数模论文 / 领域规范术语、语义角色是否清楚；长度 / 冒号等硬指标只是辅助。
- 语料驱动：阈值、角色主流写法、问题章句式全部来自 `_references/FRAME_NORMS.json`（`frame-corpus` 生成）。
- 通用：仓库不含任何具体项目的题目 / 模型 / 术语；项目确认的领域术语放项目的 `frame/FRAME_TERMS.json`。

## 目录

```text
.agents/skills/
  frame-kickoff/    run_frame.py           一键入口
  frame-inventory/  inventory_frame.py     标题树盘点；frame_common.py 共用解析
  frame-lint/       lint_frame.py          三层 lint
  frame-plan/       plan_frame.py          计划 dry-run + FRAME_PLAN.md
  frame-apply/      apply_frame.py         应用 + 编号 + 引用同步 + 零漂移校验
  frame-report/     report_frame.py        FRAME_REPORT.md
  frame-corpus/     build_corpus.py        语料统计（需 pymupdf）
  _references/      FRAME_NORMS.json/.md heading_roles.json term_map.json term_bank.json outline_corpus.json
scripts/smoke_test.py                       冒烟测试
```

## 自检

```bash
python -m compileall -q .agents/skills scripts
python scripts/smoke_test.py
```
