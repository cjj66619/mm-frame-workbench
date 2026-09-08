---
name: frame-lint
description: 依据优秀论文语料对标题树做三层 lint：框架（骨架 / 标题数量 / 问题章环节 / 编号 / 交叉引用）、节（过薄 / 独子 / 兄弟句式）、标题（术语口语化、角色非主流写法、冒号 / 数量词 / 代号 / 疑问句 / 过长）。术语为核心，硬指标为辅。
---

# frame-lint

```bash
python .agents/skills/frame-lint/scripts/lint_frame.py <proj> [--inventory frame/frame_inventory.json] [--out frame/FRAME_LINT.md] [--strict]
```

规则清单与阈值出处见脚本 docstring；阈值只来自 `_references/FRAME_NORMS.json`（`build_corpus.py` 生成，勿手改）。

## 读 LINT 的顺序

1. **术语与角色**（`term_informal`、`term_title_only`、`role_variant`、`problem_title_form`、`title_question`）：这是本工作流的重点。
   每条都带证据：term_map 的规范候选与说明、语料里该角色的主流写法与频次。候选是"可选项"不是"替换表"，
   要结合正文语境挑；`note` 里标了"××语境除外"的要先看正文。
   `term_title_only`：标题里的词术语库不认识、**全篇正文也几乎不用**（inventory 的 `unknown_body_tf` / `title_only`）——
   多半是写标题时临时造的说法，改成正文里实际使用的术语。
2. **结构**（`skeleton_missing`、`skeleton_order`、`problem_chain`、`h2_overload`、`thin_section`、`lonely_child`、`xref_missing`）。
3. **硬指标**（`title_long`、`title_colon`、`title_numeral`、`title_code_id`…）：语料占比很低的写法，作为改名时的顺手项。
4. **INFO `term_unrecognized`**：术语库外、但正文常用（≥3 次）的连续汉字，多为领域术语。确认后写进项目的
   `frame/FRAME_TERMS.json` 即可消音；**不要**把"不认识"当"不专业"。

## 加规则

先在语料上验证该模式在优秀论文中确实少见（`FRAME_NORMS.md` 有数据），再加进 `lint_frame.py`，并在 smoke test 里加断言。
加 `term_map.json` 词条前确认它是跨领域的口语 / 比喻 / 商业 / 网络 / 工程腔用词，而不是某个项目的私有词汇。
