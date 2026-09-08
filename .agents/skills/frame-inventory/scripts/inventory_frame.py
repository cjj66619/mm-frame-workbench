"""inventory_frame.py — 盘点论文 Markdown 章节的标题树，输出 frame/frame_inventory.json（确定性、可 diff）。

用法：
    python inventory_frame.py <proj> [--src paper/sections] [--out frame/frame_inventory.json]

每个标题一条记录：id（file:行号）、level、编号风格与编号、去编号标题、角色（heading_roles.json）、长度、
标点、术语切分（term_bank.json）、正文统计（到下一同级或更高级标题之前的汉字数 / 图 / 表 / 公式 / 代码块）、
子标题数。另给全稿汇总：各级数量、编号风格、一级章角色序列、章节文件顺序（paper.yaml 优先）。
只读 <src>，只写 --out。
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frame_common import (TermBank, body_stats, classify_role, dump_json, iter_headings, load_json,  # noqa: E402
                          punct_kinds, section_order, setup_stdout, zh_len)


def load_project_terms(proj: Path) -> list[str]:
    """<proj>/frame/FRAME_TERMS.json 的 domain_terms：项目确认过的领域术语（随项目走，不进工作台）。"""
    p = proj / "frame" / "FRAME_TERMS.json"
    if not p.exists():
        return []
    return [t for t in load_json(p).get("domain_terms", []) if isinstance(t, str) and t]


ZH_RUN = re.compile(r"[\u4e00-\u9fff]+")


def title_only_runs(title: str, unknown: list[str], body: str, min_tf: int = 3) -> list[str]:
    """术语库外的串里，正文里也找不到依托的部分。

    切分是最长匹配，未识别串常是切坏的碎片（如「对照表」被虚词「对」切成「照表」），所以不直接数碎片本身，
    而是在它所在的整段汉字里找：每个字若能被某个 ≥2 字、正文出现 ≥ min_tf 次的窗口覆盖就算有依托；
    连续 ≥2 个无依托的字才报出来。"""
    out: list[str] = []
    for run in ZH_RUN.findall(title):
        covered = [False] * len(run)
        for a in range(len(run)):
            for b in range(len(run), a + 1, -1):
                if body.count(run[a:b]) >= min_tf:
                    for k in range(a, b):
                        covered[k] = True
                    break
        for u in unknown:
            i = run.find(u)
            if i < 0:
                continue
            j, cur = i, ""
            for k in range(i, i + len(u)):
                if not covered[k]:
                    cur += run[k]
                else:
                    if len(cur) >= 2:
                        out.append(cur)
                    cur = ""
            if len(cur) >= 2:
                out.append(cur)
    return out


def build_inventory(proj: Path, src: Path) -> dict:
    bank = TermBank.load()
    for t in load_project_terms(proj):
        bank.terms.setdefault(t, {"df": 0, "tf": 0, "kind": "project", "in_heading": 0})
    bank.max_len = max((len(t) for t in bank.terms), default=8)
    files = section_order(src)
    records: list[dict] = []
    per_file: list[dict] = []
    body_all = "\n".join(ln for f in files for ln in f.read_text(encoding="utf-8").splitlines()
                         if not ln.lstrip().startswith("#"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        lines = text.splitlines()
        heads = iter_headings(text, f.name)
        per_file.append({"file": f.name, "headings": len(heads), "lines": len(lines),
                         "zh_chars": body_stats(lines, 0, len(lines))["zh_chars"]})
        for i, h in enumerate(heads):
            # 该节正文范围：到下一个 level ≤ 本级的标题
            end = len(lines)
            for h2 in heads[i + 1:]:
                if h2.level <= h.level:
                    end = h2.line
                    break
            own_end = heads[i + 1].line if i + 1 < len(heads) else len(lines)
            children = sum(1 for h2 in heads[i + 1:] if h2.line < end and h2.level == h.level + 1)
            seg = bank.segment(h.title)
            unknown = [t for t, k in seg if k == "unknown" and len(t) >= 2]
            records.append({
                "id": h.id, "file": h.file, "line": h.line + 1, "level": h.level,
                "num_style": h.numbering.style, "num": h.numbering.raw, "raw": h.raw, "title": h.title,
                "role": classify_role(h.title, h.level), "len": zh_len(h.title), "punct": punct_kinds(h.title),
                "terms": [t for t, k in seg if k == "term"], "ascii": [t for t, k in seg if k == "ascii"],
                "unknown": unknown,
                "unknown_body_tf": {t: body_all.count(t) for t in unknown},   # 该串在全篇正文出现次数（领域术语的证据）
                "title_only": title_only_runs(h.title, unknown, body_all),      # 正文里找不到依托的部分（疑似自造 / 临时说法）
                "children": children,
                "own_body": body_stats(lines, h.line + 1, own_end),      # 本标题直辖正文（不含子节）
                "subtree": body_stats(lines, h.line + 1, end),           # 含全部子节
            })
    lvl = Counter(r["level"] for r in records)
    styles = Counter((r["level"], r["num_style"]) for r in records)
    return {
        "src": str(src.relative_to(proj)) if src.is_relative_to(proj) else str(src),
        "files": per_file,
        "counts": {f"h{k}": v for k, v in sorted(lvl.items())},
        "num_styles": [{"level": k[0], "style": k[1], "n": v} for k, v in sorted(styles.items())],
        "h1_sequence": [{"id": r["id"], "title": r["title"], "role": r["role"]} for r in records if r["level"] == 1],
        "headings": records,
    }


def main() -> None:
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proj", type=Path)
    ap.add_argument("--src", default="paper/sections")
    ap.add_argument("--out", default="frame/frame_inventory.json")
    a = ap.parse_args()
    proj = a.proj.resolve()
    src = (proj / a.src).resolve()
    if not src.is_dir():
        sys.exit(f"章节目录不存在：{src}")
    inv = build_inventory(proj, src)
    dump_json(proj / a.out, inv)
    c = inv["counts"]
    print(f"[inventory] {len(inv['files'])} 个文件，标题 H1 {c.get('h1', 0)} / H2 {c.get('h2', 0)} / H3 {c.get('h3', 0)}"
          f" → {a.out}")


if __name__ == "__main__":
    main()
