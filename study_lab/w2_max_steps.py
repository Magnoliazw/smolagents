"""第 2 周实验台：max_steps 扫描（1 / 3 / 6 / 12）。

书稿第 7 章的落点：轮次不是越多越好，找到"再往上加也不涨"的那个点。

跑法（仓库根目录）：

    python study_lab/w2_max_steps.py --steps 1,3,6,12 --repeat 5
    python study_lab/w2_max_steps.py --steps 1,3 --repeat 1     # 试水

这道题故意需要两步：先用订单号换退款单号，再查退款状态。
所以 max_steps=1 必然失败——你要看的是它怎么失败，
以及 3 步之后再加还有没有收益。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from common import Timer, build_model, cost_of, rule
from tools_refund import build_tools

RESULTS_DIR = Path(__file__).resolve().parent / "results"

TASK = "我订单 2025110400777 申请退款了，退款到账了吗？请告诉我当前状态和预计到账日期。"
# 数据里这笔退款是「已到账 / 2025-11-06」，必须真的走完两步才能答对
SUCCESS_KEYS = ("已到账",)


def collect(agent) -> tuple[list[str], int]:
    """按顺序抓出这次运行里所有工具调用，以及用了几个 action step。"""
    from smolagents.memory import ActionStep

    seq: list[str] = []
    steps = 0
    for step in agent.memory.steps:
        if not isinstance(step, ActionStep):
            continue
        steps += 1
        calls = list(step.tool_calls or [])
        if not calls and step.model_output_message is not None:
            calls = list(step.model_output_message.tool_calls or [])
        for call in calls:
            name = call.function.name if hasattr(call, "function") else call.name
            seq.append(name)
    return seq, steps


def run_one(model, max_steps: int) -> dict:
    from smolagents import ToolCallingAgent

    agent = ToolCallingAgent(tools=build_tools("spec"), model=model, max_steps=max_steps)
    with Timer() as timer:
        try:
            result = agent.run(TASK, return_full_result=True)
            answer = str(getattr(result, "output", "") or "")
            state = getattr(result, "state", "")
            usage = getattr(result, "token_usage", None)
            tin, tout = getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0
        except Exception as exc:
            answer, state, tin, tout = f"{type(exc).__name__}: {exc}"[:160], "error", 0, 0

    seq, steps_used = collect(agent)
    success = any(k in answer for k in SUCCESS_KEYS)
    return {
        "max_steps": max_steps,
        "success": int(success),
        "state": state,
        "steps_used": steps_used,
        "tool_seq": " -> ".join(seq),
        "answer": answer[:120].replace("\n", " "),
        "tokens_in": tin,
        "tokens_out": tout,
        "cost": round(cost_of(tin, tout), 4),
        "ms": round(timer.ms),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="1,3,6,12")
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    steps_list = [int(s) for s in args.steps.split(",") if s.strip()]
    model = build_model()
    print(f"任务：{TASK}")
    print(f"计划：{len(steps_list)} 档 × {args.repeat} 轮 = {len(steps_list) * args.repeat} 次调用\n")

    rows = [run_one(model, ms) for ms in steps_list for _ in range(args.repeat)]

    rule("按 max_steps 汇总")
    header = f"{'max_steps':>10}{'轮次':>6}{'成功率':>8}{'平均步数':>9}{'平均输入':>10}{'平均输出':>10}{'平均耗时':>10}{'单次成本':>10}"
    print(header)
    print("-" * len(header))
    for ms in steps_list:
        rs = [r for r in rows if r["max_steps"] == ms]
        n = len(rs)
        print(
            f"{ms:>10}{n:>6}{sum(r['success'] for r in rs) / n:>8.0%}"
            f"{sum(r['steps_used'] for r in rs) / n:>9.1f}"
            f"{sum(r['tokens_in'] for r in rs) / n:>10.0f}{sum(r['tokens_out'] for r in rs) / n:>10.0f}"
            f"{sum(r['ms'] for r in rs) / n:>9.0f}ms{sum(r['cost'] for r in rs) / n:>10.3f}"
        )

    rule("每次运行的轨迹（工具链就是最直接的证据）")
    for r in rows:
        flag = "✓" if r["success"] else "✗"
        seq = r["tool_seq"] or "(未调用工具)"
        print(f"  steps={r['max_steps']:<3} {flag}  {seq:<58} {r['state']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"w2_{tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n已写入 {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
