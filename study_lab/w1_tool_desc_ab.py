"""第 1 周实验台：工具描述 A/B（含糊描述 vs 七栏模板）。

跑法（在仓库根目录 smolagents/ 下）：

    python study_lab/w1_tool_desc_ab.py --dry-run          # 不花钱，先看两种描述长什么样
    python study_lab/w1_tool_desc_ab.py --repeat 1         # 先跑 1 轮试水（20 次调用）
    python study_lab/w1_tool_desc_ab.py --repeat 10        # 正式测（200 次调用，注意花费）

每次运行都会在 study_lab/results/ 下落一份 CSV 和一份小结，
小结里那行 markdown 表格可以直接粘进 实验记录.md。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from common import REPO_ROOT, Timer, build_model, cost_of, rule
from tools_refund import CANON, build_tools, describe_all

RESULTS_DIR = Path(__file__).resolve().parent / "results"
QUERIES_FILE = Path(__file__).resolve().parent / "queries.json"


def load_queries(limit: int | None) -> list[dict]:
    data = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    return data[:limit] if limit else data


def first_tool_call(agent) -> tuple[str, dict, bool, str]:
    """从内存里捞出第一次工具调用：工具名、参数、工具是否真被执行、报错。

    为什么不能只看 step.tool_calls：smolagents 在执行前会校验参数，
    参数名对不上 schema 时直接抛错，这一步的 tool_calls 根本不会被写入。
    如果只读 tool_calls，你会把"模型填错参数"误判成"模型没调工具"——
    这正是第 3 章开篇那次事故在观测层面被掩盖的原因。

    所以：优先读 tool_calls（已执行的），退回读 model_output_message.tool_calls（模型的意图）。
    """
    from smolagents.memory import ActionStep

    last_error = ""
    for step in agent.memory.steps:
        if not isinstance(step, ActionStep):
            continue
        if step.error:
            last_error = f"{type(step.error).__name__}: {step.error}"[:200]

        calls = list(step.tool_calls or [])
        if not calls and step.model_output_message is not None:
            calls = list(step.model_output_message.tool_calls or [])

        if calls:
            call = calls[0]
            # 两种对象长得不一样：ToolCall 有 .name，ChatMessageToolCall 是 .function.name
            if hasattr(call, "function"):
                name = call.function.name
                args = call.function.arguments
            else:
                name = call.name
                args = call.arguments
            args = args if isinstance(args, dict) else {}
            if name == "final_answer":  # 直接给答案 = 一个工具都没调
                return "__none__", args, bool(step.tool_calls), last_error
            return name, args, bool(step.tool_calls), last_error
    return "__none__", {}, False, last_error


# 打印时的固定顺序：含糊 -> 规格，再到旧名组、对照、干净条件组
ORDERED_VARIANTS = [
    "vague", "spec",
    "vague_legacy", "spec_legacy",
    "collide", "collide_id",
    "opaque_vague", "opaque_spec",
]

VALID_ARGS = {
    # 每组都额外允许 "id"：干净条件（opaque_*）里三个工具的参数统一叫 id，
    # 那是刻意的设计，不该被记成"参数名错"。
    "query_refund_status": {"refund_id", "id"},
    "query_refund_by_order": {"order_id", "id"},
    "query_order_status": {"order_id", "id"},
}


def judge(called: str, args: dict, q: dict, user_text: str) -> tuple[bool, bool | None, bool | None]:
    """三件事分开判：工具选对没、参数名对不对、参数值对不对。

    合并成一个"对/错"会把最有用的信息（错在哪一层）丢掉。
    参数名"对不对"是相对**它调用的那个工具**的 schema 说的——
    所以往 query_refund_status 里塞 order_id，即使 order_id 本身是本该用的参数，
    这一列也记错：因为对那个工具的 schema 来说它是非法参数，会直接被框架拒掉。
    """
    tool_ok = called == q["expected_tool"]
    if called not in VALID_ARGS:
        return tool_ok, None, None

    arg_key_ok = bool(args) and set(args) <= VALID_ARGS[called]
    if not args:
        return tool_ok, False, False

    got = " ".join(str(v) for v in args.values())
    digits = "".join(ch for ch in got if ch.isdigit())
    query_digits = "".join(ch for ch in user_text if ch.isdigit())
    arg_value_ok = bool(digits) and digits in query_digits
    return tool_ok, arg_key_ok, arg_value_ok


def run_one(agent, q: dict, variant: str) -> dict:
    with Timer() as timer:
        state, error = "success", ""
        try:
            result = agent.run(q["user"], max_steps=1, return_full_result=True)
            state = getattr(result, "state", "success")
            usage = getattr(result, "token_usage", None)
            tin = getattr(usage, "input_tokens", 0) or 0
            tout = getattr(usage, "output_tokens", 0) or 0
        except Exception as exc:  # 网络抖动、限流、key 失效都记一行，不要中断整批
            tin = tout = 0
            error = f"{type(exc).__name__}: {exc}"[:200]
            state = "error"

    called, args, executed, step_error = first_tool_call(agent)
    # 旧名先归一化到规范名，再判定——这样 queries.json 一份题库能同时跑两组工具集
    called_canon = CANON.get(called, called)
    tool_ok, arg_key_ok, arg_value_ok = judge(called_canon, args, q, q["user"])

    return {
        "variant": variant,
        "query_id": q["id"],
        "type": q["type"],
        "user": q["user"],
        "expected_tool": q["expected_tool"],
        "tool_called": called,
        "args": json.dumps(args, ensure_ascii=False),
        "tool_ok": int(tool_ok),
        "arg_key_ok": "" if arg_key_ok is None else int(arg_key_ok),
        "arg_value_ok": "" if arg_value_ok is None else int(arg_value_ok),
        "executed": int(executed),
        "tokens_in": tin,
        "tokens_out": tout,
        "ms": round(timer.ms),
        "state": state,
        "error": error or step_error,
    }


def summarize(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for variant in {r["variant"] for r in rows}:
        rs = [r for r in rows if r["variant"] == variant]
        n = len(rs)
        arg_rows = [r for r in rs if r["arg_key_ok"] != ""]
        out[variant] = {
            "runs": n,
            "tool_acc": sum(r["tool_ok"] for r in rs) / n if n else 0,
            "arg_key_err": sum(1 for r in arg_rows if r["arg_key_ok"] == 0) / len(arg_rows) if arg_rows else 0,
            "arg_val_err": sum(1 for r in arg_rows if r["arg_value_ok"] == 0) / len(arg_rows) if arg_rows else 0,
            "errors": sum(1 for r in rs if r["state"] == "error"),
            "avg_in": sum(r["tokens_in"] for r in rs) / n if n else 0,
            "avg_out": sum(r["tokens_out"] for r in rs) / n if n else 0,
            "avg_ms": sum(r["ms"] for r in rs) / n if n else 0,
            "cost": sum(cost_of(r["tokens_in"], r["tokens_out"]) for r in rs),
            # 该调不调 / 不该调却调，分开看：这两种错的产品含义完全不同
            "miss": sum(1 for r in rs if r["expected_tool"] != "__none__" and r["tool_called"] == "__none__"),
            "over": sum(1 for r in rs if r["expected_tool"] == "__none__" and r["tool_called"] != "__none__"),
            # 参数被 schema 拒绝、工具压根没执行——就是书稿里那个"400 冒泡成服务繁忙"
            "rejected": sum(1 for r in rs if r["tool_called"] != "__none__" and not r["executed"]),
        }
    return out


def print_summary(summary: dict[str, dict]) -> None:
    rule("结果对比")
    header = (
        f"{'描述版本':<14}{'轮次':>6}{'选对率':>9}{'参数名错':>10}{'参数值错':>10}"
        f"{'参数被拒':>10}{'该调不调':>10}{'不该调却调':>12}{'平均输入':>10}{'平均输出':>10}{'平均耗时':>10}"
    )
    print(header)
    print("-" * len(header))
    order = ORDERED_VARIANTS + [v for v in summary if v not in ORDERED_VARIANTS]
    for variant in order:
        if variant not in summary:
            continue
        s = summary[variant]
        print(
            f"{variant:<14}{s['runs']:>6}{s['tool_acc']:>9.0%}{s['arg_key_err']:>10.0%}"
            f"{s['arg_val_err']:>10.0%}{s['rejected']:>10}{s['miss']:>10}{s['over']:>12}"
            f"{s['avg_in']:>10.0f}{s['avg_out']:>10.0f}{s['avg_ms']:>9.0f}ms"
        )
    # 每一对（含糊 vs 规格）单独算提升，别把两组混在一起比
    for vague, spec in (("vague", "spec"), ("vague_legacy", "spec_legacy"), ("opaque_vague", "opaque_spec")):
        if vague in summary and spec in summary:
            gain = summary[spec]["tool_acc"] - summary[vague]["tool_acc"]
            print(f"\n  选对率提升：{gain:+.0%}（{spec} 相对 {vague}）")
            if gain <= 0:
                print("  提升不明显时先别急着改描述——看下面的逐条明细，往往是某个工具的边界还没写清。")


def print_detail(rows: list[dict]) -> None:
    rule("逐条明细（同一问题在两套描述下的不同表现）")
    by_query: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        by_query.setdefault(r["query_id"], {}).setdefault(r["variant"], []).append(r["tool_called"])

    for qid, per_variant in sorted(by_query.items()):
        cells = []
        for variant in ORDERED_VARIANTS:
            calls = per_variant.get(variant, [])
            if not calls:
                continue
            uniq = sorted(set(calls))
            mark = "✓" if len(uniq) == 1 else "≈"
            cells.append(f"{variant}:{mark}{'/'.join(uniq)}")
        print(f"  {qid:<5}{'   '.join(cells)}")


def write_outputs(rows: list[dict], summary: dict[str, dict], tag: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS_DIR / f"w1_{tag}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    md_path = RESULTS_DIR / f"w1_{tag}.md"
    lines = [f"# 第 1 周结果 {tag}", "", "| 描述版本 | 轮次 | 选对率 | 参数名错 | 参数值错 | 平均输入 token | 平均输出 token |", "|---|---|---|---|---|---|---|"]
    for variant in ORDERED_VARIANTS:
        if variant not in summary:
            continue
        s = summary[variant]
        lines.append(
            f"| {variant} | {s['runs']} | {s['tool_acc']:.0%} | {s['arg_key_err']:.0%} | "
            f"{s['arg_val_err']:.0%} | {s['avg_in']:.0f} | {s['avg_out']:.0f} |"
        )

    lines += ["", "## 可直接粘进实验记录.md 的一行", "", "| 日期 | 仓库/分支 | 改了什么 | 期望变化 | 实际变化 | 代价 | 结论 |", "|---|---|---|---|---|---|---|"]
    if "vague" in summary and "spec" in summary:
        v, s = summary["vague"], summary["spec"]
        lines.append(
            f"| {datetime.now():%Y-%m-%d} | smolagents@v1.26.0 / study/w1-tool-desc | "
            f"把三个工具的描述从一句话改写为七栏模板 | 选对率上升、参数名错误下降 | "
            f"选对率 {v['tool_acc']:.0%} → {s['tool_acc']:.0%}；参数名错误 {v['arg_key_err']:.0%} → {s['arg_key_err']:.0%} | "
            f"平均 {(v['avg_in'] + v['avg_out']):.0f} → {(s['avg_in'] + s['avg_out']):.0f} token/次 | "
            f"{'描述确实是产品文档' if s['tool_acc'] > v['tool_acc'] else '差异不显著，需扩大样本或收紧问题'} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n已写入：\n  {csv_path}\n  {md_path}")
    return md_path


def main() -> int:
    ap = argparse.ArgumentParser(description="第 1 周：工具描述 A/B 实验")
    ap.add_argument("--repeat", type=int, default=3, help="每个问题重复几次（书稿建议 10）")
    ap.add_argument("--variants", default="vague,spec", help="vague,spec")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个问题，试水用")
    ap.add_argument("--temp", type=float, default=0.0, help="采样温度，默认 0")
    ap.add_argument("--dry-run", action="store_true", help="只打印两种描述，不调模型")
    args = ap.parse_args()

    queries = load_queries(args.limit)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    if args.dry_run:
        for variant in variants:
            rule(f"{variant} 版本中模型看到的工具描述")
            print(describe_all(variant))
        print(f"共 {len(queries)} 个问题 × {len(variants)} 套描述 × repeat 次调用。")
        return 0

    from smolagents import ToolCallingAgent

    model = build_model(temperature=args.temp)
    total = len(queries) * len(variants) * args.repeat
    print(f"准备跑 {total} 次模型调用（{len(queries)} 问题 × {len(variants)} 描述 × {args.repeat} 轮）")

    rows: list[dict] = []
    for variant in variants:
        for q in queries:
            for i in range(args.repeat):
                agent = ToolCallingAgent(tools=build_tools(variant), model=model, max_steps=1)
                row = run_one(agent, q, variant)
                rows.append(row)
                flag = "✓" if row["tool_ok"] else "✗"
                print(f"  [{variant}] {q['id']} #{i + 1} {flag} -> {row['tool_called']} {row['args']}", flush=True)

    summary = summarize(rows)
    print_summary(summary)
    print_detail(rows)
    write_outputs(rows, summary, datetime.now().strftime("%Y%m%d_%H%M%S"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
