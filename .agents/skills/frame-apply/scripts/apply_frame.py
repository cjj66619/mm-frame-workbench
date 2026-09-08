"""apply_frame.py — 按 frame/frame_plan.json 改标题 / 层级 / 顺序 / 整节删除，写出 frame/sections/，并校验正文零漂移。

用法：
    python apply_frame.py <proj> [--plan frame/frame_plan.json] [--src paper/sections] [--out frame/sections]
                          [--dry-run] [--strict]

frame_plan.json 格式（id = 盘点里的 "文件名:行号"，指向原稿标题）：
{
  "src": "paper/sections",
  "ops": [
    {"op": "rename",   "id": "04_x.md:77", "new": "目标域转频估计", "why": "…"},
    {"op": "relevel",  "id": "04_x.md:112", "level": 2, "why": "…"},
    {"op": "merge_up", "id": "04_x.md:112", "why": "…"},                 # 删标题、正文并入上一节，一个字不动
    {"op": "delete",   "id": "08_x.md:162", "why": "…"},                 # 删标题 + 整段正文（含子节）
    {"op": "move",     "id": "06_x.md:66",  "after": "06_x.md:48", "why": "…"},   # 同文件内把整节挪到某节之后
    {"op": "move",     "id": "06_x.md:66",  "before": "06_x.md:48"},
    {"op": "insert",   "after": "04_x.md:1", "level": 2, "title": "问题分析", "why": "…"}   # 只加空标题，不写正文
  ],
  "numbering": "auto"        # auto：按原稿风格重排编号；keep：不动编号
}

规则：
- 正文行一个字节不改；唯一的正文改动是 delete 的整段与编号同步（“第 4 章”“4.4 节”“§4.4” 这类交叉引用），
  每处替换写进 frame/frame_apply.json 的 refs。
- 先在内存里做完所有 op，再统一重编号：阿拉伯编号按原稿层级样式（"4 标题" / "4.1 标题"）；无编号的一级章
  （摘要 / 参考文献）保持无编号；附录按 "附录 A" + "A1" 的原样式重排。
- 校验：非标题行多重集 old == new ∪ deleted ∪ ref 替换；图 / 表 / 公式引用标签若定义被删而别处仍引用 → FAIL。
- 退出码：--strict 且校验 FAIL 时 1。--dry-run 只校验计划、不写文件。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frame-inventory" / "scripts"))
from frame_common import Numbering, dump_json, iter_headings, load_json, section_order, setup_stdout  # noqa: E402

RE_FENCE = re.compile(r"^\s*(```|~~~)")
RE_LABEL_DEF = re.compile(r"\{#((?:fig|tbl|eq|sec):[A-Za-z0-9_\-:]+)\}")
RE_LABEL_REF = re.compile(r"(?<![{#])@((?:fig|tbl|eq|sec):[A-Za-z0-9_\-:]+)")


@dataclass
class Node:
    file: str
    line: int                    # 原稿 0-based 行号；insert 的节为负数
    level: int
    title: str                   # 去编号标题
    numbering: Numbering
    attrs: str                   # pandoc 属性，如 " {#sec:xx}"
    body: list[str] = field(default_factory=list)   # 本标题直辖正文行（到下一个标题为止）
    deleted: bool = False
    new_num: str = ""            # 重编号结果
    parent: "Node | None" = None  # renumber 时临时建树

    @property
    def id(self) -> str:
        return f"{self.file}:{self.line + 1}"


@dataclass
class Doc:
    """一个 md 文件 = 标题前导正文 + 平铺的标题序列（Markdown 语义：层级只由 # 个数决定）。"""
    file: str
    preamble: list[str]
    nodes: list[Node]

    def subtree(self, n: Node) -> list[Node]:
        """n 及其后续所有层级更深的节点（Markdown 的子树）。"""
        i = self.nodes.index(n)
        out = [n]
        for m in self.nodes[i + 1:]:
            if m.level <= n.level:
                break
            out.append(m)
        return out


def parse_file(path: Path) -> Doc:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    hl = {h.line: h for h in iter_headings(text, path.name)}
    preamble: list[str] = []
    nodes: list[Node] = []
    for i, ln in enumerate(lines):
        h = hl.get(i)
        if h is None:
            (nodes[-1].body if nodes else preamble).append(ln)
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", ln)
        raw_all = m.group(2) if m else ln
        am = re.search(r"(\s*\{[^}]*\})\s*$", raw_all)
        nodes.append(Node(path.name, i, h.level, h.title, h.numbering, am.group(1) if am else ""))
    return Doc(path.name, preamble, nodes)


# ------------------------------------------------------------------ 编号

CN_DIGITS = "一二三四五六七八九十"


def cn_num(i: int) -> str:
    if i <= 10:
        return CN_DIGITS[i - 1]
    if i < 20:
        return "十" + CN_DIGITS[i - 11]
    return CN_DIGITS[i // 10 - 1] + "十" + (CN_DIGITS[i % 10 - 1] if i % 10 else "")


def live(docs: list[Doc]):
    for d in docs:
        for n in d.nodes:
            if not n.deleted:
                yield n


def link_parents(docs: list[Doc]) -> list[str]:
    """给存活节点挂 parent；返回层级不连续的问题（子级必须 = 父级 + 1）。"""
    problems: list[str] = []
    for d in docs:
        stack: list[Node] = []
        for n in d.nodes:
            if n.deleted:
                continue
            while stack and stack[-1].level >= n.level:
                stack.pop()
            n.parent = stack[-1] if stack else None
            if n.parent and n.level != n.parent.level + 1:
                problems.append(f"层级不连续：「{n.title}」是 H{n.level}，上级「{n.parent.title}」是 H{n.parent.level}")
            elif n.parent is None and n.level != 1:
                problems.append(f"层级不连续：「{n.title}」是 H{n.level}，前面没有一级标题")
            stack.append(n)
    return problems


def detect_style(docs: list[Doc]) -> dict:
    """从原稿学编号样式：一级用阿拉伯/中文；附录子节 'A1' 还是 'A.1'。"""
    style = {"h1": "arabic", "app_sub": "A1", "cn_sep": ""}
    for n in live(docs):
        if n.level == 1 and n.numbering.style == "cn":
            style["h1"] = "cn"
            style["cn_sep"] = "、"
        if n.numbering.style == "appendix_sub" and "." in n.numbering.raw:
            style["app_sub"] = "A.1"
    return style


def renumber(docs: list[Doc], style: dict) -> dict[str, str]:
    """统一重编号。返回 旧编号 → 新编号 映射。无编号的一级章（摘要 / 参考文献）及其子节保持无编号。"""
    mapping: dict[str, str] = {}
    chap = 0
    app = 0
    counter: dict[int, int] = {}          # id(parent) → 已编号子节数
    chapter_kind: dict[int, str] = {}     # id(top) → arabic | appendix | none
    for n in live(docs):
        if n.level == 1:
            if n.numbering.style == "appendix":
                app += 1
                n.new_num = f"附录 {chr(ord('A') + app - 1)}"
                chapter_kind[id(n)] = "appendix"
            elif n.numbering.style in ("arabic", "cn", "cn_paren"):
                chap += 1
                n.new_num = cn_num(chap) + style["cn_sep"] if style["h1"] == "cn" else str(chap)
                chapter_kind[id(n)] = "arabic"
            else:
                n.new_num = ""
                chapter_kind[id(n)] = "none"
            counter[id(n)] = 0
            if n.numbering.raw and n.new_num:
                mapping[n.numbering.raw] = str(chap) if chapter_kind[id(n)] == "arabic" else n.new_num
            continue
        p = n.parent
        if p is None:
            n.new_num = ""
            continue
        counter[id(p)] = counter.get(id(p), 0) + 1
        counter[id(n)] = 0
        k = counter[id(p)]
        top = p
        while top.parent is not None:
            top = top.parent
        kind = chapter_kind.get(id(top), "none")
        if kind == "none":
            n.new_num = ""
        elif kind == "appendix":
            if p.level == 1:
                letter = p.new_num.replace("附录", "").strip()
                n.new_num = f"{letter}{'' if style['app_sub'] == 'A1' else '.'}{k}"
            else:
                n.new_num = f"{p.new_num}.{k}"
        else:
            base = str(chap_of(top)) if style["h1"] == "cn" else top.new_num
            n.new_num = f"{p.new_num if p.level > 1 else base}.{k}"
        if n.numbering.raw and n.new_num:
            mapping[n.numbering.raw] = n.new_num
    return mapping


def chap_of(top: Node) -> int:
    """中文编号一级章（“三、”）对应的阿拉伯序号，供二级编号 3.1 使用。"""
    s = top.new_num.rstrip("、")
    if s.isdigit():
        return int(s)
    n = 0
    if "十" in s:
        a, _, b = s.partition("十")
        n = (CN_DIGITS.index(a) + 1 if a else 1) * 10 + (CN_DIGITS.index(b) + 1 if b else 0)
    else:
        n = CN_DIGITS.index(s) + 1
    return n


def render(doc: Doc, keep_numbers: bool) -> list[str]:
    out = list(doc.preamble)
    for n in doc.nodes:
        if n.deleted:
            continue
        num = n.numbering.raw if keep_numbers else n.new_num
        title = f"{num} {n.title}".strip() if num else n.title
        out.append(f"{'#' * n.level} {title}{n.attrs}")
        out.extend(n.body)
    return out


# ------------------------------------------------------------------ 交叉引用

def build_ref_patterns(mapping: dict[str, str]) -> "Callable[[str], str] | None":
    """一次扫描完成全部替换（避免 4.5→4.6 再被 4.6→4.7 连锁改写）。
    只改带“章 / 节 / § / 见”限定的编号引用，避免误改普通数字。"""
    chapters = sorted((k for k, v in mapping.items() if k != v and re.fullmatch(r"\d+", k)), key=len, reverse=True)
    secs = sorted((k for k, v in mapping.items() if k != v and re.fullmatch(r"\d+(\.\d+)+", k)), key=len, reverse=True)
    apps = sorted((k for k, v in mapping.items() if k != v and k.startswith("附录")), key=len, reverse=True)
    parts = []
    if chapters:
        parts.append(rf"(?P<chap>第\s*(?P<chap_n>{'|'.join(map(re.escape, chapters))})\s*章)")
    if secs:
        alt = "|".join(map(re.escape, secs))
        parts.append(rf"(?P<sec>(?<![\d.])(?P<sec_n>{alt})(?![\d.])\s*(?P<sec_w>小节|节))")
        parts.append(rf"(?P<para>§\s*(?P<para_n>{alt})(?![\d.]))")
        parts.append(rf"(?P<see>(?P<see_w>见|参见|详见|如)\s*(?P<see_n>{alt})(?![\d.]))")
    if apps:
        parts.append(rf"(?P<app>{'|'.join(map(re.escape, apps))})")
    if not parts:
        return None
    pat = re.compile("|".join(parts))

    def rep(m: re.Match) -> str:
        g = m.groupdict()
        if g.get("chap"):
            return f"第 {mapping[g['chap_n']]} 章"
        if g.get("sec"):
            return f"{mapping[g['sec_n']]} {g['sec_w']}"
        if g.get("para"):
            return f"§{mapping[g['para_n']]}"
        if g.get("see"):
            return f"{g['see_w']} {mapping[g['see_n']]}"
        return mapping[g["app"]]

    return lambda text: pat.sub(rep, text)


def apply_refs(lines: list[str], sub: "Callable[[str], str] | None", file: str, log: list[dict]) -> list[str]:
    if sub is None:
        return list(lines)
    out: list[str] = []
    in_fence = False
    for i, ln in enumerate(lines):
        if RE_FENCE.match(ln):
            in_fence = not in_fence
        if in_fence or ln.lstrip().startswith("#"):
            out.append(ln)
            continue
        new = sub(ln)
        if new != ln:
            log.append({"file": file, "line": i + 1, "old": ln.strip(), "new": new.strip()})
        out.append(new)
    return out


# ------------------------------------------------------------------ 主流程

def apply_plan(proj: Path, plan: dict, src: Path, out: Path, dry_run: bool) -> dict:
    files = section_order(src)
    docs = [parse_file(f) for f in files]
    by_file = {d.file: d for d in docs}
    index: dict[str, Node] = {n.id: n for d in docs for n in d.nodes}
    problems: list[str] = []
    applied: list[dict] = []
    deleted_nodes: list[Node] = []
    merged: list[tuple[str, Node]] = []      # (被并入节的旧编号, 接收它的节) → 引用同步时指向接收节

    for k, op in enumerate(plan.get("ops", [])):
        kind = op.get("op")
        tag = f"ops[{k}] {kind}"
        if kind == "insert":
            anchor = index.get(op.get("after", ""))
            if anchor is None:
                problems.append(f"{tag}: after={op.get('after')} 不存在")
                continue
            title = str(op.get("title", "")).strip()
            if not title:
                problems.append(f"{tag}: title 为空")
                continue
            lvl = int(op.get("level", anchor.level + 1))
            doc = by_file[anchor.file]
            node = Node(anchor.file, -1 - k, lvl, title, Numbering("arabic", ""), "")
            if lvl > anchor.level:
                pos = doc.nodes.index(anchor) + 1              # 成为 anchor 的第一个子节
            else:
                pos = doc.nodes.index(doc.subtree(anchor)[-1]) + 1   # 放在 anchor 整个子树之后
            doc.nodes.insert(pos, node)
            applied.append({**op, "file": anchor.file})
            continue
        node = index.get(op.get("id", ""))
        if node is None:
            problems.append(f"{tag}: id={op.get('id')} 不存在")
            continue
        if node.deleted:
            problems.append(f"{tag}: id={op['id']} 已被前面的 delete 删除")
            continue
        doc = by_file[node.file]
        if kind == "rename":
            new = str(op.get("new", "")).strip()
            if not new:
                problems.append(f"{tag}: new 为空")
                continue
            if new.startswith("#") or re.match(r"^\d+(\.\d+)*\s", new):
                problems.append(f"{tag}: new 不要带 # 或编号，编号由工具统一生成")
                continue
            applied.append({**op, "old": node.title})
            node.title = new
        elif kind == "relevel":
            lvl = int(op["level"])
            if lvl < 1 or lvl > 6:
                problems.append(f"{tag}: level 越界")
                continue
            delta = lvl - node.level
            for m in doc.subtree(node):           # 子树整体平移，保持内部相对层级
                m.level += delta
            applied.append({**op, "old_level": lvl - delta, "title": node.title})
        elif kind == "merge_up":
            i = doc.nodes.index(node)
            if i == 0 and not doc.preamble:
                problems.append(f"{tag}: 文件首个标题不能 merge_up")
                continue
            # 只去掉标题行；正文自然归入前一个标题，子节层级不变
            prev_body = doc.nodes[i - 1].body if i > 0 else doc.preamble
            prev_body.extend(node.body)
            doc.nodes.pop(i)
            if i > 0 and node.numbering.style == "arabic" and node.numbering.raw:
                merged.append((node.numbering.raw, doc.nodes[i - 1]))
            applied.append({**op, "title": node.title, "into": doc.nodes[i - 1].title if i > 0 else "(文件前导)"})
        elif kind == "delete":
            sub = doc.subtree(node)
            for m in sub:
                m.deleted = True
            deleted_nodes.extend(sub)
            applied.append({**op, "title": node.title, "subsections": len(sub) - 1,
                            "lines": sum(len(m.body) for m in sub)})
        elif kind == "move":
            ref_id = op.get("after") or op.get("before")
            ref = index.get(ref_id or "")
            if ref is None or ref.file != node.file or ref.deleted:
                problems.append(f"{tag}: after/before={ref_id} 不存在、已删除或跨文件")
                continue
            sub = doc.subtree(node)
            if ref in sub:
                problems.append(f"{tag}: 不能挪到自己的子节旁")
                continue
            for m in sub:
                doc.nodes.remove(m)
            if op.get("after"):
                pos = doc.nodes.index(doc.subtree(ref)[-1]) + 1
            else:
                pos = doc.nodes.index(ref)
            doc.nodes[pos:pos] = sub
            applied.append({**op, "title": node.title, "subsections": len(sub) - 1})
        else:
            problems.append(f"{tag}: 未知 op")

    problems += link_parents(docs)
    keep_numbers = plan.get("numbering", "auto") == "keep"
    mapping: dict[str, str] = {}
    if not keep_numbers:
        mapping = renumber(docs, detect_style(docs))
        for old, into in merged:
            if into.new_num and not into.deleted:
                mapping[old] = into.new_num

    sub = build_ref_patterns(mapping)
    ref_log: list[dict] = []
    rendered: dict[str, list[str]] = {}
    for d in docs:
        rendered[d.file] = apply_refs(render(d, keep_numbers), sub, d.file, ref_log)

    verify = verify_drift(files, rendered, deleted_nodes, ref_log)
    verify["warn"] = refs_to_deleted(files, deleted_nodes)
    outline = [{"file": n.file, "id": n.id, "level": n.level, "num": (n.numbering.raw if keep_numbers else n.new_num),
                "title": n.title} for n in live(docs)]
    result = {"plan_ops": len(plan.get("ops", [])), "applied": applied, "problems": problems, "outline_after": outline,
              "numbering": {k: v for k, v in mapping.items() if k != v}, "refs": ref_log,
              "deleted": [{"id": n.id, "level": n.level, "title": n.title, "lines": len(n.body)} for n in deleted_nodes],
              "verify": verify, "written": not dry_run and not problems and not verify["fail"]}
    if result["written"]:
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        for f in files:
            (out / f.name).write_text("\n".join(rendered[f.name]), encoding="utf-8")
        yaml_src = src.parent / "paper.yaml"
        if yaml_src.exists():
            shutil.copy2(yaml_src, out.parent / "paper.yaml")
    return result


RE_NUM_REF = re.compile(r"第\s*(\d+)\s*章|(?<![\d.])(\d+(?:\.\d+)+)(?![\d.])\s*(?:小节|节)|§\s*(\d+(?:\.\d+)*)")


def refs_to_deleted(files: list[Path], deleted: list[Node]) -> list[str]:
    """原稿正文里指向被删节旧编号的引用：工具不改正文，只能提醒人处理。"""
    gone = {n.numbering.raw: n.title for n in deleted if n.numbering.style == "arabic" and n.numbering.raw}
    if not gone:
        return []
    out: list[str] = []
    for f in files:
        in_fence = False
        for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if RE_FENCE.match(ln):
                in_fence = not in_fence
            if in_fence or ln.lstrip().startswith("#"):
                continue
            for m in RE_NUM_REF.finditer(ln):
                ref = m.group(1) or m.group(2) or m.group(3)
                if ref in gone:
                    out.append(f"{f.name}:{i} 引用了被删节「{ref} {gone[ref]}」（{m.group(0).strip()}），需人工改写或不删")
    return out


def _deleted_lines(n: Node):
    yield from n.body


def verify_drift(files: list[Path], rendered: dict[str, list[str]], deleted: list[Node], ref_log: list[dict]) -> dict:
    """非标题行多重集：原稿 = 新稿 + 删除行 + 引用替换（old→new 各计一次）。同时检查标签引用悬空。"""
    def non_heading(lines: list[str]) -> Counter:
        c: Counter = Counter()
        in_fence = False
        for ln in lines:
            if RE_FENCE.match(ln):
                in_fence = not in_fence
                c[ln] += 1
                continue
            if not in_fence and re.match(r"^#{1,6}\s", ln):
                continue
            c[ln] += 1
        return c

    old_all: Counter = Counter()
    new_all: Counter = Counter()
    old_text = ""
    new_text = ""
    for f in files:
        t = f.read_text(encoding="utf-8")
        old_text += t + "\n"
        old_all.update(non_heading(t.split("\n")))
        new_lines = rendered[f.name]
        new_text += "\n".join(new_lines) + "\n"
        new_all.update(non_heading(new_lines))
    for n in deleted:
        new_all.update(_deleted_lines(n))
    diff_missing = old_all - new_all
    diff_extra = new_all - old_all
    # 引用替换：old 行在 missing、new 行在 extra，各消一次
    for r in ref_log:
        for k in list(diff_missing):
            if k.strip() == r["old"]:
                diff_missing[k] -= 1
                break
        for k in list(diff_extra):
            if k.strip() == r["new"]:
                diff_extra[k] -= 1
                break
    diff_missing = +diff_missing
    diff_extra = +diff_extra
    fail: list[str] = []
    if diff_missing:
        fail.append(f"原稿有 {sum(diff_missing.values())} 行正文在新稿中消失（非删除、非引用替换）")
    if diff_extra:
        fail.append(f"新稿多出 {sum(diff_extra.values())} 行正文")
    defs_old = set(RE_LABEL_DEF.findall(old_text))
    defs_new = set(RE_LABEL_DEF.findall(new_text))
    refs_new = set(RE_LABEL_REF.findall(new_text))
    dangling = sorted((refs_new & defs_old) - defs_new)
    if dangling:
        fail.append("被删节里定义的标签仍被引用：" + "、".join(dangling))
    return {"fail": fail, "missing_lines": list(diff_missing)[:20], "extra_lines": list(diff_extra)[:20],
            "labels_removed": sorted(defs_old - defs_new), "dangling_refs": dangling,
            "figures_removed": sum(1 for n in deleted for ln in _deleted_lines(n) if "![" in ln),
            "display_eqs_removed": sum(ln.count("$$") for n in deleted for ln in _deleted_lines(n)) // 2}


def main() -> None:
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proj", type=Path)
    ap.add_argument("--plan", default="frame/frame_plan.json")
    ap.add_argument("--src", default=None, help="缺省取 plan.src，再缺省 paper/sections")
    ap.add_argument("--out", default="frame/sections")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    proj = a.proj.resolve()
    plan = load_json(proj / a.plan)
    src = (proj / (a.src or plan.get("src") or "paper/sections")).resolve()
    out = (proj / a.out).resolve()
    if out == src or src in out.parents:
        sys.exit("输出目录不能是源目录或其子目录")
    res = apply_plan(proj, plan, src, out, a.dry_run)
    dump_json(proj / "frame" / "frame_apply.json", res)
    v = res["verify"]
    status = "DRY-RUN" if a.dry_run else ("WRITTEN" if res["written"] else "NOT WRITTEN")
    print(f"[apply] {status}: ops {res['plan_ops']} 应用 {len(res['applied'])} 问题 {len(res['problems'])}"
          f" 删节 {len(res['deleted'])} 编号变更 {len(res['numbering'])} 引用同步 {len(res['refs'])}"
          f" 校验 {'FAIL ' + '; '.join(v['fail']) if v['fail'] else 'OK'} 提醒 {len(v['warn'])}")
    for w in v["warn"]:
        print(f"  ~ {w}")
    for p in res["problems"]:
        print(f"  ! {p}")
    if a.strict and (v["fail"] or res["problems"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
