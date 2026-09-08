"""plan_frame.py — 把 frame/frame_plan.json 渲染成可审阅的 frame/FRAME_PLAN.md（含前后目录对照），并做 dry-run 校验。

用法：
    python plan_frame.py <proj> [--plan frame/frame_plan.json] [--out frame/FRAME_PLAN.md] [--strict]

FRAME_PLAN.md 内容：
  1. 总览：op 数、删节数与被删正文行数、编号变更数、引用同步数、dry-run 问题
  2. 变更清单：每条 op 的 before / after / why（why 必填，空的会标出来）
  3. 前后目录对照：旧目录（带旧编号）→ 新目录（带新编号），改动处用 ← 标记
  4. 未处理的 lint WARN：frame_lint.json 里 WARN 级、但没有任何 op 触及的标题（说明为什么保留，或补 op）

只读原稿，不写 frame/sections/。--strict：dry-run 有问题时退出码 1。
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "frame-inventory" / "scripts"))
sys.path.insert(0, str(HERE.parents[2] / "frame-apply" / "scripts"))
from apply_frame import apply_plan  # noqa: E402
from frame_common import load_json, setup_stdout  # noqa: E402

OP_LABEL = {"rename": "改名", "relevel": "改层级", "merge_up": "并入上节", "delete": "删除", "move": "挪动", "insert": "新增标题"}


def render(proj: Path, plan: dict, res: dict, inv: dict, lint: dict | None) -> str:
    heads = {h["id"]: h for h in inv["headings"]}
    touched: dict[str, list[dict]] = defaultdict(list)
    for op in res["applied"]:
        if op.get("id"):
            touched[op["id"]].append(op)
    out = ["# FRAME_PLAN — 框架与标题优化计划（待确认）", "",
           f"源：`{plan.get('src', 'paper/sections')}`；编号：{plan.get('numbering', 'auto')}。"
           "本计划只改标题文字 / 层级 / 顺序，唯一的正文改动是整节删除与编号引用同步；正文一个字不动。", "",
           "## 总览", "",
           f"- 操作 {res['plan_ops']} 条：" + "、".join(
               f"{OP_LABEL.get(k, k)} {n}" for k, n in _count_ops(res["applied"]).items()),
           f"- 删除节 {len(res['deleted'])} 个，涉及正文 {sum(d['lines'] for d in res['deleted'])} 行"
           f"（图 {res['verify']['figures_removed']}、行间公式 {res['verify']['display_eqs_removed']}）",
           f"- 编号变更 {len(res['numbering'])} 处，正文引用同步 {len(res['refs'])} 处",
           f"- dry-run：{'OK' if not res['problems'] and not res['verify']['fail'] else 'FAIL'}"]
    for p in res["problems"] + res["verify"]["fail"]:
        out.append(f"  - ! {p}")
    if res["verify"].get("warn"):
        out.append(f"- 需人工处理的提醒 {len(res['verify']['warn'])} 条（工具不改正文）：")
        for w in res["verify"]["warn"]:
            out.append(f"  - ~ {w}")
    notes = plan.get("notes", [])
    if notes:
        out += ["", "## 计划说明", ""] + [f"- {n}" for n in notes]
    out += ["", "## 变更清单", "", "| # | 操作 | 位置 | 之前 | 之后 | 理由 |", "| ---: | --- | --- | --- | --- | --- |"]
    for k, op in enumerate(plan.get("ops", []), 1):
        kind = op.get("op", "?")
        hid = op.get("id") or op.get("after") or op.get("before") or ""
        h = heads.get(hid)
        before = f"{h['num']} {h['title']}".strip() if h else hid
        if kind == "rename":
            after = op.get("new", "")
        elif kind == "relevel":
            after = f"H{op.get('level')}"
        elif kind == "merge_up":
            after = "（标题删除，正文并入上一节）"
        elif kind == "delete":
            after = "（整节删除）"
        elif kind == "move":
            tgt = heads.get(op.get("after") or op.get("before") or "")
            after = f"挪到「{tgt['title']}」{'之后' if op.get('after') else '之前'}" if tgt else "?"
        elif kind == "insert":
            after = f"H{op.get('level', '?')} {op.get('title', '')}（新标题，无正文）"
            before = f"在「{h['title']}」之后" if h else hid
        else:
            after = ""
        why = op.get("why", "").strip() or "**（缺理由）**"
        out.append(f"| {k} | {OP_LABEL.get(kind, kind)} | `{hid}` | {before} | {after} | {why} |")

    out += ["", "## 前后目录对照", "", "左：原稿；右：应用后（编号已重排）。`←` 标记该行有改动；被删的节只在左侧出现并加删除线。", ""]
    after_by_id = {o["id"]: o for o in res["outline_after"]}
    deleted_ids = {d["id"] for d in res["deleted"]}
    merged_ids = {op["id"] for op in res["applied"] if op["op"] == "merge_up"}
    out += ["| 原稿 | 应用后 |", "| --- | --- |"]
    # 按新目录顺序输出；被删 / 并入的节插在原相邻位置
    old_order = [h["id"] for h in inv["headings"]]
    emitted: set[str] = set()
    new_seq = [o["id"] for o in res["outline_after"]]
    pos_in_old = {hid: i for i, hid in enumerate(old_order)}

    def old_cell(hid: str) -> str:
        h = heads.get(hid)
        if not h:
            return ""
        return "&nbsp;&nbsp;" * (h["level"] - 1) + f"{h['num']} {h['title']}".strip()

    def new_cell(o: dict) -> str:
        return "&nbsp;&nbsp;" * (o["level"] - 1) + f"{o['num']} {o['title']}".strip()

    for nid in new_seq:
        # 先把原稿里排在它之前、但已消失（删除 / 并入）的节吐出来
        if nid in pos_in_old:
            for hid in old_order:
                if hid in emitted or pos_in_old[hid] >= pos_in_old[nid]:
                    continue
                if hid in deleted_ids:
                    out.append(f"| ~~{old_cell(hid)}~~ | ← 删除 |")
                    emitted.add(hid)
                elif hid in merged_ids:
                    out.append(f"| ~~{old_cell(hid)}~~ | ← 并入上节 |")
                    emitted.add(hid)
        o = after_by_id[nid]
        if nid not in pos_in_old:
            out.append(f"| | {new_cell(o)} ← 新增 |")
            continue
        h = heads[nid]
        changed = h["title"] != o["title"] or h["level"] != o["level"] or (h["num"] or "") != (o["num"] or "")
        mark = ""
        if h["title"] != o["title"]:
            mark = " ← 改名"
        elif h["level"] != o["level"]:
            mark = " ← 改层级"
        elif any(op["op"] == "move" for op in touched.get(nid, [])):
            mark = " ← 挪动"
        elif changed:
            mark = " ← 重编号"
        out.append(f"| {old_cell(nid)} | {new_cell(o)}{mark} |")
        emitted.add(nid)
    for hid in old_order:
        if hid not in emitted and (hid in deleted_ids or hid in merged_ids):
            out.append(f"| ~~{old_cell(hid)}~~ | ← {'删除' if hid in deleted_ids else '并入上节'} |")

    if lint:
        keep = plan.get("keep", [])
        kept_ids = {k.get("id") for k in keep}
        warn_left = [i for i in lint["items"] if i["sev"] in ("WARN", "FAIL") and i.get("id")
                     and i["id"] not in touched and i["id"] not in deleted_ids and i["id"] not in merged_ids
                     and i["id"] not in kept_ids and i["rule"] not in ("sibling_mixed",)]
        out += ["", f"## 未处理的 lint WARN（{len(warn_left)} 条）", "",
                "没有任何操作触及的 WARN 级标题。保留的请在下方说明理由；否则补 op。", ""]
        by_head: dict[str, list[dict]] = defaultdict(list)
        for i in warn_left:
            by_head[i["id"]].append(i)
        for hid, items in by_head.items():
            h = heads.get(hid, {})
            out.append(f"- `{hid}` **{h.get('num', '')} {h.get('title', '')}**".replace("** ", "**"))
            for i in items:
                out.append(f"  - {i['sev']} `{i['rule']}` {i['msg']}")
        if keep:
            out += ["", "### 计划声明保留（`plan.keep`）", ""]
            for k in keep:
                h = heads.get(k.get("id", ""), {})
                out.append(f"- `{k.get('id')}` {h.get('title', '')}：{k.get('why', '')}")
    out.append("")
    return "\n".join(out)


def _count_ops(applied: list[dict]) -> dict[str, int]:
    c: dict[str, int] = {}
    for op in applied:
        c[op["op"]] = c.get(op["op"], 0) + 1
    return c


def main() -> None:
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proj", type=Path)
    ap.add_argument("--plan", default="frame/frame_plan.json")
    ap.add_argument("--inventory", default="frame/frame_inventory.json")
    ap.add_argument("--out", default="frame/FRAME_PLAN.md")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    proj = a.proj.resolve()
    plan = load_json(proj / a.plan)
    inv = load_json(proj / a.inventory)
    lint_p = proj / "frame" / "frame_lint.json"
    lint = load_json(lint_p) if lint_p.exists() else None
    src = (proj / plan.get("src", inv.get("src", "paper/sections"))).resolve()
    res = apply_plan(proj, plan, src, proj / "frame" / "sections", dry_run=True)
    (proj / a.out).write_text(render(proj, plan, res, inv, lint), encoding="utf-8")
    bad = res["problems"] + res["verify"]["fail"]
    print(f"[plan] ops {res['plan_ops']} 删节 {len(res['deleted'])} 编号变更 {len(res['numbering'])} "
          f"引用同步 {len(res['refs'])} dry-run {'OK' if not bad else 'FAIL'} → {a.out}")
    for p in bad:
        print(f"  ! {p}")
    if a.strict and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
