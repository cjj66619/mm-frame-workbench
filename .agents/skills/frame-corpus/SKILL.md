---
name: frame-corpus
description: 从往届优秀论文 PDF 抽大纲与正文术语，生成 _references/ 下的语料统计（FRAME_NORMS）、角色变体、术语库；仅维护规范时运行，仓库不存 PDF。
---

# frame-corpus

```bash
pip install pymupdf
python .agents/skills/frame-corpus/scripts/build_corpus.py <pdf 目录…> --year 23 [--append] [--min-df 3]
```

- 大纲来源优先 PDF 书签，其次目录页解析，再退到正文标题行启发式；论文只以匿名 id（`F23-01`）出现。
- 产物：`outline_corpus.json`（每篇大纲）、`FRAME_NORMS.json` / `.md`（长度 / 标点 / 数量分位数、一级章骨架、
  问题章句式、问题章二级环节、各角色写法频次）、`term_bank.json`（正文与标题里的汉字术语及 df / tf）。
- 角色词典 `heading_roles.json` 与口语映射 `term_map.json` 是手工维护的通用文件，不由脚本生成。
- 新增一届语料用 `--append`，然后跑 smoke test 看阈值变化是否引起误报。
