"""mm-frame-workbench 冒烟测试：临时目录里造一个最小数模项目并跑完整管线。

项目：paper/sections/ 三个 md（摘要 / 第 1 章 / 问题一章含 H2-H3、公式、图、代码块假标题、交叉引用 / 参考文献）+
paper.yaml 顺序。断言：
  - inventory：跳过代码块里的 #；编号 / 角色 / 计数正确；strict_level 角色不越级
  - lint：命中 term_informal、title_colon、xref_missing，不对代码块报错
  - apply：rename / relevel / merge_up / delete / move / insert 六种 op 全部生效，编号重排、引用同步、
    正文零漂移校验 OK，源文件 sha 不变，公式 / 图 / 标签零丢失
  - plan / report：FRAME_PLAN.md、FRAME_REPORT.md 生成且含前后对照
用法：python scripts/smoke_test.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
sys.path.insert(0, str(SKILLS / "frame-inventory" / "scripts"))
from frame_common import classify_role  # noqa: E402

ABSTRACT = """# 摘要

本文针对某类优化问题建立了模型。

**关键词**：优化；模型
"""

CH1 = """# 1 问题重述

## 1.1 问题背景

背景文字，见 2.3 节 与 第 2 章。

## 1.2 需要解决的问题

- 问题一
- 问题二
"""

CH2 = """# 2 问题一：模型的软肋与抓手

## 2.1 问题分析

分析文字，参见 2.4 节 与 9.9 节。

## 2.2 数据的精修与反推

$$ y = ax + b $$ {#eq:line}

如式 @eq:line 所示。

### 2.2.1 步骤一

正文 A。

```python
# 这不是标题
x = 1
```

### 2.2.2 步骤二

![图 1 示意](figures/fig01/fig01.png){#fig:one}

见 @fig:one。

## 2.3 结果印证

正文 B，含 3.14 与 2.2.1 节 的引用。

## 2.4 废弃的探索

这一节将被整节删除。

## 2.5 问题一小结

正文 C。
"""

REFS = """# 参考文献

[1] 某作者. 某文献. 2020.
"""

YAML = """title: 冒烟测试
sections:
  - 00_abstract.md
  - 01_restatement.md
  - 02_q1.md
  - 99_refs.md
"""


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    skill, name = script.split("/")
    cmd = [sys.executable, str(SKILLS / skill / "scripts" / name), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit(f"FAIL: {' '.join(cmd)} 退出码 {r.returncode}")
    return r


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print(f"  ok  {msg}")


def test_roles() -> None:
    check(classify_role("问题一：模型建立", 1) == "problem_chapter", "H1 问题一 → problem_chapter")
    check(classify_role("问题一的模型建立与求解", 2) == "sub_model", "H2 问题一的模型建立与求解 → sub_model（不是 problem_chapter）")
    check(classify_role("问题一分析", 2) == "sub_analysis", "H2 问题一分析 → sub_analysis")
    check(classify_role("模型假设", 2) == "assumptions", "H2 模型假设 退到一级角色 assumptions")
    check(classify_role("参考文献", 2) is None, "H2 参考文献 不识别（strict_level）")
    check(classify_role("模型的评价与推广", 1) == "evaluation", "评价与推广 → evaluation")
    check(classify_role("随便写的标题", 1) is None, "无角色 → None")


def main() -> None:
    print("[smoke] 角色分类")
    test_roles()
    tmp = Path(tempfile.mkdtemp(prefix="mm_frame_smoke_"))
    try:
        proj = tmp / "proj"
        src = proj / "paper" / "sections"
        src.mkdir(parents=True)
        (src / "00_abstract.md").write_text(ABSTRACT, encoding="utf-8")
        (src / "01_restatement.md").write_text(CH1, encoding="utf-8")
        (src / "02_q1.md").write_text(CH2, encoding="utf-8")
        (src / "99_refs.md").write_text(REFS, encoding="utf-8")
        (proj / "paper" / "paper.yaml").write_text(YAML, encoding="utf-8")
        before = {p.name: sha(p) for p in src.iterdir()}

        print("[smoke] inventory")
        run("frame-inventory/inventory_frame.py", str(proj))
        inv = json.loads((proj / "frame" / "frame_inventory.json").read_text(encoding="utf-8"))
        titles = [h["title"] for h in inv["headings"]]
        check("这不是标题" not in titles, "代码块里的 # 不算标题")
        check(inv["counts"] == {"h1": 4, "h2": 7, "h3": 2}, f"标题计数 {inv['counts']}")
        by_title = {h["title"]: h for h in inv["headings"]}
        check(by_title["问题一：模型的软肋与抓手"]["role"] == "problem_chapter", "问题章角色")
        check(by_title["问题一：模型的软肋与抓手"]["num"] == "2", "编号拆分")
        check(by_title["摘要"]["num_style"] == "none", "摘要无编号")
        check(by_title["问题一小结"]["role"] == "sub_summary", "小结角色")
        q1 = by_title["数据的精修与反推"]
        check(q1["own_body"]["display_eqs"] == 1 and by_title["步骤二"]["own_body"]["figures"] == 1 and q1["subtree"]["code_blocks"] == 1, "正文统计（图 / 公式）")

        print("[smoke] lint")
        run("frame-lint/lint_frame.py", str(proj))
        lint = json.loads((proj / "frame" / "frame_lint.json").read_text(encoding="utf-8"))
        rules = {i["rule"] for i in lint["items"]}
        informal = {i["title"] for i in lint["items"] if i["rule"] == "term_informal"}
        check({"数据的精修与反推", "问题一：模型的软肋与抓手", "结果印证"} <= informal, f"term_informal 命中 {informal}")
        check("title_colon" in rules, "title_colon 命中")
        xref = [i["msg"] for i in lint["items"] if i["rule"] == "xref_missing"]
        check(len(xref) == 1 and "9.9" in xref[0], f"xref_missing 只报 9.9 节：{xref}")
        check("skeleton_missing" in rules, "骨架缺失（无假设 / 评价）")
        md = (proj / "frame" / "FRAME_LINT.md").read_text(encoding="utf-8")
        check("软肋" in md and "薄弱环节" in md, "FRAME_LINT.md 给出规范候选")

        print("[smoke] plan + apply")
        hid = {h["title"]: h["id"] for h in inv["headings"]}
        plan = {
            "src": "paper/sections", "numbering": "auto",
            "ops": [
                {"op": "rename", "id": hid["问题一：模型的软肋与抓手"], "new": "问题一 模型的建立与求解", "why": "去口语与冒号"},
                {"op": "rename", "id": hid["数据的精修与反推"], "new": "模型建立", "why": "角色主流写法"},
                {"op": "merge_up", "id": hid["步骤一"], "why": "只有两步，拉平"},
                {"op": "relevel", "id": hid["步骤二"], "level": 2, "why": "升为二级"},
                {"op": "delete", "id": hid["废弃的探索"], "why": "无结论"},
                {"op": "move", "id": hid["结果印证"], "after": hid["问题一小结"], "why": "测试挪动"},
                {"op": "insert", "after": hid["问题一：模型的软肋与抓手"], "level": 2, "title": "问题描述", "why": "补环节"},
            ],
        }
        (proj / "frame" / "frame_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        run("frame-plan/plan_frame.py", str(proj), "--strict")
        plan_md = (proj / "frame" / "FRAME_PLAN.md").read_text(encoding="utf-8")
        check("前后目录对照" in plan_md and "← 删除" in plan_md and "← 新增" in plan_md, "FRAME_PLAN.md 前后对照")
        check(not (proj / "frame" / "sections").exists(), "plan 阶段不写 frame/sections")

        run("frame-apply/apply_frame.py", str(proj), "--strict")
        app = json.loads((proj / "frame" / "frame_apply.json").read_text(encoding="utf-8"))
        check(app["written"] and not app["problems"] and not app["verify"]["fail"], "apply 写出且校验 OK")
        check({p.name: sha(p) for p in src.iterdir()} == before, "源文件 sha 不变")
        out = (proj / "frame" / "sections" / "02_q1.md").read_text(encoding="utf-8")
        lines = out.splitlines()
        heads, fence = [], False
        for ln in lines:
            fence ^= ln.startswith("```")
            if not fence and ln.startswith("#"):
                heads.append(ln)
        check(heads == [
            "# 2 问题一 模型的建立与求解",
            "## 2.1 问题描述",
            "## 2.2 问题分析",
            "## 2.3 模型建立",
            "## 2.4 步骤二",
            "## 2.5 问题一小结",
            "## 2.6 结果印证",
        ], f"应用后标题序列：{heads}")
        check("废弃的探索" not in out and "这一节将被整节删除" not in out, "整节删除含正文")
        check("正文 A。" in out and "# 这不是标题" in out, "merge_up 保留正文与代码块")
        check("$$ y = ax + b $$ {#eq:line}" in out and "{#fig:one}" in out, "公式 / 图 / 标签保留")
        check("参见 2.4 节" in out and any("2.4 废弃的探索" in x for x in app["verify"]["warn"]),
              "指向被删节的引用不动、但给出人工处理提醒")
        check("含 3.14 与 2.3 节" in out, "引用同步：2.2.1 节（并入 2.2）→ 2.3 节（模型建立）")
        check(any(r["old"].startswith("正文 B") and "2.3 节" in r["new"] for r in app["refs"]), "引用同步留痕")
        check((proj / "frame" / "paper.yaml").exists(), "paper.yaml 复制到 frame/")
        ch1 = (proj / "frame" / "sections" / "01_restatement.md").read_text(encoding="utf-8")
        check("见 2.6 节" in ch1 and "第 2 章" in ch1, "跨文件引用：2.3 结果印证 挪到末尾 → 2.6 节；第 2 章不变")

        print("[smoke] run_frame --apply + report")
        shutil.rmtree(proj / "frame" / "sections")
        run("frame-kickoff/run_frame.py", str(proj), "--apply")
        rep = (proj / "frame" / "FRAME_REPORT.md").read_text(encoding="utf-8")
        check("已应用" in rep and "前后对比" in rep and "标题变更" in rep, "FRAME_REPORT.md")
        check((proj / "frame" / "FRAME_LINT_AFTER.md").exists(), "应用后 lint")
        after = json.loads((proj / "frame" / "frame_lint_after.json").read_text(encoding="utf-8"))
        check(not any(i["rule"] == "term_informal" and "软肋" in i["msg"] for i in after["items"]), "应用后 软肋 不再报")

        print("[smoke] keep 编号 + 越界 op 被拒")
        plan2 = {"src": "paper/sections", "numbering": "keep",
                 "ops": [{"op": "rename", "id": "02_q1.md:999", "new": "x", "why": "bad"},
                         {"op": "relevel", "id": hid["步骤二"], "level": 0, "why": "bad"}]}
        (proj / "frame" / "frame_plan.json").write_text(json.dumps(plan2, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([sys.executable, str(SKILLS / "frame-apply" / "scripts" / "apply_frame.py"), str(proj), "--strict"],
                           capture_output=True, text=True, encoding="utf-8")
        check(r.returncode != 0 and "NOT WRITTEN" in r.stdout, "坏 op → 非零退出且不写出")
        print("[smoke] ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
