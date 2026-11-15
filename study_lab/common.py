"""实验台公共件：读配置、建模型、算 token 与成本。

为什么单独一个文件：第 2、3、4 周要跑的脚本都从这里拿 model，
换模型只改 .env 一行，不用动任何实验代码——这本身就是"配置外置"的练习。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

# study_lab/common.py -> 仓库根 -> agent-study/
REPO_ROOT = Path(__file__).resolve().parents[1]
STUDY_ROOT = REPO_ROOT.parent
ENV_FILE = STUDY_ROOT / ".env"


def load_env() -> None:
    """把 agent-study/.env 读进环境变量。key 放在仓库外，永远不会被 git 带走。"""
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
    """
    from smolagents import OpenAIModel

    load_env()
    kwargs: dict = {"temperature": temperature}
    if os.getenv("MAX_TOKENS", "").strip():
        kwargs["max_tokens"] = int(os.environ["MAX_TOKENS"])

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
