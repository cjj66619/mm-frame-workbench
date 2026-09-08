"""build_corpus.py — 从往年优秀论文 PDF 建立框架语料：标题大纲、术语库、命名规范。

用法：
    python build_corpus.py <pdf 目录或多个目录> [--year 23] [--out-dir .agents/skills/_references] [--min-df 3]

输出（均可重跑覆盖，勿手改）：
    outline_corpus.json  每篇论文的标题大纲（层级 / 标题 / 页码），文件名匿名化为 <题号><年份>-<序号>
    term_bank.json       术语库：正文与标题中跨 ≥ min-df 篇出现的中文 n-gram 与英文词，含 df / tf / 是否出现在标题
    FRAME_NORMS.json     命名规范：各级标题长度分位、标点比率、每篇标题数量分位、一级章骨架、问题章二级骨架、
                         各角色的实际变体与频次、编号风格分布
    FRAME_NORMS.md       上述规范的可读版

依赖：pymupdf（仅本脚本；项目侧脚本不需要）。仓库不存 PDF、不存队号。
大纲来源：PDF 书签优先，不足 8 条时解析“目录”页。正文范围：摘要起、参考文献止。
"""
from __future__ import annotations

import argparse
import math
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frame-inventory" / "scripts"))
from frame_common import (REF_DIR, classify_role, dump_json, load_json, punct_kinds, setup_stdout,  # noqa: E402
                          split_number, zh_len)

try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None

CN_NUM = "一二三四五六七八九十"
TOC_LINE = re.compile(r"^(?P<title>.+?)\s*[.．…·_\s]{3,}\s*(?P<page>\d{1,3})\s*$")
CODE_LIKE = re.compile(r"[=;{}\[\]<>#%]|^\d+\.\s*[A-Za-z_]|\b(import|def|for|end|function|print)\b")
STOP_EDGE = set("的了与和及在是对为中由到并或所其之等可将被有用后前时于于从以上下来这那也又即若则而且但如把使得")
ZH_RUN = re.compile(r"[\u4e00-\u9fff]+")
EN_TOK = re.compile(r"\b[A-Za-z][A-Za-z0-9\-]{1,}\b")


# ------------------------------------------------------------------ 大纲

def load_json_list(path: Path) -> list[dict]:
    data = load_json(path)
    return data if isinstance(data, list) else []


def _level_of(title: str) -> int | None:
    num, rest = split_number(title)
    if num.style == "arabic":
        return len(num.parts)
    if num.style in ("cn", "appendix"):
        return 1
    if num.style == "cn_paren":
        return 2
    if num.style == "appendix_sub":
        return 2
    if re.fullmatch(r"(摘\s*要|目\s*录|参\s*考\s*文\s*献|附\s*录)", title.strip()):
        return 1
    return None


def _from_bookmarks(doc) -> list[list]:
    out = []
    for lvl, title, page in doc.get_toc():
        title = re.sub(r"\s+", " ", title).strip()
        if not title or lvl > 3:
            continue
        inferred = _level_of(title)
        if inferred is None and len(title) > 20:
            continue
        out.append([inferred or lvl, title, page])
    return out


def _from_toc_pages(doc) -> list[list]:
    out: list[list] = []
    started = False
    prefix = ""
    for pno in range(min(8, len(doc))):
        text = doc[pno].get_text()
        if not started:
            if re.search(r"目\s*录", text):
                started = True
            else:
                continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for ln in lines:
            if re.fullmatch(r"目\s*录", ln):
                continue
            if re.fullmatch(rf"[{CN_NUM}]+[、.．:：]?", ln) or re.fullmatch(rf"第[{CN_NUM}]+[章部分]?", ln):
                prefix = ln
                continue
            m = TOC_LINE.match(ln)
            if not m:
                continue
            title = re.sub(r"\s+", " ", m.group("title")).strip()
            if prefix:
                title = f"{prefix} {title}"
                prefix = ""
            lvl = _level_of(title)
            if lvl is None:
                continue
            out.append([lvl, title, int(m.group("page"))])
        if out and pno >= 2 and not any(TOC_LINE.match(ln) for ln in lines[-5:]) and len(out) > 8:
            break
    return out


def _clean_outline(items: list[list]) -> list[list]:
    """去封面 / 代码行 / 假标题；从第一个能识别为论文角色的条目开始。"""
    start = 0
    for i, (lvl, title, _) in enumerate(items):
        if classify_role(split_number(title)[1], lvl):
            start = i
            break
    out = []
    for lvl, title, page in items[start:]:
        t = split_number(title)[1]
        if not t and split_number(title)[0].style == "none":
            continue
        if CODE_LIKE.search(t) or len(t) > 45:
            continue
        out.append([lvl, title, page])
    return out


def _body_text(doc) -> str:
    full = "\n".join(p.get_text() for p in doc)
    m = re.search(r"摘\s*要", full)
    start = m.start() if m else 0
    ends = [m.start() for m in re.finditer(r"(?m)^\s*(参考文献|参 考 文 献|References)\s*$", full)]
    end = ends[-1] if ends and ends[-1] > start else len(full)
    return full[start:end]


def extract_paper(pdf: Path) -> tuple[dict, str]:
    doc = pymupdf.open(pdf)
    outline = _from_bookmarks(doc)
    source = "bookmarks"
    if len(outline) < 8:
        outline = _from_toc_pages(doc)
        source = "toc_pages"
    outline = _clean_outline(outline)
    meta = {"problem": pdf.stem[:1].upper() if pdf.stem[:1].isalpha() else "?", "pages": len(doc),
            "source": source, "outline": outline}
    return meta, _body_text(doc)


# ------------------------------------------------------------------ 术语

def zh_ngrams(text: str, lo: int = 2, hi: int = 6) -> Counter:
    c: Counter = Counter()
    for run in ZH_RUN.findall(text):
        n = len(run)
        for L in range(lo, hi + 1):
            for i in range(0, n - L + 1):
                c[run[i:i + L]] += 1
    return c


def _entropy(counter: Counter) -> float:
    total = sum(counter.values())
    if total == 0:
        return 0.0
    return -sum(v / total * math.log(v / total) for v in counter.values())


def extract_terms(bodies: list[str], min_df: int, min_tf: int = 6, min_cohesion: float = 30.0,
                  min_entropy: float = 1.2) -> dict[str, dict]:
    """新词发现式术语抽取：候选 = 跨 ≥ min_df 篇的 2–6 字串；保留内聚度高（各切分点 PMI）、
    左右邻接熵都高（能独立成词）、且首尾不是虚词的串。"""
    tf: Counter = Counter()
    df: Counter = Counter()
    uni: Counter = Counter()
    for body in bodies:
        grams = zh_ngrams(body, 1, 6)
        for g, v in grams.items():
            if len(g) == 1:
                uni[g] += v
            else:
                tf[g] += v
        df.update(g for g in grams if len(g) > 1)
    total_chars = max(sum(uni.values()), 1)
    cand = {g for g, d in df.items() if d >= min_df and tf[g] >= min_tf
            and g[0] not in STOP_EDGE and g[-1] not in STOP_EDGE}

    def prob(s: str) -> float:
        return (uni[s] if len(s) == 1 else tf[s]) / total_chars

    cohesive: set[str] = set()
    for g in cand:
        pg = prob(g)
        score = min(pg / (prob(g[:i]) * prob(g[i:]) or 1e-12) for i in range(1, len(g)))
        if score >= min_cohesion:
            cohesive.add(g)
    half = max(len(bodies) // 2, min_df)
    common_cand = {g for g, d in df.items() if g not in cohesive and len(g) <= 3 and d >= half and tf[g] >= 3 * min_tf
                   and g[0] not in STOP_EDGE and g[-1] not in STOP_EDGE}
    watch = cohesive | common_cand
    left: dict[str, Counter] = defaultdict(Counter)
    right: dict[str, Counter] = defaultdict(Counter)
    for body in bodies:
        for run in ZH_RUN.findall(body):
            n = len(run)
            for L in range(2, 7):
                for i in range(0, n - L + 1):
                    g = run[i:i + L]
                    if g in watch:
                        left[g][run[i - 1] if i > 0 else "^"] += 1
                        right[g][run[i + L] if i + L < n else "$"] += 1
    terms: dict[str, dict] = {}
    for g in cohesive:
        if min(_entropy(left[g]), _entropy(right[g])) < min_entropy:
            continue
        terms[g] = {"df": df[g], "tf": tf[g], "kind": "zh", "in_heading": 0}
    # 通用词：跨 ≥ 一半论文出现、左右邻接都很自由的 2–3 字串（集合、系数、量化…）。内聚度不够算不上术语，
    # 但也绝不是自造词，入库为 common 免得切分时被当作未识别
    for g in common_cand:
        if min(_entropy(left[g]), _entropy(right[g])) < min_entropy + 1.0:
            continue
        terms[g] = {"df": df[g], "tf": tf[g], "kind": "common", "in_heading": 0}
    return terms


def build_term_bank(bodies: list[str], outlines: list[list[list]], min_df: int) -> dict:
    terms = extract_terms(bodies, min_df)
    en_df: Counter = Counter()
    en_tf: Counter = Counter()
    for body in bodies:
        toks = Counter(t for t in EN_TOK.findall(body) if len(t) <= 20 and not re.fullmatch(r"[a-z]+\d+", t))
        en_tf.update(toks)
        en_df.update(toks.keys())
    # 标题里跨 ≥2 篇出现的字串直接入库（去编号后的整句 + 其内部 n-gram）
    head_df: Counter = Counter()
    for outline in outlines:
        seen: set[str] = set()
        for _lvl, title, _pg in outline:
            t = split_number(title)[1]
            for run in ZH_RUN.findall(t):
                seen.add(run)
                seen.update(g for g in zh_ngrams(run, 2, 6) if g in terms)
            seen.update(EN_TOK.findall(t))
        head_df.update(seen)
    for g, d in head_df.items():
        if g in terms:
            terms[g]["in_heading"] = d
        elif d >= 2 and ZH_RUN.fullmatch(g) and len(g) <= 12:
            terms[g] = {"df": d, "tf": d, "kind": "zh", "in_heading": d}
    # 冗余剪枝：正文短串几乎只作为更长术语的一部分出现（≥ 0.85）时删掉，标题词保留
    cover: Counter = Counter()
    for g in terms:
        if terms[g]["kind"] != "zh" or len(g) < 3:
            continue
        for L in range(2, len(g)):
            for i in range(0, len(g) - L + 1):
                s = g[i:i + L]
                if s in terms:
                    cover[s] += terms[g]["tf"]
    for s, c in cover.items():
        if terms[s]["in_heading"] == 0 and c / max(terms[s]["tf"], 1) >= 0.85:
            del terms[s]
    for t, d in en_df.items():
        if (d >= min_df and (t[:1].isupper() or d >= 2 * min_df)) or head_df.get(t, 0) >= 2:
            terms[t] = {"df": d, "tf": en_tf[t], "kind": "en", "in_heading": head_df.get(t, 0)}
    return dict(sorted(terms.items()))


# ------------------------------------------------------------------ 规范

def quantiles(v: list[float]) -> dict:
    if not v:
        return {}
    s = sorted(v)
    q = st.quantiles(s, n=20) if len(s) >= 20 else None
    return {"n": len(s), "p25": round(st.quantiles(s, n=4)[0], 1) if len(s) >= 4 else s[0],
            "p50": round(st.median(s), 1), "p75": round(st.quantiles(s, n=4)[2], 1) if len(s) >= 4 else s[-1],
            "p90": round(q[17], 1) if q else s[-1], "max": s[-1]}


def build_norms(papers: list[dict]) -> dict:
    lens: dict[int, list[int]] = defaultdict(list)
    punct: Counter = Counter()
    n_titles = 0
    counts: dict[int, list[int]] = defaultdict(list)
    role_variants: dict[str, Counter] = defaultdict(Counter)
    h1_sequences: list[list[str]] = []
    h1_roles: Counter = Counter()
    problem_h2_roles: Counter = Counter()
    problem_h2_variants: Counter = Counter()
    n_problem_chapters = 0
    num_styles: Counter = Counter()
    problem_chapter_titles: Counter = Counter()
    for p in papers:
        outline = p["outline"]
        cnt = Counter(x[0] for x in outline)
        for lvl in (1, 2, 3):
            counts[lvl].append(cnt.get(lvl, 0))
        seq: list[str] = []
        cur_h1_role = None
        for lvl, title, _pg in outline:
            num, t = split_number(title)
            if not t:
                continue
            n_titles += 1
            lens[lvl].append(zh_len(t))
            for k in punct_kinds(t):
                punct[k] += 1
            role = classify_role(t, lvl)
            if lvl == 1:
                num_styles[num.style] += 1
                cur_h1_role = role
                if role:
                    seq.append(role)
                    h1_roles[role] += 1
                    if role == "problem_chapter":
                        n_problem_chapters += 1
                        problem_chapter_titles[re.sub(r"[一二三四五六七八九十0-9]+", "N", t)] += 1
            if role:
                role_variants[role][t] += 1
            if lvl == 2 and cur_h1_role == "problem_chapter":
                problem_h2_roles[role or "other"] += 1
                problem_h2_variants[t] += 1
        h1_sequences.append(seq)
    h1_papers = Counter(r for seq in h1_sequences for r in set(seq))   # 有该角色的篇数（不是标题数）
    # 骨架：角色按其在各篇中的相对位置中位数排序
    pos: dict[str, list[float]] = defaultdict(list)
    for seq in h1_sequences:
        uniq = []
        for r in seq:
            if r not in uniq:
                uniq.append(r)
        for i, r in enumerate(uniq):
            pos[r].append(i / max(len(uniq) - 1, 1))
    skeleton = sorted(pos, key=lambda r: st.median(pos[r]))
    n = len(papers)
    return {
        "n_papers": n,
        "generated": date.today().isoformat(),
        "title_len": {f"h{l}": quantiles(lens[l]) for l in (1, 2, 3)},
        "punct_rate": {k: round(v / max(n_titles, 1), 4) for k, v in punct.most_common()},
        "n_titles": n_titles,
        "per_paper_counts": {f"h{l}": quantiles(counts[l]) for l in (1, 2, 3)},
        "h1_num_style": dict(num_styles.most_common()),
        "h1_skeleton": [{"role": r, "papers": h1_papers[r], "titles": h1_roles[r], "share": round(h1_papers[r] / n, 2)}
                        for r in skeleton if h1_papers[r] >= 2],
        "problem_chapter_title_forms": problem_chapter_titles.most_common(15),
        "problem_h2_roles": [{"role": r, "count": c, "per_chapter": round(c / max(n_problem_chapters, 1), 2)}
                             for r, c in problem_h2_roles.most_common()],
        "problem_h2_variants": problem_h2_variants.most_common(60),
        "n_problem_chapters": n_problem_chapters,
        "role_variants": {r: c.most_common(12) for r, c in role_variants.items()},
    }


def norms_md(norms: dict, n_terms: int) -> str:
    L = [f"# FRAME_NORMS — 优秀论文框架与命名规范（n = {norms['n_papers']} 篇，{norms['generated']} 生成，勿手改）", ""]
    L.append("## 标题长度（去编号；汉字计 1、英文词计 1）")
    L.append("")
    L.append("| 级别 | n | P25 | P50 | P75 | P90 | max |")
    L.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for k, q in norms["title_len"].items():
        if q:
            L.append(f"| {k.upper()} | {q['n']} | {q['p25']} | {q['p50']} | {q['p75']} | {q['p90']} | {q['max']} |")
    L += ["", "## 标题里的标点（占全部标题比例）", ""]
    L.append("| " + " | ".join(norms["punct_rate"]) + " |")
    L.append("| " + " | ".join("---:" for _ in norms["punct_rate"]) + " |")
    L.append("| " + " | ".join(f"{v:.1%}" for v in norms["punct_rate"].values()) + " |")
    L += ["", "## 每篇标题数量", ""]
    L.append("| 级别 | P25 | P50 | P75 | P90 | max |")
    L.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for k, q in norms["per_paper_counts"].items():
        if q:
            L.append(f"| {k.upper()} | {q['p25']} | {q['p50']} | {q['p75']} | {q['p90']} | {q['max']} |")
    L += ["", f"## 一级章骨架（按出现位置排序；编号风格 {norms['h1_num_style']}）", ""]
    L.append("| 顺序 | 角色 | 出现篇数 | 占比 |")
    L.append("| ---: | --- | ---: | ---: |")
    for i, s in enumerate(norms["h1_skeleton"], 1):
        L.append(f"| {i} | {s['role']} | {s['papers']} | {s['share']:.0%} |")
    L += ["", "## 问题章一级标题句式（N 代表问题序号）", ""]
    for t, c in norms["problem_chapter_title_forms"]:
        L.append(f"- {c} × {t}")
    L += ["", f"## 问题章内部的二级骨架（共 {norms['n_problem_chapters']} 个问题章）", ""]
    L.append("| 角色 | 次数 | 每章平均 |")
    L.append("| --- | ---: | ---: |")
    for r in norms["problem_h2_roles"]:
        L.append(f"| {r['role']} | {r['count']} | {r['per_chapter']} |")
    L += ["", "### 问题章二级标题高频措辞", ""]
    L.append("、".join(f"{t}({c})" for t, c in norms["problem_h2_variants"][:40]))
    L += ["", "## 各角色在语料中的实际写法（频次）", ""]
    for role, vs in norms["role_variants"].items():
        L.append(f"- **{role}**：" + "、".join(f"{t}({c})" for t, c in vs))
    L += ["", f"## 术语库", "", f"`term_bank.json` 共 {n_terms} 条（正文跨篇 n-gram + 标题词）。"
          "标题中出现术语库之外的连续汉字会被 lint 标为 `term_unrecognized`（INFO，请人工确认是否领域规范术语）。", ""]
    return "\n".join(L)


def main() -> None:
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf_dirs", nargs="+", type=Path)
    ap.add_argument("--year", default="", help="年份标签，写进匿名 id（如 23）")
    ap.add_argument("--out-dir", type=Path, default=REF_DIR)
    ap.add_argument("--min-df", type=int, default=3)
    ap.add_argument("--append", action="store_true", help="保留已有语料中其它 id 的论文与术语（分批喂不同年份时用）")
    a = ap.parse_args()
    if pymupdf is None:
        sys.exit("需要 pymupdf：pip install pymupdf")
    pdfs = sorted(p for d in a.pdf_dirs for p in d.glob("*.pdf"))
    if not pdfs:
        sys.exit("目录下没有 PDF")
    papers: list[dict] = []
    bodies: list[str] = []
    per_problem: Counter = Counter()
    for pdf in pdfs:
        meta, body = extract_paper(pdf)
        per_problem[meta["problem"]] += 1
        meta["id"] = f"{meta['problem']}{a.year}-{per_problem[meta['problem']]:02d}"
        papers.append(meta)
        bodies.append(body)
        n1 = sum(1 for x in meta["outline"] if x[0] == 1)
        print(f"[corpus] {meta['id']:8s} {meta['source']:10s} 标题 {len(meta['outline']):3d}（H1 {n1:2d}） 正文 {len(body):6d} 字")
    out_dir = a.out_dir
    corpus_path = out_dir / "outline_corpus.json"
    old: list[dict] = []
    terms = build_term_bank(bodies, [p["outline"] for p in papers], a.min_df)
    if a.append and corpus_path.exists():
        new_ids = {p["id"] for p in papers}
        old = [p for p in load_json_list(corpus_path) if p["id"] not in new_ids]
        for t, v in load_json(out_dir / "term_bank.json").get("terms", {}).items():
            terms.setdefault(t, v)
    all_papers = old + papers
    norms = build_norms(all_papers)
    dump_json(corpus_path, [{"id": p["id"], "problem": p["problem"], "pages": p["pages"], "source": p["source"],
                             "outline": p["outline"]} for p in all_papers])
    dump_json(out_dir / "term_bank.json", {"meta": {"n_papers": len(all_papers), "min_df": a.min_df,
                                                     "generated": norms["generated"]}, "terms": terms})
    dump_json(out_dir / "FRAME_NORMS.json", norms)
    (out_dir / "FRAME_NORMS.md").write_text(norms_md(norms, len(terms)), encoding="utf-8")
    print(f"[corpus] 论文 {len(all_papers)} 篇，术语 {len(terms)} 条 → {out_dir}")


if __name__ == "__main__":
    main()
