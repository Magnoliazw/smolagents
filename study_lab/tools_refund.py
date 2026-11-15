"""教学用「退款客服」工具集：两个极易混淆的工具 + 一个干扰工具。

第 3 章开篇那次事故的复刻：模型选对了工具名，但把 order_id 填进了 refund_id。

关键设计：同一个工具准备了 VAGUE / SPEC 两套描述。
- VAGUE = 现实里团队最常见的写法（一句话，参数只写类型）
- SPEC  = 书稿 3.2 的七栏模板（含"何时不该用"和"参数的业务含义"）

两者只有 description / inputs 里的说明文字不同，forward 完全一样。
这样跑出来的差异，只能归因到"描述"，不能归因到代码。
"""

from __future__ import annotations

import re

from smolagents import Tool

# ---------------------------------------------------------------- 假数据

REFUNDS: dict[str, dict] = {
    "RF20251103001": {"status": "已到账", "eta": "2025-11-04", "reason": None},
    "RF20251107042": {"status": "处理中", "eta": "2025-11-18", "reason": None},
    "RF20251101008": {"status": "已退回", "eta": None, "reason": "原银行卡已注销，款项退回失败"},
    "RF20251102003": {"status": "已到账", "eta": "2025-11-03", "reason": None},
    "RF20251105001": {"status": "处理中", "eta": "2025-11-17", "reason": None},
    "RF20251104077": {"status": "已到账", "eta": "2025-11-06", "reason": None},
    "RF20251108088": {"status": "处理中", "eta": "2025-11-19", "reason": None},
}

ORDERS: dict[str, dict] = {
    "2025110500123": {"refund_id": "RF20251105001", "order_status": "已签收"},
    "2025110400777": {"refund_id": "RF20251104077", "order_status": "已签收"},
    "2025110800888": {"refund_id": "RF20251108088", "order_status": "运输中"},
    "2025110600999": {"refund_id": None, "order_status": "已发货，顺丰 SF1234567890"},
    "2025110300222": {"refund_id": None, "order_status": "待发货"},
}


def _norm(value: str) -> str:
    """把 『RF 20251102003』『rf20251102003 』统一成 RF20251102003。"""
    compact = re.sub(r"\s+", "", str(value or "")).upper()
    if compact and not compact.startswith("RF") and len(re.sub(r"\D", "", compact)) == 11:
        compact = "RF" + compact
    return compact


# ------------------------------------------------- 工具一：查退款单状态


class _RefundStatusBase(Tool):
    name = "query_refund_status"
    output_type = "string"

    def forward(self, refund_id: str) -> str:
        rec = REFUNDS.get(_norm(refund_id))
        if rec is None:
            return (
                f"未找到退款单 {refund_id}。请核对单号是否为 RF 开头的退款单号；"
                "若只有订单号，请改用 query_refund_by_order 查询。"
            )
        if rec["reason"]:
            return f"状态：{rec['status']}；失败原因：{rec['reason']}"
        return f"状态：{rec['status']}；预计到账：{rec['eta']}"


class RefundStatusVague(_RefundStatusBase):
    description = "查询退款状态。"
    inputs = {"refund_id": {"type": "string", "description": "退款单号"}}


class RefundStatusSpec(_RefundStatusBase):
    description = (
        "查询某个退款单当前的处理状态与预计到账时间。\n"
        "何时使用：用户问某笔退款『到账了吗 / 退到哪了 / 什么时候到 / 是不是退失败了』，"
        "且已给出退款单号（RF 开头 11 位，如 RF20251103001）。\n"
        "何时不要使用：用户要发起退款（本工具不能创建退款）；用户只给了订单号（13 位纯数字）"
        "而没给退款单号，请先用 query_refund_by_order 换退款单号；用户问的是订单发货/物流，"
        "请用 query_order_status。\n"
        "失败语义：单号不存在会返回『未找到该退款单』，此时应请用户核对单号，不要重复调用。"
    )
    inputs = {
        "refund_id": {
            "type": "string",
            "description": "退款单号，必须是 RF 开头 + 10 位数字，例如 RF20251103001。注意：这不是订单号，订单号是 13 位纯数字。",
        }
    }


# ------------------------------------------- 工具二：订单号换退款单号


class _RefundByOrderBase(Tool):
    name = "query_refund_by_order"
    output_type = "string"

    def forward(self, order_id: str) -> str:
        key = re.sub(r"\D", "", str(order_id or ""))
        rec = ORDERS.get(key)
        if rec is None:
            return f"未找到订单 {order_id}，请让用户核对订单号。"
        if not rec["refund_id"]:
            return f"订单 {key} 没有申请过退款。若用户要发起退款，应引导其走售后入口。"
        return f"订单 {key} 对应的退款单号：{rec['refund_id']}"


class RefundByOrderVague(_RefundByOrderBase):
    description = "查询订单的退款。"
    inputs = {"order_id": {"type": "string", "description": "订单号"}}


class RefundByOrderSpec(_RefundByOrderBase):
    description = (
        "用订单号查出这笔订单对应的退款单号，是查询退款详情的前置步骤。\n"
        "何时使用：用户只提供了订单号（13 位纯数字），却想知道退款进度/退款到账情况。\n"
        "何时不要使用：用户已经给出 RF 开头的退款单号（直接用 query_refund_status，不必多绕一步）；"
        "用户问的是订单本身的物流或状态（用 query_order_status）。\n"
        "返回：退款单号（RF 开头）；若该订单没申请过退款，会明确说明。\n"
        "失败语义：订单号不存在会返回『未找到订单』，此时请用户核对，不要重复调用。"
    )
    inputs = {
        "order_id": {
            "type": "string",
            "description": "订单号，13 位纯数字，例如 2025110500123。注意：不是 RF 开头的退款单号。",
        }
    }


# -------------------------------------------------- 工具三：订单状态（干扰项）


class _OrderStatusBase(Tool):
    name = "query_order_status"
    output_type = "string"

    def forward(self, order_id: str) -> str:
        key = re.sub(r"\D", "", str(order_id or ""))
        rec = ORDERS.get(key)
        if rec is None:
            return f"未找到订单 {order_id}。"
        return f"订单 {key} 状态：{rec['order_status']}"


class OrderStatusVague(_OrderStatusBase):
    description = "查询订单。"
    inputs = {"order_id": {"type": "string", "description": "订单号"}}


class OrderStatusSpec(_OrderStatusBase):
    description = (
        "查询订单本身的履约状态（待发货 / 已发货 / 运输中 / 已签收）与物流单号。\n"
        "何时使用：用户问『发货了吗 / 到哪了 / 物流信息』。\n"
        "何时不要使用：用户问的是『钱退了吗 / 退款进度』——这类问题要用 query_refund_status 或 query_refund_by_order。\n"
        "失败语义：订单号不存在会返回『未找到订单』，请用户核对。"
    )
    inputs = {
        "order_id": {
            "type": "string",
            "description": "订单号，13 位纯数字，例如 2025110600999。",
        }
    }


VARIANTS = {
    "vague": [RefundStatusVague(), RefundByOrderVague(), OrderStatusVague()],
    "spec": [RefundStatusSpec(), RefundByOrderSpec(), OrderStatusSpec()],
}


def build_tools(variant: str) -> list[Tool]:
    """variant: 'vague' | 'spec'。每次返回新实例，避免上一轮的调用状态串味。"""
    if variant not in VARIANTS:
        raise SystemExit(f"variant 只能是 {list(VARIANTS)}，收到 {variant!r}")
    return [type(t)() for t in VARIANTS[variant]]


def describe_all(variant: str) -> str:
    """把 agent 实际看到的工具描述原样打印出来——这是"遮住代码看描述"的自查动作。"""
    lines = []
    for t in build_tools(variant):
        lines.append(f"### {t.name}")
        lines.append(f"description:\n{t.description}")
        for arg, spec in t.inputs.items():
            lines.append(f"  - {arg} ({spec.get('type')}): {spec.get('description')}")
        lines.append("")
    return "\n".join(lines)
