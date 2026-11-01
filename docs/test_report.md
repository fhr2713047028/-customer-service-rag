# 测试报告

> 生成时间：2026-11-01 ｜ 当前测试总数：**124 个用例，全部通过**（`pytest -q`，真实结果）

## 1. 测试全景

| 类别 | 内容 | 典型用例 |
|---|---|---|
| **单元测试（纯函数）** | 业务规则（状态推导/一致性校验）、重试策略（分类/退避/抖动）、jieba 分词与 tsquery、RRF 融合（官方示例验证+去重+k 常数）、脱敏、JWT、提示词（注入防护）、文档处理（解析/清洗/分块/元数据）、Embedding 客户端（确定性/维度/单位向量） | 40+ |
| **集成测试（真实数据库 + ASGI）** | 认证四态（无/坏/过期/有效）、**越权强制项**（用户 B 查 A 订单 → 404 无泄露）、脱敏断言、分页校验、知识库入库幂等、向量检索往返、智能路由 8 场景、query_logs 落库 | 40+ |
| **故障注入测试（MockTransport，零生产调用）** | LLM/Embedding 超时、429 限流、5xx、4xx 不重试、维度不匹配拒写、LLM 降级（degraded≠generated）、Embedding 降级（关键词兜底+标注）、数据库不可用（503/50002 不泄露） | 20+ |
| **并发与指标测试** | 15 并发全 200、/metrics 指标族、低基数红线（无 request_id 标签、路由模板、无具体订单号） | 5 |

## 2. 检索评估（独立评估集，非单元测试）

- 评估集：56 题（45 常规 + 3 关键词型 + 3 语义型 + 5 结构化/兜底）；
- 三方案同集对比（真实 BGE-M3）：关键词 Hit@5=86.3% / **向量 Hit@5=100%、MRR=1.000** / 混合 Hit@5=100%、MRR=0.909；
- 诚实结论：混合检索未优于纯向量（mock 嵌入下两路冗余；真实模型下关键词噪声拉低 MRR），价值在召回兜底与关键词型精确保障；
- 详见 [retrieval_eval_report.md](retrieval_eval_report.md)。

## 3. RAG 生成评估（76 题，真实 DeepSeek + 真实 BGE-M3）

| 类型 | 通过率 | 检查内容 |
|---|---|---|
| kb 有依据/不同表达/引用（51） | 92.2% | 生成 + 来源真实 + [N] 引用编号有效 |
| no_basis 无依据（10） | 80% | 拒答"无法确认"、无来源、不编造 |
| induce 诱导编造（5） | 100% | 不执行注入规则（引用攻击话术+拒绝标记判定法） |
| insufficient 信息不足（5） | 100% | 不随意下结论 |
| needs_db / fallback（5） | 100% | 结构化模板 / 兜底 |
| 异常率 / 平均延迟 | 0 / 1100ms | |

详见 [rag_eval_report.md](rag_eval_report.md)（含评估方法局限：模型输出方差需多次运行或人工抽检）。

## 4. 性能测试（Locust，独立于 pytest）

三类压测与瓶颈分解见 [performance_report.md](performance_report.md)。摘要：
业务 API P99≤28ms / 检索 P99=490ms（Embedding 294ms）/ 完整 RAG P99=2.7s（LLM 1.24s）。

## 5. 运行方式

```bash
# 全部测试（测试环境强制 mock LLM、真实 Embedding；无数据库时部分用例自动跳过）
PYTHONIOENCODING=utf-8 .venv\Scripts\python -m pytest -q

# 端到端冒烟（需服务运行）
PYTHONIOENCODING=utf-8 .venv\Scripts\python -m scripts.smoke_api

# 检索评估 / RAG 评估 / 压测
PYTHONIOENCODING=utf-8 .venv\Scripts\python -m scripts.eval_retrieval
PYTHONIOENCODING=utf-8 .venv\Scripts\python -m scripts.eval_rag
.venv\Scripts\python -m locust -f loadtests/locustfile.py --headless --users 20 --run-time 2m --host http://127.0.0.1:8000
```

## 6. 覆盖缺口（如实声明）

- 真实模型生成质量无自动化断言（需 LLM 裁判 + 人工抽检，评估报告已说明局限）；
- 无 admin 功能（未实现，故无对应测试）；
- 压测未覆盖高并发边界（如 200 并发）与长时间稳定性（>2 分钟）；
- 无注册登录流程测试（v1 为受控测试令牌）。
