"""校验《学习地图.md》里的行号还对不对。

第 3 章要按行号读源码，但如果分支从开发分支起、或者你不小心改了 src/，
行号就会整体漂移，学习地图变成一张错的地图——而且它不会报错，你只会读错代码。

这个脚本把"会不会漂"变成一条命令，分两层判断：

  第一层：src/ 和 v1.26.0 有没有差异。
          没差异 → 行号必然有效，这一层就够了（最快，也是 99% 的情况）。
  第二层：既然可能改过，就逐条核对"这一行的内容里有没有那个符号"。
          对不上时，会在全文里找到它现在真正在第几行。

用法：
    python study_lab/verify_line_map.py            # 完整校验
    python study_lab/verify_line_map.py --quiet    # 只报错的
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from common import REPO_ROOT, STUDY_ROOT

MAP_FILE = STUDY_ROOT / "学习地图.md"
SRC_DIR = REPO_ROOT / "src" / "smolagents"
BASE_TAG = "v1.26.0"

# `tools.py:1061` `def tool()` 这种形式；yaml 没有行号，自然不会被匹配
ENTRY_RE = re.compile(r"`([\w/]+\.py):(\d+)`\s*`([^`]*)`")
# 从符号描述里挑出可搜索的标识符；去掉 Python 关键字和太短的词
KEYWORDS = {
    "def", "class", "if", "while", "return", "not", "and", "or", "for", "in",
    "is", "none", "true", "false", "else", "elif", "with", "as", "pass",
}


def symbols_in(desc: str) -> list[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", desc)
    return [w for w in words if w.lower() not in KEYWORDS]


def src_is_pristine() -> tuple[bool, str]:
    """src/ 是否与基线 tag 完全一致。返回 (是否干净, 说明)。"""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", BASE_TAG, "--", "src/smolagents"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:
        return False, f"无法执行 git（{exc}）"
    if out.returncode != 0:
        return False, f"git 返回 {out.returncode}：{out.stderr.strip()[:120]}"
    changed = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if changed:
        return False, f"{len(changed)} 个源文件与 {BASE_TAG} 不同：" + "、".join(
            Path(c).name for c in changed[:5]
        )
    return True, f"src/smolagents 与 {BASE_TAG} 完全一致"


def check_entry(rel_path: str, lineno: int, desc: str) -> tuple[str, str]:
    """返回 (状态, 说明)。状态：ok / shift / missing_file / no_symbol。"""
    path = SRC_DIR / rel_path
    if not path.exists():
        return "missing_file", f"找不到 {rel_path}"

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if lineno > len(lines):
        return "shift", f"{rel_path} 只有 {len(lines)} 行，记录的是第 {lineno} 行"

    words = symbols_in(desc)
    if not words:
        return "no_symbol", f"`{desc}` 里提取不到可搜索的符号，跳过人工确认"

    actual = lines[lineno - 1]
    hit = [w for w in words if w in actual]
    if hit:
        return "ok", actual.strip()[:70]

    # 这行对不上，去全文找它现在真正在哪。
    # 优先找"定义行"（class X / def X），否则会先命中 __all__ 里的字符串，
    # 给出一个看着像答案、其实是错的位置。
    fallback = ""
    for word in sorted(words, key=len, reverse=True):
        for i, text in enumerate(lines, start=1):
            stripped = text.strip()
            if re.match(rf"(class|def|async def)\s+{re.escape(word)}\b", stripped):
                return "shift", f"`{word}` 定义在 {rel_path}:{i}（记录是 {lineno}）：{stripped[:60]}"
        if not fallback:
            for i, text in enumerate(lines, start=1):
                if word in text:
                    fallback = f"`{word}` 首次出现在 {rel_path}:{i}（记录是 {lineno}），该行：{text.strip()[:56]}"
                    break
    if fallback:
        return "shift", fallback
    return "shift", f"全文都找不到 {words}，可能函数被改名或删除了"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只打印有问题的条目")
    args = ap.parse_args()

    if not MAP_FILE.exists():
        print(f"[error] 找不到 {MAP_FILE}")
        return 1

    text = MAP_FILE.read_text(encoding="utf-8")
    entries = [(m.group(1), int(m.group(2)), m.group(3)) for m in ENTRY_RE.finditer(text)]
    if not entries:
        print("[error] 学习地图里没解析到任何 `文件.py:行号` 条目，检查格式是否被改")
        return 1

    pristine, note = src_is_pristine()

    print("=" * 72)
    print(f"行号校验 · 基线 {BASE_TAG}")
    print(f"条目：{len(entries)} 条")
    if pristine:
        print(f"第一层：{note}")
        print("        → 源码没被动过，地图上的行号一定有效（下面再抽样核对内容）")
    else:
        print(f"第一层：{note}")
        print("        → 源码动过了，行号可能整体漂移，逐条核对就是必须的")

    problems = 0
    checked = 0
    for rel_path, lineno, desc in entries:
        status, detail = check_entry(rel_path, lineno, desc)
        if status == "no_symbol":
            if not args.quiet:
                print(f"  [--] {rel_path}:{lineno}  {detail}")
            continue
        checked += 1
        if status == "ok":
            if not args.quiet:
                print(f"  [OK] {rel_path}:{lineno}  {detail}")
        else:
            problems += 1
            print(f"  [!!] {rel_path}:{lineno}  {detail}")

    print("-" * 72)
    if problems == 0:
        print(f"结论：{checked} 条全部对得上。可以按学习地图读代码了。")
    else:
        print(f"结论：{problems} 条对不上。按上面的『实际在』那一行去改，或者切回 {BASE_TAG} 重读。")
        print(f"      确认当前分支：git describe --tags      # 应为 {BASE_TAG}-N-gXXXXXXX")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
