# AGENTS.md — mm-frame-workbench

数模论文**框架与目录命名优化**专用下游工作流（`mm-draft-workbench` 出稿 → 本仓库整框架 → `mm-polish-workbench` 打磨正文 →
`mm-figure-workbench` / `mm-layout-workbench`）。输入一个项目目录 `<proj>`（含 `paper/sections/*.md`、`paper/paper.yaml`），
输出全部在 `<proj>/frame/`。入口技能：`.agents/skills/frame-kickoff/SKILL.md`。

本仓库是通用工具，服务于任何一届比赛的任何项目：**不得写入任何具体项目的题目、模型名、变量名、结论或术语。**
项目特有的东西只能出现在项目自己的 `frame/frame_plan.json`（计划）与 `frame/FRAME_TERMS.json`（确认过的领域术语白名单）里。
规范的依据是往届优秀论文语料（`_references/`，脚本生成，不存 PDF）。

## 硬规则（违反即失败）

1. **正文一个字不改**。只动：标题文字、标题层级、章节顺序、整节删除（含其正文）、新增空标题。编号变化引起的
   “第 N 章 / N.N 节 / §N.N / 见 N.N”交叉引用由工具同步改数字并逐条留痕（`frame_apply.json.refs`）；其它任何正文改动
   （改句子、补内容、改公式 / 数字 / 图表 / 题注 / 标签、为配合新标题重写导语）一律禁止 —— `verify_drift` 会拦。
2. **先计划后应用**。默认只出 `FRAME_LINT.md` + `FRAME_PLAN.md` 给人审；`frame_plan.json` 的每条 op 必须有 `why`。
   拿到用户明确确认后才 `run_frame.py --apply`。绝不直接改 `paper/`、`paper/main.docx`。
3. **术语优先于硬指标**。lint 与计划以“标题是否用了数模论文 / 领域的规范术语、语义角色是否清楚”为核心；
   长度、冒号、数量等只是辅助证据。每条改名建议要给证据（语料频次 / 角色主流写法 / term_map 候选 / 正文用法），
   术语库外的词只报 INFO 让人确认，**不得**把“不认识”当作“不专业”。
4. **删节要有依据**。只删无结论、与正文重复、纯过程性或明显跑题的节；删节前检查 `frame_apply.json.verify`：
   被删节里定义的标签若仍被引用 → FAIL；正文里“见 N.N 节”指向被删节 → 提醒，需用户决定不删或回 polish 改句子。
5. **只写** `<proj>/frame/`：`frame_inventory.json`、`FRAME_LINT.md` / `frame_lint.json`、`frame_plan.json`、
   `FRAME_PLAN.md`、`sections/`、`paper.yaml`、`frame_apply.json`、`after_inventory.json`、`FRAME_LINT_AFTER.md`、
   `FRAME_REPORT.md`。`paper/`、`polish/`、`data/`、`code/`、`results/`、`figures/`、`layout/` 只读。
6. **通用性**。不假设问题数量、章节文件名、模型名；问题章靠一级标题 `问题 N` 识别；角色靠 `_references/heading_roles.json`；
   口语 → 规范词候选靠 `_references/term_map.json`（跨领域通用词，加词前先确认它不是某个项目的私货）。
7. 代码：Python 3.10+ 标准库，`pathlib`，读写显式 `encoding="utf-8"`，`setup_stdout()` 处理控制台编码，不写绝对路径，
   不调 bash，子进程用列表形式。`frame-corpus` 例外依赖 `pymupdf`，仅维护语料时运行。
8. 不提交比赛数据、论文 PDF、项目稿件、凭据到仓库。

## 管线

```text
frame-kickoff/scripts/run_frame.py <proj> [--apply] [--strict]
  → frame-inventory/scripts/inventory_frame.py   标题树 + 编号 + 角色 + 术语切分 + 正文统计 → frame/frame_inventory.json
  → frame-lint/scripts/lint_frame.py             框架 / 节 / 标题三层 lint（术语为核心）→ frame/FRAME_LINT.md
  → （人 / Agent 依据 LINT 手写 frame/frame_plan.json）
  → frame-plan/scripts/plan_frame.py             dry-run 校验 + 前后目录对照 → frame/FRAME_PLAN.md（交用户确认）
  → frame-apply/scripts/apply_frame.py           --apply 时：应用 op、重排编号、同步引用、零漂移校验 → frame/sections/
  → inventory + lint 再跑一遍 frame/sections     → after_inventory.json / FRAME_LINT_AFTER.md
  → frame-report/scripts/report_frame.py         → frame/FRAME_REPORT.md
```

语料更新：`python .agents/skills/frame-corpus/scripts/build_corpus.py <pdf 目录> --year 23`（可 `--append` 分批喂不同年份）。

## 改代码后必须跑

```bash
python -m compileall -q .agents/skills scripts
python scripts/smoke_test.py      # 临时最小项目：角色分类 + 六种 op + 编号 / 引用同步 + 零漂移 + 坏 op 拒绝
```

有真实项目时 `run_frame.py <proj>`（不带 --apply）看 `FRAME_LINT.md` 没有新增误报。
