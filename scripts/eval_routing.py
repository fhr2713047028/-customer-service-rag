"""意图路由评估（阶段十五）：规则路由 vs LLM 路由，同一评估集。

评估集：data/eval/rag_questions.jsonl（76 题）
- needs_db(3) → 期望 structured（查询本人订单/物流数据）
- 其余（kb/no_basis/induce/insufficient/fallback_other）→ 期望 kb

指标：两者准确率、分歧题清单、LLM 路由失败率（真实 DeepSeek 调用，
失败=模型异常或 JSON 解析失败，这些题会回退规则路由）。
用法：
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python -m scripts.eval_routing
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.intent import detect_intents
from app.services.intent_llm import detect_route_llm

EVAL_FILE = Path("data/eval/rag_questions.jsonl")
REPORT_FILE = Path("docs/routing_eval_report.md")

VALID_INTENTS = ("order_status", "logistics", "product_info")


def rule_route(question: str) -> str:
    return "structured" if detect_intents(question) else "kb"


async def run_eval() -> None:
    questions = [
        json.loads(line)
        for line in EVAL_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    rule_correct = 0
    llm_correct = 0
    llm_failed = 0
    disagreements = []

    for q in questions:
        expected = "structured" if q["type"] == "needs_db" else "kb"
        rr = rule_route(q["question"])

        llm_data = await detect_route_llm(q["question"])
        if llm_data is None:
            lr = None
            llm_failed += 1
        else:
            lr = llm_data.get("route")
            # 与 chat_service 一致的容错：structured 但无有效意图 → 视为 kb
            if lr == "structured" and not any(
                i in VALID_INTENTS for i in llm_data.get("intents", [])
            ):
                lr = "kb"

        if rr == expected:
            rule_correct += 1
        if lr == expected:
            llm_correct += 1
        if lr is not None and lr != rr:
            disagreements.append(
                {"id": q["id"], "question": q["question"], "rule": rr, "llm": lr, "expected": expected}
            )

    n = len(questions)
    lines = [
        "# 意图路由评估报告（规则 vs LLM，阶段十五）",
        "",
        f"- 生成时间：{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
        f"- 评估集：{EVAL_FILE}（{n} 题：needs_db 3 题期望 structured，其余期望 kb）",
        "- LLM 路由：真实 DeepSeek，JSON 输出契约 + 容错解析；失败回退规则路由",
        "",
        "## 结果",
        "",
        "| 路由方案 | 准确率 | 失败率 |",
        "|---|---|---|",
        f"| 规则路由 | {rule_correct / n:.1%} | 0%（无外部依赖） |",
        f"| LLM 路由 | {llm_correct / n:.1%} | {llm_failed / n:.1%} |",
        "",
        "## 分歧题清单（两种路由判定不一致）",
        "",
        "| id | 问题 | 规则判定 | LLM 判定 | 期望 |",
        "|---|---|---|---|---|",
    ]
    for d in disagreements:
        lines.append(f"| {d['id']} | {d['question'][:40]} | {d['rule']} | {d['llm']} | {d['expected']} |")
    if not disagreements:
        lines.append("| - | 无分歧 | - | - | - |")

    lines += [
        "",
        "## 结论声明",
        "",
        "- LLM 路由每次请求多一次模型调用（约 1s 延迟、有费用），是否值得启用取决于",
        "  准确率差值与延迟预算；本报告数据供决策，不预设结论。",
        "- 规则路由零成本零延迟且可单测，是当前生产默认（config: router_llm_enabled=false）。",
        "",
    ]
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")

    print(f"规则路由准确率: {rule_correct}/{n} = {rule_correct / n:.1%}")
    print(f"LLM  路由准确率: {llm_correct}/{n} = {llm_correct / n:.1%}（失败 {llm_failed} 题，回退规则）")
    print(f"分歧题数: {len(disagreements)}")
    print(f"报告已写入 {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(run_eval())
