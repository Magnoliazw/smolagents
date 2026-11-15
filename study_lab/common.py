"""实验台公共件：读配置、建模型、算 token 与成本。

为什么单独一个文件：第 2、3、4 周要跑的脚本都从这里拿 model，
换模型只改 .env 一行，不用动任何实验代码——这本身就是"配置外置"的练习。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

# study_lab/common.py -> 仓库根 -> 工作区根（D:\AI trial\workbuddy）
REPO_ROOT = Path(__file__).resolve().parents[1]
STUDY_ROOT = REPO_ROOT.parent
ENV_FILE = STUDY_ROOT / ".env"
VENV_PY = STUDY_ROOT / ".venv" / "Scripts" / "python.exe"


def _check_interpreter() -> None:
    """被"错误的 Python"跑起来时，先讲人话，而不是抛 ModuleNotFoundError。

    这台机器上 `python` 会先命中 WorkBuddy 自带的 3.13，那里面没有 smolagents。
    直接报 traceback 会让人以为环境坏了，其实只是解释器选错了。
    """
    if importlib.util.find_spec("smolagents") is not None:
        return

    rel = (
        f"..\\.venv\\Scripts\\python.exe study_lab\\{Path(sys.argv[0]).name}"
        if Path(sys.argv[0]).suffix == ".py"
        else "..\\.venv\\Scripts\\python.exe <脚本>"
    )
    raise SystemExit(
        "\n[错误] 你用的不是本项目的 Python，所以找不到 smolagents。\n\n"
        f"  当前解释器：{sys.executable}\n"
        f"  版本：{sys.version.split()[0]}\n"
        f"  应该用：{VENV_PY}\n\n"
        "两种改法，选一个：\n"
        f"  1) 直接用 venv 的解释器（最省事）：\n     {rel} --offline\n\n"
        "  2) 先激活再跑（激活成功后提示符前会多出 (.venv)）：\n"
        "     ..\\.venv\\Scripts\\Activate.ps1\n"
        "     python study_lab\\check_env.py --offline\n"
    )


_check_interpreter()


def load_env() -> None:
    """把工作区根目录的 .env 读进环境变量。key 放在仓库外，永远不会被 git 带走。"""
    from dotenv import load_dotenv  # 放在函数内：本文件要能在缺依赖时先给出解释器提示

    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)
    else:
        print(f"[warn] 没找到 {ENV_FILE}，请复制 .env.example 为 .env 再填 key")


def _need(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise SystemExit(
            f"[error] .env 里缺少 {key}。\n"
            f"        先把 {STUDY_ROOT / '.env.example'} 复制成 {ENV_FILE}，再填上你的模型信息。"
        )
    return value


def build_model(temperature: float = 0.0):
    """建一个 OpenAI 兼容的模型客户端。

    为什么要 temperature=0：第 1 周要比的是"两种描述"的差异，
    不是采样的随机性。想观察随机性就把 --temp 调高，别混在一起。

    关于 tool_choice（踩过的坑，值得记住）：
    smolagents 的 OpenAIModel 默认发 tool_choice="required"（models.py:510），
    意思是"这一步你必须调工具"。但推理型模型（本机的 deepseek-flash 就是）
    不接受这个值，直接回 400：
        Thinking mode does not support this tool_choice
    这个 400 会一路冒泡成 AgentGenerationError，看上去像"环境坏了"，
    其实只是框架默认值和这个模型的约束撞了。这里用 .env 的 TOOL_CHOICE 覆盖它，
    默认 auto；填 none 则用 REMOVE_PARAMETER 把参数彻底摘掉。
    """
    from smolagents import OpenAIModel
    from smolagents.models import REMOVE_PARAMETER

    load_env()
    kwargs: dict = {"temperature": temperature}
    if os.getenv("MAX_TOKENS", "").strip():
        kwargs["max_tokens"] = int(os.environ["MAX_TOKENS"])

    choice = os.getenv("TOOL_CHOICE", "auto").strip().lower()
    if choice in ("none", "off", "remove"):
        kwargs["tool_choice"] = REMOVE_PARAMETER
    elif choice:
        kwargs["tool_choice"] = choice

    return OpenAIModel(
        model_id=_need("MODEL_ID"),
        api_base=os.getenv("API_BASE") or None,
        api_key=_need("API_KEY"),
        **kwargs,
    )


def price_per_1m() -> tuple[float, float]:
    """返回 (输入价, 输出价)，单位：元 / 百万 token。填 0 表示不算钱。"""
    def _num(key: str) -> float:
        try:
            return float(os.getenv(key, "0") or 0)
        except ValueError:
            return 0.0

    return _num("PRICE_IN"), _num("PRICE_OUT")


def cost_of(input_tokens: int, output_tokens: int) -> float:
    pi, po = price_per_1m()
    return input_tokens / 1_000_000 * pi + output_tokens / 1_000_000 * po


class Timer:
    """给每次调用计毫秒，第 8 章比对延迟时用得上。"""

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self.t0) * 1000
        return False


def rule(title: str = "") -> None:
    print("\n" + "=" * 72 + (f"\n{title}" if title else ""))
