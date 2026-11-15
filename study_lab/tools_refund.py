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
    # 描述里提到的兄弟工具名，必须和当前工具集里真实存在的名字一致，
    # 否则模型会去找一个不存在的工具——这会污染 A/B 结果。
    _NAMES = {k: k for k in ("query_refund_status", "query_refund_by_order", "query_order_status")}

    @property
    def description(self) -> str:
        n = self._NAMES
        return (
            "查询某个退款单当前的处理状态与预计到账时间。\n"
            "何时使用：用户问某笔退款『到账了吗 / 退到哪了 / 什么时候到 / 是不是退失败了』，"
            "且已给出退款单号（RF 开头 11 位，如 RF20251103001）。\n"
            "何时不要使用：用户要发起退款（本工具不能创建退款）；用户只给了订单号（13 位纯数字）"
            f"而没给退款单号，请先用 {n['query_refund_by_order']} 换退款单号；用户问的是订单发货/物流，"
            f"请用 {n['query_order_status']}。\n"
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
    _NAMES = {k: k for k in ("query_refund_status", "query_refund_by_order", "query_order_status")}

    @property
    def description(self) -> str:
        n = self._NAMES
        return (
            "用订单号查出这笔订单对应的退款单号，是查询退款详情的前置步骤。\n"
            "何时使用：用户只提供了订单号（13 位纯数字），却想知道退款进度/退款到账情况。\n"
            f"何时不要使用：用户已经给出 RF 开头的退款单号（直接用 {n['query_refund_status']}，不必多绕一步）；"
            f"用户问的是订单本身的物流或状态（用 {n['query_order_status']}）。\n"
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
    _NAMES = {k: k for k in ("query_refund_status", "query_refund_by_order", "query_order_status")}

    @property
    def description(self) -> str:
        n = self._NAMES
        return (
            "查询订单本身的履约状态（待发货 / 已发货 / 运输中 / 已签收）与物流单号。\n"
            "何时使用：用户问『发货了吗 / 到哪了 / 物流信息』。\n"
            "何时不要使用：用户问的是『钱退了吗 / 退款进度』——这类问题要用 "
            f"{n['query_refund_status']} 或 {n['query_refund_by_order']}。\n"
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


# ------------------------------------------- 第二组：名字故意互相打架的旧接口
#
# 为什么还要多做这一组：
# 用 query_refund_status / query_refund_by_order 这种名字跑，模型光看名字就能选对，
# 描述写得好不好几乎不影响结果——第一轮实测两套描述都是 100%，A/B 直接失效。
# 但真实公司里的工具名往往是历史遗留的：refund_query / order_refund_query / order_query。
# 这三个名字互相"看起来都能用"，选哪个只能靠描述里的『何时使用 / 何时不要使用』。
# 名字一变，描述的价值才显出来。

LEGACY_NAMES = {
    "query_refund_status": "refund_query",
    "query_refund_by_order": "order_refund_query",
    "query_order_status": "order_query",
}

# 旧名 -> 规范名。评测时先归一化，这样同一份 queries.json 能同时判两组。
CANON = {v: k for k, v in LEGACY_NAMES.items()}


class RefundStatusVagueLegacy(RefundStatusVague):
    name = LEGACY_NAMES["query_refund_status"]


class RefundStatusSpecLegacy(RefundStatusSpec):
    name = LEGACY_NAMES["query_refund_status"]
    _NAMES = LEGACY_NAMES


class RefundByOrderVagueLegacy(RefundByOrderVague):
    name = LEGACY_NAMES["query_refund_by_order"]


class RefundByOrderSpecLegacy(RefundByOrderSpec):
    name = LEGACY_NAMES["query_refund_by_order"]
    _NAMES = LEGACY_NAMES


class OrderStatusVagueLegacy(OrderStatusVague):
    name = LEGACY_NAMES["query_order_status"]


class OrderStatusSpecLegacy(OrderStatusSpec):
    name = LEGACY_NAMES["query_order_status"]
    _NAMES = LEGACY_NAMES


# ------------------------------------- 第三组：正对照（用来证明实验台"测得出问题"）
#
# 一组实验如果两臂都是 100%，有两种可能：
#   (a) 描述真的没影响   (b) 实验台根本不灵敏，什么都测不出来
# 这两种情况在结果表上长得一模一样。分不开它们的办法就是加一个"必然会坏"的对照：
# 把两个退款工具的描述写成完全相同，参数说明也相同。模型这时只能瞎猜。
# 如果连这种条件下选对率还是 100%，那实验台就是坏的，前面的结论全部作废。
#
# 这组不参与正式对比，只用来一次性验证"测得出差异"。

COLLIDE_DESC = "查询退款信息。"


class RefundStatusCollide(_RefundStatusBase):
    name = "refund_query"
    description = COLLIDE_DESC
    inputs = {"refund_id": {"type": "string", "description": "单号"}}


class RefundByOrderCollide(_RefundByOrderBase):
    name = "order_refund_query"
    description = COLLIDE_DESC
    inputs = {"order_id": {"type": "string", "description": "单号"}}


class OrderStatusCollide(_OrderStatusBase):
    name = "order_query"
    description = COLLIDE_DESC
    inputs = {"order_id": {"type": "string", "description": "单号"}}


# 更狠的一档：连参数名都统一成 id。
# 上一档把描述写成一样，选对率仍是 100%——因为 refund_id / order_id 这两个参数名
# 本身就在替模型做选择：给了 RF 开头的号，只有一个工具的 schema 接得住。
# 参数名也统一之后，模型才真正没有线索可用。这正是很多历史接口的样子：get_detail(id)。


class RefundStatusCollideId(_RefundStatusBase):
    name = "refund_query"
    description = COLLIDE_DESC
    inputs = {"id": {"type": "string", "description": "单号"}}

    def forward(self, id: str) -> str:  # noqa: A002 - 故意用 id 复刻历史接口
        return super().forward(id)


class RefundByOrderCollideId(_RefundByOrderBase):
    name = "order_refund_query"
    description = COLLIDE_DESC
    inputs = {"id": {"type": "string", "description": "单号"}}

    def forward(self, id: str) -> str:  # noqa: A002
        return super().forward(id)


class OrderStatusCollideId(_OrderStatusBase):
    name = "order_query"
    description = COLLIDE_DESC
    inputs = {"id": {"type": "string", "description": "单号"}}

    def forward(self, id: str) -> str:  # noqa: A002
        return super().forward(id)


# ------------------------------- 第四组：干净条件（名字无意义，只剩描述可用）
#
# 前三轮实测下来，模型在这个工具集上几乎不可能选错，因为线索太多了：
#   1. 工具名 refund_query / order_refund_query 本身就在说明用途
#   2. 参数名 refund_id / order_id 又替它做了一次筛选
#   3. 参数值的格式（RF 开头 vs 13 位数字）再筛一次
# 只要这三条线索在，描述写成什么样都不影响结果——所以 A/B 永远 100%。
#
# 要让"描述"成为唯一变量，就必须把 1、2、3 全部抹掉：
# 工具叫 api_query_a / b / c，参数一律叫 id，值格式也一样。
# 这时模型只能读描述。这才是检验"描述有没有用"的干净条件。

OPAQUE_NAMES = {
    "query_refund_status": "api_query_a",
    "query_refund_by_order": "api_query_b",
    "query_order_status": "api_query_c",
}
CANON |= {v: k for k, v in OPAQUE_NAMES.items()}


class RefundStatusOpaque(_RefundStatusBase):
    name = OPAQUE_NAMES["query_refund_status"]
    description = "查询退款状态。"
    inputs = {"id": {"type": "string", "description": "单号"}}

    def forward(self, id: str) -> str:  # noqa: A002
        return super().forward(id)


class RefundByOrderOpaque(_RefundByOrderBase):
    name = OPAQUE_NAMES["query_refund_by_order"]
    description = "查询订单的退款。"
    inputs = {"id": {"type": "string", "description": "单号"}}

    def forward(self, id: str) -> str:  # noqa: A002
        return super().forward(id)


class OrderStatusOpaque(_OrderStatusBase):
    name = OPAQUE_NAMES["query_order_status"]
    description = "查询订单。"
    inputs = {"id": {"type": "string", "description": "单号"}}

    def forward(self, id: str) -> str:  # noqa: A002
        return super().forward(id)


class RefundStatusOpaqueSpec(RefundStatusSpec):
    name = OPAQUE_NAMES["query_refund_status"]
    inputs = {"id": {"type": "string", "description": "退款单号，必须是 RF 开头 + 10 位数字，例如 RF20251103001。注意：这不是订单号，订单号是 13 位纯数字。"}}
    _NAMES = OPAQUE_NAMES

    def forward(self, id: str) -> str:  # noqa: A002
        return _RefundStatusBase.forward(self, id)


class RefundByOrderOpaqueSpec(RefundByOrderSpec):
    name = OPAQUE_NAMES["query_refund_by_order"]
    inputs = {"id": {"type": "string", "description": "订单号，13 位纯数字，例如 2025110500123。注意：不是 RF 开头的退款单号。"}}
    _NAMES = OPAQUE_NAMES

    def forward(self, id: str) -> str:  # noqa: A002
        return _RefundByOrderBase.forward(self, id)


class OrderStatusOpaqueSpec(OrderStatusSpec):
    name = OPAQUE_NAMES["query_order_status"]
    inputs = {"id": {"type": "string", "description": "订单号，13 位纯数字，例如 2025110600999。"}}
    _NAMES = OPAQUE_NAMES

    def forward(self, id: str) -> str:  # noqa: A002
        return _OrderStatusBase.forward(self, id)


VARIANTS |= {
    "vague_legacy": [RefundStatusVagueLegacy(), RefundByOrderVagueLegacy(), OrderStatusVagueLegacy()],
    "spec_legacy": [RefundStatusSpecLegacy(), RefundByOrderSpecLegacy(), OrderStatusSpecLegacy()],
    # 正对照：描述全同，用来一次性验证"实验台能测出错误"
    "collide": [RefundStatusCollide(), RefundByOrderCollide(), OrderStatusCollide()],
    "collide_id": [RefundStatusCollideId(), RefundByOrderCollideId(), OrderStatusCollideId()],
    # 干净条件：名字、参数名、值格式全部抹平，只剩描述这一个变量
    "opaque_vague": [RefundStatusOpaque(), RefundByOrderOpaque(), OrderStatusOpaque()],
    "opaque_spec": [RefundStatusOpaqueSpec(), RefundByOrderOpaqueSpec(), OrderStatusOpaqueSpec()],
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
