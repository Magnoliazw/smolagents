"""开工前自检：先确认"实验台本身是好的"，再去花 token。

两种模式：

    python study_lab/check_env.py --offline   # 不联网、不花钱：用假模型跑通整条链路
    python study_lab/check_env.py             # 联网：真调一次模型，确认 key/base/model 都对

--offline 之所以重要：如果链路有问题，你在 200 次真实调用之后才发现，
就会把"管道漏水"误读成"描述没写好"。
"""

from __future__ import annotations

import argparse
import sys

from common import build_model, load_env, rule
from tools_refund import build_tools, describe_all
from w1_tool_desc_ab import first_tool_call, judge


def offline_test() -> bool:
    """用一个"只会照着台词念"的假模型，验证 agent→工具→判定 这条链路。"""
    from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole, Model
    from smolagents import ToolCallingAgent

    seen_tools: list[str] = []

    class CannedModel(Model):
        """故意复刻第 3 章开篇的事故：工具选对，但参数填了 order_id。"""

        def generate(self, messages, tools_to_call_from=None, stop_sequences=None, **kwargs):
            if tools_to_call_from:
                seen_tools.extend(t.name for t in tools_to_call_from)
            return ChatMessage(
                role=MessageRole.ASSISTANT,
                content="我查一下。",
                tool_calls=[
                    ChatMessageToolCall(
                        id="call_0",
                        type="function",
                        function=ChatMessageToolCallFunction(
                            name="query_refund_status",
                            arguments={"order_id": "2025110500123"},
                        ),
                    )
                ],
            )

    q = {"id": "SELF", "user": "订单 2025110500123 的退款到账了吗", "expected_tool": "query_refund_by_order", "expected_arg": "order_id"}
    agent = ToolCallingAgent(tools=build_tools("vague"), model=CannedModel(), max_steps=1)
    try:
        agent.run(q["user"], max_steps=1, return_full_result=True)
    except Exception:
        pass  # max_steps=1 必然以"没给出最终答案"收尾，判定只看第 1 步

    called, args, executed, step_error = first_tool_call(agent)
    tool_ok, arg_key_ok, arg_value_ok = judge(called, args, q, q["user"])

    print(f"  模型看到的工具：{seen_tools}")
    print(f"  抓到第一次调用：{called} {args}")
    print(f"  工具是否真被执行：{executed}（应为 False——参数名对不上 schema，被框架拦下了）")
    print(f"  框架报的错：{step_error[:80]}")
    print(f"  判定：选对工具={tool_ok}（应为 False，因为它该用 by_order）")
    print(f"        参数名对={arg_key_ok}（应为 False）  参数值可追溯={arg_value_ok}（应为 True）")

    ok = (
        len(seen_tools) == 4  # 三个业务工具 + final_answer
        and called == "query_refund_status"
        and tool_ok is False
        and arg_key_ok is False
        and arg_value_ok is True
        and executed is False
    )
    print(f"  自检结果：{'通过 —— 链路、工具注册、判定逻辑都对' if ok else '不通过，先别跑真实实验'}")
    return ok


def online_test() -> bool:
    from smolagents import ToolCallingAgent

    load_env()
    rule("联网自检：真调一次模型")
    model = build_model()
    agent = ToolCallingAgent(tools=build_tools("spec"), model=model, max_steps=1)
    q = "我上周那笔退款 RF20251103001 到账了没"
    try:
        result = agent.run(q, max_steps=1, return_full_result=True)
    except Exception as exc:
        print(f"  调用失败：{type(exc).__name__}: {exc}")
        print("  检查 .env 里的 MODEL_ID / API_BASE / API_KEY，以及网络能不能出去。")
        return False
    called, args, executed, _ = first_tool_call(agent)
    usage = getattr(result, "token_usage", None)
    print(f"  问题：{q}")
    print(f"  模型调用：{called} {args}（执行={executed}）")
    print(f"  token：输入 {getattr(usage, 'input_tokens', 0)} / 输出 {getattr(usage, 'output_tokens', 0)}")
    print("  通了——可以跑 study_lab/w1_tool_desc_ab.py 了")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="不联网，用假模型验证链路")
    args = ap.parse_args()

    rule("工具清单：spec 版本（模型真正读到的文本）")
    print(describe_all("spec")[:1200])

    if args.offline:
        rule("离线链路自检")
        return 0 if offline_test() else 1

    return 0 if online_test() else 1


if __name__ == "__main__":
    sys.exit(main())
