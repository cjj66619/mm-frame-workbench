"""run_frame.py — mm-frame-workbench 一键入口。

用法：
    python run_frame.py <proj> [--src paper/sections] [--apply] [--strict]

阶段：
  1. inventory  paper/sections/*.md → frame/frame_inventory.json
  2. lint       → frame/FRAME_LINT.md + frame/frame_lint.json
  3. plan       若 frame/frame_plan.json 存在：dry-run 校验并渲染 frame/FRAME_PLAN.md（给人审阅）
  4. apply      仅 --apply：写 frame/sections/，再对结果跑 inventory + lint → after_inventory.json / FRAME_LINT_AFTER.md
  5. report     frame/FRAME_REPORT.md

没有 --apply 时永远不写 frame/sections/。frame_plan.json 由人 / Agent 依据 FRAME_LINT.md 手写（见 frame-plan/SKILL.md）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / "frame-inventory" / "scripts"))
from frame_common import setup_stdout  # noqa: E402


def run(script: str, *args: str) -> int:
    skill, name = script.split("/")
    cmd = [sys.executable, str(SKILLS / skill / "scripts" / name), *args]
    return subprocess.run(cmd, check=False).returncode


def main() -> None:
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proj", type=Path)
    ap.add_argument("--src", default="paper/sections")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    proj = a.proj.resolve()
    if not (proj / a.src).is_dir():
        sys.exit(f"找不到 {proj / a.src}")
    strict = ["--strict"] if a.strict else []
    rc = 0
    rc |= run("frame-inventory/inventory_frame.py", str(proj), "--src", a.src)
    rc |= run("frame-lint/lint_frame.py", str(proj), *strict)
    plan = proj / "frame" / "frame_plan.json"
    if plan.exists():
        rc |= run("frame-plan/plan_frame.py", str(proj), *strict)
        if a.apply:
            rc_apply = run("frame-apply/apply_frame.py", str(proj), "--src", a.src, "--strict")
            rc |= rc_apply
            if rc_apply == 0:
                rc |= run("frame-inventory/inventory_frame.py", str(proj), "--src", "frame/sections",
                          "--out", "frame/after_inventory.json")
                rc |= run("frame-lint/lint_frame.py", str(proj), "--inventory", "frame/after_inventory.json",
                          "--out", "frame/FRAME_LINT_AFTER.md", *strict)
    elif a.apply:
        print("[run] 没有 frame/frame_plan.json，跳过 apply")
    rc |= run("frame-report/report_frame.py", str(proj))
    sys.exit(1 if rc else 0)


if __name__ == "__main__":
    main()
