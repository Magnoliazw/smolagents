"""把你的 GitHub fork 接上本地仓库。

本机没有 gh CLI，也没配 GitHub token，所以"点 Fork"这一步只能你在网页上做一次：
    https://github.com/huggingface/smolagents  →  右上角 Fork

Fork 完成后跑：

    python study_lab/setup_fork.py --user <你的GitHub用户名>
    python study_lab/setup_fork.py --user <你的GitHub用户名> --push    # 顺便把学习分支推上去

脚本会先访问一次你的 fork 页面确认真实存在（不存在就 404，不会瞎猜），
再把 origin 指过去。upstream 已经指向 huggingface 官方仓库，不用动。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request

from common import REPO_ROOT


def sh(*args: str) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _ssl_context():
    """Windows 上 Python 走系统证书链时常报 CERTIFICATE_VERIFY_FAILED，
    显式用 certifi 的证书包最省事（certifi 随 requests 一起装好了）。"""
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fork_exists(user: str, repo: str) -> bool | None:
    """用 GitHub API 判定 fork 是否真的存在。返回 True/False/None(无法判定)。

    踩过的坑：对网页发 HEAD 请求时，不存在的仓库也可能回 200（返回的是"未找到"页面），
    所以必须走 API——它老老实实给 404。
    """
    url = f"https://api.github.com/repos/{user}/{repo}"
    req = urllib.request.Request(url, headers={"User-Agent": "study-lab", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
            if data.get("fork") is False:
                print(f"[warn] {user}/{repo} 存在，但 GitHub 上标记为原始仓库而不是 fork。")
                print("       仍然可以用，只是以后给上游提 PR 会麻烦一点。")
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        if exc.code == 403:
            print("[warn] GitHub API 限流了（未登录每小时 60 次），跳过存在性检查。")
            return None
        raise SystemExit(f"[error] 访问 {url} 返回 {exc.code}")
    except Exception as exc:
        print(f"[warn] 无法访问 {url}（{exc}），跳过存在性检查")
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True, help="你的 GitHub 用户名")
    ap.add_argument("--repo", default="smolagents", help="fork 后的仓库名，默认同名")
    ap.add_argument("--push", action="store_true", help="配置完顺手把当前分支推上去")
    args = ap.parse_args()

    exists = fork_exists(args.user, args.repo)
    if exists is False:
        print(f"[x] 没找到 https://github.com/{args.user}/{args.repo}（API 返回 404）")
        print("    先去 https://github.com/huggingface/smolagents 点 Fork，再回来跑这条命令。")
        return 1
    if exists is None:
        print("[!] 无法确认 fork 是否存在，仍然继续配置——推不上去就回来看这一行。")
    fork_url = f"https://github.com/{args.user}/{args.repo}.git"

    code, out = sh("git", "remote", "get-url", "origin")
    if code == 0:
        sh("git", "remote", "set-url", "origin", fork_url)
        print(f"[ok] origin 已更新为 {fork_url}")
    else:
        sh("git", "remote", "add", "origin", fork_url)
        print(f"[ok] origin 已添加 {fork_url}")

    code, out = sh("git", "remote", "get-url", "upstream")
    if code != 0:
        sh("git", "remote", "add", "upstream", "https://github.com/huggingface/smolagents.git")
        print("[ok] upstream 已补上 huggingface/smolagents")
    else:
        print(f"[ok] upstream 保持为 {out}")

    print("\n当前 remote：")
    print(sh("git", "remote", "-v")[1])

    if args.push:
        branch = sh("git", "branch", "--show-current")[1]
        print(f"\n推送 {branch} 到 origin ...")
        code, out = sh("git", "push", "-u", "origin", branch)
        print(out or "(无输出)")
        if code != 0:
            print("[!] 推送失败：多半是没登录 git 凭证，或 fork 还不存在。")
            return code
    else:
        print("下一步（想留备份时）：git push -u origin <当前分支>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
