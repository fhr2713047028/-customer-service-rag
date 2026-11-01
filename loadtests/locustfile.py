"""Locust 压测脚本（阶段十二）。

四类任务按 60/25/10/5 权重（人为设定假设，非真实流量）：
- BusinessUser(60%)：订单/物流/商品查询 —— 不调用任何模型；
- RetrievalUser(25%)：政策问题 chat —— 检索链路（LLM 是否调用取决于目标环境配置，
  检索压测时目标实例用 LLM_PROVIDER=mock 隔离）；
- RagUser(10%)：完整 RAG —— 真实 DeepSeek（或明确标注 Mock）；
- MixedUser(5%)：组合查询 + 异常场景（404/401）。

防重复计数：每个 @task 恰好发起一次 HTTP 请求，四类 User 互斥不共享任务。
实际请求分布从测试结果反算记录（每个 endpoint 独立统计）。
"""
import json
import os
from pathlib import Path

from locust import HttpUser, between, events, task

# 压测数据由 scripts/prepare_perf_data.py 预生成（locust 的 gevent 环境
# 无法运行 asyncio，因此不在 on_start 里连数据库）
_PERF_DATA_PATH = Path("results/perf_data.json")

_ORDER_NOS: list[str] = []
_TRACKING_NOS: list[str] = []
_PRODUCT_KEYWORDS: list[str] = ["耳机", "保温", "咖啡", "沙发", "手表", "键盘"]
_TOKEN: str = ""

KB_QUESTIONS = [
    "退货需要什么条件",
    "退款什么时候到账",
    "快递一直不更新怎么办",
    "商品坏了能不能维修",
    "怎么申请开发票",
]
MIXED_QUESTIONS = ["我的订单符合退货条件吗", "我的订单到哪里了？"]


def _prepare():
    """从预生成 JSON 加载测试数据（纯文件 IO，无 asyncio/DB）。"""
    global _TOKEN
    data = json.loads(_PERF_DATA_PATH.read_text(encoding="utf-8"))
    _TOKEN = data["token"]
    _ORDER_NOS.extend(data["order_nos"])
    _TRACKING_NOS.extend(data["tracking_nos"])


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_TOKEN}"}


class BusinessUser(HttpUser):
    """60%：订单、物流、商品查询（无模型调用）。"""

    weight = 60
    wait_time = between(0.1, 0.5)

    def on_start(self):
        if not _ORDER_NOS:
            _prepare()
        import random as r

        self.random = r.Random()

    @task(4)
    def order_list(self):
        self.client.get("/api/v1/orders?page=1&page_size=10", headers=_auth_headers(), name="business_orders_list")

    @task(3)
    def order_detail(self):
        no = self.random.choice(_ORDER_NOS)
        self.client.get(f"/api/v1/orders/{no}", headers=_auth_headers(), name="business_order_detail")

    @task(2)
    def logistics(self):
        no = self.random.choice(_TRACKING_NOS)
        self.client.get(f"/api/v1/logistics/{no}", headers=_auth_headers(), name="business_logistics")

    @task(3)
    def product_search(self):
        kw = self.random.choice(_PRODUCT_KEYWORDS)
        self.client.get(f"/api/v1/products?keyword={kw}", name="business_product_search")


class RetrievalUser(HttpUser):
    """25%：FAQ 政策检索（chat 知识库路径；检索压测时目标实例应配 Mock LLM）。"""

    weight = 25
    wait_time = between(0.2, 0.8)

    def on_start(self):
        if not _ORDER_NOS:
            _prepare()
        import random as r

        self.random = r.Random()

    @task(1)
    def kb_retrieval(self):
        q = self.random.choice(KB_QUESTIONS)
        self.client.post(
            "/api/v1/chat",
            json={"message": q},
            headers=_auth_headers(),
            name="retrieval_kb_chat",
        )


class RagUser(HttpUser):
    """10%：完整 RAG（真实 DeepSeek —— 目标实例 LLM_PROVIDER=openai）。"""

    weight = 10
    wait_time = between(1, 3)

    def on_start(self):
        if not _ORDER_NOS:
            _prepare()
        import random as r

        self.random = r.Random()

    @task(1)
    def full_rag(self):
        q = self.random.choice(KB_QUESTIONS)
        self.client.post(
            "/api/v1/chat",
            json={"message": q},
            headers=_auth_headers(),
            name="rag_full_chat",
        )


class MixedUser(HttpUser):
    """5%：组合问题 + 异常场景（404/401）。"""

    weight = 5
    wait_time = between(0.5, 1.5)

    def on_start(self):
        if not _ORDER_NOS:
            _prepare()
        import random as r

        self.random = r.Random()

    @task(2)
    def combined(self):
        q = self.random.choice(MIXED_QUESTIONS)
        self.client.post(
            "/api/v1/chat",
            json={"message": q},
            headers=_auth_headers(),
            name="mixed_combined_chat",
        )

    @task(1)
    def order_404(self):
        self.client.get("/api/v1/orders/SYNNOTEXIST99", headers=_auth_headers(), name="mixed_order_404")

    @task(1)
    def no_token_401(self):
        self.client.get("/api/v1/orders", name="mixed_no_token_401")


# 按 LOCUST_ONLY 环境变量只保留指定 User 类（三类性能测试分开跑）
_ONLY = os.environ.get("LOCUST_ONLY", "")
if _ONLY:
    for _name in list(globals()):
        _cls = globals()[_name]
        if (
            isinstance(_cls, type)
            and issubclass(_cls, HttpUser)
            and _cls is not HttpUser
            and _name != _ONLY
        ):
            del globals()[_name]


@events.test_stop.add_listener
def _on_test_stop(environment, **kwargs):
    """测试结束：输出每个端点的 P50/P95/P99 与请求数/错误数到 JSON（供报告引用）。"""
    import json
    from pathlib import Path

    stats = environment.stats
    out = []
    for name, entry in sorted(stats.entries.items()):
        out.append(
            {
                "name": name,
                "requests": entry.num_requests,
                "failures": entry.num_failures,
                "p50_ms": round(entry.response_times.percentile(0.5) or 0, 1),
                "p95_ms": round(entry.response_times.percentile(0.95) or 0, 1),
                "p99_ms": round(entry.response_times.percentile(0.99) or 0, 1),
                "avg_ms": round(entry.avg_response_time or 0, 1),
                "rps": round(entry.total_rps or 0, 2),
            }
        )
    total = {
        "requests": stats.total.num_requests,
        "failures": stats.total.num_failures,
        "rps": round(stats.total.total_rps, 2),
    }
    Path("results").mkdir(exist_ok=True)
    Path("results/last_run_summary.json").write_text(
        json.dumps({"total": total, "endpoints": out}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n=== 压测摘要 ===\n" + json.dumps({"total": total, "endpoints": out}, ensure_ascii=False, indent=2))
