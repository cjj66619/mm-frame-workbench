"""frame_common.py — mm-frame-workbench 各脚本共用：标题解析、编号识别、角色分类、术语切分、语料加载。

只依赖标准库。所有 Markdown 读写显式 UTF-8；标题只认行首 `#`，围栏代码块内的 `#` 不算标题。
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REF_DIR = Path(__file__).resolve().parents[2] / "_references"

CN_DIGITS = "一二三四五六七八九十"
CN2INT = {c: i + 1 for i, c in enumerate(CN_DIGITS)}
CN2INT["十"] = 10

# 行首编号：4 / 4.1 / 4.4.1 / 一、 / 第一章 / （一） / 附录 A / A1 / A.1
RE_ARABIC = re.compile(r"^(?P<num>\d+(?:\.\d+)*)[.、:：]?\s+(?P<title>\S.*)$")
RE_ARABIC_TIGHT = re.compile(r"^(?P<num>\d+(?:\.\d+)+)[.、:：]?(?P<title>[^\d\s].*)$")
RE_CN = re.compile(rf"^第?(?P<num>[{CN_DIGITS}]+)[、.．:：章节部分]*\s*(?P<title>\S.*)$")
RE_CN_PAREN = re.compile(rf"^[（(](?P<num>[{CN_DIGITS}]+)[)）]\s*(?P<title>\S.*)$")
RE_APPENDIX = re.compile(r"^(?P<num>附\s*录\s*[A-Za-z一二三四五六七八九十\d]*)[\s:：.、]*(?P<title>.*)$")
RE_APPENDIX_SUB = re.compile(r"^(?P<num>[A-Z](?:\.?\d+)+)[.、:：]?\s*(?P<title>\S.*)$")

FUNC_WORDS = ("及其", "与", "和", "及", "或", "的", "之", "对", "在", "于", "以", "与其", "其", "各", "按", "逐", "面向", "基于")

PUNCT_WATCH = {"：": "colon", ":": "colon", "“": "quote", "”": "quote", "（": "paren", "）": "paren",
               "(": "paren", ")": "paren", "—": "dash", "–": "dash", "、": "enum", "，": "comma", ",": "comma",
               "/": "slash", "？": "question", "!": "bang", "！": "bang"}


def setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def zh_len(s: str) -> int:
    """标题长度：汉字计 1，连续 ASCII 词计 1（`SHAP`、`XGBoost` 算一个词）。"""
    n = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    n += len(re.findall(r"[A-Za-z][A-Za-z0-9_\-]*", s))
    return n


@dataclass
class Numbering:
    style: str            # arabic | cn | cn_paren | appendix | appendix_sub | none
    raw: str              # 原编号文字，如 "4.4.1"、"一"、"附录 A"、"A1"
    parts: tuple = ()     # 阿拉伯编号的整数元组，如 (4, 4, 1)


def split_number(text: str) -> tuple[Numbering, str]:
    """把标题拆成（编号, 去编号标题）。"""
    t = text.strip()
    m = RE_APPENDIX.match(t)
    if m:
        return Numbering("appendix", re.sub(r"\s+", " ", m.group("num")).strip()), m.group("title").strip()
    m = RE_ARABIC.match(t) or RE_ARABIC_TIGHT.match(t)
    if m:
        parts = tuple(int(x) for x in m.group("num").split("."))
        return Numbering("arabic", m.group("num"), parts), m.group("title").strip()
    m = RE_APPENDIX_SUB.match(t)
    if m:
        return Numbering("appendix_sub", m.group("num")), m.group("title").strip()
    m = RE_CN_PAREN.match(t)
    if m:
        return Numbering("cn_paren", m.group("num")), m.group("title").strip()
    m = RE_CN.match(t)
    if m and m.group("title") and not m.group("title")[0] in "、：:":
        return Numbering("cn", m.group("num")), m.group("title").strip()
    return Numbering("none", ""), t


def strip_number(text: str) -> str:
    return split_number(text)[1]


def punct_kinds(title: str) -> list[str]:
    kinds: list[str] = []
    for ch, kind in PUNCT_WATCH.items():
        if ch in title and kind not in kinds:
            kinds.append(kind)
    return kinds


# ---------------------------------------------------------------- 角色

_ROLES_CACHE: list[dict] | None = None


def load_roles() -> list[dict]:
    global _ROLES_CACHE
    if _ROLES_CACHE is None:
        data = load_json(REF_DIR / "heading_roles.json")
        _ROLES_CACHE = []
        for r in data["roles"]:
            _ROLES_CACHE.append({**r, "_re": [re.compile(p) for p in r["patterns"]]})
    return _ROLES_CACHE


def classify_role(title: str, level: int | None = None) -> str | None:
    """按角色词典给去编号标题分类；level 用于消歧（同一措辞在一级/二级含义不同）。

    strict_level 的角色（问题章、摘要、参考文献、附录）只在其规定层级生效；其余角色优先取同层级命中，
    没有同层级命中时才退到别的层级（如二级标题“模型假设”仍识别为 assumptions）。"""
    s = re.sub(r"\s+", "", title)
    hits: list[dict] = []
    for r in load_roles():
        if level is not None and r.get("strict_level") and r["level"] != level:
            continue
        if any(p.search(s) for p in r["_re"]):
            hits.append(r)
    if not hits:
        return None
    if level is not None:
        same = [r for r in hits if r["level"] == level]
        if same:
            hits = same
    return hits[0]["role"]


# ---------------------------------------------------------------- 术语切分

@dataclass
class TermBank:
    terms: dict[str, dict] = field(default_factory=dict)      # 术语 → {df, tf, kind}
    max_len: int = 8

    @classmethod
    def load(cls, path: Path | None = None) -> "TermBank":
        path = path or REF_DIR / "term_bank.json"
        if not path.exists():
            return cls()
        data = load_json(path)
        bank = cls(terms=data.get("terms", {}))
        bank.max_len = max((len(t) for t in bank.terms), default=8)
        return bank

    def segment(self, title: str) -> list[tuple[str, str]]:
        """最长匹配切分。返回 [(片段, 类型)]，类型：term / ascii / punct / func / unknown / digit。"""
        out: list[tuple[str, str]] = []
        i, n = 0, len(title)
        while i < n:
            ch = title[i]
            if ch.isspace():
                i += 1
                continue
            m = re.match(r"[A-Za-z][A-Za-z0-9_\-\.]*", title[i:])
            if m:
                tok = m.group(0).rstrip(".")
                kind = "term" if tok in self.terms or tok.lower() in self.terms else "ascii"
                out.append((tok, kind))
                i += len(tok)
                continue
            m = re.match(r"\d+(?:\.\d+)?", title[i:])
            if m:
                out.append((m.group(0), "digit"))
                i += len(m.group(0))
                continue
            if not ("\u4e00" <= ch <= "\u9fff"):
                out.append((ch, "punct"))
                i += 1
                continue
            hit = None
            for L in range(min(self.max_len, n - i), 1, -1):
                cand = title[i:i + L]
                if cand in self.terms:
                    hit = cand
                    break
            if hit:
                out.append((hit, "term"))
                i += len(hit)
                continue
            fw = next((w for w in FUNC_WORDS if title.startswith(w, i)), None)
            if fw:
                out.append((fw, "func"))
                i += len(fw)
            else:
                # 收集连续未识别汉字
                j = i
                while j < n and "\u4e00" <= title[j] <= "\u9fff":
                    found = any(title[j:j + L] in self.terms for L in range(min(self.max_len, n - j), 1, -1))
                    if found or (j > i and any(title.startswith(w, j) for w in FUNC_WORDS)):
                        break
                    j += 1
                if j == i:
                    j = i + 1
                out.append((title[i:j], "unknown"))
                i = j
        return out

    def unknown_runs(self, title: str, min_len: int = 2) -> list[str]:
        return [tok for tok, kind in self.segment(title) if kind == "unknown" and len(tok) >= min_len]


# ---------------------------------------------------------------- Markdown 标题遍历

@dataclass
class Heading:
    file: str
    line: int             # 0-based 行号
    level: int
    raw: str              # 不含 # 的完整标题文字
    numbering: Numbering
    title: str            # 去编号

    @property
    def id(self) -> str:
        return f"{self.file}:{self.line + 1}"


def section_order(sections_dir: Path) -> list[Path]:
    """章节顺序：优先 <proj>/paper/paper.yaml 的 sections 列表，否则按文件名排序。"""
    yaml_path = sections_dir.parent / "paper.yaml"
    files = sorted(p for p in sections_dir.glob("*.md"))
    if yaml_path.exists():
        names: list[str] = []
        in_sections = False
        for ln in yaml_path.read_text(encoding="utf-8").splitlines():
            if re.match(r"^sections\s*:", ln):
                in_sections = True
                continue
            if in_sections:
                m = re.match(r"^\s*-\s*(\S+\.md)\s*$", ln)
                if m:
                    names.append(m.group(1))
                elif ln.strip() and not ln.startswith(" "):
                    break
        if names:
            by_name = {p.name: p for p in files}
            ordered = [by_name[n] for n in names if n in by_name]
            ordered += [p for p in files if p.name not in names]
            return ordered
    return files


def iter_headings(md_text: str, file: str) -> list[Heading]:
    out: list[Heading] = []
    in_fence = False
    for i, ln in enumerate(md_text.splitlines()):
        s = ln.rstrip()
        if re.match(r"^\s*(```|~~~)", s):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", s)
        if not m:
            continue
        raw = m.group(2).strip()
        # 去掉 pandoc 属性 {#sec:xxx}
        raw_clean = re.sub(r"\s*\{[^}]*\}\s*$", "", raw)
        num, title = split_number(raw_clean)
        out.append(Heading(file, i, len(m.group(1)), raw_clean, num, title))
    return out


def body_stats(lines: list[str], start: int, end: int) -> dict:
    """统计 [start, end) 行的正文：汉字数、图/表/公式/代码块数。"""
    text = "\n".join(lines[start:end])
    return {
        "zh_chars": sum(1 for c in text if "\u4e00" <= c <= "\u9fff"),
        "figures": len(re.findall(r"!\[", text)),
        "tables": len(re.findall(r"(?m)^\s*\|.*\|\s*$\n\s*\|[\s:\-|]+\|", text)),
        "display_eqs": len(re.findall(r"\$\$", text)) // 2,
        "code_blocks": len(re.findall(r"(?m)^\s*```", text)) // 2,
        "lines": end - start,
    }
