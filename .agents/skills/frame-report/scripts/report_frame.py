"""report_frame.py — 汇总 apply 前后的盘点 / lint 与校验结果，写 frame/FRAME_REPORT.md。

用法：
    python report_frame.py <proj>

读取：frame/frame_inventory.json（前）、frame/frame_lint.json（前）、frame/after_inventory.json（后）、
      frame/frame_lint_after.json（后）、frame/frame_apply.json。缺“后”文件时只写“前”的状态与待办。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frame-inventory" / "scripts"))
from frame_common import load_json, setup_stdout  # noqa: E402


def sev_counts(lint: dict | None) -> Counter:
    return Counter(i["sev"] for i in lint["items"]) if lint else Counter()


def rule_counts(lint: dict | None, sev: str) -> Counter:
    return Counter(i["rule"] for i in lint["items"] if i["sev"] == sev) if lint else Counter()


def main() -> None:
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proj", type=Path)
    a = ap.parse_args()
    fr = a.proj.resolve() / "frame"

    def opt(name: str) -> dict | None:
        p = fr / name
        return load_json(p) if p.exists() else None

    inv0, lint0 = opt("frame_inventory.json"), opt("frame_lint.json")
    inv1, lint1 = opt("after_inventory.json"), opt("frame_lint_after.json")
    app = opt("frame_apply.json")
    if inv0 is None:
        sys.exit("缺 frame/frame_inventory.json，先跑 inventory")

    out = ["# FRAME_REPORT — 框架优化报告", ""]
    status = "未应用（只有盘点与 lint）"
    if app:
        status = "已应用，写出 frame/sections/" if app.get("written") else "apply 未写出（有问题或校验失败）"
    out += [f"**状态：{status}**", ""]

    out += ["## 前后对比", "", "| 指标 | 之前 | 之后 |", "| --- | ---: | ---: |"]
    c0, c1 = inv0["counts"], (inv1 or {}).get("counts", {})
    for k in ("h1", "h2", "h3"):
        out.append(f"| {k.upper()} 数 | {c0.get(k, 0)} | {c1.get(k, '—')} |")
    s0, s1 = sev_counts(lint0), sev_counts(lint1)
    for sev in ("FAIL", "WARN", "INFO"):
        out.append(f"| lint {sev} | {s0.get(sev, 0)} | {s1.get(sev, '—') if lint1 else '—'} |")
    if lint0:
        out += ["", "### WARN 按规则", "", "| 规则 | 之前 | 之后 |", "| --- | ---: | ---: |"]
        r0, r1 = rule_counts(lint0, "WARN"), rule_counts(lint1, "WARN")
        for rule in sorted(set(r0) | set(r1), key=lambda r: -(r0.get(r, 0))):
            out.append(f"| `{rule}` | {r0.get(rule, 0)} | {r1.get(rule, 0) if lint1 else '—'} |")

    if app:
        v = app["verify"]
        out += ["", "## 应用与校验", "",
                f"- 操作 {app['plan_ops']} 条，应用 {len(app['applied'])} 条，问题 {len(app['problems'])} 条",
                f"- 删除节 {len(app['deleted'])} 个（正文 {sum(d['lines'] for d in app['deleted'])} 行，图 {v['figures_removed']}，"
                f"行间公式 {v['display_eqs_removed']}）",
                f"- 编号变更 {len(app['numbering'])} 处；正文引用同步 {len(app['refs'])} 处",
                f"- 正文零漂移校验：{'OK' if not v['fail'] else 'FAIL — ' + '; '.join(v['fail'])}",
                f"- 被删标签：{', '.join(v['labels_removed']) or '无'}；悬空引用：{', '.join(v['dangling_refs']) or '无'}"]
        for p in app["problems"]:
            out.append(f"  - ! {p}")
        for w in v.get("warn", []):
            out.append(f"  - ~ 需人工处理：{w}")
        if app["deleted"]:
            out += ["", "### 删除的节", ""]
            for d in app["deleted"]:
                out.append(f"- `{d['id']}` H{d['level']} {d['title']}（{d['lines']} 行）")
        if app["refs"]:
            out += ["", "### 引用同步", ""]
            for r in app["refs"]:
                out.append(f"- `{r['file']}:{r['line']}`：{_short(r['old'])} → {_short(r['new'])}")
        renames = [o for o in app["applied"] if o["op"] == "rename"]
        if renames:
            out += ["", "### 标题变更", "", "| 位置 | 之前 | 之后 |", "| --- | --- | --- |"]
            for o in renames:
                out.append(f"| `{o['id']}` | {o['old']} | {o['new']} |")

    if lint1:
        left = [i for i in lint1["items"] if i["sev"] in ("FAIL", "WARN")]
        out += ["", f"## 应用后仍存在的 WARN / FAIL（{len(left)} 条）", ""]
        for i in left[:80]:
            loc = f"`{i['id']}` " if i.get("id") else ""
            out.append(f"- {i['sev']} `{i['rule']}` {loc}{i.get('title', '')}：{i['msg']}")
        if len(left) > 80:
            out.append(f"- …另 {len(left) - 80} 条见 frame/FRAME_LINT_AFTER.md")

    out += ["", "## 下游", "",
            "- `frame/sections/*.md` + `frame/paper.yaml` 是本阶段输出；polish / layout 阶段以它为输入。",
            "- 原稿 `paper/sections/` 未改动；`paper/main.docx` 需由 draft 的构建脚本以 frame/sections 为源重新生成。", ""]
    (fr / "FRAME_REPORT.md").write_text("\n".join(out), encoding="utf-8")
    print(f"[report] {status} → frame/FRAME_REPORT.md")


def _short(s: str, n: int = 60) -> str:
    return s if len(s) <= n else s[:n] + "…"


if __name__ == "__main__":
    main()
