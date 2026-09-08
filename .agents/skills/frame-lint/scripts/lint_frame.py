"""lint_frame.py — 对照优秀论文语料，检查论文框架与标题命名，输出 frame/FRAME_LINT.md + frame/frame_lint.json。

用法：
    python lint_frame.py <proj> [--inventory frame/frame_inventory.json] [--out frame/FRAME_LINT.md] [--strict]

规则分三层，阈值全部来自 _references/FRAME_NORMS.json（语料生成）与 heading_roles.json / term_map.json：

  框架层（整篇）
    skeleton_missing     语料 ≥ 40% 论文都有的一级章角色缺失（重述 / 假设 / 符号 / 问题章 / 评价 / 参考文献）
    skeleton_order       一级章角色顺序与语料骨架不一致
    h2_overload / h3_overload   二级 / 三级标题总数超过语料 P75（WARN）或 P90（FAIL）
    problem_chain        问题章缺少语料里最常见的二级环节（问题分析 / 模型建立 / 求解 / 结果）
    numbering_gap        同级编号不连续或重复
    xref_missing         正文“第 N 章 / N.N 节”指向不存在的编号
  节层
    thin_section         无子节且正文 < 阈值汉字、无图表公式的节（合并 / 删除候选）
    lonely_child         只有一个子节的节（层级可以拉平）
    sibling_mixed        同一父节下兄弟标题有的带冒号 / 括号有的不带，句式不齐
  标题层（逐条）
    title_long           长度 > 语料同级 P90（WARN），> P75（INFO）
    title_colon / title_paren / title_dash / title_quote / title_slash / title_enum / title_comma  标题带这些标点（语料占比很低）
    title_numeral        标题里出现数量词（“六种”“9 模型”“30 维”“前 5 名”）
    title_code_id        标题里出现内部编号 / 代号（R3、D0–D4）或“（第 4 章）”式交叉引用
    title_question       疑问句式标题
    term_informal        命中 term_map.json 的口语 / 比喻 / 工程腔词，给出规范候选
    role_variant         标题能识别为某个角色但不是语料主流写法，给出主流写法及频次
    problem_title_form   问题章一级标题不是语料主流句式（“问题 N 的模型建立与求解”等）
    term_title_only      标题里有术语库外、且全篇正文几乎不出现的串（标题上的临时说法 / 自造词）
    term_unrecognized    标题里有术语库外但正文常用的串（INFO：多为领域术语，确认后写入项目 FRAME_TERMS.json）

只读；退出码：--strict 且有 FAIL 时 1。
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frame-inventory" / "scripts"))
from frame_common import REF_DIR, dump_json, load_json, load_roles, setup_stdout  # noqa: E402

CN_NUM_WORDS = "一二三四五六七八九十两"
RE_NUMERAL = re.compile(rf"(?:^|[^\w])(\d+|[{CN_NUM_WORDS}]+)\s*(?:种|个|类|组|维|名|项|步|层|阶段|模型|文件|折|次|轮|条|张|台|款)")
RE_CODE_ID = re.compile(r"(?<![A-Za-z])[A-Z]\d{1,2}(?:\s*[–\-—~～]\s*[A-Z]?\d{1,2})?(?![A-Za-z])")
RE_CHAPTER_REF = re.compile(r"[（(]?\s*第\s*\d+\s*[章节]\s*[)）]?|\d+\.\d+\s*节")
RE_QUESTION = re.compile(r"[？?]|^(为何|如何|是否|能否|怎样)|(为何|如何|是否|能否|怎样)[^，]*$")
PUNCT_RULES = {"colon": "title_colon", "paren": "title_paren", "dash": "title_dash", "quote": "title_quote",
               "slash": "title_slash", "enum": "title_enum", "comma": "title_comma", "question": "title_question"}
CORE_ROLES = {"restatement", "problem_chapter", "evaluation", "references"}
ROLE_ALIASES = {"assumptions": {"assumptions_notation"}, "notation": {"assumptions_notation"},
                "assumptions_notation": {"assumptions", "notation"}}
CHAIN_ROLES = ["sub_analysis", "sub_model", "sub_solve", "sub_results"]
UNKNOWN_BODY_TF = 3      # 术语库外的串在正文出现 ≥ 此次数视为项目在用的领域术语


class Lint:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, sev: str, rule: str, msg: str, hid: str | None = None, title: str = "", **extra) -> None:
        self.items.append({"sev": sev, "rule": rule, "id": hid, "title": title, "msg": msg, **extra})


def role_canon(norms: dict) -> dict[str, tuple[str, int, list]]:
    """每个角色在语料里最常见的写法（频次）与前几种变体。"""
    out: dict[str, tuple[str, int, list]] = {}
    for role, variants in norms.get("role_variants", {}).items():
        if variants:
            out[role] = (variants[0][0], variants[0][1], variants[:5])
    for r in load_roles():
        out.setdefault(r["role"], (r["canonical"], 0, []))
    return out


def lint(inv: dict, norms: dict, term_map: dict) -> Lint:
    L = Lint()
    heads = inv["headings"]
    by_id = {h["id"]: h for h in heads}
    canon = role_canon(norms)
    tlen = norms["title_len"]
    cnt = norms["per_paper_counts"]

    # ---------- 框架层
    h1 = [h for h in heads if h["level"] == 1]
    roles_present = {h["role"] for h in h1 if h["role"]}
    skeleton = [s for s in norms["h1_skeleton"] if s["share"] >= 0.4]
    for s in skeleton:
        r = s["role"]
        if r in roles_present or (ROLE_ALIASES.get(r, set()) & roles_present):
            continue
        L.add("WARN", "skeleton_missing", f"语料 {s['share']:.0%} 的论文有一级章「{canon[r][0]}」，本稿没有", role=r)
    order = [s["role"] for s in norms["h1_skeleton"]]
    seq = [h for h in h1 if h["role"] in order]
    for a, b in zip(seq, seq[1:]):
        ra, rb = a["role"], b["role"]
        if ra == rb:
            continue
        if order.index(ra) > order.index(rb) and not ({ra, rb} <= {"assumptions", "notation", "assumptions_notation"}):
            L.add("WARN", "skeleton_order", f"「{a['title']}」({ra}) 排在「{b['title']}」({rb}) 之前，语料骨架相反",
                  b["id"], b["title"])
    for lvl in (2, 3):
        n = inv["counts"].get(f"h{lvl}", 0)
        q = cnt.get(f"h{lvl}", {})
        if q and n > q["p90"]:
            L.add("FAIL", f"h{lvl}_overload", f"H{lvl} 共 {n} 个，超过语料 P90 = {q['p90']}（P50 = {q['p50']}）")
        elif q and n > q["p75"]:
            L.add("WARN", f"h{lvl}_overload", f"H{lvl} 共 {n} 个，超过语料 P75 = {q['p75']}（P50 = {q['p50']}）")

    # 问题章处理链
    chain_share = {r["role"]: r["per_chapter"] for r in norms.get("problem_h2_roles", [])}
    for i, h in enumerate(heads):
        if h["level"] != 1 or h["role"] != "problem_chapter":
            continue
        kids = []
        for h2 in heads[i + 1:]:
            if h2["level"] == 1:
                break
            if h2["level"] == 2:
                kids.append(h2)
        kid_roles = {k["role"] for k in kids}
        missing = [r for r in CHAIN_ROLES if r not in kid_roles and chain_share.get(r, 0) >= 0.09]
        if missing:
            names = "、".join(f"{canon[r][0]}({chain_share[r]:.0%})" for r in missing)
            L.add("INFO", "problem_chain", f"问题章「{h['title']}」二级标题里识别不到常见环节：{names}（括号为语料中每章出现率）",
                  h["id"], h["title"], missing=missing)
        # 主流句式
        forms = [f for f, _c in norms.get("problem_chapter_title_forms", [])]
        t_norm = re.sub(rf"[{CN_NUM_WORDS}0-9]+", "N", h["title"])
        if forms and t_norm not in forms[:8]:
            L.add("WARN", "problem_title_form", f"问题章标题「{h['title']}」不是语料主流句式；主流：" +
                  "、".join(f"{f}({c})" for f, c in norms["problem_chapter_title_forms"][:4]), h["id"], h["title"])

    # 编号连续性
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for h in heads:
        if h["num_style"] == "arabic":
            parts = tuple(int(x) for x in h["num"].split("."))
            groups[(h["level"], parts[:-1])].append(h)
    for key, hs in groups.items():
        nums = [int(h["num"].split(".")[-1]) for h in hs]
        expect = list(range(nums[0], nums[0] + len(nums)))
        if nums != expect:
            L.add("WARN", "numbering_gap", f"同级编号不连续：{[h['num'] for h in hs]}", hs[0]["id"], hs[0]["title"])

    # ---------- 节层
    thin = norms.get("thin_section_chars", 120)
    children_of: dict[str, list[dict]] = defaultdict(list)
    stack: list[dict] = []
    for h in heads:
        while stack and stack[-1]["level"] >= h["level"]:
            stack.pop()
        parent = stack[-1]["id"] if stack else "_root"
        children_of[parent].append(h)
        stack.append(h)
    for h in heads:
        ob = h["own_body"]
        if h["children"] == 0 and h["role"] not in ("abstract", "references") and h["num_style"] != "appendix" \
                and ob["zh_chars"] < thin and ob["figures"] + ob["tables"] + ob["display_eqs"] + ob["code_blocks"] == 0:
            L.add("WARN", "thin_section", f"正文仅 {ob['zh_chars']} 字且无图表公式，考虑并入相邻节或删除", h["id"], h["title"])
        if h["children"] == 1:
            L.add("INFO", "lonely_child", "只有一个子节，层级可拉平（子节标题并入本节）", h["id"], h["title"])
    for parent, kids in children_of.items():
        if len(kids) < 3 or parent == "_root":
            continue
        with_colon = [k for k in kids if "colon" in k["punct"]]
        if 0 < len(with_colon) < len(kids):
            L.add("INFO", "sibling_mixed", f"{len(with_colon)}/{len(kids)} 个兄弟标题带冒号，句式不齐",
                  parent, by_id[parent]["title"] if parent in by_id else "")

    # ---------- 标题层
    for h in heads:
        t, lvl = h["title"], h["level"]
        q = tlen.get(f"h{min(lvl, 3)}", {})
        if q:
            if h["len"] > q["p90"]:
                L.add("WARN", "title_long", f"{h['len']} 字 > 语料 H{lvl} P90 = {q['p90']}（P50 = {q['p50']}）", h["id"], t)
            elif h["len"] > q["p75"]:
                L.add("INFO", "title_long", f"{h['len']} 字 > 语料 H{lvl} P75 = {q['p75']}", h["id"], t)
        for kind in h["punct"]:
            rule = PUNCT_RULES.get(kind)
            if not rule:
                continue
            rate = norms["punct_rate"].get(kind, 0.0)
            sev = "WARN" if rate < 0.05 else "INFO"
            if kind == "paren" and re.search(r"[（(][a-z]\s*[)）]", t):
                continue  # 问题一(a) 这类小问标记在语料里常见
            L.add(sev, rule, f"语料标题中仅 {rate:.1%} 含此标点", h["id"], t)
        if RE_NUMERAL.search(t):
            L.add("WARN", "title_numeral", "数量词进入标题，语料标题几乎不写数量（放正文）", h["id"], t)
        if RE_CHAPTER_REF.search(t):
            L.add("WARN", "title_code_id", "标题里带章节交叉引用，编号一变就失效；放到节首正文", h["id"], t)
        elif RE_CODE_ID.search(t) and h["num_style"] != "appendix_sub":
            L.add("WARN", "title_code_id", "标题里带内部编号 / 代号（如 R3、D0–D4），读者无法从目录理解", h["id"], t)
        if RE_QUESTION.search(t):
            L.add("WARN", "title_question", "疑问句式标题，改为名词短语", h["id"], t)
        for w, spec in term_map.items():
            if w in t:
                sug = " / ".join(spec["formal"]) if spec["formal"] else "改写为名词短语"
                L.add("WARN", "term_informal", f"「{w}」（{spec['note'] or '非学术用词'}）→ {sug}", h["id"], t, word=w,
                      formal=spec["formal"])
        role = h["role"]
        if role and role in canon and role not in ("problem_chapter",):
            main, n, variants = canon[role]
            if n and re.sub(r"\s+", "", t) != main and re.sub(r"\s+", "", t) not in {v for v, _ in variants[:2]}:
                alts = "、".join(f"{v}({c})" for v, c in variants[:3])
                L.add("INFO", "role_variant", f"角色 {role}，语料主流写法：{alts}", h["id"], t, role=role, canonical=main)
        if h["unknown"] and role is None:
            tfs = h.get("unknown_body_tf", {})
            rare = h.get("title_only", [])
            used = [f"{u}（正文 {tfs[u]} 次）" for u in h["unknown"] if tfs.get(u, 0) >= UNKNOWN_BODY_TF]
            if rare:
                L.add("WARN", "term_title_only", "术语库外且正文找不到依托：" + "、".join(rare)
                      + "（标题上的临时说法 / 自造词？改用正文里实际使用的术语）", h["id"], t, unknown=h["unknown"])
            if used:
                L.add("INFO", "term_unrecognized", "术语库外但正文常用：" + "、".join(used)
                      + "（若为领域规范术语，写入 frame/FRAME_TERMS.json 即消音）", h["id"], t, unknown=h["unknown"])
    return L


RE_XREF = re.compile(r"第\s*(\d+)\s*章|(?<![\d.])(\d+(?:\.\d+)+)(?![\d.])\s*(?:小节|节)|§\s*(\d+(?:\.\d+)*)")


def lint_xrefs(L: Lint, inv: dict, proj: Path) -> None:
    """正文里“第 N 章 / N.N 节 / §N.N”指向的编号必须真有对应标题（适用于原稿和应用后的稿）。"""
    nums = {h["num"] for h in inv["headings"] if h["num_style"] == "arabic"}
    if not nums:
        return
    src = proj / inv["src"]
    seen: set[tuple] = set()
    for f in inv["files"]:
        p = src / f["file"]
        if not p.exists():
            continue
        in_fence = False
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^\s*(```|~~~)", ln):
                in_fence = not in_fence
            if in_fence or ln.lstrip().startswith("#"):
                continue
            for m in RE_XREF.finditer(ln):
                ref = m.group(1) or m.group(2) or m.group(3)
                if ref in nums or (f["file"], ref) in seen:
                    continue
                seen.add((f["file"], ref))
                L.add("WARN", "xref_missing", f"正文引用了不存在的编号「{m.group(0).strip()}」（{f['file']}:{i}）")


def render_md(L: Lint, inv: dict, norms: dict) -> str:
    sev_n = Counter(i["sev"] for i in L.items)
    rule_n = Counter((i["sev"], i["rule"]) for i in L.items)
    out = [f"# FRAME_LINT — 框架与标题命名检查", "",
           f"源：`{inv['src']}`；标题 H1 {inv['counts'].get('h1', 0)} / H2 {inv['counts'].get('h2', 0)} / "
           f"H3 {inv['counts'].get('h3', 0)}；语料 n = {norms['n_papers']}（`_references/FRAME_NORMS.md`）。", "",
           f"**FAIL {sev_n.get('FAIL', 0)} · WARN {sev_n.get('WARN', 0)} · INFO {sev_n.get('INFO', 0)}**", "",
           "## 按规则", "", "| 级别 | 规则 | 条数 |", "| --- | --- | ---: |"]
    for (sev, rule), n in sorted(rule_n.items(), key=lambda kv: ({"FAIL": 0, "WARN": 1, "INFO": 2}[kv[0][0]], -kv[1])):
        out.append(f"| {sev} | `{rule}` | {n} |")
    out += ["", "## 全局问题", ""]
    glob = [i for i in L.items if not i["id"] or i["rule"] in ("skeleton_missing", "skeleton_order", "h2_overload",
                                                              "h3_overload", "xref_missing")]
    for i in glob:
        out.append(f"- **{i['sev']}** `{i['rule']}` {i['msg']}" + (f" ← {i['title']}" if i["title"] else ""))
    if not glob:
        out.append("- 无")
    out += ["", "## 逐标题", "", "每条标题列出所有命中的规则；INFO 是提示不是错误。", ""]
    per: dict[str, list[dict]] = defaultdict(list)
    for i in L.items:
        if i["id"] and i not in glob:
            per[i["id"]].append(i)
    for h in inv["headings"]:
        items = per.get(h["id"])
        if not items:
            continue
        indent = "  " * (h["level"] - 1)
        out.append(f"- {indent}`{h['id']}` **{h['num']} {h['title']}**".replace("**  ", "** "))
        for i in sorted(items, key=lambda x: {"FAIL": 0, "WARN": 1, "INFO": 2}[x["sev"]]):
            out.append(f"  {indent}- {i['sev']} `{i['rule']}` {i['msg']}")
    out.append("")
    return "\n".join(out)


def main() -> None:
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proj", type=Path)
    ap.add_argument("--inventory", default="frame/frame_inventory.json")
    ap.add_argument("--out", default="frame/FRAME_LINT.md")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    proj = a.proj.resolve()
    inv = load_json(proj / a.inventory)
    norms = load_json(REF_DIR / "FRAME_NORMS.json")
    term_map = load_json(REF_DIR / "term_map.json")["map"]
    L = lint(inv, norms, term_map)
    lint_xrefs(L, inv, proj)
    (proj / a.out).parent.mkdir(parents=True, exist_ok=True)
    (proj / a.out).write_text(render_md(L, inv, norms), encoding="utf-8")
    out_md = proj / a.out
    dump_json(out_md.with_name(out_md.stem.lower() + ".json"), {"items": L.items})
    sev = Counter(i["sev"] for i in L.items)
    print(f"[lint] FAIL {sev.get('FAIL', 0)} WARN {sev.get('WARN', 0)} INFO {sev.get('INFO', 0)} → {a.out}")
    if a.strict and sev.get("FAIL"):
        sys.exit(1)


if __name__ == "__main__":
    main()
